import { locale, t } from '../i18n'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState, type ReactNode } from 'react'
import ReactGridLayout, { useContainerWidth, verticalCompactor, type Layout } from 'react-grid-layout'
import 'react-grid-layout/css/styles.css'
import 'react-resizable/css/styles.css'
import { api, type PanelBlock, type PanelChatPreview, type PanelControl, type PanelDefinition, type PanelDraft, type PanelInfo, type PanelPlace, type PanelProblem, type PanelStart, type PanelThing, type PanelWidget, type SettingDecl } from '../api'
import { Button, Card, Empty, ErrorText, Modal } from '../components/ui'
import { Btn, FIELD, Switch, type Notice } from '../components/panelUi'
import { Icon } from '../components/Icon'
import { words } from '../lib/project'
import { sourceIds } from '../lib/sources'
import { SourcePick } from '../components/SourcePick'
import { autoWide } from '../lib/panelLayout'

// Editing the operation panel where it is: what to add (the design's own settings, schedules, situations ... as they
// are now, the watch widgets, whole templates) and the outline on the left, the panel itself in the middle (its real
// contents, arranged by dragging on the 12-column grid), what the picked block is on the right. Every change goes
// into a draft (server/panel_draft.py); the panel's users see it once it is published.
const input = 'border border-stone-300 rounded-md px-2 py-1 text-sm bg-white'
type Panel = PanelDefinition['panel']
type Ctl = PanelControl & { bind: { kind: string; [k: string]: unknown } }

const COLS = 12
const ROW = 150                     // a grid row's height while arranging (on the panel rows are as tall as what is in them)
const newId = (base: string, taken: string[]) => { let i = 1; while (taken.includes(`${base}${i}`)) i++; return `${base}${i}` }
const move = <T,>(xs: T[], i: number, d: number) => { const n = [...xs]; const [x] = n.splice(i, 1); n.splice(i + d, 0, x); return n }
const clone = <T,>(x: T): T => JSON.parse(JSON.stringify(x))
// the spec version is the server's to stamp
const key = (x: Panel) => JSON.stringify({ ...x, format: undefined })
const bottom = (bs: PanelBlock[]) => Math.max(0, ...bs.map(b => (b.place?.y ?? 0) + (b.place?.h ?? 1)))
const DROPPING = '__dropping-elem__'           // react-grid-layout's id for what is being dropped from outside
const setPlaces = (x: Panel, l: Layout) => {
  for (const it of l) {
    const b = x.blocks.find(o => o.id === it.i)
    if (b) b.place = { x: it.x, y: it.y, w: it.w, ...(it.h > 1 ? { h: it.h } : {}) }
  }
}
/** Is this thing of the design on the panel already (anywhere)? */
const placed = (th: PanelThing, x: Panel) => {
  const [script, situation] = th.id.split('/')
  const bound = (f: (b: Record<string, unknown>) => boolean) => x.controls.some(c => f((c.bind ?? {}) as Record<string, unknown>))
  switch (th.kind) {
    case 'setting': return bound(b => b.kind === 'setting' && b.setting === th.id)
    case 'schedule': return bound(b => b.schedule === th.id)
    case 'situation': return bound(b => b.kind === 'act_situation' && b.script === script && b.situation === situation)
    case 'sub': return bound(b => b.kind === 'act_sub' && b.sub === th.id)
    case 'variable': return x.blocks.some(b => b.widget?.kind === 'values' && ((b.widget.vars as string[] | undefined) ?? []).includes(th.id))
    case 'list': return x.blocks.some(b => b.widget?.kind === 'list' && b.widget.list === th.id)
  }
}
const typing = (e: KeyboardEvent) => { const el = e.target as HTMLElement; return /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName) || el.isContentEditable }

/** Every change is a step that can be taken back (復原) and done again (重做); typing in one field is one step. */
function useSteps() {
  const [h, setH] = useState<{ past: Panel[]; now: Panel | null; next: Panel[] }>({ past: [], now: null, next: [] })
  const last = useRef<{ tag?: string; at: number }>({ at: 0 })
  const edit = (fn: (x: Panel) => void, tag?: string) => setH(s => {
    if (!s.now) return s
    const n = clone(s.now); fn(n)
    if (key(n) === key(s.now)) return s
    const join = !!tag && last.current.tag === tag && Date.now() - last.current.at < 1500
    last.current = { tag, at: Date.now() }
    return { past: join ? s.past : [...s.past.slice(-99), s.now], now: n, next: [] }
  })
  const undo = () => setH(s => s.past.length ? { past: s.past.slice(0, -1), now: s.past[s.past.length - 1], next: [s.now!, ...s.next] } : s)
  const redo = () => setH(s => s.next.length ? { past: [...s.past, s.now!], now: s.next[0], next: s.next.slice(1) } : s)
  const reset = (p: Panel, keep = false) => { last.current = { at: 0 }; setH(s => keep ? { ...s, now: clone(p) } : { past: [], now: clone(p), next: [] }) }
  return { p: h.now, edit, undo, redo, reset, canUndo: h.past.length > 0, canRedo: h.next.length > 0 }
}

/** The panel in edit mode. `live` is the draft as it is now on the server (its blocks with their real contents);
 * `render` draws one. */
