import { useState, type FormEvent } from 'react'
import type { EventDetail } from '../../api/types'
import { Check, FormStatus, Select, TextArea, TextField, type SubmitState } from '../../components/ui'

export interface EventFormValues {
  title: string; description: string; canonical_url: string; registration_url: string; organizer_name: string; organizer_url: string
  category: string; start_date: string; end_date: string; registration_deadline: string; format: string; venue: string; city: string; state: string; country: string
  eligibility: string; prerequisites: string; team_size_min: string; team_size_max: string; allows_cross_college_teams: string
  fee_choice: string; fee_amount: string; fee_currency: string; other_costs: string; prize_details: string; time_commitment: string
  schedule_text: string; judging_criteria: string; refund_policy: string; contact_info: string; accommodation_info: string
  offers_certificate: string; offers_mentorship: string
}

/** Convert a stored UTC instant to the 'YYYY-MM-DDTHH:mm' wall-clock value in India Standard Time (what the server expects for naive input). */
export function toIstInput(iso: string | null): string {
  if (!iso) return ''
  const t = new Date(iso).getTime()
  if (Number.isNaN(t)) return ''
  return new Date(t + 330 * 60000).toISOString().slice(0, 16)
}
const tri = (v: boolean | null | undefined) => (v === true ? 'true' : v === false ? 'false' : '')

export function valuesFromEvent(e?: EventDetail): EventFormValues {
  return {
    title: e?.title ?? '', description: e?.description ?? '', canonical_url: e?.canonical_url ?? '', registration_url: e?.registration_url ?? '',
    organizer_name: e?.organizer ?? '', organizer_url: e?.organizer_url ?? '', category: e?.category ?? '', start_date: e?.start_date ?? '', end_date: e?.end_date ?? '',
    registration_deadline: toIstInput(e?.registration_deadline ?? null), format: e && e.format !== 'unknown' ? e.format : '', venue: '', city: e?.city ?? '', state: '', country: e?.country ?? '',
    eligibility: e?.eligibility ?? '', prerequisites: e?.prerequisites ?? '', team_size_min: String(e?.team_size.min ?? ''), team_size_max: String(e?.team_size.max ?? ''),
    allows_cross_college_teams: tri(e?.allows_cross_college_teams), fee_choice: e?.fee.status === 'free' ? 'free' : e?.fee.status === 'paid' ? 'paid' : '',
    fee_amount: String(e?.fee.amount ?? ''), fee_currency: e?.fee.currency ?? 'INR', other_costs: e?.other_costs ?? '', prize_details: e?.prize_details ?? '',
    time_commitment: e?.time_commitment ?? '', schedule_text: e?.schedule_text ?? '', judging_criteria: e?.judging_criteria ?? '', refund_policy: e?.refund_policy ?? '',
    contact_info: e?.contact_info ?? '', accommodation_info: e?.accommodation_info ?? '', offers_certificate: tri(e?.offers_certificate), offers_mentorship: tri(e?.offers_mentorship),
  }
}

/** Builds the request body. Blank values are omitted, which the API treats as unknown (create) or unchanged (update). */
export function buildPayload(v: EventFormValues, initial?: EventFormValues): Record<string, unknown> {
  const out: Record<string, unknown> = {}
  const changed = (k: keyof EventFormValues) => !initial || v[k] !== initial[k]
  const text: (keyof EventFormValues)[] = ['title', 'description', 'canonical_url', 'registration_url', 'organizer_name', 'organizer_url', 'category', 'start_date', 'end_date', 'format', 'venue', 'city', 'state', 'country', 'eligibility', 'prerequisites', 'other_costs', 'prize_details', 'time_commitment', 'schedule_text', 'judging_criteria', 'refund_policy', 'contact_info', 'accommodation_info']
  for (const k of text) if (v[k].trim() && changed(k)) out[k] = v[k].trim()
  if (v.registration_deadline && changed('registration_deadline')) out.registration_deadline = v.registration_deadline
  for (const k of ['team_size_min', 'team_size_max'] as const) if (v[k].trim() && changed(k)) out[k] = Number(v[k])
  for (const k of ['allows_cross_college_teams', 'offers_certificate', 'offers_mentorship'] as const) if (v[k] && changed(k)) out[k] = v[k] === 'true'
  if (v.fee_choice === 'free' && (changed('fee_choice') || changed('fee_amount'))) out.fee_status = 'free'
  if (v.fee_choice === 'paid' && (changed('fee_choice') || changed('fee_amount') || changed('fee_currency'))) {
    out.fee_status = 'paid'
    if (v.fee_amount.trim()) out.fee_amount = Number(v.fee_amount)
    out.fee_currency = (v.fee_currency || 'INR').toUpperCase()
  }
  return out
}

