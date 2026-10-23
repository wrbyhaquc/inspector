import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { PageIntro } from '../components/PageIntro'
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, type LiveDevice } from '../api'
import { Button, Card, Empty, ErrorText, JobStatus, LogView, Meter, Page, Pill, Modal, MoreButton } from '../components/ui'
import { clock, duration } from '../lib/format'
import { usePersistentState } from '../lib/persist'
import { words } from '../lib/project'
import { t } from '../i18n'
import { dn } from '../lib/sources'

const METER_COLOR: Record<string, string> = { rose: 'bg-rose-500', sky: 'bg-sky-500', amber: 'bg-amber-500', emerald: 'bg-emerald-500', violet: 'bg-violet-500' }

function DeviceCard({ d }: { d: LiveDevice }) {
  const extra = Object.values(d.extra ?? {})
  return (
    <div className="bg-white border border-stone-200 rounded-lg p-4 flex flex-col gap-3">
      <div className="flex items-center justify-between gap-2">
        <div className="font-medium text-stone-900" title={d.name}>{dn(d.name)}</div>
        <div className="flex gap-1.5">
          {d.active && <Pill tone="green">{t('操作中')}</Pill>}
          {d.capturing ? <Pill tone="blue">{t('截圖中')}</Pill> : <Pill tone="amber" title={d.detail}>{t('沒截圖')}</Pill>}
        </div>
      </div>
      {extra.some(x => x.meters?.length) && <div className="flex flex-col gap-1.5">
        {extra.flatMap(x => x.meters ?? []).map(m => <Meter key={m.label} label={m.label} value={m.value} max={m.max} color={METER_COLOR[m.color ?? ''] ?? 'bg-stone-500'} />)}
      </div>}
      <div className="grid grid-cols-2 gap-x-3 gap-y-1 text-xs text-stone-600">
        {extra.flatMap(x => x.info ?? []).map(r => <span key={r.label} className={r.wide ? 'col-span-2' : ''}>{r.label}{' '}
          <span className={r.warn ? 'text-amber-700' : 'text-stone-900'}>{r.value ?? '—'}</span></span>)}
        <span className="col-span-2">{t('截圖')} {d.capture == null ? '—' : d.slow
          ? <span className="text-amber-700" title={t('較耗資源的截圖方式,頻率自動降低')}>{t('{capture}(較慢)', { capture: d.capture })}</span>
          : <span className="text-emerald-700">{d.capture}</span>}
          {!!d.slow_shots && <span className="text-stone-400 ml-1">{t('(較慢方式 {slow_shots} 張)', { slow_shots: d.slow_shots })}</span>}
          {d.active && <span className="text-sky-700 ml-2">{t('操作中,每秒截圖')}</span>}</span>
      </div>
      <div className="grid grid-cols-4 gap-2 text-center border-t border-stone-100 pt-3">
        {[[t('樣本'), d.samples], [t('事件'), d.events], [t('觸控'), d.touches], [t('失敗'), d.failed_shots]].map(([k, v]) => (
          <div key={k}><div className="text-lg font-semibold num text-stone-900">{v}</div><div className="text-[11px] text-stone-500">{k}</div></div>
        ))}
      </div>
    </div>
  )
}

