"""Purchases, sales, capital, and re-importing a statement.

Two things here can lose real money quietly. Re-importing last quarter's
statement used to add a second copy of every holding, so a portfolio doubled
without a single error message. And converting balances into purchase
parcels touches every existing position at once, so it is tested against the
shape of a database that has been in use rather than a fresh one.
"""
import json
import os
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config  # noqa: E402
import db  # noqa: E402
import ledger  # noqa: E402
import main  # noqa: E402
import stockcaps  # noqa: E402


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "BASE", str(tmp_path))
    monkeypatch.setattr(config, "CONFIG_PATH",
                        str(tmp_path / "app-config.json"))
    monkeypatch.delenv(config.ENV_DATA_DIR, raising=False)
    monkeypatch.setattr(db, "_engines", {})
    monkeypatch.setattr(db, "_factories", {})
    monkeypatch.setattr(stockcaps, "fetch", lambda timeout=60: None)
    stockcaps.forget()
    with TestClient(main.app, base_url="http://localhost:8000") as c:
        yield c


WRITE = {"Sec-Fetch-Site": "same-origin"}


def cas_row(units=100.0, avg_cost=50.0, folio="F123",
            isin="INE002A01018", name="Axis Bluechip Fund - Direct - Growth",
            txns=None):
    """One row as the CAS parser hands it to the commit endpoint."""
    return {"asset_class": "mutual_fund", "name": name, "identifier": folio,
            "scheme_code": "120503", "isin": isin, "units": units,
            "avg_cost": avg_cost, "last_price": 60.0, "category": "equity",
            "transactions": txns if txns is not None else [
                {"date": "2026-01-10", "type": "buy", "amount": 5000.0,
                 "units": 100.0}]}


def commit(client, rows, owner=None):
    body = {"rows": rows}
    if owner:
        body["owner"] = owner
    r = client.post("/api/import/commit", json=body, headers=WRITE)
    assert r.status_code == 200, r.text
    return r.json()


def holdings(client):
    return client.get("/api/holdings").json()


# ---- re-importing a statement -------------------------------------------
def test_importing_the_same_statement_twice_does_not_duplicate_anything(client):
    """The bug this whole mechanism exists to prevent: a second upload of
    last quarter's file used to double the portfolio in silence."""
    first = commit(client, [cas_row()])
    assert (first["added"], first["updated"]) == (1, 0)

    second = commit(client, [cas_row()])
    assert (second["added"], second["updated"]) == (0, 1)

    rows = [h for h in holdings(client) if h["asset_class"] == "mutual_fund"]
    assert len(rows) == 1
    assert rows[0]["units"] == 100.0
    txns = client.get("/api/holdings/%d/transactions" % rows[0]["id"]).json()
    assert len(txns) == 1


def test_a_newer_statement_replaces_the_units_rather_than_adding_to_them(client):
    commit(client, [cas_row(units=100.0)])
    commit(client, [cas_row(units=130.0, avg_cost=52.0)])
    row = [h for h in holdings(client) if h["asset_class"] == "mutual_fund"][0]
    assert row["units"] == 130.0
    assert row["avg_cost"] == 52.0


def test_what_the_user_set_by_hand_survives_a_re_import(client):
    """A statement knows units and cost. It does not know the company-size
    tag, the split, or the note, and must not flatten them."""
    commit(client, [cas_row()])
    hid = holdings(client)[0]["id"]
    client.put("/api/holdings/%d" % hid,
               json={"meta": {"cap": "small"}, "notes": "kept for the kids"},
               headers=WRITE)

    commit(client, [cas_row(units=140.0)])
    row = [h for h in holdings(client) if h["id"] == hid][0]
    assert row["meta"]["cap"] == "small"
    assert row["notes"] == "kept for the kids"
    assert row["units"] == 140.0          # the statement still won on units


def test_a_transaction_entered_by_hand_survives_a_re_import(client):
    """The importer may remove what it wrote before. It may not remove what
    a person wrote."""
    commit(client, [cas_row()])
    hid = holdings(client)[0]["id"]
    client.post("/api/holdings/%d/transactions" % hid,
                json={"date": "2026-02-01", "type": "buy", "amount": 1000.0,
                      "units": 20.0}, headers=WRITE)
    commit(client, [cas_row()])

    txns = client.get("/api/holdings/%d/transactions" % hid).json()
    assert len(txns) == 2
    assert any(t["date"] == "2026-02-01" for t in txns)


def test_a_holding_missing_from_the_new_statement_is_left_alone(client):
    """Absence means "this file did not cover it" at least as often as it
    means "sold" — a CAMS statement carries no KFintech folios."""
    commit(client, [cas_row(folio="F1", isin="INE002A01018", name="Fund One"),
                    cas_row(folio="F2", isin="INE040A01034", name="Fund Two")])
    commit(client, [cas_row(folio="F1", isin="INE002A01018", name="Fund One",
                            units=120.0)])
    names = {h["name"] for h in holdings(client)}
    assert names == {"Fund One", "Fund Two"}


def test_the_same_scheme_in_two_folios_stays_two_holdings(client):
    commit(client, [cas_row(folio="F1"), cas_row(folio="F2")])
    assert len([h for h in holdings(client)
                if h["asset_class"] == "mutual_fund"]) == 2


def test_the_same_fund_held_by_two_people_is_not_merged(client):
    """Merging them would silently move somebody's money."""
    commit(client, [cas_row()], owner="Me")
    commit(client, [cas_row()], owner="Spouse")
    rows = [h for h in holdings(client) if h["asset_class"] == "mutual_fund"]
    assert len(rows) == 2
    assert {h["owner"] for h in rows} == {"Me", "Spouse"}


