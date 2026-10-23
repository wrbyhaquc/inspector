import { t } from '../i18n'
import { PageIntro } from '../components/PageIntro'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { api, type PanelBlock, type PanelChatPreview, type PanelControl, type PanelDefinition, type PanelWidget, type SettingDecl } from '../api'
import { Button, Card, Drawer, Empty, ErrorText, Modal, MoreButton, Page } from '../components/ui'
import { words } from '../lib/project'
import { sourceIds } from '../lib/sources'
import { SourcePick } from '../components/SourcePick'
import { COLS, span, widthFor } from '../lib/panelLayout'

const input = 'border border-stone-300 rounded-md px-2 py-1 text-sm bg-white'
type Panel = PanelDefinition['panel']
type Ctl = PanelControl & { bind: { kind: string; [k: string]: unknown } }

const newId = (base: string, taken: string[]) => { let i = 1; while (taken.includes(`${base}${i}`)) i++; return `${base}${i}` }
const move = <T,>(xs: T[], i: number, d: number) => { const n = [...xs]; const [x] = n.splice(i, 1); n.splice(i + d, 0, x); return n }

/** Consultants build the end users' operation panel: blocks of controls, each wired to a real setting. */
export default function PanelDesign() {
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['panelDefinition'], queryFn: api.panelDefinition })
  const [p, setP] = useState<Panel | null>(null)
  useEffect(() => { if (q.data && !p) setP(JSON.parse(JSON.stringify(q.data.panel))) }, [q.data, p])
  const save = useMutation({ mutationFn: () => api.panelDefinitionSave(p!), onSuccess: () => { qc.invalidateQueries({ queryKey: ['panelDefinition'] }); qc.invalidateQueries({ queryKey: ['panel'] }) } })
  const [openCtl, setOpenCtl] = useState<string | null>(null)
  const [win, setWin] = useState<'settings' | 'chat' | null>(null)
  if (!q.data || !p) return <Page title={t('操作面板設計')}><Card><Empty>{q.isLoading ? t('讀取中…') : t('讀取失敗')}</Empty></Card></Page>
  const info = q.data
  const same = (x: Panel) => JSON.stringify({ ...x, format: undefined })     // the spec version is the server's to stamp
  const dirty = same(p) !== same(info.panel)
  const edit = (fn: (x: Panel) => void) => setP(old => { const n = JSON.parse(JSON.stringify(old)) as Panel; fn(n); return n })
  const ctl = (id: string) => p.controls.find(c => c.id === id) as Ctl | undefined
  const devices = [...new Set([...sourceIds(info.devices), ...p.devices])]
  const addControl = (b: number) => {
    const id = newId('c', p.controls.map(c => c.id))
    const s = info.schedules[0]
    edit(x => { x.controls.push({ id, label: t('新的設定'), type: 'toggle', scope: 'global', bind: { kind: 'schedule', schedule: s?.id, field: 'enabled' } }); x.blocks[b].items.push(id) })
    setOpenCtl(id)
  }

  return (
    <Page title={t('操作面板設計')} intro={<PageIntro id="panel-design" what={t('現場的人只看操作面板:現在怎樣、幾個按鈕、幾個設定;這頁決定面板上有什麼。')} start={t('加一個區塊,放進監看元件(狀態、數值)和開關,接到排程或腳本。')} ch={11} />} desc={t('給使用者(長輩、現場人員)的操作面板:用區塊整理「一件事」的開關和設定,每一項接到底層的排程或腳本。使用者只看得到這裡放的東西。')}>
      <div className="sticky top-0 z-20 -mx-6 px-6 py-3 bg-stone-50/95 backdrop-blur border-b border-stone-200 flex flex-wrap items-center gap-2">
        <input className={`${input} w-64 font-medium`} value={p.title} onChange={e => edit(x => { x.title = e.target.value })} />
        <span className="flex-1" />
        {dirty && <span className="text-xs text-amber-700">{t('● 有未儲存的修改')}</span>}
        {dirty && <Button variant="ghost" onClick={() => setP(JSON.parse(JSON.stringify(info.panel)))}>{t('放棄修改')}</Button>}
        <Button variant="primary" disabled={!dirty || save.isPending} onClick={() => save.mutate()}>{save.isPending ? t('儲存中…') : t('儲存')}</Button>
        <MoreButton onClick={() => setWin('settings')}>{t('⚙ 面板設定')}</MoreButton>
        <MoreButton onClick={() => setWin('chat')}>{t('聊天裡可以做的事')}</MoreButton>
        <a href="/panel" target="_blank" rel="noreferrer" className="text-sm underline">{t('預覽操作面板 ↗')}</a>
        <div className="basis-full"><ErrorText error={save.error} /></div>
      </div>

      <Drawer open={win === 'settings'} title={t('面板設定')} onClose={() => setWin(null)}>
      <AccessCard />

      <Card title={t('顯示哪些機台')}>
        <div className="flex flex-wrap gap-3 text-sm">
          <SourcePick value={p.devices} devices={devices} onChange={v => edit(x => { x.devices = v })} />
          <span className="text-xs text-stone-500">{p.devices.length ? t('依勾選順序顯示') : t('都沒勾 = 全部顯示')}</span>
        </div>
      </Card>
      <SourcePolicyCard p={p} info={info} edit={edit} />
        <div className="text-xs text-stone-500">{t('「顯示哪些機台」「使用者可以加入的來源」改完要按上方「儲存」')}</div>
      </Drawer>

      <PagesCard p={p} edit={edit} />
      <LayoutCard p={p} edit={edit} info={info} />

      {p.blocks.map((b, bi) => (
        <div key={b.id} id={`design-block-${b.id}`} className="scroll-mt-20">
        <Card title={<span className="flex items-center gap-2">
          <input className={`${input} font-medium w-56`} value={b.title} onChange={e => edit(x => { x.blocks[bi].title = e.target.value })} />
          <span className="text-xs text-stone-400">{b.widget ? t('監看元件:{p1}', { p1: info.widgets[b.widget.kind] ?? b.widget.kind }) : t('區塊 {p1}', { p1: bi + 1 })}</span></span>}
          extra={<span className="flex flex-wrap items-center gap-1">
            {(p.pages ?? []).length > 0 && <select className={`${input} text-xs`} title={t('放在哪個分頁')} value={(p.pages ?? []).some(g => g.id === b.page) ? b.page : p.pages![0].id}
              onChange={e => edit(x => { x.blocks[bi].page = e.target.value })}>
              {p.pages!.map(g => <option key={g.id} value={g.id}>{t('分頁:{title}', { title: g.title })}</option>)}</select>}
            <select className={`${input} text-xs`} title={t('寬螢幕上的寬度(手機上一律一欄)')} value={b.width ?? 'auto'}
              onChange={e => edit(x => { if (e.target.value === 'auto') delete x.blocks[bi].width; else x.blocks[bi].width = e.target.value as NonNullable<PanelBlock['width']> })}>
              {WIDTHS.map(([v, tx]) => <option key={v} value={v}>{tx}</option>)}</select>
            <Button variant="ghost" disabled={bi === 0} onClick={() => edit(x => { x.blocks = move(x.blocks, bi, -1) })}>▲</Button>
            <Button variant="ghost" disabled={bi === p.blocks.length - 1} onClick={() => edit(x => { x.blocks = move(x.blocks, bi, 1) })}>▼</Button>
            <Button variant="ghost" onClick={() => { if (confirm(b.widget ? t('刪除監看元件「{title}」?', { title: b.title }) : t('刪除區塊「{title}」和它的設定?', { title: b.title }))) edit(x => {
              const gone = new Set([...x.blocks[bi].items, x.blocks[bi].toggle].filter(Boolean))
              x.controls = x.controls.filter(c => !gone.has(c.id)); x.blocks.splice(bi, 1)
            }) }}>{t('刪除')}</Button></span>}>
          {b.widget ? <div className="flex flex-col gap-3 text-sm">
            <input className={input} placeholder={t('一句話說明這個區塊(使用者看得到)')} value={b.help ?? ''} onChange={e => edit(x => { x.blocks[bi].help = e.target.value })} />
            <WidgetEditor w={b.widget} info={info} onChange={fn => edit(x => fn(x.blocks[bi].widget!))} />
          </div> : <div className="flex flex-col gap-3 text-sm">
            <input className={input} placeholder={t('一句話說明這個區塊在做什麼(使用者看得到)')} value={b.help ?? ''} onChange={e => edit(x => { x.blocks[bi].help = e.target.value })} />
            <label className="flex items-center gap-2">{t('標題旁的大開關')}
              <select className={input} value={b.toggle ?? ''} onChange={e => edit(x => {
                const blk = x.blocks[bi]; const prev = blk.toggle
                blk.toggle = e.target.value || undefined
                blk.items = blk.items.filter(i => i !== blk.toggle)
                if (prev && prev !== blk.toggle) blk.items.unshift(prev)
              })}>
                <option value="">{t('(沒有)')}</option>
                {[b.toggle, ...b.items].filter(Boolean).map(i => ctl(i!)).filter(c => c && c.type === 'toggle' && c.scope !== 'device')
                  .map(c => <option key={c!.id} value={c!.id}>{c!.label}</option>)}
              </select></label>
            {b.toggle && ctl(b.toggle) && <ControlEditor c={ctl(b.toggle)!} info={info} open={openCtl === b.toggle} onOpen={() => setOpenCtl(o => o === b.toggle ? null : b.toggle!)}
              onChange={fn => edit(x => fn(x.controls.find(c => c.id === b.toggle) as Ctl))} header />}
            {b.items.map((id, ii) => ctl(id) && (
              <ControlEditor key={id} c={ctl(id)!} info={info} open={openCtl === id} onOpen={() => setOpenCtl(o => o === id ? null : id)}
                onChange={fn => edit(x => fn(x.controls.find(c => c.id === id) as Ctl))}
                onMove={dlt => edit(x => { x.blocks[bi].items = move(x.blocks[bi].items, ii, dlt) })} first={ii === 0} last={ii === b.items.length - 1}
                onDelete={() => edit(x => { x.blocks[bi].items.splice(ii, 1); x.controls = x.controls.filter(c => c.id !== id) })} />
            ))}
            <button className="self-start text-sm underline" onClick={() => addControl(bi)}>{t('+ 在這個區塊加一項設定')}</button>
          </div>}
        </Card>
        </div>
      ))}
      <Modal open={win === 'chat'} wide title={t('聊天裡可以做的事')} onClose={() => setWin(null)}><ChatPreview panel={p} /></Modal>

      <div className="flex flex-wrap items-center gap-3">
        <Button onClick={() => edit(x => { x.blocks.push({ id: newId('b', x.blocks.map(b => b.id)), title: t('新的區塊'), items: [] } as PanelBlock) })}>{t('+ 新增設定區塊')}</Button>
        <span className="text-sm text-stone-500">{t('或新增監看元件:')}</span>
        {Object.entries(info.widgets).map(([k, tx]) => (
          <Button key={k} variant="ghost" onClick={() => edit(x => {
            x.blocks.push({ id: newId('w', x.blocks.map(b => b.id)), title: tx, items: [],
              widget: { kind: k as PanelWidget['kind'], ...JSON.parse(JSON.stringify(info.widget_defaults[k] ?? {})) } })
          })}>+ {tx}</Button>
        ))}
      </div>
    </Page>
  )
}

