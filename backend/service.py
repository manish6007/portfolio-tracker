"""Service layer: ORM <-> dict conversion and the computation pipeline."""
import calendar
from datetime import date

import analytics
import capmix
import ledger
from db import (SOURCE_BROKER, SOURCE_CAS, SOURCE_OPENING,
                ExpenseEntry, Holding, IncomeEntry, Loan, Lot,
                Owner, Policy, RealisedTrade, RecurringOutflow,
                Transaction, get_setting, get_targets)


def holding_to_dict(h):
    return {
        "id": h.id,
        "owner": h.owner.name if h.owner else "Unassigned",
        "owner_id": h.owner_id,
        "asset_class": h.asset_class,
        "name": h.name,
        "identifier": h.identifier,
        "units": h.units,
        "avg_cost": h.avg_cost,
        "manual_value": h.manual_value,
        "value_date": h.value_date,
        "last_price": h.last_price,
        "price_date": h.price_date,
        "rate": h.rate,
        "start_date": h.start_date,
        "meta": h.meta_dict(),
        "notes": h.notes,
    }


def holding_out(h):
    """JSON-safe holding dict enriched with computed value/cost/bucket."""
    return enrich_holding(holding_to_dict(h))


def enrich_holding(d):
    """The computed half of holding_out, for a dict that already exists."""
    # How much of this holding is equity, and which company sizes that
    # equity sits in -- carried per holding so the Portfolio page can offer
    # an override on anything the classifier could not read.
    d["current_value"] = round(analytics.holding_value(d), 2)
    d["invested"] = round(analytics.holding_cost(d), 2)
    d["bucket"] = analytics.holding_bucket(d)
    equity_fraction = analytics.holding_splits(d).get("equity", 0.0)
    d["has_equity"] = equity_fraction > 0
    split, source = capmix.cap_split(d)
    d["cap_split"] = split
    d["cap_source"] = source
    d["cap_label"] = capmix.describe(split, source)
    value = d["current_value"]
    d["splits"] = {k: round(value * v, 2)
                   for k, v in analytics.holding_splits(d).items()}
    d["has_split"] = analytics.has_split(d)
    d["term"] = analytics.holding_term(d)[0]
    for k in ("value_date", "price_date", "start_date"):
        d[k] = d[k].isoformat() if d[k] else None
    return d


# ---- re-importing a statement -------------------------------------------
# What a statement is allowed to overwrite. Everything else on a holding --
# the company-size tag, a hand-built equity/debt split, notes, the owner it
# was filed under -- was authored by a person and survives every re-import.
CAS_META_KEYS = ("isin", "folio", "registrar", "nominee", "purchase_date",
                 "category", "source")


def holding_identity(meta, identifier=""):
    """What makes an imported holding the same holding as last quarter.

    Names are useless for this: every fund exists four times over as
    Direct/Regular crossed with Growth/IDCW, which is the whole reason
    matching.py exists. The ISIN names the scheme and the folio names the
    account, and one person can hold the same scheme in two folios, so it
    takes both. A statement that omits the folio still matches on the ISIN
    rather than creating a second copy.
    """
    isin = str((meta or {}).get("isin") or "").strip().upper()
    folio = str((meta or {}).get("folio") or "").strip().upper()
    return isin, folio, str(identifier or "").strip().upper()


def find_imported_holding(session, owner_id, asset_class, meta, identifier=""):
    """The existing holding a statement or tradebook row refers to, or None.

    An ISIN names a *scheme or company*; a folio names an *account*, and one
    folio routinely holds several schemes of the same fund house. Treating
    the folio as identity meant three Motilal Oswal schemes sharing a folio
    all nominated each other, and every row after the first imported as a
    duplicate.

    So the handles are tried in order of how exactly they identify the
    thing, and a weaker one is only consulted when the stronger finds
    nothing at all. That last part matters: holdings recorded before the app
    ever saw an ISIN carry none, and an ISIN-only match would file every one
    of them a second time.

    Scoped to the owner throughout: the same holding under two names is two
    holdings, and merging them would move somebody's money.
    """
    isin, folio, ident = holding_identity(meta, identifier)
    rows = session.query(Holding).filter(
        Holding.owner_id == owner_id,
        Holding.asset_class == asset_class).all()
    parsed = [(h, holding_identity(h.meta_dict(), h.identifier)) for h in rows]
    for handle, index in ((isin, 0), (ident, 2), (folio, 1)):
        if not handle:
            continue
        pool = parsed
        if index and isin:
            # The row names an ISIN, so a holding that names a *different*
            # one is a different thing however its other fields line up --
            # three schemes of one fund house share a folio and sometimes a
            # code. Only holdings that record no ISIN can be matched by the
            # weaker handles, which is exactly the pre-ISIN case this
            # fallback exists for.
            pool = [(h, ide) for h, ide in parsed if not ide[0]]
        found = [(h, ide) for h, ide in pool if ide[index] == handle]
        if not found:
            continue
        if index == 0 and folio:
            # Same scheme, possibly in more than one account. The folio is
            # what tells those apart.
            exact = [h for h, ide in found if ide[1] == folio]
            if exact:
                return exact[0]
            unfiled = [h for h, ide in found if not ide[1]]
            return unfiled[0] if len(unfiled) == 1 else None
        return found[0][0] if len(found) == 1 else None
    return None


