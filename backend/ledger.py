"""Positions derived from purchases, and what a sale realises.

The tracker stored `units` and `avg_cost` on the holding and nothing else,
which answers "what do I own" and refuses every question after it: what a
particular purchase cost, which parcel a sale consumed, how long the shares
sold had been held, whether the stop-loss saved money. Those need the
purchases kept as they happened.

So lots are the truth and the holding's `units`/`avg_cost` are a cache of
them, rewritten on every change. Everything downstream -- valuation,
allocation, the cap-size chart, snapshots -- keeps reading the holding and
does not know this module exists.

Two rules the rest of the app depends on:

* **Charges are part of the cost.** A return computed against the idealised
  price is a return nobody earned. Brokerage and STT go into the cost base on
  the way in and come off the proceeds on the way out.
* **Sales consume lots oldest-first.** FIFO is what Indian tax law assumes
  for listed equity, so a realised gain computed any other way would not
  match the return the taxpayer has to file.
"""
from datetime import date

# Which lot a sale eats first. FIFO is not a preference here -- it is the
# order the tax computation assumes.
SELL_ORDER = "fifo"

# Exit reasons. The list is short on purpose: a free-text box produces forty
# spellings of "stop loss" and answers nothing in aggregate.
REASONS = {
    "target": "Target reached",
    "stoploss": "Stop-loss hit",
    "rebalance": "Rebalancing",
    "thesis_broken": "Thesis no longer holds",
    "cash_need": "Needed the money",
    "other": "Other",
}

# Holding period beyond which a gain is long-term, in months. Listed
# securities were cut to 12 months and everything else to 24 by the Finance
# (No. 2) Act 2024; these are the two buckets that remain.
LONG_TERM_MONTHS = {"listed": 12, "other": 24}

# Asset classes that trade on an exchange, and so take the 12-month line.
LISTED = {"stock", "gold_etf", "reit", "sgb", "mutual_fund"}


class LedgerError(ValueError):
    """A sale the ledger cannot honour -- more units than are held."""


def lot_cost_per_unit(units, price, charges=0.0):
    """What one unit of a lot actually cost, charges included."""
    units = float(units or 0)
    if units <= 0:
        return 0.0
    return (units * float(price or 0) + float(charges or 0)) / units


def months_between(start, end):
    """Whole months from start to end, the way a holding period is counted."""
    if not start or not end:
        return 0
    months = (end.year - start.year) * 12 + (end.month - start.month)
    if end.day < start.day:
        months -= 1
    return max(months, 0)


# A parcel whose purchase date was never recorded. Reported as itself rather
# than collapsed into "stcg", because a position converted from a balance may
# have been held for a decade and saying otherwise would be a confident,
# wrong, and expensive answer at filing time.
GAIN_UNKNOWN = "unknown"


def gain_type(asset_class, buy_date, sell_date, date_known=True):
    """"ltcg", "stcg", or "unknown" for one parcel.

    An indication for the user's own records and a starting point for a tax
    return, not advice: debt funds bought after March 2023 are taxed at slab
    rates whatever the holding period, and this does not know when a fund
    changed category.
    """
    if not date_known:
        return GAIN_UNKNOWN
    limit = LONG_TERM_MONTHS["listed" if asset_class in LISTED else "other"]
    return "ltcg" if months_between(buy_date, sell_date) >= limit else "stcg"


def open_lots(lots):
    """The lots a sale can still consume, oldest first."""
    return sorted((lot for lot in lots if (lot.remaining or 0) > 1e-9),
                  key=lambda lot: (lot.date, lot.id or 0))


def position(lots):
    """(units, average cost per unit) implied by what is still held.

    The average is weighted by units and includes each lot's charges, so it
    is the number a holding's `avg_cost` should carry.
    """
    units = 0.0
    cost = 0.0
    for lot in open_lots(lots):
        remaining = float(lot.remaining or 0)
        units += remaining
        cost += remaining * lot_cost_per_unit(lot.units, lot.price, lot.charges)
    if units <= 1e-9:
        return 0.0, 0.0
    return units, cost / units


