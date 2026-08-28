import { useCallback, useEffect, useState } from 'react'
import { api, inr, inrShort } from '../api'
import { SipChart, SwpChart } from '../components/Charts'

const num = (v) => (v === '' || v == null ? null : Number(v))

function Field({ label, value, onChange, suffix, hint, ...rest }) {
  return (
    <label className="field" style={{ minWidth: 150 }}>
      {label}
      <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
        <input type="number" value={value} style={{ width: '100%' }}
          onChange={(e) => onChange(e.target.value)} {...rest} />
        {suffix && <span className="small muted">{suffix}</span>}
      </span>
      {hint && <span className="small muted">{hint}</span>}
    </label>
  )
}

function Stat({ label, value, sub, tone }) {
  return (
    <div style={{ minWidth: 150 }}>
      <div className="label" style={{ color: 'var(--text-secondary)', fontSize: 12 }}>
        {label}
      </div>
      <div style={{ fontSize: 30, fontWeight: 650, lineHeight: 1.15,
        color: tone ? `var(--${tone})` : undefined }}>{value}</div>
      {sub && <div className="small muted">{sub}</div>}
    </div>
  )
}

function Notes({ notes }) {
  if (!notes?.length) return null
  return (
    <ul className="small muted" style={{ margin: '4px 0 0', paddingLeft: 18 }}>
      {notes.map((n) => <li key={n} style={{ marginBottom: 2 }}>{n}</li>)}
    </ul>
  )
}

