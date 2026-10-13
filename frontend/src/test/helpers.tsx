import { vi } from 'vitest'

export type Handler = (url: URL, init?: RequestInit) => { status?: number; body?: unknown } | undefined

/** Installs a fetch mock that routes by pathname. Returns the list of requested URLs. */
export function mockFetch(handler: Handler) {
  const calls: { url: URL; init?: RequestInit }[] = []
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(typeof input === 'string' ? input : input.toString(), 'http://localhost')
    calls.push({ url, init })
    const r = handler(url, init) ?? { status: 404, body: { error: { code: 'not_found', message: 'No mock for ' + url.pathname, details: [], request_id: null } } }
    const status = r.status ?? 200
    return new Response(JSON.stringify(r.body ?? {}), { status, headers: { 'Content-Type': 'application/json' } })
  }))
  return calls
}

export const user = (role: string) => ({ id: 'u1', email: `${role}@example.com`, display_name: `Test ${role}`, role, created_at: null, organizations: [], has_profile: false })

export const baseCard = (over: Record<string, unknown> = {}) => ({
  id: 'e1', title: 'Test Hackathon', organizer: null, category: 'hackathon', format: 'online', topics: [], start_date: '2026-11-01', end_date: '2026-11-02',
  registration_deadline: null, deadline_stated: false, location: 'Online', city: null, country: null,
  fee: { status: 'unknown', label: 'Not stated (not the same as free)', amount: null, currency: null, uncertain: true },
  lifecycle_status: 'scheduled', canonical_url: 'https://example.org/e', origin: { type: 'indexed', label: 'Indexed from a connected source' },
  sources: [{ key: 's', name: 'Source A', retrieved_at: '2026-10-11T00:00:00Z' }], freshness: { state: 'fresh', message: 'Retrieved 0 day(s) ago.', last_retrieved_at: null, age_days: 0 },
  completeness: { score: 31, filled: 4, total: 13 }, missing_information: ['Registration deadline', 'Fee stated (free or amount)'], matched_because: ['Category: hackathon'],
  claims_count: 0, verification_state: 'source_listed', saved: false, fit: null, ...over,
})
