import { useState, useEffect, useCallback } from 'react'
import { RefreshCw, FileText, CheckCircle, XCircle, Loader } from 'lucide-react'
import { api } from '../../services/api'
import DataTable from '../shared/DataTable'

export default function GatewayLogsTab({ gateway }) {
  const [queryLogs, setQueryLogs] = useState([])
  const [loading, setLoading] = useState(true)
  const [autoRefresh, setAutoRefresh] = useState(false)

  const fetchQueryLogs = useCallback(async () => {
    try {
      setLoading(true)
      const logs = await api.getGatewayLogs(gateway.id, 50)
      setQueryLogs((logs || []).sort((a, b) => new Date(b.created_at) - new Date(a.created_at)))
    } catch {
      setQueryLogs([])
    } finally {
      setLoading(false)
    }
  }, [gateway.id])

  useEffect(() => {
    fetchQueryLogs()
  }, [fetchQueryLogs])

  useEffect(() => {
    if (autoRefresh) {
      const interval = setInterval(fetchQueryLogs, 2000)
      return () => clearInterval(interval)
    }
  }, [autoRefresh, fetchQueryLogs])

  const formatDate = (dateString) => {
    return new Date(dateString).toLocaleString('en-US', {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    })
  }

  const getStatusIcon = (stage) => {
    if (stage === 'completed') return <CheckCircle size={14} className="text-green-600" />
    if (stage === 'failed') return <XCircle size={14} className="text-red-600" />
    return <Loader size={14} className="animate-spin text-[#6F6F6F]" />
  }

  const completed = queryLogs.filter((q) => q.stage === 'completed').length
  const failed = queryLogs.filter((q) => q.stage === 'failed').length
  const inProgress = queryLogs.filter((q) => q.stage !== 'completed' && q.stage !== 'failed').length
  const cacheHits = queryLogs.filter((q) => q.from_cache).length

  const columns = [
    {
      key: 'created_at',
      label: 'Time',
      width: '150px',
      render: (val) => <span className="text-[#6F6F6F]">{formatDate(val)}</span>,
    },
    {
      key: 'query_text',
      label: 'Query',
      render: (val) => (
        <span className="block truncate max-w-[280px]" title={val}>
          {val}
        </span>
      ),
    },
    {
      key: 'identity',
      label: 'Identity',
      width: '100px',
      render: (val) => (
        <span className="inline-flex px-2 py-0.5 rounded text-[11px] bg-[#F7F7F7] text-[#161616]">
          {val || '-'}
        </span>
      ),
    },
    {
      key: 'stage',
      label: 'Status',
      width: '120px',
      render: (val) => (
        <span
          className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-[11px] font-medium ${
            val === 'completed'
              ? 'bg-[#F3FCF6] text-green-700'
              : val === 'failed'
              ? 'bg-red-50 text-red-600'
              : 'bg-gray-100 text-[#6F6F6F]'
          }`}
        >
          {getStatusIcon(val)}
          {val ? val.replace('_', ' ') : 'processing'}
        </span>
      ),
    },
    {
      key: 'from_cache',
      label: 'From Cache',
      width: '100px',
      render: (val) =>
        val ? (
          <span className="inline-flex items-center px-2 py-0.5 rounded text-[11px] font-medium bg-[#F3FCF6] text-green-700">
            Cache Hit
          </span>
        ) : (
          <span className="text-[#6F6F6F]">-</span>
        ),
    },
    {
      key: 'query_id',
      label: 'Query ID',
      width: '100px',
      render: (val) => (
        <span className="font-mono text-[#6F6F6F]">
          {val ? val.substring(0, 8) + '...' : '-'}
        </span>
      ),
    },
  ]

  return (
    <div className="space-y-4">
      {/* Controls */}
      <div className="flex items-center gap-4">
        <label className="flex items-center gap-2 text-[13px] text-[#6F6F6F] cursor-pointer">
          <input
            type="checkbox"
            checked={autoRefresh}
            onChange={(e) => setAutoRefresh(e.target.checked)}
            className="rounded accent-[#2272B4]"
          />
          Auto-refresh
        </label>
        <button
          onClick={fetchQueryLogs}
          disabled={loading}
          className="inline-flex items-center gap-1.5 h-8 px-3 text-[13px] font-medium text-[#161616] border border-[#CBCBCB] rounded hover:bg-[#F7F7F7] transition-colors disabled:opacity-50"
        >
          <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
          Refresh
        </button>
      </div>

      {/* Stats row */}
      <div className="grid grid-cols-5 gap-4">
        <div className="bg-white border border-[#EBEBEB] rounded p-4">
          <div className="text-[22px] font-medium text-[#161616]">{queryLogs.length}</div>
          <div className="text-[13px] text-[#6F6F6F]">Total</div>
        </div>
        <div className="bg-white border border-[#EBEBEB] rounded p-4">
          <div className="text-[22px] font-medium text-[#161616]">{completed}</div>
          <div className="text-[13px] text-[#6F6F6F]">Completed</div>
        </div>
        <div className="bg-white border border-[#EBEBEB] rounded p-4">
          <div className="text-[22px] font-medium text-[#161616]">{failed}</div>
          <div className="text-[13px] text-[#6F6F6F]">Failed</div>
        </div>
        <div className="bg-white border border-[#EBEBEB] rounded p-4">
          <div className="text-[22px] font-medium text-[#161616]">{inProgress}</div>
          <div className="text-[13px] text-[#6F6F6F]">In Progress</div>
        </div>
        <div className="bg-white border border-[#EBEBEB] rounded p-4">
          <div className="text-[22px] font-medium text-[#161616]">{cacheHits}</div>
          <div className="text-[13px] text-[#6F6F6F]">Cache Hits</div>
        </div>
      </div>

      {/* Table */}
      {loading && queryLogs.length === 0 ? (
        <div className="flex items-center justify-center py-12">
          <RefreshCw className="w-5 h-5 animate-spin text-[#6F6F6F]" />
        </div>
      ) : (
        <div className="border border-[#EBEBEB] rounded overflow-hidden">
          <DataTable
            columns={columns}
            data={queryLogs}
            emptyMessage={
              <div className="flex flex-col items-center">
                <FileText size={32} className="text-[#D8D8D8] mb-2" />
                <span>No query logs for this gateway</span>
              </div>
            }
          />
        </div>
      )}
    </div>
  )
}