export function PanelEditor({ live, render, onDone, onMsg }: {
  live: PanelInfo; render: (b: PanelBlock) => ReactNode; onDone: () => void; onMsg: (m: Notice) => void
}) {
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['panelDefinition'], queryFn: api.panelDefinition })
  const dq = useQuery({ queryKey: ['panelDraft'], queryFn: api.panelDraft, staleTime: Infinity, gcTime: 0 })
  const start = useQuery({ queryKey: ['panelStart'], queryFn: api.panelStart })
  const { p, edit, undo, redo, reset, canUndo, canRedo } = useSteps()
  const [savedKey, setSavedKey] = useState('')                       // the draft as the server keeps it
  const [problems, setProblems] = useState<PanelProblem[]>([])
  const [stale, setStale] = useState(false)                          // published by someone else since the draft began
  useEffect(() => {                                                  // the draft if there is one, else the published panel
    if (!q.data || !dq.data || p) return
    const d = dq.data.draft?.panel ?? q.data.panel
    reset(d); setSavedKey(key(d)); setProblems(dq.data.problems); setStale(!!dq.data.draft?.stale)
  }, [q.data, dq.data, p])                                           // eslint-disable-line react-hooks/exhaustive-deps
  const [sel, setSel] = useState<string | null>(null)
  const [tab, setTab] = useState('')
  const [phone, setPhone] = useState(false)
  const [right, setRight] = useState<'props' | 'problems' | 'chat'>('props')
  const [preview, setPreview] = useState(false)
  const [history, setHistory] = useState(false)
  const [pub, setPub] = useState(false)
  const [left, setLeft] = useState<'add' | 'outline'>('add')
  const [drag, setDrag] = useState<PanelThing | null>(null)
  const published = q.data ? key(q.data.panel) : ''
  const draftKey = p ? key(p) : ''
  const hasDraft = !!p && draftKey !== published
  const pending = !!p && draftKey !== savedKey
  // the draft is kept as it changes (the same as the published panel: no draft); the panel's users see none of it
  const flush = async (x: Panel) => {
    const k = key(x)
    const r = k === published ? (await api.panelDraftDrop(), await api.panelDraft()) : await api.panelDraftSave(x)
    setProblems(r.problems); setSavedKey(k)
    qc.invalidateQueries({ queryKey: ['panel', 'draft'] })
  }
  useEffect(() => {
    if (!p || !pending) return
    const tx = setTimeout(() => { flush(p).catch((e: Error) => onMsg({ ok: false, text: e.message })) }, 700)
    return () => clearTimeout(tx)
  }, [draftKey, savedKey])                                               // eslint-disable-line react-hooks/exhaustive-deps
  const publish = useMutation({
    mutationFn: async (note: string) => { await api.panelPublish(p!, note); return api.panelDefinition() },
    onSuccess: info => {          // what the server keeps (placed, tidied) is the new starting point; the steps stay
      qc.setQueryData(['panelDefinition'], info); reset(info.panel, true); setSavedKey(key(info.panel)); setStale(false); setPub(false)
      setProblems(problems.filter(x => x.level !== 'error'))
      for (const k of ['panel', 'panelStart', 'panelVersions']) qc.invalidateQueries({ queryKey: [k] })
      onMsg({ ok: true, text: t('已發佈,使用者馬上看得到') })
    },
    onError: (e: Error) => onMsg({ ok: false, text: e.message }),
  })
  const done = async () => {
    if (pending) await flush(p!).catch(() => undefined)
    if (hasDraft) onMsg({ ok: true, text: t('草稿留著,還沒發佈;下次編輯會接著改') })
    onDone()
  }
  const discard = async () => {
    if (!window.confirm(t('放棄這份草稿,回到發佈的面板?'))) return
    await api.panelDraftDrop(); reset(q.data!.panel); setSavedKey(published); setStale(false)
    setProblems((await api.panelDraft()).problems); qc.invalidateQueries({ queryKey: ['panel', 'draft'] })
  }
  const openPreview = async () => { if (pending) await flush(p!); setPreview(true) }
  const errors = problems.filter(x => x.level === 'error').length
  const badBlocks = new Set(problems.filter(x => x.level === 'error' && x.block).map(x => x.block))
  useEffect(() => {
    const f = (e: KeyboardEvent) => {
      if (typing(e)) return
      const k = e.key.toLowerCase()
      if ((e.ctrlKey || e.metaKey) && k === 'z') { e.preventDefault(); if (e.shiftKey) redo(); else undo() }
      else if ((e.ctrlKey || e.metaKey) && k === 'y') { e.preventDefault(); redo() }
      else if ((e.ctrlKey || e.metaKey) && k === 's') { e.preventDefault(); if (pending) flush(p!).catch(() => undefined) }
      else if (k === 'escape') setSel(null)
    }
    window.addEventListener('keydown', f)
    return () => window.removeEventListener('keydown', f)
  })
  useEffect(() => {
    if (!pending) return
    const f = (e: BeforeUnloadEvent) => { e.preventDefault() }
    window.addEventListener('beforeunload', f)
    return () => window.removeEventListener('beforeunload', f)
  }, [pending])
  if (!q.data || !p) return <div className="p-8 text-stone-600">{q.isLoading ? t('讀取中…') : t('讀取失敗')}</div>
  const info = q.data
  const pages = p.pages ?? []
  const page = pages.some(g => g.id === tab) ? tab : pages[0]?.id ?? ''
  const pageOf = (b: PanelBlock) => (pages.some(g => g.id === b.page) ? b.page! : pages[0]?.id ?? '')
  const shown = p.blocks.filter(b => pageOf(b) === page)
  const byId = Object.fromEntries(p.controls.map(c => [c.id, c]))
  const block = p.blocks.find(b => b.id === sel)
  const add = (b: Omit<PanelBlock, 'id' | 'place'>, base: string) => {
    const id = newId(base, p.blocks.map(x => x.id))
    const nb = { ...b, id } as PanelBlock
    edit(x => {
      nb.place = { x: 0, y: bottom(shown), w: autoWide(nb, byId) ? COLS : COLS / 2 }
      if (page && page !== pages[0]?.id) nb.page = page
      x.blocks.push(nb)
    })
    setSel(id)
  }
  const places = (l: Layout) => edit(x => setPlaces(x, l))
  const wideOf = (b: PanelBlock, cs: PanelControl[]) => autoWide(b, { ...byId, ...Object.fromEntries(cs.map(c => [c.id, c])) }) ? COLS : COLS / 2
  // a thing of the design: into the picked block when it fits there (a setting or a button into a settings block, a
  // variable into a 數值 widget) unless it is dropped somewhere; else a block of its own where it is dropped / at the bottom
  const into = (th: PanelThing) => !!block && !!th.add && (th.kind === 'variable' ? block.widget?.kind === 'values'
    : !block.widget && !th.add.block.widget && !th.add.block.toggle)
  const put = (th: PanelThing, at?: { x: number; y: number }, l?: Layout) => {
    if (!th.add) return
    const cids = p.controls.map(c => c.id)
    const ids: Record<string, string> = {}
    const cs = th.add.controls.map(c => { const id = newId('c', cids); cids.push(id); ids[c.id] = id; return { ...clone(c), id } })
    const nb = { ...clone(th.add.block), items: th.add.block.items.map(i => ids[i]) } as PanelBlock
    if (nb.toggle) nb.toggle = ids[nb.toggle]
    if (!at && into(th)) {
      edit(x => {
        const o = x.blocks.find(y => y.id === block!.id)!
        if (o.widget) o.widget.vars = [...new Set([...((o.widget.vars as string[] | undefined) ?? []), th.id])]
        else { x.controls.push(...cs); o.items.push(...nb.items) }
      })
      return
    }
    nb.id = newId(nb.widget ? 'w' : 'b', p.blocks.map(x => x.id))
    nb.place = { x: at?.x ?? 0, y: at?.y ?? bottom(shown), w: Math.min(wideOf(nb, cs), COLS - (at?.x ?? 0)) }
    if (page && page !== pages[0]?.id) nb.page = page
    edit(x => { if (l) setPlaces(x, l.filter(it => it.i !== DROPPING)); x.controls.push(...cs); x.blocks.push(clone(nb)) })
    setSel(nb.id)
  }
  // a template: the whole panel's pages, blocks and settings (its name, devices, look and the rest stay)
  const template = (d: PanelDraft, name: string) => {
    if (p.blocks.length && !window.confirm(t('用範本「{name}」重新排這個面板?現在的區塊會被換掉(還沒儲存前可以按復原拿回來)。', { name }))) return
    edit(x => { x.blocks = clone(d.blocks); x.controls = clone(d.controls); if (d.pages?.length) x.pages = clone(d.pages); else delete x.pages })
    setSel(null); setTab('')
  }
  const remove = (id: string) => {
    const b = p.blocks.find(o => o.id === id)!
    if (!window.confirm(b.widget ? t('刪除監看元件「{title}」?', { title: b.title }) : t('刪除區塊「{title}」和它的設定?', { title: b.title }))) return
    edit(x => {
      const i = x.blocks.findIndex(o => o.id === id)
      const gone = new Set([...x.blocks[i].items, x.blocks[i].toggle].filter(Boolean))
      x.controls = x.controls.filter(c => !gone.has(c.id)); x.blocks.splice(i, 1)
    })
    setSel(null)
  }
  const now = Object.fromEntries(live.blocks.map(b => [b.id, b]))
  const goto = (id: string) => { const b = p.blocks.find(x => x.id === id); if (b) { setTab(pageOf(b)); setSel(id); setRight('props') } }
  const load = async (id: string) => {         // an older version back as the draft (one step: undo takes it back)
    const v = await api.panelVersion(id)
    if (!window.confirm(t('把這個版本載入成草稿?現在編輯中的內容會被換掉(可以按復原拿回來),發佈後才會生效。'))) return
    edit(x => { for (const k of Object.keys(x)) delete (x as Record<string, unknown>)[k]; Object.assign(x, clone(v.panel)) })
    setHistory(false); setSel(null); setTab('')
  }
  const cardsAuto = page === (pages[0]?.id ?? '') && !p.blocks.some(b => b.widget?.kind === 'devices')

  return (
    <div className="h-full flex flex-col bg-stone-100 text-stone-900 text-sm">
      <header className="shrink-0 bg-white border-b border-stone-200 px-4 h-14 flex items-center gap-2">
        <span className="shrink-0 text-xs font-semibold px-2 py-1 rounded bg-accent/10 text-accent">{t('編輯中')}</span>
        <input aria-label={t('面板名稱')} className={`${FIELD} w-64 font-medium`} value={p.title} onChange={e => edit(x => { x.title = e.target.value }, 'title')} />
        <span className="w-px h-6 bg-stone-200 mx-1" />
        <Btn size="sm" variant="ghost" disabled={!canUndo} onClick={undo} title={t('復原(Ctrl+Z)')} aria-label={t('復原')}><Icon name="undo" className="w-4 h-4" />{t('復原')}</Btn>
        <Btn size="sm" variant="ghost" disabled={!canRedo} onClick={redo} title={t('重做(Ctrl+Y)')} aria-label={t('重做')}><Icon name="redo" className="w-4 h-4" />{t('重做')}</Btn>
        <span className="flex-1" />
        <span data-testid="draft-state" className={`text-xs ${hasDraft ? 'text-amber-700' : 'text-stone-500'}`}>
          {pending ? t('儲存草稿中…') : hasDraft ? t('● 草稿已儲存,還沒發佈') : t('和發佈的一樣')}</span>
        <Btn variant="ghost" onClick={() => { openPreview().catch((e: Error) => onMsg({ ok: false, text: e.message })) }}>{t('預覽')}</Btn>
        <Btn variant="ghost" onClick={() => setHistory(true)}>{t('版本紀錄')}</Btn>
        {hasDraft && <Btn variant="ghost" onClick={() => { discard().catch((e: Error) => onMsg({ ok: false, text: e.message })) }}>{t('放棄草稿')}</Btn>}
        <Btn variant="primary" disabled={!hasDraft || errors > 0 || publish.isPending} title={errors ? t('先處理問題清單裡的錯誤') : undefined}
          onClick={() => setPub(true)}>{t('發佈')}</Btn>
        <Btn onClick={() => { done().catch(() => undefined) }}>{t('完成')}</Btn>
      </header>
      {stale && hasDraft && <div className="shrink-0 bg-amber-50 border-b border-amber-200 text-amber-900 text-xs px-4 py-2">
        {t('這份草稿開始之後,面板被發佈過(別的分頁或 AI);現在發佈會蓋掉那次的修改。要看那次改了什麼,打開「版本紀錄」。')}</div>}
      <div className="lg:hidden p-6 text-stone-600">{t('編輯面板請用電腦的寬螢幕。')}</div>
      <div className="hidden lg:flex flex-1 min-h-0">
        <aside className="w-72 shrink-0 bg-white border-r border-stone-200 flex flex-col" aria-label={t('元件與大綱')}>
          <div className="shrink-0 grid grid-cols-2 border-b border-stone-200 text-[0.8125rem]" role="tablist">
            {([['add', t('加入')], ['outline', t('大綱')]] as const).map(([k, tx]) => (
              <button key={k} role="tab" aria-selected={left === k} onClick={() => setLeft(k)}
                className={`h-10 ${left === k ? 'font-semibold text-accent border-b-2 border-accent' : 'text-stone-600 hover:bg-stone-50'}`}>{tx}</button>))}
          </div>
          <div className="flex-1 min-h-0 overflow-y-auto p-3 flex flex-col gap-5">
          {left === 'add' ? <>
          {start.data && <FromDesign start={start.data} p={p} onPut={put} onDrag={setDrag} into={into} />}
          <Pane title={t('監看元件')}>
            <button className="text-left px-2 py-1.5 rounded hover:bg-stone-100" onClick={() => add({ title: t('新的區塊'), items: [] }, 'b')}>+ {t('空白的設定區塊')}</button>
            {Object.entries(info.widgets).map(([k, tx]) => (
              <button key={k} className="text-left px-2 py-1.5 rounded hover:bg-stone-100"
                onClick={() => add({ title: tx, items: [], widget: { kind: k as PanelWidget['kind'], ...clone(info.widget_defaults[k] ?? {}) } }, 'w')}>+ {tx}</button>
            ))}
          </Pane>
          {start.data && <Pane title={t('範本')}>
            <span className="px-2 pb-1 text-xs text-stone-500">{t('依方案包的內容排好整個面板,之後再自己改')}</span>
            {start.data.templates.map(tp => (
              <button key={tp.id} className="text-left px-2 py-1.5 rounded hover:bg-stone-100 flex flex-col" onClick={() => template(start.data!.drafts[tp.id], tp.name)}>
                <span>{tp.name}</span><span className="text-xs text-stone-500">{tp.desc}</span></button>))}
          </Pane>}
          </> : <>
          <Pages p={p} page={page} setPage={setTab} edit={edit} />
          <Pane title={t('這頁的區塊')}>
            {shown.length === 0 && <span className="text-xs text-stone-400 px-2">{t('還沒有區塊')}</span>}
            {[...shown].sort((a, b) => ((a.place?.y ?? 0) - (b.place?.y ?? 0)) || ((a.place?.x ?? 0) - (b.place?.x ?? 0))).map(b => (
              <button key={b.id} onClick={() => setSel(b.id)} aria-current={sel === b.id || undefined}
                className={`text-left px-2 py-1.5 rounded flex flex-col ${sel === b.id ? 'bg-accent/10 text-accent' : 'hover:bg-stone-100'}`}>
                <span className="font-medium truncate">{b.title || t('(沒有標題)')}</span>
                <span className="text-xs text-stone-500">{b.widget ? info.widgets[b.widget.kind] ?? b.widget.kind : t('{n} 項設定', { n: b.items.length + (b.toggle ? 1 : 0) })}</span>
              </button>
            ))}
          </Pane>
          </>}
          </div>
        </aside>

        <main className="flex-1 min-w-0 overflow-y-auto p-4 flex flex-col gap-3" onClick={e => { if (e.target === e.currentTarget) setSel(null) }}>
          <div className="flex items-center gap-2">
            <div className="inline-flex rounded-md border border-stone-300 bg-white overflow-hidden text-[0.8125rem]">
              {([[false, t('寬螢幕')], [true, t('手機')]] as const).map(([v, tx]) => (
                <button key={String(v)} onClick={() => setPhone(v)} aria-pressed={phone === v}
                  className={`px-3 h-8 ${phone === v ? 'bg-stone-800 text-white' : 'hover:bg-stone-50'}`}>{tx}</button>))}
            </div>
            <span className="text-xs text-stone-500">{phone ? t('手機上一欄由上到下:用 ▲▼ 排順序,也可以讓區塊在手機上不顯示')
              : t('拖拉區塊移動位置,拉右邊或下面的邊改大小;點一下區塊在右邊改它的內容')}</span>
          </div>
          {p.blocks.length === 0 && start.data && <section className="rounded-lg border border-stone-200 bg-white p-4 flex flex-col gap-3" aria-label={t('產生第一版')}>
            <div><h2 className="font-semibold">{t('從方案包產生第一版')}</h2>
              <div className="text-xs text-stone-500">{t('依方案包裡的排程、使用者設定、情境和數值排好,之後再拖拉調整;也可以從左邊一項一項拖進來。')}</div></div>
            <div className="grid grid-cols-3 gap-3">
              {start.data.templates.map(tp => (
                <button key={tp.id} onClick={() => template(start.data!.drafts[tp.id], tp.name)}
                  className="text-left rounded-lg border border-stone-300 hover:border-accent hover:bg-accent/5 p-3 flex flex-col gap-1">
                  <b>{tp.name}</b><span className="text-xs text-stone-500">{tp.desc}</span>
                  <span className="text-xs text-stone-400 num">{t('{n} 個區塊', { n: start.data!.drafts[tp.id].blocks.length })}</span>
                </button>))}
            </div>
          </section>}
          {cardsAuto && <div className="rounded-lg border border-dashed border-stone-300 px-3 py-2 text-xs text-stone-500">
            {t('每台{device}的卡片會自動放在第一頁最上面;要自己決定位置,加入「裝置狀態」元件。', { device: words.device })}</div>}
          {phone
            ? <PhoneList blocks={shown} sel={sel} setSel={setSel} edit={edit} info={info} />
            : <Canvas blocks={shown} sel={sel} setSel={setSel} onPlaces={places} info={info}
                drag={drag?.add ? { w: wideOf({ ...drag.add.block, id: '' } as PanelBlock, drag.add.controls) } : null}
                onDrop={(l, it) => { if (drag && it) put(drag, { x: it.x, y: it.y }, l); setDrag(null) }}
                content={b => now[b.id] ? render({ ...now[b.id], title: b.title, help: b.help }) : <Empty>{t('更新中…')}</Empty>}
                changed={() => pending} bad={b => badBlocks.has(b.id)} />}
        </main>

        <aside className="w-96 shrink-0 bg-white border-l border-stone-200 flex flex-col" aria-label={t('屬性')}>
          <div className="shrink-0 grid grid-cols-3 border-b border-stone-200 text-[0.8125rem]" role="tablist">
            {([['props', t('屬性')], ['problems', problems.length ? t('問題 {n}', { n: problems.length }) : t('問題')], ['chat', t('聊天')]] as const).map(([k, tx]) => (
              <button key={k} role="tab" aria-selected={right === k} onClick={() => setRight(k)}
                className={`h-10 ${right === k ? 'font-semibold text-accent border-b-2 border-accent' : 'text-stone-600 hover:bg-stone-50'} ${k === 'problems' && errors ? 'text-rose-700' : ''}`}>{tx}</button>))}
          </div>
          <div className="flex-1 min-h-0 overflow-y-auto p-4 flex flex-col gap-4">
            {right === 'problems' ? <Problems items={problems} onGo={goto} pending={pending} />
              : right === 'chat' ? <ChatPreview panel={p} />
              : block ? <BlockProps key={block.id} b={block} p={p} info={info} edit={edit} onDelete={() => remove(block.id)} onClose={() => setSel(null)} />
              : <PanelProps p={p} info={info} edit={edit} />}
          </div>
        </aside>
      </div>
      {preview && <Preview devices={live.devices} onClose={() => setPreview(false)} />}
      <History open={history} onClose={() => setHistory(false)} onLoad={id => { load(id).catch((e: Error) => onMsg({ ok: false, text: e.message })) }} />
      <PublishDialog open={pub} warns={problems.filter(x => x.level === 'warn').length} busy={publish.isPending}
        onClose={() => setPub(false)} onPublish={note => publish.mutate(note)} />
    </div>
  )
}

