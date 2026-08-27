"""Pure-python analytics: valuation, allocation, XIRR, surplus, suggestions.

Everything here operates on plain dicts/lists so it can be unit-tested
without streamlit, sqlalchemy, or a database.
"""
from datetime import date

# Which high-level bucket each asset class belongs to (overridable per
# holding via meta["bucket"], and per MF via meta["category"]).
BUCKET_MAP = {
    "mutual_fund": "equity",
    "stock": "equity",
    "gold_physical": "gold",
    "sgb": "gold",
    "gold_etf": "gold",
    "reit": "real_estate",
    "fd": "debt",
    "savings": "cash",
    "epf": "debt",
    "ppf": "debt",
    "nps": "debt",
    "other": "other",
}

MF_CATEGORY_BUCKET = {"equity": "equity", "elss": "equity", "hybrid": "equity",
                      "debt": "debt", "liquid": "cash", "gold": "gold"}

UNIT_PRICED = {"mutual_fund", "stock", "gold_etf", "reit", "sgb", "nps",
               "gold_physical"}
BALANCE_BASED = {"savings", "epf", "ppf", "other"}


# A unit-priced holding entered as "one unit costing the whole invested
# amount" -- what you get when the value is known but the unit count is not.
#
# One unit costing a lot is not enough to identify it: a single share of
# Hitachi Energy India really does cost tens of thousands. What gives it away
# is the *proportion* -- a cost per unit wildly out of line with the price
# per unit. One share bought at ₹38,627 now quoted at ₹33,125 is a holding
# down 14%; "one unit" bought at ₹2,94,000 now quoted at ₹215 is not a
# 99.9% loss, it is a total wearing a price's clothes.
PLACEHOLDER_UNIT_COST = 10000.0
PLACEHOLDER_COST_RATIO = 20.0


def _one_unit_costing_a_lot(h):
    if h.get("asset_class") not in UNIT_PRICED:
        return False
    return (abs((h.get("units") or 0.0) - 1.0) < 1e-9
            and (h.get("avg_cost") or 0.0) >= PLACEHOLDER_UNIT_COST)


def is_unit_placeholder(h):
    """True for a holding whose "1 unit" is really its whole value.

    Judged against the price already recorded, so this answers "is this
    holding's value wrong right now" -- which is only true once a real
    per-unit price has landed on it.
    """
    price = h.get("last_price") or 0.0
    return (_one_unit_costing_a_lot(h) and price > 0
            and (h.get("avg_cost") or 0.0) / price > PLACEHOLDER_COST_RATIO)


def price_would_break_value(h, new_price):
    """Would pricing this holding at new_price destroy its recorded value?

    The other half of the question: before a NAV lands, a placeholder still
    reads correctly, because one times the value is the value. This catches
    it on the way in, while the value can still be turned into units.
    """
    return (_one_unit_costing_a_lot(h) and (new_price or 0) > 0
            and (h.get("avg_cost") or 0.0) / new_price > PLACEHOLDER_COST_RATIO)


# How long a last-known balance may be extrapolated before the number owes
# more to this formula than to reality. Beyond it the balance is held flat
# and the user is asked for a fresh one.
MAX_ACCRUAL_MONTHS = 18


def fd_value(principal, annual_rate_pct, start_date, as_of,
             compounding_per_year=4, maturity_date=None):
    """Quarterly-compounded FD value (bank convention).

    Accrual stops at maturity. A matured deposit is not still earning its
    contracted rate -- the money is sitting in a savings account or was
    renewed at whatever rate applied that day -- and compounding past it
    inflates net worth a little more every day it is left unnoticed.
    """
    if not principal or not start_date or as_of <= start_date:
        return float(principal or 0.0)
    if maturity_date and maturity_date < as_of:
        as_of = maturity_date
        if as_of <= start_date:
            return float(principal)
    years = (as_of - start_date).days / 365.25
    r = annual_rate_pct / 100.0
    n = compounding_per_year
    return principal * (1 + r / n) ** (n * years)


def balance_accrued(balance, annual_rate_pct, value_date, as_of,
                    compounding_per_year=1):
    """Accrual on a last-known balance (PPF/EPF/savings).

    Compounded, like the FD path: PPF and EPF credit interest annually and
    it compounds, so simple interest quietly understates a long-held balance
    by double digits. Extrapolation is capped -- past MAX_ACCRUAL_MONTHS the
    balance stops moving, because the honest answer is that the app no longer
    knows, and a warning asks for a current figure.
    """
    if not balance:
        return 0.0
    if not value_date or as_of <= value_date or not annual_rate_pct:
        return float(balance)
    days = min((as_of - value_date).days,
               int(MAX_ACCRUAL_MONTHS * 365.25 / 12))
    years = days / 365.25
    n = max(int(compounding_per_year or 1), 1)
    return balance * (1 + annual_rate_pct / 100.0 / n) ** (n * years)


def holding_value(h, as_of=None):
    """Current value of a holding dict.

    Expected keys: asset_class, units, avg_cost, manual_value, value_date,
    last_price, rate, start_date.
    """
    as_of = as_of or date.today()
    cls = h.get("asset_class")
    if cls == "fd":
        return fd_value(h.get("avg_cost") or h.get("manual_value") or 0.0,
                        h.get("rate") or 0.0, h.get("start_date"), as_of,
                        maturity_date=_parse_date(
                            (h.get("meta") or {}).get("maturity_date")))
    if cls in BALANCE_BASED:
        return balance_accrued(h.get("manual_value") or 0.0,
                               h.get("rate") or 0.0,
                               h.get("value_date"), as_of)
    if cls in UNIT_PRICED:
        units = h.get("units") or 0.0
        price = h.get("last_price") or 0.0
        if units and price:
            return units * price
        return float(h.get("manual_value") or 0.0)
    return float(h.get("manual_value") or 0.0)


