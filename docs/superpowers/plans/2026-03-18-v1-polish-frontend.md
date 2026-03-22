# v1 Polish — Frontend Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove hardcoded auth from the React dashboard, add a toast notification system for fetch errors, and add consistent loading states to `Overview.jsx` and `Jobs.jsx`.

**Architecture:** Three independent changes in `ui/src/`. B1 removes the `AUTH`/`headers()` export from `App.jsx` and the `Authorization` header from all six page components. B2 adds `ui/src/components/Toast.jsx` (React context + reducer, no external lib) and wires it into every page via a `useToast()` hook. B3 adds loading guards to `Overview.jsx` (boolean) and `Jobs.jsx` (null-guard). Each task ends with `npm run build` to verify no build errors.

**Tech Stack:** React 18, React Router v6, Vite 5. No new npm dependencies. No Jest/unit tests (explicitly out of scope for v1 — see spec). Build verification only.

**Prerequisite:** Sub-plan A must be merged first. `POST /api/message`, `PUT /api/memory`, and `DELETE /api/memory` now return `{"detail": {"detail": "Operation failed", "request_id": "..."}}` on error — this shape is what the toast messages will display.

---

## File Map

| File | Action | What changes |
|------|--------|-------------|
| `ui/src/App.jsx` | Modify | Remove `AUTH` + `headers()`, add `<ToastProvider>` wrapper |
| `ui/src/components/Toast.jsx` | Create | `ToastContext`, `ToastProvider`, `useToast()` hook |
| `ui/src/pages/Agents.jsx` | Modify | Remove auth header, add `useToast` |
| `ui/src/pages/Jobs.jsx` | Modify | Remove auth header, add `useToast`, add null loading guard |
| `ui/src/pages/Logs.jsx` | Modify | Add `useToast` on WebSocket error |
| `ui/src/pages/Memory.jsx` | Modify | Remove auth header, add `useToast` |
| `ui/src/pages/Overview.jsx` | Modify | Remove auth header, add `useToast`, add `loading` boolean |
| `ui/src/pages/Settings.jsx` | Modify | Remove auth header, add `useToast` |

---

## Task 1: Remove Auth Headers from Frontend

**Files:**
- Modify: `ui/src/App.jsx`
- Modify: `ui/src/pages/Agents.jsx`, `Jobs.jsx`, `Logs.jsx`, `Memory.jsx`, `Overview.jsx`, `Settings.jsx`

### Context

`App.jsx` exports `AUTH = btoa('admin:secret')` and `headers()` which every page imports to attach an `Authorization: Basic ...` header. The deployment is VPN-only with `api_auth_enabled: false`, so these credentials are unnecessary and the compiled JS bundles the cleartext password visible in browser devtools.

---

- [ ] **Step 1: Remove `AUTH` and `headers()` from `ui/src/App.jsx`**

Replace:
```jsx
// TODO: Replace hardcoded credentials with a login prompt storing token in sessionStorage.
// For v1 personal use only — do NOT expose this build on a public network.
const AUTH = btoa('admin:secret')
export const headers = () => ({ Authorization: `Basic ${AUTH}`, 'Content-Type': 'application/json' })
```

With: *(delete both lines entirely — nothing replaces them)*

- [ ] **Step 2: Update `ui/src/pages/Agents.jsx`**

Remove the `headers` import and auth header from the fetch call.

*Before:*
```jsx
import { headers } from '../App.jsx'
// ...
fetch('/api/agents', { headers: headers() })
```

*After:*
```jsx
// (remove the headers import line entirely)
// ...
fetch('/api/agents')
```

