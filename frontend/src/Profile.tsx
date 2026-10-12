import { useState } from 'react'
import type { UseQueryResult } from '@tanstack/react-query'
import { useQueryClient } from '@tanstack/react-query'
import { Link, Navigate, useNavigate } from 'react-router-dom'
import { LogOut, Trash2 } from 'lucide-react'
import { ApiError } from './api'
import type { Session } from './api'

export default function Profile({ session }: { session: UseQueryResult<Session | null, Error> }) {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const [busy, setBusy] = useState<'out' | 'delete' | null>(null)
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState('')

  if (session.isSuccess && !session.data) return <Navigate to="/sign-in" replace />
  if (!session.data) return <main className="page max-w-3xl"><p role="status">{session.isError ? 'Could not load your profile.' : 'Loading your profile…'}</p></main>
  const { user, csrf_token } = session.data

  // Both actions end the session, so they share the request and the way out.
  async function leave(kind: 'out' | 'delete') {
    setBusy(kind); setError('')
    try {
      const response = await fetch(kind === 'out' ? '/auth/logout' : '/auth/me', { method: kind === 'out' ? 'POST' : 'DELETE', credentials: 'include', headers: { 'X-CSRF-Token': csrf_token } })
      if (!response.ok && response.status !== 401) {
        const body = await response.json().catch(() => null)
        throw new ApiError(response.status, typeof body?.detail === 'string' ? body.detail : 'That did not go through. Try again.')
      }
      // Update the session in place so the nav reacts now, then drop everything that belonged to the account.
      queryClient.setQueryData(['session'], null)
      queryClient.removeQueries({ predicate: query => query.queryKey[0] !== 'session' })
      navigate('/', { replace: true })
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'Could not reach Hansa. Check your connection and try again.')
      setBusy(null)
    }
  }

  return <main className="page max-w-3xl">
    <Link to="/app" className="back-link">← your agents</Link>
    <h1 className="page-title mt-2">Profile.</h1>

    <section className="slab mt-10 p-5 sm:p-8" aria-labelledby="profile-account"><h2 id="profile-account" className="slab-tab">Your account</h2>
      <div className="mt-4 flex flex-col gap-5 sm:flex-row sm:items-center">
        <div className="flex min-w-0 flex-1 items-start gap-4 sm:items-center">
          {user.avatar_url ? <img src={user.avatar_url} alt="" width="72" height="72" referrerPolicy="no-referrer" className="size-16 shrink-0 rounded-full border border-line object-cover sm:size-[72px]" />
            : <span aria-hidden="true" className="grid size-16 shrink-0 place-items-center rounded-full border border-line bg-blue-soft font-display text-[30px] font-medium text-blue sm:size-[72px]">{user.name.slice(0, 1).toUpperCase()}</span>}
          <div className="min-w-0 flex-1"><p className="font-display text-[24px] leading-tight font-medium [overflow-wrap:anywhere] sm:text-[30px]">{user.name}</p>
            <p className="mt-2 text-[14px] leading-relaxed text-muted [overflow-wrap:anywhere]">{user.email || 'no email on file'}</p></div>
        </div>
        <button className="button-secondary w-full shrink-0 sm:w-auto" disabled={busy !== null} onClick={() => void leave('out')}><LogOut size={16} aria-hidden="true" /> {busy === 'out' ? 'Signing out…' : 'Sign out'}</button>
      </div>
    </section>

    <section className="mt-10 rounded-card p-6 sm:p-8">
      <h2 className="font-display text-[26px] font-medium">Delete account</h2>
      <p className="mt-2 max-w-[58ch] text-muted">This removes your account, your GitHub connection, every imported repository copy, and all baselines, findings and results. It can't be undone.</p>
      <label htmlFor="confirm-delete" className="mt-5 block text-[15px] font-medium">Type <b className="tabular">delete</b> to confirm</label>
      <div className="mt-2 flex flex-col gap-3 sm:flex-row sm:items-start"><input id="confirm-delete" className="field min-w-0 sm:max-w-xs sm:flex-1" autoComplete="off" value={confirm} onChange={event => setConfirm(event.target.value)} />
        <button className="button-primary w-full shrink-0 enabled:bg-ink enabled:text-paper sm:w-auto" disabled={busy !== null || confirm.trim().toLowerCase() !== 'delete'} onClick={() => void leave('delete')}><Trash2 size={16} aria-hidden="true" /> {busy === 'delete' ? 'Deleting…' : 'Delete everything'}</button></div>
    </section>
    {error && <p role="alert" className="mt-5 font-medium [overflow-wrap:anywhere]">{error}</p>}
  </main>
}
