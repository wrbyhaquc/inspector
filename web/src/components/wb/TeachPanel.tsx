import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { t } from '../../i18n'
import { api, wbApi, type LibButton, type ScriptsInfo, type SubScript, type SubStep, type WbDraft, type WbStep, type WbTeach } from '../../api'
import { dn } from '../../lib/sources'
import { Button, Card, Empty, ErrorText, Pill } from '../ui'
import { boxAround, newButtonId } from './HerePanel'

const input = 'border border-stone-300 rounded-md px-2 py-1 text-sm bg-white'
export interface Press { op: 'tap' | 'long_press' | 'swipe' | 'back' | 'text'; x?: number; y?: number; x2?: number; y2?: number; ms?: number; text?: string }

/** what a person chose for a written-down step: how to find the spot, and what to wait for after it */
interface Choice {
  target: string                 // an existing button's id | "xy" | "new"
  newName: string
  after: string                  // "state:<id>:<json value>" | "wait" | "none"
  seconds: number
}

const OP_TEXT: Record<string, string> = { tap: t('點擊'), long_press: t('長按'), swipe: t('滑動'), back: t('返回鍵'), text: t('輸入文字') }

function defaultChoice(s: WbStep): Choice {
  const c = s.changes.find(x => !x.own)          // something that changes by itself would not wait for this step
  return {
    target: s.buttons?.[0]?.id ?? 'xy', newName: '',
    after: c ? `state:${c.state}:${JSON.stringify(c.value)}` : s.gap != null && s.gap >= 1 ? 'wait' : 'none',
    seconds: Math.max(1, Math.round(s.gap ?? 1)),
  }
}

/** The written-down steps -> a sub-script's steps, and the new buttons they need. */
export async function buildSteps(device: string, steps: WbStep[], choices: Record<string, Choice>, taken: Set<string>, known: { sub: string; from: number; to: number }[]) {
  const out: SubStep[] = []
  const buttons: { button: LibButton; frame?: string }[] = []
  for (let i = 0; i < steps.length; i++) {
    const hit = known.find(k => k.from === i)
    if (hit) {
      out.push({ type: 'call', sub: hit.sub, args: {} } as SubStep)
      i = hit.to
      const c = choices[steps[i].id]
      pushAfter(out, steps[i], c)
      continue
    }
    const s = steps[i]
    const c = choices[s.id] ?? defaultChoice(s)
    let target: SubStep['target'] = s.x != null ? { x: s.x, y: s.y } : undefined
    if (c.target !== 'xy' && c.target !== 'new') target = { button: c.target }
    if (c.target === 'new' && s.x != null) {
      const b: LibButton = { id: newButtonId(c.newName, taken), label: c.newName.trim(), x: s.x, y: s.y!, find: !!s.frame, box: boxAround(s.x, s.y!), search: 60, min_score: 0.8 }
      taken.add(b.id)
      buttons.push({ button: b, frame: s.frame ? (await wbApi.keep(device, s.frame)).frame : undefined })
      target = { button: b.id }
    }
    if (s.op === 'tap') out.push({ type: 'tap', target })
    else if (s.op === 'long_press') out.push({ type: 'long_press', target, ms: s.ms ?? 800 })
    else if (s.op === 'swipe') out.push({ type: 'swipe', from: { x: s.x, y: s.y }, to: { x: s.x2, y: s.y2 }, ms: s.ms ?? 400 })
    else if (s.op === 'back') out.push({ type: 'back' })
    else if (s.op === 'text') out.push({ type: 'input_text', text: s.text ?? '' })
    pushAfter(out, s, c)
  }
  return { steps: out, buttons }
}

function pushAfter(out: SubStep[], s: WbStep, c0?: Choice) {
  const c = c0 ?? defaultChoice(s)
  if (c.after.startsWith('state:')) {
    const [, state, ...rest] = c.after.split(':')
    out.push({ type: 'wait_until', when: [[{ state, op: 'is', value: JSON.parse(rest.join(':')) }]] as never, timeout: Math.max(10, Math.round((s.gap ?? 5) * 3)), on_timeout: 'fail' })
  } else if (c.after === 'wait') out.push({ type: 'wait', seconds: c.seconds })
}

