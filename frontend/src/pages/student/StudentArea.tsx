import { useEffect, useState, type FormEvent } from 'react'
import { Link, Route, Routes, useNavigate, useParams } from 'react-router-dom'
import { ApiError, api, setToken } from '../../api/client'
import { useAuth } from '../../auth/AuthContext'
import type { Dashboard, FeedbackForm, Participation, Profile, Recommendations, RecItem, SavedItem, TokenResponse } from '../../api/types'
import { EventCardView } from '../../components/EventCard'
import { DataState, Empty, Notice } from '../../components/States'
import { Badge, Check, FeeBadge, FormStatus, PageHead, Panel, Select, Tabs, TextArea, TextField, Unknown, useSubmit } from '../../components/ui'
import { ScoreBreakdown } from '../EventDetail'
import { fmtDateRange, fmtDateTime, fmtDeadline } from '../../lib/format'
import { FEEDBACK_RESPONSE, titleCase } from '../../lib/labels'
import { useAsync, useTitle } from '../../lib/useAsync'

export default function StudentArea() {
  return (
    <div className="wrap page">
      <Tabs items={[
        { to: '/me', label: 'Dashboard', end: true }, { to: '/me/recommendations', label: 'Recommendations' }, { to: '/me/saved', label: 'Saved' },
        { to: '/me/deadlines', label: 'Deadlines' }, { to: '/me/comparisons', label: 'Comparisons' }, { to: '/me/feedback', label: 'Feedback' },
        { to: '/me/profile', label: 'Preferences' }, { to: '/me/account', label: 'Account' },
      ]} />
      <Routes>
        <Route index element={<DashboardPage />} />
        <Route path="profile" element={<ProfilePage />} />
        <Route path="saved" element={<SavedPage />} />
        <Route path="deadlines" element={<DeadlinesPage />} />
        <Route path="recommendations" element={<RecommendationsPage />} />
        <Route path="comparisons" element={<ComparisonsPage />} />
        <Route path="feedback" element={<FeedbackList />} />
        <Route path="feedback/:id" element={<FeedbackFormPage />} />
        <Route path="account" element={<AccountPage />} />
        <Route path="*" element={<Empty title="Page not found" />} />
      </Routes>
    </div>
  )
}

type DashboardData = Dashboard & { recommendationsUnavailable?: string }

/** Falls back to the saved/deadline/participation endpoints if the combined dashboard endpoint fails with a server error. */
async function loadDashboard(signal: AbortSignal): Promise<DashboardData> {
  try {
    return await api.get<Dashboard>('/me/dashboard', undefined, signal)
  } catch (e) {
    if (!(e instanceof ApiError) || e.status < 500) throw e
    const [saved, parts] = await Promise.all([
      api.get<{ items: SavedItem[] }>('/me/saved', undefined, signal),
      api.get<{ items: Participation[] }>('/me/participations', undefined, signal),
    ])
    const now = Date.now()
    return {
      has_profile: true, recommendations: [], recommendation_summary: { considered: 0, excluded: 0 }, saved_count: saved.items.length,
      upcoming_deadlines: saved.items.filter((i) => i.registration_deadline && new Date(i.registration_deadline).getTime() >= now)
        .sort((a, b) => (a.registration_deadline as string).localeCompare(b.registration_deadline as string)).slice(0, 5),
      changed_saved: saved.items.filter((i) => i.changes_since_saved.length > 0).slice(0, 5),
      pending_feedback: parts.items.filter((p) => p.event_ended && p.feedback_items_submitted === 0), participations: parts.items.slice(0, 5),
      recommendationsUnavailable: e.message,
    }
  }
}

