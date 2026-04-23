import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Icon, Logo } from '../common/Icon'
import AccountDropdown from './AccountDropdown'
import { useAuth } from '../../contexts/AuthContext'
import { useProjects } from '../../contexts/ProjectContext'
import api from '../../api/client'

import UsageMeter from '../subscription/UsageMeter'

export default function Sidebar({ collapsed, setCollapsed, setShowSearch }) {
  const [showAccount, setShowAccount] = useState(false)
  const [ctxMenu, setCtxMenu] = useState(null)
  const navigate = useNavigate()
  const { user, logout } = useAuth()
  const { 
    projects, setProjects, activeProject, setActiveProject, 
    conversations, activeConversationId, setActiveConversationId,
    resetForNewProject 
  } = useProjects()

  const initial = user?.email?.charAt(0).toUpperCase() || 'U'

  const handleNewProject = () => {
    resetForNewProject()
    navigate('/')
  }

  const handleDelete = async (projectId) => {
    if (!window.confirm('Delete this document?')) return
    try {
      await api.delete(`/documents/${projectId}`)
      setProjects(p => p.filter(x => x.id !== projectId))
      if (activeProject?.id === projectId) {
        setActiveProject(null)
        navigate('/')
      }
    } catch (e) {
      alert('Delete failed')
    }
    setCtxMenu(null)
  }

  if (collapsed) {
    return (
      <nav className="sidebar sidebar-collapsed">
        <div 
          className="sidebar-logo" 
          style={{ justifyContent: 'center', padding: '16px 0 8px', cursor: 'pointer' }}
          onClick={() => setCollapsed(false)}
        >
          <Logo />
        </div>
        <div className="sidebar-nav" style={{ alignItems: 'center' }}>
          <button className="sidebar-nav-item sidebar-icon-only" onClick={handleNewProject} title="New project"><Icon.Plus /></button>
          <button className="sidebar-nav-item sidebar-icon-only" onClick={() => { setCollapsed(false); setShowSearch(true) }} title="Search"><Icon.Search /></button>
          <button className="sidebar-nav-item sidebar-icon-only" title="Library"><Icon.Library /></button>
          <button className="sidebar-nav-item sidebar-icon-only" title="Workflows"><Icon.Workflows /></button>
        </div>
        <div style={{ flex: 1 }} />
        <div className="sidebar-bottom" style={{ alignItems: 'center' }}>
          <button className="sidebar-nav-item sidebar-icon-only" title="Help"><Icon.Help /></button>
          <div style={{ position: 'relative' }}>
            <button className="sidebar-account-btn sidebar-icon-only" onClick={() => setShowAccount(v => !v)} style={{ justifyContent: 'center' }}>
              <div className="account-avatar">{initial}</div>
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

  return (
    <nav className="sidebar" style={{ position: 'relative' }}>
      <div 
        className="sidebar-logo" 
        style={{ marginBottom: 6, cursor: 'pointer' }}
        onClick={() => { setActiveProject(null); setActiveConversationId(null); navigate('/') }}
      >
        <Logo />
        <span className="sidebar-logo-text">Contract RFI</span>
        <button className="sidebar-collapse-btn" onClick={(e) => { e.stopPropagation(); setCollapsed(true) }} title="Collapse sidebar">
          <Icon.Collapse />
        </button>
      </div>

      <div className="sidebar-nav">
        <button className="sidebar-nav-item" onClick={handleNewProject} id="new-project-btn">
          <Icon.Plus /> New project
        </button>
        <button className="sidebar-nav-item" onClick={() => setShowSearch(true)} id="search-projects-btn">
          <Icon.Search /> Search projects
        </button>
        <button className="sidebar-nav-item">
          <Icon.Library /> Library
        </button>
        <button className="sidebar-nav-item">
          <Icon.Workflows /> Workflows
        </button>
      </div>

      {conversations.length > 0 && (
        <>
          <div className="sidebar-section-label">Conversations</div>
          <div style={{ overflowY: 'auto', maxHeight: 200, padding: '0 0 4px' }}>
            {conversations.map(conv => (
              <div
                key={conv.id}
                className={`sidebar-project-item ${activeConversationId === conv.id ? 'active' : ''}`}
                onClick={() => {
                  localStorage.setItem('forceHistory', 'true')
                  setActiveProject(null)
                  setActiveConversationId(conv.id)
                  navigate('/chat')
                }}
                title={conv.title}
              >
                <span className="sidebar-project-name">
                  {conv.title}
                </span>
              </div>
            ))}
          </div>
        </>
      )}

      {projects.length > 0 && (
        <>
          <div className="sidebar-section-label">Recent projects</div>
          <div style={{ flex: 1, overflowY: 'auto', padding: '0 0 8px' }}>
            {projects.map(p => (
              <div
                key={p.id}
                className={`sidebar-project-item ${activeProject?.id === p.id ? 'active' : ''}`}
                onClick={() => { 
                  localStorage.setItem('forceHistory', 'true');
                  setActiveProject(p); 
                  setActiveConversationId(null); 
                  navigate('/chat');
                }}
                id={`project-${p.id}`}
              >
                <span className="sidebar-project-name">{p.filename || p.name}</span>
                <button
                  className="sidebar-project-more"
                  onClick={e => { e.stopPropagation(); setCtxMenu({ id: p.id, x: e.clientX, y: e.clientY }) }}
                ><Icon.More /></button>
              </div>
            ))}
          </div>
        </>
      )}
      {projects.length === 0 && conversations.length === 0 && <div style={{ flex: 1 }} />}

      {ctxMenu && (
        <>
          <div style={{ position: 'fixed', inset: 0, zIndex: 199 }} onClick={() => setCtxMenu(null)} />
          <div className="ctx-menu" style={{ position: 'fixed', top: ctxMenu.y, left: ctxMenu.x }}>
            <div className="ctx-menu-item" onClick={() => setCtxMenu(null)}>Rename</div>
            <div className="ctx-menu-item" onClick={() => setCtxMenu(null)}>Pin to top</div>
            <div className="ctx-menu-item" onClick={() => setCtxMenu(null)}>Export</div>
            <div className="ctx-menu-item danger" onClick={() => handleDelete(ctxMenu.id)}>Delete</div>
          </div>
        </>
      )}

      {!collapsed && <UsageMeter />}
      
      <div className="sidebar-bottom">
        <button className="sidebar-nav-item"><Icon.Help /> Help</button>
        <div style={{ position: 'relative' }}>
          <button className="sidebar-account-btn" id="account-btn" onClick={() => setShowAccount(v => !v)}>
            <div className="account-avatar">{initial}</div>
            {user?.name || 'Account'}
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
