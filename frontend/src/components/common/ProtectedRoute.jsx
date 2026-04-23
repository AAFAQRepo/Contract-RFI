import { Navigate, Outlet } from 'react-router-dom'
import { useAuth } from '../../contexts/AuthContext'

/**
 * Route guard — redirects unauthenticated users to /login.
 * Wrap protected routes with this component.
 */
export default function ProtectedRoute() {
  const { isAuthenticated, token } = useAuth()
  console.log('ProtectedRoute: isAuthenticated=', isAuthenticated, 'hasToken=', !!token)

  if (!isAuthenticated) {
    console.log('ProtectedRoute: Redirecting to /login')
    return <Navigate to="/login" replace />
  }

  return <Outlet />
}
