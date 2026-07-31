import { AORCServiceClient } from "../api/client"
import { asFeatureCollection, geoJsonSourceCrs } from "../core/geometry"
import { previewGridPath } from "../core/pathname"
import {
  asUtcIso,
  durationEvent,
  forDateTimeInput,
  isWholeUtcHour
} from "../core/time"
import type {
  FeatureCollection,
  GeoLibreAppAPI,
  JobStatus,
  PluginState,
  TimeSeriesPoint,
  VariableMetadata
} from "../types"
import { AoiMapController } from "./aoi-map"
import { RainfallLegendControl } from "./rainfall-legend"
import { TimeSeriesChart } from "./timeseries-chart"

const DEFAULT_STATE: PluginState = {
  serviceUrl: "http://127.0.0.1:8765",
  aoi: null,
  variable: "APCP_surface",
  start: "",
  end: "",
  unitSystem: "metric",
  watershed: "WATERSHED",
  cellSize: 2000,
  bufferM: 4000
}

export class AORCWorkbench {
  private state: PluginState
  private client: AORCServiceClient
  private mapTools: AoiMapController
  private chart: TimeSeriesChart | null = null
  private eventChart: TimeSeriesChart | null = null
  private rainfallLegend: RainfallLegendControl | null = null
  private variables: VariableMetadata[] = []
  private points: TimeSeriesPoint[] = []
  private selectedEventPoints: TimeSeriesPoint[] = []
  private event: { start: string; end: string } | null = null
  private activeJob: string | null = null
  private pollController: AbortController | null = null
  private animationRevision = 0
  private timeSliderObserver: MutationObserver | null = null
  private timeSliderSearchTimer: number | null = null
  private serviceTimer: number | null = null
  private metadataLoaded = false
  private cleanup: Array<() => void> = []

  constructor(
    private readonly container: HTMLElement,
    private readonly app: GeoLibreAppAPI,
    initial?: Partial<PluginState>
  ) {
    this.state = { ...DEFAULT_STATE, ...initial }
    this.client = new AORCServiceClient(this.state.serviceUrl)
    this.render()
    this.mapTools = new AoiMapController(app, collection => {
      this.state.aoi = collection
      void this.validateAoi()
    }, message => this.status(message))
    if (this.state.aoi) this.mapTools.set(this.state.aoi)
    this.bind()
    void this.initialize()
  }

  getState(): PluginState {
    return structuredClone(this.state)
  }

  applyState(value: Partial<PluginState>): void {
    this.state = { ...this.state, ...value }
    this.client = new AORCServiceClient(this.state.serviceUrl)
    this.metadataLoaded = false
    if (this.state.aoi) this.mapTools.set(this.state.aoi)
    this.syncInputs()
    void this.initialize()
  }

  destroy(): void {
    this.pollController?.abort()
    if (this.serviceTimer !== null) window.clearTimeout(this.serviceTimer)
    this.chart?.destroy()
    this.eventChart?.destroy()
    this.detachTimeSliderCursor()
    this.removeRainfallLegend()
    this.mapTools.destroy()
    this.cleanup.forEach(callback => callback())
    this.container.replaceChildren()
  }

  private render(): void {
    this.container.className = "a2d-workbench"
    this.container.innerHTML = `
      <div class="a2d-service">
        <span class="a2d-service-dot" data-service-dot></span>
        <span data-service-label>Checking local processing service</span>
        <button type="button" class="a2d-link-button" data-action="service-retry">Retry</button>
        <button type="button" class="a2d-link-button" data-action="service-settings">Settings</button>
      </div>
      <div class="a2d-progress" hidden data-progress-wrap>
        <div class="a2d-progress-track"><span data-progress-bar></span></div>
        <div class="a2d-progress-row"><span data-progress-text></span><button type="button" data-action="cancel-job">Cancel</button></div>
      </div>
      <nav class="a2d-tabs" aria-label="AORCtoDSS workflow">
        ${this.tabButton("study", "1", "AOI Selection", true)}
        ${this.tabButton("data", "2", "AORC Data")}
        ${this.tabButton("series", "3", "AOI Time Series")}
        ${this.tabButton("event", "4", "Event Selection")}
        ${this.tabButton("export", "5", "DSS Export")}
        ${this.tabButton("results", "6", "Results")}
      </nav>
      <main class="a2d-pages">
        ${this.studyPage()}
        ${this.dataPage()}
        ${this.seriesPage()}
        ${this.eventPage()}
        ${this.exportPage()}
        ${this.resultsPage()}
      </main>
      <div class="a2d-toast" hidden data-status role="status"></div>
    `
  }

  private tabButton(id: string, number: string, label: string, active = false): string {
    return `<button type="button" class="${active ? "active" : ""}" data-tab="${id}" aria-label="${label}" title="${label}"><span>${number}</span></button>`
  }

  private studyPage(): string {
    return `
      <section class="a2d-page active" data-page="study">
        <h2>AOI Selection</h2>
        <p class="a2d-help">Choose a polygon. A declared GeoJSON CRS is detected and the analysis copy is transformed to WGS84.</p>
        <div class="a2d-button-grid">
          <button type="button" data-action="draw-aoi">Draw polygon</button>
          <button type="button" data-action="undo-aoi-vertex">Undo last vertex</button>
          <button type="button" data-action="finish-aoi">Finish polygon</button>
          <button type="button" data-action="capture-aoi">Pick loaded polygon</button>
          <button type="button" data-action="import-vector">Import vector file</button>
          <button type="button" data-action="clear-aoi">Clear selection</button>
          <button type="button" data-action="save-aoi">Save GeoJSON</button>
        </div>
        <label class="a2d-check"><input type="checkbox" checked data-field="dissolve"> Dissolve multiple polygon features</label>
        <div class="a2d-summary" data-aoi-summary>
          <span>No area selected</span>
        </div>
        <button type="button" class="a2d-primary" data-next="data" disabled>Continue to AORC Data</button>
      </section>
    `
  }

  private dataPage(): string {
    return `
      <section class="a2d-page" data-page="data">
        <h2>AORC Data</h2>
        <label>Variable<select data-field="variable"><option>Loading AORC variables automatically</option></select></label>
        <label>Time-series and DSS unit system
          <select data-field="unit-system">
            <option value="metric">Metric, precipitation in mm and temperature in °C</option>
            <option value="us-customary">US customary, precipitation in inches and temperature in °F</option>
          </select>
        </label>
        <p class="a2d-help">The source cache keeps NOAA units. Time series, event statistics, COG, and DSS outputs use the selected unit system.</p>
        <dl class="a2d-metadata" data-variable-metadata></dl>
        <div class="a2d-two-column">
          <label>Start date and time, UTC<input type="datetime-local" data-field="start"></label>
          <label>End date and time, UTC<input type="datetime-local" data-field="end"></label>
        </div>
        <p class="a2d-help">All source and output times use UTC. The end value is exclusive.</p>
        <button type="button" class="a2d-primary" data-next="series" disabled>Continue to Time Series</button>
      </section>
    `
  }

