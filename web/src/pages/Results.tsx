import { useQuery } from '@tanstack/react-query'
import { Link, useSearchParams } from 'react-router-dom'
import { api, type HeadEval, type ModelTest } from '../api'
import { Curves, Report, TEST_STYLE, TEST_TEXT } from '../components/RunReport'
import { Card, Empty, ErrorText, Page } from '../components/ui'
import { dateTime, pct } from '../lib/format'
import { t } from '../i18n'
import { words } from '../lib/project'

/** One state's exam result in plain words: passed or not, why, and the numbers behind it. */
function ScoreCard({ h, tx }: { h: HeadEval; tx?: ModelTest }) {
  const hold = h.by_group?.holdout
  return (
    <div className="border border-stone-200 rounded-lg p-3 bg-white flex flex-col gap-1.5">
      <div className="flex items-center justify-between gap-2">
        <span className="font-medium text-stone-800">{h.name}</span>
        {tx && <span className={`px-2 py-0.5 rounded-full text-xs ${TEST_STYLE[tx.result]}`}>{TEST_TEXT[tx.result]}</span>}
      </div>
      {h.kind === 'class' ? (
        <>
          <div className="text-2xl font-semibold num">{pct(h.model_acc)}<span className="text-xs font-normal text-stone-500 ml-1">{t('答對({n} 題)', { n: h.n })}</span></div>
          <div className="text-xs text-stone-500 num">
            {t('沒看過的{device} {p2}({p3} 題) · 畫面規則 {p4}', { device: words.device, p2: pct(hold?.acc), p3: hold?.n ?? 0, p4: pct(h.rule?.acc_overall) })}
          </div>
        </>
      ) : (
        <div className="text-2xl font-semibold num">±{h.test_mae != null ? (h.test_mae * 100).toFixed(1) : '—'}%<span className="text-xs font-normal text-stone-500 ml-1">{t('平均誤差({n} 張)', { n: h.n })}</span></div>
      )}
      {tx && tx.result !== 'pass' && <div className="text-xs text-stone-600">{tx.reason}</div>}
    </div>
  )
}

export default function Results() {
  const [params, setParams] = useSearchParams()
  const runs = useQuery({ queryKey: ['trainRuns'], queryFn: api.trainRuns })
  const done = (runs.data?.runs ?? []).filter(r => r.status.state === 'done')
  const id = params.get('run') || done[0]?.id || ''
  const q = useQuery({ queryKey: ['trainRun', id], queryFn: () => api.trainRun(id), enabled: !!id })
  const r = q.data
  const prog = useQuery({ queryKey: ['statesProgress'], queryFn: api.statesProgress })
  const c = prog.data?.criteria

  return (
    <Page title={t('成績與錯題')}
      desc={t('每次學習完,平台用你回答過的考題幫模型打分數。這裡看每個狀態考得怎樣、錯在哪些畫面;通過的狀態,腳本執行時才會交給模型判斷。')}>
      <ErrorText error={runs.error || q.error} />
      <Card title={t('哪一次學習')}>
        <div className="flex flex-wrap gap-3 items-center text-sm">
          <select className="border border-stone-300 rounded-md px-2 py-1.5 min-w-72" value={id}
            onChange={e => setParams(e.target.value ? { run: e.target.value } : {})}>
            {done.map((x, i) => <option key={x.id} value={x.id}>{x.config?.name || t('(未命名)')} · {dateTime(x.created)}{i === 0 ? t('(最新)') : ''}</option>)}
          </select>
          {done.length === 0 && <span className="text-stone-500">{t('還沒有學完的紀錄,先到')} <Link to="/train" className="underline">{t('學習')}</Link> {t('開始。')}</span>}
        </div>
        {c && <p className="text-xs text-stone-500 mt-2">
          {t('通過的條件:至少 {min_answers} 題考題、每種答案至少 {min_per_class} 題、不比畫面規則差、沒看過的{device}至少答對 {p4}%。 「部分通過」= 整體通過,但有些答案幾乎沒考到。', { min_answers: c.min_answers, min_per_class: c.min_per_class, device: words.device, p4: Math.round(c.holdout_min * 100) })}
        </p>}
      </Card>

      {!r ? (id && <Card><Empty>{t('讀取中…')}</Empty></Card>) : !r.eval ? <Card><Empty>{t('這次學習沒有考試結果')}</Empty></Card> : (
        <>
          <div className="grid sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
            {Object.entries(r.eval.heads).map(([k, h]) => <ScoreCard key={k} h={h} tx={r.tests?.[k]} />)}
          </div>
          <Card title={t('詳細成績與答錯的畫面')}>
            <Report run={r} />
          </Card>
          <details className="bg-white border border-stone-200 rounded-lg p-4">
            <summary className="text-sm font-medium text-stone-700 cursor-pointer">{t('學習過程(進階:每一輪的分數變化)')}</summary>
            <div className="mt-3"><Curves run={r} /></div>
          </details>
        </>
      )}
    </Page>
  )
}