def test_an_imported_holding_carries_a_position_the_journal_can_read(client):
    commit(client, [cas_row(units=100.0, avg_cost=50.0)])
    row = holdings(client)[0]
    assert row["units"] == 100.0
    assert row["invested"] == pytest.approx(5000.0)


# ---- buying through the journal -----------------------------------------
def buy(client, **kw):
    body = {"date": "2026-06-01", "units": 10, "price": 100, "charges": 0}
    body.update(kw)
    r = client.post("/api/journal/buy", json=body, headers=WRITE)
    return r


def test_a_first_purchase_opens_the_position(client):
    r = buy(client, name="Reliance Industries", identifier="RELIANCE")
    assert r.status_code == 200, r.text
    assert r.json()["units"] == 10

    row = [h for h in holdings(client) if h["name"] == "Reliance Industries"][0]
    assert row["units"] == 10 and row["avg_cost"] == 100


def test_charges_land_in_the_cost_base_not_just_the_notes(client):
    r = buy(client, name="Titan", identifier="TITAN", charges=50)
    hid = r.json()["holding_id"]
    row = [h for h in holdings(client) if h["id"] == hid][0]
    assert row["avg_cost"] == pytest.approx(105.0)
    assert row["invested"] == pytest.approx(1050.0)


def test_a_second_purchase_averages_in_and_keeps_both_parcels(client):
    hid = buy(client, name="Titan", identifier="TITAN").json()["holding_id"]
    buy(client, holding_id=hid, date="2026-07-01", units=10, price=200)
    body = client.get("/api/journal").json()
    position = [p for p in body["positions"] if p["holding_id"] == hid][0]
    assert position["units"] == 20
    assert position["avg_cost"] == pytest.approx(150)
    assert len(position["lots"]) == 2


def test_a_purchase_shows_up_in_net_worth(client):
    """The journal is a write surface for the pages that already exist."""
    before = client.get("/api/summary").json()["total_assets"]
    buy(client, name="Titan", identifier="TITAN", units=10, price=100)
    after = client.get("/api/summary").json()["total_assets"]
    assert after - before == pytest.approx(1000.0)


def test_a_purchase_without_a_name_or_a_holding_is_refused(client):
    r = client.post("/api/journal/buy",
                    json={"date": "2026-06-01", "units": 1, "price": 10},
                    headers=WRITE)
    assert r.status_code == 422


def test_the_journal_refuses_a_fund_and_says_where_to_go_instead(client):
    """A sale recorded by hand against a parcel the next statement replaces
    would leave a realised trade pointing at nothing."""
    commit(client, [cas_row()])
    hid = holdings(client)[0]["id"]
    r = client.post("/api/journal/sell",
                    json={"holding_id": hid, "date": "2026-08-01", "units": 1,
                          "price": 60, "reason": "target"}, headers=WRITE)
    assert r.status_code == 400
    assert "Portfolio page" in r.json()["detail"]


def test_funds_do_not_appear_among_the_journals_positions(client):
    commit(client, [cas_row()])
    buy(client, name="Titan", identifier="TITAN")
    names = {p["name"] for p in client.get("/api/journal").json()["positions"]}
    assert names == {"Titan"}


def test_a_purchase_records_the_stop_the_buyer_committed_to(client):
    hid = buy(client, name="Titan", identifier="TITAN",
              stoploss=90).json()["holding_id"]
    body = client.get("/api/journal").json()
    position = [p for p in body["positions"] if p["holding_id"] == hid][0]
    assert position["lots"][0]["stoploss"] == 90


# ---- selling ------------------------------------------------------------
def test_a_sale_reduces_the_position_and_books_what_it_realised(client):
    hid = buy(client, name="Titan", identifier="TITAN",
              units=10, price=100).json()["holding_id"]
    r = client.post("/api/journal/sell",
                    json={"holding_id": hid, "date": "2026-08-01", "units": 4,
                          "price": 150, "charges": 0, "reason": "target"},
                    headers=WRITE)
    assert r.status_code == 200, r.text
    assert r.json()["units_left"] == 6
    assert r.json()["realised"] == pytest.approx(200.0)

    body = client.get("/api/journal").json()
    assert body["realised"]["realised"] == pytest.approx(200.0)
    assert body["trades"][0]["reason_label"] == "Target reached"


def test_selling_more_than_is_held_is_refused_with_a_usable_message(client):
    hid = buy(client, name="Titan", identifier="TITAN",
              units=10, price=100).json()["holding_id"]
    r = client.post("/api/journal/sell",
                    json={"holding_id": hid, "date": "2026-08-01", "units": 11,
                          "price": 150, "reason": "target"}, headers=WRITE)
    assert r.status_code == 400
    assert "10" in r.json()["detail"]
    # and the position is untouched
    assert [h for h in holdings(client) if h["id"] == hid][0]["units"] == 10


def test_a_sale_needs_a_reason_the_app_can_count(client):
    hid = buy(client, name="Titan", identifier="TITAN").json()["holding_id"]
    r = client.post("/api/journal/sell",
                    json={"holding_id": hid, "date": "2026-08-01", "units": 1,
                          "price": 150, "reason": "felt like it"},
                    headers=WRITE)
    assert r.status_code == 422


