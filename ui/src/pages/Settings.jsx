import { useEffect, useState } from 'react'
import { useToast } from '../components/Toast.jsx'

function SettingRow({ label, value, highlight }) {
  return (
    <div className="setting-row">
      <span className="setting-label">{label}</span>
      <span className="setting-val" style={highlight ? { color: highlight } : {}}>{value ?? '—'}</span>
    </div>
  )
}

export default function Settings() {
  const [data, setData] = useState(null)
  const { showToast } = useToast()

  useEffect(() => {
    fetch('/api/agents')
      .then(r => r.json())
      .then(setData)
      .catch(e => showToast(e.message || 'Failed to load settings', 'error'))
  }, [])

  const execNames = Object.keys(data?.executors ?? {})

  return (
    <>
      <div className="page-header">
        <div className="page-title">Settings</div>
        <div className="page-sub">Read-only — edit config.json to make changes</div>
      </div>

      {!data
        ? <div className="loading">Loading…</div>
        : (
          <div className="settings-grid">
            <div className="card">
              <div className="card-title">Planner</div>
              <SettingRow label="Model"       value={data.planner?.model} />
              <SettingRow label="Prompt file" value={data.planner?.prompt_file} />
              <SettingRow label="Max retries" value={data.planner?.max_retries} />
            </div>

            <div className="card">
              <div className="card-title">Executors</div>
              <SettingRow label="Registered" value={execNames.join(', ') || 'none'} />
              {execNames.map(name => (
                <SettingRow key={name} label={name} value={data.executors[name]?.model} />
              ))}
            </div>

            {execNames.length > 0 && (
              <div className="card">
                <div className="card-title">Tools per Executor</div>
                {execNames.map(name => (
                  <SettingRow
                    key={name}
                    label={name}
                    value={(data.executors[name]?.tools || []).join(', ') || 'none'}
                  />
                ))}
              </div>
            )}

            <div className="card">
              <div className="card-title">Runtime</div>
              <SettingRow label="Config file" value="config.json" />
              <SettingRow label="Edit to change" value="restart required" highlight="rgba(251,191,36,0.7)" />
            </div>
          </div>
        )
      }
    </>
  )
}