function DashboardPage() {
  useTitle('My workspace')
  const { user } = useAuth()
  const state = useAsync((s) => loadDashboard(s), [])
  return (
    <>
      <PageHead title={`Welcome, ${user?.display_name ?? ''}`} lead="Your saved events, upcoming deadlines and recommendations in one place." />
      <DataState state={state} loadingLabel="Loading your dashboard">
        {(d) => (
          <>
            {d.recommendationsUnavailable && <Notice tone="warn"><strong>Recommendations are unavailable right now.</strong> The server could not build them ({d.recommendationsUnavailable}). Your saved events and deadlines below are unaffected.</Notice>}
            {!d.has_profile && <Notice tone="info"><strong>Set your preferences to get recommendations.</strong> Without them you can still search, compare and save. <Link to="/me/profile">Set preferences</Link></Notice>}
            <div className="cols-2">
              <Panel title="Upcoming deadlines" actions={<Link to="/me/deadlines" className="small">All deadlines</Link>}>
                {d.upcoming_deadlines.length === 0 ? <p className="muted">None of your {d.saved_count} saved events states an upcoming deadline. <Link to="/discover">Find events</Link></p> : (
                  <div className="mini-list">{d.upcoming_deadlines.map((e) => (
                    <div className="mini" key={e.id}><div><Link to={`/events/${e.id}`}>{e.title}</Link><div className="small muted">{fmtDeadline(e.registration_deadline)}</div></div><Badge tone="warn">{e.days_left !== undefined ? `${e.days_left} days left` : 'Upcoming'}</Badge></div>
                  ))}</div>
                )}
              </Panel>
              <Panel title="Saved events that changed" actions={<Link to="/me/saved" className="small">All saved ({d.saved_count})</Link>}>
                {d.changed_saved.length === 0 ? <p className="muted">No saved event has changed since you saved it.</p> : (
                  <div className="mini-list">{d.changed_saved.map((e) => (
                    <div className="mini" key={e.id}><div><Link to={`/events/${e.id}`}>{e.title}</Link><div className="small muted">{e.changes_since_saved.length} change(s)</div></div>{e.material_change && <Badge tone="warn">Material change</Badge>}</div>
                  ))}</div>
                )}
              </Panel>
            </div>
            {d.pending_feedback.length > 0 && (
              <Notice tone="warn"><strong>Feedback waiting:</strong> {d.pending_feedback.map((p) => <span key={p.event_id}><Link to={`/me/feedback/${p.event_id}`}>{p.title}</Link> </span>)}ended and you have not answered yet.</Notice>
            )}
            <Panel title="Top recommendations" actions={<Link to="/me/recommendations" className="small">See all with score breakdowns</Link>}>
              {d.recommendationsUnavailable ? <p className="muted">Unavailable right now. Try again later.</p> : d.has_profile ? (
                d.recommendations.length === 0 ? <p className="muted">Nothing rated yet. {d.recommendation_summary.considered} events were considered and {d.recommendation_summary.excluded} were excluded by your constraints.</p> : (
                  <div className="mini-list">{d.recommendations.map((r) => (
                    <div className="mini" key={r.id}><div><Link to={`/events/${r.id}`}>{r.title}</Link><div className="small muted">{fmtDateRange(r.start_date, r.end_date)} {'·'} {r.fit?.label}</div></div><Badge tone="info">{r.fit?.score ?? '?'}/100</Badge></div>
                  ))}</div>
                )
              ) : <p className="muted">Recommendations appear after you set preferences.</p>}
            </Panel>
          </>
        )}
      </DataState>
    </>
  )
}

const csv = (s: string) => s.split(',').map((x) => x.trim()).filter(Boolean)

function ProfilePage() {
  useTitle('Preferences')
  const state = useAsync((s) => api.get<{ profile: Profile | null; data_use: string }>('/me/profile', undefined, s), [])
  return (
    <>
      <PageHead title="Your preferences" lead="Used to rank and explain events for you. All fields are optional." />
      <DataState state={state} loadingLabel="Loading your preferences">
        {(d) => <ProfileForm initial={d.profile} dataUse={d.data_use} onChanged={state.reload} />}
      </DataState>
    </>
  )
}

