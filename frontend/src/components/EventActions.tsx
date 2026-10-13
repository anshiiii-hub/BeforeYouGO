import { useEffect, useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { api } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { COMPARE_EVENT, getTray, toggleTray } from '../lib/compare'
import { useSubmit } from './ui'

export function SaveButton({ eventId, saved, onChange, compact }: { eventId: string; saved: boolean; onChange?: (s: boolean) => void; compact?: boolean }) {
  const { user } = useAuth()
  const loc = useLocation()
  const [isSaved, setSaved] = useState(saved)
  const s = useSubmit()
  useEffect(() => setSaved(saved), [saved])
  if (!user) {
    return <Link className={`btn ${compact ? 'btn-sm' : ''}`} to="/login" state={{ next: loc.pathname + loc.search }}>Sign in to save</Link>
  }
  const toggle = async () => {
    const next = !isSaved
    const r = await s.run(() => (next ? api.put(`/me/saved/${eventId}`, {}) : api.del(`/me/saved/${eventId}`)), next ? 'Saved' : 'Removed')
    if (r !== undefined) { setSaved(next); onChange?.(next) }
  }
  return (
    <>
      <button className={`btn ${compact ? 'btn-sm' : ''} ${isSaved ? 'btn-on' : ''}`} aria-pressed={isSaved} onClick={toggle} disabled={s.busy}>
        {isSaved ? 'Saved' : 'Save'}
      </button>
      {s.error && <span className="msg-bad small" role="alert">{s.error}</span>}
    </>
  )
}

export function useTray() {
  const [tray, setTray] = useState(getTray())
  useEffect(() => {
    const h = () => setTray(getTray())
    window.addEventListener(COMPARE_EVENT, h)
    window.addEventListener('storage', h)
    return () => { window.removeEventListener(COMPARE_EVENT, h); window.removeEventListener('storage', h) }
  }, [])
  return tray
}

export function CompareButton({ id, title }: { id: string; title: string }) {
  const tray = useTray()
  const [msg, setMsg] = useState<string | null>(null)
  const inTray = tray.some((t) => t.id === id)
  return (
    <>
      <button className={`btn btn-sm ${inTray ? 'btn-on' : ''}`} aria-pressed={inTray} onClick={() => { const r = toggleTray({ id, title }); setMsg(r.ok ? null : r.reason ?? null) }}>
        {inTray ? 'In compare list' : 'Compare'}
      </button>
      {msg && <span className="msg-bad small" role="alert">{msg}</span>}
    </>
  )
}
