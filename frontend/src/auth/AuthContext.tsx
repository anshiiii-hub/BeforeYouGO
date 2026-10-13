import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { api, getToken, setToken, SESSION_EXPIRED_EVENT } from '../api/client'
import type { Role, TokenResponse, User } from '../api/types'

interface AuthValue {
  user: User | null
  loading: boolean
  sessionExpired: boolean
  login: (email: string, password: string) => Promise<User>
  register: (input: { email: string; password: string; display_name: string; role: 'student' | 'organizer' }) => Promise<User>
  logout: () => Promise<void>
  refresh: () => Promise<void>
  applyToken: (t: TokenResponse) => void
}

const Ctx = createContext<AuthValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState<boolean>(() => !!getToken())
  const [sessionExpired, setSessionExpired] = useState(false)

  const refresh = useCallback(async () => {
    if (!getToken()) { setUser(null); setLoading(false); return }
    try { setUser(await api.get<User>('/me')) } catch { setUser(null) } finally { setLoading(false) }
  }, [])

  useEffect(() => { void refresh() }, [refresh])
  useEffect(() => {
    const onExpired = () => { setUser(null); setSessionExpired(true) }
    window.addEventListener(SESSION_EXPIRED_EVENT, onExpired)
    return () => window.removeEventListener(SESSION_EXPIRED_EVENT, onExpired)
  }, [])

  const applyToken = useCallback((t: TokenResponse) => { setToken(t.access_token); setUser(t.user); setSessionExpired(false); setLoading(false) }, [])

  const value = useMemo<AuthValue>(() => ({
    user, loading, sessionExpired, refresh, applyToken,
    login: async (email, password) => {
      const t = await api.post<TokenResponse>('/auth/login', { email, password })
      applyToken(t)
      return t.user
    },
    register: async (input) => {
      const t = await api.post<TokenResponse>('/auth/register', input)
      applyToken(t)
      return t.user
    },
    logout: async () => {
      try { await api.post('/auth/logout') } catch { /* token may already be invalid; clear locally regardless */ }
      setToken(null)
      setUser(null)
    },
  }), [user, loading, sessionExpired, refresh, applyToken])

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function useAuth(): AuthValue {
  const v = useContext(Ctx)
  if (!v) throw new Error('useAuth must be used inside AuthProvider')
  return v
}

export const isStaff = (r?: Role) => r === 'reviewer' || r === 'admin'
export const canOrganize = (r?: Role) => r === 'organizer' || r === 'admin' || r === 'reviewer'
export function homeFor(role: Role): string {
  return role === 'organizer' ? '/organizer' : role === 'admin' || role === 'reviewer' ? '/admin' : '/me'
}