function ProfileForm({ initial, dataUse, onChanged }: { initial: Profile | null; dataUse: string; onChanged: () => void }) {
  const { refresh } = useAuth()
  const [f, setF] = useState(() => ({
    education_level: initial?.education_level ?? '', year_of_study: String(initial?.year_of_study ?? ''), institution: initial?.institution ?? '',
    interests: (initial?.interests ?? []).join(', '), skill_level: initial?.skill_level ?? '', learning_goals: initial?.learning_goals ?? '',
    career_goals: initial?.career_goals ?? '', available_from: initial?.available_from ?? '', available_to: initial?.available_to ?? '',
    max_budget_inr: String(initial?.max_budget_inr ?? ''), preferred_formats: initial?.preferred_formats ?? [], require_format: initial?.require_format ?? false,
    home_city: initial?.home_city ?? '', max_travel_km: String(initial?.max_travel_km ?? ''), accessibility_needs: (initial?.accessibility_needs ?? []).join(', '),
    preferred_duration_days_max: String(initial?.preferred_duration_days_max ?? ''), team_preference: initial?.team_preference ?? '',
  }))
  const s = useSubmit(); const del = useSubmit()
  const [confirm, setConfirm] = useState(false)
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value })
  const num = (v: string) => (v.trim() === '' ? null : Number(v))
  const dateErr = f.available_from && f.available_to && f.available_to < f.available_from ? 'The end date cannot be before the start date.' : null
  const submit = async (e: FormEvent) => {
    e.preventDefault()
    const body = {
      education_level: f.education_level || null, year_of_study: num(f.year_of_study), institution: f.institution || null, interests: csv(f.interests),
      skill_level: f.skill_level || null, learning_goals: f.learning_goals || null, career_goals: f.career_goals || null,
      available_from: f.available_from || null, available_to: f.available_to || null, max_budget_inr: num(f.max_budget_inr),
      preferred_formats: f.preferred_formats, require_format: f.require_format, home_city: f.home_city || null, max_travel_km: num(f.max_travel_km),
      accessibility_needs: csv(f.accessibility_needs), preferred_duration_days_max: num(f.preferred_duration_days_max), team_preference: f.team_preference || null,
    }
    const r = await s.run(() => api.put('/me/profile', body), 'Preferences saved.')
    if (r !== undefined) { onChanged(); void refresh() }
  }
  const toggleFmt = (v: string) => setF({ ...f, preferred_formats: f.preferred_formats.includes(v) ? f.preferred_formats.filter((x) => x !== v) : [...f.preferred_formats, v] })
  return (
    <>
      <Notice tone="info" live={false}><strong>How your data is used.</strong> {dataUse}</Notice>
      <form className="panel" onSubmit={submit}>
        <div className="form-grid">
          <Select label="Education level" value={f.education_level} onChange={set('education_level')} placeholder="Not set" options={['diploma', 'undergraduate', 'postgraduate', 'other'].map((v) => ({ value: v, label: titleCase(v) }))} />
          <TextField label="Year of study" type="number" min={1} max={8} value={f.year_of_study} onChange={set('year_of_study')} />
          <TextField label="Institution" value={f.institution} onChange={set('institution')} />
          <Select label="Skill level" value={f.skill_level} onChange={set('skill_level')} placeholder="Not set" options={['beginner', 'intermediate', 'advanced'].map((v) => ({ value: v, label: titleCase(v) }))} />
        </div>
        <TextField label="Interests" value={f.interests} onChange={set('interests')} hint="Separate with commas, for example: AI, web development, cybersecurity." />
        <div className="form-grid">
          <TextArea label="Learning goals" rows={3} value={f.learning_goals} onChange={set('learning_goals')} />
          <TextArea label="Career goals" rows={3} value={f.career_goals} onChange={set('career_goals')} />
        </div>
        <div className="form-grid">
          <TextField label="Available from" type="date" value={f.available_from} onChange={set('available_from')} />
          <TextField label="Available until" type="date" value={f.available_to} onChange={set('available_to')} error={dateErr} />
          <TextField label="Maximum budget (INR)" type="number" min={0} value={f.max_budget_inr} onChange={set('max_budget_inr')} hint="Events with an unstated fee are never excluded by budget; they are flagged instead." />
          <TextField label="Longest event you can attend (days)" type="number" min={1} value={f.preferred_duration_days_max} onChange={set('preferred_duration_days_max')} />
          <TextField label="Home city" value={f.home_city} onChange={set('home_city')} />
          <TextField label="Maximum travel (km)" type="number" min={0} value={f.max_travel_km} onChange={set('max_travel_km')} hint="Straight-line distance from your home city." />
          <Select label="Team preference" value={f.team_preference} onChange={set('team_preference')} placeholder="Not set" options={['individual', 'team', 'either'].map((v) => ({ value: v, label: titleCase(v) }))} />
        </div>
        <fieldset><legend>Preferred formats</legend>
          {['online', 'offline', 'hybrid'].map((v) => <Check key={v} label={titleCase(v)} checked={f.preferred_formats.includes(v)} onChange={() => toggleFmt(v)} />)}
          <Check label="Only show me these formats (a hard requirement)" checked={f.require_format} onChange={(e) => setF({ ...f, require_format: e.target.checked })} />
        </fieldset>
        <TextField label="Accessibility needs" value={f.accessibility_needs} onChange={set('accessibility_needs')} hint="Separate with commas, for example: step-free entry, captioning." />
        <div className="btn-row"><button className="btn btn-primary" disabled={s.busy || !!dateErr}>Save preferences</button></div>
        <FormStatus s={s} />
      </form>
      {initial && (
        <Panel title="Delete your preferences">
          <p className="muted">Removes your whole preference profile. Recommendations stop until you set preferences again. Your account and saved events stay.</p>
          {!confirm ? <button className="btn btn-danger" onClick={() => setConfirm(true)}>Delete preferences</button> : (
            <div className="btn-row"><button className="btn btn-danger" disabled={del.busy} onClick={async () => { const r = await del.run(() => api.del('/me/profile'), 'Preferences deleted.'); if (r !== undefined) { onChanged(); void refresh() } }}>Yes, delete my preferences</button><button className="btn" onClick={() => setConfirm(false)}>Cancel</button></div>
          )}
          <FormStatus s={del} />
        </Panel>
      )}
    </>
  )
}