def test_stop_loss_exits_are_reported_apart_from_the_rest(client):
    hid = buy(client, name="Titan", identifier="TITAN",
              units=10, price=100).json()["holding_id"]
    client.post("/api/journal/sell",
                json={"holding_id": hid, "date": "2026-08-01", "units": 5,
                      "price": 80, "reason": "stoploss"}, headers=WRITE)
    client.post("/api/journal/sell",
                json={"holding_id": hid, "date": "2026-08-02", "units": 5,
                      "price": 130, "reason": "target"}, headers=WRITE)
    body = client.get("/api/journal").json()
    assert body["stoploss"]["stopped"]["realised"] == pytest.approx(-100.0)
    assert body["stoploss"]["other_exits"]["realised"] == pytest.approx(150.0)


def test_a_fully_exited_position_leaves_the_open_list(client):
    hid = buy(client, name="Titan", identifier="TITAN",
              units=10, price=100).json()["holding_id"]
    client.post("/api/journal/sell",
                json={"holding_id": hid, "date": "2026-08-01", "units": 10,
                      "price": 130, "reason": "target"}, headers=WRITE)
    body = client.get("/api/journal").json()
    assert [p for p in body["positions"] if p["holding_id"] == hid] == []
    assert body["trades"][0]["units"] == 10


# ---- capital in and out --------------------------------------------------
def test_capital_is_tracked_apart_from_what_it_bought(client):
    """Money arriving and money being deployed are different events, and the
    monthly question needs both."""
    client.post("/api/journal/capital",
                json={"date": "2026-06-01", "direction": "in",
                      "amount": 100000}, headers=WRITE)
    client.post("/api/journal/capital",
                json={"date": "2026-07-01", "direction": "out",
                      "amount": 20000}, headers=WRITE)
    body = client.get("/api/journal").json()
    assert body["capital"]["net"] == 80000
    assert len(body["capital"]["flows"]) == 2


def test_a_capital_flow_can_be_removed(client):
    client.post("/api/journal/capital",
                json={"date": "2026-06-01", "direction": "in",
                      "amount": 5000}, headers=WRITE)
    fid = client.get("/api/journal").json()["capital"]["flows"][0]["id"]
    client.delete("/api/journal/capital/%d" % fid, headers=WRITE)
    assert client.get("/api/journal").json()["capital"]["net"] == 0


# ---- converting a database that predates lots ---------------------------
def as_pre_lots_database(path, monkeypatch):
    """Reopen `path` as a database created before lots existed.

    A file in use for a year has holdings and no conversion marker. Creating
    one through get_session writes the marker immediately -- correctly, since
    there was nothing to convert -- so the marker is cleared here to leave
    the shape a real upgrade actually meets.
    """
    from sqlalchemy import create_engine, text
    engine = create_engine("sqlite:///%s" % path)
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM settings WHERE key = :k"),
                     {"k": db.LOTS_BACKFILLED})
        conn.execute(text("DELETE FROM lots"))
    engine.dispose()
    db.reset_engines()
    monkeypatch.setattr(db, "_engines", {})
    monkeypatch.setattr(db, "_factories", {})
    return db.get_session(path)


def test_an_existing_holding_keeps_its_position_when_lots_arrive(tmp_path,
                                                                 monkeypatch):
    """The risky half of this change: every position in a database that has
    been in use for a year is converted at once, and must come out
    identical."""
    monkeypatch.setattr(config, "BASE", str(tmp_path))
    monkeypatch.setattr(config, "CONFIG_PATH",
                        str(tmp_path / "app-config.json"))
    monkeypatch.delenv(config.ENV_DATA_DIR, raising=False)
    monkeypatch.setattr(db, "_engines", {})
    monkeypatch.setattr(db, "_factories", {})
    path = str(tmp_path / "portfolio.db")

    s = db.get_session(path)
    owner = db.Owner(name="Me")
    s.add(owner)
    s.commit()
    s.add(db.Holding(owner_id=owner.id, asset_class="stock", name="Old Co",
                     identifier="OLD", units=37.0, avg_cost=412.5,
                     last_price=500.0, meta=json.dumps({"cap": "mid"})))
    # A balance-based holding has no units and must not gain a lot.
    s.add(db.Holding(owner_id=owner.id, asset_class="epf", name="EPF",
                     manual_value=250000.0))
    s.commit()
    s.close()

    s = as_pre_lots_database(path, monkeypatch)
    stock = s.query(db.Holding).filter(db.Holding.name == "Old Co").first()
    assert len(stock.lots) == 1
    assert stock.lots[0].source == db.SOURCE_OPENING
    units, avg = ledger.position(stock.lots)
    assert (units, avg) == (37.0, 412.5)
    assert stock.meta_dict()["cap"] == "mid"      # untouched by the migration
    # Nothing recorded when it was bought, so the ledger must not imply it.
    assert stock.lots[0].date_known == 0

    epf = s.query(db.Holding).filter(db.Holding.name == "EPF").first()
    assert epf.lots == []
    s.close()


