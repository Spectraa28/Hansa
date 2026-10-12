import { useEffect, useState } from 'react'
import type { CSSProperties, FormEvent } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import type { UseQueryResult } from '@tanstack/react-query'
import { Navigate, useNavigate, useSearchParams } from 'react-router-dom'
import { Braces, Cpu, Database, DollarSign, FlaskConical, Gauge, GitBranch, GitCompareArrows, Layers, MessagesSquare, Route, Search, ShieldCheck, Timer, Wrench, Zap } from 'lucide-react'
import { api, ApiError } from './api'
import type { Providers, Session } from './api'

// Codes the API sends back when Google or GitHub sign-in fails.
const providerErrors: Record<string, string> = {
  email_in_use: 'That email already has a Hansa account under a different sign-in. Use the one you signed up with (GitHub or Google).',
  cancelled: 'Sign-in was cancelled or expired. Try again.',
  invite_only: 'This Hansa server is invitation-only, and that account is not on its list. The recorded demo is open to everyone.',
  provider: 'Could not reach the sign-in provider. Try again in a moment.',
  identity: 'The provider did not return a usable account. Try again.',
}

// Everything Hansa looks at in an agent, drifting behind the page: [icon, left %, top %, size, tone, seconds, delay].
const drifting = [
  // Kept to the margins: above, below and beside the two columns, never under the words.
  [GitBranch, 4, 14, 26, 'blue', 9, 0], [Gauge, 12, 88, 30, 'ok', 11, 1.2], [FlaskConical, 3, 76, 24, 'blue', 10, 2.1], [Braces, 24, 7, 22, 'ink', 12, 0.6],
  [DollarSign, 38, 87, 26, 'ok', 9.5, 1.8], [Timer, 45, 9, 24, 'waste', 11.5, 0.3], [ShieldCheck, 55, 90, 28, 'ok', 10.5, 2.6], [GitCompareArrows, 64, 5, 26, 'blue', 12.5, 1.1],
  [Layers, 72, 91, 24, 'ink', 9, 0.9], [MessagesSquare, 80, 7, 26, 'blue', 11, 2.3], [Wrench, 95, 52, 24, 'waste', 10, 0.2], [Cpu, 93, 84, 28, 'ink', 12, 1.5],
  [Database, 95, 24, 22, 'ok', 9.5, 2.8], [Route, 26, 91, 22, 'waste', 11, 1.9], [Search, 2, 46, 22, 'ink', 10.5, 0.8], [Zap, 13, 5, 22, 'blue', 9, 2.0],
] as const
const promises = [
  [Gauge, 'Measures every model call', 'Counted, timed and priced on your own tasks.'],
  [Search, 'Finds what it wastes', 'Repeated context, extra hops, oversized tool lists.'],
  [FlaskConical, 'Tests each fix first', 'You only get changes where every answer still holds.'],
] as const
const GitHubMark = () => <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true" fill="currentColor"><path d="M12 .5a11.5 11.5 0 0 0-3.64 22.41c.58.1.79-.25.79-.56v-2c-3.2.7-3.88-1.36-3.88-1.36-.52-1.33-1.28-1.69-1.28-1.69-1.05-.71.08-.7.08-.7 1.16.08 1.77 1.19 1.77 1.19 1.03 1.77 2.7 1.26 3.36.96.1-.75.4-1.26.73-1.55-2.55-.29-5.24-1.28-5.24-5.68 0-1.26.45-2.28 1.19-3.09-.12-.29-.52-1.46.11-3.04 0 0 .97-.31 3.17 1.18a11 11 0 0 1 5.78 0c2.2-1.49 3.17-1.18 3.17-1.18.63 1.58.23 2.75.11 3.04.74.81 1.19 1.83 1.19 3.09 0 4.41-2.69 5.38-5.25 5.67.41.36.78 1.06.78 2.14v3.17c0 .31.21.67.8.56A11.5 11.5 0 0 0 12 .5Z" /></svg>
const GoogleMark = () => <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"><path fill="#4285F4" d="M23 12.27c0-.82-.07-1.6-.2-2.36H12v4.47h6.17a5.28 5.28 0 0 1-2.29 3.46v2.88h3.7C21.75 18.72 23 15.77 23 12.27Z" /><path fill="#34A853" d="M12 23.5c3.1 0 5.7-1.03 7.59-2.78l-3.7-2.88c-1.03.69-2.34 1.1-3.89 1.1-2.99 0-5.52-2.02-6.43-4.74H1.75v2.97A11.5 11.5 0 0 0 12 23.5Z" /><path fill="#FBBC05" d="M5.57 14.2a6.9 6.9 0 0 1 0-4.4V6.83H1.75a11.5 11.5 0 0 0 0 10.34l3.82-2.97Z" /><path fill="#EA4335" d="M12 5.06c1.69 0 3.2.58 4.39 1.72l3.28-3.28A11.5 11.5 0 0 0 1.75 6.83L5.57 9.8C6.48 7.08 9.01 5.06 12 5.06Z" /></svg>

