import { locale, t } from '../i18n'
import { PageIntro } from '../components/PageIntro'
import { MachineLanguage } from '../components/LangPicker'
import { AskBar } from '../components/AskBar'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api, type Hold, imageUrl, shadowLiveUrl, type TimelineRow, type AnswerValue, type ShadowDevice, type ShadowFlag, type JudgeInfo, type ShadowState, type ShadowStatus, type StateDef, type Script, type JobInfo, type ShadowControl, type Incident } from '../api'
import { edition, projectInfo, screen, words } from '../lib/project'
import { NotifySettings } from './Notify'
import { Button, Card, Drawer, Modal, MoreButton, Empty, ErrorText, LogView, Page, Pill } from '../components/ui'
import DeviceActions from './DeviceActions'
import { clock, dateTime, duration } from '../lib/format'
import { usePersistentState } from '../lib/persist'
import { COLORS, reviewStates, useSchema } from '../lib/schema'
import { dn, handOf, keyLabel, sourceIds, tagIds, tagList } from '../lib/sources'

const ACTION_STYLE: Record<string, string> = {
  tap: 'bg-amber-100 text-amber-900 border-amber-300', long_press: 'bg-amber-100 text-amber-900 border-amber-300',
  back: 'bg-amber-100 text-amber-900 border-amber-300', call: 'bg-amber-100 text-amber-900 border-amber-300',
  goto: 'bg-sky-50 text-sky-900 border-sky-200', hold: 'bg-violet-50 text-violet-900 border-violet-200',
  notify: 'bg-rose-50 text-rose-800 border-rose-200', none: 'bg-emerald-50 text-emerald-800 border-emerald-200',
  wait: 'bg-stone-100 text-stone-700 border-stone-200', uncertain: 'bg-stone-100 text-stone-700 border-stone-200',
  no_window: 'bg-stone-100 text-stone-500 border-stone-200',
}

/** "模型 97%" or "參考圖 0.98" / "顏色 32%": where a live answer came from and how sure it is */
function sourceTag(s: ShadowState) {
  const c = Math.round((s.conf ?? 1) * 100)
  if (s.source === 'not_here') return { tag: t('不用在這台'), num: '', tip: t('這個狀態只用在別的來源(狀態頁「只用在這些來源」),這台不看') }
  if (s.source === 'rule') {
    // the whole state goes by the rule (the model has not learned / passed it), or the rule won at this moment
    const why = s.why || t('這個狀態目前由畫面規則判斷(模型還沒學過或還沒通過考試;看「執行設定 › 每個狀態怎麼判斷」)')
    if (s.score == null) return { tag: t('規則'), num: '', tip: why }
    return s.rule === 'color_ratio'
      ? { tag: t('顏色'), num: `${Math.round(s.score * 100)}%`, tip: t('{why}。符合的顏色占 {p2}%', { why, p2: Math.round(s.score * 100) }) }
      : { tag: t('參考圖'), num: s.score.toFixed(2), tip: t('{why}。最像的參考圖相似度 {p2}(1 = 完全一樣)', { why, p2: s.score.toFixed(2) }) }
  }
  if (s.source === 'model+rule') {
    const own = s.model_conf != null ? Math.round(s.model_conf * 100) : null
    return { tag: own != null ? t('模型 {own}% +規則', { own }) : t('模型+規則'), num: `→ ${c}%`,
      tip: t('模型自己的信心 {p1}%,不到 95%,所以讓畫面規則也看一眼;規則說法一樣,合起來的信心 {c}%(腳本用的是這個)。設為「只用模型」就不會有這一步。', { p1: own ?? '?', c }) }
  }
  return { tag: t('模型'), num: `${c}%`, tip: t('模型判斷,信心 {c}%', { c }) }
}
const MODE_TAG: Record<string, [string, string]> = { shadow: [t('試跑'), 'bg-violet-100 text-violet-700'], live: [t('正式'), 'bg-rose-100 text-rose-700'] }

type RunTab = 'watch' | 'incidents' | 'deploy' | 'log' | 'notify' | 'settings'
const RUN_TABS: [RunTab, string][] = [['watch', t('監看')], ['incidents', t('緊急事件')], ['deploy', t('部署')], ['log', t('紀錄')]]

export default function Shadow() {
  const qc = useQueryClient()
  const sch = useSchema()
  const states = sch.data?.schema.states ?? []
  const q = useQuery({ queryKey: ['shadow'], queryFn: api.shadowStatus, refetchInterval: 1000 })
  const [run, setRun] = usePersistentState('shadow.run', '')
  // remembered per pack; until set here, what the pack recommends (project.json "run")
  const [interval, setIntervalS] = usePersistentState(`shadow.interval.${projectInfo.id}`, projectInfo.interval ?? 1)
  const [tabSaved, setTab] = usePersistentState<RunTab>('run.tab', 'watch')
  const tab: RunTab = RUN_TABS.some(([k]) => k === tabSaved) ? tabSaved : 'watch'
  const [drawer, setDrawer] = useState<'notify' | 'settings' | null>(null)
  const st = q.data?.status ?? {}
  const running = !!st.running || q.data?.job?.status === 'running'
  const start = useMutation({ mutationFn: () => api.shadowStart({ run, interval }), onSuccess: () => qc.invalidateQueries({ queryKey: ['shadow'] }) })
  const stop = useMutation({ mutationFn: api.shadowStop })
  const nBlocked = (st.blocked ?? []).length
  const open = running ? st.incidents_open ?? [] : []
  const nOpen = open.length
  const nWarn = (st.alerts ?? []).filter(a => a.level === 'warn' && Date.now() / 1000 - a.t < 3600).length
  const asks = useQuery({ queryKey: ['asks'], queryFn: api.asks, refetchInterval: 2000, enabled: running })

  return (
    <Page title={t('執行')} intro={<PageIntro id="script" what={t('腳本在這裡實際跑起來;先試跑看它會做什麼,沒問題再正式執行。')} start={t('按「部署」選哪台跑哪個腳本,按「開始」;點「詳細」看每一步怎麼判斷。')} ch={9} />} desc={t('模型即時看著每台{device},依腳本的規則決定要做什麼。「部署」決定哪台跑哪個腳本;要它先別動,按「停下來」或「暫停」。', { device: words.device })}
      actions={<>
        <MoreButton onClick={() => setDrawer('notify')}>{t('🔔 通知與 Bot')}</MoreButton>
        <MoreButton onClick={() => setDrawer('settings')}>{t('⚙ 執行設定')}</MoreButton>
      </>}>
      <ControlBar st={st} running={running} job={q.data?.job ?? null} error={q.error || start.error || stop.error}
        onStart={() => start.mutate()} starting={start.isPending} />
      {running && <AskBar items={asks.data?.items ?? []} refresh={['asks']} />}
      {open.length > 0 && tab !== 'incidents' && (
        <button onClick={() => setTab('incidents')} className="text-left rounded-md border border-rose-300 bg-rose-50 px-3 py-2 text-sm text-rose-900">
          {t('🚨 緊急事件進行中:')}{open.map(x => x.resolved ? t('{device}「{rules}」(已不成立,觀察後續中)', { device: dn(x.device), rules: x.triggers.join(t('、')) })
            : t('{device}「{rules}」', { device: dn(x.device), rules: x.triggers.join(t('、')) })).join(t(';'))} {t('— 點這裡看經過')}
        </button>
      )}
      <div className="flex border-b border-stone-200 gap-1">
        {RUN_TABS.map(([k, tx]) => (
          <button key={k} onClick={() => setTab(k)}
            className={`px-4 py-2 text-sm -mb-px border-b-2 ${tab === k ? 'border-stone-900 text-stone-900 font-medium' : 'border-transparent text-stone-500 hover:text-stone-800'}`}>
            {tx}
            {k === 'incidents' && nOpen > 0 && <span className="ml-1.5 text-[11px] px-1.5 rounded-full bg-rose-600 text-white num animate-pulse">{nOpen}</span>}
            {k === 'log' && nBlocked + nWarn > 0 && <span className="ml-1.5 text-[11px] px-1.5 rounded-full bg-rose-600 text-white num">{nBlocked + nWarn}</span>}
          </button>
        ))}
      </div>
      {tab === 'watch' && <Watch st={st} states={states} running={running} />}
      {tab === 'incidents' && <Incidents states={states} />}
      {tab === 'deploy' && <Deploy devices={sourceIds((st.devices ?? []).map(d => d.name))} />}

      {tab === 'log' && <Logs st={st} states={states} running={running} />}
      <Drawer open={drawer === 'notify'} title={t('通知與 Bot')} onClose={() => setDrawer(null)}>
        <NotifySettings devices={sourceIds((st.devices ?? []).map(d => d.name))} />
      </Drawer>
      <Drawer open={drawer === 'settings'} title={t('執行設定')} onClose={() => setDrawer(null)}>
        <Settings st={st} states={states} running={running} run={run} setRun={setRun} interval={interval} setInterval={setIntervalS}
          onStart={() => start.mutate()} onStop={() => stop.mutate()} busy={start.isPending || stop.isPending} />
        <MachineLanguage />
      </Drawer>
    </Page>
  )
}

