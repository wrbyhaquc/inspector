import { t } from '../i18n'
import { useEffect, useRef, type ReactNode } from 'react'
import { createPortal } from 'react-dom'

export function Page({ title, desc, actions, intro, children }: { title: string; desc?: ReactNode; actions?: ReactNode; intro?: ReactNode; children: ReactNode }) {
  return (
    <div className="p-6 max-w-[1400px] mx-auto flex flex-col gap-5">
      <header className="flex items-end justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-xl font-semibold text-stone-900">{title}</h1>
          {desc && <p className="text-sm text-stone-500 mt-1 max-w-3xl">{desc}</p>}
        </div>
        {actions && <div className="flex items-center gap-2">{actions}</div>}
      </header>
      {intro}
      {children}
    </div>
  )
}

export function Card({ title, extra, children, className = '' }: { title?: ReactNode; extra?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`bg-white rounded-lg border border-stone-200 ${className}`}>
      {title && (
        <div className="px-4 py-3 border-b border-stone-100 flex items-center justify-between gap-3">
          <h2 className="text-sm font-semibold text-stone-700">{title}</h2>
          {extra}
        </div>
      )}
      <div className="p-4">{children}</div>
    </section>
  )
}

export function Stat({ label, value, sub }: { label: string; value: ReactNode; sub?: ReactNode }) {
  return (
    <div className="bg-white rounded-lg border border-stone-200 px-4 py-3">
      <div className="text-xs text-stone-500">{label}</div>
      <div className="text-2xl font-semibold text-stone-900 num mt-1">{value}</div>
      {sub && <div className="text-xs text-stone-500 mt-0.5">{sub}</div>}
    </div>
  )
}

