export type Position = "top-left" | "top-right" | "bottom-left" | "bottom-right"

export interface Feature {
  type: "Feature"
  geometry: Geometry
  properties?: Record<string, unknown>
}

export interface FeatureCollection {
  type: "FeatureCollection"
  features: Feature[]
}

export interface Geometry {
  type: string
  coordinates: unknown
}

export interface MapSource {
  setData(data: FeatureCollection): void
}

export interface MapFeature {
  geometry: Geometry
  properties?: Record<string, unknown>
  source?: string
  layer?: { id: string }
}

export interface MapLike {
  on(event: string, handler: (event: any) => void): void
  off(event: string, handler: (event: any) => void): void
  once(event: string, handler: () => void): void
  getSource(id: string): MapSource | undefined
  addSource(id: string, source: unknown): void
  removeSource(id: string): void
  getLayer(id: string): unknown
  addLayer(layer: unknown): void
  removeLayer(id: string): void
  queryRenderedFeatures(point: unknown): MapFeature[]
  getCanvas(): HTMLCanvasElement
  doubleClickZoom?: {
    disable(): void
    enable(): void
    isEnabled?(): boolean
  }
}

export interface PickedVectorFile {
  file: File
  companionFiles: File[]
  sourcePath?: string
  nativeData?: FeatureCollection
}

export interface ZarrOptions {
  variable?: string
  selector?: Record<string, number | string>
  crs?: string
  colormap?: string
  rescale?: [number, number]
  zarrVersion?: 2 | 3
  bounds?: [number, number, number, number]
  spatialDimensions?: { lat?: string; lon?: string }
}

export interface CogOptions {
  colormap?: string
  rescaleMin?: number
  rescaleMax?: number
  nodata?: number
  opacity?: number
}

export interface AnimationRegistration {
  id: string
  times: string[]
  url_template: string
  bounds: [number, number, number, number]
  units: string
  colormap: string
  rescale: [number, number]
  nodata: number
}

export interface AnimationPreloadStatus {
  id: string
  state: "not_started" | "queued" | "running" | "complete" | "failed"
  progress: number
  completed: number
  total: number
  message: string
  error: string | null
}

export interface TemporalLayerAdapter {
  getTimeValues: () => ReadonlyArray<Date | number | string>
  setTime: (date: Date) => void | Promise<void>
  dimension?: string
  granularity?: "hour" | "day" | "month" | "year"
  displayUnits?: Array<"hour" | "day" | "month" | "year">
}

export interface GeoLibreAppAPI {
  getMap?: () => MapLike | null
  fitBounds?: (bounds: [number, number, number, number]) => void
  openExternalUrl?: (url: string) => void
  addGeoJsonLayer: (name: string, data: FeatureCollection, sourcePath?: string) => string
  addCogLayer?: (name: string, url: string, options?: CogOptions) => Promise<string>
  addZarrLayer?: (name: string, url: string, options?: ZarrOptions) => Promise<string>
  setZarrLayerSelector?: (
    layerId: string,
    selector: Record<string, number | string>
  ) => Promise<boolean>
  activatePlugin?: (pluginId: string, state?: unknown) => Promise<boolean>
  registerTemporalLayer?: (
    layerId: string,
    adapter: TemporalLayerAdapter,
    options?: { bind?: boolean }
  ) => () => void
  unregisterTemporalLayer?: (layerId: string) => void
  pickVectorFilesWithSidecars?: () => Promise<PickedVectorFile[]>
  importTextFile?: (options?: {
    description?: string
    extensions?: string[]
    suggestedName?: string
  }) => Promise<string | null>
  exportTextFile?: (
    filename: string,
    content: string,
    options?: { description?: string; extensions?: string[]; suggestedName?: string }
  ) => void
  registerRightPanel?: (panel: {
    id: string
    title: string
    icon?: string
    dock?: "replace-style" | "replace-layers" | "left-of-style" | "right-of-style"
    defaultWidth?: number
    render: (container: HTMLElement) => void | (() => void)
  }) => () => void
  openRightPanel?: (id: string) => boolean
  closeRightPanel?: (id: string) => void
  registerToolbarMenu?: (menu: {
    id: string
    label: string
    items: Array<{
      id: string
      label: string
      onSelect: () => void
      disabled?: boolean
    }>
  }) => () => void
  addMapControl: (control: MapControl, position?: Position) => boolean
  removeMapControl: (control: MapControl) => void
}

export interface MapControl {
  onAdd(map: MapLike): HTMLElement
  onRemove(): void
}

export interface GeoLibrePlugin {
  id: string
  name: string
  version: string
  activate(app: GeoLibreAppAPI): boolean | void
  deactivate(app: GeoLibreAppAPI): void
  getProjectState?: () => unknown
  applyProjectState?: (app: GeoLibreAppAPI, state: unknown) => boolean | void
}

export interface VariableMetadata {
  source_name: string
  display_name: string
  units: string
  temporal_resolution: string
  start: string
  end: string
  missing_value: number
  description: string
  aggregation: "sum" | "mean" | "instant"
  dss_parameter: string
  dss_units: string
  dss_data_type: number
}

export interface TimeSeriesPoint {
  time: string
  value: number | null
  units: string
  quality: string
}

export interface JobStatus {
  id: string
  kind: string
  state: "queued" | "running" | "complete" | "failed" | "cancelled"
  progress: number
  message: string
  result?: any
  error?: {
    code: string
    message: string
    guidance?: string
    retryable?: boolean
  }
}

export interface PluginState {
  serviceUrl: string
  aoi: FeatureCollection | null
  variable: string
  start: string
  end: string
  unitSystem: "metric" | "us-customary"
  watershed: string
  cellSize: number
  bufferM: number
}
