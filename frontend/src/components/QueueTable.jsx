import { useState, useEffect } from 'react';
import { RefreshCw, FileText, Clock, CheckCircle, XCircle, Loader } from 'lucide-react';
import { api } from '../services/api';

const QueueTable = () => {
  const [queryLogs, setQueryLogs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [autoRefresh, setAutoRefresh] = useState(true);

  const fetchQueryLogs = async () => {
    try {
      setLoading(true);

      const config = api.getConfig();
      let allLogs = [];

      if (config.storage_backend === 'lakebase') {
        const backendLogs = await api.getQueryLogs();
        allLogs = backendLogs;
      } else {
        const localLogs = JSON.parse(localStorage.getItem('query_logs') || '[]');
        allLogs = localLogs;
      }

      const sorted = allLogs.sort((a, b) => new Date(b.created_at) - new Date(a.created_at)).slice(0, 50);
      setQueryLogs(sorted);
    } catch {
      const localLogs = JSON.parse(localStorage.getItem('query_logs') || '[]');
      const sorted = localLogs.sort((a, b) => new Date(b.created_at) - new Date(a.created_at)).slice(0, 50);
      setQueryLogs(sorted);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchQueryLogs();
  }, []);

  useEffect(() => {
    if (autoRefresh) {
      const interval = setInterval(fetchQueryLogs, 2000);
      return () => clearInterval(interval);
    }
  }, [autoRefresh]);

  const formatDate = (dateString) => {
    return new Date(dateString).toLocaleString('en-US', {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit'
    });
  };

  const getStatusIcon = (stage) => {
    if (stage === 'completed') return <CheckCircle className="w-4 h-4 text-db-navy" />;
    if (stage === 'failed') return <XCircle className="w-4 h-4 text-db-lava" />;
    return <Loader className="w-4 h-4 animate-spin text-gray-900" />;
  };

  const getStatusColor = (stage) => {
    if (stage === 'completed') return 'bg-gray-200 text-db-navy';
    if (stage === 'failed') return 'bg-gray-100 text-db-lava';
    return 'bg-gray-200 text-gray-900';
  };

  const clearLogs = () => {
    if (confirm('Clear all query logs?')) {
      localStorage.removeItem('query_logs');
      setQueryLogs([]);
    }
  };

  const queriesToGenie = (() => {
    const oneMinuteAgo = Date.now() - 60000;
    return queryLogs.filter(q =>
      new Date(q.created_at).getTime() > oneMinuteAgo &&
      !q.from_cache
    ).length;
  })();

  return (
    <div className="space-y-4">
      {/* Queries to Genie - Stats Card */}
      <div className="bg-white rounded-lg border p-6">
        <div className="flex items-center justify-between">
          <div>
            <div className="text-sm font-medium mb-1 text-gray-500">
              Queries to Genie API (Last Minute)
            </div>
            <div className="text-5xl font-bold text-gray-900">
              {queriesToGenie}
            </div>
            <div className="text-sm mt-2 text-gray-500">
              Queries that missed the cache and required Genie API calls
            </div>
          </div>
        </div>
        {queriesToGenie >= 5 && (
          <div className="mt-3 p-3 rounded text-sm border-l-4 border-l-db-lava bg-gray-100 text-db-lava">
            Rate limit threshold reached - new queries may be queued
          </div>
        )}
      </div>

      <div className="bg-white rounded-lg shadow-sm border">
        {/* Header */}
        <div className="px-6 py-4 border-b flex items-center justify-between">
          <div className="flex items-center gap-3">
            <FileText className="w-5 h-5 text-gray-900" />
            <div>
              <h2 className="text-lg font-semibold text-gray-900">
                Query Submission Logs
              </h2>
              <p className="text-sm text-gray-500">
                History of all submitted queries and their status
              </p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <label className="flex items-center gap-2 text-sm text-gray-500">
              <input
                type="checkbox"
                checked={autoRefresh}
                onChange={(e) => setAutoRefresh(e.target.checked)}
                className="rounded accent-db-lava"
              />
              Auto-refresh
            </label>
            <button
              onClick={clearLogs}
              className="flex items-center gap-2 px-4 py-2 text-white rounded-lg text-sm bg-gray-900 transition-colors"
              onMouseEnter={(e) => { e.currentTarget.style.opacity = '0.85'; }}
              onMouseLeave={(e) => { e.currentTarget.style.opacity = '1'; }}
            >
              Clear Logs
            </button>
            <button
              onClick={fetchQueryLogs}
              disabled={loading}
              className="flex items-center gap-2 px-4 py-2 text-white rounded-lg bg-gray-900 disabled:bg-gray-300 transition-colors"
              onMouseEnter={(e) => { if (!loading) e.currentTarget.style.opacity = '0.85'; }}
              onMouseLeave={(e) => { if (!loading) e.currentTarget.style.opacity = '1'; }}
            >
              <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
              Refresh
            </button>
          </div>
        </div>

        {/* Stats */}
        <div className="px-6 py-3 border-b bg-gray-100">
          <div className="flex items-center gap-8">
            <div>
              <div className="text-sm text-gray-500">Total Queries</div>
              <div className="text-2xl font-bold text-gray-900">{queryLogs.length}</div>
            </div>
            <div>
              <div className="text-sm text-gray-500">Completed</div>
              <div className="text-2xl font-bold text-gray-900">{queryLogs.filter(q => q.stage === 'completed').length}</div>
            </div>
            <div>
              <div className="text-sm text-gray-500">Failed</div>
              <div className="text-2xl font-bold text-gray-900">{queryLogs.filter(q => q.stage === 'failed').length}</div>
            </div>
            <div>
              <div className="text-sm text-gray-500">In Progress</div>
              <div className="text-2xl font-bold text-gray-900">{queryLogs.filter(q => q.stage !== 'completed' && q.stage !== 'failed').length}</div>
            </div>
            <div>
              <div className="text-sm text-gray-500">Cache Hits</div>
              <div className="text-2xl font-bold text-gray-900">{queryLogs.filter(q => q.from_cache).length}</div>
            </div>
          </div>
        </div>

        {/* Table */}
        <div className="overflow-x-auto">
        <table className="w-full">
          <thead className="bg-gray-200">
            <tr>
              <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Time</th>
              <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Query</th>
              <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Identity</th>
              <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Status</th>
              <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">From Cache</th>
              <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Query ID</th>
            </tr>
          </thead>
          <tbody className="bg-white divide-y divide-gray-200">
            {loading ? (
              <tr>
                <td colSpan="6" className="px-6 py-4 text-center text-gray-500">
                  <RefreshCw className="w-5 h-5 animate-spin mx-auto mb-2" />
                  Loading query logs...
                </td>
              </tr>
            ) : queryLogs.length === 0 ? (
              <tr>
                <td colSpan="6" className="px-6 py-4 text-center text-gray-500">
                  <FileText className="w-12 h-12 mx-auto mb-2 text-gray-300" />
                  <div className="font-medium">No query logs available</div>
                  <div className="text-sm mt-1">Query logs will appear here once queries are submitted.</div>
                </td>
              </tr>
            ) : (
              queryLogs.map((log) => (
                <tr
                  key={log.query_id}
                  className="transition-colors hover:bg-gray-200"
                >
                  <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">{formatDate(log.created_at)}</td>
                  <td className="px-6 py-4 text-sm max-w-md text-gray-900">
                    <div className="truncate" title={log.query_text}>{log.query_text}</div>
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-sm">
                    <span className="px-2 py-1 rounded-full text-xs bg-gray-200 text-gray-900">{log.identity}</span>
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-sm">
                    <span className={`inline-flex items-center gap-1 px-2 py-1 rounded-full text-xs font-medium ${getStatusColor(log.stage)}`}>
                      {getStatusIcon(log.stage)}
                      {log.stage.replace('_', ' ')}
                    </span>
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-sm text-center">
                    {log.from_cache ? (
                      <span className="inline-flex items-center px-2 py-1 rounded-full text-xs font-medium bg-gray-200 text-db-navy">
                        Cache Hit
                      </span>
                    ) : (
                      <span className="text-gray-500">-</span>
                    )}
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-sm font-mono text-gray-500">
                    {log.query_id.substring(0, 8)}...
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
        </div>
      </div>
    </div>
  );
};

export default QueueTable;
