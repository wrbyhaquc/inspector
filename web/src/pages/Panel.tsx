import { locale, t } from '../i18n'
import { LangPicker } from '../components/LangPicker'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useState, type CSSProperties, type ReactNode } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { api, PREVIEW, type PanelBlock, type PanelCard, type PanelControl, type PanelInfo, type PanelOption, type PanelSourceRow, type PanelTodo, type WidgetData } from '../api'
import { usePersistentState } from '../lib/persist'
import { WidgetBlock } from './PanelWidgets'
import { PanelEditor } from './PanelEdit'
import { Drawer, Modal } from '../components/ui'
import { Icon } from '../components/Icon'
import { AskBar } from '../components/AskBar'
import { Btn, FIELD, Menu, MenuItem, Section, StatusBadge, Switch, Toast, type Notice } from '../components/panelUi'
import { words } from '../lib/project'
import { dn, useSourceNames } from '../lib/sources'

// The operation panel for end users: only the settings they understand, laid out like an ordinary web page.
// /panel shows the designer's pages (the first one starts with every emulator); /panel/device/<name> is one emulator;
// /panel/edit is the panel in edit mode (for whoever may design it); ?draft shows its draft as a preview.
const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b)
const DEVICE_PATH = '/panel/device/'
const EDIT_PATH = '/panel/edit'
const top = () => document.getElementById('panel-top')?.scrollIntoView({ block: 'start' })

/** "#0369a1" -> "3 105 161" (the --accent token); null for anything else */
const rgb = (hex?: string) => /^#[0-9a-f]{6}$/i.test(hex ?? '') ? [1, 3, 5].map(i => parseInt(hex!.slice(i, i + 2), 16)).join(' ') : null

/** A block's cell on a wide screen's 12-column grid (rows as tall as what is in them); a phone: one column in its
 * phone order. Inline variables, so the grid applies from lg up only. */
function cell(b: PanelBlock, order: number): CSSProperties {
  const p = b.place
  if (!p) return { '--gc': '1 / -1', order } as CSSProperties          // no place (an older server): a whole row, in order
  return { '--gc': `${p.x + 1} / span ${p.w}`, '--gr': `${p.y + 1} / span ${p.h ?? 1}`, order } as CSSProperties
}

/** The blocks of a page with their place in a phone's one column: its own order if it has one, else the wide screen's
 * (row by row, left to right); the ones with an order come first. */
function phoneOrder(blocks: PanelBlock[]): [PanelBlock, number][] {
  const wide = (b: PanelBlock) => (b.place?.y ?? 0) * 100 + (b.place?.x ?? 0)
  const sorted = [...blocks].sort((a, b) => ((a.phone?.order ?? Infinity) - (b.phone?.order ?? Infinity)) || wide(a) - wide(b))
  return blocks.map(b => [b, sorted.indexOf(b)])
}

/** Bigger text for whoever finds the page small: every size on the panel is in rem, so the root size scales it all. */
function useBigText(on: boolean) {
  useEffect(() => {
    if (!on) return
    const el = document.documentElement, prev = el.style.fontSize
    el.style.fontSize = '18px'
    return () => { el.style.fontSize = prev }
  }, [on])
}

