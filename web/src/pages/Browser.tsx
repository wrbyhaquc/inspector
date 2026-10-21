import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api, imageUrl, type SampleItem, type StateDef } from '../api'
import { FrameView, Zoom } from '../components/FrameView'
import { Button, Card, Empty, ErrorText, Page, Pill, StatePill } from '../components/ui'
import { bytes, clock, flagText, sessionTime } from '../lib/format'
import { mainRoi, reviewStates, stateColor, useSchema } from '../lib/schema'
import { t } from '../i18n'

const PAGE = 60

function Select({ id, value, onChange, options }: { id: string; value: string; onChange: (v: string) => void; options: [string, string][] }) {
  return (
    <select id={id} value={value} onChange={e => onChange(e.target.value)} className="border border-stone-300 rounded-md px-2 py-1.5 text-sm bg-white">
      {options.map(([v, tx]) => <option key={v} value={v}>{tx}</option>)}
    </select>
  )
}

export default function Browser() {
  const sessions = useQuery({ queryKey: ['sessions'], queryFn: api.sessions })
  // ?session=&device=&open= opens one frame directly (links from other pages, search results)
  const [params, setParams] = useSearchParams()
  const [session, setSession] = useState<string>(params.get('session') ?? '')
  const [device, setDevice] = useState<string>(params.get('device') ?? '')
  const [fState, setFState] = useState(''), [fValue, setFValue] = useState(''), [trigger, setTrigger] = useState(''), [reviewed, setReviewed] = useState('')
  const classStates = (useSchema().data?.schema.states ?? []).filter(s => s.type === 'class')
  const fs = classStates.find(s => s.id === fState)
  const [offset, setOffset] = useState(0)
  const [open, setOpen] = useState<string | null>(params.get('open'))
  const [query, setQuery] = useState('')
  const found = useMutation({ mutationFn: (q: string) => api.find(q) })
  const jump = (r: { session: string; device: string; id: string }) => {
    setSession(r.session); setDevice(r.device); setOpen(r.id)
    setParams({ session: r.session, device: r.device, open: r.id })
    found.reset(); setQuery('')
  }
  const closeModal = () => { setOpen(null); if (params.get('open')) setParams({}) }

  const cur = sessions.data?.find(s => s.id === session) ?? sessions.data?.[0]
  const devs = (cur?.devices ?? []).filter(d => d.samples > 0)
  const dev = devs.find(d => d.name === device)?.name ?? devs[0]?.name ?? ''
  useEffect(() => setOffset(0), [cur?.id, dev, fState, fValue, trigger, reviewed])

  const samples = useQuery({
    queryKey: ['samples', cur?.id, dev, offset, fState, fValue, trigger, reviewed],
    queryFn: () => api.samples({ session: cur!.id, device: dev, offset, limit: PAGE, state: fState, value: fValue, trigger, reviewed }),
    enabled: !!cur && !!dev, placeholderData: keepPreviousData,
  })
  const total = samples.data?.total ?? 0

  return (
    <Page title={t('畫面瀏覽')} desc={t('逐張檢查收集到的畫面、當下另外記錄的資料與自動產生的標籤。點一張圖可以看細節、加入測試集。')}
      actions={
        <form className="flex gap-2 relative" onSubmit={e => { e.preventDefault(); if (query.trim()) found.mutate(query.trim()) }}>
          <input id="find" value={query} onChange={e => setQuery(e.target.value)} placeholder={t('輸入畫面編號,例如 1760000000000')}
            className="border border-stone-300 rounded-md px-3 py-1.5 text-sm w-72 num" />
          <Button type="submit" disabled={!query.trim() || found.isPending}>{t('搜尋')}</Button>
          {found.data && (
            <div className="absolute top-full right-0 mt-1 w-96 bg-white border border-stone-200 rounded-md shadow-lg z-20 max-h-80 overflow-auto">
              {found.data.length ? found.data.map(r => (
                <button key={`${r.session}/${r.device}/${r.id}`} type="button" onClick={() => jump(r)}
                  className="w-full text-left px-3 py-2 text-sm hover:bg-stone-50 border-b border-stone-50">
                  <span className="num font-medium">{r.id}</span>
                  <span className="text-stone-500"> · {r.device} · {sessionTime(r.session)} {clock(r.t)}</span>
                </button>
              )) : <div className="px-3 py-2 text-sm text-stone-500">{t('找不到符合的畫面')}</div>}
            </div>
          )}
        </form>}>
      <ErrorText error={sessions.error || samples.error || found.error} />
      <div className="flex gap-4 items-start">
        <div className="w-56 shrink-0 bg-white border border-stone-200 rounded-lg overflow-hidden">
          <div className="px-3 py-2 text-xs text-stone-500 border-b border-stone-100">{t('場次')}</div>
          <div className="max-h-[70vh] overflow-auto">
            {sessions.data?.map(s => (
              <button key={s.id} onClick={() => { setSession(s.id); setDevice('') }}
                className={`w-full text-left px-3 py-2 text-sm border-b border-stone-50 hover:bg-stone-50 ${s.id === cur?.id ? 'bg-stone-100 font-medium' : ''}`}>
                <div>{sessionTime(s.id)}</div>
                <div className="text-xs text-stone-500 num">{s.minutes != null ? t('{minutes} 分', { minutes: s.minutes }) : t('錄製中')} {t('· {samples} 張 · {p2}', { samples: s.samples, p2: bytes(s.bytes) })}</div>
              </button>
            ))}
          </div>
        </div>

        <div className="flex-1 min-w-0 flex flex-col gap-3">
          <div className="flex flex-wrap items-center gap-2">
            <div className="flex rounded-md border border-stone-300 overflow-hidden">
              {devs.map(d => (
                <button key={d.name} onClick={() => setDevice(d.name)}
                  className={`px-3 py-1.5 text-sm ${d.name === dev ? 'bg-stone-900 text-white' : 'bg-white hover:bg-stone-50'}`}>
                  {d.name} <span className="num opacity-60">{d.samples}</span>
                </button>
              ))}
            </div>
            <Select id="f-state" value={fState} onChange={v => { setFState(v); setFValue('') }} options={[['', t('狀態:全部')], ...classStates.map(s => [s.id, s.name] as [string, string])]} />
            {fs && <Select id="f-value" value={fValue} onChange={setFValue} options={[['', t('{name}:全部', { name: fs.name })], ...(fs.classes ?? []).map(c => [String(c.value), c.name] as [string, string]), ['None', t('無法判斷')]]} />}
            <Select id="f-trigger" value={trigger} onChange={setTrigger} options={[['', t('取樣原因:全部')], ['base', t('例行')], ['active', t('操作中')], ['pre_touch', t('觸控前')], ['event:', t('事件')]]} />
            <Select id="f-reviewed" value={reviewed} onChange={setReviewed} options={[['', t('確認:全部')], ['1', t('已確認')], ['0', t('未確認')]]} />
            <span className="text-sm text-stone-500 num ml-auto">{t('{total} 張', { total })}</span>
          </div>

          {samples.data?.items.length ? (
            <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-5 gap-2">
              {samples.data.items.map(s => <Thumb key={s.id} s={s} fs={fs} classStates={classStates} onClick={() => setOpen(s.id)} />)}
            </div>
          ) : <Empty>{samples.isLoading ? t('讀取中…') : t('沒有符合條件的畫面')}</Empty>}

          {total > PAGE && (
            <div className="flex items-center justify-center gap-3 text-sm">
              <Button onClick={() => setOffset(Math.max(0, offset - PAGE))} disabled={offset === 0}>{t('上一頁')}</Button>
              <span className="num text-stone-600">{offset + 1}–{Math.min(total, offset + PAGE)} / {total}</span>
              <Button onClick={() => setOffset(offset + PAGE)} disabled={offset + PAGE >= total}>{t('下一頁')}</Button>
            </div>
          )}
        </div>
      </div>
      {open && cur && <SampleModal session={cur.id} device={dev} id={open} onNavigate={setOpen} onClose={closeModal} />}
    </Page>
  )
}

