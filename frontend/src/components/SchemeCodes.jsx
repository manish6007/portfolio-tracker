import { useEffect, useState } from 'react'
import { api, inr } from '../api'

/** Give every fund the AMFI code that prices it.
 *
 * Nobody knows their scheme codes, so a portfolio typed in by hand has a
 * dozen funds stuck at their purchase price. The app proposes matches and
 * the user applies them — it never picks silently, because every fund
 * exists as Direct/Regular × Growth/IDCW with genuinely different NAVs, and
 * a wrong pick produces a number that looks entirely reasonable.
 */
export default function SchemeCodes({ reload }) {
  const [state, setState] = useState(null)
  const [chosen, setChosen] = useState({})
  const [plan, setPlan] = useState('direct')
  const [option, setOption] = useState('growth')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')
  // Per-row search, for funds whose recorded name is a note to self rather
  // than a fund — nothing can match those, and only the person looking at
  // the screen knows what they really are.
  const [query, setQuery] = useState({})
  const [found, setFound] = useState({})
  const [adopt, setAdopt] = useState({})

  const load = async (p = plan, o = option) => {
    setMsg('')
    try {
      const r = await api.get(
        `/api/amfi/suggest-codes?plan=${p}&option=${o}`)
      setState(r)
      // Pre-tick only the unambiguous ones; the rest are a real choice.
      const pick = {}
      for (const h of r.holdings) {
        if (h.confident && h.candidates.length) {
          pick[h.holding_id] = h.candidates[0].code
        }
      }
      setChosen(pick)
    } catch (e) { setMsg(e.message) }
  }
  useEffect(() => { load() }, [])   // eslint-disable-line react-hooks/exhaustive-deps

  const repick = (p, o) => { setPlan(p); setOption(o); load(p, o) }

  const search = async (id) => {
    const q = (query[id] || '').trim()
    if (q.length < 3) return
    const r = await api.get(`/api/amfi/candidates?q=${encodeURIComponent(q)}`
      + `&plan=${plan}&option=${option}`)
    setFound({ ...found, [id]: r.candidates })
    if (r.candidates.length) {
      setChosen({ ...chosen, [id]: r.candidates[0].code })
    }
  }

  const apply = async () => {
    const assignments = Object.entries(chosen)
      .filter(([, code]) => code)
      .map(([id, code]) => ({ holding_id: +id, scheme_code: code,
        adopt_name: !!adopt[id] }))
    if (!assignments.length) return
    setBusy(true)
    try {
      const r = await api.post('/api/amfi/apply-codes', { assignments })
      setMsg(`Set the scheme code on ${r.applied} fund(s) and priced them.`
        + (r.renamed ? ` Renamed ${r.renamed} to their scheme names.` : '')
        + (r.derived_units?.length
          ? ` Units worked out from the value for ${r.derived_units.length}.`
          : '')
        + (r.errors.length ? ' Problems: ' + r.errors.join('; ') : ''))
      setFound({}); setQuery({}); setAdopt({})
      await load()
      reload()
    } catch (e) { setMsg(e.message) }
    setBusy(false)
  }

  if (!state) return null
  if (state.amfi_status && state.amfi_status !== 'ok') {
    return (
      <div className="card">
        <h2>Match funds to AMFI codes</h2>
        <p className="small muted" style={{ marginBottom: 0 }}>
          AMFI’s list could not be read, so there is nothing to match
          against. Privacy → Test connection says why.
        </p>
      </div>
    )
  }
  if (!state.holdings.length) return null

  const ticked = Object.values(chosen).filter(Boolean).length

  return (
    <div className="card">
      <h2>{state.holdings.length} fund(s) have no AMFI scheme code</h2>
      <p className="small muted" style={{ marginTop: 0 }}>
        Without one they stay frozen at the price you entered. If a name is
        a note to self rather than a fund, search AMFI for the real one. These are the
        closest matches by name — <b>check the plan and option</b> before
        applying: every fund exists as Direct and Regular, Growth and IDCW,
        and their NAVs genuinely differ. Where a fund already has a price
        recorded, the scheme whose NAV agrees with it is preferred, which is
        the surest way to tell Direct from Regular.
      </p>

      <div className="row" style={{ marginBottom: 10 }}>
        <label className="field">I normally hold
          <select value={plan}
            onChange={(e) => repick(e.target.value, option)}>
            <option value="direct">Direct plan</option>
            <option value="regular">Regular plan</option>
          </select>
        </label>
        <label className="field">with
          <select value={option}
            onChange={(e) => repick(plan, e.target.value)}>
            <option value="growth">Growth</option>
            <option value="idcw">IDCW / dividend</option>
          </select>
        </label>
        <span className="small muted" style={{ flex: 1, minWidth: 220 }}>
          Only a tie-breaker — anything the fund’s own name says wins.
        </span>
      </div>

      <table className="data">
        <thead><tr>
          <th></th><th>Your fund</th><th>Matches</th><th className="num">NAV</th>
        </tr></thead>
        <tbody>
          {state.holdings.map((h) => (
            <tr key={h.holding_id}>
              <td>
                <input type="checkbox" disabled={!h.candidates.length}
                  checked={!!chosen[h.holding_id]}
                  onChange={(e) => setChosen({
                    ...chosen,
                    [h.holding_id]: e.target.checked
                      ? (chosen[h.holding_id] || h.candidates[0]?.code) : '',
                  })} />
              </td>
              <td>
                {h.name}
                <div className="small muted">
                  {h.identifier ? 'currently ' + h.identifier : 'no identifier'}
                  {h.last_price > 0 && ' · priced at ' + inr(h.last_price)}
                </div>
              </td>
              <td>
                {h.candidates.length === 0 && !(found[h.holding_id] || []).length ? (
                  <>
                    <span className="small muted">{h.why}</span>
                    <div className="row" style={{ marginTop: 6 }}>
                      <input style={{ width: 300 }}
                        placeholder="type the real fund name…"
                        value={query[h.holding_id] || ''}
                        onChange={(e) => setQuery({
                          ...query, [h.holding_id]: e.target.value })}
                        onKeyDown={(e) => e.key === 'Enter'
                          && search(h.holding_id)} />
                      <button className="btn secondary" type="button"
                        onClick={() => search(h.holding_id)}>Search AMFI</button>
                    </div>
                    {found[h.holding_id] && !found[h.holding_id].length && (
                      <div className="small muted">
                        Nothing matched that either — try fewer words.
                      </div>
                    )}
                  </>
                ) : (
                  <>
                    <select value={chosen[h.holding_id] || ''}
                      style={{ maxWidth: 460 }}
                      onChange={(e) => setChosen({
                        ...chosen, [h.holding_id]: e.target.value })}>
                      <option value="">— leave it alone —</option>
                      {(found[h.holding_id] || h.candidates).map((c) => (
                        <option key={c.code} value={c.code}>
                          {c.name} ({c.code})
                          {c.price_gap_pct !== null && c.price_gap_pct <= 2
                            ? ' — NAV agrees' : ''}
                        </option>
                      ))}
                    </select>
                    {!found[h.holding_id] && (
                      <div className="small"
                        style={{ color: h.confident
                          ? 'var(--muted)' : 'var(--serious)' }}>
                        {h.why}
                      </div>
                    )}
                    {chosen[h.holding_id] && (
                      <label className="small muted"
                        style={{ display: 'block', marginTop: 4 }}>
                        <input type="checkbox" checked={!!adopt[h.holding_id]}
                          onChange={(e) => setAdopt({
                            ...adopt, [h.holding_id]: e.target.checked })} />
                        {' '}also rename this holding to the scheme’s own name
                      </label>
                    )}
                  </>
                )}
              </td>
              <td className="num">
                {chosen[h.holding_id]
                  ? inr((found[h.holding_id] || h.candidates).find(
                    (c) => c.code === chosen[h.holding_id])?.nav)
                  : '—'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <div className="row" style={{ marginTop: 12 }}>
        <button className="btn" disabled={!ticked || busy} onClick={apply}>
          {busy ? 'Applying…' : `Apply ${ticked} code(s)`}
        </button>
        <span className="small muted">
          Nothing changes until you press this. The folio number you had is
          kept — it moves into the holding’s details.
        </span>
      </div>
      {msg && <p className="small" style={{ marginBottom: 0 }}>{msg}</p>}
    </div>
  )
}
