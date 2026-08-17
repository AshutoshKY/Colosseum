import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useActions, useFields, useLeaderboard, useResults, useRun, useSideBySide } from '../api/hooks'
import { AccuracyCostChart, LeaderboardTable } from '../components/LeaderboardTable'
import { CostBreakdown } from '../components/CostBreakdown'
import { FieldBreakdown } from '../components/FieldBreakdown'
import { JsonDiffTree } from '../components/JsonDiffTree'
import { JudgePanel } from '../components/JudgePanel'
import { Badge, badgeHue, Card, Empty, ErrorBox, formatDuration, Modal, Spinner } from '../components/common'
import type { JudgeMode, LeaderboardRow, SideBySide } from '../types'

type Tab = 'leaderboard' | 'side' | 'fields' | 'cost' | 'judge'

const TABS: Array<[Tab, string]> = [
  ['leaderboard', 'Leaderboard'],
  ['side', 'Side-by-side'],
  ['fields', 'Field breakdown'],
  ['cost', 'Cost & Tokens'],
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
  const navigate = useNavigate()
  const [tab, setTab] = useState<Tab>('leaderboard')
  const [judgeRequested, setJudgeRequested] = useState(false)
  const [showPdfModal, setShowPdfModal] = useState(false)
  const actions = useActions()
  const run = useRun(id, tab === 'judge' && (judgeRequested || actions.judge.isPending))
  const results = useResults(id)
  const board = useLeaderboard(id)

  const handleDeleteRun = async () => {
    if (!id) return
    const runName = run.data?.run.name ?? `Run #${id}`
    if (confirm(`Delete run "${runName}" and all its results? This cannot be undone.`)) {
      await actions.deleteRun.mutateAsync(Number(id))
      navigate('/runs')
    }
  }

  const tasks = useMemo(() => run.data?.run.spec.selected_tasks ?? [], [run.data?.run.spec.selected_tasks])
  const docs = [...new Map(
    (run.data?.cells ?? []).map(cell => [cell.document_id, { id: cell.document_id, name: cell.document_name ?? cell.document ?? `Document ${cell.document_id}` }]),
  ).values()].filter(doc => doc.id) as Array<{ id: number; name: string }>

  const [task, setTask] = useState('')
  const [documentId, setDocumentId] = useState<number>()
  const [judgeTasks, setJudgeTasks] = useState<string[]>([])
  const [judgeDocumentIds, setJudgeDocumentIds] = useState<number[]>([])
  const judgeScopeInitialized = useRef(false)
  const activeTask = task || tasks[0]
  const activeDoc = documentId ?? docs[0]?.id
  const fields = useFields(id, activeTask)
  const judgeRunning = judgeRequested || run.data?.run.judge_status === 'running' || actions.judge.isPending
  const side = useSideBySide(id, activeDoc, activeTask, tab === 'judge' && judgeRunning)

  useEffect(() => {
    if (judgeRequested && ['completed', 'failed'].includes(run.data?.run.judge_status ?? '')) setJudgeRequested(false)
  }, [judgeRequested, run.data?.run.judge_status])

  useEffect(() => {
    if (judgeScopeInitialized.current || !tasks.length || !docs.length) return
    judgeScopeInitialized.current = true
    setJudgeTasks(tasks)
    setJudgeDocumentIds(docs.map(doc => doc.id))
  }, [tasks, docs])

  const groups = useMemo(
    () => Object.entries((board.data ?? []).reduce<Record<string, LeaderboardRow[]>>((all, row) => {
      ;(all[row.task] ??= []).push(row)
      return all
    }, {})),
    [board.data],
  )

  const outputs: Record<string, ModelOutput> =
    side.data?.models ?? Object.fromEntries((side.data?.outputs ?? []).map(item => [item.model_id, item]))

  const judge = (model: string, modes: JudgeMode[]) => {
    setJudgeRequested(true)
    actions.judge.mutate({ id: id ?? '', body: { model_id: model, modes, task_names: judgeTasks, document_ids: judgeDocumentIds } }, { onError: () => setJudgeRequested(false) })
  }

  const selectors = (
    <div className="row selectors" style={{ alignItems: 'flex-end', flexWrap: 'wrap', gap: '0.75rem' }}>
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
      {activeDoc && tab === 'side' && (
        <div className="row gap-xs" style={{ marginBottom: '0.2rem' }}>
          <button type="button" className="secondary" onClick={() => setShowPdfModal(true)}>
            📄 View PDF
          </button>
          <a className="button ghost" href={`/api/documents/${activeDoc}/file`} target="_blank" rel="noreferrer" title="Open PDF in new tab">
            ↗ Open in new tab
          </a>
        </div>
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
          <button
            type="button"
            className="danger"
            disabled={actions.deleteRun.isPending}
            onClick={() => void handleDeleteRun()}
            title="Delete this run and all its results"
          >
            {actions.deleteRun.isPending ? 'Deleting…' : 'Delete run'}
          </button>
        </div>
      </header>
      <ErrorBox error={actions.deleteRun.error} />

      <nav className="tabs">
        {TABS.map(([key, label]) => (
          <button className={tab === key ? 'active' : ''} key={key} onClick={() => setTab(key)}>{label}</button>
        ))}
      </nav>
      {(tab === 'side' || tab === 'fields') && selectors}
      {tab === 'judge' && <JudgeScopePicker
        tasks={tasks}
        documents={docs}
        selectedTasks={judgeTasks}
        selectedDocumentIds={judgeDocumentIds}
        onTasksChange={setJudgeTasks}
        onDocumentsChange={setJudgeDocumentIds}
      />}

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
                  <small>{formatDuration(item.latency_ms)}{item.completed_at ? ` · completed ${new Date(item.completed_at).toLocaleString()}` : ''}</small>
                  <JsonDiffTree value={item.parsed_output} metrics={item.field_metrics as Record<string, unknown>} />
                  <details>
                    <summary>Prompt {item.prompt_version ? `(${item.prompt_version})` : ''} & raw response</summary>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem', marginTop: '0.5rem' }}>
                      {item.prompt_version && (
                        <div>
                          <strong>Prompt version: </strong>
                          <span className="badge neutral">{item.prompt_version}</span>
                        </div>
                      )}
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

      {tab === 'cost' && (
        run.isLoading ? <Spinner /> : <CostBreakdown runDetail={run.data} cells={results.data?.results ?? run.data?.cells} />
      )}

      {tab === 'judge' && (
        <Card>
          <h2>Judge</h2>
          <JudgeStatus status={run.data?.run.judge_status} />
          <JudgePanel onRun={judge} busy={actions.judge.isPending || !judgeTasks.length || !judgeDocumentIds.length} error={actions.judge.error} />
          <JudgeResults outputs={outputs} rankings={side.data?.judge} />
          <ErrorBox error={side.error} />
        </Card>
      )}

      <ErrorBox error={run.error ?? board.error} />

      {showPdfModal && activeDoc && (
        <Modal title={`Document PDF · ${docs.find(d => d.id === activeDoc)?.name ?? activeDoc}`} onClose={() => setShowPdfModal(false)}>
          <div className="row between" style={{ marginBottom: '0.6rem' }}>
            <span className="muted">Viewing document #{activeDoc}</span>
            <a className="button primary sm" href={`/api/documents/${activeDoc}/file`} target="_blank" rel="noreferrer">
              ↗ Open in new tab
            </a>
          </div>
          <iframe
            src={`/api/documents/${activeDoc}/file`}
            title={`Document PDF ${activeDoc}`}
            style={{ width: '100%', height: '70vh', border: '1px solid var(--border)', borderRadius: '6px', backgroundColor: '#fff' }}
          />
        </Modal>
      )}
    </>
  )
}

function JudgeScopePicker({
  tasks, documents, selectedTasks, selectedDocumentIds, onTasksChange, onDocumentsChange,
}: {
  tasks: string[]
  documents: Array<{ id: number; name: string }>
  selectedTasks: string[]
  selectedDocumentIds: number[]
  onTasksChange: (items: string[]) => void
  onDocumentsChange: (items: number[]) => void
}) {
  const toggle = <T,>(value: T, selected: T[], onChange: (items: T[]) => void) =>
    onChange(selected.includes(value) ? selected.filter(item => item !== value) : [...selected, value])
  return <div className="row selectors judge-scope">
    <fieldset>
      <legend>Agents</legend>
      <label><input type="checkbox" checked={selectedTasks.length === tasks.length} onChange={event => onTasksChange(event.target.checked ? tasks : [])} /> All agents</label>
      {tasks.map(item => <label key={item}><input type="checkbox" checked={selectedTasks.includes(item)} onChange={() => toggle(item, selectedTasks, onTasksChange)} /> {item.replaceAll('_', ' ')}</label>)}
    </fieldset>
    <fieldset>
      <legend>Claims</legend>
      <label><input type="checkbox" checked={selectedDocumentIds.length === documents.length} onChange={event => onDocumentsChange(event.target.checked ? documents.map(item => item.id) : [])} /> All claims</label>
      {documents.map(item => <label key={item.id}><input type="checkbox" checked={selectedDocumentIds.includes(item.id)} onChange={() => toggle(item.id, selectedDocumentIds, onDocumentsChange)} /> {item.name}</label>)}
    </fieldset>
  </div>
}

function RawResponse({ value }: { value: unknown }) {
  const { isJson, parsed } = tryParseJson(value)
  return isJson ? <JsonDiffTree value={parsed} /> : <pre>{String(value)}</pre>
}

interface JudgeGrade { overall_score?: number; summary?: string; field_verdicts?: JudgeVerdict[] }
interface JudgeVerdict { field_path?: string; verdict?: string; explanation?: string }
interface HeadToHead { judge_model?: string; payload?: { ranking?: Array<{ model_id?: string; rank?: number; strengths?: string; weaknesses?: string }>; rationale?: string; confidence?: string }; rationale?: string }

function JudgeStatus({ status }: { status?: string }) {
  if (!status) return <div className="alert info">Choose one or more evaluation modes, then run the AI judge.</div>
  const tone = status === 'completed' ? 'good' : status === 'failed' ? 'bad' : 'info'
  return <div className={`alert ${tone}`}>{status === 'running' ? <><span className="spinner judge-spinner" /> The AI judge is running. Results will appear here automatically.</> : `Judge status: ${status}`}</div>
}

function JudgeResults({ outputs, rankings }: { outputs: Record<string, ModelOutput>; rankings: unknown }) {
  const scores = Object.entries(outputs).filter(([, item]) => item.judge)
  const headToHead = Array.isArray(rankings) ? rankings as HeadToHead[] : []
  if (!scores.length && !headToHead.length) return <Empty>No judge output for this document and task yet.</Empty>
  return <div className="judge-results">
    {scores.length > 0 && <section><h3>Gold standard & document grades</h3><div className="judge-grade-grid">{scores.map(([model, item]) => <JudgeScores key={model} model={model} judge={item.judge} />)}</div></section>}
    {headToHead.length > 0 && <section><h3>Head-to-head ranking</h3>{headToHead.map((result, index) => <HeadToHeadResult key={`${result.judge_model ?? 'judge'}-${index}`} result={result} />)}</section>}
  </div>
}

function JudgeScores({ model, judge }: { model: string; judge: unknown }) {
  const score = judge as (JudgeGrade & { grades?: Record<string, JudgeGrade> }) | undefined
  if (!score) return null
  return (
    <article className="judge-grade-card">
      <h3>{model}</h3>
      {Object.entries(score.grades ?? { grade: score }).map(([mode, grade]) => (
        <div className="judge-mode-result" key={mode}>
          <div className="row between"><strong>{mode === 'gold_grade' ? 'Gold standard' : mode === 'doc_grade' ? 'Document grade' : mode.replaceAll('_', ' ')}</strong><span className="judge-score">{grade.overall_score == null ? '—' : `${Math.round(grade.overall_score * 100)}%`}</span></div>
          {grade.summary && <p>{grade.summary}</p>}
          {(grade.field_verdicts?.length ?? 0) > 0 && <details><summary>{grade.field_verdicts?.length} field findings</summary>{grade.field_verdicts?.map((verdict, index) => <div className="judge-finding" key={index}><Badge tone={verdict.verdict === 'match' || verdict.verdict === 'acceptable_variant' ? 'good' : 'bad'}>{verdict.verdict?.replaceAll('_', ' ') ?? 'finding'}</Badge><code>{verdict.field_path}</code><p>{verdict.explanation}</p></div>)}</details>}
        </div>
      ))}
    </article>
  )
}

function HeadToHeadResult({ result }: { result: HeadToHead }) {
  const ranking = result.payload?.ranking ?? []
  return <article className="head-to-head-card"><div className="row between"><strong>{result.judge_model ?? 'AI judge'}</strong>{result.payload?.confidence && <Badge tone="info">{result.payload.confidence} confidence</Badge>}</div>{ranking.length > 0 ? <ol className="ranking-list">{[...ranking].sort((a, b) => (a.rank ?? 99) - (b.rank ?? 99)).map(row => <li key={`${row.model_id}-${row.rank}`}><div><strong>#{row.rank} {row.model_id}</strong>{row.strengths && <p><b>Strengths:</b> {row.strengths}</p>}{row.weaknesses && <p><b>Weaknesses:</b> {row.weaknesses}</p>}</div></li>)}</ol> : <p className="muted">No ranking was returned.</p>}{(result.payload?.rationale ?? result.rationale) && <p className="judge-rationale"><b>Judge rationale:</b> {result.payload?.rationale ?? result.rationale}</p>}</article>
}
