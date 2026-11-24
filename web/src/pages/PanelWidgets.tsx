import { locale, t } from '../i18n'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { api, type ChatBot, type PanelBlock, type PanelListDevice, type PanelOption, type PlanDevice, type PlanEntry, type WidgetData } from '../api'
import { dn } from '../lib/sources'
import { words } from '../lib/project'
import { Modal } from '../components/ui'
import { Icon } from '../components/Icon'
import { Btn, FIELD, Section } from '../components/panelUi'

// Watch widgets of the end users' operation panel (監看元件): what the consultant chose to show, big and plain.
export const TONE: Record<string, string> = {
  green: 'bg-white text-stone-800 border-stone-200', blue: 'bg-white text-stone-800 border-stone-200',
  amber: 'bg-amber-50 text-amber-900 border-amber-200', grey: 'bg-stone-50 text-stone-600 border-stone-200',
  red: 'bg-rose-50 text-rose-900 border-rose-200',
}
export const DOT: Record<string, string> = { green: 'bg-emerald-500', blue: 'bg-accent animate-pulse', amber: 'bg-amber-500', grey: 'bg-stone-400', red: 'bg-rose-500' }
const CODE_TONE: Record<string, string> = {
  success: 'bg-stone-100 text-stone-700', running: 'bg-accent/10 text-accent', partial: 'bg-amber-100 text-amber-900',
  failed: 'bg-rose-100 text-rose-900', interrupted: 'bg-amber-100 text-amber-900', off: 'bg-stone-100 text-stone-500',
}
const when = (tx: number) => new Date(tx * 1000).toLocaleString(locale, { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' })
type Msg = (m: { ok: boolean; text: string }) => void

export function WidgetBlock({ b, devices, onMsg, device }: { b: PanelBlock; devices: string[]; onMsg: Msg; device?: string }) {
  const kind = b.widget?.kind
  return (
    <Section title={b.title} help={b.help} body="p-4 flex flex-col gap-3">
      {b.error ? <div className="text-[0.8125rem] text-rose-700">{b.error}</div>
        : !b.data ? <div className="text-stone-500">{t('讀取中…')}</div>
        : kind === 'devices' ? <Devices data={b.data} />
        : kind === 'incidents' ? <Incidents data={b.data} />
        : kind === 'deploy' ? <Deploy b={b} devices={devices} onMsg={onMsg} />
        : kind === 'schedules' ? <Schedules data={b.data} devices={devices} />
        : kind === 'log' ? <Log data={b.data} />
        : kind === 'chat' ? <Chat data={b.data} onMsg={onMsg} />
        : kind === 'list' ? <ListWidget b={b} onMsg={onMsg} only={device} />
        : kind === 'values' ? <Values data={b.data} devices={device ? [device] : devices} />
        : kind === 'plans' ? <Plans b={b} devices={device ? [device] : devices} onMsg={onMsg} /> : null}
    </Section>
  )
}

/** how each emulator is doing; a small live picture if the consultant allowed it */
export function Devices({ data }: { data: WidgetData }) {
  const [tick, setTick] = useState(0)
  const pictures = (data.devices ?? []).some(d => d.image)
  useEffect(() => { if (!pictures) return; const tx = setInterval(() => setTick(x => x + 1), 3000); return () => clearInterval(tx) }, [pictures])
  return <div className="flex flex-col gap-3">
    {(data.devices ?? []).map(c => (
      <div key={c.device} className={`rounded-lg border px-3 py-2.5 flex flex-wrap gap-3 ${TONE[c.tone]}`}>
        <div className="flex-1 min-w-56">
          <div className="flex items-center gap-2"><span className={`w-3 h-3 rounded-full ${DOT[c.tone]}`} /><b>{dn(c.device)}</b><span className="ml-1">{c.now}</span></div>
          {c.step && <div className="text-[0.8125rem] mt-1">{t('目前這一步:{step}', { step: c.step })}</div>}
          {c.today.length > 0 && <div className="text-[0.8125rem] mt-1 opacity-80">{t('今天:{p1}', { p1: c.today.map(tx => `${tx.name} ${tx.text}`).join(' · ') })}</div>}
          {c.alerts.length > 0 && <div className="text-[0.8125rem] mt-1 flex flex-col">{c.alerts.map((a, i) => <span key={i} className="opacity-80">{when(a.t)} {a.text}</span>)}</div>}
        </div>
        {c.image && <img src={`/api/panel/live/${encodeURIComponent(c.device)}?v=${tick}`} alt={t('{p1} 現在的畫面', { p1: dn(c.device) })}
          className="w-64 max-w-full rounded-lg border border-black/10 bg-black/5 aspect-video object-contain" onError={e => { (e.target as HTMLImageElement).style.visibility = 'hidden' }} />}
      </div>
    ))}
  </div>
}

const STATUS: Record<string, [string, string]> = {
  open: [t('處理中'), 'bg-rose-50 text-rose-700 ring-1 ring-inset ring-rose-200'], resolved: [t('已處理完'), 'text-stone-500'],
  timeout: [t('一直沒有解除,已停止追蹤'), 'bg-amber-50 text-amber-800 ring-1 ring-inset ring-amber-200'], stopped: [t('系統停止時還沒結束'), 'text-stone-500'],
}

/** the urgent incidents: what happened, what was done about it */
function Incidents({ data }: { data: WidgetData }) {
  const [open, setOpen] = useState<string | null>(null)
  const items = data.items ?? []
  if (!items.length) return <div className="text-stone-500">{t('最近沒有緊急事件')}</div>
  return <div className="flex flex-col rounded-md border border-stone-200 divide-y divide-stone-100">
    {items.map(it => {
      const [label, tone] = STATUS[it.status] ?? [it.status, 'text-stone-500']
      return (
        <div key={it.id}>
          <button className="w-full text-left px-3 py-2.5 flex flex-wrap items-center gap-3" onClick={() => setOpen(o => o === it.id ? null : it.id)}>
            <span className="text-stone-500 text-[0.8125rem]">{when(it.start)}</span><b>{dn(it.device)}</b>
            <span className="flex-1">{it.triggers.join(t('、'))}</span>
            <span className={`text-xs px-2 py-0.5 rounded-full ${tone}`}>{label}</span>
          </button>
          {open === it.id && <div className="px-4 pb-4 flex flex-wrap gap-4 border-t border-stone-100 pt-3">
            <ol className="flex-1 min-w-64 flex flex-col gap-1 text-[0.8125rem]">
              {it.story.map((s, i) => <li key={i}><span className="text-stone-400 mr-2">{new Date(s.t * 1000).toLocaleTimeString(locale, { hour: '2-digit', minute: '2-digit', second: '2-digit' })}</span>{s.text}</li>)}
            </ol>
            {it.frame && <img src={`/api/panel/incident/${encodeURIComponent(it.id)}/frame/${encodeURIComponent(it.frame)}`} alt={t('發生當下的畫面')}
              className="w-72 max-w-full rounded-lg border border-stone-200" />}
          </div>}
        </div>
      )
    })}
  </div>
}

/** which main script runs on which emulator, as far as the consultant opened it */
/** 通知與指令: this site's chat bots - add one, invite it, pair a chat, who may give commands. */
function Chat({ data, onMsg }: { data: WidgetData; onMsg: Msg }) {
  const qc = useQueryClient()
  const [adding, setAdding] = useState<string | null>(null)           // the type being added
  const [token, setToken] = useState('')
  const [codes, setCodes] = useState<Record<string, string>>({})
  const [manage, setManage] = useState<string | null>(null)        // the bot whose settings are open
  const done = (text: string) => { onMsg({ ok: true, text }); qc.invalidateQueries({ queryKey: ['panel'] }) }
  const fail = (e: Error) => onMsg({ ok: false, text: e.message })
  const save = useMutation({ mutationFn: (b: { id?: string; type?: string; token: string }) => api.panelChatSave(b), onSuccess: () => { setAdding(null); setToken(''); done(t('已儲存,Bot 連線中')) }, onError: fail })
  const remove = useMutation({ mutationFn: (id: string) => api.panelChatRemove(id), onSuccess: () => done(t('已移除')), onError: fail })
  const pair = useMutation({ mutationFn: (id: string) => api.panelChatPair(id), onSuccess: (r, id) => setCodes(c => ({ ...c, [id]: r.code })), onError: fail })
  const unpair = useMutation({ mutationFn: (x: { id: string; user: string }) => api.panelChatUnpair(x.id, x.user), onSuccess: () => done(t('已移除這個人')), onError: fail })
  const bots = data.bots ?? []
  const state = (b: ChatBot) => !b.enabled ? t('停用中') : b.state === 'ok' ? t('✔ 已連線') : b.state === 'error' ? t('✖ 連不上:{error}', { error: b.error }) : t('連線中…')
  return <div className="flex flex-col gap-3">
    {bots.length === 0 && <div className="text-stone-500">{t('還沒有設定。設定後,緊急事件和腳本的問題會傳到你的手機,也可以從聊天裡下指令。')}</div>}
    {bots.map(b => (
      <div key={b.id} className="rounded-lg border border-stone-200 px-3 py-2.5 flex flex-wrap items-center gap-3">
        <b>{b.name}</b><span className="text-[0.8125rem] text-stone-500">{b.label}</span>
        <span className={`text-[0.8125rem] ${b.state === 'ok' ? 'text-emerald-700' : b.state === 'error' ? 'text-rose-700' : 'text-stone-500'}`}>{state(b)}</span>
        <span className="text-[0.8125rem] text-stone-600">{b.paired ? t('通知送到:{name}', { name: b.chat_name || t('已配對的對話') }) : t('還沒配對')} {t('· 可以下指令的人 {length} 位', { length: b.allowed.length })}</span>
        <span className="flex-1" />
        {(data.setup || data.pair) && <button className="px-3 py-1.5 rounded-lg border border-stone-300 bg-white font-medium flex items-center gap-1" onClick={() => setManage(b.id)}><Icon name="settings" className="w-4 h-4" />{t('管理')}</button>}
      </div>
    ))}
    {manage && bots.find(b => b.id === manage) && (() => { const b = bots.find(x => x.id === manage)!; return (
      <Modal open wide title={b.label.startsWith(b.name) ? b.label : `${b.name}(${b.label})`} onClose={() => setManage(null)}>
        <div className="flex flex-col gap-3 text-sm">
          <div className={`text-[0.8125rem] ${b.state === 'ok' ? 'text-emerald-700' : b.state === 'error' ? 'text-rose-700' : 'text-stone-500'}`}>{state(b)}</div>
        {b.invite && b.type.includes('discord') && <a className="text-[0.8125rem] underline text-indigo-700" href={b.invite} target="_blank" rel="noreferrer">{t('① 把 Bot 加進你的 Discord 伺服器')}</a>}
        {data.pair && <div className="flex flex-wrap items-center gap-3">
          <button className="px-4 py-2 rounded-lg bg-indigo-600 text-white font-medium" disabled={pair.isPending || b.state !== 'ok'} onClick={() => pair.mutate(b.id)}>
            {t('{p1}配對', { p1: b.type.includes('discord') ? '② ' : '' })}</button>
          {codes[b.id] ? <span>{b.type.includes('discord') ? t('在要收通知的頻道傳') : t('在要收通知的對話傳')} <b className="text-sm tracking-widest num">{codes[b.id]}</b>{t('(10 分鐘內有效)')}</span>
            : <span className="text-[0.8125rem] text-stone-600">{b.paired ? t('通知會送到:{name}', { name: b.chat_name || t('已配對的對話') }) : t('還沒配對:按「配對」拿一組數字,傳到你要收通知的地方')}</span>}
        </div>}
        {data.pair && <div className="flex flex-wrap items-center gap-2 text-[0.8125rem]">
          <span className="text-stone-600">{t('可以下指令的人:')}</span>
          {b.allowed.length === 0 && <span className="text-stone-400">{t('(還沒有)')}</span>}
          {b.allowed.map(u => <span key={u.id} className="flex items-center gap-1 bg-stone-100 rounded-lg px-2 py-0.5">{u.name || u.id}
            <button className="text-stone-400 hover:text-rose-600" title={t('移除')} onClick={() => { if (confirm(t('不讓「{p1}」下指令?', { p1: u.name || u.id }))) unpair.mutate({ id: b.id, user: u.id }) }}>✕</button></span>)}
        </div>}
        {data.setup && <details className="text-[0.8125rem]">
          <summary className="cursor-pointer text-stone-500">{t('換 Token(Token 結尾 …{token_end})', { token_end: b.token_end })}</summary>
          <div className="flex flex-wrap gap-2 mt-2">
            <input className="flex-1 min-w-64 border border-stone-300 rounded-lg px-3 py-2 font-mono text-[0.8125rem]" type="password" autoComplete="off" placeholder={t('新的 Bot Token')}
              value={adding === b.id ? token : ''} onChange={e => { setAdding(b.id); setToken(e.target.value) }} />
            <button className="px-4 py-2 rounded-lg bg-stone-800 text-white" disabled={adding !== b.id || !token || save.isPending} onClick={() => save.mutate({ id: b.id, token })}>{t('儲存')}</button>
          </div>
        </details>}
          {data.setup && <button className="self-start text-[0.8125rem] underline text-rose-700" onClick={() => { if (confirm(t('移除「{name}」?之後不會再收到通知,也不能下指令', { name: b.name }))) { remove.mutate(b.id); setManage(null) } }}>{t('移除這個 Bot')}</button>}
        </div>
      </Modal>) })()}
    {data.setup && (data.types ?? []).length > 0 && (adding && !bots.some(b => b.id === adding)
      ? (() => { const tx = data.types!.find(x => x.type === adding)!; return (
        <div className="rounded-lg border border-indigo-200 bg-indigo-50/50 px-3 py-2.5 flex flex-col gap-2">
          <b>{t('新增 {label}', { label: tx.label })}</b>
          <div className="text-[0.8125rem] text-stone-700">{tx.help}</div>
          <div className="flex flex-wrap gap-2">
            <input className="flex-1 min-w-64 border border-stone-300 rounded-lg px-3 py-2 font-mono text-[0.8125rem]" type="password" autoComplete="off" placeholder={t('貼上 Bot Token')}
              value={token} onChange={e => setToken(e.target.value)} />
            <button className="px-4 py-2 rounded-lg bg-indigo-600 text-white font-medium" disabled={!token || save.isPending} onClick={() => save.mutate({ type: tx.type, token })}>{t('儲存')}</button>
            <button className="px-3 py-2 underline text-stone-500" onClick={() => { setAdding(null); setToken('') }}>{t('取消')}</button>
          </div>
        </div>) })()
      : <div className="flex flex-wrap gap-2">{data.types!.map(tx => <button key={tx.type} className="px-4 py-2 rounded-lg border border-stone-300 bg-white"
          onClick={() => { setAdding(tx.type); setToken('') }}>{t('+ 新增 {label}', { label: tx.label })}</button>)}</div>)}
  </div>
}

function Deploy({ b, devices, onMsg }: { b: PanelBlock; devices: string[]; onMsg: Msg }) {
  const qc = useQueryClient()
  const d = b.data!
  const set = useMutation({
    mutationFn: (x: { script: string; device: string; mode: string }) => api.panelDeploy({ block: b.id, ...x }),
    onSuccess: (r, x) => { onMsg({ ok: true, text: t('已改成「{p1}」:{p2}', { p1: d.all_modes?.[r.new] ?? r.new, p2: dn(x.device) }) }); qc.invalidateQueries({ queryKey: ['panel'] }) },
    onError: (e: Error) => onMsg({ ok: false, text: e.message }),
  })
  const tone = (m: string) => m === 'live' ? 'border-emerald-400 bg-emerald-50' : m === 'off' ? 'border-stone-300 bg-stone-50' : 'border-violet-300 bg-violet-50'
  return <div className="flex flex-col gap-3">
    {(d.rows ?? []).map(r => (
      <div key={r.id} className="flex flex-col gap-2">
        <div className="font-medium">{r.name}{r.enabled === false && <span className="text-[0.8125rem] font-normal text-stone-500">{t('(這個腳本目前停用)')}</span>}</div>
        <div className="grid sm:grid-cols-2 gap-2">
          {devices.map(n => {
            const cur = r.modes?.[n] ?? 'shadow'
            return (
              <label key={n} className={`rounded-lg border px-3 py-2 flex items-center gap-3 ${tone(cur)}`}>
                <b className="flex-1">{dn(n)}</b>
                <select className="text-sm border border-stone-300 rounded-lg px-2 py-1 bg-white" value={cur} disabled={set.isPending}
                  onChange={e => {
                    const mode = e.target.value
                    if (mode === 'live' && !confirm(t('讓 {n} 正式執行「{name}」?(會真的點擊)', { n, name: r.name }))) return
                    set.mutate({ script: r.id, device: n, mode })
                  }}>
                  {!(cur in (d.modes ?? {})) && <option value={cur} disabled>{d.all_modes?.[cur] ?? cur}</option>}
                  {Object.entries(d.modes ?? {}).map(([m, tx]) => <option key={m} value={m}>{tx}</option>)}
                </select>
              </label>
            )
          })}
        </div>
      </div>
    ))}
  </div>
}

/** a list's names on each emulator (characters, places ...): scan it, name the new ones, take out the gone ones */
function ListWidget({ b, onMsg, only }: { b: PanelBlock; onMsg: Msg; only?: string }) {
  const d = b.data!
  const per = (d.by_device ?? {}) as Record<string, PanelListDevice>
  const names = Object.keys(per).filter(x => !only || x === only || x === '*')
  const [cur, setCur] = useState(names[0] ?? '')
  const n = names.includes(cur) ? cur : names[0]
  if (!n) return <div className="text-stone-500">{d.per_device ? t('還沒有來源') : t('還沒有項目')}</div>
  return (
    <div className="flex flex-col gap-3">
      {d.per_device && names.length > 1 && <div className="flex flex-wrap gap-2">
        {names.map(x => {
          const miss = per[x].items.filter(i => i.missing_since).length
          return <button key={x} onClick={() => setCur(x)} className={`px-4 py-2 rounded-lg text-sm font-medium border ${x === n ? 'bg-stone-900 text-white border-stone-900' : 'bg-white border-stone-300'}`}>
            {dn(x)}{miss > 0 && <span className="ml-2 text-sm px-2 rounded-full bg-rose-600 text-white">{miss}</span>}</button>
        })}</div>}
      <ListDevice key={n} b={b} device={n} x={per[n]} onMsg={onMsg} />
    </div>
  )
}

function ListDevice({ b, device, x, onMsg }: { b: PanelBlock; device: string; x: PanelListDevice; onMsg: Msg }) {
  const qc = useQueryClient()
  const d = b.data!
  const title = d.title ?? t('清單')
  const [ask, setAsk] = useState<string | null>(null)
  const done = () => qc.invalidateQueries({ queryKey: ['panel'] })
  const item = useMutation({
    mutationFn: (v: { id: string; action: 'rename' | 'keep' | 'remove'; label?: string }) => api.panelListItem(b.id, { device, ...v }),
    onSuccess: (_, v) => { onMsg({ ok: true, text: v.action === 'rename' ? t('名稱已更新') : v.action === 'keep' ? t('已保留,之後照常輪到它') : t('已從清單移除') }); done() },
    onError: (e: Error) => onMsg({ ok: false, text: e.message }),
  })
  const scan = useMutation({
    mutationFn: (if_busy: 'ask' | 'interrupt' | 'queue') => api.panelListScan(b.id, device, if_busy),
    onSuccess: r => {
      const busy = Object.values(r.busy)[0]
      if (busy) { setAsk(busy.name ?? t('別的事')); return }
      setAsk(null)
      const err = Object.values(r.errors ?? {})[0]
      onMsg(err ? { ok: false, text: err } : { ok: true, text: t('已送出:掃描{p1}的{title},約 1~3 分鐘,完成後這裡會更新', { p1: dn(device), title }) })
      done()
    },
    onError: (e: Error) => onMsg({ ok: false, text: e.message }),
  })
  const sc = x.scan
  const missing = x.items.filter(i => i.missing_since)
  const pic = (id: string) => `/api/panel/list/${encodeURIComponent(b.id)}/pic/${encodeURIComponent(device)}/${encodeURIComponent(id)}`
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-3 text-[0.8125rem]">
        <span className="flex-1 min-w-0">{sc
          ? <>{t('上次掃描 {p1}:共', { p1: when(sc.t) })} <b>{sc.total ?? x.items.length}</b> {t('個')}{sc.new.length ? <>{t(',新增')} <b className="text-emerald-700">{sc.new.length}</b> {t('個')}</> : ''}
              {sc.missing.length ? <>,<b className="text-rose-700">{sc.missing.length}</b> {t('個沒看到')}</> : ''}{sc.complete ? '' : t('(沒有掃到底,沒看到的不算)')}</>
          : <span className="text-stone-500">{t('還沒有從面板掃描過(目前清單裡有 {length} 個)', { length: x.items.length })}</span>}</span>
        {d.scan && <button disabled={scan.isPending} onClick={() => { if (confirm(t('現在掃描 {p1} 的{title}?\n會先回到選擇畫面把清單從頭滑到尾,做完再切回來,約 1~3 分鐘,期間這台的主腳本會暫停。', { p1: dn(device), title }))) scan.mutate('ask') }}
          className="px-4 py-2 rounded-lg text-sm font-medium bg-accent text-white disabled:opacity-40 flex items-center gap-2"><Icon name="search" />{scan.isPending ? t('送出中…') : t('掃描{title}', { title })}</button>}
      </div>
      {x.busy && !ask && <div className="text-[0.8125rem] text-stone-500">{t('這台正在做:{busy}', { busy: x.busy })}</div>}
      {ask && <div className="rounded-lg border border-amber-300 bg-amber-50 p-3 text-[0.8125rem] flex flex-col gap-2">
        <div>{t('{p1} 正在做「{ask}」,要怎麼辦?', { p1: dn(device), ask })}</div>
        <div className="flex flex-wrap gap-2">
          <button className="px-4 py-2 rounded-lg bg-rose-600 text-white font-medium" onClick={() => scan.mutate('interrupt')}>{t('停掉它,現在掃描')}</button>
          <button className="px-4 py-2 rounded-lg bg-white border border-stone-300 font-medium" onClick={() => scan.mutate('queue')}>{t('等它做完再掃描')}</button>
          <button className="px-4 py-2 rounded-lg text-stone-600" onClick={() => setAsk(null)}>{t('算了')}</button>
        </div></div>}
      {missing.length > 0 && <div className="rounded-lg border border-rose-300 bg-rose-50 p-3 text-[0.8125rem]">
        {t('有 {length} 個上次掃描沒看到(可能刪掉或改名了):先不會輪到它們。確定不在了就按「移除」;還在的話按「保留」。', { length: missing.length })}</div>}
      <div className="grid sm:grid-cols-2 gap-2">
        {x.items.map(i => (
          <div key={i.id} className={`rounded-lg border p-2 flex items-center gap-3 ${i.missing_since ? 'border-rose-300 bg-rose-50' : i.new ? 'border-emerald-300 bg-emerald-50' : 'border-stone-200'}`}>
            <img src={pic(i.id)} alt="" className="h-8 max-w-[150px] object-contain bg-stone-800 rounded" />
            <div className="flex-1 min-w-0 flex flex-col gap-1">
              {d.rename
                ? <NameInput value={i.label} disabled={item.isPending} onSave={v => item.mutate({ id: i.id, action: 'rename', label: v })} />
                : <span className="text-sm truncate">{i.label}</span>}
              <span className="flex flex-wrap gap-1 text-sm">
                {i.new && <span className="px-2 rounded-full bg-emerald-600 text-white">{t('新')}</span>}
                {i.missing_since && <span className="px-2 rounded-full bg-rose-600 text-white">{t('沒看到')}</span>}
              </span>
            </div>
            {i.missing_since && <button disabled={item.isPending} onClick={() => item.mutate({ id: i.id, action: 'keep' })}
              className="px-3 py-2 rounded-lg bg-white border border-stone-300 font-medium">{t('保留')}</button>}
            {d.remove && <button disabled={item.isPending} onClick={() => { if (confirm(t('把「{label}」從 {p2} 的{title}移除?\n之後不會再輪到它;還在的話,下次掃描會再加回來。', { label: i.label, p2: dn(device), title }))) item.mutate({ id: i.id, action: 'remove' }) }}
              className={`px-3 py-2 rounded-lg font-medium ${i.missing_since ? 'bg-rose-600 text-white' : 'text-stone-500'}`}>{t('移除')}</button>}
          </div>
        ))}
      </div>
    </div>
  )
}

function NameInput({ value, disabled, onSave }: { value: string; disabled: boolean; onSave: (v: string) => void }) {
  const [v, setV] = useState(value)
  useEffect(() => setV(value), [value])
  const save = () => { const tx = v.trim(); if (tx && tx !== value) onSave(tx); else setV(value) }
  return <input value={v} disabled={disabled} onChange={e => setV(e.target.value)} onBlur={save} title={t('改完按 Enter 或點別處就會儲存')}
    onKeyDown={e => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur() }}
    className="text-sm border border-stone-300 rounded-lg px-2 py-1 w-full" />
}

