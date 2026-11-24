import { t } from '../i18n'
import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, type PlanTaskDef } from '../api'
import { Button, Card, ErrorText } from '../components/ui'

const input = 'border border-stone-300 rounded-md px-2 py-1 text-sm bg-white'

/** 可以排的事: what the people at the operation panel may put on each device's week (每台行程表) - a sub-script, where
 *  they pick each of its parameters from, and the settings a pick stands for while an entry is kept (維持到下一筆) */
export function PlanTasksEditor() {
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['plan_tasks'], queryFn: api.planTasks })
  const [items, setItems] = useState<PlanTaskDef[] | null>(null)
  useEffect(() => { if (q.data && items === null) setItems(q.data.tasks) }, [q.data, items])
  const save = useMutation({ mutationFn: (x: PlanTaskDef[]) => api.planTasksSave(x), onSuccess: r => { setItems(r.tasks); qc.invalidateQueries({ queryKey: ['plan_tasks'] }) } })
  if (!q.data || !items) return <span className="text-sm text-stone-500">{t('讀取中…')}</span>
  const info = q.data
  const set = (k: number, f: (x: PlanTaskDef) => void) => setItems(xs => xs!.map((x, j) => { if (j !== k) return x; const y = JSON.parse(JSON.stringify(x)) as PlanTaskDef; f(y); return y }))
  const sources = [...info.catalogs.map(c => ({ v: `catalog:${c.id}`, l: t('目錄:{name}', { name: c.name }) })), ...info.lists.map(l => ({ v: `list:${l.id}`, l: t('清單:{title}', { title: l.title }) }))]
  const subOf = (x: PlanTaskDef) => info.subs.find(s => s.id === x.sub)
  const fill = (x: PlanTaskDef) => {                 // the sub's parameters, each with where it is picked from (guessed)
    const s = subOf(x)
    x.params = Object.fromEntries((s?.params ?? []).filter(p => p.required || x.params[p.name]).map(p => [p.name, x.params[p.name] ?? {
      label: p.label, from: p.from_list ? `list:${p.from_list}` : '', sets: [] }]))
  }
  return (
    <Card title={t('可以排的事')} extra={<span className="flex gap-2">
      <Button variant="ghost" onClick={() => setItems(xs => [...xs!, (() => { const x: PlanTaskDef = { id: `task${xs!.length + 1}`, name: '', sub: info.subs[0]?.id ?? '', params: {} }; fill(x); return x })()])}>{t('+ 新增')}</Button>
      <Button variant="primary" disabled={save.isPending} onClick={() => save.mutate(items)}>{t('儲存')}</Button></span>}>
      <div className="flex flex-col gap-3 text-sm">
        <span className="text-xs text-stone-500">{t('使用者在操作面板的「每台行程表」替每台排一週的行程時,從這裡選要做哪件事。每件事是一個子腳本:它要的參數讓使用者從清單或目錄選;勾「維持時代替」的設定,選「維持到下一筆」時,之後的動作(例如出狀況後回到原位)都照這筆選的。')}</span>
        <ErrorText error={save.error} />
        {!items.length && <span className="text-stone-500">{t('還沒有:按「+ 新增」')}</span>}
        {items.map((x, k) => (
          <div key={k} className="rounded-md border border-stone-200 p-3 flex flex-col gap-2">
            <div className="flex flex-wrap items-center gap-2">
              <input className={`${input} w-48`} placeholder={t('名稱,例如「換人去某區」')} value={x.name} onChange={e => set(k, y => { y.name = e.target.value })} />
              <input className={`${input} w-32 font-mono`} title={t('代號(小寫英文、數字、底線)')} value={x.id} onChange={e => set(k, y => { y.id = e.target.value })} />
              {t('執行')}<select className={input} value={x.sub} onChange={e => set(k, y => { y.sub = e.target.value; y.params = {}; fill(y) })}>
                {info.subs.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}</select>
              <label className="flex items-center gap-1">{t('最長')}<input type="number" className={`${input} w-16`} value={x.max_minutes ?? 60} onChange={e => set(k, y => { y.max_minutes = Number(e.target.value) || 60 })} />{t('分鐘')}</label>
              <span className="flex-1" />
              <button className="text-xs text-stone-400 hover:text-red-700" onClick={() => setItems(xs => xs!.filter((_y, j) => j !== k))}>{t('刪除')}</button>
            </div>
            {Object.entries(x.params).map(([pn, p]) => (
              <div key={pn} className="flex flex-wrap items-center gap-2 pl-4 text-xs">
                <span className="font-mono text-stone-500">{pn}</span>
                <input className={`${input} w-28`} value={p.label} onChange={e => set(k, y => { y.params[pn].label = e.target.value })} title={t('使用者看到的名稱')} />
                {t('從')}<select className={input} value={p.from} onChange={e => set(k, y => { y.params[pn].from = e.target.value })}>
                  <option value="">{t('(選選項來源)')}</option>{sources.map(o => <option key={o.v} value={o.v}>{o.l}</option>)}</select>
                <span className="text-stone-600">{t('維持時代替:')}</span>
                {info.settings.filter(s => s.scope === 'device' && (s.pick_from === p.from || (p.sets ?? []).includes(s.id))).map(s => <label key={s.id} className="flex items-center gap-1">
                  <input type="checkbox" checked={(p.sets ?? []).includes(s.id)} onChange={e => set(k, y => { const ss = new Set(y.params[pn].sets ?? []); if (e.target.checked) ss.add(s.id); else ss.delete(s.id); y.params[pn].sets = [...ss] })} />{s.label}</label>)}
                {!info.settings.some(s => s.scope === 'device' && s.pick_from === p.from) && <span className="text-stone-400">{t('(沒有從同一個來源選的設定)')}</span>}
              </div>
            ))}
            {!Object.keys(x.params).length && <span className="pl-4 text-xs text-stone-500">{t('這個子腳本不用選參數:只能「只做一次」')}</span>}
          </div>
        ))}
      </div>
    </Card>
  )
}
