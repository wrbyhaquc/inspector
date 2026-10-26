import { t } from '../i18n'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api, type NextStep, type Storage } from '../api'
import { Button, Card, Empty, ErrorText, JobStatus, Page, Share, Stat } from '../components/ui'
import { bytes, dateTime, pct, sessionTime } from '../lib/format'
import { useSchema } from '../lib/schema'
import { dn } from '../lib/sources'
import { edition } from '../lib/project'
import { tutorialLink } from '../lib/tutorial'

const BAR: Record<string, string> = { green: 'bg-emerald-500', red: 'bg-rose-500', blue: 'bg-sky-500', amber: 'bg-amber-500', violet: 'bg-violet-500', stone: 'bg-stone-400' }

const GROUPS: { id: NextStep['group']; title: string; hint: string }[] = [
  { id: 'watch', title: t('① 要看什麼'), hint: t('要看的狀態、影像來源與錄製') },
  { id: 'teach', title: t('② 教它看懂'), hint: t('回答問題、學習') },
  { id: 'auto', title: t('③ 自動化'), hint: t('腳本、素材庫、執行') },
]
const LEVEL: Record<string, { mark: string; cls: string }> = {
  warn: { mark: '!', cls: 'bg-rose-600 text-white' },
  todo: { mark: '→', cls: 'bg-amber-500 text-stone-900' },
  info: { mark: 'i', cls: 'bg-stone-200 text-stone-600' },
}