/** today's schedules on each emulator */
const DAYS = () => [t('一'), t('二'), t('三'), t('四'), t('五'), t('六'), t('日')]
const hm = (s?: string) => { const [h, m] = (s ?? '0:0').split(':').map(Number); return h * 60 + m }

/** 每台行程表: one emulator's week - its entries by day and time (the project's schedules shown faintly), which kept
 *  one stands now and until when; add, change, switch off, delete */
function Plans({ b, devices, onMsg }: { b: PanelBlock; devices: string[]; onMsg: Msg }) {
  const data = b.data!
  const [dev, setDev] = useState(devices[0] ?? '')
  const [form, setForm] = useState<PlanEntry | null>(null)
  const [editing, setEditing] = useState<string | null>(null)
  const qc = useQueryClient()
  const d = (data.by_device as Record<string, PlanDevice> | undefined)?.[dev]
  const tasks = data.tasks ?? []
  const save = useMutation({
    mutationFn: (entries: PlanEntry[]) => api.panelPlansSave(b.id, dev, entries),
    onSuccess: () => { setForm(null); setEditing(null); onMsg({ ok: true, text: t('{device} 的行程已儲存', { device: dn(dev) }) }); qc.invalidateQueries({ queryKey: ['panel'] }) },
    onError: (e: Error) => onMsg({ ok: false, text: e.message }),
  })
  if (!d) return <div className="text-stone-500">{t('沒有{device}', { device: words.device })}</div>
  const mine = d.entries.filter(e => e.mine)
  const strip = (e: PlanEntry) => ({ id: e.id, task: e.task, days: e.days, at: e.at, keep: e.keep, enabled: e.enabled, args: e.args })
  const put = (e: PlanEntry) => save.mutate(editing ? mine.map(x => x.id === editing ? e : strip(x)) : [...mine.map(strip), e])
  const days = DAYS()
  const stand = d.entries.find(e => e.id === d.standing)
  const others = (data.schedules ?? []).filter(s => s.devices.includes(dev))
  const blank = (): PlanEntry => { const tk = tasks.find(x => !x.builtin) ?? tasks[0]; return { task: tk?.id ?? '', days: [data.today ?? 0], at: '10:00', keep: !!tk?.keeps, enabled: true, args: {} } }
  return <div className="flex flex-col gap-3">
    <div className="flex flex-wrap items-center gap-2">
      {devices.length > 1 && <select className={FIELD} value={dev} onChange={e => { setDev(e.target.value); setForm(null); setEditing(null) }} aria-label={words.device}>
        {devices.map(n => <option key={n} value={n}>{dn(n)}</option>)}</select>}
      <span className="text-[0.8125rem] text-stone-600">{stand
        ? t('維持中:{name}({what}){until}', { name: stand.name, what: Object.values(stand.labels).join(' · '), until: d.until ? t(',到星期{d} {at}', { d: days[d.until.day], at: d.until.at }) : '' })
        : t('目前照平常的設定')}</span>
      <span className="flex-1" />
      {!form && <Btn size="sm" variant="primary" onClick={() => { setEditing(null); setForm(blank()) }}>{t('+ 新增行程')}</Btn>}
    </div>
    {form && <PlanForm entry={form} tasks={tasks} device={dev} busy={save.isPending} onCancel={() => { setForm(null); setEditing(null) }} onSave={put} />}
    <div className="flex flex-col divide-y divide-stone-100 rounded-lg border border-stone-200">
      {days.map((dn_, k) => {
        const es = d.entries.filter(e => e.days.includes(k)).sort((x, y) => hm(x.at) - hm(y.at))
        const ss = others.filter(s => !s.days.length || s.days.includes(k))
        if (!es.length && !ss.length) return null
        const items = [...es.map(e => ({ at: e.at, e })), ...ss.map(s => ({ at: s.at ?? '', s }))].sort((x, y) => hm(x.at) - hm(y.at))
        return <div key={k} className={`flex gap-3 px-3 py-2 ${k === data.today ? 'bg-accent/5' : ''}`}>
          <span className={`w-10 shrink-0 text-[0.8125rem] ${k === data.today ? 'font-semibold' : 'text-stone-500'}`}>{t('週{d}', { d: dn_ })}</span>
          <div className="flex-1 min-w-0 flex flex-col gap-1">
            {items.map((it, i) => 'e' in it && it.e ? (
              <div key={i} className={`flex flex-wrap items-center gap-2 text-[0.8125rem] ${it.e.enabled ? '' : 'opacity-50'}`}>
                <span className="num w-12">{it.e.at}</span>
                <span className={`px-2 py-0.5 rounded-md ${it.e.id === d.standing ? 'bg-accent/10 text-accent font-medium' : 'bg-stone-100'}`}>
                  {it.e.name}{Object.values(it.e.labels).length ? `:${Object.values(it.e.labels).join(' · ')}` : ''}</span>
                {it.e.keep && it.e.task !== '_reset' && <span className="text-stone-500">{t('維持到下一筆')}</span>}
                {!it.e.mine && <span className="text-stone-400">{t('(來自 {tag})', { tag: it.e.for })}</span>}
                {k === data.today && it.e.status.text && <span className={`px-1.5 rounded ${CODE_TONE[it.e.status.code] ?? 'text-stone-500'}`}>{it.e.status.text}</span>}
                {it.e.mine && <span className="ml-auto flex gap-2 text-stone-500">
                  <button className="hover:text-stone-900" onClick={() => { setEditing(it.e!.id); setForm(strip(it.e!)) }}>{t('修改')}</button>
                  <button className="hover:text-stone-900" onClick={() => save.mutate(mine.map(x => x.id === it.e!.id ? { ...strip(x), enabled: !x.enabled } : strip(x)))}>{it.e.enabled ? t('關掉') : t('打開')}</button>
                  <button className="hover:text-rose-700" onClick={() => save.mutate(mine.filter(x => x.id !== it.e!.id).map(strip))}>{t('刪除')}</button></span>}
              </div>) : 's' in it && it.s ? (
              <div key={i} className="flex items-center gap-2 text-[0.8125rem] text-stone-400">
                <span className="num w-12">{it.s.at}</span><span>{t('{name}(全平台排程)', { name: it.s.name })}</span></div>) : null)}
          </div>
        </div>
      })}
      {!d.entries.length && <div className="px-3 py-3 text-stone-500 text-[0.8125rem]">{t('還沒有行程:按「+ 新增行程」')}</div>}
    </div>
    <span className="text-xs text-stone-500">{t('同一台一次做一件事,後到的等前一件做完;到點 {n} 分鐘內還沒開始就算錯過。「維持到下一筆」:之後回到原位這類動作都照這筆選的,直到下一筆維持的行程。', { n: data.window ?? 10 })}</span>
  </div>
}

