import { useState } from 'react'
import { Link, Route, Routes, useNavigate, useParams } from 'react-router-dom'
import { api, download } from '../../api/client'
import { useAuth } from '../../auth/AuthContext'
import type { AuditIssue, Dispute, EventAnalytics, EventDetail, OrgEventRow, OrgFeedbackItem, OwnershipRequest, PublicationAudit, Org } from '../../api/types'
import { ClaimPanel } from '../../components/ClaimPanel'
import { DataState, Empty, Notice } from '../../components/States'
import { AccessStateBadge, Badge, Check, FormStatus, Ledger, PageHead, Panel, SeverityBadge, Select, Tabs, TextArea, TextField, useSubmit, ClaimStatusBadge } from '../../components/ui'
import { fmtDateTime, fmtPct, fmtRange } from './util'
import { CLAIM_STATUS, FEEDBACK_RESPONSE, categoryLabel, titleCase } from '../../lib/labels'
import { useAsync, useTitle } from '../../lib/useAsync'
import { EMPTY_REF, EventForm, valuesFromEvent } from './EventForm'

export default function OrganizerArea() {
  return (
    <div className="wrap page">
      <Routes>
        <Route index element={<><OrgTabs /><Home /></>} />
        <Route path="issues" element={<><OrgTabs /><IssuesPage /></>} />
        <Route path="disputes" element={<><OrgTabs /><DisputesPage /></>} />
        <Route path="ownership" element={<><OrgTabs /><OwnershipPage /></>} />
        <Route path="events/new" element={<CreateEvent />} />
        <Route path="events/:id/*" element={<ManageEvent />} />
        <Route path="*" element={<Empty title="Page not found" />} />
      </Routes>
    </div>
  )
}
function OrgTabs() {
  return <Tabs items={[{ to: '/organizer', label: 'Events and organizations', end: true }, { to: '/organizer/issues', label: 'Issue tracker' }, { to: '/organizer/disputes', label: 'Disputes' }, { to: '/organizer/ownership', label: 'Ownership requests' }]} />
}

function Home() {
  useTitle('Organizer workspace')
  const { user, refresh } = useAuth()
  const orgs = useAsync((s) => api.get<{ items: Org[] }>('/organizer/orgs', undefined, s), [])
  const events = useAsync((s) => api.get<{ items: OrgEventRow[]; total: number }>('/organizer/events', undefined, s), [])
  const [name, setName] = useState(''); const [site, setSite] = useState('')
  const s = useSubmit()
  return (
    <>
      <PageHead title="Organizer workspace" lead="Create listings, close the gaps students ask about and keep your promises on record."
        actions={orgs.data && orgs.data.items.length > 0 ? <Link className="btn btn-primary" to="/organizer/events/new">Create an event</Link> : undefined} />
      <Panel title="Your organizations">
        <DataState state={orgs} loadingLabel="Loading organizations" isEmpty={(d) => d.items.length === 0} empty={<p className="muted">You do not belong to an organization yet. Create one to publish events.</p>}>
          {(d) => <ul className="plain">{d.items.map((o) => <li key={o.id}><strong>{o.name}</strong> {o.website && <span className="small muted">{o.website}</span>}</li>)}</ul>}
        </DataState>
        {user?.role === 'organizer' || user?.role === 'admin' ? (
          <form onSubmit={async (e) => { e.preventDefault(); const r = await s.run(() => api.post('/organizer/orgs', { name, website: site || null }), 'Organization created.'); if (r !== undefined) { setName(''); setSite(''); orgs.reload(); void refresh() } }}>
            <h3 style={{ marginTop: 16 }}>Create an organization</h3>
            <div className="form-grid">
              <TextField label="Organization name" value={name} onChange={(e) => setName(e.target.value)} required minLength={2} />
              <TextField label="Website (optional)" type="url" value={site} onChange={(e) => setSite(e.target.value)} />
            </div>
            <button className="btn" disabled={s.busy || name.trim().length < 2}>Create organization</button><FormStatus s={s} />
          </form>
        ) : <p className="small muted">Your account is read-only here. Only organizer and administrator accounts can create organizations.</p>}
      </Panel>
      <Panel title="Your events">
        <DataState state={events} loadingLabel="Loading your events" isEmpty={(d) => d.items.length === 0} empty={<Empty title="No events yet">Create an event for one of your organizations, or request ownership of an indexed event from its page.</Empty>}>
          {(d) => (
            <div className="table-wrap"><table>
              <thead><tr><th scope="col">Event</th><th scope="col">Status</th><th scope="col">Open gaps</th><th scope="col">Feedback to moderate</th><th scope="col">Open disputes</th><th scope="col"><span className="sr-only">Actions</span></th></tr></thead>
              <tbody>{d.items.map((e) => (
                <tr key={e.id}><td><Link to={`/organizer/events/${e.id}`}>{e.title}</Link><div className="small muted">{fmtRange(e.start_date, e.end_date)}</div></td>
                  <td><Badge tone={e.is_published ? 'good' : 'warn'}>{e.is_published ? 'Published' : 'Draft'}</Badge></td>
                  <td>{e.open_gaps}{e.high_gaps > 0 && <> <Badge tone="bad">{e.high_gaps} high</Badge></>}</td><td>{e.pending_feedback}</td><td>{e.open_disputes}</td>
                  <td><Link className="btn btn-sm" to={`/organizer/events/${e.id}`}>Manage</Link></td></tr>
              ))}</tbody>
            </table></div>
          )}
        </DataState>
      </Panel>
    </>
  )
}

