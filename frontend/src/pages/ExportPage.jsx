import { useCallback, useEffect, useState } from 'react'
import { api } from '../api'

export default function ExportPage() {
  const [privacy, setPrivacy] = useState(true)
  const [preview, setPreview] = useState('')
  const [copied, setCopied] = useState(false)
  const [rec, setRec] = useState(null)
  const [pw, setPw] = useState('')
  const [pw2, setPw2] = useState('')
  const [rmsg, setRmsg] = useState('')
  const [fields, setFields] = useState({ household_name: '',
    record_stored_at: '', record_password_held_by: '' })

  const loadRec = useCallback(async () => {
    try {
      const st = await api.get('/api/family-record/status')
      setRec(st)
      const s = await api.get('/api/settings')
      setFields({
        household_name: s.household_name || '',
        record_stored_at: s.record_stored_at || '',
        record_password_held_by: s.record_password_held_by || '',
      })
    } catch (e) { setRmsg(e.message) }
  }, [])
  useEffect(() => { loadRec() }, [loadRec])

  const saveFields = async (patch) => {
    await api.put('/api/settings', patch)
    loadRec()
  }

  const downloadSealed = async () => {
    if (pw !== pw2) { setRmsg('The two passwords do not match.'); return }
    setRmsg('')
    const r = await fetch('/api/family-record/sealed', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ password: pw }),
    })
    if (!r.ok) {
      let d = r.statusText
      try { d = (await r.json()).detail || d } catch { /* ignore */ }
      setRmsg(d); return
    }
    const blob = await r.blob()
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = 'family_record_sealed.pdf'
    a.click()
    URL.revokeObjectURL(a.href)
    setPw(''); setPw2('')
    setRmsg('Downloaded. The password is not stored anywhere — if you lose '
      + 'it, generate the file again with a new one.')
  }
  const p = privacy ? 1 : 0

  // Why the sealed download cannot be pressed yet, in words.
  const minLen = rec?.min_password_length || 10
  const blocker = !pw ? 'Choose a password to seal the file with.'
    : pw.length < minLen
      ? `${minLen - pw.length} more character${
        minLen - pw.length === 1 ? '' : 's'} needed — ${minLen} is the minimum.`
      : !pw2 ? 'Type it a second time, so a typo cannot lock you out.'
        : pw !== pw2 ? 'The two do not match.'
          : ''

  const loadPreview = async () => {
    setPreview(JSON.stringify(await api.get('/api/export/json?privacy=' + p), null, 2))
  }

  const copyAiPackage = async () => {
    const text = await api.get('/api/export/ai-package?privacy=' + p)
    await navigator.clipboard.writeText(text)
    setCopied(true)
    setTimeout(() => setCopied(false), 2500)
  }

  return (
    <div className="grid">
      <div className="card">
        <h2>Export snapshot</h2>
        <p className="muted">
          Generate a portfolio snapshot to archive, or to paste into Claude for
          an optimization review. Privacy-safe mode strips owner names and
          masks folio/account numbers while keeping every number that matters.
        </p>
        <label className="row" style={{ alignItems: 'center', margin: '10px 0' }}>
          <input type="checkbox" checked={privacy}
            onChange={(e) => setPrivacy(e.target.checked)} />
          Privacy-safe mode (recommended before sharing with any AI)
        </label>
        <div className="row">
          <a className="btn" style={{ textDecoration: 'none' }}
            href={'/api/export/pdf?privacy=' + p}>⬇ Download PDF</a>
          <button className="btn secondary" onClick={copyAiPackage}>
            {copied ? '✓ Copied!' : '📋 Copy AI review package (prompt + JSON)'}
          </button>
          <button className="btn secondary" onClick={loadPreview}>Preview JSON</button>
        </div>
        <p className="small muted" style={{ marginTop: 10 }}>
          Workflow: copy the AI package → paste into a Claude chat → get an
          allocation / overlap / tax / debt review. It is educational analysis,
          not investment advice.
        </p>
      </div>
      {/* Family record */}
      <div className="card">
        <h2>Family record</h2>
        <p className="muted" style={{ marginTop: 0 }}>
          Most money goes unclaimed for one reason: the family never knew the
          account existed. This produces two documents — a sealed PDF listing
          every account, folio, policy and loan in full, and an open one-page
          sheet saying where that sealed file is kept. Neither contains a
          username, password or security answer, by design.
        </p>

        <label className="row" style={{ alignItems: 'center', margin: '12px 0' }}>
          <input type="checkbox" checked={!!rec?.enabled}
            onChange={(e) => saveFields({
              family_record_enabled: e.target.checked ? '1' : '' })} />
          <b>Enable the family record</b>
          <span className="small muted">— off by default</span>
        </label>

        {rec && !rec.encryption_available && (
          <div className="notice" style={{ borderColor: 'var(--critical)' }}>
            {rec.encryption_error} Nothing will be written with a weaker
            cipher — a file labelled &quot;protected&quot; that is not
            protected is worse than none.
          </div>
        )}

        {rec?.enabled && (
          <>
            <div className="row">
              <label className="field">Household name (on both documents)
                <input value={fields.household_name} style={{ width: 260 }}
                  onChange={(e) => setFields({ ...fields, household_name: e.target.value })}
                  onBlur={(e) => saveFields({ household_name: e.target.value })} />
              </label>
              <label className="field">The sealed file will be kept at
                <input value={fields.record_stored_at} style={{ width: 300 }}
                  placeholder="bank locker, with the will…"
                  onChange={(e) => setFields({ ...fields, record_stored_at: e.target.value })}
                  onBlur={(e) => saveFields({ record_stored_at: e.target.value })} />
              </label>
              <label className="field">The password is held by
                <input value={fields.record_password_held_by} style={{ width: 260 }}
                  placeholder="who can open it if you cannot"
                  onChange={(e) => setFields({ ...fields, record_password_held_by: e.target.value })}
                  onBlur={(e) => saveFields({ record_password_held_by: e.target.value })} />
              </label>
            </div>

            <div className="grid cols-2" style={{ marginTop: 14 }}>
              <div className="card">
                <h2>1 · Sealed record (AES-256)</h2>
                <p className="small muted" style={{ marginTop: 0 }}>
                  {rec.holdings} holdings, {rec.policies} policies,{' '}
                  {rec.loans} loans — with full folio, account and policy
                  numbers.
                </p>
                <div className="row">
                  <label className="field">Password (min {rec.min_password_length})
                    {/* autoComplete="new-password" matters twice over: a
                        browser filling a saved site password in here leaves
                        the box looking full while React has seen nothing —
                        and worse, would encrypt the file with a password
                        the user never chose. */}
                    <input type="password" value={pw} style={{ width: 200 }}
                      name="sealed-record-password"
                      autoComplete="new-password"
                      onChange={(e) => setPw(e.target.value)} /></label>
                  <label className="field">Repeat it
                    <input type="password" value={pw2} style={{ width: 200 }}
                      name="sealed-record-password-repeat"
                      autoComplete="new-password"
                      onChange={(e) => setPw2(e.target.value)} /></label>
                  <button className="btn" onClick={downloadSealed}
                    disabled={!!blocker}>
                    ⬇ Download sealed PDF
                  </button>
                </div>
                {/* A greyed-out button that will not say why is the one
                    thing this app is not supposed to do. */}
                {blocker && <p className="small"
                  style={{ color: 'var(--serious)', margin: '4px 0 0' }}>
                  {blocker}
                </p>}
                <p className="small muted">
                  The password is never stored — not in the app, not in the
                  database. Lose it and you regenerate the file, which is the
                  point.
                </p>
              </div>

              <div className="card">
                <h2>2 · Locator sheet (open)</h2>
                <p className="small muted" style={{ marginTop: 0 }}>
                  One page, no account numbers on it. Says where the sealed
                  file is and who holds the password, then lists the
                  institutions so a family that never opens the sealed file
                  still knows which doors to knock on.
                </p>
                <a className="btn secondary" style={{ textDecoration: 'none' }}
                  href="/api/family-record/locator">⬇ Download locator sheet</a>
                <p className="small muted" style={{ marginTop: 10 }}>
                  Print it and keep it where your family will look — with the
                  will, in the locker, with the passbooks.
                </p>
              </div>
            </div>

            {rmsg && <div className="notice">{rmsg}</div>}

            {(rec.holdings_without_nominee.length > 0
              || rec.holdings_without_identifier.length > 0) && (
              <div className="card" style={{ borderColor: 'var(--warning)' }}>
                <h2>⚠ Gaps that will make a claim harder</h2>
                {rec.holdings_without_nominee.length > 0 && (
                  <p className="small">
                    <b>No nominee ({rec.holdings_without_nominee.length}):</b>{' '}
                    {rec.holdings_without_nominee.slice(0, 6).join(', ')}
                    {rec.holdings_without_nominee.length > 6 && ' …'} — the
                    institution will ask for succession documents instead.
                  </p>
                )}
                {rec.holdings_without_identifier.length > 0 && (
                  <p className="small">
                    <b>No account/folio number
                    ({rec.holdings_without_identifier.length}):</b>{' '}
                    {rec.holdings_without_identifier.slice(0, 6).join(', ')}
                    {rec.holdings_without_identifier.length > 6 && ' …'} —
                    these appear in the record with a dash, which helps nobody.
                  </p>
                )}
              </div>
            )}

            <p className="small muted">
              <b>Where you keep it matters more than the cipher.</b> A bank
              locker or a password manager&apos;s secure notes are good. Email
              and chat apps are not — a copy mailed to yourself lives in that
              mailbox permanently. And this is a record, not a will: it
              transfers nothing, and in India a nominee is often a trustee for
              the legal heirs rather than the owner, so take proper succession
              advice.
            </p>
          </>
        )}
      </div>

      {preview && (
        <div className="card">
          <h2>JSON preview</h2>
          <pre className="export">{preview}</pre>
        </div>
      )}
    </div>
  )
}
