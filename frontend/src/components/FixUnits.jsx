import { useEffect, useState } from 'react'
import { api, inr } from '../api'

/** Repair holdings recorded as "1 unit costing the whole invested amount".
 *
 * That shape comes from knowing what a holding is worth but not how many
 * units it is. It reads correctly until a real NAV arrives, and then one
 * unit times a NAV of ₹215 is ₹215 — a five-lakh holding shown as a total
 * loss.
 *
 * Units are the quantity the app stores; invested and current value are
 * products of it. So either number repairs a holding — the unit count, or
 * simply what it is worth today, since units = value ÷ price. The second is
 * the one people can actually read off a screen.
 */
export default function FixUnits({ reload }) {
  const [rows, setRows] = useState(null)
  const [units, setUnits] = useState({})
  const [values, setValues] = useState({})
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')

  const load = () => api.get('/api/holdings/unit-placeholders')
    .then((r) => setRows(r.holdings)).catch(() => {})
  useEffect(() => { load() }, [])

  const entries = (rows || []).map((r) => {
    const u = +units[r.holding_id] || 0
    const v = +values[r.holding_id] || 0
    if (u > 0) return { holding_id: r.holding_id, units: u }
    if (v > 0 && r.priceable) {
      return { holding_id: r.holding_id, current_value: v }
    }
    return null
  }).filter(Boolean)

  const apply = async () => {
    const payload = entries
    if (!payload.length) return
    setBusy(true)
    try {
      const r = await api.post('/api/holdings/set-units', { units: payload })
      setMsg(`Set the unit count on ${r.applied} holding(s).`
        + (r.errors.length ? ' Problems: ' + r.errors.join('; ') : ''))
      setUnits({}); setValues({})
      await load()
      reload()
    } catch (e) { setMsg(e.message) }
    setBusy(false)
  }

  if (!rows || !rows.length) return null
  const ready = entries.length

  return (
    <div className="card">
      <h2>{rows.length} holding(s) need their real unit count</h2>
      <p className="small muted" style={{ marginTop: 0 }}>
        These are recorded as <b>1 unit costing the whole invested amount</b> —
        what you get when the value was known but the unit count was not. It
        looks right until a real NAV arrives, and then one unit × ₹215 is
        ₹215, so the holding reads as a near-total loss. A share that
        genuinely costs tens of thousands is not listed here — what marks a
        placeholder is a cost per unit wildly out of line with the price, not
        a large one.
      </p>
      <p className="small muted">
        Fill in <b>either</b> column: the units you hold (your CAS calls it
        “Closing Unit Balance”), <b>or</b> just what the holding is worth
        today — read that off your fund app and the units follow from the
        price. Whichever is easier.
      </p>
      <table className="data">
        <thead><tr>
          <th>Holding</th><th className="num">Invested</th>
          <th className="num">Price now</th><th>Units you hold</th>
          <th>…or value today</th><th className="num">Would be worth</th>
        </tr></thead>
        <tbody>
          {rows.map((r) => {
            const u = +units[r.holding_id] || 0
            return (
              <tr key={r.holding_id}>
                <td>{r.name}
                  <div className="small muted">{r.identifier || 'no code'}</div>
                </td>
                <td className="num">{inr(r.invested)}</td>
                <td className="num">{r.last_price ? inr(r.last_price) : '—'}</td>
                <td>
                  <input type="number" step="any" style={{ width: 130 }}
                    placeholder="e.g. 1367.44"
                    value={units[r.holding_id] || ''}
                    onChange={(e) => setUnits({
                      ...units, [r.holding_id]: e.target.value })} />
                </td>
                <td>
                  {r.priceable ? (
                    <input type="number" step="any" style={{ width: 130 }}
                      placeholder="e.g. 350000" disabled={u > 0}
                      value={values[r.holding_id] || ''}
                      onChange={(e) => setValues({
                        ...values, [r.holding_id]: e.target.value })} />
                  ) : (
                    <span className="small muted">
                      needs a real NAV first — give it a scheme code below
                    </span>
                  )}
                </td>
                <td className="num">
                  {u > 0 && r.last_price ? inr(u * r.last_price)
                    : (+values[r.holding_id] > 0 && r.priceable
                      ? inr(+values[r.holding_id]) : '—')}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
      <div className="row" style={{ marginTop: 12 }}>
        <button className="btn" disabled={!ready || busy} onClick={apply}>
          {busy ? 'Saving…' : `Set units on ${ready} holding(s)`}
        </button>
        <span className="small muted">
          What you invested stays exactly as it is; the cost per unit is
          worked out from it, so your profit stays honest.
        </span>
      </div>
      {msg && <p className="small" style={{ marginBottom: 0 }}>{msg}</p>}
    </div>
  )
}
