import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, type DatasetSummary, type RunBrief, type TrainConfig } from '../api'
import { ModelHealth } from '../components/ModelHealth'
import { Curves, TEST_STYLE, TEST_TEXT } from '../components/RunReport'
import { Button, Card, Empty, ErrorText, LogView, Modal, MoreButton, Pill } from '../components/ui'
import { dateTime, duration, pct } from '../lib/format'
import { usePersistentState } from '../lib/persist'
import { useSchema } from '../lib/schema'
import { t } from '../i18n'
import { edition, words } from '../lib/project'

const SIZES: [number, number][] = [[320, 180], [480, 270], [640, 360], [960, 540]]
const DEFAULT: TrainConfig = {
  name: '', epochs: 20, width: 640, height: 360, batch: 16, lr: 0.001, pretrained: false,
  holdout: [], neighbor_seconds: 1, augment: true, seed: 0, relabel: true,
}
const SPLIT_TEXT: Record<string, string> = { train: t('訓練'), val: t('保留裝置(驗證)'), test: t('測試集'), excluded: t('排除') }
const STATE_TEXT: Record<string, [Parameters<typeof Pill>[0]['tone'], string]> = {
  loading: ['amber', t('準備中')], training: ['green', t('訓練中')], evaluating: ['green', t('評估中')],
  done: ['blue', t('完成')], failed: ['red', t('失敗')], stopped: ['stone', t('已停止')],
}

export default function Training() {
  const qc = useQueryClient()
  const runs = useQuery({ queryKey: ['trainRuns'], queryFn: api.trainRuns, refetchInterval: q => (q.state.data?.job?.status === 'running' ? 2000 : 10000) })
  const [sel, setSel] = usePersistentState<string | null>('train.selected', null)
  const list = runs.data?.runs ?? []
  const running = runs.data?.job?.status === 'running'
  const selected = sel && list.some(r => r.id === sel) ? sel : list[0]?.id ?? null

  // a new run appears: follow it
  const newest = list[0]?.id
  useEffect(() => { if (running && newest) setSel(newest) }, [running, newest]) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="p-6 max-w-[1500px] mx-auto flex flex-col gap-5">
      <header>
        <h1 className="text-xl font-semibold text-stone-900">{t('學習')}</h1>
        <p className="text-sm text-stone-500 mt-1 max-w-4xl">
          {t('讓模型看大量自動標註過的畫面,學會判斷每個狀態。學習時不會看你回答過的考題,也不看保留的那台{device}; 學完後用考題打分數,結果在「成績與錯題」。', { device: words.device })}
        </p>
      </header>
      <ErrorText error={runs.error} />
      <ModelHealth />
      {running && runs.data?.job && <Live run={list[0]} log={runs.data.job.log} onStop={() => api.trainStop().then(() => qc.invalidateQueries({ queryKey: ['trainRuns'] }))} />}
      <div className="grid xl:grid-cols-[420px_1fr] gap-5 items-start">
        <NewRun disabled={running} />
        <RunList runs={list} selected={selected} onSelect={setSel} />
      </div>
      {selected && <RunView id={selected} live={running && selected === list[0]?.id} />}
    </div>
  )
}

// ---------------------------------------------------------------- live progress
const PHASE_ORDER = ['labels', 'cache', 'train', 'val', 'test', 'report']

