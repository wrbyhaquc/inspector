import { t } from '../i18n'
import { screen } from '../lib/project'
import { useEffect, useRef, useState, type PointerEvent as RPointerEvent } from 'react'
import { imageUrl, viewUrl } from '../api'

export type Box = [number, number, number, number]
export interface Overlay { box: Box; color: string; label?: string; active?: boolean }

const pctX = (x: number) => `${(x / screen.w) * 100}%`
const pctY = (y: number) => `${(y / screen.h) * 100}%`

/** Full frame with rectangles drawn over the regions the states look at. */
export function FrameView({ frame, overlays = [], fast }: { frame: string; overlays?: Overlay[]; fast?: boolean }) {
  return (
    <div className="relative w-full aspect-video bg-stone-900 rounded-md overflow-hidden">
      <img key={frame} src={fast ? viewUrl(frame) : imageUrl(frame)} alt={t('畫面')} className="absolute inset-0 w-full h-full" />
      {overlays.map((o, i) => (
        <div key={i} className="absolute border-2 pointer-events-none"
          style={{ left: pctX(o.box[0]), top: pctY(o.box[1]), width: pctX(o.box[2]), height: pctY(o.box[3]), borderColor: o.color }}>
          {o.label && <span className="absolute -top-4 left-0 text-[10px] px-1 rounded-sm text-stone-900 whitespace-nowrap" style={{ background: o.color }}>{o.label}</span>}
        </div>
      ))}
    </div>
  )
}

/** Zoomed crop of one region, using CSS background positioning on the full frame.
 * pad: also show this many pixels around it (where a reference picture is searched for), the region itself outlined. */
export function Zoom({ frame, box, scale = 4, label, maxWidth, fast, pad = 0 }: {
  frame: string; box: number[]; scale?: number; label?: string; maxWidth?: number; fast?: boolean; pad?: number
}) {
  const [bx, by, bw, bh] = box
  const x = Math.max(0, bx - pad), y = Math.max(0, by - pad)
  const w = Math.min(screen.w, bx + bw + pad) - x, h = Math.min(screen.h, by + bh + pad) - y
  const s = maxWidth ? Math.min(scale, maxWidth / w) : scale
  return (
    <figure className="flex flex-col gap-1">
      <div key={frame} className="relative rounded border border-stone-300 bg-stone-900" style={{
        width: w * s, height: h * s, imageRendering: 'pixelated',
        backgroundImage: `url(${fast ? viewUrl(frame) : imageUrl(frame)})`, backgroundSize: `${screen.w * s}px ${screen.h * s}px`,
        backgroundPosition: `-${x * s}px -${y * s}px`,
      }}>
        {pad > 0 && <div className="absolute border border-dashed border-amber-400 pointer-events-none" title={t('框的範圍(參考圖的大小);外面是容許偏移會找的地方')}
          style={{ left: (bx - x) * s - 1, top: (by - y) * s - 1, width: bw * s + 2, height: bh * s + 2 }} />}
      </div>
      {label && <figcaption className="text-xs text-stone-500">{label}</figcaption>}
    </figure>
  )
}

/**
 * Edit rectangles on a frame: drag inside the active box to move it, drag its corner handle to resize,
 * or drag on empty space to draw a new position for the active box. Coordinates are in the project's coordinate space.
 */