export default function SignIn({ session }: { session: UseQueryResult<Session | null, Error> }) {
  const providers = useQuery({ queryKey: ['providers'], queryFn: ({ signal }) => api<Providers>('/auth/providers', { signal }) })
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const [submitting, setSubmitting] = useState(false)
  const [params] = useSearchParams()
  const provider = providerErrors[params.get('error') || '']
  const [error, setError] = useState('')
  // The three promises light up in turn, like the loop they describe.
  const [lit, setLit] = useState(0)
  useEffect(() => {
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return
    const timer = window.setInterval(() => setLit(current => (current + 1) % promises.length), 2200)
    return () => window.clearInterval(timer)
  }, [])

  async function signIn(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = event.currentTarget
    const fields = new FormData(form)
    setSubmitting(true)
    setError('')
    try {
      const result = await api<Session>('/auth/login', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: fields.get('email'), password: fields.get('password') }),
      })
      form.reset()
      queryClient.setQueryData(['session'], result)
      navigate('/app', { replace: true })
    } catch (error) {
      setError(error instanceof ApiError ? error.message : 'Could not sign in. Check your connection and try again.')
    } finally {
      setSubmitting(false)
    }
  }

  if (session.data) return <Navigate to="/app" replace />
  return (
    <main className="signin">
      <div className="signin-drift" aria-hidden="true">{drifting.map(([Icon, left, top, size, tone, seconds, delay], index) =>
        <span key={index} className={`is-${tone}`} style={{ left: `${left}%`, top: `${top}%`, '--t': `${seconds}s`, '--d': `${delay}s` } as CSSProperties}><Icon size={size} strokeWidth={1.6} /></span>)}</div>
      <div className="signin-pitch">
        <h1 className="page-title">Meet your AI engineer.</h1>
        <p className="mt-4 max-w-[30em] text-[18px] text-muted">Sign in, point Hansa at your agent's repository, and get tested fixes that make it cheaper and faster.</p>
        <ul className="mt-9 grid gap-2.5">{promises.map(([Icon, title, text], index) => <li key={title} data-lit={lit === index} className="signin-promise">
          <span><Icon size={20} aria-hidden="true" /></span><div><p className="font-semibold">{title}</p><p className="text-[14.5px] text-muted">{text}</p></div></li>)}</ul>
      </div>
      <section aria-label="Sign-in methods" className="signin-card"><h2 className="text-[22px] font-semibold tracking-tight">Sign in</h2><p className="mt-1 mb-6 text-[14.5px] text-muted">Hansa asks GitHub for read access only, and only to the repositories you pick.</p>
        {provider && <p role="alert" className="notice-problem mb-6 text-[14px] font-medium">{provider}</p>}
        {session.isPending || providers.isPending ? <p role="status">Checking sign-in methods…</p>
          : session.isError || providers.isError ? <div role="alert"><p>Could not load sign-in. Please try again.</p><button className="button-secondary mt-4" onClick={() => { void session.refetch(); void providers.refetch() }}>Try again</button></div>
          : providers.data && <>
            <div className="flex flex-col gap-3">
              {providers.data.github && <a href="/auth/github/login" className="button-primary min-h-14 text-[16px]"><GitHubMark /> Continue with GitHub</a>}
              {providers.data.google && <a href="/auth/google/login" className="button-secondary min-h-12 bg-surface"><GoogleMark /> Continue with Google</a>}
            </div>
            {providers.data.email && <form onSubmit={signIn} className={providers.data.github || providers.data.google ? 'signin-email mt-7 pt-6' : ''}>
              <label className="block text-[15px] font-medium" htmlFor="email">Email</label>
              <input className="field mt-2" id="email" name="email" type="email" autoComplete="username" maxLength={254} required />
              <label className="mt-4 block text-[15px] font-medium" htmlFor="password">Password</label>
              <input className="field mt-2" id="password" name="password" type="password" autoComplete="current-password" maxLength={128} required />
              {error && <p role="alert" className="mt-4 text-[15px]">{error}</p>}
              <button className="button-primary mt-6 w-full" disabled={submitting}>{submitting ? 'Signing in…' : 'Sign in with email'}</button>
            </form>}
            {!providers.data.github && !providers.data.google && !providers.data.email && <p>No sign-in methods are enabled. Contact the person running Hansa.</p>}
          </>}
      </section>
    </main>
  )
}
