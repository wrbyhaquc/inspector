import { locale, t } from '../i18n'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { api, type ChatBot, type PanelBlock, type PanelListDevice, type WidgetData } from '../api'
import { dn } from '../lib/sources'
import { Modal } from '../components/ui'
import { Icon } from '../components/Icon'

// Watch widgets of the end users' operation panel (監看元件): what the consultant chose to show, big and plain.
export const TONE: Record<string, string> = {
  green: 'bg-emerald-50 text-emerald-900 border-emerald-300', blue: 'bg-sky-50 text-sky-900 border-sky-300',
  amber: 'bg-amber-50 text-amber-900 border-amber-300', grey: 'bg-stone-100 text-stone-600 border-stone-300',
  red: 'bg-rose-50 text-rose-900 border-rose-400',
}
export const DOT: Record<string, string> = { green: 'bg-emerald-500', blue: 'bg-sky-500 animate-pulse', amber: 'bg-amber-500', grey: 'bg-stone-400', red: 'bg-rose-500' }
const CODE_TONE: Record<string, string> = {
  success: 'bg-emerald-100 text-emerald-900', running: 'bg-sky-100 text-sky-900', partial: 'bg-amber-100 text-amber-900',
  failed: 'bg-rose-100 text-rose-900', interrupted: 'bg-amber-100 text-amber-900', off: 'bg-stone-100 text-stone-500',
}
const when = (tx: number) => new Date(tx * 1000).toLocaleString(locale, { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' })
type Msg = (m: { ok: boolean; text: string }) => void

export function WidgetBlock({ b, devices, onMsg, device }: { b: PanelBlock; devices: string[]; onMsg: Msg; device?: string }) {
  const kind = b.widget?.kind
  return (
    <section className="bg-white rounded-2xl border border-stone-200 p-4 flex flex-col gap-3">
      <div><h2 className="text-xl font-bold">{b.title}</h2>{b.help && <div className="text-base text-stone-500">{b.help}</div>}</div>
      {b.error ? <div className="text-base text-rose-700">{b.error}</div>
        : !b.data ? <div className="text-stone-500">{t('讀取中…')}</div>
        : kind === 'devices' ? <Devices data={b.data} />
        : kind === 'incidents' ? <Incidents data={b.data} />
        : kind === 'deploy' ? <Deploy b={b} devices={devices} onMsg={onMsg} />
        : kind === 'schedules' ? <Schedules data={b.data} devices={devices} />
        : kind === 'log' ? <Log data={b.data} />
        : kind === 'chat' ? <Chat data={b.data} onMsg={onMsg} />
        : kind === 'list' ? <ListWidget b={b} onMsg={onMsg} only={device} /> : null}
    </section>
  )
}

/** how each emulator is doing; a small live picture if the consultant allowed it */
export function Devices({ data }: { data: WidgetData }) {
  const [tick, setTick] = useState(0)
  const pictures = (data.devices ?? []).some(d => d.image)
  useEffect(() => { if (!pictures) return; const tx = setInterval(() => setTick(x => x + 1), 3000); return () => clearInterval(tx) }, [pictures])
  return <div className="flex flex-col gap-3">
    {(data.devices ?? []).map(c => (
      <div key={c.device} className={`rounded-xl border-2 px-4 py-3 flex flex-wrap gap-3 ${TONE[c.tone]}`}>
        <div className="flex-1 min-w-56">
          <div className="flex items-center gap-2"><span className={`w-3 h-3 rounded-full ${DOT[c.tone]}`} /><b>{dn(c.device)}</b><span className="ml-1">{c.now}</span></div>
          {c.step && <div className="text-base mt-1">{t('目前這一步:{step}', { step: c.step })}</div>}
          {c.today.length > 0 && <div className="text-base mt-1 opacity-80">{t('今天:{p1}', { p1: c.today.map(tx => `${tx.name} ${tx.text}`).join(' · ') })}</div>}
          {c.alerts.length > 0 && <div className="text-base mt-1 flex flex-col">{c.alerts.map((a, i) => <span key={i} className="opacity-80">{when(a.t)} {a.text}</span>)}</div>}
        </div>
        {c.image && <img src={`/api/panel/live/${encodeURIComponent(c.device)}?v=${tick}`} alt={t('{p1} 現在的畫面', { p1: dn(c.device) })}
          className="w-64 max-w-full rounded-lg border border-black/10 bg-black/5 aspect-video object-contain" onError={e => { (e.target as HTMLImageElement).style.visibility = 'hidden' }} />}
      </div>
    ))}
  </div>
}

const STATUS: Record<string, [string, string]> = {
  open: [t('處理中'), 'bg-rose-100 text-rose-900'], resolved: [t('已處理完'), 'bg-emerald-100 text-emerald-900'],
  timeout: [t('一直沒有解除,已停止追蹤'), 'bg-amber-100 text-amber-900'], stopped: [t('系統停止時還沒結束'), 'bg-stone-100 text-stone-700'],
}

/** the urgent incidents: what happened, what was done about it */
function Incidents({ data }: { data: WidgetData }) {
  const [open, setOpen] = useState<string | null>(null)
  const items = data.items ?? []
  if (!items.length) return <div className="text-stone-500">{t('最近沒有緊急事件')}</div>
  return <div className="flex flex-col gap-2">
    {items.map(it => {
      const [label, tone] = STATUS[it.status] ?? [it.status, 'bg-stone-100 text-stone-700']
      return (
        <div key={it.id} className="rounded-xl border border-stone-200">
          <button className="w-full text-left px-4 py-3 flex flex-wrap items-center gap-3" onClick={() => setOpen(o => o === it.id ? null : it.id)}>
            <span className="text-stone-500 text-base">{when(it.start)}</span><b>{dn(it.device)}</b>
            <span className="flex-1">{it.triggers.join(t('、'))}</span>
            <span className={`text-base px-2 py-0.5 rounded-lg ${tone}`}>{label}</span>
          </button>
          {open === it.id && <div className="px-4 pb-4 flex flex-wrap gap-4 border-t border-stone-100 pt-3">
            <ol className="flex-1 min-w-64 flex flex-col gap-1 text-base">
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
      <div key={b.id} className="rounded-xl border-2 border-stone-200 px-4 py-3 flex flex-wrap items-center gap-3">
        <b>{b.name}</b><span className="text-base text-stone-500">{b.label}</span>
        <span className={`text-base ${b.state === 'ok' ? 'text-emerald-700' : b.state === 'error' ? 'text-rose-700' : 'text-stone-500'}`}>{state(b)}</span>
        <span className="text-base text-stone-600">{b.paired ? t('通知送到:{name}', { name: b.chat_name || t('已配對的對話') }) : t('還沒配對')} {t('· 可以下指令的人 {length} 位', { length: b.allowed.length })}</span>
        <span className="flex-1" />
        {(data.setup || data.pair) && <button className="px-3 py-1.5 rounded-lg border-2 border-stone-300 bg-white font-bold flex items-center gap-1" onClick={() => setManage(b.id)}><Icon name="settings" className="w-4 h-4" />{t('管理')}</button>}
      </div>
    ))}
    {manage && bots.find(b => b.id === manage) && (() => { const b = bots.find(x => x.id === manage)!; return (
      <Modal open wide title={b.label.startsWith(b.name) ? b.label : `${b.name}(${b.label})`} onClose={() => setManage(null)}>
        <div className="flex flex-col gap-3 text-lg">
          <div className={`text-base ${b.state === 'ok' ? 'text-emerald-700' : b.state === 'error' ? 'text-rose-700' : 'text-stone-500'}`}>{state(b)}</div>
        {b.invite && b.type.includes('discord') && <a className="text-base underline text-indigo-700" href={b.invite} target="_blank" rel="noreferrer">{t('① 把 Bot 加進你的 Discord 伺服器')}</a>}
        {data.pair && <div className="flex flex-wrap items-center gap-3">
          <button className="px-4 py-2 rounded-xl bg-indigo-600 text-white font-bold" disabled={pair.isPending || b.state !== 'ok'} onClick={() => pair.mutate(b.id)}>
            {t('{p1}配對', { p1: b.type.includes('discord') ? '② ' : '' })}</button>
          {codes[b.id] ? <span>{b.type.includes('discord') ? t('在要收通知的頻道傳') : t('在要收通知的對話傳')} <b className="text-2xl tracking-widest num">{codes[b.id]}</b>{t('(10 分鐘內有效)')}</span>
            : <span className="text-base text-stone-600">{b.paired ? t('通知會送到:{name}', { name: b.chat_name || t('已配對的對話') }) : t('還沒配對:按「配對」拿一組數字,傳到你要收通知的地方')}</span>}
        </div>}
        {data.pair && <div className="flex flex-wrap items-center gap-2 text-base">
          <span className="text-stone-600">{t('可以下指令的人:')}</span>
          {b.allowed.length === 0 && <span className="text-stone-400">{t('(還沒有)')}</span>}
          {b.allowed.map(u => <span key={u.id} className="flex items-center gap-1 bg-stone-100 rounded-lg px-2 py-0.5">{u.name || u.id}
            <button className="text-stone-400 hover:text-rose-600" title={t('移除')} onClick={() => { if (confirm(t('不讓「{p1}」下指令?', { p1: u.name || u.id }))) unpair.mutate({ id: b.id, user: u.id }) }}>✕</button></span>)}
        </div>}
        {data.setup && <details className="text-base">
          <summary className="cursor-pointer text-stone-500">{t('換 Token(Token 結尾 …{token_end})', { token_end: b.token_end })}</summary>
          <div className="flex flex-wrap gap-2 mt-2">
            <input className="flex-1 min-w-64 border border-stone-300 rounded-lg px-3 py-2 font-mono text-base" type="password" autoComplete="off" placeholder={t('新的 Bot Token')}
              value={adding === b.id ? token : ''} onChange={e => { setAdding(b.id); setToken(e.target.value) }} />
            <button className="px-4 py-2 rounded-xl bg-stone-800 text-white" disabled={adding !== b.id || !token || save.isPending} onClick={() => save.mutate({ id: b.id, token })}>{t('儲存')}</button>
          </div>
        </details>}
          {data.setup && <button className="self-start text-base underline text-rose-700" onClick={() => { if (confirm(t('移除「{name}」?之後不會再收到通知,也不能下指令', { name: b.name }))) { remove.mutate(b.id); setManage(null) } }}>{t('移除這個 Bot')}</button>}
        </div>
      </Modal>) })()}
    {data.setup && (data.types ?? []).length > 0 && (adding && !bots.some(b => b.id === adding)
      ? (() => { const tx = data.types!.find(x => x.type === adding)!; return (
        <div className="rounded-xl border-2 border-indigo-200 bg-indigo-50/50 px-4 py-3 flex flex-col gap-2">
          <b>{t('新增 {label}', { label: tx.label })}</b>
          <div className="text-base text-stone-700">{tx.help}</div>
          <div className="flex flex-wrap gap-2">
            <input className="flex-1 min-w-64 border border-stone-300 rounded-lg px-3 py-2 font-mono text-base" type="password" autoComplete="off" placeholder={t('貼上 Bot Token')}
              value={token} onChange={e => setToken(e.target.value)} />
            <button className="px-4 py-2 rounded-xl bg-indigo-600 text-white font-bold" disabled={!token || save.isPending} onClick={() => save.mutate({ type: tx.type, token })}>{t('儲存')}</button>
            <button className="px-3 py-2 underline text-stone-500" onClick={() => { setAdding(null); setToken('') }}>{t('取消')}</button>
          </div>
        </div>) })()
      : <div className="flex flex-wrap gap-2">{data.types!.map(tx => <button key={tx.type} className="px-4 py-2 rounded-xl border-2 border-stone-300 bg-white"
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
        <div className="font-bold">{r.name}{r.enabled === false && <span className="text-base font-normal text-stone-500">{t('(這個腳本目前停用)')}</span>}</div>
        <div className="grid sm:grid-cols-2 gap-2">
          {devices.map(n => {
            const cur = r.modes?.[n] ?? 'shadow'
            return (
              <label key={n} className={`rounded-xl border-2 px-3 py-2 flex items-center gap-3 ${tone(cur)}`}>
                <b className="flex-1">{dn(n)}</b>
                <select className="text-lg border border-stone-300 rounded-lg px-2 py-1 bg-white" value={cur} disabled={set.isPending}
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
  const per = d.by_device ?? {}
  const names = Object.keys(per).filter(x => !only || x === only || x === '*')
  const [cur, setCur] = useState(names[0] ?? '')
  const n = names.includes(cur) ? cur : names[0]
  if (!n) return <div className="text-stone-500">{d.per_device ? t('還沒有來源') : t('還沒有項目')}</div>
  return (
    <div className="flex flex-col gap-3">
      {d.per_device && names.length > 1 && <div className="flex flex-wrap gap-2">
        {names.map(x => {
          const miss = per[x].items.filter(i => i.missing_since).length
          return <button key={x} onClick={() => setCur(x)} className={`px-4 py-2 rounded-xl text-lg font-bold border-2 ${x === n ? 'bg-stone-900 text-white border-stone-900' : 'bg-white border-stone-300'}`}>
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
      <div className="flex flex-wrap items-center gap-3 text-base">
        <span className="flex-1 min-w-0">{sc
          ? <>{t('上次掃描 {p1}:共', { p1: when(sc.t) })} <b>{sc.total ?? x.items.length}</b> {t('個')}{sc.new.length ? <>{t(',新增')} <b className="text-emerald-700">{sc.new.length}</b> {t('個')}</> : ''}
              {sc.missing.length ? <>,<b className="text-rose-700">{sc.missing.length}</b> {t('個沒看到')}</> : ''}{sc.complete ? '' : t('(沒有掃到底,沒看到的不算)')}</>
          : <span className="text-stone-500">{t('還沒有從面板掃描過(目前清單裡有 {length} 個)', { length: x.items.length })}</span>}</span>
        {d.scan && <button disabled={scan.isPending} onClick={() => { if (confirm(t('現在掃描 {p1} 的{title}?\n會先回到選擇畫面把清單從頭滑到尾,做完再切回來,約 1~3 分鐘,期間這台的主腳本會暫停。', { p1: dn(device), title }))) scan.mutate('ask') }}
          className="px-5 py-3 rounded-xl text-lg font-bold bg-sky-600 text-white disabled:opacity-40 flex items-center gap-2"><Icon name="search" />{scan.isPending ? t('送出中…') : t('掃描{title}', { title })}</button>}
      </div>
      {x.busy && !ask && <div className="text-base text-stone-500">{t('這台正在做:{busy}', { busy: x.busy })}</div>}
      {ask && <div className="rounded-xl border-2 border-amber-300 bg-amber-50 p-3 text-base flex flex-col gap-2">
        <div>{t('{p1} 正在做「{ask}」,要怎麼辦?', { p1: dn(device), ask })}</div>
        <div className="flex flex-wrap gap-2">
          <button className="px-4 py-2 rounded-lg bg-rose-600 text-white font-bold" onClick={() => scan.mutate('interrupt')}>{t('停掉它,現在掃描')}</button>
          <button className="px-4 py-2 rounded-lg bg-white border border-stone-300 font-bold" onClick={() => scan.mutate('queue')}>{t('等它做完再掃描')}</button>
          <button className="px-4 py-2 rounded-lg text-stone-600" onClick={() => setAsk(null)}>{t('算了')}</button>
        </div></div>}
      {missing.length > 0 && <div className="rounded-xl border-2 border-rose-300 bg-rose-50 p-3 text-base">
        {t('有 {length} 個上次掃描沒看到(可能刪掉或改名了):先不會輪到它們。確定不在了就按「移除」;還在的話按「保留」。', { length: missing.length })}</div>}
      <div className="grid sm:grid-cols-2 gap-2">
        {x.items.map(i => (
          <div key={i.id} className={`rounded-xl border-2 p-2 flex items-center gap-3 ${i.missing_since ? 'border-rose-300 bg-rose-50' : i.new ? 'border-emerald-300 bg-emerald-50' : 'border-stone-200'}`}>
            <img src={pic(i.id)} alt="" className="h-8 max-w-[150px] object-contain bg-stone-800 rounded" />
            <div className="flex-1 min-w-0 flex flex-col gap-1">
              {d.rename
                ? <NameInput value={i.label} disabled={item.isPending} onSave={v => item.mutate({ id: i.id, action: 'rename', label: v })} />
                : <span className="text-lg truncate">{i.label}</span>}
              <span className="flex flex-wrap gap-1 text-sm">
                {i.new && <span className="px-2 rounded-full bg-emerald-600 text-white">{t('新')}</span>}
                {i.missing_since && <span className="px-2 rounded-full bg-rose-600 text-white">{t('沒看到')}</span>}
              </span>
            </div>
            {i.missing_since && <button disabled={item.isPending} onClick={() => item.mutate({ id: i.id, action: 'keep' })}
              className="px-3 py-2 rounded-lg bg-white border border-stone-300 font-bold">{t('保留')}</button>}
            {d.remove && <button disabled={item.isPending} onClick={() => { if (confirm(t('把「{label}」從 {p2} 的{title}移除?\n之後不會再輪到它;還在的話,下次掃描會再加回來。', { label: i.label, p2: dn(device), title }))) item.mutate({ id: i.id, action: 'remove' }) }}
              className={`px-3 py-2 rounded-lg font-bold ${i.missing_since ? 'bg-rose-600 text-white' : 'text-stone-500'}`}>{t('移除')}</button>}
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
    className="text-lg border border-stone-300 rounded-lg px-2 py-1 w-full" />
}

/** today's schedules on each emulator */
function Schedules({ data, devices }: { data: WidgetData; devices: string[] }) {
  const rows = data.rows ?? []
  if (!rows.length) return <div className="text-stone-500">{t('沒有排程')}</div>
  return <div className="flex flex-col gap-3">
    {rows.map(r => (
      <div key={r.id} className="rounded-xl border border-stone-200 px-4 py-3 flex flex-col gap-2">
        <div className="flex items-center gap-3"><b className="flex-1">{r.name}</b>
          <span className="text-base text-stone-500">{r.enabled === false ? t('已關閉') : t('每天 {at}', { at: r.at })}</span></div>
        <div className="flex flex-col gap-1">
          {devices.filter(n => r.devices?.[n]).map(n => (
            <div key={n} className="flex flex-wrap items-baseline gap-2 text-base">
              <span className="w-32 shrink-0">{dn(n)}</span>
              <span className={`px-2 py-0.5 rounded-lg ${CODE_TONE[r.devices![n].code] ?? 'bg-stone-100 text-stone-700'}`}>{r.devices![n].text}</span>
            </div>
          ))}
        </div>
      </div>
    ))}
  </div>
}

const LEVEL: Record<string, string> = { warn: 'text-rose-800', info: 'text-stone-700', panel: 'text-sky-800' }

/** what happened lately */
function Log({ data }: { data: WidgetData }) {
  const rows = data.rows ?? []
  if (!rows.length) return <div className="text-stone-500">{t('還沒有紀錄')}</div>
  return <div className="flex flex-col gap-1">
    {rows.map((r, i) => (
      <div key={i} className={`text-base ${LEVEL[r.level ?? 'info'] ?? ''}`}>
        <span className="text-stone-400 mr-2">{when(r.t ?? 0)}</span>{r.device && <b className="mr-2">{dn(r.device)}</b>}{r.text}
      </div>
    ))}
  </div>
}
