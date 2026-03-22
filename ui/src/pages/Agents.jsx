import { useEffect, useState } from 'react'
import { useToast } from '../components/Toast.jsx'

function AgentCard({ name, role, model, tools, capabilities, isActive, activity, stats, lastRun, cost }) {
  const [modelBase, modelSuffix] = (model || '').split(':').length > 1
    ? ['', model]
    : [model?.replace(/[-\d.]+$/, '') || '', model?.match(/[-\d.]+$/)?.[0] || '']

  return (
    <div className={`agent-card${isActive ? ' is-active' : ''}`}>
      <div className="agent-header">
        <div>
          <div className="agent-name">{name}</div>
          <div className="agent-role">{role}</div>
        </div>
        <span className={isActive ? 'badge-active' : 'badge-idle'}>
          {isActive ? '● Active' : 'Idle'}
        </span>
      </div>

      <div className="agent-model">{model}</div>

      {(capabilities || tools)?.length > 0 && (
        <>
          <div className="tools-label">{capabilities ? 'Capabilities' : 'Tools'}</div>
          <div className="tools-list">
            {(capabilities || tools).map(t => (
              <span key={t} className="tool-tag">{t}</span>
            ))}
          </div>
        </>
      )}

      {isActive && activity ? (
        <div className="agent-activity">
          <div className="activity-dot" />
          {activity}
        </div>
      ) : (
        <div className="agent-footer">
          <div className="agent-stats">
            {stats?.map(({ v, l }) => (
              <div key={l}>
                <div className="agent-stat-v">{v}</div>
                <div className="agent-stat-l">{l}</div>
              </div>
            ))}
          </div>
          <div>
            {lastRun && <div className="agent-last">{lastRun}</div>}
            {cost    && <div className="agent-cost">{cost}</div>}
          </div>
        </div>
      )}
    </div>
  )
}

export default function Agents() {
  const [data, setData] = useState(null)
  const { showToast } = useToast()

  useEffect(() => {
    fetch('/api/agents')
      .then(r => r.json())
      .then(setData)
      .catch(e => showToast(e.message || 'Failed to load agents', 'error'))
  }, [])

  return (
    <>
      <div className="page-header">
        <div className="page-title">Agents</div>
        <div className="page-sub">Planner + executor pipeline</div>
      </div>

      {!data
        ? <div className="loading">Loading…</div>
        : (
          <div className="agents-grid">
            {data.planner && (
              <AgentCard
                name="Planner"
                role="Orchestrator"
                model={data.planner.model}
                capabilities={['intent classification', 'executor routing']}
                stats={[{ v: '—', l: 'Runs' }, { v: '—', l: 'Avg' }]}
                lastRun="last run: —"
              />
            )}
            {Object.entries(data.executors ?? {}).map(([name, exc]) => (
              <AgentCard
                key={name}
                name={name.charAt(0).toUpperCase() + name.slice(1)}
                role="Executor"
                model={exc.model}
                tools={exc.tools || []}
                stats={[{ v: '—', l: 'Runs' }, { v: '—', l: 'Avg' }]}
                lastRun="last run: —"
                cost="—"
              />
            ))}
          </div>
        )
      }
    </>
  )
}
