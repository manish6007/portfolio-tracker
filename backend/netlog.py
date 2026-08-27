"""A log of every outbound request the app makes.

The app has always been local-only, but a user cannot see that -- and
"trust us" is not an answer. So every call that leaves this machine is
recorded with its host and outcome and shown in the app, alongside a switch
that stops them happening at all. A short claim you can check beats a long
privacy policy you cannot.

The log lives in memory and covers the current run. It is written by the
code that makes the calls, so it can only be as honest as that code -- which
is why the list of hosts it can ever contain is fixed here, and the app
refuses to call anything else.
"""
import threading
from datetime import datetime

# Everything the app is allowed to contact, and why. Anything not in here is
# refused before a connection is opened, so the log cannot quietly grow a
# host the user did not agree to.
ALLOWED_HOSTS = {
    "www.amfiindia.com": "Mutual-fund NAVs (AMFI, the industry body)",
    "query1.finance.yahoo.com": "Stock prices (Yahoo Finance)",
    "query2.finance.yahoo.com": "Stock prices (Yahoo Finance)",
    "fc.yahoo.com": "Stock prices (Yahoo Finance)",
}

MAX_ENTRIES = 200
_lock = threading.Lock()
_entries = []


def record(host, purpose, outcome, detail=""):
    with _lock:
        _entries.append({
            "at": datetime.now().isoformat(timespec="seconds"),
            "host": host, "purpose": purpose,
            "outcome": outcome, "detail": detail[:200],
        })
        del _entries[:-MAX_ENTRIES]


def entries():
    with _lock:
        return list(reversed(_entries))


def clear():
    with _lock:
        _entries.clear()


def purpose_for(host):
    return ALLOWED_HOSTS.get(host, "")
