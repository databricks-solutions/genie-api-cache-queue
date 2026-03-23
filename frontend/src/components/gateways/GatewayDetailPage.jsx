import { useState, useEffect } from 'react'
import { useParams, useNavigate, Link } from 'react-router-dom'
import { Trash2, Play, Copy, Loader2 } from 'lucide-react'
import { api } from '../../services/api'
import GatewayOverviewTab from './GatewayOverviewTab'
import GatewayMetricsTab from './GatewayMetricsTab'
import GatewayCacheTab from './GatewayCacheTab'
import GatewayLogsTab from './GatewayLogsTab'
import GatewaySettingsTab from './GatewaySettingsTab'

const TABS = [
  { id: 'overview', label: 'Overview' },
  { id: 'metrics', label: 'Metrics' },
  { id: 'cache', label: 'Cache' },
  { id: 'logs', label: 'Logs' },
  { id: 'settings', label: 'Settings' },
]

export default function GatewayDetailPage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [gateway, setGateway] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [activeTab, setActiveTab] = useState('overview')
  const [deleting, setDeleting] = useState(false)

  const fetchGateway = async () => {
    try {
      setLoading(true)
      setError(null)
      const data = await api.getGateway(id)
      setGateway(data)
    } catch (err) {
      setError(err.response?.data?.detail || err.message || 'Failed to load gateway')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchGateway()
  }, [id])

  const handleDelete = async () => {
    if (!confirm(`Delete gateway "${gateway?.name || id}"? This action cannot be undone.`)) return
    try {
      setDeleting(true)
      await api.deleteGateway(id)
      navigate('/')
    } catch (err) {
      alert('Failed to delete gateway: ' + (err.response?.data?.detail || err.message))
    } finally {
      setDeleting(false)
    }
  }

  const handleUpdate = (updatedGateway) => {
    setGateway(updatedGateway)
  }

  const copyToClipboard = (text) => {
    navigator.clipboard.writeText(text)
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <Loader2 className="w-6 h-6 animate-spin text-[#6F6F6F]" />
      </div>
    )
  }

  if (error) {
    return (
      <div className="p-6">
        <Link to="/" className="text-[#0E538B] font-medium text-[13px] hover:underline">
          Genie Cache Gateway &gt;
        </Link>
        <div className="mt-4 text-[13px] text-red-600">Error: {error}</div>
      </div>
    )
  }

  if (!gateway) return null

  const ttlHours = gateway.cache_ttl_seconds
    ? gateway.cache_ttl_seconds / 3600
    : 24

  const renderTab = () => {
    switch (activeTab) {
      case 'overview':
        return <GatewayOverviewTab gateway={gateway} />
      case 'metrics':
        return <GatewayMetricsTab gateway={gateway} />
      case 'cache':
        return <GatewayCacheTab gateway={gateway} />
      case 'logs':
        return <GatewayLogsTab gateway={gateway} />
      case 'settings':
        return <GatewaySettingsTab gateway={gateway} onUpdate={handleUpdate} />
      default:
        return null
    }
  }

  return (
    <div className="h-full flex flex-col">
      {/* Header */}
      <div className="px-6 pt-5 pb-0">
        {/* Breadcrumb */}
        <Link to="/" className="text-[#0E538B] font-medium text-[13px] hover:underline">
          Genie Cache Gateway &gt;
        </Link>

        {/* Title row */}
        <div className="flex items-center justify-between mt-2 mb-4">
          <h1 className="text-[22px] font-medium text-[#161616]">{gateway.name}</h1>
          <div className="flex items-center gap-3">
            <button
              onClick={() => navigate(`/playground/${id}`)}
              className="inline-flex items-center gap-1.5 h-8 px-3 text-[13px] font-medium text-[#161616] border border-[#CBCBCB] rounded hover:bg-[#F7F7F7] transition-colors"
            >
              <Play size={14} />
              Test in Playground
            </button>
            <button
              onClick={handleDelete}
              disabled={deleting}
              className="inline-flex items-center gap-1.5 h-8 px-3 text-[13px] font-medium text-[#161616] border border-[#CBCBCB] rounded hover:bg-[#F7F7F7] transition-colors disabled:opacity-50"
            >
              <Trash2 size={14} />
              {deleting ? 'Deleting...' : 'Delete gateway'}
            </button>
          </div>
        </div>

        {/* Tabs */}
        <div className="flex" style={{ borderBottom: '1px solid #EBEBEB' }}>
          {TABS.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`px-0 py-1 mr-6 text-[13px] font-medium transition-colors ${
                activeTab === tab.id
                  ? 'text-[#161616] border-b-2 border-[#161616]'
                  : 'text-[#6F6F6F] border-b-2 border-transparent hover:text-[#161616]'
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>
      </div>

      {/* Content area with sidebar */}
      <div className="flex-1 flex overflow-hidden">
        {/* Main content */}
        <div className="flex-1 overflow-auto p-6">
          {renderTab()}
        </div>

        {/* Right sidebar */}
        <div
          className="w-[350px] bg-white overflow-auto px-6 py-5 flex-shrink-0"
          style={{ borderLeft: '1px solid #EBEBEB' }}
        >
          <h3 className="text-[13px] font-medium text-[#161616] mb-4">
            Gateway Endpoint Details
          </h3>

          <SidebarField label="Gateway ID" value={gateway.id} copyable onCopy={copyToClipboard} />
          <SidebarField label="Gateway Name" value={gateway.name} />
          <SidebarField label="Genie Space ID" value={gateway.genie_space_id} copyable onCopy={copyToClipboard} />
          <SidebarField label="SQL Warehouse ID" value={gateway.sql_warehouse_id || 'Not set'} />
          <SidebarField label="Created by" value={gateway.created_by || 'System'} />
          <SidebarField
            label="Date created"
            value={gateway.created_at ? new Date(gateway.created_at).toLocaleDateString('en-US', {
              year: 'numeric', month: 'short', day: 'numeric'
            }) : 'Unknown'}
          />
          <SidebarField
            label="Rate limit"
            value={`${gateway.max_qpm || gateway.max_queries_per_minute || 5} QPM`}
          />
          <SidebarField
            label="Cache TTL"
            value={`${ttlHours} hours`}
          />
          <SidebarField
            label="Similarity threshold"
            value={String(gateway.similarity_threshold ?? 0.92)}
          />
          <SidebarField
            label="Normalization"
            value={gateway.question_normalization_enabled !== false ? 'Enabled' : 'Disabled'}
          />
          <SidebarField
            label="Validation"
            value={gateway.cache_validation_enabled !== false ? 'Enabled' : 'Disabled'}
          />
        </div>
      </div>
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
      <div className="text-[13px] text-[#6F6F6F] mb-0.5">{label}</div>
      <div className="flex items-center gap-1.5">
        <span className="text-[13px] text-[#161616] break-all">{value}</span>
        {copyable && (
          <button
            onClick={handleCopy}
            className="text-[#6F6F6F] hover:text-[#161616] flex-shrink-0"
            title={copied ? 'Copied!' : 'Copy'}
          >
            <Copy size={13} />
          </button>
        )}
      </div>
    </div>
  )
}
