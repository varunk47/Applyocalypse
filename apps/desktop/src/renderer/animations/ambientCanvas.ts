interface Dot {
  x: number
  y: number
  baseX: number
  baseY: number
  phase: number
  speed: number
  radius: number
  opacity: number
}

export const mountAmbientCanvas = (canvas: HTMLCanvasElement): () => void => {
  const ctx = canvas.getContext('2d')!
  const spacing = 42
  const dots: Dot[] = []
  let rafId: number
  let time = 0

  const resize = () => {
    canvas.width = window.innerWidth
    canvas.height = window.innerHeight
    dots.length = 0
    const cols = Math.ceil(canvas.width / spacing) + 2
    const rows = Math.ceil(canvas.height / spacing) + 2
    for (let c = 0; c < cols; c++) {
      for (let r = 0; r < rows; r++) {
        dots.push({
          x: c * spacing,
          y: r * spacing,
          baseX: c * spacing,
          baseY: r * spacing,
          phase: Math.random() * Math.PI * 2,
          speed: 0.3 + Math.random() * 0.4,
          radius: 1 + Math.random() * 0.8,
          opacity: 0.05 + Math.random() * 0.1,
        })
      }
    }
  }

  const draw = () => {
    time += 0.004
    ctx.clearRect(0, 0, canvas.width, canvas.height)
    for (const dot of dots) {
      dot.x = dot.baseX + Math.sin(time * dot.speed + dot.phase) * 3
      dot.y = dot.baseY + Math.cos(time * dot.speed * 0.7 + dot.phase) * 3
      ctx.beginPath()
      ctx.arc(dot.x, dot.y, dot.radius, 0, Math.PI * 2)
      ctx.fillStyle = `rgba(61, 142, 240, ${dot.opacity})`
      ctx.fill()
    }
    rafId = requestAnimationFrame(draw)
  }

  resize()
  window.addEventListener('resize', resize)
  draw()

  return () => {
    cancelAnimationFrame(rafId)
    window.removeEventListener('resize', resize)
  }
}
