import { useState } from 'react'
import { Link, Route, Routes } from 'react-router-dom'
import { api } from '../../api/client'
import { useAuth } from '../../auth/AuthContext'
import { RequireRole } from '../../auth/RequireRole'
import type { AdminUser, AuditLog, Config, Dispute, Moderation, Org, Paged, PlatformAnalytics, SourceInfo, SyncRun } from '../../api/types'
import { DataState, Empty, Notice } from '../../components/States'
import { Badge, Check, FormStatus, PageHead, Pagination, Panel, Select, Tabs, TextArea, TextField, useSubmit, EvidenceKindBadge } from '../../components/ui'
import { fmtDateTime, fmtPct, fmtRelative } from '../../lib/format'
import { FEEDBACK_RESPONSE, claimStatusLabel, titleCase } from '../../lib/labels'
import { useAsync, useTitle } from '../../lib/useAsync'

export default function AdminArea() {
  const { user } = useAuth()
  const admin = user?.role === 'admin'
  return (
    <div className="wrap page">
      <Tabs items={[
        { to: '/admin', label: 'Overview', end: true }, { to: '/admin/sources', label: 'Source health' }, { to: '/admin/moderation', label: 'Moderation queue' },
        { to: '/admin/disputes', label: 'Disputes' },
        ...(admin ? [{ to: '/admin/users', label: 'Users and roles' }, { to: '/admin/audit', label: 'Audit logs' }, { to: '/admin/config', label: 'System configuration' }] : []),
      ]} />
      <Routes>
        <Route index element={<Overview />} />
        <Route path="sources" element={<Sources admin={!!admin} />} />
        <Route path="moderation" element={<ModerationPage />} />
        <Route path="disputes" element={<DisputesAdmin />} />
        <Route path="users" element={<RequireRole roles={['admin']}><UsersPage /></RequireRole>} />
        <Route path="audit" element={<RequireRole roles={['admin']}><AuditPage /></RequireRole>} />
        <Route path="config" element={<RequireRole roles={['admin']}><ConfigPage /></RequireRole>} />
        <Route path="*" element={<Empty title="Page not found" />} />
      </Routes>
    </div>
  )
}

function Overview() {
  useTitle('Admin overview')
  const a = useAsync((s) => api.get<PlatformAnalytics>('/admin/analytics', undefined, s), [])
  const m = useAsync((s) => api.get<Moderation>('/admin/moderation', undefined, s), [])
  return (
    <>
      <PageHead title="Platform overview" lead="Counts come from stored records. Percentages show numerator and denominator." />
      <div className="cols-2">
        <Panel title="Work waiting">
          <DataState state={m} loadingLabel="Loading queue">{(d) => (
            <ul className="plain">{Object.entries(d.counts).map(([k, v]) => <li key={k} className="mini"><span>{titleCase(k)}</span><Badge tone={v ? 'warn' : 'good'}>{v}</Badge></li>)}
              <li><Link to="/admin/moderation">Open the moderation queue</Link></li></ul>)}</DataState>
        </Panel>
        <Panel title="Platform">
          <DataState state={a} loadingLabel="Loading analytics">{(d) => (
            <>
              <div className="stat-row"><div className="stat"><strong>{d.events.toLocaleString('en-IN')}</strong><span>events</span></div><div className="stat"><strong>{d.claims.total.toLocaleString('en-IN')}</strong><span>active promises</span></div></div>
              <p>Promises with an established outcome: {fmtPct(d.claims.outcome_established)}. Information gaps closed: {fmtPct(d.gaps.closed)}.</p>
              <h4>Promises by status</h4>
              <ul className="bullets small">{Object.entries(d.claims.by_status).map(([k, v]) => <li key={k}>{claimStatusLabel(k)}: {v}</li>)}</ul>
              <h4>Feedback by moderation state</h4>
              <p className="small">{Object.keys(d.feedback_by_status).length ? Object.entries(d.feedback_by_status).map(([k, v]) => `${titleCase(k)}: ${v}`).join(', ') : 'No feedback yet.'}</p>
              <h4>Disputes by status</h4>
              <p className="small">{Object.keys(d.disputes_by_status).length ? Object.entries(d.disputes_by_status).map(([k, v]) => `${titleCase(k)}: ${v}`).join(', ') : 'No disputes yet.'}</p>
            </>)}</DataState>
        </Panel>
      </div>
    </>
  )
}

