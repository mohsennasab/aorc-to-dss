import "./styles.css"
import type {
  GeoLibreAppAPI,
  GeoLibrePlugin,
  MapControl,
  MapLike,
  PluginState
} from "./types"
import { AORCWorkbench } from "./ui/workbench"

const PLUGIN_ID = "aorctodss"
const PANEL_ID = "aorctodss-workbench"
const ICON = new URL("../geolibre-plugin/icons/aorctodss.png", import.meta.url).href

class LauncherControl implements MapControl {
  private container: HTMLElement | null = null

  constructor(private readonly open: () => void) {}

  onAdd(_map: MapLike): HTMLElement {
    const container = document.createElement("div")
    container.className = "maplibregl-ctrl maplibregl-ctrl-group a2d-launcher"
    const button = document.createElement("button")
    button.type = "button"
    button.title = "Open AORCtoDSS"
    button.setAttribute("aria-label", "Open AORCtoDSS")
    const image = document.createElement("img")
    image.src = ICON
    image.alt = ""
    button.append(image)
    button.addEventListener("click", this.open)
    container.append(button)
    this.container = container
    return container
  }

  onRemove(): void {
    this.container?.remove()
    this.container = null
  }
}

let launcher: LauncherControl | null = null
let workbench: AORCWorkbench | null = null
let disposePanel: (() => void) | null = null
let disposeMenu: (() => void) | null = null
let pendingState: Partial<PluginState> | undefined

function validState(value: unknown): value is Partial<PluginState> {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false
  const state = value as Record<string, unknown>
  if ("serviceUrl" in state && typeof state.serviceUrl !== "string") return false
  if ("variable" in state && typeof state.variable !== "string") return false
  if (
    "unitSystem" in state &&
    state.unitSystem !== "metric" &&
    state.unitSystem !== "us-customary"
  ) return false
  if ("cellSize" in state && typeof state.cellSize !== "number") return false
  return true
}

export const plugin: GeoLibrePlugin = {
  id: PLUGIN_ID,
  name: "AORCtoDSS",
  version: "0.2.0",
  activate(app: GeoLibreAppAPI) {
    const open = () => {
      if (!app.openRightPanel?.(PANEL_ID)) {
        window.alert("This GeoLibre build does not provide plugin workbench panels.")
      }
    }
    disposePanel = app.registerRightPanel?.({
      id: PANEL_ID,
      title: "AORCtoDSS",
      icon: ICON,
      dock: "replace-style",
      defaultWidth: 520,
      render(container) {
        workbench = new AORCWorkbench(container, app, pendingState)
        return () => {
          pendingState = workbench?.getState()
          workbench?.destroy()
          workbench = null
        }
      }
    }) ?? null
    disposeMenu = app.registerToolbarMenu?.({
      id: "aorctodss-menu",
      label: "AORCtoDSS",
      items: [
        { id: "aorctodss-open", label: "Open workflow", onSelect: open },
        {
          id: "aorctodss-docs",
          label: "AORC data source",
          onSelect: () => app.openExternalUrl?.("https://registry.opendata.aws/noaa-nws-aorc/")
        },
        {
          id: "aorctodss-developer",
          label: "Developer website",
          onSelect: () => app.openExternalUrl?.("https://hydromohsen.com/")
        }
      ]
    }) ?? null
    launcher = new LauncherControl(open)
    if (!app.addMapControl(launcher, "top-right")) {
      launcher = null
      disposeMenu?.()
      disposePanel?.()
      return false
    }
    window.setTimeout(open, 0)
  },
  deactivate(app: GeoLibreAppAPI) {
    pendingState = workbench?.getState() ?? pendingState
    workbench?.destroy()
    workbench = null
    app.closeRightPanel?.(PANEL_ID)
    disposeMenu?.()
    disposeMenu = null
    disposePanel?.()
    disposePanel = null
    if (launcher) app.removeMapControl(launcher)
    launcher = null
  },
  getProjectState() {
    return workbench?.getState() ?? pendingState
  },
  applyProjectState(_app, state) {
    if (!validState(state)) return false
    pendingState = state
    workbench?.applyState(state)
  }
}

export default plugin
