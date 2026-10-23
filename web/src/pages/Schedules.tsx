import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { PageIntro } from '../components/PageIntro'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api, type ArgValue, type Schedule, type ScheduleOverride, type ScheduleRunEntry } from '../api'
import { Button, Card, Empty, ErrorText, Modal, MoreButton, Page, Pill } from '../components/ui'
import { dateTime, duration } from '../lib/format'
import { usePersistentState } from '../lib/persist'
import { ArgsEditor, CondEnv } from './Scripts'
import { words } from '../lib/project'
import { dn, expandKeys, sourceIds } from '../lib/sources'
import { t } from '../i18n'
import { SourcePick } from '../components/SourcePick'

const input = 'border border-stone-300 rounded-md px-2 py-1 text-sm bg-white'
const DAYS = [t('一'), t('二'), t('三'), t('四'), t('五'), t('六'), t('日')]
const CODE_TONE: Record<string, string> = {
  running: 'bg-sky-600 text-white', success: 'bg-emerald-100 text-emerald-800', failed: 'bg-rose-100 text-rose-800',
  partial: 'bg-amber-100 text-amber-900',
  interrupted: 'bg-amber-100 text-amber-900', due: 'bg-amber-50 text-amber-900 border border-amber-300', later: 'bg-stone-100 text-stone-600',
  missed: 'bg-stone-200 text-stone-600', not_today: 'bg-stone-50 text-stone-400', off: 'bg-stone-50 text-stone-400',
}
const RESULT: Record<string, [string, string]> = {
  success: [t('完成'), 'bg-emerald-100 text-emerald-800'], failed: [t('失敗'), 'bg-rose-100 text-rose-800'],
  interrupted: [t('中斷'), 'bg-amber-100 text-amber-900'], partial: [t('部分完成'), 'bg-amber-100 text-amber-900'],
}
const newSchedule = (taken: string[], sub: string, devices: string[]): Schedule => {
  let i = 1
  while (taken.includes(`sched_${i}`)) i++
  return { id: `sched_${i}`, name: t('新排程'), enabled: true, at: '20:00', days: [], window: 120, devices, sub, args: {}, device_args: {}, pause_others: true, max_minutes: 240 }
}

