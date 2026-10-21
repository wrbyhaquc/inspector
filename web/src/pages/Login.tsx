import { useState } from 'react'
import { api } from '../api'
import { t } from '../i18n'

/** PIN sign-in for phones on the LAN: big keys, nothing else on the screen. */
export default function Login({ configured }: { configured?: { user: boolean; admin: boolean } }) {
  const [pin, setPin] = useState('')
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const ready = configured?.user || configured?.admin
  const go = async () => {
    setBusy(true); setErr('')
    try { await api.authLogin(pin); window.location.reload() } catch (e) { setErr((e as Error).message); setPin('') } finally { setBusy(false) }
  }
  if (!ready) return <div className="h-full flex items-center justify-center p-6 text-xl text-stone-700 text-center">{t('這套系統還沒開放從其他裝置登入。')}<br />{t('請聯絡負責人設定登入密碼。')}</div>
  return (
    <div className="h-full flex flex-col items-center justify-center gap-5 p-6 bg-stone-50">
      <h1 className="text-2xl font-bold">{t('請輸入密碼')}</h1>
      <div className="text-4xl tracking-[0.5em] h-12 font-mono">{'●'.repeat(pin.length) || <span className="text-stone-300 tracking-normal text-2xl">{t('4~8 位數字')}</span>}</div>
      {err && <div className="text-rose-700 text-lg">{err}</div>}
      <div className="grid grid-cols-3 gap-3">
        {['1', '2', '3', '4', '5', '6', '7', '8', '9', t('清除'), '0', '⌫'].map(k => (
          <button key={k} disabled={busy} onClick={() => setPin(p => k === t('清除') ? '' : k === '⌫' ? p.slice(0, -1) : (p + k).slice(0, 8))}
            className="w-20 h-20 rounded-2xl bg-white border-2 border-stone-300 text-3xl font-bold active:bg-stone-200">{k}</button>
        ))}
      </div>
      <button disabled={busy || pin.length < 4} onClick={go} className="w-full max-w-xs py-4 rounded-2xl bg-emerald-600 text-white text-2xl font-bold disabled:opacity-40">{t('進入')}</button>
    </div>
  )
}
