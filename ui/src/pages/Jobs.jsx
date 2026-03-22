import { useEffect, useState } from 'react'
import { useToast } from '../components/Toast.jsx'

const JOB_ICONS = {
  digest: '📰', news: '🔍', consolidation: '🧠', memory: '🧠',
  search: '🔍', default: '⏱',
}

function jobIcon(id) {
  const k = Object.keys(JOB_ICONS).find(k => id?.toLowerCase().includes(k))
  return JOB_ICONS[k] || JOB_ICONS.default
}

function fmtNextRun(next_run) {
  if (!next_run) return '—'
  const diff = Math.round((new Date(next_run) - Date.now()) / 1000)
  if (diff < 0) return 'overdue'
  if (diff < 3600) return `in ${Math.floor(diff / 60)}m`
  return `in ${Math.floor(diff / 3600)}h ${Math.floor((diff % 3600) / 60)}m`
}

const EMPTY = { job_id: '', schedule: '', prompt: '' }

// ── Cron validation ──────────────────────────────────────────────────────────

const CRON_FIELDS = [
  { name: 'minute',      min: 0,  max: 59 },
  { name: 'hour',        min: 0,  max: 23 },
  { name: 'day',         min: 1,  max: 31 },
  { name: 'month',       min: 1,  max: 12 },
  { name: 'day-of-week', min: 0,  max: 7  },
]

function validateCronField(token, { min, max }) {
  if (token === '*') return true
  // */n
  if (/^\*\/\d+$/.test(token)) {
    const n = parseInt(token.slice(2))
    return n >= 1 && n <= max
  }
  // n,m,... list
  if (token.includes(',')) {
    return token.split(',').every(t => validateCronField(t, { min, max }))
  }
  // n-m range
  if (token.includes('-')) {
    const [a, b] = token.split('-').map(Number)
    return !isNaN(a) && !isNaN(b) && a >= min && b <= max && a <= b
  }
  // n/step
  if (token.includes('/')) {
    const [base, step] = token.split('/')
    return validateCronField(base, { min, max }) && parseInt(step) >= 1
  }
  // plain number
  const n = parseInt(token)
  return !isNaN(n) && n >= min && n <= max
}

const DAYS   = ['Sun','Mon','Tue','Wed','Thu','Fri','Sat']
const MONTHS = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']

function describeCron(expr) {
  const [min, hr, day, mon, dow] = expr.trim().split(/\s+/)
  const timeStr = (hr === '*' || min === '*')
    ? null
    : `${hr.padStart(2,'0')}:${min.padStart(2,'0')}`
  const at = timeStr ? ` at ${timeStr}` : ''

  if (min === '*' && hr === '*' && day === '*' && mon === '*' && dow === '*')
    return 'Every minute'
  if (min !== '*' && hr === '*')
    return `Every hour at minute ${min}`
  if (dow !== '*' && day === '*' && mon === '*') {
    const dayName = dow.split(',').map(d => DAYS[parseInt(d)] ?? d).join(', ')
    return `Every ${dayName}${at}`
  }
  if (mon !== '*' && day !== '*')
    return `${ordinal(day)} of ${MONTHS[(parseInt(mon)-1)%12]}${at}`
  if (day !== '*' && mon === '*' && dow === '*')
    return `${ordinal(day)} of every month${at}`
  if (day === '*' && mon === '*' && dow === '*' && timeStr)
    return `Every day${at}`
  if (min.startsWith('*/'))
    return `Every ${min.slice(2)} minutes`
  if (hr.startsWith('*/'))
    return `Every ${hr.slice(2)} hours`
  return null  // no simple description
}

function ordinal(n) {
  const i = parseInt(n)
  const s = ['th','st','nd','rd']
  const v = i % 100
  return i + (s[(v-20)%10] || s[v] || s[0])
}

/** Returns { valid, error, description } for a cron expression string. */
function validateCron(expr) {
  if (!expr.trim()) return { valid: null }
  const parts = expr.trim().split(/\s+/)
  if (parts.length !== 5)
    return { valid: false, error: `Expected 5 fields, got ${parts.length}` }
  for (let i = 0; i < 5; i++) {
    if (!validateCronField(parts[i], CRON_FIELDS[i]))
      return { valid: false, error: `Invalid ${CRON_FIELDS[i].name} field: "${parts[i]}"` }
  }
  return { valid: true, description: describeCron(expr) }
}

