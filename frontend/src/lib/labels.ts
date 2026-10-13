import type { AccessState, ClaimStatus, EvidenceKind, OriginType } from '../api/types'

export type Tone = 'neutral' | 'info' | 'good' | 'warn' | 'bad' | 'violet' | 'unknown'

export const CLAIM_STATUS: Record<ClaimStatus, { label: string; tone: Tone; help: string }> = {
  advertised: { label: 'Advertised', tone: 'neutral', help: 'Stated by the organizer. Nothing has been checked yet.' },
  needs_clarification: { label: 'Needs clarification', tone: 'warn', help: 'A reviewer asked the organizer to clarify this promise.' },
  evidence_submitted: { label: 'Evidence submitted', tone: 'info', help: 'Evidence is attached and waiting for review.' },
  corroborated: { label: 'Corroborated', tone: 'good', help: 'Accepted independent or public evidence supports this promise.' },
  fulfilled: { label: 'Fulfilled', tone: 'good', help: 'The event ended and the promise was shown to be delivered.' },
  partially_fulfilled: { label: 'Partially fulfilled', tone: 'warn', help: 'Only part of the promise was shown to be delivered.' },
  disputed: { label: 'Disputed', tone: 'violet', help: 'The organizer disputes how this promise was recorded. A reviewer will decide.' },
  unverified: { label: 'Unverified', tone: 'unknown', help: 'No qualifying evidence was found. This is not a finding that the promise was broken.' },
  unable_to_determine: { label: 'Unable to determine', tone: 'unknown', help: 'A reviewer could not reach a conclusion with the evidence available.' },
}
export function claimStatusLabel(s: string): string {
  return (CLAIM_STATUS as Record<string, { label: string }>)[s]?.label ?? titleCase(s)
}

export const EVIDENCE_KIND: Record<EvidenceKind, { label: string; tone: Tone; help: string }> = {
  organizer_provided: { label: 'Organizer-provided', tone: 'neutral', help: 'Supplied by the organizer. Alone, it cannot corroborate a promise.' },
  public_source: { label: 'Public source', tone: 'info', help: 'A publicly available page or record.' },
  participant_report: { label: 'Participant report', tone: 'violet', help: 'Reported by someone who declared they took part. Not independently verified.' },
  independent_review: { label: 'Independently reviewed', tone: 'good', help: 'Checked by a reviewer with no tie to the organizer.' },
}

export const ACCESS_STATE: Record<AccessState, { label: string; tone: Tone; help: string }> = {
  documented: { label: 'Documented', tone: 'good', help: 'The organizer or listing states this is provided.' },
  not_documented: { label: 'Not documented', tone: 'unknown', help: 'Nothing is stated. This is unknown, not unavailable.' },
  confirmed_unavailable: { label: 'Confirmed unavailable', tone: 'bad', help: 'The listing or organizer states this is not available.' },
  conflicting: { label: 'Conflicting information', tone: 'warn', help: 'Sources disagree. Ask the organizer before relying on it.' },
  requires_confirmation: { label: 'Requires confirmation', tone: 'info', help: 'The organizer says to confirm this directly with them.' },
}

export const ORIGIN: Record<OriginType, { label: string; tone: Tone }> = {
  indexed: { label: 'Indexed', tone: 'info' },
  organizer_submitted: { label: 'Organizer-submitted', tone: 'good' },
  user_submitted: { label: 'User-submitted', tone: 'violet' },
}

export const FEEDBACK_RESPONSE: Record<string, string> = {
  delivered: 'Delivered', partially_delivered: 'Partially delivered', not_delivered: 'Not delivered', not_applicable: 'Not applicable', unsure: 'Unsure',
}

export const CATEGORY_LABEL: Record<string, string> = {
  prize: 'Prize', certificate: 'Certificate', mentorship: 'Mentorship', career_opportunity: 'Career opportunity', training_workshop: 'Training or workshop',
  recordings_materials: 'Recordings or materials', results_timeline: 'Results timeline', networking: 'Networking', perks_swag: 'Perks and swag',
  travel_accommodation: 'Travel or accommodation', food: 'Food', learning_outcome: 'Learning outcome', fee_cost: 'Fee or cost', refund_policy: 'Refund policy',
  scholarship_discount: 'Scholarship or discount', accessibility: 'Accessibility', other: 'Other',
}

export const CLAIM_TYPE_LABEL: Record<string, string> = {
  specific: 'Specific', vague: 'Vague', conditional: 'Conditional', informational: 'Informational',
}

export const SEVERITY_TONE: Record<string, Tone> = { high: 'bad', medium: 'warn', low: 'neutral' }

export function titleCase(s: string): string {
  const t = s.replace(/_/g, ' ')
  return t.charAt(0).toUpperCase() + t.slice(1)
}
export function categoryLabel(c: string): string { return CATEGORY_LABEL[c] ?? titleCase(c) }
