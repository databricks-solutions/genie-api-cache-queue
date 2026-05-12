import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { Plus, Search, Route as RouteIcon, Loader2 } from 'lucide-react'
import { api } from '../../services/api'
import DataTable from '../shared/DataTable'
import StatusBadge from '../shared/StatusBadge'
import EmptyState from '../shared/EmptyState'
import RouterCreateModal from './RouterCreateModal'
import { useRole } from '../../context/RoleContext'

export default function RouterListPage() {
  const navigate = useNavigate()
  const { isOwner } = useRole()
  const [routers, setRouters] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [search, setSearch] = useState('')
  const [showCreate, setShowCreate] = useState(false)

  const fetchRouters = async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await api.listRouters()
      setRouters(Array.isArray(data) ? data : [])
    } catch (err) {
      setError(err.response?.data?.detail || err.message || 'Failed to load routers')
      setRouters([])
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { fetchRouters() }, [])

  const filtered = routers.filter((r) => {
    if (!search) return true
    const q = search.toLowerCase()
    return (r.name || '').toLowerCase().includes(q) || (r.description || '').toLowerCase().includes(q)
  })

  const formatDate = (s) => {
    if (!s) return '-'
    return new Date(s).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
  }

  const columns = [
    {
      key: 'name',
      label: 'Name',
      width: '28%',
      render: (val, row) => (
        <span
          className="text-dbx-text-link hover:underline cursor-pointer font-medium"
          onClick={(e) => { e.stopPropagation(); navigate(`/routers/${row.id}`) }}
        >
          {val}
        </span>
      ),
    },
    { key: 'description', label: 'Description', width: '28%', render: (v) => v || '—' },
    {
      key: 'status', label: 'Status', width: '10%', align: 'center',
      render: (v) => <StatusBadge status={v || 'active'} />,
    },
    {
      key: 'decompose_enabled', label: 'Decompose', width: '10%', align: 'center',
      render: (v) => (
        <span className={v ? 'text-dbx-blue' : 'text-dbx-border-input'} title={v ? 'Enabled' : 'Disabled'}>
          {v ? '●' : '○'}
        </span>
      ),
    },
    {
      key: 'routing_cache_enabled', label: 'Routing cache', width: '12%', align: 'center',
      render: (v) => (
        <span className={v ? 'text-dbx-blue' : 'text-dbx-border-input'} title={v ? 'Enabled' : 'Disabled'}>
          {v ? '●' : '○'}
        </span>
      ),
    },
    { key: 'updated_at', label: 'Last Modified', width: '12%', render: (v) => formatDate(v) },
  ]

  const handleCreated = (newRouter) => {
    setShowCreate(false)
    if (newRouter?.id) navigate(`/routers/${newRouter.id}`)
    else fetchRouters()
  }

  return (
    <div className="p-6">
      <div className="flex items-start justify-between mb-5">
        <div>
          <h1 className="text-[22px] font-medium text-dbx-text">Routers</h1>
          <p className="text-[13px] text-dbx-text-secondary mt-0.5">
            Curated catalogs that route questions to the right gateway — optionally splitting a multi-intent question into sub-queries first.
          </p>
        </div>
        {isOwner && (
          <button
            onClick={() => setShowCreate(true)}
            className="flex items-center gap-2 bg-dbx-blue text-white rounded h-9 px-4 text-[13px] font-medium hover:bg-dbx-blue-dark transition-colors"
          >
            <Plus size={16} />
            Router
          </button>
        )}
      </div>

      {!loading && routers.length > 0 && (
        <div className="mb-4">
          <div className="relative w-72">
            <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-dbx-text-secondary" />
            <input
              type="text"
              placeholder="Search by name"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="w-full h-8 pl-9 pr-3 border border-dbx-border-input rounded text-[13px] text-dbx-text placeholder:text-dbx-text-secondary focus:outline-none focus:border-dbx-blue bg-dbx-bg"
            />
          </div>
        </div>
      )}

      {loading ? (
        <div className="flex items-center justify-center py-20">
          <Loader2 size={24} className="animate-spin text-dbx-text-secondary" />
        </div>
      ) : error ? (
        <div className="text-center py-12">
          <p className="text-[13px] text-red-600 mb-2">{error}</p>
          <button onClick={fetchRouters} className="text-[13px] text-dbx-text-link hover:underline">Retry</button>
        </div>
      ) : routers.length === 0 ? (
        <EmptyState
          icon={RouteIcon}
          title="No routers yet"
          description="Create a router to group gateways under a curated catalog so an LLM can route questions for you."
          action={isOwner ? (
            <button
              onClick={() => setShowCreate(true)}
              className="flex items-center gap-2 bg-dbx-blue text-white rounded h-9 px-4 text-[13px] font-medium hover:bg-dbx-blue-dark transition-colors"
            >
              <Plus size={16} />
              Create your first router
            </button>
          ) : null}
        />
      ) : (
        <DataTable
          columns={columns}
          data={filtered}
          onRowClick={(row) => navigate(`/routers/${row.id}`)}
          emptyMessage="No routers match your search"
        />
      )}

      {isOwner && (
        <RouterCreateModal open={showCreate} onClose={() => setShowCreate(false)} onCreated={handleCreated} />
      )}
    </div>
  )
}
