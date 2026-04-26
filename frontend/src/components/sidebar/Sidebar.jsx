import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Icon, Logo } from '../common/Icon'
import AccountDropdown from './AccountDropdown'
import { useAuth } from '../../contexts/AuthContext'
import { useProjects } from '../../contexts/ProjectContext'
import api from '../../api/client'

export default function Sidebar({ collapsed, setCollapsed, setShowSearch }) {
  const [showAccount, setShowAccount] = useState(false)
  const [ctxMenu, setCtxMenu] = useState(null)
  const navigate = useNavigate()
  const { user, logout } = useAuth()
  const {
    conversations, setConversations,
    activeConversationId, setActiveConversationId,
    resetForNewChat,
    loadingConversations,
  } = useProjects()

  const handleNewChat = () => {
    resetForNewChat()
    navigate('/')
  }

  const handleDeleteConversation = async (convId) => {
    if (!window.confirm('Delete this conversation?')) return
    try {
      await api.delete(`/chat/conversations/${convId}`)
      setConversations(c => c.filter(x => x.id !== convId))
      if (activeConversationId === convId) {
        setActiveConversationId(null)
        navigate('/')
      }
    } catch {
      alert('Delete failed')
    }
    setCtxMenu(null)
  }

  return (
    <nav className={`sidebar ${collapsed ? 'sidebar-collapsed' : ''}`}>
      {/* ── Top: Logo + Toggle ── */}
      <div className="sidebar-logo">
        <div className="logo-icon-wrap" style={{ margin: collapsed ? '0 auto' : '0' }}>
          <Logo />
        </div>
        
        <div className="sidebar-toggle-wrapper" style={{ display: collapsed ? 'contents' : 'block' }}>
          <button
            className="sidebar-menu-btn"
            onClick={() => setCollapsed(v => !v)}
            title={collapsed ? 'Open sidebar' : 'Close sidebar'}
            style={{ border: 'none', background: 'none' }}
          >
            <Icon.Columns />
          </button>
        </div>
      </div>

      {/* ── Nav items ── */}
      <div className="sidebar-nav">
        <button
          className="sidebar-nav-item"
          onClick={handleNewChat}
          id="new-project-btn"
          title="New project"
          style={{ justifyContent: collapsed ? 'center' : 'flex-start' }}
        >
          <Icon.Plus />
          {!collapsed && <span>New project</span>}
        </button>
        <button
          className="sidebar-nav-item"
          onClick={() => { if (collapsed) setCollapsed(false); setShowSearch(true) }}
          id="search-projects-btn"
          title="Projects"
          style={{ justifyContent: collapsed ? 'center' : 'flex-start' }}
        >
          <Icon.Search />
          {!collapsed && <span>Projects</span>}
        </button>
        <button
          className="sidebar-nav-item"
          title="Library"
          style={{ justifyContent: collapsed ? 'center' : 'flex-start' }}
        >
          <Icon.Library />
          {!collapsed && <span>Library</span>}
        </button>
        <button
          className="sidebar-nav-item"
          title="Workflows"
          style={{ justifyContent: collapsed ? 'center' : 'flex-start' }}
        >
          <Icon.Workflows />
          {!collapsed && <span>Workflows</span>}
        </button>
      </div>

      {/* ── Conversations / Recent ── */}
      {!collapsed && (
        <div style={{ flex: 1, overflowY: 'auto', padding: '0 0 8px' }}>
          {loadingConversations ? (
            <>
              <div className="sidebar-skeleton-item skeleton" />
              <div className="sidebar-skeleton-item skeleton" style={{ width: '70%' }} />
              <div className="sidebar-skeleton-item skeleton" style={{ width: '85%' }} />
            </>
          ) : conversations.length > 0 ? (
            <>
              <div className="sidebar-section-label">Recent</div>
              {conversations.map(conv => (
                <div
                  key={conv.id}
                  className={`sidebar-project-item ${activeConversationId === conv.id ? 'active' : ''}`}
                  onClick={() => {
                    localStorage.setItem('forceHistory', 'true')
                    setActiveConversationId(conv.id)
                    navigate('/chat')
                  }}
                  title={conv.title}
                >
                  <span className="sidebar-project-name">{conv.title}</span>
                  <button
                    className="sidebar-project-more"
                    onClick={e => { e.stopPropagation(); setCtxMenu({ id: conv.id, x: e.clientX, y: e.clientY }) }}
                  ><Icon.More /></button>
                </div>
              ))}
            </>
          ) : null}
        </div>
      )}

      {collapsed && <div style={{ flex: 1 }} />}

      {/* ── Context menu ── */}
      {ctxMenu && (
        <>
          <div style={{ position: 'fixed', inset: 0, zIndex: 199 }} onClick={() => setCtxMenu(null)} />
          <div className="ctx-menu" style={{ position: 'fixed', top: ctxMenu.y, left: ctxMenu.x }}>
            <div className="ctx-menu-item danger" onClick={() => handleDeleteConversation(ctxMenu.id)}>Delete</div>
          </div>
        </>
      )}

      {/* ── Bottom: Help + Account ── */}
      <div className="sidebar-bottom" style={{ borderTop: '1px solid #eeeeee', padding: '8px 0' }}>
        <button
          className="sidebar-nav-item"
          title="Help"
          style={{ justifyContent: collapsed ? 'center' : 'flex-start', padding: collapsed ? '8px 0' : '8px 16px' }}
        >
          <Icon.Help />
          {!collapsed && <span>Help</span>}
        </button>

        <div style={{ position: 'relative' }}>
          <button
            className="sidebar-account-btn"
            id="account-btn"
            onClick={() => setShowAccount(v => !v)}
            style={{ 
              justifyContent: collapsed ? 'center' : 'flex-start', 
              padding: collapsed ? '8px 0' : '8px 16px',
              display: 'flex',
              alignItems: 'center',
              width: '100%',
              border: 'none',
              background: 'none',
              cursor: 'pointer',
              color: '#333333',
              fontSize: '0.88rem',
              gap: '12px'
            }}
          >
            <Icon.User />
            {!collapsed && <span style={{ whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>Account</span>}
          </button>

          {showAccount && (
            <>
              <div style={{ position: 'fixed', inset: 0, zIndex: 199 }} onClick={() => setShowAccount(false)} />
              <div style={{ position: 'absolute', bottom: '100%', left: 0, zIndex: 200 }}>
                <AccountDropdown onClose={() => setShowAccount(false)} onLogout={logout} user={user} />
              </div>
            </>
          )}
        </div>
      </div>
    </nav>
  )
}