def holding_cost(h):
    cls = h.get("asset_class")
    if cls == "fd":
        return float(h.get("avg_cost") or 0.0)
    if cls in UNIT_PRICED:
        return (h.get("units") or 0.0) * (h.get("avg_cost") or 0.0)
    return float(h.get("manual_value") or 0.0)


def holding_bucket(h):
    meta = h.get("meta") or {}
    if meta.get("bucket"):
        return meta["bucket"]
    if h.get("asset_class") == "mutual_fund":
        cat = (meta.get("category") or "equity").lower()
        return MF_CATEGORY_BUCKET.get(cat, "equity")
    return BUCKET_MAP.get(h.get("asset_class"), "other")


LIQUID_FD_MONTHS = 12


def _months_between(start, end):
    return (end.year - start.year) * 12 + (end.month - start.month)


def _parse_date(value):
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return date.fromisoformat(value.strip()[:10])
        except ValueError:
            return None
    return None


def is_liquid(h, as_of=None, fd_liquid_months=LIQUID_FD_MONTHS):
    """Is this money reachable in an emergency?

    Savings accounts and anything sitting in the cash bucket (liquid funds, or
    a holding the user explicitly re-filed as cash) always count. A fixed
    deposit counts only when it has already matured or matures within
    `fd_liquid_months`: a 5-year tax-saver FD is not emergency money, a
    6-month sweep FD is. An FD with no maturity date recorded is treated as
    locked -- better to under-count the buffer than to claim one that is not
    reachable.
    """
    as_of = as_of or date.today()
    if h.get("asset_class") == "savings" or holding_bucket(h) == "cash":
        return True
    if h.get("asset_class") == "fd":
        maturity = _parse_date((h.get("meta") or {}).get("maturity_date"))
        if maturity:
            return _months_between(as_of, maturity) <= fd_liquid_months
    return False


def liquid_total(holdings, as_of=None, fd_liquid_months=LIQUID_FD_MONTHS):
    as_of = as_of or date.today()
    return sum(holding_value(h, as_of) for h in holdings
               if is_liquid(h, as_of, fd_liquid_months))


# Kinds that come out of payroll rather than being chosen each month.
PAYROLL_KINDS = {"pf", "nps", "esop"}

# Simplified long-term holding periods, in months. Real tax law has more
# cases than this (SGB maturity, post-2023 debt funds, unlisted shares); the
# export says so rather than pretending otherwise.
LONG_TERM_MONTHS_EQUITY = 12
LONG_TERM_MONTHS_OTHER = 24
EQUITY_MF_CATEGORIES = {"equity", "elss", "hybrid"}

BUCKET_KEYS = ("equity", "debt", "gold", "real_estate", "cash", "other")


def holding_splits(h):
    """How this holding's value divides across buckets, as fractions.

    A multi-asset fund is not 100% equity. When meta['splits'] gives
    percentages per bucket they are honoured (normalised to 1); otherwise the
    holding sits entirely in its single bucket.
    """
    meta = h.get("meta") or {}
    raw = meta.get("splits")
    if isinstance(raw, dict) and raw:
        vals = {k: float(v) for k, v in raw.items()
                if k in BUCKET_KEYS and float(v or 0) > 0}
        total = sum(vals.values())
        if total > 0:
            return {k: v / total for k, v in vals.items()}
    return {holding_bucket(h): 1.0}


def has_split(h):
    return len(holding_splits(h)) > 1


# Each check is a small function over the same context and returns the
# warnings it found. A flat 150-line reconcile() grew a branch every time the
# app learned something new; this way adding a check is a local change and
# each one can be tested on its own.
_CHECKS = []


def _check(fn):
    _CHECKS.append(fn)
    return fn


def _names(items, limit=3):
    return ", ".join(h.get("name", "?") for h in items[:limit])


@_check
def _emi_against_loans(ctx):
    emis = [r for r in ctx["recurring"] if r.get("kind") == "emi"]
    loans = ctx["loans"]
    emi_total = sum(r["amount_monthly"] for r in emis)
    loan_emi_total = sum(loan.get("emi") or 0 for loan in loans)
    out = []
    if emis and not loans:
        out.append({
            "level": "warning", "code": "emi_without_loan",
            "message": "%d EMI(s) totalling %s/month are recorded with no loan "
                       "behind them, so the interest rate, outstanding balance "
                       "and remaining tenure are unknown. Add them on the Loans "
                       "page -- prepay-vs-invest and any review depend on the "
                       "rate." % (len(emis), inr(emi_total))})
    elif emis and loans and abs(emi_total - loan_emi_total) > max(
            0.01 * max(emi_total, loan_emi_total), 100):
        out.append({
            "level": "warning", "code": "emi_mismatch",
            "message": "EMI outflows total %s/month but the recorded loans' "
                       "EMIs total %s/month. One of the two is out of date."
                       % (inr(emi_total), inr(loan_emi_total))})
    for loan in loans:
        if (loan.get("emi") or 0) > 0 and not emis:
            out.append({
                "level": "warning", "code": "loan_without_emi",
                "message": "Loan '%s' has an EMI of %s but no matching committed "
                           "outflow, so it is missing from your monthly surplus."
                           % (loan.get("name", "loan"), inr(loan["emi"]))})
            break
    return out


