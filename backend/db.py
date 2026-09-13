"""SQLAlchemy models and session for the portfolio tracker.

The database is a single local SQLite file (portfolio.db) next to this module,
so the data never leaves the machine. Delete the file to start fresh.
"""
import json
import os
from datetime import date

from sqlalchemy import (
    Column, Date, Float, ForeignKey, Integer, String, Text, create_engine,
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker


def default_db_path():
    """The default portfolio file, in whichever folder the user chose.

    Resolved on every call rather than fixed at import: this module's whole
    job is "the data is where you said it is", and a constant captured at
    import time quietly writes next to the code instead.
    """
    import config
    return os.path.join(config.data_dir(), "portfolio.db")


Base = declarative_base()

ASSET_CLASSES = [
    "mutual_fund", "stock", "gold_physical", "sgb", "gold_etf", "reit",
    "fd", "savings", "epf", "ppf", "nps", "other",
]

# Who wrote a row. A statement re-imported next quarter must be able to
# replace what it produced last time and step around everything a person
# entered by hand, and that is only possible if rows say where they came from.
SOURCE_MANUAL = "manual"      # typed into the app by a person
SOURCE_CAS = "cas"            # came from an imported statement
SOURCE_OPENING = "opening"    # synthesised when lots were introduced
SOURCE_BROKER = "broker"      # replayed from a broker's tradebook
SOURCES = (SOURCE_MANUAL, SOURCE_CAS, SOURCE_OPENING, SOURCE_BROKER)

# Which sleeve of the portfolio a purchase belongs to. Core is the long-term
# position added to month after month; satellite is the shorter technical
# bet. They are held to different standards and should be judged separately,
# because a satellite loss inside a combined number quietly eats the return
# the core actually earned.
#
# Carried on the lot rather than the holding, so the same company can be a
# long-term holding and a tactical trade at the same time without the two
# being averaged into one meaningless position.
SLEEVE_CORE = "core"
SLEEVE_SATELLITE = "satellite"
SLEEVE_NONE = ""              # not yet said which; reported, never guessed
SLEEVES = (SLEEVE_CORE, SLEEVE_SATELLITE)

ASSET_CLASS_LABELS = {
    "mutual_fund": "Mutual Fund",
    "stock": "Direct Stock",
    "gold_physical": "Gold (Physical)",
    "sgb": "Sovereign Gold Bond",
    "gold_etf": "Gold ETF/MF",
    "reit": "REIT / InvIT",
    "fd": "Fixed Deposit",
    "savings": "Savings Account",
    "epf": "EPF",
    "ppf": "PPF",
    "nps": "NPS",
    "other": "Other Investment",
}


class Owner(Base):
    __tablename__ = "owners"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False, unique=True)
    holdings = relationship("Holding", back_populates="owner")


class Holding(Base):
    """One investment position.

    Valuation depends on asset_class (see analytics.holding_value):
    - unit-priced (MF, stock, ETF, REIT, SGB, NPS): units * last_price
    - gold_physical: units = grams, last_price = rate/gram
    - fd: principal (avg_cost) compounded from start_date at rate
    - balance-based (savings, epf, ppf, other): manual_value as of value_date
    meta is a JSON blob for class-specific fields (category, bank, bucket
    override, sip_amount, maturity_date, ...).
    """
    __tablename__ = "holdings"
    id = Column(Integer, primary_key=True)
    owner_id = Column(Integer, ForeignKey("owners.id"), nullable=False)
    asset_class = Column(String, nullable=False)
    name = Column(String, nullable=False)
    identifier = Column(String, default="")  # folio no / ticker / scheme code / acct no
    units = Column(Float, default=0.0)
    avg_cost = Column(Float, default=0.0)    # per-unit cost, or FD principal
    manual_value = Column(Float, default=0.0)
    value_date = Column(Date, default=date.today)
    last_price = Column(Float, default=0.0)
    price_date = Column(Date, nullable=True)
    rate = Column(Float, default=0.0)        # annual % for FD/PPF/savings
    start_date = Column(Date, nullable=True)
    meta = Column(Text, default="{}")
    notes = Column(Text, default="")
    owner = relationship("Owner", back_populates="holdings")
    transactions = relationship("Transaction", back_populates="holding",
                                cascade="all, delete-orphan")
    lots = relationship("Lot", back_populates="holding",
                        cascade="all, delete-orphan",
                        order_by="Lot.date, Lot.id")

    def meta_dict(self):
        try:
            return json.loads(self.meta or "{}")
        except ValueError:
            return {}