const STATUS_TONE: Record<string, 'good' | 'warn' | 'bad' | 'unknown'> = { active: 'good', degraded: 'warn', blocked: 'bad', pending_first_sync: 'unknown', needs_credentials: 'warn', not_configured: 'unknown', not_implemented: 'unknown', disabled: 'unknown' }

function Sources({ admin }: { admin: boolean }) {
  useTitle('Source health')
  const sources = useAsync((s) => api.get<{ items: SourceInfo[] }>('/admin/sources', undefined, s), [])
  const runs = useAsync((s) => api.get<{ items: SyncRun[] }>('/admin/sync-runs', { limit: 30 }, s), [])
  const reloadAll = () => { sources.reload(); runs.reload() }
  return (
    <>
      <PageHead title="Source health" lead="Every connector, its last sync, and why a source is not contributing events." />
      {!admin && <Notice tone="info" live={false}>You can read source health as a reviewer. Only administrators can sync or change sources.</Notice>}
      <DataState state={sources} loadingLabel="Loading sources">
        {(d) => <div className="stack">{d.items.map((s) => <SourceCard key={s.key} s={s} admin={admin} onDone={reloadAll} />)}</div>}
      </DataState>
      <Panel title="Sync history">
        <DataState state={runs} loadingLabel="Loading sync history" isEmpty={(d) => d.items.length === 0} empty={<p className="muted">No sync has run yet.</p>}>
          {(d) => (
            <div className="table-wrap"><table>
              <thead><tr><th scope="col">Source</th><th scope="col">Started</th><th scope="col">Trigger</th><th scope="col">Status</th><th scope="col">Fetched</th><th scope="col">New</th><th scope="col">Updated</th><th scope="col">Unchanged</th><th scope="col">Missing</th><th scope="col">Errors</th></tr></thead>
              <tbody>{d.items.map((r) => <tr key={r.id}><td>{r.source_name}</td><td>{fmtDateTime(r.started_at)}</td><td>{r.trigger}</td><td><Badge tone={r.status === 'success' ? 'good' : r.status === 'failed' ? 'bad' : 'warn'}>{titleCase(r.status)}</Badge></td><td>{r.fetched}</td><td>{r.created}</td><td>{r.updated}</td><td>{r.unchanged}</td><td>{r.missing}</td><td className="small">{r.errors.length ? r.errors.map(String).join('; ') : 'None'}</td></tr>)}</tbody>
            </table></div>
          )}
        </DataState>
      </Panel>
    </>
  )
}