/** Always on top: start / stop the runner; 停下來 / 暫停 / 繼續 for every source. */
function ControlBar({ st, running, job, error, onStart, starting }: {
  st: ShadowStatus; running: boolean; job: JobInfo | null; error: unknown
  onStart: () => void; starting: boolean
}) {
  const qc = useQueryClient()
  const set = useMutation({ mutationFn: (kind: 'stop' | 'pause' | 'resume') => api.shadowAct({ device: '*', kind }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['shadow'] }) })
  const last = (st.alerts ?? [])[0]
  const all = st.hold_all
  const held = (st.devices ?? []).filter(d => d.hold).length
  const waiting = (st.devices ?? []).filter(d => !d.hold && (d.start_wait ?? 0) > 0).length
  // 繼續 while what stopped a device is still on its screen: it stops again right away
  const resumeAll = () => {
    const still = (st.devices ?? []).filter(d => d.hold && d.cause_now)
    if (still.length && !confirm(t('{p1}\n\n上面這些的原因還在,繼續後會馬上再停下來。還是要全部繼續嗎?', { p1: still.map(d => `${dn(d.name)}:${d.hold!.why ?? d.hold!.by}`).join('\n') }))) return
    set.mutate('resume')
  }
  return (
    <div className="sticky top-0 z-20 -mx-6 px-6 py-3 bg-stone-50/95 backdrop-blur border-b border-stone-200 flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-3 text-sm">
        {!running && <Button variant="primary" onClick={onStart} disabled={starting} title={t('啟動執行程式:開始看畫面、判斷;停下來 / 暫停的維持原樣')}>{t('▶ 啟動執行程式')}</Button>}
        <span className="text-xs text-stone-500 num">
          {running ? <Pill tone="green">{t('執行程式運作中')}</Pill> : <Pill>{t('執行程式沒有啟動:不看、不判斷、不通知')}</Pill>}
          {running && st.started && <span className="ml-2">{t('{p1} · 每 {p2} 毫秒看一次(處理 {p3} 毫秒)', { p1: duration((st.updated ?? 0) - st.started), p2: Math.round((st.interval ?? 1) * 1000), p3: st.tick_ms ?? '—' })}</span>}
        </span>
        {running && held > 0 && !all && <Button variant="primary" disabled={set.isPending} onClick={() => resumeAll()} title={t('停下來或暫停的全部繼續')}>{t('▶ 全部繼續')}</Button>}
        {running && (all
          ? <span className="flex items-center gap-2 px-3 py-1.5 rounded-md border-2 border-amber-400 bg-amber-50 text-amber-900">
              <b>{all.mode === 'pause' ? t('⏸ 全部暫停中') : t('🛑 全部停下來中')}</b><span className="text-xs">{t('({by}):只看不點,守門規則和排程也不動', { by: all.by })}</span>
              <Button variant="primary" disabled={set.isPending} onClick={() => resumeAll()}>{t('▶ 全部繼續')}</Button></span>
          : <span className="flex items-center gap-2">
              <Pill tone="green">{t('運作中')}{held ? t('({held} 台停下來或暫停)', { held }) : ''}{waiting ? t('({waiting} 台啟動確認中)', { waiting }) : ''}</Pill>
              <Button disabled={set.isPending} onClick={() => set.mutate('pause')} title={t('腳本、情境和正在做的事都停在原地,按「繼續」從同一步接著做')}>{t('⏸ 全部暫停')}</Button>
              <Button variant="danger" disabled={set.isPending} onClick={() => { if (confirm(t('全部停下來?正在做的事會取消(先做收尾),腳本和情境都停住(守門規則和排程也不動),按「全部繼續」後從頭開始;直到按「全部繼續」。'))) set.mutate('stop') }}>{t('🛑 全部停下來')}</Button>
            </span>)}
        <span className="flex-1" />
      </div>
      {last && <div className={`text-xs truncate ${last.level === 'warn' ? 'text-rose-700' : 'text-stone-600'}`} title={last.text}>
        <span className="num text-stone-400 mr-2">{clock(last.t)}</span>{last.device && <span className="mr-1">{dn(last.device)}</span>}{last.text}</div>}
      <ErrorText error={error || set.error} />
      {job && job.status !== 'running' && job.status !== 'stopped' && job.status !== 'done' && <LogView lines={job.log ?? []} height="h-24" />}
    </div>
  )
}

/** The devices side by side; the chosen one in detail on the right. */
function Watch({ st, states, running }: { st: ShadowStatus; states: StateDef[]; running: boolean }) {
  const devs = st.devices ?? []
  const [pick, setPick] = usePersistentState('run.device', '')
  const cur = devs.find(d => d.name === pick) ?? devs[0]
  const view = st.control?.live_view ?? true
  if (!devs.length) return <Card><Empty>{running ? t('啟動中(載入模型約 10 秒)…') : t('按上面的「啟動執行程式」')}</Empty></Card>
  return (
    <div className="grid xl:grid-cols-[1fr_460px] gap-4 items-start">
      <div className="grid sm:grid-cols-2 gap-3">
        {devs.map(d => {
          const stops = (st.blocked ?? []).filter(b => b.device === d.name)
          const main = d.hold?.why ? t('已停下來:{why}', { why: d.hold.why }) : d.proc ? `▶ ${d.proc.chain.map(c => c.sub).join(' › ')}:${d.proc.now || '…'}`
            : (d.decisions.find(x => x.done) ?? d.decisions.find(x => !x.guard) ?? d.decisions[0])?.text ?? t('沒有腳本')
          return (
            <button key={d.name} onClick={() => setPick(d.name)}
              className={`text-left rounded-lg border bg-white overflow-hidden ${cur?.name === d.name ? 'border-stone-900 ring-2 ring-stone-900/10' : 'border-stone-200 hover:border-stone-400'}`}>
              <DeviceFrame d={d} v={st.updated ?? 0} view={view} />
              <div className="px-3 py-2 flex flex-col gap-0.5">
                <div className="flex items-center gap-2 text-sm font-medium" title={d.name}>{dn(d.name)}
                  {d.health && d.health.state !== 'ok' && <span className={`text-[11px] px-1.5 rounded ${d.health.state === 'slow' ? 'bg-amber-100 text-amber-900' : 'bg-rose-600 text-white'}`}>{d.health.text}</span>}
                  {stops.length > 0 && <span className="text-[11px] px-1.5 rounded bg-amber-100 text-amber-800">{t('⏸ {length} 條規則暫停', { length: stops.length })}</span>}
                  {d.hold && <span className={`text-[11px] px-1.5 rounded text-white ${d.hold.cause ? 'bg-rose-600' : 'bg-amber-500'}`}>{d.hold.mode === 'pause' ? t('⏸ 暫停中') : t('🛑 已停下來')}</span>}
                  {!d.hold && (d.start_wait ?? 0) > 0 && <span className="text-[11px] px-1.5 rounded bg-sky-100 text-sky-800">{t('啟動確認中')}{(d.start_wait ?? 0) < 1e6 ? t(' {p1} 秒', { p1: Math.ceil(d.start_wait ?? 0) }) : ''}</span>}
                  {d.manual?.paused && <span className="text-[11px] px-1.5 rounded bg-amber-100 text-amber-800">{t('✋ 手動中')}</span>}
                  {d.held && <span className="text-[11px] px-1.5 rounded bg-violet-100 text-violet-800">{t('🛡 暫停其他')}</span>}
                  {d.decisions.some(x => x.mode === 'live') && <span className="text-[11px] px-1.5 rounded bg-rose-100 text-rose-700">{t('正式')}</span>}
                </div>
                <div className={`text-xs truncate ${d.hold?.why ? 'text-rose-700 font-semibold' : d.proc ? 'text-rose-800' : 'text-stone-600'}`}>{main}</div>
                {Object.entries(d.situations ?? {}).filter(([, x]) => x.count > 1).map(([sid, x]) =>
                  <div key={sid} className="text-[11px] text-stone-500 truncate">{(d.decisions.find(dd => dd.script === sid)?.script_name) ?? sid}:{x.name}</div>)}
              </div>
            </button>
          )
        })}
      </div>
      {cur && <div className="xl:sticky xl:top-28"><DeviceCard d={cur} states={states} v={st.updated ?? 0} live={running} hold={cur.hold}
        stops={(st.blocked ?? []).filter(b => b.device === cur.name)} /></div>}
    </div>
  )
}

