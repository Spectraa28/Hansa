import { useEffect, useRef } from 'react'
import type { CSSProperties, ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { motion, MotionConfig } from 'motion/react'
import { ArrowRight, ArrowUpRight, Box, GitBranch, KeyRound, Lock, Scissors, Wallet } from 'lucide-react'
import savedReport from './data/swarm-report.json'
import savedPatches from './data/swarm-patches.json'
import type { ImportReport } from './report'
import { areas } from './areas'
import './landing.css'

// Everything on this page is read from one saved run of OpenAI's Swarm airline example.
const report = savedReport as unknown as ImportReport
const baseline = report.baseline!
const findings = report.investigation!.findings
const attempt = report.optimizations.at(-1)!
const totals = attempt.comparison!.totals
const patch = (savedPatches as Record<string, string | null>)[attempt.job_id] || ''
const sha = report.import.commit_sha.slice(0, 7)
const ease = [0.2, 0.8, 0.2, 1] as const

const usd = (value: number | null, digits = 4) => value == null ? '—' : `$${value.toFixed(digits)}`
const file = (path: string) => path.split('/').at(-1)
const short = ['Pass-through agent', 'Dead line in the prompt', 'No cap on turns']
// The routing hop the first finding describes shows up in these tasks of the saved run.
const leaking = new Set(['1', '2', '4', '5', '6'])

function Stamp({ children, tone = 'waste', delay = 0 }: { children: ReactNode; tone?: 'waste' | 'ink'; delay?: number }) {
  return <motion.span className={`stamp stamp-${tone}`} initial={{ opacity: 0, scale: 2.4, rotate: -24 }} whileInView={{ opacity: 1, scale: 1, rotate: -9 }}
    viewport={{ once: true, amount: .6 }} transition={{ delay, type: 'spring', stiffness: 420, damping: 19 }}>{children}</motion.span>
}

function Receipt() {
  const line = { hidden: { opacity: 0, y: -8 }, show: { opacity: 1, y: 0, transition: { duration: .28, ease } } }
  return <motion.div className="receipt-wrap" initial={{ opacity: 0, y: 60, rotate: 7 }} animate={{ opacity: 1, y: 0, rotate: 2.5 }} transition={{ duration: .9, ease, delay: .25 }}>
    <motion.div className="receipt" initial="hidden" animate="show" variants={{ show: { transition: { staggerChildren: .075, delayChildren: .7 } } }} aria-label="Receipt for a saved run of the Swarm airline agent">
      <motion.div variants={line} className="receipt-head"><img src="/brand/mark.svg" alt="" width="34" height="34" /><div><strong>HANSA</strong><span>agent receipt</span></div><code>#{sha}</code></motion.div>
      <motion.p variants={line} className="receipt-meta">{report.import.repository} · airline example<br />{baseline.model} · {baseline.tasks.length} tasks × {baseline.repetitions} runs</motion.p>
      <motion.hr variants={line} />
      {baseline.tasks.map(task => <motion.div variants={line} className="receipt-row" key={task.task_id}>
        <span>{task.task_id?.padStart(2, '0')} {task.name}</span><span>{task.model_calls} calls</span><span>{usd(task.cost_usd)}</span>
      </motion.div>)}
      <motion.hr variants={line} />
      <motion.div variants={line} className="receipt-row receipt-total"><span>TOTAL / PASS</span><span>{baseline.per_pass.model_calls} calls</span><span>{usd(baseline.per_pass.cost_usd)}</span></motion.div>
      <motion.hr variants={line} />
      <motion.p variants={line} className="receipt-waste-title"><Scissors size={14} aria-hidden="true" /> WASTE FOUND</motion.p>
      {findings.map((finding, index) => <motion.div variants={line} className="receipt-row receipt-waste" key={finding.finding_id}>
        <span>{short[index]}<small>{file(finding.source[0].path)}:{finding.source[0].start_line}</small></span>
        <span className="receipt-saving">{finding.estimated_saving?.cost_usd != null ? `−${usd(finding.estimated_saving.cost_usd, 3)}` : 'risk'}</span>
      </motion.div>)}
      <motion.p variants={line} className="receipt-foot">savings are estimates until tested</motion.p>
      <motion.div variants={line} className="receipt-barcode" aria-hidden="true" />
      <Stamp delay={2.6}>{findings.length} leaks found</Stamp>
    </motion.div>
  </motion.div>
}

function Hero() {
  const words = [['Your', 'agent'], ['overspends.'], ['We', 'bring']]
  return <section className="hero">
    <div className="hero-copy">
      <motion.p className="hero-kicker" initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: .1 }}><span className="live-dot" /> for people who ship AI agents</motion.p>
      <h1 className="hero-title">
        {words.map((row, i) => <span className="hero-row" key={i}>{row.map((word, j) => <span className="hero-mask" key={word}>
          <motion.span initial={{ y: '105%' }} animate={{ y: 0 }} transition={{ duration: .7, ease, delay: .08 * (i * 2 + j) }}>{word}</motion.span></span>)}</span>)}
        <span className="hero-row"><motion.span className="hero-block" initial={{ scaleX: 0, rotate: 0 }} animate={{ scaleX: 1, rotate: -2 }} transition={{ duration: .55, ease, delay: .62 }}>
          <motion.span initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: .9 }}>receipts.</motion.span></motion.span></span>
      </h1>
      <motion.p className="hero-sub" initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: .85, duration: .6, ease }}>
        Point Hansa at your agent's repo. It runs the agent in a sandbox and finds what makes it slow and expensive: bloated prompts, heavy tool schemas, extra agent hops, the wrong model. Then it tests the fix against your own baseline and hands you the patch <em>only if the numbers hold.</em>
      </motion.p>
      <motion.div className="hero-actions" initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 1, duration: .6, ease }}>
        <Link to="/app" className="button-primary hero-cta">Import a repo <ArrowRight size={18} aria-hidden="true" /></Link>
        <a href="#real-run" className="hero-link">See a run we rejected <ArrowRight size={16} aria-hidden="true" /></a>
      </motion.div>
    </div>
    <Receipt />
  </section>
}

