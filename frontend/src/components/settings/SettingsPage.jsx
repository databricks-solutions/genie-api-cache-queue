import { useState, useEffect, useRef, useCallback } from 'react'
import { Pencil, Eye, EyeOff, Loader2, CheckCircle, XCircle, FlaskConical, Database, SlidersHorizontal } from 'lucide-react'
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

const systemFont = '-apple-system, "system-ui", "Segoe UI", Roboto, "Helvetica Neue", Arial, "Noto Sans", sans-serif'
const systemStyle = { fontFamily: systemFont, WebkitFontSmoothing: 'auto', MozOsxFontSmoothing: 'auto' }

/* ── Toggle (Pattern D) ── */
function ToggleSwitch({ checked, onChange }) {
  return (
    <div className="flex items-center gap-1.5">
      <span className="text-[13px] font-semibold text-[#161616]">{checked ? 'On' : 'Off'}</span>
      <button type="button" role="switch" aria-checked={checked} onClick={() => onChange(!checked)}
        className={`relative inline-flex items-center rounded-full transition-colors duration-200 ${checked ? 'bg-[#2272B4]' : 'bg-[#D8D8D8]'}`}
        style={{ width: '28px', height: '16px' }}>
        <span className={`inline-block rounded-full bg-white shadow transform transition-transform duration-200 ${checked ? 'translate-x-[13px]' : 'translate-x-[1px]'}`}
          style={{ width: '12px', height: '12px' }} />
      </button>
    </div>
  )
}

/* ── Pencil-edit field (Pattern A) ── */
function EditableText({ value, onChange, placeholder, masked }) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(value)
  const inputRef = useRef(null)

  const startEdit = () => { setDraft(value); setEditing(true); setTimeout(() => inputRef.current?.focus(), 0) }
  const cancel = () => setEditing(false)
  const save = () => { onChange(draft); setEditing(false) }
  const handleKey = (e) => { if (e.key === 'Enter') save(); if (e.key === 'Escape') cancel() }

  const displayValue = masked && value ? '\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022' : (value || placeholder)
  const isEmpty = !value

  if (editing) {
    return (
      <div className="flex items-center gap-2">
        <input ref={inputRef} type={masked ? 'password' : 'text'} value={draft}
          onChange={(e) => setDraft(e.target.value)} onKeyDown={handleKey}
          placeholder={placeholder}
          className="h-8 border border-[#2272B4] rounded px-3 text-[13px] text-[#161616] outline-none"
          style={{ width: '220px' }} />
        <button onClick={save}
          className="h-8 px-3 text-[13px] text-white bg-[#2272B4] rounded hover:bg-[#1b5e96] transition-colors">Save</button>
        <button onClick={cancel}
          className="h-8 px-3 text-[13px] text-[#161616] border border-[#CBCBCB] rounded hover:bg-[#F7F7F7] transition-colors">Cancel</button>
      </div>
    )
  }

  return (
    <div className="flex items-center gap-2">
      <span className={`text-[13px] ${isEmpty ? 'text-[#6F6F6F] italic' : 'text-[#161616]'}`}>
        {displayValue}
      </span>
      <button onClick={startEdit} className="text-[#6F6F6F] hover:text-[#161616] transition-colors p-1">
        <Pencil size={14} />
      </button>
    </div>
  )
}

/* ── Field row container ── */
function FieldRow({ label, description, children, noBorder }) {
  return (
    <div className={`py-6 ${noBorder ? '' : 'border-b border-[#EBEBEB]'}`}>
      <div className="flex items-center justify-between gap-6">
        <div className="flex-1">
          <span className="text-[13px] font-semibold text-[#161616] leading-[20px]">{label}</span>
          {description && <div className="text-[12px] text-[#6F6F6F] leading-[16px]">{description}</div>}
        </div>
        <div className="shrink-0">{children}</div>
      </div>
    </div>
  )
}

/* ── Field row for stacked content (token, test connection) ── */
function FieldRowStacked({ label, description, children, noBorder }) {
  return (
    <div className={`py-6 ${noBorder ? '' : 'border-b border-[#EBEBEB]'}`}>
      <span className="text-[13px] font-semibold text-[#161616] leading-[20px]">{label}</span>
      {description && <div className="text-[12px] text-[#6F6F6F] leading-[16px]">{description}</div>}
      <div className="mt-2">{children}</div>
    </div>
  )
}