/** What a watch widget shows the users, and what they may change there. */
/** What the people running the pack may scan for and pick ("選擇模擬器" on their panel): kinds (or a whole category),
 * a name filter, what to have ready, how a picked one starts. */
function SourcePolicyCard({ p, info, edit }: { p: Panel; info: PanelDefinition; edit: (fn: (x: Panel) => void) => void }) {
  const pol = p.sources ?? {}
  const kinds = info.source_kinds ?? []
  const cats = [...new Map(kinds.map(k => [k.category ?? k.kind.split('/')[0], k.category_label ?? k.kind.split('/')[0]])).entries()]
  const has = (k: string) => (pol.kinds ?? []).includes(k)
  const set = (fn: (s: NonNullable<Panel['sources']>) => void) => edit(x => { const s = { ...(x.sources ?? {}) }; fn(s); x.sources = s })
  const tick = (k: string, v: boolean) => set(s => { const cur = s.kinds ?? []; s.kinds = v ? [...cur, k] : cur.filter(x => x !== k) })
  return (
    <Card title={t('使用者可以加入的來源')} extra={<span className="text-xs text-stone-500">{t('使用者面板右上角的「選擇…」:掃描這些,勾選要用的')}</span>}>
      <div className="flex flex-col gap-3 text-sm">
        {cats.map(([c, cl]) => (
          <div key={c} className="flex flex-col gap-1">
            <label className="flex items-center gap-1.5 font-medium"><input type="checkbox" checked={has(`${c}/*`)} onChange={e => tick(`${c}/*`, e.target.checked)} />{t('{cl}(整個大類,之後新增的產品也算)', { cl })}</label>
            {!has(`${c}/*`) && <div className="flex flex-wrap gap-3 ml-5">
              {kinds.filter(k => (k.category ?? k.kind.split('/')[0]) === c).map(k => (
                <label key={k.kind} className="flex items-center gap-1"><input type="checkbox" checked={has(k.kind)} onChange={e => tick(k.kind, e.target.checked)} />{k.label}</label>))}
            </div>}
          </div>
        ))}
        <label className="flex flex-col gap-1"><span className="text-stone-600">{t('名稱過濾(找到的名稱或說明要有這些字,空白分開;不填 = 不過濾)')}</span>
          <input className={input} value={pol.q ?? ''} placeholder={t('例:NVR 北棟')} onChange={e => set(s => { s.q = e.target.value || undefined })} /></label>
        <label className="flex flex-col gap-1"><span className="text-stone-600">{t('掃描前要準備什麼(使用者看得到)')}</span>
          <input className={input} value={pol.help ?? ''} placeholder={t('例:先開好模擬器,並登入 App')} onChange={e => set(s => { s.help = e.target.value || undefined })} /></label>
        <label className="flex items-center gap-2"><span className="text-stone-600">{t('勾選後,主腳本在這台')}</span>
          <select className={input} value={pol.new_mode ?? 'shadow'} onChange={e => set(s => { s.new_mode = e.target.value as 'shadow' | 'live' })}>
            <option value="shadow">{t('先試跑(只看不點,之後到部署改正式)')}</option><option value="live">{t('直接正式執行(和其他台一樣)')}</option>
          </select></label>
        {!(pol.kinds ?? []).length && <div className="text-xs text-amber-700">{t('都沒勾 = 使用者不能自己選來源(由導入顧問在「來源」頁設定)')}</div>}
      </div>
    </Card>
  )
}

