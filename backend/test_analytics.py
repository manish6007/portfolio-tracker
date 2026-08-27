"""Unit tests for the pure-python analytics engine (no external deps)."""
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import analytics  # noqa: E402


def test_fd_value_compounds_quarterly():
    v = analytics.fd_value(100000, 8.0, date(2024, 1, 1), date(2025, 1, 1))
    assert 108000 < v < 108400  # ~8.24% effective


def test_holding_value_unit_priced():
    h = {"asset_class": "stock", "units": 10, "last_price": 250.0}
    assert analytics.holding_value(h) == 2500.0


def test_holding_value_balance_based_accrues():
    h = {"asset_class": "ppf", "manual_value": 100000, "rate": 7.1,
         "value_date": date(2025, 1, 1)}
    v = analytics.holding_value(h, date(2026, 1, 1))
    assert 106900 < v < 107300


def test_bucket_mapping_and_override():
    assert analytics.holding_bucket({"asset_class": "sgb"}) == "gold"
    assert analytics.holding_bucket(
        {"asset_class": "mutual_fund", "meta": {"category": "debt"}}) == "debt"
    assert analytics.holding_bucket(
        {"asset_class": "other", "meta": {"bucket": "equity"}}) == "equity"


def test_aggregate_totals():
    hs = [{"asset_class": "stock", "units": 1, "last_price": 100, "owner": "A"},
          {"asset_class": "savings", "manual_value": 50, "owner": "B",
           "value_date": date.today()}]
    agg = analytics.aggregate(hs)
    assert agg["total"] == 150
    assert agg["by_owner"] == {"A": 100.0, "B": 50.0}
    assert agg["by_bucket"]["equity"] == 100.0


def test_allocation_drift_sorted_underweight_first():
    drift = analytics.allocation_drift({"equity": 80, "debt": 20},
                                       {"equity": 60, "debt": 40})
    assert drift[0]["bucket"] == "debt"
    assert abs(drift[0]["gap_amount"] - 20.0) < 1e-6


def test_xirr_simple_doubling():
    flows = [(date(2020, 1, 1), -1000), (date(2027, 1, 1), 2000)]
    r = analytics.xirr(flows)
    assert r is not None and 0.095 < r < 0.11  # ~10.4% doubles in 7y


def test_xirr_degenerate_returns_none():
    assert analytics.xirr([(date(2020, 1, 1), -100)]) is None
    assert analytics.xirr([(date(2020, 1, 1), -100),
                           (date(2021, 1, 1), -50)]) is None


def test_monthly_cashflow_surplus():
    rec = [{"kind": "emi", "amount_monthly": 40000, "counts_as_investment": False},
           {"kind": "sip", "amount_monthly": 30000, "counts_as_investment": True}]
    cf = analytics.monthly_cashflow(840000, 240000, 3, rec)
    assert cf["income_m"] == 280000
    assert cf["expense_m"] == 80000
    assert cf["surplus_m"] == 280000 - 80000 - 40000 - 30000
    assert cf["savings_rate_pct"] > 0


def test_suggestions_priorities():
    ctx = {"surplus_m": 50000, "emergency_fund_target": 600000,
           "liquid_assets": 200000,
           "loans": [{"name": "PL", "kind": "personal", "annual_rate": 14.0,
                      "principal_outstanding": 100000}],
           "drift": [{"bucket": "debt", "drift_pct": -10, "target_pct": 30,
                      "actual_pct": 20, "gap_amount": 100000}]}
    out = analytics.suggestions(ctx)
    titles = " | ".join(s["title"] for s in out)
    assert "emergency fund" in titles.lower()
    assert "high-interest" in titles.lower()
    assert out[0]["priority"] == 1


def test_suggestions_negative_surplus_short_circuits():
    out = analytics.suggestions({"surplus_m": -5000})
    assert len(out) == 1 and out[0]["priority"] == 1


def test_amortization_and_prepay():
    rows, months = analytics.amortization_schedule(1000000, 9.0, 12668)
    assert months is not None and 115 <= months <= 125  # ~10 years
    res = analytics.prepay_vs_invest(1000000, 9.0, 12668, 100000, 12.0)
    assert res["interest_saved"] > 0
    assert res["months_saved"] > 0
    assert res["invest_future_value"] > 100000


