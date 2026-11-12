import { t } from '../i18n'
import { useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'

/** one choice of a TreePicker: filed under path (folders, outermost first; [] = at the top) */
export interface PickItem { key: string; path: string[]; label: string; hint?: string; img?: string }

/** "選單/設定" -> ["選單", "設定"] */
export const splitFolder = (f?: string | null) => (f ?? '').split('/').map(x => x.trim()).filter(Boolean)

/** the part of a name before "：" / ":" (the way names were sorted before folders): "選單:設定" -> "選單" */
export function labelPrefix(label: string) {
  const m = /^([^:：/]{1,12})[:：]\s*\S/.exec(label)
  return m ? m[1].trim() : null
}

/** a name inside its folder, without repeating the folder: "設定:音量" in 選單/設定 -> "音量" */
export function shortLabel(label: string, path: string[]) {
  const last = path[path.length - 1]
  if (!last) return label
  for (const sep of [':', '：']) if (label.startsWith(last + sep) && label.length > last.length + 1) return label.slice(last.length + 1).trim()
  return label
}

interface TNode { name: string; path: string[]; folders: TNode[]; items: PickItem[] }

function tree(items: PickItem[]): TNode {
  const root: TNode = { name: '', path: [], folders: [], items: [] }
  for (const it of items) {
    let n = root
    for (const seg of it.path) {
      let c = n.folders.find(f => f.name === seg)
      if (!c) { c = { name: seg, path: [...n.path, seg], folders: [], items: [] }; n.folders.push(c) }
      n = c
    }
    n.items.push(it)
  }
  return root
}

const count = (n: TNode): number => n.items.length + n.folders.reduce((a, f) => a + count(f), 0)

/** A choice out of many, filed in folders: a field that opens a searchable tree (instead of one long select).
 *  value = the chosen item's key ('' = none). */
export function TreePicker({ items, value, onChange, placeholder, className = '' }: {
  items: PickItem[]; value: string; onChange: (key: string) => void; placeholder?: string; className?: string
}) {
  const [open, setOpen] = useState(false)
  const [q, setQ] = useState('')
  const cur = items.find(i => i.key === value)
  const [shut, setShut] = useState<Set<string>>(new Set())         // folders closed by hand
  const [opened, setOpened] = useState<Set<string>>(new Set())     // folders opened by hand
  const btn = useRef<HTMLButtonElement>(null)
  const box = useRef<HTMLDivElement>(null)
  const [at, setAt] = useState<{ left: number; top: number; up: boolean }>({ left: 0, top: 0, up: false })
  const root = useMemo(() => tree(items), [items])
  const hits = useMemo(() => {
    const w = q.trim().toLowerCase().split(/\s+/).filter(Boolean)
    return w.length ? items.filter(i => { const s = `${i.path.join(' ')} ${i.label} ${i.hint ?? ''}`.toLowerCase(); return w.every(x => s.includes(x)) }) : null
  }, [q, items])

  const place = () => {
    const r = btn.current?.getBoundingClientRect()
    if (!r) return
    const up = r.bottom + 420 > window.innerHeight && r.top > 420
    setAt({ left: Math.max(8, Math.min(r.left, window.innerWidth - 368)), top: up ? r.top - 4 : r.bottom + 4, up })
  }
  useLayoutEffect(() => { if (open) place() }, [open])
  useEffect(() => {
    if (!open) return
    const down = (e: MouseEvent) => { if (!box.current?.contains(e.target as Node) && !btn.current?.contains(e.target as Node)) setOpen(false) }
    const key = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false) }
    window.addEventListener('mousedown', down)
    window.addEventListener('keydown', key)
    window.addEventListener('scroll', place, true)
    window.addEventListener('resize', place)
    return () => { window.removeEventListener('mousedown', down); window.removeEventListener('keydown', key); window.removeEventListener('scroll', place, true); window.removeEventListener('resize', place) }
  }, [open])

  const pick = (k: string) => { onChange(k); setOpen(false); setQ('') }
  const k = (p: string[]) => p.join('/')
  // a folder starts open when it holds the current choice or is the only thing there is
  const isOpen = (n: TNode) => {
    const id = k(n.path)
    if (shut.has(id)) return false
    if (opened.has(id)) return true
    return !!cur && k(cur.path.slice(0, n.path.length)) === id
  }
  const toggle = (n: TNode) => {
    const id = k(n.path), now = isOpen(n)
    setShut(s => { const x = new Set(s); if (now) x.add(id); else x.delete(id); return x })
    setOpened(s => { const x = new Set(s); if (now) x.delete(id); else x.add(id); return x })
  }
  const row = (i: PickItem, depth: number, crumbs?: boolean) => (
    <button key={i.key} onClick={() => pick(i.key)} style={{ paddingLeft: 8 + depth * 14 }}
      className={`w-full text-left flex items-center gap-2 pr-2 py-1 rounded text-sm hover:bg-sky-50 ${i.key === value ? 'bg-sky-100 font-medium' : ''}`}>
      {i.img ? <img src={i.img} alt="" className="h-5 max-w-[48px] rounded bg-stone-800 shrink-0" loading="lazy" /> : <span className="w-3 shrink-0" />}
      <span className="min-w-0 flex-1 truncate">
        {crumbs && i.path.length > 0 && <span className="text-stone-400">{i.path.join(' › ')} › </span>}
        {crumbs ? i.label : shortLabel(i.label, i.path)}
      </span>
      {i.hint && <span className="text-[11px] text-stone-400 shrink-0">{i.hint}</span>}
    </button>
  )
  const folder = (n: TNode, depth: number): ReactNode => {
    const o = isOpen(n)
    return (
      <div key={k(n.path)}>
        <button onClick={() => toggle(n)} style={{ paddingLeft: 8 + depth * 14 }}
          className="w-full text-left flex items-center gap-1.5 pr-2 py-1 rounded text-sm text-stone-700 hover:bg-stone-100">
          <span className="w-3 text-stone-400 text-[10px]">{o ? '▼' : '▶'}</span>
          <span className="flex-1 truncate font-medium">{n.name}</span>
          <span className="text-[11px] text-stone-400 num">{count(n)}</span>
        </button>
        {o && <>{n.folders.map(f => folder(f, depth + 1))}{n.items.map(i => row(i, depth + 1))}</>}
      </div>
    )
  }

  return (
    <>
      <button ref={btn} type="button" onClick={() => setOpen(o => !o)}
        className={`border border-stone-300 rounded-md px-2 py-1 text-sm bg-white text-left max-w-full min-w-[12rem] flex items-center gap-1.5 ${className}`}>
        <span className="min-w-0 flex-1 truncate">
          {cur ? <>{cur.path.length > 0 && <span className="text-stone-400">{cur.path.join(' › ')} › </span>}{shortLabel(cur.label, cur.path)}</>
            : <span className="text-stone-400">{placeholder ?? t('(請選擇)')}</span>}
        </span>
        <span className="text-stone-400 text-[10px]">▼</span>
      </button>
      {open && createPortal(
        <div ref={box} className="fixed z-50 w-[360px] max-w-[calc(100vw-16px)] bg-white border border-stone-300 rounded-lg shadow-lg flex flex-col"
          style={{ left: at.left, ...(at.up ? { bottom: window.innerHeight - at.top } : { top: at.top }) }}>
          <div className="p-2 border-b border-stone-100">
            <input autoFocus className="w-full border border-stone-300 rounded-md px-2 py-1 text-sm" placeholder={t('搜尋名稱或資料夾…')}
              value={q} onChange={e => setQ(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter' && hits?.length) pick(hits[0].key) }} />
          </div>
          <div className="max-h-[360px] overflow-auto p-1">
            {hits ? (hits.length ? hits.slice(0, 200).map(i => row(i, 0, true)) : <div className="px-2 py-3 text-sm text-stone-400">{t('找不到')}</div>)
              : <>{root.items.filter(i => i.key.startsWith('__p:')).map(i => row(i, 0))}
                {root.folders.map(f => folder(f, 0))}
                {root.items.filter(i => !i.key.startsWith('__p:')).map(i => row(i, 0))}</>}
          </div>
        </div>, document.body)}
    </>
  )
}
