import { useMemo, useRef, useState, type MouseEvent } from 'react'
import type { ModelItem } from '../types'
import { useOpenRouterSearch } from '../api/hooks'
import { useRunBuilder } from '../context/RunBuilderContext'
import {
  Spinner,
  getModelSpecs,
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
  const { discoveredModels, rememberDiscovered } = useRunBuilder()
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

  const groups = allModels.reduce<Record<string, ModelItem[]>>((all, model) => {
    const provider = model.provider || 'other'
    ;(all[provider] ??= []).push(model)
    return all
  }, {})
  // Ensure the openrouter group always renders
  groups.openrouter ??= []

  return (
    <div className="model-picker-container">
      <div className="model-picker-bar">
        <span className={selected.length ? 'count-badge active' : 'count-badge'}>
          {selected.length || 'No'} model{selected.length === 1 ? '' : 's'} selected
        </span>
        <span className="row">
          <button type="button" className="small ghost" onClick={() => searchInputRef.current?.focus()}>Search all models</button>
          {selected.length > 0 && <button type="button" className="small ghost danger" onClick={() => onChange([])}>Clear</button>}
        </span>
      </div>

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
                const isSelected = selected.includes(id)
                const { hasPdf, hasVision, isTextOnly, context, releaseDate, price } = getModelSpecs(model)
                const isVerifying = verifyingId === id

                return (
                  <div
                    className={`model-card ${disabled ? 'disabled' : ''} ${isSelected ? 'selected' : ''}`}
                    key={id}
                    title={model.gate_reason ?? undefined}
                  >
                    <div className="model-card-top">
                      <label className="model-card-label" title={model.name ?? id}>
                        <input
                          type="checkbox"
                          checked={isSelected}
                          disabled={disabled}
                          onChange={event =>
                            onChange(
                              event.target.checked
                                ? [...selected, id]
                                : selected.filter(value => value !== id),
                            )
                          }
                        />
                        <span className="model-card-name">
                          <strong>{model.name ?? id}</strong>
                        </span>
                      </label>

                      <div className="model-card-actions">
                        {model.gate_reason ? (
                          <span className="model-status-chip gated" title={model.gate_reason}>
                            {model.gate_reason}
                          </span>
                        ) : model.verified ? (
                          <span className="model-status-chip verified" title="API connection verified">
                            ✓ verified
                          </span>
                        ) : (
                          <span className="model-status-chip unverified" title="Unverified model">
                            unverified
                          </span>
                        )}

                        <button
                          type="button"
                          className={`model-verify-btn ${model.verified ? 'is-verified' : 'needs-verify'}`}
                          disabled={isVerifying || disabled}
                          onClick={event => {
                            event.stopPropagation()
                            onVerify(id)
                          }}
                          title={model.verified ? 'Re-verify API connection' : 'Test API connection'}
                        >
                          {isVerifying ? (
                            <>
                              <Spinner /> <span className="btn-text">Checking…</span>
                            </>
                          ) : (
                            <span className="btn-text">Verify</span>
                          )}
                        </button>
                      </div>
                    </div>

                    <div className="model-card-bottom">
                      <div className="model-spec-pills">
                        {hasPdf && (
                          <span className="spec-pill pill-pdf" title="Native PDF document support">
                            📄 PDF
                          </span>
                        )}
                        {hasVision && (
                          <span className="spec-pill pill-vision" title="Vision & image understanding">
                            👁 Vision
                          </span>
                        )}
                        {isTextOnly && (
                          <span className="spec-pill pill-text" title="Text-only model (cannot read PDFs or images)">
                            📝 Text-only
                          </span>
                        )}
                        {context && (
                          <span className="spec-pill pill-ctx" title={model.context_window ? `Context: ${model.context_window.toLocaleString()} tokens` : 'Context window'}>
                            ⚡ {context}
                          </span>
                        )}
                        {releaseDate && (
                          <span className="spec-pill pill-date" title={`Released: ${model.release_date}`}>
                            📅 {releaseDate}
                          </span>
                        )}
                      </div>

                      <div className="model-card-price" title="Pricing per million tokens (in · out)">
                        {price}
                      </div>
                    </div>
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
            const { hasPdf, hasVision, isTextOnly, context, releaseDate, price } = getModelSpecs(model)

            return (
              <div className={`or-result-card ${checked ? 'selected' : ''}`} key={id}>
                <div className="or-card-top">
                  <label className="or-card-label" title={model.name ?? id}>
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
                  </label>
                  <code className="muted or-model-code" title={id}>{id}</code>
                </div>

                <div className="or-card-bottom">
                  <div className="model-spec-pills">
                    {hasPdf && <span className="spec-pill pill-pdf" title="PDF support">📄 PDF</span>}
                    {hasVision && <span className="spec-pill pill-vision" title="Vision support">👁 Vision</span>}
                    {isTextOnly && <span className="spec-pill pill-text" title="Text only">📝 Text-only</span>}
                    {context && <span className="spec-pill pill-ctx" title="Context window">⚡ {context}</span>}
                    {releaseDate && <span className="spec-pill pill-date" title={`Released: ${model.release_date}`}>📅 {releaseDate}</span>}
                  </div>
                  <div className="model-card-price" title="Pricing per million tokens (in · out)">{price}</div>
                </div>
              </div>
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
