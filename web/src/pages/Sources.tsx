import { t } from '../i18n'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type ReactNode } from 'react'
import { api, type SourceHand, type SourceItem, type SourceKindInfo, type SourceNative, type SourceParam, type SourceView } from '../api'
import { Button, Card, Drawer, Empty, ErrorText, Modal, MoreButton, Page, Pill } from '../components/ui'
import { words } from '../lib/project'
import { tagList } from '../lib/sources'

const input = 'border border-stone-300 rounded-md px-2 py-1 text-sm bg-white'
const sizeText = (s: number[] | null) => (s ? `${s[0]}×${s[1]}` : '')

/** 來源: which devices this computer uses (several kinds at once), what each is called, where each is used.
 *  The page: the sources in use, one line each. Adding (scan / by address) and the kinds' settings open on demand. */
export default function Sources() {
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['sources'], queryFn: api.sources, refetchInterval: 10_000 })
  const refresh = () => { qc.invalidateQueries({ queryKey: ['sources'] }); qc.invalidateQueries({ queryKey: ['sourceNames'] }) }
  const [adding, setAdding] = useState(false)
  const [kinds, setKinds] = useState(false)
  const d = q.data
  const fresh = (d?.new ?? []).filter(n => !n.ignored)
  return (
    <Page title={t('來源')} desc={t('這台電腦要看哪些畫面、各叫什麼名字。只有勾選「使用」的才會被錄製、監看和執行腳本;名稱只是給人看的,隨時可以改。')}
      actions={<>
        <Button variant="primary" onClick={() => setAdding(true)}>{t('+ 加入來源')}</Button>
        <MoreButton onClick={() => setKinds(true)}>{t('⚙ 種類與進階設定')}</MoreButton>
      </>}>
      {!d ? <Card><Empty>{q.isLoading ? t('讀取中…') : t('讀取失敗')}</Empty></Card> : <>
        {fresh.length > 0 && <div className="rounded-md border border-sky-300 bg-sky-50 px-3 py-2 text-sm text-sky-900 flex flex-wrap items-center gap-3">
          <span className="flex-1">{t('發現 {length} 個還沒使用的來源:{p2}(新的來源預設不使用)', { length: fresh.length, p2: fresh.map(n => n.match).join(t('、')) })}</span>
          <Button onClick={() => setAdding(true)}>{t('看看')}</Button></div>}
        <InUse d={d} onChange={refresh} />
        <Modal open={adding} wide title={t('加入來源')} onClose={() => setAdding(false)}><Scan d={d} onChange={refresh} /></Modal>
        <Drawer open={kinds} title={t('來源種類與進階設定')} onClose={() => setKinds(false)}><Kinds d={d} onChange={refresh} /></Drawer>
      </>}
    </Page>
  )
}

function InUse({ d, onChange }: { d: SourceView; onChange: () => void }) {
  if (!d.items.length) return <Card title={t('使用中的來源')}><Empty>{t('還沒有。按右上角「+ 加入來源」。')}</Empty></Card>
  return (
    <Card title={t('使用中的來源({length})', { length: d.items.filter(i => i.enabled).length })} extra={<span className="text-xs text-stone-500">{t('取消「使用」= 不錄製、不監看、不執行;設定都保留')}</span>}>
      <div className="flex flex-col divide-y divide-stone-100">
        {d.items.map(it => <SourceRow key={it.id} it={it} d={d} onChange={onChange} />)}
      </div>
    </Card>
  )
}

