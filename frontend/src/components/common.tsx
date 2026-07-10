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
  Array.isArray(caps) ? caps : Object.entries(caps ?? {}).filter(([, on]) => on === true).map(([name]) => name.replaceAll('_', ' '))

export function supportsDocuments(model: { capabilities?: string[] | Record<string, unknown> }) {
  const caps = model.capabilities
  if (!caps) return true // unknown capabilities: don't raise false alarms
  if (Array.isArray(caps)) return caps.some(cap => ['pdf', 'pdf_native', 'vision', 'image'].includes(cap))
  const modalities = Array.isArray(caps.modalities) ? caps.modalities as string[] : []
  return caps.pdf_native === true || caps.vision === true || modalities.includes('pdf') || modalities.includes('image')
}

/** Human-friendly date: "Today, 14:03" or "8 Jul, 09:41". */
export function formatBriefDate(dateStr: string) {
  const date = new Date(dateStr)
  const timeStr = date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false })
  if (date.toDateString() === new Date().toDateString()) return `Today, ${timeStr}`
  return `${date.getDate()} ${date.toLocaleDateString([], { month: 'short' })}, ${timeStr}`
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
