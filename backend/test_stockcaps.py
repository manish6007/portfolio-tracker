"""Shares classified from AMFI's list, without guessing and without nagging.

The risks here are quiet ones: a parser that reads the wrong column after
AMFI edits the spreadsheet, a refresh that hammers a half-yearly file, a
cached list that silently overrides what the user set by hand. Most of the
tests are about those, not the happy path.
"""
import os
import sys
from datetime import date, datetime, timedelta
from io import BytesIO

import openpyxl
import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import capmix  # noqa: E402
import config  # noqa: E402
import pricing  # noqa: E402
import stockcaps  # noqa: E402


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "BASE", str(tmp_path))
    monkeypatch.setattr(config, "CONFIG_PATH",
                        str(tmp_path / "app-config.json"))
    monkeypatch.delenv(config.ENV_DATA_DIR, raising=False)
    stockcaps.forget()
    yield tmp_path
    stockcaps.forget()


# The real file's header row, abbreviated but with the same shape: symbol
# columns for three exchanges, and the categorization at the end.
HEADERS = ["Sr. No.", "Company name", "ISIN", "BSE Symbol",
           "BSE 6 month Avg Total Market Cap in (Rs. Crs.)", "NSE Symbol",
           "NSE 6 month Avg Total Market Cap (Rs. Crs.)", "MSEI Symbol",
           "MSEI 6 month Avg Total Market Cap in (Rs Crs.)",
           "Average of All Exchanges (Rs. Cr.)",
           "Categorization as per SEBI Circular dated Oct 6, 2017"]

ROWS = [
    [1, "Reliance Industries Ltd", "INE002A01018", "RELIANCE", 187.0,
     "RELIANCE", 187.1, "-", None, 187.05, "Large Cap"],
    [2, "Federal Bank", "INE171A01029", "FEDERALBNK", 30.0, "FEDERALBNK",
     30.1, "-", None, 30.05, "Mid Cap"],
    [3, "Shilpa Medicare", "INE790G01031", "524742", 4.0, "SHILPAMED", 4.1,
     "-", None, 4.05, "Small Cap"],
]


def workbook(rows, headers=HEADERS):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Average Market Capitalization of listed companies"])
    ws.append(headers)
    for r in rows:
        ws.append(r)
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ---- reading the spreadsheet --------------------------------------------
def test_every_exchanges_symbol_lands_in_the_index():
    by_symbol, by_isin, _, _t = stockcaps.parse_workbook(workbook(ROWS))
    assert by_symbol["RELIANCE"] == "large"
    assert by_symbol["FEDERALBNK"] == "mid"
    assert by_symbol["SHILPAMED"] == "small"
    assert by_symbol["524742"] == "small"        # the BSE name of the same company
    assert by_isin["INE002A01018"] == "large"
    assert "-" not in by_symbol


def test_columns_are_found_by_name_not_position():
    """AMFI assembles this file by hand twice a year; a new column must
    shift nothing."""
    headers = HEADERS[:2] + ["A Surprise Column"] + HEADERS[2:]
    rows = [r[:2] + ["surprise"] + r[2:] for r in ROWS]
    by_symbol, by_isin, _, _t = stockcaps.parse_workbook(workbook(rows, headers))
    assert by_symbol["RELIANCE"] == "large"
    assert by_isin["INE790G01031"] == "small"


def test_a_row_with_no_recognisable_category_is_dropped():
    rows = ROWS + [[4, "Oddity Ltd", "INE000X01000", "ODDITY", 1.0, "ODDITY",
                    1.0, "-", None, 1.0, "Not categorised"]]
    by_symbol, _, _n, _t = stockcaps.parse_workbook(workbook(rows))
    assert "ODDITY" not in by_symbol


def test_a_malformed_isin_is_not_indexed():
    rows = [[1, "Broken", "n/a", "BROKEN", 1.0, "BROKEN", 1.0, "-", None,
             1.0, "Small Cap"]]
    by_symbol, by_isin, _, _t = stockcaps.parse_workbook(workbook(rows))
    assert by_symbol["BROKEN"] == "small"        # the symbol still counts
    assert by_isin == {}


def test_a_sheet_without_the_headers_yields_nothing():
    by_symbol, by_isin, by_name, _t = stockcaps.parse_workbook(
        workbook(ROWS, headers=["one", "two", "three"]))
    assert by_symbol == {} and by_isin == {} and by_name == {}


# ---- company names, for holdings that carry no ticker --------------------
def test_a_company_name_is_reduced_to_what_is_worth_comparing():
    assert stockcaps.normalise_name("Reliance Industries Ltd.") == "reliance"
    assert stockcaps.normalise_name("Bajaj Finance Limited") == "bajaj finance"
    assert stockcaps.normalise_name("Larsen & Toubro Limited") == "larsen toubro"


