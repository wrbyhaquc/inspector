import { t } from '../i18n'
// The project being worked on (project.json): its coordinate space and its words. Read once before the app renders,
// so every page can use them directly; nothing on the pages is tied to one app or one screen size.
import { FLAG_TEXT } from './format'
import { SOURCE_TEXT } from './schema'


/** the coordinate space: every frame is this size, every position is in it */
export const screen = { w: 1280, h: 720 }
/** what this project calls things (e.g. a device is a 模擬器, an item of a per-device list is a 帳號) */
export const words: Record<string, string> = { device: t('裝置'), item: t('項目') }
export const projectInfo = { id: '', name: '' }
/** what this installation is: a studio designs, teaches and exports packs; a runtime installs packs and runs them
 *  (no design pages, no PyTorch, so it cannot train) */
export const edition: { name: 'studio' | 'runtime'; training: boolean } = { name: 'studio', training: true }
/** what the project's plugins add to the pages: flag meanings, what a plugin rule reads in each region, names of
 *  label-source kinds */
export const pluginUi: { ruleRoiUses: Record<string, Record<string, string>> } = { ruleRoiUses: {} }

export async function loadProject() {
  try {
    const r = await fetch('/api/project', { credentials: 'same-origin' })
    if (!r.ok) return
    const p = await r.json()
    screen.w = Number(p.screen?.width) || screen.w
    screen.h = Number(p.screen?.height) || screen.h
    Object.assign(words, p.words ?? {})
    projectInfo.id = p.id ?? ''
    projectInfo.name = p.name ?? ''
    edition.training = p.edition?.training ?? true
    edition.name = p.edition?.name === 'runtime' ? 'runtime' : 'studio'
    Object.assign(FLAG_TEXT, p.ui?.flags ?? {})
    Object.assign(SOURCE_TEXT, p.ui?.source_kinds ?? {})
    pluginUi.ruleRoiUses = p.ui?.rule_roi_uses ?? {}
  } catch { /* the defaults stay */ }
}
