import { t } from './i18n'
import { LangPicker } from './components/LangPicker'
import { useQuery } from '@tanstack/react-query'
import Sources from './pages/Sources'
import { useSourceNames } from './lib/sources'
import { useEffect, useState } from 'react'
import { NavLink, Route, Routes, useLocation } from 'react-router-dom'
import { api } from './api'
import { usePersistentState } from './lib/persist'
import Browser from './pages/Browser'
import Collection from './pages/Collection'
import Labels from './pages/Labels'
import Overview from './pages/Overview'
import Results from './pages/Results'
import Review from './pages/Review'
import States from './pages/States'
import Training from './pages/Training'
import Shadow from './pages/Shadow'
import Scripts from './pages/Scripts'
import Library from './pages/Library'
import Tests from './pages/Tests'
import Schedules from './pages/Schedules'
import Panel from './pages/Panel'
import PanelDesign from './pages/PanelDesign'
import Login from './pages/Login'
import Storage from './pages/Storage'
import AiAccess from './pages/AiAccess'
import Packs from './pages/Packs'
import { edition } from './lib/project'

interface NavItem { to: string; label: string; end?: boolean }
interface NavGroup { title: string; hint: string; items: NavItem[]; advanced?: boolean }

// grouped by what the user wants to get done, not by technical step:
// tell it what to watch -> teach it to see -> let it act
const NAV: NavGroup[] = [
  { title: t('① 要看什麼'), hint: t('決定要看畫面上的哪些狀態,接上影像並錄製'), items: [
    { to: '/states', label: t('要看的狀態') },
    { to: '/sources', label: t('來源') },
    { to: '/collect', label: t('錄製') },
  ] },
  { title: t('② 教它看懂'), hint: t('回答一些問題,讓它學會判斷'), items: [
    { to: '/review', label: t('回答問題') },
    { to: '/train', label: t('學習') },
    { to: '/results', label: t('成績與錯題') },
  ] },
  { title: t('③ 自動化'), hint: t('依判斷結果自動做事'), items: [
    { to: '/scripts', label: t('腳本') },
    { to: '/tests', label: t('腳本測試') },
    { to: '/schedules', label: t('排程') },
    { to: '/library', label: t('素材庫') },
    { to: '/script', label: t('執行') },
    { to: '/panel-design', label: t('操作面板設計') },
    { to: '/panel', label: t('操作面板(給使用者) ↗') },
  ] },
  { title: t('④ 交付'), hint: t('做成方案包,在別台電腦安裝執行'), items: [
    { to: '/packs', label: t('方案包') },
  ] },
  { title: t('這台電腦'), hint: t('儲存空間、資料放在哪裡、讓 AI 接入'), items: [
    { to: '/storage', label: t('儲存空間') },
    { to: '/ai', label: t('AI 接入') },
  ] },
  { title: t('進階工具'), hint: t('檢查內部細節用,平常不需要'), advanced: true, items: [
    { to: '/browse', label: t('畫面瀏覽') },
    { to: '/labels', label: t('自動標註') },
  ] },
]
const LATER = [t('畫面分群'), t('模型管理')]
// a runtime (執行版) installs packs and runs them: no design pages
const RUNTIME_NAV: NavGroup[] = [
  { title: t('執行'), hint: t('接上裝置、執行方案包'), items: [
    { to: '/script', label: t('執行') },
    { to: '/sources', label: t('來源') },
    { to: '/panel', label: t('操作面板(給使用者) ↗') },
  ] },
  { title: t('方案包'), hint: t('安裝、升級、切換'), items: [
    { to: '/packs', label: t('方案包') },
  ] },
  { title: t('這台電腦'), hint: t('儲存空間、資料放在哪裡、讓 AI 接入'), items: [
    { to: '/storage', label: t('儲存空間') },
    { to: '/ai', label: t('AI 接入') },
  ] },
]

const linkClass = ({ isActive }: { isActive: boolean }) =>
  `px-3 py-1.5 rounded-md text-sm flex items-center justify-between gap-2 focus:outline-none focus-visible:ring-2 focus-visible:ring-amber-400 ${
    isActive ? 'bg-stone-700 text-white' : 'hover:bg-stone-800 hover:text-stone-100'}`

/** Who is this: this computer and consultants get everything; end users (PIN on a phone) only the operation panel. */
export default function App() {
  const loc = useLocation()
  const me = useQuery({ queryKey: ['authMe'], queryFn: api.authMe, staleTime: 60_000 })
  useSourceNames()
  const [need, setNeed] = useState(false)
  useEffect(() => {
    const f = () => setNeed(true)
    window.addEventListener('lm-login-needed', f)
    return () => window.removeEventListener('lm-login-needed', f)
  }, [])
  if (me.isLoading) return null
  if (!me.data?.role || need) return <Login configured={me.data?.configured} />
  const isPanel = loc.pathname === '/panel' || loc.pathname.startsWith('/panel/')
  if (isPanel || me.data.role === 'user') return <div className="h-full overflow-auto"><Panel canLogout={!me.data.local} /></div>
  return <AdminApp />
}