class Transaction(Base):
    """Optional cashflow record per holding; powers XIRR when present.

    amount is the money that moved: positive for money you put in
    (buy/contribution), positive for money you took out too — the type
    field decides the XIRR sign.

    `source` says who wrote the row, and exists so re-importing a statement
    can replace what that statement produced last time without touching what
    a person entered by hand. See SOURCES.
    """
    __tablename__ = "transactions"
    id = Column(Integer, primary_key=True)
    holding_id = Column(Integer, ForeignKey("holdings.id"), nullable=False)
    date = Column(Date, nullable=False)
    type = Column(String, nullable=False)  # buy/sell/dividend/contribution/withdrawal
    amount = Column(Float, nullable=False)
    units = Column(Float, default=0.0)
    source = Column(String, default=SOURCE_MANUAL)
    # The purchase this cashflow describes, where there is one. Correcting a
    # mistyped price has to move both, or XIRR keeps quoting the typo.
    lot_id = Column(Integer, ForeignKey("lots.id"), nullable=True)
    ref = Column(String, default="")
    holding = relationship("Holding", back_populates="transactions")


class Lot(Base):
    """One purchase tranche, and how much of it is still held.

    The tracker used to keep only `units` and `avg_cost` on the holding, which
    answers "what do I own" and nothing else. It cannot say what a particular
    purchase cost, which parcel a sale consumed, or how long the shares sold
    had been held -- and holding period is what decides the tax on them. So
    purchases are stored as they happened and the average is derived.

    `remaining` is what a sale has not yet consumed; a lot that reaches zero
    stays as history rather than being deleted, because the realised trade
    that emptied it points back here.

    `charges` is brokerage, STT and the rest for the whole lot. It belongs in
    the cost base -- a return computed against the idealised price is a
    return nobody actually earned.

    `stoploss` is the price the buyer said they would be wrong at, recorded
    at purchase because a stop decided after the fall is not a stop.
    """
    __tablename__ = "lots"
    id = Column(Integer, primary_key=True)
    holding_id = Column(Integer, ForeignKey("holdings.id"), nullable=False)
    date = Column(Date, nullable=False)
    units = Column(Float, nullable=False)
    remaining = Column(Float, nullable=False)
    price = Column(Float, nullable=False)      # per unit, before charges
    charges = Column(Float, default=0.0)       # total for the lot
    stoploss = Column(Float, default=0.0)      # price level; 0 = none set
    source = Column(String, default=SOURCE_MANUAL)
    # Whether `date` is the real purchase date or a stand-in. A position that
    # predates the lot ledger usually carries no evidence of when it was
    # bought, and holding period decides the tax on it -- so the ledger says
    # it does not know rather than reporting a confident short-term gain on
    # shares held for years.
    date_known = Column(Integer, default=1)
    sleeve = Column(String, default=SLEEVE_NONE)
    # Which book this came from, when it came from one. A second tradebook
    # must replace its own rows and leave the first broker's alone, so the
    # two are told apart by name rather than lumped together as "imported".
    ref = Column(String, default="")
    notes = Column(Text, default="")
    holding = relationship("Holding", back_populates="lots")


class RealisedTrade(Base):
    """A closed round trip: one sale against one purchase lot.

    A sale spanning three lots writes three of these, because the tax and the
    holding period differ per lot and averaging them away is exactly the
    information worth keeping.

    `reason` is why the position was exited, and it is the whole point of
    recording sales at all. Without it the app can say what a stop-loss cost
    on one trade and never whether stops help across all of them.
    """
    __tablename__ = "realised_trades"
    id = Column(Integer, primary_key=True)
    holding_id = Column(Integer, ForeignKey("holdings.id"), nullable=False)
    lot_id = Column(Integer, ForeignKey("lots.id"), nullable=True)
    buy_date = Column(Date, nullable=False)
    sell_date = Column(Date, nullable=False)
    units = Column(Float, nullable=False)
    buy_price = Column(Float, nullable=False)   # per unit, charges included
    sell_price = Column(Float, nullable=False)  # per unit, before charges
    charges = Column(Float, default=0.0)        # sale charges for these units
    realised = Column(Float, nullable=False)    # net of both sides' charges
    reason = Column(String, default="")
    gain_type = Column(String, default="")      # stcg / ltcg
    # Inherited from the lot that was sold, so a closed trade stays with the
    # sleeve that took the risk even after the position is gone.
    sleeve = Column(String, default=SLEEVE_NONE)
    source = Column(String, default=SOURCE_MANUAL)
    # The sale this parcel was part of. One order can close three parcels,
    # and undoing it has to put the cashflow row back the way it was.
    txn_id = Column(Integer, ForeignKey("transactions.id"), nullable=True)
    ref = Column(String, default="")
    notes = Column(Text, default="")


