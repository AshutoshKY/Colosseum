import type { DryRun, RunSpec } from '../types'
import { matrixSize } from '../builder'
import { Badge, money } from './common'

export function CostEstimate({spec, data, error}: {spec: RunSpec; data?: DryRun; error?: Error | null}) {
  const cost = typeof data?.cost_estimate === 'number' ? data.cost_estimate : data?.cost_estimate?.total_usd ?? data?.cost_estimate?.usd
  return <div className="summary-stats"><div><span>Matrix</span><strong>{matrixSize(spec)} cells</strong></div><div><span>Estimated cost</span><strong>{money(cost)}</strong></div><div><span>Pre-run check</span><Badge tone={error ? 'bad' : data ? 'good' : 'neutral'}>{error ? 'needs attention' : data ? 'passed' : 'waiting'}</Badge></div></div>
}