Full updated file:
```jsx
import { useEffect, useState } from 'react'

export default function Agents() {
  const [data, setData] = useState(null)

  useEffect(() => {
    fetch('/api/agents').then(r => r.json()).then(setData).catch(console.error)
  }, [])

  if (!data) return <p>Loading...</p>

  return (
    <div>
      <h2>Agents</h2>
      {data.planner && (
        <div>
          <h3>Planner</h3>
          <p>Model: {data.planner.model}</p>
        </div>
      )}
      <h3>Executors</h3>
      {Object.entries(data.executors ?? {}).map(([name, exc]) => (
        <div key={name} style={{ border: '1px solid #ccc', padding: '0.5rem', marginBottom: '0.5rem' }}>
          <strong>{name}</strong>: {exc.model}<br />
          {exc.description && <em>{exc.description}</em>}<br />
          Tools: {exc.tools?.join(', ') || 'none'}
        </div>
      ))}
    </div>
  )
}
```

- [ ] **Step 3: Update `ui/src/pages/Jobs.jsx`**

Remove `headers` import; replace all `headers()` calls — POST/DELETE bodies keep `'Content-Type': 'application/json'` but drop `Authorization`.

Full updated file (note: `useState(null)` for the null-guard loading state — Task 2 Step 4 adds `useToast` and the `if (!jobs) return <p>Loading...</p>` guard):
```jsx
import { useEffect, useState } from 'react'

export default function Jobs() {
  const [jobs, setJobs] = useState(null)
  const [form, setForm] = useState({ job_id: '', schedule: '', message: '' })
  const [error, setError] = useState('')

  const reload = () => fetch('/api/jobs').then(r => r.json()).then(setJobs).catch(console.error)
  useEffect(() => { reload() }, [])

  const create = async () => {
    setError('')
    const r = await fetch('/api/jobs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(form),
    })
    if (!r.ok) { setError((await r.json()).detail); return }
    setForm({ job_id: '', schedule: '', message: '' })
    reload()
  }

  const remove = async (id) => {
    await fetch(`/api/jobs/${id}`, { method: 'DELETE' })
    reload()
  }

  if (!jobs) return <p>Loading...</p>

  return (
    <div>
      <h2>Jobs</h2>
      <table border="1" cellPadding="4">
        <thead><tr><th>ID</th><th>Next Run</th><th></th></tr></thead>
        <tbody>{jobs.map(j => (
          <tr key={j.id}>
            <td>{j.id}</td><td>{j.next_run}</td>
            <td><button onClick={() => remove(j.id)}>Delete</button></td>
          </tr>
        ))}</tbody>
      </table>
      <h3>Add Job</h3>
      {error && <p style={{ color: 'red' }}>{error}</p>}
      <input placeholder="job_id" value={form.job_id} onChange={e => setForm(f => ({...f, job_id: e.target.value}))} />
      <input placeholder="0 8 * * *" value={form.schedule} onChange={e => setForm(f => ({...f, schedule: e.target.value}))} />
      <input placeholder="message" value={form.message} onChange={e => setForm(f => ({...f, message: e.target.value}))} />
      <button onClick={create}>Create</button>
    </div>
  )
}
```

- [ ] **Step 4: Update `ui/src/pages/Memory.jsx`**

Remove `headers` import; keep `Content-Type` for PUT body.

Full updated file:
```jsx
import { useEffect, useState } from 'react'

export default function Memory() {
  const [memory, setMemory] = useState(null)
  const [editPath, setEditPath] = useState('')
  const [editValue, setEditValue] = useState('')
  const [status, setStatus] = useState('')

  const reload = () => fetch('/api/memory').then(r => r.json()).then(setMemory).catch(console.error)
  useEffect(() => { reload() }, [])

  const update = async () => {
    setStatus('')
    const r = await fetch('/api/memory', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: editPath, value: editValue }),
    })
    setStatus(r.ok ? 'Updated' : 'Error')
    reload()
  }

  if (!memory) return <p>Loading...</p>

  return (
    <div>
      <h2>Core Memory</h2>
      <pre style={{ background: '#111', color: '#ccc', padding: '0.5rem' }}>
        {JSON.stringify(memory, null, 2)}
      </pre>
      <h3>Update</h3>
      <input placeholder="path (e.g. user.name)" value={editPath} onChange={e => setEditPath(e.target.value)} />
      <input placeholder="value" value={editValue} onChange={e => setEditValue(e.target.value)} />
      <button onClick={update}>Update</button>
      {status && <span> {status}</span>}
    </div>
  )
}
```