def test_the_conversion_does_not_run_twice(tmp_path, monkeypatch):
    """A position sold down to nothing must not be resurrected on restart."""
    monkeypatch.setattr(config, "BASE", str(tmp_path))
    monkeypatch.setattr(config, "CONFIG_PATH",
                        str(tmp_path / "app-config.json"))
    monkeypatch.delenv(config.ENV_DATA_DIR, raising=False)
    monkeypatch.setattr(db, "_engines", {})
    monkeypatch.setattr(db, "_factories", {})
    path = str(tmp_path / "portfolio.db")

    s = db.get_session(path)
    owner = db.Owner(name="Me")
    s.add(owner)
    s.commit()
    s.add(db.Holding(owner_id=owner.id, asset_class="stock", name="Old Co",
                     units=10.0, avg_cost=100.0))
    s.commit()
    s.close()

    s = as_pre_lots_database(path, monkeypatch)
    stock = s.query(db.Holding).filter(db.Holding.name == "Old Co").first()
    assert len(stock.lots) == 1
    s.close()

    # Start again, twice more. The conversion has already happened, so it
    # must not add a second opening lot to a position it already converted.
    for _ in range(2):
        db.reset_engines()
        monkeypatch.setattr(db, "_engines", {})
        monkeypatch.setattr(db, "_factories", {})
        s = db.get_session(path)
        stock = s.query(db.Holding).filter(db.Holding.name == "Old Co").first()
        assert len(stock.lots) == 1
        s.close()


# ---- core against satellite ----------------------------------------------
def test_a_purchase_can_be_filed_under_a_sleeve(client):
    r = buy(client, name="Core Co", identifier="CORE", sleeve="core")
    assert r.status_code == 200, r.text
    p = client.get("/api/journal").json()["positions"][0]
    assert p["sleeve"] == "core"


def test_the_two_sleeves_are_reported_apart_and_together(client):
    """A losing trading habit must not be able to hide inside a compounding
    long-term position, or the reverse."""
    buy(client, name="Core Co", identifier="CORE", units=10, price=100,
        sleeve="core")
    buy(client, name="Sat Co", identifier="SAT", units=10, price=100,
        sleeve="satellite")
    rows = {r["sleeve"]: r for r
            in client.get("/api/journal").json()["by_sleeve"]["sleeves"]}
    assert rows["core"]["deployed"] == 1000
    assert rows["satellite"]["deployed"] == 1000
    total = client.get("/api/journal").json()["by_sleeve"]["total"]
    assert total["deployed"] == 2000


def test_a_closed_trade_stays_with_the_sleeve_that_took_the_risk(client):
    hid = buy(client, name="Sat Co", identifier="SAT", units=10, price=100,
              sleeve="satellite").json()["holding_id"]
    client.post("/api/journal/sell",
                json={"holding_id": hid, "date": "2026-08-01", "units": 10,
                      "price": 80, "reason": "stoploss"}, headers=WRITE)
    body = client.get("/api/journal").json()
    rows = {r["sleeve"]: r for r in body["by_sleeve"]["sleeves"]}
    assert rows["satellite"]["realised"] == pytest.approx(-200)
    assert rows["core"]["realised"] == 0
    assert body["trades"][0]["sleeve_label"] == "Satellite"


def test_total_profit_is_unrealised_plus_realised(client):
    hid = buy(client, name="Core Co", identifier="CORE", units=20, price=100,
              sleeve="core").json()["holding_id"]
    client.post("/api/journal/sell",
                json={"holding_id": hid, "date": "2026-08-01", "units": 10,
                      "price": 150, "reason": "target"}, headers=WRITE)
    core = {r["sleeve"]: r for r
            in client.get("/api/journal").json()["by_sleeve"]["sleeves"]}["core"]
    assert core["deployed"] == 1000            # ten units still held
    assert core["realised"] == pytest.approx(500)
    assert core["total_pnl"] == pytest.approx(core["unrealised"] + 500)


def test_an_unassigned_position_is_shown_as_itself(client):
    buy(client, name="Untagged Co", identifier="UNTAG", units=10, price=100)
    rows = {r["sleeve"]: r for r
            in client.get("/api/journal").json()["by_sleeve"]["sleeves"]}
    assert rows[""]["deployed"] == 1000
    assert rows["core"]["deployed"] == 0


def test_a_position_can_be_filed_after_the_fact(client):
    hid = buy(client, name="Untagged Co", identifier="UNTAG",
              units=10, price=100).json()["holding_id"]
    r = client.put("/api/journal/%d/sleeve" % hid,
                   json={"sleeve": "core"}, headers=WRITE)
    assert r.status_code == 200, r.text
    rows = {x["sleeve"]: x for x
            in client.get("/api/journal").json()["by_sleeve"]["sleeves"]}
    assert rows["core"]["deployed"] == 1000


def test_refiling_a_position_leaves_closed_trades_where_they_were(client):
    """Re-labelling history would rewrite what each sleeve is recorded as
    having earned."""
    hid = buy(client, name="Sat Co", identifier="SAT", units=20, price=100,
              sleeve="satellite").json()["holding_id"]
    client.post("/api/journal/sell",
                json={"holding_id": hid, "date": "2026-08-01", "units": 10,
                      "price": 150, "reason": "target"}, headers=WRITE)
    client.put("/api/journal/%d/sleeve" % hid, json={"sleeve": "core"},
               headers=WRITE)
    rows = {r["sleeve"]: r for r
            in client.get("/api/journal").json()["by_sleeve"]["sleeves"]}
    assert rows["satellite"]["realised"] == pytest.approx(500)  # stayed put
    assert rows["core"]["deployed"] == 1000                     # units moved


def test_adding_to_a_position_keeps_it_in_its_sleeve(client):
    hid = buy(client, name="Core Co", identifier="CORE", units=10, price=100,
              sleeve="core").json()["holding_id"]
    buy(client, holding_id=hid, date="2026-07-01", units=10, price=120)
    p = client.get("/api/journal").json()["positions"][0]
    assert p["sleeve"] == "core"


