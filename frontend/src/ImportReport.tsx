import { useQuery, useQueryClient } from '@tanstack/react-query'
import type { UseQueryResult } from '@tanstack/react-query'
import { Link, Navigate, useParams, useSearchParams } from 'react-router-dom'
import { api, ApiError } from './api'
import type { Session } from './api'
import { measurement, recommendedStep, sourceUrl, stepNames, steps } from './report'
import type { ImportReport, Measurements, Step } from './report'
import Result from './Result'
import StageRunner from './StageRunner'

const metrics = [
  ['model_calls', 'Model calls', 'number'],
  ['tokens_in', 'Input tokens', 'number'],
  ['tokens_out', 'Output tokens', 'number'],
  ['cost_usd', 'Cost', 'usd'],
  ['wall_time_seconds', 'Wall time', 'seconds'],
] as const

function Numbers({ values }: { values: Measurements }) {
  return <dl className="mt-5 grid grid-cols-2 gap-x-4 gap-y-4 sm:grid-cols-3 xl:grid-cols-5">
    {metrics.map(([key, label, unit]) => <div key={key} className="min-w-0"><dt className="text-xs text-muted">{label}</dt><dd className="mt-1 break-words font-mono text-[13px]">{measurement(values[key], unit)}</dd></div>)}
  </dl>
}

function Status({ value }: { value: string | null }) {
  return <span className="rounded-control border border-line bg-wash px-2 py-1 text-xs">{value === 'needs_review' ? 'Needs review' : value?.replaceAll('_', ' ') || 'Not recorded'}</span>
}