function Live({ run, log, onStop }: { run?: RunBrief; log: string[] | null; onStop: () => void }) {
  const st = run?.status ?? {}
  const now = Date.now() / 1000
  const elapsed = st.started ? now - st.started : null
  const stale = st.updated ? now - st.updated : 0
  const phaseFrac = st.total ? (st.done ?? 0) / st.total : null
  const overall = elapsed != null && st.eta_total != null ? elapsed / (elapsed + st.eta_total) : null
  const perEpoch = st.phase === 'train' || st.phase === 'val' || st.phase === 'test'
  return (
    <Card title={t('訓練進行中')} extra={<Button variant="danger" onClick={onStop}>{t('停止')}</Button>}>
      <div className="flex flex-col gap-3 text-sm">
        <div className="flex flex-wrap gap-1.5 text-xs">
          {PHASE_ORDER.map(p => {
            const i = PHASE_ORDER.indexOf(p), cur = PHASE_ORDER.indexOf(st.phase ?? '')
            const name = { labels: t('更新標籤'), cache: t('縮小畫面'), train: t('訓練'), val: t('保留裝置評分'), test: t('測試集評分'), report: t('最終報告') }[p]
            const repeated = perEpoch && (p === 'train' || p === 'val' || p === 'test')
            const cls = p === st.phase ? 'bg-emerald-600 text-white' : i < cur && !repeated ? 'bg-emerald-50 text-emerald-700' : 'bg-stone-100 text-stone-500'
            return <span key={p} className={`px-2 py-0.5 rounded-full ${cls}`}>{name}</span>
          })}
          {perEpoch && st.epoch != null && <span className="px-2 py-0.5 text-stone-600 num">{t('第 {epoch} / {epochs} 輪', { epoch: st.epoch, epochs: st.epochs })}{st.best_epoch ? t('(目前最好:第 {best_epoch} 輪)', { best_epoch: st.best_epoch }) : ''}</span>}
        </div>

        <div>
          <div className="flex justify-between text-xs text-stone-600 mb-1">
            <span>{st.phase_name ?? t('準備中')}{st.message && st.phase === 'labels' ? `(${st.message})` : ''}</span>
            <span className="num">
              {st.total ? <>{t('{p1} / {p2} 張', { p1: (st.done ?? 0).toLocaleString(), p2: st.total.toLocaleString() })}</> : t('進行中…')}
              {st.img_per_s != null && <> {t('· 每秒 {img_per_s} 張', { img_per_s: st.img_per_s })}</>}
              {st.eta_phase != null && <> {t('· 這一步約剩 {p1}', { p1: duration(st.eta_phase) })}</>}
            </span>
          </div>
          <div className="h-2 bg-stone-200 rounded-full overflow-hidden">
            {phaseFrac != null ? <div className="h-full bg-emerald-500 transition-all" style={{ width: `${phaseFrac * 100}%` }} />
              : <div className="h-full w-1/3 bg-emerald-300 animate-pulse" />}
          </div>
        </div>

        <div>
          <div className="flex justify-between text-xs text-stone-600 mb-1">
            <span>{t('整體進度')}</span>
            <span className="num">{elapsed != null && <>{t('已 {p1}', { p1: duration(elapsed) })}</>}{st.eta_total != null ? <> {t('· 全部約剩 {p1}', { p1: duration(st.eta_total) })}</> : t(' · 剩餘時間計算中')}</span>
          </div>
          <div className="h-2 bg-stone-200 rounded-full overflow-hidden"><div className="h-full bg-sky-500 transition-all" style={{ width: `${(overall ?? 0) * 100}%` }} /></div>
        </div>
        {stale > 60 && <p className="text-xs text-amber-700">{t('已經 {p1} 秒沒有進度更新,若持續很久請看下方日誌。', { p1: Math.round(stale) })}</p>}
        <LogView lines={log} height="h-40" />
      </div>
    </Card>
  )
}

