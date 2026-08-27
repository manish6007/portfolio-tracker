import { useCallback, useEffect, useState } from 'react'
import { api, inr, inrShort } from '../api'
import Warnings from '../components/Warnings'

const KINDS = [
  ['term', 'Term life'], ['life', 'Life (endowment / ULIP)'],
  ['health', 'Health'], ['pa', 'Personal accident'],
  ['ci', 'Critical illness'], ['motor', 'Motor'], ['other', 'Other'],
]
const KIND_LABEL = Object.fromEntries(KINDS)

const empty = {
  kind: 'term', insurer: '', name: '', policy_number: '', covered: '',
  sum_assured: '', premium: '', frequency: 'yearly', next_due: '',
  nominee: '', notes: '',
}

function GapCard({ label, held, needed, gap, basis }) {
  const covered = needed > 0 ? Math.min(100, (held / needed) * 100) : 100
  return (
    <div className="card stat">
      <div className="label">{label}</div>
      <div className={'value ' + (gap > 0 ? 'neg' : 'pos')}>
        {gap > 0 ? `${inrShort(gap)} short` : 'covered'}
      </div>
      <div className="sub">
        holding {inrShort(held)} of {inrShort(needed)}
      </div>
      <div style={{ height: 8, background: 'var(--grid)', borderRadius: 4,
        overflow: 'hidden', marginTop: 8 }}>
        <div style={{ width: `${covered}%`, height: '100%', borderRadius: 4,
          background: gap > 0 ? 'var(--warning)' : 'var(--good)' }} />
      </div>
      {basis && <div className="sub" style={{ marginTop: 6 }}>{basis}</div>}
    </div>
  )
}

