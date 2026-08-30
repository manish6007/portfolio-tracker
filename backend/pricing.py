"""Price feeds: AMFI mutual-fund NAVs, stock prices, NPS NAVs.

All fetchers fail soft (return {} / None) so the app keeps working offline
with last-known or manual prices.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from urllib.parse import quote, urlparse

import requests

import config
import netlog

AMFI_NAV_URL = "https://www.amfiindia.com/spages/NAVAll.txt"

# Both feeds are public pages meant for browsers, and both reject the default
# `python-requests/2.x` agent -- AMFI's WAF with a 403, Yahoo's chart API with
# a 429. Nothing here identifies the user or the machine; it is the minimum
# that makes a plain GET behave like the browser tab it stands in for.
BROWSER_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/124.0 Safari/537.36"),
    "Accept": "text/html,application/json,text/plain,*/*",
    "Accept-Language": "en-IN,en;q=0.9",
}


class Offline(Exception):
    """Raised instead of opening a connection while offline mode is on."""


def explain(exc):
    """Why a fetch failed, in words that suggest what to do about it.

    "Check your internet connection" is not an answer when the connection is
    fine and a TLS interception proxy is the problem. requests wraps very
    different causes in similar-looking exceptions, so they are separated
    here once and reused by the refresh, the log and the connection test.
    """
    if isinstance(exc, requests.exceptions.SSLError):
        return ("the secure connection could not be verified. Usually a "
                "company network, antivirus or VPN inspecting traffic, or "
                "an out-of-date certificate store (pip install -U certifi).")
    if isinstance(exc, requests.exceptions.ProxyError):
        return ("a proxy refused the connection. If you use one, set "
                "HTTPS_PROXY before starting the app.")
    if isinstance(exc, requests.exceptions.ConnectTimeout):
        return "the server did not answer in time. It may be down, or blocked."
    if isinstance(exc, requests.exceptions.ReadTimeout):
        return "the server accepted the connection then stalled."
    if isinstance(exc, requests.exceptions.ConnectionError):
        detail = str(exc).lower()
        if "name or service not known" in detail or "nodename nor" in detail \
                or "getaddrinfo" in detail:
            return ("the address could not be resolved -- DNS is not "
                    "answering, or the machine is offline.")
        return ("the connection was refused or dropped. A firewall, VPN or "
                "network filter is the usual cause.")
    if isinstance(exc, requests.exceptions.HTTPError):
        code = getattr(exc.response, "status_code", 0)
        if code in (401, 403):
            return ("the server refused the request (HTTP %d). It is "
                    "rejecting this app rather than failing." % code)
        if code == 429:
            return ("the server asked us to slow down (HTTP 429). Wait a few "
                    "minutes and try again.")
        return "the server answered HTTP %d." % code
    return str(exc)


def _get(url, timeout, head_bytes=0):
    """Fetch a URL, but only one the app is allowed to contact, and log it.

    Every outbound call goes through here so the log in the app is the whole
    truth rather than a sample, and so offline mode is a fact about the code
    rather than a promise in the UI.
    """
    host = urlparse(url).hostname or ""
    purpose = netlog.purpose_for(host)
    if not purpose:
        netlog.record(host, "not on the allowed list", "refused")
        raise Offline("This app does not contact %s." % host)
    if config.offline():
        netlog.record(host, purpose, "blocked", "offline mode is on")
        raise Offline("Offline mode is on, so nothing was fetched.")
    headers = dict(BROWSER_HEADERS)
    if head_bytes:
        headers["Range"] = "bytes=0-%d" % (head_bytes - 1)
    try:
        resp = requests.get(url, timeout=timeout, headers=headers)
        resp.raise_for_status()
    except requests.RequestException as exc:
        netlog.record(host, purpose, "failed", explain(exc))
        raise
    netlog.record(host, purpose, "ok", "%d bytes" % len(resp.content))
    return resp


def check_hosts(timeout=10):
    """Try each allowed host once and report exactly what happened.

    Written because "AMFI could not be reached -- check your internet
    connection" is useless when the connection is fine. One row per host,
    with the real reason.
    """
    # The NAV file is over a megabyte, so the first few kilobytes prove
    # reachability without pulling it twice. The chart response is small and
    # has to be read in full, because "bytes arrived" is not the question --
    # a probe that stops at reachable reported success while every price
    # lookup was coming back empty, which is the failure people actually hit.
    probes = [(AMFI_NAV_URL, "Mutual-fund NAVs (AMFI)", 4096, False),
              (CHART_URL.format(symbol="RELIANCE.NS"),
               "Stock prices (Yahoo)", 0, True)]
    out = []
    for url, label, head, is_chart in probes:
        host = urlparse(url).hostname
        row = {"host": host, "label": label}
        try:
            resp = _get(url, timeout, head_bytes=head)
            if not is_chart:
                row.update(ok=True,
                           detail="%d bytes received" % len(resp.content))
            else:
                try:
                    payload = resp.json()
                except ValueError:
                    payload = {}
                price, when = parse_chart(payload)
                if price:
                    row.update(ok=True, detail="RELIANCE.NS priced at %s (%s)"
                               % (round(price, 2), when))
                else:
                    # Reachable, and still no use. Naming that is the whole
                    # point: it sends people to the right problem.
                    row.update(ok=False, detail=(
                        "the host answered but returned no price%s -- the "
                        "feed changed or is refusing us, so no stock price "
                        "can be updated until it recovers"
                        % (": " + chart_error(payload)
                           if chart_error(payload) else "")))
        except Offline as exc:
            row.update(ok=False, detail=str(exc))
        except requests.RequestException as exc:
            row.update(ok=False, detail=explain(exc))
        out.append(row)
    return out


# AMFI writes English month abbreviations. datetime.strptime("%b") reads
# them through the machine's LC_TIME, so on a system set to any other
# language every single row fails to parse -- the file downloads perfectly
# and yields nothing. Parsed by hand so the answer does not depend on which
# country the laptop is configured for.
MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun",
     "jul", "aug", "sep", "oct", "nov", "dec"])}


def parse_nav_date(token):
    """'26-Aug-2026' -> date(2026, 8, 26). None when it is not that."""
    parts = (token or "").split("-")
    if len(parts) != 3:
        return None
    day, mon, year = parts
    month = MONTHS.get(mon.strip().lower()[:3])
    if not month:
        return None
    try:
        return date(int(year), month, int(day))
    except ValueError:
        return None


MAX_TRAILING_NUMBERS = 3        # NAV, and at most repurchase + sale prices


def _is_number(token):
    try:
        float(token)
    except ValueError:
        return False
    return True


def parse_amfi_dump(text):
    """Parse AMFI's NAVAll.txt.

    Semicolon-separated, and *not* a fixed six columns: the scheme name is
    itself split into name, plan and option, so a real row reads

      119551;INF209KA12Z1;INF209KA13Z9;Aditya Birla ... Fund;Direct Plan;\
      IDCW-Re-investment;100.1;26-Aug-2026

    Reading the NAV from column 4 got "Direct Plan" on every one of 14,000
    rows -- the file downloaded perfectly and produced nothing. So the fields
    that can be recognised by shape are found first and the rest is the name:
    the date is last, the NAV is the first of the run of numbers before it
    (AMFI orders NAV, then repurchase and sale price where those appear), and
    everything between the ISINs and that run is the scheme's name. A layout
    that grows another column cannot break this the way it just did.

    Both ISIN columns are kept so a CAS -- which identifies funds by ISIN and
    never by AMFI code -- can be resolved to the code that NAV refresh needs.
    """
    navs, by_isin = {}, {}
    for line in text.splitlines():
        parts = [p.strip() for p in line.split(";")]
        if len(parts) < 6 or not parts[0].isdigit():
            continue
        if parse_nav_date(parts[-1]) is None:
            continue
        # Walk back over the trailing numbers; the leftmost of them is the NAV.
        first_number = len(parts) - 1
        while (first_number > 4 and _is_number(parts[first_number - 1])
               and len(parts) - first_number <= MAX_TRAILING_NUMBERS):
            first_number -= 1
        if first_number >= len(parts) - 1 or not _is_number(parts[first_number]):
            continue                       # no NAV between the name and date
        nav_f = float(parts[first_number])
        name = " - ".join(p for p in parts[3:first_number] if p)
        if not name:
            continue
        code, isin1, isin2 = parts[0], parts[1], parts[2]
        navs[code] = {"name": name, "nav": nav_f,
                      "date": parse_nav_date(parts[-1])}
        for isin in (isin1, isin2):
            if isin and isin.upper() not in ("N.A.", "NA", "-"):
                by_isin[isin.upper()] = code
    return navs, by_isin


def diagnose_dump(text):
    """Why a downloaded NAV file yielded no rows.

    Reached only when the download worked and the parse produced nothing --
    a case that used to be reported as "AMFI could not be reached", sending
    people to check a connection that had just delivered a megabyte.
    """
    lines = (text or "").splitlines()
    if not lines:
        return "the file came back empty."
    candidates = [ln for ln in lines
                  if ln.split(";")[0].strip().isdigit() and ln.count(";") >= 5]
    if not candidates:
        head = " / ".join(ln.strip() for ln in lines[:3] if ln.strip())[:200]
        return ("nothing in the file looked like a NAV row (%d lines). It "
                "starts: %s" % (len(lines), head or "(blank)"))
    # The whole row, not the fields this parser guessed at: when the column
    # layout is what changed, naming the columns describes the bug rather
    # than the file.
    return ("%d rows looked like NAV rows but none could be read. The first "
            "one is: %s" % (len(candidates), candidates[0].strip()[:300]))


# What happened on the last AMFI fetch: "ok", "unreachable" or "unreadable".
# Downloading a megabyte and understanding none of it is a different problem
# from not reaching the server, and needs a different thing done about it.
AMFI_OK, AMFI_UNREACHABLE, AMFI_UNREADABLE = "ok", "unreachable", "unreadable"


def fetch_amfi(timeout=30):
    """Download today's dump once and return both views of it.

    ({scheme_code: ...}, {ISIN: scheme_code}, status). The file is over a
    megabyte, so a caller that wants both -- a price refresh that also has to
    resolve ISINs -- should not fetch it twice.
    """
    try:
        resp = _get(AMFI_NAV_URL, timeout)
    except (requests.RequestException, Offline):
        return {}, {}, AMFI_UNREACHABLE
    navs, by_isin = parse_amfi_dump(resp.text)
    if not navs:
        why = diagnose_dump(resp.text)
        netlog.record(urlparse(AMFI_NAV_URL).hostname,
                      netlog.purpose_for(urlparse(AMFI_NAV_URL).hostname),
                      "unreadable", why)
        return {}, {}, AMFI_UNREADABLE
    return navs, by_isin, AMFI_OK


def fetch_amfi_navs(timeout=30):
    """{scheme_code: {"name": str, "nav": float, "date": date}}."""
    return fetch_amfi(timeout)[0]


def fetch_amfi_isin_index(timeout=30):
    """{ISIN: AMFI scheme code}, so CAS holdings can price themselves."""
    return fetch_amfi(timeout)[1]


def search_amfi(navs, query, limit=20):
    q = query.lower()
    hits = [(code, info) for code, info in navs.items()
            if q in info["name"].lower()]
    return hits[:limit]


CHART_URL = ("https://query1.finance.yahoo.com/v8/finance/chart/"
             "{symbol}?range=5d&interval=1d")


def parse_chart(payload):
    """Latest close and its date from Yahoo's chart JSON.

    Returns (price, date) or (None, None). Yahoo pads the series with nulls
    for holidays, so the last non-null close is taken rather than the last
    element.
    """
    try:
        result = payload["chart"]["result"][0]
        stamps = result["timestamp"]
        closes = result["indicators"]["quote"][0]["close"]
    except (KeyError, IndexError, TypeError):
        return None, None
    for ts, close in zip(reversed(stamps), reversed(closes)):
        if close is not None:
            return float(close), datetime.fromtimestamp(ts).date()
    return None, None


def chart_error(payload):
    """Yahoo's own words for why a chart request produced nothing."""
    try:
        err = (payload or {}).get("chart", {}).get("error") or {}
        return str(err.get("description") or err.get("code") or "")[:120]
    except AttributeError:
        return ""


