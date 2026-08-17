import { useEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useUiMode } from '../App'
import { includeDependencies, matrixSize, resizeBuilderColumns } from '../builder'
import { ApiError } from '../api/client'
import { useActions, useCatalog, useDocuments, usePacks, usePrompts } from '../api/hooks'
import { useRunBuilder } from '../context/RunBuilderContext'
import type { DryRun, PackMeta, PackName, Prompt, Runtime, RunSpec, TaskMeta } from '../types'
import { Badge, Card, ErrorBox, Spinner } from '../components/common'
import { UploadZone } from '../components/UploadZone'
import { DocumentPicker } from '../components/DocumentPicker'
import { DependencyGraph } from '../components/DependencyGraph'
import { PromptEditor } from '../components/PromptEditor'
import { ModelPicker, textOnlyModels } from '../components/ModelPicker'
import { CostEstimate } from '../components/CostEstimate'

const LARGE_RUN_CELLS = 100

export default function RunBuilder() {
  const { spec, setSpec } = useRunBuilder()
  const { mode } = useUiMode()
  const navigate = useNavigate()
  const documents = useDocuments()
  const packs = usePacks()
  const catalog = useCatalog()
  const prompts = usePrompts(spec.pack)
  const actions = useActions()

  const [dry, setDry] = useState<DryRun>()
  const [dryError, setDryError] = useState<Error>()
  const [largeConfirmed, setLargeConfirmed] = useState(false)
  const [paneWidths, setPaneWidths] = useState([0.82, 0.9, 1.18, 0.95])
  const [resizeStart, setResizeStart] = useState<{ divider: number; x: number; columns: number[] }>()
  const dryVersion = useRef(0)
  const layoutRef = useRef<HTMLDivElement>(null)

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

  useEffect(() => {
    if (!resizeStart) return
    const resize = (event: PointerEvent) => setPaneWidths(resizeBuilderColumns(resizeStart.columns, resizeStart.divider, event.clientX - resizeStart.x, layoutRef.current?.clientWidth ?? 0))
    const stop = () => setResizeStart(undefined)
    window.addEventListener('pointermove', resize)
    window.addEventListener('pointerup', stop, { once: true })
    return () => {
      window.removeEventListener('pointermove', resize)
      window.removeEventListener('pointerup', stop)
    }
  }, [resizeStart])

  const missing = useMemo(() => {
    const body = dryError instanceof ApiError
      ? dryError.body as { detail?: { missing_gold?: Record<string, string[]> }; missing_gold?: Record<string, string[]> }
      : undefined
    return body?.missing_gold ?? body?.detail?.missing_gold
  }, [dryError])

  const blockers = [
    !spec.document_ids.length && 'Select at least one claim.',
    !spec.selected_tasks.length && 'Select at least one task.',
    !spec.model_ids.length && 'Select at least one model.',
    spec.document_ids.length > 0 && spec.selected_tasks.length > 0 && spec.model_ids.length > 0 && !dry && !dryError && 'Validating the run…',
    dryError && (missing ? 'Resolve the missing ground truth below.' : 'Resolve the pre-run validation error.'),
    size > LARGE_RUN_CELLS && !largeConfirmed && `Confirm this large run of ${size} cells.`,
  ].filter(Boolean) as string[]

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

  if (mode === 'v1') {
    return (
      <div className="legacy-builder-layout">
        <main className="legacy-builder-flow">
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
            <PipelineStep spec={spec} pack={pack} tasks={tasks} prompts={prompts.data} update={update} setPack={setPack} selectTasks={selectTasks} />
          </Card>

          <Card>
            <h2><span className="step">3</span>Models</h2>
            {catalog.isLoading ? <Spinner /> : (
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
                <strong>No document input</strong>
                <p>{textOnly.map(model => model.name ?? model.id).join(', ')} cannot read PDFs or images.</p>
              </div>
            )}
          </Card>
        </main>

        <aside className="legacy-run-summary">
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
                {Object.entries(missing).map(([doc, keys]) => <Link key={doc} to={`/datasets?document=${doc}`}>Document {doc}: {keys.join(', ')}</Link>)}
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

  return (
    <div className="builder-page">
      <header className="builder-header">
        <div>
          <span className="eyebrow">New benchmark</span>
          <h1>Build a run</h1>
          <p>Choose claims, tasks, and models. Colosseum validates the full matrix before launch.</p>
        </div>
        <Link className="button ghost" to="/settings">Run settings</Link>
      </header>

      <div
        ref={layoutRef}
        className={`builder-layout ${resizeStart ? 'resizing' : ''}`}
        style={{ gridTemplateColumns: `${paneWidths[0]}fr 10px ${paneWidths[1]}fr 10px ${paneWidths[2]}fr 10px ${paneWidths[3]}fr` }}
      >
        <Card className="builder-pane claims-pane">
          <div className="builder-pane-header">
            <h2><span className="step">1</span>Claims</h2>
            <span className="count-pill">{spec.document_ids.length} selected</span>
          </div>
          <details className="builder-upload">
            <summary>Upload claims</summary>
            <div className="builder-upload-content">
              <UploadZone busy={actions.upload.isPending} onUpload={files => actions.upload.mutateAsync(files)} />
              <ErrorBox error={actions.upload.error} />
            </div>
          </details>
          <DocumentPicker
            documents={documents.data ?? []}
            selected={spec.document_ids}
            onChange={ids => update('document_ids', ids)}
            loading={documents.isLoading}
          />
        </Card>

        <PaneResizer
          divider={0}
          onResizeStart={event => setResizeStart({ divider: 0, x: event.clientX, columns: paneWidths })}
          onResizeBy={delta => setPaneWidths(current => resizeBuilderColumns(current, 0, delta, layoutRef.current?.clientWidth ?? 0))}
        />

        <Card className="builder-pane tasks-pane">
          <div className="builder-pane-header">
            <h2><span className="step">2</span>Tasks</h2>
            <span className="count-pill">{spec.selected_tasks.length} selected</span>
          </div>
          <div className="builder-pane-scroll">
            <PipelineStep
              spec={spec}
              pack={pack}
              tasks={tasks}
              prompts={prompts.data}
              update={update}
              setPack={setPack}
              selectTasks={selectTasks}
            />
          </div>
        </Card>

        <PaneResizer
          divider={1}
          onResizeStart={event => setResizeStart({ divider: 1, x: event.clientX, columns: paneWidths })}
          onResizeBy={delta => setPaneWidths(current => resizeBuilderColumns(current, 1, delta, layoutRef.current?.clientWidth ?? 0))}
        />

        <Card className="builder-pane models-pane">
          <div className="builder-pane-header">
            <h2><span className="step">3</span>Models</h2>
            <span className="count-pill">{spec.model_ids.length} selected</span>
          </div>
          <div className="builder-pane-scroll">
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
                <strong>No document input</strong>
                <p>
                  {textOnly.map(model => model.name ?? model.id).join(', ')}{' '}
                  {textOnly.length === 1 ? 'is a text-only model' : 'are text-only models'} and cannot read PDFs or images.
                </p>
              </div>
            )}
          </div>
        </Card>

        <PaneResizer
          divider={2}
          onResizeStart={event => setResizeStart({ divider: 2, x: event.clientX, columns: paneWidths })}
          onResizeBy={delta => setPaneWidths(current => resizeBuilderColumns(current, 2, delta, layoutRef.current?.clientWidth ?? 0))}
        />

        <aside className="run-summary">
          <Card className="builder-pane review-pane">
            <div className="builder-pane-header">
              <h2><span className="step">4</span>Review</h2>
            </div>
            <label>
              Run name
              <input
                value={spec.name}
                onChange={event => {
                  isNameEdited.current = event.target.value !== ''
                  update('name', event.target.value)
                }}
              />
            </label>

            <CostEstimate spec={spec} data={dry} error={dryError} />

            <div className="summary-selection">
              <div><span>Claims</span><strong>{spec.document_ids.length}</strong></div>
              <div><span>Tasks</span><strong>{spec.selected_tasks.length}</strong></div>
              {spec.selected_tasks.length > 0 && (
                <div className="summary-tags">
                  {spec.selected_tasks.map(task => <Badge key={task}>{task.replaceAll('_', ' ')}</Badge>)}
                </div>
              )}
            </div>

            <div className="summary-settings">
              <div><span>Compression</span><strong>{spec.compression.enabled ? `on · ${spec.compression.max_megapixels} MP` : 'off'}</strong></div>
              <div><span>Judge</span><strong>{spec.judge.enabled ? spec.judge.model_id : 'off'}</strong></div>
              <div><span>Concurrency</span><strong>{spec.concurrency.global} global</strong></div>
              <div><Link to="/settings">Edit run settings →</Link></div>
            </div>

            {spec.model_ids.length > 0 && (
              <div className="summary-models-block">
                <div className="row between" style={{ marginBottom: '0.35rem' }}>
                  <span className="eyebrow" style={{ margin: 0, fontSize: '0.7rem' }}>Models ({spec.model_ids.length})</span>
                  <button
                    type="button"
                    className="ghost small danger"
                    style={{ padding: '0.1rem 0.3rem', fontSize: '0.7rem' }}
                    onClick={() => update('model_ids', [])}
                  >
                    Clear
                  </button>
                </div>
                <div className="badges compact summary-tags">
                  {spec.model_ids.map(id => (
                    <span key={id} className="badge summary-model-pill" title={id}>
                      {id.split('/').pop()}
                      <button
                        type="button"
                        className="pill-remove-x"
                        onClick={() => update('model_ids', spec.model_ids.filter(m => m !== id))}
                        title={`Remove ${id}`}
                        aria-label={`Remove ${id}`}
                      >
                        ×
                      </button>
                    </span>
                  ))}
                </div>
              </div>
            )}

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

            {blockers.length > 0 ? (
              <div className="launch-blockers">
                <strong>Before launch</strong>
                <ul>{blockers.map(reason => <li key={reason}>{reason}</li>)}</ul>
              </div>
            ) : (
              <div className="launch-ready">Ready to launch</div>
            )}

            <button className="primary wide" disabled={!ready || actions.launch.isPending} onClick={() => void launch()}>
              {actions.launch.isPending ? 'Launching…' : 'Launch benchmark'}
            </button>
            <p className="muted" style={{ marginTop: '0.7rem', marginBottom: 0 }}>
              {spec.document_ids.length} claims × {spec.model_ids.length} models × {spec.selected_tasks.length} tasks
            </p>
          </Card>
        </aside>
      </div>
    </div>
  )
}

