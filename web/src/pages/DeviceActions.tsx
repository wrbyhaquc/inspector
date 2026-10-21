import { t } from '../i18n'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api, type ArgValue, type Hold, type ProcInfo, type ShadowAct } from '../api'
import { Button } from '../components/ui'
import { ArgsEditor, CondEnv } from './Scripts'

const input = 'border border-stone-300 rounded-md px-2 py-1 text-sm bg-white'

type Busy = { name?: string; sub?: string; now?: string; loop?: string | null; schedule: boolean }

/** "操作" in the monitor: start something on this emulator now, or stop / pause what it is doing.
 * Everything goes through /api/shadow/act; when the emulator is busy it asks first: interrupt, or wait in line. */
export default function DeviceActions({ device, proc, hold, bare = false }: { device: string; proc?: ProcInfo | null; hold: Hold | null; bare?: boolean }) {
  const qc = useQueryClient()
  const [openState, setOpen] = useState(false)
  const open = bare || openState
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null)
  const [ask, setAsk] = useState<{ act: ShadowAct; label: string; busy: Busy } | null>(null)
  const acts = useQuery({ queryKey: ['actions', device], queryFn: () => api.shadowActions(device), enabled: open, refetchInterval: open ? 5000 : false })
  const send = useMutation({
    mutationFn: (x: { act: ShadowAct; label: string }) => api.shadowAct(x.act),
    onSuccess: (r, x) => {
      if (r.busy) { setAsk({ ...x, busy: r.busy }); return }
      setAsk(null)
      setMsg({ ok: true, text: t('已送出:{label}(結果會出現在「紀錄」)', { label: x.label }) })
      qc.invalidateQueries({ queryKey: ['shadow'] })
      qc.invalidateQueries({ queryKey: ['actions', device] })
    },
    onError: (e: Error) => setMsg({ ok: false, text: e.message }),
  })
  const go = (act: Omit<ShadowAct, 'device'>, label: string, confirmText?: string) => {
    if (confirmText && !window.confirm(confirmText)) return
    setMsg(null)
    send.mutate({ act: { device, if_busy: 'ask', ...act }, label })
  }
  const isSched = !!proc?.script?.startsWith('schedule:')

  return (
    <div className={bare ? '' : 'rounded-md border border-stone-200'}>
      {!bare && <button onClick={() => setOpen(v => !v)} className="w-full text-left px-3 py-2 text-sm font-semibold flex items-center gap-2">
        {t('⚡ 操作這台')}<span className="text-xs font-normal text-stone-500">{t('立即執行排程、切換情境、執行子腳本、停止')}</span>
        <span className="ml-auto text-xs text-sky-700">{open ? t('收起 ▴') : t('展開 ▾')}</span>
      </button>}
      {open && <div className={`flex flex-col gap-3 text-sm ${bare ? '' : 'px-3 pb-3 border-t border-stone-100 pt-2'}`}>
        {!bare && <Section title={t('這台')}>
          <div className="flex flex-wrap gap-2">
            {hold ? <Button variant="primary" disabled={send.isPending} onClick={() => go({ kind: 'resume' }, t('繼續'))}>{t('▶ 繼續')}{hold.mode === 'pause' ? t('(從同一步接著做)') : ''}</Button> : <>
              <Button disabled={send.isPending} onClick={() => go({ kind: 'pause' }, t('暫停'))} title={t('腳本、情境和正在做的事都停在原地,按「繼續」從同一步接著做')}>{t('⏸ 暫停')}</Button>
              <Button variant="danger" disabled={send.isPending} onClick={() => go({ kind: 'stop', mode: 'stop' }, t('停下來'), t('{device} 停下來?正在做的事會取消(先做收尾),腳本和情境都停住,按「繼續」後從頭開始。', { device }))}>{t('🛑 停下來')}</Button>
            </>}
          </div>
          {hold && <div className="text-xs text-amber-800">{hold.mode === 'pause' ? t('這台暫停中:下面的動作要先按「繼續」') : t('這台停下來中:下面的動作要先按「繼續」')}</div>}
        </Section>}
        {bare && hold && <div className="text-xs text-amber-800 bg-amber-50 rounded px-2 py-1">{hold.mode === 'pause' ? t('這台暫停中:下面的動作要先按「繼續」') : t('這台停下來中:下面的動作要先按「繼續」')}</div>}
        {msg && <div className={`text-xs rounded px-2 py-1 ${msg.ok ? 'bg-emerald-50 text-emerald-900' : 'bg-rose-50 text-rose-900'}`}>{msg.ok ? '✔ ' : '✖ '}{msg.text}</div>}

        {ask && (
          <div className="rounded-md border-2 border-amber-300 bg-amber-50 p-2 flex flex-col gap-2">
            <div>{t('這台正在做:')}<b>{ask.busy.name}</b>{ask.busy.sub ? ` › ${ask.busy.sub}` : ''}{ask.busy.loop ? `(${ask.busy.loop})` : ''}
              <div className="text-xs text-stone-600">{ask.busy.now}</div></div>
            <div>{t('要怎麼處理「{label}」?', { label: ask.label })}</div>
            <div className="flex flex-wrap gap-2">
              <Button variant="danger" onClick={() => send.mutate({ act: { ...ask.act, if_busy: 'interrupt' }, label: ask.label })}>{t('中斷它,改做這個')}</Button>
              <Button onClick={() => send.mutate({ act: { ...ask.act, if_busy: 'queue' }, label: ask.label })}>{t('等它做完再做')}</Button>
              <Button variant="ghost" onClick={() => setAsk(null)}>{t('取消')}</Button>
            </div>
          </div>
        )}

        {proc && (
          <Section title={t('目前的動作')}>
            <div className="text-xs">{proc.script_name} › {proc.sub_name}{proc.loop ? `(${proc.loop})` : ''}{proc.paused ? t(' · ⏸ 暫停中') : ''}</div>
            <div className="flex flex-wrap gap-2">
              <Button disabled={send.isPending}
                onClick={() => go({ kind: 'stop', mode: 'abort' }, t('停止「{sub_name}」', { sub_name: proc.sub_name }), isSched ? t('要停止 {device} 目前的「{sub}」嗎?(會做收尾步驟,排程今天記為中斷)', { device, sub: proc.sub_name })
                  : t('要停止 {device} 目前的「{sub}」嗎?(會做收尾步驟)', { device, sub: proc.sub_name }))} title={t('只結束這一個動作,不會停下來')}>{t('結束這個動作')}</Button>

            </div>
          </Section>
        )}

        <Section title={t('排程')}>
          {acts.isLoading && <div className="text-xs text-stone-500">{t('讀取中…')}</div>}
          {acts.data?.schedules.length === 0 && <div className="text-xs text-stone-500">{t('沒有排程包含這台(到「排程」勾選這台)')}</div>}
          {acts.data?.schedules.map(s => (
            <div key={s.id} className="flex items-center gap-2">
              <span className="flex-1">{s.name}<span className="text-xs text-stone-500"> {s.enabled ? t('每天 {at}', { at: s.at }) : t('停用')} · {s.status?.text ?? '—'}</span></span>
              <Button disabled={send.isPending || s.status?.code === 'running'}
                onClick={() => go({ kind: 'schedule', id: s.id }, t('立即執行排程「{name}」', { name: s.name }),
                  t('現在就在 {device} 執行「{name}」?\n(會真的點擊;已經做完的部分,子腳本通常會自己略過)', { device, name: s.name }))}>{t('立即執行')}</Button>
            </div>
          ))}
        </Section>

        <Section title={t('主腳本:切到情境(會做這個情境的進入動作)')}>
          {acts.data?.scripts.length === 0 && <div className="text-xs text-stone-500">{t('這台沒有多情境的主腳本')}</div>}
          {acts.data?.scripts.map(sc => (
            <div key={sc.id} className="flex flex-wrap items-center gap-1.5">
              <span className="text-xs text-stone-600 mr-1">{sc.name}</span>
              {sc.situations.map(x => (
                <Button key={x.id} disabled={send.isPending}
                  onClick={() => go({ kind: 'situation', script: sc.id, situation: x.id }, t('「{name}」切到「{name2}」', { name: sc.name, name2: x.name }),
                    t('把 {device} 的「{script}」切到「{situation}」?', { device, script: sc.name, situation: x.name }) + (x.enter ? '\n' + t('(會馬上做這個情境的進入動作)') : ''))}>{x.name}</Button>
              ))}
            </div>
          ))}
        </Section>

        <SubRunner device={device} busy={send.isPending}
          onRun={(sub, name, args) => go({ kind: 'sub', sub, args }, t('執行子腳本「{name}」', { name }), t('在 {device} 執行一次「{name}」?(會真的點擊)', { device, name }))} />
      </div>}
    </div>
  )
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return <div className="flex flex-col gap-1.5"><div className="text-xs font-semibold text-stone-500">{title}</div>{children}</div>
}

