import { Link } from 'react-router-dom'
import { api } from '../api/client'
import type { Facets, SearchResponse } from '../api/types'
import { useAuth, isStaff } from '../auth/AuthContext'
import { DataState, Notice } from '../components/States'
import { PageHead, Panel } from '../components/ui'
import { fmtRelative } from '../lib/format'
import { useAsync, useTitle } from '../lib/useAsync'

export function About() {
  useTitle('About and methodology')
  const { user } = useAuth()
  const index = useAsync((s) => api.get<SearchResponse>('/events', { page_size: 1 }, s), [])
  const facets = useAsync((s) => api.get<Facets>('/events/facets', undefined, s), [])
  return (
    <div className="wrap page" style={{ maxWidth: 900 }}>
      <PageHead title="About and methodology" lead="What BeforeYouGo reads, how it decides what to show, and what it cannot tell you." />

      <Panel title="Where the events come from">
        <DataState state={index} loadingLabel="Checking the index">
          {(d) => (
            <>
              <p>The index currently holds <strong>{d.index.events_indexed.toLocaleString('en-IN')}</strong> published events from <strong>{d.index.connectors}</strong> connectors, of which <strong>{d.index.connectors_active}</strong> have completed a successful sync. Last successful sync: {fmtRelative(d.index.last_successful_sync_at)}.</p>
              {d.index.connectors_failing.length > 0 && (
                <Notice tone="warn"><strong>Needs attention:</strong> {d.index.connectors_failing.map((c) => `${c.name} (${c.status}${c.detail ? `: ${c.detail}` : ''})`).join('; ')}. Their data may be out of date.</Notice>
              )}
              {d.index.connectors_active < d.index.connectors && (
                <p className="muted">{d.index.connectors - d.index.connectors_active} connector(s) are not active. Connectors that are not implemented, need credentials or have not synced yet do not contribute events. {isStaff(user?.role) ? <>Reviewers can see each connector in <Link to="/admin/sources">source health</Link>.</> : 'Their details are visible to reviewers only.'}</p>
              )}
              <p className="muted">{d.index.scope}</p>
            </>
          )}
        </DataState>
        <h3>Sources with upcoming events</h3>
        <DataState state={facets} loadingLabel="Loading sources" isEmpty={(f) => f.sources.length === 0} empty={<p className="muted">No source currently lists upcoming events.</p>}>
          {(f) => (
            <div className="table-wrap"><table>
              <thead><tr><th scope="col">Source</th><th scope="col">Upcoming events linked</th></tr></thead>
              <tbody>{f.sources.map((s) => <tr key={s.value}><td>{s.label ?? s.value}</td><td>{s.count.toLocaleString('en-IN')}</td></tr>)}</tbody>
            </table></div>
          )}
        </DataState>
        <p className="small muted">Counts cover upcoming, published events only. An event listed by two sources is counted under both. The full connector list is not public; the admin-only sources endpoint is not used here.</p>
      </Panel>

      <Panel title="How to read an event page">
        <ul className="bullets">
          <li><strong>Not stated means unknown.</strong> A missing fee is never shown as free, a missing deadline is never shown as open, and missing accessibility information is never shown as unavailable.</li>
          <li><strong>Every field has a provenance.</strong> Evidence labels distinguish organizer-provided, public-source, participant-report and independently reviewed information.</li>
          <li><strong>Promises are quoted, not paraphrased.</strong> The original wording is always kept. Corrections by organizers change how a promise is recorded, never what was written.</li>
          <li><strong>Status is about evidence, not honesty.</strong> {'“'}Unverified{'”'} means no qualifying evidence was found. Only reviewers can corroborate or mark a promise fulfilled, and organizer-provided evidence alone is never enough.</li>
          <li><strong>Fit scores are preference matches.</strong> They are weighted sums over the factors that are known, with unknown factors left out and the coverage shown. They are not a probability of a good outcome, and completeness, evidence strength and fit are never merged into a single trust score.</li>
        </ul>
      </Panel>

      <Panel title="How promises are extracted">
        <p>The analyzer reads text and extracts promises, vague wording and missing details. Each result states whether an AI model or fixed rules produced it. When an AI model is used, every claim must quote the source text exactly or it is discarded. Text that tries to instruct the model is detected, flagged and ignored. When no AI provider is configured, or the provider fails, deterministic rules do the extraction, which can miss unusual wording.</p>
      </Panel>

      <Panel title="What it cannot do">
        <ul className="bullets">
          <li>It does not cover the whole internet. It only covers connected sources and submitted records.</li>
          <li>It cannot confirm that an event happened or that a promise was kept without evidence from reviewers or participants.</li>
          <li>Participant reports are self-declared unless a reviewer confirms participation, and they are not independent verification. A published verdict needs a minimum number of responses.</li>
          <li>It does not measure learning outcomes. There is no pre- or post-assessment data.</li>
          <li>Distances are straight-line estimates from city names, not travel times.</li>
        </ul>
      </Panel>

      <Panel title="Your data">
        <p>Preferences you enter are used only to rank and explain events for you. Every field is optional, can be edited or deleted at any time, and is not shown to organizers. Deleting your account erases your profile, saved events, comparison history and recommendation feedback. Feedback and evidence you submitted stay attached to an anonymised placeholder so published summaries remain consistent.</p>
        <p className="small muted">Machine-readable API documentation is available at <a href="/api/docs" target="_blank" rel="noopener noreferrer">/api/docs</a>.</p>
      </Panel>
    </div>
  )
}
