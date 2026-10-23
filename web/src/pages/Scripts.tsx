import { t } from '../i18n'
import { PageIntro } from '../components/PageIntro'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Fragment, createContext, useContext, useEffect, useRef, useState, type ReactNode } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import {
  api, buttonImageUrl, buttonSnapUrl, imageUrl, isRef, shadowLiveUrl, type AnswerValue, type ArgItem, type NumVal, type ValueRef, type ArgValue, type LibButton, type Script, type ScriptCond, type ScriptPoint, type ScriptRule,
  type ListInfo, type ReplayResult, type ScriptsInfo, type SettingDecl, type Situation, type StateDef, type SubLayout, type SubParam, type SubScript, type SubStep, type VarDef,
} from '../api'
import { Button, Card, Empty, ErrorText, Modal, MoreButton, Page, Pill } from '../components/ui'
import { clock, dateTime, sessionTime } from '../lib/format'
import { DropLine, DropTarget, Grip, moveInList } from '../lib/dnd'
import { usePersistentState } from '../lib/persist'
import { screen, words } from '../lib/project'
import { useSchema } from '../lib/schema'
import { dn, sourceIds } from '../lib/sources'

const clone = <T,>(v: T): T => JSON.parse(JSON.stringify(v))
const input = 'border border-stone-300 rounded-md px-2 py-1 text-sm bg-white'
const newId = (prefix: string, taken: string[]) => { let i = 1; while (taken.includes(`${prefix}${i}`)) i++; return `${prefix}${i}` }
type Sel = { kind: 'script' | 'sub'; id: string } | null
const GUARD = 'guards'
const allRules = (s: Script) => s.situations.flatMap(x => x.rules)

function strip<T extends { version?: number; created?: number; note?: string; outline?: string[] }>(s: T | null | undefined) {
  if (!s) return null
  const { version, created, note, outline, ...rest } = s   // eslint-disable-line @typescript-eslint/no-unused-vars
  return rest
}

export default function Scripts() {
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['scripts'], queryFn: api.scripts })
  const sch = useSchema()
  const states = (sch.data?.schema.states ?? []).filter(s => s.type === 'class' || s.type === 'ratio' || s.type === 'number')
  const [sel, setSel] = useState<Sel>(null)
  const [newScript, setNewScript] = useState<Script | null>(null)
  const [newSub, setNewSub] = useState<SubScript | null>(null)
  const info = q.data
  const guard = (info?.scripts ?? []).find(s => s.id === GUARD)
  const scripts = (info?.scripts ?? []).filter(s => s.id !== GUARD)
  const subs = info?.subs ?? []
  useEffect(() => { if (!sel && !newScript && !newSub && scripts.length) setSel({ kind: 'script', id: scripts[0].id }) }, [scripts, sel, newScript, newSub])

  const order = useMutation({ mutationFn: (ids: string[]) => api.scriptsOrder(ids), onSuccess: () => qc.invalidateQueries({ queryKey: ['scripts'] }) })
  const [find, setFind] = useState('')
  const addScript = () => {
    setSel(null); setNewSub(null)
    setNewScript({ id: newId('script_', scripts.map(s => s.id)), name: t('新主腳本'), description: '', enabled: true, devices: { '*': 'shadow' },
      situations: [{ id: 'main', name: t('一般'), rules: [] }], initial: 'main', otherwise: { type: 'none', text: t('不動作') } })
  }
  const addGuard = () => {
    setSel(null); setNewSub(null)
    setNewScript({ id: GUARD, name: t('全域守門規則'), description: t('每台{device}、每個主腳本之前都先檢查;例如出現錯誤畫面就全部停止、省電就暫停其他腳本。', { device: words.device }), enabled: true,
      devices: { '*': 'shadow' }, situations: [{ id: 'main', name: t('守門規則'), rules: [] }], initial: 'main', otherwise: { type: 'none', text: t('不動作') } })
  }
  const addSub = () => {
    setSel(null); setNewScript(null)
    setNewSub({ id: newId('sub_', subs.map(s => s.id)), name: t('新子腳本'), description: '', params: [], steps: [{ type: 'wait', seconds: 1 }], cleanup: [], timeout: 300 })
  }
  const pick = (s: Sel) => { setNewScript(null); setNewSub(null); setSel(s) }
  const fromTemplate = useMutation({
    mutationFn: (tid: string) => api.scriptTemplate(tid),
    onSuccess: r => {
      setSel(null)
      if (r.kind === 'script') { setNewSub(null); setNewScript(r.item as Script) }
      else if (r.kind === 'sub') { setNewScript(null); setNewSub(r.item as SubScript) }
      else {                                          // guard rules: add them to the (new or existing) guard rules
        const g: Script = clone(guard) ?? { id: GUARD, name: t('全域守門規則'), description: t('每台{device}、每個主腳本之前都先檢查。', { device: words.device }), enabled: true,
          devices: { '*': 'shadow' }, situations: [{ id: 'main', name: t('守門規則'), rules: [] }], initial: 'main', otherwise: { type: 'none', text: t('不動作') } }
        const taken = g.situations[0].rules.map(x => x.id)
        for (const rule of r.item as ScriptRule[]) { if (taken.includes(rule.id)) rule.id = newId(`${rule.id}_`, taken); g.situations[0].rules.push(rule); taken.push(rule.id) }
        setNewSub(null); setNewScript(g)
      }
    },
  })
  const [params, setParams] = useSearchParams()
  useEffect(() => {
    const sid = params.get('script'), tid = params.get('template')
    if (!info || (!sid && !tid)) return
    if (sid) pick({ kind: 'script', id: sid })
    if (tid) fromTemplate.mutate(tid)
    setParams({}, { replace: true })
  }, [info, params]) // eslint-disable-line react-hooks/exhaustive-deps
  const curScript = newScript ?? (sel?.kind === 'script' ? (sel.id === GUARD ? guard : scripts.find(s => s.id === sel.id)) : undefined)
  const curSub = newSub ?? (sel?.kind === 'sub' ? subs.find(s => s.id === sel.id) : undefined)
  const shadowQ = useQuery({ queryKey: ['shadow'], queryFn: api.shadowStatus })
  const deviceNames = sourceIds((shadowQ.data?.status.devices ?? []).map(d => d.name))

  return (
    <CondEnv.Provider value={{ info: info ?? null, devices: deviceNames, states }}>
    <Page title={t('腳本')} intro={<PageIntro id="scripts" what={t('子腳本是一件一件的動作;主腳本一直看著狀態,第一條成立的規則就做它的步驟。')} start={t('先新增子腳本把動作寫好,再新增主腳本,加規則:如果…就依序做…')} ch={8} />} desc={t('主腳本常駐執行,用「如果…就…」的規則決定要做什麼;多步驟的動作寫成子腳本,任何主腳本或子腳本都能呼叫(像函式一樣,可以帶參數)。同一台{device}同一時間只有一個腳本在操作,上面的主腳本優先。', { device: words.device })}>
      <ErrorText error={q.error || order.error} />
      <div className="grid grid-cols-[260px_1fr] gap-4 items-start">
        <div className="flex flex-col gap-3 sticky top-3 max-h-[calc(100vh-1.5rem)] overflow-auto">
          <input className={`${input} w-full shrink-0`} placeholder={t('搜尋腳本名稱、代號、說明…')} value={find} onChange={e => setFind(e.target.value)} />
          <div className="bg-white border border-stone-200 rounded-lg overflow-hidden shrink-0">
            {guard ? (
              <button onClick={() => pick({ kind: 'script', id: GUARD })} className={`w-full text-left px-3 py-2 border-b border-stone-100 ${sel?.id === GUARD && !newScript ? 'bg-rose-50' : 'hover:bg-stone-50'}`}>
                <div className="text-sm font-medium text-rose-800">{t('🛡 全域守門規則')}{!guard.enabled && <Pill>{t('停用')}</Pill>}</div>
                <div className="text-xs text-stone-500">{t('{length} 條 · 永遠最先檢查 · v{version}', { length: allRules(guard).length, version: guard.version })}</div>
              </button>
            ) : newScript?.id === GUARD ? <div className="px-3 py-2 border-b border-stone-100 bg-rose-50 text-sm font-medium text-rose-800">{t('🛡 全域守門規則(未儲存)')}</div>
              : <button onClick={addGuard} className="w-full text-left px-3 py-2 border-b border-stone-100 text-sm text-rose-700 hover:bg-rose-50">{t('+ 建立全域守門規則')}</button>}
            <div className="px-3 py-2 text-xs text-stone-500 border-b border-stone-100" title={t('同一台{device}上,上面的主腳本可以打斷下面主腳本正在跑的子腳本', { device: words.device })}>{t('主腳本(越上面越優先,拖拉 ⠿ 調整)')}</div>
            <MainList scripts={scripts} find={find} selected={sel?.kind === 'script' && !newScript ? sel.id : null} busy={order.isPending}
              onPick={id => pick({ kind: 'script', id })} onOrder={ids => order.mutate(ids)} />
            {newScript && newScript.id !== GUARD && <div className="px-3 py-2 border-b border-stone-100 bg-stone-100 text-sm font-medium">{t('{name}(未儲存)', { name: newScript.name })}</div>}
            <button onClick={addScript} className="w-full text-left px-3 py-2 text-sm text-stone-600 hover:bg-stone-50">{t('+ 新增主腳本')}</button>
          </div>
          <SubLibrary info={info} find={find} selected={sel?.kind === 'sub' && !newSub ? sel.id : null} onPick={id => pick({ kind: 'sub', id })}>
            {newSub && <div className="px-3 py-2 border-b border-stone-100 bg-stone-100 text-sm font-medium">{t('{name}(未儲存)', { name: newSub.name })}</div>}
            <button onClick={addSub} className="w-full text-left px-3 py-2 text-sm text-stone-600 hover:bg-stone-50">{t('+ 新增子腳本')}</button>
          </SubLibrary>
          <ErrorText error={fromTemplate.error} />
          <Link to="/library" className="shrink-0 bg-white border border-stone-200 rounded-lg px-3 py-2 hover:bg-stone-50 text-sm">
            <div className="text-xs text-stone-500">{t('按鈕、變數、範本')}</div>
            <div>{t('到「素材庫」→')}</div>
          </Link>
        </div>
        {!info ? <Card><Empty>{q.isLoading ? t('讀取中…') : t('讀取失敗')}</Empty></Card>
          : curScript ? <ScriptEditor key={`s:${curScript.id}:${curScript.version ?? 'new'}:${newScript ? allRules(newScript).length : ''}`}
              saved={newScript ? (newScript.id === GUARD && guard ? guard : null) : curScript} initial={curScript} info={info} states={states}
              priority={scripts.findIndex(s => s.id === curScript.id)}
              onSaved={s => { setNewScript(null); setSel({ kind: 'script', id: s.id }); qc.invalidateQueries({ queryKey: ['scripts'] }) }}
              onDeleted={() => { setNewScript(null); setSel(null); qc.invalidateQueries({ queryKey: ['scripts'] }) }} />
          : curSub ? <SubEditor key={`u:${curSub.id}:${curSub.version ?? 'new'}`} saved={newSub ? null : curSub} initial={curSub} info={info} states={states}
              onSaved={s => { setNewSub(null); setSel({ kind: 'sub', id: s.id }); qc.invalidateQueries({ queryKey: ['scripts'] }) }}
              onDeleted={() => { setNewSub(null); setSel(null); qc.invalidateQueries({ queryKey: ['scripts'] }) }} />
          : <Card><Empty>{t('選擇或新增一個主腳本或子腳本')}</Empty></Card>}
      </div>
    </Page>
    </CondEnv.Provider>
  )
}

const matches = (find: string, ...texts: (string | undefined)[]) => !find.trim() || texts.some(tx => (tx ?? '').toLowerCase().includes(find.trim().toLowerCase()))

/** main scripts in priority order; drag to change the priority (not while searching: the list is filtered then) */
function MainList({ scripts, find, selected, busy, onPick, onOrder }: {
  scripts: Script[]; find: string; selected: string | null; busy: boolean; onPick: (id: string) => void; onOrder: (ids: string[]) => void
}) {
  const [drag, setDrag] = useState<number | null>(null)
  const searching = !!find.trim()
  const drop = (to: number) => { if (drag == null) return; const ids = scripts.map(s => s.id); moveInList(ids, drag, to); setDrag(null); onOrder(ids) }
  return <>
    {scripts.map((s, i) => !matches(find, s.name, s.id, s.description) ? null : (
      <Fragment key={s.id}>
        <DropLine active={drag != null && !busy} onDrop={() => drop(i)} />
        <MainRow s={s} i={i} selected={selected === s.id} dragging={drag === i} canDrag={!searching && !busy}
          onPick={() => onPick(s.id)} onStart={() => setDrag(i)} onEnd={() => setDrag(null)} />
      </Fragment>
    ))}
    <DropLine active={drag != null && !busy} onDrop={() => drop(scripts.length)} />
  </>
}

function MainRow({ s, i, selected, dragging, canDrag, onPick, onStart, onEnd }: {
  s: Script; i: number; selected: boolean; dragging: boolean; canDrag: boolean; onPick: () => void; onStart: () => void; onEnd: () => void
}) {
  const ref = useRef<HTMLDivElement>(null)
  return (
    <div ref={ref} className={`flex items-stretch border-b border-stone-100 ${dragging ? 'opacity-40' : ''} ${selected ? 'bg-stone-100' : 'hover:bg-stone-50'}`}>
      {canDrag && <span className="flex items-center pl-1.5"><Grip rowRef={ref} onStart={onStart} onEnd={onEnd} title={t('拖拉來調整優先順序')} /></span>}
      <button onClick={onPick} className="flex-1 text-left px-2 py-2 min-w-0">
        <div className="text-sm font-medium flex items-center gap-2"><span className="text-xs text-stone-400 num">{i + 1}</span>{s.name}{!s.enabled && <Pill>{t('停用')}</Pill>}</div>
        <div className="text-xs text-stone-500">{s.situations.length > 1 ? t('{length} 個情境 · ', { length: s.situations.length }) : ''}{t('{length} 條規則 · v{version}', { length: allRules(s).length, version: s.version })}</div>
      </button>
    </div>
  )
}

/** The sub-script library in user-made groups (folders): drag a sub-script into a group or to another place in it.
 * Only how the page shows them - saving it never makes a new version of a sub-script. */
function SubLibrary({ info, find, selected, onPick, children }: {
  info: ScriptsInfo | undefined; find: string; selected: string | null; onPick: (id: string) => void; children: ReactNode
}) {
  const qc = useQueryClient()
  const subs = info?.subs ?? []
  const [lay, setLay] = useState<SubLayout>(() => info?.sub_layout ?? { groups: [], of: {}, order: [] })
  useEffect(() => { if (info?.sub_layout) setLay(info.sub_layout) }, [info?.sub_layout])
  const [closed, setClosed] = usePersistentState<string[]>('subs.closed_groups', [])
  const [drag, setDrag] = useState<string | null>(null)          // the sub-script being dragged
  const [dragGroup, setDragGroup] = useState<number | null>(null)
  const save = useMutation({
    mutationFn: (l: SubLayout) => api.subLayout(l),
    onSuccess: l => { setLay(l); qc.invalidateQueries({ queryKey: ['scripts'] }) },
    onError: () => qc.invalidateQueries({ queryKey: ['scripts'] }),
  })
  const commit = (fn: (l: SubLayout) => void) => { const n = clone(lay); fn(n); setLay(n); save.mutate(n) }
  const searching = !!find.trim()
  const byId = new Map(subs.map(s => [s.id, s]))
  const ordered = [...lay.order.filter(id => byId.has(id)), ...subs.map(s => s.id).filter(id => !lay.order.includes(id))]
  const groupOf = (id: string) => lay.groups.some(g => g.id === lay.of[id]) ? lay.of[id] : ''
  const members = (gid: string) => ordered.filter(id => groupOf(id) === gid)
  /** put sub-script `sid` into group `gid` ('' = not grouped), before `before` (or at the end of the group) */
  const place = (sid: string, gid: string, before: string | null) => commit(l => {
    if (gid) l.of[sid] = gid; else delete l.of[sid]
    const o = ordered.filter(x => x !== sid)
    const tail = members(gid).filter(x => x !== sid)
    const at = before ? o.indexOf(before) : tail.length ? o.indexOf(tail[tail.length - 1]) + 1 : o.length
    o.splice(at < 0 ? o.length : at, 0, sid)
    l.order = o
  })
  const addGroup = () => {
    const name = prompt(t('新群組的名稱'))?.trim()
    if (name) commit(l => { l.groups.push({ id: newId('g', l.groups.map(g => g.id)), name }) })
  }
  const rename = (i: number) => {
    const name = prompt(t('群組名稱'), lay.groups[i].name)?.trim()
    if (name && name !== lay.groups[i].name) commit(l => { l.groups[i].name = name })
  }
  const remove = (i: number) => {
    const g = lay.groups[i]
    if (!confirm(t('刪除群組「{name}」?裡面的子腳本會移到「未分類」,子腳本本身不會被刪除。', { name: g.name }))) return
    commit(l => { l.groups.splice(i, 1); for (const k of Object.keys(l.of)) if (l.of[k] === g.id) delete l.of[k] })
  }
  const toggle = (key: string) => setClosed(c => c.includes(key) ? c.filter(x => x !== key) : [...c, key])
  const dropSub = (gid: string, before: string | null) => { if (drag) place(drag, gid, before); setDrag(null) }
  const section = (gid: string, name: string, i: number | null) => {
    const ids = members(gid)
    const shown = ids.filter(id => matches(find, byId.get(id)?.name, id, byId.get(id)?.description))
    if (searching && !shown.length) return null
    const key = gid || '_none'
    const open = searching || !closed.includes(key)
    return (
      <div key={key} className={dragGroup != null && dragGroup === i ? 'opacity-40' : ''}>
        {i != null && <DropLine active={dragGroup != null} onDrop={() => { const from = dragGroup!; commit(l => { moveInList(l.groups, from, i) }); setDragGroup(null) }} />}
        <DropTarget active={!!drag} onDrop={() => dropSub(gid, null)} overClass="!bg-sky-100"
          className="flex items-center gap-1 px-2 py-1.5 bg-stone-50 border-b border-stone-100 text-xs text-stone-600 group">
          {i != null && !searching && <Grip onStart={() => setDragGroup(i)} onEnd={() => setDragGroup(null)} title={t('拖拉來調整群組順序')} />}
          <button className="flex-1 text-left flex items-center gap-1 font-medium" onClick={() => toggle(key)} disabled={searching}>
            <span className="w-3 text-stone-400">{open ? '▾' : '▸'}</span>{name}<span className="text-stone-400 font-normal num">({ids.length})</span>
          </button>
          {i != null && <span className="hidden group-hover:flex gap-1.5">
            <button className="text-stone-400 hover:text-stone-900" title={t('改名')} onClick={() => rename(i)}>✎</button>
            <button className="text-stone-400 hover:text-rose-700" title={t('刪除群組(子腳本不會被刪)')} onClick={() => remove(i)}>✕</button>
          </span>}
        </DropTarget>
        {open && ids.map(sid => {
          const s = byId.get(sid)!
          if (!matches(find, s.name, s.id, s.description)) return null
          return (
            <Fragment key={sid}>
              <DropLine active={!!drag && drag !== sid} onDrop={() => dropSub(gid, sid)} />
              <SubRow s={s} info={info!} selected={selected === sid} dragging={drag === sid} canDrag={!searching}
                onPick={() => onPick(sid)} onStart={() => setDrag(sid)} onEnd={() => setDrag(null)} />
            </Fragment>
          )
        })}
        {open && <DropLine active={!!drag} onDrop={() => dropSub(gid, null)} />}
        {open && !ids.length && !drag && <div className="px-3 py-1.5 text-xs text-stone-400 border-b border-stone-100">{t('把子腳本拖到這裡')}</div>}
      </div>
    )
  }
  return (
    <div className="bg-white border border-stone-200 rounded-lg overflow-hidden shrink-0">
      <div className="px-3 py-2 text-xs text-stone-500 border-b border-stone-100 flex items-center gap-2">
        <span className="flex-1">{t('子腳本庫(被呼叫用)')}</span>
        <button className="underline text-stone-700" onClick={addGroup} disabled={save.isPending}>{t('+ 新增群組')}</button>
      </div>
      <ErrorText error={save.error} />
      {lay.groups.map((g, i) => section(g.id, g.name, i))}
      {dragGroup != null && <DropLine active onDrop={() => { const from = dragGroup; commit(l => { moveInList(l.groups, from, l.groups.length) }); setDragGroup(null) }} />}
      {(members('').length > 0 || !lay.groups.length || !!drag) && section('', lay.groups.length ? t('未分類') : t('全部'), null)}
      {children}
    </div>
  )
}

function SubRow({ s, info, selected, dragging, canDrag, onPick, onStart, onEnd }: {
  s: SubScript; info: ScriptsInfo; selected: boolean; dragging: boolean; canDrag: boolean; onPick: () => void; onStart: () => void; onEnd: () => void
}) {
  const ref = useRef<HTMLDivElement>(null)
  return (
    <div ref={ref} className={`flex items-stretch border-b border-stone-100 ${dragging ? 'opacity-40' : ''} ${selected ? 'bg-stone-100' : 'hover:bg-stone-50'}`}>
      {canDrag && <span className="flex items-center pl-1.5"><Grip rowRef={ref} onStart={onStart} onEnd={onEnd} title={t('拖拉到其他群組或位置')} /></span>}
      <button onClick={onPick} className="flex-1 text-left px-2 py-2 min-w-0">
        <div className="text-sm font-medium">{s.name}{(s.params ?? []).length > 0 && <span className="text-xs text-stone-400 font-normal">({(s.params ?? []).map(p => p.label || p.name).join(t('、'))})</span>}</div>
        <div className="text-xs text-stone-500">{(info.used_by[s.id] ?? []).length ? t('{length} 處使用', { length: info.used_by[s.id].length }) : t('還沒有人使用')} · v{s.version}</div>
      </button>
    </div>
  )
}

