import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { t } from '../../i18n'
import { wbApi, type AnswerValue, type StateDef, type WbDraft, type WbStateRead } from '../../api'
import { Button, ErrorText } from '../ui'

const input = 'border border-stone-300 rounded-md px-2 py-1 text-sm bg-white'

/** A digits state learns its characters here: what is written on this picture, as a person reads it. */
function DigitsTeach({ state, device, frame, doc, part, onPart }: { state: StateDef; device: string; frame: string; doc?: WbDraft; part: string; onPart: (p: string) => void }) {
  const qc = useQueryClient()
  const [typed, setTyped] = useState('')
  const key = ['wbGlyphs', device, frame, state.id, JSON.stringify(state.source.params), doc?.refs.length]
  const view = useQuery({ queryKey: key, queryFn: () => wbApi.glyphs(device, frame, state.id) })
  const teach = useMutation({
    mutationFn: () => wbApi.glyphTeach(device, frame, state.id, typed),
    onSuccess: async () => { setTyped(''); await qc.invalidateQueries({ queryKey: ['wbDraft'] }) },
  })
  const d = view.data
  const size = [...typed.replace(/\s/g, '')].length
  const missing = d ? [...'0123456789'].filter(c => !d.taught.includes(c)) : []
  return (
    <div className="flex flex-col gap-1.5 text-xs">
      {d && !d.count && <p className="text-rose-700">{t('這塊找不到字元:框緊一點,只框住數字。')}</p>}
      {d && !!d.count && <span>{t('切出 {n} 個字元,現在讀成:', { n: d.count })}<b className="num">{d.text}</b>{d.value != null && <> → <b className="num">{d.value}</b></>}</span>}
      {d?.text.includes('/') && <label className="flex items-center gap-1.5">{t('數值用')}
        <select className={input} value={part} onChange={e => onPart(e.target.value)}>
          <option value="left">{t('「/」左邊')}</option><option value="right">{t('「/」右邊')}</option></select></label>}
      <div className="flex items-center gap-1.5">
        <input className={`${input} flex-1 min-w-0 num`} placeholder={t('這張上面寫的是…')} value={typed} onChange={e => setTyped(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter' && size === d?.count) teach.mutate() }} />
        <Button disabled={teach.isPending || !d || size !== d.count} onClick={() => teach.mutate()}>{t('教它')}</Button>
      </div>
      {!!size && d && size !== d.count && <p className="text-amber-800">{t('切出 {n} 個字元,你打了 {m} 個。', { n: d.count, m: size })}{t('切得不對的話:框緊一點,或到「要看的狀態」點選數字的顏色。')}</p>}
      {d && !!missing.length && <p className="text-stone-500">{t('還沒教過:{chars}。畫面上出現時再凍結一張教它。', { chars: missing.join(' ') })}</p>}
      <ErrorText error={view.error || teach.error} />
    </div>
  )
}

/** This picture was judged wrong: say what it really is (a test question), and tune a screen rule on the spot. */
export function StateFix({ state, read, device, frame, sel, doc, onSave, onFreeze, onClose }: {
  state: StateDef; read?: WbStateRead; device: string; frame: string | null; sel: number[] | null; doc?: WbDraft
  onSave: (d: WbDraft) => Promise<void>; onFreeze: () => void; onClose: () => void
}) {
  const p = state.source.params ?? {}
  const answer = useMutation({
    mutationFn: async (value: AnswerValue | number) => {
      const kept = (await wbApi.keep(device, frame!)).frame
      await onSave({ ...doc!, answers: [...doc!.answers.filter(a => !(a.frame === kept && a.state === state.id)), { state: state.id, value, frame: kept }] })
    },
  })
  const setParams = useMutation({
    mutationFn: (patch: Record<string, unknown>) => onSave({
      ...doc!, states: [...doc!.states.filter(s => s.id !== state.id), { ...state, source: { ...state.source, params: { ...p, ...patch } } }],
    }),
  })
  const addRef = useMutation({
    mutationFn: async (value: AnswerValue) => {
      const roi = state.rois.find(r => r.id === p.roi) ?? state.rois[0]
      const kept = (await wbApi.keep(device, frame!)).frame
      await onSave({ ...doc!, refs: [...doc!.refs, { state: state.id, value, frame: kept, box: roi.box }] })
    },
  })
  const answered = doc?.answers.find(a => a.state === state.id && a.frame.endsWith(`__${frame}.png`))
  const box = sel && sel[2] >= 4 && sel[3] >= 4 ? sel : null
  return (
    <div className="mt-2 rounded-md border border-stone-300 bg-stone-50 p-2 flex flex-col gap-2 text-sm">
      <div className="flex items-center gap-2"><b className="flex-1">{state.name}</b><button className="text-xs text-stone-500 underline" onClick={onClose}>{t('收起')}</button></div>
      {!frame ? <div className="flex items-center gap-2 text-xs text-stone-600">{t('要修正,先凍結這一張。')}<Button onClick={onFreeze}>{t('⏸ 凍結這一張')}</Button></div> : state.source.rule === 'digits' ? <DigitsTeach state={state} device={device} frame={frame} doc={doc} part={String(p.part ?? 'all')} onPart={part => setParams.mutate({ part })} /> : <>
        <div className="flex flex-wrap items-center gap-1.5 text-xs">
          <span className="text-stone-600">{t('這張其實是:')}</span>
          {state.type === 'class'
            ? state.classes?.map(c => <Button key={String(c.value)} variant={answered?.value === c.value ? 'primary' : 'default'} disabled={answer.isPending} onClick={() => answer.mutate(c.value)}>{c.name}</Button>)
            : <input type="number" step="any" className={`${input} w-24`} defaultValue={answered?.value as number | undefined} onKeyDown={e => { if (e.key === 'Enter') answer.mutate(Number((e.target as HTMLInputElement).value)) }} placeholder={t('按 Enter')} />}
          {answered && <span className="text-emerald-700">{t('已放進草稿')}</span>}
        </div>
        <p className="text-xs text-stone-500">{state.source.kind === 'rule' && state.source.rule
          ? t('答案會變成考題,用來檢查這條規則準不準。')
          : t('這個狀態靠模型判斷:答案會變成考題和學習資料,到「學習」重新訓練後才會變聰明。')}</p>
        {state.source.rule === 'color_ratio' && <div className="flex flex-col gap-1 text-xs">
          <span>{t('這張的顏色比例:')}<b className="num">{read?.ratio != null ? `${(read.ratio * 100).toFixed(1)}%` : '—'}</b></span>
          <label className="flex items-center gap-2">{t('至少這麼多算「{name}」', { name: state.classes?.find(c => c.value === p.high_value)?.name ?? '' })}
            <input type="number" min={0} max={100} step={0.5} className={`${input} w-20 num`} defaultValue={Number(p.high_min ?? 0) * 100} key={`h${p.high_min}`}
              onBlur={e => { const v = Number(e.target.value) / 100; if (v !== p.high_min) setParams.mutate({ high_min: v }) }} />%</label>
          <label className="flex items-center gap-2">{t('最多這麼少算「{name}」', { name: state.classes?.find(c => c.value === p.low_value)?.name ?? '' })}
            <input type="number" min={0} max={100} step={0.5} className={`${input} w-20 num`} defaultValue={Number(p.low_max ?? 0) * 100} key={`l${p.low_max}`}
              onBlur={e => { const v = Number(e.target.value) / 100; if (v !== p.low_max) setParams.mutate({ low_max: v }) }} />%</label>
        </div>}
        {state.source.rule === 'template' && <div className="flex flex-col gap-1 text-xs">
          {read?.scores && <span className="text-stone-600">{t('這張和參考圖的相似度:')}{Object.entries(read.scores).map(([k, v]) => `${state.classes?.find(c => String(c.value) === k)?.name ?? k} ${Math.round(v * 100)}%`).join(t('、'))}</span>}
          <div className="flex flex-wrap items-center gap-1"><span className="text-stone-600">{t('把這張的範圍加成參考圖:')}</span>
            {state.classes?.map(c => <Button key={String(c.value)} variant="ghost" disabled={addRef.isPending} onClick={() => addRef.mutate(c.value)}>{c.name}</Button>)}</div>
        </div>}
        {box && <p className="text-xs text-stone-500">{t('要改它看的範圍:到「這個位置」分頁按「範圍改到這裡」。')}</p>}
      </>}
      <ErrorText error={answer.error || setParams.error || addRef.error} />
    </div>
  )
}