function SourceCard({ s, admin, onDone }: { s: SourceInfo; admin: boolean; onDone: () => void }) {
  const a = useSubmit()
  const [prio, setPrio] = useState(String(s.priority))
  const [feeds, setFeeds] = useState((s.config?.ics_feed_urls ?? []).join('\n'))
  return (
    <Panel title={<>{s.name} <Badge tone={STATUS_TONE[s.status] ?? 'neutral'}>{titleCase(s.status)}</Badge> {!s.enabled && <Badge tone="unknown">Disabled</Badge>}</>}>
      <dl className="kv">
        <div><dt>Events linked</dt><dd>{s.events_linked.toLocaleString('en-IN')}</dd></div>
        <div><dt>Last success</dt><dd>{s.last_success_at ? `${fmtDateTime(s.last_success_at)} (${fmtRelative(s.last_success_at)})` : 'Never'}</dd></div>
        <div><dt>Last attempt</dt><dd>{s.last_attempt_at ? fmtDateTime(s.last_attempt_at) : 'Never'}</dd></div>
        <div><dt>Connector</dt><dd>{s.connector_implemented ? 'Implemented' : 'Not implemented'}</dd></div>
        <div><dt>Access method</dt><dd>{s.access_method ?? 'Not stated'}</dd></div>
        <div><dt>Credentials</dt><dd>{s.auth_requirement ?? 'Not stated'}</dd></div>
      </dl>
      {s.status_detail && <p className="small"><strong>Status detail:</strong> {s.status_detail}</p>}
      {s.last_error && <Notice tone="bad"><strong>Last error</strong> ({s.consecutive_failures} in a row): {s.last_error}</Notice>}
      {s.limitations && <p className="small muted"><strong>Limitations:</strong> {s.limitations}</p>}
      {s.last_run && <p className="small muted">Last run: {titleCase(s.last_run.status)}, {s.last_run.fetched} fetched, {s.last_run.created} new, {s.last_run.updated} updated, {s.last_run.unchanged} unchanged.</p>}
      <p className="small muted">{s.attribution}{s.homepage && <> {'·'} <a href={s.homepage} target="_blank" rel="noopener noreferrer">Homepage</a></>}{s.terms_url && <> {'·'} <a href={s.terms_url} target="_blank" rel="noopener noreferrer">Terms</a></>}</p>
      {admin && (
        <div className="stack">
          <div className="btn-row">
            <button className="btn btn-primary btn-sm" disabled={a.busy || !s.connector_implemented || !s.enabled} title={!s.connector_implemented ? 'No connector exists for this source' : undefined}
              onClick={() => a.run(async () => { await api.post(`/admin/sources/${s.key}/sync`); setTimeout(onDone, 1500) }, 'Sync started. History refreshes shortly.')}>Sync now</button>
            <button className="btn btn-sm" disabled={a.busy || (!s.enabled && !s.connector_implemented)} onClick={() => a.run(async () => { await api.patch(`/admin/sources/${s.key}`, { enabled: !s.enabled }); onDone() }, s.enabled ? 'Disabled.' : 'Enabled.')}>{s.enabled ? 'Disable' : 'Enable'}</button>
          </div>
          <div className="inline-form"><TextField label="Priority (0 to 100)" type="number" min={0} max={100} value={prio} onChange={(e) => setPrio(e.target.value)} />
            <button className="btn btn-sm" disabled={a.busy} onClick={() => a.run(async () => { await api.patch(`/admin/sources/${s.key}`, { priority: Number(prio) }); onDone() }, 'Priority saved.')}>Save priority</button></div>
          {s.key === 'ics_feeds' && (
            <div><TextArea label="ICS feed URLs (one per line)" rows={3} value={feeds} onChange={(e) => setFeeds(e.target.value)} />
              <button className="btn btn-sm" disabled={a.busy} onClick={() => a.run(async () => { await api.patch(`/admin/sources/${s.key}`, { ics_feed_urls: feeds.split('\n').map((x) => x.trim()).filter(Boolean) }); onDone() }, 'Feeds saved.')}>Save feeds</button></div>
          )}
          <FormStatus s={a} />
        </div>
      )}
    </Panel>
  )
}

function Item({ children, onDone, actions }: { children: React.ReactNode; onDone: () => void; actions: (note: string, run: ReturnType<typeof useSubmit>['run'], reload: () => void) => React.ReactNode }) {
  const [note, setNote] = useState('')
  const s = useSubmit()
  return (
    <li>
      {children}
      <div className="inline-form" style={{ marginTop: 8 }}>
        <TextField label="Note (required)" value={note} onChange={(e) => setNote(e.target.value)} />
        {actions(note, s.run, onDone)}
      </div>
      <FormStatus s={s} />
    </li>
  )
}

