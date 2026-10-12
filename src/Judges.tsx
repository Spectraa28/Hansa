import { Link } from 'react-router-dom'
import { ArrowRight } from 'lucide-react'

// Everything on this page is a figure someone can check. Counts are as of 12 October 2026.
const criteria = [
  { name: 'Agent', weight: '30%', claim: 'Hansa is an agent that optimizes other agents, and it does not get the final word.',
    rows: [
      ['Three agent loops', 'Onboarding writes and proves an adapter for an unfamiliar repository. The deep hunt reads the measured runs and the source. The fix test edits a private copy and reruns the tasks. Each is a model choosing its next tool from the last result.'],
      ['The verdict is code, not the model', 'Whether a task regressed, whether a saving is real and whether a fix is accepted are computed from measurements. A saving under 5% is not accepted when run-to-run variation was not measured.'],
      ['Predicted, then measured', 'On OpenAI\'s Swarm airline example, on the hosted server: the hunt predicted −14.8% cost from removing a routing-only agent. The fix test measured −13.3% cost, −22.7% model calls and −16.5% time across 8 tasks, with no task regressed. Accepted.'],
      ['It reports a miss as a miss', 'On the OpenAI Agents SDK customer-service example the same kind of fix measured 0% change. Hansa finished it as "no improvement".'],
      ['It refuses a fix that breaks an answer', 'An earlier Swarm fix saved 10% of calls and made one passing task fail. Hansa rejected it and kept the evidence.'],
    ] },
  { name: 'Required tools', weight: '25%', claim: 'Neatlogs is part of the product. Entire holds the build. CFO.ai holds the business model.',
    rows: [
      ['Neatlogs', '337 traces in the project in the last 14 days. Every sandbox run and every agent job is logged as a trace, read back and confirmed. The in-app trace window shows each step with Hansa\'s own per-call figures beside it. Known gap: Neatlogs\' cost total reads $0, because Hansa sends cost in its own field.'],
      ['Entire', 'The project\'s only git remote is Entire. 10 of the first 25 commits carry a checkpoint from recorded agent sessions (Codex). Commits made in other sessions carry none, and no product feature depends on Entire.'],
      ['CFO.ai', 'A production model: Starter $149 a month for one proof, Team $299 for three, with the customer paying their own model bill. Base case over 12 months: 33 customers, $6,381 monthly revenue at exit, 92% gross margin, $211 of funding needed. The hosted stress case loses $16,200, and the model shows it. No customer has paid yet.'],
    ] },
  { name: 'Demo', weight: '20%', claim: 'The product is live, and the demo is a real saved run.',
    rows: [
      ['Live site', 'Sign in with GitHub or Google and import your own agent. One job runs at a time, and each run has a spend cap you see first.'],
      ['Recorded run', 'The demo walks a real run of Swarm from import to verdict without signing in or spending anything. It is the earlier two-task run, and it labels its own proof as thin.'],
    ] },
  { name: 'Usefulness and originality', weight: '10%', claim: 'Hansa does the work of an agent engineer: it measures an agent, examines its prompts, tools, memory, context and model choice, and proves a fix.',
    rows: [
      ['What it examines', 'Eight areas on every deep hunt: prompt structure, tool definitions, agent design, model choice, memory, output, latency and unused calls. Quick wins also cover caching, turn limits and answer-length limits. Each area is reported as a finding or as checked and clean.'],
      ['What you leave with', 'A patch against your exact commit, a brief your own coding agent can apply, and the measurements behind both.'],
      ['Honest about what it cannot prove', 'Model swaps, prompt caching and safety guards cannot be measured in the sandbox. Hansa says so and gives a labelled estimate from list prices instead of a test.'],
    ] },
] as const

const limits = [
  'Proof is only as strong as the tasks. Most results so far rest on 2 to 8 tasks run once, and the product rates that itself.',
  'Sign-in is open and one job runs at a time; a second request is refused with what is running, not queued.',
  'Agents with heavy dependencies (PyTorch, browsers) or provider-hosted tools cannot run in the sandbox yet.',
  'Costs are the figures the model provider reported per call, not reconciled against an invoice. Recorded model spend for the whole build is about $13.',
  'The newest prompt and estimate work has one real pass behind it, not many.',
]

