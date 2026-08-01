import type { TimeSeriesPoint } from "../types"

interface ChartOptions {
  units: string
  title: string
  statisticLabel: string
  zeroBaseline?: boolean
  onRange?: (start: string, end: string) => void
}

export class TimeSeriesChart {
  private readonly canvas = document.createElement("canvas")
  private readonly tooltip = document.createElement("div")
  private readonly context: CanvasRenderingContext2D
  private points: TimeSeriesPoint[] = []
  private times: number[] = []
  private minTime = 0
  private maxTime = 1
  private viewStart = 0
  private viewEnd = 1
  private dragStart: { x: number; time: number } | null = null
  private panMode = false
  private cursorTime: number | null = null
  private observer: ResizeObserver

  constructor(private readonly container: HTMLElement, private readonly options: ChartOptions) {
    const context = this.canvas.getContext("2d")
    if (!context) throw new Error("Canvas is not available")
    this.context = context
    this.canvas.className = "a2d-chart-canvas"
    this.canvas.setAttribute("aria-label", `${options.title}, ${options.statisticLabel} in ${options.units}`)
    this.tooltip.className = "a2d-chart-tooltip"
    container.classList.add("a2d-chart")
    container.append(this.canvas, this.tooltip)
    this.canvas.addEventListener("wheel", this.onWheel, { passive: false })
    this.canvas.addEventListener("pointerdown", this.onPointerDown)
    this.canvas.addEventListener("pointermove", this.onPointerMove)
    this.canvas.addEventListener("pointerup", this.onPointerUp)
    this.canvas.addEventListener("pointerleave", () => {
      this.tooltip.hidden = true
    })
    this.observer = new ResizeObserver(() => this.resize())
    this.observer.observe(container)
    this.resize()
  }

  setData(points: TimeSeriesPoint[]): void {
    this.points = points
    this.times = points.map(point => new Date(point.time).getTime())
    this.minTime = this.times[0] ?? 0
    this.maxTime = this.times[this.times.length - 1] ?? this.minTime + 1
    if (this.maxTime === this.minTime) this.maxTime += 3_600_000
    this.reset()
  }

  setCursorTime(value: Date | string | null): void {
    this.cursorTime = value === null ? null : new Date(value).getTime()
    this.draw()
  }

  reset(): void {
    this.viewStart = this.minTime
    this.viewEnd = this.maxTime
    this.draw()
  }

  pngDataUrl(): string {
    return this.canvas.toDataURL("image/png")
  }

  destroy(): void {
    this.observer.disconnect()
    this.canvas.removeEventListener("wheel", this.onWheel)
    this.canvas.removeEventListener("pointerdown", this.onPointerDown)
    this.canvas.removeEventListener("pointermove", this.onPointerMove)
    this.canvas.removeEventListener("pointerup", this.onPointerUp)
    this.container.replaceChildren()
  }

  private resize(): void {
    const ratio = window.devicePixelRatio || 1
    const width = Math.max(280, this.container.clientWidth)
    const height = Math.max(220, this.container.clientHeight)
    this.canvas.width = width * ratio
    this.canvas.height = height * ratio
    this.canvas.style.width = `${width}px`
    this.canvas.style.height = `${height}px`
    this.context.setTransform(ratio, 0, 0, ratio, 0, 0)
    this.draw()
  }

  private dimensions(): { width: number; height: number; left: number; top: number; plotWidth: number; plotHeight: number } {
    const width = this.canvas.clientWidth
    const height = this.canvas.clientHeight
    return { width, height, left: 104, top: 58, plotWidth: width - 120, plotHeight: height - 100 }
  }

  private visible(): Array<{ point: TimeSeriesPoint; time: number }> {
    return this.points
      .map((point, index) => ({ point, time: this.times[index]! }))
      .filter(item => item.time >= this.viewStart && item.time <= this.viewEnd)
  }