class CapitalFlow(Base):
    """Money entering or leaving an owner's investing pot.

    Kept apart from what the money then bought, because "did net worth rise
    because I invested or because the market moved" is the question a monthly
    tracker exists to answer, and it is a subtraction only if contributions
    are recorded in their own right. Deriving them by summing purchases gets
    it wrong the moment cash sits idle between arriving and being deployed.
    """
    __tablename__ = "capital_flows"
    id = Column(Integer, primary_key=True)
    owner_id = Column(Integer, ForeignKey("owners.id"), nullable=False)
    date = Column(Date, nullable=False)
    direction = Column(String, nullable=False)   # in / out
    amount = Column(Float, nullable=False)
    notes = Column(Text, default="")


class IncomeEntry(Base):
    __tablename__ = "income_entries"
    id = Column(Integer, primary_key=True)
    owner_id = Column(Integer, ForeignKey("owners.id"), nullable=False)
    date = Column(Date, nullable=False)
    category = Column(String, default="Salary")
    amount = Column(Float, nullable=False)
    notes = Column(Text, default="")


class ExpenseEntry(Base):
    __tablename__ = "expense_entries"
    id = Column(Integer, primary_key=True)
    owner_id = Column(Integer, ForeignKey("owners.id"), nullable=False)
    date = Column(Date, nullable=False)
    category = Column(String, default="Household")
    amount = Column(Float, nullable=False)
    fixed = Column(Integer, default=0)  # 1 = fixed/committed, 0 = discretionary
    notes = Column(Text, default="")


class RecurringOutflow(Base):
    """A committed outflow: EMIs, SIPs, premiums, subscriptions, maintenance.

    `amount` is what leaves the account on each payment and `frequency` says
    how often, so a 12,000/year subscription is entered as it is actually
    billed. `amount_monthly` is the derived monthly equivalent, written on
    save and used by every downstream calculation.
    """
    __tablename__ = "recurring_outflows"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    kind = Column(String, default="sip")
    amount = Column(Float, default=0.0)          # per payment, as billed
    frequency = Column(String, default="monthly")
    next_due = Column(Date, nullable=True)   # next payment date, for lumpy bills
    amount_monthly = Column(Float, nullable=False)   # derived from the two above
    counts_as_investment = Column(Integer, default=0)  # savings, not spend


class Loan(Base):
    __tablename__ = "loans"
    id = Column(Integer, primary_key=True)
    owner_id = Column(Integer, ForeignKey("owners.id"), nullable=False)
    name = Column(String, nullable=False)
    kind = Column(String, default="home")  # home/car/personal/credit_card/other
    principal_outstanding = Column(Float, nullable=False)
    annual_rate = Column(Float, nullable=False)
    emi = Column(Float, default=0.0)
    tenure_months_remaining = Column(Integer, default=0)
    notes = Column(Text, default="")


class Policy(Base):
    """An insurance policy.

    Records cover, nominee and renewal date -- the things a family needs and
    usually cannot find. The premium is stored for the renewal reminder and
    for reconciliation against cashflow; it is NOT added to the cashflow here,
    because the committed-outflow list already owns that number and counting
    it twice would overstate spending.
    """
    __tablename__ = "policies"
    id = Column(Integer, primary_key=True)
    owner_id = Column(Integer, ForeignKey("owners.id"), nullable=False)
    kind = Column(String, default="term")   # term/life/health/pa/ci/motor/other
    insurer = Column(String, default="")
    name = Column(String, nullable=False)
    policy_number = Column(String, default="")
    covered = Column(String, default="")    # who is insured
    sum_assured = Column(Float, default=0.0)
    premium = Column(Float, default=0.0)
    frequency = Column(String, default="yearly")
    next_due = Column(Date, nullable=True)
    valid_till = Column(Date, nullable=True)
    nominee = Column(String, default="")
    notes = Column(Text, default="")


class Goal(Base):
    """A planned future spend: education, a house, a car, a wedding.

    Amounts are in today's money and inflate at the goal's own rate, because
    education does not inflate like groceries.
    """
    __tablename__ = "goals"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    target_year = Column(Integer, nullable=False)   # years from now
    amount_today = Column(Float, nullable=False)
    inflation_pct = Column(Float, default=8.0)
    notes = Column(Text, default="")


