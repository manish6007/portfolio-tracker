"""Purchases, sales, and the position they imply.

This module decides what a holding is worth and what a sale earned, so the
tests are weighted towards the ways it could be confidently wrong: charges
quietly dropped from the cost base, a sale consuming the wrong parcel, a
holding period landing on the wrong side of the tax line, or an oversell
silently producing negative units.
"""
import os
import sys
from datetime import date

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ledger  # noqa: E402


class FakeLot:
    """A lot without a database, so the arithmetic can be tested alone."""

    def __init__(self, when, units, price, charges=0.0, lot_id=1):
        self.date, self.units, self.price = when, units, price
        self.charges, self.remaining, self.id = charges, units, lot_id


class FakeHolding:
    def __init__(self, lots=(), asset_class="stock", name="Test Co"):
        self.lots = list(lots)
        self.asset_class, self.name = asset_class, name
        self.units = self.avg_cost = 0.0
        self.id = 1


class FakeSession:
    def __init__(self):
        self.added = []

    def add(self, obj):
        self.added.append(obj)


# ---- what a unit actually cost -----------------------------------------
def test_charges_are_part_of_the_cost_of_a_unit():
    """A return measured against the quoted price is a return nobody got."""
    assert ledger.lot_cost_per_unit(10, 100, 0) == 100
    assert ledger.lot_cost_per_unit(10, 100, 50) == 105


def test_a_lot_of_nothing_costs_nothing_rather_than_dividing_by_zero():
    assert ledger.lot_cost_per_unit(0, 100, 50) == 0.0


# ---- the position implied by open lots ----------------------------------
def test_the_average_is_weighted_by_units_not_by_lot():
    """Two lots of very different sizes must not count equally."""
    lots = [FakeLot(date(2026, 1, 1), 90, 100, lot_id=1),
            FakeLot(date(2026, 2, 1), 10, 200, lot_id=2)]
    units, avg = ledger.position(lots)
    assert units == 100
    assert avg == pytest.approx(110)


def test_an_emptied_lot_leaves_the_position():
    lots = [FakeLot(date(2026, 1, 1), 10, 100, lot_id=1),
            FakeLot(date(2026, 2, 1), 10, 200, lot_id=2)]
    lots[0].remaining = 0
    units, avg = ledger.position(lots)
    assert (units, avg) == (10, 200)


def test_a_fully_sold_position_is_zero_not_a_stale_average():
    lots = [FakeLot(date(2026, 1, 1), 10, 100)]
    lots[0].remaining = 0
    assert ledger.position(lots) == (0.0, 0.0)


def test_recompute_leaves_a_holding_that_has_no_lots_alone():
    """Balance-based holdings carry hand-entered numbers; zeroing them
    would erase real money."""
    h = FakeHolding(lots=[], asset_class="epf")
    h.units, h.avg_cost = 5.0, 20.0
    ledger.recompute(h)
    assert (h.units, h.avg_cost) == (5.0, 20.0)


# ---- holding period and the tax line ------------------------------------
def test_months_between_does_not_round_a_partial_month_up():
    assert ledger.months_between(date(2025, 1, 15), date(2026, 1, 14)) == 11
    assert ledger.months_between(date(2025, 1, 15), date(2026, 1, 15)) == 12


def test_listed_equity_turns_long_term_at_twelve_months():
    short = ledger.gain_type("stock", date(2025, 1, 15), date(2026, 1, 14))
    long = ledger.gain_type("stock", date(2025, 1, 15), date(2026, 1, 15))
    assert (short, long) == ("stcg", "ltcg")


def test_an_unlisted_asset_takes_the_twenty_four_month_line():
    assert ledger.gain_type("gold_physical", date(2025, 1, 1),
                            date(2026, 6, 1)) == "stcg"
    assert ledger.gain_type("gold_physical", date(2024, 1, 1),
                            date(2026, 6, 1)) == "ltcg"


def test_an_unrecorded_purchase_date_is_reported_as_unknown():
    """A position converted from a balance may have been held for a decade;
    calling it short-term would be confidently wrong at filing time."""
    assert ledger.gain_type("stock", date(2026, 8, 30), date(2026, 9, 6),
                            date_known=False) == "unknown"


