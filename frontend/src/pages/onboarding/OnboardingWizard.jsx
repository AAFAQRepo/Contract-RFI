import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Logo, Icon } from '../../components/common/Icon'
import api from '../../api/client'
import { useAuth } from '../../contexts/AuthContext'

const STEPS = [
  { id: 'welcome', title: 'Welcome' },
  { id: 'profile', title: 'Profile' },
  { id: 'plan', title: 'Plan' },
  { id: 'upload', title: 'Finish' }
]

export default function OnboardingWizard() {
  const [step, setStep] = useState(0)
  const [data, setData] = useState({
    use_case: 'Contract Review',
    company_name: '',
    preferred_language: 'en',
    selected_plan: 'free'
  })
  const [loading, setLoading] = useState(false)
  const navigate = useNavigate()
  const { user } = useAuth()

  const handleNext = () => {
    if (step < STEPS.length - 1) setStep(step + 1)
    else finishOnboarding()
  }

  const finishOnboarding = async () => {
    setLoading(true)
    try {
      await api.post('/auth/onboarding', data)
      navigate('/')
    } catch (err) {
      alert('Something went wrong. Please try again.')
    } finally {
      setLoading(false)
    }
  }

  const renderStep = () => {
    switch (STEPS[step].id) {
      case 'welcome':
        return (
          <div className="onboarding-step">
            <h1>Welcome, {user?.name || 'Legal Professional'}!</h1>
            <p>Let's set up your workspace to help you review contracts and respond to RFIs 10x faster.</p>
            <div style={{ marginTop: 40 }}>
              <button className="login-submit" onClick={handleNext}>Get Started</button>
            </div>
          </div>
        )
      case 'profile':
        return (
          <div className="onboarding-step">
            <h2>About your work</h2>
            <p>Help us customize your experience.</p>
            <div className="login-form" style={{ textAlign: 'left', marginTop: 24 }}>
              <div className="form-group">
                <label>Company / Firm Name</label>
                <input 
                  type="text" value={data.company_name} 
                  onChange={e => setData({ ...data, company_name: e.target.value })} 
                  placeholder="Acme Legal" 
                />
              </div>
              <div className="form-group">
                <label>Primary Use Case</label>
                <select 
                  value={data.use_case} 
                  onChange={e => setData({ ...data, use_case: e.target.value })}
                  style={{ width: '100%', padding: '10px 14px', borderRadius: 8, border: '1px solid var(--border)', fontSize: '0.9rem' }}
                >
                  <option>Contract Review</option>
                  <option>RFI Response</option>
                  <option>Legal Research</option>
                  <option>Due Diligence</option>
                  <option>Other</option>
                </select>
              </div>
            </div>
            <div style={{ marginTop: 40, display: 'flex', gap: 12 }}>
              <button className="topbar-btn" onClick={() => setStep(step - 1)}>Back</button>
              <button className="login-submit" onClick={handleNext}>Continue</button>
            </div>
          </div>
        )
      case 'plan':
        return (
          <div className="onboarding-step">
            <h2>Select your plan</h2>
            <p>Choose the level of AI power you need. You can always change this later.</p>
            <div className="plan-selection" style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginTop: 24 }}>
              <div 
                className={`plan-card ${data.selected_plan === 'free' ? 'active' : ''}`} 
                onClick={() => setData({ ...data, selected_plan: 'free' })}
                style={{ padding: 16, border: '2px solid', borderColor: data.selected_plan === 'free' ? 'var(--accent)' : 'var(--border)', borderRadius: 12, cursor: 'pointer', textAlign: 'left' }}
              >
                <div style={{ fontWeight: 600, marginBottom: 4 }}>Free</div>
                <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>5 Docs · 50 Queries / mo</div>
                <div style={{ fontSize: '1.2rem', fontWeight: 700, marginTop: 12 }}>$0<span style={{ fontSize: '0.8rem', fontWeight: 400 }}>/mo</span></div>
              </div>
              <div 
                className={`plan-card ${data.selected_plan === 'pro' ? 'active' : ''}`} 
                onClick={() => setData({ ...data, selected_plan: 'pro' })}
                style={{ padding: 16, border: '2px solid', borderColor: data.selected_plan === 'pro' ? 'var(--accent)' : 'var(--border)', borderRadius: 12, cursor: 'pointer', textAlign: 'left' }}
              >
                <div style={{ fontWeight: 600, marginBottom: 4 }}>Pro</div>
                <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>50 Docs · 500 Queries / mo</div>
                <div style={{ fontSize: '1.2rem', fontWeight: 700, marginTop: 12 }}>$29<span style={{ fontSize: '0.8rem', fontWeight: 400 }}>/mo</span></div>
              </div>
            </div>
            <div style={{ marginTop: 40, display: 'flex', gap: 12 }}>
              <button className="topbar-btn" onClick={() => setStep(step - 1)}>Back</button>
              <button className="login-submit" onClick={handleNext}>Select Plan</button>
            </div>
          </div>
        )
      case 'upload':
        return (
          <div className="onboarding-step">
            <div style={{ fontSize: '3rem', marginBottom: 16 }}>🚀</div>
            <h2>You're all set!</h2>
            <p>Your workspace is ready. You can now start uploading your first contract or RFI document.</p>
            <div style={{ marginTop: 40 }}>
              <button className="login-submit" onClick={finishOnboarding} disabled={loading}>
                {loading ? 'Finalizing...' : 'Enter Workspace'}
              </button>
            </div>
          </div>
        )
    }
  }

  return (
    <div className="onboarding-wizard">
      <div className="onboarding-card">
        <div className="onboarding-header">
          <Logo />
          <div className="onboarding-progress">
            {STEPS.map((s, i) => (
              <div key={s.id} className={`progress-dot ${i <= step ? 'active' : ''}`} />
            ))}
          </div>
        </div>
        {renderStep()}
      </div>
    </div>
  )
}
