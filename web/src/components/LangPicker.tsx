import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../api'
import { LANG_NAMES, lang, languages, setLang, t } from '../i18n'
import { ErrorText } from './ui'

/** The interface's language, for this browser (the page reloads). Hidden while there is only one. */
export function LangPicker({ className = '' }: { className?: string }) {
  if (languages.length < 2) return null
  return (
    <select value={lang} onChange={e => setLang(e.target.value)} title={t('介面語言')} aria-label={t('介面語言')}
      className={`rounded border px-1.5 py-1 text-sm ${className}`}>
      {languages.map(l => <option key={l} value={l}>{LANG_NAMES[l] ?? l}</option>)}
    </select>
  )
}

/** This machine's language: what the runtime writes in its log, its notices and the chat bot's replies. */
export function MachineLanguage() {
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['language'], queryFn: api.language })
  const set = useMutation({ mutationFn: api.languageSet, onSuccess: d => qc.setQueryData(['language'], d) })
  if (!q.data || q.data.available.length < 2) return null
  return (
    <div className="flex flex-col gap-1 border-t border-stone-100 pt-2">
      <label className="text-sm flex items-center gap-2">{t('執行紀錄與通知的語言')}
        <select className="border border-stone-300 rounded px-1.5 py-0.5" value={q.data.machine} disabled={set.isPending}
          onChange={e => set.mutate(e.target.value)}>
          {q.data.available.map(l => <option key={l} value={l}>{q.data.names[l] ?? l}</option>)}
        </select>
      </label>
      <div className="text-xs text-stone-500">{t('腳本執行的紀錄、通知和聊天 Bot 的回覆用這個語言(這台電腦的設定);畫面上的文字照每個瀏覽器自己選的語言。')}</div>
      <ErrorText error={set.error} />
    </div>
  )
}
