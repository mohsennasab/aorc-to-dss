import type { Feature, FeatureCollection, Geometry } from "../types"

export function geoJsonSourceCrs(value: unknown): string {
  const crs = (value as {
    crs?: {
      type?: unknown
      properties?: { name?: unknown; code?: unknown }
    }
  })?.crs
  const name = crs?.properties?.name
  const code = crs?.properties?.code
  if (typeof code === "number" || (typeof code === "string" && /^\d+$/.test(code))) {
    return `EPSG:${code}`
  }
  if (typeof name !== "string" || !name.trim()) return "EPSG:4326"
  const normalized = name.replace(/\s+/g, "").toUpperCase()
  if (normalized.includes("CRS84") || /EPSG:+4326\b/.test(normalized)) {
    return "EPSG:4326"
  }
  const epsg = normalized.match(/EPSG:+(\d+)\b/)
  return epsg ? `EPSG:${epsg[1]}` : name
}

export function asFeatureCollection(value: any): FeatureCollection {
  if (!value || typeof value !== "object") throw new Error("GeoJSON is empty")
  if (value.type === "FeatureCollection" && Array.isArray(value.features)) {
    return {
      type: "FeatureCollection",
      features: value.features.map(asFeature)
    }
  }
  if (value.type === "Feature") return { type: "FeatureCollection", features: [asFeature(value)] }
  return {
    type: "FeatureCollection",
    features: [asFeature({ type: "Feature", geometry: value, properties: {} })]
  }
}

function asFeature(value: any): Feature {
  const geometry = value?.geometry as Geometry | undefined
  if (!geometry || !["Polygon", "MultiPolygon"].includes(geometry.type)) {
    throw new Error("The area of interest must contain polygon geometry")
  }
  return {
    type: "Feature",
    geometry,
    properties: value.properties ?? {}
  }
}

export function boundsOf(collection: FeatureCollection): [number, number, number, number] {
  const coordinates: number[][] = []
  const visit = (value: unknown): void => {
    if (Array.isArray(value) && value.length >= 2 && value.every(item => typeof item === "number")) {
      coordinates.push(value as number[])
    } else if (Array.isArray(value)) {
      value.forEach(visit)
    }
  }
  collection.features.forEach(feature => visit(feature.geometry.coordinates))
  if (!coordinates.length) throw new Error("Geometry has no coordinates")
  const xs = coordinates.map(value => value[0]!)
  const ys = coordinates.map(value => value[1]!)
  return [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)]
}
