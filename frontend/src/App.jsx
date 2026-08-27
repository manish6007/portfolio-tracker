import { useCallback, useEffect, useState } from 'react'
import { api } from './api'
import Help from './components/Help'
import ProfileBar from './components/ProfileBar'
import Cashflow from './pages/Cashflow'
import Dashboard from './pages/Dashboard'
import ExportPage from './pages/ExportPage'
import FI from './pages/FI'
import Insurance from './pages/Insurance'
import Loans from './pages/Loans'
import Portfolio from './pages/Portfolio'
import Privacy from './pages/Privacy'
import Settings from './pages/Settings'

const TABS = ['Dashboard', 'Portfolio', 'Cashflow', 'Loans', 'Insurance', 'FI',
  'Export', 'Privacy', 'Settings']

export default function App() {
  const [tab, setTab] = useState('Dashboard')
  const [summary, setSummary] = useState(null)
  const [meta, setMeta] = useState(null)
  const [owners, setOwners] = useState([])
  const [error, setError] = useState('')
  const [help, setHelp] = useState(false)

  const reload = useCallback(async () => {
    try {
      const [s, o] = await Promise.all([api.get('/api/summary'), api.get('/api/owners')])
      setSummary(s)
      setOwners(o)
      setError('')
    } catch (e) {
      setError('Cannot reach the backend (' + e.message + '). Is uvicorn running on port 8000?')
    }
  }, [])

  useEffect(() => {
    api.get('/api/meta').then(setMeta).catch(() => {})
    reload()
  }, [reload])

  const ctx = { summary, meta, owners, reload }
  return (
    <>
      <header className="topbar">
        <h1>💰 Portfolio Tracker</h1>
        <ProfileBar />
        <button className="info" title="User guide" aria-label="User guide"
          onClick={() => setHelp(true)}>ⓘ</button>
        <nav>
          {TABS.map((t) => (
            <button key={t} className={t === tab ? 'active' : ''}
              onClick={() => setTab(t)}>{t}</button>
          ))}
        </nav>
      </header>
      {help && <Help onClose={() => setHelp(false)} />}
      <main className="page">
        {error && <div className="notice">{error}</div>}
        {meta?.stale_backend && (
          <div className="notice warn">
            <b>The server is running older code than this page.</b> A file
            changed on disk after it started — the built frontend is read
            fresh on every request, but Python is not. Stop uvicorn
            (Ctrl&#8209;C) and start it again, or run it with{' '}
            <code>--reload</code>. Until then, anything added since that start
            will fail with “not found”.
          </div>
        )}
        {!summary || !meta ? (!error && <p className="muted">Loading…</p>) : (
          <>
            {tab === 'Dashboard' && <Dashboard {...ctx} />}
            {tab === 'Portfolio' && <Portfolio {...ctx} />}
            {tab === 'Cashflow' && <Cashflow {...ctx} />}
            {tab === 'Loans' && <Loans {...ctx} />}
            {tab === 'Insurance' && <Insurance {...ctx} />}
            {tab === 'FI' && <FI {...ctx} />}
            {tab === 'Export' && <ExportPage {...ctx} />}
            {tab === 'Privacy' && <Privacy {...ctx} />}
            {tab === 'Settings' && <Settings {...ctx} />}
          </>
        )}
      </main>
    </>
  )
}