def test_emi_not_covering_interest():
    rows, months = analytics.amortization_schedule(1000000, 12.0, 5000)
    assert months is None


def test_expense_average_uses_months_with_data_not_window():
    """One month of expenses in a 3-month window must not be divided by 3."""
    rec = []
    cf = analytics.monthly_cashflow(861000, 33000, 3, rec,
                                    income_months=3, expense_months=1)
    assert cf["income_m"] == 287000        # 3 months of salary -> /3
    assert cf["expense_m"] == 33000        # 1 month of spend   -> /1
    assert cf["surplus_m"] == 287000 - 33000
    assert cf["income_months"] == 3
    assert cf["expense_months"] == 1


def test_cashflow_divisors_fall_back_to_window():
    cf = analytics.monthly_cashflow(300000, 90000, 3, [])
    assert cf["income_m"] == 100000
    assert cf["expense_m"] == 30000


def test_cashflow_zero_months_does_not_divide_by_zero():
    cf = analytics.monthly_cashflow(0, 0, 3, [], income_months=0,
                                    expense_months=0)
    assert cf["income_m"] == 0 and cf["expense_m"] == 0


def test_presets_always_sum_to_100():
    for age in range(18, 96):
        t = analytics.suggest_targets(age=age)
        assert abs(sum(t.values()) - 100.0) < 0.05, age
    for profile in analytics.RISK_PROFILES:
        t = analytics.suggest_targets(profile=profile)
        assert abs(sum(t.values()) - 100.0) < 0.05, profile


def test_equity_for_age_rule_and_clamps():
    assert analytics.equity_for_age(40) == 60.0     # 100 - age
    assert analytics.equity_for_age(10) == 80.0     # capped
    assert analytics.equity_for_age(95) == 20.0     # floored


def test_equity_falls_as_age_rises():
    ages = [25, 40, 55, 70]
    eq = [analytics.suggest_targets(age=a)["equity"] for a in ages]
    assert eq == sorted(eq, reverse=True)


def test_very_high_equity_shrinks_sleeves_not_the_total():
    t = analytics._targets_from_equity(95.0)
    assert abs(sum(t.values()) - 100.0) < 0.05
    assert t["debt"] == 0.0 and t["gold"] < analytics.GOLD_PCT


def test_target_presets_shape():
    presets = analytics.target_presets(age=35)
    assert presets[0]["key"] == "age_rule" and presets[0]["recommended"]
    assert {p["key"] for p in presets} >= set(analytics.RISK_PROFILES)
    assert all(p["targets"] and p["name"] and p["detail"] for p in presets)
    # no age -> no age-based card
    assert all(p["key"] != "age_rule" for p in analytics.target_presets())


def test_savings_and_cash_bucket_are_liquid():
    assert analytics.is_liquid({"asset_class": "savings"})
    assert analytics.is_liquid({"asset_class": "mutual_fund",
                                "meta": {"category": "liquid"}})
    assert analytics.is_liquid({"asset_class": "fd", "meta": {"bucket": "cash"}})


def test_short_fd_is_liquid_long_fd_is_not():
    today = date(2026, 8, 24)
    short = {"asset_class": "fd", "meta": {"maturity_date": "2027-02-01"}}
    long = {"asset_class": "fd", "meta": {"maturity_date": "2031-01-01"}}
    assert analytics.is_liquid(short, today)
    assert not analytics.is_liquid(long, today)


def test_matured_fd_counts_as_liquid():
    assert analytics.is_liquid(
        {"asset_class": "fd", "meta": {"maturity_date": "2025-01-01"}},
        date(2026, 8, 24))


def test_fd_without_maturity_is_treated_as_locked():
    assert not analytics.is_liquid({"asset_class": "fd", "meta": {}})
    assert not analytics.is_liquid({"asset_class": "fd",
                                    "meta": {"maturity_date": "garbage"}})


def test_equity_is_never_liquid():
    assert not analytics.is_liquid({"asset_class": "stock"})
    assert not analytics.is_liquid({"asset_class": "epf"})


