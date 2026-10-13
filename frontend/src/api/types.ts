export type Role = 'student' | 'organizer' | 'reviewer' | 'admin'
export interface Org { id: string; name: string; website: string | null; members?: string[] }
export interface User {
  id: string; email: string; display_name: string; role: Role; created_at: string | null
  organizations: Org[]; has_profile: boolean
}
export interface TokenResponse { access_token: string; token_type: string; user: User }

export interface Fee { status: 'free' | 'paid' | 'unknown'; label: string; amount: number | null; currency: string | null; uncertain: boolean }
export interface Fit {
  score: number | null; label: string; eligible: boolean
  hard_violations: { key: string; message: string }[]
  coverage: number; why_match: string[]; why_skip: string[]
  unknowns?: { key: string; message: string }[]
  tradeoffs?: string[]
  components?: FitComponent[]
  weights?: Record<string, number>
  note?: string | null
}
export interface FitComponent { key: string; label: string; weight: number; score: number | null; known: boolean; reason: string; contribution: number | null }
export type OriginType = 'indexed' | 'organizer_submitted' | 'user_submitted'
export interface EventCard {
  id: string; title: string; organizer: string | null; category: string; format: string
  topics: string[]; start_date: string | null; end_date: string | null
  registration_deadline: string | null; deadline_stated: boolean
  location: string | null; city: string | null; country: string | null
  fee: Fee; lifecycle_status: string; canonical_url: string | null
  origin: { type: OriginType; label: string }
  sources: { key: string; name: string; retrieved_at: string }[]
  freshness: { state: string; message: string; last_retrieved_at: string | null; age_days: number | null }
  completeness: { score: number; filled: number; total: number }
  missing_information: string[]; matched_because: string[]
  claims_count: number; verification_state: string; saved: boolean; fit: Fit | null
}
export interface IndexStatus {
  events_indexed: number; connectors: number; connectors_active: number
  connectors_failing: { key: string; name: string; status: string; detail: string | null }[]
  last_successful_sync_at: string | null; scope: string; state: string
}
export interface SearchResponse {
  items: EventCard[]; total: number; page: number; page_size: number
  interpretation: { understood: string[]; keywords: string[]; applied: Record<string, unknown> }
  notes: string[]; broadened: boolean; state: 'ok' | 'empty_result' | 'unavailable'
  index: IndexStatus; personalized: boolean
}
export interface FacetValue { value: string; count: number; label?: string }
export interface Facets {
  categories: FacetValue[]; formats: FacetValue[]; countries: FacetValue[]; cities: FacetValue[]
  topics: FacetValue[]; sources: FacetValue[]; origins: FacetValue[]; fee: FacetValue[]
}

export type ClaimStatus = 'advertised' | 'needs_clarification' | 'evidence_submitted' | 'corroborated' | 'fulfilled'
  | 'partially_fulfilled' | 'disputed' | 'unverified' | 'unable_to_determine'
