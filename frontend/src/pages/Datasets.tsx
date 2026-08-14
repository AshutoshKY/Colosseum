import { useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useActions, useDocuments, useGold } from '../api/hooks'
import { Badge, Card, Empty, ErrorBox, formatBriefDate, Spinner } from '../components/common'
import { UploadZone } from '../components/UploadZone'

type GoldFilter = 'all' | 'gold' | 'missing' | 'starred'
type SortBy = 'date-desc' | 'date-asc' | 'name-asc' | 'pages-desc' | 'pages-asc' | 'id-desc'

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
      } catch {}
      return next
    })
  }

  return { starred, toggleStar }
}

export default function Datasets() {
  const [params] = useSearchParams()
  const documents = useDocuments()
  const actions = useActions()
  const [selected, setSelected] = useState<number>(() => Number(params.get('document')) || 0)
  const [search, setSearch] = useState('')
  const [filter, setFilter] = useState<GoldFilter>('all')
  const [sortBy, setSortBy] = useState<SortBy>('date-desc')
  const { starred, toggleStar } = useStarredDocs()
  const gold = useGold(selected || undefined)
  const [text, setText] = useState('{}')
  const [jsonError, setJsonError] = useState<string>()

  useEffect(() => {
    if (gold.data) setText(JSON.stringify(gold.data.tasks ?? {}, null, 2))
  }, [gold.data])

  const shown = useMemo(() => {
    const query = search.trim().toLowerCase()
    const filtered = (documents.data ?? []).filter(doc => {
      if (filter === 'gold' && !doc.has_gold) return false
      if (filter === 'missing' && doc.has_gold) return false
      if (filter === 'starred' && !starred.has(doc.id)) return false
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
  }, [documents.data, search, filter, sortBy, starred])

  const selectedDoc = documents.data?.find(doc => doc.id === selected)

  const save = async () => {
    try {
      const tasks = JSON.parse(text) as Record<string, unknown>
      setJsonError(undefined)
      await actions.saveGold.mutateAsync({ id: selected, tasks })
    } catch (error) {
      setJsonError(error instanceof Error ? error.message : String(error))
    }
  }

  return (
    <>
      <header className="page-title">
        <div>
          <span className="eyebrow">Corpus</span>
          <h1>Datasets & Ground Truth</h1>
          <p>Manage claim PDFs and the task outputs used for dependency feeds and scoring.</p>
        </div>
      </header>

      <div className="grid two">
        <Card>
          <div className="card-header">
            <h2>Documents</h2>
            {documents.data && <span className="count-pill">{documents.data.length} documents</span>}
          </div>

          <UploadZone busy={actions.upload.isPending} onUpload={files => actions.upload.mutateAsync(files)} />
          <UploadZone
            accept=".json,.csv"
            label="Import gold JSON or CSV"
            busy={actions.importGold.isPending}
            onUpload={files => actions.importGold.mutateAsync(files)}
          />

          <div className="picker-toolbar">
            <label className="search" style={{ maxWidth: 'none', margin: 0 }}>
              <input value={search} onChange={event => setSearch(event.target.value)} placeholder="Search documents" aria-label="Search documents" />
            </label>
            <div className="segmented">
              <button type="button" className={filter === 'all' ? 'active' : ''} onClick={() => setFilter('all')}>All</button>
              <button type="button" className={filter === 'gold' ? 'active' : ''} onClick={() => setFilter('gold')}>Gold</button>
              <button type="button" className={filter === 'missing' ? 'active' : ''} onClick={() => setFilter('missing')}>Missing</button>
              <button type="button" className={filter === 'starred' ? 'active' : ''} onClick={() => setFilter('starred')}>
                ⭐ Starred {starred.size > 0 ? `(${starred.size})` : ''}
              </button>
            </div>
            <select
              value={sortBy}
              onChange={event => setSortBy(event.target.value as SortBy)}
              aria-label="Sort documents"
              title="Sort documents by"
            >
              <option value="date-desc">🕒 Date (Newest)</option>
              <option value="date-asc">🕒 Date (Oldest)</option>
              <option value="name-asc">🔤 Name (A → Z)</option>
              <option value="pages-desc">📄 Pages (High → Low)</option>
              <option value="pages-asc">📄 Pages (Low → High)</option>
              <option value="id-desc">🔢 ID (#)</option>
            </select>
          </div>

          {documents.isLoading ? (
            <Spinner />
          ) : shown.length ? (
            <div className="document-list compact">
              {shown.map(doc => {
                const isStarred = starred.has(doc.id)
                return (
                  <button className={selected === doc.id ? 'selected' : ''} key={doc.id} onClick={() => setSelected(doc.id)}>
                    <span
                      className={`star-btn ${isStarred ? 'starred' : ''}`}
                      role="button"
                      tabIndex={0}
                      onClick={event => toggleStar(doc.id, event)}
                      title={isStarred ? 'Unstar document' : 'Star document'}
                      aria-label={isStarred ? 'Unstar document' : 'Star document'}
                    >
                      {isStarred ? '⭐' : '☆'}
                    </span>
                    <span className="grow">
                      <strong>{doc.filename ?? doc.name}</strong>
                      <small>
                        #{doc.id} · {doc.page_count ?? '—'} pages · {doc.origin ?? 'test-docs'}
                        {doc.created_at && (
                          <span title={`Uploaded: ${new Date(doc.created_at).toLocaleString()}`}>
                            {' · 🕒 '}{formatBriefDate(doc.created_at)}
                          </span>
                        )}
                      </small>
                    </span>
                    <Badge tone={doc.has_gold ? 'good' : 'warn'}>{doc.has_gold ? 'gold' : 'missing'}</Badge>
                    <a
                      className="button ghost sm"
                      href={`/api/documents/${doc.id}/file`}
                      target="_blank"
                      rel="noreferrer"
                      onClick={event => event.stopPropagation()}
                      title="Open PDF in new tab"
                      style={{ marginLeft: '0.4rem', padding: '0.1rem 0.4rem', fontSize: '0.75rem' }}
                    >
                      📄 View PDF
                    </a>
                    {doc.origin === 'upload' && (
                      <span
                        className="danger-link"
                        role="button"
                        tabIndex={0}
                        onClick={event => {
                          event.stopPropagation()
                          if (confirm('Delete this uploaded document?')) actions.deleteDocument.mutate(doc.id)
                        }}
                      >
                        Delete
                      </span>
                    )}
                  </button>
                )
              })}
            </div>
          ) : (
            <Empty>{documents.data?.length ? 'No documents match your search.' : 'No documents.'}</Empty>
          )}
          <ErrorBox error={documents.error ?? actions.upload.error ?? actions.importGold.error} />

        </Card>

        <Card>
          <div className="card-header">
            <h2>Gold editor</h2>
            {selectedDoc && <Badge tone="info">{selectedDoc.filename ?? selectedDoc.name}</Badge>}
          </div>
          {!selected ? (
            <Empty>Pick a document to edit its gold JSON.</Empty>
          ) : gold.isLoading ? (
            <Spinner />
          ) : (
            <>
              <p className="muted">Top-level keys are task names. JSON is validated before save.</p>
              <textarea className="json-editor" value={text} onChange={event => setText(event.target.value)} spellCheck={false} />
              {jsonError && <div className="alert bad">Invalid JSON: {jsonError}</div>}
              <div className="row end">
                <button className="primary" disabled={actions.saveGold.isPending} onClick={() => void save()}>
                  {actions.saveGold.isPending ? 'Saving…' : 'Save gold'}
                </button>
              </div>
              <ErrorBox error={gold.error ?? actions.saveGold.error} />
            </>
          )}
        </Card>
      </div>
    </>
  )
}
