import { useMemo, useState } from 'react'
import { Link, useParams, useLocation } from 'react-router-dom'
import { api } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import type { AccessItem, EventDetail, Gap, Outcomes } from '../api/types'
import { ClaimPanel, ReportForm } from '../components/ClaimPanel'
import { CompareButton, SaveButton } from '../components/EventActions'
import { DataState, Empty, Notice } from '../components/States'
import { AccessStateBadge, Badge, Check, ExternalLink, FeeBadge, FormStatus, Ledger, Panel, SeverityBadge, Select, TextField, KV, Unknown, Val, useSubmit, ClaimStatusBadge } from '../components/ui'
import { fmtDate, fmtDateRange, fmtDateTime, fmtDeadline, fmtPct, triState as triRaw } from '../lib/format'
import { ACCESS_STATE, categoryLabel, FEEDBACK_RESPONSE, ORIGIN, titleCase } from '../lib/labels'
import { useAsync, useTitle } from '../lib/useAsync'

const triState = (v: boolean | null | undefined, yes: string, no: string) => (v === null || v === undefined ? <Unknown /> : triRaw(v, yes, no))

const FIELD_ORIGIN: Record<string, { label: string; tone: 'info' | 'good' | 'violet' | 'warn' | 'neutral' }> = {
  source: { label: 'Public source', tone: 'info' }, derived: { label: 'Derived from a source field', tone: 'neutral' },
  ai_extracted: { label: 'AI-extracted', tone: 'violet' }, manual: { label: 'Corrected by a reviewer', tone: 'good' }, organizer: { label: 'Organizer-provided', tone: 'good' },
}

export function EventDetailPage() {
  const { id = '' } = useParams()
  const state = useAsync((s) => api.get<EventDetail>(`/events/${id}`, undefined, s), [id])
  useTitle(state.data?.title ?? 'Event')
  return (
    <div className="wrap page">
      <DataState state={state} loadingLabel="Loading event evidence">
        {(e) => <Detail e={e} reload={state.reload} />}
      </DataState>
    </div>
  )
}

function Detail({ e, reload }: { e: EventDetail; reload: () => void }) {
  const { user } = useAuth()
  const loc = useLocation()
  const origin = ORIGIN[e.origin.type]
  const perm = { manage: e.permissions.can_manage, review: e.permissions.can_review }
  const started = e.start_date ? e.start_date <= new Date().toISOString().slice(0, 10) : false
  return (
    <>
      <div className="detail-head">
        <div className="event-card-badges">
          <Badge tone="violet">{categoryLabel(e.category)}</Badge>
          <Badge>{e.format === 'unknown' ? 'Format not stated' : titleCase(e.format)}</Badge>
          <Badge tone={origin?.tone}>{origin?.label ?? e.origin.label}</Badge>
          <Badge tone="info" title={e.evidence_strength.rule}>Evidence: {titleCase(e.evidence_strength.level)}</Badge>
          {e.lifecycle_status !== 'scheduled' && <Badge tone={e.lifecycle_status === 'unknown' ? 'unknown' : 'bad'}>{titleCase(e.lifecycle_status)}</Badge>}
          {!e.is_published && <Badge tone="warn">Unpublished draft</Badge>}
        </div>
        <h1 style={{ marginBottom: 0 }}>{e.title}</h1>
        <p className="muted" style={{ margin: 0 }}>{e.organizer ? `By ${e.organizer}` : <Unknown>Organizer not stated</Unknown>} {'·'} {e.origin.label}</p>
        <div className="btn-row" style={{ marginTop: 8 }}>
          <SaveButton eventId={e.id} saved={e.saved || !!e.saved_info} />
          <CompareButton id={e.id} title={e.title} />
          {e.canonical_url && /^https?:\/\//i.test(e.canonical_url) && (
            <a className="btn btn-primary" href={e.canonical_url} target="_blank" rel="noopener noreferrer">Open original source<span className="sr-only"> (opens in a new tab)</span></a>
          )}
          {e.permissions.can_manage && <Link className="btn" to={`/organizer/events/${e.id}`}>Manage this event</Link>}
        </div>
        {!user && <p className="small muted" style={{ margin: 0 }}><Link to="/login" state={{ next: loc.pathname }}>Sign in</Link> to save, analyze, report or give feedback.</p>}
      </div>
      {!e.is_published && <Notice tone="warn">This listing is not public. Only its organizer and reviewers can see it.</Notice>}
      {e.lifecycle_status === 'removed_from_source' && <Notice tone="warn">The source no longer lists this event. That is not proof it was cancelled.</Notice>}
      {e.freshness.state !== 'fresh' && e.freshness.state !== 'submitted' && <Notice tone="warn">{e.freshness.message}</Notice>}

      <nav className="subnav" aria-label="On this page">
        {[['facts', 'Key facts'], ['fit', 'Fit for you'], ['promises', `Promises (${e.claims.length})`], ['gaps', `Gaps (${e.gaps.filter((g) => g.status !== 'resolved').length})`], ['ask', 'Ask the organizer'], ['access', 'Accessibility'], ['sources', 'Sources and provenance'], ['history', 'History'], ['outcomes', 'Outcomes'], ['participate', 'Took part?']].map(([h, l]) => <a key={h} href={`#${h}`}>{l}</a>)}
      </nav>

      <Facts e={e} />
      <FitPanel e={e} signedIn={!!user} />
      <Promises e={e} perm={perm} reload={reload} />
      <Gaps gaps={e.gaps} />
      <AskOrganizer e={e} />
      <Accessibility e={e} perm={perm} />
      <Sources e={e} />
      <History e={e} />
      <OutcomesPanel id={e.id} />
      <Participate e={e} started={started} />
      {perm.review && <Lifecycle e={e} reload={reload} />}
      {user?.role === 'organizer' && !e.owner_org_id && <ClaimOwnership e={e} />}
      <ReportForm targetType="event" targetId={e.id} />
    </>
  )
}

