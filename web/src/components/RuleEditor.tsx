import { t } from '../i18n'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { api, imageUrl, ruleTemplateUrl, type AnswerValue, type HsvRange, type RatioSuggestion, type RulePreviewItem, type RuleTemplate, type StateDef } from '../api'
import { COLORS } from '../lib/schema'
import { Zoom } from './FrameView'
import QuickAnswers from './QuickAnswers'
import { Button, Card, Empty, ErrorText } from './ui'
import { words } from '../lib/project'

/**
 * Editor for the two generic screen rules (labeler/generic.py):
 *   color_ratio — share of pixels of chosen colours inside a region, two thresholds
 *   template    — reference crops per class, the most similar class wins
 * Colours use Pillow's HSV scale (0-255 for hue, saturation and value).
 */
const input = 'border border-stone-300 rounded-md px-2 py-1 text-sm bg-white'

export const RULE_KINDS: Record<string, { name: string; desc: string }> = {
  color_ratio: { name: t('顏色比例'), desc: t('數範圍內某種顏色的像素佔多少。適合:亮/暗、有沒有發光、有沒有某種顏色的圖示或數字。') },
  template: { name: t('參考圖比對'), desc: t('每個類別存幾張參考圖,看範圍內的畫面最像哪一張。適合:形狀、圖示、文字、面板的樣子。') },
  digits: { name: t('讀數字'), desc: t('讀出範圍內的數字(例如 1250/2000、庫存 12,500)。點選數字的顏色,再教它每個字元長怎樣。') },
  bar: { name: t('長條比例'), desc: t('量長條填滿了多少(例如進度條、水位、電量)。長條換顏色(變紅、變灰)也量得到。') },
}
/** which rule kinds a state type can use */
const KINDS_FOR: Record<string, string[]> = { class: ['color_ratio', 'template'], number: ['digits'], ratio: ['bar'] }
const BAR_DIRS: Record<string, string> = { right: t('由左往右填滿'), left: t('由右往左填滿'), up: t('由下往上填滿'), down: t('由上往下填滿') }
const PARTS: Record<string, string> = { all: t('整段數字'), left: t('「/」左邊(例如 1250/2000 的 1250)'), right: t('「/」右邊') }

export function defaultParams(kind: string, s: StateDef): Record<string, any> {
  const roi = s.review?.roi ?? s.rois[0]?.id
  const v = (s.classes ?? []).map(c => c.value)
  return kind === 'color_ratio'
    ? { roi, colors: [], high_value: v[0], high_min: 0.1, low_value: v[1] ?? v[0], low_max: 0.02 }
    : kind === 'digits' ? { roi, colors: [], part: 'all', match_min: 0.6 }
    : kind === 'bar' ? { roi, dir: 'right', fill: 'auto', slant: 0 }
    : { roi, feature: 'gray', match_min: 0.6, margin: 0.05, search: 3 }
}

// ---------- colour helpers (same conversion as Pillow's RGB -> HSV) ----------
function rgbToHsv(r: number, g: number, b: number): [number, number, number] {
  const mx = Math.max(r, g, b), mn = Math.min(r, g, b), d = mx - mn
  let h = 0
  if (d) {
    if (mx === r) h = ((g - b) / d) % 6
    else if (mx === g) h = (b - r) / d + 2
    else h = (r - g) / d + 4
    h = (h / 6 + 1) % 1
  }
  return [Math.round(h * 255), mx ? Math.round((d / mx) * 255) : 0, mx]
}
const inRange = (v: number, [lo, hi]: [number, number]) => (lo <= hi ? v >= lo && v <= hi : v >= lo || v <= hi)
const matches = (hsv: [number, number, number], colors: HsvRange[]) =>
  colors.some(c => inRange(hsv[0], c.h) && hsv[1] >= c.s[0] && hsv[1] <= c.s[1] && hsv[2] >= c.v[0] && hsv[2] <= c.v[1])
const hueCss = (h: number, s = 200, v = 220) => `hsl(${Math.round((h / 255) * 360)}, ${Math.round((s / 255) * 100)}%, ${Math.round((v / 255) * 55)}%)`
function hueGradient(c: HsvRange) {
  const [lo, hi] = c.h
  const span = lo <= hi ? hi - lo : 255 - lo + hi
  const stops = Array.from({ length: 7 }, (_, i) => hueCss((lo + (span * i) / 6) % 256, (c.s[0] + c.s[1]) / 2, (c.v[0] + c.v[1]) / 2))
  return `linear-gradient(90deg, ${stops.join(',')})`
}

export function RuleEditor({ s, all, onChange }: { s: StateDef; all: StateDef[]; onChange: (fn: (s: StateDef) => void) => void }) {
  const kind = s.source.rule
  const p = s.source.params ?? {}
  const setP = (k: string, v: any) => onChange(x => { x.source.params = { ...(x.source.params ?? {}), [k]: v } })
  const roi = s.rois.find(r => r.id === p.roi) ?? s.rois[0]
  const idx = all.indexOf(s)
  // states answered before this one: the plugins' rules (they run first), then generic rules defined above it
  const gates = [...all.filter(x => x !== s && x.source.kind === 'rule' && x.source.rule && !RULE_KINDS[x.source.rule]),
    ...all.slice(0, idx).filter(x => x.source.kind === 'rule' && x.source.rule && RULE_KINDS[x.source.rule])].map(x => ({ id: x.id, name: x.name }))

  const kinds = KINDS_FOR[s.type] ?? []
  if (!kinds.length) return <Card title={t('規則設定')}><Empty>{t('通用規則只能用在「分類」「數值」或「比例」類型的狀態')}</Empty></Card>
  return (
    <Card title={t('規則設定')} extra={<span className="text-xs text-stone-500">{t('儲存後到「自動標註」按「產生標籤」才會套用')}</span>}>
      <div className="flex flex-col gap-5 text-sm">
        <div className="grid md:grid-cols-2 gap-3">
          {Object.entries(RULE_KINDS).filter(([k]) => kinds.includes(k)).map(([k, d]) => (
            <button key={k} onClick={() => onChange(x => { x.source.rule = k; x.source.params = defaultParams(k, x) })}
              className={`text-left rounded-md border p-3 ${kind === k ? 'border-stone-800 bg-stone-100' : 'border-stone-200 hover:bg-stone-50'}`}>
              <div className="font-medium">{d.name}</div>
              <div className="text-xs text-stone-500 mt-0.5">{d.desc}</div>
            </button>
          ))}
        </div>
        {kind && RULE_KINDS[kind] && roi && (
          <>
            <div className="flex flex-wrap gap-x-6 gap-y-2 items-center">
              <label className="flex items-center gap-2">{t('看哪個範圍')}
                <select className={input} value={roi.id} onChange={e => setP('roi', e.target.value)}>
                  {s.rois.map(r => <option key={r.id} value={r.id}>{r.name}</option>)}
                </select></label>
              <label className="flex items-center gap-2">{t('先決條件')}
                <select className={input} value={p.gate_state ?? ''} onChange={e => setP('gate_state', e.target.value || undefined)}>
                  <option value="">{t('無')}</option>
                  {gates.map(g => <option key={g.id} value={g.id}>{t('「{name}」看不到時,這個也算看不到', { name: g.name })}</option>)}
                </select></label>
            </div>
            {kind === 'color_ratio' ? <ColorRule s={s} box={roi.box} setP={setP} />
              : kind === 'digits' ? <DigitsRule s={s} box={roi.box} setP={setP} />
              : kind === 'bar' ? <BarRule s={s} box={roi.box} setP={setP} />
              : <TemplateRule s={s} box={roi.box} setP={setP} />}
            {kind !== 'digits' && kind !== 'bar' && <QuickAnswers s={s} box={roi.box} pad={kind === 'template' ? Number(p.search ?? 3) : 0} />}
          </>
        )}
      </div>
    </Card>
  )
}

