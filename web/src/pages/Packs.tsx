import { t } from '../i18n'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api, type PackDone, type PackExported } from '../api'
import { Button, Card, Empty, ErrorText, Page, Pill } from '../components/ui'
import { edition } from '../lib/project'

/** 方案包: what is installed here, which one runs; install a release or upgrade to a newer one, switch, restart. */
export default function Packs() {
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['packs'], queryFn: api.packs })
  const [file, setFile] = useState<File | null>(null)
  const [force, setForce] = useState(false)
  const [done, setDone] = useState<PackDone | null>(null)
  const [asking, setAsking] = useState(false)
  const [restarting, setRestarting] = useState(false)
  const after = (d: PackDone) => { setDone(d); setFile(null); qc.invalidateQueries({ queryKey: ['packs'] }) }
  const install = useMutation({ mutationFn: () => api.packInstall(file!, { force }), onSuccess: after })
  const use = useMutation({ mutationFn: (id: string) => api.packUse(id), onSuccess: after })
  const restart = useMutation({
    mutationFn: api.restart,
    onSuccess: () => {
      setRestarting(true)
      const wait = async () => {            // back when the server answers again
        for (let i = 0; i < 90; i++) {
          await new Promise(r => setTimeout(r, 2000))
          try { if ((await fetch('/api/language')).ok && i > 2) { window.location.reload(); return } } catch { /* still down */ }
        }
        setRestarting(false)
      }
      void wait()
    },
  })
  const d = q.data

  return (
    <Page title={t('方案包')} desc={edition.name === 'runtime'
      ? t('這台是執行版:安裝別人做好的方案包、升級成新版本,或切換要執行哪一個。設計只能在 Studio 修改。')
      : t('這台電腦裝了哪些方案包、正在執行哪一個。執行中的方案包可以在下面「匯出發行版」做成發行版給別人安裝(也可以用 python -m project.pack export)。')}>
      <ErrorText error={q.error} />
      {d && !d.layout && (
        <Card><p className="text-sm text-stone-600">{t('這台電腦還在用單一專案資料夾,要先改用資料目錄結構才能安裝方案包(README 的「資料目錄結構」;python -m project.layout migrate)。')}</p></Card>
      )}

      {d?.layout && (
        <Card title={t('已安裝')} extra={<span className="text-xs text-stone-500">Inspector {d.platform} · {d.edition === 'runtime' ? t('執行版') : 'Studio'}</span>}>
          {d.packs.length === 0 ? <Empty>{t('還沒有安裝任何方案包')}</Empty> : (
            <div className="flex flex-col divide-y divide-stone-100">
              {d.packs.map(p => (
                <div key={p.id} className="py-3 flex items-start gap-3">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="font-medium text-stone-900">{p.name}</span>
                      <span className="text-xs text-stone-500 num">{p.id} · {p.version}</span>
                      {p.active && <Pill tone="green">{t('執行中')}</Pill>}
                      {p.workspace && <Pill tone="blue">{t('開發中')}</Pill>}
                    </div>
                    {p.problems.map((x, i) => (
                      <div key={i} className={`text-xs mt-1 ${x.level === 'error' ? 'text-rose-700' : 'text-amber-700'}`}>{x.level === 'error' ? '✗ ' : '! '}{x.text}</div>
                    ))}
                  </div>
                  {!p.active && <Button onClick={() => use.mutate(p.id)} disabled={use.isPending || p.problems.some(x => x.level === 'error')}>{t('改用這個')}</Button>}
                </div>
              ))}
            </div>
          )}
          <ErrorText error={use.error} />
        </Card>
      )}

      {d?.layout && (
        <Card title={t('安裝或升級')}>
          <div className="flex flex-col gap-3">
            <p className="text-sm text-stone-600">{t('選一個方案包發行版(.zip)。已經裝過的會升級成新版本,舊版會保留一份;使用者改過的值、錄影與執行資料都不會動。')}</p>
            <input type="file" accept=".zip" onChange={e => { setFile(e.target.files?.[0] ?? null); setDone(null) }}
              className="text-sm file:mr-3 file:px-3 file:py-1.5 file:rounded-md file:border file:border-stone-300 file:bg-white file:text-stone-700" />
            <label className="text-sm text-stone-600 flex items-center gap-2">
              <input type="checkbox" checked={force} onChange={e => setForce(e.target.checked)} />
              {t('同版或較舊的版本也裝(換回舊版時用)')}
            </label>
            <div><Button variant="primary" disabled={!file || install.isPending} onClick={() => install.mutate()}>
              {install.isPending ? t('安裝中…') : t('安裝')}</Button></div>
            <ErrorText error={install.error} />
          </div>
        </Card>
      )}

      {d?.layout && edition.name === 'studio' && d.active && <ExportCard />}

      {done && (
        <Card title={t('完成')}>
          <div className="flex flex-col gap-2 text-sm text-stone-700">
            {done.messages.map((m, i) => <div key={i}>{m}</div>)}
          </div>
        </Card>
      )}

      {d?.layout && (
        <Card title={t('重新啟動')}>
          <div className="flex flex-col gap-3">
            <p className="text-sm text-stone-600">{t('換了執行中的方案包或升級它之後,重新啟動 Inspector 才會生效。重新啟動時腳本會停下約半分鐘,總開關會回到關閉。')}</p>
            {restarting ? <div className="text-sm text-amber-700">{t('重新啟動中,完成後這一頁會自己重新整理…')}</div>
              : asking ? (
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="text-sm text-stone-700">{t('確定現在重新啟動?')}</span>
                  <Button variant="danger" disabled={restart.isPending} onClick={() => restart.mutate()}>{t('重新啟動')}</Button>
                  <Button variant="ghost" onClick={() => setAsking(false)}>{t('取消')}</Button>
                </div>
              ) : <div><Button variant={done?.restart ? 'primary' : 'default'} onClick={() => setAsking(true)}>{t('重新啟動 Inspector')}</Button></div>}
            <ErrorText error={restart.error} />
          </div>
        </Card>
      )}
    </Page>
  )
}

