import { useCallback, useEffect, useState } from 'react'
import { api, inr } from '../api'

// A purchase that does not say where the buyer would be wrong is a purchase
// with no plan, so the stop is asked for on the way in rather than offered
// as an afterthought. It can still be left empty deliberately.
const EMPTY_BUY = {
  name: '', identifier: '', date: today(), units: '', price: '',
  charges: '', stoploss: '', sleeve: 'core', notes: '',
}

function today() {
  return new Date().toISOString().slice(0, 10)
}

function num(v) {
  const n = parseFloat(v)
  return Number.isFinite(n) ? n : 0
}

function Money({ value, plain }) {
  if (plain) return inr(value)
  const cls = value > 0 ? 'good' : value < 0 ? 'serious' : ''
  return <span style={{ color: cls ? `var(--${cls})` : undefined }}>
    {value > 0 ? '+' : ''}{inr(value)}
  </span>
}

export default function Journal({ owners, reload }) {
  const [data, setData] = useState(null)
  const [msg, setMsg] = useState('')
  const [buy, setBuy] = useState(EMPTY_BUY)
  const [buyInto, setBuyInto] = useState('')
  const [owner, setOwner] = useState('')
  const [sellFor, setSellFor] = useState(null)
  const [sell, setSell] = useState(null)
  const [capital, setCapital] = useState(
    { date: today(), direction: 'in', amount: '', notes: '' })
  const [showClosed, setShowClosed] = useState(false)
  const [editLot, setEditLot] = useState(null)

  const load = useCallback(async () => {
    try { setData(await api.get('/api/journal')) } catch (e) {
      setMsg('Error: ' + e.message)
    }
  }, [])

  useEffect(() => { load() }, [load])

  // The journal writes the same holdings every other page reads, so the
  // whole app is refreshed after a write, not just this table.
  const refreshAll = async () => { await load(); await reload() }

  const submitBuy = async (e) => {
    e.preventDefault()
    setMsg('')
    try {
      const body = {
        date: buy.date, units: num(buy.units), price: num(buy.price),
        charges: num(buy.charges), stoploss: num(buy.stoploss),
        sleeve: buy.sleeve, notes: buy.notes,
      }
      if (buyInto) body.holding_id = Number(buyInto)
      else {
        body.name = buy.name.trim()
        body.identifier = buy.identifier.trim()
        body.asset_class = 'stock'
        if (owner) body.owner = owner
      }
      await api.post('/api/journal/buy', body)
      setBuy({ ...EMPTY_BUY, date: buy.date })
      setBuyInto('')
      setMsg('Purchase recorded.')
      await refreshAll()
    } catch (e) { setMsg('Error: ' + e.message) }
  }

  const submitSell = async (e) => {
    e.preventDefault()
    setMsg('')
    try {
      const r = await api.post('/api/journal/sell', {
        holding_id: sellFor.holding_id, date: sell.date,
        units: num(sell.units), price: num(sell.price),
        charges: num(sell.charges), reason: sell.reason, notes: sell.notes,
      })
      setSellFor(null)
      setMsg(`Sold. Realised ${inr(r.realised)}.`)
      await refreshAll()
    } catch (e) { setMsg('Error: ' + e.message) }
  }

  const saveLot = async (e) => {
    e.preventDefault()
    setMsg('')
    try {
      await api.put('/api/journal/lots/' + editLot.id, {
        date: editLot.date, units: num(editLot.units),
        price: num(editLot.price), charges: num(editLot.charges),
        stoploss: num(editLot.stoploss), notes: editLot.notes,
      })
      setEditLot(null)
      setMsg('Purchase corrected.')
      await refreshAll()
    } catch (e) { setMsg('Error: ' + e.message) }
  }

  const removeLot = async (lot) => {
    if (!window.confirm(`Delete the purchase of ${lot.remaining} units at `
      + `${inr(lot.cost_per_unit)}? This cannot be undone.`)) return
    setMsg('')
    try {
      await api.del('/api/journal/lots/' + lot.id)
      setEditLot(null)
      setMsg('Purchase removed.')
      await refreshAll()
    } catch (e) { setMsg('Error: ' + e.message) }
  }

  const undoTrade = async (t) => {
    if (!window.confirm(`Undo the sale of ${t.units} ${t.name}? The units go `
      + 'back to the parcel they came from.')) return
    setMsg('')
    try {
      await api.del('/api/journal/trades/' + t.id)
      setMsg('Sale undone.')
      await refreshAll()
    } catch (e) { setMsg('Error: ' + e.message) }
  }

  const submitCapital = async (e) => {
    e.preventDefault()
    setMsg('')
    try {
      await api.post('/api/journal/capital', {
        date: capital.date, direction: capital.direction,
        amount: num(capital.amount), notes: capital.notes,
        ...(owner ? { owner } : {}),
      })
      setCapital({ ...capital, amount: '', notes: '' })
      await load()
    } catch (e) { setMsg('Error: ' + e.message) }
  }

  if (!data) return <p className="muted">Loading…</p>

  const openSell = (p) => {
    setSellFor(p)
    setSell({ date: today(), units: '', price: p.last_price || '',
      charges: '', reason: 'target', notes: '' })
  }

  return (
    <>
      <h2>Journal</h2>
      <p className="muted">
        Every purchase and sale of a share, kept as it happened. Positions,
        cost and realised gains here are the same numbers the Dashboard and
        Portfolio pages report — this is where they are written.
      </p>
      {msg && <div className="notice">{msg}</div>}

      <div style={{ overflowX: 'auto' }}>
        <table>
          <thead>
            <tr>
              <th>Portfolio</th>
              <th className="num" title="What the units still held cost, charges included">
                Deployed
              </th>
              <th className="num">Value</th>
              <th className="num" title="Profit on what is still held">
                Unrealised
              </th>
              <th className="num" title="Profit on positions already closed">
                Realised
              </th>
              <th className="num">Total P&amp;L</th>
              <th className="num" title="Unrealised, against what is deployed">
                Return
              </th>
            </tr>
          </thead>
          <tbody>
            {data.by_sleeve.sleeves.map((r) => (
              /* An unassigned row is only worth showing when it holds
                 something — otherwise it is a permanent empty reproach. */
              (r.deployed || r.realised || r.sleeve !== '') && (
                <tr key={r.sleeve || 'none'}>
                  <td>{r.label}</td>
                  <td className="num">{inr(r.deployed)}</td>
                  <td className="num">{inr(r.value)}</td>
                  <td className="num"><Money value={r.unrealised} /></td>
                  <td className="num">
                    <Money value={r.realised} />
                    {r.trades > 0 && (
                      <div className="small muted">
                        {r.trades} closed · {r.wins} in profit
                      </div>
                    )}
                  </td>
                  <td className="num"><Money value={r.total_pnl} /></td>
                  <td className="num">{r.pct}%</td>
                </tr>
              )
            ))}
            <tr style={{ fontWeight: 600 }}>
              <td>{data.by_sleeve.total.label}</td>
              <td className="num">{inr(data.by_sleeve.total.deployed)}</td>
              <td className="num">{inr(data.by_sleeve.total.value)}</td>
              <td className="num">
                <Money value={data.by_sleeve.total.unrealised} />
              </td>
              <td className="num">
                <Money value={data.by_sleeve.total.realised} />
              </td>
              <td className="num">
                <Money value={data.by_sleeve.total.total_pnl} />
              </td>
              <td className="num">{data.by_sleeve.total.pct}%</td>
            </tr>
          </tbody>
        </table>
      </div>
      <p className="small muted">
        Core is the long-term position you add to each month; satellite is the
        shorter technical bet. They are kept apart because they are judged
        against different promises — a run of satellite losses inside one
        combined number quietly eats the return the core actually earned.
        Deployed is what the units you still hold cost, charges included, so
        selling returns capital rather than leaving it counted forever.
      </p>

      {/* Recording a purchase ------------------------------------------- */}
      <h3>Record a purchase</h3>
      <form onSubmit={submitBuy} className="row wrap" style={{ gap: 8 }}>
        <select value={buyInto} onChange={(e) => setBuyInto(e.target.value)}
          title="Add to a position you already hold, or leave blank to open a new one">
          <option value="">— new position —</option>
          {data.positions.map((p) => (
            <option key={p.holding_id} value={p.holding_id}>{p.name}</option>
          ))}
        </select>
        {!buyInto && (
          <>
            <input placeholder="Company" required={!buyInto} value={buy.name}
              onChange={(e) => setBuy({ ...buy, name: e.target.value })} />
            <input placeholder="NSE symbol" value={buy.identifier} style={{ width: 120 }}
              title="The ticker, e.g. RELIANCE — this is what prices it and what classifies its size"
              onChange={(e) => setBuy({ ...buy, identifier: e.target.value })} />
            {owners.length > 1 && (
              <select value={owner} onChange={(e) => setOwner(e.target.value)}>
                <option value="">— owner —</option>
                {owners.map((o) => <option key={o.id}>{o.name}</option>)}
              </select>
            )}
          </>
        )}
        <select value={buy.sleeve} title="Core is the long-term bet you add to each month; satellite is the shorter technical trade"
          onChange={(e) => setBuy({ ...buy, sleeve: e.target.value })}>
          {data.sleeves.map((sl) => (
            <option key={sl.value} value={sl.value}>{sl.label}</option>
          ))}
        </select>
        <input type="date" value={buy.date}
          onChange={(e) => setBuy({ ...buy, date: e.target.value })} />
        <input placeholder="Quantity" type="number" step="any" required style={{ width: 100 }}
          value={buy.units}
          onChange={(e) => setBuy({ ...buy, units: e.target.value })} />
        <input placeholder="Price" type="number" step="any" required style={{ width: 100 }}
          value={buy.price}
          onChange={(e) => setBuy({ ...buy, price: e.target.value })} />
        <input placeholder="Charges" type="number" step="any" style={{ width: 100 }}
          title="Brokerage, STT and the rest. It goes into the cost, because a return measured against the quoted price is a return nobody earned."
          value={buy.charges}
          onChange={(e) => setBuy({ ...buy, charges: e.target.value })} />
        <input placeholder="Stop-loss" type="number" step="any" style={{ width: 110 }}
          title="The price you would accept being wrong at. Recorded now because a stop decided after the fall is not a stop."
          value={buy.stoploss}
          onChange={(e) => setBuy({ ...buy, stoploss: e.target.value })} />
        <input placeholder="Notes — why this one?" style={{ flex: 1, minWidth: 160 }}
          value={buy.notes}
          onChange={(e) => setBuy({ ...buy, notes: e.target.value })} />
        <button className="primary" type="submit">Buy</button>
      </form>

      {/* Open positions -------------------------------------------------- */}
      <h3>Open positions</h3>
      {!data.positions.length ? (
        <p className="muted">
          Nothing held yet. Record a purchase above, or import a statement on
          the Portfolio page.
        </p>
      ) : (
        <div style={{ overflowX: 'auto' }}>
          <table>
            <thead>
              <tr>
                <th>Company</th><th>Owner</th><th>Portfolio</th><th>Size</th>
                <th className="num">Units</th><th className="num">Avg cost</th>
                <th className="num">Price</th><th className="num">Value</th>
                <th className="num">Open P&amp;L</th><th>Parcels</th><th></th>
              </tr>
            </thead>
            <tbody>
              {data.positions.map((p) => (
                <tr key={p.holding_id}>
                  <td>{p.name}<div className="small muted">{p.identifier}</div></td>
                  <td>{p.owner}</td>
                  <td>
                    {p.sleeve === 'mixed' ? (
                      <span className="small" title="This company is held in both sleeves — set it per purchase, not per position">
                        Mixed
                      </span>
                    ) : (
                      <select value={p.sleeve} style={{ padding: '2px 4px', fontSize: 12,
                        borderColor: p.sleeve ? undefined : 'var(--serious)' }}
                        title={p.sleeve ? '' : 'Not filed yet — this position sits outside both sleeve totals'}
                        onChange={async (ev) => {
                          await api.put('/api/journal/' + p.holding_id + '/sleeve',
                            { sleeve: ev.target.value })
                          load()
                        }}>
                        {!p.sleeve && <option value="">not set</option>}
                        {data.sleeves.map((sl) => (
                          <option key={sl.value} value={sl.value}>{sl.label}</option>
                        ))}
                      </select>
                    )}
                  </td>
                  <td className="small">{p.cap_label || '—'}</td>
                  <td className="num">{p.units}</td>
                  <td className="num">{inr(p.avg_cost)}</td>
                  <td className="num">{inr(p.last_price)}</td>
                  <td className="num">{inr(p.current_value)}</td>
                  <td className="num"><Money value={p.open_pnl} /></td>
                  <td className="small">
                    {p.lots.map((l) => (
                      <div key={l.id} title={l.notes}>
                        {l.remaining} @ {inr(l.cost_per_unit)}
                        {l.date_known
                          ? ' · ' + l.date
                          : ' · date not recorded'}
                        {l.stoploss ? ` · SL ${inr(l.stoploss)}` : ''}
                        <button className="icon" title="Correct this purchase"
                          style={{ marginLeft: 4 }}
                          onClick={() => setEditLot({
                            id: l.id, name: p.name, date: l.date,
                            units: l.units, price: l.price,
                            charges: l.charges, stoploss: l.stoploss,
                            notes: l.notes, remaining: l.remaining,
                            cost_per_unit: l.cost_per_unit,
                          })}>✎</button>
                      </div>
                    ))}
                  </td>
                  <td>
                    <button onClick={() => openSell(p)}>Sell</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Correcting a purchase ------------------------------------------- */}
      {editLot && (
        <div className="notice">
          <form onSubmit={saveLot} className="row wrap" style={{ gap: 8 }}>
            <b style={{ minWidth: 140 }}>Correct {editLot.name}</b>
            <input type="date" value={editLot.date}
              onChange={(e) => setEditLot({ ...editLot, date: e.target.value })} />
            <input placeholder="Quantity" type="number" step="any" required
              style={{ width: 100 }} value={editLot.units} autoFocus
              title="The quantity bought. It cannot be cut below what has already been sold out of this parcel."
              onChange={(e) => setEditLot({ ...editLot, units: e.target.value })} />
            <input placeholder="Price" type="number" step="any" required
              style={{ width: 100 }} value={editLot.price}
              onChange={(e) => setEditLot({ ...editLot, price: e.target.value })} />
            <input placeholder="Charges" type="number" step="any"
              style={{ width: 100 }} value={editLot.charges}
              onChange={(e) => setEditLot({ ...editLot, charges: e.target.value })} />
            <input placeholder="Stop-loss" type="number" step="any"
              style={{ width: 110 }} value={editLot.stoploss}
              onChange={(e) => setEditLot({ ...editLot, stoploss: e.target.value })} />
            <input placeholder="Notes" style={{ flex: 1, minWidth: 140 }}
              value={editLot.notes}
              onChange={(e) => setEditLot({ ...editLot, notes: e.target.value })} />
            <button className="primary" type="submit">Save</button>
            <button type="button" onClick={() => setEditLot(null)}>Cancel</button>
            <button type="button" style={{ color: 'var(--serious)' }}
              onClick={() => removeLot(editLot)}>Delete</button>
          </form>
          <p className="small muted" style={{ marginBottom: 0 }}>
            Everything follows the correction: units held, average cost, the
            cashflow XIRR reads, and the profit on any part of this parcel
            already sold — which was measured against the price you are
            changing.
          </p>
        </div>
      )}

      {/* Selling --------------------------------------------------------- */}
      {sellFor && (
        <div className="notice">
          <form onSubmit={submitSell} className="row wrap" style={{ gap: 8 }}>
            <b style={{ minWidth: 140 }}>Sell {sellFor.name}</b>
            <span className="small muted">{sellFor.units} held</span>
            <input type="date" value={sell.date}
              onChange={(e) => setSell({ ...sell, date: e.target.value })} />
            <input placeholder="Quantity" type="number" step="any" required
              style={{ width: 100 }} value={sell.units} autoFocus
              onChange={(e) => setSell({ ...sell, units: e.target.value })} />
            <input placeholder="Price" type="number" step="any" required
              style={{ width: 100 }} value={sell.price}
              onChange={(e) => setSell({ ...sell, price: e.target.value })} />
            <input placeholder="Charges" type="number" step="any"
              style={{ width: 100 }} value={sell.charges}
              onChange={(e) => setSell({ ...sell, charges: e.target.value })} />
            <select value={sell.reason} required
              title="Why you are getting out. This is the only field that cannot be reconstructed later."
              onChange={(e) => setSell({ ...sell, reason: e.target.value })}>
              {data.reasons.map((r) => (
                <option key={r.value} value={r.value}>{r.label}</option>
              ))}
            </select>
            <input placeholder="Notes" style={{ flex: 1, minWidth: 140 }}
              value={sell.notes}
              onChange={(e) => setSell({ ...sell, notes: e.target.value })} />
            <button className="primary" type="submit">Sell</button>
            <button type="button" onClick={() => setSellFor(null)}>Cancel</button>
          </form>
          <p className="small muted" style={{ marginBottom: 0 }}>
            Units come off the oldest parcel first, which is the order the tax
            computation assumes.
          </p>
        </div>
      )}

      {/* What exits actually did ----------------------------------------- */}
      <h3>Closed trades</h3>
      {!data.trades.length ? (
        <p className="muted">
          Nothing sold yet. Once there is, this is where you find out whether
          your stop-losses helped.
        </p>
      ) : (
        <>
          <div className="cards">
            <div className="card">
              <div className="label">Exited on a stop</div>
              <div className="value">
                <Money value={data.stoploss.stopped.realised} />
              </div>
              <div className="small muted">
                {data.stoploss.stopped.trades} trades ·{' '}
                {data.stoploss.stopped.wins} in profit
              </div>
            </div>
            <div className="card">
              <div className="label">Every other exit</div>
              <div className="value">
                <Money value={data.stoploss.other_exits.realised} />
              </div>
              <div className="small muted">
                {data.stoploss.other_exits.trades} trades ·{' '}
                {data.stoploss.other_exits.wins} in profit
              </div>
            </div>
          </div>
          <button onClick={() => setShowClosed(!showClosed)}>
            {showClosed ? 'Hide' : 'Show'} the {data.trades.length} closed
            {data.trades.length === 1 ? ' trade' : ' trades'}
          </button>
          {showClosed && (
            <div style={{ overflowX: 'auto' }}>
              <table>
                <thead>
                  <tr>
                    <th>Company</th><th>Portfolio</th><th>Bought</th><th>Sold</th>
                    <th className="num">Units</th><th className="num">Buy</th>
                    <th className="num">Sell</th><th className="num">Realised</th>
                    <th>Why</th><th>Gain</th><th></th>
                  </tr>
                </thead>
                <tbody>
                  {data.trades.map((t) => (
                    <tr key={t.id}>
                      <td>{t.name}</td>
                      <td className="small">{t.sleeve_label}</td>
                      <td className="small">{t.buy_date}</td>
                      <td className="small">{t.sell_date}</td>
                      <td className="num">{t.units}</td>
                      <td className="num">{inr(t.buy_price)}</td>
                      <td className="num">{inr(t.sell_price)}</td>
                      <td className="num"><Money value={t.realised} /></td>
                      <td className="small">{t.reason_label}</td>
                      <td className="small">
                        {t.gain_type === 'unknown'
                          ? <span title="The purchase date was never recorded, so the holding period cannot be known.">not known</span>
                          : t.gain_type.toUpperCase()}
                      </td>
                      <td>
                        <button className="icon" title="Undo this sale"
                          onClick={() => undoTrade(t)}>✕</button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="small muted">
                An indication for your own records, not tax advice. Debt funds
                bought after March 2023 are taxed at slab rates whatever the
                holding period.
              </p>
            </div>
          )}
        </>
      )}

      {/* Capital ---------------------------------------------------------- */}
      <h3>Cash moved in and out</h3>
      <p className="muted">
        Money crossing between your bank and your investing pot. This is a
        different question from <i>deployed</i> above, which is what your open
        positions cost — the two differ by whatever has arrived but is not yet
        invested. Optional: leave it empty and the deployed figure above is
        still right.
      </p>
      <form onSubmit={submitCapital} className="row wrap" style={{ gap: 8 }}>
        <input type="date" value={capital.date}
          onChange={(e) => setCapital({ ...capital, date: e.target.value })} />
        <select value={capital.direction}
          onChange={(e) => setCapital({ ...capital, direction: e.target.value })}>
          <option value="in">Invested</option>
          <option value="out">Withdrawn</option>
        </select>
        <input placeholder="Amount" type="number" step="any" required
          style={{ width: 130 }} value={capital.amount}
          onChange={(e) => setCapital({ ...capital, amount: e.target.value })} />
        <input placeholder="Notes" style={{ flex: 1, minWidth: 140 }}
          value={capital.notes}
          onChange={(e) => setCapital({ ...capital, notes: e.target.value })} />
        <button type="submit">Add</button>
      </form>
      {data.capital.flows.length > 0 && (
        <table>
          <thead>
            <tr>
              <th>Date</th><th>Owner</th><th></th>
              <th className="num">Amount</th><th>Notes</th><th></th>
            </tr>
          </thead>
          <tbody>
            {data.capital.flows.map((f) => (
              <tr key={f.id}>
                <td className="small">{f.date}</td>
                <td className="small">{f.owner}</td>
                <td className="small">
                  {f.direction === 'in' ? 'Invested' : 'Withdrawn'}
                </td>
                <td className="num">{inr(f.amount)}</td>
                <td className="small">{f.notes}</td>
                <td>
                  <button className="icon" title="Remove"
                    onClick={async () => {
                      await api.del('/api/journal/capital/' + f.id)
                      load()
                    }}>✕</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  )
}
