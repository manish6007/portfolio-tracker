"""Rebuilding what the funds were worth, from the purchases alone.

The risk in this module is a chart that looks authoritative and is quietly
wrong: units counted on the wrong side of a date, a price extrapolated far
past any evidence for it, or a fund with no history silently held flat and
folded into the total.
"""
import os
import sys
from datetime import date

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import history  # noqa: E402


class Txn:
    def __init__(self, when, kind, amount, units):
        self.date, self.type = when, kind
        self.amount, self.units = amount, units


def buy(when, amount, units):
    return Txn(when, "buy", amount, units)


# ---- the months a reconstruction covers ---------------------------------
def test_every_month_end_between_the_first_purchase_and_today():
    ends = history.month_ends(date(2026, 1, 15), date(2026, 4, 10))
    assert ends == [date(2026, 1, 31), date(2026, 2, 28), date(2026, 3, 31),
                    date(2026, 4, 10)]


def test_the_month_in_progress_ends_today_not_in_the_future():
    """A point dated the 30th when it is the 6th would price a month that
    has not happened."""
    assert history.month_ends(date(2026, 9, 1), date(2026, 9, 6))[-1] \
        == date(2026, 9, 6)


def test_a_leap_february_is_the_29th():
    assert history.month_ends(date(2024, 2, 1), date(2024, 2, 29))[0] \
        == date(2024, 2, 29)


def test_no_dates_when_there_is_nothing_to_cover():
    assert history.month_ends(None, date(2026, 1, 1)) == []
    assert history.month_ends(date(2026, 5, 1), date(2026, 1, 1)) == []


# ---- the price a purchase actually paid ---------------------------------
def test_the_nav_is_recovered_from_the_amount_and_the_units():
    """No price feed is needed for a day the holder transacted on."""
    series = history.implied_navs([buy(date(2017, 4, 10), 3000.0, 58.474)])
    assert series[0][0] == date(2017, 4, 10)
    assert series[0][1] == pytest.approx(51.305, abs=0.001)


def test_a_transaction_with_no_units_carries_no_price():
    assert history.implied_navs([buy(date(2020, 1, 1), 500.0, 0)]) == []


def test_a_price_between_two_observations_is_interpolated():
    series = [(date(2026, 1, 1), 100.0), (date(2026, 2, 1), 200.0)]
    assert history.nav_on(series, date(2026, 1, 1)) == 100.0
    assert history.nav_on(series, date(2026, 2, 1)) == 200.0
    mid = history.nav_on(series, date(2026, 1, 16))
    assert 145 < mid < 155


def test_a_price_outside_the_evidence_stays_flat_rather_than_running_away():
    """Extending a trend past its last observation invents a return."""
    series = [(date(2026, 1, 1), 100.0), (date(2026, 2, 1), 200.0)]
    assert history.nav_on(series, date(2025, 1, 1)) == 100.0
    assert history.nav_on(series, date(2027, 1, 1)) == 200.0


def test_how_far_the_nearest_price_sits_is_reported():
    """So a long straight line can be shown as one, not passed off as data."""
    series = [(date(2026, 1, 1), 100.0), (date(2026, 6, 1), 120.0)]
    assert history.evidence_gap(series, date(2026, 1, 8)) == 7
    assert history.evidence_gap([], date(2026, 1, 8)) is None


# ---- units and money as at a date ---------------------------------------
TXNS = [buy(date(2026, 1, 10), 1000.0, 10.0),
        buy(date(2026, 2, 10), 1000.0, 8.0),
        Txn(date(2026, 3, 10), "sell", 900.0, 5.0)]


def test_units_held_count_only_what_had_happened_by_that_date():
    assert history.units_on(TXNS, date(2026, 1, 9)) == 0
    assert history.units_on(TXNS, date(2026, 1, 10)) == 10
    assert history.units_on(TXNS, date(2026, 2, 28)) == 18
    assert history.units_on(TXNS, date(2026, 3, 31)) == 13


