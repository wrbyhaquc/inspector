import { t } from '../i18n'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api, type CleanRecord, type KeepKind, type LocationCheck, type StorageSettings } from '../api'
import { Button, Card, ErrorText, Page } from '../components/ui'
import { bytes, dateTime } from '../lib/format'
import { StorageCard } from './Overview'
import { edition } from '../lib/project'

type Tab = 'overview' | 'keep' | 'protect' | 'location' | 'record'

/** This computer's disk: what the data takes, and where it is kept (the work folder, which can be moved). */
export default function Storage() {
  const tabs: [Tab, string][] = [['overview', t('總覽')], ['keep', t('保留規則')], ['protect', t('空間保護')], ['location', t('資料位置')],
    ...(edition.name === 'runtime' ? [] : [['record', t('錄製設定')] as [Tab, string]])]     // a runtime does not record
  const [tab, setTab] = useState<Tab>(() => tabs.find(([k]) => `#${k}` === location.hash)?.[0] ?? 'overview')
  return (
    <Page title={t('儲存空間')} desc={t('這台電腦的資料佔多少空間、放在哪裡。錄影、模型、標籤與答案、執行紀錄都在「工作資料」資料夾,可以整個搬到另一個位置或另一顆磁碟。')}>
      <div className="flex border-b border-stone-200 gap-1">
        {tabs.map(([k, tx]) => <button key={k} onClick={() => { setTab(k); history.replaceState(null, '', `#${k}`) }}
          className={`px-4 py-2 text-sm -mb-px border-b-2 ${tab === k ? 'border-stone-900 font-medium' : 'border-transparent text-stone-500'}`}>{tx}</button>)}
      </div>
      {tab === 'overview' ? <><StorageCard /><HistoryCard /></> : tab === 'keep' ? <><KeepCard />{edition.name !== 'runtime' && <ModelsCard />}</> : tab === 'protect' ? <ProtectCard />
        : tab === 'location' ? <LocationCard /> : <RecordCard />}
    </Page>
  )
}

const PHASE: Record<string, string> = { copy: t('複製中'), check: t('核對中'), done: t('搬好了'), failed: t('沒有搬成'), deleting: t('刪除舊位置中'), deleted: t('舊位置已刪除') }

