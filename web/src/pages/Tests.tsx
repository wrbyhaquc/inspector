import { t } from '../i18n'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api, type TestCase, type TestExpect, type TestsInfo } from '../api'
import { Button, Card, Empty, ErrorText, LogView, Page, Pill } from '../components/ui'
import { dateTime, sessionTime } from '../lib/format'
import { words } from '../lib/project'
import { ReplayView } from './Scripts'

const input = 'border border-stone-300 rounded-md px-2 py-1 text-sm bg-white'
const STATUS: Record<string, { text: string; tone: 'green' | 'red' | 'amber' }> = {
  pass: { text: t('通過'), tone: 'green' }, fail: { text: t('沒通過'), tone: 'red' }, error: { text: t('無法執行'), tone: 'amber' },
}
const strip = (tx: TestsInfo['tests'][number]): TestCase => {
  const { expect_text: _e, last: _l, ...rest } = tx
  return rest
}

/** Script tests: replay a recording with the saved scripts and check that they do what is expected. */
export default function Tests() {
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['tests'], queryFn: api.tests, refetchInterval: x => (x.state.data?.job?.status === 'running' ? 2000 : false) })
  const set = (d: TestsInfo) => qc.setQueryData(['tests'], d)
  const run = useMutation({ mutationFn: (ids: string[]) => api.testsRun(ids), onSuccess: () => qc.invalidateQueries({ queryKey: ['tests'] }) })
  const save = useMutation({ mutationFn: (tests: TestCase[]) => api.testsSave(tests), onSuccess: set })
  const [edit, setEdit] = useState<string | null>(null)
  const [view, setView] = useState<string | null>(null)
  const d = q.data
  const running = d?.job?.status === 'running'
  const tests = d?.tests ?? []
  const passed = tests.filter(tx => tx.last?.status === 'pass').length
  const replace = (tx: TestCase | null, id: string) =>
    save.mutate(tests.map(strip).flatMap(x => x.id === id ? (tx ? [tx] : []) : [x]))

  return (
    <Page title={t('腳本測試')} desc={t('用錄過的畫面重播,檢查腳本有沒有做該做的事(像單元測試)。改了腳本、狀態或模型之後按「全部執行」,就知道有沒有改壞。重播不會點任何{device};子腳本不實際執行,結果用假設的。', { device: words.device })}
      actions={<Button variant="primary" disabled={running || !tests.length} onClick={() => run.mutate([])}>{running ? t('測試中…') : t('全部執行')}</Button>}>
      <ErrorText error={q.error || run.error || save.error} />
      {tests.length > 0 && <div className="flex flex-wrap gap-2 text-sm">
        <Pill tone={passed === tests.length ? 'green' : 'red'}>{t('{passed} / {length} 通過', { passed, length: tests.length })}</Pill>
        {tests.some(tx => !tx.last) && <Pill>{t('{length} 個還沒執行過', { length: tests.filter(tx => !tx.last).length })}</Pill>}
      </div>}
      {(running || d?.job) && <Card title={running ? t('測試中') : t('上次執行的紀錄')}><LogView lines={d?.job?.log ?? []} height="h-40" /></Card>}
      {!tests.length ? (
        <Card><Empty>
          {t('還沒有測試。到')} <Link className="underline" to="/scripts">{t('腳本')}</Link> {t('打開一個主腳本 →「試跑」分頁 →「用錄過的畫面重播」, 看過結果覺得行為正確,按「存成測試」;這次重播的行為就會變成預期結果,之後可以再修改。')}
        </Empty></Card>
      ) : tests.map(tx => {
        const st = tx.last ? STATUS[tx.last.status] : null
        return (
          <Card key={tx.id} title={<span className="flex items-center gap-2">{tx.name}{st && <Pill tone={st.tone}>{st.text}</Pill>}</span>}
            extra={<div className="flex gap-2">
              <Button disabled={running} onClick={() => run.mutate([tx.id])}>{t('執行')}</Button>
              <Button variant="ghost" onClick={() => setEdit(edit === tx.id ? null : tx.id)}>{edit === tx.id ? t('收起') : t('編輯')}</Button>
              {tx.last?.replay && <Button variant="ghost" onClick={() => setView(view === tx.id ? null : tx.id)}>{view === tx.id ? t('收起重播') : t('看重播')}</Button>}
            </div>}>
            <div className="flex flex-col gap-2 text-sm">
              <div className="text-xs text-stone-500">
                {t('錄影 {p1} · {device} · 從第 {p3} 分鐘起 {minutes} 分鐘 · 子腳本假設', { p1: sessionTime(tx.session), device: tx.device, p3: Math.round(tx.start / 60), minutes: tx.minutes })}{tx.sub_result === 'fail' ? t('失敗') : t('成功')}
                {tx.last && <> {t('· 上次 {p1}', { p1: dateTime(tx.last.run_at) })}{tx.last.frames ? t('({frames} 張,{seconds} 秒)', { frames: tx.last.frames, seconds: tx.last.seconds }) : ''}{tx.last.model ? t(' · 模型 {model}', { model: tx.last.model }) : ''}</>}
              </div>
              {tx.last?.status === 'error' && <ErrorText error={tx.last.error} />}
              <ul className="flex flex-col gap-1">
                {tx.expect_text.map((text, i) => {
                  const c = tx.last?.checks?.[i]
                  return <li key={i} className="flex gap-2">
                    <span className={c ? (c.ok ? 'text-emerald-600' : 'text-rose-600') : 'text-stone-300'}>{c ? (c.ok ? '✓' : '✗') : '•'}</span>
                    <span>{text}{c && !c.ok && <span className="text-rose-700">:{c.detail}</span>}</span></li>
                })}
                {!tx.expect.length && <li className="text-stone-500">{t('沒有任何預期結果(一定通過)')}</li>}
              </ul>
              {edit === tx.id && d && <TestEditor tx={strip(tx)} info={d} busy={save.isPending}
                onSave={x => { replace(x, tx.id); setEdit(null) }} onDelete={() => { if (confirm(t('刪除測試「{name}」?', { name: tx.name }))) replace(null, tx.id) }} />}
              {view === tx.id && tx.last?.replay && <TestReplay id={tx.last.replay} />}
            </div>
          </Card>
        )
      })}
    </Page>
  )
}

