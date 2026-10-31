import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { t } from '../../i18n'
import { wbApi, type LibButton, type ScriptsInfo, type StateDef, type WbDraft } from '../../api'
import { screen } from '../../lib/project'
import { Button, Card, Empty, ErrorText } from '../ui'

const input = 'border border-stone-300 rounded-md px-2 py-1 text-sm bg-white'
const KINDS: [string, string, string][] = [
  ['template', t('圖片比對'), t('這個東西出現了沒(圖示、文字、畫面的一部分)')],
  ['color', t('顏色'), t('這塊的顏色有沒有變(亮燈、紅字)')],
  ['bar', t('長條比例'), t('血條、進度條,看填滿了多少')],
  ['digits', t('讀數字'), t('畫面上的數字;套用後到「要看的狀態」教它認字')],
]

export const newButtonId = (name: string, taken: Set<string>) => {
  const slug = name.toLowerCase().replace(/[^a-z0-9_]+/g, '_').replace(/^_+|_+$/g, '')
  const base = /^[a-z]/.test(slug) ? slug : 'button'
  if (base !== 'button' && !taken.has(base)) return base
  let n = 1
  while (taken.has(`${base}_${n}`)) n++
  return `${base}_${n}`
}

/** a find button's picture around a point */
export const boxAround = (x: number, y: number, w = 64, h = 48): number[] => {
  const bx = Math.max(0, Math.min(screen.w - w, x - (w >> 1)))
  const by = Math.max(0, Math.min(screen.h - h, y - (h >> 1)))
  return [bx, by, w, h]
}

