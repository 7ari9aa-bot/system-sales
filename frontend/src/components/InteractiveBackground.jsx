import React, { useEffect, useRef } from 'react'

const NODE_COUNT = 42
const LINK_DIST = 130
const MOUSE_RADIUS = 160

function makeNodes(w, h) {
  return Array.from({ length: NODE_COUNT }, (_, i) => ({
    x: Math.random() * w,
    y: Math.random() * h,
    vx: (Math.random() - 0.5) * 0.3,
    vy: (Math.random() - 0.5) * 0.3,
    r: 1.2 + Math.random() * 3,
    ring: i % 6 === 0,
    warm: i % 8 === 0,
  }))
}

export default function InteractiveBackground() {
  const wrapRef = useRef(null)
  const canvasRef = useRef(null)

  useEffect(() => {
    const wrap = wrapRef.current
    const canvas = canvasRef.current
    if (!wrap || !canvas) return
    const ctx = canvas.getContext('2d')
    const mouse = { x: -9999, y: -9999 }
    let w = 0, h = 0, nodes = [], raf

    const resize = () => {
      const dpr = window.devicePixelRatio || 1
      w = window.innerWidth
      h = window.innerHeight
      canvas.width = w * dpr
      canvas.height = h * dpr
      canvas.style.width = w + 'px'
      canvas.style.height = h + 'px'
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      nodes = makeNodes(w, h)
    }
    resize()
    window.addEventListener('resize', resize)

    const onMove = (e) => {
      mouse.x = e.clientX
      mouse.y = e.clientY
    }
    window.addEventListener('mousemove', onMove)

    const getColors = () => {
      const isDark = document.documentElement.classList.contains('dark') ||
        wrap.closest('.theme-dark')
      return isDark
        ? { node: 'rgba(150,210,195,0.8)', warm: 'rgba(196,136,95,0.85)', link: '170,225,210', mlink: '245,215,180' }
        : { node: 'rgba(79,107,94,0.7)', warm: 'rgba(143,90,26,0.75)', link: '79,107,94', mlink: '143,90,26' }
    }

    const draw = () => {
      ctx.clearRect(0, 0, w, h)
      const col = getColors()
      for (const n of nodes) {
        const dx = n.x - mouse.x
        const dy = n.y - mouse.y
        const d = Math.hypot(dx, dy)
        if (d < MOUSE_RADIUS && d > 0) {
          const f = (1 - d / MOUSE_RADIUS) * 1.4
          n.vx += (dx / d) * f * 0.1
          n.vy += (dy / d) * f * 0.1
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
            ctx.strokeStyle = `rgba(${col.link},${(1 - d / LINK_DIST) * 0.18})`
            ctx.lineWidth = 1
            ctx.beginPath()
            ctx.moveTo(a.x, a.y)
            ctx.lineTo(b.x, b.y)
            ctx.stroke()
          }
        }
        const dm = Math.hypot(a.x - mouse.x, a.y - mouse.y)
        if (dm < MOUSE_RADIUS * 1.5) {
          ctx.strokeStyle = `rgba(${col.mlink},${(1 - dm / (MOUSE_RADIUS * 1.5)) * 0.4})`
          ctx.beginPath()
          ctx.moveTo(a.x, a.y)
          ctx.lineTo(mouse.x, mouse.y)
          ctx.stroke()
        }
      }
      for (const n of nodes) {
        ctx.beginPath()
        ctx.arc(n.x, n.y, n.ring ? n.r + 4 : n.r, 0, Math.PI * 2)
        if (n.ring) {
          ctx.strokeStyle = n.warm ? col.warm : col.node
          ctx.lineWidth = 1.1
          ctx.stroke()
        } else {
          ctx.fillStyle = n.warm ? col.warm : col.node
          ctx.fill()
        }
      }
      raf = requestAnimationFrame(draw)
    }
    draw()

    return () => {
      cancelAnimationFrame(raf)
      window.removeEventListener('resize', resize)
      window.removeEventListener('mousemove', onMove)
    }
  }, [])

  return (
    <div className="live-bg" ref={wrapRef} aria-hidden="true">
      <canvas ref={canvasRef} className="auth-canvas" style={{ zIndex: 0 }} />
      <div className="auth-beams">
        <span className="auth-beam auth-beam-1" />
        <span className="auth-beam auth-beam-2" />
      </div>
    </div>
  )
}