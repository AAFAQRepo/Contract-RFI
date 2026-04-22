import { useEffect, useState } from 'react'
import { Icon } from './Icon'

export default function Toast({ text, type, onClose }) {
  const [visible, setVisible] = useState(false)

  useEffect(() => {
    // Small delay for entry animation
    const raf = requestAnimationFrame(() => setVisible(true))
    return () => cancelAnimationFrame(raf)
  }, [])

  const colors = {
    success: { bg: '#f0fdf4', border: '#bbf7d0', text: '#166534', icon: 'check-circle' },
    error: { bg: '#fef2f2', border: '#fecaca', text: '#991b1b', icon: 'alert-circle' },
    info: { bg: '#f0f9ff', border: '#bae6fd', text: '#075985', icon: 'info' },
    warning: { bg: '#fffbeb', border: '#fef3c7', text: '#92400e', icon: 'alert-triangle' }
  }

  const theme = colors[type] || colors.info

  return (
    <div style={{
      pointerEvents: 'auto',
      minWidth: 300,
      maxWidth: 450,
      background: theme.bg,
      border: `1px solid ${theme.border}`,
      borderRadius: 12,
      padding: '14px 18px',
      boxShadow: '0 10px 15px -3px rgba(0, 0, 0, 0.1), 0 4px 6px -2px rgba(0, 0, 0, 0.05)',
      display: 'flex',
      alignItems: 'center',
      gap: 14,
      transform: visible ? 'translateX(0)' : 'translateX(100px)',
      opacity: visible ? 1 : 0,
      transition: 'all 0.3s cubic-bezier(0.4, 0, 0.2, 1)'
    }}>
      <div style={{ color: theme.text }}>
        <Icon name={theme.icon} size={20} />
      </div>
      <div style={{ 
        flex: 1, 
        color: theme.text, 
        fontSize: '0.9rem', 
        fontWeight: 500,
        lineHeight: 1.4
      }}>
        {text}
      </div>
      <button 
        onClick={() => { setVisible(false); setTimeout(onClose, 300); }}
        style={{
          background: 'transparent',
          border: 'none',
          color: theme.text,
          opacity: 0.5,
          cursor: 'pointer',
          padding: 4,
          display: 'flex'
        }}
      >
        <Icon name="x" size={16} />
      </button>
    </div>
  )
}
