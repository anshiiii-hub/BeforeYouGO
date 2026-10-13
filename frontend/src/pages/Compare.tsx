import { useSearchParams, Link } from 'react-router-dom'
import { api } from '../api/client'
import type { CompareResponse } from '../api/types'
import { DataState, Empty, Notice } from '../components/States'
import { useTray } from '../components/EventActions'
import { Badge, ExternalLink, PageHead, Panel, Unknown } from '../components/ui'
import { clearTray } from '../lib/compare'
import { ORIGIN, categoryLabel, titleCase } from '../lib/labels'
import { useAsync, useTitle } from '../lib/useAsync'
import { useAuth } from '../auth/AuthContext'

const UNKNOWN_VALUES = new Set(['not stated', 'unknown', 'not stated (not the same as free)'])

export function CompareCell({ v }: { v: string | null }) {
  if (v === null || v === undefined || UNKNOWN_VALUES.has(String(v).trim().toLowerCase())) return <Unknown>{v ?? 'Not stated'}</Unknown>
  return <>{v}</>
}

export function ComparePage() {
  useTitle('Compare events')
  const [params, setParams] = useSearchParams()
  const { user } = useAuth()
  const tray = useTray()
  const ids = (params.get('ids') ?? '').split(',').map((s) => s.trim()).filter(Boolean)
  const key = ids.join(',')
  const state = useAsync(async () => (ids.length >= 2 ? api.post<CompareResponse>('/events/compare', { event_ids: ids }) : null), [key])
  const remove = (id: string) => { const next = ids.filter((x) => x !== id); setParams(next.length ? { ids: next.join(',') } : {}) }
  return (
    <div className="wrap page">
      <PageHead title="Compare events" lead="Differences are highlighted only where stated values differ. Not stated means unknown, never zero or none." />
      {ids.length < 2 && (
        <Empty title="Choose at least two events"
          action={<div className="btn-row">
            {tray.length >= 2 && <Link className="btn btn-primary" to={`/compare?ids=${tray.map((t) => t.id).join(',')}`}>Compare the {tray.length} events in your list</Link>}
            <Link className="btn" to="/discover">Find events to compare</Link>
            {user && <Link className="btn" to="/me/comparisons">Past comparisons</Link>}
          </div>}>
          Use the Compare button on any event, then come back here. You can compare up to four at once.
        </Empty>
      )}
      {ids.length >= 2 && (
        <DataState state={state} loadingLabel="Comparing events">
          {(c) => c && (
            <>
              {c.highlights.length > 0 && <Panel title="What stands out"><ul className="bullets">{c.highlights.map((h) => <li key={h}>{h}</li>)}</ul></Panel>}
              <div className="panel table-wrap">
                <table>
                  <caption className="sr-only">Side-by-side comparison of {c.events.length} events</caption>
                  <thead>
                    <tr>
                      <th scope="col">Detail</th>
                      {c.events.map((e) => (
                        <th scope="col" key={e.id}>
                          <Link to={`/events/${e.id}`}>{e.title}</Link>
                          <div className="small muted" style={{ fontWeight: 400 }}>{e.organizer ?? 'Organizer not stated'}</div>
                          <div style={{ marginTop: 4 }}><Badge tone="violet">{categoryLabel(e.category)}</Badge> <Badge tone={ORIGIN[e.origin.type]?.tone}>{ORIGIN[e.origin.type]?.label}</Badge></div>
                          <div className="btn-row" style={{ marginTop: 6 }}>
                            <button className="btn btn-sm" onClick={() => remove(e.id)} aria-label={`Remove ${e.title} from this comparison`}>Remove</button>
                            {e.canonical_url && <ExternalLink href={e.canonical_url}><span className="small">Source</span></ExternalLink>}
                          </div>
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {c.events.some((e) => e.fit && e.fit.score !== null) && (
                      <tr><th scope="row">Fit for you</th>{c.events.map((e) => <td key={e.id}>{e.fit ? <>{e.fit.label}{e.fit.score !== null && ` (${e.fit.score}/100)`}</> : <Unknown />}</td>)}</tr>
                    )}
                    {c.rows.map((r) => (
                      <tr key={r.key}>
                        <th scope="row" className={r.differs ? 'differs' : ''}>{r.label}{r.differs && <span className="sr-only"> (values differ)</span>}</th>
                        {r.values.map((v, i) => <td key={i} className={r.differs ? 'differs' : ''}><CompareCell v={v !== null && (r.key === 'format' || r.key === 'evidence') ? titleCase(v) : v} /></td>)}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="small muted">{c.note} Shaded rows differ between events.</p>
              <Notice tone="info" live={false}>{user ? 'This comparison was added to your history.' : 'Sign in to keep a history of your comparisons.'}</Notice>
              <button className="btn btn-sm" onClick={() => { clearTray(); setParams({}) }}>Start a new comparison</button>
            </>
          )}
        </DataState>
      )}
    </div>
  )
}
