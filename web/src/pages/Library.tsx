import { t } from '../i18n'
import { PageIntro } from '../components/PageIntro'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, buttonImageUrl, type LibButton, type OutputDef, type ScriptsInfo } from '../api'
import { Button, Card, Empty, ErrorText, Page } from '../components/ui'
import { usePersistentState } from '../lib/persist'
import { ButtonsEditor, VarsEditor, perDeviceItem } from './Scripts'
import { SettingsEditor } from './UserSettings'
import { ShareSubs } from './ShareSubs'
import { dn, sourceIds } from '../lib/sources'

type LibTab = 'buttons' | 'lists' | 'vars' | 'settings' | 'outputs' | 'share' | 'templates'
const KIND_NAME: Record<string, string> = { script: t('主腳本'), guard_rules: t('守門規則'), sub: t('子腳本') }

/** The parts every script shares: named buttons, variables and ready-made templates. */
export default function Library() {
  const qc = useQueryClient()
  const navigate = useNavigate()
  const q = useQuery({ queryKey: ['scripts'], queryFn: api.scripts })
  const shadow = useQuery({ queryKey: ['shadow'], queryFn: api.shadowStatus })
  const devices = sourceIds((shadow.data?.status.devices ?? []).map(d => d.name))
  const [tab, setTab] = usePersistentState<LibTab>('library.tab', 'buttons')
  const info = q.data
  const saved = () => qc.invalidateQueries({ queryKey: ['scripts'] })
  const tabs: [LibTab, string][] = [
    ['buttons', t('按鈕({p1})', { p1: info ? info.buttons.filter(b => !perDeviceItem(info, b) && !b.list).length : 0 })],
    ['lists', t('清單({p1})', { p1: info?.lists.length ?? 0 })], ['vars', t('變數({p1})', { p1: info?.variables.length ?? 0 })], ['settings', t('使用者設定({p1})', { p1: info?.settings.length ?? 0 })], ['outputs', t('輸出({p1})', { p1: info?.outputs.length ?? 0 })], ['share', t('分享子腳本')], ['templates', t('範本({p1})', { p1: info?.templates.length ?? 0 })]]
  return (
    <Page title={t('素材庫')} intro={<PageIntro id="library" what={t('腳本動手時用的零件:畫面上的按鈕位置、控制設備的輸出、計數用的變數。')} start={t('要點畫面就新增「按鈕」;要控制設備(網址、MQTT…)就新增「輸出」,存好後按「測試」。')} ch={6} />} desc={t('腳本共用的零件。按鈕:取好名字的點擊位置(可以找圖示再點);變數:計數器、上次時間;範本:做好的腳本,改一改就能用。')}>
      <ErrorText error={q.error} />
      <div className="flex border-b border-stone-200 gap-1">
        {tabs.map(([k, tx]) => (
          <button key={k} onClick={() => setTab(k)}
            className={`px-4 py-2 text-sm -mb-px border-b-2 ${tab === k ? 'border-stone-900 text-stone-900 font-medium' : 'border-transparent text-stone-500 hover:text-stone-800'}`}>{tx}</button>
        ))}
      </div>
      {!info ? <Card><Empty>{q.isLoading ? t('讀取中…') : t('讀取失敗')}</Empty></Card>
        : tab === 'buttons' ? <ButtonsEditor info={info} devices={devices} onSaved={saved} />
        : tab === 'lists' ? <Lists info={info} devices={devices} running={!!shadow.data?.status.running} onSaved={saved} />
        : tab === 'vars' ? <VarsEditor key={JSON.stringify(info.variables)} info={info} onSaved={saved} />
        : tab === 'settings' ? <SettingsEditor />
        : tab === 'outputs' ? <OutputsEditor onSaved={saved} />
        : tab === 'share' ? <ShareSubs info={info} />
        : (
          <div className="flex flex-col gap-5">
            {(['guard_rules', 'script', 'sub'] as const).map(k => (
              <div key={k} className="flex flex-col gap-2">
                <div className="text-sm font-medium text-stone-700">{KIND_NAME[k]}{k === 'guard_rules' && <span className="text-xs text-stone-500 font-normal">{t('(加到全域守門規則)')}</span>}</div>
                <div className="grid md:grid-cols-2 xl:grid-cols-3 gap-3">
                  {info.templates.filter(tx => tx.kind === k).map(tx => (
                    <div key={tx.id} className="bg-white border border-stone-200 rounded-lg p-4 flex flex-col gap-2">
                      <div className="font-medium">{tx.name}</div>
                      <div className="text-xs text-stone-600 flex-1">{tx.description}</div>
                      <div><Button onClick={() => navigate(`/scripts?template=${encodeURIComponent(tx.id)}`)}>{t('用這個範本建立 →')}</Button></div>
                    </div>
                  ))}
                </div>
              </div>
            ))}
            <p className="text-xs text-stone-500">{t('建立後會在「腳本」打開一份未儲存的草稿,改好再儲存。')}</p>
          </div>
        )}
    </Page>
  )
}