export default function ImportReportPage({ session, preview = false }: { session: UseQueryResult<Session | null, Error>; preview?: boolean }) {
  const { id = '' } = useParams()
  const [params] = useSearchParams()
  const queryClient = useQueryClient()
  const report = useQuery({
    queryKey: ['report', session.data?.user.id, id, preview],
    enabled: preview || Boolean(session.data),
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
    <Link to="/app" className="text-blue underline">All imports</Link>
    <h1 className="page-title mt-6">Could not load this import</h1>
    <p role="alert" className="mt-4">{report.error instanceof ApiError ? report.error.message : 'Check your connection and try again.'}</p>
    <button className="button-secondary mt-6" onClick={() => { if (session.isError) void session.refetch(); else void report.refetch() }}>Try again</button>
  </main>
  if (!report.data) return <main className="page"><p role="status">Loading import report…</p></main>
  const data = report.data
  const baseline = data.baseline
  const investigation = data.investigation

  return <main className="page max-w-7xl">
    <Link to="/app" className="inline-flex min-h-6 items-center text-[13px] text-blue underline underline-offset-4">All imports</Link>
    {preview && <p role="note" className="mt-5 border border-line bg-blue-soft px-4 py-3 text-[13px]">Saved Swarm report · development preview. These are saved results; no live run is started.</p>}
    {report.isError && <div className="mt-5"><p role="alert">{report.error instanceof ApiError ? report.error.message : 'Could not refresh the report. Check your connection.'}</p><button className="button-secondary mt-3" onClick={() => void report.refetch()}>Try again</button></div>}
    <div className="mt-6 flex flex-wrap items-start justify-between gap-4">
      <div className="min-w-0 max-w-full"><h1 className="page-title break-words [overflow-wrap:anywhere]">{data.import.repository}</h1><p className="mt-3 break-words font-mono text-xs text-muted [overflow-wrap:anywhere]">{data.import.branch} · <span title={data.import.commit_sha}>{data.import.commit_sha.slice(0, 12)}</span></p></div>
      <button className="button-secondary" disabled={report.isFetching} onClick={() => void report.refetch()}>{report.isFetching ? 'Refreshing…' : 'Refresh report'}</button>
    </div>
    <div className="mt-8 grid items-start gap-8 lg:grid-cols-[180px_minmax(0,1fr)] lg:gap-10">
      <nav aria-label="Import steps" className="lg:sticky lg:top-6">
        <ol className="grid grid-cols-2 gap-1 sm:grid-cols-3 lg:grid-cols-1">
          {steps.map(value => <li key={value}><Link
            to={`?step=${value}`} aria-current={step === value ? 'step' : undefined}
            className={`flex min-h-11 items-center justify-between gap-3 rounded-control px-3 py-2 text-[13px] ${step === value ? 'bg-ink font-semibold text-surface' : 'hover:bg-blue-soft'}`}
          >{stepNames[value]}{value === next && <span className={`text-xs ${step === value ? 'text-surface' : 'text-muted'}`}>Next</span>}</Link></li>)}
        </ol>
        <p className="mt-4 text-[13px] text-muted">Viewing stored results. Selecting a step starts no work.</p>
      </nav>
      <div className="min-w-0">
        <aside aria-label="Recommended next step" className="mb-6 border-y border-line py-4">
          <p className="text-[13px] font-medium">{data.next.action === 'wait' ? 'Job running' : `Next: ${stepNames[next]}`}</p>
          {data.next.reason && <p className="mt-1 text-[13px] text-muted">{data.next.reason}</p>}
        </aside>
        <StageRunner key={`${data.import.import_id}:${session.data?.user.id || 'preview'}`} data={data} step={step} session={session.data} preview={preview} disabled={report.isFetching || report.isError} refresh={report.refetch} />
        <section aria-labelledby="step-heading" className="overflow-hidden rounded-card border border-line bg-surface">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line bg-wash px-6 py-4"><h2 id="step-heading" className="text-lg font-semibold">{stepNames[step]}</h2>{step === 'baseline' && baseline && <Status value={baseline.status} />}{step === 'findings' && investigation && <Status value={investigation.status} />}</div>
          {step === 'import' && <div className="p-6"><p>This report is tied to a fixed repository commit.</p><dl className="mt-5 space-y-4 text-[13px]"><div><dt className="text-muted">Repository</dt><dd className="mt-1 break-words [overflow-wrap:anywhere]">{data.import.repository}</dd></div><div><dt className="text-muted">Branch</dt><dd className="mt-1 break-words font-mono [overflow-wrap:anywhere]">{data.import.branch}</dd></div><div><dt className="text-muted">Commit</dt><dd className="mt-1 break-all font-mono">{data.import.commit_sha}</dd></div></dl></div>}
          {step === 'setup' && <div className="p-6"><h3 className="font-semibold">{data.adapter ? 'Execution adapter saved' : 'Setup is pending'}</h3><p className="mt-2 text-muted">{data.adapter ? 'An adapter has been stored for this import.' : 'Complete onboarding and confirm a task contract before measuring the agent.'}</p>{data.adapter && <dl className="mt-5 text-[13px]"><dt className="text-muted">Adapter hash</dt><dd className="mt-1 break-all font-mono">{data.adapter.sha256}</dd></dl>}</div>}
          {step === 'baseline' && (baseline ? <>
            <div className="border-b border-line p-6"><p className="text-[13px] text-muted">{baseline.model || 'Model not recorded'} · {measurement(baseline.repetitions)} repetitions</p><p className="mt-3 text-[13px]">{measurement(baseline.passed)} passed · {measurement(baseline.failed)} failed · {measurement(baseline.needs_review)} need review</p><h3 className="mt-5 font-semibold">Mean per full task set</h3><Numbers values={baseline.per_pass} /><p className="report-prose mt-4 text-muted">{baseline.note.replace(/^per_pass is /, 'This is ')}</p></div>
            {baseline.tasks.length ? <ul className="divide-y divide-line">{baseline.tasks.map((task, index) => <li key={task.task_id ?? index} className="p-6"><div className="flex flex-wrap items-start justify-between gap-3"><h3 className="min-w-0 break-words font-semibold [overflow-wrap:anywhere]">{task.name || `Task ${task.task_id ?? index + 1}`}</h3><Status value={task.status} /></div><Numbers values={task} />{task.reason && <p className="mt-4 break-words text-[13px] text-muted [overflow-wrap:anywhere]">{task.reason}</p>}</li>)}</ul> : <p className="p-6">No per-task measurements saved{baseline.status === 'running' ? ' yet. The baseline is running.' : '.'}</p>}
          </> : <p className="p-6">No baseline has been saved yet.</p>)}
          {step === 'findings' && (investigation ? <>
            <div className="border-b border-line p-6">{investigation.incomplete && <p className="mb-3 text-[13px] font-medium">Investigation incomplete. These findings were saved before it ended.</p>}{investigation.summary && <p className="report-prose">{investigation.summary}</p>}<p className="text-[13px] text-muted">{investigation.note}</p></div>
            {investigation.findings.length ? <ol className="divide-y divide-line">{investigation.findings.map(finding => <li key={finding.finding_id} className="p-6">
              <div className="flex flex-wrap items-center justify-between gap-3"><h3 className="font-semibold">Finding {finding.finding_id}</h3><span className="font-mono text-xs text-muted">Hypothesis</span></div>
              <div className="mt-3 flex flex-col gap-2">{finding.source.map((source, index) => {
                const url = sourceUrl(data.import.repository, data.import.commit_sha, source)
                const label = `${source.path}:${source.start_line}${source.end_line === source.start_line ? '' : `–${source.end_line}`}`
                return url ? <a key={index} href={url} target="_blank" rel="noopener noreferrer" className="inline-flex min-h-6 items-center break-all font-mono text-xs text-blue underline underline-offset-4">{label}</a> : <span key={index} className="break-all font-mono text-xs">{label}</span>
              })}</div>
              <p className="report-prose mt-5">{finding.waste || 'No finding description saved.'}</p>
              {finding.estimated_saving && <div className="mt-5 border-y border-line py-4"><p className="text-xs font-medium">Estimated saving over cited runs</p><dl className="mt-3 grid grid-cols-2 gap-4 sm:grid-cols-4">{([['Cost', measurement(finding.estimated_saving.cost_usd, 'usd')], ['Wall time', measurement(finding.estimated_saving.wall_time_seconds, 'seconds')], ['Tokens', measurement(finding.estimated_saving.tokens)], ['Model calls', measurement(finding.estimated_saving.model_calls)]]).map(([label, value]) => <div key={label}><dt className="text-xs text-muted">{label}</dt><dd className="mt-1 break-words font-mono text-[13px]">{value}</dd></div>)}</dl>{finding.saving_scope && <p className="report-prose mt-3 text-muted">{finding.saving_scope}</p>}</div>}
              <details className="mt-5 text-[13px]"><summary className="cursor-pointer py-2 font-medium">Proposed change and risk</summary><dl className="mt-3 space-y-4"><div><dt className="font-medium">Proposed change</dt><dd className="report-prose mt-1">{finding.proposed_change || 'Not recorded'}</dd></div><div><dt className="font-medium">Behavior risk</dt><dd className="report-prose mt-1">{finding.behaviour_risk || 'Not recorded'}</dd></div>{finding.estimated_saving?.method && <div><dt className="font-medium">Estimate method</dt><dd className="report-prose mt-1">{finding.estimated_saving.method}</dd></div>}</dl></details>
              <Link to={`?step=fix&finding=${encodeURIComponent(finding.finding_id)}`} className="button-secondary mt-4">Test this fix</Link>
            </li>)}</ol> : <p className="p-6">{investigation.nothing_worth_changing ? 'The investigation found nothing worth changing.' : 'No findings have been saved yet.'}</p>}
          </> : <p className="p-6">No investigation has been saved yet.</p>)}
          {step === 'result' && <Result attempts={data.optimizations} importId={data.import.import_id} preview={preview} />}
          {step === 'fix' && <div className="p-6">{data.optimizations.length ? <>
            <p className="text-[13px]">{data.optimizations.length} saved optimization attempt{data.optimizations.length === 1 ? '' : 's'}.</p>
            <ul className="mt-5 divide-y divide-line">{data.optimizations.map((attempt, index) => <li key={attempt.job_id} className="py-5 first:pt-0"><div className="flex flex-wrap items-center justify-between gap-3"><h3 className="font-semibold">Attempt {index + 1}</h3><Status value={attempt.decision||attempt.status} /></div>{attempt.incomplete && <p className="mt-3 text-[13px]">This attempt is incomplete.</p>}<p className="report-prose mt-3">{attempt.summary||'No summary saved.'}</p></li>)}</ul>
          </> : <p>No fix has been tested yet.</p>}</div>}
        </section>
        <details className="mt-6 text-[13px]"><summary className="cursor-pointer py-2 font-medium">What these results cover</summary><ul className="mt-3 list-disc space-y-2 pl-5 text-muted">{data.limits.map(limit => <li key={limit}>{limit}</li>)}</ul></details>
      </div>
    </div>
  </main>
}