  private draw(): void {
    const { width, height, left, top, plotWidth, plotHeight } = this.dimensions()
    const ctx = this.context
    ctx.clearRect(0, 0, width, height)
    ctx.fillStyle = getComputedStyle(this.container).getPropertyValue("--a2d-chart-bg") || "#ffffff"
    ctx.fillRect(0, 0, width, height)
    const visible = this.visible()
    const values = visible.flatMap(item => item.point.value === null ? [] : [item.point.value])
    const rawMin = values.length ? Math.min(...values) : 0
    const rawMax = values.length ? Math.max(...values) : 1
    const padding = Math.max((rawMax - rawMin) * 0.08, Math.abs(rawMax) * 0.01, 1.0e-6)
    const minValue = this.options.zeroBaseline ? Math.min(0, rawMin) : rawMin - padding
    const maxValue = rawMax + padding
    const range = maxValue - minValue || 1
    ctx.strokeStyle = "rgba(120, 130, 140, 0.25)"
    ctx.fillStyle = getComputedStyle(this.container).color
    ctx.font = "11px system-ui"
    ctx.lineWidth = 1
    ctx.textAlign = "right"
    ctx.save()
    ctx.textAlign = "left"
    ctx.font = "600 15px system-ui"
    if (ctx.measureText(this.options.title).width > width - 32) {
      ctx.font = "600 12px system-ui"
    }
    ctx.fillText(this.options.title, 16, 22)
    ctx.font = "11px system-ui"
    ctx.fillStyle = "#64748b"
    ctx.fillText(`${this.options.statisticLabel} (${this.options.units}) · UTC`, 16, 42)
    ctx.restore()
    ctx.fillStyle = getComputedStyle(this.container).color
    ctx.font = "11px system-ui"
    for (let step = 0; step <= 4; step += 1) {
      const y = top + plotHeight * step / 4
      ctx.beginPath()
      ctx.moveTo(left, y)
      ctx.lineTo(left + plotWidth, y)
      ctx.stroke()
      const label = (maxValue - range * step / 4).toFixed(2)
      ctx.fillText(label, left - 10, y + 4)
    }
    const x = (time: number) => left + (time - this.viewStart) / (this.viewEnd - this.viewStart) * plotWidth
    const y = (value: number) => top + (maxValue - value) / range * plotHeight
    ctx.strokeStyle = "#1683b6"
    ctx.lineWidth = 1.5
    ctx.beginPath()
    const stride = Math.max(1, Math.floor(visible.length / Math.max(plotWidth * 2, 1)))
    let drawing = false
    visible.forEach((item, index) => {
      if (index % stride && index !== visible.length - 1) return
      if (item.point.value === null) {
        drawing = false
        return
      }
      const px = x(item.time)
      const py = y(item.point.value)
      if (drawing) ctx.lineTo(px, py)
      else {
        ctx.moveTo(px, py)
        drawing = true
      }
    })
    ctx.stroke()
    if (this.cursorTime !== null && this.points.length) {
      const index = this.times.reduce((best, value, candidate) =>
        Math.abs(value - this.cursorTime!) < Math.abs(this.times[best]! - this.cursorTime!)
          ? candidate
          : best
      , 0)
      const point = this.points[index]
      const time = this.times[index]
      if (
        point?.value !== null &&
        point?.value !== undefined &&
        time !== undefined &&
        time >= this.viewStart &&
        time <= this.viewEnd
      ) {
        const px = x(time)
        const py = y(point.value)
        ctx.strokeStyle = "rgba(201, 48, 44, 0.55)"
        ctx.lineWidth = 1
        ctx.beginPath()
        ctx.moveTo(px, top)
        ctx.lineTo(px, top + plotHeight)
        ctx.stroke()
        ctx.fillStyle = "#c9302c"
        ctx.beginPath()
        ctx.arc(px, py, 5, 0, Math.PI * 2)
        ctx.fill()
        ctx.strokeStyle = "#ffffff"
        ctx.lineWidth = 1.5
        ctx.stroke()
      }
    }
    ctx.fillStyle = getComputedStyle(this.container).color
    const startLabel = new Date(this.viewStart).toISOString().slice(0, 10)
    const endLabel = new Date(this.viewEnd).toISOString().slice(0, 10)
    ctx.textAlign = "left"
    ctx.fillText(startLabel, left, height - 12)
    const endWidth = ctx.measureText(endLabel).width
    ctx.fillText(endLabel, left + plotWidth - endWidth, height - 12)
    ctx.save()
    ctx.translate(16, top + plotHeight / 2)
    ctx.rotate(-Math.PI / 2)
    ctx.textAlign = "center"
    ctx.fillText(`${this.options.statisticLabel} (${this.options.units})`, 0, 0)
    ctx.restore()
  }

