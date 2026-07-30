export function asUtcIso(localValue: string): string {
  if (!localValue) throw new Error("A date and time is required")
  const normalized = localValue.length === 16 ? `${localValue}:00Z` : `${localValue}Z`
  const value = new Date(normalized)
  if (Number.isNaN(value.getTime())) throw new Error("Date and time is invalid")
  return value.toISOString()
}

export function forDateTimeInput(iso: string): string {
  return new Date(iso).toISOString().slice(0, 16)
}

export function durationEvent(start: string, hours: number): { start: string; end: string } {
  if (!Number.isInteger(hours) || hours <= 0) throw new Error("Duration must be a positive hour count")
  const startDate = new Date(start)
  return {
    start: startDate.toISOString(),
    end: new Date(startDate.getTime() + hours * 3_600_000).toISOString()
  }
}