function SavedRow({ e, onChanged }: { e: SavedItem; onChanged: () => void }) {
  const [note, setNote] = useState(e.note ?? '')
  const s = useSubmit()
  return (
    <div>
      <EventCardView e={e} onSavedChange={() => onChanged()} />
      <div className="panel" style={{ marginTop: -6, borderTopLeftRadius: 0, borderTopRightRadius: 0 }}>
        <p className="small muted">Saved {fmtDateTime(e.saved_at)}</p>
        {e.changes_since_saved.length > 0 && (
          <Notice tone={e.material_change ? 'warn' : 'info'}><strong>{e.changes_since_saved.length} change(s) since you saved this.</strong>
            <ul className="bullets small">{e.changes_since_saved.map((c) => <li key={c.version_no}>{c.is_material && <Badge tone="warn">Material</Badge>} {c.summary ?? `Version ${c.version_no}`} <span className="dim">({fmtDateTime(c.changed_at)})</span></li>)}</ul>
            <button className="btn btn-sm" onClick={() => s.run(async () => { await api.post(`/me/saved/${e.id}/seen`); onChanged() }, 'Marked as seen.')}>Mark as seen</button></Notice>
        )}
        <div className="inline-form">
          <TextField label="Private note" value={note} onChange={(x) => setNote(x.target.value)} maxLength={1000} />
          <button className="btn btn-sm" disabled={s.busy} onClick={() => s.run(() => api.put(`/me/saved/${e.id}`, { note: note || null }), 'Note saved.')}>Save note</button>
        </div>
        <FormStatus s={s} />
      </div>
    </div>
  )
}

function SavedPage() {
  useTitle('Saved events')
  const state = useAsync((s) => api.get<{ items: SavedItem[]; total: number }>('/me/saved', undefined, s), [])
  return (
    <>
      <PageHead title="Saved events" />
      <DataState state={state} loadingLabel="Loading saved events" isEmpty={(d) => d.items.length === 0} empty={<Empty title="Nothing saved yet" action={<Link className="btn btn-primary" to="/discover">Discover events</Link>}>Use Save on any event to keep it here and be told when it changes.</Empty>}>
        {(d) => <div className="results">{d.items.map((e) => <SavedRow key={e.id} e={e} onChanged={state.reload} />)}</div>}
      </DataState>
    </>
  )
}

