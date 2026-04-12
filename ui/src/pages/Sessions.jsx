import { useEffect, useRef, useState } from 'react'
import { markdownToHtml } from '../markdownToHtml'

function relativeTime(isoStr) {
  const diff = Date.now() - new Date(isoStr).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  return `${Math.floor(hrs / 24)}d ago`
}

// Split a flat list of events into per-run arrays, delimited by session_start.
// Run N corresponds to persisted turn pair N.
function splitIntoRuns(events) {
  const runs = []
  let current = null
  for (const e of events) {
    if (e.type === 'session_start') {
      current = [e]
      runs.push(current)
    } else if (current) {
      current.push(e)
    }
  }
  return runs
}

function TraceBlock({ runEvents }) {
  const [open, setOpen] = useState(false)
  const [expandedTools, setExpandedTools] = useState(new Set())

  if (!runEvents || runEvents.length === 0) return null

  const planSummary = runEvents.find(e => e.type === 'plan_summary')

  // Group events by step_index to build per-executor sections
  const stepMap = {}
  for (const e of runEvents) {
    if (e.step_index == null) continue
    if (!stepMap[e.step_index]) stepMap[e.step_index] = []
    stepMap[e.step_index].push(e)
  }
  const steps = Object.keys(stepMap)
    .map(Number)
    .sort((a, b) => a - b)
    .map(idx => {
      const events = stepMap[idx]
      const start = events.find(e => e.type === 'executor_start')
      const done = events.find(e => e.type === 'executor_done')
      const calls = events.filter(e => e.type === 'tool_call')
      const results = events.filter(e => e.type === 'tool_result')
      return {
        idx,
        name: start?.executor_name || '',
        model: start?.model || '',
        skills: start?.skills_loaded || [],
        pairs: calls.map((tc, i) => ({ call: tc, result: results[i] ?? null })),
        reasoningSteps: done?.reasoning_steps || [],
      }
    })

  // Header label: actual resolved executor names
  const executorNames = steps.map(s => s.name).filter(Boolean)
  const label = executorNames.length > 0 ? `planner → ${executorNames.join(' → ')}` : 'trace'
  const firstModel = steps[0]?.model?.split(':').slice(1).join(':') || steps[0]?.model || ''
  const totalTools = steps.reduce((sum, s) => sum + s.pairs.length, 0)

  const toggleTool = key => setExpandedTools(prev => {
    const next = new Set(prev)
    next.has(key) ? next.delete(key) : next.add(key)
    return next
  })

  return (
    <div className="trace-card">
      <div className="trace-card-header" onClick={() => setOpen(o => !o)}>
        <div className="trace-card-left">
          <span className="trace-toggle">{open ? '▾' : '▸'}</span>
          <span className="trace-label-main">{label}</span>
          {firstModel && <span className="trace-model-chip">{firstModel}</span>}
        </div>
        {!open && totalTools > 0 && (
          <span className="trace-tool-count">{totalTools} tool{totalTools > 1 ? 's' : ''}</span>
        )}
      </div>

      {open && (
        <div className="trace-body">
          {/* Planner section */}
          {planSummary && (
            <div className="trace-planner-row">
              <div className="trace-section-label">Planner</div>
              <div className="trace-reasoning">
                <div><strong>Intent:</strong> {planSummary.intent}</div>
                <div><strong>Reasoning:</strong> {planSummary.reasoning}</div>
                {planSummary.steps?.length > 1 && (
                  <div className="trace-steps">
                    {planSummary.steps.map((s, i) => (
                      <div key={i} className="trace-step">
                        <span className="trace-executor-name">{s.executor}</span>: {s.instruction}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Per-executor sections */}
          {steps.map(({ idx, name, model, skills, pairs, reasoningSteps }) => {
            const stepModel = model?.split(':').slice(1).join(':') || model || ''
            return (
              <div key={idx} className="trace-executor-block">
                <div className="trace-executor-header">
                  <span className="trace-executor-label">{name || `step ${idx}`}</span>
                  {stepModel && <span className="trace-model-chip">{stepModel}</span>}
                </div>

                {skills.length > 0 && (
                  <div className="trace-planner-row">
                    <div className="trace-section-label">Skills</div>
                    <div className="trace-skills">
                      {skills.map(s => <span key={s} className="trace-skill-chip">{s}</span>)}
                    </div>
                  </div>
                )}

                {reasoningSteps.length > 1 && (
                  <div className="trace-planner-row">
                    <div className="trace-section-label">Reasoning</div>
                    <div className="trace-reasoning">
                      {reasoningSteps.slice(0, -1).map((step, i) => (
                        <div key={i} className="trace-reasoning-step">{step}</div>
                      ))}
                    </div>
                  </div>
                )}

                {pairs.map(({ call, result }, toolIdx) => {
                  const key = `${idx}-${toolIdx}`
                  return (
                    <div key={toolIdx} className="trace-tool-item">
                      <div className="trace-tool-header" onClick={() => toggleTool(key)}>
                        <span className="trace-tool-icon">🔧</span>
                        <span className="trace-tool-name">{call.tool_name}</span>
                        <span className="trace-tool-expand">{expandedTools.has(key) ? '▾' : '▸ collapsed'}</span>
                      </div>
                      {expandedTools.has(key) && (
                        <div className="trace-tool-detail">
                          <div className="trace-detail-label">Args</div>
                          <pre className="trace-code trace-code-args">{JSON.stringify(call.args, null, 2)}</pre>
                          {result && (
                            <>
                              <div className="trace-detail-label">Result</div>
                              <pre className="trace-code trace-code-result">{result.result}</pre>
                            </>
                          )}
                        </div>
                      )}
                    </div>
                  )
                })}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

function Timeline({ turns, runs, scrollContainerRef }) {
  const bottomRef = useRef(null)
  const userScrolledUp = useRef(false)

  useEffect(() => {
    const container = scrollContainerRef?.current
    if (!container) return
    const onScroll = () => {
      const atBottom = container.scrollHeight - container.scrollTop - container.clientHeight < 80
      userScrolledUp.current = !atBottom
    }
    container.addEventListener('scroll', onScroll, { passive: true })
    return () => container.removeEventListener('scroll', onScroll)
  }, [scrollContainerRef])

  useEffect(() => {
    if (turns.length === 0) userScrolledUp.current = false
    if (!userScrolledUp.current) {
      bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
    }
  }, [turns, runs])

  if (turns.length === 0 && runs.length === 0) {
    return <div className="empty-state">No turns yet</div>
  }

  const pairs = []
  for (let i = 0; i < turns.length; i += 2) {
    pairs.push({ user: turns[i], asst: turns[i + 1] })
  }

  // Active run = last run that hasn't received session_done yet
  const activeRun = runs.length > 0 && !runs[runs.length - 1].some(e => e.type === 'session_done')
    ? runs[runs.length - 1]
    : null

  // Completed live runs are all runs except the active one
  const completedLiveRuns = activeRun ? runs.slice(0, -1) : runs

  // Completed live runs map to the LAST N persisted pairs (not the first N).
  // This handles the case where the WebSocket connected mid-session and liveEvents
  // only contains events from the Nth run onwards.
  const pairOffset = Math.max(0, pairs.length - completedLiveRuns.length)

  const liveMessage = activeRun?.find(e => e.type === 'session_start')?.message

  return (
    <div className="timeline">
      {pairs.map(({ user, asst }, idx) => {
        const runIdx = idx - pairOffset
        const runEvents = runIdx >= 0 ? (completedLiveRuns[runIdx] || []) : []
        return (
          <div key={idx} className="turn-pair">
            {user && <div className="bubble user-bubble" dangerouslySetInnerHTML={{ __html: markdownToHtml(user.content) }} />}
            <TraceBlock runEvents={runEvents} />
            {asst && <div className="bubble asst-bubble" dangerouslySetInnerHTML={{ __html: markdownToHtml(asst.content) }} />}
          </div>
        )
      })}

      {activeRun && (
        <div className="turn-pair">
          {liveMessage && <div className="bubble user-bubble" dangerouslySetInnerHTML={{ __html: markdownToHtml(liveMessage) }} />}
          <TraceBlock runEvents={activeRun} />
          <div className="live-waiting">
            <span className="pulse-dot" />
            Waiting for next message…
          </div>
        </div>
      )}

      <div ref={bottomRef} />
    </div>
  )
}

export default function Sessions() {
  const [sessions, setSessions] = useState([])
  const [selectedId, setSelectedId] = useState(null)
  const [sessionData, setSessionData] = useState(null)
  const [traceEvents, setTraceEvents] = useState([])
  const scrollContainerRef = useRef(null)

  useEffect(() => {
    fetch('/api/sessions').then(r => r.json()).then(setSessions).catch(() => {})
  }, [])

  // Poll trace events for the selected session every 2 s.
  // Refreshes the session list whenever a run completes (session_done seen).
  useEffect(() => {
    if (!selectedId) { setTraceEvents([]); return }
    let active = true
    let prevDoneCount = 0

    const poll = async () => {
      while (active) {
        try {
          const events = await fetch(`/api/sessions/${selectedId}/trace`).then(r => r.json())
          if (!active) break
          setTraceEvents(events)
          const doneCount = events.filter(e => e.type === 'session_done').length
          if (doneCount > prevDoneCount) {
            prevDoneCount = doneCount
            fetch('/api/sessions').then(r => r.json()).then(setSessions).catch(() => {})
          }
        } catch {}
        await new Promise(r => setTimeout(r, 2000))
      }
    }
    poll()
    return () => { active = false }
  }, [selectedId])

  // Reload session detail whenever session list refreshes (catches new turns)
  useEffect(() => {
    if (!selectedId) { setSessionData(null); return }
    fetch(`/api/sessions/${selectedId}`)
      .then(r => r.ok ? r.json() : null)
      .then(setSessionData)
      .catch(() => setSessionData(null))
  }, [selectedId, sessions])

  const turns = sessionData?.turns || []
  const runs = splitIntoRuns(traceEvents)

  // Determine if there's an active run for the live dot in the session header
  const activeRun = runs.length > 0 && !runs[runs.length - 1].some(e => e.type === 'session_done')
    ? runs[runs.length - 1]
    : null
  const isSessionLive = Boolean(activeRun)

  return (
    <>
      <div className="page-header">
        <div className="page-title">Sessions</div>
        <div className="page-sub">Execution trace for each request</div>
      </div>

      <div className="sessions-layout">

        {/* Left: session list */}
        <div className="sessions-sidebar">
          <div className="sessions-sidebar-header">
            <span className="sessions-sidebar-title">Sessions</span>
            <span className="sessions-sidebar-count">{sessions.length} total</span>
          </div>
          <div className="sessions-sidebar-list">
            {sessions.length === 0 && <div className="empty-state">No sessions yet</div>}
            {sessions.map(s => (
              <div
                key={s.session_id}
                className={`session-item${selectedId === s.session_id ? ' active' : ''}`}
                onClick={() => setSelectedId(s.session_id)}
              >
                <div className="session-id">{s.session_id}</div>
                <div className="session-meta">{relativeTime(s.created_at)} · {s.turn_count} turn{s.turn_count !== 1 ? 's' : ''}</div>
                <div className="session-preview">{s.last_message}</div>
              </div>
            ))}
          </div>
        </div>

        {/* Right: session detail */}
        <div className="sessions-right">
          {!selectedId && <div className="empty-state" style={{ margin: 'auto' }}>Select a session to view its trace</div>}
          {selectedId && sessionData && (
            <div className="session-detail-header">
              <div>
                <span className="session-detail-id">{sessionData.session_id}</span>
                <span className="session-detail-time">Started {relativeTime(sessionData.created_at)}</span>
              </div>
              {isSessionLive && (
                <div className="session-live-indicator">
                  <span className="session-live-dot" />
                  live
                </div>
              )}
            </div>
          )}
          {selectedId && (
            <div className="sessions-scroll-wrap">
              <div className="sessions-scroll" ref={scrollContainerRef}>
                <Timeline turns={turns} runs={runs} scrollContainerRef={scrollContainerRef} />
              </div>
              <button
                className="scroll-bottom-btn"
                onClick={() => scrollContainerRef.current?.scrollTo({ top: scrollContainerRef.current.scrollHeight, behavior: 'smooth' })}
                title="Scroll to bottom"
              >↓</button>
            </div>
          )}
        </div>

      </div>
    </>
  )
}
