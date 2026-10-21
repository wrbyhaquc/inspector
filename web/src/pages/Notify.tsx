import { locale, t } from '../i18n'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api, type BotInfo, type NotifyChannel, type NotifyInfo } from '../api'
import { Button, Card, Empty, ErrorText } from '../components/ui'
import { SourcePick } from '../components/SourcePick'

const input = 'border border-stone-300 rounded-md px-2 py-1 text-sm bg-white'
const clone = <T,>(v: T): T => JSON.parse(JSON.stringify(v))
const when = (tx?: number) => tx ? new Date(tx * 1000).toLocaleString(locale, { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : ''

/** 執行 › 通知: where to tell people what happened (Discord ...). Kept where it runs: the addresses are secrets. */
export function NotifySettings({ devices }: { devices: string[] }) {
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['notify'], queryFn: api.notify, refetchInterval: 10000 })
  const [draft, setDraft] = useState<{ channels: NotifyChannel[]; merge_minutes: number } | null>(null)
  const info = q.data
  const cur = draft ?? (info ? { channels: info.channels, merge_minutes: info.merge_minutes } : null)
  const dirty = !!draft && JSON.stringify(draft) !== JSON.stringify({ channels: info?.channels, merge_minutes: info?.merge_minutes })
  const save = useMutation({ mutationFn: () => api.notifySave(cur!), onSuccess: () => { setDraft(null); qc.invalidateQueries({ queryKey: ['notify'] }) } })
  const edit = (fn: (d: { channels: NotifyChannel[]; merge_minutes: number }) => void) => setDraft(() => { const n = clone(cur!); fn(n); return n })
  if (!info || !cur) return <Card><Empty>{q.isLoading ? t('讀取中…') : t('讀取失敗')}</Empty></Card>
  const add = (type: string) => edit(d => {
    let k = 1
    while (d.channels.some(c => c.id === `${type}${k}`)) k++
    d.channels.push({ id: `${type}${k}`, name: `${info.types[type].label} ${k}`, type, enabled: true, config: {}, kinds: [...info.default_kinds], devices: [], quiet: null, image: true })
  })
  return (
    <div className="flex flex-col gap-3">
      <Card title={t('通知設定')} extra={<span className="text-xs text-stone-500">{t('緊急事件、失敗、腳本的「通知」送到你常用的地方')}</span>}>
        <div className="flex flex-wrap items-center gap-3 text-sm">
          <label className="flex items-center gap-1" title={t('同一台的同一件事,在這段時間內只送一次;下一次送出時會說中間又發生了幾次')}>{t('同樣的事')}
            <input type="number" min={0} max={240} className={`${input} w-16`} value={cur.merge_minutes} onChange={e => edit(d => { d.merge_minutes = Number(e.target.value) || 0 })} />
            {t('分鐘內只送一次')}</label>
          <span className="flex-1" />
          {Object.entries(info.types).map(([k, tx]) => <Button key={k} onClick={() => add(k)}>{t('+ 新增 {label}', { label: tx.label })}</Button>)}
          {dirty && <><Button variant="primary" disabled={save.isPending} onClick={() => save.mutate()}>{save.isPending ? t('儲存中…') : t('儲存')}</Button>
            <Button variant="ghost" onClick={() => setDraft(null)}>{t('放棄修改')}</Button></>}
        </div>
        <ErrorText error={save.error} />
      </Card>
      {!cur.channels.length && <Card><Empty>{t('還沒有通知管道。按「+ 新增 Discord」開始。')}</Empty></Card>}
      {cur.channels.map((c, i) => (
        <ChannelCard key={c.id} c={c} info={info} devices={devices} saved={info.channels.find(x => x.id === c.id)} dirty={dirty}
          onChange={fn => edit(d => fn(d.channels[i]))} onDelete={() => { if (confirm(t('刪除「{name}」?', { name: c.name }))) edit(d => { d.channels.splice(i, 1) }) }} />
      ))}
      {cur.channels.some(c => info.types[c.type]?.listens) && <CommandLog />}
    </div>
  )
}

