"""Portfolio Tracker API + static frontend server.

Run:  uvicorn main:app --reload --port 8000
The built React app (frontend/dist) is served at /, the API under /api.
"""
import csv
import io
import json
import os
from datetime import date, datetime

from fastapi import (FastAPI, File, Form, HTTPException, Response,
                     UploadFile)
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from contextvars import ContextVar

import analytics
import calculators
import config as config_mod
import db as db_mod
import export as export_mod
import family_record as fr_mod
import fi as fi_mod
import importers as imp_mod
import matching
import netlog
import paths
import pricing
import profiles as profiles_mod
import schemas
import service
from db import (ASSET_CLASS_LABELS, ASSET_CLASSES, ExpenseEntry, Goal,
                Holding,
                IncomeEntry, Loan, Owner, Policy, RecurringOutflow, Snapshot,
                Transaction, get_session, get_setting, get_targets,
                set_setting)

app = FastAPI(title="Portfolio Tracker")

# There is no login, by design: this app answers to whoever is at the
# machine. That only holds while "whoever is at the machine" cannot mean a
# web page in another tab. Two things keep it true:
#
#   * no cross-origin access. In production the frontend is served from this
#     same origin, so CORS is not needed at all; wildcard CORS would let any
#     site the user has open read /api/summary or call /api/reset.
#   * no other host. A request whose Host header is not loopback is either
#     DNS rebinding or an exposure to the network, and an origin check alone
#     does not stop the first.
DEV = os.environ.get("PORTFOLIO_DEV") == "1"
if DEV:
    # `npm run dev` serves the UI from another port, so development -- and
    # only development -- allows that one origin.
    app.add_middleware(CORSMiddleware,
                       allow_origins=["http://localhost:5173",
                                      "http://127.0.0.1:5173"],
                       allow_credentials=True,
                       allow_methods=["*"], allow_headers=["*"])


@app.exception_handler(RequestValidationError)
async def _readable_validation_error(request, exc):
    """One sentence per problem, instead of FastAPI's nested error objects.

    The UI shows `detail` straight to the user, so a list of dicts would
    reach them as noise. Field name plus what was wrong is enough to fix it.
    """
    parts = []
    for err in exc.errors():
        where = ".".join(str(p) for p in err["loc"]
                         if p not in ("body", "query"))
        msg = err["msg"].replace("Value error, ", "")
        parts.append("%s: %s" % (where, msg) if where else msg)
    return JSONResponse({"detail": "; ".join(parts)}, status_code=422)


LOCAL_HOSTS = {"localhost", "127.0.0.1", "[::1]", "::1"}
WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


@app.middleware("http")
async def _local_only(request, call_next):
    host = (request.headers.get("host") or "").rsplit(":", 1)[0]
    if host and host not in LOCAL_HOSTS and not DEV:
        return JSONResponse(
            {"detail": "This app serves the machine it runs on. Open it at "
                       "http://localhost:8000."}, status_code=421)
    # Sec-Fetch-Site is set by the browser and cannot be forged by script, so
    # it is a free CSRF defence on anything that changes data. Non-browser
    # callers (curl, scripts) send no such header and are unaffected.
    site = request.headers.get("sec-fetch-site")
    if request.method in WRITE_METHODS and site and site != "same-origin":
        return JSONResponse(
            {"detail": "Cross-site requests cannot change your data."},
            status_code=403)
    return await call_next(request)

_amfi_cache = {"data": {}, "at": None}
# NAVs change daily. `at` was recorded and never read, so a long-running
# process served week-old prices to the scheme search forever.
AMFI_CACHE_HOURS = 12
MAX_UPLOAD_BYTES = 20_000_000
_started = datetime.now()


def code_changed_since_start():
    """True when a .py file on disk is newer than this running process.

    Updating is `git pull` plus `npm run build`, and the built frontend is
    read from disk on every request -- so the new UI appears immediately
    while the Python process keeps running the old code. The result is a new
    page calling an endpoint that does not exist yet, which looks like a
    network fault and is not one. Cheap to check, and it turns a confusing
    404 into "restart the server".
    """
    here = os.path.dirname(os.path.abspath(__file__))
    try:
        newest = max(os.path.getmtime(os.path.join(here, f))
                     for f in os.listdir(here) if f.endswith(".py"))
    except (OSError, ValueError):        # pragma: no cover - unreadable dir
        return False
    return newest > _started.timestamp()


# Which profile the request in hand is for. A cookie carries it rather than a
# header, so plain download links -- the export PDF, the locator sheet --
# reach the right portfolio without every call site remembering to pass it.
PROFILE_COOKIE = "profile"
_profile = ContextVar("profile", default=profiles_mod.DEFAULT_ID)


@app.middleware("http")
async def _select_profile(request, call_next):
    token = _profile.set(request.cookies.get(PROFILE_COOKIE)
                         or profiles_mod.DEFAULT_ID)
    opened = []
    sessions_token = _sessions.set(opened)
    failed = False
    try:
        response = await call_next(request)
        failed = response.status_code >= 400
        return response
    except Exception:
        failed = True
        raise
    finally:
        _close_sessions(opened, failed)
        _sessions.reset(sessions_token)
        _profile.reset(token)


# Sessions opened while serving one request. Endpoints call db() and mostly
# close it themselves, but several raise HTTPException between the two -- a
# 404 lookup, a validation error -- and those paths leaked a connection every
# time. Registering here means the request cannot end without them closed,
# whichever way it ends, and closing twice is harmless.
#
# A Depends(get_db) would be the idiomatic FastAPI shape. This does the same
# job without touching all 49 endpoints, and keeps them plain functions that
# can be called directly from tests.
_sessions = ContextVar("sessions", default=None)


def db():
    s = get_session(profiles_mod.path_for(_profile.get()))
    service.ensure_default_owner(s)
    open_now = _sessions.get()
    if open_now is not None:
        open_now.append(s)
    return s


def _close_sessions(opened, failed):
    for s in opened:
        try:
            if failed:
                s.rollback()             # never leave a half-applied write
        except Exception:                # pragma: no cover - best effort
            pass
        finally:
            s.close()


def parse_date(v):
    if not v:
        return None
    if isinstance(v, date):
        return v
    return datetime.strptime(str(v)[:10], "%Y-%m-%d").date()


# ---------------- meta ----------------
@app.get("/api/meta")
def meta():
    return {"asset_classes": ASSET_CLASSES,
            "asset_class_labels": ASSET_CLASS_LABELS,
            "buckets": ["equity", "debt", "gold", "real_estate", "cash", "other"],
            "stale_backend": code_changed_since_start(),
            "started": _started.isoformat(timespec="seconds")}


# ---------------- summary ----------------
@app.get("/api/summary")
def summary():
    s = db()
    data = service.full_pipeline(s)
    agg = data["agg"]
    total_liab = sum(loan["principal_outstanding"] for loan in data["loans"])
    snaps = s.query(Snapshot).order_by(Snapshot.date).all()
    # full_pipeline already loaded and valued every holding; re-querying and
    # re-valuing them here doubled the work on the app's busiest endpoint.
    holdings_out = [service.enrich_holding(dict(h)) for h in data["holdings"]]
    resp = {
        "total_assets": round(agg["total"], 2),
        "total_liabilities": round(total_liab, 2),
        "net_worth": round(agg["total"] - total_liab, 2),
        "by_class": {k: round(v, 2) for k, v in agg["by_class"].items()},
        "by_owner": {k: round(v, 2) for k, v in agg["by_owner"].items()},
        "by_bucket": {k: round(v, 2) for k, v in agg["by_bucket"].items()},
        "drift": data["drift"],
        "targets": data["targets"],
        "targets_customized": bool(get_setting(s, "targets", "")),
        "cashflow": data["cashflow"],
        "suggestions": data["suggestions"],
        "holdings": holdings_out,
        "loans": data["loans"],
        "recurring": data["recurring"],
        "lumpy_upcoming": analytics.upcoming_lumpy(data["recurring"]),
        "warnings": data["warnings"],
        "unrealised": analytics.unrealised_positions(data["holdings"]),
        "cap_mix": data["cap_mix"],
        "policies": data["policies"],
        "insurance": data["insurance"],
        "snapshots": [{"date": sn.date.isoformat(), "net_worth": sn.net_worth,
                       "total_assets": sn.total_assets,
                       "total_liabilities": sn.total_liabilities}
                      for sn in snaps],
    }
    s.close()
    return resp


# ---------------- owners ----------------
@app.get("/api/owners")
def list_owners():
    s = db()
    out = [{"id": o.id, "name": o.name} for o in s.query(Owner).all()]
    s.close()
    return out


