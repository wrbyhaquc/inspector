import { t } from '../i18n'
import { useMutation, useQuery } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { api, walkmapImageUrl } from '../api'
import { Button, Card, ErrorText } from './ui'
import { ScreenSource, screenRef, screenUrl, type PickedScreen } from './ScreenSource'
import { screen } from '../lib/project'
import { sourceIds } from '../lib/sources'

type Pt = { x: number; y: number; label?: string; near?: number; [k: string]: unknown }

/** 在地圖上點路徑: on a picture of the big map, find the sign the points are measured from and click where to go;
 *  the points (map px from the sign: right x, down y) go into 「走到地圖上的位置」. With a walk map its blocked parts show. */
export function MapPointsPicker({ anchor, anchors, area, points, onApply, onClose }: {
  anchor?: string; anchors?: { button: string; x: number; y: number }[]; area?: string; points: Pt[]
  onApply: (p: Pt[]) => void; onClose: () => void
}) {
  const lib = useQuery({ queryKey: ['scripts'], queryFn: api.scripts })
  const buttons = lib.data?.buttons ?? []
  const shadow = useQuery({ queryKey: ['shadow'], queryFn: api.shadowStatus })
  const devices = sourceIds((shadow.data?.status.devices ?? []).map(d => d.name))
  const maps = useQuery({ queryKey: ['walkmaps'], queryFn: api.walkmaps, enabled: !!area })
  const wm = maps.data?.find(m => m.id === area)
  const [src, setSrc] = useState<PickedScreen | null>(null)
  const [at, setAt] = useState<[number, number] | null>(null)       // the sign's place on this picture
  const [pts, setPts] = useState<Pt[]>(points.map(p => ({ ...p })))
  const [mode, setMode] = useState<'add' | 'goal'>(points.length > 1 ? 'add' : 'goal')
  const find = useMutation({
    mutationFn: async (s: PickedScreen) => {
      const tries = [...(anchor ? [{ button: anchor, x: 0, y: 0 }] : []), ...(anchors ?? [])]
      for (const a of tries) {
        const r = await api.buttonLocate(a.button, screenRef(s))
        if (r.x != null && r.y != null) return [r.x - a.x, r.y - a.y] as [number, number]
      }
      throw new Error(t('這張畫面上找不到基準圖示(先在裝置上打開大地圖,讓基準圖示出現在畫面上)'))
    },
    onSuccess: p => setAt(p),
  })
  const label = (id?: string) => buttons.find(b => b.id === id)?.label ?? id ?? ''
  const wrap = useRef<HTMLDivElement>(null)
  const cv = useRef<HTMLCanvasElement>(null)
  const [imgs, setImgs] = useState<{ pic?: HTMLImageElement; mask?: HTMLImageElement }>({})
  useEffect(() => { if (!src) return; const im = new Image(); im.onload = () => setImgs(x => ({ ...x, pic: im })); im.src = screenUrl(src) }, [src])
  useEffect(() => { if (!wm) return; const im = new Image(); im.onload = () => setImgs(x => ({ ...x, mask: im })); im.src = walkmapImageUrl(wm.id, false, wm.updated ?? 0) }, [wm?.id])
  useEffect(() => {
    const c = cv.current
    if (!c || !imgs.pic) return
    c.width = screen.w; c.height = screen.h
    const g = c.getContext('2d')!
    g.drawImage(imgs.pic, 0, 0, screen.w, screen.h)
    if (at && imgs.mask && wm) {                        // the walk map's blocked parts, where they are on this picture
      const tmp = document.createElement('canvas'); tmp.width = wm.size[0]; tmp.height = wm.size[1]
      const tg = tmp.getContext('2d')!; tg.drawImage(imgs.mask, 0, 0)
      const d = tg.getImageData(0, 0, tmp.width, tmp.height)
      for (let i = 0; i < d.data.length; i += 4) {
        const blocked = d.data[i] < 128
        d.data[i] = 220; d.data[i + 1] = 38; d.data[i + 2] = 38; d.data[i + 3] = blocked ? 90 : 0
      }
      tg.putImageData(d, 0, 0)
      g.drawImage(tmp, at[0] + wm.origin[0], at[1] + wm.origin[1])
    }
    if (at) {
      g.fillStyle = '#22c55e'; g.beginPath(); g.arc(at[0], at[1], 7, 0, Math.PI * 2); g.fill()
      g.font = 'bold 16px sans-serif'; g.lineWidth = 3
      pts.forEach((p, k) => {
        const x = at[0] + p.x, y = at[1] + p.y
        if (k > 0) { const q = pts[k - 1]; g.strokeStyle = '#38bdf8'; g.beginPath(); g.moveTo(at[0] + q.x, at[1] + q.y); g.lineTo(x, y); g.stroke() }
        g.fillStyle = k === pts.length - 1 ? '#f59e0b' : '#38bdf8'; g.beginPath(); g.arc(x, y, 7, 0, Math.PI * 2); g.fill()
        g.fillStyle = '#fff'; g.fillText(String(k + 1), x + 9, y - 8)
      })
    }
  }, [imgs, at, pts, wm?.id])
  const click = (e: React.MouseEvent) => {
    if (!at) return
    const r = wrap.current!.getBoundingClientRect()
    const x = Math.round(((e.clientX - r.left) / r.width) * screen.w) - at[0], y = Math.round(((e.clientY - r.top) / r.height) * screen.h) - at[1]
    if (mode === 'goal') setPts(ps => [{ ...(ps[ps.length - 1] ?? {}), x, y }])
    else setPts(ps => [...ps, { x, y }])
  }
  return (
    <Card title={t('在地圖上點路徑')} extra={<span className="flex gap-2">
      <Button variant="ghost" onClick={onClose}>{t('取消')}</Button>
      <Button variant="primary" disabled={!pts.length} onClick={() => onApply(pts)}>{t('用這些點')}</Button>
    </span>}>
      <div className="flex flex-col gap-2 text-xs">
        {!anchor && !anchors?.length ? <span className="text-red-700">{t('先在上面選「地圖上的基準圖示」')}</span> : <>
          <span className="text-stone-500">{t('基準圖示:{label}。點畫面上要走到的地方,位置會換算成「從基準圖示算起」。', { label: label(anchor) })}</span>
          <ScreenSource devices={devices} onPick={s => { setSrc(s); setAt(null); find.mutate(s) }} hint={t('先在裝置上打開大地圖,讓基準圖示和要去的地方都在畫面上')} />
          <ErrorText error={find.error} />
          {area && !wm && maps.isSuccess && <span className="text-amber-700">{t('找不到可走區域圖「{id}」', { id: area })}</span>}
          {src && <div className="flex flex-wrap items-center gap-2">
            <button className={`px-2 py-1 rounded border ${mode === 'goal' ? 'bg-stone-800 text-white border-stone-800' : 'border-stone-300'}`} onClick={() => setMode('goal')}>{t('點一下 = 設成目的地(只有一個點)')}</button>
            <button className={`px-2 py-1 rounded border ${mode === 'add' ? 'bg-stone-800 text-white border-stone-800' : 'border-stone-300'}`} onClick={() => setMode('add')}>{t('點一下 = 再加一個點')}</button>
            {find.isPending && <span className="text-stone-500">{t('找基準圖示中…')}</span>}
            {at && <span className="text-stone-500">{t('綠點 = 基準圖示;藍點依序走,橘點 = 目的地')}{wm ? t(';紅色 = 可走區域圖上不能走的地方') : ''}</span>}
          </div>}
          {src && <div ref={wrap} className="relative w-full max-w-4xl aspect-video bg-stone-900 rounded-md overflow-hidden cursor-crosshair" onClick={click}>
            <canvas ref={cv} className="absolute inset-0 w-full h-full" />
          </div>}
          <div className="flex flex-col gap-1">
            {pts.map((p, k) => (
              <span key={k} className="flex items-center gap-2 num">
                <span className="text-stone-500">{k + 1}.</span>x {p.x} y {p.y}{p.label ? ` · ${p.label}` : ''}
                <button className="text-stone-500 hover:text-red-700" onClick={() => setPts(ps => ps.filter((_q, j) => j !== k))}>{t('刪除')}</button>
              </span>
            ))}
          </div>
        </>}
      </div>
    </Card>
  )
}
