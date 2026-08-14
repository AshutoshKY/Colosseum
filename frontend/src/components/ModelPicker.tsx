import { useMemo, useRef, useState, type MouseEvent } from 'react'
import type { ModelItem } from '../types'
import { useOpenRouterSearch } from '../api/hooks'
import { useRunBuilder } from '../context/RunBuilderContext'
import {
  Badge,
  Spinner,
  badgeHue,
  capabilityList,
  formatContextWindow,
  formatPriceSummary,
  formatReleaseDate,
  getContextWindow,
  modelId,
  supportsDocuments,
} from './common'

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
  const { discoveredModels, rememberDiscovered, forgetDiscovered } = useRunBuilder()
  const [customInput, setCustomInput] = useState('')
  const searchInputRef = useRef<HTMLInputElement>(null)

  // Merge catalog models with discovered/custom models from persistent context
  const allModels = useMemo(() => {
    const byId = new Map<string, ModelItem>()
    // First, add all catalog models
    for (const model of models) {
      byId.set(modelId(model), model)
    }
    // Then overlay / add persistent discovered models
    for (const [id, model] of Object.entries(discoveredModels)) {
      if (!byId.has(id)) {
        byId.set(id, model)
      }
    }
    return [...byId.values()]
  }, [models, discoveredModels])

  const modelMap = useMemo(() => {
    return new Map(allModels.map(m => [modelId(m), m]))
  }, [allModels])

  const selectedModelsList = useMemo(() => {
    return selected.map(id => modelMap.get(id) || {
      id,
      model_id: id,
      name: id.split('/').pop() || id,
      provider: id.startsWith('openrouter/') ? 'openrouter' : id.split('/')[0] || 'custom',
      enabled: true,
      verified: false,
    } as ModelItem)
  }, [selected, modelMap])

  const groups = allModels.reduce<Record<string, ModelItem[]>>((all, model) => {
    const provider = model.provider || 'other'
    ;(all[provider] ??= []).push(model)
    return all
  }, {})
  // Ensure the openrouter group always renders
  groups.openrouter ??= []

  const removeSelected = (id: string) => {
    onChange(selected.filter(item => item !== id))
  }

  const clearAllSelected = () => {
    onChange([])
  }

  return (
    <div className="model-picker-container">
      {/* 1. Dedicated Selected Models Deck / Active Dashboard */}
      <section className="selected-models-deck">
        <div className="deck-header">
          <div className="deck-title">
            <strong>Active Benchmark Models</strong>
            <span className={`count-badge ${selected.length ? 'active' : ''}`}>
              {selected.length} {selected.length === 1 ? 'model' : 'models'} selected
            </span>
          </div>
          {selected.length > 0 && (
            <div className="deck-actions">
              <button
                type="button"
                className="small ghost danger"
                onClick={clearAllSelected}
                title="Remove all selected models from this run"
              >
                Clear all
              </button>
              <button
                type="button"
                className="small ghost"
                onClick={() => searchInputRef.current?.focus()}
                title="Jump to OpenRouter search to add more models"
              >
                + Add more models
              </button>
            </div>
          )}
        </div>

        {selected.length === 0 ? (
          <div className="deck-empty">
            <span className="empty-icon">🎯</span>
            <div>
              <p><strong>No models selected yet.</strong></p>
              <small className="muted">
                Select models from the provider lists below or search the live OpenRouter catalog (~345 models).
              </small>
            </div>
          </div>
        ) : (
          <div className="selected-cards-grid">
            {selectedModelsList.map(model => {
              const id = modelId(model)
              const docCapable = supportsDocuments(model)
              const ctx = getContextWindow(model)
              const ctxFormatted = formatContextWindow(ctx)
              const relDate = formatReleaseDate(model.release_date)
              const priceSummary = formatPriceSummary(model.pricing)

              return (
                <div className="selected-model-card" key={id}>
                  <div className="card-top">
                    <div className="card-identity">
                      <span className={`provider-pill ${badgeHue(model.provider, 'model')}`}>
                        {model.provider.replaceAll('_', ' ')}
                      </span>
                      <strong className="model-title" title={id}>{model.name ?? id}</strong>
                    </div>
                    <button
                      type="button"
                      className="delete-model-btn"
                      onClick={() => removeSelected(id)}
                      title={`Remove ${model.name ?? id} from active run`}
                      aria-label={`Remove ${model.name ?? id}`}
                    >
                      ✕
                    </button>
                  </div>

                  <code className="model-id-code" title={id}>{id}</code>

                  <div className="card-meta-row">
                    {relDate && (
                      <span className="meta-tag date-tag" title={`Release date: ${model.release_date}`}>
                        📅 {relDate}
                      </span>
                    )}
                    {ctxFormatted && (
                      <span className="meta-tag ctx-tag" title={ctx ? `Context window: ${ctx.toLocaleString()} tokens` : ''}>
                        ⚡ {ctxFormatted}
                      </span>
                    )}
                    <span className="meta-tag price-tag" title="Per million tokens">
                      🏷️ {priceSummary}
                    </span>
                  </div>

                  <div className="card-badges">
                    {!docCapable && (
                      <Badge tone="warn">text-only · no PDF input</Badge>
                    )}
                    {capabilityList(model.capabilities).map(cap => (
                      <Badge key={cap}>{cap}</Badge>
                    ))}
                    {model.verified && <Badge tone="good">verified</Badge>}
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </section>

      {/* 2. Provider Groups with OpenRouter live search & catalog */}
      <div className="model-groups">
        {Object.entries(groups).map(([provider, entries]) => {
          const selectable = entries.filter(model => model.enabled !== false && !model.gate_reason).map(modelId)
          const picked = entries.map(modelId).filter(id => selected.includes(id))
          const allPicked = selectable.length > 0 && selectable.every(id => selected.includes(id))

          const toggleGroup = (event: MouseEvent) => {
            event.preventDefault()
            event.stopPropagation()
            onChange(
              allPicked
                ? selected.filter(id => !selectable.includes(id))
                : [...new Set([...selected, ...selectable])],
            )
          }

          return (
            <details
              className="model-group"
              key={provider}
              open={picked.length > 0 || provider === 'openrouter'}
            >
              <summary>
                <span className="provider-name">{provider.replaceAll('_', ' ')}</span>
                <span className="row">
                  <span className="muted">
                    {picked.length ? `${picked.length} selected · ` : ''}
                    {entries.length} models
                  </span>
                  <button
                    type="button"
                    className="small"
                    onClick={toggleGroup}
                    disabled={!selectable.length}
                  >
                    {allPicked ? 'Deselect all' : 'Select all'}
                  </button>
                </span>
              </summary>

              {provider === 'openrouter' && (
                <div className="openrouter-section">
                  <OpenRouterSearch
                    selected={selected}
                    onChange={onChange}
                    onDiscover={rememberDiscovered}
                    inputRef={searchInputRef}
                  />
                </div>
              )}

              {entries.map(model => {
                const id = modelId(model)
                const disabled = model.enabled === false || Boolean(model.gate_reason)
                const docCapable = supportsDocuments(model)
                const ctx = getContextWindow(model)
                const ctxFormatted = formatContextWindow(ctx)
                const relDate = formatReleaseDate(model.release_date)
                const priceSummary = formatPriceSummary(model.pricing)

                return (
                  <div
                    className={`model-row ${disabled ? 'disabled' : ''} ${selected.includes(id) ? 'selected-row' : ''}`}
                    key={id}
                    title={model.gate_reason ?? ''}
                  >
                    <label className="model-select-label">
                      <input
                        type="checkbox"
                        checked={selected.includes(id)}
                        disabled={disabled}
                        onChange={event =>
                          onChange(
                            event.target.checked
                              ? [...selected, id]
                              : selected.filter(value => value !== id),
                          )
                        }
                      />
                      <span className="model-name-text">
                        <strong>{model.name ?? id}</strong>
                      </span>
                    </label>

                    <div className="model-meta-info grow">
                      {relDate && (
                        <span className="model-meta-pill date-pill" title={`Released: ${model.release_date}`}>
                          📅 {relDate}
                        </span>
                      )}
                      {ctxFormatted && (
                        <span className="model-meta-pill ctx-pill" title={ctx ? `Context: ${ctx.toLocaleString()} tokens` : ''}>
                          ⚡ {ctxFormatted}
                        </span>
                      )}
                      {!docCapable && (
                        <Badge tone="warn">text-only</Badge>
                      )}
                      {capabilityList(model.capabilities).slice(0, 2).map(cap => (
                        <Badge key={cap}>{cap}</Badge>
                      ))}
                    </div>

                    <div className="model-pricing-info" title="Per million tokens (in · out)">
                      <small>{priceSummary}</small>
                    </div>

                    <Badge tone={model.verified ? 'good' : disabled ? 'bad' : 'neutral'}>
                      {model.gate_reason ?? (model.verified ? 'verified' : 'unverified')}
                    </Badge>

                    <button
                      type="button"
                      className="small"
                      disabled={verifyingId === id}
                      onClick={() => onVerify(id)}
                    >
                      {verifyingId === id ? 'Verifying…' : 'Verify'}
                    </button>
                  </div>
                )
              })}
            </details>
          )
        })}
      </div>
    </div>
  )
}

/** Live search over OpenRouter's full ~345-model catalog. Any hit is directly selectable. */
function OpenRouterSearch({
  selected,
  onChange,
  onDiscover,
  inputRef,
}: {
  selected: string[]
  onChange: (ids: string[]) => void
  onDiscover: (models: ModelItem[]) => void
  inputRef?: React.RefObject<HTMLInputElement>
}) {
  const [query, setQuery] = useState('')
  const search = useOpenRouterSearch(query)
  const results = search.data?.models ?? []

  const handleAddCustomQuery = (customId: string) => {
    const trimmed = customId.trim()
    if (!trimmed) return
    const id = trimmed.includes('/') ? trimmed : `openrouter/${trimmed}`
    const customModel: ModelItem = {
      id,
      model_id: id,
      name: `${trimmed.split('/').pop()} (Custom)`,
      provider: id.startsWith('openrouter/') ? 'openrouter' : 'custom',
      family: 'custom',
      enabled: true,
      verified: false,
    }
    onDiscover([customModel])
    if (!selected.includes(id)) {
      onChange([...selected, id])
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      e.preventDefault()
      if (results.length > 0) {
        const top = results[0]
        const id = modelId(top)
        onDiscover([top])
        if (!selected.includes(id)) {
          onChange([...selected, id])
        }
      } else if (query.trim().length >= 2) {
        handleAddCustomQuery(query)
      }
    }
  }

  return (
    <div className="openrouter-search">
      <div className="search-input-wrapper">
        <input
          ref={inputRef}
          type="search"
          className="or-search-input"
          placeholder="Search all OpenRouter models (e.g. gpt, sonnet, qwen, deepseek, gemini)…"
          value={query}
          onChange={event => setQuery(event.target.value)}
          onKeyDown={handleKeyDown}
        />
        {query && (
          <button
            type="button"
            className="search-clear-btn"
            onClick={() => setQuery('')}
            title="Clear search"
          >
            ✕
          </button>
        )}
      </div>

      {query.trim().length >= 2 && (
        <div className="or-search-results">
          {search.isFetching && (
            <div className="muted search-loading">
              <Spinner /> searching OpenRouter catalog…
            </div>
          )}
          {search.isError && (
            <div className="alert bad">
              OpenRouter search failed — check the backend / network.
            </div>
          )}
          {!search.isFetching && !search.isError && results.length === 0 && (
            <div className="search-no-results">
              <span className="muted">No catalog models match “{query}”.</span>
              <button
                type="button"
                className="small secondary add-custom-search-btn"
                onClick={() => handleAddCustomQuery(query)}
              >
                + Add “{query.trim()}” as custom model
              </button>
            </div>
          )}
          {search.data && (
            <div className="muted or-count">
              {search.data.total} match{search.data.total === 1 ? '' : 'es'}
              {search.data.total > results.length ? ` · showing ${results.length}` : ''}
              <span className="or-tip"> — click any to select & keep</span>
            </div>
          )}
          {results.map(model => {
            const id = modelId(model)
            const checked = selected.includes(id)
            const ctx = getContextWindow(model)
            const ctxFormatted = formatContextWindow(ctx)
            const relDate = formatReleaseDate(model.release_date)
            const priceSummary = formatPriceSummary(model.pricing)

            return (
              <label className={`or-result-row ${checked ? 'checked-row' : ''}`} key={id}>
                <input
                  type="checkbox"
                  checked={checked}
                  onChange={event => {
                    onDiscover([model]) // keep it renderable & persistent in dashboard
                    onChange(
                      event.target.checked
                        ? [...selected, id]
                        : selected.filter(value => value !== id),
                    )
                  }}
                />
                <strong className="or-model-name">{model.name ?? id}</strong>
                <code className="muted or-model-code" title={id}>{id}</code>

                <div className="or-meta-group">
                  {relDate && (
                    <span className="or-meta-pill date" title={`Released: ${model.release_date}`}>
                      📅 {relDate}
                    </span>
                  )}
                  {ctxFormatted && (
                    <span className="or-meta-pill ctx" title={ctx ? `Context: ${ctx.toLocaleString()} tokens` : ''}>
                      ⚡ {ctxFormatted}
                    </span>
                  )}
                  <span className="or-pricing">{priceSummary}</span>
                </div>
              </label>
            )
          })}
        </div>
      )}
    </div>
  )
}

export function textOnlyModels(models: ModelItem[], selected: string[]) {
  return models.filter(model => selected.includes(modelId(model)) && !supportsDocuments(model))
}

