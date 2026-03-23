import { useState, useEffect } from 'react'
import { Save, Eye, EyeOff, Loader2, CheckCircle, XCircle, FlaskConical } from 'lucide-react'
import { api } from '../../services/api'

const secondsToTtl = (seconds) => {
  if (!seconds || seconds === 0) return { value: '0', unit: 'hours' }
  if (seconds >= 86400 && seconds % 86400 === 0) return { value: String(seconds / 86400), unit: 'days' }
  if (seconds >= 3600 && seconds % 3600 === 0) return { value: String(seconds / 3600), unit: 'hours' }
  return { value: String(seconds / 60), unit: 'minutes' }
}

const ttlToSeconds = (value, unit) => {
  const v = parseFloat(value) || 0
  if (v === 0) return 0
  if (unit === 'minutes') return Math.round(v * 60)
  if (unit === 'days') return Math.round(v * 86400)
  return Math.round(v * 3600)
}

function ToggleSwitch({ checked, onChange }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      onClick={() => onChange(!checked)}
      className={`relative inline-flex items-center h-5 rounded-full transition-colors duration-200 ${
        checked ? 'bg-[#2272B4]' : 'bg-[#D8D8D8]'
      }`}
      style={{ width: '40px' }}
    >
      <span
        className={`inline-block w-4 h-4 rounded-full bg-white shadow transform transition-transform duration-200 ${
          checked ? 'translate-x-[21px]' : 'translate-x-[1px]'
        }`}
      />
    </button>
  )
}

function SettingsField({ label, description, children, inline }) {
  if (inline) {
    return (
      <div className="flex items-center justify-between">
        <div>
          <label className="block text-[13px] font-medium text-[#161616]">{label}</label>
          {description && <p className="text-[12px] text-[#6F6F6F]">{description}</p>}
        </div>
        {children}
      </div>
    )
  }
  return (
    <div>
      <label className="block text-[13px] font-medium text-[#161616] mb-1">{label}</label>
      {description && <p className="text-[12px] text-[#6F6F6F] mb-2">{description}</p>}
      {children}
    </div>
  )
}

function EndpointSelect({ value, onChange, endpoints, loading, placeholder, filterTask }) {
  const filtered = filterTask ? endpoints.filter(ep => ep.task === filterTask) : endpoints
  if (loading) {
    return (
      <div className="h-8 flex items-center gap-2 text-[13px] text-[#6F6F6F]">
        <Loader2 size={14} className="animate-spin" /> Loading endpoints...
      </div>
    )
  }
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="h-8 w-full border border-[#CBCBCB] rounded px-3 text-[13px] text-[#161616] outline-none focus:border-[#2272B4] transition-colors bg-white"
    >
      <option value="">{placeholder || 'Select endpoint...'}</option>
      {filtered.map(ep => (
        <option key={ep.name} value={ep.name}>{ep.name}</option>
      ))}
    </select>
  )
}

