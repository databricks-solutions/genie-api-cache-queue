import { useState, useEffect, useCallback, useRef, useMemo } from 'react'
import { RefreshCw, Trash2, Database, TrendingUp, AlertTriangle } from 'lucide-react'
import { api } from '../../services/api'
import DataTable from '../shared/DataTable'
import Modal from '../shared/Modal'

export default function GatewayCacheTab({ gateway }) {
  const [cachedQueries, setCachedQueries] = useState([])
  const [loading, setLoading] = useState(true)
  const [autoRefresh, setAutoRefresh] = useState(false)
  const [error, setError] = useState(null)
  const [deleting, setDeleting] = useState(false)
  const [showConfirm, setShowConfirm] = useState(false)
  const [selectedIds, setSelectedIds] = useState(() => new Set())
  const headerCheckboxRef = useRef(null)

  const fetchCachedQueries = useCallback(async () => {
    try {
      setLoading(true)
      setError(null)
      const data = await api.getGatewayCache(gateway.id)
      setCachedQueries((data || []).sort((a, b) => new Date(b.last_used) - new Date(a.last_used)))
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [gateway.id])

  useEffect(() => {
    fetchCachedQueries()
  }, [fetchCachedQueries])

  useEffect(() => {
    if (autoRefresh) {
      const interval = setInterval(fetchCachedQueries, 5000)
      return () => clearInterval(interval)
    }
  }, [autoRefresh, fetchCachedQueries])

  // Prune selections that no longer exist after a refresh.
  useEffect(() => {
    setSelectedIds((prev) => {
      if (prev.size === 0) return prev
      const existing = new Set(cachedQueries.map((q) => q.id))
      const next = new Set()
      for (const id of prev) if (existing.has(id)) next.add(id)
      return next.size === prev.size ? prev : next
    })
  }, [cachedQueries])

  const allSelected = cachedQueries.length > 0 && selectedIds.size === cachedQueries.length
  const someSelected = selectedIds.size > 0 && !allSelected

  useEffect(() => {
    if (headerCheckboxRef.current) {
      headerCheckboxRef.current.indeterminate = someSelected
    }
  }, [someSelected])

  const toggleOne = (id) => {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const toggleAll = () => {
    setSelectedIds((prev) => {
      if (prev.size === cachedQueries.length) return new Set()
      return new Set(cachedQueries.map((q) => q.id))
    })
  }

  const handleDeleteSelected = async () => {
    setShowConfirm(false)
    const ids = [...selectedIds]
    if (ids.length === 0) return
    try {
      setDeleting(true)
      await api.deleteGatewayCacheEntries(gateway.id, ids)
      setSelectedIds(new Set())
      await fetchCachedQueries()
    } catch (err) {
      setError('Failed to delete entries: ' + err.message)
    } finally {
      setDeleting(false)
    }
  }

  const isFresh = (createdAt) => {
    const ttlSeconds = gateway.cache_ttl_seconds || 86400
    if (ttlSeconds === 0) return true
    const created = new Date(createdAt)
    const now = new Date()
    const secondsOld = (now - created) / 1000
    return secondsOld <= ttlSeconds
  }

  const totalUses = cachedQueries.reduce((sum, q) => sum + (q.use_count || 0), 0)
  const avgUses = cachedQueries.length > 0
    ? (totalUses / cachedQueries.length).toFixed(1)
    : '0'

  const columns = useMemo(() => [
    {
      key: '__select',
      width: '36px',
      label: (
        <input
          ref={headerCheckboxRef}
          type="checkbox"
          aria-label="Select all"
          checked={allSelected}
          onChange={toggleAll}
          disabled={cachedQueries.length === 0}
          className="rounded accent-dbx-blue cursor-pointer align-middle"
        />
      ),
      render: (_, row) => (
        <input
          type="checkbox"
          aria-label={`Select entry ${row.id}`}
          checked={selectedIds.has(row.id)}
          onChange={(e) => { e.stopPropagation(); toggleOne(row.id) }}
          onClick={(e) => e.stopPropagation()}
          className="rounded accent-dbx-blue cursor-pointer align-middle"
        />
      ),
    },
    {
      key: 'id',
      label: 'ID',
      width: '60px',
      render: (val) => <span className="text-dbx-text-secondary">#{val}</span>,
    },
    {
      key: 'query_text',
      label: 'Query',
      render: (val) => (
        <span className="block truncate" title={val}>
          {val}
        </span>
      ),
    },
    {
      key: 'sql_query',
      label: 'SQL',
      render: (val) => (
        <code
          className="text-[12px] px-1.5 py-0.5 rounded block truncate bg-dbx-sidebar text-dbx-text"
          title={val}
        >
          {val || '-'}
        </code>
      ),
    },
    {
      key: 'created_at',
      label: 'Status',
      render: (val) =>
        isFresh(val) ? (
          <span className="inline-flex items-center px-2 py-0.5 rounded text-[11px] font-medium bg-dbx-status-green-bg text-green-700">
            Fresh
          </span>
        ) : (
          <span className="inline-flex items-center px-2 py-0.5 rounded text-[11px] font-medium bg-dbx-sidebar text-dbx-text-secondary">
            Stale
          </span>
        ),
    },
    {
      key: 'use_count',
      label: 'Uses',
      width: '70px',
      render: (val) => (
        <span className="inline-flex items-center px-2 py-0.5 rounded text-[11px] font-medium bg-dbx-sidebar text-dbx-text">
          {val || 0}
        </span>
      ),
    },
    {
      key: 'last_used',
      label: 'Last Used',
      render: (val) => (
        <span className="text-dbx-text-secondary">
          {val ? new Date(val).toLocaleString('en-US', {
            month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
          }) : '-'}
        </span>
      ),
    },
  ], [allSelected, cachedQueries.length, selectedIds, gateway.cache_ttl_seconds])

  const selectedCount = selectedIds.size
  const confirmLabel = selectedCount === 1 ? 'entry' : 'entries'

  return (
    <div className="space-y-4">
      {/* Controls */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <label className="flex items-center gap-2 text-[13px] text-dbx-text-secondary cursor-pointer">
            <input
              type="checkbox"
              checked={autoRefresh}
              onChange={(e) => setAutoRefresh(e.target.checked)}
              className="rounded accent-dbx-blue"
            />
            Auto-refresh
          </label>
          <button
            onClick={fetchCachedQueries}
            disabled={loading}
            className="inline-flex items-center gap-1.5 h-8 px-3 text-[13px] font-medium text-dbx-text border border-dbx-border-input rounded hover:bg-dbx-neutral-hover transition-colors disabled:opacity-50"
          >
            <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
            Refresh
          </button>
        </div>
        <div className="flex items-center gap-2">
          {selectedCount > 0 && (
            <>
              <span className="text-[12px] text-dbx-text-secondary">
                {selectedCount} selected
              </span>
              <button
                onClick={() => setSelectedIds(new Set())}
                className="h-8 px-2 text-[12px] text-dbx-text-secondary hover:text-dbx-text transition-colors"
              >
                Clear selection
              </button>
              <button
                onClick={() => setShowConfirm(true)}
                disabled={deleting}
                className="inline-flex items-center gap-1.5 h-8 px-3 text-[13px] font-medium text-dbx-text-danger border border-dbx-border-input rounded hover:bg-dbx-neutral-hover transition-colors disabled:opacity-50"
              >
                <Trash2 size={14} />
                {deleting ? 'Deleting...' : `Delete ${selectedCount}`}
              </button>
            </>
          )}
        </div>
      </div>

      {/* Stats row */}
      <div className="grid grid-cols-3 gap-4">
        <div className="bg-dbx-bg border border-dbx-border rounded p-4">
          <div className="text-[22px] font-medium text-dbx-text">{cachedQueries.length}</div>
          <div className="text-[13px] text-dbx-text-secondary">Cache entries</div>
        </div>
        <div className="bg-dbx-bg border border-dbx-border rounded p-4">
          <div className="text-[22px] font-medium text-dbx-text">{totalUses}</div>
          <div className="text-[13px] text-dbx-text-secondary">Total hits</div>
        </div>
        <div className="bg-dbx-bg border border-dbx-border rounded p-4">
          <div className="flex items-center gap-1.5">
            <span className="text-[22px] font-medium text-dbx-text">{avgUses}</span>
            <TrendingUp size={16} className="text-dbx-text-secondary" />
          </div>
          <div className="text-[13px] text-dbx-text-secondary">Avg uses per query</div>
        </div>
      </div>

      {/* Table */}
      {error ? (
        <div className="text-[13px] text-dbx-text-danger bg-dbx-status-red-bg border border-dbx-danger-border rounded p-4">
          Error loading cache: {error}
        </div>
      ) : loading && cachedQueries.length === 0 ? (
        <div className="flex items-center justify-center py-12">
          <RefreshCw className="w-5 h-5 animate-spin text-dbx-text-secondary" />
        </div>
      ) : (
        <div className="border border-dbx-border rounded overflow-hidden">
          <DataTable
            columns={columns}
            data={cachedQueries}
            emptyMessage={
              <div className="flex flex-col items-center">
                <Database size={32} className="text-dbx-disabled mb-2" />
                <span>No cache entries for this gateway</span>
              </div>
            }
          />
        </div>
      )}

      <Modal
        isOpen={showConfirm}
        onClose={() => setShowConfirm(false)}
        title="Delete Selected Entries"
        maxWidth="max-w-md"
      >
        <div className="flex flex-col items-center text-center pt-2">
          <div className="w-12 h-12 rounded-full bg-dbx-status-red-bg flex items-center justify-center mb-4">
            <AlertTriangle size={24} className="text-dbx-text-danger" />
          </div>
          <p className="text-[14px] text-dbx-text mb-1">
            Delete {selectedCount} selected {confirmLabel}?
          </p>
          <p className="text-[13px] text-dbx-text-secondary mb-6">
            <span className="font-medium text-dbx-text">{selectedCount} {confirmLabel}</span> will be permanently deleted.
            Future queries will need to go through the Genie API again.
          </p>
          <div className="flex gap-3 w-full">
            <button
              onClick={() => setShowConfirm(false)}
              className="flex-1 h-9 text-[13px] font-medium text-dbx-text border border-dbx-border-input rounded hover:bg-dbx-neutral-hover transition-colors"
            >
              Cancel
            </button>
            <button
              onClick={handleDeleteSelected}
              className="flex-1 h-9 text-[13px] font-medium text-white bg-dbx-text-danger rounded hover:opacity-90 transition-colors"
            >
              Delete {selectedCount} {confirmLabel}
            </button>
          </div>
        </div>
      </Modal>
    </div>
  )
}
