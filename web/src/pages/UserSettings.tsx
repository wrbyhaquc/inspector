import { t } from '../i18n'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api, type Choice, type SettingDecl, type SettingsInfo } from '../api'
import { Button, Card, Empty, ErrorText } from '../components/ui'
import { dn } from '../lib/sources'

const clone = <T,>(v: T): T => JSON.parse(JSON.stringify(v))
const input = 'border border-stone-300 rounded-md px-2 py-1 text-sm bg-white'
const key = (v: unknown) => JSON.stringify(v)

/** What a user setting's value looks like in one line. */
export function settingText(s: SettingDecl, v: unknown, choices?: Choice[] | null): string {
  if (v === undefined || v === null) return t('(沒有值)')
  const name = (x: unknown) => choices?.find(c => key(c.value) === key(x))?.label ?? (typeof x === 'object' ? JSON.stringify(x) : String(x))
  if (s.type === 'bool') return v ? t('開') : t('關')
  if (s.type === 'list') return Array.isArray(v) ? (v.length ? v.map(name).join(t('、')) : t('(一個都沒選)')) : String(v)
  if (s.type === 'point') return name(v)
  return String(v)
}

/** Edit one value of a setting (a default, or what is chosen for one emulator). */
export function SettingValueInput({ s, value, choices, onChange }: {
  s: SettingDecl; value: unknown; choices: Choice[] | null | undefined; onChange: (v: unknown) => void
}) {
  if (s.type === 'bool') return <label className="flex items-center gap-1 text-sm"><input type="checkbox" checked={!!value} onChange={e => onChange(e.target.checked)} />{t('開')}</label>
  if (s.type === 'number') return <input type="number" className={`${input} w-28 num`} value={value == null ? '' : String(value)} min={s.min} max={s.max}
    onChange={e => onChange(e.target.value === '' ? null : Number(e.target.value))} />
  if (s.type === 'time') return <input type="time" className={input} value={String(value ?? '')} onChange={e => onChange(e.target.value)} />
  if (s.type === 'text') return <input className={`${input} w-56`} value={String(value ?? '')} onChange={e => onChange(e.target.value)} />
  if (!choices) return <span className="text-xs text-stone-500">{choices === null ? t('沒有可選的項目') : t('讀取中…')}</span>
  if (s.type === 'point') return (
    <select className={input} value={value == null ? '' : key(value)} onChange={e => onChange(e.target.value ? JSON.parse(e.target.value) : null)}>
      <option value="">{t('(未選)')}</option>
      {choices.map(c => <option key={key(c.value)} value={key(c.value)}>{c.label}</option>)}
    </select>
  )
  // a list of choices: ticked in order (the order matters, e.g. which item goes first)
  const chosen = Array.isArray(value) ? value.map(key) : []
  const set = (ks: string[]) => onChange(ks.map(k => JSON.parse(k)))
  const label = (k: string) => choices.find(c => key(c.value) === k)?.label ?? t('(已不存在)')
  return (
    <div className="flex flex-col gap-1.5">
      {chosen.length > 0 && <div className="flex flex-wrap gap-1 items-center">
        {chosen.map((k, i) => (
          <span key={k} className="text-xs px-1.5 py-0.5 rounded bg-emerald-100 text-emerald-900 flex items-center gap-1">
            <span className="num">{i + 1}.</span>{label(k)}
            <button disabled={i === 0} className="disabled:opacity-30" onClick={() => { const n = [...chosen]; [n[i - 1], n[i]] = [n[i], n[i - 1]]; set(n) }}>◀</button>
            <button disabled={i === chosen.length - 1} className="disabled:opacity-30" onClick={() => { const n = [...chosen]; [n[i + 1], n[i]] = [n[i], n[i + 1]]; set(n) }}>▶</button>
          </span>
        ))}
      </div>}
      <div className="flex flex-wrap gap-1.5">
        {choices.map(c => {
          const k = key(c.value)
          return (
            <label key={k} className="flex items-center gap-1 text-xs border border-stone-200 rounded px-1.5 py-0.5 bg-white">
              <input type="checkbox" checked={chosen.includes(k)} onChange={e => set(e.target.checked ? [...chosen, k] : chosen.filter(x => x !== k))} />{c.label}
            </label>
          )
        })}
      </div>
    </div>
  )
}

