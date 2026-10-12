import type { CSSProperties } from 'react'
import { Braces, Cpu, DollarSign, FlaskConical, Gauge, GitBranch, GitCompareArrows, Layers, MessagesSquare, ShieldCheck, Timer, Wrench } from 'lucide-react'

// The things Hansa works with, drifting in the page margins so they never sit under the content:
// [icon, side, top %, tone, seconds, delay].
const tiles = [
  [GitBranch, 'left', 6, 'blue', 9, 0], [Braces, 'left', 22, 'ink', 12, 0.6], [Wrench, 'left', 38, 'waste', 10, 0.2], [FlaskConical, 'left', 54, 'blue', 10, 2.1], [Layers, 'left', 70, 'ink', 9, 0.9], [DollarSign, 'left', 86, 'ok', 9.5, 1.8],
  [MessagesSquare, 'right', 12, 'blue', 11, 2.3], [Timer, 'right', 28, 'waste', 11.5, 0.3], [Gauge, 'right', 44, 'ok', 11, 1.2], [GitCompareArrows, 'right', 60, 'blue', 12.5, 1.1], [Cpu, 'right', 76, 'ink', 12, 1.5], [ShieldCheck, 'right', 91, 'ok', 10.5, 2.6],
] as const

/** A fixed layer behind the page content. Purely decorative. */
export default function Backdrop() {
  return <div className="backdrop" aria-hidden="true">{tiles.map(([Icon, side, top, tone, seconds, delay], index) =>
    <span key={index} className={`is-${tone} at-${side}`} style={{ top: `${top}%`, '--t': `${seconds}s`, '--d': `${delay}s` } as CSSProperties}><Icon size={20} strokeWidth={1.7} /></span>)}</div>
}
