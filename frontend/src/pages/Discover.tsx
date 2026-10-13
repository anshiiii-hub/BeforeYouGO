import { useEffect, useMemo, useState, type FormEvent } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api } from '../api/client'
import type { Facets, SearchResponse } from '../api/types'
import { EventCardView } from '../components/EventCard'
import { Empty, ErrorState, Loading, Notice } from '../components/States'
import { Check, Pagination, Select, TextField } from '../components/ui'
import { EMPTY_FILTERS, FILTER_LABELS, filtersToQuery, filtersToSearchParams, paramsToFilters, REQUIRE_KNOWN_OPTIONS, type Filters } from '../lib/filters'
import { titleCase } from '../lib/labels'
import { useAsync, useTitle } from '../lib/useAsync'
import { fmtRelative } from '../lib/format'

const PAGE_SIZE = 20

function toggle(list: string[], v: string) { return list.includes(v) ? list.filter((x) => x !== v) : [...list, v] }

export function Discover() {
  useTitle('Discover events')
  const [params, setParams] = useSearchParams()
  const applied = useMemo(() => paramsToFilters(params), [params])
  const [draft, setDraft] = useState<Filters>(applied)
  const [q, setQ] = useState(applied.q)
  const [showFilters, setShowFilters] = useState(false)
  useEffect(() => { setDraft(applied); setQ(applied.q) }, [applied])

  const facets = useAsync((s) => api.get<Facets>('/events/facets', undefined, s), [])
  const key = params.toString()
  const results = useAsync((signal) => api.get<SearchResponse>('/events', { ...filtersToQuery(applied), page_size: PAGE_SIZE }, signal), [key])

  const commit = (f: Filters) => { setShowFilters(false); setParams(filtersToSearchParams({ ...f, page: 1 })) }
  const submitSearch = (e: FormEvent) => { e.preventDefault(); commit({ ...applied, q: q.trim() }) }
  const submitFilters = (e: FormEvent) => { e.preventDefault(); commit({ ...draft, q: applied.q }) }
  const clearAll = () => { setParams(new URLSearchParams()); }
  const set = <K extends keyof Filters>(k: K, v: Filters[K]) => setDraft((d) => ({ ...d, [k]: v }))
  const f = facets.data

  const chips: { label: string; remove: () => void }[] = []
  const addChip = (label: string, patch: Partial<Filters>) => chips.push({ label, remove: () => commit({ ...applied, ...patch }) })
  if (applied.q) addChip(`Search: ${applied.q}`, { q: '' })
  applied.category.forEach((c) => addChip(`Category: ${titleCase(c)}`, { category: applied.category.filter((x) => x !== c) }))
  applied.format.forEach((c) => addChip(`Format: ${titleCase(c)}`, { format: applied.format.filter((x) => x !== c) }))
  applied.topics.forEach((c) => addChip(`Topic: ${titleCase(c)}`, { topics: applied.topics.filter((x) => x !== c) }))
  applied.require_known.forEach((c) => addChip(REQUIRE_KNOWN_OPTIONS.find((o) => o.value === c)?.label ?? c, { require_known: applied.require_known.filter((x) => x !== c) }))
  for (const k of ['city', 'country', 'date_from', 'date_to', 'deadline_from', 'deadline_to', 'max_fee', 'source', 'origin_type'] as const) {
    if (applied[k]) addChip(`${FILTER_LABELS[k]}: ${applied[k]}`, { [k]: '' } as Partial<Filters>)
  }
  for (const k of ['free_only', 'include_unknown_cost', 'certificate', 'mentorship', 'beginner', 'has_prize', 'accessibility_documented', 'cross_college', 'include_past'] as const) {
    if (applied[k]) addChip(FILTER_LABELS[k], { [k]: false } as Partial<Filters>)
  }

  const data = results.data
  return (
    <div className="wrap page">
      <h1>Discover events</h1>
      <p className="lead" style={{ marginBottom: 16 }}>Describe what you want. We show what each listing states, what it leaves out and where the information came from.</p>
      <form className="searchbox" role="search" onSubmit={submitSearch} aria-label="Search events">
        <label className="sr-only" htmlFor="q">Search events in plain language</label>
        <input id="q" type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="e.g. free beginner AI workshop online next month" maxLength={300} />
        <button className="btn btn-primary" type="submit">Search</button>
      </form>

      <button type="button" className="btn filters-toggle" style={{ marginTop: 16 }} aria-expanded={showFilters} aria-controls="filters-form" onClick={() => setShowFilters((v) => !v)}>
        {showFilters ? 'Hide filters' : 'Show filters'}
      </button>
      <div className="split" style={{ marginTop: 24 }}>
        <form id="filters-form" className={`panel filters ${showFilters ? 'open' : ''}`} onSubmit={submitFilters} aria-label="Filters">
          <div className="panel-head"><h2 style={{ fontSize: '1.1rem' }}>Filters</h2><button type="button" className="btn btn-sm" onClick={clearAll}>Clear all</button></div>
          {facets.error && <Notice tone="warn">Filter options could not be loaded. You can still type values below.</Notice>}
          <details open>
            <summary>Category and format</summary>
            <fieldset><legend>Category</legend>
              {(f?.categories ?? []).map((c) => (
                <Check key={c.value} label={`${titleCase(c.value)} (${c.count})`} checked={draft.category.includes(c.value)} onChange={() => set('category', toggle(draft.category, c.value))} />
              ))}
              {!f && !facets.error && <span className="muted small">Loading options…</span>}
            </fieldset>
            <fieldset><legend>Format</legend>
              {(f?.formats ?? []).map((c) => (
                <Check key={c.value} label={`${titleCase(c.value)} (${c.count})`} checked={draft.format.includes(c.value)} onChange={() => set('format', toggle(draft.format, c.value))} />
              ))}
            </fieldset>
          </details>
          <details>
            <summary>Dates and deadline</summary>
            <TextField label="Starts on or after" type="date" value={draft.date_from} onChange={(e) => set('date_from', e.target.value)} />
            <TextField label="Starts on or before" type="date" value={draft.date_to} onChange={(e) => set('date_to', e.target.value)} />
            <TextField label="Registration closes on or after" type="date" value={draft.deadline_from} onChange={(e) => set('deadline_from', e.target.value)} />
            <TextField label="Registration closes on or before" type="date" value={draft.deadline_to} onChange={(e) => set('deadline_to', e.target.value)} />
            <Check label="Include events that already happened" checked={draft.include_past} onChange={(e) => set('include_past', e.target.checked)} />
          </details>
          <details>
            <summary>Budget</summary>
            <TextField label="Maximum fee (INR)" type="number" min={0} inputMode="numeric" value={draft.max_fee} onChange={(e) => set('max_fee', e.target.value)} />
            <Check label="Only events that state they are free" checked={draft.free_only} onChange={(e) => set('free_only', e.target.checked)} />
            <Check label="Also include events that do not state a fee" hint="They may cost money; not stated is not free." checked={draft.include_unknown_cost} onChange={(e) => set('include_unknown_cost', e.target.checked)} />
          </details>
          <details>
            <summary>Location</summary>
            <TextField label="City" list="cities" value={draft.city} onChange={(e) => set('city', e.target.value)} />
            <datalist id="cities">{(f?.cities ?? []).map((c) => <option key={c.value} value={c.value} />)}</datalist>
            <TextField label="Country" list="countries" value={draft.country} onChange={(e) => set('country', e.target.value)} />
            <datalist id="countries">{(f?.countries ?? []).map((c) => <option key={c.value} value={c.value} />)}</datalist>
          </details>
          <details>
            <summary>What you get</summary>
            <Check label="Certificate offered" checked={draft.certificate} onChange={(e) => set('certificate', e.target.checked)} />
            <Check label="Mentorship offered" checked={draft.mentorship} onChange={(e) => set('mentorship', e.target.checked)} />
            <Check label="Prizes listed" checked={draft.has_prize} onChange={(e) => set('has_prize', e.target.checked)} />
            <Check label="Beginner-friendly" checked={draft.beginner} onChange={(e) => set('beginner', e.target.checked)} />
            <Check label="Cross-college teams allowed" checked={draft.cross_college} onChange={(e) => set('cross_college', e.target.checked)} />
            <Check label="Accessibility information documented" checked={draft.accessibility_documented} onChange={(e) => set('accessibility_documented', e.target.checked)} />
            {(f?.topics.length ?? 0) > 0 && (
              <fieldset><legend>Topics</legend>
                {f!.topics.slice(0, 10).map((t) => <Check key={t.value} label={`${titleCase(t.value)} (${t.count})`} checked={draft.topics.includes(t.value)} onChange={() => set('topics', toggle(draft.topics, t.value))} />)}
              </fieldset>
            )}
          </details>
          <details>
            <summary>Source and information quality</summary>
            <Select label="Source" value={draft.source} onChange={(e) => set('source', e.target.value)} placeholder="Any source"
              options={(f?.sources ?? []).map((s) => ({ value: s.value, label: `${s.label ?? s.value} (${s.count})` }))} />
            <Select label="Origin" value={draft.origin_type} onChange={(e) => set('origin_type', e.target.value)} placeholder="Any origin"
              options={[{ value: 'indexed', label: 'Indexed from a source' }, { value: 'organizer_submitted', label: 'Organizer-submitted' }, { value: 'user_submitted', label: 'User-submitted' }]} />
            <fieldset><legend>Must state</legend>
              {REQUIRE_KNOWN_OPTIONS.map((o) => <Check key={o.value} label={o.label} checked={draft.require_known.includes(o.value)} onChange={() => set('require_known', toggle(draft.require_known, o.value))} />)}
            </fieldset>
          </details>
          <div className="btn-row" style={{ marginTop: 12 }}><button className="btn btn-primary" type="submit">Apply filters</button></div>
        </form>

        <section aria-label="Search results">
          {chips.length > 0 && (
            <ul className="chips plain" aria-label="Active filters">
              {chips.map((c) => <li key={c.label} className="chip" style={{ listStyle: 'none' }}>{c.label}<button type="button" onClick={c.remove} aria-label={`Remove filter ${c.label}`}>{'×'}</button></li>)}
            </ul>
          )}
          <div aria-live="polite" aria-busy={results.loading}>
            {results.loading && !data && <Loading label="Searching events" />}
            {results.error && !data && <ErrorState error={results.error} onRetry={results.reload} title="Search failed" />}
            {data && (
              <>
                <div className="panel-head" style={{ marginBottom: 8 }}>
                  <p style={{ margin: 0 }}><strong>{data.total.toLocaleString('en-IN')}</strong> {data.total === 1 ? 'event' : 'events'} found{results.loading ? ' (updating…)' : ''}</p>
                  <div style={{ minWidth: 190 }}>
                    <Select label="Sort by" value={applied.sort} onChange={(e) => commit({ ...applied, sort: e.target.value as Filters['sort'] })}
                      options={[{ value: 'relevance', label: 'Relevance' }, { value: 'date', label: 'Start date' }, { value: 'deadline', label: 'Registration deadline' }]} />
                  </div>
                </div>
                {data.interpretation.understood.length > 0 && (
                  <Notice tone="info" live={false}><strong>What we understood:</strong> {data.interpretation.understood.join('; ')}.</Notice>
                )}
                {data.broadened && <Notice tone="warn">No exact match, so this search was broadened. Check each result against what you wanted.</Notice>}
                {data.notes.map((n) => <Notice key={n} tone="info" live={false}>{n}</Notice>)}
                {data.index.state === 'degraded' && (
                  <Notice tone="warn">Some sources could not be reached recently ({data.index.connectors_failing.map((c) => c.name).join(', ')}). Results may be out of date. Last successful sync {fmtRelative(data.index.last_successful_sync_at)}.</Notice>
                )}
                {data.state === 'unavailable' && <Empty title="The event index is empty">No events have been indexed yet, so there is nothing to search. An administrator can run a source sync.</Empty>}
                {data.state === 'empty_result' && (
                  <Empty title="No events match" action={<button className="btn" onClick={clearAll}>Clear all filters</button>}>
                    Nothing in the index matches this search. Try fewer filters, or allow events that do not state a fee or deadline.
                    {' '}{data.index.scope}
                  </Empty>
                )}
                <div className="results">
                  {data.items.map((e) => <EventCardView key={e.id} e={e} />)}
                </div>
                <Pagination page={applied.page} pageSize={PAGE_SIZE} total={data.total} onPage={(p) => { setParams(filtersToSearchParams({ ...applied, page: p })); window.scrollTo({ top: 0 }) }} />
                <p className="small muted" style={{ marginTop: 16 }}>{data.index.scope}</p>
              </>
            )}
          </div>
        </section>
      </div>
    </div>
  )
}

export { EMPTY_FILTERS }