// ================================================================ colour ratio
/** Frames to look at + the colour ranges of a rule (click a pixel to add one). */
function ColorSection({ s, box, setP, title, hint, frame, frames, pick, setPick, reseed }: {
  s: StateDef; box: number[]; setP: (k: string, v: any) => void; title: string; hint: ReactNode
  frame?: string; frames?: string[]; pick: number; setPick: (i: number) => void; reseed: () => void
}) {
  // a color without a hue range (h) takes any hue (e.g. white digits)
  const colors: HsvRange[] = ((s.source.params?.colors ?? []) as Partial<HsvRange>[]).map(c => ({ h: [0, 255], s: [0, 255], v: [0, 255], ...c }) as HsvRange)
  const updColor = (i: number, k: keyof HsvRange, j: 0 | 1, v: number) => {
    const n = colors.map(c => ({ ...c, [k]: [...c[k]] as [number, number] }))
    n[i][k][j] = Math.max(0, Math.min(255, Math.round(v)))
    setP('colors', n)
  }
  return (
      <section className="flex flex-col gap-2">
        <div className="font-medium text-stone-700">{title}</div>
        <p className="text-xs text-stone-500">{hint}</p>
        <div className="grid xl:grid-cols-[1fr_360px] gap-4">
          <div className="flex flex-col gap-2">
            <div className="flex gap-1 flex-wrap">
              {frames?.map((f, i) => (
                <button key={f} onClick={() => setPick(i)} className={`rounded border-2 ${i === pick ? 'border-amber-500' : 'border-transparent'}`}>
                  <Zoom frame={f} box={box} scale={1} maxWidth={90} />
                </button>
              ))}
              <Button variant="ghost" onClick={reseed}>{t('換一批')}</Button>
            </div>
            {frame && <Picker frame={frame} box={box} colors={colors} onPick={c => setP('colors', [...colors, c])} />}
          </div>
          <div className="flex flex-col gap-2">
            {colors.length === 0 && <div className="text-xs text-stone-500">{t('還沒有顏色')}</div>}
            {colors.map((c, i) => (
              <div key={i} className="border border-stone-200 rounded-md p-2 flex flex-col gap-1.5">
                <div className="flex items-center gap-2">
                  <div className="h-4 flex-1 rounded" style={{ background: hueGradient(c) }} />
                  <button className="text-xs text-stone-500 underline" onClick={() => setP('colors', colors.filter((_, j) => j !== i))}>{t('移除')}</button>
                </div>
                {([['h', t('色相')], ['s', t('飽和度')], ['v', t('亮度')]] as const).map(([k, label]) => (
                  <div key={k} className="flex items-center gap-1.5 text-xs">
                    <span className="w-12 text-stone-500">{label}</span>
                    <input type="number" className={`${input} w-16 num py-0.5`} value={c[k][0]} onChange={e => updColor(i, k, 0, Number(e.target.value))} />
                    <span>~</span>
                    <input type="number" className={`${input} w-16 num py-0.5`} value={c[k][1]} onChange={e => updColor(i, k, 1, Number(e.target.value))} />
                  </div>
                ))}
              </div>
            ))}
            <p className="text-[11px] text-stone-500">{t('數值都是 0~255。色相:0 紅、43 黃、85 綠、170 藍;起點比終點大表示跨過紅色(例如 245~10)。飽和度低 = 偏灰白;亮度低 = 偏暗。')}</p>
          </div>
        </div>
      </section>
  )
}

function ColorRule({ s, box, setP }: { s: StateDef; box: number[]; setP: (k: string, v: any) => void }) {
  const p = s.source.params ?? {}
  const classes = s.classes ?? []
  const [seed, setSeed] = useState(1)
  const frames = useQuery({ queryKey: ['randomFrames', 'rule', seed], queryFn: () => api.randomFrames(12, seed) })
  const [pick, setPick] = useState(0)
  const valueSelect = (k: 'high_value' | 'low_value') => (
    <select className={input} value={JSON.stringify(p[k])} onChange={e => setP(k, JSON.parse(e.target.value))}>
      {classes.map(c => <option key={String(c.value)} value={JSON.stringify(c.value)}>{c.name}</option>)}
    </select>
  )

  return (
    <div className="flex flex-col gap-5">
      <ColorSection s={s} box={box} setP={setP} title={t('1. 要數的顏色')} frame={frames.data?.[pick]} frames={frames.data} pick={pick} setPick={setPick}
        reseed={() => setSeed(v => v + 1)}
        hint={<>{t('在下方放大圖上')}<b>{t('點一下')}</b>{t('想數的顏色,會自動加入一個範圍。勾「標出符合的像素」可以看到哪些像素會被算進去(粉紅色)。')}</>} />

      <section className="flex flex-col gap-2">
        <div className="font-medium text-stone-700">{t('2. 門檻')}</div>
        <div className="flex flex-wrap gap-x-6 gap-y-2 items-center">
          <span className="flex items-center gap-2">{t('比例 ≥')}
            <input type="number" step={0.01} className={`${input} w-20 num`} value={p.high_min ?? ''} onChange={e => setP('high_min', Number(e.target.value))} />
            → {valueSelect('high_value')}</span>
          <span className="flex items-center gap-2">{t('比例 ≤')}
            <input type="number" step={0.01} className={`${input} w-20 num`} value={p.low_max ?? ''} onChange={e => setP('low_max', Number(e.target.value))} />
            → {valueSelect('low_value')}</span>
          <span className="text-stone-500">{t('中間 → 無法判斷(不拿來訓練)')}</span>
        </div>
      </section>

      <RatioAnalysis s={s} box={box} setP={setP} />
    </div>
  )
}