export default function SettingsPage() {
  const [config, setConfig] = useState({
    storage_backend: 'lakebase',
    lakebase_service_token: '',
    lakebase_instance_name: '',
    lakebase_catalog: 'default',
    lakebase_schema: 'public',
    cache_table_name: 'cached_queries',
    query_log_table_name: 'query_logs',
    similarity_threshold: '0.92',
    cache_ttl_value: '24',
    cache_ttl_unit: 'hours',
    max_queries_per_minute: '5',
    question_normalization_enabled: true,
    normalization_model: '',
    cache_validation_enabled: true,
    validation_model: '',
    embedding_provider: 'databricks',
    databricks_embedding_endpoint: 'databricks-gte-large-en',
    shared_cache: true,
  })
  const [showLakebaseToken, setShowLakebaseToken] = useState(false)
  const [tokenSource, setTokenSource] = useState('none')
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [loading, setLoading] = useState(true)
  const [testingConn, setTestingConn] = useState(false)
  const [connResult, setConnResult] = useState(null)

  // Serving endpoints
  const [endpoints, setEndpoints] = useState([])
  const [endpointsLoading, setEndpointsLoading] = useState(true)

  useEffect(() => {
    // Load settings
    const load = async () => {
      try {
        let server
        try { server = await api.getSettings() } catch { server = await api.getServerConfig() }
        const ttl = secondsToTtl(server.cache_ttl_seconds)
        setTokenSource(server.lakebase_token_source || 'none')
        setConfig({
          storage_backend: 'lakebase',
          lakebase_service_token: server.lakebase_token_source === 'override' ? '\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022' : '',
          lakebase_instance_name: server.lakebase_instance_name || '',
          lakebase_catalog: server.lakebase_catalog || 'default',
          lakebase_schema: server.lakebase_schema || 'public',
          cache_table_name: server.cache_table_name || 'cached_queries',
          query_log_table_name: server.query_log_table_name || 'query_logs',
          similarity_threshold: String(server.similarity_threshold ?? 0.92),
          cache_ttl_value: ttl.value,
          cache_ttl_unit: ttl.unit,
          max_queries_per_minute: String(server.max_queries_per_minute ?? 5),
          question_normalization_enabled: server.question_normalization_enabled !== false,
          normalization_model: server.normalization_model || '',
          cache_validation_enabled: server.cache_validation_enabled !== false,
          validation_model: server.validation_model || '',
          embedding_provider: server.embedding_provider || 'databricks',
          databricks_embedding_endpoint: server.databricks_embedding_endpoint || 'databricks-gte-large-en',
          shared_cache: server.shared_cache !== false,
        })
      } catch { /* keep defaults */ }
      finally { setLoading(false) }
    }
    load()

    // Load serving endpoints
    api.listServingEndpoints()
      .then((data) => {
        setEndpoints(data.endpoints || [])
      })
      .catch(() => setEndpoints([]))
      .finally(() => setEndpointsLoading(false))
  }, [])

  const handleChange = (field, value) => {
    setConfig(prev => ({ ...prev, [field]: value }))
    setSaved(false)
  }

  const handleSave = async () => {
    setSaving(true)
    try {
      const payload = {
        storage_backend: 'pgvector',
        similarity_threshold: parseFloat(config.similarity_threshold) || 0.92,
        max_queries_per_minute: parseInt(config.max_queries_per_minute) || 5,
        cache_ttl_seconds: ttlToSeconds(config.cache_ttl_value, config.cache_ttl_unit),
        question_normalization_enabled: config.question_normalization_enabled,
        normalization_model: config.normalization_model || undefined,
        cache_validation_enabled: config.cache_validation_enabled,
        validation_model: config.validation_model || undefined,
        embedding_provider: config.embedding_provider,
        databricks_embedding_endpoint: config.databricks_embedding_endpoint,
        shared_cache: config.shared_cache,
      }
      if (true) { // Always Lakebase
        if (config.lakebase_service_token && config.lakebase_service_token !== '\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022') {
          payload.lakebase_service_token = config.lakebase_service_token
        }
        payload.lakebase_instance_name = config.lakebase_instance_name
        payload.lakebase_catalog = config.lakebase_catalog
        payload.lakebase_schema = config.lakebase_schema
        payload.cache_table_name = config.cache_table_name
        payload.query_log_table_name = config.query_log_table_name
      }

      try { await api.updateSettings(payload) } catch { await api.updateServerConfig(payload) }

      const local = JSON.parse(localStorage.getItem('databricks_config') || '{}')
      localStorage.setItem('databricks_config', JSON.stringify({
        ...local,
        storage_backend: config.storage_backend,
        similarity_threshold: config.similarity_threshold,
        max_queries_per_minute: config.max_queries_per_minute,
        shared_cache: config.shared_cache,
        embedding_provider: config.embedding_provider,
        databricks_embedding_endpoint: config.databricks_embedding_endpoint,
        question_normalization_enabled: config.question_normalization_enabled,
        cache_validation_enabled: config.cache_validation_enabled,
        lakebase_instance_name: config.lakebase_instance_name,
        lakebase_catalog: config.lakebase_catalog,
        lakebase_schema: config.lakebase_schema,
        cache_table_name: config.cache_table_name,
        query_log_table_name: config.query_log_table_name,
      }))

      setSaved(true)
      setTimeout(() => setSaved(false), 3000)
    } catch (err) {
      alert('Failed to save settings: ' + (err.response?.data?.detail || err.message))
    } finally {
      setSaving(false)
    }
  }

  const inputClass = 'h-8 w-full border border-[#CBCBCB] rounded px-3 text-[13px] text-[#161616] outline-none focus:border-[#2272B4] transition-colors'

  if (loading) {
    return (
      <div className="p-6 flex justify-center">
        <div className="w-full max-w-2xl">
          <h1 className="text-[22px] font-medium text-[#161616] mb-6">Settings</h1>
          <div className="text-[13px] text-[#6F6F6F]">Loading...</div>
        </div>
      </div>
    )
  }

  return (
    <div className="p-6 flex justify-center">
      <div className="w-full max-w-2xl">
        <h1 className="text-[22px] font-medium text-[#161616] mb-6">Settings</h1>

        {/* Section 1: Workspace Configuration */}
        <div className="bg-white border border-[#EBEBEB] rounded p-6 mb-6">
          <h2 className="text-[16px] font-medium text-[#161616] mb-1">Workspace Configuration</h2>
          <p className="text-[12px] text-[#6F6F6F] mb-5">Authentication and storage backend settings</p>

          <div className="space-y-5">
            <SettingsField label="Storage Backend" description="Cached queries are persisted in Lakebase (PostgreSQL with pgvector)" inline>
              <span className="inline-flex items-center gap-1.5 px-3 py-1 text-[12px] font-medium bg-[rgba(34,114,180,0.08)] text-[#0E538B] rounded">
                Lakebase
              </span>
            </SettingsField>

            {config.storage_backend === 'lakebase' && (
              <div className="border-t border-[#EBEBEB] pt-5 space-y-4">
                <SettingsField
                  label="Lakebase Service Token"
                  description={
                    tokenSource === 'auto'
                      ? 'Using auto-injected DATABRICKS_TOKEN (Databricks Apps). Set a custom token to override.'
                      : tokenSource === 'override'
                      ? 'Custom token active (in-memory override).'
                      : 'PAT or service principal token for Lakebase operations.'
                  }
                >
                  <div className="space-y-1.5">
                    {tokenSource === 'auto' && (
                      <div className="flex items-center gap-1.5 text-[12px] text-[#2272B4]">
                        <span className="inline-block w-2 h-2 rounded-full bg-[#2272B4]" />
                        Active — auto-injected DATABRICKS_TOKEN
                      </div>
                    )}
                    {tokenSource === 'override' && (
                      <div className="flex items-center gap-1.5 text-[12px] text-[#24A148]">
                        <span className="inline-block w-2 h-2 rounded-full bg-[#24A148]" />
                        Active — custom token override
                      </div>
                    )}
                    <div className="relative">
                      <input type={showLakebaseToken ? 'text' : 'password'} value={config.lakebase_service_token}
                        onChange={(e) => handleChange('lakebase_service_token', e.target.value)}
                        placeholder={tokenSource === 'auto' ? 'Leave empty to use auto-injected token' : 'dapi... or client_id:client_secret'}
                        className={inputClass + ' pr-9'} />
                      <button type="button" onClick={() => setShowLakebaseToken(!showLakebaseToken)}
                        className="absolute right-2 top-1/2 -translate-y-1/2 text-[#6F6F6F] hover:text-[#161616]">
                        {showLakebaseToken ? <EyeOff size={14} /> : <Eye size={14} />}
                      </button>
                    </div>
                  </div>
                </SettingsField>
                <SettingsField label="Lakebase Instance Name" description="Autoscaling project name, provisioned instance, or direct hostname">
                  <input type="text" value={config.lakebase_instance_name}
                    onChange={(e) => handleChange('lakebase_instance_name', e.target.value)}
                    placeholder="genie-cache" className={inputClass} />
                </SettingsField>
                <div className="grid grid-cols-2 gap-4">
                  <SettingsField label="Catalog" description="Lakebase catalog name">
                    <input type="text" value={config.lakebase_catalog}
                      onChange={(e) => handleChange('lakebase_catalog', e.target.value)} placeholder="default" className={inputClass} />
                  </SettingsField>
                  <SettingsField label="Schema" description="Lakebase schema name">
                    <input type="text" value={config.lakebase_schema}
                      onChange={(e) => handleChange('lakebase_schema', e.target.value)} placeholder="public" className={inputClass} />
                  </SettingsField>
                </div>
                <div className="grid grid-cols-2 gap-4">
                  <SettingsField label="Cache Table Name" description="Table for cached queries">
                    <input type="text" value={config.cache_table_name}
                      onChange={(e) => handleChange('cache_table_name', e.target.value)} placeholder="cached_queries" className={inputClass} />
                  </SettingsField>
                  <SettingsField label="Query Log Table Name" description="Table for query history">
                    <input type="text" value={config.query_log_table_name}
                      onChange={(e) => handleChange('query_log_table_name', e.target.value)} placeholder="query_logs" className={inputClass} />
                  </SettingsField>
                </div>

                {/* Test Connection — inside Lakebase section */}
                <div className="pt-2 space-y-2">
                  <button
                    onClick={async () => {
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
                    }}
                    disabled={testingConn}
                    className="inline-flex items-center gap-1.5 h-8 px-4 text-[13px] font-medium text-[#161616] border border-[#CBCBCB] rounded hover:bg-[#F7F7F7] transition-colors disabled:opacity-50"
                  >
                    {testingConn ? <Loader2 size={14} className="animate-spin" /> : <FlaskConical size={14} />}
                    {testingConn ? 'Testing...' : 'Test Connection'}
                  </button>

                  {connResult && (
                    <div className={`rounded p-3 text-[13px] border ${connResult.connected ? 'bg-[#F3FCF6] border-green-200' : 'bg-red-50 border-red-200'}`}>
                      {connResult.connected ? (
                        <div className="space-y-1.5">
                          <div className="flex items-center gap-1.5 font-medium text-green-700">
                            <CheckCircle size={14} /> Connected to Lakebase
                          </div>
                          <div className="flex gap-4">
                            {[
                              ['cache_table_exists', 'Cache table'],
                              ['query_log_table_exists', 'Query log table'],
                              ['gateway_table_exists', 'Gateway table'],
                            ].map(([key, label]) => (
                              <div key={key} className="flex items-center gap-1 text-[12px]">
                                {connResult[key]
                                  ? <CheckCircle size={12} className="text-green-600" />
                                  : <XCircle size={12} className="text-amber-500" />}
                                <span className={connResult[key] ? 'text-green-700' : 'text-amber-600'}>
                                  {label} {connResult[key] ? '✓' : '(will be created)'}
                                </span>
                              </div>
                            ))}
                          </div>
                        </div>
                      ) : (
                        <div className="flex items-center gap-1.5 text-red-700">
                          <XCircle size={14} /> {connResult.error || 'Connection failed'}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Section 2: Default Gateway Settings */}
        <div className="bg-white border border-[#EBEBEB] rounded p-6 mb-6">
          <h2 className="text-[16px] font-medium text-[#161616] mb-1">Default Gateway Settings</h2>
          <p className="text-[12px] text-[#6F6F6F] mb-5">These defaults are used when creating new gateways. Each gateway can override these individually.</p>

          <div className="space-y-5">
            <div className="grid grid-cols-2 gap-4">
              <SettingsField label="Similarity Threshold" description="Minimum cosine similarity for cache hit (0-1)">
                <input type="number" min="0" max="1" step="0.01" value={config.similarity_threshold}
                  onChange={(e) => handleChange('similarity_threshold', e.target.value)} className={inputClass} />
              </SettingsField>
              <SettingsField label="Cache TTL" description="How long cached entries remain valid">
                <div className="flex gap-2">
                  <input type="number" min="0" value={config.cache_ttl_value}
                    onChange={(e) => handleChange('cache_ttl_value', e.target.value)}
                    className="h-8 flex-1 min-w-0 border border-[#CBCBCB] rounded px-3 text-[13px] text-[#161616] outline-none focus:border-[#2272B4] transition-colors" />
                  <select value={config.cache_ttl_unit} onChange={(e) => handleChange('cache_ttl_unit', e.target.value)}
                    className="h-8 border border-[#CBCBCB] rounded px-2 text-[13px] text-[#161616] outline-none focus:border-[#2272B4] transition-colors bg-white">
                    <option value="minutes">Minutes</option>
                    <option value="hours">Hours</option>
                    <option value="days">Days</option>
                  </select>
                </div>
              </SettingsField>
            </div>

            <SettingsField label="Max Queries per Minute" description="Rate limit for Genie API calls per user">
              <input type="number" min="1" max="100" value={config.max_queries_per_minute}
                onChange={(e) => handleChange('max_queries_per_minute', e.target.value)}
                className={inputClass} style={{ maxWidth: '160px' }} />
            </SettingsField>

            {/* Question Normalization + model */}
            <div className="space-y-2">
              <SettingsField label="Question Normalization" description="LLM rewrites questions to improve cache hit rates" inline>
                <ToggleSwitch checked={config.question_normalization_enabled}
                  onChange={(v) => handleChange('question_normalization_enabled', v)} />
              </SettingsField>
              {config.question_normalization_enabled && (
                <SettingsField label="Normalization Model" description="LLM endpoint used for question normalization">
                  <EndpointSelect value={config.normalization_model} onChange={(v) => handleChange('normalization_model', v)}
                    endpoints={endpoints} loading={endpointsLoading} filterTask="llm/v1/chat"
                    placeholder="Default (workspace default)" />
                </SettingsField>
              )}
            </div>

            {/* Cache Validation + model */}
            <div className="space-y-2">
              <SettingsField label="Cache Validation" description="LLM validates that cached results are relevant to the query before returning" inline>
                <ToggleSwitch checked={config.cache_validation_enabled}
                  onChange={(v) => handleChange('cache_validation_enabled', v)} />
              </SettingsField>
              {config.cache_validation_enabled && (
                <SettingsField label="Validation Model" description="LLM endpoint used for cache validation">
                  <EndpointSelect value={config.validation_model} onChange={(v) => handleChange('validation_model', v)}
                    endpoints={endpoints} loading={endpointsLoading} filterTask="llm/v1/chat"
                    placeholder="Default (workspace default)" />
                </SettingsField>
              )}
            </div>

            {/* Embedding — dropdown */}
            <div className="grid grid-cols-2 gap-4">
              <SettingsField label="Embedding Provider" description="Provider for query embeddings">
                <select value={config.embedding_provider} onChange={(e) => handleChange('embedding_provider', e.target.value)}
                  className="h-8 w-full border border-[#CBCBCB] rounded px-3 text-[13px] text-[#161616] outline-none focus:border-[#2272B4] transition-colors bg-white">
                  <option value="databricks">Databricks</option>
                  <option value="local">Local</option>
                </select>
              </SettingsField>
              {config.embedding_provider === 'databricks' && (
                <SettingsField label="Embedding Endpoint" description="Databricks serving endpoint for embeddings">
                  <EndpointSelect value={config.databricks_embedding_endpoint}
                    onChange={(v) => handleChange('databricks_embedding_endpoint', v)}
                    endpoints={endpoints} loading={endpointsLoading} filterTask="llm/v1/embeddings"
                    placeholder="Select embedding endpoint..." />
                </SettingsField>
              )}
            </div>

            <SettingsField label="Shared Cache" description="Global cache shared by all users, or per-user isolation" inline>
              <ToggleSwitch checked={config.shared_cache} onChange={(v) => handleChange('shared_cache', v)} />
            </SettingsField>
          </div>
        </div>

        {/* Save button */}
        <div className="flex items-center gap-3">
          <button onClick={handleSave} disabled={saving}
            className="inline-flex items-center gap-1.5 h-8 px-5 text-[13px] font-medium text-white bg-[#2272B4] rounded hover:bg-[#1b5e96] transition-colors disabled:opacity-50">
            <Save size={14} />
            {saving ? 'Saving...' : 'Save Settings'}
          </button>
          {saved && <span className="text-[13px] text-[#FF3621] font-medium">Settings saved</span>}
        </div>
      </div>
    </div>
  )
}
