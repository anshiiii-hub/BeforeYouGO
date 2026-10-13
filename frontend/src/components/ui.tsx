import { useCallback, useId, useState, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes, type TextareaHTMLAttributes } from 'react'
import { NavLink } from 'react-router-dom'
import { describeError } from '../api/client'
import type { Tone } from '../lib/labels'
import { CLAIM_STATUS, EVIDENCE_KIND, ACCESS_STATE, SEVERITY_TONE, titleCase } from '../lib/labels'
import type { AccessState, EvidenceKind, Fee } from '../api/types'
import { feeView } from '../lib/format'

export function Badge({ tone = 'neutral', children, title }: { tone?: Tone; children: ReactNode; title?: string }) {
  return <span className={`badge badge-${tone}`} title={title}>{children}</span>
}

export function ClaimStatusBadge({ status }: { status: string }) {
  const s = (CLAIM_STATUS as Record<string, { label: string; tone: Tone; help: string }>)[status]
  return <Badge tone={s?.tone ?? 'neutral'} title={s?.help}>{s?.label ?? titleCase(status)}</Badge>
}
export function EvidenceKindBadge({ kind }: { kind: string }) {
  const k = (EVIDENCE_KIND as Record<string, { label: string; tone: Tone; help: string }>)[kind as EvidenceKind]
  return <Badge tone={k?.tone ?? 'neutral'} title={k?.help}>{k?.label ?? titleCase(kind)}</Badge>
}
export function AccessStateBadge({ state }: { state: string }) {
  const a = (ACCESS_STATE as Record<string, { label: string; tone: Tone; help: string }>)[state as AccessState]
  return <Badge tone={a?.tone ?? 'unknown'} title={a?.help}>{a?.label ?? titleCase(state)}</Badge>
}
export function SeverityBadge({ severity }: { severity: string }) {
  return <Badge tone={SEVERITY_TONE[severity] ?? 'neutral'}>{titleCase(severity)} severity</Badge>
}

export function FeeBadge({ fee, detail = false }: { fee: Fee | null | undefined; detail?: boolean }) {
  const v = feeView(fee)
  return (
    <span className={`fee fee-${v.tone}`} data-testid="fee">
      <span className="fee-text">{v.text}</span>
      {v.uncertain && <span className="fee-caveat">{detail ? v.caveat : 'unconfirmed'}</span>}
    </span>
  )
}

/** Ledger of known vs unknown details: filled cells are stated facts, hollow cells are unknown. */
export function Ledger({ filled, total, label }: { filled: number; total: number; label?: string }) {
  const cells = Array.from({ length: total }, (_, i) => i < filled)
  return (
    <span className="ledger" role="img" aria-label={label ?? `${filled} of ${total} details stated`}>
      {cells.map((on, i) => <i key={i} className={on ? 'on' : ''} />)}
    </span>
  )
}

export function Panel({ title, children, actions, id, tone }: { title?: ReactNode; children: ReactNode; actions?: ReactNode; id?: string; tone?: 'plain' }) {
  return (
    <section className={`panel ${tone === 'plain' ? 'panel-plain' : ''}`} id={id} aria-labelledby={id ? `${id}-h` : undefined}>
      {(title || actions) && (
        <header className="panel-head">
          {title && <h2 id={id ? `${id}-h` : undefined}>{title}</h2>}
          {actions && <div className="panel-actions">{actions}</div>}
        </header>
      )}
      {children}
    </section>
  )
}

export function PageHead({ title, lead, actions }: { title: string; lead?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="page-head">
      <div>
        <h1>{title}</h1>
        {lead && <p className="lead">{lead}</p>}
      </div>
      {actions && <div className="page-actions">{actions}</div>}
    </div>
  )
}

export function Tabs({ items }: { items: { to: string; label: string; end?: boolean }[] }) {
  return (
    <nav className="tabs" aria-label="Sections">
      {items.map((i) => <NavLink key={i.to} to={i.to} end={i.end} className={({ isActive }) => (isActive ? 'active' : '')}>{i.label}</NavLink>)}
    </nav>
  )
}

interface FieldProps { label: string; hint?: string; error?: string | null; children: (id: string, describedBy: string | undefined) => ReactNode; required?: boolean }
export function Field({ label, hint, error, children, required }: FieldProps) {
  const id = useId()
  const hid = hint ? `${id}-hint` : undefined
  const eid = error ? `${id}-err` : undefined
  const described = [hid, eid].filter(Boolean).join(' ') || undefined
  return (
    <div className="field">
      <label htmlFor={id}>{label}{required && <span className="req" aria-hidden="true"> *</span>}</label>
      {children(id, described)}
      {hint && <p className="hint" id={hid}>{hint}</p>}
      {error && <p className="field-error" id={eid}>{error}</p>}
    </div>
  )
}

