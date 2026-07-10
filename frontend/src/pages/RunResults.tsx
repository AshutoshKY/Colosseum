import { useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useActions, useFields, useLeaderboard, useRun, useSideBySide } from '../api/hooks'
import { AccuracyCostChart, LeaderboardTable } from '../components/LeaderboardTable'
import { FieldBreakdown } from '../components/FieldBreakdown'
import { JsonDiffTree } from '../components/JsonDiffTree'
import { JudgePanel } from '../components/JudgePanel'
import { Badge, badgeHue, Card, Empty, ErrorBox, Spinner } from '../components/common'
import type { JudgeMode, LeaderboardRow, SideBySide } from '../types'

type Tab = 'leaderboard' | 'side' | 'fields' | 'judge'

const TABS: Array<[Tab, string]> = [
  ['leaderboard', 'Leaderboard'],
  ['side', 'Side-by-side'],
  ['fields', 'Field breakdown'],
  ['judge', 'Judge'],
]

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

type ModelOutput = Omit<NonNullable<SideBySide['outputs']>[number], 'model_id'>

export default function RunResults() {
  const { id } = useParams()
  const [tab, setTab] = useState<Tab>('leaderboard')
  const run = useRun(id)
  const board = useLeaderboard(id)
  const actions = useActions()

  const tasks = run.data?.run.spec.selected_tasks ?? []
  const docs = [...new Map(
    (run.data?.cells ?? []).map(cell => [cell.document_id, { id: cell.document_id, name: cell.document_name ?? cell.document ?? `Document ${cell.document_id}` }]),
  ).values()].filter(doc => doc.id) as Array<{ id: number; name: string }>

  const [task, setTask] = useState('')
  const [documentId, setDocumentId] = useState<number>()
  const activeTask = task || tasks[0]
  const activeDoc = documentId ?? docs[0]?.id
  const fields = useFields(id, activeTask)
  const side = useSideBySide(id, activeDoc, activeTask)

  const groups = useMemo(
    () => Object.entries((board.data ?? []).reduce<Record<string, LeaderboardRow[]>>((all, row) => {
      ;(all[row.task] ??= []).push(row)
      return all
    }, {})),
    [board.data],
  )

  const outputs: Record<string, ModelOutput> =
    side.data?.models ?? Object.fromEntries((side.data?.outputs ?? []).map(item => [item.model_id, item]))

  const judge = (model: string, modes: JudgeMode[]) => actions.judge.mutate({ id: id ?? '', body: { model_id: model, modes } })

  const selectors = (
    <div className="row selectors">
      <label>
        Task
        <select value={activeTask} onChange={event => setTask(event.target.value)}>
          {tasks.map(value => <option key={value}>{value}</option>)}
        </select>
      </label>
      {tab !== 'fields' && (
        <label>
          Document
          <select value={activeDoc ?? ''} onChange={event => setDocumentId(Number(event.target.value))}>
            {docs.map(doc => <option value={doc.id} key={doc.id}>{doc.name}</option>)}
          </select>
        </label>
      )}
    </div>
  )

  return (
    <>
      <header className="page-title">
        <div>
          <span className="eyebrow">Results · run #{id}</span>
          <h1>{run.data?.run.name ?? 'Benchmark results'}</h1>
          <div className="badges compact" style={{ marginTop: '0.4rem' }}>
            {(run.data?.run.spec?.model_ids ?? []).map(model => (
              <span key={model} className={`badge ${badgeHue(model, 'model')}`}>{model.split('/').pop()}</span>
            ))}
            {run.data?.run.spec?.compression?.enabled && (
              <Badge tone="warn">🗜 compressed · {run.data.run.spec.compression.max_megapixels} MP</Badge>
            )}
          </div>
        </div>
        <div className="row">
          <a className="button" href={`/api/runs/${id}/export?format=json`} download>Export JSON</a>
          <a className="button" href={`/api/runs/${id}/export?format=csv`} download>Export CSV</a>
          <Link className="button" to={`/runs/${id}`}>Live grid</Link>
        </div>
      </header>

      <nav className="tabs">
        {TABS.map(([key, label]) => (
          <button className={tab === key ? 'active' : ''} key={key} onClick={() => setTab(key)}>{label}</button>
        ))}
      </nav>
      {(tab === 'side' || tab === 'fields' || tab === 'judge') && selectors}

      {tab === 'leaderboard' && (
        board.isLoading ? <Spinner /> : groups.length ? (
          groups.map(([name, rows]) => (
            <Card key={name}>
              <h2>{name.replaceAll('_', ' ')}</h2>
              <LeaderboardTable rows={rows ?? []} />
              <h3>Accuracy vs cost</h3>
              <AccuracyCostChart rows={rows ?? []} />
            </Card>
          ))
        ) : (
          <Empty>No scored results yet.</Empty>
        )
      )}

      {tab === 'side' && (
        <Card>
          {side.isLoading ? (
            <Spinner />
          ) : side.data ? (
            <div className="comparison">
              <section>
                <h3>Gold</h3>
                <JsonDiffTree value={side.data.gold} />
              </section>
              {Object.entries(outputs).map(([model, item]) => (
                <section key={model}>
                  <h3>{model}</h3>
                  <JsonDiffTree value={item.parsed_output} metrics={item.field_metrics as Record<string, unknown>} />
                  <details>
                    <summary>Prompt & raw response</summary>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem', marginTop: '0.5rem' }}>
                      <strong>System prompt:</strong>
                      <pre>{item.prompt_system}</pre>
                      <strong>Instruction prompt:</strong>
                      <pre>{item.prompt_instruction}</pre>
                      <strong>Response:</strong>
                      <RawResponse value={item.raw_response} />
                    </div>
                  </details>
                </section>
              ))}
            </div>
          ) : (
            <Empty>Select a document and task with results.</Empty>
          )}
          <ErrorBox error={side.error} />
        </Card>
      )}

      {tab === 'fields' && (
        <Card>
          {fields.isLoading ? <Spinner /> : fields.data?.length ? <FieldBreakdown rows={fields.data} /> : <Empty>No field metrics for this task.</Empty>}
          <ErrorBox error={fields.error} />
        </Card>
      )}

      {tab === 'judge' && (
        <Card>
          <h2>Judge</h2>
          {run.data?.run.judge_status
            ? <div className="alert info">Judge status: {run.data.run.judge_status}</div>
            : <Empty>This run has no judge output yet.</Empty>}
          <JudgePanel onRun={judge} busy={actions.judge.isPending} error={actions.judge.error} />
          <div className="comparison">
            {Object.entries(outputs).map(([model, item]) => <JudgeScores key={model} model={model} judge={item.judge} />)}
          </div>
          {Boolean(side.data?.judge) && (
            <details open>
              <summary>Head-to-head rankings</summary>
              <JsonDiffTree value={side.data?.judge} />
            </details>
          )}
        </Card>
      )}

      <ErrorBox error={run.error ?? board.error} />
    </>
  )
}

function RawResponse({ value }: { value: unknown }) {
  const { isJson, parsed } = tryParseJson(value)
  return isJson ? <JsonDiffTree value={parsed} /> : <pre>{String(value)}</pre>
}

interface JudgeGrade { overall_score?: number; summary?: string; field_verdicts?: unknown[] }

function JudgeScores({ model, judge }: { model: string; judge: unknown }) {
  const score = judge as (JudgeGrade & { grades?: Record<string, JudgeGrade> }) | undefined
  if (!score) return null
  return (
    <section>
      <h3>{model}</h3>
      {Object.entries(score.grades ?? { grade: score }).map(([mode, grade]) => (
        <div key={mode}>
          <strong>{mode.replaceAll('_', ' ')}: {grade.overall_score == null ? '—' : `${Math.round(grade.overall_score * 100)}%`}</strong>
          <p>{grade.summary}</p>
          <small>{grade.field_verdicts?.length ?? 0} field findings</small>
        </div>
      ))}
    </section>
  )
}
