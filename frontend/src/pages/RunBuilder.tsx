import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { includeDependencies, matrixSize } from '../builder'
import { ApiError } from '../api/client'
import { useActions, useCatalog, useDocuments, usePacks, usePrompts } from '../api/hooks'
import { useRunBuilder } from '../context/RunBuilderContext'
import type { DryRun, PackMeta, PackName, Prompt, Runtime, RunSpec, TaskMeta } from '../types'
import { Card, ErrorBox, Spinner } from '../components/common'
import { UploadZone } from '../components/UploadZone'
import { DocumentPicker } from '../components/DocumentPicker'
import { DependencyGraph } from '../components/DependencyGraph'
import { PromptEditor } from '../components/PromptEditor'
import { ModelPicker, textOnlyModels } from '../components/ModelPicker'
import { CostEstimate } from '../components/CostEstimate'

const LARGE_RUN_CELLS = 100

export default function RunBuilder() {
  const { spec, setSpec } = useRunBuilder()
  const navigate = useNavigate()
  const documents = useDocuments()
  const packs = usePacks()
  const catalog = useCatalog()
  const prompts = usePrompts(spec.pack)
  const actions = useActions()

  const [dry, setDry] = useState<DryRun>()
  const [dryError, setDryError] = useState<Error>()
  const [largeConfirmed, setLargeConfirmed] = useState(false)
  const dryVersion = useRef(0)

  const pack = packs.data?.find(item => item.name === spec.pack)
  const tasks = pack?.tasks ?? []
  const size = matrixSize(spec)
  const textOnly = useMemo(() => textOnlyModels(catalog.data ?? [], spec.model_ids), [catalog.data, spec.model_ids])
  const ready = Boolean(
    spec.document_ids.length && spec.selected_tasks.length && spec.model_ids.length &&
    dry && !dryError && (size <= LARGE_RUN_CELLS || largeConfirmed),
  )

  const update = <K extends keyof RunSpec>(key: K, value: RunSpec[K]) =>
    setSpec(current => ({ ...current, [key]: value }))

  // Debounced dry-run validation whenever the spec changes.
  useEffect(() => {
    const version = ++dryVersion.current
    const timer = window.setTimeout(() => {
      if (!spec.document_ids.length || !spec.selected_tasks.length || !spec.model_ids.length) {
        setDry(undefined)
        setDryError(undefined)
        return
      }
      actions.dryRun.mutateAsync(spec)
        .then(value => { if (version === dryVersion.current) { setDry(value); setDryError(undefined) } })
        .catch(error => { if (version === dryVersion.current) { setDry(undefined); setDryError(error as Error) } })
    }, 400)
    return () => clearTimeout(timer)
  }, [spec]) // eslint-disable-line react-hooks/exhaustive-deps

  // Auto-generate a run name until the user edits it manually.
  const isNameEdited = useRef(false)
  useEffect(() => {
    if (isNameEdited.current && spec.name !== '') return
    const dateStr = new Date().toISOString().slice(5, 10)
    const modelPart = spec.model_ids.length
      ? (spec.model_ids[0].split('/').pop() || '') + (spec.model_ids.length > 1 ? `+${spec.model_ids.length - 1}` : '')
      : ''
    const agentPart = spec.selected_tasks.length
      ? (spec.selected_tasks[0].replaceAll('_', '-') || '') + (spec.selected_tasks.length > 1 ? `+${spec.selected_tasks.length - 1}` : '')
      : ''
    const autoName = [spec.pack.toLowerCase(), modelPart, agentPart, dateStr].filter(Boolean).join('-')
    if (spec.name !== autoName) update('name', autoName)
  }, [spec.pack, spec.model_ids, spec.selected_tasks, spec.name]) // eslint-disable-line react-hooks/exhaustive-deps

  const missing = useMemo(() => {
    const body = dryError instanceof ApiError
      ? dryError.body as { detail?: { missing_gold?: Record<string, string[]> }; missing_gold?: Record<string, string[]> }
      : undefined
    return body?.missing_gold ?? body?.detail?.missing_gold
  }, [dryError])

  const selectTasks = (selected: string[]) =>
    update('selected_tasks', spec.upstream_mode === 'model' && pack ? includeDependencies(pack, selected) : selected)

  const setPack = (name: PackName) =>
    setSpec(current => ({ ...current, pack: name, variant: null, selected_tasks: [], prompt_overrides: {}, runtime_overrides: {} }))

  const launch = async () => {
    if (size > LARGE_RUN_CELLS && !largeConfirmed) return
    const body = size > LARGE_RUN_CELLS ? { ...spec, confirm_large: true } : spec
    const response = await actions.launch.mutateAsync(body)
    navigate(`/runs/${response.run_id}`)
  }

  return (
    <div className="builder-layout">
      <main className="builder-flow">
        <header className="page-title">
          <div>
            <span className="eyebrow">New benchmark</span>
            <h1>Build a run</h1>
            <p>Choose claims, pipeline agents, and models. Colosseum validates the full matrix before launch.</p>
          </div>
        </header>

        <Card>
          <h2><span className="step">1</span>Documents</h2>
          <UploadZone busy={actions.upload.isPending} onUpload={files => actions.upload.mutateAsync(files)} />
          <ErrorBox error={actions.upload.error} />
          <DocumentPicker
            documents={documents.data ?? []}
            selected={spec.document_ids}
            onChange={ids => update('document_ids', ids)}
            loading={documents.isLoading}
          />
        </Card>

        <Card>
          <h2><span className="step">2</span>Pipeline</h2>
          <PipelineStep
            spec={spec}
            pack={pack}
            tasks={tasks}
            prompts={prompts.data}
            update={update}
            setPack={setPack}
            selectTasks={selectTasks}
          />
        </Card>

        <Card>
          <h2><span className="step">3</span>Models</h2>
          {catalog.isLoading ? (
            <Spinner />
          ) : (
            <ModelPicker
              models={catalog.data ?? []}
              selected={spec.model_ids}
              onChange={ids => update('model_ids', ids)}
              onVerify={id => actions.verify.mutate(id)}
              verifyingId={actions.verify.isPending ? actions.verify.variables : undefined}
            />
          )}
          <ErrorBox error={actions.verify.error} />
          {textOnly.length > 0 && (
            <div className="alert warn">
              <strong>No PDF or image input</strong>
              <p>
                {textOnly.map(model => model.name ?? model.id).join(', ')}{' '}
                {textOnly.length === 1 ? 'is a text-only model' : 'are text-only models'} and cannot read the uploaded
                documents. Cells for document tasks will fail or return empty output.
              </p>
            </div>
          )}
        </Card>
      </main>

      <aside className="run-summary">
        <Card>
          <span className="eyebrow">Run summary</span>
          <label>
            Name
            <input
              value={spec.name}
              onChange={event => {
                isNameEdited.current = event.target.value !== ''
                update('name', event.target.value)
              }}
            />
          </label>

          <CostEstimate spec={spec} data={dry} error={dryError} />

          <div className="summary-settings">
            <div><span>Compression</span><strong>{spec.compression.enabled ? `on · ${spec.compression.max_megapixels} MP` : 'off'}</strong></div>
            <div><span>Judge</span><strong>{spec.judge.enabled ? spec.judge.model_id : 'off'}</strong></div>
            <div><span>Concurrency</span><strong>{spec.concurrency.global} global</strong></div>
            <div><Link to="/settings">Edit run settings →</Link></div>
          </div>

          {missing && (
            <div className="alert bad">
              <strong>Missing gold</strong>
              {Object.entries(missing).map(([doc, keys]) => (
                <Link key={doc} to={`/datasets?document=${doc}`}>Document {doc}: {keys.join(', ')}</Link>
              ))}
            </div>
          )}
          <ErrorBox error={!missing ? dryError : null} />

          {size > LARGE_RUN_CELLS && (
            <label className="alert warn">
              <input type="checkbox" checked={largeConfirmed} onChange={event => setLargeConfirmed(event.target.checked)} />
              I confirm this large run of {size} cells and its estimated cost.
            </label>
          )}

          <button className="primary wide" disabled={!ready || actions.launch.isPending} onClick={() => void launch()}>
            {actions.launch.isPending ? 'Launching…' : 'Launch run'}
          </button>
          <p className="muted" style={{ marginTop: '0.7rem', marginBottom: 0 }}>
            {spec.document_ids.length} docs × {spec.model_ids.length} models × {spec.selected_tasks.length} agents
          </p>
        </Card>
      </aside>
    </div>
  )
}

