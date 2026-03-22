import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useToast } from '../components/Toast.jsx'

const SPARK_MEM  = [6, 8, 9, 11, 13, 15, 18]

function Sparkline({ heights, color }) {
  const max = Math.max(...heights)
  return (
    <div className="stat-sparkline">
      {heights.map((h, i) => (
        <div key={i} className="spark-bar"
          style={{ height: `${Math.round((h / max) * 20)}px`, background: color }} />
      ))}
    </div>
  )
}

export default function Overview() {
  const [jobs, setJobs] = useState([])
  const [secs, setSecs] = useState(44 * 60 + 58)
  const { showToast } = useToast()
  const navigate = useNavigate()

  useEffect(() => {
    fetch('/api/jobs').then(r => r.json()).then(setJobs)
      .catch(e => showToast(e.message || 'Failed to load', 'error'))
  }, [])

  useEffect(() => {
    const t = setInterval(() => setSecs(s => (s > 0 ? s - 1 : 7200)), 1000)
    return () => clearInterval(t)
  }, [])

  const fmtCountdown = s => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`

  const fmtNextRun = job => {
    if (!job.next_run) return '—'
    const diff = Math.round((new Date(job.next_run) - Date.now()) / 1000)
    if (diff < 0) return 'overdue'
    if (diff < 3600) return `in ${Math.floor(diff / 60)}m`
    return `in ${Math.floor(diff / 3600)}h ${Math.floor((diff % 3600) / 60)}m`
  }

  return (
    <>
      <div className="page-header">
        <div className="page-title">Overview</div>
        <div className="page-sub">Live system status</div>
      </div>

      <div className="stats-grid">
        <div className="stat-card">
          <div className="stat-label">Status</div>
          <div className="stat-value" style={{ fontSize: 14, color: '#22c55e', display: 'flex', alignItems: 'center', gap: 6, marginTop: 7 }}>
            <div style={{ width: 7, height: 7, borderRadius: '50%', background: '#22c55e', animation: 'pulse-ring 2s ease-out infinite', flexShrink: 0 }} />
            Running
          </div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Active Jobs</div>
          <div className="stat-value" style={{ color: '#22d3ee' }}>{jobs.length}</div>
          <div className="stat-sub">next in <span style={{ color: '#22d3ee' }}>{fmtCountdown(secs)}</span></div>
          <div className="stat-sparkline">
            {[0.3,0.3,0.6,0.3,0.6,0.3,0.9].map((o, i) => (
              <div key={i} className="spark-bar" style={{ height: 8, background: `rgba(34,211,238,${o})` }} />
            ))}
          </div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Memories</div>
          <div className="stat-value" style={{ color: '#fbbf24' }}>—</div>
          <div className="stat-sub">core memory</div>
          <Sparkline heights={SPARK_MEM} color="rgba(251,191,36,0.6)" />
        </div>
      </div>

      <div className="two-col">
        <div className="card">
          <div className="card-header">
            <div className="card-title">Scheduled Jobs</div>
            <button className="card-action" onClick={() => navigate('/jobs')}>Manage →</button>
          </div>
          {jobs.length === 0
            ? <div className="loading">No jobs</div>
            : jobs.slice(0, 4).map(job => (
                <div key={job.id} className="job-row">
                  <span className="job-name-sm">{job.id}</span>
                  <span className="job-cron-sm">{job.schedule || '—'}</span>
                  <span className="job-next-sm">{fmtNextRun(job)}</span>
                </div>
              ))
          }
        </div>
      </div>
    </>
  )
}