def test_liquid_total_sums_only_reachable_money():
    today = date(2026, 8, 24)
    hs = [{"asset_class": "savings", "manual_value": 300000,
           "value_date": today},
          {"asset_class": "fd", "avg_cost": 200000, "rate": 0,
           "start_date": today, "meta": {"maturity_date": "2027-01-01"}},
          {"asset_class": "fd", "avg_cost": 500000, "rate": 0,
           "start_date": today, "meta": {"maturity_date": "2032-01-01"}}]
    assert analytics.liquid_total(hs, today) == 500000


def test_frequency_converts_to_monthly():
    assert analytics.to_monthly(1200, "monthly") == 1200
    assert analytics.to_monthly(1200, "quarterly") == 400
    assert analytics.to_monthly(1200, "half_yearly") == 200
    assert analytics.to_monthly(1200, "yearly") == 100


def test_annual_cost_is_frequency_independent():
    for freq, per_payment in (("monthly", 1000), ("quarterly", 3000),
                              ("half_yearly", 6000), ("yearly", 12000)):
        assert analytics.to_annual(per_payment, freq) == 12000


def test_unknown_frequency_treated_as_monthly():
    assert analytics.to_monthly(500, "fortnightly") == 500
    assert analytics.to_monthly(500, None) == 500


def test_lumpy_outflows_fold_into_the_monthly_surplus():
    rec = [{"kind": "subscription", "counts_as_investment": False,
            "amount_monthly": analytics.to_monthly(12000, "yearly")},
           {"kind": "maintenance", "counts_as_investment": False,
            "amount_monthly": analytics.to_monthly(9000, "quarterly")}]
    cf = analytics.monthly_cashflow(100000, 0, 1, rec)
    assert cf["other_committed_m"] == 1000 + 3000
    assert cf["surplus_m"] == 100000 - 4000


def test_no_entries_reports_zero_months_not_the_window():
    """An empty ledger must say 'no entries', not 'average of 3 months'."""
    cf = analytics.monthly_cashflow(287000, 0, 3, [], income_months=1,
                                    expense_months=0)
    assert cf["expense_months"] == 0
    assert cf["expense_m"] == 0
    assert cf["income_months"] == 1


def test_recurring_costs_are_included_in_monthly_expenses():
    """A yearly subscription is spending, so it belongs in Expenses/month."""
    rec = [{"kind": "subscription", "counts_as_investment": False,
            "amount_monthly": 1000},
           {"kind": "maintenance", "counts_as_investment": False,
            "amount_monthly": 3000},
           {"kind": "emi", "counts_as_investment": False,
            "amount_monthly": 23300},
           {"kind": "sip", "counts_as_investment": True,
            "amount_monthly": 100000}]
    cf = analytics.monthly_cashflow(287000, 33000, 1, rec)
    assert cf["expense_entries_m"] == 33000      # ad-hoc ledger
    assert cf["recurring_expense_m"] == 4000     # sub + maintenance
    assert cf["expense_m"] == 37000              # headline figure
    # EMIs and investments stay out of the expense figure
    assert cf["emi_m"] == 23300
    assert cf["committed_invest_m"] == 100000
    # and nothing is double counted
    assert cf["surplus_m"] == 287000 - 37000 - 23300 - 100000


def test_add_months_clamps_short_months():
    assert analytics._add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert analytics._add_months(date(2026, 11, 15), 3) == date(2027, 2, 15)


def test_upcoming_lumpy_lists_due_payments_in_horizon():
    today = date(2026, 8, 25)
    rec = [{"name": "Home maintenance", "amount": 9000, "frequency": "quarterly",
            "next_due": "2026-09-10"},
           {"name": "Prime", "amount": 12000, "frequency": "yearly",
            "next_due": "2026-10-01"},
           {"name": "Far off", "amount": 5000, "frequency": "yearly",
            "next_due": "2027-06-01"},
           {"name": "SIP", "amount": 5000, "frequency": "monthly",
            "next_due": "2026-09-01"}]
    out = analytics.upcoming_lumpy(rec, today, 3)
    names = [x["name"] for x in out]
    assert names == ["Home maintenance", "Prime"]      # sorted by due date
    assert "SIP" not in names                          # monthly is not lumpy
    assert sum(x["amount"] for x in out) == 21000