/** The parameters this design opens to the people who run it (素材庫 › 使用者設定). */
export function SettingsEditor() {
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['settings'], queryFn: api.settings })
  const [draft, setDraft] = useState<SettingDecl[] | null>(null)
  const [open, setOpen] = useState<string | null>(null)
  const info = q.data
  const list = draft ?? info?.settings ?? []
  const dirty = !!draft && key(draft) !== key(info?.settings)
  const save = useMutation({
    mutationFn: () => api.settingsSave(list),
    onSuccess: () => { setDraft(null); qc.invalidateQueries({ queryKey: ['settings'] }); qc.invalidateQueries({ queryKey: ['scripts'] }) },
  })
  const edit = (i: number, fn: (s: SettingDecl) => void) => setDraft(() => { const n = clone(list); fn(n[i]); return n })
  const add = () => {
    const taken = list.map(s => s.id)
    let k = 1
    while (taken.includes(`setting${k}`)) k++
    const s: SettingDecl = { id: `setting${k}`, label: t('新的設定'), type: 'number', scope: 'shared', default: 0 }
    setDraft([...list, s]); setOpen(s.id)
  }
  if (!info) return <Card><Empty>{q.isLoading ? t('讀取中…') : t('讀取失敗')}</Empty></Card>
  return (
    <div className="flex flex-col gap-3">
      <Card title={t('使用者設定')} extra={<span className="text-xs text-stone-500">{t('開放給使用者的參數:這裡宣告,值由使用者在操作面板上選')}</span>}>
        <div className="text-sm text-stone-600 flex flex-col gap-1">
          <p>{t('排程、主腳本、子腳本的參數可以選「用使用者設定」,執行開始時才讀當下的值;操作面板的控制項接到使用者設定,使用者就能自己改。')}</p>
          <p className="text-xs text-stone-500">{t('預設值是設計的一部分;使用者選的值另外存在執行端,改設計不會蓋掉它們。')}</p>
        </div>
      </Card>
      {list.map((s, i) => (
        <SettingCard key={s.id + i} s={s} info={info} isNew={!info.settings.some(x => x.id === s.id)} open={open === s.id}
          onToggle={() => setOpen(o => o === s.id ? null : s.id)} onChange={fn => edit(i, fn)}
          onDelete={() => { if (confirm(t('刪除「{label}」?', { label: s.label }))) setDraft(list.filter((_, k) => k !== i)) }} />
      ))}
      <div className="flex flex-wrap items-center gap-3">
        <Button onClick={add}>{t('+ 新增使用者設定')}</Button>
        {dirty && <>
          <Button variant="primary" disabled={save.isPending} onClick={() => save.mutate()}>{save.isPending ? t('儲存中…') : t('儲存')}</Button>
          <Button variant="ghost" onClick={() => setDraft(null)}>{t('放棄修改')}</Button>
        </>}
        <ErrorText error={save.error} />
      </div>
    </div>
  )
}

