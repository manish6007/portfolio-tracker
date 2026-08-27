async function req(method, url, body) {
  const opts = { method, headers: {} }
  if (body instanceof FormData) opts.body = body
  else if (body !== undefined) {
    opts.headers['Content-Type'] = 'application/json'
    opts.body = JSON.stringify(body)
  }
  const r = await fetch(url, opts)
  if (!r.ok) {
    let detail = r.statusText
    try { detail = (await r.json()).detail || detail } catch { /* ignore */ }
    // A 404 on an /api path is almost never a missing record — those return
    // a message. It means this endpoint is not in the running server, i.e.
    // the Python process is older than the page calling it.
    if (r.status === 404 && url.startsWith('/api/')) {
      detail = 'this server does not have ' + url + '. It is probably running'
        + ' older code — stop uvicorn and start it again, then reload.'
    }
    throw new Error(detail)
  }
  const ct = r.headers.get('content-type') || ''
  return ct.includes('json') ? r.json() : r.text()
}

export const api = {
  get: (url) => req('GET', url),
  post: (url, body) => req('POST', url, body),
  put: (url, body) => req('PUT', url, body),
  del: (url, body) => req('DELETE', url, body),
}

export function inr(x) {
  if (x === null || x === undefined || isNaN(x)) return '—'
  return '₹' + Math.round(x).toLocaleString('en-IN')
}

export function inrShort(x) {
  const a = Math.abs(x)
  if (a >= 1e7) return '₹' + (x / 1e7).toFixed(2) + ' Cr'
  if (a >= 1e5) return '₹' + (x / 1e5).toFixed(1) + ' L'
  if (a >= 1e3) return '₹' + (x / 1e3).toFixed(0) + 'k'
  return inr(x)
}

export const SERIES = [
  'var(--series-1)', 'var(--series-2)', 'var(--series-3)', 'var(--series-4)',
  'var(--series-5)', 'var(--series-6)', 'var(--series-7)', 'var(--series-8)',
]

export const BUCKET_LABELS = {
  equity: 'Equity', debt: 'Debt', gold: 'Gold',
  real_estate: 'Real estate', cash: 'Cash', other: 'Other',
}
