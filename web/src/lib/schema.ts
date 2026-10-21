import { t } from '../i18n'
import { pluginUi } from './project'
import { useQuery } from '@tanstack/react-query'
import { api, type StateDef } from '../api'

/** Current state definitions; every page that crops, overlays or asks questions reads from here. */
export function useSchema() {
  return useQuery({ queryKey: ['schema'], queryFn: api.states, staleTime: 30_000 })
}

export const reviewStates = (states: StateDef[] = []) =>
  states.filter(s => s.type === 'class' && s.review?.enabled && s.classes?.length)

/** The region to zoom on when showing a state: its review region, else its first region. */
export const mainRoi = (s: StateDef) => s.rois.find(r => r.id === s.review?.roi) ?? s.rois[0]

// Tailwind classes per colour name used in class definitions (must be literal strings for Tailwind to keep them)
export const COLORS: Record<string, { pill: string; box: string; hex: string }> = {
  green: { pill: 'bg-emerald-50 text-emerald-700', box: 'border-emerald-400', hex: '#34d399' },
  red: { pill: 'bg-rose-50 text-rose-700', box: 'border-rose-400', hex: '#fb7185' },
  blue: { pill: 'bg-sky-50 text-sky-700', box: 'border-sky-400', hex: '#38bdf8' },
  amber: { pill: 'bg-amber-50 text-amber-800', box: 'border-amber-400', hex: '#fbbf24' },
  violet: { pill: 'bg-violet-50 text-violet-700', box: 'border-violet-400', hex: '#a78bfa' },
  stone: { pill: 'bg-stone-100 text-stone-600', box: 'border-stone-400', hex: '#a8a29e' },
}
export const COLOR_NAMES = Object.keys(COLORS)

/** Distinct overlay colour per state (by position in the schema). */
const STATE_HEX = ['#fbbf24', '#38bdf8', '#a78bfa', '#fb7185', '#34d399', '#f472b6', '#facc15', '#60a5fa']
export const stateColor = (index: number) => STATE_HEX[index % STATE_HEX.length]


const GENERIC_RULE_TEXT: Record<string, string> = { color_ratio: t('數顏色比例'), template: t('和參考圖比對') }

export interface RoiUse { text: string; kind: 'display' | 'rule' | 'plugin' | 'unused' }

/** What a region is used for, so editing it shows what will be affected. */
export function roiUses(s: StateDef, roiId: string): RoiUse[] {
  const uses: RoiUse[] = []
  if (mainRoi(s)?.id === roiId) {
    if (s.review?.enabled) uses.push({ text: t('人工確認顯示'), kind: 'display' })
    uses.push({ text: t('資料瀏覽顯示'), kind: 'display' })
  }
  const generic = GENERIC_RULE_TEXT[s.source.rule ?? '']
  const rule = generic ? (s.source.params?.roi === roiId ? t('規則:{generic}', { generic }) : undefined) : pluginUi.ruleRoiUses[s.source.rule ?? '']?.[roiId]
  if (rule && s.source.kind !== 'manual') uses.push({ text: rule, kind: 'rule' })
  if (s.source.kind === 'gallery' && s.rois[0]?.id === roiId) uses.push({ text: t('名稱庫:切出名稱並比對'), kind: 'rule' })
  if (!['rule', 'gallery', 'manual'].includes(s.source.kind) && mainRoi(s)?.id === roiId)      // a plugin's label source
    uses.push({ text: t('畫面對照(標籤來自{p1})', { p1: SOURCE_TEXT[s.source.kind] ?? s.source.kind }), kind: 'plugin' })
  if (!uses.length) uses.push({ text: t('目前沒有用到'), kind: 'unused' })
  return uses
}

export const USE_STYLE: Record<RoiUse['kind'], string> = {
  display: 'bg-sky-50 text-sky-700',
  rule: 'bg-amber-50 text-amber-800',
  plugin: 'bg-violet-50 text-violet-700',
  unused: 'bg-stone-100 text-stone-500',
}

export const TYPE_TEXT: Record<string, string> = { class: t('分類'), ratio: t('比例 0~1'), number: t('數值'), gallery: t('名稱庫') }
/** source kinds: the platform's; the label sources of the project's plugins are added when the project loads */
export const SOURCE_TEXT: Record<string, string> = { rule: t('畫面規則'), gallery: t('名稱庫'), manual: t('人工標註') }
