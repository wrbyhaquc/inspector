import { t } from '../i18n'
import { dn, tagIds, tagList } from '../lib/sources'

/** Tick sources - or a tag (#北棟 = every source with it, also the ones added later). value holds ids and "#tag". */
export function SourcePick({ value, devices, onChange, sort = false }: { value: string[]; devices: string[]; onChange: (v: string[]) => void; sort?: boolean }) {
  const set = (k: string, on: boolean) => { const n = on ? [...value, k] : value.filter(x => x !== k); onChange(sort ? [...n].sort() : n) }
  const byTag = new Set(value.filter(k => k.startsWith('#')).flatMap(tagIds))
  return (
    <>
      {tagList().map(tx => (
        <label key={tx} className="flex items-center gap-1 text-sky-800" title={t('有標籤「{tx}」的:{p2};之後貼上這個標籤的也算', { tx, p2: tagIds(tx).map(dn).join(t('、')) })}>
          <input type="checkbox" checked={value.includes(`#${tx}`)} onChange={e => set(`#${tx}`, e.target.checked)} />#{tx}<span className="text-xs text-sky-600">({tagIds(tx).length})</span></label>
      ))}
      {devices.map(n => (
        <label key={n} className="flex items-center gap-1" title={byTag.has(n) && !value.includes(n) ? t('已經因為標籤包含') : n}>
          <input type="checkbox" checked={value.includes(n) || byTag.has(n)} disabled={byTag.has(n) && !value.includes(n)} onChange={e => set(n, e.target.checked)} />{dn(n)}</label>
      ))}
    </>
  )
}