/** Zoomed region drawn on a canvas: click a pixel to add a colour range around it; optionally highlight matches. */
function Picker({ frame, box, colors, onPick }: { frame: string; box: number[]; colors: HsvRange[]; onPick: (c: HsvRange) => void }) {
  const ref = useRef<HTMLCanvasElement>(null)
  const pixels = useRef<ImageData | null>(null)
  const [show, setShow] = useState(true)
  const [ratio, setRatio] = useState(0)
  const [hover, setHover] = useState<{ rgb: number[]; hsv: [number, number, number] } | null>(null)
  const [x, y, w, h] = box
  const scale = Math.max(1, Math.min(8, Math.floor(560 / w)))

  useEffect(() => {
    const img = new Image()
    img.onload = () => {
      const off = document.createElement('canvas')
      off.width = w; off.height = h
      const octx = off.getContext('2d')!
      octx.drawImage(img, x, y, w, h, 0, 0, w, h)
      pixels.current = octx.getImageData(0, 0, w, h)
      draw()
    }
    img.src = imageUrl(frame)
  }, [frame, x, y, w, h]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { draw() }, [colors, show]) // eslint-disable-line react-hooks/exhaustive-deps

  function draw() {
    const cv = ref.current, px = pixels.current
    if (!cv || !px) return
    const ctx = cv.getContext('2d')!
    const out = ctx.createImageData(w * scale, h * scale)
    let hit = 0
    for (let j = 0; j < h; j++) for (let i = 0; i < w; i++) {
      const k = (j * w + i) * 4
      let [r, g, b] = [px.data[k], px.data[k + 1], px.data[k + 2]]
      const m = colors.length > 0 && matches(rgbToHsv(r, g, b), colors)
      if (m) hit++
      if (m && show) [r, g, b] = [255, 0, 200]
      for (let dy = 0; dy < scale; dy++) for (let dx = 0; dx < scale; dx++) {
        const o = ((j * scale + dy) * w * scale + i * scale + dx) * 4
        out.data[o] = r; out.data[o + 1] = g; out.data[o + 2] = b; out.data[o + 3] = 255
      }
    }
    ctx.putImageData(out, 0, 0)
    setRatio(hit / (w * h))
  }
  const at = (e: React.MouseEvent) => {
    const r = ref.current!.getBoundingClientRect()
    const i = Math.floor(((e.clientX - r.left) / r.width) * w), j = Math.floor(((e.clientY - r.top) / r.height) * h)
    const px = pixels.current
    if (!px || i < 0 || j < 0 || i >= w || j >= h) return null
    const k = (j * w + i) * 4
    const rgb = [px.data[k], px.data[k + 1], px.data[k + 2]]
    return { rgb, hsv: rgbToHsv(rgb[0], rgb[1], rgb[2]) }
  }

  return (
    <div className="flex flex-col gap-1">
      <canvas ref={ref} width={w * scale} height={h * scale} className="rounded border border-stone-300 cursor-crosshair max-w-full"
        style={{ imageRendering: 'pixelated' }}
        onMouseMove={e => setHover(at(e))} onMouseLeave={() => setHover(null)}
        onClick={e => {
          const p = at(e)
          if (!p) return
          const [hh, ss, vv] = p.hsv
          onPick({ h: [(hh - 10 + 256) % 256, (hh + 10) % 256], s: [Math.max(0, ss - 70), 255], v: [Math.max(0, vv - 70), 255] })
        }} />
      <div className="flex flex-wrap gap-4 text-xs text-stone-600 items-center">
        <label className="flex items-center gap-1"><input type="checkbox" checked={show} onChange={e => setShow(e.target.checked)} />{t('標出符合的像素')}</label>
        <span>{t('這張的比例')} <b className="num">{(ratio * 100).toFixed(1)}%</b></span>
        {hover && <span className="flex items-center gap-1 num">
          <span className="w-3 h-3 rounded-sm border border-stone-300" style={{ background: `rgb(${hover.rgb.join(',')})` }} />
          {t('色相 {p1} · 飽和度 {p2} · 亮度 {p3}', { p1: hover.hsv[0], p2: hover.hsv[1], p3: hover.hsv[2] })}</span>}
      </div>
    </div>
  )
}

