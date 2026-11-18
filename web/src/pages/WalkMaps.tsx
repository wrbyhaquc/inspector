import { t } from '../i18n'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { api, walkmapImageUrl, type LibButton, type WalkMapInfo } from '../api'
import { Button, Card, Empty, ErrorText } from '../components/ui'
import { ScreenSource, screenRef, screenUrl, type PickedScreen } from '../components/ScreenSource'
import { screen } from '../lib/project'

const input = 'border border-stone-300 rounded-md px-2 py-1 text-sm bg-white'

/** 可走區域圖: where on a big map one can walk (dark = cannot), for 「走到地圖上的位置」 to find its own way.
 *  Made from a picture of the big map (a box of the screen, measured from a sign on the map), more parts merged in,
 *  then painted by hand where the picture is wrong; spots found blocked while walking (marks) can be taken off. */
export function WalkMapsEditor({ buttons, devices }: { buttons: LibButton[]; devices: string[] }) {
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['walkmaps'], queryFn: api.walkmaps })
  const [make, setMake] = useState<{ id?: string } | null>(null)
  const [edit, setEdit] = useState<string | null>(null)
  const [confirmDel, setConfirmDel] = useState<string | null>(null)
  const del = useMutation({ mutationFn: (id: string) => api.walkmapDelete(id), onSuccess: () => { setConfirmDel(null); qc.invalidateQueries({ queryKey: ['walkmaps'] }) } })
  const done = () => { setMake(null); qc.invalidateQueries({ queryKey: ['walkmaps'] }) }
  const maps = q.data ?? []
  return (
    <div className="flex flex-col gap-4">
      <Card title={t('可走區域圖({n})', { n: maps.length })} extra={<Button onClick={() => { setEdit(null); setMake({}) }}>{t('+ 新增可走區域圖')}</Button>}>
        <p className="text-sm text-stone-600 mb-3">{t('從大地圖的截圖做出「哪裡能走」:地圖上暗的地方(牆、水、石頭)不能走,其他能走。「走到地圖上的位置」填了可走區域圖,就會照它避開障礙自己找路。截圖沒畫清楚的地方可以用筆刷改。')}</p>
        <ErrorText error={q.error || del.error} />
        {!maps.length ? <Empty>{q.isLoading ? t('讀取中…') : t('還沒有可走區域圖')}</Empty> : (
          <div className="flex flex-col divide-y divide-stone-100">
            {maps.map(m => (
              <div key={m.id} className="flex flex-wrap items-center gap-3 py-2 text-sm">
                <img src={walkmapImageUrl(m.id, false, m.updated ?? 0)} alt="" className="h-12 w-20 object-contain bg-stone-800 rounded" />
                <span className="font-medium">{m.label}</span>
                <span className="font-mono text-xs text-stone-500">{m.id}</span>
                <span className="text-xs text-stone-500 num">{t('{w}×{h} 像素 · 卡住點 {k} 個 · 走通過的路線 {p} 條', { w: m.size[0], h: m.size[1], k: m.marks.length, p: m.proven })}</span>
                <span className="ml-auto flex gap-2">
                  <Button variant="ghost" onClick={() => { setMake(null); setEdit(m.id) }}>{t('修改')}</Button>
                  <Button variant="ghost" onClick={() => { setEdit(null); setMake({ id: m.id }) }}>{t('再合併一張')}</Button>
                  {confirmDel === m.id
                    ? <><Button variant="primary" onClick={() => del.mutate(m.id)}>{t('確定刪除')}</Button><Button variant="ghost" onClick={() => setConfirmDel(null)}>{t('取消')}</Button></>
                    : <Button variant="ghost" onClick={() => setConfirmDel(m.id)}>{t('刪除')}</Button>}
                </span>
              </div>
            ))}
          </div>
        )}
      </Card>
      {make && <MakeForm key={make.id ?? 'new'} merge={make.id} maps={maps} buttons={buttons} devices={devices} onDone={done} onCancel={() => setMake(null)} />}
      {edit && maps.find(m => m.id === edit) && <PaintForm key={edit} m={maps.find(m => m.id === edit)!} onDone={() => { setEdit(null); done() }} onCancel={() => setEdit(null)} />}
    </div>
  )
}

