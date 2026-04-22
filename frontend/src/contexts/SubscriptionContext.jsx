import { createContext, useContext, useState, useCallback, useEffect } from 'react'
import api from '../api/client'
import { useAuth } from './AuthContext'

const SubscriptionContext = createContext(null)

export function SubscriptionProvider({ children }) {
  const { isAuthenticated } = useAuth()
  const [subscription, setSubscription] = useState(null)
  const [usage, setUsage] = useState(null)
  const [loading, setLoading] = useState(false)

  const fetchSubscriptionData = useCallback(async () => {
    if (!isAuthenticated) return
    setLoading(true)
    try {
      const [subRes, usageRes] = await Promise.all([
        api.get('/billing/subscription'),
        api.get('/billing/usage')
      ])
      setSubscription(subRes.data)
      setUsage(usageRes.data.usage)
    } catch (err) {
      console.error('Failed to load subscription data', err)
    } finally {
      setLoading(false)
    }
  }, [isAuthenticated])

  useEffect(() => {
    fetchSubscriptionData()
  }, [fetchSubscriptionData])

  const refreshUsage = useCallback(async () => {
    try {
      const res = await api.get('/billing/usage')
      setUsage(res.data.usage)
    } catch {}
  }, [])

  return (
    <SubscriptionContext.Provider value={{
      subscription, usage, loading, fetchSubscriptionData, refreshUsage
    }}>
      {children}
    </SubscriptionContext.Provider>
  )
}

export function useSubscription() {
  const ctx = useContext(SubscriptionContext)
  if (!ctx) throw new Error('useSubscription must be used within SubscriptionProvider')
  return ctx
}
