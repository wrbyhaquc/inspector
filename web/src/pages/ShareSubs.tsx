import { t } from '../i18n'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api, type ScriptsInfo, type ShareAnalysis } from '../api'
import { Button, Card, Empty, ErrorText, Pill } from '../components/ui'
import { dateTime } from '../lib/format'
import { useSchema } from '../lib/schema'

const input = 'border border-stone-300 rounded-md px-2 py-1 text-sm bg-white'

/** Export sub-scripts as one file / text, and import one: references are matched to this project before saving. */
export function ShareSubs({ info }: { info: ScriptsInfo }) {
  return (
    <div className="flex flex-col gap-5">
      <ExportCard info={info} />
      <ImportCard info={info} />
    </div>
  )
}

function ExportCard({ info }: { info: ScriptsInfo }) {
  const [sel, setSel] = useState<string[]>([])
  const [withCalls, setWithCalls] = useState(true)
  const [note, setNote] = useState('')
  const exp = useMutation({ mutationFn: () => api.shareExport(sel, withCalls) })
  const text = exp.data ? JSON.stringify(exp.data, null, 1) : ''
  const download = () => {
    const a = document.createElement('a')
    a.href = URL.createObjectURL(new Blob([text], { type: 'application/json' }))
    const names = exp.data!.subs.map(s => s.name).slice(0, 3).join('_')
    a.download = t('子腳本_{names}.inspector.json', { names })
    a.click()
    URL.revokeObjectURL(a.href)
  }
  return (
    <Card title={t('分享子腳本')} extra={<span className="text-xs text-stone-500">{t('對方匯入時,按鈕、狀態、清單會對應到他自己的')}</span>}>
      <div className="flex flex-col gap-3 text-sm">
        <div className="flex flex-wrap gap-2">
          {info.subs.map(s => (
            <label key={s.id} className={`flex items-center gap-1.5 border rounded-md px-2 py-1 cursor-pointer ${sel.includes(s.id) ? 'border-stone-800 bg-stone-50' : 'border-stone-200'}`}>
              <input type="checkbox" checked={sel.includes(s.id)} onChange={() => setSel(x => x.includes(s.id) ? x.filter(y => y !== s.id) : [...x, s.id])} />{s.name}
            </label>
          ))}
        </div>
        <label className="flex items-center gap-1.5 text-xs"><input type="checkbox" checked={withCalls} onChange={e => setWithCalls(e.target.checked)} />
          {t('連同它呼叫的子腳本一起分享(建議)')}</label>
        <div className="flex gap-2 items-center">
          <Button variant="primary" disabled={!sel.length || exp.isPending} onClick={() => { setNote(''); exp.mutate() }}>{t('產生分享檔')}</Button>
          {exp.data && <>
            <Button onClick={download}>{t('下載檔案')}</Button>
            <Button onClick={() => navigator.clipboard?.writeText(text).then(() => setNote(t('已複製,可以直接貼給對方'))).catch(() => setNote(t('瀏覽器不允許複製,請下載檔案')))}>{t('複製文字')}</Button>
          </>}
          {note && <span className="text-xs text-emerald-700">{note}</span>}
        </div>
        <ErrorText error={exp.error} />
        {exp.data && <p className="text-xs text-stone-500">{t('包含 {length} 個子腳本({p2})、{length2} 個按鈕、用到的狀態 {length3} 個。輸出的網址不會放進去。', { length: exp.data.subs.length, p2: exp.data.subs.map(s => s.name).join(t('、')), length2: Object.keys(exp.data.buttons).length, length3: Object.keys(exp.data.states).length })}</p>}
      </div>
    </Card>
  )
}

