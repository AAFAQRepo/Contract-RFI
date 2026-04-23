import { useState, useEffect } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { Logo } from '../components/common/Icon'
import { useAuth } from '../contexts/AuthContext'

export default function LoginPage() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const { login, isAuthenticated } = useAuth()
  const navigate = useNavigate()

  useEffect(() => {
    if (isAuthenticated) {
      navigate('/dashboard', { replace: true })
    }
  }, [isAuthenticated, navigate])
  const handleLogin = async (e) => {
    e.preventDefault()
    setLoading(true)
    setError('')

    try {
      await login(email, password)
      navigate('/dashboard')
    } catch (err) {
      setError(err.response?.data?.detail || 'Login failed. Please check your credentials.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="auth-single-container">
      <div className="auth-header-top">
        <h1 className="auth-title">Welcome!</h1>
      </div>

      <div className="auth-form-card">
        <form className="auth-form" onSubmit={handleLogin}>
          <div className="form-group">
            <label>Email</label>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="Your email address"
              required
            />
          </div>

          <div className="form-group">
            <label>Password</label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="••••••••"
              required
            />
          </div>

          {error && <div className="login-error" style={{ color: '#ff5252', fontSize: '0.85rem', marginBottom: '16px' }}>⚠️ {error}</div>}

          <button className="btn-continue" type="submit" disabled={loading}>
            {loading ? 'Processing...' : 'Continue'}
          </button>

          <div className="divider">
            <span>OR</span>
          </div>

          <button type="button" className="btn-social">
            <img src="https://www.gstatic.com/images/branding/product/1x/gsa_512dp.png" width="20" alt="" />
            Continue with Google
          </button>

          <div className="auth-footer">
            <p>Don't have an account? <Link to="/register">Sign up</Link></p>
          </div>
        </form>
      </div>
    </div>
  )
}

