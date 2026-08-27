"""Large / mid / small, across funds and shares.

Asset allocation says how much is in equity. It does not say whether that
equity is Nifty-50 steady or small-cap volatile, and those are different
portfolios with identical asset-class charts.

The risk in this module is confident misclassification, so most of what is
tested is the near-misses and what must stay unclassified.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import analytics  # noqa: E402
import capmix  # noqa: E402


def label(name):
    return capmix.CATEGORY_LABELS.get(capmix.classify_scheme(name), "")


# ---- reading a fund's own name ------------------------------------------
def test_the_plain_sebi_categories_are_recognised():
    assert label("DSP Midcap Fund - Direct Plan - Growth") == "Mid cap"
    assert label("SBI Small Cap Fund - Direct Plan - Growth") == "Small cap"
    assert label("Axis Bluechip Fund - Direct Plan - Growth") == "Large cap"
    assert label("Parag Parikh Flexi Cap Fund - Direct - Growth") == "Flexi cap"
    assert label("Axis ELSS Tax Saver Fund - Direct - Growth") == "ELSS"


def test_large_and_mid_is_not_read_as_large():
    """One name contains the other, so order of matching decides it."""
    assert label("Mirae Asset Large & Midcap Fund - Direct - Growth") \
        == "Large & mid cap"
    assert label("SBI Large and Midcap Fund - Direct - Growth") \
        == "Large & mid cap"


def test_nifty_next_50_is_not_read_as_nifty_50():
    for name in ("ICICI Prudential Nifty 50 Index Fund - Direct - Growth",
                 "ICICI Prudential Nifty Next 50 Index Fund - Direct - Growth"):
        assert label(name) == "Large-cap index", name


def test_an_index_fund_follows_the_index_it_tracks():
    assert label("Motilal Oswal Nifty Midcap 150 Index Fund") == "Midcap index"
    assert label("Nippon India Nifty Smallcap 250 Index Fund") == "Smallcap index"


def test_a_fund_investing_abroad_is_not_given_an_indian_cap():
    """Indian large/mid/small is an AMFI list of Indian companies."""
    for name in ("ICICI Prudential NASDAQ 100 Index Fund - Direct - Growth",
                 "Motilal Oswal Nasdaq 100 Fund of Fund - Direct - Growth",
                 "Franklin India Feeder US Opportunities Fund"):
        assert label(name) == "International", name
    split, _ = capmix.cap_split({"asset_class": "mutual_fund",
                                 "name": "Motilal Oswal Nasdaq 100 FoF"})
    assert split == {"international": 1.0}


def test_a_hybrid_is_classified_on_its_equity_sleeve():
    for name in ("HDFC Balanced Advantage Fund - Direct - Growth",
                 "ICICI Prudential Equity & Debt Fund - Direct - Growth",
                 "Nippon India Multi Asset Allocation Fund - Direct - Growth"):
        assert label(name) == "Hybrid (equity sleeve)", name


def test_a_debt_fund_matches_nothing():
    assert label("HDFC Corporate Bond Fund - Direct Plan - Growth") == ""
    assert label("SBI Liquid Fund - Direct Plan - Growth") == ""


def test_every_category_split_adds_up():
    for category, (split, why) in capmix.CATEGORY_SPLITS.items():
        assert sum(split.values()) == 100, category
        assert set(split) <= set(capmix.BUCKETS), category
        assert why, category            # the reason travels with the number


# ---- shares, which name nothing -----------------------------------------
def test_an_untagged_share_is_unclassified_not_guessed():
    split, why = capmix.cap_split({"asset_class": "stock",
                                   "name": "Some Smallco", "meta": {}})
    assert split == {} and why == ""


def test_a_tagged_share_uses_the_tag():
    split, why = capmix.cap_split({"asset_class": "stock", "name": "Reliance",
                                   "meta": {"cap": "large"}})
    assert split == {"large": 1.0} and why == "set by you"


def test_a_tag_overrides_what_the_name_would_say():
    """A fund the user knows better than its name does."""
    h = {"asset_class": "mutual_fund", "name": "DSP Midcap Fund",
         "meta": {"cap": "small"}}
    assert capmix.cap_split(h)[0] == {"small": 1.0}


def test_a_hand_written_split_is_honoured_and_normalised():
    h = {"asset_class": "mutual_fund", "name": "Anything",
         "meta": {"cap_split": {"large": 50, "mid": 25, "small": 25}}}
    split, why = capmix.cap_split(h)
    assert split == {"large": 0.5, "mid": 0.25, "small": 0.25}
    assert why == "set by you"


# ---- the mix over a portfolio -------------------------------------------
def equity_share(h):
    return (analytics.holding_splits(h).get("equity", 0.0)
            * analytics.holding_value(h))


PORTFOLIO = [
    {"asset_class": "mutual_fund", "name": "SBI Small Cap Fund - Direct - Growth",
     "units": 100, "avg_cost": 50, "last_price": 100, "meta": {"category": "equity"}},
    {"asset_class": "mutual_fund", "name": "ICICI Prudential Nifty 50 Index Fund",
     "units": 100, "avg_cost": 50, "last_price": 200, "meta": {"category": "equity"}},
    {"asset_class": "mutual_fund", "name": "HDFC Balanced Advantage Fund",
     "units": 100, "avg_cost": 50, "last_price": 100,
     "meta": {"category": "hybrid", "splits": {"equity": 65, "debt": 35}}},
    {"asset_class": "stock", "name": "Reliance", "units": 10, "avg_cost": 2400,
     "last_price": 3000, "meta": {"cap": "large"}},
    {"asset_class": "stock", "name": "Some Smallco", "units": 10,
     "avg_cost": 100, "last_price": 150, "meta": {}},
    {"asset_class": "mutual_fund", "name": "HDFC Corporate Bond Fund",
     "units": 100, "avg_cost": 20, "last_price": 25, "meta": {"category": "debt"}},
]


def test_only_the_equity_inside_a_holding_is_counted():
    mix = capmix.cap_mix(PORTFOLIO, equity_share)
    # 10,000 small + 20,000 index + 6,500 (65% of 10,000) + 30,000 + 1,500
    assert mix["total_equity"] == 68000.0
    named = {r["name"]: r["equity"] for r in mix["holdings"]}
    assert named["HDFC Balanced Advantage Fund"] == 6500.0
    assert "HDFC Corporate Bond Fund" not in named       # no equity at all


def test_the_percentages_are_of_what_could_be_classified():
    mix = capmix.cap_mix(PORTFOLIO, equity_share)
    assert abs(sum(mix["pct"].values()) - 100) < 0.2
    assert mix["unclassified"] == 1500.0
    assert mix["unclassified_pct"] == round(1500 / 68000 * 100, 1)


def test_each_holding_carries_the_reason_it_landed_where_it_did():
    mix = capmix.cap_mix(PORTFOLIO, equity_share)
    for row in mix["holdings"]:
        assert row["why"], row["name"]
    why = {r["name"]: r["why"] for r in mix["holdings"]}
    assert "SEBI" in why["SBI Small Cap Fund - Direct - Growth"]
    assert why["Some Smallco"] == "not classified"
    assert why["Reliance"] == "set by you"


def test_an_empty_portfolio_does_not_divide_by_zero():
    mix = capmix.cap_mix([], equity_share)
    assert mix["total_equity"] == 0
    assert mix["pct"] == {b: 0.0 for b in capmix.BUCKETS}
    assert mix["unclassified_pct"] == 0.0