/** Lists (清單): names on a scrolling list of the screen (accounts or places, a camera list ...),
 * captured here and named, then picked in parameters, user settings and the panel. A per-device list differs per device. */
function Lists({ info, devices, running, onSaved }: { info: ScriptsInfo; devices: string[]; running: boolean; onSaved: () => void }) {
  const [lid, setLid] = usePersistentState('library.list', info.lists[0]?.id ?? '')
  const list = info.lists.find(l => l.id === lid) ?? info.lists[0]
  const items = info.buttons.filter(b => list && b.list === list.id)
  const devs = [...new Set([...devices, ...items.map(b => b.device ?? '')])].filter(Boolean).sort()
  const [dev, setDev] = usePersistentState('library.listDevice', devs[0] ?? '')
  const cur = devs.includes(dev) ? dev : devs[0] ?? ''
  const mine = list?.per_device ? items.filter(b => b.device === cur) : items
  const openSub = info.subs.find(s => s.id === list?.open_sub)
  const open = useMutation({ mutationFn: () => api.runSub({ device: cur, sub: list!.open_sub!, args: {} }) })
  const capture = useMutation({ mutationFn: () => api.listCapture(list!.id, cur), onSuccess: onSaved })
  if (!list) return <Card><Empty>{t('這個專案還沒有清單')}</Empty></Card>
  return (
    <div className="flex flex-col gap-4">
      <Card title={t('擷取清單')} extra={<span className="flex gap-2">
        <select className="border border-stone-300 rounded-md px-2 py-1 text-sm" value={list.id} onChange={e => setLid(e.target.value)}>
          {info.lists.map(l => <option key={l.id} value={l.id}>{l.title}{l.per_device ? t('(每台各自)') : ''}</option>)}</select>
        <select className="border border-stone-300 rounded-md px-2 py-1 text-sm" value={cur} onChange={e => setDev(e.target.value)}>
          {devs.map(d => <option key={d} value={d}>{dn(d)}</option>)}</select></span>}>
        <div className="flex flex-col gap-2 text-sm">
          <p className="text-stone-600">{t('讓 {cur} 停在這個清單的畫面{p2},按「擷取」:會自動捲過整個清單,把每一項的名字截下來(已經有的會略過)。擷取後替新的項目取名字,參數、使用者設定、操作面板就能選它們。', { cur, p2: list.ready_text ? t('({n})', { n: list.ready_text }) : '' })} {list.per_device ? t('這份清單每台不一樣,每台各自擷取。') : t('這份清單每台都一樣,擷取一次就好。')}</p>
          <div className="flex flex-wrap gap-2 items-center">
            {openSub && <Button onClick={() => { if (confirm(t('在 {cur} 執行「{name}」,把清單帶到畫面上?', { cur, name: openSub.name }))) open.mutate() }}
              disabled={!running || open.isPending}>① {openSub.name}</Button>}
            <Button variant="primary" onClick={() => { if (confirm(t('擷取 {cur} 的「{title}」?(會捲動清單)', { cur, title: list.title }))) capture.mutate() }}
              disabled={!running || capture.isPending}>{capture.isPending ? t('擷取中…') : t('{p1}擷取', { p1: openSub ? '② ' : '' })}</Button>
            {!running && <span className="text-xs text-amber-800">{t('要先到「執行」開始執行')}</span>}
            {open.isSuccess && <span className="text-xs text-emerald-700">{t('已送出,畫面到清單後再按「擷取」')}</span>}
            {capture.data && <span className="text-xs text-emerald-700">{t('新增 {length} 個,已經有的 {length2} 個', { length: capture.data.new.length, length2: capture.data.known.length })}</span>}
          </div>
          <ErrorText error={open.error || capture.error} />
        </div>
      </Card>
      <Card title={list.per_device ? t('{cur} 的{title}({n})', { cur, title: list.title, n: mine.length }) : t('{name}({n})', { name: list.title, n: mine.length })}>
        {!mine.length ? <Empty>{t('還沒有項目')}</Empty> : (
          <div className="grid md:grid-cols-2 xl:grid-cols-3 gap-2">
            {mine.map(b => <ItemRow key={b.id} b={b} onSaved={onSaved} />)}
          </div>
        )}
      </Card>
    </div>
  )
}