function CreateEvent() {
  useTitle('Create an event')
  const { user } = useAuth()
  const nav = useNavigate()
  const [org, setOrg] = useState(user?.organizations[0]?.id ?? '')
  const [publish, setPublish] = useState(false)
  const s = useSubmit()
  const [audit, setAudit] = useState<{ id: string; audit: PublicationAudit; is_published: boolean } | null>(null)
  if (!user) return null
  if (user.organizations.length === 0) return <Empty title="Create an organization first" action={<Link className="btn btn-primary" to="/organizer">Go to the organizer workspace</Link>}>Events belong to an organization.</Empty>
  return (
    <>
      <PageHead title="Create an event" lead="Everything you leave blank is shown to students as not stated. A pre-publication audit runs when you save." />
      {audit ? (
        <Panel title="Saved">
          <Notice tone={audit.audit.readiness.state === 'ready' ? 'good' : 'warn'}>{audit.is_published ? 'Published. ' : 'Saved as a draft. '}{audit.audit.readiness.summary}</Notice>
          <div className="btn-row"><Link className="btn btn-primary" to={`/organizer/events/${audit.id}`}>Review the audit and manage the event</Link><button className="btn" onClick={() => nav('/organizer')}>Back to my events</button></div>
        </Panel>
      ) : (
        <>
          <Select label="Organization" value={org} onChange={(e) => setOrg(e.target.value)} options={user.organizations.map((o) => ({ value: o.id, label: o.name }))} />
          <EventForm initial={EMPTY_REF} submitLabel={publish ? 'Create and publish' : 'Save as draft'} status={s}
            extra={<Check label="Publish immediately (a description of at least 40 characters is required)" checked={publish} onChange={(e) => setPublish(e.target.checked)} />}
            onSubmit={async (payload) => { const r = await s.run(() => api.post<{ id: string; is_published: boolean; audit: PublicationAudit }>('/organizer/events', { ...payload, organization_id: org, publish }), 'Event saved.'); if (r) setAudit(r) }} />
        </>
      )}
    </>
  )
}

