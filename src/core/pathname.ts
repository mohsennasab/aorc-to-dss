const INVALID = /[^A-Z0-9 _.\-:]/g

export function cleanDssPart(value: string, fallback: string): string {
  const cleaned = value.toUpperCase().trim().replaceAll("/", "_").replace(INVALID, "_")
    .replace(/\s+/g, " ").replace(/^[ ._-]+|[ ._-]+$/g, "")
  return cleaned || fallback
}

export function shgPart(cellSize: number): string {
  if (cellSize === 2000) return "SHG"
  if (cellSize % 1000 === 0) return `SHG${cellSize / 1000}K`
  return `SHG${cellSize}M`
}

export function previewGridPath(
  watershed: string,
  parameter: string,
  cellSize: number
): string {
  return `/${shgPart(cellSize)}/${cleanDssPart(watershed, "WATERSHED")}/${cleanDssPart(parameter, "MET")}/[START UTC]/[END UTC]/AORC-V1.1/`
}
