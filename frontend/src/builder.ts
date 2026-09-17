import type { PackMeta, RunSpec, TaskMeta } from './types'

export const DEFAULT_PER_PROVIDER_CONCURRENCY: Record<string, number> = {
  vertex_ai: 4,
  vertex_partner: 4,
  openai_compatible: 8,
  openrouter: 8,
  bedrock: 4,
  xai: 2,
}

export const initialRunSpec = (): RunSpec => ({
  name: `benchmark-${new Date().toISOString().slice(0, 10)}`, pack: 'OPD', variant: null,
  selected_tasks: [], document_ids: [], model_ids: [], upstream_mode: 'gold', prompt_overrides: {}, runtime_overrides: {},
  concurrency: {global: 16, per_provider: { ...DEFAULT_PER_PROVIDER_CONCURRENCY }},
  judge: {enabled: true, model_id: 'gemini-3.1-pro', modes: ['gold_grade', 'head_to_head']},
  compression: {enabled: false, max_megapixels: 4, max_image_mb: null}, confirm_large: false,
})

export function goldDependencies(tasks: TaskMeta[], selected: string[]): Record<string, string[]> {
  const chosen = new Set(selected); const result: Record<string, string[]> = {}
  for (const task of tasks.filter(item => chosen.has(item.name))) {
    const upstream = task.depends_on.filter(dep => !chosen.has(dep))
    const required = [...(task.gold_context_keys ?? [])]
    if (upstream.length) required.push(...(task.gold_feed_keys.length ? task.gold_feed_keys : upstream))
    if (required.length) result[task.name] = [...new Set(required)]
  }
  return result
}

export function includeDependencies(pack: PackMeta, selected: string[]): string[] {
  const tasks = new Map(pack.tasks.map(task => [task.name, task])); const all = new Set(selected)
  const visit = (name: string) => { for (const dep of tasks.get(name)?.depends_on ?? []) if (!all.has(dep)) { all.add(dep); visit(dep) } }
  selected.forEach(visit)
  return (pack.order ?? pack.tasks.map(task => task.name)).filter(name => all.has(name))
}

export const matrixSize = (spec: RunSpec) => spec.document_ids.length * spec.model_ids.length * spec.selected_tasks.length

const MIN_BUILDER_COLUMN = [0.7, 0.75, 0.9, 0.8]

/** Keep adjacent builder panes usable while a divider is dragged. */
export function resizeBuilderColumns(columns: number[], divider: number, deltaX: number, containerWidth: number): number[] {
  if (!containerWidth || divider < 0 || divider >= columns.length - 1) return columns
  const total = columns[divider] + columns[divider + 1]
  const next = Math.min(total - MIN_BUILDER_COLUMN[divider + 1], Math.max(MIN_BUILDER_COLUMN[divider], columns[divider] + deltaX / containerWidth * columns.reduce((sum, value) => sum + value, 0)))
  return columns.map((value, index) => index === divider ? next : index === divider + 1 ? total - next : value)
}
