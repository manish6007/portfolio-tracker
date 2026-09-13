"""Broker tradebooks: trades, not positions.

A holdings export and a tradebook look alike to a column sniffer -- both
carry a symbol, a quantity and a price -- and importing one as the other is
a disaster: four hundred trades become four hundred holdings. Most of what
is tested here is that distinction, and the arithmetic that keeps a book of
history from inflating a position it is merely describing.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import importers as imp  # noqa: E402

ZERODHA = """symbol,isin,trade_date,exchange,trade_type,quantity,price
FEDERALBNK,INE171A01029,2026-01-01,NSE,sell,50.000000,264.850006
APLAPOLLO,INE702C01027,2026-01-01,NSE,buy,5.000000,1970.000000
APLAPOLLO,INE702C01027,2026-02-02,NSE,buy,5.000000,1980.000000
"""

KOTAK = """Trade Date,Security Name,ISIN,Transaction Type,Quantity,Market Rate,Total Charges
31/08/2026,Titan Company Ltd,INE280A01028   ,Buy,3,5125.4,26.48
31/08/2026,Tata Consumer Products Ltd,INE192A01025   ,Sell,13,1031.1,24.1
06/07/2026,TD Power Systems Ltd,INE419M01027   ,Sell,35,1097.2,46.76
31/08/2026,TD Power Systems Ltd,INE419M01035   ,Buy,20,756.7,26.43
"""

HOLDINGS = """Symbol,Quantity Available,Average Price
TITAN,8,4494.00
"""


def table(text):
    return imp.read_table(text.encode(), "x.csv")


# ---- telling a tradebook from a position list ---------------------------
def test_a_tradebook_is_recognised_by_its_buy_and_sell_column():
    """A position has no direction; a trade is nothing without one."""
    for text in (ZERODHA, KOTAK):
        headers, records = table(text)
        assert imp.looks_like_tradebook(headers, records)


def test_a_holdings_export_is_not_mistaken_for_a_tradebook():
    headers, records = table(HOLDINGS)
    assert not imp.looks_like_tradebook(headers, records)


def test_columns_are_found_in_either_broker_s_wording():
    z = imp.trade_columns(table(ZERODHA)[0])
    k = imp.trade_columns(table(KOTAK)[0])
    assert z["side"] == "trade_type" and z["symbol"] == "symbol"
    assert k["side"] == "Transaction Type" and k["name"] == "Security Name"
    assert k["charges"] == "Total Charges"


# ---- reading the rows ----------------------------------------------------
def test_both_date_formats_are_read():
    """One broker writes 2026-01-01 and the other 31/08/2026."""
    assert imp._trade_date("2026-01-01") == "2026-01-01"
    assert imp._trade_date("31/08/2026") == "2026-08-31"
    assert imp._trade_date("2026-01-01T14:21:15") == "2026-01-01"
    assert imp._trade_date("10-Apr-2017") == "2017-04-10"
    assert imp._trade_date("nonsense") == ""


def test_every_trade_is_read_with_its_side():
    """Returned oldest first, then by name, so a replay can just walk them."""
    trades, notes = imp.parse_tradebook(*table(ZERODHA))
    assert notes == []
    assert [(t["date"], t["name"], t["type"]) for t in trades] == [
        ("2026-01-01", "APLAPOLLO", "buy"),
        ("2026-01-01", "FEDERALBNK", "sell"),
        ("2026-02-02", "APLAPOLLO", "buy")]
    sold = next(t for t in trades if t["type"] == "sell")
    assert sold["units"] == 50 and sold["price"] == pytest.approx(264.85)


def test_charges_are_kept_where_the_broker_reports_them():
    trades, _ = imp.parse_tradebook(*table(KOTAK))
    titan = next(t for t in trades if "Titan" in t["name"])
    assert titan["charges"] == pytest.approx(26.48)


def test_a_padded_isin_is_still_an_isin():
    """One broker pads the column to a fixed width."""
    trades, _ = imp.parse_tradebook(*table(KOTAK))
    assert trades[0]["isin"].strip() == trades[0]["isin"]
    assert all(len(t["isin"]) == 12 for t in trades if t["isin"])


def test_a_row_that_is_not_a_trade_is_counted_not_guessed():
    text = ZERODHA + "GARBAGE,,,,buy,,\n"
    trades, notes = imp.parse_tradebook(*table(text))
    assert len(trades) == 3
    assert notes and "could not be read" in notes[0]


# ---- gathering trades into holdings --------------------------------------
def test_trades_are_gathered_per_company():
    groups = imp.group_trades(imp.parse_tradebook(*table(ZERODHA))[0])
    by_name = {g["symbol"]: g for g in groups}
    assert len(by_name["APLAPOLLO"]["trades"]) == 2
    assert len(by_name["FEDERALBNK"]["trades"]) == 1


def test_a_company_that_changed_isin_stays_one_holding():
    """A split or a scheme of arrangement issues a new code; it is still the
    same company, and keying on the ISIN would file it twice."""
    groups = imp.group_trades(imp.parse_tradebook(*table(KOTAK))[0])
    td = [g for g in groups if "TD Power" in g["name"]]
    assert len(td) == 1
    assert len(td[0]["trades"]) == 2
    assert len(td[0]["isins"]) == 2        # both codes remembered


def test_trades_come_back_oldest_first():
    groups = imp.group_trades(imp.parse_tradebook(*table(KOTAK))[0])
    for g in groups:
        dates = [t["date"] for t in g["trades"]]
        assert dates == sorted(dates)


def test_a_company_name_never_becomes_a_ticker():
    """A book that prints no ticker used to have its company name written
    into the field that prices a share. Nothing could price
    "NGL FINE CHEM LTD", so the holding showed its whole cost as a loss."""
    groups = imp.group_trades(imp.parse_tradebook(*table(KOTAK))[0])
    assert all(g["symbol"] == "" for g in groups)
    assert all(" " not in g["symbol"] for g in groups)


def test_a_book_that_does_print_tickers_keeps_them():
    groups = imp.group_trades(imp.parse_tradebook(*table(ZERODHA))[0])
    assert {g["symbol"] for g in groups} == {"FEDERALBNK", "APLAPOLLO"}


def test_grouping_still_gathers_a_company_with_no_ticker():
    """The name is used to gather the trades; it just never poses as a
    ticker afterwards."""
    groups = imp.group_trades(imp.parse_tradebook(*table(KOTAK))[0])
    assert {g["name"] for g in groups} >= {"Titan Company Ltd"}
    assert all(g["key"] for g in groups)