export interface Claim {
  id: string; original_text: string; normalized_text: string; category: string; claim_type: string
  responsible_party: string | null; conditions: string[]; numeric_values: { kind: string; value: number; currency?: string; text: string }[]
  missing_details: string[]; verification_questions: string[]; evidence_url: string | null; evidence_excerpt: string | null
  extraction_method: string; extraction_confidence: number | null; status: ClaimStatus; status_updated_at: string
  last_checked_at: string | null; evidence_counts: Record<string, number>; provenance: string
}
export interface Evidence {
  id: string; claim_id: string | null; kind: EvidenceKind; kind_label: string; url: string | null; excerpt: string | null
  file_name: string | null; mime_type: string | null; file_size: number | null; has_file: boolean; claim_specific: boolean
  submitted_at: string; coi_declared: boolean; coi_statement: string | null; review_status: 'pending' | 'accepted' | 'rejected'
  reviewed_at: string | null; review_note: string | null
}
export type EvidenceKind = 'organizer_provided' | 'public_source' | 'participant_report' | 'independent_review'
export interface Transition { to: ClaimStatus; roles: string[]; evidence_requirement: string; requires_event_ended: boolean; permitted_for_you: boolean }
export interface ClaimFull extends Claim {
  event_id: string; event_title: string | null; is_active: boolean
  history: { from_status: string | null; to_status: string; actor_role: string | null; reason: string | null; review_outcome: string | null; at: string }[]
  evidence: Evidence[]
  organizer_responses: { id: string; body: string; created_at: string }[]
  disputes: { id: string; kind: string; status: string; description: string; created_at: string; resolution_note: string | null }[]
  transitions: Transition[]; status_note: string
}
export interface Gap {
  id?: string; rule_id: string; gap: string; source_text: string | null; why_it_matters: string
  severity: 'high' | 'medium' | 'low'; severity_rule: string; student_question: string; organizer_fix: string
  scope_note: string | null; status?: string; detected_at?: string; resolution_note?: string | null
}
export type AccessState = 'documented' | 'not_documented' | 'confirmed_unavailable' | 'conflicting' | 'requires_confirmation'
export interface AccessItem {
  key: string; label: string; state: AccessState; detail: string | null; evidence_excerpt: string | null
  evidence_url: string | null; origin: string | null; updated_at: string | null
  student_question: string | null; organizer_fix: string | null
}
export interface AccessPanel {
  items: AccessItem[]; documented_count: number; answered_count: number; total_count: number
  completeness_note: string; student_questions: string[]
  organizer_checklist: { item: string; state: string; suggested_fix: string | null }[]
}
export interface Assertion { value: unknown; origin: string; source_key: string | null; source_name: string | null; source_url: string | null; retrieved_at: string }
export interface Version { version_no: number; changed_at: string; change_source: string; is_material: boolean; summary: string | null; diff: Record<string, unknown> }
export interface SourceRecord { key: string; name: string; source_status: string; retrieved_at: string; source_url: string | null; event_url: string | null; attribution: string | null; missing_since: string | null }
export interface EventDetail extends EventCard {
  description: string | null; eligibility: string | null; prerequisites: string | null; other_costs: string | null
  prize_details: string | null; schedule_text: string | null; judging_criteria: string | null; refund_policy: string | null
  contact_info: string | null; accommodation_info: string | null; time_commitment: string | null
  team_size: { min: number | null; max: number | null }
  allows_cross_college_teams: boolean | null; offers_certificate: boolean | null; offers_mentorship: boolean | null
  registration_url: string | null; organizer_url: string | null; extras: Record<string, unknown>
  first_discovered_at: string; owner_org_id: string | null
  source_records: SourceRecord[]
  provenance: { fields: Record<string, { label: string; assertions: Assertion[] }>; conflicts: { field: string; label: string; values: Assertion[] }[] }
  claims: Claim[]; gaps: Gap[]; accessibility: AccessPanel
  completeness: { score: number; filled: number; total: number; missing: { key: string; label: string }[]; note: string }
  evidence_strength: { level: string; rule: string; sources: number; claims_total: number; claims_corroborated_or_outcome: number; claims_with_evidence_pending: number; accepted_independent_evidence: number; note: string }
  versions: Version[]
  possible_duplicates: { id: string; other_event_id: string; similarity: number; reasons: unknown }[]
  analysis_pending: boolean
  permissions: { can_manage: boolean; can_review: boolean; can_submit_feedback: boolean }
  is_published: boolean
  saved_info?: { saved_at: string; note: string | null; last_seen_version: number | null } | null
}

export interface CompareResponse {
  events: { id: string; title: string; organizer: string | null; canonical_url: string | null; fit: Fit | null; origin: { type: OriginType; label: string }; category: string }[]
  rows: { key: string; label: string; values: (string | null)[]; differs: boolean }[]
  highlights: string[]; note: string
}

export interface AnalysisResult {
  claims: (Omit<Claim, 'id' | 'status_updated_at' | 'last_checked_at' | 'evidence_counts' | 'evidence_url'> & { claim_id?: string })[]
  gaps: (Gap & { provenance: string })[]
  accessibility_detected: { item_key: string; state: AccessState; excerpt: string; provenance: string }[]
  summary: { claims: number; vague_claims: number; gaps: number; high_severity_gaps: number }
  notes: string[]; caveat: string; run_id: string
  analysis: { provider: string; model: string | null; used_fallback: boolean; llm_error: string | null; injection_flags: { type: string; excerpt: string }[]; input_type: string }
  retrieval?: { requested_url: string; final_url: string; canonical_url: string; retrieved_at: string; content_type: string; title: string | null }
  document?: { file_name: string | null; method: string; mime: string; sha256: string; characters: number }
}

