import { lang, t } from '../i18n'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api, type AiLevel, type AiLogEntry } from '../api'
import { AiRequests } from '../components/AiRequests'
import { Button, Card, ErrorText, Page } from '../components/ui'
import { dateTime } from '../lib/format'

const LEVELS: [AiLevel, string, string][] = [
  ['read', t('只能看'), t('看設計和執行的情況、說明規則、整理報告、只檢查不存、重播錄影')],
  ['design', t('可以改設計'), t('再加上修改腳本、狀態、排程、面板等;它存的腳本只會試跑,不會正式執行')],
  ['run', t('可以控制執行'), t('再加上開始 / 停止、停下來 / 暫停 / 繼續、部署成關閉或試跑、改設定的值;正式執行只能提出要求,由人同意')],
]
const UNDOABLE = ['save_script', 'delete_script', 'save_subscript', 'delete_subscript', 'save_panel', 'save_state', 'save_schedule',
  'save_user_setting', 'save_variable', 'save_output']

function Copy({ text }: { text: string }) {
  const [ok, setOk] = useState(false)
  return (
    <div className="flex items-start gap-2">
      <pre className="flex-1 min-w-0 overflow-x-auto rounded-md bg-stone-900 text-stone-100 text-xs px-3 py-2 whitespace-pre-wrap break-all">{text}</pre>
      <Button onClick={() => { navigator.clipboard?.writeText(text).then(() => { setOk(true); setTimeout(() => setOk(false), 1500) }).catch(() => undefined) }}>
        {ok ? t('已複製') : t('複製')}</Button>
    </div>
  )
}

/** Letting an AI in: how to connect it (here or over the network with a token), the tokens, what it did (undo), what it asks. */
export default function AiAccess() {
  return (
    <Page title={t('AI 接入')} desc={t('讓 Claude 等支援 MCP 的 AI 工具連到這台 Inspector:看設計和執行的情況、幫你改設計、照顧執行。它能做多少由權限決定;正式執行一定要由人同意。')}>
      <AiRequests />
      <Connect />
      <Tokens />
      <Log />
    </Page>
  )
}

function Connect() {
  const q = useQuery({ queryKey: ['aiConnect'], queryFn: api.aiConnect })
  const [level, setLevel] = useState<AiLevel>('design')
  const c = q.data
  if (!c) return <ErrorText error={q.error} />
  const desktop = JSON.stringify({ mcpServers: { inspector: { command: c.python, args: ['-m', 'mcp_server', '--level', level, '--url', `http://127.0.0.1:${c.port}`], cwd: c.folder } } }, null, 2)
  return (
    <Card title={t('在這台電腦上連(建議)')} extra={<span className="text-xs text-stone-500">{t('AI 工具裝在這台電腦上時用這個,不需要權杖')}</span>}>
      <div className="flex flex-col gap-3 text-sm">
        <div className="flex flex-wrap gap-2">
          {LEVELS.map(([v, name, help]) => (
            <label key={v} title={help} className={`flex items-center gap-1.5 rounded-md border px-2.5 py-1 cursor-pointer ${level === v ? 'border-stone-800 bg-stone-50' : 'border-stone-200'}`}>
              <input type="radio" checked={level === v} onChange={() => setLevel(v)} />{name}</label>))}
          <span className="text-xs text-stone-500 self-center">{LEVELS.find(l => l[0] === level)![2]}</span>
        </div>
        <div className="font-medium">{t('Claude Code(在終端機執行)')}</div>
        <Copy text={`cd "${c.folder}"\nclaude mcp add inspector -- python -m mcp_server --level ${level} --url http://127.0.0.1:${c.port}`} />
        <div className="font-medium">{t('Claude Desktop(貼進 claude_desktop_config.json,再重新開啟 Claude)')}</div>
        <Copy text={desktop} />
        <div className="text-xs text-stone-500">{t('接好後可以直接問它:「現在怎麼樣?」「為什麼這條規則沒觸發?」「昨天發生了什麼?」。Inspector 要開著。')}</div>
        <div className="text-xs text-stone-500">{t('也可以在 AI 工具裡選用工作範本:每日報告(daily_report)、找原因(diagnose)、做一個方案(build_solution)、上線前檢查(check_before_live)。')}
          {' '}<a className="underline text-sky-700" target="_blank" rel="noreferrer"
            href={`https://github.com/wrbyhaquc/inspector/blob/main/docs/${lang.startsWith('zh') ? 'ai.zh-TW.md' : 'ai.md'}`}>{t('完整說明 ↗')}</a></div>
      </div>
    </Card>
  )
}