/** The design's own things, by group, each as it is now: click puts it on the panel (into the picked block when it
 * fits there), or drag it to where it should go. */
function FromDesign({ start, p, onPut, onDrag, into }: {
  start: PanelStart; p: Panel; onPut: (th: PanelThing) => void; onDrag: (th: PanelThing | null) => void; into: (th: PanelThing) => boolean
}) {
  const [q, setQ] = useState('')
  const [shut, setShut] = useState<Record<string, boolean>>({ sub: true })
  const kinds = Object.keys(start.groups) as PanelThing['kind'][]
  const hit = (th: PanelThing) => !q.trim() || `${th.group ?? ''} ${th.name}`.toLowerCase().includes(q.trim().toLowerCase())
  return (
    <Pane title={t('從設定開始')}>
      <span className="px-2 pb-1 text-xs text-stone-500">{t('點一下放到這頁最下面(有選區塊時加進那個區塊),或拖到面板上想放的位置')}</span>
      <input className={`${FIELD} mx-1 mb-1`} placeholder={t('找…')} aria-label={t('找設定')} value={q} onChange={e => setQ(e.target.value)} />
      {kinds.map(k => {
        const xs = start.things.filter(th => th.kind === k && hit(th))
        if (!xs.length) return null
        const open = !!q.trim() || !shut[k]
        return <div key={k} className="flex flex-col">
          <button className="flex items-center gap-1 px-2 py-1 text-xs font-semibold text-stone-600 hover:text-stone-900" aria-expanded={open}
            onClick={() => setShut(s => ({ ...s, [k]: open }))}>
            <span className="w-3">{open ? '▾' : '▸'}</span><span className="flex-1 text-left">{start.groups[k]}</span><span className="font-normal text-stone-400 num">{xs.length}</span></button>
          {open && xs.map(th => {
            const on = placed(th, p)
            return <button key={`${k}:${th.id}`} disabled={!th.add} draggable={!!th.add} data-thing={`${k}:${th.id}`}
              title={th.why ?? th.help ?? (into(th) ? t('加到選取的區塊') : t('放到這頁最下面'))}
              onClick={() => onPut(th)} onDragEnd={() => onDrag(null)}
              onDragStart={e => { e.dataTransfer.setData('text/plain', th.name); e.dataTransfer.effectAllowed = 'copy'; onDrag(th) }}
              className="text-left pl-6 pr-2 py-1 rounded hover:bg-stone-100 disabled:opacity-50 disabled:hover:bg-transparent cursor-grab disabled:cursor-not-allowed flex flex-col">
              <span className="flex items-center gap-1.5 min-w-0">
                <span className="truncate">{th.group && <span className="text-stone-400">{th.group} › </span>}{th.name}</span>
                {on && <span className="shrink-0 text-[0.6875rem] px-1 rounded bg-stone-100 text-stone-500">{t('已放上')}</span>}
              </span>
              {(th.why || th.now) && <span className={`text-xs truncate ${th.why ? 'text-amber-700' : 'text-stone-500'}`}>{th.why ?? th.now}</span>}
            </button>
          })}
        </div>
      })}
    </Pane>
  )
}

