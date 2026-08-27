@echo off
REM Run from source on Windows. Needs Python 3.9+ and Node 18+.
REM If you would rather not install those, download the ready-made app -
REM see the README.
REM
REM The interface is rebuilt by the app itself whenever it is older than the
REM code it comes from, so this stays out of that decision: checking only for
REM a missing folder meant a stale build was served silently after every pull.
cd /d "%~dp0"

if not exist ".venv" (
  echo Setting up Python ^(first run only^)...
  python -m venv .venv || goto :fail
  ".venv\Scripts\python" -m pip install --quiet --upgrade pip
)
".venv\Scripts\pip" install --quiet -r backend\requirements.txt || goto :fail

".venv\Scripts\python" backend\desktop.py %*
goto :eof

:fail
echo.
echo Something went wrong. Check that Python 3.9+ and Node 18+ are installed
echo and on your PATH, then run this again.
pause