function ImportCard({ info }: { info: ScriptsInfo }) {
  const qc = useQueryClient()
  const [text, setText] = useState('')
  const [plan, setPlan] = useState<Record<string, Record<string, string>>>({})
  const ana = useMutation({
    mutationFn: () => api.shareAnalyze(JSON.parse(text)),
    onSuccess: a => setPlan({
      subs: Object.fromEntries(a.subs.map(s => [s.id, s.exists ? 'overwrite' : 'new'])),
      buttons: Object.fromEntries(a.buttons.map(b => [b.id, b.match || (b.can_create ? 'create' : '')])),
      states: Object.fromEntries(a.states.map(s => [s.id, s.match])),
      lists: Object.fromEntries(a.lists.map(s => [s.id, s.match])),
      outputs: Object.fromEntries(a.outputs.map(s => [s.id, s.match])),
    }),
  })
  const imp = useMutation({
    mutationFn: () => api.shareImport(JSON.parse(text), plan),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['scripts'] }),
  })
  const a: ShareAnalysis | undefined = ana.data
  const setP = (kind: string, id: string, v: string) => setPlan(p => ({ ...p, [kind]: { ...(p[kind] ?? {}), [id]: v } }))
  const states = useSchema().data?.schema.states ?? []
  const row = (kind: string, id: string, label: string, opts: [string, string][], extra?: string) => (
    <div key={`${kind}:${id}`} className="flex flex-wrap items-center gap-2">
      <span className="w-56 truncate" title={id}>{label} <code className="text-[11px] text-stone-400">{id}</code></span>
      <span className="text-stone-400">→</span>
      <select className={`${input} ${plan[kind]?.[id] ? '' : 'border-rose-400'}`} value={plan[kind]?.[id] ?? ''} onChange={e => setP(kind, id, e.target.value)}>
        <option value="">{t('(請選擇)')}</option>
        {opts.map(([v, tx]) => <option key={v} value={v}>{tx}</option>)}
      </select>
      {extra && <span className="text-xs text-stone-500">{extra}</span>}
    </div>
  )
  const readFile = (f: File | undefined) => { if (f) f.text().then(tx => { setText(tx); ana.reset(); imp.reset() }) }
  return (
    <Card title={t('匯入子腳本')}>
      <div className="flex flex-col gap-3 text-sm">
        <div className="flex flex-wrap items-center gap-2">
          <input id="share-file" type="file" accept=".json,application/json" onChange={e => readFile(e.target.files?.[0])} className="text-xs" />
          <span className="text-xs text-stone-500">{t('或把對方給的文字貼在下面')}</span>
        </div>
        <textarea id="share-text" className="font-mono text-xs border border-stone-300 rounded-md p-2 h-28" value={text} spellCheck={false}
          onChange={e => { setText(e.target.value); ana.reset(); imp.reset() }} placeholder='{"kind": "inspector.subscripts", ...}' />
        <div><Button disabled={!text.trim() || ana.isPending} onClick={() => ana.mutate()}>{t('讀取')}</Button></div>
        <ErrorText error={ana.error} />
        {a && <>
          <p className="text-xs text-stone-500">{t('來自「{p1}」', { p1: a.from ?? '?' })}{a.exported ? t(',{p1} 匯出', { p1: dateTime(a.exported) }) : ''}。
            {a.screen && (a.screen[0] !== a.here_screen[0] || a.screen[1] !== a.here_screen[1]) &&
              <span className="text-amber-700"> {t('對方的畫面座標是 {p1},這裡是 {p2}:新建的按鈕位置可能不對,建議對應到自己的按鈕。', { p1: a.screen.join('×'), p2: a.here_screen.join('×') })}</span>}</p>
          {a.missing_subs.length > 0 && <ErrorText error={t('分享檔裡少了它呼叫的子腳本:{p1}(請對方勾「連同它呼叫的子腳本」重新分享)', { p1: a.missing_subs.join(t('、')) })} />}
          <section className="flex flex-col gap-1.5">
            <div className="font-medium text-stone-700">{t('子腳本')}</div>
            {a.subs.map(s => (
              <div key={s.id} className="flex flex-wrap items-center gap-2">
                <span className="w-56 truncate">{s.name} <code className="text-[11px] text-stone-400">{s.id}</code></span>
                {s.exists && <Pill tone="amber">{t('這裡已有「{here_name}」', { here_name: s.here_name })}</Pill>}
                <select className={input} value={['new', 'overwrite', 'skip'].includes(plan.subs?.[s.id] ?? '') ? plan.subs?.[s.id] : 'rename'}
                  onChange={e => setP('subs', s.id, e.target.value === 'rename' ? `${s.id}_2` : e.target.value)}>
                  {!s.exists && <option value="new">{t('新增')}</option>}
                  {s.exists && <option value="overwrite">{t('覆蓋這裡的(存成新版本,舊版本可還原)')}</option>}
                  <option value="rename">{t('用新代號另存')}</option>
                  {s.exists && <option value="skip">{t('不匯入,用這裡的')}</option>}
                </select>
                {!['new', 'overwrite', 'skip'].includes(plan.subs?.[s.id] ?? '') &&
                  <input className={`${input} w-40 font-mono`} value={plan.subs?.[s.id] ?? ''} onChange={e => setP('subs', s.id, e.target.value)} />}
              </div>
            ))}
          </section>
          {a.buttons.length > 0 && <section className="flex flex-col gap-1.5">
            <div className="font-medium text-stone-700">{t('按鈕')}</div>
            {a.buttons.map(b => row('buttons', b.id, b.label,
              [...(b.can_create ? [['create', b.has_image ? t('用對方的建立新按鈕(含找圖的圖片)') : t('用對方的建立新按鈕')] as [string, string]] : []),
                ...info.buttons.filter(x => !x.list).map(x => [x.id, x.label] as [string, string])]))}
          </section>}
          {a.states.length > 0 && <section className="flex flex-col gap-1.5">
            <div className="font-medium text-stone-700">{t('狀態(條件看的)')}</div>
            {a.states.map(s => row('states', s.id, s.name, states.map(x => [x.id, x.name] as [string, string]), s.match ? '' : t('這裡沒有同名的狀態,請選一個對應的')))}
          </section>}
          {a.lists.length > 0 && <section className="flex flex-col gap-1.5">
            <div className="font-medium text-stone-700">{t('清單')}</div>
            {a.lists.map(s => row('lists', s.id, s.title, info.lists.map(x => [x.id, x.title] as [string, string])))}
          </section>}
          {a.outputs.length > 0 && <section className="flex flex-col gap-1.5">
            <div className="font-medium text-stone-700">{t('輸出')}</div>
            {a.outputs.map(s => row('outputs', s.id, s.name, info.outputs.map(x => [x.id, x.name] as [string, string]), t('輸出的網址不會分享,請對應到自己的')))}
          </section>}
          {(a.variables.some(v => !v.exists) || a.settings.some(s => !s.exists)) && <p className="text-xs text-stone-500">
            {t('會自動新增:')}{[...a.variables.filter(v => !v.exists).map(v => t('變數「{p1}」', { p1: v.label || v.name })), ...a.settings.filter(s => !s.exists).map(s => t('使用者設定「{p1}」', { p1: s.label || s.id }))].join(t('、'))}</p>}
          <div className="flex items-center gap-2">
            <Button variant="primary" disabled={imp.isPending || a.missing_subs.length > 0} onClick={() => imp.mutate()}>{t('匯入')}</Button>
            <span className="text-xs text-stone-500">{t('匯入前會用腳本規範檢查;有任何一個不通過就什麼都不存。')}</span>
          </div>
          <ErrorText error={imp.error} />
          {imp.data && <div className="text-xs text-emerald-700">{t('已匯入:{p1}', { p1: imp.data.saved.join(t('、')) })}
            {imp.data.created_buttons.length > 0 && t(';新建按鈕 {p1}', { p1: imp.data.created_buttons.join(t('、')) })}
            {imp.data.added_variables.length > 0 && t(';新增變數 {p1}', { p1: imp.data.added_variables.join(t('、')) })}
            {imp.data.added_settings.length > 0 && t(';新增使用者設定 {p1}', { p1: imp.data.added_settings.join(t('、')) })}</div>}
        </>}
        {!a && !text && <Empty>{t('選一個分享檔,或貼上文字後按「讀取」')}</Empty>}
      </div>
    </Card>
  )
}
