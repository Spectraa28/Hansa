import { useEffect, useRef } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api, ApiError } from './api'
import { measurement } from './report'
import type { ActiveJob } from './report'

export type RunEvent = { id: number; kind: string; data: Record<string, unknown>; created_at: number }
type Usage = { calls?: number; estimated_cost_usd?: number | null; unknown_cost_calls?: number }
export type RunJob = { status: string; created_at: number; reason?: string; contract?: { limits: { max_spend_usd: number } }; result?: { decision?: string; reason?: string; summary?: string; max_spend_usd?: number; max_target_spend_usd?: number; agent_usage?: Usage; target_usage?: Usage } }
type Feed = { events: RunEvent[]; job: RunJob; done: boolean; updatedAt: number }
export const stageLabels = { onboarding: 'Onboarding', baseline: 'Baseline', investigation: 'Investigation', optimization: 'Fix testing' }

export function mergeEvents(previous: RunEvent[], incoming: RunEvent[]): RunEvent[] {
  return [...new Map([...previous, ...incoming].map(event => [event.id, event])).values()].sort((a, b) => a.id - b.id)
}

function summary(event: RunEvent): string {
  const data = event.data
  if (typeof data.text === 'string') return data.text
  if (event.kind === 'tool_error') return `${data.name || 'Tool'}: ${data.error || 'Could not complete'}`
  if (event.kind === 'run' || event.kind === 'task') return `Task ${data.task_id} · ${String(data.status || 'recorded').replaceAll('_', ' ')}`
  if (event.kind === 'experiment') return `Experiment ${data.experiment} · ${(data.comparison as { verdict?: string })?.verdict || 'measured'}`
  return String(data.summary || data.reason || data.warning || data.name || data.path || data.status || data.model || event.kind.replaceAll('_', ' '))
}