# What the salary figure means. Stored as a short code, but the dropdown
# once stored its own label -- "net take-home (after tax and deductions)" --
# so anything already saved has to keep working. Read by shape rather than
# by equality: a display string used as a stored key is exactly how "I set
# that" and "it is not set" end up both being true.
INCOME_BASIS_LABELS = {
    "net": "net take-home (after tax and deductions)",
    "gross": "gross (before tax and deductions)",
}


def normalise_income_basis(value):
    """"net", "gross", or "" for anything that does not say."""
    text = (value or "").strip().lower()
    if not text:
        return ""
    if "gross" in text or text.startswith("before"):
        return "gross"
    if "net" in text or "take" in text or "hand" in text:
        return "net"
    return ""


def income_basis_label(value):
    """The readable phrase, for an export a stranger has to interpret."""
    return INCOME_BASIS_LABELS.get(normalise_income_basis(value), "")


@_check
def _income_basis(ctx):
    """Gross or net changes what the surplus means.

    The app will not guess a tax bill; it says which way the number is wrong
    instead, because a surplus nobody can interpret is worse than none.
    """
    if not ctx["income_monthly"]:
        return []
    basis = normalise_income_basis(ctx["income_basis"])
    if basis == "gross":
        return [{
            "level": "warning", "code": "income_is_gross",
            "message": "Income is recorded as gross pay, so the surplus "
                       "above is overstated by your whole tax bill, and "
                       "any PF deducted from salary is being subtracted "
                       "from money that never reached you. Enter take-home "
                       "pay for a surplus you can act on."}]
    if basis != "net":
        return [{
            "level": "info", "code": "income_basis_unknown",
            "message": "Whether the salary entered is gross or take-home "
                       "is not set, so nobody reading this plan -- you "
                       "included -- can tell whether the surplus is "
                       "spendable. Set it under Settings -> Planning "
                       "inputs."}]
    return []


@_check
def _matured_fds(ctx):
    as_of = ctx["as_of"]
    matured = [h for h in ctx["holdings"]
               if h.get("asset_class") == "fd"
               and _parse_date((h.get("meta") or {}).get("maturity_date"))
               and _parse_date(h["meta"]["maturity_date"]) < as_of]
    if not matured:
        return []
    return [{
        "level": "warning", "code": "fd_matured",
        "message": "%d fixed deposit(s) matured on or before today, so "
                   "their value is held at the maturity amount and is no "
                   "longer growing. Re-enter them as renewed deposits or "
                   "as savings, whichever happened: %s."
                   % (len(matured), _names(matured))}]


@_check
def _stale_balances(ctx):
    as_of = ctx["as_of"]
    stale = [h for h in ctx["holdings"]
             if h.get("asset_class") in BALANCE_BASED
             and h.get("manual_value")
             and h.get("value_date")
             and (as_of - _parse_date(str(h["value_date"]))).days
             > MAX_ACCRUAL_MONTHS * 365.25 / 12]
    if not stale:
        return []
    return [{
        "level": "warning", "code": "balance_too_old",
        "message": "%d balance(s) (PF/PPF/NPS/savings) were last entered "
                   "over %d months ago. Accrual stops there rather than "
                   "extrapolating further, and contributions since then "
                   "are not included, so these read low: %s."
                   % (len(stale), MAX_ACCRUAL_MONTHS, _names(stale))}]


@_check
def _unit_placeholders(ctx):
    """Holdings recorded as one unit costing the entire invested amount.

    Harmless while the "price" is the market value, and catastrophic the
    moment a real NAV lands on it: one unit times a NAV of 215 is 215, and
    a five-lakh holding reads as a total loss.
    """
    placeholders = [h for h in ctx["holdings"] if is_unit_placeholder(h)]
    if not placeholders:
        return []
    return [{
        "level": "warning", "code": "unit_placeholder",
        "message": "%d holding(s) are recorded as 1 unit costing %s — that "
                   "is a total, not a price per unit, so their current value "
                   "and profit are wrong. Enter the units you actually hold "
                   "(your CAS has them) on the Portfolio page: %s."
                   % (len(placeholders),
                      inr(max(h.get("avg_cost") or 0 for h in placeholders)),
                      _names(placeholders))}]


@_check
def _hybrid_without_split(ctx):
    hybrid = [h for h in ctx["holdings"]
              if h.get("asset_class") == "mutual_fund"
              and ((h.get("meta") or {}).get("category") or "").lower()
              in ("hybrid", "multi_asset")
              and not has_split(h)]
    if not hybrid:
        return []
    return [{
        "level": "warning", "code": "hybrid_without_split",
        "message": "%d hybrid/multi-asset fund(s) are counted 100%% as "
                   "equity because no look-through split is set, which "
                   "understates the debt and gold you already hold: %s."
                   % (len(hybrid), _names(hybrid))}]


@_check
def _stale_prices(ctx):
    as_of = ctx["as_of"]
    stale = [h for h in ctx["holdings"]
             if h.get("asset_class") in ("mutual_fund", "stock")
             and h.get("price_date")
             # 10 days, not 7: a long weekend plus a holiday is not staleness.
             and (as_of - _parse_date(h["price_date"])).days > 10]
    if not stale:
        return []
    return [{
        "level": "info", "code": "stale_prices",
        "message": "%d holding(s) were last priced over ten days ago; "
                   "refresh prices before relying on the valuation."
                   % len(stale)}]


