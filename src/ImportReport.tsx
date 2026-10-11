import { useQuery, useQueryClient } from '@tanstack/react-query'
import type { UseQueryResult } from '@tanstack/react-query'
import { Link, Navigate, useParams, useSearchParams } from 'react-router-dom'
import { api, ApiError } from './api'
import type { Session } from './api'
import { ArrowLeft, ArrowRight, Check, RefreshCw } from 'lucide-react'
import { measurement, recommendedStep, sourceUrl, stepNames, steps } from './report'
import type { Coverage, Finding, ImportReport, Step } from './report'
import { areas } from './areas'
import Result from './Result'
import StageRunner from './StageRunner'
import Setup from './Setup'
import type { ImportItem } from './api'

const tone: Record<string, [string, string]> = {
  passed: ['Passed', 'chip-ok'], needs_review: ['Checks passed', 'chip-ok'], failed: ['Failed', 'chip-waste'], completed: ['Done', 'chip-ok'],
  ready: ['Done', 'chip-ok'], running: ['Running', 'chip-waste'], reject: ['Rejected', 'chip-waste'], accept: ['Accepted', 'chip-ok'],
}
function Status({ value }: { value: string | null }) {
  const [label, style] = tone[value || ''] || [value?.replaceAll('_', ' ') || 'Not recorded', 'chip-quiet']
  return <span className={`chip ${style}`}>{label}</span>
}

function Tile({ label, value, small }: { label: string; value: string; small?: string }) {
  return <div className="slab min-w-0 px-5 pt-6 pb-5"><span className="slab-tab">{label}</span>
    <p className="big-number text-[40px] break-words sm:text-[56px]">{value}</p>{small && <p className="mt-2 font-mono text-[12px] text-muted">{small}</p>}</div>
}

function Cells({ count }: { count: number | null }) {
  return <span className="flex flex-wrap gap-1" aria-hidden="true">{Array.from({ length: Math.min(Math.round(count || 0), 40) }, (_, i) => <i key={i} className="size-4 rounded-[4px] bg-ink" />)}</span>
}

// The model writes a paragraph; the first sentence is the headline and the rest is detail.
function split(text: string | null): [string, string] {
  if (!text) return ['No description saved.', '']
  const cut = text.search(/[.!?](\s|$)/)
  if (cut >= 0 && cut <= 150) return [text.slice(0, cut + 1), text.slice(cut + 1).trim()]
  const stop = text.lastIndexOf(' ', 110)
  return [text.slice(0, stop > 0 ? stop : 110) + '…', text]
}

// Which area a finding belongs to: its own field once the backend sends one, otherwise the coverage record that cites it.
function areaOf(finding: Finding, coverage: Coverage[]) {
  const key = finding.category || coverage.find(item => item.finding_ids.includes(finding.finding_id))?.category
  return areas.find(area => area.key === key)
}

function Areas({ findings, coverage }: { findings: Finding[]; coverage: Coverage[] }) {
  return <section className="slab mb-10 p-6 pt-8 sm:p-8 sm:pt-9"><span className="slab-tab">where hansa looks</span>
    <ul className="grid gap-x-8 gap-y-5 sm:grid-cols-2 lg:grid-cols-4">{areas.map(area => {
      const record = coverage.find(item => item.category === area.key)
      const found = findings.filter(finding => areaOf(finding, coverage)?.key === area.key).length
      return <li key={area.key} className="min-w-0 border-t-2 border-ink pt-3">
        <div className="flex items-center justify-between gap-2"><h3 className="font-display text-[19px] font-[760] tracking-[-.02em]">{area.name}</h3>
          {found ? <span className="chip chip-waste">{found} found</span> : record ? <span className="chip chip-ok">clean</span> : <span className="chip chip-quiet border-dashed">not checked</span>}</div>
        <p className="mt-1.5 text-[13px] leading-snug text-muted">{record && !found ? record.observation : area.covers}</p></li>
    })}</ul>
    {coverage.length === 0 && <p className="mt-5 font-mono text-[12px] text-muted">This investigation ended before it reported area by area, so only its saved findings are shown below.</p>}
  </section>
}

