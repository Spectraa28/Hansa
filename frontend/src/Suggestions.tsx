import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Check, ClipboardCopy, Download, ShieldCheck, TestTube2 } from 'lucide-react'
import { api, ApiError } from './api'
import type { Session } from './api'
import { areas } from './areas'
import { sourceUrl } from './report'
import type { ImportReport } from './report'

type Play = {
  id: string; area: string; kind: 'safe' | 'needs_proof'; title: string; why: string; evidence: string[]; steps: string[]; keep: string; check: string; where: string[]
  estimate: { cost_percent: number | null; latency_percent: number | null; basis: string | null }
}
type Answer = { measured: boolean; suggestions: Play[]; brief_all?: string }

// Savings overlap, so they compound: 30% then 20% of what is left is 44%, not 50%.
const combined = (plays: Play[], key: 'cost_percent' | 'latency_percent') => Math.round((1 - plays.reduce((left, play) => left * (1 - (play.estimate[key] || 0) / 100), 1)) * 100)

/** What an agent engineer would change, picked from measurements. Choose some, get one brief for a coding agent. */
export default function Suggestions({ data, session, preview }: { data: ImportReport; session?: Session | null; preview: boolean }) {
  const base = `/github/imports/${encodeURIComponent(data.import.import_id)}`
  const answer = useQuery({ queryKey: ['suggestions', session?.user.id, data.import.import_id, data.baseline?.baseline_id, preview], enabled: preview || Boolean(session),
    queryFn: async ({ signal }): Promise<Answer> => preview ? (await import('./data/swarm-suggestions.json')).default as Answer : api<Answer>(`${base}/suggestions`, { signal }) })
  const [picked, setPicked] = useState<Set<string> | null>(null)
  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState('')
  const [manual, setManual] = useState('')

  if (answer.isPending) return <p role="status" className="slab p-8">Reading the measurements and your code…</p>
  if (answer.isError) return <div role="alert" className="slab p-8"><p>{answer.error instanceof ApiError ? answer.error.message : 'Could not load suggestions.'}</p><button className="button-secondary mt-4" onClick={() => void answer.refetch()}>Try again</button></div>
  const plays = answer.data.suggestions
  // Safe changes start ticked: they do not alter what the agent does.
  const chosen = picked ?? new Set(plays.filter(play => play.kind === 'safe').map(play => play.id))
  const selected = plays.filter(play => chosen.has(play.id))
  const toggle = (id: string) => { const next = new Set(chosen); if (next.has(id)) next.delete(id); else next.add(id); setPicked(next); setNote('') }
  const cost = combined(selected, 'cost_percent'), time = combined(selected, 'latency_percent')

  async function brief(action: 'copy' | 'download') {
    setBusy(true); setNote(''); setManual('')
    try {
      const text = preview ? answer.data!.brief_all || '' : await (await fetch(`${base}/suggestions/brief`, { method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': session!.csrf_token }, body: JSON.stringify({ ids: [...chosen] }) }).then(response => { if (!response.ok) throw new Error(); return response })).text()
      if (action === 'download') {
        const url = URL.createObjectURL(new Blob([text], { type: 'text/markdown;charset=utf-8' }))
        const link = Object.assign(document.createElement('a'), { href: url, download: 'hansa-brief.md' })
        link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000); setNote('Brief downloaded.')
      } else {
        try { await navigator.clipboard.writeText(text); setNote('Copied. Paste it into Claude Code, Codex or Cursor in your repo.') }
        catch { setManual(text); setNote('Copy it from the box below.') }
      }
    } catch { setNote('Could not build the brief. Try again.') } finally { setBusy(false) }
  }

  if (!plays.length) return <section className="rounded-card border-2 border-dashed border-ink px-8 py-12 text-center"><p className="font-display text-[28px] font-[760] tracking-[-.03em]">Nothing obvious to change.</p>
    <p className="mx-auto mt-2 max-w-[52ch] text-muted">{answer.data.measured ? 'The shape of the calls and the code look reasonable. A deeper hunt below can still find waste.' : 'Run the baseline first so Hansa has measurements to work from.'}</p></section>

  const group = (kind: Play['kind'], Icon: typeof Check, title: string, sub: string) => { const items = plays.filter(play => play.kind === kind)
    return items.length > 0 && <div className="mt-8 first:mt-0"><h3 className="flex items-center gap-2 font-display text-[22px] font-[780] tracking-[-.03em]"><Icon size={20} aria-hidden="true" />{title}</h3><p className="mt-1 text-[14px] text-muted">{sub}</p>
      <ul className="mt-4 grid gap-3">{items.map(play => { const on = chosen.has(play.id), est = play.estimate
        return <li key={play.id} className={`rounded-control border-2 border-ink ${on ? 'bg-surface shadow-[4px_4px_0_var(--ink)]' : 'bg-transparent'}`}>
          <label className="relative flex cursor-pointer items-start gap-3 p-4 sm:p-5"><input type="checkbox" className="absolute inset-0 size-full cursor-pointer opacity-0" checked={on} onChange={() => toggle(play.id)} />
            <span aria-hidden="true" className={`mt-0.5 grid size-6 shrink-0 place-items-center rounded-[6px] border-2 border-ink ${on ? 'bg-waste' : 'bg-surface'}`}>{on && <Check size={15} strokeWidth={3.5} />}</span>
            <span className="min-w-0 flex-1"><span className="flex flex-wrap items-center gap-x-3 gap-y-1"><span className="font-display text-[19px] leading-snug font-[740] tracking-[-.02em] sm:text-[21px]">{play.title}</span>
              <span className="chip chip-quiet px-2 py-0 text-[11px]">{areas.find(area => area.key === play.area)?.name || play.area}</span></span>
              <span className="mt-1 block text-[14px] text-muted">{play.why}</span></span>
            <span className="shrink-0 text-right">{est.cost_percent ? <span className="big-number block text-[26px] sm:text-[30px]">−{Math.round(est.cost_percent)}%</span> : est.latency_percent ? <span className="big-number block text-[26px] sm:text-[30px]">−{Math.round(est.latency_percent)}%</span> : <span className="chip chip-quiet">guard</span>}
              <span className="font-mono text-[11px] text-muted">{est.cost_percent ? 'cost, est.' : est.latency_percent ? 'time, est.' : 'no saving'}</span></span></label>
          <details className="border-t-2 border-dashed border-line px-4 pb-4 text-[14px] sm:px-5"><summary className="flex min-h-11 cursor-pointer items-center font-mono text-[12px] text-muted">evidence, where, and how</summary>
            <ul className="list-disc space-y-1 pl-5">{play.evidence.map(item => <li key={item}>{item}</li>)}</ul>
            {play.where.length > 0 && <p className="mt-3 flex flex-wrap gap-1.5">{play.where.map(place => { const [path, line] = [place.slice(0, place.lastIndexOf(':')), Number(place.slice(place.lastIndexOf(':') + 1))]
              const url = sourceUrl(data.import.repository, data.import.commit_sha, { path, start_line: line, end_line: line }, data.import.folder)
              return url ? <a key={place} href={url} target="_blank" rel="noopener noreferrer" className="chip shrink bg-surface break-all whitespace-normal hover:bg-ink hover:text-paper">{place} ↗</a> : <span key={place} className="chip shrink break-all whitespace-normal">{place}</span> })}</p>}
            <ol className="mt-3 list-decimal space-y-1 pl-5">{play.steps.map(step => <li key={step}>{step}</li>)}</ol>
            <p className="mt-3"><b>Must stay true:</b> {play.keep}</p><p className="mt-1"><b>How to check:</b> {play.check}</p>
            {est.basis && <p className="mt-2 font-mono text-[12px] text-muted">estimate basis: {est.basis}</p>}</details></li> })}</ul></div> }

  return <section>
    <div className="slab p-6 pt-8 sm:p-8 sm:pt-9"><span className="slab-tab">what an agent engineer would change</span>
      <p className="mb-6 max-w-[64ch] text-muted">Picked from {answer.data.measured ? 'the X-ray of your baseline and ' : ''}a read of your code. No AI run, no cost. Tick what you want, and Hansa writes one brief your coding agent can carry out.</p>
      {group('safe', ShieldCheck, 'Safe to apply', 'These change how requests are sent and billed, not what your agent does or says.')}
      {group('needs_proof', TestTube2, 'Needs proof', 'These change behaviour. Apply one at a time and rerun your tasks after each.')}
    </div>
    <div className="sticky bottom-3 z-30 mt-5 rounded-card border-2 border-ink bg-ink p-4 text-paper shadow-[var(--hard)] sm:p-5">
      <div className="flex flex-wrap items-center gap-x-6 gap-y-3"><p className="min-w-0 flex-1"><span className="font-mono text-[12px] uppercase tracking-[.08em] text-paper/70">{selected.length} selected · estimated together</span>
        <span className="mt-0.5 block font-display text-[26px] leading-tight font-[780] tracking-[-.03em]">{cost ? `−${cost}% cost` : 'no cost change'}{time ? ` · −${time}% time` : ''}</span></p>
        <div className="flex flex-wrap gap-3"><button className="button-primary shadow-[3px_3px_0_var(--paper)]" disabled={busy || !selected.length} onClick={() => void brief('copy')}><ClipboardCopy size={16} aria-hidden="true" /> {busy ? 'Writing…' : 'Copy the brief'}</button>
          <button className="button-secondary shadow-[3px_3px_0_var(--waste)]" disabled={busy || !selected.length} aria-label="Download the brief" onClick={() => void brief('download')}><Download size={16} aria-hidden="true" /></button></div></div>
      {note && <p role="status" className="mt-3 text-[14px]">{note} Then push the change, import the repo again and rerun the baseline to see the real numbers.</p>}
      {preview && <p className="mt-2 font-mono text-[12px] text-paper/60">Demo: the brief here covers every suggestion for the saved Swarm run.</p>}
      {manual && <textarea readOnly value={manual} onFocus={event => event.currentTarget.select()} className="field mt-3 h-56 font-mono text-[12px] text-ink" />}
    </div>
    <p className="mt-3 font-mono text-[12px] text-muted">Estimates compound rather than add, and stay estimates until your tasks are rerun.</p>
  </section>
}
