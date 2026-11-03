import { t } from '../i18n'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { api, type AskItem } from '../api'
import { dn } from '../lib/sources'

/** Questions running scripts wait on (問使用者): one button per option; the first answer anywhere (a chat, this
 *  page, the operation panel) wins. big = the operation panel's large style. */
export function AskBar({ items, big = false, refresh }: { items: AskItem[]; big?: boolean; refresh: string[] }) {
  const qc = useQueryClient()
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null)
  const [now, setNow] = useState(() => Date.now() / 1000)
  useEffect(() => { const tx = setInterval(() => setNow(Date.now() / 1000), 1000); return () => clearInterval(tx) }, [])
  const ans = useMutation({
    mutationFn: (a: { id: string; option: number }) => api.answer(a.id, a.option),
    onSuccess: r => { setMsg({ ok: true, text: r.message }); qc.invalidateQueries({ queryKey: refresh }) },
    onError: (e: Error) => { setMsg({ ok: false, text: e.message }); qc.invalidateQueries({ queryKey: refresh }) },
  })
  if (!items.length && !msg) return null
  const left = (q: AskItem) => { const s = Math.max(0, Math.round(q.expires - now)); return s >= 60 ? t('{p1} 分 {p2} 秒', { p1: Math.floor(s / 60), p2: s % 60 }) : t('{s} 秒', { s }) }
  return (
    <div className="flex flex-col gap-2">
      {items.map(q => (
        <div key={q.id} className={`rounded-lg border border-rose-200 bg-rose-50 ${big ? 'px-4 py-3 text-sm' : 'px-3 py-2 text-sm'}`}>
          <div className={`${big ? 'font-medium' : ''} text-rose-900`}>
            <span className="font-semibold">❓ {dn(q.device)}{q.script_name ? ` · ${q.script_name}` : ''}</span>:{q.text}
          </div>
          <div className="flex flex-wrap items-center gap-2 mt-2">
            {q.options.map((o, k) => (
              <button key={k} disabled={ans.isPending} onClick={() => { setMsg(null); ans.mutate({ id: q.id, option: k + 1 }) }}
                className={`rounded-md bg-white border border-rose-300 text-rose-900 font-semibold hover:bg-rose-100 ${big ? 'h-9 px-4 text-sm' : 'px-3 py-1'}`}>{o}</button>
            ))}
            <span className={`text-rose-700 ${big ? 'text-[0.8125rem]' : 'text-xs'}`}>
              {t('還有 {p1}', { p1: left(q) })}{q.default ? t(',沒人回答就選「{p1}」', { p1: q.options[q.default - 1] }) : t(',沒人回答腳本就停在失敗')}</span>
          </div>
        </div>
      ))}
      {msg && <div className={`${big ? 'px-1 text-sm' : 'text-xs'} ${msg.ok ? 'text-emerald-800' : 'text-rose-800'}`}>{msg.ok ? '✔ ' : '✖ '}{msg.text}</div>}
    </div>
  )
}