@app.post("/api/owners")
def add_owner(body: schemas.OwnerIn):
    s = db()
    name = body.name
    if s.query(Owner).filter(Owner.name == name).first():
        raise HTTPException(409, "owner exists")
    o = Owner(name=name)
    s.add(o)
    s.commit()
    out = {"id": o.id, "name": o.name}
    s.close()
    return out


@app.delete("/api/owners/{oid}")
def delete_owner(oid: int):
    s = db()
    o = s.get(Owner, oid)
    if not o:
        raise HTTPException(404, "not found")
    if s.query(Holding).filter(Holding.owner_id == oid).count():
        raise HTTPException(409, "owner has holdings; reassign them first")
    s.delete(o)
    s.commit()
    s.close()
    return {"ok": True}


# ---------------- holdings ----------------
HOLDING_FIELDS = ("asset_class", "name", "identifier", "units", "avg_cost",
                  "manual_value", "last_price", "rate", "notes")


def apply_holding_payload(h, payload):
    for f in HOLDING_FIELDS:
        if f in payload and payload[f] is not None:
            setattr(h, f, payload[f])
    if "owner_id" in payload and payload["owner_id"]:
        h.owner_id = int(payload["owner_id"])
    for f in ("start_date", "value_date", "price_date"):
        if f in payload:
            setattr(h, f, parse_date(payload[f]))
    if "meta" in payload and isinstance(payload["meta"], dict):
        # Merge, don't clobber: setting a bucket must not wipe an MF's
        # category. An empty value clears that key.
        merged = h.meta_dict()
        for k, v in payload["meta"].items():
            if v in (None, ""):
                merged.pop(k, None)
            else:
                merged[k] = v
        h.meta = json.dumps(merged)


def _restate_from_money(h, money):
    """Re-derive units and cost from what a holding cost and is worth.

    The month after a SIP, what you can see is a larger invested figure and
    a larger value; how many units the instalments bought at that day's NAV
    is nobody's idea of a memorable number. Both figures are honoured
    exactly, and the units follow.
    """
    invested = money.get("invested")
    value = money.get("current_value")
    if invested is None:
        invested = (h.units or 0.0) * (h.avg_cost or 0.0)
    if value is None:
        value = (h.units or 0.0) * (h.last_price or 0.0)

    # A price is only a real per-unit price when it is not the whole value
    # wearing a price's clothes, and not the placeholder the app writes at
    # creation (last_price = avg_cost). Deriving units from either of those
    # invents a unit count out of the purchase price.
    price = h.last_price or 0.0
    usable = (price and price < analytics.PLACEHOLDER_UNIT_COST
              and abs(price - (h.avg_cost or 0.0)) > 0.005)
    if usable and value:
        # A real per-unit price: the value says how many units there are.
        h.units = value / price
    elif h.units:
        # No usable price, so the unit count cannot move. Both numbers are
        # still honoured -- the price absorbs the change instead.
        h.last_price = value / h.units
        h.price_date = date.today()
    if h.units:
        h.avg_cost = invested / h.units
    h.value_date = date.today()


@app.get("/api/holdings")
def list_holdings():
    s = db()
    out = [service.holding_out(h) for h in s.query(Holding).all()]
    s.close()
    return out


@app.post("/api/holdings")
def add_holding(body: schemas.HoldingIn):
    s = db()
    payload = body.model_dump(exclude_unset=True)
    h = Holding(owner_id=body.owner_id or s.query(Owner).first().id,
                asset_class=body.asset_class, name=body.name)
    apply_holding_payload(h, payload)
    if not h.value_date:
        h.value_date = date.today()
    if h.asset_class in analytics.UNIT_PRICED and not h.last_price:
        h.last_price = h.avg_cost or 0.0
        h.price_date = date.today()
    s.add(h)
    s.commit()
    out = service.holding_out(h)
    s.close()
    return out


@app.put("/api/holdings/{hid}")
def update_holding(hid: int, body: schemas.HoldingUpdate):
    s = db()
    payload = body.model_dump(exclude_unset=True)
    money = {k: payload.pop(k) for k in ("invested", "current_value")
             if k in payload}
    h = s.get(Holding, hid)
    if not h:
        raise HTTPException(404, "not found")
    apply_holding_payload(h, payload)
    if money:
        _restate_from_money(h, money)
    if "manual_value" in payload:
        h.value_date = date.today()
    if "last_price" in payload:
        h.price_date = date.today()
    s.commit()
    out = service.holding_out(h)
    s.close()
    return out


@app.delete("/api/holdings/{hid}")
def delete_holding(hid: int):
    s = db()
    h = s.get(Holding, hid)
    if not h:
        raise HTTPException(404, "not found")
    s.delete(h)
    s.commit()
    s.close()
    return {"ok": True}


def _price_for_row(row, navs):
    """The per-unit price for a template row, from the file or from AMFI.

    A scheme code is enough: the NAV is already downloaded, so nobody has to
    type a price in beside it.
    """
    given = float(row.get("last_price") or 0)
    if given:
        return given
    info = navs.get(str(row.get("identifier") or "").strip())
    return info["nav"] if info else 0.0


@app.post("/api/holdings/import")
async def import_holdings(file: UploadFile):
    s = db()
    text = (await file.read()).decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    owners = {o.name: o.id for o in s.query(Owner).all()}
    # Fetched once for the whole file, so a row carrying a scheme code needs
    # no price and no unit count -- what it cost and what it is worth are
    # enough, and those are the two numbers people can actually read off a
    # screen.
    navs, _, _ = _amfi_navs()
    added, errors, derived = 0, [], 0
    for i, r in enumerate(reader):
        try:
            oname = (r.get("owner") or "Me").strip()
            if oname not in owners:
                o = Owner(name=oname)
                s.add(o)
                s.commit()
                owners[oname] = o.id
            cls = (r.get("asset_class") or "").strip()
            if cls not in ASSET_CLASSES:
                raise ValueError("bad asset_class %r" % cls)
            units, avg_cost = float(r.get("units") or 0), \
                float(r.get("avg_cost") or 0)
            price = 0.0
            if cls in analytics.UNIT_PRICED:
                price = _price_for_row(r, navs)
                before = units
                units, avg_cost, price = imp_mod.derive_quantities(
                    units, avg_cost, price,
                    float(r.get("invested") or 0),
                    float(r.get("current_value") or 0))
                units, avg_cost = units or 0.0, avg_cost or 0.0
                if units and not before:
                    derived += 1
            h = Holding(
                owner_id=owners[oname], asset_class=cls,
                name=(r.get("name") or "").strip(),
                identifier=(r.get("identifier") or "").strip(),
                units=units, avg_cost=avg_cost,
                manual_value=float(r.get("manual_value") or 0),
                rate=float(r.get("rate") or 0),
                start_date=parse_date((r.get("start_date") or "").strip()),
                value_date=date.today(),
                meta=json.dumps({
                    k: v for k, v in (
                        ("category", (r.get("category") or "").strip()),
                        ("bucket", (r.get("bucket") or "").strip()),
                        ("maturity_date", (r.get("maturity_date") or "").strip()),
                        ("purchase_date", (r.get("purchase_date") or "").strip()),
                        ("nominee", (r.get("nominee") or "").strip()),
                    ) if v}))
            if cls in analytics.UNIT_PRICED:
                h.last_price = price or h.avg_cost
                h.price_date = date.today()
                if not h.units:
                    raise ValueError(
                        "no units, and none could be worked out. Give units, "
                        "or give current_value with either last_price or an "
                        "identifier AMFI prices.")
            if not h.name:
                raise ValueError("name required")
            s.add(h)
            added += 1
        except (ValueError, TypeError, KeyError) as ex:
            errors.append("row %d: %s" % (i + 2, ex))
    s.commit()
    s.close()
    return {"added": added, "errors": errors,
            "units_derived": derived}


# ---------------- guided import ----------------
@app.get("/api/import/fields")
def import_fields():
    return {"mappable": imp_mod.MAPPABLE,
            "aliases": {k: v[:6] for k, v in imp_mod.COLUMN_ALIASES.items()}}