/** Which device runs which script, in one table (the scripts' "devices" setting). */
function Deploy({ devices }: { devices: string[] }) {
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['scripts'], queryFn: api.scripts })
  const [draft, setDraft] = useState<Record<string, Record<string, string>>>({})
  const scripts = q.data?.scripts ?? []
  const modes = q.data?.modes ?? {}
  const keys = scripts.flatMap(s => Object.keys(s.devices).filter(k => k !== '*'))
  const tagCols = [...new Set([...tagList().map(tx => `#${tx}`), ...keys.filter(k => k.startsWith('#'))])].sort()
  const cols = [...new Set([...devices, ...keys.filter(k => !k.startsWith('#'))])].sort()
  const order: Record<string, number> = { off: 0, shadow: 1, live: 2 }
  /** where a source's mode comes from: itself, else its tags (the most careful), else the default */
  const decide = (s: Script, dev: string): [string, string] => {
    const d = devs(s)
    if (d[dev]) return [d[dev], '']
    const hits = tagCols.filter(tx => d[tx] && tagIds(tx).includes(dev)).map(tx => [d[tx], tx] as [string, string])
    if (hits.length) return hits.reduce((a, b) => (order[b[0]] < order[a[0]] ? b : a))
    return [d['*'] ?? 'shadow', '']
  }
  const devs = (s: Script) => draft[s.id] ?? s.devices
  const changed = scripts.filter(s => draft[s.id] && JSON.stringify(draft[s.id]) !== JSON.stringify(s.devices))
  const setCell = (s: Script, key: string, v: string) => setDraft(d => {
    const n = { ...(d[s.id] ?? s.devices) }
    if (v === '') delete n[key]; else n[key] = v
    return { ...d, [s.id]: n }
  })
  const save = useMutation({
    mutationFn: async () => {
      for (const s of changed) {
        const { version: _v, created: _c, note: _n, outline: _o, ...rest } = s as Script & { outline?: string[] }
        await api.scriptSave({ ...rest, devices: draft[s.id] } as Script, t('部署:') + Object.entries(draft[s.id]).map(([k, m]) => `${k === '*' ? t('預設') : k.startsWith('#') ? k : dn(k)} ${modes[m] ?? m}`).join(t('、')))
      }
    },
    onSuccess: () => { setDraft({}); qc.invalidateQueries({ queryKey: ['scripts'] }) },
  })
  const eff = (s: Script, dev: string) => decide(s, dev)[0]
  const tone = (m: string) => m === 'live' ? 'bg-rose-50 text-rose-800' : m === 'off' ? 'bg-stone-50 text-stone-400' : 'bg-violet-50 text-violet-800'
  const addsLive = changed.some(s => cols.some(c => eff(s, c) === 'live' && (s.devices[c] ?? s.devices['*']) !== 'live'))
  return (
    <Card title={t('哪台{device}跑哪個腳本', { device: words.device })} extra={<span className="flex items-center gap-2">
      {changed.length > 0 && <Button variant="ghost" onClick={() => setDraft({})}>{t('還原')}</Button>}
      <Button variant="primary" disabled={!changed.length || save.isPending} onClick={() => {
        if (addsLive && !confirm(t('有{device}改成「正式執行」:會真的點擊(停下來或暫停中的除外)。確定儲存?', { device: words.device }))) return
        save.mutate()
      }}>{save.isPending ? t('儲存中…') : changed.length ? t('儲存({length} 個腳本)', { length: changed.length }) : t('儲存')}</Button></span>}>
      <ErrorText error={q.error || save.error} />
      {!scripts.length ? <Empty>{q.isLoading ? t('讀取中…') : t('還沒有腳本')}</Empty> : (
        <div className="overflow-x-auto">
          <table className="text-sm w-full">
            <thead><tr className="text-xs text-stone-500 text-left">
              <th className="py-2 pr-3 font-normal">{t('腳本(越上面越優先)')}</th>
              <th className="py-2 pr-3 font-normal">{t('預設(所有{device})', { device: words.device })}</th>
              {tagCols.map(tx => <th key={tx} className="py-2 pr-3 font-normal text-sky-800" title={t('有這個標籤的:{p1}(之後貼上的也算)', { p1: tagIds(tx).map(dn).join(t('、')) })}>{keyLabel(tx)}</th>)}
              {cols.map(c => <th key={c} className="py-2 pr-3 font-normal" title={c}>{dn(c)}
                {handOf(c) && <div className="text-[10px] text-sky-700" title={t('在「來源」頁設定')}>{t('動作:{p1}', { p1: handOf(c) })}</div>}</th>)}
            </tr></thead>
            <tbody>
              {scripts.map(s => (
                <tr key={s.id} className={`border-t border-stone-100 ${s.enabled ? '' : 'opacity-50'}`}>
                  <td className="py-2 pr-3">
                    <Link className="font-medium hover:underline" to={`/scripts?script=${encodeURIComponent(s.id)}`}>{s.id === 'guards' ? '🛡 ' : ''}{s.name}</Link>
                    {!s.enabled && <span className="ml-1"><Pill>{t('停用')}</Pill></span>}
                    {draft[s.id] && JSON.stringify(draft[s.id]) !== JSON.stringify(s.devices) && <span className="ml-1 text-xs text-amber-700">{t('已修改')}</span>}
                  </td>
                  <td className="py-2 pr-3">
                    <select className={`border border-stone-300 rounded px-2 py-1 ${tone(devs(s)['*'] ?? 'shadow')}`} value={devs(s)['*'] ?? 'shadow'} onChange={e => setCell(s, '*', e.target.value)}>
                      {Object.entries(modes).map(([k, tx]) => <option key={k} value={k}>{tx}</option>)}
                    </select>
                  </td>
                  {tagCols.map(tx => (
                    <td key={tx} className="py-2 pr-3">
                      <select className={`border border-sky-300 rounded px-2 py-1 ${devs(s)[tx] ? tone(devs(s)[tx]) : ''}`} value={devs(s)[tx] ?? ''} onChange={e => setCell(s, tx, e.target.value)}>
                        <option value="">{t('(不用標籤決定)')}</option>
                        {Object.entries(modes).map(([k, tt]) => <option key={k} value={k}>{tt}</option>)}
                      </select>
                    </td>
                  ))}
                  {cols.map(c => (
                    <td key={c} className="py-2 pr-3">
                      <select className={`border border-stone-300 rounded px-2 py-1 ${tone(eff(s, c))}`} value={devs(s)[c] ?? ''} onChange={e => setCell(s, c, e.target.value)}>
                        <option value="">{decide(s, c)[1] ? t('跟 {p1}', { p1: decide(s, c)[1] }) : t('跟預設')}{t('({n})', { n: (modes[eff(s, c)] ?? '').replace(/\(.*\)/, '').trim() })}</option>
                        {Object.entries(modes).map(([k, tx]) => <option key={k} value={k}>{tx}</option>)}
                      </select>
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
          <p className="text-xs text-stone-500 mt-3">{t('試跑:只記錄會做什麼。正式執行:真的點擊(停下來或暫停中的不會;啟動後每台畫面正常幾秒才開始)。關閉:這台不跑這個腳本。腳本本身的停用 / 啟用在「腳本」裡設定。')}</p>
        </div>
      )}
    </Card>
  )
}

/** What happened: notifications, paused rules, decisions, flagged frames, variables. */
function Logs({ st, states, running }: { st: ShadowStatus; states: StateDef[]; running: boolean }) {
  const qc = useQueryClient()
  const set = useMutation({ mutationFn: api.shadowControl, onSuccess: () => qc.invalidateQueries({ queryKey: ['shadow'] }) })
  const scripts = useQuery({ queryKey: ['scripts'], queryFn: api.scripts })
  const ruleName = (sid: string, rid: string) => {
    const s = scripts.data?.scripts.find(x => x.id === sid)
    return { script: s?.name ?? sid, rule: s?.situations.flatMap(x => x.rules).find(r => r.id === rid)?.name ?? rid }
  }
  const alerts = st.alerts ?? []
  return (
    <div className="grid xl:grid-cols-2 gap-4 items-start">
      <div className="flex flex-col gap-4">
        {(st.blocked ?? []).length > 0 && (
          <Card title={t('已暫停的規則({length})', { length: st.blocked!.length })} extra={<Button onClick={() => set.mutate({ unblock: true })}>{t('全部解除')}</Button>}>
            <div className="flex flex-col gap-1.5 text-sm">
              {st.blocked!.map((b, i) => {
                const n = ruleName(b.script, b.rule)
                return (
                  <div key={i} className="flex flex-wrap items-center gap-2">
                    <span className="text-stone-500">{dn(b.device)}</span><b>{n.script}</b>{t('·規則「{rule}」', { rule: n.rule })}
                    <span className="text-xs text-amber-800">{b.reason}</span>
                    <Link className="text-xs underline ml-auto" to={`/scripts?script=${encodeURIComponent(b.script)}`}>{t('去修改')}</Link>
                  </div>
                )
              })}
            </div>
          </Card>
        )}
        <Card title={t('通知({length})', { length: alerts.length })}>
          {alerts.length ? (
            <div className="flex flex-col gap-0.5 max-h-80 overflow-auto">
              {alerts.map((a, i) => (
                <div key={i} className={`text-xs ${a.level === 'warn' ? 'text-rose-700' : 'text-stone-700'}`}>
                  <span className="num text-stone-400 mr-2">{clock(a.t)}</span>{a.device && <span className="mr-1">{dn(a.device)}</span>}{a.text}
                </div>
              ))}
            </div>
          ) : <Empty>{running ? t('還沒有通知') : t('執行後這裡會顯示通知')}</Empty>}
        </Card>
        {(st.vars?.defs ?? []).length > 0 && <VarsCard st={st} />}
      </div>
      <div className="flex flex-col gap-4">
        <History />
        <Stuck />
        <Flags states={states} />
      </div>
    </div>
  )
}

/** Which model, how often, and the safety limits. */
function Settings({ st, states, running, run, setRun, interval, setInterval, onStart, onStop, busy }: {
  st: ShadowStatus; states: StateDef[]; running: boolean; run: string; setRun: (v: string) => void; interval: number; setInterval: (v: number) => void
  onStart: () => void; onStop: () => void; busy: boolean
}) {
  const qc = useQueryClient()
  const runs = useQuery({ queryKey: ['trainRuns'], queryFn: api.trainRuns })
  const done = (runs.data?.runs ?? []).filter(r => r.status.state === 'done')
  const judge = useQuery({ queryKey: ['statesJudge', run, running], queryFn: () => api.statesJudge(run), refetchInterval: 15000 })
  // the settings file itself (the runner's report is stale while it is not running); the runner's defaults underneath
  const saved = useQuery({ queryKey: ['shadowControl'], queryFn: api.shadowControlGet })
  const c: ShadowControl = { ...CONTROL_DEFAULT, ...(saved.data ?? st.control ?? {}) }
  const [savedAt, setSavedAt] = useState(0)
  const set = useMutation({ mutationFn: api.shadowControl, onSuccess: () => {
    setSavedAt(Date.now()); qc.invalidateQueries({ queryKey: ['shadowControl'] }); qc.invalidateQueries({ queryKey: ['shadow'] }) } })
  useEffect(() => { if (!savedAt) return; const tx = setTimeout(() => setSavedAt(0), 3000); return () => clearTimeout(tx) }, [savedAt])
  const savedNote = <span className="text-xs text-emerald-700">{savedAt ? t('✓ 已儲存') : ''}</span>
  const field = 'border border-stone-300 rounded px-2 py-1 num'
  return (
    <div className="grid xl:grid-cols-2 gap-4 items-start">
      <Card title={t('模型與速度')} extra={running && <span className="text-xs text-stone-500">{t('執行程式運作中不能改,先關閉')}</span>}>
        <div className="flex flex-col gap-3 text-sm">
          <div className="flex flex-wrap items-center gap-2 rounded-md bg-stone-50 border border-stone-200 px-3 py-2">
            <span className="flex-1 text-xs text-stone-600">{running
              ? t('執行程式運作中。換模型或速度時才需要關閉;關閉後不看、不判斷、不通知,再啟動時每台停下來 / 暫停的狀態維持原樣。要讓腳本先別動,用「暫停」或「停下來」就好。')
              : t('執行程式沒有啟動。')}</span>
            {running
              ? <Button variant="danger" disabled={busy} onClick={() => { if (confirm(t('關閉執行程式?之後不看、不判斷、不通知,直到再啟動。\n(只是要腳本先別動的話,用「暫停」或「停下來」)'))) onStop() }}>{t('■ 關閉執行程式')}</Button>
              : <Button variant="primary" disabled={busy} onClick={onStart}>{t('▶ 啟動執行程式')}</Button>}
          </div>
          <label className="flex flex-col gap-1"><span className="text-stone-600">{t('使用的模型')}</span>
            <select className="border border-stone-300 rounded-md px-2 py-1.5" value={run} disabled={running} onChange={e => setRun(e.target.value)}>
              <option value="">{t('最新一次完成的訓練')}</option>
              {done.map(r => <option key={r.id} value={r.id}>{r.config?.name || r.id} · {r.id.slice(0, 13)}</option>)}
            </select></label>
          {st.model && <div className="text-xs text-stone-500">{t('執行中的模型:{p1}{p2}', { p1: st.model.split(/[\\/]/).slice(-2, -1)[0], p2: st.model_backend && ` · ${st.model_backend}` })}</div>}
          <label className="flex items-center gap-2 flex-wrap">{t('每')}
            <input type="number" step={100} min={300} max={10000} value={Math.round(interval * 1000)} disabled={running}
              onChange={e => { const ms = Math.round(Number(e.target.value) / 100) * 100; if (ms >= 300 && ms <= 10000) setInterval(ms / 1000) }} className={`${field} w-24`} />
            {t('毫秒看一次')}<span className="text-xs text-stone-500">{t('({p1} 秒;最快 300)', { p1: interval.toFixed(1) })}{st.tick_ms ? t(';每一輪處理約 {tick_ms} 毫秒', { tick_ms: st.tick_ms }) + (st.interval && st.interval * 1000 > st.tick_ms ? t(',其餘 {p1} 毫秒空閒', { p1: Math.round(st.interval * 1000 - st.tick_ms) }) : '') : ''}</span></label>
          {st.tick_ms && interval * 1000 < st.tick_ms && <div className="text-xs text-amber-700">{t('比每一輪的處理時間還短:會一輪接一輪沒有空閒,電腦負擔變重,也不會再更快')}</div>}
          <div className="border-t border-stone-100 pt-2">
            <div className="text-xs text-stone-500">{t('每個狀態怎麼判斷')}</div>
            <JudgeSummary info={judge.data} states={states} />
          </div>
        </div>
      </Card>
      <Card title={t('安全限制')} extra={savedNote}>
        <div className="flex flex-col gap-3 text-sm">
          <div className="text-xs text-stone-500">{t('改完按 Enter 或點別處就會儲存;執行程式沒啟動時也會存,下次啟動照用。')}</div>
          <ErrorText error={set.error} />
          <label className="flex items-center gap-1">{t('每台每分鐘最多點')}
            <NumField min={1} max={60} className={`${field} w-16`} value={c.max_per_min} onSave={v => set.mutate({ max_per_min: v })} />{t('次')}</label>
          <label className="flex items-center gap-1">{t('同一條規則連續')}
            <NumField min={1} max={10} className={`${field} w-14`} value={c.max_strikes} onSave={v => set.mutate({ max_strikes: v })} />{t('次沒效果就暫停(條件不成立後自動解除)')}</label>
          <label className="flex items-center gap-1" title={t('偵測到你在{device}上點擊或滑動時,那台先不執行,也會中斷進行中的子腳本;填 0 = 不暫停', { device: words.device })}>{t('手動操作後暫停')}
            <NumField min={0} max={3600} className={`${field} w-20`} value={c.manual_pause_s ?? 60} onSave={v => set.mutate({ manual_pause_s: v })} />{t('秒')}</label>
          {c.manual_pause_s === 0 && <div className="text-xs text-amber-700 -mt-2">{t('目前手動操作時腳本不會讓開:你在{device}上操作時,它照樣會動作', { device: words.device })}</div>}
          <label className="flex items-center gap-1" title={t('執行器啟動、或來源斷線後回來時:每台畫面正常這麼久才開始動作(這段時間只看不點)')}>{t('啟動確認')}
            <NumField min={0} max={600} className={`${field} w-16`} value={c.start_wait_s ?? 5} onSave={v => set.mutate({ start_wait_s: v })} />{t('秒')}</label>
          <label className="flex items-center gap-1" title={t('畫面完全沒變這麼久就通知「畫面卡住」(程式當掉、串流停住);填 0 = 不偵測。靜止的畫面(例如晚上的攝影機)可以設長一點')}>{t('畫面沒變化')}
            <NumField min={0} max={86400} className={`${field} w-20`} value={c.freeze_seconds ?? 300} onSave={v => set.mutate({ freeze_seconds: v })} />{t('秒就算卡住')}</label>
          <label className="flex items-center gap-1" title={t('畫面一片黑或單色這麼久就通知(鏡頭被擋住、沒有訊號);填 0 = 不偵測。晚上暗暗的畫面不算,還看得到東西就不算')}>{t('畫面全黑或單色')}
            <NumField min={0} max={86400} className={`${field} w-20`} value={c.blank_seconds ?? 60} onSave={v => set.mutate({ blank_seconds: v })} />{t('秒就通知')}</label>
          <Link to="/storage#keep" className="text-xs underline text-stone-600 self-center">{t('執行紀錄保留幾天:儲存空間 ›')}</Link>
        </div>
      </Card>
      <Card title={t('收集與顯示')} extra={savedNote}>
        <div className="flex flex-col gap-3 text-sm">
          <label className="flex items-center gap-1.5 flex-wrap" title={t('模型信心低,或模型和參考圖判斷不一樣時,存下畫面到「回答問題 › 執行時存下的」')}>
            <input type="checkbox" checked={c.auto_save ?? true} onChange={e => set.mutate({ auto_save: e.target.checked })} />
            {t('自動存下拿不準的畫面,每小時最多')}
            {(c.auto_save ?? true)
              ? <NumField min={1} max={200} className={`${field} w-16`} value={c.auto_save_per_hour ?? 20} onSave={v => set.mutate({ auto_save_per_hour: v })} />
              : <input type="number" className={`${field} w-16`} value={c.auto_save_per_hour ?? 20} disabled />}{t('張')}
            <span className="text-xs text-stone-500">{t('(最近一小時存了 {p1} 張)', { p1: st.saved_last_hour ?? 0 })}</span></label>
          <label className="flex items-center gap-1.5" title={t('關掉後不再產生即時畫面(判斷和執行不受影響);開著時也只在這一頁打開時才產生')}>
            <input type="checkbox" checked={c.live_view ?? true} onChange={e => set.mutate({ live_view: e.target.checked })} />
            {t('顯示即時畫面(只在這一頁開著時產生)')}</label>
        </div>
      </Card>
    </div>
  )
}

/** which states the model answers and which fall back to a screen rule (with the chosen / running model) */
function JudgeSummary({ info, states }: { info?: JudgeInfo; states: StateDef[] }) {
  if (!info) return null
  const by = (src: string) => states.filter(s => info.states[s.id]?.source === src)
  const model = by('model'), rule = by('rule'), none = by('none')
  return (
    <div className="text-xs mt-2 flex flex-col gap-1">
      <div className="flex flex-wrap gap-1 items-center">
        <span className="text-stone-500" title={t('模型沒把握時,有畫面規則的狀態會由規則幫忙確認(標「只用模型」的除外)')}>{info.run_name ? t('模型判斷({name}):', { name: info.run_name }) : t('模型判斷:')}</span>
        {model.length ? model.map(s => <span key={s.id} className="px-1.5 rounded bg-stone-100 text-stone-700" title={info.states[s.id].reason}>{s.name}
          {info.states[s.id].only && <span className="ml-1 text-[10px] text-rose-700">{t('只用模型')}</span>}</span>) : <span className="text-stone-400">{t('無')}</span>}
      </div>
      {rule.length > 0 && <div className="flex flex-wrap gap-1 items-center">
        <span className="text-stone-500">{t('參考圖/顏色判斷:')}</span>
        {rule.map(s => <span key={s.id} className="px-1.5 rounded bg-sky-600 text-white" title={info.states[s.id].reason}>{s.name}
          {info.states[s.id].mode === 'rule' && <span className="ml-1 text-[10px]">{t('只用規則')}</span>}</span>)}
        <span className="text-stone-500">{t('(滑鼠移上去看原因)')}</span>
      </div>}
      {none.length > 0 && <div className="flex flex-wrap gap-1 items-center">
        <span className="text-stone-500">{t('執行時不判斷:')}</span>
        {none.map(s => <span key={s.id} className="px-1.5 rounded bg-stone-50 text-stone-400 border border-stone-200" title={info.states[s.id].reason}>{s.name}</span>)}
      </div>}
    </div>
  )
}

/** current values of the variables (counters, "last time"); click a value to change it */
function VarsCard({ st }: { st: ShadowStatus }) {
  const v = st.vars!
  const devices = Object.keys(v.device).sort()
  const show = (x: number | undefined) => {
    if (x == null) return '—'
    return x > 1e9 ? clock(x) : String(x)            // a stored time vs a number
  }
  return (
    <Card title={t('變數')} extra={<span className="text-xs text-stone-500">{t('點數字可以修改;每天歸零的變數會在 0 點回到初始值')}</span>}>
      <div className="overflow-auto">
        <table className="text-sm">
          <thead><tr className="text-xs text-stone-500 text-left">
            <th className="font-normal pr-4 py-1">{t('變數')}</th>
            {devices.map(d => <th key={d} className="font-normal px-3" title={d}>{dn(d)}</th>)}
            <th className="font-normal px-3">{t('全部共用')}</th>
          </tr></thead>
          <tbody>
            {v.defs.map(d => (
              <tr key={d.name} className="border-t border-stone-100">
                <td className="pr-4 py-1.5">{d.label || d.name}<span className="text-[11px] text-stone-400 ml-1">{d.reset === 'daily' ? t('每天歸零') : ''}</span></td>
                {d.scope === 'device'
                  ? devices.map(dev => <td key={dev} className="px-3"><VarValue text={show(v.device[dev]?.[d.name])} onSet={n => api.shadowVarSet({ var: d.name, value: n, device: dev })} /></td>)
                  : devices.map(dev => <td key={dev} className="px-3 text-stone-300">·</td>)}
                <td className="px-3">{d.scope === 'global' ? <VarValue text={show(v.global[d.name])} onSet={n => api.shadowVarSet({ var: d.name, value: n })} /> : <span className="text-stone-300">·</span>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  )
}

function VarValue({ text, onSet }: { text: string; onSet: (n: number) => void }) {
  return (
    <button className="num underline decoration-dotted underline-offset-2 hover:text-amber-700" title={t('點一下修改')}
      onClick={() => { const s = prompt(t('新的值(數字;要清掉「上次時間」就填 0)'), text.match(/^-?[\d.]+$/) ? text : '0'); if (s != null && s.trim() !== '' && !isNaN(Number(s))) onSet(Number(s)) }}>{text}</button>
  )
}

const TL_STYLE = (r: TimelineRow) =>
  r.action === 'alert' ? (r.level === 'warn' ? 'bg-rose-100 text-rose-800' : 'bg-sky-100 text-sky-800')
    : r.executed && r.action !== 'sub_step' ? 'bg-rose-600 text-white'
    : r.action === 'sub_step' ? 'bg-amber-100 text-amber-900'
    : r.action === 'set_var' ? 'bg-emerald-100 text-emerald-800' : 'bg-stone-100 text-stone-700'

/** what the runner did on one device: decisions that changed, inputs, sub-script steps, situation switches, alerts */
function Timeline({ device }: { device: string }) {
  const [minutes, setMinutes] = useState(30)
  const q = useQuery({ queryKey: ['timeline', device, minutes], queryFn: () => api.shadowTimeline(device, minutes), refetchInterval: 5000 })
  const rows = q.data ?? []
  return (
    <div className="flex flex-col gap-1.5 border-t border-stone-100 pt-2">
      <div className="flex items-center gap-2 text-xs text-stone-500">{t('時間軸(最新在上)')}
        <select className="border border-stone-300 rounded px-1 py-0.5" value={minutes} onChange={e => setMinutes(Number(e.target.value))}>
          {[10, 30, 60, 180, 720].map(m => <option key={m} value={m}>{m >= 60 ? t('最近 {n} 小時', { n: m / 60 }) : t('最近 {n} 分鐘', { n: m })}</option>)}
        </select>
        <span>{t('{length} 筆', { length: rows.length })}</span>
      </div>
      {rows.length === 0 ? <div className="text-xs text-stone-400">{t('這段時間沒有紀錄')}</div> : (
        <div className="max-h-72 overflow-auto flex flex-col gap-0.5">
          {rows.map((r, i) => (
            <div key={i} className="flex gap-2 text-xs items-start">
              <span className="num text-stone-400 shrink-0">{clock(r.t)}</span>
              <span className={`px-1.5 rounded shrink-0 ${TL_STYLE(r)}`}>{r.action === 'alert' ? t('通知') : r.action === 'sub_step' ? t('子腳本')
                : r.action === 'set_var' ? t('變數') : r.executed ? t('執行') : t('決定')}</span>
              <span className="text-stone-700">{r.action === 'set_var' ? `${r.var}:${String(r.old)} → ${String(r.new)}`
                : `${r.script_name ? `[${r.script_name}] ` : ''}${r.text ?? ''}${r.reason ? `:${r.reason}` : ''}`}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function valueName(states: StateDef[], sid: string, v: unknown) {
  const s = states.find(x => x.id === sid)
  const c = s?.classes?.find(c => c.value === v)
  return { name: c?.name ?? String(v ?? '—'), color: c?.color, state: s?.name ?? sid }
}

function DeviceFrame({ d, v, view }: { d: ShadowDevice; v: number; view: boolean }) {
  const taps = d.decisions.filter(x => x.tap).map(x => x.tap!)
  return (
    <div className="relative w-full aspect-video bg-stone-900 overflow-hidden">
      {d.window && view && <img src={shadowLiveUrl(d.name, Math.floor(v))} alt={d.name} className="absolute inset-0 w-full h-full" />}
      {d.window && !view && <div className="absolute inset-0 flex items-center justify-center text-xs text-stone-400">{t('即時畫面已關閉(判斷照常進行)')}</div>}
      {!d.window && <div className="absolute inset-0 flex items-center justify-center text-xs text-stone-400">{t('沒有視窗({device}沒開或縮到最小)', { device: words.device })}</div>}
      {taps.map((tap, i) => (
        <span key={i}>
          <span className="absolute w-6 h-6 -ml-3 -mt-3 rounded-full border-4 border-amber-400 animate-ping"
            style={{ left: `${(tap[0] / screen.w) * 100}%`, top: `${(tap[1] / screen.h) * 100}%` }} />
          <span className="absolute w-4 h-4 -ml-2 -mt-2 rounded-full bg-amber-400/80"
            style={{ left: `${(tap[0] / screen.w) * 100}%`, top: `${(tap[1] / screen.h) * 100}%` }} />
        </span>
      ))}
    </div>
  )
}

function DeviceCard({ d, states, v, live, stops = [], hold }: {
  d: ShadowDevice; states: StateDef[]; v: number; live: boolean; stops?: { device: string; script: string; rule: string; reason: string }[]; armed?: boolean
  hold?: Hold | null
}) {
  const qc = useQueryClient()
  const resume = useMutation({ mutationFn: (b: { device: string; script: string; rule: string }) => api.shadowControl({ resume: b }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['shadow'] }) })
  const [flagged, setFlagged] = useState<number | null>(null)
  const [win, setWin] = useState<'acts' | 'more' | null>(null)
  const flag = useMutation({ mutationFn: () => api.shadowFlag(d.name), onSuccess: () => setFlagged(Date.now()) })
  const act = useMutation({ mutationFn: (kind: 'stop' | 'pause' | 'resume') => api.shadowAct({ device: d.name, kind, mode: kind === 'stop' ? 'stop' : undefined }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['shadow'] }) })
  const resumeOne = () => {
    if (d.cause_now && !confirm(t('{name}:{p2}\n原因還在畫面上,繼續後會馬上再停下來。還是要繼續嗎?', { name: dn(d.name), p2: hold?.why ?? '' }))) return
    act.mutate('resume')
  }
  const st = d.state
  // on the card: what each script decides (the guard rules only when they do something); the rest under 詳細
  const mainDec = d.decisions.filter(x => !x.guard || (x.action !== 'none' && x.action !== 'uncertain'))
  return (
    <Card title={d.name} extra={<span className="flex items-center gap-2 text-xs text-stone-500 num">
      {d.manual?.paused && <span className="px-1.5 py-0.5 rounded bg-amber-100 text-amber-800" title={t('偵測到手動操作,這台暫停執行')}>{t('✋ 手動操作中,{resume_in} 秒後恢復', { resume_in: d.manual.resume_in })}</span>}
      {d.manual && !d.manual.watched && live && <span className="text-stone-400" title={t('裝置來源目前無法偵測手動操作')}>{t('未偵測觸控')}</span>}
      {d.window ? t('視窗 {window}', { window: d.window }) : t('沒有視窗')}</span>}>
      <div className="flex flex-col gap-3">
        {hold && (
          <div className={`rounded-md border-2 px-3 py-2 text-sm flex items-start gap-3 ${hold.cause ? 'border-rose-400 bg-rose-50 text-rose-900' : 'border-amber-400 bg-amber-50 text-amber-900'}`}>
            <div className="flex-1">
              <div className="font-semibold">{hold.mode === 'pause' ? t('⏸ 這台暫停中') : t('🛑 這台已停下來')}{hold.cause ? `(${hold.by})` : t('(由「{by}」按下)', { by: hold.by })}</div>
              {hold.why && <div className="text-xs mt-0.5">{t('原因:{why}', { why: hold.why })}</div>}
              <div className="text-xs mt-0.5">{t('{p1} 停下 · 腳本和情境都停住(守門規則和排程也不動)', { p1: new Date(hold.t * 1000).toLocaleString(locale, { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' }) })}{hold.mode === 'pause' ? t(';按「繼續」從同一步接著做') : t(';按「繼續」後從頭開始')}</div>
              {d.cause_now === true && <div className="text-xs mt-1 font-semibold">{t('⚠ 原因還在畫面上:現在按「繼續」會馬上再停下來,請先處理。')}</div>}
              {d.cause_now === false && <div className="text-xs mt-1 text-emerald-800">{t('原因已經不在畫面上,可以繼續。')}</div>}
              {hold.again != null && <div className="text-xs mt-1 font-semibold">{t('⚠ 上次按「繼續」後 {again} 秒又因同樣原因停下來。', { again: hold.again })}</div>}
            </div>
            <Button variant="primary" disabled={act.isPending} onClick={() => resumeOne()}>{t('▶ 繼續')}</Button>
          </div>
        )}
        {stops.map(b => {
          const name = d.decisions.find(x => x.script === b.script)?.script_name ?? b.script
          return (
            <div key={`${b.script}|${b.rule}`} className="rounded-md border-2 px-3 py-2 text-sm flex items-start gap-3 border-amber-300 bg-amber-50 text-amber-900">
              <div className="flex-1">
                <div className="font-semibold">{t('⏸ 「{name}」的規則「{rule}」暫停中(其他規則照常)', { name, rule: b.rule })}</div>
                <div className="text-xs mt-0.5">{t('原因:{reason}', { reason: b.reason })}</div>
              </div>
              <Button disabled={resume.isPending} onClick={() => resume.mutate({ device: b.device, script: b.script, rule: b.rule })}>{t('解除')}</Button>
            </div>
          )
        })}
        {d.held && <div className="rounded-md border border-violet-300 bg-violet-50 px-3 py-2 text-violet-900 text-sm">{t('🛡 守門規則「{held}」:這台的其他腳本暫停中', { held: d.held })}</div>}
        {Object.entries(d.situations ?? {}).filter(([, x]) => x.count > 1).length > 0 && (
          <div className="flex flex-wrap gap-1.5 text-xs">
            {Object.entries(d.situations ?? {}).filter(([, x]) => x.count > 1).map(([sid, x]) => (
              <span key={sid} className="px-2 py-0.5 rounded-full bg-stone-900 text-white" title={t('這個主腳本在這台目前的情境')}>
                {(d.decisions.find(dd => dd.script === sid)?.script_name) ?? sid}:{x.name}<span className="opacity-60 num"> {duration(v - x.since)}</span>
              </span>
            ))}
          </div>
        )}
        {d.proc && (
          <div className={`rounded-md border px-3 py-2 ${d.proc.cleaning ? 'border-amber-300 bg-amber-50 text-amber-900' : 'border-rose-300 bg-rose-50 text-rose-900'}`}>
            <div className="text-[11px] opacity-80">{t('控制權:{script_name}', { script_name: d.proc.script_name })}{d.proc.rule_name ? t(' · 規則「{rule_name}」', { rule_name: d.proc.rule_name }) : ''}</div>
            <div className="font-semibold">{d.proc.chain.map(c => t('{sub}(第 {step}/{steps} 步)', { sub: c.sub, step: c.step, steps: c.steps })).join(' › ')}</div>
            <div className="text-xs">{d.proc.now || '…'}{d.proc.retry ? t(' · 重試 {retry}', { retry: d.proc.retry }) : ''}{d.proc.loop ? ` · ${d.proc.loop}` : ''}{d.proc.paused ? t(' · ⏸ 暫停中(手動操作)') : ''} {t('· 已執行 {p1}', { p1: duration(v - d.proc.started) })}</div>
            {d.proc.cleaning && <div className="text-xs mt-0.5">{t('正在收尾:{message}', { message: d.proc.message })}</div>}
          </div>
        )}
        {live && <div className="flex flex-wrap items-center gap-2">
          {hold ? null : <>
            <Button disabled={act.isPending} onClick={() => act.mutate('pause')} title={t('腳本、情境和正在做的事都停在原地,按「繼續」從同一步接著做')}>{t('⏸ 暫停')}</Button>
            <Button variant="danger" disabled={act.isPending} onClick={() => { if (confirm(t('{name} 停下來?正在做的事會取消(先做收尾),腳本和情境都停住,按「繼續」後從頭開始。', { name: dn(d.name) }))) act.mutate('stop') }}>{t('🛑 停下來')}</Button>
          </>}
          <MoreButton onClick={() => setWin('acts')} title={t('立即執行排程、切換情境、執行子腳本')}>{t('⚡ 操作…')}</MoreButton>
          <span className="flex-1" />
          <MoreButton onClick={() => setWin('more')} title={t('每條規則的判斷、所有狀態、時間軸')}>{t('詳細')}</MoreButton>
        </div>}
        <ErrorText error={act.error} />
        {!d.proc && d.decisions.length === 0 && <div className="text-xs text-stone-500">{t('沒有腳本在這台執行(到「部署」設定)')}</div>}
        {mainDec.map(dec => <DecisionBox key={dec.script} dec={dec} d={d} v={v} />)}
        {d.decisions.length > mainDec.length && <div className="text-[11px] text-stone-400">{t('另外 {p1} 條守門規則沒有動作(看「詳細」)', { p1: d.decisions.length - mainDec.length })}</div>}
        <div className="flex items-center gap-2">
          <Button variant="ghost" onClick={() => flag.mutate()} disabled={!live || !d.window || flag.isPending}
            title={t('把這一刻的畫面存下來,之後回答正確答案,成為測試資料')}>{t('判斷錯了')}</Button>
          {flagged && Date.now() - flagged < 5000 && <span className="text-xs text-emerald-700">{t('已存下這張畫面,可以在「紀錄 › 標記的畫面」回答')}</span>}
        </div>
        <Modal open={win === 'acts'} title={t('操作 {name}', { name: dn(d.name) })} onClose={() => setWin(null)}>
          <DeviceActions device={d.name} proc={d.proc} hold={hold ?? null} bare />
        </Modal>
        <Modal open={win === 'more'} wide title={t('{name} 的詳細判斷', { name: dn(d.name) })} onClose={() => setWin(null)}>
          <div className="text-xs font-semibold text-stone-600">{t('每個腳本的判斷(含守門規則)')}</div>
          {d.decisions.map(dec => <DecisionBox key={dec.script} dec={dec} d={d} v={v} />)}
        {st && (
          <div className="flex flex-wrap gap-1.5 text-xs">
            {states.filter(s => s.type === 'class' && st[s.id]).map(s => s.id).map(k => {
              const n = valueName(states, k, st[k].value)
              const low = (st[k].conf ?? 1) < 0.7
              const tx = sourceTag(st[k])
              return (
                <span key={k} className={`px-2 py-0.5 rounded-full inline-flex items-center gap-1 ${n.color ? COLORS[n.color]?.pill : 'bg-stone-100 text-stone-600'} ${low ? 'ring-1 ring-rose-400' : ''}`}
                  title={tx.tip}>
                  {n.state}:{st[k].value == null ? t('不確定') : n.name}
                  <span className={`px-1 rounded text-[10px] ${st[k].source === 'rule' ? 'bg-sky-600 text-white' : st[k].source === 'model+rule' ? 'bg-sky-100 text-sky-800' : 'bg-white/60 text-stone-600'}`}>{tx.tag}{tx.num && <span className="num"> {tx.num}</span>}</span>
                </span>
              )
            })}
            {states.filter(x => x.type === 'ratio' && st[x.id]).map(x => (
              <span key={x.id} className="px-2 py-0.5 rounded-full bg-stone-100 text-stone-700 num">{x.name} {Math.round(Number(st[x.id].value) * 100)}%</span>
            ))}
          </div>
        )}
          <div className="text-xs font-semibold text-stone-600 mt-2">{t('時間軸')}</div>
          <Timeline device={d.name} />
        </Modal>
      </div>
    </Card>
  )
}

function DecisionBox({ dec, d, v }: { dec: ShadowDevice['decisions'][number]; d: ShadowDevice; v: number }) {
  return (
          <div className={`rounded-md border px-3 py-2 ${ACTION_STYLE[dec.action] ?? ACTION_STYLE.none}`}>
            <div className="flex justify-between items-center gap-2">
              <span className="font-semibold">{dec.urgent && <span className="text-[10px] px-1 mr-1 rounded bg-rose-600 text-white align-middle">{t('緊急')}</span>}{dec.tap || dec.action === 'call' ? t('會做:{text}', { text: dec.text }) : dec.text}</span>
              <span className="text-xs opacity-70 whitespace-nowrap">{dec.stable ? (dec.since ? t('持續 {p1}', { p1: duration(v - dec.since) }) : '') : t('確認中…')}</span>
            </div>
            <div className="text-xs mt-0.5">{dec.reason}</div>
            {(dec as { warnings?: string[] }).warnings?.map((w, i) => <div key={i} className="text-xs mt-0.5 text-rose-700">⚠ {w}</div>)}
            <div className="text-[11px] mt-1 flex gap-1.5 items-center opacity-80">
              <span className={`px-1.5 rounded ${(MODE_TAG[dec.mode ?? ''] ?? ['', ''])[1]}`}>{(MODE_TAG[dec.mode ?? ''] ?? [dec.mode])[0]}</span>
              {dec.guard ? '🛡 ' : ''}{dec.script_name}{dec.situation_name && !dec.guard && (d.situations?.[dec.script ?? '']?.count ?? 1) > 1 ? `(${dec.situation_name})` : ''}{dec.rule_name ? ` · ${dec.on_enter ? '' : t('規則')}「${dec.rule_name}」` : ''}
              {dec.exec && <span className={`ml-auto px-1.5 rounded ${dec.done ? 'bg-rose-600 text-white' : 'bg-white/70'}`}>{dec.exec}</span>}
            </div>
            {dec.sub_steps && !dec.done && <pre className="text-[11px] mt-1 opacity-80 whitespace-pre-wrap">{dec.sub_steps.join(String.fromCharCode(10))}</pre>}
          </div>
  )
}

function History() {
  const q = useQuery({ queryKey: ['shadowLog'], queryFn: () => api.shadowLog(150), refetchInterval: 3000 })
  const [onlyAct, setOnlyAct] = usePersistentState('shadow.onlyAct', false)
  const rows = (q.data ?? []).filter(r => !onlyAct || r.tap || r.executed || r.action === 'call' || r.action === 'alert')
  return (
    <Card title={t('決定紀錄(狀態改變時記一筆)')} extra={
      <label className="text-xs flex items-center gap-1"><input type="checkbox" checked={onlyAct} onChange={e => setOnlyAct(e.target.checked)} />{t('只看點擊、流程和通知')}</label>}>
      {rows.length === 0 ? <Empty>{t('還沒有紀錄')}</Empty> : (
        <div className="max-h-[480px] overflow-auto">
          <table className="text-sm w-full">
            <tbody>
              {rows.map((r, i) => (
                <tr key={i} className="border-t border-stone-100 align-top">
                  <td className="py-1 pr-2 text-xs text-stone-500 num whitespace-nowrap">{clock(r.t)}</td>
                  <td className="pr-2 text-xs whitespace-nowrap">{dn(r.device)}<div className="text-stone-400">{r.script_name}</div></td>
                  <td className="pr-2 whitespace-nowrap">{r.action === 'alert' ? <span className={r.level === 'warn' ? 'text-rose-700' : ''}>{t('通知')}</span>
                    : r.executed ? <span className="text-rose-700 font-semibold">{t('▶ 已{text}', { text: r.text })}</span>
                    : r.tap || r.action === 'call' ? <span className="text-amber-800 font-medium">{t('會{text}', { text: r.text })}</span> : r.text}</td>
                  <td className="text-xs text-stone-500">{r.reason}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  )
}

/** The screens kept when a device got stuck: what the scripts did not foresee (teach them from these). */
function Stuck() {
  const q = useQuery({ queryKey: ['shadowStuck'], queryFn: api.shadowStuck, refetchInterval: 15000 })
  const rows = q.data ?? []
  const [all, setAll] = useState(false)
  if (!rows.length) return null
  return (
    <Card title={t('卡住時的畫面({length})', { length: rows.length })} extra={<span className="text-xs text-stone-500">{t('畫面停住、排程或子腳本失敗、主腳本等了 5 分鐘以上時自動存下')}</span>}>
      <div className="flex flex-col gap-3 max-h-[720px] overflow-auto">
        {(all ? rows : rows.slice(0, 6)).map(r => (
          <div key={r.frame} className="flex gap-3 border border-stone-200 rounded-md p-2">
            <a href={imageUrl(r.frame)} target="_blank" rel="noreferrer"><img src={imageUrl(r.frame, 320)} alt="" className="w-56 rounded" /></a>
            <div className="text-xs flex flex-col gap-1">
              <div className="font-medium">{dn(r.device)} · {new Date(r.t * 1000).toLocaleString(locale, { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' })}</div>
              <div className="text-rose-800">{r.why}</div>
              {r.proc?.sub_name && <div className="text-stone-500">{t('當時在做:{sub_name} · {now}', { sub_name: r.proc.sub_name, now: r.proc.now })}</div>}
            </div>
          </div>
        ))}
        {rows.length > 6 && !all && <button className="text-xs underline text-stone-500 text-left" onClick={() => setAll(true)}>{t('看全部 {length} 張', { length: rows.length })}</button>}
      </div>
    </Card>
  )
}

function Flags({ states }: { states: StateDef[] }) {
  const q = useQuery({ queryKey: ['shadowFlags'], queryFn: api.shadowFlags, refetchInterval: 5000 })
  const rows = q.data ?? []
  const todo = rows.filter(r => !r.answered).length
  return (
    <Card title={t('標記的畫面({todo} 張待回答)', { todo })}>
      {rows.length === 0 ? <Empty>{t('腳本執行中,看到判斷錯的就按該台的「判斷錯了」')}</Empty> : (
        <div className="flex flex-col gap-4 max-h-[720px] overflow-auto">
          {rows.map(r => <FlagItem key={r.frame} r={r} states={states} />)}
        </div>
      )}
    </Card>
  )
}

function FlagItem({ r, states }: { r: ShadowFlag; states: StateDef[] }) {
  const qc = useQueryClient()
  const questions = reviewStates(states)
  const [answers, setAnswers] = useState<Record<string, AnswerValue | '__skip__'>>({})
  const [open, setOpen] = useState(!r.answered)
  const save = useMutation({
    mutationFn: () => api.reviewDecide({ frame: r.frame, session: r.session, device: r.device, id: r.id,
      answers: Object.fromEntries(Object.entries(answers).filter(([, v]) => v !== '__skip__')) as Record<string, AnswerValue> }),
    onSuccess: () => { setOpen(false); qc.invalidateQueries({ queryKey: ['shadowFlags'] }) },
  })
  const complete = questions.every(q => answers[q.id] != null)
  return (
    <div className="border border-stone-200 rounded-md p-2 flex flex-col gap-2">
      <div className="flex gap-3">
        <a href={imageUrl(r.frame)} target="_blank" rel="noreferrer"><img src={imageUrl(r.frame, 320)} alt="" className="w-56 rounded" /></a>
        <div className="text-xs flex flex-col gap-1">
          <div className="font-medium">{dn(r.device)} · {clock(r.t)}</div>
          <div className="text-stone-600">{t('模型:{p1}', { p1: Object.entries(r.pred).slice(0, 4).map(([k, v]) => {
            const n = valueName(states, k, v); return `${n.state} ${n.name}`
          }).join(t('、')) })}</div>
          <div className="text-stone-500">{t('決定:{p1}', { p1: (r.decisions ?? (r.decision ? [r.decision] : [])).map(x => `${x.text}(${x.reason})`).join(t(';')) })}</div>
          {r.answered ? <Pill tone="green">{t('已回答')}</Pill> : <Pill tone="amber">{t('待回答')}</Pill>}
          {r.answered && !open && <button className="text-left underline text-stone-500" onClick={() => setOpen(true)}>{t('重新回答')}</button>}
        </div>
      </div>
      {open && (
        <div className="flex flex-col gap-2 text-sm">
          {questions.map(q => (
            <div key={q.id} className="flex flex-wrap gap-1 items-center">
              <span className="w-16 text-xs text-stone-600">{q.name}</span>
              {q.classes!.map(c => (
                <Button key={String(c.value)} variant={answers[q.id] === c.value ? 'primary' : 'default'} onClick={() => setAnswers(a => ({ ...a, [q.id]: c.value }))}>{c.name}</Button>
              ))}
              {!q.classes!.some(c => c.value === 'hidden') &&
                <Button variant={answers[q.id] === '__skip__' ? 'primary' : 'ghost'} onClick={() => setAnswers(a => ({ ...a, [q.id]: '__skip__' }))}>{t('無法判斷')}</Button>}
            </div>
          ))}
          <div className="flex gap-2 items-center">
            <Button variant="primary" disabled={!complete || save.isPending} onClick={() => save.mutate()}>{t('存成測試資料')}</Button>
            <span className="text-xs text-stone-500">{t('回答後會加入測試集;下次產生標籤後也會出現在「回答問題」')}</span>
          </div>
          <ErrorText error={save.error} />
        </div>
      )}
    </div>
  )
}

// ================================================================ urgent incidents
const INC_STATUS: Record<string, [string, string]> = {
  open: [t('進行中'), 'bg-rose-600 text-white'], resolved: [t('已結束'), 'bg-emerald-100 text-emerald-800'],
  timeout: [t('超時停止追蹤'), 'bg-amber-100 text-amber-900'], stopped: [t('執行停止'), 'bg-stone-200 text-stone-700'],
}
const INC_KIND: Record<string, [string, string]> = {
  trigger: ['🚨', 'text-rose-700 font-medium'], again: ['🚨', 'text-rose-700'], action: ['👆', 'text-stone-900'],
  exec: ['⛔', 'text-amber-800'], sub: ['▶', 'text-sky-800'], proc: ['▶', 'text-sky-900 font-medium'],
  situation: ['↪', 'text-violet-800'], hold: ['🛡', 'text-violet-800'], state: ['●', 'text-stone-600'],
  alert: ['!', 'text-stone-700'], frame: ['📷', 'text-stone-400'], resolved: ['✓', 'text-emerald-700 font-medium'],
  end: ['■', 'text-stone-900 font-medium'],
}

function Incidents({ states }: { states: StateDef[] }) {
  const list = useQuery({ queryKey: ['incidents'], queryFn: () => api.incidents(), refetchInterval: 5000 })
  const items = list.data?.items ?? []
  const [pick, setPick] = useState<string | null>(null)
  const cur = pick ?? items[0]?.id ?? null
  if (!items.length) return <Card><Empty>{list.isLoading ? t('讀取中…') : t('還沒有緊急事件。勾了「緊急」的規則一成立,這裡就會記下整個經過。')}</Empty></Card>
  return (
    <div className="grid xl:grid-cols-[340px_1fr] gap-4 items-start">
      <div className="flex flex-col gap-2 xl:sticky xl:top-28 max-h-[calc(100vh-8rem)] overflow-auto">
        {items.map(x => {
          const [st, tone] = INC_STATUS[x.status] ?? [x.status, 'bg-stone-100']
          return (
            <button key={x.id} onClick={() => setPick(x.id)}
              className={`text-left rounded-lg border bg-white px-3 py-2 ${cur === x.id ? 'border-stone-900 ring-2 ring-stone-900/10' : 'border-stone-200 hover:border-stone-400'}`}>
              <div className="flex items-center gap-2 text-sm">
                <span className={`text-[11px] px-1.5 rounded ${tone}`}>{st}</span>
                <span className="font-medium">{dn(x.device)}</span>
                <span className="text-xs text-stone-500 num ml-auto">{dateTime(x.start)}</span>
              </div>
              <div className="text-sm truncate">{x.triggers.map(tx => tx.rule_name).join(t('、'))}</div>
              <div className="text-xs text-stone-500 num">
                {x.end ? t('持續 {p1}', { p1: duration(x.end - x.start) }) : t('已 {p1}', { p1: duration(Date.now() / 1000 - x.start) })} {t('· 點擊 {actions} 次', { actions: x.actions })}{x.warnings ? t(' · 警告 {warnings}', { warnings: x.warnings }) : ''}
              </div>
              {x.not_done.length > 0 && <div className="text-xs text-amber-800 truncate" title={x.not_done.join('\n')}>{t('⛔ 有時沒執行:{p1}', { p1: x.not_done.join(t('、')) })}</div>}
              {x.urgent_actions === 0 && <div className="text-xs text-rose-700">{t('緊急規則一次都沒有真的點擊')}</div>}
            </button>
          )
        })}
      </div>
      {cur && <IncidentView key={cur} id={cur} states={states} />}
    </div>
  )
}

/** An incident's clip: a frame a second from before the trigger to after it, played back (no video file: the frames). */
function ClipPlayer({ id, clip, start }: { id: string; clip: [number, string][]; start: number }) {
  const [k, setK] = useState(() => Math.max(0, clip.findIndex(([tt]) => tt >= start)))
  const [playing, setPlaying] = useState(false)
  const [speed, setSpeed] = useState(2)
  useEffect(() => {                                       // the frames are a second apart: shown 1 / speed seconds each
    if (!playing) return
    const h = window.setInterval(() => setK(i => { if (i >= clip.length - 1) { setPlaying(false); return i } return i + 1 }), 1000 / speed)
    return () => window.clearInterval(h)
  }, [playing, speed, clip.length])
  useEffect(() => { clip.slice(0, 20).forEach(([, n]) => { new Image().src = api.incidentClipUrl(id, n) }) }, [id, clip])   // smooth start
  const at = clip[Math.min(k, clip.length - 1)][0] - start
  return (
    <div className="flex flex-col gap-1.5" data-testid="clip">
      <div className="relative">
        <img src={api.incidentClipUrl(id, clip[Math.min(k, clip.length - 1)][1])} alt="" className="w-full rounded-md border border-stone-200 bg-stone-900" />
        <span className={`absolute left-2 top-2 text-xs px-1.5 py-0.5 rounded num ${at < 0 ? 'bg-stone-800/80 text-white' : 'bg-rose-600 text-white'}`}>
          {at < 0 ? t('事件前 {s} 秒', { s: Math.round(-at) }) : t('事件後 {s} 秒', { s: Math.round(at) })}</span>
      </div>
      <div className="flex items-center gap-3 text-sm">
        <Button onClick={() => { if (k >= clip.length - 1) setK(0); setPlaying(p => !p) }}>{playing ? t('⏸ 暫停') : t('▶ 播放')}</Button>
        <input type="range" min={0} max={clip.length - 1} value={k} onChange={e => { setPlaying(false); setK(Number(e.target.value)) }} className="flex-1" />
        <select className="border border-stone-300 rounded px-1 py-0.5 text-xs" value={speed} onChange={e => setSpeed(Number(e.target.value))}>
          {[1, 2, 4].map(v => <option key={v} value={v}>{v}×</option>)}</select>
        <span className="text-xs text-stone-500 num">{t('前後 {n} 秒', { n: Math.round(clip[clip.length - 1][0] - clip[0][0]) })}</span>
      </div>
    </div>
  )
}

/** The incident as a script test: its clip becomes a recording, the saved scripts replay it, and what they did is
 * what the test expects (kept after the incident itself is deleted; edit the expectations on the tests page). */
function ToTest({ d }: { d: Incident }) {
  const nav = useNavigate()
  const [step, setStep] = useState('')
  const go = useMutation({
    mutationFn: async () => {
      setStep(t('把影片存成錄影…'))
      const rec = await api.incidentToRecording(d.id)
      setStep(t('用目前的腳本重播…'))
      const { id } = await api.replayStart({ ...rec, sub_result: 'success' })
      for (let i = 0; i < 300; i++) {
        await new Promise(r => setTimeout(r, 1000))
        const r = await api.replayResult(id)
        if (r.status === 'done') break
        if (r.status === 'failed' || r.status === 'stopped') throw new Error((r.log ?? []).join(' ') || t('重播失敗'))
      }
      setStep(t('存成測試…'))
      return api.testFromReplay(id, t('緊急事件:{rules}({when})', { rules: d.triggers.map(x => x.rule_name).join(t('、')), when: dateTime(d.start) }))
    },
    onSuccess: () => nav('/tests'),
    onSettled: () => setStep(''),
  })
  return (
    <div className="flex flex-wrap items-center gap-3 text-sm">
      <Button disabled={go.isPending} onClick={() => go.mutate()}>{go.isPending ? step : t('做成腳本測試')}</Button>
      <span className="text-xs text-stone-500">{t('這段影片會存成一段錄影,用目前的腳本重播,它做的事就是測試的預期結果;以後改腳本時,同樣的狀況處理壞了就會知道。')}</span>
      <ErrorText error={go.error} />
    </div>
  )
}

function IncidentView({ id, states }: { id: string; states: StateDef[] }) {
  const q = useQuery({ queryKey: ['incident', id], queryFn: () => api.incident(id), refetchInterval: d => (d.state.data?.status === 'open' ? 3000 : false) })
  const [frame, setFrame] = useState<string | null>(null)
  const [all, setAll] = useState(false)
  const d = q.data
  if (!d) return <Card><Empty>{q.isLoading ? t('讀取中…') : t('讀取失敗')}</Empty></Card>
  const shown = frame ?? d.entries.find(e => e.frame)?.frame ?? null
  const entries = d.entries.filter(e => all || e.kind !== 'frame')
  const stateText = (sid: string, v: unknown) => {
    const s = states.find(x => x.id === sid)
    return `${s?.name ?? sid} → ${s?.classes?.find(c => c.value === v)?.name ?? (v == null ? t('不確定') : String(v))}`
  }
  const [st, tone] = INC_STATUS[d.status] ?? [d.status, '']
  return (
    <div className="flex flex-col gap-4 min-w-0">
      <Card title={<span className="flex items-center gap-2"><span className={`text-xs px-1.5 rounded ${tone}`}>{st}</span>{dn(d.device)}:{d.triggers.map(tx => tx.rule_name).join(t('、'))}</span>}
        extra={<span className="text-xs text-stone-500 num">{t('{p1} 起 ·', { p1: dateTime(d.start) })} {d.end ? t('持續 {p1}', { p1: duration(d.end - d.start) }) : t('還在追蹤')}</span>}>
        <div className="flex flex-col gap-3">
          <div className="text-xs text-stone-600 flex flex-col gap-0.5">
            {d.triggers.map(tx => <div key={tx.key}>🚨 {tx.script_name} ·「{tx.rule_name}」:{tx.reason} → {tx.text}{tx.mode !== 'live' && <span className="text-amber-700">{t('(試跑,只記錄)')}</span>}</div>)}
          </div>
          {(d.clip?.length ?? 0) > 1 && <ClipPlayer id={d.id} clip={d.clip!} start={d.start} />}
          {(d.clip?.length ?? 0) > 1 && d.status !== 'open' && edition.name !== 'runtime' && <ToTest d={d} />}
          {shown && (
            <div>
              <img src={api.incidentFrameUrl(d.id, shown)} alt="" className="w-full rounded-md border border-stone-200" />
              <div className="flex gap-1 mt-2 overflow-x-auto pb-1">
                {d.entries.filter(e => e.frame).map(e => (
                  <button key={e.frame} onClick={() => setFrame(e.frame!)} title={t('+{p1} 秒 {text}', { p1: (e.t - d.start).toFixed(1), text: e.text })}
                    className={`shrink-0 rounded border-2 ${shown === e.frame ? 'border-stone-900' : 'border-transparent'}`}>
                    <img src={api.incidentFrameUrl(d.id, e.frame!)} alt="" className="h-12 rounded-sm" loading="lazy" />
                    <div className="text-[10px] text-stone-500 num">+{(e.t - d.start).toFixed(0)}s</div>
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>
      </Card>
      <Card title={t('經過({length})', { length: entries.length })} extra={<label className="text-xs flex items-center gap-1"><input type="checkbox" checked={all} onChange={e => setAll(e.target.checked)} />{t('顯示定時截圖')}</label>}>
        <div className="flex flex-col text-sm">
          {entries.map((e, i) => {
            const [icon, cls] = INC_KIND[e.kind] ?? ['·', '']
            return (
              <div key={i} className={`flex gap-2 py-1 border-b border-stone-100 ${cls} ${e.frame ? 'cursor-pointer hover:bg-stone-50' : ''} ${e.frame && e.frame === shown ? 'bg-amber-50' : ''}`}
                onClick={() => e.frame && setFrame(e.frame)}>
                <span className="num text-xs text-stone-400 w-14 shrink-0 text-right pt-0.5">+{(e.t - d.start).toFixed(1)}s</span>
                <span className="w-5 text-center shrink-0">{icon}</span>
                <span className="min-w-0 flex-1">{e.kind === 'state' ? stateText(e.sid!, e.value) : e.text || (e.kind === 'frame' ? t('畫面') : '')}
                  {e.level === 'warn' && <span className="ml-1 text-[10px] px-1 rounded bg-rose-100 text-rose-700">{t('警告')}</span>}</span>
                {e.frame && <span className="text-xs text-stone-400 shrink-0">📷</span>}
              </div>
            )
          })}
        </div>
      </Card>
    </div>
  )
}

/** A number that is saved when you are done typing (Enter or leaving the box), not on every key: a half-typed or
 * empty box must never be saved (clearing "20" to type "120" used to save 0). */
const CONTROL_DEFAULT: ShadowControl = { max_per_min: 12, max_strikes: 3, manual_pause_s: 60, auto_save: true, auto_save_per_hour: 20,
  live_view: true, start_wait_s: 5, freeze_seconds: 300, blank_seconds: 60 }   // as runtime/shadow.py CONTROL_DEFAULT

function NumField({ value, min, max, className, onSave }: { value: number; min: number; max: number; className: string; onSave: (v: number) => void }) {
  const [text, setText] = useState(String(value))
  useEffect(() => { setText(String(value)) }, [value])
  const done = () => {
    const v = Number(text)
    if (text.trim() === '' || !Number.isFinite(v) || v < min || v > max) { setText(String(value)); return }
    if (v !== value) onSave(Math.round(v))
  }
  return <input type="number" min={min} max={max} className={className} value={text} title={t('{min}~{max},按 Enter 或點別處儲存', { min, max })}
    onChange={e => setText(e.target.value)} onBlur={done} onKeyDown={e => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur() }} />
}
