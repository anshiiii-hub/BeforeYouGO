import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api, download } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import type { Claim, ClaimFull, ClaimStatus, Evidence } from '../api/types'
import { fmtBytes, fmtDateTime } from '../lib/format'
import { CATEGORY_LABEL, CLAIM_STATUS, CLAIM_TYPE_LABEL, claimStatusLabel, titleCase } from '../lib/labels'
import { Badge, Check, ClaimStatusBadge, EvidenceKindBadge, FormStatus, Select, TextArea, TextField, useSubmit } from './ui'
import { DataState } from './States'
import { useAsync } from '../lib/useAsync'

const PROVENANCE: Record<string, string> = {
  ai_interpretation: 'Read by an AI model', deterministic_rule: 'Read by fixed rules', source_field: 'From a source field', manual: 'Added by a person',
}
const CLAIM_TYPES = ['specific', 'vague', 'conditional', 'informational']

export function ClaimSummary({ c, extra }: { c: Claim; extra?: React.ReactNode }) {
  return (
    <>
      <div className="claim-top">
        <ClaimStatusBadge status={c.status} />
        <Badge tone="violet">{CATEGORY_LABEL[c.category] ?? titleCase(c.category)}</Badge>
        <Badge tone={c.claim_type === 'vague' ? 'warn' : 'neutral'} title="How specific and checkable the wording is">{CLAIM_TYPE_LABEL[c.claim_type] ?? titleCase(c.claim_type)}</Badge>
        <Badge tone="neutral" title="How this promise was extracted">{PROVENANCE[c.provenance] ?? titleCase(c.provenance)}</Badge>
      </div>
      <blockquote className="quote" style={{ margin: '8px 0' }}>{'“'}{c.original_text}{'”'}</blockquote>
      <p className="small muted" style={{ marginBottom: 4 }}>{CLAIM_STATUS[c.status]?.help}</p>
      {c.numeric_values?.length > 0 && <p className="small"><strong>Numbers quoted:</strong> {c.numeric_values.map((n) => n.text).join(', ')}</p>}
      {c.conditions?.length > 0 && <p className="small"><strong>Conditions:</strong> {c.conditions.join('; ')}</p>}
      {c.missing_details?.length > 0 && <p className="small"><strong>Missing details:</strong> {c.missing_details.join('; ')}</p>}
      {c.verification_questions?.length > 0 && (
        <div className="small"><strong>Questions to ask:</strong><ul className="bullets">{c.verification_questions.map((q) => <li key={q}>{q}</li>)}</ul></div>
      )}
      {extra}
    </>
  )
}

export interface ClaimPerm { manage: boolean; review: boolean }

export function ClaimPanel({ claim, eventId, perm, onChanged }: { claim: Claim; eventId: string; perm: ClaimPerm; onChanged?: () => void }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="claim" data-testid="claim">
      <ClaimSummary c={claim} />
      <button className="btn btn-sm" aria-expanded={open} onClick={() => setOpen((o) => !o)}>{open ? 'Hide evidence and history' : 'Show evidence and history'}</button>
      {open && <ClaimDetail id={claim.id} eventId={eventId} perm={perm} onChanged={onChanged} />}
    </div>
  )
}

