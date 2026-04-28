import { useState, useEffect } from 'react'
import { useParams, useNavigate, Link } from 'react-router-dom'
import { Trash2, Copy, Loader2, AlertTriangle } from 'lucide-react'
import { api } from '../../services/api'
import Modal from '../shared/Modal'
import { useRole } from '../../context/RoleContext'
import RouterOverviewTab from './RouterOverviewTab'
import RouterMembersTab from './RouterMembersTab'
import RouterPreviewTab from './RouterPreviewTab'
import RouterSettingsTab from './RouterSettingsTab'

const ALL_TABS = [
  { id: 'overview', label: 'Overview' },
  { id: 'members', label: 'Members' },
  { id: 'preview', label: 'Preview' },
  { id: 'settings', label: 'Settings', minRole: 'manage' },
]

export default function RouterDetailPage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const { isOwner, isManage } = useRole()
  const [routerCfg, setRouterCfg] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [activeTab, setActiveTab] = useState('overview')
  const [deleting, setDeleting] = useState(false)
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false)
  const [deleteError, setDeleteError] = useState(null)

  const fetchRouter = async () => {
    try {
      setLoading(true)
      setError(null)
      const data = await api.getRouter(id)
      setRouterCfg(data)
    } catch (err) {
      setError(err.response?.data?.detail || err.message || 'Failed to load router')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { fetchRouter() }, [id])

  const handleDelete = async () => {
    try {
      setDeleteError(null)
      setDeleting(true)
      await api.deleteRouter(id)
      setShowDeleteConfirm(false)
      navigate('/routers')
    } catch (err) {
      setDeleteError(err.response?.data?.detail || err.message || 'Failed to delete router')
    } finally {
      setDeleting(false)
    }
  }

  const copyToClipboard = (text) => { navigator.clipboard.writeText(text) }

  const TABS = ALL_TABS.filter((t) => !t.minRole || isManage)

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <Loader2 className="w-6 h-6 animate-spin text-dbx-text-secondary" />
      </div>
    )
  }

  if (error) {
    return (
      <div className="p-6">
        <Link to="/routers" className="text-dbx-text-link font-medium text-[13px] hover:underline">
          Routers &gt;
        </Link>
        <div className="mt-4 text-[13px] text-red-600">Error: {error}</div>
      </div>
    )
  }

  if (!routerCfg) return null

  const renderTab = () => {
    switch (activeTab) {
      case 'overview':
        return <RouterOverviewTab routerCfg={routerCfg} />
      case 'members':
        return <RouterMembersTab routerCfg={routerCfg} onChange={fetchRouter} />
      case 'preview':
        return <RouterPreviewTab routerCfg={routerCfg} />
      case 'settings':
        return <RouterSettingsTab routerCfg={routerCfg} onUpdate={fetchRouter} />
      default:
        return null
    }
  }

  return (
    <div className="h-full flex flex-col">
      <div className="px-6 pt-5 pb-0">
        <Link to="/routers" className="text-dbx-text-link font-medium text-[13px] hover:underline">
          Routers &gt;
        </Link>

        <div className="flex items-center justify-between mt-2 mb-4">
          <h1 className="text-[22px] font-medium text-dbx-text">{routerCfg.name}</h1>
          <div className="flex items-center gap-3">
            {isOwner && (
              <button
                onClick={() => setShowDeleteConfirm(true)}
                disabled={deleting}
                className="inline-flex items-center gap-1.5 h-8 px-3 text-[13px] font-medium text-dbx-text border border-dbx-border-input rounded hover:bg-dbx-neutral-hover transition-colors disabled:opacity-50"
              >
                <Trash2 size={14} />
                {deleting ? 'Deleting...' : 'Delete router'}
              </button>
            )}
          </div>
        </div>

        <div className="flex border-b border-dbx-border">
          {TABS.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`px-0 py-1 mr-6 text-[13px] font-medium transition-colors ${
                activeTab === tab.id
                  ? 'text-dbx-text border-b-2 border-dbx-text'
                  : 'text-dbx-text-secondary border-b-2 border-transparent hover:text-dbx-text'
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>
      </div>

      <div className="flex-1 flex overflow-hidden">
        <div className="flex-1 overflow-auto p-6">
          {renderTab()}
        </div>

        <div
          className="w-[350px] bg-dbx-bg overflow-auto px-6 py-5 flex-shrink-0 border-l border-dbx-border"
        >
          <h3 className="text-[13px] font-medium text-dbx-text mb-4">Router details</h3>
          <SidebarField label="Router ID" value={routerCfg.id} copyable onCopy={copyToClipboard} />
          <SidebarField label="Name" value={routerCfg.name} />
          {routerCfg.description && <SidebarField label="Description" value={routerCfg.description} />}
          <SidebarField label="Members" value={String((routerCfg.members || []).length)} />
          <SidebarField
            label="Decompose"
            value={routerCfg.decompose_enabled ? 'Enabled' : 'Disabled'}
          />
          <SidebarField
            label="Routing cache"
            value={routerCfg.routing_cache_enabled ? 'Enabled' : 'Disabled'}
          />
          <SidebarField
            label="Similarity threshold"
            value={String(routerCfg.similarity_threshold ?? 0.92)}
          />
          <SidebarField
            label="Cache TTL"
            value={`${routerCfg.cache_ttl_hours ?? 24} hours`}
          />
          <SidebarField
            label="Selector model"
            value={routerCfg.selector_model || 'default'}
          />
          <SidebarField label="Created by" value={routerCfg.created_by || 'System'} />
          <SidebarField
            label="Date created"
            value={routerCfg.created_at ? new Date(routerCfg.created_at).toLocaleDateString('en-US', {
              year: 'numeric', month: 'short', day: 'numeric'
            }) : 'Unknown'}
          />
        </div>
      </div>

      <Modal
        isOpen={showDeleteConfirm}
        onClose={() => { if (!deleting) { setShowDeleteConfirm(false); setDeleteError(null) } }}
        title="Delete router"
        maxWidth="max-w-md"
      >
        <div className="flex flex-col items-center text-center pt-2">
          <div className="w-12 h-12 rounded-full bg-dbx-status-red-bg flex items-center justify-center mb-4">
            <AlertTriangle size={24} className="text-dbx-text-danger" />
          </div>
          <p className="text-[14px] text-dbx-text mb-1">Are you sure you want to delete this router?</p>
          <p className="text-[13px] text-dbx-text-secondary mb-6">
            <span className="font-medium text-dbx-text">{routerCfg?.name}</span> and its members
            + routing cache will be permanently deleted. The underlying gateways are unaffected.
          </p>
          {deleteError && (
            <div className="w-full mb-4 px-3 py-2 rounded bg-red-50 border border-red-200 text-red-700 text-[12px] text-left">
              {deleteError}
            </div>
          )}
          <div className="flex gap-3 w-full">
            <button
              onClick={() => { setShowDeleteConfirm(false); setDeleteError(null) }}
              disabled={deleting}
              className="flex-1 h-8 text-[13px] font-medium text-dbx-text border border-dbx-border-input rounded hover:bg-dbx-neutral-hover transition-colors disabled:opacity-50"
            >Cancel</button>
            <button
              onClick={handleDelete}
              disabled={deleting}
              className="flex-1 h-8 text-[13px] font-medium text-white bg-[#D32F2F] rounded hover:bg-[#B71C1C] transition-colors disabled:opacity-50"
            >{deleting ? 'Deleting...' : 'Delete'}</button>
          </div>
        </div>
      </Modal>
    </div>
  )
}

function SidebarField({ label, value, copyable, onCopy }) {
  const [copied, setCopied] = useState(false)
  const handleCopy = () => {
    onCopy?.(value)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }
  return (
    <div className="mb-4">
      <div className="text-[13px] text-dbx-text-secondary mb-0.5">{label}</div>
      <div className="flex items-center gap-1.5">
        <span className="text-[13px] text-dbx-text break-all">{value}</span>
        {copyable && (
          <button
            onClick={handleCopy}
            className="text-dbx-text-secondary hover:text-dbx-text flex-shrink-0"
            title={copied ? 'Copied!' : 'Copy'}
          >
            <Copy size={13} />
          </button>
        )}
      </div>
    </div>
  )
}
