import { t } from '../i18n'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { api, buttonSnapUrl, walkmapImageUrl, type LibButton, type MapPlace, type WalkMapInfo, type WalkSettings, type WalkView } from '../api'
import { Button, Card, Empty, ErrorText } from '../components/ui'
import { dn } from '../lib/sources'
import { screen, words } from '../lib/project'
import { usePersistentState } from '../lib/persist'
import { PaintForm } from './WalkMaps'

const input = 'border border-stone-300 rounded-md px-2 py-1 text-sm bg-white'

/** 地圖: a picture of a big map is all it takes - 拍下來, click the places, 試走. The signs that tell where the map is
 *  on the screen are cut from the picture by the platform; how walking is done (open the map, "me", the control) is
 *  set once for the project (走路設定). */
export function MapsEditor({ buttons, subs, devices }: { buttons: LibButton[]; subs: { id: string; name: string }[]; devices: string[] }) {
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['walkmaps'], queryFn: api.walkmaps })
  const ws = useQuery({ queryKey: ['walksettings'], queryFn: api.walkSettings })
  const [openId, setOpenId] = usePersistentState<string | null>('maps.open', null)
  const [dev, setDev] = usePersistentState<string>('maps.device', devices[0] ?? '')
  const [adding, setAdding] = useState(false)
  const [confirmDel, setConfirmDel] = useState<string | null>(null)
  const del = useMutation({ mutationFn: (id: string) => api.walkmapDelete(id), onSuccess: () => { setConfirmDel(null); qc.invalidateQueries({ queryKey: ['walkmaps'] }) } })
  const maps = q.data ?? []
  const ready = !!ws.data?.me
  const cur = maps.find(m => m.id === openId)
  const device = devices.includes(dev) ? dev : devices[0] ?? ''
  return (
    <div className="flex flex-col gap-4">
      <WalkSettingsCard s={ws.data} loading={ws.isLoading} buttons={buttons} subs={subs} devices={devices} device={device} />
      <Card title={t('地圖({n})', { n: maps.length })} extra={ready && <Button variant="primary" onClick={() => setAdding(true)}>{t('+ 新增地圖')}</Button>}>
        <ol className="text-sm text-stone-600 mb-3 flex flex-wrap gap-x-6 gap-y-1">
          <li>{t('① 在{device}上打開大地圖,按「拍下來」', { device: words.device })}</li>
          <li>{t('② 在地圖上點要去的地方,取個名字')}</li>
          <li>{t('③ 按「試走」,看它自己走過去')}</li>
        </ol>
        <ErrorText error={q.error || del.error} />
        {adding && <NewMap devices={devices} device={device} setDevice={setDev}
          onDone={m => { setAdding(false); setOpenId(m.id); qc.invalidateQueries({ queryKey: ['walkmaps'] }); qc.invalidateQueries({ queryKey: ['scripts'] }) }}
          onCancel={() => setAdding(false)} />}
        {!maps.length ? <Empty>{q.isLoading ? t('讀取中…') : ready ? t('還沒有地圖:按「+ 新增地圖」') : t('先設定上面的「走路設定」')}</Empty> : (
          <div className="flex flex-col divide-y divide-stone-100">
            {maps.map(m => (
              <div key={m.id} className={`flex flex-wrap items-center gap-3 py-2 text-sm ${m.id === openId ? 'bg-amber-50' : ''}`}>
                <img src={walkmapImageUrl(m.id, m.has_bg, m.updated ?? 0)} alt="" className="h-12 w-20 object-cover bg-stone-800 rounded" />
                <button className="font-medium hover:underline" onClick={() => setOpenId(m.id === openId ? null : m.id)}>{m.label}</button>
                <span className="text-xs text-stone-500">{m.places.length ? t('{n} 個地點:{names}', { n: m.places.length, names: m.places.map(p => p.name).join('、') }) : t('還沒有地點')}</span>
                {!m.signs.length && <span className="text-xs text-amber-700" title={t('用舊的方式(自己選基準圖示)做的:只能在腳本的進階設定裡用')}>{t('舊的地圖')}</span>}
                <span className="ml-auto flex gap-2">
                  <Button variant="ghost" onClick={() => setOpenId(m.id === openId ? null : m.id)}>{m.id === openId ? t('收起') : t('打開')}</Button>
                  {confirmDel === m.id
                    ? <><Button variant="primary" onClick={() => del.mutate(m.id)}>{t('確定刪除')}</Button><Button variant="ghost" onClick={() => setConfirmDel(null)}>{t('取消')}</Button></>
                    : <Button variant="ghost" onClick={() => setConfirmDel(m.id)}>{t('刪除')}</Button>}
                </span>
              </div>
            ))}
          </div>
        )}
      </Card>
      {cur && <MapView key={cur.id} m={cur} devices={devices} device={device} setDevice={setDev} />}
    </div>
  )
}

