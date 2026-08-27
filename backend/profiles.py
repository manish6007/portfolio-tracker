"""Separate portfolios in one installation.

The problem this solves is not security, it is embarrassment: you cannot
show the app to anyone while your own salary and net worth are on the
screen. A profile is a whole separate database file -- switch to "Demo" and
every page shows that household instead, with nothing of yours reachable
from it.

It is deliberately not a login. On your own laptop a password box would be
theatre: whoever holds the machine can open the .db file whatever the
screen says. What profiles give you is separation, which is the part that
was actually missing. If this is ever hosted for other people, real accounts
belong on top of this boundary rather than instead of it -- every request
already carries which profile it is for.
"""
import json
import os
import re

import config

DEFAULT_ID = "default"
DEFAULT_FILE = "portfolio.db"          # where a pre-profiles install already is
MAX_PROFILES = 20


# Every path is resolved through these rather than fixed at import, so
# pointing the app at a different folder -- an encrypted volume, a synced
# drive, a USB stick -- takes effect without restarting anything.
def profile_dir():
    return os.path.join(config.data_dir(), "profiles")


def registry_path():
    return os.path.join(config.data_dir(), "profiles.json")


def _read():
    try:
        with open(registry_path()) as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        data = {}
    profiles = data.get("profiles")
    if not isinstance(profiles, list) or not profiles:
        profiles = [{"id": DEFAULT_ID, "name": "My portfolio",
                     "file": DEFAULT_FILE, "demo": False}]
    return {"profiles": profiles}


def _write(data):
    os.makedirs(config.data_dir(), exist_ok=True)
    path = registry_path()
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(data, fh, indent=2)
    os.replace(tmp, path)              # never leave a half-written registry


def slugify(name):
    slug = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    return slug[:40]


def list_profiles():
    return _read()["profiles"]


def get(profile_id):
    """The named profile, or the default one.

    An unknown id falls back rather than raising: a stale tab holding a
    deleted profile should land somewhere sane, not error on every request.
    """
    profiles = list_profiles()
    for p in profiles:
        if p["id"] == (profile_id or DEFAULT_ID):
            return p
    return profiles[0]


def path_for(profile_id):
    p = get(profile_id)
    if p["file"] == DEFAULT_FILE:
        return os.path.join(config.data_dir(), DEFAULT_FILE)
    return os.path.join(profile_dir(), p["file"])


def create(name, demo=False):
    """Add a profile. Its database file is created on first use."""
    name = (name or "").strip()
    if not name:
        raise ValueError("Give the profile a name.")
    data = _read()
    if len(data["profiles"]) >= MAX_PROFILES:
        raise ValueError("That is %d profiles already — delete one first."
                         % MAX_PROFILES)
    slug = slugify(name)
    if not slug:
        raise ValueError("Use some letters or numbers in the name.")
    existing = {p["id"] for p in data["profiles"]}
    if slug in existing:
        raise ValueError("A profile called %r already exists." % name)
    os.makedirs(profile_dir(), exist_ok=True)
    profile = {"id": slug, "name": name[:60], "file": slug + ".db",
               "demo": bool(demo)}
    data["profiles"].append(profile)
    _write(data)
    return profile


def rename(profile_id, name):
    name = (name or "").strip()
    if not name:
        raise ValueError("Give the profile a name.")
    data = _read()
    for p in data["profiles"]:
        if p["id"] == profile_id:
            p["name"] = name[:60]
            _write(data)
            return p
    raise ValueError("No such profile.")


def delete(profile_id):
    """Remove a profile and its data file.

    The default profile is never deletable: it is where an installation that
    predates profiles keeps everything, so a mis-click there would erase the
    real portfolio.
    """
    if profile_id == DEFAULT_ID:
        raise ValueError("The first profile cannot be deleted — it holds the "
                         "data this installation started with. Use Erase all "
                         "data inside it if that is really what you want.")
    data = _read()
    keep = [p for p in data["profiles"] if p["id"] != profile_id]
    if len(keep) == len(data["profiles"]):
        raise ValueError("No such profile.")
    gone = [p for p in data["profiles"] if p["id"] == profile_id][0]
    data["profiles"] = keep
    _write(data)
    try:
        os.remove(os.path.join(profile_dir(), gone["file"]))
    except OSError:
        pass                            # never created, or already gone
    return gone
