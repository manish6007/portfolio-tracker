import { useEffect, useState } from 'react'
import { api, inr } from '../api'
import Warnings from '../components/Warnings'

const today = () => new Date().toISOString().slice(0, 10)

const basis = (n) =>
  !n ? 'no entries yet'
    : n === 1 ? 'based on 1 month of entries'
      : `average of ${n} months of entries`

function EntryForm({ kind, owners, onDone }) {
  const isIncome = kind === 'income'
  const [f, setF] = useState({
    date: today(), category: isIncome ? 'Salary' : 'Household',
    amount: '', owner_id: '', fixed: !isIncome, notes: '',
  })
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value })
  const cats = isIncome
    ? ['Salary', 'Bonus', 'Rent received', 'Dividend', 'Interest', 'Other']
    : ['Household', 'Rent paid', 'School fees', 'Transport', 'Utilities',
       'Insurance', 'Medical', 'Dining & fun', 'Travel', 'Shopping', 'Other']
  const submit = async (e) => {
    e.preventDefault()
    await api.post('/api/' + (isIncome ? 'income' : 'expenses'), {
      ...f, amount: +f.amount,
      owner_id: f.owner_id ? +f.owner_id : undefined,
      fixed: f.fixed === true || f.fixed === 'true',
    })
    setF({ ...f, amount: '', notes: '' })
    onDone()
  }
  return (
    <form className="row" onSubmit={submit}>
      <label className="field">Date
        <input type="date" value={f.date} onChange={set('date')} /></label>
      <label className="field">Owner
        <select value={f.owner_id} onChange={set('owner_id')}>
          <option value="">{owners[0]?.name || 'Me'}</option>
          {owners.slice(1).map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
        </select></label>
      <label className="field">Category
        <select value={f.category} onChange={set('category')}>
          {cats.map((c) => <option key={c}>{c}</option>)}
        </select></label>
      <label className="field">Amount
        <input type="number" step="any" required value={f.amount} onChange={set('amount')} /></label>
      {!isIncome && (
        <label className="field">Type
          <select value={String(f.fixed)} onChange={set('fixed')}>
            <option value="true">Fixed / committed</option>
            <option value="false">Discretionary</option>
          </select></label>
      )}
      <button className="btn" type="submit">Add</button>
    </form>
  )
}

