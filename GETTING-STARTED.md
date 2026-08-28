# Getting started

Written for someone who has never cloned a repository, never installed
Python, and does not want to. If you are comfortable with a terminal, the
[README](README.md#running-it) says the same thing in a quarter of the space.

**What you are about to run:** a program that keeps track of your family's
money — investments, loans, insurance, income and expenses — and runs on
*your own computer*. There is no account to create, no password to choose,
and nothing is uploaded. Your figures live in a single file on your disk. The
only thing the app ever fetches from the internet is today's mutual-fund and
share prices, and it can show you every request it has made.

---

## Contents

1. [Which way should I run it?](#1-which-way-should-i-run-it)
2. [The easy way: download one file](#2-the-easy-way-download-one-file)
3. [The other way: run from the source code](#3-the-other-way-run-from-the-source-code)
4. [Your first twenty minutes in the app](#4-your-first-twenty-minutes-in-the-app)
5. [Getting your holdings in without typing them](#5-getting-your-holdings-in-without-typing-them)
6. [Making prices update by themselves](#6-making-prices-update-by-themselves)
7. [Backing up, moving, and deleting your data](#7-backing-up-moving-and-deleting-your-data)
8. [When something goes wrong](#8-when-something-goes-wrong)
9. [Words this app uses](#9-words-this-app-uses)

---

## 1. Which way should I run it?

| | Download one file | Run from the source code |
|---|---|---|
| Need Python or Node installed? | No | Yes |
| Steps | Download, double-click | Install two tools, clone, run a script |
| Get new features by | Downloading the next release | `git pull` |
| Can read/change the code? | No | Yes |

If you are not a programmer, use the download. Section 3 is for people who
want to see or change how it works — and for the time before the first
release has been published, when there is nothing to download yet.

---

## 2. The easy way: download one file

1. Go to the **[Releases](../../releases)** page of this repository.
2. Under the newest release, open **Assets** and download the one file for
   your machine:

   | Your machine | File |
   |---|---|
   | Windows | `PortfolioTracker-windows.exe` |
   | macOS | `PortfolioTracker-macos` |
   | Linux | `PortfolioTracker-linux` |

3. Run it.

   - **Windows** — double-click it. Windows will say *"Windows protected
     your PC"*. That is not a virus warning; it means nobody has paid for a
     code-signing certificate. Click **More info → Run anyway**.
   - **macOS** — the first time, **right-click the file → Open**, then
     **Open** again in the dialog. (Double-clicking gives you a dead end
     that only offers *Cancel*; right-click → Open is what adds the
     *Open* button.) If macOS says the file cannot be executed, open
     Terminal and run `chmod +x ~/Downloads/PortfolioTracker-macos` once.
   - **Linux** — `chmod +x PortfolioTracker-linux` then
     `./PortfolioTracker-linux`.

4. A small black window appears and tells you three things: the address to
   open, where your data is kept, and when the interface was built. Your
   browser opens by itself at the app.

5. **Leave that black window open** — it *is* the app. Closing it stops
   everything. Nothing runs in the background afterwards, and nothing starts
   itself when you next switch the computer on.

**If the Releases page is empty**, no release has been built yet. Either ask
whoever maintains this repository to push a version tag, or use section 3.

### Where does my data go?

The first run creates one folder:

| | Folder |
|---|---|
| Windows | `%LOCALAPPDATA%\PortfolioTracker` |
| macOS | `~/Library/Application Support/PortfolioTracker` |
| Linux | `~/.local/share/PortfolioTracker` |

The app prints this path when it starts, and shows it again on its **Privacy**
page. Everything you enter is in there.

**Keeping it on a USB stick instead:** put the downloaded app and an empty
file named `portfolio.db` in the same folder on the stick. The app notices
the file sitting beside it and uses that one, so your figures travel with the
stick and nothing at all is written to the computer.

---

## 3. The other way: run from the source code

### 3a. Install the two tools it needs

- **Python 3.9 or newer** — <https://www.python.org/downloads/>.
  On Windows, tick **"Add Python to PATH"** on the first screen of the
  installer. Miss that and every command below fails with *"python is not
  recognized"*.
- **Node 18 or newer** — <https://nodejs.org/> (the LTS button). This builds
  the pages you look at.
- **Git** — <https://git-scm.com/downloads>. Only needed to download the code
  and to update it later. You can skip it and use GitHub's **Code → Download
  ZIP** instead, but then updating means downloading the ZIP again.

Check they worked. Open **Command Prompt** (Windows) or **Terminal**
(macOS/Linux) and type:

```
python --version
node --version
```

Two version numbers means you are ready. On macOS and Linux, `python` may not
exist while `python3` does — that is fine, the start script uses `python3`.

### 3b. Get the code

```bash
git clone https://github.com/manish6007/portfolio-tracker.git
cd portfolio-tracker
```

### 3c. Run it

```bash
./start.sh          # macOS / Linux
```
```
start.bat           REM Windows — or just double-click start.bat in Explorer
```

The first run takes a couple of minutes: it makes its own private Python
environment inside the folder (`.venv`) and builds the interface. Later runs
take seconds. Then the same black window appears, with the address and the
data folder.

Here your data goes in `backend/portfolio.db`, inside the folder you cloned —
not in the system folder listed in section 2.

### 3d. Getting later versions

```bash
git pull
./start.sh          # or start.bat
```

That is the whole update. The interface rebuilds itself whenever the code is
newer than the last build, so there is no build step to remember and no way
to end up looking at last month's pages. If a page still looks wrong after an
update, your browser has cached it: press **Ctrl+Shift+R**
(**Cmd+Shift+R** on macOS).

Your `portfolio.db` is never touched by an update, and it is listed in
`.gitignore`, so your money cannot be committed to a repository by accident.

---

## 4. Your first twenty minutes in the app

**Try it with fake data first.** Go to **Settings → Load demo data**. That
fills in a realistic Indian household you can click around in. **Clear demo
data** removes exactly those records and nothing else, so you can explore
without committing to anything.

When you are ready to use your own, work down this list. The order matters —
each step makes the next one's numbers mean something.

1. **Settings → Household members.** Add yourself, your spouse, anyone else
   whose money you track. Every holding gets tagged to one of them.
2. **Settings → Target asset allocation.** Enter your age and apply a
   suggested split, or set your own. Until you do, the dashboard is comparing
   you against placeholder numbers and says so.
3. **Settings → Planning inputs.** Your emergency-fund target, and — this one
   matters more than it looks — whether the salary figure you are about to
   enter is **gross or net**. Getting it wrong is the commonest reason a
   plan quietly fails to add up.
4. **Portfolio.** Add what you own. Do not type it in — see section 5.
5. **Cashflow.** One month of income and expenses, then your committed
   outflows (EMIs, SIPs, premiums) once. Enter each one **the way it is
   actually billed** — a yearly premium as yearly, not divided by twelve.
   The app spreads it for you.
6. **Loans** and **Insurance.** Add what applies.
7. **Dashboard → Take snapshot.** Do this once a month. It is the only thing
   that builds your net-worth trend — the app does not invent history.

There is also a **Calculators** tab that needs none of the above. It works
purely on numbers you type — what a monthly SIP becomes, what SIP you need to
reach a particular amount, and how long a pot lasts if you withdraw from it
every month — and it never touches your own figures. It is a safe place to
poke around on day one.

The **ⓘ** button in the top bar opens the full guide inside the app.

### Showing it to someone without showing them your money

**Profiles** (top bar) are entirely separate portfolios, each in its own file.
Make one, tick *fill it with demo data*, switch to it, and none of your own
figures can appear on any screen. Switch back when the demo is over.

---

## 5. Getting your holdings in without typing them

**You never have to work out a unit count.** Give the app the two numbers your
fund app already shows you — **what it cost** and **what it is worth today** —
and it solves the units from the price itself.

Three ways in, best first:

1. **Your CAMS or KFintech statement (a CAS PDF).** Portfolio → Import. This
   brings in every mutual-fund folio you hold across both registrars in one
   go, complete with scheme codes, so prices refresh by themselves
   afterwards. A CAS is normally locked; there is a **CAS password** box on
   the import page — fill it in before you upload. The password is used to
   open the file and is not stored.
2. **Your broker's export.** Zerodha, Groww, Upstox, Angel One, ICICI Direct
   and most others, CSV or XLSX, uploaded exactly as it downloads. The app
   guesses which column is which, shows you its guess, and saves nothing
   until you confirm.
3. **The CSV template**, if you would rather fill in a spreadsheet.
   **Download template** on the Portfolio page. Fill in owner, name,
   identifier, invested and current_value; leave `units` and `avg_cost`
   blank — the app works those out.

Nothing is saved until you have seen the rows and pressed confirm.

---

## 6. Making prices update by themselves

**Refresh prices** (Portfolio page) fetches mutual-fund NAVs from AMFI and
share prices from Yahoo. For that to work each holding needs an identifier:

- **Mutual funds** need an **AMFI scheme code** — a number nobody knows off
  hand. A CAS import fills these in for you. Otherwise press **Match funds to
  AMFI codes**, which proposes a scheme for each of your funds by name and
  applies them in one go. Check the suggestions: every fund exists in
  Direct/Regular and Growth/IDCW versions with genuinely different NAVs, so
  the app shows you which is which and only pre-ticks matches it is sure of.
- **Shares** need the **NSE symbol** in the Identifier field — `RELIANCE`,
  not "Reliance Industries".

If *nothing* updates, that is one network problem, not fifty data problems.
**Privacy → Test connection** tries each host once and tells you exactly what
happened — a corporate proxy, DNS, a firewall, or the host refusing.

---

## 7. Backing up, moving, and deleting your data

**Backup is a file copy.** Open the **Privacy** page, which shows the real
path of every file the app keeps, then copy that folder somewhere safe. That
is a complete backup — there is nothing else. Restoring is copying it back.

**Moving it** — to an encrypted drive, a synced folder, a USB stick — is on
the same page. The app moves the files and remembers where they went.

**Deleting everything** is deleting that folder. There is no account
somewhere else, no cloud copy, and nothing left behind.

**A file named `portfolio.db` is your money in plain form.** Never commit it,
never email it, never drop it in a shared folder. If you want it encrypted,
keep the data folder on an encrypted volume (BitLocker, FileVault, LUKS) —
that is the sound way to do it, rather than trusting a password box in an app.

---

## 8. When something goes wrong

| What you see | What it means | What to do |
|---|---|---|
| *"Windows protected your PC"* | The app is not code-signed | **More info → Run anyway** |
| macOS: *"cannot be opened because it is from an unidentified developer"* | Same thing | Right-click the file → **Open** → **Open** |
| *"python is not recognized"* (Windows) | Python was installed without *Add to PATH* | Re-run the Python installer, choose **Modify**, tick *Add to PATH* |
| *"node is not recognized"* or the app says the interface could not be built | Node is missing | Install Node 18+ from nodejs.org, then run the start script again |
| The browser does not open | Only the auto-open failed | Type the address from the black window into your browser (usually `http://127.0.0.1:8765`) |
| The page looks like an older version | Your browser cached it | **Ctrl+Shift+R** (**Cmd+Shift+R** on macOS) |
| A different address than 8765 | Something else was using that port | Use whichever address the black window printed — that is always the right one |
| *MF NAVs updated: 0* | Either no scheme codes, or no network | Section 6, then **Privacy → Test connection** |
| The dashboard warns about something | The app found two figures that disagree | It reports, it never silently corrects — the warning says which two |

Anything not on this list: open an
[issue](../../issues) and paste the text from the black window.

---

## 9. Words this app uses

- **NAV** — net asset value: what one unit of a mutual fund is worth today.
- **AMFI scheme code** — the number that identifies a specific fund *and its
  exact variant* (Direct or Regular, Growth or IDCW). Prices are looked up by
  this, not by name.
- **CAS** — Consolidated Account Statement. One PDF from CAMS or KFintech
  listing every mutual fund you hold, whoever you bought it through. Request
  one at [camsonline.com](https://www.camsonline.com/) — it is emailed to you.
- **ISIN** — a twelve-character code identifying a security worldwide. The app
  uses it to match a fund in your statement to the right scheme code.
- **XIRR** — your actual annualised return, taking into account *when* each
  instalment went in. A more honest number than "current value ÷ invested".
- **FI number** — the corpus at which your investments could cover your
  expenses indefinitely.
- **Nominee** — the person a bank or fund pays out to. The app flags holdings
  without one, because that is the commonest reason a family cannot claim.
  Note that in India a nominee is often a *trustee* for the legal heirs
  rather than the owner — a nomination is not a will.
- **Offline mode** — a switch that blocks every outbound request. Everything
  except price refresh keeps working, so you can verify the privacy claim
  rather than take it on trust.
