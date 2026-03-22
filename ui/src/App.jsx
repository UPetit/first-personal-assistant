import { BrowserRouter, NavLink, Route, Routes } from 'react-router-dom'
import { ToastProvider } from './components/Toast.jsx'
import Overview from './pages/Overview.jsx'
import Logs from './pages/Logs.jsx'
import Jobs from './pages/Jobs.jsx'
import Agents from './pages/Agents.jsx'
import Memory from './pages/Memory.jsx'
import Settings from './pages/Settings.jsx'
import Sessions from './pages/Sessions.jsx'

const MAIN_NAV = [
  { to: '/',       label: 'Overview', icon: '⬡', end: true },
  { to: '/logs',   label: 'Logs',     icon: '≡', badge: 'live' },
  { to: '/jobs',   label: 'Jobs',     icon: '⏱' },
  { to: '/sessions', label: 'Sessions', icon: '◎', badge: 'debug' },
]
const SYSTEM_NAV = [
  { to: '/agents',   label: 'Agents',   icon: '◈' },
  { to: '/memory',   label: 'Memory',   icon: '🧠' },
  { to: '/settings', label: 'Settings', icon: '⚙' },
]
const ALL_NAV = [...MAIN_NAV, ...SYSTEM_NAV]

export default function App() {
  return (
    <ToastProvider>
      <BrowserRouter>
        <div className="sb">
          <div className="logo">
            <div className="logo-icon">K</div>
            <div className="logo-name">K<em>ore</em></div>
          </div>

          <div className="nav-section">Main</div>
          {MAIN_NAV.map(({ to, label, icon, badge, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={({ isActive }) => 'nav-item' + (isActive ? ' active' : '')}
            >
              <span className="icon">{icon}</span>
              {label}
              {badge && <span className="nav-badge">{badge}</span>}
              {to === '/' && <div className="status-dot" style={{ marginLeft: 'auto' }} />}
            </NavLink>
          ))}

          <div className="nav-section">System</div>
          {SYSTEM_NAV.map(({ to, label, icon }) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) => 'nav-item' + (isActive ? ' active' : '')}
            >
              <span className="icon">{icon}</span>
              {label}
            </NavLink>
          ))}

          <div className="sb-footer">
            <div className="status-dot" />
            Agent online
          </div>
        </div>

        <div className="main">
          <Routes>
            <Route path="/"        element={<Overview />} />
            <Route path="/logs"    element={<Logs />} />
            <Route path="/jobs"    element={<Jobs />} />
            <Route path="/sessions" element={<Sessions />} />
            <Route path="/agents"  element={<Agents />} />
            <Route path="/memory"  element={<Memory />} />
            <Route path="/settings" element={<Settings />} />
          </Routes>
        </div>

        <nav className="bottom-nav">
          {ALL_NAV.map(({ to, label, icon, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={({ isActive }) => 'bottom-nav-item' + (isActive ? ' active' : '')}
            >
              <span className="bottom-nav-icon">{icon}</span>
              <span className="bottom-nav-label">{label}</span>
            </NavLink>
          ))}
        </nav>
      </BrowserRouter>
    </ToastProvider>
  )
}
