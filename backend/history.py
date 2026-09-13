"""What the funds were worth, month by month, back to the first purchase.

The net-worth chart could only ever start where the snapshots started --
two points a week apart, because that is when the button was first pressed.
Everything before it was unknowable: the app had positions but no purchase
history, so it could not say what was held in 2019, let alone what it was
worth.

A full-history CAS supplies the missing half. Every transaction carries an
amount and a unit count, and their ratio is the NAV on that day, so a folio
that received a monthly SIP also carries a monthly price series for free.
Units held at any past date fall straight out of the same transactions.

Two deliberate limits, both visible to the reader rather than hidden:

* **Funds only.** Shares, deposits and balances have no recorded purchase
  history, so they are left out entirely instead of being held flat at
  today's value and passed off as the past.
* **Reconstructed, not observed.** This is computed from evidence, not
  recorded at the time, so it is returned separately from the snapshots and
  never written into them.
"""
import calendar
from datetime import date


# Beyond this, a price is being carried rather than observed: a quarter is
# long enough that a fund's own transactions no longer say much about it.
STALE_DAYS = 120


def month_ends(first, last):
    """The last day of each month from `first` through `last`, inclusive."""
    if not first or not last or first > last:
        return []
    out = []
    year, month = first.year, first.month
    while (year, month) <= (last.year, last.month):
        out.append(date(year, month, calendar.monthrange(year, month)[1]))
        month += 1
        if month > 12:
            year, month = year + 1, 1
    if out and out[-1] > last:
        out[-1] = last                 # the month in progress ends today
    return out


def implied_navs(transactions):
    """[(date, NAV)] for one holding, from what each purchase actually paid.

    A statement prints the amount and the units; their ratio is the price
    that day. No NAV feed is fetched, and none is needed for a date the
    holder transacted on.
    """
    series = []
    for t in transactions:
        units = float(t.units or 0)
        amount = float(t.amount or 0)
        if units > 0 and amount > 0:
            series.append((t.date, amount / units))
    series.sort()
    return series


def nav_on(series, when):
    """The NAV on a date, interpolated between the nearest known prices.

    Straight-line between two observations, and flat beyond either end. A
    fund bought into every month carries a price every month, so the line is
    short; one left alone for two years is a long line through a period that
    was not actually straight, which is why the caller is told how far the
    nearest evidence sits.
    """
    if not series:
        return None
    if when <= series[0][0]:
        return series[0][1]
    if when >= series[-1][0]:
        return series[-1][1]
    for i in range(1, len(series)):
        d1, n1 = series[i - 1]
        d2, n2 = series[i]
        if d1 <= when <= d2:
            span = (d2 - d1).days or 1
            return n1 + (n2 - n1) * ((when - d1).days / span)
    return series[-1][1]


def evidence_gap(series, when):
    """Days to the nearest known price, so staleness can be shown not hidden."""
    if not series:
        return None
    return min(abs((d - when).days) for d, _ in series)


def units_on(transactions, when):
    """Units held on a date: everything bought less everything sold by then."""
    units = 0.0
    for t in transactions:
        if t.date > when:
            break
        if t.type == "sell":
            units -= float(t.units or 0)
        elif t.type in ("buy", "dividend"):
            units += float(t.units or 0)
    return round(units, 6)


def invested_on(transactions, when):
    """Money put in by a date, less anything taken back out."""
    total = 0.0
    for t in transactions:
        if t.date > when:
            break
        if t.type == "sell":
            total -= float(t.amount or 0)
        elif t.type == "buy":
            total += float(t.amount or 0)
    return round(total, 2)


def fund_history(funds, today=None):
    """Month-end invested and value for a set of funds.

    `funds` is an iterable of (transactions, latest NAV) pairs, one per
    holding, each transaction list sorted by date. Today's NAV is appended
    to each price series so the reconstruction is anchored at both ends
    rather than drifting off the last thing a statement happened to record.
    """
    today = today or date.today()
    prepared, first = [], None
    for txns, last_price in funds:
        txns = sorted(txns, key=lambda t: t.date)
        if not txns:
            continue
        series = implied_navs(txns)
        if last_price:
            series = [p for p in series if p[0] < today] + [(today,
                                                             float(last_price))]
        if not series:
            continue
        prepared.append((txns, series))
        first = txns[0].date if first is None else min(first, txns[0].date)
    if not prepared:
        return []
    out = []
    for when in month_ends(first, today):
        value = invested = stale_value = 0.0
        worst = 0
        for txns, series in prepared:
            units = units_on(txns, when)
            invested += invested_on(txns, when)
            if units <= 0:
                continue
            nav = nav_on(series, when)
            if nav is None:
                continue
            held = units * nav
            value += held
            gap = evidence_gap(series, when) or 0
            worst = max(worst, gap)
            if gap > STALE_DAYS:
                stale_value += held
        out.append({
            "date": when.isoformat(),
            "invested": round(invested, 2),
            "value": round(value, 2),
            "gain": round(value - invested, 2),
            # How much of this month's value rests on a price more than a
            # quarter away, as a share. One neglected fund makes a month
            # "stale" by any other measure, which reads as though the whole
            # line were guesswork; what matters is how much money it moves.
            "stale_pct": round(stale_value / value * 100, 1) if value else 0.0,
            "evidence_days": worst,
        })
    return out
