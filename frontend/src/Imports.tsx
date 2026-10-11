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
        <div className="min-w-0 max-w-full"><h1 className="page-title">Your imports</h1><p className="mt-3 break-words text-muted [overflow-wrap:anywhere]">{session.data ? `Signed in as ${session.data.user.name}.` : 'Checking your session…'}</p></div>
        {session.data && <button className="button-secondary" disabled={imports.isFetching} onClick={() => void imports.refetch()}>{imports.isFetching ? 'Refreshing…' : 'Refresh imports'}</button>}
      </div>
      <section aria-label="Imported repositories" aria-busy={session.isPending || imports.isFetching} className="mt-8 overflow-hidden rounded-card border border-line bg-surface">
        {session.isError ? <div className="p-6" role="alert"><p>Could not check your session.</p><button className="button-secondary mt-4" onClick={() => void session.refetch()}>Try again</button></div>
          : session.isPending || imports.isPending ? <p role="status" className="p-6">Loading your imports…</p>
          : <>
            {imports.isError && <div role="alert" className="border-b border-line p-6"><p>{imports.error instanceof ApiError ? imports.error.message : 'Could not load imports. Check your connection and try again.'}</p><button className="button-secondary mt-4" onClick={() => void imports.refetch()}>Try again</button></div>}
            {imports.data && (imports.data.imports.length === 0 ? <div className="p-8"><h2 className="text-lg font-semibold">{page === 1 ? 'No repositories imported yet' : 'No imports on this page'}</h2><p className="mt-2 text-muted">{page === 1 ? 'Your imported repositories will appear here.' : 'Go back to the previous page to see earlier imports.'}</p></div>
              : <ul className="divide-y divide-line">
                {imports.data.imports.map(item => <li key={item.id} className="p-6 sm:px-8">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <h2 className="min-w-0 break-words text-lg font-semibold [overflow-wrap:anywhere]"><Link to={`/app/imports/${encodeURIComponent(item.id)}`} className="inline-block min-h-6 text-blue underline decoration-line underline-offset-4 hover:decoration-blue">{item.repository_name}</Link></h2>
                    <span className="rounded-control border border-line bg-wash px-3 py-1 font-mono text-xs">{item.status}</span>
                  </div>
                  <dl className="mt-4 grid grid-cols-1 gap-4 text-[13px] sm:grid-cols-3">
                    <div className="min-w-0"><dt className="text-muted">Branch</dt><dd className="mt-1 break-words font-mono [overflow-wrap:anywhere]">{item.branch}</dd></div>
                    <div><dt className="text-muted">Commit</dt><dd className="mt-1 font-mono" title={item.commit_sha}>{item.commit_sha.slice(0, 12)}</dd></div>
                    <div><dt className="text-muted">Imported</dt><dd className="mt-1"><time dateTime={new Date(item.created_at * 1000).toISOString()}>{new Date(item.created_at * 1000).toLocaleDateString()}</time></dd></div>
                  </dl>
                  {item.failure_reason && <p className="mt-4 break-words text-[13px] [overflow-wrap:anywhere]">{item.failure_reason}</p>}
                </li>)}
              </ul>)}
          </>}
        {session.data && <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line bg-wash px-6 py-4">
          <span className="font-mono text-xs">Page {page}</span>
          <div className="flex gap-2"><button className="button-secondary" disabled={page === 1 || imports.isFetching} onClick={() => setParams({ page: String(page - 1) })}>Previous</button><button className="button-secondary" disabled={!imports.data?.has_next || imports.isFetching || page === 10000} onClick={() => setParams({ page: String(page + 1) })}>Next</button></div>
        </div>}
      </section>
    </main>
  )
}