function ManageEvent() {
  const { id = '' } = useParams()
  const state = useAsync((s) => api.get<EventDetail>(`/events/${id}`, undefined, s), [id])
  useTitle(state.data ? `Manage: ${state.data.title}` : 'Manage event')
  return (
    <DataState state={state} loadingLabel="Loading the event">
      {(e) => (
        <>
          <PageHead title={e.title} lead={<><Badge tone={e.is_published ? 'good' : 'warn'}>{e.is_published ? 'Published' : 'Draft'}</Badge> {categoryLabel(e.category)} {'·'} {e.origin.label}</>}
            actions={<><Link className="btn" to={`/events/${e.id}`}>View public page</Link><PublishToggle e={e} onDone={state.reload} /></>} />
          {!e.permissions.can_manage && <Notice tone="warn">Your account cannot manage this event. You can read it, but changes will be refused by the server.</Notice>}
          <Tabs items={[
            { to: `/organizer/events/${id}`, label: 'Pre-publication audit', end: true }, { to: `/organizer/events/${id}/edit`, label: 'Edit listing' }, { to: `/organizer/events/${id}/claims`, label: 'Promises and evidence' },
            { to: `/organizer/events/${id}/accessibility`, label: 'Accessibility' }, { to: `/organizer/events/${id}/feedback`, label: 'Participant feedback' }, { to: `/organizer/events/${id}/disputes`, label: 'Disputes' },
            { to: `/organizer/events/${id}/analytics`, label: 'Outcomes' }, { to: `/organizer/events/${id}/report`, label: 'Audit report' },
          ]} />
          <Routes>
            <Route index element={<AuditTab id={id} />} />
            <Route path="edit" element={<EditTab e={e} onSaved={state.reload} />} />
            <Route path="claims" element={<ClaimsTab e={e} reload={state.reload} />} />
            <Route path="accessibility" element={<AccessTab e={e} reload={state.reload} />} />
            <Route path="feedback" element={<FeedbackTab id={id} />} />
            <Route path="disputes" element={<EventDisputes e={e} />} />
            <Route path="analytics" element={<AnalyticsTab id={id} />} />
            <Route path="report" element={<ReportTab id={id} title={e.title} />} />
          </Routes>
        </>
      )}
    </DataState>
  )
}

function PublishToggle({ e, onDone }: { e: EventDetail; onDone: () => void }) {
  const s = useSubmit()
  return (
    <span>
      <button className={`btn ${e.is_published ? '' : 'btn-primary'}`} disabled={s.busy} onClick={() => s.run(async () => { await api.post(`/organizer/events/${e.id}/${e.is_published ? 'unpublish' : 'publish'}`); onDone() }, e.is_published ? 'Unpublished.' : 'Published.')}>
        {e.is_published ? 'Unpublish' : 'Publish'}
      </button>
      <FormStatus s={s} />
    </span>
  )
}

function IssueRow({ g, onDone, id }: { g: AuditIssue; onDone: () => void; id?: string }) {
  const [note, setNote] = useState('')
  const s = useSubmit()
  const isGap = !g.type || g.type === 'information_gap'
  return (
    <div className={`gap gap-${g.severity}`} data-testid="issue">
      <div className="claim-top"><SeverityBadge severity={g.severity} />{g.type && g.type !== 'information_gap' && <Badge tone="violet">{titleCase(g.type)}</Badge>}<Badge tone="info">Priority {g.priority}</Badge>{g.event_title && <Badge>{g.event_title}</Badge>}</div>
      <h4>{g.gap}</h4>
      <p className="small">{g.why_it_matters}</p>
      {g.source_text && <div className="quote small">{'“'}{g.source_text}{'”'}</div>}
      {g.student_question && <p className="small"><strong>Students are asking:</strong> {g.student_question}</p>}
      <p className="small"><strong>Suggested correction:</strong> {g.organizer_fix ?? g.next_action}</p>
      {g.urgency_reason && <p className="small dim">Urgency: {g.urgency_reason} (impact {g.impact} {'×'} urgency {g.urgency})</p>}
      {g.event_id && <Link className="btn btn-sm" to={`/organizer/events/${g.event_id}${isGap ? '/edit' : ''}`}>Open event</Link>}
      {isGap && g.id && g.status === 'open' && (
        <div className="inline-form" style={{ marginTop: 8 }}>
          <TextField label="Resolution note" value={note} onChange={(e) => setNote(e.target.value)} />
          <button className="btn btn-sm" disabled={s.busy || note.trim().length < 5} onClick={() => s.run(async () => { await api.patch(`/organizer/gaps/${g.id}`, { status: 'resolved', note }); onDone() }, 'Marked resolved.')}>Resolved</button>
          <button className="btn btn-sm" disabled={s.busy || note.trim().length < 5} onClick={() => s.run(async () => { await api.patch(`/organizer/gaps/${g.id}`, { status: 'dismissed', note }); onDone() }, 'Dismissed.')}>Dismiss</button>
        </div>
      )}
      {g.status !== 'open' && g.resolution_note && <p className="small muted">{titleCase(g.status)}: {g.resolution_note}</p>}
      <FormStatus s={s} />
      <span hidden>{id}</span>
    </div>
  )
}

