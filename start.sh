#!/usr/bin/env sh
# Run from source on macOS or Linux. Needs Python 3.9+ and Node 18+.
# If you would rather not install those, download the ready-made app --
# see the README.
#
# The interface is rebuilt by the app itself whenever it is older than the
# code it comes from, so this stays out of that decision: checking only for
# a missing folder meant a stale build was served silently after every pull.
set -e
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  echo "Setting up Python (first run only)..."
  python3 -m venv .venv
  .venv/bin/pip install --quiet --upgrade pip
fi
.venv/bin/pip install --quiet -r backend/requirements.txt

exec .venv/bin/python backend/desktop.py "$@"