function EntryTable({ rows, onDelete, showFixed }) {
  if (!rows.length) return <p className="muted">No entries yet.</p>
  return (
    <div style={{ overflowX: 'auto' }}>
      <table className="data">
        <thead><tr>
          <th>Date</th><th>Owner</th><th>Category</th>
          {showFixed && <th>Type</th>}
          <th className="num">Amount</th><th></th>
        </tr></thead>
        <tbody>
          {rows.slice(0, 60).map((r) => (
            <tr key={r.id}>
              <td>{r.date}</td><td>{r.owner}</td><td>{r.category}</td>
              {showFixed && <td className="small muted">{r.fixed ? 'fixed' : 'discretionary'}</td>}
              <td className="num">{inr(r.amount)}</td>
              <td><button className="icon" onClick={() => onDelete(r.id)}>🗑</button></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export default function Cashflow({ summary, owners, reload }) {
  const [income, setIncome] = useState([])
  const [expenses, setExpenses] = useState([])
  const [rec, setRec] = useState([])
  const [rf, setRf] = useState({ name: '', kind: 'sip', amount: '',
    frequency: 'monthly', next_due: '', counts_as_investment: true })

  const loadLists = async () => {
    const [i, e, r] = await Promise.all([
      api.get('/api/income'), api.get('/api/expenses'), api.get('/api/recurring')])
    setIncome(i); setExpenses(e); setRec(r)
  }
  useEffect(() => { loadLists() }, [])

  const refresh = () => { loadLists(); reload() }
  const cf = summary.cashflow
  const lumpy = summary.lumpy_upcoming || []
  const lumpyTotal = lumpy.reduce((a, l) => a + l.amount, 0)

  const addRec = async (e) => {
    e.preventDefault()
    await api.post('/api/recurring', {
      name: rf.name, kind: rf.kind, amount: +rf.amount,
      frequency: rf.frequency, next_due: rf.next_due || null,
      counts_as_investment: rf.counts_as_investment,
    })
    setRf({ name: '', kind: 'sip', amount: '', frequency: 'monthly',
      next_due: '', counts_as_investment: true })
    refresh()
  }

  return (
    <div className="grid">
      <div className="grid cols-4">
        <div className="card stat">
          <div className="label">Income / month</div>
          <div className="value">{inr(cf.income_m)}</div>
          <div className="sub">{basis(cf.income_months)}</div>
        </div>
        <div className="card stat">
          <div className="label">Expenses / month</div>
          <div className="value">{inr(cf.expense_m)}</div>
          <div className="sub">
            logged {inr(cf.expense_entries_m)} ({basis(cf.expense_months)})
            {cf.recurring_expense_m > 0 &&
              ` + recurring ${inr(cf.recurring_expense_m)}`}
          </div>
        </div>
        <div className="card stat">
          <div className="label">EMIs + investing</div>
          <div className="value">{inr(cf.emi_m + cf.committed_invest_m)}</div>
          <div className="sub">
            EMI {inr(cf.emi_m)} · SIPs {inr(cf.sip_m)}{cf.payroll_invest_m > 0 && ` · payroll ${inr(cf.payroll_invest_m)}`}
            {cf.recurring_expense_m > 0 &&
              ` · recurring costs ${inr(cf.recurring_expense_m)} counted in expenses`}
          </div>
        </div>
        <div className="card stat">
          <div className="label">Investible surplus</div>
          <div className={'value ' + (cf.surplus_m < 0 ? 'neg' : '')}>{inr(cf.surplus_m)}</div>
          <div className="sub">savings rate {(cf.savings_rate_pct || 0).toFixed(0)}%</div>
        </div>
      </div>

      {cf.expense_months > 0 && cf.income_months > cf.expense_months && (
        <div className="notice">
          Expenses are logged for {cf.expense_months} month
          {cf.expense_months > 1 ? 's' : ''} but income for {cf.income_months} —
          each is averaged over its own months, so the figures above are per-month
          either way. Log the missing months' expenses for a truer surplus.
        </div>
      )}

      <Warnings items={summary.warnings} />

      {lumpy.length > 0 && (
        <div className="card" style={{ borderColor: 'var(--warning)' }}>
          <h2>⚠ Lumpy bills due in the next 3 months</h2>
          <p className="small muted" style={{ marginTop: 0 }}>
            These are already spread into your monthly figures, but the cash
            leaves in one go on these dates — keep {inr(lumpyTotal)} reachable.
          </p>
          <table className="data">
            <thead><tr>
              <th>Due</th><th>What</th><th>Every</th><th className="num">Amount</th>
            </tr></thead>
            <tbody>
              {lumpy.map((l, i) => (
                <tr key={i}>
                  <td>{l.due_date}</td>
                  <td>{l.name}
                    {l.counts_as_investment &&
                      <span className="small muted"> · investment</span>}</td>
                  <td className="small muted">{l.frequency_label}</td>
                  <td className="num">{inr(l.amount)}</td>
                </tr>
              ))}
            </tbody>
            <tfoot><tr>
              <td colSpan={3}><b>Total</b></td>
              <td className="num"><b>{inr(lumpyTotal)}</b></td>
            </tr></tfoot>
          </table>
        </div>
      )}

      <div className="card">
        <h2>Committed outflows (EMIs, SIPs, premiums, subscriptions, upkeep)</h2>
        <form className="row" onSubmit={addRec}>
          <label className="field">Name
            <input required value={rf.name} onChange={(e) => setRf({ ...rf, name: e.target.value })} /></label>
          <label className="field">Kind
            <select value={rf.kind} onChange={(e) => setRf({
              ...rf, kind: e.target.value,
              counts_as_investment: ['sip', 'pf', 'nps', 'esop'].includes(e.target.value),
            })}>
              <option value="sip">SIP / savings plan</option>
              <option value="pf">PF / EPF contribution</option>
              <option value="nps">NPS contribution</option>
              <option value="esop">ESOP / RSU</option>
              <option value="emi">EMI</option>
              <option value="premium">Insurance premium</option>
              <option value="subscription">Subscription</option>
              <option value="maintenance">Maintenance / upkeep</option>
              <option value="tax">Tax / statutory</option>
              <option value="other">Other</option>
            </select></label>
          <label className="field">Amount per payment
            <input type="number" step="any" required value={rf.amount}
              onChange={(e) => setRf({ ...rf, amount: e.target.value })} /></label>
          <label className="field">Every
            <select value={rf.frequency}
              onChange={(e) => setRf({ ...rf, frequency: e.target.value })}>
              <option value="monthly">Month</option>
              <option value="quarterly">Quarter</option>
              <option value="half_yearly">6 months</option>
              <option value="yearly">Year</option>
            </select></label>
          {rf.frequency !== 'monthly' && (
            <label className="field">Next due
              <input type="date" value={rf.next_due}
                onChange={(e) => setRf({ ...rf, next_due: e.target.value })} />
            </label>
          )}
          <label className="field">Treat as
            <select value={String(rf.counts_as_investment)}
              onChange={(e) => setRf({ ...rf, counts_as_investment: e.target.value === 'true' })}>
              <option value="true">Investment (money you keep)</option>
              <option value="false">Expense (money you spend)</option>
            </select></label>
          <button className="btn" type="submit">Add</button>
        </form>
        <p className="small muted">
          Enter each cost the way it is actually billed — a ₹12,000 yearly
          subscription or ₹9,000 quarterly maintenance — and it is spread into a
          monthly equivalent so your surplus stays honest between the lumpy
          months. PF, NPS and ESOP contributions are savings, not spending: mark
          them as investments.
        </p>
        {rec.length > 0 && (
          <table className="data" style={{ marginTop: 10 }}>
            <thead><tr>
              <th>Name</th><th>Kind</th><th>Every</th><th>Next due</th>
              <th className="num">Per payment</th>
              <th className="num">Per month</th>
              <th className="num">Per year</th><th></th>
            </tr></thead>
            <tbody>{rec.map((r) => (
              <tr key={r.id}>
                <td>{r.name}</td>
                <td>
                  {r.kind}{' '}
                  <button className="icon" style={{ fontSize: 12 }}
                    title="Click to switch between investment and expense"
                    onClick={async () => {
                      await api.put('/api/recurring/' + r.id,
                        { counts_as_investment: !r.counts_as_investment })
                      refresh()
                    }}>
                    {r.counts_as_investment ? '· investment ⇄' : '· expense ⇄'}
                  </button>
                </td>
                <td className="small">{r.frequency_label}</td>
                <td className="small muted">
                  {r.frequency === 'monthly' ? '—'
                    : r.next_due || <span style={{ color: 'var(--warning)' }}>set a date</span>}
                </td>
                <td className="num">{inr(r.amount)}</td>
                <td className="num">{inr(r.amount_monthly)}</td>
                <td className="num muted">{inr(r.amount_annual)}</td>
                <td><button className="icon" onClick={async () => { await api.del('/api/recurring/' + r.id); refresh() }}>🗑</button></td>
              </tr>
            ))}</tbody>
            <tfoot><tr>
              <td colSpan={5}><b>Total</b></td>
              <td className="num"><b>
                {inr(rec.reduce((a, r) => a + r.amount_monthly, 0))}
              </b></td>
              <td className="num"><b>
                {inr(rec.reduce((a, r) => a + (r.amount_annual || 0), 0))}
              </b></td>
              <td></td>
            </tr></tfoot>
          </table>
        )}
        {rec.some((r) => r.frequency !== 'monthly') && (
          <p className="small muted">
            Non-monthly items are spread evenly above and counted in
            Expenses / month. Add a next-due date to each so they appear in the
            lumpy-bills warning.
          </p>
        )}
      </div>

      <div className="grid cols-2">
        <div className="card">
          <h2>Income</h2>
          <EntryForm kind="income" owners={owners} onDone={refresh} />
          <div style={{ marginTop: 12 }}>
            <EntryTable rows={income} showFixed={false}
              onDelete={async (id) => { await api.del('/api/income/' + id); refresh() }} />
          </div>
        </div>
        <div className="card">
          <h2>Expenses</h2>
          <EntryForm kind="expense" owners={owners} onDone={refresh} />
          <div style={{ marginTop: 12 }}>
            <EntryTable rows={expenses} showFixed
              onDelete={async (id) => { await api.del('/api/expenses/' + id); refresh() }} />
          </div>
        </div>
      </div>
    </div>
  )
}
