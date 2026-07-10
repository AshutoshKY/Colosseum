import type { LeaderboardRow } from '../types'
import { money, percent } from './common'

export function LeaderboardTable({rows}: {rows: LeaderboardRow[]}) { return <div className="table-scroll"><table><thead><tr><th>Model</th><th>Accuracy</th><th>Valid</th><th>Judge</th><th>Win rate</th><th>Cost/doc</th><th>Median latency</th><th>Composite</th></tr></thead><tbody>{rows.map(row => <tr key={row.model_id ?? row.model}><th>{row.model_id ?? row.model}</th><td>{percent(row.accuracy)}</td><td>{percent(row.valid_percent ?? row.valid_rate)}</td><td>{row.judge_score?.toFixed(2) ?? '—'}</td><td>{percent(row.win_rate)}</td><td>{money(row.cost_per_doc ?? row.cost_usd)}</td><td>{Math.round(row.median_latency_ms ?? row.latency_ms ?? 0).toLocaleString()} ms</td><td><strong>{row.composite?.toFixed(2) ?? '—'}</strong></td></tr>)}</tbody></table></div> }

export function AccuracyCostChart({rows}: {rows: LeaderboardRow[]}) {
  const maxCost = Math.max(...rows.map(row => row.cost_per_doc ?? row.cost_usd ?? 0), .001)
  return <div className="scatter" role="img" aria-label="Accuracy versus cost chart">{rows.map(row => <span key={row.model_id ?? row.model} title={`${row.model_id ?? row.model}: ${percent(row.accuracy)}, ${money(row.cost_per_doc ?? row.cost_usd)}`} style={{left: `${((row.cost_per_doc ?? row.cost_usd ?? 0) / maxCost) * 88 + 5}%`, bottom: `${((row.accuracy ?? 0) <= 1 ? row.accuracy ?? 0 : (row.accuracy ?? 0) / 100) * 82 + 8}%`}}><i/>{row.model_id ?? row.model}</span>)}</div>
}