def test_money_in_is_net_of_what_was_taken_back_out():
    assert history.invested_on(TXNS, date(2026, 2, 28)) == 2000
    assert history.invested_on(TXNS, date(2026, 3, 31)) == 1100


# ---- the series as a whole ----------------------------------------------
def test_the_history_starts_at_the_first_purchase_and_ends_today():
    funds = [([buy(date(2017, 4, 10), 3000.0, 58.474)], 100.0)]
    out = history.fund_history(funds, today=date(2017, 7, 15))
    assert out[0]["date"] == "2017-04-30"
    assert out[-1]["date"] == "2017-07-15"


def test_the_last_point_is_priced_at_todays_nav_not_the_last_purchase():
    """Anchored at both ends, so the line cannot drift away from the value
    every other page reports."""
    funds = [([buy(date(2026, 1, 10), 1000.0, 10.0)], 250.0)]
    out = history.fund_history(funds, today=date(2026, 6, 30))
    assert out[-1]["value"] == pytest.approx(2500.0)   # 10 units at 250
    assert out[-1]["invested"] == 1000.0
    assert out[-1]["gain"] == pytest.approx(1500.0)


def test_a_month_before_anything_was_bought_is_worth_nothing():
    funds = [([buy(date(2026, 3, 10), 1000.0, 10.0)], 120.0)]
    out = history.fund_history(funds, today=date(2026, 5, 31))
    assert out[0]["date"] == "2026-03-31"      # not February
    assert out[0]["invested"] == 1000.0


def test_a_fund_with_no_transactions_is_left_out_rather_than_held_flat():
    """Carrying today's value backwards would pass invention off as history."""
    funds = [([], 500.0), ([buy(date(2026, 1, 10), 1000.0, 10.0)], 120.0)]
    out = history.fund_history(funds, today=date(2026, 2, 28))
    assert out[-1]["value"] == pytest.approx(1200.0)   # only the second fund


def test_nothing_to_reconstruct_returns_nothing():
    assert history.fund_history([], today=date(2026, 1, 1)) == []
    assert history.fund_history([([], 100.0)], today=date(2026, 1, 1)) == []


def test_two_funds_are_summed_at_every_month_end():
    funds = [([buy(date(2026, 1, 10), 1000.0, 10.0)], 150.0),
             ([buy(date(2026, 2, 10), 2000.0, 20.0)], 110.0)]
    out = history.fund_history(funds, today=date(2026, 3, 31))
    assert out[-1]["invested"] == 3000.0
    assert out[-1]["value"] == pytest.approx(10 * 150 + 20 * 110)


def test_the_stale_share_is_measured_in_money_not_in_months():
    """One neglected fund made every month read as guesswork; what matters
    is how much value the carried price actually moves."""
    # Bought into every month, so its price is always freshly evidenced.
    fresh = [buy(date(2026, m, 10), 1000.0, 10.0) for m in range(1, 7)]
    # One purchase years earlier and nothing since.
    neglected = [buy(date(2020, 1, 10), 100.0, 1.0)]
    out = history.fund_history([(fresh, 100.0), (neglected, 100.0)],
                               today=date(2026, 6, 30))
    mid = next(p for p in out if p["date"] == "2026-01-31")
    assert mid["evidence_days"] > 120           # the neglected fund
    assert 0 < mid["stale_pct"] < 10            # but barely any of the money


def test_a_fully_current_history_reports_nothing_stale():
    funds = [([buy(date(2026, 5, 10), 1000.0, 10.0)], 100.0)]
    out = history.fund_history(funds, today=date(2026, 6, 30))
    assert out[-1]["stale_pct"] == 0.0


def test_todays_nav_leaves_the_final_point_fully_evidenced():
    """Every series is anchored at today, so the last point is never a
    carried price however long the fund was left alone."""
    funds = [([buy(date(2020, 1, 10), 100.0, 1.0)], 500.0)]
    out = history.fund_history(funds, today=date(2026, 6, 30))
    assert out[-1]["evidence_days"] == 0
    assert out[-1]["value"] == pytest.approx(500.0)
