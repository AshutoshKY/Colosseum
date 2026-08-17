import { useState, type PropsWithChildren, type ReactNode } from 'react'

export const cx = (...values: Array<string | false | null | undefined>) => values.filter(Boolean).join(' ')

export function Card({ children, className }: PropsWithChildren<{ className?: string }>) {
  return <section className={cx('card', className)}>{children}</section>
}

export function Badge({ children, tone = 'neutral' }: PropsWithChildren<{ tone?: 'neutral' | 'good' | 'bad' | 'warn' | 'info' }>) {
  return <span className={`badge ${tone}`}>{children}</span>
}

export function Empty({ children }: PropsWithChildren) {
  return <div className="empty">{children}</div>
}

export function Spinner() {
  return <span className="spinner" aria-label="Loading" />
}

export function ErrorBox({ error }: { error: unknown }) {
  return error ? <div className="alert bad">{error instanceof Error ? error.message : String(error)}</div> : null
}

export function Modal({ title, children, onClose }: { title: string; children: ReactNode; onClose: () => void }) {
  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={onClose}>
      <div className="modal" role="dialog" aria-modal="true" aria-label={title} onMouseDown={event => event.stopPropagation()}>
        <header>
          <h2>{title}</h2>
          <button className="ghost" onClick={onClose} aria-label="Close">×</button>
        </header>
        {children}
      </div>
    </div>
  )
}

/** Kebab/dropdown menu. Items close the menu automatically when clicked. Force cache reload. */
export function Menu({ label = '⋮', items }: { label?: ReactNode; items: Array<{ label: ReactNode; onClick?: () => void; href?: string; danger?: boolean; download?: boolean } | false | null | undefined> }) {
  const [open, setOpen] = useState(false)
  const shown = items.filter(Boolean) as Array<{ label: ReactNode; onClick?: () => void; href?: string; danger?: boolean; download?: boolean }>
  return (
    <div className="menu-anchor">
      <button className="ghost small" aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen(!open)} style={{ fontSize: '1.1rem', fontWeight: 700 }}>
        {label}
      </button>
      {open && (
        <>
          <div className="menu-overlay" onClick={() => setOpen(false)} />
          <div className="menu" role="menu">
            {shown.map((item, index) =>
              item.href ? (
                <a key={index} role="menuitem" className={cx('button', 'menu-item', item.danger && 'danger')} href={item.href} download={item.download} onClick={() => setOpen(false)}>
                  {item.label}
                </a>
              ) : (
                <button key={index} role="menuitem" className={cx('menu-item', item.danger && 'danger')} onClick={() => { setOpen(false); item.onClick?.() }}>
                  {item.label}
                </button>
              ),
            )}
          </div>
        </>
      )}
    </div>
  )
}

export const money = (value?: number | null) => `$${Number(value ?? 0).toFixed(4)}`
export const percent = (value?: number | null) => `${((value ?? 0) <= 1 ? (value ?? 0) * 100 : value ?? 0).toFixed(1)}%`
export const modelId = (model: { id?: string; model_id?: string }) => model.id ?? model.model_id ?? ''

export const capabilityList = (caps?: string[] | Record<string, unknown>) =>
  Array.isArray(caps)
    ? caps
    : Object.entries(caps ?? {})
        .filter(([key, on]) => on === true && !['modalities', 'context_window'].includes(key))
        .map(([name]) => name.replaceAll('_', ' '))

export function supportsDocuments(model: { capabilities?: string[] | Record<string, unknown> }) {
  const caps = model.capabilities
  if (!caps) return true // unknown capabilities: don't raise false alarms
  if (Array.isArray(caps)) return caps.some(cap => ['pdf', 'pdf_native', 'vision', 'image'].includes(cap))
  const modalities = Array.isArray(caps.modalities) ? caps.modalities as string[] : []
  return caps.pdf_native === true || caps.vision === true || modalities.includes('pdf') || modalities.includes('image')
}

export function getContextWindow(model: { context_window?: number | null; capabilities?: string[] | Record<string, unknown> }): number | null {
  if (model.context_window) return model.context_window
  if (model.capabilities && !Array.isArray(model.capabilities)) {
    const ctx = model.capabilities.context_window
    if (typeof ctx === 'number') return ctx
  }
  return null
}

export function formatContextWindow(tokens?: number | null): string | null {
  if (!tokens || tokens <= 0) return null
  if (tokens >= 1_000_000) {
    const m = tokens / 1_000_000
    return `${m % 1 === 0 ? m.toFixed(0) : m.toFixed(1)}M ctx`
  }
  if (tokens >= 1_000) {
    return `${Math.round(tokens / 1_000)}k ctx`
  }
  return `${tokens} ctx`
}