/** 進階:pick a sub-script, fill its parameters (accounts / places of this device), run it once. */
function SubRunner({ device, busy, onRun }: { device: string; busy: boolean; onRun: (sub: string, name: string, args: Record<string, ArgValue>) => void }) {
  const [open, setOpen] = useState(false)
  const info = useQuery({ queryKey: ['scripts'], queryFn: api.scripts, enabled: open })
  const [sid, setSid] = useState('')
  const [args, setArgs] = useState<Record<string, ArgValue>>({})
  const sub = info.data?.subs.find(s => s.id === sid)
  if (!open) return <button className="text-xs text-left text-sky-700 underline" onClick={() => setOpen(true)}>{t('進階:執行一次子腳本 ▾')}</button>
  return (
    <Section title={t('進階:執行一次子腳本')}>
      <div className="flex items-center gap-2">
        <select className={input} value={sid} onChange={e => { setSid(e.target.value); setArgs({}) }}>
          <option value="">{t('(選子腳本)')}</option>
          {info.data?.subs.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
        </select>
        <Button disabled={!sub || busy} onClick={() => sub && onRun(sub.id, sub.name, args)}>{t('執行一次')}</Button>
      </div>
      {sub && info.data && (
        <CondEnv.Provider value={{ info: info.data, devices: [device] }}>
          <ArgsEditor sub={sub} args={args} info={info.data} callerParams={[]} device={device} onChange={setArgs} />
        </CondEnv.Provider>
      )}
    </Section>
  )
}
