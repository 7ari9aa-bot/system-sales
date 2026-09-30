import React, { useRef, useEffect } from 'react'

const NODE_COUNT = 52
const LINK_DIST = 155
const MOUSE_RADIUS = 200

function makeNodes(w, h) {
  const nodes = []
  const leftCount = Math.ceil(NODE_COUNT * 0.62)
  const rightCount = NODE_COUNT - leftCount
  for (let k = 0; k < leftCount; k++) {
    nodes.push({
      x: Math.random() * (w * 0.48),
      y: Math.random() * h,
      vx: (Math.random() - 0.5) * 0.45,
      vy: (Math.random() - 0.5) * 0.45,
      r: 1.5 + Math.random() * 3.2,
      ring: Math.random() < 0.22,
      warm: Math.random() < 0.3,
    })
  }
  for (let k = 0; k < rightCount; k++) {
    nodes.push({
      x: w * 0.52 + Math.random() * (w * 0.48),
      y: Math.random() * h,
      vx: (Math.random() - 0.5) * 0.35,
      vy: (Math.random() - 0.5) * 0.35,
      r: 1.5 + Math.random() * 2.5,
      ring: Math.random() < 0.22,
      warm: Math.random() < 0.3,
    })
  }
  return nodes
}

export default function HeroRelationCanvas() {
  const canvasRef = useRef(null)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const parent = canvas.parentElement
    const ctx = canvas.getContext('2d')
    const mouse = { x: -9999, y: -9999 }
    let w = 0, h = 0, nodes = [], raf

    const resize = () => {
      const dpr = window.devicePixelRatio || 1
      w = parent.clientWidth
      h = parent.clientHeight
      canvas.width = w * dpr
      canvas.height = h * dpr
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      nodes = makeNodes(w, h)
    }
    resize()
    window.addEventListener('resize', resize)

    const onMove = (e) => {
      const rect = parent.getBoundingClientRect()
      const x = e.clientX - rect.left
      const y = e.clientY - rect.top
      if (x >= 0 && x <= rect.width && y >= 0 && y <= rect.height) {
        mouse.x = x; mouse.y = y
      } else {
        mouse.x = mouse.y = -9999
      }
    }
    window.addEventListener('mousemove', onMove)

    const draw = () => {
      ctx.clearRect(0, 0, w, h)
      for (const n of nodes) {
        const dx = n.x - mouse.x
        const dy = n.y - mouse.y
        const d = Math.hypot(dx, dy)
        if (d < MOUSE_RADIUS && d > 0) {
          const f = (1 - d / MOUSE_RADIUS) * 1.1
          n.vx += (dx / d) * f * 0.08
          n.vy += (dy / d) * f * 0.08
        }
        n.vx *= 0.99
        n.vy *= 0.99
        const sp = Math.hypot(n.vx, n.vy)
        if (sp < 0.12) {
          const ang = Math.atan2(n.vy || (Math.random() - 0.5), n.vx || (Math.random() - 0.5))
          n.vx = Math.cos(ang) * 0.16
          n.vy = Math.sin(ang) * 0.16
        }
        if (sp > 1.3) { n.vx = (n.vx / sp) * 1.3; n.vy = (n.vy / sp) * 1.3 }
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
            ctx.strokeStyle = `rgba(79,107,94,${(1 - d / LINK_DIST) * 0.15})`
            ctx.lineWidth = 1
            ctx.beginPath()
            ctx.moveTo(a.x, a.y)
            ctx.lineTo(b.x, b.y)
            ctx.stroke()
          }
        }
        const dm = Math.hypot(a.x - mouse.x, a.y - mouse.y)
        if (dm < MOUSE_RADIUS * 1.4) {
          ctx.strokeStyle = `rgba(143,90,26,${(1 - dm / (MOUSE_RADIUS * 1.4)) * 0.33})`
          ctx.lineWidth = 1
          ctx.beginPath()
          ctx.moveTo(a.x, a.y)
          ctx.lineTo(mouse.x, mouse.y)
          ctx.stroke()
        }
      }
      for (const n of nodes) {
        const color = n.warm ? 'rgba(143,90,26,0.62)' : 'rgba(79,107,94,0.58)'
        ctx.beginPath()
        ctx.arc(n.x, n.y, n.ring ? n.r + 3 : n.r, 0, Math.PI * 2)
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
      window.removeEventListener('mousemove', onMove)
    }
  }, [])

  return <canvas ref={canvasRef} className="hero-canvas" aria-hidden="true" />
}