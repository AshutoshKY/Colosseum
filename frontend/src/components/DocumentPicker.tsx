import { useMemo, useState } from 'react'
import type { DocumentItem } from '../types'
import { Badge, Empty, Spinner } from './common'

type GoldFilter = 'all' | 'gold' | 'missing'

const hasGold = (doc: DocumentItem) => Boolean(doc.has_gold)

export function DocumentPicker({
  documents,
  selected,
  onChange,
  loading,
}: {
  documents: DocumentItem[]
  selected: number[]
  onChange: (ids: number[]) => void
  loading?: boolean
}) {
  const [search, setSearch] = useState('')
  const [goldFilter, setGoldFilter] = useState<GoldFilter>('all')

  const shown = useMemo(() => {
    const query = search.trim().toLowerCase()
    return documents.filter(doc => {
      if (goldFilter === 'gold' && !hasGold(doc)) return false
      if (goldFilter === 'missing' && hasGold(doc)) return false
      return (doc.filename ?? doc.name ?? '').toLowerCase().includes(query)
    })
  }, [documents, search, goldFilter])

  const selectedSet = new Set(selected)
  const shownIds = shown.map(doc => doc.id)
  const allShownSelected = shown.length > 0 && shownIds.every(id => selectedSet.has(id))

  const selectShown = () => onChange([...new Set([...selected, ...shownIds])])
  const deselectShown = () => onChange(selected.filter(id => !shownIds.includes(id)))

  const toggle = (id: number, checked: boolean) =>
    onChange(checked ? [...selected, id] : selected.filter(value => value !== id))

  if (loading) return <Spinner />

  return (
    <>
      <div className="picker-toolbar">
        <label className="search">
          <input
            value={search}
            onChange={event => setSearch(event.target.value)}
            placeholder="Search by claim or filename"
            aria-label="Search documents"
          />
        </label>
        <div className="segmented">
          <button className={goldFilter === 'all' ? 'active' : ''} onClick={() => setGoldFilter('all')}>All</button>
          <button className={goldFilter === 'gold' ? 'active' : ''} onClick={() => setGoldFilter('gold')}>Gold</button>
          <button className={goldFilter === 'missing' ? 'active' : ''} onClick={() => setGoldFilter('missing')}>No gold</button>
        </div>
        <div className="picker-actions">
          {allShownSelected
            ? <button type="button" className="small" onClick={deselectShown}>Deselect all</button>
            : <button type="button" className="small" onClick={selectShown} disabled={!shown.length}>Select all{shown.length !== documents.length ? ` (${shown.length})` : ''}</button>}
          {selected.length > 0 && <button type="button" className="small ghost" onClick={() => onChange([])}>Clear</button>}
        </div>
        <span className="count-pill">{selected.length} / {documents.length} selected</span>
      </div>

      {shown.length ? (
        <div className="document-list">
          {shown.map(doc => {
            const checked = selectedSet.has(doc.id)
            return (
              <label key={doc.id} className={checked ? 'checked' : ''}>
                <input type="checkbox" checked={checked} onChange={event => toggle(doc.id, event.target.checked)} />
                <span className="grow">
                  <strong>{doc.filename ?? doc.name}</strong>
                  <small>{doc.page_count ?? '—'} pages · {doc.origin ?? 'test-docs'}</small>
                </span>
                <Badge tone={hasGold(doc) ? 'good' : 'warn'}>{hasGold(doc) ? 'gold' : 'no gold'}</Badge>
              </label>
            )
          })}
        </div>
      ) : (
        <Empty>{documents.length ? 'No documents match the current filter.' : 'No documents yet. Upload PDFs to start.'}</Empty>
      )}
    </>
  )
}