function DeadlineList({ title, items, empty }: { title: string; items: SavedItem[]; empty: string }) {
  return (
    <Panel title={`${title} (${items.length})`}>
      {items.length === 0 ? <p className="muted">{empty}</p> : (
        <div className="mini-list">{items.map((e) => (
          <div className="mini" key={e.id}><div><Link to={`/events/${e.id}`}>{e.title}</Link><div className="small muted">{e.registration_deadline ? fmtDeadline(e.registration_deadline) : <Unknown>No deadline stated</Unknown>} {'·'} <FeeBadge fee={e.fee} /></div></div>
            {e.days_left !== undefined && <Badge tone={e.days_left <= 3 ? 'bad' : 'warn'}>{e.days_left} days left</Badge>}</div>
        ))}</div>
      )}
    </Panel>
  )
}
function DeadlinesPage() {
  useTitle('Upcoming deadlines')
  const state = useAsync((s) => api.get<{ upcoming: SavedItem[]; no_deadline_stated: SavedItem[]; closed: SavedItem[]; note: string }>('/me/deadlines', undefined, s), [])
  return (
    <>
      <PageHead title="Upcoming deadlines" lead="Only events that state a registration deadline are counted down." />
      <DataState state={state} loadingLabel="Loading deadlines">
        {(d) => (
          <>
            {d.upcoming.length + d.no_deadline_stated.length + d.closed.length === 0 && <Empty title="No saved events" action={<Link className="btn btn-primary" to="/discover">Discover events</Link>}>Save events to track their deadlines here.</Empty>}
            <DeadlineList title="Upcoming" items={d.upcoming} empty="No saved event has an upcoming stated deadline." />
            <DeadlineList title="No deadline stated" items={d.no_deadline_stated} empty="Every saved event states a deadline." />
            <DeadlineList title="Closed" items={d.closed} empty="No saved event has a closed deadline." />
            <p className="small muted">{d.note}</p>
          </>
        )}
      </DataState>
    </>
  )
}

function RecCard({ r, onHidden }: { r: RecItem; onHidden: () => void }) {
  const s = useSubmit()
  const [reason, setReason] = useState('')
  const [voted, setVoted] = useState<string | null>(null)
  const vote = async (v: 'helpful' | 'not_relevant' | 'hide') => {
    const x = await s.run(() => api.post<{ effect: string }>('/me/recommendation-feedback', { event_id: r.id, vote: v, reason: reason || null }), 'Feedback saved.')
    if (x) { setVoted(v); if (v !== 'helpful') onHidden() }
  }
  return (
    <div>
      <EventCardView e={r} />
      <div className="panel" style={{ marginTop: -6 }}>
        <h3>Why this ranks #{r.rank}</h3>
        {r.fit && <p><strong>{r.fit.label}</strong> {'—'} {r.fit.score}/100 using {Math.round(r.fit.coverage * 100)}% of the factors.</p>}
        {r.why_match.length > 0 && <><h4>Why it matches</h4><ul className="bullets">{r.why_match.map((w) => <li key={w}>{w}</li>)}</ul></>}
        {r.why_skip.length > 0 && <><h4>Why you might skip it</h4><ul className="bullets">{r.why_skip.map((w) => <li key={w}>{w}</li>)}</ul></>}
        {r.tradeoffs.length > 0 && <><h4>Trade-offs</h4><ul className="bullets">{r.tradeoffs.map((w) => <li key={w}>{w}</li>)}</ul></>}
        {r.fit && r.fit.hard_violations.length > 0 && <Notice tone="bad"><strong>Hard-constraint failures:</strong> {r.fit.hard_violations.map((v) => v.message).join(' ')}</Notice>}
        {r.warnings.length > 0 && <Notice tone="warn"><strong>Check before you go:</strong><ul className="bullets small">{r.warnings.map((w) => <li key={w}>{w}</li>)}</ul></Notice>}
        {r.fit && <details><summary>Score breakdown and weights</summary><ScoreBreakdown fit={r.fit} /></details>}
        {r.alternatives.length > 0 && <p className="small"><strong>Similar:</strong> {r.alternatives.map((a) => <span key={a.id}><Link to={`/events/${a.id}`}>{a.title}</Link> ({a.score ?? '?'}/100) </span>)}</p>}
        <div className="inline-form" style={{ marginTop: 10 }}>
          <TextField label="Tell us why (optional)" value={reason} onChange={(e) => setReason(e.target.value)} maxLength={500} />
          <button className="btn btn-sm" disabled={s.busy} onClick={() => vote('helpful')}>Helpful</button>
          <button className="btn btn-sm" disabled={s.busy} onClick={() => vote('not_relevant')}>Not relevant</button>
          <button className="btn btn-sm btn-danger" disabled={s.busy} onClick={() => vote('hide')}>Hide</button>
        </div>
        <FormStatus s={s} />
        {voted && voted !== 'helpful' && <p className="small muted">This event will not be recommended again.</p>}
      </div>
    </div>
  )
}