@_check
def _premiums_against_cashflow(ctx):
    policies = ctx["policies"]
    policy_premium = sum(to_annual(p.get("premium") or 0, p.get("frequency"))
                         for p in policies)
    outflow_premium = sum(r["amount_monthly"] * 12 for r in ctx["recurring"]
                          if r.get("kind") == "premium")
    if policy_premium > 0 and abs(policy_premium - outflow_premium) > max(
            0.05 * policy_premium, 1000):
        return [{
            "level": "warning", "code": "premium_not_in_cashflow",
            "message": "Policies total %s/year in premiums but committed "
                       "outflows carry %s/year. Whichever is missing, your "
                       "surplus is wrong by the difference."
                       % (inr(policy_premium), inr(outflow_premium))}]
    return []


@_check
def _policy_without_nominee(ctx):
    for p in ctx["policies"]:
        if not (p.get("nominee") or "").strip():
            return [{
                "level": "warning", "code": "policy_without_nominee",
                "message": "Policy '%s' has no nominee recorded — a claim "
                           "without one is far harder for a family to settle."
                           % p.get("name", "policy")}]
    return []


@_check
def _holdings_without_nominee(ctx):
    as_of = ctx["as_of"]
    none_named = [h for h in ctx["holdings"]
                  if not (h.get("meta") or {}).get("nominee")
                  and holding_value(h, as_of) > 0]
    if not none_named:
        return []
    return [{
        "level": "warning", "code": "missing_nominee",
        "message": "%d holding(s) worth %s have no nominee recorded. A "
                   "missing or stale nomination is the most common reason "
                   "a family cannot reach money it is entitled to."
                   % (len(none_named),
                      inr(sum(holding_value(h, as_of)
                              for h in none_named)))}]


@_check
def _fds_without_maturity(ctx):
    undated = [h for h in ctx["holdings"] if h.get("asset_class") == "fd"
               and not (h.get("meta") or {}).get("maturity_date")]
    if not undated:
        return []
    return [{
        "level": "info", "code": "fd_without_maturity",
        "message": "%d fixed deposit(s) have no maturity date, so they are "
                   "treated as locked and excluded from your emergency "
                   "fund." % len(undated)}]


def reconcile(recurring, loans, holdings=None, as_of=None,
              policies=None, income_basis="", income_monthly=0.0):
    """Inconsistencies a human reviewer would otherwise have to guess about.

    Returns dicts of {level, code, message}. These are reported, never
    silently corrected -- the app cannot know which side is right.
    """
    ctx = {"recurring": recurring, "loans": loans,
           "holdings": holdings or [], "policies": policies or [],
           "as_of": as_of or date.today(),
           "income_basis": income_basis, "income_monthly": income_monthly}
    out = []
    for check in _CHECKS:
        out.extend(check(ctx))
    return out


def holding_term(h, as_of=None):
    """(term, days_held) using a simplified long-term rule; None when unknown."""
    as_of = as_of or date.today()
    bought = _parse_date((h.get("meta") or {}).get("purchase_date"))
    if not bought:
        return None, None
    days = (as_of - bought).days
    cls = h.get("asset_class")
    cat = ((h.get("meta") or {}).get("category") or "").lower()
    equity_like = cls in ("stock", "reit") or (
        cls == "mutual_fund" and cat in EQUITY_MF_CATEGORIES)
    months = LONG_TERM_MONTHS_EQUITY if equity_like else LONG_TERM_MONTHS_OTHER
    return ("long" if days >= months * 30.44 else "short"), days


def unrealised_positions(holdings, as_of=None):
    """Per-holding unrealised gain/loss with short/long-term split."""
    as_of = as_of or date.today()
    rows, totals = [], {"gain": 0.0, "loss": 0.0, "short_gain": 0.0,
                        "long_gain": 0.0, "short_loss": 0.0, "long_loss": 0.0,
                        "undated": 0}
    for h in holdings:
        # Only unit-priced assets have an unrealised gain. Accrued FD/PPF
        # interest is income, taxable as it accrues, and cannot be
        # "unrealised" -- counting it here inflated the panel and gave it a
        # capital-gains term it does not have.
        if h.get("asset_class") not in UNIT_PRICED:
            continue
        cost = holding_cost(h)
        value = holding_value(h, as_of)
        if not cost:
            continue
        pnl = value - cost
        term, days = holding_term(h, as_of)
        if term is None:
            totals["undated"] += 1
        rows.append({"name": h.get("name"), "asset_class": h.get("asset_class"),
                     "invested": round(cost, 2), "current_value": round(value, 2),
                     "unrealised": round(pnl, 2), "term": term,
                     "days_held": days})
        key = "gain" if pnl >= 0 else "loss"
        totals[key] += pnl
        if term:
            totals["%s_%s" % (term, key)] += pnl
    totals = {k: (round(v, 2) if isinstance(v, float) else v)
              for k, v in totals.items()}
    totals["losers"] = sum(1 for r in rows if r["unrealised"] < 0)
    totals["count"] = len(rows)
    rows.sort(key=lambda r: r["unrealised"])
    return {"positions": rows, "totals": totals}