/** Moving the work folder: check a place, copy and check there, switch after a restart, delete the old copy later. */
function LocationCard() {
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['storageLocation'], queryFn: api.storageLocation,
    refetchInterval: x => (['copy', 'check', 'deleting'].includes(x.state.data?.move.phase ?? '') || x.state.data?.job?.status === 'running' ? 1000 : false) })
  const [to, setTo] = useState('')
  const [checked, setChecked] = useState<LocationCheck | null>(null)
  const check = useMutation({ mutationFn: () => api.storageLocationCheck(to), onSuccess: setChecked })
  const move = useMutation({ mutationFn: () => api.storageLocationMove(to), onSuccess: () => { setChecked(null); qc.invalidateQueries({ queryKey: ['storageLocation'] }) } })
  const del = useMutation({ mutationFn: api.storageLocationDeleteOld, onSuccess: () => qc.invalidateQueries({ queryKey: ['storageLocation'] }) })
  const [restarting, setRestarting] = useState(false)
  const restart = useMutation({
    mutationFn: async () => {
      setRestarting(true)
      await api.restart()
      await new Promise(r => setTimeout(r, 4000))
      for (let i = 0; i < 90; i++) {                          // until the new one answers
        try { await api.storageLocation(); window.location.reload(); return } catch { await new Promise(r => setTimeout(r, 1000)) }
      }
      throw new Error(t('Inspector 沒有回來;請手動啟動它'))
    },
    onError: () => setRestarting(false),
  })
  const d = q.data
  if (!d) return <ErrorText error={q.error} />
  const m = d.move
  const busy = ['copy', 'check', 'deleting'].includes(m.phase ?? '') && d.job?.status === 'running'
  const input = 'border border-stone-300 rounded-md px-2 py-1 text-sm'
  return (
    <div className="flex flex-col gap-4">
      <Card title={t('工作資料的位置')}>
        <div className="flex flex-col gap-2 text-sm">
          <div><span className="text-stone-500">{t('現在使用:')}</span><b className="font-mono">{d.running_from}</b></div>
          {d.restart_needed && <div><span className="text-stone-500">{t('重新啟動後:')}</span><b className="font-mono">{d.current}</b></div>}
          <div className="text-xs text-stone-500">{t('這台每個方案包的錄影、模型、標籤與答案、執行紀錄都在這裡(每個方案包一個子資料夾)。設計和這台的設定不在這裡,不會搬。')}</div>
          {!d.movable && <div className="text-amber-800">{t('這台的資料位置由環境變數 INSPECTOR_WORK 或舊的單一專案資料夾決定,不能在這裡搬。')}</div>}
        </div>
      </Card>

      {m.phase && (
        <Card title={t('搬移')} extra={<span className="text-xs text-stone-500">{PHASE[m.phase] ?? m.phase}</span>}>
          <div className="flex flex-col gap-2 text-sm">
            <div className="font-mono text-xs">{m.from} → {m.to}</div>
            {(m.phase === 'copy' || m.phase === 'check') && <>
              <div className="h-2 rounded-full bg-stone-200 overflow-hidden"><div className="h-full bg-sky-600" style={{ width: `${(100 * (m.bytes_done ?? 0)) / Math.max(1, m.bytes ?? 1)}%` }} /></div>
              <div className="text-xs text-stone-600 num">{t('{a} / {b} 個檔案 · {c} / {d}', { a: m.files_done ?? 0, b: m.files ?? 0, c: bytes(m.bytes_done), d: bytes(m.bytes) })}
                {m.phase === 'check' && ' · ' + t('核對每個檔案…')}</div>
              {!busy && <div className="text-amber-800">{t('搬移中斷了(Inspector 重開或關掉)。再按一次「開始搬移」會從中斷的地方接著做。')}</div>}
            </>}
            {m.phase === 'failed' && <div className="text-rose-700">{m.error}{' '}{t('現在的位置沒有動過,資料都還在。')}</div>}
            {m.phase === 'done' && d.restart_needed && <div className="flex flex-wrap items-center gap-3">
              <span>{t('{n} 個檔案都核對過。重新啟動 Inspector 後改用新位置(腳本執行會照上次的設定再啟動;停下來 / 暫停的仍然停著)。', { n: m.files ?? 0 })}</span>
              <Button variant="primary" disabled={restarting} onClick={() => restart.mutate()}>{restarting ? t('重新啟動中…') : t('重新啟動 Inspector')}</Button>
            </div>}
            {m.phase === 'done' && !d.restart_needed && d.old_exists && <div className="flex flex-wrap items-center gap-3">
              <span>{t('已經改用新位置。舊位置的資料還在,確認新位置一切正常(錄影、模型、紀錄都看得到)後再刪。')}</span>
              <Button variant="danger" disabled={del.isPending || busy} onClick={() => { if (confirm(t('刪除舊位置 {p} 的所有資料?這無法復原。', { p: m.from ?? '' }))) del.mutate() }}>
                {t('刪除舊位置的資料')}</Button>
            </div>}
            {m.phase === 'deleted' && <div className="text-stone-600">{t('舊位置已刪除,搬移完成。')}</div>}
            {m.error && m.phase !== 'failed' && <div className="text-amber-800">{m.error}</div>}
            <ErrorText error={restart.error || del.error} />
          </div>
        </Card>
      )}

      {d.movable && !busy && !(m.phase === 'done' && d.restart_needed) && (
        <Card title={t('搬到新位置')}>
          <div className="flex flex-col gap-3 text-sm">
            <div className="flex flex-wrap items-center gap-2">
              <input className={`${input} w-96 font-mono`} placeholder={t('例如 E:\\InspectorWork')} value={to} onChange={e => { setTo(e.target.value); setChecked(null) }} />
              <Button disabled={!to.trim() || check.isPending} onClick={() => check.mutate()}>{check.isPending ? t('檢查中…') : t('檢查')}</Button>
            </div>
            {checked && <div className={`rounded-md border px-3 py-2 ${checked.ok ? 'border-emerald-200 bg-emerald-50' : 'border-rose-200 bg-rose-50'}`}>
              {checked.ok ? <div className="flex flex-col gap-2">
                <div>{t('可以搬:{n} 個檔案、{size};新位置的磁碟剩 {free}。', { n: checked.files, size: bytes(checked.bytes), free: bytes(checked.free) })}</div>
                <div className="text-xs text-stone-600">{t('開始後會先停下錄製和腳本執行,在背景複製、逐一核對,沒問題才改用新位置,再按「重新啟動 Inspector」。現在的位置不會動,確認後再刪。')}</div>
                <div><Button variant="primary" disabled={move.isPending} onClick={() => move.mutate()}>{t('開始搬移')}</Button></div>
              </div> : <ul className="list-disc pl-5 text-rose-800">{checked.problems.map(p => <li key={p}>{p}</li>)}</ul>}
            </div>}
            <ErrorText error={check.error || move.error} />
          </div>
        </Card>
      )}
    </div>
  )
}