def test_two_companies_sharing_a_reduced_name_are_both_dropped():
    """A wrong bucket is worse than an empty one, so ambiguity loses."""
    rows = [[1, "Sterling Ltd", "INE111A01011", "STER1", 1.0, "STER1", 1.0,
             "-", None, 1.0, "Large Cap"],
            [2, "Sterling Limited", "INE222A01022", "STER2", 1.0, "STER2",
             1.0, "-", None, 1.0, "Small Cap"]]
    _, _, by_name, _t = stockcaps.parse_workbook(workbook(rows))
    assert "sterling" not in by_name


def test_the_same_company_listed_twice_in_one_bucket_survives():
    rows = [[1, "Twice Ltd", "INE111A01011", "TW1", 1.0, "TW1", 1.0, "-",
             None, 1.0, "Mid Cap"],
            [2, "Twice Limited", "INE222A01022", "TW2", 1.0, "TW2", 1.0, "-",
             None, 1.0, "Mid Cap"]]
    _, _, by_name, _t = stockcaps.parse_workbook(workbook(rows))
    assert by_name["twice"] == "mid"


# ---- the half-year calendar ----------------------------------------------
def test_period_ends_walk_backwards_from_today():
    assert stockcaps.period_ends(date(2026, 8, 30)) == \
        [date(2026, 6, 30), date(2025, 12, 31)]
    assert stockcaps.period_ends(date(2026, 1, 2)) == \
        [date(2025, 12, 31), date(2025, 6, 30)]
    assert stockcaps.period_ends(date(2026, 6, 30)) == \
        [date(2026, 6, 30), date(2025, 12, 31)]


def test_the_source_says_which_half_year_it_was():
    assert stockcaps.source_label(date(2026, 6, 30)) == \
        "AMFI's list, Jan–Jun 2026"
    assert stockcaps.source_label(date(2025, 12, 31)) == \
        "AMFI's list, Jul–Dec 2025"


# ---- looking a share up ---------------------------------------------------
def saved_list(as_of=None):
    return {"as_of": (as_of or stockcaps.period_ends()[0]).isoformat(),
            "fetched": datetime.now().isoformat(timespec="seconds"),
            "by_symbol": {"RELIANCE": "large", "FEDERALBNK": "mid"},
            "by_isin": {"INE002A01018": "large"},
            "by_name": {"bajaj finance": "large"},
            "tickers": {"INE002A01018": "RELIANCE"}}


def test_lookup_ignores_a_yahoo_exchange_suffix(store):
    stockcaps.save(saved_list())
    assert stockcaps.lookup("RELIANCE")[0] == "large"
    assert stockcaps.lookup("RELIANCE.NS")[0] == "large"
    assert stockcaps.lookup("reliance")[0] == "large"


def test_lookup_falls_back_to_the_isin(store):
    stockcaps.save(saved_list())
    assert stockcaps.lookup("", "INE002A01018")[0] == "large"


def test_a_share_not_on_the_list_is_simply_not_found(store):
    stockcaps.save(saved_list())
    assert stockcaps.lookup("AAPL") == (None, "")


def test_a_holding_with_no_ticker_is_matched_by_its_name(store):
    stockcaps.save(saved_list())
    bucket, why = stockcaps.lookup("", "", "Bajaj Finance Ltd.")
    assert bucket == "large"
    assert why.endswith(", matched by name")   # the weaker match says so


def test_a_name_that_is_really_a_ticker_is_an_exact_match(store):
    """Imports name a holding by its NSE symbol more often than not, and
    that is a ticker, not a name to be matched loosely."""
    stockcaps.save(saved_list())
    bucket, why = stockcaps.lookup("", "", "FEDERALBNK")
    assert bucket == "mid"
    assert "matched by name" not in why


def test_an_isin_in_the_identifier_field_is_read_as_one(store):
    """Identifier holds a ticker for some holdings and an ISIN for others,
    depending on what put it there."""
    stockcaps.save(saved_list())
    bucket, why = stockcaps.lookup("INE002A01018", "", "Some Old Name")
    assert bucket == "large"
    assert "matched by name" not in why


def test_an_isin_shaped_identifier_is_not_hunted_for_as_a_ticker(store):
    data = saved_list()
    data["by_symbol"]["INE002A01018"] = "small"   # never in the real file
    stockcaps.save(data)
    assert stockcaps.lookup("INE002A01018")[0] == "large"


def test_a_ticker_beats_a_name_that_disagrees(store):
    data = saved_list()
    data["by_name"] = {"reliance": "small"}
    stockcaps.save(data)
    bucket, why = stockcaps.lookup("RELIANCE", "", "Reliance Industries Ltd")
    assert bucket == "large"
    assert "matched by name" not in why


def test_no_cache_means_no_answer_and_no_network(store, monkeypatch):
    def explode(*a, **k):
        raise AssertionError("lookup opened a connection")
    monkeypatch.setattr(pricing, "_get", explode)
    assert stockcaps.lookup("RELIANCE") == (None, "")


