import { useMemo, useState } from 'react'
import type { DocumentItem } from '../types'
import { Badge, Empty, formatBriefDate, Spinner } from './common'

type GoldFilter = 'all' | 'gold' | 'missing' | 'starred'
type SortBy = 'date-desc' | 'date-asc' | 'name-asc' | 'pages-desc' | 'pages-asc' | 'id-desc'

const hasGold = (doc: DocumentItem) => Boolean(doc.has_gold)

function useStarredDocs() {
  const [starred, setStarred] = useState<Set<number>>(() => {
    try {
      const stored = localStorage.getItem('colosseum_starred_docs')
      return stored ? new Set(JSON.parse(stored)) : new Set()
    } catch {
      return new Set()
    }
  })

  const toggleStar = (id: number, event?: React.MouseEvent) => {
    event?.stopPropagation()
    event?.preventDefault()
    setStarred(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      try {
        localStorage.setItem('colosseum_starred_docs', JSON.stringify([...next]))
      } catch { /* Ignore unavailable storage. */ }
      return next
    })
  }

  return { starred, toggleStar }
}

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
  const [sortBy, setSortBy] = useState<SortBy>('date-desc')
  const { starred, toggleStar } = useStarredDocs()

  const shown = useMemo(() => {
    const query = search.trim().toLowerCase()
    const filtered = documents.filter(doc => {
      if (goldFilter === 'gold' && !hasGold(doc)) return false
      if (goldFilter === 'missing' && hasGold(doc)) return false
      if (goldFilter === 'starred' && !starred.has(doc.id)) return false
      return (doc.filename ?? doc.name ?? '').toLowerCase().includes(query)
    })

    return filtered.sort((a, b) => {
      if (sortBy === 'date-desc') {
        const da = a.created_at ? new Date(a.created_at).getTime() : 0
        const db = b.created_at ? new Date(b.created_at).getTime() : 0
        return db - da || b.id - a.id
      }
      if (sortBy === 'date-asc') {
        const da = a.created_at ? new Date(a.created_at).getTime() : 0
        const db = b.created_at ? new Date(b.created_at).getTime() : 0
        return da - db || a.id - b.id
      }
      if (sortBy === 'name-asc') {
        return (a.filename ?? a.name ?? '').localeCompare(b.filename ?? b.name ?? '')
      }
      if (sortBy === 'pages-desc') {
        return (b.page_count ?? 0) - (a.page_count ?? 0)
      }
      if (sortBy === 'pages-asc') {
        return (a.page_count ?? 0) - (b.page_count ?? 0)
      }
      if (sortBy === 'id-desc') {
        return b.id - a.id
      }
      return 0
    })
  }, [documents, search, goldFilter, sortBy, starred])

  const selectedSet = new Set(selected)
  const shownIds = shown.map(doc => doc.id)
  const allShownSelected = shown.length > 0 && shownIds.every(id => selectedSet.has(id))

  const selectShown = () => onChange([...new Set([...selected, ...shownIds])])
  const deselectShown = () => onChange(selected.filter(id => !shownIds.includes(id)))
  const selectGold = () => {
    const goldIds = documents.filter(hasGold).map(doc => doc.id)
    onChange([...new Set([...selected, ...goldIds])])
  }
  const selectStarred = () => {
    const starredIds = documents.filter(doc => starred.has(doc.id)).map(doc => doc.id)
    onChange([...new Set([...selected, ...starredIds])])
  }

  const toggle = (id: number, checked: boolean) =>
    onChange(checked ? [...selected, id] : selected.filter(value => value !== id))

  if (loading) return <Spinner />

  return (
    <div className="document-picker">
      <div className="picker-toolbar">
        <label className="search">
          <input
            value={search}
            onChange={event => setSearch(event.target.value)}
            placeholder="Search by claim or filename"
            aria-label="Search documents"
          />
        </label>
        <div className="picker-filters">
          <select value={goldFilter} onChange={event => setGoldFilter(event.target.value as GoldFilter)} aria-label="Filter claims">
            <option value="all">All claims</option>
            <option value="gold">Has gold</option>
            <option value="missing">Missing gold</option>
            <option value="starred">Starred{starred.size ? ` (${starred.size})` : ''}</option>
          </select>
          <select value={sortBy} onChange={event => setSortBy(event.target.value as SortBy)} aria-label="Sort claims">
            <option value="date-desc">Newest</option>
            <option value="date-asc">Oldest</option>
            <option value="name-asc">Name A–Z</option>
            <option value="pages-desc">Most pages</option>
            <option value="pages-asc">Fewest pages</option>
            <option value="id-desc">Highest ID</option>
          </select>
        </div>
        <div className="picker-actions">
          {allShownSelected
            ? <button type="button" className="small" onClick={deselectShown}>Deselect all</button>
            : <button type="button" className="small" onClick={selectShown} disabled={!shown.length}>Select all{shown.length !== documents.length ? ` (${shown.length})` : ''}</button>}
          <button type="button" className="small ghost" onClick={selectGold} title="Select every claim with ground truth">Select gold</button>
          {starred.size > 0 && (
            <button type="button" className="small ghost" onClick={selectStarred} title="Select all starred documents">Select starred</button>
          )}
          {selected.length > 0 && <button type="button" className="small ghost danger" onClick={() => onChange([])}>Clear</button>}
        </div>
      </div>

      {shown.length ? (
        <div className="document-list">
          {shown.map(doc => {
            const checked = selectedSet.has(doc.id)
            const isStarred = starred.has(doc.id)
            return (
              <label key={doc.id} className={checked ? 'checked' : ''}>
                <input type="checkbox" checked={checked} onChange={event => toggle(doc.id, event.target.checked)} />
                <button
                  type="button"
                  className={`star-btn ${isStarred ? 'starred' : ''}`}
                  onClick={event => toggleStar(doc.id, event)}
                  title={isStarred ? 'Unstar document' : 'Star document'}
                  aria-label={isStarred ? 'Unstar document' : 'Star document'}
                >
                  {isStarred ? '⭐' : '☆'}
                </button>
                <span className="grow">
                  <strong title={doc.filename ?? doc.name}>{doc.filename ?? doc.name}</strong>
                  <small>
                    #{doc.id} · {doc.page_count ?? '—'} pages
                    {doc.created_at && (
                      <span title={`Uploaded: ${new Date(doc.created_at).toLocaleString()}`}>
                        {' · '}{formatBriefDate(doc.created_at)}
                      </span>
                    )}
                  </small>
                </span>
                <Badge tone={hasGold(doc) ? 'good' : 'warn'}>{hasGold(doc) ? 'gold' : 'no gold'}</Badge>
                <a
                  className="button ghost small"
                  href={`/api/documents/${doc.id}/file`}
                  target="_blank"
                  rel="noreferrer"
                  onClick={event => event.stopPropagation()}
                  title="Open PDF in new tab"
                  aria-label={`Open ${doc.filename ?? doc.name} in a new tab`}
                >
                  ↗
                </a>
              </label>
            )
          })}
        </div>
      ) : (
        <Empty>{documents.length ? 'No documents match the current filter.' : 'No documents yet. Upload PDFs to start.'}</Empty>
      )}
    </div>
  )
}