def aggregate(holdings, as_of=None):
    """Totals by asset class, by owner, by bucket, and overall."""
    as_of = as_of or date.today()
    by_class, by_owner, by_bucket = {}, {}, {}
    total = 0.0
    for h in holdings:
        v = holding_value(h, as_of)
        total += v
        by_class[h.get("asset_class")] = by_class.get(h.get("asset_class"), 0.0) + v
        owner = h.get("owner") or "Unassigned"
        by_owner[owner] = by_owner.get(owner, 0.0) + v
        for b, frac in holding_splits(h).items():
            by_bucket[b] = by_bucket.get(b, 0.0) + v * frac
    return {"total": total, "by_class": by_class,
            "by_owner": by_owner, "by_bucket": by_bucket}


def allocation_drift(by_bucket, targets):
    """Actual vs target percentage per bucket.

    Returns list of dicts sorted by most-underweight first.
    """
    total = sum(by_bucket.values()) or 1.0
    rows = []
    buckets = set(list(by_bucket.keys()) + list(targets.keys()))
    for b in buckets:
        actual_pct = 100.0 * by_bucket.get(b, 0.0) / total
        target_pct = float(targets.get(b, 0.0))
        rows.append({"bucket": b, "actual_pct": actual_pct,
                     "target_pct": target_pct,
                     "drift_pct": actual_pct - target_pct,
                     "gap_amount": (target_pct - actual_pct) / 100.0 * total})
    rows.sort(key=lambda r: r["drift_pct"])
    return rows


def xirr(cashflows, guess=0.1):
    """Money-weighted annual return.

    cashflows: list of (date, amount); negative = money in (investment),
    positive = money out (redemption / current value). Returns None when
    it cannot converge or the data is degenerate.
    """
    if len(cashflows) < 2:
        return None
    amounts = [a for _, a in cashflows]
    if all(a >= 0 for a in amounts) or all(a <= 0 for a in amounts):
        return None
    t0 = min(d for d, _ in cashflows)

    def npv(rate):
        return sum(a / (1 + rate) ** ((d - t0).days / 365.25)
                   for d, a in cashflows)

    lo, hi = -0.999, 10.0
    f_lo, f_hi = npv(lo), npv(hi)
    if f_lo * f_hi > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2
        f_mid = npv(mid)
        if abs(f_mid) < 1e-8:
            return mid
        if f_lo * f_mid < 0:
            hi = mid
        else:
            lo, f_lo = mid, f_mid
    return (lo + hi) / 2


# How many months one payment of each frequency covers. A quarterly bill is
# not a monthly bill -- spreading it is the only way a monthly surplus means
# anything.
FREQUENCY_MONTHS = {"monthly": 1, "quarterly": 3, "half_yearly": 6,
                    "yearly": 12}
FREQUENCY_LABELS = {"monthly": "Monthly", "quarterly": "Quarterly",
                    "half_yearly": "Half-yearly", "yearly": "Yearly"}


def to_monthly(amount, frequency):
    """Monthly-equivalent cost of a payment made every `frequency`."""
    return float(amount or 0.0) / FREQUENCY_MONTHS.get(frequency, 1)


def to_annual(amount, frequency):
    """What this outflow actually costs over a year."""
    return to_monthly(amount, frequency) * 12.0


def monthly_cashflow(income_total, expense_total, months, recurring,
                     income_months=None, expense_months=None):
    """Average monthly picture and the investible surplus.

    income_total/expense_total are sums of ad-hoc entries. Each is divided
    by the number of calendar months that actually carry entries
    (income_months/expense_months), NOT by the length of the lookback
    window -- otherwise one month of expenses logged against a 3-month
    window reads as a third of the real spend. `months` is the fallback
    when a caller does not count them. recurring is a list of dicts with
    amount_monthly, kind, counts_as_investment.
    """
    months = max(months, 1)
    # `is None` matters: zero entries is a real answer ("no data yet"), not a
    # missing argument, and must not silently fall back to the window length.
    income_div = months if income_months is None else income_months
    expense_div = months if expense_months is None else expense_months
    income_m = income_total / max(income_div, 1)
    expense_m = expense_total / max(expense_div, 1)
    emi_m = sum(r["amount_monthly"] for r in recurring if r.get("kind") == "emi")
    committed_invest_m = sum(r["amount_monthly"] for r in recurring
                             if r.get("counts_as_investment"))
    # Payroll deductions and discretionary SIPs are both saving, but they are
    # not interchangeable -- one is chosen every month, the other is not.
    payroll_invest_m = sum(r["amount_monthly"] for r in recurring
                           if r.get("counts_as_investment")
                           and r.get("kind") in PAYROLL_KINDS)
    sip_m = committed_invest_m - payroll_invest_m
    other_committed_m = sum(r["amount_monthly"] for r in recurring
                            if r.get("kind") != "emi"
                            and not r.get("counts_as_investment"))
    # Subscriptions, maintenance and premiums are spending, whatever their
    # billing cycle -- so the headline expense figure includes their monthly
    # equivalent. `expense_entries_m` keeps the ad-hoc ledger separable.
    expense_entries_m = expense_m
    recurring_expense_m = other_committed_m
    expense_m = expense_entries_m + recurring_expense_m
    surplus = income_m - expense_m - emi_m - committed_invest_m
    return {"income_m": income_m, "expense_m": expense_m, "emi_m": emi_m,
            "sip_m": sip_m, "payroll_invest_m": payroll_invest_m,
            "expense_entries_m": expense_entries_m,
            "recurring_expense_m": recurring_expense_m,
            "income_months": income_div,
            "expense_months": expense_div,
            "committed_invest_m": committed_invest_m,
            "other_committed_m": other_committed_m,
            "surplus_m": surplus,
            "savings_rate_pct": 100.0 * (committed_invest_m + max(surplus, 0.0))
            / income_m if income_m else 0.0}


