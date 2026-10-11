import { useEffect, useRef } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api, ApiError } from './api'
import { measurement } from './report'
import type { ActiveJob } from './report'
import { advice } from './advice'

export type RunEvent = { id: number; kind: string; data: Record<string, unknown>; created_at: number }
type Usage = { calls?: number; estimated_cost_usd?: number | null; unknown_cost_calls?: number }
export type RunJob = { status: string; created_at: number; reason?: string; contract?: { limits: { max_spend_usd: number } }; result?: { decision?: string; reason?: string; summary?: string; max_spend_usd?: number; max_target_spend_usd?: number; agent_usage?: Usage; target_usage?: Usage } }
type Feed = { events: RunEvent[]; job: RunJob; done: boolean; updatedAt: number }
export const stageLabels = { onboarding: 'Onboarding', baseline: 'Baseline', investigation: 'Investigation', optimization: 'Fix testing' }

export function mergeEvents(previous: RunEvent[], incoming: RunEvent[]): RunEvent[] {
  return [...new Map([...previous, ...incoming].map(event => [event.id, event])).values()].sort((a, b) => a.id - b.id)
}

const tools: Record<string, (args: Record<string, unknown>) => string> = {
  read_file: args => `Reading ${args.path}`, list_files: args => `Looking through ${args.path || 'the repository'}`, search_code: args => `Searching the code for "${args.query}"`,
  write_adapter: () => 'Writing the adapter', run_smoke: () => 'Trying a real run in the sandbox', read_baseline: () => 'Reading the baseline numbers',
  read_run: args => `Reading run ${String(args.run_id || '').slice(0, 8)} call by call`, save_finding: () => 'Saving a finding', note: () => 'Making a note',
  edit_file: args => `Editing ${args.path}`, write_file: args => `Rewriting ${args.path}`, revert: () => 'Undoing the change', show_diff: () => 'Reviewing the change',
  run_candidate: () => 'Rerunning your tasks with the fix', measure_baseline: () => 'Rerunning the original to see how much it varies', finish: () => 'Wrapping up', block: () => 'Reporting a blocker',
}
const money = (value: unknown) => typeof value === 'number' ? ` · $${value.toFixed(4)}` : ''