function AuditTab({ id }: { id: string }) {
  const state = useAsync((s) => api.get<PublicationAudit>(`/organizer/events/${id}/audit`, undefined, s), [id])
  const s = useSubmit()
  return (
    <DataState state={state} loadingLabel="Running the audit">
      {(a) => (
        <>
          <Notice tone={a.readiness.state === 'ready' ? 'good' : a.readiness.state === 'blocked' ? 'bad' : 'warn'}>
            <strong>{a.readiness.state === 'ready' ? 'Ready to publish' : a.readiness.state === 'blocked' ? 'Blocked' : 'Needs attention'}.</strong> {a.readiness.summary}
            {a.readiness.blocking.length > 0 && <ul className="bullets">{a.readiness.blocking.map((b) => <li key={b}>{b}</li>)}</ul>}
          </Notice>
          <div className="cols-2">
            <Panel title="Completeness">
              <div className="card-meter"><Ledger filled={a.completeness.filled} total={a.completeness.total} /> <span>{a.completeness.filled} of {a.completeness.total} details stated</span></div>
              <p className="small muted">{a.completeness.note}</p>
              {a.completeness.missing.length > 0 && <p className="small"><strong>Missing:</strong> {a.completeness.missing.map((m) => m.label).join(', ')}</p>}
              <p className="small">Accessibility documented: {a.accessibility.documented} of {a.accessibility.total} items. <Link to={`/organizer/events/${id}/accessibility`}>Update checklist</Link></p>
            </Panel>
            <Panel title="Fix these first">
              {a.next_actions.length === 0 ? <p className="muted">Nothing urgent.</p> : <ol>{a.next_actions.map((n) => <li key={n.label}><strong>{n.label}</strong><div className="small muted">{n.action}</div></li>)}</ol>}
              <p className="small dim">{a.prioritisation}</p>
              <div className="btn-row"><button className="btn btn-sm" disabled={s.busy} onClick={() => s.run(async () => { await api.post(`/organizer/events/${id}/audit`); state.reload() }, 'Audit re-run.')}>Re-run the audit</button></div><FormStatus s={s} />
            </Panel>
          </div>
          <Panel title={`Open issues (${a.issues.length})`}>
            {a.issues.length === 0 ? <p className="muted">No open issues.</p> : a.issues.map((g) => <IssueRow key={g.id} g={g} onDone={state.reload} />)}
          </Panel>
          {a.vague_claims.length > 0 && (
            <Panel title={`Vague promises (${a.vague_claims.length})`}>
              {a.vague_claims.map((v) => <div className="claim" key={v.claim_id}><div className="quote">{'“'}{v.text}{'”'}</div><p className="small"><strong>Missing:</strong> {v.missing_details.join('; ')}</p><p className="small">{v.suggestion}</p></div>)}
            </Panel>
          )}
          {a.closed_issues.length > 0 && <Panel title={`Closed issues (${a.closed_issues.length})`}>{a.closed_issues.map((g) => <IssueRow key={g.id} g={g} onDone={state.reload} />)}</Panel>}
        </>
      )}
    </DataState>
  )
}

