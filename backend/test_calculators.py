"""The calculators, checked against closed-form answers where one exists."""
import pytest

import calculators as c


def _fv_sip(p, annual_pct, years):
    """Textbook SIP future value, instalment at the start of the month."""
    i = annual_pct / 100.0 / 12.0
    n = years * 12
    return p * (((1 + i) ** n - 1) / i) * (1 + i)


# ---------------- sip ----------------
def test_sip_matches_the_closed_form():
    got = c.sip(10000, 12, 10)["value"]
    assert got == pytest.approx(_fv_sip(10000, 12, 10), abs=0.01)


def test_sip_invested_is_just_the_instalments():
    r = c.sip(5000, 12, 5)
    assert r["invested"] == pytest.approx(5000 * 60)
    assert r["gain"] == pytest.approx(r["value"] - r["invested"])


def test_zero_return_grows_nothing():
    r = c.sip(1000, 0, 3)
    assert r["value"] == pytest.approx(36000)
    assert r["gain"] == pytest.approx(0)


def test_lumpsum_alone_compounds_monthly():
    r = c.sip(0, 12, 1, lumpsum=100000)
    assert r["value"] == pytest.approx(100000 * (1.01 ** 12))
    assert r["invested"] == pytest.approx(100000)


def test_step_up_raises_the_instalment_yearly_not_monthly():
    r = c.sip(10000, 12, 2, step_up_pct=10)
    # Year one at 10k, year two at 11k.
    assert r["invested"] == pytest.approx(10000 * 12 + 11000 * 12)


def test_step_up_beats_a_flat_sip():
    flat = c.sip(10000, 12, 15)["value"]
    stepped = c.sip(10000, 12, 15, step_up_pct=10)["value"]
    assert stepped > flat


def test_real_value_is_below_nominal_when_inflation_is_positive():
    r = c.sip(10000, 12, 20, inflation_pct=6)
    assert r["value_real"] < r["value"]


def test_rows_are_yearly_and_start_at_the_opening_balance():
    r = c.sip(1000, 10, 5)
    assert [row["year"] for row in r["rows"]] == [0, 1, 2, 3, 4, 5]
    assert r["rows"][0]["value"] == 0
    assert r["rows"][-1]["value"] == pytest.approx(r["value"])


def test_a_sip_of_nothing_is_rejected():
    with pytest.raises(ValueError):
        c.sip(0, 12, 10)


def test_negative_amounts_are_rejected():
    with pytest.raises(ValueError):
        c.sip(-500, 12, 10)


def test_a_period_under_a_month_is_rejected():
    with pytest.raises(ValueError):
        c.sip(1000, 12, 0)


def test_absurd_horizons_are_clamped_rather_than_hanging():
    assert c.sip(1000, 12, 500)["months"] == c.MAX_MONTHS


# ---------------- sip_for_target ----------------
def test_target_solves_back_to_the_forward_calculation():
    need = c.sip_for_target(5000000, 12, 10)["monthly"]
    got = c.sip(need, 12, 10)["value"]
    # Never short of the target, and never sillily over it.
    assert 5000000 <= got < 5000000 * 1.0002


def test_target_solves_back_with_a_step_up_too():
    need = c.sip_for_target(5000000, 12, 10, step_up_pct=10)["monthly"]
    got = c.sip(need, 12, 10, step_up_pct=10)["value"]
    assert 5000000 <= got < 5000000 * 1.0002


def test_the_instalment_is_whole_rupees():
    need = c.sip_for_target(5000000, 12, 10)["monthly"]
    assert need == int(need)


def test_a_lumpsum_reduces_the_instalment_needed():
    plain = c.sip_for_target(5000000, 12, 10)["monthly"]
    helped = c.sip_for_target(5000000, 12, 10, lumpsum=1000000)["monthly"]
    assert helped < plain


def test_a_lumpsum_that_already_gets_there_asks_for_nothing():
    r = c.sip_for_target(1000000, 12, 10, lumpsum=1000000)
    assert r["already_enough"] is True
    assert r["monthly"] == 0.0


def test_a_target_of_zero_is_rejected():
    with pytest.raises(ValueError):
        c.sip_for_target(0, 12, 10)


# ---------------- swp ----------------
def test_a_small_withdrawal_from_a_growing_corpus_survives():
    r = c.swp(10000000, 30000, 10, 25)
    assert r["survives"] is True
    assert r["depleted_month"] is None
    assert r["ending_balance"] > 0


