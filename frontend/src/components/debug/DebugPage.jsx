import { useState, useEffect } from 'react'
import { RefreshCw, CheckCircle, XCircle, AlertCircle, Loader2 } from 'lucide-react'
import { api } from '../../services/api'

const SENSITIVE_KEYS = ['user_pat', 'lakebase_service_token', 'token', 'secret', 'password', 'pat']
const OBSOLETE_KEYS = ['genie_space_id', 'genie_spaces', 'sql_warehouse_id']

function isSensitive(key) {
  return SENSITIVE_KEYS.some(k => key.toLowerCase().includes(k))
}

function StatusIcon({ value }) {
  if (value === null || value === undefined || value === '' || value === 'NOT SET' || value === false) {
    return <XCircle className="w-3.5 h-3.5 text-red-500 flex-shrink-0" />
  }
  return <CheckCircle className="w-3.5 h-3.5 text-green-600 flex-shrink-0" />
}

function formatValue(key, value) {
  if (isSensitive(key)) return '••••••••'
  if (value === null || value === undefined) return <span className="text-[#CBCBCB] italic">null</span>
  if (typeof value === 'boolean') return String(value)
  if (Array.isArray(value)) return `[${value.length} items]`
  if (typeof value === 'object') return JSON.stringify(value)
  const str = String(value)
  return str.length > 80 ? str.substring(0, 80) + '…' : str
}

function ConfigRow({ label, value }) {
  return (
    <div className="flex items-center justify-between py-1.5 border-b border-[#EBEBEB] last:border-0 gap-4">
      <div className="flex items-center gap-2 min-w-0">
        <StatusIcon value={value} />
        <code className="text-[12px] text-[#161616] font-mono truncate">{label}</code>
      </div>
      <span className="text-[12px] text-[#6F6F6F] font-mono text-right flex-shrink-0 max-w-[55%] truncate">
        {formatValue(label, value)}
      </span>
    </div>
  )
}

function StatusCard({ title, ok, details, loading }) {
  return (
    <div className={`rounded p-4 border ${ok ? 'border-green-200 bg-[#F3FCF6]' : 'border-[#EBEBEB] bg-white'}`}>
      <div className="flex items-center gap-2 mb-1">
        {loading ? (
          <Loader2 className="w-4 h-4 animate-spin text-[#6F6F6F]" />
        ) : ok ? (
          <CheckCircle className="w-4 h-4 text-green-600" />
        ) : (
          <XCircle className="w-4 h-4 text-red-500" />
        )}
        <span className="text-[13px] font-medium text-[#161616]">{title}</span>
      </div>
      {details && <p className="text-[12px] text-[#6F6F6F] ml-6">{details}</p>}
    </div>
  )
}