/** The tabs of the users' panel: none = one page; each block is on one (the 這台 view comes by itself). */
const WIDTHS: [NonNullable<PanelBlock['width']>, string][] = [['auto', t('寬度:自動')], ['third', t('寬度:1/3 列')], ['narrow', t('寬度:半列')],
  ['two_thirds', t('寬度:2/3 列')], ['wide', t('寬度:整列')]]

/** The panel's layout as the users' wide screen shows it: drag a block to move it (onto a tab: to that page), drag its
 * right edge to make it wider or narrower. */
function LayoutCard({ p, edit, info }: { p: Panel; edit: (fn: (x: Panel) => void) => void; info: PanelDefinition }) {
  const pages = p.pages ?? []
  const [tab, setTab] = useState(pages[0]?.id ?? '')
  const [drag, setDrag] = useState<string | null>(null)
  const [over, setOver] = useState<string | null>(null)
  const grid = useRef<HTMLDivElement>(null)
  const byId = Object.fromEntries(p.controls.map(c => [c.id, c]))
  const pageOf = (b: PanelBlock) => (pages.some(g => g.id === b.page) ? b.page! : pages[0]?.id ?? '')
  const cur = pages.some(g => g.id === tab) ? tab : pages[0]?.id ?? ''
  const shown = p.blocks.filter(b => pageOf(b) === cur)
  const moveTo = (id: string, before: string | null, page: string) => edit(x => {
    const i = x.blocks.findIndex(b => b.id === id)
    const [b] = x.blocks.splice(i, 1)
    if (page && page !== (x.pages ?? [])[0]?.id) b.page = page
    else delete b.page                                              // the first page: where a block without one is
    const j = before ? x.blocks.findIndex(o => o.id === before) : -1
    x.blocks.splice(j < 0 ? x.blocks.length : j, 0, b)
  })
  const resize = (e: React.PointerEvent, b: PanelBlock) => {        // the right edge: the width follows the pointer
    e.preventDefault(); e.stopPropagation()
    const left = (e.currentTarget.parentElement as HTMLElement).getBoundingClientRect().left
    const col = (grid.current?.clientWidth ?? 600) / COLS
    const onMove = (m: PointerEvent) => {
      const w = widthFor(Math.max(1, Math.round((m.clientX - left) / col)))
      edit(x => { const blk = x.blocks.find(o => o.id === b.id); if (blk) blk.width = w })
    }
    const onUp = () => { window.removeEventListener('pointermove', onMove); window.removeEventListener('pointerup', onUp) }
    window.addEventListener('pointermove', onMove); window.addEventListener('pointerup', onUp)
  }
  const drop = (e: React.DragEvent, fn: () => void) => { e.preventDefault(); if (drag) fn(); setDrag(null); setOver(null) }
  const label = (b: PanelBlock) => WIDTHS.find(([v]) => v === (b.width ?? 'auto'))![1]
  return (
    <Card title={t('版面')} extra={<span className="text-xs text-stone-500">{t('寬螢幕上的樣子:拖拉區塊排順序(拖到分頁上 = 移到那頁),拖右邊邊緣改寬度;手機上一律一欄')}</span>}>
      <div className="flex flex-col gap-3">
        {pages.length > 0 && <div className="flex gap-1 border-b border-stone-200">
          {pages.map(g => <button key={g.id} onClick={() => setTab(g.id)}
            onDragOver={e => { if (drag) { e.preventDefault(); setOver(`tab:${g.id}`) } }} onDragLeave={() => setOver(null)}
            onDrop={e => drop(e, () => { if (g.id !== cur) moveTo(drag!, null, g.id) })}
            className={`px-3 py-1.5 text-sm -mb-px border-b-2 ${g.id === cur ? 'border-stone-900 font-medium' : 'border-transparent text-stone-500'} ${over === `tab:${g.id}` ? 'bg-sky-100' : ''}`}>{g.title}</button>)}
        </div>}
        <div ref={grid} className="grid grid-cols-6 gap-2" data-testid="layout">
          {shown.map(b => (
            <div key={b.id} draggable data-block={b.id} onDragStart={e => { setDrag(b.id); e.dataTransfer.effectAllowed = 'move' }}
              onDragEnd={() => { setDrag(null); setOver(null) }}
              onDragOver={e => { if (drag && drag !== b.id) { e.preventDefault(); setOver(b.id) } }} onDragLeave={() => setOver(o => (o === b.id ? null : o))}
              onDrop={e => drop(e, () => { if (drag !== b.id) moveTo(drag!, b.id, pageOf(b)) })}
              className={`${GRID_SPAN[span(b, byId)]} relative rounded-md border bg-white px-3 py-2 pr-5 cursor-grab select-none text-sm
                ${drag === b.id ? 'opacity-40' : ''} ${over === b.id ? 'border-sky-500 ring-2 ring-sky-200' : 'border-stone-300'}`}>
              <button className="font-medium text-left hover:underline" onClick={() => document.getElementById(`design-block-${b.id}`)?.scrollIntoView({ behavior: 'smooth' })}>{b.title}</button>
              <div className="text-xs text-stone-500">{b.widget ? info.widgets[b.widget.kind] ?? b.widget.kind : t('{n} 項設定', { n: b.items.length + (b.toggle ? 1 : 0) })}
                {' · '}{label(b)}{(b.width ?? 'auto') === 'auto' ? `(${span(b, byId) === COLS ? t('整列') : t('半列')})` : ''}</div>
              <span onPointerDown={e => resize(e, b)} title={t('拖這裡改寬度')} data-edge={b.id}
                className="absolute right-0 top-0 h-full w-3 cursor-ew-resize rounded-r-md bg-stone-100 hover:bg-sky-200 border-l border-stone-200" />
            </div>
          ))}
          <div onDragOver={e => { if (drag) { e.preventDefault(); setOver('end') } }} onDragLeave={() => setOver(null)}
            onDrop={e => drop(e, () => moveTo(drag!, null, cur))}
            className={`col-span-6 rounded-md border border-dashed px-3 py-2 text-xs text-stone-400 ${over === 'end' ? 'border-sky-500 bg-sky-50' : 'border-stone-300'}`}>
            {shown.length ? t('拖到這裡 = 放到這頁最後') : t('這頁還沒有區塊;把區塊拖到這裡或上面的分頁')}</div>
        </div>
      </div>
    </Card>
  )
}
// the layout card's own grid (always six columns, whatever the screen)
const GRID_SPAN: Record<number, string> = { 2: 'col-span-2', 3: 'col-span-3', 4: 'col-span-4', 6: 'col-span-6' }