def merge_import_meta(existing_meta, incoming_meta):
    """Statement facts over the top of what the user authored."""
    merged = dict(existing_meta or {})
    for key in CAS_META_KEYS:
        if key in (incoming_meta or {}):
            merged[key] = incoming_meta[key]
    merged["source"] = SOURCE_CAS
    return merged


# What a statement is allowed to replace when it restates a holding. A CAS
# row supersedes what the last CAS wrote, and it also supersedes the opening
# lot the migration synthesised -- that lot exists only to stand in for a
# position whose purchases were never recorded, which is precisely what the
# statement now supplies. Leaving it in place added the stated position on
# top of the placeholder and doubled the units of every fund imported.
IMPORT_OWNED_LOTS = (SOURCE_CAS, SOURCE_OPENING)


def replace_imported_rows(session, holding):
    """Drop what the last import of this holding produced.

    Never touches what a person entered: a purchase recorded in the journal
    or a transaction typed by hand is theirs, not the importer's to remove.
    This is what makes re-importing the same statement idempotent instead of
    doubling every position.
    """
    session.query(Transaction).filter(
        Transaction.holding_id == holding.id,
        Transaction.source == SOURCE_CAS).delete(synchronize_session=False)
    session.query(Lot).filter(
        Lot.holding_id == holding.id,
        Lot.source.in_(IMPORT_OWNED_LOTS)).delete(synchronize_session=False)
    session.expire(holding, ["transactions", "lots"])


def set_imported_position(session, holding, units, avg_cost, when):
    """Carry a statement's stated position, without double-counting.

    A statement states the *whole* position and the average it was bought at,
    and both are authoritative. It does not reliably carry the purchase
    history behind them -- a statement for one period opens with a balance
    whose purchases happened before it starts -- so one lot is recorded
    rather than a history invented from a partial file.

    The subtlety is a holding the user has also traded in the journal. Those
    purchases are real, they carry a stop-loss and a sleeve the statement
    knows nothing about, and they are *already inside* the stated total --
    the broker counted them too. Adding the stated position on top of them
    turned eight shares into eleven.

    So only the remainder is recorded, priced so the blended average comes
    out at the average the statement reports. What the user entered keeps its
    detail; the total comes out at what the broker says it is.

    Returns (lot, conflict). `conflict` is the units by which hand-entered
    purchases exceed the stated position -- a real disagreement about what is
    held, reported rather than silently resolved.
    """
    units = float(units or 0)
    if units <= 0:
        holding.units = 0.0
        return None, 0.0
    kept = [lot for lot in holding.lots if lot.remaining > 1e-9]
    kept_units = sum(float(lot.remaining) for lot in kept)
    kept_cost = sum(float(lot.remaining)
                    * ledger.lot_cost_per_unit(lot.units, lot.price,
                                               lot.charges)
                    for lot in kept)
    residual = round(units - kept_units, 6)
    if residual <= 1e-6:
        # The statement says there is no more than what is already recorded.
        # Its own lot would be zero or negative, so none is added; a genuine
        # shortfall is handed back for the caller to report.
        return None, round(kept_units - units, 6)
    total_cost = units * float(avg_cost or 0)
    price = max((total_cost - kept_cost) / residual, 0.0)
    lot = ledger.add_lot(
        session, holding, when, residual, price, source=SOURCE_CAS,
        notes="Position as reported by the imported statement."
              + (" Recorded as the part not already entered by hand."
                 if kept_units else ""))
    return lot, 0.0


