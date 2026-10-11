import { Fragment, useRef, useState } from 'react'
import { ArrowRight } from 'lucide-react'
import { motion, useMotionValueEvent, useScroll } from 'motion/react'
import { useReducedMotion } from './motionPreference'
import { report, latest, views, SavedRunPanel, SavedComparison } from './SavedRun'
import { measurement, sourceUrl } from './report'

const stageCopy = [
  ['Hold the source still.', 'Import your repository at a fixed commit. Hansa inspects the source without running it. You review the setup and task contract before execution.'],
  ['Measure before editing.', 'Run the agreed tasks with recorded calls, cost and wall time. The baseline is the reference every candidate has to answer to.'],
  ['Follow the waste to the code.', 'Hansa investigates the run and points to a file and line for each finding. A possible saving is a hypothesis until a candidate measures it.'],
  ['Test it. Then make the call.', 'Compare the candidate on the same tasks and declared settings. Keep a measured improvement or reject the change when behavior regresses.'],
]

export default function LandingSections() {
  const track = useRef<HTMLDivElement>(null)
  const [stage, setStage] = useState(0)
  const reduced = useReducedMotion()
  const { scrollYProgress } = useScroll({ target: track, offset: ['start start', 'end end'] })
  useMotionValueEvent(scrollYProgress, 'change', progress => setStage(Math.min(3, Math.max(0, Math.floor(progress * 4)))))

  function jump(index: number) {
    if (!track.current) return
    const top = track.current.getBoundingClientRect().top + window.scrollY
    const distance = Math.max(0, track.current.offsetHeight - window.innerHeight)
    window.scrollTo({ top: top + distance * (index + 0.1) / 4, behavior: 'instant' })
  }

  return <>
    <section id="how-it-works" aria-labelledby="how-title" className={`how-section${reduced ? ' is-still' : ''}`}>
      <div ref={track} className="how-track">
        <div className="how-sticky">
          <div className="how-copy">
            <p className="section-label">How it works</p>
            <h2 id="how-title" className="section-title">From repository to a measured decision.</h2>
            <p className="section-sub">One experiment. The source, the baseline and the reason behind the result.</p>
            <ol className="how-nav">{views.map((name, index) => <li key={name}><button type="button" onClick={() => jump(index)} aria-current={stage === index ? 'step' : undefined}><span className="font-mono text-xs">0{index + 1}</span><span>{name}</span><ArrowRight size={16} strokeWidth={1.75} aria-hidden="true" /></button></li>)}</ol>
            <p className="how-scroll-note">Scroll through the experiment ↓<br />Saved report · no work starts here</p>
          </div>
          <div className="how-scenes">{views.map((name, index) => <article key={name} className={`how-scene${stage === index ? ' is-active' : ''}`} data-stage={name.toLowerCase()}>
            <div className="how-scene-copy"><p className="section-label">{name}</p><h3>{stageCopy[index][0]}</h3><p>{stageCopy[index][1]}</p></div>
            <div className="how-product"><div className="hero-window-bar"><span className="font-mono text-xs">hansa / {name.toLowerCase()}</span><span className="font-mono text-xs text-muted">Saved run</span></div><div className="hero-panel"><SavedRunPanel view={index} level={3} /></div></div>
            <p className="how-stage-caption">{stageCopy[index][1]}</p>
          </article>)}</div>
        </div>
      </div>
    </section>

    <section id="real-run" aria-labelledby="real-title" className="real-section">
      <div className="real-intro"><p className="section-label">A real run · Swarm airline</p><h2 id="real-title" className="section-title">The cheaper fix Hansa refused to ship.</h2><p className="section-sub">A direct route removed an intermediate model call. The full task set exposed a regression, so the candidate was reverted.</p></div>
      <dl className="real-context"><div><dt>Repository</dt><dd>{report.import.repository}</dd></div><div><dt>Commit</dt><dd>{report.import.commit_sha.slice(0, 7)}</dd></div><div><dt>Model</dt><dd>{report.baseline?.model}</dd></div><div><dt>Compared</dt><dd>{latest.comparison?.tasks.length} tasks · {report.baseline?.repetitions} repetitions</dd></div></dl>
      <div className="real-evidence">
        <div className="real-measurements"><div className="real-cell-heading"><h3>Baseline vs candidate</h3><p>Mean per full task set · last candidate tried</p></div><SavedComparison /></div>
        <div className="real-outcomes"><div className="real-cell-heading"><h3>What happened to each task</h3><p>Automatic checks; needs review is not a pass.</p></div>
          <div className="real-task-table"><table><thead><tr><th scope="col">Task</th><th scope="col">Baseline</th><th scope="col">Candidate</th></tr></thead><tbody>{latest.comparison?.tasks.map(task => <Fragment key={task.task_id}><tr className={`real-task-summary${task.regressed ? ' is-regressed' : ''}`}><th scope="row">{task.name}{task.regressed && <span className="real-regression">Regression</span>}</th><td>{task.baseline_status?.replaceAll('_', ' ')}</td><td>{task.candidate_status?.replaceAll('_', ' ')}</td></tr>{task.regressed && task.candidate_reason && <tr className="real-task-reason"><td colSpan={3}><p><strong>Candidate check · {task.name}:</strong> {task.candidate_reason}</p></td></tr>}</Fragment>)}</tbody></table></div>
        </div>
        <div className="real-verdict"><div><p className="section-label">The decision</p><h3>Fix rejected.</h3><p>Fewer calls do not settle correctness.</p></div><div><h4>Why it stayed rejected</h4><p>{latest.summary?.split('**Why rejected:**')[1]?.split('\n\n')[0] ?? latest.summary}</p><p className="real-verdict-note">Saved optimizer explanation. The cause of the regression was not confirmed within the remaining budget.</p></div></div>
        <div className="real-findings"><div className="real-cell-heading"><h3>What the investigation found</h3><p>Incomplete investigation · estimates over cited runs, not measured gains.</p></div><ol>{report.investigation?.findings.map(finding => <li key={finding.finding_id}><div><p>{finding.waste?.split(/(?<=[.!?])\s/)[0]}</p><div className="hero-sources">{finding.source.map(source => <a key={`${source.path}:${source.start_line}`} href={sourceUrl(report.import.repository, report.import.commit_sha, source) ?? undefined} target="_blank" rel="noreferrer">{source.path}:{source.start_line}{source.end_line !== source.start_line ? `–${source.end_line}` : ''}<ArrowRight size={12} strokeWidth={1.75} aria-hidden="true" /></a>)}</div></div><p className="real-finding-estimate">{finding.estimated_saving?.cost_usd == null ? 'Saving not quantified' : `${measurement(finding.estimated_saving.cost_usd, 'usd')} estimated`}</p></li>)}</ol></div>
      </div>
      <div className="real-limits"><p>{latest.comparison?.note?.replaceAll('needs_review', 'Needs review')}</p><p>{report.limits[0]} {report.limits[2]} {report.limits[3]}</p></div>
      {latest.trace && <details className="real-traces"><summary>Trace details · export {latest.trace.status}</summary><p>Recorded trace IDs, with content withheld in this saved report. Readback is not confirmed. The import owner must be signed in to open these API records.</p><ul>{(latest.trace.trace_ids ?? (latest.trace.trace_id ? [latest.trace.trace_id] : [])).map(id => <li key={id}><a href={`/github/imports/${report.import.import_id}/traces/${id}`} target="_blank" rel="noreferrer">Trace {id.slice(0, 8)} <ArrowRight size={12} strokeWidth={1.75} aria-hidden="true" /></a></li>)}</ul></details>}
      <motion.p className="real-endnote" initial={false} whileInView={reduced ? undefined : { opacity: [0.6, 1], y: [8, 0] }} viewport={{ once: true }} transition={{ duration: 0.4 }}>The result is the evidence and the decision. A rejected change is a completed experiment.</motion.p>
    </section>
  </>
}
