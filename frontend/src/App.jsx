import { useState, useEffect } from 'react'
import { BrowserRouter, Routes, Route, NavLink, useNavigate, Navigate } from 'react-router-dom'
import './index.css'
import './App.css'
import ChatPage from './pages/ChatPage'
import LoginPage from './pages/LoginPage'

/* ── Icons (inline SVG) ──────────────────────────────────────── */
export const Icon = {
  Plus: () => <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>,
  Search: () => <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>,
  Library: () => <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/></svg>,
  Workflows: () => <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/></svg>,
  Help: () => <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>,
  Settings: () => <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>,
  Logout: () => <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/></svg>,
  More: () => <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><circle cx="5" cy="12" r="2"/><circle cx="12" cy="12" r="2"/><circle cx="19" cy="12" r="2"/></svg>,
  ArrowBack: () => <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><line x1="19" y1="12" x2="5" y2="12"/><polyline points="12 19 5 12 12 5"/></svg>,
  ChevronDown: () => <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><polyline points="6 9 12 15 18 9"/></svg>,
  Share: () => <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/><line x1="8.59" y1="13.51" x2="15.42" y2="17.49"/><line x1="15.41" y1="6.51" x2="8.59" y2="10.49"/></svg>,
  Columns: () => <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="3" width="7" height="18"/><rect x="14" y="3" width="7" height="18"/></svg>,
  Collapse: () => <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><line x1="3" y1="12" x2="21" y2="12"/><polyline points="8 7 3 12 8 17"/></svg>,
  Attach: () => <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"/></svg>,
  Send: () => <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><line x1="12" y1="19" x2="12" y2="5"/><polyline points="5 12 12 5 19 12"/></svg>,
  Lock: () => <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>,
  ThumbUp: () => <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M14 9V5a3 3 0 0 0-3-3l-4 9v11h11.28a2 2 0 0 0 2-1.7l1.38-9a2 2 0 0 0-2-2.3zM7 22H4a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2h3"/></svg>,
  ThumbDown: () => <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M10 15v4a3 3 0 0 0 3 3l4-9V2H5.72a2 2 0 0 0-2 1.7l-1.38 9a2 2 0 0 0 2 2.3zm7-13h2.67A2.31 2.31 0 0 1 22 4v7a2.31 2.31 0 0 1-2.33 2H17"/></svg>,
  Copy: () => <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>,
  Close: () => <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>,
  Legal: () => <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><path d="M7 21h10"/><path d="M12 21V7"/><path d="M3 7h18"/><path d="M3 10c0 4 4.5 6 4.5 6s4.5-2 4.5-6"/><path d="M12 10c0 4 4.5 6 4.5 6s4.5-2 4.5-6"/></svg>,
  Web: () => <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>,
  Mic: () => <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" y1="19" x2="12" y2="23"/><line x1="8" y1="23" x2="16" y2="23"/></svg>,
  Prompts: () => <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/><path d="M13 8H7"/><path d="M17 12H7"/></svg>,
}

/* ── Logo ─────────────────────────────────────────────────────── */
export function Logo() {
  return (
    <div style={{ width: 26, height: 26, borderRadius: 6, background: 'linear-gradient(135deg,#e53935,#ff7043,#fdd835)', display:'flex', alignItems:'center', justifyContent:'center', flexShrink: 0 }}>
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none"><path d="M12 2L2 7l10 5 10-5-10-5z" fill="white" opacity=".9"/><path d="M2 17l10 5 10-5" stroke="white" strokeWidth="2" strokeLinecap="round"/><path d="M2 12l10 5 10-5" stroke="white" strokeWidth="2" strokeLinecap="round"/></svg>
    </div>
  )
}

/* ── Account Dropdown ─────────────────────────────────────────── */
function AccountDropdown({ onClose, onLogout, user }) {
  const initial = user?.email?.charAt(0).toUpperCase() || 'U'
  return (
    <div className="account-dropdown">
      <div className="account-dropdown-header">
        <div className="account-avatar" style={{ width: 36, height: 36, fontSize: '1rem' }}>{initial}</div>
        <div>
          <div className="account-dropdown-name">{user?.name || 'User'}</div>
          <div className="account-dropdown-email">{user?.email}</div>
        </div>
      </div>
      <div className="account-dropdown-item" onClick={onClose}>
        <Icon.Settings /> Settings
      </div>
      <div className="account-dropdown-item" onClick={onLogout}>
        <Icon.Logout /> Sign out
      </div>
    </div>
  )
}

