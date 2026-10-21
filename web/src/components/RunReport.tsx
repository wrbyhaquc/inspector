import { t } from '../i18n'
// The parts of a training run's report shared by "學習" (live curves) and "成績與錯題" (scores, mistakes)
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { browseLink, type EpochMetrics, type HeadEval, type RunDetail } from '../api'
import { Zoom } from './FrameView'
import { Empty } from './ui'
import { pct } from '../lib/format'
import { mainRoi, stateColor, useSchema } from '../lib/schema'

export const TEST_TEXT: Record<string, string> = { pass: t('通過'), partial: t('部分通過'), fail: t('未通過') }
export const TEST_STYLE: Record<string, string> = {
  pass: 'bg-emerald-100 text-emerald-800', partial: 'bg-amber-100 text-amber-800', fail: 'bg-rose-100 text-rose-800',
}

export function Curves({ run }: { run: RunDetail }) {
  const m = run.metrics
  if (!m.length) return <div className="text-sm text-stone-500">{t('還沒有完成任何一輪')}</div>
  const heads = run.heads ?? []
  return (
    <div className="flex flex-col gap-2">
      <div className="text-sm font-medium text-stone-700">{t('學習曲線')} <span className="text-xs font-normal text-stone-500">{t('(★ = 保留裝置分數最好的一輪,最後用它評估)')}</span></div>
      <div className="grid md:grid-cols-2 xl:grid-cols-3 gap-3">
        <MiniChart title={t('訓練損失(越低越好)')} m={m} series={[{ label: t('總和'), color: '#44403c', get: e => e.train_loss.total }]} />
        {heads.map((h, i) => (
          <MiniChart key={h.id} title={h.kind === 'class' ? t('{name} 準確率', { name: h.name }) : t('{name} 平均誤差(越低越好)', { name: h.name })} m={m} percent={h.kind === 'class'}
            series={[
              { label: t('保留裝置'), color: stateColor(i), get: e => e.val[h.id] ?? null, dash: true },
              { label: t('測試集'), color: stateColor(i), get: e => e.test[h.id] ?? null },
            ]} />
        ))}
      </div>
    </div>
  )
}

export function MiniChart({ title, m, series, percent }: {
  title: string; m: EpochMetrics[]; percent?: boolean
  series: { label: string; color: string; get: (e: EpochMetrics) => number | null | undefined; dash?: boolean }[]
}) {
  const W = 300, H = 120, P = { l: 34, r: 8, t: 8, b: 18 }
  const vals = series.flatMap(s => m.map(s.get)).filter((v): v is number => v != null)
  if (!vals.length) return null
  let lo = Math.min(...vals), hi = Math.max(...vals)
  if (percent) { lo = Math.max(0, Math.min(lo, 0.5)); hi = 1 }
  if (hi - lo < 1e-6) hi = lo + 1
  const x = (ep: number) => P.l + ((ep - 1) / Math.max(1, m.length - 1)) * (W - P.l - P.r)
  const y = (v: number) => P.t + (1 - (v - lo) / (hi - lo)) * (H - P.t - P.b)
  const fmt = (v: number) => (percent ? `${Math.round(v * 100)}%` : v < 0.1 ? v.toFixed(3) : v.toFixed(2))
  const best = m.find(e => e.best && m.filter(z => z.best).slice(-1)[0] === e)
  return (
    <div className="border border-stone-200 rounded-md p-2">
      <div className="text-xs text-stone-600 mb-1 flex justify-between gap-2">
        <span>{title}</span>
        <span className="flex gap-2">{series.map(s => (
          <span key={s.label} className="flex items-center gap-1">
            <svg width="14" height="4"><line x1="0" y1="2" x2="14" y2="2" stroke={s.color} strokeWidth="2" strokeDasharray={s.dash ? '3 2' : undefined} /></svg>{s.label}
          </span>
        ))}</span>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full">
        {[lo, (lo + hi) / 2, hi].map(v => (
          <g key={v}>
            <line x1={P.l} x2={W - P.r} y1={y(v)} y2={y(v)} stroke="#e7e5e4" />
            <text x={P.l - 4} y={y(v) + 3} textAnchor="end" fontSize="9" fill="#78716c">{fmt(v)}</text>
          </g>
        ))}
        <text x={P.l} y={H - 4} fontSize="9" fill="#78716c">1</text>
        <text x={W - P.r} y={H - 4} fontSize="9" fill="#78716c" textAnchor="end">{t('{length} 輪', { length: m.length })}</text>
        {best && <line x1={x(best.epoch)} x2={x(best.epoch)} y1={P.t} y2={H - P.b} stroke="#fbbf24" strokeDasharray="2 2" />}
        {series.map(s => {
          const pts = m.map(e => [e.epoch, s.get(e)] as const).filter(([, v]) => v != null) as [number, number][]
          return (
            <g key={s.label}>
              <polyline fill="none" stroke={s.color} strokeWidth="1.8" strokeDasharray={s.dash ? '4 3' : undefined}
                points={pts.map(([ep, v]) => `${x(ep)},${y(v)}`).join(' ')} />
              {pts.length > 0 && <text x={x(pts[pts.length - 1][0]) - 2} y={y(pts[pts.length - 1][1]) - 4} fontSize="9" textAnchor="end" fill={s.color}>{fmt(pts[pts.length - 1][1])}</text>}
            </g>
          )
        })}
      </svg>
    </div>
  )
}