/** Run a sub-script on some emulators at a time of day, once a day each. */
export default function Schedules() {
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['schedules'], queryFn: api.schedules, refetchInterval: 3000 })
  const info = useQuery({ queryKey: ['scripts'], queryFn: api.scripts })
  const shadow = useQuery({ queryKey: ['shadow'], queryFn: api.shadowStatus })
  const devices = sourceIds((shadow.data?.status.devices ?? []).map(d => d.name))
  const [draft, setDraft] = useState<Schedule[] | null>(null)
  const [day, setDay] = useState(false)
  const items = draft ?? q.data?.items ?? []
  const [sel, setSel] = usePersistentState('schedules.sel', '')
  const cur = items.find(s => s.id === sel) ?? items[0]
  const dirty = draft !== null && JSON.stringify(draft) !== JSON.stringify(q.data?.items ?? [])
  const save = useMutation({ mutationFn: () => api.schedulesSave(draft ?? []), onSuccess: () => { setDraft(null); qc.invalidateQueries({ queryKey: ['schedules'] }) } })
  const edit = (fn: (x: Schedule[]) => void) => { const n = JSON.parse(JSON.stringify(items)) as Schedule[]; fn(n); setDraft(n) }
  const subs = info.data?.subs ?? []
  const status = q.data?.status ?? {}
  const allNames = [...new Set(items.flatMap(x => x.devices))]

  return (
    <CondEnv.Provider value={{ info: info.data ?? null, devices }}>
    <Page title={t('排程')} intro={<PageIntro id="schedules" what={t('定時要做的事(例如每天餵食)放這裡,時間到就執行一個子腳本。')} start={t('按「+ 新增排程」,選時間、哪幾台和要執行的子腳本。')} ch={10} />} actions={<MoreButton onClick={() => setDay(true)}>{t('⚙ 每天 {p1} 重置', { p1: q.data?.day_start ?? '00:00' })}</MoreButton>} desc={t('時間到就在指定的{device}上執行一個子腳本(例如輪流處理清單裡的每一項)。每個排程每台每天只執行一次,可以重置;同時有好幾個到時間就依開始時間排隊。執行期間主腳本暫停,守門規則照常運作。', { device: words.device })}>
      <ErrorText error={q.error || save.error} />
      <Modal open={day} title={t('一天從幾點開始')} onClose={() => setDay(false)}>
        <p className="text-xs text-stone-600">{t('每個排程「今天跑過了」的紀錄在這個時間歸零(例如 App 的每日重置);排程的時間也以它為一天的開始。')}</p>
        <DayStart value={q.data?.day_start} items={q.data?.items ?? []} disabled={dirty} />
      </Modal>
      <div className="grid grid-cols-[280px_1fr] gap-4 items-start">
        <div className="flex flex-col gap-2 sticky top-3">
          {items.map(s => {
            const st = status[s.id] ?? {}
            return (
              <button key={s.id} onClick={() => setSel(s.id)}
                className={`text-left rounded-lg border bg-white px-3 py-2 ${cur?.id === s.id ? 'border-stone-900 ring-2 ring-stone-900/10' : 'border-stone-200 hover:border-stone-400'} ${s.enabled ? '' : 'opacity-60'}`}>
                <div className="flex items-center gap-2 text-sm font-medium">{s.name}{!s.enabled && <Pill>{t('停用')}</Pill>}
                  {q.data?.overrides?.[s.id] && <span className="text-[10px] px-1 rounded bg-violet-100 text-violet-800" title={t('使用者在操作面板上改過開關、時間或機台')}>{t('面板改過')}</span>}
                  <span className="ml-auto text-xs text-stone-500 num">{s.at}{s.days.length ? t(' 週{p1}', { p1: s.days.map(d => DAYS[d]).join('') }) : t(' 每天')}</span></div>
                <div className="text-xs text-stone-500 truncate">{subs.find(x => x.id === s.sub)?.name ?? s.sub}</div>
                <div className="flex flex-wrap gap-1 mt-1">
                  {expandKeys(s.devices).map(n => <span key={n} className={`text-[10px] px-1.5 rounded ${CODE_TONE[st[n]?.code] ?? 'bg-stone-50 text-stone-400'}`} title={`${n}:${st[n]?.text ?? ''}`}>{dn(n) !== n ? dn(n) : n.slice(commonPrefix(allNames).length) || n}</span>)}
                </div>
              </button>
            )
          })}
          <Button onClick={() => { const n = newSchedule(items.map(x => x.id), subs[0]?.id ?? '', devices.slice(0, 1)); edit(x => { x.push(n) }); setSel(n.id) }}>{t('+ 新增排程')}</Button>
          {!q.data?.running && <div className="text-xs text-amber-800 bg-amber-50 border border-amber-200 rounded-md px-3 py-2">{t('腳本執行沒有在跑:時間到也不會執行。到')} <Link className="underline" to="/script">{t('執行')}</Link> {t('開始。')}</div>}
        </div>

        {!cur ? <Card><Empty>{q.isLoading ? t('讀取中…') : t('還沒有排程。按「+ 新增排程」。')}</Empty></Card> : (
          <div className="flex flex-col gap-4 min-w-0">
            <div className="sticky top-0 z-20 pt-3 pb-2 bg-stone-50/95 backdrop-blur border-b border-stone-200 flex flex-wrap items-center gap-2">
              <span className="text-xs px-1.5 py-0.5 rounded bg-sky-700 text-white">{t('排程')}</span>
              <input className={`${input} font-medium w-56`} value={cur.name} onChange={e => edit(x => { x.find(y => y.id === cur.id)!.name = e.target.value })} />
              <label className="text-sm flex items-center gap-1"><input type="checkbox" checked={cur.enabled} onChange={e => edit(x => { x.find(y => y.id === cur.id)!.enabled = e.target.checked })} />{t('啟用')}</label>
              <span className="flex-1" />
              {dirty && <span className="text-xs text-amber-700">{t('● 有未儲存的修改')}</span>}
              {dirty && <Button variant="ghost" onClick={() => setDraft(null)}>{t('放棄修改')}</Button>}
              <Button variant="primary" disabled={!dirty || save.isPending} onClick={() => save.mutate()}>{save.isPending ? t('儲存中…') : t('儲存')}</Button>
              <Button variant="ghost" onClick={() => { if (confirm(t('刪除排程「{name}」?(按儲存才會生效)', { name: cur.name }))) edit(x => { x.splice(x.findIndex(y => y.id === cur.id), 1) }) }}>{t('刪除')}</Button>
            </div>
            {q.data?.overrides?.[cur.id] && <OverrideNotice id={cur.id} o={q.data.overrides[cur.id]} />}
            <Editor s={cur} devices={devices} onChange={fn => edit(x => fn(x.find(y => y.id === cur.id)!))} />
            <Today s={cur} status={status[cur.id] ?? {}} saved={!dirty && !!q.data?.items.some(x => x.id === cur.id)} running={!!q.data?.running} />
            <Runs schedule={cur.id} />
          </div>
        )}
      </div>
    </Page>
    </CondEnv.Provider>
  )
}