export function EventForm({ initial, submitLabel, onSubmit, status, extra }: {
  initial: EventFormValues; submitLabel: string; onSubmit: (payload: Record<string, unknown>, values: EventFormValues) => void; status: SubmitState; extra?: React.ReactNode
}) {
  const [v, setV] = useState(initial)
  const set = (k: keyof EventFormValues) => (e: { target: { value: string } }) => setV({ ...v, [k]: e.target.value })
  const triOpts = (yes: string, no: string) => [{ value: 'true', label: yes }, { value: 'false', label: no }]
  const submit = (e: FormEvent) => { e.preventDefault(); onSubmit(buildPayload(v, initial === EMPTY_REF ? undefined : initial), v) }
  const dateErr = v.start_date && v.end_date && v.end_date < v.start_date ? 'The end date cannot be before the start date.' : null
  return (
    <form className="panel" onSubmit={submit}>
      <p className="hint">Leave a field blank if it is not decided. Blank is shown to students as {'“'}Not stated{'”'}, never as free or none.</p>
      <TextField label="Title" value={v.title} onChange={set('title')} required minLength={3} />
      <TextArea label="Description" rows={6} value={v.description} onChange={set('description')} hint="At least 40 characters are needed to publish." />
      <div className="form-grid">
        <Select label="Category" value={v.category} onChange={set('category')} placeholder="Detect automatically" options={['hackathon', 'workshop', 'conference', 'meetup', 'competition', 'internship', 'other'].map((x) => ({ value: x, label: x[0].toUpperCase() + x.slice(1) }))} />
        <Select label="Format" value={v.format} onChange={set('format')} placeholder="Not stated" options={['online', 'offline', 'hybrid'].map((x) => ({ value: x, label: x[0].toUpperCase() + x.slice(1) }))} />
        <TextField label="Starts on" type="date" value={v.start_date} onChange={set('start_date')} />
        <TextField label="Ends on" type="date" value={v.end_date} onChange={set('end_date')} error={dateErr} />
        <TextField label="Registration deadline (India time)" type="datetime-local" value={v.registration_deadline} onChange={set('registration_deadline')} hint="Entered as IST. It cannot be after the event ends." />
      </div>
      <fieldset><legend>Where</legend>
        <div className="form-grid">
          <TextField label="Venue" value={v.venue} onChange={set('venue')} />
          <TextField label="City" value={v.city} onChange={set('city')} />
          <TextField label="State" value={v.state} onChange={set('state')} />
          <TextField label="Country" value={v.country} onChange={set('country')} />
        </div>
      </fieldset>
      <fieldset><legend>Fee</legend>
        <div className="form-grid">
          <Select label="Registration fee" value={v.fee_choice} onChange={set('fee_choice')} placeholder="Not stated" options={[{ value: 'free', label: 'Free' }, { value: 'paid', label: 'Paid' }]} hint="Choose Free only if no fee applies." />
          {v.fee_choice === 'paid' && <TextField label="Amount" type="number" min={0} value={v.fee_amount} onChange={set('fee_amount')} />}
          {v.fee_choice === 'paid' && <TextField label="Currency" value={v.fee_currency} onChange={set('fee_currency')} maxLength={3} />}
        </div>
        <TextArea label="Other costs (travel, materials, accommodation)" rows={2} value={v.other_costs} onChange={set('other_costs')} />
        <TextArea label="Refund and cancellation policy" rows={2} value={v.refund_policy} onChange={set('refund_policy')} />
      </fieldset>
      <fieldset><legend>Who can take part</legend>
        <TextArea label="Eligibility" rows={2} value={v.eligibility} onChange={set('eligibility')} />
        <TextArea label="Prerequisites" rows={2} value={v.prerequisites} onChange={set('prerequisites')} />
        <div className="form-grid">
          <TextField label="Minimum team size" type="number" min={1} value={v.team_size_min} onChange={set('team_size_min')} />
          <TextField label="Maximum team size" type="number" min={1} value={v.team_size_max} onChange={set('team_size_max')} />
          <Select label="Cross-college teams" value={v.allows_cross_college_teams} onChange={set('allows_cross_college_teams')} placeholder="Not stated" options={triOpts('Allowed', 'Not allowed')} />
        </div>
      </fieldset>
      <fieldset><legend>What participants get</legend>
        <div className="form-grid">
          <Select label="Certificate" value={v.offers_certificate} onChange={set('offers_certificate')} placeholder="Not stated" options={triOpts('Offered', 'Not offered')} />
          <Select label="Mentorship" value={v.offers_mentorship} onChange={set('offers_mentorship')} placeholder="Not stated" options={triOpts('Offered', 'Not offered')} />
        </div>
        <TextArea label="Prizes" rows={2} value={v.prize_details} onChange={set('prize_details')} hint="Include amounts, how many winners, and when they are paid." />
        <TextArea label="Judging criteria" rows={2} value={v.judging_criteria} onChange={set('judging_criteria')} />
      </fieldset>
      <fieldset><legend>Logistics</legend>
        <TextArea label="Schedule" rows={3} value={v.schedule_text} onChange={set('schedule_text')} />
        <TextField label="Time commitment" value={v.time_commitment} onChange={set('time_commitment')} />
        <TextArea label="Accommodation information" rows={2} value={v.accommodation_info} onChange={set('accommodation_info')} />
        <TextField label="Contact (email or phone)" value={v.contact_info} onChange={set('contact_info')} />
        <div className="form-grid">
          <TextField label="Event page URL" type="url" value={v.canonical_url} onChange={set('canonical_url')} />
          <TextField label="Registration URL" type="url" value={v.registration_url} onChange={set('registration_url')} />
          <TextField label="Organizer name" value={v.organizer_name} onChange={set('organizer_name')} hint="Defaults to your organization." />
          <TextField label="Organizer website" type="url" value={v.organizer_url} onChange={set('organizer_url')} />
        </div>
      </fieldset>
      {extra}
      <div className="btn-row"><button className="btn btn-primary" disabled={status.busy || !!dateErr || v.title.trim().length < 3}>{submitLabel}</button></div>
      <FormStatus s={status} />
    </form>
  )
}
export const EMPTY_REF = valuesFromEvent()
export { Check }