def test_upcoming_lumpy_rolls_a_stale_due_date_forward():
    today = date(2026, 8, 25)
    rec = [{"name": "Old quarterly", "amount": 3000, "frequency": "quarterly",
            "next_due": "2025-09-05"}]
    out = analytics.upcoming_lumpy(rec, today, 3)
    assert len(out) == 1 and out[0]["due_date"] == "2026-09-05"


def test_upcoming_lumpy_needs_a_due_date():
    assert analytics.upcoming_lumpy(
        [{"name": "No date", "amount": 9000, "frequency": "yearly"}],
        date(2026, 8, 25)) == []


def test_upcoming_lumpy_repeats_within_a_long_horizon():
    out = analytics.upcoming_lumpy(
        [{"name": "Q bill", "amount": 1000, "frequency": "quarterly",
          "next_due": "2026-09-01"}], date(2026, 8, 25), 12)
    assert len(out) == 4


# ---- recurring classification -------------------------------------------
def test_payroll_and_sip_are_reported_separately():
    rec = [{"kind": "sip", "counts_as_investment": True, "amount_monthly": 100000},
           {"kind": "pf", "counts_as_investment": True, "amount_monthly": 32000},
           {"kind": "nps", "counts_as_investment": True, "amount_monthly": 10000},
           {"kind": "esop", "counts_as_investment": True, "amount_monthly": 5000}]
    cf = analytics.monthly_cashflow(287000, 0, 1, rec)
    assert cf["sip_m"] == 100000            # what the user actually chooses
    assert cf["payroll_invest_m"] == 47000  # PF + NPS + ESOP
    assert cf["committed_invest_m"] == 147000


# ---- look-through splits -------------------------------------------------
def test_split_distributes_one_holding_across_buckets():
    h = {"asset_class": "mutual_fund", "units": 1, "last_price": 100000,
         "meta": {"category": "hybrid",
                  "splits": {"equity": 65, "debt": 20, "gold": 15}}}
    agg = analytics.aggregate([h])
    assert agg["total"] == 100000
    assert agg["by_bucket"]["equity"] == 65000
    assert agg["by_bucket"]["gold"] == 15000
    assert abs(sum(agg["by_bucket"].values()) - 100000) < 0.01


def test_splits_normalise_when_they_do_not_total_100():
    h = {"asset_class": "mutual_fund", "meta": {"splits": {"equity": 1, "gold": 1}}}
    assert analytics.holding_splits(h) == {"equity": 0.5, "gold": 0.5}


def test_no_split_keeps_the_single_bucket():
    h = {"asset_class": "stock"}
    assert analytics.holding_splits(h) == {"equity": 1.0}
    assert not analytics.has_split(h)


# ---- reconciliation ------------------------------------------------------
def test_emi_without_a_loan_is_flagged():
    codes = [w["code"] for w in analytics.reconcile(
        [{"kind": "emi", "amount_monthly": 23300}], [])]
    assert "emi_without_loan" in codes


def test_emi_matching_its_loan_is_not_flagged():
    codes = [w["code"] for w in analytics.reconcile(
        [{"kind": "emi", "amount_monthly": 23300}],
        [{"name": "Home", "emi": 23300}])]
    assert "emi_without_loan" not in codes and "emi_mismatch" not in codes


def test_emi_disagreeing_with_its_loan_is_flagged():
    codes = [w["code"] for w in analytics.reconcile(
        [{"kind": "emi", "amount_monthly": 23300}],
        [{"name": "Home", "emi": 42000}])]
    assert "emi_mismatch" in codes


def test_hybrid_fund_without_a_split_is_flagged():
    hs = [{"asset_class": "mutual_fund", "name": "Multi Asset",
           "meta": {"category": "hybrid"}}]
    assert "hybrid_without_split" in [w["code"] for w in
                                      analytics.reconcile([], [], hs)]
    hs[0]["meta"]["splits"] = {"equity": 65, "debt": 20, "gold": 15}
    assert "hybrid_without_split" not in [w["code"] for w in
                                          analytics.reconcile([], [], hs)]


