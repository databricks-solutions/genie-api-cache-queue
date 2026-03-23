import { useState, useEffect } from 'react'
import { BarChart3, Loader2 } from 'lucide-react'
import { api } from '../../services/api'

export default function GatewayMetricsTab({ gateway }) {
  const [metrics, setMetrics] = useState(null)
  const [logs, setLogs] = useState([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const fetchData = async () => {
      try {
        setLoading(true)
        const [metricsData, logsData] = await Promise.all([
          api.getGatewayMetrics(gateway.id).catch(() => null),
          api.getGatewayLogs(gateway.id, 10).catch(() => []),
        ])
        setMetrics(metricsData)
        setLogs((logsData || []).sort((a, b) => new Date(b.created_at) - new Date(a.created_at)))
      } finally {
        setLoading(false)
      }
    }
    fetchData()
  }, [gateway.id])

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2 className="w-5 h-5 animate-spin text-[#6F6F6F]" />
      </div>
    )
  }

  const totalQueries = metrics?.total_queries ?? logs.length
  const cacheHits = metrics?.cache_hits ?? logs.filter((l) => l.from_cache).length
  const cacheMisses = totalQueries - cacheHits
  const hitPct = totalQueries > 0 ? ((cacheHits / totalQueries) * 100).toFixed(1) : '0.0'
  const missPct = totalQueries > 0 ? ((cacheMisses / totalQueries) * 100).toFixed(1) : '0.0'

  const formatDate = (dateString) => {
    return new Date(dateString).toLocaleString('en-US', {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    })
  }

  return (
    <div className="space-y-6">
      {/* Cache Hit/Miss ratio */}
      <div className="bg-white border border-[#EBEBEB] rounded p-5">
        <h3 className="text-[13px] font-medium text-[#161616] mb-3">Cache Hit / Miss Ratio</h3>
        <div className="flex items-center gap-4 mb-2">
          <span className="text-[13px] text-[#6F6F6F] w-16">Hits</span>
          <div className="flex-1 h-6 bg-[#EBEBEB] rounded overflow-hidden flex">
            {totalQueries > 0 && (
              <>
                <div
                  className="h-full bg-[#FF3621] transition-all duration-500"
                  style={{ width: `${hitPct}%` }}
                />
                <div
                  className="h-full bg-[#D8D8D8] transition-all duration-500"
                  style={{ width: `${missPct}%` }}
                />
              </>
            )}
          </div>
          <span className="text-[13px] text-[#161616] font-medium w-16 text-right">{hitPct}%</span>
        </div>
        <div className="flex items-center gap-4">
          <span className="text-[13px] text-[#6F6F6F] w-16">Misses</span>
          <div className="flex items-center gap-3 text-[13px]">
            <span className="flex items-center gap-1.5">
              <span className="w-3 h-3 rounded bg-[#FF3621] inline-block" />
              Cache hits: {cacheHits}
            </span>
            <span className="flex items-center gap-1.5">
              <span className="w-3 h-3 rounded bg-[#D8D8D8] inline-block" />
              Cache misses: {cacheMisses}
            </span>
          </div>
          <span className="text-[13px] text-[#161616] font-medium w-16 text-right">{missPct}%</span>
        </div>
      </div>

      {/* Total queries card */}
      <div className="bg-white border border-[#EBEBEB] rounded p-5">
        <div className="text-[13px] text-[#6F6F6F] mb-1">Total Queries</div>
        <div className="text-[28px] font-medium text-[#161616]">{totalQueries}</div>
      </div>

      {/* Recent query activity */}
      <div className="bg-white border border-[#EBEBEB] rounded overflow-hidden">
        <div className="px-5 py-4 border-b border-[#EBEBEB]">
          <h3 className="text-[13px] font-medium text-[#161616]">Recent Query Activity</h3>
        </div>

        {logs.length === 0 ? (
          <div className="text-center py-12 text-[13px] text-[#6F6F6F]">
            <BarChart3 size={32} className="mx-auto mb-2 text-[#D8D8D8]" />
            No recent queries
          </div>
        ) : (
          <div className="divide-y divide-[#EBEBEB]">
            {logs.map((log) => (
              <div key={log.query_id} className="flex items-center gap-4 px-5 py-3 hover:bg-[#F7F7F7]">
                <span className="text-[13px] text-[#6F6F6F] w-36 flex-shrink-0">
                  {formatDate(log.created_at)}
                </span>
                <span className="text-[13px] text-[#161616] flex-1 truncate" title={log.query_text}>
                  {log.query_text}
                </span>
                <span className="flex-shrink-0">
                  {log.from_cache ? (
                    <span className="inline-flex items-center px-2 py-0.5 rounded text-[11px] font-medium bg-[#F3FCF6] text-[#FF3621]">
                      Cache Hit
                    </span>
                  ) : log.stage === 'completed' ? (
                    <span className="inline-flex items-center px-2 py-0.5 rounded text-[11px] font-medium bg-blue-50 text-[#2272B4]">
                      Completed
                    </span>
                  ) : log.stage === 'failed' ? (
                    <span className="inline-flex items-center px-2 py-0.5 rounded text-[11px] font-medium bg-red-50 text-red-600">
                      Failed
                    </span>
                  ) : (
                    <span className="inline-flex items-center px-2 py-0.5 rounded text-[11px] font-medium bg-gray-100 text-[#6F6F6F]">
                      {log.stage || 'Processing'}
                    </span>
                  )}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