/** variable definitions: counters and "last time" stamps used by conditions and the 設定變數 action */
export function VarsEditor({ info, onSaved }: { info: ScriptsInfo; onSaved: () => void }) {
  const [vs, setVs] = useState<VarDef[]>(() => clone(info.variables))
  const save = useMutation({ mutationFn: () => api.variablesSave(vs), onSuccess: onSaved })
  const dirty = JSON.stringify(vs) !== JSON.stringify(info.variables)
  const set = (i: number, fn: (v: VarDef) => void) => setVs(d => { const n = clone(d); fn(n[i]); return n })
  return (
    <Card title={t('變數')} extra={<Button variant="primary" disabled={!dirty || save.isPending} onClick={() => save.mutate()}>{save.isPending ? t('儲存中…') : t('儲存')}</Button>}>
      <div className="flex flex-col gap-3 text-sm">
        <p className="text-xs text-stone-500">{t('變數用來記住事情,例如「今天補貨了幾次」(用「設定變數」加 1)、「上次巡檢的時間」(用「記下現在時間」,再用條件「距離上次」判斷)。 目前的值在「執行」頁可以看到和修改。')}</p>
        <ErrorText error={save.error} />
        {vs.map((v, i) => (
          <div key={i} className="flex flex-wrap items-center gap-2 border-b border-stone-100 pb-2">
            <input className={`${input} w-32 font-mono`} placeholder={t('代號(英文)')} value={v.name} onChange={e => set(i, x => { x.name = e.target.value })} />
            <input className={`${input} w-36`} placeholder={t('顯示名稱')} value={v.label ?? ''} onChange={e => set(i, x => { x.label = e.target.value })} />
            <select className={input} value={v.scope} onChange={e => set(i, x => { x.scope = e.target.value as VarDef['scope'] })}>
              {Object.entries(info.var_scopes).map(([k, tx]) => <option key={k} value={k}>{tx}</option>)}
            </select>
            <select className={input} value={v.reset} onChange={e => set(i, x => { x.reset = e.target.value as VarDef['reset'] })}>
              {Object.entries(info.var_resets).map(([k, tx]) => <option key={k} value={k}>{tx}</option>)}
            </select>
            <label className="flex items-center gap-1 text-xs">{t('初始值')}<input type="number" className={`${input} w-20 num`} value={v.initial ?? 0} onChange={e => set(i, x => { x.initial = Number(e.target.value) })} /></label>
            <Button variant="ghost" onClick={() => setVs(d => d.filter((_, k) => k !== i))}>✕</Button>
          </div>
        ))}
        <button className="text-xs text-stone-700 underline self-start" onClick={() => setVs(d => [...d, { name: newId('v', d.map(x => x.name)), label: '', scope: 'device', reset: 'daily', initial: 0 }])}>{t('+ 新增變數')}</button>
      </div>
    </Card>
  )
}

/** name, note and the save / discard / delete buttons shared by both editors */
function SaveBar({ dirty, isNew, saving, error, savedText, onSave, onDiscard, onDelete }: {
  dirty: boolean; isNew: boolean; saving: boolean; error: unknown; savedText?: ReactNode
  onSave: (note: string) => void; onDiscard: () => void; onDelete: () => void
}) {
  const [note, setNote] = useState('')
  return (
    <>
      <div className="flex flex-wrap items-center gap-2">
        {dirty && <span className="text-xs text-amber-700">{t('● 有未儲存的修改')}</span>}
        {dirty && !isNew && <Button variant="ghost" onClick={onDiscard}>{t('放棄修改')}</Button>}
        <input value={note} onChange={e => setNote(e.target.value)} placeholder={t('這次修改的說明(產生新版本時記下)')} className={`${input} w-56`} />
        <Button variant="primary" onClick={() => onSave(note)} disabled={(!dirty && !isNew) || saving}
          title={t('只改了部署、啟用、規則的開關或次數限制:直接存,不產生新版本。改了情境、條件、動作:存成新版本')}>{saving ? t('儲存中…') : t('儲存')}</Button>
        <Button variant="ghost" onClick={onDelete}>{isNew ? t('放棄') : t('刪除')}</Button>
      </div>
      <SaveStatus error={error} text={savedText && !dirty ? savedText : null} />
    </>
  )
}

function SaveStatus({ error, text }: { error: unknown; text: ReactNode }) {
  return (
    <div className="basis-full flex flex-col gap-1 empty:hidden">
      {!!error && <ErrorText error={error} />}
      {text && <div className="text-sm text-emerald-700 bg-emerald-50 border border-emerald-200 rounded-md px-3 py-1.5">{text}</div>}
    </div>
  )
}

/** The editor's header stays on screen: what is being edited, save, and the tabs. */
function EditorHeader<T extends string>({ badge, title, tabs, tab, setTab, children }: {
  badge: ReactNode; title: ReactNode; tabs: [T, ReactNode][]; tab: T; setTab: (tx: T) => void; children: ReactNode
}) {
  return (
    <div className="sticky top-0 z-20 pt-3 bg-stone-50/95 backdrop-blur border-b border-stone-200 flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-2">
        {badge}{title}<span className="flex-1" />{children}
      </div>
      <div className="flex gap-1">
        {tabs.map(([k, tx]) => (
          <button key={k} onClick={() => setTab(k)}
            className={`px-4 py-2 text-sm -mb-px border-b-2 ${tab === k ? 'border-stone-900 text-stone-900 font-medium' : 'border-transparent text-stone-500 hover:text-stone-800'}`}>{tx}</button>
        ))}
      </div>
    </div>
  )
}

function History({ load, onLoad }: { load: () => Promise<{ version: number; created: number; note: string }[]>; onLoad: (v: number) => void }) {
  const hist = useQuery({ queryKey: ['history', load.toString()], queryFn: load })
  return (
    <Card title={t('版本紀錄')}>
      <div className="flex flex-col gap-1 text-xs max-h-56 overflow-auto">
        {hist.data?.slice().reverse().map(h => (
          <div key={h.version} className="flex gap-3 items-center border-b border-stone-100 py-1">
            <span className="font-medium w-10">v{h.version}</span><span className="text-stone-500 w-36">{dateTime(h.created)}</span>
            <span className="flex-1">{h.note}</span>
            <button className="underline text-stone-500" onClick={() => onLoad(h.version)}>{t('載入這個版本')}</button>
          </div>
        ))}
      </div>
      <p className="text-xs text-stone-500 mt-2">{t('載入後按「儲存」就等於還原(部署、開關、次數限制這些設定維持目前的,不會跟著倒回去)。')}</p>
    </Card>
  )
}

// ================================================================ main scripts
function ScriptEditor({ saved, initial, info, states, priority, onSaved, onDeleted }: {
  saved: Script | null; initial: Script; info: ScriptsInfo; states: StateDef[]; priority: number
  onSaved: (s: Script) => void; onDeleted: () => void
}) {
  const [s, setS] = useState<Script>(() => clone(initial))
  const onChange = (fn: (x: Script) => void) => setS(d => { const n = clone(d); fn(n); return n })
  const isNew = !saved
  const dirty = JSON.stringify(strip(s)) !== JSON.stringify(strip(saved))
  const save = useMutation({ mutationFn: (note: string) => api.scriptSave(strip(s) as Script, note), onSuccess: onSaved })
  const del = useMutation({ mutationFn: () => api.scriptDelete(s.id), onSuccess: onDeleted })
  const isGuard = s.id === GUARD
  const [cur, setCur] = useState(0)
  const [tab, setTab] = usePersistentState<'rules' | 'info' | 'test' | 'json' | 'history'>('scripts.tab', 'rules')
  const [open, setOpen] = useState<string | null>(null)              // the one rule being edited (the rest stay one line)
  const [dragRule, setDragRule] = useState<number | null>(null)      // index (in the current situation) of the rule being dragged
  const ci = Math.min(cur, s.situations.length - 1)
  const sit = s.situations[ci]
  const ids = allRules(s).map(r => r.id)
  const modes = (m?: string) => (info.modes[m ?? ''] ?? m ?? '').replace(/\(.*\)/, '')
  const deploy = [t('預設 {p1}', { p1: modes(s.devices['*'] ?? 'shadow') }), ...Object.entries(s.devices).filter(([k]) => k !== '*').map(([k, m]) => `${k} ${modes(m)}`)].join(' · ')
  const tx = tab === 'history' && isNew ? 'rules' : tab
  return (
    <div className="flex flex-col gap-4 min-w-0">
      <EditorHeader badge={<span className={`text-xs px-1.5 py-0.5 rounded ${isGuard ? 'bg-rose-700' : 'bg-stone-900'} text-white`}>{isGuard ? t('🛡 守門規則') : isNew ? t('主腳本') : t('主腳本 · 優先 #{n}', { n: priority + 1 })}</span>}
        title={<>
          <input className={`${input} font-medium w-56`} value={s.name} onChange={e => onChange(x => { x.name = e.target.value })} />
          <label className="text-sm flex items-center gap-1"><input type="checkbox" checked={s.enabled} onChange={e => onChange(x => { x.enabled = e.target.checked })} />{t('啟用')}</label>
        </>}
        tabs={[['rules', isGuard ? t('規則({length})', { length: sit.rules.length }) : t('情境與規則({length})', { length: allRules(s).length })], ['info', t('設定')], ['test', t('測試')], ['json', 'JSON'], ...(isNew ? [] : [['history', t('版本')] as ['history', string]])]}
        tab={tx} setTab={setTab}>
        <SaveBar dirty={dirty} isNew={isNew} saving={save.isPending} error={save.error || del.error}
          savedText={save.data && <>{save.data.settings_only ? <>{t('已儲存「{name}」的設定(部署、開關、次數限制):設計沒變,仍是 v{version}。', { name: save.data.name, version: save.data.version })}</>
            : <>{t('已儲存「{name}」v{version}。', { name: save.data.name, version: save.data.version })}</>}{t('腳本執行中的話會立刻套用,到')} <Link className="underline" to="/script">{t('執行')}</Link> {t('看結果。')}</>}
          onSave={note => save.mutate(note)} onDiscard={() => setS(clone(saved!))}
          onDelete={() => { if (isNew) onDeleted(); else if (confirm(t('刪除主腳本「{name}」?(舊版本會保留在 .deleted 資料夾)', { name: s.name }))) del.mutate() }} />
      </EditorHeader>

      {tx === 'json' && <JsonPanel kind="script" value={s} onApply={v => setS(v as Script)} />}
      {tx === 'rules' && <>
        {!isGuard && <SituationsCard s={s} cur={ci} setCur={c => { setCur(c); setOpen(null) }} info={info} onChange={onChange}
          dragging={dragRule != null} onDropRule={to => {
            const from = dragRule!
            setDragRule(null)
            onChange(x => { const [it] = x.situations[ci].rules.splice(from, 1); x.situations[to].rules.push(it) })
          }} />}
        <div className="flex flex-col gap-2">
          <div className="text-xs text-stone-500">{isGuard
            ? t('每台{device}、每個主腳本之前都先檢查,由上往下第一條符合的就依序做它的步驟。「停下這台」停掉這台的所有腳本,「暫停其他腳本」在條件成立時讓其他腳本都不動作。', { device: words.device })
            : t('這台{device}在「{name}」時,由上往下檢查,第一條符合的就依序做它的步驟。點一條規則展開編輯。', { device: words.device, name: sit.name })}</div>
          {sit.rules.map((r, i) => (
            <Fragment key={r.id}>
              <DropLine active={dragRule != null} onDrop={() => { const from = dragRule!; setDragRule(null); onChange(x => moveInList(x.situations[ci].rules, from, i)) }} />
              <RuleCard r={r} i={i} n={sit.rules.length} info={info} states={states} script={s} dragging={dragRule === i}
                open={open === r.id} onToggle={() => setOpen(o => o === r.id ? null : r.id)}
                onDragStart={() => setDragRule(i)} onDragEnd={() => setDragRule(null)}
                onChange={fn => onChange(x => fn(x.situations[ci].rules[i]))}
                onMove={d => onChange(x => { const rs = x.situations[ci].rules; const [it] = rs.splice(i, 1); rs.splice(i + d, 0, it) })}
                onDelete={() => onChange(x => { x.situations[ci].rules.splice(i, 1) })} />
            </Fragment>
          ))}
          <DropLine active={dragRule != null} onDrop={() => { const from = dragRule!; setDragRule(null); onChange(x => moveInList(x.situations[ci].rules, from, x.situations[ci].rules.length)) }} />
          <div className="flex flex-wrap items-center gap-3">
            <Button onClick={() => {
              const id = newId('r', ids)
              onChange(x => {
                const rs = x.situations[ci].rules
                rs.push({ id, name: t('規則 {p1}', { p1: rs.length + 1 }), enabled: true, cooldown: 10, when: [[defaultCond(states)]], do: [] })
              })
              setOpen(id)
            }}>{t('+ 新增規則')}</Button>
            <label className="flex items-center gap-2 text-sm text-stone-600">{t('都不符合時:')}
              <input className={input} value={s.otherwise?.text ?? t('不動作')} onChange={e => onChange(x => { x.otherwise = { type: 'none', text: e.target.value } })} /></label>
          </div>
        </div>
      </>}

      {tx === 'info' && (
        <Card title={t('設定')}>
          <div className="grid md:grid-cols-2 gap-3 text-sm">
            <label className="flex flex-col gap-1"><span className="text-stone-600">{t('代號(英文)')}</span>
              <input className={`${input} font-mono`} value={s.id} disabled={!isNew || isGuard} onChange={e => onChange(x => { x.id = e.target.value })} /></label>
            <label className="flex flex-col gap-1"><span className="text-stone-600">{t('說明')}</span>
              <input className={input} value={s.description ?? ''} onChange={e => onChange(x => { x.description = e.target.value })} /></label>
            <div className="md:col-span-2 flex flex-col gap-1">
              <span className="text-stone-600">{t('在哪些{device}執行', { device: words.device })}</span>
              <div>{deploy} <Link className="underline text-xs ml-2" to="/script">{t('到「執行 › 部署」修改')}</Link></div>
              <span className="text-xs text-stone-500">{t('所有腳本 × {device}在同一張表設定,一眼看出哪台跑什麼。', { device: words.device })}{isNew && t('新腳本預設是試跑(只記錄不點擊)。')}</span>
            </div>
          </div>
        </Card>
      )}

      {tx === 'test' && <>
        <TryRun s={s} states={states} />
        <ReplayCard draft={s} dirty={dirty} />
      </>}

      {tx === 'history' && !isNew && <History load={() => api.scriptHistory(s.id)} onLoad={v => api.scriptVersion(s.id, v).then(x => { setS(clone(x)); setTab('rules') })} />}
    </div>
  )
}

const OP_WORD: Record<string, string> = { is: '=', is_not: '≠', lt: '<', lte: '≤', gt: '>', gte: '≥' }

function condText(c: ScriptCond, states: StateDef[], info: ScriptsInfo, envInfo: ScriptsInfo | null): string {
  const kind = c.kind ?? 'state'
  const st = states.find(x => x.id === c.state)
  const val = (v: unknown) => isRef(v) ? valueText(v, envInfo ?? info, states) : st?.type === 'ratio' ? `${Math.round(Number(v) * 100)}%`
    : st?.type === 'number' ? `${v}${st.unit ?? ''}` : st?.classes?.find(x => x.value === v)?.name ?? String(v)
  const name = st?.name ?? c.state ?? ''
  const vars = (envInfo ?? info).variables
  const vname = vars.find(v => v.name === c.var)?.label || c.var || ''
  const op = OP_WORD[c.op ?? 'is'] ?? c.op ?? ''
  switch (kind) {
    case 'state': return `${name} ${op} ${val(c.value)}${c.for ? t('(持續 {for} 秒)', { for: c.for }) : ''}`
    case 'device': return t('{device} 的{name} {op} {p4}', { device: c.device, name, op, p4: val(c.value) })
    case 'became': return t('{name} 剛變成 {p2}', { name, p2: val(c.value) })
    case 'count': return t('{within} 秒內{name}變成{p3} {op} {p5} 次', { within: c.within, name, p3: val(c.value), op, p5: isRef(c.times) ? valueText(c.times, envInfo ?? info, states) : c.times })
    case 'change': {
      const p = { state: name, n: c.within, amount: isRef(c.amount) ? valueText(c.amount, envInfo ?? info, states) : `${Math.round(Number(c.amount ?? 0) * 100)}%` }
      return c.dir === 'rise' ? t('{state} {n} 秒內上升 {amount}', p) : t('{state} {n} 秒內下降 {amount}', p)
    }
    case 'time': return t('時段 {from}~{to}', { from: c.from, to: c.to })
    case 'always': return t('總是')
    case 'var': return `${vname} ${op} ${isRef(c.value) ? valueText(c.value, envInfo ?? info, states) : c.value}`
    case 'elapsed': return t('距離{vname} {op} {value} 秒', { vname, op, value: isRef(c.value) ? valueText(c.value, envInfo ?? info, states) : (c.value as string | number | undefined) })
    case 'compare': return `${valueText(c.left, envInfo ?? info, states)} ${op} ${valueText(c.right, envInfo ?? info, states)}`
    case 'visible': {
      const target = c.target?.button ? t('「{x}」', { x: (envInfo ?? info).buttons.find(b => b.id === c.target?.button)?.label ?? c.target.button }) : t('參數的按鈕')
      return c.op === 'is_not' ? t('畫面上看不到{target}', { target }) : t('畫面上看得到{target}', { target })
    }
    default: return info.cond_kinds[kind] ?? kind
  }
}

/** a value of a number field in words: 12, 「庫存」 + 設定「安全庫存」 */
function valueText(v: unknown, info: ScriptsInfo | null, states: StateDef[], params: SubParam[] = []): string {
  if (v == null) return ''
  if (!isRef(v)) return typeof v === 'number' ? String(Math.round(v * 1000) / 1000) : String(v)
  if ('sum' in v) return v.sum.map(x => valueText(x, info, states, params)).join(' + ')
  if ('state' in v) return t('「{x}」', { x: states.find(s => s.id === v.state)?.name ?? v.state })
  if ('setting' in v) return t('設定「{p1}」', { p1: info?.settings.find(s => s.id === v.setting)?.label ?? v.setting })
  if ('var' in v) return t('變數「{p1}」', { p1: info?.variables.find(x => x.name === v.var)?.label || v.var })
  return t('「{x}」', { x: params.find(p => p.name === v.param)?.label || v.param })
}

function pointText(p: ScriptPoint | undefined, info: ScriptsInfo, params: SubParam[] = []): string {
  if (!p) return t('(還沒選)')
  if (p.button) return t('「{x}」', { x: info.buttons.find(b => b.id === p.button)?.label ?? p.button })
  if (p.param != null) return t('「{x}」', { x: params.find(x => x.name === p.param)?.label || p.param })
  if ((p as { setting?: string }).setting) return t('設定「{label}」', { label: info.settings.find(x => x.id === (p as { setting?: string }).setting)?.label })
  if (p.x != null) return `(${p.x}, ${p.y})`
  return t('(還沒選)')
}

const whenText = (when: ScriptCond[][] | undefined, ctx: Ctx) =>
  (when ?? []).map(g => g.map(c => condText(c, ctx.states, ctx.info, ctx.info)).join(t(' 且 '))).join(t(' ,或 ')) || t('(還沒設條件)')

/** one step in words, for the one-line view (blocks: their header; their steps are listed under them) */
function stepText(st: SubStep, ctx: Ctx): string {
  const { info, params } = ctx
  const v = (x: unknown) => valueText(x, info, ctx.states, params)
  let tx = ''
  switch (st.type) {
    case 'tap': tx = t('點擊 {p1}', { p1: pointText(st.target, info, params) }); break
    case 'long_press': tx = t('長按 {p1}', { p1: pointText(st.target, info, params) }); break
    case 'swipe': tx = t('滑動 {p1} → {p2}', { p1: pointText(st.from, info, params), p2: pointText(st.to, info, params) }); break
    case 'back': tx = t('按返回鍵'); break
    case 'input_text': tx = t('輸入「{p1}」', { p1: st.text ?? '' }); break
    case 'launch_app': tx = t('啟動 App{p1}', { p1: st.package ? `「${st.package}」` : '' }); break
    case 'pick': tx = t('在清單中找到並點擊 {p1}', { p1: pointText(st.target, info, params) }); break
    case 'capture_list': tx = t('擷取清單「{p1}」', { p1: info.lists.find(l => l.id === st.list)?.title ?? st.list }); break
    case 'wait': tx = t('等 {p1} 秒', { p1: v(st.seconds ?? 1) }); break
    case 'wait_until': {
      const p = { when: whenText(st.when, ctx), n: v(st.timeout ?? 10) }
      tx = st.on_timeout === 'continue' ? t('等到 {when}(最多 {n} 秒,逾時就繼續)', p) : t('等到 {when}(最多 {n} 秒)', p); break
    }
    case 'if': tx = t('如果 {p1}', { p1: whenText(st.when, ctx) }); break
    case 'repeat_until': tx = t('重複下面的步驟,直到 {p1}(最多 {p2} 次)', { p1: whenText(st.when, ctx), p2: v(st.max_times ?? 10) }); break
    case 'retry': tx = t('下面的步驟失敗就重來(最多 {p1} 次)', { p1: v(st.times ?? 3) }); break
    case 'for_each': tx = t('「{p1}」的每一個都做', { p1: params.find(p => p.name === st.list)?.label ?? st.list ?? '' }); break
    case 'call': {
      const p = { sub: info.subs.find(x => x.id === st.sub)?.name ?? st.sub ?? '' }
      tx = st.on_fail === 'continue' ? t('執行子腳本「{sub}」(失敗也繼續)', p) : st.on_fail === 'stop' ? t('執行子腳本「{sub}」(失敗就停下這台)', p) : t('執行子腳本「{sub}」', p); break
    }
    case 'notify': tx = t('通知「{p1}」', { p1: st.text ?? '' }); break
    case 'ask': tx = t('問使用者「{p1}」({p2})', { p1: st.text ?? '', p2: (st.options ?? []).map(o => o.label).join(' / ') }); break
    case 'output': tx = t('送到輸出「{p1}」{p2}', { p1: info.outputs.find(o => o.id === st.output)?.name ?? st.output ?? '', p2: st.command ? `:${st.command}` : '' }); break
    case 'set_var': {
      const vr = info.variables.find(x => x.name === st.var)?.label || st.var || ''
      tx = st.mode === 'now' ? t('變數「{var}」記下現在時間', { var: vr })
        : t('變數「{var}」{mode} {value}', { var: vr, mode: info.var_modes[st.mode ?? 'add'] ?? '', value: v(st.value) }); break
    }
    case 'succeed': tx = st.text ? t('到此結束(成功):{text}', { text: st.text }) : t('到此結束(成功)'); break
    case 'fail': tx = st.text ? t('到此結束(失敗):{text}', { text: st.text }) : t('到此結束(失敗)'); break
    case 'stop': tx = st.text ? t('停下這台:{text}', { text: st.text }) : t('停下這台'); break
    case 'goto': tx = t('切換到情境「{p1}」', { p1: ctx.place?.situations.find(x => x.id === st.situation)?.name ?? st.situation ?? '' }); break
    case 'stay': tx = st.text ? t('原地等著,不動作({text})', { text: st.text }) : t('原地等著,不動作'); break
    case 'hold': tx = st.text ? t('暫停其他腳本({text})', { text: st.text }) : t('暫停其他腳本'); break
    default: tx = info.step_types[st.type] ?? st.type
  }
  const a = st.after
  if (a?.until) tx += t(',然後等到 {p1}(最多 {p2} 秒)', { p1: whenText(a.until, ctx), p2: v(a.timeout ?? 10) })
  else if (a?.seconds != null) tx += t(',然後等 {p1} 秒', { p1: v(a.seconds) })
  return tx
}

