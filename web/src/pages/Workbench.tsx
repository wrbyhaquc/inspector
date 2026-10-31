import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useRef, useState, type PointerEvent as RPointerEvent } from 'react'
import { t } from '../i18n'
import { api, wbApi, wbFrameUrl, wbLiveUrl, type AnswerValue, type StateDef, type WbButton, type WbDraft, type WbStateRead, type WbWhy } from '../api'
import { Button, Card, Empty, ErrorText, Page, Pill, StatePill } from '../components/ui'
import { DraftPanel } from '../components/wb/DraftPanel'
import { HerePanel } from '../components/wb/HerePanel'
import { RuleForm, type RulePick } from '../components/wb/RuleForm'
import { StateFix } from '../components/wb/StateFix'
import { TeachPanel, type Press } from '../components/wb/TeachPanel'
import { clock } from '../lib/format'
import { usePersistentState } from '../lib/persist'
import { screen, words } from '../lib/project'
import { stateColor, useSchema } from '../lib/schema'
import { dn, expandKeys, sourceIds } from '../lib/sources'

const input = 'border border-stone-300 rounded-md px-2 py-1 text-sm bg-white'
const pctX = (x: number) => `${(x / screen.w) * 100}%`
const pctY = (y: number) => `${(y / screen.h) * 100}%`
const SWIPE_MIN = 15        // project pixels: a press that moved further is a swipe
const LONG_MS = 500

/** does this state apply to this source? (a state can be for some sources only) */
const appliesTo = (s: StateDef, device: string) => !s.sources?.length || expandKeys(s.sources).includes(device)

/** The live picture, swapped only when the next one has loaded: no flicker, and at most one request at a time. */
function useLiveImage(device: string, on: boolean) {
  const [src, setSrc] = useState('')
  const [failed, setFailed] = useState(false)
  useEffect(() => {
    if (!on || !device) return
    let alive = true
    let timer = 0
    const next = () => {
      if (!alive) return
      if (document.hidden) { timer = window.setTimeout(next, 1000); return }
      const url = wbLiveUrl(device, Date.now())
      const im = new Image()
      im.onload = () => { if (alive) { setSrc(url); setFailed(false); timer = window.setTimeout(next, 800) } }
      im.onerror = () => { if (alive) { setFailed(true); timer = window.setTimeout(next, 3000) } }
      im.src = url
    }
    next()
    return () => { alive = false; clearTimeout(timer) }
  }, [device, on])
  return { src, failed }
}

function valueText(s: StateDef, r?: { value: unknown } | null) {
  const v = r?.value
  if (v == null) return '?'
  if (s.type === 'ratio' && typeof v === 'number') return `${Math.round(v * 100)}%`
  return s.classes?.find(c => JSON.stringify(c.value) === JSON.stringify(v))?.name ?? String(v)
}

