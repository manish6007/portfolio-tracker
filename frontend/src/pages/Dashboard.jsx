import { useEffect, useState } from 'react'
import { api, BUCKET_LABELS, inr } from '../api'
import { AllocationChart, CapMixChart, DonutByClass, FundHistoryChart, OwnerBar, TrendChart } from '../components/Charts'
import Warnings from '../components/Warnings'

export default function Dashboard({ summary, meta, reload }) {
  const s = summary
  const takeSnapshot = async () => { await api.post('/api/snapshots'); reload() }
  const empty = !s.holdings.length
  // The money-weighted return. Computed from the transaction history a
  // statement carries, so it is blank until one has been imported — which
  // is also why importing one appeared to change nothing.
  const [xirr, setXirr] = useState(null)
  const [showXirr, setShowXirr] = useState(false)
  const [funds, setFunds] = useState(null)
  useEffect(() => {
    api.get('/api/xirr').then(setXirr).catch(() => {})
    api.get('/api/history/funds').then(setFunds).catch(() => {})
  }, [summary])
  const ranked = (xirr?.holdings || [])
    .filter((h) => h.xirr_pct !== null)
    .sort((a, b) => b.xirr_pct - a.xirr_pct)

  return (
    <div className="grid">
      {!s.targets_customized && (
        <div className="notice">
          <b>Set your target allocation.</b> The allocation chart and
          suggestions below are comparing your portfolio against generic
          placeholder numbers, not a plan you chose. Open <b>Settings</b> to
          apply an age-based or risk-profile starting point in one click.
        </div>
      )}
      {(s.lumpy_upcoming || []).length > 0 && (
        <div className="notice">
          <b>⚠ {inr((s.lumpy_upcoming).reduce((a, l) => a + l.amount, 0))} of
          lumpy bills due in the next 3 months</b> —{' '}
          {s.lumpy_upcoming.slice(0, 3).map((l) =>
            `${l.name} ${inr(l.amount)} on ${l.due_date}`).join(', ')}
          {s.lumpy_upcoming.length > 3 && ` +${s.lumpy_upcoming.length - 3} more`}.
          They are already spread into your monthly expenses; this is about
          having the cash on the day.
        </div>
      )}
      <Warnings items={s.warnings} compact />
      {empty && (
        <div className="notice">
          No holdings yet — add them in <b>Portfolio</b>, or load sample data
          from <b>Settings → Demo data</b> to explore the app.
        </div>
      )}
      <div className="grid cols-4">
        <div className="card stat">
          <div className="label">Total assets</div>
          <div className="value">{inr(s.total_assets)}</div>
        </div>
        <div className="card stat">
          <div className="label">Liabilities</div>
          <div className="value">{inr(s.total_liabilities)}</div>
        </div>
        <div className="card stat">
          <div className="label">Net worth</div>
          <div className={'value ' + (s.net_worth >= 0 ? 'pos' : 'neg')}>{inr(s.net_worth)}</div>
        </div>
        <div className="card stat">
          <div className="label">Investible surplus / month</div>
          <div className={'value ' + (s.cashflow.surplus_m >= 0 ? '' : 'neg')}>
            {inr(s.cashflow.surplus_m)}
          </div>
          <div className="sub">savings rate {s.cashflow.savings_rate_pct.toFixed(0)}%</div>
        </div>
      </div>

      {xirr && xirr.overall_pct !== null && (
        <div className="card">
          <div className="row" style={{ justifyContent: 'space-between' }}>
            <div>
              <div className="label">Return so far (XIRR)</div>
              <div className="value">{xirr.overall_pct}%</div>
              <div className="sub">
                Money-weighted, from {ranked.length} holding
                {ranked.length === 1 ? '' : 's'} with a recorded history —
                what your money actually earned, not what the funds returned.
              </div>
            </div>
            {ranked.length > 0 && (
              <button onClick={() => setShowXirr(!showXirr)}>
                {showXirr ? 'Hide' : 'By holding'}
              </button>
            )}
          </div>
          {showXirr && (
            <div style={{ overflowX: 'auto', marginTop: 8 }}>
              <table>
                <thead>
                  <tr><th>Holding</th><th className="num">XIRR</th></tr>
                </thead>
                <tbody>
                  {ranked.map((h) => (
                    <tr key={h.holding_id}>
                      <td>{h.name}</td>
                      <td className="num">{h.xirr_pct}%</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="small muted">
                A holding is missing here when nothing records when it was
                bought. Import a full-history CAS, or record purchases in the
                Journal, and it appears.
              </p>
            </div>
          )}
        </div>
      )}

      <div className="grid cols-2">
        <div className="card">
          <h2>By asset class</h2>
          <DonutByClass byClass={s.by_class} labels={meta.asset_class_labels} />
        </div>
        <div className="card">
          <h2>By owner</h2>
          <OwnerBar byOwner={s.by_owner} />
        </div>
      </div>

      <div className="grid cols-2">
        <div className="card">
          <h2>Equity by company size</h2>
          <p className="small muted" style={{ marginTop: -4 }}>
            Where the {inr(s.cap_mix?.total_equity || 0)} of equity inside your
            portfolio actually sits — funds and shares together.
          </p>
          <CapMixChart capMix={s.cap_mix} />
        </div>
        <div className="card">
          <h2>Allocation vs target</h2>
          <AllocationChart drift={s.drift} bucketLabels={BUCKET_LABELS}
            holdings={s.holdings} />
        </div>
      </div>

      <div className="grid">
        <div className="card">
          <h2>Suggestions</h2>
          {s.suggestions.map((g, i) => (
            <div className="sugg" key={i}>
              <span className={'dot p' + g.priority} />
              <div><b>{g.title}</b><span>{g.detail}</span></div>
            </div>
          ))}
          <p className="small muted">Educational nudges only — not investment advice.</p>
        </div>
      </div>

      {funds && funds.points && funds.points.length > 1 && (
        <div className="card">
          <h2>Mutual funds since {funds.starts}</h2>
          <p className="muted">
            What the funds were worth month by month, against what you had put
            in — reconstructed from your statement, which is why it reaches
            back further than the snapshots below.
          </p>
          <FundHistoryChart history={funds} />
        </div>
      )}

      <div className="card">
        <div className="row" style={{ justifyContent: 'space-between' }}>
          <h2>Net worth trend</h2>
          <button className="btn secondary" onClick={takeSnapshot}>
            📸 Take snapshot (monthly)
          </button>
        </div>
        <TrendChart snapshots={s.snapshots} />
      </div>
    </div>
  )
}
