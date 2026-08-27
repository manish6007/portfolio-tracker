import { useEffect, useState } from 'react'
import { api, BUCKET_LABELS } from '../api'
import Profiles from '../components/Profiles'

// Fixed colour per bucket - colour follows the bucket, never its rank.
const BUCKET_COLORS = {
  equity: 'var(--series-1)',
  debt: 'var(--series-3)',
  gold: 'var(--series-4)',
  real_estate: 'var(--series-2)',
  cash: 'var(--series-5)',
  other: 'var(--muted)',
}
const BUCKET_ORDER = ['equity', 'debt', 'gold', 'real_estate', 'cash', 'other']
const SHORT = {
  equity: 'Eq', debt: 'Debt', gold: 'Gold', real_estate: 'RE',
  cash: 'Cash', other: 'Other',
}

// Reads whatever is stored — the short code, or the long label an older
// build saved — so the dropdown shows the user's actual answer either way.
const basis = (value) => {
  const text = (value || '').toLowerCase()
  if (!text) return ''
  if (text.includes('gross')) return 'gross'
  if (text.includes('net') || text.includes('take')) return 'net'
  return ''
}

const allocText = (t) => BUCKET_ORDER
  .filter((b) => (t[b] || 0) > 0)
  .map((b) => `${SHORT[b]} ${t[b]}%`)
  .join(' \u00b7 ')

function AllocBar({ targets }) {
  const parts = BUCKET_ORDER.filter((b) => (targets[b] || 0) > 0)
  return (
    <div style={{ display: 'flex', gap: 2, height: 8, margin: '6px 0 8px' }}>
      {parts.map((b) => (
        <div key={b} title={`${BUCKET_LABELS[b]} ${targets[b]}%`}
          style={{
            width: `${targets[b]}%`, background: BUCKET_COLORS[b],
            borderRadius: 3,
          }} />
      ))}
    </div>
  )
}

