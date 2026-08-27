# Personal Wealth & Portfolio Tracker — Product Plan

A single place to track the complete financial life of a household (self + spouse):
investments, liabilities, cashflow, and savings opportunities — with an exportable
PDF snapshot that can be fed to Claude (or any AI) for optimization suggestions.

Built first for personal use, then hardened for sharing with friends and
family. It runs on the machine it is installed on; there is no service behind
it.

---

## 1. Vision & Goals

- **One dashboard** for total net worth across every asset class the household owns.
- **Household view**: my folios + wife's investments, tagged by owner, viewable
  together or separately.
- **Cashflow intelligence**: salary in, expenses out, EMIs, SIPs — surface the
  *monthly investible surplus* and suggest where it should go based on target
  asset allocation.
- **AI-ready export**: one-click PDF/JSON snapshot (with a privacy-safe mode)
  designed to be pasted into Claude for portfolio review and optimization.
- **Trust first**: this is the most sensitive data a person has. Privacy and
  security decisions are made in Phase 1, not bolted on later.

## 2. Asset Classes & Modules to Cover

### 2.1 Investments (Assets)
| Module | Key fields | Valuation source |
|---|---|---|
| Mutual Funds | Folio no., scheme, units, avg NAV, SIP details, category (equity/debt/hybrid/ELSS) | AMFI NAV feed (free, daily) |
| Direct Stocks | Ticker, exchange (NSE/BSE), qty, avg buy price, demat account | NSE/BSE EOD prices or yfinance |
| Gold | Physical (grams, purity), SGB (units, interest dates, maturity), Gold ETF/MF | IBJA gold rate / NAV |
| REITs / InvITs | Units, avg price, distributions received | Exchange price |
| Fixed Deposits | Bank, principal, rate, start/maturity date, payout type, auto-renew | Computed accrual |
| Savings Accounts | Bank, balance (manual or via import), rate | Manual/statement import |
| PF (EPF) | Balance, monthly contribution (employee+employer), rate | Manual + annual passbook entry |
| PPF | Account, balance, yearly contributions, maturity date, current rate | Computed accrual |
| NPS | PRAN, Tier I/II, scheme allocation (E/C/G), units | NPS NAV feed |
| Other investments | Bonds, P2P, crypto, ESOP/RSU, unlisted shares, real estate, insurance with investment component (ULIP/endowment), cash | Manual value + optional feed |

### 2.2 Liabilities
- **Home loan**: outstanding principal, rate (and rate-reset history), EMI,
  tenure remaining, amortization schedule, prepayment tracking, prepayment
  vs. invest what-if calculator.
- Other loans: car, personal, credit card revolving balance, loan against securities.

### 2.3 Income & Expenses
- **Salary**: net credit per month per earner; bonus/variable pay as one-offs.
- Other income: rent, dividends, FD/SGB interest, distributions.
- **Expenses**: category-wise monthly tracking (manual entry first; statement
  CSV import later; UPI/AA integration much later). Fixed vs. discretionary split.
- **Committed outflows**: EMIs, SIPs, insurance premiums, school fees — the
  recurring skeleton of the month.

### 2.4 Derived Intelligence (the real product)
- **Net worth**: total, by owner, by asset class, trend over time (monthly snapshots).
- **Asset allocation**: actual vs. target (user-defined, e.g. 60/25/10/5
  equity/debt/gold/cash), drift alerts.
- **Monthly investible cashflow** = income − expenses − EMIs − committed
  investments. Shown with a suggestion engine (rule-based first):
  - Emergency fund gap → liquid fund/FD first.
  - Allocation drift → direct surplus to underweight class.
  - Tax buckets → 80C remaining (ELSS/PPF), NPS 80CCD(1B).
  - High-interest debt → prepay before investing.
- **Savings opportunities**: idle savings-account balance above threshold,
  FDs earning below current best rates, expense categories trending up,
  duplicate/overlapping MF schemes, high expense-ratio regular plans vs. direct.
- **Goal tracking** (v2): retirement, house, education — mapped to holdings.
- **XIRR** per holding / per asset class / overall (money-weighted return).

## 3. AI Optimization Loop (differentiator)

1. **Export snapshot** as PDF (human-readable report) and JSON (machine-readable).
   Contents: net worth summary, allocation vs. target, holdings tables, XIRR,
   liabilities, cashflow summary, expense breakdown.
2. **Privacy-safe mode**: strips names, account/folio numbers, PRAN, bank names —
   keeps amounts, categories, rates, dates. This is the version fed to AI.
