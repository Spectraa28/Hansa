import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import { apiText, ApiError } from './api'
import { barWidth, measurement } from './report'
import type { MetricComparison, Optimization } from './report'

const metrics = [['model_calls', 'Model calls', 'number'], ['cost_usd', 'Cost', 'usd'], ['wall_time_seconds', 'Wall time', 'seconds']] as const
const outcomes: Record<string, string> = { passed: 'Passed', failed: 'Failed', needs_review: 'Auto passed · needs review' }

function TaskOutcome({ status, passes }: { status: string | null; passes?: [number, number] }) {
  return <><p>{status ? outcomes[status] || status.replaceAll('_', ' ') : 'Not recorded'}</p>{passes && <p className="mt-1 text-xs text-muted">{passes[0]}/{passes[1]} automatic checks passed</p>}</>
}

function Bars({ label, values, unit }: { label: string; values: MetricComparison; unit: 'number' | 'usd' | 'seconds' }) {
  const change = values.change_percent
  return <div className="min-w-0">
    <h4 className="font-semibold">{label}</h4>
    <dl className="mt-4 space-y-4">{(['baseline', 'candidate'] as const).map(side => <div key={side}>
      <div className="flex flex-wrap justify-between gap-x-2 text-[13px]"><dt>{side === 'baseline' ? 'Baseline' : 'Candidate'}</dt><dd className="font-mono">{measurement(values[side], unit)}</dd></div>
      <div aria-hidden="true" className="mt-2 h-3 border-l border-line"><div hidden={barWidth(values[side], values[side === 'baseline' ? 'candidate' : 'baseline']) === 0} className={`h-full border border-current ${side === 'baseline' ? 'bg-ink text-ink' : 'bg-blue text-blue'}`} style={{ width: `${barWidth(values[side], values[side === 'baseline' ? 'candidate' : 'baseline'])}%` }} /></div>
    </div>)}</dl>
    <p className="mt-4 text-[13px] text-muted">{change == null || !Number.isFinite(change) ? 'Change not recorded' : change === 0 ? 'No change' : `${measurement(Math.abs(change))}% ${change < 0 ? 'lower' : 'higher'}`}</p>
  </div>
}