class Snapshot(Base):
    """Monthly freeze of net worth; powers the trend chart."""
    __tablename__ = "snapshots"
    id = Column(Integer, primary_key=True)
    date = Column(Date, nullable=False)
    total_assets = Column(Float, nullable=False)
    total_liabilities = Column(Float, nullable=False)
    net_worth = Column(Float, nullable=False)
    by_class_json = Column(Text, default="{}")
    by_owner_json = Column(Text, default="{}")


class Setting(Base):
    __tablename__ = "settings"
    key = Column(String, primary_key=True)
    value = Column(Text, default="")


# One engine per database file. Profiles are separate files, so a session
# has to be asked for by profile rather than taken from a single global.
_engines = {}
_factories = {}


def _migrate(engine):
    """Add columns introduced after a database was first created.

    SQLite cannot express these through create_all, and silently running
    against a stale schema would break inserts, so add what is missing and
    backfill it from the old values.
    """
    from sqlalchemy import text
    with engine.begin() as conn:
        cols = {r[1] for r in conn.execute(
            text("PRAGMA table_info(recurring_outflows)"))}
        if not cols:
            return
        if "amount" not in cols:
            conn.execute(text(
                "ALTER TABLE recurring_outflows ADD COLUMN amount FLOAT"))
            conn.execute(text(
                "UPDATE recurring_outflows SET amount = amount_monthly"))
        if "frequency" not in cols:
            conn.execute(text("ALTER TABLE recurring_outflows "
                              "ADD COLUMN frequency VARCHAR"))
            conn.execute(text("UPDATE recurring_outflows "
                              "SET frequency = 'monthly'"))
        if "next_due" not in cols:
            conn.execute(text("ALTER TABLE recurring_outflows "
                              "ADD COLUMN next_due DATE"))
        lot_cols = {r[1] for r in conn.execute(text("PRAGMA table_info(lots)"))}
        if lot_cols and "sleeve" not in lot_cols:
            # Left empty rather than defaulted to core: which sleeve a
            # position belongs to is a judgement only its owner can make, and
            # a wrong guess would be invisible inside the totals.
            conn.execute(text("ALTER TABLE lots ADD COLUMN sleeve VARCHAR"))
            conn.execute(text("UPDATE lots SET sleeve = :n"),
                         {"n": SLEEVE_NONE})
        trade_cols = {r[1] for r in conn.execute(
            text("PRAGMA table_info(realised_trades)"))}
        if trade_cols and "sleeve" not in trade_cols:
            conn.execute(text(
                "ALTER TABLE realised_trades ADD COLUMN sleeve VARCHAR"))
            conn.execute(text("UPDATE realised_trades SET sleeve = :n"),
                         {"n": SLEEVE_NONE})
        if lot_cols and "date_known" not in lot_cols:
            conn.execute(text("ALTER TABLE lots ADD COLUMN date_known INTEGER"))
            conn.execute(text("UPDATE lots SET date_known = "
                              "CASE WHEN source = :o THEN 0 ELSE 1 END"),
                         {"o": SOURCE_OPENING})
        for table in ("lots", "transactions", "realised_trades"):
            have = {r[1] for r in conn.execute(
                text("PRAGMA table_info(%s)" % table))}
            if have and "ref" not in have:
                conn.execute(text(
                    "ALTER TABLE %s ADD COLUMN ref VARCHAR" % table))
                conn.execute(text("UPDATE %s SET ref = ''" % table))
        if trade_cols and "txn_id" not in trade_cols:
            conn.execute(text(
                "ALTER TABLE realised_trades ADD COLUMN txn_id INTEGER"))
        txn_cols = {r[1] for r in conn.execute(
            text("PRAGMA table_info(transactions)"))}
        if txn_cols and "lot_id" not in txn_cols:
            conn.execute(text(
                "ALTER TABLE transactions ADD COLUMN lot_id INTEGER"))
        if txn_cols and "source" not in txn_cols:
            conn.execute(text("ALTER TABLE transactions "
                              "ADD COLUMN source VARCHAR"))
            # Every row that predates provenance came from a CAS import,
            # since that was the only thing writing transactions.
            conn.execute(text("UPDATE transactions SET source = :s"),
                         {"s": SOURCE_CAS})
        _backfill_opening_lots(conn)


# Marks the one-time conversion of balances into lots, so it cannot run
# twice and re-open positions the user has since sold down to nothing.
LOTS_BACKFILLED = "lots_backfilled"