/** The screen with the design over it. Dragging marks a spot; while teaching, a press goes to the device. */
function Stage({ src, states, reads, buttons, layers, hot, sel, teaching, onMark, onStart, onPress }: {
  src: string; states: StateDef[]; reads: Record<string, WbStateRead | undefined>; buttons: WbButton[]
  layers: { states: boolean; buttons: boolean; labels: boolean }; hot: string | null
  sel: number[] | null; teaching: boolean; onMark: (box: number[]) => void; onStart: () => void; onPress: (p: Press) => void
}) {
  const ref = useRef<HTMLDivElement>(null)
  const drag = useRef<{ x: number; y: number; t: number } | null>(null)
  const [draw, setDraw] = useState<number[] | null>(null)
  const at = (e: { clientX: number; clientY: number }): [number, number] => {
    const r = ref.current!.getBoundingClientRect()
    return [Math.max(0, Math.min(screen.w - 1, Math.round(((e.clientX - r.left) / r.width) * screen.w))),
      Math.max(0, Math.min(screen.h - 1, Math.round(((e.clientY - r.top) / r.height) * screen.h)))]
  }
  const down = (e: RPointerEvent<HTMLDivElement>) => {
    e.preventDefault()
    const [x, y] = at(e)
    drag.current = { x, y, t: Date.now() }
    try { ref.current!.setPointerCapture(e.pointerId) } catch { /* still works inside */ }
    if (!teaching) { onStart(); setDraw([x, y, 0, 0]) }
  }
  const move = (e: RPointerEvent<HTMLDivElement>) => {
    const d = drag.current
    if (!d) return
    const [x, y] = at(e)
    setDraw([Math.min(d.x, x), Math.min(d.y, y), Math.abs(x - d.x), Math.abs(y - d.y)])
  }
  const up = (e: RPointerEvent<HTMLDivElement>) => {
    const d = drag.current
    drag.current = null
    setDraw(null)
    if (!d) return
    const [x, y] = at(e)
    const moved = Math.abs(x - d.x) + Math.abs(y - d.y)
    if (teaching) {
      const ms = Date.now() - d.t
      if (moved > SWIPE_MIN) onPress({ op: 'swipe', x: d.x, y: d.y, x2: x, y2: y, ms: Math.max(200, ms) })
      else if (ms >= LONG_MS) onPress({ op: 'long_press', x: d.x, y: d.y, ms })
      else onPress({ op: 'tap', x: d.x, y: d.y })
    } else if (moved < 6) onMark([x, y, 0, 0])
    else onMark([Math.min(d.x, x), Math.min(d.y, y), Math.abs(x - d.x), Math.abs(y - d.y)])
  }
  const mark = draw ?? (teaching ? null : sel)
  return (
    <div ref={ref} onPointerDown={down} onPointerMove={move} onPointerUp={up}
      className={`relative w-full bg-stone-900 rounded-md overflow-hidden select-none touch-none cursor-crosshair ${teaching ? 'ring-4 ring-rose-500' : ''}`}
      style={{ aspectRatio: `${screen.w} / ${screen.h}` }}>
      {src && <img src={src} alt={t('畫面')} draggable={false} className="absolute inset-0 w-full h-full pointer-events-none" />}
      {!teaching && layers.states && states.flatMap((s, i) => s.rois.map(r => {
        const color = stateColor(i)
        const on = hot === s.id
        const draft = reads[s.id]?.draft
        return (
          <div key={`${s.id}:${r.id}`} className={`absolute pointer-events-none border-2 ${draft ? 'border-dashed' : ''}`}
            style={{ left: pctX(r.box[0]), top: pctY(r.box[1]), width: pctX(r.box[2]), height: pctY(r.box[3]), borderColor: color, background: on ? 'rgba(255,255,255,.2)' : undefined, zIndex: on ? 3 : 1 }}>
            {(on || draft || layers.labels) && <span className="absolute -top-4 left-0 text-[10px] leading-4 px-1 rounded-sm text-stone-900 whitespace-nowrap" style={{ background: color }}>
              {s.name} {valueText(s, reads[s.id])}</span>}
          </div>
        )
      }))}
      {!teaching && layers.buttons && buttons.map(b => {
        const missing = b.find && b.found === false
        const [x, y] = b.at ?? [b.x, b.y]
        return (
          <div key={b.id} title={`${b.label}${b.find ? (b.found ? t(' · 找到 {p1}%', { p1: Math.round((b.score ?? 0) * 100) }) : t(' · 這張找不到')) : ''}`}
            className="absolute -ml-1.5 -mt-1.5 w-3 h-3 rounded-full border-2" style={{ left: pctX(x), top: pctY(y), zIndex: 4,
              borderColor: missing ? '#f87171' : '#fbbf24', background: missing ? 'transparent' : 'rgba(251,191,36,.35)', opacity: missing ? 0.5 : 1 }} />
        )
      })}
      {mark && (mark[2] || mark[3]
        ? <div className="absolute pointer-events-none border-2 border-white shadow-[0_0_0_1px_#000]" style={{ left: pctX(mark[0]), top: pctY(mark[1]), width: pctX(mark[2]), height: pctY(mark[3]), zIndex: 5 }} />
        : <div className="absolute pointer-events-none -ml-2.5 -mt-2.5 w-5 h-5 rounded-full border-2 border-white shadow-[0_0_0_1px_#000]" style={{ left: pctX(mark[0]), top: pctY(mark[1]), zIndex: 5 }} />)}
    </div>
  )
}

