import { useState, useEffect } from 'react';
import { api } from '../services/api';
import { RefreshCw, Database, TrendingUp } from 'lucide-react';

const CacheTable = () => {
  const [cachedQueries, setCachedQueries] = useState([]);
  const [loading, setLoading] = useState(true);
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [error, setError] = useState(null);
  const [storageLabel, setStorageLabel] = useState('Cache');

  useEffect(() => {
    const config = api.getConfig();
    const backend = config.storage_backend;
    if (backend === 'lakebase') setStorageLabel('Cache (Lakebase)');
    else setStorageLabel('Cache (Local)');
  }, []);

  const fetchCachedQueries = async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await api.getCachedQueries(null);
      const sorted = (data || []).sort((a, b) =>
        new Date(b.last_used) - new Date(a.last_used)
      ).slice(0, 10);
      setCachedQueries(sorted);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchCachedQueries();
  }, []);

  useEffect(() => {
    if (autoRefresh) {
      const interval = setInterval(fetchCachedQueries, 5000);
      return () => clearInterval(interval);
    }
  }, [autoRefresh]);

  const formatDate = (dateString) => {
    return new Date(dateString).toLocaleString();
  };

  const isFresh = (createdAt) => {
    const config = api.getConfig();
    const ttl = api.computeTtlHours(config);
    if (ttl === 0) return true;
    const created = new Date(createdAt);
    const now = new Date();
    const hoursOld = (now - created) / (1000 * 60 * 60);
    return hoursOld <= ttl;
  };

  return (
    <div className="bg-white rounded-lg shadow-sm border">
      {/* Header */}
      <div className="px-6 py-4 border-b flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Database className="w-5 h-5 text-gray-900" />
          <div>
            <h2 className="text-lg font-semibold text-gray-900">
              {storageLabel}
            </h2>
            <p className="text-sm text-gray-500">
              Cached queries with embeddings
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
            onClick={fetchCachedQueries}
            disabled={loading}
            className="flex items-center gap-2 px-4 py-2 text-white rounded-lg bg-gray-900 disabled:bg-gray-300 transition-colors"
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
            <div className="text-sm text-gray-500">Showing</div>
            <div className="text-2xl font-bold text-gray-900">
              {cachedQueries.length}
            </div>
            <div className="text-xs text-gray-500">most recent</div>
          </div>
          <div>
            <div className="text-sm text-gray-500">Total Uses</div>
            <div className="text-2xl font-bold text-gray-900">
              {cachedQueries.reduce((sum, q) => sum + q.use_count, 0)}
            </div>
            <div className="text-xs text-gray-500">cache hits</div>
          </div>
          <div>
            <div className="text-sm text-gray-500">Avg Uses</div>
            <div className="text-2xl font-bold flex items-center gap-2 text-gray-900">
              {cachedQueries.length > 0
                ? (cachedQueries.reduce((sum, q) => sum + q.use_count, 0) / cachedQueries.length).toFixed(1)
                : '0'}
              <TrendingUp className="w-4 h-4" />
            </div>
            <div className="text-xs text-gray-500">per query</div>
          </div>
        </div>
      </div>

      {/* Table */}
      <div className="overflow-x-auto">
        <table className="w-full">
          <thead className="bg-gray-200">
            <tr>
              <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">ID</th>
              <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Query</th>
              <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">SQL</th>
              <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Status</th>
              <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Uses</th>
              <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Last Used</th>
            </tr>
          </thead>
          <tbody className="bg-white divide-y divide-gray-200">
            {loading ? (
              <tr>
                <td colSpan="6" className="px-6 py-4 text-center text-gray-500">
                  <RefreshCw className="w-5 h-5 animate-spin mx-auto mb-2" />
                  Loading cached queries...
                </td>
              </tr>
            ) : error ? (
              <tr>
                <td colSpan="6" className="px-6 py-4 text-center text-db-lava">
                  Error: {error}
                </td>
              </tr>
            ) : cachedQueries.length === 0 ? (
              <tr>
                <td colSpan="6" className="px-6 py-4 text-center text-gray-500">
                  <Database className="w-12 h-12 mx-auto mb-2 text-gray-300" />
                  <div className="font-medium">No cached queries available</div>
                  <div className="text-sm mt-1">
                    Cached queries will appear here once submitted.
                  </div>
                </td>
              </tr>
            ) : (
              cachedQueries.map((query) => (
                <tr
                  key={query.id}
                  className="transition-colors hover:bg-gray-200"
                >
                  <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">
                    #{query.id}
                  </td>
                  <td className="px-6 py-4 text-sm max-w-xs text-gray-900">
                    <div className="truncate" title={query.query_text}>
                      {query.query_text}
                    </div>
                  </td>
                  <td className="px-6 py-4 text-sm max-w-xs text-gray-500">
                    <code className="text-xs px-2 py-1 rounded block truncate bg-gray-200 text-gray-900" title={query.sql_query}>
                      {query.sql_query.substring(0, 60)}...
                    </code>
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-sm">
                    {isFresh(query.created_at) ? (
                      <span className="px-2 py-1 rounded-full text-xs font-medium bg-gray-200 text-db-navy">
                        Fresh
                      </span>
                    ) : (
                      <span className="px-2 py-1 rounded-full text-xs font-medium bg-gray-200 text-gray-500">
                        Stale
                      </span>
                    )}
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-sm">
                    <span className="inline-flex items-center px-2 py-1 rounded-full text-xs font-semibold bg-gray-200 text-gray-900">
                      {query.use_count}
                    </span>
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                    {formatDate(query.last_used)}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
};

export default CacheTable;
