import { useCallback, useEffect, useState } from 'react'
import { api, inr, inrShort } from '../api'
import { FiChart } from '../components/Charts'

const pct = (n) => (n == null ? '—' : `${n}%`)

export default function FI({ summary }) {
  const [data, setData] = useState(null)
  const [real, setReal] = useState(true)
  const [horizon, setHorizon] = useState(null)
  const [goals, setGoals] = useState([])
  const [gf, setGf] = useState({ name: '', target_year: '', amount_today: '',
    inflation_pct: '8' })
  const [err, setErr] = useState('')
  const [a, setA] = useState({ inflation_pct: '', step_up_pct: '', swr_multiple: '' })

  const load = useCallback(async () => {
    const q = Object.entries(a)
      .filter(([, v]) => v !== '')
      .map(([k, v]) => `${k}=${v}`).join('&')
    try {
      setData(await api.get('/api/fi' + (q ? '?' + q : '')))
      setErr('')
    } catch (e) { setErr(e.message) }
  }, [a])

  const loadGoals = useCallback(async () => {
    try { setGoals(await api.get('/api/goals')) } catch { /* ignore */ }
  }, [])

  useEffect(() => { load(); loadGoals() }, [load, loadGoals])

  const addGoal = async (e) => {
    e.preventDefault()
    try {
      await api.post('/api/goals', {
        name: gf.name, target_year: +gf.target_year,
        amount_today: +gf.amount_today, inflation_pct: +gf.inflation_pct,
      })
      setGf({ name: '', target_year: '', amount_today: '', inflation_pct: '8' })
      loadGoals(); load()
    } catch (er) { setErr(er.message) }
  }

  if (err) return <div className="notice">Could not build the projection: {err}</div>
  if (!data) return <p className="muted">Projecting…</p>

  const as = data.assumptions
  const base = data.scenarios.find((s) => s.equity_return_pct === 12)
    || data.scenarios[1] || data.scenarios[0]
  const lo = data.scenarios[0]
  const hi = data.scenarios[data.scenarios.length - 1]
  const ck = real ? 'corpus_real' : 'corpus'
  const tk = real ? 'fi_target_real' : 'fi_target'

  // Plot a window around the answer. Charting 40 years when FI lands in 5
  // squashes every year that matters into a flat line at the bottom.
  // The drawdown is half the story now, so the whole horizon is the default.
  const suggested = as.years
  const shown = horizon ?? suggested
  const rows = base.rows.slice(0, shown + 1).map((r, i) => ({
    year: r.year,
    corpus: r[ck],
    target: r[tk],
    band: [lo.rows[i][ck], hi.rows[i][ck]],
    living: r.living_withdrawal,
    goalSpend: r.goal_withdrawal,
    goalNames: r.goals || [],
  }))

  const age = summary && +(summary.age || 0)
  const progress = data.fi_number_today > 0
    ? Math.min(100, (data.corpus_today / data.fi_number_today) * 100) : 0
  const noExpenses = as.annual_expense <= 0

  return (
    <div className="grid">
      {noExpenses && (
        <div className="notice">
          No expenses are logged, so your FI target is ₹0 and everything below
          is meaningless. Log a month of spending on <b>Cashflow</b> first —
          FI is defined by what you spend, not what you earn.
        </div>
      )}

      {/* Hero */}
      <div className="card" style={{ display: 'flex', gap: 32, flexWrap: 'wrap',
        alignItems: 'flex-end' }}>
        <div>
          <div className="label" style={{ color: 'var(--text-secondary)', fontSize: 12 }}>
            Your FI number, in today&apos;s money
          </div>
          <div style={{ fontSize: 44, fontWeight: 650, lineHeight: 1.1 }}>
            {inr(data.fi_number_today)}
          </div>
          <div className="small muted">
            {inr(as.annual_expense)}/year of spending × {as.swr_multiple}
          </div>
        </div>
        <div>
          <div className="label" style={{ color: 'var(--text-secondary)', fontSize: 12 }}>
            On a 12% equity assumption
          </div>
          <div style={{ fontSize: 44, fontWeight: 650, lineHeight: 1.1 }}>
            {base.years_to_fi == null ? 'not within ' + as.years + 'y'
              : base.years_to_fi === 0 ? 'already there'
                : `${base.years_to_fi} years`}
          </div>
          <div className="small muted">
            {base.years_to_fi != null && age > 0
              ? `at about age ${age + base.years_to_fi}`
              : 'set your age in Settings to see the age you reach it'}
          </div>
        </div>
        <div style={{ flex: 1, minWidth: 220 }}>
          <div className="small muted" style={{ marginBottom: 4 }}>
            {progress.toFixed(0)}% of the way there ({inr(data.corpus_today)})
          </div>
          <div style={{ height: 10, background: 'var(--grid)', borderRadius: 5,
            overflow: 'hidden' }}>
            <div style={{ width: `${progress}%`, height: '100%',
              background: 'var(--series-1)', borderRadius: 5 }} />
          </div>
        </div>
      </div>

      {/* Scenarios */}
      <div className="grid cols-4">
        {data.scenarios.map((s) => (
          <div className="card stat" key={s.equity_return_pct}
            style={{
              borderColor: s.years_to_fi != null && !s.survives
                ? 'var(--critical)'
                : s === base ? 'var(--accent)' : undefined,
            }}>
            <div className="label">
              Equity at {s.equity_return_pct}%{s === base ? ' · base case' : ''}
            </div>
            <div className="value">
              {s.years_to_fi == null ? '—' : `${s.years_to_fi}y`}
            </div>
            <div className="sub">
              {s.years_to_fi == null
                ? `not reached within ${as.years} years`
                : s.survives
                  ? `then lasts, ending with ${inrShort(s.ending_corpus_real)}`
                  : `but runs out in year ${s.depleted_year}`}
            </div>
          </div>
        ))}
        <div className="card stat">
          <div className="label">Coast FI</div>
          <div className="value">
            {data.coast.years_to_fi == null ? '—' : `${data.coast.years_to_fi}y`}
          </div>
          <div className="sub">if you never invest another rupee</div>
        </div>
      </div>

      {/* Will it last */}
      {base.years_to_fi != null && (
        <div className="card" style={{
          borderColor: base.survives ? 'var(--good)' : 'var(--critical)',
        }}>
          <h2>{base.survives ? '✓ ' : '⚠ '}Will it last?</h2>
          {base.survives ? (
            <p style={{ marginTop: 0 }}>
              At 12% equity the corpus survives all {as.years} years of
              withdrawals and still holds{' '}
              <b>{inr(base.ending_corpus_real)}</b> in today&apos;s money at the
              end. Withdrawals start at {inr(as.annual_expense)}/year and rise
              with inflation every year after.
            </p>
          ) : (
            <p style={{ marginTop: 0 }}>
              At 12% equity the corpus is <b>exhausted in year
              {' '}{base.depleted_year}</b>. Reaching the number is not the same
              as it lasting — the withdrawals inflate every year. Raise the
              expenses multiple, spend less, or retire later.
            </p>
          )}
          <div className="row small muted">
            {data.scenarios.map((s) => (
              <span key={s.equity_return_pct} style={{ marginRight: 18 }}>
                At {s.equity_return_pct}%:{' '}
                {s.years_to_fi == null ? 'never reaches FI'
                  : s.survives ? `lasts, ends with ${inrShort(s.ending_corpus_real)}`
                    : `runs out in year ${s.depleted_year}`}
              </span>
            ))}
          </div>
          <p className="small muted">
            At retirement the corpus is re-allocated to a more conservative mix
            (40% equity / 50% debt) — the usual de-risking — which is why growth
            slows once drawdown begins.
          </p>
        </div>
      )}

      {/* Goals */}
      <div className="card">
        <h2>Goals</h2>
        <p className="small muted" style={{ marginTop: 0 }}>
          A goal is money withdrawn from the same corpus in a given year, so
          you can see what it costs in FI years rather than pretending it is
          funded from somewhere else. Education inflates faster than groceries,
          so each goal carries its own rate.
        </p>
        <form className="row" onSubmit={addGoal}>
          <label className="field">Goal
            <input required value={gf.name} placeholder="Child's college"
              onChange={(e) => setGf({ ...gf, name: e.target.value })} /></label>
          <label className="field">In how many years
            <input type="number" min="0" max="60" required style={{ width: 130 }}
              value={gf.target_year}
              onChange={(e) => setGf({ ...gf, target_year: e.target.value })} /></label>
          <label className="field">Cost in today&apos;s money
            <input type="number" step="any" required style={{ width: 160 }}
              value={gf.amount_today}
              onChange={(e) => setGf({ ...gf, amount_today: e.target.value })} /></label>
          <label className="field">Inflates at % p.a.
            <input type="number" step="any" style={{ width: 120 }}
              value={gf.inflation_pct}
              onChange={(e) => setGf({ ...gf, inflation_pct: e.target.value })} /></label>
          <button className="btn" type="submit">Add goal</button>
        </form>

        {goals.length > 0 && (
          <table className="data" style={{ marginTop: 12 }}>
            <thead><tr>
              <th>Goal</th><th className="num">In</th>
              <th className="num">Cost today</th><th className="num">Inflation</th>
              <th className="num">Actual cost then</th><th></th>
            </tr></thead>
            <tbody>
              {goals.map((g) => {
                const row = base.rows.find((r) => r.year === g.target_year)
                const actual = row && row.goal_withdrawal
                  ? row.goals.includes(g.name)
                    ? g.amount_today * (1 + g.inflation_pct / 100) ** g.target_year
                    : null : g.amount_today * (1 + g.inflation_pct / 100) ** g.target_year
                return (
                  <tr key={g.id}>
                    <td>{g.name}</td>
                    <td className="num">{g.target_year}y</td>
                    <td className="num">{inr(g.amount_today)}</td>
                    <td className="num">{g.inflation_pct}%</td>
                    <td className="num">{actual ? inr(actual) : '—'}</td>
                    <td><button className="icon" onClick={async () => {
                      await api.del('/api/goals/' + g.id); loadGoals(); load()
                    }}>🗑</button></td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}

        {data.goal_impact && data.goal_impact.delay_years != null && (
          <div className="notice" style={{ marginTop: 12 }}>
            {data.goal_impact.delay_years === 0
              ? 'These goals do not move your FI date.'
              : <>Your goals push financial independence out by{' '}
                <b>{data.goal_impact.delay_years} year
                  {data.goal_impact.delay_years > 1 ? 's' : ''}</b> —{' '}
                {data.goal_impact.years_to_fi_without_goals}y without them,{' '}
                {data.goal_impact.years_to_fi_with_goals}y with. That is the
                real price, and it may well be worth paying.</>}
          </div>
        )}
      </div>

      {/* Projection */}
      <div className="card">
        <div className="row" style={{ justifyContent: 'space-between',
          alignItems: 'center' }}>
          <h2>Corpus vs FI target</h2>
          <div className="row" style={{ alignItems: 'center', gap: 14 }}>
            <label className="row small" style={{ alignItems: 'center', gap: 6 }}>
              Show
              <select value={shown} style={{ padding: '4px 8px' }}
                onChange={(e) => setHorizon(+e.target.value)}>
                {[...new Set([suggested, 10, 20, 30, as.years])]
                  .filter((n) => n <= as.years).sort((x, y) => x - y)
                  .map((n) => (
                    <option key={n} value={n}>
                      {n} years{n === suggested ? ' (fits the answer)' : ''}
                    </option>
                  ))}
              </select>
            </label>
            <label className="row small" style={{ alignItems: 'center', gap: 6 }}>
              <input type="checkbox" checked={real}
                onChange={(e) => setReal(e.target.checked)} />
              Show in today&apos;s money
            </label>
          </div>
        </div>
        <FiChart rows={rows} crossover={base.years_to_fi} real={real}
          depleted={base.depleted_year} />
        <p className="small muted">
          The target line rises because your expenses inflate — FI is a moving
          number, not a fixed one. The band is the 9%–15% equity range; the
          gap between its edges is the honest width of this forecast, and a
          real market path will wander inside and outside it.
          {!real && ' Nominal figures flatter the plan: switch to today’s money to see what it buys.'}
        </p>
      </div>

      {/* Rule of 72 */}
      <div className="card">
        <h2>Rule of 72</h2>
        <p className="small muted" style={{ marginTop: 0 }}>
          Divide 72 by a return to get the years money takes to double. It is
          the quickest sanity check on any projection — and on any product
          promising to double your money.
        </p>
        <div className="row">
          {[6, 8, 9, 12, 15].map((r) => (
            <div className="card stat" key={r} style={{ minWidth: 120 }}>
              <div className="label">At {r}%</div>
              <div className="value" style={{ fontSize: 26 }}>
                {(72 / r).toFixed(1)}y
              </div>
              <div className="sub">to double</div>
            </div>
          ))}
        </div>
        <p className="small muted">
          At {as.inflation_pct}% inflation your <i>costs</i> double every{' '}
          {(72 / as.inflation_pct).toFixed(0)} years — which is why the FI
          target line above rises, and why a {as.inflation_pct}% return is
          standing still.
        </p>
      </div>

      {/* Assumptions */}
      <div className="card">
        <h2>Assumptions</h2>
        <div className="row">
          <label className="field">Inflation % p.a.
            <input type="number" step="any" style={{ width: 110 }}
              placeholder={String(as.inflation_pct)} value={a.inflation_pct}
              onChange={(e) => setA({ ...a, inflation_pct: e.target.value })} />
          </label>
          <label className="field">SIP step-up % p.a.
            <input type="number" step="any" style={{ width: 130 }}
              placeholder={String(as.step_up_pct)} value={a.step_up_pct}
              onChange={(e) => setA({ ...a, step_up_pct: e.target.value })} />
          </label>
          <label className="field">Expenses multiple
            <select value={a.swr_multiple}
              onChange={(e) => setA({ ...a, swr_multiple: e.target.value })}>
              <option value="">{as.swr_multiple}× (current)</option>
              <option value="25">25× — 4% withdrawal (US-derived)</option>
              <option value="30">30× — 3.3% withdrawal</option>
              <option value="33">33× — 3% withdrawal (cautious)</option>
            </select>
          </label>
        </div>
        <div className="row" style={{ marginTop: 10 }}>
          <table className="data" style={{ maxWidth: 640 }}>
            <thead><tr>
              <th>Input</th><th className="num">Value</th><th>Where it comes from</th>
            </tr></thead>
            <tbody>
              <tr><td>Annual spending</td><td className="num">{inr(as.annual_expense)}</td>
                <td className="small muted">Cashflow — already excludes EMI, which is
                  what post-FI spending looks like</td></tr>
              <tr><td>Invested per year</td><td className="num">{inr(as.annual_investment)}</td>
                <td className="small muted">SIPs + payroll, growing {pct(as.step_up_pct)}/yr</td></tr>
              <tr><td>Corpus today</td><td className="num">{inr(data.corpus_today)}</td>
                <td className="small muted">All holdings, each bucket compounding at its own rate</td></tr>
              <tr><td>New money allocated</td><td className="num">
                {Object.entries(as.new_money_allocation_pct || {})
                  .filter(([, v]) => v > 0)
                  .map(([k, v]) => `${k} ${v}%`).join(' · ')}</td>
                <td className="small muted">Your target allocation from Settings</td></tr>
              <tr><td>Loan closes</td><td className="num">
                {as.loan_payoff_year == null ? '—' : `${as.loan_payoff_year}y`}</td>
                <td className="small muted">
                  {as.freed_emi_annual > 0
                    ? `then ${inr(as.freed_emi_annual)}/yr of freed EMI is invested`
                    : 'no loan recorded'}</td></tr>
              <tr><td>Expected returns</td><td className="num small">
                {Object.entries(as.returns_pct).filter(([k]) => k !== 'other')
                  .map(([k, v]) => `${k} ${v}%`).join(' · ')}</td>
                <td className="small muted">Per bucket; only equity moves across scenarios</td></tr>
            </tbody>
          </table>
        </div>
        {data.notes.map((n, i) => (
          <p className="small muted" key={i}>• {n}</p>
        ))}
        <p className="small muted">
          A projection is not a prediction. It assumes steady returns in a
          straight line; real markets deliver the same average through crashes
          and booms, and retiring into a bad decade is the risk this chart
          cannot show. Treat the range as a direction of travel, revisit it
          yearly, and change the assumptions rather than trusting these.
        </p>
      </div>
    </div>
  )
}
