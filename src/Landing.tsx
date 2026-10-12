import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { ArrowDown, ArrowRight, Braces, FileCode2, FlaskConical, GitBranch, GitCompareArrows, Gauge, ShieldCheck } from 'lucide-react'
import savedReport from './data/swarm-report.json'
import savedPatches from './data/swarm-patches.json'
import { measurement as preciseMeasurement, sourceUrl, type ImportReport } from './report'
import { useReducedMotion } from './motionPreference'
import './landing.css'

// The public demo reads saved evidence only; selecting a view never starts a run.
const report = savedReport as unknown as ImportReport
const baseline = report.baseline!
const attempt = report.optimizations.at(-1)!
const comparison = attempt.comparison!
const totals = comparison.totals
const regressions = comparison.tasks.filter(task => task.regressed)
const needsReview = comparison.tasks.filter(task => task.candidate_status === 'needs_review').length
// Everything the page says about the outcome follows the saved decision; nothing here assumes one.
const accepted = attempt.decision === 'accept'
const verdict = accepted ? 'Accepted' : attempt.decision === 'reject' ? 'Rejected' : 'No change kept'
const behaviour = regressions.length ? `${regressions.length} task${regressions.length === 1 ? '' : 's'} regressed` : 'No task regressed'
const proof = attempt.proof
const heroCost = measurement(baseline.per_pass.cost_usd, 'usd')
const patch = (savedPatches as Record<string, string | null>)[attempt.job_id] || ''
const diffLine = patch.split('\n').find(line => line.startsWith('+') && !line.startsWith('+++')) || 'No patch recorded.'
const tabs = ['Baseline', 'Findings', 'Tested change', 'Verdict'] as const
const demoSteps = ['baseline', 'findings&view=hunt', 'fix', 'result']
const metrics = [
  ['Model calls', 'model_calls', 'number'],
  ['Recorded cost', 'cost_usd', 'usd'],
  ['Run time', 'wall_time_seconds', 'seconds'],
] as const
const status = (value: string | null) => value === 'needs_review' ? 'Needs review' : value === 'failed' ? 'Checks failed' : value === 'passed' ? 'Checks passed' : value?.replaceAll('_', ' ') || 'Not recorded'
// Round only homepage displays; the app keeps its shared precision and saved measurements.
function measurement(value: number | null | undefined, unit: 'number' | 'usd' | 'seconds' = 'number') {
  if (value == null || !Number.isFinite(value)) return preciseMeasurement(value, unit)
  return unit === 'usd' ? value.toLocaleString('en-US', { style: 'currency', currency: 'USD' }) : preciseMeasurement(Math.round(value), unit)
}
function change(value: number | null) {
  if (value == null || !Number.isFinite(value)) return 'Not recorded'
  const rounded = Math.round(value)
  return `${rounded > 0 ? '+' : rounded < 0 ? '−' : ''}${Math.abs(rounded)}%`
}

const steps = [
  { title: 'Bring your agent', text: 'Connect a repository and choose the tasks and changes you allow.' },
  { title: 'Establish the baseline', text: 'Measure the original’s calls, cost and task outcomes.' },
  { title: 'Test a targeted change', text: 'Investigate the source, edit a copy and rerun the same tasks.' },
  { title: 'Review the trade-offs', text: 'Compare savings and regressions. Keep or reject the patch.' },
]
const recordedMetrics = [
  { name: 'Cost', value: `${measurement(totals.cost_usd.baseline, 'usd')} → ${measurement(totals.cost_usd.candidate, 'usd')}`, delta: totals.cost_usd.change_percent, detail: 'Recorded model cost per pass' },
  { name: 'Latency', value: `${measurement(totals.wall_time_seconds.baseline, 'seconds')} → ${measurement(totals.wall_time_seconds.candidate, 'seconds')}`, delta: totals.wall_time_seconds.change_percent, detail: 'Run time per pass' },
  { name: 'Model calls', value: `${measurement(totals.model_calls.baseline)} → ${measurement(totals.model_calls.candidate)}`, delta: totals.model_calls.change_percent, detail: 'Model calls per pass' },
  { name: 'Context', value: `${measurement(totals.tokens_in.baseline)} → ${measurement(totals.tokens_in.candidate)}`, delta: totals.tokens_in.change_percent, detail: `Input tokens; output ${measurement(totals.tokens_out.baseline)} → ${measurement(totals.tokens_out.candidate)}` },
  { name: 'Task behavior', value: behaviour, detail: `${needsReview} candidate answer${needsReview === 1 ? '' : 's'} still need${needsReview === 1 ? 's' : ''} human review. Change ${verdict.toLowerCase()}.` },
  { name: 'Run conditions', value: `${baseline.tasks.length} tasks × ${measurement(baseline.repetitions)} repetitions`, detail: `${baseline.model || 'Model not recorded'}. Spend/runtime caps not recorded.` },
]

