import { useEffect, useRef } from 'react'
import type { ComponentType } from 'react'
import { BookOpen, Boxes, CircleAlert, CircleCheck, ClipboardList, FileSearch, FlaskConical, FolderSearch, Gauge, ListChecks, PenLine, Play, Search, Sparkles, StickyNote, Undo2 } from 'lucide-react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api, ApiError } from './api'
import { measurement } from './report'
import type { ActiveJob } from './report'
import { advice } from './advice'

export type RunEvent = { id: number; kind: string; data: Record<string, unknown>; created_at: number }
type Usage = { calls?: number; estimated_cost_usd?: number | null; unknown_cost_calls?: number }
export type RunJob = { status: string; created_at: number; reason?: string; repetitions?: number; contract?: { limits: { max_spend_usd: number }; tasks?: { name: string }[] }; result?: { decision?: string; reason?: string; summary?: string; max_spend_usd?: number; max_target_spend_usd?: number; agent_usage?: Usage; target_usage?: Usage } }
type Feed = { events: RunEvent[]; job: RunJob; done: boolean; updatedAt: number }
export const stageLabels = { onboarding: 'Onboarding', baseline: 'Baseline', investigation: 'Investigation', optimization: 'Fix testing' }

export function mergeEvents(previous: RunEvent[], incoming: RunEvent[]): RunEvent[] {
  return [...new Map([...previous, ...incoming].map(event => [event.id, event])).values()].sort((a, b) => a.id - b.id)
}

type TaskName = { task_id: string | null; name: string | null }
export function taskProgress(events: RunEvent[], kind: ActiveJob['kind'], info?: RunJob, names: TaskName[] = []) {
  if (kind !== 'baseline' && kind !== 'optimization') return []
  const experiment = events.filter(event => event.kind === 'experiment_started').at(-1)
  const results = events.filter(event => event.kind === (kind === 'baseline' ? 'run' : 'candidate_run') && !event.data.unchanged_agent && (kind === 'baseline' || experiment && event.id > experiment.id && event.data.experiment === experiment.data.experiment))
  const repetitions = kind === 'baseline' ? info?.repetitions || 1 : Number(experiment?.data.repetitions) || 1
  const definitions = kind === 'baseline'
    ? info?.contract?.tasks?.map((task, index) => ({ task_id: String(index + 1), name: task.name })) || []
    : (Array.isArray(experiment?.data.task_ids) ? experiment.data.task_ids : []).map(id => ({ task_id: String(id), name: names.find(task => task.task_id === String(id))?.name || null }))
  const tasks = new Map(definitions.map(task => [task.task_id, task]))
  for (const event of results) if (typeof event.data.task_id === 'string' && !tasks.has(event.data.task_id)) tasks.set(event.data.task_id, { task_id: event.data.task_id, name: typeof event.data.name === 'string' ? event.data.name : null })
  return [...tasks.values()].map(task => {
    const runs = [...new Map(results.filter(event => event.data.task_id === task.task_id).map(event => [event.data.repetition ?? event.id, event])).values()]
    const final = kind === 'baseline' ? events.filter(event => event.kind === 'task' && event.data.task_id === task.task_id).at(-1) : undefined
    const complete = Boolean(final) || runs.length >= repetitions
    const status = final ? String(final.data.status || 'not_recorded') : !complete ? null
      : runs.some(event => event.data.status === 'failed') ? 'failed'
      : runs.some(event => event.data.status === 'needs_review') ? 'needs_review'
      : runs.every(event => event.data.status === 'passed') ? 'passed' : 'not_recorded'
    return { ...task, runs: runs.length, repetitions, status }
  })
}

const outcome = (value: unknown) => value === 'needs_review' ? 'needs review' : value === 'passed' ? 'checks passed' : value === 'failed' ? 'checks failed' : String(value || 'not recorded').replaceAll('_', ' ')

