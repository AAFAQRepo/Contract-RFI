import { createContext, useContext, useState, useCallback, useEffect } from 'react'
import api from '../api/client'

const ProjectContext = createContext(null)

export function ProjectProvider({ children }) {
  const [projects, setProjects] = useState([])
  const [activeProject, setActiveProject] = useState(null)
  const [conversations, setConversations] = useState([])
  const [activeConversationId, setActiveConversationId] = useState(null)

  const fetchProjects = useCallback(async () => {
    try {
      const r = await api.get('/documents/')
      const docs = r.data.documents || []
      setProjects(docs)
      return docs
    } catch (err) {
      console.error('Failed to load documents', err)
      return []
    }
  }, [])

  const fetchConversations = useCallback(async () => {
    try {
      const r = await api.get('/chat/conversations')
      if (Array.isArray(r.data)) setConversations(r.data)
    } catch { /* silent */ }
  }, [])

  // Load on mount
  useEffect(() => {
    fetchProjects()
    fetchConversations()
  }, [fetchProjects, fetchConversations])

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
