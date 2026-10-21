import { t } from '../i18n'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, type ClassDef, type JudgeInfo, type JudgeSource, type ProgressStep, type RoiDef, type StateDef, type StateProgress, type JudgeMode } from '../api'
import { RoiEditor, Zoom, type Box } from '../components/FrameView'
import { defaultParams, RULE_KINDS, RuleEditor } from '../components/RuleEditor'
import { Button, Card, Empty, ErrorText, Modal, MoreButton, Page, Pill } from '../components/ui'
import { dateTime } from '../lib/format'
import { COLOR_NAMES, COLORS, roiUses, SOURCE_TEXT, stateColor, TYPE_TEXT, USE_STYLE, useSchema } from '../lib/schema'
import { words } from '../lib/project'

const clone = <T,>(v: T): T => JSON.parse(JSON.stringify(v))
const input = 'border border-stone-300 rounded-md px-2 py-1 text-sm bg-white'

const JUDGE_TAG: Record<JudgeSource['source'], [string, string]> = {
  model: [t('模型判斷'), 'bg-stone-100 text-stone-600'],
  rule: [t('參考圖/顏色判斷'), 'bg-sky-600 text-white'],
  none: [t('執行時不判斷'), 'bg-stone-50 text-stone-400 border border-stone-200'],
}
const STEP_DOT: Record<ProgressStep['status'], string> = {
  ok: 'bg-emerald-500', partial: 'bg-amber-400', todo: 'bg-stone-300', na: 'bg-stone-200',
}

/** the four steps of a state as small dots (list) */
function MiniRail({ p }: { p?: StateProgress }) {
  if (!p) return null
  return (
    <span className="inline-flex items-center gap-0.5 mt-1" title={p.steps.map(s => `${s.name}:${s.text}`).join('\n')}>
      {p.steps.map((s, i) => (
        <span key={s.key} className="flex items-center gap-0.5">
          {i > 0 && <span className={`w-2 h-px ${s.status === 'ok' ? 'bg-emerald-500' : 'bg-stone-300'}`} />}
          <span className={`w-2 h-2 rounded-full ${STEP_DOT[s.status]} ${p.current === i ? 'ring-2 ring-amber-400' : ''}`} />
        </span>
      ))}
    </span>
  )
}

/** the four steps in full: what is done, what is next, with a link to do it */
function Rail({ p }: { p?: StateProgress }) {
  if (!p) return <div className="text-xs text-stone-500 md:col-span-2">{t('學習進度:儲存後才會更新')}</div>
  return (
    <div className="md:col-span-2 flex flex-col gap-2">
      <span className="text-stone-600 text-sm">{t('學習進度')}</span>
      <ol className="grid sm:grid-cols-2 xl:grid-cols-4 gap-2">
        {p.steps.map((s, i) => {
          const now = p.current === i
          return (
            <li key={s.key} className={`rounded-md border px-3 py-2 text-xs flex flex-col gap-1 ${now ? 'border-amber-400 bg-amber-50' : 'border-stone-200 bg-white'}`}>
              <div className="flex items-center gap-1.5 font-medium text-stone-800 text-sm">
                <span className={`w-4 h-4 rounded-full flex items-center justify-center text-[10px] text-white ${STEP_DOT[s.status]}`}>
                  {s.status === 'ok' ? '✓' : s.status === 'partial' ? '!' : i + 1}</span>
                {s.name}{now && <span className="text-[11px] font-normal text-amber-700">{t('← 下一步')}</span>}
              </div>
              <div className="text-stone-600">{s.text}</div>
              {s.link && s.status !== 'ok' && s.status !== 'na' && <Link to={s.link} className="text-stone-900 underline underline-offset-2 w-fit">
                {s.key === 'test' ? t('去回答這一題') : s.key === 'model' ? t('看成績') : t('去處理')} →</Link>}
            </li>
          )
        })}
      </ol>
    </div>
  )
}

const pct = (v?: number | null) => v == null ? '' : `${Math.round(v * 1000) / 10}%`