const SOURCE_TEXT: Record<string, string> = { rule: t('規則'), runner: t('執行程式'), model: t('模型'), 'model+rule': t('模型+規則') }

function StatesNow({ states, reads, hot, onHot, running, frozen, open, onOpen, picks, onPick }: {
  states: StateDef[]; reads: Record<string, WbStateRead | undefined>; hot: string | null; onHot: (id: string | null) => void; running: boolean
  frozen: boolean; open: string | null; onOpen: (id: string | null) => void; picks: Set<string>; onPick: (id: string) => void
}) {
  if (!states.length) return <Empty>{t('這個專案還沒有狀態。在畫面上框一塊,就能新增第一個。')}</Empty>
  return (
    <div className="flex flex-col text-sm">
      {!running && <p className="text-xs text-amber-800 bg-amber-50 rounded px-2 py-1 mb-1">{t('執行程式沒有開:畫面規則還是會算,靠模型判斷的狀態要開了才有值。')}</p>}
      {states.map((s, i) => {
        const r = reads[s.id]
        return (
          <div key={s.id} onMouseEnter={() => onHot(s.id)} onMouseLeave={() => onHot(null)}
            className={`flex items-center gap-2 px-1.5 py-1 rounded ${hot === s.id ? 'bg-stone-100' : ''}`}>
            <input type="checkbox" title={t('用這個值組成規則')} checked={picks.has(s.id)} disabled={r?.value == null} onChange={() => onPick(s.id)} />
            <span className="w-2 h-2 rounded-full shrink-0" style={{ background: stateColor(i) }} />
            <button className="flex-1 min-w-0 truncate text-left hover:underline" title={frozen ? t('這張判斷錯了?點這裡修正') : t('先凍結,才能在那一張上修正')}
              onClick={() => onOpen(open === s.id ? null : s.id)}>{s.name}{r?.draft ? t('(草稿)') : ''}</button>
            {r?.error ? <span className="text-xs text-rose-700 truncate" title={r.error}>{t('算不出來')}</span>
              : <StatePill state={{ ...s, name: '' }} v={r?.value ?? null} />}
            <span className="text-[11px] text-stone-400 w-12 text-right num truncate" title={r?.source}>
              {r?.conf != null ? `${Math.round(r.conf * 100)}%` : SOURCE_TEXT[r?.source ?? ''] ?? ''}</span>
          </div>
        )
      })}
    </div>
  )
}

const NOW_STYLE: Record<string, string> = { holds: 'text-emerald-700', 'does not hold': 'text-stone-400', unsure: 'text-amber-700' }
const NOW_MARK: Record<string, string> = { holds: '✓', 'does not hold': '✕', unsure: '?' }

