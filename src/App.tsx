import { useQuery } from '@tanstack/react-query'
import { lazy, Suspense } from 'react'
import { Link, NavLink, Route, Routes, useLocation } from 'react-router-dom'
import { FolderOpen, Menu, LogIn } from 'lucide-react'
import Backdrop from './Backdrop'
import ThemeToggle from './ThemeToggle'
import { toTop } from './smoothScroll'
import { currentSession } from './api'
import Landing from './Landing'

const SignIn = lazy(() => import('./SignIn'))
const Judges = lazy(() => import('./Judges'))
const Imports = lazy(() => import('./Imports'))
const ImportReportPage = lazy(() => import('./ImportReport'))
const Profile = lazy(() => import('./Profile'))
const NewImport = lazy(() => import('./NewImport'))

const homeLinks = [['Demo run', '/#real-run'], ['Measurements', '/#what-it-checks'], ['How it works', '/#how-it-works'], ['For judges', '/judges']] as const
const appLinks = [['Your agents', '/app'], ['Import an agent', '/app/new'], ['Recorded demo', '/demo'], ['Home', '/']] as const
// Where the build history can be read (the Entire repository). Set VITE_BUILD_LOG_URL to show the link.
const buildLog: string | undefined = import.meta.env.VITE_BUILD_LOG_URL
const link = (active: boolean) => `inline-flex min-h-11 items-center whitespace-nowrap transition-colors hover:text-paper ${active ? 'font-semibold text-paper' : 'text-paper/70'}`

export default function App() {
  const session = useQuery({ queryKey: ['session'], queryFn: ({ signal }) => currentSession(signal) })
  const { pathname } = useLocation()
  const inApp = pathname.startsWith('/app')

  return (
    <>
      {pathname !== '/sign-in' && <Backdrop />}
      <header className="sticky top-0 z-40 bg-ink text-paper">
        <nav aria-label="Main navigation" className="flex h-[71px] items-center gap-4 px-(--gutter) lg:gap-9">
          <Link to="/" aria-label="Hansa home" className="flex shrink-0 items-center gap-2.5" onClick={() => toTop(pathname === '/')}>
            <img src="/brand/mark.svg" alt="" width="38" height="38" />
            <span className="text-[21px] leading-none font-semibold tracking-tight">Hansa</span>
          </Link>
          {/* The middle of the bar follows where you are: the page's sections at home, the product's places inside the app. */}
          <div className="hidden items-center gap-7 text-[15px] lg:flex">
            {(inApp ? appLinks.slice(2) : homeLinks).map(([label, to]) => to.startsWith('/#')
              ? <a key={to} href={to} className={link(false)}>{label}</a>
              : <NavLink key={to} to={to} end className={({ isActive }) => link(isActive)}>{label}</NavLink>)}
            {buildLog && <a href={buildLog} target="_blank" rel="noopener noreferrer" className={link(false)}>Build log</a>}
          </div>
          <div className="ml-auto flex items-center gap-3">
            <ThemeToggle />
            {session.data ? <>
              <NavLink to="/app" end aria-label="Your agents" title="Your agents" className="button-secondary size-11 px-0 sm:w-auto sm:px-4"><FolderOpen size={18} aria-hidden="true" /><span className="hidden sm:inline">Your agents</span></NavLink>
              <Link to="/app/new" className="button-primary hidden whitespace-nowrap sm:inline-flex">Import an agent</Link>
              <Link to="/app/profile" aria-label={`Profile: ${session.data.user.name}`} className="grid size-11 place-items-center overflow-hidden rounded-full border border-paper/30 bg-surface text-[17px] font-semibold text-ink hover:border-paper">
                {session.data.user.avatar_url ? <img src={session.data.user.avatar_url} alt="" referrerPolicy="no-referrer" className="size-full object-cover" /> : session.data.user.name.slice(0, 1).toUpperCase()}
              </Link>
            </> : <>
              <Link to="/sign-in" className="nav-signin hidden sm:inline-flex"><LogIn size={16} aria-hidden="true" /> Sign in</Link>
              <Link to="/app/new" className="button-primary px-4 whitespace-nowrap sm:px-6"><span className="sm:hidden">Start</span><span className="hidden sm:inline">Analyze my agent</span></Link>
            </>}
            <details className="relative lg:hidden"><summary aria-label="Menu" className="grid size-11 cursor-pointer list-none place-items-center rounded-control border border-paper/30 text-paper hover:bg-paper/10 [&::-webkit-details-marker]:hidden"><Menu size={20} aria-hidden="true" /></summary>
              <div className="absolute right-0 mt-2 grid w-56 gap-1 rounded-control border border-line bg-surface p-2 text-ink shadow-[0_12px_32px_-12px_rgb(11_42_48/.3)]" onClick={event => (event.currentTarget.parentElement as HTMLDetailsElement).open = false}>
                {[...homeLinks, ...(session.data ? appLinks.slice(0, 2) : [['Sign in', '/sign-in'] as const])].map(([label, to]) => to.startsWith('/#')
                  ? <a key={to} href={to} className="flex min-h-11 items-center rounded-[6px] px-3 py-2 font-medium hover:bg-wash">{label}</a>
                  : <Link key={to} to={to} className="flex min-h-11 items-center rounded-[6px] px-3 py-2 font-medium hover:bg-wash">{label}</Link>)}
                {buildLog && <a href={buildLog} target="_blank" rel="noopener noreferrer" className="rounded-[6px] px-3 py-2 font-medium hover:bg-wash">Build log</a>}
              </div></details>
          </div>
        </nav>
      </header>
      <Suspense fallback={<main className="page" aria-busy="true">Loading page…</main>}><Routes>
        <Route path="/" element={<Landing />} />
        <Route path="/sign-in" element={<SignIn session={session} />} />
        <Route path="/judges" element={<Judges />} />
        <Route path="/app" element={<Imports session={session} />} />
        <Route path="/app/new" element={<NewImport session={session} />} />
        <Route path="/app/profile" element={<Profile session={session} />} />
        <Route path="/app/imports/:id" element={<ImportReportPage session={session} />} />
        <Route path="/demo" element={<ImportReportPage session={session} preview />} />
        <Route path="*" element={<main className="page"><h1 className="page-title">Page not found</h1><Link to="/" className="text-blue underline">Return home</Link></main>} />
      </Routes></Suspense>
    </>
  )
}