function PipelineStep({
  spec,
  pack,
  tasks,
  prompts,
  update,
  setPack,
  selectTasks,
}: {
  spec: RunSpec
  pack?: PackMeta
  tasks: TaskMeta[]
  prompts?: Prompt[]
  update: <K extends keyof RunSpec>(key: K, value: RunSpec[K]) => void
  setPack: (name: PackName) => void
  selectTasks: (selected: string[]) => void
}) {
  const setRuntime = (task: TaskMeta, patch: Partial<Runtime>) =>
    update('runtime_overrides', { ...spec.runtime_overrides, [task.name]: { ...spec.runtime_overrides[task.name], ...patch } })

  return (
    <>
      <div className="row between">
        <div className="segmented">
          <button className={spec.pack === 'OPD' ? 'active' : ''} onClick={() => setPack('OPD')}>OPD</button>
          <button className={spec.pack === 'IPD' ? 'active' : ''} onClick={() => setPack('IPD')}>IPD</button>
        </div>
        {spec.pack === 'IPD' && (
          <label style={{ margin: 0, minWidth: 160 }}>
            Variant
            <select value={spec.variant ?? ''} onChange={event => update('variant', event.target.value || null)}>
              <option value="">Default</option>
              {(pack?.variants ?? ['CL', 'RM', 'PP']).map(value => <option key={value}>{value}</option>)}
            </select>
          </label>
        )}
      </div>

      <div className="row" style={{ margin: '0.8rem 0' }}>
        <label>
          <input type="radio" checked={spec.upstream_mode === 'gold'} onChange={() => update('upstream_mode', 'gold')} />
          Feed unselected dependencies from gold
        </label>
        <label>
          <input
            type="radio"
            checked={spec.upstream_mode === 'model'}
            onChange={() => {
              update('upstream_mode', 'model')
              if (pack) selectTasks(includeDependencies(pack, spec.selected_tasks))
            }}
          />
          Run dependencies with model
        </label>
      </div>

      <DependencyGraph tasks={tasks} selected={spec.selected_tasks} upstreamMode={spec.upstream_mode} onChange={selectTasks} />

      {tasks.filter(task => spec.selected_tasks.includes(task.name)).map(task => {
        const baseline = prompts?.find(prompt => (prompt.task ?? prompt.task_name) === task.name)
        const runtime = { ...task.reference_runtime, ...spec.runtime_overrides[task.name] }
        return (
          <details className="task-config" key={task.name}>
            <summary>{task.name.replaceAll('_', ' ')} settings <small>source defaults visible below</small></summary>
            <PromptEditor
              baseline={baseline}
              value={spec.prompt_overrides[task.name]}
              onChange={value => {
                const overrides = { ...spec.prompt_overrides }
                if (value) overrides[task.name] = value
                else delete overrides[task.name]
                update('prompt_overrides', overrides)
              }}
            />
            <div className="form-grid runtime">
              <label>
                Task model override
                <input
                  placeholder="Selected model"
                  value={runtime.model_id ?? ''}
                  onChange={event => setRuntime(task, { model_id: event.target.value || null })}
                />
              </label>
              <label>
                Thinking budget
                <input
                  type="number"
                  value={runtime.thinking_budget ?? ''}
                  onChange={event => setRuntime(task, { thinking_budget: event.target.value ? Number(event.target.value) : null })}
                />
              </label>
              <label>
                Thinking level
                <select
                  value={runtime.thinking_level ?? ''}
                  onChange={event => setRuntime(task, { thinking_level: event.target.value || null })}
                >
                  <option value="">Provider default</option>
                  <option>minimal</option>
                  <option>low</option>
                  <option>medium</option>
                </select>
              </label>
              <label>
                Max output tokens
                <input
                  type="number"
                  value={runtime.max_output_tokens ?? ''}
                  onChange={event => setRuntime(task, { max_output_tokens: event.target.value ? Number(event.target.value) : null })}
                />
              </label>
              <label>
                Timeout seconds
                <input
                  type="number"
                  value={runtime.timeout_s ?? ''}
                  onChange={event => setRuntime(task, { timeout_s: event.target.value ? Number(event.target.value) : null })}
                />
              </label>
            </div>
          </details>
        )
      })}
    </>
  )
}