/** how the script runner judges this state: model (with its test scores) / screen rule / not at all */
function JudgeLine({ j, info }: { j?: JudgeSource; info?: JudgeInfo }) {
  if (!j) return <div className="text-xs text-stone-500 md:col-span-2">{t('腳本執行時:儲存後才會知道')}</div>
  const [tag, cls] = JUDGE_TAG[j.source]
  const scores = j.source === 'model' && (j.acc != null
    ? (j.holdout_acc != null ? t('測試正確率 {acc}(沒學過的{device} {holdout})', { acc: pct(j.acc), device: words.device, holdout: pct(j.holdout_acc) })
      : t('測試正確率 {acc}', { acc: pct(j.acc) }))
    : j.mae != null ? t('測試平均誤差 {p1}', { p1: pct(j.mae) }) : '')
  return (
    <div className="text-xs md:col-span-2 flex flex-wrap items-center gap-2">
      <span className="text-stone-600">{t('腳本執行時:')}</span>
      <span className={`px-1.5 rounded ${cls}`}>{tag}</span>
      <span className="text-stone-500">{j.reason}{scores ? ` · ${scores}` : ''}</span>
      {info?.running && <span className="text-emerald-700">{t('(腳本執行中使用的模型)')}</span>}
    </div>
  )
}

