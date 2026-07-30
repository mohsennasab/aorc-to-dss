import type {
  AnimationPreloadStatus,
  AnimationRegistration,
  JobStatus,
  VariableMetadata
} from "../types"

export class ServiceError extends Error {
  constructor(message: string, readonly status: number) {
    super(message)
  }
}

export class AORCServiceClient {
  constructor(readonly baseUrl = "http://127.0.0.1:8765") {}

  private async request<T>(path: string, init?: RequestInit, timeoutMs = 15_000): Promise<T> {
    const controller = new AbortController()
    const timer = window.setTimeout(() => controller.abort(), timeoutMs)
    try {
      const response = await fetch(`${this.baseUrl}${path}`, {
        ...init,
        signal: init?.signal ?? controller.signal,
        headers: {
          "Content-Type": "application/json",
          ...init?.headers
        }
      })
      const body = await response.json().catch(() => ({}))
      if (!response.ok) {
        throw new ServiceError(body.error || `Service returned ${response.status}`, response.status)
      }
      return body as T
    } finally {
      window.clearTimeout(timer)
    }
  }

  health(): Promise<{ status: string; version: string; dss: { available: boolean; message: string } }> {
    return this.request("/health", undefined, 3_000)
  }

  metadata(): Promise<{ variables: VariableMetadata[]; years: number[] }> {
    return this.request("/metadata/variables", undefined, 90_000)
  }

  validateGeometry(payload: unknown): Promise<any> {
    return this.request("/geometry/validate", {
      method: "POST",
      body: JSON.stringify(payload)
    })
  }

  estimate(payload: unknown): Promise<any> {
    return this.request("/estimate", {
      method: "POST",
      body: JSON.stringify(payload)
    })
  }

  startTimeseries(payload: unknown): Promise<JobStatus> {
    return this.request("/jobs/timeseries", {
      method: "POST",
      body: JSON.stringify(payload)
    })
  }

  startExport(payload: unknown): Promise<JobStatus> {
    return this.request("/jobs/export", {
      method: "POST",
      body: JSON.stringify(payload)
    })
  }

  createAnimation(payload: unknown): Promise<AnimationRegistration> {
    return this.request("/animations", {
      method: "POST",
      body: JSON.stringify(payload)
    })
  }

  startAnimationPreload(id: string): Promise<AnimationPreloadStatus> {
    return this.request(`/animations/${id}/preload`, {
      method: "POST",
      body: "{}"
    })
  }

  animationStatus(id: string): Promise<AnimationPreloadStatus> {
    return this.request(`/animations/${id}`)
  }

  async waitForAnimation(
    id: string,
    onUpdate: (status: AnimationPreloadStatus) => void
  ): Promise<AnimationPreloadStatus> {
    while (true) {
      const status = await this.animationStatus(id)
      onUpdate(status)
      if (status.state === "complete") return status
      if (status.state === "failed") {
        throw new Error(status.error || status.message)
      }
      await new Promise(resolve => window.setTimeout(resolve, 500))
    }
  }

  chooseFolder(): Promise<{ path: string }> {
    return this.request("/dialogs/folder", {
      method: "POST",
      body: "{}"
    })
  }

  savePng(dataUrl: string, suggestedName: string): Promise<{ path: string }> {
    return this.request("/dialogs/save-png", {
      method: "POST",
      body: JSON.stringify({ data_url: dataUrl, suggested_name: suggestedName })
    })
  }

  openFolder(path: string): Promise<{ opened: boolean }> {
    return this.request("/open-folder", {
      method: "POST",
      body: JSON.stringify({ path })
    })
  }

  job(id: string): Promise<JobStatus> {
    return this.request(`/jobs/${id}`)
  }

  cancel(id: string): Promise<{ cancelled: boolean }> {
    return this.request(`/jobs/${id}`, { method: "DELETE" })
  }

  fileUrl(jobId: string, relativePath: string): string {
    const path = relativePath.split("/").map(encodeURIComponent).join("/")
    return `${this.baseUrl}/jobs/${jobId}/files/${path}`
  }

  async waitForJob(
    id: string,
    onUpdate: (job: JobStatus) => void,
    signal?: AbortSignal
  ): Promise<JobStatus> {
    while (!signal?.aborted) {
      const job = await this.job(id)
      onUpdate(job)
      if (["complete", "failed", "cancelled"].includes(job.state)) return job
      await new Promise<void>((resolve, reject) => {
        const timer = window.setTimeout(resolve, 750)
        signal?.addEventListener("abort", () => {
          window.clearTimeout(timer)
          reject(new DOMException("Aborted", "AbortError"))
        }, { once: true })
      })
    }
    throw new DOMException("Aborted", "AbortError")
  }
}
