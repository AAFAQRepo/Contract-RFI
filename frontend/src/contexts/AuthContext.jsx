import { createContext, useContext, useState, useCallback, useEffect } from 'react'
import api from '../api/client'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [token, setToken] = useState(() => {
    const t = localStorage.getItem('token')
    console.log('AuthProvider: Initial token from localStorage:', t ? 'EXISTS' : 'MISSING')
    return t
  })
  const [user, setUser] = useState(() => {
    try { 
      const u = JSON.parse(localStorage.getItem('user'))
      console.log('AuthProvider: Initial user from localStorage:', u ? u.email : 'MISSING')
      return u
    } catch { return null }
  })

  const login = useCallback(async (email, password) => {
    const res = await api.post('/auth/login', { email, password })
    const { access_token, refresh_token, user: userData } = res.data
    localStorage.setItem('token', access_token)
    localStorage.setItem('refresh_token', refresh_token)
    localStorage.setItem('user', JSON.stringify(userData))
    setToken(access_token)
    setUser(userData)
    return userData
  }, [])

  const fetchUser = useCallback(async () => {
    try {
      const res = await api.get('/auth/me')
      const userData = res.data
      localStorage.setItem('user', JSON.stringify(userData))
      setUser(userData)
      return userData
    } catch (err) {
      console.error('Failed to fetch user', err)
      return null
    }
  }, [])

  const logout = useCallback(() => {
    localStorage.removeItem('token')
    localStorage.removeItem('refresh_token')
    localStorage.removeItem('user')
    localStorage.removeItem('forceHistory')
    setToken(null)
    setUser(null)
  }, [])

  const isAuthenticated = !!token

  // Verify token on mount
  useEffect(() => {
    if (token) {
      fetchUser().catch(() => {
        // fetchUser already handles logging error, but we might want to clear here if it fails critically
        // although api interceptor should handle 401
      })
    }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <AuthContext.Provider value={{ token, user, isAuthenticated, login, logout, fetchUser }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}