# ---- replaying a broker's tradebook -------------------------------------
def clear_book(session, holding, ref):
    """Remove what one tradebook wrote for a holding, and nothing else.

    Scoped by `ref` so importing a second broker's book does not delete the
    first's -- a share held at two brokers is one holding with parcels from
    both, and wiping "everything imported" would halve it.
    """
    lots = session.query(Lot).filter(Lot.holding_id == holding.id,
                                     Lot.ref == ref).all()
    ids = [lot.id for lot in lots]
    if ids:
        session.query(RealisedTrade).filter(
            RealisedTrade.lot_id.in_(ids)).delete(synchronize_session=False)
    session.query(RealisedTrade).filter(
        RealisedTrade.holding_id == holding.id,
        RealisedTrade.ref == ref).delete(synchronize_session=False)
    session.query(Transaction).filter(
        Transaction.holding_id == holding.id,
        Transaction.ref == ref).delete(synchronize_session=False)
    session.query(Lot).filter(Lot.holding_id == holding.id,
                              Lot.ref == ref).delete(synchronize_session=False)
    session.expire(holding, ["transactions", "lots"])


def replay_trades(session, holding, trades, ref, sleeve=""):
    """Put a broker's trades through the ledger, oldest first.

    A tradebook is the one source that says *when* a share was bought, which
    is what a purchase parcel needs and what nothing else in the app has for
    shares. Buys become parcels; sells consume them oldest-first and book
    what they realised, exactly as the journal does, so the two produce the
    same kind of record from different evidence.

    New parcels inherit `sleeve` -- the one the position was already filed
    under. A book knows nothing about core and satellite, and importing one
    used to reset that judgement to nothing across the whole portfolio.

    Returns (parcels, closed, skipped, merged). `skipped` counts sales the
    ledger could not honour -- a book that opens mid-history sells shares it
    never records buying, and inventing them would be worse than saying so.
    """
    parcels = closed = skipped = merged = 0
    for t in sorted(trades, key=lambda x: x["date"]):
        try:
            when = date.fromisoformat(t["date"])
        except ValueError:
            continue
        units, price = float(t["units"]), float(t["price"])
        charges = float(t.get("charges") or 0)
        if t["type"] == "buy" and _already_recorded(holding, when, units,
                                                    price, ref):
            # The user typed this trade in before the book arrived. It is
            # one purchase, not two, and the one they entered carries a
            # stop-loss and a sleeve the book knows nothing about -- so
            # theirs is kept and the book's copy is dropped.
            merged += 1
            continue
        if t["type"] == "buy":
            lot = ledger.add_lot(session, holding, when, units, price,
                                 charges=charges, source=SOURCE_BROKER,
                                 notes="From an imported tradebook.",
                                 sleeve=sleeve)
            lot.ref = ref
            session.flush()
            session.add(Transaction(
                holding_id=holding.id, date=when, type="buy",
                amount=units * price + charges, units=units,
                lot_id=lot.id, source=SOURCE_BROKER, ref=ref))
            parcels += 1
        else:
            try:
                made = ledger.sell(session, holding, when, units, price,
                                   charges=charges, reason="other",
                                   source=SOURCE_BROKER,
                                   notes="From an imported tradebook.")
            except ledger.LedgerError:
                skipped += 1
                continue
            txn = Transaction(holding_id=holding.id, date=when, type="sell",
                              amount=units * price - charges, units=units,
                              source=SOURCE_BROKER, ref=ref)
            session.add(txn)
            session.flush()
            for trade in made:
                trade.ref = ref
                trade.txn_id = txn.id
            closed += len(made)
    ledger.recompute(holding)
    return parcels, closed, skipped, merged


# How far a price may sit from the book's and still be the same trade. A
# broker's own export and a figure typed off a contract note differ by
# rounding, never by a percent.
SAME_TRADE_PRICE = 0.005


def _already_recorded(holding, when, units, price, ref):
    """True when this purchase is already on the holding from another source.

    Matched on the day, the quantity and the price together: one of those
    coinciding is common, all three is the same trade.
    """
    for lot in holding.lots:
        if lot.ref == ref or lot.source == SOURCE_OPENING:
            continue
        if lot.date != when or abs(float(lot.units) - units) > 1e-6:
            continue
        base = float(lot.price) or price
        if abs(base - price) <= max(base, price) * SAME_TRADE_PRICE:
            return True
    return False


