"""How much of your equity sits in large, mid and small companies.

Asset allocation says how much is in equity at all. It does not say whether
that equity is Nifty-50 steady or small-cap volatile, and those are different
portfolios with the same asset-class chart.

Two sources feed this:

* **Mutual funds** classify themselves. SEBI's categories carry mandates --
  a Large Cap fund must hold at least 80% in the top 100 companies, a Small
  Cap fund at least 65% outside the top 250 -- and AMFI's scheme names carry
  the category. So a fund's mix is read from its own name.
* **Direct shares** do not. Which bucket a company sits in comes from AMFI's
  half-yearly classification list, which this app has no honest way to fetch,
  so shares are tagged by the user and anything untagged is reported as
  unclassified rather than guessed into a bucket.

Every split below is an assumption, and stated as one. The mandate fixes the
floor; the remainder is placed the way the category is usually run. They are
here to be argued with, which is why the reason travels with the number.
"""
import re

BUCKETS = ("large", "mid", "small", "international")
LABELS = {"large": "Large cap", "mid": "Mid cap", "small": "Small cap",
          "international": "International"}

# category -> (split, why). Splits are percentages of the fund's equity.
CATEGORY_SPLITS = {
    "large_cap": ({"large": 90, "mid": 10}, "SEBI: at least 80% in the top 100 companies"),
    "mid_cap": ({"large": 10, "mid": 80, "small": 10}, "SEBI: at least 65% in companies 101-250"),
    "small_cap": ({"large": 5, "mid": 15, "small": 80}, "SEBI: at least 65% beyond company 250"),
    "large_and_mid": ({"large": 45, "mid": 45, "small": 10}, "SEBI: at least 35% large and 35% mid"),
    "multi_cap": ({"large": 40, "mid": 30, "small": 30}, "SEBI: at least 25% in each of the three"),
    "flexi_cap": ({"large": 70, "mid": 20, "small": 10}, "unconstrained by mandate; typically large-tilted"),
    "elss": ({"large": 70, "mid": 20, "small": 10}, "unconstrained by mandate; typically large-tilted"),
    "focused": ({"large": 65, "mid": 25, "small": 10}, "unconstrained, concentrated; typically large-tilted"),
    "value": ({"large": 65, "mid": 25, "small": 10}, "unconstrained; typically large-tilted"),
    "sectoral": ({"large": 60, "mid": 30, "small": 10}, "one sector, spread across sizes"),
    "hybrid_equity": ({"large": 75, "mid": 20, "small": 5},
                      "the equity sleeve of a hybrid fund, usually run large-tilted"),
    "index_large": ({"large": 100}, "tracks an index of the top 100 companies"),
    "index_mid": ({"mid": 100}, "tracks a midcap index"),
    "index_small": ({"small": 100}, "tracks a smallcap index"),
    "international": ({"international": 100}, "invests outside India, so Indian caps do not apply"),
}

# Longest and most specific first: "Nifty Next 50" must not be read as
# "Nifty 50", and "Large & Mid Cap" must not be read as "Large Cap".
CATEGORY_PATTERNS = [
    ("international", r"nasdaq|s&p\s*500|global|international|overseas|"
                      r"\bus\b|greater china|emerging market|world|europe|japan"),
    ("index_small", r"(smallcap|small cap).{0,12}(index|etf|50|100|250)|"
                    r"(index|etf).{0,12}(smallcap|small cap)"),
    ("index_mid", r"(midcap|mid cap).{0,12}(index|etf|50|100|150)|"
                  r"(index|etf).{0,12}(midcap|mid cap)"),
    ("index_large", r"nifty next 50|nifty 50|nifty100|nifty 100|sensex|"
                    r"bse 30|nifty bank|index fund|index etf"),
    ("large_and_mid", r"large\s*(&|and)\s*mid"),
    ("large_cap", r"large\s*cap|bluechip|blue chip|top 100"),
    ("mid_cap", r"mid\s*cap|midcap"),
    ("small_cap", r"small\s*cap|smallcap"),
    ("multi_cap", r"multi\s*cap|multicap"),
    ("flexi_cap", r"flexi\s*cap|flexicap"),
    ("hybrid_equity", r"balanced advantage|dynamic asset allocation|"
                      r"aggressive hybrid|equity savings|multi[- ]asset|"
                      r"balanced fund|asset allocator|equity\s*(&|and)\s*debt"),
    ("elss", r"elss|tax saver|tax advantage|long term equity"),
    ("focused", r"focused|focussed"),
    ("value", r"value fund|contra|dividend yield"),
    ("sectoral", r"banking|financial services|pharma|healthcare|technology|"
                 r"digital|infrastructure|consumption|psu|energy|manufacturing|"
                 r"transport|defence|realty|metal|fmcg"),
]
CATEGORY_LABELS = {
    "large_cap": "Large cap", "mid_cap": "Mid cap", "small_cap": "Small cap",
    "large_and_mid": "Large & mid cap", "multi_cap": "Multi cap",
    "flexi_cap": "Flexi cap", "elss": "ELSS", "focused": "Focused",
    "value": "Value / contra", "sectoral": "Sectoral / thematic",
    "index_large": "Large-cap index", "index_mid": "Midcap index",
    "index_small": "Smallcap index", "international": "International",
    "hybrid_equity": "Hybrid (equity sleeve)",
}


