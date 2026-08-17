import { createContext, useContext, useEffect, useState } from 'react'
import { Link, NavLink, Outlet } from 'react-router-dom'
import { useTheme } from './theme'
import { BuildIcon, CatalogIcon, ChevronLeftIcon, ChevronRightIcon, DatasetIcon, MoonIcon, PromptIcon, RunsIcon, SettingsIcon, SunIcon } from './components/icons'
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

const SIDEBAR_STORAGE_KEY = 'colosseum_sidebar_collapsed_v2'
const UI_MODE_STORAGE_KEY = 'colosseum_ui_mode'

export type UiMode = 'v1' | 'v2'
export const UiModeContext = createContext<{ mode: UiMode; setMode: (mode: UiMode) => void }>({ mode: 'v2', setMode: () => undefined })
export const useUiMode = () => useContext(UiModeContext)

export default function App() {
  const { resolved, setPreference } = useTheme()
  const dark = resolved === 'dark'
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => localStorage.getItem(SIDEBAR_STORAGE_KEY) !== 'false')
  const [uiMode, setUiMode] = useState<UiMode>(() => localStorage.getItem(UI_MODE_STORAGE_KEY) === 'v1' ? 'v1' : 'v2')

  useEffect(() => {
    localStorage.setItem(SIDEBAR_STORAGE_KEY, String(sidebarCollapsed))
  }, [sidebarCollapsed])

  useEffect(() => {
    localStorage.setItem(UI_MODE_STORAGE_KEY, uiMode)
  }, [uiMode])

  return (
    <UiModeContext.Provider value={{ mode: uiMode, setMode: setUiMode }}>
      <div className={`app-shell ${uiMode === 'v1' ? 'classic-shell' : ''} ${sidebarCollapsed && uiMode === 'v2' ? 'sidebar-collapsed' : ''}`}>
        {uiMode === 'v2' && (
          <header className="topbar">
            <Brand />
            <div className="topbar-actions">
              <button type="button" className="ui-mode-toggle" onClick={() => setUiMode('v1')}>
                V1 · Classic UI
              </button>
              <ThemeToggle dark={dark} setPreference={setPreference} />
            </div>
          </header>
        )}

        <div className="app-body">
          <aside className="sidebar">
            {uiMode === 'v1' ? <Brand /> : (
              <div className="sidebar-toolbar">
                <button
                  type="button"
                  className="sidebar-collapse-btn"
                  onClick={() => setSidebarCollapsed(value => !value)}
                  aria-label={sidebarCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
                  title={sidebarCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
                >
                  {sidebarCollapsed ? <ChevronRightIcon width={14} height={14} /> : <ChevronLeftIcon width={14} height={14} />}
                </button>
              </div>
            )}

            <nav className="sidebar-nav" aria-label="Main navigation">
              {NAV.map(group => (
                <div key={group.section} className="sidebar-section-wrap">
                  <span className="sidebar-section">{group.section}</span>
                  {group.items.map(({ to, label, icon: Icon, end }) => (
                    <NavLink
                      key={to}
                      to={to}
                      end={end}
                      aria-label={label}
                      title={sidebarCollapsed ? label : undefined}
                      className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}
                    >
                      <span className="nav-icon-wrap"><Icon width={18} height={18} /></span>
                      <span className="nav-label">{label}</span>
                    </NavLink>
                  ))}
                </div>
              ))}
            </nav>

            <div className="sidebar-footer">
              {uiMode === 'v1' && (
                <button type="button" className="ui-mode-toggle classic-mode-toggle" onClick={() => setUiMode('v2')}>
                  V2 · New UI
                </button>
              )}
              <NavLink
                to="/settings"
                aria-label="Settings"
                title={sidebarCollapsed ? 'Settings' : undefined}
                className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}
              >
                <span className="nav-icon-wrap"><SettingsIcon width={18} height={18} /></span>
                <span className="nav-label">Settings</span>
              </NavLink>
              {uiMode === 'v1' && <ThemeToggle dark={dark} setPreference={setPreference} />}
            </div>
          </aside>

          <div className="content">
            <div className="shell">
              <Outlet />
            </div>
          </div>
        </div>
      </div>
    </UiModeContext.Provider>
  )
}

function ThemeToggle({ dark, setPreference }: { dark: boolean; setPreference: (value: 'light' | 'dark') => void }) {
  return (
    <button
      type="button"
      className="theme-toggle"
      aria-pressed={dark}
      aria-label={`Switch to ${dark ? 'light' : 'dark'} mode`}
      onClick={() => setPreference(dark ? 'light' : 'dark')}
    >
      <span className="row" style={{ gap: '0.65rem' }}>
        {dark ? <MoonIcon width={16} height={16} /> : <SunIcon width={16} height={16} />}
        <span className="theme-label">{dark ? 'Dark mode' : 'Light mode'}</span>
      </span>
      <span aria-hidden="true" className={`theme-indicator ${dark ? 'on' : ''}`} />
    </button>
  )
}

function Brand() {
  return (
    <Link to="/" className="brand" aria-label="Colosseum home">
      <span className="brand-mark">
        <img src={logoUrl} alt="" style={{ width: '100%', height: '100%', objectFit: 'contain', borderRadius: 'inherit' }} />
      </span>
      <span className="brand-copy">
        COLOSSEUM
        <small>MODEL BENCHMARKING</small>
      </span>
    </Link>
  )
}