function PlanForm({ entry, tasks, device, busy, onCancel, onSave }: {
  entry: PlanEntry; tasks: NonNullable<WidgetData['tasks']>; device: string; busy: boolean; onCancel: () => void; onSave: (e: PlanEntry) => void
}) {
  const [e, setE] = useState(entry)
  const task = tasks.find(x => x.id === e.task)
  const days = DAYS()
  const set = (f: (x: PlanEntry) => PlanEntry) => setE(x => f(x))
  const ok = !!task && e.days.length > 0 && /^\d\d:\d\d$/.test(e.at) && task.params.every(p => e.args[p.name] !== undefined)
  const pick = (opts: PanelOption[], v: unknown) => opts.findIndex(o => JSON.stringify(o.value) === JSON.stringify(v))
  return <div className="rounded-lg border border-accent/40 bg-accent/5 p-3 flex flex-col gap-2 text-[0.8125rem]">
    <div className="flex flex-wrap items-center gap-2">
      <select className={FIELD} value={e.task} onChange={ev => { const tk = tasks.find(x => x.id === ev.target.value); set(x => ({ ...x, task: ev.target.value, args: {}, keep: !!tk?.keeps })) }}>
        {tasks.map(x => <option key={x.id} value={x.id}>{x.name}</option>)}</select>
      <input type="time" className={`${FIELD} num`} value={e.at} onChange={ev => set(x => ({ ...x, at: ev.target.value }))} />
    </div>
    <div className="flex flex-wrap items-center gap-1">
      {days.map((dd, k) => <button key={k} className={`w-8 h-8 rounded-md border ${e.days.includes(k) ? 'bg-accent text-white border-accent' : 'border-stone-300'}`}
        onClick={() => set(x => ({ ...x, days: x.days.includes(k) ? x.days.filter(y => y !== k) : [...x.days, k].sort() }))}>{dd}</button>)}
      <button className="ml-2 text-stone-600 hover:underline" onClick={() => set(x => ({ ...x, days: [0, 1, 2, 3, 4, 5, 6] }))}>{t('每天')}</button>
      <button className="text-stone-600 hover:underline" onClick={() => set(x => ({ ...x, days: [0, 1, 2, 3, 4] }))}>{t('平日')}</button>
      <button className="text-stone-600 hover:underline" onClick={() => set(x => ({ ...x, days: [5, 6] }))}>{t('週末')}</button>
    </div>
    {task?.params.map(p => {
      const opts = p.options[device] ?? []
      const groups = opts.reduce<[string, number[]][]>((g, o, i) => { const f = (o as PanelOption & { folder?: string }).folder ?? ''; const l = g.at(-1); if (l && l[0] === f) l[1].push(i); else g.push([f, [i]]); return g }, [])
      return <label key={p.name} className="flex flex-wrap items-center gap-2">{p.label}
        <select className={`${FIELD} max-w-64`} value={pick(opts, e.args[p.name])} onChange={ev => { const o = opts[Number(ev.target.value)]; set(x => ({ ...x, args: { ...x.args, [p.name]: o?.value } })) }}>
          <option value={-1}>{t('(請選擇)')}</option>
          {groups.map(([f, ix], k) => f ? <optgroup key={k} label={f}>{ix.map(i => <option key={i} value={i}>{opts[i].label}</option>)}</optgroup>
            : ix.map(i => <option key={i} value={i}>{opts[i].label}</option>))}
        </select></label>
    })}
    {task && task.keeps && task.id !== '_reset' && <div className="flex flex-wrap gap-4">
      <label className="flex items-center gap-1"><input type="radio" checked={!e.keep} onChange={() => set(x => ({ ...x, keep: false }))} />{t('只做一次')}</label>
      <label className="flex items-center gap-1"><input type="radio" checked={e.keep} onChange={() => set(x => ({ ...x, keep: true }))} />{t('維持到下一筆')}</label>
    </div>}
    {task?.id === '_reset' && <span className="text-stone-500">{t('結束目前維持的行程,回到平常的設定(不執行任何動作)')}</span>}
    <div className="flex gap-2"><Btn size="sm" variant="primary" disabled={!ok || busy} onClick={() => onSave(e)}>{busy ? t('儲存中…') : t('儲存')}</Btn>
      <Btn size="sm" variant="ghost" onClick={onCancel}>{t('取消')}</Btn></div>
  </div>
}