function ModerationPage() {
  useTitle('Moderation queue')
  const state = useAsync((s) => api.get<Moderation>('/admin/moderation', undefined, s), [])
  const { user } = useAuth()
  return (
    <>
      <PageHead title="Moderation queue" lead="Feedback, evidence, reports, ownership requests and possible duplicates waiting for a decision." />
      <DataState state={state} loadingLabel="Loading the queue">
        {(d) => (
          <>
            <Notice tone="info" live={false}>{Object.entries(d.counts).map(([k, v]) => `${titleCase(k)}: ${v}`).join(' · ')}. Reviewers who belong to an event's organization are blocked by the server from deciding its items.</Notice>
            <Panel title={`Participant feedback (${d.feedback.length})`}>
              {d.feedback.length === 0 ? <p className="muted">Nothing waiting.</p> : <ul className="plain">{d.feedback.map((f) => (
                <Item key={f.id} onDone={state.reload} actions={(note, run, reload) => (<>
                  <button className="btn btn-sm" disabled={note.trim().length < 3} onClick={() => run(async () => { await api.post(`/admin/feedback/${f.id}/moderate`, { status: 'published', note }); reload() }, 'Published.')}>Publish</button>
                  <button className="btn btn-sm btn-danger" disabled={note.trim().length < 3} onClick={() => run(async () => { await api.post(`/admin/feedback/${f.id}/moderate`, { status: 'rejected', note }); reload() }, 'Rejected.')}>Reject</button></>)}>
                  <div className="claim-top"><Badge tone="violet">Participant report</Badge><Badge>{FEEDBACK_RESPONSE[f.response] ?? f.response}</Badge><Badge tone="neutral">{titleCase(f.participation_level)}</Badge>{f.has_evidence && <Badge tone="info">Has evidence link</Badge>}</div>
                  <div className="small"><Link to={`/events/${f.event_id}`}>{f.event_title}</Link></div><div className="quote small">{'“'}{f.claim}{'”'}</div>{f.comment && <p>{f.comment}</p>}
                </Item>
              ))}</ul>}
            </Panel>
            <Panel title={`Evidence awaiting review (${d.evidence.length})`}>
              {d.evidence.length === 0 ? <p className="muted">Nothing waiting.</p> : <ul className="plain">{d.evidence.map((e) => (
                <Item key={e.id} onDone={state.reload} actions={(note, run, reload) => (<>
                  <button className="btn btn-sm" disabled={note.trim().length < 5} onClick={() => run(async () => { await api.post(`/evidence/${e.id}/review`, { decision: 'accepted', note }); reload() }, 'Accepted.')}>Accept</button>
                  <button className="btn btn-sm btn-danger" disabled={note.trim().length < 5} onClick={() => run(async () => { await api.post(`/evidence/${e.id}/review`, { decision: 'rejected', note }); reload() }, 'Rejected.')}>Reject</button></>)}>
                  <div className="claim-top"><EvidenceKindBadge kind={e.kind} />{e.coi_declared && <Badge tone="warn">Conflict declared</Badge>}{e.has_file && <Badge>File: {e.file_name}</Badge>}</div>
                  <div className="small"><Link to={`/events/${e.event_id}#promises`}>{e.event_title}</Link></div>{e.excerpt && <div className="quote small">{e.excerpt}</div>}{e.url && <p className="small"><a href={e.url} target="_blank" rel="noopener noreferrer">{e.url}</a></p>}
                </Item>
              ))}</ul>}
            </Panel>
            <Panel title={`Reports (${d.reports.length})`}>
              {d.reports.length === 0 ? <p className="muted">Nothing waiting.</p> : <ul className="plain">{d.reports.map((r) => (
                <Item key={r.id} onDone={state.reload} actions={(note, run, reload) => (<>
                  <button className="btn btn-sm" disabled={note.trim().length < 3} onClick={() => run(async () => { await api.post(`/admin/reports/${r.id}/handle`, { action: 'dismiss', note }); reload() }, 'Dismissed.')}>Dismiss</button>
                  <button className="btn btn-sm btn-danger" disabled={note.trim().length < 3} onClick={() => run(async () => { await api.post(`/admin/reports/${r.id}/handle`, { action: 'upheld_hide', note }); reload() }, 'Upheld.')}>Uphold and hide</button></>)}>
                  <Badge tone="violet">{titleCase(r.target_type)}</Badge> <span className="small dim">{fmtDateTime(r.created_at)}</span><p>{r.reason}</p>
                  {r.target_type === 'event' && <Link className="small" to={`/events/${r.target_id}`}>Open event</Link>}
                </Item>
              ))}</ul>}
            </Panel>
            <Panel title={`Ownership requests (${d.ownership_requests.length})`}>
              {d.ownership_requests.length === 0 ? <p className="muted">Nothing waiting.</p> : <ul className="plain">{d.ownership_requests.map((r) => (
                <Item key={r.id} onDone={state.reload} actions={(note, run, reload) => (<>
                  <button className="btn btn-sm" disabled={note.trim().length < 3} onClick={() => run(async () => { await api.post(`/admin/ownership-requests/${r.id}/decision`, { approve: true, note }); reload() }, 'Approved.')}>Approve</button>
                  <button className="btn btn-sm btn-danger" disabled={note.trim().length < 3} onClick={() => run(async () => { await api.post(`/admin/ownership-requests/${r.id}/decision`, { approve: false, note }); reload() }, 'Rejected.')}>Reject</button></>)}>
                  <strong>{r.organization}</strong> wants <Link to={`/events/${r.event_id}`}>{r.event_title}</Link><p className="small">{r.justification}</p>{r.proof_url && <p className="small"><a href={r.proof_url} target="_blank" rel="noopener noreferrer">Proof link</a></p>}
                </Item>
              ))}</ul>}
            </Panel>
            <Panel title={`Possible duplicates (${d.duplicates.length})`}>
              {d.duplicates.length === 0 ? <p className="muted">No candidates waiting.</p> : <ul className="plain">{d.duplicates.map((x) => <DuplicateRow key={x.id} d={x} onDone={state.reload} canMerge={user?.role === 'admin' || user?.role === 'reviewer'} />)}</ul>}
            </Panel>
          </>
        )}
      </DataState>
    </>
  )
}