function StepCard({ s, n, c, onChange, onForget, known, busy }: {
  s: WbStep; n: number; c: Choice; onChange: (c: Choice) => void; onForget: () => void; known?: string; busy: boolean
}) {
  const hasSpot = s.x != null && s.op !== 'swipe'
  return (
    <div className="rounded-md border border-stone-200 p-2 flex flex-col gap-1.5 text-xs">
      <div className="flex items-center gap-2">
        <b className="num">{n}.</b><b>{OP_TEXT[s.op] ?? s.op}</b>
        {s.x != null && <span className="num text-stone-500">{s.x}, {s.y}{s.x2 != null ? ` → ${s.x2}, ${s.y2}` : ''}</span>}
        {s.text && <span className="truncate">「{s.text}」</span>}
        {s.by === 'hand' && <Pill>{t('直接操作')}</Pill>}
        <span className="flex-1" />
        <button className="text-stone-400 hover:text-rose-600" disabled={busy} title={t('這步不要')} onClick={onForget}>✕</button>
      </div>
      {known && <span className="text-sky-800">{known}</span>}
      {hasSpot && !known && <div className="flex items-center gap-1.5 flex-wrap">
        <span className="text-stone-500">{t('點哪裡:')}</span>
        <select className={input} value={c.target} onChange={e => onChange({ ...c, target: e.target.value })}>
          {s.buttons?.map(b => <option key={b.id} value={b.id}>{t('既有按鈕「{label}」', { label: b.label })}</option>)}
          <option value="xy">{t('固定位置')}</option>
          <option value="new">{t('存成新按鈕(會找圖)')}</option>
        </select>
        {c.target === 'new' && <input className={`${input} w-32`} placeholder={t('按鈕名稱')} value={c.newName} onChange={e => onChange({ ...c, newName: e.target.value })} />}
      </div>}
      <div className="flex items-center gap-1.5 flex-wrap">
        <span className="text-stone-500">{t('做完:')}</span>
        <select className={`${input} max-w-full`} value={c.after} onChange={e => onChange({ ...c, after: e.target.value })}>
          {s.changes.map(x => <option key={x.state} value={`state:${x.state}:${JSON.stringify(x.value)}`}>{t('等到「{name}」變成「{value}」', { name: x.name, value: x.value_name })}{x.own ? t('(沒人碰也會自己變)') : ''}</option>)}
          <option value="wait">{t('等幾秒')}</option>
          <option value="none">{t('不用等')}</option>
        </select>
        {c.after === 'wait' && <input type="number" min={0} step={0.5} className={`${input} w-16 num`} value={c.seconds} onChange={e => onChange({ ...c, seconds: Number(e.target.value) })} />}
      </div>
    </div>
  )
}