export default function Panel({ canLogout = false, canEdit = false }: { canLogout?: boolean; canEdit?: boolean }) {
  const qc = useQueryClient()
  const loc = useLocation()
  // the draft being edited: in edit mode (its contents) and in its preview
  const draft = canEdit && (PREVIEW || loc.pathname === EDIT_PATH)
  const q = useQuery({ queryKey: ['panel', draft ? 'draft' : 'live'], queryFn: () => api.panel(draft), refetchInterval: 3000 })
  useSourceNames()
  const nav = useNavigate()
  const [msg, setMsg] = useState<Notice | null>(null)
  const closeMsg = useCallback(() => setMsg(null), [])
  const [open, setOpen] = useState<string | null>(null)              // "<block>|<device>" being edited
  const [showLog, setShowLog] = useState(false)
  const [pickOpen, setPickOpen] = useState(false)                     // the window to scan for and pick sources
  const [bell, setBell] = useState(false)                             // the notices drawer
  const [bigPick, setBig] = usePersistentState<boolean | null>('panel.big', null)     // null: as the designer set it
  const [view, setView] = usePersistentState<string>('panel.view', '')          // a page id
  const srcs = useQuery({ queryKey: ['panelSources'], queryFn: api.panelSources })
  const big = bigPick ?? !!q.data?.theme?.big_text
  useBigText(big)
  type Change = { control: string; device?: string; value: unknown; label: string; undo?: boolean }
  const set = useMutation({
    mutationFn: (b: Change) => api.panelSet({ control: b.control, device: b.device, value: b.value }),
    onSuccess: (r, b) => {     // saved: it can be put back to what it was (the server says what that was)
      setMsg(b.undo ? { ok: true, text: t('已復原:{label}', { label: b.label }) }
        : { ok: true, text: t('已儲存:{label}', { label: b.label }), undo: () => set.mutate({ ...b, value: r.old, undo: true }) })
      qc.invalidateQueries({ queryKey: ['panel'] })
    },
    onError: (e: Error) => setMsg({ ok: false, text: e.message }),
  })
  const pause = useMutation({ mutationFn: (p: 'stop' | 'pause' | 'resume') => (p === 'resume' ? api.panelResume() : api.panelPause(p)), onSuccess: () => qc.invalidateQueries({ queryKey: ['panel'] }) })
  const d = q.data
  if (!d) return <div className="min-h-full bg-stone-100 p-8 text-stone-600">{q.isLoading ? t('讀取中…') : t('連不上系統,請稍後再試或聯絡負責人')}</div>
  const byId = Object.fromEntries(d.controls.map(c => [c.id, c]))
  const change = (c: PanelControl, value: unknown, device?: string) => { setMsg(null); set.mutate({ control: c.id, device, value, label: c.label }) }
  const devChoices = (c: PanelControl, n: string) => (c.choices as Record<string, PanelOption[]>)?.[n] ?? []
  const stop = d.controls.find(x => x.bind?.kind === 'act_stop' && x.scope === 'device')
  const openDevice = (n: string) => { nav(DEVICE_PATH + encodeURIComponent(n)); top() }
  const shown = loc.pathname.startsWith(DEVICE_PATH) ? decodeURIComponent(loc.pathname.slice(DEVICE_PATH.length)) : null
  const card = shown ? d.cards.find(c => c.device === shown) : undefined

  const grid = (b?: PanelBlock) => <DeviceGrid cards={d.cards} data={b?.data} widget={b?.widget} stop={stop} onOpen={openDevice} onMsg={setMsg} />
  const blockFor = (b: PanelBlock) => b.widget?.kind === 'devices' && !b.error
    ? <Section title={b.title} help={b.help}>{grid(b)}</Section>
    : b.widget
      ? <WidgetBlock key={b.id} b={b} devices={d.devices} onMsg={m => setMsg(m)} />
      : <ControlBlock key={b.id} b={b} byId={byId} devices={d.devices} open={open} setOpen={setOpen} change={change} busy={set.isPending} onMsg={setMsg} />
  // the designer's pages (none = one page 總覽); a block on no page / an unknown one is on the first
  const pages = d.pages?.length ? d.pages : [{ id: 'all', title: t('總覽') }]
  const pageOf = (b: PanelBlock) => pages.some(p => p.id === b.page) ? b.page! : pages[0].id
  const tab = pages.some(p => p.id === view) ? view : pages[0].id
  const hasGrid = d.blocks.some(b => b.widget?.kind === 'devices' && !b.error)
  // 去看: an emulator's own page, or the page a block is on (and to the block)
  const go = (g: PanelTodo['go']) => {
    setBell(false)
    const b = g.block ? d.blocks.find(x => x.id === g.block) : undefined
    if (b && !(b.widget?.kind === 'list' && g.device)) {
      setView(pageOf(b)); nav('/panel')
      setTimeout(() => document.getElementById(`block-${b.id}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 50)
    } else if (g.device) openDevice(g.device)
  }
  const accent = rgb(d.theme?.accent) ? { '--accent': rgb(d.theme?.accent) } as CSSProperties : undefined
  if (canEdit && loc.pathname === EDIT_PATH) return (
    <div className="h-full" style={accent}>
      <PanelEditor live={d} render={blockFor} onDone={() => nav('/panel')} onMsg={setMsg} />
      <Toast msg={msg} onClose={closeMsg} />
    </div>
  )
  const stopAll = () => { if (window.confirm(t('確定全部停下來?每台都不會再自動做事,要恢復請按「全部繼續」。'))) pause.mutate('stop') }
  const todo = d.todo ?? []
  const bad = todo.filter(i => i.level === 'bad')

  return (
    <div id="panel-top" className="min-h-full bg-stone-100 text-stone-900 text-sm" style={accent}>
      {PREVIEW && draft && <div className="bg-amber-100 text-amber-900 text-xs text-center px-4 py-1.5">{t('草稿預覽:發佈後就是這個樣子;在這裡按了不會真的動作')}</div>}
      <header className="sticky top-0 z-20 bg-white border-b border-stone-200" style={{ paddingTop: 'env(safe-area-inset-top, 0px)' }}>
        <div className="max-w-screen-2xl mx-auto px-4 h-14 flex items-center gap-2 sm:gap-3">
          <h1 className="min-w-0 truncate"><button onClick={() => { nav('/panel'); top() }} className="block max-w-full truncate text-base font-semibold hover:text-accent">{d.title}</button></h1>
          <Summary cards={d.cards} />
          <span className="flex-1" />
          <button onClick={() => setBell(true)} title={t('通知')} aria-label={t('通知')}
            className="relative h-9 w-9 shrink-0 inline-flex items-center justify-center rounded-md border border-stone-300 bg-white hover:bg-stone-50">
            <Icon name="bell" className="w-4 h-4" />
            {todo.length > 0 && <span className={`absolute -top-1.5 -right-1.5 min-w-5 h-5 px-1 rounded-full text-[0.6875rem] font-semibold text-white flex items-center justify-center num ${bad.length ? 'bg-rose-600' : 'bg-amber-500'}`}>{todo.length}</span>}
          </button>
          {d.paused
            ? <Btn variant="primary" onClick={() => pause.mutate('resume')} disabled={pause.isPending}><Icon name="play" className="w-4 h-4" />{t('全部繼續')}</Btn>
            : <Menu label={<><Icon name="pause" className="w-4 h-4" />{t('全部')}</>}>
                {close => <>
                  <MenuItem icon={<Icon name="pause" className="w-4 h-4" />} help={t('腳本、情境和正在做的事都停在原地,按「繼續」從同一步接著做')}
                    onClick={() => { close(); pause.mutate('pause') }}>{t('全部暫停')}</MenuItem>
                  <MenuItem danger icon={<Icon name="stop" className="w-4 h-4" />} onClick={() => { close(); stopAll() }}>{t('全部停下來')}</MenuItem>
                </>}
              </Menu>}
          <Menu label={<Icon name="settings" className="w-4 h-4" />} title={t('設定')}>
            {close => <>
              {srcs.data?.can && <MenuItem icon={<Icon name="search" className="w-4 h-4" />} help={t('掃描這台電腦上的{device},選要讓它操作的', { device: words.device })}
                onClick={() => { close(); setPickOpen(true) }}>{t('選擇{device}', { device: words.device })}</MenuItem>}
              {canEdit && <MenuItem icon={<Icon name="edit" className="w-4 h-4" />} help={t('在面板上直接加區塊、拖拉排版、改設定')}
                onClick={() => { close(); nav(EDIT_PATH) }}>{t('編輯面板')}</MenuItem>}
              <div className="px-3 py-2 flex items-center justify-between gap-3 text-sm"><span className="text-stone-600">{t('大字模式')}</span><Switch on={big} label={t('大字模式')} onChange={setBig} /></div>
              <div className="px-3 py-2 flex items-center justify-between gap-3 text-sm"><span className="text-stone-600">{t('介面語言')}</span><LangPicker className="border-stone-300" /></div>
              {canLogout && <MenuItem onClick={() => api.authLogout().then(() => window.location.reload())}>{t('登出')}</MenuItem>}
            </>}
          </Menu>
        </div>
      </header>

      {d.paused && <Banner>{d.paused_mode === 'pause' ? t('目前全部暫停中,不會自動做任何事。要恢復請按右上角「全部繼續」。') : t('目前全部停下來中,不會自動做任何事。要恢復請按右上角「全部繼續」。')}</Banner>}
      {!d.running && <Banner>{t('系統目前沒有在運作,設定可以先改,但不會執行。請聯絡負責人。')}</Banner>}
      {bad.length > 0 && <Banner tone="red">
        <span className="flex-1 min-w-0 truncate">{bad[0].device && <span className="font-medium mr-2">{dn(bad[0].device)}</span>}{bad[0].text}</span>
        <Btn size="sm" onClick={() => go(bad[0].go)}>{t('去看')}<Icon name="go" className="w-3.5 h-3.5" /></Btn>
        {todo.length > 1 && <button className="shrink-0 text-[0.8125rem] underline" onClick={() => setBell(true)}>{t('還有 {length} 件', { length: todo.length - 1 })}</button>}
      </Banner>}

      <main className="max-w-screen-2xl mx-auto px-4 py-4 flex flex-col gap-4 min-w-0">
        <AskBar items={d.asks ?? []} big refresh={['panel']} />
        {srcs.data?.can && d.cards.length === 0 && <Section title={t('還沒有選擇要操作的{device}', { device: words.device })}>
          <div className="flex flex-col items-start gap-3">
            <div className="text-stone-600">{srcs.data.help || t('先開好{device},再按下面的按鈕掃描、勾選要使用的。', { device: words.device })}</div>
            <Btn variant="primary" onClick={() => setPickOpen(true)}><Icon name="search" className="w-4 h-4" />{t('掃描並選擇{device}', { device: words.device })}</Btn>
          </div>
        </Section>}
        <PickSources open={pickOpen} onClose={() => setPickOpen(false)} onMsg={setMsg} />

        {shown !== null
          ? card
            ? <DeviceView n={card.device} card={card} d={d} byId={byId} change={change} busy={set.isPending} onMsg={setMsg} onOpen={openDevice} onBack={() => nav('/panel')} />
            : <Section title={t('找不到「{p1}」', { p1: dn(shown) })}><Btn onClick={() => nav('/panel')}><Icon name="back" className="w-4 h-4" />{t('回總覽')}</Btn></Section>
          : <>
              <nav className="flex gap-1 border-b border-stone-200 overflow-x-auto">
                {pages.map(p => (
                  <button key={p.id} onClick={() => setView(p.id)} aria-current={tab === p.id ? 'page' : undefined}
                    className={`px-3 py-2.5 text-sm font-medium whitespace-nowrap -mb-px border-b-2 transition-colors ${tab === p.id ? 'border-accent text-stone-900' : 'border-transparent text-stone-500 hover:text-stone-800'}`}>{p.title}</button>
                ))}
              </nav>
              {!hasGrid && tab === pages[0].id && d.cards.length > 0 && <Section title={words.device}>{grid()}</Section>}
              <div className="flex flex-col lg:grid lg:grid-cols-12 gap-4 items-start" data-testid="panel-grid">
                {phoneOrder(d.blocks.filter(b => pageOf(b) === tab)).map(([b, order]) => <div key={b.id} id={`block-${b.id}`} data-place={JSON.stringify(b.place ?? null)}
                  style={cell(b, order)} className={`scroll-mt-20 min-w-0 w-full self-stretch lg:self-start lg:[grid-column:var(--gc)] lg:[grid-row:var(--gr)] ${b.phone?.hide ? 'hidden lg:block' : ''}`}>{blockFor(b)}</div>)}
              </div>
              {tab === pages[pages.length - 1].id && <History d={d} byId={byId} show={showLog} setShow={setShowLog} devChoices={devChoices} />}
            </>}
      </main>
      <Drawer open={bell} title={t('通知')} onClose={() => setBell(false)}>
        <TodoList items={todo} onGo={go} onMsg={setMsg} />
      </Drawer>
      <Toast msg={msg} onClose={closeMsg} />
    </div>
  )
}

/** Beside the title: how many there are and how many need someone, so it is seen before reading anything else. */
function Summary({ cards }: { cards: PanelCard[] }) {
  if (!cards.length) return null
  const n = (tone: string) => cards.filter(c => c.tone === tone).length
  const bad = n('red'), warn = n('amber')
  return (
    <span className="hidden sm:flex items-center gap-2 text-[0.8125rem] text-stone-500 whitespace-nowrap">
      <span className="w-px h-4 bg-stone-200" />
      {t('{count} 個{device}', { count: cards.length, device: words.device })}
      {bad > 0 && <StatusBadge tone="red">{t('{count} 要處理', { count: bad })}</StatusBadge>}
      {warn > 0 && <StatusBadge tone="amber">{t('{count} 注意', { count: warn })}</StatusBadge>}
      {!bad && !warn && <StatusBadge tone="green">{t('都正常')}</StatusBadge>}
    </span>
  )
}

/** A thin line under the header: a state that holds everything (all paused, the system not running), or the most
 * pressing thing to deal with. */
function Banner({ tone = 'amber', children }: { tone?: 'amber' | 'red'; children: ReactNode }) {
  return <div className={`border-b ${tone === 'red' ? 'bg-rose-50 border-rose-200 text-rose-900' : 'bg-amber-50 border-amber-200 text-amber-900'}`}>
    <div className="max-w-screen-2xl mx-auto px-4 py-2 flex items-center gap-2"><Icon name="alert" className="w-4 h-4 shrink-0" />{children}</div>
  </div>
}

/** Find the sources the pack allows on this computer and tick the ones to use (the others never show, nothing acts on
 * them). Unticking only turns one off: its name and settings stay for when it is ticked again. */
function PickSources({ open, onClose, onMsg }: { open: boolean; onClose: () => void; onMsg: (m: Notice) => void }) {
  const qc = useQueryClient()
  const info = useQuery({ queryKey: ['panelSources'], queryFn: api.panelSources, enabled: open })
  const scan = useMutation({ mutationFn: api.panelSourcesScan })
  const use = useMutation({
    mutationFn: (b: { kind: string; match: string; use: boolean; name?: string }) => api.panelSourcesUse(b),
    onSuccess: (_r, b) => { onMsg({ ok: true, text: b.use ? t('開始使用:{p1}', { p1: b.name || b.match }) : t('不再使用:{p1}', { p1: b.name || b.match }) })
      qc.invalidateQueries({ queryKey: ['panelSources'] }); qc.invalidateQueries({ queryKey: ['panel'] }); scan.mutate() },
    onError: (e: Error) => onMsg({ ok: false, text: e.message }),
  })
  useEffect(() => { if (open && !scan.data && !scan.isPending) scan.mutate() }, [open])  // eslint-disable-line react-hooks/exhaustive-deps
  const items = info.data?.items ?? []
  const on = (r: PanelSourceRow) => items.find(i => i.kind === r.kind && i.match === r.match)?.enabled ?? false
  const found = scan.data?.found ?? []
  // what each one shows now: pick by looking; one with no picture to take cannot be used (folded away unless in use)
  const peek = useQuery({ queryKey: ['panelSourcePeek', scan.data], queryFn: () => api.panelSourcesPeek(found.slice(0, 60)), enabled: open && found.length > 0,
    refetchInterval: open ? 2500 : false, placeholderData: p => p })
  const seen = (r: PanelSourceRow) => { const i = found.indexOf(r); return i >= 0 && i < 60 ? peek.data?.items[i] : undefined }
  const [showNone, setShowNone] = useState(false)
  const none = found.filter(r => !on(r) && !!peek.data && seen(r)?.state !== 'ok')
  const away = scan.data && !scan.isPending ? items.filter(i => i.enabled && !found.some(r => r.kind === i.kind && r.match === i.match)) : []
  return (
    <Modal open={open} wide title={t('選擇要操作的{device}', { device: words.device })} onClose={onClose}>
      <div className="flex flex-col gap-3">
        <div className="text-stone-600">{info.data?.help || t('先開好{device},再按「重新掃描」。', { device: words.device })}
          {info.data?.kinds?.length ? <span className="block text-xs text-stone-500 mt-1">{t('會找:{p1}', { p1: info.data.kinds.map(k => k.label).join(t('、')) })}</span> : null}</div>
        <div className="flex flex-wrap items-center gap-3">
          <Btn variant="primary" onClick={() => scan.mutate()} disabled={scan.isPending}><Icon name="search" className="w-4 h-4" />{scan.isPending ? t('掃描中…') : t('重新掃描')}</Btn>
          <span className="text-xs text-stone-500">{t('勾選的才會出現在面板、被腳本操作;沒勾的完全不會動到它')}</span>
        </div>
        {scan.error && <div className="text-rose-700">{(scan.error as Error).message}</div>}
        {Object.entries(scan.data?.errors ?? {}).map(([k, v]) => <div key={k} className="text-amber-800">{k}:{v}</div>)}
        {scan.data && found.length === 0 && <div className="text-stone-500">{t('沒有找到。確認{device}已經開好,再按「重新掃描」。', { device: words.device })}</div>}
        {found.filter(r => showNone || !none.includes(r)).map(r => {
          const u = on(r)
          const s = seen(r)
          return (
            <label key={`${r.kind}|${r.match}`} className={`rounded-lg border px-3 py-2.5 flex items-center gap-3 cursor-pointer ${u ? 'border-accent bg-accent/5' : 'border-stone-200 bg-white hover:bg-stone-50'}`}>
              <input type="checkbox" className="w-4 h-4" checked={u} disabled={use.isPending}
                onChange={e => use.mutate({ kind: r.kind, match: r.match, use: e.target.checked, name: r.name })} />
              <div className="relative w-32 sm:w-44 shrink-0 aspect-video rounded-md bg-stone-900 overflow-hidden">
                {s?.image && <img src={s.image} alt="" className="absolute inset-0 w-full h-full object-contain" />}
                {s?.state !== 'ok' && <span className="absolute inset-0 flex items-center justify-center text-xs text-stone-300 text-center px-1">
                  {!s ? t('取得畫面中…') : s.state === 'blank' ? t('全黑或單色') : t('沒有畫面')}</span>}
              </div>
              <div className="flex-1 min-w-0">
                <div className="font-medium">{dn(items.find(i => i.kind === r.kind && i.match === r.match)?.id ?? r.name)}</div>
                <div className="text-xs text-stone-500">{r.kind_label}{r.detail ? ` · ${r.detail}` : ''}</div>
                {r.warn && <div className="text-xs text-amber-800">{r.warn}</div>}
              </div>
              <span className={`text-xs font-medium ${u ? 'text-accent' : 'text-stone-400'}`}>{u ? t('使用中') : t('不使用')}</span>
            </label>
          )
        })}
        {none.length > 0 && <button className="self-start text-xs underline text-stone-500" onClick={() => setShowNone(v => !v)}>
          {showNone ? t('收起沒有畫面的') : t('另外 {length} 個沒有畫面可抓(縮到最小、隱藏或全黑),用不了;要用的話先把它打開', { length: none.length })}</button>}
        {away.length > 0 && <div className="flex flex-col gap-2">
          <div className="text-stone-600">{t('使用中、但這次沒找到(可能沒開):')}</div>
          {away.map(i => (
            <div key={i.id} className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 flex items-center gap-3">
              <div className="flex-1 min-w-0"><span className="font-medium">{dn(i.id)}</span><span className="ml-2 text-xs text-stone-500">{i.kind_label}</span></div>
              <Btn size="sm" disabled={use.isPending} onClick={() => use.mutate({ kind: i.kind, match: i.match, use: false, name: i.name })}>{t('不再使用')}</Btn>
            </div>
          ))}
        </div>}
      </div>
    </Modal>
  )
}

const clockIn = (s: number) => new Date(Date.now() + s * 1000).toLocaleTimeString(locale, { hour: '2-digit', minute: '2-digit', hour12: false })
const span = (s: number) => s >= 3600 ? `${Math.floor(s / 3600)}:${String(Math.floor(s / 60) % 60).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`
  : `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`

/** Every emulator as a card: a small live picture (if the designer allowed it), how it is, what it is doing and how far,
 * and its main button. Clicking a card opens that emulator's own page. The designer's 裝置狀態 widget shows as this,
 * with its options (the step it is on, its last alerts, the picture). */
function DeviceGrid({ cards, data, widget, stop, onOpen, onMsg }: {
  cards: PanelCard[]; data?: WidgetData; widget?: PanelBlock['widget']; stop?: PanelControl; onOpen: (n: string) => void; onMsg: (m: Notice) => void
}) {
  const [tick, setTick] = useState(0)
  const extra = Object.fromEntries((data?.devices ?? []).map(x => [x.device, x]))
  const pictures = Object.values(extra).some(x => x.image)
  useEffect(() => { if (!pictures) return; const tx = setInterval(() => setTick(x => x + 1), 3000); return () => clearInterval(tx) }, [pictures])
  return (
    <div className="grid gap-3 grid-cols-[repeat(auto-fill,minmax(15rem,1fr))]">
      {cards.map(c => <DeviceCard key={c.device} c={c} more={extra[c.device]} step={widget?.show_step !== false} alerts={!!widget?.show_alerts}
        tick={tick} stop={stop} onOpen={() => onOpen(c.device)} onMsg={onMsg} />)}
    </div>
  )
}

function DeviceCard({ c, more, step, alerts, tick, stop, onOpen, onMsg }: {
  c: PanelCard; more?: NonNullable<WidgetData['devices']>[number]; step: boolean; alerts: boolean; tick: number
  stop?: PanelControl; onOpen: () => void; onMsg: (m: Notice) => void
}) {
  const p = c.progress
  const frac = p?.i && p.n ? Math.min(1, ((p.i - 1) + (p.wait_total ? 1 - (p.wait_left ?? 0) / p.wait_total : 0)) / p.n) : null
  const edge = c.tone === 'red' ? 'border-rose-300' : c.tone === 'amber' ? 'border-amber-300' : 'border-stone-200'
  return (
    <div role="link" tabIndex={0} onClick={onOpen} onKeyDown={e => { if (e.key === 'Enter') onOpen() }}
      className={`cursor-pointer rounded-lg bg-white border overflow-hidden flex flex-col hover:border-stone-400 hover:shadow-sm transition ${edge}`}>
      {more?.image && <div className="aspect-video bg-stone-900">
        <img src={`/api/panel/live/${encodeURIComponent(c.device)}?v=${tick}`} alt={t('{p1} 現在的畫面', { p1: dn(c.device) })}
          className="w-full h-full object-contain" onError={e => { (e.target as HTMLImageElement).style.visibility = 'hidden' }} />
      </div>}
      <div className="px-3 py-2.5 flex flex-col gap-1.5 flex-1">
        <div className="flex items-center gap-2">
          <span className="flex-1 min-w-0 font-medium break-words leading-tight">{dn(c.device)}</span>
          <StatusBadge tone={c.tone}>{c.label ?? ''}</StatusBadge>
        </div>
        {p?.name
          ? <>
              <div className="text-[0.8125rem] text-stone-700 truncate">{p.name}{p.i && p.n ? ` ${p.i}/${p.n}` : ''}{p.paused ? t('(暫停中)') : ''}</div>
              {p.say && <div className="text-xs text-stone-500 truncate">{p.say}</div>}
              {frac !== null && <div className="h-1.5 rounded-full bg-stone-100 overflow-hidden"><div className="h-full bg-accent" style={{ width: `${Math.round(frac * 100)}%` }} /></div>}
              {(p.wait_left != null || p.eta != null) && <div className="text-xs text-stone-500 flex items-center gap-1"><Icon name="clock" className="w-3.5 h-3.5" />
                {p.wait_left != null ? t('這個還剩 {p1}', { p1: span(p.wait_left) }) : ''}{p.wait_left != null && p.eta != null ? ' · ' : ''}{p.eta != null ? t('約 {p1} 完成', { p1: clockIn(p.eta) }) : ''}</div>}
            </>
          : <div className="text-[0.8125rem] text-stone-500 line-clamp-2">{c.now}</div>}
        {step && more?.step && <div className="text-xs text-stone-500 truncate">{t('目前這一步:{step}', { step: more.step })}</div>}
        {alerts && c.alerts.length > 0 && <div className="text-xs text-stone-500 flex flex-col">{c.alerts.map((a, i) => <span key={i} className="truncate">
          <span className="text-stone-400 mr-1 num">{new Date(a.t * 1000).toLocaleTimeString(locale, { hour: '2-digit', minute: '2-digit' })}</span>{a.text}</span>)}</div>}
        <span className="flex-1" />
        {stop && <div className="flex justify-end pt-1" onClick={e => e.stopPropagation()}><ActionButton c={stop} device={c.device} onMsg={onMsg} small /></div>}
      </div>
    </div>
  )
}

/** The notices (the bell): the most pressing first, each with where to go; an event (a failed schedule, a stuck
 * screen) is put away with 知道了, a state (stopped by a rule, no picture, names not seen) goes once it is over. */
function TodoList({ items, onGo, onMsg }: { items: PanelTodo[]; onGo: (g: PanelTodo['go']) => void; onMsg: (m: Notice) => void }) {
  const qc = useQueryClient()
  const [pic, setPic] = useState<string | null>(null)
  const ack = useMutation({ mutationFn: (keys: string[]) => api.panelTodoAck(keys), onSuccess: () => qc.invalidateQueries({ queryKey: ['panel'] }),
    onError: (e: Error) => onMsg({ ok: false, text: e.message }) })
  if (!items.length) return <div className="text-sm text-stone-500 py-10 text-center">{t('沒有要處理的事')}</div>
  const events = items.filter(i => i.ack).map(i => i.key)
  return (
    <div className="flex flex-col gap-3 text-sm">
      <div className="flex items-center gap-3">
        <span className="flex-1 text-stone-600">{t('{length} 件事要處理', { length: items.length })}</span>
        {events.length > 1 && <Btn variant="ghost" size="sm" disabled={ack.isPending}
          onClick={() => { if (confirm(t('把 {length} 件「知道了」就好的事都收起來?(被停下來、看不到畫面這類,要處理好才會消失)', { length: events.length }))) ack.mutate(events) }}>{t('全部知道了')}</Btn>}
      </div>
      <div className="bg-white rounded-lg border border-stone-200 divide-y divide-stone-100">
        {items.map(i => (
          <div key={i.key} className="px-4 py-3 flex flex-col gap-2">
            <div className="flex items-start gap-3">
              <span className={`mt-1.5 w-2 h-2 rounded-full shrink-0 ${i.level === 'bad' ? 'bg-rose-500' : 'bg-amber-500'}`} />
              <div className="flex-1 min-w-0">
                <div>{i.device && <span className="font-medium mr-2">{dn(i.device)}</span>}{i.text}</div>
                {i.detail && <div className="text-xs text-stone-500">{i.detail}</div>}
                {i.t && <div className="text-xs text-stone-400 num">{new Date(i.t * 1000).toLocaleString(locale, { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' })}</div>}
              </div>
              {i.frame && <button onClick={() => setPic(i.frame!)} title={t('看當時的畫面')}>
                <img src={`/api/panel/stuck_frame?frame=${encodeURIComponent(i.frame)}`} alt="" className="h-12 rounded border border-stone-200" /></button>}
            </div>
            <div className="flex gap-2 pl-5">
              <Btn size="sm" onClick={() => onGo(i.go)}>{t('去看')}<Icon name="go" className="w-3.5 h-3.5" /></Btn>
              {i.ack && <Btn size="sm" variant="ghost" disabled={ack.isPending} onClick={() => ack.mutate([i.key])}>{t('知道了')}</Btn>}
            </div>
          </div>
        ))}
      </div>
      <Modal open={!!pic} wide title={t('卡住時的畫面')} onClose={() => setPic(null)}>
        {pic && <img src={`/api/panel/stuck_frame?frame=${encodeURIComponent(pic)}`} alt="" className="w-full rounded" />}
      </Modal>
    </div>
  )
}

/** Is a per-emulator control (or button) for this emulator? (the server lists the ones it is for in "targets") */
const forDev = (c: PanelControl, n: string) => !c.targets || c.targets.includes(n)
type Doing = { name?: string; loop?: string | null; paused?: boolean }
const doingOf = (c: PanelControl, n: string) => ((c.value as Record<string, Doing | null>) ?? {})[n]
const doingText = (x: Doing) => t('正在進行:{name}{p2}', { name: x.name ?? '', p2: x.loop ? `(${x.loop.split(' ').pop()})` : '' })

/** A block of controls: the shared ones, then each emulator's (one line each, opened to change). */
function ControlBlock({ b, byId, devices, open, setOpen, change, busy, onMsg }: {
  b: PanelBlock; byId: Record<string, PanelControl>; devices: string[]; open: string | null; setOpen: (k: string | null) => void
  change: (c: PanelControl, v: unknown, device?: string) => void; busy: boolean; onMsg: (m: Notice) => void
}) {
  const devValue = (c: PanelControl, n: string) => (c.value as Record<string, unknown>)?.[n]
  const devChoices = (c: PanelControl, n: string) => (c.choices as Record<string, PanelOption[]>)?.[n] ?? []
  const tg = b.toggle ? byId[b.toggle] : undefined
  const off = tg && tg.value === false
  const items = b.items.map(i => byId[i]).filter(Boolean)
  const globals = items.filter(c => c.scope !== 'device' && c.type !== 'action')
  const globalActs = items.filter(c => c.scope !== 'device' && c.type === 'action')
  const perDev = items.filter(c => c.scope === 'device' && c.type !== 'action')
  const devActs = items.filter(c => c.scope === 'device' && c.type === 'action')
  const rowDevs = devices.filter(n => [...perDev, ...devActs].some(c => forDev(c, n)))     // the emulators this block is for
  return (
    <Section title={b.title} help={b.help} extra={tg && <Switch on={tg.value === true} busy={busy} label={tg.label} onChange={v => change(tg, v)} />}>
      {off && <div className="text-[0.8125rem] text-stone-500 mb-3">{t('目前關閉:時間到也不會執行。下面的設定可以先改好。')}</div>}
      <div className={`flex flex-col gap-4 ${off ? 'opacity-60' : ''}`}>
        {globals.length > 0 && <div className="flex flex-col divide-y divide-stone-100 -my-2">
          {globals.map(c => <div key={c.id} className="py-2.5"><Control c={c} value={c.value} choices={(c.choices as PanelOption[]) ?? []} onChange={v => change(c, v)} busy={busy} /></div>)}
        </div>}
        {globalActs.length > 0 && <div className="flex flex-wrap gap-2">{globalActs.map(c => <ActionButton key={c.id} c={c} onMsg={onMsg} />)}</div>}
        {(perDev.length > 0 || devActs.length > 0) && <DeviceTable devices={rowDevs} perDev={perDev} devActs={devActs} change={change} busy={busy} onMsg={onMsg} />}
        {rowDevs.length > 0 && <div className="lg:hidden rounded-md border border-stone-200 divide-y divide-stone-100">
          {rowDevs.map(n => {
            const mine = perDev.filter(c => forDev(c, n))
            const key = `${b.id}|${n}`
            const isOpen = open === key
            const doing = devActs.length ? doingOf(devActs[0], n) : null
            return (
              <div key={n}>
                <div className="px-3 py-2.5 flex flex-wrap items-center gap-3">
                  <button onClick={() => mine.length && setOpen(isOpen ? null : key)} className="flex-1 min-w-48 text-left flex items-center gap-3">
                    <span className="shrink-0 font-medium">{dn(n)}</span>
                    <span className="flex-1 text-stone-500 text-[0.8125rem]">{mine.length ? summary(mine, c => devValue(c, n), c => devChoices(c, n)) : ''}
                      {doing?.name && <span className="block text-accent">{doingText(doing)}{doing.paused ? t(' · 暫停中') : ''}</span>}</span>
                    {mine.length > 0 && <span className="shrink-0 text-[0.8125rem] text-accent">{isOpen ? t('收起 ▴') : t('改設定 ▾')}</span>}
                  </button>
                  {devActs.map(c => <ActionButton key={c.id} c={c} device={n} onMsg={onMsg} small />)}
                </div>
                {isOpen && <div className="px-3 pb-3 flex flex-col divide-y divide-stone-100 bg-stone-50/60">
                  {mine.map(c => <div key={c.id} className="py-2.5"><Control c={c} value={devValue(c, n)} choices={devChoices(c, n)} onChange={v => change(c, v, n)} busy={busy} /></div>)}
                </div>}
              </div>
            )
          })}
        </div>}
      </div>
    </Section>
  )
}

/** A wide screen: the settings each emulator has as a table - a row per emulator, a column per setting - so they are
 * compared and changed at a glance. A list to tick (which characters, in order) opens in a window. */
function DeviceTable({ devices, perDev, devActs, change, busy, onMsg }: {
  devices: string[]; perDev: PanelControl[]; devActs: PanelControl[]
  change: (c: PanelControl, v: unknown, device?: string) => void; busy: boolean; onMsg: (m: Notice) => void
}) {
  const [edit, setEdit] = useState<{ c: PanelControl; n: string } | null>(null)
  const devValue = (c: PanelControl, n: string) => (c.value as Record<string, unknown>)?.[n]
  const devChoices = (c: PanelControl, n: string) => (c.choices as Record<string, PanelOption[]>)?.[n] ?? []
  const join = perDev.find(c => c.type === 'toggle' && c.bind?.kind === 'schedule_device')
  return (
    <div className="hidden lg:block overflow-x-auto rounded-md border border-stone-200">
      <table className="w-full text-sm border-collapse">
        <thead><tr className="text-left text-xs text-stone-500 bg-stone-50 border-b border-stone-200">
          <th className="py-2 px-3 font-medium">{words.device}</th>
          {perDev.map(c => <th key={c.id} className="py-2 px-3 font-medium" title={c.help}>{c.label}{c.unit ? `(${c.unit})` : ''}</th>)}
          {devActs.length > 0 && <th className="py-2 px-3 font-medium">{t('動作')}</th>}
        </tr></thead>
        <tbody className="divide-y divide-stone-100">{devices.map(n => {
          const out = join && devValue(join, n) === false          // not taking part: its other settings matter less
          const doing = devActs.length ? doingOf(devActs[0], n) : null
          return (
            <tr key={n} className="align-middle hover:bg-stone-50/60">
              <td className="py-2 px-3"><span className="font-medium">{dn(n)}</span>
                {doing?.name && <div className="text-xs text-accent">{doingText(doing)}</div>}</td>
              {perDev.map(c => (
                <td key={c.id} className={`py-2 px-3 ${out && c !== join ? 'opacity-40' : ''}`}>
                  {forDev(c, n) ? <Cell c={c} value={devValue(c, n)} choices={devChoices(c, n)} busy={busy} onChange={v => change(c, v, n)} onOpen={() => setEdit({ c, n })} />
                    : <span className="text-stone-300">—</span>}
                </td>
              ))}
              {devActs.length > 0 && <td className="py-2 px-3"><div className="flex flex-wrap gap-2">{devActs.map(c => <ActionButton key={c.id} c={c} device={n} onMsg={onMsg} small />)}</div></td>}
            </tr>
          )
        })}</tbody>
      </table>
      <Modal open={!!edit} wide title={edit ? `${dn(edit.n)}:${edit.c.label}` : ''} onClose={() => setEdit(null)}>
        {edit && <Control c={edit.c} value={devValue(edit.c, edit.n)} choices={devChoices(edit.c, edit.n)} onChange={v => change(edit.c, v, edit.n)} busy={busy} />}
      </Modal>
    </div>
  )
}

/** One setting in a table cell: small, changed in place (a list to tick: its summary, opened in a window). */
function Cell({ c, value, choices, busy, onChange, onOpen }: {
  c: PanelControl; value: unknown; choices: PanelOption[]; busy: boolean; onChange: (v: unknown) => void; onOpen: () => void
}) {
  const [num, setNum] = useState<string | null>(null)
  if (c.error) return <span className="text-rose-700" title={c.error}>{t('無法顯示')}</span>
  if (c.type === 'toggle') return <Switch on={value === true} busy={busy} label={c.label} onChange={onChange} />
  if (c.type === 'time') return <input type="time" disabled={busy} value={String(value ?? '')} onChange={e => e.target.value && onChange(e.target.value)} className={FIELD} />
  if (c.type === 'number') {
    const cur = Number(value ?? 0)
    return <input type="number" disabled={busy} value={num ?? String(cur)} min={c.min ?? undefined} max={c.max ?? undefined}
      onChange={e => setNum(e.target.value)} title={t('改完按 Enter 或點別處就會儲存')}
      onBlur={() => { if (num !== null && num !== String(cur) && num.trim() !== '') onChange(Number(num)); setNum(null) }}
      onKeyDown={e => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur() }}
      className={`${FIELD} w-24 text-center num`} />
  }
  if (c.type === 'single') return (
    <select disabled={busy} value={choices.findIndex(o => same(o.value, value))} onChange={e => onChange(choices[Number(e.target.value)]?.value)} className={`${FIELD} max-w-48`}>
      {choices.findIndex(o => same(o.value, value)) < 0 && <option value={-1}>{t('(請選擇)')}</option>}
      {choices.map((o, i) => <option key={i} value={i}>{o.label}</option>)}
    </select>
  )
  const chosen = (Array.isArray(value) ? value : []) as unknown[]
  const names = chosen.map(x => choices.find(o => same(o.value, x))?.label ?? '?')
  return <button onClick={onOpen} title={names.join(' → ') || t('(沒有)')} className={`${FIELD} text-left max-w-72 truncate hover:bg-stone-50`}>
    <span className="font-medium">{t('{length} 個', { length: chosen.length })}</span><span className="text-stone-500">{names.length ? `:${names.slice(0, 3).join(t('、'))}${names.length > 3 ? '…' : ''}` : ''}</span>
    <span className="ml-1 text-accent">✎</span></button>
}

/** Everything about one emulator in one place: how it is, what can be done on it, its own settings and lists. */
function DeviceView({ n, card, d, byId, change, busy, onMsg, onOpen, onBack }: {
  n: string; card: PanelCard; d: PanelInfo; byId: Record<string, PanelControl>
  change: (c: PanelControl, v: unknown, device?: string) => void; busy: boolean; onMsg: (m: Notice) => void
  onOpen: (n: string) => void; onBack: () => void
}) {
  const [tick, setTick] = useState(0)
  const picture = card.online && d.blocks.some(b => b.widget?.kind === 'devices' && b.widget.show_image)   // the designer allowed pictures
  useEffect(() => { if (!picture) return; const tx = setInterval(() => setTick(x => x + 1), 3000); return () => clearInterval(tx) }, [picture])
  const devValue = (c: PanelControl) => (c.value as Record<string, unknown>)?.[n]
  const devChoices = (c: PanelControl) => (c.choices as Record<string, PanelOption[]>)?.[n] ?? []
  const acts = d.blocks.flatMap(b => b.widget ? [] : b.items.map(i => byId[i]).filter(c => c && c.scope === 'device' && c.type === 'action'))
  const doing = acts.length ? doingOf(acts[0], n) : null
  const blocks = d.blocks.filter(b => !b.widget && b.items.some(i => byId[i]?.scope === 'device' && byId[i]?.type !== 'action' && forDev(byId[i], n)))
  const lists = d.blocks.filter(b => b.widget?.kind === 'list' && b.data?.by_device?.[n])
  return (
    <div className="grid xl:grid-cols-2 gap-4 items-start">
      <div className="xl:col-span-2 flex flex-wrap items-center gap-2 text-sm">
        <button onClick={onBack} className="inline-flex items-center gap-1 text-stone-600 hover:text-accent"><Icon name="back" className="w-4 h-4" />{t('總覽')}</button>
        <span className="text-stone-300">/</span>
        <select value={n} onChange={e => onOpen(e.target.value)} aria-label={words.device} className={`${FIELD} font-medium`}>
          {d.cards.map(c => <option key={c.device} value={c.device}>{dn(c.device)}</option>)}
        </select>
      </div>
      <Section className={`xl:col-span-2 ${card.tone === 'red' ? 'border-rose-200' : card.tone === 'amber' ? 'border-amber-200' : ''}`}>
        <div className="flex flex-col md:flex-row gap-4">
        {picture && <div className="md:w-96 shrink-0 aspect-video rounded-md bg-stone-900 overflow-hidden">
          <img src={`/api/panel/live/${encodeURIComponent(n)}?v=${tick}`} alt={t('{p1} 現在的畫面', { p1: dn(n) })}
            className="w-full h-full object-contain" onError={e => { (e.target as HTMLImageElement).style.visibility = 'hidden' }} />
        </div>}
        <div className="flex flex-col gap-3 flex-1 min-w-0">
          <div className="flex flex-wrap items-center gap-3">
            <h2 className="text-lg font-semibold">{dn(n)}</h2>
            <StatusBadge tone={card.tone}>{card.label ?? ''}</StatusBadge>
            <span className="text-stone-600">{card.now}</span>
          </div>
          {doing?.name && <div className="text-accent">{doingText(doing)}{doing.paused ? t(' · 暫停中') : ''}</div>}
          {card.today.length > 0 && <div className="text-stone-600">{t('今天:{p1}', { p1: card.today.map(tx => `${tx.name} ${tx.text}`).join(' · ') })}</div>}
          {acts.length > 0 && <div className="flex flex-wrap gap-2">{acts.map(c => <ActionButton key={c.id} c={c} device={n} onMsg={onMsg} />)}</div>}
          {card.alerts.length > 0 && <div className="text-[0.8125rem] flex flex-col gap-0.5 text-stone-600 border-t border-stone-100 pt-2">
            {card.alerts.map((a, i) => <div key={i}><span className="text-stone-400 mr-2 num">{new Date(a.t * 1000).toLocaleTimeString(locale, { hour: '2-digit', minute: '2-digit' })}</span>{a.text}</div>)}</div>}
        </div>
        </div>
      </Section>
      {blocks.map(b => {
        const tg = b.toggle ? byId[b.toggle] : undefined
        const own = b.items.map(i => byId[i]).filter(c => c && c.scope === 'device' && c.type !== 'action' && forDev(c, n))
        return (
          <Section key={b.id} title={b.title} help={tg && tg.value === false ? t('這個排程目前關閉(到「總覽」打開):設定可以先改好。') : undefined}>
            <div className="flex flex-col divide-y divide-stone-100 -my-2">
              {own.map(c => <div key={c.id} className="py-2.5"><Control c={c} value={devValue(c)} choices={devChoices(c)} onChange={v => change(c, v, n)} busy={busy} /></div>)}
            </div>
          </Section>
        )
      })}
      {lists.map(b => <div key={b.id} className="xl:col-span-2"><WidgetBlock b={b} devices={d.devices} onMsg={onMsg} device={n} /></div>)}
    </div>
  )
}

function History({ d, byId, show: open, setShow, devChoices }: {
  d: PanelInfo; byId: Record<string, PanelControl>; show: boolean; setShow: (f: (v: boolean) => boolean) => void
  devChoices: (c: PanelControl, n: string) => PanelOption[]
}) {
  return (
    <section className="bg-white rounded-lg border border-stone-200 shadow-sm">
      <button onClick={() => setShow(v => !v)} aria-expanded={open} className="w-full text-left px-4 py-3 text-[0.9375rem] font-semibold flex items-center gap-2">
        <span className="flex-1">{t('最近的修改')}</span><span className="text-stone-400 text-xs">{open ? '▴' : '▾'}</span></button>
      {open && <div className="px-4 pb-3 pt-2 border-t border-stone-100 flex flex-col gap-1">{d.history.length === 0 ? <div className="text-stone-500">{t('還沒有修改紀錄')}</div> : d.history.map((h, i) => {
        const c = byId[h.control]
        const ch = c ? (c.scope === 'device' ? devChoices(c, h.device ?? '') : (c.choices as PanelOption[]) ?? []) : []
        return <div key={i} className="text-stone-700">
          <span className="text-stone-400 mr-2 num">{new Date(h.t * 1000).toLocaleString(locale, { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' })}</span>
          {h.device && <span className="mr-1">{dn(h.device)}</span>}{h.action
            ? <>{t('按下「{label}」{p2}', { label: h.label, p2: h.result ? `:${Object.entries(h.result).map(([k, v]) => h.device ? v : `${k} ${v}`).join(t('、'))}` : '' })}</>
            : <>「{h.label}」:{show(c, h.old, ch)} → <b className="font-medium">{show(c, h.new, ch)}</b></>}
        </div>
      })}</div>}
    </section>
  )
}

/** One line per emulator: "這台不跑" or "9 個項目 · 20 分鐘 · 做完切回 A01". */
function summary(cs: PanelControl[], val: (c: PanelControl) => unknown, choices: (c: PanelControl) => PanelOption[]): string {
  const join = cs.find(c => c.type === 'toggle' && c.bind?.kind === 'schedule_device')
  if (join && val(join) === false) return t('這台不跑')
  return cs.filter(c => c !== join).map(c => {
    const v = val(c)
    if (c.type === 'multi') return t('{label} {p2} 個', { label: c.label, p2: Array.isArray(v) ? v.length : 0 })
    if (c.type === 'toggle') return t('{p1}:{p2}', { p1: c.label, p2: v ? t('開') : t('關') })
    if (c.type === 'single') return `${c.label} ${show(c, v, choices(c))}`
    return show(c, v, choices(c))
  }).join(' · ')
}

function show(c: PanelControl | undefined, v: unknown, choices: PanelOption[]): string {
  if (v === true) return t('開')
  if (v === false) return t('關')
  if (v == null) return '—'
  if (Array.isArray(v)) return v.map(x => choices.find(o => same(o.value, x))?.label ?? '?').join(t('、')) || t('(沒有)')
  if (typeof v === 'object') return choices.find(o => same(o.value, v))?.label ?? '?'
  return `${v}${c?.unit ?? ''}`
}

/** One setting as a form row: what it is on the left, the control on the right (a list to tick: under it). */
function Control({ c, value, choices, onChange, busy }: { c: PanelControl; value: unknown; choices: PanelOption[]; onChange: (v: unknown) => void; busy: boolean }) {
  const [num, setNum] = useState<string | null>(null)
  if (c.error) return <div className="text-rose-700">{t('「{label}」無法顯示:{error}', { label: c.label, error: c.error })}</div>
  const head = <div className="min-w-0"><div className="font-medium text-stone-900">{c.label}</div>{c.help && <div className="text-[0.8125rem] text-stone-500">{c.help}</div>}</div>
  const row = (control: ReactNode) => <div className="flex items-center justify-between gap-4 flex-wrap">{head}<div className="shrink-0">{control}</div></div>
  if (c.type === 'toggle') return row(<Switch on={value === true} busy={busy} label={c.label} onChange={onChange} />)
  if (c.type === 'time') return row(<input type="time" disabled={busy} value={String(value ?? '')} onChange={e => e.target.value && onChange(e.target.value)} className={FIELD} />)
  if (c.type === 'number') {
    const cur = Number(value ?? 0)
    const step = (dlt: number) => onChange(Math.min(c.max ?? 1e9, Math.max(c.min ?? -1e9, cur + dlt)))
    return row(
      <div className="flex items-center gap-2">
        <div className="inline-flex items-stretch h-9 rounded-md border border-stone-300 bg-white overflow-hidden focus-within:ring-2 focus-within:ring-accent/30 focus-within:border-accent">
          <button disabled={busy} onClick={() => step(-5)} aria-label="-5" className="w-9 text-stone-600 hover:bg-stone-50 disabled:opacity-40 border-r border-stone-200">−</button>
          <input type="number" value={num ?? String(cur)} onChange={e => setNum(e.target.value)}
            onBlur={() => { if (num !== null && num !== String(cur)) onChange(Number(num)); setNum(null) }}
            onKeyDown={e => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur() }}
            className="w-16 text-sm text-center num focus:outline-none" />
          <button disabled={busy} onClick={() => step(5)} aria-label="+5" className="w-9 text-stone-600 hover:bg-stone-50 disabled:opacity-40 border-l border-stone-200">+</button>
        </div>
        {c.unit && <span className="text-stone-500">{c.unit}</span>}
      </div>)
  }
  if (c.type === 'single') return row(
    <select disabled={busy} value={choices.findIndex(o => same(o.value, value))} onChange={e => onChange(choices[Number(e.target.value)]?.value)} className={`${FIELD} max-w-full`}>
      {choices.findIndex(o => same(o.value, value)) < 0 && <option value={-1}>{t('(請選擇)')}</option>}
      {choices.map((o, i) => <option key={i} value={i}>{o.label}</option>)}
    </select>)
  // multi: tick in order
  const chosen = (Array.isArray(value) ? value : []) as unknown[]
  const at = (o: PanelOption) => chosen.findIndex(x => same(x, o.value))
  return (
    <div className="flex flex-col gap-2">{head}
      <div className="flex flex-wrap gap-1.5">
        {choices.map((o, i) => {
          const k = at(o)
          return (
            <button key={i} disabled={busy} onClick={() => onChange(k >= 0 ? chosen.filter((_, j) => j !== k) : [...chosen, o.value])} aria-pressed={k >= 0}
              className={`h-8 px-2.5 rounded-md border text-[0.8125rem] inline-flex items-center gap-1 transition-colors disabled:opacity-50 ${k >= 0 ? 'bg-accent/10 text-accent border-accent/60 font-medium' : 'bg-white text-stone-700 border-stone-300 hover:bg-stone-50'}`}>
              {k >= 0 && <span className="num text-[0.6875rem] w-4 h-4 rounded-full bg-accent text-white inline-flex items-center justify-center">{k + 1}</span>}{o.label}
            </button>
          )
        })}
      </div>
      {chosen.length > 0 && <div className="text-xs text-stone-500">{t('順序:{p1}(取消再點一次可以排到最後)', { p1: chosen.map(x => choices.find(o => same(o.value, x))?.label ?? '?').join(' → ') })}</div>}
    </div>
  )
}

/** A button that does something now (run a schedule, back to the spot, stop). Asks before acting; if the emulator
 * is busy with something else, asks whether to interrupt it or wait for it. */
function ActionButton({ c, device, onMsg, small = false }: { c: PanelControl; device?: string; onMsg: (m: Notice) => void; small?: boolean }) {
  const qc = useQueryClient()
  const [ask, setAsk] = useState<Record<string, { name?: string; loop?: string | null }> | null>(null)
  const kind = c.bind?.kind
  const doing = (c.value as Record<string, { name?: string; held?: boolean } | null>) ?? {}
  const who = device ? [device] : c.targets ?? []
  const isStop = kind === 'act_stop'
  const held = isStop && who.length > 0 && who.every(n => doing[n]?.held)       // 停下來 pressed before: now it says 繼續
  const press = useMutation({
    mutationFn: (if_busy: 'ask' | 'interrupt' | 'queue') => api.panelAct({ control: c.id, device, if_busy, resume: held }),
    onSuccess: r => {
      if (Object.keys(r.busy).length) { setAsk(r.busy); return }
      setAsk(null)
      const errs = Object.entries(r.errors ?? {})
      onMsg(errs.length ? { ok: false, text: t('「{label}」:{errors}', { label: c.label, errors: errs.map(([k, v]) => `${k} ${v}`).join(t('、')) }) }
        : { ok: true, text: held ? t('{who} 恢復自動了', { who: device ?? t('全部') }) : isStop ? t('{who} 已停下來,不會再自動做事;要恢復按「繼續」', { who: device ?? t('全部') })
          : device ? t('已經送出「{label}」給 {device},過一下就會開始', { label: c.label, device }) : t('已經送出「{label}」,過一下就會開始', { label: c.label }) })
      qc.invalidateQueries({ queryKey: ['panel'] })
    },
    onError: (e: Error) => onMsg({ ok: false, text: e.message }),
  })
  const go = () => {
    const where = device ? dn(device) : (who.length ? who.map(dn).join(t('、')) : t('所有{device}', { device: words.device }))
    if (!held && !isStop && !window.confirm(t('確定要讓 {where} 現在「{label}」嗎?', { where, label: c.label }))) return
    press.mutate('ask')
  }
  if (device && c.targets && !c.targets.includes(device)) return null      // this emulator does not take part
  return (
    <div className="flex flex-col gap-2">
      <Btn onClick={go} disabled={press.isPending} title={held ? t('恢復自動') : c.help} size={small ? 'sm' : 'md'} variant={held ? 'primary' : isStop ? 'danger' : small ? 'secondary' : 'primary'}>
        {press.isPending ? t('送出中…') : held ? <><Icon name="play" className="w-3.5 h-3.5" />{t('繼續')}</> : c.label}</Btn>
      {ask && (
        <div className="rounded-md border border-amber-200 bg-amber-50 p-3 text-[0.8125rem] flex flex-col gap-2 max-w-md">
          <div>{Object.entries(ask).map(([n, x]) => t('{n} 正在做「{p2}」{p3}', { n, p2: x.name ?? '', p3: x.loop ? `(${x.loop.split(' ').pop()})` : '' })).join(t(';'))}</div>
          <div>{t('要怎麼辦?')}</div>
          <div className="flex flex-wrap gap-2">
            <Btn size="sm" variant="dangerSolid" onClick={() => press.mutate('interrupt')}>{t('停掉它,改做這個')}</Btn>
            <Btn size="sm" onClick={() => press.mutate('queue')}>{t('等它做完再做')}</Btn>
            <Btn size="sm" variant="ghost" onClick={() => setAsk(null)}>{t('算了')}</Btn>
          </div>
        </div>
      )}
    </div>
  )
}