  private seriesPage(): string {
    return `
      <section class="a2d-page" data-page="series">
        <h2>AOI Time Series</h2>
        <p class="a2d-help">The AOI mean is area weighted, including partial AORC cells along the boundary.</p>
        <button type="button" class="a2d-primary" data-action="run-timeseries">Run analysis</button>
        <div class="a2d-chart-toolbar">
          <button type="button" data-action="chart-reset">Reset view</button>
          <button type="button" data-action="chart-image">Save image...</button>
          <button type="button" data-action="series-csv">Export CSV</button>
        </div>
        <p class="a2d-help">Wheel to zoom. Shift and drag to pan.</p>
        <div class="a2d-chart-host" data-chart></div>
        <button type="button" class="a2d-primary" data-next="event" disabled>Continue to Event Selection</button>
      </section>
    `
  }

  private eventPage(): string {
    return `
      <section class="a2d-page" data-page="event">
        <h2>Event Selection</h2>
        <p class="a2d-help">Enter a start and end time, or enter the start and use a duration button to update the end automatically.</p>
        <div class="a2d-two-column">
          <label>Event start, UTC<input type="datetime-local" step="3600" data-field="event-start"></label>
          <label>Event end, UTC<input type="datetime-local" step="3600" data-field="event-end"></label>
        </div>
        <div class="a2d-button-row">
          <button type="button" data-duration="24">24 hours</button>
          <button type="button" data-duration="48">48 hours</button>
          <button type="button" data-duration="72">72 hours</button>
          <button type="button" data-duration="96">96 hours</button>
        </div>
        <div class="a2d-summary" data-event-summary>No event selected</div>
        <button type="button" class="a2d-primary" data-action="create-animation" disabled>
          Download frames and create Time Slider
        </button>
        <div class="a2d-animation-progress" hidden data-animation-progress>
          <div class="a2d-progress-track"><span data-animation-progress-bar></span></div>
          <div class="a2d-progress-row"><span data-animation-progress-text></span></div>
        </div>
        <div class="a2d-summary" data-animation-status>
          Select an event, then use the button above to preload its animation.
        </div>
        <div class="a2d-animation-legend" hidden data-animation-legend></div>
        <h3>Selected event time series</h3>
        <div class="a2d-chart-host a2d-event-chart-host" data-event-chart></div>
        <button type="button" class="a2d-primary" data-next="export" disabled>Continue to DSS Export</button>
      </section>
    `
  }

  private exportPage(): string {
    return `
      <section class="a2d-page" data-page="export">
        <h2>DSS Export</h2>
        <label>Output folder
          <span class="a2d-input-action"><input type="text" data-field="output-dir" placeholder="C:\\AORCtoDSS\\Project"><button type="button" data-action="choose-output">Browse</button></span>
        </label>
        <label>DSS filename<input type="text" value="aorc_event.dss" data-field="dss-filename"></label>
        <label>Watershed or project name<input type="text" value="${this.state.watershed}" data-field="watershed"></label>
        <div class="a2d-two-column">
          <label>SHG cell size
            <select data-field="cell-size">
              ${[10, 20, 50, 100, 200, 500, 1000, 2000, 4000, 5000, 10000]
                .map(value => `<option value="${value}" ${value === this.state.cellSize ? "selected" : ""}>${value} m</option>`)
                .join("")}
            </select>
          </label>
          <label>AOI buffer, m<input type="number" min="0" step="100" value="${this.state.bufferM}" data-field="buffer-m"></label>
        </div>
        <label>Raster processing<input type="text" value="Nearest neighbor; source clip all_touched=True" disabled></label>
        <label class="a2d-check"><input type="checkbox" data-field="overwrite"> Replace an existing output file</label>
        <h3>DSS pathname preview</h3>
        <code data-path-preview></code>
        <details>
          <summary>Pathname parts</summary>
          <dl class="a2d-metadata">
            <dt>A</dt><dd>SHG grid system and resolution</dd>
            <dt>B</dt><dd>Watershed or project</dd>
            <dt>C</dt><dd>Meteorologic parameter</dd>
            <dt>D</dt><dd>Interval start or instantaneous time</dd>
            <dt>E</dt><dd>Interval end for accumulated or average data</dd>
            <dt>F</dt><dd>AORC dataset version</dd>
          </dl>
        </details>
        <button type="button" data-action="estimate-export">Estimate size</button>
        <div class="a2d-summary" data-export-estimate>No estimate calculated</div>
        <button type="button" class="a2d-primary" data-action="run-export">Create DSS and validate</button>
      </section>
    `
  }

  private resultsPage(): string {
    return `
      <section class="a2d-page" data-page="results">
        <h2>Results</h2>
        <div data-results><p>No export has been run.</p></div>
      </section>
    `
  }

