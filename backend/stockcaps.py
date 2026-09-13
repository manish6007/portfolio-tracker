"""Which size bucket each listed company sits in, from AMFI's own list.

capmix reads a mutual fund's bucket from its name, because SEBI makes the
name mean something. A share's name means nothing: SEBI defines the buckets
by rank -- the top 100 companies are large cap, 101-250 mid, the rest small
-- and AMFI publishes the ranked list every half year as an Excel file, per
SEBI circular SEBI/HO/IMD/DF3/CIR/P/2017/114. That file is fetched here,
reduced to symbol/ISIN -> bucket, and cached in the data folder, so shares
classify themselves and stop piling up as "unclassified".

Three things stay true:

* The user's own tag wins. This list is the default, not the authority on a
  portfolio -- capmix checks the tag first and never asks this module.
* The fetch happens only inside a price refresh. The app does not phone
  home on its own, and with no cache and no fetch a share simply stays
  unclassified, which is exactly what the app did before this module.
* The list is half-yearly, so the cache is kept until a newer period can
  exist, and a failed fetch keeps the old list rather than forgetting it.
"""
import json
import os
import re
from datetime import date, datetime
from io import BytesIO

import openpyxl
import requests

import config
import pricing

# AMFI moved the current file to portal.amfiindia.com when it rebuilt its
# site in 2025; the older half-years stayed behind on www, under two naming
# schemes. All three are tried, newest home first.
_URLS = (
    "https://portal.amfiindia.com/spages/AverageMarketCapitalization%s.xlsx",
    "https://www.amfiindia.com/Themes/Theme1/downloads/"
    "AverageMarketCapitalization%s.xlsx",
    "https://www.amfiindia.com/Themes/Theme1/downloads/"
    "AverageMarketCapitalizationoflistedcompaniesduringthesixmonthsended"
    "%s.xlsx",
)

# Hand-written month names for the same reason pricing parses AMFI dates by
# hand: strftime("%b") answers in the machine's language, and these URLs are
# in English no matter where the machine is.
_STAMPS = {6: "30Jun%d", 12: "31Dec%d"}
_PERIODS = {6: "Jan–Jun %d", 12: "Jul–Dec %d"}

_BUCKET_FOR = {"large": "large", "mid": "mid", "small": "small"}

# Dropped before two company names are compared. A holding typed as "Bajaj
# Finance" and a list entry reading "Bajaj Finance Limited" are the same
# company, and nothing below distinguishes two different ones.
_NOISE = re.compile(
    r"\b(ltd|limited|the|and|company|co|corp|corporation|inc|plc|"
    r"industries|india|indian)\b")


def normalise_name(name):
    """A company name reduced to what is worth comparing, or "".

    Only ever used to match a name against AMFI's own spelling of it. Names
    that reduce to nothing -- or to something a second company also reduces
    to -- are dropped rather than matched, because a wrong bucket here is
    worse than an empty one.
    """
    text = re.sub(r"[^a-z0-9 ]", " ", (name or "").lower())
    text = _NOISE.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


CACHE_FILE = "stockcaps.json"

# Between period end and publication the newest file does not exist yet, and
# every refresh would burn three 404s rediscovering that. One look per day
# is plenty for a list that changes twice a year.
RECHECK_HOURS = 24


def period_ends(today=None, count=2):
    """The most recent half-year ends, newest first.

    AMFI cuts the list at 30 June and 31 December. The newest file may not
    be published yet in the days right after a cut, which is why more than
    one period is returned -- the fetch falls back rather than failing.
    """
    today = today or date.today()
    ends = []
    year = today.year
    while len(ends) < count:
        for end in (date(year, 12, 31), date(year, 6, 30)):
            if end <= today and len(ends) < count:
                ends.append(end)
        year -= 1
    return ends


def period_label(end):
    """"Jan-Jun 2026" for the half-year ending on `end`."""
    return _PERIODS[end.month] % end.year


def source_label(end):
    """What the Portfolio page says when this list classified a share."""
    return "AMFI's list, %s" % period_label(end)


def _columns(rows):
    """Which column is which, read from the header row, or None.

    Found by header text rather than position because a file that is
    hand-assembled twice a year will eventually gain a column, and a parser
    counting positions would then read market caps as tickers without a word
    of complaint. Consumes rows up to and including the header, leaving the
    caller iterating over data.
    """
    for row in rows:
        headers = [str(c or "").strip().lower() for c in row]
        if not (any(h == "isin" for h in headers)
                and any("categor" in h for h in headers)):
            continue
        cols = {"isin": None, "cat": None, "name": None, "symbols": [],
                "nse_symbols": []}
        for i, h in enumerate(headers):
            if h == "isin":
                cols["isin"] = i
            elif "categor" in h:
                cols["cat"] = i
            elif "symbol" in h:
                cols["symbols"].append(i)
                # A holding is keyed by its NSE ticker, so that column is
                # preferred over the BSE numeric code when both are present.
                if "nse" in h:
                    cols["nse_symbols"].append(i)
            elif "name" in h and cols["name"] is None:
                cols["name"] = i
        return cols
    return None


