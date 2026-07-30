import { describe, expect, it } from "vitest"
import { durationEvent } from "../src/core/time"

describe("event time helpers", () => {
  it("creates a half-open duration", () => {
    const event = durationEvent("2020-01-01T00:00:00Z", 72)
    expect(event.end).toBe("2020-01-04T00:00:00.000Z")
  })
})
