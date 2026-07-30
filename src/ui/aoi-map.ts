import type { Feature, FeatureCollection, GeoLibreAppAPI, MapFeature, MapLike } from "../types"

const SOURCE_ID = "aorctodss-aoi"
const FILL_ID = "aorctodss-aoi-fill"
const LINE_ID = "aorctodss-aoi-line"
const VERTEX_ID = "aorctodss-aoi-vertices"

export class AoiMapController {
  private map: MapLike | null = null
  private drawing: Array<[number, number]> | null = null
  private captureMode = false
  private restoreDoubleClickZoom = false
  private current: FeatureCollection = { type: "FeatureCollection", features: [] }

  constructor(
    private readonly app: GeoLibreAppAPI,
    private readonly onChange: (collection: FeatureCollection) => void,
    private readonly onMessage: (message: string) => void
  ) {
    this.map = app.getMap?.() ?? null
  }

  set(collection: FeatureCollection): void {
    this.current = collection
    this.ensureLayers()
    this.map?.getSource(SOURCE_ID)?.setData(collection)
    try {
      this.app.fitBounds?.(this.bounds(collection))
    } catch {
      this.onMessage("Area loaded. Map extent could not be changed.")
    }
  }

  clear(): void {
    this.stopTools()
    this.current = { type: "FeatureCollection", features: [] }
    this.map?.getSource(SOURCE_ID)?.setData(this.current)
  }

  startDrawing(): void {
    const map = this.requireMap()
    this.stopTools()
    this.drawing = []
    this.map?.getSource(SOURCE_ID)?.setData({
      type: "FeatureCollection",
      features: []
    })
    this.restoreDoubleClickZoom = map.doubleClickZoom?.isEnabled?.() ?? true
    map.doubleClickZoom?.disable()
    map.getCanvas().style.cursor = "crosshair"
    map.on("click", this.onDrawClick)
    map.on("dblclick", this.onDrawDoubleClick)
    map.on("mousemove", this.onDrawMove)
    this.onMessage(
      "Drawing started. Click vertices; move the pointer to preview the boundary. " +
      "Double-click or use Finish polygon when done."
    )
  }

  undoDrawingVertex(): void {
    if (!this.drawing) {
      this.onMessage("Select Draw polygon before undoing a vertex.")
      return
    }
    this.drawing.pop()
    this.updateDrawing()
    this.onMessage(`${this.drawing.length} fixed vertices. Continue drawing or finish.`)
  }

  finishDrawing(): void {
    if (!this.drawing) {
      this.onMessage("Select Draw polygon before finishing.")
      return
    }
    const vertices = this.drawing.filter((point, index, values) =>
      index === 0 || !this.samePoint(point, values[index - 1]!)
    )
    if (vertices.length > 1 && this.samePoint(vertices[0]!, vertices.at(-1)!)) {
      vertices.pop()
    }
    if (vertices.length < 3) {
      this.onMessage("A polygon needs at least three distinct vertices.")
      return
    }
    const ring = [...vertices, vertices[0]!]
    const collection: FeatureCollection = {
      type: "FeatureCollection",
      features: [{
        type: "Feature",
        properties: { source: "drawn in GeoLibre" },
        geometry: { type: "Polygon", coordinates: [ring] }
      }]
    }
    this.stopTools(false)
    this.set(collection)
    this.onChange(collection)
  }

  captureLoadedPolygon(): void {
    const map = this.requireMap()
    this.stopTools()
    this.captureMode = true
    map.getCanvas().style.cursor = "crosshair"
    map.on("click", this.onCaptureClick)
    this.onMessage("Click a polygon from a loaded map layer.")
  }

  destroy(): void {
    this.stopTools()
    if (!this.map) return
    if (this.map.getLayer(VERTEX_ID)) this.map.removeLayer(VERTEX_ID)
    if (this.map.getLayer(FILL_ID)) this.map.removeLayer(FILL_ID)
    if (this.map.getLayer(LINE_ID)) this.map.removeLayer(LINE_ID)
    if (this.map.getSource(SOURCE_ID)) this.map.removeSource(SOURCE_ID)
  }

  private requireMap(): MapLike {
    this.map = this.app.getMap?.() ?? this.map
    if (!this.map) throw new Error("The GeoLibre map is not ready")
    this.ensureLayers()
    return this.map
  }

