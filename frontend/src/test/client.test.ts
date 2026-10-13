import { describe, expect, it, vi } from 'vitest'
import { ApiError, api, buildQuery, describeError, getToken, setToken, SESSION_EXPIRED_EVENT } from '../api/client'
import { mockFetch } from './helpers'

describe('api client error handling', () => {
  it('parses the {error:{code,message,details,request_id}} envelope into an ApiError', async () => {
    mockFetch(() => ({ status: 422, body: { error: { code: 'weak_password', message: 'That password is too weak.', details: ['Add a digit.'], request_id: 'abc123' } } }))
    const err = (await api.post('/auth/register', {}).catch((e) => e)) as ApiError
    expect(err).toBeInstanceOf(ApiError)
    expect(err.status).toBe(422)
    expect(err.code).toBe('weak_password')
    expect(err.requestId).toBe('abc123')
    expect(describeError(err)).toContain('Add a digit.')
  })

  it('formats field-level validation details', () => {
    const e = new ApiError(422, 'validation_error', 'Request validation failed.', [{ field: 'email', message: 'not a valid email' }])
    expect(describeError(e)).toBe('Request validation failed. email: not a valid email')
  })

  it('turns a dropped connection into a network_error', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => { throw new TypeError('Failed to fetch') }))
    const err = (await api.get('/events').catch((e) => e)) as ApiError
    expect(err.code).toBe('network_error')
    expect(err.status).toBe(0)
  })

  it('handles non-JSON error bodies (for example a proxy 502)', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('<html>Bad gateway</html>', { status: 502 })))
    const err = (await api.get('/events').catch((e) => e)) as ApiError
    expect(err).toBeInstanceOf(ApiError)
    expect(err.status).toBe(502)
    expect(err.code).toBe('server_error')
  })

  it('clears the token and announces an expired session on a revoked token', async () => {
    setToken('stale')
    const heard = vi.fn()
    window.addEventListener(SESSION_EXPIRED_EVENT, heard)
    mockFetch(() => ({ status: 401, body: { error: { code: 'token_revoked', message: 'Session has been revoked.', details: [], request_id: null } } }))
    await api.get('/me').catch(() => undefined)
    expect(getToken()).toBeNull()
    expect(heard).toHaveBeenCalled()
    window.removeEventListener(SESSION_EXPIRED_EVENT, heard)
  })

  it('keeps the token on a plain 403', async () => {
    setToken('good')
    mockFetch(() => ({ status: 403, body: { error: { code: 'role_forbidden', message: 'This action requires one of the roles: admin.', details: [], request_id: null } } }))
    const err = (await api.get('/admin/users').catch((e) => e)) as ApiError
    expect(err.isForbidden).toBe(true)
    expect(getToken()).toBe('good')
  })

  it('sends the bearer token and JSON body', async () => {
    setToken('tok')
    const calls = mockFetch(() => ({ body: { ok: true } }))
    await api.post('/x', { a: 1 })
    const h = calls[0].init?.headers as Record<string, string>
    expect(h.Authorization).toBe('Bearer tok')
    expect(calls[0].init?.body).toBe('{"a":1}')
  })

  it('builds queries without empty, false or null values', () => {
    expect(buildQuery({ q: 'ai', free_only: false, page: 2, category: ['a', 'b'], city: '', x: null })).toBe('?q=ai&page=2&category=a&category=b')
  })
})
