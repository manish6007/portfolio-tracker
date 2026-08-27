"""Profiles: one installation, several separate portfolios.

The point of these is not access control -- it is that nothing of yours can
appear while someone else is looking at the screen, so the tests are about
isolation and about not being able to delete the wrong thing.
"""
import json

import pytest

import config
import db
import main
import profiles as profiles_mod
import schemas


@pytest.fixture
def store(tmp_path, monkeypatch):
    """A fresh installation: empty registry, empty profile directory."""
    monkeypatch.setattr(config, "BASE", str(tmp_path))
    monkeypatch.setattr(config, "CONFIG_PATH", str(tmp_path / "app-config.json"))
    monkeypatch.delenv(config.ENV_DATA_DIR, raising=False)
    monkeypatch.setattr(db, "_engines", {})
    monkeypatch.setattr(db, "_factories", {})
    return tmp_path


def _use(monkeypatch, pid):
    """Pretend a request arrived carrying that profile's cookie."""
    monkeypatch.setattr(main, "_profile", type("V", (), {
        "get": staticmethod(lambda: pid)})())


def test_a_new_installation_has_one_profile(store):
    ps = profiles_mod.list_profiles()
    assert len(ps) == 1
    assert ps[0]["id"] == profiles_mod.DEFAULT_ID
    # It points at the file a pre-profiles install already had.
    assert profiles_mod.path_for("default").endswith("portfolio.db")


def test_holdings_do_not_leak_between_profiles(store, monkeypatch):
    profiles_mod.create("Demo", demo=False)

    _use(monkeypatch, "default")
    main.add_holding(schemas.HoldingIn(
        asset_class="stock", name="My real stock", units=10, avg_cost=100))

    _use(monkeypatch, "demo")
    assert main.list_holdings() == []              # nothing of yours is here
    main.add_holding(schemas.HoldingIn(
        asset_class="stock", name="Demo stock", units=1, avg_cost=5))
    assert [h["name"] for h in main.list_holdings()] == ["Demo stock"]

    _use(monkeypatch, "default")
    assert [h["name"] for h in main.list_holdings()] == ["My real stock"]


def test_settings_do_not_leak_between_profiles(store, monkeypatch):
    profiles_mod.create("Demo")
    _use(monkeypatch, "default")
    main.put_settings(schemas.SettingsIn(
        targets={"equity": 60, "debt": 30, "gold": 10}))
    _use(monkeypatch, "demo")
    s = db.get_session(profiles_mod.path_for("demo"))
    assert db.get_setting(s, "targets", "") == ""
    s.close()


def test_each_profile_gets_its_own_file(store):
    profiles_mod.create("Wife")
    assert profiles_mod.path_for("wife").endswith("profiles/wife.db")
    assert profiles_mod.path_for("wife") != profiles_mod.path_for("default")


def test_duplicate_names_are_refused(store):
    profiles_mod.create("Demo")
    with pytest.raises(ValueError):
        profiles_mod.create("demo")               # same slug


def test_a_nameless_profile_is_refused(store):
    for bad in ("", "   ", "!!!"):
        with pytest.raises(ValueError):
            profiles_mod.create(bad)


def test_the_first_profile_cannot_be_deleted(store):
    """It holds whatever an installation had before profiles existed."""
    with pytest.raises(ValueError):
        profiles_mod.delete(profiles_mod.DEFAULT_ID)


def test_deleting_needs_the_name_typed_back(store):
    profiles_mod.create("Demo")
    with pytest.raises(main.HTTPException):
        main.delete_profile("demo", schemas.ConfirmIn(confirm="nope"))
    assert main.delete_profile("demo", schemas.ConfirmIn(confirm="Demo"))["ok"]
    assert [p["id"] for p in profiles_mod.list_profiles()] == ["default"]


def test_deleting_a_profile_takes_its_data_file(store, monkeypatch):
    profiles_mod.create("Demo")
    _use(monkeypatch, "demo")
    main.add_holding(schemas.HoldingIn(
        asset_class="stock", name="Demo stock", units=1, avg_cost=5))
    path = profiles_mod.path_for("demo")
    import os
    assert os.path.exists(path)
    main.delete_profile("demo", schemas.ConfirmIn(confirm="Demo"))
    assert not os.path.exists(path)


def test_an_unknown_profile_falls_back_rather_than_erroring(store, monkeypatch):
    """A tab left open on a deleted profile should land somewhere sane."""
    _use(monkeypatch, "was-deleted")
    assert main.list_holdings() == []
    assert profiles_mod.get("was-deleted")["id"] == profiles_mod.DEFAULT_ID


def test_the_registry_survives_being_corrupted(store):
    with open(profiles_mod.registry_path(), "w") as fh:
        fh.write("{not json")
    assert profiles_mod.list_profiles()[0]["id"] == profiles_mod.DEFAULT_ID


def test_a_demo_profile_comes_seeded(store, monkeypatch):
    main.create_profile(schemas.ProfileIn(name="Demo", demo=True))
    _use(monkeypatch, "demo")
    assert main.list_holdings()                    # the fake household is here
    _use(monkeypatch, "default")
    assert main.list_holdings() == []              # and only there


def test_the_registry_is_written_atomically(store):
    profiles_mod.create("Demo")
    with open(profiles_mod.registry_path()) as fh:
        assert len(json.load(fh)["profiles"]) == 2