function DuplicateRow({ d, onDone }: { d: Moderation['duplicates'][number]; onDone: () => void; canMerge: boolean }) {
  const s = useSubmit()
  return (
    <li>
      <p><Link to={`/events/${d.a.id}`}>{d.a.title}</Link> <span className="dim">and</span> <Link to={`/events/${d.b.id}`}>{d.b.title}</Link> <Badge tone="info">{Math.round(d.similarity * 100)}% similar</Badge></p>
      <div className="btn-row">
        <button className="btn btn-sm" disabled={s.busy} onClick={() => s.run(async () => { await api.post(`/admin/duplicates/${d.id}/resolve`, { action: 'distinct' }); onDone() }, 'Marked as different events.')}>These are different events</button>
        <button className="btn btn-sm" disabled={s.busy} onClick={() => s.run(async () => { await api.post(`/admin/duplicates/${d.id}/resolve`, { action: 'merge', keep_event_id: d.a.id }); onDone() }, 'Merged, keeping the first.')}>Merge, keep the first</button>
        <button className="btn btn-sm" disabled={s.busy} onClick={() => s.run(async () => { await api.post(`/admin/duplicates/${d.id}/resolve`, { action: 'merge', keep_event_id: d.b.id }); onDone() }, 'Merged, keeping the second.')}>Merge, keep the second</button>
      </div>
      <FormStatus s={s} />
    </li>
  )
}