def _cas_preview(data, password, owner):
    """The CAS half of the import preview.

    Split out so import_preview stays one readable flow: pick the format,
    parse it, resolve what can be resolved, hand back rows for confirmation.
    """
    try:
        text = imp_mod.extract_cas_text(data, password)
    except PermissionError as exc:
        raise HTTPException(401, str(exc))
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    rows, notes, layout = imp_mod.parse_cas_any(text, owner=owner)
    # A CAS names funds by ISIN and never by AMFI code, so resolve the
    # codes here: without one, NAV refresh cannot price these holdings.
    resolved = 0
    if rows:
        index = pricing.fetch_amfi_isin_index()
        for r in rows:
            code = index.get((r.get("isin") or "").upper())
            if code:
                r["scheme_code"] = code
                resolved += 1
        if index and resolved < len(rows):
            notes = notes + ["%d of %d schemes could not be matched to an "
                             "AMFI code, so their NAV will not refresh "
                             "automatically. Set the code by hand on the "
                             "Portfolio page."
                             % (len(rows) - resolved, len(rows))]
        elif not index:
            notes = notes + ["AMFI could not be reached, so scheme codes "
                             "were not resolved. Prices from the "
                             "statement are used; run Refresh prices "
                             "later once codes are set."]
    return {"source": "cas", "layout": layout, "headers": [],
            "mapping": {}, "mappable": imp_mod.MAPPABLE, "rows": rows,
            "skipped": [], "notes": notes,
            "asset_class": "mutual_fund"}


