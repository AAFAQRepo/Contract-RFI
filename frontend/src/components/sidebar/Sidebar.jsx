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

  const initial = user?.name?.charAt(0).toUpperCase() || user?.email?.charAt(0).toUpperCase() || 'U'

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
      {/* ── Top: Menu toggle + Logo ── */}
      <div className="sidebar-logo">
        <button
          className="sidebar-menu-btn"
          onClick={() => setCollapsed(v => !v)}
          title={collapsed ? 'Open sidebar' : 'Close sidebar'}
        >
          <Icon.Menu />
        </button>

        <span className="sidebar-logo-text">
          Contract RFI
        </span>
      </div>

      {/* ── Nav items ── */}
      <div className="sidebar-nav">
        <button
          className="sidebar-nav-item"
          onClick={handleNewChat}
          id="new-project-btn"
          title="New chat"
        >
          <Icon.Plus />
          <span className="sidebar-text">New chat</span>
        </button>
        <button
          className="sidebar-nav-item"
          onClick={() => { if (collapsed) setCollapsed(false); setShowSearch(true) }}
          id="search-projects-btn"
          title="Search"
        >
          <Icon.Search />
          <span className="sidebar-text">Search</span>
        </button>
        <button
          className="sidebar-nav-item"
          title="Library"
        >
          <Icon.Library />
          <span className="sidebar-text">Library</span>
        </button>
        <button
          className="sidebar-nav-item"
          title="Workflows"
        >
          <Icon.Workflows />
          <span className="sidebar-text">Workflows</span>
        </button>
      </div>

      {/* ── Conversations ── */}
      <div className="sidebar-scroll-area">
        {loadingConversations ? (
          <div className="sidebar-skeletons">
            <div className="sidebar-skeleton-item skeleton" />
            <div className="sidebar-skeleton-item skeleton" style={{ width: '70%' }} />
            <div className="sidebar-skeleton-item skeleton" style={{ width: '85%' }} />
          </div>
        ) : conversations.length > 0 ? (
          <>
            <div className="sidebar-section-label">Conversations</div>
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
      <div className="sidebar-bottom">
        <button
          className="sidebar-nav-item"
          title="Help"
        >
          <Icon.Help />
          <span className="sidebar-text">Help</span>
        </button>

        <div style={{ position: 'relative' }}>
          <button
            className="sidebar-account-btn"
            id="account-btn"
            onClick={() => setShowAccount(v => !v)}
          >
            <div className="account-avatar" title={user?.name || 'Account'}>{initial}</div>
            <span className="sidebar-text account-name">{user?.name || 'Account'}</span>
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
