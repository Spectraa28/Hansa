import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import { ExternalLink, Link2, X } from 'lucide-react'
import { api, ApiError } from './api'

type Span = { span_id: string; name: string; type: string; status: string; duration_ms: number | null; parent_span_id: string | null }
type TraceContext = {
  trace_id: string; name: string; status: string; latency_ms: number | null; llm_calls: number | null; tool_calls: number | null
  prompt_tokens: number | null; completion_tokens: number | null; has_error: boolean; span_count: number; returned_span_count: number
  created_at: string; spans: Span[]; detections: Record<string, unknown>[]
}
export type TraceRef = { status?: string; trace_id?: string; trace_ids?: string[]; reason?: string } | null | undefined

// Where a trace opens on Neatlogs itself, e.g. https://…/traces/{id}. Set VITE_NEATLOGS_TRACE_URL to show the link.
const template: string | undefined = import.meta.env.VITE_NEATLOGS_TRACE_URL
const kinds: Record<string, [string, string]> = { llm: ['model', 'bg-ink text-paper'], tool_call: ['tool', 'bg-waste text-ink'], chain: ['code', 'bg-wash text-ink'] }
const seconds = (ms: number | null) => ms == null ? '—' : ms >= 1000 ? `${(ms / 1000).toFixed(ms >= 10000 ? 0 : 1)} s` : `${Math.round(ms)} ms`
const idsOf = (trace: TraceRef) => [...new Set([...(trace?.trace_ids || []), ...(trace?.trace_id ? [trace.trace_id] : [])])].filter(Boolean)

/** Chips that open a run's trace. The trace ID goes in the address, so the link can be shared. */
export function TraceLinks({ ids, trace, label = 'trace' }: { ids?: (string | null)[]; trace?: TraceRef; label?: string }) {
  const [params, setParams] = useSearchParams()
  const all = ids ? ids.filter((id): id is string => Boolean(id)) : idsOf(trace)
  if (!all.length) return trace?.reason ? <span className="chip chip-quiet" title={trace.reason}>trace not delivered</span> : null
  const open = (id: string) => { const next = new URLSearchParams(params); next.set('trace', id); setParams(next) }
  return <span className="inline-flex flex-wrap gap-1.5">{all.map((id, index) => <button key={id} type="button" onClick={() => open(id)}
    className={`chip min-h-8 ${params.get('trace') === id ? 'bg-ink text-paper' : 'bg-surface hover:bg-waste'}`}>{label}{all.length > 1 ? ` ${index + 1}` : ''} ↗</button>)}</span>
}