type Tone = 'stone' | 'green' | 'red' | 'blue' | 'amber' | 'violet'
const TONES: Record<Tone, string> = {
  stone: 'bg-stone-100 text-stone-600',
  green: 'bg-emerald-50 text-emerald-700',
  red: 'bg-rose-50 text-rose-700',
  blue: 'bg-sky-50 text-sky-700',
  amber: 'bg-amber-50 text-amber-800',
  violet: 'bg-violet-50 text-violet-700',
}
export function Pill({ tone = 'stone', children, title }: { tone?: Tone; children: ReactNode; title?: string }) {
  return <span title={title} className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium whitespace-nowrap ${TONES[tone]}`}>{children}</span>
}

/** one state's value as a badge, in its answer's color (any state of the project) */
export function StatePill({ state, v }: { state: { name: string; type: string; classes?: { value: unknown; name: string; color?: string }[] }; v: unknown }) {
  if (state.type === 'ratio') return <Pill>{state.name} {typeof v === 'number' ? `${Math.round(v * 100)}%` : '?'}</Pill>
  const c = state.classes?.find(x => JSON.stringify(x.value) === JSON.stringify(v))
  return <Pill tone={(c?.color as Tone) ?? 'stone'}>{state.name} {c ? c.name : v == null ? '?' : String(v)}</Pill>
}

export function Button({ children, onClick, variant = 'default', disabled, type = 'button', title }: {
  children: ReactNode; onClick?: () => void; variant?: 'default' | 'primary' | 'danger' | 'ghost' | 'auto'; disabled?: boolean; type?: 'button' | 'submit'; title?: string
}) {
  const v = {
    default: 'bg-white border border-stone-300 text-stone-700 hover:bg-stone-50',
    primary: 'bg-stone-900 text-white hover:bg-stone-700',
    danger: 'bg-rose-600 text-white hover:bg-rose-500',
    ghost: 'text-stone-600 hover:bg-stone-100',
    auto: 'bg-sky-50 border border-dashed border-sky-500 text-sky-900 hover:bg-sky-100',     // a pre-filled answer nobody confirmed
  }[variant]
  return (
    <button type={type} onClick={onClick} disabled={disabled} title={title}
      className={`px-3 py-1.5 rounded-md text-sm font-medium transition-colors disabled:opacity-40 disabled:cursor-not-allowed focus:outline-none focus-visible:ring-2 focus-visible:ring-amber-400 ${v}`}>
      {children}
    </button>
  )
}

export function Meter({ value, max, color = 'bg-stone-700', label }: { value: number | null | undefined; max: number | null | undefined; color?: string; label?: string }) {
  const r = value != null && max ? Math.max(0, Math.min(1, value / max)) : null
  return (
    <div className="flex items-center gap-2 text-xs">
      {label && <span className="w-6 text-stone-500">{label}</span>}
      <div className="flex-1 h-2 rounded-full bg-stone-100 overflow-hidden">
        {r != null && <div className={`h-full ${color}`} style={{ width: `${r * 100}%` }} />}
      </div>
      <span className="num text-stone-600 w-24 text-right">{value != null ? `${value} / ${max}` : '—'}</span>
    </div>
  )
}

/** Horizontal share bar for label counts. */
export function Share({ parts }: { parts: { label: string; value: number; color: string }[] }) {
  const total = parts.reduce((a, p) => a + p.value, 0) || 1
  return (
    <div className="flex flex-col gap-2">
      <div className="flex h-3 rounded-full overflow-hidden bg-stone-100">
        {parts.map(p => p.value > 0 && <div key={p.label} className={p.color} style={{ width: `${(p.value / total) * 100}%` }} title={`${p.label} ${p.value}`} />)}
      </div>
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-stone-600">
        {parts.map(p => (
          <span key={p.label} className="flex items-center gap-1.5">
            <span className={`w-2.5 h-2.5 rounded-sm ${p.color}`} />{p.label}<span className="num text-stone-900 font-medium">{p.value}</span>
          </span>
        ))}
      </div>
    </div>
  )
}

export function LogView({ lines, height = 'h-64' }: { lines?: string[] | null; height?: string }) {
  const ref = useRef<HTMLPreElement>(null)
  useEffect(() => { if (ref.current) ref.current.scrollTop = ref.current.scrollHeight }, [lines])
  return (
    <pre ref={ref} className={`${height} overflow-auto bg-stone-950 text-stone-300 text-xs font-mono p-3 rounded-md whitespace-pre-wrap`}>
      {lines?.length ? lines.join('\n') : t('(沒有輸出)')}
    </pre>
  )
}

export function JobStatus({ status }: { status: string }) {
  const m: Record<string, [Tone, string]> = { running: ['green', t('執行中')], done: ['blue', t('完成')], failed: ['red', t('失敗')], stopped: ['stone', t('已停止')] }
  const [tone, text] = m[status] ?? ['stone', status]
  return <Pill tone={tone}>{text}</Pill>
}

export function ErrorText({ error }: { error: unknown }) {
  if (!error) return null
  return <div className="text-sm text-rose-700 bg-rose-50 border border-rose-200 rounded-md px-3 py-2">{String((error as Error).message ?? error)}</div>
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="text-sm text-stone-500 py-8 text-center">{children}</div>
}

/** A floating window for one thing's less common settings (or a short task): Esc / the backdrop / ✕ close it.
 *  footer: the window's own buttons (e.g. 儲存). wide: for editors with more room. */
export function Modal({ open, title, onClose, children, footer, wide = false }: {
  open: boolean; title: ReactNode; onClose: () => void; children: ReactNode; footer?: ReactNode; wide?: boolean
}) {
  useEffect(() => {
    if (!open) return
    const k = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', k)
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => { window.removeEventListener('keydown', k); document.body.style.overflow = prev }
  }, [open, onClose])
  if (!open) return null
  return createPortal(
    <div className="fixed inset-0 z-50 bg-black/40 flex items-start justify-center p-4 overflow-y-auto" onMouseDown={e => { if (e.target === e.currentTarget) onClose() }}>
      <div role="dialog" aria-modal="true" className={`bg-white rounded-xl shadow-xl w-full ${wide ? 'max-w-4xl' : 'max-w-xl'} my-8 flex flex-col max-h-[calc(100vh-4rem)]`}>
        <div className="flex items-center gap-3 px-4 py-3 border-b border-stone-200">
          <h2 className="font-semibold text-stone-900 flex-1 min-w-0">{title}</h2>
          <button onClick={onClose} className="text-stone-400 hover:text-stone-800 text-lg leading-none" aria-label={t('關閉')}>✕</button>
        </div>
        <div className="px-4 py-3 overflow-y-auto flex flex-col gap-3 text-sm">{children}</div>
        {footer && <div className="px-4 py-3 border-t border-stone-200 flex flex-wrap items-center justify-end gap-2">{footer}</div>}
      </div>
    </div>, document.body)
}

/** A side panel for a page's settings that are set once and rarely touched (the page stays visible beside it). */
export function Drawer({ open, title, onClose, children }: { open: boolean; title: ReactNode; onClose: () => void; children: ReactNode }) {
  useEffect(() => {
    if (!open) return
    const k = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', k)
    return () => window.removeEventListener('keydown', k)
  }, [open, onClose])
  if (!open) return null
  return createPortal(
    <div className="fixed inset-0 z-50 bg-black/30 flex justify-end" onMouseDown={e => { if (e.target === e.currentTarget) onClose() }}>
      <aside role="dialog" aria-modal="true" className="bg-stone-50 w-full max-w-2xl h-full shadow-xl flex flex-col">
        <div className="flex items-center gap-3 px-5 py-3 border-b border-stone-200 bg-white">
          <h2 className="font-semibold text-stone-900 flex-1">{title}</h2>
          <button onClick={onClose} className="text-stone-400 hover:text-stone-800 text-lg leading-none" aria-label={t('關閉')}>✕</button>
        </div>
        <div className="flex-1 overflow-y-auto p-5 flex flex-col gap-4">{children}</div>
      </aside>
    </div>, document.body)
}

/** The small "⚙ 設定" / "⋯ 更多" button that opens a Modal or Drawer. */
export function MoreButton({ onClick, children = t('⋯ 更多'), title }: { onClick: () => void; children?: ReactNode; title?: string }) {
  return <button onClick={onClick} title={title} className="text-xs px-2 py-1 rounded-md border border-stone-300 bg-white text-stone-700 hover:bg-stone-100 whitespace-nowrap">{children}</button>
}