def _cell(row, col):
    return str(row[col] or "").strip() if col is not None and len(row) > col \
        else ""


def _read_row(row, cols, by_symbol, by_isin, names):
    """Index one company, if the row names a bucket at all."""
    cat = _cell(row, cols["cat"]).lower()
    bucket = next((b for word, b in _BUCKET_FOR.items()
                   if cat.startswith(word)), None)
    if not bucket:
        return
    isin = _cell(row, cols["isin"]).upper()
    if re.fullmatch(r"[A-Z0-9]{12}", isin):
        by_isin[isin] = bucket
    # Every exchange's symbol column is indexed: the same company answers to
    # its BSE and NSE names, and a holding may carry either.
    for col in cols["symbols"]:
        sym = _cell(row, col).upper()
        if sym and sym != "-":
            by_symbol[sym] = bucket
    key = normalise_name(_cell(row, cols["name"]))
    if key:
        # Two companies reducing to one key make that key useless; kept as
        # None so the second poisons the first rather than overwriting it.
        names[key] = bucket if key not in names or names[key] == bucket \
            else None


def parse_workbook(blob):
    """(by_symbol, by_isin, by_name) out of AMFI's spreadsheet.

    Company names are indexed alongside the tickers, for holdings that were
    typed in as names -- but only where the reduced name belongs to exactly
    one company. An ambiguous one is dropped from the index entirely.
    """
    wb = openpyxl.load_workbook(BytesIO(blob), read_only=True, data_only=True)
    by_symbol, by_isin, names, tickers = {}, {}, {}, {}
    for ws in wb.worksheets:
        rows = ws.iter_rows(values_only=True)
        cols = _columns(rows)
        if not cols:
            continue
        for row in rows:
            _read_row(row, cols, by_symbol, by_isin, names)
            _read_ticker(row, cols, tickers)
        if by_symbol or by_isin:
            break
    wb.close()
    return (by_symbol, by_isin, {k: v for k, v in names.items() if v},
            tickers)


def _read_ticker(row, cols, tickers):
    """Remember what a company trades as, keyed by its ISIN.

    A broker tradebook may name a company and give its ISIN without ever
    printing the ticker, while the portfolio is keyed by ticker. This is the
    only public list that carries both, and it is already downloaded for the
    company-size classification.
    """
    isin = _cell(row, cols["isin"]).upper()
    if not re.fullmatch(r"[A-Z0-9]{12}", isin):
        return
    for col in cols["nse_symbols"] or cols["symbols"]:
        sym = _cell(row, col).upper()
        if sym and sym != "-":
            tickers.setdefault(isin, sym)
            return


def fetch(timeout=60):
    """Download the newest list that exists, or None.

    Tries the current half-year at each known address, then the previous
    one -- the current file simply does not exist for the first days after
    a period ends. Offline mode stops the whole attempt at the first door,
    the way every other fetch in the app stops.
    """
    for end in period_ends():
        stamp = _STAMPS[end.month] % end.year
        for pattern in _URLS:
            try:
                resp = pricing._get(pattern % stamp, timeout)
            except pricing.Offline:
                return None
            except requests.RequestException:
                continue
            by_symbol, by_isin, by_name, tickers = parse_workbook(
                resp.content)
            if by_symbol or by_isin:
                return {"as_of": end.isoformat(),
                        "fetched": datetime.now().isoformat(timespec="seconds"),
                        "by_symbol": by_symbol, "by_isin": by_isin,
                        "by_name": by_name, "tickers": tickers}
    return None


# ---- the cache -----------------------------------------------------------
# Loaded once per data folder. The folder can move mid-session (the Privacy
# page allows it), so the cache remembers where it came from.
_cache = {"dir": None, "data": None}


def _path():
    return os.path.join(config.data_dir(), CACHE_FILE)


def load():
    """The cached list, or None. Never touches the network."""
    if _cache["dir"] != config.data_dir():
        _cache["dir"], _cache["data"] = config.data_dir(), None
        try:
            with open(_path()) as fh:
                data = json.load(fh)
            if isinstance(data, dict) and data.get("by_symbol") is not None:
                _cache["data"] = data
        except (OSError, ValueError):
            pass
    return _cache["data"]


def save(data):
    tmp = _path() + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(data, fh)
    os.replace(tmp, _path())
    _cache["dir"], _cache["data"] = config.data_dir(), data


def forget():
    """Drop the in-memory copy -- used by tests and after a data-dir move."""
    _cache["dir"] = _cache["data"] = None