function Ticker() {
  const items = ['Prompt structure', 'Tool schemas', 'Agent design', 'Model choice', 'Latency', 'Cost', 'File + line on every finding', 'Rejects its own bad fixes']
  const row = <ul aria-hidden="true">{items.map(item => <li key={item}>{item}<span>✂</span></li>)}</ul>
  return <div className="ticker" role="marquee" aria-label={items.join(', ')}><div className="ticker-track">{row}{row}</div></div>
}

// Marks an element once it scrolls into view, without re-rendering React.
function useSeen<T extends HTMLElement>(amount: number, onSeen?: (node: T) => void) {
  const ref = useRef<T>(null)
  useEffect(() => {
    const node = ref.current
    if (!node) return
    const watch = new IntersectionObserver(([entry]) => {
      if (!entry.isIntersecting) return
      node.classList.add('is-seen'); onSeen?.(node); watch.disconnect()
    }, { threshold: amount })
    watch.observe(node)
    return () => watch.disconnect()
  }, [])
  return ref
}

function Blocks({ flag = false }: { flag?: boolean }) {
  const ref = useSeen<HTMLDivElement>(.5)
  let n = 0
  return <div className="blocks" ref={ref}>{baseline.tasks.map(task => <div className="blocks-row" key={task.task_id}>
    <span className="blocks-name">{task.task_id?.padStart(2, '0')} {task.name}</span>
    <span className="blocks-cells">{Array.from({ length: task.model_calls || 0 }, (_, i) =>
      <i key={i} className={flag && i === 1 && leaking.has(task.task_id || '') ? 'is-waste' : ''} style={{ '--i': n++ } as CSSProperties} />)}</span>
    <span className="blocks-cost">{usd(task.cost_usd)}</span>
  </div>)}</div>
}

function Diff() {
  return <pre className="diff" aria-label="The change that was tested">{patch.trim().split('\n').filter(row => !row.startsWith('---') && !row.startsWith('+++')).map((row, i) =>
    <span key={i} className={row.startsWith('@@') ? 'diff-hunk' : row.startsWith('+') ? 'diff-add' : row.startsWith('-') ? 'diff-del' : ''}>{row || ' '}{'\n'}</span>)}</pre>
}

// Counts up by writing text directly: one text node per frame, nothing else on the page moves.
function Counter({ value, digits = 0, prefix = '', suffix = '', sign = false }: { value: number; digits?: number; prefix?: string; suffix?: string; sign?: boolean }) {
  const text = (n: number) => `${sign && n > 0 ? '+' : ''}${n < 0 ? '−' : ''}${prefix}${Math.abs(n).toFixed(digits)}${suffix}`
  const ref = useSeen<HTMLSpanElement>(.8, node => {
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) { node.textContent = text(value); return }
    const start = performance.now()
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / 900)
      node.textContent = text(value * (1 - (1 - t) ** 3))
      if (t < 1) requestAnimationFrame(tick)
    }
    requestAnimationFrame(tick)
  })
  return <span ref={ref} className="tabular">{text(0)}</span>
}