def test_a_parcel_with_no_known_buy_date_does_not_claim_a_tax_treatment():
    lot = FakeLot(date(2026, 8, 30), 10, 100)
    lot.date_known = 0
    h = FakeHolding([lot])
    trades = ledger.sell(FakeSession(), h, date(2026, 9, 6), 10, 150)
    assert trades[0].gain_type == ledger.GAIN_UNKNOWN
    assert trades[0].realised == pytest.approx(500)   # the money is still known


# ---- selling ------------------------------------------------------------
def test_a_sale_consumes_the_oldest_parcel_first():
    """FIFO is not a preference — it is what the tax computation assumes."""
    h = FakeHolding([FakeLot(date(2026, 1, 1), 10, 100, lot_id=1),
                     FakeLot(date(2026, 6, 1), 10, 200, lot_id=2)])
    trades = ledger.sell(FakeSession(), h, date(2026, 7, 1), 5, 300)
    assert len(trades) == 1
    assert trades[0].buy_price == 100
    assert h.lots[0].remaining == 5 and h.lots[1].remaining == 10


def test_a_sale_spanning_two_parcels_books_each_one_separately():
    """Holding period differs per parcel, so averaging them away would lose
    the reason for keeping parcels at all."""
    h = FakeHolding([FakeLot(date(2025, 1, 1), 10, 100, lot_id=1),
                     FakeLot(date(2026, 6, 1), 10, 200, lot_id=2)])
    trades = ledger.sell(FakeSession(), h, date(2026, 7, 1), 15, 300)
    assert [t.units for t in trades] == [10, 5]
    assert [t.gain_type for t in trades] == ["ltcg", "stcg"]
    assert ledger.position(h.lots)[0] == 5


def test_sale_charges_are_split_across_the_parcels_they_closed():
    h = FakeHolding([FakeLot(date(2026, 1, 1), 10, 100, lot_id=1),
                     FakeLot(date(2026, 2, 1), 10, 100, lot_id=2)])
    trades = ledger.sell(FakeSession(), h, date(2026, 7, 1), 20, 150,
                         charges=100)
    assert [t.charges for t in trades] == [50, 50]


def test_the_realised_amount_is_net_of_both_sides_charges():
    h = FakeHolding([FakeLot(date(2026, 1, 1), 10, 100, charges=50)])
    trades = ledger.sell(FakeSession(), h, date(2026, 7, 1), 10, 150,
                         charges=30)
    # bought at 105 all-in, sold at 150, less 30 to sell
    assert trades[0].realised == pytest.approx(10 * (150 - 105) - 30)


def test_selling_more_than_is_held_is_refused():
    h = FakeHolding([FakeLot(date(2026, 1, 1), 10, 100)])
    with pytest.raises(ledger.LedgerError) as exc:
        ledger.sell(FakeSession(), h, date(2026, 7, 1), 11, 150)
    assert "10" in str(exc.value)
    assert h.lots[0].remaining == 10          # nothing was consumed


def test_a_full_exit_is_not_refused_over_floating_point_dust():
    """Units divide badly; a full exit typed by hand must still go through."""
    h = FakeHolding([FakeLot(date(2026, 1, 1), 0.1 + 0.2, 100)])
    ledger.sell(FakeSession(), h, date(2026, 7, 1), 0.3, 150)
    assert ledger.position(h.lots)[0] == 0.0


def test_a_sale_of_nothing_is_refused():
    h = FakeHolding([FakeLot(date(2026, 1, 1), 10, 100)])
    with pytest.raises(ledger.LedgerError):
        ledger.sell(FakeSession(), h, date(2026, 7, 1), 0, 150)


# ---- what the reports add up to -----------------------------------------
class FakeTrade:
    def __init__(self, realised, units=1, buy_price=100, reason=""):
        self.realised, self.units = realised, units
        self.buy_price, self.reason = buy_price, reason


def test_the_realised_summary_counts_wins_and_percent_on_cost():
    trades = [FakeTrade(500, 10, 100), FakeTrade(-200, 10, 100)]
    out = ledger.realised_summary(trades)
    assert out["realised"] == 300 and out["invested"] == 2000
    assert out["pct"] == 15.0 and out["wins"] == 1 and out["trades"] == 2


def test_an_empty_summary_does_not_divide_by_zero():
    assert ledger.realised_summary([])["pct"] == 0.0