export interface Profile {
  education_level: string | null; year_of_study: number | null; institution: string | null; interests: string[]
  skill_level: string | null; learning_goals: string | null; career_goals: string | null
  available_from: string | null; available_to: string | null; max_budget_inr: number | null
  preferred_formats: string[]; require_format: boolean; home_city: string | null; max_travel_km: number | null
  accessibility_needs: string[]; preferred_duration_days_max: number | null; team_preference: string | null; updated_at?: string | null
}
export interface RecItem extends EventCard {
  rank: number; why_match: string[]; why_skip: string[]; tradeoffs: string[]; warnings: string[]
  alternatives: { id: string; title: string; score: number | null; why: string }[]
  completeness_detail: { filled: number; total: number }
}
export interface Recommendations {
  needs_profile: boolean; items: RecItem[]; considered?: number; eligible?: number; not_rated?: number
  excluded: { count: number; reasons: { key: string; label: string; count: number }[]; examples: { id: string; title: string; why: string[] }[] }
  weights?: Record<string, number>; method?: string; message?: string
}
export interface SavedItem extends EventCard {
  note: string | null; saved_at: string; material_change: boolean
  changes_since_saved: { version_no: number; changed_at: string; summary: string | null; is_material: boolean; change_source: string }[]
  days_left?: number
}
export interface Participation { event_id: string; title: string; start_date: string | null; end_date: string | null; level: string; event_ended: boolean; feedback_items_submitted: number }
export interface Dashboard {
  has_profile: boolean; recommendations: RecItem[]; recommendation_summary: { considered: number; excluded: number }
  saved_count: number; upcoming_deadlines: SavedItem[]; changed_saved: SavedItem[]; pending_feedback: Participation[]; participations: Participation[]
}
export interface FeedbackForm {
  event: { id: string; title: string; ended: boolean }; participation: boolean; can_submit: boolean
  claims: { id: string; text: string; category: string; answered: boolean }[]
}
export interface OutcomeClaim {
  claim_id: string; text: string; category: string; status: ClaimStatus; responses: Record<string, number>; responses_total: number
  evidence: Record<string, number>; independent_evidence_accepted: number; verdict: string; summary: string
}
export interface Outcomes {
  claims: OutcomeClaim[]; status_counts: Record<string, number>; participants_declared: number; participants_responded: number
  response_rate: Ratio; min_responses_required: number; caveat: string
  comments: { id: string; claim: string; response: string; comment: string; participation_level: string; created_at: string; organizer_responses: { body: string; created_at: string }[] }[]
}
export interface Ratio { numerator: number; denominator: number; pct: number | null }

export interface Dispute {
  id: string; event_id: string; claim_id: string | null; kind: string; description: string; status: string
  prior_claim_status: string | null; created_at: string; resolution_note: string | null; resolved_at: string | null; event_title?: string | null
}