const when = (s: number) => new Date(s * 1000).toLocaleString(locale, { year: 'numeric', month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' })

/** What is wrong with the draft (errors keep it from being published) or worth a look; one about a block goes to it. */
function Problems({ items, onGo, pending }: { items: PanelProblem[]; onGo: (block: string) => void; pending: boolean }) {
  if (!items.length) return <Empty>{pending ? t('檢查中…') : t('沒有問題,可以發佈')}</Empty>
  return <div className="flex flex-col gap-2" data-testid="problems">
    {items.map((x, i) => (
      <button key={i} disabled={!x.block} onClick={() => x.block && onGo(x.block)}
        className={`text-left rounded-md border px-3 py-2 flex gap-2 ${x.level === 'error' ? 'border-rose-200 bg-rose-50 text-rose-900' : 'border-amber-200 bg-amber-50 text-amber-900'} ${x.block ? 'hover:brightness-95' : 'cursor-default'}`}>
        <span className="shrink-0 font-semibold">{x.level === 'error' ? t('錯誤') : t('注意')}</span><span className="flex-1">{x.text}</span>
      </button>))}
    <span className="text-xs text-stone-500">{t('有錯誤的草稿不能發佈;「注意」可以先不管。')}</span>
  </div>
}

const SIZES = [['desk', 1280], ['tablet', 820], ['phone', 390]] as const

/** The draft as the panel's users will see it, at a computer's, a tablet's or a phone's width, on the overview or one
 * device's own page (the page itself, in preview: nothing it is asked to do happens). */
function Preview({ devices, onClose }: { devices: string[]; onClose: () => void }) {
  const [size, setSize] = useState<(typeof SIZES)[number][0]>('desk')
  const [dev, setDev] = useState('')
  const box = useRef<HTMLDivElement>(null)
  const [room, setRoom] = useState({ w: 1200, h: 700 })
  useEffect(() => {
    const el = box.current
    if (!el) return
    const ro = new ResizeObserver(() => setRoom({ w: el.clientWidth, h: el.clientHeight }))
    ro.observe(el)
    const k = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', k)
    return () => { ro.disconnect(); window.removeEventListener('keydown', k) }
  }, [onClose])
  const w = SIZES.find(x => x[0] === size)![1]
  const scale = Math.min(1, (room.w - 32) / w)
  const label = { desk: t('桌機'), tablet: t('平板'), phone: t('手機') }
  return (
    <div className="fixed inset-0 z-50 bg-stone-900/80 flex flex-col" role="dialog" aria-modal="true" aria-label={t('預覽')}>
      <div className="shrink-0 bg-white px-4 h-12 flex items-center gap-3 text-sm">
        <b>{t('預覽草稿')}</b>
        <div className="inline-flex rounded-md border border-stone-300 overflow-hidden text-[0.8125rem]">
          {SIZES.map(([k, px]) => <button key={k} aria-pressed={size === k} onClick={() => setSize(k)}
            className={`px-3 h-8 ${size === k ? 'bg-stone-800 text-white' : 'hover:bg-stone-50'}`}>{label[k]} <span className="opacity-60 num">{px}</span></button>)}
        </div>
        <select aria-label={t('看哪一頁')} className={FIELD} value={dev} onChange={e => setDev(e.target.value)}>
          <option value="">{t('總覽')}</option>
          {devices.map(n => <option key={n} value={n}>{t('{device} 自己的頁面', { device: n })}</option>)}
        </select>
        <span className="flex-1 text-xs text-stone-500">{t('發佈後使用者看到的就是這樣;在預覽裡按了不會真的動作')}</span>
        <Btn onClick={onClose}>{t('關閉')}</Btn>
      </div>
      <div ref={box} className="flex-1 min-h-0 overflow-auto p-4 flex justify-center">
        <iframe key={`${size}|${dev}`} title={t('預覽')} src={`/panel${dev ? `/device/${encodeURIComponent(dev)}` : ''}?draft=1`}
          className="bg-white rounded-lg shadow-xl shrink-0 origin-top"
          style={{ width: w, height: (room.h - 32) / scale, transform: `scale(${scale})` }} />
      </div>
    </div>
  )
}

/** Every published version (newest first); one of them comes back as the draft, to look at and publish again. */
function History({ open, onClose, onLoad }: { open: boolean; onClose: () => void; onLoad: (id: string) => void }) {
  const q = useQuery({ queryKey: ['panelVersions'], queryFn: api.panelVersions, enabled: open })
  return (
    <Modal open={open} title={t('版本紀錄')} onClose={onClose}>
      <div className="text-xs text-stone-500">{t('每次發佈都會留一份(最近 50 份)。載入成草稿後,看過沒問題再發佈。')}</div>
      {!q.data ? <Empty>{t('讀取中…')}</Empty> : !q.data.items.length ? <Empty>{t('還沒有發佈過')}</Empty> :
        <div className="flex flex-col divide-y divide-stone-100" data-testid="versions">
          {q.data.items.map((v, i) => (
            <div key={v.id} className="py-2 flex items-center gap-3">
              <div className="flex-1 min-w-0"><div className="font-medium">{when(v.t)}{i === 0 && <span className="ml-2 text-xs px-1.5 rounded bg-accent/10 text-accent">{t('現在發佈的')}</span>}</div>
                <div className="text-xs text-stone-500 truncate">{v.note} · {t('{n} 個區塊', { n: v.blocks })}</div></div>
              <Btn size="sm" onClick={() => onLoad(v.id)}>{t('載入成草稿')}</Btn>
            </div>))}
        </div>}
    </Modal>
  )
}

function PublishDialog({ open, warns, busy, onClose, onPublish }: { open: boolean; warns: number; busy: boolean; onClose: () => void; onPublish: (note: string) => void }) {
  const [note, setNote] = useState('')
  return (
    <Modal open={open} title={t('發佈面板')} onClose={onClose}
      footer={<><Btn variant="ghost" onClick={onClose}>{t('取消')}</Btn>
        <Btn variant="primary" disabled={busy} onClick={() => { onPublish(note); setNote('') }}>{busy ? t('發佈中…') : t('發佈')}</Btn></>}>
      <div>{t('發佈後,使用者馬上會看到新的面板。之前的版本會留在「版本紀錄」,隨時可以拿回來。')}</div>
      {warns > 0 && <div className="text-amber-800 text-xs">{t('問題清單裡還有 {n} 項「注意」,發佈前可以先看一下。', { n: warns })}</div>}
      <label className="flex flex-col gap-1"><span className="text-stone-600">{t('這次改了什麼(可不填,會記在版本紀錄)')}</span>
        <input className={FIELD} value={note} onChange={e => setNote(e.target.value)} placeholder={t('例:排程移到第二頁')} /></label>
    </Modal>
  )
}

function Pane({ title, extra, children }: { title: string; extra?: ReactNode; children: ReactNode }) {
  return <section className="flex flex-col gap-0.5">
    <div className="flex items-center px-2 pb-1"><h2 className="flex-1 text-xs font-semibold text-stone-500 uppercase tracking-wide">{title}</h2>{extra}</div>
    {children}
  </section>
}

/** The page being arranged on the 12-column grid: each block shows what it really shows (it cannot be used here). */
function Canvas({ blocks, sel, setSel, onPlaces, content, changed, bad, info, drag, onDrop }: {
  blocks: PanelBlock[]; sel: string | null; setSel: (id: string) => void; onPlaces: (l: Layout) => void
  content: (b: PanelBlock) => ReactNode; changed: (b: PanelBlock) => boolean; bad: (b: PanelBlock) => boolean; info: PanelDefinition
  drag: { w: number } | null; onDrop: (l: Layout, it: Layout[number] | undefined) => void      // something of the design dragged in
}) {
  const { width, containerRef, mounted } = useContainerWidth()
  const layout = blocks.map(b => ({ i: b.id, x: b.place?.x ?? 0, y: b.place?.y ?? 0, w: b.place?.w ?? COLS, h: b.place?.h ?? 1 }))
  return (
    <div ref={containerRef} data-testid="edit-grid" className={`relative min-h-40 rounded-lg ${drag ? 'outline-2 outline-dashed outline-offset-4 outline-accent/40' : ''}`}>
      {blocks.length === 0 && <div className="absolute inset-0 rounded-lg border border-dashed border-stone-300 p-8 text-center text-stone-500 pointer-events-none">{t('這頁還沒有區塊:從左邊「加入」放一個進來')}</div>}
      {mounted && <ReactGridLayout width={width} layout={layout} compactor={verticalCompactor} style={{ minHeight: '10rem' }}
        gridConfig={{ cols: COLS, rowHeight: ROW, margin: [16, 16], containerPadding: [0, 0] }}
        dragConfig={{ enabled: true, cancel: '.no-drag' }} resizeConfig={{ enabled: true, handles: ['e', 's', 'se'] }}
        dropConfig={{ enabled: !!drag, defaultItem: { w: drag?.w ?? COLS / 2, h: 1 } }} onDropDragOver={() => drag ? { w: drag.w, h: 1 } : false}
        onDrop={(l, it) => onDrop(l, it)}
        onDragStop={l => onPlaces(l)} onResizeStop={l => onPlaces(l)}>
        {blocks.map(b => (
          <div key={b.id} data-block={b.id} data-place={JSON.stringify(b.place ?? null)} onClick={() => setSel(b.id)}
            className={`group relative rounded-lg overflow-hidden cursor-move bg-white ${sel === b.id ? 'ring-2 ring-accent' : 'ring-1 ring-stone-300 hover:ring-stone-400'}`}>
            <div className="pointer-events-none select-none h-full overflow-hidden" inert>{content(b)}</div>
            <div className="pointer-events-none absolute inset-x-0 bottom-0 h-10 bg-gradient-to-t from-white" />
            <div className="pointer-events-none absolute top-1.5 right-1.5 flex gap-1 text-[0.6875rem]">
              {bad(b) && <span className="px-1.5 py-0.5 rounded bg-rose-100 text-rose-800">{t('有問題')}</span>}
              {changed(b) && <span className="px-1.5 py-0.5 rounded bg-stone-100 text-stone-600">{t('更新中…')}</span>}
              {b.phone?.hide && <span className="px-1.5 py-0.5 rounded bg-stone-200 text-stone-600">{t('手機不顯示')}</span>}
              <span className="px-1.5 py-0.5 rounded bg-stone-800/80 text-white num">{b.widget ? info.widgets[b.widget.kind] ?? b.widget.kind : t('設定')} · {b.place?.w ?? COLS}/{COLS}</span>
            </div>
          </div>
        ))}
      </ReactGridLayout>}
    </div>
  )
}

/** How the page runs down a phone: its order (▲▼ give every block of the page an order) and the ones left out. */
function PhoneList({ blocks, sel, setSel, edit, info }: {
  blocks: PanelBlock[]; sel: string | null; setSel: (id: string) => void; edit: (fn: (x: Panel) => void) => void; info: PanelDefinition
}) {
  const wide = (b: PanelBlock) => (b.place?.y ?? 0) * 100 + (b.place?.x ?? 0)
  const list = [...blocks].sort((a, b) => ((a.phone?.order ?? Infinity) - (b.phone?.order ?? Infinity)) || wide(a) - wide(b))
  const reorder = (i: number, d: number) => edit(x => {
    move(list, i, d).forEach((b, j) => { const o = x.blocks.find(y => y.id === b.id)!; o.phone = { ...o.phone, order: j + 1 } })
  })
  return (
    <div className="w-[24rem] max-w-full mx-auto flex flex-col gap-2" data-testid="phone-list">
      {list.map((b, i) => (
        <div key={b.id} onClick={() => setSel(b.id)} data-block={b.id}
          className={`rounded-lg bg-white px-3 py-2.5 flex items-center gap-2 cursor-pointer ${sel === b.id ? 'ring-2 ring-accent' : 'ring-1 ring-stone-300'} ${b.phone?.hide ? 'opacity-50' : ''}`}>
          <span className="w-5 text-xs text-stone-400 num">{i + 1}</span>
          <div className="flex-1 min-w-0"><div className="font-medium truncate">{b.title}</div>
            <div className="text-xs text-stone-500">{b.widget ? info.widgets[b.widget.kind] : t('設定')}{b.phone?.hide ? t(' · 手機不顯示') : ''}</div></div>
          <Btn size="sm" variant="ghost" aria-label={t('往上')} disabled={i === 0} onClick={e => { e.stopPropagation(); reorder(i, -1) }}>▲</Btn>
          <Btn size="sm" variant="ghost" aria-label={t('往下')} disabled={i === list.length - 1} onClick={e => { e.stopPropagation(); reorder(i, 1) }}>▼</Btn>
        </div>
      ))}
    </div>
  )
}

/** The panel's tabs (none = one page 總覽); a page's blocks go to the first when it is deleted. */
function Pages({ p, page, setPage, edit }: { p: Panel; page: string; setPage: (id: string) => void; edit: (fn: (x: Panel) => void, tag?: string) => void }) {
  const pages = p.pages ?? []
  const addPage = () => {
    const ids = pages.map(g => g.id)
    const id = pages.length ? newId('page', ids) : 'page2'
    edit(x => { if (!x.pages?.length) x.pages = [{ id: 'main', title: t('總覽') }]; x.pages.push({ id, title: t('新的分頁') }) })
    setPage(id)
  }
  return (
    <Pane title={t('分頁')} extra={<button className="text-xs text-accent hover:underline" onClick={addPage}>+ {t('新增分頁')}</button>}>
      {pages.length === 0 && <span className="px-2 text-xs text-stone-500">{t('只有一頁「總覽」')}</span>}
      {pages.map((g, gi) => (
        <div key={g.id} className={`flex items-center gap-1 rounded px-1 ${g.id === page ? 'bg-stone-100' : ''}`}>
          <button className="w-4 text-stone-400" aria-label={t('看這頁')} onClick={() => setPage(g.id)}>{g.id === page ? '●' : '○'}</button>
          <input className="flex-1 min-w-0 bg-transparent px-1 py-1 rounded focus:bg-white focus:outline-none focus:ring-1 focus:ring-stone-300" value={g.title}
            onFocus={() => setPage(g.id)} onChange={e => edit(x => { x.pages![gi].title = e.target.value }, `page:${g.id}`)} />
          <button className="text-stone-400 hover:text-stone-700 disabled:opacity-30" disabled={gi === 0} aria-label={t('往上')} onClick={() => edit(x => { x.pages = move(x.pages!, gi, -1) })}>▲</button>
          <button className="text-stone-400 hover:text-stone-700 disabled:opacity-30" disabled={gi === pages.length - 1} aria-label={t('往下')} onClick={() => edit(x => { x.pages = move(x.pages!, gi, 1) })}>▼</button>
          <button className="text-stone-400 hover:text-rose-700" aria-label={t('刪除分頁')} onClick={() => {
            if (window.confirm(t('刪除分頁「{title}」?上面的區塊會移到第一個分頁。', { title: g.title }))) edit(x => {
              x.pages!.splice(gi, 1)
              const first = x.pages![0]?.id
              const y0 = bottom(x.blocks.filter(b => (b.page ?? first) === first || !x.pages!.some(q => q.id === b.page)))
              for (const b of x.blocks) if (b.page === g.id) { delete b.page; if (b.place) b.place = { ...b.place, y: b.place.y + y0 } }
              if (x.pages!.length <= 1) delete x.pages
            })
          }}>✕</button>
        </div>
      ))}
    </Pane>
  )
}

/** The picked block: its words, where it is, how it is on a phone, and what is in it. */
function BlockProps({ b, p, info, edit, onDelete, onClose }: {
  b: PanelBlock; p: Panel; info: PanelDefinition; edit: (fn: (x: Panel) => void, tag?: string) => void; onDelete: () => void; onClose: () => void
}) {
  const [openCtl, setOpenCtl] = useState<string | null>(null)
  const pages = p.pages ?? []
  const me = (fn: (x: PanelBlock) => void, tag?: string) => edit(x => fn(x.blocks.find(o => o.id === b.id)!), tag && `${tag}:${b.id}`)
  const ctl = (id: string) => p.controls.find(c => c.id === id) as Ctl | undefined
  const setCtl = (id: string) => (fn: (c: Ctl) => void) => edit(x => fn(x.controls.find(c => c.id === id) as Ctl), `ctl:${id}`)
  const addControl = () => {
    const id = newId('c', p.controls.map(c => c.id))
    const s = info.schedules[0]
    edit(x => { x.controls.push({ id, label: t('新的設定'), type: 'toggle', scope: 'global', bind: { kind: 'schedule', schedule: s?.id, field: 'enabled' } }); x.blocks.find(o => o.id === b.id)!.items.push(id) })
    setOpenCtl(id)
  }
  const toPage = (id: string) => edit(x => {
    const o = x.blocks.find(y => y.id === b.id)!
    const there = x.blocks.filter(y => y.id !== b.id && (pages.some(g => g.id === y.page) ? y.page : pages[0]?.id) === id)
    if (id === pages[0]?.id) delete o.page; else o.page = id
    o.place = { ...(o.place ?? { x: 0, w: COLS }), x: 0, y: bottom(there) } as PanelPlace
  })
  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center gap-2">
        <h2 className="flex-1 font-semibold">{b.widget ? info.widgets[b.widget.kind] ?? b.widget.kind : t('設定區塊')}</h2>
        <Btn size="sm" variant="ghost" onClick={onClose}>{t('面板設定')}</Btn>
      </div>
      <label className="flex flex-col gap-1"><span className="text-stone-600">{t('標題')}</span>
        <input className={FIELD} value={b.title} onChange={e => me(x => { x.title = e.target.value }, 'title')} /></label>
      <label className="flex flex-col gap-1"><span className="text-stone-600">{t('說明')}</span>
        <input className={FIELD} placeholder={t('一句話說明這個區塊(使用者看得到)')} value={b.help ?? ''} onChange={e => me(x => { x.help = e.target.value || undefined }, 'help')} /></label>
      {pages.length > 0 && <label className="flex flex-col gap-1"><span className="text-stone-600">{t('放在哪個分頁')}</span>
        <select className={FIELD} value={pages.some(g => g.id === b.page) ? b.page : pages[0].id} onChange={e => toPage(e.target.value)}>
          {pages.map(g => <option key={g.id} value={g.id}>{g.title}</option>)}</select></label>}
      <div className="flex items-center justify-between gap-3"><span className="text-stone-600">{t('手機上不顯示')}</span>
        <Switch on={!!b.phone?.hide} label={t('手機上不顯示')} onChange={v => me(x => { x.phone = { ...x.phone, hide: v || undefined }; if (!x.phone.hide && x.phone.order == null) delete x.phone })} /></div>
      <div className="border-t border-stone-100 pt-4 flex flex-col gap-3">
        {b.widget
          ? <WidgetEditor w={b.widget} info={info} onChange={fn => me(x => fn(x.widget!), 'widget')} />
          : <>
              <label className="flex flex-col gap-1"><span className="text-stone-600">{t('標題旁的大開關')}</span>
                <select className={FIELD} value={b.toggle ?? ''} onChange={e => me(blk => {
                  const prev = blk.toggle
                  blk.toggle = e.target.value || undefined
                  blk.items = blk.items.filter(i => i !== blk.toggle)
                  if (prev && prev !== blk.toggle) blk.items.unshift(prev)
                })}>
                  <option value="">{t('(沒有)')}</option>
                  {[b.toggle, ...b.items].filter(Boolean).map(i => ctl(i!)).filter(c => c && c.type === 'toggle' && c.scope !== 'device')
                    .map(c => <option key={c!.id} value={c!.id}>{c!.label}</option>)}
                </select></label>
              {b.toggle && ctl(b.toggle) && <ControlEditor c={ctl(b.toggle)!} info={info} open={openCtl === b.toggle} onOpen={() => setOpenCtl(o => o === b.toggle ? null : b.toggle!)}
                onChange={setCtl(b.toggle)} header />}
              {b.items.map((id, ii) => ctl(id) && (
                <ControlEditor key={id} c={ctl(id)!} info={info} open={openCtl === id} onOpen={() => setOpenCtl(o => o === id ? null : id)}
                  onChange={setCtl(id)} onMove={dlt => me(x => { x.items = move(x.items, ii, dlt) })} first={ii === 0} last={ii === b.items.length - 1}
                  onDelete={() => edit(x => { const o = x.blocks.find(y => y.id === b.id)!; o.items.splice(ii, 1); x.controls = x.controls.filter(c => c.id !== id) })} />
              ))}
              <button className="self-start text-sm text-accent hover:underline" onClick={addControl}>{t('+ 在這個區塊加一項設定')}</button>
            </>}
      </div>
      <div className="border-t border-stone-100 pt-4"><Btn variant="danger" onClick={onDelete}>{t('刪除這個區塊')}</Btn></div>
    </div>
  )
}

/** Nothing picked: the panel's own settings - its look, which emulators, what users may add, the PINs. */
function PanelProps({ p, info, edit }: { p: Panel; info: PanelDefinition; edit: (fn: (x: Panel) => void, tag?: string) => void }) {
  const theme = p.theme ?? {}
  const setTheme = (fn: (th: NonNullable<Panel['theme']>) => void, tag?: string) => edit(x => {
    const th = { ...(x.theme ?? {}) }; fn(th)
    if (!th.accent) delete th.accent
    if (!th.big_text) delete th.big_text
    if (Object.keys(th).length) x.theme = th; else delete x.theme
  }, tag)
  const devices = [...new Set([...sourceIds(info.devices), ...p.devices])]
  return (
    <div className="flex flex-col gap-4">
      <h2 className="font-semibold">{t('面板設定')}</h2>
      <div className="text-xs text-stone-500 -mt-2">{t('點中間的區塊改它的內容;沒點選時這裡是整個面板的設定。')}</div>
      <section className="flex flex-col gap-3">
        <h3 className="text-xs font-semibold text-stone-500">{t('外觀')}</h3>
        <div className="flex items-center justify-between gap-3"><span className="text-stone-600">{t('強調色(要按的東西)')}</span>
          <span className="flex items-center gap-2">
            <input type="color" aria-label={t('強調色(要按的東西)')} className="h-8 w-12 rounded border border-stone-300 bg-white" value={theme.accent ?? '#0369a1'}
              onChange={e => setTheme(th => { th.accent = e.target.value }, 'accent')} />
            {theme.accent && <button className="text-xs text-stone-500 underline" onClick={() => setTheme(th => { delete th.accent })}>{t('用預設')}</button>}
          </span></div>
        <div className="flex items-center justify-between gap-3"><span className="text-stone-600">{t('預設用大字(看的人可以自己關掉)')}</span>
          <Switch on={!!theme.big_text} label={t('預設用大字(看的人可以自己關掉)')} onChange={v => setTheme(th => { th.big_text = v })} /></div>
      </section>
      <Card title={t('顯示哪些機台')}>
        <div className="flex flex-wrap gap-3 text-sm">
          <SourcePick value={p.devices} devices={devices} onChange={v => edit(x => { x.devices = v })} />
          <span className="text-xs text-stone-500">{p.devices.length ? t('依勾選順序顯示') : t('都沒勾 = 全部顯示')}</span>
        </div>
      </Card>
      <SourcePolicyCard p={p} info={info} edit={edit} />
      <AccessCard />
    </div>
  )
}

/** What the people running the pack may scan for and pick ("選擇模擬器" on their panel): kinds (or a whole category),
 * a name filter, what to have ready, how a picked one starts. */
function SourcePolicyCard({ p, info, edit }: { p: Panel; info: PanelDefinition; edit: (fn: (x: Panel) => void) => void }) {
  const pol = p.sources ?? {}
  const kinds = info.source_kinds ?? []
  const cats = [...new Map(kinds.map(k => [k.category ?? k.kind.split('/')[0], k.category_label ?? k.kind.split('/')[0]])).entries()]
  const has = (k: string) => (pol.kinds ?? []).includes(k)
  const set = (fn: (s: NonNullable<Panel['sources']>) => void) => edit(x => { const s = { ...(x.sources ?? {}) }; fn(s); x.sources = s })
  const tick = (k: string, v: boolean) => set(s => { const cur = s.kinds ?? []; s.kinds = v ? [...cur, k] : cur.filter(x => x !== k) })
  return (
    <Card title={t('使用者可以加入的來源')} extra={<span className="text-xs text-stone-500">{t('使用者面板右上角的「選擇…」:掃描這些,勾選要用的')}</span>}>
      <div className="flex flex-col gap-3 text-sm">
        {cats.map(([c, cl]) => (
          <div key={c} className="flex flex-col gap-1">
            <label className="flex items-center gap-1.5 font-medium"><input type="checkbox" checked={has(`${c}/*`)} onChange={e => tick(`${c}/*`, e.target.checked)} />{t('{cl}(整個大類,之後新增的產品也算)', { cl })}</label>
            {!has(`${c}/*`) && <div className="flex flex-wrap gap-3 ml-5">
              {kinds.filter(k => (k.category ?? k.kind.split('/')[0]) === c).map(k => (
                <label key={k.kind} className="flex items-center gap-1"><input type="checkbox" checked={has(k.kind)} onChange={e => tick(k.kind, e.target.checked)} />{k.label}</label>))}
            </div>}
          </div>
        ))}
        <label className="flex flex-col gap-1"><span className="text-stone-600">{t('名稱過濾(找到的名稱或說明要有這些字,空白分開;不填 = 不過濾)')}</span>
          <input className={input} value={pol.q ?? ''} placeholder={t('例:NVR 北棟')} onChange={e => set(s => { s.q = e.target.value || undefined })} /></label>
        <label className="flex flex-col gap-1"><span className="text-stone-600">{t('掃描前要準備什麼(使用者看得到)')}</span>
          <input className={input} value={pol.help ?? ''} placeholder={t('例:先開好模擬器,並登入 App')} onChange={e => set(s => { s.help = e.target.value || undefined })} /></label>
        <label className="flex items-center gap-2"><span className="text-stone-600">{t('勾選後,主腳本在這台')}</span>
          <select className={input} value={pol.new_mode ?? 'shadow'} onChange={e => set(s => { s.new_mode = e.target.value as 'shadow' | 'live' })}>
            <option value="shadow">{t('先試跑(只看不點,之後到部署改正式)')}</option><option value="live">{t('直接正式執行(和其他台一樣)')}</option>
          </select></label>
        {!(pol.kinds ?? []).length && <div className="text-xs text-amber-700">{t('都沒勾 = 使用者不能自己選來源(由導入顧問在「來源」頁設定)')}</div>}
      </div>
    </Card>
  )
}


function WidgetEditor({ w, info, onChange }: { w: PanelWidget; info: PanelDefinition; onChange: (fn: (w: PanelWidget) => void) => void }) {
  const flag = (k: string, label: string, help?: string) => (
    <label className="flex items-center gap-1.5" title={help}><input type="checkbox" checked={!!w[k]} onChange={e => onChange(x => { x[k] = e.target.checked })} />{label}</label>)
  const ids = (k: string) => (w[k] as string[] | undefined) ?? []
  const pick = (k: string, id: string, on: boolean) => onChange(x => { const cur = (x[k] as string[] | undefined) ?? []; x[k] = on ? [...cur, id] : cur.filter(y => y !== id) })
  const limit = <label className="flex items-center gap-1">{t('最多顯示')}<input type="number" min={1} max={200} className={`${input} w-20`} value={Number(w.limit ?? 10)}
    onChange={e => onChange(x => { x.limit = Number(e.target.value) || 1 })} />{t('筆')}</label>
  switch (w.kind) {
    case 'devices': return <div className="flex flex-wrap gap-4">
      <span className="text-stone-600">{t('每台的狀態,另外顯示:')}</span>
      {flag('show_step', t('目前這一步'), t('例如「等待 55 分鐘 · 還剩 12:30」'))}{flag('show_alerts', t('最近的提醒'))}{flag('show_image', t('即時小畫面'), t('每 3 秒更新一次'))}
    </div>
    case 'incidents': return <div className="flex flex-wrap items-center gap-4">{limit}{flag('show_frames', t('顯示發生當下的畫面'))}</div>
    case 'deploy': return <div className="flex flex-col gap-2">
      <div className="flex flex-wrap gap-3"><span className="text-stone-600">{t('使用者可以切換的主腳本:')}</span>
        {info.main_scripts.map(s => <label key={s.id} className="flex items-center gap-1"><input type="checkbox" checked={ids('scripts').includes(s.id)} onChange={e => pick('scripts', s.id, e.target.checked)} />{s.name}</label>)}</div>
      <div className="flex flex-wrap gap-3"><span className="text-stone-600">{t('可以選的方式:')}</span>
        {Object.entries(info.modes).map(([m, tx]) => <label key={m} className="flex items-center gap-1"><input type="checkbox" checked={ids('modes').includes(m)} onChange={e => pick('modes', m, e.target.checked)} />{tx}</label>)}</div>
      <span className="text-xs text-stone-500">{t('使用者只能在勾選的方式之間切換;改了會存成主腳本的新版本,和「執行 › 部署」一樣。')}</span>
    </div>
    case 'schedules': return <div className="flex flex-wrap gap-3">
      <span className="text-stone-600">{t('顯示哪些排程:')}</span>
      {info.schedules.map(s => <label key={s.id} className="flex items-center gap-1"><input type="checkbox" checked={ids('schedules').includes(s.id)} onChange={e => pick('schedules', s.id, e.target.checked)} />{s.name}</label>)}
      <span className="text-xs text-stone-500">{ids('schedules').length ? '' : t('都沒勾 = 所有開著的排程')}</span>
    </div>
    case 'list': return <div className="flex flex-col gap-2">
      <label className="flex items-center gap-2"><span className="text-stone-600">{t('顯示哪一份清單')}</span>
        <select className={input} value={String(w.list ?? '')} onChange={e => onChange(x => { x.list = e.target.value })}>
          <option value="">{t('(請選擇)')}</option>
          {info.lists.map(l => <option key={l.id} value={l.id}>{l.title}{l.per_device ? t('(每台各自)') : ''}</option>)}
        </select></label>
      <label className="flex items-center gap-2"><span className="text-stone-600">{t('掃描按鈕執行的子腳本')}</span>
        <select className={input} value={String(w.scan_sub ?? '')} onChange={e => onChange(x => { x.scan_sub = e.target.value })}>
          <option value="">{t('(不放掃描按鈕)')}</option>
          {info.runnable_subs.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
        </select></label>
      <div className="flex flex-wrap gap-4">{flag('rename', t('使用者可以改名稱'), t('掃描存下的是名字的圖片,預設名稱是「項目 3」這類,讓使用者取好認的名字'))}
        {flag('remove', t('使用者可以移除'), t('刪掉或改名的項目:掃描時會標「沒看到」,先不輪到它;使用者確認後移除'))}</div>
      <span className="text-xs text-stone-500">{t('每台(或共用)一份:上次掃描的結果、每個名字的圖片,新的標「新」、這次沒看到的標「沒看到」。')}</span>
    </div>
    case 'values': return <div className="flex flex-col gap-2">
      <div className="flex flex-wrap gap-3"><span className="text-stone-600">{t('顯示哪些變數:')}</span>
        {info.variables.map(v => <label key={v.name} className="flex items-center gap-1"><input type="checkbox" checked={ids('vars').includes(v.name)} onChange={e => pick('vars', v.name, e.target.checked)} />{v.label}</label>)}</div>
      {!info.variables.length && <span className="text-xs text-amber-700">{t('方案包還沒有變數(在主腳本的「變數」新增)')}</span>}
      <span className="text-xs text-stone-500">{t('每台各自的變數列成一張表,全部共用的只顯示一個值;看起來像時間的數字會顯示成時間。')}</span>
    </div>
    case 'log': return <div className="flex flex-wrap items-center gap-4">{limit}{flag('panel_changes', t('也列出使用者在面板上的修改'))}
      <span className="text-xs text-stone-500">{t('紀錄包含:排程開始/結束、緊急規則、失敗與提醒')}</span></div>
    case 'chat': return <div className="flex flex-col gap-2">
      <div className="flex flex-wrap gap-4">
        {flag('setup', t('可以新增 Bot、換 Token、移除'), t('使用者自己建 Discord / Telegram Bot 貼上 Token'))}
        {flag('pair', t('可以配對、移除可以下指令的人'))}
      </div>
      <span className="text-xs text-stone-500">{t('Bot 存在執行的這台電腦(和「執行 › 通知」同一份);配對過的人在聊天裡能做的,就是這個面板開放的(見下方「聊天裡可以做的事」)。')}</span>
    </div>
    default: return null
  }
}

const PARAM_TYPE: Record<string, string> = { point: t('位置'), number: t('數字'), text: t('文字'), list: t('清單') }

function ControlEditor({ c, info, open, onOpen, onChange, onMove, onDelete, first, last, header }: {
  c: Ctl; info: PanelDefinition; open: boolean; onOpen: () => void; onChange: (fn: (c: Ctl) => void) => void
  onMove?: (d: number) => void; onDelete?: () => void; first?: boolean; last?: boolean; header?: boolean
}) {
  const b = c.bind
  const sched = info.schedules.find(s => s.id === b.schedule)
  const entry = info.entries.find(e => e.script === b.script && e.situation === b.situation)
  const params = b.kind === 'schedule_arg' ? sched?.params ?? [] : b.kind === 'entry_arg' ? entry?.params ?? [] : []
  const param = params.find(x => x.name === b.param)
  // the control's type follows what it is wired to
  const suggest = (kind: string, field?: string, pm?: { type: string; item?: string | null; from_list?: string | null }) => (x: Ctl) => {
    if (kind.startsWith('act_')) { x.type = 'action'; x.scope = x.scope ?? 'device'; delete x.options; delete x.unit; delete x.scale; delete x.min; delete x.max }
    else if (kind === 'schedule') { x.type = field === 'at' ? 'time' : 'toggle'; x.scope = 'global' }
    else if (kind === 'schedule_device') { x.type = 'toggle'; x.scope = 'device' }
    else if (pm) {
      delete x.options; delete x.unit; delete x.scale; delete x.min; delete x.max
      if (pm.type === 'number') { x.type = 'number'; x.unit = ''; x.scale = 1 }
      else if (pm.type === 'list') { x.type = 'multi'; x.options = pm.from_list ? `list:${pm.from_list}` : [] }
      else if (pm.type === 'point') { x.type = 'single'; x.options = [] }
      else x.type = 'single'
    }
  }
  const setting = b.kind === 'setting' ? info.settings.find(s => s.id === b.setting) : undefined
  const fromSetting = (s: SettingDecl | undefined) => (x: Ctl) => {
    if (!s) return
    delete x.options; delete x.unit; delete x.scale; delete x.min; delete x.max
    x.scope = s.scope === 'device' ? 'device' : 'global'
    x.type = ({ number: 'number', bool: 'toggle', time: 'time', point: 'single', list: 'multi' } as Record<string, PanelControl['type']>)[s.type] ?? 'single'
    if (s.pick_from) x.options = s.pick_from as PanelControl['options']
    if (s.type === 'number') { x.unit = ''; x.scale = 1 }
    if (!x.label || x.label === t('新的控制項') || x.label === '新的控制項') x.label = s.label
  }
  const where = b.kind === 'setting' ? (setting ? t('使用者設定「{label}」', { label: setting.label }) : t('請選擇使用者設定'))
    : b.kind === 'schedule' ? b.field === 'at' ? t('排程「{name}」的開始時間', { name: sched?.name ?? b.schedule }) : t('排程「{name}」的開關', { name: sched?.name ?? b.schedule })
    : b.kind === 'schedule_device' ? t('這台要不要參加排程「{p1}」', { p1: sched?.name ?? b.schedule })
    : b.kind === 'schedule_arg' ? t('排程「{p1}」的參數「{p2}」', { p1: sched?.name ?? b.schedule, p2: param?.label ?? b.param })
    : b.kind === 'entry_arg' ? t('「{p1}」{p2} 的參數「{p3}」', { p1: entry?.script_name ?? b.script, p2: entry?.situation_name ?? '', p3: param?.label ?? b.param })
    : b.kind === 'act_schedule' ? t('按下就立即執行排程「{p1}」', { p1: sched?.name ?? b.schedule })
    : b.kind === 'act_sub' ? t('按下就執行子腳本「{p1}」', { p1: info.runnable_subs.find(s => s.id === b.sub)?.name ?? b.sub })
    : b.kind === 'act_situation' ? (() => { const sc = info.scripts.find(y => y.id === b.script); return t('按下就讓「{p1}」切到「{p2}」', { p1: sc?.name ?? b.script, p2: sc?.situations.find(y => y.id === b.situation)?.name ?? String(b.situation ?? '') }) })()
    : b.kind === 'act_stop' ? t('按下就停止這台正在做的事') : t('還沒設定')
  return (
    <div className={`rounded-md border ${open ? 'border-stone-400' : 'border-stone-200'} ${header ? 'bg-amber-50/50' : 'bg-white'}`}>
      <div className="flex items-center gap-2 px-3 py-2">
        <button className="flex-1 text-left" onClick={onOpen}>
          <span className="font-medium">{c.label}</span>
          <span className="text-xs text-stone-500 ml-2">{info.types[c.type]} · {c.scope === 'device' ? t('每台各自') : t('全部共用')} {t('· 接到 {where}', { where })}</span>
          {header && <span className="text-[10px] ml-2 px-1 rounded bg-amber-200 text-amber-900">{t('標題旁的大開關')}</span>}
        </button>
        {onMove && <><Button variant="ghost" disabled={first} onClick={() => onMove(-1)}>▲</Button><Button variant="ghost" disabled={last} onClick={() => onMove(1)}>▼</Button></>}
        {onDelete && <Button variant="ghost" onClick={() => { if (confirm(t('刪除「{label}」?', { label: c.label }))) onDelete() }}>✕</Button>}
      </div>
      {open && (
        <div className="px-3 pb-3 flex flex-col gap-2 border-t border-stone-100 pt-2 text-sm">
          <div className="flex flex-wrap gap-2">
            <label className="flex items-center gap-1">{t('名稱')}<input className={`${input} w-48`} value={c.label} onChange={e => onChange(x => { x.label = e.target.value })} /></label>
            <label className="flex items-center gap-1 flex-1 min-w-64">{t('說明')}<input className={`${input} flex-1`} placeholder={t('給使用者看的一句話(可不填)')} value={c.help ?? ''} onChange={e => onChange(x => { x.help = e.target.value || undefined })} /></label>
          </div>
          {b.kind !== 'act_stop' && <div className="flex flex-wrap items-center gap-2">
            <label className="flex items-center gap-1" title={t('在 Discord / Telegram 裡打的名稱;不填 = 用名稱(重複時前面加區塊名稱)')}>{t('聊天名稱')}
              <input className={`${input} w-48`} placeholder={t('(用名稱)')} disabled={!!c.chat_off} value={c.chat ?? ''} onChange={e => onChange(x => { x.chat = e.target.value || undefined })} /></label>
            <label className="flex items-center gap-1 text-xs"><input type="checkbox" checked={!!c.chat_off} onChange={e => onChange(x => { x.chat_off = e.target.checked || undefined })} />{t('只放在頁面,聊天裡不能用')}</label>
          </div>}
          {c.scope === 'device' && sourceIds(info.devices).length > 1 && <div className="flex flex-wrap items-center gap-2"
            title={t('例如溫室的按鈕只放在溫室攝影機那一列;都不勾 = 每一台')}>
            <span className="text-stone-600">{t('只給這幾台')}</span>
            {sourceIds(info.devices).map(n => <label key={n} className="flex items-center gap-1 text-xs">
              <input type="checkbox" checked={(c.devices ?? []).includes(n)} onChange={e => onChange(x => {
                const v = (x.devices ?? []).filter(d => d !== n).concat(e.target.checked ? [n] : [])
                x.devices = v.length ? v : undefined
              })} />{n}</label>)}
            {!c.devices?.length && <span className="text-xs text-stone-500">{t('(每一台)')}</span>}
          </div>}
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-stone-600">{t('接到')}</span>
            <select className={input} value={b.kind} onChange={e => onChange(x => {
              const k = e.target.value
              if (k === 'setting') { x.bind = { kind: k, setting: info.settings[0]?.id }; fromSetting(info.settings[0])(x); return }
              if (k === 'act_sub') { x.bind = { kind: k, sub: info.runnable_subs[0]?.id }; suggest(k)(x); return }
              x.bind = k === 'act_stop' ? { kind: k }
                : k === 'act_situation' ? { kind: k, script: info.scripts[0]?.id, situation: info.scripts[0]?.situations[1]?.id ?? info.scripts[0]?.situations[0]?.id }
                : k === 'entry_arg' ? { kind: k, script: info.entries[0]?.script, situation: info.entries[0]?.situation, param: info.entries[0]?.params[0]?.name }
                : { kind: k, schedule: info.schedules[0]?.id, ...(k === 'schedule' ? { field: 'enabled' } : k === 'schedule_arg' ? { param: info.schedules[0]?.params[0]?.name } : {}) }
              const pm = k === 'entry_arg' ? info.entries[0]?.params[0] : k === 'schedule_arg' ? info.schedules[0]?.params[0] : undefined
              suggest(k, 'enabled', pm)(x)
            })}>
              {Object.entries(info.binds).map(([k, tx]) => <option key={k} value={k}>{tx}</option>)}
            </select>
            {b.kind === 'setting' && <>
              <select className={input} value={String(b.setting ?? '')} onChange={e => onChange(x => { x.bind.setting = e.target.value; fromSetting(info.settings.find(s => s.id === e.target.value))(x) })}>
                {!info.settings.length && <option value="">{t('(先到「素材庫 › 使用者設定」新增)')}</option>}
                {info.settings.map(s => <option key={s.id} value={s.id}>{s.label}</option>)}
              </select>
              <span className="text-xs text-stone-500">{t('種類、每台或共用、可選項目都跟著使用者設定')}</span>
            </>}
            {b.kind === 'act_situation' && <select className={input} value={`${b.script}|${b.situation}`} onChange={e => onChange(x => {
              const [sc, si] = e.target.value.split('|'); x.bind.script = sc; x.bind.situation = si })}>
              {info.scripts.flatMap(sc => sc.situations.map(si => <option key={`${sc.id}|${si.id}`} value={`${sc.id}|${si.id}`}>{sc.name} › {si.name}</option>))}
            </select>}
            {c.type === 'action' && <select className={input} value={c.scope ?? 'device'} onChange={e => onChange(x => { x.scope = e.target.value as 'global' | 'device' })}>
              <option value="device">{t('每台一顆按鈕')}</option><option value="global">{t('一顆按鈕,所有{device}一起', { device: words.device })}</option></select>}
            {b.kind === 'act_sub' && <select className={input} value={String(b.sub ?? '')} onChange={e => onChange(x => { x.bind.sub = e.target.value })}>
              {!info.runnable_subs.length && <option value="">{t('(沒有不需要參數的子腳本)')}</option>}
              {info.runnable_subs.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select>}
            {b.kind !== 'entry_arg' && b.kind !== 'act_situation' && b.kind !== 'act_stop' && b.kind !== 'setting' && b.kind !== 'act_sub' && <select className={input} value={String(b.schedule ?? '')} onChange={e => onChange(x => {
              x.bind.schedule = e.target.value
              if (x.bind.kind === 'schedule_arg') { const s = info.schedules.find(y => y.id === e.target.value); x.bind.param = s?.params[0]?.name; suggest('schedule_arg', undefined, s?.params[0])(x) }
            })}>
              {info.schedules.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select>}
            {b.kind === 'schedule' && <select className={input} value={String(b.field)} onChange={e => onChange(x => { x.bind.field = e.target.value; suggest('schedule', e.target.value)(x) })}>
              <option value="enabled">{t('開關')}</option><option value="at">{t('開始時間')}</option></select>}
            {b.kind === 'entry_arg' && <select className={input} value={`${b.script}|${b.situation}`} onChange={e => onChange(x => {
              const [sc, si] = e.target.value.split('|'); const en = info.entries.find(y => y.script === sc && y.situation === si)
              x.bind.script = sc; x.bind.situation = si; x.bind.param = en?.params[0]?.name; suggest('entry_arg', undefined, en?.params[0])(x)
            })}>
              {info.entries.map(en => <option key={`${en.script}|${en.situation}`} value={`${en.script}|${en.situation}`}>{en.script_name} › {en.situation_name}</option>)}
            </select>}
            {(b.kind === 'schedule_arg' || b.kind === 'entry_arg') && <select className={input} value={String(b.param ?? '')} onChange={e => onChange(x => {
              x.bind.param = e.target.value; suggest(b.kind, undefined, params.find(y => y.name === e.target.value))(x)
            })}>
              {params.map(pm => <option key={pm.name} value={pm.name}>{t('{name}({n})', { name: pm.label, n: PARAM_TYPE[pm.type] ?? pm.type })}</option>)}
            </select>}
            {b.kind === 'schedule_arg' && <label className="flex items-center gap-1">
              <select className={input} value={c.scope ?? 'global'} onChange={e => onChange(x => { x.scope = e.target.value as 'global' | 'device' })}>
                <option value="device">{t('每台各自設定')}</option><option value="global">{t('全部機台共用')}</option></select></label>}
          </div>
          {c.type === 'number' && (
            <div className="flex flex-wrap items-center gap-2">
              <label className="flex items-center gap-1">{t('單位')}<input className={`${input} w-20`} value={c.unit ?? ''} onChange={e => onChange(x => { x.unit = e.target.value })} /></label>
              <label className="flex items-center gap-1" title={t('使用者填的數字 × 這個 = 實際存的值,例如使用者填分鐘、參數要秒,就填 60')}>{t('換算 ×')}<input type="number" className={`${input} w-20`} value={c.scale ?? 1} onChange={e => onChange(x => { x.scale = Number(e.target.value) || 1 })} /></label>
              <label className="flex items-center gap-1">{t('最小')}<input type="number" className={`${input} w-20`} value={c.min ?? ''} onChange={e => onChange(x => { x.min = e.target.value === '' ? undefined : Number(e.target.value) })} /></label>
              <label className="flex items-center gap-1">{t('最大')}<input type="number" className={`${input} w-20`} value={c.max ?? ''} onChange={e => onChange(x => { x.max = e.target.value === '' ? undefined : Number(e.target.value) })} /></label>
            </div>
          )}
          {(c.type === 'single' || c.type === 'multi') && b.kind !== 'setting' && (
            <div className="flex flex-col gap-1">
              <label className="flex items-center gap-2">{t('選項來源')}
                <select className={input} value={typeof c.options === 'string' ? c.options : 'custom'} onChange={e => onChange(x => { x.options = e.target.value === 'custom' ? [] : e.target.value as PanelControl['options'] })}>
                  {info.lists.map(l => <option key={l.id} value={`list:${l.id}`}>{t('清單:{title}', { title: l.title })}{l.per_device ? t('(這台的)') : t('(全部)')}</option>)}
                  <option value="custom">{t('自己列出選項')}</option></select></label>
              {c.type === 'multi' && <label className="flex items-center gap-1">{t('至少選')}<input type="number" className={`${input} w-16`} value={c.min ?? 0} onChange={e => onChange(x => { x.min = Number(e.target.value) || undefined })} />{t('個')}</label>}
              {typeof c.options !== 'string' && (
                <div className="flex flex-col gap-1 pl-3 border-l-2 border-stone-200">
                  {((c.options as { label: string; value: unknown }[]) ?? []).map((o, i) => (
                    <div key={i} className="flex items-center gap-2">
                      <input className={`${input} w-48`} placeholder={t('使用者看到的名稱')} value={o.label} onChange={e => onChange(x => { (x.options as { label: string }[])[i].label = e.target.value })} />
                      <select className={input} value={String((o.value as { button?: string })?.button ?? '')} onChange={e => onChange(x => { (x.options as { value: unknown }[])[i].value = { button: e.target.value } })}>
                        <option value="">{t('(選按鈕庫裡的位置)')}</option>
                        {info.buttons.filter(bt => !info.lists.find(l => l.id === bt.list)?.per_device).map(bt => <option key={bt.id} value={bt.id}>{bt.label}</option>)}
                      </select>
                      <Button variant="ghost" onClick={() => onChange(x => { (x.options as unknown[]).splice(i, 1) })}>✕</Button>
                    </div>
                  ))}
                  <button className="self-start text-xs underline" onClick={() => onChange(x => { x.options = [...((x.options as unknown[]) ?? []), { label: '', value: null }] as never })}>{t('+ 加一個選項')}</button>
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

/** What a paired person can type to the chat bot with this design: the panel, nothing more. */
function ChatPreview({ panel }: { panel: Panel }) {
  const [data, setData] = useState<PanelChatPreview | null>(null)
  const key = JSON.stringify(panel)
  useEffect(() => {
    const tx = setTimeout(() => { api.panelChatPreview(panel).then(setData).catch(() => setData(null)) }, 400)
    return () => clearTimeout(tx)
  }, [key])                                          // eslint-disable-line react-hooks/exhaustive-deps
  const word: Record<string, string> = { toggle: t('開/關'), time: t('時間'), number: t('數字'), single: t('選一個'), multi: t('選幾個'), action: t('按鈕') }
  return (
    <Card title={t('聊天裡可以做的事')} extra={<span className="text-xs text-stone-500">{t('配對過的人在 Discord / Telegram 能做的 = 這個面板開放的,再加上停下來、暫停、繼續這些安全指令')}</span>}>
      {!data ? <Empty>{t('讀取中…')}</Empty> : <div className="flex flex-col gap-2 text-sm">
        <ErrorText error={data.error} />
        <div className="text-xs text-stone-600">{t('一定有:選單 · 狀態 · 畫面 <機台> · 停下來 · 暫停 · 繼續(一台、#標籤或全部)')}
          {data.widgets.length > 0 && <> {t('· 看:{p1}', { p1: data.widgets.join(' · ') })}</>}</div>
        {data.commands.length === 0 ? <Empty>{t('面板上還沒有可以在聊天裡用的設定或按鈕')}</Empty> :
          <div className="grid md:grid-cols-2 gap-x-6 gap-y-0.5">
            {data.commands.map(c => <div key={c.control} className="flex gap-2">
              <code className="text-xs bg-stone-100 rounded px-1">{c.name}{c.scope === 'device' ? t(' [機台]') : ''}</code>
              <span className="text-xs text-stone-500">{word[c.type] ?? c.type}{c.type === 'action' ? t('(會先問確認)') : t('(打名稱看值,加新的值就改,會先問確認)')}</span>
            </div>)}
          </div>}
      </div>}
    </Card>
  )
}

function AccessCard() {
  const qc = useQueryClient()
  const me = useQuery({ queryKey: ['authMe'], queryFn: api.authMe })
  const [userPin, setUserPin] = useState('')
  const [adminPin, setAdminPin] = useState('')
  const save = useMutation({ mutationFn: (b: { user_pin?: string; admin_pin?: string }) => api.authPins(b),
    onSuccess: () => { setUserPin(''); setAdminPin(''); qc.invalidateQueries({ queryKey: ['authMe'] }) } })
  const c = me.data?.configured
  return (
    <Card title={t('手機連線與登入')}>
      <div className="flex flex-col gap-2 text-sm">
        <div>{me.data?.lan
          ? <>{t('同一個網路的手機打開')} <b className="select-all">{me.data.lan}</b>{t(',輸入使用者 PIN 碼就能用操作面板。')}</>
          : <>{t('目前只有這台電腦能用。要讓手機也能連,請用')} <code className="bg-stone-100 px-1 rounded">python -m server --lan</code> {t('啟動介面(先設定下面的 PIN 碼)。')}</>}</div>
        <div className="text-xs text-stone-500">{t('這台電腦本身不用登入。從其他裝置連進來:使用者 PIN 只能進操作面板;顧問 PIN 可以進全部的管理介面。')}</div>
        <div className="flex flex-wrap items-center gap-3">
          <label className="flex items-center gap-1">{t('使用者 PIN')} <input className={`${input} w-28`} inputMode="numeric" placeholder={c?.user ? t('已設定(改才填)') : t('4~8 位數字')} value={userPin} onChange={e => setUserPin(e.target.value)} /></label>
          <label className="flex items-center gap-1">{t('顧問 PIN')} <input className={`${input} w-28`} inputMode="numeric" placeholder={c?.admin ? t('已設定(改才填)') : t('4~8 位數字')} value={adminPin} onChange={e => setAdminPin(e.target.value)} /></label>
          <Button disabled={(!userPin && !adminPin) || save.isPending} onClick={() => save.mutate({ ...(userPin ? { user_pin: userPin } : {}), ...(adminPin ? { admin_pin: adminPin } : {}) })}>{t('設定 PIN 碼')}</Button>
          {c?.user && <Button variant="ghost" onClick={() => { if (confirm(t('關閉使用者從手機登入?'))) save.mutate({ user_pin: '' }) }}>{t('關閉使用者登入')}</Button>}
          {c?.admin && <Button variant="ghost" onClick={() => { if (confirm(t('關閉顧問從其他裝置登入?'))) save.mutate({ admin_pin: '' }) }}>{t('關閉顧問登入')}</Button>}
        </div>
        <ErrorText error={save.error} />
      </div>
    </Card>
  )
}
