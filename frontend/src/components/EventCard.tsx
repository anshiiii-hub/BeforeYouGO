import { Link } from 'react-router-dom'
import type { EventCard as Card } from '../api/types'
import { fmtDateRange, fmtDeadline } from '../lib/format'
import { categoryLabel, ORIGIN, titleCase } from '../lib/labels'
import { Badge, FeeBadge, Ledger, Unknown } from './ui'
import { SaveButton, CompareButton } from './EventActions'

const FRESH: Record<string, { label: string; tone: 'good' | 'warn' | 'unknown' | 'info' }> = {
  fresh: { label: 'Fresh', tone: 'good' }, stale: { label: 'Stale', tone: 'warn' }, unconfirmed: { label: 'Unconfirmed', tone: 'warn' },
  submitted: { label: 'Submitted by a person', tone: 'info' }, unknown: { label: 'Retrieval time unknown', tone: 'unknown' },
}

export function EventCardView({ e, onSavedChange }: { e: Card; onSavedChange?: (saved: boolean) => void }) {
  const fresh = FRESH[e.freshness.state] ?? { label: titleCase(e.freshness.state), tone: 'unknown' as const }
  const origin = ORIGIN[e.origin.type]
  return (
    <article className="event-card" aria-labelledby={`t-${e.id}`}>
      <header>
        <div className="event-card-badges">
          <Badge tone="violet">{categoryLabel(e.category)}</Badge>
          <Badge tone="neutral">{e.format === 'unknown' ? 'Format not stated' : titleCase(e.format)}</Badge>
          <Badge tone={origin?.tone ?? 'info'} title={e.origin.label}>{origin?.label ?? e.origin.label}</Badge>
          {e.lifecycle_status !== 'scheduled' && e.lifecycle_status !== 'unknown' && <Badge tone="bad">{titleCase(e.lifecycle_status)}</Badge>}
        </div>
        <h3 id={`t-${e.id}`}><Link to={`/events/${e.id}`}>{e.title}</Link></h3>
        <p className="organizer">{e.organizer ? `By ${e.organizer}` : <Unknown>Organizer not stated</Unknown>}</p>
      </header>
      <dl className="facts">
        <div><dt>When</dt><dd>{fmtDateRange(e.start_date, e.end_date)}</dd></div>
        <div><dt>Register by</dt><dd>{e.registration_deadline ? fmtDeadline(e.registration_deadline) : <Unknown>No deadline stated</Unknown>}</dd></div>
        <div><dt>Where</dt><dd>{e.location ?? <Unknown />}</dd></div>
        <div><dt>Fee</dt><dd><FeeBadge fee={e.fee} /></dd></div>
      </dl>
      {e.matched_because.length > 0 && (
        <p className="why"><strong>Why it matches:</strong> {e.matched_because.join('; ')}</p>
      )}
      {e.fit && e.fit.score !== null && (
        <p className="why"><strong>For you:</strong> {e.fit.label} ({e.fit.score}/100, {Math.round(e.fit.coverage * 100)}% of factors known)</p>
      )}
      {e.fit && !e.fit.eligible && e.fit.hard_violations.length > 0 && (
        <p className="why msg-bad"><strong>Excluded by your constraints:</strong> {e.fit.hard_violations.map((v) => v.message).join(' ')}</p>
      )}
      <div className="card-meter">
        <Ledger filled={e.completeness.filled} total={e.completeness.total} />
        <span className="small">{e.completeness.filled} of {e.completeness.total} details stated</span>
      </div>
      {e.missing_information.length > 0 && (
        <p className="missing small"><strong>Missing:</strong> {e.missing_information.join(', ')}</p>
      )}
      <footer>
        <p className="small meta">
          <Badge tone={fresh.tone} title={e.freshness.message}>{fresh.label}</Badge>{' '}
          <span title={e.freshness.message}>{e.freshness.message}</span>
          <br />
          Source: {e.sources.length ? e.sources.map((s) => s.name).join(', ') : <Unknown>No connected source (submitted record)</Unknown>}
          {e.claims_count > 0 && <> {'·'} {e.claims_count} promise{e.claims_count === 1 ? '' : 's'} extracted</>}
        </p>
        <div className="card-actions">
          <SaveButton eventId={e.id} saved={e.saved} onChange={onSavedChange} compact />
          <CompareButton id={e.id} title={e.title} />
          <Link className="btn btn-sm" to={`/events/${e.id}`}>View evidence</Link>
        </div>
      </footer>
    </article>
  )
}