export default function States() {
  const qc = useQueryClient()
  const q = useSchema()
  const schema = q.data?.schema
  const [draft, setDraft] = useState<StateDef[] | null>(null)          // edited copy of all states
  const [sel, setSel] = useState(0)
  const [note, setNote] = useState('')
  const [versions, setVersions] = useState(false)
  const states = draft ?? schema?.states ?? []
  const dirty = !!draft && JSON.stringify(draft) !== JSON.stringify(schema?.states)
  const judge = useQuery({ queryKey: ['statesJudge', '', schema?.version], queryFn: () => api.statesJudge(), refetchInterval: 30000 })
  const prog = useQuery({ queryKey: ['statesProgress', schema?.version], queryFn: api.statesProgress, refetchInterval: 30000 })
  useEffect(() => { if (schema && !draft) setDraft(clone(schema.states)) }, [schema, draft])

  const update = (i: number, fn: (s: StateDef) => void) => setDraft(d => { const n = clone(d ?? []); fn(n[i]); return n })
  const save = useMutation({
    mutationFn: () => api.statesSave(states, note),
    onSuccess: s => { setNote(''); setDraft(clone(s.states)); qc.invalidateQueries({ queryKey: ['schema'] }) },
  })
  const restore = useMutation({
    mutationFn: (v: number) => api.statesRestore(v),
    onSuccess: s => { setDraft(clone(s.states)); qc.invalidateQueries({ queryKey: ['schema'] }) },
  })
  const addState = () => {
    const n = clone(states)
    n.push({ id: `state_${n.length + 1}`, name: t('新狀態'), type: 'class', description: '', source: { kind: 'manual' },
      classes: [{ value: 'yes', name: t('是'), color: 'green', key: '' }, { value: 'no', name: t('否'), color: 'red', key: '' }],
      rois: [{ id: 'main', name: t('主要範圍'), box: [540, 260, 200, 200] }], review: { enabled: false, roi: 'main', scale: 2 } })
    setDraft(n); setSel(n.length - 1)
  }
  const cur = states[sel]

  return (
    <Page title={t('要看的狀態')} desc={t('模型要辨識哪些狀態、每個狀態看畫面的哪個範圍、有哪些選項。標籤程式、人工確認、資料瀏覽的截圖與框線都依照這份定義。每次儲存都是一個新版本。')}
      actions={<>
        <MoreButton onClick={() => setVersions(true)}>{t('版本紀錄(目前 v{p1})', { p1: schema?.version ?? '–' })}</MoreButton>
        {dirty && <Button variant="ghost" onClick={() => setDraft(clone(schema!.states))}>{t('放棄修改')}</Button>}
        <input id="note" value={note} onChange={e => setNote(e.target.value)} placeholder={t('這次修改的說明')} className={`${input} w-56`} />
        <Button variant="primary" onClick={() => save.mutate()} disabled={!dirty || save.isPending}
          title={t('只改了名稱、說明、人工確認、選項的名稱 / 顏色 / 快速鍵:直接存,不產生新版本。改了範圍、規則、選項的值:存成新版本')}>{t('儲存')}</Button>
      </>}>
      <ErrorText error={q.error || save.error || restore.error} />
      {save.data && !dirty && <div className="text-sm text-emerald-700 bg-emerald-50 border border-emerald-200 rounded-md px-3 py-2">
        {save.data.settings_only
          ? <>{t('已儲存設定(名稱、說明、人工確認、快速鍵這類):設計沒變,仍是 v{version},不用重新產生標籤。', { version: save.data.version })}</>
          : <>{t('已儲存為 v{version}。如果改了範圍或規則參數,請到「自動標註」按「產生標籤」讓舊畫面套用新設定。', { version: save.data.version })}</>}</div>}

      <div className="grid grid-cols-[240px_1fr] gap-4 items-start">
        <div className="flex flex-col gap-3">
          <div className="bg-white border border-stone-200 rounded-lg overflow-hidden">
            {states.map((s, i) => (
              <button key={i} onClick={() => setSel(i)}
                className={`w-full text-left px-3 py-2.5 border-b border-stone-100 flex items-start gap-2 ${i === sel ? 'bg-stone-100' : 'hover:bg-stone-50'}`}>
                <span className="w-2.5 h-2.5 rounded-sm mt-1.5 shrink-0" style={{ background: stateColor(i) }} />
                <span className="flex-1 min-w-0">
                  <span className="block text-sm font-medium truncate">{s.name}</span>
                  <span className="block text-xs text-stone-500">{TYPE_TEXT[s.type]} · {SOURCE_TEXT[s.source.kind]}{s.review?.enabled ? t(' · 人工確認') : ''}</span>
                  {judge.data?.states[s.id] && <span className={`inline-block mt-0.5 px-1.5 rounded text-[11px] ${JUDGE_TAG[judge.data.states[s.id].source][1]}`}
                    title={judge.data.states[s.id].reason}>{JUDGE_TAG[judge.data.states[s.id].source][0]}</span>}
                  <span className="block"><MiniRail p={prog.data?.states[s.id]} /></span>
                </span>
              </button>
            ))}
            <button onClick={addState} className="w-full text-left px-3 py-2.5 text-sm text-stone-600 hover:bg-stone-50">{t('+ 新增狀態')}</button>
          </div>
        </div>

        <Modal open={versions} title={t('版本紀錄(目前 v{p1})', { p1: schema?.version ?? '–' })} onClose={() => setVersions(false)}>
            <div className="flex flex-col gap-2 text-xs max-h-72 overflow-auto">
              {q.data?.history.slice().reverse().map(h => (
                <div key={h.version} className="flex flex-col gap-0.5 border-b border-stone-100 pb-2">
                  <div className="flex justify-between items-center">
                    <span className="font-medium">v{h.version}{h.version === schema?.version && <span className="text-emerald-700"> {t('· 使用中')}</span>}</span>
                    {h.version !== schema?.version && <button className="text-stone-500 underline" onClick={() => restore.mutate(h.version)}>{t('還原')}</button>}
                  </div>
                  <span className="text-stone-500">{t('{p1} · {states} 個狀態', { p1: dateTime(h.created), states: h.states })}</span>
                  {h.note && <span className="text-stone-600">{h.note}</span>}
                </div>
              ))}
            </div>
        </Modal>
        {cur ? <StateEditor key={sel} s={cur} index={sel} all={states} judge={judge.data} progress={prog.data?.states[cur.id]} onChange={fn => update(sel, fn)}
          onDelete={() => { setDraft(d => (d ?? []).filter((_, i) => i !== sel)); setSel(0) }} /> : <Card><Empty>{t('讀取中…')}</Empty></Card>}
      </div>
    </Page>
  )
}

