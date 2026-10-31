import { useMutation } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { t } from '../../i18n'
import type { AnswerValue, ScriptRule, ScriptsInfo, StateDef, SubStep, WbDraft, WbWhy } from '../../api'
import { Button, Card, ErrorText } from '../ui'

const input = 'border border-stone-300 rounded-md px-2 py-1 text-sm bg-white'
export interface RulePick { state: StateDef; value: AnswerValue | number }
type Act = 'call' | 'tap' | 'notify' | 'goto'

/** "When it looks like this, do that": the ticked states as they read now become a rule of a main script, in the draft. */
export function RuleForm({ picks, info, why, doc, onSave, onDone }: {
  picks: RulePick[]; info: ScriptsInfo; why: WbWhy[]; doc: WbDraft; onSave: (d: WbDraft) => Promise<void>; onDone: () => void
}) {
  const here = why[0]?.script
  const [script, setScript] = useState(here ?? info.scripts[0]?.id ?? '')
  const sc = info.scripts.find(s => s.id === script)
  // the situation it is in now, when that main script is on this device
  const nowSit = useMemo(() => sc?.situations.find(x => x.name === why.find(w => w.script === script)?.situation)?.id, [sc, why, script])
  const [sit, setSit] = useState('')
  const situation = sc?.situations.some(x => x.id === sit) ? sit : nowSit ?? sc?.initial ?? ''
  const [name, setName] = useState('')
  const [hold, setHold] = useState(2)
  const [cooldown, setCooldown] = useState(30)
  const [first, setFirst] = useState(true)
  const [act, setAct] = useState<Act>('call')
  const [sub, setSub] = useState('')
  const [button, setButton] = useState('')
  const [text, setText] = useState('')
  const [goto_, setGoto] = useState('')
  const [ops, setOps] = useState<Record<string, string>>({})
  const conds = picks.map(p => {
    const named = p.state.type === 'class'
    const op = ops[p.state.id] ?? (named ? 'is' : 'gte')
    return { state: p.state.id, op, value: p.value, ...(hold ? { for: hold } : {}) }
  })
  const add = useMutation({
    mutationFn: async () => {
      const taken = new Set([...info.scripts.flatMap(s => s.situations.flatMap(x => (x.rules ?? []).map(r => r.id))), ...doc.rules.map(r => r.rule.id)])
      let n = 1
      while (taken.has(`rule_wb_${n}`)) n++
      const step: SubStep = act === 'call' ? { type: 'call', sub, args: {} }
        : act === 'tap' ? { type: 'tap', target: { button } }
        : act === 'goto' ? { type: 'goto', situation: goto_ }
        : { type: 'notify', text }
      const rule: ScriptRule = { id: `rule_wb_${n}`, name: name.trim(), enabled: true, when: [conds as never], do: [step], cooldown }
      await onSave({ ...doc, rules: [...doc.rules, { script, situation, first, rule }] })
    },
    onSuccess: onDone,
  })
  const ready = name.trim() && script && situation && (act === 'call' ? sub : act === 'tap' ? button : act === 'goto' ? goto_ : text.trim())
  return (
    <Card title={t('用勾選的組成規則')}>
      <div className="flex flex-col gap-2 text-sm">
        <div className="flex flex-col gap-1 text-xs">
          <span className="text-stone-500">{t('當畫面是這樣:')}</span>
          {picks.map(p => (
            <div key={p.state.id} className="flex items-center gap-2">
              <span className="flex-1 min-w-0 truncate">{p.state.name}</span>
              {p.state.type === 'class'
                ? <select className={input} value={ops[p.state.id] ?? 'is'} onChange={e => setOps({ ...ops, [p.state.id]: e.target.value })}><option value="is">{t('是')}</option><option value="is_not">{t('不是')}</option></select>
                : <select className={input} value={ops[p.state.id] ?? 'gte'} onChange={e => setOps({ ...ops, [p.state.id]: e.target.value })}><option value="gte">≥</option><option value="lte">≤</option></select>}
              <b>{p.state.classes?.find(c => c.value === p.value)?.name ?? (p.state.type === 'ratio' && typeof p.value === 'number' ? `${Math.round(p.value * 100)}%` : String(p.value))}</b>
            </div>
          ))}
          <label className="flex items-center gap-2 mt-1">{t('持續')}<input type="number" min={0} className={`${input} w-16 num`} value={hold} onChange={e => setHold(Number(e.target.value))} />{t('秒才算')}</label>
        </div>
        <div className="flex flex-col gap-1 text-xs">
          <span className="text-stone-500">{t('就做:')}</span>
          <div className="flex items-center gap-2 flex-wrap">
            <select className={input} value={act} onChange={e => setAct(e.target.value as Act)}>
              <option value="call">{t('執行子腳本')}</option><option value="tap">{t('點按鈕')}</option><option value="notify">{t('通知')}</option><option value="goto">{t('切換情境')}</option></select>
            {act === 'call' && <select className={`${input} flex-1 min-w-0`} value={sub} onChange={e => setSub(e.target.value)}><option value="">{t('(選子腳本)')}</option>{info.subs.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}</select>}
            {act === 'tap' && <select className={`${input} flex-1 min-w-0`} value={button} onChange={e => setButton(e.target.value)}><option value="">{t('(選按鈕)')}</option>{info.buttons.filter(b => !b.list).map(b => <option key={b.id} value={b.id}>{b.label}</option>)}</select>}
            {act === 'notify' && <input className={`${input} flex-1 min-w-0`} value={text} onChange={e => setText(e.target.value)} placeholder={t('要通知的話')} />}
            {act === 'goto' && <select className={`${input} flex-1 min-w-0`} value={goto_} onChange={e => setGoto(e.target.value)}><option value="">{t('(選情境)')}</option>{sc?.situations.map(x => <option key={x.id} value={x.id}>{x.name}</option>)}</select>}
          </div>
        </div>
        <div className="flex flex-col gap-1 text-xs">
          <span className="text-stone-500">{t('放在:')}</span>
          <div className="flex items-center gap-2 flex-wrap">
            <select className={input} value={script} onChange={e => setScript(e.target.value)}>{info.scripts.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}</select>
            <select className={input} value={situation} onChange={e => setSit(e.target.value)}>{sc?.situations.map(x => <option key={x.id} value={x.id}>{x.name}</option>)}</select>
            <label className="flex items-center gap-1"><input type="checkbox" checked={first} onChange={e => setFirst(e.target.checked)} />{t('排在最前面')}</label>
            <label className="flex items-center gap-1">{t('間隔')}<input type="number" min={0} className={`${input} w-16 num`} value={cooldown} onChange={e => setCooldown(Number(e.target.value))} />{t('秒')}</label>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <input className={`${input} flex-1 min-w-0`} placeholder={t('規則名稱')} value={name} onChange={e => setName(e.target.value)} />
          <Button variant="primary" disabled={!ready || add.isPending} onClick={() => add.mutate()}>{t('放進草稿')}</Button>
        </div>
        <ErrorText error={add.error} />
      </div>
    </Card>
  )
}