/** How new recordings keep their frames: PNG exactly, or JPEG about four times smaller. */
function RecordCard() {
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['storageSettings'], queryFn: api.storageSettings })
  const save = useMutation({ mutationFn: api.storageSettingsSave, onSuccess: d => qc.setQueryData(['storageSettings'], d) })
  const s = q.data
  if (!s) return <ErrorText error={q.error} />
  const opt = (v: 'png' | 'jpg', title: string, help: string) => (
    <label className={`flex gap-3 items-start rounded-lg border px-3 py-2 cursor-pointer ${s.record_format === v ? 'border-stone-800 bg-stone-50' : 'border-stone-200'}`}>
      <input type="radio" className="mt-1" checked={s.record_format === v} onChange={() => save.mutate({ record_format: v })} />
      <span className="flex flex-col gap-0.5"><b>{title}</b><span className="text-xs text-stone-600">{help}</span></span>
    </label>)
  return (
    <Card title={t('錄影畫面的存法')} extra={<span className="text-xs text-stone-500">{t('只影響之後的錄影;已經錄好的不變')}</span>}>
      <div className="flex flex-col gap-3 text-sm max-w-3xl">
        {opt('png', t('PNG(原樣,預設)'), t('每張畫面原封不動,學習和畫面規則看到的跟現場一樣。檔案大:1280×720 的畫面每張約 0.2~1.4 MB。'))}
        {opt('jpg', t('JPEG(小約 4 倍)'), t('省 75~88% 的空間。實測(畫質 90):畫面規則的答案幾乎都一樣,少數畫面從有答案變成「判斷不出」(魚塭 2.5%、模擬器 1%),從沒有變成相反的答案;數值狀態平均差 0.1~0.2%。模型和參考圖的影響沒有實測過。'))}
        {s.record_format === 'jpg' && <label className="flex items-center gap-2">{t('畫質')}
          <select className="border border-stone-300 rounded-md px-2 py-1 text-sm" value={s.jpeg_quality} onChange={e => save.mutate({ jpeg_quality: Number(e.target.value) })}>
            {[95, 90, 80].map(v => <option key={v} value={v}>{v === 90 ? t('{v}(建議)', { v }) : v}</option>)}</select>
          <span className="text-xs text-stone-500">{t('95 省約 70%、90 省約 75~80%、80 省約 80~88%')}</span></label>}
        <ErrorText error={save.error} />
      </div>
    </Card>
  )
}

function useSettings() {
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['storageSettings'], queryFn: api.storageSettings })
  const save = useMutation({ mutationFn: (b: Partial<StorageSettings>) => api.storageSettingsSave(b),
    onSuccess: d => { qc.setQueryData(['storageSettings'], d); qc.invalidateQueries({ queryKey: ['storage'] }) } })
  return { s: q.data, error: q.error || save.error, save }
}

const KINDS: [KeepKind, string, string][] = [
  ['actions', t('動作的畫面'), t('每一次真的點擊、輸入時的畫面')],
  ['incidents', t('緊急事件'), t('事件的經過、畫面和影片(還在進行中的不會刪)')],
  ['schedules', t('排程紀錄'), t('每次排程執行的經過和畫面')],
  ['logs', t('每天的紀錄'), t('執行紀錄、模型把握度、背景工作的輸出')],
]