function DeviceSelect({ devices, device, setDevice }: { devices: string[]; device: string; setDevice: (d: string) => void }) {
  return <select className={input} value={device} onChange={e => setDevice(e.target.value)}>{devices.map(d => <option key={d} value={d}>{dn(d)}</option>)}</select>
}

/** ① a name, the device, 拍下來 (the device's screen now, with its big map open) */
function NewMap({ devices, device, setDevice, onDone, onCancel }: {
  devices: string[]; device: string; setDevice: (d: string) => void; onDone: (m: WalkMapInfo) => void; onCancel: () => void
}) {
  const [label, setLabel] = useState('')
  const shoot = useMutation({
    mutationFn: async () => { const s = await api.buttonSnap(device); return api.mapShoot({ label, snap: s.device }) },
    onSuccess: onDone,
  })
  return (
    <div className="flex flex-col gap-2 mb-3 p-3 rounded-md border border-amber-300 bg-amber-50 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <input className={`${input} w-56`} autoFocus placeholder={t('地圖的名字,例如「某某村莊」')} value={label} onChange={e => setLabel(e.target.value)} />
        <DeviceSelect devices={devices} device={device} setDevice={setDevice} />
        <Button variant="primary" disabled={!label.trim() || !device || shoot.isPending} onClick={() => shoot.mutate()}>{shoot.isPending ? t('拍照中…') : t('拍下來')}</Button>
        <Button variant="ghost" onClick={onCancel}>{t('取消')}</Button>
      </div>
      <span className="text-xs text-stone-500">{t('先在這台{device}上打開大地圖,並打開地圖上的標示(人物、地點的名字;常在地圖下方的篩選裡),讓要去的地方在畫面上看得到,再按「拍下來」。地圖比一個畫面大的話,之後可以移過去「再拍一塊」。', { device: words.device })}</span>
      <ErrorText error={shoot.error} />
    </div>
  )
}

const WHY: Record<string, string> = {
  lost: t('在地圖上認不出自己在哪:可能地圖被放大縮小過,或這一帶還沒拍進來(移過去按「再拍一塊」)'),
  no_way: t('照地圖找不到走得到的路:目的地可能在紅色(不能走)的地方,把地點點在能走的地方,或用「修改能不能走」塗開'),
  stuck: t('走不過去:卡住的地方已記成不能走(橘色圈),再試一次會繞開'),
  too_far: t('推了很多次還沒走到:看看路線(虛線)是不是繞得太遠'),
}

