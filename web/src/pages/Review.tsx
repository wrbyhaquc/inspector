import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { api, browseLink, type AnswerValue, type Decision, type StateDef } from '../api'
import { FrameView, preloadFrames, useImageReady, Zoom } from '../components/FrameView'
import { Button, Card, Empty, ErrorText, Page } from '../components/ui'
import { pct } from '../lib/format'
import { usePersistentState } from '../lib/persist'
import { COLORS, mainRoi, reviewStates, stateColor, useSchema } from '../lib/schema'
import GalleryNaming from './GalleryNaming'
import { t } from '../i18n'
import { words } from '../lib/project'

type Answers = Record<string, AnswerValue | null>
const SKIP = '__skip__'          // "can't judge this question" (e.g. the icon is covered): not saved as an answer

const valueName = (s: StateDef | undefined, v: unknown) =>
  s?.classes?.find(c => c.value === v)?.name ?? (v == null ? t('無法判斷') : String(v))

export default function Review() {
  const [saved, setTab] = usePersistentState<string>('review.tab', 'labels')
  const sch = useSchema()
  // one tab per name gallery (states whose answer is a name the user gives once)
  const galleries = (sch.data?.schema.states ?? []).filter(s => s.source.kind === 'gallery')
  const tab = galleries.some(g => g.id === saved) ? saved : 'labels'
  return (
    <Page title={t('回答問題')} desc={tab === 'labels'
      ? t('逐張看畫面回答問題。題目由「要看的狀態」決定。這份答案是測試集,用來衡量自動標籤和之後模型的真實準確率。預設不顯示自動標籤,避免被影響。')
      : t('替畫面上切出來的名稱命名。每個不同的名稱只要命名一次,之後產生標籤時就靠這份名稱庫辨識。')}>
      {galleries.length > 0 && <div className="flex rounded-md border border-stone-300 overflow-hidden w-fit">
        {[['labels', t('狀態確認')], ...galleries.map(g => [g.id, g.name])].map(([k, tx]) => (
          <button key={k} onClick={() => setTab(k)} className={`px-4 py-1.5 text-sm ${tab === k ? 'bg-stone-900 text-white' : 'bg-white hover:bg-stone-50'}`}>{tx}</button>
        ))}
      </div>}
      {tab !== 'labels' ? <GalleryNaming sid={tab} /> : sch.data ? <LabelReview states={sch.data.schema.states} /> : <ErrorText error={sch.error} />}
    </Page>
  )
}