function EditTab({ e, onSaved }: { e: EventDetail; onSaved: () => void }) {
  const s = useSubmit()
  const [note, setNote] = useState('')
  const [result, setResult] = useState<string | null>(null)
  const initial = valuesFromEvent(e)
  return (
    <>
      {result && <Notice tone="good">{result}</Notice>}
      <EventForm initial={initial} submitLabel="Save changes" status={s}
        extra={<TextField label="What changed? (kept in the change history)" value={note} onChange={(x) => setNote(x.target.value)} maxLength={500} />}
        onSubmit={async (payload) => {
          if (Object.keys(payload).length === 0) { await s.run(() => Promise.reject(new Error('No changes to save.'))); return }
          const r = await s.run(() => api.patch<{ changed_fields: string[] }>(`/organizer/events/${e.id}`, { ...payload, change_note: note || null }), 'Changes saved.')
          if (r) { setResult(`Saved: ${r.changed_fields.map(titleCase).join(', ')}. The audit was re-run.`); onSaved() }
        }} />
    </>
  )
}

function ClaimsTab({ e, reload }: { e: EventDetail; reload: () => void }) {
  const [text, setText] = useState(''); const [cat, setCat] = useState('other'); const [type, setType] = useState('specific'); const [party, setParty] = useState('')
  const s = useSubmit()
  return (
    <>
      <Panel title="Add a promise">
        <p className="muted">Add a commitment the analyzer did not pick up. It is recorded in your exact words.</p>
        <form onSubmit={async (ev) => { ev.preventDefault(); const r = await s.run(() => api.post(`/organizer/events/${e.id}/claims`, { original_text: text, category: cat, claim_type: type, responsible_party: party || null }), 'Promise added.'); if (r !== undefined) { setText(''); reload() } }}>
          <TextArea label="Promise, exactly as you would publish it" rows={2} value={text} onChange={(x) => setText(x.target.value)} hint="At least 8 characters." />
          <div className="form-grid">
            <Select label="Category" value={cat} onChange={(x) => setCat(x.target.value)} options={['prize', 'certificate', 'mentorship', 'career_opportunity', 'training_workshop', 'recordings_materials', 'results_timeline', 'networking', 'perks_swag', 'travel_accommodation', 'food', 'learning_outcome', 'fee_cost', 'refund_policy', 'scholarship_discount', 'accessibility', 'other'].map((v) => ({ value: v, label: titleCase(v) }))} />
            <Select label="Type" value={type} onChange={(x) => setType(x.target.value)} options={['specific', 'vague', 'conditional', 'informational'].map((v) => ({ value: v, label: titleCase(v) }))} />
            <TextField label="Who is responsible (optional)" value={party} onChange={(x) => setParty(x.target.value)} />
          </div>
          <button className="btn" disabled={s.busy || text.trim().length < 8}>Add promise</button><FormStatus s={s} />
        </form>
      </Panel>
      <Panel title={`Promises (${e.claims.length})`}>
        {e.claims.length === 0 ? <p className="muted">No promises are recorded yet. Saving the listing runs the analyzer, or add one above.</p> : e.claims.map((c) => <ClaimPanel key={c.id} claim={c} eventId={e.id} perm={{ manage: e.permissions.can_manage, review: e.permissions.can_review }} onChanged={reload} />)}
        <p className="small muted">Open a promise to attach evidence. Evidence you provide is labelled organizer-provided and cannot corroborate a promise by itself; reviewers decide status.</p>
      </Panel>
    </>
  )
}

function AccessTab({ e, reload }: { e: EventDetail; reload: () => void }) {
  return (
    <Panel title="Accessibility checklist">
      <p className="muted">{e.accessibility.completeness_note} Choose {'“'}Documented{'”'} only when you can describe what is provided. {'“'}Not documented{'”'} tells students it is unknown, not unavailable.</p>
      <div className="stack">{e.accessibility.items.map((i) => <AccessRow key={i.key} eventId={e.id} item={i} onDone={reload} />)}</div>
    </Panel>
  )
}
function AccessRow({ eventId, item, onDone }: { eventId: string; item: EventDetail['accessibility']['items'][number]; onDone: () => void }) {
  const [state, setState] = useState(item.state); const [detail, setDetail] = useState(item.detail ?? ''); const [url, setUrl] = useState(item.evidence_url ?? '')
  const s = useSubmit()
  return (
    <form className="acc-item" onSubmit={async (ev) => { ev.preventDefault(); const r = await s.run(() => api.put(`/organizer/events/${eventId}/accessibility/${item.key}`, { state, detail: detail || null, evidence_url: url || null }), 'Saved.'); if (r !== undefined) onDone() }}>
      <h4>{item.label} <AccessStateBadge state={item.state} /></h4>
      {item.student_question && <p className="small muted">Students ask: {item.student_question}</p>}
      <div className="form-grid">
        <Select label="State" value={state} onChange={(x) => setState(x.target.value as typeof state)} options={['documented', 'not_documented', 'confirmed_unavailable', 'conflicting', 'requires_confirmation'].map((v) => ({ value: v, label: titleCase(v) }))} />
        <TextField label="Details" value={detail} onChange={(x) => setDetail(x.target.value)} />
        <TextField label="Evidence link" type="url" value={url} onChange={(x) => setUrl(x.target.value)} />
      </div>
      <button className="btn btn-sm" disabled={s.busy}>Save</button><FormStatus s={s} />
    </form>
  )
}