/** Run the rule on many frames: histogram of ratios with the thresholds, click a bar to see those frames. */
function RatioAnalysis({ s, box, setP }: { s: StateDef; box: number[]; setP: (k: string, v: any) => void }) {
  const p = s.source.params ?? {}
  const run = useMutation({ mutationFn: (seed: number) => api.rulesPreview(s, 200, seed) })
  const [bin, setBin] = useState<number | null>(null)
  const items = run.data?.items ?? []
  const ratios = items.map(i => i.ratio ?? 0)
  const max = Math.max(0.05, ...ratios)
  const N = 40
  const bins = useMemo(() => {
    const b: RulePreviewItem[][] = Array.from({ length: N }, () => [])
    items.forEach(it => { if (!it.gated) b[Math.min(N - 1, Math.floor(((it.ratio ?? 0) / max) * N))].push(it) })
    return b
  }, [items, max])
  const top = Math.max(1, ...bins.map(b => b.length))
  const W = 640, H = 140
  const xOf = (r: number) => (r / max) * W
  const count = (v: AnswerValue | null) => items.filter(i => i.value === v).length
  const name = (v: AnswerValue | null) => v == null ? t('無法判斷') : s.classes?.find(c => c.value === v)?.name ?? String(v)
  const sug = run.data?.suggest
  const answered = items.filter(i => i.answer != null).length

  return (
    <section className="flex flex-col gap-2">
      <div className="flex items-center gap-3 flex-wrap">
        <div className="font-medium text-stone-700">{t('3. 用 200 張畫面檢查')}{answered > 0 && <span className="font-normal text-xs text-stone-500">{t('(另外加上你回答過的 {n} 張)', { n: answered })}</span>}</div>
        <Button onClick={() => { setBin(null); run.mutate(Date.now() % 1000) }} disabled={run.isPending || !(p.colors?.length)}>{run.isPending ? t('計算中…') : t('分析')}</Button>
        <span className="text-xs text-stone-500">{t('理想的樣子:長條分成左右兩群,中間空空的。門檻設在空的地方。')}</span>
      </div>
      <ErrorText error={run.error} />
      {items.length > 0 && (
        <>
          <svg viewBox={`0 0 ${W} ${H + 18}`} className="w-full max-w-3xl border border-stone-200 rounded bg-white">
            {bins.map((b, i) => b.length > 0 && (
              <rect key={i} x={(i / N) * W + 1} width={W / N - 2} y={H - (b.length / top) * (H - 10)} height={(b.length / top) * (H - 10)}
                fill={bin === i ? '#f59e0b' : '#78716c'} className="cursor-pointer" onClick={() => setBin(i)}>
                <title>{t('{p1}%~{p2}%:{length} 張', { p1: ((i / N) * max * 100).toFixed(1), p2: (((i + 1) / N) * max * 100).toFixed(1), length: b.length })}</title>
              </rect>
            ))}
            {p.low_max != null && <line x1={xOf(p.low_max)} x2={xOf(p.low_max)} y1={0} y2={H} stroke="#e11d48" strokeDasharray="4 3" />}
            {p.high_min != null && <line x1={xOf(p.high_min)} x2={xOf(p.high_min)} y1={0} y2={H} stroke="#059669" strokeDasharray="4 3" />}
            {sug && !sug.none && <rect x={xOf(sug.low_max)} width={Math.max(1, xOf(sug.high_min) - xOf(sug.low_max))} y={0} height={H} fill="#0284c7" opacity={0.12}>
              <title>{t('建議的門檻之間(判斷不出來的範圍)')}</title></rect>}
            <text x={2} y={H + 14} fontSize="11" fill="#78716c">0%</text>
            <text x={W - 2} y={H + 14} fontSize="11" fill="#78716c" textAnchor="end">{(max * 100).toFixed(1)}%</text>
          </svg>
          <div className="flex flex-wrap gap-3 text-xs text-stone-600">
            {[...(s.classes ?? []).map(c => c.value), null].map(v => <span key={String(v)}>{name(v)} <b className="num">{count(v)}</b></span>)}
            {items.some(i => i.gated) && <span>{t('(先決條件擋下 {length} 張)', { length: items.filter(i => i.gated).length })}</span>}
            <span className="text-stone-400">{t('紅線 = 低門檻,綠線 = 高門檻;點長條看那些畫面')}</span>
          </div>
          {sug && <Suggestion sug={sug} name={name} high={p.high_value} low={p.low_value} same={!sug.none && p.low_max === sug.low_max && p.high_min === sug.high_min}
            apply={() => { if (!sug.none) { setP('low_max', sug.low_max); setP('high_min', sug.high_min) } }} />}
          {bin !== null && (
            <div className="flex flex-col gap-1">
              <div className="flex gap-3 items-center text-xs text-stone-600">
                {t('比例 {p1}%~{p2}% 的畫面', { p1: ((bin / N) * max * 100).toFixed(1), p2: (((bin + 1) / N) * max * 100).toFixed(1) })}
                <button className="underline" onClick={() => setP('high_min', +((bin / N) * max).toFixed(3))}>{t('高門檻設在這裡')}</button>
                <button className="underline" onClick={() => setP('low_max', +(((bin + 1) / N) * max).toFixed(3))}>{t('低門檻設在這裡')}</button>
              </div>
              <PreviewGrid s={s} box={box} items={bins[bin].slice(0, 24)} />
            </div>
          )}
        </>
      )}
    </section>
  )
}

/** The thresholds the analysis suggests, what they would make of these frames, and a button to take them. */
function Suggestion({ sug, name, high, low, same, apply }: { sug: RatioSuggestion; name: (v: AnswerValue | null) => string
  high: AnswerValue; low: AnswerValue; same: boolean; apply: () => void }) {
  if (sug.none) return <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">{{
    one_group: t('建議不出門檻:這些畫面的比例都在同一群。錄到的畫面可能還沒有另一種狀況(先錄一段有的),或換一種顏色、縮小範圍。'),
    few_frames: t('建議不出門檻:畫面太少(至少要 10 張)。'),
    answers_mixed: t('建議不出門檻:你的答案兩種的比例混在一起分不開。試試換一種顏色或縮小範圍。'),
  }[sug.none]}</div>
  const pct = (v: number) => `${+(v * 100).toPrecision(2)}%`
  return (
    <div className="rounded-md border border-sky-200 bg-sky-50 px-3 py-2 text-sm text-sky-950 flex flex-wrap items-center gap-x-4 gap-y-1" data-testid="suggestion">
      <b>{t('建議門檻')}</b>
      <span className="num">{t('比例 ≥ {high}→{hv},≤ {low}→{lv}', { high: sug.high_min, hv: name(high), low: sug.low_max, lv: name(low) })}
        <span className="text-sky-800/70">{` (${pct(sug.high_min)} / ${pct(sug.low_max)})`}</span></span>
      <span className="text-xs text-sky-800">{sug.basis === 'answers' ? t('依你回答過的畫面:答案都不會判錯') : t('依畫面比例的分佈:兩群中間空的地方')}</span>
      <span className="text-xs num">{t('這些畫面會是:{hv} {h} 張、{lv} {l} 張、判斷不出 {u} 張', { hv: name(high), h: sug.high, lv: name(low), l: sug.low, u: sug.unsure })}
        {sug.basis === 'answers' && sug.unsure_answers > 0 && t(';你的答案有 {n} 張在中間,會判斷不出來', { n: sug.unsure_answers })}</span>
      <Button variant={same ? 'ghost' : 'primary'} disabled={same} onClick={apply}>{same ? t('已套用') : t('套用建議')}</Button>
    </div>
  )
}

