import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { api, galleryImageUrl, type GalleryCluster } from '../api'
import { Zoom } from '../components/FrameView'
import { t } from '../i18n'
import { Button, Card, Empty, ErrorText, JobStatus, Pill } from '../components/ui'

/** Name each distinct crop of a name gallery once; the labeler then recognises it on every other frame. */
export default function GalleryNaming({ sid }: { sid: string }) {
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['gallery', sid], queryFn: () => api.gallery(sid) })
  const [jobId, setJobId] = useState<string | null>(null)
  const job = useQuery({
    queryKey: ['job', jobId], queryFn: () => api.job(jobId!), enabled: !!jobId,
    refetchInterval: x => (x.state.data?.status === 'running' ? 1000 : false),
  })
  const finished = job.data && job.data.status !== 'running'
  useEffect(() => { if (finished) { qc.invalidateQueries({ queryKey: ['gallery', sid] }); qc.invalidateQueries({ queryKey: ['labels'] }) } }, [finished, qc, sid])
  const run = useMutation({ mutationFn: () => api.labelsRun(), onSuccess: j => setJobId(j.id) })

  const [done, setDone] = useState<Record<number, string>>({})    // cluster id -> name given in this sitting
  useEffect(() => setDone({}), [sid])
  const r = q.data
  const pending = (r?.clusters ?? []).filter(c => !(c.id in done))
  const named = Object.keys(done).length

  return (
    <div className="flex flex-col gap-4">
      <ErrorText error={q.error || run.error} />
      <Card title={t('待命名的「{p1}」', { p1: r?.name ?? '' })} extra={
        <div className="flex items-center gap-3">
          {job.data && <JobStatus status={job.data.status} />}
          <Button variant={named ? 'primary' : 'default'} onClick={() => run.mutate()} disabled={job.data?.status === 'running'}>
            {job.data?.status === 'running' ? t('套用中…') : named ? t('重新產生標籤(套用 {named} 個新名稱)', { named }) : t('重新產生標籤')}
          </Button>
        </div>}>
        <p className="text-sm text-stone-600 mb-4 max-w-3xl">
          {t('看起來一樣的名稱已經自動分成一群,每群只要命名一次。同一個名稱可能因為背景不同分成好幾群,輸入相同名稱即可(會自動提示已有的名稱)。 切到的不是名稱(例如被選單、圖示蓋住)時,按「不是名稱」。命名完按右上角「重新產生標籤」,其他畫面就會自動套用,還沒認出的才會再出現在這裡。')}
        </p>
        {pending.length ? (
          <div className="flex flex-col divide-y divide-stone-100">
            {pending.map(c => <ClusterRow key={c.id} sid={sid} c={c} names={r!.names} row={r!.row} notName={r!.not_a_name}
              onDone={name => setDone(d => ({ ...d, [c.id]: name }))} />)}
          </div>
        ) : <Empty>{q.isLoading ? t('讀取中…') : named ? t('這一批都命名完了,按右上角「重新產生標籤」套用') : t('沒有待命名的項目')}</Empty>}
      </Card>
      <GalleryCard sid={sid} />
    </div>
  )
}

function ClusterRow({ sid, c, names, row, notName, onDone }: { sid: string; c: GalleryCluster; names: string[]; row: [number, number]; notName: string; onDone: (name: string) => void }) {
  const [name, setName] = useState('')
  const save = useMutation({ mutationFn: (n: string) => api.galleryName(sid, { frame: c.rep, ext: c.ext, name: n }), onSuccess: (_, n) => onDone(n) })
  const box = (ext: [number, number]) => [ext[0] - 8, row[0] - 3, ext[1] - ext[0] + 16, row[1] - row[0] + 6]
  const listId = `names-${sid}-${c.id}`
  return (
    <div className="py-3 flex flex-wrap items-center gap-4">
      <div className="flex flex-col gap-1">
        <Zoom frame={c.rep} box={box(c.ext)} scale={2} />
        <span className="text-xs text-stone-500 num">{t('{count} 張 · 寬 {width}px', { count: c.count, width: c.width })}</span>
      </div>
      <div className="flex gap-2 items-center flex-1 min-w-[280px]">
        <input id={`name-${sid}-${c.id}`} list={listId} value={name} onChange={e => setName(e.target.value)} placeholder={t('輸入名稱')}
          onKeyDown={e => { if (e.key === 'Enter' && name.trim()) save.mutate(name.trim()) }}
          className="border border-stone-300 rounded-md px-3 py-1.5 text-sm flex-1 max-w-xs" />
        <datalist id={listId}>{names.map(n => <option key={n} value={n} />)}</datalist>
        <Button variant="primary" onClick={() => save.mutate(name.trim())} disabled={!name.trim() || save.isPending}>{t('命名')}</Button>
        <Button variant="ghost" onClick={() => save.mutate(notName)} disabled={save.isPending}>{t('不是名稱')}</Button>
      </div>
      <ErrorText error={save.error} />
    </div>
  )
}

function GalleryCard({ sid }: { sid: string }) {
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['gallery', sid], queryFn: () => api.gallery(sid) })
  const [edit, setEdit] = useState<Record<string, string>>({})
  const refresh = () => qc.invalidateQueries({ queryKey: ['gallery', sid] })
  const rename = useMutation({ mutationFn: ({ f, n }: { f: string; n: string }) => api.galleryRename(sid, f, n), onSuccess: refresh })
  const del = useMutation({ mutationFn: (f: string) => api.galleryDelete(sid, f), onSuccess: refresh })
  const g = q.data?.gallery ?? []
  return (
    <Card title={t('名稱庫({length})', { length: g.length })} extra={<span className="text-xs text-stone-500">{t('產生標籤時用這份名稱庫辨識')}</span>}>
      <ErrorText error={rename.error || del.error} />
      {g.length ? (
        <div className="flex flex-col divide-y divide-stone-100">
          {g.map(e => {
            const isNot = e.name === q.data!.not_a_name
            const value = edit[e.file] ?? e.name
            return (
              <div key={e.file} className="py-2 flex flex-wrap items-center gap-3 text-sm">
                <img src={galleryImageUrl(sid, e.file)} alt={e.name} className="h-8 border border-stone-300 rounded bg-stone-900" style={{ imageRendering: 'pixelated' }} />
                {isNot ? <Pill>{t('不是名稱')}</Pill> : (
                  <input id={`g-${sid}-${e.file}`} value={value} onChange={ev => setEdit(s => ({ ...s, [e.file]: ev.target.value }))}
                    className="border border-stone-200 rounded px-2 py-1 w-48" />
                )}
                {!isNot && value !== e.name && <Button onClick={() => rename.mutate({ f: e.file, n: value })}>{t('儲存')}</Button>}
                <span className="text-xs text-stone-500 num">{isNot ? '' : t('目前標籤 {p1} 張', { p1: q.data!.counts[e.name] ?? 0 })}</span>
                <span className="ml-auto"><Button variant="ghost" onClick={() => del.mutate(e.file)}>{t('刪除')}</Button></span>
              </div>
            )
          })}
        </div>
      ) : <Empty>{t('還沒有任何名稱')}</Empty>}
    </Card>
  )
}