function SettingCard({ s, info, isNew, open, onToggle, onChange, onDelete }: {
  s: SettingDecl; info: SettingsInfo; isNew: boolean; open: boolean; onToggle: () => void
  onChange: (fn: (s: SettingDecl) => void) => void; onDelete: () => void
}) {
  const used = info.used_by[s.id] ?? []
  const devices = info.devices
  // the choices of a source that is not saved yet come from the server; saved ones come with the settings
  const fresh = useQuery({
    queryKey: ['settingChoices', s.pick_from, s.scope === 'device' ? devices : '*'],
    enabled: !!s.pick_from && (isNew || info.settings.find(x => x.id === s.id)?.pick_from !== s.pick_from),
    queryFn: async () => Object.fromEntries(await Promise.all((s.scope === 'device' ? devices : ['*']).map(async d =>
      [d, (await api.settingChoices(s.pick_from!, d === '*' ? undefined : d)).choices] as const))),
  })
  const choicesFor = (d: string) => s.pick_from ? (fresh.data?.[d] ?? info.choices[s.id]?.[d]) : null
  const anyChoices = s.scope === 'device' ? choicesFor(devices[0] ?? '') : choicesFor('*')
  const summary = s.scope === 'device'
    ? devices.map(d => `${dn(d)}:${settingText(s, info.current[s.id]?.[d], choicesFor(d))}`).join(' · ')
    : settingText(s, info.current[s.id]?.['*'], choicesFor('*'))
  const chosen = info.chosen[s.id] ?? []
  const reset = useMutation({ mutationFn: (d: string | null) => api.settingValue(s.id, d, null) })
  const qc = useQueryClient()
  return (
    <div className={`bg-white border rounded-lg ${open ? 'border-stone-400' : 'border-stone-200'}`}>
      <button className="w-full text-left px-3 py-2 flex flex-col gap-0.5" onClick={onToggle}>
        <span className="flex items-center gap-2"><span className="font-medium text-sm">{s.label}</span>
          <span className="text-xs text-stone-500">{info.types[s.type]}{s.type === 'list' ? t('(每一項:{p1})', { p1: info.items[s.item ?? 'point'] }) : ''} · {info.scopes[s.scope]}</span>
          {isNew && <span className="text-[10px] px-1 rounded bg-amber-200 text-amber-900">{t('未儲存')}</span>}</span>
        <span className="text-xs text-stone-600 truncate" title={summary}>{t('目前:{summary}', { summary })}</span>
        <span className="text-xs text-stone-400">{used.length ? t('用在:{p1}', { p1: used.join(t('、')) }) : t('還沒有地方使用')}{chosen.length ? ' · ' + t('使用者改過:{who}', { who: chosen.map(d => d === '*' ? t('共用值') : d).join(t('、')) }) : ''}</span>
      </button>
      {open && (
        <div className="px-3 pb-3 pt-2 border-t border-stone-100 flex flex-col gap-3 text-sm">
          <div className="grid md:grid-cols-2 gap-2">
            <label className="flex items-center gap-2"><span className="w-16 text-stone-600">{t('名稱')}</span>
              <input className={`${input} flex-1`} value={s.label} onChange={e => onChange(x => { x.label = e.target.value })} /></label>
            <label className="flex items-center gap-2"><span className="w-16 text-stone-600">{t('代號')}</span>
              <input className={`${input} flex-1 font-mono`} value={s.id} disabled={!isNew} onChange={e => onChange(x => { x.id = e.target.value })} /></label>
            <label className="flex items-center gap-2 md:col-span-2"><span className="w-16 text-stone-600">{t('說明')}</span>
              <input className={`${input} flex-1`} placeholder={t('給使用者看的一句話(可不填)')} value={s.description ?? ''} onChange={e => onChange(x => { x.description = e.target.value || undefined })} /></label>
            <label className="flex items-center gap-2"><span className="w-16 text-stone-600">{t('種類')}</span>
              <select className={input} value={s.type} disabled={used.length > 0} title={used.length ? t('已經有地方在用,不能改種類') : undefined} onChange={e => onChange(x => {
                x.type = e.target.value as SettingDecl['type']; delete x.default; x.device_default = {}
                delete x.min; delete x.max; delete x.min_items; delete x.max_items; delete x.pick_from
                if (x.type === 'list') x.item = 'point'; else delete x.item
                if ((x.type === 'point' || x.type === 'list') && info.lists[0]) { x.pick_from = `list:${info.lists[0].id}`; if (info.lists[0].per_device) x.scope = 'device' }
              })}>{Object.entries(info.types).map(([k, tx]) => <option key={k} value={k}>{tx}</option>)}</select></label>
            <label className="flex items-center gap-2"><span className="w-16 text-stone-600">{t('範圍')}</span>
              <select className={input} value={s.scope} onChange={e => onChange(x => { x.scope = e.target.value as SettingDecl['scope'] })}>
                {Object.entries(info.scopes).map(([k, tx]) => <option key={k} value={k} disabled={k === 'shared' && !!info.lists.find(l => `list:${l.id}` === s.pick_from)?.per_device}>{tx}</option>)}
              </select></label>
            {(s.type === 'point' || (s.type === 'list' && (s.item ?? 'point') === 'point')) && (
              <label className="flex items-center gap-2 md:col-span-2"><span className="w-16 text-stone-600">{t('從哪裡選')}</span>
                <select className={input} value={s.pick_from ?? ''} onChange={e => onChange(x => {
                  x.pick_from = e.target.value; delete x.default; x.device_default = {}
                  if (info.lists.find(l => `list:${l.id}` === x.pick_from)?.per_device) x.scope = 'device'
                })}>
                  {info.lists.map(l => <option key={l.id} value={`list:${l.id}`}>{t('清單:{title}', { title: l.title })}{l.per_device ? t('(每台各自)') : ''}</option>)}
                </select></label>
            )}
            {s.type === 'list' && (
              <label className="flex items-center gap-2"><span className="w-16 text-stone-600">{t('每一項')}</span>
                <select className={input} value={s.item ?? 'point'} disabled={used.length > 0} onChange={e => onChange(x => {
                  x.item = e.target.value as SettingDecl['item']; delete x.default; x.device_default = {}
                  if (x.item === 'point') x.pick_from = x.pick_from ?? (info.lists[0] ? `list:${info.lists[0].id}` : undefined); else delete x.pick_from
                })}>{Object.entries(info.items).map(([k, tx]) => <option key={k} value={k}>{tx}</option>)}</select></label>
            )}
            {s.type === 'number' && <div className="flex items-center gap-2 md:col-span-2">
              <span className="w-16 text-stone-600">{t('範圍')}</span>
              <input type="number" className={`${input} w-24`} placeholder={t('最小')} value={s.min ?? ''} onChange={e => onChange(x => { x.min = e.target.value === '' ? undefined : Number(e.target.value) })} />~
              <input type="number" className={`${input} w-24`} placeholder={t('最大')} value={s.max ?? ''} onChange={e => onChange(x => { x.max = e.target.value === '' ? undefined : Number(e.target.value) })} />
            </div>}
            {s.type === 'list' && <div className="flex items-center gap-2 md:col-span-2">
              <span className="w-16 text-stone-600">{t('要選')}</span>
              <input type="number" min={0} className={`${input} w-20`} placeholder={t('至少')} value={s.min_items ?? ''} onChange={e => onChange(x => { x.min_items = e.target.value === '' ? undefined : Number(e.target.value) })} />~
              <input type="number" min={0} className={`${input} w-20`} placeholder={t('最多')} value={s.max_items ?? ''} onChange={e => onChange(x => { x.max_items = e.target.value === '' ? undefined : Number(e.target.value) })} />{t('個')}
            </div>}
          </div>

          <div className="flex flex-col gap-2 border-t border-stone-100 pt-2">
            <div className="text-xs font-semibold text-stone-600">{t('預設值(使用者還沒改時用這個)')}</div>
            {s.scope === 'shared' || !devices.length
              ? <SettingValueInput s={s} value={s.default} choices={anyChoices} onChange={v => onChange(x => { if (v == null) delete x.default; else x.default = v })} />
              : devices.map(d => (
                <div key={d} className="flex flex-wrap items-start gap-2">
                  <span className="text-xs text-stone-600 w-28 pt-1">{d}</span>
                  <div className="flex-1 min-w-0"><SettingValueInput s={s} value={s.device_default?.[d] ?? s.default} choices={choicesFor(d)}
                    onChange={v => onChange(x => { x.device_default = { ...(x.device_default ?? {}) }; if (v == null) delete x.device_default[d]; else x.device_default[d] = v })} /></div>
                </div>
              ))}
          </div>

          {chosen.length > 0 && <div className="flex flex-wrap items-center gap-2 border-t border-stone-100 pt-2 text-xs">
            <span className="text-stone-600">{t('使用者改過的值:')}</span>
            {chosen.map(d => (
              <Button key={d} variant="ghost" disabled={reset.isPending} onClick={() => reset.mutate(d === '*' ? null : d, { onSuccess: () => qc.invalidateQueries({ queryKey: ['settings'] }) })}>
                {d === '*' ? t('共用值') : d} {t('改回預設')}</Button>
            ))}
            <ErrorText error={reset.error} />
          </div>}

          <div className="flex justify-end">
            <Button variant="ghost" disabled={used.length > 0} onClick={onDelete} title={used.length ? t('還有地方在用,先把那邊改掉') : undefined}>{t('刪除這個設定')}</Button>
          </div>
        </div>
      )}
    </div>
  )
}
