import { useCallback, useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import { api, ApiError } from './api'
import type { Session } from './api'
import { measurement } from './report'
import type { ActiveJob, ImportReport, StageKind, Step } from './report'
import RunFeed, { stageLabels } from './RunFeed'

type Contract = { status?: string; stale: boolean; missing_requirements: string[]; contract: { limits: { max_spend_usd: number } | null; tasks: unknown[] } | null }
const kinds: Partial<Record<Step, StageKind>> = { setup: 'onboarding', baseline: 'baseline', findings: 'investigation', fix: 'optimization' }
const buttons = { onboarding: 'Start onboarding', baseline: 'Start baseline', investigation: 'Start investigation', optimization: 'Test fix' }

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

  return <section aria-label="Start a stage" className="mb-6 rounded-card border border-line bg-surface p-6">
    <h2 className="text-lg font-semibold">{stageLabels[kind]}</h2>
    <p className="mt-2 text-[13px] text-muted">Review the spend cap before starting. This launches model calls{kind === 'investigation' ? '.' : ' and isolated task runs.'}</p>
    <form onSubmit={event => void start(event)} className="mt-5">
      {kind === 'baseline' ? <>
        <p className="text-[13px]">Confirmed contract spend cap: <strong className="font-mono">{measurement(contract.data?.contract?.limits?.max_spend_usd, 'usd')}</strong></p>
        <p className="mt-1 text-[13px] text-muted">Applies across the entire baseline, including all repetitions. Change it in the task contract, then confirm that contract again.</p>
        <label htmlFor="run-repetitions" className="mt-4 block text-[13px] font-medium">Repetitions</label><select id="run-repetitions" className="field mt-2 max-w-xs text-[13px]" value={repetitions} disabled={busy || pending || preview} onChange={event => setRepetitions(event.target.value)}>{[1, 2, 3, 4, 5].map(value => <option key={value} value={value}>{value}</option>)}</select>
        {contract.isError && <div className="mt-4"><p role="alert" className="text-[13px]">Could not load the confirmed spend cap.</p><button type="button" className="button-secondary mt-3" onClick={() => void contract.refetch()}>Reload spend cap</button></div>}
      </> : <div className="grid gap-4 sm:grid-cols-2">
        <div><label htmlFor="run-cap" className="block text-[13px] font-medium">{kind === 'optimization' ? 'Optimizer spend cap (USD)' : 'Stage spend cap (USD)'}</label><input id="run-cap" className="field mt-2 font-mono text-[13px]" type="number" min="0.01" max="1.5" step="0.01" required value={cap} disabled={busy || pending || preview} onChange={event => setCap(event.target.value)} /></div>
        {kind === 'optimization' && <div><label htmlFor="target-cap" className="block text-[13px] font-medium">Candidate-run spend cap (USD)</label><input id="target-cap" className="field mt-2 font-mono text-[13px]" type="number" min="0.01" max="3" step="0.01" required value={targetCap} disabled={busy || pending || preview} onChange={event => setTargetCap(event.target.value)} /></div>}
      </div>}
      {kind === 'optimization' && <>
        <p className="mt-3 text-[13px]">Combined spend caps: <strong className="font-mono">{measurement(Number(cap) + Number(targetCap), 'usd')}</strong></p>
        <label htmlFor="run-finding" className="mt-4 block text-[13px] font-medium">Finding to test</label><select id="run-finding" className="field mt-2 text-[13px]" value={finding} disabled={busy || pending || preview} onChange={event => setFinding(event.target.value)}><option value="">Custom goal</option>{data.investigation?.job_id && data.investigation.findings.map(item => <option key={item.finding_id} value={item.finding_id}>Finding {item.finding_id} · {item.waste?.slice(0, 100)}</option>)}</select>
        {!finding && <><label htmlFor="run-goal" className="mt-4 block text-[13px] font-medium">Optimization goal</label><textarea id="run-goal" className="field mt-2 min-h-24 text-[13px]" minLength={10} maxLength={2000} required value={goal} disabled={busy || pending || preview} onChange={event => setGoal(event.target.value)} /></>}
      </>}
      <p className="report-prose mt-4 text-muted">Spend caps stop further work against recorded costs. A call or batch already running can take spend above the cap. Missing cost is reported as unknown.</p>
      {preview && <p className="mt-4 text-[13px]">Starting stages is disabled in this saved preview.</p>}
      {busy && <p role="status" className="mt-4 text-[13px]">A job is already running. Reattached to its live feed.</p>}
      {!preview && prerequisite && <p className="mt-4 text-[13px]">{prerequisite}</p>}
      {error && <p role="alert" className="report-prose mt-4">{error}</p>}
      {uncertain ? <button type="button" disabled={pending} className="button-secondary mt-5" onClick={() => void checkStatus()}>Check run status</button> : <button className="button-primary mt-5" disabled={locked}>{pending ? 'Starting…' : buttons[kind]}</button>}
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
    {busy && <p role="status" className="mb-4 text-[13px]">A job is already running. Reattached to its live feed.</p>}
    {kind && !busy && <StageForm key={`${kind}:${step === 'fix' ? data.investigation?.job_id || '' : ''}`} kind={kind} data={data} session={session} preview={preview} busy={busy} disabled={disabled} onStarted={onStarted} refresh={refresh} />}
    {job && session && !preview && <RunFeed key={job.job_id} job={job} importId={data.import.import_id} ownerId={session.user.id} onFinished={onFinished} />}
  </>
}