_ISIN = re.compile(r"[A-Z]{2}[A-Z0-9]{9}[0-9]")


def _exact_keys(symbol, isin, name):
    """Everything about a holding that identifies a company exactly.

    The Identifier field is whatever the user or an import put there, and in
    practice that is a ticker for some holdings and an ISIN for others, so
    it is tried as both rather than trusted to be one. The name goes in too:
    imports routinely name a holding "SHILPAMED", which is an exact ticker
    wearing the name field, not a company name to be matched loosely.
    """
    symbols, isins = [], []
    for raw in (symbol, name):
        text = (raw or "").strip().upper()
        if not text:
            continue
        if _ISIN.fullmatch(text):
            isins.append(text)
            continue
        symbols.append(text)
        if "." in text:
            # RELIANCE.NS is priced by Yahoo but listed by AMFI as RELIANCE.
            symbols.append(text.rsplit(".", 1)[0])
    code = (isin or "").strip().upper()
    if code:
        isins.insert(0, code)
    return symbols, isins


def lookup(symbol=None, isin=None, name=None):
    """(bucket, source label) for a share, or (None, "").

    Tried in order of how certain the identification is: an exact ticker or
    ISIN first, then the company name reduced to its distinctive words. Only
    that last one can be wrong about which company it found, so only that
    one says how it matched.

    A foreign share is on none of the indexes and stays unclassified, which
    is the honest answer for buckets defined over Indian ranks.
    """
    data = load()
    if not data:
        return None, ""
    symbols, isins = _exact_keys(symbol, isin, name)
    bucket, how = None, ""
    for key in symbols:
        bucket = data["by_symbol"].get(key)
        if bucket:
            break
    if not bucket:
        for key in isins:
            bucket = data["by_isin"].get(key)
            if bucket:
                break
    if not bucket:
        bucket = (data.get("by_name") or {}).get(normalise_name(name))
        if bucket:
            how = ", matched by name"
    if not bucket:
        return None, ""
    return bucket, source_label(date.fromisoformat(data["as_of"])) + how


def has_tickers():
    """Whether the cached list can answer ISIN -> ticker at all.

    A cache saved before that index existed answers "" for everything, which
    looks exactly like a company that is not listed. Worth telling apart.
    """
    data = load()
    return bool(data and data.get("tickers"))


def ticker_for(isin):
    """What a company trades as on the exchange, from its ISIN, or "".

    Used when a broker export identifies a company by ISIN and name but
    never by ticker, which is how the portfolio keys its shares.
    """
    data = load()
    code = (isin or "").strip().upper()
    if not data or not code:
        return ""
    return (data.get("tickers") or {}).get(code, "")


def refresh(timeout=60):
    """Bring the cache up to date, gently. Called from a price refresh.

    Returns {"status", "as_of"} for the refresh response. "fresh" means the
    cache already holds the newest possible period and nothing was fetched;
    "updated" means a fetch improved it; "kept" means the fetch failed but
    an older list is still standing; "unavailable" means there is nothing
    at all. A recent failed attempt is not retried on every refresh --
    the file changes twice a year, not twice an hour.
    """
    cached = load()
    as_of = cached["as_of"] if cached else None
    # A cache from the current half-year is normally as good as it gets --
    # unless it was written before an index this app now relies on existed.
    # "Fresh" then meant "never refetch", and every company failed to
    # resolve to a ticker for as long as the period lasted.
    # A list that carries companies but not the ISIN -> ticker index was
    # written before that index existed, and is worth refetching even inside
    # its own half-year. A stub recording a failed attempt carries neither,
    # and must still be left alone until the recheck window passes.
    has_data = bool(cached and cached.get("by_symbol"))
    outdated = has_data and not cached.get("tickers")
    current = bool(cached
                   and cached["as_of"] == period_ends()[0].isoformat())
    if current and not outdated:
        return {"status": "fresh", "as_of": as_of}
    checked = None if outdated else (cached or {}).get("checked")
    if checked:
        try:
            age = datetime.now() - datetime.fromisoformat(checked)
            if age.total_seconds() < RECHECK_HOURS * 3600:
                return {"status": "kept" if as_of else "unavailable",
                        "as_of": as_of}
        except ValueError:
            pass
    data = fetch(timeout)
    if data and (not as_of or data["as_of"] >= as_of):
        save(data)
        return {"status": "updated" if data["as_of"] != as_of else "fresh",
                "as_of": data["as_of"]}
    # Remember that we looked, so the next refresh does not re-download or
    # re-404 for a day; whatever list is standing stays as it was. With no
    # list at all this writes a stub that only carries the timestamp.
    kept = cached or {"as_of": None, "by_symbol": {}, "by_isin": {}}
    kept["checked"] = datetime.now().isoformat(timespec="seconds")
    save(kept)
    return {"status": "kept" if as_of else "unavailable", "as_of": as_of}