@app.post("/api/import/preview")
async def import_preview(file: UploadFile = File(...),
                         asset_class: str = Form("stock"),
                         owner: str = Form("Me"),
                         password: str = Form(""),
                         mapping: str = Form("")):
    """Read a broker export or a CAS and show what would be imported.

    Nothing is written here. The caller confirms the rows (and can correct
    the column mapping) before anything reaches the portfolio.
    """
    data = await file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "That file is %d MB. Imports are capped at "
                                 "%d MB; a CAS or broker export is far "
                                 "smaller than this."
                            % (len(data) // 1_000_000,
                               MAX_UPLOAD_BYTES // 1_000_000))
    name = (file.filename or "").lower()
    if name.endswith(".pdf"):
        return _cas_preview(data, password, owner)
    try:
        headers, records = imp_mod.read_table(data, name)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    if not headers:
        raise HTTPException(400, "No readable rows in that file.")
    if mapping:
        try:
            chosen = {k: v for k, v in json.loads(mapping).items() if v}
        except ValueError:
            raise HTTPException(400, "mapping must be JSON")
    else:
        chosen = imp_mod.sniff_columns(headers)
    rows, skipped = imp_mod.build_rows(records, chosen,
                                       asset_class=asset_class, owner=owner)
    notes = []
    unmapped = [f for f in ("units",) if f not in chosen]
    if unmapped:
        notes.append("No quantity column was recognised — pick it below, "
                     "otherwise every row is skipped.")
    if "avg_cost" not in chosen and "invested" not in chosen:
        notes.append("Neither an average price nor an invested value was "
                     "recognised, so cost and profit will read as zero.")
    return {"source": "table", "headers": headers, "mapping": chosen,
            "mappable": imp_mod.MAPPABLE, "rows": rows, "skipped": skipped,
            "notes": notes, "asset_class": asset_class}


def _add_import_txns(s, holding, rows):
    """Store the transaction history a detailed CAS carries.

    It is what turns XIRR from an estimate into the real money-weighted
    return, so it is kept rather than thrown away after valuing the holding.
    A row that does not carry a usable date is dropped, not guessed at.
    """
    kept = 0
    for t in rows:
        try:
            when = date.fromisoformat((t.get("date") or "")[:10])
        except ValueError:
            continue
        amount = float(t.get("amount") or 0)
        if amount <= 0 or t.get("type") not in ("buy", "sell", "dividend"):
            continue
        s.add(Transaction(holding_id=holding.id, date=when, type=t["type"],
                          amount=amount, units=float(t.get("units") or 0)))
        kept += 1
    return kept


@app.post("/api/import/commit")
def import_commit(body: schemas.ImportCommit):
    """Create holdings from rows the user has just reviewed."""
    s = db()
    owners = {o.name: o.id for o in s.query(Owner).all()}
    default_owner = body.owner or s.query(Owner).first().name
    added, txns, errors = 0, 0, []
    for i, r in enumerate(row.model_dump() for row in body.rows):
        try:
            oname = (r.get("owner") or default_owner).strip()
            if oname not in owners:
                o = Owner(name=oname)
                s.add(o)
                s.commit()
                owners[oname] = o.id
            cls = r.get("asset_class") or "stock"
            if cls not in ASSET_CLASSES:
                raise ValueError("bad asset_class %r" % cls)
            meta = {}
            if r.get("purchase_date"):
                meta["purchase_date"] = r["purchase_date"]
            if cls == "mutual_fund":
                meta["category"] = r.get("category") or "equity"
            for k in ("isin", "registrar", "nominee"):
                if r.get(k):
                    meta[k] = r[k]
            # The AMFI code is what prices a fund, so it wins the identifier
            # slot; the folio stays in meta where the family record finds it.
            ident = (r.get("identifier") or "").strip()
            if r.get("scheme_code"):
                if ident:
                    meta["folio"] = ident
                ident = r["scheme_code"]
            h = Holding(owner_id=owners[oname], asset_class=cls,
                        name=(r.get("name") or "").strip(),
                        identifier=ident,
                        units=float(r.get("units") or 0),
                        avg_cost=float(r.get("avg_cost") or 0),
                        last_price=float(r.get("last_price") or 0),
                        price_date=date.today(), value_date=date.today(),
                        meta=json.dumps(meta))
            if not h.name:
                raise ValueError("name required")
            s.add(h)
            s.flush()                 # need the id to hang transactions off
            txns += _add_import_txns(s, h, r.get("transactions") or [])
            added += 1
        except (ValueError, TypeError) as exc:
            errors.append("row %d: %s" % (i + 1, exc))
    s.commit()
    s.close()
    return {"added": added, "transactions": txns, "errors": errors}


# ---------------- transactions (optional, powers XIRR) ----------------
@app.get("/api/holdings/{hid}/transactions")
def list_txns(hid: int):
    s = db()
    out = [{"id": t.id, "date": t.date.isoformat(), "type": t.type,
            "amount": t.amount, "units": t.units}
           for t in s.query(Transaction).filter(Transaction.holding_id == hid)
           .order_by(Transaction.date)]
    s.close()
    return out


@app.post("/api/holdings/{hid}/transactions")
def add_txn(hid: int, body: schemas.TransactionIn):
    s = db()
    if not s.get(Holding, hid):
        raise HTTPException(404, "holding not found")
    t = Transaction(holding_id=hid, date=parse_date(body.date),
                    type=body.type, amount=body.amount, units=body.units)
    s.add(t)
    s.commit()
    s.close()
    return {"ok": True}


@app.get("/api/xirr")
def portfolio_xirr():
    """Overall + per-holding XIRR from recorded transactions."""
    s = db()
    today = date.today()
    all_flows = []
    per = []
    for h in s.query(Holding).all():
        txns = list(h.transactions)
        if not txns:
            continue
        flows = []
        for t in txns:
            sign = -1 if t.type in ("buy", "contribution") else 1
            flows.append((t.date, sign * t.amount))
        cur = analytics.holding_value(service.holding_to_dict(h), today)
        flows.append((today, cur))
        all_flows.extend(flows[:-1])
        r = analytics.xirr(flows)
        per.append({"holding_id": h.id, "name": h.name,
                    "xirr_pct": round(r * 100, 2) if r is not None else None})
        all_flows.append((today, cur))
    overall = analytics.xirr(all_flows) if all_flows else None
    s.close()
    return {"overall_pct": round(overall * 100, 2) if overall is not None else None,
            "holdings": per}


# ---------------- prices ----------------
@app.post("/api/prices/refresh")
def refresh_prices():
    s = db()
    navs, by_isin, amfi_status = pricing.fetch_amfi()
    mf_updated = stock_updated = 0
    failed, mf_failed, mf_placeholders = [], [], []
    if navs:
        _amfi_cache["data"], _amfi_cache["at"] = navs, datetime.now()
        for h in s.query(Holding).filter(Holding.asset_class == "mutual_fund"):
            ident = str(h.identifier or "").strip()
            info = navs.get(ident)
            if not info:
                # A fund imported from a CAS is identified by its folio, and
                # by its ISIN if AMFI was unreachable that day. Resolve the
                # scheme code now and keep it, so this fund prices itself
                # from here on instead of failing every refresh.
                meta = json.loads(h.meta or "{}")
                code = by_isin.get((meta.get("isin") or "").upper())
                if code and navs.get(code):
                    info = navs[code]
                    if ident and ident != code:
                        meta["folio"] = ident
                        h.meta = json.dumps(meta)
                    h.identifier = code
            if info and analytics.price_would_break_value(
                    service.holding_to_dict(h), info["nav"]):
                # Pricing this would replace a value with a NAV and wipe out
                # the holding. It is reported instead, and priced once the
                # real unit count is in.
                mf_placeholders.append(h.name)
            elif info:
                h.last_price, h.price_date = info["nav"], info["date"]
                mf_updated += 1
            else:
                mf_failed.append(h.name)
    stocks = list(s.query(Holding).filter(Holding.asset_class == "stock"))
    # A holding with no ticker is a different problem from a lookup that
    # failed, and lumping them together sent people to check their internet
    # connection when the fix was to fill in a field.
    no_ticker = [h.name for h in stocks if not (h.identifier or "").strip()]
    priceable = [h for h in stocks if (h.identifier or "").strip()]
    # Fetched together and de-duplicated: the same stock held by two people
    # is one price, and thirty holdings should not mean thirty waits.
    prices = pricing.fetch_stock_prices([h.identifier for h in priceable])
    for h in priceable:
        px, pd_ = prices.get(h.identifier.strip(), (None, None))
        if px and analytics.price_would_break_value(
                service.holding_to_dict(h), px):
            mf_placeholders.append(h.name)
        elif px:
            h.last_price, h.price_date = px, pd_
            stock_updated += 1
        else:
            failed.append("%s (%s)" % (h.name, h.identifier.strip()))
    s.commit()
    s.close()
    # The reason the last attempt failed, so the answer is in the message
    # rather than three clicks away on the Privacy page.
    reason = next((e["detail"] for e in netlog.entries()
                   if e["outcome"] in ("failed", "refused", "unreadable")), "")
    # A price feed that answers with nothing is not a broken connection and
    # not a wrong ticker, and telling those apart is the difference between
    # "check your symbols" and "wait for the feed". Only said when every
    # lookup came back empty, which is what a feed-side failure looks like.
    stock_reason = ""
    if failed and not stock_updated:
        empties = [e for e in netlog.entries() if e["outcome"] == "empty"]
        if len(empties) >= len(failed):
            stock_reason = (
                "Every lookup reached Yahoo and came back with no price, so "
                "this is the feed rather than your tickers. Try again later; "
                "Privacy \u2192 Test connection confirms it.")
    return {"amfi_reachable": amfi_status == pricing.AMFI_OK,
            "amfi_status": amfi_status, "offline": config_mod.offline(),
            "mf_updated": mf_updated, "mf_failed": mf_failed,
            "mf_placeholders": mf_placeholders,
            "stocks_updated": stock_updated, "stock_failed": failed,
            "stock_no_ticker": no_ticker, "reason": reason,
            "stock_reason": stock_reason}


# A recorded price is only worth comparing against today's NAV when it is
# actually a recent NAV. Most of the time it is the average purchase cost --
# the app writes last_price = avg_cost when a holding is created, and a fund
# bought five years ago is legitimately far from its purchase price. Treating
# that as evidence rejected every correct match.
OBSERVED_NAV_DAYS = 45


def _observed_nav(h):
    """The holding's price if it is a real observed NAV, else None."""
    price, cost = h.last_price or 0.0, h.avg_cost or 0.0
    if not price or not h.price_date:
        return None
    if abs(price - cost) < 0.005:        # the placeholder written at creation
        return None
    if (date.today() - h.price_date).days > OBSERVED_NAV_DAYS:
        return None                      # too old to say anything about today
    return price


@app.get("/api/holdings/unit-placeholders")
def list_unit_placeholders():
    """Holdings recorded as one unit costing their whole invested amount.

    Each needs the real unit count. Everything else about them -- what was
    invested, which scheme -- is right, so the fix is one number per row.
    """
    s = db()
    out = []
    for h in s.query(Holding).all():
        d = service.holding_to_dict(h)
        if not analytics.is_unit_placeholder(d):
            continue
        price = h.last_price or 0.0
        # A price that is still the holding's whole value cannot turn a
        # value into units -- dividing a value by itself gives 1 back.
        priceable = bool(price) and price < analytics.PLACEHOLDER_UNIT_COST
        out.append({"holding_id": h.id, "name": h.name,
                    "asset_class": h.asset_class,
                    "identifier": h.identifier or "",
                    "invested": round(h.avg_cost or 0.0, 2),
                    "last_price": round(price, 4),
                    "priceable": priceable})
    s.close()
    return {"holdings": out}


@app.post("/api/holdings/set-units")
def set_real_units(body: schemas.SetUnits):
    """Replace a placeholder unit count with the real one.

    The invested amount is the part that was never in doubt, so it is held
    constant and the cost per unit is derived from it. Anything else would
    silently rewrite what was actually put in.
    """
    s = db()
    applied, errors = 0, []
    for item in body.units:
        h = s.get(Holding, item.holding_id)
        if not h:
            errors.append("holding %d no longer exists" % item.holding_id)
            continue
        invested = (h.avg_cost or 0.0) * (h.units or 0.0)
        units = item.units
        if units is None:
            # What it is worth today, divided by today's price. Easier to
            # find than a unit count, and exactly as accurate -- but only
            # once the recorded price is a real per-unit price. While it is
            # still the holding's whole value, dividing by it just gives 1
            # back, so that is refused rather than quietly done.
            price = h.last_price or 0.0
            if not price or price >= analytics.PLACEHOLDER_UNIT_COST:
                errors.append(
                    "%s: its recorded price of %s is a total, not a price "
                    "per unit, so units cannot be worked out from a value. "
                    "Give it a scheme code first so it has a real NAV, or "
                    "enter the units directly."
                    % (h.name, analytics.inr(price)))
                continue
            units = item.current_value / price
        h.units = units
        h.avg_cost = invested / units if units else invested
        applied += 1
    s.commit()
    s.close()
    return {"applied": applied, "errors": errors}


@app.get("/api/amfi/suggest-codes")
def suggest_scheme_codes(plan: str = matching.DEFAULT_PLAN,
                         option: str = matching.DEFAULT_OPTION):
    """Candidate AMFI codes for every fund that has none.

    Without a code a fund cannot be priced, and nobody knows their scheme
    codes -- so a portfolio typed in by hand has a dozen funds stuck at
    their purchase price forever. This proposes the matches; the user
    applies them.
    """
    navs, _, status = _amfi_navs()
    if status != pricing.AMFI_OK:
        return {"amfi_status": status, "holdings": []}
    s = db()
    out = []
    for h in s.query(Holding).filter(Holding.asset_class == "mutual_fund"):
        if matching.looks_like_scheme_code(h.identifier) \
                and str(h.identifier).strip() in navs:
            continue
        observed = _observed_nav(h)
        sugg = matching.suggest(h.name, navs, want_plan=plan,
                                want_option=option, known_price=observed)
        out.append({"holding_id": h.id, "name": h.name,
                    "identifier": h.identifier or "",
                    "last_price": h.last_price or 0.0,
                    "compared_against": observed, **sugg})
    s.close()
    return {"amfi_status": status, "holdings": out}


@app.get("/api/amfi/candidates")
def amfi_candidates(q: str, plan: str = matching.DEFAULT_PLAN,
                    option: str = matching.DEFAULT_OPTION):
    """Search AMFI by name, ranked the same way the suggestions are.

    For the funds whose recorded name is a placeholder -- "HDFC MF via
    Zerodha Coin" -- nothing can match it, and the only person who knows
    what it really is, is the one looking at the screen.
    """
    navs, _, status = _amfi_navs()
    if status != pricing.AMFI_OK:
        return {"amfi_status": status, "candidates": []}
    return {"amfi_status": status,
            "candidates": matching.rank(q, navs, want_plan=plan,
                                        want_option=option, limit=8)}


@app.post("/api/amfi/apply-codes")
def apply_scheme_codes(body: schemas.ApplyCodes):
    """Set the chosen scheme code on each fund and price it straight away."""
    navs, _, status = _amfi_navs()
    s = db()
    applied, errors, derived, renamed = 0, [], [], []
    for item in body.assignments:
        h = s.get(Holding, item.holding_id)
        if not h:
            errors.append("holding %d no longer exists" % item.holding_id)
            continue
        info = navs.get(item.scheme_code)
        if not info:
            errors.append("%s is not an AMFI scheme code" % item.scheme_code)
            continue
        # The folio is not lost: it moves to meta, where the family record
        # and the CAS reconciliation still need it.
        meta = h.meta_dict()
        ident = (h.identifier or "").strip()
        if ident and ident != item.scheme_code:
            meta["folio"] = ident
            h.meta = json.dumps(meta)
        h.identifier = item.scheme_code
        if item.adopt_name:
            # A recorded name like "HDFC MF via Zerodha Coin (scheme name
            # TBC)" is a note to self, not a fund. Replacing it is offered,
            # never done quietly.
            h.name = info["name"][:200]
            renamed.append(item.scheme_code)
        # A holding recorded as "1 unit costing the whole invested amount"
        # carries its market value in last_price. Overwriting that with a
        # NAV turns a five-lakh holding into two hundred rupees, so the
        # units are derived from the value instead -- arithmetic on numbers
        # the user gave us, not a guess.
        # Derive units only while the recorded price is still the holding's
        # value. Once a NAV has already flattened it, that price is a NAV
        # too, and dividing one NAV by another invents a unit count -- 559
        # over 759 is not 0.736 units of anything. Those stay flagged for
        # the user to supply the real figure.
        if (h.last_price
                and analytics.price_would_break_value(
                    service.holding_to_dict(h), info["nav"])
                and not analytics.is_unit_placeholder(
                    service.holding_to_dict(h))):
            market_value = h.last_price
            invested = h.avg_cost or 0.0
            h.units = market_value / info["nav"]
            h.avg_cost = invested / h.units if h.units else invested
            derived.append(h.name)
        h.last_price, h.price_date = info["nav"], info["date"]
        applied += 1
    s.commit()
    s.close()
    return {"applied": applied, "errors": errors,
            "derived_units": derived, "renamed": len(renamed)}


def _amfi_navs():
    """Today's NAV table, downloaded at most once every AMFI_CACHE_HOURS."""
    fresh = (_amfi_cache["at"] is not None
             and (datetime.now() - _amfi_cache["at"]).total_seconds()
             < AMFI_CACHE_HOURS * 3600)
    if _amfi_cache["data"] and fresh:
        return _amfi_cache["data"], _amfi_cache.get("by_isin", {}), \
            pricing.AMFI_OK
    navs, by_isin, status = pricing.fetch_amfi()
    if navs:                              # keep yesterday's rather than none
        _amfi_cache["data"], _amfi_cache["by_isin"] = navs, by_isin
        _amfi_cache["at"] = datetime.now()
    elif _amfi_cache["data"]:
        return _amfi_cache["data"], _amfi_cache.get("by_isin", {}), \
            pricing.AMFI_OK
    return navs, by_isin, status


@app.get("/api/amfi/search")
def amfi_search(q: str):
    navs, _, _ = _amfi_navs()
    hits = pricing.search_amfi(navs, q)
    return [{"code": c, "name": i["name"], "nav": i["nav"],
             "date": i["date"].isoformat()} for c, i in hits]


# ---------------- income / expenses / recurring ----------------
def _entry_rows(s, model):
    rows = (s.query(model).order_by(model.date.desc()).limit(500).all())
    owners = {o.id: o.name for o in s.query(Owner).all()}
    out = []
    for e in rows:
        d = {"id": e.id, "owner": owners.get(e.owner_id, "?"),
             "owner_id": e.owner_id, "date": e.date.isoformat(),
             "category": e.category, "amount": e.amount, "notes": e.notes}
        if hasattr(e, "fixed"):
            d["fixed"] = bool(e.fixed)
        out.append(d)
    return out


@app.get("/api/income")
def list_income():
    s = db()
    out = _entry_rows(s, IncomeEntry)
    s.close()
    return out


@app.post("/api/income")
def add_income(body: schemas.EntryIn):
    s = db()
    s.add(IncomeEntry(owner_id=body.owner_id or s.query(Owner).first().id,
                      date=parse_date(body.date) or date.today(),
                      category=body.category or "Salary",
                      amount=body.amount,
                      notes=body.notes or ""))
    s.commit()
    s.close()
    return {"ok": True}


@app.delete("/api/income/{eid}")
def delete_income(eid: int):
    s = db()
    e = s.get(IncomeEntry, eid)
    if e:
        s.delete(e)
        s.commit()
    s.close()
    return {"ok": True}


@app.get("/api/expenses")
def list_expenses():
    s = db()
    out = _entry_rows(s, ExpenseEntry)
    s.close()
    return out


@app.post("/api/expenses")
def add_expense(body: schemas.EntryIn):
    s = db()
    s.add(ExpenseEntry(owner_id=body.owner_id or s.query(Owner).first().id,
                       date=parse_date(body.date) or date.today(),
                       category=body.category or "Household",
                       amount=body.amount,
                       fixed=1 if body.fixed else 0,
                       notes=body.notes or ""))
    s.commit()
    s.close()
    return {"ok": True}


@app.delete("/api/expenses/{eid}")
def delete_expense(eid: int):
    s = db()
    e = s.get(ExpenseEntry, eid)
    if e:
        s.delete(e)
        s.commit()
    s.close()
    return {"ok": True}


@app.get("/api/recurring")
def list_recurring():
    s = db()
    out = [service.recurring_to_dict(r)
           for r in s.query(RecurringOutflow).all()]
    s.close()
    return out


@app.post("/api/recurring")
def add_recurring(body: schemas.RecurringIn):
    s = db()
    kind, freq = body.kind, body.frequency
    # accept either the per-payment amount or a legacy monthly figure
    amount = (body.amount if body.amount is not None
              else body.amount_monthly * analytics.FREQUENCY_MONTHS[freq])
    invests = (body.counts_as_investment if body.counts_as_investment
               is not None else kind == "sip")
    r = RecurringOutflow(
        name=body.name, kind=kind, amount=amount, frequency=freq,
        next_due=parse_date(body.next_due),
        amount_monthly=analytics.to_monthly(amount, freq),
        counts_as_investment=1 if invests else 0)
    s.add(r)
    s.commit()
    out = service.recurring_to_dict(r)
    s.close()
    return out


@app.put("/api/recurring/{rid}")
def update_recurring(rid: int, body: schemas.RecurringUpdate):
    s = db()
    payload = body.model_dump(exclude_unset=True)
    r = s.get(RecurringOutflow, rid)
    if not r:
        raise HTTPException(404, "not found")
    for f in ("name", "kind"):
        if f in payload and payload[f] is not None:
            setattr(r, f, payload[f])
    if payload.get("frequency"):
        if payload["frequency"] not in analytics.FREQUENCY_MONTHS:
            raise HTTPException(400, "bad frequency %r" % payload["frequency"])
        r.frequency = payload["frequency"]
    if "next_due" in payload:
        r.next_due = parse_date(payload["next_due"])
    if payload.get("amount") is not None:
        r.amount = float(payload["amount"])
    elif payload.get("amount_monthly") is not None:
        # A monthly-equivalent figure has to be scaled up to a per-payment
        # one, not passed through to_monthly and re-divided by the frequency
        # below -- that gave a quarterly item a third of the right amount.
        freq = r.frequency or "monthly"
        r.amount = (float(payload["amount_monthly"])
                    * analytics.FREQUENCY_MONTHS.get(freq, 1))
    r.amount_monthly = analytics.to_monthly(r.amount, r.frequency or "monthly")
    if "counts_as_investment" in payload:
        r.counts_as_investment = 1 if payload["counts_as_investment"] else 0
    s.commit()
    out = service.recurring_to_dict(r)
    s.close()
    return out


@app.delete("/api/recurring/{rid}")
def delete_recurring(rid: int):
    s = db()
    r = s.get(RecurringOutflow, rid)
    if r:
        s.delete(r)
        s.commit()
    s.close()
    return {"ok": True}


# ---------------- loans ----------------
@app.get("/api/loans")
def list_loans():
    s = db()
    out = [service.loan_to_dict(loan) for loan in s.query(Loan).all()]
    s.close()
    return out


@app.post("/api/loans")
def add_loan(body: schemas.LoanIn):
    s = db()
    loan = Loan(owner_id=body.owner_id or s.query(Owner).first().id,
                name=body.name, kind=body.kind,
                principal_outstanding=body.principal_outstanding,
                annual_rate=body.annual_rate, emi=body.emi,
                tenure_months_remaining=body.tenure_months_remaining,
                notes=body.notes or "")
    s.add(loan)
    s.commit()
    out = service.loan_to_dict(loan)
    s.close()
    return out


@app.put("/api/loans/{lid}")
def update_loan(lid: int, body: schemas.LoanUpdate):
    s = db()
    payload = body.model_dump(exclude_unset=True)
    loan = s.get(Loan, lid)
    if not loan:
        raise HTTPException(404, "not found")
    for f in ("name", "kind", "principal_outstanding", "annual_rate", "emi",
              "tenure_months_remaining", "notes"):
        if f in payload and payload[f] is not None:
            setattr(loan, f, payload[f])
    s.commit()
    out = service.loan_to_dict(loan)
    s.close()
    return out


@app.delete("/api/loans/{lid}")
def delete_loan(lid: int):
    s = db()
    loan = s.get(Loan, lid)
    if loan:
        s.delete(loan)
        s.commit()
    s.close()
    return {"ok": True}


@app.post("/api/loans/prepay-vs-invest")
def prepay_vs_invest(body: schemas.PrepayIn):
    res = analytics.prepay_vs_invest(
        body.principal, body.annual_rate, body.emi, body.lumpsum,
        body.invest_return_pct)
    if res is None:
        raise HTTPException(400, "EMI does not cover the monthly interest")
    return {k: (round(v, 2) if isinstance(v, (int, float)) else v)
            for k, v in res.items()}


@app.get("/api/loans/{lid}/schedule")
def loan_schedule(lid: int):
    s = db()
    loan = s.get(Loan, lid)
    if not loan:
        raise HTTPException(404, "not found")
    rows, months = analytics.amortization_schedule(
        loan.principal_outstanding, loan.annual_rate, loan.emi)
    s.close()
    return {"months_to_close": months,
            "total_interest": round(sum(r["interest"] for r in rows), 2),
            "schedule": [{k: round(v, 2) for k, v in r.items()}
                         for r in rows[:360]]}


# ---------------- snapshots ----------------
@app.post("/api/snapshots")
def take_snapshot():
    s = db()
    data = service.full_pipeline(s)
    agg = data["agg"]
    total_liab = sum(loan["principal_outstanding"] for loan in data["loans"])
    existing = s.query(Snapshot).filter(Snapshot.date == date.today()).first()
    if existing:
        s.delete(existing)
    s.add(Snapshot(date=date.today(), total_assets=agg["total"],
                   total_liabilities=total_liab,
                   net_worth=agg["total"] - total_liab,
                   by_class_json=json.dumps(agg["by_class"]),
                   by_owner_json=json.dumps(agg["by_owner"])))
    s.commit()
    s.close()
    return {"ok": True}


# ---------------- settings ----------------
SETTING_KEYS = ("emergency_fund_target", "savings_float", "tax_80c_used",
                "tax_80ccd1b_used", "age", "income_basis",
                "inflation_pct", "step_up_pct", "swr_multiple",
                "family_record_enabled", "household_name",
                "record_stored_at", "record_password_held_by")


@app.get("/api/targets/presets")
def targets_presets(age: int = None):
    """Suggested target allocations. Age-based card appears when age given."""
    s = db()
    if age is None:
        raw = get_setting(s, "age", "")
        if raw:
            try:
                age = int(float(raw))
            except ValueError:
                age = None
    s.close()
    if age is not None and not (10 <= age <= 100):
        raise HTTPException(400, "age must be between 10 and 100")
    return {"age": age, "presets": analytics.target_presets(age)}


@app.get("/api/settings")
def get_settings():
    s = db()
    out = {"targets": get_targets(s),
           "targets_customized": bool(get_setting(s, "targets", ""))}
    for k in SETTING_KEYS:
        out[k] = get_setting(s, k, "")
    s.close()
    return out


@app.put("/api/settings")
def put_settings(body: schemas.SettingsIn):
    s = db()
    payload = body.model_dump(exclude_unset=True)
    payload.update(body.model_extra or {})
    if "targets" in payload and payload["targets"] is not None:
        set_setting(s, "targets", json.dumps(payload["targets"]))
    for k in SETTING_KEYS:
        if k in payload:
            value = str(payload[k])
            if k == "income_basis":
                # Store the short code whatever the client sent, so an old
                # saved label is rewritten the first time settings are saved
                # rather than living on forever.
                value = analytics.normalise_income_basis(value)
            set_setting(s, k, value)
    s.close()
    return {"ok": True}


# ---------------- insurance ----------------
POLICY_KINDS = ("term", "life", "health", "pa", "ci", "motor", "other")


@app.get("/api/policies")
def list_policies():
    s = db()
    out = [service.policy_to_dict(p) for p in s.query(Policy).all()]
    s.close()
    return out


@app.post("/api/policies")
def add_policy(body: schemas.PolicyIn):
    s = db()
    if body.kind not in POLICY_KINDS:
        raise HTTPException(400, "kind must be one of: %s"
                            % ", ".join(POLICY_KINDS))
    if body.frequency not in analytics.FREQUENCY_MONTHS:
        raise HTTPException(400, "bad frequency %r" % body.frequency)
    p = Policy(owner_id=body.owner_id or s.query(Owner).first().id,
               kind=body.kind, insurer=body.insurer or "", name=body.name,
               policy_number=body.policy_number or "",
               covered=body.covered or "",
               sum_assured=body.sum_assured, premium=body.premium,
               frequency=body.frequency,
               next_due=parse_date(body.next_due),
               valid_till=parse_date(body.valid_till),
               nominee=body.nominee or "", notes=body.notes or "")
    s.add(p)
    s.commit()
    out = service.policy_to_dict(p)
    s.close()
    return out


@app.put("/api/policies/{pid}")
def update_policy(pid: int, body: schemas.PolicyUpdate):
    s = db()
    payload = body.model_dump(exclude_unset=True)
    p = s.get(Policy, pid)
    if not p:
        raise HTTPException(404, "not found")
    for f in ("kind", "insurer", "name", "policy_number", "covered",
              "nominee", "notes", "frequency"):
        if payload.get(f) is not None:
            setattr(p, f, payload[f])
    for f in ("sum_assured", "premium"):
        if payload.get(f) is not None:
            setattr(p, f, float(payload[f]))
    for f in ("next_due", "valid_till"):
        if f in payload:
            setattr(p, f, parse_date(payload[f]))
    s.commit()
    out = service.policy_to_dict(p)
    s.close()
    return out


@app.delete("/api/policies/{pid}")
def delete_policy(pid: int):
    s = db()
    p = s.get(Policy, pid)
    if p:
        s.delete(p)
        s.commit()
    s.close()
    return {"ok": True}


@app.get("/api/insurance")
def insurance_view(income_multiple: float = None, health_floor: float = None):
    """Cover held against cover commonly recommended, plus renewals due."""
    s = db()
    data = service.full_pipeline(s)
    gap = analytics.insurance_gap(
        data["policies"], data["cashflow"]["income_m"] * 12,
        sum(loan["principal_outstanding"] for loan in data["loans"]),
        income_multiple=(income_multiple
                         or analytics.LIFE_COVER_INCOME_MULTIPLE),
        health_floor=(health_floor or analytics.HEALTH_COVER_FLOOR))
    renewals = analytics.upcoming_lumpy(
        [{"name": p["name"], "amount": p["premium"],
          "frequency": p["frequency"], "next_due": p["next_due"],
          "counts_as_investment": False} for p in data["policies"]],
        horizon_months=6)
    s.close()
    return {"policies": data["policies"], "gap": gap, "renewals": renewals}


# ---------------- goals ----------------
def goal_dict(g):
    return {"id": g.id, "name": g.name, "target_year": g.target_year,
            "amount_today": g.amount_today, "inflation_pct": g.inflation_pct,
            "notes": g.notes}


@app.get("/api/goals")
def list_goals():
    s = db()
    out = [goal_dict(g) for g in s.query(Goal).order_by(Goal.target_year).all()]
    s.close()
    return out


@app.post("/api/goals")
def add_goal(body: schemas.GoalIn):
    s = db()
    g = Goal(name=body.name, target_year=body.target_year,
             amount_today=body.amount_today,
             inflation_pct=(body.inflation_pct
                            if body.inflation_pct is not None
                            else fi_mod.DEFAULT_GOAL_INFLATION),
             notes=body.notes or "")
    s.add(g)
    s.commit()
    out = goal_dict(g)
    s.close()
    return out


@app.delete("/api/goals/{gid}")
def delete_goal(gid: int):
    s = db()
    g = s.get(Goal, gid)
    if g:
        s.delete(g)
        s.commit()
    s.close()
    return {"ok": True}


# ---------------- financial independence ----------------
@app.get("/api/fi")
def fi_projection(years: int = 50, inflation_pct: float = None,
                  step_up_pct: float = None, swr_multiple: float = None):
    """FI projection under three equity assumptions, from live data."""
    s = db()
    data = service.full_pipeline(s)
    agg = data["agg"]
    cf = data["cashflow"]

    inflation = (inflation_pct if inflation_pct is not None
                 else service.float_setting(s, "inflation_pct",
                                            fi_mod.DEFAULT_INFLATION))
    step_up = (step_up_pct if step_up_pct is not None
               else service.float_setting(s, "step_up_pct",
                                          fi_mod.DEFAULT_STEP_UP))
    multiple = (swr_multiple if swr_multiple is not None
                else service.float_setting(s, "swr_multiple",
                                           fi_mod.DEFAULT_SWR_MULTIPLE))

    # What is actually invested every month, and what will be once the loan
    # closes. Expenses here already exclude EMI, which is what post-FI
    # spending looks like.
    annual_investment = cf["committed_invest_m"] * 12
    annual_expense = cf["expense_m"] * 12
    payoff_year, freed_emi = fi_mod.loan_payoff_year(
        data["loans"], analytics.amortization_schedule)

    targets = data["targets"]
    kw = dict(target_allocation=targets, inflation_pct=inflation,
              step_up_pct=step_up, swr_multiple=multiple, years=years,
              payoff_year=payoff_year, freed_emi_annual=freed_emi)

    goals = [{"name": g.name, "year": g.target_year,
              "amount_today": g.amount_today,
              "inflation_pct": g.inflation_pct}
             for g in s.query(Goal).order_by(Goal.target_year).all()]
    scen = fi_mod.plan_scenarios(agg["by_bucket"], annual_investment,
                                 annual_expense, goals=goals, **kw)
    impact = fi_mod.goal_impact(agg["by_bucket"], annual_investment,
                                annual_expense, goals, **kw) if goals else None
    coast = fi_mod.coast_fi(agg["by_bucket"], annual_expense,
                            target_allocation=targets, inflation_pct=inflation,
                            step_up_pct=step_up, swr_multiple=multiple,
                            years=years)

    notes = []
    base = next((x for x in scen if x["equity_return_pct"] == 12.0), scen[0])
    if base["years_to_fi"] is not None and not base["survives"]:
        notes.append("At 12%% the corpus is exhausted in year %d -- reaching "
                     "the number is not the same as it lasting. Raise the "
                     "expenses multiple, spend less, or retire later."
                     % base["depleted_year"])
    if annual_expense <= 0:
        notes.append("No expenses recorded, so the FI target is zero and the "
                     "projection is meaningless. Log a month of spending first.")
    if annual_investment <= 0:
        notes.append("No monthly investing recorded, so only existing corpus "
                     "compounds.")
    if payoff_year is None and data["loans"]:
        notes.append("A loan's EMI does not cover its interest, so the payoff "
                     "year could not be computed and no freed EMI is assumed.")
    elif payoff_year:
        notes.append("The loan closes in about %d years; from then on %s/year "
                     "of freed EMI is assumed to be invested."
                     % (payoff_year, analytics.inr(freed_emi)))
    s.close()
    return {
        "assumptions": {
            "inflation_pct": inflation, "step_up_pct": step_up,
            "swr_multiple": multiple, "years": years,
            "returns_pct": fi_mod.DEFAULT_RETURNS,
            "annual_investment": round(annual_investment, 2),
            "annual_expense": round(annual_expense, 2),
            "new_money_allocation_pct": targets,
            "loan_payoff_year": payoff_year,
            "freed_emi_annual": round(freed_emi, 2),
        },
        "fi_number_today": round(annual_expense * multiple, 2),
        "corpus_today": round(agg["total"], 2),
        "scenarios": scen,
        "goals": goals,
        "goal_impact": impact,
        "coast": {"years_to_fi": coast["years_to_fi"]},
        "notes": notes,
    }


# ---------------- calculators ----------------
# Pure what-ifs: nothing here opens a session, because none of it depends on
# what the user owns. That is the point of keeping them off the FI page,
# which is entirely about the real portfolio.
def _calc(fn, **kw):
    """Run a calculator, turning its own complaints into a 400 with the
    sentence it wrote. The models in schemas.py catch the ranges; these are
    the objections only the maths knows about."""
    try:
        return fn(**kw)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/calc/sip")
def calc_sip(body: schemas.SipIn):
    """What a monthly instalment becomes -- or what reaching a target costs.

    Both directions in one endpoint because they are the same plan seen from
    either end, and answering only the first is what makes most SIP
    calculators a toy.
    """
    monthly, target_plan = body.monthly, None
    if body.target is not None:
        target_plan = _calc(
            calculators.sip_for_target, target=body.target,
            annual_return_pct=body.annual_return_pct, years=body.years,
            step_up_pct=body.step_up_pct, lumpsum=body.lumpsum,
            rate_mode=body.rate_mode)
        monthly = target_plan["monthly"]

    result = _calc(calculators.sip, monthly=monthly,
                   annual_return_pct=body.annual_return_pct, years=body.years,
                   step_up_pct=body.step_up_pct, lumpsum=body.lumpsum,
                   inflation_pct=body.inflation_pct, rate_mode=body.rate_mode)
    result["target_plan"] = target_plan
    result["notes"] = calculators.notes(result, "sip")
    return result


@app.post("/api/calc/swp")
def calc_swp(body: schemas.SwpIn):
    """Whether a corpus survives a monthly withdrawal, and what it would take.

    The sustainable figure ships with every answer rather than behind a
    second button: "it runs out in year 14" is only actionable next to the
    amount that would not have.
    """
    result = _calc(calculators.swp, corpus=body.corpus,
                   monthly_withdrawal=body.monthly_withdrawal,
                   annual_return_pct=body.annual_return_pct, years=body.years,
                   step_up_pct=body.step_up_pct,
                   inflation_pct=body.inflation_pct, rate_mode=body.rate_mode)
    result["sustainable"] = _calc(
        calculators.swp_sustainable, corpus=body.corpus,
        annual_return_pct=body.annual_return_pct, years=body.years,
        step_up_pct=body.step_up_pct, rate_mode=body.rate_mode)
    result["notes"] = calculators.notes(result, "swp")
    return result


# ---------------- family record ----------------
def _record_enabled(s):
    return get_setting(s, "family_record_enabled", "") == "1"


@app.get("/api/family-record/status")
def family_record_status():
    s = db()
    data = service.full_pipeline(s)
    missing = [h["name"] for h in data["holdings"]
               if not (h.get("meta") or {}).get("nominee")]
    no_id = [h["name"] for h in data["holdings"]
             if not (h.get("identifier") or "").strip()]
    out = {
        "enabled": _record_enabled(s),
        "encryption_available": True,
        "encryption_error": "",
        "min_password_length": fr_mod.MIN_PASSWORD_LENGTH,
        "holdings": len(data["holdings"]),
        "policies": len(data["policies"]),
        "loans": len(data["loans"]),
        "holdings_without_nominee": missing,
        "holdings_without_identifier": no_id,
        "stored_at": get_setting(s, "record_stored_at", ""),
        "password_held_by": get_setting(s, "record_password_held_by", ""),
    }
    try:
        import pypdf  # noqa: F401
        from cryptography.hazmat.primitives.ciphers import algorithms  # noqa
    except Exception as exc:
        out["encryption_available"] = False
        out["encryption_error"] = (
            "AES-256 is unavailable (%s). Install pypdf and cryptography; "
            "the sealed record will not be written with weaker encryption."
            % type(exc).__name__)
    s.close()
    return out


@app.post("/api/family-record/sealed")
def family_record_sealed(body: schemas.SealedRecordIn):
    """The full record, AES-256 encrypted. The password is never stored."""
    s = db()
    if not _record_enabled(s):
        s.close()
        raise HTTPException(403, "family record is switched off in Settings")
    data = service.full_pipeline(s)
    household = get_setting(s, "household_name", "")
    s.close()
    try:
        pdf = fr_mod.build_sealed_record(
            data["holdings"], data["policies"], data["loans"],
            [h.get("owner") for h in data["holdings"]], household=household)
        enc = fr_mod.encrypt_pdf(pdf, body.password)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except fr_mod.EncryptionUnavailable as exc:
        raise HTTPException(503, str(exc))
    return Response(enc, media_type="application/pdf", headers={
        "Content-Disposition": "attachment; filename=family_record_sealed_%s.pdf"
                               % date.today().isoformat()})


@app.get("/api/family-record/locator")
def family_record_locator():
    """The open one-pager: where the sealed record is, institutions only."""
    s = db()
    if not _record_enabled(s):
        s.close()
        raise HTTPException(403, "family record is switched off in Settings")
    data = service.full_pipeline(s)
    pdf = fr_mod.build_locator_sheet(
        data["holdings"], data["policies"], data["loans"],
        household=get_setting(s, "household_name", ""),
        stored_at=get_setting(s, "record_stored_at", ""),
        password_held_by=get_setting(s, "record_password_held_by", ""))
    s.close()
    return Response(pdf, media_type="application/pdf", headers={
        "Content-Disposition": "attachment; filename=where_our_records_are_%s.pdf"
                               % date.today().isoformat()})


# ---------------- export ----------------
def _fi_for_export(s, data):
    """Compact FI block for the export: assumptions plus the headline result."""
    cf = data["cashflow"]
    annual_expense = cf["expense_m"] * 12
    annual_investment = cf["committed_invest_m"] * 12
    multiple = service.float_setting(s, "swr_multiple",
                                     fi_mod.DEFAULT_SWR_MULTIPLE)
    inflation = service.float_setting(s, "inflation_pct",
                                      fi_mod.DEFAULT_INFLATION)
    step_up = service.float_setting(s, "step_up_pct", fi_mod.DEFAULT_STEP_UP)
    payoff_year, freed = fi_mod.loan_payoff_year(
        data["loans"], analytics.amortization_schedule)
    scen = fi_mod.scenarios(
        data["agg"]["by_bucket"], annual_investment, annual_expense,
        target_allocation=data["targets"], inflation_pct=inflation,
        step_up_pct=step_up, swr_multiple=multiple, years=40,
        payoff_year=payoff_year, freed_emi_annual=freed)
    return {
        "fi_number_today": round(annual_expense * multiple, 2),
        "corpus_today": round(data["agg"]["total"], 2),
        "assumptions": {
            "annual_expense_excludes_emi": True,
            "expense_multiple": multiple,
            "inflation_pct": inflation,
            "sip_step_up_pct": step_up,
            "returns_pct_by_bucket": fi_mod.DEFAULT_RETURNS,
            "new_money_allocated_at": data["targets"],
            "loan_payoff_year": payoff_year,
        },
        "years_to_fi_by_equity_return": {
            str(s_["equity_return_pct"]): s_["years_to_fi"] for s_ in scen},
        "caveat": "Straight-line compounding; ignores sequence-of-returns "
                  "risk and any post-FI change in spending beyond inflation.",
    }


def build_snapshot(privacy: bool):
    s = db()
    data = service.full_pipeline(s)
    snap = export_mod.build_snapshot(
        data["holdings"], data["loans"], data["cashflow"], data["drift"],
        data["suggestions"], data["targets"], privacy_safe=privacy,
        recurring=data["recurring"], warnings=data["warnings"],
        income_basis=get_setting(s, "income_basis", ""),
        fi=_fi_for_export(s, data), insurance=data["insurance"],
        policies=data["policies"])
    s.close()
    return snap


@app.get("/api/export/json")
def export_json(privacy: int = 1):
    return build_snapshot(bool(privacy))


@app.get("/api/export/ai-package")
def export_ai(privacy: int = 1):
    return Response(export_mod.to_ai_package(build_snapshot(bool(privacy))),
                    media_type="text/plain")


@app.get("/api/export/pdf")
def export_pdf(privacy: int = 1):
    pdf = export_mod.to_pdf(build_snapshot(bool(privacy)))
    return Response(pdf, media_type="application/pdf", headers={
        "Content-Disposition":
            "attachment; filename=portfolio_snapshot_%s.pdf"
            % date.today().isoformat()})


# ---------------- where the data is, and what leaves ----------------
@app.get("/api/privacy")
def privacy_state():
    """Everything needed to check the app's claims rather than believe them.

    The real paths on this machine, every outbound request made since the
    app started, and the complete list of hosts it is able to contact.
    """
    return {
        "data_dir": config_mod.data_dir(),
        "data_dir_source": config_mod.data_dir_source(),
        "env_var": config_mod.ENV_DATA_DIR,
        "files": config_mod.data_files(),
        "offline": config_mod.offline(),
        "allowed_hosts": [{"host": h, "purpose": p}
                          for h, p in sorted(netlog.ALLOWED_HOSTS.items())],
        "outbound": netlog.entries(),
        "started": _started.isoformat(timespec="seconds"),
    }


@app.get("/api/privacy/test-connection")
def test_connection():
    """Try each allowed host and say exactly what happened to each."""
    return {"results": pricing.check_hosts(), "offline": config_mod.offline()}


@app.post("/api/privacy/offline")
def set_offline(body: schemas.OfflineIn):
    """Stop the app contacting anything at all.

    Prices then come only from what you type, which is a real cost -- and
    the point: the app keeps working with the network switched off, which is
    the sort of claim a user can check in a minute.
    """
    return {"offline": config_mod.set_offline(body.offline)}


@app.post("/api/privacy/data-dir")
def move_data_dir(body: schemas.DataDirIn):
    """Point the app at a different folder, copying what is already there."""
    try:
        if body.reset:
            config_mod.clear_data_dir()
            db_mod.reset_engines()
            return {"data_dir": config_mod.data_dir(), "copied": []}
        result = config_mod.move_data(body.path)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    db_mod.reset_engines()               # reopen against the new location
    return {"data_dir": config_mod.data_dir(), **result}


# ---------------- profiles ----------------
@app.get("/api/profiles")
def list_profiles():
    """Every profile, and which one this browser is looking at."""
    active = _profile.get()
    known = {p["id"] for p in profiles_mod.list_profiles()}
    return {"active": active if active in known else profiles_mod.DEFAULT_ID,
            "profiles": profiles_mod.list_profiles()}


@app.post("/api/profiles")
def create_profile(body: schemas.ProfileIn):
    try:
        p = profiles_mod.create(body.name, demo=body.demo)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    if body.demo:
        from demo_data import seed
        s = get_session(profiles_mod.path_for(p["id"]))
        service.ensure_default_owner(s)
        seed(s)
        s.close()
    return p


@app.put("/api/profiles/{pid}")
def rename_profile(pid: str, body: schemas.ProfileRename):
    try:
        return profiles_mod.rename(pid, body.name)
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.delete("/api/profiles/{pid}")
def delete_profile(pid: str, body: schemas.ConfirmIn = None,
                   confirm: str = ""):
    """Delete a profile and its data file.

    Deleting takes the whole portfolio with it, so the caller has to send the
    profile's own name back as confirmation -- the same bar as Erase all data.
    It travels in the body: a profile name in the query string ends up in
    browser history and the server's access log.
    """
    confirm = ((body.confirm if body else "") or confirm)
    p = profiles_mod.get(pid)
    if p["id"] != pid:
        raise HTTPException(404, "No such profile.")
    if confirm.strip() != p["name"]:
        raise HTTPException(400, "Type the profile's name to confirm.")
    try:
        profiles_mod.delete(pid)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"ok": True, "deleted": pid}