// ---------------- SIP ----------------
function Sip() {
  const [mode, setMode] = useState('grow')     // grow | target
  const [f, setF] = useState({
    monthly: '10000', lumpsum: '', target: '5000000',
    annual_return_pct: '12', years: '10', step_up_pct: '10',
    inflation_pct: '6',
  })
  const [data, setData] = useState(null)
  const [err, setErr] = useState('')

  const set = (k) => (v) => setF((p) => ({ ...p, [k]: v }))

  const run = useCallback(async () => {
    const body = {
      lumpsum: num(f.lumpsum) || 0,
      annual_return_pct: num(f.annual_return_pct),
      years: num(f.years),
      step_up_pct: num(f.step_up_pct) || 0,
      inflation_pct: num(f.inflation_pct),
    }
    if (mode === 'target') body.target = num(f.target)
    else body.monthly = num(f.monthly) || 0
    try {
      setData(await api.post('/api/calc/sip', body))
      setErr('')
    } catch (e) { setErr(e.message); setData(null) }
  }, [f, mode])

  useEffect(() => { run() }, [run])

  const rows = (data?.rows || []).map((r) => ({
    year: r.year, invested: r.invested, gain: r.gain, value: r.value,
    instalment: r.monthly_instalment,
  }))

  return (
    <div className="grid">
      <div className="card">
        <div className="seg" style={{ marginBottom: 12 }}>
          <button className={mode === 'grow' ? 'active' : ''}
            onClick={() => setMode('grow')}>What will my SIP become?</button>
          <button className={mode === 'target' ? 'active' : ''}
            onClick={() => setMode('target')}>What SIP do I need?</button>
        </div>
        <div className="row" style={{ gap: 12, flexWrap: 'wrap' }}>
          {mode === 'grow' ? (
            <Field label="Monthly SIP" value={f.monthly} onChange={set('monthly')}
              min="0" suffix="₹" />
          ) : (
            <Field label="I want to reach" value={f.target} onChange={set('target')}
              min="1" suffix="₹" hint="in today's rupees, ignoring inflation" />
          )}
          <Field label="Lumpsum today" value={f.lumpsum} onChange={set('lumpsum')}
            min="0" suffix="₹" hint="optional" />
          <Field label="For" value={f.years} onChange={set('years')}
            min="0.1" max="60" step="0.5" suffix="years" />
          <Field label="Expected return" value={f.annual_return_pct}
            onChange={set('annual_return_pct')} step="0.5" suffix="% a year"
            hint="equity funds: 10–12 is a fair long-run guess" />
          <Field label="Raise the SIP by" value={f.step_up_pct}
            onChange={set('step_up_pct')} min="0" step="1" suffix="% a year"
            hint="your expected pay rise" />
          <Field label="Inflation" value={f.inflation_pct}
            onChange={set('inflation_pct')} min="0" step="0.5" suffix="% a year"
            hint="used for the today's-money figure" />
        </div>
      </div>

      {err && <div className="notice">{err}</div>}

      {data && (
        <>
          <div className="card" style={{ display: 'flex', gap: 32,
            flexWrap: 'wrap', alignItems: 'flex-end' }}>
            {mode === 'target' && data.target_plan && (
              <Stat label="You need to invest"
                value={data.target_plan.already_enough
                  ? 'nothing more'
                  : inr(data.target_plan.monthly) + '/mo'}
                sub={data.target_plan.already_enough
                  ? 'the lumpsum alone gets there'
                  : `to reach ${inr(data.target_plan.target)} in ${f.years} years`} />
            )}
            <Stat label="Worth at the end" value={inr(data.value)}
              sub={`${inr(data.value_real)} in today's money`} />
            <Stat label="You will have put in" value={inr(data.invested)}
              sub={data.growth_multiple
                ? `it grows ${data.growth_multiple}×` : null} />
            <Stat label="Growth" value={inr(data.gain)} tone="good-text"
              sub={data.value > 0
                ? `${Math.round((data.gain / data.value) * 100)}% of the final pot`
                : null} />
            {num(f.step_up_pct) > 0 && (
              <Stat label="Final instalment" value={inr(data.final_instalment) + '/mo'}
                sub="after the yearly increases" />
            )}
          </div>

          <div className="card">
            <h3>Where the money comes from</h3>
            <p className="small muted" style={{ marginTop: 0 }}>
              The lower band is your own money; everything above it is growth.
              The year the upper band overtakes the lower is the year
              compounding starts doing more work than you do.
            </p>
            <SipChart rows={rows} />
          </div>

          <div className="card">
            <h3>Year by year</h3>
            <div style={{ overflowX: 'auto' }}>
              <table className="data">
                <thead>
                  <tr>
                    <th>Year</th><th className="num">Invested</th>
                    <th className="num">Growth</th><th className="num">Value</th>
                    <th className="num">In today&apos;s money</th>
                    <th className="num">Monthly SIP</th>
                  </tr>
                </thead>
                <tbody>
                  {data.rows.filter((r) => r.year > 0).map((r) => (
                    <tr key={r.year}>
                      <td>{r.year}</td>
                      <td className="num">{inrShort(r.invested)}</td>
                      <td className="num">{inrShort(r.gain)}</td>
                      <td className="num"><b>{inrShort(r.value)}</b></td>
                      <td className="num">{inrShort(r.value_real)}</td>
                      <td className="num">{inrShort(r.monthly_instalment)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Notes notes={data.notes} />
          </div>
        </>
      )}
    </div>
  )
}

// ---------------- SWP ----------------
function Swp({ summary }) {
  const [f, setF] = useState({
    corpus: '10000000', monthly_withdrawal: '50000',
    annual_return_pct: '8', years: '25', step_up_pct: '6',
    inflation_pct: '6',
  })
  const [data, setData] = useState(null)
  const [err, setErr] = useState('')

  const set = (k) => (v) => setF((p) => ({ ...p, [k]: v }))

  const run = useCallback(async () => {
    try {
      setData(await api.post('/api/calc/swp', {
        corpus: num(f.corpus),
        monthly_withdrawal: num(f.monthly_withdrawal),
        annual_return_pct: num(f.annual_return_pct),
        years: num(f.years),
        step_up_pct: num(f.step_up_pct) || 0,
        inflation_pct: num(f.inflation_pct),
      }))
      setErr('')
    } catch (e) { setErr(e.message); setData(null) }
  }, [f])

  useEffect(() => { run() }, [run])

  const mine = summary?.total_assets
  const rows = (data?.rows || []).map((r) => ({
    year: r.year, balance: r.balance, withdrawn: r.withdrawn,
    monthly: r.monthly_withdrawal,
  }))

  return (
    <div className="grid">
      <div className="card">
        <div className="row" style={{ gap: 12, flexWrap: 'wrap' }}>
          <Field label="Starting corpus" value={f.corpus} onChange={set('corpus')}
            min="1" suffix="₹" />
          <Field label="Withdraw" value={f.monthly_withdrawal}
            onChange={set('monthly_withdrawal')} min="1" suffix="₹ a month" />
          <Field label="For" value={f.years} onChange={set('years')}
            min="0.1" max="60" step="1" suffix="years"
            hint="how long it has to last" />
          <Field label="Expected return" value={f.annual_return_pct}
            onChange={set('annual_return_pct')} step="0.5" suffix="% a year"
            hint="lower than while accumulating — a drawdown pot is de-risked" />
          <Field label="Raise the withdrawal by" value={f.step_up_pct}
            onChange={set('step_up_pct')} min="0" step="0.5" suffix="% a year"
            hint="set this to inflation, or the plan gets poorer every year" />
          <Field label="Inflation" value={f.inflation_pct}
            onChange={set('inflation_pct')} min="0" step="0.5" suffix="% a year"
            hint="used for the today's-money figure" />
        </div>
        {mine > 0 && (
          <p className="small muted" style={{ marginBottom: 0 }}>
            Your portfolio is worth {inr(mine)} today.{' '}
            <button className="linkish" onClick={() => set('corpus')(String(Math.round(mine)))}>
              Use that as the corpus
            </button>
          </p>
        )}
      </div>

      {err && <div className="notice">{err}</div>}

      {data && (
        <>
          <div className="card" style={{ display: 'flex', gap: 32,
            flexWrap: 'wrap', alignItems: 'flex-end' }}>
            <Stat
              label={data.survives ? 'It lasts' : 'It runs out'}
              tone={data.survives ? 'good-text' : 'critical'}
              value={data.survives ? `all ${f.years} years`
                : `in year ${data.depleted_year}`}
              sub={data.survives
                ? `${inr(data.ending_balance)} left at the end`
                : 'the chart is zero from that point, not nearly zero'} />
            <Stat label="Safe to withdraw"
              value={inr(data.sustainable.monthly) + '/mo'}
              sub={data.sustainable.unbounded
                ? 'the return covers any withdrawal at this length'
                : `the most that lasts the full ${f.years} years`} />
            <Stat label="Total taken out" value={inr(data.total_withdrawn)} />
            {data.survives && (
              <Stat label="Left at the end" value={inr(data.ending_balance)}
                sub={`${inr(data.ending_balance_real)} in today's money`} />
            )}
          </div>

          <div className="card">
            <h3>What is left, year by year</h3>
            <p className="small muted" style={{ marginTop: 0 }}>
              Withdrawals come out at the start of each month, before that
              month&apos;s growth — the conservative reading, and the one that
              does not flatter the plan.
            </p>
            <SwpChart rows={rows} depletedYear={data.depleted_year} />
          </div>

          <div className="card">
            <h3>Year by year</h3>
            <div style={{ overflowX: 'auto' }}>
              <table className="data">
                <thead>
                  <tr>
                    <th>Year</th><th className="num">Withdrawing</th>
                    <th className="num">Taken so far</th>
                    <th className="num">Balance</th>
                    <th className="num">In today&apos;s money</th>
                  </tr>
                </thead>
                <tbody>
                  {data.rows.filter((r) => r.year > 0).map((r) => (
                    <tr key={r.year}>
                      <td>{r.year}</td>
                      <td className="num">
                        {r.balance > 0 ? inrShort(r.monthly_withdrawal) : '—'}
                      </td>
                      <td className="num">{inrShort(r.withdrawn)}</td>
                      <td className="num">
                        <b>{r.balance > 0 ? inrShort(r.balance) : '—'}</b>
                      </td>
                      <td className="num">
                        {r.balance > 0 ? inrShort(r.balance_real) : '—'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Notes notes={data.notes} />
          </div>
        </>
      )}
    </div>
  )
}

export default function Calculators({ summary }) {
  const [which, setWhich] = useState('sip')
  return (
    <div className="grid">
      <div className="card">
        <h2 style={{ marginTop: 0 }}>Calculators</h2>
        <p className="small muted">
          What-ifs on numbers you type. Nothing here reads or changes your
          portfolio, so you can try anything — the one exception is the button
          that copies your own corpus into the SWP, and that only fills in a
          box.
        </p>
        <div className="seg">
          <button className={which === 'sip' ? 'active' : ''}
            onClick={() => setWhich('sip')}>SIP · building it up</button>
          <button className={which === 'swp' ? 'active' : ''}
            onClick={() => setWhich('swp')}>SWP · drawing it down</button>
        </div>
      </div>
      {which === 'sip' ? <Sip /> : <Swp summary={summary} />}
    </div>
  )
}