def reconcile_opening(session, holding, target_units):
    """Shrink the placeholder parcel by whatever the book now accounts for.

    A tradebook covering the last eight months is history, not news: the
    shares it records buying are already inside the position the app shows.
    Replaying it on top would count them twice.

    The opening parcel stands in for purchases that were never recorded, so
    once the book records some of them, the placeholder is worth exactly the
    remainder. Where the book covers everything it empties; where the book
    starts mid-history it keeps what came before, still undated because
    nothing says when that was.

    Emptied rather than deleted: a sale may already have been booked against
    the placeholder, and that realised trade points back at it. Dropping the
    row would either break the link or quietly erase a closed trade, so the
    parcel stays at zero, exactly as any other fully sold one does.

    Returns the units the book claims beyond what is held -- a real
    disagreement, handed back rather than absorbed.
    """
    from db import SOURCE_OPENING as _OPENING
    opening = [lot for lot in holding.lots if lot.source == _OPENING]
    others = sum(float(lot.remaining) for lot in holding.lots
                 if lot.source != _OPENING and lot.remaining > 1e-9)
    residual = round(float(target_units) - others, 6)
    for lot in opening[1:]:
        lot.remaining = 0.0
    if residual <= 1e-6:
        for lot in opening[:1]:
            lot.remaining = 0.0
        ledger.recompute(holding)
        return round(-residual, 6) if residual < -1e-6 else 0.0
    if opening:
        opening[0].units = max(float(opening[0].units), residual)
        opening[0].remaining = residual
    else:
        lot = ledger.add_lot(
            session, holding, holding.value_date or date.today(), residual,
            holding.avg_cost or 0.0, source=_OPENING,
            notes="Position held before the imported tradebook begins.")
        lot.date_known = 0
    ledger.recompute(holding)
    return 0.0


def loan_to_dict(loan):
    return {
        "id": loan.id, "owner_id": loan.owner_id, "name": loan.name,
        "kind": loan.kind,
        "principal_outstanding": loan.principal_outstanding,
        "annual_rate": loan.annual_rate, "emi": loan.emi,
        "tenure_months_remaining": loan.tenure_months_remaining,
        "notes": loan.notes,
    }


def recurring_to_dict(r):
    freq = r.frequency or "monthly"
    amount = r.amount if r.amount else r.amount_monthly
    return {
        "id": r.id, "name": r.name, "kind": r.kind,
        "amount": amount, "frequency": freq,
        "next_due": r.next_due.isoformat() if r.next_due else None,
        "frequency_label": analytics.FREQUENCY_LABELS.get(freq, freq),
        "amount_monthly": r.amount_monthly,
        "amount_annual": analytics.to_annual(amount, freq),
        "counts_as_investment": bool(r.counts_as_investment),
    }


def policy_to_dict(p):
    return {
        "id": p.id, "owner_id": p.owner_id, "kind": p.kind,
        "insurer": p.insurer, "name": p.name,
        "policy_number": p.policy_number, "covered": p.covered,
        "sum_assured": p.sum_assured, "premium": p.premium,
        "frequency": p.frequency,
        "frequency_label": analytics.FREQUENCY_LABELS.get(p.frequency,
                                                          p.frequency),
        "annual_premium": analytics.to_annual(p.premium, p.frequency),
        "next_due": p.next_due.isoformat() if p.next_due else None,
        "valid_till": p.valid_till.isoformat() if p.valid_till else None,
        "nominee": p.nominee, "notes": p.notes,
    }


def load_all(session):
    holdings = [holding_to_dict(h) for h in session.query(Holding).all()]
    loans = [loan_to_dict(loan) for loan in session.query(Loan).all()]
    recurring = [recurring_to_dict(r)
                 for r in session.query(RecurringOutflow).all()]
    policies = [policy_to_dict(p) for p in session.query(Policy).all()]
    return holdings, loans, recurring, policies


def _window_start(months):
    """First day of the calendar month `months - 1` back from this one."""
    today = date.today()
    y, m = today.year, today.month - (months - 1)
    while m <= 0:
        m += 12
        y -= 1
    return date(y, m, 1)