function FeedbackTab({ id }: { id: string }) {
  const [status, setStatus] = useState('')
  const state = useAsync((s) => api.get<{ items: OrgFeedbackItem[] }>(`/organizer/events/${id}/feedback`, { status }, s), [id, status])
  return (
    <Panel title="Participant feedback" actions={<div style={{ minWidth: 180 }}><Select label="Show" value={status} onChange={(e) => setStatus(e.target.value)} options={[{ value: '', label: 'Published and pending' }, { value: 'published', label: 'Published only' }, { value: 'pending', label: 'Pending moderation' }]} /></div>}>
      <p className="small muted">Reporter identities are never shown. Pending answers are awaiting a moderator and do not count yet.</p>
      <DataState state={state} loadingLabel="Loading feedback" isEmpty={(d) => d.items.length === 0} empty={<Empty title="No feedback yet">Participants can answer once the event has ended.</Empty>}>
        {(d) => <ul className="plain">{d.items.map((f) => <FeedbackRow key={f.id} f={f} eventId={id} onDone={state.reload} />)}</ul>}
      </DataState>
    </Panel>
  )
}
function FeedbackRow({ f, eventId, onDone }: { f: OrgFeedbackItem; eventId: string; onDone: () => void }) {
  const [body, setBody] = useState(''); const s = useSubmit()
  return (
    <li>
      <div className="claim-top"><Badge tone="violet">Participant report</Badge><Badge>{FEEDBACK_RESPONSE[f.response] ?? f.response}</Badge><Badge tone={f.status === 'published' ? 'good' : 'unknown'}>{titleCase(f.status)}</Badge><Badge tone="neutral">{titleCase(f.participation_level)}</Badge></div>
      <div className="small dim">On: {'“'}{f.claim}{'”'}</div>
      {f.comment ? <p>{f.comment}</p> : <p className="unknown">No comment.</p>}
      {f.organizer_responses.map((r, i) => <div className="quote small" key={i}><strong>Your reply:</strong> {r.body}</div>)}
      <div className="inline-form"><TextField label="Reply publicly" value={body} onChange={(e) => setBody(e.target.value)} />
        <button className="btn btn-sm" disabled={s.busy || body.trim().length < 5} onClick={async () => { const r = await s.run(() => api.post('/organizer/responses', { event_id: eventId, feedback_id: f.id, body }), 'Reply published.'); if (r !== undefined) { setBody(''); onDone() } }}>Reply</button></div>
      <FormStatus s={s} />
    </li>
  )
}