function Facts({ e }: { e: EventDetail }) {
  return (
    <Panel id="facts" title="Key facts">
      <KV items={[
        ['Dates', fmtDateRange(e.start_date, e.end_date)],
        ['Registration deadline', e.registration_deadline ? fmtDeadline(e.registration_deadline) : <Unknown>No deadline stated. Do not assume registration stays open.</Unknown>],
        ['Location', <Val v={e.location} />],
        ['Registration fee', <FeeBadge fee={e.fee} detail />],
        ['Other costs', <Val v={e.other_costs} />],
        ['Eligibility', <Val v={e.eligibility} />],
        ['Prerequisites', <Val v={e.prerequisites} />],
        ['Team size', e.team_size.min || e.team_size.max ? `${e.team_size.min ?? '?'}–${e.team_size.max ?? '?'}` : <Unknown />],
        ['Cross-college teams', triState(e.allows_cross_college_teams, 'Allowed', 'Not allowed')],
        ['Certificate', triState(e.offers_certificate, 'Offered', 'Not offered')],
        ['Mentorship', triState(e.offers_mentorship, 'Offered', 'Not offered')],
        ['Prizes', <Val v={e.prize_details} />],
        ['Refund policy', <Val v={e.refund_policy} />],
        ['Time commitment', <Val v={e.time_commitment} />],
        ['Judging criteria', <Val v={e.judging_criteria} />],
        ['Contact', <Val v={e.contact_info} />],
        ['Schedule', <Val v={e.schedule_text} />],
        ['Accommodation', <Val v={e.accommodation_info} />],
        ['Registration link', e.registration_url ? <ExternalLink href={e.registration_url}>{e.registration_url}</ExternalLink> : <Unknown />],
      ]} />
      {e.description ? <><h3 style={{ marginTop: 20 }}>Description</h3><p style={{ whiteSpace: 'pre-wrap' }}>{e.description}</p></> : <p className="unknown" style={{ marginTop: 16 }}>No description is stated in the retrieved sources.</p>}
      <div className="card-meter" style={{ marginTop: 12 }}>
        <Ledger filled={e.completeness.filled} total={e.completeness.total} />
        <span>{e.completeness.filled} of {e.completeness.total} details stated.</span>
      </div>
      <p className="small muted">{e.completeness.note}</p>
      {e.completeness.missing.length > 0 && <p className="small"><strong>Missing:</strong> {e.completeness.missing.map((m) => m.label).join(', ')}</p>}
      <p className="small muted"><strong>Freshness:</strong> {e.freshness.message}</p>
      <p className="small muted"><strong>Evidence strength:</strong> {e.evidence_strength.rule} {e.evidence_strength.note}</p>
    </Panel>
  )
}

