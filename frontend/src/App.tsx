import { Link, NavLink, Outlet } from 'react-router-dom'
import { useTheme } from './theme'
import { BuildIcon, CatalogIcon, DatasetIcon, MoonIcon, PromptIcon, RunsIcon, SettingsIcon, SunIcon } from './components/icons'
import logoUrl from './logo.jpg'

const NAV = [
  {
    section: 'Benchmark',
    items: [
      { to: '/', label: 'Build', icon: BuildIcon, end: true },
      { to: '/runs', label: 'Runs', icon: RunsIcon, end: false },
    ],
  },
  {
    section: 'Library',
    items: [
      { to: '/datasets', label: 'Datasets', icon: DatasetIcon, end: false },
      { to: '/prompts', label: 'Prompts', icon: PromptIcon, end: false },
      { to: '/catalog', label: 'Catalog', icon: CatalogIcon, end: false },
    ],
  },
]

export default function App() {
  const { resolved, setPreference } = useTheme()
  const dark = resolved === 'dark'

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <Link to="/" className="brand">
          <span className="brand-mark">
            <img src={logoUrl} alt="" style={{ width: '100%', height: '100%', objectFit: 'contain', borderRadius: 'inherit' }} />
          </span>
          <div>
            COLOSSEUM
            <small>MODEL BENCHMARKING</small>
          </div>
        </Link>

        <nav className="sidebar-nav" aria-label="Main navigation">
          {NAV.map(group => (
            <div key={group.section} style={{ display: 'contents' }}>
              <span className="sidebar-section">{group.section}</span>
              {group.items.map(({ to, label, icon: Icon, end }) => (
                <NavLink key={to} to={to} end={end} className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
                  <Icon />
                  {label}
                </NavLink>
              ))}
            </div>
          ))}
        </nav>

        <div className="sidebar-footer">
          <NavLink to="/settings" className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
            <SettingsIcon />
            Settings
          </NavLink>
          <div className="theme-row">
            <span className="row" style={{ gap: '0.65rem' }}>
              {dark ? <MoonIcon width={16} height={16} /> : <SunIcon width={16} height={16} />}
              {dark ? 'Dark mode' : 'Light mode'}
            </span>
            <span className="switch">
              <input
                type="checkbox"
                checked={dark}
                aria-label="Toggle dark mode"
                onChange={event => setPreference(event.target.checked ? 'dark' : 'light')}
              />
              <i />
            </span>
          </div>
        </div>
      </aside>

      <div className="content">
        <div className="shell">
          <Outlet />
        </div>
      </div>
    </div>
  )
}