function TestReplay({ id }: { id: string }) {
  const r = useQuery({ queryKey: ['replay', id], queryFn: () => api.replayResult(id) })
  return r.data?.result ? <ReplayView r={r.data.result} /> : <ErrorText error={r.error} />
}

function TestEditor({ tx, info, busy, onSave, onDelete }: { tx: TestCase; info: TestsInfo; busy: boolean; onSave: (tx: TestCase) => void; onDelete: () => void }) {
  const [x, setX] = useState<TestCase>(tx)
  const setE = (i: number, e: TestExpect | null) => setX({ ...x, expect: x.expect.flatMap((y, k) => k === i ? (e ? [e] : []) : [y]) })
  return (
    <div className="border-t border-stone-100 pt-3 flex flex-col gap-3">
      <div className="flex flex-wrap gap-3 items-center">
        <label className="flex items-center gap-1">{t('名稱')}<input className={`${input} w-64`} value={x.name} onChange={e => setX({ ...x, name: e.target.value })} /></label>
        <label className="flex items-center gap-1">{t('從第')}<input type="number" min={0} className={`${input} w-20 num`} value={Math.round(x.start / 60)}
          onChange={e => setX({ ...x, start: Number(e.target.value) * 60 })} />{t('分鐘起')}</label>
        <label className="flex items-center gap-1">{t('共')}<input type="number" min={1} max={240} className={`${input} w-20 num`} value={x.minutes}
          onChange={e => setX({ ...x, minutes: Number(e.target.value) })} />{t('分鐘')}</label>
        <label className="flex items-center gap-1">{t('子腳本假設')}
          <select className={input} value={x.sub_result} onChange={e => setX({ ...x, sub_result: e.target.value as TestCase['sub_result'] })}>
            <option value="success">{t('都成功')}</option><option value="fail">{t('都失敗')}</option></select></label>
      </div>
      <div className="flex flex-col gap-2">
        <div className="text-xs text-stone-500">{t('預期結果(全部成立才算通過)')}</div>
        {x.expect.map((e, i) => <ExpectRow key={i} e={e} info={info} onChange={v => setE(i, v)} />)}
        <div><Button variant="ghost" onClick={() => setX({ ...x, expect: [...x.expect, { kind: 'call', when: 'ever', sub: info.subs[0]?.id }] })}>{t('+ 新增預期結果')}</Button></div>
      </div>
      <div className="flex gap-2">
        <Button variant="primary" disabled={busy} onClick={() => onSave(x)}>{t('儲存')}</Button>
        <Button variant="danger" onClick={onDelete}>{t('刪除測試')}</Button>
      </div>
    </div>
  )
}