  private bind(): void {
    this.container.querySelectorAll<HTMLButtonElement>("[data-tab]").forEach(button => {
      button.addEventListener("click", () => this.openPage(button.dataset.tab!))
    })
    this.container.querySelectorAll<HTMLButtonElement>("[data-next]").forEach(button => {
      button.addEventListener("click", () => this.openPage(button.dataset.next!))
    })
    this.onAction("draw-aoi", () => this.mapTools.startDrawing())
    this.onAction("undo-aoi-vertex", () => this.mapTools.undoDrawingVertex())
    this.onAction("finish-aoi", () => this.mapTools.finishDrawing())
    this.onAction("capture-aoi", () => this.mapTools.captureLoadedPolygon())
    this.onAction("import-vector", () => void this.importVector())
    this.onAction("clear-aoi", () => this.clearAoi())
    this.onAction("save-aoi", () => this.saveAoi())
    this.onAction("service-retry", () => void this.initialize())
    this.onAction("service-settings", () => this.editServiceUrl())
    this.onAction("run-timeseries", () => void this.runTimeseries())
    this.onAction("cancel-job", () => void this.cancelJob())
    this.onAction("chart-reset", () => this.chart?.reset())
    this.onAction("chart-image", () => void this.exportChartImage())
    this.onAction("series-csv", () => this.exportSeriesCsv())
    this.onAction("estimate-export", () => void this.estimateExport())
    this.onAction("run-export", () => void this.runExport())
    this.onAction("choose-output", () => void this.chooseOutput())
    this.onAction("create-animation", () => void this.createEventAnimation())
    this.container.querySelectorAll<HTMLButtonElement>("[data-duration]").forEach(button => {
      button.addEventListener("click", () => this.selectDuration(Number(button.dataset.duration)))
    })
    this.field<HTMLSelectElement>("variable").addEventListener("change", event => {
      this.state.variable = (event.target as HTMLSelectElement).value
      this.animationRevision += 1
      this.clearAnimationPresentation()
      this.points = []
      this.selectedEventPoints = []
      this.event = null
      this.chart?.destroy()
      this.chart = null
      this.eventChart?.destroy()
      this.eventChart = null
      this.q("[data-chart]").replaceChildren()
      this.q("[data-event-chart]").replaceChildren()
      this.q("[data-event-summary]").textContent = "No event selected"
      this.q("[data-animation-status]").textContent =
        "Variable changed. Run the time-series analysis again."
      this.q<HTMLElement>("[data-animation-progress]").hidden = true
      this.q<HTMLButtonElement>('[data-action="create-animation"]').disabled = true
      this.q<HTMLButtonElement>('[data-next="event"]').disabled = true
      this.q<HTMLButtonElement>('[data-next="export"]').disabled = true
      this.showVariable()
      this.updatePathPreview()
    })
    this.field<HTMLSelectElement>("unit-system").addEventListener("change", event => {
      this.state.unitSystem = (event.target as HTMLSelectElement).value as PluginState["unitSystem"]
      this.animationRevision += 1
      this.clearAnimationPresentation()
      this.refreshVariableLabels()
      this.showVariable()
      this.points = []
      this.selectedEventPoints = []
      this.event = null
      this.chart?.destroy()
      this.chart = null
      this.eventChart?.destroy()
      this.eventChart = null
      this.q("[data-chart]").replaceChildren()
      this.q("[data-event-chart]").replaceChildren()
      this.q("[data-event-summary]").textContent = "No event selected"
      this.q("[data-animation-status]").textContent =
        "Run the time-series analysis again, then select an event."
      this.q<HTMLElement>("[data-animation-progress]").hidden = true
      this.q<HTMLButtonElement>('[data-action="create-animation"]').disabled = true
      this.q<HTMLButtonElement>('[data-next="event"]').disabled = true
      this.q<HTMLButtonElement>('[data-next="export"]').disabled = true
      this.status("Unit system changed. Run the time-series analysis again.")
    })
    this.field<HTMLInputElement>("start").addEventListener("change", event => {
      this.state.start = asUtcIso((event.target as HTMLInputElement).value)
    })
    this.field<HTMLInputElement>("end").addEventListener("change", event => {
      this.state.end = asUtcIso((event.target as HTMLInputElement).value)
    })
    this.field<HTMLInputElement>("event-start").addEventListener("change", () => this.readEventInputs())
    this.field<HTMLInputElement>("event-end").addEventListener("change", () => this.readEventInputs())
    this.field<HTMLInputElement>("watershed").addEventListener("input", event => {
      this.state.watershed = (event.target as HTMLInputElement).value
      this.updatePathPreview()
    })
    this.field<HTMLSelectElement>("cell-size").addEventListener("change", event => {
      this.state.cellSize = Number((event.target as HTMLSelectElement).value)
      this.updatePathPreview()
    })
    this.field<HTMLInputElement>("buffer-m").addEventListener("change", event => {
      this.state.bufferM = Number((event.target as HTMLInputElement).value)
    })
    this.syncInputs()
  }

  private async initialize(): Promise<void> {
    if (this.serviceTimer !== null) {
      window.clearTimeout(this.serviceTimer)
      this.serviceTimer = null
    }
    const ready = await this.checkHealth()
    if (ready && !this.metadataLoaded) await this.loadMetadata()
    this.updatePathPreview()
    this.serviceTimer = window.setTimeout(
      () => void this.initialize(),
      ready && this.metadataLoaded ? 30_000 : 3_000
    )
  }

  private async checkHealth(): Promise<boolean> {
    const dot = this.q<HTMLElement>("[data-service-dot]")
    const label = this.q<HTMLElement>("[data-service-label]")
    try {
      const health = await this.client.health()
      dot.className = `a2d-service-dot ${health.dss.available ? "ready" : "warning"}`
      label.textContent = health.dss.available
        ? `Processing service ${health.version} ready`
        : `Service ready. DSS component unavailable: ${health.dss.message}`
      return true
    } catch {
      dot.className = "a2d-service-dot warning"
      label.textContent = "Local service is starting or reconnecting. Retrying automatically."
      return false
    }
  }

  private async waitForService(): Promise<void> {
    this.client = new AORCServiceClient(this.state.serviceUrl)
    for (let attempt = 1; attempt <= 30; attempt += 1) {
      if (await this.checkHealth()) return
      if (attempt < 10) {
        await new Promise(resolve => window.setTimeout(resolve, 1_000))
      }
    }
    throw new Error(
      "The local processing service did not respond. Run the AORCtoDSS installer or service and retry."
    )
  }

  private async loadMetadata(): Promise<void> {
    const select = this.field<HTMLSelectElement>("variable")
    const loading = document.createElement("option")
    loading.textContent = "Loading AORC variables automatically"
    select.replaceChildren(loading)
    select.disabled = true
    try {
      const result = await this.client.metadata()
      this.variables = result.variables
      select.replaceChildren(...this.variables.map(variable => {
        const option = document.createElement("option")
        option.value = variable.source_name
        option.textContent = `${variable.display_name} (${this.outputUnit(variable)})`
        return option
      }))
      if (!this.variables.some(variable => variable.source_name === this.state.variable)) {
        this.state.variable = this.variables[0]?.source_name ?? ""
      }
      select.value = this.state.variable
      const selected = this.selectedVariable()
      if (!this.state.start && selected) {
        const end = new Date(selected.end)
        const start = new Date(Math.max(new Date(selected.start).getTime(), end.getTime() - 30 * 86_400_000))
        this.state.start = start.toISOString()
        this.state.end = new Date(end.getTime() + 3_600_000).toISOString()
      }
      this.syncInputs()
      this.showVariable()
      this.metadataLoaded = true
      this.q<HTMLButtonElement>('[data-next="series"]').disabled = false
    } catch (error) {
      this.metadataLoaded = false
      this.q<HTMLButtonElement>('[data-next="series"]').disabled = true
      const unavailable = document.createElement("option")
      unavailable.textContent = "Variables unavailable. Retrying automatically."
      select.replaceChildren(unavailable)
      this.status(`AORC metadata could not be loaded: ${this.message(error)}`)
    } finally {
      select.disabled = !this.metadataLoaded
    }
  }