def inr(x):
    """Indian-grouped amount string: 12,34,567."""
    x = int(round(x))
    neg = x < 0
    s = str(abs(x))
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        s = ",".join(parts + [tail])
    return ("-" if neg else "") + "\u20b9" + s


def _add_months(d, n):
    """Shift a date by n months, clamping the day (31 Jan + 1m -> 28 Feb)."""
    import calendar
    total = d.month - 1 + n
    year = d.year + total // 12
    month = total % 12 + 1
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


def upcoming_lumpy(recurring, as_of=None, horizon_months=3):
    """Non-monthly payments actually falling due in the next few months.

    Spreading a quarterly bill keeps the surplus honest, but the cash still
    leaves in one lump -- this is what to keep in the buffer. Monthly items
    are excluded (they are not lumpy) and so are entries with no due date,
    since a date is the only thing that makes the projection real.
    """
    as_of = as_of or date.today()
    horizon_end = _add_months(as_of, horizon_months)
    out = []
    for r in recurring:
        freq = r.get("frequency") or "monthly"
        step = FREQUENCY_MONTHS.get(freq, 1)
        if step <= 1:
            continue
        due = _parse_date(r.get("next_due"))
        if not due:
            continue
        # Two counters, not one: a next_due left years in the past used to
        # spend the whole budget rolling forward and then emit nothing, so
        # the bill silently vanished from the warning.
        rolled = 0
        while due < as_of and rolled < 240:     # roll a stale date forward
            due = _add_months(due, step)
            rolled += 1
        emitted = 0
        while due <= horizon_end and emitted < 240:
            out.append({
                "name": r.get("name"), "amount": float(r.get("amount") or 0),
                "due_date": due.isoformat(), "frequency": freq,
                "frequency_label": FREQUENCY_LABELS.get(freq, freq),
                "counts_as_investment": bool(r.get("counts_as_investment")),
            })
            emitted += 1
            due = _add_months(due, step)
    out.sort(key=lambda x: x["due_date"])
    return out


# Cover conventions common in Indian financial planning. Educational
# starting points, not entitlements -- the UI says so and every input is
# editable.
LIFE_COVER_INCOME_MULTIPLE = 12.0   # 10-15x annual income is the usual band
HEALTH_COVER_FLOOR = 1000000.0      # a family floor most planners quote

LIFE_KINDS = {"term", "life"}
HEALTH_KINDS = {"health"}


def insurance_gap(policies, annual_income, total_liabilities=0.0, *,
                  income_multiple=LIFE_COVER_INCOME_MULTIPLE,
                  health_floor=HEALTH_COVER_FLOOR):
    """Cover you hold against cover commonly recommended.

    Life cover is sized to replace income and clear debts, since a family
    left with the loan but not the earner is the case insurance exists for.
    Investment-linked policies are counted at their stated sum assured, which
    flatters them: an endowment's cover is usually a fraction of a term
    plan's for the same premium.
    """
    life = sum(p.get("sum_assured") or 0 for p in policies
               if p.get("kind") in LIFE_KINDS)
    health = sum(p.get("sum_assured") or 0 for p in policies
                 if p.get("kind") in HEALTH_KINDS)
    life_needed = annual_income * income_multiple + (total_liabilities or 0)
    return {
        "life_cover": round(life, 2),
        "life_cover_needed": round(life_needed, 2),
        "life_gap": round(max(life_needed - life, 0.0), 2),
        "life_basis": "%.0fx annual income plus outstanding debt"
                      % income_multiple,
        "health_cover": round(health, 2),
        "health_floor": round(health_floor, 2),
        "health_gap": round(max(health_floor - health, 0.0), 2),
        "policies": len(policies),
        "annual_premium": round(sum(
            to_annual(p.get("premium") or 0, p.get("frequency"))
            for p in policies), 2),
    }


