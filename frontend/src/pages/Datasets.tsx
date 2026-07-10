import { useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useActions, useDocuments, useGold } from '../api/hooks'
import { Badge, Card, Empty, ErrorBox, Spinner } from '../components/common'
import { UploadZone } from '../components/UploadZone'

export default function Datasets() {
  const [params] = useSearchParams()
  const documents = useDocuments()
  const actions = useActions()
  const [selected, setSelected] = useState<number>(() => Number(params.get('document')) || 0)
  const [search, setSearch] = useState('')
  const gold = useGold(selected || undefined)
  const [text, setText] = useState('{}')
  const [jsonError, setJsonError] = useState<string>()

  useEffect(() => {
    if (gold.data) setText(JSON.stringify(gold.data.tasks ?? {}, null, 2))
  }, [gold.data])

  const shown = useMemo(() => {
    const query = search.trim().toLowerCase()
    return (documents.data ?? []).filter(doc => (doc.filename ?? doc.name ?? '').toLowerCase().includes(query))
  }, [documents.data, search])

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
          <span className="eyebrow">Dataset</span>
          <h1>Documents & gold</h1>
          <p>Manage claim PDFs and the task outputs used for dependency feeds and scoring.</p>
        </div>
      </header>

      <div className="two-col">
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

          <label className="search" style={{ maxWidth: 'none' }}>
            <input value={search} onChange={event => setSearch(event.target.value)} placeholder="Search documents" aria-label="Search documents" />
          </label>

          {documents.isLoading ? (
            <Spinner />
          ) : shown.length ? (
            <div className="document-list compact">
              {shown.map(doc => (
                <button className={selected === doc.id ? 'selected' : ''} key={doc.id} onClick={() => setSelected(doc.id)}>
                  <span className="grow">
                    <strong>{doc.filename ?? doc.name}</strong>
                    <small>#{doc.id} · {doc.page_count ?? '—'} pages · {doc.origin ?? 'test-docs'}</small>
                  </span>
                  <Badge tone={doc.has_gold ? 'good' : 'warn'}>{doc.has_gold ? 'gold' : 'missing'}</Badge>
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
              ))}
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
