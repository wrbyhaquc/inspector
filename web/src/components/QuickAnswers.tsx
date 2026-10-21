import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api, type AnswerValue, type StateDef } from '../api'
import { COLORS } from '../lib/schema'
import { Button } from './ui'
import { Zoom } from './FrameView'
import { t } from '../i18n'
import { words } from '../lib/project'

const input = 'border border-stone-300 rounded-md px-2 py-1 text-sm bg-white'

/** 答題: answer this one state on frames picked by session and time (test questions, not reference pictures).
 * A frame already used as a reference picture cannot be a question: the rule would be graded on its own answer key. */
export default function QuickAnswers({ s, box, pad = 0 }: { s: StateDef; box: number[]; pad?: number }) {
  const qc = useQueryClient()
  const sessions = useQuery({ queryKey: ['sessions'], queryFn: api.sessions })
  const [src, setSrc] = useState<{ session: string; device: string; offset: number } | null>(null)
  const frames = useQuery({
    queryKey: ['qaFrames', src], enabled: !!src,
    queryFn: () => api.framesBrowse(src!.session, src!.device, src!.offset, 24),
  })
  const ans = useQuery({ queryKey: ['qaAnswers', s.id], queryFn: () => api.reviewAnswers(s.id) })
  const set = useMutation({
    mutationFn: (b: { frame: string; value: AnswerValue | null }) => api.reviewAnswerOne({ frame: b.frame, state: s.id, value: b.value }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['qaAnswers', s.id] }),
  })
  const sess = sessions.data?.find(x => x.id === src?.session)
  const classes = s.classes ?? []
  const counts = ans.data?.counts ?? {}
  const tpls = useQuery({ queryKey: ['ruleTemplates', s.id], queryFn: () => api.ruleTemplates(s.id), enabled: s.source?.rule === 'template' })
  const refs = new Set((tpls.data ?? []).map(tx => tx.frame))

  return (
    <section className="flex flex-col gap-2 rounded-md border border-sky-200 bg-sky-50/40 p-3">
      <div className="flex items-center gap-3 flex-wrap">
        <div className="font-medium text-stone-700">{t('答題(考題)')}</div>
        <span className="text-xs text-stone-600">{t('已經答的考題:{p1}(每種至少 3 題、總共至少 20 題,模型才算考過)', { p1: classes.map(c => `${c.name} ${counts[String(c.value)] ?? 0}`).join(t('、')) })}</span>
      </div>
      <div className="text-xs text-stone-500">{t('挑你錄這個狀態的那一段,一張一張按答案。這裡的答案是')}<b>{t('考題')}</b>{t('(用來檢查模型和規則準不準), 和上面的參考圖分開;已經拿去當參考圖的畫面不能出題。')}{pad > 0 && t('縮圖會多顯示容許偏移的範圍(三格都看得到),虛線是你框的那一格。')}</div>
      <div className="flex items-center gap-2 flex-wrap">
        <select className={input} value={src?.session ?? ''} onChange={e => {
          const sid = e.target.value
          const dv = sessions.data?.find(x => x.id === sid)?.devices[0]?.name
          setSrc(sid && dv ? { session: sid, device: dv, offset: 0 } : null)
        }}>
          <option value="">{t('(選場次)')}</option>
          {sessions.data?.map(x => <option key={x.id} value={x.id}>{t('場次 {id}', { id: x.id })}</option>)}
        </select>
        {src && sess && (
          <select className={input} value={src.device} onChange={e => setSrc({ ...src, device: e.target.value, offset: 0 })}>
            {sess.devices.map(d => <option key={d.name} value={d.name}>{d.name}</option>)}
          </select>
        )}
        {src && (
          <span className="flex items-center gap-2 text-xs text-stone-600">
            <Button variant="ghost" disabled={src.offset === 0} onClick={() => setSrc({ ...src, offset: Math.max(0, src.offset - 24) })}>{t('← 較早')}</Button>
            <span className="num">{t('第 {p1}~{p2} 張 / 共 {p3}', { p1: src.offset + 1, p2: Math.min(src.offset + 24, frames.data?.total ?? 0), p3: frames.data?.total ?? 0 })}</span>
            <Button variant="ghost" disabled={src.offset + 24 >= (frames.data?.total ?? 0)} onClick={() => setSrc({ ...src, offset: src.offset + 24 })}>{t('較晚 →')}</Button>
            <input type="range" min={0} max={Math.max(0, (frames.data?.total ?? 1) - 1)} step={24} value={src.offset}
              onChange={e => setSrc({ ...src, offset: Number(e.target.value) })} className="w-40" />
          </span>
        )}
      </div>
      {set.error && <div className="text-xs text-rose-700">{(set.error as Error).message}</div>}
      <div className="flex flex-wrap gap-2">
        {frames.data?.items.map(f => {
          const cur = ans.data?.answers[f]
          const isRef = refs.has(f)
          return (
            <div key={f} className={`flex flex-col gap-1 rounded border-2 p-0.5 ${cur !== undefined ? 'border-sky-400' : 'border-transparent'}`}>
              <div className={isRef ? 'opacity-40' : ''}><Zoom frame={f} box={box} scale={2} maxWidth={150} pad={pad} /></div>
              {isRef ? <span className="text-[11px] text-stone-500">{t('已是參考圖,不能出題')}</span> : (
                <div className="flex flex-wrap gap-1">
                  {classes.map(c => {
                    const on = cur !== undefined && JSON.stringify(cur) === JSON.stringify(c.value)
                    return (
                      <button key={String(c.value)} disabled={set.isPending}
                        onClick={() => set.mutate({ frame: f, value: on ? null : c.value })}
                        title={on ? t('再按一次取消') : undefined}
                        className={`px-2 py-0.5 rounded-full text-xs ${on ? `${COLORS[c.color]?.pill} ring-2 ring-stone-700` : 'bg-white border border-stone-300 text-stone-600'}`}>
                        {on ? '✔ ' : ''}{c.name}</button>
                    )
                  })}
                </div>
              )}
            </div>
          )
        })}
        {!src && <div className="text-xs text-stone-500">{t('先選場次和{device}', { device: words.device })}</div>}
      </div>
    </section>
  )
}