/** a new walk map (or another part merged in): a picture of the big map, the box that is the map, how dark is blocked, the sign */
function MakeForm({ merge, maps, buttons, devices, onDone, onCancel }: {
  merge?: string; maps: WalkMapInfo[]; buttons: LibButton[]; devices: string[]; onDone: () => void; onCancel: () => void
}) {
  const old = maps.find(m => m.id === merge)
  const [id, setId] = useState(merge ?? '')
  const [label, setLabel] = useState(old?.label ?? '')
  const [src, setSrc] = useState<PickedScreen | null>(null)
  const [box, setBox] = useState<number[]>([Math.round(screen.w * 0.2), Math.round(screen.h * 0.18), Math.round(screen.w * 0.6), Math.round(screen.h * 0.65)])
  const [dark, setDark] = useState(35)
  const [anchor, setAnchor] = useState('')
  const save = useMutation({ mutationFn: () => api.walkmapMake({ id, label, ...(src ? screenRef(src) : {}), box, anchor, dark, merge: !!merge }), onSuccess: onDone })
  const finds = buttons.filter(b => b.find)
  const wrap = useRef<HTMLDivElement>(null)
  const cv = useRef<HTMLCanvasElement>(null)
  const img = useRef<HTMLImageElement | null>(null)
  const [drag, setDrag] = useState<[number, number] | null>(null)
  const [loaded, setLoaded] = useState(0)
  useEffect(() => {
    if (!src) return
    const im = new Image()
    im.onload = () => { img.current = im; setLoaded(x => x + 1) }
    im.src = screenUrl(src)
  }, [src])
  useEffect(() => {                                     // the picture, the box, and in it what counts as blocked (red)
    const c = cv.current, im = img.current
    if (!c || !im) return
    c.width = screen.w; c.height = screen.h
    const g = c.getContext('2d')!
    g.drawImage(im, 0, 0, screen.w, screen.h)
    const [x, y, w, h] = box
    if (w > 0 && h > 0) {
      const d = g.getImageData(x, y, w, h)
      for (let i = 0; i < d.data.length; i += 4) {
        if (Math.max(d.data[i], d.data[i + 1], d.data[i + 2]) <= dark) { d.data[i] = 220; d.data[i + 1] = 38; d.data[i + 2] = 38 }
      }
      g.putImageData(d, x, y)
      g.strokeStyle = '#38bdf8'; g.lineWidth = 3; g.strokeRect(x, y, w, h)
    }
  }, [loaded, box, dark])
  const at = (e: React.MouseEvent): [number, number] => {
    const r = wrap.current!.getBoundingClientRect()
    return [Math.round(((e.clientX - r.left) / r.width) * screen.w), Math.round(((e.clientY - r.top) / r.height) * screen.h)]
  }
  const ok = /^[a-z][a-z0-9_]{0,40}$/.test(id) && !!src && !!anchor && box[2] >= 20 && box[3] >= 20
  return (
    <Card title={merge ? t('合併到「{label}」', { label: old?.label ?? merge }) : t('新增可走區域圖')} extra={<span className="flex gap-2">
      <Button variant="ghost" onClick={onCancel}>{t('取消')}</Button>
      <Button variant="primary" disabled={!ok || save.isPending} onClick={() => save.mutate()}>{save.isPending ? t('處理中…') : merge ? t('合併') : t('建立')}</Button>
    </span>}>
      <div className="flex flex-col gap-3 text-sm">
        <ErrorText error={save.error} />
        {!merge && <div className="flex flex-wrap items-center gap-2">
          <input className={`${input} w-48`} placeholder={t('名稱,例如「某某地區(平面地圖)」')} value={label} onChange={e => setLabel(e.target.value)} />
          <input className={`${input} w-40 font-mono`} placeholder={t('代號,例如 plaza')} value={id} onChange={e => setId(e.target.value)} />
          {maps.some(m => m.id === id) && <span className="text-amber-700 text-xs">{t('已經有這個代號:建立會取代它(學到的卡住點和路線也會清掉)')}</span>}
        </div>}
        <ScreenSource devices={devices} onPick={setSrc} hint={t('先在裝置上打開大地圖,移到要走的那一帶,再擷取')} />
        {src && <>
          <span className="text-xs text-stone-500">{t('在畫面上拖出地圖的範圍(藍框);框裡紅色的地方算不能走。')}</span>
          <div ref={wrap} className="relative w-full max-w-4xl aspect-video bg-stone-900 rounded-md overflow-hidden cursor-crosshair select-none"
            onMouseDown={e => setDrag(at(e))}
            onMouseMove={e => { if (drag) { const [x, y] = at(e); setBox([Math.min(drag[0], x), Math.min(drag[1], y), Math.abs(x - drag[0]), Math.abs(y - drag[1])]) } }}
            onMouseUp={() => setDrag(null)} onMouseLeave={() => setDrag(null)}>
            <canvas ref={cv} className="absolute inset-0 w-full h-full" />
          </div>
          <div className="flex flex-wrap items-center gap-3 text-xs">
            <label className="flex items-center gap-2" title={t('地圖上比這個暗的地方(最亮的顏色也不超過)算不能走')}>{t('多暗算不能走')}
              <input type="range" min={5} max={120} value={dark} onChange={e => setDark(Number(e.target.value))} /><span className="num w-8">{dark}</span></label>
            <span className="num text-stone-500">{t('範圍 {x}, {y}, {w}×{h}', { x: box[0], y: box[1], w: box[2], h: box[3] })}</span>
          </div>
          <label className="flex flex-wrap items-center gap-2 text-xs" title={t('地圖上一個固定的圖示(找圖的按鈕),所有位置都從它算起;地圖跟著自己捲動也沒關係')}>
            {t('地圖上的基準圖示')}
            <select className={`${input} max-w-72`} value={anchor} onChange={e => setAnchor(e.target.value)}>
              <option value="">{t('(選一個找圖的按鈕)')}</option>
              {finds.map(b => <option key={b.id} value={b.id}>{b.label}</option>)}
            </select>
            <span className="text-stone-400">{t('還沒有的話,先到「按鈕」用這張地圖新增一個')}</span>
          </label>
        </>}
      </div>
    </Card>
  )
}

