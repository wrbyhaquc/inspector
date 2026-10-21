import { t } from '../i18n'
import { useState, type ReactNode, type RefObject } from 'react'

/** Drag handle: start dragging the row it sits in. onStart runs a tick later - changing the page inside dragstart
 * (showing the drop lines) would cancel the drag in Chrome. */
export function Grip({ rowRef, onStart, onEnd, title = t('拖拉來移動') }: {
  rowRef?: RefObject<HTMLElement | null>; onStart: () => void; onEnd: () => void; title?: string
}) {
  return (
    <span draggable title={title} aria-label={title}
      className="cursor-grab active:cursor-grabbing select-none text-stone-400 hover:text-stone-800 px-0.5 leading-none"
      onDragStart={e => {
        e.dataTransfer.effectAllowed = 'move'
        e.dataTransfer.setData('text/plain', '')
        if (rowRef?.current) e.dataTransfer.setDragImage(rowRef.current, 14, 14)
        setTimeout(onStart, 0)
      }}
      onDragEnd={onEnd}>⠿</span>
  )
}

/** A thin line between items that takes the drop while something is being dragged (hidden otherwise). */
export function DropLine({ active, onDrop, label }: { active: boolean; onDrop: () => void; label?: string }) {
  const [over, setOver] = useState(false)
  if (!active) return null
  return (
    <div className="h-4 -my-1.5 flex items-center relative z-10"
      onDragOver={e => { e.preventDefault(); e.dataTransfer.dropEffect = 'move'; if (!over) setOver(true) }}
      onDragLeave={() => setOver(false)}
      onDrop={e => { e.preventDefault(); setOver(false); onDrop() }}>
      <div className={`w-full rounded-full transition-all ${over ? 'h-1.5 bg-sky-500' : 'h-0.5 bg-sky-200'}`} />
      {over && label && <span className="absolute right-1 -top-3 text-[10px] text-sky-700 bg-white px-1 rounded">{label}</span>}
    </div>
  )
}

/** Any element that takes a drop (a group header, a situation tab): highlighted while something is over it. */
export function DropTarget({ active, onDrop, className = '', overClass = 'ring-2 ring-sky-500', children }: {
  active: boolean; onDrop: () => void; className?: string; overClass?: string; children: ReactNode
}) {
  const [over, setOver] = useState(false)
  return (
    <div className={`${className} ${active && over ? overClass : ''}`}
      onDragOver={active ? e => { e.preventDefault(); e.dataTransfer.dropEffect = 'move'; if (!over) setOver(true) } : undefined}
      onDragLeave={active ? () => setOver(false) : undefined}
      onDrop={active ? e => { e.preventDefault(); setOver(false); onDrop() } : undefined}>
      {children}
    </div>
  )
}

/** Move one item inside an array (to = the gap index before removal, 0..length). */
export function moveInList<T>(xs: T[], from: number, to: number) {
  if (to === from || to === from + 1) return
  const [it] = xs.splice(from, 1)
  xs.splice(to > from ? to - 1 : to, 0, it)
}