function DisputesAdmin() {
  useTitle('Disputes')
  const [status, setStatus] = useState('open')
  const state = useAsync((s) => api.get<{ items: Dispute[] }>('/disputes', { status }, s), [status])
  return (
    <>
      <PageHead title="Disputes and correction requests" lead="Raised by organizers. Resolving a claim dispute moves the promise out of the disputed state." />
      <div style={{ maxWidth: 240 }}><Select label="Status" value={status} onChange={(e) => setStatus(e.target.value)} options={[{ value: 'open', label: 'Open' }, { value: 'under_review', label: 'Under review' }, { value: 'upheld', label: 'Upheld' }, { value: 'rejected', label: 'Rejected' }]} /></div>
      <DataState state={state} loadingLabel="Loading disputes" isEmpty={(d) => d.items.length === 0} empty={<Empty title="No disputes with this status" />}>
        {(d) => <Panel><ul className="plain">{d.items.map((x) => <DisputeResolve key={x.id} d={x} onDone={state.reload} />)}</ul></Panel>}
      </DataState>
    </>
  )
}
function DisputeResolve({ d, onDone }: { d: Dispute; onDone: () => void }) {
  const [note, setNote] = useState(''); const [withdraw, setWithdraw] = useState(false); const s = useSubmit()
  const closed = ['upheld', 'rejected', 'withdrawn'].includes(d.status)
  const go = (outcome: string, ok: string) => s.run(async () => { await api.post(`/disputes/${d.id}/resolve`, { outcome, note, withdraw_claim: withdraw }); onDone() }, ok)
  return (
    <li>
      <div className="claim-top"><Badge tone="violet">{titleCase(d.kind)}</Badge><Badge tone="warn">{titleCase(d.status)}</Badge></div>
      <div className="small"><Link to={`/events/${d.event_id}#promises`}>{d.event_title ?? 'Event'}</Link> <span className="dim">{fmtDateTime(d.created_at)}</span></div>
      <p>{d.description}</p>
      {d.resolution_note && <p className="small muted">Resolution: {d.resolution_note}</p>}
      {!closed && (
        <>
          <TextField label="Resolution note (required)" value={note} onChange={(e) => setNote(e.target.value)} />
          {d.claim_id && <Check label="Withdraw the promise as part of this decision" checked={withdraw} onChange={(e) => setWithdraw(e.target.checked)} />}
          <div className="btn-row">
            <button className="btn btn-sm" disabled={s.busy || note.trim().length < 5} onClick={() => go('upheld', 'Dispute upheld.')}>Uphold dispute</button>
            <button className="btn btn-sm btn-danger" disabled={s.busy || note.trim().length < 5} onClick={() => go('rejected', 'Dispute rejected.')}>Reject dispute</button>
            <button className="btn btn-sm" disabled={s.busy || note.trim().length < 5} onClick={() => go('under_review', 'Marked under review.')}>Mark under review</button>
          </div>
          <FormStatus s={s} />
        </>
      )}
    </li>
  )
}

function UsersPage() {
  useTitle('Users and roles')
  const [q, setQ] = useState(''); const [role, setRole] = useState(''); const [page, setPage] = useState(1)
  const [applied, setApplied] = useState({ q: '', role: '' })
  const state = useAsync((s) => api.get<Paged<AdminUser>>('/admin/users', { q: applied.q, role: applied.role, page, page_size: 25 }, s), [applied.q, applied.role, page])
  const orgs = useAsync((s) => api.get<{ items: Org[] }>('/admin/orgs', undefined, s), [])
  return (
    <>
      <PageHead title="Users and roles" lead="Changing a role signs that person out so the new permissions apply on next sign-in." />
      <form className="inline-form" onSubmit={(e) => { e.preventDefault(); setApplied({ q, role }); setPage(1) }} role="search">
        <TextField label="Search name or email" value={q} onChange={(e) => setQ(e.target.value)} />
        <Select label="Role" value={role} onChange={(e) => setRole(e.target.value)} placeholder="Any role" options={['student', 'organizer', 'reviewer', 'admin'].map((r) => ({ value: r, label: titleCase(r) }))} />
        <button className="btn">Search</button>
      </form>
      <DataState state={state} loadingLabel="Loading users" isEmpty={(d) => d.items.length === 0} empty={<Empty title="No users match" />}>
        {(d) => (
          <>
            <p className="small muted" style={{ marginTop: 12 }}>{d.total} users</p>
            <div className="panel table-wrap"><table>
              <thead><tr><th scope="col">User</th><th scope="col">Role</th><th scope="col">Active</th><th scope="col">Last sign-in</th></tr></thead>
              <tbody>{d.items.map((u) => <UserRow key={u.id} u={u} onDone={state.reload} />)}</tbody>
            </table></div>
            <Pagination page={page} pageSize={d.page_size} total={d.total} onPage={setPage} />
          </>
        )}
      </DataState>
      <Panel title="Organizations and members">
        <DataState state={orgs} loadingLabel="Loading organizations" isEmpty={(d) => d.items.length === 0} empty={<p className="muted">No organizations yet.</p>}>
          {(d) => <ul className="plain">{d.items.map((o) => <OrgRow key={o.id} o={o} onDone={orgs.reload} />)}</ul>}
        </DataState>
      </Panel>
    </>
  )
}
function UserRow({ u, onDone }: { u: AdminUser; onDone: () => void }) {
  const s = useSubmit()
  return (
    <tr>
      <td>{u.display_name}<div className="small muted">{u.email}</div><FormStatus s={s} /></td>
      <td><label className="sr-only" htmlFor={`role-${u.id}`}>Role for {u.email}</label>
        <select id={`role-${u.id}`} value={u.role} disabled={s.busy} onChange={(e) => s.run(async () => { await api.patch(`/admin/users/${u.id}`, { role: e.target.value }); onDone() }, 'Role updated.')}>
          {['student', 'organizer', 'reviewer', 'admin'].map((r) => <option key={r} value={r}>{titleCase(r)}</option>)}</select></td>
      <td><button className="btn btn-sm" disabled={s.busy} onClick={() => s.run(async () => { await api.patch(`/admin/users/${u.id}`, { is_active: !u.is_active }); onDone() }, u.is_active ? 'Deactivated.' : 'Reactivated.')}>{u.is_active ? 'Deactivate' : 'Reactivate'}</button></td>
      <td className="small">{u.last_login_at ? fmtDateTime(u.last_login_at) : 'Never'}</td>
    </tr>
  )
}
function OrgRow({ o, onDone }: { o: Org; onDone: () => void }) {
  const [email, setEmail] = useState(''); const s = useSubmit()
  return (
    <li><strong>{o.name}</strong> <span className="small muted">{(o.members ?? []).length ? (o.members ?? []).join(', ') : 'No members'}</span>
      <div className="inline-form"><TextField label="Add member by email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} />
        <button className="btn btn-sm" disabled={s.busy || !email} onClick={async () => { const r = await s.run(() => api.post(`/admin/orgs/${o.id}/members`, { email }), 'Member added.'); if (r !== undefined) { setEmail(''); onDone() } }}>Add member</button></div><FormStatus s={s} /></li>
  )
}