def suggestions(context):
    """Rule-based, generic (deliberately not product-specific) suggestions.

    context keys: surplus_m, emergency_fund_target, liquid_assets,
    drift (from allocation_drift), loans (list of dicts with kind,
    annual_rate, principal_outstanding), idle_savings, savings_threshold,
    tax_80c_used, tax_80ccd1b_used.
    Returns ordered list of {priority, title, detail} dicts.
    """
    out = []
    surplus = context.get("surplus_m", 0.0)

    if surplus <= 0:
        out.append({
            "priority": 1, "title": "Cashflow is negative or zero",
            "detail": "Expenses plus EMIs consume your full income. Review "
                      "the top expense categories before planning investments."})
        return out

    ef_target = context.get("emergency_fund_target", 0.0)
    liquid = context.get("liquid_assets", 0.0)
    if ef_target and liquid < ef_target:
        gap = ef_target - liquid
        out.append({
            "priority": 1, "title": "Fill the emergency fund first",
            "detail": "Liquid assets (savings + liquid funds) are "
                      "%s short of your %s target. Route the surplus "
                      "to a liquid fund / sweep FD until covered."
                      % (inr(gap), inr(ef_target))})

    for loan in context.get("loans", []):
        if loan.get("annual_rate", 0) >= 10.0 and loan.get("principal_outstanding", 0) > 0:
            out.append({
                "priority": 1,
                "title": "Prepay high-interest debt: %s" % loan.get("name", loan.get("kind", "loan")),
                "detail": "At %.1f%% this loan likely costs more than "
                          "post-tax investment returns. Prepaying is a "
                          "risk-free return at that rate." % loan["annual_rate"]})

    used_80c = context.get("tax_80c_used")
    if used_80c is not None and used_80c < 150000:
        out.append({
            "priority": 2, "title": "Section 80C headroom (old regime)",
            "detail": "%s of the \u20b91,50,000 80C limit is unused this FY "
                      "(ELSS / PPF / EPF top-up count)." % inr(150000 - used_80c)})
    used_1b = context.get("tax_80ccd1b_used")
    if used_1b is not None and used_1b < 50000:
        out.append({
            "priority": 2, "title": "NPS 80CCD(1B) headroom (old regime)",
            "detail": "%s of the extra \u20b950,000 NPS deduction is unused "
                      "this FY." % inr(50000 - used_1b)})

    drift = context.get("drift", [])
    under = [d for d in drift if d["drift_pct"] < -2.0 and d["target_pct"] > 0]
    if under:
        worst = under[0]
        gap = max(worst["gap_amount"], 0.0)
        # A percentage gap expressed as a lump sum reads as an instruction to
        # move that much money today. Framing it against monthly surplus says
        # what it actually is: a direction for new money.
        months = gap / surplus if surplus > 0 else None
        pace = ("about %.0f months of your %s/month surplus"
                % (months, inr(surplus))) if months and months >= 1 else (
            "well inside one month of your surplus")
        out.append({
            "priority": 2,
            "title": "Rebalance: %s is underweight" % worst["bucket"],
            "detail": "Actual %.1f%% vs target %.1f%%, a gap of %s — %s. "
                      "Steer new monthly money towards %s rather than moving a "
                      "lump sum; if the target itself no longer fits your "
                      "horizon, change the target instead."
                      % (worst["actual_pct"], worst["target_pct"], inr(gap),
                         pace, worst["bucket"])})

    idle = context.get("idle_savings", 0.0)
    threshold = context.get("savings_threshold", 0.0)
    if threshold and idle > threshold:
        out.append({
            "priority": 3, "title": "Idle money in savings accounts",
            "detail": "%s sits in savings beyond your %s float. A "
                      "liquid fund or sweep FD earns 2-4%% more with "
                      "similar access." % (inr(idle - threshold), inr(threshold))})

    if not out:
        out.append({
            "priority": 3, "title": "On track",
            "detail": "Emergency fund covered, allocation within band, no "
                      "expensive debt. Continue SIPs and invest the surplus "
                      "of %s/month per your target allocation." % inr(surplus)})
    out.sort(key=lambda s: s["priority"])
    return out


def amortization_schedule(principal, annual_rate_pct, emi, max_months=600):
    """Month-by-month schedule; returns list of dicts and payoff months."""
    r = annual_rate_pct / 100.0 / 12.0
    bal = principal
    rows = []
    month = 0
    while bal > 0 and month < max_months:
        month += 1
        interest = bal * r
        principal_part = emi - interest
        if principal_part <= 0:
            return rows, None  # EMI doesn't even cover interest
        principal_part = min(principal_part, bal)
        bal -= principal_part
        rows.append({"month": month, "interest": interest,
                     "principal": principal_part, "balance": bal})
    return rows, month


def _grow(amount, annual_rate_pct, months):
    return amount * (1 + annual_rate_pct / 100.0) ** (months / 12.0)


def _sip_value(monthly, annual_rate_pct, months):
    """Future value of `monthly` invested at each month end."""
    if months <= 0 or not monthly:
        return 0.0
    r = (1 + annual_rate_pct / 100.0) ** (1 / 12.0) - 1
    if r == 0:
        return monthly * months
    return monthly * ((1 + r) ** months - 1) / r


def prepay_vs_invest(principal, annual_rate_pct, emi, lumpsum,
                     invest_return_pct):
    """Which leaves you better off: prepaying the loan, or investing?

    Comparing summed interest saved against a compounded investment gain --
    which is what this used to do -- is comparing two different things: one
    is nominal rupees spread over years, the other is a terminal figure, and
    a rupee saved in year 17 is not a rupee today. It also handed the whole
    benefit of the freed EMI to the investing side, when prepaying is
    precisely what frees an EMI early.

    So both strategies are run to the same horizon (the original payoff
    date) and their terminal net worth is compared:

      * prepay -- shorter schedule, then the whole EMI is invested from the
        early payoff to the horizon;
      * invest -- the lumpsum is invested, the EMI keeps being paid to the
        original end, and nothing is freed.

    Also returns the breakeven return: the rate at which the two strategies
    tie. That is the number that survives a disagreement about "12%", since
    the reader can judge it against their own expectation.
    """
    base_rows, base_months = amortization_schedule(principal, annual_rate_pct,
                                                   emi)
    if base_months is None:
        return None
    pre_rows, pre_months = amortization_schedule(
        max(principal - lumpsum, 0.0), annual_rate_pct, emi)
    if pre_months is None:
        return None
    base_interest = sum(r["interest"] for r in base_rows)
    pre_interest = sum(r["interest"] for r in pre_rows)
    months_saved = base_months - pre_months

    def terminal(rate_pct):
        # Prepay: debt-free at pre_months, then the EMI itself is invested.
        prepay_end = _sip_value(emi, rate_pct, months_saved)
        # Invest: the lumpsum compounds for the whole horizon; the EMI runs
        # to the original payoff, so nothing is left over to invest.
        invest_end = _grow(lumpsum, rate_pct, base_months)
        return prepay_end, invest_end

    prepay_terminal, invest_terminal = terminal(invest_return_pct)

    # Breakeven: the two curves cross at most once in a sane range, so a
    # bisection is enough. Below the breakeven, prepaying wins.
    lo, hi = 0.0, 40.0
    breakeven = None
    f_lo = (lambda p: p[1] - p[0])(terminal(lo))
    f_hi = (lambda p: p[1] - p[0])(terminal(hi))
    if f_lo * f_hi < 0:
        for _ in range(80):
            mid = (lo + hi) / 2
            f_mid = (lambda p: p[1] - p[0])(terminal(mid))
            if f_lo * f_mid <= 0:
                hi = mid
            else:
                lo, f_lo = mid, f_mid
        breakeven = round((lo + hi) / 2, 2)

    return {"interest_saved": base_interest - pre_interest,
            "months_saved": months_saved,
            "payoff_months": pre_months,
            "horizon_months": base_months,
            "prepay_terminal": prepay_terminal,
            "invest_terminal": invest_terminal,
            "difference": prepay_terminal - invest_terminal,
            "breakeven_return_pct": breakeven,
            # Kept for the export's older readers.
            "invest_future_value": _grow(lumpsum, invest_return_pct,
                                         base_months),
            "invest_gain": _grow(lumpsum, invest_return_pct,
                                 base_months) - lumpsum}