def test_one_company_can_be_held_in_both_sleeves(client):
    """A long-term holding and a tactical trade in the same name is a real
    thing to do, and averaging them into one position hides both."""
    hid = buy(client, name="Both Co", identifier="BOTH", units=10, price=100,
              sleeve="core").json()["holding_id"]
    buy(client, holding_id=hid, date="2026-07-01", units=10, price=200,
        sleeve="satellite")
    body = client.get("/api/journal").json()
    assert body["positions"][0]["sleeve"] == "mixed"
    rows = {r["sleeve"]: r for r in body["by_sleeve"]["sleeves"]}
    assert rows["core"]["deployed"] == 1000
    assert rows["satellite"]["deployed"] == 2000


def test_an_unknown_sleeve_is_refused(client):
    r = client.post("/api/journal/buy",
                    json={"name": "X", "date": "2026-06-01", "units": 1,
                          "price": 10, "sleeve": "medium"}, headers=WRITE)
    assert r.status_code == 422


# ---- capital deployed ----------------------------------------------------
def test_deployed_is_the_cost_of_open_positions(client):
    buy(client, name="Core Co", identifier="CORE", units=10, price=100,
        charges=50, sleeve="core")
    body = client.get("/api/journal").json()
    assert body["deployed"] == pytest.approx(1050)


def test_selling_returns_capital_rather_than_leaving_it_deployed(client):
    hid = buy(client, name="Core Co", identifier="CORE", units=10, price=100,
              sleeve="core").json()["holding_id"]
    client.post("/api/journal/sell",
                json={"holding_id": hid, "date": "2026-08-01", "units": 6,
                      "price": 150, "reason": "target"}, headers=WRITE)
    assert client.get("/api/journal").json()["deployed"] == pytest.approx(400)


# ---- correcting an entry -------------------------------------------------
def lots_of(client, hid):
    body = client.get("/api/journal").json()
    p = [x for x in body["positions"] if x["holding_id"] == hid]
    return p[0]["lots"] if p else []


def test_a_mistyped_price_can_be_corrected(client):
    """The reason this exists: a parcel entered at the wrong price makes
    every number derived from it wrong."""
    hid = buy(client, name="APL Apollo", identifier="APLAPOLLO",
              units=2, price=4549, sleeve="core").json()["holding_id"]
    lot = lots_of(client, hid)[0]
    r = client.put("/api/journal/lots/%d" % lot["id"],
                   json={"price": 2250}, headers=WRITE)
    assert r.status_code == 200, r.text
    assert r.json()["avg_cost"] == pytest.approx(2250)
    assert lots_of(client, hid)[0]["cost_per_unit"] == pytest.approx(2250)


def test_a_mistyped_quantity_can_be_corrected(client):
    hid = buy(client, name="APL Apollo", identifier="APLAPOLLO",
              units=20, price=2250).json()["holding_id"]
    lot = lots_of(client, hid)[0]
    client.put("/api/journal/lots/%d" % lot["id"], json={"units": 8},
               headers=WRITE)
    assert lots_of(client, hid)[0]["remaining"] == 8
    assert [h for h in holdings(client) if h["id"] == hid][0]["units"] == 8


def test_correcting_a_purchase_moves_its_cashflow_row_too(client):
    """Otherwise XIRR goes on quoting the typo."""
    hid = buy(client, name="Titan", identifier="TITAN", units=10,
              price=999).json()["holding_id"]
    lot = lots_of(client, hid)[0]
    client.put("/api/journal/lots/%d" % lot["id"],
               json={"units": 5, "price": 100, "charges": 20}, headers=WRITE)
    txns = client.get("/api/holdings/%d/transactions" % hid).json()
    assert len(txns) == 1
    assert txns[0]["amount"] == pytest.approx(520)
    assert txns[0]["units"] == 5


def test_correcting_the_cost_reworks_profit_already_booked_against_it(client):
    """A sale measured against the wrong buy price must not keep the wrong
    profit once the price is fixed."""
    hid = buy(client, name="Titan", identifier="TITAN", units=10,
              price=200).json()["holding_id"]
    client.post("/api/journal/sell",
                json={"holding_id": hid, "date": "2026-08-01", "units": 4,
                      "price": 300, "reason": "target"}, headers=WRITE)
    assert client.get("/api/journal").json()["realised"]["realised"] \
        == pytest.approx(400)

    lot = lots_of(client, hid)[0]
    client.put("/api/journal/lots/%d" % lot["id"], json={"price": 100},
               headers=WRITE)
    body = client.get("/api/journal").json()
    assert body["realised"]["realised"] == pytest.approx(800)
    assert body["trades"][0]["buy_price"] == pytest.approx(100)


def test_a_parcel_cannot_be_cut_below_what_was_sold_out_of_it(client):
    """The sale really happened; the arithmetic has nowhere to put it."""
    hid = buy(client, name="Titan", identifier="TITAN", units=10,
              price=100).json()["holding_id"]
    client.post("/api/journal/sell",
                json={"holding_id": hid, "date": "2026-08-01", "units": 7,
                      "price": 150, "reason": "target"}, headers=WRITE)
    lot = lots_of(client, hid)[0]
    r = client.put("/api/journal/lots/%d" % lot["id"], json={"units": 5},
                   headers=WRITE)
    assert r.status_code == 400
    assert "7" in r.json()["detail"]
    assert lots_of(client, hid)[0]["remaining"] == 3     # untouched