3. **Prompt template shipped with the export** ("You are a fee-only advisor.
   Review this portfolio for allocation drift, overlap, cost, tax efficiency…")
   so the user gets consistent, high-quality reviews from Claude.
4. Later: built-in "Ask AI" using the Claude API — the app calls
   claude-sonnet-5/claude-fable-5 directly with the anonymized snapshot, renders
   the review in-app, and keeps a history of past reviews to track whether
   suggestions were acted on.
5. **Guardrails**: always label AI output as "educational, not investment
   advice" — this matters legally (see §8).

## 4. Data Entry & Automation Strategy

Phase the pain of data entry:
1. **Manual first** (MVP): clean, fast forms + bulk CSV import templates per
   asset type. Editing must be effortless — this decides whether you keep using it.
2. **Semi-automatic**: parse standard statements users already get:
   - CAMS/KFintech Consolidated Account Statement (CAS) PDF → all MF folios
     (both spouses) in one import. This one feature removes 70% of manual work.
   - NSDL/CDSL CAS → demat holdings.
   - Broker tradebook CSVs (Zerodha/Groww/Upstox formats).
3. **Automatic prices, manual balances**: NAVs (AMFI), stock EOD prices, gold
   rate, NPS NAV auto-refresh daily; bank/EPF balances stay manual or imported.
4. **Account Aggregator (AA) framework** (only if this were ever hosted as a
   service): true auto-sync of bank/deposits via Setu/Finvu — requires being
   an AA client (FIU), regulatory overhead; not worth it for personal use.

## 5. Architecture & Tech Stack

### MVP (personal use, 2–4 weekends)
- **Streamlit + Python + SQLite** — fastest path given a Python repo; forms,
  tables, charts (plotly), and PDF export (reportlab/weasyprint) out of the box.
- Local-only data, single file DB → trivially private, easy backup.
- Modules: `models/` (SQLAlchemy), `pricing/` (AMFI, yfinance, gold), `importers/`
  (CAS/CSV parsers), `analytics/` (net worth, allocation, XIRR, suggestions),
  `export/` (PDF/JSON), `app.py` (UI).

### Share-with-others (Phase 3)
- Re-platform UI: **FastAPI backend + React/Next.js frontend** (or keep Streamlit
  briefly with auth), **PostgreSQL**, hosted (Railway/Fly/Vercel+Supabase).
- Multi-tenancy: `household → users → accounts → holdings → transactions`.
- Auth: email+OTP or Google sign-in; 2FA for good measure.

### Data model core (design this correctly on day 1)
```
User (household member)      Account (broker/bank/AMC, owner → User)
Holding (account, asset, qty, cost basis)
Transaction (buy/sell/SIP/dividend/interest/contribution/EMI/prepayment)
PriceHistory (asset, date, price/NAV)
Snapshot (monthly net-worth & allocation freeze — powers trends)
ExpenseEntry / IncomeEntry (date, category, amount, owner)
Target (allocation targets, goals)
```
Transactions-first (not balances-first) wherever possible — it unlocks XIRR,
capital gains, and history for free. Balance-only assets (EPF, savings) store
periodic balance observations instead.

## 6. Security & Privacy (non-negotiable, even for personal use)

- Encrypt DB at rest (SQLCipher locally; KMS-managed encryption hosted).
- Never store bank credentials; imports are read-only files.
- Mask account/folio numbers in UI by default (show last 4).
- Anonymized export mode (see §3) as the default for AI sharing.
- Hosted phase: TLS everywhere, per-tenant row isolation, audit log, encrypted
  backups, delete-my-data button (DPDP Act 2023 compliance in India).
- No selling of data, ever — say it in the privacy policy; it's the product's trust moat.

## 7. Roadmap

**Phase 1 — Personal MVP (use it yourself, ~4–6 weeks part-time)**
- Manual entry + CSV import for all asset classes in §2.1/2.2
- AMFI NAV + stock EOD auto-pricing; FD/PPF accrual math
- Net worth dashboard (total, by owner, by class), allocation pie, monthly snapshot
- Income/expense entry, monthly investible surplus calculation
- Rule-based investment suggestions + savings opportunities list
- PDF/JSON export with privacy-safe mode + Claude prompt template

**Phase 2 — Make it stick (validate on yourself, 4 weeks)**
- CAMS/KFintech CAS PDF importer (game-changer for MF)
- XIRR, net-worth trend charts, allocation drift alerts
- Home-loan amortization + prepay-vs-invest calculator
- 80C/80CCD tax-bucket tracker
- The test: do *you* update it monthly without forcing yourself? If not, fix
  friction before adding anything.

**Phase 3 — Share with a small circle (2–3 months)**
- Re-platform to hosted multi-user (FastAPI/Postgres), auth, household sharing
- Onboarding flow, empty states, mobile-responsive UI
- Feedback loop with 10–20 trusted users; watch retention (do they return monthly?)

Anything beyond that — hosting it as a service, charging for it — is out of
scope here, and section 8 is the reason to read before going near it.

Competition worth studying either way: INDmoney, ET Money, Kuvera, Zerodha
Console, MProfit, Fold Money. What this does that they do not: a
household-level view, an AI optimization loop, and privacy-first by
construction — no data selling, no cross-selling, and nothing leaving the
machine.

## 8. Risks & Compliance (before sharing this in India)

- **Investment advice is regulated (SEBI RIA)**: rule-based nudges and AI
  "educational analysis" must be clearly disclaimed as not investment advice;
  personalized "buy X fund" recommendations for a fee require an RIA license.
  Keep suggestions generic ("increase debt allocation") not product-specific.
- **DPDP Act 2023**: consent, purpose limitation, deletion rights once you hold
  others' data.
- **Data-source fragility**: AMFI/NSE endpoints and CAS formats change; build
  importers defensively with format-version tests.
- **Key-person risk**: it's a side project — automate pricing refresh and
  backups so a busy month doesn't kill the data.

## 9. Success Metrics

- Phase 1–2: you update it monthly for 3 consecutive months; export→Claude
  review actually changes an investment decision at least once.
- Phase 3: ≥50% of invited users active in month 2.

## 10. Immediate Next Steps

1. Freeze the data model (§5) and target allocation format.
2. Scaffold Streamlit + SQLite app with the module layout above.
3. Build MF + stocks + FD modules first (bulk of most portfolios), with AMFI
   pricing and the net-worth dashboard.
4. Add cashflow (salary/expense/EMI) and the surplus + suggestions engine.
5. Ship the PDF/JSON export with the Claude prompt template — close the AI loop.
6. Live with it for a month; let real friction drive Phase 2 priorities.