function Tree({ spans }: { spans: Span[] }) {
  const known = new Set(spans.map(span => span.span_id))
  const children = new Map<string, Span[]>()
  for (const span of spans) { const key = span.parent_span_id && known.has(span.parent_span_id) ? span.parent_span_id : ''; children.set(key, [...(children.get(key) || []), span]) }
  const longest = Math.max(1, ...spans.map(span => span.duration_ms || 0))
  const rows: { span: Span; depth: number }[] = []
  const walk = (key: string, depth: number) => { for (const span of children.get(key) || []) { rows.push({ span, depth }); walk(span.span_id, depth + 1) } }
  walk('', 0)
  return <ol className="divide-y divide-line">{rows.map(({ span, depth }) => { const [label, tone] = kinds[span.type] || [span.type.replaceAll('_', ' '), 'bg-surface text-ink']
    return <li key={span.span_id} className="grid grid-cols-[minmax(0,1fr)_64px] items-center gap-3 py-2.5" style={{ paddingLeft: Math.min(depth, 4) * 16 }}>
      <div className="min-w-0"><p className="flex items-center gap-2 text-[14px]"><span className={`chip px-2 py-0 text-[11px] ${tone}`}>{label}</span><span className="truncate font-mono text-[13px]">{span.name}</span>
        {span.status !== 'SUCCESS' && <span className="chip chip-waste px-2 py-0 text-[11px]">{span.status.toLowerCase()}</span>}</p>
        <div aria-hidden="true" className="mt-1.5 h-2 rounded-full bg-wash"><div className={`h-full rounded-full ${span.type === 'llm' ? 'bg-ink' : span.type === 'tool_call' || span.type === 'chain' ? 'bg-waste' : 'bg-muted/50'}`} style={{ width: `${Math.max(1.5, (span.duration_ms || 0) / longest * 100)}%` }} /></div></div>
      <span className="text-right font-mono text-[12px] tabular-nums text-muted">{seconds(span.duration_ms)}</span></li> })}</ol>
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
  const stats = data ? [['time', seconds(data.latency_ms)], ['model calls', data.llm_calls ?? '—'], ['tool calls', data.tool_calls ?? '—'], ['tokens in', data.prompt_tokens?.toLocaleString() ?? '—'], ['tokens out', data.completion_tokens?.toLocaleString() ?? '—']] : []
  return <div className="fixed inset-0 z-50 flex justify-end bg-ink/40" onClick={close}>
    <aside role="dialog" aria-modal="true" aria-label="Trace" onClick={event => event.stopPropagation()} className="flex h-full w-full max-w-[640px] flex-col border-l-[3px] border-ink bg-paper">
      <header className="flex items-start justify-between gap-3 border-b-[3px] border-ink bg-ink px-5 py-4 text-paper">
        <div className="min-w-0"><p className="font-mono text-[12px] uppercase tracking-[.08em] text-paper/70">trace · read back from Neatlogs</p>
          <h2 className="mt-1 font-display text-[26px] leading-none font-[780] tracking-[-.03em]">{data ? data.name.replace(/^hansa-/, '').replaceAll('-', ' ') + ' run' : 'Loading…'}</h2>
          <p className="mt-2 font-mono text-[12px] break-all text-paper/70">{id}</p></div>
        <button aria-label="Close trace" onClick={close} className="grid size-11 shrink-0 place-items-center rounded-control border-2 border-paper hover:bg-waste hover:text-ink"><X size={20} aria-hidden="true" /></button>
      </header>
      <div className="flex flex-wrap gap-2 border-b-2 border-ink px-5 py-3">
        <button className="chip min-h-9 bg-surface hover:bg-waste" onClick={() => { void navigator.clipboard.writeText(location.href).then(() => { setCopied(true); setTimeout(() => setCopied(false), 1600) }).catch(() => undefined) }}><Link2 size={14} aria-hidden="true" /> {copied ? 'link copied' : 'copy link to this trace'}</button>
        {template && <a href={template.replace('{id}', encodeURIComponent(id))} target="_blank" rel="noopener noreferrer" className="chip min-h-9 bg-waste hover:bg-surface"><ExternalLink size={14} aria-hidden="true" /> open in Neatlogs</a>}
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-5 py-5">
        {trace.isPending ? <p role="status">Fetching the trace from Neatlogs…</p>
          : trace.isError ? <div role="alert"><p className="font-semibold">Neatlogs didn't return this trace.</p><p className="mt-1 text-muted">{trace.error instanceof ApiError ? trace.error.message : 'Check your connection.'}</p><button className="button-secondary mt-4" onClick={() => void trace.refetch()}>Try again</button></div>
          : data && <>
            <dl className="grid grid-cols-3 gap-x-4 gap-y-4 sm:grid-cols-5">{stats.map(([label, value]) => <div key={label as string}><dt className="label">{label}</dt><dd className="mt-1 font-display text-[22px] font-[760] tracking-[-.02em] tabular-nums">{value}</dd></div>)}</dl>
            {data.has_error && <p className="mt-4 rounded-control border-2 border-ink bg-waste px-3 py-2 text-[14px] font-medium">Neatlogs marked an error in this trace.</p>}
            {data.detections.length > 0 && <section className="mt-6"><h3 className="label">flagged by Neatlogs</h3><ul className="mt-2 grid gap-2">{data.detections.map((item, index) =>
              <li key={index} className="rounded-control border-2 border-ink bg-waste-soft px-3 py-2 text-[14px]">{String(item.title || item.name || item.type || 'Detection')}{item.description || item.message ? <span className="block text-[13px] text-muted">{String(item.description || item.message)}</span> : null}</li>)}</ul></section>}
            <section className="mt-7"><h3 className="label">every step, in order · bar = how long it took</h3><div className="mt-2"><Tree spans={data.spans} /></div>
              {data.returned_span_count < data.span_count && <p className="mt-3 font-mono text-[12px] text-muted">Showing {data.returned_span_count} of {data.span_count} steps.</p>}</section>
            <p className="mt-6 font-mono text-[12px] leading-relaxed text-muted">Hansa sends Neatlogs the timing, size and outcome of each call. Recorded {new Date(data.created_at).toLocaleString()}.</p>
          </>}
      </div>
    </aside>
  </div>
}