// ================================================================ bar (長條比例)
/** How full a bar is: the region is the whole bar (0% -> 100%); its fill colour is read where it starts. */
function BarRule({ s, box, setP }: { s: StateDef; box: number[]; setP: (k: string, v: any) => void }) {
  const p = s.source.params ?? {}
  const [seed, setSeed] = useState(1)
  const frames = useQuery({ queryKey: ['randomFrames', 'rule', seed], queryFn: () => api.randomFrames(12, seed), enabled: p.fill === 'colors' })
  const [pick, setPick] = useState(0)
  const [adv, setAdv] = useState(false)
  const prev = useMutation({ mutationFn: (sd: number) => api.rulesPreview(s, 24, sd) })
  const horizontal = (p.dir ?? 'right') === 'right' || p.dir === 'left'
  return (
    <div className="flex flex-col gap-5">
      <section className="flex flex-col gap-2">
        <div className="font-medium text-stone-700">{t('1. 長條的範圍與方向')}</div>
        <p className="text-xs text-stone-500">{t('上面選的範圍要框住')}<b>{t('整條長條')}</b>{t(':從開始填的那一端(0%)到全滿的那一端(100%),只框長條本身,不要框到外框。')}</p>
        <div className="flex flex-wrap gap-x-6 gap-y-2 items-center">
          <label className="flex items-center gap-2">{t('填滿的方向')}
            <select className={input} value={p.dir ?? 'right'} onChange={e => setP('dir', e.target.value)}>
              {Object.entries(BAR_DIRS).map(([k, tx]) => <option key={k} value={k}>{tx}</option>)}
            </select></label>
          <label className="flex items-center gap-2" title={horizontal ? t('長條是斜的(平行四邊形)時:最上面一列比最下面一列往填滿方向偏幾個像素;範圍框最下面一列的位置') : t('長條是斜的時:最左一行比最右一行往填滿方向偏幾個像素')}>
            {t('傾斜')}<input type="number" min={-200} max={200} className={`${input} w-20 num`} value={p.slant ?? 0} onChange={e => setP('slant', Number(e.target.value) || 0)} />{t('像素')}
            <span className="text-xs text-stone-500">{t('(不斜填 0)')}</span></label>
        </div>
      </section>
      <section className="flex flex-col gap-2">
        <div className="font-medium text-stone-700">{t('2. 填滿的顏色')}</div>
        <div className="flex flex-wrap gap-4">
          <label className="flex items-center gap-1.5"><input type="radio" checked={(p.fill ?? 'auto') === 'auto'} onChange={() => setP('fill', 'auto')} />
            {t('自動:看長條開頭的顏色')}<span className="text-xs text-stone-500">{t('(長條會換顏色時用這個,例如警告時變紅)')}</span></label>
          <label className="flex items-center gap-1.5"><input type="radio" checked={p.fill === 'colors'} onChange={() => setP('fill', 'colors')} />{t('指定顏色')}</label>
        </div>
        {p.fill === 'colors' && <ColorSection s={s} box={box} setP={setP} title={t('填滿部分的顏色')} frame={frames.data?.[pick]} frames={frames.data} pick={pick} setPick={setPick}
          reseed={() => setSeed(v => v + 1)} hint={<>{t('在放大圖上點')}<b>{t('長條填滿的部分')}</b>{t('加入它的顏色;長條會變色的話,每種顏色都點一下。')}</>} />}
        <button className="self-start text-xs text-stone-600 underline" onClick={() => setAdv(v => !v)}>{adv ? t('收起進階設定') : t('進階設定…')}</button>
        {adv && <div className="flex flex-wrap gap-x-6 gap-y-2 items-center text-sm">
          <label className="flex items-center gap-2" title={t('填滿的部分要多鮮豔(和開頭比);很多長條空的部分是同一個顏色,只是比較淡或比較暗')}>{t('至少要有開頭的')}
            <input type="number" step={0.05} min={0.3} max={1} className={`${input} w-20 num`} value={p.min_vivid ?? 0.75} onChange={e => setP('min_vivid', Number(e.target.value))} />{t('倍鮮豔')}</label>
          <label className="flex items-center gap-1.5" title={t('長條上的白色或淡色文字(例如 45 / 100)不算填滿也不算空的')}>
            <input type="checkbox" checked={p.ignore_text ?? true} onChange={e => setP('ignore_text', e.target.checked)} />{t('略過長條上的白字')}</label>
          <label className="flex items-center gap-2">{t('開頭是暗的時候')}
            <select className={input} value={p.dark_start ?? 'unsure'} onChange={e => setP('dark_start', e.target.value)}>
              <option value="unsure">{t('先不判斷(可能是畫面變暗)')}</option><option value="empty">{t('當作 0%(空的)')}</option>
            </select></label>
        </div>}
      </section>
      <section className="flex flex-col gap-2">
        <div className="font-medium text-stone-700">{t('3. 試試看')}</div>
        <div className="flex gap-2"><Button onClick={() => prev.mutate(seed)} disabled={prev.isPending}>{t('在 24 張畫面上試量')}</Button>
          {prev.data && <Button variant="ghost" onClick={() => { setSeed(v => v + 1); prev.mutate(seed + 1) }}>{t('換一批')}</Button>}</div>
        <p className="text-xs text-stone-500">{t('青色線是量到的位置。量不清楚時會寫「不確定」和原因(例如畫面變暗、背景透出來),腳本會等,不會亂用。')}</p>
        <ErrorText error={prev.error} />
        {prev.data && <div className="flex flex-wrap gap-3">
          {prev.data.items.map(it => {
            const r = it.ratio ?? null
            const [bx, , bw, bh] = box
            const sc = Math.min(1.2, 230 / (bw + (p.slant ? Math.abs(p.slant) : 0)))
            return (
              <div key={it.frame} className="flex flex-col gap-0.5 text-xs">
                <div className="relative">
                  <Zoom frame={it.frame} box={[bx, box[1] - 2, bw + Math.abs(p.slant ?? 0), bh + 4]} scale={sc} maxWidth={260} />
                  {r != null && horizontal && <div className="absolute top-0 bottom-0 w-0.5 bg-cyan-400"
                    style={{ left: ((p.dir === 'left' ? 1 - r : r) * bw + Math.abs(p.slant ?? 0) / 2) * Math.min(sc, 260 / (bw + Math.abs(p.slant ?? 0))) }} />}
                </div>
                <span className={r == null ? 'text-amber-700' : 'num'}>{r == null ? t('不確定:{p1}', { p1: it.why ?? '' }) : `${(r * 100).toFixed(1)}%`}</span>
              </div>
            )
          })}
        </div>}
      </section>
    </div>
  )
}

function PreviewGrid({ s, box, items }: { s: StateDef; box: number[]; items: RulePreviewItem[] }) {
  return (
    <div className="flex flex-wrap gap-3">
      {items.map(it => {
        const c = s.classes?.find(x => x.value === it.value)
        const best = it.scores ? Object.entries(it.scores).sort((a, b) => b[1] - a[1])[0] : null
        return (
          <div key={it.frame} className="flex flex-col gap-1">
            <Zoom frame={it.frame} box={box} scale={2} maxWidth={200} pad={s.source?.rule === 'template' ? (s.source?.params?.search ?? 3) : 0} />
            <div className="flex items-center gap-1.5 text-xs">
              <span className={`px-1.5 rounded-full ${c ? COLORS[c.color]?.pill : 'bg-stone-100 text-stone-500'}`}>{c?.name ?? t('無法判斷')}</span>
              {it.ratio != null && <span className="num text-stone-500">{(it.ratio * 100).toFixed(1)}%</span>}
              {best && <span className="num text-stone-500">{t('相似 {p1}', { p1: best[1] })}</span>}
              {it.gated && <span className="text-stone-400">{t('先決條件')}</span>}
            </div>
          </div>
        )
      })}
    </div>
  )
}

