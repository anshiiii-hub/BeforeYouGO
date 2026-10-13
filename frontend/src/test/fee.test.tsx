import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it } from 'vitest'
import { EventCardView } from '../components/EventCard'
import { FeeBadge } from '../components/ui'
import { feeView } from '../lib/format'
import { baseCard, mockFetch } from './helpers'
import { AuthProvider } from '../auth/AuthContext'
import type { EventCard } from '../api/types'

describe('fee uncertainty', () => {
  beforeEach(() => { mockFetch(() => ({ body: {} })) })
  it('never treats an unstated fee as free', () => {
    const v = feeView({ status: 'unknown', label: 'x', amount: null, currency: null, uncertain: true })
    expect(v.text).toBe('Fee not stated')
    expect(v.text.toLowerCase()).not.toContain('free')
    expect(v.uncertain).toBe(true)
  })
  it('shows free only when the source states it', () => {
    expect(feeView({ status: 'free', label: 'Free (stated by source)', amount: null, currency: null, uncertain: false }).text).toBe('Free')
  })
  it('labels a paid event with no amount as unknown amount', () => {
    const v = feeView({ status: 'paid', label: 'Paid (amount not stated)', amount: null, currency: null, uncertain: true })
    expect(v.text).toBe('Paid, amount not stated')
    expect(v.uncertain).toBe(true)
  })
  it('renders the uncertainty label in the badge', () => {
    render(<FeeBadge detail fee={{ status: 'unknown', label: '', amount: null, currency: null, uncertain: true }} />)
    expect(screen.getByTestId('fee')).toHaveTextContent('Fee not stated')
    expect(screen.getByTestId('fee')).toHaveTextContent(/not the same as free/i)
  })
  it('renders a result card with unknown values as unknown, with origin, source and missing info', () => {
    render(<MemoryRouter><AuthProvider><EventCardView e={baseCard() as unknown as EventCard} /></AuthProvider></MemoryRouter>)
    expect(screen.getByText('Fee not stated')).toBeInTheDocument()
    expect(screen.queryByText(/^Free$/)).not.toBeInTheDocument()
    expect(screen.getByText('Organizer not stated')).toBeInTheDocument()
    expect(screen.getByText('No deadline stated')).toBeInTheDocument()
    expect(screen.getByText('Indexed')).toBeInTheDocument()
    expect(screen.getByText(/Registration deadline, Fee stated/)).toBeInTheDocument()
    expect(screen.getByText(/Source A/)).toBeInTheDocument()
    expect(screen.getByText(/4 of 13 details stated/)).toBeInTheDocument()
  })
  it('renders a stated amount', () => {
    render(<MemoryRouter><AuthProvider><EventCardView e={baseCard({ fee: { status: 'paid', label: 'From ₹200', amount: 200, currency: 'INR', uncertain: false } }) as unknown as EventCard} /></AuthProvider></MemoryRouter>)
    expect(screen.getByText('From ₹200')).toBeInTheDocument()
    expect(screen.queryByText('unconfirmed')).not.toBeInTheDocument()
  })
})