- [ ] **Step 5: Update `ui/src/pages/Overview.jsx`**

Remove `headers` import and `headers()` calls.

Full updated file (auth removed; loading state added in Task 3):
```jsx
import { useEffect, useState } from 'react'

export default function Overview() {
  const [logs, setLogs] = useState([])
  const [jobs, setJobs] = useState([])

  useEffect(() => {
    fetch('/api/logs?n=20').then(r => r.json()).then(setLogs).catch(console.error)
    fetch('/api/jobs').then(r => r.json()).then(setJobs).catch(console.error)
  }, [])

  return (
    <div>
      <h2>Overview</h2>
      <h3>Scheduled Jobs ({jobs.length})</h3>
      {jobs.length === 0 ? <p>No jobs scheduled.</p> : (
        <ul>{jobs.map(j => <li key={j.id}>{j.id} — next: {j.next_run}</li>)}</ul>
      )}
      <h3>Recent Logs</h3>
      <pre style={{ background: '#111', color: '#ccc', padding: '0.5rem', maxHeight: '300px', overflow: 'auto' }}>
        {logs.slice().reverse().join('\n') || '(no logs yet)'}
      </pre>
    </div>
  )
}
```

- [ ] **Step 6: Update `ui/src/pages/Settings.jsx`**

Full updated file:
```jsx
import { useEffect, useState } from 'react'

export default function Settings() {
  const [agents, setAgents] = useState(null)

  useEffect(() => {
    fetch('/api/agents').then(r => r.json()).then(setAgents).catch(console.error)
  }, [])

  return (
    <div>
      <h2>Settings</h2>
      <p>Read-only configuration view. Edit config.json to make changes.</p>
      {agents && (
        <pre style={{ background: '#111', color: '#ccc', padding: '0.5rem' }}>
          {JSON.stringify(agents, null, 2)}
        </pre>
      )}
    </div>
  )
}
```

- [ ] **Step 7: `Logs.jsx` has no auth header — verify and leave unchanged**

`Logs.jsx` uses only WebSocket — no `headers` import, no auth. No changes needed.

- [ ] **Step 8: Build to verify no errors**

```bash
cd /root/kore-ai/ui && npm run build 2>&1 | tail -20
```

Expected: clean build, no errors about missing `headers` export.

- [ ] **Step 9: Commit**

```bash
cd /root/kore-ai
git add ui/src/App.jsx ui/src/pages/
git commit -m "fix: remove hardcoded auth headers from frontend — VPN-only deployment needs no credentials"
```

---

## Task 2: Toast Notification System

**Files:**
- Create: `ui/src/components/Toast.jsx`
- Modify: `ui/src/App.jsx`
- Modify: all 6 page components

### Context

All page components currently call `.catch(console.error)` — errors are silent in the UI. This task adds a `ToastContext` with a `useToast()` hook so pages can show brief error messages without per-page error state.

The toast system is self-contained in one file, uses no external dependencies, and auto-dismisses after 4 seconds.

---

- [ ] **Step 1: Create `ui/src/components/Toast.jsx`**

