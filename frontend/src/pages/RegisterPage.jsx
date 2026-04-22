import { useState, useEffect } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import OtpInput from 'react-otp-input'
import api from '../api/client'

export default function RegisterPage() {
  const [step, setStep] = useState(1)
  const [formData, setFormData] = useState({
    email: '',
    password: '',
    firstName: '',
    lastName: ''
  })
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [otp, setOtp] = useState('')
  const [countdown, setCountdown] = useState(60)
  const navigate = useNavigate()

  useEffect(() => {
    let timer
    if (step === 3 && countdown > 0) {
      timer = setInterval(() => setCountdown(c => c - 1), 1000)
    }
    return () => clearInterval(timer)
  }, [step, countdown])

  const handleNextStep = async (e) => {
    e.preventDefault()
    if (!formData.firstName || !formData.lastName || !formData.email) {
      setError('Please fill out all fields.')
      return
    }
    setError('')
    setLoading(true)
    
    try {
      const res = await api.get(`/auth/check-email?email=${encodeURIComponent(formData.email)}`)
      if (!res.data.available) {
        setError('This email is not available')
        return
      }
      setStep(2)
    } catch (err) {
      setError('Failed to verify email. Please try again.')
    } finally {
      setLoading(false)
    }
  }

  const handleRegister = async (e) => {
    e.preventDefault()
    if (!formData.password) {
      setError('Please create a password.')
      return
    }
    setLoading(true)
    setError('')

    try {
      await api.post('/auth/register', {
        email: formData.email,
        password: formData.password,
        name: `${formData.firstName} ${formData.lastName}`.trim(),
        company: 'Individual' // Default for now
      })
      setStep(3)
      setCountdown(60)
    } catch (err) {
      setError(err.response?.data?.detail || 'Registration failed. Please try again.')
    } finally {
      setLoading(false)
    }
  }

  const handleVerifyOTP = async (e) => {
    if (e) e.preventDefault()
    if (otp.length !== 6) {
      setError('Please enter the 6-digit code.')
      return
    }
    setLoading(true)
    setError('')
    try {
      await api.post('/auth/verify-otp', {
        email: formData.email,
        otp: otp
      })
      navigate('/login', { state: { message: 'Account verified! Please sign in.' } })
    } catch (err) {
      setError(err.response?.data?.detail || 'Invalid verification code.')
    } finally {
      setLoading(false)
    }
  }

  const handleResendOTP = async () => {
    setLoading(true)
    setError('')
    try {
      await api.post('/auth/resend-otp', { email: formData.email })
      setCountdown(60)
      setOtp('')
    } catch (err) {
      setError('Failed to resend code. Please try again.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="auth-split-container">
      <div className="auth-left">
        <div className="auth-header-top">
          <div className="gem-logo">
            <svg width="36" height="36" viewBox="0 0 24 24" fill="none">
              <path d="M12 2L22 10H2L12 2Z" fill="#ff7043"/>
              <path d="M22 10L12 22L2 10H22Z" fill="#00bcd4"/>
              <path d="M12 2L17 10H7L12 2Z" fill="#ffa726"/>
              <path d="M17 10L12 22L7 10H17Z" fill="#29b6f6"/>
            </svg>
          </div>
          <h1 className="auth-title">Create your Account</h1>
        </div>

        {step === 1 ? (
          <div className="auth-form-card">
            <form className="auth-form" onSubmit={handleNextStep}>
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

              {error && <div className="login-error" style={{ color: '#ff5252', fontSize: '0.85rem', marginBottom: '16px' }}>⚠️ {error}</div>}

              <button className="btn-continue" type="submit" disabled={loading}>
                {loading ? 'Checking...' : 'Continue'}
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
        ) : step === 2 ? (
          <>
            <div className="auth-form-card">
              <form className="auth-form" onSubmit={handleRegister}>
                <div className="form-group">
                  <label>Email</label>
                  <input
                    type="email"
                    value={formData.email}
                    disabled
                    style={{ color: '#888', background: '#222' }}
                  />
                </div>

                <div className="form-group" style={{ position: 'relative' }}>
                  <label>Password</label>
                  <input
                    type={showPassword ? "text" : "password"}
                    placeholder="Create a password"
                    value={formData.password}
                    onChange={(e) => setFormData({ ...formData, password: e.target.value })}
                    required
                    autoFocus
                    style={{ paddingRight: '40px' }}
                  />
                  <button 
                    type="button" 
                    onClick={() => setShowPassword(!showPassword)}
                    style={{ position: 'absolute', right: '12px', top: '34px', background: 'none', border: 'none', color: '#888', cursor: 'pointer', padding: 0 }}
                  >
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path>
                      <circle cx="12" cy="12" r="3"></circle>
                    </svg>
                  </button>
                </div>

                {error && <div className="login-error" style={{ color: '#ff5252', fontSize: '0.85rem', marginBottom: '16px' }}>⚠️ {error}</div>}

                <button className="btn-continue" type="submit" disabled={loading}>
                  {loading ? 'Creating Account...' : 'Continue'}
                </button>

                <div className="divider">
                  <span>OR</span>
                </div>

                <button type="button" className="btn-social">
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ marginRight: '8px' }}>
                    <path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"></path>
                    <polyline points="22,6 12,13 2,6"></polyline>
                  </svg>
                  Continue with email code
                </button>
              </form>
            </div>
            
            <div style={{ marginTop: '24px', display: 'flex', justifyContent: 'center' }}>
                <button type="button" onClick={() => setStep(1)} style={{ background: 'none', border: 'none', color: '#888', cursor: 'pointer', fontSize: '0.9rem', display: 'flex', alignItems: 'center', gap: '8px' }}>
                    &lt; Go back
                </button>
            </div>
          </>
        ) : (
          <div className="auth-form-card">
            <h1 className="auth-title" style={{ textAlign: 'center', marginBottom: '8px' }}>Verify your email</h1>
            <p style={{ textAlign: 'center', color: '#888', fontSize: '0.9rem', marginBottom: '24px' }}>
              Enter the code sent to <br />
              <strong style={{ color: '#fff' }}>{formData.email}</strong>
            </p>

            <form onSubmit={handleVerifyOTP}>
              <div className="otp-container">
                <OtpInput
                  value={otp}
                  onChange={setOtp}
                  numInputs={6}
                  renderSeparator={null}
                  renderInput={(props) => <input {...props} className="otp-input" />}
                  inputType="number"
                  shouldAutoFocus
                />
              </div>

              {error && <div className="login-error" style={{ color: '#ff5252', fontSize: '0.85rem', marginBottom: '16px', textAlign: 'center' }}>⚠️ {error}</div>}

              <button className="btn-continue" type="submit" disabled={loading || otp.length !== 6}>
                {loading ? 'Verifying...' : 'Verify & Finish'}
              </button>

              <div className="resend-container">
                Didn't receive a code? {' '}
                {countdown > 0 ? (
                  <span>Resend ({countdown})</span>
                ) : (
                  <button type="button" className="resend-link" onClick={handleResendOTP} disabled={loading}>
                    Resend
                  </button>
                )}
              </div>

              <Link to="/login" className="back-to-login">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M15 18l-6-6 6-6"/>
                </svg>
                Back to sign-in
              </Link>
            </form>
          </div>
        )}
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