def fetch_stock_price(symbol, timeout=15):
    """Latest close for an NSE/BSE ticker, straight from Yahoo's chart API.

    This used to go through yfinance, which opened its own connections to
    whatever hosts it liked -- so the allowlist was advisory for the one feed
    that was a third-party library, and the log named a host that may not
    have been the one contacted. One small JSON parse buys back an enforced
    allowlist, an honest log, and one less dependency that breaks on Yahoo's
    schedule rather than ours.

    Pass the plain symbol (e.g. RELIANCE); .NS is appended if no suffix.
    Returns (price, date) or (None, None).
    """
    ticker = symbol if "." in symbol else symbol + ".NS"
    try:
        resp = _get(CHART_URL.format(symbol=quote(ticker, safe="")), timeout)
    except (requests.RequestException, Offline):
        return None, None
    try:
        payload = resp.json()
    except ValueError:
        netlog.record(urlparse(CHART_URL).hostname,
                      netlog.purpose_for(urlparse(CHART_URL).hostname),
                      "unreadable", "%s: the reply was not JSON" % ticker)
        return None, None
    price, when = parse_chart(payload)
    if price is None:
        # A 200 with no usable price is not the same as no answer, and the
        # difference decides what the user should do about it. _get logged
        # the request as ok, so this says what the ok was worth.
        netlog.record(urlparse(CHART_URL).hostname,
                      netlog.purpose_for(urlparse(CHART_URL).hostname),
                      "empty", "%s: no price in the reply%s" % (
                          ticker,
                          " (" + chart_error(payload) + ")"
                          if chart_error(payload) else ""))
    return price, when


def fetch_stock_prices(symbols, timeout=15, workers=5):
    """Prices for several tickers at once.

    One holding per round trip made a thirty-stock refresh a thirty-request
    wait; symbols are de-duplicated first, because the same stock held by two
    people is still one price.
    """
    unique = []
    for sym in symbols:
        sym = (sym or "").strip()
        if sym and sym not in unique:
            unique.append(sym)
    if not unique:
        return {}
    if config.offline():                 # no threads, no sockets, one log line
        return {sym: fetch_stock_price(sym, timeout) for sym in unique[:1]}
    with ThreadPoolExecutor(max_workers=min(workers, len(unique))) as pool:
        results = pool.map(lambda s: fetch_stock_price(s, timeout), unique)
        return dict(zip(unique, results))
