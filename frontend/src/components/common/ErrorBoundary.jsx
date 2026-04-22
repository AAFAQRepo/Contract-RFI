import React from 'react'

export default class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props)
    this.state = { hasError: false, error: null }
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error }
  }

  componentDidCatch(error, errorInfo) {
    console.error("Uncaught error:", error, errorInfo)
  }

  render() {
    if (this.state.hasError) {
      return (
        <div style={{
          height: '100vh',
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          padding: 24,
          textAlign: 'center',
          background: 'var(--bg-secondary)'
        }}>
          <div style={{ fontSize: '3rem', marginBottom: 20 }}>⚠️</div>
          <h1 style={{ marginBottom: 12 }}>Something went wrong</h1>
          <p style={{ color: 'var(--text-secondary)', maxWidth: 400, marginBottom: 24 }}>
            An unexpected error occurred. We've been notified and are looking into it.
          </p>
          <button 
            onClick={() => window.location.reload()}
            className="login-submit"
            style={{ width: 'auto', padding: '12px 32px' }}
          >
            Reload Page
          </button>
        </div>
      )
    }

    return this.props.children
  }
}