function Tokens() {
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['aiTokens'], queryFn: api.aiTokens })
  const c = useQuery({ queryKey: ['aiConnect'], queryFn: api.aiConnect })
  const [name, setName] = useState('')
  const [level, setLevel] = useState<AiLevel>('design')
  const make = useMutation({ mutationFn: () => api.aiTokenNew(name, level), onSuccess: () => { setName(''); qc.invalidateQueries({ queryKey: ['aiTokens'] }) } })
  const revoke = useMutation({ mutationFn: api.aiTokenRevoke, onSuccess: () => qc.invalidateQueries({ queryKey: ['aiTokens'] }) })
  const url = c.data?.lan_mcp ?? c.data?.local_mcp ?? ''
  const input = 'border border-stone-300 rounded-md px-2 py-1 text-sm'
  return (
    <Card title={t('從別台電腦連(權杖)')} extra={<span className="text-xs text-stone-500">{t('每個 AI 工具一把權杖,可以隨時撤銷')}</span>}>
      <div className="flex flex-col gap-3 text-sm">
        <div className="text-xs text-stone-600">
          {c.data?.lan_mcp ? t('位址:{url}', { url }) : t('Inspector 現在只接受這台電腦的連線;要讓別台連,用 --lan 啟動(start.bat 或 python -m server --lan)。')}
          {' '}{t('同一個網路裡權杖不會加密;要從外面連,請透過 Tailscale 或 VPN 等加密的通道。')}</div>
        <div className="flex flex-wrap items-center gap-2">
          <input className={`${input} w-56`} placeholder={t('名稱,例如:辦公室的 Claude')} value={name} onChange={e => setName(e.target.value)} maxLength={60} />
          <select className={input} value={level} onChange={e => setLevel(e.target.value as AiLevel)}>
            {LEVELS.map(([v, n]) => <option key={v} value={v}>{n}</option>)}</select>
          <Button variant="primary" disabled={!name.trim() || make.isPending} onClick={() => make.mutate()}>{t('建立權杖')}</Button>
        </div>
        {make.data && <div className="rounded-md border border-amber-300 bg-amber-50 px-3 py-2 flex flex-col gap-2">
          <b>{t('權杖只會顯示這一次,請現在複製起來:')}</b>
          <Copy text={make.data.token} />
          <div className="text-xs">{t('Claude Code:')}</div>
          <Copy text={`claude mcp add --transport http inspector ${url} --header "Authorization: Bearer ${make.data.token}"`} />
        </div>}
        <div className="flex flex-col divide-y divide-stone-100">
          {(q.data?.items ?? []).map(r => (
            <div key={r.id} className={`py-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 ${r.revoked ? 'text-stone-400' : ''}`}>
              <b>{r.name}</b>
              <span className="text-xs px-1.5 rounded bg-stone-100">{LEVELS.find(l => l[0] === r.level)?.[1] ?? r.level}</span>
              <span className="text-xs num">{t('建立 {t}', { t: dateTime(r.created) })}{' · '}{r.last_used ? t('最近使用 {t}', { t: dateTime(r.last_used) }) : t('還沒用過')}</span>
              <span className="flex-1" />
              {r.revoked ? <span className="text-xs">{t('已撤銷')}</span>
                : <Button variant="ghost" disabled={revoke.isPending} onClick={() => { if (confirm(t('撤銷「{name}」?用它的 AI 工具會馬上連不上。', { name: r.name }))) revoke.mutate(r.id) }}>{t('撤銷')}</Button>}
            </div>
          ))}
          {!q.data?.items.length && <div className="text-stone-500 py-1">{t('還沒有權杖:沒有權杖時,別台電腦的 AI 一律連不上。')}</div>}
        </div>
        <ErrorText error={make.error || revoke.error} />
      </div>
    </Card>
  )
}

function Log() {
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['aiLog'], queryFn: api.aiLog, refetchInterval: 15000 })
  const undo = useMutation({ mutationFn: (e: AiLogEntry) => api.aiUndo(e.id), onSuccess: () => qc.invalidateQueries({ queryKey: ['aiLog'] }) })
  const items = q.data?.items ?? []
  return (
    <Card title={t('AI 做過的事')} extra={<span className="text-xs text-stone-500">{t('每一筆都有理由;改設計的可以退回到改之前')}</span>}>
      {items.length === 0 ? <div className="text-sm text-stone-500">{t('AI 還沒有做過任何修改。')}</div> : (
        <div className="flex flex-col divide-y divide-stone-100 text-sm">
          {items.map(e => (
            <div key={e.id} className="py-1.5 flex flex-wrap items-center gap-x-3 gap-y-0.5">
              <span className="text-stone-500 num text-xs">{dateTime(e.t)}</span>
              {e.client && <span className="text-xs px-1.5 rounded bg-violet-100 text-violet-900">{e.client}</span>}
              <span className="font-mono text-xs">{e.tool}</span>
              <span className="text-xs text-stone-600">{e.target}</span>
              <span className="flex-1 min-w-[12rem]">{e.reason}</span>
              {UNDOABLE.includes(e.tool) && <Button variant="ghost" disabled={undo.isPending}
                onClick={() => { if (confirm(t('把這次修改退回到改之前?'))) undo.mutate(e) }}>{t('退回')}</Button>}
            </div>
          ))}
        </div>
      )}
      {undo.data && <div className="text-xs text-emerald-700 mt-2">{t('已退回')}</div>}
      <ErrorText error={q.error || undo.error} />
    </Card>
  )
}