export function TextField({ label, hint, error, required, ...rest }: { label: string; hint?: string; error?: string | null } & InputHTMLAttributes<HTMLInputElement>) {
  return <Field label={label} hint={hint} error={error} required={required}>{(id, d) => <input id={id} aria-describedby={d} aria-invalid={!!error || undefined} required={required} {...rest} />}</Field>
}
export function TextArea({ label, hint, error, required, ...rest }: { label: string; hint?: string; error?: string | null } & TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <Field label={label} hint={hint} error={error} required={required}>{(id, d) => <textarea id={id} aria-describedby={d} aria-invalid={!!error || undefined} required={required} rows={4} {...rest} />}</Field>
}
export function Select({ label, hint, error, options, placeholder, ...rest }: { label: string; hint?: string; error?: string | null; options: { value: string; label: string }[]; placeholder?: string } & SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <Field label={label} hint={hint} error={error}>
      {(id, d) => (
        <select id={id} aria-describedby={d} {...rest}>
          {placeholder !== undefined && <option value="">{placeholder}</option>}
          {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
        </select>
      )}
    </Field>
  )
}
export function Check({ label, hint, ...rest }: { label: ReactNode; hint?: string } & InputHTMLAttributes<HTMLInputElement>) {
  return (
    <label className="check">
      <input type="checkbox" {...rest} />
      <span>{label}{hint && <small className="hint"> {hint}</small>}</span>
    </label>
  )
}

export interface SubmitState { busy: boolean; error: string | null; ok: string | null }
/** Wraps an async action with busy / error / success state for forms and buttons. */
export function useSubmit() {
  const [state, setState] = useState<SubmitState>({ busy: false, error: null, ok: null })
  const run = useCallback(async <T,>(fn: () => Promise<T>, okMessage?: string): Promise<T | undefined> => {
    setState({ busy: true, error: null, ok: null })
    try {
      const r = await fn()
      setState({ busy: false, error: null, ok: okMessage ?? 'Done.' })
      return r
    } catch (e) {
      setState({ busy: false, error: describeError(e), ok: null })
      return undefined
    }
  }, [])
  const reset = useCallback(() => setState({ busy: false, error: null, ok: null }), [])
  return { ...state, run, reset }
}

export function FormStatus({ s }: { s: SubmitState }) {
  return (
    <div className="form-status" aria-live="polite">
      {s.busy && <span className="muted">Working…</span>}
      {s.error && <span className="msg-bad" role="alert">{s.error}</span>}
      {s.ok && <span className="msg-good">{s.ok}</span>}
    </div>
  )
}

export function Pagination({ page, pageSize, total, onPage }: { page: number; pageSize: number; total: number; onPage: (p: number) => void }) {
  const pages = Math.max(1, Math.ceil(total / pageSize))
  if (pages <= 1) return null
  return (
    <nav className="pagination" aria-label="Pagination">
      <button className="btn btn-sm" disabled={page <= 1} onClick={() => onPage(page - 1)}>Previous</button>
      <span aria-live="polite">Page {page} of {pages}</span>
      <button className="btn btn-sm" disabled={page >= pages} onClick={() => onPage(page + 1)}>Next</button>
    </nav>
  )
}

export function KV({ items }: { items: [string, ReactNode][] }) {
  return (
    <dl className="kv">
      {items.map(([k, v]) => (<div key={k}><dt>{k}</dt><dd>{v}</dd></div>))}
    </dl>
  )
}

/** Unknown values render as muted "Not stated", never as zero / free / none. */
export function Unknown({ children }: { children?: ReactNode }) {
  return <span className="unknown">{children ?? 'Not stated'}</span>
}
export function Val({ v, unknown }: { v: ReactNode | null | undefined; unknown?: string }) {
  return v === null || v === undefined || v === '' ? <Unknown>{unknown}</Unknown> : <>{v}</>
}

export function ExternalLink({ href, children }: { href: string | null | undefined; children: ReactNode }) {
  if (!href || !/^https?:\/\//i.test(href)) return <>{children}</>
  return <a href={href} target="_blank" rel="noopener noreferrer">{children}<span className="sr-only"> (opens in a new tab)</span></a>
}
