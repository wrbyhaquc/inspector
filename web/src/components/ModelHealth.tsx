import { locale, t } from '../i18n'
import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api, type QualityRates } from '../api'
import { Card, Empty, ErrorText } from './ui'

const pct = (v: number | null | undefined) => v == null ? '—' : `${Math.round(v * 100)}%`
const worse = (r: QualityRates, u: QualityRates) => r.n > 0 && r.low != null && u.n >= 2000 && r.low >= Math.max(0.25, (u.low ?? 0) * 2 + 0.05)
const tone = (r: QualityRates, u: QualityRates) => worse(r, u) ? 'text-rose-700 font-semibold' : r.low != null && u.low != null && r.low > u.low * 1.5 + 0.03 ? 'text-amber-700' : 'text-stone-700'

/** Whether to train again, and how sure the running model has been per state (學習 page). */
export function ModelHealth() {
  const [hours, setHours] = useState(24)
  const q = useQuery({ queryKey: ['quality', hours], queryFn: () => api.quality(hours), refetchInterval: 60000 })
  const [open, setOpen] = useState<string | null>(null)
  const d = q.data
  if (!d) return <Card title={t('執行中的模型')}><ErrorText error={q.error} /><Empty>{q.isLoading ? t('讀取中…') : t('讀取失敗')}</Empty></Card>
  const r = d.retrain
  return (
    <div className="grid xl:grid-cols-[420px_1fr] gap-5 items-start">
      <Card title={t('要不要重新訓練')}>
        <div className={`rounded-lg px-3 py-2 text-sm ${r.suggest ? 'bg-amber-50 border border-amber-200 text-amber-900' : 'bg-emerald-50 border border-emerald-200 text-emerald-900'}`}>
          {r.suggest ? <>{t('建議重新訓練:{p1}', { p1: r.reasons.join(t(';')) })}</> : t('目前不用:模型的表現穩定,新答的題也還不多。')}
        </div>
        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-sm mt-3">
          <dt className="text-stone-500">{t('執行中的模型')}</dt><dd>{d.model ?? '—'}</dd>
          <dt className="text-stone-500">{t('訓練至今')}</dt><dd>{r.days == null ? '—' : t('{p1} 天', { p1: r.days.toFixed(1) })}</dd>
          <dt className="text-stone-500">{t('之後新答的題')}</dt><dd className="num">{r.answers}</dd>
          <dt className="text-stone-500">{t('執行時存下的題')}</dt><dd className="num">{t('{saved}(還沒答 {unanswered},', { saved: r.saved, unanswered: r.unanswered })}<Link className="underline" to="/review">{t('去回答')}</Link>)</dd>
        </dl>
        <p className="text-xs text-stone-500 mt-2">{t('判斷方式:{rule}。先把沒把握的題答一答,再訓練,效果最好。', { rule: r.rule })}</p>
      </Card>

      <Card title={t('執行中的品質')} extra={<label className="text-xs text-stone-600 flex items-center gap-1">{t('最近')}
        <select className="border border-stone-300 rounded px-1 py-0.5" value={hours} onChange={e => setHours(Number(e.target.value))}>
          {[6, 24, 72, 168].map(h => <option key={h} value={h}>{h >= 24 ? t('{p1} 天', { p1: h / 24 }) : t('{h} 小時', { h })}</option>)}
        </select></label>}>
        <p className="text-xs text-stone-500 mb-2">{t('執行時每個狀態的把握程度,和這個模型平常比。「沒把握」= 信心低於 {conf_low};「和規則不同」= 有畫面規則的狀態,規則說的不一樣。 某個狀態突然變差(例如畫面改版),會自動發通知。', { conf_low: d.conf_low })}</p>
        {!d.states.length ? <Empty>{t('還沒有資料:腳本執行跑一段時間後(每 10 分鐘記一次)就會出現。')}</Empty> : (
          <div className="overflow-x-auto">
            <table className="text-sm w-full">
              <thead><tr className="text-xs text-stone-500 text-left">
                <th className="py-1.5 pr-3 font-normal">{t('狀態')}</th><th className="py-1.5 pr-3 font-normal">{t('平均信心')}</th>
                <th className="py-1.5 pr-3 font-normal">{t('沒把握(平常)')}</th><th className="py-1.5 pr-3 font-normal">{t('和規則不同(平常)')}</th>
                <th className="py-1.5 pr-3 font-normal">{t('每小時沒把握')}</th><th className="py-1.5 font-normal num">{t('畫面數')}</th>
              </tr></thead>
              <tbody>
                {d.states.map(s => {
                  const max = Math.max(0.3, ...s.hours.map(h => h.low ?? 0))
                  return [
                    <tr key={s.id} className="border-t border-stone-100 cursor-pointer hover:bg-stone-50" onClick={() => setOpen(o => o === s.id ? null : s.id)}>
                      <td className="py-1.5 pr-3">{s.name}{worse(s.recent, s.usual) && <span className="ml-1 text-[10px] px-1 rounded bg-rose-600 text-white">{t('變差')}</span>}</td>
                      <td className="py-1.5 pr-3 num">{s.recent.conf == null ? '—' : s.recent.conf.toFixed(2)}</td>
                      <td className={`py-1.5 pr-3 num ${tone(s.recent, s.usual)}`}>{pct(s.recent.low)}<span className="text-stone-400 font-normal">({pct(s.usual.low)})</span></td>
                      <td className="py-1.5 pr-3 num">{s.recent.rule_n ? pct(s.recent.dis) : '—'}<span className="text-stone-400">({s.usual.rule_n ? pct(s.usual.dis) : '—'})</span></td>
                      <td className="py-1.5 pr-3">
                        <div className="flex items-end gap-px h-6" title={t('每一格一小時;越高 = 沒把握的畫面越多')}>
                          {s.hours.map(h => <span key={h.t} className={`w-1.5 rounded-t ${(h.low ?? 0) >= 0.25 ? 'bg-rose-400' : 'bg-sky-300'}`}
                            style={{ height: `${Math.max(2, ((h.low ?? 0) / max) * 24)}px` }} title={t('{p1}:沒把握 {p2}({n} 張)', { p1: new Date(h.t * 1000).toLocaleString(locale, { month: 'numeric', day: 'numeric', hour: '2-digit' }), p2: pct(h.low), n: h.n })} />)}
                        </div>
                      </td>
                      <td className="py-1.5 num text-stone-500">{s.recent.n}</td>
                    </tr>,
                    open === s.id && <tr key={`${s.id}:d`}><td colSpan={6} className="pb-2">
                      <div className="flex flex-wrap gap-2 text-xs">
                        {Object.entries(s.devices).map(([dev, v]) => <span key={dev} className="px-2 py-1 rounded bg-stone-50 border border-stone-200">
                          {t('{dev}:信心 {p2} · 沒把握 {p3} · 和規則不同 {p4}({n} 張)', { dev, p2: v.conf == null ? '—' : v.conf.toFixed(2), p3: pct(v.low), p4: v.rule_n ? pct(v.dis) : '—', n: v.n })}</span>)}
                      </div>
                    </td></tr>,
                  ]
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  )
}