export function formatReleaseDate(dateStr?: string | null): string | null {
  if (!dateStr) return null
  try {
    const parts = dateStr.split('-')
    if (parts.length === 3) {
      const date = new Date(Number(parts[0]), Number(parts[1]) - 1, Number(parts[2]))
      if (!isNaN(date.getTime())) {
        return date.toLocaleDateString('en-US', { month: 'short', year: 'numeric' })
      }
    }
    return dateStr
  } catch {
    return dateStr
  }
}

export function formatPriceSummary(pricing?: { input?: number | null; output?: number | null; input_per_million?: number | null; output_per_million?: number | null }): string {
  if (!pricing) return '$0.00/M'
  const inVal = Number(pricing.input_per_million ?? pricing.input ?? 0)
  const outVal = Number(pricing.output_per_million ?? pricing.output ?? 0)
  if (inVal === 0 && outVal === 0) return 'Free'
  if (outVal > 0) {
    return `$${inVal >= 1 ? inVal.toFixed(2) : inVal.toFixed(4)} in · $${outVal >= 1 ? outVal.toFixed(2) : outVal.toFixed(4)} out / 1M`
  }
  return `$${inVal >= 1 ? inVal.toFixed(2) : inVal.toFixed(4)}/M in`
}

export interface ModelSpecs {
  hasPdf: boolean
  hasVision: boolean
  isTextOnly: boolean
  context: string | null
  releaseDate: string | null
  price: string
}

export function getModelSpecs(model: {
  capabilities?: string[] | Record<string, unknown>
  context_window?: number | null
  release_date?: string | null
  pricing?: {
    input?: number | null
    output?: number | null
    input_per_million?: number | null
    output_per_million?: number | null
  }
}): ModelSpecs {
  const caps = model.capabilities
  let hasPdf = false
  let hasVision = false

  if (Array.isArray(caps)) {
    hasPdf = caps.some(c => ['pdf', 'pdf_native', 'pdf native'].includes(c.toLowerCase()))
    hasVision = caps.some(c => ['vision', 'image'].includes(c.toLowerCase()))
  } else if (caps && typeof caps === 'object') {
    const modalities = Array.isArray(caps.modalities) ? (caps.modalities as string[]) : []
    hasPdf = Boolean(caps.pdf_native || caps.pdf || modalities.includes('pdf'))
    hasVision = Boolean(caps.vision || modalities.includes('image') || modalities.includes('vision'))
  }

  const isTextOnly = !hasPdf && !hasVision && !supportsDocuments(model)
  const ctx = getContextWindow(model)
  const context = formatContextWindow(ctx)
  const releaseDate = formatReleaseDate(model.release_date)
  const price = formatPriceSummary(model.pricing)

  return { hasPdf, hasVision, isTextOnly, context, releaseDate, price }
}

/** Human-friendly date: "Today, 14:03" or "8 Jul, 09:41". */
export function formatBriefDate(dateStr: string) {
  const date = new Date(dateStr)
  const timeStr = date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false })
  if (date.toDateString() === new Date().toDateString()) return `Today, ${timeStr}`
  return `${date.getDate()} ${date.toLocaleDateString([], { month: 'short' })}, ${timeStr}`
}

export function formatDuration(milliseconds?: number | null) {
  if (milliseconds == null) return '—'
  if (milliseconds < 1000) return `${milliseconds} ms`
  const seconds = milliseconds / 1000
  if (seconds < 60) return `${seconds.toFixed(seconds < 10 ? 1 : 0)} s`
  const minutes = Math.floor(seconds / 60)
  return `${minutes}m ${Math.round(seconds % 60)}s`
}

/** Stable hue class for model / agent / pack chips. */
export function badgeHue(value: string, kind: 'pack' | 'model' | 'agent') {
  const lower = value.toLowerCase()
  if (kind === 'pack') return lower === 'opd' ? 'hue-violet' : 'hue-amber'
  if (kind === 'model') {
    if (lower.includes('gemini')) return 'hue-blue'
    if (lower.includes('qwen')) return 'hue-teal'
    if (lower.includes('gpt') || lower.includes('openai')) return 'hue-violet'
    if (lower.includes('claude') || lower.includes('anthropic')) return 'hue-red'
    return 'hue-blue'
  }
  if (lower.includes('segregation')) return 'hue-rose'
  if (lower.includes('bills') || lower.includes('categorisation')) return 'hue-teal'
  if (lower.includes('audit')) return 'hue-red'
  if (lower.includes('policy') || lower.includes('nme') || lower.includes('plan')) return 'hue-amber'
  return 'hue-blue'
}
