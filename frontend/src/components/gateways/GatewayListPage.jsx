import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { Plus, Search, Layers, Loader2 } from 'lucide-react'
import { api } from '../../services/api'
import DataTable from '../shared/DataTable'
import StatusBadge from '../shared/StatusBadge'
import EmptyState from '../shared/EmptyState'
import GatewayCreateModal from './GatewayCreateModal'
import { useRole } from '../../context/RoleContext'

export default function GatewayListPage() {
  const navigate = useNavigate()
  const { isOwner } = useRole()
  const [gateways, setGateways] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [search, setSearch] = useState('')
  const [showCreate, setShowCreate] = useState(false)

  const fetchGateways = async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await api.listGateways()
      setGateways(Array.isArray(data) ? data : data.gateways || [])
    } catch (err) {
      setError(err.response?.data?.detail || err.message || 'Failed to load gateways')
      setGateways([])
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchGateways()
  }, [])

  const filtered = gateways.filter((gw) => {
    if (!search) return true
    const q = search.toLowerCase()
    return (
      (gw.name || '').toLowerCase().includes(q) ||
      (gw.genie_space_id || '').toLowerCase().includes(q) ||
      (gw.genie_space_name || '').toLowerCase().includes(q)
    )
  })

  const formatDate = (dateStr) => {
    if (!dateStr) return '-'
    const d = new Date(dateStr)
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
  }

  const columns = [
    {
      key: 'name',
      label: 'Name',
      width: '22%',
      render: (val, row) => (
        <span
          className="text-dbx-text-link hover:underline cursor-pointer font-medium"
          onClick={(e) => {
            e.stopPropagation()
            navigate(`/gateways/${row.id}`)
          }}
        >
          {val}
        </span>
      ),
    },
    {
      key: 'genie_space_name',
      label: 'Genie Space',
      width: '18%',
      render: (val, row) => val || row.genie_space_id?.substring(0, 12) + '...' || '-',
    },
    {
      key: 'status',
      label: 'Status',
      width: '10%',
      align: 'center',
      render: (val) => <StatusBadge status={val || 'active'} />,
    },
    {
      key: 'caching_enabled',
      label: 'Cache',
      width: '7%',
      align: 'center',
      render: (val) => (
        <span className={val !== false ? 'text-dbx-blue' : 'text-dbx-border-input'} title={val !== false ? 'Enabled' : 'Disabled'}>
          {val !== false ? '●' : '○'}
        </span>
      ),
    },
    {
      key: 'cache_entries',
      label: 'Cache Entries',
      width: '10%',
      align: 'center',
      render: (val) => (val != null ? val.toLocaleString() : '-'),
    },
    {
      key: 'max_queries_per_minute',
      label: 'Rate Limit (QPM)',
      width: '12%',
      align: 'center',
      render: (val) => (val != null ? val : '-'),
    },
    {
      key: 'question_normalization_enabled',
      label: 'Normalization',
      width: '10%',
      align: 'center',
      render: (val) => (
        <span className={val ? 'text-dbx-blue' : 'text-dbx-border-input'} title={val ? 'Enabled' : 'Disabled'}>
          {val ? '●' : '○'}
        </span>
      ),
    },
    {
      key: 'cache_validation_enabled',
      label: 'Validation',
      width: '9%',
      align: 'center',
      render: (val) => (
        <span className={val ? 'text-dbx-blue' : 'text-dbx-border-input'} title={val ? 'Enabled' : 'Disabled'}>
          {val ? '●' : '○'}
        </span>
      ),
    },
    {
      key: 'updated_at',
      label: 'Last Modified',
      width: '12%',
      render: (val) => formatDate(val),
    },
  ]

  const handleCreated = (newGateway) => {
    setShowCreate(false)
    if (newGateway?.id) {
      navigate(`/gateways/${newGateway.id}`)
    } else {
      fetchGateways()
    }
  }

  return (
    <div className="p-6">
      {/* Header */}
      <div className="flex items-start justify-between mb-5">
        <div>
          <h1 className="text-[22px] font-medium text-dbx-text">Genie Cache Gateway</h1>
          <p className="text-[13px] text-dbx-text-secondary mt-0.5">
            Intelligent caching gateway for Databricks Genie API
          </p>
        </div>
        {isOwner && (
          <button
            onClick={() => setShowCreate(true)}
            className="flex items-center gap-2 bg-dbx-blue text-white rounded h-9 px-4 text-[13px] font-medium hover:bg-dbx-blue-dark transition-colors"
          >
            <Plus size={16} />
            Gateway
          </button>
        )}
      </div>

      {/* Search bar */}
      {!loading && gateways.length > 0 && (
        <div className="mb-4">
          <div className="relative w-72">
            <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-dbx-text-secondary" />
            <input
              type="text"
              placeholder="Search by name or destination"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="w-full h-8 pl-9 pr-3 border border-dbx-border-input rounded text-[13px] text-dbx-text placeholder:text-dbx-text-secondary focus:outline-none focus:border-dbx-blue bg-dbx-bg"
            />
          </div>
        </div>
      )}

      {/* Content */}
      {loading ? (
        <div className="flex items-center justify-center py-20">
          <Loader2 size={24} className="animate-spin text-dbx-text-secondary" />
        </div>
      ) : error ? (
        <div className="text-center py-12">
          <p className="text-[13px] text-red-600 mb-2">{error}</p>
          <button
            onClick={fetchGateways}
            className="text-[13px] text-dbx-text-link hover:underline"
          >
            Retry
          </button>
        </div>
      ) : gateways.length === 0 ? (
        <EmptyState
          icon={Layers}
          title="No gateways yet"
          description="Create a gateway to start caching Genie queries and accelerating your analytics."
          action={isOwner ? (
            <button
              onClick={() => setShowCreate(true)}
              className="flex items-center gap-2 bg-dbx-blue text-white rounded h-9 px-4 text-[13px] font-medium hover:bg-dbx-blue-dark transition-colors"
            >
              <Plus size={16} />
              Create your first gateway
            </button>
          ) : null}
        />
      ) : (
        <DataTable
          columns={columns}
          data={filtered}
          onRowClick={(row) => navigate(`/gateways/${row.id}`)}
          emptyMessage="No gateways match your search"
        />
      )}

      {isOwner && (
        <GatewayCreateModal
          open={showCreate}
          onClose={() => setShowCreate(false)}
          onCreated={handleCreated}
        />
      )}
    </div>
  )
}
