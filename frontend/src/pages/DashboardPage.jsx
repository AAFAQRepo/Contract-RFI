import { useState, useEffect } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import api from '../api/client'
import { Icon } from '../components/common/Icon'
import { useAuth } from '../contexts/AuthContext'
import { useProjects } from '../contexts/ProjectContext'

export default function DashboardPage() {
  const { user } = useAuth()
  const { fetchProjects } = useProjects()
  const navigate = useNavigate()
  const [stats, setStats] = useState(null)
  const [activity, setActivity] = useState([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    async function loadDashboard() {
      try {
        const [statsRes, activityRes] = await Promise.all([
          api.get('/workspace/stats'),
          api.get('/workspace/activity')
        ])
        setStats(statsRes.data)
        setActivity(activityRes.data)
      } catch (err) {
        console.error('Failed to load dashboard data', err)
      } finally {
        setLoading(false)
      }
    }
    loadDashboard()
  }, [])

  if (loading) return <div className="p-8">Loading workspace...</div>

  const StatCard = ({ title, value, limit, icon, color }) => {
    const percent = limit && limit !== -1 ? Math.min(100, (value / limit) * 100) : 0
    return (
      <div className="stat-card" style={{ 
        background: '#fff', 
        border: '1px solid var(--border)', 
        borderRadius: 16, 
        padding: 24,
        display: 'flex',
        flexDirection: 'column',
        gap: 16
      }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div style={{ color: 'var(--text-secondary)', fontSize: '0.85rem', fontWeight: 500 }}>{title}</div>
          <div style={{ padding: 8, borderRadius: 8, background: `${color}15`, color: color }}>
            {icon}
          </div>
        </div>
        <div style={{ fontSize: '1.8rem', fontWeight: 700 }}>
          {value}
          {limit && limit !== -1 && <span style={{ fontSize: '1rem', color: 'var(--text-secondary)', fontWeight: 400 }}> / {limit}</span>}
          {limit === -1 && <span style={{ fontSize: '1.2rem', color: 'var(--text-secondary)', fontWeight: 400 }}> (∞)</span>}
        </div>
        {limit && limit !== -1 && (
          <div style={{ height: 4, background: 'var(--border)', borderRadius: 2, overflow: 'hidden' }}>
            <div style={{ height: '100%', width: `${percent}%`, background: color }} />
          </div>
        )}
      </div>
    )
  }

  return (
    <div className="dashboard-page" style={{ padding: '40px 32px', maxWidth: 1200, margin: '0 auto' }}>
      <header style={{ marginBottom: 40, display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end' }}>
        <div>
          <h1 style={{ fontSize: '2rem', fontWeight: 800, marginBottom: 8 }}>Welcome back, {user?.name || 'User'}</h1>
          <p style={{ color: 'var(--text-secondary)' }}>Here's what's happening in your workspace.</p>
        </div>
        <button className="login-submit" style={{ width: 'auto', padding: '12px 24px' }} onClick={() => navigate('/chat')}>
          <span style={{ marginRight: 8, display: 'inline-flex' }}><Icon.Plus /></span>
          New Analysis
        </button>
      </header>

      <section className="stats-grid" style={{ 
        display: 'grid', 
        gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', 
        gap: 24,
        marginBottom: 48
      }}>
        <StatCard title="Documents" value={stats?.totals?.documents || 0} icon={<Icon.Library />} color="#6366f1" />
        <StatCard title="AI Queries" value={stats?.usage?.queries?.used || 0} limit={stats?.usage?.queries?.limit} icon={<Icon.Workflows />} color="#f59e0b" />
        <StatCard title="Monthly Cap" value={stats?.usage?.documents?.used || 0} limit={stats?.usage?.documents?.limit} icon={<Icon.Plus />} color="#10b981" />
        <StatCard title="Total Messages" value={stats?.totals?.messages || 0} icon={<Icon.Search />} color="#ec4899" />
      </section>

      <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: 48 }}>
        <section className="activity-section">
          <h2 style={{ fontSize: '1.25rem', fontWeight: 700, marginBottom: 24 }}>Recent Activity</h2>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            {activity.length === 0 ? (
              <div style={{ padding: 40, textAlign: 'center', color: 'var(--text-secondary)', border: '2px dashed var(--border)', borderRadius: 16 }}>
                No recent activity. Start by uploading a contract!
              </div>
            ) : activity.map(act => (
              <div key={`${act.type}-${act.id}`} style={{ 
                background: '#fff', 
                border: '1px solid var(--border)', 
                borderRadius: 12, 
                padding: 16,
                display: 'flex',
                alignItems: 'center',
                gap: 16
              }}>
                <div style={{ 
                  width: 40, 
                  height: 40, 
                  borderRadius: 8, 
                  background: act.type === 'document' ? '#e0e7ff' : '#fef3c7',
                  color: act.type === 'document' ? '#4338ca' : '#d97706',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center'
                }}>
                  {act.type === 'document' ? <Icon.Library /> : <Icon.Workflows />}
                </div>
                <div style={{ flex: 1 }}>
                  <div style={{ fontWeight: 600, fontSize: '0.95rem' }}>{act.title}</div>
                  <div style={{ color: 'var(--text-secondary)', fontSize: '0.8rem' }}>
                    {act.type === 'document' ? 'Document uploaded' : 'Chat session updated'} • {new Date(act.timestamp).toLocaleDateString()}
                  </div>
                </div>
                <Link to={act.type === 'document' ? '/chat' : '/'} style={{ 
                  padding: '8px 16px', 
                  borderRadius: 6, 
                  border: '1px solid var(--border)', 
                  textDecoration: 'none',
                  color: 'var(--text-primary)',
                  fontSize: '0.85rem',
                  fontWeight: 500
                }}>
                  Open
                </Link>
              </div>
            ))}
          </div>
        </section>

        <section className="quick-actions">
          <h2 style={{ fontSize: '1.25rem', fontWeight: 700, marginBottom: 24 }}>Quick Help</h2>
          <div style={{ background: 'var(--bg-secondary)', borderRadius: 16, padding: 24 }}>
            <div style={{ marginBottom: 20 }}>
              <h3 style={{ fontSize: '1rem', marginBottom: 8 }}>Need Support?</h3>
              <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', lineHeight: 1.5 }}>
                Check out our documentation or contact support for help with your contract reviews.
              </p>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              <button className="topbar-btn" style={{ width: '100%', justifyContent: 'center' }}>
                View Tutorials
              </button>
              <button className="topbar-btn" style={{ width: '100%', justifyContent: 'center' }}>
                Contact Us
              </button>
            </div>
          </div>
        </section>
      </div>
    </div>
  )
}