function ChannelCard({ c, info, devices, saved, dirty, onChange, onDelete }: {
  c: NotifyChannel; info: NotifyInfo; devices: string[]; saved?: NotifyChannel; dirty: boolean
  onChange: (fn: (c: NotifyChannel) => void) => void; onDelete: () => void
}) {
  const tx = info.types[c.type]
  const st = info.status[c.id]
  const test = useMutation({ mutationFn: () => api.notifyTest(c.id) })
  const toggle = (k: 'kinds' | 'devices', v: string, on: boolean) => onChange(x => { x[k] = on ? [...x[k], v] : x[k].filter(y => y !== v) })
  return (
    <div className={`bg-white border rounded-lg p-3 flex flex-col gap-3 text-sm ${c.enabled ? 'border-stone-300' : 'border-stone-200 opacity-70'}`}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs px-1.5 py-0.5 rounded bg-indigo-600 text-white">{tx?.label ?? c.type}</span>
        <input className={`${input} w-48 font-medium`} value={c.name} onChange={e => onChange(x => { x.name = e.target.value })} />
        <label className="flex items-center gap-1"><input type="checkbox" checked={c.enabled} onChange={e => onChange(x => { x.enabled = e.target.checked })} />{t('啟用')}</label>
        <span className="flex-1" />
        {st?.last_ok && <span className="text-xs text-emerald-700">{t('上次送出 {p1}', { p1: when(st.last_ok) })}</span>}
        {st?.error && (!st.last_ok || (st.last_error ?? 0) > st.last_ok) && <span className="text-xs text-rose-700" title={st.error}>{t('上次失敗 {p1}:{p2}', { p1: when(st.last_error), p2: st.error.slice(0, 60) })}</span>}
        <Button disabled={!saved || dirty || test.isPending} onClick={() => test.mutate()} title={!saved || dirty ? t('先儲存再測試') : undefined}>{test.isPending ? t('送出中…') : t('送測試訊息')}</Button>
        <Button variant="ghost" onClick={onDelete}>{t('刪除')}</Button>
      </div>
      {test.isSuccess && <div className="text-xs text-emerald-700">{t('已送出,去 {label} 看看有沒有收到。', { label: tx?.label })}</div>}
      <ErrorText error={test.error} />
      {tx && <div className="text-xs text-stone-600 bg-stone-50 rounded px-2 py-1.5">{tx.help}</div>}
      {tx?.listens && saved && !dirty && <BotPanel id={c.id} enabled={c.enabled} />}
      <div className="grid md:grid-cols-2 gap-2">
        {tx?.fields.map(f => (
          <label key={f.name} className="flex flex-col gap-1"><span className="text-stone-600">{f.label}{f.secret && <span className="text-xs text-stone-400">{t('(儲存後只顯示最後幾碼)')}</span>}</span>
            <input className={`${input} font-mono`} placeholder={f.placeholder} value={String(c.config[f.name] ?? '')} type={f.secret ? 'password' : 'text'} autoComplete="off"
              onFocus={e => { if (f.secret && String(c.config[f.name] ?? '').startsWith('••')) e.target.select() }}
              onChange={e => onChange(x => { x.config = { ...x.config, [f.name]: e.target.value } })} /></label>
        ))}
      </div>
      <div className="flex flex-wrap gap-3"><span className="text-stone-600">{t('要送哪些:')}</span>
        {Object.entries(info.kinds).map(([k, label]) => <label key={k} className="flex items-center gap-1"><input type="checkbox" checked={c.kinds.includes(k)} onChange={e => toggle('kinds', k, e.target.checked)} />{label}</label>)}
      </div>
      <div className="flex flex-wrap gap-3"><span className="text-stone-600">{t('只看這幾台:')}</span>
        <SourcePick value={c.devices} devices={devices} onChange={v => onChange(x => { x.devices = v })} />
        <span className="text-xs text-stone-500">{c.devices.length ? '' : t('都沒勾 = 每一台')}</span>
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <label className="flex items-center gap-1"><input type="checkbox" checked={!!c.quiet} onChange={e => onChange(x => { x.quiet = e.target.checked ? { from: '23:00', to: '07:00' } : null })} />{t('勿擾時段')}</label>
        {c.quiet && <><input type="time" className={input} value={c.quiet.from} onChange={e => onChange(x => { x.quiet = { ...x.quiet!, from: e.target.value } })} />~
          <input type="time" className={input} value={c.quiet.to} onChange={e => onChange(x => { x.quiet = { ...x.quiet!, to: e.target.value } })} />
          <span className="text-xs text-stone-500">{t('這段時間只送緊急事件')}</span></>}
        <label className="flex items-center gap-1 ml-4"><input type="checkbox" checked={c.image} onChange={e => onChange(x => { x.image = e.target.checked })} />{t('緊急事件附上當下畫面')}</label>
      </div>
    </div>
  )
}

