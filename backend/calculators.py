"""SIP and SWP calculators: what a plan would do, not what the portfolio did.

The FI projection in `fi.py` answers a question about *your* money -- it reads
the real corpus, the real cashflow, the real loans. These two answer a
what-if with numbers you type, which is a different job and deliberately a
different module: nothing here touches the database.

**Conventions, stated because calculators disagree about them.**

* The monthly rate is the annual rate divided by twelve. Compounding the
  effective rate instead -- (1+r)^(1/12)-1 -- is arguably more correct and
  gives a slightly smaller answer, but every SIP calculator an Indian
  investor will compare this against uses annual/12, and a figure that
  disagrees with all of them reads as a bug rather than as rigour.
* A SIP instalment goes in at the **start** of the month, so it earns that
  month's return. This is the ordinary Indian convention and matches the
  standard formula FV = P x [((1+i)^n - 1) / i] x (1+i).
* An SWP withdrawal comes out at the **start** of the month, before that
  month's growth. It is the conservative reading, and the honest one: the
  money is gone before the market can act on it.
* Step-up is applied once every twelve instalments, not continuously.

Returns are nominal. Anything the calculators report in today's money is
discounted at the inflation rate, because a crore in twenty years is not a
crore now and quoting only the nominal figure flatters the plan.
"""
import math

MAX_YEARS = 60
MAX_MONTHS = MAX_YEARS * 12

DEFAULT_RETURN = 12.0
DEFAULT_INFLATION = 6.0
DEFAULT_STEP_UP = 0.0

# An SWP that empties the corpus is still a valid plan if that is what was
# asked for, but a withdrawal so large the money is gone within a year is
# almost always a typo -- a yearly figure typed into a monthly box.
SHORT_PLAN_MONTHS = 12


def _months(years):
    """Whole months for a year count, clamped to something a person will live."""
    months = int(round(float(years) * 12))
    if months < 1:
        raise ValueError("The period must be at least one month.")
    return min(months, MAX_MONTHS)


def _monthly_rate(annual_pct):
    return float(annual_pct) / 100.0 / 12.0


def sip(monthly, annual_return_pct=DEFAULT_RETURN, years=10, *,
        step_up_pct=DEFAULT_STEP_UP, lumpsum=0.0,
        inflation_pct=DEFAULT_INFLATION):
    """Grow a monthly instalment (and any opening lumpsum) for `years`.

    Returns yearly rows plus the totals. `invested` is money in, `value` is
    what it is worth, and the difference is growth -- reported separately
    because the gap between them is the entire point of the exercise.
    """
    monthly = float(monthly or 0)
    lumpsum = float(lumpsum or 0)
    if monthly < 0 or lumpsum < 0:
        raise ValueError("Amounts cannot be negative.")
    if monthly == 0 and lumpsum == 0:
        raise ValueError("Enter a monthly amount, a lumpsum, or both.")

    n = _months(years)
    rate = _monthly_rate(annual_return_pct)
    step = 1 + float(step_up_pct) / 100.0

    balance, invested, instalment = lumpsum, lumpsum, monthly
    rows = [{"month": 0, "year": 0, "invested": round(invested, 2),
             "value": round(balance, 2), "gain": 0.0,
             "monthly_instalment": round(instalment, 2)}]

    for m in range(1, n + 1):
        balance += instalment                      # start-of-month instalment
        invested += instalment
        balance *= 1 + rate
        if m % 12 == 0:
            instalment *= step
            deflator = (1 + float(inflation_pct) / 100.0) ** (m / 12.0)
            rows.append({
                "month": m, "year": m // 12,
                "invested": round(invested, 2),
                "value": round(balance, 2),
                "gain": round(balance - invested, 2),
                "value_real": round(balance / deflator, 2),
                "monthly_instalment": round(instalment, 2),
            })

    deflator = (1 + float(inflation_pct) / 100.0) ** (n / 12.0)
    return {
        "rows": rows,
        "months": n,
        "invested": round(invested, 2),
        "value": round(balance, 2),
        "gain": round(balance - invested, 2),
        "value_real": round(balance / deflator, 2),
        "growth_multiple": round(balance / invested, 2) if invested else None,
        "final_instalment": round(instalment / step, 2) if n >= 12 else round(monthly, 2),
        "assumptions": {
            "monthly": monthly, "lumpsum": lumpsum,
            "annual_return_pct": float(annual_return_pct),
            "step_up_pct": float(step_up_pct),
            "inflation_pct": float(inflation_pct),
            "years": round(n / 12.0, 4),
        },
    }