function FitPanel({ e, signedIn }: { e: EventDetail; signedIn: boolean }) {
  const fit = e.fit
  return (
    <Panel id="fit" title="Fit for you">
      {!signedIn && <p className="muted">Sign in and set preferences to see why this event does or does not fit you.</p>}
      {signedIn && !fit && <p className="muted">You have not set preferences yet. <Link to="/me/profile">Set preferences</Link> to get an explained fit score.</p>}
      {fit && (
        <>
          <p><strong>{fit.label}</strong>{fit.score !== null && <> {'—'} {fit.score}/100 weighted match using {Math.round(fit.coverage * 100)}% of the factors</>}</p>
          {fit.hard_violations.length > 0 && <Notice tone="bad"><strong>Excluded by your constraints:</strong><ul className="bullets">{fit.hard_violations.map((v) => <li key={v.key}>{v.message}</li>)}</ul></Notice>}
          {fit.why_match.length > 0 && <><h4>Why it matches</h4><ul className="bullets">{fit.why_match.map((w) => <li key={w}>{w}</li>)}</ul></>}
          {fit.why_skip.length > 0 && <><h4>Why you might skip it</h4><ul className="bullets">{fit.why_skip.map((w) => <li key={w}>{w}</li>)}</ul></>}
          {fit.components && <ScoreBreakdown fit={fit} />}
        </>
      )}
    </Panel>
  )
}

export function ScoreBreakdown({ fit }: { fit: NonNullable<EventDetail['fit']> }) {
  if (!fit.components?.length) return null
  return (
    <div>
      <h4>Score breakdown</h4>
      {fit.components.map((c) => (
        <div className="score-row" key={c.key}>
          <span>{c.label} <span className="dim small">({Math.round(c.weight * 100)}% weight)</span></span>
          {c.known ? (
            <div><div className="meter-bar" role="img" aria-label={`${Math.round((c.score ?? 0) * 100)} percent`}><span style={{ width: `${Math.round((c.score ?? 0) * 100)}%` }} /></div><span className="small muted">{c.reason}</span></div>
          ) : <span className="unknown small">Unknown, left out of the score. {c.reason}</span>}
          <span className="small">{c.known && c.contribution !== null ? `+${c.contribution}` : '—'}</span>
        </div>
      ))}
      {fit.note && <p className="small muted">{fit.note}</p>}
    </div>
  )
}

function Promises({ e, perm, reload }: { e: EventDetail; perm: { manage: boolean; review: boolean }; reload: () => void }) {
  const { user } = useAuth()
  const s = useSubmit()
  const analyze = () => s.run(async () => { await api.post(`/events/${e.id}/analyze`); reload() }, 'Analysis complete.')
  return (
    <Panel id="promises" title="Promises and their status">
      <p className="muted">Each promise is quoted exactly as written. Status shows what has been checked, not whether the organizer is honest.</p>
      {e.claims.length === 0 && (
        <Empty title="No promises extracted yet">
          Nobody has run the promise analyzer on this listing. {e.description ? '' : 'The listing also has no description to analyze, so the result may be thin.'}
        </Empty>
      )}
      {e.claims.length === 0 && (
        user ? <div className="btn-row"><button className="btn btn-primary" onClick={analyze} disabled={s.busy}>Analyze this event</button><FormStatus s={s} /></div>
          : <p><Link to="/login" state={{ next: `/events/${e.id}` }}>Sign in</Link> to analyze this event.</p>
      )}
      {e.claims.length > 0 && perm.manage && <div className="btn-row" style={{ marginBottom: 12 }}><button className="btn btn-sm" onClick={analyze} disabled={s.busy}>Re-run analysis</button><FormStatus s={s} /></div>}
      {e.claims.map((c) => <ClaimPanel key={c.id} claim={c} eventId={e.id} perm={perm} onChanged={reload} />)}
    </Panel>
  )
}