export default function Collection() {
  const qc = useQueryClient()
  const col = useQuery({ queryKey: ['collector'], queryFn: api.collector, refetchInterval: 2000 })
  const devs = useQuery({ queryKey: ['devices'], queryFn: api.devices, staleTime: 30_000 })
  // remembered in this browser, so a page reload keeps the last settings
  const [interval, setIntervalSec] = usePersistentState('collect.interval', 3)
  const [minutes, setMinutes] = usePersistentState('collect.minutes', 0)
  const [touch, setTouch] = usePersistentState('collect.touch', true)
  const [labelAfter, setLabelAfter] = usePersistentState('collect.labelAfter', true)
  const [capture, setCapture] = usePersistentState<string>('collect.capture', 'window')
  const drv = useQuery({ queryKey: ['drivers'], queryFn: api.drivers })
  const kind = drv.data ? drv.data.kinds[drv.data.current.driver] : undefined
  const modes = kind?.capture_modes ?? {}
  const mode = capture in modes ? capture : Object.keys(modes)[0] ?? 'default'
  const [only, setOnly] = usePersistentState<string[] | null>('collect.only', null)   // null = all running emulators
  const [now, setNow] = useState(Date.now() / 1000)
  const [settings, setSettings] = useState(false)
  useEffect(() => { const tx = setInterval(() => setNow(Date.now() / 1000), 1000); return () => clearInterval(tx) }, [])

  const live = col.data?.live
  const running = !!live?.running && !live.stale
  // remembered names may include emulators that are not running now; only send the ones that are
  const selected = only === null ? null : only.filter(n => devs.data?.some(d => d.name === n) ?? true)
  const nothingSelected = selected !== null && selected.length === 0
  const start = useMutation({
    // an empty list would mean "all" to the collector, so it is never sent (the button is disabled instead)
    mutationFn: () => api.collectorStart({ interval, minutes, touch, only: selected ?? [], label_after: labelAfter, capture: mode }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['collector'] }),
  })
  const stop = useMutation({ mutationFn: api.collectorStop, onSuccess: () => qc.invalidateQueries({ queryKey: ['collector'] }) })

  return (
    <Page title={t('錄製')} intro={<PageIntro id="collect" what={t('錄下來的畫面用來定義狀態、檢查判斷、訓練模型;錄得越完整,判斷越準。')} start={t('設好分鐘數按「開始錄製」,錄的時候讓畫面出現每一種狀況。')} ch={3} />} desc={<>{t('錄製截圖與觸控,以及專案外掛另外記錄的資料;關掉介面不會中斷錄製。錄的是')} <Link to="/sources" className="underline">{t('來源')}</Link> {t('頁勾選「使用」的{device}。', { device: words.device })}</>}
      actions={running
        ? <Button variant="danger" onClick={() => stop.mutate()} disabled={stop.isPending}>{stop.isPending ? t('停止中…') : t('停止錄製')}</Button>
        : <Button variant="primary" onClick={() => start.mutate()} disabled={start.isPending || nothingSelected}
            title={nothingSelected ? t('請至少勾選一台{device}', { device: words.device }) : undefined}>{start.isPending ? t('啟動中…') : t('開始錄製')}</Button>}>
      <ErrorText error={start.error || stop.error || col.error} />
      {live?.stale && <ErrorText error={t('收集器的狀態超過 10 秒沒有更新,程序可能已經異常結束。')} />}


      {running && live ? (
        <>
          <div className="flex flex-wrap gap-x-6 gap-y-1 text-sm text-stone-600">
            <span>{t('場次')} <span className="text-stone-900 font-medium">{live.session}</span></span>
            <span>{t('開始 {p1}', { p1: clock(live.started) })}</span>
            <span>{t('已錄製')} <span className="num text-stone-900">{duration(now - live.started)}</span></span>
            <span className="text-stone-400 truncate">{live.session_dir}</span>
          </div>
          <div className="grid md:grid-cols-2 xl:grid-cols-4 gap-3">
            {live.devices.filter(d => d.ok || Object.values(d.extra ?? {}).some(x => x.connected)).map(d => <DeviceCard key={d.name} d={d} />)}
          </div>
        </>
      ) : (
        <Card title={t('錄製')} extra={<MoreButton onClick={() => setSettings(true)}>{t('⚙ 錄製設定')}</MoreButton>}>
          <div className="flex flex-wrap items-end gap-5 text-sm">
            <label className="flex flex-col gap-1.5">
              <span className="text-stone-600">{t('自動停止(分鐘)')}</span>
              <input id="minutes" type="number" min={0} step={5} value={minutes} onChange={e => setMinutes(Number(e.target.value))}
                className="border border-stone-300 rounded-md px-2 py-1.5 w-32 num" />
              <span className="text-xs text-stone-500">{t('0 = 直到按下停止')}</span>
            </label>
            <span className="text-xs text-stone-500 pb-6">{t('閒置每 {interval} 秒一張 ·', { interval })} {touch ? t('記錄觸控') : t('不記錄觸控')}{labelAfter ? t(' · 結束後產生標籤') : ''}</span>
          </div>
          <Modal open={settings} title={t('錄製設定')} onClose={() => setSettings(false)} footer={<Button variant="primary" onClick={() => setSettings(false)}>{t('好')}</Button>}>
          <div className="grid md:grid-cols-2 gap-5 text-sm">
            <label className="flex flex-col gap-1.5">
              <span className="text-stone-600">{t('閒置時每幾秒存一張')}</span>
              <input id="interval" type="number" min={1} max={30} step={0.5} value={interval} onChange={e => setIntervalSec(Number(e.target.value))}
                className="border border-stone-300 rounded-md px-2 py-1.5 w-32 num" />
              <span className="text-xs text-stone-500">{t('操作中固定每 1 秒;閒置時可以調大省空間')}</span>
            </label>
            <label className="flex items-start gap-2 pt-6">
              <input id="touch" type="checkbox" checked={touch} onChange={e => setTouch(e.target.checked)} className="mt-1" />
              <span><span className="text-stone-700">{t('記錄觸控')}</span><br /><span className="text-xs text-stone-500">{t('模仿學習需要;不會記錄程式送出的點擊')}{kind && !kind.caps.includes('touch_watch') ? t('(目前的裝置來源不支援)') : ''}</span></span>
            </label>
            {Object.keys(modes).length > 0 && <label className="flex flex-col gap-1">
              <span className="text-stone-700">{t('截圖方式')}</span>
              <select id="capture" value={mode} onChange={e => setCapture(e.target.value)} className="border border-stone-300 rounded-md px-2 py-1.5">
                {Object.entries(modes).map(([k, tx]) => <option key={k} value={k}>{tx}</option>)}
              </select>
            </label>}
            <label className="flex items-start gap-2 pt-6">
              <input id="label-after" type="checkbox" checked={labelAfter} onChange={e => setLabelAfter(e.target.checked)} className="mt-1" />
              <span><span className="text-stone-700">{t('結束後自動產生標籤')}</span><br /><span className="text-xs text-stone-500">{t('按停止或時間到時,接著執行「產生標籤」')}</span></span>
            </label>
          </div>
          </Modal>
          <div className="mt-5">
            <div className="text-sm text-stone-600 mb-2 flex items-center gap-3">
              {t('要錄製的{device}', { device: words.device })}
              <button className="text-xs text-stone-500 underline" onClick={() => setOnly(null)}>{t('全部')}</button>
              {devs.isFetching && <span className="text-xs text-stone-400">{t('偵測中…')}</span>}
            </div>
            {devs.data?.length ? (
              <div className="flex flex-wrap gap-2">
                {devs.data.map(d => {
                  const on = only === null || only.includes(d.name)
                  return (
                    <label key={d.name} className={`flex items-center gap-2 border rounded-md px-3 py-2 text-sm cursor-pointer ${on ? 'border-stone-800 bg-stone-50' : 'border-stone-200 text-stone-400'}`}>
                      <input type="checkbox" checked={on} onChange={() => {
                        const cur = only ?? devs.data!.map(x => x.name)
                        setOnly(on ? cur.filter(n => n !== d.name) : [...cur, d.name])
                      }} />
                      {dn(d.name)}
                      {!d.ok && <Pill tone="amber" title={d.detail}>{t('無法使用')}</Pill>}
                    </label>
                  )
                })}
              </div>
            ) : <Empty>{devs.isLoading ? t('偵測{device}中…', { device: words.device }) : t('沒有偵測到執行中的{device}', { device: words.device })}</Empty>}
            {nothingSelected && devs.data?.length ? <p className="text-xs text-rose-600 mt-2">{t('請至少勾選一台{device}才能開始錄製。', { device: words.device })}</p> : null}
            <p className="text-xs text-stone-500 mt-2">{t('這頁的設定會記在這個瀏覽器裡,重新整理或下次打開都會保留。')}</p>
          </div>
        </Card>
      )}

      <Card title={t('收集器輸出')} extra={col.data?.job && <span className="flex items-center gap-2 text-xs text-stone-500">{clock(col.data.job.started)}<JobStatus status={col.data.job.status} /></span>}>
        {col.data?.job ? <LogView lines={col.data.job.log} /> : <Empty>{t('這次啟動介面後還沒有從介面啟動過收集器')}</Empty>}
      </Card>
    </Page>
  )
}

