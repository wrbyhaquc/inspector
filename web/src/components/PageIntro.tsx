import { t } from '../i18n'
import { useState } from 'react'
import { tutorialLink } from '../lib/tutorial'

const KEY = 'inspector.intro.'

/** "What this page is for": shown until closed (remembered in this browser), with the tutorial's chapter on it. */
export function PageIntro({ id, what, start, ch }: { id: string; what: string; start: string; ch?: number }) {
  const [shown, setShown] = useState(() => { try { return localStorage.getItem(KEY + id) !== '1' } catch { return true } })
  if (!shown) return null
  const close = () => { try { localStorage.setItem(KEY + id, '1') } catch { /* this page only */ } ; setShown(false) }
  return (
    <div className="rounded-lg border border-sky-200 bg-sky-50 px-4 py-3 text-sm text-sky-950 flex gap-3 items-start">
      <div className="flex-1 flex flex-col gap-1">
        <b>{t('這頁是做什麼的')}</b>
        <span>{what}</span>
        <span><span className="text-sky-800 font-medium">{t('從這裡開始:')}</span>{start}</span>
        {ch && <a className="text-sky-700 underline w-fit" href={tutorialLink(ch)} target="_blank" rel="noreferrer">{t('教學的這一章 ↗')}</a>}
      </div>
      <button className="text-sky-700 hover:text-sky-950 shrink-0" onClick={close} title={t('知道了,不再顯示')}>{t('知道了')}</button>
    </div>
  )
}
