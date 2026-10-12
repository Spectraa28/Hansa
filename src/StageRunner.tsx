import { useCallback, useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import { api, ApiError } from './api'
import type { Session } from './api'
import { measurement } from './report'
import type { ActiveJob, ImportReport, StageKind, Step } from './report'
import RunFeed, { stageLabels } from './RunFeed'
import { advice } from './advice'

type Contract = { status?: string; stale: boolean; missing_requirements: string[]; contract: { limits: { max_spend_usd: number } | null; tasks: unknown[] } | null }
const kinds: Partial<Record<Step, StageKind>> = { setup: 'onboarding', baseline: 'baseline', findings: 'investigation', fix: 'optimization' }
const buttons = { onboarding: 'Start onboarding', baseline: 'Run the baseline', investigation: 'Start the hunt', optimization: 'Test this fix' }
const copy: Record<StageKind, [string, string]> = {
  onboarding: ['Teach Hansa to run it.', 'Hansa reads the source, writes a small adapter and proves it with one real run in the sandbox.'],
  baseline: ['Measure it.', 'Every task runs in the sandbox. Each model call is counted, timed and priced.'],
  investigation: ['Hunt for leaks.', 'Hansa lines every call up against the source and goes through all eight areas, from prompt structure to wasted calls.'],
  optimization: ['Test a fix.', 'Hansa changes a private copy, reruns your tasks and keeps the fix only if it is cheaper and nothing breaks.'],
}

function StageForm({ kind, data, session, preview, busy, disabled, onStarted, refresh }: { kind: StageKind; data: ImportReport; session?: Session | null; preview: boolean; busy: boolean; disabled: boolean; onStarted: (job: ActiveJob) => void; refresh: () => Promise<unknown> }) {
  const [params] = useSearchParams()
  const queryClient = useQueryClient()
  const [cap, setCap] = useState('0.50')
  const [targetCap, setTargetCap] = useState('0.50')
  const [repetitions, setRepetitions] = useState('1')
  const [finding, setFinding] = useState(data.investigation?.job_id ? params.get('finding') || data.investigation.findings[0]?.finding_id || '' : '')
  const [goal, setGoal] = useState('')
  const [pending, setPending] = useState(false)
  const [uncertain, setUncertain] = useState(false)
  const [error, setError] = useState('')
  const submitting = useRef(false)
  const base = `/github/imports/${encodeURIComponent(data.import.import_id)}`
  const contract = useQuery({ queryKey: ['run-contract', session?.user.id, data.import.import_id], enabled: kind === 'baseline' && !preview && Boolean(session), queryFn: async ({ signal }) => {
    try { return await api<Contract>(`${base}/contract`, { signal }) }
    catch (error) { if (error instanceof ApiError && error.status === 401) queryClient.setQueryData(['session'], null); throw error }
  } })
  const contractReady = contract.data?.status === 'confirmed' && !contract.data.stale && !contract.data.missing_requirements.length && contract.data.contract?.limits != null
  const prerequisite = kind === 'baseline' ? !data.adapter ? 'Run onboarding first to save an execution adapter.' : !contractReady ? 'A current confirmed task contract is required. Its spend limit is shown here before launch.' : ''
    : (kind === 'investigation' || kind === 'optimization') && data.baseline?.status !== 'completed' ? 'A completed baseline is required first.' : ''
  const locked = preview || !session?.csrf_token || busy || disabled || pending || uncertain || Boolean(prerequisite) || (kind === 'baseline' && (contract.isFetching || contract.isError))

  async function start(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (locked || submitting.current) return
    const amount = Number(cap), target = Number(targetCap)
    if (kind !== 'baseline' && (!Number.isFinite(amount) || amount <= 0 || amount > 1.5)) { setError('Set the stage spend cap above $0 and at most $1.50.'); return }
    if (kind === 'optimization' && (!Number.isFinite(target) || target <= 0 || target > 3)) { setError('Set the candidate-run cap above $0 and at most $3.00.'); return }
    if (kind === 'optimization' && !finding && (goal.trim().length < 10 || goal.trim().length > 2000)) { setError('Choose a finding or describe a goal in 10 to 2000 characters.'); return }
    const body = kind === 'baseline' ? { repetitions: Number(repetitions) } : kind === 'optimization'
      ? { max_spend_usd: amount, max_target_spend_usd: target, ...(finding && data.investigation?.job_id ? { investigation_job_id: data.investigation.job_id, finding_id: finding } : { goal: goal.trim() }) }
      : { max_spend_usd: amount, ...(kind === 'investigation' && data.baseline?.baseline_id ? { baseline_id: data.baseline.baseline_id } : {}) }
    submitting.current = true; setPending(true); setError('')
    try {
      const result = await api<{ job_id?: string; baseline_id?: string }>(`${base}/${kind}`, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': session!.csrf_token }, body: JSON.stringify(body) })
      const jobId = result.job_id || result.baseline_id
      if (!jobId) throw new Error('Start response missing job ID')
      onStarted({ kind, job_id: jobId })
      void refresh()
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) queryClient.setQueryData(['session'], null)
      if (!(error instanceof ApiError) || error.status >= 500) {
        setUncertain(true); setError('Start was not confirmed. Check run status before trying again; the job may already be running.')
      } else { setError(error.message); void refresh() }
    } finally { submitting.current = false; setPending(false) }
  }

  async function checkStatus() {
    setPending(true)
    try {
      const report = await api<ImportReport>(`${base}/report`)
      if (report.active) onStarted(report.active)
      setUncertain(false); setError(report.active ? '' : 'No running job is reported. Review the saved results before starting again.')
      void refresh()
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) queryClient.setQueryData(['session'], null)
      setError('Could not check run status. Try checking again before starting another job.')
    } finally { setPending(false) }
  }

  const disabledFields = busy || pending || preview
  const [title, pitch] = copy[kind]
  const tasks = contract.data?.contract?.tasks.length
  const terms = kind === 'baseline'
    ? [tasks != null && `${tasks} task${tasks === 1 ? '' : 's'}`, `${repetitions} run${repetitions === '1' ? '' : 's'} each`, `stops at ${measurement(contract.data?.contract?.limits?.max_spend_usd, 'usd')}`]
    : [`stops at ${measurement(kind === 'optimization' ? Number(cap) + Number(targetCap) : Number(cap), 'usd')}`, kind === 'investigation' ? 'reads only, runs nothing' : 'runs in the sandbox']
  return <section aria-label="Start a stage" className="slab mb-9 p-6 pt-8 md:p-8">
    <span className="slab-tab">{stageLabels[kind]}</span><h2 className="font-display text-[32px] leading-none font-medium">{title}</h2>
    <p className="mt-3 max-w-[60ch] text-[15px] text-muted">{pitch}</p>
    <form onSubmit={event => void start(event)} className="mt-5">
      {kind === 'optimization' && <>
        <label htmlFor="run-finding" className="block text-[15px] font-medium">What to fix</label><select id="run-finding" className="field mt-2" value={finding} disabled={disabledFields} onChange={event => setFinding(event.target.value)}>{data.investigation?.job_id && data.investigation.findings.map((item, index) => <option key={item.finding_id} value={item.finding_id}>Leak {String(index + 1).padStart(2, '0')} · {item.waste?.slice(0, 90)}</option>)}<option value="">Something else (describe it)</option></select>
        {!finding && <><label htmlFor="run-goal" className="mt-4 block text-[15px] font-medium">Describe the change to try</label><textarea id="run-goal" className="field mt-2 min-h-24" minLength={10} maxLength={2000} required value={goal} disabled={disabledFields} onChange={event => setGoal(event.target.value)} /></>}
      </>}
      {error && <div role="alert" className="notice-problem mt-4 max-w-[65ch] text-[14px]"><p className="font-semibold">{error}</p>{advice(error) && <p className="mt-1">{advice(error)}</p>}</div>}
      {!preview && prerequisite && <p className="mt-4 rounded-control px-4 py-3 text-[14px]">{prerequisite}</p>}
      <div className="mt-5 flex flex-wrap items-center gap-x-5 gap-y-3">
        {uncertain ? <button type="button" disabled={pending} className="button-secondary" onClick={() => void checkStatus()}>Check run status</button> : <button className="button-primary min-h-12 px-7 text-[16px]" disabled={locked}>{pending ? 'Starting…' : buttons[kind]}</button>}
        <p className="tabular text-[15px] text-muted">{terms.filter(Boolean).join(' · ')}</p>
      </div>
      <details className="mt-5 text-[15px]"><summary className="cursor-pointer tabular text-muted underline decoration-line decoration-2 underline-offset-4">change options</summary>
        <div className="mt-4 grid gap-4 sm:grid-cols-2">
          {kind === 'baseline' ? <div><label htmlFor="run-repetitions" className="block font-medium">Runs per task</label><select id="run-repetitions" className="field mt-2" value={repetitions} disabled={disabledFields} onChange={event => setRepetitions(event.target.value)}>{[1, 2, 3, 4, 5].map(value => <option key={value} value={value}>{value}{value === 1 ? ' (quick)' : value === 2 ? ' (shows variation)' : ''}</option>)}</select>
            <p className="mt-2 text-muted">The spend cap comes from your tasks in Setup.</p></div>
          : <div><label htmlFor="run-cap" className="block font-medium">{kind === 'optimization' ? 'Cap for Hansa\'s own thinking (USD)' : 'Spend cap (USD)'}</label><input id="run-cap" className="field mt-2 tabular" type="number" min="0.01" max="1.5" step="0.01" required value={cap} disabled={disabledFields} onChange={event => setCap(event.target.value)} /></div>}
          {kind === 'optimization' && <div><label htmlFor="target-cap" className="block font-medium">Cap for rerunning your tasks (USD)</label><input id="target-cap" className="field mt-2 tabular" type="number" min="0.01" max="3" step="0.01" required value={targetCap} disabled={disabledFields} onChange={event => setTargetCap(event.target.value)} /></div>}
        </div>
        <p className="mt-3 max-w-[65ch] text-muted">A cap stops new work once recorded cost reaches it. A call already in flight can finish past it.</p>
        {contract.isError && <div className="mt-3"><p role="alert">Could not load the spend cap.</p><button type="button" className="button-secondary mt-2" onClick={() => void contract.refetch()}>Reload</button></div>}
      </details>
    </form>
  </section>
}

