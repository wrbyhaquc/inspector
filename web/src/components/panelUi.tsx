import { t } from '../i18n'
import { useEffect, useRef, useState, type ButtonHTMLAttributes, type ReactNode } from 'react'

// The operation panel's look, in one place: grey while all is well, colour only for what needs someone (注意 / 要處理),
// one accent for "this is the thing to press" (its value is the --accent token, so a pack can have its own).

export const DOT: Record<string, string> = { green: 'bg-emerald-500', blue: 'bg-accent animate-pulse', amber: 'bg-amber-500', grey: 'bg-stone-400', red: 'bg-rose-500' }

/** How one emulator is: a dot and a word; filled only when it needs attention. */
export function StatusBadge({ tone, children }: { tone: string; children: ReactNode }) {
  const loud = tone === 'red' ? 'bg-rose-50 text-rose-700 ring-1 ring-inset ring-rose-200' : tone === 'amber' ? 'bg-amber-50 text-amber-800 ring-1 ring-inset ring-amber-200' : 'text-stone-600'
  return <span className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium whitespace-nowrap ${loud}`}>
    <span className={`w-2 h-2 rounded-full ${DOT[tone] ?? DOT.grey}`} />{children}</span>
}

type Variant = 'primary' | 'secondary' | 'danger' | 'dangerSolid' | 'ghost'
const VARIANT: Record<Variant, string> = {
  primary: 'bg-accent text-white border border-accent hover:bg-accent/90',
  secondary: 'bg-white text-stone-800 border border-stone-300 hover:bg-stone-50',
  danger: 'bg-white text-rose-700 border border-rose-300 hover:bg-rose-50',
  dangerSolid: 'bg-rose-600 text-white border border-rose-600 hover:bg-rose-500',
  ghost: 'text-stone-600 border border-transparent hover:bg-stone-100',
}
export function Btn({ variant = 'secondary', size = 'md', className = '', children, ...rest }: {
  variant?: Variant; size?: 'sm' | 'md'; className?: string; children: ReactNode
} & Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'className' | 'children'>) {
  return <button type="button" {...rest}
    className={`inline-flex items-center justify-center gap-1.5 rounded-md font-medium whitespace-nowrap transition-colors disabled:opacity-40 disabled:cursor-not-allowed focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/40 ${size === 'sm' ? 'h-8 px-3 text-[0.8125rem]' : 'h-9 px-4 text-sm'} ${VARIANT[variant]} ${className}`}>
    {children}</button>
}

/** An on/off switch, with the word beside it for anyone unsure which way is on. */
export function Switch({ on, busy, onChange, label }: { on: boolean; busy?: boolean; onChange: (v: boolean) => void; label?: string }) {
  return (
    <button type="button" role="switch" aria-checked={on} aria-label={label} disabled={busy} onClick={() => onChange(!on)}
      className="shrink-0 inline-flex items-center gap-2 disabled:opacity-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/40 rounded-full">
      <span className={`relative w-10 h-6 rounded-full transition-colors ${on ? 'bg-accent' : 'bg-stone-300'}`}>
        <span className={`absolute top-0.5 left-0.5 w-5 h-5 rounded-full bg-white shadow transition-transform ${on ? 'translate-x-4' : ''}`} />
      </span>
      <span className={`text-sm w-4 ${on ? 'text-stone-900' : 'text-stone-500'}`}>{on ? t('開') : t('關')}</span>
    </button>
  )
}

/** Text boxes, time and number boxes and drop-downs all look the same. */
export const FIELD = 'h-9 rounded-md border border-stone-300 bg-white px-2.5 text-sm text-stone-900 focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent disabled:opacity-50'

/** A card on the panel: a title (and what it is for), anything beside the title, then its contents. */
export function Section({ title, help, extra, children, className = '', body = 'p-4' }: {
  title?: ReactNode; help?: ReactNode; extra?: ReactNode; children: ReactNode; className?: string; body?: string
}) {
  return (
    <section className={`bg-white rounded-lg border border-stone-200 shadow-sm ${className}`}>
      {(title || extra) && <div className="px-4 pt-3.5 pb-3 border-b border-stone-100 flex items-start gap-3">
        <div className="flex-1 min-w-0">
          {title && <h2 className="text-[0.9375rem] font-semibold text-stone-900 leading-snug">{title}</h2>}
          {help && <p className="text-[0.8125rem] text-stone-500 mt-0.5">{help}</p>}
        </div>
        {extra}
      </div>}
      <div className={body}>{children}</div>
    </section>
  )
}

/** A button that opens a short list of choices under it (closed by a click elsewhere or Esc). */
export function Menu({ label, title, children, align = 'right' }: { label: ReactNode; title?: string; children: (close: () => void) => ReactNode; align?: 'left' | 'right' }) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const out = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) setOpen(false) }
    const esc = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false) }
    document.addEventListener('mousedown', out); document.addEventListener('keydown', esc)
    return () => { document.removeEventListener('mousedown', out); document.removeEventListener('keydown', esc) }
  }, [open])
  return (
    <div ref={ref} className="relative">
      <Btn aria-haspopup="menu" aria-expanded={open} title={title} aria-label={title} onClick={() => setOpen(v => !v)}>{label}<span className="text-stone-400 text-xs">▾</span></Btn>
      {open && <div role="menu" className={`absolute z-30 mt-1 min-w-56 rounded-lg border border-stone-200 bg-white shadow-lg py-1 ${align === 'right' ? 'right-0' : 'left-0'}`}>
        {children(() => setOpen(false))}</div>}
    </div>
  )
}

export function MenuItem({ onClick, icon, children, help, danger = false, disabled }: {
  onClick: () => void; icon?: ReactNode; children: ReactNode; help?: ReactNode; danger?: boolean; disabled?: boolean
}) {
  return <button type="button" role="menuitem" onClick={onClick} disabled={disabled}
    className={`w-full text-left px-3 py-2 flex items-start gap-2.5 text-sm hover:bg-stone-50 disabled:opacity-40 ${danger ? 'text-rose-700' : 'text-stone-800'}`}>
    {icon && <span className="mt-0.5 shrink-0">{icon}</span>}
    <span className="flex-1 min-w-0"><span className="font-medium">{children}</span>{help && <span className="block text-xs text-stone-500 mt-0.5">{help}</span>}</span>
  </button>
}

export type Notice = { ok: boolean; text: string; undo?: () => void }

/** What just happened, in the corner for a moment (a failure stays until closed); a change can be taken back from it. */
export function Toast({ msg, onClose }: { msg: Notice | null; onClose: () => void }) {
  useEffect(() => {
    if (!msg?.ok) return
    const tx = setTimeout(onClose, msg.undo ? 8000 : 4000)
    return () => clearTimeout(tx)
  }, [msg, onClose])
  if (!msg) return null
  return (
    <div role="status" className="fixed z-40 bottom-4 right-4 left-4 sm:left-auto sm:max-w-md rounded-lg shadow-lg border bg-white px-4 py-3 flex items-start gap-3 text-sm
      border-stone-200" style={{ marginBottom: 'env(safe-area-inset-bottom, 0px)' }}>
      <span className={`mt-0.5 w-5 h-5 shrink-0 rounded-full flex items-center justify-center text-white text-xs ${msg.ok ? 'bg-emerald-600' : 'bg-rose-600'}`}>{msg.ok ? '✓' : '!'}</span>
      <span className={`flex-1 min-w-0 ${msg.ok ? 'text-stone-800' : 'text-rose-800'}`}>{msg.text}</span>
      {msg.undo && <button onClick={() => { msg.undo!(); onClose() }} className="shrink-0 font-medium text-accent hover:underline">{t('復原')}</button>}
      <button onClick={onClose} className="text-stone-400 hover:text-stone-700 leading-none" aria-label={t('關閉')}>✕</button>
    </div>
  )
}
