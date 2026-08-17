import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useActions, useRuns } from '../api/hooks'
import { Badge, badgeHue, Card, Empty, ErrorBox, formatBriefDate, formatDuration, Menu, Modal, money, Spinner } from '../components/common'
import type { RunItem } from '../types'

const statusTone = (status: string) =>
  status === 'completed' ? 'good' : status === 'failed' ? 'bad' : status === 'cancelled' ? 'warn' : status === 'running' ? 'info' : 'neutral'

export default function Runs() {
  const runs = useRuns()
  const actions = useActions()
  const [renaming, setRenaming] = useState<RunItem>()
  const [name, setName] = useState('')

  const runId = (run: RunItem) => run.run_id ?? run.id ?? 0

  const openRename = (run: RunItem) => {
    setRenaming(run)
    setName(run.name)
  }

  const saveRename = async () => {
    if (!renaming || !name.trim()) return
    await actions.renameRun.mutateAsync({ id: runId(renaming), name: name.trim() })
    setRenaming(undefined)
  }

  const remove = (run: RunItem) => {
    if (confirm(`Delete run "${run.name}" and all its results? This cannot be undone.`)) actions.deleteRun.mutate(runId(run))
  }

  return (
    <>
      <header className="page-title">
        <div>
          <span className="eyebrow">History</span>
          <h1>Runs</h1>
          <p>Monitor active benchmarks and revisit completed comparisons.</p>
        </div>
        <Link className="button primary" to="/">New run</Link>
      </header>

      <Card>
        {runs.isLoading ? (
          <Spinner />
        ) : runs.data?.length ? (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Name</th><th>Pack</th><th>Models</th><th>Agents</th><th>Status</th><th>Created</th><th>Duration</th><th>Progress</th><th>Cost</th><th></th>
                </tr>
              </thead>
              <tbody>
                {runs.data.map(run => <RunRow key={runId(run)} run={run} id={runId(run)} onRename={openRename} onDelete={remove} cancel={id => confirm('Cancel this run?') && actions.cancel.mutate(id)} cancelPending={actions.cancel.isPending} deletePending={actions.deleteRun.isPending} />)}
              </tbody>
            </table>
          </div>
        ) : (
          <Empty>No benchmark runs yet.</Empty>
        )}
        <ErrorBox error={runs.error ?? actions.cancel.error ?? actions.renameRun.error ?? actions.deleteRun.error} />
      </Card>

      {renaming && (
        <Modal title="Rename run" onClose={() => setRenaming(undefined)}>
          <form onSubmit={event => { event.preventDefault(); void saveRename() }}>
            <label>
              Run name
              <input autoFocus value={name} onChange={event => setName(event.target.value)} />
            </label>
            <div className="row end">
              <button type="button" onClick={() => setRenaming(undefined)}>Cancel</button>
              <button className="primary" type="submit" disabled={!name.trim() || actions.renameRun.isPending}>
                {actions.renameRun.isPending ? 'Saving…' : 'Save'}
              </button>
            </div>
          </form>
        </Modal>
      )}
    </>
  )
}

function RunRow({
  run,
  id,
  onRename,
  onDelete,
  cancel,
  cancelPending,
  deletePending,
}: {
  run: RunItem
  id: number
  onRename: (run: RunItem) => void
  onDelete: (run: RunItem) => void
  cancel: (id: number) => void
  cancelPending: boolean
  deletePending: boolean
}) {
  const done = run.counts.succeeded + run.counts.failed + run.counts.skipped
  const percentDone = run.counts.total ? (done / run.counts.total) * 100 : 0
  const terminal = ['completed', 'failed', 'cancelled'].includes(run.status)
  const active = ['pending', 'running'].includes(run.status)
  const progressState = run.status === 'cancelled' ? 'cancelled' : run.status === 'failed' || run.counts.failed > 0 ? 'failed' : ''

  return (
    <tr>
      <th>
        <Link to={`/runs/${id}`}>{run.name}</Link>
        {run.spec?.compression?.enabled && (
          <Badge tone="warn">🗜 {run.spec.compression.max_megapixels} MP</Badge>
        )}
      </th>
      <td><span className={`badge ${badgeHue(run.pack, 'pack')}`}>{run.pack}</span></td>
      <td>
        <div className="badges compact">
          {(run.spec?.model_ids ?? []).map(model => (
            <span key={model} className={`badge ${badgeHue(model, 'model')}`}>{model.split('/').pop()}</span>
          ))}
        </div>
      </td>
      <td>
        <div className="badges compact">
          {(run.spec?.selected_tasks ?? []).map(task => {
            const hasOverride = Boolean(run.spec?.prompt_overrides?.[task])
            return (
              <span key={task} className={`badge ${badgeHue(task, 'agent')}`} title={hasOverride ? `Prompt override active for ${task}` : `Default prompt for ${task}`}>
                {task.replaceAll('_', ' ')}
                {hasOverride && <small style={{ marginLeft: '0.2rem', opacity: 0.85 }}>✏️</small>}
              </span>
            )
          })}
        </div>
      </td>
      <td><Badge tone={statusTone(run.status)}>{run.status}</Badge></td>
      <td title={new Date(run.created_at).toLocaleString()}>{formatBriefDate(run.created_at)}</td>
      <td>{formatDuration(run.elapsed_ms)}</td>
      <td>
        <div className={`progress ${progressState}`} style={{ width: 60 }}>
          <span style={{ width: `${percentDone}%` }} />
        </div>
        <small>
          {done}/{run.counts.total}
          {run.counts.failed > 0 && <strong style={{ color: 'var(--danger)', marginLeft: '0.4rem' }} title={`${run.counts.failed} tasks failed`}>({run.counts.failed} failed)</strong>}
        </small>
      </td>
      <td>{money(run.cost_usd)}</td>
      <td>
        <Menu
          items={[
            active && { label: 'Cancel', danger: true, onClick: () => !cancelPending && cancel(id) },
            { label: 'Rename', onClick: () => onRename(run) },
            { label: 'Export JSON', href: `/api/runs/${id}/export?format=json`, download: true },
            { label: 'Export CSV', href: `/api/runs/${id}/export?format=csv`, download: true },
            { label: 'Delete', danger: true, onClick: () => !deletePending && onDelete(run) },
          ]}
        />
      </td>
    </tr>
  )
}
