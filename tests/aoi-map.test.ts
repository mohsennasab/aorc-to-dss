// @vitest-environment jsdom

import { describe, expect, it, vi } from "vitest"
import { AoiMapController } from "../src/ui/aoi-map"

describe("AOI map drawing", () => {
  it("shows live vertices and a closing boundary, then finishes reliably", () => {
    const handlers = new Map<string, (event: any) => void>()
    const layers = new Map<string, any>()
    let displayed: any = null
    const source = { setData: vi.fn((data: any) => { displayed = data }) }
    let zoomEnabled = true
    const map = {
      on: vi.fn((event: string, handler: (event: any) => void) => handlers.set(event, handler)),
      off: vi.fn((event: string, handler: (event: any) => void) => {
        if (handlers.get(event) === handler) handlers.delete(event)
      }),
      once: vi.fn(),
      getSource: vi.fn(() => source),
      addSource: vi.fn(),
      removeSource: vi.fn(),
      getLayer: vi.fn((id: string) => layers.get(id)),
      addLayer: vi.fn((layer: any) => layers.set(layer.id, layer)),
      removeLayer: vi.fn((id: string) => layers.delete(id)),
      queryRenderedFeatures: vi.fn(() => []),
      getCanvas: () => document.createElement("canvas"),
      doubleClickZoom: {
        disable: vi.fn(() => { zoomEnabled = false }),
        enable: vi.fn(() => { zoomEnabled = true }),
        isEnabled: () => zoomEnabled
      }
    }
    const changed = vi.fn()
    const controller = new AoiMapController(
      {
        getMap: () => map as any,
        addGeoJsonLayer: () => "layer",
        addMapControl: () => true,
        removeMapControl: () => undefined
      },
      changed,
      vi.fn()
    )

    controller.startDrawing()
    expect(map.doubleClickZoom.disable).toHaveBeenCalled()
    handlers.get("click")!({ lngLat: { lng: -90, lat: 35 } })
    handlers.get("click")!({ lngLat: { lng: -89, lat: 35 } })
    handlers.get("mousemove")!({ lngLat: { lng: -89, lat: 36 } })

    expect(displayed.features.filter((feature: any) => feature.geometry.type === "Point"))
      .toHaveLength(2)
    const preview = displayed.features.find((feature: any) =>
      feature.geometry.type === "LineString"
    )
    expect(preview.geometry.coordinates.at(-1)).toEqual([-90, 35])
    expect(layers.has("aorctodss-aoi-vertices")).toBe(true)

    handlers.get("click")!({ lngLat: { lng: -89, lat: 36 } })
    controller.finishDrawing()
    expect(changed).toHaveBeenCalledOnce()
    expect(changed.mock.calls[0]![0].features[0].geometry.type).toBe("Polygon")
    expect(map.doubleClickZoom.enable).toHaveBeenCalled()
  })
})
