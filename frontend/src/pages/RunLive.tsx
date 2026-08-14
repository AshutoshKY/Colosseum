import { useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { subscribeToRun } from '../api/sse'
import { useActions, useResults, useRun } from '../api/hooks'
import type { Cell, ProgressEvent, RunDetail } from '../types'
import { Badge, badgeHue, Card, ErrorBox, formatDuration, Modal, money, Spinner } from '../components/common'
import { RunGrid, cellKey } from '../components/RunGrid'
import { JsonDiffTree } from '../components/JsonDiffTree'

const statusTone = (status: string) =>
  status === 'completed' || status === 'succeeded' ? 'good' : status === 'failed' ? 'bad' : status === 'running' ? 'info' : 'neutral'

function tryParseJson(value: unknown) {
  if (typeof value === 'string') {
    const trimmed = value.trim()
    if ((trimmed.startsWith('{') && trimmed.endsWith('}')) || (trimmed.startsWith('[') && trimmed.endsWith(']'))) {
      try {
        return { isJson: true, parsed: JSON.parse(trimmed) as unknown }
      } catch {
        /* fall through to plain text */
      }
    }
  } else if (value !== null && typeof value === 'object') {
    return { isJson: true, parsed: value }
  }
  return { isJson: false, parsed: value }
}

export default function RunLive() {
  const { id } = useParams()
  const client = useQueryClient()
  const [polling, setPolling] = useState(false)
  const [selected, setSelected] = useState<Cell>()
  const detail = useRun(id, polling)
  const results = useResults(id)
  const actions = useActions()

  // Live updates over SSE; fall back to polling if the stream drops.
  useEffect(() => {
    if (!id || polling) return
    return subscribeToRun(
      id,
      event => client.setQueryData<RunDetail>(['run', id], current => applyEvent(current, event)),
      () => setPolling(true),
    ).close
  }, [id, polling, client])

  const run = detail.data?.run
  const cells = useMemo(() => detail.data?.cells ?? [], [detail.data?.cells])
  const cost = useMemo(() => cells.reduce((total, cell) => total + (cell.cost_usd ?? 0), 0), [cells])
  const terminal = run && ['completed', 'failed', 'cancelled'].includes(run.status)
  const selectedDetail = selected
    ? results.data?.results.find(cell =>
        cell.document_id === selected.document_id && cell.model_id === selected.model_id && cell.task === selected.task,
      ) ?? selected
    : undefined

  return (
    <>
      <header className="page-title">
        <div>
          <span className="eyebrow">Live run #{id}</span>
          <h1>{run?.name ?? 'Run progress'}</h1>
          <div className="row">
            {run && <Badge tone={statusTone(run.status)}>{run.status}</Badge>}
            {polling && <Badge tone="warn">SSE unavailable · polling every 3s</Badge>}
          </div>
          <div className="badges compact" style={{ marginTop: '0.4rem' }}>
            {(run?.spec?.model_ids ?? []).map(model => (
              <span key={model} className={`badge ${badgeHue(model, 'model')}`}>{model.split('/').pop()}</span>
            ))}
            {run?.spec?.compression?.enabled && <Badge tone="warn">🗜 compressed · {run.spec.compression.max_megapixels} MP</Badge>}
            {run?.spec?.prompt_overrides && Object.keys(run.spec.prompt_overrides).length > 0 && <Badge tone="warn">✏️ prompt override</Badge>}
          </div>
        </div>
        <div className="row">
          {run && ['pending', 'running'].includes(run.status) && (
            <button className="danger" onClick={() => confirm('Cancel this run?') && actions.cancel.mutate(Number(id))}>
              Cancel run
            </button>
          )}
          <Link className="button" to="/runs">All runs</Link>
        </div>
      </header>

      {terminal && (
        <div className={`alert ${run.status === 'failed' ? 'bad' : 'good'}`}>
          Run is {run.status}.{run.failure_reason ? ` ${run.failure_reason}` : ''} <Link to={`/runs/${id}/results`}>View results →</Link>
        </div>
      )}

      <div className="metrics">
        <Card><span>Completed</span><strong>{run ? run.counts.succeeded + run.counts.failed + run.counts.skipped : 0}/{run?.counts.total ?? 0}</strong></Card>
        <Card><span>Failed</span><strong>{run?.counts.failed ?? 0}</strong></Card>
        <Card><span>Running cost</span><strong>{money(cost)}</strong></Card>
        <Card><span>Started</span><strong>{run ? new Date(run.created_at).toLocaleTimeString() : '—'}</strong></Card>
        <Card><span>Elapsed</span><strong>{formatDuration(run?.elapsed_ms)}</strong></Card>
      </div>

      <Card>
        <h2>Progress grid</h2>
        <p className="muted grid-help">Use <strong>View result</strong> when a claim is complete, or when all processing for a document has finished. You do not need to wait for the whole run.</p>
        {detail.isLoading ? (
          <Spinner />
        ) : (
          <RunGrid cells={cells} spec={run?.spec} onCell={cell => { setSelected(cell); void results.refetch() }} />
        )}
        <ErrorBox error={detail.error ?? actions.cancel.error} />
      </Card>

      {selectedDetail && (
        <Modal title={`${selectedDetail.task} · ${selectedDetail.model_id}`} onClose={() => setSelected(undefined)}>
          <dl className="details">
            <dt>Status</dt><dd><Badge tone={statusTone(selectedDetail.status)}>{selectedDetail.status}</Badge></dd>
            <dt>Document</dt><dd>{selectedDetail.document_name ?? selectedDetail.document ?? selectedDetail.document_id ?? '—'}</dd>
            <dt>Prompt version</dt><dd><Badge tone={selectedDetail.prompt_version?.startsWith('db:') ? 'good' : selectedDetail.prompt_version === 'override' ? 'warn' : 'neutral'}>{selectedDetail.prompt_version ?? 'code baseline'}</Badge></dd>
            <dt>Queued</dt><dd>{selectedDetail.created_at ? new Date(selectedDetail.created_at).toLocaleString() : '—'}</dd>
            <dt>Completed</dt><dd>{selectedDetail.completed_at ? new Date(selectedDetail.completed_at).toLocaleString() : '—'}</dd>
            <dt>Execution time</dt><dd>{formatDuration(selectedDetail.latency_ms)}</dd>
            <dt>Cost</dt><dd>{selectedDetail.cost_usd != null ? money(selectedDetail.cost_usd) : '—'}</dd>
            <dt>Retries</dt><dd>{selectedDetail.retries ?? '—'}</dd>
          </dl>

          {(selectedDetail.error || selectedDetail.skip_reason) && (
            <div className="alert bad"><pre>{selectedDetail.error ?? selectedDetail.skip_reason}</pre></div>
          )}

          {selectedDetail.prompt_system || selectedDetail.prompt_instruction ? (
            <details>
              <summary>Prompt {selectedDetail.prompt_version ? `(${selectedDetail.prompt_version})` : ''}</summary>
              <pre>{selectedDetail.prompt_system}{'\n\n'}{selectedDetail.prompt_instruction}</pre>
            </details>
          ) : (
            <p className="muted">Prompt is available once the cell has run.</p>
          )}

          {selectedDetail.parsed_output != null && (
            <details open>
              <summary>Result</summary>
              <JsonDiffTree value={selectedDetail.parsed_output} />
            </details>
          )}

          {selectedDetail.raw_response != null ? (
            <details>
              <summary>Raw response</summary>
              <RawResponse value={selectedDetail.raw_response} />
            </details>
          ) : (
            <p className="muted">No raw response yet — this cell has not produced a model reply.</p>
          )}
        </Modal>
      )}
    </>
  )
}

function RawResponse({ value }: { value: unknown }) {
  const { isJson, parsed } = tryParseJson(value)
  return isJson ? <JsonDiffTree value={parsed} /> : <pre>{String(value)}</pre>
}

export function applyEvent(current: RunDetail | undefined, event: ProgressEvent): RunDetail | undefined {
  if (!current) return current
  if (event.type === 'run') {
    return { ...current, run: { ...current.run, status: event.status as typeof current.run.status, counts: event.counts ?? current.run.counts } }
  }
  const next: Cell = {
    document_id: event.document_id,
    document: event.document,
    model_id: event.model_id ?? '',
    task: event.task ?? '',
    status: event.status as Cell['status'],
    latency_ms: event.latency_ms,
    cost_usd: event.cost_usd,
    error: event.error,
    skip_reason: event.skip_reason,
  }
  const key = cellKey(next)
  const index = current.cells.findIndex(cell => cellKey(cell) === key)
  const cells = [...current.cells]
  if (index >= 0) cells[index] = { ...cells[index], ...next }
  else cells.push(next)
  return { ...current, cells }
}
