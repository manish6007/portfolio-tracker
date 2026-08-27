"""Match a fund you hold to the AMFI scheme that prices it.

AMFI prices by scheme code. Nobody knows their scheme codes, and the CAS is
the only document that even hints at them (via the ISIN). So a portfolio
typed in by hand, or imported from a broker that reports names, ends up with
fourteen funds nobody can price -- and "go and look up fourteen codes" is not
a product.

The names line up well enough to match on, with one hard catch: every fund
exists four times over as Direct/Regular crossed with Growth/IDCW, and those
have genuinely different NAVs. Picking the wrong one produces a number that
looks entirely reasonable and is wrong, which is the worst outcome available.

So this module ranks candidates and says how confident it is; it never
decides. A confident, unambiguous match is offered pre-ticked, everything
else is offered for a human to choose, and the plan and option are always
shown so the choice being made is visible.
"""
import re

# Words that carry no distinguishing information: every second fund has them.
STOPWORDS = {"fund", "scheme", "plan", "option", "the", "of", "an", "a",
             "mutual", "mf", "open", "ended", "india", "indian"}

# The two axes that split one fund into four schemes with four NAVs.
PLAN_WORDS = {"direct": "direct", "regular": "regular"}
OPTION_WORDS = {
    "growth": "growth",
    "idcw": "idcw", "dividend": "idcw", "payout": "idcw",
    "reinvestment": "idcw", "recap": "idcw", "bonus": "bonus",
}

DEFAULT_PLAN = "direct"        # what a self-directed investor almost always holds
DEFAULT_OPTION = "growth"

# Below this, a suggestion is worse than no suggestion.
MIN_SCORE = 0.45
# A best match this far clear of the runner-up is unambiguous enough to
# pre-tick; anything closer is a choice the user has to make.
CLEAR_MARGIN = 0.08


def _words(text):
    return re.findall(r"[a-z0-9]+", (text or "").lower())


def facets(name):
    """(tokens, plan, option) -- the name split from what it is a variant of."""
    plan = option = ""
    tokens = []
    for word in _words(name):
        if word in PLAN_WORDS and not plan:
            plan = PLAN_WORDS[word]
            continue
        if word in OPTION_WORDS and not option:
            option = OPTION_WORDS[word]
            continue
        if word in STOPWORDS:
            continue
        tokens.append(word)
    return tokens, plan, option


def similarity(a_tokens, b_tokens):
    """F1 over token sets: rewards covering the query, punishes padding.

    Plain overlap would score "ICICI Prudential Nifty 50 Index Fund" as a
    perfect match for "ICICI Prudential Nifty 50 Index Fund - Series 3", and
    plain containment would rank the shortest name top regardless.
    """
    a, b = set(a_tokens), set(b_tokens)
    if not a or not b:
        return 0.0
    shared = len(a & b)
    if not shared:
        return 0.0
    precision, recall = shared / len(b), shared / len(a)
    return 2 * precision * recall / (precision + recall)


# A candidate whose NAV is within this of the price already recorded is
# almost certainly the same scheme; beyond the outer band it is almost
# certainly a different plan of the same fund.
PRICE_MATCH_PCT = 2.0
PRICE_MISMATCH_PCT = 15.0


def price_gap_pct(candidate_nav, known_price):
    if not known_price or not candidate_nav:
        return None
    return abs(candidate_nav - known_price) / known_price * 100.0


def rank(holding_name, navs, want_plan=DEFAULT_PLAN, want_option=DEFAULT_OPTION,
         limit=5, known_price=None):
    """Candidate schemes for one holding, best first.

    navs is AMFI's {code: {"name", "nav", "date"}}. Scoring is on the name
    alone; plan and option then break ties, because a fund whose name matches
    perfectly in the wrong plan is still the wrong scheme.

    known_price -- a NAV already recorded for the holding, from a CAS or
    typed in -- settles the plan question on evidence rather than on the
    assumption that everyone holds Direct. Direct and Regular NAVs of the
    same fund diverge by years of expense ratio, so the one that agrees with
    a price you already had is the one you actually hold.
    """
    want_tokens, name_plan, name_option = facets(holding_name)
    # A name that says "Direct" or "Growth" itself outranks the default.
    want_plan = name_plan or want_plan
    want_option = name_option or want_option
    if not want_tokens:
        return []

    scored = []
    for code, info in navs.items():
        tokens, plan, option = facets(info["name"])
        base = similarity(want_tokens, tokens)
        if base < MIN_SCORE:
            continue
        score = base
        if plan and want_plan:
            score += 0.06 if plan == want_plan else -0.10
        if option and want_option:
            score += 0.06 if option == want_option else -0.10
        gap = price_gap_pct(info["nav"], known_price)
        if gap is not None:
            if gap <= PRICE_MATCH_PCT:
                score += 0.25
            elif gap >= PRICE_MISMATCH_PCT:
                score -= 0.25
        scored.append({
            "code": code, "name": info["name"], "nav": info["nav"],
            "price_gap_pct": round(gap, 2) if gap is not None else None,
            "date": info["date"].isoformat() if hasattr(info["date"],
                                                        "isoformat")
            else str(info["date"]),
            "plan": plan or "", "option": option or "",
            "score": round(score, 4), "name_score": round(base, 4),
        })
    scored.sort(key=lambda c: (-c["score"], c["name"]))
    return scored[:limit]


def suggest(holding_name, navs, **kw):
    """Best candidates plus whether the top one is safe to pre-tick.

    Returns {"candidates": [...], "confident": bool, "why": str}. "Confident"
    means one candidate is both a strong name match and clearly ahead of the
    next -- not that it is right. The user still confirms.
    """
    candidates = rank(holding_name, navs, **kw)
    if not candidates:
        return {"candidates": [], "confident": False,
                "why": "nothing in AMFI's list resembles this name closely "
                       "enough to suggest. Search for it by hand."}
    best = candidates[0]
    runner_up = candidates[1]["score"] if len(candidates) > 1 else 0.0
    margin = best["score"] - runner_up
    if best["name_score"] < 0.7:
        return {"candidates": candidates, "confident": False,
                "why": "the closest name is only a partial match — check it "
                       "before applying."}
    if margin < CLEAR_MARGIN:
        return {"candidates": candidates, "confident": False,
                "why": "several schemes match this name about equally well, "
                       "usually the same fund in different plans or options. "
                       "Pick the one you actually hold."}
    if best.get("price_gap_pct") is not None:
        if best["price_gap_pct"] <= PRICE_MATCH_PCT:
            return {"candidates": candidates, "confident": True,
                    "why": "the name matches and its NAV is within %.1f%% of "
                           "the price already recorded — that agreement is "
                           "what identifies the plan."
                           % best["price_gap_pct"]}
        if best["price_gap_pct"] >= PRICE_MISMATCH_PCT:
            return {"candidates": candidates, "confident": False,
                    "why": "the name matches but its NAV is %.0f%% away from "
                           "the price already recorded, which usually means "
                           "this is a different plan of the same fund. Check "
                           "before applying." % best["price_gap_pct"]}
    return {"candidates": candidates, "confident": True,
            "why": "one clear match, in the %s plan with the %s option."
                   % (best["plan"] or "unstated", best["option"] or "unstated")}


def looks_like_scheme_code(identifier):
    """AMFI codes are short digit strings; folios are longer or have slashes."""
    ident = (identifier or "").strip()
    return ident.isdigit() and 3 <= len(ident) <= 7
