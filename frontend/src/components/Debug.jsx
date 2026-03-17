import { useState, useEffect } from 'react';
import { Bug, RefreshCw, CheckCircle, XCircle, AlertCircle } from 'lucide-react';
import { api } from '../services/api';

const Debug = () => {
  const [debugInfo, setDebugInfo] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const [serverConfig, setServerConfig] = useState(null);

  const fetchDebugInfo = async () => {
    setLoading(true);
    setError(null);
    try {
      const [debugResp, configResp] = await Promise.all([
        fetch('/api/debug/config'),
        fetch('/api/config'),
      ]);
      setDebugInfo(await debugResp.json());
      setServerConfig(await configResp.json());
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchDebugInfo();
  }, []);

  const getStatusIcon = (value) => {
    if (!value || value === "NOT SET" || value === "EMPTY" || value === false) {
      return <XCircle className="w-4 h-4 text-db-lava" />;
    }
    return <CheckCircle className="w-4 h-4 text-db-navy" />;
  };

  const getStatusStyle = (value) => {
    if (!value || value === "NOT SET" || value === "EMPTY" || value === false) {
      return 'bg-gray-100 text-db-lava';
    }
    return 'bg-gray-200 text-db-navy';
  };

  const localConfig = api.getConfig();

  return (
    <div className="max-w-6xl mx-auto space-y-4">
      {/* Header */}
      <div className="bg-white rounded-lg shadow-sm border p-6">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Bug className="w-6 h-6 text-gray-900" />
            <div>
              <h2 className="text-xl font-semibold text-gray-900">Debug Information</h2>
              <p className="text-sm text-gray-500">View configuration, environment variables, and API logs</p>
            </div>
          </div>
          <button
            onClick={fetchDebugInfo}
            disabled={loading}
            className="flex items-center gap-2 px-4 py-2 text-white rounded-lg bg-gray-900 disabled:opacity-50"
          >
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
            Refresh
          </button>
        </div>
      </div>

      {error && (
        <div className="rounded-lg p-4 border bg-gray-100 border-db-lava">
          <p className="text-sm text-db-lava">Error: {error}</p>
        </div>
      )}

      {/* LocalStorage Config */}
      <div className="bg-white rounded-lg shadow-sm border">
        <div className="px-6 py-4 border-b">
          <h3 className="text-lg font-semibold text-gray-900">Frontend Config (localStorage)</h3>
          <p className="text-sm text-gray-500">Configuration stored in browser</p>
        </div>
        <div className="p-6">
          {Object.keys(localConfig).length === 0 ? (
            <div className="flex items-center gap-2 text-gray-500">
              <AlertCircle className="w-4 h-4" />
              <span className="text-sm">No configuration found in localStorage</span>
            </div>
          ) : (
            <div className="space-y-2">
              {Object.entries(localConfig).map(([key, value]) => (
                <div key={key} className="flex items-center justify-between py-2 border-b">
                  <div className="flex items-center gap-2">
                    {getStatusIcon(value)}
                    <span className="font-mono text-sm text-gray-500">{key}</span>
                  </div>
                  <span className={`text-sm font-mono px-3 py-1 rounded ${getStatusStyle(value)}`}>
                    {typeof value === 'string' && value.length > 50
                      ? value.substring(0, 50) + '...'
                      : String(value)}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Server Config (Unified — shared between UI and Clone API) */}
      {serverConfig && (
        <div className="bg-white rounded-lg shadow-sm border">
          <div className="px-6 py-4 border-b">
            <h3 className="text-lg font-semibold text-gray-900">Server Config (Unified)</h3>
            <p className="text-sm text-gray-500">Active configuration used by Clone API and UI (from PUT /api/config)</p>
          </div>
          <div className="p-6">
            <div className="space-y-2">
              {Object.entries(serverConfig).map(([key, value]) => (
                <div key={key} className="flex items-center justify-between py-2 border-b">
                  <div className="flex items-center gap-2">
                    {getStatusIcon(value)}
                    <span className="font-mono text-sm text-gray-500">{key}</span>
                  </div>
                  <span className={`text-sm font-mono px-3 py-1 rounded ${getStatusStyle(value)}`}>
                    {String(value)}
                  </span>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {debugInfo && (
        <>
          {/* Environment Variables */}
          <div className="bg-white rounded-lg shadow-sm border">
            <div className="px-6 py-4 border-b">
              <h3 className="text-lg font-semibold text-gray-900">Environment Variables</h3>
              <p className="text-sm text-gray-500">Backend configuration from environment</p>
            </div>
            <div className="p-6">
              <div className="space-y-2">
                {Object.entries(debugInfo.environment_variables).map(([key, value]) => (
                  <div key={key} className="flex items-center justify-between py-2 border-b">
                    <div className="flex items-center gap-2">
                      {getStatusIcon(value)}
                      <span className="font-mono text-sm text-gray-500">{key}</span>
                    </div>
                    <span className={`text-sm font-mono px-3 py-1 rounded ${getStatusStyle(value)}`}>
                      {value}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* Request Headers */}
          <div className="bg-white rounded-lg shadow-sm border">
            <div className="px-6 py-4 border-b">
              <h3 className="text-lg font-semibold text-gray-900">Request Headers</h3>
              <p className="text-sm text-gray-500">Headers available from Databricks Apps</p>
            </div>
            <div className="p-6">
              <div className="space-y-2">
                {Object.entries(debugInfo.request_headers).map(([key, value]) => (
                  <div key={key} className="flex items-center justify-between py-2 border-b">
                    <div className="flex items-center gap-2">
                      {getStatusIcon(value)}
                      <span className="font-mono text-sm text-gray-500">{key}</span>
                    </div>
                    <span className={`text-sm font-mono px-3 py-1 rounded ${getStatusStyle(value)}`}>
                      {value}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* Config Values */}
          <div className="bg-white rounded-lg shadow-sm border">
            <div className="px-6 py-4 border-b">
              <h3 className="text-lg font-semibold text-gray-900">Backend Config Values</h3>
              <p className="text-sm text-gray-500">Actual values used by backend</p>
            </div>
            <div className="p-6">
              <div className="space-y-2">
                {Object.entries(debugInfo.config_values).map(([key, value]) => (
                  <div key={key} className="flex items-center justify-between py-2 border-b">
                    <div className="flex items-center gap-2">
                      {getStatusIcon(value)}
                      <span className="font-mono text-sm text-gray-500">{key}</span>
                    </div>
                    <span className={`text-sm font-mono px-3 py-1 rounded ${getStatusStyle(value)}`}>
                      {String(value)}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* Diagnosis */}
          <div className="rounded-lg p-6 border bg-gray-200">
            <h3 className="text-lg font-semibold mb-4 text-gray-900">Diagnosis</h3>
            <div className="space-y-2 text-sm">
              {!debugInfo.config_values.databricks_host || debugInfo.config_values.databricks_host === "EMPTY" ? (
                <div className="flex items-start gap-2 text-db-lava">
                  <XCircle className="w-4 h-4 mt-0.5" />
                  <span><strong>CRITICAL:</strong> DATABRICKS_HOST is not set. Configure it in .env or as an environment variable.</span>
                </div>
              ) : (
                <div className="flex items-start gap-2 text-db-navy">
                  <CheckCircle className="w-4 h-4 mt-0.5" />
                  <span>DATABRICKS_HOST is configured</span>
                </div>
              )}

              {!debugInfo.config_values.databricks_token_set ? (
                <div className="flex items-start gap-2 text-gray-500">
                  <AlertCircle className="w-4 h-4 mt-0.5" />
                  <span>DATABRICKS_TOKEN is not set. This is needed for App Auth mode.</span>
                </div>
              ) : (
                <div className="flex items-start gap-2 text-db-navy">
                  <CheckCircle className="w-4 h-4 mt-0.5" />
                  <span>DATABRICKS_TOKEN is configured</span>
                </div>
              )}

              {!debugInfo.config_values.genie_space_id || debugInfo.config_values.genie_space_id === "EMPTY" ? (
                <div className="flex items-start gap-2 text-gray-500">
                  <AlertCircle className="w-4 h-4 mt-0.5" />
                  <span>Genie Space ID not configured</span>
                </div>
              ) : (
                <div className="flex items-start gap-2 text-db-navy">
                  <CheckCircle className="w-4 h-4 mt-0.5" />
                  <span>Genie Space ID is configured</span>
                </div>
              )}

              {!debugInfo.config_values.sql_warehouse_id || debugInfo.config_values.sql_warehouse_id === "EMPTY" ? (
                <div className="flex items-start gap-2 text-gray-500">
                  <AlertCircle className="w-4 h-4 mt-0.5" />
                  <span>SQL Warehouse ID not configured</span>
                </div>
              ) : (
                <div className="flex items-start gap-2 text-db-navy">
                  <CheckCircle className="w-4 h-4 mt-0.5" />
                  <span>SQL Warehouse ID is configured</span>
                </div>
              )}

            </div>
          </div>
        </>
      )}
    </div>
  );
};

export default Debug;
