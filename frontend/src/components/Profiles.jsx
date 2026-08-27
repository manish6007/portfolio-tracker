import { useEffect, useState } from 'react'
import { api } from '../api'

/** Manage the separate portfolios this installation holds. */
export default function Profiles() {
  const [state, setState] = useState(null)
  const [name, setName] = useState('')
  const [demo, setDemo] = useState(true)
  const [msg, setMsg] = useState('')
  const [busy, setBusy] = useState(false)

  const load = () => api.get('/api/profiles').then(setState).catch(() => {})
  useEffect(() => { load() }, [])

  const create = async () => {
    setBusy(true); setMsg('')
    try {
      const p = await api.post('/api/profiles', { name, demo })
      setName('')
      await load()
      setMsg(`Created “${p.name}”. Switch to it from the top bar.`)
    } catch (e) { setMsg(e.message) }
    setBusy(false)
  }

  const remove = async (p) => {
    const typed = window.prompt(
      `Deleting “${p.name}” erases that portfolio permanently — every holding,`
      + ' loan and entry inside it. Type the profile name to confirm.')
    if (typed === null) return
    setMsg('')
    try {
      await api.del(`/api/profiles/${p.id}`, { confirm: typed })
      await load()
      setMsg(`Deleted “${p.name}”.`)
    } catch (e) { setMsg(e.message) }
  }

  if (!state) return null
  return (
    <div className="card">
      <h2>Profiles</h2>
      <p className="small muted" style={{ marginTop: 0 }}>
        Each profile is a completely separate portfolio in its own file —
        switch to a demo one before showing the app to anyone, and none of
        your own numbers can appear. Switch from the top bar.
      </p>

      <table className="data">
        <thead><tr>
          <th>Profile</th><th>Data file</th><th></th>
        </tr></thead>
        <tbody>
          {state.profiles.map((p) => (
            <tr key={p.id}>
              <td>
                {p.name}
                {p.id === state.active && (
                  <span className="small muted"> · you are here</span>)}
                {p.demo && <span className="small muted"> · demo data</span>}
              </td>
              <td className="small muted">{p.file}</td>
              <td style={{ textAlign: 'right' }}>
                {p.id === 'default' ? (
                  <span className="small muted">cannot be deleted</span>
                ) : (
                  <button className="icon" title="Delete this profile"
                    onClick={() => remove(p)}>✕</button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <div className="row" style={{ marginTop: 12 }}>
        <label className="field">New profile
          <input value={name} placeholder="e.g. Demo household"
            onChange={(e) => setName(e.target.value)} />
        </label>
        <label className="field">&nbsp;
          <span className="small">
            <input type="checkbox" checked={demo}
              onChange={(e) => setDemo(e.target.checked)} />
            {' '}fill it with demo data
          </span>
        </label>
        <button className="btn" disabled={!name.trim() || busy}
          onClick={create}>{busy ? 'Creating…' : 'Create profile'}</button>
      </div>
      {msg && <p className="small" style={{ marginBottom: 0 }}>{msg}</p>}

      <p className="small muted" style={{ marginBottom: 0 }}>
        This separates data; it is not a lock. Anyone using the laptop can
        switch back, and every profile’s file sits unencrypted in the backend
        folder — same as before. Keep the machine itself protected.
      </p>
    </div>
  )
}