function PaneResizer({ divider, onResizeStart, onResizeBy }: { divider: number; onResizeStart: (event: ReactPointerEvent<HTMLDivElement>) => void; onResizeBy: (delta: number) => void }) {
  return (
    <div
      className="pane-resizer"
      role="separator"
      aria-label={`Resize builder panes ${divider + 1} and ${divider + 2}`}
      aria-orientation="vertical"
      title="Drag or use arrow keys to resize"
      tabIndex={0}
      onPointerDown={onResizeStart}
      onKeyDown={event => {
        if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
          event.preventDefault()
          onResizeBy(event.key === 'ArrowLeft' ? -40 : 40)
        }
      }}
    />
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

      <label className="dependency-mode">
        Dependency inputs
        <select
          value={spec.upstream_mode}
          onChange={event => {
            const mode = event.target.value as RunSpec['upstream_mode']
            update('upstream_mode', mode)
            if (mode === 'model' && pack) selectTasks(includeDependencies(pack, spec.selected_tasks))
          }}
        >
          <option value="gold">Feed unselected dependencies from gold</option>
          <option value="model">Run dependencies with the model</option>
        </select>
      </label>

      <DependencyGraph tasks={tasks} selected={spec.selected_tasks} upstreamMode={spec.upstream_mode} onChange={selectTasks} />

      {tasks.filter(task => spec.selected_tasks.includes(task.name)).map(task => {
        const baseline = prompts?.find(prompt => (prompt.task ?? prompt.task_name) === task.name)
        const runtime = { ...task.reference_runtime, ...spec.runtime_overrides[task.name] }
        const promptVersionLabel = spec.prompt_overrides[task.name] ? 'override' : baseline?.active_version ? `v${baseline.active_version}` : 'code baseline'
        return (
          <details className="task-config" key={task.name}>
            <summary>
              <div className="row center gap-xs" style={{ display: 'inline-flex' }}>
                <span>{task.name.replaceAll('_', ' ')} settings</span>
                <Badge tone={spec.prompt_overrides[task.name] ? 'warn' : baseline?.active_version ? 'good' : 'neutral'}>
                  {promptVersionLabel}
                </Badge>
              </div>
            </summary>
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
