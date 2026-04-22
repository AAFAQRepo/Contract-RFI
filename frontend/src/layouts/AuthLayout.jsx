import { Outlet } from 'react-router-dom'

export default function AuthLayout() {
  return (
    <div className="auth-layout">
      <Outlet />
      <div className="login-background">
        <div className="bg-blob blob-1"></div>
        <div className="bg-blob blob-2"></div>
        <div className="bg-blob blob-3"></div>
      </div>
    </div>
  )
}