# ---------------------------------------------------------------------------
# Target-allocation presets
#
# These follow conventions commonly used by Indian fee-only planners and SEBI
# RIA material. They are starting points for a conversation, not advice, and
# every number is meant to be edited by the user:
#   * Equity via the classic "100 minus age" rule, floored at 20% and capped
#     at 80% so neither extreme of age lands somewhere silly.
#   * Gold 10% -- the midpoint of the 5-15% diversifier range most planners
#     and the World Gold Council quote for Indian portfolios.
#   * Cash 5% -- a working float; the real emergency fund is sized in months
#     of expenses, tracked separately in Settings.
#   * Real estate 5% -- REITs/InvITs only. A home you live in is not an
#     investment allocation and is deliberately excluded.
#   * Debt takes the remainder: EPF, PPF, FDs, debt funds, NPS-G.
# ---------------------------------------------------------------------------

GOLD_PCT = 10.0
CASH_PCT = 5.0
REAL_ESTATE_PCT = 5.0
EQUITY_FLOOR, EQUITY_CAP = 20.0, 80.0

RISK_PROFILES = {
    "conservative": (30.0, "Capital protection first; short horizons or "
                           "near/in retirement."),
    "balanced": (50.0, "Middle path \u2014 growth with a large stability cushion."),
    "growth": (70.0, "Long horizon and the stomach for deep drawdowns."),
}


def _targets_from_equity(equity_pct):
    """Fill the remaining buckets around a chosen equity weight."""
    equity = min(max(float(equity_pct), 0.0), 100.0)
    fixed = GOLD_PCT + CASH_PCT + REAL_ESTATE_PCT
    debt = max(100.0 - equity - fixed, 0.0)
    # If equity is so high the fixed sleeves cannot all fit, shrink them
    # proportionally rather than letting the total drift off 100.
    if equity + fixed > 100.0:
        room = max(100.0 - equity, 0.0)
        scale = room / fixed if fixed else 0.0
        out = {"equity": round(equity, 1), "debt": 0.0,
               "gold": round(GOLD_PCT * scale, 1),
               "real_estate": round(REAL_ESTATE_PCT * scale, 1),
               "cash": round(CASH_PCT * scale, 1), "other": 0.0}
    else:
        out = {"equity": round(equity, 1), "debt": round(debt, 1),
               "gold": GOLD_PCT, "real_estate": REAL_ESTATE_PCT,
               "cash": CASH_PCT, "other": 0.0}
    return _normalise_to_100(out)


def _normalise_to_100(targets):
    """Push any rounding residual into the largest bucket so the total is
    exactly 100 -- the UI refuses to save anything else."""
    residual = round(100.0 - sum(targets.values()), 1)
    if residual:
        biggest = max(targets, key=lambda k: targets[k])
        targets[biggest] = round(targets[biggest] + residual, 1)
    return targets


def equity_for_age(age):
    """The '100 minus age' rule, clamped to a sane band."""
    return min(max(100.0 - float(age), EQUITY_FLOOR), EQUITY_CAP)


def suggest_targets(age=None, profile=None):
    """Targets for one preset: age rule when `age` given, else a risk profile."""
    if age is not None:
        return _targets_from_equity(equity_for_age(age))
    equity, _ = RISK_PROFILES.get(profile or "balanced",
                                  RISK_PROFILES["balanced"])
    return _targets_from_equity(equity)


def target_presets(age=None):
    """All presets the UI offers, age-based one first when an age is known."""
    out = []
    if age is not None:
        eq = equity_for_age(age)
        out.append({
            "key": "age_rule",
            "name": "Age-based (100 \u2212 age)",
            "detail": "At %d that puts %.0f%% in equity \u2014 the rule Indian "
                      "planners most often start from." % (int(age), eq),
            "targets": suggest_targets(age=age),
            "recommended": True,
        })
    for key, (equity, detail) in RISK_PROFILES.items():
        out.append({
            "key": key,
            "name": key.capitalize(),
            "detail": detail,
            "targets": suggest_targets(profile=key),
            "recommended": False,
        })
    return out
