import { useCallback, useEffect, useState } from 'react'
import { useToast } from '../components/Toast.jsx'

function SkillCard({ name, emoji, description, always_on, required_tools, required_bins, required_env, active, missing }) {
  const allTags = [
    ...required_tools.map(t => ({ label: t, key: 'tool-' + t })),
    ...required_bins.map(b => ({ label: b, key: 'bin-' + b })),
    ...required_env.map(e => ({ label: e, key: 'env-' + e })),
  ]
  return (
    <div className={`card${!active ? ' skill-card-warn' : ''}`}>
      <div className="agent-header">
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span style={{ fontSize: '18px', lineHeight: 1 }}>{emoji}</span>
          <div className="agent-name">{name}</div>
        </div>
        {always_on && <span className="always-tag">always-on</span>}
      </div>
      <div className="agent-role" style={{ margin: '6px 0 8px' }}>{description}</div>
      {allTags.length > 0 && (
        <div className="tools-list">
          {allTags.map(({ label, key }) => (
            <span key={key} className="tool-tag">{label}</span>
          ))}
        </div>
      )}
      {!active && missing.length > 0 && (
        <div className="skill-missing">⚠ missing: {missing.join(', ')}</div>
      )}
    </div>
  )
}

function SkillSection({ title, skills, emptyMessage }) {
  return (
    <div className="skill-section">
      <div className="card-title">{title} · {skills.length}</div>
      {skills.length === 0 ? (
        <div className="skill-empty">
          {emptyMessage}
        </div>
      ) : (
        <div className="agents-grid">
          {skills.map(s => <SkillCard key={s.name} {...s} />)}
        </div>
      )}
    </div>
  )
}

export default function Skills() {
  const [data, setData] = useState(null)
  const { showToast } = useToast()

  const load = useCallback(() => {
    fetch('/api/skills')
      .then(r => r.json())
      .then(setData)
      .catch(e => showToast(e.message || 'Failed to load skills', 'error'))
  }, [showToast])

  useEffect(() => { load() }, [load])

  return (
    <>
      <div className="page-header">
        <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between' }}>
          <div>
            <div className="page-title">Skills</div>
            <div className="page-sub">Built-in and workspace skill library</div>
          </div>
          <button className="card-action" onClick={load} style={{ fontSize: '12px', padding: '4px 10px' }}>
            ↺ Reload
          </button>
        </div>
      </div>

      {!data ? (
        <div className="loading">Loading…</div>
      ) : (
        <>
          <SkillSection title="Built-in" skills={data.builtin} emptyMessage="No built-in skills found" />
          <SkillSection title="Workspace" skills={data.user} emptyMessage="Drop a SKILL.md into ~/.kore/data/skills/ to add your own" />
        </>
      )}
    </>
  )
}
