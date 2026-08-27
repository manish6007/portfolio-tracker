"""Where the app lives and where its data goes.

Running from source and running as a downloaded application are different
worlds, and the difference is not cosmetic: a PyInstaller bundle unpacks
itself into a temporary folder that is wiped when the process exits. Writing
the portfolio there would lose every rupee of it on quit.

So the code and the data are separated. Code comes from the bundle; data
goes to the place each operating system keeps a user's own files, unless
the folder next to the application already holds a portfolio -- which is how
someone runs the whole thing off a USB stick.
"""
import os
import sys

APP_NAME = "PortfolioTracker"


def is_frozen():
    """True when running as a built application rather than from source."""
    return bool(getattr(sys, "frozen", False))


def bundle_dir():
    """Read-only files shipped with the app: the built frontend."""
    if is_frozen():
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def app_dir():
    """The folder the application itself sits in."""
    if is_frozen():
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def user_data_dir():
    """Where this operating system keeps a user's own application data."""
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    elif sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    else:
        base = (os.environ.get("XDG_DATA_HOME")
                or os.path.expanduser("~/.local/share"))
    return os.path.join(base, APP_NAME)


def portable_dir():
    """The folder beside the application, when it already holds a portfolio.

    Someone who unzips the app onto a USB stick and copies their data in
    beside it means for that copy to be used. Only an existing file counts:
    creating one there by default would scatter portfolios across download
    folders.
    """
    beside = app_dir()
    for name in ("portfolio.db", "app-config.json"):
        if os.path.exists(os.path.join(beside, name)):
            return beside
    return ""


def default_data_dir():
    """Where the portfolio lives when nothing else has been chosen.

    From source that is the backend folder, unchanged, so an existing
    checkout keeps its database exactly where it was.
    """
    if not is_frozen():
        return os.path.dirname(os.path.abspath(__file__))
    return portable_dir() or user_data_dir()


def frontend_dist():
    return os.path.join(bundle_dir(), "frontend", "dist")


# Files that, if newer than the build, mean the build is out of date.
_FRONTEND_SOURCES = ("src", "index.html", "package.json", "package-lock.json",
                     "vite.config.js", "vite.config.mjs", "vite.config.ts")


def _newest_mtime(path):
    if os.path.isfile(path):
        return os.path.getmtime(path)
    newest = 0.0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                newest = max(newest, os.path.getmtime(os.path.join(root, name)))
            except OSError:
                continue
    return newest


def frontend_is_stale():
    """True when the interface was built before the code it is built from.

    A build only runs when someone remembers to run it, and after a `git
    pull` nobody does -- so the app serves months-old HTML against today's
    API and half the pages are simply missing. Checking is cheap; being
    wrong about it is a confusing afternoon.

    Only meaningful from source. A bundled app carries its own build.
    """
    if is_frozen():
        return False
    built = os.path.join(frontend_dist(), "index.html")
    if not os.path.exists(built):
        return True
    built_at = os.path.getmtime(built)
    frontend = os.path.join(bundle_dir(), "frontend")
    for name in _FRONTEND_SOURCES:
        source = os.path.join(frontend, name)
        if os.path.exists(source) and _newest_mtime(source) > built_at:
            return True
    return False
