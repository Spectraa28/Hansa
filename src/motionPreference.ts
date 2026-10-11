import { useSyncExternalStore } from 'react'

const media = window.matchMedia('(prefers-reduced-motion: reduce)')
function subscribe(update: () => void) {
  media.addEventListener('change', update)
  return () => media.removeEventListener('change', update)
}

export function useReducedMotion() {
  return useSyncExternalStore(subscribe, () => media.matches)
}