def sip_for_target(target, annual_return_pct=DEFAULT_RETURN, years=10, *,
                   step_up_pct=DEFAULT_STEP_UP, lumpsum=0.0):
    """The monthly instalment that reaches `target` -- the question people
    actually have.

    "What will 10k a month become" is the calculator everyone builds. "I need
    50 lakh in eight years, what does that cost me a month" is the one that
    changes behaviour. Solved directly: the future value is linear in the
    instalment, so one unit SIP gives the factor to divide by.
    """
    target = float(target or 0)
    if target <= 0:
        raise ValueError("The target must be more than zero.")

    n = _months(years)
    rate = _monthly_rate(annual_return_pct)
    step = 1 + float(step_up_pct) / 100.0

    # What the lumpsum alone becomes, and what a 1/month SIP becomes.
    from_lumpsum = float(lumpsum or 0) * (1 + rate) ** n
    per_unit, instalment = 0.0, 1.0
    for m in range(1, n + 1):
        per_unit = (per_unit + instalment) * (1 + rate)
        if m % 12 == 0:
            instalment *= step

    shortfall = target - from_lumpsum
    if shortfall <= 0:
        return {"monthly": 0.0, "months": n, "target": round(target, 2),
                "from_lumpsum": round(from_lumpsum, 2),
                "already_enough": True}
    # Rounded *up* to the rupee. Rounding to the nearest leaves the plan a
    # few rupees short of its own target, which reads as a bug next to the
    # figure asked for -- and under-funding a goal is the wrong way to err.
    return {
        "monthly": float(math.ceil(shortfall / per_unit)),
        "months": n,
        "target": round(target, 2),
        "from_lumpsum": round(from_lumpsum, 2),
        "already_enough": False,
    }


def swp(corpus, monthly_withdrawal, annual_return_pct=DEFAULT_RETURN, years=25,
        *, step_up_pct=DEFAULT_STEP_UP, inflation_pct=DEFAULT_INFLATION):
    """Draw `monthly_withdrawal` from `corpus` and see whether it lasts.

    The number that matters is not the ending balance, it is the month the
    money runs out -- so that is computed exactly rather than inferred from a
    balance going negative. A withdrawal is capped at what is left, so the
    last one is partial and honest about it.

    `step_up_pct` raises the withdrawal every twelve months, which is how a
    retiree actually lives: set it to inflation and the plan is asking
    whether the corpus survives a rising cost of living, which is the real
    question.
    """
    corpus = float(corpus or 0)
    monthly_withdrawal = float(monthly_withdrawal or 0)
    if corpus <= 0:
        raise ValueError("Enter the corpus you are drawing from.")
    if monthly_withdrawal <= 0:
        raise ValueError("Enter a monthly withdrawal.")

    n = _months(years)
    rate = _monthly_rate(annual_return_pct)
    step = 1 + float(step_up_pct) / 100.0

    balance, withdrawn, want = corpus, 0.0, monthly_withdrawal
    depleted_month = None
    rows = [{"month": 0, "year": 0, "balance": round(balance, 2),
             "withdrawn": 0.0, "monthly_withdrawal": round(want, 2)}]

    for m in range(1, n + 1):
        take = min(want, balance)               # start-of-month withdrawal
        balance -= take
        withdrawn += take
        if depleted_month is None and take < want:
            depleted_month = m
        balance *= 1 + rate
        if m % 12 == 0:
            want *= step
            deflator = (1 + float(inflation_pct) / 100.0) ** (m / 12.0)
            rows.append({
                "month": m, "year": m // 12,
                "balance": round(balance, 2),
                "balance_real": round(balance / deflator, 2),
                "withdrawn": round(withdrawn, 2),
                "monthly_withdrawal": round(want, 2),
            })

    deflator = (1 + float(inflation_pct) / 100.0) ** (n / 12.0)
    lasted = depleted_month is None
    return {
        "rows": rows,
        "months": n,
        "survives": lasted,
        "depleted_month": depleted_month,
        "depleted_year": None if lasted else round(depleted_month / 12.0, 1),
        "total_withdrawn": round(withdrawn, 2),
        "ending_balance": round(balance, 2),
        "ending_balance_real": round(balance / deflator, 2),
        "assumptions": {
            "corpus": corpus, "monthly_withdrawal": monthly_withdrawal,
            "annual_return_pct": float(annual_return_pct),
            "step_up_pct": float(step_up_pct),
            "inflation_pct": float(inflation_pct),
            "years": round(n / 12.0, 4),
        },
    }