function Schedules({ data, devices }: { data: WidgetData; devices: string[] }) {
  const rows = data.rows ?? []
  if (!rows.length) return <div className="text-stone-500">{t('沒有排程')}</div>
  return <div className="flex flex-col gap-3">
    {rows.map(r => (
      <div key={r.id} className="rounded-lg border border-stone-200 px-3 py-2.5 flex flex-col gap-2">
        <div className="flex items-center gap-3"><b className="flex-1">{r.name}</b>
          <span className="text-[0.8125rem] text-stone-500">{r.enabled === false ? t('已關閉') : t('每天 {at}', { at: r.at })}</span></div>
        <div className="flex flex-col gap-1">
          {devices.filter(n => r.devices?.[n]).map(n => (
            <div key={n} className="flex flex-wrap items-baseline gap-2 text-[0.8125rem]">
              <span className="w-32 shrink-0">{dn(n)}</span>
              <span className={`px-2 py-0.5 rounded-lg ${CODE_TONE[r.devices![n].code] ?? 'bg-stone-100 text-stone-700'}`}>{r.devices![n].text}</span>
            </div>
          ))}
        </div>
      </div>
    ))}
  </div>
}

// a number in this range is a moment ("last time" variables), 2001 - 2099; same as server/panel_start.py
const moment = (v: unknown) => typeof v === 'number' && v >= 1e9 && v < 4.1e9
const shown = (v: unknown) => v == null || v === '' ? '—' : moment(v) ? when(v as number) : typeof v === 'number' ? v.toLocaleString(locale) : String(v)