```jsx
import { createContext, useCallback, useContext, useReducer } from 'react'

const ToastContext = createContext(null)

function reducer(state, action) {
  switch (action.type) {
    case 'ADD':
      return [...state, { id: action.id, message: action.message, variant: action.variant }]
    case 'REMOVE':
      return state.filter(t => t.id !== action.id)
    default:
      return state
  }
}

const VARIANTS = {
  error: { background: '#c62828', color: '#fff' },
  info:  { background: '#1565c0', color: '#fff' },
}

export function ToastProvider({ children }) {
  const [toasts, dispatch] = useReducer(reducer, [])

  const showToast = useCallback((message, variant = 'info') => {
    const id = Date.now() + Math.random()
    dispatch({ type: 'ADD', id, message, variant })
    setTimeout(() => dispatch({ type: 'REMOVE', id }), 4000)
  }, [])

  return (
    <ToastContext.Provider value={{ showToast }}>
      {children}
      <div style={{ position: 'fixed', top: '1rem', right: '1rem', zIndex: 9999, display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
        {toasts.map(t => (
          <div key={t.id} style={{ ...VARIANTS[t.variant] || VARIANTS.info, padding: '0.75rem 1rem', borderRadius: '4px', maxWidth: '320px', display: 'flex', alignItems: 'center', gap: '0.75rem', boxShadow: '0 2px 8px rgba(0,0,0,0.3)' }}>
            <span style={{ flex: 1, fontSize: '0.9rem' }}>{t.message}</span>
            <button onClick={() => dispatch({ type: 'REMOVE', id: t.id })} style={{ background: 'none', border: 'none', color: 'inherit', cursor: 'pointer', fontSize: '1rem', lineHeight: 1 }}>×</button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  )
}

export function useToast() {
  const ctx = useContext(ToastContext)
  if (!ctx) throw new Error('useToast must be used inside <ToastProvider>')
  return ctx
}
```

- [ ] **Step 2: Wrap router in `<ToastProvider>` in `ui/src/App.jsx`**

*Before:*
```jsx
import { BrowserRouter, NavLink, Route, Routes } from 'react-router-dom'
import Overview from './pages/Overview.jsx'
// ... other imports

export default function App() {
  return (
    <BrowserRouter>
      ...
    </BrowserRouter>
  )
}
```

*After:*
```jsx
import { BrowserRouter, NavLink, Route, Routes } from 'react-router-dom'
import { ToastProvider } from './components/Toast.jsx'
import Overview from './pages/Overview.jsx'
import Logs from './pages/Logs.jsx'
import Jobs from './pages/Jobs.jsx'
import Agents from './pages/Agents.jsx'
import Memory from './pages/Memory.jsx'
import Settings from './pages/Settings.jsx'

const NAV = [
  { to: '/', label: 'Overview' },
  { to: '/logs', label: 'Logs' },
  { to: '/jobs', label: 'Jobs' },
  { to: '/agents', label: 'Agents' },
  { to: '/memory', label: 'Memory' },
  { to: '/settings', label: 'Settings' },
]

export default function App() {
  return (
    <ToastProvider>
      <BrowserRouter>
        <nav style={{ display: 'flex', gap: '1rem', padding: '0.5rem 1rem', background: '#1a1a2e', color: '#eee' }}>
          <strong style={{ marginRight: '1rem' }}>Kore AI</strong>
          {NAV.map(({ to, label }) => (
            <NavLink key={to} to={to} end={to === '/'} style={({ isActive }) => ({ color: isActive ? '#90caf9' : '#ccc', textDecoration: 'none' })}>
              {label}
            </NavLink>
          ))}
        </nav>
        <main style={{ padding: '1rem' }}>
          <Routes>
            <Route path="/" element={<Overview />} />
            <Route path="/logs" element={<Logs />} />
            <Route path="/jobs" element={<Jobs />} />
            <Route path="/agents" element={<Agents />} />
            <Route path="/memory" element={<Memory />} />
            <Route path="/settings" element={<Settings />} />
          </Routes>
        </main>
      </BrowserRouter>
    </ToastProvider>
  )
}
```

- [ ] **Step 3: Add `useToast` to `Agents.jsx`**

Replace `.catch(console.error)` with toast:

```jsx
import { useEffect, useState } from 'react'
import { useToast } from '../components/Toast.jsx'

export default function Agents() {
  const [data, setData] = useState(null)
  const { showToast } = useToast()

  useEffect(() => {
    fetch('/api/agents')
      .then(r => r.json())
      .then(setData)
      .catch(e => showToast(e.message || 'Failed to load agents', 'error'))
  }, [])

  if (!data) return <p>Loading...</p>

  return (
    <div>
      <h2>Agents</h2>
      {data.planner && (
        <div>
          <h3>Planner</h3>
          <p>Model: {data.planner.model}</p>
        </div>
      )}
      <h3>Executors</h3>
      {Object.entries(data.executors ?? {}).map(([name, exc]) => (
        <div key={name} style={{ border: '1px solid #ccc', padding: '0.5rem', marginBottom: '0.5rem' }}>
          <strong>{name}</strong>: {exc.model}<br />
          {exc.description && <em>{exc.description}</em>}<br />
          Tools: {exc.tools?.join(', ') || 'none'}
        </div>
      ))}
    </div>
  )
}
```

- [ ] **Step 4: Add `useToast` to `Jobs.jsx`**

Replace `.catch(console.error)` with toast on `reload`:

```jsx
import { useEffect, useState } from 'react'
import { useToast } from '../components/Toast.jsx'

export default function Jobs() {
  const [jobs, setJobs] = useState(null)
  const [form, setForm] = useState({ job_id: '', schedule: '', message: '' })
  const [error, setError] = useState('')
  const { showToast } = useToast()

  const reload = () =>
    fetch('/api/jobs')
      .then(r => r.json())
      .then(setJobs)
      .catch(e => showToast(e.message || 'Failed to load jobs', 'error'))
  useEffect(() => { reload() }, [])

  const create = async () => {
    setError('')
    const r = await fetch('/api/jobs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(form),
    })
    if (!r.ok) { setError((await r.json()).detail); return }
    setForm({ job_id: '', schedule: '', message: '' })
    reload()
  }

  const remove = async (id) => {
    await fetch(`/api/jobs/${id}`, { method: 'DELETE' })
    reload()
  }

  if (!jobs) return <p>Loading...</p>

  return (
    <div>
      <h2>Jobs</h2>
      <table border="1" cellPadding="4">
        <thead><tr><th>ID</th><th>Next Run</th><th></th></tr></thead>
        <tbody>{jobs.map(j => (
          <tr key={j.id}>
            <td>{j.id}</td><td>{j.next_run}</td>
            <td><button onClick={() => remove(j.id)}>Delete</button></td>
          </tr>
        ))}</tbody>
      </table>
      <h3>Add Job</h3>
      {error && <p style={{ color: 'red' }}>{error}</p>}
      <input placeholder="job_id" value={form.job_id} onChange={e => setForm(f => ({...f, job_id: e.target.value}))} />
      <input placeholder="0 8 * * *" value={form.schedule} onChange={e => setForm(f => ({...f, schedule: e.target.value}))} />
      <input placeholder="message" value={form.message} onChange={e => setForm(f => ({...f, message: e.target.value}))} />
      <button onClick={create}>Create</button>
    </div>
  )
}
```

Note: `jobs` state now initialises to `null` (not `[]`) so the null-guard loading state from Task 3 is already included here.

- [ ] **Step 5: Add `useToast` to `Logs.jsx`**

`Logs.jsx` uses WebSocket, not fetch. Add toast on WebSocket error:

```jsx
import { useEffect, useRef, useState } from 'react'
import { useToast } from '../components/Toast.jsx'

export default function Logs() {
  const [lines, setLines] = useState([])
  const bottomRef = useRef(null)
  const { showToast } = useToast()

  useEffect(() => {
    const protocol = location.protocol === 'https:' ? 'wss' : 'ws'
    const ws = new WebSocket(`${protocol}://${location.host}/ws/logs`)
    ws.onmessage = e => setLines(prev => [...prev.slice(-499), e.data])
    ws.onerror = () => showToast('Log stream disconnected', 'error')
    return () => ws.close()
  }, [])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [lines])

  return (
    <div>
      <h2>Live Logs</h2>
      <pre style={{ background: '#111', color: '#ccc', padding: '0.5rem', height: '70vh', overflow: 'auto', fontSize: '0.8rem' }}>
        {lines.join('\n') || 'Waiting for logs...'}
        <div ref={bottomRef} />
      </pre>
    </div>
  )
}
```

- [ ] **Step 6: Add `useToast` to `Memory.jsx`**

```jsx
import { useEffect, useState } from 'react'
import { useToast } from '../components/Toast.jsx'

export default function Memory() {
  const [memory, setMemory] = useState(null)
  const [editPath, setEditPath] = useState('')
  const [editValue, setEditValue] = useState('')
  const [status, setStatus] = useState('')
  const { showToast } = useToast()

  const reload = () =>
    fetch('/api/memory')
      .then(r => r.json())
      .then(setMemory)
      .catch(e => showToast(e.message || 'Failed to load memory', 'error'))
  useEffect(() => { reload() }, [])

  const update = async () => {
    setStatus('')
    const r = await fetch('/api/memory', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: editPath, value: editValue }),
    })
    if (r.ok) {
      setStatus('Updated')
    } else {
      setStatus('Error')
      showToast('Failed to update memory', 'error')
    }
    reload()
  }

  if (!memory) return <p>Loading...</p>

  return (
    <div>
      <h2>Core Memory</h2>
      <pre style={{ background: '#111', color: '#ccc', padding: '0.5rem' }}>
        {JSON.stringify(memory, null, 2)}
      </pre>
      <h3>Update</h3>
      <input placeholder="path (e.g. user.name)" value={editPath} onChange={e => setEditPath(e.target.value)} />
      <input placeholder="value" value={editValue} onChange={e => setEditValue(e.target.value)} />
      <button onClick={update}>Update</button>
      {status && <span> {status}</span>}
    </div>
  )
}
```

- [ ] **Step 7: Add `useToast` to `Overview.jsx`**

```jsx
import { useEffect, useState } from 'react'
import { useToast } from '../components/Toast.jsx'

export default function Overview() {
  const [logs, setLogs] = useState([])
  const [jobs, setJobs] = useState([])
  const [loading, setLoading] = useState(true)
  const { showToast } = useToast()

  useEffect(() => {
    Promise.all([
      fetch('/api/logs?n=20').then(r => r.json()),
      fetch('/api/jobs').then(r => r.json()),
    ])
      .then(([logsData, jobsData]) => {
        setLogs(logsData)
        setJobs(jobsData)
      })
      .catch(e => showToast(e.message || 'Failed to load overview', 'error'))
      .finally(() => setLoading(false))
  }, [])

  if (loading) return <p>Loading...</p>

  return (
    <div>
      <h2>Overview</h2>
      <h3>Scheduled Jobs ({jobs.length})</h3>
      {jobs.length === 0 ? <p>No jobs scheduled.</p> : (
        <ul>{jobs.map(j => <li key={j.id}>{j.id} — next: {j.next_run}</li>)}</ul>
      )}
      <h3>Recent Logs</h3>
      <pre style={{ background: '#111', color: '#ccc', padding: '0.5rem', maxHeight: '300px', overflow: 'auto' }}>
        {logs.slice().reverse().join('\n') || '(no logs yet)'}
      </pre>
    </div>
  )
}
```

- [ ] **Step 8: Add `useToast` to `Settings.jsx`**

```jsx
import { useEffect, useState } from 'react'
import { useToast } from '../components/Toast.jsx'