def recompute(holding):
    """Rewrite the holding's cached position from its lots.

    Called after anything touches a lot. Holdings with no lots at all are
    left alone: balance-based assets and anything not yet converted still
    carry hand-entered numbers, and zeroing those would erase real money.
    """
    if not holding.lots:
        return holding
    units, avg_cost = position(holding.lots)
    holding.units = round(units, 6)
    holding.avg_cost = round(avg_cost, 6)
    return holding


def add_lot(session, holding, when, units, price, charges=0.0, stoploss=0.0,
            source="manual", notes="", sleeve=""):
    """Record a purchase and refresh the position."""
    from db import Lot
    units = float(units or 0)
    if units <= 0:
        raise LedgerError("A purchase needs a positive number of units.")
    lot = Lot(date=when, units=units, remaining=units,
              price=float(price or 0), charges=float(charges or 0),
              stoploss=float(stoploss or 0), source=source, notes=notes or "",
              sleeve=sleeve or "")
    # Appended to the relationship rather than added to the session with a
    # holding_id: doing both puts the lot in the collection twice before the
    # flush reconciles them, and the position is read from that collection.
    holding.lots.append(lot)
    recompute(holding)
    return lot


def sold_from(lot, trades):
    """How much of a parcel has already been sold."""
    return round(sum(t.units for t in trades if t.lot_id == lot.id), 6)


def rebook(trade, lot, asset_class):
    """Recompute what a closed parcel realised, after its cost changed.

    The sale is untouched -- units, price, charges and the reason all stand.
    Only the cost side is redone, because correcting a mistyped purchase
    price has to correct the profit that was measured against it. Leaving
    the old figure would be a number the app knows is wrong.
    """
    buy_cost = lot_cost_per_unit(lot.units, lot.price, lot.charges)
    trade.buy_price = round(buy_cost, 6)
    trade.buy_date = lot.date
    trade.realised = round(
        trade.units * (trade.sell_price - buy_cost) - (trade.charges or 0), 2)
    trade.gain_type = gain_type(asset_class, lot.date, trade.sell_date,
                                date_known=bool(getattr(lot, "date_known", 1)))
    return trade


def update_lot(holding, lot, trades, **changes):
    """Correct a purchase that was entered wrongly.

    `trades` are the closed parcels booked against this lot. Two things have
    to stay true afterwards: the units still held is what was bought less
    what was sold, and any profit already booked was measured against the
    corrected cost. Both are done here rather than left to the caller.

    Reducing a parcel below what has already been sold out of it is refused
    -- the sale really happened, and the arithmetic has nowhere to put it.
    """
    sold = sold_from(lot, trades)
    if "units" in changes:
        units = float(changes["units"] or 0)
        if units <= 0:
            raise LedgerError("A purchase needs a positive number of units.")
        if units < sold - 1e-6:
            raise LedgerError(
                "%g units of this parcel have already been sold, so it "
                "cannot be reduced to %g." % (sold, units))
        lot.units = units
    for field in ("price", "charges", "stoploss"):
        if field in changes and changes[field] is not None:
            setattr(lot, field, float(changes[field]))
    if changes.get("date"):
        lot.date = changes["date"]
        lot.date_known = 1          # a date typed in is a date that is known
    if changes.get("sleeve") is not None:
        lot.sleeve = changes["sleeve"]
    if changes.get("notes") is not None:
        lot.notes = changes["notes"]
    lot.remaining = round(float(lot.units) - sold, 6)
    for trade in trades:
        if trade.lot_id == lot.id:
            rebook(trade, lot, holding.asset_class)
    recompute(holding)
    return lot


def remove_lot(holding, lot, trades):
    """Delete a purchase that never happened.

    Refused once part of it has been sold: the sale is a separate record
    that would be left pointing at nothing, and quietly deleting that too
    would erase a realised gain the user may have already filed against.
    """
    sold = sold_from(lot, trades)
    if sold > 1e-9:
        raise LedgerError(
            "%g units of this parcel have been sold. Remove the sale first, "
            "then this can go." % sold)
    holding.lots.remove(lot)
    recompute(holding)
    return lot


