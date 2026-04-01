import { useState } from 'react'
import { Routes, Route, Navigate, useNavigate } from 'react-router-dom'
import { Settings, PanelLeft } from 'lucide-react'
import Sidebar from './components/layout/Sidebar'
import GatewayListPage from './components/gateways/GatewayListPage'
import GatewayDetailPage from './components/gateways/GatewayDetailPage'
import PlaygroundPage from './components/playground/PlaygroundPage'
import SettingsPage from './components/settings/SettingsPage'
import ApiReferencePage from './components/api/ApiReferencePage'
import McpPage from './components/mcp/McpPage'
import DebugPage from './components/debug/DebugPage'

function TopBar({ onToggleSidebar }) {
  const navigate = useNavigate()
  return (
    <header className="h-[48px] min-h-[48px] w-full bg-dbx-sidebar flex items-center justify-between px-3 border-b border-dbx-border">
      <div className="flex items-center gap-1.5">
        <button
          onClick={onToggleSidebar}
          className="p-1.5 rounded hover:bg-dbx-neutral-hover transition-colors"
          title="Toggle sidebar"
        >
          <PanelLeft size={18} className="text-dbx-text-secondary" />
        </button>
        <img src="/genie-icon-alt.svg" alt="Genie" width="24" height="24" />
        <span className="text-[16px] font-medium text-dbx-text" style={{ fontFamily: '"DM Sans", sans-serif' }}>Genie Cache Gateway</span>
      </div>
      <button
        onClick={() => navigate('/settings')}
        className="p-1.5 rounded hover:bg-dbx-neutral-hover transition-colors"
        title="Settings"
      >
        <Settings size={18} className="text-dbx-text-secondary" />
      </button>
    </header>
  )
}

function App() {
  const [sidebarOpen, setSidebarOpen] = useState(true)

  return (
    <div className="flex flex-col h-screen bg-dbx-sidebar">
      <TopBar onToggleSidebar={() => setSidebarOpen(v => !v)} />
      <div className="flex flex-1 min-h-0">
        <div
          className="flex-shrink-0 overflow-hidden transition-all duration-200"
          style={{ width: sidebarOpen ? 200 : 0 }}
        >
          <Sidebar />
        </div>
        <main className="flex-1 overflow-hidden rounded-lg bg-dbx-bg border border-dbx-border mb-1 mr-1" style={{ boxShadow: 'rgba(0,0,0,0.05) 0px 2px 3px -1px, rgba(0,0,0,0.02) 0px 1px 0px 0px' }}>
          <div className="h-full overflow-auto">
            <Routes>
              <Route path="/" element={<GatewayListPage />} />
              <Route path="/gateways/:id" element={<GatewayDetailPage />} />
              <Route path="/playground" element={<PlaygroundPage />} />
              <Route path="/playground/:id" element={<PlaygroundPage />} />
              <Route path="/settings" element={<SettingsPage />} />
              <Route path="/api-reference" element={<ApiReferencePage />} />
              <Route path="/mcp" element={<McpPage />} />
              <Route path="/debug" element={<DebugPage />} />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </div>
        </main>
      </div>
    </div>
  )
}

export default App
