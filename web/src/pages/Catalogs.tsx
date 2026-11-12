import { t } from '../i18n'
import { useMutation } from '@tanstack/react-query'
import { useState, type ReactNode } from 'react'
import { api, type Catalog, type CatalogCall, type CatalogItem, type ScriptsInfo, type StateDef } from '../api'
import { Button, Card, Empty, ErrorText } from '../components/ui'
import { usePersistentState } from '../lib/persist'
import { shortLabel, splitFolder } from '../components/TreePicker'
import { ArgsEditor, CondEnv, CondGroups, defaultCond } from './Scripts'
import { useSchema } from '../lib/schema'

const input = 'border border-stone-300 rounded-md px-2 py-1 text-sm bg-white'
const clone = <T,>(x: T): T => JSON.parse(JSON.stringify(x))
const freeId = (prefix: string, taken: string[]) => { let n = taken.length + 1; while (taken.includes(`${prefix}${n}`)) n++; return `${prefix}${n}` }

/** Catalogs (目錄): named items to choose from - each one sub-script call with its arguments, filed in folders.
 *  A user setting of the kind "目錄的一項" lets the people running it choose one; the step "照目錄項目做" runs it. */
export function CatalogsEditor({ info, devices, onSaved }: { info: ScriptsInfo; devices: string[]; onSaved: () => void }) {
  const [draft, setDraft] = useState<Catalog[] | null>(null)
  const cats = draft ?? info.catalogs
  const [cid, setCid] = usePersistentState('library.catalog', cats[0]?.id ?? '')
  const cat = cats.find(c => c.id === cid) ?? cats[0]
  const [edit, setEdit] = useState<{ item: CatalogItem; isNew: boolean } | null>(null)
  const [shut, setShut] = usePersistentState<string[]>('library.catalogShut', [])
  const [q, setQ] = useState('')
  const save = useMutation({ mutationFn: () => api.catalogsSave(cats), onSuccess: () => { setDraft(null); onSaved() } })
  const change = (fn: (c: Catalog) => void) => setDraft(cats.map(c => { if (c.id !== cat?.id) return c; const x = clone(c); fn(x); return x }))
  const subName = (id: string) => info.subs.find(s => s.id === id)?.name ?? id
  const how = (x: CatalogItem) => x.calls.map(c => subName(c.sub)).join(' → ')
  const sch = useSchema()
  const states = (sch.data?.schema.states ?? []).filter(s => s.type === 'class' || s.type === 'ratio' || s.type === 'number')
  const addCatalog = () => {
    const id = freeId('catalog_', cats.map(c => c.id))
    setDraft([...cats, { id, name: t('新的目錄'), items: [] }])
    setCid(id)
  }
  const w = q.trim().toLowerCase().split(/\s+/).filter(Boolean)
  const items = (cat?.items ?? []).filter(x => !w.length || w.every(k => `${x.folder ?? ''} ${x.name} ${how(x)}`.toLowerCase().includes(k)))
  const folders = [...new Set((cat?.items ?? []).flatMap(x => splitFolder(x.folder).map((_, i, a) => a.slice(0, i + 1).join('/'))))]
    .sort((x, y) => x.localeCompare(y, 'zh-Hant', { numeric: true }))
  const tree = (path: string[]): ReactNode => {
    const here = path.join('/')
    const subs = folders.filter(f => { const p = splitFolder(f); return p.length === path.length + 1 && p.slice(0, -1).join('/') === here })
    const inside = (f: string) => items.filter(x => { const g = splitFolder(x.folder).join('/'); return g === f || g.startsWith(f + '/') }).length
    return <>
      {subs.filter(f => inside(f) > 0).map(f => {
        const open = w.length > 0 || !shut.includes(`${cat!.id}:${f}`)
        return (
          <div key={f} className="flex flex-col">
            <button className="flex items-center gap-1.5 py-1.5 border-b border-stone-100 text-sm font-medium text-stone-700 text-left" style={{ paddingLeft: path.length * 18 }}
              onClick={() => setShut(s => s.includes(`${cat!.id}:${f}`) ? s.filter(x => x !== `${cat!.id}:${f}`) : [...s, `${cat!.id}:${f}`])}>
              <span className="w-3 text-[10px] text-stone-400">{open ? '▼' : '▶'}</span>📁 {splitFolder(f).pop()}
              <span className="text-xs text-stone-400 font-normal num">{inside(f)}</span>
            </button>
            {open && tree(splitFolder(f))}
          </div>
        )
      })}
      {items.filter(x => splitFolder(x.folder).join('/') === here).map(x => (
        <div key={x.id} className="flex items-center gap-3 border-b border-stone-100 py-1.5 text-sm" style={{ paddingLeft: path.length * 18 }}>
          <span className="font-medium min-w-0 truncate">{shortLabel(x.name, splitFolder(x.folder))}</span>
          <span className="text-xs text-amber-800 truncate min-w-0">→ {how(x)}</span>
          {x.here && <span className="text-xs text-emerald-700 whitespace-nowrap" title={t('會先看是不是已經在那裡;做完後確認到了')}>{t('✓ 會確認')}</span>}
          {x.note && <span className="text-xs text-stone-500 truncate min-w-0">{x.note}</span>}
          <span className="flex-1" />
          <Button variant="ghost" onClick={() => setEdit({ item: clone(x), isNew: false })}>{t('修改')}</Button>
          <Button variant="ghost" onClick={() => { if (confirm(t('刪除「{name}」?(要按「儲存」才會生效)', { name: x.name }))) change(c => { c.items = c.items.filter(y => y.id !== x.id) }) }}>{t('刪除')}</Button>
        </div>
      ))}
    </>
  }
  return (
    <div className="flex flex-col gap-4 min-w-0">
      <Card title={t('目錄')} extra={<span className="flex gap-2">
        {cats.length > 0 && <select className={input} value={cat?.id} onChange={e => setCid(e.target.value)}>{cats.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}</select>}
        <Button onClick={addCatalog}>{t('+ 新增目錄')}</Button>
        {draft && <Button variant="ghost" onClick={() => { setDraft(null); setEdit(null) }}>{t('放棄修改')}</Button>}
        {draft && <Button variant="primary" disabled={save.isPending} onClick={() => save.mutate()}>{save.isPending ? t('儲存中…') : t('儲存')}</Button>}
      </span>}>
        <div className="flex flex-col gap-3 text-sm">
          <p className="text-xs text-stone-500">{t('目錄是一份「可以選的項目」:每一項有自己的名字,和到時候要做的事(依序呼叫哪些子腳本、各帶什麼參數)。例如「要去的地點」:有的直接傳送、有的要先進某個地方再走過去,各用各的子腳本。在「使用者設定」加一個「目錄的一項」讓使用者選,腳本裡用「照目錄項目做」就會照選的那一項去做。')}</p>
          <ErrorText error={save.error} />
          {!cat ? <Empty>{t('還沒有目錄')}</Empty> : <>
            <div className="flex flex-wrap items-center gap-2">
              <input className={`${input} w-48`} value={cat.name} placeholder={t('目錄名稱')} onChange={e => change(c => { c.name = e.target.value })} />
              <input className={`${input} w-36 font-mono`} value={cat.id} disabled={info.catalogs.some(c => c.id === cat.id)} title={t('腳本用代號找到它,存了之後不能改')}
                onChange={e => { const id = e.target.value; setDraft(cats.map(c => c === cat ? { ...c, id } : c)); setCid(id) }} />
              <input className={`${input} flex-1 min-w-[200px]`} value={cat.description ?? ''} placeholder={t('說明(可不填)')} onChange={e => change(c => { c.description = e.target.value })} />
              <Button variant="ghost" onClick={() => { if (confirm(t('刪除目錄「{name}」和裡面的 {n} 項?(要按「儲存」才會生效)', { name: cat.name, n: cat.items.length }))) setDraft(cats.filter(c => c !== cat)) }}>{t('刪除目錄')}</Button>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <input className={`${input} w-56`} placeholder={t('搜尋名稱或資料夾…')} value={q} onChange={e => setQ(e.target.value)} />
              <Button onClick={() => setEdit({ isNew: true, item: { id: freeId('item_', cat.items.map(x => x.id)), name: '', folder: '', calls: [{ sub: info.subs[0]?.id ?? '', args: {} }] } })}
                disabled={!info.subs.length}>{t('+ 新增項目')}</Button>
              {!info.subs.length && <span className="text-xs text-amber-800">{t('先建立子腳本(每一項要用一個子腳本去做)')}</span>}
            </div>
            {!cat.items.length ? <Empty>{t('還沒有項目')}</Empty> : !items.length ? <Empty>{t('找不到')}</Empty> : <div className="flex flex-col">{tree([])}</div>}
          </>}
        </div>
      </Card>
      {edit && cat && <ItemForm key={edit.item.id} item={edit.item} isNew={edit.isNew} info={info} devices={devices} folders={folders} states={states}
        onCancel={() => setEdit(null)}
        onDone={it => { change(c => { c.items = edit.isNew ? [...c.items, it] : c.items.map(x => x.id === it.id ? it : x) }); setEdit(null) }} />}
    </div>
  )
}

