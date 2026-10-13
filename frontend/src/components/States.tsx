import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { ApiError, describeError } from '../api/client'
import type { AsyncState } from '../lib/useAsync'

export function Loading({ label = 'Loading' }: { label?: string }) {
  return (
    <div className="state state-loading" role="status" aria-live="polite">
      <span className="spinner" aria-hidden="true" />
      <span>{label}…</span>
    </div>
  )
}

export function ErrorState({ error, onRetry, title }: { error: unknown; onRetry?: () => void; title?: string }) {
  const e = error instanceof ApiError ? error : null
  if (e?.isForbidden) return <Forbidden message={e.message} />
  if (e?.isAuth) {
    return (
      <div className="state state-error" role="alert">
        <h3>Sign in to continue</h3>
        <p>{e.message}</p>
        <Link className="btn btn-primary" to="/login">Sign in</Link>
      </div>
    )
  }
  return (
    <div className="state state-error" role="alert">
      <h3>{title ?? (e?.isNotFound ? 'Not found' : 'That did not load')}</h3>
      <p>{describeError(error)}</p>
      {e?.requestId && <p className="muted small">Reference: {e.requestId}</p>}
      {onRetry && !e?.isNotFound && <button className="btn" onClick={onRetry}>Try again</button>}
    </div>
  )
}

export function Forbidden({ message, role, needed }: { message?: string; role?: string; needed?: string[] }) {
  return (
    <div className="state state-forbidden" role="alert">
      <h3>You do not have access to this</h3>
      <p>{message ?? (role && needed ? `Your account is a ${role} account. This area is for ${needed.join(' or ')} accounts.` : 'Your account is not permitted to do this.')}</p>
      <p className="muted small">The server checks permissions on every request. If you think this is a mistake, ask an administrator to review your role.</p>
      <Link className="btn" to="/">Back to home</Link>
    </div>
  )
}

export function Empty({ title, children, action }: { title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="state state-empty">
      <h3>{title}</h3>
      {children && <p>{children}</p>}
      {action}
    </div>
  )
}

/** Renders the right state for an async result; children get the data when it is ready. */
export function DataState<T>({ state, children, loadingLabel, isEmpty, empty }: {
  state: AsyncState<T>
  children: (data: T) => ReactNode
  loadingLabel?: string
  isEmpty?: (d: T) => boolean
  empty?: ReactNode
}) {
  if (state.loading && !state.data) return <Loading label={loadingLabel} />
  if (state.error && !state.data) return <ErrorState error={state.error} onRetry={state.reload} />
  if (!state.data) return null
  if (isEmpty?.(state.data)) return <>{empty}</>
  return (
    <>
      {state.error && <ErrorState error={state.error} onRetry={state.reload} title="Refreshing failed" />}
      <div aria-busy={state.loading}>{children(state.data)}</div>
    </>
  )
}

export function Notice({ tone = 'info', children, live = true }: { tone?: 'info' | 'good' | 'warn' | 'bad'; children: ReactNode; live?: boolean }) {
  return (
    <div className={`notice notice-${tone}`} role={live ? (tone === 'bad' ? 'alert' : 'status') : undefined}>
      {children}
    </div>
  )
}
