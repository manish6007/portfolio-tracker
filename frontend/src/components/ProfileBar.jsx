import { useEffect, useState } from 'react'
import { api } from '../api'

/** Which portfolio is on screen, and how to switch.
 *
 * Sits in the top bar rather than in Settings because the answer to "whose
 * numbers am I looking at" has to be visible at all times — the whole point
 * is handing the laptop to someone without your own salary on the screen.
 */
export default function ProfileBar() {
  const [state, setState] = useState(null)

  useEffect(() => { api.get('/api/profiles').then(setState).catch(() => {}) }, [])

  const switchTo = async (id) => {
    if (!id || id === state.active) return
    await api.post(`/api/profiles/${id}/activate`)
    // A full reload rather than a re-render: every page holds data from the
    // profile being left, and a stale figure from the wrong portfolio is the
    // one mistake this feature must never make.
    window.location.reload()
  }

  if (!state || state.profiles.length < 2) return null
  const active = state.profiles.find((p) => p.id === state.active)
  return (
    <div className={'profile-chip' + (active?.demo ? ' demo' : '')}>
      <span className="small muted">Viewing</span>
      <select value={state.active} onChange={(e) => switchTo(e.target.value)}>
        {state.profiles.map((p) => (
          <option key={p.id} value={p.id}>{p.name}{p.demo ? ' (demo)' : ''}</option>
        ))}
      </select>
    </div>
  )
}
