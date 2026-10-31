import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { t } from '../../i18n'
import { api, wbApi, type ScriptsInfo, type WbDraft, type WbDraftView } from '../../api'
import { dateTime } from '../../lib/format'
import { useSchema } from '../../lib/schema'
import { dn } from '../../lib/sources'
import { ReplayView } from '../../pages/Scripts'
import { Button, Card, Empty, ErrorText } from '../ui'

const input = 'border border-stone-300 rounded-md px-2 py-1 text-sm bg-white'

function Row({ tag, text, onDelete }: { tag: string; text: string; onDelete: () => void }) {
  return (
    <div className="flex items-center gap-2 py-1">
      <span className="px-1.5 rounded bg-stone-100 text-xs shrink-0">{tag}</span>
      <span className="flex-1 min-w-0 truncate" title={text}>{text}</span>
      <button className="text-stone-400 hover:text-rose-600 shrink-0" title={t('從草稿拿掉')} onClick={onDelete}>✕</button>
    </div>
  )
}

/** Try the draft's rules on a recording: what the main script would have done (nothing is pressed). */
function ReplayRules({ doc }: { doc: WbDraft }) {
  const sessions = useQuery({ queryKey: ['sessions'], queryFn: api.sessions })
  const scripts = useQuery({ queryKey: ['scripts'], queryFn: api.scripts })
  const [sess, setSess] = useState('')
  const [job, setJob] = useState<string | null>(null)
  const res = useQuery({
    queryKey: ['replay', job], queryFn: () => api.replayResult(job!), enabled: !!job,
    refetchInterval: q => (q.state.data?.status === 'running' || !q.state.data ? 1500 : false),
  })
  const dev = sessions.data?.find(x => x.id === sess)?.devices[0]?.name
  const go = useMutation({
    mutationFn: () => {
      const sid = doc.rules[0].script
      const sc = JSON.parse(JSON.stringify(scripts.data!.scripts.find(s => s.id === sid)))
      for (const r of doc.rules.filter(x => x.script === sid)) {
        const sit = sc.situations.find((x: { id: string }) => x.id === r.situation)
        sit.rules = [{ ...r.rule, enabled: true }, ...(sit.rules ?? [])]
      }
      return api.replayStart({ session: sess, device: dev!, start: 0, minutes: 10, script: sc, sub_result: 'success' })
    },
    onSuccess: d => setJob(d.id),
  })
  const usesDraftState = doc.rules.some(r => doc.states.some(s => JSON.stringify(r.rule.when).includes(`"state":"${s.id}"`)))
  return (
    <div className="flex flex-col gap-2 text-xs">
      <div className="flex items-center gap-2 flex-wrap">
        <select className={input} value={sess} onChange={e => setSess(e.target.value)}><option value="">{t('(選一段錄影)')}</option>
          {sessions.data?.map(x => <option key={x.id} value={x.id}>{x.id}</option>)}</select>
        <Button disabled={!sess || !dev || go.isPending || res.data?.status === 'running'} onClick={() => go.mutate()}>{t('在錄影上重播規則')}</Button>
      </div>
      {usesDraftState && <p className="text-amber-800">{t('用到草稿狀態的規則,要套用狀態後才能重播。')}</p>}
      <ErrorText error={go.error || res.error} />
      {res.data?.status === 'running' && <span className="text-stone-500">{t('重播中…')}</span>}
      {res.data?.result && <ReplayView r={res.data.result} />}
    </div>
  )
}

