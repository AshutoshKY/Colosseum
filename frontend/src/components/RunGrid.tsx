import type { Cell, RunSpec } from '../types'
import { cx, money } from './common'

const glyph = {pending: '○', running: '◌', succeeded: '●', failed: '×', skipped: '–'}
export function cellKey(cell: Pick<Cell, 'document_id'|'document'|'document_name'|'model_id'|'model'|'task'>) { return `${cell.document_id ?? cell.document ?? cell.document_name}|${cell.model_id ?? cell.model}|${cell.task}` }
export function RunGrid({cells, spec, onCell}: {cells: Cell[]; spec?: RunSpec; onCell?: (cell: Cell) => void}) {
  if (!cells.length) return <div className="empty">Progress cells appear when the run starts.</div>
  const documents = [...new Map(cells.map(cell => [cell.document_id ?? cell.document ?? cell.document_name, {id: cell.document_id ?? cell.document, name: cell.document_name ?? cell.document ?? `Document ${cell.document_id}`}])).values()]
  const models = spec?.model_ids ?? [...new Set(cells.map(cell => cell.model_id ?? cell.model))].filter(Boolean) as string[]
  const tasks = spec?.selected_tasks ?? [...new Set(cells.map(cell => cell.task))]
  const byKey = new Map(cells.map(cell => [cellKey(cell), cell]))
  return <div className="grid-scroll"><table className="run-grid"><thead><tr><th rowSpan={2}>Document</th>{models.map(model => <th key={model} colSpan={tasks.length}>{model}</th>)}</tr><tr>{models.flatMap(model => tasks.map(task => <th key={`${model}-${task}`}>{task}</th>))}</tr></thead><tbody>
    {documents.map(doc => <tr key={String(doc.id)}><th>{doc.name}</th>{models.flatMap(model => tasks.map(task => { const cell = byKey.get(`${doc.id}|${model}|${task}`) ?? byKey.get(`${doc.name}|${model}|${task}`); const status = cell?.status ?? 'pending'; return <td key={`${model}-${task}`}><button type="button" className={cx('cell-status', status)} onClick={() => cell && onCell?.(cell)} title={`${status}${cell?.latency_ms ? ` · ${cell.latency_ms}ms` : ''}${cell?.cost_usd ? ` · ${money(cell.cost_usd)}` : ''}${cell?.error ? ` · ${cell.error}` : ''}`}><span>{glyph[status]}</span></button></td>}))}</tr>)}
  </tbody></table></div>
}
