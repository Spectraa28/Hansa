import { useQuery, useQueryClient } from '@tanstack/react-query'
import type { UseQueryResult } from '@tanstack/react-query'
import { Link, Navigate, useSearchParams } from 'react-router-dom'
import { api, ApiError } from './api'
import type { ImportsPage, Session } from './api'

export default function Imports({ session }: { session: UseQueryResult<Session | null, Error> }) {
  const [params, setParams] = useSearchParams()
  const requestedPage = Number(params.get('page') ?? 1)
  const page = Number.isInteger(requestedPage) && requestedPage >= 1 && requestedPage <= 10000 ? requestedPage : 1
  const queryClient = useQueryClient()
  const imports = useQuery({
    queryKey: ['imports', session.data?.user.id, page],
    enabled: Boolean(session.data),
    queryFn: async ({ signal }) => {
      try {
        return await api<ImportsPage>(`/github/imports?page=${page}`, { signal })
      } catch (error) {
        if (error instanceof ApiError && error.status === 401) queryClient.setQueryData(['session'], null)
        throw error
      }
    },
  })

  if (session.isSuccess && !session.data) return <Navigate to="/sign-in" replace />
  return (
    <main className="page">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="min-w-0 max-w-full"><h1 className="page-title">Your agents.</h1><p className="mt-3 break-words text-muted [overflow-wrap:anywhere]">{session.data ? `${session.data.user.name}, pick one to open its receipts.` : 'Checking your session…'}</p></div>
        {session.data && <div className="flex flex-wrap gap-3"><button className="button-secondary" disabled={imports.isFetching} onClick={() => void imports.refetch()}>{imports.isFetching ? 'Refreshing…' : 'Refresh'}</button><Link to="/app/new" className="button-primary">+ Import a repo</Link></div>}
      </div>
      <section aria-label="Imported repositories" aria-busy={session.isPending || imports.isFetching} className="slab mt-10 overflow-hidden">
        {session.isError ? <div className="p-6" role="alert"><p>Could not check your session.</p><button className="button-secondary mt-4" onClick={() => void session.refetch()}>Try again</button></div>
          : session.isPending || imports.isPending ? <p role="status" className="p-6">Loading your imports…</p>
          : <>
            {imports.isError && <div role="alert" className="border-b border-line p-6"><p>{imports.error instanceof ApiError ? imports.error.message : 'Could not load imports. Check your connection and try again.'}</p><button className="button-secondary mt-4" onClick={() => void imports.refetch()}>Try again</button></div>}
            {imports.data && (imports.data.imports.length === 0 ? <div className="px-8 py-16 text-center"><h2 className="font-display text-[34px] font-[780] tracking-[-.04em]">{page === 1 ? 'Nothing here yet.' : 'No imports on this page'}</h2><p className="mt-2 text-muted">{page === 1 ? 'Import an agent repo and Hansa will show you where it overspends.' : 'Go back to the previous page to see earlier imports.'}</p>{page === 1 && <Link to="/app/new" className="button-primary mt-6">Import your first repo</Link>}</div>
              : <ul className="divide-y-2 divide-ink">
                {imports.data.imports.map(item => <li key={item.id} className="group relative p-6 transition-colors hover:bg-waste sm:px-8">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <h2 className="min-w-0 font-display text-[28px] leading-none font-[780] tracking-[-.04em] [overflow-wrap:anywhere] sm:text-[36px]"><Link to={`/app/imports/${encodeURIComponent(item.id)}`} className="after:absolute after:inset-0">{item.repository_name} <span aria-hidden="true" className="inline-block transition-transform group-hover:translate-x-2">→</span></Link></h2>
                    <span className={`chip ${item.status === 'ready' ? 'chip-ok' : item.status === 'failed' ? 'bg-ink text-paper' : 'bg-surface'}`}>{item.status}</span>
                  </div>
                  <dl className="mt-4 flex flex-wrap gap-x-8 gap-y-2 font-mono text-[13px]">
                    <div className="min-w-0"><dt className="sr-only">Branch</dt><dd className="mt-1 break-words font-mono [overflow-wrap:anywhere]">{item.branch}{item.folder ? ` · /${item.folder}` : ''}</dd></div>
                    <div><dt className="sr-only">Commit</dt><dd className="mt-1 font-mono" title={item.commit_sha}>{item.commit_sha.slice(0, 12)}</dd></div>
                    <div><dt className="sr-only">Imported</dt><dd className="mt-1"><time dateTime={new Date(item.created_at * 1000).toISOString()}>{new Date(item.created_at * 1000).toLocaleDateString()}</time></dd></div>
                  </dl>
                  {item.failure_reason && <p className="mt-4 break-words text-[13px] [overflow-wrap:anywhere]">{item.failure_reason}</p>}
                </li>)}
              </ul>)}
          </>}
        {session.data && <div className="flex flex-wrap items-center justify-between gap-3 border-t-2 border-ink bg-wash px-6 py-4">
          <span className="font-mono text-xs">Page {page}</span>
          <div className="flex gap-2"><button className="button-secondary" disabled={page === 1 || imports.isFetching} onClick={() => setParams({ page: String(page - 1) })}>Previous</button><button className="button-secondary" disabled={!imports.data?.has_next || imports.isFetching || page === 10000} onClick={() => setParams({ page: String(page + 1) })}>Next</button></div>
        </div>}
      </section>
    </main>
  )
}
