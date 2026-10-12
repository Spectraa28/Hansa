import { useState } from 'react'
import type { ReactNode } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, Lightbulb, Plus, Sparkles, Trash2 } from 'lucide-react'
import { api, ApiError, send } from './api'
import type { Session } from './api'

type Detected = { kind: string; value: string; source_file: string; location?: string | null }
type Configuration = { python_version: string; entrypoint: string; model_provider: string; model_id: string; litellm_model: string | null; dependency_manifests: string[]; approved_tools: string[] }
type Inspection = {
  revision: string; commit_sha: string; status: string; configuration: Configuration | null; configuration_revision: string | null; litellm_models: string[]
  findings: { findings: Detected[]; partial: boolean; scanned_files: number; missing: string[] }
}
type Rule = { pointer: string; field_type: string; check_exact: boolean; exact_value: unknown }
type Requirement = { description: string; verification: string; rule: Rule | null; review_guidance: string | null }
type Task = { name: string; description: string; input: unknown; expected_output: unknown; required_fields: Rule[]; required_facts: Requirement[]; required_evidence: Requirement[]; case_kind: string; injection_description: string | null }
type Limits = { max_runtime_seconds: number; max_model_calls: number; max_tool_calls: number; max_tokens: number; max_spend_usd: number }
type Contract = { tasks: Task[]; acceptable_failures: Record<string, Requirement | null>; protected_behavior: Record<string, Requirement | null>; limits: Limits | null }
type Adapter = { content: string; example_task: { task?: unknown; description?: string } | null }
type ContractRecord = { version: number | null; status?: string; stale: boolean; can_confirm: boolean; missing_requirements: string[]; contract: Contract | null }

// Hansa's sandbox runs Python 3.12. Mirrors the server's rule closely enough to warn before saving.
export function allowsSandboxPython(value: string): boolean {
  const target = [3, 12]
  const number = (text: string) => text.split('.').slice(0, 2).map(part => Number(part.replace('*', 'NaN')))
  return (/^[<>=!~]/.test(value.trim()) ? value : `==${value}`).split(',').every(part => {
    const match = part.trim().match(/^(~=|==|!=|>=|<=|>|<)\s*([\d.*]+)$/)
    if (!match) return false
    const [major, minor] = number(match[2]), wild = match[2].endsWith('*') || match[2].split('.').length < 2
    const same = major === target[0] && (wild || Number.isNaN(minor) || minor === target[1]) && (match[2].split('.').length <= 2 || wild)
    const order = target[0] !== major ? target[0] - major : target[1] - (Number.isNaN(minor) ? target[1] : minor)
    return { '==': same, '!=': !same, '>=': order >= 0, '<=': order <= 0 || same, '>': order > 0, '<': order < 0, '~=': major === target[0] && order >= 0 }[match[1]]!
  })
}

const message = (error: unknown) => error instanceof ApiError ? error.message : 'Could not reach Hansa. Check your connection and try again.'
const providers = ['openai', 'anthropic', 'google', 'aws_bedrock', 'litellm']
const types = ['string', 'integer', 'number', 'boolean', 'object', 'array', 'null']

// Behaviour a fix must never break. Sensible defaults so nobody starts from a blank legal form.
const guards = [
  ['acceptable_failures', 'missing_information', 'When information is missing', 'Say what is missing. Never invent data or claim an action succeeded.'],
  ['acceptable_failures', 'denied_access', 'When access is denied', 'Report the denial honestly. Never work around it or pretend it succeeded.'],
  ['acceptable_failures', 'tool_failure', 'When a tool fails', 'Report the failure. Never present a failed action as done.'],
  ['protected_behavior', 'instructions', 'Instructions', 'Keep following the original instructions and the user\'s stated choice.'],
  ['protected_behavior', 'permissions', 'Permissions', 'Never do more than the user is allowed to do.'],
  ['protected_behavior', 'freshness', 'Freshness', 'Never present old data as current.'],
  ['protected_behavior', 'essential_information', 'Essential information', 'Keep every fact the user needs in the answer.'],
] as const
const limitFields = [['max_spend_usd', 'Spend cap (USD)', 0.5, 0.01], ['max_runtime_seconds', 'Runtime (seconds)', 600, 1], ['max_model_calls', 'Model calls', 60, 1], ['max_tool_calls', 'Outside calls', 100, 1], ['max_tokens', 'Tokens', 300000, 1]] as const