// One readable line per event. `quiet` rows are bookkeeping and stay out of the headline.
export function describe(event: RunEvent): { text: string; quiet?: boolean; tone?: 'waste' | 'ok' } {
  const data = event.data, text = typeof data.text === 'string' ? data.text : ''
  switch (event.kind) {
    case 'started': return { text: 'Started' }
    case 'context': case 'compacted': case 'coverage': return { text: event.kind === 'coverage' ? 'Reported area by area' : 'Tidying its working memory', quiet: true }
    case 'note': return { text }
    case 'ledger': return { text: 'Wrote down what it has learned so far', quiet: true }
    case 'tool': return { text: (tools[String(data.name)] || (() => `Using ${data.name}`))((data.arguments || {}) as Record<string, unknown>) }
    case 'tool_error': return { text: `Hit a snag: ${data.error || 'a step could not complete'}`, tone: 'waste' }
    case 'finding': return { text: `Found a leak: ${String(data.waste || '').split(/(?<=[.!?])\s/)[0]}`, tone: 'waste' }
    case 'build': return { text: 'Built the sandbox image' }
    case 'experiment_started': return { text: 'Sandbox runs started', quiet: true }
    case 'edit': return { text: `Changed ${data.path || 'a file'}` }
    case 'revert': return { text: 'Undid the change' }
    case 'smoke': return { text: `Sandbox run finished: ${String(data.stop_reason || 'done').replaceAll('_', ' ')}${money(data.cost_usd)}`, tone: data.stop_reason === 'completed' ? 'ok' : undefined }
    case 'run': return { text: `Task ${data.task_id} ran · ${data.model_calls ?? '?'} calls${money(data.cost_usd)} · ${data.status === 'failed' ? 'failed its checks' : data.status === 'needs_review' ? 'checks passed' : String(data.status || 'recorded')}`, tone: data.status === 'failed' ? 'waste' : 'ok' }
    case 'task': return { text: `Task ${data.task_id} done: ${data.status === 'needs_review' ? 'checks passed' : String(data.status || 'recorded').replaceAll('_', ' ')}`, quiet: true }
    case 'experiment': { const verdict = (data.comparison as { verdict?: string })?.verdict
      return { text: `Measured attempt ${data.experiment}: ${verdict === 'improved' ? 'cheaper and still passing' : verdict === 'regressed' ? 'something broke' : 'no real change'}`, tone: verdict === 'improved' ? 'ok' : 'waste' } }
    case 'finished': return { text: data.status === 'ready' || data.status === 'completed' ? 'Finished' : `Stopped: ${data.reason || String(data.status || '').replaceAll('_', ' ')}`, tone: data.status === 'ready' || data.status === 'completed' ? 'ok' : 'waste' }
    default: return { text: text || String(data.summary || data.reason || data.warning || data.name || data.path || data.status || event.kind.replaceAll('_', ' ')) }
  }
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
  const now = [...events].reverse().map(describe).find(line => !line.quiet)?.text.split(/(?<=[.!?])\s/)[0].slice(0, 160)
  const status = feed.data?.done ? feed.data.job.status === 'ready' ? 'completed' : feed.data.job.status.replaceAll('_', ' ') : 'running'

  return <section aria-label="Live run" className="slab mb-9 overflow-hidden">
    <div className="flex flex-wrap items-center justify-between gap-3 border-b-2 border-ink bg-ink px-6 py-4 text-paper"><h2 className="flex items-center gap-3 font-display text-[22px] font-[760] tracking-[-.03em]">{!feed.data?.done && <span className="live-dot" />}{stageLabels[job.kind]} · {status}</h2><p className="font-mono text-[12px] text-paper/70">{feed.data?.done ? 'finished' : feed.isError ? 'feed paused' : 'live'}</p></div>
    {!feed.data?.done && now && <p role="status" className="border-b-2 border-ink bg-waste-soft px-6 py-4 font-display text-[20px] leading-snug font-[700] tracking-[-.02em] [overflow-wrap:anywhere]">{now}…</p>}
    {feed.data?.job.result?.decision && <p className="border-b border-line px-6 py-3 text-[13px]">Verdict: {feed.data.job.result.decision === 'reject' ? 'Fix rejected' : feed.data.job.result.decision === 'accept' ? 'Fix accepted' : feed.data.job.result.decision.replaceAll('_', ' ')}</p>}
    {feed.data?.done && (feed.data.job.reason || feed.data.job.result?.reason) && <p className="border-b border-line px-6 py-3 text-[13px]">{feed.data.job.reason || feed.data.job.result?.reason}{advice(feed.data.job.reason || feed.data.job.result?.reason || '') && <span className="mt-1 block font-medium">{advice(feed.data.job.reason || feed.data.job.result?.reason || '')}</span>}</p>}
    {feed.isError && <div className="border-b border-line px-6 py-4"><p role="alert" className="text-[13px]">{feed.error instanceof ApiError ? feed.error.message : 'Live feed paused. Check your connection and try again.'}</p><button className="button-secondary mt-3" onClick={() => void feed.refetch()}>Resume feed</button></div>}
    <div className="grid lg:grid-cols-[minmax(0,1fr)_180px]">
      <div className="order-2 min-w-0 border-t border-line lg:order-1 lg:border-t-0 lg:border-r">
        <div ref={log} role="log" aria-label="Run events" aria-live="polite" aria-relevant="additions" tabIndex={0} className="max-h-96 overflow-y-auto" onScroll={event => { const node = event.currentTarget; following.current = node.scrollHeight - node.scrollTop - node.clientHeight < 32 }}>
          {events.length ? <ol>{events.map(event => { const line = describe(event)
            return <li key={event.id} className={`run-event grid grid-cols-[64px_minmax(0,1fr)] gap-3 border-b border-line px-6 py-2.5 ${line.quiet ? 'text-muted' : ''}`}>
              <time className="pt-0.5 font-mono text-[12px] text-muted" dateTime={new Date(event.created_at * 1000).toISOString()}>{new Date(event.created_at * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false })}</time>
              <details className="min-w-0"><summary className="flex cursor-pointer list-none items-start gap-2 text-[14px] leading-snug [&::-webkit-details-marker]:hidden">
                {line.tone && <span aria-hidden="true" className={`mt-1.5 size-2 shrink-0 rounded-full ${line.tone === 'waste' ? 'bg-waste' : 'bg-ok'}`} />}<span className="line-clamp-2 min-w-0 [overflow-wrap:anywhere]">{line.text}</span></summary>
                {event.kind === 'note' ? <p className="report-prose mt-2 text-ink">{line.text}</p> : <pre className="mt-2 max-h-64 overflow-auto rounded-control bg-wash p-3 font-mono text-[12px] whitespace-pre-wrap [overflow-wrap:anywhere]">{JSON.stringify(event.data, null, 2)}</pre>}</details></li> })}</ol>
            : <p role="status" className="px-6 py-5 text-[14px]">{feed.isPending ? 'Connecting to the run…' : 'Waiting for the first event…'}</p>}
        </div>
        <button className="min-h-8 px-6 py-2 font-mono text-[12px] text-muted underline" onClick={() => { following.current = true; if (log.current) log.current.scrollTop = log.current.scrollHeight }}>jump to latest · click a line for its raw data</button>
      </div>
      <aside aria-label="Running totals" className="order-1 p-6 lg:order-2"><h3 className="label">so far</h3><dl className="mt-4 grid grid-cols-2 gap-4 lg:grid-cols-1"><div><dt className="text-xs text-muted">This run's spend cap</dt><dd className="mt-1 font-mono text-[13px]">{measurement(feed.data?.job.result?.max_spend_usd ?? feed.data?.job.contract?.limits.max_spend_usd, 'usd')}</dd></div>{job.kind === 'optimization' && <div><dt className="text-xs text-muted">Candidate-run cap</dt><dd className="mt-1 font-mono text-[13px]">{measurement(feed.data?.job.result?.max_target_spend_usd, 'usd')}</dd></div>}{totals.map(([label, value, unit]) => <div key={label}><dt className="text-xs text-muted">{label}</dt><dd className="mt-1 break-words font-mono text-[13px]">{measurement(value, unit)}</dd></div>)}<div><dt className="text-xs text-muted">Elapsed time</dt><dd className="mt-1 font-mono text-[13px]">{measurement(feed.data ? Math.max(0, feed.data.updatedAt / 1000 - feed.data.job.created_at) : null, 'seconds')}</dd></div></dl><p className="mt-4 text-xs text-muted">Costs appear when reported. Missing values are unknown.</p></aside>
    </div>
  </section>
}
