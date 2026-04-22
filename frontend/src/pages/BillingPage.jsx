import { useState } from 'react'
import { useSubscription } from '../contexts/SubscriptionContext'
import api from '../api/client'
import { Icon } from '../components/common/Icon'

export default function BillingPage() {
  const { subscription, usage, loading } = useSubscription()
  const [upgrading, setUpgrading] = useState(false)

  const handleUpgrade = async (planId) => {
    setUpgrading(true)
    try {
      const res = await api.post('/billing/checkout', { plan_id: planId })
      if (res.data.checkout_url) {
        window.location.href = res.data.checkout_url
      }
    } catch (err) {
      alert('Failed to initiate checkout. Please try again.')
    } finally {
      setUpgrading(false)
    }
  }

  const handlePortal = async () => {
    try {
      const res = await api.post('/billing/portal')
      if (res.data.portal_url) {
        window.location.href = res.data.portal_url
      }
    } catch (err) {
      alert('Failed to open billing portal.')
    }
  }

  if (loading && !subscription) return <div className="p-8">Loading billing details...</div>

  const renderUsageBar = (resource, used, limit) => {
    const percent = limit === -1 ? 0 : Math.min(100, (used / limit) * 100)
    return (
      <div className="usage-row" style={{ marginBottom: 20 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8, fontSize: '0.85rem' }}>
          <span style={{ textTransform: 'capitalize', fontWeight: 500 }}>{resource}</span>
          <span style={{ color: 'var(--text-secondary)' }}>
            {used} / {limit === -1 ? 'Unlimited' : limit}
          </span>
        </div>
        <div style={{ height: 6, background: 'var(--border)', borderRadius: 3, overflow: 'hidden' }}>
          <div style={{ 
            height: '100%', 
            width: `${percent}%`, 
            background: percent > 90 ? '#ef4444' : 'var(--accent)',
            transition: 'width 0.5s ease-out'
          }} />
        </div>
      </div>
    )
  }

  return (
    <div className="billing-page" style={{ padding: '40px 20px', maxWidth: 800, margin: '0 auto' }}>
      <header style={{ marginBottom: 40 }}>
        <h1 style={{ fontSize: '1.8rem', fontWeight: 700, marginBottom: 8 }}>Subscription & Billing</h1>
        <p style={{ color: 'var(--text-secondary)' }}>Manage your plan and track your monthly usage.</p>
      </header>

      <section className="current-plan-card" style={{ 
        background: '#fff', 
        border: '1px solid var(--border)', 
        borderRadius: 16, 
        padding: 32,
        marginBottom: 32,
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center'
      }}>
        <div>
          <div style={{ color: 'var(--text-secondary)', fontSize: '0.8rem', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 8 }}>
            Current Plan
          </div>
          <div style={{ fontSize: '1.5rem', fontWeight: 700, display: 'flex', alignItems: 'center', gap: 12 }}>
            {subscription?.plan?.toUpperCase()}
            <span style={{ 
              fontSize: '0.7rem', 
              background: '#e0f2fe', 
              color: '#0369a1', 
              padding: '2px 8px', 
              borderRadius: 4,
              textTransform: 'uppercase'
            }}>
              {subscription?.status}
            </span>
          </div>
        </div>
        <button className="topbar-btn" onClick={handlePortal} style={{ padding: '10px 20px' }}>
          Manage Billing
        </button>
      </section>

      <section style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 32 }}>
        <div className="usage-card" style={{ background: '#fff', border: '1px solid var(--border)', borderRadius: 16, padding: 32 }}>
          <h3 style={{ marginBottom: 24, fontSize: '1.1rem' }}>Monthly Usage</h3>
          {usage && (
            <>
              {renderUsageBar('documents', usage.documents.used, usage.documents.limit)}
              {renderUsageBar('queries', usage.queries.used, usage.queries.limit)}
              {renderUsageBar('storage', usage.storage_mb.used, usage.storage_mb.limit)}
            </>
          )}
        </div>

        <div className="upgrade-card" style={{ background: 'var(--bg-secondary)', border: '1px solid var(--border)', borderRadius: 16, padding: 32, display: 'flex', flexDirection: 'column', justifyContent: 'center', textAlign: 'center' }}>
          <Icon name="zap" size={32} style={{ color: 'var(--accent)', margin: '0 auto 16px' }} />
          <h3 style={{ marginBottom: 12 }}>Need more power?</h3>
          <p style={{ color: 'var(--text-secondary)', fontSize: '0.9rem', marginBottom: 24 }}>
            Upgrade to Pro for 50 documents, 500 queries, and OCR support.
          </p>
          <button 
            className="login-submit" 
            onClick={() => handleUpgrade('pro')}
            disabled={subscription?.plan === 'pro' || upgrading}
          >
            {upgrading ? 'Connecting...' : 'Upgrade to Pro'}
          </button>
        </div>
      </section>
    </div>
  )
}
