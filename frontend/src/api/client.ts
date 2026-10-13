// Small typed API client. Every failure becomes an ApiError built from the backend's
// {error:{code,message,details,request_id}} envelope (or a synthesised equivalent).

export class ApiError extends Error {
  status: number
  code: string
  details: unknown[]
  requestId: string | null
  constructor(status: number, code: string, message: string, details: unknown[] = [], requestId: string | null = null) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.details = details
    this.requestId = requestId
  }
  get isAuth() { return this.status === 401 }
  get isForbidden() { return this.status === 403 }
  get isNotFound() { return this.status === 404 }
}

const TOKEN_KEY = 'byg.token'
export const SESSION_EXPIRED_EVENT = 'byg:session-expired'
const SESSION_CODES = new Set(['token_revoked', 'invalid_token', 'account_disabled', 'token_expired'])
let inMemoryToken: string | null = null

export function getToken(): string | null {
  try { return window.localStorage.getItem(TOKEN_KEY) } catch { return inMemoryToken }
}
export function setToken(t: string | null) {
  inMemoryToken = t
  try { if (t) window.localStorage.setItem(TOKEN_KEY, t); else window.localStorage.removeItem(TOKEN_KEY) } catch { /* storage unavailable */ }
}

export type Query = Record<string, string | number | boolean | null | undefined | (string | number)[]>

export function buildQuery(q?: Query): string {
  if (!q) return ''
  const p = new URLSearchParams()
  for (const [k, v] of Object.entries(q)) {
    if (v === null || v === undefined || v === '' || v === false) continue
    if (Array.isArray(v)) v.forEach((x) => p.append(k, String(x)))
    else p.set(k, String(v))
  }
  const s = p.toString()
  return s ? `?${s}` : ''
}

interface Opts {
  query?: Query
  body?: unknown
  form?: FormData
  signal?: AbortSignal
  auth?: boolean
}

function toApiError(status: number, payload: unknown, fallback: string): ApiError {
  const env = (payload as { error?: { code?: string; message?: string; details?: unknown[]; request_id?: string } } | null)?.error
  if (env && typeof env === 'object') {
    return new ApiError(status, env.code ?? 'http_error', env.message ?? fallback, Array.isArray(env.details) ? env.details : [], env.request_id ?? null)
  }
  const detail = (payload as { detail?: unknown } | null)?.detail
  return new ApiError(status, status >= 500 ? 'server_error' : 'http_error', typeof detail === 'string' ? detail : fallback)
}

async function raw(method: string, path: string, opts: Opts = {}): Promise<Response> {
  const headers: Record<string, string> = { Accept: 'application/json' }
  const token = getToken()
  if (token && opts.auth !== false) headers.Authorization = `Bearer ${token}`
  let body: BodyInit | undefined
  if (opts.form) body = opts.form
  else if (opts.body !== undefined) { headers['Content-Type'] = 'application/json'; body = JSON.stringify(opts.body) }
  let res: Response
  try {
    res = await fetch(`/api${path}${buildQuery(opts.query)}`, { method, headers, body, signal: opts.signal })
  } catch (e) {
    if ((e as Error)?.name === 'AbortError') throw e
    throw new ApiError(0, 'network_error', 'Could not reach the BeforeYouGo server. Check your connection and try again.')
  }
  if (!res.ok) {
    let payload: unknown = null
    try { payload = await res.json() } catch { /* non-JSON error body */ }
    const err = toApiError(res.status, payload, res.status >= 500 ? 'The server had a problem handling that request.' : `Request failed (${res.status}).`)
    if (res.status === 401 && token && (SESSION_CODES.has(err.code) || err.code === 'unauthorized')) {
      setToken(null)
      window.dispatchEvent(new CustomEvent(SESSION_EXPIRED_EVENT))
    }
    throw err
  }
  return res
}

export async function request<T>(method: string, path: string, opts: Opts = {}): Promise<T> {
  const res = await raw(method, path, opts)
  if (res.status === 204) return undefined as T
  try { return (await res.json()) as T } catch {
    throw new ApiError(res.status, 'bad_response', 'The server returned a response this app could not read.')
  }
}

export async function download(path: string, query: Query, fileName: string): Promise<void> {
  const res = await raw('GET', path, { query })
  const blob = await res.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = fileName
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 2000)
}

export const api = {
  get: <T,>(path: string, query?: Query, signal?: AbortSignal) => request<T>('GET', path, { query, signal }),
  post: <T,>(path: string, body?: unknown, query?: Query) => request<T>('POST', path, { body: body ?? {}, query }),
  put: <T,>(path: string, body?: unknown) => request<T>('PUT', path, { body: body ?? {} }),
  patch: <T,>(path: string, body?: unknown) => request<T>('PATCH', path, { body: body ?? {} }),
  del: <T,>(path: string, body?: unknown) => request<T>('DELETE', path, body === undefined ? {} : { body }),
  upload: <T,>(path: string, form: FormData) => request<T>('POST', path, { form }),
}

/** Human-readable text for any thrown value, including field-level validation details. */
export function describeError(e: unknown): string {
  if (e instanceof ApiError) {
    const parts = e.details
      .map((d) => (typeof d === 'string' ? d : d && typeof d === 'object' && 'message' in d ? `${(d as { field?: string }).field ? (d as { field?: string }).field + ': ' : ''}${(d as { message: string }).message}` : ''))
      .filter(Boolean)
    return parts.length ? `${e.message} ${parts.join(' ')}` : e.message
  }
  return e instanceof Error ? e.message : 'Something went wrong.'
}