/** a rule's / an entry's steps in one line */
function doText(steps: SubStep[] | null | undefined, ctx: Ctx): string {
  if (!steps?.length) return t('不動作')
  return steps.map(st => stepText(st, ctx) + (st.type === 'if' || st.type === 'repeat_until' || st.type === 'retry' || st.type === 'for_each' || st.type === 'ask' ? ' …' : '')).join(' → ')
}

function defaultCond(states: StateDef[]): ScriptCond {
  const st = states[0]
  return { state: st?.id ?? '', op: 'is', value: st?.classes?.[0]?.value ?? 0, min_conf: 0.7 }
}

/** what step lists inside a main script / the guard rules may use (goto, stay, hold) */
function placeOf(script: Script, kind: 'rule' | 'enter'): Place {
  return { kind, guard: script.id === GUARD, situations: script.situations.map(x => ({ id: x.id, name: x.name })) }
}

function RuleCard({ r, i, n, info, states, script, open, dragging, onToggle, onDragStart, onDragEnd, onChange, onMove, onDelete }: {
  r: ScriptRule; i: number; n: number; info: ScriptsInfo; states: StateDef[]; script: Script; open: boolean; dragging: boolean; onToggle: () => void
  onDragStart: () => void; onDragEnd: () => void
  onChange: (fn: (r: ScriptRule) => void) => void; onMove: (d: number) => void; onDelete: () => void
}) {
  const env = useContext(CondEnv)
  const ref = useRef<HTMLDivElement>(null)
  const grip = <Grip rowRef={ref} onStart={onDragStart} onEnd={onDragEnd} title={t('拖拉來調整順序,或拖到上面的其他情境')} />
  const [limits, setLimits] = useState(false)
  const ctx: Ctx = { info, states, params: [], selfId: '', place: placeOf(script, 'rule') }
  if (!open) {
    const when = r.when.map(g => g.map(c => condText(c, states, info, env.info)).join(t(' 且 '))).join(t(' ,或 '))
    return (
      <div ref={ref} className={`border rounded-lg bg-white flex items-stretch ${dragging ? 'opacity-30' : ''} ${!r.enabled ? 'border-stone-200 opacity-60' : r.urgent ? 'border-rose-400' : 'border-stone-200'}`}>
        <span className="flex items-center pl-1.5">{grip}</span>
        <button onClick={onToggle} className="flex-1 text-left px-3 py-2 flex items-start gap-2 hover:bg-stone-50 rounded-l-lg min-w-0">
          <span className="text-xs font-semibold bg-stone-900 text-white rounded px-1.5 py-0.5 shrink-0">#{i + 1}</span>
          <span className="min-w-0">
            <span className="font-medium text-sm">{r.name}</span>
            {r.urgent && <span className="ml-1.5 text-[10px] px-1 rounded bg-rose-600 text-white align-middle">{t('緊急')}</span>}
            {!r.enabled && <span className="ml-1.5 text-[10px] px-1 rounded bg-stone-200 text-stone-600 align-middle">{t('停用')}</span>}
            <span className="block text-xs text-stone-600 truncate" title={when}>{t('如果 {when}', { when })}</span>
            <span className="block text-xs text-stone-800">→ {doText(r.do, ctx)}
              <span className="text-stone-400">{r.cooldown ? t(' · 冷卻 {cooldown} 秒', { cooldown: r.cooldown }) : ''}{r.max_per_hour ? t(' · 每小時 {max_per_hour} 次', { max_per_hour: r.max_per_hour }) : ''}{r.max_per_day ? t(' · 每天 {max_per_day} 次', { max_per_day: r.max_per_day }) : ''}</span></span>
          </span>
        </button>
        <div className="flex flex-col justify-center pr-1">
          <button className="text-xs text-stone-400 hover:text-stone-900 disabled:opacity-30 px-1" disabled={i === 0} onClick={() => onMove(-1)} title={t('往上(先檢查)')}>▲</button>
          <button className="text-xs text-stone-400 hover:text-stone-900 disabled:opacity-30 px-1" disabled={i === n - 1} onClick={() => onMove(1)} title={t('往下')}>▼</button>
        </div>
      </div>
    )
  }
  return (
    <div ref={ref} className={`border-2 rounded-lg p-3 flex flex-col gap-3 bg-white ${dragging ? 'opacity-30' : ''} ${!r.enabled ? 'border-stone-300' : r.urgent ? 'border-rose-400' : 'border-stone-400'}`}>
      <div className="flex items-center gap-2 flex-wrap">
        {grip}
        <span className="text-xs font-semibold bg-stone-900 text-white rounded px-1.5 py-0.5">#{i + 1}</span>
        <input className={`${input} font-medium w-56`} value={r.name} onChange={e => onChange(x => { x.name = e.target.value })} />
        <label className="text-xs flex items-center gap-1"><input type="checkbox" checked={r.enabled} onChange={e => onChange(x => { x.enabled = e.target.checked })} />{t('啟用')}</label>
        <label className="text-xs flex items-center gap-1 text-rose-700" title={t('緊急:條件第一次成立就執行(不等第二次確認),而且可以打斷這台正在跑的任何子腳本')}>
          <input type="checkbox" checked={!!r.urgent} onChange={e => onChange(x => { if (e.target.checked) x.urgent = true; else delete x.urgent })} />{t('緊急')}</label>
        <span className="flex-1" />
        <Button variant="ghost" disabled={i === 0} onClick={() => onMove(-1)}>↑</Button>
        <Button variant="ghost" disabled={i === n - 1} onClick={() => onMove(1)}>↓</Button>
        <Button variant="ghost" onClick={onDelete}>{t('刪除')}</Button>
        <Button onClick={onToggle}>{t('收合 ▴')}</Button>
      </div>
      {r.urgent && <UrgentHealth r={r} states={states} />}
      <div className="flex flex-col gap-2">
        <div className="text-xs text-stone-500">{t('如果')}</div>
        <CondGroups when={r.when} states={states} ops={info.ops} onChange={fn => onChange(x => fn(x.when))} />
      </div>
      <div className="flex flex-col gap-2 text-sm border-t border-stone-100 pt-2">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs text-stone-500">{t('就依序做:')}</span>
          <span className="flex-1" />
          <span className="text-xs text-stone-500">{r.cooldown ? t('做完後冷卻 {cooldown} 秒', { cooldown: r.cooldown }) : t('不冷卻')}{r.max_per_hour ? t(' · 每小時 {max_per_hour} 次', { max_per_hour: r.max_per_hour }) : ''}{r.max_per_day ? t(' · 每天 {max_per_day} 次', { max_per_day: r.max_per_day }) : ''}</span>
          <MoreButton onClick={() => setLimits(true)}>{t('次數限制')}</MoreButton>
        </div>
        <StepsRoot onRoot={fn => onChange(x => { x.do = x.do ?? []; fn(x as unknown as Record<string, unknown>) })}>
          <StepList steps={r.do ?? []} ctx={ctx} path={['do']} onChange={fn => onChange(x => { x.do = x.do ?? []; fn(x.do) })}
            empty={t('還沒有步驟 = 條件成立時什麼都不做。按「+ 新增步驟」加入要做的事,例如通知、點擊、停下這台。')} />
        </StepsRoot>
        <Modal open={limits} title={t('規則「{name}」:次數限制', { name: r.name })} onClose={() => setLimits(false)} footer={<Button variant="primary" onClick={() => setLimits(false)}>{t('好')}</Button>}>
          <label className="flex items-center gap-1" title={t('執行一次之後,這麼久之內不再執行')}>{t('冷卻')} <input type="number" className={`${input} w-16 num`} value={r.cooldown ?? 0} onChange={e => onChange(x => { x.cooldown = Number(e.target.value) })} /> {t('秒')}</label>
          <label className="flex items-center gap-1" title={t('正式執行時,一小時內最多執行幾次;超過就暫停這條規則並通知(0 = 不限)')}>{t('每小時最多')}
            <input type="number" min={0} className={`${input} w-14 num`} value={r.max_per_hour ?? 0} onChange={e => onChange(x => { const v = Number(e.target.value); if (v > 0) x.max_per_hour = v; else delete x.max_per_hour })} /> {t('次')}</label>
          <label className="flex items-center gap-1" title={t('每台{device}每天(0 點起算)最多執行幾次(0 = 不限)。例如每天 05:00 做一次:條件用時段 05:00~05:10,這裡填 1', { device: words.device })}>{t('每天最多')}
            <input type="number" min={0} className={`${input} w-14 num`} value={r.max_per_day ?? 0} onChange={e => onChange(x => { const v = Number(e.target.value); if (v > 0) x.max_per_day = v; else delete x.max_per_day })} /> {t('次')}</label>
          <span className="text-xs text-stone-500">{t('改完按上方「儲存」才會生效')}</span>
        </Modal>
      </div>
    </div>
  )
}

/** "送到輸出": which output, the command text ({variable} filled in) and an optional value */
function OutputFields({ a, info, onChange }: { a: { output?: string; command?: string; value?: NumVal }; info: ScriptsInfo; onChange: (fn: (x: { output?: string; command?: string; value?: NumVal }) => void) => void }) {
  if (!info.outputs.length) return <span className="text-xs text-rose-700">{t('先到「素材庫 › 輸出」新增一個輸出')}</span>
  return (
    <span className="flex flex-wrap items-center gap-1.5">
      <select className={input} value={a.output ?? ''} onChange={e => onChange(x => { x.output = e.target.value })}>
        {info.outputs.map(o => <option key={o.id} value={o.id}>{o.name}</option>)}
      </select>
      <input className={`${input} w-40`} placeholder={t('指令(例如 開水車)')} value={a.command ?? ''} title={t('可以用 {變數代號} 帶入目前的值')}
        onChange={e => onChange(x => { x.command = e.target.value })} />
      <label className="flex items-center gap-1 text-xs"><input type="checkbox" checked={a.value != null}
        onChange={e => onChange(x => { if (e.target.checked) x.value = 1; else delete x.value })} />{t('帶數值')}</label>
      {a.value != null && <ValueInput value={a.value} def={1} onChange={v => onChange(x => { x.value = v })} />}
    </span>
  )
}

/** "設定變數": which variable, set / add / store the time */
function VarAction({ a, info, onChange }: { a: { var?: string; mode?: string; value?: NumVal }; info: ScriptsInfo; onChange: (fn: (x: { var?: string; mode?: string; value?: NumVal }) => void) => void }) {
  if (!info.variables.length) return <span className="text-xs text-rose-700">{t('先在左邊「變數」新增變數')}</span>
  return (
    <span className="flex items-center gap-1.5">
      <select className={input} value={a.var ?? ''} onChange={e => onChange(x => { x.var = e.target.value })}>
        {info.variables.map(v => <option key={v.name} value={v.name}>{v.label || v.name}</option>)}
      </select>
      <select className={input} value={a.mode ?? 'add'} onChange={e => onChange(x => { x.mode = e.target.value; if (e.target.value === 'now') delete x.value; else x.value = x.value ?? 1 })}>
        {Object.entries(info.var_modes).map(([k, tx]) => <option key={k} value={k}>{tx}</option>)}
      </select>
      {a.mode !== 'now' && <ValueInput value={a.value} def={1} w="w-20" onChange={v => onChange(x => { x.value = v })} />}
    </span>
  )
}

/** the situations (情境) of a main script: pick one to edit its rules; entry action and time limit per situation */
function SituationsCard({ s, cur, setCur, info, onChange, dragging, onDropRule }: {
  s: Script; cur: number; setCur: (i: number) => void; info: ScriptsInfo; onChange: (fn: (x: Script) => void) => void
  dragging: boolean; onDropRule: (to: number) => void
}) {
  const sit: Situation = s.situations[cur]
  const set = (fn: (x: Situation) => void) => onChange(x => fn(x.situations[cur]))
  // a situation without rules is all settings (e.g. "go back to the start on entry"): show them open
  const [showSet, setShowSet] = useState(sit.rules.length === 0)
  useEffect(() => { setShowSet(sit.rules.length === 0) }, [sit.id]) // eslint-disable-line react-hooks/exhaustive-deps
  const sitName = (id?: string | null) => id === 'stop' ? t('停止腳本') : s.situations.find(x => x.id === id)?.name ?? id ?? ''
  const env = useContext(CondEnv)
  const ctx: Ctx = { info, states: env.states ?? [], params: [], selfId: '', place: placeOf(s, 'enter') }
  const e = sit.on_enter
  const enterText = e ? doText(e, ctx) : ''
  const timeText = sit.max_seconds != null ? t('{max_seconds} 秒後切到「{p2}」', { max_seconds: sit.max_seconds, p2: sitName(sit.on_timeout) }) : ''
  return (
    <div className="bg-white border border-stone-200 rounded-lg p-3" title={t('每台{device}同一時間只在一個情境;只檢查那個情境的規則。規則的「切換情境」、子腳本成功/失敗、逾時都可以換情境', { device: words.device })}>
      <div className="flex flex-col gap-3 text-sm">
        <div className="flex flex-wrap gap-1.5 items-center">
          {s.situations.map((x, i) => (
            <DropTarget key={x.id} active={dragging && i !== cur} onDrop={() => onDropRule(i)} className="rounded-md" overClass="ring-2 ring-sky-500">
              <button onClick={() => setCur(i)} title={dragging && i !== cur ? t('放開:把規則移到「{name}」的最後', { name: x.name }) : undefined}
                className={`px-3 py-1 rounded-md border ${i === cur ? 'bg-stone-900 text-white border-stone-900' : dragging ? 'bg-sky-50 border-sky-300 border-dashed' : 'bg-white border-stone-300 hover:bg-stone-50'}`}>
                {x.id === s.initial && <span title={t('一開始的情境')}>▶ </span>}{x.name}<span className="opacity-60 text-xs"> ({x.rules.length})</span>
              </button>
            </DropTarget>
          ))}
          <button className="text-xs text-stone-700 underline ml-1" onClick={() => onChange(x => {
            const id = newId('s', x.situations.map(y => y.id))
            x.situations.push({ id, name: t('情境 {p1}', { p1: x.situations.length + 1 }), rules: [] })
            setCur(x.situations.length - 1)
          })}>{t('+ 新增情境')}</button>
          <span className="flex-1" />
          <Button variant="ghost" onClick={() => setShowSet(v => !v)}>{showSet ? t('收起情境設定 ▴') : t('編輯情境設定 ▾')}</Button>
        </div>
        {!showSet && (
          <div className="flex flex-wrap gap-2 text-xs">
            {s.initial === sit.id && <span className="px-2 py-1 rounded bg-stone-100 text-stone-700">{t('▶ 一開始的情境')}</span>}
            <span className={`px-2 py-1 rounded ${e ? 'bg-amber-50 text-amber-900 border border-amber-200' : 'bg-stone-50 text-stone-400'}`}>{t('進入時:')}{e ? enterText : t('不做事')}</span>
            <span className={`px-2 py-1 rounded ${timeText ? 'bg-sky-50 text-sky-900 border border-sky-200' : 'bg-stone-50 text-stone-400'}`}>{t('最長停留:')}{timeText || t('不限')}</span>
          </div>
        )}
        {showSet && <div className="grid md:grid-cols-2 gap-3 border-t border-stone-100 pt-3">
          <label className="flex items-center gap-2"><span className="text-stone-600 w-16">{t('名稱')}</span>
            <input className={`${input} flex-1`} value={sit.name} onChange={e => set(x => { x.name = e.target.value })} /></label>
          <div className="flex items-center gap-3">
            <label className="flex items-center gap-1.5"><input type="radio" checked={s.initial === sit.id} onChange={() => onChange(x => { x.initial = sit.id })} />{t('一開始的情境')}</label>
            {s.situations.length > 1 && <Button variant="ghost" onClick={() => {
              const used = s.situations.some(x => x.on_timeout === sit.id || JSON.stringify([x.rules, x.on_enter ?? null]).includes(`"${sit.id}"`))
              if (used && !confirm(t('有其他地方會切換到這個情境,確定刪除?(儲存時會提醒哪裡要改)'))) return
              onChange(x => { x.situations.splice(cur, 1); if (x.initial === sit.id) x.initial = x.situations[0].id })
              setCur(0)
            }}>{t('刪除這個情境')}</Button>}
          </div>
          <div className="md:col-span-2 flex flex-col gap-1">
            <label className="flex items-center gap-2 text-stone-600">
              <input type="checkbox" checked={!!sit.on_enter} onChange={e => set(x => { x.on_enter = e.target.checked ? [] : null })} />
              {t('進入這個情境時先做這些步驟(每次進入做一次)')}</label>
            {sit.on_enter && <div className="pl-6">
              <StepsRoot onRoot={fn => set(x => { x.on_enter = x.on_enter ?? []; fn(x as unknown as Record<string, unknown>) })}>
                <StepList steps={sit.on_enter} ctx={ctx} path={['on_enter']} onChange={fn => set(x => { x.on_enter = x.on_enter ?? []; fn(x.on_enter) })}
                  empty={t('例如:執行子腳本「回到起點」,成功後切換到「工作中」')} />
              </StepsRoot>
            </div>}
          </div>
          <div className="md:col-span-2 flex flex-wrap items-center gap-2 text-stone-600">
            <label className="flex items-center gap-2">
              <input type="checkbox" checked={sit.max_seconds != null} onChange={e => set(x => {
                if (e.target.checked) { x.max_seconds = 600; x.on_timeout = s.initial !== sit.id ? s.initial : s.situations.find(y => y.id !== sit.id)?.id ?? sit.id }
                else { x.max_seconds = null; delete x.on_timeout }
              })} />{t('最長停留')}</label>
            {sit.max_seconds != null && <>
              <input type="number" min={1} className={`${input} w-20 num`} value={sit.max_seconds} onChange={e => set(x => { x.max_seconds = Number(e.target.value) })} />{t('秒,超過就切到')}
              <select className={input} value={sit.on_timeout ?? ''} onChange={e => set(x => { x.on_timeout = e.target.value })}>
                {s.situations.map(x => <option key={x.id} value={x.id}>{x.name}</option>)}
              </select>
              <span className="text-xs text-stone-500">{t('(避免卡在這個情境出不來)')}</span>
            </>}
          </div>
        </div>}
      </div>
    </div>
  )
}

/** An urgent rule acts on the first sighting: how reliably is each state it reads judged? */
function UrgentHealth({ r, states }: { r: ScriptRule; states: StateDef[] }) {
  const ids = [...new Set(r.when.flat().map(c => c.state).filter((x): x is string => !!x))].sort()
  const q = useQuery({ queryKey: ['urgentCheck', ids.join(',')], queryFn: () => api.statesUrgentCheck(ids), enabled: ids.length > 0, staleTime: 60_000 })
  if (!ids.length) return null
  const tone = { ok: 'text-emerald-700', warn: 'text-amber-700', bad: 'text-rose-700' }
  const mark = { ok: '✓', warn: '⚠', bad: '✕' }
  const worst = Object.values(q.data?.states ?? {}).some(x => x.level === 'bad') ? 'bad'
    : Object.values(q.data?.states ?? {}).some(x => x.level === 'warn') ? 'warn' : 'ok'
  return (
    <div className={`text-xs rounded-md px-3 py-2 flex flex-col gap-0.5 ${worst === 'ok' ? 'bg-emerald-50' : worst === 'warn' ? 'bg-amber-50' : 'bg-rose-50'}`}>
      <div className="text-stone-600">{t('緊急規則第一次看到就動作,用到的狀態要非常準(建議 {p1}% 以上):', { p1: Math.round((q.data?.min_acc ?? 0.99) * 100) })}</div>
      {q.isLoading && <div className="text-stone-400">{t('檢查中…(畫面規則會拿您答過的畫面實測)')}</div>}
      <ErrorText error={q.error} />
      {ids.map(sid => {
        const x = q.data?.states[sid]
        if (!x) return null
        return <div key={sid} className={tone[x.level]}>{mark[x.level]} {states.find(z => z.id === sid)?.name ?? sid}:{x.text}
          {x.level !== 'ok' && <Link className="ml-2 underline" to={`/review?state=${encodeURIComponent(sid)}`}>{t('去補考題')}</Link>}</div>
      })}
    </div>
  )
}

const ParamsCtx = createContext<SubParam[]>([])

/** what the condition editors need besides the states: variables, other emulators */
export const CondEnv = createContext<{ info: ScriptsInfo | null; devices: string[]; states?: StateDef[] }>({ info: null, devices: [] })

/** A number field of the script spec: a number, or where it comes from when the script runs - a parameter of the
 *  sub-script, a user setting, a variable or a number state read off the screen (automation/values.py).
 *  scale: shown ×scale (percentages). */