/** what the scripts' variables are now: a shared one once, the others on each emulator */
function Values({ data, devices }: { data: WidgetData; devices: string[] }) {
  const vars = data.vars ?? []
  const own = vars.filter(v => !v.shared)
  return <div className="flex flex-col gap-3">
    {!data.running && <div className="text-[0.8125rem] text-stone-500">{t('系統沒有在執行,看不到現在的值')}</div>}
    {vars.filter(v => v.shared).map(v => (
      <div key={v.name} className="flex items-baseline gap-3"><span className="flex-1 text-stone-600">{v.label}</span><b className="num text-base">{shown(data.shared?.[v.name])}</b></div>))}
    {own.length > 0 && <div className="overflow-x-auto"><table className="w-full text-[0.8125rem]">
      <thead><tr className="text-left text-stone-500">{[words.device, ...own.map(v => v.label)].map((h, i) => <th key={i} className="font-normal pb-1 pr-3">{h}</th>)}</tr></thead>
      <tbody>{devices.map(n => <tr key={n} className="border-t border-stone-100">
        <td className="py-1.5 pr-3">{dn(n)}</td>
        {own.map(v => <td key={v.name} className="py-1.5 pr-3 num font-medium">{shown(data.values?.[n]?.[v.name])}</td>)}
      </tr>)}</tbody>
    </table></div>}
  </div>
}

const LEVEL: Record<string, string> = { warn: 'text-rose-800', info: 'text-stone-700', panel: 'text-sky-800' }

/** what happened lately */
function Log({ data }: { data: WidgetData }) {
  const rows = data.rows ?? []
  if (!rows.length) return <div className="text-stone-500">{t('還沒有紀錄')}</div>
  return <div className="flex flex-col gap-1">
    {rows.map((r, i) => (
      <div key={i} className={`text-[0.8125rem] ${LEVEL[r.level ?? 'info'] ?? ''}`}>
        <span className="text-stone-400 mr-2">{when(r.t ?? 0)}</span>{r.device && <b className="mr-2">{dn(r.device)}</b>}{r.text}
      </div>
    ))}
  </div>
}
