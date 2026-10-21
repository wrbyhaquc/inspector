import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { api } from '../api'
import { Button, Card, Empty, ErrorText, JobStatus, LogView, Page, Share } from '../components/ui'
import { dateTime, flagText } from '../lib/format'
import { useSchema } from '../lib/schema'
import { t } from '../i18n'

const BAR: Record<string, string> = { green: 'bg-emerald-500', red: 'bg-rose-500', blue: 'bg-sky-500', amber: 'bg-amber-500', violet: 'bg-violet-500', stone: 'bg-stone-400' }

export default function Labels() {
  const qc = useQueryClient()
  const versions = useQuery({ queryKey: ['labels'], queryFn: api.labels })
  const [jobId, setJobId] = useState<string | null>(null)
  const [ver, setVer] = useState<string>('')
  const job = useQuery({
    queryKey: ['job', jobId], queryFn: () => api.job(jobId!), enabled: !!jobId,
    refetchInterval: q => (q.state.data?.status === 'running' ? 1000 : false),
  })
  const run = useMutation({ mutationFn: () => api.labelsRun(), onSuccess: j => setJobId(j.id) })
  const finished = job.data && job.data.status !== 'running'
  useEffect(() => {
    if (finished) qc.invalidateQueries({ queryKey: ['labels'] })     // show the new version when the job ends
  }, [finished, qc])

  const list = versions.data ?? []
  const v = list.find(x => x.version === ver) ?? list[list.length - 1]
  const tx = v?.summary.total ?? {}
  const allStates = useSchema().data?.schema.states ?? []
  const classStates = allStates.filter(x => x.type === 'class')
  const stateNames = Object.fromEntries(allStates.map(x => [x.id, x.name]))
  const [rowStateId, setRowState] = useState('')
  const rowState = classStates.find(x => x.id === rowStateId) ?? classStates[0]
  const cols: [string, string][] = rowState ? [...(rowState.classes ?? []).map(c => [`${rowState.id}=${c.value}`, c.name] as [string, string]), [`${rowState.id}=None`, '?']] : []
  const flags = Object.entries(tx).filter(([k]) => k.startsWith('flag:')).map(([k, n]) => [k.slice(5), n] as const).sort((a, b) => b[1] - a[1])

  return (
    <Page title={t('自動標註')} desc={t('用畫面規則和專案的標註來源,替每張收集到的畫面自動產生狀態標籤。收集到新資料後按「產生標籤」;只會計算新的畫面,已算過的會用快取。')}
      actions={<Button variant="primary" onClick={() => run.mutate()} disabled={run.isPending || job.data?.status === 'running'}>
        {job.data?.status === 'running' ? t('產生中…') : t('產生標籤')}</Button>}>
      <ErrorText error={run.error || versions.error} />
      {jobId && (
        <Card title={t('產生標籤')} extra={job.data && <JobStatus status={job.data.status} />}>
          <LogView lines={job.data?.log} height="h-40" />
        </Card>
      )}

      {v ? (
        <>
          <div className="flex items-center gap-3 text-sm">
            <span className="text-stone-600">{t('版本')}</span>
            <select id="ver" value={v.version} onChange={e => setVer(e.target.value)} className="border border-stone-300 rounded-md px-2 py-1 bg-white">
              {list.map(x => <option key={x.version} value={x.version}>{x.version}</option>)}
            </select>
            <span className="text-stone-500">{t('更新於 {p1} · 共 {p2} 張', { p1: dateTime(v.updated), p2: tx.frames ?? 0 })}</span>
          </div>
          <div className="grid lg:grid-cols-2 gap-4">
            {classStates.map(st => (
              <Card key={st.id} title={st.name}>
                <Share parts={[...(st.classes ?? []).map(c => ({ label: c.name, value: tx[`${st.id}=${c.value}`] ?? 0, color: BAR[c.color ?? 'stone'] ?? 'bg-stone-400' })),
                  { label: t('無法判斷'), value: tx[`${st.id}=None`] ?? 0, color: 'bg-stone-300' }]} />
              </Card>
            ))}
          </div>

          <Card title={t('各場次 / 裝置')} extra={<select className="border border-stone-300 rounded-md px-2 py-1 text-sm bg-white" value={rowState?.id ?? ''} onChange={e => setRowState(e.target.value)}>
            {classStates.map(st => <option key={st.id} value={st.id}>{st.name}</option>)}</select>}>
            <div className="overflow-x-auto">
              <table className="w-full text-sm num">
                <thead>
                  <tr className="text-xs text-stone-500 text-left">
                    {[t('場次 / 裝置'), t('畫面數'), ...cols.map(([, h]) => h)].map(h => <th key={h} className="font-normal pb-2 pr-4">{h}</th>)}
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(v.summary.by_session_device).map(([k, c]) => (
                    <tr key={k} className="border-t border-stone-100">
                      <td className="py-1.5 pr-4">{k}</td>
                      {['frames', ...cols.map(([f]) => f)].map(f =>
                        <td key={f} className={`pr-4 ${f !== 'frames' && !f.endsWith('=None') && !(c[f] > 0) ? 'text-rose-600' : ''}`}>{c[f] ?? 0}</td>)}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="text-xs text-stone-500 mt-3">{t('紅色的 0 代表這台還沒有這個答案的畫面。之後保留一台當測試集時,那台最好每種答案都有。')}</p>
          </Card>

          <Card title={t('旗標(這些畫面的對應標籤不會用來訓練)')}>
            {flags.length ? (
              <div className="flex flex-col divide-y divide-stone-100 text-sm">
                {flags.map(([f, n]) => (
                  <div key={f} className="py-1.5 flex justify-between gap-4">
                    <span><code className="text-xs text-stone-500 mr-2">{f}</code>{flagText(f, stateNames)}</span>
                    <span className="num">{n}</span>
                  </div>
                ))}
              </div>
            ) : <Empty>{t('沒有旗標')}</Empty>}
          </Card>
        </>
      ) : <Card><Empty>{t('還沒有標籤,按右上角「產生標籤」')}</Empty></Card>}

    </Page>
  )
}
