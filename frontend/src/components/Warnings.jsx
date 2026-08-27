export default function Warnings({ items, compact }) {
  if (!items || !items.length) return null
  const worst = items.some((w) => w.level === 'warning')
  return (
    <div className="card" style={{
      borderColor: worst ? 'var(--warning)' : 'var(--border)',
    }}>
      <h2>{worst ? '⚠ ' : 'ℹ '}Check your data
        <span className="small muted" style={{ fontWeight: 400 }}>
          {' '}— these are reported, never silently corrected
        </span>
      </h2>
      {items.map((w, i) => (
        <div className="sugg" key={i}>
          <span className={'dot ' + (w.level === 'warning' ? 'p2' : 'p3')} />
          <div><span>{w.message}</span></div>
        </div>
      ))}
      {!compact && (
        <p className="small muted">
          Anything listed here is also sent in the export, so a reviewer knows
          what is uncertain instead of assuming a number.
        </p>
      )}
    </div>
  )
}