export default function Insurance({ summary, owners, reload }) {
  const [data, setData] = useState(null)
  const [f, setF] = useState({ ...empty, owner_id: '' })
  const [msg, setMsg] = useState('')

  const load = useCallback(async () => {
    try { setData(await api.get('/api/insurance')) }
    catch (e) { setMsg(e.message) }
  }, [])
  useEffect(() => { load() }, [load])

  if (!data) return <p className="muted">Loading…</p>
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value })
  const g = data.gap

  const submit = async (e) => {
    e.preventDefault()
    try {
      await api.post('/api/policies', {
        ...f, owner_id: f.owner_id ? +f.owner_id : undefined,
        sum_assured: +f.sum_assured || 0, premium: +f.premium || 0,
        next_due: f.next_due || null,
      })
      setF({ ...empty, owner_id: f.owner_id })
      load(); reload()
    } catch (er) { setMsg('Error: ' + er.message) }
  }

  return (
    <div className="grid">
      {msg && <div className="notice">{msg}</div>}

      <div className="grid cols-4">
        <GapCard label="Life cover" held={g.life_cover}
          needed={g.life_cover_needed} gap={g.life_gap} basis={g.life_basis} />
        <GapCard label="Health cover" held={g.health_cover}
          needed={g.health_floor} gap={g.health_gap}
          basis="a family floor most planners quote" />
        <div className="card stat">
          <div className="label">Policies</div>
          <div className="value">{g.policies}</div>
          <div className="sub">{inr(g.annual_premium)}/year in premiums</div>
        </div>
        <div className="card stat">
          <div className="label">Renewals next 6 months</div>
          <div className="value">{data.renewals.length}</div>
          <div className="sub">
            {inr(data.renewals.reduce((a, r) => a + r.amount, 0))} due
          </div>
        </div>
      </div>

      <div className="notice">
        Cover targets are educational conventions, not entitlements — 10–15×
        income is the usual band for life cover and this uses 12×, plus your
        outstanding debt, on the reasoning that a family left with the loan but
        not the earner is the case insurance exists for. Endowment and ULIP
        policies are counted at their stated sum assured, which flatters them:
        for the same premium a term plan usually buys many times the cover.
      </div>

      <Warnings items={(summary.warnings || []).filter(
        (w) => w.code === 'premium_not_in_cashflow'
          || w.code === 'policy_without_nominee')} />

      {data.renewals.length > 0 && (
        <div className="card">
          <h2>Renewals due</h2>
          <table className="data">
            <thead><tr>
              <th>Due</th><th>Policy</th><th className="num">Premium</th>
            </tr></thead>
            <tbody>
              {data.renewals.map((r, i) => (
                <tr key={i}>
                  <td>{r.due_date}</td><td>{r.name}</td>
                  <td className="num">{inr(r.amount)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="small muted">
            A lapsed policy is worth nothing on the day it is needed. These
            premiums are recorded here for the reminder only — the committed
            outflows on Cashflow own the cashflow number, so nothing is
            counted twice.
          </p>
        </div>
      )}

      <div className="card">
        <h2>Add a policy</h2>
        <form className="stack" onSubmit={submit}>
          <div className="row">
            <label className="field">Type
              <select value={f.kind} onChange={set('kind')}>
                {KINDS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
              </select></label>
            <label className="field">Owner
              <select value={f.owner_id} onChange={set('owner_id')}>
                <option value="">{owners[0]?.name || 'Me'}</option>
                {owners.slice(1).map((o) => (
                  <option key={o.id} value={o.id}>{o.name}</option>))}
              </select></label>
            <label className="field">Policy name
              <input required value={f.name} onChange={set('name')}
                placeholder="Term Plan" /></label>
            <label className="field">Insurer
              <input value={f.insurer} onChange={set('insurer')} /></label>
            <label className="field">Policy number
              <input value={f.policy_number} onChange={set('policy_number')}
                placeholder="masked in exports" /></label>
          </div>
          <div className="row">
            <label className="field">Who is covered
              <input value={f.covered} onChange={set('covered')}
                placeholder="Self / Family" /></label>
            <label className="field">Sum assured
              <input type="number" step="any" value={f.sum_assured}
                onChange={set('sum_assured')} /></label>
            <label className="field">Premium per payment
              <input type="number" step="any" value={f.premium}
                onChange={set('premium')} /></label>
            <label className="field">Every
              <select value={f.frequency} onChange={set('frequency')}>
                <option value="monthly">Month</option>
                <option value="quarterly">Quarter</option>
                <option value="half_yearly">6 months</option>
                <option value="yearly">Year</option>
              </select></label>
            <label className="field">Next due
              <input type="date" value={f.next_due} onChange={set('next_due')} /></label>
            <label className="field">Nominee
              <input value={f.nominee} onChange={set('nominee')} /></label>
            <button className="btn" type="submit">Add policy</button>
          </div>
        </form>
        <p className="small muted">
          Record where the policy is and who claims it — never a password or a
          security answer. This page exists so a family can find and claim
          cover, not so an account can be logged into.
        </p>
      </div>

      <div className="card">
        <h2>Policies</h2>
        {!data.policies.length ? <p className="muted">None recorded yet.</p> : (
          <div style={{ overflowX: 'auto' }}>
            <table className="data">
              <thead><tr>
                <th>Type</th><th>Policy</th><th>Insurer</th><th>Covered</th>
                <th className="num">Sum assured</th>
                <th className="num">Premium</th><th>Every</th>
                <th>Next due</th><th>Nominee</th><th></th>
              </tr></thead>
              <tbody>
                {data.policies.map((p) => (
                  <tr key={p.id}>
                    <td>{KIND_LABEL[p.kind] || p.kind}</td>
                    <td>{p.name}
                      {p.policy_number &&
                        <span className="small muted"> · {p.policy_number}</span>}</td>
                    <td>{p.insurer}</td>
                    <td>{p.covered}</td>
                    <td className="num">{inr(p.sum_assured)}</td>
                    <td className="num">{inr(p.premium)}</td>
                    <td className="small">{p.frequency_label}</td>
                    <td className="small muted">{p.next_due || '—'}</td>
                    <td>{p.nominee || (
                      <span style={{ color: 'var(--warning)' }}>not set</span>)}</td>
                    <td><button className="icon" onClick={async () => {
                      if (!window.confirm('Delete ' + p.name + '?')) return
                      await api.del('/api/policies/' + p.id); load(); reload()
                    }}>🗑</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
