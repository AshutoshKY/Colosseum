import { createContext, type Dispatch, type PropsWithChildren, type SetStateAction, useContext, useEffect, useState } from 'react'
import { initialRunSpec } from '../builder'
import type { RunSpec } from '../types'

const DEFAULTS_KEY = 'colosseum.runDefaults'

type RunDefaults = Pick<RunSpec, 'compression' | 'concurrency' | 'judge'>

function loadRunDefaults(): Partial<RunDefaults> {
  try {
    return JSON.parse(localStorage.getItem(DEFAULTS_KEY) ?? '{}') as Partial<RunDefaults>
  } catch {
    return {}
  }
}

interface BuilderState {
  spec: RunSpec
  setSpec: Dispatch<SetStateAction<RunSpec>>
}

const Context = createContext<BuilderState | null>(null)

export function RunBuilderProvider({ children }: PropsWithChildren) {
  const [spec, setSpec] = useState<RunSpec>(() => ({ ...initialRunSpec(), ...loadRunDefaults() }))

  // Compression, concurrency, and judge settings double as the user's saved
  // defaults (edited on the Settings page) for future sessions.
  useEffect(() => {
    const defaults: RunDefaults = { compression: spec.compression, concurrency: spec.concurrency, judge: spec.judge }
    localStorage.setItem(DEFAULTS_KEY, JSON.stringify(defaults))
  }, [spec.compression, spec.concurrency, spec.judge])

  return <Context.Provider value={{ spec, setSpec }}>{children}</Context.Provider>
}

export function useRunBuilder() {
  const value = useContext(Context)
  if (!value) throw new Error('RunBuilderProvider is missing')
  return value
}