function ClaimDetail({ id, eventId, perm, onChanged }: { id: string; eventId: string; perm: ClaimPerm; onChanged?: () => void }) {
  const state = useAsync((s) => api.get<ClaimFull>(`/claims/${id}`, undefined, s), [id])
  const { user } = useAuth()
  const changed = () => { state.reload(); onChanged?.() }
  return (
    <div style={{ marginTop: 12 }}>
      <DataState state={state} loadingLabel="Loading evidence">
        {(c) => (
          <div className="stack">
            <div>
              <h4>Evidence ({c.evidence.length})</h4>
              {c.evidence.length === 0 && <p className="muted small">No evidence has been attached to this promise yet. That is not a finding that it was broken.</p>}
              <ul className="plain">{c.evidence.map((e) => <EvidenceRow key={e.id} e={e} canReview={perm.review} onChanged={changed} canSee={!!user} />)}</ul>
            </div>
            {c.organizer_responses.length > 0 && (
              <div><h4>Organizer responses</h4><ul className="plain">{c.organizer_responses.map((r) => <li key={r.id}>{r.body}<br /><span className="small dim">{fmtDateTime(r.created_at)}</span></li>)}</ul></div>
            )}
            {c.disputes.length > 0 && (
              <div><h4>Disputes</h4><ul className="plain">{c.disputes.map((d) => <li key={d.id}><Badge tone="violet">{titleCase(d.kind)}</Badge> <Badge>{titleCase(d.status)}</Badge><br />{d.description}{d.resolution_note && <><br /><span className="small muted">Resolution: {d.resolution_note}</span></>}</li>)}</ul></div>
            )}
            <div>
              <h4>Status history</h4>
              {c.history.length === 0 ? <p className="muted small">No status changes yet.</p> : (
                <ol className="timeline">{c.history.map((h, i) => (
                  <li key={i}><strong>{h.from_status ? `${claimStatusLabel(h.from_status)} → ` : ''}{claimStatusLabel(h.to_status)}</strong>
                    <span className="small dim"> {fmtDateTime(h.at)}{h.actor_role ? `, by a ${h.actor_role}` : ''}</span>
                    {h.reason && <div className="small">{h.reason}</div>}</li>
                ))}</ol>
              )}
              <p className="small muted">{c.status_note}</p>
            </div>
            {user ? (
              <>
                <TransitionForm claim={c} onDone={changed} />
                <EvidenceForm claimId={c.id} role={user.role} onDone={changed} />
                {perm.manage && <OrganizerClaimActions claim={c} eventId={eventId} onDone={changed} />}
                <ReportForm targetType="claim" targetId={c.id} />
              </>
            ) : <p className="small"><Link to="/login">Sign in</Link> to submit evidence or report a problem with this promise.</p>}
          </div>
        )}
      </DataState>
    </div>
  )
}

function EvidenceRow({ e, canReview, onChanged, canSee }: { e: Evidence; canReview: boolean; onChanged: () => void; canSee: boolean }) {
  const s = useSubmit()
  const [note, setNote] = useState('')
  const review = (decision: 'accepted' | 'rejected') => s.run(async () => { await api.post(`/evidence/${e.id}/review`, { decision, note }); onChanged() }, 'Reviewed.')
  return (
    <li>
      <div className="claim-top"><EvidenceKindBadge kind={e.kind} />
        <Badge tone={e.review_status === 'accepted' ? 'good' : e.review_status === 'rejected' ? 'bad' : 'unknown'}>{e.review_status === 'pending' ? 'Awaiting review' : titleCase(e.review_status)}</Badge>
        {!e.claim_specific && <Badge tone="warn">Not specific to this promise</Badge>}
        {e.coi_declared && <Badge tone="warn" title={e.coi_statement ?? undefined}>Conflict of interest declared</Badge>}
      </div>
      {e.excerpt && <div className="quote">{e.excerpt}</div>}
      {e.url && <p className="small"><a href={/^https?:/i.test(e.url) ? e.url : '#'} target="_blank" rel="noopener noreferrer">{e.url}</a></p>}
      {e.has_file && canSee && (
        <p className="small"><button className="btn btn-sm" onClick={() => s.run(() => download(`/evidence/${e.id}/file`, {}, e.file_name ?? 'evidence'), 'Downloaded.')}>Download {e.file_name ?? 'file'} {fmtBytes(e.file_size)}</button></p>
      )}
      <p className="small dim">Submitted {fmtDateTime(e.submitted_at)}{e.review_note ? ` · Review note: ${e.review_note}` : ''}</p>
      {canReview && e.review_status === 'pending' && (
        <div className="inline-form">
          <TextField label="Review note (required)" value={note} onChange={(ev) => setNote(ev.target.value)} />
          <button className="btn btn-sm" disabled={note.trim().length < 5 || s.busy} onClick={() => review('accepted')}>Accept</button>
          <button className="btn btn-sm btn-danger" disabled={note.trim().length < 5 || s.busy} onClick={() => review('rejected')}>Reject</button>
        </div>
      )}
      <FormStatus s={s} />
    </li>
  )
}