function RulesNow({ items }: { items: WbWhy[] }) {
  if (!items.length) return <Empty>{t('這台沒有部署主腳本。')}</Empty>
  return (
    <div className="flex flex-col gap-3 text-sm">
      {items.map(w => (
        <div key={w.script} className="flex flex-col gap-1">
          <div className="flex items-center gap-2 flex-wrap">
            <b>{w.name}</b>
            {w.situation && <span className="text-xs text-stone-500">{w.situation}</span>}
            <Pill tone={w.mode === 'live' ? 'green' : 'stone'}>{w.mode === 'live' ? t('正式') : w.mode === 'off' ? t('沒有部署') : t('試跑')}</Pill>
            {w.held && <Pill tone="amber">{t('停住中')}</Pill>}
          </div>
          <div className="text-xs text-stone-600">{t('現在會做:')}<b>{w.decision_now.text || t('不動作')}</b>{w.decision_now.rule_name ? t('(規則「{name}」)', { name: w.decision_now.rule_name }) : ''}</div>
          {w.rules_in_order.map(r => {
            const holds = r.any_of.some(g => g.group === 'holds')
            return (
              <details key={r.rule} className={`rounded border px-2 py-1 ${r.draft ? 'border-dashed border-sky-500 bg-sky-50/50' : 'border-stone-200'}`}>
                <summary className={`cursor-pointer text-xs ${r.enabled === false ? 'line-through text-stone-400' : holds ? 'font-semibold text-emerald-800' : 'text-stone-700'}`}>
                  {holds ? '● ' : '○ '}{r.name || r.rule}{r.urgent ? t('(緊急)') : ''}{r.draft ? t('(草稿:只判斷,不會做)') : ''}</summary>
                <div className="mt-1 flex flex-col gap-1">
                  {r.any_of.map((g, i) => (
                    <div key={i} className="flex flex-col">
                      {i > 0 && <span className="text-[11px] text-stone-400">{t('或')}</span>}
                      {g.all_of.map((c, k) => <span key={k} className={`text-xs ${NOW_STYLE[c.now] ?? ''}`}>{NOW_MARK[c.now] ?? ''} {c.condition}</span>)}
                    </div>
                  ))}
                </div>
              </details>
            )
          })}
        </div>
      ))}
    </div>
  )
}

type Tab = 'now' | 'here' | 'draft' | 'teach'