def _backfill_opening_lots(conn):
    """Give every existing unit-priced holding a lot, once.

    Positions predate the lot ledger, so without this a database that has
    been in use for a year would report every holding as zero units the
    moment the position is derived from lots. The opening lot carries the
    units and average cost already recorded, which reproduces exactly what
    the app showed before -- no purchase history is invented, and the lot is
    marked `opening` so it is never mistaken for a real purchase.

    Runs at most once per database. A holding legitimately sold to zero must
    not be resurrected on the next start, so the marker is written even when
    there was nothing to convert.
    """
    from sqlalchemy import text
    done = conn.execute(text("SELECT value FROM settings WHERE key = :k"),
                        {"k": LOTS_BACKFILLED}).fetchone()
    if done:
        return
    unit_priced = ("mutual_fund", "stock", "gold_etf", "reit", "sgb", "nps",
                   "gold_physical")
    placeholders = ",".join(":c%d" % i for i in range(len(unit_priced)))
    params = {"c%d" % i: c for i, c in enumerate(unit_priced)}
    rows = conn.execute(text(
        "SELECT id, units, avg_cost, start_date, value_date FROM holdings "
        "WHERE asset_class IN (%s) AND units > 0" % placeholders), params).all()
    for hid, units, avg_cost, start_date, value_date in rows:
        # The best evidence of when this was bought, in descending order of
        # trustworthiness. A CAS transaction is a real date; value_date is
        # only when the app last saw the holding, and dating a lot from it
        # would put a years-old position inside the short-term window.
        earliest = conn.execute(text(
            "SELECT MIN(date) FROM transactions WHERE holding_id = :h "
            "AND type = 'buy'"), {"h": hid}).scalar()
        when = earliest or start_date
        known = 1 if when else 0
        conn.execute(text(
            "INSERT INTO lots (holding_id, date, units, remaining, price, "
            "charges, stoploss, source, date_known, notes) "
            "VALUES (:h, :d, :u, :u, :p, 0, 0, :s, :k, :n)"),
            {"h": hid, "d": when or value_date or date.today(),
             "u": units, "p": avg_cost or 0.0, "s": SOURCE_OPENING, "k": known,
             "n": "Opening position, from the balance recorded before "
                  "purchases were tracked individually."
                  + ("" if known else " The purchase date was not recorded, "
                     "so the holding period is unknown.")})
    conn.execute(text("INSERT INTO settings (key, value) VALUES (:k, '1')"),
                 {"k": LOTS_BACKFILLED})


def get_session(path=None):
    """A session on a database file, creating and migrating it on first use.

    path defaults to the portfolio file in the configured data folder.
    """
    path = path or default_db_path()
    if path not in _factories:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        # FastAPI runs sync endpoints in a threadpool, so several requests
        # can hit one file at once. Without a busy timeout that surfaces as
        # "database is locked" the moment a price refresh overlaps a page
        # load; WAL lets reads continue during a write.
        engine = create_engine(f"sqlite:///{path}",
                               connect_args={"timeout": 30})
        _apply_pragmas(engine)
        Base.metadata.create_all(engine)
        _migrate(engine)
        _engines[path] = engine
        _factories[path] = sessionmaker(bind=engine)
    return _factories[path]()


def _apply_pragmas(engine):
    """Settings SQLite does not default to, and this schema assumes.

    foreign_keys is OFF by default in SQLite, which makes every ForeignKey in
    the models decorative -- the ORM cascades save us, but a bulk delete
    would orphan rows.
    """
    from sqlalchemy import event

    @event.listens_for(engine, "connect")
    def _set(conn, _record):
        cur = conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.close()


def reset_engines():
    """Drop every open connection.

    Needed when the data folder changes: the engines are holding files in
    the old location, and SQLite would keep writing there.
    """
    for engine in _engines.values():
        engine.dispose()
    _engines.clear()
    _factories.clear()


def get_setting(session, key, default=""):
    row = session.get(Setting, key)
    return row.value if row else default


def set_setting(session, key, value):
    row = session.get(Setting, key)
    if row:
        row.value = value
    else:
        session.add(Setting(key=key, value=value))
    session.commit()


DEFAULT_TARGETS = {"equity": 60.0, "debt": 25.0, "gold": 10.0,
                   "real_estate": 0.0, "cash": 5.0}


def get_targets(session):
    raw = get_setting(session, "targets", "")
    if not raw:
        return dict(DEFAULT_TARGETS)
    try:
        return json.loads(raw)
    except ValueError:
        return dict(DEFAULT_TARGETS)