/* ── Endpoint select (Pattern C) ── */
function EndpointSelect({ value, onChange, endpoints, loading, placeholder, filterTask }) {
  const filtered = filterTask ? endpoints.filter(ep => ep.task === filterTask) : endpoints
  if (loading) {
    return (
      <div className="h-8 flex items-center gap-2 text-[13px] text-[#6F6F6F]">
        <Loader2 size={14} className="animate-spin" /> Loading...
      </div>
    )
  }
  return (
    <select value={value} onChange={(e) => onChange(e.target.value)}
      className="h-8 border border-[#CBCBCB] rounded px-3 text-[13px] text-[#161616] outline-none focus:border-[#2272B4] transition-colors bg-white"
      style={{ width: '220px' }}>
      <option value="">{placeholder || 'Select endpoint...'}</option>
      {filtered.map(ep => <option key={ep.name} value={ep.name}>{ep.name}</option>)}
    </select>
  )
}

/* ── Sidebar structure ── */
const SIDEBAR = [
  { category: 'Connection', icon: Database, items: [{ id: 'general', label: 'General' }] },
  { category: 'Gateway Defaults', icon: SlidersHorizontal, items: [
    { id: 'cache', label: 'Cache' },
    { id: 'rate-limiting', label: 'Rate Limiting' },
    { id: 'ai-pipeline', label: 'AI Pipeline' },
  ]},
]

const SECTION_TITLES = { general: 'General', cache: 'Cache', 'rate-limiting': 'Rate Limiting', 'ai-pipeline': 'AI Pipeline' }