export default function Judges() {
  return <main className="page max-w-[1080px]">
    <p className="label">neatHack 2026 · team Spectra</p>
    <h1 className="page-title mt-2">Check every Hansa claim.</h1>
    <p className="mt-4 max-w-[62ch] text-[18px] text-muted">Each scoring criterion, what we claim for it, and the figure behind the claim. Where something is weak or unfinished, it says so here.</p>
    <div className="mt-6 flex flex-wrap gap-3"><Link to="/demo" className="button-primary">Open the recorded run <ArrowRight size={16} aria-hidden="true" /></Link><Link to="/app/new" className="button-secondary">Try it on your own agent</Link>
      <a href="https://cfo.ai/s/fG9t075-Bd4KFAHP" target="_blank" rel="noopener noreferrer" className="button-secondary">The CFO.ai model</a></div>

    {criteria.map(section => <section key={section.name} className="slab mt-9 overflow-hidden">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 border-b border-line bg-wash px-6 py-4">
        <h2 className="text-[22px] font-semibold tracking-tight">{section.name}</h2><span className="font-mono text-[14px] text-muted">{section.weight} of the score</span>
        <p className="w-full text-[16px] text-body">{section.claim}</p></div>
      <dl>{section.rows.map(([what, proof]) => <div key={what} className="grid gap-x-8 gap-y-1 border-b border-line px-6 py-4 last:border-b-0 md:grid-cols-[240px_minmax(0,1fr)]">
        <dt className="font-semibold">{what}</dt><dd className="text-[15.5px] leading-relaxed text-body">{proof}</dd></div>)}</dl>
    </section>)}

    <section className="slab mt-9 overflow-hidden">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 border-b border-line bg-wash px-6 py-4">
        <h2 className="text-[22px] font-semibold tracking-tight">Public work</h2><span className="font-mono text-[14px] text-muted">15% of the score</span>
        <p className="w-full text-[16px] text-body">Posted as it was built, including the fix Hansa refused and the first one it accepted.</p></div>
      <ul className="divide-y divide-line">{([
        ["\"your AI agent is wasting model calls. you just can't see which ones\"", 'Launch post on X, with a short video. 11 October.', 'https://x.com/sonuv_dev/status/2109154433456050612'],
        ['"then the mf refused to ship the fix because ONE conversation broke"', 'On X, about the 10% saving Hansa rejected. 11 October.', 'https://x.com/sonuv_dev/status/2109209614344712594'],
        ["\"finally got a fix accepted on OpenAI's Swarm\"", 'On X: 33% fewer model calls, 23% lower cost, both tasks passing.', 'https://x.com/sonuv_dev'],
        ['The launch post on LinkedIn', 'Same story for a different audience, with the video.', 'https://www.linkedin.com/posts/sonu-verma28_neathack-ugcPost-7515014968757366785-dUo4/'],
      ] as const).map(([label, note, url]) =>
        <li key={label} className="px-6 py-3.5"><a href={url} target="_blank" rel="noopener noreferrer" className="link-action font-semibold">{label}</a><p className="mt-0.5 text-[14.5px] text-muted">{note}</p></li>)}</ul>
    </section>

    <section className="slab mt-9 p-6 md:p-8"><h2 className="text-[22px] font-semibold tracking-tight">By the numbers</h2>
      <dl className="mt-5 grid grid-cols-2 gap-x-6 gap-y-6 md:grid-cols-4">{([['297', 'backend tests passing'], ['337', 'Neatlogs traces'], ['2', 'real third-party agents taken end to end'], ['−13.3%', 'measured cost on Swarm, 8 tasks']] as const).map(([value, label]) =>
        <div key={label}><dt className="big-number text-[36px]">{value}</dt><dd className="mt-1.5 text-[14.5px] leading-snug text-muted">{label}</dd></div>)}</dl></section>

    <section className="mt-9 rounded-[12px] border border-dashed border-line p-6 md:p-8"><h2 className="text-[22px] font-semibold tracking-tight">Known limits</h2>
      <ul className="mt-4 list-disc space-y-2 pl-5 text-[15.5px] text-body">{limits.map(item => <li key={item}>{item}</li>)}</ul></section>
    <p className="mt-8 text-[14px] text-muted">Built for neatHack by <a className="link-action" href="https://x.com/sonuv_dev">@sonuv_dev</a>. Figures as of 12 October 2026.</p>
  </main>
}
