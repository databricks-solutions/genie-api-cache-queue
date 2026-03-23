import { useState } from 'react'
import { Routes, Route, Navigate, useNavigate } from 'react-router-dom'
import { Settings, PanelLeft } from 'lucide-react'
import Sidebar from './components/layout/Sidebar'
import GatewayListPage from './components/gateways/GatewayListPage'
import GatewayDetailPage from './components/gateways/GatewayDetailPage'
import PlaygroundPage from './components/playground/PlaygroundPage'
import SettingsPage from './components/settings/SettingsPage'
import ApiReferencePage from './components/api/ApiReferencePage'
import DebugPage from './components/debug/DebugPage'

function TopBar({ onToggleSidebar }) {
  const navigate = useNavigate()
  return (
    <header className="h-[48px] min-h-[48px] w-full bg-[#F7F7F7] border-b border-[#EBEBEB] flex items-center justify-between px-3">
      <div className="flex items-center gap-1.5">
        <button
          onClick={onToggleSidebar}
          className="p-1.5 rounded hover:bg-[rgba(0,0,0,0.06)] transition-colors"
          title="Toggle sidebar"
        >
          <PanelLeft size={18} className="text-[#6F6F6F]" />
        </button>
        <img src="/genie-icon-alt.svg" alt="Genie" width="24" height="24" />
        <span className="text-[16px] font-medium text-[#0B2026]" style={{ fontFamily: '"DM Sans", sans-serif' }}>Genie Cache Gateway</span>
      </div>
      <button
        onClick={() => navigate('/settings')}
        className="p-1.5 rounded hover:bg-[rgba(0,0,0,0.06)] transition-colors"
        title="Settings"
      >
        <Settings size={18} className="text-[#6F6F6F]" />
      </button>
    </header>
  )
}

function App() {
  const [sidebarOpen, setSidebarOpen] = useState(true)

  return (
    <div className="flex flex-col h-screen bg-white">
      <TopBar onToggleSidebar={() => setSidebarOpen(v => !v)} />
      <div className="flex flex-1 overflow-hidden">
        <div
          className="flex-shrink-0 overflow-hidden transition-all duration-200"
          style={{ width: sidebarOpen ? 200 : 0 }}
        >
          <Sidebar />
        </div>
        <main className="flex-1 overflow-auto">
          <Routes>
            <Route path="/" element={<GatewayListPage />} />
            <Route path="/gateways/:id" element={<GatewayDetailPage />} />
            <Route path="/playground" element={<PlaygroundPage />} />
            <Route path="/playground/:id" element={<PlaygroundPage />} />
            <Route path="/settings" element={<SettingsPage />} />
            <Route path="/api-reference" element={<ApiReferencePage />} />
            <Route path="/debug" element={<DebugPage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </main>
      </div>
    </div>
  )
}

export default App
