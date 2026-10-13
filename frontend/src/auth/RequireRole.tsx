import type { ReactNode } from 'react'
import { Navigate, useLocation } from 'react-router-dom'
import type { Role } from '../api/types'
import { useAuth } from './AuthContext'
import { Forbidden, Loading } from '../components/States'

/** Client-side convenience only; the server enforces every permission. */
export function RequireRole({ roles, children }: { roles?: Role[]; children: ReactNode }) {
  const { user, loading, sessionExpired } = useAuth()
  const loc = useLocation()
  if (loading) return <Loading label="Checking your session" />
  if (!user) {
    return <Navigate to="/login" replace state={{ next: loc.pathname + loc.search, expired: sessionExpired }} />
  }
  if (roles && !roles.includes(user.role)) {
    return <Forbidden role={user.role} needed={roles} />
  }
  return <>{children}</>
}
