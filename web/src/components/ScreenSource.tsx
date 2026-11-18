import { t } from '../i18n'
import { useMutation } from '@tanstack/react-query'
import { useState } from 'react'
import { api, buttonSnapUrl, imageUrl } from '../api'
import { Button, ErrorText } from './ui'
import { dn } from '../lib/sources'
import { words } from '../lib/project'

/** a picture to work on: a device's screen now, or a recorded frame */
export type PickedScreen = { snap: string; v: number } | { frame: string }
export const screenUrl = (p: PickedScreen) => 'snap' in p ? buttonSnapUrl(p.snap, p.v) : imageUrl(p.frame)
export const screenRef = (p: PickedScreen) => 'snap' in p ? { snap: p.snap } : { frame: p.frame }

const input = 'border border-stone-300 rounded-md px-2 py-1 text-sm bg-white'

export function ScreenSource({ devices, onPick, hint }: { devices: string[]; onPick: (p: PickedScreen) => void; hint?: string }) {
  const [dev, setDev] = useState(devices[0] ?? '')
  const [seed, setSeed] = useState(1)
  const snap = useMutation({ mutationFn: () => api.buttonSnap(dev), onSuccess: r => onPick({ snap: r.device, v: r.updated }) })
  const rec = useMutation({ mutationFn: () => api.randomFrames(1, seed), onSuccess: f => { setSeed(x => x + 1); if (f[0]) onPick({ frame: f[0] }) } })
  return (
    <div className="flex flex-col gap-1 text-xs">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-stone-500">{t('畫面來源:')}</span>
        <select className={input} value={dev} onChange={e => setDev(e.target.value)}>{devices.map(d => <option key={d} value={d}>{dn(d)}</option>)}</select>
        <Button onClick={() => snap.mutate()} disabled={!dev || snap.isPending}>{snap.isPending ? t('擷取中…') : t('擷取這台現在的畫面')}</Button>
        <Button variant="ghost" onClick={() => rec.mutate()} disabled={rec.isPending}>{t('用錄過的畫面(換一張)')}</Button>
        {hint && <span className="text-stone-400">{hint.replace('{device}', words.device)}</span>}
      </div>
      <ErrorText error={snap.error || rec.error} />
    </div>
  )
}