/** ② ③ the map: click to add a place, 試走 to a place (the walk shown on the map as it goes) */
function MapView({ m, devices, device, setDevice }: { m: WalkMapInfo; devices: string[]; device: string; setDevice: (d: string) => void }) {
  const qc = useQueryClient()
  const [W, H] = m.size
  const [places, setPlaces] = useState<MapPlace[]>(m.places)
  useEffect(() => setPlaces(m.places), [m.updated])
  const [adding, setAdding] = useState<{ x: number; y: number } | null>(null)     // picture px of a new place
  const [name, setName] = useState('')
  const [editing, setEditing] = useState<number | null>(null)
  const [showBlocked, setShowBlocked] = useState(false)
  const [paint, setPaint] = useState(false)
  const [label, setLabel] = useState<string | null>(null)
  const [tried, setTried] = useState<{ place: string; device: string; t: number } | null>(null)
  const refresh = () => { qc.invalidateQueries({ queryKey: ['walkmaps'] }); qc.invalidateQueries({ queryKey: ['scripts'] }) }
  const save = useMutation({ mutationFn: (ps: MapPlace[]) => api.mapPlaces(m.id, ps), onSuccess: ps => { setPlaces(ps); refresh() } })
  const rename = useMutation({ mutationFn: (l: string) => api.mapLabel(m.id, l), onSuccess: () => { setLabel(null); refresh() } })
  const more = useMutation({ mutationFn: async () => { const s = await api.buttonSnap(device); return api.mapShoot({ id: m.id, snap: s.device }) }, onSuccess: refresh })
  const go = useMutation({ mutationFn: (p: MapPlace) => api.mapTry(m.id, device, p.id!), onSuccess: (r, p) => setTried({ place: p.id!, device, t: r.t }) })
  const shadow = useQuery({ queryKey: ['shadow'], queryFn: api.shadowStatus, refetchInterval: tried ? 1000 : false })
  const dv = shadow.data?.status.devices?.find(d => d.name === (tried?.device ?? device))
  const walk: WalkView | null = tried && dv?.walk && dv.walk.map === m.id && (dv.walk.t ?? 0) >= tried.t - 1 ? dv.walk : null
  const proc = tried ? dv?.proc : null
  const done = walk && walk.state !== 'walking' && !proc
  useEffect(() => { if (done || (tried && !proc && !walk && Date.now() / 1000 - tried.t > 20)) setTimeout(() => qc.invalidateQueries({ queryKey: ['walkmaps'] }), 500) }, [done])

  // the pictures: the map (or, for an old one, what can be walked) and its blocked parts in red
  const cv = useRef<HTMLCanvasElement>(null)
  const [pic, setPic] = useState<HTMLImageElement | null>(null)
  const [red, setRed] = useState<HTMLCanvasElement | null>(null)
  useEffect(() => {
    const im = new Image(); im.onload = () => setPic(im); im.src = walkmapImageUrl(m.id, m.has_bg, m.updated ?? 0)
    const mk = new Image()
    mk.onload = () => {
      const c = document.createElement('canvas'); c.width = W; c.height = H
      const g = c.getContext('2d')!; g.drawImage(mk, 0, 0)
      const d = g.getImageData(0, 0, W, H)
      for (let i = 0; i < d.data.length; i += 4) { const b = d.data[i] < 128; d.data[i] = 220; d.data[i + 1] = 38; d.data[i + 2] = 38; d.data[i + 3] = b ? 110 : 0 }
      g.putImageData(d, 0, 0); setRed(c)
    }
    mk.src = walkmapImageUrl(m.id, false, m.updated ?? 0)
  }, [m.id, m.updated])
  const [ox, oy] = m.origin
  useEffect(() => {
    const c = cv.current
    if (!c || !pic) return
    c.width = W; c.height = H
    const g = c.getContext('2d')!
    g.drawImage(pic, 0, 0, W, H)
    if (showBlocked && red) g.drawImage(red, 0, 0)
    const P = (p: [number, number]) => [p[0] - ox, p[1] - oy] as const
    g.lineWidth = 2
    for (const [x, y, r] of m.marks) { g.strokeStyle = '#f59e0b'; g.beginPath(); g.arc(x - ox, y - oy, Math.max(r, 4), 0, Math.PI * 2); g.stroke() }
    if (walk) {
      if (walk.way.length) {                       // the way it means to go
        g.setLineDash([6, 5]); g.strokeStyle = '#fbbf24'; g.lineWidth = 2; g.beginPath()
        const s0 = walk.me ? P(walk.me) : P(walk.way[0]); g.moveTo(s0[0], s0[1]); walk.way.forEach(p => { const q = P(p); g.lineTo(q[0], q[1]) }); g.stroke(); g.setLineDash([])
      }
      if (walk.trail.length > 1) {                 // where it has been
        g.strokeStyle = '#38bdf8'; g.lineWidth = 3; g.beginPath()
        walk.trail.forEach((p, k) => { const q = P(p); if (k) g.lineTo(q[0], q[1]); else g.moveTo(q[0], q[1]) }); g.stroke()
      }
      for (const mk of walk.marks ?? []) { const q = P(mk); g.strokeStyle = '#f59e0b'; g.beginPath(); g.arc(q[0], q[1], 7, 0, Math.PI * 2); g.stroke() }
      if (walk.me) { const q = P(walk.me); g.fillStyle = '#ef4444'; g.strokeStyle = '#fff'; g.lineWidth = 2; g.beginPath(); g.arc(q[0], q[1], 7, 0, Math.PI * 2); g.fill(); g.stroke() }
    }
    g.font = 'bold 15px sans-serif'; g.lineWidth = 3
    places.forEach(p => {
      const [x, y] = [p.x - ox, p.y - oy]
      g.fillStyle = tried?.place === p.id ? '#f59e0b' : '#22c55e'; g.strokeStyle = '#fff'; g.lineWidth = 2
      g.beginPath(); g.arc(x, y, 8, 0, Math.PI * 2); g.fill(); g.stroke()
      g.lineWidth = 3; g.strokeStyle = 'rgba(0,0,0,.75)'; g.strokeText(p.name, x + 11, y + 5); g.fillStyle = '#fff'; g.fillText(p.name, x + 11, y + 5)
    })
    if (adding) { g.fillStyle = '#a855f7'; g.beginPath(); g.arc(adding.x, adding.y, 8, 0, Math.PI * 2); g.fill() }
  }, [pic, red, showBlocked, places, adding, walk, m.marks, tried?.place])
  const at = (e: React.MouseEvent) => {
    const r = cv.current!.getBoundingClientRect()
    return { x: Math.round(((e.clientX - r.left) / r.width) * W), y: Math.round(((e.clientY - r.top) / r.height) * H) }
  }
  const addPlace = () => {
    if (!adding || !name.trim()) return
    save.mutate([...places, { name: name.trim(), x: adding.x + ox, y: adding.y + oy }])
    setAdding(null); setName('')
  }
  const left = (adding?.x ?? 0) / W > 0.6
  const secs = tried ? Math.max(0, Math.round(((walk?.ended ?? (done ? walk?.t : undefined) ?? Date.now() / 1000) - tried.t))) : 0
  const tp = places.find(p => p.id === tried?.place)
  return (
    <Card title={label === null
      ? <span className="flex items-center gap-2">{m.label}<button className="text-xs font-normal text-stone-500 hover:text-stone-900" onClick={() => setLabel(m.label)}>{t('改名')}</button></span>
      : <span className="flex items-center gap-2"><input className={`${input} w-48`} autoFocus value={label} onChange={e => setLabel(e.target.value)} onKeyDown={e => { if (e.key === 'Enter') rename.mutate(label) }} />
        <Button onClick={() => rename.mutate(label)}>{t('存')}</Button><Button variant="ghost" onClick={() => setLabel(null)}>{t('取消')}</Button></span>}
      extra={<span className="flex flex-wrap items-center gap-2 text-xs">
        <DeviceSelect devices={devices} device={device} setDevice={setDevice} />
        {!!m.signs.length && <Button onClick={() => more.mutate()} disabled={more.isPending} title={t('在{device}上把大地圖移到還沒拍的地方(要和拍過的有一點重疊),再按這個', { device: words.device })}>{more.isPending ? t('拍照中…') : t('再拍一塊')}</Button>}
        <Button variant="ghost" onClick={() => setPaint(!paint)}>{paint ? t('收起') : t('修改能不能走')}</Button>
      </span>}>
      <div className="flex flex-col gap-2 text-sm">
        <ErrorText error={save.error || rename.error || more.error || go.error} />
        {more.data && <span className="text-xs text-green-700">{t('拍進來了:地圖變成 {w}×{h},多了 {n} 個記號', { w: more.data.size[0], h: more.data.size[1], n: more.data.added_signs })}</span>}
        {!m.signs.length && <span className="text-xs text-amber-700">{t('這是舊的地圖(自己選基準圖示做的):地點可以標,但試走和腳本裡的「走到地點」要用新拍的地圖。')}</span>}
        {paint && <PaintForm m={m} onDone={() => { setPaint(false); refresh() }} onCancel={() => setPaint(false)} />}
        <div className="flex flex-wrap items-center gap-3 text-xs text-stone-500">
          <span>{t('點地圖上要去的地方 = 新增一個地點')}</span>
          <span>{t('看不到要去的地方?在{device}上打開地圖上的標示(人物、地點的名字),再按「再拍一塊」。', { device: words.device })}</span>
          <label className="flex items-center gap-1"><input type="checkbox" checked={showBlocked} onChange={e => setShowBlocked(e.target.checked)} />{t('顯示不能走的地方(紅色)')}</label>
          {walk && <span>{t('藍線 = 走過的路;黃虛線 = 打算走的路;紅點 = 自己')}</span>}
        </div>
        <div className="flex flex-col lg:flex-row gap-3 items-start">
          <div className="relative w-full lg:flex-1 min-w-0 overflow-hidden rounded-md bg-stone-900">
            <canvas ref={cv} className="block w-full h-auto cursor-crosshair" onClick={e => { if (!adding) { setAdding(at(e)); setName('') } }} />
            {adding && (
              <div className="absolute flex items-center gap-1 p-1.5 rounded-md bg-white shadow-lg border border-stone-200"
                style={{ top: `${(adding.y / H) * 100}%`, ...(left ? { right: `${100 - (adding.x / W) * 100 + 2}%` } : { left: `${(adding.x / W) * 100 + 2}%` }) }}>
                <input className={`${input} w-36`} autoFocus placeholder={t('這裡叫什麼?')} value={name} onChange={e => setName(e.target.value)}
                  onKeyDown={e => { if (e.key === 'Enter') addPlace(); if (e.key === 'Escape') setAdding(null) }} />
                <Button variant="primary" disabled={!name.trim()} onClick={addPlace}>{t('加入')}</Button>
                <Button variant="ghost" onClick={() => setAdding(null)}>{t('取消')}</Button>
              </div>
            )}
          </div>
          <div className="w-full lg:w-72 flex flex-col gap-2">
            <span className="font-medium">{t('地點')}</span>
            {!places.length && <span className="text-xs text-stone-500">{t('還沒有:在地圖上點一下')}</span>}
            {places.map((p, k) => (
              <div key={p.id ?? k} className="flex items-center gap-1.5">
                {editing === k
                  ? <input className={`${input} flex-1 min-w-0`} autoFocus defaultValue={p.name}
                      onBlur={e => { setEditing(null); if (e.target.value.trim() && e.target.value.trim() !== p.name) save.mutate(places.map((q, j) => j === k ? { ...q, name: e.target.value.trim() } : q)) }}
                      onKeyDown={e => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur(); if (e.key === 'Escape') setEditing(null) }} />
                  : <button className="flex-1 min-w-0 text-left truncate hover:underline" title={t('改名')} onClick={() => setEditing(k)}>{p.name}</button>}
                <Button variant="primary" disabled={!m.signs.length || !device || go.isPending || (!!tried && !done && !!proc)} onClick={() => go.mutate(p)}>{t('試走')}</Button>
                <button className="text-xs text-stone-400 hover:text-red-700" onClick={() => save.mutate(places.filter((_q, j) => j !== k))}>{t('刪除')}</button>
              </div>
            ))}
            {tried && tp && (
              <div className={`mt-2 p-2 rounded-md text-xs border ${done ? (walk?.state === 'arrived' ? 'border-green-300 bg-green-50' : 'border-red-300 bg-red-50') : 'border-sky-300 bg-sky-50'}`}>
                <div className="font-medium mb-1">{t('{device} 試走到「{place}」', { device: dn(tried.device), place: tp.name })}</div>
                {!walk && proc && <div>{t('準備中:{now}', { now: proc.now || proc.sub_name })}</div>}
                {!walk && !proc && <div className="text-stone-500">{Date.now() / 1000 - tried.t > 20 ? t('沒有開始:看看「監看」頁的提醒(這台可能停下來了或正在做別的事)') : t('送出了,等它開始…')}</div>}
                {walk && walk.state === 'walking' && <div>{t('走路中… {s} 秒,看了 {n} 次地圖', { s: secs, n: walk.looks ?? 0 })}</div>}
                {walk && walk.state === 'walking' && !proc && <div className="text-stone-500">{t('(結束了,等最後結果…)')}</div>}
                {done && walk?.state === 'arrived' && <div className="text-green-800">{t('✓ 走到了,共 {s} 秒(看了 {n} 次地圖)。腳本裡用「走到地圖上的位置」選「{map} › {place}」就會走到這裡。', { s: secs, n: walk.looks ?? 0, map: m.label, place: tp.name })}</div>}
                {done && walk?.state === 'failed' && <div className="text-red-800">{t('✗ 沒走到({s} 秒):', { s: secs })}{WHY[walk.why ?? ''] ?? walk.message ?? ''}</div>}
                {walk?.state === 'walking' && proc && <div className="text-stone-500 mt-1">{proc.now}</div>}
              </div>
            )}
          </div>
        </div>
      </div>
    </Card>
  )
}

