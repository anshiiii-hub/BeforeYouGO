import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import { Discover } from '../pages/Discover'
import { AuthProvider } from '../auth/AuthContext'
import { EMPTY_FILTERS, filtersToQuery, filtersToSearchParams, paramsToFilters } from '../lib/filters'
import { baseCard, mockFetch } from './helpers'

const index = { events_indexed: 10, connectors: 2, connectors_active: 2, connectors_failing: [], last_successful_sync_at: null, scope: 'Results come only from connected sources.', state: 'ok' }
const facets = { categories: [{ value: 'hackathon', count: 4 }, { value: 'conference', count: 9 }], formats: [{ value: 'online', count: 3 }], countries: [], cities: [], topics: [], sources: [{ value: 'src', label: 'Source A', count: 5 }], origins: [], fee: [] }

describe('filters to query wiring', () => {
  it('maps filters to API parameters and omits empty ones', () => {
    const q = filtersToQuery({ ...EMPTY_FILTERS, q: ' free ai ', category: ['hackathon'], format: ['online', 'hybrid'], max_fee: '500', include_unknown_cost: true, certificate: true, require_known: ['fee', 'deadline'], sort: 'deadline', page: 3 })
    expect(q).toEqual({ q: 'free ai', category: ['hackathon'], format: ['online', 'hybrid'], max_fee: '500', include_unknown_cost: true, certificate: true, require_known: ['fee', 'deadline'], sort: 'deadline', page: 3 })
    expect(filtersToQuery(EMPTY_FILTERS)).toEqual({})
  })
  it('round-trips through the URL', () => {
    const f = { ...EMPTY_FILTERS, category: ['workshop'], city: 'Delhi', deadline_from: '2026-11-01', free_only: true, require_known: ['eligibility'] }
    const back = paramsToFilters(filtersToSearchParams(f))
    expect(back).toEqual(f)
  })
  it('sends the chosen filters to /api/events when applied', async () => {
    const calls = mockFetch((u) => {
      if (u.pathname === '/api/events/facets') return { body: facets }
      if (u.pathname === '/api/events') return { body: { items: [baseCard()], total: 1, page: 1, page_size: 20, interpretation: { understood: [], keywords: [], applied: {} }, notes: [], broadened: false, state: 'ok', index, personalized: false } }
    })
    render(<MemoryRouter initialEntries={['/discover']}><AuthProvider><Discover /></AuthProvider></MemoryRouter>)
    const user = userEvent.setup()
    await screen.findByText('Test Hackathon')
    await user.click(await screen.findByLabelText(/Hackathon \(4\)/))
    await user.type(screen.getByLabelText('Maximum fee (INR)'), '300')
    await user.click(screen.getByLabelText(/Certificate offered/))
    await user.click(screen.getByRole('button', { name: 'Apply filters' }))
    await waitFor(() => {
      const last = calls.filter((c) => c.url.pathname === '/api/events').slice(-1)[0].url.searchParams
      expect(last.getAll('category')).toEqual(['hackathon'])
      expect(last.get('max_fee')).toBe('300')
      expect(last.get('certificate')).toBe('true')
    })
    expect(await screen.findByRole('list', { name: 'Active filters' })).toBeInTheDocument()
    const chips = within(screen.getByRole('list', { name: 'Active filters' }))
    expect(chips.getByText('Category: Hackathon')).toBeInTheDocument()
  })
  it('sends the natural-language query', async () => {
    const calls = mockFetch((u) => {
      if (u.pathname === '/api/events/facets') return { body: facets }
      if (u.pathname === '/api/events') return { body: { items: [], total: 0, page: 1, page_size: 20, interpretation: { understood: ['Stated as free'], keywords: [], applied: {} }, notes: [], broadened: false, state: 'empty_result', index, personalized: false } }
    })
    render(<MemoryRouter initialEntries={['/discover']}><AuthProvider><Discover /></AuthProvider></MemoryRouter>)
    const user = userEvent.setup()
    await user.type(await screen.findByLabelText('Search events in plain language'), 'free online hackathon')
    await user.click(screen.getByRole('button', { name: 'Search' }))
    await waitFor(() => expect(calls.some((c) => c.url.searchParams.get('q') === 'free online hackathon')).toBe(true))
    expect(await screen.findByText('No events match')).toBeInTheDocument()
    expect(screen.getByText(/What we understood/)).toBeInTheDocument()
  })
  it('shows an error state with retry when search fails', async () => {
    mockFetch((u) => {
      if (u.pathname === '/api/events/facets') return { body: facets }
      return { status: 500, body: { error: { code: 'internal_error', message: 'An unexpected error occurred.', details: [], request_id: 'req9' } } }
    })
    render(<MemoryRouter initialEntries={['/discover']}><AuthProvider><Discover /></AuthProvider></MemoryRouter>)
    expect(await screen.findByText('Search failed')).toBeInTheDocument()
    expect(screen.getByText('Reference: req9')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument()
  })
})
