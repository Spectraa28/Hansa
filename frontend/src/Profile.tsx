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
    <Link to="/app" className="font-mono text-[13px] font-medium hover:underline">← your agents</Link>
    <h1 className="page-title mt-2">Profile.</h1>

    <section className="slab mt-10 flex flex-wrap items-center gap-5 p-6 pt-8 sm:p-8 sm:pt-9"><span className="slab-tab">you</span>
      {user.avatar_url ? <img src={user.avatar_url} alt="" width="72" height="72" referrerPolicy="no-referrer" className="size-[72px] rounded-full border-2 border-ink object-cover" />
        : <span aria-hidden="true" className="grid size-[72px] place-items-center rounded-full border-2 border-ink bg-waste font-display text-[34px] font-[800]">{user.name.slice(0, 1).toUpperCase()}</span>}
      <div className="min-w-0 flex-1"><p className="font-display text-[30px] leading-none font-[780] tracking-[-.04em] [overflow-wrap:anywhere]">{user.name}</p>
        <p className="mt-2 font-mono text-[13px] text-muted [overflow-wrap:anywhere]">{user.email || 'no email on file'}</p></div>
      <button className="button-secondary" disabled={busy !== null} onClick={() => void leave('out')}><LogOut size={16} aria-hidden="true" /> {busy === 'out' ? 'Signing out…' : 'Sign out'}</button>
    </section>

    <section className="mt-10 rounded-card border-2 border-dashed border-ink p-6 sm:p-8">
      <h2 className="font-display text-[26px] font-[780] tracking-[-.03em]">Delete account</h2>
      <p className="mt-2 max-w-[58ch] text-muted">This removes your account, your GitHub connection, every imported repository copy, and all baselines, findings and results. It can't be undone.</p>
      <label htmlFor="confirm-delete" className="mt-5 block text-[13px] font-medium">Type <b className="font-mono">delete</b> to confirm</label>
      <div className="mt-2 flex flex-wrap gap-3"><input id="confirm-delete" className="field max-w-[220px] font-mono" autoComplete="off" value={confirm} onChange={event => setConfirm(event.target.value)} />
        <button className="button-primary bg-ink text-paper" disabled={busy !== null || confirm.trim().toLowerCase() !== 'delete'} onClick={() => void leave('delete')}><Trash2 size={16} aria-hidden="true" /> {busy === 'delete' ? 'Deleting…' : 'Delete everything'}</button></div>
    </section>
    {error && <p role="alert" className="mt-5 font-medium">{error}</p>}
  </main>
}
