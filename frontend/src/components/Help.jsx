import { useEffect, useState } from 'react'

/* The in-app half of the user guide. Mirrors README.md — keep the two in
   step when a feature changes. */
const SECTIONS = [
  {
    id: 'start',
    title: 'Start here',
    body: [
      ['Set up, in about 20 minutes',
        ['Settings → add your spouse and anyone else whose money you track.',
          'Settings → enter your age and apply a suggested target allocation. Until you do, the dashboard is comparing you against placeholder numbers.',
          'Settings → emergency-fund target, savings float, and whether the salary you enter is gross or net — the commonest reason a plan fails to reconcile.',
          'Portfolio → add holdings, or import the CSV template in bulk.',
          'Cashflow → one month of income and expenses, then your committed outflows once.',
          'Loans and Insurance → add what applies.',
          'Dashboard → Take snapshot. Do this monthly; it is what builds the trend.']],
      ['Just exploring?',
        ['Settings → Load demo data fills a realistic household. Clear demo data removes exactly those records again, leaving anything you added.']],
      ['Showing it to someone else',
        ['Settings → Profiles → create one with “fill it with demo data” ticked, then switch to it from the chip in the top bar. A profile is a completely separate portfolio, so none of your own numbers can appear on any screen.',
          'The chip turns amber on a demo profile, so whose money is on screen is never a guess.',
          'This separates data; it is not a lock. Anyone using the laptop can switch back, and the files are unencrypted on disk — protect the machine, not the tab.']],
    ],
  },
  {
    id: 'dashboard',
    title: 'Dashboard',
    body: [
      ['What it shows',
        ['Net worth, assets, liabilities and monthly investible surplus.',
          'Allocation by asset class and by owner — hover any bar to see which holdings are inside that bucket.',
          'Equity by company size splits the equity inside your holdings into large, mid, small and international — funds and direct shares together. Funds are read from their own SEBI category and a hybrid contributes only its equity sleeve; hover a bar to see which holdings are in it and why. A share names no category, so tag it in the Company size column on the Portfolio page. That column is offered on anything carrying equity — a fund whose name says nothing, or an ESOP or PMS forced into equity by Counts as — and whatever stays untagged is listed by name under the chart, so you never have to hunt for it.',
          'Your allocation against target, prioritised suggestions, and the net-worth trend from monthly snapshots.']],
      ['Warnings',
        ['Inconsistencies appear here: an EMI with no loan behind it, holdings without a nominee, stale prices, a hybrid fund with no look-through split.',
          'Also a holding recorded as 1 unit costing its whole invested amount — what you get when the value was known but the unit count was not. It reads correctly until a real NAV arrives, and then one unit × ₹215 is ₹215. The Portfolio page asks for the real unit count and keeps what you invested unchanged; prices are left alone until you supply it, rather than wiping the holding out.',
          'These are reported, never silently corrected — the app cannot know which side is right.']],
    ],
  },
  {
    id: 'portfolio',
    title: 'Portfolio',
    body: [
      ['Fields that do real work',
        ['Identifier — AMFI scheme code for auto-NAV, NSE ticker for auto-price, or the folio/account number.',
          'Bought on — enables the short-term vs long-term split on unrealised gains.',
          'Maturity date (FDs) — an FD maturing within 12 months counts toward your emergency fund.',
          'Nominee — flagged when missing; the commonest reason a family cannot claim.',
          'Counts as — overrides the allocation bucket, e.g. a sweep FD filed under Cash.',
          '⊞ split — divides one holding across buckets, for multi-asset funds whose gold and debt would otherwise be counted as equity.']],
      ['You never have to type a unit count',
        ['Units are what the app stores — invested is units × cost, current value is units × price — but nobody reads unit counts off a screen.',
          'So give it the two numbers your fund app shows you: what it cost and what it is worth. The units follow from the price. This works in the CSV template (fill in identifier, invested and current_value; leave units and avg_cost blank), in the guided import, and when repairing a holding that has the wrong units.',
          'A row that offers no route to a unit count is refused rather than stored as a placeholder — a placeholder reads correctly until a real price arrives and then collapses the holding to that price.',
          'The same applies month to month: the ✏️ on a fund or share edits what it cost and what it is worth, and the units follow. After a SIP, put in the two new figures your fund app shows and the instalment’s units are worked out for you. The edit box shows what the units will become before you save.']],
      ['Import instead of typing',
        ['Upload a broker export exactly as it downloads — Zerodha, Groww, Upstox, Angel One, ICICI Direct and most others, CSV or XLSX. No need to rename columns.',
          'The headings brokers use are recognised automatically; the guessed mapping is shown so you can correct anything wrong, and you confirm the rows before anything is saved.',
          'A CAMS/KFintech statement PDF brings in every mutual-fund folio at once — you need the password you chose when requesting it. Both the Consolidated Account Summary table and the detailed statement work.',
          'Scheme codes are looked up from each ISIN, so imported funds refresh their own NAVs afterwards without you hunting codes.',
          'The detailed statement carries more: the nominee on each folio, and every transaction since you started — imported as real cashflows, which is what turns XIRR from an estimate into your actual money-weighted return. If a scheme opens with a balance the statement began mid-history, so its transactions are left out rather than producing a confident wrong number.',
          'The parsed totals are checked against the statement’s own Total row — if they disagree, you are told rather than quietly given a short portfolio.',
          'Importing adds new holdings; it does not update or de-duplicate existing ones.']],
      ['Prices',
        ['Refresh prices pulls MF NAVs from AMFI and stock prices from Yahoo. Give each holding its code or ticker first.',
          'AMFI prices by scheme code, not by folio number, and nobody knows their scheme codes. Funds imported from a CAS resolve their own code from the ISIN. For the rest, the Portfolio page offers “N fund(s) have no AMFI scheme code” — it proposes the match for each one and applies them together.',
          'It never picks silently. Every fund exists as Direct and Regular, Growth and IDCW, and their NAVs genuinely differ, so the plan and option are always shown and only unambiguous matches are pre-ticked. Where a fund already has a recent NAV recorded, the scheme whose price agrees with it is preferred — the surest way to tell Direct from Regular.',
          'Stocks need the NSE symbol in Identifier — RELIANCE, not “Reliance Industries”. Holdings with no ticker at all are listed separately from lookups that failed; they are different problems.',
          'If nothing comes back at all, that is one network problem rather than dozens of data problems. The message names the likely cause, and Privacy → Test connection probes each host and reports exactly what happened. Prices are never zeroed on failure.']],
    ],
  },
  {
    id: 'cashflow',
    title: 'Cashflow',
    body: [
      ['Enter costs as they are billed',
        ['A ₹12,000 yearly subscription stays a yearly ₹12,000 — the app spreads it into a monthly equivalent.',
          'The per-year column is the one that surprises people.',
          'Add a next-due date to non-monthly items and they appear in the lumpy-bills warning.']],
      ['Classify savings correctly',
        ['Mark PF, NPS and ESOP as investments, not expenses, or your savings rate reads far too low.',
          'Each card states what it is based on, e.g. "average of 3 months of entries".']],
    ],
  },
  {
    id: 'loans',
    title: 'Loans & Insurance',
    body: [
      ['Loans',
        ['Outstanding, rate, EMI and tenure, plus prepay-vs-invest.',
          'Both strategies are run to the same date and compared on what you would be worth then. Prepaying closes the loan early and the EMI freed by that is invested for the remaining months — the half most comparisons forget, and the reason a raw “interest saved” figure understates prepaying.',
          'It also gives the breakeven return: the rate at which the two tie. Argue with that number rather than with the 12% guess. Neither side models tax on the gains or the section 24 interest deduction.']],
      ['Insurance',
        ['Cover, premium, renewal date and nominee, with gaps against conventional levels — 12× income plus outstanding debt for life, a family floor for health.',
          'Premiums are held here for the reminder only; the committed outflows on Cashflow own the cashflow figure, so nothing is double-counted.']],
    ],
  },
  {
    id: 'fi',
    title: 'Financial independence',
    body: [
      ['The two questions',
        ['When do you reach your number — under 9%, 12% and 15% equity assumptions.',
          'Whether it then lasts. The projection runs accumulation and drawdown on one timeline; a plan can reach FI and still run out.']],
      ['Goals',
        ['A goal is money withdrawn from the same corpus in a given year, each inflating at its own rate — education faster than groceries.',
          'The page reports what your goals cost in FI years. That is the real price, and it may well be worth paying.']],
      ['Reading the chart',
        ['The target line rises because your expenses inflate. The band is the 9–15% range — the honest width of the forecast.',
          "Today's money is the default view; nominal figures flatter the plan."]],
    ],
  },
  {
    id: 'calculators',
    title: 'Calculators',
    body: [
      ['What they are',
        ['What-ifs on numbers you type. Nothing on this page reads or changes your portfolio, so try anything.',
          'The FI page answers a question about your actual money; these answer one about a plan you are considering. That is why they are separate.']],
      ['SIP — building it up',
        ['“What will my SIP become?” grows an instalment, and any opening lumpsum, at the return you choose.',
          '“What SIP do I need?” runs it backwards: name the amount you want and the years you have, and it gives the monthly figure — rounded up, because under-funding a goal is the wrong way to be wrong.',
          'Set the yearly increase to your expected pay rise. A flat instalment for twenty years is a real-terms cut, and the difference at the end is large.',
          'The chart is stacked: your own money below, growth above. The year the upper band overtakes the lower is the year compounding starts doing more work than you do.']],
      ['SWP — drawing it down',
        ['Ask whether a corpus survives a monthly withdrawal, and for how long. “Safe to withdraw” is the largest first withdrawal that lasts the whole period.',
          'Set the yearly increase to inflation. Withdrawing the same rupees for thirty years is a plan that quietly gets poorer; the honest question is whether it survives a rising cost of living.',
          'Withdrawals come out at the start of each month, before that month’s growth — the conservative reading.']],
      ['What they do not model',
        ['A steady return. Real markets deliver the same average in a different order, and while withdrawing that works against you: a bad early year sells more units to raise the same rupees.',
          'Tax. Every SWP instalment is a redemption, and equity gains above the annual exemption are taxed on each one.']],
    ],
  },
  {
    id: 'export',
    title: 'Export & family record',
    body: [
      ['AI review',
        ['Copy AI review package puts a reviewer prompt plus your JSON on the clipboard — paste it into a Claude chat.',
          'Privacy-safe mode (default) masks names and account numbers.',
          'The export states its own data quality, so a reviewer asks instead of assuming.']],
      ['Family record — off by default',
        ['A sealed PDF (AES-256) listing every account, folio, policy and loan in full.',
          'An open one-page locator sheet saying where the sealed file is kept and who holds the password, listing institutions with no numbers on it.',
          'Neither contains a username, password or security answer. This exists so a family can claim what is theirs, not so an account can be logged into.',
          'Where you keep it matters more than the cipher: a locker or a password manager, not email or chat.']],
    ],
  },
  {
    id: 'numbers',
    title: 'How the numbers work',
    body: [
      ['Assumptions, all editable',
        ['Income and expenses are averaged over the months that actually carry entries, not a fixed window.',
          'FDs compound quarterly and stop at maturity — a matured deposit is not still earning its old rate. PPF/EPF/savings compound annually from the balance you entered, for at most 18 months, then hold flat and ask you for a current figure. Neither grows by contributions recorded on Cashflow.',
          'Unrealised gains cover unit-priced holdings only. Accrued FD or PPF interest is income taxed as it accrues, not a capital gain.',
          'Expenses exclude EMI and include recurring costs — which is also what post-FI spending looks like.',
          'FI target defaults to 30× expenses; the 25× (4%) rule is US-derived and Indian inflation is higher.',
          'Each bucket compounds at its own rate; only equity moves across scenarios.',
          'Long-term capital gains use a simplified rule: 12 months for listed equity and equity funds, 24 otherwise. Confirm with a CA.']],
      ['What it will not do',
        ['A projection is not a prediction. It assumes steady returns; real markets deliver the same average through crashes and booms.',
          'Suggestions are deliberately generic — asset-class level, never specific products. This is not investment advice.']],
    ],
  },
  {
    id: 'privacy',
    title: 'Privacy',
    body: [
      ['No account, and nowhere to sign in',
        ['There is no login because there is nobody to log in to. The app runs on this machine and serves only this machine; whoever is at the keyboard is the user.',
          'That is deliberate rather than unfinished. The moment a personal-finance app has accounts, it has a server holding other people\u2019s salaries and folio numbers — and nobody sensible hands those over. Keeping it local is the feature.',
          'To use it on another computer, run a copy there. To take it with you, put the app and your portfolio.db in one folder on a USB stick and it will use that copy wherever it is plugged in.']],
      ['Where your data lives',
        ['SQLite files on this machine. No accounts, no cloud, no telemetry. The Privacy page shows their exact paths — back those up and you have backed up everything.',
          'The downloaded app keeps them in the place your operating system reserves for a user\u2019s own files: %LOCALAPPDATA%\\PortfolioTracker on Windows, ~/Library/Application Support/PortfolioTracker on macOS, ~/.local/share/PortfolioTracker on Linux.',
          'Keep them somewhere else if you prefer: point the app at an encrypted volume, a synced folder or a USB stick from the Privacy page. The files are copied and verified before the switch, and the originals are left for you to delete.',
          'There is no field anywhere for a password, PIN or security answer, and there will not be.']],
      ['Check it rather than believe it',
        ['The Privacy page lists every outbound request made since the app started — the whole list, not a sample. Only four hosts can ever appear: AMFI for NAVs and three Yahoo hosts for stock prices. Anything else is refused in code before a connection opens.',
          'Nothing about your portfolio is sent anywhere. A NAV refresh downloads the whole public price list and picks your funds out of it on this machine.',
          'Offline mode blocks even those. Turn it on, unplug the network, and everything except price refresh still works — which is the claim worth checking.',
          'What it does not protect you from: the files are not encrypted, profiles are separation and not a lock, and anything you export leaves on your instructions.']],
    ],
  },
]

