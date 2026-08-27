"""Machine-level settings: where the data lives, and whether to go online.

Separate from the per-portfolio settings table on purpose. These two answers
have to be available before any database is opened, and they are the two
questions a sceptical user asks first -- "where exactly is my data" and
"what does this thing talk to". Keeping them in one small readable file next
to the code means the answer can be checked without trusting the UI.
"""
import json
import os
import shutil
from datetime import datetime

import paths

# Both of these must sit somewhere that survives quitting the app. When it
# runs as a built application the code unpacks into a temporary folder, so
# "next to the code" is exactly the wrong answer.
BASE = paths.default_data_dir()
CONFIG_PATH = os.path.join(BASE, "app-config.json")
ENV_DATA_DIR = "PORTFOLIO_DATA_DIR"


def _read():
    try:
        with open(CONFIG_PATH) as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write(data):
    tmp = CONFIG_PATH + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(data, fh, indent=2)
    os.replace(tmp, CONFIG_PATH)


def data_dir():
    """Folder holding every database file.

    An environment variable wins, so a data directory can be pinned without
    trusting anything the app writes; then a folder chosen in the UI; then
    the code directory, which is where an installation that predates this
    already has its portfolio.db.
    """
    return (os.environ.get(ENV_DATA_DIR)
            or _read().get("data_dir")
            or BASE)


def data_dir_source():
    if os.environ.get(ENV_DATA_DIR):
        return "environment"
    if _read().get("data_dir"):
        return "chosen"
    return "default"


def set_data_dir(path):
    path = os.path.abspath(os.path.expanduser((path or "").strip()))
    if not path:
        raise ValueError("Give a folder path.")
    try:
        os.makedirs(path, exist_ok=True)
        probe = os.path.join(path, ".write-test")
        with open(probe, "w") as fh:
            fh.write("ok")
        os.remove(probe)
    except OSError as exc:
        raise ValueError("That folder cannot be written to: %s" % exc)
    data = _read()
    data["data_dir"] = path
    _write(data)
    return path


def clear_data_dir():
    data = _read()
    data.pop("data_dir", None)
    _write(data)
    return data_dir()


DATA_FILES = ("portfolio.db", "profiles.json")


def data_files(directory=None):
    """Every file the app keeps, with its size and when it was last written.

    This is the answer to "where is my data" -- real paths on this machine,
    so it can be checked in a file manager rather than believed.
    """
    directory = directory or data_dir()
    out = []
    candidates = [os.path.join(directory, n) for n in DATA_FILES]
    profiles = os.path.join(directory, "profiles")
    if os.path.isdir(profiles):
        candidates += [os.path.join(profiles, n)
                       for n in sorted(os.listdir(profiles))
                       if n.endswith(".db")]
    for path in candidates:
        try:
            st = os.stat(path)
        except OSError:
            continue
        out.append({"path": path, "bytes": st.st_size,
                    "modified": datetime.fromtimestamp(
                        st.st_mtime).isoformat(timespec="seconds")})
    return out


def move_data(new_dir):
    """Copy the data files to a new folder and start using it.

    Copies, never moves: if anything goes wrong the originals are still
    where they were. The old copies are left behind deliberately and the
    caller is told where, so deleting them stays the user's decision.
    """
    old = data_dir()
    new = os.path.abspath(os.path.expanduser((new_dir or "").strip()))
    if not new:
        raise ValueError("Give a folder path.")
    if os.path.normpath(new) == os.path.normpath(old):
        raise ValueError("The data is already in that folder.")
    set_data_dir(new)                    # validates it is writable
    copied = []
    try:
        for entry in data_files(old):
            rel = os.path.relpath(entry["path"], old)
            dest = os.path.join(new, rel)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.copy2(entry["path"], dest)
            if os.path.getsize(dest) != entry["bytes"]:
                raise OSError("copy of %s came out a different size" % rel)
            copied.append(rel)
    except OSError as exc:
        set_data_dir(old)                # put it back; nothing was destroyed
        raise ValueError("Could not copy the data: %s. Nothing was moved."
                         % exc)
    return {"from": old, "to": new, "copied": copied}


def offline():
    """True when the app must make no outbound request at all."""
    return bool(_read().get("offline"))


def set_offline(value):
    data = _read()
    data["offline"] = bool(value)
    _write(data)
    return data["offline"]