  private showVariable(): void {
    const variable = this.selectedVariable()
    if (!variable) return
    this.q("[data-variable-metadata]").innerHTML = `
      <dt>Source name</dt><dd>${this.escape(variable.source_name)}</dd>
      <dt>AORC source units</dt><dd>${this.escape(variable.units)}</dd>
      <dt>Time-series units</dt><dd>${this.escape(this.outputUnit(variable))}</dd>
      <dt>DSS units</dt><dd>${this.escape(this.outputDssUnit(variable))}</dd>
      <dt>Resolution</dt><dd>${this.escape(variable.temporal_resolution)}</dd>
      <dt>Available</dt><dd>${this.escape(variable.start)} through ${this.escape(variable.end)}</dd>
      <dt>Missing value</dt><dd>${variable.missing_value}</dd>
      <dt>Description</dt><dd>${this.escape(variable.description)}</dd>
    `
  }

  private async importVector(): Promise<void> {
    try {
      if (this.app.pickVectorFilesWithSidecars) {
        const picked = await this.app.pickVectorFilesWithSidecars()
        const selected = picked[0]
        if (!selected) return
        if (selected.nativeData) {
          this.setAoi(selected.nativeData)
          return
        }
        if (/\.(geojson|json)$/i.test(selected.file.name)) {
          const value = JSON.parse(await selected.file.text())
          this.setAoi(asFeatureCollection(value), geoJsonSourceCrs(value))
          return
        }
        this.status("GeoLibre could not decode this vector file. Load it as a map layer, then use Pick loaded polygon.")
        return
      }
      const text = await this.app.importTextFile?.({
        description: "GeoJSON",
        extensions: ["geojson", "json"]
      })
      if (text) {
        const value = JSON.parse(text)
        this.setAoi(asFeatureCollection(value), geoJsonSourceCrs(value))
      }
    } catch (error) {
      this.status(`Vector import failed: ${this.message(error)}`)
    }
  }

  private setAoi(collection: FeatureCollection, sourceCrs = "EPSG:4326"): void {
    this.state.aoi = null
    this.mapTools.clear()
    this.q("[data-aoi-summary]").textContent = `Validating and transforming ${sourceCrs}`
    this.q<HTMLButtonElement>('[data-next="data"]').disabled = true
    void this.validateAoi(collection, sourceCrs)
  }

  private async validateAoi(
    collection: FeatureCollection | null = this.state.aoi,
    sourceCrs = "EPSG:4326"
  ): Promise<void> {
    if (!collection) return
    try {
      const summary = await this.client.validateGeometry({
        geometry: collection,
        source_crs: sourceCrs,
        dissolve: this.field<HTMLInputElement>("dissolve").checked
      })
      const normalized = asFeatureCollection({
        type: "Feature",
        properties: { source_crs: summary.source_crs },
        geometry: summary.geometry
      })
      this.state.aoi = normalized
      this.mapTools.set(normalized)
      const largeArea = summary.area_sq_km > 100_000
      this.q("[data-aoi-summary]").innerHTML = `
        <strong>${summary.area_sq_km.toLocaleString(undefined, { maximumFractionDigits: 2 })} km²</strong>
        <span>${summary.feature_count} source feature${summary.feature_count === 1 ? "" : "s"}</span>
        <span>Source CRS: ${this.escape(summary.source_crs)} → analysis CRS: WGS84</span>
        <span>${summary.repaired ? "Simple geometry repairs applied" : "Geometry is valid"}</span>
        <span>${summary.dissolved ? "Features dissolved for analysis" : "No dissolve required"}</span>
        ${largeArea ? "<span class=\"a2d-warning\">Large study area. Long periods can require substantial download time and memory.</span>" : ""}
      `
      this.q<HTMLButtonElement>('[data-next="data"]').disabled = false
      this.status(largeArea
        ? "Study area is ready. This is a large domain, so start with a short test period."
        : "Study area is ready.")
    } catch (error) {
      this.state.aoi = null
      this.mapTools.clear()
      this.q("[data-aoi-summary]").textContent = this.message(error)
      this.q<HTMLButtonElement>('[data-next="data"]').disabled = true
    }
  }

  private clearAoi(): void {
    this.animationRevision += 1
    this.clearAnimationPresentation()
    this.state.aoi = null
    this.event = null
    this.selectedEventPoints = []
    this.mapTools.clear()
    this.q("[data-aoi-summary]").textContent = "No area selected"
    this.q("[data-animation-status]").textContent =
      "Select a study area and event to prepare the Time Slider."
    this.q<HTMLElement>("[data-animation-progress]").hidden = true
    this.q<HTMLButtonElement>('[data-action="create-animation"]').disabled = true
    this.q<HTMLButtonElement>('[data-next="data"]').disabled = true
    this.q<HTMLButtonElement>('[data-next="export"]').disabled = true
  }

  private saveAoi(): void {
    if (!this.state.aoi) {
      this.status("Select an area first.")
      return
    }
    this.app.exportTextFile?.(
      "aorctodss_aoi.geojson",
      JSON.stringify(this.state.aoi, null, 2),
      { description: "GeoJSON", extensions: ["geojson"], suggestedName: "aorctodss_aoi.geojson" }
    )
  }

  private async runTimeseries(): Promise<void> {
    if (!this.state.aoi) {
      this.status("Select a study area first.")
      return
    }
    const button = this.q<HTMLButtonElement>('[data-action="run-timeseries"]')
    const buttonLabel = button.textContent
    button.disabled = true
    try {
      button.textContent = "Connecting to service..."
      this.status("Connecting to the local processing service.")
      await this.waitForService()
      button.textContent = "Starting analysis..."
      this.readPeriodInputs()
      const job = await this.client.startTimeseries({
        geometry: this.state.aoi,
        source_crs: "EPSG:4326",
        dissolve: this.field<HTMLInputElement>("dissolve").checked,
        variable: this.state.variable,
        start: this.state.start,
        end: this.state.end,
        unit_system: this.state.unitSystem
      })
      const result = await this.monitor(job)
      if (result.state !== "complete") {
        const guidance = result.error?.guidance ? ` ${result.error.guidance}` : ""
        throw new Error(`${result.error?.message ?? result.message}${guidance}`)
      }
      this.points = result.result.points
      this.renderSeries()
      this.q<HTMLButtonElement>('[data-next="event"]').disabled = false
      if (this.points.length) {
        this.animationRevision += 1
        this.clearAnimationPresentation()
        this.event = null
        this.selectedEventPoints = []
        this.eventChart?.destroy()
        this.eventChart = null
        this.q("[data-event-chart]").replaceChildren()
        this.field<HTMLInputElement>("event-start").value = forDateTimeInput(this.state.start)
        this.field<HTMLInputElement>("event-end").value = ""
        this.q("[data-event-summary]").textContent =
          "Choose an end time or click 24, 48, 72, or 96 hours."
        this.q("[data-animation-status]").textContent =
          "Select an event, then download its frames to create the Time Slider."
        this.q<HTMLButtonElement>('[data-action="create-animation"]').disabled = true
        this.q<HTMLButtonElement>('[data-next="export"]').disabled = true
      }
      this.status(`Calculated ${this.points.length.toLocaleString()} hourly values.`)
    } catch (error) {
      if ((error as Error).name !== "AbortError") this.status(`Time-series analysis failed: ${this.message(error)}`)
    } finally {
      button.disabled = false
      button.textContent = buttonLabel
    }
  }

