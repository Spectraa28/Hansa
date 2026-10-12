import { useState } from 'react'
import type { MouseEvent } from 'react'
import { Moon, Sun } from 'lucide-react'

type Theme = 'light' | 'dark'
const current = (): Theme => document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light'

/** Switches between the light and dark themes. The new theme spreads out from the button like a wave. */
export default function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>(current)
  function toggle(event: MouseEvent<HTMLButtonElement>) {
    const next: Theme = current() === 'dark' ? 'light' : 'dark'
    const apply = () => {
      document.documentElement.dataset.theme = next
      document.querySelector('meta[name="theme-color"]')?.setAttribute('content', next === 'dark' ? '#0A111D' : '#F7F9FC')
      try { localStorage.setItem('hansa-theme', next) } catch { /* private windows may refuse storage; the theme still applies for this visit */ }
      setTheme(next)
    }
    const calm = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    if (calm) return apply()
    // Far enough to reach the corner of the window furthest from the button.
    const box = event.currentTarget.getBoundingClientRect()
    const x = box.left + box.width / 2, y = box.top + box.height / 2
    const reach = Math.hypot(Math.max(x, innerWidth - x), Math.max(y, innerHeight - y))
    const root = document.documentElement
    const phone = window.matchMedia('(max-width: 960px), (pointer: coarse)').matches
    if (!phone && !document.startViewTransition) return apply()
    if (phone) {
      // Phones: the snapshot a full-page wave needs is what made the tap feel late. Instead, one plain circle
      // in the new theme's colour grows from the button straight away, the theme changes under it, and it fades.
      const wave = document.createElement('div')
      wave.style.cssText = `position:fixed;z-index:9999;pointer-events:none;border-radius:50%;left:${x - reach}px;top:${y - reach}px;width:${reach * 2}px;height:${reach * 2}px;background:${next === 'dark' ? '#0A111D' : '#F7F9FC'};transform:scale(0);will-change:transform,opacity`
      document.body.append(wave)
      wave.animate({ transform: ['scale(0)', 'scale(1)'] }, { duration: 300, easing: 'cubic-bezier(.4, 0, .2, 1)', fill: 'forwards' }).finished
        .then(() => { apply(); return wave.animate({ opacity: [1, 0] }, { duration: 200, easing: 'ease-out', fill: 'forwards' }).finished })
        .finally(() => wave.remove())
      return
    }
    // Larger screens: the new theme itself is revealed in the circle. Everything else is stilled meanwhile.
    root.classList.add('theme-switching')
    const transition = document.startViewTransition(apply)
    transition.ready.then(() => {
      root.animate({ clipPath: [`circle(0px at ${x}px ${y}px)`, `circle(${reach}px at ${x}px ${y}px)`] },
        { duration: 700, easing: 'cubic-bezier(.4, 0, .2, 1)', pseudoElement: '::view-transition-new(root)' })
    }).catch(() => undefined)
    void transition.finished.finally(() => root.classList.remove('theme-switching'))
  }
  return <button type="button" onClick={toggle} aria-label={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'} title={theme === 'dark' ? 'Light mode' : 'Dark mode'}
    className="theme-toggle grid size-11 shrink-0 place-items-center rounded-control">{theme === 'dark' ? <Sun size={18} aria-hidden="true" /> : <Moon size={18} aria-hidden="true" />}</button>
}