function AuditPage() {
  useTitle('Audit logs')
  const [f, setF] = useState({ action: '', actor_role: '', target_type: '' }); const [applied, setApplied] = useState(f); const [page, setPage] = useState(1)
  const state = useAsync((s) => api.get<Paged<AuditLog>>('/admin/audit-logs', { ...applied, page, page_size: 50 }, s), [applied, page])
  return (
    <>
      <PageHead title="Audit logs" lead="Every sensitive action, newest first." />
      <form className="inline-form" onSubmit={(e) => { e.preventDefault(); setApplied(f); setPage(1) }}>
        <TextField label="Action starts with" value={f.action} onChange={(e) => setF({ ...f, action: e.target.value })} placeholder="e.g. user." />
        <Select label="Actor role" value={f.actor_role} onChange={(e) => setF({ ...f, actor_role: e.target.value })} placeholder="Any" options={['student', 'organizer', 'reviewer', 'admin'].map((r) => ({ value: r, label: titleCase(r) }))} />
        <TextField label="Target type" value={f.target_type} onChange={(e) => setF({ ...f, target_type: e.target.value })} placeholder="e.g. event" />
        <button className="btn">Filter</button>
      </form>
      <DataState state={state} loadingLabel="Loading audit logs" isEmpty={(d) => d.items.length === 0} empty={<Empty title="No log entries match" />}>
        {(d) => (
          <>
            <p className="small muted" style={{ marginTop: 12 }}>{d.total.toLocaleString('en-IN')} entries</p>
            <div className="panel table-wrap"><table>
              <thead><tr><th scope="col">When</th><th scope="col">Actor</th><th scope="col">Action</th><th scope="col">Target</th><th scope="col">Details</th></tr></thead>
              <tbody>{d.items.map((a) => <tr key={a.id}><td className="small">{fmtDateTime(a.at)}</td><td>{a.actor_role ?? 'system'}</td><td>{a.action}</td><td className="small">{a.target_type}{a.target_id ? ` ${a.target_id.slice(0, 8)}` : ''}</td><td className="small"><code>{a.details ? JSON.stringify(a.details).slice(0, 160) : ''}</code></td></tr>)}</tbody>
            </table></div>
            <Pagination page={page} pageSize={d.page_size} total={d.total} onPage={setPage} />
          </>
        )}
      </DataState>
    </>
  )
}