  private renderSeries(): void {
    const variable = this.selectedVariable()
    const host = this.q<HTMLElement>("[data-chart]")
    this.chart?.destroy()
    this.chart = new TimeSeriesChart(host, {
      units: this.points[0]?.units ?? (variable ? this.outputUnit(variable) : ""),
      onRange: (start, end) => this.setEvent(start, end)
    })
    this.chart.setData(this.points)
  }

  private exportSeriesCsv(): void {
    if (!this.points.length) return
    const quote = (value: unknown) => `"${String(value ?? "").replaceAll('"', '""')}"`
    const rows = ["time,value,units,quality", ...this.points.map(point =>
      [point.time, point.value, point.units, point.quality].map(quote).join(",")
    )]
    this.app.exportTextFile?.(
      "aorc_watershed_timeseries.csv",
      rows.join("\n"),
      { description: "CSV", extensions: ["csv"], suggestedName: "aorc_watershed_timeseries.csv" }
    )
  }

  private async exportChartImage(): Promise<void> {
    if (!this.chart) {
      this.status("Run the time-series analysis before saving an image.")
      return
    }
    try {
      const result = await this.client.savePng(
        this.chart.pngDataUrl(),
        "aorc_watershed_timeseries.png"
      )
      if (result.path) this.status(`Saved chart image to ${result.path}`)
    } catch (error) {
      this.status(`Chart image could not be saved: ${this.message(error)}`)
    }
  }

  private selectDuration(hours: number): void {
    try {
      const startValue = this.field<HTMLInputElement>("event-start").value
      if (!startValue) throw new Error("Choose the event start date and time first")
      const event = durationEvent(asUtcIso(startValue), hours)
      this.setEvent(event.start, event.end)
    } catch (error) {
      this.status(this.message(error))
    }
  }

  private setEvent(start: string, end: string): void {
    const startTime = new Date(start)
    const endTime = new Date(end)
    if (!isWholeUtcHour(startTime) || !isWholeUtcHour(endTime)) {
      throw new Error("Event start and end must use :00 minutes in UTC")
    }
    const hours = (endTime.getTime() - startTime.getTime()) / 3_600_000
    if (hours <= 0) throw new Error("Event end must be after event start")
    if (!Number.isInteger(hours)) throw new Error("Event times must define a whole number of hours")
    if (this.state.start && startTime < new Date(this.state.start)) {
      throw new Error("Event start is before the analyzed time series")
    }
    if (this.state.end && endTime > new Date(this.state.end)) {
      throw new Error("Event end is after the analyzed time series")
    }
    this.animationRevision += 1
    this.clearAnimationPresentation()
    this.event = { start: startTime.toISOString(), end: endTime.toISOString() }
    this.field<HTMLInputElement>("event-start").value = forDateTimeInput(this.event.start)
    this.field<HTMLInputElement>("event-end").value = forDateTimeInput(this.event.end)
    const accumulated = this.selectedVariable()?.aggregation === "sum"
    const selectedPoints = this.points.filter(point => {
      const time = new Date(point.time).getTime()
      return accumulated
        ? time > startTime.getTime() && time <= endTime.getTime()
        : time >= startTime.getTime() && time < endTime.getTime()
    })
    this.selectedEventPoints = selectedPoints
    const values = selectedPoints.flatMap(point => point.value === null ? [] : [point.value])
    const statistic = accumulated
      ? values.reduce((sum, value) => sum + value, 0)
      : values.length
        ? values.reduce((sum, value) => sum + value, 0) / values.length
        : Number.NaN
    const statisticLabel = accumulated ? "Selected-series sum" : "Selected-series mean"
    this.q("[data-event-summary]").innerHTML = `
      <strong>${hours.toLocaleString()} hourly grids</strong>
      <span>${this.escape(this.event.start)} through ${this.escape(this.event.end)}</span>
      <span>${statisticLabel}: ${Number.isFinite(statistic) ? statistic.toFixed(3) : "not available"} ${this.escape(this.points[0]?.units ?? "")}</span>
      <span>Source time zone: UTC. DSS time zone: UTC.</span>
    `
    const host = this.q<HTMLElement>("[data-event-chart]")
    this.eventChart?.destroy()
    this.eventChart = new TimeSeriesChart(host, {
      units: this.points[0]?.units ?? ""
    })
    this.eventChart.setData(selectedPoints)
    const animationButton = this.q<HTMLButtonElement>('[data-action="create-animation"]')
    animationButton.disabled = false
    animationButton.textContent = "Download frames and create Time Slider"
    this.q<HTMLElement>("[data-animation-progress]").hidden = true
    this.q<HTMLElement>("[data-animation-progress-bar]").style.width = "0%"
    this.q("[data-animation-status]").textContent =
      `${selectedPoints.length.toLocaleString()} frames are ready to download. ` +
      "The Time Slider will be created only after the download finishes."
    this.q<HTMLButtonElement>('[data-next="export"]').disabled = false
  }

