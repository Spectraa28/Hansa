import { useState } from 'react'
import type { FormEvent } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import type { UseQueryResult } from '@tanstack/react-query'
import { Navigate, useNavigate } from 'react-router-dom'
import { api, ApiError } from './api'
import type { Providers, Session } from './api'

export default function SignIn({ session }: { session: UseQueryResult<Session | null, Error> }) {
  const providers = useQuery({ queryKey: ['providers'], queryFn: ({ signal }) => api<Providers>('/auth/providers', { signal }) })
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')

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
    <main className="page max-w-lg">
      <h1 className="page-title">Sign in to Hansa</h1>
      <p className="mt-3 text-muted">Continue to your imported repositories.</p>
      <section aria-label="Sign-in methods" className="mt-8 rounded-card border border-line bg-surface p-6 sm:p-8">
        {session.isPending || providers.isPending ? <p role="status">Checking sign-in methods…</p>
          : session.isError || providers.isError ? <div role="alert"><p>Could not load sign-in. Please try again.</p><button className="button-secondary mt-4" onClick={() => { void session.refetch(); void providers.refetch() }}>Try again</button></div>
          : providers.data && <>
            <div className="flex flex-col gap-3">
              {providers.data.github && <a href="/auth/github/login" className="button-primary">Continue with GitHub</a>}
              {providers.data.google && <a href="/auth/google/login" className="button-secondary">Continue with Google</a>}
            </div>
            {providers.data.email && <form onSubmit={signIn} className={providers.data.github || providers.data.google ? 'mt-6 border-t border-line pt-6' : ''}>
              <label className="block text-[13px] font-medium" htmlFor="email">Email</label>
              <input className="field mt-2" id="email" name="email" type="email" autoComplete="username" maxLength={254} required />
              <label className="mt-4 block text-[13px] font-medium" htmlFor="password">Password</label>
              <input className="field mt-2" id="password" name="password" type="password" autoComplete="current-password" maxLength={128} required />
              {error && <p role="alert" className="mt-4 text-[13px]">{error}</p>}
              <button className="button-primary mt-6 w-full" disabled={submitting}>{submitting ? 'Signing in…' : 'Sign in with email'}</button>
            </form>}
            {!providers.data.github && !providers.data.google && !providers.data.email && <p>No sign-in methods are enabled. Contact the person running Hansa.</p>}
          </>}
      </section>
    </main>
  )
}