/** A bot channel: is it connected, who may give commands (paired), the invite link, a new pairing code. */
function BotPanel({ id, enabled }: { id: string; enabled: boolean }) {
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['notifyBots'], queryFn: api.notifyBots, refetchInterval: 5000 })
  const pair = useMutation({ mutationFn: () => api.notifyPair(id) })
  const unpair = useMutation({ mutationFn: (user: string) => api.notifyUnpair(id, user), onSuccess: () => qc.invalidateQueries({ queryKey: ['notifyBots'] }) })
  const b: BotInfo | undefined = q.data?.bots[id]
  const help = useQuery({ queryKey: ['notifyHelp'], queryFn: api.notifyHelp, staleTime: 60000 })
  if (!enabled) return <div className="text-xs text-stone-500">{t('啟用後才會連線、收指令')}</div>
  const st = b?.state
  return (
    <div className="border border-indigo-200 bg-indigo-50/40 rounded-md p-2 flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-3 text-xs">
        <span>{t('連線:')}{!st ? t('準備中…') : st.state === 'ok' ? <span className="text-emerald-700">{t('已連線,可以收指令')}</span>
          : st.state === 'error' ? <span className="text-rose-700">{t('連不上:{error}', { error: st.error })}</span> : t('連線中…')}</span>
        {b?.invite && <a className="underline text-indigo-700" href={b.invite} target="_blank" rel="noreferrer">{b.invite.includes('discord') ? t('邀請 Bot 到你的伺服器') : t('打開你的 Bot')}</a>}
        <span>{b?.paired ? t('通知會送到:{chat}', { chat: b.chat_name || t('已配對的對話') }) : <span className="text-amber-700">{t('還沒配對:通知還不會送出')}</span>}</span>
      </div>
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <Button onClick={() => pair.mutate()} disabled={pair.isPending}>{t('配對')}</Button>
        {pair.data && <span>{t('在要收通知的對話裡把')} <b className="text-base num tracking-widest">{pair.data.code}</b> {t('傳給 Bot({p1} 分鐘內有效);傳的人會加入「可以下指令的人」', { p1: Math.round(pair.data.seconds / 60) })}</span>}
      </div>
      <ErrorText error={pair.error || unpair.error} />
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <span className="text-stone-600">{t('可以下指令的人:')}</span>
        {(b?.allowed ?? []).length === 0 && <span className="text-stone-400">{t('(還沒有;其他人傳的訊息一律不理)')}</span>}
        {(b?.allowed ?? []).map(u => <span key={u.id} className="flex items-center gap-1 bg-white border border-stone-200 rounded px-1.5 py-0.5">
          {u.name || u.id}<button className="text-stone-400 hover:text-rose-600" title={t('移除')} onClick={() => unpair.mutate(u.id)}>✕</button></span>)}
      </div>
      <details className="text-[11px] text-stone-500">
        <summary className="cursor-pointer">{t('可以傳哪些指令(跟著「操作面板設計」;改面板就會改這裡)')}</summary>
        <pre className="whitespace-pre-wrap font-sans mt-1">{help.data?.text ?? '…'}</pre>
        <div>{t('傳「選單」會出現按鈕;改設定和按按鈕都會先問「確認」,停下來、暫停、繼續不用。')}</div>
      </details>
    </div>
  )
}

function CommandLog() {
  const q = useQuery({ queryKey: ['notifyBots'], queryFn: api.notifyBots, refetchInterval: 5000 })
  const log = q.data?.log ?? []
  return (
    <Card title={t('最近的聊天指令')}>
      {!log.length ? <Empty>{t('還沒有人下過指令')}</Empty> : (
        <div className="flex flex-col gap-0.5 text-xs max-h-60 overflow-auto">
          {log.map((r, i) => <div key={i} className="flex gap-2"><span className="text-stone-400 num w-24">{when(r.t)}</span>
            <span className="w-24 truncate">{r.user_name}</span><span className="w-40 truncate font-mono">{r.command}</span>
            <span className="text-stone-600 truncate">{r.result}</span></div>)}
        </div>)}
    </Card>
  )
}