// ---------------------------------------------------------------- new run form + dataset preview
function NewRun({ disabled }: { disabled: boolean }) {
  const qc = useQueryClient()
  const [cfg, setCfg] = usePersistentState<TrainConfig>('train.config', DEFAULT)
  const c = { ...DEFAULT, ...cfg }
  const [adv, setAdv] = useState(false)
  const set = <K extends keyof TrainConfig>(k: K, v: TrainConfig[K]) => setCfg({ ...c, [k]: v })
  const preview = useQuery({
    queryKey: ['trainPreview', c.holdout.join(','), c.neighbor_seconds],
    queryFn: () => api.trainPreview(c.holdout, c.neighbor_seconds),
    refetchInterval: q => (q.state.data?.labeling ? 3000 : 30000),
  })
  const labeling = !!preview.data?.labeling
  const start = useMutation({
    mutationFn: () => api.trainStart(c),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['trainRuns'] })
      document.querySelector('main')?.scrollTo({ top: 0, behavior: 'smooth' })     // the progress card is at the top
    },
  })
  const devices = preview.data?.all_devices ?? []
  const toggle = (d: string) => set('holdout', c.holdout.includes(d) ? c.holdout.filter(x => x !== d) : [...c.holdout, d])
  const num = (k: 'epochs' | 'batch' | 'lr' | 'neighbor_seconds' | 'seed', step = 1) => (
    <input type="number" step={step} value={c[k]} onChange={e => set(k, Number(e.target.value))}
      className="w-24 border border-stone-300 rounded px-2 py-1 text-sm num" />
  )

  return (
    <Card title={t('開始新的學習')} extra={
      <Button variant="primary" disabled={!edition.training || disabled || labeling || start.isPending || !preview.data} onClick={() => start.mutate()}>
        {!edition.training ? t('純執行版不能學習') : disabled ? t('已有學習在進行') : labeling ? t('標籤產生中,請稍候') : start.isPending ? t('啟動中…') : t('開始學習')}
      </Button>}>
      <div className="flex flex-col gap-4 text-sm">
        {!edition.training && <p className="text-xs text-amber-800 bg-amber-50 rounded px-3 py-2">{t('這是純執行版:可以執行腳本、看成績,但沒有安裝學習需要的 PyTorch。要學習請在完整版(pip install -r requirements.txt)操作。')}</p>}
        <ErrorText error={start.error} />
        <Field label={t('名稱')} hint={t('方便自己辨認,例如「預訓練640」')}>
          <input value={c.name} onChange={e => set('name', e.target.value)} placeholder={t('(可不填)')} className="w-full border border-stone-300 rounded px-2 py-1" />
        </Field>
        <Field label={t('保留裝置')} hint={t('勾選的{device}完全不拿來訓練,用來看模型遇到「沒看過的畫面」時表現如何,並用來挑最好的一輪。', { device: words.device })}>
          <div className="flex flex-wrap gap-x-4 gap-y-1">
            {devices.map(d => (
              <label key={d} className="flex items-center gap-1.5"><input type="checkbox" checked={c.holdout.includes(d)} onChange={() => toggle(d)} />{d}</label>
            ))}
          </div>
        </Field>
        <div className="flex flex-wrap items-center gap-2 text-xs text-stone-600">
          <span>{t('輪數 {epochs} · 批次 {batch} · 學習率 {lr} · {width}×{height} · 預訓練', { epochs: c.epochs, batch: c.batch, lr: c.lr, width: c.width, height: c.height })}{c.pretrained ? t('開') : t('關')} {t('· 資料增強')}{c.augment ? t('開') : t('關')}</span>
          <MoreButton onClick={() => setAdv(true)}>{t('進階設定')}</MoreButton>
        </div>
        <Modal open={adv} wide title={t('進階訓練設定')} onClose={() => setAdv(false)} footer={<Button variant="primary" onClick={() => setAdv(false)}>{t('好')}</Button>}>
        <div className="grid grid-cols-2 gap-3">
          <Field label={t('輪數(epoch)')} hint={t('整份訓練資料看幾遍')}>{num('epochs')}</Field>
          <Field label={t('批次大小')} hint={t('一次看幾張;{device}開著建議 16', { device: words.device })}>{num('batch')}</Field>
          <Field label={t('學習率')} hint={t('每一步調整多大;預訓練建議 0.0003')}>{num('lr', 0.0001)}</Field>
          <Field label={t('輸入尺寸')} hint={t('越大越看得清小字,越慢')}>
            <select value={`${c.width}x${c.height}`} onChange={e => { const [w, h] = e.target.value.split('x').map(Number); setCfg({ ...c, width: w, height: h }) }}
              className="border border-stone-300 rounded px-2 py-1 num">
              {SIZES.map(([w, h]) => <option key={w} value={`${w}x${h}`}>{w}×{h}</option>)}
            </select>
          </Field>
          <Field label={t('測試集鄰近排除(秒)')} hint={t('測試畫面前後這幾秒的畫面不拿來訓練,避免「幾乎一樣的畫面」洩漏答案')}>{num('neighbor_seconds', 0.5)}</Field>
          <Field label={t('亂數種子')} hint={t('同樣設定換種子,可看結果穩不穩定')}>{num('seed')}</Field>
        </div>
        <label className="flex items-start gap-2">
          <input type="checkbox" className="mt-1" checked={c.pretrained} onChange={e => set('pretrained', e.target.checked)} />
          <span>{t('使用預訓練權重(ImageNet)')}<br /><span className="text-xs text-stone-500">{t('主幹先學過一般圖片,通常資料少時更準。第一次會從 download.pytorch.org 下載約 45 MB 的 resnet18 權重。')}</span></span>
        </label>
        <label className="flex items-start gap-2">
          <input type="checkbox" className="mt-1" checked={c.augment} onChange={e => set('augment', e.target.checked)} />
          <span>{t('資料增強')}<br /><span className="text-xs text-stone-500">{t('訓練時隨機改亮度、對比、稍微平移,讓模型不死記某張圖。')}</span></span>
        </label>
        </Modal>
        <label className="flex items-start gap-2">
          <input type="checkbox" className="mt-1" checked={c.relabel} onChange={e => set('relabel', e.target.checked)} />
          <span>{t('訓練前自動更新標籤')}<br /><span className="text-xs text-stone-500">{t('只在標籤過期時才做(有新資料、狀態定義或參考圖改過)。')}</span></span>
        </label>

        <LabelsState data={preview.data} relabel={c.relabel} />
        <DatasetPreview data={preview.data} error={preview.error} />

      </div>
    </Card>
  )
}

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1">
      <span className="text-stone-700 font-medium">{label}</span>
      {children}
      {hint && <span className="text-xs text-stone-500">{hint}</span>}
    </div>
  )
}

