import { useState } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { Logo, Icon } from '../components/common/Icon'
import api from '../api/client'

export default function RegisterPage() {
  const [formData, setFormData] = useState({
    email: '',
    password: 'password_auto_gen', // Simplified for the 'Continue' flow
    firstName: '',
    lastName: ''
  })
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const navigate = useNavigate()

  const handleRegister = async (e) => {
    e.preventDefault()
    setLoading(true)
    setError('')

    try {
      // In a real flow, this 'Continue' might just be the first step
      // For now, we'll fulfill the registration
      await api.post('/auth/register', {
        email: formData.email,
        password: formData.password,
        name: `${formData.firstName} ${formData.lastName}`.trim(),
        company: 'Individual' // Default for now
      })
      navigate('/dashboard')
    } catch (err) {
      setError(err.response?.data?.detail || 'Registration failed. Please try again.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="auth-split-container">
      <div className="auth-left">
        <div className="auth-header-top">
          <h1 className="auth-title">Create your Account</h1>
        </div>

        <div className="auth-form-card">
          <form className="auth-form" onSubmit={handleRegister}>
            <div className="form-row">
              <div className="form-group">
                <label>First name</label>
                <input
                  type="text"
                  placeholder="Your first name"
                  value={formData.firstName}
                  onChange={(e) => setFormData({ ...formData, firstName: e.target.value })}
                  required
                />
              </div>
              <div className="form-group">
                <label>Last name</label>
                <input
                  type="text"
                  placeholder="Your last name"
                  value={formData.lastName}
                  onChange={(e) => setFormData({ ...formData, lastName: e.target.value })}
                  required
                />
              </div>
            </div>

            <div className="form-group">
              <label>Email</label>
              <input
                type="email"
                placeholder="Your email address"
                value={formData.email}
                onChange={(e) => setFormData({ ...formData, email: e.target.value })}
                required
              />
            </div>

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
              <p>Already have an account? <Link to="/login">Sign in</Link></p>
            </div>
          </form>
        </div>
      </div>

      <div className="auth-right">
        <div className="auth-info-content">
          <h2 className="info-title">Join 4,000+ law firms and in-house teams using Contract RFI</h2>
          
          <ul className="info-list">
            <li>
              <span className="check-icon">✓</span>
              Draft quickly with AI, informed by your past precedents
            </li>
            <li>
              <span className="check-icon">✓</span>
              Spot issues, add precise redlines
            </li>
            <li>
              <span className="check-icon">✓</span>
              Streamline negotiations with custom Playbooks
            </li>
            <li>
              <span className="check-icon">✓</span>
              7-day trial, no credit card required. Cancel anytime
            </li>
          </ul>

          <div className="classic-quote">
            <blockquote>
              "Contract RFI has completely transformed our workflow. It's like having a senior partner review every redline, instantly."
            </blockquote>
            <p className="quote-author">— Sarah J., General Counsel</p>
          </div>
        </div>
      </div>
    </div>
  )
}