def _month_span(rows, today=None):
    """How many months of spending these entries actually represent.

    Not a count of calendar months: the month in progress is only partly
    over, and counting it whole made logging an expense *reduce* the monthly
    average. Six days into September, one ₹10,000 entry turned ₹30,000/month
    into ₹20,000/month -- the number moved the opposite way to the spending,
    and the FI target fell with it.

    So completed months count as one each and the current month counts as
    the fraction of it that has elapsed, which is the span the entries have
    actually had a chance to accumulate over.

    Floored at one month when that is all there is. A few days of entries
    scaled up to a full month is arithmetic nobody asked for -- ₹10,000 on
    the 6th is not ₹50,000 of monthly spending, it is ₹10,000 so far.
    """
    today = today or date.today()
    months = {(r.date.year, r.date.month) for r in rows}
    if not months:
        return 0
    span = 0.0
    for year, month in months:
        if (year, month) == (today.year, today.month):
            days = calendar.monthrange(year, month)[1]
            span += today.day / days
        else:
            span += 1.0
    return max(span, 1.0)


def cashflow_summary(session, recurring, months=3):
    since = _window_start(months)
    inc_rows = session.query(IncomeEntry).filter(IncomeEntry.date >= since).all()
    exp_rows = session.query(ExpenseEntry).filter(ExpenseEntry.date >= since).all()
    return analytics.monthly_cashflow(
        sum(e.amount for e in inc_rows), sum(e.amount for e in exp_rows),
        months, recurring,
        income_months=_month_span(inc_rows),
        expense_months=_month_span(exp_rows))


def float_setting(session, key, default=0.0):
    try:
        return float(get_setting(session, key, "") or default)
    except ValueError:
        return default


def build_suggestion_context(session, holdings, loans, cashflow):
    agg = analytics.aggregate(holdings)
    targets = get_targets(session)
    drift = analytics.allocation_drift(agg["by_bucket"], targets)
    liquid = analytics.liquid_total(holdings)
    idle_savings = sum(analytics.holding_value(h) for h in holdings
                       if h["asset_class"] == "savings")
    ctx = {
        "surplus_m": cashflow["surplus_m"],
        "emergency_fund_target": float_setting(session, "emergency_fund_target"),
        "liquid_assets": liquid,
        "drift": drift,
        "loans": loans,
        "idle_savings": idle_savings,
        "savings_threshold": float_setting(session, "savings_float"),
    }
    for key in ("tax_80c_used", "tax_80ccd1b_used"):
        raw = get_setting(session, key, "")
        if raw != "":
            try:
                ctx[key] = float(raw)
            except ValueError:
                pass
    return ctx, drift, targets, agg


def full_pipeline(session):
    holdings, loans, recurring, policies = load_all(session)
    cashflow = cashflow_summary(session, recurring)
    ctx, drift, targets, agg = build_suggestion_context(
        session, holdings, loans, cashflow)
    sugg = analytics.suggestions(ctx)
    warnings = analytics.reconcile(
        recurring, loans, holdings, policies=policies,
        income_basis=get_setting(session, "income_basis", ""),
        income_monthly=cashflow["income_m"])
    insurance = analytics.insurance_gap(
        policies, cashflow["income_m"] * 12,
        sum(loan["principal_outstanding"] for loan in loans))
    # Cap mix runs on the equity *inside* each holding, not the holding --
    # a balanced advantage fund contributes only its equity sleeve, and a
    # debt fund none of itself.

    def equity_share(h):
        return (analytics.holding_splits(h).get("equity", 0.0)
                * analytics.holding_value(h))

    caps = capmix.cap_mix(holdings, equity_share)
    return {"holdings": holdings, "loans": loans, "recurring": recurring,
            "cap_mix": caps,
            "policies": policies, "insurance": insurance,
            "warnings": warnings,
            "cashflow": cashflow, "drift": drift, "targets": targets,
            "suggestions": sugg, "agg": agg}


# Which database files have been checked. Doing this on every request meant
# a query -- sometimes a commit -- before serving /api/meta.
_owner_checked = set()


def forget_owner_check(session):
    """Re-check on the next request -- used after a wipe removes the owner."""
    _owner_checked.discard(session.get_bind().url.database)


def ensure_default_owner(session):
    key = session.get_bind().url.database
    if key in _owner_checked:
        return
    if not session.query(Owner).count():
        session.add(Owner(name="Me"))
        session.commit()
    _owner_checked.add(key)