export function RoiEditor({ frame, boxes, activeIndex, onChange }: {
  frame: string; boxes: { box: Box; color: string; label: string }[]; activeIndex: number; onChange: (box: Box) => void
}) {
  const ref = useRef<HTMLDivElement>(null)
  const drag = useRef<{ mode: 'move' | 'resize' | 'draw'; x: number; y: number; box: Box } | null>(null)
  const [hover, setHover] = useState<[number, number] | null>(null)

  const toImg = (e: { clientX: number; clientY: number }): [number, number] => {
    const r = ref.current!.getBoundingClientRect()
    return [Math.round(((e.clientX - r.left) / r.width) * screen.w), Math.round(((e.clientY - r.top) / r.height) * screen.h)]
  }
  const clamp = (b: Box): Box => {
    let [x, y, w, h] = b
    w = Math.max(4, Math.min(screen.w, w)); h = Math.max(4, Math.min(screen.h, h))
    x = Math.max(0, Math.min(screen.w - w, x)); y = Math.max(0, Math.min(screen.h - h, y))
    return [x, y, w, h]
  }
  const active = boxes[activeIndex]

  const down = (e: RPointerEvent<HTMLDivElement>, mode: 'move' | 'resize' | 'draw') => {
    if (!active) return
    e.stopPropagation(); e.preventDefault()
    const [x, y] = toImg(e)
    drag.current = { mode, x, y, box: mode === 'draw' ? [x, y, 4, 4] : active.box }
    try { ref.current!.setPointerCapture(e.pointerId) } catch { /* pointer already released: dragging still works while inside */ }
    if (mode === 'draw') onChange([x, y, 4, 4])
  }
  const move = (e: RPointerEvent<HTMLDivElement>) => {
    const [x, y] = toImg(e)
    setHover([x, y])
    const d = drag.current
    if (!d) return
    const dx = x - d.x, dy = y - d.y
    const [bx, by, bw, bh] = d.box
    if (d.mode === 'move') onChange(clamp([bx + dx, by + dy, bw, bh]))
    else if (d.mode === 'resize') onChange(clamp([bx, by, bw + dx, bh + dy]))
    else onChange(clamp([Math.min(d.x, x), Math.min(d.y, y), Math.abs(dx), Math.abs(dy)]))
  }
  const up = () => { drag.current = null }

  return (
    <div className="flex flex-col gap-1">
      <div ref={ref} className="relative w-full aspect-video bg-stone-900 rounded-md overflow-hidden select-none cursor-crosshair touch-none"
        onPointerDown={e => down(e, 'draw')} onPointerMove={move} onPointerUp={up} onPointerLeave={() => setHover(null)}>
        <img src={imageUrl(frame)} alt={t('範例畫面')} draggable={false} className="absolute inset-0 w-full h-full pointer-events-none" />
        {boxes.map((b, i) => {
          const isActive = i === activeIndex
          return (
            <div key={i} className={`absolute border-2 ${isActive ? 'cursor-move' : 'pointer-events-none opacity-60'}`}
              style={{ left: pctX(b.box[0]), top: pctY(b.box[1]), width: pctX(b.box[2]), height: pctY(b.box[3]), borderColor: b.color,
                background: isActive ? 'rgba(255,255,255,0.08)' : undefined }}
              onPointerDown={isActive ? e => down(e, 'move') : undefined}>
              <span className="absolute -top-4 left-0 text-[10px] px-1 rounded-sm text-stone-900 whitespace-nowrap" style={{ background: b.color }}>{b.label}</span>
              {isActive && (
                <div className="absolute -right-1.5 -bottom-1.5 w-3 h-3 rounded-sm border border-stone-900 cursor-se-resize" style={{ background: b.color }}
                  onPointerDown={e => down(e, 'resize')} />
              )}
            </div>
          )
        })}
      </div>
      <div className="text-xs text-stone-500 flex justify-between">
        <span>{t('拖曳框內移動、拖曳右下角改大小,在空白處拖曳可直接重畫這個範圍')}</span>
        <span className="num">{hover ? t('游標 {p1}, {p2}', { p1: hover[0], p2: hover[1] }) : ''}</span>
      </div>
    </div>
  )
}

// frames downloaded (and decoded) ahead of time; kept referenced so the browser does not drop them
const preloaded = new Map<string, HTMLImageElement>()

function load(url: string) {
  const old = preloaded.get(url)
  if (old && !(old.complete && !old.naturalWidth)) return old     // loaded or still loading
  // never reuse a failed download (e.g. made while the server was restarting): start a new one
  const im = new Image()
  im.decoding = 'async'
  im.src = url
  preloaded.delete(url)
  preloaded.set(url, im)
  if (preloaded.size > 40) preloaded.delete(preloaded.keys().next().value!)     // forget the oldest
  return im
}

const RETRIES = 5
const STALL_MS = 10000

/** Is the frame's (fast) image really loaded, so what is shown is this frame? A failed or stalled download is
 *  retried a few times; after that `failed` is set and retry() starts over. */
export function useImageReady(frame: string | undefined) {
  const [st, setSt] = useState<{ frame: string; ok: boolean; failed: boolean } | null>(null)
  const [round, setRound] = useState(0)
  useEffect(() => {
    if (!frame) return
    const url = viewUrl(frame)
    let alive = true, attempt = 0
    let stall: ReturnType<typeof setTimeout> | undefined, again: ReturnType<typeof setTimeout> | undefined
    setSt({ frame, ok: false, failed: false })
    const fail = () => {
      if (!alive) return
      clearTimeout(stall)
      const im = preloaded.get(url)
      if (im && !im.naturalWidth) preloaded.delete(url)
      if (++attempt < RETRIES) again = setTimeout(start, 500 * attempt)
      else setSt({ frame, ok: false, failed: true })
    }
    function start() {
      if (!alive) return
      const im = load(url)
      if (im.complete && im.naturalWidth) { setSt({ frame: frame!, ok: true, failed: false }); return }
      const onLoad = () => { if (alive && im.naturalWidth) { clearTimeout(stall); setSt({ frame: frame!, ok: true, failed: false }) } else fail() }
      im.addEventListener('load', onLoad, { once: true })
      im.addEventListener('error', fail, { once: true })
      clearTimeout(stall)
      stall = setTimeout(() => { if (alive && !(im.complete && im.naturalWidth)) { preloaded.delete(url); fail() } }, STALL_MS)
    }
    start()
    return () => { alive = false; clearTimeout(stall); clearTimeout(again) }
  }, [frame, round])
  const mine = !!frame && st?.frame === frame
  return { ready: mine && st!.ok, failed: mine && st!.failed, retry: () => setRound(r => r + 1) }
}

/** start downloading the next frames while the current one is answered */
export function preloadFrames(frames: string[]) {
  for (const f of frames) load(viewUrl(f))
}
