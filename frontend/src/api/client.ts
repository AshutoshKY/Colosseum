import type { DryRun, RunSpec } from '../types'
import { getToken, handleUnauthorized } from './auth'

/**
 * API base. Empty by default so requests hit the same origin and are proxied:
 * by Vite in dev (`server.proxy`) and by nginx in the production image.
 * Set VITE_API_BASE to call a remote API directly (CORS must allow it).
 */
const API_BASE = import.meta.env.VITE_API_BASE ?? ''

export class ApiError extends Error {
  constructor(public status: number, public body: unknown) {
    super(errorMessage(body) || `Request failed (${status})`)
  }
}

function errorMessage(body: unknown) {
  if (!body || typeof body !== 'object') return String(body ?? '')
  const data = body as Record<string, unknown>
  if (typeof data.detail === 'string') return data.detail
  if (typeof data.message === 'string') return data.message
  return ''
}

export async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const headers = new Headers(options?.headers)
  if (options?.body && !(options.body instanceof FormData)) headers.set('Content-Type', 'application/json')
  const token = getToken()
  if (token) headers.set('Authorization', `Bearer ${token}`)

  const response = await fetch(`${API_BASE}/api${path}`, { ...options, headers })
  const body = response.status === 204 ? null : await response.json().catch(() => null)
  if (response.status === 401) handleUnauthorized()
  if (!response.ok) throw new ApiError(response.status, body)
  return body as T
}

export const postJson = <T>(path: string, body?: unknown) =>
  api<T>(path, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) })

export const putJson = <T>(path: string, body: unknown) =>
  api<T>(path, { method: 'PUT', body: JSON.stringify(body) })

export const dryRun = (spec: RunSpec) => postJson<DryRun>('/runs/dry-run', spec)

export const uploadFiles = (path: string, files: File[], field = 'files') => {
  const form = new FormData()
  files.forEach(file => form.append(field, file))
  return api(path, { method: 'POST', body: form })
}

export function asList<T>(value: T[] | Record<string, T[]> | undefined, key: string): T[] {
  return Array.isArray(value) ? value : value?.[key] ?? []
}
