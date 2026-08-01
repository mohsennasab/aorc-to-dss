// @vitest-environment jsdom

import { afterEach, describe, expect, it, vi } from "vitest"
import { AORCWorkbench } from "../src/ui/workbench"

const metadata = {
  variables: [
    {
      source_name: "APCP_surface",
      display_name: "Total precipitation",
      units: "kg/m^2",
      temporal_resolution: "1 hour",
      start: "1979-01-01T00:00:00Z",
      end: "2025-12-31T23:00:00Z",
      missing_value: -32767,
      description: "Hourly depth",
      aggregation: "sum",
      dss_parameter: "PRECIP",
      dss_units: "MM",
      dss_data_type: 1
    }
  ],
  years: [1979, 2025]
}

afterEach(() => {
  vi.unstubAllGlobals()
  document.body.replaceChildren()
})

describe("AORC workbench startup", () => {
  it("shows service installation help when the companion service is unavailable", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => {
      throw new TypeError("Failed to fetch")
    }))
    const openExternalUrl = vi.fn()
    const container = document.createElement("div")
    document.body.append(container)
    const workbench = new AORCWorkbench(container, {
      addGeoJsonLayer: () => "layer",
      addMapControl: () => true,
      removeMapControl: () => undefined,
      openExternalUrl
    })

    await vi.waitFor(() => {
      expect(container.querySelector<HTMLElement>("[data-service-setup]")?.hidden).toBe(false)
    })
    expect(container.querySelector("[data-service-setup]")?.textContent)
      .toContain("Windows companion service needed")

    container.querySelector<HTMLButtonElement>('[data-action="service-download"]')?.click()
    container.querySelector<HTMLButtonElement>('[data-action="service-guide"]')?.click()
    expect(openExternalUrl).toHaveBeenNthCalledWith(
      1,
      "https://github.com/mohsennasab/aorc-to-dss/releases"
    )
    expect(openExternalUrl).toHaveBeenNthCalledWith(
      2,
      "https://github.com/mohsennasab/aorc-to-dss#install-from-the-geolibre-marketplace"
    )
    workbench.destroy()
  })

  it("loads variables automatically and renders the simplified event controls", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: string | URL | Request) => {
      const url = String(input)
      const body = url.endsWith("/health")
        ? { status: "ok", version: "0.2.0", dss: { available: true, message: "ready" } }
        : metadata
      return {
        ok: true,
        json: async () => body,
        arrayBuffer: async () => new ArrayBuffer(0)
      } as Response
    }))
    const container = document.createElement("div")
    document.body.append(container)
    const workbench = new AORCWorkbench(container, {
      addGeoJsonLayer: () => "layer",
      addMapControl: () => true,
      removeMapControl: () => undefined
    })

    await vi.waitFor(() => {
      expect(container.querySelector<HTMLSelectElement>('[data-field="variable"]')?.value)
        .toBe("APCP_surface")
    })

    expect(container.textContent).not.toContain("Reload archive metadata")
    expect(container.textContent).not.toContain("Automatic precipitation event separation")
    expect(container.textContent).not.toContain("Rolling maximum")
    expect(container.querySelector("[data-series-table]")).toBeNull()
    expect(container.querySelector('[data-field="averaging-method"]')).toBeNull()
    expect(container.textContent).toContain("The AOI mean is area weighted")
    expect(container.querySelectorAll("[data-duration]")).toHaveLength(4)
    expect(container.querySelector('[data-duration="96"]')).not.toBeNull()
    expect(container.querySelector<HTMLSelectElement>('[data-field="cell-size"]')?.textContent)
      .toContain("4000 m")
    expect(container.querySelector("[data-event-chart]")).not.toBeNull()
    expect(Array.from(container.querySelectorAll(".a2d-page h2")).map(item => item.textContent))
      .toEqual([
        "AOI Selection",
        "AORC Data",
        "AOI Time Series",
        "Event Selection",
        "DSS Export",
        "Results"
      ])
    expect(container.querySelector(".a2d-tabs")?.textContent?.replace(/\s/g, "")).toBe("123456")
    workbench.destroy()
  })

  it("preloads frames before explicitly creating GeoLibre's native Time Slider", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: string | URL | Request) => {
      const url = String(input)
      const body = url.endsWith("/health")
        ? { status: "ok", version: "0.2.0", dss: { available: true, message: "ready" } }
        : url.endsWith("/animations")
          ? {
              id: "animation-1",
              times: ["2025-10-27T00:00:00Z", "2025-10-27T01:00:00Z"],
              url_template: "/animations/animation-1/{date:YYYY-MM-DD-HH}.tif",
              bounds: [-90, 35, -89, 36],
              units: "in",
              colormap: "gist_ncar",
              rescale: [0, 0.5],
              nodata: -9999
            }
          : url.endsWith("/preload")
            ? {
                id: "animation-1",
                state: "queued",
                progress: 0,
                completed: 0,
                total: 2,
                message: "Queued",
                error: null
              }
            : url.endsWith("/animations/animation-1")
              ? {
                  id: "animation-1",
                  state: "complete",
                  progress: 1,
                  completed: 2,
                  total: 2,
                  message: "All frames ready",
                  error: null
                }
          : metadata
      return {
        ok: true,
        json: async () => body,
        arrayBuffer: async () => new ArrayBuffer(0)
      } as Response
    }))
    const activatePlugin = vi.fn(async (_pluginId: string, _state?: unknown) => true)
    const addCogLayer = vi.fn(async () => "cog")
    const addZarrLayer = vi.fn(async () => "zarr")
    const container = document.createElement("div")
    document.body.append(container)
    const workbench = new AORCWorkbench(container, {
      addGeoJsonLayer: () => "layer",
      addMapControl: () => true,
      removeMapControl: () => undefined,
      addCogLayer,
      addZarrLayer,
      activatePlugin
    })
    await vi.waitFor(() => {
      expect(container.querySelector<HTMLSelectElement>('[data-field="variable"]')?.value)
        .toBe("APCP_surface")
    })
    ;(workbench as any).state.aoi = {
      type: "FeatureCollection",
      features: [{
        type: "Feature",
        geometry: {
          type: "Polygon",
          coordinates: [[[-90, 35], [-89, 35], [-89, 36], [-90, 36], [-90, 35]]]
        }
      }]
    }
    ;(workbench as any).state.start = "2025-10-26T23:00:00.000Z"
    ;(workbench as any).state.end = "2025-10-27T01:00:00.000Z"
    const points = [
      { time: "2025-10-27T00:00:00Z", value: 0.1, units: "in", quality: "ok" },
      { time: "2025-10-27T01:00:00Z", value: 0.2, units: "in", quality: "ok" }
    ]
    ;(workbench as any).points = points
    ;(workbench as any).event = {
      start: "2025-10-26T23:00:00.000Z",
      end: "2025-10-27T01:00:00.000Z"
    }
    ;(workbench as any).updateDefaultDssFilename()
    expect(container.querySelector<HTMLInputElement>('[data-field="dss-filename"]')?.value)
      .toBe("aorc_20251026t2300z_002h_shg2k_precipitation.dss")
    expect((workbench as any).analysisArtifactFilename("csv"))
      .toBe("aorc_20251026t2300z_002h_aoi_area_weighted_average_precipitation.csv")
    ;(workbench as any).selectedEventPoints = points
    const setCursorTime = vi.fn()
    ;(workbench as any).eventChart = {
      setCursorTime,
      destroy: vi.fn()
    }
    const timeSliderDock = document.createElement("div")
    timeSliderDock.className = "maplibregl-time-slider-dock"
    const markerLabel = document.createElement("div")
    markerLabel.className = "ts-marker-label"
    markerLabel.textContent = "2025 Oct 26 23:00"
    timeSliderDock.appendChild(markerLabel)
    document.body.appendChild(timeSliderDock)
    expect(activatePlugin).not.toHaveBeenCalled()
    await (workbench as any).createEventAnimation()

    expect(activatePlugin).toHaveBeenCalled()
    const [pluginId, rawConfig] = activatePlugin.mock.calls.at(-1)!
    const config = rawConfig as any
    expect(pluginId).toBe("maplibre-gl-time-slider")
    expect(config.granularity).toBe("hour")
    expect(config.dates).toHaveLength(2)
    expect(config.sources[0]).toMatchObject({
      type: "cog",
      engine: "gpu",
      colormap: "gist_ncar",
      nodata: -9999,
      bounds: [-90, 35, -89, 36]
    })
    expect(config.sources[0].url).toContain("{date:YYYY-MM-DD-HH}")
    expect(config.onChange).toBeUndefined()
    markerLabel.textContent = "2025 Oct 27 01:00"
    await Promise.resolve()
    expect(setCursorTime).toHaveBeenLastCalledWith("2025-10-27T01:00:00Z")
    const frameRequests = (globalThis.fetch as any).mock.calls
      .map((call: any[]) => String(call[0]))
      .filter((url: string) => url.endsWith(".tif"))
    expect(frameRequests).toHaveLength(2)
    expect(container.querySelector("[data-animation-status]")?.textContent)
      .toContain("Time Slider animation is ready to play")
    expect(container.querySelector<HTMLElement>("[data-animation-legend]")?.hidden).toBe(false)
    expect(container.querySelector("[data-animation-legend]")?.textContent)
      .toContain("Hourly Precipitation (in)")
    expect(container.querySelector("[data-animation-legend]")?.textContent)
      .toContain("AOI chart is area weighted")

    await (workbench as any).renderResults({
      id: "job-1",
      result: {
        validation: [],
        output_dir: "C:\\output",
        pathnames: [],
        dss_file: "C:\\output\\event.dss",
        cog_file: "C:\\output\\rasters\\aorc_summary.tif",
        visualization: {
          colormap: "gist_ncar",
          rescale_min: 0,
          rescale_max: 2.5,
          nodata: -9999
        }
      }
    })
    expect(addCogLayer).toHaveBeenLastCalledWith(
      "AORC event summary",
      expect.stringContaining("rasters/aorc_summary.tif"),
      expect.objectContaining({
        colormap: "gist_ncar",
        rescaleMin: 0,
        rescaleMax: 2.5,
        nodata: -9999
      })
    )
    expect(addZarrLayer).not.toHaveBeenCalled()
    workbench.destroy()
  })
})
