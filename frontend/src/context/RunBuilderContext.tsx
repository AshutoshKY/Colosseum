import { createContext, type Dispatch, type PropsWithChildren, type SetStateAction, useContext, useEffect, useState } from 'react'
import { DEFAULT_PER_PROVIDER_CONCURRENCY, initialRunSpec } from '../builder'
import type { ModelItem, RunSpec } from '../types'
import { modelId } from '../components/common'

const DEFAULTS_KEY = 'colosseum.runDefaults'
const SELECTED_MODELS_KEY = 'colosseum.selectedModels'
const DISCOVERED_MODELS_KEY = 'colosseum.discoveredModels'

type RunDefaults = Pick<RunSpec, 'compression' | 'concurrency' | 'judge'>

function loadRunDefaults(): Partial<RunDefaults> {
  try {
    return JSON.parse(localStorage.getItem(DEFAULTS_KEY) ?? '{}') as Partial<RunDefaults>
  } catch {
    return {}
  }
}

function loadSelectedModels(): string[] {
  try {
    const raw = localStorage.getItem(SELECTED_MODELS_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw)
    return Array.isArray(parsed) ? parsed : []
  } catch {
    return []
  }
}

function loadDiscoveredModels(): Record<string, ModelItem> {
  try {
    const raw = localStorage.getItem(DISCOVERED_MODELS_KEY)
    if (!raw) return {}
    const parsed = JSON.parse(raw)
    return parsed && typeof parsed === 'object' ? parsed : {}
  } catch {
    return {}
  }
}

interface BuilderState {
  spec: RunSpec
  setSpec: Dispatch<SetStateAction<RunSpec>>
  discoveredModels: Record<string, ModelItem>
  setDiscoveredModels: Dispatch<SetStateAction<Record<string, ModelItem>>>
  rememberDiscovered: (models: ModelItem[]) => void
  forgetDiscovered: (id: string) => void
  selectModel: (id: string, model?: ModelItem) => void
  deselectModel: (id: string) => void
  clearSelectedModels: () => void
}

const Context = createContext<BuilderState | null>(null)

export function RunBuilderProvider({ children }: PropsWithChildren) {
  const [spec, setSpec] = useState<RunSpec>(() => {
    const base = initialRunSpec()
    const savedDefaults = loadRunDefaults()
    const savedModels = loadSelectedModels()
    return {
      ...base,
      ...savedDefaults,
      concurrency: {
        global: savedDefaults.concurrency?.global ?? base.concurrency.global,
        per_provider: {
          ...DEFAULT_PER_PROVIDER_CONCURRENCY,
          ...(savedDefaults.concurrency?.per_provider ?? {}),
        },
      },
      compression: {
        ...base.compression,
        ...(savedDefaults.compression ?? {}),
      },
      judge: {
        ...base.judge,
        ...(savedDefaults.judge ?? {}),
      },
      model_ids: savedModels.length ? savedModels : base.model_ids,
    }
  })

  const [discoveredModels, setDiscoveredModels] = useState<Record<string, ModelItem>>(() => loadDiscoveredModels())

  // Compression, concurrency, and judge settings double as the user's saved
  // defaults (edited on the Settings page) for future sessions.
  useEffect(() => {
    const defaults: RunDefaults = { compression: spec.compression, concurrency: spec.concurrency, judge: spec.judge }
    localStorage.setItem(DEFAULTS_KEY, JSON.stringify(defaults))
  }, [spec.compression, spec.concurrency, spec.judge])

  // Persist selected model IDs
  useEffect(() => {
    localStorage.setItem(SELECTED_MODELS_KEY, JSON.stringify(spec.model_ids))
  }, [spec.model_ids])

  // Persist discovered custom / OpenRouter models
  useEffect(() => {
    localStorage.setItem(DISCOVERED_MODELS_KEY, JSON.stringify(discoveredModels))
  }, [discoveredModels])

  const rememberDiscovered = (found: ModelItem[]) => {
    setDiscoveredModels(current => {
      const next = { ...current }
      for (const model of found) {
        next[modelId(model)] = model
      }
      return next
    })
  }

  const forgetDiscovered = (id: string) => {
    setDiscoveredModels(current => {
      const next = { ...current }
      delete next[id]
      return next
    })
    setSpec(current => ({
      ...current,
      model_ids: current.model_ids.filter(item => item !== id),
    }))
  }

  const selectModel = (id: string, model?: ModelItem) => {
    if (model) rememberDiscovered([model])
    setSpec(current => ({
      ...current,
      model_ids: current.model_ids.includes(id) ? current.model_ids : [...current.model_ids, id],
    }))
  }

  const deselectModel = (id: string) => {
    setSpec(current => ({
      ...current,
      model_ids: current.model_ids.filter(item => item !== id),
    }))
  }

  const clearSelectedModels = () => {
    setSpec(current => ({ ...current, model_ids: [] }))
  }

  return (
    <Context.Provider
      value={{
        spec,
        setSpec,
        discoveredModels,
        setDiscoveredModels,
        rememberDiscovered,
        forgetDiscovered,
        selectModel,
        deselectModel,
        clearSelectedModels,
      }}
    >
      {children}
    </Context.Provider>
  )
}

export function useRunBuilder() {
  const value = useContext(Context)
  if (!value) throw new Error('RunBuilderProvider is missing')
  return value
}
