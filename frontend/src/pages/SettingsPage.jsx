import { useState } from 'react'
import api from '../api/client'
import { Icon } from '../components/common/Icon'
import { useAuth } from '../contexts/AuthContext'
import { useSubscription } from '../contexts/SubscriptionContext'
import { useToast } from '../contexts/ToastContext'

export default function SettingsPage() {
  const { user, setUser } = useAuth()
  const { subscription } = useSubscription()
  const { addToast } = useToast()
  const [activeTab, setActiveTab] = useState('profile')
  const [loading, setLoading] = useState(false)

  // Profile Form State
  const [profile, setProfile] = useState({
    name: user?.name || '',
    company: user?.company || '',
    email: user?.email || ''
  })

  // Password Form State
  const [passwords, setPasswords] = useState({
    old: '',
    new: '',
    confirm: ''
  })

  const handleUpdateProfile = async (e) => {
    e.preventDefault()
    setLoading(true)
    try {
      const res = await api.patch('/auth/me', {
        name: profile.name,
        company: profile.company
      })
      setUser(res.data)
      addToast('Profile updated successfully!', 'success')
    } catch (err) {
      addToast('Failed to update profile.', 'error')
    } finally {
      setLoading(false)
    }
  }

  const handleChangePassword = async (e) => {
    e.preventDefault()
    if (passwords.new !== passwords.confirm) {
      return addToast('New passwords do not match.', 'error')
    }
    setLoading(true)
    try {
      await api.post('/auth/change-password', {
        old_password: passwords.old,
        new_password: passwords.new
      })
      addToast('Password changed successfully!', 'success')
      setPasswords({ old: '', new: '', confirm: '' })
    } catch (err) {
      addToast(err.response?.data?.detail || 'Failed to change password.', 'error')
    } finally {
      setLoading(false)
    }
  }

  const tabs = [
    { id: 'profile', label: 'Profile', icon: 'user' },
    { id: 'security', label: 'Security', icon: 'lock' },
    { id: 'billing', label: 'Billing', icon: 'credit-card' },
    { id: 'api', label: 'API Keys', icon: 'key' },
  ]

  return (
    <div className="settings-page" style={{ padding: '40px 32px', maxWidth: 1000, margin: '0 auto' }}>
      <header style={{ marginBottom: 40 }}>
        <h1 style={{ fontSize: '1.8rem', fontWeight: 800, marginBottom: 8 }}>Account Settings</h1>
        <p style={{ color: 'var(--text-secondary)' }}>Manage your personal details and account preferences.</p>
      </header>

      <div style={{ display: 'grid', gridTemplateColumns: '240px 1fr', gap: 64 }}>
        <aside>
          <nav style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            {tabs.map(tab => (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 12,
                  padding: '12px 16px',
                  borderRadius: 10,
                  border: 'none',
                  background: activeTab === tab.id ? 'var(--accent)' : 'transparent',
                  color: activeTab === tab.id ? '#fff' : 'var(--text-primary)',
                  cursor: 'pointer',
                  textAlign: 'left',
                  fontSize: '0.95rem',
                  fontWeight: activeTab === tab.id ? 600 : 500,
                  transition: 'all 0.2s'
                }}
              >
                <Icon name={tab.icon} size={18} />
                {tab.label}
              </button>
            ))}
          </nav>
        </aside>

        <main style={{ background: '#fff', border: '1px solid var(--border)', borderRadius: 20, padding: 40 }}>

          {activeTab === 'profile' && (
            <form onSubmit={handleUpdateProfile}>
              <h2 style={{ fontSize: '1.2rem', marginBottom: 24 }}>Personal Information</h2>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
                <div className="form-group">
                  <label style={{ display: 'block', marginBottom: 8, fontSize: '0.9rem', fontWeight: 500 }}>Email Address</label>
                  <input type="email" value={profile.email} disabled className="login-input" style={{ opacity: 0.6, cursor: 'not-allowed' }} />
                  <p style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', marginTop: 4 }}>Email cannot be changed.</p>
                </div>
                <div className="form-group">
                  <label style={{ display: 'block', marginBottom: 8, fontSize: '0.9rem', fontWeight: 500 }}>Full Name</label>
                  <input 
                    type="text" 
                    value={profile.name} 
                    onChange={e => setProfile({...profile, name: e.target.value})}
                    className="login-input" 
                    placeholder="Enter your name"
                  />
                </div>
                <div className="form-group">
                  <label style={{ display: 'block', marginBottom: 8, fontSize: '0.9rem', fontWeight: 500 }}>Company</label>
                  <input 
                    type="text" 
                    value={profile.company} 
                    onChange={e => setProfile({...profile, company: e.target.value})}
                    className="login-input" 
                    placeholder="Enter company name"
                  />
                </div>
                <button type="submit" disabled={loading} className="login-submit" style={{ width: 'auto', padding: '12px 32px', marginTop: 12 }}>
                  {loading ? 'Saving...' : 'Save Changes'}
                </button>
              </div>
            </form>
          )}

          {activeTab === 'security' && (
            <form onSubmit={handleChangePassword}>
              <h2 style={{ fontSize: '1.2rem', marginBottom: 24 }}>Password & Security</h2>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
                <div className="form-group">
                  <label style={{ display: 'block', marginBottom: 8, fontSize: '0.9rem', fontWeight: 500 }}>Current Password</label>
                  <input 
                    type="password" 
                    value={passwords.old} 
                    onChange={e => setPasswords({...passwords, old: e.target.value})}
                    className="login-input" 
                    required 
                  />
                </div>
                <div className="form-group">
                  <label style={{ display: 'block', marginBottom: 8, fontSize: '0.9rem', fontWeight: 500 }}>New Password</label>
                  <input 
                    type="password" 
                    value={passwords.new} 
                    onChange={e => setPasswords({...passwords, new: e.target.value})}
                    className="login-input" 
                    required 
                  />
                </div>
                <div className="form-group">
                  <label style={{ display: 'block', marginBottom: 8, fontSize: '0.9rem', fontWeight: 500 }}>Confirm New Password</label>
                  <input 
                    type="password" 
                    value={passwords.confirm} 
                    onChange={e => setPasswords({...passwords, confirm: e.target.value})}
                    className="login-input" 
                    required 
                  />
                </div>
                <button type="submit" disabled={loading} className="login-submit" style={{ width: 'auto', padding: '12px 32px', marginTop: 12 }}>
                  {loading ? 'Updating Password...' : 'Change Password'}
                </button>
              </div>
            </form>
          )}

          {activeTab === 'billing' && (
            <div style={{ textAlign: 'center', padding: '40px 0' }}>
              <Icon name="credit-card" size={48} style={{ color: 'var(--accent)', marginBottom: 20 }} />
              <h2 style={{ fontSize: '1.2rem', marginBottom: 12 }}>Subscription Plan</h2>
              <p style={{ color: 'var(--text-secondary)', marginBottom: 24 }}>
                You are currently on the <strong>{subscription?.plan?.toUpperCase()}</strong> plan.
              </p>
              <button onClick={() => window.location.href = '/billing'} className="topbar-btn" style={{ padding: '12px 24px' }}>
                Go to Billing Dashboard
              </button>
            </div>
          )}

          {activeTab === 'api' && (
            <div style={{ textAlign: 'center', padding: '40px 0' }}>
              <Icon name="key" size={48} style={{ color: 'var(--accent)', marginBottom: 20 }} />
              <h2 style={{ fontSize: '1.2rem', marginBottom: 12 }}>API Access</h2>
              <p style={{ color: 'var(--text-secondary)', marginBottom: 24 }}>
                API keys are available for Pro and Enterprise users to automate contract reviews.
              </p>
              {subscription?.plan === 'free' ? (
                <button onClick={() => window.location.href = '/billing'} className="login-submit" style={{ width: 'auto', padding: '12px 24px' }}>
                  Upgrade for API Access
                </button>
              ) : (
                <button className="topbar-btn" style={{ padding: '12px 24px' }}>
                  Generate New API Key
                </button>
              )}
            </div>
          )}
        </main>
      </div>
    </div>
  )
}