/** How long each kind of the run's records is kept; what cleaning now would delete, then cleaning. */
function KeepCard() {
  const qc = useQueryClient()
  const { s, error, save } = useSettings()
  const preview = useQuery({ queryKey: ['cleanPreview', s?.keep], queryFn: api.storageCleanPreview, enabled: !!s })
  const clean = useMutation({ mutationFn: api.storageClean, onSuccess: () => { qc.invalidateQueries({ queryKey: ['cleanPreview'] }); qc.invalidateQueries({ queryKey: ['storage'] }); qc.invalidateQueries({ queryKey: ['storageHistory'] }) } })
  if (!s) return <ErrorText error={error} />
  const p = preview.data
  return (
    <Card title={t('執行紀錄保留幾天')} extra={<span className="text-xs text-stone-500">{t('腳本執行每 6 小時清一次;填 0 = 全部保留')}</span>}>
      <div className="flex flex-col gap-3 text-sm max-w-3xl">
        {KINDS.map(([k, name, help]) => (
          <div key={k} className="flex flex-wrap items-center gap-3">
            <span className="w-28 font-medium">{name}</span>
            <input type="number" min={0} max={3650} className="w-20 border border-stone-300 rounded-md px-2 py-1 text-sm num" defaultValue={s.keep[k]} key={s.keep[k]}
              onBlur={e => { const v = Number(e.target.value); if (v !== s.keep[k] && v >= 0) save.mutate({ keep: { ...s.keep, [k]: v } }) }} />
            <span className="text-stone-600">{s.keep[k] ? t('天') : t('全部保留')}</span>
            <span className="text-xs text-stone-500">{help}</span>
            {p?.kinds[k] && <span className="text-xs text-amber-800 num">{t('現在清會刪 {n} 個檔案、{size}', { n: p.kinds[k]!.files, size: bytes(p.kinds[k]!.bytes) })}</span>}
          </div>
        ))}
        <div className="text-xs text-stone-500">{t('錄影、答案、標籤、模型不在這裡,不會被刪。')}</div>
        <div className="flex flex-wrap items-center gap-3 border-t border-stone-100 pt-3">
          <Button disabled={!p?.files || clean.isPending} onClick={() => {
            if (p && confirm(t('刪掉過期的執行紀錄:{n} 個檔案、{size}?', { n: p.files, size: bytes(p.bytes) }))) clean.mutate()
          }}>{clean.isPending ? t('清理中…') : t('現在清理')}</Button>
          <span className="text-xs text-stone-600">{p ? (p.files ? t('會刪 {n} 個檔案、{size}', { n: p.files, size: bytes(p.bytes) }) : t('現在沒有過期的紀錄')) : ''}</span>
          {clean.data && <span className="text-xs text-emerald-700">{t('清掉 {n} 個檔案、{size}', { n: clean.data.files, size: bytes(clean.data.bytes) })}</span>}
        </div>
        <ErrorText error={error || clean.error} />
      </div>
    </Card>
  )
}

/** The free space to keep, and what happens to recording when the disk runs short. */
function ProtectCard() {
  const { s, error, save } = useSettings()
  if (!s) return <ErrorText error={error} />
  const opt = (v: 'stop' | 'cycle', title: string, help: string) => (
    <label className={`flex gap-3 items-start rounded-lg border px-3 py-2 cursor-pointer ${s.when_full === v ? 'border-stone-800 bg-stone-50' : 'border-stone-200'}`}>
      <input type="radio" className="mt-1" checked={s.when_full === v} onChange={() => save.mutate({ when_full: v })} />
      <span className="flex flex-col gap-0.5"><b>{title}</b><span className="text-xs text-stone-600">{help}</span></span>
    </label>)
  return (
    <Card title={t('空間保護')}>
      <div className="flex flex-col gap-3 text-sm max-w-3xl">
        <label className="flex flex-wrap items-center gap-2">{t('工作資料的磁碟至少留')}
          <input type="number" min={0} step={1} className="w-24 border border-stone-300 rounded-md px-2 py-1 text-sm num" defaultValue={s.min_free_gb} key={s.min_free_gb}
            onBlur={e => { const v = Number(e.target.value); if (v !== s.min_free_gb && v >= 0) save.mutate({ min_free_gb: v }) }} />
          {t('GB 可用空間')}<span className="text-xs text-stone-500">{t('填 0 = 不檢查。不夠時會通知(Discord / Telegram),首頁也會提醒。')}</span></label>
        <div className="text-stone-600">{t('錄製時空間不夠:')}</div>
        {opt('stop', t('停止錄製(預設)'), t('錄製停下來,已經錄的都留著;騰出空間後再開始錄。'))}
        {opt('cycle', t('循環錄製'), t('刪掉最舊的錄影騰出空間,繼續錄。有答案、或被腳本測試用到的錄影一定留著;正在錄的那段也不會刪。能刪的都刪了還不夠,就停止錄製。'))}
        <div className="text-xs text-stone-500">{t('腳本執行不受影響,空間不夠也會繼續;執行紀錄照「保留規則」清理。')}</div>
        <ErrorText error={error} />
      </div>
    </Card>
  )
}