function ConfigPage() {
  useTitle('System configuration')
  const state = useAsync((s) => api.get<Config>('/admin/config', undefined, s), [])
  return (
    <>
      <PageHead title="System configuration" lead="Policy values that change how freshness, evidence and recommendations work. Every change is audited." />
      <DataState state={state} loadingLabel="Loading configuration">{(c) => <ConfigForm c={c} reload={state.reload} />}</DataState>
    </>
  )
}
function ConfigForm({ c, reload }: { c: Config; reload: () => void }) {
  const [v, setV] = useState({ stale_after_days: String(c.effective.stale_after_days), participant_threshold: String(c.effective.participant_threshold), unverified_grace_days: String(c.effective.unverified_grace_days), min_outcome_responses: String(c.effective.min_outcome_responses) })
  const [w, setW] = useState<Record<string, string>>(Object.fromEntries(Object.entries(c.effective.scoring_weights).map(([k, x]) => [k, String(Math.round(x * 1000) / 10)])))
  const s = useSubmit(); const r = useSubmit()
  const total = Object.values(w).reduce((a, b) => a + (Number(b) || 0), 0)
  return (
    <>
      <Panel title="Environment (read-only)">
        <dl className="kv"><div><dt>Environment</dt><dd>{c.environment.env}</dd></div><div><dt>AI provider configured</dt><dd>{c.environment.llm_provider_configured ? 'Yes' : 'No (rule-based extraction is used)'}</dd></div>
          <div><dt>Scheduler</dt><dd>{c.environment.scheduler_enabled ? `On, every ${c.environment.sync_interval_hours} h` : 'Off'}</dd></div><div><dt>Upload limit</dt><dd>{c.environment.max_upload_mb} MB</dd></div></dl>
      </Panel>
      <form className="panel" onSubmit={async (e) => { e.preventDefault(); const x = await s.run(() => api.put('/admin/config', {
        stale_after_days: Number(v.stale_after_days), participant_threshold: Number(v.participant_threshold), unverified_grace_days: Number(v.unverified_grace_days), min_outcome_responses: Number(v.min_outcome_responses),
        scoring_weights: Object.fromEntries(Object.entries(w).map(([k, x]) => [k, Number(x) || 0])) }), 'Configuration saved. Weights are normalised to sum to 100%.'); if (x !== undefined) reload() }}>
        <h2>Policy</h2>
        <div className="form-grid">
          <TextField label="Mark data stale after (days)" type="number" min={1} max={365} value={v.stale_after_days} onChange={(e) => setV({ ...v, stale_after_days: e.target.value })} hint={`Default ${c.defaults.stale_after_days}`} />
          <TextField label="Participant confirmations needed" type="number" min={1} max={100} value={v.participant_threshold} onChange={(e) => setV({ ...v, participant_threshold: e.target.value })} hint={`Default ${c.defaults.participant_threshold}`} />
          <TextField label="Days before a promise may be marked unverified" type="number" min={1} max={365} value={v.unverified_grace_days} onChange={(e) => setV({ ...v, unverified_grace_days: e.target.value })} hint={`Default ${c.defaults.unverified_grace_days}`} />
          <TextField label="Published responses needed for an outcome verdict" type="number" min={1} max={100} value={v.min_outcome_responses} onChange={(e) => setV({ ...v, min_outcome_responses: e.target.value })} hint={`Default ${c.defaults.min_outcome_responses}`} />
        </div>
        <h2>Recommendation weights</h2>
        <div className="form-grid">{Object.keys(w).map((k) => <TextField key={k} label={`${titleCase(c.weight_labels[k] ?? k)} (%)`} type="number" min={0} step="0.5" value={w[k]} onChange={(e) => setW({ ...w, [k]: e.target.value })} />)}</div>
        <p className="small muted">Entered total: {Math.round(total * 10) / 10}%. Values are rescaled to sum to 100%.</p>
        <button className="btn btn-primary" disabled={s.busy || total <= 0}>Save configuration</button><FormStatus s={s} />
      </form>
      <Panel title="Reset to defaults"><button className="btn btn-danger" disabled={r.busy} onClick={async () => { const x = await r.run(() => api.del('/admin/config'), 'Reset to defaults.'); if (x !== undefined) reload() }}>Reset configuration</button><FormStatus s={r} /></Panel>
    </>
  )
}