/** paint where the picture is wrong, take off spots marked blocked while walking, drop the ways walked through */
function PaintForm({ m, onDone, onCancel }: { m: WalkMapInfo; onDone: () => void; onCancel: () => void }) {
  const [W, H] = m.size
  const cv = useRef<HTMLCanvasElement>(null)
  const mask = useRef<Uint8Array | null>(null)          // 1 = can walk
  const over = useRef<ImageData | null>(null)
  const bg = useRef<HTMLImageElement | null>(null)
  const [ready, setReady] = useState(0)
  const [brush, setBrush] = useState(8)
  const [mode, setMode] = useState<'block' | 'free' | 'mark'>('block')
  const [marks, setMarks] = useState(m.marks)
  const [clearWays, setClearWays] = useState(false)
  const [dirty, setDirty] = useState(false)
  const down = useRef(false)
  const save = useMutation({
    mutationFn: () => {
      const c = document.createElement('canvas'); c.width = W; c.height = H
      const g = c.getContext('2d')!, d = g.createImageData(W, H)
      mask.current!.forEach((v, i) => { const k = v ? 255 : 0; d.data[i * 4] = k; d.data[i * 4 + 1] = k; d.data[i * 4 + 2] = k; d.data[i * 4 + 3] = 255 })
      g.putImageData(d, 0, 0)
      return api.walkmapPaint(m.id, c.toDataURL('image/png'), marks, clearWays)
    }, onSuccess: onDone,
  })
  useEffect(() => {
    const im = new Image()
    im.onload = () => {
      const c = document.createElement('canvas'); c.width = W; c.height = H
      const g = c.getContext('2d')!; g.drawImage(im, 0, 0)
      const d = g.getImageData(0, 0, W, H).data
      const a = new Uint8Array(W * H)
      for (let i = 0; i < a.length; i++) a[i] = d[i * 4] >= 128 ? 1 : 0
      mask.current = a
      over.current = new ImageData(W, H)
      paintOver(0, 0, W, H)
      setReady(x => x + 1)
    }
    im.src = walkmapImageUrl(m.id, false, m.updated ?? 0)
    if (m.has_bg) { const b = new Image(); b.onload = () => { bg.current = b; setReady(x => x + 1) }; b.src = walkmapImageUrl(m.id, true, m.updated ?? 0) }
  }, [m.id])
  const paintOver = (x0: number, y0: number, w: number, h: number) => {   // blocked: red over the picture (or dark)
    const o = over.current!, a = mask.current!
    for (let y = y0; y < y0 + h; y++) for (let x = x0; x < x0 + w; x++) {
      const i = y * W + x, j = i * 4
      if (a[i]) { o.data[j] = 255; o.data[j + 1] = 255; o.data[j + 2] = 255; o.data[j + 3] = m.has_bg ? 0 : 255 }
      else { o.data[j] = 220; o.data[j + 1] = 38; o.data[j + 2] = 38; o.data[j + 3] = m.has_bg ? 120 : 255 }
    }
  }
  useEffect(() => {                                     // draw: the map picture, the blocked parts, the marks
    const c = cv.current
    if (!c || !over.current) return
    c.width = W; c.height = H
    const g = c.getContext('2d')!
    g.clearRect(0, 0, W, H)
    if (bg.current) g.drawImage(bg.current, 0, 0)
    const t2 = document.createElement('canvas'); t2.width = W; t2.height = H
    t2.getContext('2d')!.putImageData(over.current, 0, 0)
    g.drawImage(t2, 0, 0)
    g.strokeStyle = '#f59e0b'; g.lineWidth = 2
    for (const [x, y, r] of marks) { g.beginPath(); g.arc(x - m.origin[0], y - m.origin[1], Math.max(r, 4), 0, Math.PI * 2); g.stroke() }
    g.fillStyle = '#22c55e'; g.beginPath(); g.arc(-m.origin[0], -m.origin[1], 5, 0, Math.PI * 2); g.fill()   // the sign (0, 0)
  }, [ready, marks])
  const at = (e: React.MouseEvent): [number, number] => {
    const r = cv.current!.getBoundingClientRect()
    return [Math.round(((e.clientX - r.left) / r.width) * W), Math.round(((e.clientY - r.top) / r.height) * H)]
  }
  const stroke = (e: React.MouseEvent) => {
    const [x, y] = at(e)
    if (mode === 'mark') {
      const wx = x + m.origin[0], wy = y + m.origin[1]
      setMarks(ms => ms.filter(([mx, my, r]) => Math.hypot(mx - wx, my - wy) > Math.max(r, 6)))
      setDirty(true)
      return
    }
    const a = mask.current!, v = mode === 'free' ? 1 : 0, r = brush
    const x0 = Math.max(0, x - r), y0 = Math.max(0, y - r), x1 = Math.min(W, x + r + 1), y1 = Math.min(H, y + r + 1)
    for (let yy = y0; yy < y1; yy++) for (let xx = x0; xx < x1; xx++) if ((xx - x) ** 2 + (yy - y) ** 2 <= r * r) a[yy * W + xx] = v
    paintOver(x0, y0, x1 - x0, y1 - y0)
    setDirty(true)
    setReady(k => k + 1)
  }
  const tool = (k: typeof mode, tx: string) => (
    <button className={`px-2 py-1 rounded border text-xs ${mode === k ? 'bg-stone-800 text-white border-stone-800' : 'border-stone-300'}`} onClick={() => setMode(k)}>{tx}</button>)
  return (
    <Card title={t('修改「{label}」', { label: m.label })} extra={<span className="flex gap-2">
      <Button variant="ghost" onClick={onCancel}>{t('取消')}</Button>
      <Button variant="primary" disabled={(!dirty && !clearWays) || save.isPending} onClick={() => save.mutate()}>{save.isPending ? t('儲存中…') : t('儲存')}</Button>
    </span>}>
      <div className="flex flex-col gap-2 text-sm">
        <ErrorText error={save.error} />
        <div className="flex flex-wrap items-center gap-2 text-xs">
          {tool('block', t('塗成不能走'))}{tool('free', t('塗成能走'))}{tool('mark', t('點掉卡住點'))}
          {mode !== 'mark' && <label className="flex items-center gap-1">{t('筆刷')}<input type="range" min={2} max={40} value={brush} onChange={e => setBrush(Number(e.target.value))} /><span className="num w-6">{brush}</span></label>}
          <label className="flex items-center gap-1" title={t('地圖改過很多時,之前「走通過、下次一口氣走完」的路線可能不再對:清掉讓它重新學')}>
            <input type="checkbox" checked={clearWays} onChange={e => setClearWays(e.target.checked)} />{t('清掉走通過的路線({n} 條)', { n: m.proven })}</label>
        </div>
        <span className="text-xs text-stone-500">{t('紅色 = 不能走;橘色圈 = 走路時卡住記下的點;綠點 = 基準圖示。')}{!m.has_bg && t('(這張是舊的,沒有存地圖原圖,只能看到能不能走)')}</span>
        <div className="overflow-auto max-h-[70vh] border border-stone-200 rounded bg-stone-900">
          <canvas ref={cv} className="cursor-crosshair" style={{ width: Math.min(W, 1100), imageRendering: 'pixelated' }}
            onMouseDown={e => { down.current = true; stroke(e) }} onMouseMove={e => { if (down.current && mode !== 'mark') stroke(e) }}
            onMouseUp={() => { down.current = false }} onMouseLeave={() => { down.current = false }} />
        </div>
      </div>
    </Card>
  )
}
