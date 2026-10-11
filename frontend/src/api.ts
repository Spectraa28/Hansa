export type Session = { user: { id: string; name: string; email: string | null; avatar_url?: string | null }; csrf_token: string }
export type Providers = { google: boolean; github: boolean; email: boolean }
export type ImportItem = {
  id: string
  repository_name: string
  branch: string
  commit_sha: string
  status: string
  failure_reason: string | null
  created_at: number
}
export type ImportsPage = { imports: ImportItem[]; page: number; has_next: boolean }

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message)
  }
}

async function request(path: string, options: RequestInit = {}): Promise<Response> {
  const response = await fetch(path, { ...options, credentials: 'include' })
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    throw new ApiError(response.status, typeof body?.detail === 'string'
      ? body.detail : `Request failed (${response.status}). Please try again.`)
  }
  return response
}

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  return (await request(path, options)).json()
}

export async function apiText(path: string): Promise<string> {
  return (await request(path)).text()
}

export async function currentSession(signal: AbortSignal): Promise<Session | null> {
  try {
    return await api<Session>('/auth/me', { signal })
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) return null
    throw error
  }
}

// A JSON mutation with the session's CSRF token.
export async function send<T>(path: string, csrf: string, body?: unknown, method = 'POST'): Promise<T> {
  const response = await request(path, { method, headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf }, body: body === undefined ? undefined : JSON.stringify(body) })
  return response.status === 204 ? null as T : response.json()
}
