import { goldDependencies } from '../builder'
import type { TaskMeta } from '../types'
import { Badge, cx } from './common'

export function DependencyGraph({tasks, selected, upstreamMode, onChange}: {tasks: TaskMeta[]; selected: string[]; upstreamMode: 'gold'|'model'; onChange: (names: string[]) => void}) {
  const selectedSet = new Set(selected); const gold = goldDependencies(tasks, selected)
  const toggle = (name: string) => onChange(selectedSet.has(name) ? selected.filter(item => item !== name) : [...selected, name])
  return <div className="dag" aria-label="Agent dependency graph">
    {tasks.map((task, index) => <div className="dag-row" key={task.name}>
      {index > 0 && task.depends_on.length > 0 && <span className="dag-edge" aria-hidden>↓ {task.depends_on.join(', ')}</span>}
      <button type="button" className={cx('task-node', selectedSet.has(task.name) && 'selected', task.deterministic && 'deterministic')} aria-pressed={selectedSet.has(task.name)} onClick={() => toggle(task.name)}>
        <span>{task.name.replaceAll('_', ' ')}</span>
        <Badge tone={task.deterministic ? 'info' : 'neutral'}>{task.deterministic ? 'transform' : 'LLM'}</Badge>
      </button>
      {upstreamMode === 'gold' && gold[task.name] && <Badge tone="warn">fed from gold: {gold[task.name].join(', ')}</Badge>}
    </div>)}
  </div>
}