/** The users changed this schedule on the operation panel: what runs is that, not the design below. */
function OverrideNotice({ id, o }: { id: string; o: ScheduleOverride }) {
  const qc = useQueryClient()
  const clear = useMutation({ mutationFn: (field?: string) => api.scheduleOverrideClear(id, field), onSuccess: () => qc.invalidateQueries({ queryKey: ['schedules'] }) })
  const rows: [string, string][] = []
  if (o.enabled !== undefined) rows.push(['enabled', o.enabled ? t('開關:開') : t('開關:關')])
  if (o.at !== undefined) rows.push(['at', t('開始時間:{at}', { at: o.at })])
  if (o.devices !== undefined) rows.push(['devices', t('機台:{devices}', { devices: o.devices.join(t('、')) || t('(沒有)') })])
  return (
    <div className="rounded-lg border border-violet-200 bg-violet-50 px-3 py-2 text-sm flex flex-col gap-1">
      <div className="text-violet-900">{t('使用者在操作面板上改過這個排程;實際執行的是改過的值(存在執行端,下面的設計沒有變):')}</div>
      <div className="flex flex-wrap items-center gap-2">
        {rows.map(([f, tx]) => <span key={f} className="flex items-center gap-1 px-2 py-0.5 rounded bg-white border border-violet-200">{tx}
          <button className="text-xs text-violet-700 underline" disabled={clear.isPending} onClick={() => clear.mutate(f)}>{t('改回設計值')}</button></span>)}
        {rows.length > 1 && <button className="text-xs text-violet-700 underline" disabled={clear.isPending} onClick={() => clear.mutate(undefined)}>{t('全部改回設計值')}</button>}
      </div>
      <ErrorText error={clear.error} />
    </div>
  )
}

/** the start all names share (shown once, not on every chip), up to a separator */
function commonPrefix(names: string[]) {
  if (names.length < 2) return ''
  let p = names[0]
  for (const n of names) while (!n.startsWith(p)) p = p.slice(0, -1)
  const cut = Math.max(p.lastIndexOf('-'), p.lastIndexOf('_'), p.lastIndexOf(' '))
  return cut >= 0 ? p.slice(0, cut + 1) : ''
}

/** When a day begins: "ran today" resets then (e.g. an app's daily reset). */
function DayStart({ value, items, disabled }: { value?: string; items: Schedule[]; disabled: boolean }) {
  const qc = useQueryClient()
  const [v, setV] = useState<string | null>(null)
  const save = useMutation({ mutationFn: (ds: string) => api.schedulesSave(items, ds), onSuccess: () => { setV(null); qc.invalidateQueries({ queryKey: ['schedules'] }) } })
  const cur = v ?? value ?? '00:00'
  return (
    <div className="text-xs bg-white border border-stone-200 rounded-md px-3 py-2 flex flex-col gap-1" title={t('每個排程「今天跑過了」的紀錄在這個時間歸零;排程的時間也以這個時間為一天的開始(比它早的時間算在隔天凌晨)')}>
      <span className="flex items-center gap-1.5">{t('每天')}
        <input type="time" className={`${input} num`} value={cur} onChange={e => setV(e.target.value)} />{t('重置')}
        {v !== null && v !== value && <Button onClick={() => save.mutate(cur)} disabled={disabled || save.isPending}>{t('儲存')}</Button>}</span>
      {disabled && v !== null && <span className="text-amber-700">{t('先儲存排程的修改')}</span>}
      <ErrorText error={save.error} />
    </div>
  )
}