function ItemForm({ item, isNew, info, devices, folders, states, onDone, onCancel }: {
  item: CatalogItem; isNew: boolean; info: ScriptsInfo; devices: string[]; folders: string[]; states: StateDef[]; onDone: (it: CatalogItem) => void; onCancel: () => void
}) {
  const [x, setX] = useState<CatalogItem>(item)
  const setCall = (k: number, c: CatalogCall | null) => setX(v => {
    const calls = [...v.calls]
    if (c) calls[k] = c; else calls.splice(k, 1)
    return { ...v, calls }
  })
  const move = (k: number, d: number) => setX(v => { const calls = [...v.calls]; [calls[k], calls[k + d]] = [calls[k + d], calls[k]]; return { ...v, calls } })
  const missing = x.calls.flatMap((c, k) => {
    const sub = info.subs.find(s => s.id === c.sub)
    if (!sub) return [t('第 {k} 段的子腳本', { k: k + 1 })]
    return (sub.params ?? []).filter(p => (c.args[p.name] ?? p.default) == null).map(p => x.calls.length > 1 ? t('第 {k} 段的{p}', { k: k + 1, p: p.label || p.name }) : (p.label || p.name))
  })
  const here = x.here ?? []
  return (
    <Card title={isNew ? t('新增項目') : t('修改「{name}」', { name: item.name })} extra={<span className="flex gap-2">
      <Button variant="ghost" onClick={onCancel}>{t('取消')}</Button>
      <Button variant="primary" disabled={!x.name.trim() || !x.calls.length || missing.length > 0} title={missing.length ? t('還要填:{p1}', { p1: missing.join(t('、')) }) : ''}
        onClick={() => onDone({ ...x, name: x.name.trim(), here: here.length ? here : undefined, here_wait: here.length ? x.here_wait : undefined })}>{t('好')}</Button>
    </span>}>
      <CondEnv.Provider value={{ info, devices, states }}>
      <div className="flex flex-col gap-3 text-sm">
        <div className="flex flex-wrap items-center gap-2">
          <input className={`${input} w-56`} placeholder={t('名稱,例如「北邊的田」')} value={x.name} onChange={e => setX({ ...x, name: e.target.value })} />
          <input className={`${input} w-48`} list="catalog-folders" placeholder={t('資料夾(可不填)')} value={x.folder ?? ''} onChange={e => setX({ ...x, folder: e.target.value })} />
          <datalist id="catalog-folders">{folders.map(f => <option key={f} value={f} />)}</datalist>
        </div>
        <div className="flex flex-col gap-2">
          <span className="text-stone-600">{t('要做的事:依序呼叫這些子腳本(例如先進到那個地方,再選區,再走過去)')}</span>
          {x.calls.map((c, k) => {
            const sub = info.subs.find(s => s.id === c.sub)
            return (
              <div key={k} className="rounded-md border border-stone-200 p-2 flex flex-col gap-2">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-xs text-stone-500 num">{k + 1}.</span>
                  <select className={input} value={c.sub} onChange={e => setCall(k, { sub: e.target.value, args: {} })}>
                    {info.subs.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
                  </select>
                  <span className="flex-1" />
                  {k > 0 && <Button variant="ghost" onClick={() => move(k, -1)} title={t('往前移')}>↑</Button>}
                  {k < x.calls.length - 1 && <Button variant="ghost" onClick={() => move(k, 1)} title={t('往後移')}>↓</Button>}
                  {x.calls.length > 1 && <Button variant="ghost" onClick={() => setCall(k, null)}>{t('刪除')}</Button>}
                </div>
                {sub && (sub.params ?? []).length > 0 &&
                  <ArgsEditor sub={sub} args={c.args} info={info} callerParams={[]} shared onChange={a => setCall(k, { ...c, args: a })} />}
              </div>
            )
          })}
          <Button onClick={() => setX({ ...x, calls: [...x.calls, { sub: info.subs[0]?.id ?? '', args: {} }] })} disabled={x.calls.length >= 10}>{t('+ 再加一段')}</Button>
        </div>
        <div className="flex flex-col gap-2 rounded-md border border-emerald-200 bg-emerald-50/40 p-2">
          <label className="flex items-center gap-2">
            <input type="checkbox" checked={here.length > 0} onChange={e => setX({ ...x, here: e.target.checked ? [[defaultCond(states)]] : undefined })} />
            <span className="font-medium">{t('怎麼看出已經在那裡')}</span>
          </label>
          <span className="text-xs text-stone-500">{t('設了之後:開始前先看,已經在那裡就不用再做(不會重複花費);做完後等它成立,沒等到就算這一項失敗(呼叫的地方可以改做別的)。例如:畫面上看得到那個地方才有的圖示。')}</span>
          {here.length > 0 && <>
            <CondGroups when={here} states={states} ops={info.ops} onChange={fn => setX(v => { const w = clone(v.here ?? []); fn(w); return { ...v, here: w } })} />
            <span className="flex items-center gap-2 text-xs text-stone-600">{t('做完後最多等')}
              <input type="number" min={1} max={600} className={`${input} w-20`} value={x.here_wait ?? 15} onChange={e => setX({ ...x, here_wait: Number(e.target.value) || 15 })} />{t('秒')}</span>
          </>}
        </div>
        <input className={input} placeholder={t('備註(可不填),例如要準備什麼')} value={x.note ?? ''} onChange={e => setX({ ...x, note: e.target.value })} />
        {missing.length > 0 && <span className="text-xs text-amber-800">{t('還要填:{p1}', { p1: missing.join(t('、')) })}</span>}
      </div>
      </CondEnv.Provider>
    </Card>
  )
}
