import { useEffect } from 'react'

const SELECTOR = '.feature-card, .audience-card, .detail-points article, .scn-step, .ba-card, .price-card, .btn'

export default function Spotlight() {
  useEffect(() => {
    const onMove = (e) => {
      const el = e.target.closest && e.target.closest(SELECTOR)
      if (!el) return
      const rect = el.getBoundingClientRect()
      el.style.setProperty('--smx', `${e.clientX - rect.left}px`)
      el.style.setProperty('--smy', `${e.clientY - rect.top}px`)
    }
    window.addEventListener('mousemove', onMove, { passive: true })
    return () => window.removeEventListener('mousemove', onMove)
  }, [])
  return null
}