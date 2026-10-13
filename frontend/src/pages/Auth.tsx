import { useState, type FormEvent } from 'react'
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom'
import { useAuth, homeFor } from '../auth/AuthContext'
import { Check, FormStatus, Select, TextField, useSubmit } from '../components/ui'
import { useTitle } from '../lib/useAsync'
import { Notice } from '../components/States'

function useNext(): string | null {
  const loc = useLocation()
  const s = loc.state as { next?: string } | null
  return s?.next && s.next.startsWith('/') ? s.next : null
}

export function Login() {
  useTitle('Sign in')
  const { login, user } = useAuth()
  const nav = useNavigate()
  const next = useNext()
  const loc = useLocation()
  const expired = (loc.state as { expired?: boolean } | null)?.expired
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const s = useSubmit()
  if (user && !s.busy) return <Navigate to={next ?? homeFor(user.role)} replace />
  const submit = async (e: FormEvent) => {
    e.preventDefault()
    const u = await s.run(() => login(email, password), 'Signed in.')
    if (u) nav(next ?? homeFor(u.role), { replace: true })
  }
  return (
    <div className="wrap page" style={{ maxWidth: 520 }}>
      <h1>Sign in</h1>
      {expired && <Notice tone="warn">Your session ended. Sign in again to continue.</Notice>}
      {next && !expired && <Notice tone="info">Sign in to continue to the page you asked for.</Notice>}
      <form className="panel" onSubmit={submit} noValidate>
        <TextField label="Email" type="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
        <TextField label="Password" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required />
        <div className="btn-row"><button className="btn btn-primary" disabled={s.busy || !email || !password}>Sign in</button></div>
        <FormStatus s={{ ...s, ok: null }} />
      </form>
      <p>New here? <Link to="/register" state={{ next }}>Create an account</Link>.</p>
    </div>
  )
}

export function Register() {
  useTitle('Create account')
  const { register, user } = useAuth()
  const nav = useNavigate()
  const next = useNext()
  const [form, setForm] = useState({ display_name: '', email: '', password: '', role: 'student' as 'student' | 'organizer' })
  const [agree, setAgree] = useState(false)
  const s = useSubmit()
  if (user && !s.busy) return <Navigate to={next ?? homeFor(user.role)} replace />
  const set = (k: keyof typeof form) => (e: { target: { value: string } }) => setForm({ ...form, [k]: e.target.value })
  const submit = async (e: FormEvent) => {
    e.preventDefault()
    const u = await s.run(() => register(form), 'Account created.')
    if (u) nav(next ?? homeFor(u.role), { replace: true })
  }
  return (
    <div className="wrap page" style={{ maxWidth: 560 }}>
      <h1>Create your account</h1>
      <p className="lead">Searching, comparing and the analyzer work without an account. An account lets you save events, get explained recommendations and give feedback.</p>
      <form className="panel" onSubmit={submit} noValidate>
        <TextField label="Your name" autoComplete="name" value={form.display_name} onChange={set('display_name')} required maxLength={120} />
        <TextField label="Email" type="email" autoComplete="email" value={form.email} onChange={set('email')} required />
        <TextField label="Password" type="password" autoComplete="new-password" value={form.password} onChange={set('password')} required minLength={10}
          hint="At least 10 characters. Mix letters, numbers and symbols; common passwords are rejected." />
        <Select label="I am joining as" value={form.role} onChange={set('role')}
          options={[{ value: 'student', label: 'A student looking for events' }, { value: 'organizer', label: 'An event organizer' }]}
          hint="Reviewer and administrator accounts are assigned by an administrator, not chosen here." />
        <Check checked={agree} onChange={(e) => setAgree(e.target.checked)}
          label="I understand BeforeYouGo stores my account details and preferences only to run this service, and I can edit or delete them at any time." />
        <div className="btn-row"><button className="btn btn-primary" disabled={s.busy || !agree || !form.email || !form.password || !form.display_name}>Create account</button></div>
        <FormStatus s={{ ...s, ok: null }} />
      </form>
      <p>Already registered? <Link to="/login" state={{ next }}>Sign in</Link>.</p>
    </div>
  )
}
