import { useEffect, useState } from 'react'
import { useToast } from '../components/Toast.jsx'

// Infer category from memory path
function inferCategory(path) {
  const p = path.toLowerCase()
  if (p.startsWith('preferences') || p.startsWith('prefs') || p.includes('preference')) return 'pref'
  if (p.startsWith('projects') || p.includes('project')) return 'proj'
  if (p.startsWith('corrections') || p.includes('correction') || p.includes('corrected')) return 'corr'
  return 'fact'
}

function catClass(cat) {
  return { fact: 'cat-fact', pref: 'cat-pref', proj: 'cat-proj', corr: 'cat-corr' }[cat] || 'cat-fact'
}
function catLabel(cat) {
  return { fact: 'Fact', pref: 'Pref', proj: 'Project', corr: 'Correction' }[cat] || 'Fact'
}

// Flatten nested object into [{path, value}] pairs
function flatten(obj, prefix = '') {
  const items = []
  for (const [k, v] of Object.entries(obj || {})) {
    const path = prefix ? `${prefix}.${k}` : k
    if (v !== null && typeof v === 'object' && !Array.isArray(v)) {
      items.push(...flatten(v, path))
    } else {
      items.push({ path, value: Array.isArray(v) ? JSON.stringify(v) : String(v ?? '') })
    }
  }
  return items
}

// Approximate token count (4 chars ≈ 1 token)
function approxTokens(obj) {
  return Math.round(JSON.stringify(obj || {}).length / 4)
}

const FILTER_OPTS = [
  ['all', 'All'], ['fact', 'Facts'], ['pref', 'Preferences'],
  ['proj', 'Projects'], ['corr', 'Corrections'],
]

export default function Memory() {
  const [memory, setMemory]     = useState(null)
  const [filter, setFilter]     = useState('all')
  const [search, setSearch]     = useState('')
  const [editPath, setEditPath] = useState('')
  const [editValue, setEditValue] = useState('')
  const [showForm, setShowForm] = useState(false)
  const { showToast } = useToast()

  const reload = () =>
    fetch('/api/memory').then(r => r.json()).then(setMemory)
      .catch(e => showToast(e.message || 'Failed to load memory', 'error'))

  useEffect(() => { reload() }, [])

  const update = async () => {
    const r = await fetch('/api/memory', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: editPath, value: editValue }),
    })
    if (r.ok) {
      showToast('Memory updated', 'info')
      setEditPath(''); setEditValue(''); setShowForm(false)
      reload()
    } else {
      showToast('Failed to update memory', 'error')
    }
  }

  const del = async (path) => {
    const r = await fetch(`/api/memory/${encodeURIComponent(path)}`, { method: 'DELETE' })
    if (r.ok) { showToast('Deleted', 'info'); reload() }
    else showToast('Failed to delete', 'error')
  }

  const items = flatten(memory)
  const tokens = approxTokens(memory)
  const tokenPct = Math.min(100, Math.round((tokens / 4000) * 100))

  const visible = items.filter(({ path, value }) => {
    const cat = inferCategory(path)
    if (filter !== 'all' && cat !== filter) return false
    if (search && !path.toLowerCase().includes(search.toLowerCase()) &&
        !value.toLowerCase().includes(search.toLowerCase())) return false
    return true
  })

  return (
    <>
      <div className="page-header">
        <div className="page-title">Memory</div>
        <div className="page-sub">Core memory — always in agent context</div>
      </div>

      <div className="memory-top">
        {FILTER_OPTS.map(([val, lbl]) => (
          <span
            key={val}
            className={`filter-btn${filter === val ? ' active' : ''}`}
            onClick={() => setFilter(val)}
          >{lbl}</span>
        ))}
        <input
          className="search-input"
          placeholder="Search memories…"
          value={search}
          onChange={e => setSearch(e.target.value)}
          style={{ marginLeft: 'auto' }}
        />
        <button className="add-btn" onClick={() => setShowForm(f => !f)}>
          {showForm ? '✕ Cancel' : '+ Add'}
        </button>
      </div>

      {showForm && (
        <div className="mem-form">
          <div className="mem-form-title">Update Memory</div>
          <div className="mem-form-row">
            <input
              className="mem-input"
              placeholder="path (e.g. user.name)"
              value={editPath}
              onChange={e => setEditPath(e.target.value)}
            />
            <input
              className="mem-input"
              placeholder="value"
              value={editValue}
              onChange={e => setEditValue(e.target.value)}
            />
            <button className="mem-save-btn" onClick={update}>Save</button>
          </div>
        </div>
      )}

      {memory !== null && (
        <div className="token-bar-wrap">
          <div className="token-bar-label">
            <span>Token usage</span>
            <span>{tokens.toLocaleString()} / 4,000 tokens</span>
          </div>
          <div className="token-bar">
            <div className="token-bar-fill" style={{ width: `${tokenPct}%` }} />
          </div>
        </div>
      )}

      {memory === null
        ? <div className="loading">Loading…</div>
        : visible.length === 0
          ? <div className="empty-state">
              {items.length === 0 ? 'No memories yet' : 'No entries match filter'}
            </div>
          : visible.map(({ path, value }) => {
              const cat = inferCategory(path)
              return (
                <div key={path} className="mem-item">
                  <span className={`mem-cat ${catClass(cat)}`}>{catLabel(cat)}</span>
                  <div className="mem-body">
                    <div className="mem-content">{value}</div>
                    <div className="mem-meta">
                      <span className="mem-path">{path}</span>
                      <span className="mem-src">core</span>
                    </div>
                  </div>
                  <button className="mem-del-btn" onClick={() => del(path)}>✕</button>
                </div>
              )
            })
      }
    </>
  )
}
