import { useSubscription } from '../../contexts/SubscriptionContext'

export default function UsageMeter() {
  const { usage, subscription } = useSubscription()

  if (!usage || !subscription) return null

  const docsUsed = usage.documents.used
  const docsLimit = usage.documents.limit
  const percent = docsLimit === -1 ? 0 : Math.min(100, (docsUsed / docsLimit) * 100)

  return (
    <div className="sidebar-usage" style={{ padding: '20px 16px', borderTop: '1px solid var(--border)', marginTop: 'auto' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8, fontSize: '0.75rem', fontWeight: 500 }}>
        <span>Usage</span>
        <span>{docsUsed} / {docsLimit === -1 ? '∞' : docsLimit} docs</span>
      </div>
      <div style={{ height: 4, background: 'var(--border)', borderRadius: 2, overflow: 'hidden', marginBottom: 12 }}>
        <div style={{ 
          height: '100%', 
          width: `${percent}%`, 
          background: percent > 90 ? '#ef4444' : 'var(--accent)',
          transition: 'width 0.3s'
        }} />
      </div>
      {subscription.plan === 'free' && (
        <a href="/billing" style={{ 
          fontSize: '0.7rem', 
          color: 'var(--accent)', 
          textDecoration: 'none', 
          fontWeight: 600,
          display: 'flex',
          alignItems: 'center',
          gap: 4
        }}>
          Upgrade to Pro →
        </a>
      )}
    </div>
  )
}
