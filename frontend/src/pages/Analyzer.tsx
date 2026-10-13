import { useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { api, describeError } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import type { AnalysisResult } from '../api/types'
import { GapCard } from './EventDetail'
import { Notice } from '../components/States'
import { Badge, FormStatus, PageHead, Panel, SeverityBadge, TextArea, TextField, useSubmit } from '../components/ui'
import { ClaimSummary } from '../components/ClaimPanel'
import { AccessStateBadge } from '../components/ui'
import { titleCase } from '../lib/labels'
import { useTitle } from '../lib/useAsync'
import type { Claim } from '../api/types'

type Mode = 'text' | 'url' | 'file'

export function ProviderBanner({ a }: { a: AnalysisResult['analysis'] }) {
  const ai = a.provider !== 'deterministic'
  return (
    <div className={`notice ${ai ? 'notice-info' : 'notice-warn'}`} data-testid="provider-banner" role="status">
      {ai ? (
        <><strong>Read by an AI model</strong> ({a.provider}{a.model ? `, ${a.model}` : ''}). Every claim was checked to quote the source text exactly; claims that did not were discarded.</>
      ) : a.llm_error ? (
        <><strong>Read by fixed rules (fallback).</strong> An AI service was configured but failed, so deterministic rule-based extraction was used instead. Reason: {a.llm_error}</>
      ) : (
        <><strong>Read by fixed rules, not AI.</strong> No AI provider is configured in this deployment, so deterministic rule-based extraction produced these results. It can miss unusual wording.</>
      )}
    </div>
  )
}

export function AnalyzerPage() {
  useTitle('Promise analyzer')
  const { user } = useAuth()
  const [mode, setMode] = useState<Mode>('text')
  const [text, setText] = useState('')
  const [url, setUrl] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [result, setResult] = useState<AnalysisResult | null>(null)
  const s = useSubmit()

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setResult(null)
    const r = await s.run(async () => {
      if (mode === 'text') return api.post<AnalysisResult>('/analyzer/text', { text })
      if (mode === 'url') return api.post<AnalysisResult>('/analyzer/url', { url })
      const fd = new FormData(); fd.append('file', file as File)
      return api.upload<AnalysisResult>('/analyzer/file', fd)
    }, 'Analysis complete.')
    if (r) setResult(r)
  }
  const ready = mode === 'text' ? text.trim().length >= 20 : mode === 'url' ? url.trim().length >= 8 : !!file
  return (
    <div className="wrap page">
      <PageHead title="AI Promise Analyzer" lead="Paste an event announcement, enter a web address or upload a file. Each promise is quoted exactly, rated for specificity and checked for missing details. Nothing here says a promise is true or false." />
      <form className="panel" onSubmit={submit}>
        <div role="tablist" aria-label="Input type" className="tabs" style={{ marginBottom: 16 }}>
          {([['text', 'Paste text'], ['url', 'Web address'], ['file', 'Upload file']] as [Mode, string][]).map(([m, l]) => (
            <a key={m} role="tab" href="#" aria-selected={mode === m} className={mode === m ? 'active' : ''} onClick={(ev) => { ev.preventDefault(); setMode(m) }}>{l}</a>
          ))}
        </div>
        {mode === 'text' && <TextArea label="Event text" rows={10} value={text} onChange={(e) => setText(e.target.value)} hint={`At least 20 characters. ${text.length.toLocaleString('en-IN')} entered.`} maxLength={60000} />}
        {mode === 'url' && <TextField label="Event page address" type="url" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://" hint="Pages are fetched respecting robots rules. If the server cannot reach the site, paste the text instead." />}
        {mode === 'file' && <TextField label="Flyer or brochure" type="file" accept=".pdf,.txt,.md,.docx,.png,.jpg,.jpeg,.webp,text/plain,application/pdf" onChange={(e) => setFile(e.target.files?.[0] ?? null)} hint="PDF, text, Word or image files. Size limits are set by the server." />}
        <div className="btn-row"><button className="btn btn-primary" disabled={!ready || s.busy}>{s.busy ? 'Analyzing…' : 'Analyze promises'}</button></div>
        <FormStatus s={{ ...s, ok: null }} />
      </form>
      {result && <Result r={result} mode={mode} text={text} url={url} signedIn={!!user} />}
    </div>
  )
}

function Result({ r, mode, text, url, signedIn }: { r: AnalysisResult; mode: Mode; text: string; url: string; signedIn: boolean }) {
  return (
    <div aria-live="polite">
      <ProviderBanner a={r.analysis} />
      {r.analysis.injection_flags.length > 0 && (
        <Notice tone="warn"><strong>Instruction-like text found.</strong> This document contains wording that tries to give instructions to an AI. It was treated as plain data and ignored.
          <ul className="bullets small">{r.analysis.injection_flags.map((f, i) => <li key={i}>{titleCase(f.type)}: {'“'}{f.excerpt}{'”'}</li>)}</ul></Notice>
      )}
      {r.notes.filter((n) => !/instructions to an AI|No AI provider is configured/.test(n)).map((n) => <Notice key={n} tone="info" live={false}>{n}</Notice>)}
      {r.retrieval && <p className="small muted">Fetched {r.retrieval.final_url} on {new Date(r.retrieval.retrieved_at).toLocaleString('en-IN')}{r.retrieval.title ? ` (page title: ${r.retrieval.title})` : ''}.</p>}
      {r.document && <p className="small muted">File {r.document.file_name}: read by {titleCase(r.document.method)}, {r.document.characters.toLocaleString('en-IN')} characters.</p>}
      <Panel title="Summary">
        <div className="stat-row">
          <div className="stat"><strong>{r.summary.claims}</strong><span>promises found</span></div>
          <div className="stat"><strong>{r.summary.vague_claims}</strong><span>vague</span></div>
          <div className="stat"><strong>{r.summary.gaps}</strong><span>information gaps</span></div>
          <div className="stat"><strong>{r.summary.high_severity_gaps}</strong><span>high severity</span></div>
        </div>
        <p className="small muted" style={{ marginTop: 12 }}>{r.caveat}</p>
      </Panel>
      <Panel title={`Promises (${r.claims.length})`}>
        {r.claims.length === 0 ? <p className="muted">No promises were found in this text. That does not mean the event promises nothing; try pasting the full announcement.</p> :
          r.claims.map((c, i) => (
            <div className="claim" key={i} data-testid="analysis-claim">
              <ClaimSummary c={{ ...(c as unknown as Claim), status: 'advertised' }} extra={<p className="small dim">Extraction confidence {c.extraction_confidence !== null ? Math.round((c.extraction_confidence ?? 0) * 100) + '%' : 'unknown'} (confidence is not evidence the promise is true).</p>} />
            </div>
          ))}
      </Panel>
      <Panel title={`Information gaps (${r.gaps.length})`}>
        {r.gaps.length === 0 ? <p className="muted">No gaps were flagged.</p> : r.gaps.map((g) => <GapCard key={g.rule_id} g={g} />)}
        {r.gaps.length > 0 && <p className="small muted"><SeverityBadge severity="high" /> gaps involve money or eligibility; each card explains how its severity was set.</p>}
      </Panel>
      {r.accessibility_detected.length > 0 && (
        <Panel title="Accessibility details found in the text"><ul className="plain">{r.accessibility_detected.map((a) => <li key={a.item_key}><strong>{titleCase(a.item_key)}</strong> <AccessStateBadge state={a.state} /><div className="quote small">{'“'}{a.excerpt}{'”'}</div></li>)}</ul>
          <p className="small muted">Anything not listed here is not documented, which is unknown, not unavailable.</p></Panel>
      )}
      <Submit mode={mode} text={text} url={url} signedIn={signedIn} />
    </div>
  )
}

function Submit({ mode, text, url, signedIn }: { mode: Mode; text: string; url: string; signedIn: boolean }) {
  const [title, setTitle] = useState('')
  const [org, setOrg] = useState('')
  const [eventId, setEventId] = useState<string | null>(null)
  const s = useSubmit()
  if (mode === 'file') return null
  if (!signedIn) return <Panel title="Keep this as an event record"><p className="muted"><Link to="/login">Sign in</Link> to add this event to BeforeYouGo as a clearly labelled user-submitted record.</p></Panel>
  return (
    <Panel title="Keep this as an event record">
      <p className="muted">Adds a record labelled <em>user-submitted</em>. Only values found in this text are stored; everything else stays unknown.</p>
      {eventId ? <Notice tone="good">Saved. <Link to={`/events/${eventId}`}>Open the event record</Link>.</Notice> : mode === 'text' ? (
        <form onSubmit={async (e) => { e.preventDefault(); const r = await s.run(() => api.post<{ event_id: string }>('/events/submit-text', { title, text, organizer_name: org || null }), 'Record created.'); if (r) setEventId(r.event_id) }}>
          <TextField label="Event title" value={title} onChange={(e) => setTitle(e.target.value)} required minLength={3} />
          <TextField label="Organizer (optional)" value={org} onChange={(e) => setOrg(e.target.value)} />
          <p className="hint">The text must be at least 40 characters.</p>
          <button className="btn" disabled={s.busy || title.trim().length < 3 || text.trim().length < 40}>Create user-submitted record</button><FormStatus s={s} />
        </form>
      ) : (
        <div><button className="btn" disabled={s.busy} onClick={async () => { const r = await s.run(() => api.post<{ event_id?: string }>('/events/submit-url', { url }), 'Record created.'); if (r?.event_id) setEventId(r.event_id) }}>Create user-submitted record from this page</button><FormStatus s={s} /></div>
      )}
    </Panel>
  )
}

export { Badge, describeError }