function FindingCard({ finding, index, data, coverage }: { finding: Finding; index: number; data: ImportReport; coverage: Coverage[] }) {
  const area = areaOf(finding, coverage)
  const [title, rest] = split(finding.waste)
  const saving = finding.estimated_saving
  const extras = saving ? [saving.model_calls != null && `${measurement(saving.model_calls)} calls`, saving.wall_time_seconds != null && `${measurement(saving.wall_time_seconds, 'seconds')}`, saving.tokens != null && `${measurement(saving.tokens)} tokens`].filter(Boolean) : []
  return <li className="slab grid gap-6 p-6 pt-8 md:grid-cols-[minmax(0,1fr)_200px] md:p-8">
    <span className="slab-tab">leak {String(index + 1).padStart(2, '0')}{area ? ` · ${area.name}` : ''}</span>
    <div className="min-w-0">
      <h3 className="font-display text-[24px] leading-[1.1] font-[740] tracking-[-.03em] [overflow-wrap:anywhere] sm:text-[28px]">{title}</h3>
      <div className="mt-4 flex flex-wrap gap-2">{finding.source.map((source, i) => {
        const url = sourceUrl(data.import.repository, data.import.commit_sha, source)
        const label = `${source.path}:${source.start_line}${source.end_line === source.start_line ? '' : `–${source.end_line}`}`
        return url ? <a key={i} href={url} target="_blank" rel="noopener noreferrer" className="chip shrink bg-surface break-all whitespace-normal hover:bg-ink hover:text-paper">{label} ↗</a> : <span key={i} className="chip shrink break-all whitespace-normal">{label}</span>
      })}</div>
      {rest && <p className="report-prose mt-4 text-muted">{rest}</p>}
      <details className="mt-4 text-[14px]"><summary className="cursor-pointer py-1 font-semibold underline decoration-line decoration-2 underline-offset-4">The fix Hansa would try, and the risk</summary>
        <dl className="mt-3 space-y-4"><div><dt className="label">Proposed change</dt><dd className="report-prose mt-1">{finding.proposed_change || 'Not recorded'}</dd></div><div><dt className="label">Risk</dt><dd className="report-prose mt-1">{finding.behaviour_risk || 'Not recorded'}</dd></div>{saving?.method && <div><dt className="label">How the saving was estimated</dt><dd className="report-prose mt-1">{saving.method}</dd></div>}</dl></details>
    </div>
    <div className="flex flex-col items-start gap-1 border-t-2 border-ink pt-5 md:items-end md:border-t-0 md:border-l-2 md:pt-0 md:pl-6 md:text-right">
      <span className="label">could save</span>
      <p className="big-number text-[44px]">{saving?.cost_usd != null ? measurement(saving.cost_usd, 'usd') : '?'}</p>
      <p className="font-mono text-[12px] text-muted">{extras.length ? extras.join(' · ') : 'not priced yet'}</p>
      <p className="font-mono text-[12px] text-muted">estimate, until tested</p>
      <Link to={`?step=fix&finding=${encodeURIComponent(finding.finding_id)}`} className="button-primary mt-4 w-full md:mt-auto">Test this fix <ArrowRight size={16} aria-hidden="true" /></Link>
    </div>
  </li>
}