export default function StageRunner({ data, step, session, preview, disabled, refresh }: { data: ImportReport; step: Step; session?: Session | null; preview: boolean; disabled: boolean; refresh: () => Promise<unknown> }) {
  const [job, setJob] = useState<ActiveJob | null>(data.active || null)
  const [finished, setFinished] = useState(false)
  useEffect(() => { if (data.active && data.active.job_id !== job?.job_id) { setJob(data.active); setFinished(false) } }, [data.active?.job_id, job?.job_id])
  const onStarted = (job: ActiveJob) => { setJob(job); setFinished(false) }
  const onFinished = useCallback(() => { setFinished(true); void refresh() }, [refresh])
  const kind = kinds[step]
  const busy = Boolean(job) && !finished
  return <>
    {busy && <p role="status" className="mb-4 flex items-center gap-2 tabular text-[15px]"><span className="live-dot" /> A job is running. Live feed below.</p>}
    {kind && !busy && !preview && <StageForm key={`${kind}:${step === 'fix' ? data.investigation?.job_id || '' : ''}`} kind={kind} data={data} session={session} preview={preview} busy={busy} disabled={disabled} onStarted={onStarted} refresh={refresh} />}
    {job && session && !preview && <RunFeed key={job.job_id} job={job} importId={data.import.import_id} ownerId={session.user.id} onFinished={onFinished} tasks={data.baseline?.tasks} />}
  </>
}