def unwind(holding, trade):
    """Put the units of a closed parcel back where they came from."""
    for lot in holding.lots:
        if lot.id == trade.lot_id:
            lot.remaining = round(float(lot.remaining) + float(trade.units), 6)
            break
    recompute(holding)
    return holding


def units_held(holding):
    return position(holding.lots)[0]


def sell(session, holding, when, units, price, charges=0.0, reason="",
         source="manual", notes=""):
    """Consume lots oldest-first and book what each parcel realised.

    Returns the list of RealisedTrade rows created -- one per lot touched,
    because holding period and therefore tax differ per lot and averaging
    them away discards the reason for keeping lots at all.

    Sale charges are apportioned across the parcels by units, so three
    parcels closed by one order carry a third of the brokerage each rather
    than all of it landing on the oldest.
    """
    from db import RealisedTrade
    units = float(units or 0)
    if units <= 0:
        raise LedgerError("A sale needs a positive number of units.")
    available = units_held(holding)
    # Compared with a tolerance because units are floats and a full exit
    # entered by hand should not fail on the eighth decimal place.
    if units > available + 1e-6:
        raise LedgerError(
            "Only %g units of %s are held, so %g cannot be sold."
            % (available, holding.name, units))
    price = float(price or 0)
    charges = float(charges or 0)
    left = units
    trades = []
    for lot in open_lots(holding.lots):
        if left <= 1e-9:
            break
        taken = min(left, float(lot.remaining))
        share = taken / units                    # this parcel's slice of the sale
        buy_cost = lot_cost_per_unit(lot.units, lot.price, lot.charges)
        sale_charges = charges * share
        realised = taken * (price - buy_cost) - sale_charges
        trade = RealisedTrade(
            holding_id=holding.id, lot_id=lot.id,
            buy_date=lot.date, sell_date=when, units=taken,
            buy_price=round(buy_cost, 6), sell_price=price,
            charges=round(sale_charges, 2), realised=round(realised, 2),
            reason=reason or "", source=source, notes=notes or "",
            sleeve=getattr(lot, "sleeve", "") or "",
            gain_type=gain_type(holding.asset_class, lot.date, when,
                                date_known=bool(
                                    getattr(lot, "date_known", 1))))
        session.add(trade)
        trades.append(trade)
        lot.remaining = round(float(lot.remaining) - taken, 6)
        left -= taken
    recompute(holding)
    return trades


def realised_summary(trades):
    """Totals over a set of closed parcels, for a page header."""
    total = sum(t.realised for t in trades)
    invested = sum(t.units * t.buy_price for t in trades)
    return {
        "realised": round(total, 2),
        "invested": round(invested, 2),
        "pct": round(total / invested * 100, 2) if invested else 0.0,
        "trades": len(trades),
        "wins": sum(1 for t in trades if t.realised > 0),
    }


SLEEVE_LABELS = {"core": "Core", "satellite": "Satellite",
                 "": "Not assigned"}
SLEEVE_ORDER = ("core", "satellite", "")


def sleeve_of(row):
    """The sleeve on a lot or a closed trade, normalised."""
    value = (getattr(row, "sleeve", "") or "").strip().lower()
    return value if value in SLEEVE_LABELS else ""


def open_summary(lots, price):
    """Cost, value and unrealised profit for a set of lots at one price."""
    cost = deployed(lots)
    value = round(sum(float(lot.remaining) for lot in open_lots(lots))
                  * float(price or 0), 2)
    return {"deployed": cost, "value": value,
            "unrealised": round(value - cost, 2),
            "pct": round((value - cost) / cost * 100, 2) if cost else 0.0}


