"""Service layer: ORM <-> dict conversion and the computation pipeline."""
from datetime import date

import analytics
import capmix
from db import (ExpenseEntry, Holding, IncomeEntry, Loan, Owner, Policy,
                RecurringOutflow, get_setting, get_targets)


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


def _month_span(rows):
    """How many distinct calendar months actually carry entries."""
    return len({(r.date.year, r.date.month) for r in rows})


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