export default function RunFeed({ job, importId, ownerId, onFinished }: { job: ActiveJob; importId: string; ownerId: string; onFinished: (job: RunJob) => void }) {
  const queryClient = useQueryClient()
  const key = ['run-events', ownerId, importId, job.kind, job.job_id]
  const feed = useQuery({
    queryKey: key,
    queryFn: async ({ signal }): Promise<Feed> => {
      const previous = queryClient.getQueryData<Feed>(key)
      const cursor = previous?.events.at(-1)?.id || 0
      const path = `/github/imports/${encodeURIComponent(importId)}/${job.kind === 'baseline' ? 'baseline-jobs' : 'agent-jobs'}/${encodeURIComponent(job.job_id)}`
      try {
        const [page, status] = await Promise.all([api<{ events: RunEvent[] }>(`${path}/events?after=${cursor}`, { signal }), api<RunJob>(path, { signal })])
        const events = mergeEvents(previous?.events || [], page.events)
        const final = events.find(event => event.kind === 'finished')
        const current = final && status.status === 'running' && typeof final.data.status === 'string' ? { ...status, status: final.data.status } : status
        return { events, job: current, updatedAt: Date.now(), done: Boolean(final) || (status.status !== 'running' && page.events.length < 200) }
      } catch (error) {
        if (error instanceof ApiError && error.status === 401) queryClient.setQueryData(['session'], null)
        throw error
      }
    },
    retry: false,
    refetchInterval: query => query.state.data?.done || query.state.status === 'error' ? false : 1000,
    refetchOnWindowFocus: false,
  })
  const log = useRef<HTMLDivElement>(null)
  const following = useRef(true)
  useEffect(() => { if (feed.data?.done) onFinished(feed.data.job) }, [feed.data?.done, onFinished])
  useEffect(() => { if (following.current && log.current) log.current.scrollTop = log.current.scrollHeight }, [feed.data?.events.length])

  const events = feed.data?.events || []
  const runs = events.filter(event => event.kind === (job.kind === 'baseline' ? 'run' : 'smoke'))
  function recorded(key: string): number | null {
    if (!runs.length || runs.some(event => typeof event.data[key] !== 'number' || (key === 'cost_usd' && Number(event.data.unknown_cost_calls) > 0))) return null
    return runs.reduce((sum, event) => sum + Number(event.data[key]), 0)
  }
  const agent = feed.data?.job.result?.agent_usage
  const target = feed.data?.job.result?.target_usage
  const totals = job.kind === 'baseline'
    ? [['Completed-run calls', recorded('model_calls'), 'number'], ['Completed-run cost', recorded('cost_usd'), 'usd'], ['Recorded run time', recorded('wall_time_seconds'), 'seconds']] as const
    : [['Agent calls', agent?.calls, 'number'], ['Agent cost', agent?.unknown_cost_calls ? null : agent?.estimated_cost_usd, 'usd'], ['Target calls', target?.calls ?? recorded('model_calls'), 'number'], ['Target cost', target?.unknown_cost_calls ? null : target?.estimated_cost_usd ?? recorded('cost_usd'), 'usd']] as const
  const status = feed.data?.done ? feed.data.job.status === 'ready' ? 'completed' : feed.data.job.status.replaceAll('_', ' ') : 'running'

  return <section aria-label="Live run" className="mb-6 overflow-hidden rounded-card border border-line bg-surface">
    <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line bg-wash px-6 py-4"><h2 className="text-lg font-semibold">{stageLabels[job.kind]} · {status}</h2><p className="text-[13px] text-muted">{feed.data?.done ? 'Polling stopped' : feed.isError ? 'Feed paused' : 'Updates every second'}</p></div>
    {feed.data?.job.result?.decision && <p className="border-b border-line px-6 py-3 text-[13px]">Verdict: {feed.data.job.result.decision === 'reject' ? 'Fix rejected' : feed.data.job.result.decision === 'accept' ? 'Fix accepted' : feed.data.job.result.decision.replaceAll('_', ' ')}</p>}
    {feed.data?.done && (feed.data.job.reason || feed.data.job.result?.reason) && <p className="border-b border-line px-6 py-3 text-[13px]">{feed.data.job.reason || feed.data.job.result?.reason}</p>}
    {feed.isError && <div className="border-b border-line px-6 py-4"><p role="alert" className="text-[13px]">{feed.error instanceof ApiError ? feed.error.message : 'Live feed paused. Check your connection and try again.'}</p><button className="button-secondary mt-3" onClick={() => void feed.refetch()}>Resume feed</button></div>}
    <div className="grid lg:grid-cols-[minmax(0,1fr)_180px]">
      <div className="order-2 min-w-0 border-t border-line lg:order-1 lg:border-t-0 lg:border-r">
        <div ref={log} role="log" aria-label="Run events" aria-live="polite" aria-relevant="additions" tabIndex={0} className="max-h-96 overflow-y-auto" onScroll={event => { const node = event.currentTarget; following.current = node.scrollHeight - node.scrollTop - node.clientHeight < 32 }}>
          {events.length ? <ol className="divide-y divide-line">{events.map(event => <li key={event.id} className="run-event px-6 py-4"><div className="flex flex-wrap justify-between gap-2 text-xs text-muted"><span>{event.kind.replaceAll('_', ' ')}</span><time dateTime={new Date(event.created_at * 1000).toISOString()}>{new Date(event.created_at * 1000).toLocaleTimeString()}</time></div><p className="report-prose mt-2">{summary(event)}</p><details className="mt-2 text-xs"><summary className="cursor-pointer py-1">Event details</summary><pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap break-words font-mono [overflow-wrap:anywhere]">{JSON.stringify(event.data, null, 2)}</pre></details></li>)}</ol> : <p role="status" className="px-6 py-5 text-[13px]">{feed.isPending ? 'Connecting to the run…' : 'Waiting for the first event…'}</p>}
        </div>
        <button className="min-h-8 px-6 py-2 text-[13px] text-blue underline" onClick={() => { following.current = true; if (log.current) log.current.scrollTop = log.current.scrollHeight }}>Follow latest</button>
      </div>
      <aside aria-label="Running totals" className="order-1 p-6 lg:order-2"><h3 className="text-[13px] font-semibold">Recorded so far</h3><dl className="mt-4 grid grid-cols-2 gap-4 lg:grid-cols-1"><div><dt className="text-xs text-muted">This run's spend cap</dt><dd className="mt-1 font-mono text-[13px]">{measurement(feed.data?.job.result?.max_spend_usd ?? feed.data?.job.contract?.limits.max_spend_usd, 'usd')}</dd></div>{job.kind === 'optimization' && <div><dt className="text-xs text-muted">Candidate-run cap</dt><dd className="mt-1 font-mono text-[13px]">{measurement(feed.data?.job.result?.max_target_spend_usd, 'usd')}</dd></div>}{totals.map(([label, value, unit]) => <div key={label}><dt className="text-xs text-muted">{label}</dt><dd className="mt-1 break-words font-mono text-[13px]">{measurement(value, unit)}</dd></div>)}<div><dt className="text-xs text-muted">Elapsed time</dt><dd className="mt-1 font-mono text-[13px]">{measurement(feed.data ? Math.max(0, feed.data.updatedAt / 1000 - feed.data.job.created_at) : null, 'seconds')}</dd></div></dl><p className="mt-4 text-xs text-muted">Costs appear when reported. Missing values are unknown.</p></aside>
    </div>
  </section>
}
