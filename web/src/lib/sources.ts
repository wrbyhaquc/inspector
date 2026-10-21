import { t } from '../i18n'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api'

// The names people read for sources (來源): ids stay the codes everything is keyed by, pages show these.
let names: Record<string, string> = {}
let enabled: string[] = []
let hands: Record<string, string> = {}
let tagMap: Record<string, string[]> = {}

/** a source's name for people (its id when it has none / is unknown) */
export const dn = (id?: string | null) => (id ? names[id] ?? id : '')

/** the sources that are used (in the 來源 page's order) plus any other ids given (e.g. the runner's): for every
 *  "which devices" list - a source that is off for now still shows where it was set up */
export const sourceIds = (also: string[] = []) => [...enabled, ...also.filter(x => !enabled.includes(x))]

/** where a source's actions go, when it is not itself (e.g. 送到輸出「水車」); '' for the usual case */
export const handOf = (id?: string | null) => (id ? hands[id] ?? '' : '')

/** the tags there are -> the sources with each ("#北棟" in a list means all of them) */
export const tagList = () => Object.keys(tagMap).sort()
export const tagIds = (tag: string) => tagMap[tag.replace(/^#/, '')] ?? []
/** ids and "#tag" -> the ids (each once) */
export const expandKeys = (ks: string[] = []) => [...new Set(ks.flatMap(k => (k.startsWith('#') ? tagIds(k) : [k])))]
/** "#tag" or an id -> what people read */
export const keyLabel = (k: string) => (k.startsWith('#') ? t('#{p1}({length} 台)', { p1: k.slice(1), length: tagIds(k).length }) : dn(k))

/** keep the names fresh; call once near the top of a page tree (App, the operation panel) */
export function useSourceNames() {
  const q = useQuery({ queryKey: ['sourceNames'], queryFn: api.sourceNames, refetchInterval: 30_000, retry: false })
  if (q.data) { names = q.data.names; enabled = q.data.enabled; hands = q.data.hands ?? {}; tagMap = q.data.tags ?? {} }
  return dn
}
