import { useState } from 'react'
import { Outlet } from 'react-router-dom'
import Sidebar from '../components/sidebar/Sidebar'
import SearchPanel from '../components/common/SearchPanel'

export default function AppLayout() {
  const [sidebarCollapsed, setSidebarCollapsed] = useState(true)
  const [showSearch, setShowSearch] = useState(false)

  return (
    <div className="app-shell">
      {showSearch
        ? <SearchPanel onClose={() => setShowSearch(false)} />
        : <Sidebar
            collapsed={sidebarCollapsed}
            setCollapsed={setSidebarCollapsed}
            setShowSearch={setShowSearch}
          />
      }
      <Outlet />
    </div>
  )
}
