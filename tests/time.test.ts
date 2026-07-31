import { describe, expect, it } from "vitest"
import { durationEvent, isWholeUtcHour } from "../src/core/time"

describe("event time helpers", () => {
  it("creates a half-open duration", () => {
    const event = durationEvent("2020-01-01T00:00:00Z", 72)
    expect(event.end).toBe("2020-01-04T00:00:00.000Z")
  })

  it("recognizes complete UTC hours", () => {
    expect(isWholeUtcHour("2020-01-01T00:00:00Z")).toBe(true)
    expect(isWholeUtcHour("2020-01-01T00:30:00Z")).toBe(false)
  })
})