export function GapCard({ g }: { g: Gap }) {
  return (
    <div className={`gap gap-${g.severity}`} data-testid="gap">
      <div className="claim-top"><SeverityBadge severity={g.severity} />{g.status && g.status !== 'open' && <Badge tone="good">{titleCase(g.status)}</Badge>}</div>
      <h4>{g.gap}</h4>
      <p className="small">{g.why_it_matters}</p>
      {g.source_text && <div className="quote small">{'“'}{g.source_text}{'”'}</div>}
      <p className="small"><strong>Question to ask:</strong> {g.student_question}</p>
      <p className="small"><strong>Suggested correction:</strong> {g.organizer_fix}</p>
      <details><summary className="small">How this severity was set</summary><p className="small muted">{g.severity_rule}</p>{g.scope_note && <p className="small muted">{g.scope_note}</p>}</details>
      {g.resolution_note && <p className="small muted">Resolution: {g.resolution_note}</p>}
    </div>
  )
}

function Gaps({ gaps }: { gaps: Gap[] }) {
  return (
    <Panel id="gaps" title="Information gaps">
      {gaps.length === 0 ? <p className="muted">No gap findings are recorded. If no analysis has run yet, there is nothing to report here, which is not the same as a complete listing.</p>
        : gaps.map((g) => <GapCard key={g.id ?? g.rule_id} g={g} />)}
    </Panel>
  )
}

function emailFrom(text: string | null): string | null {
  const m = text?.match(/[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}/)
  return m ? m[0] : null
}

function AskOrganizer({ e }: { e: EventDetail }) {
  const all = useMemo(() => {
    const qs = new Set<string>()
    e.gaps.filter((g) => g.status !== 'resolved' && g.status !== 'dismissed').forEach((g) => qs.add(g.student_question))
    e.claims.forEach((c) => c.verification_questions.forEach((q) => qs.add(q)))
    e.accessibility.student_questions.slice(0, 4).forEach((q) => qs.add(q))
    return [...qs]
  }, [e])
  const [picked, setPicked] = useState<string[]>([])
  const [copied, setCopied] = useState<string | null>(null)
  const email = emailFrom(e.contact_info)
  const text = `Hello,\n\nI am considering "${e.title}" and have a few questions before I register:\n\n${picked.map((q, i) => `${i + 1}. ${q}`).join('\n')}\n\nThank you.`
  const copy = async () => {
    try { await navigator.clipboard.writeText(text); setCopied('Copied to clipboard.') } catch { setCopied('Copy failed. Select the text in the box below and copy it manually.') }
  }
  return (
    <Panel id="ask" title="Ask the organizer">
      {all.length === 0 ? <p className="muted">No open questions were found. Run the analysis to generate questions from this listing.</p> : (
        <>
          <p className="muted">Pick the questions you want answered. BeforeYouGo does not contact organizers for you.</p>
          <fieldset><legend>Questions</legend>
            {all.slice(0, 20).map((q) => <Check key={q} label={q} checked={picked.includes(q)} onChange={() => setPicked((p) => p.includes(q) ? p.filter((x) => x !== q) : [...p, q])} />)}
          </fieldset>
          <label className="sr-only" htmlFor="ask-text">Message to the organizer</label>
          <textarea id="ask-text" readOnly rows={6} value={picked.length ? text : 'Select at least one question to draft a message.'} />
          <div className="btn-row" style={{ marginTop: 10 }}>
            <button className="btn btn-sm" disabled={picked.length === 0} onClick={copy}>Copy message</button>
            {email ? <a className="btn btn-sm btn-primary" aria-disabled={picked.length === 0} href={`mailto:${email}?subject=${encodeURIComponent(`Questions about ${e.title}`)}&body=${encodeURIComponent(text)}`}>Email {email}</a>
              : <span className="small muted">No organizer email is stated, so copy the message and send it where the original listing says to.</span>}
          </div>
          <p className="small" aria-live="polite">{copied}</p>
        </>
      )}
    </Panel>
  )
}