def swp_sustainable(corpus, annual_return_pct=DEFAULT_RETURN, years=25, *,
                    step_up_pct=DEFAULT_STEP_UP, tolerance=1.0):
    """The largest first withdrawal the corpus survives for the whole period.

    Bisection rather than a closed form, because the step-up makes the
    withdrawal a growing series against a compounding balance and the
    algebra stops being worth trusting. The simulation above is the
    definition of survival here, so the answer cannot disagree with the
    chart the user is looking at -- which a separate formula eventually
    would.
    """
    corpus = float(corpus or 0)
    if corpus <= 0:
        raise ValueError("Enter the corpus you are drawing from.")
    n = _months(years)

    def survives(amount):
        return swp(corpus, amount, annual_return_pct, n / 12.0,
                   step_up_pct=step_up_pct)["survives"]

    lo, hi = 0.0, corpus                    # taking the lot in month one fails
    if survives(hi):                        # a return so high it never depletes
        return {"monthly": round(hi, 2), "unbounded": True, "months": n}
    for _ in range(200):
        if hi - lo <= tolerance:
            break
        mid = (lo + hi) / 2
        if survives(mid):
            lo = mid
        else:
            hi = mid
    return {"monthly": round(lo, 2), "unbounded": False, "months": n}


def notes(result, kind):
    """Plain sentences about what the numbers do and do not say.

    Every one of these is a thing a calculator elsewhere leaves the user to
    discover for themselves.
    """
    out = []
    a = result.get("assumptions", {})
    if kind == "sip":
        if a.get("step_up_pct", 0) == 0:
            out.append(
                "The instalment never rises. Twenty years of the same amount "
                "is a real fall in what you invest -- try a step-up equal to "
                "your expected pay rise.")
        if result.get("value_real") and result.get("value"):
            out.append(
                "In today's money that is %s. The nominal figure is the one "
                "every calculator shows you; this is the one you can spend."
                % _inr(result["value_real"]))
    elif kind == "swp":
        if a.get("step_up_pct", 0) == 0 and a.get("inflation_pct", 0) > 0:
            out.append(
                "The withdrawal never rises, so this plan quietly gets poorer "
                "every year. Set the yearly increase to your inflation "
                "assumption to ask the question that matters.")
        if not result.get("survives"):
            out.append(
                "The money runs out in year %s. Everything after that month "
                "in the chart is zero, not a small balance."
                % result.get("depleted_year"))
        elif result.get("ending_balance", 0) > 0:
            out.append(
                "The corpus lasts the full period and ends at %s (%s in "
                "today's money)." % (_inr(result.get("ending_balance", 0)),
                                     _inr(result.get("ending_balance_real", 0))))
        if result.get("depleted_month") and result["depleted_month"] <= SHORT_PLAN_MONTHS:
            out.append(
                "It empties within a year, which usually means a yearly "
                "figure was typed into the monthly box.")
    out.append(
        "Returns are assumed steady. Real markets are not, and the order the "
        "years arrive in changes the answer -- " + (
            "while investing that mostly works in your favour, because a bad "
            "early year buys more units."
            if kind == "sip" else
            "while withdrawing it works against you, because a bad early year "
            "sells more units to raise the same rupees. This is the single "
            "biggest thing this calculator cannot show you."))
    out.append(
        "Tax is not modelled. " + (
            "Gains are taxed when you eventually sell, so the final figure is "
            "before tax, not in your hand."
            if kind == "sip" else
            "Every SWP instalment is a redemption, and equity gains above the "
            "annual exemption are taxed on each one -- so less reaches you "
            "than the withdrawal figures here."))
    return out


def _inr(n):
    """Indian digit grouping, without importing the analytics module."""
    n = round(float(n or 0))
    sign, n = ("-", -n) if n < 0 else ("", n)
    s = str(int(n))
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        s = ",".join(parts) + "," + tail
    return sign + "₹" + s