function LabelsState({ data, relabel }: { data?: DatasetSummary; relabel: boolean }) {
  const st = data?.labels_status
  if (!st) return null
  if (data?.labeling) return <div className="text-xs rounded bg-sky-50 text-sky-900 border border-sky-200 px-2 py-1.5">{t('標籤產生中(「{title}」),完成後下面的資料切分會自動更新。', { title: data.labeling.title })}</div>
  if (!st.stale) return <div className="text-xs rounded bg-emerald-50 text-emerald-800 border border-emerald-200 px-2 py-1.5">{t('標籤 {version} 是最新的(產生於 {p2})', { version: st.version, p2: dateTime(st.built) })}</div>
  return (
    <div className={`text-xs rounded border px-2 py-1.5 ${relabel ? 'bg-sky-50 text-sky-900 border-sky-200' : 'bg-amber-50 text-amber-900 border-amber-200'}`}>
      {t('標籤 {p1} 不是最新的:{p2}。', { p1: st.version ?? '', p2: st.reasons.join(t(';')) })}
      {relabel ? t('開始訓練時會先自動更新標籤(多花幾分鐘),下面的資料切分是舊標籤的數字。')
        : <>{t('這次訓練會用舊標籤。要更新請勾選上面的「訓練前自動更新標籤」,或到')} <Link to="/labels" className="underline">{t('自動標註')}</Link> {t('按「產生標籤」。')}</>}
    </div>
  )
}

const LOW_TRAIN = 10     // fewer training examples than this: the class may be learned poorly

/** Classes the model cannot learn (0 training examples although the data has them) or will learn poorly. */
function coverage(data: DatasetSummary) {
  const out: { level: 'red' | 'amber' | 'grey'; head: string; cls: string; text: string }[] = []
  for (const h of data.heads) {
    if (h.kind !== 'class') continue
    const n = (sp: string, cl: string) => h.splits[sp]?.[cl] ?? 0
    const total = (sp: string) => Object.values(h.splits[sp] ?? {}).reduce((a, b) => a + b, 0)
    if (!total('train') && !total('val') && !total('test')) {
      out.push({ level: 'grey', head: h.id, cls: '', text: t('「{name}」還沒有任何標籤(新狀態要先產生標籤才會出現)。', { name: h.name }) })
      continue
    }
    h.classes!.forEach((cl, i) => {
      const tr = n('train', cl), val = n('val', cl), te = n('test', cl), name = h.class_names![i]
      if (tr === 0 && val + te > 0)
        out.push({ level: 'red', head: h.id, cls: cl, text: t('「{name}:{name2}」在訓練資料裡 0 張(只有驗證 {val}、測試 {te} 張),模型學不到。請在保留裝置以外的{device}收集這種畫面。', { name: h.name, name2: name, val, te, device: words.device }) })
      else if (tr > 0 && tr < LOW_TRAIN)
        out.push({ level: 'amber', head: h.id, cls: cl, text: t('「{name}:{name2}」訓練資料只有 {tr} 張,可能學不好,建議多收集一些。', { name: h.name, name2: name, tr }) })
    })
  }
  return out
}