def classify_scheme(name):
    """SEBI-ish category from a fund's name, or "" when it does not say."""
    text = re.sub(r"\s+", " ", (name or "")).lower()
    for category, pattern in CATEGORY_PATTERNS:
        if re.search(pattern, text):
            return category
    return ""


def _normalise(split):
    total = sum(split.values())
    if not total:
        return {}
    return {k: v / total for k, v in split.items() if v}


def cap_split(h):
    """How this holding's *equity* divides across caps, as fractions.

    Returns ({bucket: fraction}, source). An empty dict means the holding
    could not be classified -- reported, never guessed into a bucket.
    """
    meta = h.get("meta") or {}
    raw = meta.get("cap_split")
    if isinstance(raw, dict) and raw:
        chosen = {k: float(v) for k, v in raw.items()
                  if k in BUCKETS and float(v or 0) > 0}
        if chosen:
            return _normalise(chosen), "set by you"
    single = (meta.get("cap") or "").strip().lower()
    if single in BUCKETS:
        return {single: 1.0}, "set by you"
    if h.get("asset_class") == "mutual_fund":
        category = classify_scheme(h.get("name"))
        if category:
            split, why = CATEGORY_SPLITS[category]
            return _normalise(dict(split)), "%s — %s" % (
                CATEGORY_LABELS[category], why)
    return {}, ""


def describe(split, source):
    """A short label for a cap split, for a table cell.

    "Mid cap" when it is one bucket, "70/20/10 large/mid/small" when it is a
    mandate spread, "" when nothing could be read -- which is the case that
    needs to be visible, since it is the only one anyone has to act on.
    """
    if not split:
        return ""
    if len(split) == 1:
        only = next(iter(split))
        return LABELS[only]
    parts = [(b, split[b]) for b in BUCKETS if split.get(b)]
    return "%s %s" % (
        "/".join(str(int(round(f * 100))) for _, f in parts),
        "/".join(LABELS[b].split()[0].lower() for b, _ in parts))


def cap_mix(holdings, equity_share, as_of=None, value_of=None):
    """Cap breakdown of the equity inside a portfolio.

    equity_share(h) -> the rupees of this holding that are equity, so a
    hybrid fund contributes only its equity sleeve and a debt fund none of
    itself. Returns totals per bucket plus what could not be classified, and
    a per-holding trail so the chart can say why each fund landed where it
    did.
    """
    totals = {b: 0.0 for b in BUCKETS}
    unclassified, rows = 0.0, []
    for h in holdings:
        equity = equity_share(h)
        if equity <= 0:
            continue
        split, why = cap_split(h)
        if not split:
            unclassified += equity
            rows.append({"name": h.get("name"), "equity": round(equity, 2),
                         "split": {}, "why": "not classified"})
            continue
        for bucket, fraction in split.items():
            totals[bucket] += equity * fraction
        rows.append({"name": h.get("name"), "equity": round(equity, 2),
                     "split": {k: round(v, 4) for k, v in split.items()},
                     "why": why})
    classified = sum(totals.values())
    total = classified + unclassified
    return {
        "totals": {k: round(v, 2) for k, v in totals.items()},
        "unclassified": round(unclassified, 2),
        "total_equity": round(total, 2),
        "pct": {k: (round(v / classified * 100, 1) if classified else 0.0)
                for k, v in totals.items()},
        "unclassified_pct": (round(unclassified / total * 100, 1)
                             if total else 0.0),
        "holdings": sorted(rows, key=lambda r: -r["equity"]),
    }