function TransitionForm({ claim, onDone }: { claim: ClaimFull; onDone: () => void }) {
  const allowed = claim.transitions.filter((t) => t.permitted_for_you)
  const [to, setTo] = useState('')
  const [reason, setReason] = useState('')
  const s = useSubmit()
  if (allowed.length === 0) return null
  const chosen = allowed.find((t) => t.to === to)
  return (
    <form className="panel" style={{ margin: 0 }} onSubmit={async (e) => {
      e.preventDefault()
      const r = await s.run(() => api.post(`/claims/${claim.id}/transition`, { to_status: to, reason }), 'Status updated.')
      if (r !== undefined) { setReason(''); setTo(''); onDone() }
    }}>
      <h4>Change status</h4>
      <Select label="New status" value={to} onChange={(e) => setTo(e.target.value)} placeholder="Choose a status" options={allowed.map((t) => ({ value: t.to, label: claimStatusLabel(t.to) }))} />
      {chosen && <p className="hint">Requires: {chosen.evidence_requirement}{chosen.requires_event_ended ? ' The event must have ended.' : ''}</p>}
      <TextArea label="Reason" value={reason} onChange={(e) => setReason(e.target.value)} minLength={5} rows={2} />
      <button className="btn btn-sm btn-primary" disabled={!to || reason.trim().length < 5 || s.busy}>Update status</button>
      <FormStatus s={s} />
    </form>
  )
}

function EvidenceForm({ claimId, role, onDone }: { claimId: string; role: string; onDone: () => void }) {
  const [url, setUrl] = useState('')
  const [excerpt, setExcerpt] = useState('')
  const [kind, setKind] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [specific, setSpecific] = useState(true)
  const [coi, setCoi] = useState(false)
  const [coiText, setCoiText] = useState('')
  const s = useSubmit()
  const staff = role === 'reviewer' || role === 'admin'
  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    const r = await s.run(async () => {
      if (file) {
        const fd = new FormData()
        fd.append('file', file)
        if (url) fd.append('url', url)
        if (excerpt) fd.append('excerpt', excerpt)
        if (kind) fd.append('kind', kind)
        fd.append('claim_specific', String(specific))
        fd.append('coi_declared', String(coi))
        if (coiText) fd.append('coi_statement', coiText)
        return api.upload(`/claims/${claimId}/evidence/upload`, fd)
      }
      return api.post(`/claims/${claimId}/evidence`, { url: url || null, excerpt: excerpt || null, kind: kind || null, claim_specific: specific, coi_declared: coi, coi_statement: coiText || null })
    }, 'Evidence submitted for review.')
    if (r !== undefined) { setUrl(''); setExcerpt(''); setFile(null); onDone() }
  }
  return (
    <details>
      <summary>Add evidence</summary>
      <form className="panel" style={{ margin: '8px 0 0' }} onSubmit={submit}>
        <p className="small muted">
          {role === 'organizer' ? 'Evidence you provide is labelled organizer-provided. On its own it cannot corroborate a promise.'
            : role === 'student' ? 'Only people who declared they took part in the event can add a participant report.' : 'Evidence you add is labelled with the kind you choose.'}
        </p>
        <TextField label="Link to evidence" type="url" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://" />
        <TextArea label="Quoted excerpt" rows={3} value={excerpt} onChange={(e) => setExcerpt(e.target.value)} />
        <TextField label="Upload a file" type="file" accept=".pdf,.png,.jpg,.jpeg,.webp,.txt" onChange={(e) => setFile(e.target.files?.[0] ?? null)} hint="PDF, PNG, JPEG, WebP or text." />
        {staff && <Select label="Evidence kind" value={kind} onChange={(e) => setKind(e.target.value)} options={[{ value: 'independent_review', label: 'Independently reviewed' }, { value: 'public_source', label: 'Public source' }]} placeholder="Default: independently reviewed" />}
        <Check label="This evidence is specific to this promise" checked={specific} onChange={(e) => setSpecific(e.target.checked)} />
        <Check label="I have a conflict of interest to declare" checked={coi} onChange={(e) => setCoi(e.target.checked)} />
        {coi && <TextField label="Describe the conflict of interest" value={coiText} onChange={(e) => setCoiText(e.target.value)} />}
        <button className="btn btn-sm btn-primary" disabled={s.busy || (!url && !excerpt && !file)}>Submit evidence</button>
        <FormStatus s={s} />
      </form>
    </details>
  )
}