export default function Workbench() {
  const qc = useQueryClient()
  const devices = sourceIds()
  const [device, setDevice] = usePersistentState('wb.device', '')
  const cur = devices.includes(device) ? device : devices[0] ?? ''
  const [frozen, setFrozen] = useState<string | null>(null)        // the id of the picture being looked at; null = live
  const [layers, setLayers] = usePersistentState('wb.layers2', { states: true, buttons: true, labels: false })
  const [hot, setHot] = useState<string | null>(null)
  const [sel, setSel] = useState<number[] | null>(null)
  const [tab, setTab] = usePersistentState<Tab>('wb.tab', 'now')
  const [fix, setFix] = useState<string | null>(null)
  const [picks, setPicks] = useState<Set<string>>(new Set())
  const schema = useSchema()
  const draftView = useQuery({ queryKey: ['wbDraft'], queryFn: wbApi.draft })
  const doc = draftView.data?.doc
  const count = doc ? doc.buttons.length + doc.states.length + doc.refs.length + doc.answers.length + doc.subs.length + doc.rules.length : 0
  const states = useMemo(() => {
    const mine = new Map((doc?.states ?? []).map(s => [s.id, s]))
    const base = schema.data?.schema.states ?? []
    return [...base.map(s => mine.get(s.id) ?? s), ...(doc?.states ?? []).filter(s => !base.some(b => b.id === s.id))].filter(s => appliesTo(s, cur))
  }, [schema.data, doc, cur])
  const teach = useQuery({ queryKey: ['wbTeach', cur], queryFn: () => wbApi.teach(cur), enabled: !!cur, refetchInterval: q => (q.state.data?.active ? 1500 : false) })
  const teaching = !!teach.data?.active
  const live = useLiveImage(cur, !frozen || teaching)
  const prev = useRef(cur)
  useEffect(() => { if (prev.current !== cur) { prev.current = cur; setFrozen(null); setSel(null); setFix(null); setPicks(new Set()) } }, [cur])
  useEffect(() => { if (teaching) setFrozen(null) }, [teaching])

  const sees = useQuery({ queryKey: ['wbSees', cur], queryFn: () => wbApi.sees(cur), enabled: !!cur && !frozen, refetchInterval: 1500 })
  const draftLive = useQuery({ queryKey: ['wbDraftLive', cur, count], queryFn: () => wbApi.draftLive(cur), enabled: !!cur && !frozen && !teaching && (sees.data?.running === false || (doc?.states.length ?? 0) + (doc?.refs.length ?? 0) > 0), refetchInterval: 1500 })
  const kept = useQuery({ queryKey: ['wbFrames', cur], queryFn: () => wbApi.frames(cur), enabled: !!cur })
  const frame = useQuery({ queryKey: ['wbFrame', cur, frozen, draftView.dataUpdatedAt], queryFn: () => wbApi.frame(cur, frozen!), enabled: !!frozen, placeholderData: p => p })
  const freezing = useRef<Promise<{ id: string }> | null>(null)
  const freeze = useMutation({
    mutationFn: () => wbApi.freeze(cur),
    onSuccess: r => { setFrozen(r.id); qc.invalidateQueries({ queryKey: ['wbFrames', cur] }) },
  })
  const startMark = () => { if (!frozen && !freeze.isPending) freezing.current = freeze.mutateAsync() }
  const reads: Record<string, WbStateRead | undefined> = frozen
    ? frame.data?.states ?? {}
    : { ...(sees.data?.state as Record<string, WbStateRead> | null | undefined), ...draftLive.data?.states }
  const why = useQuery({
    queryKey: ['wbWhy', cur, frozen, draftView.dataUpdatedAt],
    queryFn: () => wbApi.why(cur, frozen),
    enabled: !!cur && !teaching,
    refetchInterval: frozen ? false : 3000,
  })
  const running = frozen ? !!frame.data?.runner.running : !!sees.data?.running
  const buttons: WbButton[] = frozen ? frame.data?.buttons ?? [] : []
  const saveDraft = async (d: WbDraft) => { await wbApi.draftSave(d); await qc.invalidateQueries({ queryKey: ['wbDraft'] }) }
  const press = useMutation({
    mutationFn: (p: Press) => wbApi.teachPress({ device: cur, ...p }),
    onSuccess: d => qc.setQueryData(['wbTeach', cur], d),
  })
  const pick = (id: string) => setPicks(s => { const n = new Set(s); if (n.has(id)) n.delete(id); else n.add(id); return n })
  const rulePicks: RulePick[] = states.filter(s => picks.has(s.id) && reads[s.id]?.value != null).map(s => ({ state: s, value: reads[s.id]!.value as AnswerValue | number }))
  const fixState = states.find(s => s.id === fix)
  const info = useQuery({ queryKey: ['scripts'], queryFn: api.scripts })

  if (!devices.length) return (
    <Page title={t('即時工作台')}><Empty>{t('還沒有來源。先到「來源」接上{device}。', { device: words.device })}</Empty></Page>
  )
  const TABS: [Tab, string][] = [['now', t('現在')], ['here', t('這個位置')], ['draft', count ? t('草稿({count})', { count }) : t('草稿')], ['teach', teaching ? t('● 教一次') : t('教一次')]]
  return (
    <Page title={t('即時工作台')} desc={t('看著{device}現在的畫面做事:看懂現在怎麼判斷、框一塊做按鈕或狀態、修正判斷錯的、組規則,或實際操作一次讓它變成腳本。既有的項目會一起顯示和運作;改動先放在草稿,套用才生效。', { device: words.device })}>
      <div className="flex flex-wrap items-center gap-3 text-sm">
        <select className={input} value={cur} disabled={teaching} onChange={e => setDevice(e.target.value)}>
          {devices.map(d => <option key={d} value={d}>{dn(d)}</option>)}</select>
        {teaching ? <Pill tone="red">{t('教學中:在畫面上按,裝置真的會動')}</Pill> : frozen
          ? <><Button onClick={() => { setFrozen(null); setSel(null) }}>{t('▶ 回到即時')}</Button><Pill tone="amber">{t('凍結中 · {p1}', { p1: clock(Number(frozen) / 1000) })}</Pill></>
          : <><Button variant="primary" disabled={freeze.isPending || live.failed} onClick={() => freeze.mutate()}>{freeze.isPending ? t('凍結中…') : t('⏸ 凍結這一張')}</Button><Pill tone="green">{t('即時')}</Pill></>}
        <label className="flex items-center gap-1.5"><input type="checkbox" checked={layers.states} onChange={e => setLayers({ ...layers, states: e.target.checked })} />{t('狀態範圍')}</label>
        <label className="flex items-center gap-1.5"><input type="checkbox" checked={layers.labels} onChange={e => setLayers({ ...layers, labels: e.target.checked })} />{t('顯示名稱和值')}</label>
        <label className="flex items-center gap-1.5" title={t('凍結後才會顯示按鈕和找圖結果')}>
          <input type="checkbox" checked={layers.buttons} onChange={e => setLayers({ ...layers, buttons: e.target.checked })} />{t('按鈕')}</label>
        {!teaching && !!kept.data?.items.length && <label className="flex items-center gap-1.5 ml-auto">{t('之前凍結的')}
          <select className={input} value={frozen ?? ''} onChange={e => { setFrozen(e.target.value || null); setSel(null) }}>
            <option value="">{t('(選一張)')}</option>
            {kept.data.items.map(f => <option key={f.id} value={f.id}>{clock(f.t)}</option>)}</select></label>}
      </div>
      <ErrorText error={freeze.error || (frozen ? frame.error : null) || press.error} />
      <div className="grid lg:grid-cols-[minmax(0,1fr)_380px] gap-4 items-start">
        <div className="flex flex-col gap-2 min-w-0 lg:sticky lg:top-4">
          <Stage src={frozen && !teaching ? wbFrameUrl(cur, frozen) : live.src} states={states} reads={reads} buttons={buttons} layers={layers} hot={hot} sel={sel}
            teaching={teaching} onStart={startMark} onPress={p => press.mutate(p)}
            onMark={box => { setSel(box); setTab('here') }} />
          {live.failed && !frozen && <p className="text-sm text-rose-700">{t('拿不到這個來源的畫面:確認它有開、視窗沒有縮到最小。')}</p>}
          <p className="text-xs text-stone-500">{teaching ? t('按一下 = 點擊、按住 = 長按、拖曳 = 滑動;也可以直接操作{device}本身。', { device: words.device })
            : t('在畫面上框一塊或點一下(會自動凍結),看這裡已經有什麼、要新增什麼。圓點是按鈕,紅圈是這張找不到;把游標移到框上或右邊的名字會標出來。')}</p>
        </div>
        <div className="flex flex-col gap-3 min-w-0">
          <div className="flex gap-1 border-b border-stone-200">
            {TABS.map(([k, label]) => <button key={k} onClick={() => setTab(k)}
              className={`px-3 py-1.5 text-sm rounded-t-md ${tab === k ? 'bg-white border border-b-0 border-stone-200 font-semibold' : 'text-stone-500 hover:text-stone-800'}`}>{label}</button>)}
          </div>
          {tab === 'now' && <>
            <Card title={t('現在的狀態')}>
              <StatesNow states={states} reads={reads} hot={hot} onHot={setHot} running={running} frozen={!!frozen} open={fix} onOpen={setFix} picks={picks} onPick={pick} />
              {fixState && <StateFix state={fixState} read={reads[fixState.id]} device={cur} frame={frozen} sel={sel} doc={doc} onSave={saveDraft} onFreeze={() => freeze.mutate()} onClose={() => setFix(null)} />}
            </Card>
            {!!rulePicks.length && doc && info.data && <RuleForm picks={rulePicks} info={info.data} why={why.data?.items ?? []} doc={doc} onSave={saveDraft} onDone={() => { setPicks(new Set()); setTab('draft') }} />}
            <Card title={t('規則為什麼會動或不動')}><RulesNow items={why.data?.items ?? []} /><ErrorText error={why.error} /></Card>
          </>}
          {tab === 'here' && <HerePanel device={cur} frame={frozen} sel={sel} doc={doc} info={info.data} states={states} onSave={saveDraft}
            onToDraft={() => setTab('draft')} onDigits={id => { setFix(id); setTab('now') }} />}
          {tab === 'draft' && <DraftPanel view={draftView.data} info={info.data} onSave={saveDraft} />}
          {tab === 'teach' && <TeachPanel device={cur} teach={teach.data} doc={doc} info={info.data} onSave={saveDraft} onToDraft={() => setTab('draft')} pressing={press.isPending} onPress={p => press.mutate(p)} />}
        </div>
      </div>
    </Page>
  )
}
