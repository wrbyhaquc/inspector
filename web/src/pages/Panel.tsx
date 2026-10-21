import { locale, t } from '../i18n'
import { LangPicker } from '../components/LangPicker'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { api, type PanelBlock, type PanelCard, type PanelControl, type PanelInfo, type PanelOption, type PanelSourceRow, type PanelTodo } from '../api'
import { usePersistentState } from '../lib/persist'
import { WidgetBlock } from './PanelWidgets'
import { Modal } from '../components/ui'
import { Icon } from '../components/Icon'
import { AskBar } from '../components/AskBar'
import { words } from '../lib/project'
import { dn, useSourceNames } from '../lib/sources'

// The operation panel for end users: only the settings they understand, big and plain.
const DOT: Record<string, string> = { green: 'bg-emerald-500', blue: 'bg-sky-500 animate-pulse', amber: 'bg-amber-500', grey: 'bg-stone-400', red: 'bg-rose-500' }
// the emulator cards: a coloured edge and a short word (正常 / 進行中 / 注意 / 要處理 / 已停止), the card itself stays white
const EDGE: Record<string, string> = { green: 'border-l-emerald-500', blue: 'border-l-sky-500', amber: 'border-l-amber-500', red: 'border-l-rose-600', grey: 'border-l-stone-400' }
const CHIP: Record<string, string> = { green: 'bg-emerald-100 text-emerald-800', blue: 'bg-sky-100 text-sky-800', amber: 'bg-amber-100 text-amber-900',
  red: 'bg-rose-600 text-white', grey: 'bg-stone-200 text-stone-700' }
const LEGEND: [string, string][] = [['green', t('正常')], ['blue', t('進行中')], ['amber', t('注意')], ['red', t('要處理')], ['grey', t('已停止')]]
const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b)

