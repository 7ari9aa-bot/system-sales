import React, { useState, useEffect, useRef } from 'react'

const c = (ar, en) => ({ ar, en })
const tx = (copy, locale) => copy[locale]

const phrases = [
  c('رسالة واحدة. سياق كامل. خطوة أوضح.', 'One message. Full context. Clearer next step.'),
  c('المبيعات تبدأ من السياق، لا من السرعة.', 'Sales start with context, not speed.'),
  c('كل محادثة لها مالك وموعد وخطوة.', 'Every conversation has an owner, a window, and a next step.'),
  c('AI يقترح. فريقك يقرر. النتيجة تُسجَّل.', 'AI suggests. Your team decides. The outcome is logged.'),
]

const NODE_COUNT = 46
const LINK_DIST = 120
const MOUSE_RADIUS = 150

function makeNodes(w, h) {
  return Array.from({ length: NODE_COUNT }, (_, i) => ({
    x: Math.random() * w,
    y: Math.random() * h,
    vx: (Math.random() - 0.5) * 0.35,
    vy: (Math.random() - 0.5) * 0.35,
    r: 1.5 + Math.random() * 3.5,
    ring: i % 5 === 0,
    warm: i % 7 === 0,
  }))
}

export default function AuthArtPanel({ locale }) {
  const [phraseIndex, setPhraseIndex] = useState(0)
  const panelRef = useRef(null)
  const canvasRef = useRef(null)

  useEffect(() => {
    const timer = window.setInterval(() => setPhraseIndex((i) => (i + 1) % phrases.length), 4000)
    return () => window.clearInterval(timer)
  }, [])

  useEffect(() => {
    const panel = panelRef.current
    const canvas = canvasRef.current
    if (!panel || !canvas) return
    const ctx = canvas.getContext('2d')
    const mouse = { x: -9999, y: -9999 }
    let w = 0, h = 0, nodes = [], raf

    const resize = () => {
      const dpr = window.devicePixelRatio || 1
      w = panel.clientWidth
      h = panel.clientHeight
      canvas.width = w * dpr
      canvas.height = h * dpr
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      nodes = makeNodes(w, h)
    }
    resize()
    window.addEventListener('resize', resize)

    const onMove = (e) => {
      const rect = panel.getBoundingClientRect()
      mouse.x = e.clientX - rect.left
      mouse.y = e.clientY - rect.top
      panel.style.setProperty('--mx', `${mouse.x}px`)
      panel.style.setProperty('--my', `${mouse.y}px`)
      panel.classList.add('is-hover')
    }
    const onLeave = () => {
      mouse.x = mouse.y = -9999
      panel.classList.remove('is-hover')
    }
    panel.addEventListener('mousemove', onMove)
    panel.addEventListener('mouseleave', onLeave)

    const draw = () => {
      ctx.clearRect(0, 0, w, h)
      for (const n of nodes) {
        const dx = n.x - mouse.x
        const dy = n.y - mouse.y
        const d = Math.hypot(dx, dy)
        if (d < MOUSE_RADIUS && d > 0) {
          const f = (1 - d / MOUSE_RADIUS) * 1.6
          n.vx += (dx / d) * f * 0.12
          n.vy += (dy / d) * f * 0.12
        }
        n.vx *= 0.985
        n.vy *= 0.985
        n.x += n.vx
        n.y += n.vy
        if (n.x < -10) n.x = w + 10
        if (n.x > w + 10) n.x = -10
        if (n.y < -10) n.y = h + 10
        if (n.y > h + 10) n.y = -10
      }
      for (let i = 0; i < nodes.length; i++) {
        const a = nodes[i]
        for (let j = i + 1; j < nodes.length; j++) {
          const b = nodes[j]
          const d = Math.hypot(a.x - b.x, a.y - b.y)
          if (d < LINK_DIST) {
            ctx.strokeStyle = `rgba(190,225,214,${(1 - d / LINK_DIST) * 0.28})`
            ctx.lineWidth = 1
            ctx.beginPath()
            ctx.moveTo(a.x, a.y)
            ctx.lineTo(b.x, b.y)
            ctx.stroke()
          }
        }
        const dm = Math.hypot(a.x - mouse.x, a.y - mouse.y)
        if (dm < MOUSE_RADIUS * 1.5) {
          ctx.strokeStyle = `rgba(245,215,180,${(1 - dm / (MOUSE_RADIUS * 1.5)) * 0.5})`
          ctx.beginPath()
          ctx.moveTo(a.x, a.y)
          ctx.lineTo(mouse.x, mouse.y)
          ctx.stroke()
        }
      }
      for (const n of nodes) {
        const color = n.warm ? 'rgba(232,180,130,0.85)' : 'rgba(200,235,224,0.8)'
        ctx.beginPath()
        ctx.arc(n.x, n.y, n.ring ? n.r + 4 : n.r, 0, Math.PI * 2)
        if (n.ring) {
          ctx.strokeStyle = color
          ctx.lineWidth = 1.2
          ctx.stroke()
        } else {
          ctx.fillStyle = color
          ctx.fill()
        }
      }
      raf = requestAnimationFrame(draw)
    }
    draw()

    return () => {
      cancelAnimationFrame(raf)
      window.removeEventListener('resize', resize)
      panel.removeEventListener('mousemove', onMove)
      panel.removeEventListener('mouseleave', onLeave)
    }
  }, [])

  const isAr = locale === 'ar'

  return (
    <div className="auth-art-panel" ref={panelRef}>
      <div className="auth-art-orbs" aria-hidden="true">
        <div className="auth-art-orb auth-mesh-1" />
        <div className="auth-art-orb auth-mesh-2" />
      </div>

      <div className="auth-beams" aria-hidden="true">
        <span className="auth-beam auth-beam-1" />
        <span className="auth-beam auth-beam-2" />
      </div>

      <div className="auth-spotlight" aria-hidden="true" />
      <canvas ref={canvasRef} className="auth-canvas" aria-hidden="true" />

      <div className="auth-art-content">
        <div className="auth-art-brand">
          <img src="/fihrist-mark.svg" alt="" />
          <span>FIHRIST</span>
        </div>
        <div className="auth-art-phrases">
          {phrases.map((phrase, i) => (
            <p key={i} className={i === phraseIndex ? 'auth-art-phrase on' : 'auth-art-phrase'} dir={isAr ? 'rtl' : 'ltr'}>
              {tx(phrase, locale)}
            </p>
          ))}
        </div>
        <div className="auth-art-footnote">
          <span className="demo-dot" /> {tx(c('محتوى تجريبي · لا توجد تكاملات إنتاجية', 'Demo content · no production integrations'), locale)}
        </div>
      </div>
    </div>
  )
}