function NextStepsCard() {
  const q = useQuery({ queryKey: ['nextSteps'], queryFn: api.nextSteps, refetchInterval: 15000 })
  const steps = q.data?.steps ?? []
  return (
    <div className="grid lg:grid-cols-3 gap-4">
      {GROUPS.map(g => {
        const mine = steps.filter(s => s.group === g.id)
        return (
          <Card key={g.id} title={g.title} extra={<span className="text-xs text-stone-500">{g.hint}</span>}>
            {q.isLoading ? <Empty>{t('整理中…')}</Empty> : mine.length === 0 ? (
              <div className="text-sm text-emerald-700 flex items-center gap-2">
                <span className="w-5 h-5 rounded-full bg-emerald-100 text-emerald-700 flex items-center justify-center text-xs">✓</span>{t('這一段目前沒有要做的事')}
              </div>
            ) : (
              <div className="flex flex-col gap-3">
                {mine.map((s, i) => (
                  <div key={i} className="flex gap-2.5 items-start">
                    <span className={`w-5 h-5 shrink-0 mt-0.5 rounded-full flex items-center justify-center text-xs font-semibold ${LEVEL[s.level]?.cls ?? LEVEL.info.cls}`}>
                      {LEVEL[s.level]?.mark ?? 'i'}</span>
                    <div className="flex-1 min-w-0">
                      <div className={`text-sm ${s.level === 'info' ? 'text-stone-600' : 'font-medium text-stone-900'}`}>{s.title}</div>
                      {s.detail && <div className="text-xs text-stone-500 mt-0.5">{s.detail}</div>}
                      {s.link && <Link to={s.link} className={`inline-block mt-1.5 text-xs whitespace-nowrap rounded-md ${s.level === 'info'
                        ? 'text-stone-500 hover:text-stone-900 underline underline-offset-2' : 'px-2.5 py-1 bg-stone-900 text-white hover:bg-stone-700'}`}>{s.cta || t('前往')} →</Link>}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </Card>
        )
      })}
    </div>
  )
}

/** a runtime (執行版): only what can be done here - the running scripts, the sources, the packs */
const PARTS: { k: keyof Storage['sizes']; label: string; color: string }[] = [
  { k: 'recordings', label: t('錄影'), color: 'bg-sky-500' }, { k: 'records', label: t('執行紀錄'), color: 'bg-amber-500' },
  { k: 'models', label: t('模型'), color: 'bg-violet-500' }, { k: 'answers', label: t('標籤與答案'), color: 'bg-emerald-500' },
  { k: 'other', label: t('其他'), color: 'bg-stone-400' }]

/** Where the disk goes: each kind of data, a day's growth, how long the free space lasts, cleaning the run's records. */
export function StorageCard() {
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['storage'], queryFn: () => api.storage(), staleTime: 60_000 })
  const re = useMutation({ mutationFn: () => api.storage(true), onSuccess: d => qc.setQueryData(['storage'], d) })
  const s = q.data
  if (!s) return null
  const short = s.days_left !== null && s.days_left < 30
  const days = Object.values(s.keep)
  const kept = days.some(d => d === 0) ? t('(有些全部保留)') : Math.min(...days) === Math.max(...days)
    ? t('(保留 {days} 天)', { days: days[0] }) : t('(保留 {a}~{b} 天)', { a: Math.min(...days), b: Math.max(...days) })
  return (
    <Card title={t('儲存空間')} extra={<span className="flex items-center gap-3 text-xs text-stone-500">
      <span className="num">{t('磁碟剩 {free} / {total}', { free: bytes(s.free), total: bytes(s.disk_total) })}</span>
      <button className="underline" disabled={re.isPending} onClick={() => re.mutate()}>{re.isPending ? t('計算中…') : t('重新計算')}</button>
      {location.pathname !== '/storage' && <Link to="/storage" className="underline">{t('管理 →')}</Link>}</span>}>
      <div className="flex flex-col gap-3 text-sm">
        <div className="flex h-3 rounded-full overflow-hidden bg-stone-100" title={bytes(s.total)}>
          {PARTS.map(p => s.sizes[p.k] > 0 && <div key={p.k} className={p.color} style={{ width: `${(s.sizes[p.k] / Math.max(1, s.total)) * 100}%` }} />)}
        </div>
        <div className="flex flex-wrap gap-x-5 gap-y-1">
          {PARTS.map(p => <span key={p.k} className="flex items-center gap-1.5"><span className={`w-2.5 h-2.5 rounded-sm ${p.color}`} />{p.label}
            <b className="num">{bytes(s.sizes[p.k])}</b>
            {p.k === 'recordings' && s.per_day.recordings > 0 && <span className="text-xs text-stone-500 num">{t('(每天 +{size})', { size: bytes(s.per_day.recordings) })}</span>}
            {p.k === 'records' && <span className="text-xs text-stone-500 num">{kept}</span>}</span>)}
        </div>
        <div className={short ? 'text-amber-800' : 'text-stone-600'}>
          {s.days_left === null ? t('最近一週沒有變多。') : s.days_left > 3650 ? t('照最近一週的速度(每天約 +{size}),磁碟還能用超過 10 年。', { size: bytes(s.growing) }) : t('照最近一週的速度(每天約 +{size}),磁碟大約還能用 {days} 天。', { size: bytes(s.growing), days: s.days_left.toLocaleString() })}
          {s.keep_days > 0 && s.record_days >= s.keep_days && ' ' + t('執行紀錄已經滿 {days} 天,之後會邊記邊刪,不再變多。', { days: s.keep_days })}
        </div>
        <div className="text-xs text-stone-500">{s.min_free_gb > 0
          ? t('至少留 {gb} GB 可用空間;不夠時{then}。', { gb: s.min_free_gb, then: s.when_full === 'cycle' ? t('刪掉最舊、沒有答案和測試在用的錄影,繼續錄製') : t('停止錄製') })
          : t('沒有設定至少要留的空間。')}{' '}{t('保留天數和空間保護在「儲存空間」設定。')}</div>
        <ErrorText error={q.error} />
      </div>
    </Card>
  )
}

function RuntimeOverview() {
  const q = useQuery({ queryKey: ['nextSteps'], queryFn: api.nextSteps, refetchInterval: 15000 })
  const steps = q.data?.steps ?? []
  return (
    <Page title={t('首頁')} desc={t('這台是執行版:執行安裝好的方案包。要改設計請在 Studio 修改,再匯出新版本安裝到這裡。')}>
      <ErrorText error={q.error} />
      <Card title={t('現在的狀況')}>
        {q.isLoading ? <Empty>{t('整理中…')}</Empty> : steps.length === 0 ? <Empty>{t('一切正常')}</Empty> : (
          <div className="flex flex-col gap-3">
            {steps.map((s, i) => (
              <div key={i} className="flex gap-2.5 items-start">
                <span className={`w-5 h-5 shrink-0 mt-0.5 rounded-full flex items-center justify-center text-xs font-semibold ${LEVEL[s.level]?.cls ?? LEVEL.info.cls}`}>
                  {LEVEL[s.level]?.mark ?? 'i'}</span>
                <div className="flex-1 min-w-0">
                  <div className={`text-sm ${s.level === 'info' ? 'text-stone-600' : 'font-medium text-stone-900'}`}>{s.title}</div>
                  {s.detail && <div className="text-xs text-stone-500 mt-0.5">{s.detail}</div>}
                  {s.link && <Link to={s.link} className="inline-block mt-1.5 text-xs text-stone-500 hover:text-stone-900 underline underline-offset-2">{s.cta || t('前往')} →</Link>}
                </div>
              </div>
            ))}
          </div>
        )}
      </Card>
      <StorageCard />
      <div className="flex gap-3 flex-wrap text-sm">
        <Link to="/script" className="px-3 py-1.5 rounded-md bg-stone-900 text-white hover:bg-stone-700">{t('執行')} →</Link>
        <Link to="/panel" className="px-3 py-1.5 rounded-md border border-stone-300 bg-white hover:bg-stone-50">{t('操作面板(給使用者) ↗')}</Link>
        <Link to="/packs" className="px-3 py-1.5 rounded-md border border-stone-300 bg-white hover:bg-stone-50">{t('方案包')} →</Link>
      </div>
    </Page>
  )
}

export default function Overview() {
  if (edition.name === 'runtime') return <RuntimeOverview />
  return <StudioOverview />
}

// the first-steps route: from an empty project to a pack, one stop per part of the platform (the tutorial's chapters)
const STOPS: { id: string; title: string; why: string; how: string; to: string; ch: number }[] = [
  { id: 'project', title: t('替專案取名字'), why: t('方案包和每一頁都用這個名字;「一台叫做」決定頁面怎麼稱呼一個畫面來源。'),
    how: t('在下面的「專案」卡片填名稱和說明,按「儲存」。'), to: '/', ch: 1 },
  { id: 'sources', title: t('接上畫面來源'), why: t('平台看的就是這些畫面:模擬器、手機、視窗、螢幕、攝影機或錄影檔。'),
    how: t('「來源 › + 加入來源」:掃描這台電腦,或用位址加入攝影機。'), to: '/sources', ch: 2 },
  { id: 'record', title: t('錄一段畫面'), why: t('定義狀態時拿來試規則、檢查準不準;錄到的畫面要涵蓋每一種狀況。'),
    how: t('「錄製」:設好分鐘數按「開始錄製」,同時讓畫面出現各種狀況。'), to: '/collect', ch: 3 },
  { id: 'states', title: t('定義要看的狀態'), why: t('狀態是腳本要問的事,例如「門開了沒」「水位多高」。'),
    how: t('「要看的狀態 › + 新增狀態」:框出範圍、選畫面規則,用錄好的畫面檢查。'), to: '/states', ch: 4 },
  { id: 'answer', title: t('回答問題'), why: t('用你的答案檢查判斷準不準;要訓練模型時,也是用這些答案。'),
    how: t('「回答問題」:每個狀態答 20~30 題(按 1、2…)。'), to: '/review', ch: 5 },
  { id: 'actions', title: t('準備動作'), why: t('腳本怎麼動手:點擊畫面上的位置,或透過輸出控制設備;寫成子腳本重複使用。'),
    how: t('「素材庫」新增按鈕或輸出,再到「腳本」新增子腳本。'), to: '/library', ch: 6 },
  { id: 'scripts', title: t('寫主腳本'), why: t('主腳本一直看著狀態,第一條成立的規則就做它的步驟。'),
    how: t('「腳本 › + 新增主腳本」,加規則:如果…就依序做…'), to: '/scripts', ch: 8 },
  { id: 'run', title: t('開始執行'), why: t('先試跑,看它會做什麼;沒問題再改成正式執行。'),
    how: t('「執行 › 部署」選正式執行,按「開始」,用「詳細」看它怎麼判斷。'), to: '/script', ch: 9 },
  { id: 'panel', title: t('設計操作面板'), why: t('現場的人看這一頁:現在怎樣、幾個按鈕、幾個設定。'),
    how: t('「操作面板設計」:加區塊和監看元件。'), to: '/panel-design', ch: 11 },
  { id: 'export', title: t('匯出方案包'), why: t('做成一個發行版,裝到別台電腦執行(執行版就夠)。'),
    how: t('「方案包 › 匯出發行版」。'), to: '/packs', ch: 12 },
]
const ROUTE_KEY = 'inspector.route.open'

/** From an empty project to a pack: where you are on the way, what each stop is for, and the tutorial's chapter. */
function GettingStarted() {
  const q = useQuery({ queryKey: ['gettingStarted'], queryFn: api.gettingStarted, refetchInterval: 15000 })
  const done = q.data?.done ?? {}
  const n = STOPS.filter(s => done[s.id]).length
  const next = STOPS.find(s => !done[s.id])
  const [open, setOpen] = useState(() => { try { return localStorage.getItem(ROUTE_KEY) !== '0' } catch { return true } })
  const toggle = () => { const v = !open; try { localStorage.setItem(ROUTE_KEY, v ? '1' : '0') } catch { /* this page only */ } ; setOpen(v) }
  if (!q.data) return null
  return (
    <Card title={t('入門路線')} extra={<span className="flex items-center gap-3 text-xs text-stone-500">
      <span className="num">{t('完成 {n} / {total}', { n, total: STOPS.length })}</span>
      <a className="text-sky-700 underline" href={tutorialLink()} target="_blank" rel="noreferrer">{t('完整教學 ↗')}</a>
      <button className="text-stone-600 hover:text-stone-900" onClick={toggle}>{open ? t('收起 ▴') : t('展開 ▾')}</button></span>}>
      {!open ? <div className="text-sm text-stone-600">{next ? t('下一站:{title}', { title: next.title }) : t('入門路線都完成了。')}</div> : (
        <ol className="flex flex-col gap-1">
          {STOPS.map((s, i) => {
            const ok = !!done[s.id], here = s === next
            return (
              <li key={s.id} className={`rounded-lg px-3 py-2 flex gap-3 items-start ${here ? 'bg-amber-50 border border-amber-200' : ''}`}>
                <span className={`mt-0.5 w-6 h-6 shrink-0 rounded-full grid place-items-center text-xs font-bold ${ok ? 'bg-emerald-600 text-white' : here ? 'bg-amber-500 text-stone-900' : 'bg-stone-200 text-stone-600'}`}>{ok ? '✓' : i + 1}</span>
                <div className="flex-1 min-w-0">
                  <div className={`font-medium ${ok ? 'text-stone-500' : 'text-stone-900'}`}>{s.title}{here && <span className="ml-2 text-xs text-amber-700">{t('下一站')}</span>}</div>
                  {(here || !ok) && <div className="text-sm text-stone-600">{s.why}</div>}
                  {here && <div className="text-sm text-stone-800 mt-0.5">{s.how}</div>}
                </div>
                <span className="flex gap-3 text-sm shrink-0">
                  {s.to !== '/' && <Link to={s.to} className={here ? 'text-amber-800 font-medium' : 'text-stone-500 hover:text-stone-900'}>{t('去做 →')}</Link>}
                  <a href={tutorialLink(s.ch)} target="_blank" rel="noreferrer" className="text-stone-500 hover:text-stone-900">{t('教學')}</a>
                </span>
              </li>
            )
          })}
        </ol>
      )}
    </Card>
  )
}

/** What this project is called and what it calls things: the pack (and every page) goes by these. */
function ProjectCard() {
  const q = useQuery({ queryKey: ['project'], queryFn: api.projectGet })
  const [f, setF] = useState<{ name: string; description: string; device: string; item: string } | null>(null)
  const p = q.data
  const v = f ?? (p ? { name: p.name, description: p.description ?? '', device: p.words.device ?? '', item: p.words.item ?? '' } : null)
  const save = useMutation({
    mutationFn: () => api.projectSettingsSave({ name: v!.name, description: v!.description, words: { device: v!.device, item: v!.item } }),
    onSuccess: () => window.location.reload(),          // the words are read once, when the pages open
  })
  if (!p || !v) return null
  const input = 'border border-stone-300 rounded-md px-2 py-1 text-sm'
  return (
    <Card title={t('專案')} extra={<span className="text-xs text-stone-500 num">{t('畫面座標 {w}×{h}', { w: p.screen.width, h: p.screen.height })}</span>}>
      <div className="grid md:grid-cols-[auto_1fr_auto_1fr] gap-x-3 gap-y-2 items-center text-sm">
        <span className="text-stone-600">{t('名稱')}</span>
        <input className={`${input} md:col-span-3`} value={v.name} onChange={e => setF({ ...v, name: e.target.value })} />
        <span className="text-stone-600">{t('說明')}</span>
        <input className={`${input} md:col-span-3`} value={v.description} placeholder={t('一句話:看什麼、做什麼')} onChange={e => setF({ ...v, description: e.target.value })} />
        <span className="text-stone-600" title={t('頁面上怎麼稱呼一個畫面來源,例如「攝影機」「模擬器」')}>{t('一台叫做')}</span>
        <input className={input} value={v.device} onChange={e => setF({ ...v, device: e.target.value })} />
        <span className="text-stone-600" title={t('清單裡的一筆怎麼稱呼,例如「帳號」「魚池」')}>{t('一筆叫做')}</span>
        <input className={input} value={v.item} onChange={e => setF({ ...v, item: e.target.value })} />
      </div>
      <div className="mt-3 flex items-center gap-3 flex-wrap">
        <Button variant="primary" disabled={!f || !v.name.trim() || save.isPending} onClick={() => save.mutate()}>{t('儲存')}</Button>
        <span className="text-xs text-stone-500">{t('方案包的名稱和說明也會跟著改。')}</span>
      </div>
      <ErrorText error={save.error} />
    </Card>
  )
}

function StudioOverview() {
  const q = useQuery({ queryKey: ['overview'], queryFn: api.overview, refetchInterval: 5000 })
  const o = q.data
  const live = o?.collector?.running && !o.collector.stale ? o.collector : null
  const tx = o?.labels?.summary.total ?? {}
  const sch = useSchema()
  // the first two states the screen rules answer
  const shown = (sch.data?.schema.states ?? []).filter(s => s.type === 'class' && s.source.kind === 'rule').slice(0, 2)

  return (
    <Page title={t('下一步')} desc={t('平台整理出現在該做的事。照 ① 要看什麼 → ② 教它看懂 → ③ 自動化 的順序,點右邊的按鈕就會帶你到對應的頁面。')}>
      <ErrorText error={q.error} />
      <GettingStarted />
      <NextStepsCard />
      <ProjectCard />
      <StorageCard />
      <h2 className="text-sm font-semibold text-stone-700 mt-2">{t('數字一覽')} {o && <span className="font-normal text-xs text-stone-500">{t('資料目錄')} <code>{o.data_root}</code></span>}</h2>
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <Stat label={t('錄製次數')} value={o?.sessions ?? '—'} sub={o ? t('觸控 {touches} 次', { touches: o.touches }) : undefined} />
        <Stat label={t('畫面樣本')} value={o?.samples.toLocaleString() ?? '—'} sub={o ? bytes(o.bytes) : undefined} />
        <Stat label={t('已回答的考題')} value={o?.testset.reviewed ?? '—'} sub={t('目標約 200 張')} />
        <Stat label={t('磁碟剩餘')} value={o ? bytes(o.disk.free) : '—'}
          sub={o ? t('已用 {p1},共 {p2}', { p1: pct(o.disk.used / o.disk.total, 0), p2: bytes(o.disk.total) }) : undefined} />
      </div>

      <div className="grid lg:grid-cols-2 gap-4">
        <Card title={t('錄製')} extra={<Link to="/collect" className="text-xs text-stone-500 hover:text-stone-900">{t('前往 →')}</Link>}>
          {live ? (
            <div className="flex flex-col gap-2">
              <div className="text-sm"><span className="text-emerald-700 font-medium">{t('錄製中')}</span>{t(',場次 {session}', { session: live.session })}</div>
              {live.devices.map(d => (
                <div key={d.name} className="flex items-center justify-between text-sm">
                  <span>{dn(d.name)}</span>
                  <span className="text-stone-500 num">{t('樣本 {samples} · 觸控 {touches}{p3}', { samples: d.samples, touches: d.touches, p3: Object.values(d.extra ?? {}).map(x => x.summary).filter(Boolean).map(x => ` · ${x}`).join('') })}</span>
                </div>
              ))}
            </div>
          ) : <Empty>{t('目前沒有在錄製')}</Empty>}
        </Card>

        <Card title={t('自動標註分布{p1}', { p1: o?.labels ? `(${o.labels.version})` : '' })}
          extra={<Link to="/labels" className="text-xs text-stone-500 hover:text-stone-900">{t('前往 →')}</Link>}>
          {o?.labels ? (
            <div className="flex flex-col gap-4">
              {shown.length ? shown.map(s => (
                <div key={s.id}>
                  <div className="text-xs text-stone-500 mb-1.5">{s.name}</div>
                  <Share parts={[...(s.classes ?? []).map(c => ({ label: c.name, value: tx[`${s.id}=${c.value}`] ?? 0, color: BAR[c.color] ?? 'bg-stone-400' })),
                    { label: t('無法判斷'), value: tx[`${s.id}=None`] ?? 0, color: 'bg-stone-300' }]} />
                </div>
              )) : <Empty>{t('還沒有用畫面規則判斷的分類狀態')}</Empty>}
            </div>
          ) : <Empty>{t('還沒有產生標籤')}</Empty>}
        </Card>
      </div>

      <div className="grid lg:grid-cols-2 gap-4">
        <Card title={t('最近的錄製')} extra={<Link to="/browse" className="text-xs text-stone-500 hover:text-stone-900">{t('瀏覽 →')}</Link>}>
          {o?.recent_sessions.length ? (
            <table className="w-full text-sm">
              <thead><tr className="text-xs text-stone-500 text-left"><th className="font-normal pb-2">{t('場次')}</th><th className="font-normal">{t('長度')}</th><th className="font-normal text-right">{t('樣本')}</th><th className="font-normal text-right">{t('大小')}</th></tr></thead>
              <tbody>
                {o.recent_sessions.map(s => (
                  <tr key={s.id} className="border-t border-stone-100">
                    <td className="py-1.5">{sessionTime(s.id)}</td>
                    <td className="num text-stone-600">{s.minutes != null ? t('{minutes} 分', { minutes: s.minutes }) : t('錄製中')}</td>
                    <td className="num text-right">{s.samples}</td>
                    <td className="num text-right text-stone-600">{bytes(s.bytes)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : <Empty>{t('還沒有資料')}</Empty>}
        </Card>

        <Card title={t('最近的工作')}>
          {o?.jobs.length ? (
            <div className="flex flex-col divide-y divide-stone-100">
              {o.jobs.map(j => (
                <div key={j.id} className="py-1.5 flex items-center justify-between text-sm">
                  <span>{j.title}</span>
                  <span className="flex items-center gap-2 text-stone-500 text-xs">{dateTime(j.started)}<JobStatus status={j.status} /></span>
                </div>
              ))}
            </div>
          ) : <Empty>{t('這次啟動介面後還沒有執行過工作')}</Empty>}
        </Card>
      </div>
    </Page>
  )
}
