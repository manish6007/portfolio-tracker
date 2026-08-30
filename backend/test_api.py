"""Tests through HTTP, not around it.

Everything in main.py -- the CORS configuration, the host check, profile
selection from the cookie, the session lifecycle, the confirmation guards --
only exists on the request path, so calling the endpoint functions directly
proves none of it. These go through the app.
"""
import sys

import pytest
from datetime import date
from fastapi.testclient import TestClient

import config
import db
import main


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "BASE", str(tmp_path))
    monkeypatch.setattr(config, "CONFIG_PATH", str(tmp_path / "app-config.json"))
    monkeypatch.delenv(config.ENV_DATA_DIR, raising=False)
    monkeypatch.setattr(db, "_engines", {})
    monkeypatch.setattr(db, "_factories", {})
    # base_url matters: the host check rejects anything that is not
    # loopback, and TestClient defaults to http://testserver.
    with TestClient(main.app, base_url="http://localhost:8000") as c:
        yield c


def as_profile(client, pid):
    """Point the client at a profile the way a browser does."""
    client.cookies.set("profile", pid)
    return client


# ---- the boundary that replaces having no login -------------------------
def test_another_website_cannot_read_the_portfolio(client):
    """Wildcard CORS would let any open tab fetch /api/summary."""
    r = client.get("/api/summary", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in {
        k.lower() for k in r.headers}


def test_a_cross_site_write_is_refused(client):
    """Sec-Fetch-Site is browser-set and cannot be forged by script."""
    r = client.post("/api/reset", json={"confirm": "ERASE"},
                    headers={"Origin": "https://evil.example",
                             "Sec-Fetch-Site": "cross-site"})
    assert r.status_code == 403


def test_a_same_origin_write_still_works(client):
    r = client.post("/api/holdings",
                    json={"asset_class": "stock", "name": "S", "units": 1,
                          "avg_cost": 10},
                    headers={"Sec-Fetch-Site": "same-origin"})
    assert r.status_code == 200


def test_a_request_for_another_host_is_refused(client):
    """Closes DNS rebinding, which an origin check alone does not."""
    r = client.get("/api/summary", headers={"Host": "portfolio.evil.example"})
    assert r.status_code == 421


def test_loopback_hosts_are_allowed(client):
    for host in ("localhost:8000", "127.0.0.1:8000"):
        assert client.get("/api/summary",
                          headers={"Host": host}).status_code == 200


# ---- profiles, through the cookie that actually selects them ------------
def test_profiles_are_isolated_over_http(client):
    client.post("/api/profiles", json={"name": "Demo"})
    client.post("/api/holdings", json={"asset_class": "stock",
                                       "name": "My real stock",
                                       "units": 10, "avg_cost": 100})
    as_profile(client, "demo")
    assert client.get("/api/holdings").json() == []
    client.post("/api/holdings", json={"asset_class": "stock",
                                       "name": "Demo stock", "units": 1,
                                       "avg_cost": 5})
    assert [h["name"] for h in client.get("/api/holdings").json()] == [
        "Demo stock"]

    as_profile(client, "default")
    assert [h["name"] for h in client.get("/api/holdings").json()] == [
        "My real stock"]


def test_activating_a_profile_sets_the_cookie(client):
    client.post("/api/profiles", json={"name": "Demo"})
    r = client.post("/api/profiles/demo/activate")
    assert r.cookies.get("profile") == "demo"


def test_an_unknown_profile_cookie_falls_back(client):
    """A tab left open on a deleted profile must not error on every call."""
    as_profile(client, "gone")
    assert client.get("/api/holdings").status_code == 200


# ---- the guards on destructive things -----------------------------------
def test_reset_needs_the_confirm_token(client):
    assert client.post("/api/reset", json={}).status_code == 400
    assert client.post("/api/reset",
                       json={"confirm": "ERASE"}).status_code == 200


def test_deleting_a_profile_needs_its_name_in_the_body(client):
    client.post("/api/profiles", json={"name": "Demo"})
    assert client.request("DELETE", "/api/profiles/demo",
                          json={"confirm": "wrong"}).status_code == 400
    assert client.request("DELETE", "/api/profiles/demo",
                          json={"confirm": "Demo"}).status_code == 200


def test_the_first_profile_cannot_be_deleted_over_http(client):
    r = client.request("DELETE", "/api/profiles/default",
                       json={"confirm": "My portfolio"})
    assert r.status_code == 400


# ---- a holding through its whole life -----------------------------------
def test_a_holding_round_trips(client):
    created = client.post("/api/holdings", json={
        "asset_class": "stock", "name": "Reliance", "identifier": "RELIANCE",
        "units": 10, "avg_cost": 1000}).json()
    hid = created["id"]
    assert created["current_value"] == 10000      # priced at cost until refresh
    assert created["price_date"]

    fetched = [h for h in client.get("/api/holdings").json()
               if h["id"] == hid][0]
    assert fetched["name"] == "Reliance"

    updated = client.put("/api/holdings/%d" % hid,
                         json={"last_price": 1400}).json()
    assert updated["current_value"] == 14000
    assert updated["price_date"]

    assert client.delete("/api/holdings/%d" % hid).status_code == 200
    assert client.get("/api/holdings").json() == []


def test_a_404_does_not_leak_a_session(client):
    """The error paths are where the session leak lived."""
    for _ in range(30):
        assert client.get("/api/holdings").status_code == 200
        assert client.put("/api/holdings/999999",
                          json={"name": "x"}).status_code == 404
    assert client.get("/api/summary").status_code == 200


def test_a_bad_asset_class_is_refused(client):
    r = client.post("/api/holdings", json={"asset_class": "crypto",
                                           "name": "X"})
    assert r.status_code == 422
    assert "asset_class must be one of" in r.json()["detail"]


def test_a_misspelled_field_is_an_error_not_a_silent_no_op(client):
    """`payload.get("assetClass")` used to just return None."""
    r = client.post("/api/holdings", json={"asset_class": "stock",
                                           "name": "X", "assetClass": "y"})
    assert r.status_code == 422
    assert "assetClass" in r.json()["detail"]


def test_a_validation_error_reads_as_a_sentence(client):
    """The UI shows `detail` verbatim; a list of error objects is noise."""
    r = client.post("/api/holdings", json={"asset_class": "stock",
                                           "name": "X", "units": "lots"})
    assert isinstance(r.json()["detail"], str)
    assert r.json()["detail"].startswith("units: ")


def test_a_negative_quantity_is_refused(client):
    r = client.post("/api/holdings", json={"asset_class": "stock",
                                           "name": "X", "units": -5})
    assert r.status_code == 422


def test_a_holding_needs_a_name(client):
    r = client.post("/api/holdings", json={"asset_class": "stock"})
    assert r.status_code == 422
    assert "name" in r.json()["detail"]


def test_a_missing_amount_is_a_422_not_a_500(client):
    """float(payload["amount"]) used to raise KeyError -> 500."""
    r = client.post("/api/income", json={"category": "Salary"})
    assert r.status_code == 422
    assert "amount" in r.json()["detail"]


# ---- the privacy claims, over HTTP --------------------------------------
def test_the_privacy_page_reports_the_real_data_folder(client, tmp_path):
    body = client.get("/api/privacy").json()
    assert body["data_dir"] == str(tmp_path)
    assert body["offline"] is False
    assert {h["host"] for h in body["allowed_hosts"]} == set(
        main.netlog.ALLOWED_HOSTS)


def test_offline_mode_survives_a_round_trip(client):
    client.post("/api/privacy/offline", json={"offline": True})
    assert client.get("/api/privacy").json()["offline"] is True
    assert client.post("/api/prices/refresh").json()["offline"] is True


def test_an_oversized_upload_is_refused(client):
    big = b"x" * (main.MAX_UPLOAD_BYTES + 1)
    r = client.post("/api/import/preview",
                    files={"file": ("big.csv", big, "text/csv")})
    assert r.status_code == 413


def test_a_wipe_leaves_a_usable_portfolio_behind(client):
    """The default owner check is cached per file; a wipe must clear it."""
    client.post("/api/holdings", json={"asset_class": "stock", "name": "S",
                                       "units": 1, "avg_cost": 10})
    assert client.post("/api/reset", json={"confirm": "ERASE"}).status_code == 200
    assert client.get("/api/owners").json()
    assert client.post("/api/holdings",
                       json={"asset_class": "stock", "name": "After",
                             "units": 1, "avg_cost": 10}).status_code == 200


def test_the_dashboard_summary_matches_the_holdings_list(client):
    """summary() and /api/holdings must not drift apart now they share a load."""
    client.post("/api/holdings", json={"asset_class": "stock", "name": "A",
                                       "units": 10, "avg_cost": 100})
    client.post("/api/holdings", json={"asset_class": "fd", "name": "FD",
                                       "avg_cost": 50000, "rate": 7,
                                       "start_date": "2024-01-01"})
    summary = client.get("/api/summary").json()
    listed = client.get("/api/holdings").json()
    assert len(summary["holdings"]) == len(listed) == 2
    assert round(sum(h["current_value"] for h in listed), 2) == \
        summary["total_assets"]


# ---- partial updates must stay partial ----------------------------------
def test_a_put_touches_only_the_fields_it_was_sent(client):
    """exclude_unset is what keeps "absent" different from "sent as null"."""
    h = client.post("/api/holdings", json={
        "asset_class": "mutual_fund", "name": "Fund", "identifier": "120503",
        "units": 100, "avg_cost": 50,
        "meta": {"category": "equity", "nominee": "Spouse"}}).json()

    client.put("/api/holdings/%d" % h["id"], json={"last_price": 75})
    after = client.get("/api/holdings").json()[0]
    assert after["identifier"] == "120503"          # untouched
    assert after["units"] == 100
    assert after["meta"]["nominee"] == "Spouse"
    assert after["current_value"] == 7500


def test_meta_merges_rather_than_replacing(client):
    h = client.post("/api/holdings", json={
        "asset_class": "mutual_fund", "name": "Fund", "units": 1,
        "avg_cost": 1, "meta": {"category": "hybrid"}}).json()
    client.put("/api/holdings/%d" % h["id"],
               json={"meta": {"nominee": "Spouse"}})
    meta = client.get("/api/holdings").json()[0]["meta"]
    assert meta["category"] == "hybrid" and meta["nominee"] == "Spouse"


def test_a_recurring_cost_keeps_its_frequency_on_a_partial_update(client):
    r = client.post("/api/recurring", json={
        "name": "Insurance", "kind": "premium", "amount": 12000,
        "frequency": "yearly"}).json()
    assert r["amount_monthly"] == 1000
    client.put("/api/recurring/%d" % r["id"], json={"name": "Car insurance"})
    after = client.get("/api/recurring").json()[0]
    assert after["frequency"] == "yearly" and after["amount_monthly"] == 1000


def test_a_bad_frequency_is_refused(client):
    r = client.post("/api/recurring", json={"name": "X", "amount": 100,
                                            "frequency": "fortnightly"})
    assert r.status_code == 422
    assert "frequency" in r.json()["detail"]


def test_settings_still_accept_the_whole_object_back(client):
    """The UI sends read-only fields along with the editable ones."""
    settings = client.get("/api/settings").json()
    settings["age"] = "38"
    assert client.put("/api/settings", json=settings).status_code == 200
    assert client.get("/api/settings").json()["age"] == "38"


def test_the_openapi_schema_describes_the_bodies(client):
    """Every request body used to be documented as "object"."""
    schema = client.get("/openapi.json").json()
    body = (schema["paths"]["/api/holdings"]["post"]["requestBody"]
            ["content"]["application/json"]["schema"])
    ref = body.get("$ref", "")
    assert ref.endswith("HoldingIn")
    props = schema["components"]["schemas"]["HoldingIn"]["properties"]
    assert "asset_class" in props and "units" in props


def test_erase_all_data_really_erases_all_of_it(client):
    """Policies and goals used to survive a wipe, orphaned against no owner."""
    client.post("/api/holdings", json={"asset_class": "stock", "name": "S",
                                       "units": 1, "avg_cost": 10})
    client.post("/api/policies", json={"name": "Term", "kind": "term",
                                       "sum_assured": 10000000,
                                       "premium": 18000})
    client.post("/api/goals", json={"name": "Car", "amount_today": 1200000,
                                    "target_year": 5})
    client.post("/api/loans", json={"name": "Home", "annual_rate": 8.5,
                                    "principal_outstanding": 5000000})

    assert client.post("/api/reset", json={"confirm": "ERASE"}).status_code == 200

    for path in ("/api/holdings", "/api/policies", "/api/goals", "/api/loans"):
        assert client.get(path).json() == [], path
    assert client.get("/api/summary").json()["total_assets"] == 0


def test_the_app_notices_when_the_server_is_older_than_the_code(client,
                                                                monkeypatch):
    """Updating is git pull + npm run build; the Python process is not
    restarted by either, so a new page ends up calling an endpoint the
    running server does not have. That looks like a network fault."""
    from datetime import datetime, timedelta
    assert client.get("/api/meta").json()["stale_backend"] is False

    # Pretend the process started before the files on disk were last written.
    monkeypatch.setattr(main, "_started", datetime.now() + timedelta(days=1))
    assert client.get("/api/meta").json()["stale_backend"] is False

    monkeypatch.setattr(main, "_started", datetime.now() - timedelta(days=365))
    assert client.get("/api/meta").json()["stale_backend"] is True


def test_a_readable_nav_file_and_an_unreadable_one_report_differently(client,
                                                                      monkeypatch):
    """"AMFI could not be reached" for a file that downloaded fine sent
    someone to check a connection that had just delivered a megabyte."""
    import pricing

    monkeypatch.setattr(pricing, "fetch_amfi",
                        lambda *a, **k: ({}, {}, pricing.AMFI_UNREACHABLE))
    body = client.post("/api/prices/refresh").json()
    assert body["amfi_status"] == "unreachable"
    assert body["amfi_reachable"] is False

    monkeypatch.setattr(pricing, "fetch_amfi",
                        lambda *a, **k: ({}, {}, pricing.AMFI_UNREADABLE))
    body = client.post("/api/prices/refresh").json()
    assert body["amfi_status"] == "unreadable"
    assert body["amfi_reachable"] is False      # still no NAVs, different why


# ---- giving funds the code that prices them -----------------------------
def _stub_amfi(monkeypatch, main_mod):
    """A small AMFI table, so the suggestion path can be tested offline."""
    from datetime import date as _date
    import pricing
    navs, code, nav = {}, 100000, 50.0
    for base in ("DSP Midcap Fund", "Parag Parikh Flexi Cap Fund"):
        for plan in ("Direct Plan", "Regular Plan"):
            nav += 20
            navs[str(code)] = {"name": "%s - %s - Growth" % (base, plan),
                               "nav": nav, "date": _date(2026, 8, 26)}
            code += 1
    monkeypatch.setattr(pricing, "fetch_amfi",
                        lambda *a, **k: (navs, {}, pricing.AMFI_OK))
    main_mod._amfi_cache.update(data={}, at=None, by_isin={})
    return navs


def test_a_fund_with_a_folio_gets_its_code_suggested(client, monkeypatch):
    _stub_amfi(monkeypatch, main)
    client.post("/api/holdings", json={
        "asset_class": "mutual_fund", "name": "DSP Midcap Fund",
        "identifier": "90722941761/0", "units": 100, "avg_cost": 50})
    body = client.get("/api/amfi/suggest-codes").json()
    assert len(body["holdings"]) == 1
    row = body["holdings"][0]
    assert row["confident"] is True
    assert row["candidates"][0]["name"].startswith("DSP Midcap Fund - Direct")


def test_a_fund_that_already_has_a_code_is_left_out(client, monkeypatch):
    navs = _stub_amfi(monkeypatch, main)
    code = next(iter(navs))
    client.post("/api/holdings", json={
        "asset_class": "mutual_fund", "name": "DSP Midcap Fund",
        "identifier": code, "units": 100, "avg_cost": 50})
    assert client.get("/api/amfi/suggest-codes").json()["holdings"] == []


def test_applying_a_code_prices_the_fund_and_keeps_the_folio(client,
                                                             monkeypatch):
    navs = _stub_amfi(monkeypatch, main)
    h = client.post("/api/holdings", json={
        "asset_class": "mutual_fund", "name": "DSP Midcap Fund",
        "identifier": "90722941761/0", "units": 100, "avg_cost": 50}).json()
    row = client.get("/api/amfi/suggest-codes").json()["holdings"][0]
    code = row["candidates"][0]["code"]

    r = client.post("/api/amfi/apply-codes", json={"assignments": [
        {"holding_id": h["id"], "scheme_code": code}]}).json()
    assert r["applied"] == 1 and r["errors"] == []

    after = client.get("/api/holdings").json()[0]
    assert after["identifier"] == code
    assert after["last_price"] == navs[code]["nav"]
    # The folio is needed by the family record and CAS reconciliation.
    assert after["meta"]["folio"] == "90722941761/0"
    assert client.get("/api/amfi/suggest-codes").json()["holdings"] == []


def test_applying_a_code_that_is_not_a_scheme_is_refused(client, monkeypatch):
    _stub_amfi(monkeypatch, main)
    h = client.post("/api/holdings", json={
        "asset_class": "mutual_fund", "name": "DSP Midcap Fund",
        "units": 1, "avg_cost": 50}).json()
    r = client.post("/api/amfi/apply-codes", json={"assignments": [
        {"holding_id": h["id"], "scheme_code": "999999"}]}).json()
    assert r["applied"] == 0 and "not an AMFI scheme code" in r["errors"][0]


def test_a_purchase_price_is_not_treated_as_a_recent_nav(client, monkeypatch):
    """The app writes last_price = avg_cost when a holding is created. Read
    as evidence, that rejected every correct match for funds bought years
    ago at a very different price."""
    _stub_amfi(monkeypatch, main)
    client.post("/api/holdings", json={
        "asset_class": "mutual_fund", "name": "DSP Midcap Fund",
        "units": 100, "avg_cost": 12.5})       # nothing like today's NAV
    row = client.get("/api/amfi/suggest-codes").json()["holdings"][0]
    assert row["compared_against"] is None
    assert row["confident"] is True


# ---- "1 unit costing the whole invested amount" -------------------------
# What you get when the value is known but the unit count is not. Harmless
# while the "price" is the market value; the moment a real NAV lands on it,
# one unit times 215 is 215 and a five-lakh holding reads as a total loss.
def _placeholder(client, name="SBI Small Cap Fund", invested=294000,
                 price=215):
    """The broken shape: one "unit" costing the lot, priced at a real NAV."""
    return client.post("/api/holdings", json={
        "asset_class": "mutual_fund", "name": name, "units": 1,
        "avg_cost": invested, "last_price": price}).json()


def test_a_placeholder_holding_is_reported(client):
    _placeholder(client)
    codes = [w["code"] for w in client.get("/api/summary").json()["warnings"]]
    assert "unit_placeholder" in codes


def test_a_genuine_single_unit_holding_is_not_reported(client):
    client.post("/api/holdings", json={
        "asset_class": "mutual_fund", "name": "One unit", "units": 1,
        "avg_cost": 215, "last_price": 240})
    codes = [w["code"] for w in client.get("/api/summary").json()["warnings"]]
    assert "unit_placeholder" not in codes


def test_setting_the_real_units_keeps_the_invested_amount(client):
    h = _placeholder(client)
    r = client.post("/api/holdings/set-units", json={"units": [
        {"holding_id": h["id"], "units": 1367.44}]}).json()
    assert r["applied"] == 1 and r["errors"] == []
    after = client.get("/api/holdings").json()[0]
    assert after["units"] == 1367.44
    assert round(after["invested"]) == 294000          # unchanged
    assert round(after["avg_cost"], 4) == round(294000 / 1367.44, 4)


def test_placeholders_are_listed_with_what_is_known_about_them(client):
    _placeholder(client, invested=294000, price=215)
    row = client.get("/api/holdings/unit-placeholders").json()["holdings"][0]
    assert row["invested"] == 294000
    assert row["last_price"] == 215
    assert row["priceable"] is True         # a real NAV, so a value works


def test_a_single_share_that_really_costs_a_lot_is_left_alone(client):
    """One share of Hitachi Energy India really is tens of thousands. What
    marks a placeholder is the proportion, not the size: a cost per unit
    wildly out of line with the price per unit."""
    client.post("/api/holdings", json={
        "asset_class": "stock", "name": "Hitachi Energy India",
        "identifier": "POWERINDIA", "units": 1,
        "avg_cost": 38627, "last_price": 33125})
    assert client.get("/api/holdings/unit-placeholders").json()["holdings"] == []
    codes = [w["code"] for w in client.get("/api/summary").json()["warnings"]]
    assert "unit_placeholder" not in codes


def test_a_real_single_share_still_gets_its_price_refreshed(client,
                                                            monkeypatch):
    import pricing
    monkeypatch.setattr(pricing, "fetch_amfi",
                        lambda *a, **k: ({}, {}, pricing.AMFI_OK))
    monkeypatch.setattr(pricing, "fetch_stock_prices",
                        lambda syms, **k: {s: (34000.0, date.today())
                                           for s in syms})
    client.post("/api/holdings", json={
        "asset_class": "stock", "name": "Hitachi Energy India",
        "identifier": "POWERINDIA", "units": 1,
        "avg_cost": 38627, "last_price": 33125})
    body = client.post("/api/prices/refresh").json()
    assert body["stocks_updated"] == 1
    assert body["mf_placeholders"] == []
    assert client.get("/api/holdings").json()[0]["current_value"] == 34000.0


def test_a_refresh_will_not_price_a_placeholder_away(client, monkeypatch):
    """Repricing it would replace a value with a NAV and wipe the holding.

    Caught on the way in, while the recorded value can still become units.
    """
    navs = _stub_amfi(monkeypatch, main)
    code = next(c for c, i in navs.items()
                if i["name"].startswith("DSP Midcap Fund - Direct"))
    client.post("/api/holdings", json={
        "asset_class": "mutual_fund", "name": "DSP Midcap Fund",
        "identifier": code, "units": 1, "avg_cost": 363000,
        "last_price": 420000})

    body = client.post("/api/prices/refresh").json()
    assert body["mf_updated"] == 0
    assert body["mf_placeholders"] == ["DSP Midcap Fund"]
    after = client.get("/api/holdings").json()[0]
    assert after["current_value"] == 420000            # value survived


def test_applying_a_code_derives_units_instead_of_destroying_the_value(
        client, monkeypatch):
    navs = _stub_amfi(monkeypatch, main)
    h = client.post("/api/holdings", json={
        "asset_class": "mutual_fund", "name": "DSP Midcap Fund", "units": 1,
        "avg_cost": 363000, "last_price": 420000}).json()
    row = client.get("/api/amfi/suggest-codes").json()["holdings"][0]
    code = row["candidates"][0]["code"]
    nav = navs[code]["nav"]

    r = client.post("/api/amfi/apply-codes", json={"assignments": [
        {"holding_id": h["id"], "scheme_code": code}]}).json()
    assert r["derived_units"] == ["DSP Midcap Fund"]

    after = client.get("/api/holdings").json()[0]
    assert round(after["units"], 4) == round(420000 / nav, 4)
    assert round(after["current_value"]) == 420000     # value preserved
    assert round(after["invested"]) == 363000          # and so is the cost
    assert after["last_price"] == nav                  # now a real NAV


def test_units_can_be_given_as_the_value_they_are_worth(client):
    """Nobody reads unit counts off a screen; everybody can see a value."""
    h = _placeholder(client, name="SBI Small Cap Fund", invested=294000,
                     price=215)            # already flattened by a NAV
    r = client.post("/api/holdings/set-units", json={"units": [
        {"holding_id": h["id"], "current_value": 350000}]}).json()
    assert r["applied"] == 1

    after = client.get("/api/holdings").json()[0]
    assert round(after["units"], 4) == round(350000 / 215, 4)
    assert round(after["current_value"]) == 350000
    assert round(after["invested"]) == 294000          # untouched


def test_a_value_cannot_become_units_while_the_price_is_still_a_total(client):
    """Dividing a value by itself gives 1 back, which is the bug, not a fix."""
    h = client.post("/api/holdings", json={
        "asset_class": "mutual_fund", "name": "Not yet priced", "units": 1,
        "avg_cost": 294000, "last_price": 350000}).json()
    r = client.post("/api/holdings/set-units", json={"units": [
        {"holding_id": h["id"], "current_value": 350000}]}).json()
    assert r["applied"] == 0
    assert "is a total, not a price per unit" in r["errors"][0]

    # Entering the units directly still works, because that needs no price.
    r = client.post("/api/holdings/set-units", json={"units": [
        {"holding_id": h["id"], "units": 1367.44}]}).json()
    assert r["applied"] == 1


def test_set_units_needs_one_of_the_two_numbers(client):
    h = _placeholder(client)
    r = client.post("/api/holdings/set-units",
                    json={"units": [{"holding_id": h["id"]}]})
    assert r.status_code == 422
    assert "either the units or the current value" in r.json()["detail"]


# ---- the template: give money, get units --------------------------------
TEMPLATE_HEAD = ("owner,asset_class,name,identifier,invested,current_value,"
                 "units,avg_cost,manual_value,last_price,rate,start_date,"
                 "category,bucket,maturity_date,purchase_date,nominee\n")


def test_the_template_works_out_units_from_the_nav(client, monkeypatch):
    """Typing unit counts is the tedious part, and they are derivable:
    what it is worth, divided by today's price."""
    navs = _stub_amfi(monkeypatch, main)
    code, nav = next((c, i["nav"]) for c, i in navs.items()
                     if i["name"].startswith("DSP Midcap Fund - Direct"))
    csv = TEMPLATE_HEAD + (
        "Me,mutual_fund,DSP Midcap Fund,%s,363000,490050,,,0,,0,,equity,,,,\n"
        % code)

    r = client.post("/api/holdings/import",
                    files={"file": ("h.csv", csv, "text/csv")}).json()
    assert r["added"] == 1 and r["errors"] == []
    assert r["units_derived"] == 1

    h = client.get("/api/holdings").json()[0]
    assert round(h["units"], 4) == round(490050 / nav, 4)
    assert round(h["invested"]) == 363000            # what was put in
    assert round(h["current_value"]) == 490050       # what it is worth
    assert h["last_price"] == nav


def test_derived_units_survive_a_price_refresh(client, monkeypatch):
    """Value must follow units x NAV, not be a number stored beside them."""
    navs = _stub_amfi(monkeypatch, main)
    code = next(c for c, i in navs.items()
                if i["name"].startswith("DSP Midcap Fund - Direct"))
    csv = TEMPLATE_HEAD + (
        "Me,mutual_fund,DSP Midcap Fund,%s,363000,490050,,,0,,0,,equity,,,,\n"
        % code)
    client.post("/api/holdings/import",
                files={"file": ("h.csv", csv, "text/csv")})

    body = client.post("/api/prices/refresh").json()
    assert body["mf_updated"] == 1 and body["mf_placeholders"] == []
    h = client.get("/api/holdings").json()[0]
    assert abs(h["units"] * h["last_price"] - h["current_value"]) < 1
    assert abs(h["units"] * h["avg_cost"] - h["invested"]) < 1


def test_a_template_row_with_an_explicit_price_needs_no_lookup(client,
                                                               monkeypatch):
    _stub_amfi(monkeypatch, main)
    csv = TEMPLATE_HEAD + (
        "Me,stock,Reliance,RELIANCE,24000,29500,,,0,2950,0,,,,,,\n")
    r = client.post("/api/holdings/import",
                    files={"file": ("h.csv", csv, "text/csv")}).json()
    assert r["added"] == 1
    h = client.get("/api/holdings").json()[0]
    assert h["units"] == 10.0                        # 29500 / 2950
    assert round(h["avg_cost"]) == 2400              # 24000 / 10


def test_a_template_row_with_no_route_to_units_is_refused(client,
                                                          monkeypatch):
    """Better to reject the row than store a placeholder that breaks later."""
    _stub_amfi(monkeypatch, main)
    csv = TEMPLATE_HEAD + (
        "Me,mutual_fund,Mystery Fund,,363000,490050,,,0,,0,,equity,,,,\n")
    r = client.post("/api/holdings/import",
                    files={"file": ("h.csv", csv, "text/csv")}).json()
    assert r["added"] == 0
    assert "none could be worked out" in r["errors"][0]
    assert client.get("/api/holdings").json() == []


def test_units_given_explicitly_are_still_respected(client, monkeypatch):
    _stub_amfi(monkeypatch, main)
    csv = TEMPLATE_HEAD + (
        "Me,stock,Reliance,RELIANCE,,,10,2400,0,2950,0,,,,,,\n")
    r = client.post("/api/holdings/import",
                    files={"file": ("h.csv", csv, "text/csv")}).json()
    assert r["added"] == 1 and r["units_derived"] == 0
    h = client.get("/api/holdings").json()[0]
    assert h["units"] == 10.0 and h["avg_cost"] == 2400


# ---- keeping a holding up to date after a month of SIPs -----------------
def test_editing_invested_and_value_moves_the_units(client, monkeypatch):
    """What you can see after a SIP is a bigger invested figure and a bigger
    value; how many units the instalment bought is nobody's idea of a
    memorable number."""
    navs = _stub_amfi(monkeypatch, main)
    code, nav = next((c, i["nav"]) for c, i in navs.items()
                     if i["name"].startswith("DSP Midcap Fund - Direct"))
    csv = TEMPLATE_HEAD + (
        "Me,mutual_fund,DSP Midcap Fund,%s,363000,490050,,,0,,0,,equity,,,,\n"
        % code)
    client.post("/api/holdings/import",
                files={"file": ("h.csv", csv, "text/csv")})
    h = client.get("/api/holdings").json()[0]
    units_before = h["units"]

    # A month later: another ₹25,000 in, and the value has moved.
    after = client.put("/api/holdings/%d" % h["id"], json={
        "invested": 388000, "current_value": 530000}).json()

    assert round(after["invested"]) == 388000
    assert round(after["current_value"]) == 530000
    assert round(after["units"], 4) == round(530000 / nav, 4)
    assert after["units"] > units_before                 # the SIP bought some
    assert abs(after["units"] * after["avg_cost"] - 388000) < 1


def test_editing_only_the_invested_amount_keeps_the_value(client,
                                                          monkeypatch):
    navs = _stub_amfi(monkeypatch, main)
    code, nav = next((c, i["nav"]) for c, i in navs.items()
                     if i["name"].startswith("DSP Midcap Fund - Direct"))
    csv = TEMPLATE_HEAD + (
        "Me,mutual_fund,DSP Midcap Fund,%s,363000,490050,,,0,,0,,equity,,,,\n"
        % code)
    client.post("/api/holdings/import",
                files={"file": ("h.csv", csv, "text/csv")})
    h = client.get("/api/holdings").json()[0]

    after = client.put("/api/holdings/%d" % h["id"],
                       json={"invested": 388000}).json()
    assert round(after["invested"]) == 388000
    assert round(after["current_value"]) == 490050       # untouched
    assert after["last_price"] == nav


def test_a_holding_with_no_usable_price_absorbs_the_change_in_the_price(
        client):
    """Units cannot move without a real per-unit price -- and a price equal
    to the cost is the placeholder written at creation, not a live one. Both
    figures the user gave must still come out true."""
    h = client.post("/api/holdings", json={
        "asset_class": "gold_physical", "name": "Gold jewellery",
        "units": 85, "avg_cost": 4800}).json()
    after = client.put("/api/holdings/%d" % h["id"], json={
        "invested": 408000, "current_value": 616250}).json()
    assert after["units"] == 85                          # unchanged
    assert round(after["current_value"]) == 616250
    assert round(after["invested"]) == 408000
    assert round(after["last_price"], 2) == round(616250 / 85, 2)


def test_the_money_figures_stay_consistent_after_editing(client, monkeypatch):
    navs = _stub_amfi(monkeypatch, main)
    code = next(c for c, i in navs.items()
                if i["name"].startswith("DSP Midcap Fund - Direct"))
    csv = TEMPLATE_HEAD + (
        "Me,mutual_fund,DSP Midcap Fund,%s,363000,490050,,,0,,0,,equity,,,,\n"
        % code)
    client.post("/api/holdings/import",
                files={"file": ("h.csv", csv, "text/csv")})
    h = client.get("/api/holdings").json()[0]
    client.put("/api/holdings/%d" % h["id"],
               json={"invested": 388000, "current_value": 530000})
    client.post("/api/prices/refresh")

    after = client.get("/api/holdings").json()[0]
    assert abs(after["units"] * after["avg_cost"] - after["invested"]) < 1
    assert abs(after["units"] * after["last_price"]
               - after["current_value"]) < 1


def test_a_holding_already_flattened_is_not_given_invented_units(client,
                                                                 monkeypatch):
    """Its recorded price is already a NAV; dividing one NAV by another is
    not a unit count. It stays flagged for the real figure instead."""
    navs = _stub_amfi(monkeypatch, main)
    h = _placeholder(client, name="DSP Midcap Fund", invested=363000,
                     price=559)            # already flattened by a NAV
    row = client.get("/api/amfi/suggest-codes").json()["holdings"][0]
    code = row["candidates"][0]["code"]

    r = client.post("/api/amfi/apply-codes", json={"assignments": [
        {"holding_id": h["id"], "scheme_code": code}]}).json()
    assert r["applied"] == 1
    assert r["derived_units"] == []        # nothing invented

    after = client.get("/api/holdings").json()[0]
    assert after["units"] == 1             # untouched
    assert after["last_price"] == navs[code]["nav"]
    # and it is still listed as needing a real unit count
    assert client.get("/api/holdings/unit-placeholders").json()["holdings"]


def test_a_placeholder_can_be_renamed_to_the_scheme_it_turns_out_to_be(
        client, monkeypatch):
    """"HDFC MF via Zerodha Coin (scheme name TBC)" is a note to self."""
    navs = _stub_amfi(monkeypatch, main)
    h = client.post("/api/holdings", json={
        "asset_class": "mutual_fund", "units": 100, "avg_cost": 50,
        "name": "HDFC MF via Zerodha Coin (scheme name TBC)"}).json()
    code, info = next(iter(navs.items()))

    r = client.post("/api/amfi/apply-codes", json={"assignments": [
        {"holding_id": h["id"], "scheme_code": code,
         "adopt_name": True}]}).json()
    assert r["applied"] == 1 and r["renamed"] == 1
    assert client.get("/api/holdings").json()[0]["name"] == info["name"]


def test_a_name_is_only_replaced_when_asked(client, monkeypatch):
    navs = _stub_amfi(monkeypatch, main)
    h = client.post("/api/holdings", json={
        "asset_class": "mutual_fund", "name": "My own label",
        "units": 100, "avg_cost": 50}).json()
    code = next(iter(navs))
    client.post("/api/amfi/apply-codes", json={"assignments": [
        {"holding_id": h["id"], "scheme_code": code}]})
    assert client.get("/api/holdings").json()[0]["name"] == "My own label"


def test_amfi_can_be_searched_for_a_fund_no_name_could_match(client,
                                                             monkeypatch):
    _stub_amfi(monkeypatch, main)
    body = client.get("/api/amfi/candidates?q=DSP Midcap").json()
    assert body["candidates"]
    assert body["candidates"][0]["name"].startswith("DSP Midcap Fund - Direct")


# ---- nothing may be unclassifiable ---------------------------------------
def test_every_holding_carrying_equity_can_be_tagged(client):
    """Restricting the override by asset class left holdings that count as
    equity with no way to say what size they are — permanently unclassified
    and permanently unfixable."""
    forced = client.post("/api/holdings", json={
        "asset_class": "other", "name": "Employer ESOP", "units": 100,
        "avg_cost": 500, "meta": {"bucket": "equity"}}).json()
    assert forced["has_equity"] is True
    assert forced["cap_label"] == ""          # nothing could be read

    client.put("/api/holdings/%d" % forced["id"], json={"meta": {"cap": "large"}})
    after = client.get("/api/holdings").json()[0]
    assert after["cap_label"] == "Large cap"
    assert after["cap_source"] == "set by you"
    assert client.get("/api/summary").json()["cap_mix"]["unclassified"] == 0


def test_a_fund_whose_name_says_nothing_can_still_be_set(client):
    h = client.post("/api/holdings", json={
        "asset_class": "mutual_fund", "name": "My PMS account", "units": 10,
        "avg_cost": 1000, "meta": {"category": "equity"}}).json()
    assert h["has_equity"] is True and h["cap_label"] == ""
    client.put("/api/holdings/%d" % h["id"], json={"meta": {"cap": "mid"}})
    assert client.get("/api/holdings").json()[0]["cap_label"] == "Mid cap"


def test_a_holding_with_no_equity_is_not_asked_about(client):
    h = client.post("/api/holdings", json={
        "asset_class": "fd", "name": "Bank FD", "avg_cost": 500000,
        "rate": 7.0, "start_date": "2025-01-01"}).json()
    assert h["has_equity"] is False


def test_an_auto_classified_fund_reports_what_it_read_and_why(client):
    h = client.post("/api/holdings", json={
        "asset_class": "mutual_fund", "units": 100, "avg_cost": 50,
        "name": "DSP Midcap Fund - Direct Plan - Growth",
        "meta": {"category": "equity"}}).json()
    assert h["cap_label"] == "80/10/10 mid/large/small" or "mid" in h["cap_label"]
    assert "SEBI" in h["cap_source"]


def test_the_chart_can_name_what_it_could_not_classify(client):
    """"Something is unclassified" with no way to find out what sends the
    reader hunting through the whole table."""
    client.post("/api/holdings", json={
        "asset_class": "stock", "name": "Tips Music", "units": 10,
        "avg_cost": 5100, "meta": {}})
    mix = client.get("/api/summary").json()["cap_mix"]
    unnamed = [r for r in mix["holdings"] if r["why"] == "not classified"]
    assert [r["name"] for r in unnamed] == ["Tips Music"]
    assert unnamed[0]["equity"] == 51000


# ---- running as a downloaded application --------------------------------
def test_the_data_folder_is_never_inside_the_bundle(monkeypatch):
    """A PyInstaller bundle unpacks into a temporary folder that is deleted
    on quit. Writing the portfolio there would lose it every time."""
    import paths

    monkeypatch.setattr(paths, "is_frozen", lambda: True)
    monkeypatch.setattr(sys, "_MEIPASS", "/tmp/_MEI_unpacked", raising=False)
    monkeypatch.setattr(paths, "portable_dir", lambda: "")

    assert paths.bundle_dir() == "/tmp/_MEI_unpacked"
    assert paths.default_data_dir() == paths.user_data_dir()
    assert "_MEI" not in paths.default_data_dir()


def test_a_portfolio_beside_the_app_is_used_where_it_lies(tmp_path,
                                                          monkeypatch):
    """Someone who copies their data onto a USB stick beside the app means
    that copy to be used."""
    import paths

    monkeypatch.setattr(paths, "is_frozen", lambda: True)
    monkeypatch.setattr(paths, "app_dir", lambda: str(tmp_path))
    assert paths.portable_dir() == ""              # nothing there yet
    assert paths.default_data_dir() == paths.user_data_dir()

    (tmp_path / "portfolio.db").write_bytes(b"")
    assert paths.default_data_dir() == str(tmp_path)


def test_the_frontend_is_found_inside_the_bundle(monkeypatch):
    import paths

    monkeypatch.setattr(paths, "is_frozen", lambda: True)
    monkeypatch.setattr(sys, "_MEIPASS", "/tmp/_MEI_unpacked", raising=False)
    assert paths.frontend_dist() == "/tmp/_MEI_unpacked/frontend/dist"


def test_a_busy_port_does_not_stop_the_app(monkeypatch):
    """A second copy, or anything else on that port, must not put a stack
    trace on a stranger's screen."""
    import socket

    import desktop

    taken = socket.socket()
    taken.bind((desktop.HOST, 0))
    taken.listen(1)                                # exactly what a server does
    port = taken.getsockname()[1]
    try:
        assert desktop.free_port(port) == port + 1
    finally:
        taken.close()


def test_the_app_only_ever_serves_the_machine_it_is_on():
    import desktop
    assert desktop.HOST == "127.0.0.1"             # never 0.0.0.0


# ---- the interface must not be older than the code -----------------------
def test_a_build_older_than_its_sources_is_detected(tmp_path, monkeypatch):
    """Rebuilding only when the folder is missing was the bug: after a pull
    the folder is still there, so months-old HTML gets served against
    today's API and whole pages are simply absent."""
    import os
    import paths

    frontend = tmp_path / "frontend"
    (frontend / "dist").mkdir(parents=True)
    (frontend / "src").mkdir()
    monkeypatch.setattr(paths, "is_frozen", lambda: False)
    monkeypatch.setattr(paths, "bundle_dir", lambda: str(tmp_path))

    assert paths.frontend_is_stale() is True       # no index.html at all

    built = frontend / "dist" / "index.html"
    built.write_text("<html></html>")
    source = frontend / "src" / "App.jsx"
    source.write_text("x")
    os.utime(source, (1, 1))                       # source older than build
    assert paths.frontend_is_stale() is False

    os.utime(built, (1, 1))                        # build older than source
    os.utime(source, None)
    assert paths.frontend_is_stale() is True


def test_package_json_counts_as_a_source(tmp_path, monkeypatch):
    import os
    import paths

    frontend = tmp_path / "frontend"
    (frontend / "dist").mkdir(parents=True)
    built = frontend / "dist" / "index.html"
    built.write_text("<html></html>")
    os.utime(built, (1, 1))
    (frontend / "package.json").write_text("{}")

    monkeypatch.setattr(paths, "is_frozen", lambda: False)
    monkeypatch.setattr(paths, "bundle_dir", lambda: str(tmp_path))
    assert paths.frontend_is_stale() is True


def test_a_bundled_app_carries_its_own_build(monkeypatch):
    """It cannot rebuild and does not need to."""
    import paths
    monkeypatch.setattr(paths, "is_frozen", lambda: True)
    assert paths.frontend_is_stale() is False


# ---- finding npm on Windows ---------------------------------------------
def test_npm_prefers_the_one_windows_can_run(tmp_path, monkeypatch):
    """A Node install puts two files on the PATH: `npm`, a Unix shell
    script, and `npm.cmd`. Since Python 3.12 shutil.which() returns an
    extensionless match when one exists, so which("npm") hands back the
    shell script and CreateProcess refuses it:
    "%1 is not a valid Win32 application"."""
    import desktop

    nodejs = tmp_path / "nodejs"
    nodejs.mkdir()
    (nodejs / "npm").write_text("#!/bin/sh\n")        # the shell script
    (nodejs / "npm.cmd").write_text("@echo off\n")    # the Windows one

    def fake_which(name):
        candidate = nodejs / name
        return str(candidate) if candidate.exists() else None

    monkeypatch.setattr(desktop.shutil, "which", fake_which)

    monkeypatch.setattr(desktop.os, "name", "nt")
    assert desktop.npm().endswith("npm.cmd")

    monkeypatch.setattr(desktop.os, "name", "posix")
    assert desktop.npm().endswith("npm")
    assert not desktop.npm().endswith(".cmd")


def test_no_node_at_all_is_reported_not_crashed(monkeypatch):
    import desktop
    monkeypatch.setattr(desktop.shutil, "which", lambda name: None)
    assert desktop.npm() == ""


def test_a_build_step_that_cannot_start_is_a_sentence_not_a_traceback(
        monkeypatch, capsys):
    """WinError 193 arrived as a stack trace ending in subprocess.py. The
    person reading it wants to know what to do."""
    import desktop

    def refuse(*a, **k):
        raise OSError(8, "%1 is not a valid Win32 application")

    monkeypatch.setattr(desktop.subprocess, "call", refuse)
    assert desktop.run("npm", ["run", "build"], ".") is False
    printed = capsys.readouterr().out
    assert "Could not run npm run build" in printed
    assert "Traceback" not in printed


# ---- an update has to actually reach the browser ------------------------
def test_the_page_is_never_cached_but_its_assets_always_are(client):
    """Without a Cache-Control header a browser invents a freshness lifetime
    from the file's age, so a months-old index.html is cached for weeks and
    never requested again. Rebuilding then changes nothing on screen."""
    page = client.get("/")
    if page.status_code == 404:
        pytest.skip("frontend not built in this checkout")
    assert page.headers["cache-control"] == "no-cache, must-revalidate"

    import re
    asset = re.search(r'/assets/[^"\']+\.js', page.text)
    assert asset, "the built page should reference a hashed asset"
    served = client.get(asset.group(0))
    assert served.status_code == 200
    # Hashed filenames make a changed file a changed URL, so these are safe
    # to keep forever — and keeping them is what makes reloads cheap.
    assert "immutable" in served.headers["cache-control"]


def test_the_launcher_reports_when_the_interface_was_built(tmp_path,
                                                           monkeypatch):
    """"It rebuilt" and "you are looking at the rebuild" are different
    claims, and only the second one matters."""
    import desktop
    import paths

    dist = tmp_path / "dist"
    dist.mkdir()
    monkeypatch.setattr(paths, "frontend_dist", lambda: str(dist))
    assert desktop.built_at() == "not built"

    (dist / "index.html").write_text("<html></html>")
    assert desktop.built_at() != "not built"
    assert "20" in desktop.built_at()               # a real year


# ---------------- calculators ----------------
def test_sip_endpoint_returns_a_projection(client):
    r = client.post("/api/calc/sip", json={"monthly": 10000,
                                           "annual_return_pct": 12,
                                           "years": 10})
    assert r.status_code == 200
    body = r.json()
    assert body["invested"] == 1200000
    assert body["value"] > body["invested"]
    assert body["rows"][-1]["year"] == 10
    assert any("Tax" in n for n in body["notes"])


def test_sip_endpoint_inverts_when_given_a_target(client):
    r = client.post("/api/calc/sip", json={"target": 5000000,
                                           "annual_return_pct": 12,
                                           "years": 10})
    assert r.status_code == 200
    body = r.json()
    assert body["target_plan"]["monthly"] > 0
    # The forward projection it returns must actually reach the target.
    assert body["value"] >= 5000000


def test_sip_endpoint_rejects_an_empty_plan(client):
    r = client.post("/api/calc/sip", json={"annual_return_pct": 12, "years": 10})
    assert r.status_code == 422


def test_sip_endpoint_rejects_an_absurd_return(client):
    r = client.post("/api/calc/sip", json={"monthly": 1000,
                                           "annual_return_pct": 5000,
                                           "years": 10})
    assert r.status_code == 422


def test_sip_endpoint_rejects_a_misspelled_field(client):
    r = client.post("/api/calc/sip", json={"monthly": 1000, "yrs": 10})
    assert r.status_code == 422


def test_swp_endpoint_reports_survival_and_the_sustainable_amount(client):
    r = client.post("/api/calc/swp", json={"corpus": 10000000,
                                           "monthly_withdrawal": 30000,
                                           "annual_return_pct": 8,
                                           "years": 25})
    assert r.status_code == 200
    body = r.json()
    assert body["survives"] is True
    assert body["sustainable"]["monthly"] > 30000
    assert body["rows"][0]["balance"] == 10000000


def test_swp_endpoint_says_when_the_money_runs_out(client):
    r = client.post("/api/calc/swp", json={"corpus": 1000000,
                                           "monthly_withdrawal": 50000,
                                           "annual_return_pct": 8,
                                           "years": 25})
    body = r.json()
    assert body["survives"] is False
    assert body["depleted_year"] is not None
    assert any("runs out" in n for n in body["notes"])


def test_swp_endpoint_rejects_a_zero_corpus(client):
    r = client.post("/api/calc/swp", json={"corpus": 0,
                                           "monthly_withdrawal": 1000})
    assert r.status_code == 422


def test_the_calculators_need_no_profile_or_data(client):
    """They are pure what-ifs: an empty installation must still answer."""
    for path, body in (("/api/calc/sip", {"monthly": 1000}),
                       ("/api/calc/swp", {"corpus": 100000,
                                          "monthly_withdrawal": 500})):
        assert client.post(path, json=body).status_code == 200


def test_the_rate_convention_is_effective_unless_asked_otherwise(client):
    r = client.post("/api/calc/sip", json={"monthly": 10000, "years": 1,
                                           "annual_return_pct": 15})
    body = r.json()
    assert body["assumptions"]["rate_mode"] == "effective"
    # The workbooks' own month-12 figure for this exact plan.
    assert body["value"] == pytest.approx(129541.88, abs=0.01)


def test_the_simple_convention_can_be_asked_for(client):
    r = client.post("/api/calc/sip", json={"monthly": 10000, "years": 1,
                                           "annual_return_pct": 15,
                                           "rate_mode": "simple"})
    assert r.status_code == 200
    assert r.json()["value"] > 129541.88


def test_an_invented_rate_convention_is_rejected(client):
    r = client.post("/api/calc/sip", json={"monthly": 10000,
                                           "rate_mode": "vibes"})
    assert r.status_code == 422


def test_a_price_feed_that_answers_with_nothing_says_so(client, monkeypatch):
    """"Check your tickers" is the wrong advice when the feed is empty.

    A 200 carrying no price is neither a broken connection nor a wrong
    symbol, and sending someone to re-check forty tickers they typed
    correctly is the most expensive way to be unhelpful.
    """
    import netlog
    import pricing
    assert client.post("/api/holdings", json={
        "asset_class": "stock", "name": "Reliance",
        "identifier": "RELIANCE", "units": 10,
        "avg_cost": 100}).status_code == 200

    def empty_chart(url, timeout, head_bytes=0):
        class R:
            content = b"{}"

            def json(self):
                return {"chart": {"result": None,
                                  "error": {"description": "No data found"}}}
        netlog.record("query1.finance.yahoo.com", "Stock prices", "ok", "2 b")
        return R()

    monkeypatch.setattr(pricing, "_get", empty_chart)
    monkeypatch.setattr(pricing, "fetch_amfi",
                        lambda *a, **k: ({}, {}, pricing.AMFI_OK))
    body = client.post("/api/prices/refresh").json()
    assert body["stocks_updated"] == 0
    assert body["stock_failed"]
    assert "feed rather than your tickers" in body["stock_reason"]


def test_a_wrong_ticker_does_not_blame_the_feed(client, monkeypatch):
    """The same message must not appear when some lookups did work."""
    import pricing
    for name, ident in (("Reliance", "RELIANCE"), ("Typo", "NOTATICKER")):
        assert client.post("/api/holdings", json={
            "asset_class": "stock", "name": name, "identifier": ident,
            "units": 10, "avg_cost": 100}).status_code == 200
    monkeypatch.setattr(pricing, "fetch_amfi",
                        lambda *a, **k: ({}, {}, pricing.AMFI_OK))
    monkeypatch.setattr(
        pricing, "fetch_stock_prices",
        lambda syms, **k: {"RELIANCE": (1400.0, date(2026, 8, 28)),
                           "NOTATICKER": (None, None)})
    body = client.post("/api/prices/refresh").json()
    assert body["stocks_updated"] == 1
    assert body["stock_failed"] and not body["stock_reason"]
