import type { Cell, RunSpec } from '../types'
import { cx, formatDuration, money } from './common'

const glyph = {pending: '○', running: '◌', succeeded: '●', failed: '×', skipped: '–'}
export function cellKey(cell: Pick<Cell, 'document_id'|'document'|'document_name'|'model_id'|'model'|'task'>) { return `${cell.document_id ?? cell.document ?? cell.document_name}|${cell.model_id ?? cell.model}|${cell.task}` }
export function RunGrid({cells, spec, onCell}: {cells: Cell[]; spec?: RunSpec; onCell?: (cell: Cell) => void}) {
  if (!cells.length) return <div className="empty">Progress cells appear when the run starts.</div>
  const documents = [...new Map(cells.map(cell => [cell.document_id ?? cell.document ?? cell.document_name, {id: cell.document_id ?? cell.document, name: cell.document_name ?? cell.document ?? `Document ${cell.document_id}`}])).values()]
  const models = spec?.model_ids ?? [...new Set(cells.map(cell => cell.model_id ?? cell.model))].filter(Boolean) as string[]
  const tasks = spec?.selected_tasks ?? [...new Set(cells.map(cell => cell.task))]
  const byKey = new Map(cells.map(cell => [cellKey(cell), cell]))
  const cellsForDocument = (doc: { id?: number | string; name: string }) => cells.filter(cell =>
    cell.document_id === doc.id || cell.document === doc.id || cell.document_name === doc.name || cell.document === doc.name,
  )
  const resultForDocument = (doc: { id?: number | string; name: string }) => {
    const documentCells = cellsForDocument(doc)
    const claim = documentCells.find(cell => cell.task === 'claim_form' && cell.status === 'succeeded')
    if (claim) return claim
    const isComplete = documentCells.length > 0 && documentCells.every(cell => ['succeeded', 'failed', 'skipped'].includes(cell.status))
    return isComplete ? documentCells.find(cell => cell.status === 'succeeded') : undefined
  }
  return <div className="grid-scroll"><table className="run-grid"><thead><tr><th rowSpan={2}>Document</th>{models.map(model => <th key={model} colSpan={tasks.length}>{model}</th>)}</tr><tr>{models.flatMap(model => tasks.map(task => <th key={`${model}-${task}`}>{task}</th>))}</tr></thead><tbody>
    {documents.map(doc => {
      const result = resultForDocument(doc)
      const docId = typeof doc.id === 'number' ? doc.id : Number(doc.id)
      return <tr key={String(doc.id)}><th><div className="document-cell"><span>{doc.name}</span>{!Number.isNaN(docId) && docId > 0 && <a className="button ghost sm" href={`/api/documents/${docId}/file`} target="_blank" rel="noreferrer" title="Open PDF in new tab" style={{ padding: '0.1rem 0.4rem', fontSize: '0.75rem' }}>📄 PDF</a>}{result && <button type="button" className="document-result" onClick={() => onCell?.(result)}>View result</button>}</div></th>{models.flatMap(model => tasks.map(task => { const cell = byKey.get(`${doc.id}|${model}|${task}`) ?? byKey.get(`${doc.name}|${model}|${task}`); const status = cell?.status ?? 'pending'; return <td key={`${model}-${task}`}><button type="button" className={cx('cell-status', status)} onClick={() => cell && onCell?.(cell)} title={`${status}${cell?.latency_ms != null ? ` · ${formatDuration(cell.latency_ms)}` : ''}${cell?.completed_at ? ` · completed ${new Date(cell.completed_at).toLocaleTimeString()}` : ''}${cell?.cost_usd ? ` · ${money(cell.cost_usd)}` : ''}${cell?.error ? ` · ${cell.error}` : ''}`} aria-label={`${doc.name} · ${task} · ${status}${status === 'succeeded' ? ' · view result' : ''}`}><span>{glyph[status]}</span></button></td>}))}</tr>
    })}
  </tbody></table></div>
}
