import type { PanelBlock, PanelControl } from '../api'

/** A new block's width on the 12-column grid: the whole row for long lists, logs and settings asked per device, else
 * half (as the server places a block without a place: server/panel.py auto_wide). */
export function autoWide(b: PanelBlock, byId: Record<string, PanelControl>) {
  if (b.widget) return ['list', 'log', 'chat', 'devices'].includes(b.widget.kind)
  return b.items.some(i => byId[i]?.scope === 'device' && byId[i]?.type !== 'action')
}