function Thumb({ s, fs, classStates, onClick }: { s: SampleItem; fs?: StateDef; classStates: StateDef[]; onClick: () => void }) {
  return (
    <button onClick={onClick} className="group bg-white border border-stone-200 rounded-md overflow-hidden text-left hover:border-stone-500 focus:outline-none focus-visible:ring-2 focus-visible:ring-amber-400">
      <div className="aspect-video bg-stone-200 relative">
        <img src={imageUrl(s.frame, 320)} alt="" loading="lazy" className="w-full h-full object-cover" />
        {s.reviewed && <span className="absolute top-1 right-1"><Pill tone="violet">{t('已確認')}</Pill></span>}
      </div>
      <div className="px-2 py-1.5 flex flex-wrap items-center gap-1">
        {(fs ? [fs] : classStates.slice(0, 2)).map(st => <StatePill key={st.id} state={st} v={s.label?.values?.[st.id]} />)}
        <span className="text-[11px] text-stone-500 num ml-auto">{clock(s.t)}</span>
      </div>
    </button>
  )
}

function SampleModal({ session, device, id, onNavigate, onClose }: { session: string; device: string; id: string; onNavigate: (id: string) => void; onClose: () => void }) {
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['sample', session, device, id], queryFn: () => api.sample(session, device, id) })
  const d = q.data
  const states = useSchema().data?.schema.states ?? []
  const stateNames = Object.fromEntries(states.map(x => [x.id, x.name]))
  const questions = reviewStates(states)
  const [overlay, setOverlay] = useState(true)

  useEffect(() => {
    const k = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement).tagName === 'INPUT') return
      if (e.key === 'Escape') onClose()
      if (e.key === 'ArrowLeft' && d?.prev) onNavigate(d.prev)
      if (e.key === 'ArrowRight' && d?.next) onNavigate(d.next)
    }
    window.addEventListener('keydown', k)
    return () => window.removeEventListener('keydown', k)
  }, [d, onClose, onNavigate])

  const decide = useMutation({
    mutationFn: (patch: Record<string, number | string>) => api.reviewDecide({
      frame: d!.frame, session, device, id, answers: { ...(d!.review?.answers ?? {}), ...patch },
    }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['sample', session, device, id] }); qc.invalidateQueries({ queryKey: ['samples'] }) },
  })

  const lab = d?.label
  return (
    <div className="fixed inset-0 z-50 bg-black/60 flex items-center justify-center p-4" onClick={onClose}>
      <div className="bg-stone-50 rounded-lg w-full max-w-[1300px] max-h-[95vh] overflow-auto" onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between px-4 py-3 border-b border-stone-200 bg-white sticky top-0 z-10">
          <div className="text-sm">
            <span className="font-medium">{device}</span> · <span className="num">{d ? clock(d.sample.t_req) : ''}</span>
            <span className="text-stone-500"> {t('· {trigger} · 第 {p2} / {count} 張 · 編號', { trigger: d?.sample.trigger, p2: d ? d.index + 1 : '–', count: d?.count })} </span>
            <span className="num text-stone-700 select-all">{id}</span>
          </div>
          <div className="flex items-center gap-2">
            <label className="text-xs text-stone-600 flex items-center gap-1.5 mr-2"><input type="checkbox" checked={overlay} onChange={e => setOverlay(e.target.checked)} />{t('顯示判斷區域')}</label>
            <Button onClick={() => d?.prev && onNavigate(d.prev)} disabled={!d?.prev}>{t('← 上一張')}</Button>
            <Button onClick={() => d?.next && onNavigate(d.next)} disabled={!d?.next}>{t('下一張 →')}</Button>
            <Button variant="ghost" onClick={onClose}>{t('關閉')}</Button>
          </div>
        </div>
        <ErrorText error={q.error} />
        {d && (
          <div className="grid lg:grid-cols-[1fr_340px] gap-4 p-4">
            <div className="flex flex-col gap-3">
              <FrameView frame={d.frame} overlays={overlay ? states.map((s, i) => ({ box: mainRoi(s).box, color: stateColor(i), label: s.name })) : []} />
              <div className="flex gap-4 flex-wrap items-end">
                {states.map(s => <Zoom key={s.id} frame={d.frame} box={mainRoi(s).box} scale={s.review?.scale ?? 1.6} maxWidth={420} label={s.name} />)}
              </div>
            </div>
            <div className="flex flex-col gap-3 text-sm">
              <Card title={t('自動標籤')}>
                {lab ? (
                  <div className="flex flex-col gap-2">
                    <div className="flex flex-wrap gap-1.5 items-center">
                      {states.filter(x => x.type === 'class' || x.type === 'ratio').map(x => <StatePill key={x.id} state={x} v={lab.values?.[x.id]} />)}
                      {states.filter(x => x.type === 'gallery').map(x => <span key={x.id} className="text-xs text-stone-700">{x.name}:{String(lab.values?.[x.id] ?? t('未命名'))}</span>)}
                    </div>
                    {lab.scores && <details className="text-xs text-stone-500"><summary className="cursor-pointer">{t('規則的原始分數')}</summary>
                      <pre className="whitespace-pre-wrap break-all num">{JSON.stringify(lab.scores, null, 1)}</pre></details>}
                    {lab.flags.map((f: string) => <div key={f} className="text-xs text-amber-800 bg-amber-50 rounded px-2 py-1">{flagText(f, stateNames) || f}</div>)}
                  </div>
                ) : <span className="text-stone-500">{t('這張還沒有標籤')}</span>}
              </Card>
              <Card title={t('人工確認(加入測試集)')}>
                <div className="flex flex-col gap-2">
                  {questions.map(qs => (
                    <div key={qs.id} className="flex flex-wrap gap-1.5 items-center">
                      <span className="text-xs text-stone-500 w-12">{qs.name}</span>
                      {qs.classes!.map(c => (
                        <Button key={String(c.value)} variant={d.review?.answers?.[qs.id] === c.value ? 'primary' : 'default'}
                          onClick={() => decide.mutate({ [qs.id]: c.value })}>{c.name}</Button>
                      ))}
                    </div>
                  ))}
                  <ErrorText error={decide.error} />
                </div>
              </Card>
              {d.recorded.map(r => <Card key={r.title} title={r.title}>
                <div className="grid grid-cols-2 gap-1 text-xs num">
                  {r.rows.map(([k, v]) => <span key={k}>{k} {v ?? '—'}</span>)}
                </div>
              </Card>)}
              <Card title={t('前後 5 秒的事件')}>
                <div className="flex flex-col gap-1 text-xs max-h-40 overflow-auto">
                  {[...d.events.map(e => ({ t: e.t, text: `${e.event}${e.id ? ` ${e.id}` : ''}${e.kind ? ` ${e.kind}` : ''}${e.action ? ` ${e.action}` : ''}` })),
                    ...d.touches.map(x => ({ t: x.t_down, text: t('觸控 {action} ({x0},{y0})', { action: x.action, x0: x.x0, y0: x.y0 }) }))]
                    .sort((a, b) => a.t - b.t)
                    .map((e, i) => (
                      <div key={i} className={`flex gap-2 ${Math.abs(e.t - d.sample.t_req) < 0.5 ? 'font-medium text-stone-900' : 'text-stone-600'}`}>
                        <span className="num w-14 shrink-0">{(e.t - d.sample.t_req >= 0 ? '+' : '') + (e.t - d.sample.t_req).toFixed(1)}s</span><span>{e.text}</span>
                      </div>
                    ))}
                  {!d.events.length && !d.touches.length && <span className="text-stone-500">{t('沒有')}</span>}
                </div>
              </Card>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
