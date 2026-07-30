import { describe, expect, it } from "vitest"
import { asFeatureCollection, boundsOf, geoJsonSourceCrs } from "../src/core/geometry"

describe("GeoJSON helpers", () => {
  it("wraps a polygon geometry", () => {
    const collection = asFeatureCollection({
      type: "Polygon",
      coordinates: [[[0, 0], [2, 0], [2, 1], [0, 0]]]
    })
    expect(collection.features).toHaveLength(1)
    expect(boundsOf(collection)).toEqual([0, 0, 2, 1])
  })

  it("rejects points", () => {
    expect(() => asFeatureCollection({ type: "Point", coordinates: [0, 0] }))
      .toThrow(/polygon/)
  })

  it("reads a projected EPSG code from a legacy GeoJSON CRS", () => {
    expect(geoJsonSourceCrs({
      crs: {
        type: "name",
        properties: { name: "urn:ogc:def:crs:EPSG::5070" }
      }
    })).toBe("EPSG:5070")
    expect(geoJsonSourceCrs({ type: "FeatureCollection", features: [] })).toBe("EPSG:4326")
  })
})