function OrganizerClaimActions({ claim, eventId, onDone }: { claim: ClaimFull; eventId: string; onDone: () => void }) {
  const [body, setBody] = useState('')
  const [reason, setReason] = useState('')
  const [normalized, setNormalized] = useState(claim.normalized_text)
  const [ctype, setCtype] = useState(claim.claim_type)
  const [dispute, setDispute] = useState('')
  const r = useSubmit(); const c = useSubmit(); const d = useSubmit()
  return (
    <details>
      <summary>Organizer actions</summary>
      <div className="stack" style={{ marginTop: 8 }}>
        <form className="panel" style={{ margin: 0 }} onSubmit={async (e) => { e.preventDefault(); const x = await r.run(() => api.post('/organizer/responses', { event_id: eventId, claim_id: claim.id, body }), 'Response published.'); if (x !== undefined) { setBody(''); onDone() } }}>
          <h4>Respond publicly</h4>
          <TextArea label="Your response" rows={3} value={body} onChange={(e) => setBody(e.target.value)} />
          <button className="btn btn-sm" disabled={r.busy || body.trim().length < 5}>Publish response</button><FormStatus s={r} />
        </form>
        <form className="panel" style={{ margin: 0 }} onSubmit={async (e) => { e.preventDefault(); const x = await c.run(() => api.patch(`/organizer/claims/${claim.id}`, { normalized_text: normalized, claim_type: ctype, reason }), 'Correction saved. The original quote is unchanged.'); if (x !== undefined) onDone() }}>
          <h4>Correct how this promise was recorded</h4>
          <p className="hint">Fixes extraction mistakes. The original quoted text is never altered and every change is audited.</p>
          <TextArea label="Normalised wording" rows={2} value={normalized} onChange={(e) => setNormalized(e.target.value)} />
          <Select label="Type" value={ctype} onChange={(e) => setCtype(e.target.value)} options={CLAIM_TYPES.map((t) => ({ value: t, label: titleCase(t) }))} />
          <TextField label="Reason for the correction" value={reason} onChange={(e) => setReason(e.target.value)} />
          <div className="btn-row">
            <button className="btn btn-sm" disabled={c.busy || reason.trim().length < 5}>Save correction</button>
            <button type="button" className="btn btn-sm btn-danger" disabled={c.busy || reason.trim().length < 5} onClick={async () => { const x = await c.run(() => api.patch(`/organizer/claims/${claim.id}`, { withdraw: true, reason }), 'Promise withdrawn.'); if (x !== undefined) onDone() }}>Withdraw this promise</button>
          </div>
          <FormStatus s={c} />
        </form>
        <form className="panel" style={{ margin: 0 }} onSubmit={async (e) => { e.preventDefault(); const x = await d.run(() => api.post('/disputes', { event_id: eventId, claim_id: claim.id, kind: 'claim_dispute', description: dispute }), 'Dispute raised. A reviewer will decide.'); if (x !== undefined) { setDispute(''); onDone() } }}>
          <h4>Dispute this promise</h4>
          <TextArea label="Why is it wrong or unfair?" rows={3} value={dispute} onChange={(e) => setDispute(e.target.value)} hint="At least 15 characters." />
          <button className="btn btn-sm btn-danger" disabled={d.busy || dispute.trim().length < 15}>Raise dispute</button><FormStatus s={d} />
        </form>
      </div>
    </details>
  )
}

export function ReportForm({ targetType, targetId }: { targetType: 'claim' | 'event' | 'evidence' | 'feedback'; targetId: string }) {
  const [reason, setReason] = useState('')
  const s = useSubmit()
  return (
    <details>
      <summary>Report a problem</summary>
      <form className="panel" style={{ margin: '8px 0 0' }} onSubmit={async (e) => { e.preventDefault(); const x = await s.run(() => api.post('/reports', { target_type: targetType, target_id: targetId, reason }), 'Report sent to the moderation team.'); if (x !== undefined) setReason('') }}>
        <TextArea label="What is wrong?" rows={2} value={reason} onChange={(e) => setReason(e.target.value)} hint="At least 10 characters." />
        <button className="btn btn-sm" disabled={s.busy || reason.trim().length < 10}>Send report</button><FormStatus s={s} />
      </form>
    </details>
  )
}

export type { ClaimStatus }
