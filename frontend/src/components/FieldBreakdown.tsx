import type { FieldRow } from '../types'
import { percent } from './common'

export function FieldBreakdown({rows}: {rows: FieldRow[]}) {
  const models = [...new Set(rows.flatMap(row => Object.keys(row.per_model)))]
  return <div className="table-scroll"><table><thead><tr><th>Field</th>{models.map(model => <th key={model}>{model}</th>)}</tr></thead><tbody>{rows.map(row => <tr key={row.path}><th><code>{row.path}</code></th>{models.map(model => { const value = row.per_model[model] ?? 0; const ratio = value <= 1 ? value : value / 100; return <td key={model} style={{background: `color-mix(in srgb, var(--success) ${ratio * 45}%, transparent)`}}>{percent(value)}</td>})}</tr>)}</tbody></table></div>
}
