import { createContext, useContext, useState, useCallback, useEffect } from 'react'
import api from '../api/client'
import { useAuth } from './AuthContext'

const ProjectContext = createContext(null)

export function ProjectProvider({ children }) {
  const { isAuthenticated } = useAuth()
  const [projects, setProjects] = useState([])
  const [activeProject, setActiveProject] = useState(null)
  const [conversations, setConversations] = useState([])
  const [activeConversationId, setActiveConversationId] = useState(null)

  const fetchProjects = useCallback(async () => {
    if (!isAuthenticated) return []
    try {
      const r = await api.get('/documents/')
      const docs = r.data.documents || []
      setProjects(docs)
      return docs
    } catch (err) {
      console.error('Failed to load documents', err)
      return []
    }
  }, [isAuthenticated])

  const fetchConversations = useCallback(async () => {
    if (!isAuthenticated) return
    try {
      const r = await api.get('/chat/conversations')
      if (Array.isArray(r.data)) setConversations(r.data)
    } catch { /* silent */ }
  }, [isAuthenticated])

  // Load on mount or when auth changes
  useEffect(() => {
    if (isAuthenticated) {
      fetchProjects()
      fetchConversations()
    } else {
      setProjects([])
      setConversations([])
    }
  }, [isAuthenticated, fetchProjects, fetchConversations])

  const addProject = useCallback((doc) => {
    setProjects(prev => [doc, ...prev])
  }, [])

  const removeProject = useCallback((docId) => {
    setProjects(prev => prev.filter(p => p.id !== docId))
    if (activeProject?.id === docId) setActiveProject(null)
  }, [activeProject])

  const resetForNewProject = useCallback(() => {
    setActiveProject(null)
    setActiveConversationId(null)
    localStorage.removeItem('forceHistory')
  }, [])

  return (
    <ProjectContext.Provider value={{
      projects, setProjects, activeProject, setActiveProject,
      conversations, fetchConversations,
      activeConversationId, setActiveConversationId,
      fetchProjects, addProject, removeProject, resetForNewProject,
    }}>
      {children}
    </ProjectContext.Provider>
  )
}

export function useProjects() {
  const ctx = useContext(ProjectContext)
  if (!ctx) throw new Error('useProjects must be used within ProjectProvider')
  return ctx
}
