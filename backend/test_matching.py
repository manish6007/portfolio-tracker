"""Matching a fund you hold to the AMFI scheme that prices it.

The danger here is not failing to match -- it is matching confidently to the
wrong scheme. Every fund exists as Direct/Regular crossed with Growth/IDCW,
those have genuinely different NAVs, and a wrong pick produces a number that
looks entirely reasonable. So most of these tests are about what must NOT be
suggested.
"""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import matching  # noqa: E402

BASES = [
    "Axis ELSS Tax Saver Fund", "Axis Bluechip Fund",
    "DSP Midcap Fund", "DSP Small Cap Fund",
    "Mirae Asset Large & Midcap Fund", "Mirae Asset Large Cap Fund",
    "SBI Small Cap Fund", "SBI Large & Midcap Fund",
    "Motilal Oswal ELSS Tax Saver Fund", "Motilal Oswal Midcap Fund",
    "Motilal Oswal Nasdaq 100 Fund of Fund",
    "Parag Parikh Flexi Cap Fund", "Parag Parikh Tax Saver Fund",
    "HSBC Small Cap Fund", "HSBC Midcap Fund",
    "Nippon India Multi Asset Allocation Fund", "Nippon India Small Cap Fund",
    "ICICI Prudential NASDAQ 100 Index Fund",
    "ICICI Prudential Nifty 50 Index Fund",
    "ICICI Prudential Nifty Next 50 Index Fund",
    "HDFC Flexi Cap Fund", "HDFC Mid-Cap Opportunities Fund",
]


def universe():
    """Every fund four times over, as AMFI really lists them."""
    navs, code, nav = {}, 100000, 50.0
    for base in BASES:
        for plan in ("Direct Plan", "Regular Plan"):
            for option in ("Growth", "IDCW"):
                nav += 7.31
                navs[str(code)] = {
                    "name": "%s - %s - %s" % (base, plan, option),
                    "nav": round(nav, 4), "date": date(2026, 8, 26)}
                code += 1
    return navs


NAVS = universe()


def best(name, **kw):
    out = matching.suggest(name, NAVS, **kw)
    return out, (out["candidates"][0] if out["candidates"] else None)


# ---- the funds actually held --------------------------------------------
HELD = ["Axis ELSS Tax Saver Fund", "DSP Midcap Fund",
        "Mirae Asset Large & Midcap Fund", "SBI Small Cap Fund",
        "Motilal Oswal ELSS Tax Saver Fund", "Parag Parikh Flexi Cap Fund",
        "HSBC Small Cap Fund", "Nippon India Multi Asset Allocation Fund",
        "ICICI Prudential NASDAQ 100 Index Fund",
        "ICICI Prudential Nifty 50 Index Fund", "Motilal Oswal Midcap Fund",
        "Motilal Oswal Nasdaq 100 Fund of Fund"]


def test_a_plain_fund_name_matches_its_own_scheme():
    for name in HELD:
        out, top = best(name)
        assert top is not None, name
        assert out["confident"], name
        assert top["name"].startswith(name), (name, top["name"])


def test_the_default_is_direct_growth():
    _, top = best("DSP Midcap Fund")
    assert top["plan"] == "direct" and top["option"] == "growth"


def test_the_preference_can_be_changed():
    _, top = best("DSP Midcap Fund", want_plan="regular", want_option="idcw")
    assert top["plan"] == "regular" and top["option"] == "idcw"


def test_a_name_that_states_its_own_plan_beats_the_preference():
    """What the fund calls itself outranks a global default."""
    _, top = best("DSP Midcap Fund - Regular Plan - IDCW",
                  want_plan="direct", want_option="growth")
    assert top["plan"] == "regular" and top["option"] == "idcw"


# ---- the pairs where a wrong answer is plausible -------------------------
def test_nifty_50_is_not_matched_to_nifty_next_50():
    """One name's tokens are a subset of the other's."""
    _, top = best("ICICI Prudential Nifty 50 Index Fund")
    assert "Next 50" not in top["name"]
    _, top = best("ICICI Prudential Nifty Next 50 Index Fund")
    assert "Next 50" in top["name"]


def test_similar_funds_from_one_house_are_told_apart():
    for name in ["DSP Small Cap Fund", "DSP Midcap Fund",
                 "Motilal Oswal Midcap Fund",
                 "Motilal Oswal Nasdaq 100 Fund of Fund",
                 "SBI Large & Midcap Fund", "SBI Small Cap Fund",
                 "Parag Parikh Tax Saver Fund", "Parag Parikh Flexi Cap Fund",
                 "HDFC Mid-Cap Opportunities Fund", "HDFC Flexi Cap Fund"]:
        _, top = best(name)
        assert top["name"].startswith(name), (name, top["name"])


def test_a_placeholder_name_suggests_nothing_rather_than_guessing():
    out, _ = best("HDFC MF via Zerodha Coin (scheme name TBC)")
    assert not out["confident"]


def test_an_unrecognisable_name_is_refused_outright():
    out, _ = best("some fund I once heard about")
    assert out["candidates"] == [] and not out["confident"]


# ---- the recorded price as evidence -------------------------------------
def test_a_recorded_nav_overrides_the_direct_default():
    """Direct and Regular NAVs diverge by years of expense ratio, so the one
    that agrees with a price you already had is the one you hold."""
    regular = [c for c, i in NAVS.items()
               if i["name"] == "DSP Midcap Fund - Regular Plan - Growth"][0]
    out, top = best("DSP Midcap Fund", known_price=NAVS[regular]["nav"])
    assert top["code"] == regular
    assert out["confident"] and "NAV is within" in out["why"]


def test_a_recorded_nav_far_from_every_candidate_withholds_confidence():
    out, _ = best("DSP Midcap Fund", known_price=1.0)
    assert not out["confident"]
    assert "different plan" in out["why"]


def test_the_price_gap_is_reported_per_candidate():
    _, top = best("DSP Midcap Fund", known_price=None)
    assert top["price_gap_pct"] is None
    _, top = best("DSP Midcap Fund", known_price=top["nav"])
    assert top["price_gap_pct"] == 0.0


# ---- what counts as a scheme code ---------------------------------------
def test_folios_are_not_mistaken_for_scheme_codes():
    assert matching.looks_like_scheme_code("120503")
    assert not matching.looks_like_scheme_code("90722941761/0")
    assert not matching.looks_like_scheme_code("4274832 / 68")
    assert not matching.looks_like_scheme_code("RELIANCE")
    assert not matching.looks_like_scheme_code("")


def test_facets_split_the_name_from_the_variant():
    tokens, plan, option = matching.facets(
        "Axis ELSS Tax Saver Fund - Direct Plan - IDCW")
    assert plan == "direct" and option == "idcw"
    assert "fund" not in tokens and "axis" in tokens and "elss" in tokens