function ExperimentDiagram() {
  const reducedMotion = useReducedMotion()
  const [stage, setStage] = useState(0)
  const [hovered, setHovered] = useState(false)
  const [focused, setFocused] = useState(false)
  // The loop only runs while the diagram is on screen and the tab is in front; otherwise it costs renders nobody sees.
  const [watching, setWatching] = useState(true)
  const figure = useRef<HTMLElement>(null)
  useEffect(() => {
    let onScreen = true
    const update = () => setWatching(onScreen && !document.hidden)
    const observer = new IntersectionObserver(([entry]) => { onScreen = entry.isIntersecting; update() })
    if (figure.current) observer.observe(figure.current)
    document.addEventListener('visibilitychange', update)
    return () => { observer.disconnect(); document.removeEventListener('visibilitychange', update) }
  }, [])
  useEffect(() => {
    if (reducedMotion || hovered || focused || !watching) return
    const timer = window.setInterval(() => setStage(current => (current + 1) % 6), 1200)
    return () => window.clearInterval(timer)
  }, [reducedMotion, hovered, focused, watching])
  const active = (index: number) => !reducedMotion && stage === index
  return <figure ref={figure} className="experiment-diagram" tabIndex={0} aria-label="Recorded Swarm experiment: original model calls and cost, Hansa's tested change, and the verdict Hansa reached after rerunning the tasks. Animation pauses while focused."
    onMouseEnter={() => setHovered(true)} onMouseLeave={() => setHovered(false)}
    onFocus={() => setFocused(true)} onBlur={event => { if (!event.currentTarget.contains(event.relatedTarget)) setFocused(false) }}>
    <figcaption><span className="data-label">THE ENGINEERING LOOP</span><span className="diagram-label">SAVED SWARM RUN</span></figcaption>
    <div className="diagram-input"><GitBranch size={23} aria-hidden="true" /><div><strong>Your agent</strong><span className="diagram-baseline">{measurement(baseline.per_pass.model_calls)} calls, {heroCost}</span><span>Swarm airline example · mean per pass</span></div><span className="diagram-label">IN</span></div>
    <div className="diagram-connector" aria-hidden="true"><ArrowDown size={18} /></div>
    <div className="diagram-engine"><div className="diagram-engine-title"><img src="/brand/mark.svg" width="44" height="44" alt="" /><div><strong>Hansa</strong><span>Your optimization engineer</span></div></div>
      <div className="diagram-actions"><span data-active={active(0)}><FileCode2 size={18} aria-hidden="true" />Investigate</span><ArrowRight size={14} aria-hidden="true" /><span data-active={active(1)}><Braces size={18} aria-hidden="true" />Edit</span><ArrowRight size={14} aria-hidden="true" /><span data-active={active(2)}><FlaskConical size={18} aria-hidden="true" />Test</span></div>
      <p><GitCompareArrows size={15} aria-hidden="true" /> Compare against the original. Keep or reject.</p>
    </div>
    <div className="diagram-connector" aria-hidden="true"><ArrowDown size={18} /></div>
    <div className="diagram-output"><div data-active={active(3)}><span><FileCode2 size={18} aria-hidden="true" />Patch</span><small>Tested candidate</small></div><div data-active={active(4)}><span><Gauge size={18} aria-hidden="true" />Measurements</span><small>{baseline.tasks.length} tasks · {baseline.repetitions === 1 ? 'run once' : `${measurement(baseline.repetitions)} runs each`}</small></div><div className="diagram-verdict" data-active={active(5)}><span><ShieldCheck size={18} aria-hidden="true" />Verdict</span><small>{change(totals.model_calls.change_percent)} calls<br />{behaviour.toLowerCase()}<br /><b className={accepted ? 'is-accepted' : ''}>{verdict}</b></small></div></div>
    <p className="diagram-note">Recorded results. Automatic checks; human review still required.</p>
  </figure>
}

