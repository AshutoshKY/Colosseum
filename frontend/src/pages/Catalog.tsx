import { useMemo, useState } from 'react'
import { useActions, useCatalog } from '../api/hooks'
import { Badge, capabilityList, Card, Empty, ErrorBox, modelId, money, Spinner } from '../components/common'
import type { ModelItem } from '../types'

export default function Catalog() {
  const catalog = useCatalog()
  const actions = useActions()
  const [search, setSearch] = useState('')

  const groups = useMemo(() => {
    const query = search.trim().toLowerCase()
    const shown = (catalog.data ?? []).filter(model =>
      (model.name ?? '').toLowerCase().includes(query) ||
      modelId(model).toLowerCase().includes(query) ||
      model.provider.toLowerCase().includes(query),
    )
    return shown.reduce<Record<string, ModelItem[]>>((all, model) => {
      ;(all[model.provider] ??= []).push(model)
      return all
    }, {})
  }, [catalog.data, search])

  const providers = Object.entries(groups)

  return (
    <>
      <header className="page-title">
        <div>
          <span className="eyebrow">Providers</span>
          <h1>Model catalog</h1>
          <p>Capabilities, pricing, availability gates, and live verification.</p>
        </div>
        <label className="search">
          <input value={search} onChange={event => setSearch(event.target.value)} placeholder="Search models or providers" aria-label="Search catalog" />
        </label>
      </header>

      {catalog.isLoading ? (
        <Spinner />
      ) : providers.length ? (
        providers.map(([provider, models]) => (
          <section key={provider}>
            <h2 className="section-title">
              {provider.replaceAll('_', ' ')}
              <span className="count-pill">{models.length}</span>
            </h2>
            <div className="catalog-grid">
              {models.map(model => (
                <ModelCard
                  key={modelId(model)}
                  model={model}
                  verifying={actions.verify.isPending && actions.verify.variables === modelId(model)}
                  onVerify={() => actions.verify.mutate(modelId(model))}
                />
              ))}
            </div>
          </section>
        ))
      ) : (
        <Empty>No models match your search.</Empty>
      )}
      <ErrorBox error={catalog.error ?? actions.verify.error} />
    </>
  )
}

function ModelCard({ model, verifying, onVerify }: { model: ModelItem; verifying: boolean; onVerify: () => void }) {
  const id = modelId(model)
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
      </div>
      <dl className="details">
        <dt>Input / 1M</dt>
        <dd>{money(model.pricing?.input_per_million ?? model.pricing?.input)}</dd>
        <dt>Output / 1M</dt>
        <dd>{money(model.pricing?.output_per_million ?? model.pricing?.output)}</dd>
      </dl>
      {model.gate_reason && <div className="alert warn">{model.gate_reason}</div>}
      <button disabled={verifying} onClick={onVerify}>{verifying ? 'Verifying…' : 'Verify live'}</button>
    </Card>
  )
}