export function ValueInput({ value, onChange, def = 0, w = 'w-16', step = 1, scale = 1, min, sum = true }: {
  value: NumVal | undefined; onChange: (v: NumVal) => void; def?: number; w?: string; step?: number; scale?: number; min?: number; sum?: boolean
}) {
  const env = useContext(CondEnv)
  const params = useContext(ParamsCtx)
  const v = value ?? def
  if (isRef(v) && 'sum' in v) {                       // a + b + ...: each part its own value
    const parts = v.sum
    const setPart = (k: number, nv: NumVal | null) => {
      const ps = [...parts]
      if (nv === null) ps.splice(k, 1); else ps[k] = nv
      onChange(ps.length === 1 ? ps[0] : { sum: ps })
    }
    return (
      <span className="inline-flex flex-wrap items-center gap-1 rounded border border-dashed border-stone-300 px-1 py-0.5">
        {parts.map((p, k) => <Fragment key={k}>
          {k > 0 && <span className="text-stone-500">+</span>}
          <span className="inline-flex items-center">
            <ValueInput value={p} def={0} w={w} step={step} sum={false} onChange={nv => setPart(k, nv)} />
            <button className="text-[10px] text-stone-400 hover:text-rose-600 px-0.5" title={t('拿掉這一項')} onClick={() => setPart(k, null)}>✕</button>
          </span>
        </Fragment>)}
        <button className="text-xs text-sky-700 px-1" title={t('再加一項')} onClick={() => onChange({ sum: [...parts, 0] })}>+</button>
      </span>
    )
  }
  const ref = isRef(v)
  const opts: [string, string][] = [
    ...params.filter(p => p.type === 'number').map(p => [`param:${p.name}`, t('參數「{p1}」', { p1: p.label || p.name })] as [string, string]),
    ...(env.info?.settings ?? []).filter(x => x.type === 'number' || x.type === 'time').map(x => [`setting:${x.id}`, t('設定「{label}」', { label: x.label })] as [string, string]),
    ...(env.info?.variables ?? []).map(x => [`var:${x.name}`, t('變數「{p1}」', { p1: x.label || x.name })] as [string, string]),
    ...(scale === 1 ? env.states ?? [] : []).filter(x => x.type === 'number').map(x => [`state:${x.id}`, t('「{name}」(畫面上讀到的數字)', { name: x.name })] as [string, string]),
  ]
  const canSum = sum && scale === 1
  const cur = ref ? `${Object.keys(v)[0]}:${Object.values(v)[0]}` : ''
  return (
    <span className="inline-flex items-center gap-0.5">
      {!ref && <input type="number" step={step} min={min} className={`${input} ${w} num`} value={Math.round(Number(v) * scale * 1000) / 1000}
        onChange={e => onChange(Number(e.target.value) / scale)} />}
      {(opts.length > 0 || canSum) && <select className={`${input} ${ref ? '' : 'w-7 px-0.5 text-stone-400'}`} value={cur} title={t('用固定的數字,或執行時從參數、使用者設定、變數、畫面上讀到的數字取值;也可以把幾個值加起來')}
        onChange={e => {
          if (!e.target.value) { onChange(def); return }
          if (e.target.value === '__sum') { onChange({ sum: [v, 0] }); return }
          const [k, n] = e.target.value.split(/:(.*)/)
          onChange({ [k]: n } as ValueRef)
        }}>
        <option value="">{ref ? t('改回固定值') : '…'}</option>
        {opts.map(([k, tx]) => <option key={k} value={k}>{tx}</option>)}
        {ref && !opts.some(([k]) => k === cur) && <option value={cur}>{t('{cur}(已不存在)', { cur })}</option>}
        {canSum && <option value="__sum">{t('再加上另一個值…')}</option>}
      </select>}
    </span>
  )
}

function CondGroups({ when, states, ops, onChange }: {
  when: ScriptCond[][]; states: StateDef[]; ops: Record<string, string>; onChange: (fn: (w: ScriptCond[][]) => void) => void
}) {
  // one condition open for editing at a time ("group:index"); the others read as one sentence each
  const [open, setOpen] = useState<string | null>(null)
  const many = when.length > 1
  return (
    <div className="group/conds flex flex-col gap-1.5">
      {when.map((g, gi) => (
        <div key={gi} className="flex flex-col gap-1.5">
          {gi > 0 && <div className="flex items-center gap-2 text-xs font-semibold text-violet-700">
            <span className="flex-1 border-t border-violet-200" />{t('或者')}<span className="flex-1 border-t border-violet-200" /></div>}
          <div className={`rounded-md flex flex-col gap-1 ${many ? 'border border-stone-200 bg-stone-50/60 p-2' : ''}`}>
            {many && <div className="text-[11px] text-stone-500">{t('第 {p1} 組', { p1: gi + 1 })}{g.length > 1 ? t(':以下全部成立') : ''}</div>}
            {g.map((c, ci) => (
              <CondRow key={ci} c={c} states={states} ops={ops} first={ci === 0}
                open={open === `${gi}:${ci}`} onOpen={o => setOpen(o ? `${gi}:${ci}` : null)}
                onChange={fn => onChange(w => fn(w[gi][ci]))}
                onReplace={nc => onChange(w => { w[gi][ci] = nc })}
                onDelete={() => { setOpen(null); onChange(w => { w[gi].splice(ci, 1); if (!w[gi].length) w.splice(gi, 1) }) }} />
            ))}
            <button className={`text-xs text-stone-600 hover:text-stone-900 self-start pl-9 ${open || many ? '' : 'opacity-0 group-hover/conds:opacity-100 focus:opacity-100'}`} title={t('這一組再多一個條件:全部都成立才算')}
              onClick={() => { onChange(w => { w[gi].push(defaultCond(states)) }); setOpen(`${gi}:${g.length}`) }}>{t('+ 而且(再加一個條件)')}</button>
          </div>
        </div>
      ))}
      <button className={`text-xs text-violet-700 hover:text-violet-900 self-start ${open || many ? '' : 'opacity-0 group-hover/conds:opacity-100 focus:opacity-100'}`} title={t('另一組條件:任何一組成立就算')}
        onClick={() => { onChange(w => { w.push([defaultCond(states)]) }); setOpen(`${when.length}:0`) }}>{t('+ 或者(另一組條件,任何一組成立就算)')}</button>
    </div>
  )
}

const DAYS = [t('一'), t('二'), t('三'), t('四'), t('五'), t('六'), t('日')]
const OPSYM: Record<string, string> = { lt: '<', lte: '≤', gt: '>', gte: '≥', is: '=', is_not: '≠' }

/** what a condition looks at: "st:<state id>", "var:<name>", "btn", "time", "always", "compare" */
function condSubject(c: ScriptCond): string {
  const k = c.kind ?? 'state'
  if (k === 'state' || k === 'became' || k === 'count' || k === 'change' || k === 'device') return `st:${c.state ?? ''}`
  if (k === 'var' || k === 'elapsed') return `var:${c.var ?? ''}`
  if (k === 'visible') return 'btn'
  return k
}

/** how it is compared: =, ≠, <, …, became, count, drop, rise (states); the ops or elapsed (variables); is / is_not (buttons) */
function condHow(c: ScriptCond): string {
  const k = c.kind ?? 'state'
  if (k === 'became' || k === 'count' || k === 'elapsed') return k
  if (k === 'change') return c.dir === 'rise' ? 'rise' : 'drop'
  return c.op ?? (k === 'var' ? 'gte' : 'is')
}

function howChoices(subject: string, st?: StateDef): [string, string][] {
  const cmp = (ks: string[]) => ks.map(k => [k, OPSYM[k]] as [string, string])
  if (subject.startsWith('st:')) {
    if (st?.type === 'class' || !st) return [...cmp(['is', 'is_not']), ['became', t('剛變成')], ['count', t('一段時間內變成幾次')]]
    const trend: [string, string][] = [['drop', t('一段時間內下降')], ['rise', t('一段時間內上升')]]
    return st.type === 'ratio' ? [...cmp(['lt', 'lte', 'gt', 'gte']), ...trend] : [...cmp(['lt', 'lte', 'gt', 'gte', 'is', 'is_not']), ...trend]
  }
  if (subject.startsWith('var:')) return [...cmp(['gte', 'gt', 'lte', 'lt', 'is', 'is_not']), ['elapsed', t('距離記下的時間')]]
  if (subject === 'btn') return [['is', t('看得到')], ['is_not', t('看不到')]]
  return []
}

const stateDefault = (st?: StateDef): AnswerValue | NumVal => st?.type === 'ratio' ? 0.3 : st?.type === 'number' ? 0 : (st?.classes?.[0]?.value ?? 0)

/** the condition for a subject and a way of comparing, keeping what still fits from the one before */
function makeCond(subject: string, how: string | null, prev: ScriptCond, states: StateDef[], env: { info: ScriptsInfo | null; devices: string[] }): ScriptCond {
  const choices = howChoices(subject, states.find(x => `st:${x.id}` === subject))
  const h = how ?? (choices.some(([k]) => k === condHow(prev)) ? condHow(prev) : choices[0]?.[0])
  if (subject.startsWith('st:')) {
    const id = subject.slice(3)
    const st = states.find(x => x.id === id)
    const same = condSubject(prev) === subject
    const plain = (k?: string) => !!k && k in OPSYM
    const value = same && prev.value !== undefined && (plain(condHow(prev)) || st?.type === 'class') ? prev.value : stateDefault(st)
    const conf = st?.type === 'class' ? { min_conf: prev.min_conf ?? 0.7 } : {}
    if (h === 'became') return { kind: 'became', state: id, value: st?.type === 'class' ? value : stateDefault(st), within: prev.within ?? 5, ...conf }
    if (h === 'count') return { kind: 'count', state: id, value: st?.type === 'class' ? value : stateDefault(st), within: prev.within ?? 600, op: 'gte', times: prev.times ?? 2 }
    if (h === 'drop' || h === 'rise') return { kind: 'change', state: id, dir: h, within: prev.within ?? 10,
      amount: same && prev.kind === 'change' && prev.amount != null ? prev.amount : st?.type === 'number' ? 1 : 0.1 }
    return { kind: prev.kind === 'device' && same ? 'device' : 'state', ...(prev.kind === 'device' && same ? { device: prev.device } : {}),
      state: id, op: h, value, ...(prev.for ? { for: prev.for } : {}), ...conf }
  }
  if (subject.startsWith('var:')) {
    const name = subject.slice(4)
    if (h === 'elapsed') return { kind: 'elapsed', var: name, op: 'gt', value: prev.kind === 'elapsed' ? prev.value : 1800 }
    return { kind: 'var', var: name, op: h, value: prev.kind === 'var' && prev.value != null ? prev.value : 1, ...(prev.for ? { for: prev.for } : {}) }
  }
  if (subject === 'btn') return { kind: 'visible', op: h === 'is_not' ? 'is_not' : 'is', target: prev.kind === 'visible' && prev.target ? prev.target : { button: env.info?.buttons.find(b => b.find)?.id ?? '' } }
  if (subject === 'time') return prev.kind === 'time' ? prev : { kind: 'time', from: '22:00', to: '06:00', days: [] }
  if (subject === 'compare') {
    const nums = states.filter(x => x.type === 'number')
    return { kind: 'compare', left: nums[0] ? { state: nums[0].id } : 0, op: 'gte', right: nums[1] ? { state: nums[1].id } : 0 }
  }
  return { kind: 'always' }
}

