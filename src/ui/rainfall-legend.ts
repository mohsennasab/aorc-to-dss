import type { MapControl, MapLike } from "../types"

export class RainfallLegendControl implements MapControl {
  private container: HTMLElement | null = null

  constructor(
    private readonly minimum: number,
    private readonly maximum: number,
    private readonly units: string
  ) {}

  onAdd(_map: MapLike): HTMLElement {
    const container = document.createElement("div")
    container.className = "maplibregl-ctrl a2d-rainfall-legend"
    const values = Array.from(
      { length: 6 },
      (_, index) => this.minimum + (this.maximum - this.minimum) * index / 5
    )
    container.innerHTML = `
      <strong>Hourly rainfall (${this.escape(this.units)})</strong>
      <div class="a2d-rainfall-gradient" aria-hidden="true"></div>
      <div class="a2d-rainfall-values">
        ${values.map(value => `<span>${this.format(value)}</span>`).join("")}
      </div>
    `
    this.container = container
    return container
  }

  onRemove(): void {
    this.container?.remove()
    this.container = null
  }

  private format(value: number): string {
    if (this.maximum <= 5) return value.toFixed(2)
    if (this.maximum <= 50) return value.toFixed(1)
    return Math.round(value).toString()
  }

  private escape(value: string): string {
    const element = document.createElement("span")
    element.textContent = value
    return element.innerHTML
  }
}
