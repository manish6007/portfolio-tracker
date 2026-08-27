"""The thing someone double-clicks.

A person who wants to track their money should not have to meet Python,
npm, or a terminal. This starts the server, opens the browser at it, and
stays out of the way -- and says, in words, where their data is being kept,
because that is the first question anyone sensible asks.

Closing the window stops the app. Nothing keeps running in the background.
"""
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import webbrowser

import paths

DEFAULT_PORT = 8765          # not 8000: too many other things want 8000
HOST = "127.0.0.1"           # never 0.0.0.0 -- this serves the machine it is on


def free_port(preferred=DEFAULT_PORT, tries=20):
    """The first port nothing else is using, starting at the preferred one.

    A second copy of the app, or any other server on that port, should not
    produce a stack trace on a stranger's screen.
    """
    for offset in range(tries):
        port = preferred + offset
        with socket.socket() as probe:
            # Bind *and* listen, with no SO_REUSEADDR: the probe has to be
            # exactly as strict as the real server, or it reports a port
            # free and uvicorn then fails with "address already in use".
            try:
                probe.bind((HOST, port))
                probe.listen(1)
                return port
            except OSError:
                continue
    raise SystemExit("Could not find a free port between %d and %d."
                     % (preferred, preferred + tries - 1))


def wait_until_serving(port, timeout=30.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        with socket.socket() as probe:
            if probe.connect_ex((HOST, port)) == 0:
                return True
        time.sleep(0.1)
    return False


def built_at():
    """When the interface on disk was built, in words.

    Printed because "it rebuilt" and "you are looking at the rebuild" are
    different claims, and only the second one matters.
    """
    index = os.path.join(paths.frontend_dist(), "index.html")
    try:
        when = time.localtime(os.path.getmtime(index))
    except OSError:
        return "not built"
    return time.strftime("%d %b %Y, %H:%M", when)


def announce(port, data_dir):
    """Say it, and flush it.

    A console app that buffers its output shows a stranger a blank window
    while the thing they need -- the address to open -- sits unwritten.
    """
    print()
    print("  Portfolio Tracker is running.")
    print()
    print("  Open it at   http://%s:%d" % (HOST, port))
    print("  Your data is %s" % data_dir)
    print("  Interface built %s" % built_at())
    print()
    print("  Nothing leaves this machine except mutual-fund and share prices.")
    print("  Back up the folder above and you have backed up everything.")
    print()
    print("  Close this window to stop the app.")
    print("  If a page looks out of date, press Ctrl+Shift+R in the browser.")
    print(flush=True)


def npm():
    """The npm Windows can actually run, or "" when Node is not installed.

    A Node install puts two files on the PATH: `npm`, which is a Unix shell
    script, and `npm.cmd`, which is the Windows one. Since Python 3.12
    shutil.which() returns an extensionless match when one exists, so
    which("npm") hands back the shell script and CreateProcess refuses it
    with "%1 is not a valid Win32 application". The extension has to be
    asked for by name.
    """
    names = ("npm.cmd", "npm.exe", "npm") if os.name == "nt" else ("npm",)
    for name in names:
        found = shutil.which(name)
        if found:
            return found
    return ""


def run(tool, args, cwd):
    """Run a build step, turning a failure into a sentence.

    A traceback is not a message. Whatever goes wrong here -- npm missing,
    the wrong kind of npm, a build error -- the person reading it wants to
    know what to do, not which line of subprocess.py raised.
    """
    try:
        return subprocess.call([tool] + args, cwd=cwd) == 0
    except OSError as exc:
        print("  Could not run %s %s: %s" % (os.path.basename(tool),
                                             " ".join(args), exc), flush=True)
        return False


def build_frontend():
    """Rebuild the interface when it is older than the code it comes from.

    Doing this only when the folder is missing was the bug: after a pull the
    folder is still there, so months-old HTML gets served against today's
    API and whole pages are simply absent. It is checked every start now,
    and a rebuild takes a few seconds.
    """
    def usable():
        return os.path.isfile(os.path.join(paths.frontend_dist(), "index.html"))

    if paths.is_frozen() or not paths.frontend_is_stale():
        return True
    frontend = os.path.join(paths.bundle_dir(), "frontend")
    tool = npm()
    if not tool:
        print("  The interface needs rebuilding but Node was not found.",
              flush=True)
        print("  Install Node 18+ and run this again, or download the "
              "ready-made app.", flush=True)
        return usable()
    if not os.path.isdir(os.path.join(frontend, "node_modules")):
        print("  Installing the interface's dependencies (first run only)...",
              flush=True)
        if not run(tool, ["install"], frontend):
            return usable()
    print("  Building the interface (a few seconds)...", flush=True)
    if not run(tool, ["run", "build"], frontend):
        print("  The app will start with whatever was built last, which may "
              "be out of date. Some pages may be missing until this "
              "succeeds.", flush=True)
    return usable()


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    port = free_port(int(os.environ.get("PORTFOLIO_PORT") or DEFAULT_PORT))

    if not build_frontend():
        raise SystemExit(
            "\n  The interface could not be built, and there is no earlier "
            "build to fall back on.\n"
            "  Install Node 18+ (nodejs.org) and run this again, or download "
            "the ready-made app.\n")

    import config
    os.makedirs(config.data_dir(), exist_ok=True)
    announce(port, config.data_dir())

    if "--no-browser" not in argv:
        threading.Thread(
            target=lambda: (wait_until_serving(port)
                            and webbrowser.open("http://%s:%d" % (HOST, port))),
            daemon=True).start()

    import uvicorn
    from main import app
    try:
        uvicorn.run(app, host=HOST, port=port, log_level="warning")
    except KeyboardInterrupt:            # Ctrl-C is a normal way to stop
        pass
    print("Stopped. Your data is still in %s" % config.data_dir(),
          flush=True)


if __name__ == "__main__":
    main()
