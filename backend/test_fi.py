"""Tests for the FI projection engine."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import analytics  # noqa: E402
import fi  # noqa: E402


def test_zero_growth_zero_inflation_is_simple_addition():
    r = fi.project({"cash": 100000}, 120000, 0, returns={"cash": 0.0},
                   inflation_pct=0, step_up_pct=0, years=3)
    assert [row["corpus"] for row in r["rows"]] == [100000, 220000, 340000, 460000]


def test_each_bucket_compounds_at_its_own_rate():
    r = fi.project({"equity": 100, "debt": 100}, 0, 0,
                   returns={"equity": 10.0, "debt": 0.0},
                   inflation_pct=0, step_up_pct=0, years=1)
    assert r["rows"][1]["corpus"] == 210          # 110 + 100, not 220


def test_new_money_follows_target_allocation():
    r = fi.project({"equity": 0}, 1000, 0,
                   target_allocation={"equity": 50, "debt": 50},
                   returns={"equity": 0.0, "debt": 0.0},
                   inflation_pct=0, step_up_pct=0, years=1)
    assert r["rows"][1]["corpus"] == 1000


def test_step_up_increases_contributions():
    flat = fi.project({"cash": 0}, 100, 0, returns={"cash": 0.0},
                      inflation_pct=0, step_up_pct=0, years=3)
    stepped = fi.project({"cash": 0}, 100, 0, returns={"cash": 0.0},
                         inflation_pct=0, step_up_pct=10, years=3)
    assert stepped["rows"][3]["corpus"] > flat["rows"][3]["corpus"]


def test_fi_target_rises_with_inflation():
    r = fi.project({"cash": 0}, 0, 100000, inflation_pct=6, years=2,
                   swr_multiple=30)
    assert r["rows"][0]["fi_target"] == 3000000
    assert round(r["rows"][2]["fi_target"]) == round(3000000 * 1.06 ** 2)


def test_real_values_discount_the_nominal_ones():
    r = fi.project({"cash": 1000000}, 0, 0, returns={"cash": 6.0},
                   inflation_pct=6, years=10)
    last = r["rows"][10]
    assert last["corpus"] > 1700000                 # nominal roughly doubles
    assert abs(last["corpus_real"] - 1000000) < 1   # real buying power flat


def test_crossover_is_the_first_year_corpus_beats_target():
    r = fi.project({"equity": 5000000}, 600000, 600000, returns={"equity": 11.0},
                   inflation_pct=6, swr_multiple=30, years=40)
    n = r["years_to_fi"]
    assert n is not None and n > 0
    assert r["rows"][n]["corpus"] >= r["rows"][n]["fi_target"]
    assert r["rows"][n - 1]["corpus"] < r["rows"][n - 1]["fi_target"]


def test_already_fi_reports_zero_years_not_one():
    r = fi.project({"equity": 10000000}, 0, 300000, returns={"equity": 10.0},
                   inflation_pct=6, swr_multiple=30, years=40)
    assert r["years_to_fi"] == 0


def test_unreachable_plan_reports_no_crossover():
    r = fi.project({"cash": 1000}, 0, 1000000, returns={"cash": 3.0},
                   inflation_pct=7, years=30)
    assert r["years_to_fi"] is None and r["corpus_at_fi"] is None


def test_freed_emi_is_invested_after_the_loan_closes():
    kw = dict(returns={"cash": 0.0}, inflation_pct=0, step_up_pct=0, years=5,
              target_allocation={"cash": 100})
    without = fi.project({"cash": 0}, 12000, 0, **kw)
    with_emi = fi.project({"cash": 0}, 12000, 0, payoff_year=2,
                          freed_emi_annual=60000, **kw)
    assert without["rows"][5]["corpus"] == 60000
    # years 3, 4, 5 each gain the freed EMI
    assert with_emi["rows"][5]["corpus"] == 60000 + 3 * 60000


def test_loan_payoff_year_uses_the_amortisation_schedule():
    years, emi_annual = fi.loan_payoff_year(
        [{"principal_outstanding": 1000000, "annual_rate": 9.0, "emi": 12668}],
        analytics.amortization_schedule)
    assert years == 10 and emi_annual == 12668 * 12


def test_loan_whose_emi_never_clears_interest_is_reported():
    years, _ = fi.loan_payoff_year(
        [{"principal_outstanding": 1000000, "annual_rate": 12.0, "emi": 5000}],
        analytics.amortization_schedule)
    assert years is None


def test_scenarios_only_move_the_equity_rate():
    out = fi.scenarios({"equity": 100, "debt": 100}, 0, 0,
                       returns={"debt": 0.0}, inflation_pct=0, years=1)
    assert [s["equity_return_pct"] for s in out] == [9.0, 12.0, 15.0]
    # debt is untouched across scenarios: difference is equity growth alone
    diffs = [s["rows"][1]["corpus"] - 100 for s in out]
    assert [round(d, 2) for d in diffs] == [109.0, 112.0, 115.0]


def test_higher_equity_return_reaches_fi_sooner():
    out = fi.scenarios({"equity": 5000000}, 600000, 600000,
                       inflation_pct=6, years=40)
    yrs = [s["years_to_fi"] for s in out]
    assert all(y is not None for y in yrs)
    assert yrs[0] >= yrs[1] >= yrs[2]


def test_coast_fi_ignores_future_contributions():
    r = fi.coast_fi({"equity": 20000000}, 300000, returns={"equity": 11.0},
                    inflation_pct=6, years=40)
    assert r["rows"][5]["corpus"] > 0
    plain = fi.project({"equity": 20000000}, 0, 300000,
                       returns={"equity": 11.0}, inflation_pct=6, years=40)
    assert r["rows"][10]["corpus"] == plain["rows"][10]["corpus"]


def test_empty_allocation_does_not_divide_by_zero():
    r = fi.project({}, 1000, 0, target_allocation={}, inflation_pct=0,
                   step_up_pct=0, years=1)
    assert r["rows"][1]["corpus"] == 1000


# ---- decumulation --------------------------------------------------------
def test_plan_switches_to_withdrawing_after_fi():
    r = fi.plan({"equity": 20000000}, 0, 300000, returns={"equity": 10.0},
                inflation_pct=6, swr_multiple=30, years=30)
    assert r["years_to_fi"] == 0
    phases = {row["phase"] for row in r["rows"][1:]}
    assert phases == {"withdraw"}
    assert r["rows"][5]["living_withdrawal"] > 0


def test_withdrawals_rise_with_inflation():
    r = fi.plan({"equity": 20000000}, 0, 300000, returns={"equity": 10.0},
                inflation_pct=6, swr_multiple=30, years=20)
    w5 = r["rows"][5]["living_withdrawal"]
    w10 = r["rows"][10]["living_withdrawal"]
    assert w10 > w5 * 1.25          # ~6%/yr compounding over five years


def test_an_overspent_corpus_depletes_and_is_reported():
    r = fi.plan({"equity": 3000000}, 0, 100000, returns={"equity": 4.0},
                inflation_pct=10, swr_multiple=30, retire_year=0, years=40)
    assert r["survives"] is False
    assert r["depleted_year"] is not None
    assert r["rows"][r["depleted_year"]]["corpus"] <= 1


def test_a_sustainable_corpus_survives_the_horizon():
    r = fi.plan({"equity": 30000000}, 0, 300000, returns={"equity": 10.0},
                inflation_pct=6, swr_multiple=30, retire_year=0, years=35)
    assert r["survives"] is True and r["ending_corpus"] > 0


def test_corpus_is_rebalanced_to_the_post_fi_mix_at_retirement():
    r = fi.plan({"equity": 20000000}, 0, 300000,
                post_fi_allocation={"debt": 100}, returns={"debt": 0.0},
                inflation_pct=0, swr_multiple=30, years=3)
    # everything sits in debt at 0% after retiring, so it only falls by spend
    assert r["rows"][1]["corpus"] == round(20000000 - 300000, 2)


def test_withdrawal_never_takes_more_than_the_corpus_holds():
    b = {"equity": 1000.0}
    assert fi._withdraw(b, 5000) == 1000.0
    assert round(sum(b.values()), 6) == 0.0
    assert fi._withdraw({}, 100) == 0.0


# ---- goals ---------------------------------------------------------------
def test_a_goal_is_withdrawn_in_its_year_and_inflated():
    goals = [{"name": "College", "year": 5, "amount_today": 1000000,
              "inflation_pct": 8}]
    r = fi.plan({"cash": 50000000}, 0, 0, goals=goals, returns={"cash": 0.0},
                inflation_pct=0, swr_multiple=0, years=6)
    row = r["rows"][5]
    assert row["goals"] == ["College"]
    assert round(row["goal_withdrawal"]) == round(1000000 * 1.08 ** 5)
    assert r["rows"][4]["goal_withdrawal"] == 0


def test_goals_use_their_own_inflation_not_the_household_rate():
    g = [{"name": "School", "year": 10, "amount_today": 100000,
          "inflation_pct": 10}]
    r = fi.plan({"cash": 90000000}, 0, 0, goals=g, returns={"cash": 0.0},
                inflation_pct=4, swr_multiple=0, years=11)
    assert round(r["rows"][10]["goal_withdrawal"]) == round(100000 * 1.10 ** 10)


def test_goals_delay_financial_independence():
    kw = dict(returns={"equity": 11.0}, inflation_pct=6, swr_multiple=30,
              years=45, target_allocation={"equity": 100})
    imp = fi.goal_impact({"equity": 5000000}, 600000, 600000,
                         [{"name": "House", "year": 5,
                           "amount_today": 5000000, "inflation_pct": 6}], **kw)
    assert imp["years_to_fi_without_goals"] is not None
    assert imp["delay_years"] is not None and imp["delay_years"] > 0


def test_goal_impact_reports_none_when_fi_is_unreachable():
    imp = fi.goal_impact({"cash": 1000}, 0, 1000000, [],
                         returns={"cash": 3.0}, inflation_pct=7, years=20)
    assert imp["delay_years"] is None


def test_plan_scenarios_cover_each_equity_rate():
    out = fi.plan_scenarios({"equity": 5000000}, 600000, 600000,
                            inflation_pct=6, years=40)
    assert [s["equity_return_pct"] for s in out] == [9.0, 12.0, 15.0]
    assert all("survives" in s for s in out)
