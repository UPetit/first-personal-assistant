import { useEffect, useRef, useState } from 'react'
import { useToast } from '../components/Toast.jsx'

function parseLevel(line) {
  // Extract level from its position in the formatted log line:
  // "YYYY-MM-DD HH:MM:SS,mmm LEVEL logger.name — message"
  // This avoids false positives from logger names like "uvicorn.error".
  const m = line.match(/^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}[.,\d]* ([A-Z]+) /)
  if (m) {
    const lvl = m[1]
    if (lvl === 'ERROR' || lvl === 'CRITICAL') return 'error'
    if (lvl === 'WARNING' || lvl === 'WARN')   return 'warn'
    if (lvl === 'INFO' && /\bTOOL\b|tool_call/i.test(line)) return 'tool'
    return 'info'
  }
  // Fallback for unformatted lines
  if (/\bTOOL\b|tool_call/i.test(line)) return 'tool'
  return 'info'
}

function parseTs(line) {
  const iso = line.match(/(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2})/)
  if (iso) return iso[1].replace('T', ' ')
  const t = line.match(/(\d{2}:\d{2}:\d{2})/)
  return t ? t[1] : ''
}

function stripPrefix(line) {
  // The formatter uses an em dash — (U+2014); also handle en dash and hyphen.
  return line.replace(/^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}[.,\d]* \w+ [\w.]+ [—–\-] /, '').trim()
}


function LogEntry({ line, idx, expanded, onToggle }) {
  const lvl   = parseLevel(line)
  const ts    = parseTs(line)
  const msg   = stripPrefix(line) || line
  const isOpen = expanded.has(idx)
  return (
    <div
      className={`log-entry${isOpen ? ' expanded' : ''}`}
      onClick={() => onToggle(idx)}
    >
      <span className="log-ts">{ts || '—'}</span>
      <span className={`lv-badge lv-${lvl}`}>{lvl.toUpperCase()}</span>
      <div className="log-body-wrap">
        <div className="log-body">{msg}</div>
        {isOpen && <div className="log-detail">{line}</div>}
      </div>
    </div>
  )
}

function LogColumn({ title, lines, filter, search, emptyMsg }) {
  const [expanded, setExpanded] = useState(new Set())
  const bottomRef = useRef(null)

  const toggle = idx => setExpanded(prev => {
    const next = new Set(prev)
    next.has(idx) ? next.delete(idx) : next.add(idx)
    return next
  })

  const visible = lines.filter(line => {
    if (filter !== 'all' && parseLevel(line) !== filter) return false
    if (search && !line.toLowerCase().includes(search.toLowerCase())) return false
    return true
  })

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [lines])

  return (
    <div className="log-col">
      <div className="log-col-header">{title}</div>
      <div className="log-col-scroll">
        {visible.length === 0
          ? <div className="empty-state">{emptyMsg}</div>
          : visible.map((line, i) => (
              <LogEntry
                key={i}
                line={line}
                idx={i}
                expanded={expanded}
                onToggle={toggle}
              />
            ))
        }
        <div ref={bottomRef} />
      </div>
    </div>
  )
}

export default function Logs() {
  const [lines, setLines]     = useState([])
  const [filter, setFilter]   = useState('all')
  const [search, setSearch]   = useState('')
  const [paused, setPaused]   = useState(false)
  const pausedRef = useRef(false)
  const { showToast } = useToast()

  useEffect(() => { pausedRef.current = paused }, [paused])

  useEffect(() => {
    const protocol = location.protocol === 'https:' ? 'wss' : 'ws'
    const ws = new WebSocket(`${protocol}://${location.host}/ws/logs`)
    ws.onmessage = e => {
      if (pausedRef.current) return
      setLines(prev => [...prev.slice(-499), e.data])
    }
    ws.onerror = () => showToast('Log stream disconnected', 'error')
    return () => ws.close()
  }, [])

  return (
    <>
      <div className="page-header">
        <div className="page-title">Logs</div>
        <div className="page-sub">Real-time gateway activity — click any entry to expand</div>
      </div>

      <div className="logs-toolbar">
        {[['all','All'],['info','INFO'],['warn','WARN'],['tool','TOOL'],['error','ERROR']].map(([val, lbl]) => (
          <span
            key={val}
            className={`filter-btn${filter === val ? ' active' : ''}${val === 'tool' ? ' ftool' : ''}${val === 'warn' ? ' fwarn' : ''}${val === 'error' ? ' ferror' : ''}`}
            onClick={() => setFilter(val)}
          >{lbl}</span>
        ))}
        <input
          className="search-input"
          placeholder="Search logs…"
          value={search}
          onChange={e => setSearch(e.target.value)}
        />
        <span
          className={`pause-btn${paused ? ' paused' : ''}`}
          onClick={() => setPaused(p => !p)}
        >{paused ? '▶ Resume' : '⏸ Pause'}</span>
      </div>

      <div className="log-columns">
        <LogColumn
          title="Gateway"
          lines={lines}
          filter={filter}
          search={search}
          emptyMsg={lines.length === 0 ? 'Waiting for logs…' : 'No entries match filter'}
        />
      </div>
    </>
  )
}