function Accessibility({ e, perm }: { e: EventDetail; perm: { manage: boolean; review: boolean } }) {
  const a = e.accessibility
  return (
    <Panel id="access" title="Accessibility information" actions={perm.manage ? <Link className="btn btn-sm" to={`/organizer/events/${e.id}/accessibility`}>Update checklist</Link> : undefined}>
      <p className="muted">{a.completeness_note}</p>
      <details style={{ marginBottom: 12 }}>
        <summary>What the five states mean</summary>
        <ul className="bullets small">{Object.entries(ACCESS_STATE).map(([k, v]) => <li key={k}><strong>{v.label}:</strong> {v.help}</li>)}</ul>
      </details>
      <div className="acc-grid">
        {a.items.map((i: AccessItem) => (
          <div className="acc-item" key={i.key}>
            <h4>{i.label}</h4>
            <AccessStateBadge state={i.state} />
            {i.detail && <p className="small" style={{ marginTop: 6 }}>{i.detail}</p>}
            {i.evidence_excerpt && <div className="quote small">{'“'}{i.evidence_excerpt}{'”'}</div>}
            {i.origin && <p className="small dim">Source: {i.origin === 'organizer' ? 'organizer-provided' : i.origin === 'derived' ? 'read from the listing text' : i.origin}</p>}
            {i.student_question && <p className="small muted">Ask: {i.student_question}</p>}
          </div>
        ))}
      </div>
    </Panel>
  )
}

function Sources({ e }: { e: EventDetail }) {
  const fields = Object.entries(e.provenance.fields)
  return (
    <Panel id="sources" title="Sources and field provenance">
      <h3>Source records</h3>
      {e.source_records.length === 0 ? <p className="muted">This is a submitted record with no connected source. Its content comes from the person who submitted it.</p> : (
        <ul className="plain">
          {e.source_records.map((s) => (
            <li key={s.key}>
              <strong>{s.name}</strong> <Badge tone={s.source_status === 'active' ? 'good' : 'warn'}>{titleCase(s.source_status)}</Badge>
              <div className="small muted">Retrieved {fmtDateTime(s.retrieved_at)}{s.missing_since ? ` · no longer listed since ${fmtDate(s.missing_since)}` : ''}</div>
              <div className="small">
                {s.event_url && <ExternalLink href={s.event_url}>Event page in source</ExternalLink>}{s.event_url && s.source_url ? ' · ' : ''}
                {s.source_url && <ExternalLink href={s.source_url}>Raw source data</ExternalLink>}
              </div>
              {s.attribution && <div className="small dim">{s.attribution}</div>}
            </li>
          ))}
        </ul>
      )}
      {e.provenance.conflicts.length > 0 && (
        <Notice tone="warn"><strong>Sources disagree on:</strong> {e.provenance.conflicts.map((c) => c.label).join(', ')}. Check the original source.</Notice>
      )}
      <h3 style={{ marginTop: 20 }}>Where each field came from</h3>
      <div className="table-wrap">
        <table>
          <thead><tr><th scope="col">Field</th><th scope="col">Value</th><th scope="col">Evidence label</th><th scope="col">Source</th><th scope="col">Retrieved</th></tr></thead>
          <tbody>
            {fields.map(([k, f]) => f.assertions.map((a, i) => (
              <tr key={`${k}-${i}`}>
                <th scope="row">{i === 0 ? f.label : ''}</th>
                <td>{typeof a.value === 'object' ? JSON.stringify(a.value) : String(a.value)}</td>
                <td><Badge tone={FIELD_ORIGIN[a.origin]?.tone ?? 'neutral'}>{FIELD_ORIGIN[a.origin]?.label ?? titleCase(a.origin)}</Badge></td>
                <td>{a.source_url ? <ExternalLink href={a.source_url}>{a.source_name ?? 'Source'}</ExternalLink> : (a.source_name ?? <Unknown />)}</td>
                <td className="small">{fmtDateTime(a.retrieved_at)}</td>
              </tr>
            )))}
          </tbody>
        </table>
      </div>
      {e.possible_duplicates.length > 0 && (
        <><h3 style={{ marginTop: 20 }}>Possible duplicates</h3><ul className="plain">{e.possible_duplicates.map((d) => <li key={d.id}><Link to={`/events/${d.other_event_id}`}>Another listing that may be the same event</Link> <span className="small muted">(similarity {Math.round(d.similarity * 100)}%)</span></li>)}</ul></>
      )}
    </Panel>
  )
}