const LEVEL: Record<string, [string, string]> = { error: ['✗', 'text-rose-700'], warn: ['!', 'text-amber-700'], ok: ['✓', 'text-emerald-700'], info: ['·', 'text-stone-600'] }

/** Export the running pack as a release: name, version and what it is; checked first, compared with the last one. */
function ExportCard() {
  const [model, setModel] = useState(false)
  const chk = useQuery({ queryKey: ['packExport', model], queryFn: () => api.packExportCheck(model) })
  const [form, setForm] = useState<{ version: string; name: string; description: string } | null>(null)
  const [made, setMade] = useState<PackExported | null>(null)
  const [showFiles, setShowFiles] = useState(false)
  const c = chk.data
  const f = form ?? (c ? { version: c.next, name: c.pack.name ?? '', description: c.pack.description ?? '' } : null)
  const go = useMutation({ mutationFn: () => api.packExport({ ...f!, model }), onSuccess: r => { setMade(r); setForm(null); void chk.refetch() } })
  const blocked = !!c?.checks.some(x => x.level === 'error')
  const ch = c?.changes
  const input = 'border border-stone-300 rounded-md px-2 py-1 text-sm'
  return (
    <Card title={t('匯出發行版')}>
      <div className="flex flex-col gap-3">
        <p className="text-sm text-stone-600">{t('把執行中的方案包做成一個發行版(.zip),給別台電腦安裝或升級。匯出前會先檢查,並和上一版比較。')}</p>
        <ErrorText error={chk.error} />
        {c && f && <>
          <div className="grid md:grid-cols-[auto_1fr] gap-x-3 gap-y-2 items-center text-sm">
            <span className="text-stone-600">{t('名稱')}</span>
            <input className={input} value={f.name} onChange={e => setForm({ ...f, name: e.target.value })} />
            <span className="text-stone-600">{t('版本')}</span>
            <span className="flex items-center gap-2 flex-wrap">
              <input className={`${input} w-28 num`} value={f.version} onChange={e => setForm({ ...f, version: e.target.value })} />
              <span className="text-xs text-stone-500">{c.last ? t('上一版 {v}', { v: c.last.version }) : t('第一次匯出')}</span>
            </span>
            <span className="text-stone-600 self-start pt-1">{t('說明')}</span>
            <textarea className={`${input} min-h-16`} value={f.description} onChange={e => setForm({ ...f, description: e.target.value })} />
          </div>
          <label className="text-sm text-stone-600 flex items-center gap-2">
            <input type="checkbox" checked={model} onChange={e => setModel(e.target.checked)} />
            {t('放進最新學好的模型(只放 ONNX;沒有模型的方案包就只用畫面規則)')}
          </label>
          <div className="flex flex-col gap-1 text-sm">
            {chk.isFetching ? <span className="text-stone-500">{t('檢查中…')}</span>
              : c.checks.map((x, i) => <div key={i} className={LEVEL[x.level][1]}>{LEVEL[x.level][0]} {x.text}</div>)}
          </div>
          {ch && <div className="text-sm text-stone-600">
            {t('和上一版比:新增 {a}、刪除 {r}、修改 {m} 個檔案', { a: ch.added.length, r: ch.removed.length, m: ch.changed.length })}
            {(ch.added.length + ch.removed.length + ch.changed.length) > 0 &&
              <button className="ml-2 text-sky-700" onClick={() => setShowFiles(v => !v)}>{showFiles ? t('收起 ▴') : t('看是哪些 ▾')}</button>}
            {showFiles && <ul className="mt-1 font-mono text-xs text-stone-600">
              {ch.added.map(x => <li key={'a' + x}>+ {x}</li>)}{ch.removed.map(x => <li key={'r' + x}>− {x}</li>)}{ch.changed.map(x => <li key={'c' + x}>~ {x}</li>)}
            </ul>}
          </div>}
          <div className="flex items-center gap-3 flex-wrap">
            <Button variant="primary" disabled={blocked || go.isPending || chk.isFetching || !f.version.trim()} onClick={() => go.mutate()}>
              {go.isPending ? t('匯出中…') : t('匯出 {v}', { v: f.version })}</Button>
            {blocked && <span className="text-xs text-rose-700">{t('先處理上面打 ✗ 的項目')}</span>}
          </div>
          <ErrorText error={go.error} />
          {made && <div className="text-sm text-emerald-800 flex flex-col gap-1">
            {made.messages.map((m, i) => <div key={i}>{m}</div>)}
            <a className="text-sky-700 underline" href={`/api/packs/releases/${encodeURIComponent(made.file)}`} download>
              {t('下載 {file}({kb} KB)', { file: made.file, kb: Math.round(made.size / 1024) })}</a>
          </div>}
        </>}
      </div>
    </Card>
  )
}