  private ensureLayers(): void {
    if (!this.map) return
    if (!this.map.getSource(SOURCE_ID)) {
      this.map.addSource(SOURCE_ID, { type: "geojson", data: this.current })
    }
    if (!this.map.getLayer(FILL_ID)) {
      this.map.addLayer({
        id: FILL_ID,
        type: "fill",
        source: SOURCE_ID,
        paint: {
          "fill-color": "#f59e0b",
          "fill-opacity": 0.22
        }
      })
    }
    if (!this.map.getLayer(LINE_ID)) {
      this.map.addLayer({
        id: LINE_ID,
        type: "line",
        source: SOURCE_ID,
        paint: {
          "line-color": "#f15a24",
          "line-width": 3
        }
      })
    }
    if (!this.map.getLayer(VERTEX_ID)) {
      this.map.addLayer({
        id: VERTEX_ID,
        type: "circle",
        source: SOURCE_ID,
        paint: {
          "circle-radius": 5,
          "circle-color": "#ffffff",
          "circle-stroke-color": "#f15a24",
          "circle-stroke-width": 3
        }
      })
    }
  }

  private stopTools(restoreCurrent = true): void {
    if (!this.map) return
    this.map.off("click", this.onDrawClick)
    this.map.off("dblclick", this.onDrawDoubleClick)
    this.map.off("mousemove", this.onDrawMove)
    this.map.off("click", this.onCaptureClick)
    if (this.restoreDoubleClickZoom) this.map.doubleClickZoom?.enable()
    this.restoreDoubleClickZoom = false
    this.map.getCanvas().style.cursor = ""
    this.drawing = null
    this.captureMode = false
    if (restoreCurrent) this.map.getSource(SOURCE_ID)?.setData(this.current)
  }

  private readonly onDrawClick = (event: any): void => {
    if (!this.drawing) return
    this.drawing.push([event.lngLat.lng, event.lngLat.lat])
    this.updateDrawing()
    this.onMessage(`${this.drawing.length} fixed vertices. Double-click or use Finish polygon.`)
  }

  private readonly onDrawDoubleClick = (event: any): void => {
    event.preventDefault?.()
    event.originalEvent?.preventDefault?.()
    this.finishDrawing()
  }

  private readonly onDrawMove = (event: any): void => {
    if (!this.drawing) return
    this.updateDrawing([event.lngLat.lng, event.lngLat.lat])
  }

  private updateDrawing(cursor?: [number, number]): void {
    if (!this.drawing) return
    const features: Feature[] = this.drawing.map((coordinates, index) => ({
      type: "Feature",
      properties: { vertex: index + 1 },
      geometry: { type: "Point", coordinates }
    }))
    const preview = cursor ? [...this.drawing, cursor] : [...this.drawing]
    if (preview.length >= 2) {
      const boundary = preview.length >= 3
        ? [...preview, preview[0]!]
        : preview
      if (preview.length >= 3) {
        features.unshift({
          type: "Feature",
          properties: { preview: true },
          geometry: { type: "Polygon", coordinates: [boundary] }
        })
      }
      features.push({
        type: "Feature",
        properties: { preview: true },
        geometry: { type: "LineString", coordinates: boundary }
      })
    }
    this.map?.getSource(SOURCE_ID)?.setData({
      type: "FeatureCollection",
      features
    })
  }

  private samePoint(first: [number, number], second: [number, number]): boolean {
    return Math.abs(first[0] - second[0]) < 1e-10 &&
      Math.abs(first[1] - second[1]) < 1e-10
  }

  private readonly onCaptureClick = (event: any): void => {
    if (!this.captureMode || !this.map) return
    const features = this.map.queryRenderedFeatures(event.point)
      .filter(feature => ["Polygon", "MultiPolygon"].includes(feature.geometry.type))
    const feature = this.pickFeature(features)
    if (!feature) {
      this.onMessage("No polygon was found at that location.")
      return
    }
    const collection: FeatureCollection = {
      type: "FeatureCollection",
      features: [{
        type: "Feature",
        properties: {
          ...feature.properties,
          source_layer: feature.layer?.id ?? "",
          source: feature.source ?? ""
        },
        geometry: feature.geometry
      }]
    }
    this.stopTools()
    this.set(collection)
    this.onChange(collection)
  }

  private pickFeature(features: MapFeature[]): MapFeature | undefined {
    return features.find(feature => !feature.layer?.id.startsWith("aorctodss-"))
  }

  private bounds(collection: FeatureCollection): [number, number, number, number] {
    const points: Array<[number, number]> = []
    const visit = (coordinates: unknown): void => {
      if (
        Array.isArray(coordinates) &&
        coordinates.length >= 2 &&
        typeof coordinates[0] === "number" &&
        typeof coordinates[1] === "number"
      ) {
        points.push([coordinates[0], coordinates[1]])
      } else if (Array.isArray(coordinates)) {
        coordinates.forEach(visit)
      }
    }
    collection.features.forEach(feature => visit(feature.geometry.coordinates))
    if (!points.length) throw new Error("No polygon coordinates")
    return [
      Math.min(...points.map(point => point[0])),
      Math.min(...points.map(point => point[1])),
      Math.max(...points.map(point => point[0])),
      Math.max(...points.map(point => point[1]))
    ]
  }
}
