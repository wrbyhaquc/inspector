import { t } from '../i18n'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../api'
import { dateTime } from '../lib/format'
import { Button, ErrorText } from './ui'

/** What an AI (over MCP) asked a person to decide: a main script going live on a device. Yes makes it so, no leaves it. */
export function AiRequests() {
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['aiRequests'], queryFn: api.aiRequests, refetchInterval: 10000 })
  const answer = useMutation({ mutationFn: ({ id, approve }: { id: string; approve: boolean }) => api.aiRequestAnswer(id, approve),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['aiRequests'] }); qc.invalidateQueries({ queryKey: ['scripts'] }); qc.invalidateQueries({ queryKey: ['nextSteps'] }) } })
  const open = (q.data?.items ?? []).filter(r => r.status === 'open')
  if (!open.length) return null
  return (
    <div className="flex flex-col gap-2">
      {open.map(r => (
        <div key={r.id} className="rounded-lg border-2 border-violet-300 bg-violet-50 px-4 py-3 flex flex-wrap items-center gap-3 text-sm">
          <div className="flex-1 min-w-0">
            <div className="font-semibold text-violet-950">{t('AI 要求讓「{script}」在「{device}」正式執行', { script: r.script_name, device: r.device_name })}</div>
            <div className="text-violet-900">{r.reason}</div>
            <div className="text-xs text-violet-700 num">{dateTime(r.t)}{' · '}{t('同意後它會真的動作;先在「詳細」看它試跑時會做什麼')}</div>
          </div>
          <Button variant="primary" disabled={answer.isPending} onClick={() => {
            if (confirm(t('讓「{script}」在「{device}」正式執行?', { script: r.script_name, device: r.device_name }))) answer.mutate({ id: r.id, approve: true })
          }}>{t('同意')}</Button>
          <Button disabled={answer.isPending} onClick={() => answer.mutate({ id: r.id, approve: false })}>{t('拒絕')}</Button>
        </div>
      ))}
      <ErrorText error={answer.error} />
    </div>
  )
}
