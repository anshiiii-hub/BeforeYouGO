import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { AccessStateBadge, ClaimStatusBadge, EvidenceKindBadge } from '../components/ui'
import { ClaimSummary } from '../components/ClaimPanel'
import { ProviderBanner } from '../pages/Analyzer'
import { CompareCell } from '../pages/Compare'
import { claimStatusLabel, CLAIM_STATUS } from '../lib/labels'
import type { Claim } from '../api/types'

describe('claim lifecycle labels', () => {
  it('has a human label for every lifecycle status', () => {
    const all = ['advertised', 'needs_clarification', 'evidence_submitted', 'corroborated', 'fulfilled', 'partially_fulfilled', 'disputed', 'unverified', 'unable_to_determine']
    expect(Object.keys(CLAIM_STATUS).sort()).toEqual([...all].sort())
    expect(claimStatusLabel('partially_fulfilled')).toBe('Partially fulfilled')
    expect(claimStatusLabel('something_new')).toBe('Something new')
  })
  it('renders status badges with explanatory titles', () => {
    render(<><ClaimStatusBadge status="unverified" /><ClaimStatusBadge status="corroborated" /></>)
    expect(screen.getByText('Unverified')).toHaveAttribute('title', expect.stringMatching(/not a finding that the promise was broken/))
    expect(screen.getByText('Corroborated')).toBeInTheDocument()
  })
  it('distinguishes evidence kinds', () => {
    render(<><EvidenceKindBadge kind="organizer_provided" /><EvidenceKindBadge kind="public_source" /><EvidenceKindBadge kind="participant_report" /><EvidenceKindBadge kind="independent_review" /></>)
    for (const l of ['Organizer-provided', 'Public source', 'Participant report', 'Independently reviewed']) expect(screen.getByText(l)).toBeInTheDocument()
  })
  it('shows all five accessibility states, with not documented described as unknown', () => {
    render(<>{['documented', 'not_documented', 'confirmed_unavailable', 'conflicting', 'requires_confirmation'].map((s) => <AccessStateBadge key={s} state={s} />)}</>)
    expect(screen.getByText('Not documented')).toHaveAttribute('title', expect.stringMatching(/unknown, not unavailable/))
    expect(screen.getAllByText(/./)).toHaveLength(5)
  })
  it('quotes the exact original claim text with specificity', () => {
    const c = { id: '1', original_text: 'Every participant gets a certificate.', normalized_text: 'n', category: 'certificate', claim_type: 'vague', responsible_party: null, conditions: [], numeric_values: [],
      missing_details: ['Who qualifies'], verification_questions: ['Who receives it?'], evidence_url: null, evidence_excerpt: null, extraction_method: 'deterministic', extraction_confidence: 0.6,
      status: 'advertised', status_updated_at: '', last_checked_at: null, evidence_counts: {}, provenance: 'deterministic_rule' } as Claim
    render(<ClaimSummary c={c} />)
    expect(screen.getByText(/“Every participant gets a certificate\.”/)).toBeInTheDocument()
    expect(screen.getByText('Vague')).toBeInTheDocument()
    expect(screen.getByText('Read by fixed rules')).toBeInTheDocument()
  })
})

describe('analyzer provenance banner', () => {
  const base = { model: null, injection_flags: [], input_type: 'text' }
  it('says rules, not AI, when no provider is configured', () => {
    render(<ProviderBanner a={{ ...base, provider: 'deterministic', used_fallback: true, llm_error: null }} />)
    expect(screen.getByTestId('provider-banner')).toHaveTextContent(/fixed rules, not AI/)
  })
  it('says fallback when the AI provider failed', () => {
    render(<ProviderBanner a={{ ...base, provider: 'deterministic', used_fallback: true, llm_error: 'timeout' }} />)
    expect(screen.getByTestId('provider-banner')).toHaveTextContent(/fallback/)
    expect(screen.getByTestId('provider-banner')).toHaveTextContent(/timeout/)
  })
  it('names the provider when an AI model did the reading', () => {
    render(<ProviderBanner a={{ ...base, provider: 'anthropic', model: 'claude-x', used_fallback: false, llm_error: null }} />)
    expect(screen.getByTestId('provider-banner')).toHaveTextContent(/Read by an AI model/)
    expect(screen.getByTestId('provider-banner')).toHaveTextContent(/anthropic, claude-x/)
  })
})

describe('compare cells', () => {
  it('renders Not stated as unknown rather than a value', () => {
    const { container } = render(<><CompareCell v="Not stated" /><CompareCell v={null} /><CompareCell v="₹200" /></>)
    expect(container.querySelectorAll('.unknown')).toHaveLength(2)
    expect(screen.getByText('₹200')).not.toHaveClass('unknown')
  })
})
