import { t } from '../i18n'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { api, type NextStep } from '../api'
import { Card, Empty, ErrorText, JobStatus, Page, Share, Stat } from '../components/ui'
import { bytes, dateTime, pct, sessionTime } from '../lib/format'
import { useSchema } from '../lib/schema'
import { dn } from '../lib/sources'
import { edition } from '../lib/project'

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
      <NextStepsCard />
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
