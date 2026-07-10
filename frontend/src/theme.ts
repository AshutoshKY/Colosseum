import { useSyncExternalStore } from 'react'

export type ThemePreference = 'light' | 'dark' | 'system'

const STORAGE_KEY = 'colosseum.theme'
const listeners = new Set<() => void>()
const media = window.matchMedia('(prefers-color-scheme: dark)')

export function getPreference(): ThemePreference {
  const stored = localStorage.getItem(STORAGE_KEY) ?? localStorage.getItem('theme')
  return stored === 'light' || stored === 'dark' ? stored : 'system'
}

export function resolveTheme(preference: ThemePreference = getPreference()): 'light' | 'dark' {
  if (preference === 'system') return media.matches ? 'dark' : 'light'
  return preference
}

export function setPreference(preference: ThemePreference) {
  if (preference === 'system') localStorage.removeItem(STORAGE_KEY)
  else localStorage.setItem(STORAGE_KEY, preference)
  localStorage.removeItem('theme') // drop the legacy key
  apply()
  listeners.forEach(listener => listener())
}

function apply() {
  document.documentElement.dataset.theme = resolveTheme()
}

function subscribe(listener: () => void) {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

media.addEventListener('change', () => {
  if (getPreference() === 'system') {
    apply()
    listeners.forEach(listener => listener())
  }
})

apply()

/** Current theme preference plus the resolved light/dark value, kept in sync across the app. */
export function useTheme() {
  const preference = useSyncExternalStore(subscribe, getPreference)
  const resolved = useSyncExternalStore(subscribe, () => resolveTheme())
  return { preference, resolved, setPreference }
}
