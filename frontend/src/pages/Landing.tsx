import { useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import type { SearchResponse } from '../api/types'
import { ErrorState, Loading } from '../components/States'
import { Badge, FeeBadge, Ledger, Unknown } from '../components/ui'
import { fmtDateRange, fmtDeadline, fmtRelative } from '../lib/format'
import { categoryLabel } from '../lib/labels'
import { useAsync, useTitle } from '../lib/useAsync'

const EXAMPLES = ['free hackathon online', 'AI workshop for beginners', 'security conference in India', 'events with certificates']

export function Landing() {
  useTitle('Know what an event promises before you go')
  const nav = useNavigate()
  const [q, setQ] = useState('')
  const sample = useAsync((signal) => api.get<SearchResponse>('/events', { page_size: 1, sort: 'date', topics: 'ai' }, signal), [])
  const submit = (e: FormEvent) => { e.preventDefault(); nav(`/discover${q.trim() ? `?q=${encodeURIComponent(q.trim())}` : ''}`) }
  const ev = sample.data?.items[0]
  const idx = sample.data?.index
  return (
    <>
      <section className="hero">
        <div className="wrap hero-grid">
          <div>
            <p className="eyebrow"><span className="eyebrow-dot" /> Event information, with the gaps left visible</p>
            <h1>Know what an event promises before you go.</h1>
            <p className="lead">BeforeYouGo reads event listings for Indian college students, shows exactly what is stated and what is missing, and keeps organizers accountable for their promises.</p>
            <form className="searchbox" role="search" onSubmit={submit} aria-label="Search events">
              <label className="sr-only" htmlFor="hero-q">Describe the event you are looking for</label>
              <input id="hero-q" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Try: free online hackathon in October" />
              <button className="btn btn-primary" type="submit">Search events</button>
            </form>
            <p className="small muted" style={{ marginTop: 12 }}>
              Or try{' '}
              {EXAMPLES.map((x, i) => (
                <span key={x}><Link to={`/discover?q=${encodeURIComponent(x)}`}>{x}</Link>{i < EXAMPLES.length - 1 ? ', ' : ''}</span>
              ))}.
            </p>
            <p className="hero-note"><span aria-hidden="true">↗</span> Search the way you talk. We’ll show the evidence behind every match.</p>
            {idx && (
              <div className="stat-row" aria-label="Index status">
                <div className="stat"><strong>{idx.events_indexed.toLocaleString('en-IN')}</strong><span>events in the index</span></div>
                <div className="stat"><strong>{idx.connectors_active} of {idx.connectors}</strong><span>connectors active</span></div>
                <div className="stat"><strong>{fmtRelative(idx.last_successful_sync_at)}</strong><span>last successful sync</span></div>
              </div>
            )}
          </div>
          <div aria-label="Example of an evidence record">
            <div className="specimen-label"><span>What a listing looks like here</span><span className="specimen-rule" /></div>
            {sample.loading && <Loading label="Loading a live example" />}
            {sample.error && !ev && <ErrorState error={sample.error} onRetry={sample.reload} title="Live example unavailable" />}
            {ev && (
              <article className="specimen">
                <Badge tone="violet">{categoryLabel(ev.category)}</Badge> <Badge tone="info">{ev.origin.label}</Badge>
                <h3><Link to={`/events/${ev.id}`}>{ev.title}</Link></h3>
                <dl style={{ margin: 0 }}>
                  <div className="spec-row"><dt>When</dt><dd>{fmtDateRange(ev.start_date, ev.end_date)}</dd><span className="tag badge badge-good">stated</span></div>
                  <div className="spec-row"><dt>Where</dt><dd>{ev.location ?? <Unknown />}</dd><span className={`tag badge ${ev.location ? 'badge-good' : 'badge-unknown'}`}>{ev.location ? 'stated' : 'unknown'}</span></div>
                  <div className="spec-row"><dt>Fee</dt><dd><FeeBadge fee={ev.fee} detail /></dd><span className={`tag badge ${ev.fee.uncertain ? 'badge-unknown' : 'badge-good'}`}>{ev.fee.uncertain ? 'unknown' : 'stated'}</span></div>
                  <div className="spec-row"><dt>Deadline</dt><dd>{ev.registration_deadline ? fmtDeadline(ev.registration_deadline) : <Unknown>No deadline stated</Unknown>}</dd><span className={`tag badge ${ev.registration_deadline ? 'badge-good' : 'badge-unknown'}`}>{ev.registration_deadline ? 'stated' : 'unknown'}</span></div>
                  <div className="spec-row"><dt>Organizer</dt><dd>{ev.organizer ?? <Unknown />}</dd><span className={`tag badge ${ev.organizer ? 'badge-good' : 'badge-unknown'}`}>{ev.organizer ? 'stated' : 'unknown'}</span></div>
                </dl>
                <p className="small muted" style={{ marginTop: 12, marginBottom: 0 }}>
                  <Ledger filled={ev.completeness.filled} total={ev.completeness.total} /> {ev.completeness.filled} of {ev.completeness.total} details stated.
                  {' '}A live record from {ev.sources[0]?.name ?? 'a submitted record'}; hollow cells are unknown, not zero.
                </p>
              </article>
            )}
          </div>
        </div>
      </section>

      <section className="band wrap" aria-labelledby="loop-h">
        <div className="section-intro">
          <p className="eyebrow">A better event loop</p>
          <h2 id="loop-h">From finding an event to fixing the next one</h2>
          <p className="muted">The useful part is not another rating. It’s knowing what was said, what wasn’t, and what to ask next.</p>
        </div>
        <ol className="loop">
          <li><h3>Discover</h3><p>Search in plain language. Filters cover dates, deadlines, budget, location, certificates and how complete the information is.</p></li>
          <li><h3>Decide</h3><p>See why an event matches you, what is missing, and ask the organizer the questions the listing leaves open. Compare up to four side by side.</p></li>
          <li><h3>Verify</h3><p>Each promise is quoted word for word, then tracked from advertised to corroborated or fulfilled as evidence arrives.</p></li>
          <li><h3>Improve</h3><p>Participants report what was delivered. Organizers get a prioritised list of gaps to fix and an audit report.</p></li>
        </ol>
      </section>

      <section className="band wrap" style={{ paddingTop: 0 }}>
        <div className="grid grid-2">
          <div className="panel">
            <h2>Paste a flyer, check its promises</h2>
            <p className="muted">The promise analyzer works on pasted text, a web address or an uploaded file. It quotes each claim exactly, flags vague wording and tells you whether an AI model or fixed rules did the reading.</p>
            <Link className="btn btn-primary" to="/analyzer">Open the analyzer</Link>
          </div>
          <div className="panel">
            <h2>Organizing an event?</h2>
            <p className="muted">Run a pre-publication audit, close the gaps students ask about, attach evidence to your promises and export an audit report.</p>
            <Link className="btn" to="/register">Create an organizer account</Link>
          </div>
        </div>
      </section>
    </>
  )
}