/** What is at the marked spot already (use it, or move it here) and what can be made from it. */
export function HerePanel({ device, frame, sel, doc, info, states, onSave, onToDraft }: {
  device: string; frame: string | null; sel: number[] | null; doc?: WbDraft; info?: ScriptsInfo; states: StateDef[]
  onSave: (d: WbDraft) => Promise<void>; onToDraft: () => void
}) {
  const qc = useQueryClient()
  const key = sel && frame ? sel.join(',') : ''
  const at = useQuery({ queryKey: ['wbAt', device, frame, key], queryFn: () => wbApi.at(device, frame!, sel!), enabled: !!sel && !!frame })
  const [name, setName] = useState('')
  const [find, setFind] = useState(true)
  const [stateName, setStateName] = useState('')
  const [dup, setDup] = useState(false)
  const [msg, setMsg] = useState('')
  const boxed = !!sel && sel[2] >= 4 && sel[3] >= 4
  const center = sel ? [sel[0] + (sel[2] >> 1), sel[1] + (sel[3] >> 1)] : [0, 0]
  const buttonsNow = info?.buttons ?? []
  const addButton = useMutation({
    mutationFn: async () => {
      const taken = new Set([...buttonsNow.map(b => b.id), ...(doc?.buttons ?? []).map(b => b.button.id)])
      const b: LibButton = { id: newButtonId(name, taken), label: name.trim(), x: center[0], y: center[1], find }
      let kept: string | undefined
      if (find) {
        b.box = boxed && sel![2] >= 8 && sel![3] >= 8 ? sel! : boxAround(center[0], center[1])
        b.search = 60; b.min_score = 0.8
        kept = (await wbApi.keep(device, frame!)).frame
      }
      await onSave({ ...doc!, buttons: [...doc!.buttons, { button: b, frame: kept }] })
    },
    onSuccess: () => { setName(''); setDup(false); setMsg(t('已放進草稿')); },
  })
  const addState = useMutation({
    mutationFn: (kind: string) => wbApi.newState({ device, frame: frame!, box: sel!, name: stateName, kind }),
    onSuccess: () => { setStateName(''); setMsg(t('已放進草稿,畫面上虛線的就是它')); qc.invalidateQueries({ queryKey: ['wbDraft'] }) },
  })
  const moveButton = useMutation({
    mutationFn: async (id: string) => {
      const b = buttonsNow.find(x => x.id === id)
      if (!b) return
      const moved: LibButton = { ...b, x: center[0], y: center[1] }
      let kept: string | undefined
      if (b.find) {
        moved.box = boxed && sel![2] >= 8 && sel![3] >= 8 ? sel! : boxAround(center[0], center[1], b.box?.[2] ?? 64, b.box?.[3] ?? 48)
        kept = (await wbApi.keep(device, frame!)).frame
      }
      await onSave({ ...doc!, buttons: [...doc!.buttons.filter(x => x.button.id !== id), { button: moved, frame: kept }] })
    },
    onSuccess: () => setMsg(t('已放進草稿,套用後用到它的地方都會跟著改')),
  })
  const moveRoi = useMutation({
    mutationFn: async (r: { state: string; roi: string }) => {
      const s = states.find(x => x.id === r.state)
      if (!s) return
      const edited: StateDef = { ...s, rois: s.rois.map(x => (x.id === r.roi ? { ...x, box: sel as [number, number, number, number] } : x)) }
      await onSave({ ...doc!, states: [...doc!.states.filter(x => x.id !== s.id), edited] })
    },
    onSuccess: () => setMsg(t('已放進草稿,看看它在這張上現在怎麼判斷')),
  })
  const addRef = useMutation({
    mutationFn: async (r: { state: string; value: unknown }) => {
      const kept = (await wbApi.keep(device, frame!)).frame
      await onSave({ ...doc!, refs: [...doc!.refs, { state: r.state, value: r.value as never, frame: kept, box: sel! }] })
    },
    onSuccess: () => setMsg(t('已放進草稿')),
  })
  if (!sel || !frame) return <Card title={t('這個位置')}><Empty>{t('在畫面上框一塊或點一下,這裡會列出那裡已經有的按鈕和狀態,也可以新增。')}</Empty></Card>
  const here = at.data
  const near = here?.buttons ?? []
  return (
    <div className="flex flex-col gap-3">
      <Card title={t('這裡已經有')} extra={<span className="text-xs text-stone-500 num">{boxed ? `${sel[0]}, ${sel[1]} · ${sel[2]}×${sel[3]}` : `${sel[0]}, ${sel[1]}`}</span>}>
        <div className="flex flex-col gap-2 text-sm">
          {!near.length && !here?.states.length && <p className="text-stone-500">{at.isLoading ? t('查詢中…') : t('這裡還沒有東西。')}</p>}
          {near.map(b => (
            <div key={b.id} className="flex items-center gap-2 flex-wrap">
              <span className="px-1.5 rounded bg-amber-100 text-amber-900 text-xs">{t('按鈕')}</span><b className="flex-1 min-w-0 truncate">{b.label}</b>
              <Button variant="ghost" disabled={moveButton.isPending} title={t('按鈕有偏移時用:寫回原本的按鈕,不會多一份')} onClick={() => moveButton.mutate(b.id)}>{t('改到這裡')}</Button>
            </div>
          ))}
          {here?.states.map(r => {
            const s = states.find(x => x.id === r.state)
            return (
              <div key={`${r.state}:${r.roi}`} className="flex flex-col gap-1">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="px-1.5 rounded bg-sky-100 text-sky-900 text-xs">{t('狀態')}</span><b className="flex-1 min-w-0 truncate">{r.name}</b>
                  {boxed && <Button variant="ghost" disabled={moveRoi.isPending} onClick={() => moveRoi.mutate(r)}>{t('範圍改到這裡')}</Button>}
                </div>
                {boxed && s?.source.rule === 'template' && <div className="flex flex-wrap items-center gap-1 text-xs pl-1">
                  <span className="text-stone-500">{t('把這塊當參考圖:')}</span>
                  {s.classes?.map(c => <Button key={String(c.value)} variant="ghost" disabled={addRef.isPending} onClick={() => addRef.mutate({ state: s.id, value: c.value })}>{c.name}</Button>)}
                </div>}
              </div>
            )
          })}
          {msg && <p className="text-xs text-emerald-700">{msg} <button className="underline" onClick={onToDraft}>{t('看草稿')}</button></p>}
          <ErrorText error={at.error || moveButton.error || moveRoi.error || addRef.error} />
        </div>
      </Card>
      <Card title={t('新增按鈕')}>
        <div className="flex flex-col gap-2 text-sm">
          <div className="flex items-center gap-2">
            <input className={`${input} flex-1 min-w-0`} placeholder={t('名稱,例如「設定圖示」')} value={name} onChange={e => { setName(e.target.value); setDup(false) }} />
            <Button disabled={!name.trim() || addButton.isPending || !doc} onClick={() => { if (near.length && !dup) setDup(true); else addButton.mutate() }}>{t('放進草稿')}</Button>
          </div>
          <label className="flex items-center gap-1.5 text-xs"><input type="checkbox" checked={find} onChange={e => setFind(e.target.checked)} />{t('找圖(按鈕會移動時用)')}</label>
          {dup && <div className="rounded-md border border-amber-300 bg-amber-50 px-2 py-1.5 text-xs flex flex-wrap items-center gap-2">
            <span className="flex-1 min-w-[10rem]">{t('這裡已經有「{label}」。腳本用它就好,不必再多一個。', { label: near[0].label })}</span>
            <Button variant="ghost" onClick={() => { setDup(false); setName('') }}>{t('用既有的')}</Button>
            <Button variant="ghost" onClick={() => addButton.mutate()}>{t('還是新增')}</Button>
          </div>}
          <ErrorText error={addButton.error} />
        </div>
      </Card>
      <Card title={t('新增狀態')}>
        {!boxed ? <p className="text-sm text-stone-500">{t('拖曳框出一塊,才能做成狀態。')}</p> : (
          <div className="flex flex-col gap-2 text-sm">
            <input className={input} placeholder={t('要看什麼,例如「地圖開著」')} value={stateName} onChange={e => setStateName(e.target.value)} />
            {!!here?.states.length && <p className="text-xs text-amber-800">{t('這裡已經有「{name}」在看了。如果是同一件事,用上面的按鈕改它就好。', { name: here.states[0].name })}</p>}
            <div className="grid grid-cols-2 gap-2">
              {KINDS.map(([k, label, help]) => (
                <button key={k} disabled={!stateName.trim() || addState.isPending} onClick={() => addState.mutate(k)}
                  className={`text-left rounded-md border p-2 disabled:opacity-50 ${(here?.looks === 'bar' ? k === 'bar' : k === 'template') ? 'border-stone-700' : 'border-stone-200'} hover:bg-stone-50`}>
                  <div className="font-medium">{label}</div><div className="text-xs text-stone-500">{help}</div></button>))}
            </div>
            <ErrorText error={addState.error} />
          </div>
        )}
      </Card>
    </div>
  )
}