function DisputeList({ items }: { items: Dispute[] }) {
  return <ul className="plain">{items.map((d) => (
    <li key={d.id}><div className="claim-top"><Badge tone="violet">{titleCase(d.kind)}</Badge><Badge tone={d.status === 'upheld' ? 'good' : d.status === 'rejected' ? 'bad' : 'warn'}>{titleCase(d.status)}</Badge></div>
      {d.event_title && <div className="small"><Link to={`/organizer/events/${d.event_id}`}>{d.event_title}</Link></div>}
      <p>{d.description}</p>{d.resolution_note && <p className="small muted">Reviewer note: {d.resolution_note}</p>}<span className="small dim">{fmtDateTime(d.created_at)}</span></li>
  ))}</ul>
}
function EventDisputes({ e }: { e: EventDetail }) {
  const state = useAsync((s) => api.get<{ items: Dispute[] }>('/disputes', { event_id: e.id }, s), [e.id])
  const [desc, setDesc] = useState(''); const s = useSubmit()
  return (
    <>
      <Panel title="Request a correction">
        <p className="muted">Tell reviewers about wrong information on this listing. To dispute a specific promise, open it under Promises and evidence.</p>
        <form onSubmit={async (ev) => { ev.preventDefault(); const r = await s.run(() => api.post('/disputes', { event_id: e.id, kind: 'correction_request', description: desc }), 'Correction request sent.'); if (r !== undefined) { setDesc(''); state.reload() } }}>
          <TextArea label="What is wrong, and what is correct?" rows={3} value={desc} onChange={(x) => setDesc(x.target.value)} hint="At least 15 characters." />
          <button className="btn" disabled={s.busy || desc.trim().length < 15}>Send request</button><FormStatus s={s} />
        </form>
      </Panel>
      <Panel title="Disputes for this event">
        <DataState state={state} loadingLabel="Loading disputes" isEmpty={(d) => d.items.length === 0} empty={<p className="muted">No disputes or correction requests.</p>}>{(d) => <DisputeList items={d.items} />}</DataState>
      </Panel>
    </>
  )
}
function DisputesPage() {
  useTitle('Disputes')
  const state = useAsync((s) => api.get<{ items: Dispute[] }>('/disputes', undefined, s), [])
  return (
    <>
      <PageHead title="Disputes" lead="Disputes and correction requests across your events. Reviewers decide them." />
      <Panel><DataState state={state} loadingLabel="Loading disputes" isEmpty={(d) => d.items.length === 0} empty={<Empty title="No disputes">Raise one from a promise on an event you manage.</Empty>}>{(d) => <DisputeList items={d.items} />}</DataState></Panel>
    </>
  )
}

function IssuesPage() {
  useTitle('Issue tracker')
  const state = useAsync((s) => api.get<{ items: AuditIssue[]; total: number; ordering: string }>('/organizer/issues', undefined, s), [])
  return (
    <>
      <PageHead title="Issue tracker" lead="Everything students and reviewers have flagged across your events, most important first." />
      <DataState state={state} loadingLabel="Loading issues" isEmpty={(d) => d.items.length === 0} empty={<Empty title="No open issues">Nothing is flagged across your events.</Empty>}>
        {(d) => <><p className="small muted">{d.total} open. {d.ordering}</p>{d.items.map((g) => <IssueRow key={`${g.type}-${g.id}`} g={g} onDone={state.reload} />)}</>}
      </DataState>
    </>
  )
}

function OwnershipPage() {
  useTitle('Ownership requests')
  const state = useAsync((s) => api.get<{ items: OwnershipRequest[] }>('/organizer/ownership-requests', undefined, s), [])
  return (
    <>
      <PageHead title="Ownership requests" lead="Requests to take over listings that were indexed from public sources. Start one from the event's own page." />
      <Panel><DataState state={state} loadingLabel="Loading requests" isEmpty={(d) => d.items.length === 0} empty={<Empty title="No requests" action={<Link className="btn" to="/discover">Find your event</Link>}>Open your event in Discover and choose {'“'}Is this your event?{'”'} at the bottom of its page.</Empty>}>
        {(d) => <ul className="plain">{d.items.map((r) => <li key={r.id}><Link to={`/events/${r.event_id}`}>{r.event_title}</Link> <Badge tone={r.status === 'approved' ? 'good' : r.status === 'rejected' ? 'bad' : 'warn'}>{titleCase(r.status)}</Badge><div className="small muted">{fmtDateTime(r.created_at)}{r.decision_note ? ` · ${r.decision_note}` : ''}</div></li>)}</ul>}
      </DataState></Panel>
    </>
  )
}

