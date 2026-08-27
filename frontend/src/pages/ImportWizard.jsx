import { useRef, useState } from 'react'
import { api, inr } from '../api'

const FIELD_LABEL = {
  identifier: 'Ticker / folio no.', name: 'Name', units: 'Quantity / units',
  avg_cost: 'Average cost', last_price: 'Current price',
  invested: 'Invested value', current_value: 'Current value',
  purchase_date: 'Purchase date (YYYY-MM-DD)',
}

export default function ImportWizard({ meta, owners, reload, onDone }) {
  const [preview, setPreview] = useState(null)
  const [file, setFile] = useState(null)
  const [assetClass, setAssetClass] = useState('stock')
  const [owner, setOwner] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')
  const fileRef = useRef()

  const run = async (mapping) => {
    if (!file) return
    setBusy(true); setMsg('')
    const fd = new FormData()
    fd.append('file', file)
    fd.append('asset_class', assetClass)
    fd.append('owner', owner || (owners[0]?.name || 'Me'))
    fd.append('password', password)
    if (mapping) fd.append('mapping', JSON.stringify(mapping))
    const r = await fetch('/api/import/preview', { method: 'POST', body: fd })
    if (!r.ok) {
      let d = r.statusText
      try { d = (await r.json()).detail || d } catch { /* ignore */ }
      setMsg(d); setPreview(null); setBusy(false); return
    }
    setPreview(await r.json())
    setBusy(false)
  }

  const remap = (field, column) => {
    const m = { ...preview.mapping }
    if (column) m[field] = column; else delete m[field]
    run(m)
  }

  const commit = async () => {
    setBusy(true)
    const res = await api.post('/api/import/commit', {
      rows: preview.rows.map((r) => ({
        ...r, asset_class: preview.asset_class || assetClass,
        owner: owner || r.owner,
      })),
      owner: owner || (owners[0]?.name || 'Me'),
    })
    setBusy(false)
    setMsg(`Imported ${res.added} holdings.`
      + (res.transactions
        ? ` ${res.transactions} transactions came with them, so these holdings`
          + ' now have a real XIRR.' : '')
      + (res.errors.length ? ' Problems: ' + res.errors.join('; ') : ''))
    setPreview(null); setFile(null)
    if (fileRef.current) fileRef.current.value = ''
    reload()
    if (onDone) onDone()
  }

  const isPdf = (file?.name || '').toLowerCase().endsWith('.pdf')
  const isCas = preview?.source === 'cas'
  // Only the detailed statement carries nominees and a transaction history.
  const isDetailed = isCas && preview?.layout === 'detailed'
  const txnTotal = isDetailed
    ? preview.rows.reduce((a, r) => a + (r.transactions?.length || 0), 0) : 0

  return (
    <div className="card">
      <h2>Import from your broker or CAS</h2>
      <p className="small muted" style={{ marginTop: 0 }}>
        Upload the file <b>exactly as it downloads</b> — no need to rename
        columns. The headings brokers use are recognised automatically and the
        guessed mapping is shown below for you to correct. Nothing is saved
        until you press Import.
      </p>

      <div className="row">
        <label className="field">File
          <input ref={fileRef} type="file" accept=".csv,.xlsx,.xlsm,.pdf,.txt"
            onChange={(e) => { setFile(e.target.files[0]); setPreview(null) }} />
        </label>
        {!isPdf && (
          <label className="field">These are
            <select value={assetClass} onChange={(e) => setAssetClass(e.target.value)}>
              {meta.asset_classes.map((c) => (
                <option key={c} value={c}>{meta.asset_class_labels[c]}</option>
              ))}
            </select>
          </label>
        )}
        <label className="field">Owner
          <select value={owner} onChange={(e) => setOwner(e.target.value)}>
            <option value="">{owners[0]?.name || 'Me'}</option>
            {owners.slice(1).map((o) => <option key={o.id}>{o.name}</option>)}
          </select>
        </label>
        {isPdf && (
          <label className="field">CAS password
            <input type="password" value={password} style={{ width: 170 }}
              placeholder="the one you chose"
              onChange={(e) => setPassword(e.target.value)} />
          </label>
        )}
        <button className="btn" disabled={!file || busy} onClick={() => run()}>
          {busy ? 'Reading…' : 'Read file'}
        </button>
      </div>

      <p className="small muted">
        Works with Zerodha, Groww, Upstox, Angel One, ICICI Direct and most
        others (CSV or XLSX). For mutual funds, upload a CAMS/KFintech
        statement PDF — both the Consolidated Account Summary table and the
        detailed statement are understood, and scheme codes are looked up from
        the ISIN so prices refresh by themselves afterwards.
      </p>

      {msg && <div className="notice">{msg}</div>}

      {preview && (
        <>
          {preview.source === 'table' && (
            <div className="card" style={{ marginTop: 12 }}>
              <h2>Column mapping</h2>
              <p className="small muted" style={{ marginTop: 0 }}>
                Change anything that was guessed wrong — the preview updates.
              </p>
              <div className="row">
                {preview.mappable.map((f) => (
                  <label className="field" key={f}>{FIELD_LABEL[f] || f}
                    <select value={preview.mapping[f] || ''}
                      onChange={(e) => remap(f, e.target.value)}>
                      <option value="">— not in this file —</option>
                      {preview.headers.map((h) => (
                        <option key={h} value={h}>{h}</option>
                      ))}
                    </select>
                  </label>
                ))}
              </div>
            </div>
          )}

          {preview.notes.map((n, i) => (
            <div className="notice" key={i}>{n}</div>
          ))}

          <div className="card" style={{ marginTop: 12 }}>
            <h2>{preview.rows.length} holdings ready to import
              {isCas && preview.layout && (
                <span className="small muted" style={{ fontWeight: 400 }}>
                  {' '}— read as a {preview.layout} statement
                </span>
              )}
            </h2>
            {preview.rows.length === 0 ? (
              <p className="muted">
                Nothing readable yet — check the mapping above, especially the
                quantity column.
              </p>
            ) : (
              <div style={{ overflowX: 'auto', maxHeight: 340 }}>
                <table className="data">
                  <thead><tr>
                    <th>Name</th><th>Ticker / folio</th>
                    {isCas && <th>ISIN</th>}
                    {isCas && <th>AMFI code</th>}
                    {isDetailed && <th>Nominee</th>}
                    {isDetailed && <th className="num">Txns</th>}
                    <th className="num">Qty</th><th className="num">Avg cost</th>
                    <th className="num">Price</th><th className="num">Invested</th>
                    <th className="num">Value</th>
                  </tr></thead>
                  <tbody>
                    {preview.rows.map((r, i) => (
                      <tr key={i}>
                        <td>{r.name}</td>
                        <td className="small muted">{r.identifier || '—'}</td>
                        {isCas && <td className="small muted">{r.isin || '—'}</td>}
                        {isCas && (
                          <td className="small">
                            {r.scheme_code || (
                              <span style={{ color: 'var(--warning)' }}>
                                not matched
                              </span>)}
                          </td>
                        )}
                        {isDetailed && (
                          <td className="small muted">{r.nominee || (
                            <span style={{ color: 'var(--warning)' }}>
                              none
                            </span>)}</td>
                        )}
                        {isDetailed && (
                          <td className="num small muted">
                            {r.transactions?.length || 0}
                          </td>
                        )}
                        <td className="num">{r.units}</td>
                        <td className="num">{inr(r.avg_cost)}</td>
                        <td className="num">{inr(r.last_price)}</td>
                        <td className="num">{inr(r.invested)}</td>
                        <td className="num">{inr(r.current_value)}</td>
                      </tr>
                    ))}
                  </tbody>
                  <tfoot><tr>
                    <td colSpan={isDetailed ? 9 : isCas ? 7 : 5}>
                      <b>Total</b>
                      {txnTotal > 0 && (
                        <span className="small muted">
                          {' '}· {txnTotal} transactions
                        </span>)}
                    </td>
                    <td className="num"><b>
                      {inr(preview.rows.reduce((a, r) => a + r.invested, 0))}
                    </b></td>
                    <td className="num"><b>
                      {inr(preview.rows.reduce((a, r) => a + r.current_value, 0))}
                    </b></td>
                  </tr></tfoot>
                </table>
              </div>
            )}

            {preview.skipped.length > 0 && (
              <div className="notice" style={{ borderColor: 'var(--warning)' }}>
                <b>Skipped {preview.skipped.length} row
                {preview.skipped.length > 1 ? 's' : ''}:</b>{' '}
                {preview.skipped.slice(0, 5).join('; ')}
                {preview.skipped.length > 5 && ' …'}
              </div>
            )}

            <div className="row" style={{ marginTop: 10 }}>
              <button className="btn" disabled={!preview.rows.length || busy}
                onClick={commit}>
                Import {preview.rows.length} holdings
              </button>
              <button className="btn secondary" onClick={() => setPreview(null)}>
                Cancel
              </button>
              <span className="small muted">
                Importing adds new holdings; it does not update or de-duplicate
                existing ones.
              </span>
            </div>
          </div>
        </>
      )}
    </div>
  )
}