def test_stop_loss_exits_are_reported_apart_from_every_other_exit():
    """The question stops exist to answer, and no spreadsheet can."""
    trades = [FakeTrade(-500, 10, 100, "stoploss"),
              FakeTrade(-300, 10, 100, "stoploss"),
              FakeTrade(900, 10, 100, "target")]
    out = ledger.stoploss_verdict(trades)
    assert out["stopped"]["realised"] == -800
    assert out["stopped"]["trades"] == 2
    assert out["other_exits"]["realised"] == 900


# ---- capital in and out --------------------------------------------------
class FakeFlow:
    def __init__(self, direction, amount):
        self.direction, self.amount = direction, amount


def test_cash_into_the_pot_is_contributions_less_withdrawals():
    flows = [FakeFlow("in", 100000), FakeFlow("in", 50000),
             FakeFlow("out", 20000)]
    assert ledger.cash_moved(flows) == 130000


def test_no_capital_flows_is_zero_not_an_error():
    assert ledger.cash_moved([]) == 0.0


# ---- capital actually at work -------------------------------------------
def test_deployed_is_the_cost_of_what_is_still_held():
    """Charges included, because that is what left the bank — and it keeps
    open profit equal to value minus this."""
    lots = [FakeLot(date(2026, 1, 1), 10, 100, charges=50)]
    assert ledger.deployed(lots) == 1050


def test_selling_releases_the_capital_behind_the_units_sold():
    """A figure counting every unit ever bought would only ever grow, and
    would double-count every rupee that has been recycled."""
    lots = [FakeLot(date(2026, 1, 1), 10, 100)]
    assert ledger.deployed(lots) == 1000
    lots[0].remaining = 4
    assert ledger.deployed(lots) == 400


def test_cash_moved_is_a_different_question_from_deployed():
    flows = [FakeFlow("in", 100000), FakeFlow("out", 20000)]
    assert ledger.cash_moved(flows) == 80000


# ---- core against satellite ---------------------------------------------
def sleeved(lot, sleeve):
    lot.sleeve = sleeve
    return lot


def test_the_two_sleeves_are_totalled_separately_and_together():
    core = sleeved(FakeLot(date(2026, 1, 1), 10, 100, lot_id=1), "core")
    sat = sleeved(FakeLot(date(2026, 2, 1), 10, 200, lot_id=2), "satellite")
    out = ledger.by_sleeve([([core], 150), ([sat], 180)], [])
    rows = {r["sleeve"]: r for r in out["sleeves"]}
    assert rows["core"]["deployed"] == 1000
    assert rows["core"]["unrealised"] == 500
    assert rows["satellite"]["unrealised"] == -200
    assert out["total"]["deployed"] == 3000
    assert out["total"]["unrealised"] == 300


def test_a_closed_trade_counts_against_the_sleeve_that_took_the_risk():
    trade = FakeTrade(-800, 10, 100, "stoploss")
    trade.sleeve = "satellite"
    out = ledger.by_sleeve([], [trade])
    rows = {r["sleeve"]: r for r in out["sleeves"]}
    assert rows["satellite"]["realised"] == -800
    assert rows["core"]["realised"] == 0
    assert out["total"]["realised"] == -800


def test_total_profit_is_unrealised_plus_realised():
    lot = sleeved(FakeLot(date(2026, 1, 1), 10, 100, lot_id=1), "core")
    trade = FakeTrade(250, 5, 100, "target")
    trade.sleeve = "core"
    out = ledger.by_sleeve([([lot], 130)], [trade])
    core = {r["sleeve"]: r for r in out["sleeves"]}["core"]
    assert core["unrealised"] == 300 and core["realised"] == 250
    assert core["total_pnl"] == 550


def test_an_unassigned_parcel_is_shown_as_itself_not_folded_into_core():
    """The same rule the size chart follows: report it, never guess it."""
    lot = FakeLot(date(2026, 1, 1), 10, 100, lot_id=1)
    out = ledger.by_sleeve([([lot], 150)], [])
    rows = {r["sleeve"]: r for r in out["sleeves"]}
    assert rows[""]["deployed"] == 1000
    assert rows["core"]["deployed"] == 0
    assert rows[""]["label"] == "Not assigned"


def test_an_unknown_sleeve_value_does_not_lose_the_money():
    lot = sleeved(FakeLot(date(2026, 1, 1), 10, 100, lot_id=1), "nonsense")
    out = ledger.by_sleeve([([lot], 150)], [])
    assert out["total"]["deployed"] == 1000