function RecommendationsPage() {
  useTitle('Recommendations')
  const state = useAsync((s) => api.get<Recommendations>('/me/recommendations', { limit: 20 }, s), [])
  return (
    <>
      <PageHead title="Recommendations" lead="Ranked by a weighted preference match. Hard constraints exclude events; unknown factors are left out, not guessed." />
      <DataState state={state} loadingLabel="Scoring events against your preferences">
        {(d) => d.needs_profile ? (
          <Empty title="Set your preferences first" action={<Link className="btn btn-primary" to="/me/profile">Set preferences</Link>}>{d.message}</Empty>
        ) : (
          <>
            <Panel title="How this was decided">
              <p>{d.method}</p>
              <p className="small muted">{d.considered} events considered, {d.eligible} eligible, {d.excluded.count} excluded by your constraints, {d.not_rated} without enough information to rate.</p>
              {d.weights && <p className="small">Weights: {Object.entries(d.weights).map(([k, v]) => `${titleCase(k)} ${Math.round(v * 100)}%`).join(', ')}</p>}
              {d.excluded.count > 0 && (
                <details><summary>{d.excluded.count} events excluded</summary>
                  <ul className="bullets small">{d.excluded.reasons.map((r) => <li key={r.key}>{r.label}: {r.count}</li>)}</ul>
                  {d.excluded.examples.length > 0 && <><p className="small"><strong>Examples:</strong></p><ul className="bullets small">{d.excluded.examples.map((x) => <li key={x.id}><Link to={`/events/${x.id}`}>{x.title}</Link>: {x.why.join(' ')}</li>)}</ul></>}
                </details>
              )}
            </Panel>
            {d.items.length === 0 ? <Empty title="No rated recommendations yet">No eligible event has enough known information to rate. Try adding interests, or <Link to="/discover">search directly</Link>.</Empty> : (
              <div className="results">{d.items.map((r) => <RecCard key={r.id} r={r} onHidden={() => undefined} />)}</div>
            )}
          </>
        )}
      </DataState>
    </>
  )
}

function ComparisonsPage() {
  useTitle('Comparison history')
  const state = useAsync((s) => api.get<{ items: { id: string; created_at: string; events: { id: string; title: string }[] }[] }>('/me/comparisons', undefined, s), [])
  return (
    <>
      <PageHead title="Comparison history" />
      <DataState state={state} loadingLabel="Loading history" isEmpty={(d) => d.items.length === 0} empty={<Empty title="No comparisons yet" action={<Link className="btn btn-primary" to="/discover">Find events to compare</Link>}>Comparisons you run while signed in are kept here.</Empty>}>
        {(d) => (
          <Panel>
            <div className="mini-list">{d.items.map((c) => (
              <div className="mini" key={c.id}><div><strong>{c.events.map((e) => e.title).join(' vs ')}</strong><div className="small muted">{fmtDateTime(c.created_at)}</div></div>
                <Link className="btn btn-sm" to={`/compare?ids=${c.events.map((e) => e.id).join(',')}`}>Open again</Link></div>
            ))}</div>
          </Panel>
        )}
      </DataState>
    </>
  )
}