function CandidateMeasurement({ from, to, unit }: { from: number | null; to: number | null; unit: 'number' | 'usd' | 'seconds' }) {
  const reducedMotion = useReducedMotion()
  const [value, setValue] = useState(from)
  useEffect(() => {
    if (reducedMotion || from == null || to == null || !Number.isFinite(from) || !Number.isFinite(to)) return
    const start = performance.now()
    let frame: number
    const tick = (now: number) => {
      const progress = Math.min((now - start) / 1100, 1)
      setValue(progress === 1 ? to : from + (to - from) * (1 - (1 - progress) ** 3))
      if (progress < 1) frame = requestAnimationFrame(tick)
    }
    frame = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(frame)
  }, [from, to, reducedMotion])
  const display = reducedMotion || from == null || to == null || !Number.isFinite(from) || !Number.isFinite(to) ? to : value
  return <span className="candidate-measurement" data-value={display}><span aria-hidden="true">{measurement(display, unit)}</span><span className="sr-only">{measurement(to, unit)}</span></span>
}

function SavedDemo() {
  const reducedMotion = useReducedMotion()
  const [view, setView] = useState(0)
  const [autoplay, setAutoplay] = useState(true)
  const [inView, setInView] = useState(false)
  const [pageVisible, setPageVisible] = useState(!document.hidden)
  const tablist = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const observer = new IntersectionObserver(([entry]) => setInView(entry.isIntersecting && entry.intersectionRatio >= 0.25), { threshold: 0.25 })
    observer.observe(tablist.current!)
    const visibility = () => setPageVisible(!document.hidden)
    document.addEventListener('visibilitychange', visibility)
    return () => { observer.disconnect(); document.removeEventListener('visibilitychange', visibility) }
  }, [])
  const advancing = autoplay && inView && pageVisible && !reducedMotion
  useEffect(() => {
    if (!advancing) return
    const timer = window.setTimeout(() => setView(current => (current + 1) % tabs.length), 5000)
    return () => window.clearTimeout(timer)
  }, [advancing, view])
  return <div className="saved-demo" onFocusCapture={() => setAutoplay(false)} onPointerDownCapture={() => setAutoplay(false)}>
    <div className="demo-topline"><span><span className="recorded-dot" /> RECORDED EXPERIMENT</span><span>{report.import.repository} <span className="demo-commit">/ {report.import.commit_sha.slice(0, 7)}</span></span></div>
    <div id="what-it-checks" className="recorded-measurements">
      <h3>What we measured on Swarm</h3>
      <p className="demo-note">Original → candidate. Mean per pass of the same {baseline.tasks.length} tasks. Rounded figures; percentages use full precision. LiteLLM-reported model cost excludes compute and is not invoice-reconciled.</p>
      <dl className="recorded-metrics">{recordedMetrics.map(metric => <div key={metric.name}><dt>{metric.name}</dt><dd><div className="metric-figure"><span className={metric.delta !== undefined ? 'metric-value' : undefined}>{metric.value}</span>{metric.delta != null && <span className={`metric-change ${metric.delta < 0 ? 'text-ok' : metric.delta > 0 ? 'text-waste' : 'text-muted'}`}>{change(metric.delta)}</span>}</div><small>{metric.detail}</small></dd></div>)}</dl>
    </div>
    <div className="demo-tabs" ref={tablist} role="tablist" aria-label="Recorded experiment views" data-advancing={advancing} onKeyDown={event => {
      const next = event.key === 'ArrowRight' ? (view + 1) % tabs.length : event.key === 'ArrowLeft' ? (view + tabs.length - 1) % tabs.length : event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : null
      if (next == null) return
      event.preventDefault(); setAutoplay(false); setView(next)
      tablist.current?.querySelectorAll<HTMLButtonElement>('[role=tab]')[next]?.focus()
    }}>{tabs.map((label, index) => <button key={label} id={`demo-tab-${index}`} role="tab" aria-label={label} aria-selected={view === index} aria-controls="demo-panel" tabIndex={view === index ? 0 : -1} onClick={() => { setAutoplay(false); setView(index) }}><span>{String(index + 1).padStart(2, '0')}</span>{index === 2 ? 'Change' : label}</button>)}</div>
    <div className="demo-panel" role="tabpanel" id="demo-panel" aria-labelledby={`demo-tab-${view}`} tabIndex={0}>
      {view === 0 && <>
        <div className="demo-panel-heading"><div><span className="data-label">THE ORIGINAL</span><h3>First, establish what happens today.</h3></div><span className="demo-model">{baseline.model}</span></div>
        <p className="demo-note">{baseline.tasks.length} tasks · {measurement(baseline.repetitions)} repetitions each · {measurement(baseline.failed)} tasks with failed checks · {measurement(baseline.needs_review)} needing review. A pass here means one run of the task set.</p>
        <div className="task-list">{baseline.tasks.map(task => <div key={task.task_id}><span>{task.name}</span><span className={task.status === 'failed' ? 'outcome-warning' : ''}>{status(task.status)}</span></div>)}</div>
      </>}
      {view === 1 && <>
        <div className="demo-panel-heading"><div><span className="data-label">SOURCE + EXECUTION</span><h3>Findings you can trace to the code.</h3></div></div>
        <p className="demo-note">These are hypotheses, not measured gains. The investigation ended early; its saved findings remain available.</p>
        <ol className="demo-findings">{report.investigation!.findings.map((finding, index) => <li key={finding.finding_id}>
          <details><summary><span className="finding-number">{String(index + 1).padStart(2, '0')}</span><span>{finding.source[0]?.path || `Finding ${index + 1}`}</span><span className="finding-estimate">{finding.estimated_saving?.cost_usd == null ? 'Not quantified' : `${measurement(finding.estimated_saving.cost_usd, 'usd')} estimated`}</span></summary>
            <p>{finding.waste}</p><p><b>Proposed change:</b> {finding.proposed_change}</p><p><b>Behavior risk:</b> {finding.behaviour_risk}</p>
            <div className="finding-sources">{finding.source.map(source => {
              const url = sourceUrl(report.import.repository, report.import.commit_sha, source, report.import.folder)
              return url && <a key={`${source.path}:${source.start_line}`} href={url} target="_blank" rel="noopener noreferrer">{source.path}:{source.start_line} <ArrowRight size={14} aria-hidden="true" /></a>
            })}</div>
          </details>
        </li>)}</ol>
      </>}
      {view === 2 && <>
        <div className="demo-panel-heading"><div><span className="data-label">THE CANDIDATE</span><h3>A small change, tested on the same tasks.</h3></div><span className={accepted ? 'verdict-label is-accepted' : 'outcome-warning'}>{accepted ? 'Accepted' : 'Not accepted'}</span></div>
        <p className="demo-note">{accepted ? 'This is the patch Hansa kept after rerunning the tasks. Read it before applying it: the checks are automatic and a person has not confirmed the answers.' : 'The saved patch is an experiment artifact. Its result includes a regression; review it before considering any change.'}</p>
        <pre className="demo-patch" aria-label="Tested candidate patch">{patch ? patch.trim().split('\n').map((line, index) => <span key={index} className={line.startsWith('+') && !line.startsWith('+++') ? 'patch-add' : line.startsWith('-') && !line.startsWith('---') ? 'patch-remove' : ''}>{line || ' '}{'\n'}</span>) : 'No patch recorded.'}</pre>
      </>}
      {view === 3 && <>
        <div className="demo-panel-heading"><div><span className="data-label">THE VERDICT</span><h3>{accepted ? 'Cheaper and faster, and every task held.' : regressions.length ? 'Cheaper and faster. Still rejected.' : 'No saving worth keeping.'}</h3></div><span className={`verdict-label ${accepted ? 'is-accepted' : ''}`}>Change {verdict.toLowerCase()}</span></div>
        <div className="comparison-scroll"><table className="demo-comparison"><caption>Mean totals per pass of the same task set</caption><thead><tr><th scope="col">Measurement</th><th scope="col">Original</th><th scope="col">Candidate</th><th scope="col">Change</th></tr></thead><tbody>{metrics.map(([label, key, unit]) => {
          const value = comparison.totals[key]
          return <tr key={key}><th scope="row">{label}</th><td>{measurement(value.baseline, unit)}</td><td><CandidateMeasurement from={value.baseline} to={value.candidate} unit={unit} /></td><td>{change(value.change_percent)}</td></tr>
        })}</tbody></table></div>
        <p className="demo-note">{behaviour}. {comparison.note.replaceAll('needs_review', '“Needs review”')} Lower resource usage does not establish correct answers.</p>
        {/* How far the evidence goes, in the product's own words: an accepted change on a small task set is a lead, not a guarantee. */}
        {proof && <p className="demo-note"><b>Proof strength: {proof.strength}.</b> {proof.notes.join(' ')}</p>}
        {regressions.length > 0 && <details className="regression-detail"><summary>Why this change was rejected</summary>{regressions.map(task => <p key={task.task_id}><b>{task.name || `Task ${task.task_id}`}:</b> {task.candidate_reason || 'No detailed reason recorded.'}</p>)}</details>}
        <div className="task-list">{comparison.tasks.map(task => <div key={task.task_id}><span>{task.name || `Task ${task.task_id}`}</span><span className={task.regressed ? 'outcome-warning' : ''}>{task.regressed ? 'Regressed' : status(task.candidate_status)}</span></div>)}</div>
      </>}
    </div>
    <div className="demo-bottomline"><span>Saved results. Exploring this demo starts no jobs.</span><Link to={`/demo?step=${demoSteps[view]}`} className="text-link">Open full report <ArrowRight size={16} aria-hidden="true" /></Link></div>
  </div>
}