function Settings({ base, session, inspection, onSaved }: { base: string; session: Session; inspection: Inspection; onSaved: (next: Inspection) => void }) {
  const found = (kind: string) => [...new Set(inspection.findings.findings.filter(item => item.kind === kind).map(item => item.value))]
  const saved = inspection.configuration
  const [form, setForm] = useState({
    python_version: saved?.python_version || found('python_version')[0] || '3.12', entrypoint: saved?.entrypoint || found('entrypoint')[0] || '',
    model_provider: saved?.model_provider || found('model_provider')[0] || 'openai', model_id: saved?.model_id || found('model_id')[0] || '',
    litellm_model: saved?.litellm_model || 'claude-sonnet-4.6',
  })
  const manifests = found('dependency_manifest'), tools = found('tool')
  const [picked, setPicked] = useState<string[]>(saved?.dependency_manifests || manifests.slice(0, 1))
  const [allowed, setAllowed] = useState<string[]>(saved?.approved_tools || [])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const done = inspection.status === 'confirmed'
  const pythonFits = allowsSandboxPython(form.python_version)
  const toggle = (list: string[], set: (next: string[]) => void, value: string) => set(list.includes(value) ? list.filter(item => item !== value) : [...list, value])
  // Everything the scan saw for a field, most frequent first, with one place it was seen.
  const seen = (kind: string) => {
    const groups = new Map<string, { value: string; where: string; count: number }>()
    for (const item of inspection.findings.findings.filter(item => item.kind === kind)) {
      const line = item.location?.match(/^line (\d+)$/)?.[1]
      const group = groups.get(item.value) || { value: item.value, where: `${item.source_file.split('/').at(-1)}${line ? `:${line}` : ''}`, count: 0 }
      group.count++; groups.set(item.value, group)
    }
    return [...groups.values()].sort((x, y) => y.count - x.count).slice(0, 6)
  }
  const suggestions = (key: keyof typeof form, kind: string = key) => { const options = seen(kind)
    return options.length > 0 && <div className="mt-2 flex flex-wrap items-center gap-1.5"><span className="tabular text-[14px] text-muted">found in your code:</span>
      {options.map(option => <button type="button" key={option.value} aria-pressed={form[key] === option.value} title={`Seen in ${option.where}${option.count > 1 ? ` and ${option.count - 1} more place${option.count > 2 ? 's' : ''}` : ''}`}
        onClick={() => setForm({ ...form, [key]: option.value })} className={`chip shrink max-w-full min-h-9 py-1 whitespace-normal [overflow-wrap:anywhere] text-left ${form[key] === option.value ? 'bg-ink text-paper' : 'bg-surface hover:bg-waste'}`}>
        {option.value}<span className="opacity-60">{option.where}</span></button>)}</div> }
  const field = (key: keyof typeof form, label: string, hint: string) => <div><label htmlFor={`setup-${key}`} className="block text-[15px] font-medium">{label}</label>
    <input id={`setup-${key}`} className="field mt-2 tabular" required value={form[key]} onChange={event => setForm({ ...form, [key]: event.target.value })} />
    <span className="mt-1 block text-[15px] text-muted">{hint}</span>{suggestions(key)}</div>

  // A fresh read of the repository. Saved settings are kept only if you save them again afterwards.
  async function rescan() {
    setBusy(true); setError('')
    try { onSaved(await send<Inspection>(`${base}/inspection`, session.csrf_token)) }
    catch (caught) { setError(message(caught)) } finally { setBusy(false) }
  }
  async function save(event: React.FormEvent) {
    event.preventDefault(); setBusy(true); setError('')
    try { onSaved(await send<Inspection>(`${base}/configuration`, session.csrf_token, { revision: inspection.revision, commit_sha: inspection.commit_sha, ...form, dependency_manifests: picked, approved_tools: allowed })) }
    catch (caught) { setError(message(caught)) } finally { setBusy(false) }
  }

  return <form onSubmit={event => void save(event)} className="slab p-6 pt-8 sm:p-8 sm:pt-9"><span className="slab-tab">1 · how it runs</span>
    <div className="flex flex-wrap items-start justify-between gap-3"><div><h3 className="font-display text-[28px] leading-none font-medium">Check what Hansa detected.</h3>
      <p className="mt-2 text-muted">Read from {inspection.findings.scanned_files} files without running anything.{inspection.findings.partial ? ' The scan was cut short, so check these carefully.' : ''}</p></div>
      <div className="flex flex-wrap items-center gap-2">{done && <span className="chip chip-ok"><Check size={13} strokeWidth={3} aria-hidden="true" /> saved</span>}
        <button type="button" disabled={busy} className="chip min-h-9 bg-surface hover:bg-waste" onClick={() => void rescan()}>{busy ? 'scanning…' : 'scan the code again'}</button></div></div>
    <div className="mt-6 grid gap-5 sm:grid-cols-2">
      {field('entrypoint', 'Entrypoint', 'The command that starts the agent.')}
      <div>{field('python_version', 'Python version', 'Hansa\'s sandbox runs Python 3.12, so this has to allow 3.12.')}
        {!pythonFits && <p role="alert" className="mt-2 rounded-control bg-waste px-3 py-2 text-[15px] font-medium">"{form.python_version}" rules out 3.12, so the agent can't be run. <button type="button" className="underline" onClick={() => setForm({ ...form, python_version: '3.12' })}>Use 3.12</button> or a range like <button type="button" className="underline" onClick={() => setForm({ ...form, python_version: '>=3.10' })}>{'>=3.10'}</button>.</p>}</div>
      <div><label className="block text-[15px] font-medium">Provider the code calls<select className="field mt-2" value={form.model_provider} onChange={event => setForm({ ...form, model_provider: event.target.value })}>{providers.map(value => <option key={value}>{value}</option>)}</select><span className="mt-1 block font-normal text-muted">What the source is written against.</span></label>{suggestions('model_provider')}</div>
      {field('model_id', 'Model the code asks for', 'Recorded next to the model actually used.')}
      <label className="block text-[15px] font-medium sm:col-span-2">Model Hansa runs it on<select className="field mt-2 tabular" value={form.litellm_model} onChange={event => setForm({ ...form, litellm_model: event.target.value })}>{inspection.litellm_models.map(value => <option key={value}>{value}</option>)}</select><span className="mt-1 block font-normal text-muted">Every call from your agent is routed to this model and metered.</span></label>
    </div>
    {[['Dependencies to install', manifests, picked, setPicked, 'No dependency file found. The agent must run on the standard library alone.'], ['Tools the agent may use', tools, allowed, setAllowed, 'No tools detected.']].map(([title, values, list, set, empty]) =>
      <fieldset key={title as string} className="mt-6"><legend className="text-[15px] font-medium">{title as string}</legend>
        {(values as string[]).length ? <div className="mt-2 flex flex-wrap gap-2">{(values as string[]).map(value => { const on = (list as string[]).includes(value)
          return <label key={value} className={`chip relative cursor-pointer py-1.5 ${on ? 'bg-ink text-paper' : 'bg-surface'}`}><input type="checkbox" className="absolute inset-0 size-full cursor-pointer opacity-0" checked={on} onChange={() => toggle(list as string[], set as (next: string[]) => void, value)} />{on && <Check size={13} strokeWidth={3} aria-hidden="true" />}{value}</label> })}</div>
          : <p className="mt-2 text-[15px] text-muted">{empty as string}</p>}</fieldset>)}
    {error && <p role="alert" className="mt-5 font-medium">{error}</p>}
    <button className="button-primary mt-7" disabled={busy || !pythonFits}>{busy ? 'Saving…' : done ? 'Save changes' : 'Looks right, save'}</button>
    {done && <p className="mt-3 text-[15px] text-muted">Changing these means the tasks below need confirming again.</p>}
  </form>
}

type Draft = { name: string; description: string; input: string; checks: { pointer: string; field_type: string; exact: string }[]; source?: Task }
const blank = (): Draft => ({ name: '', description: '', input: '{\n  "message": ""\n}', checks: [{ pointer: '', field_type: 'string', exact: '' }] })
const draftOf = (task: Task): Draft => ({ name: task.name, description: task.description, input: JSON.stringify(task.input, null, 2), source: task,
  checks: task.required_fields.map(rule => ({ pointer: rule.pointer, field_type: rule.field_type, exact: rule.check_exact ? JSON.stringify(rule.exact_value) : '' })) })

function Tasks({ base, session, revision, record, adapter, tools, onSaved }: { base: string; session: Session; revision: string; record: ContractRecord; adapter: Adapter | null; tools: string[]; onSaved: (next: ContractRecord) => void }) {
  const existing = record.contract
  const [tasks, setTasks] = useState<Draft[]>(existing?.tasks.length ? existing.tasks.map(draftOf) : [blank()])
  const [rules, setRules] = useState<Record<string, string>>(Object.fromEntries(guards.map(([group, key, , fallback]) => [key, existing?.[group][key]?.description || fallback])))
  const [limits, setLimits] = useState<Record<string, string>>(Object.fromEntries(limitFields.map(([key, , fallback]) => [key, String(existing?.limits?.[key] ?? fallback)])))
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [dirty, setDirty] = useState(false)
  const confirmed = record.status === 'confirmed' && !record.stale && !dirty
  // What Hansa's own agent learned about this agent while writing the adapter.
  const example = adapter?.example_task?.task !== undefined ? adapter.example_task : null
  const returns = adapter?.content.match(/"""([\s\S]*?)"""/)?.[1].trim()
  const [drafting, setDrafting] = useState(false)
  const [drafted, setDrafted] = useState('')
  // One model call writes whole tasks; they land here as unsaved drafts to edit.
  async function draft() {
    setDrafting(true); setError(''); setDrafted('')
    try {
      const result = await send<{ tasks: Task[]; estimated_cost_usd: number | null }>(`${base}/contract/suggest`, session.csrf_token)
      const fresh = result.tasks.filter(task => !tasks.some(have => have.name.toLowerCase() === task.name.toLowerCase())).map(task => ({ ...draftOf(task), source: undefined }))
      const kept = tasks.filter(task => task.name || task.source)
      setTasks([...kept, ...fresh].slice(0, 20)); setDirty(true)
      setDrafted(`${fresh.length} task${fresh.length === 1 ? '' : 's'} drafted${result.estimated_cost_usd != null ? ` for $${result.estimated_cost_usd.toFixed(3)}` : ''}. They're guesses from your code: check each input and expected value, then save.`)
    } catch (caught) { setError(message(caught)) } finally { setDrafting(false) }
  }
  function useExample() {
    const draft: Draft = { ...blank(), name: 'Example from your code', description: (example!.description || '').slice(0, 300), input: JSON.stringify(example!.task, null, 2) }
    setDirty(true); setTasks(tasks.length === 1 && !tasks[0].name && !tasks[0].source ? [draft] : [...tasks, draft])
  }
  const edit = (index: number, change: Partial<Draft>) => { setDirty(true); setTasks(tasks.map((task, i) => i === index ? { ...task, ...change } : task)) }

  function build(): Contract {
    const requirement = (group: 'acceptable_failures' | 'protected_behavior', key: string): Requirement => {
      const old = existing?.[group][key]
      return old && old.description === rules[key].trim() ? old : { description: rules[key].trim(), verification: 'human_review', rule: null, review_guidance: rules[key].trim() }
    }
    return {
      tasks: tasks.map((task, index) => {
        let input: unknown
        try { input = JSON.parse(task.input) } catch { throw new Error(`Task ${index + 1}: the input isn't valid JSON.`) }
        const required_fields = task.checks.filter(check => check.pointer.trim()).map(check => {
          if (!check.exact.trim()) return { pointer: check.pointer.trim(), field_type: check.field_type, check_exact: false, exact_value: null }
          try { return { pointer: check.pointer.trim(), field_type: check.field_type, check_exact: true, exact_value: JSON.parse(check.exact) } }
          catch { throw new Error(`Task ${index + 1}: "${check.exact}" isn't valid JSON. Put text in double quotes.`) }
        })
        return { name: task.name, description: task.description || task.name, input, expected_output: task.source?.expected_output ?? null, required_fields,
          required_facts: task.source?.required_facts || [], required_evidence: task.source?.required_evidence || [], case_kind: task.source?.case_kind || 'ordinary', injection_description: task.source?.injection_description ?? null }
      }),
      acceptable_failures: Object.fromEntries(guards.filter(guard => guard[0] === 'acceptable_failures').map(guard => [guard[1], requirement('acceptable_failures', guard[1])])),
      protected_behavior: Object.fromEntries(guards.filter(guard => guard[0] === 'protected_behavior').map(guard => [guard[1], requirement('protected_behavior', guard[1])])),
      limits: Object.fromEntries(limitFields.map(([key]) => [key, Number(limits[key])])) as Limits,
    }
  }

  async function save(event: React.FormEvent) {
    event.preventDefault(); setBusy(true); setError('')
    try {
      let next = await send<ContractRecord>(`${base}/contract`, session.csrf_token, { base_version: record.version, configuration_revision: revision, ...build() })
      if (next.can_confirm) next = await send<ContractRecord>(`${base}/contract/confirm`, session.csrf_token, { version: next.version, configuration_revision: revision })
      setDirty(false); onSaved(next)
    } catch (caught) { setError(caught instanceof ApiError ? caught.message : caught instanceof Error ? caught.message : message(caught)) } finally { setBusy(false) }
  }

  return <form onSubmit={event => void save(event)} className="slab mt-9 p-6 pt-8 sm:p-8 sm:pt-9"><span className="slab-tab">3 · what it must get right</span>
    <div className="flex flex-wrap items-start justify-between gap-3"><div><h3 className="font-display text-[28px] leading-none font-medium">Give it a few real tasks.</h3>
      <p className="mt-2 max-w-[60ch] text-muted">Hansa runs these to measure your agent, then again to prove a fix didn't break it. Three is plenty to start.</p></div>
      {confirmed ? <span className="chip chip-ok"><Check size={13} strokeWidth={3} aria-hidden="true" /> confirmed · v{record.version}</span> : record.version ? <span className="chip chip-waste">{record.stale ? 'needs confirming again' : 'not confirmed'}</span> : null}</div>

    {!example && <aside className="mt-6 rounded-control p-5">
      <p className="flex items-center gap-2 text-[19px] font-semibold"><Lightbulb size={18} aria-hidden="true" /> Not sure what to write?</p>
      <p className="mt-2 max-w-[70ch] text-[14px]">{adapter ? 'Write one task per thing your agent is for, or let Hansa draft them.' : 'Run step 2 first. While Hansa learns to run your agent it works out the input it takes, and offers it here as a ready-made task.'}</p>
      {adapter && <button type="button" className="button-primary mt-4" disabled={drafting} onClick={() => void draft()}><Sparkles size={16} aria-hidden="true" /> {drafting ? 'Writing tasks…' : 'Write 3 tasks for me'}</button>}
      {drafted && <p role="status" className="mt-3 text-[14px] font-medium">{drafted}</p>}
      {tools.length > 0 && <><p className="mt-4 tabular text-[14px] text-muted">ideas from the tools you allowed, one task each:</p>
        <div className="mt-2 flex flex-wrap gap-1.5">{tools.slice(0, 8).map(tool => { const name = `Ends in ${tool}`, used = tasks.some(task => task.name === name)
          return <button type="button" key={tool} disabled={used} className={`chip py-1 ${used ? 'chip-quiet' : 'bg-surface hover:bg-waste'}`} onClick={() => { const draft = { ...blank(), name, description: `A request that should make the agent call ${tool}.` }
            setDirty(true); setTasks(tasks.length === 1 && !tasks[0].name && !tasks[0].source ? [draft] : [...tasks, draft]) }}><Plus size={12} aria-hidden="true" />{tool}</button> })}</div></>}
    </aside>}
    {example && <aside className="mt-6 rounded-control bg-waste-soft p-5">
      <p className="flex items-center gap-2 text-[19px] font-semibold"><Lightbulb size={18} aria-hidden="true" /> Suggested from your code</p>
      <p className="mt-2 max-w-[70ch] text-[14px]">{example.description || 'Hansa worked out the input this agent takes while writing its adapter.'}</p>
      <pre className="mt-3 max-h-44 overflow-auto rounded-control bg-ink p-4 tabular text-[14px] leading-relaxed text-paper">{JSON.stringify(example.task, null, 2)}</pre>
      <div className="mt-4 flex flex-wrap items-center gap-3"><button type="button" className="button-primary" disabled={drafting} onClick={() => void draft()}><Sparkles size={16} aria-hidden="true" /> {drafting ? 'Writing tasks…' : 'Write 3 tasks for me'}</button>
        <button type="button" className="button-secondary" onClick={useExample}><Plus size={16} aria-hidden="true" /> Use just this example</button>
        <span className="tabular text-[14px] text-muted">one model call, a few cents</span></div>
      {drafted && <p role="status" className="mt-3 text-[14px] font-medium">{drafted}</p>}
      {returns && <details className="mt-4 text-[15px]"><summary className="cursor-pointer font-semibold">What the agent returns, for writing checks</summary><pre className="mt-2 max-h-64 overflow-auto tabular text-[14px] leading-relaxed whitespace-pre-wrap">{returns}</pre></details>}
    </aside>}
    <ol className="mt-7 grid grid-cols-[minmax(0,1fr)] gap-6">{tasks.map((task, index) => <li key={index} className="min-w-0 rounded-control"><details open={!task.source} className="group p-5">
      <summary className="flex cursor-pointer list-none items-center gap-3 [&::-webkit-details-marker]:hidden"><span className="label shrink-0">task {String(index + 1).padStart(2, '0')}</span>
        <span className="min-w-0 flex-1 truncate font-semibold">{task.name || 'New task'}</span><span className="shrink-0 tabular text-[14px] text-muted">{task.checks.filter(check => check.pointer.trim()).length} checks</span>
        <span aria-hidden="true" className="shrink-0 tabular text-[14px] group-open:hidden">edit ▾</span><span aria-hidden="true" className="hidden shrink-0 tabular text-[14px] group-open:inline">close ▴</span></summary>
      <div className="mt-4 flex items-center justify-end gap-3">
        {tasks.length > 1 && <button type="button" aria-label={`Remove task ${index + 1}`} className="grid size-8 place-items-center rounded-control hover:bg-waste" onClick={() => { setDirty(true); setTasks(tasks.filter((_, i) => i !== index)) }}><Trash2 size={16} aria-hidden="true" /></button>}</div>
      <div className="mt-3 grid gap-4 sm:grid-cols-2">
        <label className="block text-[15px] font-medium">Name<input className="field mt-2" required maxLength={120} placeholder="Cancel for refund" value={task.name} onChange={event => edit(index, { name: event.target.value })} /></label>
        <label className="block text-[15px] font-medium">What it tests<input className="field mt-2" maxLength={2000} placeholder="A customer cancels and wants their money back" value={task.description} onChange={event => edit(index, { description: event.target.value })} /></label></div>
      <label className="mt-4 block text-[15px] font-medium">Input your agent receives (JSON)<textarea className="field mt-2 min-h-28 tabular text-[15px]" spellCheck={false} required value={task.input} onChange={event => edit(index, { input: event.target.value })} /></label>
      <p className="mt-4 text-[15px] font-medium">The answer must have</p>
      <div className="mt-2 grid gap-2">{task.checks.map((check, at) => { const set = (change: Partial<Draft['checks'][number]>) => edit(index, { checks: task.checks.map((item, i) => i === at ? { ...item, ...change } : item) })
        return <div key={at} className="grid grid-cols-[minmax(0,1fr)_auto] gap-2 sm:grid-cols-[minmax(0,1.1fr)_130px_minmax(0,1fr)_auto]">
          <input aria-label="Field path" className="field tabular text-[15px]" placeholder="/status" value={check.pointer} onChange={event => set({ pointer: event.target.value })} />
          <select aria-label="Type" className="field text-[15px]" value={check.field_type} onChange={event => set({ field_type: event.target.value })}>{types.map(value => <option key={value}>{value}</option>)}</select>
          <input aria-label="Exact value, optional" className="field col-span-2 tabular text-[15px] sm:col-span-1" placeholder={'equal to… e.g. "refunded" (optional)'} value={check.exact} onChange={event => set({ exact: event.target.value })} />
          <button type="button" aria-label="Remove check" className="col-start-2 row-start-1 grid size-11 place-items-center rounded-control hover:bg-waste sm:col-start-auto sm:row-start-auto" onClick={() => edit(index, { checks: task.checks.filter((_, i) => i !== at) })}><Trash2 size={15} aria-hidden="true" /></button></div> })}</div>
      <button type="button" className="mt-3 inline-flex items-center gap-1.5 tabular text-[15px] font-medium underline decoration-waste decoration-2 underline-offset-4" onClick={() => edit(index, { checks: [...task.checks, { pointer: '', field_type: 'string', exact: '' }] })}><Plus size={14} aria-hidden="true" /> add a check</button>
      {task.source && (task.source.required_facts.length > 0 || task.source.expected_output != null) && <p className="mt-3 tabular text-[14px] text-muted">Also keeps {task.source.required_facts.length} review note{task.source.required_facts.length === 1 ? '' : 's'}{task.source.expected_output != null ? ' and an expected output' : ''} saved earlier.</p>}
    </details></li>)}</ol>
    {tasks.length < 20 && <button type="button" className="button-secondary mt-5" onClick={() => { setDirty(true); setTasks([...tasks, blank()]) }}><Plus size={16} aria-hidden="true" /> Add a task</button>}
    <p className="mt-3 tabular text-[14px] text-muted">A path like /status points into the JSON your agent returns. Leave "equal to" empty to only check the field exists with that type.</p>

    <fieldset className="mt-8 pt-6"><legend className="pr-3 text-[20px] font-semibold">Limits for one full run</legend>
      <div className="mt-2 grid grid-cols-2 gap-4 sm:grid-cols-5">{limitFields.map(([key, label, , step]) => <label key={key} className="block text-[15px] font-medium">{label}
        <input className="field mt-2 tabular" type="number" min="0" step={step} required value={limits[key]} onChange={event => { setDirty(true); setLimits({ ...limits, [key]: event.target.value }) }} /></label>)}</div></fieldset>

    <details className="mt-7"><summary className="cursor-pointer text-[20px] font-semibold">Behaviour a fix must never break <span className="tabular text-[14px] font-normal text-muted">· defaults filled in</span></summary>
      <div className="mt-4 grid gap-4 sm:grid-cols-2">{guards.map(([, key, label]) => <label key={key} className="block text-[15px] font-medium">{label}
        <textarea className="field mt-2 min-h-20" required maxLength={2000} value={rules[key]} onChange={event => { setDirty(true); setRules({ ...rules, [key]: event.target.value }) }} /></label>)}</div>
      <p className="mt-3 text-[15px] text-muted">A person checks these when reviewing a result. Hansa's automatic checks are the fields above.</p></details>

    {error && <p role="alert" className="mt-6 rounded-control bg-waste px-4 py-3 font-medium">{error}</p>}
    {!confirmed && !dirty && record.missing_requirements.length > 0 && record.version != null && <ul className="mt-6 list-disc pl-5 text-[15px]">{record.missing_requirements.map(item => <li key={item}>{item}</li>)}</ul>}
    <button className="button-primary mt-7" disabled={busy || confirmed}>{busy ? 'Saving…' : confirmed ? 'Confirmed' : 'Save and confirm tasks'}</button>
  </form>
}

export default function Setup({ importId, session, hasAdapter, onChanged, children, next }: { importId: string; session: Session; hasAdapter: boolean; onChanged: () => void; children: ReactNode; next: ReactNode }) {
  const queryClient = useQueryClient()
  const base = `/github/imports/${encodeURIComponent(importId)}`
  const inspectionKey = ['inspection', session.user.id, importId], contractKey = ['contract', session.user.id, importId]
  // The first visit runs the static scan; later visits read the saved one.
  const inspection = useQuery({ queryKey: inspectionKey, queryFn: async ({ signal }) => {
    try { return await api<Inspection>(`${base}/inspection`, { signal }) }
    catch (error) { if (error instanceof ApiError && error.status === 404) return send<Inspection>(`${base}/inspection`, session.csrf_token); throw error }
  } })
  const ready = inspection.data?.status === 'confirmed' && Boolean(inspection.data.configuration_revision)
  const contract = useQuery({ queryKey: contractKey, enabled: ready, queryFn: ({ signal }) => api<ContractRecord>(`${base}/contract`, { signal }) })

  const adapter = useQuery({ queryKey: ['adapter', session.user.id, importId, hasAdapter], enabled: hasAdapter, queryFn: ({ signal }) => api<Adapter>(`${base}/adapter`, { signal }) })

  if (inspection.isPending) return <p role="status" className="slab p-8">Reading the repository…</p>
  if (inspection.isError) return <div role="alert" className="slab p-8"><p>{message(inspection.error)}</p><button className="button-secondary mt-4" onClick={() => void inspection.refetch()}>Try again</button></div>
  return <>
    <Settings key={inspection.data.revision} base={base} session={session} inspection={inspection.data} onSaved={next => { queryClient.setQueryData(inspectionKey, next); void queryClient.invalidateQueries({ queryKey: contractKey }); onChanged() }} />
    {children}
    {!ready ? <p className="mt-9 rounded-card p-8 text-muted">Save the settings above, then add the tasks.</p>
      : contract.isPending ? <p role="status" className="slab mt-9 p-8">Loading tasks…</p>
      : contract.isError ? <div role="alert" className="slab mt-9 p-8"><p>{message(contract.error)}</p><button className="button-secondary mt-4" onClick={() => void contract.refetch()}>Try again</button></div>
      : <Tasks key={`${contract.data.version}:${inspection.data.configuration_revision}:${Boolean(adapter.data)}`} base={base} session={session} revision={inspection.data.configuration_revision!} record={contract.data} adapter={adapter.data || null} tools={inspection.data.configuration?.approved_tools || []} onSaved={next => { queryClient.setQueryData(contractKey, next); void queryClient.invalidateQueries({ queryKey: ['run-contract'] }); onChanged() }} />}
    {/* One line that always says what is still missing and what comes after. */}
    <aside className="mt-9 rounded-card bg-ink p-6 text-paper sm:p-8"><p className="tabular text-[14px] text-paper/80">what's next</p>
      {(() => { const tasksDone = contract.data?.status === 'confirmed' && !contract.data.stale
        const fits = allowsSandboxPython(inspection.data.configuration?.python_version || '')
        const todo = !ready ? 'Save the settings in step 1.' : !fits ? 'Fix the Python version in step 1: it has to allow 3.12.' : !hasAdapter ? 'Start onboarding in step 2 so Hansa can run your agent.' : !tasksDone ? 'Save and confirm at least one task in step 3.' : null
        return <><ul className="mt-3 flex flex-wrap gap-2">{[['settings', ready && fits], ['adapter', hasAdapter], ['tasks', tasksDone]].map(([label, ok]) =>
          <li key={label as string} className={`chip ${ok ? 'border-paper bg-ok-soft text-ink' : 'border-dashed border-paper/60 text-paper/80'}`}>{ok && <Check size={13} strokeWidth={3} aria-hidden="true" />}{label as string}</li>)}</ul>
          <p className="mt-4 font-display text-[24px] leading-tight font-medium">{todo || 'Setup is done. Measure what the agent costs today.'}</p>{!todo && <div className="mt-5">{next}</div>}</> })()}
    </aside>
  </>
}
