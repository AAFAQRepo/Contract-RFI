import { Navigate, Outlet } from 'react-router-dom'
import { useAuth } from '../../contexts/AuthContext'

/**
 * Route guard — redirects unauthenticated users to /login.
 * Wrap protected routes with this component.
 */
export default function ProtectedRoute({ requireOnboarded = false }) {
  const { isAuthenticated, user } = useAuth()

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />
  }

  if (requireOnboarded && user && !user.onboarding_completed) {
    return <Navigate to="/onboarding" replace />
  }

  return <Outlet />
}
