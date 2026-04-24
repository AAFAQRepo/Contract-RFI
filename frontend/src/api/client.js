import axios from 'axios'

const api = axios.create({
  baseURL: '/api',
  headers: {
    'Content-Type': 'application/json',
  },
})

// Request interceptor: always attach the latest token from localStorage
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

let isRefreshing = false
let failedQueue = []

const processQueue = (error, token = null) => {
  failedQueue.forEach((prom) => {
    if (error) prom.reject(error)
    else prom.resolve(token)
  })
  failedQueue = []
}

// Only wipe auth keys, NOT everything (prevents losing refresh_token on network blip)
const clearAuthAndRedirect = () => {
  localStorage.removeItem('token')
  localStorage.removeItem('refresh_token')
  localStorage.removeItem('user')
  localStorage.removeItem('forceHistory')
  if (!['/', '/login', '/register'].includes(window.location.pathname)) {
    window.location.href = '/login'
  }
}

// Response interceptor: handle 401 with queued refresh
api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const originalRequest = error.config

    // Only handle 401 and don't retry the refresh call itself
    if (
      error.response?.status === 401 &&
      !originalRequest._retry &&
      !originalRequest.url?.includes('/auth/refresh')
    ) {
      if (isRefreshing) {
        // Queue this request until the ongoing refresh finishes
        return new Promise((resolve, reject) => {
          failedQueue.push({ resolve, reject })
        })
          .then((token) => {
            originalRequest.headers.Authorization = `Bearer ${token}`
            return api(originalRequest)
          })
          .catch((err) => Promise.reject(err))
      }

      originalRequest._retry = true
      isRefreshing = true

      const refreshToken = localStorage.getItem('refresh_token')
      if (!refreshToken) {
        isRefreshing = false
        clearAuthAndRedirect()
        return Promise.reject(error)
      }

      try {
        const res = await axios.post('/api/auth/refresh', { refresh_token: refreshToken })
        const { access_token } = res.data
        localStorage.setItem('token', access_token)

        processQueue(null, access_token)
        isRefreshing = false

        originalRequest.headers.Authorization = `Bearer ${access_token}`
        return api(originalRequest)
      } catch (refreshError) {
        processQueue(refreshError, null)
        isRefreshing = false
        clearAuthAndRedirect()
        return Promise.reject(refreshError)
      }
    }

    return Promise.reject(error)
  }
)

/**
 * Helper: get the current auth token, refreshing if needed.
 * Use this before raw XHR calls (like document upload) to ensure
 * the token is fresh before sending the request.
 */
export async function getValidToken() {
  const token = localStorage.getItem('token')
  if (!token) return null

  // Decode expiry without a library (JWT payload is base64)
  try {
    const payload = JSON.parse(atob(token.split('.')[1]))
    const expiresAt = payload.exp * 1000
    const bufferMs = 60 * 1000 // refresh 60s before actual expiry

    if (Date.now() < expiresAt - bufferMs) {
      return token // still valid
    }

    // Proactively refresh
    const refreshToken = localStorage.getItem('refresh_token')
    if (!refreshToken) return token // can't refresh, use what we have

    const res = await axios.post('/api/auth/refresh', { refresh_token: refreshToken })
    const { access_token } = res.data
    localStorage.setItem('token', access_token)
    return access_token
  } catch {
    return token // fallback to existing token on any error
  }
}

export default api