function History({ e }: { e: EventDetail }) {
  return (
    <Panel id="history" title="Change history">
      {e.versions.length === 0 ? <p className="muted">No versions are recorded.</p> : (
        <ol className="timeline">
          {e.versions.map((v) => (
            <li key={v.version_no}>
              <strong>Version {v.version_no}</strong> {v.is_material && <Badge tone="warn">Material change</Badge>}
              <span className="small dim"> {fmtDateTime(v.changed_at)} {'·'} {v.change_source}</span>
              <div className="small">{v.summary ?? 'No summary.'}</div>
              {Object.keys(v.diff ?? {}).length > 0 && (
                <details><summary className="small">Changed fields</summary>
                  <ul className="bullets small">{Object.entries(v.diff).map(([k, d]) => <li key={k}><strong>{titleCase(k)}:</strong> {renderDiff(d)}</li>)}</ul>
                </details>
              )}
            </li>
          ))}
        </ol>
      )}
    </Panel>
  )
}
function renderDiff(d: unknown): string {
  if (d && typeof d === 'object' && ('old' in d || 'new' in d || 'before' in d || 'after' in d)) {
    const x = d as Record<string, unknown>
    const a = 'old' in x ? x.old : x.before
    const b = 'new' in x ? x.new : x.after
    return `${a === null || a === undefined ? 'not stated' : String(a)} → ${b === null || b === undefined ? 'not stated' : String(b)}`
  }
  return typeof d === 'string' ? d : JSON.stringify(d)
}

function OutcomesPanel({ id }: { id: string }) {
  const state = useAsync((s) => api.get<Outcomes>(`/events/${id}/outcomes`, undefined, s), [id])
  return (
    <Panel id="outcomes" title="Outcomes reported by participants">
      <DataState state={state} loadingLabel="Loading outcomes">
        {(o) => (
          <>
            <p><strong>Response rate:</strong> {fmtPct(o.response_rate)} of declared participants. <span className="muted small">At least {o.min_responses_required} published responses are needed before a promise gets a participant verdict.</span></p>
            {o.claims.length === 0 ? <p className="muted">No promises have been recorded, so there is nothing to report on yet.</p> : (
              <div className="table-wrap"><table>
                <thead><tr><th scope="col">Promise</th><th scope="col">Status</th><th scope="col">Participant responses</th><th scope="col">Summary</th></tr></thead>
                <tbody>{o.claims.map((c) => (
                  <tr key={c.claim_id}>
                    <td>{c.text}</td><td><ClaimStatusBadge status={c.status} /></td>
                    <td>{c.responses_total === 0 ? <Unknown>None published</Unknown> : Object.entries(c.responses).map(([k, v]) => `${FEEDBACK_RESPONSE[k] ?? k}: ${v}`).join(', ') + ` (of ${c.responses_total})`}</td>
                    <td className="small">{c.summary}</td>
                  </tr>
                ))}</tbody>
              </table></div>
            )}
            {o.comments.length > 0 && <><h3 style={{ marginTop: 16 }}>Participant comments</h3><ul className="plain">{o.comments.map((c) => (
              <li key={c.id}><Badge tone="violet">Participant report</Badge> <Badge>{FEEDBACK_RESPONSE[c.response] ?? c.response}</Badge>
                <div className="small dim">On: {'“'}{c.claim}{'”'}</div><div>{c.comment}</div>
                {c.organizer_responses.map((r, i) => <div key={i} className="quote small"><strong>Organizer replied:</strong> {r.body}</div>)}
              </li>))}</ul></>}
            <p className="small muted">{o.caveat}</p>
          </>
        )}
      </DataState>
    </Panel>
  )
}