/** Teach it once: the job done on the device (on the picture or on the device itself) becomes the steps of a sub-script. */
export function TeachPanel({ device, teach, doc, info, onSave, onToDraft, pressing, onPress }: {
  device: string; teach?: WbTeach; doc?: WbDraft; info?: ScriptsInfo; onSave: (d: WbDraft) => Promise<void>; onToDraft: () => void; pressing: boolean; onPress: (p: Press) => void
}) {
  const qc = useQueryClient()
  const set = (d: WbTeach) => qc.setQueryData(['wbTeach', device], d)
  const active = !!teach?.active
  const [kept, setKept] = useState<WbTeach | null>(null)       // the steps after stopping, until they are saved
  useEffect(() => { setKept(null) }, [device])
  const data = active ? teach! : kept
  const steps = data?.steps ?? []
  const known = data?.known ?? []
  const [choices, setChoices] = useState<Record<string, Choice>>({})
  const [useKnown, setUseKnown] = useState<Set<string>>(new Set())
  const [text, setText] = useState('')
  const [name, setName] = useState('')
  const [into, setInto] = useState('')
  const start = useMutation({ mutationFn: () => wbApi.teachStart(device), onSuccess: d => { set(d); setKept(null); setChoices({}); setUseKnown(new Set()) } })
  const stop = useMutation({ mutationFn: () => wbApi.teachStop(device), onSuccess: d => { setKept(d); set({ ...d, active: false }) } })
  const forget = useMutation({ mutationFn: (id: string) => wbApi.teachForget(device, id), onSuccess: set })
  const resume = useMutation({
    mutationFn: () => api.shadowAct({ device, kind: 'resume' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['wbSees', device] }),
  })
  const chosen = known.filter(k => useKnown.has(`${k.sub}:${k.from}`))
  const save = useMutation({
    mutationFn: async () => {
      const taken = new Set([...(info?.buttons ?? []).map(b => b.id), ...(doc?.buttons ?? []).map(b => b.button.id)])
      const full = Object.fromEntries(steps.map(s => [s.id, choices[s.id] ?? defaultChoice(s)]))
      for (const s of steps) if (full[s.id].target === 'new' && !full[s.id].newName.trim()) throw new Error(t('第 {n} 步要替新按鈕取名字', { n: steps.indexOf(s) + 1 }))
      const built = await buildSteps(device, steps, full, taken, chosen)
      const old = info?.subs.find(s => s.id === into)
      let sub: SubScript
      if (old) {
        const { version: _v, created: _c, note: _n, outline: _o, ...bare } = old
        sub = { ...bare, steps: [...old.steps, ...built.steps] }
      } else {
        const ids = new Set([...(info?.subs ?? []).map(s => s.id), ...(doc?.subs ?? []).map(s => s.id)])
        sub = { id: newButtonId(name, ids).replace(/^button/, 'sub'), name: name.trim(), params: [], steps: built.steps, cleanup: [], timeout: 300 }
      }
      await onSave({ ...doc!, buttons: [...doc!.buttons, ...built.buttons], subs: [...doc!.subs.filter(s => s.id !== sub.id), sub] })
    },
    onSuccess: () => { setKept(null); setChoices({}); setName(''); setInto(''); onToDraft() },
  })
  const sees = active ? teach?.sees : undefined
  const held = !!(sees?.hold || sees?.hold_all)
  return (
    <div className="flex flex-col gap-3">
      <Card title={t('教一次')} extra={active ? <Button variant="danger" disabled={stop.isPending} onClick={() => stop.mutate()}>{t('■ 結束')}</Button>
        : <Button variant="primary" disabled={start.isPending} onClick={() => start.mutate()}>{steps.length ? t('● 重新教') : t('● 開始教')}</Button>}>
        <div className="flex flex-col gap-2 text-sm">
          {!active && <p className="text-xs text-stone-600">{t('實際做一次你要它做的事,做的每一步都會記下來,變成子腳本。開始後 {device} 的腳本會暫停,結束後由你按「繼續」。', { device: dn(device) })}</p>}
          {active && <>
            <p className="text-xs text-stone-600">{teach?.watching ? t('在左邊的畫面上按,或直接操作裝置本身,都會記下來。') : t('在左邊的畫面上按,就會真的送到裝置。(這個來源偵測不到直接操作)')}</p>
            {sees?.here && !held && <p className="text-xs text-rose-700 font-medium">{t('這台的腳本沒有暫停:先按「暫停」,不然會互相打架。')}</p>}
            <div className="flex items-center gap-2 flex-wrap">
              <Button disabled={pressing} onClick={() => onPress({ op: 'back' })}>{t('返回鍵')}</Button>
              <input className={`${input} flex-1 min-w-[8rem]`} placeholder={t('輸入文字(先點輸入框)')} value={text} onChange={e => setText(e.target.value)} />
              <Button disabled={pressing || !text} onClick={() => { onPress({ op: 'text', text }); setText('') }}>{t('送出')}</Button>
            </div>
          </>}
          {!active && sees === undefined && kept?.paused_here && <div className="flex items-center gap-2 text-xs rounded-md bg-amber-50 border border-amber-200 px-2 py-1.5">
            <span className="flex-1">{t('{device} 還在暫停中。', { device: dn(device) })}</span>
            <Button disabled={resume.isPending || resume.isSuccess} onClick={() => resume.mutate()}>{resume.isSuccess ? t('已繼續') : t('▶ 繼續')}</Button></div>}
          <ErrorText error={start.error || stop.error || forget.error || resume.error} />
        </div>
      </Card>
      {!!steps.length && <Card title={t('記下來的步驟')}>
        <div className="flex flex-col gap-2">
          {known.map(k => <label key={`${k.sub}:${k.from}`} className="flex items-center gap-1.5 text-xs rounded-md bg-sky-50 border border-sky-200 px-2 py-1.5">
            <input type="checkbox" checked={useKnown.has(`${k.sub}:${k.from}`)} onChange={e => setUseKnown(s => { const n = new Set(s); const id = `${k.sub}:${k.from}`; if (e.target.checked) n.add(id); else n.delete(id); return n })} />
            {t('第 {a}~{b} 步和子腳本「{name}」一樣,改成呼叫它', { a: k.from + 1, b: k.to + 1, name: k.name })}</label>)}
          {steps.map((s, i) => {
            const k = chosen.find(x => i >= x.from && i <= x.to)
            return <StepCard key={s.id} s={s} n={i + 1} c={choices[s.id] ?? defaultChoice(s)} busy={!active || forget.isPending}
              known={k ? t('由子腳本「{name}」處理', { name: k.name ?? '' }) : undefined}
              onChange={c => setChoices({ ...choices, [s.id]: c })} onForget={() => { if (active) forget.mutate(s.id); else setKept(v => v && { ...v, steps: v.steps.filter(x => x.id !== s.id) }) }} />
          })}
        </div>
      </Card>}
      {!active && !!steps.length && <Card title={t('存起來')}>
        <div className="flex flex-col gap-2 text-sm">
          <input className={input} placeholder={t('新子腳本的名稱')} value={name} disabled={!!into} onChange={e => setName(e.target.value)} />
          <label className="flex items-center gap-2 text-xs">{t('或接在既有子腳本後面:')}
            <select className={`${input} flex-1 min-w-0`} value={into} onChange={e => setInto(e.target.value)}><option value="">{t('(不要,新建一個)')}</option>
              {info?.subs.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}</select></label>
          <Button variant="primary" disabled={save.isPending || !doc || (!into && !name.trim())} onClick={() => save.mutate()}>{t('放進草稿')}</Button>
          <ErrorText error={save.error} />
        </div>
      </Card>}
      {!active && !steps.length && <Empty>{t('還沒有步驟。')}</Empty>}
    </div>
  )
}
