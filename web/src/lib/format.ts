import { locale, t } from '../i18n'
export const bytes = (n?: number | null) => {
  if (n == null) return '—'
  const u = ['B', 'KB', 'MB', 'GB', 'TB']
  let i = 0
  let v = n
  while (v >= 1024 && i < u.length - 1) { v /= 1024; i++ }
  return `${v.toFixed(v >= 100 || i === 0 ? 0 : 1)} ${u[i]}`
}

export const clock = (tx?: number | null) =>
  tx ? new Date(tx * 1000).toLocaleTimeString(locale, { hour12: false }) : '—'

export const dateTime = (tx?: number | null) =>
  tx ? new Date(tx * 1000).toLocaleString(locale, { hour12: false, month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }) : '—'

/** a session id (20261018_213045, shadow_20261018 …) as "10/18 21:30" */
export const sessionTime = (id: string) => {
  const m = /(\d{4})(\d{2})(\d{2})(?:_(\d{2})(\d{2}))?/.exec(id)
  return m ? `${m[2]}/${m[3]}${m[4] ? ` ${m[4]}:${m[5]}` : ''}` : id
}

export const duration = (sec?: number | null) => {
  if (sec == null) return '—'
  const s = Math.max(0, Math.round(sec))
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), r = s % 60
  return h ? `${h}:${String(m).padStart(2, '0')}:${String(r).padStart(2, '0')}` : `${m}:${String(r).padStart(2, '0')}`
}

export const pct = (v?: number | null, digits = 1) => (v == null ? '—' : `${(v * 100).toFixed(digits)}%`)

// Human-readable meaning of labeler flags: the platform's own here; the plugins' come with the project (lib/project.ts)
export const FLAG_TEXT: Record<string, string> = {
  bad_size: t('畫面尺寸和專案的座標空間不同'),
}

/** A flag's meaning; generic ones (<state>_uncertain, <state>_unnamed ...) are explained with the state's name. */
export function flagText(f: string, names: Record<string, string> = {}) {
  if (FLAG_TEXT[f]) return FLAG_TEXT[f]
  const m = f.match(/^(.+)_(uncertain|unmatched|unnamed|conflict)$/)
  if (!m || !names[m[1]]) return ''
  const name = names[m[1]]
  return { uncertain: t('「{name}」的分數在中間地帶', { name }), unmatched: t('「{name}」沒有相符的參考圖', { name }),
    unnamed: t('「{name}」還沒命名(到回答問題命名)', { name }), conflict: t('「{name}」和其他資料矛盾', { name }) }[m[2]] ?? ''
}
