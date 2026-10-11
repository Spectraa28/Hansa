import { useQuery } from '@tanstack/react-query'
import { lazy, Suspense } from 'react'
import { Link, Route, Routes } from 'react-router-dom'
import { currentSession } from './api'
import Landing from './Landing'

const SignIn = lazy(() => import('./SignIn'))
const Imports = lazy(() => import('./Imports'))
const ImportReportPage = lazy(() => import('./ImportReport'))

export default function App() {
  const session = useQuery({ queryKey: ['session'], queryFn: ({ signal }) => currentSession(signal) })

  return (
    <>
      <header className="border-b border-line bg-paper/95">
        <nav aria-label="Main navigation" className="flex flex-wrap items-center gap-x-10 gap-y-3 px-5 py-4 sm:px-8">
          <Link to="/" aria-label="Hansa home" className="flex shrink-0 items-center gap-3">
            <img src="/brand/mark.svg" alt="" width="40" height="40" />
            <span className="font-display text-2xl leading-none font-[750] tracking-[-0.035em]">Hansa</span>
          </Link>
          <div className="order-3 flex w-full flex-wrap items-center gap-x-6 gap-y-2 font-mono text-xs sm:order-none sm:w-auto">
            <Link to="/#how-it-works" className="flex min-h-6 items-center hover:text-blue">How it works</Link>
            <Link to="/#real-run" className="flex min-h-6 items-center hover:text-blue">A real run</Link>
            <a href="https://github.com" className="flex min-h-6 items-center hover:text-blue">GitHub</a>
          </div>
          <Link to={session.data ? '/app' : '/sign-in'} className="button-secondary ml-auto">
            {session.data ? 'Imports' : 'Sign in'}
          </Link>
        </nav>
      </header>
      <Suspense fallback={<main className="page" aria-busy="true">Loading page…</main>}><Routes>
        <Route path="/" element={<Landing />} />
        <Route path="/sign-in" element={<SignIn session={session} />} />
        <Route path="/app" element={<Imports session={session} />} />
        <Route path="/app/imports/:id" element={<ImportReportPage session={session} />} />
        {import.meta.env.DEV && <Route path="/app/dev/swarm-report" element={<ImportReportPage session={session} preview />} />}
        <Route path="*" element={<main className="page"><h1 className="page-title">Page not found</h1><Link to="/" className="text-blue underline">Return home</Link></main>} />
      </Routes></Suspense>
    </>
  )
}