/** one source: what matters at a glance; everything else in its window */
function SourceRow({ it, d, onChange }: { it: SourceItem; d: SourceView; onChange: () => void }) {
  const [open, setOpen] = useState(false)
  const upd = useMutation({ mutationFn: (enabled: boolean) => api.sourceUpdate({ id: it.id, enabled }), onSuccess: onChange })
  const state = !it.enabled ? <Pill>{t('不使用')}</Pill>
    : !it.present ? <Pill tone="amber">{t('現在找不到')}</Pill>
    : it.health && it.health.state !== 'ok' ? <Pill tone={it.health.state === 'slow' ? 'amber' : 'red'}>{it.health.text}</Pill>
    : it.watching ? <Pill tone="green">{t('連線中')}</Pill> : <Pill tone="green">{t('找得到')}</Pill>
  const warn = it.size_warn || (it.enabled && !it.present ? t('找不到:沒開、斷線,或名稱改了(按「設定」可以接回)') : '')
  return (
    <div className={`py-2 flex flex-col gap-1 text-sm ${it.enabled ? '' : 'opacity-60'}`}>
      <div className="flex flex-wrap items-center gap-2">
        <input type="checkbox" checked={it.enabled} disabled={upd.isPending} onChange={e => upd.mutate(e.target.checked)} title={t('使用')} />
        <button className="font-medium hover:underline text-left" onClick={() => setOpen(true)}>{it.label}</button>
        {it.name && <code className="text-[11px] text-stone-400" title={t('代號:腳本、排程、設定都用它,不會變')}>{it.id}</code>}
        <span className="text-xs text-stone-500">{it.kind_label.split('(')[0]}</span>
        {state}
        {it.health?.state === 'ok' && it.health.fps > 0 && <span className="text-[11px] text-stone-400" title={t('執行器實際拿到畫面的頻率')}>{t('{fps} 張/秒', { fps: it.health.fps })}</span>}
        {(it.tags ?? []).map(tx => <span key={tx} className="text-[11px] bg-sky-50 border border-sky-200 text-sky-800 rounded px-1.5">#{tx}</span>)}
        {(it.hand?.to ?? 'self') !== 'self' && <span className="text-[11px] text-sky-700">{t('動作:{hand_text}', { hand_text: it.hand_text })}</span>}
        <span className="flex-1" />
        <span className="text-xs text-stone-400">{t('用到 {length} 處', { length: it.refs.length })}</span>
        <MoreButton onClick={() => setOpen(true)}>{t('設定')}</MoreButton>
      </div>
      {warn && <div className="text-xs text-amber-800 pl-6">⚠ {warn}</div>}
      <ErrorText error={upd.error} />
      <SourceModal open={open} it={it} d={d} onClose={() => setOpen(false)} onChange={onChange} />
    </div>
  )
}

/** a source's settings: name, tags, where its actions go, how it is found, re-attach, where it is used, remove */
function SourceModal({ open, it, d, onClose, onChange }: { open: boolean; it: SourceItem; d: SourceView; onClose: () => void; onChange: () => void }) {
  const [name, setName] = useState<string | null>(null)
  const [rebind, setRebind] = useState('')
  const upd = useMutation({ mutationFn: (b: { name?: string; match?: string; kind?: string; hand?: SourceHand; params?: Record<string, string>; tags?: string[] }) => api.sourceUpdate({ id: it.id, ...b }),
    onSuccess: r => {
      setName(null); setRebind('')
      if (r.now_live?.length) alert(t('注意:因為這個改變,這些主腳本現在會在「{label}」正式執行(會點擊):{p2}', { label: it.label, p2: r.now_live.join(t('、')) }))
      onChange()
    } })
  const rm = useMutation({
    mutationFn: async () => {
      const r = await api.sourceRemove(it.id)
      if (!r.removed && confirm(t('「{label}」還被這些地方用到:\n{p2}\n\n移除後它們會找不到這台(代號不會再給別的來源用)。確定移除?', { label: it.label, p2: r.refs.map(x => '・' + x.text).join('\n') })))
        return api.sourceRemove(it.id, true)
      return r
    },
    onSuccess: r => { if (r.removed) onClose(); onChange() },
  })
  const candidates = d.new.filter(n => n.kind === it.kind)
  const own = Object.keys(it.per_source ?? {}).length > 0
  return (
    <Modal open={open} title={<span>{it.label} <code className="text-xs text-stone-400 font-normal">{it.id}</code></span>} onClose={onClose}>
      <Section title={t('名稱')}>
        <div className="flex gap-2">
          <input className={`${input} flex-1`} placeholder={it.id} value={name ?? it.name} maxLength={40} onChange={e => setName(e.target.value)} />
          <Button variant="primary" disabled={name === null || name === it.name || upd.isPending} onClick={() => upd.mutate({ name: name ?? '' })}>{t('儲存')}</Button>
        </div>
        <div className="text-xs text-stone-500">{it.kind_label} · {it.match}{it.detail ? ` · ${it.detail}` : ''}{it.size ? ` · ${sizeText(it.size)}` : ''}</div>
        {it.size_warn && <div className="text-xs text-amber-800">⚠ {it.size_warn}</div>}
      </Section>
      <Section title={t('標籤')} hint={t('部署、排程、通知、操作面板、聊天都可以用「#標籤」一次選一群')}>
        <TagRow tags={it.tags ?? []} busy={upd.isPending} onSet={tags => upd.mutate({ tags })} />
      </Section>
      <Section title={t('動作送到')} hint={t('畫面從這個來源來;腳本的點擊、滑動、返回、輸入文字送到這裡')}>
        <HandRow it={it} d={d} busy={upd.isPending} onSet={hand => upd.mutate({ hand })} />
        {!it.caps.includes('tap') && <div className="text-xs text-stone-500">{t('它現在不能點擊:部署在它上面的腳本只會判斷,不會動作')}</div>}
        {it.used_as_hand_by.length > 0 && <div className="text-xs text-stone-500">{t('這些來源的動作交給它:{p1}', { p1: it.used_as_hand_by.map(x => d.items.find(y => y.id === x)?.label ?? x).join(t('、')) })}</div>}
      </Section>
      {own && <Section title={t('怎麼找到它、只取哪一塊')}>
        {it.enabled && !it.present && <div className="text-xs text-amber-800">{t('照這些設定找不到:視窗關了、被改了標題,或改一下設定(例如標題改成「包含」其中一段)')}</div>}
        <OwnSettings it={it} busy={upd.isPending} onSave={params => upd.mutate({ params })} />
      </Section>}
      {it.enabled && !it.present && candidates.length > 0 && <Section title={t('接回(它只是改了名稱)')} hint={t('代號和所有設定都保留')}>
        <div className="flex gap-2">
          <select className={`${input} flex-1`} value={rebind} onChange={e => setRebind(e.target.value)}>
            <option value="">{t('選擇現在的名稱…')}</option>
            {candidates.map(c => <option key={c.match} value={c.match}>{c.match}{c.detail ? `(${c.detail})` : ''}</option>)}
          </select>
          <Button disabled={!rebind || upd.isPending} onClick={() => upd.mutate({ match: rebind, kind: it.kind })}>{t('接回')}</Button>
        </div>
      </Section>}
      <Section title={t('用到的地方({length})', { length: it.refs.length })}>
        <div className="text-xs text-stone-600">{it.refs.length === 0 ? t('還沒有地方用到它。到「執行 › 部署」決定它跑哪個腳本,或在排程、操作面板勾選它。')
          : it.refs.map((r, i) => <div key={i}>・{r.text}</div>)}</div>
      </Section>
      <ErrorText error={upd.error || rm.error} />
      <div className="border-t border-stone-200 pt-3 flex justify-end"><Button variant="ghost" disabled={rm.isPending} onClick={() => rm.mutate()}>{t('移除這個來源')}</Button></div>
    </Modal>
  )
}

function Section({ title, hint, children }: { title: ReactNode; hint?: string; children: ReactNode }) {
  return <div className="flex flex-col gap-1.5"><div className="text-xs font-semibold text-stone-600" title={hint}>{title}{hint && <span className="font-normal text-stone-400"> · {hint}</span>}</div>{children}</div>
}

/** 標籤: groups a source belongs to - deploy, schedule, filter notifications, show on the panel by tag */
function TagRow({ tags, busy, onSet }: { tags: string[]; busy: boolean; onSet: (tx: string[]) => void }) {
  const [text, setText] = useState('')
  const add = (tx: string) => { const v = tx.trim().replace(/^#/, ''); if (v && !tags.includes(v)) onSet([...tags, v]); setText('') }
  const others = tagList().filter(tx => !tags.includes(tx))
  return (
    <div className="flex flex-wrap items-center gap-1.5 text-xs">
      <span className="text-stone-600" title={t('部署、排程、通知、操作面板、聊天都可以用「#標籤」一次選一群;之後貼上同樣標籤的來源自動套用')}>{t('標籤')}</span>
      {tags.map(tx => <span key={tx} className="flex items-center gap-1 bg-sky-50 border border-sky-200 text-sky-800 rounded px-1.5">#{tx}
        <button className="text-sky-400 hover:text-rose-600" disabled={busy} onClick={() => onSet(tags.filter(x => x !== tx))}>✕</button></span>)}
      <input className={`${input} w-28 text-xs`} placeholder={t('+ 標籤')} value={text} list="tag-list" maxLength={20}
        onChange={e => setText(e.target.value)} onKeyDown={e => { if (e.key === 'Enter') add(text) }} onBlur={() => text && add(text)} />
      <datalist id="tag-list">{others.map(tx => <option key={tx} value={tx} />)}</datalist>
    </div>
  )
}

/** a window / screen source's own settings (how it is found, the part to keep) */
function OwnSettings({ it, busy, onSave }: { it: SourceItem; busy: boolean; onSave: (p: Record<string, string>) => void }) {
  const [p, setP] = useState<Record<string, string> | null>(null)
  const cur = p ?? it.params ?? {}
  return (
    <div className="text-xs">
      {<div className="flex flex-col gap-1.5">
        {Object.entries(it.per_source).map(([k, sp]) => <ParamInput key={k} k={k} sp={sp} value={cur[k] ?? (sp.type === 'select' ? Object.keys(sp.options ?? {})[0] : '')}
          suggested={undefined} onChange={v => setP({ ...cur, [k]: String(v) })} />)}
        <div><Button variant="primary" disabled={!p || busy} onClick={() => { onSave(cur); setP(null) }}>{t('儲存')}</Button></div>
      </div>}
    </div>
  )
}

/** 動作送到: the eye and the hand are separate - the same device (usual), another source, an output, or nothing. */
function HandRow({ it, d, busy, onSet }: { it: SourceItem; d: SourceView; busy: boolean; onSet: (h: SourceHand) => void }) {
  const h = it.hand ?? { to: 'self' }
  const others = d.items.filter(x => x.id !== it.id)
  const pick = (to: SourceHand['to']) => {
    if (to === 'source') { if (others[0]) onSet({ to, id: others[0].id }) }
    else if (to === 'output') { if (d.outputs[0]) onSet({ to, id: d.outputs[0].id }) }
    else onSet({ to })
  }
  return (
    <div className="flex flex-wrap items-center gap-2 text-xs">
      <span className="text-stone-600" title={t('畫面從這個來源來;腳本的點擊、滑動、返回、輸入文字送到這裡')}>{t('動作送到')}</span>
      <select className={input} value={h.to} disabled={busy} onChange={e => pick(e.target.value as SourceHand['to'])}>
        <option value="self">{t('同一台(建議)')}</option>
        <option value="source" disabled={!others.length}>{t('交給另一個來源')}</option>
        <option value="output" disabled={!d.outputs.length}>{t('送到輸出')}{d.outputs.length ? '' : t('(先在素材庫新增輸出)')}</option>
        <option value="none">{t('不動作(只看)')}</option>
      </select>
      {h.to === 'source' && <select className={input} value={h.id} disabled={busy} onChange={e => onSet({ to: 'source', id: e.target.value })}>
        {others.map(x => <option key={x.id} value={x.id}>{x.label}</option>)}</select>}
      {h.to === 'output' && <select className={input} value={h.id} disabled={busy} onChange={e => onSet({ to: 'output', id: e.target.value })}>
        {d.outputs.map(o => <option key={o.id} value={o.id}>{o.name}</option>)}</select>}
      {h.to === 'output' && <span className="text-stone-500">{t('每個動作會送一則訊息:command = tap / swipe…,value = 位置')}</span>}
    </div>
  )
}

function Scan({ d, onChange }: { d: SourceView; onChange: () => void }) {
  const on = Object.entries(d.kinds).filter(([, k]) => k.in_use > 0).map(([k]) => k)
  const [kinds, setKinds] = useState<string[] | null>(null)
  const [text, setText] = useState('')
  const pick = kinds ?? on
  const scan = useMutation({ mutationFn: (only?: string[]) => api.sourceScan(only ?? pick, text) })
  const [showUsed, setShowUsed] = useState(true)
  const [showMin, setShowMin] = useState(false)
  const rows = scan.data?.found ?? []
  const fresh = rows.filter(r => !r.bound)
  const used = rows.filter(r => r.bound)
  const byCat: Record<string, SourceNative[]> = {}
  for (const r of showUsed ? [...fresh, ...used] : fresh) (byCat[r.category_label || r.kind] ??= []).push(r)
  const rescanAs = (kind: string) => { setKinds([kind]); scan.mutate([kind]) }
  return (
    <>
      <div className="flex flex-col gap-3 text-sm">
        <div className="text-xs text-stone-500">{t('找出這台電腦上的{device};可以只找某一種,或打字篩選。找不到的(例如攝影機)在最下面用位址加入。', { device: words.device })}</div>
        <div className="flex flex-wrap items-center gap-3">
          <span className="text-stone-600">{t('找哪幾種:')}</span>
          {Object.entries(groups(d.kinds)).map(([cat, ks]) => (
            <span key={cat} className="flex flex-wrap items-center gap-2 border border-stone-200 rounded px-2 py-0.5">
              <span className="text-xs text-stone-500">{ks[0][1].category_label}</span>
              {ks.map(([k, x]) => <label key={k} className="flex items-center gap-1"><input type="checkbox" checked={pick.includes(k)}
                onChange={e => setKinds(e.target.checked ? [...pick, k] : pick.filter(y => y !== k))} />{x.label}</label>)}
            </span>
          ))}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <input className={`${input} w-72`} placeholder={t('篩選,例如:MuMu、雷電、5558、BlueStacks')} value={text} onChange={e => setText(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter' && pick.length) scan.mutate(undefined) }} />
          <Button variant="primary" disabled={!pick.length || scan.isPending} onClick={() => scan.mutate(undefined)}>{scan.isPending ? t('掃描中…') : t('掃描')}</Button>
          <span className="text-xs text-stone-500">{t('篩選會比對種類、名稱、型號與連線位置;空白 = 全部')}</span>
        </div>
        {scan.data && Object.entries(scan.data.errors).map(([k, e]) => <ErrorText key={k} error={`${d.kinds[k]?.label ?? k}:${e}`} />)}
        <ErrorText error={scan.error} />
        {scan.data && <div className="flex flex-wrap items-center gap-3 text-xs text-stone-600">
          <span>{t('找到 {length} 個:還沒使用 {length2} 個', { length: rows.length, length2: fresh.length })}{used.length ? t('、已在使用 {length} 個', { length: used.length }) : ''}</span>
          {used.length > 0 && <label className="flex items-center gap-1"><input type="checkbox" checked={showUsed} onChange={e => setShowUsed(e.target.checked)} />{t('列出已在使用的')}</label>}
        </div>}
        {scan.data && (Object.keys(byCat).length === 0 ? <Empty>{rows.length ? t('找到的都已經在使用了') : t('沒有找到符合的來源')}</Empty> :
          Object.entries(byCat).map(([cat, rs]) => {
            const hidden = rs.filter(r => r.per_source && r.ok === false)
            const shown = showMin ? rs : rs.filter(r => !hidden.includes(r))
            return (
              <div key={cat} className="flex flex-col gap-1.5">
                <div className="text-xs font-semibold text-stone-600">{t('{name}({n})', { name: cat, n: rs.length })}</div>
                {shown.map(r => <NativeRow key={`${r.kind}|${r.match}`} r={r} d={d} onRescan={rescanAs} onDone={() => { onChange(); scan.mutate(undefined) }} />)}
                {hidden.length > 0 && <button className="self-start text-xs underline text-stone-500" onClick={() => setShowMin(v => !v)}>
                  {showMin ? t('收起縮到最小的視窗') : t('另外 {length} 個縮到最小的視窗(要用的話先把它打開)', { length: hidden.length })}</button>}
              </div>
            )
          }))}
        <div className="border-t border-stone-200 pt-3"><ManualAdd d={d} onDone={onChange} /></div>
      </div>
    </>
  )
}

/** sources that cannot be found by looking (a camera's address): typed in */
function ManualAdd({ d, onDone }: { d: SourceView; onDone: () => void }) {
  const manual = Object.entries(d.kinds).filter(([, k]) => k.manual)
  const [kind, setKind] = useState<string | null>(null)
  const [p, setP] = useState<Record<string, string>>({})
  const [name, setName] = useState('')
  const [id, setId] = useState('')
  const k = kind ? d.kinds[kind] : null
  const add = useMutation({
    mutationFn: () => api.sourceAdd({ kind: kind!, match: name || p.url || kind!, name, id: id || undefined, params: { fit: 'contain', ...p } }),
    onSuccess: res => {
      setKind(null); setP({}); setName(''); setId('')
      if (res.trial?.length) alert(t('已加入。它在這些主腳本先設成「試跑」:{p1}。', { p1: res.trial.join(t('、')) }))
      onDone()
    },
  })
  if (!manual.length) return null
  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <span className="text-stone-600">{t('找不到的(例如攝影機)用位址加入:')}</span>
        {manual.map(([kid, x]) => <Button key={kid} variant={kind === kid ? 'primary' : 'ghost'} onClick={() => { setKind(kind === kid ? null : kid); setP({}) }}>+ {x.label}</Button>)}
      </div>
      {k && <div className="rounded-md border border-sky-200 bg-sky-50/50 p-2.5 flex flex-col gap-1.5 text-xs">
        <div className="text-stone-600">{k.note}</div>
        <label className="flex items-center gap-2"><span className="w-40 text-stone-600">{t('名稱')}</span>
          <input className={`${input} w-56`} placeholder={t('例如:魚池 A、大門口')} value={name} onChange={e => setName(e.target.value)} maxLength={40} /></label>
        <label className="flex items-center gap-2" title={t('腳本、排程、設定都用它,之後不能改')}><span className="w-40 text-stone-600">{t('代號')}</span>
          <input className={`${input} w-56 font-mono`} placeholder={t('不填 = 用名稱')} value={id} onChange={e => setId(e.target.value)} maxLength={40} /></label>
        {Object.entries(k.per_source).map(([pk, sp]) => <ParamInput key={pk} k={pk} sp={sp}
          value={p[pk] ?? (pk === 'fit' ? 'contain' : sp.type === 'select' ? Object.keys(sp.options ?? {})[0] : '')} suggested={undefined}
          onChange={v => setP({ ...p, [pk]: String(v) })} />)}
        {!k.has_hand && <div className="text-stone-500">{t('這種來源只能看;要讓腳本動作,加入後在「動作送到」交給另一個來源或送到輸出(例如 MQTT 開關)。')}</div>}
        <div className="flex gap-2"><Button variant="primary" disabled={!p.url || add.isPending} onClick={() => add.mutate()}>{t('加入')}</Button>
          <ErrorText error={add.error} /></div>
      </div>}
    </div>
  )
}

function NativeRow({ r, d, onDone, onRescan }: { r: SourceNative; d: SourceView; onDone: () => void; onRescan: (kind: string) => void }) {
  const [id, setId] = useState('')
  const [name, setName] = useState('')
  const [open, setOpen] = useState(false)
  const add = useMutation({ mutationFn: () => api.sourceAdd({ kind: r.kind, match: r.match, id: id || undefined, name: name || (r.per_source ? r.match.slice(0, 40) : ''), params: r.opts ?? undefined }),
    onSuccess: res => { if (res.trial?.length) alert(t('已加入。為了安全,它在這些主腳本先設成「試跑」(只判斷不點擊):{p1}。要正式執行請到「執行 › 部署」改。', { p1: res.trial.join(t('、')) })); onDone() } })
  const ign = useMutation({ mutationFn: () => api.sourceIgnore(r.kind, r.match, !r.ignored), onSuccess: onDone })
  const bound = d.items.find(it => it.id === r.bound)
  return (
    <div className={`rounded-md border px-2.5 py-2 flex flex-col gap-1.5 ${bound ? 'border-emerald-200 bg-emerald-50/40 text-stone-500' : 'border-stone-200 bg-white'}`}>
      <div className="flex flex-wrap items-center gap-2">
        <b>{r.match}</b>
        <span className="text-xs text-stone-500">{r.category_label ? `${r.category_label} › ` : ''}{r.kind_label.split('(')[0]}{r.detail ? ` · ${r.detail}` : ''}{r.size ? ` · ${sizeText(r.size)}` : ''}</span>
        <span className="flex-1" />
        {bound ? <Pill tone="green">{r.same_as ? t('就是已使用的「{label}」({p2})', { label: bound.label, p2: r.same_as.split('(')[0] }) : t('已使用:{label}', { label: bound.label })}{bound.enabled ? '' : t('(目前不使用)')}</Pill> : <>
          {r.ignored && <Pill>{t('已忽略')}</Pill>}
          <Button variant="primary" onClick={() => setOpen(v => !v)}>{t('使用…')}</Button>
          <Button variant="ghost" disabled={ign.isPending} onClick={() => ign.mutate()}>{r.ignored ? t('取消忽略') : t('忽略')}</Button>
        </>}
      </div>
      {!bound && r.suggest && <div className="flex flex-wrap items-center gap-2 text-xs text-sky-900 bg-sky-50 rounded px-2 py-1">
        {t('看起來是{label}:建議改用「{category_label} › {label2}」加入(點擊、輸入文字比較穩,也認得它的名字)', { label: r.suggest.label, category_label: r.suggest.category_label, label2: r.suggest.label })}
        <Button onClick={() => onRescan(r.suggest!.kind)}>{t('改用這一類掃描')}</Button></div>}
      {!bound && !r.suggest && r.size_warn && <div className="text-xs text-amber-800 bg-amber-50 rounded px-2 py-1">⚠ {r.size_warn}</div>}
      {open && !bound && <div className="flex flex-wrap items-center gap-2 text-xs bg-stone-50 rounded px-2 py-1.5">
        <label className="flex items-center gap-1">{t('名稱')}<input className={`${input} w-40`} placeholder={t('例如:主帳號、水車池 A')} value={name} onChange={e => setName(e.target.value)} maxLength={40} /></label>
        <label className="flex items-center gap-1" title={t('腳本、排程、設定都用它,之後不能改;不填 = 用它現在的名字')}>{t('代號')}<input className={`${input} w-40 font-mono`} placeholder={r.per_source ? t('例如 nvr_1') : r.match} value={id} onChange={e => setId(e.target.value)} maxLength={40} /></label>
        {r.per_source && <span className="text-stone-500">{t('之後用標題「{title}」和程式「{process}」找它;標題會變的話,加入後在「這個來源的設定」改成「包含」其中一段', { title: r.opts?.title, process: r.opts?.process })}</span>}
        <Button variant="primary" disabled={add.isPending} onClick={() => add.mutate()}>{t('開始使用')}</Button>
        <span className="text-stone-500">{t('之後到「執行 › 部署」決定它跑哪個腳本(新來源預設試跑,不會點擊)')}</span>
        <ErrorText error={add.error} />
      </div>}
    </div>
  )
}

const groups = (kinds: Record<string, SourceKindInfo>) => {
  const out: Record<string, [string, SourceKindInfo][]> = {}
  for (const [k, x] of Object.entries(kinds)) (out[x.category] ??= []).push([k, x])
  return out
}

/** 來源種類: categories (where the picture comes from), each with presets; a preset's 進階設定 start from its suggestion. */
function Kinds({ d, onChange }: { d: SourceView; onChange: () => void }) {
  return (
    <>
      <div className="flex flex-col gap-4 text-sm">
        <div className="text-xs text-stone-500">{t('依「畫面從哪裡來」分類;細項是某個產品的建議設定,每一項都可以在進階設定改。有來源在使用的種類會自動持續偵測。')}</div>
        {Object.entries(groups(d.kinds)).map(([cat, ks]) => (
          <div key={cat} className="flex flex-col gap-1.5">
            <div className="font-semibold text-stone-700">{ks[0][1].category_label}</div>
            {ks.map(([k, x]) => <KindRow key={k} id={k} x={x} onChange={onChange} />)}
          </div>
        ))}
      </div>
    </>
  )
}

function KindRow({ id, x, onChange }: { id: string; x: SourceKindInfo; onChange: () => void }) {
  const [open, setOpen] = useState(false)
  const [edit, setEdit] = useState<Record<string, unknown> | null>(null)
  const set = useMutation({ mutationFn: (b: { on: boolean; params: Record<string, unknown> }) => api.sourceKind(id, b.on, b.params),
    onSuccess: () => { setEdit(null); onChange() } })
  const p = edit ?? x.params_set
  const val = (k: string) => (k in p ? p[k] : x.defaults[k])
  const changed = Object.keys(x.params_set).length
  return (
    <div className={`rounded-md border px-2.5 py-1.5 ${x.in_use ? 'border-stone-300 bg-white' : 'border-stone-200'}`}>
      <div className="flex flex-wrap items-center gap-3">
        <b className="flex-1 min-w-48">{x.label}</b>
        {x.in_use > 0 ? <Pill tone="green">{t('使用中 {in_use} 個來源', { in_use: x.in_use })}</Pill> : <span className="text-xs text-stone-400">{t('沒有使用')}</span>}
        <span className="text-[11px] text-stone-400" title={x.caps.map(c => CAP[c] ?? c).join(t('、'))}>{t('能做 {length} 件事', { length: x.caps.length })}</span>
        <span className="flex-1" />
        {Object.keys(x.params).length > 0 && <button className="text-xs underline text-stone-600" onClick={() => setOpen(v => !v)}>
          {t('進階設定')}{changed ? t('(改了 {changed} 項)', { changed }) : ''}</button>}
      </div>
      {x.note && <div className="text-xs text-stone-500 mt-0.5">{x.note}</div>}
      {open && <div className="flex flex-col gap-1.5 mt-2 pl-5">
        {Object.entries(x.params).map(([k, sp]) => <ParamInput key={k} k={k} sp={sp} value={val(k)} suggested={x.defaults[k]}
          onChange={v => setEdit({ ...p, [k]: v })} />)}
        <div className="flex gap-2">
          <Button variant="primary" disabled={!edit || set.isPending} onClick={() => set.mutate({ on: x.on, params: p })}>{t('儲存')}</Button>
          {changed > 0 && <Button variant="ghost" disabled={set.isPending} onClick={() => set.mutate({ on: x.on, params: {} })}>{t('全部回到建議值')}</Button>}
          <ErrorText error={set.error} />
        </div>
      </div>}
    </div>
  )
}

function ParamInput({ k, sp, value, suggested, onChange }: { k: string; sp: SourceParam; value: unknown; suggested: unknown; onChange: (v: unknown) => void }) {
  const tip = suggested !== undefined && suggested !== '' ? t('建議:{value}', { value: String(sp.type === 'select' ? sp.options?.[String(suggested)] ?? suggested : sp.type === 'bool' ? (suggested ? t('開') : t('關')) : suggested) }) : ''
  return (
    <label className="flex flex-wrap items-center gap-2 text-xs" title={sp.help}>
      <span className="w-40 text-stone-600">{sp.label}</span>
      {sp.type === 'select' ? <select className={input} value={String(value ?? '')} onChange={e => onChange(e.target.value)}>
          {Object.entries(sp.options ?? {}).map(([o, tx]) => <option key={o} value={o}>{tx}</option>)}</select>
        : sp.type === 'bool' ? <input type="checkbox" checked={value === true || value === 'True' || value === 'true'} onChange={e => onChange(e.target.checked)} />
        : <input className={`${input} w-72`} value={String(value ?? '')} placeholder={sp.help ?? ''} onChange={e => onChange(e.target.value)} />}
      {tip && <span className="text-stone-400">{tip}</span>}
      <code className="text-[10px] text-stone-300">{k}</code>
    </label>
  )
}

const CAP: Record<string, string> = { screen: t('取得畫面'), tap: t('點擊'), long_press: t('長按'), swipe: t('滑動'), back: t('返回鍵'), launch: t('啟動 App'), text: t('輸入文字'), touch_watch: t('偵測有人操作') }
