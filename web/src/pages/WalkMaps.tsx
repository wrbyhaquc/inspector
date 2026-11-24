import { t } from '../i18n'
import { useMutation } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { api, walkmapImageUrl, type WalkMapInfo } from '../api'
import { Button, Card, ErrorText } from '../components/ui'

/** paint where the picture is wrong, take off spots marked blocked while walking, drop the ways walked through */
export function PaintForm({ m, onDone, onCancel }: { m: WalkMapInfo; onDone: () => void; onCancel: () => void }) {
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