export default function Settings({ owners, reload }) {
  const [settings, setSettings] = useState(null)
  const [newOwner, setNewOwner] = useState('')
  const [msg, setMsg] = useState('')
  const [presets, setPresets] = useState([])
  const [age, setAge] = useState('')

  useEffect(() => {
    api.get('/api/settings').then((s) => { setSettings(s); setAge(s.age || '') })
  }, [])

  useEffect(() => {
    const valid = age !== '' && +age >= 10 && +age <= 100
    api.get('/api/targets/presets' + (valid ? '?age=' + +age : ''))
      .then((d) => setPresets(d.presets))
      .catch(() => setPresets([]))
  }, [age])

  if (!settings) return <p className="muted">Loading…</p>

  const targets = settings.targets
  const targetSum = Object.values(targets).reduce((a, b) => a + (+b || 0), 0)
  const offTotal = Math.abs(targetSum - 100) > 0.5

  const save = async () => {
    await api.put('/api/settings', { ...settings, age })
    setSettings({ ...settings, targets_customized: true })
    setMsg('Saved.')
    reload()
  }

  const applyPreset = async (preset) => {
    const payload = { targets: preset.targets }
    if (age !== '') payload.age = age
    await api.put('/api/settings', payload)
    setSettings({ ...settings, targets: preset.targets, targets_customized: true })
    setMsg('Applied the "' + preset.name + '" allocation. Tweak below and save '
           + 'if you want something different.')
    reload()
  }

  const addOwner = async (e) => {
    e.preventDefault()
    try {
      await api.post('/api/owners', { name: newOwner })
      setNewOwner('')
      reload()
    } catch (err) { setMsg('Error: ' + err.message) }
  }

  const loadDemo = async () => {
    await api.post('/api/demo-data')
    setMsg('Demo data loaded (all names start with DEMO — delete them from Portfolio when done exploring).')
    reload()
  }

  return (
    <div className="grid">
      {msg && <div className="notice">{msg}</div>}

      <div className="card">
        <h2>Household members</h2>
        <div className="row">
          {owners.map((o) => (
            <span key={o.id} className="card" style={{ padding: '6px 12px' }}>
              {o.name}
              <button className="icon" title="Delete (must have no holdings)"
                onClick={async () => {
                  try { await api.del('/api/owners/' + o.id); reload() }
                  catch (err) { setMsg('Error: ' + err.message) }
                }}>✕</button>
            </span>
          ))}
          <form className="row" onSubmit={addOwner}>
            <input placeholder="Add member (e.g. Wife)" value={newOwner}
              onChange={(e) => setNewOwner(e.target.value)} />
            <button className="btn secondary" type="submit">Add</button>
          </form>
        </div>
      </div>

      <div className="card">
        <h2>Target asset allocation</h2>
        {!settings.targets_customized && (
          <div className="notice">
            You haven’t chosen targets yet, so the dashboard is comparing
            your portfolio against generic placeholder numbers. Pick a starting
            point below — it drives every rebalancing suggestion.
          </div>
        )}

        <p className="small muted" style={{ marginTop: 0 }}>
          Starting points commonly used by Indian fee-only planners. Educational
          conventions, not advice — edit anything below before saving.
        </p>

        <div className="row" style={{ marginBottom: 12 }}>
          <label className="field">Your age (unlocks the age-based suggestion)
            <input type="number" min="10" max="100" style={{ width: 130 }}
              value={age} placeholder="e.g. 38"
              onChange={(e) => setAge(e.target.value)} />
          </label>
        </div>

        <div className="grid cols-4">
          {presets.map((p) => (
            <div className="card" key={p.key}
              style={p.recommended ? { borderColor: 'var(--accent)' } : {}}>
              <b>{p.name}{p.recommended ? ' ★' : ''}</b>
              <p className="small muted" style={{ minHeight: 48 }}>{p.detail}</p>
              <AllocBar targets={p.targets} />
              <p className="small muted">{allocText(p.targets)}</p>
              <button className="btn secondary" style={{ width: '100%' }}
                onClick={() => applyPreset(p)}>Apply</button>
            </div>
          ))}
        </div>

        <h2 style={{ marginTop: 18 }}>Fine-tune (%)</h2>
        <div className="row">
          {Object.keys(BUCKET_LABELS).map((b) => (
            <label className="field" key={b}>{BUCKET_LABELS[b]}
              <input type="number" step="any" style={{ width: 90 }}
                value={targets[b] ?? 0}
                onChange={(e) => setSettings({
                  ...settings,
                  targets: { ...targets, [b]: +e.target.value || 0 },
                })} />
            </label>
          ))}
        </div>
        <div className="row" style={{ alignItems: 'center' }}>
          <button className="btn" onClick={save} disabled={offTotal}>
            Save targets
          </button>
          <span className={'small ' + (offTotal ? '' : 'muted')}
            style={offTotal ? { color: 'var(--critical)' } : {}}>
            Total: {targetSum.toFixed(0)}%
            {offTotal && ' — must add up to 100% before saving'}
          </span>
        </div>
      </div>

      <div className="card">
        <h2>Planning inputs</h2>
        <div className="row">
          {[['emergency_fund_target', 'Emergency fund target (₹)'],
            ['savings_float', 'Savings account float (₹, keep this much idle)'],
            ['tax_80c_used', '80C used this FY (₹, blank = not tracked)'],
            ['tax_80ccd1b_used', 'NPS 80CCD(1B) used this FY (₹)']].map(([k, label]) => (
              <label className="field" key={k}>{label}
                <input type="number" step="any" style={{ width: 200 }}
                  value={settings[k]}
                  onChange={(e) => setSettings({ ...settings, [k]: e.target.value })} />
              </label>
            ))}
        </div>
        <div className="row">
          <label className="field">Salary figure you enter is
            {/* A short code, not the label. Storing the display string
                meant "net take-home (after tax and deductions)" never
                equalled "net", so the app went on saying it was not set
                however many times it was. Old saved values still read
                correctly — the backend normalises by shape. */}
            <select value={basis(settings.income_basis)}
              onChange={(e) => setSettings({ ...settings, income_basis: e.target.value })}>
              <option value="">Unspecified</option>
              <option value="net">Net take-home (after tax &amp; deductions)</option>
              <option value="gross">Gross (before tax &amp; deductions)</option>
            </select>
          </label>
        </div>
        <p className="small muted">
          Stating this stops a reviewer mistaking gross pay for spendable
          income — the single most common reason a plan does not reconcile.
        </p>
        <div className="row" style={{ marginTop: 12 }}>
          <button className="btn" onClick={save}>Save settings</button>
        </div>
      </div>

      <Profiles />

      <div className="card">
        <h2>Demo data</h2>
        <p className="muted small">Loads a realistic sample household (holdings
          named "DEMO …") so you can explore every screen before entering real data.</p>
        <div className="row">
          <button className="btn secondary" onClick={loadDemo}>Load demo data</button>
          <button className="btn secondary" onClick={async () => {
            const r = await api.del('/api/demo-data')
            setMsg('Removed ' + r.removed + ' demo records. Your own data was untouched.')
            reload()
          }}>Clear demo data</button>
        </div>
      </div>

      <div className="card">
        <h2>Danger zone</h2>
        <p className="muted small">Erases every holding, loan, entry, snapshot
          and member — a completely fresh start. Settings/targets are kept.
          (Equivalent to deleting backend/portfolio.db.)</p>
        <button className="btn danger" onClick={async () => {
          if (!window.confirm('Erase ALL data? This cannot be undone.')) return
          if (window.prompt('Type ERASE to confirm') !== 'ERASE') return
          await api.post('/api/reset', { confirm: 'ERASE' })
          setMsg('All data erased.')
          reload()
        }}>Erase ALL data</button>
      </div>
    </div>
  )
}
