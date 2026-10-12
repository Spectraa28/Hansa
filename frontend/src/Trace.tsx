import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import { ChevronRight, Link2, X } from 'lucide-react'
import { api, ApiError } from './api'
import { holdScroll } from './smoothScroll'

type Span = { span_id: string; name: string; type: string; status: string; duration_ms: number | null; parent_span_id: string | null; input_value?: string | null; output_value?: string | null }
// What Hansa's own gateway recorded for a model call. Neatlogs keeps the step; the figures come from the ledger.
type Step = { model: string; requested_model: string; tokens_in: number | null; tokens_out: number | null; cost_usd: number | null; http_status: number | null
  messages: number; prompt_chars: number; repeated_messages: number; repeated_chars: number; tool_schema_chars: number; tool_calls: string[]; finish_reason: string }
// What one of Hansa's own tool steps took in and gave back, kept by Hansa when the job ran.
type Tool = { name: string; ok: boolean; input: string; output: string }
type Summary = { cost_usd?: number | null; task_id?: string; stop_reason?: string; prompt_chars?: number; repeated_chars?: number; external_calls?: number; status?: string }
type TraceContext = {
  trace_id: string; name: string; status: string; latency_ms: number | null; llm_calls: number | null; tool_calls: number | null
  prompt_tokens: number | null; completion_tokens: number | null; has_error: boolean; span_count: number; returned_span_count: number
  created_at: string; spans: Span[]; detections: Record<string, unknown>[]
  hansa?: { kind: string; summary: Summary; steps: Record<string, Step>; tools?: Record<string, Tool> }
}
export type TraceRef = { status?: string; trace_id?: string; trace_ids?: string[]; reason?: string } | null | undefined

const kinds: Record<string, [string, string]> = { llm: ['model', 'bg-ink text-paper'], tool_call: ['tool', 'bg-wash text-ink'], chain: ['code', 'bg-surface text-muted'] }
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
    className={`chip min-h-8 ${params.get('trace') === id ? 'is-selected' : 'bg-surface hover:bg-wash'}`}>{label}{all.length > 1 ? ` ${index + 1}` : ''}</button>)}
    {shown.length < all.length && <button type="button" className="chip chip-quiet min-h-8" onClick={() => setExpanded(true)}>+{all.length - shown.length} more</button>}</span>
}