const tools: Record<string, (args: Record<string, unknown>) => string> = {
  read_file: args => `Reading ${args.path}`, list_files: args => `Looking through ${args.path || 'the repository'}`, search_code: args => `Searching the code for "${args.query}"`,
  write_adapter: () => 'Writing the adapter', run_smoke: () => 'Trying a real run in the sandbox', read_baseline: () => 'Reading the baseline numbers',
  read_run: args => `Reading run ${String(args.run_id || '').slice(0, 8)} call by call`, save_finding: () => 'Saving a finding', note: () => 'Making a note',
  edit_file: args => `Editing ${args.path}`, write_file: args => `Rewriting ${args.path}`, revert: () => 'Undoing the change', show_diff: () => 'Reviewing the change',
  run_candidate: () => 'Preparing to rerun your tasks with the fix', measure_baseline: () => 'Rerunning the original to see how much it varies', finish: () => 'Wrapping up', block: () => 'Reporting a blocker',
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
    case 'experiment_started': { const count = (Array.isArray(data.task_ids) ? data.task_ids.length : 0) * Number(data.repetitions || 1)
      return { text: `Rerunning your tasks with the fix: ${count || 'several'} sandbox runs, about half a minute each` } }
    case 'candidate_run': return { text: `${typeof data.done === 'number' && typeof data.of === 'number' ? `Run ${data.done} of ${data.of} done` : 'Run completed'} · ${data.name || (data.task_id ? `task ${data.task_id}` : 'task not recorded')} · ${outcome(data.status)}${money(data.cost_usd)}`, tone: data.status === 'failed' ? 'waste' : data.status === 'passed' ? 'ok' : undefined }
    case 'edit': return { text: `Changed ${data.path || 'a file'}` }
    case 'revert': return { text: 'Undid the change' }
    case 'smoke': return { text: `Sandbox run finished: ${String(data.stop_reason || 'done').replaceAll('_', ' ')}${money(data.cost_usd)}`, tone: data.stop_reason === 'completed' ? 'ok' : undefined }
    case 'run': return { text: `Task ${data.task_id} ran · ${data.model_calls ?? '?'} calls${money(data.cost_usd)} · ${outcome(data.status)}`, tone: data.status === 'failed' ? 'waste' : data.status === 'passed' ? 'ok' : undefined }
    case 'task': return { text: `Task ${data.task_id} done: ${outcome(data.status)}`, quiet: true }
    case 'experiment': { const verdict = (data.comparison as { verdict?: string })?.verdict
      return { text: `Measured attempt ${data.experiment}: ${verdict === 'improved' ? 'cheaper and still passing' : verdict === 'regressed' ? 'something broke' : 'no real change'}`, tone: verdict === 'improved' ? 'ok' : 'waste' } }
    case 'finished': return { text: data.status === 'ready' || data.status === 'completed' ? 'Finished' : `Stopped: ${data.reason || String(data.status || '').replaceAll('_', ' ')}`, tone: data.status === 'ready' || data.status === 'completed' ? 'ok' : 'waste' }
    default: return { text: text || String(data.summary || data.reason || data.warning || data.name || data.path || data.status || event.kind.replaceAll('_', ' ')) }
  }
}