  private async createEventAnimation(): Promise<void> {
    if (!this.state.aoi || !this.event) return
    const revision = ++this.animationRevision
    const status = this.q("[data-animation-status]")
    const button = this.q<HTMLButtonElement>('[data-action="create-animation"]')
    const progressWrap = this.q<HTMLElement>("[data-animation-progress]")
    const progressBar = this.q<HTMLElement>("[data-animation-progress-bar]")
    const progressText = this.q("[data-animation-progress-text]")
    button.disabled = true
    button.textContent = "Preparing animation..."
    progressWrap.hidden = false
    progressBar.style.width = "0%"
    progressText.textContent = "Connecting to the local processing service"
    status.textContent = "The Time Slider will open when every frame is ready."
    try {
      await this.waitForService()
      const registration = await this.client.createAnimation({
        geometry: this.state.aoi,
        source_crs: "EPSG:4326",
        dissolve: this.field<HTMLInputElement>("dissolve").checked,
        variable: this.state.variable,
        unit_system: this.state.unitSystem,
        event_start: this.event.start,
        event_end: this.event.end,
        selected_values: this.selectedEventPoints.map(point => point.value)
      })
      if (revision !== this.animationRevision) return
      if (!registration.times.length) throw new Error("No animation frames were registered")
      await this.client.startAnimationPreload(registration.id)
      await this.client.waitForAnimation(registration.id, preload => {
        if (revision !== this.animationRevision) return
        const percent = Math.round(preload.progress * 90)
        progressBar.style.width = `${percent}%`
        progressText.textContent =
          `${percent}% — ${preload.message} (${preload.completed} of ${preload.total} frames)`
      })
      if (revision !== this.animationRevision) return
      const sourceUrl = `${this.state.serviceUrl}${registration.url_template}`
      await this.warmAnimationCache(sourceUrl, registration.times, revision, completed => {
        const percent = 90 + Math.round(completed / registration.times.length * 10)
        progressBar.style.width = `${percent}%`
        progressText.textContent =
          `${percent}% — loaded ${completed} of ${registration.times.length} frames into GeoLibre's cache`
      })
      if (revision !== this.animationRevision) return
      const animationLegend = this.q<HTMLElement>("[data-animation-legend]")
      animationLegend.hidden = false
      animationLegend.innerHTML = `
        <strong>Hourly rainfall (${this.escape(registration.units)})</strong>
        <div class="a2d-rainfall-gradient" aria-hidden="true"></div>
        <div class="a2d-animation-legend-values">
          <span>${this.formatLegendValue(registration.rescale[0], registration.rescale[1])}</span>
          <span>${this.formatLegendValue((registration.rescale[0] + registration.rescale[1]) / 2, registration.rescale[1])}</span>
          <span>${this.formatLegendValue(registration.rescale[1], registration.rescale[1])}</span>
        </div>
      `
      this.removeRainfallLegend()
      if (this.state.variable === "APCP_surface") {
        const legend = new RainfallLegendControl(
          registration.rescale[0],
          registration.rescale[1],
          registration.units
        )
        if (this.app.addMapControl(legend, "bottom-right")) {
          this.rainfallLegend = legend
        }
      }
      this.eventChart?.setCursorTime(registration.times[0]!)
      const activated = await this.app.activatePlugin?.("maplibre-gl-time-slider", {
        startDate: registration.times[0],
        endDate: registration.times.at(-1),
        dates: registration.times,
        interval: 1,
        granularity: "hour",
        granularities: ["hour"],
        currentDate: registration.times[0],
        initialDate: registration.times[0],
        speed: 800,
        loop: true,
        autoPlay: false,
        collapsed: false,
        dateFormat: "YYYY MMM DD HH:00",
        sources: [{
          type: "cog",
          id: `aorctodss-event-${registration.id}`,
          name: `${this.selectedVariable()?.display_name ?? "AORC"} event`,
          url: sourceUrl,
          engine: "gpu",
          colormap: registration.colormap,
          rescale: registration.rescale,
          nodata: registration.nodata,
          bidx: [1],
          opacity: 0.85,
          bounds: registration.bounds
        }]
      })
      if (!activated) {
        throw new Error("This GeoLibre build could not open its native Time Slider")
      }
      if (revision !== this.animationRevision) return
      this.attachTimeSliderCursor(registration.times, revision)
      this.app.fitBounds?.(registration.bounds)
      status.innerHTML = `
        <strong>Time Slider animation is ready to play</strong>
        <span>All ${registration.times.length.toLocaleString()} hourly frames are downloaded and cached locally.</span>
        <span>Use Play in the Time Slider below the map. Rainfall uses a radar-style scale with the highest intensities in pink.</span>
        <span>The red marker on the selected-event plot follows the active animation hour.</span>
      `
      progressBar.style.width = "100%"
      progressText.textContent =
        `100% — all ${registration.times.length.toLocaleString()} frames are ready`
      button.textContent = "Rebuild Time Slider animation"
    } catch (error) {
      if (revision !== this.animationRevision) return
      this.clearAnimationPresentation()
      status.textContent = `Animation could not be prepared: ${this.message(error)}`
      progressWrap.hidden = true
      button.textContent = "Retry Time Slider download"
    } finally {
      if (revision === this.animationRevision) button.disabled = false
    }
  }

  private async warmAnimationCache(
    template: string,
    times: string[],
    revision: number,
    onProgress: (completed: number) => void
  ): Promise<void> {
    let next = 0
    let completed = 0
    const worker = async (): Promise<void> => {
      while (revision === this.animationRevision) {
        const index = next
        next += 1
        if (index >= times.length) return
        const key = new Date(times[index]!).toISOString().slice(0, 13).replace("T", "-")
        const response = await fetch(
          template.replace("{date:YYYY-MM-DD-HH}", key)
        )
        if (!response.ok) {
          throw new Error(`Frame ${index + 1} could not be loaded into GeoLibre's cache`)
        }
        await response.arrayBuffer()
        completed += 1
        onProgress(completed)
      }
    }
    await Promise.all(
      Array.from(
        { length: Math.min(4, Math.max(times.length, 1)) },
        () => worker()
      )
    )
  }

  private readEventInputs(): void {
    try {
      const start = this.field<HTMLInputElement>("event-start").value
      const end = this.field<HTMLInputElement>("event-end").value
      if (!start || !end) {
        this.animationRevision += 1
        this.clearAnimationPresentation()
        this.event = null
        this.selectedEventPoints = []
        this.q("[data-animation-status]").textContent =
          "Choose an event end time to prepare the Time Slider."
        this.q<HTMLButtonElement>('[data-action="create-animation"]').disabled = true
        this.q<HTMLButtonElement>('[data-next="export"]').disabled = true
        return
      }
      this.setEvent(
        asUtcIso(start),
        asUtcIso(end)
      )
    } catch (error) {
      this.status(this.message(error))
    }
  }