@app.post("/api/profiles/{pid}/activate")
def activate_profile(pid: str, response: Response):
    """Point this browser at a profile. Others are unaffected."""
    p = profiles_mod.get(pid)
    if p["id"] != pid:
        raise HTTPException(404, "No such profile.")
    response.set_cookie(PROFILE_COOKIE, pid, max_age=60 * 60 * 24 * 365,
                        samesite="lax", path="/")
    return {"active": pid}


# ---------------- demo data ----------------
@app.post("/api/demo-data")
def load_demo():
    from demo_data import seed
    s = db()
    seed(s)
    s.close()
    return {"ok": True}


@app.delete("/api/demo-data")
def clear_demo():
    """Remove everything the demo seeder created (names/notes marked DEMO)."""
    s = db()
    removed = 0
    for model in (Holding, Loan, RecurringOutflow):
        for row in s.query(model).filter(model.name.like("DEMO %")):
            s.delete(row)
            removed += 1
    for model in (IncomeEntry, ExpenseEntry):
        for row in s.query(model).filter(model.notes == "DEMO"):
            s.delete(row)
            removed += 1
    s.commit()
    s.close()
    return {"removed": removed}


@app.post("/api/reset")
def reset_all(body: schemas.ConfirmIn):
    """Wipe ALL data. Requires {"confirm": "ERASE"} to guard against slips."""
    if body.confirm != "ERASE":
        raise HTTPException(400, "pass {\"confirm\": \"ERASE\"} to wipe all data")
    s = db()
    # Policies and goals were missing here, so "erase all data" left them
    # behind pointing at an owner that no longer existed. With foreign_keys
    # ON that is an error rather than a silent orphan -- which is the whole
    # reason for turning the pragma on. Owner goes last: everything else
    # references it.
    for model in (Transaction, Holding, Policy, Goal, Loan, RecurringOutflow,
                  IncomeEntry, ExpenseEntry, Snapshot, Owner):
        s.query(model).delete()
    s.commit()
    service.forget_owner_check(s)     # the default owner just went with it
    service.ensure_default_owner(s)
    s.close()
    return {"ok": True}


# Serve the built React app if present (production single-process mode).
class AppFiles(StaticFiles):
    """Serve the built app so an update is actually seen.

    Without a Cache-Control header a browser applies heuristic caching: it
    invents a freshness lifetime from how old the file is, so a months-old
    index.html gets cached for weeks and the browser stops asking the server
    for it at all. Rebuilding then changes nothing on screen -- the new page
    is served to nobody, because nobody requests it.

    index.html must therefore always be revalidated. Everything under
    assets/ carries a content hash in its filename, so a changed file is a
    changed URL and those can be cached forever.
    """

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        kind = response.headers.get("content-type", "")
        if kind.startswith("text/html"):
            response.headers["Cache-Control"] = "no-cache, must-revalidate"
        elif "assets/" in path:
            response.headers["Cache-Control"] = ("public, max-age=31536000, "
                                                 "immutable")
        return response


DIST = paths.frontend_dist()
if os.path.isdir(DIST):
    app.mount("/", AppFiles(directory=DIST, html=True), name="frontend")