/** 走路設定: set once for the project - where to tap to open / close the big map, how "me" looks on it and where the map
 *  is on the screen, the direction control, what to do before / after walking */
function WalkSettingsCard({ s, loading, buttons, subs, devices, device }: {
  s?: WalkSettings; loading: boolean; buttons: LibButton[]; subs: { id: string; name: string }[]; devices: string[]; device: string
}) {
  const qc = useQueryClient()
  const [edit, setEdit] = useState<WalkSettings | null>(null)
  const save = useMutation({ mutationFn: (x: WalkSettings) => api.walkSettingsSave(x), onSuccess: () => { setEdit(null); qc.invalidateQueries({ queryKey: ['walksettings'] }) } })
  const ready = !!s?.me
  const bl = (p?: unknown) => { const id = (p as { button?: string } | undefined)?.button; return buttons.find(b => b.id === id)?.label ?? id ?? t('(沒設定)') }
  const sub = (id?: string) => id ? subs.find(x => x.id === id)?.name ?? id : t('(不用)')
  if (!edit) return (
    <Card title={t('走路設定')} extra={<Button variant={ready ? 'ghost' : 'primary'} disabled={loading} onClick={() => setEdit(JSON.parse(JSON.stringify(s ?? {})))}>{ready ? t('修改') : t('設定')}</Button>}>
      {ready ? <span className="text-xs text-stone-600">{t('每張地圖都一樣:打開地圖點「{open}」、關掉點「{close}」;走之前做「{before}」、走到之後做「{after}」。', { open: bl(s?.open), close: bl(s?.close), before: sub(s?.before), after: sub(s?.after) })}</span>
        : <span className="text-sm text-stone-600">{t('第一次用地圖要先設定一次:怎麼打開大地圖、地圖上的「自己」長什麼樣子、方向搖桿在哪。設定好之後,每張地圖都只要拍下來就能用。')}</span>}
    </Card>
  )
  const e = edit
  const set = (f: (x: WalkSettings) => void) => setEdit(x => { const y = JSON.parse(JSON.stringify(x)) as WalkSettings; f(y); return y })
  const me = e.me ?? { color: [210, 84, 50], tol: 40, min_px: 6, box: [Math.round(screen.w * 0.1), Math.round(screen.h * 0.2), Math.round(screen.w * 0.8), Math.round(screen.h * 0.6)] }
  const stick = e.stick ?? { x: Math.round(screen.w * 0.15), y: Math.round(screen.h * 0.8), r: 60 }
  const hex = '#' + me.color.map(c => Math.max(0, Math.min(255, c | 0)).toString(16).padStart(2, '0')).join('')
  const btnSel = (k: 'open' | 'close') => (
    <select className={`${input} max-w-60`} value={(e[k] as { button?: string } | undefined)?.button ?? ''} onChange={ev => set(x => { x[k] = ev.target.value ? { button: ev.target.value } : undefined })}>
      <option value="">{t('(選一個按鈕)')}</option>{buttons.filter(b => !b.list).map(b => <option key={b.id} value={b.id}>{b.label}</option>)}
    </select>)
  const subSel = (k: 'before' | 'after') => (
    <select className={`${input} max-w-60`} value={e[k] ?? ''} onChange={ev => set(x => { x[k] = ev.target.value || undefined })}>
      <option value="">{t('(不用)')}</option>{subs.map(x => <option key={x.id} value={x.id}>{x.name}</option>)}
    </select>)
  return (
    <Card title={t('走路設定')} extra={<span className="flex gap-2"><Button variant="ghost" onClick={() => setEdit(null)}>{t('取消')}</Button>
      <Button variant="primary" disabled={save.isPending} onClick={() => save.mutate({ ...e, me, stick })}>{t('儲存')}</Button></span>}>
      <div className="flex flex-col gap-2 text-sm">
        <ErrorText error={save.error} />
        <span className="flex flex-wrap items-center gap-2">{t('打開大地圖:點')}{btnSel('open')}{t('關掉大地圖:點')}{btnSel('close')}</span>
        <span className="flex flex-wrap items-center gap-2">{t('走之前先做')}{subSel('before')}{t('走到之後做')}{subSel('after')}</span>
        <ScreenPicker devices={devices} device={device} me={me} stick={stick}
          onColor={(c, size) => set(x => { x.me = { ...me, color: c, size } })} onBox={b => set(x => { x.me = { ...me, box: b } })} onStick={(px, py) => set(x => { x.stick = { ...stick, x: px, y: py } })} />
        <span className="flex flex-wrap items-center gap-2 text-xs text-stone-600">
          {t('「自己」的顏色')}<input type="color" value={hex} onChange={ev => { const h = ev.target.value; set(x => { x.me = { ...me, color: [1, 3, 5].map(i => parseInt(h.slice(i, i + 2), 16)) } }) }} />
          {me.size ? <span className="num">{t('「自己」大小 {n} 點', { n: me.size })}</span> : null}
          <span className="num">{t('地圖範圍 {x}, {y}, {w}×{h}', { x: me.box[0], y: me.box[1], w: me.box[2], h: me.box[3] })}</span>
          <span className="num">{t('搖桿中心 {x}, {y}', { x: stick.x, y: stick.y })}</span>
          {t('搖桿半徑')}<input type="number" className={`${input} w-16 num`} value={stick.r} onChange={ev => set(x => { x.stick = { ...stick, r: Number(ev.target.value) } })} />
        </span>
      </div>
    </Card>
  )
}

