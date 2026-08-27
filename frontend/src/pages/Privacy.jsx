import { useEffect, useState } from 'react'
import { api } from '../api'

const kb = (n) => (n < 1024 ? n + ' B'
  : n < 1024 * 1024 ? (n / 1024).toFixed(0) + ' KB'
    : (n / 1024 / 1024).toFixed(1) + ' MB')

const when = (iso) => {
  if (!iso) return '—'
  const d = new Date(iso)
  return d.toLocaleString(undefined, {
    day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit',
  })
}

const OUTCOME = {
  ok: { label: 'sent', color: 'var(--good-text)' },
  failed: { label: 'failed', color: 'var(--serious)' },
  blocked: { label: 'blocked — offline mode', color: 'var(--muted)' },
  refused: { label: 'refused — not on the list', color: 'var(--critical)' },
}

/** The page for someone who does not believe the claims.
 *
 * Nothing here is a reassurance; everything is a fact they can check
 * elsewhere — a real path they can open in a file manager, the actual list
 * of hosts, every request made since the app started, and a switch that
 * stops all of them.
 */
export default function Privacy() {
  const [state, setState] = useState(null)
  const [dir, setDir] = useState('')
  const [msg, setMsg] = useState('')
  const [busy, setBusy] = useState(false)
  const [probe, setProbe] = useState(null)
  const [probing, setProbing] = useState(false)

  const load = () => api.get('/api/privacy').then((s) => {
    setState(s); setDir(s.data_dir)
  }).catch(() => {})
  useEffect(() => { load() }, [])

  const testConnection = async () => {
    setProbing(true); setProbe(null)
    try {
      setProbe(await api.get('/api/privacy/test-connection'))
    } catch (e) {
      setProbe({ results: [{ host: '—', label: 'the test itself failed',
        ok: false, detail: e.message }] })
    }
    setProbing(false)
    load()
  }

  const toggleOffline = async () => {
    await api.post('/api/privacy/offline', { offline: !state.offline })
    load()
  }

  const move = async () => {
    setBusy(true); setMsg('')
    try {
      const r = await api.post('/api/privacy/data-dir', { path: dir })
      setMsg(`Copied ${r.copied.length} file(s) to ${r.to}. The app is now`
        + ` using that folder. The old copies are still in ${r.from} —`
        + ' delete them yourself once you have checked the move.')
      load()
    } catch (e) { setMsg(e.message) }
    setBusy(false)
  }

  if (!state) return <p className="muted">Loading…</p>
  const total = state.files.reduce((a, f) => a + f.bytes, 0)

  return (
    <div className="grid">
      <div className="card">
        <h2>Where your data is</h2>
        <p className="small muted" style={{ marginTop: 0 }}>
          There is no account and no server. These are real files on this
          machine — open the folder and look at them. Nothing is written
          anywhere else.
        </p>
        <table className="data">
          <thead><tr>
            <th>File</th><th className="num">Size</th><th className="num">Last written</th>
          </tr></thead>
          <tbody>
            {state.files.length === 0 ? (
              <tr><td colSpan={3} className="muted">
                Nothing saved yet — the file appears once you add something.
              </td></tr>
            ) : state.files.map((f) => (
              <tr key={f.path}>
                <td className="small" style={{ wordBreak: 'break-all' }}>{f.path}</td>
                <td className="num">{kb(f.bytes)}</td>
                <td className="num small muted">{when(f.modified)}</td>
              </tr>
            ))}
          </tbody>
          {state.files.length > 1 && (
            <tfoot><tr>
              <td><b>Total</b></td>
              <td className="num"><b>{kb(total)}</b></td><td></td>
            </tr></tfoot>
          )}
        </table>
        <p className="small muted">
          Back these up and you have backed up everything. Delete them and
          nothing of yours remains.
        </p>
      </div>

      <div className="card">
        <h2>What leaves this machine</h2>
        <p className="small muted" style={{ marginTop: 0 }}>
          Only prices, and only from these two places. The app refuses to
          open a connection to anything else — not analytics, not an update
          check, not us. Nothing about your portfolio is ever sent: a NAV
          request asks for the whole public price list and picks your funds
          out of it here.
        </p>
        <table className="data">
          <thead><tr><th>Host</th><th>What for</th></tr></thead>
          <tbody>
            {state.allowed_hosts.map((h) => (
              <tr key={h.host}>
                <td className="small">{h.host}</td>
                <td className="small muted">{h.purpose}</td>
              </tr>
            ))}
          </tbody>
        </table>

        <div className="row" style={{ marginTop: 14, alignItems: 'center' }}>
          <button className="btn secondary" disabled={probing}
            onClick={testConnection}>
            {probing ? 'Testing…' : 'Test connection'}
          </button>
          <span className="small muted" style={{ flex: 1, minWidth: 240 }}>
            Tries each host once and says exactly what happened — the answer
            when prices will not refresh.
          </span>
        </div>
        {probe && (
          <table className="data" style={{ marginTop: 8 }}>
            <tbody>
              {probe.results.map((r) => (
                <tr key={r.host}>
                  <td className="small">{r.label}
                    <div className="muted">{r.host}</div>
                  </td>
                  <td className="small" style={{
                    color: r.ok ? 'var(--good-text)' : 'var(--serious)' }}>
                    {r.ok ? '✓ reachable' : '✕ failed'} — {r.detail}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}

        <div className="row" style={{ marginTop: 14, alignItems: 'center' }}>
          <button className={'btn' + (state.offline ? '' : ' secondary')}
            onClick={toggleOffline}>
            {state.offline ? '✓ Offline mode is on' : 'Turn on offline mode'}
          </button>
          <span className="small muted" style={{ flex: 1, minWidth: 260 }}>
            {state.offline
              ? 'Nothing leaves this machine at all. Prices come only from'
                + ' what you type — everything else works as normal.'
              : 'Blocks every outbound request, including price refresh.'
                + ' Turn it on, pull out the network cable, and the app'
                + ' still works — which is the claim worth checking.'}
          </span>
        </div>
      </div>

      <div className="card">
        <h2>Every request made since the app started</h2>
        <p className="small muted" style={{ marginTop: 0 }}>
          Started {when(state.started)}. This is the whole list, not a
          sample — if the app talked to something, it is here.
        </p>
        {state.outbound.length === 0 ? (
          <p className="muted small">
            Nothing has been sent. The app has not contacted anything since
            it started.
          </p>
        ) : (
          <div style={{ maxHeight: 320, overflowY: 'auto' }}>
            <table className="data">
              <thead><tr>
                <th>When</th><th>Host</th><th>What for</th><th>Result</th>
              </tr></thead>
              <tbody>
                {state.outbound.map((e, i) => (
                  <tr key={i}>
                    <td className="small muted">{when(e.at)}</td>
                    <td className="small">{e.host}</td>
                    <td className="small muted">{e.purpose}</td>
                    <td className="small"
                      style={{ color: (OUTCOME[e.outcome] || {}).color }}>
                      {(OUTCOME[e.outcome] || { label: e.outcome }).label}
                      {e.detail && (
                        <span className="muted"> · {e.detail}</span>)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <button className="btn secondary" style={{ marginTop: 10 }}
          onClick={load}>Refresh this list</button>
      </div>

      <div className="card">
        <h2>Keep the data somewhere else</h2>
        <p className="small muted" style={{ marginTop: 0 }}>
          Put the files in an encrypted volume, a synced folder, or on a USB
          stick — anywhere this machine can write. The files are copied, the
          originals are left where they are, and the app switches over only
          once the copy is verified.
        </p>
        <div className="row">
          <label className="field" style={{ flex: 1, minWidth: 320 }}>
            Data folder
            <input value={dir} onChange={(e) => setDir(e.target.value)}
              placeholder="/Users/you/Documents/portfolio-data" />
          </label>
          <button className="btn" disabled={busy || !dir.trim()
            || dir.trim() === state.data_dir} onClick={move}>
            {busy ? 'Copying…' : 'Move data here'}
          </button>
        </div>
        {msg && <p className="small">{msg}</p>}
        <p className="small muted" style={{ marginBottom: 0 }}>
          {state.data_dir_source === 'environment'
            ? `Fixed by the ${state.env_var} environment variable, which wins`
              + ' over anything set here.'
            : `Or set ${state.env_var} before starting the app, which takes`
              + ' precedence over this setting.'}
        </p>
      </div>

      <div className="card">
        <h2>What this does not protect you from</h2>
        <ul className="small" style={{ margin: 0, paddingLeft: 20,
          color: 'var(--text-secondary)' }}>
          <li>The files are <b>not encrypted</b>. Anyone who can read the
            disk can read them — put them in an encrypted volume above if
            that matters to you.</li>
          <li>Profiles separate data, they do not lock it. There is no
            login, because on your own machine one would not stop anybody.</li>
          <li>Anything you <b>export</b> leaves on your instructions. The AI
            review package is text you paste somewhere else; use
            privacy-safe mode, which masks names and account numbers.</li>
          <li>The sealed family record is AES-256 encrypted, but wherever you
            put that file is now the weakest point — a locker or a password
            manager, not email.</li>
        </ul>
      </div>
    </div>
  )
}
