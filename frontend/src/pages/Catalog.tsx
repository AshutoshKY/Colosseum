import { useMemo, useState } from 'react'
import { useActions, useCatalog, useDiscoverBedrockModels, useDiscoverVertexModels } from '../api/hooks'
import {
  Badge,
  Card,
  Empty,
  ErrorBox,
  Spinner,
  capabilityList,
  formatContextWindow,
  formatReleaseDate,
  getContextWindow,
  getModelSpecs,
  modelId,
  money,
} from '../components/common'
import type { AddModelPayload, DiscoveredModelItem, ModelItem } from '../types'

export default function Catalog() {
  const catalog = useCatalog()
  const actions = useActions()
  const [search, setSearch] = useState('')
  const [selectedProvider, setSelectedProvider] = useState<string>('all')
  const [selectedRegion, setSelectedRegion] = useState<string>('all')
  const [selectedModality, setSelectedModality] = useState<string>('all')
  const [showDiscoverModal, setShowDiscoverModal] = useState(false)
  const [showBedrockModal, setShowBedrockModal] = useState(false)
  const [showAddModal, setShowAddModal] = useState(false)
  const [toast, setToast] = useState<{ msg: string; type: 'good' | 'bad' } | null>(null)

  const showToast = (msg: string, type: 'good' | 'bad' = 'good') => {
    setToast({ msg, type })
    setTimeout(() => setToast(null), 4500)
  }

  const allCatalogModels = catalog.data ?? []

  const groups = useMemo(() => {
    const query = search.trim().toLowerCase()
    const shown = allCatalogModels.filter(model => {
      const id = modelId(model).toLowerCase()
      const name = (model.name ?? '').toLowerCase()
      const provider = (model.provider ?? '').toLowerCase()
      const family = (model.family ?? '').toLowerCase()
      const region = (model.region ?? '').toLowerCase()
      const regions = (model.regions ?? []).map(r => r.toLowerCase())

      // Provider filter
      if (selectedProvider !== 'all' && (model.provider || 'other') !== selectedProvider) {
        return false
      }

      // Region filter
      if (selectedRegion !== 'all') {
        const matchReg = region === selectedRegion.toLowerCase() || regions.includes(selectedRegion.toLowerCase())
        if (!matchReg) return false
      }

      // Modality filter
      const specs = getModelSpecs(model)
      if (selectedModality === 'vision' && !specs.hasVision) {
        return false
      }
      if (selectedModality === 'pdf' && !specs.hasPdf) {
        return false
      }
      if (selectedModality === 'thinking') {
        const caps = model.capabilities
        const hasThinking = typeof caps === 'object' && caps !== null && !Array.isArray(caps) && Boolean((caps as Record<string, unknown>).thinking)
        if (!hasThinking) return false
      }

      if (query) {
        const tokens = query.split(/\s+/).filter(Boolean)
        const searchable = `${id} ${name} ${provider} ${family} ${region} ${regions.join(' ')}`.toLowerCase()
        const match = tokens.every(tok => searchable.includes(tok))
        if (!match) return false
      }

      return true
    })
    return shown.reduce<Record<string, ModelItem[]>>((all, model) => {
      ;(all[model.provider] ??= []).push(model)
      return all
    }, {})
  }, [allCatalogModels, search, selectedProvider, selectedRegion, selectedModality])

  const providers = Object.entries(groups)

  const handleDeleteModel = async (mid: string, name: string) => {
    if (!confirm(`Are you sure you want to remove '${name}' (${mid}) from the catalog?`)) return
    try {
      await actions.deleteModel.mutateAsync(mid)
      showToast(`Removed '${name}' from catalog.`, 'good')
    } catch (err: unknown) {
      const e = err as Error
      showToast(`Failed to remove model: ${e?.message || err}`, 'bad')
    }
  }

  return (
    <>
      <header className="page-title">
        <div>
          <span className="eyebrow">Providers & Models</span>
          <h1>Model catalog</h1>
          <p>Capabilities, pricing, availability gates, and live multi-region verification across AWS Bedrock, Google Vertex AI, OpenRouter & partners.</p>
        </div>
        <div className="catalog-header-actions">
          <label className="search">
            <input
              value={search}
              onChange={event => setSearch(event.target.value)}
              placeholder="Search models, providers, or regions (e.g. us-west-2, virginia, sonnet)…"
              aria-label="Search catalog"
            />
          </label>
          <button
            type="button"
            className="secondary discover-btn"
            onClick={() => setShowDiscoverModal(true)}
            title="Scan & discover Vertex AI and Partner models across locations"
          >
            🔍 Discover Vertex Models
          </button>
          <button
            type="button"
            className="secondary discover-btn"
            onClick={() => setShowBedrockModal(true)}
            title="Scan & discover AWS Bedrock models across any region (us-east-1, us-west-2, ap-south-1, etc.)"
          >
            🔍 Discover Bedrock Models
          </button>
          <button
            type="button"
            className="primary add-model-btn"
            onClick={() => setShowAddModal(true)}
            title="Add any custom or new model"
          >
            + Add Model
          </button>
        </div>
      </header>

      {/* Catalog Filters Bar */}
      <div className="universal-search-container" style={{ margin: '0.75rem 0 1.25rem 0' }}>
        <div className="model-filter-tabs">
          <button
            type="button"
            className={`filter-tab-pill ${selectedProvider === 'all' ? 'active' : ''}`}
            onClick={() => setSelectedProvider('all')}
          >
            All Providers ({allCatalogModels.length})
          </button>
          <button
            type="button"
            className={`filter-tab-pill ${selectedProvider === 'bedrock' ? 'active' : ''}`}
            onClick={() => setSelectedProvider('bedrock')}
          >
            AWS Bedrock
          </button>
          <button
            type="button"
            className={`filter-tab-pill ${selectedProvider === 'vertex_ai' || selectedProvider === 'vertex_partner' ? 'active' : ''}`}
            onClick={() => setSelectedProvider(p => p.startsWith('vertex') ? 'all' : 'vertex_ai')}
          >
            Vertex AI
          </button>
          <button
            type="button"
            className={`filter-tab-pill ${selectedProvider === 'openrouter' ? 'active' : ''}`}
            onClick={() => setSelectedProvider('openrouter')}
          >
            OpenRouter
          </button>
        </div>

        {/* Region & Modality Filter Chips */}
        <div className="modality-filter-chips">
          <span className="filter-chips-label">Region:</span>
          <button
            type="button"
            className={`modality-chip ${selectedRegion === 'all' ? 'active' : ''}`}
            onClick={() => setSelectedRegion('all')}
          >
            All Regions
          </button>
          <button
            type="button"
            className={`modality-chip ${selectedRegion === 'us-east-1' ? 'active' : ''}`}
            onClick={() => setSelectedRegion(r => r === 'us-east-1' ? 'all' : 'us-east-1')}
          >
            🌐 us-east-1 (N. Virginia)
          </button>
          <button
            type="button"
            className={`modality-chip ${selectedRegion === 'us-west-2' ? 'active' : ''}`}
            onClick={() => setSelectedRegion(r => r === 'us-west-2' ? 'all' : 'us-west-2')}
          >
            🌐 us-west-2 (Oregon)
          </button>
          <button
            type="button"
            className={`modality-chip ${selectedRegion === 'ap-south-1' ? 'active' : ''}`}
            onClick={() => setSelectedRegion(r => r === 'ap-south-1' ? 'all' : 'ap-south-1')}
          >
            🌐 ap-south-1 (Mumbai)
          </button>
          <button
            type="button"
            className={`modality-chip ${selectedRegion === 'eu-west-1' ? 'active' : ''}`}
            onClick={() => setSelectedRegion(r => r === 'eu-west-1' ? 'all' : 'eu-west-1')}
          >
            🌐 eu-west-1 (Ireland)
          </button>
          <button
            type="button"
            className={`modality-chip ${selectedRegion === 'us-central1' ? 'active' : ''}`}
            onClick={() => setSelectedRegion(r => r === 'us-central1' ? 'all' : 'us-central1')}
          >
            🌐 us-central1 (Vertex)
          </button>
          <button
            type="button"
            className={`modality-chip ${selectedRegion === 'global' ? 'active' : ''}`}
            onClick={() => setSelectedRegion(r => r === 'global' ? 'all' : 'global')}
          >
            🌐 Global (OpenRouter)
          </button>
        </div>

        <div className="modality-filter-chips" style={{ borderTop: 'none', paddingTop: 0 }}>
          <span className="filter-chips-label">Features:</span>
          <button
            type="button"
            className={`modality-chip ${selectedModality === 'all' ? 'active' : ''}`}
            onClick={() => setSelectedModality('all')}
          >
            All Modalities
          </button>
          <button
            type="button"
            className={`modality-chip ${selectedModality === 'vision' ? 'active' : ''}`}
            onClick={() => setSelectedModality(m => m === 'vision' ? 'all' : 'vision')}
          >
            👁 Vision
          </button>
          <button
            type="button"
            className={`modality-chip ${selectedModality === 'pdf' ? 'active' : ''}`}
            onClick={() => setSelectedModality(m => m === 'pdf' ? 'all' : 'pdf')}
          >
            📄 PDF Native
          </button>
          <button
            type="button"
            className={`modality-chip ${selectedModality === 'thinking' ? 'active' : ''}`}
            onClick={() => setSelectedModality(m => m === 'thinking' ? 'all' : 'thinking')}
          >
            🧠 Thinking
          </button>
        </div>
      </div>

      {search.trim() && (
        <div
          className="discovery-search-hint"
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            background: 'rgba(255, 153, 0, 0.08)',
            border: '1px solid rgba(255, 153, 0, 0.28)',
            borderRadius: '8px',
            padding: '0.65rem 1rem',
            margin: '0.5rem 0 1.25rem 0',
          }}
        >
          <span style={{ fontSize: '0.9rem', color: '#ffb347' }}>
            🌐 Searching live AWS Bedrock models? Discover & import foundation models & inference profiles directly from AWS.
          </span>
          <button
            type="button"
            className="secondary small"
            onClick={() => setShowBedrockModal(true)}
            style={{ marginLeft: '1rem', whiteSpace: 'nowrap' }}
          >
            🔍 Discover Bedrock Models
          </button>
        </div>
      )}

      {toast && (
        <div className={`alert ${toast.type}`} style={{ margin: '0.75rem 0' }}>
          <strong>{toast.type === 'good' ? '✓ ' : '⚠ '}</strong>
          {toast.msg}
        </div>
      )}

      {catalog.isLoading ? (
        <Spinner />
      ) : providers.length ? (
        providers.map(([provider, models]) => (
          <section key={provider}>
            <h2 className="section-title">
              {provider === 'vertex_ai'
                ? 'Google Vertex AI'
                : provider === 'bedrock'
                ? 'AWS Bedrock (us-east-1)'
                : provider === 'openrouter'
                ? 'OpenRouter'
                : provider.replaceAll('_', ' ')}
              <span className="count-pill">{models.length}</span>
            </h2>
            <div className="catalog-grid">
              {models.map(model => (
                <ModelCard
                  key={modelId(model)}
                  model={model}
                  verifying={actions.verify.isPending && actions.verify.variables === modelId(model)}
                  onVerify={() => actions.verify.mutate(modelId(model))}
                  onDelete={() => handleDeleteModel(modelId(model), model.name ?? modelId(model))}
                />
              ))}
            </div>
          </section>
        ))
      ) : (
        <Empty>No models match your search filters.</Empty>
      )}

      <ErrorBox error={catalog.error ?? actions.verify.error ?? actions.addModel.error} />

      {/* Discover Vertex & Partner Models Modal */}
      {showDiscoverModal && (
        <DiscoverModal
          onClose={() => setShowDiscoverModal(false)}
          onAdded={(name) => {
            showToast(`✓ Added ${name} to Catalog!`)
            catalog.refetch()
          }}
        />
      )}

      {/* Discover AWS Bedrock Models Modal */}
      {showBedrockModal && (
        <BedrockDiscoverModal
          initialSearch={search}
          onClose={() => setShowBedrockModal(false)}
          onAdded={(name) => {
            showToast(`✓ Added ${name} to Catalog!`)
            catalog.refetch()
          }}
        />
      )}

      {/* Add Custom / New Model Modal */}
      {showAddModal && (
        <AddModelModal
          onClose={() => setShowAddModal(false)}
          onSuccess={(name) => {
            showToast(`✓ Successfully registered ${name} in Catalog!`)
            catalog.refetch()
            setShowAddModal(false)
          }}
        />
      )}
    </>
  )
}

