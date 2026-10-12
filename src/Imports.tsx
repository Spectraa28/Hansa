import { DeleteAgent } from './ImportReport'
import type { ImportReport } from './report'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import type { UseQueryResult } from '@tanstack/react-query'
import { Link, Navigate, useSearchParams } from 'react-router-dom'
import { ArrowRight, FlaskConical, Gauge, GitBranch, Search } from 'lucide-react'
import { api, ApiError } from './api'
import type { ImportsPage, Session } from './api'

/** Where an agent stands, in one line: what it costs, what was found, and what to do next. */
function AgentStatus({ id, owner }: { id: string; owner: string }) {
  const report = useQuery({ queryKey: ['report', owner, id, false], staleTime: 30000, queryFn: ({ signal }) => api<ImportReport>(`/github/imports/${encodeURIComponent(id)}/report`, { signal }) })
  if (!report.data) return <p className="mt-4 tabular text-[14px] text-muted">{report.isError ? 'status unavailable' : 'reading status…'}</p>
  const data = report.data, latest = data.optimizations.at(-1), cost = data.baseline?.status === 'completed' ? data.baseline.per_pass.cost_usd : null
  const next: Record<string, string> = { onboard: 'next: set it up', baseline: 'next: measure the baseline', investigate: 'next: see what to fix', optimize: 'next: test a fix', review: 'all findings tested', wait: 'a job is running' }
  const facts = [cost != null && `$${cost.toFixed(4)} a pass`, data.investigation && `${data.investigation.findings.length} leak${data.investigation.findings.length === 1 ? '' : 's'} found`,
    latest && (latest.decision === 'accept' ? 'fix accepted' : latest.decision === 'reject' ? 'fix rejected' : 'fix tested')].filter(Boolean)
  return <p className="mt-4 flex flex-wrap items-center gap-2 text-[14px]">{data.active && <span className="live-dot" />}{facts.map(fact => <span key={fact as string} className="chip bg-surface">{fact}</span>)}
    <span className="chip chip-waste">{next[data.next.action] || data.next.action}</span></p>
}

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
        <div className="min-w-0 max-w-full"><h1 className="page-title">Your agents.</h1><p className="report-prose mt-4 text-body">{session.data ? 'Open an agent to continue setup, inspect its measurements, or review a tested change.' : 'Checking your session…'}</p></div>
        {session.data && <div className="flex flex-wrap gap-3"><button className="button-secondary" disabled={imports.isFetching} onClick={() => void imports.refetch()}>{imports.isFetching ? 'Refreshing…' : 'Refresh'}</button></div>}
      </div>
      <section aria-label="Imported repositories" aria-busy={session.isPending || imports.isFetching} className="slab mt-10 overflow-hidden">
        {session.isError ? <div className="p-6" role="alert"><p>Could not check your session.</p><button className="button-secondary mt-4" onClick={() => void session.refetch()}>Try again</button></div>
          : session.isPending || imports.isPending ? <p role="status" className="p-6">Loading your imports…</p>
          : <>
            {imports.isError && <div role="alert" className="p-6"><p>{imports.error instanceof ApiError ? imports.error.message : 'Could not load imports. Check your connection and try again.'}</p><button className="button-secondary mt-4" onClick={() => void imports.refetch()}>Try again</button></div>}
            {imports.data && (imports.data.imports.length === 0 ? (page === 1
              ? <div className="grid gap-10 p-6 sm:p-10 lg:grid-cols-[minmax(0,5fr)_minmax(0,6fr)] lg:items-center">
                <div><span className="grid size-12 place-items-center rounded-[12px] bg-blue-soft text-blue"><GitBranch size={24} aria-hidden="true" /></span>
                  <h2 className="mt-5 text-[28px] leading-tight font-semibold tracking-tight sm:text-[34px]">Import your first agent.</h2>
                  <p className="mt-3 max-w-[46ch] text-muted">Point Hansa at the repository your agent lives in. It copies one commit, read-only, and nothing runs until you start it.</p>
                  <div className="mt-6 flex flex-wrap gap-3"><Link to="/app/new" className="button-primary min-h-12 px-6">Import an agent <ArrowRight size={17} aria-hidden="true" /></Link><Link to="/demo" className="button-secondary min-h-12">See a finished run first</Link></div></div>
                <ol className="grid gap-3">{([[Gauge, 'Measure', 'Your own tasks run in a sandbox. Every model call is counted, timed and priced.'], [Search, 'Find', 'See what each request is made of, and the fixes worth making.'], [FlaskConical, 'Test', 'Each fix is rerun against your tasks before you get it.']] as const).map(([Icon, title, text], index) =>
                  <li key={title} className="flex items-start gap-4 rounded-control border border-line bg-paper p-4"><span className="grid size-10 shrink-0 place-items-center rounded-[10px] bg-wash text-muted"><Icon size={19} aria-hidden="true" /></span>
                    <div><p className="font-semibold"><span className="mr-2 font-mono text-[13px] text-muted">{index + 1}</span>{title}</p><p className="mt-0.5 text-[15px] text-muted">{text}</p></div></li>)}</ol>
              </div>
              : <div className="px-8 py-16 text-center"><h2 className="text-[26px] font-semibold">No imports on this page</h2><p className="mt-2 text-muted">Go back to the previous page to see earlier imports.</p></div>)
              : <ul className="">
                {imports.data.imports.map(item => <li key={item.id} className="group relative p-6 transition-colors hover:bg-blue-soft sm:px-8">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <h2 className="min-w-0 font-display text-[28px] leading-none font-medium [overflow-wrap:anywhere] sm:text-[36px]"><Link to={`/app/imports/${encodeURIComponent(item.id)}`} className="after:absolute after:inset-0">{item.repository_name} <span aria-hidden="true" className="inline-block group-hover:translate-x-2">→</span></Link></h2>
                    <span className="relative z-10 flex items-center gap-2"><span className={`chip ${item.status === 'ready' ? 'chip-ok' : item.status === 'failed' ? 'chip-waste' : 'bg-surface'}`}>{item.status}</span>{session.data && <DeleteAgent compact importId={item.id} name={item.repository_name} csrf={session.data.csrf_token} onDone={() => void imports.refetch()} />}</span>
                  </div>
                  <dl className="mt-4 flex flex-wrap gap-x-8 gap-y-2 tabular text-[15px]">
                    <div className="min-w-0"><dt className="sr-only">Branch</dt><dd className="mt-1 break-words tabular [overflow-wrap:anywhere]">{item.branch}{item.folder ? ` · /${item.folder}` : ''}</dd></div>
                    <div><dt className="sr-only">Commit</dt><dd className="mt-1 tabular" title={item.commit_sha}>{item.commit_sha.slice(0, 12)}</dd></div>
                    <div><dt className="sr-only">Imported</dt><dd className="mt-1"><time dateTime={new Date(item.created_at * 1000).toISOString()}>{new Date(item.created_at * 1000).toLocaleDateString()}</time></dd></div>
                  </dl>
                  {item.failure_reason && <p className="mt-4 break-words text-[15px] [overflow-wrap:anywhere]">{item.failure_reason}</p>}
                  {item.status === 'ready' && session.data && <AgentStatus id={item.id} owner={session.data.user.id} />}
                </li>)}
              </ul>)}
          </>}
        {session.data && <div className="flex flex-wrap items-center justify-between gap-3 bg-wash px-6 py-4">
          <span className="tabular text-[14px]">Page {page}</span>
          <div className="flex gap-2"><button className="button-secondary" disabled={page === 1 || imports.isFetching} onClick={() => setParams({ page: String(page - 1) })}>Previous</button><button className="button-secondary" disabled={!imports.data?.has_next || imports.isFetching || page === 10000} onClick={() => setParams({ page: String(page + 1) })}>Next</button></div>
        </div>}
      </section>
      {Boolean(imports.data?.imports.length) && <section className="workflow-guide mt-12 pt-10" aria-labelledby="agents-guide">
        <h2 id="agents-guide" className="font-display text-[26px] leading-tight font-semibold">How to work with your agents</h2>
        <p className="mt-3 max-w-[70ch] text-muted">Each agent has its own setup, measurements and experiment history. Open its repository name above to pick up where you left off.</p>
        <ol className="mt-8 grid gap-8 sm:grid-cols-2 xl:grid-cols-4">
          <li><h3 className="font-semibold">1. Open and check the status</h3><p className="mt-2 text-muted">Ready means the source copy is available. Queued or downloading means the import is still in progress. A failed import shows what went wrong.</p></li>
          <li><h3 className="font-semibold">2. Set up and measure</h3><p className="mt-2 text-muted">In Setup, review the model, allowed tools, tasks and correctness checks. Complete onboarding, confirm your tasks, then start a baseline to measure the original.</p></li>
          <li><h3 className="font-semibold">3. Investigate and test</h3><p className="mt-2 text-muted">Open Fixes for suggestions or start a deeper investigation. Choose a finding or describe a goal, then start Test to try a change against your tasks.</p></li>
          <li><h3 className="font-semibold">4. Review the result</h3><p className="mt-2 text-muted">Compare cost, time, calls and task outcomes in Result. Review the patch or coding-agent brief, including any rejection reason. Changes are not applied to your repository automatically.</p></li>
        </ol>
        <p className="guide-note mt-8 max-w-[75ch] rounded-control bg-wash p-5">Opening an agent does not start a run. Review the displayed spend limit before starting a stage. Passing automatic checks does not confirm the answer; some results still need human review.</p>
        <div className="mt-4 flex flex-wrap gap-3"><Link to="/app/new" className="button-secondary">Import another agent</Link><Link to="/demo" className="button-secondary">Explore the recorded demo</Link></div>
      </section>}
    </main>
  )
}
