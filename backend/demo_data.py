"""Seed realistic demo data so the app can be explored before real entry."""
import json
from datetime import date, timedelta

from db import (ExpenseEntry, Holding, IncomeEntry, Loan, Owner,
                RecurringOutflow, set_setting)


def _owner(s, name):
    o = s.query(Owner).filter(Owner.name == name).first()
    if not o:
        o = Owner(name=name)
        s.add(o)
        s.commit()
    return o


def seed(s):
    me = _owner(s, "Me")
    wife = _owner(s, "Wife")
    today = date.today()

    if s.query(Holding).filter(Holding.name.like("DEMO %")).count():
        return  # already seeded

    holdings = [
        Holding(owner_id=me.id, asset_class="mutual_fund",
                name="DEMO Flexi Cap Fund Direct-G", identifier="122639",
                units=1520.5, avg_cost=48.2, last_price=61.4,
                price_date=today, meta=json.dumps({"category": "equity"})),
        Holding(owner_id=me.id, asset_class="mutual_fund",
                name="DEMO Corporate Bond Fund Direct-G", identifier="119091",
                units=8200.0, avg_cost=24.1, last_price=27.9,
                price_date=today, meta=json.dumps({"category": "debt"})),
        Holding(owner_id=wife.id, asset_class="mutual_fund",
                name="DEMO ELSS Tax Saver Direct-G", identifier="120503",
                units=950.0, avg_cost=71.0, last_price=93.5,
                price_date=today, meta=json.dumps({"category": "elss"})),
        Holding(owner_id=me.id, asset_class="stock", name="DEMO Reliance",
                identifier="RELIANCE", units=40, avg_cost=2350.0,
                last_price=2960.0, price_date=today),
        Holding(owner_id=wife.id, asset_class="stock", name="DEMO HDFC Bank",
                identifier="HDFCBANK", units=60, avg_cost=1490.0,
                last_price=1710.0, price_date=today),
        Holding(owner_id=me.id, asset_class="sgb", name="DEMO SGB 2027 Tr-IV",
                units=25, avg_cost=5926.0, last_price=7300.0, price_date=today),
        Holding(owner_id=wife.id, asset_class="gold_physical",
                name="DEMO Gold jewellery", units=85, avg_cost=4800.0,
                last_price=7250.0, price_date=today),
        Holding(owner_id=me.id, asset_class="reit", name="DEMO Embassy REIT",
                identifier="EMBASSY", units=300, avg_cost=340.0,
                last_price=392.0, price_date=today),
        Holding(owner_id=me.id, asset_class="fd", name="DEMO Bank FD",
                identifier="XX441", avg_cost=600000.0, rate=7.2,
                start_date=today - timedelta(days=400)),
        Holding(owner_id=me.id, asset_class="savings", name="DEMO Salary a/c",
                identifier="XX103", manual_value=340000.0, rate=3.0,
                value_date=today),
        Holding(owner_id=wife.id, asset_class="savings",
                name="DEMO Joint savings", identifier="XX771",
                manual_value=180000.0, rate=3.5, value_date=today),
        Holding(owner_id=me.id, asset_class="epf", name="DEMO EPF",
                manual_value=1250000.0, rate=8.25, value_date=today),
        Holding(owner_id=me.id, asset_class="ppf", name="DEMO PPF",
                manual_value=560000.0, rate=7.1, value_date=today),
        Holding(owner_id=me.id, asset_class="nps", name="DEMO NPS Tier-1",
                units=9500.0, avg_cost=32.0, last_price=44.8, price_date=today),
    ]
    s.add_all(holdings)

    s.add(Loan(owner_id=me.id, name="DEMO Home loan", kind="home",
               principal_outstanding=3200000.0, annual_rate=8.6, emi=42000.0,
               tenure_months_remaining=132))

    s.add_all([
        RecurringOutflow(name="DEMO Equity SIPs", kind="sip",
                         amount_monthly=40000, counts_as_investment=1),
        RecurringOutflow(name="DEMO Term + health premium", kind="premium",
                         amount_monthly=4500, counts_as_investment=0),
    ])

    for m in range(3):
        d = today - timedelta(days=30 * m + 1)
        s.add(IncomeEntry(owner_id=me.id, date=d, category="Salary",
                          amount=185000, notes="DEMO"))
        s.add(IncomeEntry(owner_id=wife.id, date=d, category="Salary",
                          amount=95000, notes="DEMO"))
        s.add(ExpenseEntry(owner_id=me.id, date=d, category="Household",
                           amount=55000, fixed=1, notes="DEMO"))
        s.add(ExpenseEntry(owner_id=me.id, date=d, category="School fees",
                           amount=18000, fixed=1, notes="DEMO"))
        s.add(ExpenseEntry(owner_id=wife.id, date=d, category="Discretionary",
                           amount=22000, fixed=0, notes="DEMO"))
    s.commit()

    set_setting(s, "emergency_fund_target", "600000")
    set_setting(s, "savings_float", "150000")
    set_setting(s, "tax_80c_used", "90000")
    set_setting(s, "tax_80ccd1b_used", "0")