function Editor({ s, devices, onChange }: { s: Schedule; devices: string[]; onChange: (fn: (x: Schedule) => void) => void }) {
  const info = useQuery({ queryKey: ['scripts'], queryFn: api.scripts })
  const subs = info.data?.subs ?? []
  const sub = subs.find(x => x.id === s.sub)
  const allDevs = [...new Set([...devices, ...s.devices])].sort()
  const [perDev, setPerDev] = useState(Object.keys(s.device_args ?? {}).length > 0)
  const [adv, setAdv] = useState(false)
  const hasChars = (sub?.params ?? []).some(p => !!info.data?.lists.find(l => l.id === p.from_list)?.per_device)   // a per-device list's names differ per device
  return (
    <Card title={t('設定')}>
      <div className="flex flex-col gap-4 text-sm">
        <div className="flex flex-wrap items-center gap-3">
          <label className="flex items-center gap-2">{t('每天')}
            <input type="time" className={`${input} num`} value={s.at} onChange={e => onChange(x => { x.at = e.target.value })} />{t('開始')}</label>
          <span className="flex items-center gap-1">
            {DAYS.map((d, i) => (
              <button key={i} onClick={() => onChange(x => { x.days = x.days.includes(i) ? x.days.filter(y => y !== i) : [...x.days, i].sort() })}
                className={`w-7 h-7 rounded-full text-xs ${s.days.length === 0 || s.days.includes(i) ? 'bg-stone-900 text-white' : 'bg-stone-100 text-stone-500'}`}>{d}</button>
            ))}
            <span className="text-xs text-stone-500 ml-1">{s.days.length ? '' : t('(都沒選 = 每天)')}</span>
          </span>
        </div>
        <div className="flex flex-wrap items-center gap-2 text-xs text-stone-600">
          <span>{t('錯過的話')} {s.window ? t('{window} 分鐘內', { window: s.window }) : t('當天')}{t('補做 · 最長 {max_minutes} 分鐘 · 執行期間', { max_minutes: s.max_minutes })}{s.pause_others ? t('暫停') : t('不暫停')}{t('主腳本')}</span>
          <MoreButton onClick={() => setAdv(true)}>{t('進階')}</MoreButton>
        </div>
        <Modal open={adv} title={t('{name}:進階', { name: s.name })} onClose={() => setAdv(false)} footer={<Button variant="primary" onClick={() => setAdv(false)}>{t('好')}</Button>}>
        <div className="flex flex-col gap-3">
          <label className="flex items-center gap-1" title={t('時間到時腳本執行沒在跑、這台停下來或暫停中、或在排隊,這段時間內還是會開始;超過就算錯過')}>
            {t('錯過的話')}
            <input type="number" min={0} max={1440} className={`${input} w-20 num`} value={s.window} onChange={e => onChange(x => { x.window = Number(e.target.value) })} />
            {t('分鐘內補做')}<span className="text-xs text-stone-500">{t('(0 = 當天都可以)')}</span></label>
          <label className="flex items-center gap-1">{t('最長執行')}
            <input type="number" min={1} max={1440} className={`${input} w-20 num`} value={s.max_minutes} onChange={e => onChange(x => { x.max_minutes = Number(e.target.value) })} />{t('分鐘,超過就中斷')}</label>
          <label className="flex items-center gap-1.5"><input type="checkbox" checked={s.pause_others} onChange={e => onChange(x => { x.pause_others = e.target.checked })} />
            {t('執行期間暫停主腳本(守門規則照常)')}</label>
          <span className="text-xs text-stone-500">{t('改完按上方「儲存」才會生效')}</span>
        </div>
        </Modal>
        <div className="flex flex-col gap-1">
          <span className="text-stone-600">{t('在哪些{device}', { device: words.device })}</span>
          <div className="flex flex-wrap gap-3">
            <SourcePick value={s.devices} devices={allDevs.filter(n => !n.startsWith('#'))} sort onChange={v => onChange(x => { x.devices = v })} />
          </div>
        </div>
        <div className="flex flex-col gap-2 border-t border-stone-100 pt-3">
          <label className="flex items-center gap-2"><span className="text-stone-600">{t('執行子腳本')}</span>
            <select className={input} value={s.sub} onChange={e => onChange(x => { x.sub = e.target.value; x.args = {}; x.device_args = {} })}>
              {subs.map(x => <option key={x.id} value={x.id}>{x.name}</option>)}
            </select>
            {sub && <Link className="text-xs underline" to="/scripts">{t('到「腳本」編輯')}</Link>}</label>
          {sub && info.data && (sub.params ?? []).length > 0 && <>
            {s.devices.length === 0 && hasChars && <div className="text-xs text-amber-700">{t('先勾選上面「在哪些{device}」,才能設定各台的項目', { device: words.device })}</div>}
            <div className="text-xs font-medium text-stone-600">{t('所有{device}共用', { device: words.device })}</div>
            <ArgsEditor sub={sub} args={s.args} info={info.data} callerParams={[]} shared onChange={a => onChange(x => { x.args = a })} />
            {hasChars
              ? <div className="text-xs text-stone-600 mt-1">{t('每台{device}的項目:', { device: words.device })}</div>
              : <label className="flex items-center gap-1.5 text-xs text-stone-600"><input type="checkbox" checked={perDev}
                  onChange={e => { setPerDev(e.target.checked); if (!e.target.checked) onChange(x => { x.device_args = {} }) }} />{t('每台{device}用不同的參數', { device: words.device })}</label>}
            {(perDev || hasChars) && expandKeys(s.devices).map(n => (
              <div key={n} className="flex flex-col gap-1 pl-3">
                <span className="text-xs font-medium">{dn(n)}<span className="text-stone-400 font-normal">{t('(沒填的用上面的)')}</span></span>
                <ArgsEditor sub={sub} args={{ ...s.args, ...(s.device_args?.[n] ?? {}) }} info={info.data!} callerParams={[]} device={n}
                  onChange={a => onChange(x => {
                    const diff: Record<string, ArgValue> = {}
                    for (const [k, v] of Object.entries(a)) if (JSON.stringify(v) !== JSON.stringify(x.args[k])) diff[k] = v
                    x.device_args = { ...(x.device_args ?? {}), [n]: diff }
                  })} />
              </div>
            ))}
          </>}
          {sub && <pre className="text-xs text-stone-600 whitespace-pre-wrap bg-stone-50 rounded-md px-3 py-2">{(sub.outline ?? []).join('\n')}</pre>}
        </div>
      </div>
    </Card>
  )
}