function StateEditor({ s, index, all, judge, progress, onChange, onDelete }: {
  s: StateDef; index: number; all: StateDef[]; judge?: JudgeInfo; progress?: StateProgress
  onChange: (fn: (s: StateDef) => void) => void; onDelete: () => void
}) {
  const [active, setActive] = useState(0)
  const [seed, setSeed] = useState(1)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [more, setMore] = useState<'more' | 'gallery' | null>(null)
  const hasParams = !!(s.source.params && Object.keys(s.source.params).length > 0 && !(s.source.rule && RULE_KINDS[s.source.rule]) && s.source.kind !== 'gallery')
  const frames = useQuery({ queryKey: ['randomFrames', seed], queryFn: () => api.randomFrames(13, seed) })
  const sample = frames.data?.[0]
  const previews = frames.data?.slice(1) ?? []
  const roi = s.rois[active]
  const color = stateColor(index)
  const usedKeys = useMemo(() => new Set(all.filter(x => x !== s && x.review?.enabled).flatMap(x => (x.classes ?? []).map(c => c.key).filter(Boolean))), [all, s])

  return (
    <div className="flex flex-col gap-4 min-w-0">
      <Card title={<span className="flex items-center gap-2">{s.name}{s.plugin && <Pill>{t('外掛:{plugin}', { plugin: s.plugin })}</Pill>}</span>}
        extra={<span className="flex gap-2">
          {s.source.kind === 'gallery' && <MoreButton onClick={() => setMore('gallery')}>{t('名稱庫設定')}</MoreButton>}
          <MoreButton onClick={() => setMore('more')}>{t('⋯ 更多')}</MoreButton></span>}>
        <div className="grid md:grid-cols-2 gap-x-6 gap-y-3 text-sm">
          <label className="flex flex-col gap-1"><span className="text-stone-600">{t('顯示名稱')}</span>
            <input id="st-name" className={input} value={s.name} onChange={e => onChange(x => { x.name = e.target.value })} /></label>
          <label className="flex flex-col gap-1"><span className="text-stone-600">{t('說明')}</span>
            <input id="st-desc" className={input} value={s.description ?? ''} onChange={e => onChange(x => { x.description = e.target.value })} /></label>
          <label className="flex flex-col gap-1"><span className="text-stone-600">{t('類型')}</span>
            <select id="st-type" className={input} value={s.type} disabled={!!s.plugin} onChange={e => onChange(x => {
                x.type = e.target.value as StateDef['type']
                if (x.type === 'gallery') { x.source = { kind: 'gallery', params: { cut: 'box' } }; delete x.classes }
                else if (x.type === 'number') { x.source = { kind: 'rule', rule: 'digits', params: defaultParams('digits', x) }; delete x.classes }
                else if (x.type === 'ratio' && x.source.kind === 'rule') { x.source = { kind: 'rule', rule: 'bar', params: defaultParams('bar', x) }; delete x.classes }
                else if (x.source.kind === 'gallery') x.source = { kind: 'manual' }
              })}>
              {Object.entries(TYPE_TEXT).map(([k, tx]) => <option key={k} value={k}>{tx}</option>)}</select></label>
          <label className="flex flex-col gap-1"><span className="text-stone-600">{t('標籤來源')}</span>
            <select id="st-src" className={input} value={s.source.kind} disabled={!!s.plugin} onChange={e => onChange(x => {
                x.source = { kind: e.target.value as StateDef['source']['kind'] }
                if (x.type === 'gallery') x.source = { kind: 'gallery', params: { cut: 'box' } }
                else if (x.source.kind !== 'manual' && x.source.kind !== 'rule') x.source.kind = 'manual'
              })}>
              {Object.entries(SOURCE_TEXT).filter(([k]) => !!s.plugin || k === s.source.kind || (s.type === 'gallery' ? k === 'gallery' : k === 'rule' || k === 'manual'))
                .map(([k, tx]) => <option key={k} value={k}>{tx}</option>)}</select></label>
          {(s.type === 'class' || s.type === 'number') && <label className="flex flex-col gap-1 md:col-span-2">
            <span className="text-stone-600">{t('執行時的判斷方式')}</span>
            <span className="flex flex-wrap items-center gap-2">
              <select id="st-judge" className={input} value={s.judge ?? 'auto'}
                onChange={e => onChange(x => { if (e.target.value === 'auto') delete x.judge; else x.judge = e.target.value as JudgeMode })}>
                <option value="auto">{t('自動(建議)')}</option>
                <option value="model">{t('只用模型')}</option>
                <option value="rule">{t('只用規則')}</option>
              </select>
              {judge?.states[s.id] && <span className="text-xs text-stone-500">{t('目前:{reason}', { reason: judge.states[s.id].reason })}</span>}
            </span>
            <span className="text-xs text-stone-500">
              {(s.judge ?? 'auto') === 'auto' ? t('自動:模型通過考試就用模型,模型沒把握時由畫面規則幫忙確認;規則考得明顯比較好(或模型還沒學過)才整個交給規則。')
                : s.judge === 'model' ? t('只用模型:畫面規則完全不參與(規則在某些畫面不可靠時用)。模型還沒學過時會先用規則。')
                : t('只用規則:不看模型(規則本身就是標準答案時用)。這個狀態沒有畫面規則時會照自動處理。')}
              {t('這是設定,儲存時不會產生新版本。')}</span>
          </label>}
          {s.type === 'number' && <div className="md:col-span-2 flex flex-wrap gap-3 items-end">
            <label className="flex flex-col gap-1"><span className="text-stone-600">{t('單位(可不填)')}</span>
              <input id="st-unit" className={`${input} w-24`} value={s.unit ?? ''} onChange={e => onChange(x => { x.unit = e.target.value || undefined })} /></label>
            <label className="flex flex-col gap-1"><span className="text-stone-600">{t('最小值')}</span>
              <input id="st-min" type="number" className={`${input} w-28 num`} value={s.min ?? ''} onChange={e => onChange(x => { x.min = e.target.value === '' ? undefined : Number(e.target.value) })} /></label>
            <label className="flex flex-col gap-1"><span className="text-stone-600">{t('最大值')}</span>
              <input id="st-max" type="number" className={`${input} w-28 num`} value={s.max ?? ''} onChange={e => onChange(x => { x.max = e.target.value === '' ? undefined : Number(e.target.value) })} /></label>
            <span className="text-xs text-stone-500 pb-1.5">{t('讀到超出範圍的數字會當成「不確定」(多半是看錯了)')}</span>
          </div>}
          {!!!s.plugin && s.source.kind === 'manual' && <div className="text-xs text-stone-500 md:col-span-2">{t('人工標註:只能在「回答問題」手動回答,答案只進測試集,')}<b>{t('模型學不到')}</b>{t('。要讓模型學,請改成「畫面規則」。')}</div>}
          {s.source.rule && !RULE_KINDS[s.source.rule] && <div className="text-xs text-stone-500 md:col-span-2">{t('規則程式:')}<code>{s.source.rule}</code>{s.source.field && <> {t('· 欄位 {field}', { field: s.source.field })}</>}</div>}
          {s.source.field && !s.source.rule && <div className="text-xs text-stone-500 md:col-span-2">{t('來源欄位:{field}', { field: s.source.field })}</div>}
          <JudgeLine j={judge?.states[s.id]} info={judge} />
          <Rail p={progress} />
        </div>
      </Card>

      {s.type === 'class' && (
        <Card title={t('類別選項')}>
          <table className="w-full text-sm">
            <thead><tr className="text-xs text-stone-500 text-left">{[t('值'), t('顯示名稱'), t('顏色'), t('人工確認快速鍵'), ''].map(h => <th key={h} className="font-normal pb-2 pr-3">{h}</th>)}</tr></thead>
            <tbody>
              {(s.classes ?? []).map((c, i) => (
                <tr key={i} className="border-t border-stone-100">
                  <td className="py-1.5 pr-3"><input id={`c-v-${i}`} className={`${input} w-24 font-mono`} value={String(c.value)} disabled={!!s.plugin}
                    onChange={e => onChange(x => { x.classes![i].value = /^-?\d+$/.test(e.target.value) ? Number(e.target.value) : e.target.value })} /></td>
                  <td className="pr-3"><input id={`c-n-${i}`} className={`${input} w-28`} value={c.name} onChange={e => onChange(x => { x.classes![i].name = e.target.value })} /></td>
                  <td className="pr-3">
                    <select id={`c-c-${i}`} className={input} value={c.color} onChange={e => onChange(x => { x.classes![i].color = e.target.value })}>
                      {COLOR_NAMES.map(n => <option key={n} value={n}>{n}</option>)}</select>
                    <span className={`ml-2 px-2 py-0.5 rounded-full text-xs ${COLORS[c.color]?.pill}`}>{c.name}</span>
                  </td>
                  <td className="pr-3"><input id={`c-k-${i}`} maxLength={1} className={`${input} w-12 text-center font-mono ${c.key && usedKeys.has(c.key) ? 'border-rose-500' : ''}`}
                    value={c.key ?? ''} onChange={e => onChange(x => { x.classes![i].key = e.target.value.toLowerCase() })} /></td>
                  <td className="text-right">{!!!s.plugin && <button className="text-xs text-stone-500 underline" onClick={() => onChange(x => { x.classes!.splice(i, 1) })}>{t('移除')}</button>}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {!!!s.plugin && <button className="text-sm text-stone-600 mt-2" onClick={() => onChange(x => { x.classes = [...(x.classes ?? []), { value: `c${(x.classes?.length ?? 0) + 1}`, name: t('新選項'), color: 'stone', key: '' } as ClassDef] })}>{t('+ 新增選項')}</button>}
          <div className="flex flex-wrap gap-4 items-center text-sm mt-4 pt-3 border-t border-stone-100">
            <label className="flex items-center gap-2"><input id="rv-on" type="checkbox" checked={!!s.review?.enabled}
              onChange={e => onChange(x => { x.review = { ...(x.review ?? {}), enabled: e.target.checked } })} />{t('在「回答問題」出題')}</label>
            <label className="flex items-center gap-2">{t('放大顯示的範圍')}
              <select id="rv-roi" className={input} value={s.review?.roi ?? ''} onChange={e => onChange(x => { x.review = { ...(x.review ?? { enabled: false }), roi: e.target.value } })}>
                {s.rois.map(r => <option key={r.id} value={r.id}>{r.name}</option>)}</select></label>
            <label className="flex items-center gap-2">{t('放大倍數')}
              <input id="rv-scale" type="number" step={0.1} min={0.5} max={6} className={`${input} w-20 num`} value={s.review?.scale ?? 2}
                onChange={e => onChange(x => { x.review = { ...(x.review ?? { enabled: false }), scale: Number(e.target.value) } })} /></label>
          </div>
        </Card>
      )}

      <Card title={t('裁切範圍')} extra={<Button variant="ghost" onClick={() => setSeed(v => v + 1)}>{t('換一批畫面')}</Button>}>
        <div className="flex flex-wrap gap-2 mb-3">
          {s.rois.map((r, i) => (
            <button key={i} onClick={() => setActive(i)}
              className={`px-3 py-1.5 rounded-md text-sm border flex flex-col items-start gap-1 ${i === active ? 'border-stone-800 bg-stone-100' : 'border-stone-200'}`}>
              {r.name}
              <span className="flex flex-wrap gap-1">
                {roiUses(s, r.id).map(u => <span key={u.text} className={`text-[11px] px-1.5 rounded ${USE_STYLE[u.kind]}`}>{u.text}</span>)}
              </span>
            </button>
          ))}
          <button className="px-3 py-1 text-sm text-stone-600" onClick={() => {
            onChange(x => { x.rois.push({ id: `roi${x.rois.length + 1}`, name: t('範圍 {p1}', { p1: x.rois.length + 1 }), box: [560, 300, 160, 120] } as RoiDef) })
            setActive(s.rois.length)
          }}>{t('+ 新增範圍')}</button>
        </div>
        {roi && (
          <div className="grid xl:grid-cols-[1fr_300px] gap-4">
            <div className="flex flex-col gap-3">
              {sample ? <RoiEditor frame={sample} activeIndex={active}
                boxes={s.rois.map(r => ({ box: r.box, color, label: r.name }))}
                onChange={(b: Box) => onChange(x => { x.rois[active].box = b })} /> : <Empty>{t('讀取畫面中…')}</Empty>}
            </div>
            <div className="flex flex-col gap-2 text-sm">
              <div className="flex flex-col gap-1">
                <span className="text-stone-600">{t('用途(修改範圍會影響這些地方)')}</span>
                {roiUses(s, roi.id).map(u => <span key={u.text} className={`text-xs px-2 py-1 rounded ${USE_STYLE[u.kind]}`}>{u.text}</span>)}
                {roiUses(s, roi.id).some(u => u.kind === 'rule') &&
                  <span className="text-xs text-stone-500">{t('規則範圍改了之後,要到「自動標註」重新產生標籤才會套用到舊畫面')}</span>}
              </div>
              <label className="flex flex-col gap-1"><span className="text-stone-600">{t('名稱')}</span>
                <input id="roi-name" className={input} value={roi.name} onChange={e => onChange(x => { x.rois[active].name = e.target.value })} /></label>
              <label className="flex flex-col gap-1"><span className="text-stone-600">{t('代號')}</span>
                <input id="roi-id" className={`${input} font-mono`} value={roi.id} disabled={!!s.plugin}
                  onChange={e => onChange(x => { x.rois[active].id = e.target.value })} /></label>
              <div className="grid grid-cols-4 gap-1.5">
                {(['x', 'y', t('寬'), t('高')] as const).map((k, j) => (
                  <label key={k} className="flex flex-col gap-0.5 text-xs text-stone-500">{k}
                    <input id={`roi-${j}`} type="number" className={`${input} num`} value={roi.box[j]}
                      onChange={e => onChange(x => { x.rois[active].box[j] = Math.round(Number(e.target.value)) })} /></label>
                ))}
              </div>
              {!!!s.plugin && s.rois.length > 1 && <button className="text-xs text-stone-500 underline self-start"
                onClick={() => { onChange(x => { x.rois.splice(active, 1) }); setActive(0) }}>{t('移除這個範圍')}</button>}
            </div>
          </div>
        )}
        {roi && (
          <div className="mt-4 pt-3 border-t border-stone-100">
            <div className="text-xs text-stone-500 mb-2">{t('其他畫面在這個範圍的樣子(確認不會截斷、不會框到別的東西)')}</div>
            <div className="flex flex-wrap gap-3">
              {previews.map(f => <Zoom key={f} frame={f} box={roi.box} scale={2} maxWidth={260} />)}
            </div>
          </div>
        )}
      </Card>

      {!!!s.plugin && s.source.kind === 'rule' && (!s.source.rule || RULE_KINDS[s.source.rule]) && <RuleEditor s={s} all={all} onChange={onChange} />}
      <Modal open={more === 'gallery'} wide title={t('{name}:名稱庫設定', { name: s.name })} onClose={() => setMore(null)}>
        <GallerySettings s={s} onChange={onChange} />
      </Modal>
      <Modal open={more === 'more'} title={t('{name}:更多', { name: s.name })} onClose={() => setMore(null)}
        footer={<span className="text-xs text-stone-500 mr-auto">{t('改完記得按上方「儲存」')}</span>}>
        <label className="flex flex-col gap-1"><span className="text-stone-600">{t('代號(英文,用於資料欄位;改了舊資料會對不上)')}</span>
          <input id="st-id" className={`${input} font-mono`} value={s.id} disabled={!!s.plugin} onChange={e => onChange(x => { x.id = e.target.value })} /></label>
        {hasParams && <><div className="text-xs font-semibold text-stone-600 mt-2">{t('規則參數(改完需要重新產生標籤)')}</div>
          <div className="grid md:grid-cols-3 gap-3 text-sm">
            {Object.entries(s.source.params ?? {}).map(([k, v]) => (
              <label key={k} className="flex flex-col gap-1"><span className="text-stone-600 font-mono text-xs">{k}</span>
                <input id={`p-${k}`} className={`${input} num`} value={Array.isArray(v) ? v.join(', ') : String(v)}
                  onChange={e => onChange(x => {
                    const raw = e.target.value
                    x.source.params![k] = Array.isArray(v) ? raw.split(',').map(tx => Number(tx.trim())) : (raw === '' || isNaN(Number(raw)) ? raw : Number(raw))
                  })} /></label>
            ))}
          </div>
        </>}
        {!s.plugin && <div className="border-t border-stone-200 pt-3 mt-2">{confirmDelete
          ? <span className="flex gap-2 items-center text-xs"><span className="text-rose-700">{t('確定刪除這個狀態?')}</span>
              <Button variant="danger" onClick={() => { setMore(null); onDelete() }}>{t('刪除')}</Button><Button variant="ghost" onClick={() => setConfirmDelete(false)}>{t('取消')}</Button></span>
          : <Button variant="ghost" onClick={() => setConfirmDelete(true)}>{t('刪除這個狀態')}</Button>}</div>}
      </Modal>

    </div>
  )
}

/** A name gallery: how its row (the first region) is cut, and how sure a match must be. */
function GallerySettings({ s, onChange }: { s: StateDef; onChange: (fn: (s: StateDef) => void) => void }) {
  const g = useQuery({ queryKey: ['galleries'], queryFn: api.galleries })
  const p = s.source.params ?? {}
  const set = (k: string, v: unknown) => onChange(x => { x.source.params = { ...(x.source.params ?? {}), [k]: v } })
  const input = 'border border-stone-300 rounded-md px-2 py-1 text-sm'
  return (
    <div>
      <p className="text-xs text-stone-500 mb-3">{t('每張畫面從第一個範圍(名稱所在的那一列)切出名稱,和名稱庫比對;沒認出的會分群,到「回答問題」的「{name}」分頁命名一次就好。', { name: s.name })}</p>
      <div className="grid md:grid-cols-2 gap-x-6 gap-y-3 text-sm">
        <label className="flex flex-col gap-1"><span className="text-stone-600">{t('切割方式')}</span>
          <select id="gal-cut" className={input} value={p.cut ?? 'box'} onChange={e => set('cut', e.target.value)}>
            {Object.entries(g.data?.cuts ?? { box: t('整個範圍') }).map(([k, tx]) => <option key={k} value={k}>{tx}</option>)}</select></label>
        <label className="flex flex-col gap-1"><span className="text-stone-600">{t('比對門檻(0~1,越高越嚴)')}</span>
          <input id="gal-min" type="number" step="0.01" min="0.5" max="1" className={input} value={p.match_min ?? 0.85} onChange={e => set('match_min', Number(e.target.value))} /></label>
        <label className="flex flex-col gap-1"><span className="text-stone-600">{t('寬度容許誤差(px)')}</span>
          <input id="gal-tol" type="number" min="0" max="50" className={input} value={p.width_tol ?? 5} onChange={e => set('width_tol', Number(e.target.value))} /></label>
        <label className="flex flex-col gap-1"><span className="text-stone-600">{t('這些標記的畫面不拿來命名(逗號分隔)')}</span>
          <input id="gal-skip" className={`${input} font-mono`} value={(p.skip_flags ?? []).join(', ')}
            onChange={e => set('skip_flags', e.target.value.split(',').map(x => x.trim()).filter(Boolean))} /></label>
      </div>
    </div>
  )
}