function Participate({ e, started }: { e: EventDetail; started: boolean }) {
  const { user } = useAuth()
  const [coi, setCoi] = useState(false)
  const s = useSubmit()
  const [done, setDone] = useState(false)
  return (
    <Panel id="participate" title="Did you take part?">
      {!user ? <p><Link to="/login" state={{ next: `/events/${e.id}` }}>Sign in</Link> to declare that you took part and report whether the promises were kept.</p>
        : !e.start_date ? <p className="muted">This event has no stated date, so participation cannot be declared yet.</p>
        : !started ? <p className="muted">You can declare participation once the event has started on {fmtDate(e.start_date)}.</p>
        : (
          <>
            <p className="muted">Declaring participation lets you give feedback on each promise once the event ends. Your name is never shown. Your report counts as a participant report, not independent verification.</p>
            <Check label="I have a conflict of interest (for example I helped organize this event)" checked={coi} onChange={(ev) => setCoi(ev.target.checked)} />
            <div className="btn-row">
              <button className="btn btn-primary" disabled={s.busy} onClick={async () => { const r = await s.run(() => api.post(`/me/participations/${e.id}`, { conflict_of_interest: coi }), 'Participation recorded.'); if (r !== undefined) setDone(true) }}>I took part in this event</button>
              {done && <Link className="btn" to={`/me/feedback/${e.id}`}>Go to feedback</Link>}
            </div>
            <FormStatus s={s} />
          </>
        )}
    </Panel>
  )
}

function Lifecycle({ e, reload }: { e: EventDetail; reload: () => void }) {
  const [status, setStatus] = useState(e.lifecycle_status === 'unknown' ? 'scheduled' : e.lifecycle_status)
  const [reason, setReason] = useState('')
  const s = useSubmit()
  return (
    <Panel title="Reviewer: set event status">
      <form onSubmit={async (ev) => { ev.preventDefault(); const r = await s.run(() => api.post(`/admin/events/${e.id}/lifecycle`, { status, reason }), 'Status updated.'); if (r !== undefined) reload() }}>
        <Select label="Lifecycle status" value={status} onChange={(x) => setStatus(x.target.value)} options={['scheduled', 'postponed', 'cancelled'].map((v) => ({ value: v, label: titleCase(v) }))} />
        <TextField label="Reason (recorded in the audit log)" value={reason} onChange={(x) => setReason(x.target.value)} />
        <button className="btn btn-sm" disabled={s.busy || reason.trim().length < 5}>Save status</button><FormStatus s={s} />
      </form>
    </Panel>
  )
}

function ClaimOwnership({ e }: { e: EventDetail }) {
  const { user } = useAuth()
  const [org, setOrg] = useState(user?.organizations[0]?.id ?? '')
  const [why, setWhy] = useState('')
  const [proof, setProof] = useState('')
  const s = useSubmit()
  if (!user || user.organizations.length === 0) return <Panel title="Is this your event?"><p className="muted">Create an organization first, then you can request ownership. <Link to="/organizer">Go to the organizer workspace</Link>.</p></Panel>
  return (
    <Panel title="Is this your event?">
      <form onSubmit={async (ev) => { ev.preventDefault(); await s.run(() => api.post('/organizer/ownership-requests', { organization_id: org, justification: why, proof_url: proof || null }, { event_id: e.id }), 'Request sent. A reviewer will decide.') }}>
        <Select label="Organization" value={org} onChange={(x) => setOrg(x.target.value)} options={user.organizations.map((o) => ({ value: o.id, label: o.name }))} />
        <TextField label="Why is it yours?" value={why} onChange={(x) => setWhy(x.target.value)} hint="At least 20 characters." />
        <TextField label="Proof link (optional)" type="url" value={proof} onChange={(x) => setProof(x.target.value)} />
        <button className="btn btn-sm" disabled={s.busy || why.trim().length < 20}>Request ownership</button><FormStatus s={s} />
      </form>
    </Panel>
  )
}
