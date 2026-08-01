// @vitest-environment jsdom

import { afterEach, describe, expect, it, vi } from "vitest"
import { TimeSeriesChart } from "../src/ui/timeseries-chart"

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
  document.body.replaceChildren()
})

describe("TimeSeriesChart labels", () => {
  it("draws the selected variable and AOI statistic into the visible and saved canvas", () => {
    const fillText = vi.fn()
    const context = {
      setTransform: vi.fn(), clearRect: vi.fn(), fillRect: vi.fn(), beginPath: vi.fn(),
      moveTo: vi.fn(), lineTo: vi.fn(), stroke: vi.fn(), fill: vi.fn(), arc: vi.fn(),
      save: vi.fn(), restore: vi.fn(), translate: vi.fn(), rotate: vi.fn(),
      fillText, measureText: (text: string) => ({ width: text.length * 7 })
    } as unknown as CanvasRenderingContext2D
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(context)
    vi.spyOn(HTMLCanvasElement.prototype, "clientWidth", "get").mockReturnValue(640)
    vi.spyOn(HTMLCanvasElement.prototype, "clientHeight", "get").mockReturnValue(320)
    vi.stubGlobal("ResizeObserver", class {
      observe(): void {}
      disconnect(): void {}
    })
    const host = document.createElement("div")
    document.body.append(host)
    const chart = new TimeSeriesChart(host, {
      units: "°C",
      title: "Air Temperature — AOI Area-Weighted Average",
      statisticLabel: "AOI area-weighted average",
      zeroBaseline: false
    })
    fillText.mockClear()
    chart.setData([
      { time: "2025-01-01T00:00:00Z", value: 20, units: "°C", quality: "ok" },
      { time: "2025-01-01T01:00:00Z", value: 21, units: "°C", quality: "ok" }
    ])
    const labels = fillText.mock.calls.map(call => String(call[0]))
    expect(labels).toContain("Air Temperature — AOI Area-Weighted Average")
    expect(labels).toContain("AOI area-weighted average (°C) · UTC")
    expect(labels).toContain("AOI area-weighted average (°C)")
    expect(labels).not.toContain("0.00")
    expect(host.querySelector("canvas")?.getAttribute("aria-label"))
      .toContain("Air Temperature — AOI Area-Weighted Average")
    chart.destroy()
  })
})