function FeedbackList() {
  useTitle('Feedback')
  const state = useAsync((s) => api.get<{ items: Participation[] }>('/me/participations', undefined, s), [])
  return (
    <>
      <PageHead title="Post-event feedback" lead="Tell others whether each promise was kept. Your name is never shown, and a moderator checks answers before they are published." />
      <DataState state={state} loadingLabel="Loading your events" isEmpty={(d) => d.items.length === 0} empty={<Empty title="No events yet" action={<Link className="btn" to="/discover">Discover events</Link>}>Open an event that has started and choose {'“'}I took part in this event{'”'}. It will appear here, and feedback opens once the event ends.</Empty>}>
        {(d) => (
          <Panel><div className="mini-list">{d.items.map((p) => (
            <div className="mini" key={p.event_id}>
              <div><Link to={`/events/${p.event_id}`}>{p.title}</Link><div className="small muted">{fmtDateRange(p.start_date, p.end_date)} {'·'} {titleCase(p.level)}</div></div>
              {p.event_ended ? <Link className="btn btn-sm btn-primary" to={`/me/feedback/${p.event_id}`}>{p.feedback_items_submitted ? `Answered ${p.feedback_items_submitted}. Review` : 'Give feedback'}</Link> : <Badge tone="unknown">Opens when the event ends</Badge>}
            </div>
          ))}</div></Panel>
        )}
      </DataState>
    </>
  )
}

function FeedbackFormPage() {
  const { id = '' } = useParams()
  const state = useAsync((s) => api.get<FeedbackForm>(`/events/${id}/feedback-form`, undefined, s), [id])
  return (
    <DataState state={state} loadingLabel="Loading the feedback form">
      {(f) => <FeedbackFormBody f={f} id={id} reload={state.reload} />}
    </DataState>
  )
}
function FeedbackFormBody({ f, id, reload }: { f: FeedbackForm; id: string; reload: () => void }) {
  useTitle(`Feedback: ${f.event.title}`)
  const [answers, setAnswers] = useState<Record<string, { response: string; comment: string; evidence_url: string }>>({})
  const s = useSubmit()
  const [result, setResult] = useState<{ saved: number; skipped: { claim_id: string; reason: string }[]; note: string } | null>(null)
  const set = (cid: string, k: 'response' | 'comment' | 'evidence_url', v: string) => setAnswers((a) => ({ ...a, [cid]: { ...(a[cid] ?? { response: '', comment: '', evidence_url: '' }), [k]: v } }))
  const items = f.claims.filter((c) => !c.answered && answers[c.id]?.response)
  const submit = async (e: FormEvent) => {
    e.preventDefault()
    const r = await s.run(() => api.post<{ saved: number; skipped: { claim_id: string; reason: string }[]; note: string }>(`/events/${id}/feedback`, {
      items: items.map((c) => ({ claim_id: c.id, response: answers[c.id].response, comment: answers[c.id].comment || null, evidence_url: answers[c.id].evidence_url || null })),
    }), 'Feedback submitted.')
    if (r) { setResult(r); setAnswers({}); reload() }
  }
  return (
    <>
      <PageHead title={`Feedback: ${f.event.title}`} lead="For each promise, say what you experienced." />
      {!f.participation && <Notice tone="warn">You have not declared that you took part. <Link to={`/events/${id}#participate`}>Declare participation on the event page</Link> first.</Notice>}
      {f.participation && !f.event.ended && <Notice tone="info">Feedback opens once the event has ended.</Notice>}
      {result && <Notice tone="good">{result.saved} answer(s) saved. {result.note}{result.skipped.length > 0 && <ul className="bullets small">{result.skipped.map((x) => <li key={x.claim_id}>{x.reason}</li>)}</ul>}</Notice>}
      {f.claims.length === 0 ? <Empty title="No promises to report on">This event has no recorded promises, so there is nothing to answer.</Empty> : (
        <form onSubmit={submit}>
          {f.claims.map((c) => (
            <div className="panel" key={c.id}>
              <blockquote className="quote" style={{ margin: 0 }}>{'“'}{c.text}{'”'}</blockquote>
              {c.answered ? <p className="msg-good">You answered this already.</p> : (
                <>
                  <Select label="What happened?" value={answers[c.id]?.response ?? ''} onChange={(e) => set(c.id, 'response', e.target.value)} placeholder="Skip this one" disabled={!f.can_submit}
                    options={Object.entries(FEEDBACK_RESPONSE).map(([v, l]) => ({ value: v, label: l }))} />
                  <TextArea label="Comment (optional)" rows={2} value={answers[c.id]?.comment ?? ''} onChange={(e) => set(c.id, 'comment', e.target.value)} disabled={!f.can_submit} />
                  <TextField label="Link to evidence (optional)" type="url" value={answers[c.id]?.evidence_url ?? ''} onChange={(e) => set(c.id, 'evidence_url', e.target.value)} disabled={!f.can_submit} />
                </>
              )}
            </div>
          ))}
          <button className="btn btn-primary" disabled={!f.can_submit || items.length === 0 || s.busy}>Submit {items.length || ''} answer{items.length === 1 ? '' : 's'}</button>
          <FormStatus s={{ ...s, ok: null }} />
        </form>
      )}
    </>
  )
}