# ---- unrealised gains / tax terms ----------------------------------------
def test_holding_term_uses_twelve_months_for_equity():
    today = date(2026, 8, 25)
    h = {"asset_class": "stock", "meta": {"purchase_date": "2025-01-01"}}
    assert analytics.holding_term(h, today)[0] == "long"
    h["meta"]["purchase_date"] = "2026-06-01"
    assert analytics.holding_term(h, today)[0] == "short"


def test_holding_term_uses_twentyfour_months_for_non_equity():
    today = date(2026, 8, 25)
    h = {"asset_class": "gold_physical", "meta": {"purchase_date": "2025-06-01"}}
    assert analytics.holding_term(h, today)[0] == "short"   # 14 months
    h["meta"]["purchase_date"] = "2024-01-01"
    assert analytics.holding_term(h, today)[0] == "long"


def test_holding_term_unknown_without_a_purchase_date():
    assert analytics.holding_term({"asset_class": "stock"})[0] is None


def test_unrealised_positions_split_winners_and_losers():
    today = date(2026, 8, 25)
    hs = [{"name": "Winner", "asset_class": "stock", "units": 10,
           "avg_cost": 100, "last_price": 150,
           "meta": {"purchase_date": "2024-01-01"}},
          {"name": "Loser", "asset_class": "stock", "units": 10,
           "avg_cost": 100, "last_price": 70,
           "meta": {"purchase_date": "2026-07-01"}},
          {"name": "Undated", "asset_class": "stock", "units": 10,
           "avg_cost": 100, "last_price": 90}]
    r = analytics.unrealised_positions(hs, today)
    t = r["totals"]
    assert t["gain"] == 500 and t["loss"] == -400   # -300 and -100
    assert t["long_gain"] == 500 and t["short_loss"] == -300
    assert t["losers"] == 2 and t["undated"] == 1
    assert r["positions"][0]["name"] == "Loser"      # worst first


def test_rebalance_suggestion_is_framed_in_months_of_surplus():
    out = analytics.suggestions({
        "surplus_m": 100000,
        "drift": [{"bucket": "gold", "drift_pct": -8.8, "target_pct": 10.0,
                   "actual_pct": 1.2, "gap_amount": 1120000}]})
    detail = [s for s in out if "Rebalance" in s["title"]][0]["detail"]
    assert "11 months" in detail
    assert "lump sum" in detail


def test_holdings_without_a_nominee_are_flagged():
    hs = [{"asset_class": "stock", "name": "X", "units": 1, "last_price": 100,
           "avg_cost": 100}]
    assert "missing_nominee" in [w["code"] for w in
                                 analytics.reconcile([], [], hs)]
    hs[0]["meta"] = {"nominee": "Spouse"}
    assert "missing_nominee" not in [w["code"] for w in
                                     analytics.reconcile([], [], hs)]


def test_zero_value_holdings_do_not_trigger_a_nominee_warning():
    hs = [{"asset_class": "stock", "name": "Sold out", "units": 0,
           "last_price": 100, "avg_cost": 0}]
    assert "missing_nominee" not in [w["code"] for w in
                                     analytics.reconcile([], [], hs)]


# ---- insurance -----------------------------------------------------------
def test_life_cover_is_sized_to_income_and_debt():
    g = analytics.insurance_gap(
        [{"kind": "term", "sum_assured": 10000000}],
        annual_income=3000000, total_liabilities=3200000, income_multiple=12)
    assert g["life_cover"] == 10000000
    assert g["life_cover_needed"] == 3000000 * 12 + 3200000
    assert g["life_gap"] == 39200000 - 10000000


def test_no_gap_when_cover_exceeds_the_need():
    g = analytics.insurance_gap([{"kind": "term", "sum_assured": 50000000}],
                                annual_income=1000000, total_liabilities=0)
    assert g["life_gap"] == 0


def test_health_gap_uses_the_floor():
    g = analytics.insurance_gap([{"kind": "health", "sum_assured": 300000}],
                                annual_income=0, health_floor=1000000)
    assert g["health_cover"] == 300000 and g["health_gap"] == 700000


def test_motor_cover_does_not_count_as_life_or_health():
    g = analytics.insurance_gap([{"kind": "motor", "sum_assured": 800000}],
                                annual_income=1000000)
    assert g["life_cover"] == 0 and g["health_cover"] == 0