/** Everything known about one step: the ledger's figures for a model call, and what was sent and returned. */
function Facts({ span, step, tool }: { span: Span; step?: Step; tool?: Tool }) {
  const rows: [string, string][] = step ? [
    ['model', step.requested_model && step.requested_model !== step.model ? `${step.model} (the agent asked for ${step.requested_model})` : step.model],
    ['tokens', `${step.tokens_in?.toLocaleString() ?? '—'} in · ${step.tokens_out?.toLocaleString() ?? '—'} out`],
    ['cost', money(step.cost_usd)],
    ['request', `${step.messages} messages · ${step.prompt_chars.toLocaleString()} characters`],
    ['already sent before', `${share(step.repeated_chars, step.prompt_chars)}% · ${step.repeated_messages} of ${step.messages} messages repeat the previous call`],
    ['tool definitions', step.tool_schema_chars ? `${step.tool_schema_chars.toLocaleString()} characters sent with this call` : 'none sent'],
    ['asked to run', step.tool_calls.length ? step.tool_calls.join(', ') : 'no tools; it answered'],
    ['ended because', `${step.finish_reason || 'not reported'}${step.http_status && step.http_status !== 200 ? ` · HTTP ${step.http_status}` : ''}`],
  ] : tool ? [['tool', tool.name], ['outcome', tool.ok ? 'completed' : 'returned an error']] : []
  const sent = (tool?.input || span.input_value)?.trim(), returned = (tool?.output || span.output_value)?.trim()
  return <div className="mt-3 rounded-control px-3.5 py-3">
    {rows.length > 0 && <dl className="grid grid-cols-[130px_minmax(0,1fr)] gap-x-3 gap-y-1.5 text-[15px]">{rows.map(([label, value]) => <div key={label} className="contents"><dt className="text-muted">{label}</dt><dd className="tabular [overflow-wrap:anywhere]">{value}</dd></div>)}</dl>}
    {span.type === 'chain' && <p className="text-[15px] text-muted">Time between two model calls, spent in the agent's own code and tools. Worked out from the gaps, not measured directly.</p>}
    {sent && <div className={rows.length ? 'mt-3' : ''}><p className="label">{step ? 'last message sent' : 'went in'}</p><p className="mt-1 text-[15px] leading-relaxed whitespace-pre-wrap [overflow-wrap:anywhere]">{sent}</p></div>}
    {returned && <div className="mt-3"><p className="label">came back</p><p className="mt-1 text-[15px] leading-relaxed whitespace-pre-wrap [overflow-wrap:anywhere]">{returned}</p></div>}
    {!rows.length && !sent && !returned && span.type !== 'chain' && <p className="text-[15px] text-muted">Only the name, the outcome and the time were recorded for this step.</p>}
  </div>
}

type Row = { span: Span; depth: number }
function ordered(spans: Span[]): Row[] {
  const known = new Set(spans.map(span => span.span_id))
  const children = new Map<string, Span[]>()
  for (const span of spans) { const key = span.parent_span_id && known.has(span.parent_span_id) ? span.parent_span_id : ''; children.set(key, [...(children.get(key) || []), span]) }
  const rows: Row[] = []
  const walk = (key: string, depth: number) => { for (const span of children.get(key) || []) { rows.push({ span, depth }); walk(span.span_id, depth + 1) } }
  walk('', 0)
  return rows
}

/** The trace named in the address, as a window over the page: every step on the left, the chosen step's details on the right. */
export function TracePanel({ importId }: { importId: string }) {
  const [params, setParams] = useSearchParams()
  const [copied, setCopied] = useState(false)
  const [picked, setPicked] = useState<string | null>(null)
  const id = params.get('trace')
  const trace = useQuery({ queryKey: ['trace', importId, id], enabled: Boolean(id), staleTime: 60000,
    queryFn: ({ signal }) => api<TraceContext>(`/github/imports/${encodeURIComponent(importId)}/traces/${encodeURIComponent(id!)}`, { signal }) })
  const close = () => { const next = new URLSearchParams(params); next.delete('trace'); setParams(next) }
  // Escape closes it, and the page behind does not scroll while it is open.
  useEffect(() => {
    if (!id) return
    const key = (event: KeyboardEvent) => { if (event.key === 'Escape') close() }
    const before = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    holdScroll(true)
    window.addEventListener('keydown', key)
    return () => { document.body.style.overflow = before; holdScroll(false); window.removeEventListener('keydown', key) }
  }, [id])
  useEffect(() => setPicked(null), [id])
  if (!id) return null
  const data = trace.data
  const summary = data?.hansa?.summary
  const steps = data?.hansa?.steps || {}, tools = data?.hansa?.tools || {}
  const rows = data ? ordered(data.spans) : []
  const longest = Math.max(1, ...rows.map(row => row.span.duration_ms || 0))
  // Open on the first model call, since that is where the figures are.
  const chosen = rows.find(row => row.span.span_id === picked) || rows.find(row => steps[row.span.span_id]) || rows[0]
  const stats = data ? [['time', seconds(data.latency_ms)], ['cost', money(summary?.cost_usd)], ['model calls', data.llm_calls ?? '—'], ['tool calls', data.tool_calls ?? '—'], ['tokens in', data.prompt_tokens?.toLocaleString() ?? '—'], ['tokens out', data.completion_tokens?.toLocaleString() ?? '—']] : []
  return <div className="trace-backdrop fixed inset-0 z-50 grid place-items-center bg-black/55 p-0 sm:p-6" onClick={close}>
    <aside role="dialog" aria-modal="true" aria-label="Trace" onClick={event => event.stopPropagation()} className="trace-panel flex h-full w-full max-w-[1180px] flex-col overflow-hidden bg-paper sm:h-[min(860px,92vh)] sm:rounded-[16px] sm:border sm:border-line">
      <header className="flex items-start justify-between gap-3 border-b border-line bg-surface px-5 py-4 sm:px-6">
        <div className="min-w-0"><p className="label">trace · {data?.hansa?.kind || 'run'}</p>
          <h2 className="mt-0.5 text-[22px] leading-tight font-semibold tracking-tight">{data ? data.name.replace(/^hansa-/, '').replaceAll('-', ' ') + ' run' : 'Loading…'}</h2>
          <p className="mt-1 font-mono text-[12.5px] break-all text-muted">{id}</p></div>
        <div className="flex shrink-0 items-center gap-2">
          <button className="chip hidden min-h-10 bg-surface hover:bg-blue-soft sm:inline-flex" onClick={() => { void navigator.clipboard.writeText(location.href).then(() => { setCopied(true); setTimeout(() => setCopied(false), 1600) }).catch(() => undefined) }}><Link2 size={14} aria-hidden="true" /> {copied ? 'link copied' : 'copy link'}</button>
          <button aria-label="Close trace" onClick={close} className="grid size-11 place-items-center rounded-control border border-line hover:bg-wash"><X size={20} aria-hidden="true" /></button></div>
      </header>
      {trace.isPending ? <p role="status" className="p-6">Fetching the trace…</p>
        : trace.isError ? <div role="alert" className="p-6"><p className="font-semibold">This trace could not be read back.</p><p className="mt-1 text-muted">{trace.error instanceof ApiError ? trace.error.message : 'Check your connection.'}</p><button className="button-secondary mt-4" onClick={() => void trace.refetch()}>Try again</button></div>
        : data && <>
          <div className="border-b border-line bg-surface px-5 py-4 sm:px-6">
            <dl className="grid grid-cols-3 gap-x-4 gap-y-3 sm:grid-cols-6">{stats.map(([label, value]) => <div key={label as string}><dt className="label">{label}</dt><dd className="mt-0.5 text-[19px] font-semibold tabular-nums">{value}</dd></div>)}</dl>
            {summary?.prompt_chars ? <p className="mt-3 rounded-control bg-waste-soft px-3 py-2 text-[14px]"><b>{share(summary.repeated_chars || 0, summary.prompt_chars)}% of what this run sent, it had already sent</b> on the call before ({(summary.repeated_chars || 0).toLocaleString()} of {summary.prompt_chars.toLocaleString()} characters).{summary.task_id ? ` Task ${summary.task_id}.` : ''}{summary.stop_reason ? ` Ended: ${summary.stop_reason.replaceAll('_', ' ')}.` : ''}</p> : null}
            {data.has_error && <p className="notice-problem mt-3 text-[14px] font-medium">An error was recorded in this trace.</p>}
            {data.detections.length > 0 && <ul className="mt-3 grid gap-2">{data.detections.map((item, index) =>
              <li key={index} className="rounded-control bg-waste-soft px-3 py-2 text-[14px]">{String(item.title || item.name || item.type || 'Detection')}{item.description || item.message ? <span className="block text-muted">{String(item.description || item.message)}</span> : null}</li>)}</ul>}
          </div>
          <div className="grid min-h-0 flex-1 lg:grid-cols-[minmax(0,5fr)_minmax(0,6fr)]">
            <div className="min-h-0 overflow-y-auto overscroll-contain border-line lg:border-r">
              <p className="label sticky top-0 z-10 border-b border-line bg-paper px-5 py-2.5 sm:px-6">{rows.length} steps, in order · bar = how long each took</p>
              <ol>{rows.map(({ span, depth }) => { const [label, tone] = kinds[span.type] || [span.type.replaceAll('_', ' '), 'bg-surface text-ink']
                const step = steps[span.span_id], on = chosen?.span.span_id === span.span_id
                return <li key={span.span_id} className="border-b border-line">
                  <button type="button" aria-pressed={on} onClick={() => setPicked(span.span_id)} className={`trace-step grid w-full grid-cols-[minmax(0,1fr)_60px] items-center gap-3 py-2.5 pr-5 text-left sm:pr-6 ${on ? 'is-on' : ''}`} style={{ paddingLeft: 20 + Math.min(depth, 4) * 14 }}>
                    <span className="min-w-0"><span className="flex items-center gap-2 text-[14px]"><span className={`chip px-2 py-0 text-[13px] ${tone}`}>{label}</span><span className="truncate font-mono text-[13px]">{tools[span.span_id]?.name || span.name}</span>
                      {span.status !== 'SUCCESS' && <span className="chip chip-waste px-2 py-0 text-[13px]">{span.status.toLowerCase()}</span>}</span>
                      {/* The figures that matter, readable without opening the step. */}
                      {step && <span className="mt-1 block tabular text-[13px] text-muted">{step.tokens_in?.toLocaleString() ?? '—'} in · {step.tokens_out?.toLocaleString() ?? '—'} out · {money(step.cost_usd)}
                        {step.repeated_chars > 0 && <span className="font-semibold text-waste"> · {share(step.repeated_chars, step.prompt_chars)}% already sent</span>}</span>}
                      <span aria-hidden="true" className="mt-1.5 block h-1.5 rounded-full bg-wash"><span className={`block h-full rounded-full ${span.type === 'llm' ? 'bg-ink' : 'bg-muted/60'}`} style={{ width: `${Math.max(1.5, (span.duration_ms || 0) / longest * 100)}%` }} /></span></span>
                    <span className="flex items-center justify-end gap-1 tabular text-[13px] tabular-nums text-muted">{seconds(span.duration_ms)}<ChevronRight size={14} aria-hidden="true" className={`shrink-0 transition-transform lg:rotate-0 ${on ? 'rotate-90' : ''}`} /></span></button>
                  {/* On a narrow screen the details open under the step; on a wide one they fill the right-hand pane. */}
                  {on && <div className="px-5 pb-4 lg:hidden"><Facts span={span} step={step} tool={tools[span.span_id]} /></div>}</li> })}</ol>
              {data.returned_span_count < data.span_count && <p className="px-5 py-3 tabular text-[14px] text-muted sm:px-6">Showing {data.returned_span_count} of {data.span_count} steps.</p>}
            </div>
            <div className="hidden min-h-0 overflow-y-auto overscroll-contain bg-surface px-6 py-5 lg:block">
              {chosen && <div key={chosen.span.span_id} className="trace-detail"><p className="label">step {rows.indexOf(chosen) + 1} of {rows.length} · {seconds(chosen.span.duration_ms)}</p>
                <h3 className="mt-1 text-[19px] leading-snug font-semibold [overflow-wrap:anywhere]">{tools[chosen.span.span_id]?.name || chosen.span.name}</h3>
                <Facts span={chosen.span} step={steps[chosen.span.span_id]} tool={tools[chosen.span.span_id]} /></div>}
              <p className="mt-6 text-[13px] leading-relaxed text-muted">Steps and timing are read back from Neatlogs. Tokens, cost, request sizes and tool inputs and outputs come from Hansa's own record of the run. Recorded {new Date(data.created_at).toLocaleString()}.</p>
            </div>
          </div>
        </>}
    </aside>
  </div>
}