function ModelCard({
  model,
  verifying,
  onVerify,
  onDelete,
}: {
  model: ModelItem
  verifying: boolean
  onVerify: () => void
  onDelete: () => void
}) {
  const id = modelId(model)
  const ctx = getContextWindow(model)
  const ctxFormatted = formatContextWindow(ctx)
  const relDate = formatReleaseDate(model.release_date)
  const isCustom = model.family === 'custom' || id.startsWith('dyn:') || model.family === 'openrouter'
  const specs = getModelSpecs(model)

  return (
    <Card>
      <div className="row between">
        <h3>{model.name ?? id}</h3>
        <Badge tone={model.enabled === false ? 'bad' : model.verified ? 'good' : 'neutral'}>
          {model.enabled === false ? 'disabled' : model.verified ? 'verified' : 'unverified'}
        </Badge>
      </div>
      <code>{id}</code>
      <div className="badges">
        {capabilityList(model.capabilities).map(cap => <Badge key={cap}>{cap}</Badge>)}
        <span className="spec-pill pill-region" title={`Cloud Region: ${specs.region}`}>
          🌐 {specs.region}
        </span>
      </div>
      <dl className="details">
        <dt>Input / 1M</dt>
        <dd>{money(model.pricing?.input_per_million ?? model.pricing?.input)}</dd>
        <dt>Output / 1M</dt>
        <dd>{money(model.pricing?.output_per_million ?? model.pricing?.output)}</dd>
        {ctxFormatted && (
          <>
            <dt>Context</dt>
            <dd title={ctx ? `${ctx.toLocaleString()} tokens` : ''}>⚡ {ctxFormatted}</dd>
          </>
        )}
        {relDate && (
          <>
            <dt>Released</dt>
            <dd title={model.release_date ?? ''}>📅 {relDate}</dd>
          </>
        )}
      </dl>
      {model.gate_reason && <div className="alert warn">{model.gate_reason}</div>}
      <div className="row gap between" style={{ marginTop: '0.5rem' }}>
        <button disabled={verifying} onClick={onVerify}>
          {verifying ? 'Verifying…' : 'Verify live'}
        </button>
        {isCustom && (
          <button type="button" className="ghost danger small" onClick={onDelete} title="Remove custom model">
            Remove
          </button>
        )}
      </div>
    </Card>
  )
}