export function Report({ run }: { run: RunDetail }) {
  const ev = run.eval!
  const sch = useSchema()
  const [filter, setFilter] = useState<string>('all')
  const cls = Object.entries(ev.heads).filter(([, h]) => h.kind === 'class')
  const ratio = Object.entries(ev.heads).filter(([, h]) => h.kind === 'ratio')
  const mistakes = ev.mistakes.filter(x => filter === 'all' || x.state === filter)
  const nameOf = (h: HeadEval, v: unknown) => h.class_names?.[h.classes?.indexOf(String(v)) ?? -1] ?? String(v ?? t('無法判斷'))
  return (
    <div className="flex flex-col gap-5">
      <div>
        <div className="text-sm font-medium text-stone-700 mb-2">{t('測試集報告')} <span className="text-xs font-normal text-stone-500">{t('(第 {best_epoch} 輪的模型 · {test_frames} 張 · 保留裝置', { best_epoch: ev.best_epoch, test_frames: ev.test_frames })} {ev.holdout.join(', ') || t('無')})</span></div>
        <table className="text-sm w-full max-w-4xl">
          <thead>
            <tr className="text-xs text-stone-500 text-left">
              <th className="font-normal py-1">{t('狀態')}</th><th className="font-normal text-right">{t('模型')}</th>
              <th className="font-normal text-right">{t('看過的裝置')}</th><th className="font-normal text-right">{t('保留裝置')}</th>
              <th className="font-normal text-right">{t('規則(全部)')}</th><th className="font-normal text-right">{t('規則(有判斷時)')}</th><th className="font-normal text-right">{t('規則判斷率')}</th>
            </tr>
          </thead>
          <tbody>
            {cls.map(([id, h]) => (
              <tr key={id} className="border-t border-stone-100 num">
                <td className="py-1.5">{h.name}</td>
                <td className="text-right font-semibold">{pct(h.model_acc)}</td>
                <td className="text-right">{pct(h.by_group?.seen?.acc)} <span className="text-stone-400 text-xs">({h.by_group?.seen?.n ?? 0})</span></td>
                <td className="text-right">{pct(h.by_group?.holdout?.acc)} <span className="text-stone-400 text-xs">({h.by_group?.holdout?.n ?? 0})</span></td>
                <td className="text-right">{pct(h.rule?.acc_overall)}</td>
                <td className="text-right">{pct(h.rule?.acc_when_answered)}</td>
                <td className="text-right">{pct(h.rule?.coverage)}</td>
              </tr>
            ))}
            {ratio.map(([id, h]) => (
              <tr key={id} className="border-t border-stone-100 num">
                <td className="py-1.5">{h.name}</td>
                <td className="text-right font-semibold" colSpan={1}>±{h.test_mae != null ? (h.test_mae * 100).toFixed(1) : '—'}%</td>
                <td colSpan={5} className="text-xs text-stone-500 pl-4">{t('平均誤差(和標註來源的真實值比),{n} 張', { n: h.n })}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="text-xs text-stone-500 mt-2 max-w-4xl">
          {t('「規則(有判斷時)」很準但常常不判斷(被遮住、特效、橫幅…);模型每張都要回答。「保留裝置」是模型完全沒看過的裝置,這欄最能代表換到新裝置時的表現。')}
        </p>
      </div>

      <div className="flex flex-wrap gap-4">
        {cls.map(([id, h]) => <Confusion key={id} h={h} />)}
      </div>

      <div>
        <div className="flex items-center gap-3 mb-2 flex-wrap">
          <div className="text-sm font-medium text-stone-700">{t('答錯的畫面({length})', { length: mistakes.length })}</div>
          <select value={filter} onChange={e => setFilter(e.target.value)} className="border border-stone-300 rounded px-2 py-0.5 text-sm">
            <option value="all">{t('全部狀態')}</option>
            {cls.map(([id, h]) => <option key={id} value={id}>{h.name}</option>)}
          </select>
          <span className="text-xs text-stone-500">{t('點圖到資料瀏覽看完整畫面。答錯的圖常常透露模型缺哪一類資料,或答案本身有問題。')}</span>
        </div>
        {mistakes.length === 0 ? <Empty>{t('沒有答錯的畫面')}</Empty> : (
          <div className="flex flex-wrap gap-3">
            {mistakes.slice(0, 80).map((x, i) => {
              const h = ev.heads[x.state]
              const st = sch.data?.schema.states.find(s => s.id === x.state)
              const link = browseLink(x.frame)
              const body = (
                <div className="border border-stone-200 rounded-md p-2 hover:border-amber-400 flex flex-col gap-1 bg-white">
                  {st && <Zoom frame={x.frame} box={mainRoi(st).box} scale={st.review?.scale ?? 2} maxWidth={260} />}
                  <div className="text-xs">
                    <span className="text-stone-500">{h.name}:</span>{t('答案')} <b>{nameOf(h, x.answer)}</b> {t('· 模型')} <b className="text-rose-700">{nameOf(h, x.pred)}</b>
                    <span className="text-stone-400 num"> ({Math.round(x.conf * 100)}%)</span>
                  </div>
                  <div className="text-[11px] text-stone-400">{t('規則 {p1} · {device}', { p1: nameOf(h, x.rule), device: x.device })}</div>
                </div>
              )
              return link ? <Link key={i} to={link}>{body}</Link> : <div key={i}>{body}</div>
            })}
          </div>
        )}
      </div>
    </div>
  )
}

export function Confusion({ h }: { h: HeadEval }) {
  const cm = h.confusion ?? []
  const keep = h.classes!.map((_, i) => i).filter(i => cm[i]?.some(v => v) || cm.some(r => r[i]))
  const max = Math.max(1, ...cm.flat())
  return (
    <div className="border border-stone-200 rounded-md p-2">
      <div className="text-xs text-stone-600 mb-1">{t('{name}:列 = 答案,欄 = 模型', { name: h.name })}</div>
      <table className="text-xs num">
        <thead><tr><th />{keep.map(j => <th key={j} className="px-2 font-normal text-stone-500">{h.class_names![j]}</th>)}</tr></thead>
        <tbody>
          {keep.map(i => (
            <tr key={i}>
              <th className="pr-2 font-normal text-stone-500 text-right">{h.class_names![i]}</th>
              {keep.map(j => {
                const v = cm[i][j]
                return <td key={j} className="w-10 h-7 text-center" style={{ background: v ? (i === j ? `rgba(16,185,129,${0.15 + 0.6 * v / max})` : `rgba(244,63,94,${0.15 + 0.6 * v / max})`) : undefined }}>{v || ''}</td>
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
