import { api, BUCKET_LABELS, inr } from '../api'
import { AllocationChart, CapMixChart, DonutByClass, OwnerBar, TrendChart } from '../components/Charts'
import Warnings from '../components/Warnings'

export default function Dashboard({ summary, meta, reload }) {
  const s = summary
  const takeSnapshot = async () => { await api.post('/api/snapshots'); reload() }
  const empty = !s.holdings.length

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