function PagesCard({ p, edit }: { p: Panel; edit: (fn: (x: Panel) => void) => void }) {
  const pages = p.pages ?? []
  const count = (id: string, first: boolean) => p.blocks.filter(b => b.page === id || (first && !pages.some(g => g.id === b.page))).length
  return (
    <Card title={t('分頁')} extra={<span className="text-xs text-stone-500">{t('使用者面板上的分頁;每台的「這台」頁會自動加在最後')}</span>}>
      <div className="flex flex-col gap-2 text-sm">
        {pages.length === 0 && <div className="text-stone-500">{t('目前只有一頁「總覽」,所有區塊都在上面。區塊多的話,可以分成幾頁(例如「現況」「排程設定」「通知」)。')}</div>}
        {pages.map((g, gi) => (
          <div key={g.id} className="flex flex-wrap items-center gap-2">
            <input className={`${input} w-48`} value={g.title} onChange={e => edit(x => { x.pages![gi].title = e.target.value })} />
            <span className="text-xs text-stone-500">{t('{p1} 個區塊', { p1: count(g.id, gi === 0) })}{gi === 0 ? t('(沒指定分頁的區塊也在這頁)') : ''}</span>
            <span className="flex-1" />
            <Button variant="ghost" disabled={gi === 0} onClick={() => edit(x => { x.pages = move(x.pages!, gi, -1) })}>▲</Button>
            <Button variant="ghost" disabled={gi === pages.length - 1} onClick={() => edit(x => { x.pages = move(x.pages!, gi, 1) })}>▼</Button>
            <Button variant="ghost" onClick={() => { if (confirm(t('刪除分頁「{title}」?上面的區塊會移到第一個分頁。', { title: g.title }))) edit(x => {
              x.pages!.splice(gi, 1)
              for (const b of x.blocks) if (b.page === g.id) delete b.page
              if (!x.pages!.length) delete x.pages
            }) }}>{t('刪除')}</Button>
          </div>
        ))}
        <button className="self-start underline" onClick={() => edit(x => {
          const ids = (x.pages ?? []).map(g => g.id)
          if (!x.pages?.length) x.pages = [{ id: 'main', title: t('總覽') }, { id: 'page2', title: t('新的分頁') }]
          else x.pages.push({ id: newId('page', ids), title: t('新的分頁') })
        })}>+ {pages.length ? t('新增分頁') : t('分成幾個分頁')}</button>
      </div>
    </Card>
  )
}