/** the picture of the screen (screen size) as pixels */
function screenPixels(im: HTMLImageElement): ImageData {
  const c = document.createElement('canvas'); c.width = screen.w; c.height = screen.h
  const g = c.getContext('2d')!; g.drawImage(im, 0, 0, screen.w, screen.h)
  return g.getImageData(0, 0, screen.w, screen.h)
}

/** the colour of the marker clicked: the most vivid pixel within 4 px of the click (a marker is drawn in a strong
 *  colour; its edges blend into the map, so the exact pixel clicked may be a paler one) */
function pixelAt(im: HTMLImageElement, x: number, y: number): number[] {
  const d = screenPixels(im)
  let best = [0, 0, 0], vivid = -1
  for (let dy = -4; dy <= 4; dy++) for (let dx = -4; dx <= 4; dx++) {
    const px = x + dx, py = y + dy
    if (px < 0 || py < 0 || px >= screen.w || py >= screen.h) continue
    const i = (py * screen.w + px) * 4, c = [d.data[i], d.data[i + 1], d.data[i + 2]]
    const v = Math.max(...c) - Math.min(...c)
    if (v > vivid) { vivid = v; best = c }
  }
  return best
}

/** how many pixels "me" has where it was clicked: its colour (within tol), pieces up to 4 px apart counted as one
 *  patch (as the walk sees it) - so an icon of the same colour but another size is not taken for "me" */
