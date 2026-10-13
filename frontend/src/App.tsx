import { lazy, Suspense } from 'react'
import { Route, Routes } from 'react-router-dom'
import { Layout } from './components/Layout'
import { RequireRole } from './auth/RequireRole'
import { Loading, Empty } from './components/States'
import { Landing } from './pages/Landing'
import { Discover } from './pages/Discover'
import { EventDetailPage } from './pages/EventDetail'
import { ComparePage } from './pages/Compare'
import { AnalyzerPage } from './pages/Analyzer'
import { About } from './pages/About'
import { Login, Register } from './pages/Auth'
import { Link } from 'react-router-dom'

const StudentArea = lazy(() => import('./pages/student/StudentArea'))
const OrganizerArea = lazy(() => import('./pages/organizer/OrganizerArea'))
const AdminArea = lazy(() => import('./pages/admin/AdminArea'))

export function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Landing />} />
        <Route path="discover" element={<Discover />} />
        <Route path="events/:id" element={<EventDetailPage />} />
        <Route path="compare" element={<ComparePage />} />
        <Route path="analyzer" element={<AnalyzerPage />} />
        <Route path="about" element={<About />} />
        <Route path="login" element={<Login />} />
        <Route path="register" element={<Register />} />
        <Route path="me/*" element={<RequireRole><Suspense fallback={<Loading />}><StudentArea /></Suspense></RequireRole>} />
        <Route path="organizer/*" element={<RequireRole roles={['organizer', 'admin', 'reviewer']}><Suspense fallback={<Loading />}><OrganizerArea /></Suspense></RequireRole>} />
        <Route path="admin/*" element={<RequireRole roles={['admin', 'reviewer']}><Suspense fallback={<Loading />}><AdminArea /></Suspense></RequireRole>} />
        <Route path="*" element={<div className="wrap page"><Empty title="Page not found" action={<Link className="btn" to="/">Go home</Link>}>That address does not exist in BeforeYouGo.</Empty></div>} />
      </Route>
    </Routes>
  )
}
