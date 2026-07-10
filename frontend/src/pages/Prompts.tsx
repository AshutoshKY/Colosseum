import { useEffect, useState } from 'react'
import { useActions, usePacks, usePrompts, usePromptVersions } from '../api/hooks'
import { Badge, Card, Empty, ErrorBox, Spinner } from '../components/common'
import type { PackName } from '../types'

export default function Prompts() {
  const [pack, setPack] = useState<PackName>('OPD')
  const prompts = usePrompts(pack)
  const packs = usePacks()
  const [task, setTask] = useState('')
  const activeTask = task || packs.data?.find(item => item.name === pack)?.tasks[0]?.name
  const versions = usePromptVersions(pack, activeTask)
  const actions = useActions()

  const [system, setSystem] = useState('')
  const [instruction, setInstruction] = useState('')
  const [activate, setActivate] = useState(true)

  const active = prompts.data?.find(item => (item.task ?? item.task_name) === activeTask)

  useEffect(() => {
    setSystem(active?.system_prompt ?? '')
    setInstruction(active?.instruction_template ?? '')
  }, [active])

  const create = async () => {
    if (!activeTask) return
    await actions.createPrompt.mutateAsync({ pack, task: activeTask, body: { system_prompt: system, instruction_template: instruction, activate } })
    versions.refetch()
    prompts.refetch()
  }

  return (
    <>
      <header className="page-title">
        <div>
          <span className="eyebrow">Prompt store</span>
          <h1>Prompts</h1>
          <p>Inspect provenance and create versioned baselines. Run-only edits belong in the builder.</p>
        </div>
        <div className="segmented">
          <button className={pack === 'OPD' ? 'active' : ''} onClick={() => { setPack('OPD'); setTask('') }}>OPD</button>
          <button className={pack === 'IPD' ? 'active' : ''} onClick={() => { setPack('IPD'); setTask('') }}>IPD</button>
        </div>
      </header>

      <div className="prompt-layout">
        <Card>
          <h2>Tasks</h2>
          {prompts.isLoading ? (
            <Spinner />
          ) : prompts.data?.length ? (
            <nav className="side-nav">
              {prompts.data.map(item => {
                const name = item.task ?? item.task_name ?? ''
                return (
                  <button className={activeTask === name ? 'active' : ''} key={name} onClick={() => setTask(name)}>
                    <span>{name.replaceAll('_', ' ')}</span>
                    <Badge tone={item.differs_from_code ? 'warn' : 'good'}>
                      {item.active_version ? `v${item.active_version}` : 'fallback'}
                    </Badge>
                  </button>
                )
              })}
            </nav>
          ) : (
            <Empty>No prompts seeded for {pack}.</Empty>
          )}
        </Card>

        <div className="stack">
          <Card>
            <div className="card-header">
              <h2>{activeTask?.replaceAll('_', ' ') ?? 'Prompt'}</h2>
              {active?.active_version && <Badge tone="good">active v{active.active_version}</Badge>}
            </div>
            {active && (
              <p className="muted">
                {[active.source_repo, active.source_branch, active.source_path].filter(Boolean).join(' · ') || 'No provenance recorded'}
              </p>
            )}
            <label>
              System prompt
              <textarea value={system} onChange={event => setSystem(event.target.value)} />
            </label>
            <label>
              Instruction template
              <textarea value={instruction} onChange={event => setInstruction(event.target.value)} />
            </label>
            <div className="row between">
              <label>
                <input type="checkbox" checked={activate} onChange={event => setActivate(event.target.checked)} />
                Activate this version
              </label>
              <button className="primary" disabled={!activeTask || actions.createPrompt.isPending} onClick={() => void create()}>
                {actions.createPrompt.isPending ? 'Creating…' : 'Create version'}
              </button>
            </div>
            <ErrorBox error={actions.createPrompt.error} />
          </Card>

          <Card>
            <h2>Version history</h2>
            {versions.isLoading ? (
              <Spinner />
            ) : versions.data?.length ? (
              <div className="timeline">
                {versions.data.map((version, index) => (
                  <details key={version.version ?? index} open={index === 0}>
                    <summary>
                      <Badge tone={version.active ? 'good' : 'neutral'}>
                        v{version.version ?? '—'}{version.active ? ' active' : ''}
                      </Badge>{' '}
                      {version.created_at ? new Date(version.created_at).toLocaleString() : ''}
                    </summary>
                    <p className="muted">{[version.source_repo, version.source_branch, version.source_path].filter(Boolean).join(' · ')}</p>
                    <h4>System</h4>
                    <pre>{version.system_prompt}</pre>
                    <h4>Instruction</h4>
                    <pre>{version.instruction_template}</pre>
                  </details>
                ))}
              </div>
            ) : (
              <Empty>No versions.</Empty>
            )}
            <ErrorBox error={versions.error} />
          </Card>
        </div>
      </div>
    </>
  )
}
