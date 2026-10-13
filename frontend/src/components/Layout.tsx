import { useState } from 'react'
import { Link, NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { useAuth, homeFor } from '../auth/AuthContext'
import { clearTray, removeFromTray } from '../lib/compare'
import { useTray } from './EventActions'

function Logo() {
  return (
    <Link to="/" className="logo" aria-label="BeforeYouGo home">
      <svg width="28" height="28" viewBox="0 0 32 32" aria-hidden="true"><rect width="32" height="32" rx="8" fill="#16234a" /><path d="M8 17l5 5 11-12" fill="none" stroke="#22d3ee" strokeWidth="3.5" strokeLinecap="round" strokeLinejoin="round" /></svg>
      <span>BeforeYouGo</span>
    </Link>
  )
}

function CompareTray() {
  const tray = useTray()
  const nav = useNavigate()
  const loc = useLocation()
  if (tray.length === 0 || loc.pathname.startsWith('/compare')) return null
  return (
    <aside className="tray" aria-label="Events selected for comparison">
      <div className="tray-inner">
        <strong>Compare ({tray.length}/4)</strong>
        <ul>
          {tray.map((t) => (
            <li key={t.id}>
              <span className="tray-title">{t.title}</span>
              <button className="icon-btn" onClick={() => removeFromTray(t.id)} aria-label={`Remove ${t.title} from compare list`}>{'×'}</button>
            </li>
          ))}
        </ul>
        <button className="btn btn-primary btn-sm" disabled={tray.length < 2} onClick={() => nav(`/compare?ids=${tray.map((t) => t.id).join(',')}`)}>
          {tray.length < 2 ? 'Add one more to compare' : 'Compare side by side'}
        </button>
        <button className="btn btn-sm" onClick={clearTray}>Clear</button>
      </div>
    </aside>
  )
}

export function Layout() {
  const { user, logout, sessionExpired } = useAuth()
  const [open, setOpen] = useState(false)
  const nav = useNavigate()
  const close = () => setOpen(false)
  return (
    <>
      <a className="skip" href="#main">Skip to content</a>
      <header className="site-header">
        <div className="wrap bar">
          <Logo />
          <button className="menu-btn btn btn-sm" aria-expanded={open} aria-controls="primary-nav" onClick={() => setOpen((o) => !o)}>{open ? 'Close' : 'Menu'}</button>
          <nav id="primary-nav" className={`primary ${open ? 'open' : ''}`} aria-label="Primary" onClick={close}>
            <NavLink to="/discover">Discover</NavLink>
            <NavLink to="/compare">Compare</NavLink>
            <NavLink to="/analyzer">Promise analyzer</NavLink>
            <NavLink to="/about">Methodology</NavLink>
            {user && <NavLink to={homeFor(user.role)}>{user.role === 'student' ? 'My workspace' : user.role === 'organizer' ? 'Organizer' : 'Admin'}</NavLink>}
            <span className="spacer" />
            {user ? (
              <>
                <span className="who" title={user.email}>{user.display_name} <small>({user.role})</small></span>
                <button className="btn btn-sm" onClick={async () => { await logout(); nav('/') }}>Sign out</button>
              </>
            ) : (
              <>
                <NavLink to="/login">Sign in</NavLink>
                <Link className="btn btn-primary btn-sm" to="/register">Create account</Link>
              </>
            )}
          </nav>
        </div>
      </header>
      {sessionExpired && !user && (
        <div className="notice notice-warn wrap" role="status">Your session ended, so you were signed out. <Link to="/login">Sign in again</Link>.</div>
      )}
      <main id="main" tabIndex={-1}><Outlet /></main>
      <CompareTray />
      <footer className="site-footer">
        <div className="wrap">
          <p><strong>BeforeYouGo</strong> checks what events promise. It does not rate organizers or guarantee outcomes. Unknown stays unknown.</p>
          <p className="small"><Link to="/about">How it works and what it cannot do</Link> {'·'} <a href="/api/docs" target="_blank" rel="noopener noreferrer">API documentation</a></p>
        </div>
      </footer>
    </>
  )
}