function LabelReview({ states }: { states: StateDef[] }) {
  const qc = useQueryClient()
  const navigate = useNavigate()
  const allQuestions = useMemo(() => reviewStates(states), [states])
  // ?state=<id>: ask only this question, on the frames that have no answer for it yet
  const [params, setParams] = useSearchParams()
  const focus = allQuestions.find(q => q.id === params.get('state')) ?? null
  const runtimeMode = params.get('origin') === 'runtime'      // frames the scripts saved (with a state picked: only that question)
  const questions = useMemo(() => focus ? [focus] : allQuestions, [focus, allQuestions])
  const keyMap = useMemo(() => {
    const m: Record<string, [string, AnswerValue]> = {}
    for (const s of questions) for (const c of s.classes!) if (c.key) m[c.key.toLowerCase()] = [s.id, c.value]
    return m
  }, [questions])
  const queue = useQuery({ queryKey: ['reviewQueue'], queryFn: api.reviewQueue })
  // which question helps most now (the model's weakest first), and putting aside the frames only about states it knows well
  const prio = useQuery({ queryKey: ['reviewPrio'], queryFn: api.reviewPriorities, enabled: runtimeMode,
    refetchInterval: q => q.state.data?.tidy.job?.status === 'running' ? 2000 : false })
  // tidying finished: the questions changed
  const tidyRunning = prio.data?.tidy.job?.status === 'running'
  const [wasTidying, setWasTidying] = useState(false)
  useEffect(() => {
    if (tidyRunning) setWasTidying(true)
    else if (wasTidying) { setWasTidying(false); qc.invalidateQueries({ queryKey: ['reviewQueue'] }) }
  }, [tidyRunning, wasTidying, qc])
  // one round = the frames picked as most worth answering for the chosen question (not every frame there is)
  const [roundOnly, setRoundOnly] = usePersistentState('review.roundOnly', true)
  const best = useMemo(() => (focus && prio.data?.states.find(p => p.state === focus.id)?.best) || [], [focus, prio.data])
  const prioOf = useMemo(() => Object.fromEntries((prio.data?.states ?? []).map(p => [p.state, p])), [prio.data])
  const putAside = useMutation({ mutationFn: (restore: boolean) => api.reviewPutAside(restore),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['reviewQueue'] }); qc.invalidateQueries({ queryKey: ['reviewPrio'] }) } })
  // a saved frame asks only what it still asks (all of why it was saved when it has not been looked at again)
  const asks = (i: { ask?: string[] | null; reasons?: { state: string }[] }) => i.ask ?? (i.reasons ?? []).map(x => x.state)
  const stats = useQuery({ queryKey: ['reviewStats'], queryFn: api.reviewStats })
  const [onlyCheck, setOnlyCheck] = usePersistentState('review.onlyCheck', true)
  // frames answered in this visit leave the "needs your check" list right away (before the queue refetches)
  const [answered, setAnswered] = useState<Set<string>>(new Set())
  // only one recording (the one made to catch a state): its frames are asked, and new questions come from it
  const [pickSession, setPickSession] = usePersistentState('review.session', '')
  const [pickDevice, setPickDevice] = usePersistentState('review.device', '')
  const sessions = useQuery({ queryKey: ['sessions'], queryFn: api.sessions, enabled: !!focus })
  const allItems = useMemo(() => (queue.data?.items ?? []).filter(i =>
    !focus || !pickSession || (i.session === pickSession && (!pickDevice || i.device === pickDevice))), [queue.data, focus, pickSession, pickDevice])
  const items = useMemo(() => focus && runtimeMode && roundOnly && best.length
    ? best.map(f => allItems.find(i => i.frame === f)).filter((i): i is NonNullable<typeof i> => !!i && !answered.has(i.frame)
        && i.decision?.answers?.[focus.id] == null && !i.decision?.skipped?.includes(focus.id))
    : focus && runtimeMode
    // saved while scripts ran, not answered for this state yet; the frames saved because of this very state first
    ? allItems.filter(i => i.origin !== 'testset' && !answered.has(i.frame) && !i.decision && (i.origin === 'flag' || asks(i).includes(focus.id)))
        // the model's least sure first (no confidence for this state = after those that have one)
        .sort((a, b) => (a.conf?.[focus.id] ?? 2) - (b.conf?.[focus.id] ?? 2))
    : focus
    ? allItems.filter(i => !answered.has(i.frame) && i.decision?.answers?.[focus.id] == null && !i.decision?.skipped?.includes(focus.id))
    : runtimeMode ? allItems.filter(i => i.origin !== 'testset' && !i.decision && !answered.has(i.frame) && (i.origin === 'flag' || asks(i).length > 0))
    : onlyCheck ? allItems.filter(i => i.needs_human && !answered.has(i.frame)) : allItems, [allItems, onlyCheck, answered, focus, runtimeMode, roundOnly, best])
  const [idx, setIdx] = useState<number | null>(null)
  const [answers, setAnswers] = useState<Answers>({})
  const [showRule, setShowRule] = useState(false)

  useEffect(() => { setIdx(null) }, [onlyCheck, focus?.id, runtimeMode])
  const add = useMutation({
    mutationFn: () => api.reviewAddQuestions(focus!.id, 30, pickSession || undefined, pickDevice || undefined),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['reviewQueue'] }); qc.invalidateQueries({ queryKey: ['statesProgress'] }) },
  })
  useEffect(() => {
    if (idx === null && items.length) {
      const first = items.findIndex(i => !i.decision)
      setIdx(first === -1 ? 0 : first)
    } else if (idx !== null && idx >= items.length && items.length) setIdx(items.length - 1)
  }, [items, idx])
  const item = idx !== null ? items[idx] : undefined
  // frames saved while scripts ran: answer what the model was unsure about; the other answers are pre-filled
  // from the automatic label (shown dashed) and only saved if you change them
  const quick = runtimeMode && !!item && item.origin !== 'testset'
  const required = useMemo(() => {
    if (!quick || !item || focus) return questions.map(q => q.id)      // one question picked: that one is asked
    const r = new Set(asks(item))
    return questions.filter(q => r.has(q.id)).map(q => q.id)
  }, [quick, item, questions, focus])
  const prefill = useMemo(() => {
    const out: Record<string, AnswerValue> = {}
    if (!quick || !item) return out
    for (const q of questions) {
      const v = item.rule[q.id]
      if (!required.includes(q.id) && q.classes!.some(c => c.value === v)) out[q.id] = v as AnswerValue
    }
    return out
  }, [quick, item, questions, required])
  const shown = useMemo(() => quick                     // the ones to answer on top (next to the picture), the pre-filled ones below
    ? [...questions.filter(q => required.includes(q.id)), ...questions.filter(q => !required.includes(q.id))] : questions,
  [quick, questions, required])
  // answers only count for a frame that is really on screen: wait until its image has loaded
  const img = useImageReady(item?.frame)
  const ready = img.ready
  // the server prepares the next 20 (fast JPEG copies), the browser downloads the next 6
  const upcoming = useMemo(() => idx === null ? [] : items.slice(idx + 1, idx + 21).map(i => i.frame), [idx, items])
  useEffect(() => { preloadFrames(upcoming.slice(0, 6)) }, [upcoming])
  const warmKey = upcoming.slice(0, 20).join('|')
  useEffect(() => { if (upcoming.length) api.imageWarm(upcoming).catch(() => undefined) }, [warmKey]) // eslint-disable-line react-hooks/exhaustive-deps
  // Claude's answer is not pre-filled on frames it asked you to check, so it doesn't sway your answer
  const blind = !focus && !!item?.needs_human && !answered.has(item.frame)
  useEffect(() => {
    const a: Answers = blind ? {} : { ...(item?.decision?.answers ?? {}) }
    // a saved decision without an answer for a question = that question was skipped
    if (!blind && !focus && item?.decision) for (const q of questions) if (a[q.id] == null) a[q.id] = SKIP
    setAnswers(a)
  }, [item?.frame]) // eslint-disable-line react-hooks/exhaustive-deps

  const save = useMutation({
    mutationFn: (d: Decision) => api.reviewDecide(d),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['reviewQueue'] }); qc.invalidateQueries({ queryKey: ['reviewStats'] }) },
  })
  const go = useCallback((delta: number) => {
    setIdx(i => (i === null ? i : Math.max(0, Math.min(items.length - 1, i + delta))))
  }, [items.length])

  const commit = useCallback((next: Answers) => {
    if (!item) return
    // keep the answers to the other questions (a focused round only asks one)
    const saved = Object.fromEntries(Object.entries({ ...(item.decision?.answers ?? {}), ...next }).filter(([, v]) => v !== SKIP && v != null))
    const skipped = [...new Set([...(item.decision?.skipped ?? []), ...Object.keys(next).filter(k => next[k] === SKIP)])].filter(k => !(k in saved))
    save.mutate({ frame: item.frame, session: item.session, device: item.device, id: item.id, answers: saved, skipped,
      use: item.use === 'train' ? 'train' : undefined })
    if (onlyCheck || focus || runtimeMode) setAnswered(a => new Set(a).add(item.frame))   // list shrinks: the next frame slides into this slot
    else go(1)
  }, [item, save, go, onlyCheck, focus, runtimeMode])

  // answering every required question saves and moves on automatically
  const pick = useCallback((stateId: string, value: AnswerValue) => {
    if (!item || !ready) return
    const next = { ...answers, [stateId]: value }
    setAnswers(next)
    if (quick ? required.length > 0 && required.every(id => next[id] != null) : questions.every(q => next[q.id] != null)) commit(next)
  }, [answers, item, questions, ready, quick, required, commit])

  useEffect(() => {
    const k = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement).tagName
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return
      const key = e.key.toLowerCase()
      if (e.repeat) { e.preventDefault(); return }        // a held-down key answers once, not 30 frames a second
      if (keyMap[key]) pick(...keyMap[key])
      else if (key === 'enter' && quick && ready && required.every(id => answers[id] != null)) commit(answers)
      else if (key === 'arrowright') go(1)
      else if (key === 'arrowleft' || key === 'backspace') go(-1)
      else return
      e.preventDefault()
    }
    window.addEventListener('keydown', k)
    return () => window.removeEventListener('keydown', k)
  }, [keyMap, pick, go, quick, ready, required, answers, commit])

  const done = queue.data?.done ?? 0, total = items.length
  const toCheck = Math.max(0, (queue.data?.needs_human ?? 0) - [...answered].filter(f => allItems.some(i => i.frame === f && i.needs_human)).length)
  const s = stats.data
  const dec = item?.decision
  if (!questions.length) return <Card><Empty>{t('「要看的狀態」裡沒有開啟人工確認的狀態')}</Empty></Card>
  const dist = focus ? s?.states[focus.id]?.distribution ?? {} : {}

  return (
    <>
      <ErrorText error={queue.error || save.error || add.error} />
      {focus && (
        <div className="rounded-md border border-amber-300 bg-amber-50 px-4 py-3 text-sm flex flex-wrap items-center gap-x-4 gap-y-2">
          <span>{t('只問「')}<b>{focus.name}</b>{t('」:還有')} <b className="num">{items.length}</b> {t('張沒回答這一題')}</span>
          <span className="text-stone-600 num">{t('目前答案:{p1}', { p1: focus.classes!.filter(c => c.value !== 'hidden').map(c => `${c.name} ${dist[String(c.value)] ?? 0}`).join(t('、')) })}</span>
          <span className="flex items-center gap-2 ml-auto">
            {add.data && <span className="text-emerald-700 text-xs">{t('已補 {added} 題({p2})', { added: add.data.added, p2: Object.entries(add.data.by_answer).map(([k, v]) => `${k} ${v}`).join(t('、')) })}</span>}
            <select value={pickSession} onChange={e => { setPickSession(e.target.value); setPickDevice('') }}
              className={`border rounded-md px-2 py-1 text-sm ${pickSession ? 'border-2 border-rose-500 bg-rose-50 font-semibold' : 'border-stone-300 bg-white'}`}
              title={t('只看這個場次的畫面;補考題也從這個場次挑')}>
              <option value="">{t('所有場次')}</option>
              {sessions.data?.filter(x => !runtimeMode || (queue.data?.items ?? []).some(i => i.origin !== 'testset' && i.session === x.id))
                .map(x => <option key={x.id} value={x.id}>{t('場次 {id}', { id: x.id })}</option>)}
            </select>
            {pickSession && (
              <select value={pickDevice} onChange={e => setPickDevice(e.target.value)} className="border border-stone-300 rounded-md px-2 py-1 text-sm bg-white">
                <option value="">{t('所有{device}', { device: words.device })}</option>
                {sessions.data?.find(x => x.id === pickSession)?.devices.map(d => <option key={d.name} value={d.name}>{d.name}</option>)}
              </select>
            )}
            <Button onClick={() => add.mutate()} disabled={add.isPending} title={t('從錄過的畫面裡,挑自動標註說有出現各種答案的畫面(各種答案平均),補成新的考題')}>
              {add.isPending ? t('挑選中…') : pickSession ? t('從這個場次補 30 題「{name}」的考題', { name: focus.name }) : t('補 30 題「{name}」的考題', { name: focus.name })}</Button>
          </span>
        </div>
      )}
      <div className="flex items-center gap-3 flex-wrap">
        <div className="flex rounded-md border border-stone-300 overflow-hidden w-fit text-sm">
          <button onClick={() => { setParams({}); setOnlyCheck(true) }} className={`px-3 py-1 ${!focus && !runtimeMode && onlyCheck ? 'bg-violet-600 text-white' : 'bg-white hover:bg-stone-50'}`}>{t('需要您確認({toCheck})', { toCheck })}</button>
          <button onClick={() => setParams(focus ? { origin: 'runtime', state: focus.id } : { origin: 'runtime' })} title={t('腳本執行時,模型拿不準或被標記「判斷錯了」而存下的畫面')}
            className={`px-3 py-1 ${runtimeMode ? 'bg-sky-600 text-white' : 'bg-white hover:bg-stone-50'}`}>{t('執行時存下、還要回答的({p1})', { p1: Math.max(0, (queue.data?.runtime_todo ?? 0) - [...answered].filter(f => allItems.some(i => i.frame === f && i.origin !== 'testset')).length) })}</button>
          <button onClick={() => { setParams({}); setOnlyCheck(false) }} className={`px-3 py-1 ${!focus && !runtimeMode && !onlyCheck ? 'bg-stone-900 text-white' : 'bg-white hover:bg-stone-50'}`}
            title={t('所有畫面,包括已經回答過的(可以回頭修改)')}>{t('所有畫面(含已答)')}</button>
        </div>
        <label className="text-sm flex items-center gap-1.5">{t('只問一題')}
          <select value={focus?.id ?? ''} onChange={e => setParams({ ...(runtimeMode ? { origin: 'runtime' } : {}), ...(e.target.value ? { state: e.target.value } : {}) })}
            className={`border rounded-md px-2 py-1 text-sm ${focus ? 'border-amber-500 bg-amber-50' : 'border-stone-300'}`}>
            <option value="">{t('(全部題目)')}</option>
            {(runtimeMode && prio.data ? [...allQuestions].sort((a, b) => (prio.data!.states.findIndex(p => p.state === a.id) + 1 || 99) - (prio.data!.states.findIndex(p => p.state === b.id) + 1 || 99)) : allQuestions)
              .map(q => { const p = runtimeMode ? prioOf[q.id] : undefined
                return <option key={q.id} value={q.id}>{p ? `${p.level === 'suggest' ? '★ ' : ''}${q.name}【${p.level_text}】${p.why}`
                  + (p.need != null ? (p.median_conf != null ? t('|腳本要信心 {need},目前中位數 {median}', { need: p.need.toFixed(2), median: p.median_conf.toFixed(2) })
                    : t('|腳本要信心 {need}', { need: p.need.toFixed(2) })) : t('|沒有腳本用到'))
                  + (p.best.length ? t('|這輪挑好 {length} 題', { length: p.best.length }) : '') : q.name}</option> })}
          </select></label>
        {runtimeMode && prio.data && (() => {
          const top = prio.data.states.filter(p => p.level === 'suggest')
          return (
            <div className="w-full flex flex-wrap items-center gap-2 text-xs rounded-md bg-sky-50 border border-sky-200 px-3 py-1.5">
              <span className="text-sky-900">{top.length ? <>{t('建議先答:')}{top.map(p => <button key={p.state} className="underline mr-2" onClick={() => setParams({ origin: 'runtime', state: p.state })}>{p.name}</button>)}</>
                : t('模型目前每一題都考得不錯,沒有特別需要先答的')}</span>
              {focus && prioOf[focus.id] && (() => { const p = prioOf[focus.id]; const left = items.length
                return <span className="w-full text-sky-900">
                  {t('「{name}」:腳本要的信心 {p2},目前模型(「{model}」上線後存下的畫面)低於它的有', { name: focus.name, p2: p.need != null ? p.need.toFixed(2) : '—', model: prio.data!.model })} <b>{p.stuck}</b> {t('張。')}
                  {p.best.length ? <> {t('這輪挑了')} <b>{p.best.length}</b> {t('題最值得答的(最沒把握、彼此不重複、各種答案都有),')}
                    {roundOnly ? (left ? <> {t('還剩')} <b>{left}</b> {t('題。')}</> : <b> {t('這輪答完了 ✔ 建議先重新訓練,再看這題還要不要答。')}</b>) : null}
                    <label className="ml-2 inline-flex items-center gap-1"><input type="checkbox" checked={roundOnly} onChange={e => setRoundOnly(e.target.checked)} />{t('只答挑好的題')}</label></>
                    : t(' 目前沒有需要特別挑的題目。')}
                </span> })()}
              <span className="flex-1" />
              <span className="w-full flex flex-wrap items-center gap-2 text-stone-600">
                {tidyRunning ? <span className="text-sky-800">{t('整理題目中:用目前的模型重新看每一張沒答的畫面…')}</span>
                  : !prio.data.tidy.current ? <span className="text-amber-800">{t('模型換過了,題目還沒用新模型重新整理(題數可能偏多)')}</span>
                  : <span>{t('題目已用目前的模型整理過:收起 {learned} 張模型已經會的、{dupes} 張重複的(同一台、兩分鐘內問一樣的)', { learned: prio.data.tidy.learned, dupes: prio.data.tidy.dupes })}{prio.data.tidy.user ? t(',另外您收起的 {user} 張', { user: prio.data.tidy.user }) : ''}</span>}
                <Button variant="ghost" disabled={putAside.isPending || tidyRunning} onClick={() => putAside.mutate(false)}
                  title={t('用目前的模型重新看每一張還沒回答的畫面:模型已經有把握(有畫面規則時:和規則一致)的題不再問,重複的畫面收起。不會刪除,訓練完也會自動整理')}>{t('整理題目')}</Button>
                {prio.data.put_aside > 0 && <Button variant="ghost" disabled={putAside.isPending || tidyRunning}
                  onClick={() => { if (confirm(t('把收起的 {put_aside} 張全部拿回來?(之後按「整理題目」可以再收起)', { put_aside: prio.data!.put_aside }))) putAside.mutate(true) }}>{t('恢復收起的 {put_aside} 張', { put_aside: prio.data.put_aside })}</Button>}
              </span>
            </div>
          )
        })()}
        <div className="flex-1 h-2 bg-stone-200 rounded-full overflow-hidden min-w-24"><div className="h-full bg-violet-500" style={{ width: `${queue.data?.total ? (done / queue.data.total) * 100 : 0}%` }} /></div>
        <span className="text-sm num text-stone-600">{t('已有答案 {done} / {p2}', { done, p2: queue.data?.total ?? 0 })}
          {s && <span className="text-stone-400">{t('(您 {p1} · Claude 預標 {p2})', { p1: s.by_reviewer?.human ?? 0, p2: s.by_reviewer?.claude ?? 0 })}</span>}</span>
      </div>
      {item ? (
        <div className="grid xl:grid-cols-[1fr_380px] gap-4">
          <div className="flex flex-col gap-3">
            <div className="relative">
              <FrameView fast frame={item.frame} overlays={questions.map(q => ({ box: mainRoi(q).box, color: stateColor(states.indexOf(q)), label: q.name }))} />
              {!ready && <div className="absolute inset-0 flex flex-col gap-2 items-center justify-center bg-stone-900/80 text-stone-100 rounded-md text-sm">
                {img.failed ? <>{t('畫面載入失敗(伺服器可能正在重新啟動)')}<Button onClick={img.retry}>{t('重新載入')}</Button></> : t('畫面載入中…(載入完才能作答)')}
              </div>}
            </div>
            <div className="flex gap-6 flex-wrap items-end">
              {questions.map(q => ready
                ? <Zoom fast key={q.id} frame={item.frame} box={mainRoi(q).box} scale={q.review?.scale ?? 2} maxWidth={720} label={`${q.name}(${mainRoi(q).name})`}
                    pad={q.source?.kind === 'rule' && q.source?.rule === 'template' ? Number(q.source?.params?.search ?? 0) : 0} />
                : <div key={q.id} className="rounded border border-stone-300 bg-stone-200 text-xs text-stone-500 flex items-center justify-center"
                    style={{ width: Math.min(mainRoi(q).box[2] * (q.review?.scale ?? 2), 720), height: Math.min(mainRoi(q).box[2] * (q.review?.scale ?? 2), 720) * mainRoi(q).box[3] / mainRoi(q).box[2] }}>{t('載入中…')}</div>)}
            </div>
          </div>

          <div className="flex flex-col gap-3">
            <Card title={<span>{t('第 {p1} / {total} 張', { p1: idx! + 1, total })} <span className="ml-1 px-1.5 py-0.5 rounded bg-stone-900 text-white text-xs num">#{allItems.findIndex(i => i.frame === item.frame)}</span></span>}
              extra={<span className="text-xs text-stone-500 num select-all" title={t('畫面編號(可在資料瀏覽搜尋)')}>{item.device} · {item.id}</span>}>
              <div className="flex flex-col gap-4">
                {item.origin && item.origin !== 'testset' && (
                  <div className="text-xs rounded-md bg-sky-50 text-sky-900 px-3 py-2 flex flex-col gap-0.5">
                    <div>{item.origin === 'flag' ? t('腳本執行時被標記「判斷錯了」的畫面') : t('腳本執行時,模型在這張畫面上拿不準:')}</div>
                    {(item.reasons ?? []).filter(r => asks(item).includes(r.state)).map((r, i) => {
                      const st = states.find(z => z.id === r.state)
                      return <div key={i}>· {r.kind === 'disagree' ? t('「{p1}」模型和參考圖的判斷不一樣', { p1: st?.name ?? r.state }) : t('對「{p1}」沒把握', { p1: st?.name ?? r.state })}</div>
                    })}
                    {asks(item).filter(sid => !(item.reasons ?? []).some(r => r.state === sid)).map(sid =>
                      <div key={sid}>{t('· 目前的模型對「{p1}」還沒把握', { p1: states.find(z => z.id === sid)?.name ?? sid })}</div>)}
                    {!!item.urgent_states?.length && <div className="text-rose-700 font-medium">
                      {t('⚠ 緊急規則用到「{p1}」:這種畫面判斷錯的代價最高,排在最前面', { p1: item.urgent_states.map(sid => states.find(z => z.id === sid)?.name ?? sid).join(t('、')) })}</div>}
                    <div className="text-sky-700">{item.use === 'train' ? t('這張回答後會拿去學習') : t('這張回答後會成為考題')}</div>
                  </div>
                )}
                {dec?.reviewer === 'claude' && (blind ? (
                  <div className="text-xs rounded-md bg-violet-50 text-violet-800 px-3 py-2">
                    {dec.unsure ? <>{t('Claude 不確定這張,請您判斷。')}{dec.note && <div className="text-violet-600 mt-0.5">{t('Claude 的說明:{note}', { note: dec.note })}</div>}</>
                      : <>{t('抽查:這張 Claude 有把握,隨機抽出來請您確認(答案先不顯示,避免影響您)。')}</>}
                  </div>
                ) : (
                  <div className="text-xs rounded-md bg-stone-50 text-stone-600 px-3 py-2">
                    {t('這張是 Claude 預標的答案{p1},有錯可以直接改。', { p1: dec.note && `(${dec.note})` })}
                  </div>
                ))}
                {quick && required.length > 0 && shown.length > required.length && (
                  <div className="text-xs text-stone-500 border-b border-stone-100 pb-2">
                    {t('虛線框 =')} {item.auto_from === 'label' ? t('自動標註') : t('執行時模型判斷')}{t('的答案,看一眼對就不用點,錯了點正確的。 回答下面')}<b className="text-amber-700">{t('要回答')}</b>{t('的題目後自動存檔。')}</div>
                )}
                {shown.map(q => (
                  <div key={q.id} className={quick && required.includes(q.id) ? 'rounded-md bg-amber-50 border border-amber-300 px-3 py-2' : ''}>
                    <div className="text-sm text-stone-700 mb-2 flex items-center gap-2">{t('{name} 是?', { name: q.name })}
                      {quick && required.includes(q.id) && <span className="text-xs px-1.5 rounded bg-amber-500 text-white">{t('要回答')}</span>}
                      {quick && !required.includes(q.id) && answers[q.id] == null && prefill[q.id] !== undefined &&
                        <span className="text-xs text-sky-700">{t('自動{p1}', { p1: item.auto_from === 'model' && item.conf?.[q.id] != null ? ` ${pct(item.conf[q.id])}` : '' })}</span>}
                    </div>
                    <div className="flex gap-2 flex-wrap">
                      {q.classes!.map(c => (
                        <Button key={String(c.value)} variant={answers[q.id] === c.value ? 'primary' : answers[q.id] == null && prefill[q.id] === c.value ? 'auto' : 'default'}
                          onClick={() => pick(q.id, c.value)} disabled={!ready}>
                          {c.name}{c.key && <kbd className="ml-1 text-[10px] opacity-60">{c.key.toUpperCase()}</kbd>}
                        </Button>
                      ))}
                      {!q.classes!.some(c => c.value === 'hidden') && (
                        <Button variant={answers[q.id] === SKIP ? 'primary' : 'ghost'} onClick={() => pick(q.id, SKIP)} disabled={!ready} title={t('這張畫面無法回答這一題(例如被面板蓋住),這題不記錄答案')}>{t('此題無法判斷')}</Button>
                      )}
                    </div>
                  </div>
                ))}
                <div className="flex gap-2 border-t border-stone-100 pt-3">
                  <Button onClick={() => go(-1)} disabled={idx === 0}>{t('← 上一張')}</Button>
                  <Button onClick={() => go(1)} disabled={idx === items.length - 1}>{t('跳過 →')}</Button>
                </div>
                {quick && (
                  <Button variant={required.length ? 'default' : 'primary'} onClick={() => commit(answers)} disabled={!ready || !required.every(id => answers[id] != null)}
                    title={t('虛線框的自動答案不會存成您的答案;只有您點過的才算')}>
                    {required.length ? t('存檔並下一張') : t('確認並下一張')}<kbd className="ml-1 text-[10px] opacity-60">Enter</kbd></Button>
                )}
                <p className="text-xs text-stone-500">{quick ? t('只有您點過的答案會存下;沒點的維持自動標註(學習時照用,當考題時不計分)。被面板蓋住時選「看不到」。')
                  : t('所有題目都回答後會自動儲存並跳到下一張。被彈出視窗、選單等蓋住時選「看不到」。')}</p>
                <label className="text-xs text-stone-600 flex items-center gap-1.5">
                  <input type="checkbox" checked={showRule} onChange={e => setShowRule(e.target.checked)} />{t('顯示自動標籤')}
                </label>
                {showRule && (
                  <div className="flex gap-1.5 flex-wrap items-center text-xs">
                    {questions.map(q => {
                      const v = item.rule[q.id]
                      const c = q.classes!.find(x => x.value === v)
                      return <span key={q.id} className={`px-2 py-0.5 rounded-full ${c ? COLORS[c.color]?.pill : 'bg-stone-100 text-stone-600'}`}>{q.name} {valueName(q, v)}</span>
                    })}
                    {item.rule.flags.map(f => <span key={f} className="text-stone-500">{f}</span>)}
                  </div>
                )}
              </div>
            </Card>

            <Card title={t('自動標籤的準確率(和您的答案比對)')}>
              {s && s.reviewed ? (
                <div className="flex flex-col gap-3 text-sm">
                  {Object.entries(s.states).map(([sid, st]) => (
                    <div key={sid}>
                      <div className="flex justify-between"><span>{st.name}</span><span className="num font-semibold">{pct(st.accuracy)}</span></div>
                      <div className="text-xs text-stone-500 num">
                        {t('對 {p1} · 錯 {p2} · 自動標籤沒判斷 {p3}(其中其實看得到 {p4})', { p1: st.eval.correct ?? 0, p2: st.eval.wrong ?? 0, p3: (st.eval.abstained_ok ?? 0) + (st.eval.abstained_missed ?? 0), p4: st.eval.abstained_missed ?? 0 })}
                      </div>
                    </div>
                  ))}
                  {(() => {
                    const c = s.claude_check ?? {}
                    const agree = (c.unsure_agree ?? 0) + (c.spot_agree ?? 0), differ = (c.unsure_differ ?? 0) + (c.spot_differ ?? 0)
                    if (!agree && !differ) return null
                    return (
                      <div className="border-t border-stone-100 pt-2 text-xs text-stone-600">
                        <div className="flex justify-between text-sm text-stone-800"><span>{t('Claude 預標和您一致')}</span><span className="num font-semibold">{pct(agree / (agree + differ))}</span></div>
                        <div className="num">{t('抽查 {p1}/{p2} · 不確定的 {p3}/{p4}', { p1: c.spot_agree ?? 0, p2: (c.spot_agree ?? 0) + (c.spot_differ ?? 0), p3: c.unsure_agree ?? 0, p4: (c.unsure_agree ?? 0) + (c.unsure_differ ?? 0) })}</div>
                        {c.differences.map((x, i) => {
                          const st = states.find(z => z.id === x.field)
                          return <div key={i} className="text-stone-500">{t('{p1}:您 {p2} / Claude {p3}', { p1: st?.name ?? x.field, p2: valueName(st, x.human), p3: valueName(st, x.claude) })}{x.kind === 'spot' ? t('(抽查)') : ''}</div>
                        })}
                      </div>
                    )
                  })()}
                  {s.disagreements.length > 0 && (
                    <div className="border-t border-stone-100 pt-2">
                      <div className="text-xs text-stone-500 mb-1">{t('不一致的畫面(點擊跳過去看)')}</div>
                      <div className="flex flex-col gap-0.5 max-h-40 overflow-auto">
                        {s.disagreements.slice().reverse().map((x, i) => {
                          const j = items.findIndex(it => it.frame === x.frame)   // only frames in the current list (全部 shows all)
                          const st = states.find(z => z.id === x.field)
                          const link = browseLink(x.frame)
                          // frames confirmed from the Data browser are not in this queue: open them there instead
                          const openIt = () => { if (j >= 0) setIdx(j); else if (link) navigate(link) }
                          return (
                            <button key={i} onClick={openIt} title={j >= 0 ? t('在這裡查看') : t('到資料瀏覽查看')} className="text-left text-xs hover:bg-stone-50 rounded px-1">
                              {t('{p1}:您 {p2} / 自動 {p3}', { p1: st?.name ?? x.field, p2: valueName(st, x.human), p3: valueName(st, x.rule) })}
                              <span className="text-stone-400"> · {x.frame.split('/').pop()}</span>
                            </button>
                          )
                        })}
                      </div>
                    </div>
                  )}
                </div>
              ) : <Empty>{t('確認幾張之後,這裡會顯示自動標籤的準確率')}</Empty>}
            </Card>
          </div>
        </div>
      ) : focus && pickSession ? (
        // a remembered recording filter can hide every question: say so, and how many there are without it
        <Card><Empty>
          {t('目前只看「場次 {pickSession}{p2}」的畫面,這裡沒有「{name}」待答的題目。', { pickSession, p2: pickDevice ? ` · ${pickDevice}` : '', name: focus.name })}
          <div className="mt-3"><Button onClick={() => { setPickSession(''); setPickDevice('') }}>{t('改看所有場次')}</Button></div>
        </Empty></Card>
      ) : <Card><Empty>{queue.isLoading ? t('讀取中…') : focus ? t('「{name}」這一題都回答完了。需要更多考題,按上面的「補 30 題」。', { name: focus.name })
        : runtimeMode ? t('腳本執行時存下的畫面都回答完了。腳本執行時,模型拿不準的畫面會自動存到這裡。')
        : onlyCheck ? t('需要您確認的畫面都處理完了,可以切到「全部」再看看。') : t('沒有待確認的畫面。請先到「自動標註」產生標籤。')}</Empty></Card>}
    </>
  )
}