  private timeAt(clientX: number): number {
    const box = this.canvas.getBoundingClientRect()
    const { left, plotWidth } = this.dimensions()
    const x = Math.max(left, Math.min(left + plotWidth, clientX - box.left))
    return this.viewStart + (x - left) / plotWidth * (this.viewEnd - this.viewStart)
  }

  private readonly onWheel = (event: WheelEvent): void => {
    event.preventDefault()
    const anchor = this.timeAt(event.clientX)
    const factor = event.deltaY > 0 ? 1.25 : 0.8
    const start = anchor - (anchor - this.viewStart) * factor
    const end = anchor + (this.viewEnd - anchor) * factor
    const minimumWindow = 3_600_000
    if (end - start < minimumWindow) return
    this.viewStart = Math.max(this.minTime, start)
    this.viewEnd = Math.min(this.maxTime, end)
    this.draw()
  }

  private readonly onPointerDown = (event: PointerEvent): void => {
    this.canvas.setPointerCapture(event.pointerId)
    this.dragStart = { x: event.clientX, time: this.timeAt(event.clientX) }
    this.panMode = event.shiftKey
  }

  private readonly onPointerMove = (event: PointerEvent): void => {
    if (this.dragStart && this.panMode) {
      const current = this.timeAt(event.clientX)
      const delta = this.dragStart.time - current
      const width = this.viewEnd - this.viewStart
      let start = this.viewStart + delta
      start = Math.max(this.minTime, Math.min(this.maxTime - width, start))
      this.viewStart = start
      this.viewEnd = start + width
      this.dragStart = { x: event.clientX, time: this.timeAt(event.clientX) }
      this.draw()
      return
    }
    if (!this.points.length) return
    const time = this.timeAt(event.clientX)
    let low = 0
    let high = this.times.length - 1
    while (low < high) {
      const middle = Math.floor((low + high) / 2)
      if (this.times[middle]! < time) low = middle + 1
      else high = middle
    }
    const candidates = [low, Math.max(0, low - 1)]
    const index = candidates.reduce((best, value) =>
      Math.abs(this.times[value]! - time) < Math.abs(this.times[best]! - time) ? value : best
    )
    const point = this.points[index]!
    const box = this.canvas.getBoundingClientRect()
    this.tooltip.hidden = false
    this.tooltip.style.left = `${event.clientX - box.left + 10}px`
    this.tooltip.style.top = `${event.clientY - box.top + 10}px`
    this.tooltip.textContent = `${point.time}  ${point.value ?? "missing"} ${point.units}`
  }

  private readonly onPointerUp = (event: PointerEvent): void => {
    if (!this.dragStart) return
    const start = this.dragStart
    this.dragStart = null
    if (this.panMode) {
      this.panMode = false
      return
    }
    if (Math.abs(event.clientX - start.x) < 5) return
    const a = start.time
    const b = this.timeAt(event.clientX)
    const startTime = new Date(Math.min(a, b))
    const endTime = new Date(Math.max(a, b))
    startTime.setUTCMinutes(0, 0, 0)
    endTime.setUTCMinutes(0, 0, 0)
    if (endTime <= startTime) endTime.setUTCHours(endTime.getUTCHours() + 1)
    this.options.onRange?.(startTime.toISOString(), endTime.toISOString())
  }
}