/* ── Sidebar ─────────────────────────────────────────────────── */
function Sidebar({ collapsed, setCollapsed, activeProject, setActiveProject, projects, setProjects, setShowSearch, onLogout, user, chatSessions, activeChatSession, setActiveChatSession, onNewProject }) {
  const [showAccount, setShowAccount] = useState(false)
  const [ctxMenu, setCtxMenu] = useState(null)
  const navigate = useNavigate()
  const initial = user?.email?.charAt(0).toUpperCase() || 'U'

  const handleNewProject = () => {
    if (onNewProject) onNewProject()
    navigate('/')
  }

  const handleDelete = async (projectId) => {
    if (!window.confirm('Delete this document?')) return
    try {
      await fetch(`/api/documents/${projectId}`, { method: 'DELETE' })
      setProjects(p => p.filter(x => x.id !== projectId))
      if (activeProject?.id === projectId) { setActiveProject(null); navigate('/') }
    } catch (e) { alert('Delete failed') }
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
                  <AccountDropdown onClose={() => setShowAccount(false)} onLogout={onLogout} user={user} />
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
        onClick={() => { setActiveProject(null); setActiveChatSession(null); navigate('/') }}
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

      {/* Chat sessions — populated from DB */}
      {chatSessions.length > 0 && (
        <>
          <div className="sidebar-section-label">Chats</div>
          <div style={{ overflowY: 'auto', maxHeight: 200, padding: '0 0 4px' }}>
            {chatSessions.map(session => {
              const isActive = session.is_global
                ? !activeProject && activeChatSession === 'global'
                : activeProject?.id === session.document_id
              return (
                <div
                  key={session.document_id || 'global'}
                  className={`sidebar-project-item ${isActive ? 'active' : ''}`}
                  onClick={() => {
                    if (session.is_global) {
                      setActiveProject(null)
                      setActiveChatSession('global')
                      navigate('/')
                    } else {
                      const doc = projects.find(p => p.id === session.document_id)
                      if (doc) { setActiveProject(doc); navigate('/chat') }
                    }
                  }}
                  title={session.title}
                >
                  <span className="sidebar-project-name" style={{ color: session.is_global ? 'var(--text-secondary)' : undefined }}>
                    {session.is_global ? '💬 ' : '📄 '}{session.title}
                  </span>
                  <span style={{ fontSize: '0.68rem', color: '#999', marginLeft: 4, flexShrink: 0 }}>{session.message_count}</span>
                </div>
              )
            })}
          </div>
        </>
      )}

      {/* Recent document projects — from API data */}
      {projects.length > 0 && (
        <>
          <div className="sidebar-section-label">Recent projects</div>
          <div style={{ flex: 1, overflowY: 'auto', padding: '0 0 8px' }}>
            {projects.map(p => (
              <div
                key={p.id}
                className={`sidebar-project-item ${activeProject?.id === p.id ? 'active' : ''}`}
                onClick={() => { setActiveProject(p); setActiveChatSession(null); navigate('/chat') }}
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
      {projects.length === 0 && chatSessions.length === 0 && <div style={{ flex: 1 }} />}

      {ctxMenu && (
        <>
          <div style={{ position: 'fixed', inset: 0, zIndex: 199 }} onClick={() => setCtxMenu(null)} />
          <div className="ctx-menu" style={{ position: 'fixed', top: ctxMenu.y, left: ctxMenu.x }}>
            <div className="ctx-menu-item" onClick={() => setCtxMenu(null)}>✏️ Rename</div>
            <div className="ctx-menu-item" onClick={() => setCtxMenu(null)}>📌 Pin to top</div>
            <div className="ctx-menu-item" onClick={() => setCtxMenu(null)}>⬆️ Export</div>
            <div className="ctx-menu-item danger" onClick={() => handleDelete(ctxMenu.id)}>🗑 Delete</div>
          </div>
        </>
      )}

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
                <AccountDropdown onClose={() => setShowAccount(false)} onLogout={onLogout} user={user} />
              </div>
            </>
          )}
        </div>
      </div>
    </nav>
  )
}

/* ── Search Panel ────────────────────────────────────────────── */
function SearchPanel({ onClose, onSelect, projects }) {
  const [q, setQ] = useState('')
  const filtered = projects.filter(p => !q || (p.filename || p.name || '').toLowerCase().includes(q.toLowerCase()))

  const relTime = (iso) => {
    if (!iso) return ''
    const diff = Math.floor((Date.now() - new Date(iso)) / 1000)
    if (diff < 60) return 'just now'
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
    if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`
    return `${Math.floor(diff / 86400)}d ago`
  }

  return (
    <div className="search-panel">
      <div className="search-panel-top">
        <Icon.Search />
        <input
          className="search-panel-input"
          autoFocus
          placeholder="Search all projects..."
          value={q}
          onChange={e => setQ(e.target.value)}
          id="search-input"
        />
        <button className="search-panel-back" onClick={onClose}><Icon.ArrowBack /></button>
      </div>
      <div className="search-results-label">{filtered.length} project{filtered.length !== 1 ? 's' : ''}</div>
      {filtered.map(p => (
        <div key={p.id} className="search-result-item" onClick={() => { onSelect(p); onClose() }}>
          <div className="search-result-title">{p.filename || p.name}</div>
          <div className="search-result-meta">{p.retrieval_chunks ? `${p.retrieval_chunks} chunks` : (p.status || 'ready')} · {relTime(p.created_at)}</div>
        </div>
      ))}
    </div>
  )
}

/* ── App Shell ───────────────────────────────────────────────── */
function AppShell({ onLogout, user }) {
  const [activeProject, setActiveProject] = useState(null)
  const [activeChatSession, setActiveChatSession] = useState(null) // 'global' or null
  const [showSearch, setShowSearch] = useState(false)
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)
  const [projects, setProjects] = useState([])
  const [chatSessions, setChatSessions] = useState([])
  const [resetKey, setResetKey] = useState(0)  // increment to force ChatPage remount

  // Load chat sessions (for sidebar) on mount + after new messages
  const refreshChatSessions = () => {
    const token = localStorage.getItem('token')
    fetch('/api/chat/sessions', {
      headers: { 'Authorization': `Bearer ${token}` }
    })
      .then(r => r.json())
      .then(data => Array.isArray(data) ? setChatSessions(data) : null)
      .catch(() => {})
  }

  useEffect(() => { refreshChatSessions() }, [])

  return (
    <div className="app-shell">
      {showSearch
        ? <SearchPanel onClose={() => setShowSearch(false)} onSelect={p => setActiveProject(p)} projects={projects} />
        : <Sidebar
            collapsed={sidebarCollapsed}
            setCollapsed={setSidebarCollapsed}
            activeProject={activeProject}
            setActiveProject={setActiveProject}
            projects={projects}
            setProjects={setProjects}
            setShowSearch={setShowSearch}
            onLogout={onLogout}
            user={user}
            chatSessions={chatSessions}
            activeChatSession={activeChatSession}
            setActiveChatSession={setActiveChatSession}
            onNewProject={() => {
              setActiveProject(null)
              setActiveChatSession(null)
              setResetKey(k => k + 1)
            }}
          />
      }

      <Routes>
        <Route path="/" element={
          <ChatPage
            key={`home-${resetKey}`}
            project={activeProject}
            setProject={setActiveProject}
            projects={projects}
            setProjects={setProjects}
            onMessageSent={refreshChatSessions}
          />
        } />
        <Route path="/chat" element={
          <ChatPage
            key={`chat-${resetKey}`}
            project={activeProject}
            setProject={setActiveProject}
            projects={projects}
            setProjects={setProjects}
            onMessageSent={refreshChatSessions}
          />
        } />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </div>
  )
}

export default function App() {
  const [token, setToken] = useState(localStorage.getItem('token'))
  const [user, setUser] = useState(() => {
    try {
      return JSON.parse(localStorage.getItem('user'))
    } catch {
      return null
    }
  })

  const logout = () => {
    localStorage.removeItem('token')
    localStorage.removeItem('user')
    setToken(null)
    setUser(null)
  }

  if (!token) {
    return (
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="*" element={<Navigate to="/login" replace />} />
        </Routes>
      </BrowserRouter>
    )
  }

  return (
    <BrowserRouter>
      <AppShell onLogout={logout} user={user} />
    </BrowserRouter>
  )
}
