import Lenis from 'lenis'

// One smoothed page scroll for the whole site. A mouse wheel otherwise moves the page in hard steps
// (most visibly on Linux, where browsers do not smooth it themselves).
let lenis: Lenis | null = null

export function startSmoothScroll() {
  if (lenis || window.matchMedia('(prefers-reduced-motion: reduce)').matches) return
  lenis = new Lenis({ autoRaf: true, lerp: 0.13, anchors: true, allowNestedScroll: true })
  // The drifting background rests while the page moves, so the two never compete for the same frame.
  const root = document.documentElement
  let rest = 0
  lenis.on('scroll', () => {
    root.classList.add('is-scrolling')
    window.clearTimeout(rest)
    rest = window.setTimeout(() => root.classList.remove('is-scrolling'), 180)
  })
}

/** Hold the page still while a window (the trace) is open over it, and release it afterwards. */
export const holdScroll = (held: boolean) => { if (held) lenis?.stop(); else lenis?.start() }

/** Back to the top of the page: glided when already there, immediate when arriving from another page. */
export function toTop(glide: boolean) {
  if (lenis) lenis.scrollTo(0, { immediate: !glide, force: true })
  else window.scrollTo({ top: 0, behavior: glide ? 'smooth' : 'auto' })
}