type Icon = ComponentType<{ size?: number; className?: string; 'aria-hidden'?: boolean | 'true' }>
// The stretch of work each kind of job goes through, so a run reads as a journey instead of a log.
const journeys: Record<ActiveJob['kind'], [string, Icon][]> = {
  onboarding: [['Read the code', BookOpen], ['Write the adapter', PenLine], ['Prove it in the sandbox', FlaskConical], ['Ready', CircleCheck]],
  baseline: [['Build the sandbox', Boxes], ['Run your tasks', Play], ['Record the numbers', Gauge]],
  investigation: [['Read the baseline', Gauge], ['Go through the runs', ListChecks], ['Check the code', FileSearch], ['Write up findings', ClipboardList]],
  optimization: [['Investigate', FileSearch], ['Edit a copy', PenLine], ['Rerun your tasks', FlaskConical], ['Verdict', CircleCheck]],
}
const reading = new Set(['read_file', 'list_files', 'search_code'])
/** Which stretch of the journey an event belongs to, or -1 when it says nothing about progress. */
export function stageOf(event: RunEvent, kind: ActiveJob['kind']): number {
  const tool = event.kind === 'tool' ? String(event.data.name) : ''
  if (kind === 'baseline') return event.kind === 'run' || event.kind === 'task' ? 1 : event.kind === 'finished' ? 2 : event.kind === 'started' || event.kind === 'build' ? 0 : -1
  if (event.kind === 'finished') return 3
  if (kind === 'onboarding') return reading.has(tool) ? 0 : tool === 'write_adapter' ? 1 : tool === 'run_smoke' || event.kind === 'build' || event.kind === 'smoke' ? 2 : -1
  if (kind === 'investigation') return tool === 'read_baseline' ? 0 : tool === 'read_run' ? 1 : reading.has(tool) ? 2 : event.kind === 'finding' || tool === 'save_finding' || event.kind === 'coverage' ? 3 : -1
  return reading.has(tool) || tool === 'read_baseline' || tool === 'read_run' ? 0 : event.kind === 'edit' || event.kind === 'revert' || tool === 'edit_file' || tool === 'write_file' || tool === 'revert' ? 1
    : event.kind === 'experiment_started' || event.kind === 'candidate_run' || tool === 'run_candidate' || tool === 'measure_baseline' ? 2 : event.kind === 'experiment' ? 3 : -1
}
const toolIcons: Record<string, Icon> = { read_file: BookOpen, list_files: FolderSearch, search_code: Search, write_adapter: PenLine, run_smoke: FlaskConical, read_baseline: Gauge, read_run: ListChecks,
  save_finding: ClipboardList, note: StickyNote, edit_file: PenLine, write_file: PenLine, revert: Undo2, show_diff: FileSearch, run_candidate: FlaskConical, measure_baseline: Gauge, finish: CircleCheck, block: CircleAlert }
const kindIcons: Record<string, Icon> = { started: Play, note: StickyNote, tool_error: CircleAlert, finding: Sparkles, build: Boxes, experiment_started: FlaskConical, candidate_run: Play, edit: PenLine, revert: Undo2,
  smoke: FlaskConical, run: Play, task: ListChecks, experiment: Gauge, finished: CircleCheck }
const iconOf = (event: RunEvent): Icon => (event.kind === 'tool' ? toolIcons[String(event.data.name)] : kindIcons[event.kind]) || StickyNote