  private exportPayload(): Record<string, unknown> {
    if (!this.state.aoi || !this.event) throw new Error("Select an area and event first")
    this.state.watershed = this.field<HTMLInputElement>("watershed").value
    this.state.cellSize = Number(this.field<HTMLSelectElement>("cell-size").value)
    this.state.bufferM = Number(this.field<HTMLInputElement>("buffer-m").value)
    return {
      geometry: this.state.aoi,
      source_crs: "EPSG:4326",
      dissolve: this.field<HTMLInputElement>("dissolve").checked,
      variable: this.state.variable,
      unit_system: this.state.unitSystem,
      event_start: this.event.start,
      event_end: this.event.end,
      output_dir: this.field<HTMLInputElement>("output-dir").value,
      dss_filename: this.field<HTMLInputElement>("dss-filename").value,
      watershed: this.state.watershed,
      parameter: this.selectedVariable()?.dss_parameter,
      cell_size: this.state.cellSize,
      buffer_m: this.state.bufferM,
      dataset_version: "AORC-V1.1",
      overwrite: this.field<HTMLInputElement>("overwrite").checked
    }
  }

  private async estimateExport(): Promise<void> {
    try {
      const payload = this.exportPayload()
      const result = await this.client.estimate(payload)
      this.q("[data-export-estimate]").innerHTML = `
        <strong>${result.grid.width.toLocaleString()} by ${result.grid.height.toLocaleString()} cells</strong>
        <span>${result.grid.cells.toLocaleString()} cells per hour</span>
        <span>${result.grid.hours.toLocaleString()} hourly grids</span>
        <span>Estimated DSS size: ${result.grid.estimated_dss_megabytes.toLocaleString()} MB</span>
        <span>Uncompressed working data: ${result.grid.raw_megabytes.toLocaleString()} MB</span>
      `
    } catch (error) {
      this.status(`Estimate failed: ${this.message(error)}`)
    }
  }

  private async runExport(): Promise<void> {
    try {
      const payload = this.exportPayload()
      if (!payload.output_dir) throw new Error("Choose an output folder")
      const job = await this.client.startExport(payload)
      const result = await this.monitor(job)
      if (result.state !== "complete") {
        const guidance = result.error?.guidance ? ` ${result.error.guidance}` : ""
        throw new Error(`${result.error?.message ?? result.message}${guidance}`)
      }
      await this.renderResults(result)
      this.openPage("results")
    } catch (error) {
      if ((error as Error).name !== "AbortError") this.status(`DSS export failed: ${this.message(error)}`)
    }
  }

  private async chooseOutput(): Promise<void> {
    try {
      const result = await this.client.chooseFolder()
      if (result.path) this.field<HTMLInputElement>("output-dir").value = result.path
    } catch (error) {
      this.status(`Folder picker failed: ${this.message(error)}`)
    }
  }

  private async renderResults(job: JobStatus): Promise<void> {
    const result = job.result
    const checks = result.validation as Array<{ name: string; status: string; message: string }>
    const failures = checks.filter(check => check.status === "failure").length
    const warnings = checks.filter(check => check.status === "warning").length
    this.q("[data-results]").innerHTML = `
      <div class="a2d-result-banner ${failures ? "failure" : warnings ? "warning" : "pass"}">
        <strong>${failures ? "Validation failed" : warnings ? "Created with warnings" : "DSS validation passed"}</strong>
        <span>${failures} failures and ${warnings} warnings</span>
      </div>
      <h3>Output folder</h3>
      <code>${this.escape(result.output_dir)}</code>
      <button type="button" data-open-output>Open output folder</button>
      <h3>Files</h3>
      <ul>
        ${[
          result.dss_file,
          result.timeseries_file,
          result.timeseries_parquet,
          result.aoi_file,
          result.event_summary,
          result.download_log,
          result.processing_log,
          result.pathname_inventory,
          result.grid_metadata,
          result.validation_report,
          result.cog_file
        ].filter(Boolean).map((path: string) => `<li>${this.escape(path)}</li>`).join("")}
      </ul>
      <h3>Validation checks</h3>
      <table><thead><tr><th>Status</th><th>Check</th><th>Finding</th></tr></thead>
      <tbody>${checks.map(check => `
        <tr><td><span class="a2d-badge ${check.status}">${this.escape(check.status)}</span></td>
        <td>${this.escape(check.name)}</td><td>${this.escape(check.message)}</td></tr>
      `).join("")}</tbody></table>
      <details><summary>DSS pathname inventory, ${result.pathnames.length} records</summary>
        <pre>${this.escape(result.pathnames.join("\n"))}</pre>
      </details>
    `
    this.q<HTMLButtonElement>("[data-open-output]").addEventListener("click", () => {
      void this.client.openFolder(result.output_dir).catch(error => {
        this.status(`Output folder could not be opened: ${this.message(error)}`)
      })
    })
    try {
      const cogUrl = this.client.fileUrl(job.id, "event_summary.tif")
      await this.app.addCogLayer?.("AORC event summary", cogUrl, {
        colormap: result.visualization?.colormap ?? "gist_ncar",
        rescaleMin: result.visualization?.rescale_min ?? 0,
        rescaleMax: result.visualization?.rescale_max ?? 1,
        nodata: result.visualization?.nodata ?? -9999,
        opacity: 0.85
      })
    } catch (error) {
      this.status(`DSS finished. The summary COG could not be added to the map: ${this.message(error)}`)
    }
  }

  private async monitor(job: JobStatus): Promise<JobStatus> {
    this.activeJob = job.id
    this.pollController?.abort()
    this.pollController = new AbortController()
    this.showProgress(job)
    try {
      return await this.client.waitForJob(job.id, value => this.showProgress(value), this.pollController.signal)
    } finally {
      this.activeJob = null
      this.q<HTMLElement>("[data-progress-wrap]").hidden = true
    }
  }

  private showProgress(job: JobStatus): void {
    this.q<HTMLElement>("[data-progress-wrap]").hidden = false
    this.q<HTMLElement>("[data-progress-bar]").style.width = `${Math.round(job.progress * 100)}%`
    this.q("[data-progress-text]").textContent = `${Math.round(job.progress * 100)}%  ${job.message}`
  }

  private async cancelJob(): Promise<void> {
    if (!this.activeJob) return
    await this.client.cancel(this.activeJob)
    this.pollController?.abort()
    this.status("Cancellation requested.")
  }

  private editServiceUrl(): void {
    const value = window.prompt("Local processing service URL", this.state.serviceUrl)
    if (!value) return
    this.state.serviceUrl = value.replace(/\/+$/, "")
    this.client = new AORCServiceClient(this.state.serviceUrl)
    this.metadataLoaded = false
    this.variables = []
    void this.initialize()
  }

  private updatePathPreview(): void {
    const variable = this.selectedVariable()
    this.q("[data-path-preview]").textContent = previewGridPath(
      this.field<HTMLInputElement>("watershed")?.value || this.state.watershed,
      variable?.dss_parameter ?? "MET",
      Number(this.field<HTMLSelectElement>("cell-size")?.value || this.state.cellSize)
    )
  }

