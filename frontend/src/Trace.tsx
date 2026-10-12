import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import { ChevronRight, ExternalLink, Link2, X } from 'lucide-react'
import { api, ApiError } from './api'

type Span = { span_id: string; name: string; type: string; status: string; duration_ms: number | null; parent_span_id: string | null; input_value?: string | null; output_value?: string | null }
// What Hansa's own gateway recorded for a model call. Neatlogs keeps the step; the figures come from the ledger.
type Step = { model: string; requested_model: string; tokens_in: number | null; tokens_out: number | null; cost_usd: number | null; http_status: number | null
  messages: number; prompt_chars: number; repeated_messages: number; repeated_chars: number; tool_schema_chars: number; tool_calls: string[]; finish_reason: string }
type Summary = { cost_usd?: number | null; task_id?: string; stop_reason?: string; prompt_chars?: number; repeated_chars?: number; external_calls?: number; status?: string }
type TraceContext = {
  trace_id: string; name: string; status: string; latency_ms: number | null; llm_calls: number | null; tool_calls: number | null
  prompt_tokens: number | null; completion_tokens: number | null; has_error: boolean; span_count: number; returned_span_count: number
  created_at: string; spans: Span[]; detections: Record<string, unknown>[]
  hansa?: { kind: string; summary: Summary; steps: Record<string, Step> }
}
export type TraceRef = { status?: string; trace_id?: string; trace_ids?: string[]; reason?: string } | null | undefined

// Where a trace opens on Neatlogs itself. Neatlogs returns no link with a trace, so the address is built from its ID;
// set VITE_NEATLOGS_TRACE_URL if your project's traces live at a different address.
const template: string = import.meta.env.VITE_NEATLOGS_TRACE_URL || 'https://app.neatlogs.com/traces/{id}'
const neatlogs = (id: string) => template.replace('{id}', encodeURIComponent(id))
const kinds: Record<string, [string, string]> = { llm: ['model', 'bg-ink text-paper'], tool_call: ['tool', 'bg-waste text-ink'], chain: ['code', 'bg-wash text-ink'] }
const seconds = (ms: number | null) => ms == null ? '—' : ms >= 1000 ? `${(ms / 1000).toFixed(ms >= 10000 ? 0 : 1)} s` : `${Math.round(ms)} ms`
const money = (value: number | null | undefined) => value == null ? 'not priced' : `$${value.toFixed(value < 0.01 ? 5 : 4)}`
const share = (part: number, whole: number) => whole > 0 ? Math.round(part / whole * 100) : 0
const idsOf = (trace: TraceRef) => [...new Set([...(trace?.trace_ids || []), ...(trace?.trace_id ? [trace.trace_id] : [])])].filter(Boolean)

/** Chips that open a run's trace in the side panel. The trace ID goes in the address, so the link can be shared. */
export function TraceLinks({ ids, trace, label = 'trace' }: { ids?: (string | null)[]; trace?: TraceRef; label?: string }) {
  const [params, setParams] = useSearchParams()
  const [expanded, setExpanded] = useState(false)
  const all = ids ? ids.filter((id): id is string => Boolean(id)) : idsOf(trace)
  if (!all.length) return trace?.reason ? <span className="chip chip-quiet" title={trace.reason}>trace not delivered</span> : null
  const open = (id: string) => { const next = new URLSearchParams(params); next.set('trace', id); setParams(next) }
  // A long job is stored as several parts. Show two, and the rest on request, instead of a row of five chips.
  const shown = expanded || all.length <= 3 ? all : all.slice(0, 2)
  return <span className="inline-flex flex-wrap gap-1.5">{shown.map((id, index) => <button key={id} type="button" onClick={() => open(id)}
    className={`chip min-h-8 ${params.get('trace') === id ? 'bg-ink text-paper' : 'bg-surface hover:bg-wash'}`}>{label}{all.length > 1 ? ` ${index + 1}` : ''}</button>)}
    {shown.length < all.length && <button type="button" className="chip chip-quiet min-h-8" onClick={() => setExpanded(true)}>+{all.length - shown.length} more</button>}</span>
}

