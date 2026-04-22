import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Logo } from '../components/common/Icon'
import api from '../api/client'

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState('')
  const [loading, setLoading] = useState(false)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')

  const handleSubmit = async (e) => {
    e.preventDefault()
    setLoading(true)
    setMessage('')
    setError('')

    try {
      const res = await api.post('/auth/forgot-password', { email })
      setMessage(res.data.message)
    } catch (err) {
      setError(err.response?.data?.detail || 'Something went wrong. Please try again.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="login-page">
      <div className="login-card">
        <div className="login-header">
          <Logo />
          <h1 className="login-title">Reset Password</h1>
          <p className="login-subtitle">Enter your email to receive a reset link</p>
        </div>

        {message ? (
          <div className="login-success-view">
            <div style={{ fontSize: '3rem', marginBottom: 16 }}>📧</div>
            <p style={{ color: 'var(--text-secondary)', lineHeight: 1.6, marginBottom: 24 }}>{message}</p>
            <Link to="/login" className="login-submit" style={{ textDecoration: 'none', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              Back to Login
            </Link>
          </div>
        ) : (
          <form className="login-form" onSubmit={handleSubmit}>
            <div className="form-group">
              <label>Email Address</label>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="name@company.com"
                required
              />
            </div>

            {error && <div className="login-error">⚠️ {error}</div>}

            <button className="login-submit" type="submit" disabled={loading}>
              {loading ? 'Sending...' : 'Send Reset Link'}
            </button>
          </form>
        )}

        {!message && (
          <div className="login-footer">
            <p>Remember your password? <Link to="/login">Sign in</Link></p>
          </div>
        )}
      </div>
    </div>
  )
}