export default function RunFeed({ job, importId, ownerId, onFinished, tasks = [] }: { job: ActiveJob; importId: string; ownerId: string; onFinished: (job: RunJob) => void; tasks?: TaskName[] }) {
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
  const track = useRef<HTMLOListElement>(null)
  const following = useRef(true)
  useEffect(() => { if (feed.data?.done) onFinished(feed.data.job) }, [feed.data?.done, onFinished])
  useEffect(() => { if (following.current && log.current) log.current.scrollTop = log.current.scrollHeight }, [feed.data?.events.length])

  const events = feed.data?.events || []
  const progress = taskProgress(events, job.kind, feed.data?.job, tasks)
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
  // Where the job is on its journey: the latest event that says so. A finished job that did not succeed stops where it was.
  const finishedWell = feed.data?.done && ['ready', 'completed'].includes(feed.data.job.status)
  const journey = journeys[job.kind]
  const at = finishedWell ? journey.length : Math.max(0, [...events].reverse().filter(event => event.kind !== 'finished').map(event => stageOf(event, job.kind)).find(stage => stage >= 0) ?? 0)
  const latest = [...events].reverse().find(event => !describe(event).quiet)
  const NowIcon = latest ? iconOf(latest) : Play
  const cap = feed.data?.job.result?.max_spend_usd ?? feed.data?.job.contract?.limits.max_spend_usd
  const spent = job.kind === 'baseline' ? recorded('cost_usd') : agent?.unknown_cost_calls ? null : agent?.estimated_cost_usd ?? null
  // On a narrow screen the journey scrolls sideways; keep the current stage in view without moving the page.
  useEffect(() => { const row = track.current, here = row?.querySelector<HTMLElement>('[data-stage=now]'); if (row && here) row.scrollTo({ left: here.offsetLeft - 24, behavior: 'smooth' }) }, [at])
  const status = feed.data?.done ? feed.data.job.status === 'ready' ? 'completed' : feed.data.job.status.replaceAll('_', ' ') : 'running'

  return <section aria-label="Live run" className="run-box slab mb-9 overflow-hidden" data-state={!feed.data?.done ? 'running' : finishedWell ? 'done' : 'stopped'}>
    <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line bg-wash px-6 py-4 text-ink"><h2 className="flex items-center gap-3 font-display text-[22px] font-medium">{!feed.data?.done && !feed.isError && <span className="live-dot" aria-hidden="true" />}{stageLabels[job.kind]} · {status}</h2><p className="tabular text-[14px] text-muted">{feed.data?.done ? 'finished' : feed.isError ? 'feed paused' : 'live'}</p></div>
    <ol ref={track} aria-label="Where this run is" className="run-journey">{journey.map(([label, StageIcon], index) => <li key={label} data-stage={index < at ? 'done' : index === at && !feed.data?.done ? 'now' : 'ahead'} aria-current={index === at && !feed.data?.done ? 'step' : undefined}>
      <span>{index < at ? <CircleCheck size={18} aria-hidden="true" /> : <StageIcon size={18} aria-hidden="true" />}</span><b>{label}</b></li>)}</ol>
    {!feed.data?.done && now && <p role="status" className="run-now flex items-start gap-3 border-b border-line bg-surface px-6 py-4 text-[20px] leading-snug font-semibold [overflow-wrap:anywhere]">{!feed.isError && <span className="live-dot mt-2 shrink-0" aria-hidden="true" />}<NowIcon size={22} className="mt-0.5 shrink-0 text-blue" aria-hidden="true" /><span key={latest?.id} className="run-now-text">{now}…</span></p>}
    {feed.data?.job.result?.decision && <p className="px-6 py-3 text-[15px]">Verdict: {feed.data.job.result.decision === 'reject' ? 'Fix rejected' : feed.data.job.result.decision === 'accept' ? 'Fix accepted' : feed.data.job.result.decision.replaceAll('_', ' ')}</p>}
    {feed.data?.done && (feed.data.job.reason || feed.data.job.result?.reason) && <p className="px-6 py-3 text-[15px]">{feed.data.job.reason || feed.data.job.result?.reason}{advice(feed.data.job.reason || feed.data.job.result?.reason || '') && <span className="mt-1 block font-medium">{advice(feed.data.job.reason || feed.data.job.result?.reason || '')}</span>}</p>}
    {feed.isError && <div className="px-6 py-4"><p role="alert" className="text-[15px]">{feed.error instanceof ApiError ? feed.error.message : 'Live feed paused. Check your connection and try again.'}</p><button className="button-secondary mt-3" onClick={() => void feed.refetch()}>Resume feed</button></div>}
    {progress.length > 0 && <section aria-label="Task progress" className=""><h3 className="label px-6 pt-4">Task results as they arrive</h3><ul className="">{progress.map(task => <li key={task.task_id} data-task-id={task.task_id} className="task-row flex flex-wrap items-center justify-between gap-2 px-6 py-3 text-[14px]">
      <span className="min-w-0 font-medium [overflow-wrap:anywhere]">{task.name || `Task ${task.task_id}`}</span><span className="flex flex-wrap items-center gap-2"><span className="text-[14px] text-muted">{task.runs} / {task.repetitions} runs recorded</span><span key={task.status || 'waiting'} className={`chip ${task.status ? 'task-resolved' : ''} ${task.status === 'failed' ? 'chip-waste' : task.status === 'passed' ? 'chip-ok' : 'chip-quiet'}`}>{task.status ? outcome(task.status) : feed.data?.done ? 'incomplete' : 'waiting for results'}</span></span>
    </li>)}</ul></section>}
    <div className="grid lg:grid-cols-[minmax(0,1fr)_180px]">
      <div className="order-2 min-w-0 lg:order-1">
        <div ref={log} role="log" aria-label="Run events" aria-live="polite" aria-relevant="additions" tabIndex={0} className="max-h-96 overflow-y-auto" onScroll={event => { const node = event.currentTarget; following.current = node.scrollHeight - node.scrollTop - node.clientHeight < 32 }}>
          {events.length ? <ol>{events.map(event => { const line = describe(event)
            return <li key={event.id} className={`run-event grid grid-cols-[64px_minmax(0,1fr)] gap-3 px-6 py-2.5 ${line.quiet ? 'text-muted' : ''}`}>
              <time className="pt-0.5 tabular text-[14px] text-muted" dateTime={new Date(event.created_at * 1000).toISOString()}>{new Date(event.created_at * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false })}</time>
              <details className="min-w-0"><summary className="flex cursor-pointer list-none items-start gap-2 text-[14px] leading-snug [&::-webkit-details-marker]:hidden">
                {(() => { const EventIcon = iconOf(event); return <EventIcon size={15} className={`mt-0.5 shrink-0 ${line.tone === 'waste' ? 'text-waste' : line.tone === 'ok' ? 'text-ok' : 'text-muted'}`} aria-hidden="true" /> })()}<span className="line-clamp-2 min-w-0 [overflow-wrap:anywhere]">{line.text}</span></summary>
                {event.kind === 'note' ? <p className="report-prose mt-2 text-ink">{line.text}</p> : <pre className="mt-2 max-h-64 overflow-auto rounded-control bg-wash p-3 tabular text-[14px] whitespace-pre-wrap [overflow-wrap:anywhere]">{JSON.stringify(event.data, null, 2)}</pre>}</details></li> })}</ol>
            : <p role="status" className="px-6 py-5 text-[14px]">{feed.isPending ? 'Connecting to the run…' : 'Waiting for the first event…'}</p>}
        </div>
        <button className="min-h-8 px-6 py-2 tabular text-[14px] text-muted underline" onClick={() => { following.current = true; if (log.current) log.current.scrollTop = log.current.scrollHeight }}>jump to latest · click a line for its raw data</button>
      </div>
      <aside aria-label="Running totals" className="order-1 p-6 lg:order-2"><h3 className="label">so far</h3><dl className="mt-4 grid grid-cols-2 gap-4 lg:grid-cols-1"><div><dt className="text-[14px] text-muted">This run's spend cap</dt><dd className="mt-1 tabular text-[15px]">{measurement(cap, 'usd')}</dd>{cap ? <dd className="mt-2"><span className="run-meter" role="img" aria-label={spent == null ? 'Spend so far is not known' : `${Math.round(Math.min(1, spent / cap) * 100)}% of the cap spent`}><span style={{ width: `${Math.min(100, (spent || 0) / cap * 100)}%` }} /></span><span className="mt-1 block tabular text-[12.5px] text-muted">{spent == null ? 'spend not known yet' : `${measurement(Number(spent.toFixed(4)), 'usd')} spent`}</span></dd> : null}</div>{job.kind === 'optimization' && <div><dt className="text-[14px] text-muted">Candidate-run cap</dt><dd className="mt-1 tabular text-[15px]">{measurement(feed.data?.job.result?.max_target_spend_usd, 'usd')}</dd></div>}{totals.map(([label, value, unit]) => <div key={label}><dt className="text-[14px] text-muted">{label}</dt><dd className="mt-1 break-words tabular text-[15px]">{measurement(value, unit)}</dd></div>)}<div><dt className="text-[14px] text-muted">Elapsed time</dt><dd className="mt-1 tabular text-[15px]">{measurement(feed.data ? Math.max(0, feed.data.updatedAt / 1000 - feed.data.job.created_at) : null, 'seconds')}</dd></div></dl><p className="mt-4 text-[14px] text-muted">Costs appear when reported. Missing values are unknown.</p></aside>
    </div>
  </section>
}