// organizer
export interface OrgEventRow extends EventCard { is_published: boolean; open_gaps: number; high_gaps: number; pending_feedback: number; open_disputes: number }
export interface AuditIssue {
  id: string; rule_id?: string; gap: string; severity: string; severity_rule?: string; why_it_matters: string
  student_question?: string; organizer_fix?: string; source_text?: string | null; status: string; scope_note?: string | null
  impact?: number; urgency?: number; urgency_reason?: string; priority: number; resolution_note?: string | null; next_action: string
  event_id?: string; event_title?: string; type?: string
}
export interface PublicationAudit {
  event_id: string; is_published: boolean
  readiness: { state: 'ready' | 'needs_attention' | 'blocked'; blocking: string[]; high_severity_open: number; summary: string }
  completeness: { score: number; filled: number; total: number; missing: { key: string; label: string }[]; note: string }
  issues: AuditIssue[]; closed_issues: AuditIssue[]
  vague_claims: { claim_id: string; text: string; missing_details: string[]; questions: string[]; suggestion: string }[]
  accessibility: { documented: number; total: number; checklist: { item: string; state: string; suggested_fix: string | null }[]; note: string }
  prioritisation: string; next_actions: { label: string; action: string; priority: number }[]
}
export interface OrgFeedbackItem {
  id: string; claim_id: string; claim: string; response: string; comment: string | null; status: string
  participation_level: string; created_at: string; organizer_responses: { body: string; created_at: string }[]
}
export interface EventAnalytics {
  event_id: string
  claims: { total: number; by_status: Record<string, number>; outcome_established: Ratio; fulfilled: number; partially_fulfilled: number; disputed: number; unresolved: number; note: string }
  completeness: { before: { filled: number; total: number } | null; after: { filled: number; total: number } | null; versions: number; organizer_corrections: number; change: number | null; note: string }
  accessibility: { documented: Ratio; answered: Ratio; note: string }
  feedback: { participants_declared: number; participants_responded: number; response_rate: Ratio; responses_published: number; responses_pending_moderation: number }
  issues: { gaps_total: number; gaps_open: number; gap_resolution_rate: Ratio; gap_median_hours_to_resolve: number | null; gap_resolved_by_people: number; disputes_total: number; disputes_closed: Ratio; dispute_median_hours_to_resolve: number | null }
  learning_outcomes: string
}
export interface OwnershipRequest { id: string; event_id: string; event_title: string; status: string; created_at: string; decision_note: string | null }

// admin
export interface SourceInfo {
  key: string; name: string; kind: string; homepage: string | null; status: string; status_detail: string | null; enabled: boolean
  access_method: string | null; limitations: string | null; rate_limit_note: string | null; auth_requirement: string | null
  attribution: string | null; terms_url: string | null; license_note: string | null; priority: number
  connector_implemented: boolean; events_linked: number; last_attempt_at: string | null; last_success_at: string | null
  last_error: string | null; consecutive_failures: number
  last_run: { status: string; fetched: number; created: number; updated: number; unchanged: number; started_at: string; errors: unknown[] } | null
  config?: { ics_feed_urls: string[] | null }
}
export interface SyncRun { id: string; source: string; source_name: string; trigger: string; status: string; started_at: string; finished_at: string | null; fetched: number; created: number; updated: number; unchanged: number; skipped: number; missing: number; errors: unknown[] }
export interface Moderation {
  counts: Record<string, number>
  feedback: { id: string; event_id: string; event_title: string; claim: string; response: string; comment: string | null; participation_level: string; created_at: string; has_evidence: boolean }[]
  evidence: { id: string; event_id: string; event_title: string; claim_id: string | null; kind: EvidenceKind; url: string | null; excerpt: string | null; has_file: boolean; file_name: string | null; submitted_at: string; coi_declared: boolean }[]
  reports: { id: string; target_type: string; target_id: string; reason: string; created_at: string }[]
  ownership_requests: { id: string; event_id: string; event_title: string; organization: string; justification: string; proof_url: string | null; created_at: string }[]
  duplicates: { id: string; a: { id: string; title: string }; b: { id: string; title: string }; similarity: number; reasons: unknown }[]
}
export interface AdminUser { id: string; email: string; display_name: string; role: Role; is_active: boolean; created_at: string; last_login_at: string | null }
export interface Paged<T> { items: T[]; total: number; page: number; page_size: number }
export interface AuditLog { id: string; at: string; actor_id: string | null; actor_role: string | null; action: string; target_type: string; target_id: string | null; details: unknown }
export interface Config {
  effective: { stale_after_days: number; participant_threshold: number; unverified_grace_days: number; min_outcome_responses: number; scoring_weights: Record<string, number> }
  defaults: Config['effective']
  environment: { env: string; scheduler_enabled: boolean; sync_interval_hours: number; max_upload_mb: number; llm_provider_configured: boolean }
  weight_labels: Record<string, string>
}
export interface PlatformAnalytics {
  events: number; claims: { total: number; by_status: Record<string, number>; outcome_established: Ratio }
  gaps: { total: number; closed: Ratio }; feedback_by_status: Record<string, number>; disputes_by_status: Record<string, number>
}