function AccountPage() {
  useTitle('Account')
  const { user, applyToken, logout } = useAuth()
  const nav = useNavigate()
  const [name, setName] = useState(user?.display_name ?? '')
  useEffect(() => setName(user?.display_name ?? ''), [user])
  const [cur, setCur] = useState(''); const [nw, setNw] = useState('')
  const [pw, setPw] = useState(''); const [sure, setSure] = useState(false)
  const a = useSubmit(); const b = useSubmit(); const c = useSubmit()
  const { refresh } = useAuth()
  return (
    <>
      <PageHead title="Your account" lead={`${user?.email} · ${titleCase(user?.role ?? '')} account`} />
      <div className="cols-2">
        <form className="panel" onSubmit={async (e) => { e.preventDefault(); const r = await a.run(() => api.patch('/me', { display_name: name }), 'Name updated.'); if (r !== undefined) void refresh() }}>
          <h2>Display name</h2>
          <TextField label="Name" value={name} onChange={(e) => setName(e.target.value)} required maxLength={120} />
          <button className="btn" disabled={a.busy || !name.trim()}>Save name</button><FormStatus s={a} />
        </form>
        <form className="panel" onSubmit={async (e) => { e.preventDefault(); const r = await b.run(() => api.patch<TokenResponse>('/me', { current_password: cur, new_password: nw }), 'Password changed. Other devices were signed out.'); if (r) { applyToken(r); setCur(''); setNw('') } }}>
          <h2>Change password</h2>
          <TextField label="Current password" type="password" autoComplete="current-password" value={cur} onChange={(e) => setCur(e.target.value)} />
          <TextField label="New password" type="password" autoComplete="new-password" value={nw} onChange={(e) => setNw(e.target.value)} hint="At least 10 characters." />
          <button className="btn" disabled={b.busy || !cur || nw.length < 10}>Change password</button><FormStatus s={b} />
        </form>
      </div>
      <Panel title="Delete your account">
        <p className="muted">This erases your preferences, saved events, comparison history and recommendation feedback, and signs you out everywhere. Feedback or evidence you submitted stays attached to an anonymous placeholder so public summaries stay consistent. This cannot be undone.</p>
        <TextField label="Confirm with your password" type="password" autoComplete="current-password" value={pw} onChange={(e) => setPw(e.target.value)} />
        <Check label="I understand this is permanent" checked={sure} onChange={(e) => setSure(e.target.checked)} />
        <button className="btn btn-danger" disabled={!sure || !pw || c.busy} onClick={async () => { const r = await c.run(() => api.del('/me', { password: pw }), 'Account deleted.'); if (r !== undefined) { setToken(null); await logout(); nav('/', { replace: true }) } }}>Delete my account</button>
        <FormStatus s={{ ...c, ok: null }} />
      </Panel>
    </>
  )
}