  private readPeriodInputs(): void {
    this.state.start = asUtcIso(this.field<HTMLInputElement>("start").value)
    this.state.end = asUtcIso(this.field<HTMLInputElement>("end").value)
    if (new Date(this.state.end) <= new Date(this.state.start)) {
      throw new Error("End time must be after start time")
    }
    const variable = this.selectedVariable()
    if (variable) {
      const availableStart = new Date(variable.start)
      const availableEndExclusive = new Date(new Date(variable.end).getTime() + 3_600_000)
      if (new Date(this.state.start) < availableStart || new Date(this.state.end) > availableEndExclusive) {
        throw new Error(`Requested period is outside ${variable.start} through ${variable.end}`)
      }
    }
  }

  private syncInputs(): void {
    this.field<HTMLSelectElement>("variable").value = this.state.variable
    this.field<HTMLSelectElement>("unit-system").value = this.state.unitSystem
    if (this.state.start) this.field<HTMLInputElement>("start").value = forDateTimeInput(this.state.start)
    if (this.state.end) this.field<HTMLInputElement>("end").value = forDateTimeInput(this.state.end)
    this.field<HTMLInputElement>("watershed").value = this.state.watershed
    this.field<HTMLSelectElement>("cell-size").value = String(this.state.cellSize)
    this.field<HTMLInputElement>("buffer-m").value = String(this.state.bufferM)
  }

  private selectedVariable(): VariableMetadata | undefined {
    return this.variables.find(variable => variable.source_name === this.state.variable)
  }

  private outputUnit(variable: VariableMetadata): string {
    if (variable.source_name === "APCP_surface") {
      return this.state.unitSystem === "us-customary" ? "in" : "mm"
    }
    if (variable.source_name === "TMP_2maboveground") {
      return this.state.unitSystem === "us-customary" ? "°F" : "°C"
    }
    return variable.units
  }

  private outputDssUnit(variable: VariableMetadata): string {
    if (variable.source_name === "APCP_surface") {
      return this.state.unitSystem === "us-customary" ? "IN" : "MM"
    }
    if (variable.source_name === "TMP_2maboveground") {
      return this.state.unitSystem === "us-customary" ? "DEG F" : "DEG C"
    }
    return variable.dss_units
  }

  private refreshVariableLabels(): void {
    const select = this.field<HTMLSelectElement>("variable")
    this.variables.forEach(variable => {
      const option = Array.from(select.options).find(item => item.value === variable.source_name)
      if (option) option.textContent = `${variable.display_name} (${this.outputUnit(variable)})`
    })
  }

  private openPage(id: string): void {
    this.container.querySelectorAll("[data-page]").forEach(page => {
      page.classList.toggle("active", (page as HTMLElement).dataset.page === id)
    })
    this.container.querySelectorAll("[data-tab]").forEach(tab => {
      tab.classList.toggle("active", (tab as HTMLElement).dataset.tab === id)
    })
    this.container.querySelector(".a2d-pages")?.scrollTo({ top: 0 })
  }

  private removeRainfallLegend(): void {
    if (!this.rainfallLegend) return
    this.app.removeMapControl(this.rainfallLegend)
    this.rainfallLegend = null
  }

  private clearAnimationPresentation(): void {
    this.detachTimeSliderCursor()
    this.removeRainfallLegend()
    this.eventChart?.setCursorTime(null)
    const legend = this.container.querySelector<HTMLElement>("[data-animation-legend]")
    if (legend) {
      legend.hidden = true
      legend.replaceChildren()
    }
  }

  private formatLegendValue(value: number, maximum: number): string {
    if (maximum <= 5) return value.toFixed(2)
    if (maximum <= 50) return value.toFixed(1)
    return Math.round(value).toString()
  }

  private attachTimeSliderCursor(times: string[], revision: number, attempt = 0): void {
    if (attempt === 0) this.detachTimeSliderCursor()
    if (revision !== this.animationRevision) return
    const marker = document.querySelector<HTMLElement>(
      ".maplibregl-time-slider-dock .ts-marker-label"
    )
    if (!marker) {
      if (attempt >= 40) return
      this.timeSliderSearchTimer = window.setTimeout(
        () => this.attachTimeSliderCursor(times, revision, attempt + 1),
        50
      )
      return
    }
    this.timeSliderSearchTimer = null
    const timeByLabel = new Map(times.map(time => [this.timeSliderLabel(time), time]))
    const update = (): void => {
      const activeTime = timeByLabel.get(marker.textContent?.trim() ?? "")
      if (activeTime) this.eventChart?.setCursorTime(activeTime)
    }
    this.timeSliderObserver = new MutationObserver(update)
    this.timeSliderObserver.observe(marker, {
      childList: true,
      characterData: true,
      subtree: true
    })
    update()
  }

  private detachTimeSliderCursor(): void {
    this.timeSliderObserver?.disconnect()
    this.timeSliderObserver = null
    if (this.timeSliderSearchTimer !== null) {
      window.clearTimeout(this.timeSliderSearchTimer)
      this.timeSliderSearchTimer = null
    }
  }

  private timeSliderLabel(value: string): string {
    const date = new Date(value)
    const months = [
      "Jan", "Feb", "Mar", "Apr", "May", "Jun",
      "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"
    ]
    const pad = (part: number): string => String(part).padStart(2, "0")
    return `${date.getUTCFullYear()} ${months[date.getUTCMonth()]} ` +
      `${pad(date.getUTCDate())} ${pad(date.getUTCHours())}:00`
  }

  private onAction(name: string, callback: () => void): void {
    this.q<HTMLButtonElement>(`[data-action="${name}"]`).addEventListener("click", callback)
  }

  private field<T extends HTMLElement>(name: string): T {
    return this.q<T>(`[data-field="${name}"]`)
  }

  private q<T extends HTMLElement = HTMLElement>(selector: string): T {
    const element = this.container.querySelector<T>(selector)
    if (!element) throw new Error(`Missing interface element ${selector}`)
    return element
  }

  private status(message: string): void {
    const element = this.q("[data-status]")
    element.textContent = message
    element.hidden = false
    window.setTimeout(() => {
      if (element.textContent === message) element.hidden = true
    }, 6500)
  }

  private message(error: unknown): string {
    return error instanceof Error ? error.message : String(error)
  }

  private escape(value: unknown): string {
    const element = document.createElement("span")
    element.textContent = String(value ?? "")
    return element.innerHTML
  }
}