export default function ImportReportPage({ session, preview = false }: { session: UseQueryResult<Session | null, Error>; preview?: boolean }) {
  const { id = '' } = useParams()
  const [params] = useSearchParams()
  const queryClient = useQueryClient()
  // A fresh import is copied in the background; the report only exists once the copy is ready.
  const source = useQuery({ queryKey: ['import', session.data?.user.id, id], enabled: !preview && Boolean(session.data),
    queryFn: ({ signal }) => api<ImportItem>(`/github/imports/${encodeURIComponent(id)}`, { signal }),
    refetchInterval: query => ['queued', 'downloading'].includes(query.state.data?.status || '') ? 1500 : false })
  const report = useQuery({
    queryKey: ['report', session.data?.user.id, id, preview],
    enabled: preview || (Boolean(session.data) && source.data?.status === 'ready'),
    queryFn: async ({ signal }): Promise<ImportReport> => {
      if (preview && import.meta.env.DEV) return (await import('./data/swarm-report.json')).default
      try {
        return await api<ImportReport>(`/github/imports/${encodeURIComponent(id)}/report`, { signal })
      } catch (error) {
        if (error instanceof ApiError && error.status === 401) queryClient.setQueryData(['session'], null)
        throw error
      }
    },
  })

  if (!preview && session.isSuccess && !session.data) return <Navigate to="/sign-in" replace />
  const requestedStep = params.get('step')
  const next = report.data ? recommendedStep(report.data) : 'import'
  const step: Step = steps.includes(requestedStep as Step) ? requestedStep as Step : next

  if ((!preview && session.isError) || (report.isError && !report.data)) return <main className="page">
    <Link to="/app" className="font-semibold underline decoration-waste decoration-[3px] underline-offset-4">All imports</Link>
    <h1 className="page-title mt-6">Could not load this import</h1>
    <p role="alert" className="mt-4">{report.error instanceof ApiError ? report.error.message : 'Check your connection and try again.'}</p>
    <button className="button-secondary mt-6" onClick={() => { if (session.isError) void session.refetch(); else void report.refetch() }}>Try again</button>
  </main>
  if (source.isError) return <main className="page"><Link to="/app" className="font-semibold underline decoration-waste decoration-[3px] underline-offset-4">All imports</Link>
    <h1 className="page-title mt-6">Could not load this import</h1><p role="alert" className="mt-4">{source.error instanceof ApiError ? source.error.message : 'Check your connection and try again.'}</p></main>
  if (source.data && source.data.status !== 'ready') {
    const waiting = ['queued', 'downloading'].includes(source.data.status)
    return <main className="page max-w-3xl"><Link to="/app" className="font-mono text-[13px] font-medium hover:underline">← your agents</Link>
      <h1 className="page-title mt-2 [overflow-wrap:anywhere]">{source.data.repository_name}</h1>
      <section className="slab mt-10 p-8 pt-9"><span className="slab-tab">{source.data.status}</span>
        {waiting ? <><p className="flex items-center gap-3 font-display text-[28px] font-[760] tracking-[-.03em]"><span className="live-dot" /> Copying one commit…</p>
          <p className="mt-2 text-muted">Hansa is fetching {source.data.branch} at {source.data.commit_sha.slice(0, 7)}. This page moves on by itself.</p></>
          : <><p className="font-display text-[28px] font-[760] tracking-[-.03em]">This import didn't finish.</p><p className="mt-2 text-muted">{source.data.failure_reason || `Status: ${source.data.status}.`}</p>
            <Link to="/app/new" className="button-primary mt-6">Import again</Link></>}</section></main>
  }
  if (!report.data) return <main className="page"><p role="status">Loading import report…</p></main>
  const data = report.data
  const baseline = data.baseline
  const investigation = data.investigation

  const done: Record<Step, boolean> = { import: true, setup: Boolean(data.adapter), baseline: data.stages.baseline, findings: data.stages.investigated, fix: data.stages.optimized, result: data.stages.optimized }
  const nextLabel: Record<string, string> = { onboard: 'Set up the adapter', baseline: 'Measure the baseline', investigate: 'Hunt for leaks in the latest baseline', optimize: 'Test a fix', review: 'Review the result', wait: 'A job is running' }

  const runner = <StageRunner key={`${data.import.import_id}:${session.data?.user.id || 'preview'}`} data={data} step={step} session={session.data} preview={preview} disabled={report.isFetching || report.isError} refresh={report.refetch} />
  const adapter = <section className="slab mt-9 p-8"><span className="slab-tab">2 · adapter</span>
        <p className="font-display text-[28px] font-[740] tracking-[-.03em]">{data.adapter ? 'Hansa knows how to run this agent.' : 'Hansa needs to learn how to run this agent.'}</p>
        <p className="mt-2 max-w-[60ch] text-muted">{data.adapter ? 'Its own agent read the source and wrote a small adapter, then proved it with a real run.' : 'Start onboarding above. Hansa reads the source, writes a small adapter and proves it with one run.'}</p>
        {data.adapter && <p className="mt-5 font-mono text-[12px] break-all text-muted">adapter {data.adapter.sha256}</p>}</section>

  return <main className="page">
    <div className="flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0 max-w-full">
        <Link to="/app" className="inline-flex items-center gap-1.5 font-mono text-[13px] font-medium hover:underline"><ArrowLeft size={14} aria-hidden="true" /> imports</Link>
        <h1 className="page-title mt-2 [overflow-wrap:anywhere]">{data.import.repository}</h1>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <span className="chip bg-surface">{data.import.branch}</span><span className="chip bg-ink text-paper" title={data.import.commit_sha}>{data.import.commit_sha.slice(0, 7)}</span>
        <button className="button-secondary min-h-9 px-3" disabled={report.isFetching} aria-label="Refresh report" onClick={() => void report.refetch()}><RefreshCw size={16} className={report.isFetching ? 'animate-spin' : ''} aria-hidden="true" /></button>
      </div>
    </div>
    {preview && <p role="note" className="mt-4 font-mono text-[12px] text-muted">Saved Swarm run. Nothing starts from this preview.</p>}
    {report.isError && <div className="mt-5"><p role="alert">{report.error instanceof ApiError ? report.error.message : 'Could not refresh the report. Check your connection.'}</p><button className="button-secondary mt-3" onClick={() => void report.refetch()}>Try again</button></div>}

    <nav aria-label="Import steps" className="mt-7">
      <ol className="grid grid-cols-3 gap-2 md:grid-cols-6">{steps.map((value, index) => <li key={value}><Link to={`?step=${value}`} aria-current={step === value ? 'step' : undefined}
        className={`flex min-h-14 items-center gap-2.5 rounded-control border-2 border-ink px-3 text-[14px] font-semibold transition-transform hover:-translate-y-0.5 ${step === value ? 'bg-ink text-paper shadow-[4px_4px_0_var(--waste)]' : done[value] ? 'bg-surface' : 'border-dashed bg-transparent text-muted'}`}>
        <span className={`grid size-6 shrink-0 place-items-center rounded-full border-2 font-mono text-[11px] ${step === value ? 'border-paper' : done[value] ? 'border-ink bg-ok-soft' : 'border-current'}`}>{done[value] ? <Check size={13} strokeWidth={3} aria-label="done" /> : index + 1}</span>
        {stepNames[value]}{value === next && step !== value && <span className="live-dot ml-auto" aria-label="next step" />}</Link></li>)}</ol>
    </nav>

    {step !== next && <Link to={`?step=${next}`} className="mt-5 flex flex-wrap items-center justify-between gap-3 rounded-control border-2 border-ink bg-waste px-5 py-3 font-semibold shadow-[4px_4px_0_var(--ink)] transition-transform hover:-translate-y-0.5">
      <span><span className="font-mono text-[12px] uppercase tracking-[.08em]">next up · </span>{nextLabel[data.next.action] || stepNames[next]}</span><ArrowRight size={18} aria-hidden="true" /></Link>}

    <div className="mt-9 flex min-w-0 flex-col">
      {(step !== 'setup' || preview) && <div className={done[step] && !data.active ? 'order-last mt-9' : ''}>{runner}</div>}

      {step === 'import' && <section className="slab p-8"><span className="slab-tab">pinned source</span>
        <p className="font-display text-[28px] font-[740] tracking-[-.03em]">One commit, held still.</p><p className="mt-2 text-muted">Everything Hansa measures is tied to this exact commit. Nothing ran on import.</p>
        <dl className="mt-6 grid gap-5 sm:grid-cols-3"><div><dt className="label">Repository</dt><dd className="mt-1 font-mono [overflow-wrap:anywhere]">{data.import.repository}</dd></div><div><dt className="label">Branch</dt><dd className="mt-1 font-mono [overflow-wrap:anywhere]">{data.import.branch}</dd></div><div><dt className="label">Commit</dt><dd className="mt-1 font-mono break-all">{data.import.commit_sha}</dd></div></dl></section>}

      {step === 'setup' && (session.data && !preview
        ? <Setup importId={data.import.import_id} session={session.data} hasAdapter={Boolean(data.adapter)} onChanged={() => void report.refetch()}>{adapter}<div className="mt-9">{runner}</div></Setup>
        : adapter)}

      {step === 'baseline' && (baseline ? <section>
        <div className="grid gap-6 sm:grid-cols-3"><Tile label="calls per pass" value={measurement(baseline.per_pass.model_calls)} small={`${measurement(baseline.per_pass.tokens_in)} tokens in`} />
          <Tile label="cost per pass" value={measurement(baseline.per_pass.cost_usd && Number(baseline.per_pass.cost_usd.toFixed(4)), 'usd')} small="provider-reported" />
          <Tile label="time per pass" value={measurement(baseline.per_pass.wall_time_seconds && Math.round(baseline.per_pass.wall_time_seconds), 'seconds')} small={`${baseline.model || 'model not recorded'} · ${measurement(baseline.repetitions)} runs each`} /></div>
        <div className="slab mt-9"><span className="slab-tab">every task, every call</span>
          {baseline.tasks.length ? <ul className="divide-y-2 divide-line overflow-hidden rounded-[14px] pt-3">{baseline.tasks.map((task, index) => <li key={task.task_id ?? index} className="grid items-center gap-x-5 gap-y-2 px-6 py-4 md:grid-cols-[minmax(0,240px)_minmax(0,1fr)_auto_auto]">
            <div className="min-w-0"><p className="font-semibold [overflow-wrap:anywhere]">{task.name || `Task ${task.task_id ?? index + 1}`}</p>{task.status === 'failed' && task.reason && <p className="mt-1 text-[12px] text-muted [overflow-wrap:anywhere]">{task.reason.split(';').at(-1)}</p>}</div>
            <Cells count={task.model_calls} />
            <p className="font-mono text-[13px] tabular-nums">{measurement(task.model_calls)} calls · {measurement(task.cost_usd && Number(task.cost_usd.toFixed(4)), 'usd')} · {measurement(task.wall_time_seconds && Number(task.wall_time_seconds.toFixed(1)), 'seconds')}</p>
            <Status value={task.status} /></li>)}</ul> : <p className="p-6">No per-task measurements saved{baseline.status === 'running' ? ' yet. The baseline is running.' : '.'}</p>}</div>
        <p className="mt-5 font-mono text-[12px] text-muted">One square is one model call. "Checks passed" means the automatic checks passed; a person hasn't confirmed the answer.</p>
      </section> : <Empty title="No baseline yet." text="Run the baseline above to see what the agent costs today." />)}

      {step === 'findings' && (investigation ? <section>
        <div className="mb-8 flex flex-wrap items-end justify-between gap-3"><p className="font-display text-[34px] leading-none font-[780] tracking-[-.04em] sm:text-[48px]">{investigation.findings.length} leak{investigation.findings.length === 1 ? '' : 's'} found.</p>
          {investigation.incomplete && <span className="chip chip-quiet">investigation ended early · findings kept</span>}</div>
        <Areas findings={investigation.findings} coverage={investigation.coverage || []} />
        {investigation.findings.length ? <ol className="grid gap-9">{investigation.findings.map((finding, index) => <FindingCard key={finding.finding_id} finding={finding} index={index} data={data} coverage={investigation.coverage || []} />)}</ol>
          : <Empty title={investigation.nothing_worth_changing ? 'Nothing worth changing.' : 'No findings saved.'} text="Hansa only reports what it can point to in the source." />}
      </section> : <Empty title="No investigation yet." text="Start one above. Hansa lines up every call against the source and points at the waste." />)}

      {step === 'fix' && (data.optimizations.length ? <section className="grid gap-9">{data.optimizations.map((attempt, index) => <article key={attempt.job_id} className="slab p-6 pt-8 md:p-8"><span className="slab-tab">attempt {index + 1}</span>
        <div className="flex flex-wrap items-center justify-between gap-3"><h3 className="font-display text-[24px] font-[740] tracking-[-.03em]">{split(attempt.summary?.replace(/\*\*[^*]+\*\*\s*/g, '').replace(/`/g, '') || 'No summary saved.')[0]}</h3><Status value={attempt.decision || attempt.status} /></div>
        {attempt.incomplete && <p className="mt-3 text-[13px]">This attempt ended before finishing.</p>}
        <Link to={`?step=result&attempt=${attempt.job_id}`} className="button-secondary mt-5">See the numbers <ArrowRight size={16} aria-hidden="true" /></Link></article>)}</section>
        : <Empty title="No fix tested yet." text="Pick a finding and test it above." />)}

      {step === 'result' && <Result attempts={data.optimizations} importId={data.import.import_id} preview={preview} />}

      <details className="order-last mt-10 text-[13px]"><summary className="cursor-pointer py-2 font-mono text-muted">what these results cover</summary><ul className="mt-2 list-disc space-y-1.5 pl-5 text-muted">{data.limits.map(limit => <li key={limit}>{limit}</li>)}</ul></details>
    </div>
  </main>
}

function Empty({ title, text }: { title: string; text: string }) {
  return <section className="rounded-card border-2 border-dashed border-ink px-8 py-14 text-center"><p className="font-display text-[30px] font-[760] tracking-[-.03em]">{title}</p><p className="mx-auto mt-2 max-w-[46ch] text-muted">{text}</p></section>
}