function meSize(im: HTMLImageElement, x: number, y: number, c: number[], tol: number): number | undefined {
  const d = screenPixels(im), W = screen.w, H = screen.h, R = 40, J = 4
  const ok = (px: number, py: number) => { const i = (py * W + px) * 4; return Math.max(Math.abs(d.data[i] - c[0]), Math.abs(d.data[i + 1] - c[1]), Math.abs(d.data[i + 2] - c[2])) <= tol }
  const seen = new Set<number>(), todo: [number, number][] = []
  for (let dy = -J; dy <= J && !todo.length; dy++) for (let dx = -J; dx <= J; dx++) {
    const px = x + dx, py = y + dy
    if (px >= 0 && py >= 0 && px < W && py < H && ok(px, py)) { todo.push([px, py]); seen.add(py * W + px); break }
  }
  while (todo.length) {
    const [px, py] = todo.pop()!
    for (let dy = -J; dy <= J; dy++) for (let dx = -J; dx <= J; dx++) {
      const qx = px + dx, qy = py + dy, k = qy * W + qx
      if (qx < 0 || qy < 0 || qx >= W || qy >= H || Math.abs(qx - x) > R || Math.abs(qy - y) > R || seen.has(k) || !ok(qx, qy)) continue
      seen.add(k); todo.push([qx, qy])
    }
  }
  return seen.size >= 3 ? seen.size : undefined
}