def test_the_units_still_held_follow_a_corrected_quantity(client):
    hid = buy(client, name="Titan", identifier="TITAN", units=10,
              price=100).json()["holding_id"]
    client.post("/api/journal/sell",
                json={"holding_id": hid, "date": "2026-08-01", "units": 4,
                      "price": 150, "reason": "target"}, headers=WRITE)
    lot = lots_of(client, hid)[0]
    client.put("/api/journal/lots/%d" % lot["id"], json={"units": 12},
               headers=WRITE)
    assert lots_of(client, hid)[0]["remaining"] == 8      # 12 bought, 4 gone


def test_giving_a_parcel_a_real_date_makes_its_holding_period_knowable(client):
    hid = buy(client, name="Titan", identifier="TITAN").json()["holding_id"]
    lot = lots_of(client, hid)[0]
    client.put("/api/journal/lots/%d" % lot["id"],
               json={"date": "2024-01-15"}, headers=WRITE)
    fixed = lots_of(client, hid)[0]
    assert fixed["date"] == "2024-01-15" and fixed["date_known"] is True


def test_a_purchase_that_never_happened_can_be_removed(client):
    hid = buy(client, name="Titan", identifier="TITAN", units=10,
              price=100).json()["holding_id"]
    buy(client, holding_id=hid, date="2026-07-01", units=5, price=200)
    lots = lots_of(client, hid)
    client.delete("/api/journal/lots/%d" % lots[1]["id"], headers=WRITE)
    assert len(lots_of(client, hid)) == 1
    assert [h for h in holdings(client) if h["id"] == hid][0]["units"] == 10
    assert len(client.get("/api/holdings/%d/transactions" % hid).json()) == 1


def test_a_parcel_that_has_been_sold_cannot_just_be_deleted(client):
    """Deleting it would leave the sale pointing at nothing."""
    hid = buy(client, name="Titan", identifier="TITAN", units=10,
              price=100).json()["holding_id"]
    client.post("/api/journal/sell",
                json={"holding_id": hid, "date": "2026-08-01", "units": 4,
                      "price": 150, "reason": "target"}, headers=WRITE)
    lot = lots_of(client, hid)[0]
    r = client.delete("/api/journal/lots/%d" % lot["id"], headers=WRITE)
    assert r.status_code == 400
    assert "Remove the sale first" in r.json()["detail"]


def test_a_sale_entered_wrongly_can_be_undone(client):
    hid = buy(client, name="Titan", identifier="TITAN", units=10,
              price=100).json()["holding_id"]
    client.post("/api/journal/sell",
                json={"holding_id": hid, "date": "2026-08-01", "units": 4,
                      "price": 150, "reason": "target"}, headers=WRITE)
    tid = client.get("/api/journal").json()["trades"][0]["id"]
    r = client.delete("/api/journal/trades/%d" % tid, headers=WRITE)
    assert r.status_code == 200, r.text

    body = client.get("/api/journal").json()
    assert body["trades"] == []
    assert body["realised"]["realised"] == 0
    assert lots_of(client, hid)[0]["remaining"] == 10     # units restored
    # and the sale's cashflow row goes with it
    kinds = [t["type"] for t in
             client.get("/api/holdings/%d/transactions" % hid).json()]
    assert kinds == ["buy"]


def test_undoing_one_parcel_of_a_multi_parcel_sale_keeps_the_rest(client):
    hid = buy(client, name="Titan", identifier="TITAN", units=10,
              price=100).json()["holding_id"]
    buy(client, holding_id=hid, date="2026-07-01", units=10, price=200)
    client.post("/api/journal/sell",
                json={"holding_id": hid, "date": "2026-08-01", "units": 15,
                      "price": 300, "reason": "target"}, headers=WRITE)
    body = client.get("/api/journal").json()
    assert len(body["trades"]) == 2

    client.delete("/api/journal/trades/%d" % body["trades"][0]["id"],
                  headers=WRITE)
    after = client.get("/api/journal").json()
    assert len(after["trades"]) == 1
    # the sale's cashflow row is rebuilt from what is left, not deleted
    sells = [t for t in
             client.get("/api/holdings/%d/transactions" % hid).json()
             if t["type"] == "sell"]
    assert len(sells) == 1
    assert sells[0]["units"] == after["trades"][0]["units"]


# ---- what a folio is, and is not ----------------------------------------
def test_several_schemes_in_one_folio_do_not_collide(client):
    """A folio names an account, not a scheme, and a fund house routinely
    puts several schemes in one. Treating it as scheme identity made every
    row after the first import as a duplicate holding."""
    folio = "1000000001 / 0"
    rows = [cas_row(folio=folio, isin="INF247L01445", name="MO Midcap"),
            cas_row(folio=folio, isin="INF247L01569", name="MO ELSS"),
            cas_row(folio=folio, isin="INF247L01718", name="MO Nasdaq FoF")]
    first = commit(client, rows)
    assert (first["added"], first["updated"]) == (3, 0)

    again = commit(client, rows)
    assert (again["added"], again["updated"]) == (0, 3)
    assert len([h for h in holdings(client)
                if h["asset_class"] == "mutual_fund"]) == 3


def test_a_statement_does_not_overwrite_the_code_that_prices_a_fund(client):
    """A CAS names a fund by folio and never by AMFI code. Writing the folio
    into `identifier` destroyed the one field NAV refresh needs."""
    commit(client, [cas_row()])
    hid = holdings(client)[0]["id"]
    client.put("/api/holdings/%d" % hid, json={"identifier": "120503"},
               headers=WRITE)

    commit(client, [cas_row(units=140.0)])
    row = [h for h in holdings(client) if h["id"] == hid][0]
    assert row["identifier"] == "120503"          # the scheme code survived
    assert row["meta"]["folio"] == "F123"         # the folio went to meta
    assert row["units"] == 140.0