function WidgetEditor({ w, info, onChange }: { w: PanelWidget; info: PanelDefinition; onChange: (fn: (w: PanelWidget) => void) => void }) {
  const flag = (k: string, label: string, help?: string) => (
    <label className="flex items-center gap-1.5" title={help}><input type="checkbox" checked={!!w[k]} onChange={e => onChange(x => { x[k] = e.target.checked })} />{label}</label>)
  const ids = (k: string) => (w[k] as string[] | undefined) ?? []
  const pick = (k: string, id: string, on: boolean) => onChange(x => { const cur = (x[k] as string[] | undefined) ?? []; x[k] = on ? [...cur, id] : cur.filter(y => y !== id) })
  const limit = <label className="flex items-center gap-1">{t('最多顯示')}<input type="number" min={1} max={200} className={`${input} w-20`} value={Number(w.limit ?? 10)}
    onChange={e => onChange(x => { x.limit = Number(e.target.value) || 1 })} />{t('筆')}</label>
  switch (w.kind) {
    case 'devices': return <div className="flex flex-wrap gap-4">
      <span className="text-stone-600">{t('每台的狀態,另外顯示:')}</span>
      {flag('show_step', t('目前這一步'), t('例如「等待 55 分鐘 · 還剩 12:30」'))}{flag('show_alerts', t('最近的提醒'))}{flag('show_image', t('即時小畫面'), t('每 3 秒更新一次'))}
    </div>
    case 'incidents': return <div className="flex flex-wrap items-center gap-4">{limit}{flag('show_frames', t('顯示發生當下的畫面'))}</div>
    case 'deploy': return <div className="flex flex-col gap-2">
      <div className="flex flex-wrap gap-3"><span className="text-stone-600">{t('使用者可以切換的主腳本:')}</span>
        {info.main_scripts.map(s => <label key={s.id} className="flex items-center gap-1"><input type="checkbox" checked={ids('scripts').includes(s.id)} onChange={e => pick('scripts', s.id, e.target.checked)} />{s.name}</label>)}</div>
      <div className="flex flex-wrap gap-3"><span className="text-stone-600">{t('可以選的方式:')}</span>
        {Object.entries(info.modes).map(([m, tx]) => <label key={m} className="flex items-center gap-1"><input type="checkbox" checked={ids('modes').includes(m)} onChange={e => pick('modes', m, e.target.checked)} />{tx}</label>)}</div>
      <span className="text-xs text-stone-500">{t('使用者只能在勾選的方式之間切換;改了會存成主腳本的新版本,和「執行 › 部署」一樣。')}</span>
    </div>
    case 'schedules': return <div className="flex flex-wrap gap-3">
      <span className="text-stone-600">{t('顯示哪些排程:')}</span>
      {info.schedules.map(s => <label key={s.id} className="flex items-center gap-1"><input type="checkbox" checked={ids('schedules').includes(s.id)} onChange={e => pick('schedules', s.id, e.target.checked)} />{s.name}</label>)}
      <span className="text-xs text-stone-500">{ids('schedules').length ? '' : t('都沒勾 = 所有開著的排程')}</span>
    </div>
    case 'list': return <div className="flex flex-col gap-2">
      <label className="flex items-center gap-2"><span className="text-stone-600">{t('顯示哪一份清單')}</span>
        <select className={input} value={String(w.list ?? '')} onChange={e => onChange(x => { x.list = e.target.value })}>
          <option value="">{t('(請選擇)')}</option>
          {info.lists.map(l => <option key={l.id} value={l.id}>{l.title}{l.per_device ? t('(每台各自)') : ''}</option>)}
        </select></label>
      <label className="flex items-center gap-2"><span className="text-stone-600">{t('掃描按鈕執行的子腳本')}</span>
        <select className={input} value={String(w.scan_sub ?? '')} onChange={e => onChange(x => { x.scan_sub = e.target.value })}>
          <option value="">{t('(不放掃描按鈕)')}</option>
          {info.runnable_subs.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
        </select></label>
      <div className="flex flex-wrap gap-4">{flag('rename', t('使用者可以改名稱'), t('掃描存下的是名字的圖片,預設名稱是「項目 3」這類,讓使用者取好認的名字'))}
        {flag('remove', t('使用者可以移除'), t('刪掉或改名的項目:掃描時會標「沒看到」,先不輪到它;使用者確認後移除'))}</div>
      <span className="text-xs text-stone-500">{t('每台(或共用)一份:上次掃描的結果、每個名字的圖片,新的標「新」、這次沒看到的標「沒看到」。')}</span>
    </div>
    case 'log': return <div className="flex flex-wrap items-center gap-4">{limit}{flag('panel_changes', t('也列出使用者在面板上的修改'))}
      <span className="text-xs text-stone-500">{t('紀錄包含:排程開始/結束、緊急規則、失敗與提醒')}</span></div>
    case 'chat': return <div className="flex flex-col gap-2">
      <div className="flex flex-wrap gap-4">
        {flag('setup', t('可以新增 Bot、換 Token、移除'), t('使用者自己建 Discord / Telegram Bot 貼上 Token'))}
        {flag('pair', t('可以配對、移除可以下指令的人'))}
      </div>
      <span className="text-xs text-stone-500">{t('Bot 存在執行的這台電腦(和「執行 › 通知」同一份);配對過的人在聊天裡能做的,就是這個面板開放的(見下方「聊天裡可以做的事」)。')}</span>
    </div>
    default: return null
  }
}

const PARAM_TYPE: Record<string, string> = { point: t('位置'), number: t('數字'), text: t('文字'), list: t('清單') }

function ControlEditor({ c, info, open, onOpen, onChange, onMove, onDelete, first, last, header }: {
  c: Ctl; info: PanelDefinition; open: boolean; onOpen: () => void; onChange: (fn: (c: Ctl) => void) => void
  onMove?: (d: number) => void; onDelete?: () => void; first?: boolean; last?: boolean; header?: boolean
}) {
  const b = c.bind
  const sched = info.schedules.find(s => s.id === b.schedule)
  const entry = info.entries.find(e => e.script === b.script && e.situation === b.situation)
  const params = b.kind === 'schedule_arg' ? sched?.params ?? [] : b.kind === 'entry_arg' ? entry?.params ?? [] : []
  const param = params.find(x => x.name === b.param)
  // the control's type follows what it is wired to
  const suggest = (kind: string, field?: string, pm?: { type: string; item?: string | null; from_list?: string | null }) => (x: Ctl) => {
    if (kind.startsWith('act_')) { x.type = 'action'; x.scope = x.scope ?? 'device'; delete x.options; delete x.unit; delete x.scale; delete x.min; delete x.max }
    else if (kind === 'schedule') { x.type = field === 'at' ? 'time' : 'toggle'; x.scope = 'global' }
    else if (kind === 'schedule_device') { x.type = 'toggle'; x.scope = 'device' }
    else if (pm) {
      delete x.options; delete x.unit; delete x.scale; delete x.min; delete x.max
      if (pm.type === 'number') { x.type = 'number'; x.unit = ''; x.scale = 1 }
      else if (pm.type === 'list') { x.type = 'multi'; x.options = pm.from_list ? `list:${pm.from_list}` : [] }
      else if (pm.type === 'point') { x.type = 'single'; x.options = [] }
      else x.type = 'single'
    }
  }
  const setting = b.kind === 'setting' ? info.settings.find(s => s.id === b.setting) : undefined
  const fromSetting = (s: SettingDecl | undefined) => (x: Ctl) => {
    if (!s) return
    delete x.options; delete x.unit; delete x.scale; delete x.min; delete x.max
    x.scope = s.scope === 'device' ? 'device' : 'global'
    x.type = ({ number: 'number', bool: 'toggle', time: 'time', point: 'single', list: 'multi' } as Record<string, PanelControl['type']>)[s.type] ?? 'single'
    if (s.pick_from) x.options = s.pick_from as PanelControl['options']
    if (s.type === 'number') { x.unit = ''; x.scale = 1 }
    if (!x.label || x.label === t('新的控制項') || x.label === '新的控制項') x.label = s.label
  }
  const where = b.kind === 'setting' ? (setting ? t('使用者設定「{label}」', { label: setting.label }) : t('請選擇使用者設定'))
    : b.kind === 'schedule' ? b.field === 'at' ? t('排程「{name}」的開始時間', { name: sched?.name ?? b.schedule }) : t('排程「{name}」的開關', { name: sched?.name ?? b.schedule })
    : b.kind === 'schedule_device' ? t('這台要不要參加排程「{p1}」', { p1: sched?.name ?? b.schedule })
    : b.kind === 'schedule_arg' ? t('排程「{p1}」的參數「{p2}」', { p1: sched?.name ?? b.schedule, p2: param?.label ?? b.param })
    : b.kind === 'entry_arg' ? t('「{p1}」{p2} 的參數「{p3}」', { p1: entry?.script_name ?? b.script, p2: entry?.situation_name ?? '', p3: param?.label ?? b.param })
    : b.kind === 'act_schedule' ? t('按下就立即執行排程「{p1}」', { p1: sched?.name ?? b.schedule })
    : b.kind === 'act_sub' ? t('按下就執行子腳本「{p1}」', { p1: info.runnable_subs.find(s => s.id === b.sub)?.name ?? b.sub })
    : b.kind === 'act_situation' ? (() => { const sc = info.scripts.find(y => y.id === b.script); return t('按下就讓「{p1}」切到「{p2}」', { p1: sc?.name ?? b.script, p2: sc?.situations.find(y => y.id === b.situation)?.name ?? String(b.situation ?? '') }) })()
    : b.kind === 'act_stop' ? t('按下就停止這台正在做的事') : t('還沒設定')
  return (
    <div className={`rounded-md border ${open ? 'border-stone-400' : 'border-stone-200'} ${header ? 'bg-amber-50/50' : 'bg-white'}`}>
      <div className="flex items-center gap-2 px-3 py-2">
        <button className="flex-1 text-left" onClick={onOpen}>
          <span className="font-medium">{c.label}</span>
          <span className="text-xs text-stone-500 ml-2">{info.types[c.type]} · {c.scope === 'device' ? t('每台各自') : t('全部共用')} {t('· 接到 {where}', { where })}</span>
          {header && <span className="text-[10px] ml-2 px-1 rounded bg-amber-200 text-amber-900">{t('標題旁的大開關')}</span>}
        </button>
        {onMove && <><Button variant="ghost" disabled={first} onClick={() => onMove(-1)}>▲</Button><Button variant="ghost" disabled={last} onClick={() => onMove(1)}>▼</Button></>}
        {onDelete && <Button variant="ghost" onClick={() => { if (confirm(t('刪除「{label}」?', { label: c.label }))) onDelete() }}>✕</Button>}
      </div>
      {open && (
        <div className="px-3 pb-3 flex flex-col gap-2 border-t border-stone-100 pt-2 text-sm">
          <div className="flex flex-wrap gap-2">
            <label className="flex items-center gap-1">{t('名稱')}<input className={`${input} w-48`} value={c.label} onChange={e => onChange(x => { x.label = e.target.value })} /></label>
            <label className="flex items-center gap-1 flex-1 min-w-64">{t('說明')}<input className={`${input} flex-1`} placeholder={t('給使用者看的一句話(可不填)')} value={c.help ?? ''} onChange={e => onChange(x => { x.help = e.target.value || undefined })} /></label>
          </div>
          {b.kind !== 'act_stop' && <div className="flex flex-wrap items-center gap-2">
            <label className="flex items-center gap-1" title={t('在 Discord / Telegram 裡打的名稱;不填 = 用名稱(重複時前面加區塊名稱)')}>{t('聊天名稱')}
              <input className={`${input} w-48`} placeholder={t('(用名稱)')} disabled={!!c.chat_off} value={c.chat ?? ''} onChange={e => onChange(x => { x.chat = e.target.value || undefined })} /></label>
            <label className="flex items-center gap-1 text-xs"><input type="checkbox" checked={!!c.chat_off} onChange={e => onChange(x => { x.chat_off = e.target.checked || undefined })} />{t('只放在頁面,聊天裡不能用')}</label>
          </div>}
          {c.scope === 'device' && sourceIds(info.devices).length > 1 && <div className="flex flex-wrap items-center gap-2"
            title={t('例如溫室的按鈕只放在溫室攝影機那一列;都不勾 = 每一台')}>
            <span className="text-stone-600">{t('只給這幾台')}</span>
            {sourceIds(info.devices).map(n => <label key={n} className="flex items-center gap-1 text-xs">
              <input type="checkbox" checked={(c.devices ?? []).includes(n)} onChange={e => onChange(x => {
                const v = (x.devices ?? []).filter(d => d !== n).concat(e.target.checked ? [n] : [])
                x.devices = v.length ? v : undefined
              })} />{n}</label>)}
            {!c.devices?.length && <span className="text-xs text-stone-500">{t('(每一台)')}</span>}
          </div>}
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-stone-600">{t('接到')}</span>
            <select className={input} value={b.kind} onChange={e => onChange(x => {
              const k = e.target.value
              if (k === 'setting') { x.bind = { kind: k, setting: info.settings[0]?.id }; fromSetting(info.settings[0])(x); return }
              if (k === 'act_sub') { x.bind = { kind: k, sub: info.runnable_subs[0]?.id }; suggest(k)(x); return }
              x.bind = k === 'act_stop' ? { kind: k }
                : k === 'act_situation' ? { kind: k, script: info.scripts[0]?.id, situation: info.scripts[0]?.situations[1]?.id ?? info.scripts[0]?.situations[0]?.id }
                : k === 'entry_arg' ? { kind: k, script: info.entries[0]?.script, situation: info.entries[0]?.situation, param: info.entries[0]?.params[0]?.name }
                : { kind: k, schedule: info.schedules[0]?.id, ...(k === 'schedule' ? { field: 'enabled' } : k === 'schedule_arg' ? { param: info.schedules[0]?.params[0]?.name } : {}) }
              const pm = k === 'entry_arg' ? info.entries[0]?.params[0] : k === 'schedule_arg' ? info.schedules[0]?.params[0] : undefined
              suggest(k, 'enabled', pm)(x)
            })}>
              {Object.entries(info.binds).map(([k, tx]) => <option key={k} value={k}>{tx}</option>)}
            </select>
            {b.kind === 'setting' && <>
              <select className={input} value={String(b.setting ?? '')} onChange={e => onChange(x => { x.bind.setting = e.target.value; fromSetting(info.settings.find(s => s.id === e.target.value))(x) })}>
                {!info.settings.length && <option value="">{t('(先到「素材庫 › 使用者設定」新增)')}</option>}
                {info.settings.map(s => <option key={s.id} value={s.id}>{s.label}</option>)}
              </select>
              <span className="text-xs text-stone-500">{t('種類、每台或共用、可選項目都跟著使用者設定')}</span>
            </>}
            {b.kind === 'act_situation' && <select className={input} value={`${b.script}|${b.situation}`} onChange={e => onChange(x => {
              const [sc, si] = e.target.value.split('|'); x.bind.script = sc; x.bind.situation = si })}>
              {info.scripts.flatMap(sc => sc.situations.map(si => <option key={`${sc.id}|${si.id}`} value={`${sc.id}|${si.id}`}>{sc.name} › {si.name}</option>))}
            </select>}
            {c.type === 'action' && <select className={input} value={c.scope ?? 'device'} onChange={e => onChange(x => { x.scope = e.target.value as 'global' | 'device' })}>
              <option value="device">{t('每台一顆按鈕')}</option><option value="global">{t('一顆按鈕,所有{device}一起', { device: words.device })}</option></select>}
            {b.kind === 'act_sub' && <select className={input} value={String(b.sub ?? '')} onChange={e => onChange(x => { x.bind.sub = e.target.value })}>
              {!info.runnable_subs.length && <option value="">{t('(沒有不需要參數的子腳本)')}</option>}
              {info.runnable_subs.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select>}
            {b.kind !== 'entry_arg' && b.kind !== 'act_situation' && b.kind !== 'act_stop' && b.kind !== 'setting' && b.kind !== 'act_sub' && <select className={input} value={String(b.schedule ?? '')} onChange={e => onChange(x => {
              x.bind.schedule = e.target.value
              if (x.bind.kind === 'schedule_arg') { const s = info.schedules.find(y => y.id === e.target.value); x.bind.param = s?.params[0]?.name; suggest('schedule_arg', undefined, s?.params[0])(x) }
            })}>
              {info.schedules.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select>}
            {b.kind === 'schedule' && <select className={input} value={String(b.field)} onChange={e => onChange(x => { x.bind.field = e.target.value; suggest('schedule', e.target.value)(x) })}>
              <option value="enabled">{t('開關')}</option><option value="at">{t('開始時間')}</option></select>}
            {b.kind === 'entry_arg' && <select className={input} value={`${b.script}|${b.situation}`} onChange={e => onChange(x => {
              const [sc, si] = e.target.value.split('|'); const en = info.entries.find(y => y.script === sc && y.situation === si)
              x.bind.script = sc; x.bind.situation = si; x.bind.param = en?.params[0]?.name; suggest('entry_arg', undefined, en?.params[0])(x)
            })}>
              {info.entries.map(en => <option key={`${en.script}|${en.situation}`} value={`${en.script}|${en.situation}`}>{en.script_name} › {en.situation_name}</option>)}
            </select>}
            {(b.kind === 'schedule_arg' || b.kind === 'entry_arg') && <select className={input} value={String(b.param ?? '')} onChange={e => onChange(x => {
              x.bind.param = e.target.value; suggest(b.kind, undefined, params.find(y => y.name === e.target.value))(x)
            })}>
              {params.map(pm => <option key={pm.name} value={pm.name}>{t('{name}({n})', { name: pm.label, n: PARAM_TYPE[pm.type] ?? pm.type })}</option>)}
            </select>}
            {b.kind === 'schedule_arg' && <label className="flex items-center gap-1">
              <select className={input} value={c.scope ?? 'global'} onChange={e => onChange(x => { x.scope = e.target.value as 'global' | 'device' })}>
                <option value="device">{t('每台各自設定')}</option><option value="global">{t('全部機台共用')}</option></select></label>}
          </div>
          {c.type === 'number' && (
            <div className="flex flex-wrap items-center gap-2">
              <label className="flex items-center gap-1">{t('單位')}<input className={`${input} w-20`} value={c.unit ?? ''} onChange={e => onChange(x => { x.unit = e.target.value })} /></label>
              <label className="flex items-center gap-1" title={t('使用者填的數字 × 這個 = 實際存的值,例如使用者填分鐘、參數要秒,就填 60')}>{t('換算 ×')}<input type="number" className={`${input} w-20`} value={c.scale ?? 1} onChange={e => onChange(x => { x.scale = Number(e.target.value) || 1 })} /></label>
              <label className="flex items-center gap-1">{t('最小')}<input type="number" className={`${input} w-20`} value={c.min ?? ''} onChange={e => onChange(x => { x.min = e.target.value === '' ? undefined : Number(e.target.value) })} /></label>
              <label className="flex items-center gap-1">{t('最大')}<input type="number" className={`${input} w-20`} value={c.max ?? ''} onChange={e => onChange(x => { x.max = e.target.value === '' ? undefined : Number(e.target.value) })} /></label>
            </div>
          )}
          {(c.type === 'single' || c.type === 'multi') && b.kind !== 'setting' && (
            <div className="flex flex-col gap-1">
              <label className="flex items-center gap-2">{t('選項來源')}
                <select className={input} value={typeof c.options === 'string' ? c.options : 'custom'} onChange={e => onChange(x => { x.options = e.target.value === 'custom' ? [] : e.target.value as PanelControl['options'] })}>
                  {info.lists.map(l => <option key={l.id} value={`list:${l.id}`}>{t('清單:{title}', { title: l.title })}{l.per_device ? t('(這台的)') : t('(全部)')}</option>)}
                  <option value="custom">{t('自己列出選項')}</option></select></label>
              {c.type === 'multi' && <label className="flex items-center gap-1">{t('至少選')}<input type="number" className={`${input} w-16`} value={c.min ?? 0} onChange={e => onChange(x => { x.min = Number(e.target.value) || undefined })} />{t('個')}</label>}
              {typeof c.options !== 'string' && (
                <div className="flex flex-col gap-1 pl-3 border-l-2 border-stone-200">
                  {((c.options as { label: string; value: unknown }[]) ?? []).map((o, i) => (
                    <div key={i} className="flex items-center gap-2">
                      <input className={`${input} w-48`} placeholder={t('使用者看到的名稱')} value={o.label} onChange={e => onChange(x => { (x.options as { label: string }[])[i].label = e.target.value })} />
                      <select className={input} value={String((o.value as { button?: string })?.button ?? '')} onChange={e => onChange(x => { (x.options as { value: unknown }[])[i].value = { button: e.target.value } })}>
                        <option value="">{t('(選按鈕庫裡的位置)')}</option>
                        {info.buttons.filter(bt => !info.lists.find(l => l.id === bt.list)?.per_device).map(bt => <option key={bt.id} value={bt.id}>{bt.label}</option>)}
                      </select>
                      <Button variant="ghost" onClick={() => onChange(x => { (x.options as unknown[]).splice(i, 1) })}>✕</Button>
                    </div>
                  ))}
                  <button className="self-start text-xs underline" onClick={() => onChange(x => { x.options = [...((x.options as unknown[]) ?? []), { label: '', value: null }] as never })}>{t('+ 加一個選項')}</button>
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

/** Phones on the LAN: where to open the panel, and the PINs for end users and consultants. */
/** What a paired person can type to the chat bot with this design: the panel, nothing more. */
function ChatPreview({ panel }: { panel: Panel }) {
  const [data, setData] = useState<PanelChatPreview | null>(null)
  const key = JSON.stringify(panel)
  useEffect(() => {
    const tx = setTimeout(() => { api.panelChatPreview(panel).then(setData).catch(() => setData(null)) }, 400)
    return () => clearTimeout(tx)
  }, [key])                                          // eslint-disable-line react-hooks/exhaustive-deps
  const word: Record<string, string> = { toggle: t('開/關'), time: t('時間'), number: t('數字'), single: t('選一個'), multi: t('選幾個'), action: t('按鈕') }
  return (
    <Card title={t('聊天裡可以做的事')} extra={<span className="text-xs text-stone-500">{t('配對過的人在 Discord / Telegram 能做的 = 這個面板開放的,再加上停下來、暫停、繼續這些安全指令')}</span>}>
      {!data ? <Empty>{t('讀取中…')}</Empty> : <div className="flex flex-col gap-2 text-sm">
        <ErrorText error={data.error} />
        <div className="text-xs text-stone-600">{t('一定有:選單 · 狀態 · 畫面 <機台> · 停下來 · 暫停 · 繼續(一台、#標籤或全部)')}
          {data.widgets.length > 0 && <> {t('· 看:{p1}', { p1: data.widgets.join(' · ') })}</>}</div>
        {data.commands.length === 0 ? <Empty>{t('面板上還沒有可以在聊天裡用的設定或按鈕')}</Empty> :
          <div className="grid md:grid-cols-2 gap-x-6 gap-y-0.5">
            {data.commands.map(c => <div key={c.control} className="flex gap-2">
              <code className="text-xs bg-stone-100 rounded px-1">{c.name}{c.scope === 'device' ? t(' [機台]') : ''}</code>
              <span className="text-xs text-stone-500">{word[c.type] ?? c.type}{c.type === 'action' ? t('(會先問確認)') : t('(打名稱看值,加新的值就改,會先問確認)')}</span>
            </div>)}
          </div>}
      </div>}
    </Card>
  )
}

function AccessCard() {
  const qc = useQueryClient()
  const me = useQuery({ queryKey: ['authMe'], queryFn: api.authMe })
  const [userPin, setUserPin] = useState('')
  const [adminPin, setAdminPin] = useState('')
  const save = useMutation({ mutationFn: (b: { user_pin?: string; admin_pin?: string }) => api.authPins(b),
    onSuccess: () => { setUserPin(''); setAdminPin(''); qc.invalidateQueries({ queryKey: ['authMe'] }) } })
  const c = me.data?.configured
  return (
    <Card title={t('手機連線與登入')}>
      <div className="flex flex-col gap-2 text-sm">
        <div>{me.data?.lan
          ? <>{t('同一個網路的手機打開')} <b className="select-all">{me.data.lan}</b>{t(',輸入使用者 PIN 碼就能用操作面板。')}</>
          : <>{t('目前只有這台電腦能用。要讓手機也能連,請用')} <code className="bg-stone-100 px-1 rounded">python -m server --lan</code> {t('啟動介面(先設定下面的 PIN 碼)。')}</>}</div>
        <div className="text-xs text-stone-500">{t('這台電腦本身不用登入。從其他裝置連進來:使用者 PIN 只能進操作面板;顧問 PIN 可以進全部的管理介面。')}</div>
        <div className="flex flex-wrap items-center gap-3">
          <label className="flex items-center gap-1">{t('使用者 PIN')} <input className={`${input} w-28`} inputMode="numeric" placeholder={c?.user ? t('已設定(改才填)') : t('4~8 位數字')} value={userPin} onChange={e => setUserPin(e.target.value)} /></label>
          <label className="flex items-center gap-1">{t('顧問 PIN')} <input className={`${input} w-28`} inputMode="numeric" placeholder={c?.admin ? t('已設定(改才填)') : t('4~8 位數字')} value={adminPin} onChange={e => setAdminPin(e.target.value)} /></label>
          <Button disabled={(!userPin && !adminPin) || save.isPending} onClick={() => save.mutate({ ...(userPin ? { user_pin: userPin } : {}), ...(adminPin ? { admin_pin: adminPin } : {}) })}>{t('設定 PIN 碼')}</Button>
          {c?.user && <Button variant="ghost" onClick={() => { if (confirm(t('關閉使用者從手機登入?'))) save.mutate({ user_pin: '' }) }}>{t('關閉使用者登入')}</Button>}
          {c?.admin && <Button variant="ghost" onClick={() => { if (confirm(t('關閉顧問從其他裝置登入?'))) save.mutate({ admin_pin: '' }) }}>{t('關閉顧問登入')}</Button>}
        </div>
        <ErrorText error={save.error} />
      </div>
    </Card>
  )
}
