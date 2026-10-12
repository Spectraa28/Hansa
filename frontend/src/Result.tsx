import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Link, useSearchParams } from 'react-router-dom'
import { apiText, ApiError } from './api'
import { CircleCheck, CircleDashed, CircleX } from 'lucide-react'
import { measurement } from './report'
import type { Optimization } from './report'
import { TraceLinks } from './Trace'

const metrics = [['cost_usd', 'Cost', 'usd'], ['wall_time_seconds', 'Time', 'seconds'], ['model_calls', 'Model calls', 'number'], ['tokens_in', 'Input tokens', 'number']] as const
// A change this small is inside the noise of any two runs of the same agent.
const FLAT = 2
const percent = (change: number) => `${change > 0 ? '+' : '−'}${Math.abs(change) >= 10 ? Math.round(Math.abs(change)) : Math.abs(change).toFixed(1)}%`
const outcomes: Record<string, string> = { passed: 'passed', failed: 'failed', needs_review: 'checks passed' }

function TaskOutcome({ status }: { status: string | null }) {
  return <span>{status ? outcomes[status] || status.replaceAll('_', ' ') : 'not recorded'}</span>
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
      if (preview) {
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

  const rejected = attempt.decision === 'reject'
  // Say what the numbers say, not what an accepted fix is supposed to mean.
  const moved = comparison ? metrics.map(([key, label]) => [label.toLowerCase(), comparison.totals[key]?.change_percent] as const).filter((item): item is readonly [string, number] => item[1] != null && Math.abs(item[1]) >= FLAT) : []
  const better = moved.filter(([, change]) => change < 0).map(([label, change]) => `${label} ${percent(change)}`)
  const worse = moved.filter(([, change]) => change > 0).map(([label, change]) => `${label} ${percent(change)}`)
  const broken = comparison?.tasks.filter(task => task.regressed).length || 0
  const headline = !comparison ? 'No measured comparison was saved for this attempt.'
    : accepted ? `${better.length ? `Measured: ${better.join(', ')}.` : 'No measurable saving on these tasks.'}${worse.length ? ` Up: ${worse.join(', ')}.` : ''} No task got worse.${comparison.variation_measured ? '' : ' The baseline ran each task once, so a difference in time may just be run-to-run noise.'} The patch is yours.`
    : rejected ? `${broken ? `${broken} task${broken === 1 ? '' : 's'} that used to pass now fail${broken === 1 ? 's' : ''}` : 'It did not hold up'}${better.length ? `, even though it measured ${better.join(', ')}` : ''}. Hansa reverted it. The numbers are above so you can judge it yourself.`
    : 'No accepted patch is recorded for this attempt.'
  const reason = attempt.summary?.replace(/\*\*([^*]+)\*\*/g, '$1').replace(/`([^`]+)`/g, '$1')
  return <>
    <section className="slab overflow-hidden">
      <div className={`flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-line px-6 py-4 ${accepted ? 'bg-ok-soft' : rejected ? 'bg-waste-soft' : 'bg-wash'}`}>
        <h3 className="flex items-center gap-2.5 text-[20px] leading-tight font-semibold">{accepted ? <CircleCheck size={22} className="text-ok" aria-hidden="true" /> : rejected ? <CircleX size={22} className="text-waste" aria-hidden="true" /> : <CircleDashed size={22} className="text-muted" aria-hidden="true" />}{verdict}</h3>
        <p className="tabular text-[14px] text-muted">{comparison ? `tested against your baseline · ${comparison.tasks.length} task${comparison.tasks.length === 1 ? '' : 's'}${broken ? ` · ${broken} got worse` : ' · none got worse'}` : 'stored attempt'}</p>
      </div>
      {/* Before and after first: the verdict is only as good as these four rows. */}
      {comparison && <table className="w-full text-[15px] tabular-nums">
        <thead><tr className="text-left text-[13px] text-muted"><th scope="col" className="px-6 py-2.5 font-medium">measured</th><th scope="col" className="px-3 py-2.5 text-right font-medium">before</th><th scope="col" className="px-3 py-2.5 text-right font-medium">with fix</th><th scope="col" className="px-6 py-2.5 text-right font-medium">change</th></tr></thead>
        <tbody>{metrics.map(([key, label, unit]) => { const values = comparison.totals[key], change = values?.change_percent
          const round = (value: number | null) => value == null ? value : unit === 'usd' ? Number(value.toFixed(4)) : Number(value.toFixed(1))
          return <tr key={key} className="border-t border-line"><th scope="row" className="px-6 py-3 text-left font-medium">{label}</th><td className="px-3 py-3 text-right text-muted">{measurement(round(values?.baseline ?? null), unit)}</td><td className="px-3 py-3 text-right font-semibold">{measurement(round(values?.candidate ?? null), unit)}</td>
            <td className={`px-6 py-3 text-right text-[17px] font-semibold ${change == null || Math.abs(change) < FLAT ? 'text-muted' : change > 0 ? 'text-waste' : 'text-ok'}`}>{change == null || !Number.isFinite(change) ? '—' : Math.abs(change) < FLAT ? 'same' : percent(change)}</td></tr> })}</tbody>
      </table>}
      <div className="border-t border-line px-6 py-4"><p className="max-w-[72ch] text-[15px]">{headline}{attempt.incomplete ? ' This attempt ended before completing its work.' : ''}</p></div>
    </section>
    {attempt.proof && <section className={`mt-6 rounded-control p-5 ${attempt.proof.strength === 'thin' ? 'bg-waste-soft' : 'bg-surface'}`}>
      <p className="flex flex-wrap items-center gap-2 text-[20px] font-semibold">How strong is this proof? <span className={`chip ${attempt.proof.strength === 'solid' ? 'chip-ok' : attempt.proof.strength === 'thin' ? 'chip-waste' : 'bg-surface'}`}>{attempt.proof.strength}</span></p>
      {attempt.proof.notes.length ? <ul className="mt-2 list-disc space-y-1 pl-5 text-[14px]">{attempt.proof.notes.map(note => <li key={note}>{note}</li>)}</ul> : <p className="mt-2 text-[14px]">Every task was run, the checks test exact values, and the saving is larger than the agent's normal variation.</p>}
      {attempt.proof.strength === 'thin' && <p className="mt-3 text-[14px] font-medium">Treat this as a strong lead to review, not a finished change. Add tasks or exact checks in Setup and test it again to firm it up.</p>}
    </section>}
    {comparison ? <>
      {!preview && <p className="mt-4 flex flex-wrap items-center gap-2 tabular text-[14px] text-muted"><span>how Hansa got here:</span><TraceLinks trace={attempt.trace} label="trace" /></p>}
      <p className="mt-4 tabular text-[14px] text-muted">{comparison.all_tasks ? 'Full task set' : 'Partial task set'} · {comparison.tasks.length} task{comparison.tasks.length === 1 ? '' : 's'} · mean per pass{comparison.variation_measured ? '' : ' · baseline variation not measured'}</p>
      <div className="slab mt-9"><span className="slab-tab">task by task</span>
        <ul className="overflow-hidden rounded-[14px] pt-3">{comparison.tasks.map(task => <li key={task.task_id} className={`task-row grid items-center gap-x-5 gap-y-2 px-6 py-4 md:grid-cols-[minmax(0,1fr)_auto_auto] ${task.regressed ? 'bg-waste-soft' : ''}`}>
          <div className="min-w-0"><h4 className="font-semibold [overflow-wrap:anywhere]">{task.name || `Task ${task.task_id}`}</h4>{task.regressed && task.candidate_reason && <p className="mt-1 text-[14px] [overflow-wrap:anywhere]">{task.candidate_reason.split(';').slice(0, 2).join(';')}</p>}</div>
          <p className="tabular text-[14px] text-muted"><TaskOutcome status={task.baseline_status} /> → <TaskOutcome status={task.candidate_status} /></p>
          {task.regressed ? <span className="chip chip-waste">broke</span> : task.fixed ? <span className="chip chip-ok">fixed</span> : <span className="chip chip-quiet">same</span>}
        </li>)}</ul></div>
    </> : <p className="mt-9 rounded-card p-6 text-[14px]">No tested comparison was saved for this attempt.</p>}
    {reason && <details className="slab mt-9 p-6 pt-7"><span className="slab-tab">why</span><summary className="cursor-pointer font-display text-[22px] font-medium">Read Hansa's full reasoning</summary><p className="report-prose mt-4">{reason}</p></details>}
    <section className="slab mt-9 p-6 md:p-8">
      <h3 className="text-[22px] leading-tight font-semibold">{accepted ? 'Take it.' : 'Take it for review.'}</h3>
      <p className="mt-2 max-w-[56ch] text-muted">{accepted ? 'Download the patch, or copy a brief your coding agent can apply.' : 'Not accepted, so don\'t apply it as is. The prompt carries the rejection and the measurements with it.'}</p>
      {available ? <div className="mt-6 flex flex-wrap gap-4"><button className="button-primary" disabled={busy !== null} onClick={() => void artifact('patch')}>{busy === 'patch' ? 'Downloading…' : 'Download patch'}</button><button className="button-secondary" disabled={busy !== null} onClick={() => void artifact('handoff')}>{busy === 'handoff' ? 'Loading prompt…' : 'Copy prompt for my coding agent'}</button></div> : <p className="mt-4 text-[15px] text-muted">No patch or prompt is available for this attempt.</p>}
      {!accepted && !preview && <div className="mt-7 pt-5"><p className="tabular text-[14px] text-muted">or keep going</p>
        <div className="mt-2 flex flex-wrap gap-x-6 text-[15px] font-semibold"><Link to="?step=fix" className="inline-flex min-h-11 items-center link-action">Test it again to confirm →</Link><Link to="?step=findings" className="inline-flex min-h-11 items-center link-action">Try a different leak →</Link></div></div>}
      {message && <p role="status" className="mt-4 text-[15px]">{message}</p>}{error && <p role="alert" className="mt-4 text-[15px]">{error}</p>}
      {manualPrompt && <div className="mt-4"><label htmlFor="handoff-prompt" className="text-[15px] font-medium">Handoff prompt</label><textarea id="handoff-prompt" readOnly value={manualPrompt} onFocus={event => event.currentTarget.select()} className="field mt-2 h-64 tabular text-[14px] text-ink" /></div>}
    </section>
  </>
}

export default function Result({ attempts, importId, preview }: { attempts: Optimization[]; importId: string; preview: boolean }) {
  const [params, setParams] = useSearchParams()
  const attempt = attempts.find(item => item.job_id === params.get('attempt')) || attempts.at(-1)
  if (!attempt) return <section className="rounded-card px-8 py-14 text-center"><p className="font-display text-[30px] font-medium">No result yet.</p><p className="mt-2 text-muted">Test a fix and the verdict lands here.</p></section>
  return <>
    {attempts.length > 1 && <div role="tablist" aria-label="Tested fixes" className="mb-6 flex flex-wrap gap-2">{attempts.map((item, index) => <button key={item.job_id} role="tab" aria-selected={item.job_id === attempt.job_id}
      className={`chip min-h-9 px-4 text-[15px] ${item.job_id === attempt.job_id ? 'is-selected' : 'bg-surface hover:bg-wash'}`} onClick={() => setParams({ step: 'result', attempt: item.job_id })}>attempt {index + 1} · {item.decision === 'accept' ? 'accepted' : item.decision === 'reject' ? 'rejected' : item.decision?.replaceAll('_', ' ') || item.status}</button>)}</div>}
    <TestedFix key={attempt.job_id} attempt={attempt} importId={importId} preview={preview} />
  </>
}