def test_a_fund_with_no_code_keeps_the_folio_out_of_the_identifier(client):
    """An empty identifier is recoverable — the ISIN resolves the code on the
    next refresh — and a folio sitting in it is not."""
    commit(client, [dict(cas_row(), scheme_code=None)])
    row = holdings(client)[0]
    assert row["identifier"] == ""
    assert row["meta"]["folio"] == "F123"


def test_a_statement_replaces_the_opening_position_instead_of_adding_to_it(
        client):
    """The opening lot stands in for purchases that were never recorded,
    which is exactly what the statement now supplies. Leaving it in place
    doubled the units of every fund imported."""
    commit(client, [cas_row(units=100.0, avg_cost=50.0)])
    hid = holdings(client)[0]["id"]
    before = [h for h in holdings(client) if h["id"] == hid][0]["units"]
    assert before == 100.0

    commit(client, [cas_row(units=100.0, avg_cost=50.0)])
    after = [h for h in holdings(client) if h["id"] == hid][0]
    assert after["units"] == 100.0                # not 200
    assert after["invested"] == pytest.approx(5000.0)


def test_a_journal_purchase_is_not_swept_away_by_a_statement(client):
    """Only what an import wrote is the importer's to replace."""
    hid = buy(client, name="Titan", identifier="TITAN", units=10,
              price=100).json()["holding_id"]
    commit(client, [cas_row()])
    assert [h for h in holdings(client) if h["id"] == hid][0]["units"] == 10


def test_an_unreadable_scheme_name_does_not_rename_a_fund(client):
    """The parser's placeholder is not an improvement on a name the user can
    already read on screen."""
    import importers as imp
    commit(client, [cas_row(name="HSBC Small Cap Fund")])
    hid = holdings(client)[0]["id"]
    commit(client, [cas_row(name=imp.UNREADABLE_NAME, units=120.0)])
    row = [h for h in holdings(client) if h["id"] == hid][0]
    assert row["name"] == "HSBC Small Cap Fund"
    assert row["units"] == 120.0        # the numbers still updated


# ---- a broker export against journal entries -----------------------------
def broker_row(name="Titan", identifier="TITAN", units=8.0, avg_cost=4494.0):
    """One row as a broker holdings export produces it: a whole position."""
    return {"asset_class": "stock", "name": name, "identifier": identifier,
            "units": units, "avg_cost": avg_cost, "last_price": 5169.0}


def test_a_broker_position_already_contains_what_you_entered_by_hand(client):
    """The broker counted the journal purchase too, so adding its stated
    position on top of that purchase turned eight shares into eleven."""
    hid = buy(client, name="Titan", identifier="TITAN", units=3,
              price=5125.4, sleeve="core").json()["holding_id"]
    commit(client, [broker_row(units=8.0)])
    row = [h for h in holdings(client) if h["id"] == hid][0]
    assert row["units"] == 8.0                      # not 11
    assert row["avg_cost"] == pytest.approx(4494.0)  # the stated average


def test_the_journal_parcel_keeps_its_detail_through_a_broker_import(client):
    """Only the remainder is imported, so the stop-loss and the sleeve on a
    hand-entered purchase survive."""
    hid = buy(client, name="Titan", identifier="TITAN", units=3, price=5125.4,
              stoploss=4800, sleeve="core").json()["holding_id"]
    commit(client, [broker_row(units=8.0)])
    lots = [p for p in client.get("/api/journal").json()["positions"]
            if p["holding_id"] == hid][0]["lots"]
    mine = [x for x in lots if x["source"] == "manual"]
    assert len(mine) == 1
    assert mine[0]["stoploss"] == 4800
    assert sum(x["remaining"] for x in lots) == 8.0


def test_re_importing_a_broker_export_changes_nothing(client):
    hid = buy(client, name="Titan", identifier="TITAN", units=3,
              price=5125.4).json()["holding_id"]
    commit(client, [broker_row(units=8.0)])
    commit(client, [broker_row(units=8.0)])
    assert [h for h in holdings(client) if h["id"] == hid][0]["units"] == 8.0


def test_a_broker_export_matches_on_the_ticker(client):
    commit(client, [broker_row()])
    first = holdings(client)
    commit(client, [broker_row(units=12.0)])
    assert len(holdings(client)) == len(first)
    assert holdings(client)[0]["units"] == 12.0


def test_holding_more_than_the_statement_reports_is_a_conflict_not_a_guess(
        client):
    """Two sources disagreeing about what is held is worth saying out loud."""
    hid = buy(client, name="Titan", identifier="TITAN", units=3,
              price=5125.4).json()["holding_id"]
    r = client.post("/api/import/commit",
                    json={"rows": [broker_row(units=1.0)], "owner": "Me"},
                    headers=WRITE).json()
    assert len(r["conflicts"]) == 1
    assert "Titan" in r["conflicts"][0]
    # and the holding keeps the parcels it actually has
    assert [h for h in holdings(client) if h["id"] == hid][0]["units"] == 3.0


def test_a_stock_the_export_has_never_seen_is_added(client):
    commit(client, [broker_row()])
    before = len(holdings(client))
    commit(client, [broker_row(name="Newco", identifier="NEWCO", units=5.0)])
    assert len(holdings(client)) == before + 1


# ---- replaying a broker's tradebook --------------------------------------
def trade(when, kind, units, price, charges=0.0):
    return {"date": when, "type": kind, "units": units, "price": price,
            "charges": charges}