/* ── Main component ── */
export default function SettingsPage() {
  const [activeSection, setActiveSection] = useState('general')
  const [config, setConfig] = useState({
    storage_backend: 'lakebase', lakebase_service_token: '', lakebase_instance_name: '',
    lakebase_catalog: 'default', lakebase_schema: 'public',
    cache_table_name: 'cached_queries', query_log_table_name: 'query_logs',
    similarity_threshold: '0.92', cache_ttl_value: '24', cache_ttl_unit: 'hours',
    max_queries_per_minute: '5', question_normalization_enabled: true, normalization_model: '',
    cache_validation_enabled: true, validation_model: '',
    embedding_provider: 'databricks', databricks_embedding_endpoint: 'databricks-gte-large-en',
    shared_cache: true,
  })
  const [tokenSource, setTokenSource] = useState('none')
  const [loading, setLoading] = useState(true)
  const [testingConn, setTestingConn] = useState(false)
  const [connResult, setConnResult] = useState(null)
  const [saveStatus, setSaveStatus] = useState(null)
  const [endpoints, setEndpoints] = useState([])
  const [endpointsLoading, setEndpointsLoading] = useState(true)

  const sectionRefs = useRef({})
  const saveTimerRef = useRef(null)
  const configRef = useRef(config)
  configRef.current = config

  useEffect(() => {
    (async () => {
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
          cache_ttl_value: ttl.value, cache_ttl_unit: ttl.unit,
          max_queries_per_minute: String(server.max_queries_per_minute ?? 5),
          question_normalization_enabled: server.question_normalization_enabled !== false,
          normalization_model: server.normalization_model || '',
          cache_validation_enabled: server.cache_validation_enabled !== false,
          validation_model: server.validation_model || '',
          embedding_provider: server.embedding_provider || 'databricks',
          databricks_embedding_endpoint: server.databricks_embedding_endpoint || 'databricks-gte-large-en',
          shared_cache: server.shared_cache !== false,
        })
      } catch { /* defaults */ }
      finally { setLoading(false) }
    })()
    api.listServingEndpoints()
      .then((data) => setEndpoints(data.endpoints || []))
      .catch(() => setEndpoints([]))
      .finally(() => setEndpointsLoading(false))
  }, [])

  const persistSettings = useCallback(async () => {
    const c = configRef.current
    setSaveStatus('saving')
    try {
      const payload = {
        storage_backend: 'pgvector',
        similarity_threshold: parseFloat(c.similarity_threshold) || 0.92,
        max_queries_per_minute: parseInt(c.max_queries_per_minute) || 5,
        cache_ttl_seconds: ttlToSeconds(c.cache_ttl_value, c.cache_ttl_unit),
        question_normalization_enabled: c.question_normalization_enabled,
        normalization_model: c.normalization_model || undefined,
        cache_validation_enabled: c.cache_validation_enabled,
        validation_model: c.validation_model || undefined,
        embedding_provider: c.embedding_provider,
        databricks_embedding_endpoint: c.databricks_embedding_endpoint,
        shared_cache: c.shared_cache,
        lakebase_instance_name: c.lakebase_instance_name,
        lakebase_catalog: c.lakebase_catalog,
        lakebase_schema: c.lakebase_schema,
        cache_table_name: c.cache_table_name,
        query_log_table_name: c.query_log_table_name,
      }
      if (c.lakebase_service_token && !c.lakebase_service_token.startsWith('\u2022')) {
        payload.lakebase_service_token = c.lakebase_service_token
      }
      try { await api.updateSettings(payload) } catch { await api.updateServerConfig(payload) }
      const local = JSON.parse(localStorage.getItem('databricks_config') || '{}')
      localStorage.setItem('databricks_config', JSON.stringify({ ...local,
        storage_backend: c.storage_backend, similarity_threshold: c.similarity_threshold,
        max_queries_per_minute: c.max_queries_per_minute, shared_cache: c.shared_cache,
        embedding_provider: c.embedding_provider, databricks_embedding_endpoint: c.databricks_embedding_endpoint,
        question_normalization_enabled: c.question_normalization_enabled, cache_validation_enabled: c.cache_validation_enabled,
        lakebase_instance_name: c.lakebase_instance_name, lakebase_catalog: c.lakebase_catalog,
        lakebase_schema: c.lakebase_schema, cache_table_name: c.cache_table_name, query_log_table_name: c.query_log_table_name,
      }))
      setSaveStatus('saved')
      setTimeout(() => setSaveStatus(null), 2000)
    } catch {
      setSaveStatus('error')
      setTimeout(() => setSaveStatus(null), 3000)
    }
  }, [])

  const handleChange = useCallback((field, value) => {
    setConfig(prev => ({ ...prev, [field]: value }))
    if (saveTimerRef.current) clearTimeout(saveTimerRef.current)
    saveTimerRef.current = setTimeout(() => persistSettings(), 800)
  }, [persistSettings])

  const handleImmediateSave = useCallback((field, value) => {
    setConfig(prev => ({ ...prev, [field]: value }))
    setTimeout(() => persistSettings(), 50)
  }, [persistSettings])

  const scrollToSection = (id) => {
    setActiveSection(id)
    sectionRefs.current[id]?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  const inputClass = 'h-8 border border-[#CBCBCB] rounded px-3 text-[13px] text-[#161616] outline-none focus:border-[#2272B4] transition-colors'

  if (loading) {
    return (
      <div className="flex h-full" style={systemStyle}>
        <div style={{ width: '240px' }} className="shrink-0 border-r border-[#EBEBEB]" />
        <div className="flex-1 p-6"><div className="text-[13px] text-[#6F6F6F]">Loading...</div></div>
      </div>
    )
  }

  return (
    <div className="flex h-full" style={systemStyle}>
      {/* ── Sidebar ── */}
      <div style={{ width: '240px' }} className="shrink-0 border-r border-[#EBEBEB]">
        <div className="px-6 pt-6 pb-6">
          <h2 className="text-[22px] font-semibold text-[#161616] leading-[28px]">Settings</h2>
        </div>
        <nav className="px-4">
          {SIDEBAR.map(({ category, icon: Icon, items }, idx) => (
            <div key={category} className={idx > 0 ? 'mt-6' : ''}>
              {category && (
                <div className="flex items-center gap-2 px-2 mb-1 text-[13px] text-[#6F6F6F]">
                  <Icon size={20} strokeWidth={1.5} />
                  <span>{category}</span>
                </div>
              )}
              <div className={category ? 'ml-3' : ''}>
                {items.map(({ id, label }) => (
                  <button key={id} onClick={() => scrollToSection(id)}
                    className={`w-full text-left rounded text-[13px] leading-[20px] transition-colors py-2 px-3 ${
                      activeSection === id
                        ? 'bg-[#F7F7F7] text-[#11171C]'
                        : 'text-[#11171C] hover:bg-[#F7F7F7]'
                    }`}>
                    {label}
                  </button>
                ))}
              </div>
            </div>
          ))}
        </nav>
      </div>

      {/* ── Content ── */}
      <div className="flex-1 overflow-y-auto p-6 flex justify-center">
        <div className="w-full max-w-[640px]">

          {/* Auto-save toast */}
          {saveStatus && (
            <div className="fixed top-3 right-4 z-50">
              <div className={`flex items-center gap-1.5 px-3 py-1.5 rounded text-[12px] shadow-sm ${
                saveStatus === 'saving' ? 'bg-white text-[#6F6F6F] border border-[#EBEBEB]' :
                saveStatus === 'saved' ? 'bg-[#F3FCF6] text-green-700 border border-green-200' :
                'bg-red-50 text-red-700 border border-red-200'
              }`}>
                {saveStatus === 'saving' && <Loader2 size={12} className="animate-spin" />}
                {saveStatus === 'saving' ? 'Saving...' : saveStatus === 'saved' ? 'Saved' : 'Save failed'}
              </div>
            </div>
          )}

          {/* ── General ── */}
          <div ref={el => sectionRefs.current['general'] = el} className="mb-10">
            <h2 className="text-[22px] font-semibold text-[#161616] leading-[28px] pb-3 border-b border-[#EBEBEB]">General</h2>

            <FieldRow label="Storage Backend" description="Cached queries are persisted in Lakebase (PostgreSQL with pgvector)">
              <span className="inline-flex items-center px-3 py-1 text-[12px] font-medium bg-[rgba(34,114,180,0.08)] text-[#0E538B] rounded">Lakebase</span>
            </FieldRow>

            <FieldRow label="Lakebase Instance Name" description="Autoscaling project name, provisioned instance, or direct hostname">
              <EditableText value={config.lakebase_instance_name} onChange={(v) => handleImmediateSave('lakebase_instance_name', v)} placeholder="genie-cache" />
            </FieldRow>

            <FieldRow label="Catalog" description="Lakebase catalog name">
              <EditableText value={config.lakebase_catalog} onChange={(v) => handleImmediateSave('lakebase_catalog', v)} placeholder="default" />
            </FieldRow>

            <FieldRow label="Schema" description="Lakebase schema name">
              <EditableText value={config.lakebase_schema} onChange={(v) => handleImmediateSave('lakebase_schema', v)} placeholder="public" />
            </FieldRow>

            <FieldRow label="Cache Table Name" description="Table for cached queries">
              <EditableText value={config.cache_table_name} onChange={(v) => handleImmediateSave('cache_table_name', v)} placeholder="cached_queries" />
            </FieldRow>

            <FieldRow label="Query Log Table Name" description="Table for query history">
              <EditableText value={config.query_log_table_name} onChange={(v) => handleImmediateSave('query_log_table_name', v)} placeholder="query_logs" />
            </FieldRow>

            <FieldRow label="Lakebase Service Token" description={
              tokenSource === 'auto' ? 'Using auto-injected DATABRICKS_TOKEN. Set a custom token to override.'
                : tokenSource === 'override' ? 'Custom token active (in-memory override).'
                : 'Service principal token for Lakebase operations.'
            }>
              <EditableText value={config.lakebase_service_token} onChange={(v) => handleImmediateSave('lakebase_service_token', v)}
                placeholder="client_id:client_secret" masked />
            </FieldRow>

            <FieldRowStacked label="Test Connection" description="Verify connectivity to Lakebase" noBorder>
              <div className="space-y-2">
                <button onClick={async () => {
                    setTestingConn(true); setConnResult(null)
                    try { setConnResult(await api.testLakebaseConnection()) }
                    catch (err) { setConnResult({ connected: false, error: err.response?.data?.detail || err.message }) }
                    finally { setTestingConn(false) }
                  }} disabled={testingConn}
                  className="inline-flex items-center gap-1.5 h-8 px-3 text-[13px] text-[#161616] border border-[#CBCBCB] rounded hover:bg-[#F7F7F7] transition-colors disabled:opacity-50">
                  {testingConn ? <Loader2 size={14} className="animate-spin" /> : <FlaskConical size={14} />}
                  {testingConn ? 'Testing...' : 'Test Connection'}
                </button>
                {connResult && (
                  <div className={`rounded p-3 text-[13px] border ${connResult.connected ? 'bg-[#F3FCF6] border-green-200' : 'bg-red-50 border-red-200'}`}>
                    {connResult.connected ? (
                      <div className="space-y-1.5">
                        <div className="flex items-center gap-1.5 font-medium text-green-700"><CheckCircle size={14} /> Connected to Lakebase</div>
                        <div className="flex gap-4">
                          {[['cache_table_exists','Cache table'],['query_log_table_exists','Query log table'],['gateway_table_exists','Gateway table']].map(([key,label]) => (
                            <div key={key} className="flex items-center gap-1 text-[12px]">
                              {connResult[key] ? <CheckCircle size={12} className="text-green-600" /> : <XCircle size={12} className="text-amber-500" />}
                              <span className={connResult[key] ? 'text-green-700' : 'text-amber-600'}>{label} {connResult[key] ? '\u2713' : '(will be created)'}</span>
                            </div>
                          ))}
                        </div>
                      </div>
                    ) : (
                      <div className="flex items-center gap-1.5 text-red-700"><XCircle size={14} /> {connResult.error || 'Connection failed'}</div>
                    )}
                  </div>
                )}
              </div>
            </FieldRowStacked>
          </div>

          {/* ── Cache ── */}
          <div ref={el => sectionRefs.current['cache'] = el} className="mb-10">
            <h3 className="text-[18px] font-semibold text-[#161616] leading-[24px] mb-2">Cache</h3>

            <FieldRow label="Similarity Threshold" description="Minimum cosine similarity for cache hit (0-1)">
              <input type="number" min="0" max="1" step="0.01" value={config.similarity_threshold}
                onChange={(e) => handleChange('similarity_threshold', e.target.value)}
                className={inputClass} style={{ width: '80px' }} />
            </FieldRow>

            <FieldRow label="Cache TTL" description="How long cached entries remain valid">
              <div className="flex gap-2">
                <input type="number" min="0" value={config.cache_ttl_value}
                  onChange={(e) => handleChange('cache_ttl_value', e.target.value)}
                  className={inputClass} style={{ width: '80px' }} />
                <select value={config.cache_ttl_unit} onChange={(e) => handleChange('cache_ttl_unit', e.target.value)}
                  className={`${inputClass} bg-white`}>
                  <option value="minutes">Minutes</option>
                  <option value="hours">Hours</option>
                  <option value="days">Days</option>
                </select>
              </div>
            </FieldRow>

            <FieldRow label="Shared Cache" description="Global cache shared by all users, or per-user isolation" noBorder>
              <ToggleSwitch checked={config.shared_cache} onChange={(v) => handleChange('shared_cache', v)} />
            </FieldRow>
          </div>

          {/* ── Rate Limiting ── */}
          <div ref={el => sectionRefs.current['rate-limiting'] = el} className="mb-10">
            <h3 className="text-[18px] font-semibold text-[#161616] leading-[24px] mb-2">Rate Limiting</h3>

            <FieldRow label="Max Queries per Minute" description="Rate limit for Genie API calls per user" noBorder>
              <input type="number" min="1" max="100" value={config.max_queries_per_minute}
                onChange={(e) => handleChange('max_queries_per_minute', e.target.value)}
                className={inputClass} style={{ width: '80px' }} />
            </FieldRow>
          </div>

          {/* ── AI Pipeline ── */}
          <div ref={el => sectionRefs.current['ai-pipeline'] = el} className="mb-10">
            <h3 className="text-[18px] font-semibold text-[#161616] leading-[24px] mb-2">AI Pipeline</h3>

            <FieldRow label="Question Normalization" description="LLM rewrites questions to improve cache hit rates">
              <ToggleSwitch checked={config.question_normalization_enabled}
                onChange={(v) => handleChange('question_normalization_enabled', v)} />
            </FieldRow>

            {config.question_normalization_enabled && (
              <FieldRow label="Normalization Model" description="LLM endpoint used for question normalization">
                <EndpointSelect value={config.normalization_model} onChange={(v) => handleChange('normalization_model', v)}
                  endpoints={endpoints} loading={endpointsLoading} filterTask="llm/v1/chat" placeholder="Default (workspace default)" />
              </FieldRow>
            )}

            <FieldRow label="Cache Validation" description="LLM validates cached results are relevant before returning">
              <ToggleSwitch checked={config.cache_validation_enabled}
                onChange={(v) => handleChange('cache_validation_enabled', v)} />
            </FieldRow>

            {config.cache_validation_enabled && (
              <FieldRow label="Validation Model" description="LLM endpoint used for cache validation">
                <EndpointSelect value={config.validation_model} onChange={(v) => handleChange('validation_model', v)}
                  endpoints={endpoints} loading={endpointsLoading} filterTask="llm/v1/chat" placeholder="Default (workspace default)" />
              </FieldRow>
            )}

            <FieldRow label="Embedding Provider" description="Provider for query embeddings">
              <select value={config.embedding_provider} onChange={(e) => handleChange('embedding_provider', e.target.value)}
                className={`${inputClass} bg-white`} style={{ width: '140px' }}>
                <option value="databricks">Databricks</option>
                <option value="local">Local</option>
              </select>
            </FieldRow>

            {config.embedding_provider === 'databricks' && (
              <FieldRow label="Embedding Endpoint" description="Databricks serving endpoint for embeddings" noBorder>
                <EndpointSelect value={config.databricks_embedding_endpoint}
                  onChange={(v) => handleChange('databricks_embedding_endpoint', v)}
                  endpoints={endpoints} loading={endpointsLoading} filterTask="llm/v1/embeddings" placeholder="Select endpoint..." />
              </FieldRow>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