export default function Settings() {
  const [agents, setAgents] = useState(null)
  const { showToast } = useToast()

  useEffect(() => {
    fetch('/api/agents')
      .then(r => r.json())
      .then(setAgents)
      .catch(e => showToast(e.message || 'Failed to load settings', 'error'))
  }, [])

  return (
    <div>
      <h2>Settings</h2>
      <p>Read-only configuration view. Edit config.json to make changes.</p>
      {agents && (
        <pre style={{ background: '#111', color: '#ccc', padding: '0.5rem' }}>
          {JSON.stringify(agents, null, 2)}
        </pre>
      )}
    </div>
  )
}
```

- [ ] **Step 9: Build to verify no errors**

```bash
cd /root/kore-ai/ui && npm run build 2>&1 | tail -20
```

Expected: clean build output ending with something like:
```
✓ built in Xs
```
No `Cannot find module`, no `is not defined`, no TypeScript/JSX errors.

- [ ] **Step 10: Commit**

```bash
cd /root/kore-ai
git add ui/src/components/Toast.jsx ui/src/App.jsx ui/src/pages/
git commit -m "feat: toast notification system — useToast hook, auto-dismiss 4s, error/info variants"
```

---

## Task 3: Verification — Loading States for `Overview.jsx` and `Jobs.jsx`

**Files:**
- Already handled in Task 2 above.

### Context

`Overview.jsx` and `Jobs.jsx` were updated in Task 2 steps 7 and 4 respectively:
- `Jobs.jsx` initialises `jobs` to `null` (not `[]`) and has `if (!jobs) return <p>Loading...</p>`.
- `Overview.jsx` uses a `loading` boolean set via `Promise.all(...).finally(() => setLoading(false))`.

Both loading guards are already in the code written in Task 2. No separate implementation step is needed.

- [ ] **Step 1: Verify loading guards are present**

After Task 2, check:
- `ui/src/pages/Jobs.jsx` contains `const [jobs, setJobs] = useState(null)` and `if (!jobs) return <p>Loading...</p>`
- `ui/src/pages/Overview.jsx` contains `const [loading, setLoading] = useState(true)` and `if (loading) return <p>Loading...</p>`

```bash
grep -n "Loading" ui/src/pages/Jobs.jsx ui/src/pages/Overview.jsx
```

Expected: both files contain the loading guard.

- [ ] **Step 2: Run final build + full Python test suite**

```bash
cd /root/kore-ai/ui && npm run build 2>&1 | tail -10
cd /root/kore-ai && python3 -m pytest --tb=short -q
```

Expected: clean build, all Python tests pass (no regressions from frontend changes — the Python suite doesn't test JSX).

- [ ] **Step 3: Commit (if not already committed in Task 2)**

If there are uncommitted changes after verifying:
```bash
cd /root/kore-ai
git add ui/src/pages/Jobs.jsx ui/src/pages/Overview.jsx
git commit -m "fix: loading states for Overview and Jobs pages"
```

---

## Verification Checklist

After all three tasks:

- [ ] `cd ui && npm run build` — clean build, no warnings about missing exports
- [ ] `ui/src/App.jsx` — no `AUTH`, no `headers()` export, has `<ToastProvider>` wrapper
- [ ] `ui/src/components/Toast.jsx` exists with `ToastProvider` and `useToast()` export
- [ ] All 6 page components — no `import { headers }`, no `Authorization` header, all have `useToast`
- [ ] All 6 page components — no `.catch(console.error)` remaining; each has `.catch(e => showToast(e.message || '...', 'error'))` or equivalent toast call (Logs.jsx: `ws.onerror = () => showToast(...)`)
- [ ] `ui/src/pages/Jobs.jsx` — `useState(null)` + `if (!jobs) return <p>Loading...</p>`
- [ ] `ui/src/pages/Overview.jsx` — `useState(true)` loading boolean + `Promise.all` + `finally`
- [ ] `python3 -m pytest --tb=short -q` — all tests still pass (Python suite unaffected)