/** one condition: 看什麼 → 怎麼了 → 值 (states, variables, buttons, time ...); 持續 / 信心 behind 更多… */
function CondRow({ c, states, first, open = true, onOpen, onChange, onReplace, onDelete }: {
  c: ScriptCond; states: StateDef[]; ops: Record<string, string>; first: boolean; open?: boolean; onOpen?: (o: boolean) => void
  onChange: (fn: (c: ScriptCond) => void) => void; onReplace: (c: ScriptCond) => void; onDelete: () => void
}) {
  const [more, setMore] = useState(false)
  const env = useContext(CondEnv)
  const params = useContext(ParamsCtx)
  const kind = c.kind ?? 'state'
  const subject = condSubject(c)
  const how = condHow(c)
  const st = states.find(x => x.id === c.state)
  const vars = env.info?.variables ?? []
  const choices = howChoices(subject, st)
  const num = (v: number | undefined, set: (v: number) => void, w = 'w-16', step = 1) =>
    <input type="number" step={step} className={`${input} ${w} num`} value={v ?? 0} onChange={e => set(Number(e.target.value))} />
  const classSel = () => (
    <select className={input} value={JSON.stringify(c.value)} onChange={e => onChange(x => { x.value = JSON.parse(e.target.value) })}>
      {(st?.classes ?? []).map(cl => <option key={String(cl.value)} value={JSON.stringify(cl.value)}>{cl.name}</option>)}
    </select>
  )
  const numberIn = () => st?.type === 'ratio'
    ? <span className="flex items-center gap-1"><ValueInput value={c.value as NumVal} def={0.3} scale={100} onChange={v => onChange(x => { x.value = v })} />{isRef(c.value) ? '' : '%'}</span>
    : <span className="flex items-center gap-1"><ValueInput value={c.value as NumVal} def={0} w="w-20" onChange={v => onChange(x => { x.value = v })} />{isRef(c.value) ? '' : st?.unit ?? ''}</span>
  const opSel = (list: string[]) => (
    <select className={input} value={c.op ?? list[0]} onChange={e => onChange(x => { x.op = e.target.value })}>
      {list.map(o => <option key={o} value={o}>{OPSYM[o]}</option>)}
    </select>
  )
  // 持續 / 信心: rarely changed - behind "更多…" unless set. 信心 only where a model judges it (a class state not "只用規則")
  const usesModel = st?.type === 'class' && st.judge !== 'rule'
  const custom = !!c.for || (c.min_conf != null && Math.abs(c.min_conf - 0.7) > 1e-6)
  const adv = more || custom
  const canHold = (kind === 'state' || kind === 'device' || kind === 'var' || kind === 'compare')
  const held = <label className="flex items-center gap-1 text-xs text-stone-600" title={t('條件要一直成立這麼久才算(避免畫面閃一下就觸發)')}>{t('持續')}
    <input type="number" min={0} step={0.5} className={`${input} w-14 num`} value={c.for ?? 0} onChange={e => onChange(x => { const v = Number(e.target.value); if (v > 0) x.for = v; else delete x.for })} />{t('秒')}</label>
  const conf = <label className="flex items-center gap-1 text-xs text-stone-600" title={t('模型要多有把握才算數;沒把握時這條規則先不動作')}>{t('信心 ≥')}
    <input type="number" min={0} max={100} className={`${input} w-14 num`} value={Math.round((c.min_conf ?? 0.7) * 100)} onChange={e => onChange(x => { x.min_conf = Number(e.target.value) / 100 })} />%</label>
  const confOk = usesModel && ['state', 'device', 'became'].includes(kind)
  const hasAdv = canHold || confOk
  if (!open && onOpen && env.info) return (
    <div className="group flex items-center gap-1.5 text-sm min-w-0">
      <span className="text-xs text-stone-400 w-8 shrink-0 text-right">{first ? '' : t('而且')}</span>
      <button className="flex-1 min-w-0 text-left rounded px-1.5 py-0.5 hover:bg-violet-50 truncate" onClick={() => onOpen(true)} title={t('點一下編輯這個條件')}>
        {condText(c, states, env.info, env.info)}</button>
      <button className="hidden group-hover:block text-xs text-stone-400 hover:text-rose-600 px-1" onClick={onDelete} title={t('刪除這個條件')}>✕</button>
    </div>
  )
  return (
    <div className={`flex flex-wrap gap-1.5 items-center text-sm ${onOpen ? 'rounded ring-1 ring-violet-300 bg-white p-1.5' : ''}`}>
      <span className="text-xs text-stone-400 w-8 text-right">{first ? '' : t('而且')}</span>
      {/* 1. 看什麼 */}
      <select className={`${input} bg-stone-50 max-w-[14rem]`} value={subject} title={t('看什麼')}
        onChange={e => onReplace(makeCond(e.target.value, null, c, states, env))}>
        <optgroup label={t('畫面狀態')}>
          {states.map(x => <option key={x.id} value={`st:${x.id}`}>{x.name}</option>)}
          {subject.startsWith('st:') && !st && <option value={subject}>{t('{state}(已不存在)', { state: c.state })}</option>}
        </optgroup>
        {vars.length > 0 && <optgroup label={t('變數')}>
          {vars.map(v => <option key={v.name} value={`var:${v.name}`}>{v.label || v.name}</option>)}
        </optgroup>}
        <optgroup label={t('其他')}>
          <option value="btn">{t('畫面上的按鈕(找圖)')}</option>
          <option value="time">{t('時段')}</option>
          <option value="always">{t('總是成立')}</option>
          <option value="compare">{t('自訂算式(兩邊都能相加)')}</option>
        </optgroup>
      </select>
      {/* 2. 怎麼了 */}
      {choices.length > 0 && <select className={input} value={how} title={t('怎麼比')}
        onChange={e => onReplace(makeCond(subject, e.target.value, c, states, env))}>
        {choices.map(([k, tx]) => <option key={k} value={k}>{tx}</option>)}
      </select>}
      {/* 3. 值 */}
      {(kind === 'state' || kind === 'device') && <>
        {st?.type === 'class' ? classSel() : numberIn()}
        {env.devices.length > 1 && <select className={`${input} text-xs`} value={kind === 'device' ? c.device ?? '' : ''} title={t('看哪一台的畫面')}
          onChange={e => onChange(x => { if (e.target.value) { x.kind = 'device'; x.device = e.target.value } else { x.kind = 'state'; delete x.device } })}>
          <option value="">{t('(這台)')}</option>
          {[...new Set([...env.devices, ...(c.device ? [c.device] : [])])].map(d => <option key={d} value={d}>{t('{d} 的', { d })}</option>)}
        </select>}
      </>}
      {kind === 'became' && <>{classSel()}<span className="text-xs">(</span>{num(c.within, v => onChange(x => { x.within = v }), 'w-14')}<span className="text-xs">{t('秒內)')}</span></>}
      {kind === 'count' && <><span className="text-xs">{t('在')}</span>{num(c.within, v => onChange(x => { x.within = v }), 'w-16')}<span className="text-xs">{t('秒內變成')}</span>{classSel()}
        {opSel(['gte', 'gt', 'lte', 'lt'])}<ValueInput value={c.times} def={1} w="w-14" onChange={v => onChange(x => { x.times = v })} /><span className="text-xs">{t('次')}</span></>}
      {kind === 'change' && <><span className="text-xs">{t('在')}</span>{num(c.within, v => onChange(x => { x.within = v }), 'w-14')}<span className="text-xs">{t('秒內')}{c.dir === 'rise' ? t('上升') : t('下降')}</span>
        <ValueInput value={c.amount} def={0.1} w="w-14" scale={st?.type === 'number' ? 1 : 100} onChange={v => onChange(x => { x.amount = v })} />
        <span className="text-xs">{t('{p1} 以上', { p1: isRef(c.amount) ? '' : st?.type === 'number' ? st.unit ?? '' : '%' })}</span></>}
      {kind === 'var' && <ValueInput value={c.value as NumVal} def={0} w="w-20" onChange={v => onChange(x => { x.value = v })} />}
      {kind === 'elapsed' && <>{opSel(['gt', 'gte', 'lt', 'lte'])}
        <ValueInput value={c.value as NumVal} def={600} scale={1 / 60} onChange={v => onChange(x => { x.value = v })} /><span className="text-xs">{isRef(c.value) ? t('秒') : t('分鐘')}</span></>}
      {kind === 'visible' && <>
        <select className={input} value={c.target?.param != null ? `__p:${c.target.param}` : `__b:${c.target?.button ?? ''}`}
          onChange={e => onChange(x => { const v = e.target.value; x.target = v.startsWith('__p:') ? { param: v.slice(4) } : { button: v.slice(4) } })}>
          {params.filter(p => p.type === 'point').map(p => <option key={p.name} value={`__p:${p.name}`}>{t('參數「{p1}」', { p1: p.label || p.name })}</option>)}
          {buttonGroups(env.info?.buttons.filter(b => b.find) ?? [], env.info?.lists ?? [])}
        </select>
      </>}
      {kind === 'time' && <>
        <input type="time" className={input} value={c.from ?? '00:00'} onChange={e => onChange(x => { x.from = e.target.value })} />~
        <input type="time" className={input} value={c.to ?? '23:59'} onChange={e => onChange(x => { x.to = e.target.value })} />
        <span className="flex gap-0.5 text-xs" title={t('不勾 = 每天')}>{DAYS.map((d, i) => (
          <button key={i} onClick={() => onChange(x => { const ds = new Set(x.days ?? []); if (ds.has(i)) ds.delete(i); else ds.add(i); x.days = [...ds].sort() })}
            className={`w-6 h-6 rounded border ${(c.days ?? []).includes(i) ? 'bg-stone-900 text-white border-stone-900' : 'bg-white border-stone-300'}`}>{d}</button>
        ))}</span>
        <span className="text-[11px] text-stone-400">{t('可以跨午夜,例如 22:00~06:00')}</span></>}
      {kind === 'always' && <span className="text-xs text-stone-500">{t('(搭配「冷卻」= 每隔一段時間做一次)')}</span>}
      {kind === 'compare' && <>
        <ValueInput value={c.left} def={0} w="w-16" onChange={v => onChange(x => { x.left = v })} />
        {opSel(['gte', 'gt', 'lte', 'lt', 'is', 'is_not'])}
        <ValueInput value={c.right} def={0} w="w-16" onChange={v => onChange(x => { x.right = v })} />
      </>}
      {adv && canHold && held}
      {adv && confOk && conf}
      {!adv && hasAdv && <button className="text-[11px] text-stone-500 underline" onClick={() => setMore(true)} title={t('持續幾秒才算、模型要多有把握')}>{t('更多…')}</button>}
      <span className="flex-1" />
      <button className="text-xs text-stone-400 hover:text-rose-600" onClick={onDelete} title={t('刪除這個條件')}>✕</button>
      {onOpen && <button className="text-xs px-2 py-0.5 rounded border border-stone-300 hover:bg-stone-50" onClick={() => onOpen(false)} title={t('收成一句')}>{t('完成 ✓')}</button>}
    </div>
  )
}

/** a tap position: a named on-screen element, x/y picked on a frame, or (inside a sub-script) one of its point parameters */
function TargetEditor({ tx, params = [], device, noPerDevice, fromList, onChange }: {
  tx: ScriptPoint; params?: SubParam[]; device?: string; noPerDevice?: boolean; fromList?: string; onChange: (tx: ScriptPoint) => void
}) {
  const [pick, setPick] = useState(false)
  const env = useContext(CondEnv)
  const lib = (env.info?.buttons ?? []).filter(b => !fromList || b.list === fromList)     // "from a list": only its names
  const value = tx.param != null ? `__p:${tx.param}` : tx.button != null ? `__b:${tx.button}` : tx.x != null ? '__xy' : ''
  return (
    <span className="flex flex-col gap-1">
      <span className="flex flex-wrap gap-1.5 items-center">
        <select className={input} value={value} onChange={e => {
          const v = e.target.value
          onChange(v === '__xy' ? { x: Math.round(screen.w / 2), y: Math.round(screen.h / 2) } : v.startsWith('__p:') ? { param: v.slice(4) } : v.startsWith('__b:') ? { button: v.slice(4) } : {})
        }}>
          {value === '' && <option value="">{t('(請選擇要點的位置)')}</option>}
          {params.filter(p => p.type === 'point').map(p => <option key={p.name} value={`__p:${p.name}`}>{t('參數「{p1}」', { p1: p.label || p.name })}</option>)}
          {buttonGroups(lib, env.info?.lists ?? [], device, noPerDevice, tx.button)}
          <option value="__xy">{t('自訂位置…')}</option>
        </select>
        {tx.x != null && tx.param == null && tx.button == null && (
          <span className="flex items-center gap-1 text-xs num">
            x <input type="number" className={`${input} w-16`} value={tx.x ?? 0} onChange={e => onChange({ x: Math.round(Number(e.target.value)), y: tx.y ?? 0 })} />
            y <input type="number" className={`${input} w-16`} value={tx.y ?? 0} onChange={e => onChange({ x: tx.x ?? 0, y: Math.round(Number(e.target.value)) })} />
          </span>
        )}
        {tx.param == null && tx.button == null && <Button variant="ghost" onClick={() => setPick(p => !p)}>{pick ? t('收起畫面') : t('在畫面上選')}</Button>}
      </span>
      {pick && tx.param == null && tx.button == null && <PointPicker point={tx.x != null ? { x: tx.x, y: tx.y ?? 0 } : null} onPick={(x, y) => onChange({ x, y })} />}
    </span>
  )
}

/** Button choices: the library, then each list's names (shared lists; per-device lists: only that device's when given). */
function buttonGroups(lib: LibButton[], lists: ListInfo[], device?: string, noPerDevice?: boolean, current?: string) {
  const per = new Set(lists.filter(l => l.per_device).map(l => l.id))
  const title = (id: string) => lists.find(l => l.id === id)?.title ?? id
  const shared = lib.filter(b => !b.list)
  const sharedLists = [...new Set(lib.filter(b => b.list && !per.has(b.list)).map(b => b.list!))].sort()
  const devLists = noPerDevice ? [] : [...new Set(lib.filter(b => b.list && per.has(b.list)).map(b => `${b.device ?? ''}|${b.list}`))]
    .filter(k => !device || k.startsWith(`${device}|`)).sort()
  const cur = lib.find(b => b.id === current && b.list && per.has(b.list) && (noPerDevice || (device && b.device !== device)))
  return <>
    {cur && <option value={`__b:${cur.id}`}>{t('{label}({device} 的{p3})', { label: cur.label, device: cur.device, p3: title(cur.list!) })}</option>}
    {shared.length > 0 && <optgroup label={t('按鈕庫')}>{shared.map(b => <option key={b.id} value={`__b:${b.id}`}>{b.label}{b.find ? t('(找圖)') : ''}</option>)}</optgroup>}
    {sharedLists.map(l => <optgroup key={l} label={t('清單:{p1}', { p1: title(l) })}>{lib.filter(b => b.list === l).sort((x, y) => x.label.localeCompare(y.label, 'zh-Hant', { numeric: true })).map(b =>
      <option key={b.id} value={`__b:${b.id}`}>{b.label}</option>)}</optgroup>)}
    {devLists.map(k => { const [d, l] = k.split('|'); return <optgroup key={k} label={t('{d} 的{p2}', { d, p2: title(l) })}>{lib.filter(b => b.list === l && (b.device ?? '') === d).map(b =>
      <option key={b.id} value={`__b:${b.id}`}>{b.label}</option>)}</optgroup> })}
  </>
}

/** values for a called sub-script's parameters */
export function ArgsEditor({ sub, args, info, callerParams, device, shared, onChange }: {
  sub: SubScript; args: Record<string, ArgValue>; info: ScriptsInfo; callerParams: SubParam[]; device?: string
  shared?: boolean                       // values for every device: a per-device list's names differ, so none here
  onChange: (a: Record<string, ArgValue>) => void
}) {
  const ps = sub.params ?? []
  if (!ps.length) return null
  return (
    <div className="flex flex-col gap-1.5 pl-3 border-l-2 border-sky-200">
      {ps.map(p => {
        const v = args[p.name] ?? p.default
        const bound = settingOf(v)
        const usable = (info.settings ?? []).filter(s => fitsParam(s, p))
        const decl = info.settings?.find(s => s.id === bound)
        const fromList = info.lists.find(l => l.id === p.from_list)
        return (
          <div key={p.name} className="flex flex-wrap items-center gap-1.5 text-sm">
            <span className="text-xs text-sky-800 w-24">{p.label || p.name}</span>
            {usable.length > 0 && <select className={`${input} text-xs`} value={bound ?? ''} title={t('使用者設定:值由使用者在操作面板上選,執行開始時才讀')}
              onChange={e => { const n = { ...args }; if (e.target.value) n[p.name] = { setting: e.target.value }; else delete n[p.name]; onChange(n) }}>
              <option value="">{t('自己填')}</option>
              {usable.map(s => <option key={s.id} value={s.id}>{t('用使用者設定「{label}」', { label: s.label })}</option>)}
            </select>}
            {bound
              ? <span className="text-xs px-1.5 py-0.5 rounded bg-violet-50 border border-violet-200 text-violet-900">
                  {decl ? t('由使用者決定({scope}),到「素材庫 › 使用者設定」看目前的值', { scope: decl.scope === 'device' ? t('每台各自') : t('全部共用') }) : t('找不到使用者設定「{bound}」', { bound })}</span>
              : shared && fromList?.per_device
              ? <span className="text-xs text-stone-500">{t('每台的「{title}」不一樣,請在下面各台分別選', { title: fromList.title })}</span>
              : p.type === 'list'
              ? fromList && !(v && !Array.isArray(v) && typeof v === 'object' && 'param' in v)
                ? <ListItemsPicker v={v} info={info} list={fromList} device={device} onChange={nv => onChange({ ...args, [p.name]: nv })} />
                : <ListArg p={p} v={v} callerParams={callerParams} onChange={nv => onChange({ ...args, [p.name]: nv })} />
              : p.type === 'point'
              ? <TargetEditor tx={(v as ScriptPoint) ?? {}} params={callerParams} device={device} noPerDevice={shared} fromList={p.from_list}
                  onChange={tx => onChange({ ...args, [p.name]: tx })} />
              : <input type={p.type === 'number' ? 'number' : 'text'} className={`${input} w-40`} value={v == null ? '' : String(v)}
                  onChange={e => onChange({ ...args, [p.name]: p.type === 'number' ? Number(e.target.value) : e.target.value })} />}
          </div>
        )
      })}
    </div>
  )
}

/** a name of a per-device list (shown in 素材庫 › 清單, not with the shared buttons) */
export const perDeviceItem = (info: ScriptsInfo, b: LibButton) => !!info.lists.find(l => l.id === b.list)?.per_device

const settingOf = (v: ArgValue | undefined) => v && typeof v === 'object' && !Array.isArray(v) && 'setting' in v ? (v as { setting: string }).setting : null

/** can this user setting be passed as this parameter? */
function fitsParam(s: SettingDecl, p: SubParam) {
  if (s.type !== p.type) return false
  const want = p.from_list ? `list:${p.from_list}` : null          // a parameter "from a list" takes only that list's names
  if (p.type === 'point') return !want || s.pick_from === want
  if (p.type !== 'list') return true
  if ((s.item ?? 'point') !== (p.item ?? 'point')) return false
  return !want || s.pick_from === want
}

/** Names of one list to go through (a per-device list: that device's), ticked in order; ◀▶ to reorder. */
function ListItemsPicker({ v, info, list, device, onChange }: { v: ArgValue | undefined; info: ScriptsInfo; list: ListInfo; device?: string; onChange: (v: ArgValue) => void }) {
  const chosen = ((Array.isArray(v) ? v : []) as ScriptPoint[]).map(x => x.button ?? '')
  const all = info.buttons.filter(b => b.list === list.id && (!list.per_device || !device || b.device === device))
  const name = (id: string) => info.buttons.find(b => b.id === id)?.label ?? t('{id}(已刪除)', { id })
  const set = (ids: string[]) => onChange(ids.map(button => ({ button })))
  if (!all.length) return <span className="text-xs text-rose-700">{device && list.per_device ? t('{device} 的', { device }) : ''}{t('「{title}」還是空的。到「素材庫 › 清單」擷取。', { title: list.title })}</span>
  return (
    <div className="flex flex-col gap-1.5">
      {chosen.length > 0 && <div className="flex flex-wrap gap-1 items-center">
        {chosen.map((id, k) => (
          <span key={id} className="text-xs px-1.5 py-0.5 rounded bg-emerald-100 text-emerald-900 flex items-center gap-1">
            <span className="num">{k + 1}.</span>{name(id)}
            <button disabled={k === 0} className="disabled:opacity-30" onClick={() => { const n = [...chosen]; [n[k - 1], n[k]] = [n[k], n[k - 1]]; set(n) }}>◀</button>
            <button disabled={k === chosen.length - 1} className="disabled:opacity-30" onClick={() => { const n = [...chosen]; [n[k + 1], n[k]] = [n[k], n[k + 1]]; set(n) }}>▶</button>
          </span>
        ))}
      </div>}
      <div className="flex flex-wrap gap-2">
        {all.map(b => (
          <label key={b.id} className="flex items-center gap-1 text-xs border border-stone-200 rounded px-1.5 py-0.5 bg-white" title={b.device}>
            <input type="checkbox" checked={chosen.includes(b.id)} onChange={e => set(e.target.checked ? [...chosen, b.id] : chosen.filter(x => x !== b.id))} />
            <img src={buttonImageUrl(b.id, b.updated)} alt="" className="h-4" />{b.label}{!device && list.per_device && <span className="text-stone-400">({dn(b.device)})</span>}
          </label>
        ))}
      </div>
    </div>
  )
}

/** A list argument: its items one by one, or the caller's own list parameter passed along. */
function ListArg({ p, v, callerParams, onChange }: {
  p: SubParam; v: ArgValue | undefined; callerParams: SubParam[]; onChange: (v: ArgValue) => void
}) {
  const passed = !!v && !Array.isArray(v) && typeof v === 'object' && 'param' in v ? (v as { param: string }).param : null
  const lists = callerParams.filter(x => x.type === 'list')
  const items = (Array.isArray(v) ? v : []) as ArgItem[]
  const item = p.item ?? 'point'
  const set = (fn: (xs: ArgItem[]) => void) => { const n = [...items]; fn(n); onChange(n) }
  return (
    <div className="flex flex-col gap-1">
      {lists.length > 0 && <select className={input} value={passed ?? ''} onChange={e => onChange(e.target.value ? { param: e.target.value } : [])}>
        <option value="">{t('自己填')}</option>
        {lists.map(x => <option key={x.name} value={x.name}>{t('用參數「{p1}」', { p1: x.label || x.name })}</option>)}
      </select>}
      {!passed && <>
        {items.map((it, k) => (
          <div key={k} className="flex flex-wrap items-center gap-1">
            <span className="text-xs text-stone-500 num w-6">{k + 1}.</span>
            {item === 'point'
              ? <TargetEditor tx={(it as ScriptPoint) ?? {}} params={callerParams} onChange={tx => set(xs => { xs[k] = tx })} />
              : <input type={item === 'number' ? 'number' : 'text'} className={`${input} w-36`} value={String(it ?? '')}
                  onChange={e => set(xs => { xs[k] = item === 'number' ? Number(e.target.value) : e.target.value })} />}
            <button className="text-xs text-stone-400 hover:text-stone-900 disabled:opacity-30" disabled={k === 0} onClick={() => set(xs => { [xs[k - 1], xs[k]] = [xs[k], xs[k - 1]] })}>▲</button>
            <button className="text-xs text-stone-400 hover:text-stone-900 disabled:opacity-30" disabled={k === items.length - 1} onClick={() => set(xs => { [xs[k + 1], xs[k]] = [xs[k], xs[k + 1]] })}>▼</button>
            <button className="text-xs text-stone-400 hover:text-rose-700" onClick={() => set(xs => { xs.splice(k, 1) })}>✕</button>
          </div>
        ))}
        <button className="text-xs underline text-stone-700 self-start" onClick={() => set(xs => { xs.push(item === 'point' ? {} : item === 'number' ? 0 : '') })}>{t('+ 加一項')}</button>
      </>}
    </div>
  )
}

/** Click on a frame (live frame if the scripts are running, else a recorded one) to set the tap position. */
function PointPicker({ point, onPick }: { point: { x: number; y: number } | null; onPick: (x: number, y: number) => void }) {
  const ref = useRef<HTMLDivElement>(null)
  const shadow = useQuery({ queryKey: ['shadow'], queryFn: api.shadowStatus })
  const frames = useQuery({ queryKey: ['randomFrames', 'pick'], queryFn: () => api.randomFrames(1, 3) })
  const live = shadow.data?.status.devices?.find(d => d.window)
  const src = live ? shadowLiveUrl(live.name, Math.floor(shadow.data?.status.updated ?? 0)) : frames.data?.[0] ? imageUrl(frames.data[0]) : null
  return (
    <div className="flex flex-col gap-1">
      <div ref={ref} className="relative w-full max-w-3xl aspect-video bg-stone-900 rounded-md overflow-hidden cursor-crosshair"
        onClick={e => {
          const r = ref.current!.getBoundingClientRect()
          onPick(Math.round(((e.clientX - r.left) / r.width) * screen.w), Math.round(((e.clientY - r.top) / r.height) * screen.h))
        }}>
        {src && <img src={src} alt="" className="absolute inset-0 w-full h-full" />}
        {point && <span className="absolute w-5 h-5 -ml-2.5 -mt-2.5 rounded-full border-4 border-amber-400 bg-amber-400/40"
          style={{ left: `${(point.x / screen.w) * 100}%`, top: `${(point.y / screen.h) * 100}%` }} />}
      </div>
      <span className="text-xs text-stone-500">{t('在畫面上點一下,就會設成點擊位置(座標是專案的 {w}×{h})', { w: screen.w, h: screen.h })}{live ? t(',畫面來自 {name} 現在的畫面', { name: live.name }) : ''}</span>
    </div>
  )
}

function TryRun({ s, states }: { s: Script; states: StateDef[] }) {
  const run = useMutation({ mutationFn: () => api.scriptTest(s) })
  const name = (sid: string, v: unknown) => {
    const st = states.find(x => x.id === sid)
    return `${st?.name ?? sid} ${st?.classes?.find(c => c.value === v)?.name ?? (typeof v === 'number' && st?.type === 'ratio' ? `${Math.round(v * 100)}%` : String(v))}`
  }
  return (
    <Card title={t('用現在的畫面算一次')} extra={<Button onClick={() => run.mutate()} disabled={run.isPending}>{run.isPending ? t('計算中…') : t('算一次')}</Button>}>
      <ErrorText error={run.error} />
      {!run.data ? <p className="text-sm text-stone-500">{t('不用儲存也能試:用目前編輯中的規則,判斷每台{device}現在會做什麼(這裡忽略「持續幾秒」)。需要腳本正在執行或執行過。', { device: words.device })}</p> : (
        <div className="flex flex-col gap-2 text-sm">
          {!run.data.running && <p className="text-xs text-amber-700">{t('腳本目前沒有在執行,用的是最後一次看到的畫面狀態。')}</p>}
          {run.data.results.map(r => (
            <div key={r.device} className="border border-stone-200 rounded-md px-3 py-2">
              <div className="flex justify-between"><span className="font-medium">{dn(r.device)}</span>
                <span className={r.tap || r.action === 'call' ? 'text-amber-800 font-semibold' : ''}>{r.tap || r.action === 'call' ? t('會做:{text}', { text: r.text }) : r.text}</span></div>
              <div className="text-xs text-stone-600">{r.reason}{r.rule_name ? t(' · 規則「{rule_name}」', { rule_name: r.rule_name }) : ''}</div>
              <div className="text-[11px] text-stone-400">{r.state ? Object.entries(r.state).map(([k, v]) => name(k, v.value)).join(t('、')) : t('沒有畫面')}</div>
            </div>
          ))}
        </div>
      )}
    </Card>
  )
}

// ================================================================ sub-scripts
/** where a step list is: a sub-script (no place), a rule of a main script / the guard rules, a situation's entry */
interface Place { kind: 'rule' | 'enter'; guard: boolean; situations: { id: string; name: string }[] }
interface Ctx { info: ScriptsInfo; states: StateDef[]; params: SubParam[]; selfId: string; place?: Place }
const ITEM_TYPES: Record<string, string> = { point: t('位置'), number: t('數字'), text: t('文字') }

function loopParams(st: SubStep, params: SubParam[]): SubParam[] {
  const lst = params.find(p => p.name === st.list)
  const v = st.as || 'item'
  const label = st.as_label || t('目前的{item}', { item: lst?.label || lst?.name || t('項目') })
  return [{ name: v, label, type: lst?.item ?? 'point', ...(lst?.from_list ? { from_list: lst.from_list } : {}) }, { name: `${v}_no`, label: t('{label}是第幾個', { label }), type: 'number' }]
}

function newStep(type: string, ctx: Ctx): SubStep {
  const cond = () => [[defaultCond(ctx.states)]]
  switch (type) {
    case 'tap': return { type, target: {} }
    case 'long_press': return { type, target: {}, ms: 800 }
    case 'pick': return { type, target: { param: ctx.params.find(p => p.type === 'point')?.name ?? '' }, max_swipes: 25 }
    case 'swipe': return { type, from: { x: 640, y: 500 }, to: { x: 640, y: 300 }, ms: 400 }
    case 'wait': return { type, seconds: 1 }
    case 'wait_until': return { type, when: cond(), timeout: 10, on_timeout: 'fail' }
    case 'if': return { type, when: cond(), then: [{ type: 'wait', seconds: 1 }], else: [] }
    case 'retry': return { type, times: 3, delay: 1, steps: [{ type: 'wait', seconds: 1 }] }
    case 'repeat_until': return { type, when: cond(), max_times: 10, max_seconds: 120, steps: [{ type: 'back' }] }
    case 'for_each': return { type, list: ctx.params.find(p => p.type === 'list')?.name, as: 'item', as_label: '', on_item_fail: 'fail', steps: [{ type: 'wait', seconds: 1 }] }
    case 'call': return { type, sub: ctx.info.subs.find(s => s.id !== ctx.selfId)?.id, args: {}, on_fail: 'fail' }
    case 'set_var': return { type, var: ctx.info.variables[0]?.name, mode: 'add', value: 1 }
    case 'output': return { type, output: ctx.info.outputs[0]?.id, command: '' }
    case 'input_text': return { type, text: '' }
    case 'capture_list': return { type, list: ctx.info.lists[0]?.id, timeout: 300 }
    case 'ask': return { type, text: '', timeout: 300, default: 0, options: [{ label: t('好'), then: [] }, { label: t('不要'), then: [] }] }
    case 'goto': return { type, situation: ctx.place?.situations[0]?.id }
    case 'notify': return { type, text: '' }
    case 'stop': return { type, text: '' }
    default: return { type }
  }
}

/** where a list of steps sits in the sub-script: ['steps'], ['cleanup'], ['steps', 3, 'then'], ... */
type ListPath = (string | number)[]
type StepDrag = { list: ListPath; index: number; type: string }
const StepDnd = createContext<{ drag: StepDrag | null; start: (d: StepDrag | null) => void; drop: (list: ListPath, at: number) => void } | null>(null)
/** which step is open for editing (one at a time; the others are one line each) */
const StepFocus = createContext<{ open: string | null; setOpen: (k: string | null) => void } | null>(null)

/** drag and drop + "which step is open" for the step lists of one object (a sub-script, a rule, a situation) */
function StepsRoot({ onRoot, children }: { onRoot: (fn: (root: Record<string, unknown>) => void) => void; children: ReactNode }) {
  const [drag, setDrag] = useState<StepDrag | null>(null)
  const [open, setOpen] = useState<string | null>(null)
  const dnd = { drag, start: setDrag, drop: (list: ListPath, at: number) => { const d = drag; setDrag(null); setOpen(null); if (d) onRoot(x => moveStep(x, d, list, at)) } }
  return <StepDnd.Provider value={dnd}><StepFocus.Provider value={{ open, setOpen }}>{children}</StepFocus.Provider></StepDnd.Provider>
}

/** a short help line for each kind of step (the step menu) */
const STEP_HINT: Record<string, string> = {
  tap: t('點畫面上的按鈕或位置'), long_press: t('按住不放'), swipe: t('從一點滑到另一點'), back: t('按 Android 返回鍵'),
  input_text: t('在輸入框打字'), pick: t('在會捲動的清單裡找到名字並點它'), launch_app: t('開啟 App(已開著就切到前面)'),
  capture_list: t('把清單從頭滑到尾,記下名字'), wait: t('等固定的秒數'), wait_until: t('等到畫面或數字符合條件'),
  if: t('依條件做不同的事'), repeat_until: t('重複做,直到條件成立'), for_each: t('清單裡每一個都做一次'), retry: t('裡面失敗了就重來'),
  call: t('執行另一個子腳本'), succeed: t('到這裡就結束(算成功)'), fail: t('到這裡就結束(算失敗)'), stop: t('讓這台停下來,等你按「繼續」'),
  goto: t('主腳本換到另一個情境'), notify: t('傳一則通知給你'), ask: t('問你,等你回答再決定'), output: t('送指令到外部設備'),
  set_var: t('記下數字或時間,之後的條件可以用'), stay: t('什麼都不做,也不讓下面的規則做(等畫面變)'), hold: t('條件成立的期間,其他腳本都不動'),
}
const GROUP_TONE = ['bg-sky-100 text-sky-900', 'bg-amber-100 text-amber-900', 'bg-violet-100 text-violet-900', 'bg-stone-200 text-stone-800',
  'bg-emerald-100 text-emerald-900', 'bg-teal-100 text-teal-900', 'bg-rose-100 text-rose-900']
const toneOf = (info: ScriptsInfo, type: string) => GROUP_TONE[Math.max(0, info.step_groups.findIndex(([, ts]) => ts.includes(type)))] ?? GROUP_TONE[3]

/** the kinds of step a list may hold: a cleanup list only simple ones; goto / stay / hold only where they mean something */
function stepTypes(ctx: Ctx, depth: number, allowed?: string[]): [string, string][] {
  const p = ctx.place
  return Object.entries(ctx.info.step_types).filter(([k]) => {
    if (allowed && !allowed.includes(k)) return false
    if (k === 'goto') return !!p && !p.guard
    if (k === 'stay') return p?.kind === 'rule' && depth === 0
    if (k === 'hold') return p?.kind === 'rule' && p.guard && depth === 0
    return true
  })
}

const samePath = (a: ListPath, b: ListPath) => a.length === b.length && a.every((k, i) => k === b[i])
const startsWith = (a: ListPath, pre: ListPath) => a.length >= pre.length && pre.every((k, i) => k === a[i])

function listAt(root: object, path: ListPath): SubStep[] {
  let o = root as Record<string | number, unknown>
  path.forEach((k, i) => {
    if (i === path.length - 1 && o[k] == null) o[k] = []
    o = o[k] as Record<string | number, unknown>
  })
  return o as unknown as SubStep[]
}

/** can the dragged step go to gap `at` of list `list`? (not into itself, not a step the list does not allow, not where it already is) */
function canDrop(d: StepDrag | null, list: ListPath, at: number, allowed?: string[]) {
  if (!d) return false
  if (allowed && !allowed.includes(d.type)) return false
  if (startsWith(list, [...d.list, d.index])) return false
  return !(samePath(d.list, list) && (at === d.index || at === d.index + 1))
}

function moveStep(root: object, from: StepDrag, list: ListPath, at: number) {
  const [it] = listAt(root, from.list).splice(from.index, 1)
  const to = [...list]
  const k = from.list.length
  if (to.length > k && startsWith(to, from.list) && (to[k] as number) > from.index) to[k] = (to[k] as number) - 1   // a later sibling's branch
  if (samePath(from.list, to) && at > from.index) at -= 1
  listAt(root, to).splice(at, 0, it)
}

/** step numbers of the 否則如果 branches: 3.b1, 3.c1, ... (3.1 = 成立時, 3.否1 = 否則) */
const ELIF_MARK = 'bcdefghijklmnopqrstu'

/** the 否則 holds nothing but one 如果: it can become 否則如果 of this step (the same meaning, one level less) */
const canFlatten = (st: SubStep) => st.type === 'if' && (st.else ?? []).length === 1 && st.else![0].type === 'if'

function flattenElse(st: SubStep) {
  while (canFlatten(st)) {
    const inner = st.else![0]
    st.elif = [...(st.elif ?? []), { when: inner.when ?? [], then: inner.then ?? [] }, ...(inner.elif ?? [])]
    st.else = inner.else ?? []
  }
}

const BLOCK_STYLE: Record<string, string> = { if: 'border-violet-300', retry: 'border-amber-300', repeat_until: 'border-sky-300', for_each: 'border-emerald-400', ask: 'border-rose-300' }

function StepList({ steps, ctx, onChange, path, allowed, depth = 0, prefix = '', empty, compact }: {
  steps: SubStep[]; ctx: Ctx; onChange: (fn: (s: SubStep[]) => void) => void; path: ListPath; allowed?: string[]; depth?: number; prefix?: string
  empty?: string; compact?: boolean      // compact: the trailing "+ 新增步驟" only shows on hover (a block that is one line)
}) {
  const types = stepTypes(ctx, depth, allowed)
  const focus = useContext(StepFocus)
  const add = (at: number, type: string) => {
    onChange(x => { x.splice(at, 0, newStep(type, ctx)) })
    focus?.setOpen(JSON.stringify([...path, at]))           // the new step opens for editing
  }
  const dnd = useContext(StepDnd)
  const gap = (at: number, last?: boolean) => dnd?.drag
    ? <DropLine active={canDrop(dnd.drag, path, at, allowed)} onDrop={() => dnd.drop(path, at)} label={t('移到第 {prefix}{p2} 步', { prefix, p2: at + 1 })} />
    : <InsertBar types={types} info={ctx.info} where={`${prefix}${at + 1}`} onAdd={tx => add(at, tx)} last={last && !(compact && steps.length > 0)} />
  return (
    <div className="flex flex-col gap-0.5">
      {!steps.length && empty && !dnd?.drag && <div className="text-xs text-stone-400 pl-1">{empty}</div>}
      {steps.map((st, i) => (
        <Fragment key={i}>
          {gap(i)}
          <StepRow st={st} i={i} n={steps.length} ctx={ctx} types={types} depth={depth} allowed={allowed} no={`${prefix}${i + 1}`} path={path}
            onChange={fn => onChange(x => fn(x[i]))}
            onReplace={ns => onChange(x => { x[i] = ns })}
            onMove={d => { focus?.setOpen(null); onChange(x => { const [it] = x.splice(i, 1); x.splice(i + d, 0, it) }) }}
            onDelete={() => { focus?.setOpen(null); onChange(x => { x.splice(i, 1) }) }} />
        </Fragment>
      ))}
      {gap(steps.length, true)}
      {dnd?.drag && !steps.length && <div className="text-[11px] text-stone-400 pl-1">{t('(空的,可以拖到這裡)')}</div>}
    </div>
  )
}

/** "+ 插入步驟" between two steps (shows on hover) and at the end of a list (always shown): a menu of the kinds of
 *  step, grouped (操作畫面 / 等待 / 判斷與重複 ...), each with a line of what it does. */
function InsertBar({ types, info, where, onAdd, last }: { types: [string, string][]; info: ScriptsInfo; where: string; onAdd: (type: string) => void; last?: boolean }) {
  const [open, setOpen] = useState(false)
  const ok = new Set(types.map(([k]) => k))
  const groups = info.step_groups.map(([g, ts]) => [g, ts.filter(tx => ok.has(tx))] as [string, string[]]).filter(([, ts]) => ts.length)
  if (open) return (
    <div className="my-1 rounded-md border border-sky-300 bg-sky-50 p-2 flex flex-col gap-2 text-xs">
      <div className="flex items-center gap-2"><span className="text-sky-900">{t('在第')} <b className="num">{where}</b> {t('步的位置加入:')}</span>
        <span className="flex-1" /><button className="text-stone-500 underline" onClick={() => setOpen(false)}>{t('取消')}</button></div>
      <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
        {groups.map(([g, ts], gi) => (
          <div key={g} className="flex flex-col gap-1">
            <div className="font-semibold text-stone-600">{g}</div>
            {ts.map(tx => (
              <button key={tx} className="text-left rounded px-2 py-1 bg-white border border-stone-200 hover:border-sky-400 hover:bg-white flex flex-col"
                onClick={() => { onAdd(tx); setOpen(false) }}>
                <span className="flex items-center gap-1.5"><span className={`rounded px-1 text-[11px] ${GROUP_TONE[info.step_groups.findIndex(([x]) => x === g)] ?? GROUP_TONE[gi]}`}>{info.step_types[tx]}</span></span>
                <span className="text-[11px] text-stone-500">{STEP_HINT[tx] ?? ''}</span>
              </button>
            ))}
          </div>
        ))}
      </div>
    </div>
  )
  return last
    ? <div className="pt-1"><button className="text-xs text-sky-700 underline" onClick={() => setOpen(true)}>{t('+ 新增步驟')}</button></div>
    : <div className="group h-2.5 -my-0.5 flex items-center">
        <button className="hidden group-hover:flex items-center gap-1 w-full text-[11px] leading-none text-sky-700" onClick={() => setOpen(true)}>
          <span className="flex-1 border-t border-dashed border-sky-300" />{t('+ 在這裡插入步驟')}<span className="flex-1 border-t border-dashed border-sky-300" />
        </button>
      </div>
}

/** "然後…" after an input step: go on at once, wait some seconds, or wait until something shows / holds */
function AfterEditor({ st, ctx, onChange }: { st: SubStep; ctx: Ctx; onChange: (fn: (s: SubStep) => void) => void }) {
  const a = st.after
  const mode = a?.until ? 'until' : a?.seconds != null ? 'seconds' : ''
  return (
    <div className="flex flex-col gap-1.5 text-xs">
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="text-stone-600">{t('做完之後')}</span>
        <select className={input} value={mode} onChange={e => onChange(x => {
          if (e.target.value === 'seconds') x.after = { seconds: 1 }
          else if (e.target.value === 'until') x.after = { until: [[defaultCond(ctx.states)]], timeout: 10, on_timeout: 'fail' }
          else delete x.after
        })}>
          <option value="">{t('直接做下一步')}</option><option value="seconds">{t('等幾秒')}</option><option value="until">{t('等到畫面/數字符合條件')}</option>
        </select>
        {mode === 'seconds' && <><ValueInput value={a?.seconds} def={1} step={0.5} onChange={v => onChange(x => { x.after = { seconds: v } })} />{t('秒')}</>}
        {mode === 'until' && <>
          <span>{t('最多等')}</span><ValueInput value={a?.timeout} def={10} onChange={v => onChange(x => { x.after = { ...x.after, timeout: v } })} />{t('秒,逾時就')}
          <select className={input} value={a?.on_timeout ?? 'fail'} onChange={e => onChange(x => { x.after = { ...x.after, on_timeout: e.target.value } })}>
            <option value="fail">{t('算失敗')}</option><option value="continue">{t('繼續下一步')}</option>
          </select>
        </>}
      </div>
      {mode === 'until' && <div className="ml-2"><CondGroups when={a?.until ?? []} states={ctx.states} ops={ctx.info.ops}
        onChange={fn => onChange(x => { x.after = { ...x.after }; x.after.until = x.after.until ?? []; fn(x.after.until) })} /></div>}
    </div>
  )
}

/** steps that take a while or can fail: they may carry plain words for the people running it (say / say_fail) */
const SAYABLE = new Set(['tap', 'long_press', 'pick', 'wait', 'wait_until', 'call', 'capture_list', 'repeat_until', 'ask', 'for_each'])

function StepRow({ st, i, n, ctx, types, depth, allowed, no, path, onChange, onReplace, onMove, onDelete }: {
  st: SubStep; i: number; n: number; ctx: Ctx; types: [string, string][]; depth: number; allowed?: string[]; no: string; path: ListPath
  onChange: (fn: (s: SubStep) => void) => void; onReplace: (s: SubStep) => void; onMove: (d: number) => void; onDelete: () => void
}) {
  const dnd = useContext(StepDnd)
  const ref = useRef<HTMLDivElement>(null)
  const dragging = !!dnd?.drag && samePath(dnd.drag.list, path) && dnd.drag.index === i
  const here = [...path, i]
  const { info, states, params } = ctx
  const block = st.type === 'if' || st.type === 'retry' || st.type === 'repeat_until' || st.type === 'for_each' || st.type === 'ask'
  const target = info.subs.find(s => s.id === st.sub)
  const [say, setSay] = useState(false)
  const focus = useContext(StepFocus)
  const key = JSON.stringify(here)
  const open = focus ? focus.open === key : true
  const [elseOn, setElseOn] = useState(false)
  const moveBtns = <>
    <Button variant="ghost" disabled={i === 0} onClick={() => onMove(-1)} title={t('往上')}>↑</Button>
    <Button variant="ghost" disabled={i === n - 1} onClick={() => onMove(1)} title={t('往下')}>↓</Button>
    <Button variant="ghost" onClick={onDelete} title={t('刪除這一步')}>✕</Button>
  </>
  if (st.type === 'if') {
    // 如果 / 否則如果 / 否則: the same card as a main script's rule ("如果 … 就依序做 …"), one card per branch
    const showElse = elseOn || (st.else ?? []).length > 0
    const card = (head: ReactNode, when: ScriptCond[][] | null, onWhen: ((fn: (w: ScriptCond[][]) => void) => void) | null, body: ReactNode) => (
      <div className="rounded-lg border border-violet-200 bg-white">
        <div className="flex flex-wrap items-center gap-1.5 px-2 pt-1.5 text-sm">{head}</div>
        {when && onWhen && <div className="px-2 pt-1"><CondGroups when={when} states={states} ops={info.ops} onChange={onWhen} /></div>}
        <div className="px-2 pb-2 pt-1.5 flex flex-col gap-1">
          <div className="text-xs text-stone-500">{t('就依序做:')}</div>
          {body}
        </div>
      </div>
    )
    return (
      <ParamsCtx.Provider value={params}><div ref={ref} className={`flex flex-col gap-1 ${dragging ? 'opacity-30' : ''}`}>
        {card(<>
          {dnd && <Grip rowRef={ref} onStart={() => dnd.start({ list: path, index: i, type: st.type })} onEnd={() => dnd.start(null)}
            title={t('拖拉來移動(連同裡面的步驟),可以拖進或拖出其他區塊')} />}
          <span className="text-xs font-semibold bg-stone-700 text-white rounded px-1.5 py-0.5 num">{no}</span>
          <span className="text-xs font-semibold text-violet-800">{t('如果')}</span>
          <span className="flex-1" />{moveBtns}
        </>, st.when ?? [], fn => onChange(x => { x.when = x.when ?? []; fn(x.when) }),
          <StepList steps={st.then ?? []} ctx={ctx} allowed={allowed} depth={depth + 1} prefix={`${no}.`} path={[...here, 'then']}
            onChange={fn => onChange(x => { x.then = x.then ?? []; fn(x.then) })} empty={t('(還沒有步驟)')} />)}
        {(st.elif ?? []).map((e, k) => <Fragment key={k}>{card(<>
          <span className="text-xs font-semibold text-violet-800 pl-1">{t('否則如果')}</span>
          <span className="text-[11px] text-stone-400">{t('(步驟 {no}.{p2}…)', { no, p2: ELIF_MARK[k] })}</span>
          <span className="flex-1" />
          <Button variant="ghost" disabled={k === 0} onClick={() => onChange(x => { const es = x.elif!; [es[k - 1], es[k]] = [es[k], es[k - 1]] })}>↑</Button>
          <Button variant="ghost" disabled={k === (st.elif ?? []).length - 1} onClick={() => onChange(x => { const es = x.elif!; [es[k], es[k + 1]] = [es[k + 1], es[k]] })}>↓</Button>
          <Button variant="ghost" onClick={() => onChange(x => { x.elif!.splice(k, 1); if (!x.elif!.length) delete x.elif })} title={t('拿掉這個「否則如果」')}>✕</Button>
        </>, e.when, fn => onChange(x => fn(x.elif![k].when)),
          <StepList steps={e.then ?? []} ctx={ctx} allowed={allowed} depth={depth + 1} prefix={`${no}.${ELIF_MARK[k]}`} path={[...here, 'elif', k, 'then']}
            onChange={fn => onChange(x => { const b = x.elif![k]; b.then = b.then ?? []; fn(b.then) })} empty={t('(還沒有步驟)')} />)}</Fragment>)}
        {showElse && card(<>
          <span className="text-xs font-semibold text-violet-800 pl-1">{t('否則')}</span><span className="text-[11px] text-stone-400">{t('(以上都不成立時)')}</span>
          <span className="flex-1" />
          <Button variant="ghost" onClick={() => { setElseOn(false); onChange(x => { x.else = [] }) }} title={t('拿掉「否則」')}>✕</Button>
        </>, null, null,
          <StepList steps={st.else ?? []} ctx={ctx} allowed={allowed} depth={depth + 1} prefix={t('{no}.否', { no })} path={[...here, 'else']}
            onChange={fn => onChange(x => { x.else = x.else ?? []; fn(x.else) })} empty={t('(還沒有步驟)')} />)}
        <div className="flex flex-wrap items-center gap-3 pl-2 text-xs">
          <button className="text-violet-700 hover:text-violet-900" disabled={(st.elif ?? []).length >= 20}
            onClick={() => onChange(x => { x.elif = [...(x.elif ?? []), { when: [[defaultCond(states)]], then: [] }] })}>{t('+ 否則如果')}</button>
          {!showElse && <button className="text-violet-700 hover:text-violet-900" onClick={() => setElseOn(true)}>{t('+ 否則(以上都不成立時)')}</button>}
          {canFlatten(st) && <button className="text-violet-700 underline" title={t('「否則」裡只有一個「如果」:把它變成這裡的「否則如果」,意思完全一樣,只是不用一層層往內縮')}
            onClick={() => onChange(x => flattenElse(x))}>{t('把「否則」裡的「如果」攤平成「否則如果」')}</button>}
        </div>
      </div></ParamsCtx.Provider>
    )
  }
  return (
    <ParamsCtx.Provider value={params}><div ref={ref} className={`rounded-md ${dragging ? 'opacity-30' : ''} ${block ? `border-l-4 ${BLOCK_STYLE[st.type]} bg-stone-50 pl-2 py-1.5 pr-1` : ''} ${open && focus ? 'ring-2 ring-sky-300 bg-white p-2' : ''}`}>
      {!open && <div className="group flex items-center gap-1.5 text-sm min-w-0">
        {dnd && <Grip rowRef={ref} onStart={() => dnd.start({ list: path, index: i, type: st.type })} onEnd={() => dnd.start(null)}
          title={block ? t('拖拉來移動(連同裡面的步驟),可以拖進或拖出其他區塊') : t('拖拉來移動,可以拖進或拖出「如果」「重試」「重複」區塊')} />}
        <span className="text-xs font-semibold bg-stone-700 text-white rounded px-1.5 py-0.5 num shrink-0">{no}</span>
        <button className="flex-1 min-w-0 text-left flex items-center gap-2 rounded px-1 py-0.5 hover:bg-sky-50" onClick={() => focus?.setOpen(key)} title={t('點一下編輯這一步')}>
          <span className={`shrink-0 rounded px-1.5 text-[11px] ${toneOf(info, st.type)}`}>{info.step_types[st.type] ?? st.type}</span>
          <span className="truncate">{stepText(st, ctx)}</span>
          {(st.say || st.say_fail) && <span className="shrink-0 text-xs" title={st.say_fail ? t('給使用者看:{say} / 失敗時:{say_fail}', { say: st.say ?? '', say_fail: st.say_fail }) : t('給使用者看:{say}', { say: st.say ?? '' })}>💬</span>}
        </button>
        <span className="hidden group-hover:flex shrink-0">{moveBtns}</span>
      </div>}
      {open && <>
      <div className="flex flex-wrap gap-1.5 items-center text-sm">
        {dnd && <Grip rowRef={ref} onStart={() => dnd.start({ list: path, index: i, type: st.type })} onEnd={() => dnd.start(null)}
          title={block ? t('拖拉來移動(連同裡面的步驟),可以拖進或拖出其他區塊') : t('拖拉來移動,可以拖進或拖出「如果」「重試」「重複」區塊')} />}
        <span className="text-xs font-semibold bg-stone-700 text-white rounded px-1.5 py-0.5 num">{no}</span>
        <select className={input} value={st.type} onChange={e => onReplace(newStep(e.target.value, ctx))} title={t('換成另一種步驟')}>
          {types.map(([k, tx]) => <option key={k} value={k}>{tx}</option>)}
        </select>
        {(st.type === 'tap' || st.type === 'long_press' || st.type === 'pick') && <>
          <TargetEditor tx={st.target ?? {}} params={params} onChange={tx => onChange(x => { x.target = tx })} />
          <input className={`${input} w-28`} placeholder={t('說明(可不填)')} value={st.label ?? ''} onChange={e => onChange(x => { x.label = e.target.value || undefined })} />
        </>}
        {st.type === 'pick' && <>
          <label className="flex items-center gap-1 text-xs" title={t('清單滑動後會慣性滑一下:看到名稱停在同一個位置這麼久,才點下去')}>{t('停穩')}<ValueInput value={st.settle} def={1} w="w-14" step={0.5} onChange={v => onChange(x => { x.settle = v })} />{t('秒才點')}</label>
          <label className="flex items-center gap-1 text-xs" title={t('清單沒看到這個名稱時,會自己往上或往下滑來找')}>{t('最多滑')}<ValueInput value={st.max_swipes} def={25} onChange={v => onChange(x => { x.max_swipes = v })} />{t('次')}</label>
        </>}
        {st.type === 'long_press' && <label className="flex items-center gap-1 text-xs">{t('按住')}<ValueInput value={st.ms} def={800} w="w-20" onChange={v => onChange(x => { x.ms = v })} />{t('毫秒')}</label>}
        {st.type === 'swipe' && <span className="flex flex-col gap-1 text-xs">
          <span className="flex items-center gap-1">{t('從')} <TargetEditor tx={st.from ?? {}} params={params} onChange={tx => onChange(x => { x.from = tx })} /></span>
          <span className="flex items-center gap-1">{t('到')} <TargetEditor tx={st.to ?? {}} params={params} onChange={tx => onChange(x => { x.to = tx })} /></span>
          <span className="flex items-center gap-1">{t('花')}<ValueInput value={st.ms} def={400} w="w-20" onChange={v => onChange(x => { x.ms = v })} />{t('毫秒')}</span>
        </span>}
        {st.type === 'wait' && <span className="flex items-center gap-1 text-xs">
          <ValueInput value={st.seconds} def={1} step={0.5} onChange={v => onChange(x => { x.seconds = v })} />{t('秒')}
        </span>}
        {st.type === 'wait_until' && <>
          <label className="flex items-center gap-1 text-xs">{t('最多等')}<ValueInput value={st.timeout} def={10} onChange={v => onChange(x => { x.timeout = v })} />{t('秒')}</label>
          <label className="flex items-center gap-1 text-xs">{t('逾時')}
            <select className={input} value={st.on_timeout ?? 'fail'} onChange={e => onChange(x => { x.on_timeout = e.target.value })}>
              <option value="fail">{t('算失敗(外層有重試就重試)')}</option><option value="continue">{t('繼續下一步')}</option>
            </select></label>
        </>}
        {st.type === 'retry' && <>
          <label className="flex items-center gap-1 text-xs">{t('最多試')}<ValueInput value={st.times} def={3} w="w-14" onChange={v => onChange(x => { x.times = v })} />{t('次')}</label>
          <label className="flex items-center gap-1 text-xs">{t('每次間隔')}<ValueInput value={st.delay} def={0} w="w-14" step={0.5} onChange={v => onChange(x => { x.delay = v })} />{t('秒')}</label>
        </>}
        {st.type === 'repeat_until' && <>
          <label className="flex items-center gap-1 text-xs">{t('最多')}<ValueInput value={st.max_times} def={10} w="w-14" onChange={v => onChange(x => { x.max_times = v })} />{t('次')}</label>
          <label className="flex items-center gap-1 text-xs">{t('或')}<ValueInput value={st.max_seconds} def={600} onChange={v => onChange(x => { x.max_seconds = v })} />{t('秒')}</label>
        </>}
        {st.type === 'for_each' && <>
          <select className={input} value={st.list ?? ''} onChange={e => onChange(x => { x.list = e.target.value })}>
            {!params.some(p => p.type === 'list') && <option value="">{t('(先在「參數」加一個清單)')}</option>}
            {params.filter(p => p.type === 'list').map(p => <option key={p.name} value={p.name}>{p.label || p.name}</option>)}
          </select>
          <label className="flex items-center gap-1 text-xs" title={t('裡面的步驟用這個名字指「目前這一個」(例如點擊的位置選參數「目前這一個」)')}>{t('目前這個叫')}
            <input className={`${input} w-28`} placeholder={t('目前的{item}', { item: params.find(p => p.name === st.list)?.label ?? t('項目') })} value={st.as_label ?? ''}
              onChange={e => onChange(x => { x.as_label = e.target.value })} /></label>
          <label className="flex items-center gap-1 text-xs">{t('某一個失敗時')}
            <select className={input} value={st.on_item_fail ?? 'fail'} onChange={e => onChange(x => { x.on_item_fail = e.target.value })}>
              <option value="fail">{t('整個失敗(停止)')}</option><option value="continue">{t('略過它,繼續下一個')}</option>
            </select></label>
        </>}
        {st.type === 'call' && <>
          <select className={input} value={st.sub ?? ''} onChange={e => onChange(x => { x.sub = e.target.value; x.args = {} })}>
            {info.subs.filter(s => s.id !== ctx.selfId).map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
          </select>
          <label className="flex items-center gap-1 text-xs">{t('它失敗時')}
            <select className={input} value={st.on_fail ?? 'fail'} onChange={e => onChange(x => { x.on_fail = e.target.value; if (e.target.value !== 'continue') delete x.fail_goto })}>
              {Object.entries(info.on_fail).map(([k, tx]) => <option key={k} value={k}>{tx}</option>)}
            </select></label>
          {st.fail_goto && ctx.place && <label className="flex items-center gap-1 text-xs">{t('並切換到')}
            <select className={input} value={st.fail_goto} onChange={e => onChange(x => { if (e.target.value) x.fail_goto = e.target.value; else delete x.fail_goto })}>
              <option value="">{t('(不切換)')}</option>
              {ctx.place.situations.map(x => <option key={x.id} value={x.id}>{x.name}</option>)}
            </select></label>}
        </>}
        {st.type === 'goto' && (ctx.place?.situations.length
          ? <select className={input} value={st.situation ?? ''} onChange={e => onChange(x => { x.situation = e.target.value })}>
              {ctx.place.situations.map(x => <option key={x.id} value={x.id}>{x.name}</option>)}
            </select>
          : <span className="text-xs text-rose-700">{t('只有主腳本的規則能切換情境')}</span>)}
        {(st.type === 'stop' || st.type === 'stay' || st.type === 'hold') &&
          <input className={`${input} w-64`} placeholder={st.type === 'stop' ? t('停下來的原因(會顯示在面板和通知)') : t('說明(可不填)')} value={st.text ?? ''}
            onChange={e => onChange(x => { x.text = e.target.value || undefined })} />}
        {st.type === 'set_var' && <VarAction a={st} info={info} onChange={fn => onChange(x => fn(x))} />}
        {st.type === 'input_text' && <>
          <input className={`${input} w-56`} placeholder={t('要輸入的文字(先點一下輸入框)')} value={st.text ?? ''} onChange={e => onChange(x => { x.text = e.target.value })}
            title={t('輸入到目前有游標的輸入框,所以前一步要先點輸入框。可以用 {參數或變數代號} 帶入目前的值')} />
        </>}
        {st.type === 'output' && <OutputFields a={st} info={info} onChange={fn => onChange(x => fn(x))} />}
        {st.type === 'capture_list' && <>
          <select className={input} value={st.list ?? ''} onChange={e => onChange(x => { x.list = e.target.value })}>
            {info.lists.map(l => <option key={l.id} value={l.id}>{l.title}{l.per_device ? t('(每台各自)') : ''}</option>)}
          </select>
          <label className="flex items-center gap-1 text-xs" title={t('從頭滑到尾要多久;超過就算失敗')}>{t('最多')}<ValueInput value={st.timeout} def={300} onChange={v => onChange(x => { x.timeout = v })} />{t('秒')}</label>
          <span className="text-xs text-stone-500">{t('要先在這個清單的畫面上')}</span>
        </>}
        {st.type === 'ask' && <>
          <input className={`${input} w-72`} placeholder={t('要問的問題,例如:存量不夠了,要回去補充嗎?')} value={st.text ?? ''} onChange={e => onChange(x => { x.text = e.target.value })}
            title={t('會送到配對過的 Discord / Telegram(每個選項一個按鈕),也會出現在執行頁和操作面板;可以用 {變數或參數的代號} 帶入目前的值')} />
          <label className="flex items-center gap-1 text-xs">{t('等')}<ValueInput value={st.timeout} def={300} onChange={v => onChange(x => { x.timeout = v })} />{t('秒')}</label>
          <label className="flex items-center gap-1 text-xs">{t('沒人回答就')}
            <select className={input} value={st.default ?? 0} onChange={e => onChange(x => { x.default = Number(e.target.value) })}>
              <option value={0}>{t('算失敗')}</option>
              {(st.options ?? []).map((o, k) => <option key={k} value={k + 1}>{t('選「{label}」', { label: o.label })}</option>)}
            </select></label>
          <label className="flex items-center gap-1 text-xs" title={t('把選了第幾個(1、2…)記到變數,後面的條件可以用;沒人回答又沒有預設 = 0')}>{t('記到變數')}
            <select className={input} value={st.var ?? ''} onChange={e => onChange(x => { x.var = e.target.value || undefined })}>
              <option value="">{t('(不用)')}</option>
              {info.variables.map(v => <option key={v.name} value={v.name}>{v.label || v.name}</option>)}
            </select></label>
        </>}
        {(st.type === 'notify' || st.type === 'succeed' || st.type === 'fail') &&
          <input className={`${input} w-64`} placeholder={st.type === 'notify' ? t('通知的內容') : t('說明(可不填)')} value={st.text ?? ''} onChange={e => onChange(x => { x.text = e.target.value })}
            title={t('可以用 {變數或參數的代號} 帶入目前的值,例如「今天第 {restocks_today} 次」')} />}
        <span className="flex-1" />
        {SAYABLE.has(st.type) && <Button variant="ghost" onClick={() => setSay(v => !v)}
          title={t('給使用者看的白話:正在做什麼、失敗時說什麼(不填 = 平台自動用白話說明)')}>{st.say || st.say_fail ? '💬✓' : '💬'}</Button>}
        {moveBtns}
        {focus && <Button onClick={() => focus.setOpen(null)} title={t('收成一行')}>{t('完成 ✓')}</Button>}
      </div>
      {info.after_steps.includes(st.type) && <div className="mt-1.5 ml-7"><AfterEditor st={st} ctx={ctx} onChange={onChange} /></div>}
      {say && SAYABLE.has(st.type) && <div className="mt-1.5 ml-7 flex flex-wrap gap-2 text-xs items-center rounded bg-sky-50 border border-sky-200 px-2 py-1.5">
        <span className="text-sky-900">{t('給使用者看:')}</span>
        <input className={`${input} w-56`} placeholder={t('正在做什麼(例:等工作開始)')} value={st.say ?? ''} onChange={e => onChange(x => { x.say = e.target.value || undefined })} />
        <input className={`${input} w-80`} placeholder={t('失敗時說什麼(例:工作沒有開始,可能工作清單是空的)')} value={st.say_fail ?? ''}
          onChange={e => onChange(x => { x.say_fail = e.target.value || undefined })} />
        <span className="text-stone-500">{t('顯示在操作面板、待處理和通知;技術細節仍留在紀錄裡')}</span>
      </div>}
      {(st.type === 'wait_until' || st.type === 'repeat_until') && st.when && (
        <div className="mt-1.5 ml-7">
          {st.type === 'repeat_until' && <div className="text-xs text-sky-800 mb-1">{t('重複下面的步驟,直到:')}</div>}
          <ParamsCtx.Provider value={params}>
            <CondGroups when={st.when} states={states} ops={info.ops} onChange={fn => onChange(x => fn(x.when!))} />
          </ParamsCtx.Provider>
        </div>
      )}
      {st.type === 'call' && target && <div className="mt-1.5 ml-7"><ArgsEditor sub={target} args={st.args ?? {}} info={info} callerParams={params}
        onChange={a => onChange(x => { x.args = a })} /></div>}
      </>}
      {st.type === 'ask' && <div className="mt-2 ml-5 flex flex-col gap-2">
        {(st.options ?? []).map((o, k) => (
          <div key={k} className={`flex flex-col gap-1 ${k ? 'border-t border-dashed border-rose-200 pt-2' : ''}`}>
            <div className="flex flex-wrap items-center gap-2 text-xs font-semibold text-rose-700">
              {t('選')}
              <input className={`${input} w-32 font-normal`} maxLength={20} value={o.label} onChange={e => onChange(x => { x.options![k].label = e.target.value })} />
              {t('時做:')}<span className="font-normal text-rose-500">{t('(沒有步驟 = 直接往下一步)')}</span>
              <span className="flex-1" />
              <Button variant="ghost" disabled={k === 0} onClick={() => onChange(x => { const os = x.options!; [os[k - 1], os[k]] = [os[k], os[k - 1]]; if (x.default === k + 1) x.default = k; else if (x.default === k) x.default = k + 1 })}>↑</Button>
              <Button variant="ghost" disabled={(st.options ?? []).length <= 2} onClick={() => onChange(x => {
                x.options!.splice(k, 1)
                if (x.default === k + 1) x.default = 0; else if ((x.default ?? 0) > k + 1) x.default = (x.default ?? 0) - 1
              })}>{t('移除這個選項')}</Button>
            </div>
            <StepList steps={o.then ?? []} ctx={ctx} allowed={allowed} depth={depth + 1} prefix={`${no}.${k + 1}.`} path={[...here, 'options', k, 'then']}
              onChange={fn => onChange(x => { const b = x.options![k]; b.then = b.then ?? []; fn(b.then) })} compact={!open} />
          </div>
        ))}
        <button className="self-start text-xs text-rose-700 underline" disabled={(st.options ?? []).length >= 6}
          onClick={() => onChange(x => { x.options = [...(x.options ?? []), { label: t('選項{p1}', { p1: (x.options ?? []).length + 1 }), then: [] }] })}>{t('+ 選項(最多 6 個)')}</button>
      </div>}
      {st.type === 'for_each' && <div className="mt-2 ml-5 flex flex-col gap-1">
        <div className="text-xs font-semibold text-emerald-700">{t('每一個都做:(可以用參數「{label}」)', { label: loopParams(st, params)[0].label })}</div>
        <StepList steps={st.steps ?? []} ctx={{ ...ctx, params: [...params, ...loopParams(st, params)] }} allowed={allowed} depth={depth + 1} prefix={`${no}.`} path={[...here, 'steps']}
          onChange={fn => onChange(x => { x.steps = x.steps ?? []; fn(x.steps) })} compact={!open} />
      </div>}
      {(st.type === 'retry' || st.type === 'repeat_until') && <div className="mt-2 ml-5">
        <StepList steps={st.steps ?? []} ctx={ctx} allowed={allowed} depth={depth + 1} prefix={`${no}.`} path={[...here, 'steps']} onChange={fn => onChange(x => { x.steps = x.steps ?? []; fn(x.steps) })} compact={!open} />
      </div>}
    </div></ParamsCtx.Provider>
  )
}

function SubEditor({ saved, initial, info, states, onSaved, onDeleted }: {
  saved: SubScript | null; initial: SubScript; info: ScriptsInfo; states: StateDef[]
  onSaved: (s: SubScript) => void; onDeleted: () => void
}) {
  const [s, setS] = useState<SubScript>(() => clone(initial))
  const onChange = (fn: (x: SubScript) => void) => setS(d => { const n = clone(d); fn(n); return n })
  const isNew = !saved
  const dirty = JSON.stringify(strip(s)) !== JSON.stringify(strip(saved))
  const save = useMutation({ mutationFn: (note: string) => api.subSave(strip(s) as SubScript, note), onSuccess: onSaved })
  const del = useMutation({ mutationFn: () => api.subDelete(s.id), onSuccess: onDeleted })
  const usedBy = info.used_by[s.id] ?? []
  const ctx: Ctx = { info, states, params: s.params ?? [], selfId: s.id }
  const [tab, setTab] = usePersistentState<'steps' | 'info' | 'test' | 'json' | 'history'>('subs.tab', 'steps')
  const tx = (tab === 'history' || tab === 'test') && isNew ? 'steps' : tab
  return (
    <div className="flex flex-col gap-4 min-w-0">
      <EditorHeader badge={<span className="text-xs px-1.5 py-0.5 rounded bg-sky-700 text-white">{t('子腳本')}</span>}
        title={<>
          <input className={`${input} font-medium w-56`} value={s.name} onChange={e => onChange(x => { x.name = e.target.value })} />
          <span className="text-xs text-stone-500">{usedBy.length ? t('用在:{p1}', { p1: usedBy.join(t('、')) }) : t('還沒有人呼叫')}</span>
        </>}
        tabs={[['steps', t('步驟({length})', { length: s.steps.length })], ['info', t('設定')], ['json', 'JSON'], ...(isNew ? [] : [['test', t('測試')], ['history', t('版本')]] as ['test' | 'history', string][])]}
        tab={tx} setTab={setTab}>
        <SaveBar dirty={dirty} isNew={isNew} saving={save.isPending} error={save.error || del.error}
          savedText={save.data && <>{t('已儲存子腳本「{name}」v{version}。呼叫它的腳本會立刻用新版本。', { name: save.data.name, version: save.data.version })}</>}
          onSave={note => save.mutate(note)} onDiscard={() => setS(clone(saved!))}
          onDelete={() => { if (isNew) onDeleted(); else if (confirm(t('刪除子腳本「{name}」?(舊版本會保留在 .deleted 資料夾)', { name: s.name }))) del.mutate() }} />
      </EditorHeader>

      {tx === 'json' && <JsonPanel kind="sub" value={s} onApply={v => setS(v as SubScript)} />}
      {tx === 'steps' && <StepsRoot onRoot={fn => onChange(x => fn(x as unknown as Record<string, unknown>))}>
      <Card title={t('參數({length})', { length: (s.params ?? []).length })} extra={<span className="text-xs text-stone-500">{t('呼叫時要填的值,例如「地點」;步驟裡的點擊位置可以選「參數」')}</span>}>
        <div className="flex flex-col gap-2 text-sm">
          {(s.params ?? []).map((p, i) => (
            <div key={i} className="flex flex-wrap items-center gap-2">
              <input className={`${input} w-32 font-mono`} placeholder={t('代號(英文)')} value={p.name} onChange={e => onChange(x => { x.params![i].name = e.target.value })} />
              <input className={`${input} w-32`} placeholder={t('顯示名稱')} value={p.label ?? ''} onChange={e => onChange(x => { x.params![i].label = e.target.value })} />
              <select className={input} value={p.type} onChange={e => onChange(x => {
                x.params![i].type = e.target.value as SubParam['type']; delete x.params![i].default
                if (e.target.value === 'list') x.params![i].item = 'point'; else delete x.params![i].item
              })}>
                {Object.entries(info.param_types).map(([k, tx]) => <option key={k} value={k}>{tx}</option>)}
              </select>
              {p.type === 'list' && <label className="flex items-center gap-1 text-xs">{t('每一項是')}
                <select className={input} value={p.item ?? 'point'} onChange={e => onChange(x => { x.params![i].item = e.target.value as SubParam['item']; if (e.target.value !== 'point') delete x.params![i].from_list })}>
                  {Object.entries(ITEM_TYPES).map(([k, tx]) => <option key={k} value={k}>{tx}</option>)}
                </select></label>}
              {(p.type === 'point' || (p.type === 'list' && (p.item ?? 'point') === 'point')) && info.lists.length > 0 &&
                <label className="flex items-center gap-1 text-xs" title={t('從一份清單選:呼叫時只能選這份清單裡的名字(每台各自的清單:那台的)')}>{t('從清單選')}
                  <select className={input} value={p.from_list ?? ''} onChange={e => onChange(x => { if (e.target.value) x.params![i].from_list = e.target.value; else delete x.params![i].from_list })}>
                    <option value="">{t('(不限)')}</option>
                    {info.lists.map(l => <option key={l.id} value={l.id}>{l.title}{l.per_device ? t('(每台各自)') : ''}</option>)}
                  </select></label>}
              {p.type !== 'point' && p.type !== 'list' && <input className={`${input} w-28`} placeholder={t('預設值(可不填)')} value={p.default == null ? '' : String(p.default)}
                onChange={e => onChange(x => { const v = e.target.value; if (v === '') delete x.params![i].default; else x.params![i].default = p.type === 'number' ? Number(v) : v })} />}
              <Button variant="ghost" onClick={() => onChange(x => { x.params!.splice(i, 1) })}>✕</Button>
            </div>
          ))}
          <button className="text-xs text-stone-700 underline self-start" onClick={() => onChange(x => {
            x.params = x.params ?? []
            x.params.push({ name: newId('p', x.params.map(p => p.name)), label: '', type: 'point' })
          })}>{t('+ 新增參數')}</button>
        </div>
      </Card>

      <Card title={t('步驟')} extra={<span className="text-xs text-stone-500">{t('由上往下執行;點一步編輯,拖拉 ⠿ 搬移(也能拖進或拖出區塊)')}</span>}>
        <StepList steps={s.steps} ctx={ctx} path={['steps']} onChange={fn => onChange(x => fn(x.steps))} />
      </Card>

      <Card title={t('收尾步驟({length})', { length: (s.cleanup ?? []).length })} extra={<span className="text-xs text-stone-500">{t('被打斷或失敗時先做這些,例如按返回鍵關掉開到一半的視窗')}</span>}>
        <StepList steps={s.cleanup ?? []} ctx={ctx} allowed={info.cleanup_steps} path={['cleanup']} onChange={fn => onChange(x => { x.cleanup = x.cleanup ?? []; fn(x.cleanup) })} />
      </Card>

      </StepsRoot>}

      {tx === 'info' && <>
        <Card title={t('設定')}>
          <div className="grid md:grid-cols-2 gap-3 text-sm">
            <label className="flex flex-col gap-1"><span className="text-stone-600">{t('代號(英文)')}</span>
              <input className={`${input} font-mono`} value={s.id} disabled={!isNew} onChange={e => onChange(x => { x.id = e.target.value })} /></label>
            <label className="flex flex-col gap-1"><span className="text-stone-600">{t('說明')}</span>
              <input className={input} value={s.description ?? ''} onChange={e => onChange(x => { x.description = e.target.value })} /></label>
            <label className="flex flex-col gap-1" title={t('操作面板上顯示的白話,例如「輪流讓每個帳號做每日工作」')}><span className="text-stone-600">{t('給使用者看:在做什麼(白話)')}</span>
              <input className={input} value={s.say ?? ''} placeholder={t('不填 = 用名稱')} onChange={e => onChange(x => { x.say = e.target.value || undefined })} /></label>
            <label className="flex flex-col gap-1" title={t('步驟沒有自己的說明時,失敗了就說這句')}><span className="text-stone-600">{t('給使用者看:失敗時說什麼')}</span>
              <input className={input} value={s.say_fail ?? ''} placeholder={t('不填 = 平台自動用白話說明')} onChange={e => onChange(x => { x.say_fail = e.target.value || undefined })} /></label>
            <label className="flex items-center gap-2" title={t('整個子腳本(包含它呼叫的)最多跑多久;超過就算失敗,並執行收尾步驟')}>{t('整個子腳本最多執行')}
              <input type="number" className={`${input} w-20 num`} value={s.timeout ?? 300} onChange={e => onChange(x => { x.timeout = Number(e.target.value) })} />{t('秒')}</label>
          </div>
        </Card>
        {saved?.outline && <Card title={t('一句話說明(已儲存的版本)')}>
          <pre className="text-xs text-stone-700 whitespace-pre-wrap">{saved.outline.join('\n')}</pre>
        </Card>}
      </>}

      {tx === 'test' && saved && <RunOnce sub={saved} info={info} />}
      {tx === 'history' && !isNew && <History load={() => api.subHistory(s.id)} onLoad={v => api.subVersion(s.id, v).then(x => { setS(clone(x)); setTab('steps') })} />}
    </div>
  )
}

// ================================================================ JSON view / edit
/** The script as JSON (script spec v1, automation/spec_schema.py): read it, copy it, or edit and apply it to the
 *  draft. Applying checks it first (field names and types, then the same checks as saving); saving is still 儲存. */
function JsonPanel({ kind, value, onApply }: { kind: 'script' | 'sub'; value: Script | SubScript; onApply: (v: unknown) => void }) {
  const SPEC = useQuery({ queryKey: ['spec'], queryFn: api.spec, staleTime: 600000 }).data?.format ?? ''
  const current = JSON.stringify(strip(value as Script), null, 2)
  const [text, setText] = useState(current)
  const [errors, setErrors] = useState<{ path: string; message: string }[] | null>(null)
  const [note, setNote] = useState('')
  const changed = text !== current
  const parse = (): unknown => {
    try {
      return JSON.parse(text)
    } catch (e) {
      const m = String((e as Error).message)
      const pos = Number(m.match(/position (\d+)/)?.[1])
      const line = Number.isFinite(pos) ? text.slice(0, pos).split('\n').length : null
      setErrors([{ path: line ? t('第 {line} 行', { line }) : t('(整份)'), message: t('不是正確的 JSON:{m}', { m }) }])
      return undefined
    }
  }
  const check = useMutation({
    mutationFn: async (apply: boolean) => {
      const doc = parse()
      if (doc === undefined) return
      if (doc && typeof doc === 'object' && (doc as { id?: string }).id !== value.id) {
        setErrors([{ path: 'id', message: t('代號不能在這裡改(要改代號請另存一份新的)') }]); return
      }
      const r = await api.specCheck(kind, doc)
      setErrors(r.errors)
      if (r.ok && apply) { onApply(doc); setNote(t('已套用到編輯中的內容,按上面的「儲存」才會存成新版本')) }
      else setNote(r.ok ? t('沒有問題,可以套用') : '')
    },
  })
  return (
    <Card title="JSON" extra={<span className="flex items-center gap-2 text-xs text-stone-500">
      {t('腳本規範 v{SPEC} ·', { SPEC })} <a className="underline" href={`/api/spec/schema/${kind}`} target="_blank" rel="noreferrer">JSON Schema</a></span>}>
      <div className="flex flex-col gap-2 text-sm">
        <p className="text-xs text-stone-500">{t('可以直接改這裡的 JSON、或貼上別人給的內容,再按「套用」。套用前會先檢查欄位與內容(和儲存時一樣),通過才會換掉編輯中的內容; 要按上面的「儲存」才會存成新版本。')}</p>
        <textarea id={`json-${kind}`} spellCheck={false} value={text} onChange={e => { setText(e.target.value); setErrors(null); setNote('') }}
          className="font-mono text-xs leading-5 border border-stone-300 rounded-md p-3 h-[60vh] w-full bg-stone-50 whitespace-pre" />
        <div className="flex flex-wrap items-center gap-2">
          <Button onClick={() => check.mutate(false)} disabled={check.isPending}>{t('檢查')}</Button>
          <Button variant="primary" onClick={() => check.mutate(true)} disabled={check.isPending || !changed}>{t('套用')}</Button>
          <Button variant="ghost" onClick={() => { setText(current); setErrors(null); setNote('') }} disabled={!changed}>{t('還原成目前內容')}</Button>
          <Button variant="ghost" onClick={() => navigator.clipboard?.writeText(text).then(() => setNote(t('已複製'))).catch(() => setNote(t('瀏覽器不允許複製,請自行選取')))}>{t('複製')}</Button>
          {note && <span className="text-xs text-emerald-700">{note}</span>}
        </div>
        <ErrorText error={check.error} />
        {errors && errors.length > 0 && <div className="flex flex-col gap-1 border border-rose-200 bg-rose-50 rounded-md p-2 text-xs">
          {errors.map((e, i) => <div key={i}><code className="text-rose-800">{e.path}</code> {e.message}</div>)}
        </div>}
      </div>
    </Card>
  )
}

// ================================================================ replay over a recording
const SIT_COLORS = ['bg-sky-400', 'bg-amber-400', 'bg-violet-400', 'bg-emerald-400', 'bg-rose-400', 'bg-stone-400']
const EVENT_STYLE: Record<string, string> = {
  input: 'bg-rose-600 text-white', call: 'bg-amber-500 text-white', alert: 'bg-rose-100 text-rose-800', info: 'bg-sky-100 text-sky-800',
}

/** Run the scripts (this one as edited, even unsaved) over a recorded stretch: what would they have done? */
function ReplayCard({ draft, dirty }: { draft: Script; dirty: boolean }) {
  const sessions = useQuery({ queryKey: ['sessions'], queryFn: api.sessions })
  const list = (sessions.data ?? []).filter(x => x.samples > 0 && /^\d/.test(x.id))     // recordings (not the single frames saved while running)
  const [session, setSession] = useState('')
  const [device, setDevice] = useState('')
  const [start, setStart] = useState(0)
  const [minutes, setMinutes] = useState(30)
  const [subResult, setSubResult] = useState('success')
  const [useDraft, setUseDraft] = useState(true)
  const [rid, setRid] = useState<string | null>(null)
  const sess = list.find(x => x.id === session) ?? list[0]
  const dev = sess?.devices.find(d => d.name === device)?.name ?? sess?.devices.find(d => d.samples > 0)?.name ?? ''
  const go = useMutation({
    mutationFn: () => api.replayStart({ session: sess!.id, device: dev, start: start * 60, minutes, sub_result: subResult,
      script: useDraft ? strip(draft) as Script : null }),
    onSuccess: r => setRid(r.id),
  })
  const res = useQuery({ queryKey: ['replay', rid], queryFn: () => api.replayResult(rid!), enabled: !!rid,
    refetchInterval: q => (q.state.data?.status === 'done' || q.state.data?.status === 'failed' ? false : 1500) })
  const running = !!rid && res.data?.status !== 'done' && res.data?.status !== 'failed'
  return (
    <Card title={t('用錄過的畫面重播')} extra={<span className="text-xs text-stone-500">{t('不會點任何{device};子腳本不實際執行,結果用假設的', { device: words.device })}</span>}>
      <div className="flex flex-col gap-3 text-sm">
        <div className="flex flex-wrap items-center gap-2">
          <select className={input} value={sess?.id ?? ''} onChange={e => { setSession(e.target.value); setDevice('') }}>
            {list.map(x => <option key={x.id} value={x.id}>{sessionTime(x.id)}{x.minutes != null ? t('({minutes} 分)', { minutes: x.minutes }) : ''}</option>)}
          </select>
          <select className={input} value={dev} onChange={e => setDevice(e.target.value)}>
            {(sess?.devices ?? []).filter(d => d.samples > 0).map(d => <option key={d.name} value={d.name}>{t('{name}({samples} 張)', { name: d.name, samples: d.samples })}</option>)}
          </select>
          <label className="flex items-center gap-1">{t('從第')}<input type="number" min={0} className={`${input} w-16 num`} value={start} onChange={e => setStart(Number(e.target.value))} />{t('分鐘起')}</label>
          <label className="flex items-center gap-1">{t('重播')}<input type="number" min={1} max={240} className={`${input} w-16 num`} value={minutes} onChange={e => setMinutes(Number(e.target.value))} />{t('分鐘')}</label>
          <label className="flex items-center gap-1">{t('子腳本假設')}
            <select className={input} value={subResult} onChange={e => setSubResult(e.target.value)}><option value="success">{t('都成功')}</option><option value="fail">{t('都失敗')}</option></select></label>
          <label className="flex items-center gap-1.5 text-xs"><input type="checkbox" checked={useDraft} onChange={e => setUseDraft(e.target.checked)} />
            {t('用目前編輯中的版本')}{dirty ? t('(未儲存)') : ''}</label>
          <Button variant="primary" disabled={!sess || !dev || go.isPending || running} onClick={() => go.mutate()}>{running ? t('重播中…') : t('開始重播')}</Button>
        </div>
        <ErrorText error={go.error || res.error} />
        {running && <div className="text-xs text-stone-500">{(res.data?.log ?? []).slice(-1)[0] ?? t('準備中(載入模型約 10 秒)…')}</div>}
        {res.data?.status === 'failed' && <ErrorText error={(res.data.log ?? []).join(' ') || t('重播失敗')} />}
        {res.data?.result && <ReplayView r={res.data.result} />}
      </div>
    </Card>
  )
}

export function ReplayView({ r }: { r: ReplayResult }) {
  const [all, setAll] = useState(false)
  const qc = useQueryClient()
  const navigate = useNavigate()
  const keep = useMutation({
    mutationFn: (name: string) => api.testFromReplay(r.id, name),
    onSuccess: d => { qc.setQueryData(['tests'], d); navigate('/tests') },
  })
  const [open, setOpen] = useState<number | null>(null)
  const s = r.summary
  const span = Math.max(1, s.to - s.from)
  // situation bands: one row per script that has more than one situation
  const scripts = [...new Set(r.ticks.flatMap(tx => Object.keys(tx.situations)))]
    .filter(sid => new Set(r.ticks.map(tx => tx.situations[sid])).size > 1)
  const rows = r.ticks.map((tx, i) => ({ tx, i })).filter(({ tx, i }) => all || tx.events.length > 0 || i === 0
    || tx.decisions.some((d, k) => d.text !== r.ticks[i - 1]?.decisions[k]?.text))
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap gap-2 text-xs">
        <Pill>{t('{frames} 張畫面 · {p2} 分鐘', { frames: s.frames, p2: Math.round(span / 60) })}</Pill>
        <Pill tone={s.inputs ? 'red' : 'stone'}>{t('會點擊 {inputs} 次', { inputs: s.inputs })}</Pill>
        <Pill tone={s.calls ? 'amber' : 'stone'}>{t('呼叫子腳本 {calls} 次', { calls: s.calls })}</Pill>
        <Pill tone={s.switches ? 'blue' : 'stone'}>{t('切換情境 {switches} 次', { switches: s.switches })}</Pill>
        <Pill tone={s.alerts ? 'red' : 'stone'}>{t('警告 {alerts} 次', { alerts: s.alerts })}</Pill>
        {!r.id.startsWith('test_') && <span className="ml-auto flex items-center gap-2">
          <Button disabled={r.draft || keep.isPending} title={r.draft ? t('這次用的是還沒儲存的腳本:先儲存、再重播一次,才能存成測試') : t('把這次的行為(結束時的情境、呼叫了哪些子腳本、有沒有停止或警示)存成預期結果')}
            onClick={() => { const n = prompt(t('測試名稱'), `${sessionTime(r.session)} ${r.device}`); if (n) keep.mutate(n) }}>{t('存成測試')}</Button>
        </span>}
      </div>
      <ErrorText error={keep.error} />
      {scripts.map(sid => {
        const names = [...new Set(r.ticks.map(tx => tx.situations[sid]))]
        return (
          <div key={sid} className="flex flex-col gap-1">
            <div className="relative h-4 rounded bg-stone-100 overflow-hidden">
              {r.ticks.map((tx, i) => {
                const next = r.ticks[i + 1]?.t ?? s.to
                return <span key={i} className={`absolute top-0 h-full ${SIT_COLORS[names.indexOf(tx.situations[sid]) % SIT_COLORS.length]}`}
                  style={{ left: `${((tx.t - s.from) / span) * 100}%`, width: `${Math.max(0.2, ((next - tx.t) / span) * 100)}%` }} title={`${clock(tx.t)} ${tx.situations[sid]}`} />
              })}
            </div>
            <div className="flex gap-3 text-[11px] text-stone-500">{names.map((n, k) => <span key={n} className="flex items-center gap-1">
              <span className={`w-2.5 h-2.5 rounded-sm ${SIT_COLORS[k % SIT_COLORS.length]}`} />{n}</span>)}</div>
          </div>
        )
      })}
      <label className="flex items-center gap-1.5 text-xs text-stone-600"><input type="checkbox" checked={all} onChange={e => setAll(e.target.checked)} />
        {t('顯示每一張(預設只顯示有動作、決定改變的時刻)')}</label>
      <div className="flex flex-col max-h-[560px] overflow-auto border border-stone-200 rounded-md">
        {rows.map(({ tx, i }) => (
          <div key={i} className="border-b border-stone-100 px-3 py-1.5 text-xs flex flex-col gap-1">
            <div className="flex flex-wrap items-center gap-2">
              <button className="num text-stone-500 underline decoration-dotted" onClick={() => setOpen(open === i ? null : i)} title={t('看這張畫面')}>{clock(tx.t)}</button>
              {Object.entries(tx.situations).filter(([sid]) => scripts.includes(sid)).map(([sid, n]) => <span key={sid} className="px-1.5 rounded bg-stone-900 text-white">{n}</span>)}
              {tx.held && <span className="px-1.5 rounded bg-violet-100 text-violet-800">🛡 {tx.held}</span>}
              {tx.events.map((e, k) => <span key={k} className={`px-1.5 rounded ${EVENT_STYLE[e.kind]}`}>{e.text}</span>)}
            </div>
            <div className="flex flex-wrap gap-x-3 text-stone-600">
              {tx.decisions.map((d, k) => <span key={k}>{d.guard ? '🛡' : ''}{d.script_name}:{d.text}{d.exec ? <span className="text-stone-400">({d.exec})</span> : ''}</span>)}
            </div>
            {open === i && <img src={imageUrl(tx.frame, 640)} alt="" className="w-full max-w-xl rounded" />}
          </div>
        ))}
      </div>
    </div>
  )
}

/** run the saved sub-script once on one emulator (real taps; needs the master switch) */
function RunOnce({ sub, info }: { sub: SubScript; info: ScriptsInfo }) {
  const env = useContext(CondEnv)
  const [dev, setDev] = useState(env.devices[0] ?? '')
  const [args, setArgs] = useState<Record<string, ArgValue>>({})
  const run = useMutation({ mutationFn: () => api.runSub({ device: dev, sub: sub.id, args }) })
  return (
    <Card title={t('在{device}上執行一次', { device: words.device })} extra={<span className="text-xs text-rose-700">{t('會真的點擊;這台停下來或暫停中的話要先按「繼續」')}</span>}>
      <div className="flex flex-col gap-2 text-sm">
        <div className="flex flex-wrap items-center gap-2">
          <select className={input} value={dev} onChange={e => setDev(e.target.value)}>{env.devices.map(d => <option key={d} value={d}>{dn(d)}</option>)}</select>
          <Button variant="primary" disabled={!dev || run.isPending}
            onClick={() => { if (confirm(t('在 {p1} 上執行子腳本「{name}」一次?會真的點擊。', { p1: dn(dev), name: sub.name }))) run.mutate() }}>{t('執行一次')}</Button>
          {run.isSuccess && <span className="text-xs text-emerald-700">{t('已送出,到')} <Link className="underline" to="/script">{t('執行')}</Link> {t('看這台的進度和時間軸')}</span>}
        </div>
        <ArgsEditor sub={sub} args={args} info={info} callerParams={[]} onChange={setArgs} />
        <ErrorText error={run.error} />
      </div>
    </Card>
  )
}

// ================================================================ button library
const BTN_NEW: LibButton = { id: '', label: '', x: 640, y: 360, find: false }

/** named tap positions: picked on a frame (a device's frame right now, or a recorded one); "find" buttons are looked
 *  for by their picture every time, so they still work when they move a little */
export function ButtonsEditor({ info, devices, onSaved }: { info: ScriptsInfo; devices: string[]; onSaved: () => void }) {
  const [edit, setEdit] = useState<LibButton | null>(null)
  const del = useMutation({ mutationFn: (id: string) => api.buttonDelete(id), onSuccess: onSaved })
  return (
    <div className="flex flex-col gap-4 min-w-0">
      <Card title={t('按鈕庫({length})', { length: info.buttons.filter(b => !perDeviceItem(info, b)).length })} extra={<Button onClick={() => setEdit({ ...BTN_NEW, id: newId('btn_', info.buttons.map(b => b.id)) })}>{t('+ 新增按鈕')}</Button>}>
        <div className="flex flex-col gap-2 text-sm">
          <p className="text-xs text-stone-500">{t('在畫面上點一下、取個名字,之後所有腳本的點擊位置都可以選「按鈕庫」裡的名字。勾「找圖」的按鈕每次會先在畫面上找它的圖片再點,按鈕位置稍微變動也點得到;找不到就不點。')}</p>
          <ErrorText error={del.error} />
          {info.buttons.filter(b => !perDeviceItem(info, b)).length === 0 && <Empty>{t('還沒有按鈕')}</Empty>}
          {info.buttons.filter(b => !perDeviceItem(info, b)).map(b => (
            <div key={b.id} className="flex items-center gap-3 border-b border-stone-100 pb-2">
              {b.find ? <img src={buttonImageUrl(b.id, b.updated)} alt="" className="h-10 rounded border border-stone-200" /> : <span className="w-10 text-center text-stone-300">·</span>}
              <span className="font-medium">{b.label}</span>
              <span className="text-xs text-stone-500 num">({b.x}, {b.y}){b.find ? t(' · 找圖,相似度 ≥ {p1}%', { p1: Math.round((b.min_score ?? 0.8) * 100) }) : ''}</span>
              <span className="text-xs text-stone-400 font-mono">{b.id}</span>
              <span className="flex-1" />
              <Button variant="ghost" onClick={() => setEdit(clone(b))}>{t('修改')}</Button>
              <Button variant="ghost" onClick={() => { if (confirm(t('刪除按鈕「{label}」?', { label: b.label }))) del.mutate(b.id) }}>{t('刪除')}</Button>
            </div>
          ))}
        </div>
      </Card>
      {edit && <ButtonForm key={edit.id} b={edit} isNew={!info.buttons.some(x => x.id === edit.id)} devices={devices}
        onDone={() => { setEdit(null); onSaved() }} onCancel={() => setEdit(null)} />}
    </div>
  )
}

function ButtonForm({ b: initial, isNew, devices, onDone, onCancel }: {
  b: LibButton; isNew: boolean; devices: string[]; onDone: () => void; onCancel: () => void
}) {
  const [b, setB] = useState<LibButton>(initial)
  const [src, setSrc] = useState<{ snap?: string; frame?: string; v: number } | null>(null)
  const [dev, setDev] = useState(devices[0] ?? '')
  const [seed, setSeed] = useState(1)
  const ref = useRef<HTMLDivElement>(null)
  const snap = useMutation({ mutationFn: () => api.buttonSnap(dev), onSuccess: r => setSrc({ snap: r.device, v: r.updated }) })
  const rec = useMutation({ mutationFn: () => api.randomFrames(1, seed), onSuccess: f => { setSeed(x => x + 1); if (f[0]) setSrc({ frame: f[0], v: 0 }) } })
  const save = useMutation({ mutationFn: () => api.buttonSave(b, src ? { snap: src.snap, frame: src.frame } : {}), onSuccess: onDone })
  const img = src?.snap ? buttonSnapUrl(src.snap, src.v) : src?.frame ? imageUrl(src.frame) : null
  const box = b.box ?? [b.x - 40, b.y - 25, 80, 50]
  const setBox = (i: number, v: number) => setB(x => { const nb = [...(x.box ?? box)]; nb[i] = v; return { ...x, box: nb } })
  const pct = (v: number, of: number) => `${(v / of) * 100}%`
  return (
    <Card title={isNew ? t('新增按鈕') : t('修改按鈕「{label}」', { label: initial.label })} extra={<span className="flex gap-2">
      <Button variant="ghost" onClick={onCancel}>{t('取消')}</Button>
      <Button variant="primary" disabled={save.isPending || (b.find && isNew && !src)} onClick={() => save.mutate()}>{save.isPending ? t('儲存中…') : t('儲存')}</Button>
    </span>}>
      <div className="flex flex-col gap-3 text-sm">
        <ErrorText error={snap.error || rec.error || save.error} />
        <div className="flex flex-wrap items-center gap-2">
          <input className={`${input} w-40`} placeholder={t('名稱,例如「設定圖示」')} value={b.label} onChange={e => setB({ ...b, label: e.target.value })} />
          <input className={`${input} w-32 font-mono`} value={b.id} disabled={!isNew} onChange={e => setB({ ...b, id: e.target.value })} />
          <label className="flex items-center gap-1 text-xs num">x <input type="number" className={`${input} w-16`} value={b.x} onChange={e => setB({ ...b, x: Math.round(Number(e.target.value)) })} />
            y <input type="number" className={`${input} w-16`} value={b.y} onChange={e => setB({ ...b, y: Math.round(Number(e.target.value)) })} /></label>
          <label className="flex items-center gap-1.5"><input type="checkbox" checked={!!b.find} onChange={e => setB({ ...b, find: e.target.checked, box: e.target.checked ? box : undefined })} />
            {t('找圖(按鈕會移動時用)')}</label>
        </div>
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <span className="text-stone-500">{t('畫面來源:')}</span>
          <select className={input} value={dev} onChange={e => setDev(e.target.value)}>{devices.map(d => <option key={d} value={d}>{dn(d)}</option>)}</select>
          <Button onClick={() => snap.mutate()} disabled={!dev || snap.isPending}>{snap.isPending ? t('擷取中…') : t('擷取這台現在的畫面')}</Button>
          <Button variant="ghost" onClick={() => rec.mutate()} disabled={rec.isPending}>{t('用錄過的畫面(換一張)')}</Button>
          <span className="text-stone-400">{t('先把{device}切到有這個按鈕的畫面,再擷取', { device: words.device })}</span>
        </div>
        {img && (
          <div ref={ref} className="relative w-full max-w-4xl aspect-video bg-stone-900 rounded-md overflow-hidden cursor-crosshair"
            onClick={e => {
              const r = ref.current!.getBoundingClientRect()
              const x = Math.round(((e.clientX - r.left) / r.width) * screen.w), y = Math.round(((e.clientY - r.top) / r.height) * screen.h)
              setB(v => ({ ...v, x, y, box: v.find ? [x - (box[2] >> 1), y - (box[3] >> 1), box[2], box[3]] : v.box }))
            }}>
            <img src={img} alt="" className="absolute inset-0 w-full h-full" />
            {b.find && <span className="absolute border-2 border-sky-400 pointer-events-none" style={{ left: pct(box[0], screen.w), top: pct(box[1], screen.h), width: pct(box[2], screen.w), height: pct(box[3], screen.h) }} />}
            <span className="absolute w-5 h-5 -ml-2.5 -mt-2.5 rounded-full border-4 border-amber-400 bg-amber-400/40 pointer-events-none" style={{ left: pct(b.x, screen.w), top: pct(b.y, screen.h) }} />
          </div>
        )}
        {b.find && (
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <span className="text-stone-500">{t('按鈕圖片範圍(藍框,點畫面時會以點的位置為中心):')}</span>
            {([t('左'), t('上'), t('寬'), t('高')] as const).map((n, i) => <label key={n} className="flex items-center gap-1">{n}<input type="number" className={`${input} w-16 num`} value={box[i]} onChange={e => setBox(i, Number(e.target.value))} /></label>)}
            <label className="flex items-center gap-1">{t('往外找')}<input type="number" className={`${input} w-16 num`} value={b.search ?? 60} onChange={e => setB({ ...b, search: Number(e.target.value) })} />{t('像素')}</label>
            <label className="flex items-center gap-1">{t('相似度 ≥')}<input type="number" className={`${input} w-14 num`} value={Math.round((b.min_score ?? 0.8) * 100)} onChange={e => setB({ ...b, min_score: Number(e.target.value) / 100 })} />%</label>
            {!isNew && !src && <span className="text-stone-400">{t('(不重新擷取就沿用原本的圖片)')}</span>}
          </div>
        )}
      </div>
    </Card>
  )
}