# ---- what capmix does with it --------------------------------------------
def test_a_listed_share_classifies_itself(store):
    stockcaps.save(saved_list(date(2026, 6, 30)))
    split, why = capmix.cap_split({"asset_class": "stock",
                                   "identifier": "FEDERALBNK",
                                   "name": "Federal Bank", "meta": {}})
    assert split == {"mid": 1.0}
    assert why == "AMFI's list, Jan–Jun 2026"


def test_the_users_own_tag_still_wins(store):
    stockcaps.save(saved_list())
    split, why = capmix.cap_split({"asset_class": "stock",
                                   "identifier": "RELIANCE",
                                   "name": "Reliance",
                                   "meta": {"cap": "small"}})
    assert split == {"small": 1.0} and why == "set by you"


def test_an_unlisted_share_stays_unclassified(store):
    stockcaps.save(saved_list())
    split, why = capmix.cap_split({"asset_class": "stock",
                                   "identifier": "AAPL",
                                   "name": "Apple", "meta": {}})
    assert split == {} and why == ""


# ---- refreshing without hammering ----------------------------------------
def test_a_current_list_is_not_fetched_again(store, monkeypatch):
    stockcaps.save(saved_list())

    def explode(*a, **k):
        raise AssertionError("a fresh list was re-fetched")
    monkeypatch.setattr(stockcaps, "fetch", explode)
    assert stockcaps.refresh()["status"] == "fresh"


def test_a_stale_list_is_replaced_by_a_newer_one(store, monkeypatch):
    old = stockcaps.period_ends()[1]
    stockcaps.save(saved_list(old))
    monkeypatch.setattr(stockcaps, "fetch", lambda timeout=60: saved_list())
    out = stockcaps.refresh()
    assert out["status"] == "updated"
    assert out["as_of"] == stockcaps.period_ends()[0].isoformat()


def test_a_failed_fetch_keeps_the_old_list(store, monkeypatch):
    old = stockcaps.period_ends()[1]
    stockcaps.save(saved_list(old))
    monkeypatch.setattr(stockcaps, "fetch", lambda timeout=60: None)
    out = stockcaps.refresh()
    assert out["status"] == "kept"
    assert out["as_of"] == old.isoformat()
    assert stockcaps.lookup("RELIANCE")[0] == "large"


def test_a_recent_failed_attempt_is_not_retried(store, monkeypatch):
    monkeypatch.setattr(stockcaps, "fetch", lambda timeout=60: None)
    assert stockcaps.refresh()["status"] == "unavailable"

    def explode(timeout=60):
        raise AssertionError("re-fetched within the recheck window")
    monkeypatch.setattr(stockcaps, "fetch", explode)
    assert stockcaps.refresh()["status"] == "unavailable"


def test_the_recheck_window_expires(store, monkeypatch):
    stale = saved_list(stockcaps.period_ends()[1])
    stale["checked"] = (datetime.now()
                        - timedelta(hours=stockcaps.RECHECK_HOURS + 1)
                        ).isoformat(timespec="seconds")
    stockcaps.save(stale)
    monkeypatch.setattr(stockcaps, "fetch", lambda timeout=60: saved_list())
    assert stockcaps.refresh()["status"] == "updated"


def test_offline_mode_stops_the_fetch_at_the_first_door(store, monkeypatch):
    calls = []

    def offline(url, timeout):
        calls.append(url)
        raise pricing.Offline("offline mode is on")
    monkeypatch.setattr(pricing, "_get", offline)
    assert stockcaps.fetch() is None
    assert len(calls) == 1               # not six attempts against a wall


def test_a_cache_written_before_the_ticker_index_is_refetched(store,
                                                              monkeypatch):
    """"Current half-year" used to mean "never refetch", so a cache saved
    before this index existed answered nothing for the whole period."""
    stale = saved_list()
    stale.pop("tickers", None)
    stockcaps.save(stale)
    assert stockcaps.has_tickers() is False

    fresh = saved_list()
    monkeypatch.setattr(stockcaps, "fetch", lambda timeout=60: fresh)
    assert stockcaps.refresh()["status"] in ("updated", "fresh")
    assert stockcaps.has_tickers() is True


def test_a_complete_current_cache_is_left_alone(store, monkeypatch):
    stockcaps.save(saved_list())

    def explode(timeout=60):
        raise AssertionError("a complete, current list was refetched")
    monkeypatch.setattr(stockcaps, "fetch", explode)
    assert stockcaps.refresh()["status"] == "fresh"


def test_an_isin_resolves_to_what_the_company_trades_as(store):
    stockcaps.save(saved_list())
    assert stockcaps.ticker_for("INE002A01018") == "RELIANCE"
    assert stockcaps.ticker_for("INE999Z01011") == ""
    assert stockcaps.ticker_for("") == ""


def test_the_nse_ticker_is_preferred_over_a_numeric_bse_code():
    """A holding is keyed by its NSE symbol; the BSE column is a number."""
    _s, _i, _n, tickers = stockcaps.parse_workbook(workbook(ROWS))
    assert tickers["INE790G01031"] == "SHILPAMED"     # not 524742