def test_annual_premium_respects_frequency():
    g = analytics.insurance_gap(
        [{"kind": "term", "premium": 6000, "frequency": "half_yearly"},
         {"kind": "health", "premium": 24000, "frequency": "yearly"}],
        annual_income=0)
    assert g["annual_premium"] == 12000 + 24000


def test_premiums_missing_from_cashflow_are_flagged():
    pols = [{"name": "Term", "premium": 24000, "frequency": "yearly",
             "nominee": "Spouse"}]
    codes = [w["code"] for w in analytics.reconcile([], [], [], policies=pols)]
    assert "premium_not_in_cashflow" in codes
    rec = [{"kind": "premium", "amount_monthly": 2000}]
    codes = [w["code"] for w in analytics.reconcile(rec, [], [], policies=pols)]
    assert "premium_not_in_cashflow" not in codes


def test_policy_without_a_nominee_is_flagged():
    pols = [{"name": "Term", "premium": 0, "nominee": ""}]
    assert "policy_without_nominee" in [
        w["code"] for w in analytics.reconcile([], [], [], policies=pols)]
    pols[0]["nominee"] = "Spouse"
    assert "policy_without_nominee" not in [
        w["code"] for w in analytics.reconcile([], [], [], policies=pols)]


# ---- review findings: valuation conventions ------------------------------
def test_an_fd_stops_growing_at_maturity():
    """A matured deposit is not still earning its contracted rate."""
    h = {"asset_class": "fd", "avg_cost": 100000, "rate": 7.0,
         "start_date": date(2018, 1, 1),
         "meta": {"maturity_date": "2023-01-01"}}
    at_maturity = analytics.holding_value(h, date(2023, 1, 1))
    much_later = analytics.holding_value(h, date(2026, 8, 26))
    assert round(at_maturity) == round(much_later)
    assert 141000 < at_maturity < 142000        # 5 years, quarterly


def test_an_fd_with_no_maturity_date_still_accrues():
    h = {"asset_class": "fd", "avg_cost": 100000, "rate": 7.0,
         "start_date": date(2018, 1, 1), "meta": {}}
    assert analytics.holding_value(h, date(2026, 8, 26)) > 170000


def test_a_matured_fd_is_reported_not_silently_frozen():
    h = {"asset_class": "fd", "name": "Old FD", "avg_cost": 100000,
         "rate": 7.0, "start_date": date(2018, 1, 1),
         "meta": {"maturity_date": "2023-01-01"}}
    codes = [w["code"] for w in analytics.reconcile(
        [], [], holdings=[h], as_of=date(2026, 8, 26))]
    assert "fd_matured" in codes


def test_ppf_compounds_rather_than_accruing_simple_interest():
    """PPF and EPF credit interest annually and it compounds."""
    ten_years = analytics.balance_accrued(
        100000, 7.1, date(2016, 1, 1), date(2026, 1, 1))
    # Capped at MAX_ACCRUAL_MONTHS, so this is the 18-month figure, not the
    # 10-year one -- the cap is the point.
    eighteen_months = 100000 * 1.071 ** (analytics.MAX_ACCRUAL_MONTHS / 12)
    assert abs(ten_years - eighteen_months) < 50


def test_a_fresh_balance_compounds_and_beats_simple_interest():
    compounded = analytics.balance_accrued(
        100000, 7.1, date(2025, 1, 1), date(2026, 1, 1) + timedelta(days=180))
    simple = 100000 * (1 + 0.071 * (365 + 180) / 365.25)
    assert compounded > simple


def test_a_balance_too_old_to_extrapolate_is_reported():
    h = {"asset_class": "ppf", "name": "PPF", "manual_value": 100000,
         "rate": 7.1, "value_date": date(2020, 1, 1)}
    codes = [w["code"] for w in analytics.reconcile(
        [], [], holdings=[h], as_of=date(2026, 8, 26))]
    assert "balance_too_old" in codes


def test_accrued_interest_is_not_an_unrealised_capital_gain():
    """FD/PPF interest is income taxable on accrual; it cannot be unrealised."""
    fd = {"asset_class": "fd", "name": "FD", "avg_cost": 100000, "rate": 7.0,
          "start_date": date(2018, 1, 1), "meta": {}}
    stock = {"asset_class": "stock", "name": "S", "units": 10,
             "avg_cost": 100, "last_price": 150, "meta": {}}
    out = analytics.unrealised_positions([fd, stock], as_of=date(2026, 8, 26))
    assert [r["name"] for r in out["positions"]] == ["S"]
    assert out["totals"]["gain"] == 500
    assert out["totals"]["count"] == 1