export default function DebugPage() {
  const [serverConfig, setServerConfig] = useState(null)
  const [gateways, setGateways] = useState([])
  const [loading, setLoading] = useState(false)
  const [connResult, setConnResult] = useState(null)
  const [testingConn, setTestingConn] = useState(false)
  const [error, setError] = useState(null)

  const fetchAll = async () => {
    setLoading(true)
    setError(null)
    try {
      const [cfg, gws] = await Promise.all([
        api.getSettings().catch(() => null),
        api.listGateways().catch(() => []),
      ])
      setServerConfig(cfg)
      setGateways(Array.isArray(gws) ? gws : [])
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  const testConnection = async () => {
    setTestingConn(true)
    setConnResult(null)
    try {
      const result = await api.testLakebaseConnection()
      setConnResult(result)
    } catch (err) {
      setConnResult({ connected: false, error: err.response?.data?.detail || err.message })
    } finally {
      setTestingConn(false)
    }
  }

  useEffect(() => { fetchAll() }, [])

  // Safe server config: filter out sensitive and obsolete keys
  const safeConfig = serverConfig
    ? Object.fromEntries(
        Object.entries(serverConfig).filter(([k]) => !isSensitive(k) && !OBSOLETE_KEYS.includes(k))
      )
    : null

  const backendOk = serverConfig !== null
  const lakebaseOk = serverConfig?.storage_backend === 'pgvector' || serverConfig?.storage_backend === 'lakebase'
  const gatewayCount = gateways.length

  return (
    <div className="p-6 max-w-3xl">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-[22px] font-medium text-[#161616]">Debug</h1>
          <p className="text-[13px] text-[#6F6F6F]">System health and configuration diagnostics</p>
        </div>
        <button
          onClick={fetchAll}
          disabled={loading}
          className="inline-flex items-center gap-1.5 h-8 px-3 text-[13px] font-medium text-[#161616] border border-[#CBCBCB] rounded hover:bg-[#F7F7F7] transition-colors disabled:opacity-50"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
          Refresh
        </button>
      </div>

      {error && (
        <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded text-[13px] text-red-700">{error}</div>
      )}

      {/* System Status */}
      <div className="bg-white border border-[#EBEBEB] rounded p-4 mb-4">
        <h2 className="text-[14px] font-medium text-[#161616] mb-3">System Status</h2>
        <div className="grid grid-cols-3 gap-3">
          <StatusCard
            title="Backend API"
            ok={backendOk}
            details={backendOk ? 'Responding' : 'Unreachable'}
            loading={loading}
          />
          <StatusCard
            title="Lakebase"
            ok={lakebaseOk}
            details={lakebaseOk ? `Instance: ${serverConfig?.lakebase_instance_name || 'configured'}` : 'Not configured'}
            loading={loading}
          />
          <StatusCard
            title="Gateways"
            ok={gatewayCount > 0}
            details={loading ? 'Loading…' : `${gatewayCount} gateway${gatewayCount !== 1 ? 's' : ''} active`}
            loading={loading}
          />
        </div>
      </div>

      {/* Lakebase Connection Test */}
      <div className="bg-white border border-[#EBEBEB] rounded p-4 mb-4">
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-[14px] font-medium text-[#161616]">Lakebase Connection</h2>
          <button
            onClick={testConnection}
            disabled={testingConn}
            className="inline-flex items-center gap-1.5 h-7 px-3 text-[12px] font-medium text-[#161616] border border-[#CBCBCB] rounded hover:bg-[#F7F7F7] transition-colors disabled:opacity-50"
          >
            {testingConn ? <Loader2 size={12} className="animate-spin" /> : null}
            {testingConn ? 'Testing…' : 'Test Connection'}
          </button>
        </div>

        {!connResult && !testingConn && (
          <p className="text-[13px] text-[#6F6F6F]">Click "Test Connection" to verify Lakebase connectivity and table status.</p>
        )}

        {testingConn && (
          <div className="flex items-center gap-2 text-[13px] text-[#6F6F6F]">
            <Loader2 size={14} className="animate-spin" /> Connecting to Lakebase…
          </div>
        )}

        {connResult && (
          <div className={`rounded p-3 text-[13px] border ${connResult.connected ? 'bg-[#F3FCF6] border-green-200' : 'bg-red-50 border-red-200'}`}>
            {connResult.connected ? (
              <>
                <div className="flex items-center gap-1.5 font-medium text-green-700 mb-2">
                  <CheckCircle size={14} /> Connected successfully
                </div>
                <div className="grid grid-cols-3 gap-2">
                  {[
                    ['cache_table_exists', 'Cache table'],
                    ['query_log_table_exists', 'Query log table'],
                    ['gateway_table_exists', 'Gateway configs table'],
                  ].map(([key, label]) => (
                    <div key={key} className="flex items-center gap-1.5 text-[12px]">
                      {connResult[key]
                        ? <CheckCircle size={12} className="text-green-600" />
                        : <AlertCircle size={12} className="text-amber-500" />}
                      <span className={connResult[key] ? 'text-green-700' : 'text-amber-600'}>
                        {label}: {connResult[key] ? 'exists' : 'will be created on startup'}
                      </span>
                    </div>
                  ))}
                </div>
              </>
            ) : (
              <div className="flex items-center gap-1.5 text-red-700">
                <XCircle size={14} /> {connResult.error || 'Connection failed'}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Gateways */}
      {gatewayCount > 0 && (
        <div className="bg-white border border-[#EBEBEB] rounded p-4 mb-4">
          <h2 className="text-[14px] font-medium text-[#161616] mb-3">Active Gateways ({gatewayCount})</h2>
          <div className="space-y-2">
            {gateways.map(gw => (
              <div key={gw.id} className="flex items-center justify-between py-2 border-b border-[#EBEBEB] last:border-0">
                <div>
                  <span className="text-[13px] font-medium text-[#161616]">{gw.name}</span>
                  <span className="ml-2 text-[11px] text-[#6F6F6F] font-mono">{gw.id}</span>
                </div>
                <div className="flex items-center gap-3 text-[12px] text-[#6F6F6F]">
                  <span>ID: <code className="font-mono">{gw.id?.substring(0, 12)}…</code></span>
                  <span className={`px-1.5 py-0.5 rounded text-[11px] font-medium ${gw.status === 'active' ? 'bg-[#F3FCF6] text-green-700' : 'bg-[#F7F7F7] text-[#6F6F6F]'}`}>
                    {gw.status}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Server Config (safe fields only) */}
      {safeConfig && (
        <div className="bg-white border border-[#EBEBEB] rounded p-4">
          <h2 className="text-[14px] font-medium text-[#161616] mb-3">Backend Configuration</h2>
          <p className="text-[12px] text-[#6F6F6F] mb-3">Active server settings. Sensitive values are hidden.</p>
          <div>
            {Object.entries(safeConfig).map(([key, value]) => (
              <ConfigRow key={key} label={key} value={value} />
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
