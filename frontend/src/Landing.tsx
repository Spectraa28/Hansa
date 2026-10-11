import { useEffect, useRef, useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { ArrowRight, MousePointer2, Pause, Play } from 'lucide-react'
import { motion, useInView, useScroll, useTransform } from 'motion/react'
import { useReducedMotion } from './motionPreference'
import { annotations, views, SavedRunPanel } from './SavedRun'
import LandingSections from './LandingSections'

export default function Landing() {
  const [view, setView] = useState(2)
  const [paused, setPaused] = useState(false)
  const [hovered, setHovered] = useState(false)
  const [focused, setFocused] = useState(false)
  const [phone, setPhone] = useState(window.matchMedia('(max-width: 639px)').matches)
  const [visible, setVisible] = useState(!document.hidden)
  const windowRef = useRef<HTMLDivElement>(null)
  const location = useLocation()
  const inView = useInView(windowRef, { amount: 0.15 })
  const reduced = useReducedMotion()
  const { scrollYProgress } = useScroll({ target: windowRef, offset: ['start start', 'end start'] })
  const scale = useTransform(scrollYProgress, [0, 1], [1, 0.96])
  const y = useTransform(scrollYProgress, [0, 1], [0, -24])
  const playing = !paused && !hovered && !focused && visible && inView && !reduced

  useEffect(() => {
    if (location.hash === '#swarm-run') { setView(2); setPaused(true) }
    if (location.hash) document.getElementById(location.hash.slice(1))?.scrollIntoView({ block: 'start' })
  }, [location.hash, location.key])

  useEffect(() => {
    const update = () => setVisible(!document.hidden)
    const media = window.matchMedia('(max-width: 639px)')
    const resize = () => setPhone(media.matches)
    document.addEventListener('visibilitychange', update)
    media.addEventListener('change', resize)
    return () => { document.removeEventListener('visibilitychange', update); media.removeEventListener('change', resize) }
  }, [])
  useEffect(() => {
    if (!playing) return
    const timer = window.setTimeout(() => setView(current => (current + 1) % views.length), view === 2 ? 9000 : 6000)
    return () => window.clearTimeout(timer)
  }, [playing, view])

  function selectView(index: number) { setView(index); setPaused(true) }

  return (
    <main className="landing">
      <section aria-labelledby="hero-title" className="hero-intro">
        <p className="hero-tag">For teams running AI agents</p>
        <h1 id="hero-title" className="hero-title">
          <span className="hero-line">Make your agent cheaper</span>{' '}
          <span className="hero-line">and faster. <span className="hero-highlight">With proof.</span></span>
        </h1>
        <p className="hero-sub">Import your agent's repository. Hansa runs it, finds the calls it is wasting, tests the fix against your baseline, and hands you a patch that is measured to work.</p>
        <div className="hero-actions">
          <Link to="/app" className="button-primary hero-import">Import a repository <ArrowRight size={16} strokeWidth={1.75} aria-hidden="true" /></Link>
          <a href="#real-run" onClick={() => selectView(2)} className="button-secondary">See a real run</a>
        </div>
      </section>
        <ul className="hero-capabilities" aria-label="What you get">
          <li><strong>1 repo</strong><span>in, no SDK to install</span></li>
          <li><strong>File + line</strong><span>on every finding</span></li>
          <li><strong>Patch or prompt</strong><span>out, ready for your coding agent</span></li>
        </ul>

      <motion.div ref={windowRef} style={reduced ? undefined : { scale, y }} className="hero-window-scroll">
        <div id="swarm-run" className="hero-window" onMouseEnter={() => setHovered(window.matchMedia('(hover: hover)').matches)} onMouseLeave={() => setHovered(false)}
          onFocusCapture={event => setFocused(!(event.target as HTMLElement).closest('.hero-play'))} onBlurCapture={event => { if (!event.currentTarget.contains(event.relatedTarget)) setFocused(false) }}>
          <div className="hero-window-bar">
            <span className="flex items-center gap-2 font-mono text-xs"><img src="/brand/mark.svg" width="24" height="24" alt="" /> hansa / <strong className="font-normal">saved run</strong></span>
            <button type="button" className="hero-play" onClick={() => setPaused(!paused)} disabled={!!reduced} aria-label={reduced ? 'Still saved run preview' : paused ? 'Play saved run preview' : 'Pause saved run preview'}>
              {paused || reduced ? <Play size={14} strokeWidth={1.75} /> : <Pause size={14} strokeWidth={1.75} />}
              <span>{reduced ? 'Still preview' : paused ? 'Play preview' : 'Pause preview'}</span>
            </button>
          </div>
          <div className="hero-window-body">
            <div className="hero-rail" role="tablist" aria-label="Saved run stages" aria-orientation={phone ? 'horizontal' : 'vertical'}>
              {views.map((name, index) => <button key={name} type="button" role="tab" aria-selected={view === index} aria-controls="saved-run-panel" id={`saved-run-tab-${index}`} tabIndex={view === index ? 0 : -1}
                onClick={() => selectView(index)} onKeyDown={event => {
                  let next: number | undefined
                  if (['ArrowDown', 'ArrowRight'].includes(event.key)) next = (view + 1) % views.length
                  if (['ArrowUp', 'ArrowLeft'].includes(event.key)) next = (view + views.length - 1) % views.length
                  if (event.key === 'Home') next = 0
                  if (event.key === 'End') next = views.length - 1
                  if (next !== undefined) { event.preventDefault(); selectView(next); document.getElementById(`saved-run-tab-${next}`)?.focus() }
                }}>
                <span className="hero-step-number">0{index + 1}</span>{name}
                {view === index && !paused && !reduced && <MousePointer2 className="hero-cursor" size={19} strokeWidth={1.75} aria-hidden="true" />}
              </button>)}
              <p className="hero-rail-note">One repository.<br />A measured decision.</p>
            </div>
            <div id="saved-run-panel" role="tabpanel" aria-labelledby={`saved-run-tab-${view}`} tabIndex={0} className="hero-panel">
              <SavedRunPanel view={view} />
            </div>
          </div>
          <div className="hero-window-footer"><span>Saved Swarm run · read-only</span><span className="hero-mobile-annotation">{annotations[view]}</span><span className="hero-footer-flow">Source → measurement → decision</span></div>
        </div>
      </motion.div>
      <LandingSections />
    </main>
  )
}