function JobForm({ title, initial, onSubmit, onCancel, submitLabel, error }) {
  const [form, setForm] = useState(initial)
  const set = (k, v) => setForm(f => ({ ...f, [k]: v }))

  const cron = validateCron(form.schedule)
  const scheduleClass = [
    'job-input job-input-schedule',
    cron.valid === false ? 'input-invalid' : '',
    cron.valid === true  ? 'input-valid'   : '',
  ].join(' ').trim()

  return (
    <div className="job-form">
      <div className="job-form-title">{title}</div>
      <div className="job-form-top-row">
        <input
          className="job-input"
          placeholder="job_id"
          value={form.job_id}
          onChange={e => set('job_id', e.target.value)}
        />
        <div className="schedule-wrap">
          <input
            className={scheduleClass}
            placeholder="0 8 * * *"
            value={form.schedule}
            onChange={e => set('schedule', e.target.value)}
          />
          {cron.valid === false && (
            <div className="cron-hint cron-error">{cron.error}</div>
          )}
          {cron.valid === true && cron.description && (
            <div className="cron-hint cron-ok">{cron.description}</div>
          )}
        </div>
      </div>
      <textarea
        className="job-textarea"
        placeholder="Prompt — what the agent should do when this job runs"
        rows={3}
        value={form.prompt}
        onChange={e => set('prompt', e.target.value)}
      />
      <div className="job-form-actions">
        {error && <div className="form-error">{error}</div>}
        <button className="job-cancel" onClick={onCancel}>Cancel</button>
        <button
          className="job-submit"
          disabled={cron.valid === false}
          onClick={() => onSubmit(form)}
        >{submitLabel}</button>
      </div>
    </div>
  )
}

export default function Jobs() {
  const [jobs, setJobs]       = useState(null)
  const [showNew, setShowNew] = useState(false)
  const [editingId, setEditingId] = useState(null)
  const [createErr, setCreateErr] = useState('')
  const [editErr, setEditErr]     = useState('')
  const { showToast } = useToast()

  const reload = () =>
    fetch('/api/jobs').then(r => r.json()).then(setJobs)
      .catch(e => showToast(e.message || 'Failed to load jobs', 'error'))

  useEffect(() => { reload() }, [])

  const create = async (form) => {
    setCreateErr('')
    const r = await fetch('/api/jobs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(form),
    })
    if (!r.ok) { setCreateErr((await r.json()).detail || 'Error'); return }
    setShowNew(false)
    reload()
  }

  const save = async (originalId, form) => {
    setEditErr('')
    // Delete old if id changed
    if (originalId !== form.job_id) {
      await fetch(`/api/jobs/${originalId}`, { method: 'DELETE' })
    }
    const r = await fetch('/api/jobs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(form),
    })
    if (!r.ok) { setEditErr((await r.json()).detail || 'Error'); return }
    setEditingId(null)
    reload()
  }

  const run = async (id) => {
    const r = await fetch(`/api/jobs/${id}/run`, { method: 'POST' })
    if (r.ok) {
      showToast(`Job "${id}" triggered`, 'info')
    } else {
      const err = await r.json().catch(() => ({}))
      showToast(err.detail || `Failed to trigger "${id}"`, 'error')
    }
  }

  const remove = async (id) => {
    await fetch(`/api/jobs/${id}`, { method: 'DELETE' })
    if (editingId === id) setEditingId(null)
    reload()
  }

  return (
    <>
      <div className="jobs-header">
        <div>
          <div className="page-title">Scheduled Jobs</div>
          <div className="page-sub" style={{ marginTop: 4 }}>Static + agent-created CRON tasks</div>
        </div>
        <button className="add-btn" onClick={() => { setShowNew(f => !f); setCreateErr('') }}>
          {showNew ? '✕ Cancel' : '+ New Job'}
        </button>
      </div>

      {showNew && (
        <JobForm
          title="New Job"
          initial={EMPTY}
          submitLabel="Create"
          error={createErr}
          onSubmit={create}
          onCancel={() => { setShowNew(false); setCreateErr('') }}
        />
      )}

      {jobs === null
        ? <div className="loading">Loading…</div>
        : jobs.length === 0
          ? <div className="empty-state">No jobs scheduled yet</div>
          : jobs.map(job => (
              <div key={job.id}>
                <div className="job-card">
                  <div className="job-icon">{jobIcon(job.id)}</div>
                  <div className="job-info">
                    <div className="job-name">{job.id}</div>
                    <div className="job-desc">{job.prompt || <em style={{ opacity: 0.4 }}>No prompt</em>}</div>
                  </div>
                  <div className="job-card-meta">
                    <span className="job-cron-tag">{job.schedule || '—'}</span>
                    <div className="job-next">{fmtNextRun(job.next_run)}</div>
                    <div className="job-actions">
                      <span className="btn-run" onClick={() => run(job.id)}>▶ Run</span>
                      <span
                        className={`btn-edit${editingId === job.id ? ' active' : ''}`}
                        onClick={() => { setEditingId(id => id === job.id ? null : job.id); setEditErr('') }}
                      >✎ Edit</span>
                      <span className="btn-del" onClick={() => remove(job.id)}>✕</span>
                    </div>
                  </div>
                </div>

                {editingId === job.id && (
                  <JobForm
                    title={`Edit — ${job.id}`}
                    initial={{ job_id: job.id, schedule: job.schedule || '', prompt: job.prompt || '' }}
                    submitLabel="Save"
                    error={editErr}
                    onSubmit={form => save(job.id, form)}
                    onCancel={() => { setEditingId(null); setEditErr('') }}
                  />
                )}
              </div>
            ))
      }
    </>
  )
}