function ExpectRow({ e, info, onChange }: { e: TestExpect; info: TestsInfo; onChange: (e: TestExpect | null) => void }) {
  const sc = info.scripts.find(s => s.id === e.script)
  const set = (p: Partial<TestExpect>) => onChange({ ...e, ...p })
  const scriptSel = (allowAny: boolean) => (
    <select className={input} value={e.script ?? ''} onChange={v => set({ script: v.target.value || undefined, situation: undefined, rule: undefined })}>
      {allowAny && <option value="">{t('任何腳本')}</option>}
      {info.scripts.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
    </select>)
  const counts = e.when === 'ever' && e.kind !== 'situation' && (
    <span className="flex items-center gap-1 text-xs">{t('次數')}<input type="number" min={0} placeholder={t('至少')} className={`${input} w-16 num`} value={e.min ?? ''}
      onChange={v => set({ min: v.target.value === '' ? null : Number(v.target.value) })} />~<input type="number" min={0} placeholder={t('最多')}
      className={`${input} w-16 num`} value={e.max ?? ''} onChange={v => set({ max: v.target.value === '' ? null : Number(v.target.value) })} /></span>)
  return (
    <div className="flex flex-wrap items-center gap-2 bg-stone-50 rounded px-2 py-1.5">
      <select className={input} value={e.kind} onChange={v => {
        const kind = v.target.value as TestExpect['kind']
        onChange(kind === 'situation' ? { kind, when: 'end', script: info.scripts.find(s => s.situations.length > 1)?.id ?? info.scripts[0]?.id }
          : kind === 'call' ? { kind, when: 'ever', sub: info.subs[0]?.id } : { kind, when: kind === 'input' || kind === 'output' ? 'ever' : 'never' })
      }}>{Object.entries(info.kinds).map(([k, n]) => <option key={k} value={k}>{n}</option>)}</select>
      {e.kind === 'situation' && <>{scriptSel(false)}
        <select className={input} value={e.when} onChange={v => set({ when: v.target.value as TestExpect['when'] })}>
          <option value="end">{t('結束時在')}</option><option value="ever">{t('會進入')}</option><option value="never">{t('不會進入')}</option></select>
        <select className={input} value={e.situation ?? ''} onChange={v => set({ situation: v.target.value })}>
          <option value="">{t('(選情境)')}</option>{(sc?.situations ?? []).map(s => <option key={s.id} value={s.id}>{s.name}</option>)}</select></>}
      {e.kind !== 'situation' && <select className={input} value={e.when} onChange={v => set({ when: v.target.value as TestExpect['when'] })}>
        <option value="ever">{t('會')}</option><option value="never">{t('不會')}</option></select>}
      {e.kind === 'call' && <>{scriptSel(true)}<span>{t('呼叫')}</span>
        <select className={input} value={e.sub ?? ''} onChange={v => set({ sub: v.target.value })}>
          {info.subs.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}</select></>}
      {e.kind === 'input' && <>{scriptSel(true)}<span>{t('點擊')}</span>
        {sc && <select className={input} value={e.rule ?? ''} onChange={v => set({ rule: v.target.value || undefined })}>
          <option value="">{t('任何規則')}</option>{sc.rules.map(r => <option key={r.id} value={r.id}>{r.name}</option>)}</select>}</>}
      {e.kind === 'stop' && <>{scriptSel(true)}<span>{t('停止')}</span></>}
      {e.kind === 'output' && <><span>{t('送到輸出')}</span>
        <input className={`${input} w-28 font-mono`} placeholder={t('(任何輸出)')} value={e.output ?? ''} onChange={v => set({ output: v.target.value || undefined })} /></>}
      {e.kind === 'alert' && <><span>{t('出現警示,內容含')}</span>
        <input className={`${input} w-40`} placeholder={t('(任何警示)')} value={e.text ?? ''} onChange={v => set({ text: v.target.value || undefined })} /></>}
      {counts}
      <span className="flex items-center gap-1 text-xs">{t('只看第')}<input type="number" min={0} className={`${input} w-16 num`} value={e.within?.[0] ?? ''}
        onChange={v => set({ within: v.target.value === '' ? null : [Number(v.target.value), e.within?.[1] ?? 99999] })} />~
        <input type="number" min={0} className={`${input} w-16 num`} value={e.within?.[1] ?? ''}
          onChange={v => set({ within: v.target.value === '' ? null : [e.within?.[0] ?? 0, Number(v.target.value)] })} />{t('秒')}</span>
      <button className="ml-auto text-xs text-stone-500 underline" onClick={() => onChange(null)}>{t('移除')}</button>
    </div>
  )
}