/** Modal to scan, inspect, and add Vertex AI and Partner models across locations */
function DiscoverModal({ onClose, onAdded }: { onClose: () => void; onAdded: (name: string) => void }) {
  const [selectedLoc, setSelectedLoc] = useState<string>('us-central1')
  const discover = useDiscoverVertexModels(selectedLoc)
  const actions = useActions()
  const [filterPub, setFilterPub] = useState<string>('all')
  const [searchTerm, setSearchTerm] = useState('')
  const [addingId, setAddingId] = useState<string | null>(null)
  const [addedIds, setAddedIds] = useState<Set<string>>(new Set())

  const items = discover.data?.discovered ?? []

  const locations = [
    { id: 'us-central1', name: 'us-central1 (Iowa)' },
    { id: 'us-east4', name: 'us-east4 (N. Virginia)' },
    { id: 'us-west1', name: 'us-west1 (Oregon)' },
    { id: 'europe-west4', name: 'europe-west4 (Netherlands)' },
    { id: 'asia-east1', name: 'asia-east1 (Taiwan)' },
  ]

  const publishers = useMemo(() => {
    const pubs = new Set<string>()
    for (const item of items) {
      if (item.publisher) pubs.add(item.publisher)
    }
    return ['all', ...Array.from(pubs).sort()]
  }, [items])

  const filteredItems = useMemo(() => {
    const term = searchTerm.trim().toLowerCase()
    const tokens = term ? term.split(/\s+/).filter(Boolean) : []
    return items.filter(item => {
      const matchPub = filterPub === 'all' || item.publisher === filterPub
      if (!matchPub) return false
      if (!tokens.length) return true
      const searchable = `${item.model_id} ${item.name} ${item.family} ${item.publisher} ${item.description || ''}`.toLowerCase()
      return tokens.every(tok => searchable.includes(tok))
    })
  }, [items, filterPub, searchTerm])

  const handleAddModel = async (item: DiscoveredModelItem) => {
    setAddingId(item.model_id)
    try {
      await actions.addModel.mutateAsync({
        model_id: item.model_id,
        display_name: item.name,
        provider: item.provider,
        family: item.family,
        region: selectedLoc,
        regions: [selectedLoc],
        modalities: Array.isArray(item.capabilities.modalities) ? item.capabilities.modalities : ['text'],
        pdf_native: Boolean(item.capabilities.pdf_native),
        vision: Boolean(item.capabilities.vision),
        context_window: item.capabilities.context_window,
        structured_method: (item.capabilities.structured_method as string) ?? 'json_schema',
        thinking: Boolean(item.capabilities.thinking),
        caching: Boolean(item.capabilities.caching),
        input_per_million: item.pricing.input_per_million ?? item.pricing.input ?? 0,
        output_per_million: item.pricing.output_per_million ?? item.pricing.output ?? 0,
        enabled: true,
        verify_now: false,
      })
      setAddedIds(prev => new Set(prev).add(item.model_id))
      onAdded(item.name)
    } catch (err) {
      console.error('Failed to add model:', err)
    } finally {
      setAddingId(null)
    }
  }

  const handleAddAll = async () => {
    const unreg = filteredItems.filter(item => !item.is_registered && !addedIds.has(item.model_id))
    for (const item of unreg) {
      await handleAddModel(item)
    }
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content discover-modal" onClick={e => e.stopPropagation()}>
        <div className="modal-header">
          <div>
            <h2>🔍 Discover Vertex AI & Partner Models ({selectedLoc})</h2>
            <p className="muted">
              Live probe of Foundation Models and Model Garden partners available in your selected location.
            </p>
          </div>
          <button type="button" className="close-btn" onClick={onClose} aria-label="Close modal">✕</button>
        </div>

        {/* Location Selector Bar */}
        <div className="discovery-region-selector">
          <span className="discovery-region-label">🌐 Vertex Location:</span>
          <select
            className="region-select-dropdown"
            value={selectedLoc}
            onChange={e => setSelectedLoc(e.target.value)}
          >
            {locations.map(loc => (
              <option key={loc.id} value={loc.id}>
                {loc.name}
              </option>
            ))}
          </select>
          {discover.data && (
            <span className="muted small" style={{ marginLeft: 'auto' }}>
              <strong>Project:</strong> <code>{discover.data.project || 'vertex-internal-testing'}</code>
            </span>
          )}
        </div>

        {discover.data && (
          <div className="discovery-status-bar">
            <span className={`status-dot ${discover.data.has_credentials ? 'green' : 'red'}`} />
            <span>
              <strong>Location:</strong> <code>{discover.data.location}</code> ·{' '}
              <strong>Discovered:</strong> {discover.data.total} models
            </span>
            <button
              type="button"
              className="small ghost"
              disabled={discover.isFetching}
              onClick={() => discover.refetch()}
              title="Rescan Vertex AI"
            >
              {discover.isFetching ? 'Scanning…' : '🔄 Refresh'}
            </button>
          </div>
        )}

        <div className="discovery-controls">
          <input
            type="search"
            className="discovery-search"
            placeholder="Filter discovered models (e.g. gemini, claude, llama, qwen, deepseek)…"
            value={searchTerm}
            onChange={e => setSearchTerm(e.target.value)}
          />

          <div className="discovery-filter-tabs">
            {publishers.map(pub => (
              <button
                key={pub}
                type="button"
                className={`tab-btn ${filterPub === pub ? 'active' : ''}`}
                onClick={() => setFilterPub(pub)}
              >
                {pub === 'all' ? 'All Publishers' : pub.toUpperCase()}
              </button>
            ))}
          </div>
        </div>

        <div className="discovery-items-container">
          {discover.isLoading ? (
            <div className="discovery-loading">
              <Spinner />
              <p>Scanning Vertex AI ({selectedLoc}) Model Garden & checking availability…</p>
            </div>
          ) : filteredItems.length === 0 ? (
            <div className="discovery-empty">
              <p className="muted">No models match your search filters.</p>
            </div>
          ) : (
            <div className="discovery-items-grid">
              {filteredItems.map(item => {
                const inCatalog = item.is_registered || addedIds.has(item.model_id)
                const isAdding = addingId === item.model_id
                const ctxFmt = formatContextWindow(item.capabilities.context_window)

                return (
                  <div className={`discovery-item-card ${inCatalog ? 'in-catalog' : ''}`} key={item.model_id}>
                    <div className="item-header">
                      <div className="item-title">
                        <span className="publisher-badge">{item.publisher}</span>
                        <strong>{item.name}</strong>
                      </div>
                      <Badge tone={inCatalog ? 'good' : 'neutral'}>
                        {inCatalog ? 'In Catalog' : 'Available'}
                      </Badge>
                    </div>

                    <code className="item-code">{item.model_id}</code>

                    <div className="item-meta">
                      {item.capabilities.pdf_native && <Badge tone="good">PDF Native</Badge>}
                      {item.capabilities.vision && <Badge>Vision</Badge>}
                      {item.capabilities.thinking && <Badge tone="info">Thinking</Badge>}
                      {ctxFmt && <span className="meta-tag">⚡ {ctxFmt}</span>}
                      <span className="meta-tag">
                        💰 ${item.pricing.input_per_million ?? item.pricing.input ?? 0} / ${item.pricing.output_per_million ?? item.pricing.output ?? 0}
                      </span>
                    </div>

                    <div className="item-actions">
                      <button
                        type="button"
                        className={inCatalog ? 'small ghost disabled-btn' : 'small primary'}
                        disabled={inCatalog || isAdding}
                        onClick={() => handleAddModel(item)}
                      >
                        {isAdding ? 'Adding…' : inCatalog ? '✓ Added to Catalog' : '+ Add to Catalog'}
                      </button>
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </div>

        <div className="modal-footer">
          <span className="muted">
            Showing {filteredItems.length} of {items.length} discovered models in {selectedLoc}
          </span>
          <div className="row gap">
            <button
              type="button"
              className="secondary"
              onClick={handleAddAll}
              disabled={discover.isLoading || filteredItems.every(i => i.is_registered || addedIds.has(i.model_id))}
            >
              + Add All Unregistered Models
            </button>
            <button type="button" className="primary" onClick={onClose}>
              Done
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

/** Modal to discover and import AWS Bedrock foundation models across any AWS region */
function BedrockDiscoverModal({
  initialSearch = '',
  onClose,
  onAdded,
}: {
  initialSearch?: string
  onClose: () => void
  onAdded: (name: string) => void
}) {
  const [selectedRegion, setSelectedRegion] = useState<string>('us-east-1')
  const discover = useDiscoverBedrockModels(selectedRegion)
  const actions = useActions()
  const [filterPub, setFilterPub] = useState<string>('all')
  const [searchTerm, setSearchTerm] = useState(initialSearch)
  const [addingId, setAddingId] = useState<string | null>(null)
  const [addedIds, setAddedIds] = useState<Set<string>>(new Set())
  const [settingActive, setSettingActive] = useState(false)
  const [activeMsg, setActiveMsg] = useState<string | null>(null)

  const items = discover.data?.discovered ?? []

  const bedrockRegions = [
    { id: 'us-east-1', name: 'us-east-1 (N. Virginia)' },
    { id: 'us-west-2', name: 'us-west-2 (Oregon)' },
    { id: 'ap-south-1', name: 'ap-south-1 (Mumbai)' },
    { id: 'eu-west-1', name: 'eu-west-1 (Ireland)' },
    { id: 'us-east-2', name: 'us-east-2 (Ohio)' },
    { id: 'eu-central-1', name: 'eu-central-1 (Frankfurt)' },
    { id: 'ap-southeast-1', name: 'ap-southeast-1 (Singapore)' },
    { id: 'ap-northeast-1', name: 'ap-northeast-1 (Tokyo)' },
  ]

  const publishers = useMemo(() => {
    const pubs = new Set<string>()
    for (const item of items) {
      if (item.publisher) pubs.add(item.publisher)
    }
    return ['all', ...Array.from(pubs).sort()]
  }, [items])

  const filteredItems = useMemo(() => {
    const term = searchTerm.trim().toLowerCase()
    const tokens = term ? term.split(/\s+/).filter(Boolean) : []
    return items.filter(item => {
      const matchPub = filterPub === 'all' || item.publisher === filterPub
      if (!matchPub) return false
      if (!tokens.length) return true
      const searchable = `${item.model_id} ${item.name} ${item.family} ${item.publisher} ${item.description || ''}`.toLowerCase()
      return tokens.every(tok => searchable.includes(tok))
    })
  }, [items, filterPub, searchTerm])

  const handleMakeActiveRegion = async () => {
    setSettingActive(true)
    try {
      await actions.setBedrockRegion.mutateAsync(selectedRegion)
      setActiveMsg(`✓ Set ${selectedRegion} as active Bedrock region!`)
      setTimeout(() => setActiveMsg(null), 3500)
    } catch (err) {
      setActiveMsg(`Failed to set region: ${err}`)
    } finally {
      setSettingActive(false)
    }
  }

  const handleAddModel = async (item: DiscoveredModelItem) => {
    setAddingId(item.model_id)
    try {
      await actions.addModel.mutateAsync({
        model_id: item.model_id,
        display_name: item.name,
        provider: 'bedrock',
        family: item.family,
        region: selectedRegion,
        regions: [selectedRegion],
        modalities: Array.isArray(item.capabilities.modalities) ? item.capabilities.modalities : ['text'],
        pdf_native: Boolean(item.capabilities.pdf_native),
        vision: Boolean(item.capabilities.vision),
        context_window: item.capabilities.context_window,
        structured_method: (item.capabilities.structured_method as string) ?? 'json_mode',
        thinking: Boolean(item.capabilities.thinking),
        caching: Boolean(item.capabilities.caching),
        input_per_million: item.pricing.input_per_million ?? item.pricing.input ?? 0,
        output_per_million: item.pricing.output_per_million ?? item.pricing.output ?? 0,
        enabled: true,
        verify_now: false,
      })
      setAddedIds(prev => new Set(prev).add(item.model_id))
      onAdded(item.name)
    } catch (err) {
      console.error('Failed to add Bedrock model:', err)
    } finally {
      setAddingId(null)
    }
  }

  const handleAddAll = async () => {
    const unreg = filteredItems.filter(item => !item.is_registered && !addedIds.has(item.model_id))
    for (const item of unreg) {
      await handleAddModel(item)
    }
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content discover-modal" onClick={e => e.stopPropagation()}>
        <div className="modal-header">
          <div>
            <h2>🔍 Discover AWS Bedrock Models ({selectedRegion})</h2>
            <p className="muted">
              Select any AWS region to scan live foundation models and cross-region inference profiles.
            </p>
          </div>
          <button type="button" className="close-btn" onClick={onClose} aria-label="Close modal">✕</button>
        </div>

        {/* Region Selector Bar */}
        <div className="discovery-region-selector">
          <span className="discovery-region-label">🌐 Bedrock Region:</span>
          <select
            className="region-select-dropdown"
            value={selectedRegion}
            onChange={e => setSelectedRegion(e.target.value)}
          >
            {bedrockRegions.map(reg => (
              <option key={reg.id} value={reg.id}>
                {reg.name}
              </option>
            ))}
          </select>
          <button
            type="button"
            className="small secondary"
            onClick={handleMakeActiveRegion}
            disabled={settingActive}
            title="Set as active region in Colosseum backend settings"
          >
            {settingActive ? 'Setting…' : '⭐ Set as Active Region'}
          </button>
          {activeMsg && (
            <span className="small text-good" style={{ marginLeft: '0.5rem', fontWeight: 600 }}>
              {activeMsg}
            </span>
          )}
        </div>

        {discover.data && (
          <div className="discovery-status-bar">
            <span className={`status-dot ${discover.data.has_credentials ? 'green' : 'red'}`} />
            <span>
              <strong>Region:</strong> <code>{discover.data.region}</code> ·{' '}
              <strong>Discovered:</strong> {discover.data.total} models ·{' '}
              <strong>Auth:</strong> {discover.data.has_credentials ? 'IAM SigV4 (Auto-renewing)' : 'Credentials missing'}
            </span>
            <button
              type="button"
              className="small ghost"
              disabled={discover.isFetching}
              onClick={() => discover.refetch()}
              title="Rescan Bedrock"
            >
              {discover.isFetching ? 'Scanning…' : '🔄 Refresh'}
            </button>
          </div>
        )}

        <div className="discovery-controls">
          <input
            type="search"
            className="discovery-search"
            placeholder="Filter discovered Bedrock models (e.g. qwen, claude, sonnet, nova, deepseek, mistral, llama)…"
            value={searchTerm}
            onChange={e => setSearchTerm(e.target.value)}
          />

          <div className="discovery-filter-tabs">
            {publishers.map(pub => (
              <button
                key={pub}
                type="button"
                className={`tab-btn ${filterPub === pub ? 'active' : ''}`}
                onClick={() => setFilterPub(pub)}
              >
                {pub === 'all' ? 'All Publishers' : pub.toUpperCase()}
              </button>
            ))}
          </div>
        </div>

        <div className="discovery-items-container">
          {discover.isLoading ? (
            <div className="discovery-loading">
              <Spinner />
              <p>Scanning AWS Bedrock ({selectedRegion}) foundation models…</p>
            </div>
          ) : filteredItems.length === 0 ? (
            <div className="discovery-empty">
              <p className="muted">No models match your search filters in {selectedRegion}.</p>
            </div>
          ) : (
            <div className="discovery-items-grid">
              {filteredItems.map(item => {
                const inCatalog = item.is_registered || addedIds.has(item.model_id)
                const isAdding = addingId === item.model_id
                const ctxFmt = formatContextWindow(item.capabilities.context_window)

                return (
                  <div className={`discovery-item-card ${inCatalog ? 'in-catalog' : ''}`} key={item.model_id}>
                    <div className="item-header">
                      <div className="item-title">
                        <span className="publisher-badge">{item.publisher}</span>
                        <strong>{item.name}</strong>
                      </div>
                      <Badge tone={inCatalog ? 'good' : 'neutral'}>
                        {inCatalog ? 'In Catalog' : 'Available'}
                      </Badge>
                    </div>

                    <code className="item-code">{item.model_id}</code>

                    <div className="item-meta">
                      {item.capabilities.pdf_native && <Badge tone="good">PDF Native</Badge>}
                      {item.capabilities.vision && <Badge>Vision</Badge>}
                      {item.capabilities.thinking && <Badge tone="info">Thinking</Badge>}
                      {ctxFmt && <span className="meta-tag">⚡ {ctxFmt}</span>}
                      <span className="meta-tag">
                        💰 ${item.pricing.input_per_million ?? item.pricing.input ?? 0} / ${item.pricing.output_per_million ?? item.pricing.output ?? 0}
                      </span>
                    </div>

                    <div className="item-actions">
                      <button
                        type="button"
                        className={inCatalog ? 'small ghost disabled-btn' : 'small primary'}
                        disabled={inCatalog || isAdding}
                        onClick={() => handleAddModel(item)}
                      >
                        {isAdding ? 'Adding…' : inCatalog ? '✓ Added to Catalog' : '+ Add to Catalog'}
                      </button>
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </div>

        <div className="modal-footer">
          <span className="muted">
            Showing {filteredItems.length} of {items.length} discovered models in {selectedRegion}
          </span>
          <div className="row gap">
            <button
              type="button"
              className="secondary"
              onClick={handleAddAll}
              disabled={discover.isLoading || filteredItems.every(i => i.is_registered || addedIds.has(i.model_id))}
            >
              + Add All Unregistered Models
            </button>
            <button type="button" className="primary" onClick={onClose}>
              Done
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

/** Modal to add any custom or new model directly */
function AddModelModal({ onClose, onSuccess }: { onClose: () => void; onSuccess: (name: string) => void }) {
  const actions = useActions()
  const [modelIdInput, setModelIdInput] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [provider, setProvider] = useState('vertex_ai')
  const [region, setRegion] = useState('us-east-1')
  const [family, setFamily] = useState('gemini')
  const [pdfNative, setPdfNative] = useState(false)
  const [vision, setVision] = useState(true)
  const [thinking, setThinking] = useState(false)
  const [caching, setCaching] = useState(false)
  const [contextWindow, setContextWindow] = useState('1000000')
  const [structuredMethod, setStructuredMethod] = useState('json_schema')
  const [inputPrice, setInputPrice] = useState('0.30')
  const [outputPrice, setOutputPrice] = useState('2.50')
  const [verifyNow, setVerifyNow] = useState(true)
  const [verifying, setVerifying] = useState(false)
  const [verifyResult, setVerifyResult] = useState<{ ok: boolean; msg: string } | null>(null)
  const [errorMsg, setErrorMsg] = useState<string | null>(null)

  // Auto-fill defaults when model ID changes
  const handleModelIdChange = (val: string) => {
    setModelIdInput(val)
    const lower = val.toLowerCase()
    if (!displayName || displayName === modelIdInput) {
      const parts = val.split('/')
      setDisplayName(parts[parts.length - 1].replace(/-/g, ' ').replace(/\b\w/g, c => c.toUpperCase()))
    }
    if (lower.startsWith('vertex_ai/')) {
      if (lower.includes('claude') || lower.includes('llama') || lower.includes('mistral') || lower.includes('qwen') || lower.includes('deepseek') || lower.includes('grok') || lower.includes('glm')) {
        setProvider('vertex_partner')
      } else {
        setProvider('vertex_ai')
      }
      setRegion('us-central1')
    } else if (lower.startsWith('openrouter/')) {
      setProvider('openrouter')
      setRegion('global')
    } else if (lower.startsWith('bedrock/')) {
      setProvider('bedrock')
      setRegion('us-east-1')
    }

    if (lower.includes('gemini')) {
      setFamily('gemini')
      setPdfNative(true)
      setVision(true)
      setStructuredMethod('json_schema')
    } else if (lower.includes('claude')) {
      setFamily('claude')
      setPdfNative(true)
      setVision(true)
      setStructuredMethod('tools')
    } else if (lower.includes('llama')) {
      setFamily('llama')
      setPdfNative(false)
      setVision(lower.includes('vision'))
      setStructuredMethod('json_mode')
    } else if (lower.includes('mistral') || lower.includes('pixtral')) {
      setFamily('mistral')
      setPdfNative(false)
      setVision(lower.includes('pixtral') || lower.includes('small') || lower.includes('ocr'))
      setStructuredMethod('json_mode')
    } else if (lower.includes('qwen')) {
      setFamily('qwen')
      setPdfNative(false)
      setVision(lower.includes('vl'))
      setStructuredMethod('json_mode')
    } else if (lower.includes('deepseek')) {
      setFamily('deepseek')
      setPdfNative(false)
      setVision(lower.includes('ocr'))
      setThinking(lower.includes('r1'))
      setStructuredMethod('json_mode')
    }
  }

  const handleTestVerify = async () => {
    if (!modelIdInput.trim()) {
      setErrorMsg('Please enter a Model ID first.')
      return
    }
    setVerifying(true)
    setVerifyResult(null)
    setErrorMsg(null)
    try {
      // First register dynamically
      await actions.addModel.mutateAsync({
        model_id: modelIdInput.trim(),
        display_name: displayName.trim() || modelIdInput.trim(),
        provider,
        family,
        region,
        regions: [region],
        pdf_native: pdfNative,
        vision,
        thinking,
        caching,
        context_window: parseInt(contextWindow, 10) || null,
        structured_method: structuredMethod,
        input_per_million: parseFloat(inputPrice) || 0,
        output_per_million: parseFloat(outputPrice) || 0,
        enabled: true,
        verify_now: false,
      })

      // Run live verify
      const res = await actions.verify.mutateAsync(modelIdInput.trim())
      if (res.ok) {
        setVerifyResult({ ok: true, msg: `Verified successfully! Latency: ${res.latency_ms}ms` })
      } else {
        setVerifyResult({ ok: false, msg: res.error || 'Verification failed' })
      }
    } catch (err: unknown) {
      const errObj = err as Error
      setVerifyResult({ ok: false, msg: errObj?.message || String(err) })
    } finally {
      setVerifying(false)
    }
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!modelIdInput.trim()) {
      setErrorMsg('Model ID is required.')
      return
    }
    setErrorMsg(null)
    try {
      const payload: AddModelPayload = {
        model_id: modelIdInput.trim(),
        display_name: displayName.trim() || modelIdInput.trim(),
        provider,
        family,
        region,
        regions: [region],
        modalities: [
          'text',
          ...(pdfNative ? ['pdf'] : []),
          ...(vision ? ['image'] : []),
        ],
        pdf_native: pdfNative,
        vision,
        context_window: parseInt(contextWindow, 10) || null,
        structured_method: structuredMethod,
        thinking,
        caching,
        input_per_million: parseFloat(inputPrice) || 0,
        output_per_million: parseFloat(outputPrice) || 0,
        enabled: true,
        verify_now: verifyNow,
      }
      await actions.addModel.mutateAsync(payload)
      onSuccess(displayName.trim() || modelIdInput.trim())
    } catch (err: unknown) {
      const errObj = err as Error
      setErrorMsg(errObj?.message || 'Failed to add model.')
    }
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content add-modal" onClick={e => e.stopPropagation()}>
        <div className="modal-header">
          <div>
            <h2>+ Add New Model</h2>
            <p className="muted">Register any Bedrock, Vertex AI, Model Garden, or OpenAI-compatible model with regional routing.</p>
          </div>
          <button type="button" className="close-btn" onClick={onClose} aria-label="Close modal">✕</button>
        </div>

        <form onSubmit={handleSubmit} className="add-model-form">
          <div className="form-grid">
            <label className="form-field full-width">
              <span>Model ID (Transport ID) *</span>
              <input
                type="text"
                required
                placeholder="e.g. vertex_ai/gemini-2.0-flash or vertex_ai/meta/llama-3.3-70b-instruct-maas"
                value={modelIdInput}
                onChange={e => handleModelIdChange(e.target.value)}
              />
              <small className="muted">Exact provider string (e.g. <code>vertex_ai/...</code>, <code>openrouter/...</code>)</small>
            </label>

            <label className="form-field">
              <span>Display Name *</span>
              <input
                type="text"
                required
                placeholder="e.g. Gemini 2.0 Flash"
                value={displayName}
                onChange={e => setDisplayName(e.target.value)}
              />
            </label>

            <label className="form-field">
              <span>Provider</span>
              <select value={provider} onChange={e => setProvider(e.target.value)}>
                <option value="vertex_ai">Google Vertex AI (vertex_ai)</option>
                <option value="vertex_partner">Vertex Model Garden Partner (vertex_partner)</option>
                <option value="openrouter">OpenRouter (openrouter)</option>
                <option value="bedrock">AWS Bedrock (bedrock)</option>
                <option value="openai_compatible">OpenAI-Compatible Endpoint</option>
                <option value="xai">xAI (Grok)</option>
              </select>
            </label>

            <label className="form-field">
              <span>Family</span>
              <select value={family} onChange={e => setFamily(e.target.value)}>
                <option value="gemini">Gemini</option>
                <option value="claude">Claude</option>
                <option value="llama">Llama</option>
                <option value="mistral">Mistral</option>
                <option value="qwen">Qwen</option>
                <option value="deepseek">DeepSeek</option>
                <option value="grok">Grok</option>
                <option value="glm">GLM</option>
                <option value="open_models">Open Models / Gemma</option>
                <option value="bedrock">Bedrock</option>
                <option value="custom">Custom</option>
              </select>
            </label>

            <label className="form-field">
              <span>Structured Output Mode</span>
              <select value={structuredMethod} onChange={e => setStructuredMethod(e.target.value)}>
                <option value="json_schema">JSON Schema (Recommended for Gemini/OpenAI)</option>
                <option value="json_mode">JSON Mode + Repair Ladder</option>
                <option value="tools">Tools / Function Calling (Claude)</option>
              </select>
            </label>

            <label className="form-field">
              <span>Context Window (Tokens)</span>
              <input
                type="number"
                placeholder="1000000"
                value={contextWindow}
                onChange={e => setContextWindow(e.target.value)}
              />
            </label>

            <label className="form-field">
              <span>Input Price ($ / 1M tokens)</span>
              <input
                type="number"
                step="0.001"
                placeholder="0.30"
                value={inputPrice}
                onChange={e => setInputPrice(e.target.value)}
              />
            </label>

            <label className="form-field">
              <span>Output Price ($ / 1M tokens)</span>
              <input
                type="number"
                step="0.001"
                placeholder="2.50"
                value={outputPrice}
                onChange={e => setOutputPrice(e.target.value)}
              />
            </label>
          </div>

          <div className="capabilities-fieldset">
            <span className="field-label">Capabilities</span>
            <div className="checkbox-row">
              <label className="checkbox-item">
                <input
                  type="checkbox"
                  checked={pdfNative}
                  onChange={e => setPdfNative(e.target.checked)}
                />
                <span>PDF Native (Direct file ingestion)</span>
              </label>
              <label className="checkbox-item">
                <input
                  type="checkbox"
                  checked={vision}
                  onChange={e => setVision(e.target.checked)}
                />
                <span>Vision (Rasterized Image input)</span>
              </label>
              <label className="checkbox-item">
                <input
                  type="checkbox"
                  checked={thinking}
                  onChange={e => setThinking(e.target.checked)}
                />
                <span>Thinking / Reasoning tokens</span>
              </label>
              <label className="checkbox-item">
                <input
                  type="checkbox"
                  checked={caching}
                  onChange={e => setCaching(e.target.checked)}
                />
                <span>Prompt / Context Caching</span>
              </label>
            </div>
          </div>

          {verifyResult && (
            <div className={`alert ${verifyResult.ok ? 'good' : 'bad'}`}>
              <strong>{verifyResult.ok ? '✓ Live Verification Succeeded' : '✗ Verification Note:'}</strong>
              <p>{verifyResult.msg}</p>
            </div>
          )}

          {errorMsg && <div className="alert bad">{errorMsg}</div>}

          <div className="modal-footer">
            <button
              type="button"
              className="secondary"
              disabled={verifying || !modelIdInput}
              onClick={handleTestVerify}
            >
              {verifying ? 'Testing live call…' : '🧪 Test Live Verification'}
            </button>
            <div className="row gap">
              <button type="button" className="ghost" onClick={onClose}>
                Cancel
              </button>
              <button
                type="submit"
                className="primary"
                disabled={actions.addModel.isPending}
              >
                {actions.addModel.isPending ? 'Saving…' : 'Save & Register Model'}
              </button>
            </div>
          </div>
        </form>
      </div>
    </div>
  )
}