function AdminApp() {
  const col = useQuery({ queryKey: ['collector'], queryFn: api.collector, refetchInterval: 3000 })
  const running = col.data?.live?.running && !col.data.live.stale
  const steps = useQuery({ queryKey: ['nextSteps'], queryFn: api.nextSteps, refetchInterval: 30000 })
  const [showAdv, setShowAdv] = usePersistentState('nav.advanced', false)
  const runtime = edition.name === 'runtime'

  return (
    <div className="flex h-full">
      <aside className="w-56 shrink-0 bg-stone-900 text-stone-300 flex flex-col overflow-y-auto">
        <div className="px-5 py-5">
          <div className="text-stone-50 font-semibold tracking-wide">Inspector</div>
          <div className="text-xs text-stone-500 mt-0.5">{runtime ? t('執行版') : t('看畫面、自動做事')}</div>
        </div>
        <nav className="flex flex-col px-2 gap-4">
          <NavLink to="/" end className={linkClass}>
            {runtime ? t('首頁') : t('首頁:下一步')}
            {!!steps.data?.todo && <span className="text-[11px] px-1.5 rounded-full bg-amber-500 text-stone-900 font-medium num">{steps.data.todo}</span>}
          </NavLink>
          {(runtime ? RUNTIME_NAV : NAV).map(g => {
            const open = !g.advanced || showAdv
            return (
              <div key={g.title} className="flex flex-col gap-0.5">
                {g.advanced
                  ? <button onClick={() => setShowAdv(v => !v)} title={g.hint}
                      className="px-3 pb-1 text-left text-[11px] tracking-wider text-stone-500 hover:text-stone-300 flex justify-between">
                      {g.title}<span>{showAdv ? '▾' : '▸'}</span></button>
                  : <div className="px-3 pb-1 text-[11px] tracking-wider text-stone-400" title={g.hint}>{g.title}</div>}
                {open && g.items.map(n => (
                  <NavLink key={n.to} to={n.to} end={n.end} className={linkClass}>
                    {n.label}
                    {n.to === '/collect' && running && (
                      <span className="flex items-center gap-1 text-xs text-emerald-300">
                        <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />{t('錄製中')}
                      </span>
                    )}
                  </NavLink>
                ))}
              </div>
            )
          })}
        </nav>
        {showAdv && !runtime && <>
          <div className="mt-6 px-5 text-[11px] tracking-wider text-stone-500">{t('之後的階段')}</div>
          <div className="flex flex-col gap-0.5 px-2 mt-1">
            {LATER.map(l => <div key={l} className="px-3 py-1.5 text-sm text-stone-600">{l}</div>)}
          </div>
        </>}
        <div className="mt-auto px-4 py-4"><LangPicker className="w-full bg-stone-800 border-stone-700 text-stone-200" /></div>
      </aside>
      <main className="flex-1 min-w-0 overflow-auto">
        {runtime ? (
          <Routes>
            <Route path="/sources" element={<Sources />} />
            <Route path="/script" element={<Shadow />} />
            <Route path="/packs" element={<Packs />} />
            <Route path="/storage" element={<Storage />} />
            <Route path="/ai" element={<AiAccess />} />
            <Route path="*" element={<Overview />} />
          </Routes>
        ) : (
        <Routes>
          <Route path="/" element={<Overview />} />
          <Route path="/packs" element={<Packs />} />
          <Route path="/storage" element={<Storage />} />
          <Route path="/ai" element={<AiAccess />} />
          <Route path="/sources" element={<Sources />} />
          <Route path="/collect" element={<Collection />} />
          <Route path="/browse" element={<Browser />} />
          <Route path="/labels" element={<Labels />} />
          <Route path="/review" element={<Review />} />
          <Route path="/states" element={<States />} />
          <Route path="/train" element={<Training />} />
          <Route path="/results" element={<Results />} />
          <Route path="/script" element={<Shadow />} />
          <Route path="/scripts" element={<Scripts />} />
          <Route path="/library" element={<Library />} />
          <Route path="/tests" element={<Tests />} />
          <Route path="/schedules" element={<Schedules />} />
          <Route path="/panel-design" element={<PanelDesign />} />
        </Routes>
        )}
      </main>
    </div>
  )
}
