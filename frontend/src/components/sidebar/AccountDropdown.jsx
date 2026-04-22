import { Icon } from '../common/Icon'

export default function AccountDropdown({ onClose, onLogout, user }) {
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