function Today({ s, status, saved, running }: { s: Schedule; status: Record<string, { code: string; text: string; online?: boolean; run?: string | null }>; saved: boolean; running: boolean }) {
  const qc = useQueryClient()
  const req = useMutation({ mutationFn: (b: { action: 'run_now' | 'reset'; id: string; device?: string }) => api.scheduleRequest(b),
    onSuccess: () => setTimeout(() => qc.invalidateQueries({ queryKey: ['schedules'] }), 1500) })
  return (
    <Card title={t('今天')} extra={!saved && <span className="text-xs text-amber-700">{t('先儲存才能執行')}</span>}>
      <div className="flex flex-col gap-2 text-sm">
        <ErrorText error={req.error} />
        {expandKeys(s.devices).map(n => {
          const st = status[n]
          return (
            <div key={n} className="flex flex-wrap items-center gap-2">
              <span className="w-36">{dn(n)}</span>
              <span className={`text-xs px-2 py-0.5 rounded ${CODE_TONE[st?.code ?? ''] ?? 'bg-stone-50 text-stone-400'}`}>{st?.text ?? '—'}</span>
              <span className="flex-1" />
              <Button disabled={!saved || !running || st?.code === 'running' || req.isPending}
                onClick={() => { if (confirm(t('現在就在 {n} 執行「{name}」?(會真的點擊;這台停下來或暫停中的話要先按「繼續」)', { n, name: s.name }))) req.mutate({ action: 'run_now', id: s.id, device: n }) }}>{t('立即執行')}</Button>
              <Button variant="ghost" disabled={!saved || !['success', 'partial', 'failed', 'interrupted'].includes(st?.code ?? '') || req.isPending}
                onClick={() => req.mutate({ action: 'reset', id: s.id, device: n })} title={t('忘記今天已經執行過;還在時間內的話會再執行一次')}>{t('重置今天')}</Button>
            </div>
          )
        })}
      </div>
    </Card>
  )
}