/** Everything known about one step: the ledger's figures for a model call, and what was sent and returned. */
function Facts({ span, step }: { span: Span; step?: Step }) {
  const rows: [string, string][] = step ? [
    ['model', step.requested_model && step.requested_model !== step.model ? `${step.model} (the agent asked for ${step.requested_model})` : step.model],
    ['tokens', `${step.tokens_in?.toLocaleString() ?? '—'} in · ${step.tokens_out?.toLocaleString() ?? '—'} out`],
    ['cost', money(step.cost_usd)],
    ['request', `${step.messages} messages · ${step.prompt_chars.toLocaleString()} characters`],
    ['already sent before', `${share(step.repeated_chars, step.prompt_chars)}% · ${step.repeated_messages} of ${step.messages} messages repeat the previous call`],
    ['tool definitions', step.tool_schema_chars ? `${step.tool_schema_chars.toLocaleString()} characters sent with this call` : 'none sent'],
    ['asked to run', step.tool_calls.length ? step.tool_calls.join(', ') : 'no tools; it answered'],
    ['ended because', `${step.finish_reason || 'not reported'}${step.http_status && step.http_status !== 200 ? ` · HTTP ${step.http_status}` : ''}`],
  ] : []
  const sent = span.input_value?.trim(), returned = span.output_value?.trim()
  return <div className="mt-3 rounded-control px-3.5 py-3">
    {rows.length > 0 && <dl className="grid grid-cols-[130px_minmax(0,1fr)] gap-x-3 gap-y-1.5 text-[15px]">{rows.map(([label, value]) => <div key={label} className="contents"><dt className="text-muted">{label}</dt><dd className="tabular [overflow-wrap:anywhere]">{value}</dd></div>)}</dl>}
    {span.type === 'chain' && <p className="text-[15px] text-muted">Time between two model calls, spent in the agent's own code and tools. Worked out from the gaps, not measured directly.</p>}
    {sent && <div className={rows.length ? 'mt-3' : ''}><p className="label">{step ? 'last message sent' : 'went in'}</p><p className="mt-1 text-[15px] leading-relaxed whitespace-pre-wrap [overflow-wrap:anywhere]">{sent}</p></div>}
    {returned && <div className="mt-3"><p className="label">came back</p><p className="mt-1 text-[15px] leading-relaxed whitespace-pre-wrap [overflow-wrap:anywhere]">{returned}</p></div>}
    {!rows.length && !sent && !returned && span.type !== 'chain' && <p className="text-[15px] text-muted">Neatlogs kept only the name, the outcome and the time for this step.</p>}
  </div>
}

function Tree({ spans, steps }: { spans: Span[]; steps: Record<string, Step> }) {
  const known = new Set(spans.map(span => span.span_id))
  const children = new Map<string, Span[]>()
  for (const span of spans) { const key = span.parent_span_id && known.has(span.parent_span_id) ? span.parent_span_id : ''; children.set(key, [...(children.get(key) || []), span]) }
  const longest = Math.max(1, ...spans.map(span => span.duration_ms || 0))
  const rows: { span: Span; depth: number }[] = []
  const walk = (key: string, depth: number) => { for (const span of children.get(key) || []) { rows.push({ span, depth }); walk(span.span_id, depth + 1) } }
  walk('', 0)
  return <ol className="">{rows.map(({ span, depth }) => { const [label, tone] = kinds[span.type] || [span.type.replaceAll('_', ' '), 'bg-surface text-ink']
    const step = steps[span.span_id]
    return <li key={span.span_id} className="task-row" style={{ paddingLeft: Math.min(depth, 4) * 16 }}><details className="group py-2.5">
      <summary className="grid cursor-pointer list-none grid-cols-[minmax(0,1fr)_64px] items-center gap-3 [&::-webkit-details-marker]:hidden">
        <div className="min-w-0"><p className="flex items-center gap-2 text-[14px]"><ChevronRight size={14} aria-hidden="true" className="shrink-0 text-muted transition-transform group-open:rotate-90" /><span className={`chip px-2 py-0 text-[14px] ${tone}`}>{label}</span><span className="truncate tabular text-[15px]">{span.name}</span>
          {span.status !== 'SUCCESS' && <span className="chip chip-waste px-2 py-0 text-[14px]">{span.status.toLowerCase()}</span>}</p>
          {/* The figures that matter, readable without opening the step. */}
          {step && <p className="mt-1 pl-[22px] tabular text-[14px] text-muted">{step.tokens_in?.toLocaleString() ?? '—'} in · {step.tokens_out?.toLocaleString() ?? '—'} out · {money(step.cost_usd)}
            {step.repeated_chars > 0 && <span className="font-semibold text-ink"> · {share(step.repeated_chars, step.prompt_chars)}% already sent</span>}{step.tool_calls.length > 0 && <> · calls {step.tool_calls.join(', ')}</>}</p>}
          <div aria-hidden="true" className="mt-1.5 ml-[22px] h-2 rounded-full bg-wash"><div className={`h-full rounded-full ${span.type === 'llm' ? 'bg-ink' : span.type === 'tool_call' || span.type === 'chain' ? 'bg-waste' : 'bg-muted/50'}`} style={{ width: `${Math.max(1.5, (span.duration_ms || 0) / longest * 100)}%` }} /></div></div>
        <span className="text-right tabular text-[14px] tabular-nums text-muted">{seconds(span.duration_ms)}</span></summary>
      <Facts span={span} step={step} /></details></li> })}</ol>
}

/** A side panel showing the trace named in the address. Render once per import page. */
export function TracePanel({ importId }: { importId: string }) {
  const [params, setParams] = useSearchParams()
  const [copied, setCopied] = useState(false)
  const id = params.get('trace')
  const trace = useQuery({ queryKey: ['trace', importId, id], enabled: Boolean(id), staleTime: 60000,
    queryFn: ({ signal }) => api<TraceContext>(`/github/imports/${encodeURIComponent(importId)}/traces/${encodeURIComponent(id!)}`, { signal }) })
  if (!id) return null
  const close = () => { const next = new URLSearchParams(params); next.delete('trace'); setParams(next) }
  const data = trace.data
  const summary = data?.hansa?.summary
  const stats = data ? [['time', seconds(data.latency_ms)], ['cost', money(summary?.cost_usd)], ['model calls', data.llm_calls ?? '—'], ['tool calls', data.tool_calls ?? '—'], ['tokens in', data.prompt_tokens?.toLocaleString() ?? '—'], ['tokens out', data.completion_tokens?.toLocaleString() ?? '—']] : []
  return <div className="trace-backdrop fixed inset-0 z-50 flex justify-end bg-ink/40" onClick={close}>
    <aside role="dialog" aria-modal="true" aria-label="Trace" onClick={event => event.stopPropagation()} className="trace-panel flex h-full w-full max-w-[640px] flex-col bg-paper">
      <header className="flex items-start justify-between gap-3 bg-ink px-5 py-4 text-paper">
        <div className="min-w-0"><p className="tabular text-[14px] text-paper/80">trace · read back from Neatlogs</p>
          <h2 className="mt-1 font-display text-[26px] leading-none font-medium">{data ? data.name.replace(/^hansa-/, '').replaceAll('-', ' ') + ' run' : 'Loading…'}</h2>
          <p className="mt-2 tabular text-[14px] break-all text-paper/80">{id}</p></div>
        <button aria-label="Close trace" onClick={close} className="grid size-11 shrink-0 place-items-center rounded-control border border-paper hover:bg-waste hover:text-ink"><X size={20} aria-hidden="true" /></button>
      </header>
      <div className="flex flex-wrap gap-2 px-5 py-3">
        <button className="chip min-h-9 bg-surface hover:bg-waste" onClick={() => { void navigator.clipboard.writeText(location.href).then(() => { setCopied(true); setTimeout(() => setCopied(false), 1600) }).catch(() => undefined) }}><Link2 size={14} aria-hidden="true" /> {copied ? 'link copied' : 'copy link to this trace'}</button>
        <a href={neatlogs(id)} target="_blank" rel="noopener noreferrer" className="chip min-h-9 bg-surface hover:bg-wash"><ExternalLink size={14} aria-hidden="true" /> open in Neatlogs (needs project access)</a>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-5 py-5">
        {trace.isPending ? <p role="status">Fetching the trace from Neatlogs…</p>
          : trace.isError ? <div role="alert"><p className="font-semibold">Neatlogs didn't return this trace.</p><p className="mt-1 text-muted">{trace.error instanceof ApiError ? trace.error.message : 'Check your connection.'}</p><button className="button-secondary mt-4" onClick={() => void trace.refetch()}>Try again</button></div>
          : data && <>
            <dl className="grid grid-cols-3 gap-x-4 gap-y-4 sm:grid-cols-6">{stats.map(([label, value]) => <div key={label as string}><dt className="label">{label}</dt><dd className="mt-1 font-display text-[19px] font-medium tabular-nums">{value}</dd></div>)}</dl>
            {summary?.prompt_chars ? <p className="mt-4 rounded-control bg-waste-soft px-3 py-2 text-[14px]"><b>{share(summary.repeated_chars || 0, summary.prompt_chars)}% of what this run sent, it had already sent</b> on the call before ({(summary.repeated_chars || 0).toLocaleString()} of {summary.prompt_chars.toLocaleString()} characters).{summary.task_id ? ` Task ${summary.task_id}.` : ''}{summary.stop_reason ? ` Ended: ${summary.stop_reason.replaceAll('_', ' ')}.` : ''}</p> : null}
            {data.has_error && <p className="mt-4 rounded-control bg-waste px-3 py-2 text-[14px] font-medium">Neatlogs marked an error in this trace.</p>}
            {data.detections.length > 0 && <section className="mt-6"><h3 className="label">flagged by Neatlogs</h3><ul className="mt-2 grid gap-2">{data.detections.map((item, index) =>
              <li key={index} className="rounded-control bg-waste-soft px-3 py-2 text-[14px]">{String(item.title || item.name || item.type || 'Detection')}{item.description || item.message ? <span className="block text-[15px] text-muted">{String(item.description || item.message)}</span> : null}</li>)}</ul></section>}
            <section className="mt-7"><h3 className="label">every step, in order · bar = how long it took · open a step for its details</h3><div className="mt-2"><Tree spans={data.spans} steps={data.hansa?.steps || {}} /></div>
              {data.returned_span_count < data.span_count && <p className="mt-3 tabular text-[14px] text-muted">Showing {data.returned_span_count} of {data.span_count} steps.</p>}</section>
            <p className="mt-6 tabular text-[14px] leading-relaxed text-muted">The steps and their timing are read back from Neatlogs. Tokens, cost and request sizes come from Hansa's own record of each call. Recorded {new Date(data.created_at).toLocaleString()}.</p>
          </>}
      </div>
    </aside>
  </div>
}
