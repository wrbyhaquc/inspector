import type { PanelBlock, PanelControl } from '../api'

// The operation panel's layout on a wide screen: six columns, a block takes a third, a half, two thirds or all of a
// row (spec v10); "auto" = half, or the whole row for long lists, logs and settings asked per device. Phones: one column.
export type BlockWidth = NonNullable<PanelBlock['width']>
export const SPANS = { third: 2, narrow: 3, two_thirds: 4, wide: 6 } as const
export const SPAN_CLASS: Record<number, string> = { 2: 'xl:col-span-2', 3: 'xl:col-span-3', 4: 'xl:col-span-4', 6: 'xl:col-span-6' }
export const COLS = 6

/** what "auto" makes of a block: the whole row for long lists and logs, and settings asked per device */
export function autoWide(b: PanelBlock, byId: Record<string, PanelControl>) {
  if (b.widget) return ['list', 'log', 'chat', 'devices'].includes(b.widget.kind)
  return b.items.some(i => byId[i]?.scope === 'device' && byId[i]?.type !== 'action')
}

/** how many of the six columns the block takes */
export function span(b: PanelBlock, byId: Record<string, PanelControl>) {
  return b.width && b.width !== 'auto' ? SPANS[b.width] : autoWide(b, byId) ? 6 : 3
}

/** the width nearest to a number of columns (dragging a block's edge) */
export function widthFor(cols: number): Exclude<BlockWidth, 'auto'> {
  const [w] = (Object.entries(SPANS) as [Exclude<BlockWidth, 'auto'>, number][]).sort((a, b) => Math.abs(a[1] - cols) - Math.abs(b[1] - cols))[0]
  return w
}