/** Everything waiting to go into the design: what it is, what it affects, and applying all of it - or undoing it. */
export function DraftPanel({ view, info, onSave }: { view?: WbDraftView; info?: ScriptsInfo; onSave: (d: WbDraft) => Promise<void> }) {
  const qc = useQueryClient()
  const doc = view?.doc
  const [note, setNote] = useState('')
  const [enable, setEnable] = useState(false)
  const history = useQuery({ queryKey: ['wbApplied'], queryFn: wbApi.applied })
  const refresh = () => {
    for (const k of ['wbDraft', 'wbApplied', 'schema', 'scripts', 'wbFrame', 'wbWhy']) qc.invalidateQueries({ queryKey: [k] })
  }
  const apply = useMutation({ mutationFn: () => wbApi.apply(note, enable), onSuccess: () => { setNote(''); refresh() } })
  const undo = useMutation({ mutationFn: wbApi.undo, onSuccess: refresh })
  const tryIt = useMutation({ mutationFn: wbApi.draftTry })
  const schema = useSchema()
  const name = (sid: string) => doc?.states.find(s => s.id === sid)?.name ?? schema.data?.schema.states.find(s => s.id === sid)?.name ?? sid
  const scriptName = (sid: string) => info?.scripts.find(s => s.id === sid)?.name ?? sid
  const liveOn = Object.entries(view?.live ?? {}).filter(([, d]) => d.length)
  const count = doc ? doc.buttons.length + doc.states.length + doc.refs.length + doc.answers.length + doc.subs.length + doc.rules.length : 0
  const without = <K extends keyof WbDraft>(k: K, i: number) => ({ ...doc!, [k]: (doc![k] as unknown[]).filter((_, x) => x !== i) } as WbDraft)
  return (
    <div className="flex flex-col gap-3">
      <Card title={t('草稿')} extra={<span className="text-xs text-stone-500">{t('現在都還沒有存進專案')}</span>}>
        {!doc || !count ? <Empty>{t('還沒有東西。在畫面上框一塊、修正判斷、組規則,或教一次,都會先放在這裡。')}</Empty> : (
          <div className="flex flex-col text-sm divide-y divide-stone-100">
            {doc.buttons.map((r, i) => <Row key={r.button.id} tag={t('按鈕')} text={r.button.label} onDelete={() => onSave(without('buttons', i))} />)}
            {doc.states.map((s, i) => <Row key={s.id} tag={t('狀態')} text={s.name} onDelete={() => onSave({ ...without('states', i), refs: doc.refs.filter(r => r.state !== s.id) })} />)}
            {doc.refs.map((r, i) => <Row key={`${r.state}${i}`} tag={t('參考圖')} text={`${name(r.state)} → ${String(r.value)}`} onDelete={() => onSave(without('refs', i))} />)}
            {doc.answers.map((a, i) => <Row key={`${a.state}${a.frame}`} tag={t('考題')} text={`${name(a.state)} = ${String(a.value)}`} onDelete={() => onSave(without('answers', i))} />)}
            {doc.subs.map((s, i) => <Row key={s.id} tag={t('子腳本')} text={t('{name}({n} 步)', { name: s.name, n: s.steps.length })} onDelete={() => onSave(without('subs', i))} />)}
            {doc.rules.map((r, i) => <Row key={r.rule.id} tag={t('規則')} text={`${scriptName(r.script)} › ${r.rule.name}`} onDelete={() => onSave(without('rules', i))} />)}
          </div>
        )}
      </Card>
      {!!count && doc && <>
        {!!view?.impact.length && <Card title={t('會影響到')}>
          <div className="flex flex-col gap-1 text-xs">
            {view.impact.map(x => <div key={x.what}><b>{x.what}</b>:{x.users.length ? x.users.join(t('、')) : t('目前沒有地方用到')}</div>)}
          </div>
        </Card>}
        {(!!doc.states.length || !!doc.rules.length) && <Card title={t('先試試看')}>
          <div className="flex flex-col gap-2 text-xs">
            {!!doc.states.length && <>
              <p className="text-stone-500">{t('只用一張畫面做的狀態容易不穩。用錄影裡隨機的畫面算一次,看它是不是都合理:')}</p>
              <div><Button disabled={tryIt.isPending} onClick={() => tryIt.mutate()}>{tryIt.isPending ? t('計算中…') : t('在錄影畫面上算一次')}</Button></div>
              <ErrorText error={tryIt.error} />
              {tryIt.data && (tryIt.data.frames ? tryIt.data.items.map(r => <div key={r.state}><b>{r.name}</b>:{Object.entries(r.counts).map(([k, n]) => `${k} ${n}`).join(t('、')) || t('都看不出來')}{r.unsure ? t('、看不出來 {n}', { n: r.unsure }) : ''}{t('(共 {n} 張)', { n: tryIt.data.frames })}</div>)
                : <p className="text-amber-800">{t('還沒有錄影可以驗證,這個狀態只在這張畫面上看過。')}</p>)}
            </>}
            {!!doc.rules.length && <ReplayRules doc={doc} />}
          </div>
        </Card>}
        <Card title={t('套用')}>
          <div className="flex flex-col gap-2 text-sm">
            {view?.problems.map(p => <p key={p} className="text-xs text-rose-700">{p}</p>)}
            {!!doc.rules.length && <div className="flex flex-col gap-1 text-xs rounded-md border border-stone-200 p-2">
              <label className="flex items-start gap-1.5"><input type="radio" checked={!enable} onChange={() => setEnable(false)} className="mt-0.5" />{t('規則先存著、不啟用(建議):到「腳本」頁看過再打開')}</label>
              <label className="flex items-start gap-1.5"><input type="radio" checked={enable} onChange={() => setEnable(true)} className="mt-0.5" />{t('規則馬上啟用')}</label>
              {enable && liveOn.map(([sid, d]) => <p key={sid} className="text-rose-700 font-medium">{t('「{name}」正在 {devices} 正式執行:條件成立就會真的動作。', { name: scriptName(sid), devices: d.map(dn).join(t('、')) })}</p>)}
            </div>}
            <input className={input} placeholder={t('這次改了什麼(版本說明,可不填)')} value={note} onChange={e => setNote(e.target.value)} />
            <Button variant="primary" disabled={apply.isPending || !!view?.problems.length} onClick={() => apply.mutate()}>{apply.isPending ? t('套用中…') : t('全部套用')}</Button>
            <p className="text-xs text-stone-500">{t('全部成功才生效;有一項不行就全部退回。套用後可以整批退回。')}</p>
            <ErrorText error={apply.error} />
          </div>
        </Card>
      </>}
      {apply.isSuccess && <p className="text-sm text-emerald-700">{t('已經套用。')}</p>}
      {!!history.data?.items.length && <Card title={t('套用紀錄')}>
        <div className="flex flex-col divide-y divide-stone-100 text-xs">
          {history.data.items.map(r => (
            <div key={r.id} className="flex items-center gap-2 py-1">
              <span className="num text-stone-500 shrink-0">{dateTime(r.t)}</span>
              <span className="flex-1 min-w-0 truncate">{r.note || t('{n} 項', { n: Object.values(r.counts ?? {}).reduce((a, b) => a + b, 0) })}</span>
              {r.undone ? <span className="text-stone-400">{t('已退回')}</span>
                : <Button variant="ghost" disabled={undo.isPending} onClick={() => { if (confirm(t('把這次套用全部退回?'))) undo.mutate(r.id) }}>{t('退回')}</Button>}
            </div>
          ))}
        </div>
        <ErrorText error={undo.error} />
        {!!undo.data?.failed.length && <p className="text-xs text-rose-700 mt-1">{undo.data.failed.join('; ')}</p>}
      </Card>}
    </div>
  )
}