def test_a_large_withdrawal_empties_the_corpus():
    r = c.swp(1000000, 50000, 8, 25)
    assert r["survives"] is False
    assert r["depleted_month"] is not None
    assert r["ending_balance"] == pytest.approx(0)


def test_withdrawals_stop_at_the_corpus_rather_than_going_negative():
    r = c.swp(100000, 60000, 0, 1)
    assert r["total_withdrawn"] == pytest.approx(100000)
    assert r["ending_balance"] == pytest.approx(0)


def test_zero_return_depletes_on_the_arithmetic_month():
    # 12 lakh drawn at 1 lakh a month, no growth: the 12th is the last full one.
    r = c.swp(1200000, 100000, 0, 5)
    assert r["depleted_month"] == 13


def test_a_rising_withdrawal_depletes_sooner_than_a_flat_one():
    flat = c.swp(10000000, 60000, 8, 40)
    rising = c.swp(10000000, 60000, 8, 40, step_up_pct=6)
    assert flat["total_withdrawn"] != rising["total_withdrawn"]
    assert not rising["survives"]


def test_withdrawing_exactly_the_growth_leaves_the_corpus_intact():
    """The perpetual withdrawal, which start-of-month timing makes i/(1+i).

    Taking the money out *before* the month's growth means the amount that
    can be drawn for ever is not the full 1% a month -- the withdrawn rupee
    does not earn. Getting this wrong by one compounding period is the
    classic SWP-calculator bug, so it is pinned here.
    """
    i = 0.12 / 12
    perpetual = 10000000 * i / (1 + i)
    r = c.swp(10000000, perpetual, 12, 30)
    assert r["survives"] is True
    assert r["ending_balance"] == pytest.approx(10000000, rel=1e-6)


def test_drawing_the_full_monthly_return_slowly_erodes_the_corpus():
    """One rupee more than perpetual, and it is a decaying plan, not a flat one."""
    r = c.swp(10000000, 100000, 12, 30)
    assert r["ending_balance"] < 10000000


def test_a_zero_corpus_is_rejected():
    with pytest.raises(ValueError):
        c.swp(0, 10000, 12, 10)


def test_a_zero_withdrawal_is_rejected():
    with pytest.raises(ValueError):
        c.swp(1000000, 0, 12, 10)


# ---------------- swp_sustainable ----------------
def test_the_sustainable_amount_survives_and_a_bit_more_does_not():
    corpus, ret, yrs = 10000000, 9, 30
    found = c.swp_sustainable(corpus, ret, yrs)["monthly"]
    assert c.swp(corpus, found, ret, yrs)["survives"] is True
    assert c.swp(corpus, found * 1.02, ret, yrs)["survives"] is False


def test_the_sustainable_amount_shrinks_when_it_must_rise_each_year():
    flat = c.swp_sustainable(10000000, 9, 30)["monthly"]
    rising = c.swp_sustainable(10000000, 9, 30, step_up_pct=6)["monthly"]
    assert rising < flat


def test_a_return_that_outruns_any_withdrawal_is_reported_as_unbounded():
    # Drawing the whole corpus in month one still "survives" a one-month plan.
    r = c.swp_sustainable(1000000, 12, 1.0 / 12)
    assert r["unbounded"] is True


# ---------------- notes ----------------
def test_a_flat_sip_is_called_out():
    said = " ".join(c.notes(c.sip(10000, 12, 20), "sip"))
    assert "step-up" in said


def test_a_depleting_swp_says_when():
    r = c.swp(1000000, 50000, 8, 25)
    said = " ".join(c.notes(r, "swp"))
    assert "runs out" in said


def test_a_yearly_figure_in_the_monthly_box_is_guessed_at():
    said = " ".join(c.notes(c.swp(500000, 600000, 8, 20), "swp"))
    assert "yearly figure" in said


def test_tax_is_always_disclaimed():
    for kind, r in (("sip", c.sip(1000, 12, 5)),
                    ("swp", c.swp(1000000, 5000, 8, 10))):
        assert any("Tax" in n for n in c.notes(r, kind))


def test_inr_groups_the_indian_way():
    assert c._inr(12345678) == "₹1,23,45,678"
    assert c._inr(0) == "₹0"
    assert c._inr(-1500) == "-₹1,500"
