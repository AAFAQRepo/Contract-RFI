import { createContext, useContext, useState, useCallback, useEffect } from 'react'
import api from '../api/client'
import { useAuth } from './AuthContext'

const ProjectContext = createContext(null)

export function ProjectProvider({ children }) {
  const { isAuthenticated } = useAuth()
  const [conversations, setConversations] = useState([])
  const [activeConversationId, setActiveConversationId] = useState(null)
  // conversationDocs: docs scoped to the currently active conversation
  const [conversationDocs, setConversationDocs] = useState([])

  const fetchConversations = useCallback(async () => {
    if (!isAuthenticated) return
    try {
      const r = await api.get('/chat/conversations')
      if (Array.isArray(r.data)) setConversations(r.data)
    } catch { /* silent */ }
  }, [isAuthenticated])

  // Fetch documents scoped to a specific conversation
  const fetchConversationDocs = useCallback(async (conversationId) => {
    if (!conversationId) {
      setConversationDocs([])
      return []
    }
    try {
      const r = await api.get('/documents/', { params: { conversation_id: conversationId } })
      const docs = r.data.documents || []
      setConversationDocs(docs)
      return docs
    } catch (err) {
      console.error('Failed to load conversation documents', err)
      return []
    }
  }, [])

  // Load conversations on mount / auth change
  useEffect(() => {
    if (isAuthenticated) {
      fetchConversations()
    } else {
      setConversations([])
      setConversationDocs([])
      setActiveConversationId(null)
    }
  }, [isAuthenticated, fetchConversations])

  // When active conversation changes, fetch its documents
  useEffect(() => {
    if (activeConversationId) {
      fetchConversationDocs(activeConversationId)
    } else {
      setConversationDocs([])
    }
  }, [activeConversationId, fetchConversationDocs])

  const resetForNewChat = useCallback(() => {
    setActiveConversationId(null)
    setConversationDocs([])
    localStorage.removeItem('forceHistory')
  }, [])

  return (
    <ProjectContext.Provider value={{
      // Conversations
      conversations, setConversations, fetchConversations,
      activeConversationId, setActiveConversationId,
      // Per-conversation documents
      conversationDocs, setConversationDocs, fetchConversationDocs,
      // Helpers
      resetForNewChat,
      // Legacy aliases so nothing else breaks
      resetForNewProject: resetForNewChat,
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
