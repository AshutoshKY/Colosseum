import type { MouseEvent } from 'react'
import type { ModelItem } from '../types'
import { Badge, capabilityList, modelId, money, supportsDocuments } from './common'

export function ModelPicker({
  models,
  selected,
  onChange,
  onVerify,
  verifyingId,
}: {
  models: ModelItem[]
  selected: string[]
  onChange: (ids: string[]) => void
  onVerify: (id: string) => void
  verifyingId?: string
}) {
  const groups = models.reduce<Record<string, ModelItem[]>>((all, model) => {
    const provider = model.provider || 'other'
    ;(all[provider] ??= []).push(model)
    return all
  }, {})

  return (
    <div className="model-groups">
      {Object.entries(groups).map(([provider, entries]) => {
        const selectable = entries.filter(model => model.enabled !== false && !model.gate_reason).map(modelId)
        const picked = entries.map(modelId).filter(id => selected.includes(id))
        const allPicked = selectable.length > 0 && selectable.every(id => selected.includes(id))

        const toggleGroup = (event: MouseEvent) => {
          // Keep the <details> from toggling when the group button is clicked.
          event.preventDefault()
          event.stopPropagation()
          onChange(allPicked
            ? selected.filter(id => !selectable.includes(id))
            : [...new Set([...selected, ...selectable])])
        }

        return (
          <details className="model-group" key={provider} open={picked.length > 0}>
            <summary>
              <span className="provider-name">{provider.replaceAll('_', ' ')}</span>
              <span className="row">
                <span className="muted">{picked.length ? `${picked.length} selected · ` : ''}{entries.length} models</span>
                <button type="button" className="small" onClick={toggleGroup} disabled={!selectable.length}>
                  {allPicked ? 'Deselect all' : 'Select all'}
                </button>
              </span>
            </summary>
            {entries.map(model => {
              const id = modelId(model)
              const disabled = model.enabled === false || Boolean(model.gate_reason)
              const docCapable = supportsDocuments(model)
              return (
                <div className={`model-row ${disabled ? 'disabled' : ''}`} key={id} title={model.gate_reason ?? ''}>
                  <label>
                    <input
                      type="checkbox"
                      checked={selected.includes(id)}
                      disabled={disabled}
                      onChange={event => onChange(event.target.checked ? [...selected, id] : selected.filter(value => value !== id))}
                    />
                    <strong>{model.name ?? id}</strong>
                  </label>
                  <span className="grow badges compact">
                    {!docCapable && <Badge tone="warn">text-only · no PDF/image input</Badge>}
                    {capabilityList(model.capabilities).map(cap => <Badge key={cap}>{cap}</Badge>)}
                  </span>
                  <small>{money(model.pricing?.input_per_million ?? model.pricing?.input)}/M in</small>
                  <Badge tone={model.verified ? 'good' : disabled ? 'bad' : 'neutral'}>
                    {model.gate_reason ?? (model.verified ? 'verified' : 'unverified')}
                  </Badge>
                  <button type="button" className="small" disabled={verifyingId === id} onClick={() => onVerify(id)}>
                    {verifyingId === id ? 'Verifying…' : 'Verify'}
                  </button>
                </div>
              )
            })}
          </details>
        )
      })}
    </div>
  )
}

export function textOnlyModels(models: ModelItem[], selected: string[]) {
  return models.filter(model => selected.includes(modelId(model)) && !supportsDocuments(model))
}
