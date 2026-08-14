import { useMemo, useState } from 'react'
import type { ModelItem } from '../types'
import { modelId } from './common'

export function JudgeModelPicker({ models, value, onChange }: { models: ModelItem[]; value: string; onChange: (value: string) => void }) {
  const [provider, setProvider] = useState('')
  const [showUnverified, setShowUnverified] = useState(false)
  const visible = useMemo(
    () => models.filter(model => (showUnverified || model.verified) && (!provider || model.provider === provider)),
    [models, provider, showUnverified],
  )
  const providers = useMemo(
    () => [...new Set(models.filter(model => showUnverified || model.verified).map(model => model.provider))].sort(),
    [models, showUnverified],
  )

  return <div className="judge-model-picker">
    <div className="form-grid">
      <label>
        Provider
        <select value={provider} onChange={event => setProvider(event.target.value)}>
          <option value="">All providers</option>
          {providers.map(item => <option key={item} value={item}>{item.replaceAll('_', ' ')}</option>)}
        </select>
      </label>
      <label>
        Judge model
        <select value={value} onChange={event => onChange(event.target.value)}>
          {!visible.some(model => modelId(model) === value) && <option value={value}>{value} (unavailable)</option>}
          {visible.map(model => {
            const id = modelId(model)
            const unavailable = !model.verified || model.enabled === false || Boolean(model.gate_reason)
            return <option key={id} value={id} disabled={unavailable}>
              {model.name ?? id}{unavailable ? ' — unverified' : ''}
            </option>
          })}
        </select>
      </label>
    </div>
    <label className="judge-unverified-toggle">
      <input type="checkbox" checked={showUnverified} onChange={event => setShowUnverified(event.target.checked)} />
      Show unverified models
    </label>
  </div>
}