function ItemRow({ b, onSaved }: { b: LibButton; onSaved: () => void }) {
  const [label, setLabel] = useState(b.label)
  const save = useMutation({ mutationFn: () => api.buttonSave({ ...b, label }, {}), onSuccess: onSaved })
  const del = useMutation({ mutationFn: () => api.buttonDelete(b.id), onSuccess: onSaved })
  return (
    <div className="flex items-center gap-2 bg-white border border-stone-200 rounded-md px-2 py-1.5">
      <img src={buttonImageUrl(b.id, b.updated)} alt="" className="h-8 rounded bg-stone-800" />
      <input className="border border-stone-300 rounded px-2 py-1 text-sm w-32" value={label} onChange={e => setLabel(e.target.value)} />
      {label !== b.label && <Button onClick={() => save.mutate()} disabled={save.isPending || !label}>{t('儲存')}</Button>}
      <span className="flex-1" />
      <Button variant="ghost" onClick={() => { if (confirm(t('刪除「{label}」?', { label: b.label }))) del.mutate() }}>{t('刪除')}</Button>
      <ErrorText error={save.error || del.error} />
    </div>
  )
}

/** 輸出: where scripts send things besides the screen - a web hook, a home-automation server, a relay. */
function OutputsEditor({ onSaved }: { onSaved: () => void }) {
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['outputs'], queryFn: api.outputs })
  const [draft, setDraft] = useState<OutputDef[] | null>(null)
  const list = draft ?? q.data?.outputs ?? []
  const save = useMutation({ mutationFn: () => api.outputsSave(list), onSuccess: d => { qc.setQueryData(['outputs'], d); setDraft(null); onSaved() } })
  const test = useMutation({ mutationFn: (id: string) => api.outputTest(id) })
  const set = (i: number, p: Partial<OutputDef>) => setDraft(list.map((o, k) => k === i ? { ...o, ...p } : o))
  const inp = 'border border-stone-300 rounded-md px-2 py-1 text-sm bg-white'
  return (
    <Card title={t('輸出')} extra={<div className="flex gap-2">
      <Button onClick={() => setDraft([...list, { id: `out_${list.length + 1}`, name: t('新的輸出'), type: 'http', url: 'https://', method: 'POST' }])}>{t('+ 新增輸出')}</Button>
      {draft && <Button variant="primary" disabled={save.isPending} onClick={() => save.mutate()}>{t('儲存')}</Button>}</div>}>
      <div className="flex flex-col gap-3 text-sm">
        <p className="text-xs text-stone-500">{t('腳本的「送到輸出」會把一則訊息送到這裡:{p1}"device", "script", "command", "value", "time"{p2}。 網址輸出用 POST 時送 JSON,用 GET 時放在網址參數;可以接 Home Assistant、Node-RED、IFTTT 這類 Webhook。試跑和重播都不會真的送出。', { p1: '{', p2: '}' })}</p>
        <ErrorText error={q.error || save.error || test.error} />
        {test.isSuccess && <div className="text-xs text-emerald-700">{t('測試訊息已送出(回應 {status})', { status: test.data.status })}</div>}
        {!list.length && <Empty>{t('還沒有輸出')}</Empty>}
        {list.map((o, i) => (
          <div key={i} className="border border-stone-200 rounded-md p-3 flex flex-wrap gap-2 items-center">
            <input className={`${inp} w-32`} value={o.name} onChange={e => set(i, { name: e.target.value })} placeholder={t('名稱')} />
            <input className={`${inp} w-28 font-mono`} value={o.id} onChange={e => set(i, { id: e.target.value })} placeholder={t('代號')} title={t('腳本用代號找到它,存了之後不要再改')} />
            <select className={inp} value={o.type} onChange={e => set(i, { type: e.target.value })}>
              {Object.entries(q.data?.types ?? { http: { label: t('網址'), fields: {} } }).map(([k, tx]) => <option key={k} value={k}>{tx.label}</option>)}
            </select>
            {o.type === 'http' && <>
              <input className={`${inp} flex-1 min-w-[240px] font-mono`} value={String(o.url ?? '')} onChange={e => set(i, { url: e.target.value })} placeholder="https://..." />
              <select className={inp} value={String(o.method ?? 'POST')} onChange={e => set(i, { method: e.target.value })}><option>POST</option><option>GET</option></select>
            </>}
            <span className="ml-auto flex gap-2">
              <Button variant="ghost" disabled={!!draft || test.isPending} title={draft ? t('先儲存') : t('送一則測試訊息')} onClick={() => test.mutate(o.id)}>{t('測試')}</Button>
              <Button variant="ghost" onClick={() => setDraft(list.filter((_, k) => k !== i))}>{t('刪除')}</Button>
            </span>
          </div>
        ))}
      </div>
    </Card>
  )
}