def book(client, groups, name="book:test"):
    r = client.post("/api/import/tradebook",
                    json={"book": name, "groups": groups, "owner": "Me"},
                    headers=WRITE)
    assert r.status_code == 200, r.text
    return r.json()


def group(symbol="TITAN", name="Titan", isin="INE280A01028", trades=()):
    return {"symbol": symbol, "name": name, "isin": isin, "isins": [isin],
            "trades": list(trades)}


def test_a_tradebook_gives_shares_the_purchase_dates_they_never_had(client):
    r = book(client, [group(trades=[trade("2026-01-05", "buy", 10, 100),
                                    trade("2026-03-05", "buy", 5, 120)])])
    assert (r["added"], r["parcels"]) == (1, 2)
    pos = client.get("/api/journal").json()["positions"][0]
    assert pos["units"] == 15
    assert [lot["date"] for lot in pos["lots"]] == ["2026-01-05", "2026-03-05"]
    assert all(lot["date_known"] for lot in pos["lots"])


def test_a_sale_in_the_book_closes_the_oldest_parcel(client):
    r = book(client, [group(trades=[trade("2026-01-05", "buy", 10, 100),
                                    trade("2026-06-05", "sell", 4, 150)])])
    assert r["closed"] == 1
    body = client.get("/api/journal").json()
    assert body["positions"][0]["units"] == 6
    assert body["realised"]["realised"] == pytest.approx(200)


def test_re_importing_the_same_book_replaces_what_it_wrote(client):
    trades = [trade("2026-01-05", "buy", 10, 100)]
    book(client, [group(trades=trades)])
    r = book(client, [group(trades=trades)])
    assert (r["added"], r["updated"]) == (0, 1)
    assert client.get("/api/journal").json()["positions"][0]["units"] == 10


def test_a_second_broker_does_not_delete_the_first_brokers_parcels(client):
    """A share held at two brokers is one holding with parcels from both."""
    book(client, [group(trades=[trade("2026-01-05", "buy", 10, 100)])],
         name="book:one")
    book(client, [group(trades=[trade("2026-02-05", "buy", 4, 110)])],
         name="book:two")
    assert client.get("/api/journal").json()["positions"][0]["units"] == 14


def test_a_trade_you_already_entered_is_not_imported_twice(client):
    """The book records the same purchase the user typed in. One trade, not
    two -- and the one they entered carries a stop-loss the book lacks."""
    hid = buy(client, name="Titan", identifier="TITAN", date="2026-01-05",
              units=10, price=100, stoploss=90).json()["holding_id"]
    r = book(client, [group(trades=[trade("2026-01-05", "buy", 10, 100)])])
    assert r["merged"] == 1 and r["parcels"] == 0
    row = [h for h in holdings(client) if h["id"] == hid][0]
    assert row["units"] == 10                      # not 20
    lots = client.get("/api/journal").json()["positions"][0]["lots"]
    assert lots[0]["stoploss"] == 90               # the user's parcel kept


def test_a_price_that_merely_rounds_differently_is_the_same_trade(client):
    buy(client, name="Titan", identifier="TITAN", date="2026-01-05",
        units=10, price=100.0)
    r = book(client, [group(trades=[trade("2026-01-05", "buy", 10, 100.2)])])
    assert r["merged"] == 1


def test_a_different_trade_on_the_same_day_is_still_imported(client):
    buy(client, name="Titan", identifier="TITAN", date="2026-01-05",
        units=10, price=100)
    r = book(client, [group(trades=[trade("2026-01-05", "buy", 4, 100)])])
    assert r["merged"] == 0 and r["parcels"] == 1


def test_a_book_claiming_more_than_is_held_says_so(client):
    hid = buy(client, name="Titan", identifier="TITAN", units=2,
              price=100).json()["holding_id"]
    r = book(client, [group(trades=[trade("2026-01-05", "buy", 5, 100)])])
    assert any("more units than are held" in w for w in r["warnings"])
    assert [h for h in holdings(client) if h["id"] == hid][0]["units"] == 7


def test_a_sale_with_no_recorded_purchase_is_reported_not_invented(client):
    """A book that opens mid-history sells shares it never records buying."""
    r = book(client, [group(trades=[trade("2026-06-05", "sell", 4, 150)])])
    assert r["skipped"] == 1
    assert any("could not be matched" in w for w in r["warnings"])


def test_a_tradebook_matches_a_holding_that_has_no_isin_recorded(client):
    """Shares recorded before the app ever saw an ISIN carry none, and an
    ISIN-only match would file every one of them a second time."""
    hid = buy(client, name="Titan", identifier="TITAN", units=10,
              price=100).json()["holding_id"]
    r = book(client, [group(trades=[trade("2026-01-05", "buy", 4, 100)])])
    assert r["added"] == 0
    assert [h for h in holdings(client) if h["id"] == hid][0]["id"] == hid


def test_a_tradebook_does_not_reset_which_sleeve_a_position_is_in(client):
    """A book knows nothing about core and satellite. Importing one used to
    wipe that judgement across the whole portfolio."""
    hid = buy(client, name="Titan", identifier="TITAN", units=10, price=100,
              sleeve="satellite").json()["holding_id"]
    book(client, [group(trades=[trade("2026-02-05", "buy", 4, 110)])])
    pos = [p for p in client.get("/api/journal").json()["positions"]
           if p["holding_id"] == hid][0]
    assert pos["sleeve"] == "satellite"
    assert all(lot["sleeve"] == "satellite" for lot in pos["lots"])