function Ratio({ label, r }: { label: string; r: { numerator: number; denominator: number; pct: number | null } }) {
  return <div className="stat"><strong>{r.pct === null ? '—' : `${r.pct}%`}</strong><span>{label}: {r.numerator} of {r.denominator}{r.pct === null ? ' (no data yet)' : ''}</span></div>
}
function AnalyticsTab({ id }: { id: string }) {
  const state = useAsync((s) => api.get<EventAnalytics>(`/organizer/events/${id}/analytics`, undefined, s), [id])
  return (
    <DataState state={state} loadingLabel="Calculating outcomes">
      {(a) => (
        <>
          <Notice tone="info" live={false}>Every percentage shows its numerator and denominator. {a.learning_outcomes}</Notice>
          <div className="cols-2">
            <Panel title="Promises"><div className="stat-row"><Ratio label="Outcome established" r={a.claims.outcome_established} /><div className="stat"><strong>{a.claims.unresolved}</strong><span>unresolved (unknown, not failed)</span></div><div className="stat"><strong>{a.claims.disputed}</strong><span>disputed</span></div></div>
              <ul className="bullets small">{Object.entries(a.claims.by_status).map(([k, v]) => <li key={k}>{CLAIM_STATUS[k as keyof typeof CLAIM_STATUS]?.label ?? titleCase(k)}: {v}</li>)}</ul><p className="small muted">{a.claims.note}</p></Panel>
            <Panel title="Participant feedback"><div className="stat-row"><Ratio label="Response rate" r={a.feedback.response_rate} /><div className="stat"><strong>{a.feedback.responses_published}</strong><span>published answers</span></div><div className="stat"><strong>{a.feedback.responses_pending_moderation}</strong><span>pending moderation</span></div></div></Panel>
            <Panel title="Information quality"><p>{a.completeness.before && a.completeness.after ? `Details stated: ${a.completeness.before.filled} of ${a.completeness.before.total} at first version, ${a.completeness.after.filled} of ${a.completeness.after.total} now.` : 'No version history to compare yet.'} {a.completeness.organizer_corrections} correction(s) by organizers or reviewers.</p><p className="small muted">{a.completeness.note}</p>
              <div className="stat-row"><Ratio label="Accessibility documented" r={a.accessibility.documented} /><Ratio label="Accessibility answered" r={a.accessibility.answered} /></div><p className="small muted">{a.accessibility.note}</p></Panel>
            <Panel title="Issues and disputes"><div className="stat-row"><Ratio label="Gaps closed" r={a.issues.gap_resolution_rate} /><Ratio label="Disputes closed" r={a.issues.disputes_closed} /></div>
              <p className="small muted">Median time to resolve a gap: {a.issues.gap_median_hours_to_resolve === null ? 'no resolved gaps yet' : `${a.issues.gap_median_hours_to_resolve} h (from ${a.issues.gap_resolved_by_people} resolved by people)`}. Median time to close a dispute: {a.issues.dispute_median_hours_to_resolve === null ? 'none closed yet' : `${a.issues.dispute_median_hours_to_resolve} h`}.</p></Panel>
          </div>
        </>
      )}
    </DataState>
  )
}

function ReportTab({ id, title }: { id: string; title: string }) {
  const s = useSubmit()
  const get = (format: 'json' | 'md' | 'html') => s.run(() => download(`/organizer/events/${id}/report`, { format }, `audit-${title.replace(/[^a-z0-9]+/gi, '-').toLowerCase().slice(0, 40)}.${format === 'md' ? 'md' : format}`), 'Report downloaded.')
  return (
    <Panel title="Audit report">
      <p className="muted">Lists advertised promises, the evidence reviewed, information gaps, accessibility, outcomes with denominators, change history and the audit trail. It does not rate your honesty. Each export is recorded in the audit log.</p>
      <div className="btn-row">
        <button className="btn btn-primary" disabled={s.busy} onClick={() => get('html')}>Download HTML</button>
        <button className="btn" disabled={s.busy} onClick={() => get('md')}>Download Markdown</button>
        <button className="btn" disabled={s.busy} onClick={() => get('json')}>Download JSON</button>
      </div>
      <FormStatus s={s} />
    </Panel>
  )
}
export { ClaimStatusBadge, fmtPct }