export default function Landing() {
  useEffect(() => {
    const jump = () => { if (location.hash) document.getElementById(location.hash.slice(1))?.scrollIntoView() }
    jump(); window.addEventListener('hashchange', jump)
    return () => window.removeEventListener('hashchange', jump)
  }, [])

  return <main className="landing">
    <section className="hero">
      <div className="hero-copy">
        <h1>An optimization engineer for your <span>AI agent.</span></h1>
        <p className="hero-sub">Hansa investigates your agent, tests code changes on your tasks, and returns a reviewable patch with the measurements and regressions behind it.</p>
        <div className="hero-actions"><Link to="/app/new" className="button-primary">Analyze my agent <ArrowRight size={17} aria-hidden="true" /></Link><a href="#real-run" className="text-link">Explore the demo <ArrowDown size={16} aria-hidden="true" /></a></div>
        <p className="hero-footnote"><GitBranch size={15} aria-hidden="true" /> Saved Swarm run · {measurement(baseline.per_pass.model_calls)} calls · {heroCost} per pass</p>
      </div>
      <ExperimentDiagram />
    </section>

    <section id="real-run" className="real-run landing-section">
      <div className="section-heading"><h2>One run. The whole story.</h2><p>OpenAI’s Swarm airline example. Explore the measurements, findings, patch and verdict.</p></div>
      <SavedDemo />
    </section>

    <section id="how-it-works" className="how landing-section">
      <div className="section-heading"><h2>From source to a tested change.</h2><p>You set the goal and boundaries. Follow the saved Swarm run from repository to verdict.</p></div>
      <ol className="process-flow">{steps.map(({ title, text }, index) => <li key={title}>
        <span className="process-node" aria-hidden="true" />
        <div className="step-artifact">
          {index === 0 && <a className="artifact-repo" href={`https://github.com/${report.import.repository}/tree/${report.import.commit_sha}`} target="_blank" rel="noopener noreferrer" title={`${report.import.repository} · ${report.import.commit_sha}`}><GitBranch size={16} aria-hidden="true" /><span>{report.import.repository}</span></a>}
          {index === 1 && <div className="artifact-calls"><div className="artifact-call-bars" aria-hidden="true">{Array.from({ length: Math.round(baseline.per_pass.model_calls || 0) }, (_, call) => <i key={call} />)}</div><span>{measurement(baseline.per_pass.model_calls)} calls / pass</span></div>}
          {index === 2 && <Link to="/demo?step=fix" className="artifact-diff" title={diffLine} aria-label="Open the saved tested patch"><code>{diffLine}</code></Link>}
          {index === 3 && <div className="artifact-verdict"><span className={`verdict-label ${accepted ? 'is-accepted' : ''}`}><ShieldCheck size={16} aria-hidden="true" />{verdict}</span><span>{behaviour}</span></div>}
        </div>
        <h3>{title}</h3><p>{text}</p>
      </li>)}</ol>
    </section>

    <footer className="landing-footer">
      <div className="footer-invitation"><div><h2>Find your agent’s next improvement.</h2></div><Link to="/app/new" className="button-primary">Analyze my agent <ArrowRight size={17} aria-hidden="true" /></Link></div>
      <div className="footer-bottom"><Link to="/" className="footer-brand"><img src="/brand/mark.svg" width="32" height="32" alt="" />Hansa</Link><span>Investigate. Experiment. Review.</span><Link to="/demo">Recorded demo <ArrowRight size={14} aria-hidden="true" /></Link><span>Built for neatHack by <a href="https://x.com/sonuv_dev" target="_blank" rel="noopener noreferrer">@sonuv_dev</a></span></div>
    </footer>
  </main>
}