function DatasetPreview({ data, error }: { data?: DatasetSummary; error: unknown }) {
  if (error) return <ErrorText error={error} />
  if (!data) return <div className="text-xs text-stone-500">{t('計算資料切分中…')}</div>
  const order = ['train', 'val', 'test', 'excluded'].filter(s => data.splits[s])
  const checks = coverage(data)
  const missing = new Set(checks.filter(c => c.level === 'red').map(c => `${c.head}|${c.cls}`))
  return (
    <div className="border border-stone-200 rounded-md p-3 flex flex-col gap-3 bg-stone-50">
      {checks.length > 0 && (
        <div className="flex flex-col gap-1">
          {checks.map((c, i) => (
            <div key={i} className={`text-xs rounded border px-2 py-1.5 ${c.level === 'red' ? 'bg-rose-50 text-rose-800 border-rose-300 font-medium'
              : c.level === 'amber' ? 'bg-amber-50 text-amber-900 border-amber-200' : 'bg-stone-100 text-stone-600 border-stone-200'}`}>{c.text}</div>
          ))}
        </div>
      )}
      <div className="text-xs text-stone-500">{t('資料切分(標籤 {labels_version} · 狀態定義 v{schema_version})', { labels_version: data.labels_version, schema_version: data.schema_version })}</div>
      <div className="grid grid-cols-4 gap-2 text-center">
        {order.map(s => (
          <div key={s} className="bg-white rounded border border-stone-200 py-1.5" title={Object.entries(data.splits[s].devices).map(([d, n]) => `${d} ${n}`).join('\n')}>
            <div className="text-lg font-semibold num">{data.splits[s].frames}</div>
            <div className="text-[11px] text-stone-500">{SPLIT_TEXT[s]}</div>
          </div>
        ))}
      </div>
      <table className="text-xs w-full">
        <thead><tr className="text-stone-500"><th className="text-left font-normal">{t('狀態')}</th><th className="text-left font-normal">{t('訓練')}</th><th className="text-left font-normal">{t('驗證')}</th><th className="text-left font-normal">{t('測試')}</th></tr></thead>
        <tbody>
          {data.heads.map(h => (
            <tr key={h.id} className="border-t border-stone-200 align-top">
              <td className="py-1 pr-2 whitespace-nowrap">{h.name}</td>
              {(['train', 'val', 'test'] as const).map(sp => (
                <td key={sp} className="py-1 pr-2 num">
                  {h.kind === 'class'
                    ? h.classes!.map((cl, i) => h.splits[sp]?.[cl] ? <div key={cl}>{h.class_names![i]} {h.splits[sp][cl]}</div>
                      : sp === 'train' && missing.has(`${h.id}|${cl}`) ? <div key={cl} className="text-rose-700 font-semibold">{h.class_names![i]} 0 ⚠</div> : null)
                    : <div>{t('{p1} 張', { p1: h.splits[sp]?.labeled ?? 0 })}</div>}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ---------------------------------------------------------------- run list
function RunList({ runs, selected, onSelect }: { runs: RunBrief[]; selected: string | null; onSelect: (id: string) => void }) {
  const heads = useMemo(() => {
    const ids = new Set<string>()
    runs.forEach(r => Object.keys(r.result ?? {}).forEach(k => ids.add(k)))
    return [...ids]
  }, [runs])
  const sch = useSchema()
  const name = (id: string) => sch.data?.schema.states.find(s => s.id === id)?.name ?? id
  return (
    <Card title={t('訓練紀錄')}>
      {runs.length === 0 ? <Empty>{t('還沒有訓練過。設定好左邊後按「開始訓練」。')}</Empty> : (
        <div className="overflow-auto">
          <table className="text-sm w-full">
            <thead>
              <tr className="text-xs text-stone-500 text-left">
                <th className="font-normal py-1">{t('訓練')}</th><th className="font-normal">{t('設定')}</th><th className="font-normal">{t('進度')}</th>
                {heads.map(h => <th key={h} className="font-normal text-right px-2">{name(h)}</th>)}
              </tr>
            </thead>
            <tbody>
              {runs.map(r => {
                const [tone, text] = STATE_TEXT[r.status.state ?? 'stopped'] ?? ['stone', r.status.state]
                const c = r.config
                return (
                  <tr key={r.id} onClick={() => onSelect(r.id)} className={`border-t border-stone-100 cursor-pointer ${selected === r.id ? 'bg-amber-50' : 'hover:bg-stone-50'}`}>
                    <td className="py-1.5 pr-2">
                      <div className="font-medium">{c?.name || t('(未命名)')}</div>
                      <div className="text-xs text-stone-500 num">{dateTime(r.created)}</div>
                    </td>
                    <td className="text-xs text-stone-600 num pr-2">
                      {c && <>{t('{width}×{height} · {epochs} 輪', { width: c.width, height: c.height, epochs: c.epochs })}{c.pretrained ? t(' · 預訓練') : ''}<br />{t('保留裝置:{devices}', { devices: c.holdout.join(', ') || t('無') })}</>}
                    </td>
                    <td><Pill tone={tone}>{text}</Pill></td>
                    {heads.map(h => {
                      const v = r.result?.[h]
                      return (
                        <td key={h} className="text-right px-2 num">
                          {v?.model_acc != null ? <><span className="font-semibold">{pct(v.model_acc)}</span><div className="text-[11px] text-stone-400">{t('規則 {p1}', { p1: pct(v.rule_acc) })}</div></>
                            : v?.test_mae != null ? <span title={t('平均誤差')}>±{(v.test_mae * 100).toFixed(1)}%</span> : '—'}
                        </td>
                      )
                    })}
                  </tr>
                )
              })}
            </tbody>
          </table>
          <p className="text-xs text-stone-500 mt-2">{t('分數是模型在測試集的準確率;下方小字是畫面規則在同一批畫面的準確率(規則「無法判斷」的畫面,只有答案是「看不到」時才算對)。比例和數值狀態顯示平均誤差。')}</p>
        </div>
      )}
    </Card>
  )
}

// ---------------------------------------------------------------- one run: curves, report, mistakes
function RunView({ id, live }: { id: string; live: boolean }) {
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['trainRun', id], queryFn: () => api.trainRun(id), refetchInterval: live ? 3000 : false })
  const del = useMutation({ mutationFn: () => api.trainDelete(id), onSuccess: () => qc.invalidateQueries({ queryKey: ['trainRuns'] }) })
  const r = q.data
  if (!r) return <ErrorText error={q.error} />
  return (
    <Card title={`${r.config?.name || t('(未命名)')} · ${r.id}`}
      extra={!live && <Button variant="ghost" onClick={() => { if (confirm(t('刪除這次訓練(包含模型檔)?'))) del.mutate() }}>{t('刪除')}</Button>}>
      <div className="flex flex-col gap-6">
        {r.status.state === 'failed' && <ErrorText error={r.status.message ?? t('訓練失敗,請看工作日誌')} />}
        <ErrorText error={del.error} />
        <Curves run={r} />
        {r.eval
          ? <div className="text-sm flex items-center gap-3 flex-wrap">
              <span className="text-stone-600">{t('學完了,考試結果:')}</span>
              {Object.entries(r.tests ?? {}).map(([k, tx]) => (
                <span key={k} className={`px-2 py-0.5 rounded-full text-xs ${TEST_STYLE[tx.result]}`} title={tx.reason}>{r.eval!.heads[k]?.name ?? k} {TEST_TEXT[tx.result]}</span>
              ))}
              <Link to={`/results?run=${r.id}`} className="text-xs px-2.5 py-1 rounded-md bg-stone-900 text-white hover:bg-stone-700">{t('看成績與錯題 →')}</Link>
            </div>
          : <Empty>{live ? t('學習完成後會在這裡顯示考試結果') : t('這次學習沒有完成,沒有考試結果')}</Empty>}
      </div>
    </Card>
  )
}