/** on a picture of the device: click "me" (its colour), drag the map's part of the screen (no fixed buttons or names in
 *  it: they do not move with the map), click the middle of the direction control */
function ScreenPicker({ devices, device, me, stick, onColor, onBox, onStick }: {
  devices: string[]; device: string; me: { color: number[]; box: number[]; tol?: number }; stick: { x: number; y: number; r: number }
  onColor: (c: number[], size?: number) => void; onBox: (b: number[]) => void; onStick: (x: number, y: number) => void
}) {
  const [dev, setDev] = useState(device)
  const [mode, setMode] = useState<'color' | 'box' | 'stick'>('color')
  const snap = useMutation({ mutationFn: () => api.buttonSnap(dev) })
  const cv = useRef<HTMLCanvasElement>(null)
  const img = useRef<HTMLImageElement | null>(null)
  const [loaded, setLoaded] = useState(0)
  const [drag, setDrag] = useState<[number, number] | null>(null)
  useEffect(() => { if (!snap.data) return; const im = new Image(); im.onload = () => { img.current = im; setLoaded(x => x + 1) }; im.src = buttonSnapUrl(snap.data.device, snap.data.updated) }, [snap.data])
  useEffect(() => {
    const c = cv.current, im = img.current
    if (!c || !im) return
    c.width = screen.w; c.height = screen.h
    const g = c.getContext('2d')!
    g.drawImage(im, 0, 0, screen.w, screen.h)
    g.strokeStyle = '#38bdf8'; g.lineWidth = 3; g.strokeRect(me.box[0], me.box[1], me.box[2], me.box[3])
    g.strokeStyle = '#a855f7'; g.beginPath(); g.arc(stick.x, stick.y, stick.r, 0, Math.PI * 2); g.stroke()
  }, [loaded, me.box.join(), stick.x, stick.y, stick.r])
  const at = (ev: React.MouseEvent): [number, number] => {
    const r = cv.current!.getBoundingClientRect()
    return [Math.round(((ev.clientX - r.left) / r.width) * screen.w), Math.round(((ev.clientY - r.top) / r.height) * screen.h)]
  }
  const tool = (k: typeof mode, tx: string) => <button className={`px-2 py-1 rounded border text-xs ${mode === k ? 'bg-stone-800 text-white border-stone-800' : 'border-stone-300'}`} onClick={() => setMode(k)}>{tx}</button>
  return (
    <div className="flex flex-col gap-1 text-xs">
      <div className="flex flex-wrap items-center gap-2">
        <DeviceSelect devices={devices} device={dev} setDevice={setDev} />
        <Button onClick={() => snap.mutate()} disabled={!dev || snap.isPending}>{snap.isPending ? t('擷取中…') : t('擷取這台現在的畫面(大地圖打開)')}</Button>
        {snap.data && <>{tool('color', t('點「自己」'))}{tool('box', t('拖出地圖範圍'))}{tool('stick', t('點搖桿中心'))}</>}
      </div>
      <ErrorText error={snap.error} />
      {snap.data && <span className="text-stone-500">{mode === 'color' ? t('點地圖上代表自己的記號,取它的顏色') : mode === 'box' ? t('拖出大地圖的範圍(藍框);不要框到固定不動的按鈕或文字') : t('點方向搖桿的中心(紫圈)')}</span>}
      {snap.data && <div className="relative w-full max-w-3xl aspect-video bg-stone-900 rounded-md overflow-hidden cursor-crosshair select-none">
        <canvas ref={cv} className="absolute inset-0 w-full h-full"
          onMouseDown={ev => { const p = at(ev); if (mode === 'box') setDrag(p); else if (mode === 'stick') onStick(p[0], p[1]); else { const im = img.current; if (im) { const c = pixelAt(im, p[0], p[1]); onColor(c, meSize(im, p[0], p[1], c, me.tol ?? 40)) } } }}
          onMouseMove={ev => { if (drag) { const [x, y] = at(ev); onBox([Math.min(drag[0], x), Math.min(drag[1], y), Math.abs(x - drag[0]), Math.abs(y - drag[1])]) } }}
          onMouseUp={() => setDrag(null)} onMouseLeave={() => setDrag(null)} />
      </div>}
    </div>
  )
}
