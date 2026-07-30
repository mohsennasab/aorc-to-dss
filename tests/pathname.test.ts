import { describe, expect, it } from "vitest"
import { cleanDssPart, previewGridPath, shgPart } from "../src/core/pathname"

describe("DSS pathname helpers", () => {
  it("cleans invalid characters", () => {
    expect(cleanDssPart("Upper/Tennessee!*", "BASIN")).toBe("UPPER_TENNESSEE")
  })

  it("uses the HEC default SHG label for 2 km", () => {
    expect(shgPart(2000)).toBe("SHG")
    expect(shgPart(1000)).toBe("SHG1K")
    expect(shgPart(500)).toBe("SHG500M")
  })

  it("previews all six pathname parts", () => {
    expect(previewGridPath("Basin", "PRECIP", 2000))
      .toBe("/SHG/BASIN/PRECIP/[START UTC]/[END UTC]/AORC-V1.1/")
  })
})
