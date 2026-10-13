import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import { App } from '../App'
import { AuthProvider } from '../auth/AuthContext'
import { setToken } from '../api/client'
import { mockFetch, user } from './helpers'

function renderAt(path: string) {
  return render(<MemoryRouter initialEntries={[path]}><AuthProvider><App /></AuthProvider></MemoryRouter>)
}
const empty = { body: { items: [], total: 0 } }

describe('route guards', () => {
  it('sends a signed-out visitor to sign in', async () => {
    mockFetch(() => empty)
    renderAt('/me')
    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument()
    expect(screen.getByText(/Sign in to continue to the page you asked for/)).toBeInTheDocument()
  })
  it('shows a permission-denied state when a student opens the organizer area', async () => {
    setToken('t')
    mockFetch((u) => (u.pathname === '/api/me' ? { body: user('student') } : empty))
    renderAt('/organizer')
    expect(await screen.findByText('You do not have access to this')).toBeInTheDocument()
    expect(screen.getByText(/Your account is a student account/)).toBeInTheDocument()
  })
  it('keeps students out of admin pages', async () => {
    setToken('t')
    mockFetch((u) => (u.pathname === '/api/me' ? { body: user('student') } : empty))
    renderAt('/admin/users')
    expect(await screen.findByText('You do not have access to this')).toBeInTheDocument()
  })
  it('lets a reviewer in to admin but denies admin-only tabs', async () => {
    setToken('t')
    mockFetch((u) => {
      if (u.pathname === '/api/me') return { body: user('reviewer') }
      return { body: { counts: {}, feedback: [], evidence: [], reports: [], ownership_requests: [], duplicates: [], events: 0, claims: { total: 0, by_status: {}, outcome_established: { numerator: 0, denominator: 0, pct: null } }, gaps: { total: 0, closed: { numerator: 0, denominator: 0, pct: null } }, feedback_by_status: {}, disputes_by_status: {} } }
    })
    renderAt('/admin/users')
    expect(await screen.findByText('You do not have access to this')).toBeInTheDocument()
    expect(screen.getByText(/admin accounts/)).toBeInTheDocument()
  })
  it('lets an organizer open the organizer workspace', async () => {
    setToken('t')
    mockFetch((u) => (u.pathname === '/api/me' ? { body: user('organizer') } : empty))
    renderAt('/organizer')
    expect(await screen.findByRole('heading', { name: 'Organizer workspace' })).toBeInTheDocument()
  })
  it('reflects a server 403 on an API call as a permission-denied state', async () => {
    setToken('t')
    mockFetch((u) => {
      if (u.pathname === '/api/me') return { body: user('reviewer') }
      return { status: 403, body: { error: { code: 'role_forbidden', message: 'This action requires one of the roles: admin.', details: [], request_id: 'r1' } } }
    })
    renderAt('/admin/sources')
    await waitFor(() => expect(screen.getAllByText('You do not have access to this').length).toBeGreaterThan(0))
    expect(screen.getAllByText(/requires one of the roles: admin/).length).toBeGreaterThan(0)
  })
})