# ---- review findings: prepay vs invest -----------------------------------
PREPAY = dict(principal=5000000, annual_rate_pct=8.5, emi=45000,
              lumpsum=500000)


def test_prepay_credits_the_emi_freed_by_closing_early():
    """The whole point of prepaying is that the EMI stops sooner."""
    r = analytics.prepay_vs_invest(invest_return_pct=12.0, **PREPAY)
    assert r["months_saved"] > 0
    # Terminal value comes from investing the freed EMI, so it must be at
    # least the undiscounted sum of those payments.
    assert r["prepay_terminal"] > 45000 * r["months_saved"]


def test_both_strategies_are_measured_on_the_same_date():
    r = analytics.prepay_vs_invest(invest_return_pct=12.0, **PREPAY)
    assert r["payoff_months"] + r["months_saved"] == r["horizon_months"]
    assert r["difference"] == r["prepay_terminal"] - r["invest_terminal"]


def test_a_low_expected_return_favours_prepaying():
    low = analytics.prepay_vs_invest(invest_return_pct=4.0, **PREPAY)
    high = analytics.prepay_vs_invest(invest_return_pct=14.0, **PREPAY)
    assert low["difference"] > 0                 # prepay wins
    assert high["difference"] < 0                # investing wins


def test_the_breakeven_return_is_where_the_two_tie():
    r = analytics.prepay_vs_invest(invest_return_pct=12.0, **PREPAY)
    be = r["breakeven_return_pct"]
    assert be is not None
    at_breakeven = analytics.prepay_vs_invest(invest_return_pct=be, **PREPAY)
    assert abs(at_breakeven["difference"]) < 0.001 * at_breakeven["invest_terminal"]
    # And it sits near the loan rate, which is the intuition it has to match.
    assert 7.0 < be < 11.0


def test_prepay_returns_none_when_the_emi_cannot_cover_interest():
    assert analytics.prepay_vs_invest(5000000, 18.0, 5000, 100000, 12) is None


# ---- the salary basis, which is stored and then compared -----------------
def test_a_saved_income_basis_is_recognised_however_it_was_worded():
    """The dropdown once stored its own label, so "net take-home (after tax
    and deductions)" never equalled "net" and the app went on saying it was
    not set however many times it was set."""
    for value in ("net", "NET", "net take-home (after tax and deductions)",
                  "Net take-home", "take home", "in hand"):
        assert analytics.normalise_income_basis(value) == "net", value
    for value in ("gross", "GROSS", "gross (before tax and deductions)",
                  "before tax"):
        assert analytics.normalise_income_basis(value) == "gross", value
    for value in ("", None, "   ", "something else"):
        assert analytics.normalise_income_basis(value) == ""


def test_setting_the_basis_clears_the_warning():
    entries = [{"kind": "sip", "amount_monthly": 1000}]
    codes = lambda basis: [w["code"] for w in analytics.reconcile(  # noqa: E731
        entries, [], holdings=[], income_basis=basis, income_monthly=150000)]

    assert "income_basis_unknown" in codes("")
    assert "income_basis_unknown" in codes("something else")
    # The long form an older build saved must count as answered.
    assert "income_basis_unknown" not in codes(
        "net take-home (after tax and deductions)")
    assert "income_basis_unknown" not in codes("net")
    assert "income_basis_unknown" not in codes("gross")


def test_gross_pay_is_warned_about_rather_than_merely_noted():
    codes = [w["code"] for w in analytics.reconcile(
        [], [], holdings=[], income_basis="gross (before tax and deductions)",
        income_monthly=150000)]
    assert "income_is_gross" in codes


def test_the_export_spells_the_basis_out_for_a_stranger():
    assert analytics.income_basis_label("net") == \
        "net take-home (after tax and deductions)"
    assert analytics.income_basis_label("gross") == \
        "gross (before tax and deductions)"
    assert analytics.income_basis_label("") == ""
