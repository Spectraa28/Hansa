import { useQuery } from '@tanstack/react-query'
import { lazy, Suspense } from 'react'
import { Link, Route, Routes } from 'react-router-dom'
import { currentSession } from './api'
import Landing from './Landing'

const SignIn = lazy(() => import('./SignIn'))
const Imports = lazy(() => import('./Imports'))
const ImportReportPage = lazy(() => import('./ImportReport'))
const Profile = lazy(() => import('./Profile'))
const NewImport = lazy(() => import('./NewImport'))

export default function App() {
  const session = useQuery({ queryKey: ['session'], queryFn: ({ signal }) => currentSession(signal) })

  return (
    <>
      <header className="sticky top-0 z-40 border-b-[3px] border-ink bg-paper">
        <nav aria-label="Main navigation" className="flex h-[73px] items-center gap-8 px-[max(20px,calc((100vw-1280px)/2))]">
          <Link to="/" aria-label="Hansa home" className="flex shrink-0 items-center gap-2.5">
            <img src="/brand/mark.svg" alt="" width="40" height="40" />
            <span className="font-display text-[28px] leading-none font-[800] tracking-[-0.045em]">Hansa</span>
          </Link>
          <div className="hidden items-center gap-7 text-[15px] font-medium md:flex">
            <Link to="/#how-it-works" className="hover:underline decoration-waste decoration-[3px] underline-offset-[6px]">How it works</Link>
            <Link to="/#real-run" className="hover:underline decoration-waste decoration-[3px] underline-offset-[6px]">A real run</Link>
          </div>
          {session.data ? <div className="ml-auto flex items-center gap-3">
            <Link to="/app" className="button-secondary hidden sm:inline-flex">Your agents</Link>
            <Link to="/app/profile" aria-label={`Profile: ${session.data.user.name}`} className="grid size-11 place-items-center overflow-hidden rounded-full border-2 border-ink bg-waste font-display text-[20px] font-[800] shadow-[3px_3px_0_var(--ink)] transition-transform hover:-translate-y-0.5">
              {session.data.user.avatar_url ? <img src={session.data.user.avatar_url} alt="" referrerPolicy="no-referrer" className="size-full object-cover" /> : session.data.user.name.slice(0, 1).toUpperCase()}
            </Link>
          </div> : <Link to="/sign-in" className="button-primary ml-auto">Sign in</Link>}
        </nav>
      </header>
      <Suspense fallback={<main className="page" aria-busy="true">Loading page…</main>}><Routes>
        <Route path="/" element={<Landing />} />
        <Route path="/sign-in" element={<SignIn session={session} />} />
        <Route path="/app" element={<Imports session={session} />} />
        <Route path="/app/new" element={<NewImport session={session} />} />
        <Route path="/app/profile" element={<Profile session={session} />} />
        <Route path="/app/imports/:id" element={<ImportReportPage session={session} />} />
        {import.meta.env.DEV && <Route path="/app/dev/swarm-report" element={<ImportReportPage session={session} preview />} />}
        <Route path="*" element={<main className="page"><h1 className="page-title">Page not found</h1><Link to="/" className="text-blue underline">Return home</Link></main>} />
      </Routes></Suspense>
    </>
  )
}
