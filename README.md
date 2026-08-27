# Portfolio Tracker

A household financial platform for Indian families: track everything you own
and owe in one place, see whether you are on course for financial
independence, and leave your family a record they can actually use.

It runs entirely on your own machine. All data sits in a single SQLite file
that never leaves it.

> **New here, and not a programmer?** Read
> **[GETTING-STARTED.md](GETTING-STARTED.md)** instead of this file. It walks
> through downloading and running the app, your first twenty minutes in it,
> and what to do when something goes wrong — assuming nothing.

**Stack**: FastAPI + SQLite backend, React (Vite) + Recharts frontend.
See [docs/PLAN.md](docs/PLAN.md) for the original product plan.

---

## Contents

- [Getting started, for a newcomer](GETTING-STARTED.md)
- [What it does](#what-it-does)
- [Running it](#running-it)
- [User guide](#user-guide)
- [How the numbers are calculated](#how-the-numbers-are-calculated)
- [Privacy and security](#privacy-and-security)
- [Testing](#testing)
- [Not built yet](#not-built-yet)

---

## What it does

### Track everything
Twelve asset classes — mutual funds, direct stocks, physical gold, sovereign
gold bonds, gold ETFs, REITs/InvITs, fixed deposits, savings accounts, EPF,
PPF, NPS and a catch-all — each tagged to a household member so you can see
your holdings and your spouse's together or apart. Mutual-fund NAVs refresh
from AMFI and stock prices from Yahoo, with a built-in AMFI scheme-code
search.

**You never have to type a unit count.** Units are what the app stores —
invested is units × cost, current value is units × price — but nobody reads
unit counts off a screen. So give it the two numbers your fund app shows you,
**what it cost and what it is worth**, and the units are worked out from the
price. That applies to the CSV template, the guided import and repairing an
existing holding alike.

**Import instead of typing.** Upload a broker export exactly as it downloads —
Zerodha, Groww, Upstox, Angel One, ICICI Direct and most others, CSV or XLSX.
The column headings brokers use are recognised automatically, the guessed
mapping is shown for you to correct, and you confirm the rows before anything
is saved. A CAMS/KFintech statement PDF brings in every mutual-fund folio across both
registrars in one go — both the Consolidated Account Summary table and the
detailed statement are understood, scheme codes are resolved from each ISIN so
NAVs refresh by themselves afterwards, and the parsed totals are checked
against the statement's own Total row so a partial read cannot pass silently.
The detailed statement also carries each folio's nominee and its full
transaction history, which are imported too — giving those holdings a real
XIRR instead of an estimate.

### See the risk inside your equity
Asset allocation says how much is in equity. It does not say whether that
equity is Nifty-50 steady or small-cap volatile, and those are different
portfolios with identical asset-class charts. **Equity by company size**
breaks the equity *inside* every holding into large, mid, small and
international — funds and direct shares in one chart. Funds are read from
their own SEBI category (a Large Cap fund must hold 80% in the top 100; a
Small Cap fund 65% beyond the top 250), a hybrid contributes only its equity
sleeve, and hovering a bar lists exactly which holdings are in it and why.
Shares carry no category in their name, so you tag those in the **Company
size** column — which is offered on anything carrying equity, including a
fund whose name says nothing and anything forced into equity by *Counts as*.
Whatever stays untagged is listed by name under the chart rather than left
as an unexplained total.

### Understand your allocation
Holdings roll up into buckets (equity, debt, gold, real estate, cash) which
you compare against a target you choose. Multi-asset funds can be split
across buckets so the gold and debt inside them stop being counted as equity.
Hover any bar to see exactly which holdings are inside that bucket.

### Know your real cashflow
Income and expenses per member, plus committed outflows — EMIs, SIPs, PF, NPS,
premiums, subscriptions, maintenance — each entered **the way it is actually
billed**: monthly, quarterly, half-yearly or yearly. Non-monthly costs are
spread into a monthly equivalent so the surplus is honest, and a warning lists
the lumpy bills falling due in the next three months so you keep the cash
reachable.

### Plan for financial independence
Your FI number, years to reach it under 9% / 12% / 15% equity assumptions, and
— the question most calculators skip — **whether the money then lasts**. The
projection runs accumulation and drawdown on one timeline. Goals (a car, a
child's education) are modelled as withdrawals from the same corpus, so you
can see what each one costs in FI years.

### Check your cover
An insurance register with sum assured, premium, renewal date and nominee,
plus a cover-adequacy check against the conventional 12× income plus
outstanding debt for life cover and a family floor for health.

### Get an AI review
Export a privacy-safe snapshot — a PDF, JSON, or a ready-to-paste package with
a reviewer prompt. The export states its own data quality: how many months
each average rests on, whether income is gross or net, what is estimated, and
every inconsistency the app has spotted, so a reviewer asks instead of
assuming.

### Show it to someone without showing them your money
Profiles: several completely separate portfolios in one installation, each in
its own database file. Switch to a demo one from the top bar and none of your
own numbers can appear on any screen. A new profile can be created pre-filled
with a sample household, so a demo takes one click rather than an evening of
typing.

This separates data; it is not a lock — see
[Privacy and security](#privacy-and-security).

### Check the privacy claims instead of believing them
A **Privacy** page that exists for the sceptic: the real paths of your data
files on this machine with their sizes, the complete list of the four hosts
the app is *able* to contact and why, and a log of **every outbound request
made since the app started** — the whole list, not a sample. Plus an
**offline mode** that blocks all of them: turn it on, unplug the network, and
everything except price refresh still works. You can also move the data
anywhere writable — an encrypted volume, a synced folder, a USB stick.

### Leave your family a record
Two documents: a **sealed PDF** (AES-256) listing every account, folio, policy
and loan in full, and an **open one-page locator sheet** saying where the
sealed file is kept and who holds the password, listing institutions with no
numbers against them. Neither contains a username, password or security
answer. Off by default.

---

## Running it

**It runs on your own machine.** That is the point of it — nobody is going to
hand their salary, portfolio and folio numbers to someone else's server, and
this app never asks them to. There is no account to make, no server to sign
in to, and nothing to trust: see [Privacy and security](#privacy-and-security),
which the app itself will show you.

### The easy way — download and run

1. Download the one file for your machine from the
   [releases page](../../releases):

   | Your machine | File |
   |---|---|
   | Windows | `PortfolioTracker-windows.exe` |
   | macOS | `PortfolioTracker-macos` |
   | Linux | `PortfolioTracker-linux` |

2. Run it. A small window opens saying where your data is kept, and your
   browser opens at the app.
3. Close that window when you are done. Nothing keeps running afterwards.

Nothing to clone, nothing to install. **Publishing a release** is one push
by whoever maintains this:

```bash
git tag v1
git push origin v1
```

That builds all three, checks each one actually starts and serves, and
attaches them to a release with direct download links. Until a tag is
pushed there is nothing on the releases page and the only way in is
[from source](#from-source).

No Python, no Node, no installer, no admin rights. The first run creates your
data folder:

| | where your portfolio is kept |
|---|---|
| Windows | `%LOCALAPPDATA%\PortfolioTracker` |
| macOS | `~/Library/Application Support/PortfolioTracker` |
| Linux | `~/.local/share/PortfolioTracker` |

**On a USB stick.** Put the app and a `portfolio.db` in the same folder and it
uses that one, so the whole thing travels with the stick and leaves nothing
on the machine.

macOS and Windows will warn that the app is from an unidentified developer,
because it is not code-signed — signing costs money and buys you nothing here
that reading the source does not. On macOS: right-click → Open. On Windows:
More info → Run anyway.

### From source
<a id="from-source"></a>

Prerequisites: Python 3.9+, Node 18+.

```bash
./start.sh          # macOS / Linux
start.bat           # Windows
```

Python is set up on the first run only. The interface is rebuilt **whenever
it is older than the code it comes from**, so after a `git pull` you just run
it again — there is no build step to remember, and no way to end up looking
at last month's pages against this month's API. The app prints when the
interface was built, so you can see which one you are looking at.

To build the downloadable app yourself:

```bash
cd frontend && npm install && npm run build && cd ..
pip install -r backend/requirements.txt pyinstaller
pyinstaller --clean --noconfirm portfolio-tracker.spec   # -> dist/
```

### For development

Two terminals, so the UI reloads as you edit it:

```bash
PORTFOLIO_DEV=1 uvicorn main:app --reload --port 8000    # in backend/
npm run dev                                              # in frontend/
```

Open the Vite URL. `PORTFOLIO_DEV=1` is what allows that origin through;
without it, cross-origin requests are refused, which is the point in
production.

**Back up your data folder** — the app shows you exactly where it is on the
Privacy page. Copy that folder and you have copied everything.

## User guide

The **ⓘ** button in the top bar opens this guide inside the app.

### Start here (about 20 minutes)

1. **Settings → Household members.** Add your spouse, and anyone else whose
   money you track.
2. **Settings → Target asset allocation.** Enter your age and apply one of the
   suggested allocations, or set your own. Until you do, the dashboard warns
   that it is comparing you against placeholder numbers.
3. **Settings → Planning inputs.** Emergency-fund target, savings float, and
   whether the salary you enter is **gross or net** — the most common reason a
   plan fails to reconcile.
4. **Portfolio.** Import your broker's CSV or your CAS PDF rather than typing
   — upload the file untouched and correct the mapping if anything was
   guessed wrong. Give mutual funds their AMFI scheme code and stocks their
   NSE ticker so prices refresh automatically.
5. **Cashflow.** Add a month of income and expenses, then your committed
   outflows once.
6. **Loans**, **Insurance** — add what applies.
7. **Dashboard → Take snapshot.** Do this monthly; it is what builds the trend.

Not sure yet? **Settings → Load demo data** fills a realistic household you
can explore, and **Clear demo data** removes exactly those records again.

### Dashboard

Net worth, assets, liabilities and monthly investible surplus; allocation by
asset class and by owner; your allocation against target; prioritised
suggestions; and the net-worth trend built from monthly snapshots.

Anything the app finds inconsistent appears here as a warning — an EMI with no
loan behind it, holdings without a nominee, stale prices, a hybrid fund with
no look-through split, a holding recorded as one unit costing its whole
invested amount. These are **reported, never silently corrected**,
because the app cannot know which side is right.

### Portfolio

| Field | Why it matters |
|---|---|
| **Identifier** | AMFI scheme code (auto-NAV), NSE ticker (auto-price), or folio/account number |
| **Bought on** | Enables the short-term vs long-term split on unrealised gains |
| **Maturity date** (FDs) | An FD maturing within 12 months counts toward your emergency fund |
| **Nominee** | Flagged when missing — the commonest reason a family cannot claim |
| **Counts as** | Overrides the allocation bucket, e.g. a sweep FD filed under Cash |
| **⊞ split** | Splits one holding across buckets — for multi-asset funds |

**Keeping it current.** The ✏️ on any fund or share edits **what it cost** and
**what it is worth** — the two figures your fund app shows you after a month
of SIPs. The units are solved back from them, so a fresh instalment is one
edit rather than an arithmetic exercise. Where there is no real per-unit
price to divide by, the unit count stays put and the price absorbs the
change; either way both numbers you typed come out true.

**Refresh prices** pulls MF NAVs from AMFI and stock prices from Yahoo.

- AMFI prices by *scheme code*, and nobody knows their scheme codes. A CAS
  import resolves them from the ISIN; for everything else, **Match funds to
  AMFI codes** on the Portfolio page proposes the scheme for each fund by
  name and applies the lot in one click. It never picks silently: every fund
  exists as Direct/Regular × Growth/IDCW with genuinely different NAVs, so
  the plan and option are always shown, only unambiguous matches are
  pre-ticked, and where a fund already has a recent NAV recorded the scheme
  whose price agrees with it wins — which is the surest way to tell Direct
  from Regular.
- Stocks need the **NSE symbol** in Identifier (`RELIANCE`, not "Reliance
  Industries"). Holdings with no ticker are listed separately from lookups
  that failed — they are different problems with different fixes.
- If nothing at all comes back, that is one network problem rather than
  dozens of data problems, and the message says which: a TLS interception
  proxy, DNS, a firewall, or the host refusing us. **Privacy → Test
  connection** tries each host once and reports exactly what happened.
  Prices are never zeroed on failure; they are left as they were.
**Unrealised gains & losses** shows the long/short split and how many holdings
are underwater.

### Cashflow

Enter each committed cost **as it is billed** — a ₹12,000 yearly subscription
stays a yearly ₹12,000 — and the app spreads it. The table shows per-payment,
per-month and per-year columns; the per-year total is the one that surprises
people.

Mark PF, NPS and ESOP contributions as **investments**, not expenses, or your
savings rate will read far too low. Each card states what it is based on
("average of 3 months of entries"), and adding a **next-due date** to
non-monthly items puts them in the lumpy-bills warning.

### Loans

Outstanding, rate, EMI and tenure, plus a **prepay vs invest** comparison. Both
strategies are run to the same date and compared on what you would be *worth*
then — prepaying closes the loan early and the freed EMI is invested for those
months, which is the half most comparisons leave out. It also reports the
**breakeven return**: the rate at which the two tie. That is the number to
argue with, rather than the 12% guess.

### Insurance

Policies with cover, premium, renewal date and nominee, and gaps against
conventional cover levels. Renewals due in the next six months are listed —
premiums are held here **for the reminder only**; the committed outflows on
Cashflow own the cashflow figure, so nothing is double-counted.

### FI (financial independence)

Your FI number in today's money, years to reach it, and whether the corpus
survives the drawdown. Add **goals** to see what each costs in FI years. The
chart shows corpus against a rising FI target with a band across the 9–15%
range; **today's money is the default view** because nominal figures flatter
the plan.

### Privacy

- **Where your data is** — the real file paths, sizes and last-written times.
  Back those files up and you have backed up everything.
- **What leaves this machine** — the four hosts the app can reach (AMFI for
  NAVs, three Yahoo hosts for stock prices) and nothing else. **Test
  connection** probes them and names the real cause when one fails. An unlisted
  host is refused in code before a connection is opened, not merely absent
  from a policy document.
- **Every request since the app started** — host, purpose, outcome. If the
  app talked to something, it is on that list.
- **Offline mode** — blocks every outbound request. Prices then come only
  from what you type; nothing else changes.
- **Keep the data somewhere else** — point the app at any writable folder.
  Files are *copied* and verified before the switch, and the originals are
  left where they were for you to delete once you have checked.

### Export

- **Privacy-safe mode** (default) masks owner names and account numbers.
- **Copy AI review package** puts a reviewer prompt plus the JSON on your
  clipboard — paste it into a Claude chat.
- **Family record** — see [Privacy and security](#privacy-and-security).

### Settings

Household members, target allocation with age-based and risk-profile presets,
planning inputs, profiles, demo data, and a confirm-guarded **Erase all data**.

#### Profiles

Create one from **Settings → Profiles**, tick *fill it with demo data*, and
switch to it from the chip in the top bar — it turns amber on a demo profile,
so whose numbers are on screen is never a guess. Each profile keeps its own
holdings, cashflow, loans, settings and snapshots in
`backend/profiles/<name>.db`; your original portfolio stays in
`backend/portfolio.db` and cannot be deleted from the UI. Deleting any other
profile erases that whole portfolio, so it asks you to type the name back.

---

## How the numbers are calculated

Assumptions worth knowing, all of them editable:

- **Valuation** — unit-priced assets use units × latest price; FDs compound
  quarterly from their start date **and stop at maturity**; PPF/EPF/savings
  compound annually from the last balance you entered, for at most 18 months,
  after which the figure is held flat and you are asked for a fresh one.
  Neither grows by contributions you record separately.
- **Averages** — income and expenses are each divided by the number of
  calendar months that actually carry entries, not by a fixed window.
- **Expenses** exclude EMI (which is tracked separately) and include the
  monthly equivalent of recurring costs. That is also what post-FI spending
  looks like, which is why the FI page uses the same figure.
- **Company size** — a fund's split is its SEBI *mandate*, not its actual
  portfolio on the day: the mandate fixes the floor and the rest is placed
  the way the category is usually run. Every split states its reasoning in
  the tooltip, and any of them can be overridden per holding.
- **Allocation presets** — equity via the "100 minus age" rule clamped to
  20–80%, gold 10%, cash 5%, REITs 5%, debt the remainder. Conventions common
  among Indian fee-only planners, not advice.
- **FI target** — annual expenses × 30 by default. The 25× (4%) rule is
  US-derived; Indian inflation is higher. 25×/30×/33× are all selectable.
- **Projection** — each bucket compounds at its own rate (equity 12%, debt 7%,
  gold 8%, cash 3.5%); new money follows your target allocation; SIPs step up
  5%/year; the EMI becomes investible when the loan closes; at FI the corpus
  is re-allocated to a conservative mix and withdrawals begin, rising with
  inflation.
- **Long-term capital gains** — simplified: 12 months for listed equity and
  equity-oriented funds, 24 otherwise. Confirm specifics with a CA.
- **Life cover** — 12× annual income plus outstanding debt. Investment-linked
  policies are counted at their stated sum assured, which flatters them.

A projection is not a prediction. It assumes steady returns in a straight
line; real markets deliver the same average through crashes and booms, and
sequence-of-returns risk is the thing these charts cannot show.

**This is not investment advice.** Suggestions are deliberately generic —
asset-class level, never specific products — and labelled educational.

---

## Privacy and security

- **There is no account, because there is nobody to log in to.** The app
  serves only the machine it runs on, and whoever is at the keyboard is the
  user. That is the design, not a gap: a personal-finance app with accounts
  needs a server holding other people's salaries and folio numbers, and
  nobody sensible hands those over. To use it elsewhere, run a copy there.
- **Nothing outside this machine can reach the app.** It refuses requests
  that did not arrive at localhost, allows no cross-origin access, and rejects
  cross-site writes. There is no login because there is no boundary to cross;
  that only holds while the boundary is actually shut, so it is tested.
- **Your data never leaves your machine.** SQLite files on disk, no accounts,
  no cloud, no telemetry. Outbound requests go only to AMFI and Yahoo for
  prices — and the **Privacy** page shows you every one of them as it
  happens, so this is checkable rather than a promise. Nothing about your
  portfolio is ever sent: the NAV request asks for the whole public price
  list and picks your funds out of it locally.
- **Nothing else is reachable.** The hosts the app may contact are a fixed
  list in `netlog.py`; anything else is refused before a socket opens. There
  is no analytics, no crash reporting and no update check.
- **Offline mode** blocks even those. The app is fully usable with the
  network off.
- **The data folder is yours to choose.** Default is next to the code;
  `PORTFOLIO_DATA_DIR` or the Privacy page moves it to an encrypted volume
  or removable drive. The files themselves are *not* encrypted — put them
  somewhere encrypted if that matters.
- **Profiles separate data; they do not lock it.** There is no login, because
  on your own laptop one would be theatre — whoever holds the machine can open
  the `.db` files whatever the screen says. Anyone using it can also switch
  profiles back. Protect the laptop, not the tab. (If this is ever hosted for
  other people, real accounts belong *on top of* the profile boundary — every
  request already says which profile it is for — and holding other people's
  financial data brings the DPDP Act into scope.)
- **No credentials, ever.** There is no field anywhere for a username,
  password, PIN or security answer, and there will not be. The app records
  *where* money is and *who inherits it*, never how to log in.
- **Privacy-safe export** masks owner names, folio and account numbers,
  insurers and policy numbers while keeping every number needed for analysis.
  Use it before sharing with any AI or person.

### The family record

Two documents, off by default, generated from Export:

1. **Sealed record** — every account, folio, policy and loan in full,
   **AES-256 encrypted**. Passwords need 10+ characters and are never stored
   anywhere; if you lose one, regenerate the file.
2. **Locator sheet** — one unencrypted page saying where the sealed file is
   kept and who holds the password, then the institutions with **no account
   numbers on it**, so it can safely sit with your will.

If AES-256 is unavailable the app **refuses to write the file** rather than
falling back to ReportLab's RC4 — a document labelled "protected" that is not
protected is worse than none.

Where you keep these matters more than the cipher. A bank locker or a password
manager's secure notes are good; email and chat apps are not.

Both documents state plainly that a record is not a will, and that in India a
nominee is often a trustee for the legal heirs rather than the owner.

---

## Testing

```bash
cd backend && pytest        # settings live in backend/pyproject.toml
flake8 .                    # settings live in backend/.flake8
```

The API is typed: request bodies are Pydantic models in `backend/schemas.py`,
so a bad value is a 422 with a readable sentence rather than a 500, a
misspelled field is rejected instead of silently ignored, and
<http://localhost:8000/docs> describes every request body properly.

CI runs both, plus a frontend build, on every push and pull request — see
`.github/workflows/ci.yml`.

299 tests. The pure analytics and FI modules, the importers, profiles,
privacy — and `test_api.py`, which goes through HTTP rather than around it,
because the host check, the CORS configuration, profile selection from the
cookie and the session lifecycle only exist on the request path.

---

## Not built yet

Considered and deliberately deferred:

- **Tax module** — old vs new regime comparison, 80C/80D optimiser.
- **Estate planning** — will drafting, document vault.
- **Account Aggregator sync** — requires being a regulated FIU; not worth it
  for personal use.

If you plan to share this with others or charge for it, read the compliance
notes in [docs/PLAN.md](docs/PLAN.md) first: personalised investment advice
for a fee is regulated by SEBI, and holding other people's financial data
brings the DPDP Act into scope.