function StackCard({ index, tone, title, body, children }: { index: number; tone: string; title: string; body: string; children: ReactNode }) {
  // Sticky positioning does the stacking; no scroll listener is needed.
  return <div className="stack-slot" style={{ top: `calc(84px + ${index * 18}px)` }}>
    <article className={`stack-card tone-${tone}`}>
      <div className="stack-copy"><span className="stack-number">0{index + 1}</span><h3>{title}</h3><p>{body}</p></div>
      <div className="stack-visual">{children}</div>
    </article>
  </div>
}

function How() {
  return <section id="how-it-works" className="how">
    <div className="how-head"><p className="eyebrow">How it works</p><h2>Four steps.<br />No dashboards to stare at.</h2></div>
    <div className="stack">
      <StackCard index={0} tone="paper" title="Point at a repo." body="Pick the repository and branch. Hansa pins one commit and reads it. Nothing runs yet, and you install nothing in your code.">
        <div className="repo-card"><div className="repo-line"><GitBranch size={20} aria-hidden="true" /><span>github.com/<b>{report.import.repository}</b></span></div>
          <div className="repo-pin"><span>pinned</span><code>{sha}</code><span>branch</span><code>{report.import.branch}</code></div>
          <p>Hansa's own agent reads the source and writes the adapter that runs it.</p></div>
      </StackCard>
      <StackCard index={1} tone="ink" title="Run it for real." body="Your tasks run in a locked-down container on a throwaway key with a spend cap. Every model call is counted, timed and priced.">
        <Blocks />
        <dl className="meter"><div><dt>calls</dt><dd><Counter value={baseline.per_pass.model_calls || 0} /></dd></div>
          <div><dt>cost</dt><dd><Counter value={baseline.per_pass.cost_usd || 0} digits={3} prefix="$" /></dd></div>
          <div><dt>time</dt><dd><Counter value={baseline.per_pass.wall_time_seconds || 0} suffix="s" /></dd></div></dl>
      </StackCard>
      <StackCard index={2} tone="waste" title="Find the leak." body="Hansa lines every call up against the source: the prompt, the tool schemas, the hand-offs, the model. Then it points at the exact line. Here: an agent that only forwards to another agent.">
        <Blocks flag />
        <pre className="snippet"><span className="snippet-file">{findings[0].source[0].path}</span>
          <span><i>46</i>    functions=[transfer_to_flight_modification, …],</span>
          <span><i>47</i>{' )'}</span>
          <span><i>48</i></span>
          <span className="is-hot"><i>49</i> flight_modification = Agent(   <b>← 1 extra call, every task</b></span></pre>
      </StackCard>
      <StackCard index={3} tone="paper" title="Prove it, or bin it." body="The fix runs on a private copy against the same tasks. Cheaper and still passing: you get the patch. Cheaper but broken: it goes in the bin, and you see why.">
        <Diff />
        <div className="prove-row"><span className="chip chip-ok">cheaper ✓</span><span className="chip chip-ok">faster ✓</span><span className="chip chip-waste">still passes ?</span></div>
      </StackCard>
    </div>
  </section>
}

function Looks() {
  return <section className="looks">
    <p className="eyebrow">What it looks at</p>
    <h2>Eight places<br />an agent leaks.</h2>
    <p className="looks-sub">Cost is the symptom. Hansa goes through what the agent is made of, one area at a time, and tells you which are clean.</p>
    <ol className="looks-grid">{areas.map((area, index) => <motion.li key={area.key} initial={{ opacity: 0, y: 24 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true, amount: .4 }} transition={{ duration: .45, ease, delay: (index % 4) * .06 }}>
      <span>{String(index + 1).padStart(2, '0')}</span><h3>{area.name}</h3><p>{area.covers}</p></motion.li>)}</ol>
  </section>
}

function RealRun() {
  const stats = [['model calls', totals.model_calls.change_percent], ['cost', totals.cost_usd.change_percent], ['wall time', totals.wall_time_seconds.change_percent]] as const
  const tasks = attempt.comparison!.tasks
  return <section id="real-run" className="real">
    <p className="eyebrow">A real run · OpenAI Swarm, airline example</p>
    <h2>We found a fix that saved 10%.<br /><span className="strike">Then we threw it out.</span></h2>
    <div className="real-grid">
      <div className="real-stats">{stats.map(([label, change]) => <div key={label}>
        <strong className="big-number"><Counter value={change || 0} digits={Number.isInteger(change) ? 0 : 1} sign suffix="%" /></strong><span>{label}</span></div>)}
        <Stamp tone="ink" delay={.5}>rejected</Stamp>
      </div>
      <div className="real-why">
        <p className="real-lede">Skipping the pass-through agent made the run cheaper and faster. It also made <b>one task fail that used to pass.</b></p>
        <ul className="task-strip" aria-label="Each task before and after the fix">{tasks.map(task => <li key={task.task_id} className={task.regressed ? 'is-broken' : task.fixed ? 'is-fixed' : ''}>
          <span>{task.task_id.padStart(2, '0')}</span><b>{task.regressed ? 'broke' : task.fixed ? 'fixed' : 'same'}</b></li>)}</ul>
        <p>Two failing tasks started passing. One passing task broke. Hansa doesn't trade a working answer for a cheaper bill, so the patch was reverted and marked for review.</p>
        <p className="real-punch">A cheaper agent that breaks isn't cheaper.</p>
        <p className="real-small">{baseline.tasks.length} tasks × {baseline.repetitions} runs on {baseline.model} at commit {sha}. Automatic checks, provider-reported cost. Good for these tasks, not a promise for every input.</p>
      </div>
    </div>
  </section>
}

function Reveal({ children, className = '', delay = 0 }: { children: ReactNode; className?: string; delay?: number }) {
  return <motion.div className={className} initial={{ opacity: 0, y: 36 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true, amount: .3 }} transition={{ duration: .6, ease, delay }}>{children}</motion.div>
}

function Bars() {
  const rows = [['calls', totals.model_calls], ['cost', totals.cost_usd], ['time', totals.wall_time_seconds]] as const
  return <div className="bars">{rows.map(([label, row]) => <div className="bars-row" key={label}><span>{label}</span>
    <div className="bars-track"><motion.i initial={{ scaleX: 0 }} whileInView={{ scaleX: 1 }} viewport={{ once: true }} transition={{ duration: .7, ease }} />
      <motion.i style={{ width: `${(row.candidate || 0) / (row.baseline || 1) * 100}%` }} initial={{ scaleX: 0 }} whileInView={{ scaleX: 1 }} viewport={{ once: true }} transition={{ duration: .7, ease, delay: .15 }} /></div>
    <b>{row.change_percent}%</b></div>)}
    <p className="bars-key"><span>baseline</span><span>with the fix</span></p></div>
}

function Get() {
  return <section className="get">
    <p className="eyebrow">What you walk away with</p>
    <h2>Not a chart. A change.</h2>
    <div className="bento">
      <Reveal className="bento-card bento-patch"><span className="slab-tab">the patch</span><h3>A diff you can apply today.</h3><p>Small, reviewable, made against your exact commit, with the before and after measured on the same tasks.</p><Diff /><Bars /></Reveal>
      <Reveal className="bento-card bento-prompt" delay={.08}><span className="slab-tab">the prompt</span><h3>Or hand it to your coding agent.</h3>
        <p>One brief with the reason, the numbers and the diff. Paste it into Claude Code, Codex or Cursor.</p>
        <ol className="outline"><li># Change for you/agent</li><li>## Why</li><li>## What was measured</li><li>## The change</li><li>## Instructions</li></ol></Reveal>
      <Reveal className="bento-card bento-proof" delay={.16}><span className="slab-tab">the receipts</span><h3>Every claim has a trace.</h3>
        <p>Each run is logged call by call, so you can open the exact request behind any number.</p>
        <div className="built"><span>traces by <b>Neatlogs</b></span><span>build history by <b>Entire</b></span></div></Reveal>
    </div>
    <ul className="safe">{[[Box, 'Sandboxed', 'Your code runs in a locked container. Never on our host.'], [KeyRound, 'Throwaway keys', 'Each run gets its own key that dies with it.'],
      [Wallet, 'Spend cap first', 'You see the cap before anything starts.'], [Lock, 'Source stays put', 'A read-only copy of one commit. Nothing is pushed.']].map(([Icon, title, text]) => {
      const Glyph = Icon as typeof Box
      return <li key={title as string}><Glyph size={22} aria-hidden="true" /><b>{title as string}</b><span>{text as string}</span></li>
    })}</ul>
  </section>
}

function Closer() {
  return <section className="closer">
    <h2>Bring your agent.<br />Leave with receipts.</h2>
    <Link to="/app" className="closer-cta">Import a repo <ArrowUpRight size={26} aria-hidden="true" /></Link>
    <footer><span><img src="/brand/mark.svg" alt="" width="28" height="28" /> Hansa</span><span>Built for neatHack by <a href="https://x.com/sonuv_dev">@sonuv_dev</a></span></footer>
  </section>
}

export default function Landing() {
  return <MotionConfig reducedMotion="user"><main className="landing"><Hero /><Ticker /><How /><Looks /><RealRun /><Get /><Closer /></main></MotionConfig>
}
