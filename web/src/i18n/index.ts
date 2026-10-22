/**
 * Interface languages (多語系).
 *
 * The interface is written in Traditional Chinese and the Chinese text itself is the key: t('新增規則') shows
 * 「新增規則」 in 繁體中文, and in another language the text its catalog gives (src/i18n/locales/<lang>.json,
 * {"新增規則": "Add rule"}); a text the catalog lacks falls back to the Chinese.
 * Values go in by name: t('第 {n} 步', { n: 3 }). Keep the whole sentence in one text, so a language with another
 * word order can move the values.
 *
 * The language is chosen per browser (localStorage; until one is picked, the browser's own) and sent with every
 * request (X-Lang), so the sentences the server builds come in it too. Changing it reloads the page (texts outside components are read once).
 * tools/i18n.py lists every text in use (src/i18n/zh-TW.json, the full list to translate) and what each language
 * still lacks.
 */
const files = import.meta.glob('./locales/*.json', { eager: true, import: 'default' }) as Record<string, Record<string, string>>

export const BASE = 'zh-TW'
/** the languages the interface can be in, in their own words */
export const LANG_NAMES: Record<string, string> = { 'zh-TW': '繁體中文', en: 'English', 'zh-CN': '简体中文', ja: '日本語', ko: '한국어' }

const catalogs: Record<string, Record<string, string>> = {}
for (const [path, c] of Object.entries(files)) catalogs[path.replace(/^.*\/([^/]+)\.json$/, '$1')] = c

/** the languages that can be picked now: the base one and those with a catalog */
export const languages = Object.keys(LANG_NAMES).filter(l => l === BASE || Object.keys(catalogs[l] ?? {}).length > 0)

function pick(): string {
  try {
    const s = localStorage.getItem('inspector.lang')
    if (s && languages.includes(s)) return s
  } catch { /* private window: the browser's language */ }
  return fromBrowser()
}

/** never picked here: the first of the browser's languages there is a catalog for (zh-HK / zh-Hant -> zh-TW) */
function fromBrowser(): string {
  let wanted: readonly string[] = []
  try { wanted = navigator.languages?.length ? navigator.languages : [navigator.language] } catch { /* not in a page */ }
  for (const w of wanted) {
    const l = (w || '').toLowerCase()
    const code = l.startsWith('zh') ? (/hans|cn|sg/.test(l) ? 'zh-CN' : 'zh-TW') : l.split('-')[0]
    if (languages.includes(code)) return code
  }
  return BASE
}

/** the language this page is in */
export const lang = pick()
/** for dates and numbers (toLocaleString) */
export const locale = lang
const table = lang === BASE ? null : catalogs[lang] ?? null
try { document.documentElement.lang = lang === 'zh-TW' ? 'zh-Hant' : lang === 'zh-CN' ? 'zh-Hans' : lang } catch { /* not in a page */ }

type Params = Record<string, unknown>   // any value: shown as String(value), like a template string would

/** the text in the interface's language, with {name} filled in from params */
export function t(msg: string, params?: Params): string {
  const s = (table && table[msg]) || msg
  if (!params) return s
  return s
    // a translation may pick a word by a count: {n|frame|frames} (the first when n is 1)
    .replace(/\{(\w+)\|([^|{}]*)\|([^|{}]*)\}/g, (m, k: string, one: string, many: string) => (params[k] == null ? m : Number(params[k]) === 1 ? one : many))
    .replace(/\{(\w+)\}/g, (m, k: string) => (params[k] != null ? String(params[k]) : m))
}

/** switch the interface's language (the page reloads) */
export function setLang(l: string) {
  try { localStorage.setItem('inspector.lang', l) } catch { /* not kept: this page only */ }
  location.reload()
}