const BY: Record<CleanRecord['by'], string> = { runner: t('自動(保留天數)'), user: t('手動'), room: t('空間不夠') }

/** Every cleaning so far: when, why, what and how much. */
function HistoryCard() {
  const q = useQuery({ queryKey: ['storageHistory'], queryFn: api.storageHistory })
  const items = q.data?.items ?? []
  return (
    <Card title={t('清理紀錄')}>
      {items.length === 0 ? <div className="text-sm text-stone-500">{t('還沒有清理過。')}</div> : (
        <div className="flex flex-col divide-y divide-stone-100 text-sm">
          {items.map((r, i) => (
            <div key={i} className="py-1.5 flex flex-wrap gap-x-3 gap-y-0.5">
              <span className="text-stone-500 num">{dateTime(r.t)}</span>
              <span className="text-xs px-1.5 rounded bg-stone-100 self-center">{BY[r.by] ?? r.by}</span>
              {r.what === 'stopped' ? <span className="text-amber-800">{r.why}</span> : <span>
                {r.what === 'recordings' ? t('刪掉 {n} 段錄影', { n: r.sessions?.length ?? 0 }) : r.what === 'models' ? t('刪掉 {n} 次訓練', { n: r.runs?.length ?? 0 }) : t('執行紀錄')}
                {' · '}{t('{n} 個檔案、{size}', { n: r.files, size: bytes(r.bytes) })}
                {(r.sessions ?? r.runs)?.length ? <span className="text-xs text-stone-500 font-mono">{' '}{(r.sessions ?? r.runs)!.join(', ')}</span> : null}</span>}
            </div>
          ))}
        </div>
      )}
      <ErrorText error={q.error} />
    </Card>
  )
}

/** How many training runs are kept (the newest ones; the one in use and the newest finished one always stay). */
function ModelsCard() {
  const qc = useQueryClient()
  const { s, error, save } = useSettings()
  const preview = useQuery({ queryKey: ['modelsPreview', s?.keep_models], queryFn: api.storageModelsPreview, enabled: !!s })
  const clean = useMutation({ mutationFn: api.storageModelsClean, onSuccess: () => { qc.invalidateQueries({ queryKey: ['modelsPreview'] }); qc.invalidateQueries({ queryKey: ['storage'] }); qc.invalidateQueries({ queryKey: ['storageHistory'] }) } })
  if (!s) return null
  const p = preview.data
  return (
    <Card title={t('訓練保留幾次')} extra={<span className="text-xs text-stone-500">{t('每次訓練完成後清一次;填 0 = 全部保留(預設)')}</span>}>
      <div className="flex flex-col gap-3 text-sm max-w-3xl">
        <label className="flex flex-wrap items-center gap-2">{t('保留最近')}
          <input type="number" min={0} max={1000} className="w-20 border border-stone-300 rounded-md px-2 py-1 text-sm num" defaultValue={s.keep_models} key={s.keep_models}
            onBlur={e => { const v = Number(e.target.value); if (v !== s.keep_models && v >= 0) save.mutate({ keep_models: v }) }} />
          {t('次訓練')}<span className="text-xs text-stone-500">{t('正在用的模型、最新一次完成的訓練、還在訓練的那次一定保留;方案包附的模型不在這裡。')}</span></label>
        <div className="flex flex-wrap items-center gap-3">
          <Button disabled={!p?.runs.length || clean.isPending} onClick={() => {
            if (p && confirm(t('刪掉較舊的 {n} 次訓練({size})?這無法復原。', { n: p.runs.length, size: bytes(p.bytes) }))) clean.mutate()
          }}>{clean.isPending ? t('清理中…') : t('現在清理')}</Button>
          <span className="text-xs text-stone-600">{!s.keep_models ? t('全部保留') : p?.runs.length ? t('會刪 {n} 次訓練、{size}:{runs}', { n: p.runs.length, size: bytes(p.bytes), runs: p.runs.join(', ') }) : t('沒有要刪的訓練')}</span>
        </div>
        <ErrorText error={error || clean.error} />
      </div>
    </Card>
  )
}
