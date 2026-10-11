import { ArrowRight, GitBranch } from 'lucide-react'
import saved from './data/swarm-report.json'
import { barWidth, measurement, sourceUrl, type ImportReport } from './report'

export const report = saved as ImportReport
export const views = ['Import', 'Baseline', 'Findings', 'Verdict'] as const
export const annotations = ['Fixed commit. Nothing runs on import.', 'Measured before changing a line.', 'Every finding points to the code.', 'A cheaper fix still has to hold up.']
export const latest = report.optimizations.at(-1)!

export function SavedComparison() {
  return <div className="hero-comparison">{([
                  ['model_calls', 'Model calls', 'number'], ['cost_usd', 'Cost', 'usd'], ['wall_time_seconds', 'Wall time', 'seconds'],
                ] as const).map(([key, label, unit]) => {
                  const metric = latest.comparison!.totals[key]
                  return <div key={key}><h3>{label}</h3>{(['baseline', 'candidate'] as const).map(kind => <div className="hero-bar-row" key={kind}><span>{kind}</span><svg viewBox="0 0 100 8" preserveAspectRatio="none" aria-hidden="true"><rect width="100" height="8" fill="var(--wash)" /><rect width={barWidth(metric[kind], metric[kind === 'baseline' ? 'candidate' : 'baseline'])} height="8" fill={kind === 'baseline' ? 'var(--ink)' : 'var(--blue)'} /></svg><code>{measurement(metric[kind], unit)}</code></div>)}</div>
                })}</div>
}

export function SavedRunPanel({ view, level = 2 }: { view: number; level?: 2 | 3 }) {
  const Heading = level === 2 ? 'h2' : 'h3'
  return <>
              <div className="hero-repository"><GitBranch size={16} strokeWidth={1.75} aria-hidden="true" /><span>{report.import.repository}</span><code>{report.import.commit_sha.slice(0, 7)}</code></div>
              <div className="hero-panel-heading"><Heading>{views[view]}</Heading><p className="hero-annotation">{annotations[view]}</p></div>
              {view === 0 && <div className="hero-import-view">
                <p className="font-display text-[34px] leading-tight font-[750] tracking-[-0.035em]">The source, held still.</p>
                <dl className="hero-import-details"><div><dt>Repository</dt><dd>{report.import.repository}</dd></div><div><dt>Branch</dt><dd>{report.import.branch}</dd></div><div><dt>Commit</dt><dd>{report.import.commit_sha}</dd></div></dl>
                <p className="text-muted text-[13px]">This saved run compares the same tasks against the same source snapshot. Importing source starts no execution.</p>
              </div>}
              {view === 1 && report.baseline && <>
                <p className="hero-panel-note">Mean per full task set · {report.baseline.repetitions} repetitions · {report.baseline.model}</p>
                <dl className="hero-baseline-totals">{[
                  ['Model calls', measurement(report.baseline.per_pass.model_calls)], ['Cost', measurement(report.baseline.per_pass.cost_usd, 'usd')], ['Wall time', measurement(report.baseline.per_pass.wall_time_seconds, 'seconds')],
                ].map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>
                <ul className="hero-task-list">{report.baseline.tasks.map(task => <li key={task.task_id}><span>{task.name}</span><span className={task.status === 'failed' ? 'font-mono text-xs text-ink bg-waste-soft px-2 py-1' : 'font-mono text-xs text-muted'}>{task.status?.replaceAll('_', ' ')}</span></li>)}</ul>
                <p className="hero-panel-note">Automatic checks only. Needs review is not a pass.</p>
              </>}
              {view === 2 && <>
                <p className="hero-panel-note hero-findings-caveat">Estimates over cited runs, not measured gains. {report.investigation?.incomplete && 'Investigation incomplete; saved findings retained.'}</p>
                <div className="hero-findings-label"><span>{report.investigation?.findings.length} findings</span><span>Estimated saving</span></div>
                <ol className="hero-findings">{report.investigation?.findings.map(finding => {
                  const estimate = finding.estimated_saving
                  const details = [[estimate?.model_calls, 'calls'], [estimate?.wall_time_seconds, 's'], [estimate?.tokens, 'tokens']] as const
                  return <li key={finding.finding_id}>
                    <div className="hero-finding-copy"><p className="hero-finding-title">{finding.waste?.split(/(?<=[.!?])\s/)[0]}</p>
                      <div className="hero-sources">{finding.source.map(source => <a key={`${source.path}:${source.start_line}`} href={sourceUrl(report.import.repository, report.import.commit_sha, source) ?? undefined} target="_blank" rel="noreferrer">{source.path}:{source.start_line}{source.end_line !== source.start_line ? `–${source.end_line}` : ''}<ArrowRight size={12} strokeWidth={1.75} aria-hidden="true" /></a>)}</div>
                    </div>
                    <div className="hero-estimate"><strong className={estimate?.cost_usd == null ? 'hero-estimate-unknown' : undefined}>{estimate?.cost_usd != null ? measurement(estimate.cost_usd, 'usd') : 'Not quantified'}</strong><span>{details.filter(([value]) => value != null).map(([value, unit]) => `${measurement(value)} ${unit}`).join(' · ')}</span></div>
                  </li>
                })}</ol>
              </>}
              {view === 3 && latest.comparison && <>
                <div className="hero-verdict"><strong>Fix {latest.decision === 'reject' ? 'rejected' : latest.decision}</strong><span>Last candidate tried · {latest.comparison.all_tasks ? 'full task set' : 'partial task set'}</span></div>
                <SavedComparison />
                <p className="hero-panel-note">{latest.comparison.tasks.filter(task => task.regressed).map(task => `${task.name}: ${task.baseline_status?.replaceAll('_', ' ')} → ${task.candidate_status}.`).join(' ')} {latest.summary?.split('**Why rejected:**')[1]?.split('\n\n')[0] ?? latest.summary}</p>
              </>}
  </>
}