function Runs({ schedule }: { schedule: string }) {
  const q = useQuery({ queryKey: ['scheduleRuns'], queryFn: () => api.scheduleRuns(), refetchInterval: 5000 })
  const items = (q.data?.items ?? []).filter(x => x.schedule === schedule)
  const [open, setOpen] = useState<string | null>(null)
  return (
    <Card title={t('執行紀錄({length})', { length: items.length })}>
      {!items.length ? <Empty>{t('還沒有執行過')}</Empty> : (
        <div className="flex flex-col gap-1 text-sm">
          {items.map(r => {
            const [tx, tone] = r.result ? RESULT[r.result] ?? [r.result, ''] : [t('執行中'), 'bg-sky-600 text-white']
            return (
              <div key={r.id} className="border-b border-stone-100">
                <button onClick={() => setOpen(o => o === r.id ? null : r.id)} className="w-full text-left py-1.5 flex flex-wrap items-center gap-2 hover:bg-stone-50">
                  <span className={`text-xs px-1.5 rounded ${tone}`}>{tx}</span>
                  <span className="num text-stone-600">{dateTime(r.start)}</span><span>{dn(r.device)}</span>
                  <span className="text-xs text-stone-500">{t('{p1} · {steps} 步', { p1: r.end ? duration(r.end - r.start) : '', steps: r.steps })}</span>
                  {r.message && <span className="text-xs text-rose-700 truncate">{r.message}</span>}
                </button>
                {open === r.id && <RunView id={r.id} />}
              </div>
            )
          })}
        </div>
      )}
    </Card>
  )
}

function RunView({ id }: { id: string }) {
  const q = useQuery({ queryKey: ['scheduleRun', id], queryFn: () => api.scheduleRun(id), refetchInterval: d => (d.state.data?.end ? false : 3000) })
  const [frame, setFrame] = useState<string | null>(null)
  const d = q.data
  if (!d) return <div className="text-xs text-stone-400 py-2">{t('讀取中…')}</div>
  const shown = frame ?? [...d.entries].reverse().find(e => e.frame)?.frame ?? null
  const tone = (e: ScheduleRunEntry) => e.kind === 'warn' ? 'text-rose-700' : e.kind === 'notify' ? 'text-sky-800' : e.kind === 'end' || e.kind === 'start' ? 'font-medium' : 'text-stone-700'
  return (
    <div className="grid lg:grid-cols-[1fr_360px] gap-3 py-2">
      <div className="flex flex-col text-xs max-h-96 overflow-auto">
        {d.entries.filter(e => e.kind !== 'frame').map((e, i) => (
          <div key={i} className={`flex gap-2 py-0.5 ${tone(e)} ${e.frame ? 'cursor-pointer hover:bg-stone-50' : ''}`} onClick={() => e.frame && setFrame(e.frame)}>
            <span className="num text-stone-400 w-16 text-right shrink-0">+{duration(e.t - d.start)}</span><span>{e.text}</span>{e.frame && <span>📷</span>}
          </div>
        ))}
      </div>
      <div className="flex flex-col gap-1">
        {shown && <img src={api.scheduleRunFrameUrl(d.id, shown)} alt="" className="w-full rounded border border-stone-200" />}
        <div className="flex gap-1 overflow-x-auto">
          {d.entries.filter(e => e.frame).map(e => (
            <button key={e.frame} onClick={() => setFrame(e.frame!)} className={`shrink-0 border-2 rounded ${shown === e.frame ? 'border-stone-900' : 'border-transparent'}`}>
              <img src={api.scheduleRunFrameUrl(d.id, e.frame!)} alt="" className="h-10" loading="lazy" />
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}
