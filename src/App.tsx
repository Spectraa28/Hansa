import { useQuery } from '@tanstack/react-query'
import { lazy, Suspense } from 'react'
import { Link, NavLink, Route, Routes, useLocation } from 'react-router-dom'
import { Menu } from 'lucide-react'
import { currentSession } from './api'
import Landing from './Landing'

const SignIn = lazy(() => import('./SignIn'))
const Imports = lazy(() => import('./Imports'))
const ImportReportPage = lazy(() => import('./ImportReport'))
const Profile = lazy(() => import('./Profile'))
const NewImport = lazy(() => import('./NewImport'))

const homeLinks = [['How it works', '/#how-it-works'], ['What it checks', '/#what-it-checks'], ['A real run', '/#real-run'], ['Live demo', '/demo']] as const
const appLinks = [['Your agents', '/app'], ['Import a repo', '/app/new'], ['Live demo', '/demo'], ['Home', '/']] as const
// Where the build history can be read (the Entire repository). Set VITE_BUILD_LOG_URL to show the link.
const buildLog: string | undefined = import.meta.env.VITE_BUILD_LOG_URL
const link = (active: boolean) => `underline-offset-[6px] decoration-waste decoration-[3px] hover:underline ${active ? 'underline' : ''}`

export default function App() {
  const session = useQuery({ queryKey: ['session'], queryFn: ({ signal }) => currentSession(signal) })
  const { pathname } = useLocation()
  const inApp = pathname.startsWith('/app')

  return (
    <>
      <header className="sticky top-0 z-40 border-b-[3px] border-ink bg-paper">
        <nav aria-label="Main navigation" className="flex h-[73px] items-center gap-4 px-[max(20px,calc((100vw-1280px)/2))] lg:gap-8">
          <Link to="/" aria-label="Hansa home" className="flex shrink-0 items-center gap-2.5">
            <img src="/brand/mark.svg" alt="" width="40" height="40" />
            <span className="font-display text-[28px] leading-none font-[800] tracking-[-0.045em]">Hansa</span>
          </Link>
          {/* The middle of the bar follows where you are: the page's sections at home, the product's places inside the app. */}
          <div className="hidden items-center gap-6 text-[15px] font-medium md:flex">
            {(inApp ? appLinks : homeLinks).map(([label, to]) => to.startsWith('/#')
              ? <a key={to} href={to} className={link(false)}>{label}</a>
              : <NavLink key={to} to={to} end className={({ isActive }) => link(isActive)}>{label}</NavLink>)}
            {buildLog && <a href={buildLog} target="_blank" rel="noopener noreferrer" className={link(false)}>Build log ↗</a>}
          </div>
          <div className="ml-auto flex items-center gap-3">
            {session.data ? <>
              <Link to={pathname === '/app/new' ? '/app' : '/app/new'} className="button-primary hidden sm:inline-flex">{pathname === '/app/new' ? 'Your agents' : '+ Import a repo'}</Link>
              <Link to="/app/profile" aria-label={`Profile: ${session.data.user.name}`} className="grid size-11 place-items-center overflow-hidden rounded-full border-2 border-ink bg-waste font-display text-[20px] font-[800] shadow-[3px_3px_0_var(--ink)] transition-transform hover:-translate-y-0.5">
                {session.data.user.avatar_url ? <img src={session.data.user.avatar_url} alt="" referrerPolicy="no-referrer" className="size-full object-cover" /> : session.data.user.name.slice(0, 1).toUpperCase()}
              </Link>
            </> : <>
              <Link to="/sign-in" className="hidden text-[15px] font-medium hover:underline sm:inline">Sign in</Link>
              <Link to="/app" className="button-primary">Import a repo</Link>
            </>}
            <details className="relative md:hidden"><summary aria-label="Menu" className="grid size-11 cursor-pointer list-none place-items-center rounded-control border-2 border-ink bg-surface [&::-webkit-details-marker]:hidden"><Menu size={20} aria-hidden="true" /></summary>
              <div className="absolute right-0 mt-2 grid w-56 gap-1 rounded-control border-2 border-ink bg-surface p-2 shadow-[var(--hard)]" onClick={event => (event.currentTarget.parentElement as HTMLDetailsElement).open = false}>
                {[...homeLinks, ...(session.data ? appLinks.slice(0, 2) : [['Sign in', '/sign-in'] as const])].map(([label, to]) => to.startsWith('/#')
                  ? <a key={to} href={to} className="rounded-[6px] px-3 py-2 font-medium hover:bg-waste">{label}</a>
                  : <Link key={to} to={to} className="rounded-[6px] px-3 py-2 font-medium hover:bg-waste">{label}</Link>)}
                {buildLog && <a href={buildLog} target="_blank" rel="noopener noreferrer" className="rounded-[6px] px-3 py-2 font-medium hover:bg-waste">Build log ↗</a>}
              </div></details>
          </div>
        </nav>
      </header>
      <Suspense fallback={<main className="page" aria-busy="true">Loading page…</main>}><Routes>
        <Route path="/" element={<Landing />} />
        <Route path="/sign-in" element={<SignIn session={session} />} />
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