export default function Panel({ canLogout = false }: { canLogout?: boolean }) {
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['panel'], queryFn: api.panel, refetchInterval: 3000 })
  useSourceNames()
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null)
  const [open, setOpen] = useState<string | null>(null)              // "<block>|<device>" being edited
  const [showLog, setShowLog] = useState(false)
  const [pickOpen, setPickOpen] = useState(false)                     // the window to scan for and pick sources
  const srcs = useQuery({ queryKey: ['panelSources'], queryFn: api.panelSources })
  const [view, setView] = usePersistentState<string>('panel.view', '')          // a page id, or 'device' (這台)
  const [cur, setCur] = usePersistentState('panel.device', '')
  const set = useMutation({
    mutationFn: (b: { control: string; device?: string; value: unknown; label: string }) => api.panelSet(b),
    onSuccess: (_r, b) => { setMsg({ ok: true, text: t('已儲存:{label}', { label: b.label }) }); qc.invalidateQueries({ queryKey: ['panel'] }) },
    onError: (e: Error) => setMsg({ ok: false, text: e.message }),
  })
  const pause = useMutation({ mutationFn: (p: 'stop' | 'pause' | 'resume') => (p === 'resume' ? api.panelResume() : api.panelPause(p)), onSuccess: () => qc.invalidateQueries({ queryKey: ['panel'] }) })
  const d = q.data
  if (!d) return <div className="p-8 text-xl text-stone-600">{q.isLoading ? t('讀取中…') : t('連不上系統,請稍後再試或聯絡負責人')}</div>
  const byId = Object.fromEntries(d.controls.map(c => [c.id, c]))
  const change = (c: PanelControl, value: unknown, device?: string) => { setMsg(null); set.mutate({ control: c.id, device, value, label: c.label }) }
  const devChoices = (c: PanelControl, n: string) => (c.choices as Record<string, PanelOption[]>)?.[n] ?? []

  const blockFor = (b: PanelBlock) => b.widget
    ? <WidgetBlock key={b.id} b={b} devices={d.devices} onMsg={m => setMsg(m)} />
    : <ControlBlock key={b.id} b={b} byId={byId} devices={d.devices} open={open} setOpen={setOpen} change={change} busy={set.isPending} onMsg={setMsg} />
  const card = d.cards.find(c => c.device === cur)
  const pickDevice = (n: string) => { setCur(n); setView('device') }
  // the designer's pages (none = one page 總覽); a block on no page / an unknown one is on the first
  const pages = d.pages?.length ? d.pages : [{ id: 'all', title: t('總覽') }]
  const pageOf = (b: PanelBlock) => pages.some(p => p.id === b.page) ? b.page! : pages[0].id
  const tab = view === 'device' || pages.some(p => p.id === view) ? view : pages[0].id
  // 去看: an emulator's 這台 view, or the page a block is on (and to the block)
  const go = (g: PanelTodo['go']) => {
    const b = g.block ? d.blocks.find(x => x.id === g.block) : undefined
    if (b && !(b.widget?.kind === 'list' && g.device)) {
      setView(pageOf(b))
      setTimeout(() => document.getElementById(`block-${b.id}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 50)
    } else if (g.device) { setCur(g.device); setView('device'); window.scrollTo({ top: 0, behavior: 'smooth' }) }
  }

  return (
    <div className="min-h-full bg-stone-50 text-stone-900 text-lg">
      <header className="sticky top-0 z-10 bg-white border-b border-stone-200 px-4 py-3 flex flex-wrap items-center gap-3">
        <h1 className="text-2xl font-bold">{d.title}</h1>
        <span className="flex-1" />
        <LangPicker className="text-base border-stone-300" />
        {canLogout && <button onClick={() => api.authLogout().then(() => window.location.reload())} className="text-base text-stone-500 underline">{t('登出')}</button>}
        {srcs.data?.can && <button onClick={() => setPickOpen(true)} className="px-4 py-2.5 rounded-xl border-2 border-stone-300 bg-white text-lg font-bold flex items-center gap-2"
          title={t('掃描這台電腦上的{device},選要讓它操作的', { device: words.device })}><Icon name="search" />{t('選擇{device}', { device: words.device })}</button>}
        {d.paused
          ? <button onClick={() => pause.mutate('resume')} className="px-5 py-2.5 rounded-xl bg-emerald-600 text-white text-xl font-bold flex items-center gap-2"><Icon name="play" />{t('全部繼續')}</button>
          : <>
              <button onClick={() => pause.mutate('pause')} className="px-4 py-2.5 rounded-xl bg-amber-500 text-white text-xl font-bold flex items-center gap-2" title={t('腳本、情境和正在做的事都停在原地,按「繼續」從同一步接著做')}><Icon name="pause" />{t('全部暫停')}</button>
              <button onClick={() => { if (confirm(t('全部停下來?正在做的事會取消,腳本和情境都停住、什麼都不會自動做。按「全部繼續」後從頭開始。'))) pause.mutate('stop') }}
                className="px-4 py-2.5 rounded-xl bg-rose-600 text-white text-xl font-bold flex items-center gap-2"><Icon name="stop" />{t('全部停下來')}</button>
            </>}
      </header>

      {/* a wide screen: the emulators on the left all the time, the rest on the right; a phone: one column */}
      <div className="lg:grid lg:grid-cols-[300px_1fr] lg:items-start">
        <aside className="lg:sticky lg:top-[73px] lg:h-[calc(100vh-73px)] lg:overflow-y-auto lg:border-r lg:border-stone-200 bg-white lg:bg-transparent">
          <div className="hidden lg:block px-4 pt-4 pb-1 text-base font-bold text-stone-500">{words.device}</div>
          <div className="flex lg:flex-col gap-2 p-3 lg:p-4 lg:pt-1 overflow-x-auto">
            {d.cards.map(c => <DeviceCard key={c.device} c={c} chosen={tab === 'device' && cur === c.device} onPick={() => pickDevice(c.device)}
              stop={d.controls.find(x => x.bind?.kind === 'act_stop' && x.scope === 'device')} onMsg={setMsg} />)}
          </div>
          <div className="hidden lg:flex flex-wrap gap-x-3 gap-y-1 px-4 pb-4 text-sm text-stone-500">
            {LEGEND.map(([tx, w]) => <span key={tx} className="flex items-center gap-1"><span className={`w-2.5 h-2.5 rounded-full ${DOT[tx].replace(' animate-pulse', '')}`} />{w}</span>)}
          </div>
        </aside>

        <main className="p-4 flex flex-col gap-4 max-w-3xl mx-auto lg:max-w-none lg:mx-0 w-full min-w-0">
          {d.paused && <div className="rounded-xl border-2 border-rose-300 bg-rose-50 px-4 py-3 text-rose-900 text-xl">{d.paused_mode === 'pause' ? t('目前全部暫停中,不會自動做任何事。要恢復請按右上角「全部繼續」。') : t('目前全部停下來中,不會自動做任何事。要恢復請按右上角「全部繼續」。')}</div>}
          {!d.running && <div className="rounded-xl border-2 border-amber-300 bg-amber-50 px-4 py-3 text-amber-900">{t('系統目前沒有在運作,設定可以先改,但不會執行。請聯絡負責人。')}</div>}
          {msg && <div className={`rounded-xl px-4 py-3 ${msg.ok ? 'bg-emerald-50 text-emerald-900' : 'bg-rose-50 text-rose-900'}`}>{msg.ok ? '✔ ' : '✖ '}{msg.text}</div>}
          <AskBar items={d.asks ?? []} big refresh={['panel']} />
          <TodoBar items={d.todo ?? []} onGo={go} onMsg={setMsg} />
          {srcs.data?.can && d.cards.length === 0 && <section className="rounded-2xl border-2 border-sky-300 bg-sky-50 p-6 flex flex-col items-start gap-3">
            <h2 className="text-2xl font-bold">{t('還沒有選擇要操作的{device}', { device: words.device })}</h2>
            <div className="text-lg">{srcs.data.help || t('先開好{device},再按下面的按鈕掃描、勾選要使用的。', { device: words.device })}</div>
            <button onClick={() => setPickOpen(true)} className="px-6 py-3 rounded-xl bg-sky-600 text-white text-xl font-bold flex items-center gap-2"><Icon name="search" />{t('掃描並選擇{device}', { device: words.device })}</button>
          </section>}
          <PickSources open={pickOpen} onClose={() => setPickOpen(false)} onMsg={setMsg} />

          <div className="flex gap-2 border-b-2 border-stone-200">
            {[...pages.map(p => [p.id, p.title] as const), ['device', card ? t('這台:{p1}', { p1: dn(card.device) }) : t('這台')] as const].map(([k, tx]) => (
              <button key={k} onClick={() => { if (k === 'device' && !card && d.cards[0]) setCur(d.cards[0].device); setView(k) }}
                className={`px-5 py-2 text-xl font-bold -mb-0.5 border-b-4 ${tab === k ? 'border-stone-900 text-stone-900' : 'border-transparent text-stone-500'}`}>{tx}</button>
            ))}
          </div>

          {tab !== 'device' || !card
            ? <div className="grid xl:grid-cols-2 gap-4 items-start">
                {d.blocks.filter(b => pageOf(b) === tab).map(b => <div key={b.id} id={`block-${b.id}`}
                  className={`scroll-mt-24 ${wide(b, byId) ? 'xl:col-span-2' : ''} ${b.widget?.kind === 'devices' && !b.widget.show_image ? 'lg:hidden' : ''}`}>{blockFor(b)}</div>)}
                {tab === pages[pages.length - 1].id && <div className="xl:col-span-2"><History d={d} byId={byId} show={showLog} setShow={setShowLog} devChoices={devChoices} /></div>}
              </div>
            : <DeviceView n={card.device} card={card} d={d} byId={byId} change={change} busy={set.isPending} onMsg={setMsg} />}
        </main>
      </div>
    </div>
  )
}

/** Find the sources the pack allows on this computer and tick the ones to use (the others never show, nothing acts on
 * them). Unticking only turns one off: its name and settings stay for when it is ticked again. */
function PickSources({ open, onClose, onMsg }: { open: boolean; onClose: () => void; onMsg: (m: { ok: boolean; text: string }) => void }) {
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
  const away = scan.data && !scan.isPending ? items.filter(i => i.enabled && !found.some(r => r.kind === i.kind && r.match === i.match)) : []
  return (
    <Modal open={open} wide title={t('選擇要操作的{device}', { device: words.device })} onClose={onClose}>
      <div className="flex flex-col gap-3 text-lg">
        <div className="text-base text-stone-600">{info.data?.help || t('先開好{device},再按「重新掃描」。', { device: words.device })}
          {info.data?.kinds?.length ? <span className="block text-sm text-stone-500 mt-1">{t('會找:{p1}', { p1: info.data.kinds.map(k => k.label).join(t('、')) })}</span> : null}</div>
        <div className="flex items-center gap-3">
          <button onClick={() => scan.mutate()} disabled={scan.isPending} className="px-5 py-2.5 rounded-xl bg-sky-600 text-white font-bold flex items-center gap-2 disabled:opacity-50">
            <Icon name="search" />{scan.isPending ? t('掃描中…') : t('重新掃描')}</button>
          <span className="text-base text-stone-500">{t('勾選的才會出現在面板、被腳本操作;沒勾的完全不會動到它')}</span>
        </div>
        {scan.error && <div className="text-rose-700 text-base">{(scan.error as Error).message}</div>}
        {Object.entries(scan.data?.errors ?? {}).map(([k, v]) => <div key={k} className="text-amber-800 text-base">{k}:{v}</div>)}
        {scan.data && found.length === 0 && <div className="text-stone-500">{t('沒有找到。確認{device}已經開好,再按「重新掃描」。', { device: words.device })}</div>}
        {found.map(r => {
          const u = on(r)
          return (
            <label key={`${r.kind}|${r.match}`} className={`rounded-xl border-2 px-4 py-3 flex items-center gap-3 cursor-pointer ${u ? 'border-emerald-400 bg-emerald-50' : 'border-stone-200 bg-white'}`}>
              <input type="checkbox" className="w-6 h-6" checked={u} disabled={use.isPending}
                onChange={e => use.mutate({ kind: r.kind, match: r.match, use: e.target.checked, name: r.name })} />
              <div className="flex-1 min-w-0">
                <b>{dn(items.find(i => i.kind === r.kind && i.match === r.match)?.id ?? r.name)}</b>
                <span className="ml-2 text-base text-stone-500">{r.kind_label}{r.detail ? ` · ${r.detail}` : ''}</span>
                {r.warn && <div className="text-sm text-amber-800">{r.warn}</div>}
              </div>
              <span className={`text-base font-bold ${u ? 'text-emerald-700' : 'text-stone-400'}`}>{u ? t('使用中') : t('不使用')}</span>
            </label>
          )
        })}
        {away.length > 0 && <div className="flex flex-col gap-2">
          <div className="text-base text-stone-600">{t('使用中、但這次沒找到(可能沒開):')}</div>
          {away.map(i => (
            <div key={i.id} className="rounded-xl border-2 border-amber-300 bg-amber-50 px-4 py-2 flex items-center gap-3">
              <b className="flex-1">{dn(i.id)}<span className="ml-2 text-base font-normal text-stone-500">{i.kind_label}</span></b>
              <button className="px-3 py-1.5 rounded-lg border border-stone-300 bg-white" disabled={use.isPending}
                onClick={() => use.mutate({ kind: i.kind, match: i.match, use: false, name: i.name })}>{t('不再使用')}</button>
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

/** One emulator on the left: how it is, how far what it is doing has got (a bar, what is left, when it will be over),
 * and 停下來 / 繼續 right there. Clicking it opens its 這台 view. */
function DeviceCard({ c, chosen, onPick, stop, onMsg }: {
  c: PanelCard; chosen: boolean; onPick: () => void; stop?: PanelControl; onMsg: (m: { ok: boolean; text: string }) => void
}) {
  const p = c.progress
  const frac = p?.i && p.n ? Math.min(1, ((p.i - 1) + (p.wait_total ? 1 - (p.wait_left ?? 0) / p.wait_total : 0)) / p.n) : null
  return (
    <div role="button" tabIndex={0} onClick={onPick} onKeyDown={e => { if (e.key === 'Enter') onPick() }}
      className={`shrink-0 lg:shrink w-64 lg:w-auto cursor-pointer text-left rounded-xl bg-white border border-stone-200 border-l-[6px] ${EDGE[c.tone]} px-3 py-2 flex flex-col gap-1 hover:bg-stone-50 ${chosen ? 'ring-2 ring-stone-900 ring-offset-1' : ''}`}>
      <div className="flex items-center gap-2">
        <b className="flex-1 min-w-0 break-all leading-tight">{dn(c.device)}</b>
        <span className={`shrink-0 text-sm px-2 py-0.5 rounded-full font-bold ${CHIP[c.tone]}`}>{c.label ?? ''}</span>
      </div>
      {p?.name
        ? <>
            <div className="text-base truncate">{p.name}{p.i && p.n ? ` ${p.i}/${p.n}` : ''}{p.paused ? t('(暫停中)') : ''}</div>
            {p.say && <div className="text-sm truncate opacity-80">{p.say}</div>}
            {frac !== null && <div className="h-2 rounded-full bg-stone-200 overflow-hidden"><div className="h-full bg-sky-600" style={{ width: `${Math.round(frac * 100)}%` }} /></div>}
            {(p.wait_left != null || p.eta != null) && <div className="text-sm text-stone-600 flex items-center gap-1"><Icon name="clock" className="w-4 h-4" />
              {p.wait_left != null ? t('這個還剩 {p1}', { p1: span(p.wait_left) }) : ''}{p.wait_left != null && p.eta != null ? ' · ' : ''}{p.eta != null ? t('約 {p1} 完成', { p1: clockIn(p.eta) }) : ''}</div>}
          </>
        : <div className="text-sm text-stone-600 line-clamp-2">{c.now}</div>}
      {stop && <div className="flex justify-end" onClick={e => e.stopPropagation()}><ActionButton c={stop} device={c.device} onMsg={onMsg} small /></div>}
    </div>
  )
}

/** What to look at now, on top: the most pressing first, each with where to go; an event (a failed schedule, a stuck
 * screen) is hidden with 知道了, a state (stopped by a rule, no picture, names not seen) goes away once it is over. */
function TodoBar({ items, onGo, onMsg }: { items: PanelTodo[]; onGo: (g: PanelTodo['go']) => void; onMsg: (m: { ok: boolean; text: string }) => void }) {
  const qc = useQueryClient()
  const [all, setAll] = useState(false)
  const [pic, setPic] = useState<string | null>(null)
  const ack = useMutation({ mutationFn: (keys: string[]) => api.panelTodoAck(keys), onSuccess: () => qc.invalidateQueries({ queryKey: ['panel'] }),
    onError: (e: Error) => onMsg({ ok: false, text: e.message }) })
  if (!items.length) return null
  const bad = items.some(i => i.level === 'bad')
  const shown = all ? items : items.slice(0, 3)
  const events = items.filter(i => i.ack).map(i => i.key)
  return (
    <section className={`rounded-2xl border-2 p-4 flex flex-col gap-3 ${bad ? 'border-rose-400 bg-rose-50' : 'border-amber-300 bg-amber-50'}`}>
      <div className="flex flex-wrap items-center gap-3">
        <h2 className={`text-xl font-bold flex items-center gap-2 ${bad ? 'text-rose-900' : 'text-amber-900'}`}><Icon name="alert" className="w-6 h-6" />{t('{length} 件事要處理', { length: items.length })}</h2>
        <span className="flex-1" />
        {events.length > 1 && <button className="text-base underline text-stone-600" disabled={ack.isPending}
          onClick={() => { if (confirm(t('把 {length} 件「知道了」就好的事都收起來?(被停下來、看不到畫面這類,要處理好才會消失)', { length: events.length }))) ack.mutate(events) }}>{t('全部知道了')}</button>}
      </div>
      {shown.map(i => (
        <div key={i.key} className="rounded-xl bg-white border border-stone-200 px-3 py-2 flex flex-wrap items-center gap-3">
          <span className={`w-3 h-3 rounded-full shrink-0 ${i.level === 'bad' ? 'bg-rose-500' : 'bg-amber-500'}`} />
          <div className="flex-1 min-w-56">
            <div>{i.device && <b className="mr-2">{dn(i.device)}</b>}{i.text}</div>
            {i.detail && <div className="text-base text-stone-500">{i.detail}</div>}
          </div>
          {i.frame && <button onClick={() => setPic(i.frame!)} title={t('看當時的畫面')}>
            <img src={`/api/panel/stuck_frame?frame=${encodeURIComponent(i.frame)}`} alt="" className="h-12 rounded border border-stone-300" /></button>}
          <button className="px-4 py-2 rounded-lg bg-stone-800 text-white font-bold flex items-center gap-1" onClick={() => onGo(i.go)}>{t('去看')}<Icon name="go" className="w-4 h-4" /></button>
          {i.ack && <button className="px-3 py-2 rounded-lg border border-stone-300 bg-white" disabled={ack.isPending} onClick={() => ack.mutate([i.key])}>{t('知道了')}</button>}
        </div>
      ))}
      {items.length > 3 && <button className="self-start text-base underline text-stone-600" onClick={() => setAll(v => !v)}>{all ? t('只看前 3 件') : t('看全部 {length} 件', { length: items.length })}</button>}
      <Modal open={!!pic} wide title={t('卡住時的畫面')} onClose={() => setPic(null)}>
        {pic && <img src={`/api/panel/stuck_frame?frame=${encodeURIComponent(pic)}`} alt="" className="w-full rounded" />}
      </Modal>
    </section>
  )
}

/** A block that takes the whole width on a wide screen: long lists and logs, and settings asked per emulator. */
function wide(b: PanelBlock, byId: Record<string, PanelControl>) {
  if (b.width === 'wide' || b.width === 'narrow') return b.width === 'wide'
  if (b.widget) return ['list', 'log', 'chat', 'devices'].includes(b.widget.kind)
  return b.items.some(i => byId[i]?.scope === 'device' && byId[i]?.type !== 'action')
}

/** A block of controls: the shared ones, then each emulator's (one line each, opened to change). */
function ControlBlock({ b, byId, devices, open, setOpen, change, busy, onMsg }: {
  b: PanelBlock; byId: Record<string, PanelControl>; devices: string[]; open: string | null; setOpen: (k: string | null) => void
  change: (c: PanelControl, v: unknown, device?: string) => void; busy: boolean; onMsg: (m: { ok: boolean; text: string }) => void
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
  return (
    <section className="bg-white rounded-2xl border border-stone-200 p-4 flex flex-col gap-4">
      <div className="flex items-start gap-4">
        <div className="flex-1"><h2 className="text-xl font-bold">{b.title}</h2>{b.help && <div className="text-base text-stone-500">{b.help}</div>}</div>
        {tg && <Toggle on={tg.value === true} busy={busy} onChange={v => change(tg, v)} />}
      </div>
      {off && <div className="text-base text-stone-500 -mt-2">{t('目前關閉:時間到也不會執行。下面的設定可以先改好。')}</div>}
      <div className={`flex flex-col gap-4 ${off ? 'opacity-60' : ''}`}>
        {globals.map(c => <Control key={c.id} c={c} value={c.value} choices={(c.choices as PanelOption[]) ?? []} onChange={v => change(c, v)} busy={busy} />)}
        {globalActs.length > 0 && <div className="flex flex-wrap gap-3">{globalActs.map(c => <ActionButton key={c.id} c={c} onMsg={onMsg} />)}</div>}
        {(perDev.length > 0 || devActs.length > 0) && <DeviceTable devices={devices} perDev={perDev} devActs={devActs} change={change} busy={busy} onMsg={onMsg} />}
        {(perDev.length > 0 || devActs.length > 0) && devices.map(n => {
          const key = `${b.id}|${n}`
          const isOpen = open === key
          const doing = devActs.length ? ((devActs[0].value as Record<string, { name?: string; loop?: string | null; paused?: boolean } | null>) ?? {})[n] : null
          return (
            <div key={n} className="rounded-xl border border-stone-200 lg:hidden">
              <div className="px-4 py-3 flex flex-wrap items-center gap-3">
                <button onClick={() => perDev.length && setOpen(isOpen ? null : key)} className="flex-1 min-w-48 text-left flex items-center gap-3">
                  <b className="shrink-0">{dn(n)}</b>
                  <span className="flex-1 text-stone-600 text-base">{perDev.length ? summary(perDev, c => devValue(c, n), c => devChoices(c, n)) : ''}
                    {doing?.name && <span className="block text-sky-800">{t('正在進行:{name}{p2}', { name: doing.name, p2: doing.loop ? `(${doing.loop.split(' ').pop()})` : '' })}{doing.paused ? t(' · 暫停中') : ''}</span>}</span>
                  {perDev.length > 0 && <span className="shrink-0 text-base text-sky-700">{isOpen ? t('收起 ▴') : t('改設定 ▾')}</span>}
                </button>
                {devActs.map(c => <ActionButton key={c.id} c={c} device={n} onMsg={onMsg} />)}
              </div>
              {isOpen && <div className="px-4 pb-4 flex flex-col gap-4 border-t border-stone-100 pt-3">
                {perDev.map(c => <Control key={c.id} c={c} value={devValue(c, n)} choices={devChoices(c, n)} onChange={v => change(c, v, n)} busy={busy} />)}
              </div>}
            </div>
          )
        })}
      </div>
    </section>
  )
}

/** A wide screen: the settings each emulator has as a table - a row per emulator, a column per setting - so they are
 * compared and changed at a glance. A list to tick (which characters, in order) opens in a window. */
function DeviceTable({ devices, perDev, devActs, change, busy, onMsg }: {
  devices: string[]; perDev: PanelControl[]; devActs: PanelControl[]
  change: (c: PanelControl, v: unknown, device?: string) => void; busy: boolean; onMsg: (m: { ok: boolean; text: string }) => void
}) {
  const [edit, setEdit] = useState<{ c: PanelControl; n: string } | null>(null)
  const devValue = (c: PanelControl, n: string) => (c.value as Record<string, unknown>)?.[n]
  const devChoices = (c: PanelControl, n: string) => (c.choices as Record<string, PanelOption[]>)?.[n] ?? []
  const join = perDev.find(c => c.type === 'toggle' && c.bind?.kind === 'schedule_device')
  return (
    <div className="hidden lg:block overflow-x-auto">
      <table className="w-full text-base border-collapse">
        <thead><tr className="text-left text-stone-500 border-b-2 border-stone-200">
          <th className="py-2 pr-3 font-semibold">{words.device}</th>
          {perDev.map(c => <th key={c.id} className="py-2 px-3 font-semibold" title={c.help}>{c.label}{c.unit ? `(${c.unit})` : ''}</th>)}
          {devActs.length > 0 && <th className="py-2 pl-3 font-semibold">{t('動作')}</th>}
        </tr></thead>
        <tbody>{devices.map(n => {
          const out = join && devValue(join, n) === false          // not taking part: its other settings matter less
          const doing = devActs.length ? ((devActs[0].value as Record<string, { name?: string; loop?: string | null; paused?: boolean } | null>) ?? {})[n] : null
          return (
            <tr key={n} className="border-b border-stone-100 align-middle">
              <td className="py-2 pr-3"><b>{dn(n)}</b>
                {doing?.name && <div className="text-sm text-sky-800">{t('正在進行:{name}{p2}', { name: doing.name, p2: doing.loop ? `(${doing.loop.split(' ').pop()})` : '' })}</div>}</td>
              {perDev.map(c => (
                <td key={c.id} className={`py-2 px-3 ${out && c !== join ? 'opacity-40' : ''}`}>
                  <Cell c={c} value={devValue(c, n)} choices={devChoices(c, n)} busy={busy} onChange={v => change(c, v, n)} onOpen={() => setEdit({ c, n })} />
                </td>
              ))}
              {devActs.length > 0 && <td className="py-2 pl-3"><div className="flex flex-wrap gap-2">{devActs.map(c => <ActionButton key={c.id} c={c} device={n} onMsg={onMsg} small />)}</div></td>}
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
  if (c.type === 'toggle') {
    const on = value === true
    return <button disabled={busy} onClick={() => onChange(!on)} aria-pressed={on}
      className={`w-16 h-9 rounded-full font-bold ${on ? 'bg-emerald-600 text-white' : 'bg-stone-300 text-stone-700'}`}>{on ? t('開') : t('關')}</button>
  }
  if (c.type === 'time') return <input type="time" disabled={busy} value={String(value ?? '')} onChange={e => e.target.value && onChange(e.target.value)}
    className="border-2 border-stone-300 rounded-lg px-2 py-1" />
  if (c.type === 'number') {
    const cur = Number(value ?? 0)
    return <input type="number" disabled={busy} value={num ?? String(cur)} min={c.min ?? undefined} max={c.max ?? undefined}
      onChange={e => setNum(e.target.value)} title={t('改完按 Enter 或點別處就會儲存')}
      onBlur={() => { if (num !== null && num !== String(cur) && num.trim() !== '') onChange(Number(num)); setNum(null) }}
      onKeyDown={e => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur() }}
      className="w-24 border-2 border-stone-300 rounded-lg px-2 py-1 text-center" />
  }
  if (c.type === 'single') return (
    <select disabled={busy} value={choices.findIndex(o => same(o.value, value))} onChange={e => onChange(choices[Number(e.target.value)]?.value)}
      className="border-2 border-stone-300 rounded-lg px-2 py-1 max-w-48">
      {choices.findIndex(o => same(o.value, value)) < 0 && <option value={-1}>{t('(請選擇)')}</option>}
      {choices.map((o, i) => <option key={i} value={i}>{o.label}</option>)}
    </select>
  )
  const chosen = (Array.isArray(value) ? value : []) as unknown[]
  const names = chosen.map(x => choices.find(o => same(o.value, x))?.label ?? '?')
  return <button onClick={onOpen} title={names.join(' → ') || t('(沒有)')} className="text-left rounded-lg border-2 border-stone-300 px-2 py-1 hover:bg-stone-50 max-w-72">
    <b>{t('{length} 個', { length: chosen.length })}</b><span className="text-stone-500">{names.length ? `:${names.slice(0, 3).join(t('、'))}${names.length > 3 ? '…' : ''}` : ''}</span>
    <span className="ml-1 text-sky-700">✎</span></button>
}

/** Everything about one emulator in one place: how it is, what can be done on it, its own settings and lists. */
function DeviceView({ n, card, d, byId, change, busy, onMsg }: {
  n: string; card: PanelCard; d: PanelInfo; byId: Record<string, PanelControl>
  change: (c: PanelControl, v: unknown, device?: string) => void; busy: boolean; onMsg: (m: { ok: boolean; text: string }) => void
}) {
  const devValue = (c: PanelControl) => (c.value as Record<string, unknown>)?.[n]
  const devChoices = (c: PanelControl) => (c.choices as Record<string, PanelOption[]>)?.[n] ?? []
  const acts = d.blocks.flatMap(b => b.widget ? [] : b.items.map(i => byId[i]).filter(c => c && c.scope === 'device' && c.type === 'action'))
  const doing = acts.length ? ((acts[0].value as Record<string, { name?: string; loop?: string | null; paused?: boolean } | null>) ?? {})[n] : null
  const blocks = d.blocks.filter(b => !b.widget && b.items.some(i => byId[i]?.scope === 'device' && byId[i]?.type !== 'action'))
  const lists = d.blocks.filter(b => b.widget?.kind === 'list' && b.data?.by_device?.[n])
  return (
    <div className="grid xl:grid-cols-2 gap-4 items-start">
      <section className={`xl:col-span-2 rounded-2xl bg-white border border-stone-200 border-l-[8px] ${EDGE[card.tone]} p-4 flex flex-col gap-3`}>
        <div className="flex flex-wrap items-center gap-3">
          <h2 className="text-2xl font-bold">{dn(n)}</h2>
          <span className={`text-base px-2.5 py-0.5 rounded-full font-bold ${CHIP[card.tone]}`}>{card.label ?? ''}</span>
          <span className="text-xl">{card.now}</span>
        </div>
        {doing?.name && <div className="text-base">{t('正在進行:{name}{p2}', { name: doing.name, p2: doing.loop ? `(${doing.loop.split(' ').pop()})` : '' })}{doing.paused ? t(' · 暫停中') : ''}</div>}
        {card.today.length > 0 && <div className="text-base">{t('今天:{p1}', { p1: card.today.map(tx => `${tx.name} ${tx.text}`).join(' · ') })}</div>}
        {acts.length > 0 && <div className="flex flex-wrap gap-3">{acts.map(c => <ActionButton key={c.id} c={c} device={n} onMsg={onMsg} />)}</div>}
        {card.alerts.length > 0 && <div className="text-base flex flex-col gap-0.5 opacity-90">
          {card.alerts.map((a, i) => <div key={i}><span className="opacity-60 mr-2">{new Date(a.t * 1000).toLocaleTimeString(locale, { hour: '2-digit', minute: '2-digit' })}</span>{a.text}</div>)}</div>}
      </section>
      {blocks.map(b => {
        const tg = b.toggle ? byId[b.toggle] : undefined
        const own = b.items.map(i => byId[i]).filter(c => c && c.scope === 'device' && c.type !== 'action')
        return (
          <section key={b.id} className="bg-white rounded-2xl border border-stone-200 p-4 flex flex-col gap-4">
            <div><h2 className="text-xl font-bold">{b.title}</h2>
              {tg && tg.value === false && <div className="text-base text-stone-500">{t('這個排程目前關閉(到「總覽」打開):設定可以先改好。')}</div>}</div>
            {own.map(c => <Control key={c.id} c={c} value={devValue(c)} choices={devChoices(c)} onChange={v => change(c, v, n)} busy={busy} />)}
          </section>
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
    <section className="bg-white rounded-2xl border border-stone-200 p-4 flex flex-col gap-2">
      <button onClick={() => setShow(v => !v)} className="text-left text-xl font-bold">{t('最近的修改 {p1}', { p1: open ? '▴' : '▾' })}</button>
      {open && (d.history.length === 0 ? <div className="text-stone-500">{t('還沒有修改紀錄')}</div> : d.history.map((h, i) => {
        const c = byId[h.control]
        const ch = c ? (c.scope === 'device' ? devChoices(c, h.device ?? '') : (c.choices as PanelOption[]) ?? []) : []
        return <div key={i} className="text-base text-stone-700">
          <span className="text-stone-400 mr-2">{new Date(h.t * 1000).toLocaleString(locale, { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' })}</span>
          {h.device && <span className="mr-1">{dn(h.device)}</span>}{h.action
            ? <>{t('按下「{label}」{p2}', { label: h.label, p2: h.result ? `:${Object.entries(h.result).map(([k, v]) => h.device ? v : `${k} ${v}`).join(t('、'))}` : '' })}</>
            : <>「{h.label}」:{show(c, h.old, ch)} → <b>{show(c, h.new, ch)}</b></>}
        </div>
      }))}
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

function Toggle({ on, busy, onChange }: { on: boolean; busy: boolean; onChange: (v: boolean) => void }) {
  return <button disabled={busy} onClick={() => onChange(!on)} aria-pressed={on}
    className={`shrink-0 w-28 h-14 rounded-full text-xl font-bold transition-colors ${on ? 'bg-emerald-600 text-white' : 'bg-stone-300 text-stone-700'}`}>{on ? t('開') : t('關')}</button>
}

function show(c: PanelControl | undefined, v: unknown, choices: PanelOption[]): string {
  if (v === true) return t('開')
  if (v === false) return t('關')
  if (v == null) return '—'
  if (Array.isArray(v)) return v.map(x => choices.find(o => same(o.value, x))?.label ?? '?').join(t('、')) || t('(沒有)')
  if (typeof v === 'object') return choices.find(o => same(o.value, v))?.label ?? '?'
  return `${v}${c?.unit ?? ''}`
}

function Control({ c, value, choices, onChange, busy }: { c: PanelControl; value: unknown; choices: PanelOption[]; onChange: (v: unknown) => void; busy: boolean }) {
  const [num, setNum] = useState<string | null>(null)
  if (c.error) return <div className="text-rose-700">{t('「{label}」無法顯示:{error}', { label: c.label, error: c.error })}</div>
  const head = <div><div className="font-semibold">{c.label}</div>{c.help && <div className="text-base text-stone-500">{c.help}</div>}</div>
  if (c.type === 'toggle') {
    const on = value === true
    return (
      <div className="flex items-center justify-between gap-4">{head}
        <button disabled={busy} onClick={() => onChange(!on)} aria-pressed={on}
          className={`shrink-0 w-28 h-14 rounded-full text-xl font-bold transition-colors ${on ? 'bg-emerald-600 text-white' : 'bg-stone-300 text-stone-700'}`}>{on ? t('開') : t('關')}</button>
      </div>
    )
  }
  if (c.type === 'time') return (
    <div className="flex items-center justify-between gap-4">{head}
      <input type="time" disabled={busy} value={String(value ?? '')} onChange={e => e.target.value && onChange(e.target.value)}
        className="shrink-0 text-2xl border-2 border-stone-300 rounded-xl px-3 py-2" />
    </div>
  )
  if (c.type === 'number') {
    const cur = Number(value ?? 0)
    const step = (dlt: number) => onChange(Math.min(c.max ?? 1e9, Math.max(c.min ?? -1e9, cur + dlt)))
    return (
      <div className="flex items-center justify-between gap-4 flex-wrap">{head}
        <div className="flex items-center gap-2 shrink-0">
          <button disabled={busy} onClick={() => step(-5)} className="w-14 h-14 rounded-xl bg-stone-200 text-2xl font-bold">−</button>
          <input type="number" value={num ?? String(cur)} onChange={e => setNum(e.target.value)}
            onBlur={() => { if (num !== null && num !== String(cur)) onChange(Number(num)); setNum(null) }}
            className="w-24 text-2xl text-center border-2 border-stone-300 rounded-xl py-2" />
          <button disabled={busy} onClick={() => step(5)} className="w-14 h-14 rounded-xl bg-stone-200 text-2xl font-bold">+</button>
          <span>{c.unit}</span>
        </div>
      </div>
    )
  }
  if (c.type === 'single') return (
    <div className="flex items-center justify-between gap-4 flex-wrap">{head}
      <select disabled={busy} value={choices.findIndex(o => same(o.value, value))} onChange={e => onChange(choices[Number(e.target.value)]?.value)}
        className="shrink-0 text-xl border-2 border-stone-300 rounded-xl px-3 py-2 max-w-full">
        {choices.findIndex(o => same(o.value, value)) < 0 && <option value={-1}>{t('(請選擇)')}</option>}
        {choices.map((o, i) => <option key={i} value={i}>{o.label}</option>)}
      </select>
    </div>
  )
  // multi: tick in order
  const chosen = (Array.isArray(value) ? value : []) as unknown[]
  const at = (o: PanelOption) => chosen.findIndex(x => same(x, o.value))
  return (
    <div className="flex flex-col gap-2">{head}
      <div className="flex flex-wrap gap-2">
        {choices.map((o, i) => {
          const k = at(o)
          return (
            <button key={i} disabled={busy} onClick={() => onChange(k >= 0 ? chosen.filter((_, j) => j !== k) : [...chosen, o.value])}
              className={`px-3 py-2 rounded-xl border-2 text-lg ${k >= 0 ? 'bg-emerald-600 text-white border-emerald-600' : 'bg-white text-stone-700 border-stone-300'}`}>
              {k >= 0 && <span className="mr-1 text-base opacity-80">{k + 1}.</span>}{o.label}
            </button>
          )
        })}
      </div>
      {chosen.length > 0 && <div className="text-base text-stone-500">{t('順序:{p1}(取消再點一次可以排到最後)', { p1: chosen.map(x => choices.find(o => same(o.value, x))?.label ?? '?').join(' → ') })}</div>}
    </div>
  )
}

/** A big button that does something now (run a schedule, back to the spot, stop). Asks before acting; if the emulator
 * is busy with something else, asks whether to interrupt it or wait for it. */
function ActionButton({ c, device, onMsg, small = false }: { c: PanelControl; device?: string; onMsg: (m: { ok: boolean; text: string }) => void; small?: boolean }) {
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
    if (!window.confirm(held ? t('讓 {where} 恢復自動嗎?', { where })
      : isStop ? t('確定要讓 {where} 停下來嗎?\n會停掉它正在做的事,腳本和情境都停住、不會自動做任何事。按「繼續」後從頭開始。', { where })
      : t('確定要讓 {where} 現在「{label}」嗎?', { where, label: c.label }))) return
    press.mutate('ask')
  }
  if (device && c.targets && !c.targets.includes(device)) return null      // this emulator does not take part
  return (
    <div className="flex flex-col gap-2">
      <button onClick={go} disabled={press.isPending} title={held ? t('恢復自動') : c.help}
        className={`${small ? 'px-3 py-1.5 rounded-lg text-base' : 'px-5 py-3 rounded-xl text-lg'} font-bold disabled:opacity-40 ${held ? 'bg-emerald-600 text-white' : isStop ? 'bg-rose-600 text-white' : 'bg-sky-600 text-white'}`}>
        {press.isPending ? t('送出中…') : held ? <span className="inline-flex items-center gap-1"><Icon name="play" className="w-4 h-4" />{t('繼續')}</span> : c.label}</button>
      {ask && (
        <div className="rounded-xl border-2 border-amber-300 bg-amber-50 p-3 text-base flex flex-col gap-2 max-w-md">
          <div>{Object.entries(ask).map(([n, x]) => t('{n} 正在做「{p2}」{p3}', { n, p2: x.name ?? '', p3: x.loop ? `(${x.loop.split(' ').pop()})` : '' })).join(t(';'))}</div>
          <div>{t('要怎麼辦?')}</div>
          <div className="flex flex-wrap gap-2">
            <button className="px-4 py-2 rounded-lg bg-rose-600 text-white font-bold" onClick={() => press.mutate('interrupt')}>{t('停掉它,改做這個')}</button>
            <button className="px-4 py-2 rounded-lg bg-white border border-stone-300 font-bold" onClick={() => press.mutate('queue')}>{t('等它做完再做')}</button>
            <button className="px-4 py-2 rounded-lg text-stone-600" onClick={() => setAsk(null)}>{t('算了')}</button>
          </div>
        </div>
      )}
    </div>
  )
}