function TestedFix({ attempt, importId, preview }: { attempt: Optimization; importId: string; preview: boolean }) {
  const queryClient = useQueryClient()
  const [busy, setBusy] = useState<'patch' | 'handoff' | null>(null)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const [manualPrompt, setManualPrompt] = useState('')
  const accepted = attempt.decision === 'accept'
  const comparison = attempt.comparison
  const available = attempt.patch_available || attempt.tried_patch_available
  const verdict = accepted ? 'Fix accepted' : attempt.decision === 'reject' ? 'Fix rejected' : attempt.decision === 'no_improvement' ? 'No improvement retained' : 'No final verdict yet'

  async function artifact(kind: 'patch' | 'handoff') {
    setBusy(kind); setError(''); setMessage(''); setManualPrompt('')
    try {
      let text: string
      if (preview && import.meta.env.DEV) {
        const data = kind === 'patch' ? (await import('./data/swarm-patches.json')).default : (await import('./data/swarm-handoffs.json')).default
        text = (data as Record<string, string>)[attempt.job_id]
        if (!text) throw new Error('No saved artifact')
      } else {
        text = await apiText(`/github/imports/${encodeURIComponent(importId)}/agent-jobs/${encodeURIComponent(attempt.job_id)}/${kind}`)
      }
      if (kind === 'patch') {
        const url = URL.createObjectURL(new Blob([text], { type: 'text/plain;charset=utf-8' }))
        const link = document.createElement('a')
        link.href = url
        link.download = `hansa-${attempt.job_id.slice(0, 8)}${accepted ? '' : '-not-accepted'}.patch`
        link.click()
        setTimeout(() => URL.revokeObjectURL(url), 1000)
        setMessage('Patch downloaded.')
      } else {
        try { await navigator.clipboard.writeText(text); setMessage('Prompt copied.') }
        catch { setManualPrompt(text); setMessage('Clipboard access is unavailable. Select and copy the prompt below.') }
      }
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 401) queryClient.setQueryData(['session'], null)
      setError(caught instanceof ApiError ? caught.message : `Could not ${kind === 'patch' ? 'download the patch' : 'load the prompt'}. Try again.`)
    } finally { setBusy(null) }
  }

  return <>
    <div className={`border-b border-line px-6 py-5 ${accepted ? 'bg-ok-soft' : attempt.decision === 'reject' ? 'bg-waste-soft' : 'bg-wash'}`}>
      <div className="flex flex-wrap items-center justify-between gap-3"><h3 className="font-display text-2xl font-semibold">{verdict}</h3><span className="text-[13px]">{comparison ? 'Tested result' : 'Stored attempt'}</span></div>
      <p className="mt-2 text-[13px]">{accepted ? 'The tested change was retained.' : attempt.decision === 'reject' ? 'The tested change was not retained. Its measurements are preserved below.' : 'No accepted patch is recorded for this attempt.'}</p>
      {attempt.incomplete && <p className="mt-2 text-[13px]">This attempt ended before completing its work.</p>}
    </div>
    {comparison ? <>
      <div className="border-b border-line p-6">
        <h3 className="font-semibold">Baseline vs candidate</h3>
        <p className="mt-2 text-[13px] text-muted">{comparison.all_tasks ? 'Full task set' : 'Partial task set'} · {comparison.tasks.length} compared task{comparison.tasks.length === 1 ? '' : 's'} · mean per compared task set</p>
        <p className="mt-1 text-[13px] text-muted">Comparing the {attempt.comparison_is_of || 'stored candidate'} against its own baseline.</p>
        <div className="mt-6 grid gap-8 md:grid-cols-3">{metrics.map(([key, label, unit]) => <Bars key={key} label={label} unit={unit} values={comparison.totals[key]} />)}</div>
        {!comparison.variation_measured && <p className="mt-5 text-[13px] text-muted">Baseline variation was not measured.</p>}
      </div>
      <div className="border-b border-line p-6">
        <h3 className="font-semibold">Task outcomes</h3><p className="report-prose mt-2 text-muted">{comparison.note.replaceAll('needs_review', 'Needs review')}</p>
        <ul className="mt-5 divide-y divide-line">{comparison.tasks.map(task => <li key={task.task_id} className="py-5 first:pt-0 last:pb-0">
          <div className="flex flex-wrap items-start justify-between gap-2"><h4 className="min-w-0 break-words text-[13px] font-semibold [overflow-wrap:anywhere]">{task.name || `Task ${task.task_id}`}</h4>{task.regressed && <span className="rounded-control bg-waste-soft px-2 py-1 text-xs">Regressed</span>}{task.fixed && <span className="rounded-control border border-line px-2 py-1 text-xs">Automatic checks improved</span>}</div>
          <dl className="mt-3 grid grid-cols-2 gap-4 text-[13px]"><div><dt className="mb-1 text-xs text-muted">Baseline</dt><dd><TaskOutcome status={task.baseline_status} passes={task.baseline_automatic_passes} /></dd></div><div><dt className="mb-1 text-xs text-muted">Candidate</dt><dd><TaskOutcome status={task.candidate_status} passes={task.candidate_automatic_passes} /></dd></div></dl>
          {task.candidate_reason && <p className="report-prose mt-3 text-muted">{task.candidate_reason}</p>}
        </li>)}</ul>
      </div>
    </> : <p className="border-b border-line p-6 text-[13px]">No tested comparison has been saved for this attempt.</p>}
    <div className="border-b border-line p-6"><h3 className="font-semibold">Why this verdict</h3><p className="report-prose mt-3">{attempt.summary?.replace(/\*\*([^*]+)\*\*/g, '$1').replace(/`([^`]+)`/g, '$1') || 'No reason was recorded.'}</p>{comparison && <p className="mt-4 text-[13px] text-muted">Measured outcome: {comparison.verdict.replaceAll('_', ' ')}.</p>}</div>
    <div className="p-6">
      <h3 className="font-semibold">Take it to your coding agent</h3>
      <p className="report-prose mt-2 text-muted">{accepted ? 'Download the retained patch or copy its measured handoff prompt.' : 'For review only. Do not apply this change unchanged. The prompt includes its rejection and measured results.'}</p>
      {available ? <div className="mt-5 flex flex-wrap gap-3"><button className="button-primary" disabled={busy !== null} onClick={() => void artifact('patch')}>{busy === 'patch' ? 'Downloading…' : 'Download patch'}</button><button className="button-secondary" disabled={busy !== null} onClick={() => void artifact('handoff')}>{busy === 'handoff' ? 'Loading prompt…' : 'Copy prompt'}</button></div> : <p className="mt-4 text-[13px] text-muted">No patch or handoff prompt is available for this attempt.</p>}
      {message && <p role="status" className="mt-4 text-[13px]">{message}</p>}{error && <p role="alert" className="mt-4 text-[13px]">{error}</p>}
      {manualPrompt && <div className="mt-4"><label htmlFor="handoff-prompt" className="text-[13px] font-medium">Handoff prompt</label><textarea id="handoff-prompt" readOnly value={manualPrompt} onFocus={event => event.currentTarget.select()} className="field mt-2 h-64 font-mono text-xs" /></div>}
    </div>
  </>
}

export default function Result({ attempts, importId, preview }: { attempts: Optimization[]; importId: string; preview: boolean }) {
  const [params, setParams] = useSearchParams()
  const attempt = attempts.find(item => item.job_id === params.get('attempt')) || attempts.at(-1)
  if (!attempt) return <p className="p-6">No optimization result has been saved yet.</p>
  return <>
    <div className="border-b border-line px-6 py-4"><label htmlFor="result-attempt" className="block text-[13px] font-medium">Tested fix</label><select id="result-attempt" value={attempt.job_id} className="field mt-2 text-[13px]" onChange={event => setParams({ step: 'result', attempt: event.target.value })}>{attempts.map((item, index) => <option key={item.job_id} value={item.job_id}>Attempt {index + 1} · {item.decision === 'accept' ? 'accepted' : item.decision === 'reject' ? 'rejected' : item.decision?.replaceAll('_', ' ') || item.status}</option>)}</select></div>
    <TestedFix key={attempt.job_id} attempt={attempt} importId={importId} preview={preview} />
  </>
}