export default function Help({ onClose }) {
  const [active, setActive] = useState(SECTIONS[0].id)

  useEffect(() => {
    const esc = (e) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', esc)
    return () => window.removeEventListener('keydown', esc)
  }, [onClose])

  const section = SECTIONS.find((s) => s.id === active) || SECTIONS[0]

  return (
    <div className="help-overlay" onClick={onClose}>
      <div className="help-panel" onClick={(e) => e.stopPropagation()}
        role="dialog" aria-label="User guide">
        <div className="help-head">
          <h1 style={{ fontSize: 18 }}>User guide</h1>
          <button className="btn secondary" onClick={onClose}>Close ✕</button>
        </div>
        <div className="help-body">
          <nav className="help-nav">
            {SECTIONS.map((s) => (
              <button key={s.id}
                className={s.id === active ? 'active' : ''}
                onClick={() => setActive(s.id)}>{s.title}</button>
            ))}
          </nav>
          <div className="help-content">
            <h2 style={{ fontSize: 16 }}>{section.title}</h2>
            {section.body.map(([heading, points]) => (
              <div key={heading} style={{ marginBottom: 18 }}>
                <b>{heading}</b>
                <ul>{points.map((t, i) => <li key={i}>{t}</li>)}</ul>
              </div>
            ))}
            <p className="small muted">
              The same guide, in more detail, is in README.md.
            </p>
          </div>
        </div>
      </div>
    </div>
  )
}
