import { useState } from 'react'
import { areas } from './areas'
import type { Xray as XrayData } from './report'

const usd = (value: number) => value >= 100 ? `$${Math.round(value).toLocaleString()}` : value >= 1 ? `$${value.toFixed(2)}` : `$${value.toFixed(value >= 0.01 ? 3 : 4)}`

function Split({ parts }: { parts: [string, number | null, string][] }) {
  return <div><div className="flex h-9 overflow-hidden rounded-control" role="img" aria-label={parts.map(([label, value]) => `${label} ${value ?? 0}%`).join(', ')}>
    {parts.map(([label, value, tone]) => (value || 0) > 0 && <div key={label} className={`${tone} grid place-items-center overflow-hidden tabular text-[14px] font-medium`} style={{ width: `${value}%` }}>{(value || 0) >= 9 ? `${Math.round(value!)}%` : ''}</div>)}</div>
    <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1 tabular text-[14px]">{parts.map(([label, value, tone]) => <li key={label} className="flex items-center gap-1.5"><i className={`size-3 rounded-[3px] border border-line ${tone}`} />{label} {value == null ? '—' : `${Math.round(value)}%`}</li>)}</ul></div>
}

/** What the agent is made of, measured from the call ledger. No model wrote any of this. */
export default function Xray({ xray, costPerPass }: { xray: XrayData; costPerPass: number | null }) {
  const [volume, setVolume] = useState('10000')
  const runs = Math.max(0, Number(volume) || 0)
  const saving = xray.prompt_caching_estimate
  return <section className="slab mt-9 p-6 pt-8 md:p-8"><span className="slab-tab">x-ray · measured, no model involved</span>
    <h3 className="font-display text-[28px] leading-none font-medium sm:text-[34px]">What this agent is made of.</h3>
    <p className="mt-2 max-w-[62ch] text-muted">Read straight from the sizes of all {xray.model_calls} model calls in this baseline. These are measurements, not opinions.</p>

    <div className="mt-7 grid gap-8 lg:grid-cols-2">
      <div><p className="label">every request is made of</p><div className="mt-2"><Split parts={[['system prompt', xray.input.system_percent, 'bg-ink text-paper'], ['tool definitions', xray.input.tool_schema_percent, 'bg-waste text-ink'], ['conversation', xray.input.conversation_percent, 'bg-wash text-ink']]} /></div></div>
      <div><p className="label">where the time goes</p><div className="mt-2"><Split parts={[['inside the model', xray.time.model_percent, 'bg-ink text-paper'], ['agent code and tools', xray.time.outside_model_percent, 'bg-waste text-ink']]} /></div></div>
    </div>

    <dl className="mt-8 grid grid-cols-2 gap-x-6 gap-y-6 py-6 lg:grid-cols-4">
      {[[`${Math.round(xray.input.sent_before_percent ?? 0)}%`, 'of each request was already sent on the call before'], [`${xray.calls_per_run}`, 'model calls per task, on average'],
        [`${xray.handoff_calls.count}`, 'calls that say nothing and make one tool call'], [`${xray.time.seconds_per_call}s`, `per call · slowest ${xray.time.slowest_call_seconds}s`]].map(([value, label], index) =>
        <div key={label} className={index === 0 ? 'rounded-control bg-waste-soft px-4 py-3' : 'px-4 py-3'}><dt className={`big-number text-[40px] sm:text-[48px] ${index === 0 ? 'text-waste' : ''}`}>{value}</dt><dd className={`mt-1.5 text-[15px] leading-snug ${index === 0 ? 'text-ink' : 'text-muted'}`}>{label}</dd></div>)}
    </dl>

    {xray.readings.length > 0 ? <ul className="mt-7 grid gap-4 md:grid-cols-2">{xray.readings.map(reading => <li key={reading.headline} className={`rounded-control border p-4 ${reading.strength === 'strong' ? 'border-transparent bg-waste-soft' : 'border-line bg-paper'}`}>
      <span className="chip border-transparent bg-surface px-2 py-0 text-[13px] text-muted">{areas.find(area => area.key === reading.area)?.name || reading.area}</span>
      <p className="mt-2 text-[19px] leading-snug font-semibold">{reading.headline}</p><p className="mt-1.5 text-[14px] text-muted">{reading.detail}</p></li>)}</ul>
      : <p className="mt-7 rounded-control p-4 text-[14px]">Nothing stands out in the shape of the calls. The hunt can still find waste in the source.</p>}

    {costPerPass != null && <div className="mt-8 rounded-control border border-line bg-paper p-5 sm:p-6">
      <label htmlFor="xray-volume" className="tabular text-[14px] text-muted">if this task set runs</label>
      <div className="mt-2 flex flex-wrap items-center gap-3"><input id="xray-volume" type="number" min="0" step="1000" value={volume} onChange={event => setVolume(event.target.value)} className="field w-36 tabular text-ink" /><span className="text-[15px]">times a month</span></div>
      <dl className="mt-5 grid gap-5 sm:grid-cols-2"><div><dt className="text-[15px] text-muted">it costs about</dt><dd className="big-number mt-1 text-[36px]">{usd(costPerPass * runs)}<span className="text-[16px] font-medium tracking-normal text-muted"> / month</span></dd></div>
        {saving && saving.saving_percent ? <div><dt className="text-[15px] text-muted">prompt caching alone could save roughly</dt><dd className="big-number mt-1 text-[36px] text-ok">{usd(costPerPass * runs * saving.saving_percent / 100)}<span className="text-[16px] font-medium tracking-normal text-muted"> / month</span></dd></div> : null}</dl>
      {saving && <p className="mt-4 tabular text-[14px] leading-relaxed text-muted">The caching figure is an estimate, not a measurement. {saving.assumes}</p>}
    </div>}
  </section>
}