def by_sleeve(positions, trades):
    """Core against satellite, and the total, on one set of numbers.

    Held apart because they are different promises: the core is judged over
    years and the satellite over weeks, and a combined figure lets a losing
    trading habit hide inside a compounding long-term position -- or the
    reverse. Anything not yet assigned is shown as itself rather than folded
    into either, for the same reason the size chart reports unclassified
    equity instead of guessing.

    `positions` is an iterable of (lots, current price) pairs.
    """
    out = {}
    for key in SLEEVE_ORDER:
        out[key] = {"sleeve": key, "label": SLEEVE_LABELS[key],
                    "deployed": 0.0, "value": 0.0, "unrealised": 0.0,
                    "realised": 0.0, "trades": 0, "wins": 0}
    for lots, price in positions:
        for lot in open_lots(lots):
            bucket = out[sleeve_of(lot)]
            cost = float(lot.remaining) * lot_cost_per_unit(
                lot.units, lot.price, lot.charges)
            bucket["deployed"] += cost
            bucket["value"] += float(lot.remaining) * float(price or 0)
    for trade in trades:
        bucket = out[sleeve_of(trade)]
        bucket["realised"] += trade.realised
        bucket["trades"] += 1
        bucket["wins"] += 1 if trade.realised > 0 else 0
    rows = []
    total = {"sleeve": "total", "label": "Total", "deployed": 0.0,
             "value": 0.0, "unrealised": 0.0, "realised": 0.0,
             "trades": 0, "wins": 0}
    for key in SLEEVE_ORDER:
        bucket = out[key]
        bucket["unrealised"] = bucket["value"] - bucket["deployed"]
        for field in ("deployed", "value", "unrealised", "realised",
                      "trades", "wins"):
            total[field] += bucket[field]
        rows.append(_rounded(bucket))
    return {"sleeves": rows, "total": _rounded(total)}


def _rounded(bucket):
    """Money to paise, and a return percentage measured against cost.

    Unrealised is measured against what is still deployed; realised against
    nothing, because the capital behind a closed trade is already home and
    dividing by it would compare two different denominators.
    """
    out = dict(bucket)
    for field in ("deployed", "value", "unrealised", "realised"):
        out[field] = round(out[field], 2)
    out["total_pnl"] = round(out["unrealised"] + out["realised"], 2)
    out["pct"] = (round(out["unrealised"] / out["deployed"] * 100, 2)
                  if out["deployed"] else 0.0)
    return out


def stoploss_verdict(trades):
    """What exiting on stops actually did, across every trade that used one.

    The question a stop-loss rule exists to answer and no spreadsheet can:
    over many trades, did stopping out preserve capital or crystallise dips
    that recovered? This reports the realised half honestly -- what the stops
    cost or saved at the moment they fired -- and says nothing about what the
    price did afterwards, which needs history this does not have.
    """
    stopped = [t for t in trades if t.reason == "stoploss"]
    others = [t for t in trades if t.reason and t.reason != "stoploss"]
    return {"stopped": realised_summary(stopped),
            "other_exits": realised_summary(others)}


def deployed(lots):
    """What the units still held actually cost -- money currently at work.

    Counted over the *remaining* units, not every unit ever bought: capital
    returned by a sale is free to buy something else, and a figure that only
    ever grows would double-count every rupee that has been recycled.

    Charges are included, for the same reason they are included everywhere
    else here -- it is what left the bank. That also keeps the arithmetic
    honest, since open profit is then exactly value minus this.
    """
    total = 0.0
    for lot in open_lots(lots):
        total += float(lot.remaining) * lot_cost_per_unit(
            lot.units, lot.price, lot.charges)
    return round(total, 2)


def cash_moved(flows):
    """Net cash into the investing pot: contributions less withdrawals.

    A different question from `deployed`, and worth keeping apart from it.
    This is money that left the bank account; deployed is the part of it
    sitting in positions right now. They differ by whatever is uninvested.
    """
    total = 0.0
    for flow in flows:
        total += flow.amount if flow.direction == "in" else -flow.amount
    return round(total, 2)


def today():
    """Indirection so tests can pin the date without patching the stdlib."""
    return date.today()
