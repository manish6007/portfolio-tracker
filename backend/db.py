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
    """
    __tablename__ = "transactions"
    id = Column(Integer, primary_key=True)
    holding_id = Column(Integer, ForeignKey("holdings.id"), nullable=False)
    date = Column(Date, nullable=False)
    type = Column(String, nullable=False)  # buy/sell/dividend/contribution/withdrawal
    amount = Column(Float, nullable=False)
    units = Column(Float, default=0.0)
    holding = relationship("Holding", back_populates="transactions")


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