// ================================================================ templates
function TemplateRule({ s, box, setP }: { s: StateDef; box: number[]; setP: (k: string, v: any) => void }) {
  const qc = useQueryClient()
  const p = s.source.params ?? {}
  const tpls = useQuery({ queryKey: ['ruleTemplates', s.id], queryFn: () => api.ruleTemplates(s.id) })
  const [seed, setSeed] = useState(1)
  const [src, setSrc] = useState<{ session: string; device: string; offset: number } | null>(null)   // null = random
  const sessions = useQuery({ queryKey: ['sessions'], queryFn: api.sessions })
  const frames = useQuery({
    queryKey: ['tplFrames', seed, src],
    queryFn: async () => src ? await api.framesBrowse(src.session, src.device, src.offset, 24) : { total: 0, offset: 0, items: await api.randomFrames(24, seed) },
  })
  const [chosen, setChosen] = useState<string | null>(null)
  const pad = Number(s.source?.params?.search ?? 3)
  const [spot, setSpot] = useState<[number, number]>([0, 0])           // the reference is cut here: the region moved by spot
  useEffect(() => { setSpot([0, 0]) }, [chosen])
  const fallback = s.source?.params?.fallback
  const sess = sessions.data?.find(x => x.id === src?.session)
  const add = useMutation({
    mutationFn: (v: AnswerValue) => api.ruleTemplateAdd({ state_id: s.id, value: v, frame: chosen!,
      box: [box[0] + spot[0], box[1] + spot[1], box[2], box[3]] }),
    onSuccess: () => { setChosen(null); qc.invalidateQueries({ queryKey: ['ruleTemplates', s.id] }) },
  })
  const del = useMutation({ mutationFn: (f: string) => api.ruleTemplateDelete(s.id, f), onSuccess: () => qc.invalidateQueries({ queryKey: ['ruleTemplates', s.id] }) })
  const preview = useMutation({ mutationFn: (sd: number) => api.rulesPreview(s, 24, sd) })
  const list = tpls.data ?? []

  return (
    <div className="flex flex-col gap-5">
      <section className="flex flex-wrap gap-x-6 gap-y-2 items-center">
        <label className="flex items-center gap-2">{t('比對方式')}
          <select className={input} value={p.feature ?? 'gray'} onChange={e => setP('feature', e.target.value)}>
            <option value="gray">{t('灰階(看形狀)')}</option>
            <option value="color">{t('彩色(形狀和顏色都要像)')}</option>
            <option value="minch">{t('最暗通道(不受背景顏色影響)')}</option>
          </select></label>
        <label className="flex items-center gap-2">{t('最低相似度')}
          <input type="number" step={0.05} className={`${input} w-20 num`} value={p.match_min ?? 0.6} onChange={e => setP('match_min', Number(e.target.value))} /></label>
        <label className="flex items-center gap-2">{t('領先第二名至少')}
          <input type="number" step={0.01} className={`${input} w-20 num`} value={p.margin ?? 0.05} onChange={e => setP('margin', Number(e.target.value))} /></label>
        <label className="flex items-center gap-2">{t('容許偏移(像素)')}
          <input type="number" className={`${input} w-16 num`} value={p.search ?? 3} onChange={e => setP('search', Number(e.target.value))} /></label>
        <label className="flex items-center gap-2" title={t('例如「有沒有出現某個圖示」:沒出現時背景每次都不一樣,參考圖比不到,就直接當作「否」')}>{t('都不像時當作')}
          <select className={input} value={p.fallback === undefined || p.fallback === null ? '' : JSON.stringify(p.fallback)}
            onChange={e => setP('fallback', e.target.value === '' ? undefined : JSON.parse(e.target.value))}>
            <option value="">{t('不判斷(沒把握)')}</option>
            {(s.classes ?? []).map(c => <option key={String(c.value)} value={JSON.stringify(c.value)}>{c.name}</option>)}
          </select></label>
        <span className="text-xs text-stone-500 w-full">{t('相似度 1 = 完全一樣。最像的類別分數要超過「最低相似度」,且比第二像的類別高出「領先」這麼多,才下判斷。 判斷「某個圖示有沒有出現」時,只放「有」的參考圖,「都不像時當作」選「否」最穩:沒出現時的背景(底圖、其他按鈕)每次都不一樣,很難用參考圖比到。')}</span>
      </section>

      <section className="flex flex-col gap-2">
        <div className="font-medium text-stone-700">{t('1. 各類別的參考圖')}</div>
        <p className="text-xs text-stone-500">{t('每個類別至少 1 張,不同背景各放 1 張最好。參考圖存在狀態代號「{id}」底下,代號之後不要再改。', { id: s.id })}</p>
        <ErrorText error={tpls.error || del.error} />
        {(s.classes ?? []).map(c => {
          const mine = list.filter(tx => tx.value === c.value)
          return (
            <div key={String(c.value)} className="flex items-start gap-3 border-t border-stone-100 pt-2">
              <span className={`px-2 py-0.5 rounded-full text-xs shrink-0 w-20 text-center ${COLORS[c.color]?.pill}`}>{c.name}</span>
              <div className="flex flex-wrap gap-2">
                {mine.length === 0 && <span className="text-xs text-stone-400">{t('還沒有參考圖')}</span>}
                {mine.map(tx => (
                  <div key={tx.file} className="relative group">
                    <img src={ruleTemplateUrl(s.id, tx.file)} alt={c.name} style={{ imageRendering: 'pixelated', height: Math.min(80, box[3] * 2) }}
                      className="rounded border border-stone-300" />
                    <button onClick={() => del.mutate(tx.file)} title={t('刪除這張參考圖')}
                      className="absolute -top-1.5 -right-1.5 hidden group-hover:flex w-5 h-5 rounded-full bg-rose-600 text-white text-xs items-center justify-center">×</button>
                  </div>
                ))}
              </div>
            </div>
          )
        })}
      </section>

      <section className="flex flex-col gap-2">
        <div className="flex items-center gap-3 flex-wrap">
          <div className="font-medium text-stone-700">{t('2. 從畫面加入參考圖')}</div>
          <select className={input} value={src?.session ?? ''} onChange={e => {
            const sid = e.target.value
            const dv = sessions.data?.find(x => x.id === sid)?.devices[0]?.name
            setSrc(sid && dv ? { session: sid, device: dv, offset: 0 } : null); setChosen(null)
          }}>
            <option value="">{t('隨機(所有場次)')}</option>
            {sessions.data?.map(x => <option key={x.id} value={x.id}>{t('場次 {id}', { id: x.id })}</option>)}
          </select>
          {src && sess && (
            <select className={input} value={src.device} onChange={e => { setSrc({ ...src, device: e.target.value, offset: 0 }); setChosen(null) }}>
              {sess.devices.map(d => <option key={d.name} value={d.name}>{d.name}</option>)}
            </select>
          )}
          {src ? (
            <span className="flex items-center gap-2 text-xs text-stone-600">
              <Button variant="ghost" disabled={src.offset === 0} onClick={() => setSrc({ ...src, offset: Math.max(0, src.offset - 24) })}>{t('← 較早')}</Button>
              <span className="num">{t('第 {p1}~{p2} 張 / 共 {p3}', { p1: src.offset + 1, p2: Math.min(src.offset + 24, frames.data?.total ?? 0), p3: frames.data?.total ?? 0 })}</span>
              <Button variant="ghost" disabled={src.offset + 24 >= (frames.data?.total ?? 0)} onClick={() => setSrc({ ...src, offset: src.offset + 24 })}>{t('較晚 →')}</Button>
              <input type="range" min={0} max={Math.max(0, (frames.data?.total ?? 1) - 1)} step={24} value={src.offset}
                onChange={e => setSrc({ ...src, offset: Number(e.target.value) })} className="w-40" />
            </span>
          ) : <Button variant="ghost" onClick={() => { setSeed(v => v + 1); setChosen(null) }}>{t('換一批')}</Button>}
          <span className="text-xs text-stone-500 w-full">{t('點一張,再選它是哪個類別。要找少見的畫面(例如剛錄的某一段),選場次和{device},依時間順序翻。', { device: words.device })}</span>
        </div>
        <ErrorText error={add.error} />
        <div className="flex flex-wrap gap-2">
          {frames.data?.items.map(f => {
            // frames already used as a reference (same region) are marked, so they are not added twice by mistake
            const used = list.filter(tx => tx.frame === f && tx.box[2] === box[2] && tx.box[3] === box[3])
            const usedNames = used.map(tx => s.classes?.find(c => c.value === tx.value)?.name ?? String(tx.value))
            return (
              <div key={f} className={`relative flex flex-col gap-1 rounded border-2 p-0.5 ${chosen === f ? 'border-amber-500' : 'border-transparent'}`}>
                <button onClick={() => setChosen(chosen === f ? null : f)} className={used.length ? 'opacity-40' : ''}>
                  <Zoom frame={f} box={box} scale={2} maxWidth={170} pad={s.source?.params?.search ?? 3} />
                </button>
                {used.length > 0 && <span className="absolute top-1 left-1 text-[11px] px-1.5 rounded bg-stone-900/80 text-white pointer-events-none">{t('已加入:{p1}', { p1: usedNames.join(t('、')) })}</span>}
                {chosen === f && (
                  <div className="flex flex-wrap gap-1">
                    {(s.classes ?? []).map(c => {
                      const already = used.some(tx => tx.value === c.value)
                      const isFallback = fallback != null && JSON.stringify(fallback) === JSON.stringify(c.value)
                      return (
                        <button key={String(c.value)} onClick={() => add.mutate(c.value)} disabled={add.isPending || already || isFallback}
                          title={isFallback ? t('「{name}」不用加參考圖:都不像時就當作{name2}。加了反而會比到其他圖示而干擾判斷', { name: c.name, name2: c.name }) : undefined}
                          className={`px-2 py-0.5 rounded-full text-xs ${COLORS[c.color]?.pill} hover:ring-1 ring-stone-400 disabled:opacity-40`}>
                          {already ? t('已是{name}', { name: c.name }) : isFallback ? t('{name}(不用加)', { name: c.name }) : `+ ${c.name}`}</button>
                      )
                    })}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      </section>

      {chosen && pad > 0 && (
        <SpotPicker frame={chosen} box={box} pad={pad} spot={spot} onSpot={setSpot}>
          {(s.classes ?? []).filter(c => fallback == null || JSON.stringify(fallback) !== JSON.stringify(c.value)).map(c => (
            <button key={String(c.value)} onClick={() => add.mutate(c.value)} disabled={add.isPending}
              className={`px-3 py-1 rounded-full text-sm ${COLORS[c.color]?.pill} hover:ring-1 ring-stone-400 disabled:opacity-40`}>{t('+ 存成「{name}」的參考圖', { name: c.name })}</button>
          ))}
        </SpotPicker>
      )}

      <section className="flex flex-col gap-2">
        <div className="flex items-center gap-3">
          <div className="font-medium text-stone-700">{t('3. 預覽')}</div>
          <Button onClick={() => preview.mutate(Date.now() % 1000)} disabled={preview.isPending || list.length === 0}>{preview.isPending ? t('計算中…') : t('用 24 張畫面試試')}</Button>
          {list.length === 0 && <span className="text-xs text-stone-500">{t('先加入參考圖')}</span>}
        </div>
        <ErrorText error={preview.error} />
        {preview.data && <PreviewGrid s={s} box={box} items={preview.data.items} />}
      </section>
    </div>
  )
}

/** The chosen frame, region + the allowed offset, large: click where the thing is, the region (= what the reference
 * picture keeps) moves there. The picture is always region-sized; this only picks which spot of the frame it is cut from. */
function SpotPicker({ frame, box, pad, spot, onSpot, children }: {
  frame: string; box: number[]; pad: number; spot: [number, number]; onSpot: (s: [number, number]) => void; children?: React.ReactNode
}) {
  const [bx, by, bw, bh] = box
  const x0 = Math.max(0, bx - pad), y0 = Math.max(0, by - pad)
  const S = 4
  const click = (e: React.MouseEvent<HTMLDivElement>) => {
    const r = e.currentTarget.getBoundingClientRect()
    const cx = x0 + (e.clientX - r.left) / S, cy = y0 + (e.clientY - r.top) / S      // frame pixels
    const clampd = (v: number) => Math.max(-pad, Math.min(pad, Math.round(v)))
    onSpot([clampd(cx - (bx + bw / 2)), clampd(cy - (by + bh / 2))])
  }
  return (
    <section className="flex flex-col gap-1.5 rounded-md border border-amber-300 bg-amber-50 p-3">
      <div className="text-sm text-amber-900">{t('點一下要存成參考圖的那個圖示(例如它在左邊那一格,就點左邊那格的中間)。參考圖只存')}<b>{t('實線框')}</b>{t('裡的這一格。')}</div>
      <div className="relative self-start cursor-crosshair" onClick={click}>
        <Zoom frame={frame} box={box} scale={S} pad={pad} />
        <div className="absolute border-2 border-emerald-400 pointer-events-none"
          style={{ left: (bx + spot[0] - x0) * S, top: (by + spot[1] - y0) * S, width: bw * S, height: bh * S }} />
      </div>
      <div className="text-xs text-stone-600">{t('虛線 = 你設定的範圍;實線 = 這次要存的位置')}{spot[0] || spot[1] ? t('(移動了 {p1}, {p2} 像素)', { p1: spot[0], p2: spot[1] }) : ''}。</div>
      <div className="flex flex-wrap gap-2">{children}</div>
    </section>
  )
}

// ================================================================ read a number
/** 讀數字: the text colour finds the characters; each is compared with the characters taught here. */
function DigitsRule({ s, box, setP }: { s: StateDef; box: number[]; setP: (k: string, v: any) => void }) {
  const p = s.source.params ?? {}
  const qc = useQueryClient()
  const [seed, setSeed] = useState(1)
  const frames = useQuery({ queryKey: ['randomFrames', 'rule', seed], queryFn: () => api.randomFrames(12, seed) })
  const [pick, setPick] = useState(0)
  const frame = frames.data?.[pick]
  const sig = JSON.stringify([s.rois, p])
  const gl = useQuery({ queryKey: ['glyphs', s.id, frame, sig], queryFn: () => api.ruleGlyphs(s, frame!), enabled: !!frame && (p.colors ?? []).length > 0 })
  const [typed, setTyped] = useState<Record<number, string>>({})
  const teach = useMutation({
    mutationFn: ({ i, c }: { i: number; c: string }) => api.ruleGlyphTeach(s, frame!, i, c),
    onSuccess: d => { qc.setQueryData(['glyphs', s.id, frame, sig], d); qc.invalidateQueries({ queryKey: ['ruleTemplates', s.id] }); setTyped({}) },
  })
  const taught = useQuery({ queryKey: ['ruleTemplates', s.id], queryFn: () => api.ruleTemplates(s.id) })
  const del = useMutation({ mutationFn: (f: string) => api.ruleTemplateDelete(s.id, f), onSuccess: () => { qc.invalidateQueries({ queryKey: ['ruleTemplates', s.id] }); qc.invalidateQueries({ queryKey: ['glyphs'] }) } })
  const prev = useMutation({ mutationFn: () => api.rulesPreview(s, 24, seed) })
  const byChar: Record<string, RuleTemplate[]> = {}
  for (const tx of taught.data ?? []) (byChar[String(tx.value)] ??= []).push(tx)
  return (
    <div className="flex flex-col gap-5">
      <ColorSection s={s} box={box} setP={setP} title={t('1. 數字的顏色')} frame={frame} frames={frames.data} pick={pick} setPick={setPick}
        reseed={() => setSeed(v => v + 1)}
        hint={<>{t('在放大圖上')}<b>{t('點數字本身')}</b>{t('(不是背景),加入它的顏色。勾「標出符合的像素」確認每個數字都有被標出來、背景沒有;數字半透明或有外框時,多點幾個地方。')}</>} />
      <section className="flex flex-col gap-2">
        <div className="font-medium text-stone-700">{t('2. 讀哪一段')}</div>
        <div className="flex flex-wrap gap-x-6 gap-y-2 items-center">
          <select className={input} value={p.part ?? 'all'} onChange={e => setP('part', e.target.value)}>
            {Object.entries(PARTS).map(([k, tx]) => <option key={k} value={k}>{tx}</option>)}
          </select>
          <label className="flex items-center gap-2">{t('每個字元至少要像')}
            <input type="number" step={0.05} min={0.3} max={0.95} className={`${input} w-20 num`} value={p.match_min ?? 0.6} onChange={e => setP('match_min', Number(e.target.value))} />
            <span className="text-xs text-stone-500">{t('(低於就算「不確定」,腳本會等)')}</span></label>
        </div>
      </section>
      <section className="flex flex-col gap-2">
        <div className="font-medium text-stone-700">{t('3. 教它認字元')}</div>
        <p className="text-xs text-stone-500">{t('下面是這張畫面切出來的字元和目前認成什麼。認錯或還沒教過的,在下面填正確的字元(0~9 . , / % - :)按「教」。每個字元教 2~5 個例子最穩;換幾張畫面多教幾次。教之前請先')}<b>{t('儲存')}</b>{t('狀態定義。')}</p>
        {!(p.colors ?? []).length ? <Empty>{t('先在上面點選數字的顏色')}</Empty> : !gl.data ? <Empty>{gl.isLoading ? t('讀取中…') : t('選一張畫面')}</Empty> : (
          <div className="flex flex-col gap-2">
            <div className="text-sm">{t('讀到:')}<b className="num">{gl.data.text || t('(沒有找到字元)')}</b> {t('→ 數值')} <b className="num">{gl.data.value ?? t('不確定')}</b>{s.unit ? ` ${s.unit}` : ''}</div>
            <div className="flex flex-wrap gap-2">
              {gl.data.glyphs.map((g, i) => (
                <div key={i} className="flex flex-col items-center gap-1 border border-stone-200 rounded p-1">
                  <Zoom frame={frame!} box={[g.box[0] - 1, g.box[2] - 1, g.box[1] - g.box[0] + 2, g.box[3] - g.box[2] + 2]} scale={4} maxWidth={60} />
                  <span className={`text-xs num ${g.char == null || g.score < (p.match_min ?? 0.6) ? 'text-rose-700' : 'text-stone-700'}`}>{g.char ?? '?'} · {g.score.toFixed(2)}</span>
                  <input className={`${input} w-10 text-center num`} maxLength={1} value={typed[i] ?? ''} onChange={e => setTyped(tx => ({ ...tx, [i]: e.target.value }))} />
                  <Button disabled={!typed[i] || teach.isPending} onClick={() => teach.mutate({ i, c: typed[i] })}>{t('教')}</Button>
                </div>
              ))}
            </div>
          </div>
        )}
        <ErrorText error={gl.error || teach.error || del.error} />
        {Object.keys(byChar).length > 0 && <div className="flex flex-wrap gap-3 text-xs">
          {Object.entries(byChar).sort().map(([c, ts]) => (
            <div key={c} className="flex items-center gap-1 border border-stone-200 rounded px-1.5 py-1">
              <b className="num w-3">{c}</b>
              {ts.map(tx => <button key={tx.file} title={t('刪除這個例子')} onClick={() => del.mutate(tx.file)}>
                <img src={ruleTemplateUrl(s.id, tx.file)} alt={c} className="h-6 border border-stone-300 bg-stone-900" style={{ imageRendering: 'pixelated' }} /></button>)}
            </div>))}
        </div>}
      </section>
      <section className="flex flex-col gap-2">
        <div className="font-medium text-stone-700">{t('4. 試試看')}</div>
        <div><Button onClick={() => prev.mutate()} disabled={prev.isPending}>{t('在 24 張畫面上試讀')}</Button></div>
        <ErrorText error={prev.error} />
        {prev.data && <div className="flex flex-wrap gap-2">
          {prev.data.items.map(it => (
            <div key={it.frame} className="flex flex-col gap-0.5 text-xs">
              <Zoom frame={it.frame} box={box} scale={1} maxWidth={180} />
              <span className={`num ${it.value == null ? 'text-amber-700' : ''}`}>{it.text || '—'} → {it.value ?? t('不確定')}</span>
            </div>))}
        </div>}
      </section>
    </div>
  )
}
