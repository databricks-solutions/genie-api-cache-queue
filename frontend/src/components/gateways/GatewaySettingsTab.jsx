import { useState, useEffect } from 'react'
import { Save, RotateCcw, Loader2 } from 'lucide-react'
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

function EndpointSelect({ value, onChange, endpoints, loading, placeholder, filterTask }) {
  const filtered = filterTask ? endpoints.filter(ep => ep.task === filterTask) : endpoints
  if (loading) {
    return (
      <div className="h-8 flex items-center gap-2 text-[13px] text-dbx-text-secondary">
        <Loader2 size={14} className="animate-spin" /> Loading...
      </div>
    )
  }
  return (
    <select value={value} onChange={(e) => onChange(e.target.value)}
      className="h-8 w-full border border-dbx-border-input rounded px-3 text-[13px] text-dbx-text outline-none focus:border-dbx-blue transition-colors bg-dbx-bg">
      <option value="">{placeholder || 'Select endpoint...'}</option>
      {filtered.map(ep => (
        <option key={ep.name} value={ep.name}>{ep.name}</option>
      ))}
    </select>
  )
}

export default function GatewaySettingsTab({ gateway, onUpdate }) {
  const ttl = secondsToTtl(gateway.cache_ttl_seconds)

  const [form, setForm] = useState({
    caching_enabled: gateway.caching_enabled !== false,
    similarity_threshold: String(gateway.similarity_threshold ?? 0.92),
    cache_ttl_value: ttl.value,
    cache_ttl_unit: ttl.unit,
    max_queries_per_minute: String(gateway.max_qpm || gateway.max_queries_per_minute || 5),
    question_normalization_enabled: gateway.question_normalization_enabled !== false,
    normalization_model: gateway.normalization_model || '',
    cache_validation_enabled: gateway.cache_validation_enabled !== false,
    validation_model: gateway.validation_model || '',
    embedding_provider: gateway.embedding_provider || 'databricks',
    databricks_embedding_endpoint: gateway.databricks_embedding_endpoint || 'databricks-gte-large-en',
    shared_cache: gateway.shared_cache !== false,
    sql_warehouse_id: gateway.sql_warehouse_id || '',
  })

  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [endpoints, setEndpoints] = useState([])
  const [endpointsLoading, setEndpointsLoading] = useState(true)
  const [warehouses, setWarehouses] = useState([])
  const [warehousesLoading, setWarehousesLoading] = useState(true)

  useEffect(() => {
    api.listServingEndpoints()
      .then((data) => setEndpoints(data.endpoints || []))
      .catch(() => setEndpoints([]))
      .finally(() => setEndpointsLoading(false))

    api.listWarehouses()
      .then((data) => setWarehouses(data.warehouses || []))
      .catch(() => setWarehouses([]))
      .finally(() => setWarehousesLoading(false))
  }, [])

  useEffect(() => {
    if (saved) {
      const timer = setTimeout(() => setSaved(false), 2000)
      return () => clearTimeout(timer)
    }
  }, [saved])

  const handleChange = (field, value) => {
    setForm((prev) => ({ ...prev, [field]: value }))
    setSaved(false)
  }

  const handleSave = async () => {
    try {
      setSaving(true)
      const updates = {
        caching_enabled: form.caching_enabled,
        similarity_threshold: parseFloat(form.similarity_threshold) || 0.92,
        cache_ttl_seconds: ttlToSeconds(form.cache_ttl_value, form.cache_ttl_unit),
        max_qpm: parseInt(form.max_queries_per_minute) || 5,
        max_queries_per_minute: parseInt(form.max_queries_per_minute) || 5,
        question_normalization_enabled: form.question_normalization_enabled,
        normalization_model: form.normalization_model || undefined,
        cache_validation_enabled: form.cache_validation_enabled,
        validation_model: form.validation_model || undefined,
        embedding_provider: form.embedding_provider,
        databricks_embedding_endpoint: form.databricks_embedding_endpoint,
        shared_cache: form.shared_cache,
        sql_warehouse_id: form.sql_warehouse_id || undefined,
      }
      const updated = await api.updateGateway(gateway.id, updates)
      onUpdate?.(updated)
      setSaved(true)
    } catch (err) {
      alert('Failed to save settings: ' + (err.response?.data?.detail || err.message))
    } finally {
      setSaving(false)
    }
  }

  const handleResetDefaults = async () => {
    try {
      const defaults = await api.getSettings().catch(() => null)
      setForm({
        similarity_threshold: String(defaults?.similarity_threshold ?? 0.92),
        cache_ttl_value: '24',
        cache_ttl_unit: 'hours',
        max_queries_per_minute: String(defaults?.max_queries_per_minute ?? 5),
        question_normalization_enabled: defaults?.question_normalization_enabled ?? true,
        normalization_model: defaults?.normalization_model || '',
        cache_validation_enabled: defaults?.cache_validation_enabled ?? true,
        validation_model: defaults?.validation_model || '',
        embedding_provider: defaults?.embedding_provider ?? 'databricks',
        databricks_embedding_endpoint: defaults?.databricks_embedding_endpoint ?? 'databricks-gte-large-en',
        shared_cache: defaults?.shared_cache ?? true,
        sql_warehouse_id: form.sql_warehouse_id,
      })
      setSaved(false)
    } catch {
      setForm(prev => ({
        ...prev,
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
      }))
    }
  }

  const inputClass = 'h-8 w-full border border-dbx-border-input rounded px-3 text-[13px] text-dbx-text bg-dbx-bg outline-none focus:border-dbx-blue transition-colors'

  return (
    <div className="max-w-xl space-y-6">
      {/* ── Semantic Cache (top-level toggle) ── */}
      <SettingsField label="Semantic Cache" description="Enable cache lookup and storage for this gateway. When disabled, every query goes directly to Genie.">
        <ToggleSwitch checked={form.caching_enabled} onChange={(v) => handleChange('caching_enabled', v)} />
      </SettingsField>

      {/* Cache-dependent settings — only shown when caching is enabled */}
      {form.caching_enabled && (
        <div className="space-y-6 pl-4 border-l-2 border-dbx-border">
          <SettingsField label="Similarity Threshold" description="Minimum cosine similarity to consider a cache hit (0-1)">
            <input type="number" min="0" max="1" step="0.01" value={form.similarity_threshold}
              onChange={(e) => handleChange('similarity_threshold', e.target.value)} className={inputClass} />
          </SettingsField>

          <SettingsField label="Cache TTL" description="How long cached entries remain valid">
            <div className="flex gap-2">
              <input type="number" min="0" value={form.cache_ttl_value}
                onChange={(e) => handleChange('cache_ttl_value', e.target.value)}
                className="h-8 flex-1 border border-dbx-border-input rounded px-3 text-[13px] text-dbx-text bg-dbx-bg outline-none focus:border-dbx-blue transition-colors" />
              <select value={form.cache_ttl_unit} onChange={(e) => handleChange('cache_ttl_unit', e.target.value)}
                className="h-8 border border-dbx-border-input rounded px-3 text-[13px] text-dbx-text outline-none focus:border-dbx-blue transition-colors bg-dbx-bg">
                <option value="minutes">Minutes</option>
                <option value="hours">Hours</option>
                <option value="days">Days</option>
              </select>
            </div>
          </SettingsField>

          <div className="space-y-2">
            <SettingsField label="Question Normalization" description="LLM rewrites questions to improve cache hit rates">
              <ToggleSwitch checked={form.question_normalization_enabled}
                onChange={(v) => handleChange('question_normalization_enabled', v)} />
            </SettingsField>
            {form.question_normalization_enabled && (
              <SettingsField label="Normalization Model" description="LLM endpoint for normalization">
                <EndpointSelect value={form.normalization_model} onChange={(v) => handleChange('normalization_model', v)}
                  endpoints={endpoints} loading={endpointsLoading} filterTask="llm/v1/chat"
                  placeholder="Default (from global settings)" />
              </SettingsField>
            )}
          </div>

          <div className="space-y-2">
            <SettingsField label="Cache Validation" description="LLM validates that cached results are relevant to the query before returning">
              <ToggleSwitch checked={form.cache_validation_enabled}
                onChange={(v) => handleChange('cache_validation_enabled', v)} />
            </SettingsField>
            {form.cache_validation_enabled && (
              <SettingsField label="Validation Model" description="LLM endpoint for cache validation">
                <EndpointSelect value={form.validation_model} onChange={(v) => handleChange('validation_model', v)}
                  endpoints={endpoints} loading={endpointsLoading} filterTask="llm/v1/chat"
                  placeholder="Default (from global settings)" />
              </SettingsField>
            )}
          </div>

          <SettingsField label="Embedding Provider" description="Provider for query embeddings">
            <select value={form.embedding_provider} onChange={(e) => handleChange('embedding_provider', e.target.value)}
              className="h-8 w-full border border-dbx-border-input rounded px-3 text-[13px] text-dbx-text outline-none focus:border-dbx-blue transition-colors bg-dbx-bg">
              <option value="databricks">Databricks</option>
              <option value="local">Local</option>
            </select>
          </SettingsField>

          {form.embedding_provider === 'databricks' && (
            <SettingsField label="Embedding Endpoint" description="Databricks serving endpoint for embeddings">
              <EndpointSelect value={form.databricks_embedding_endpoint}
                onChange={(v) => handleChange('databricks_embedding_endpoint', v)}
                endpoints={endpoints} loading={endpointsLoading} filterTask="llm/v1/embeddings"
                placeholder="Select embedding endpoint..." />
            </SettingsField>
          )}

          <SettingsField label="SQL Warehouse" description="Warehouse used for executing cached SQL queries">
            {warehousesLoading ? (
              <div className="h-8 flex items-center gap-2 text-[13px] text-dbx-text-secondary">
                <Loader2 size={14} className="animate-spin" /> Loading warehouses...
              </div>
            ) : (
              <select value={form.sql_warehouse_id} onChange={(e) => handleChange('sql_warehouse_id', e.target.value)}
                className="h-8 w-full border border-dbx-border-input rounded px-3 text-[13px] text-dbx-text outline-none focus:border-dbx-blue transition-colors bg-dbx-bg">
                <option value="">From Genie Space (default)</option>
                {warehouses.map(w => (
                  <option key={w.id} value={w.id}>{w.name} ({w.id})</option>
                ))}
              </select>
            )}
          </SettingsField>

          <SettingsField label="Shared Cache" description="When enabled, all users share a single cache">
            <ToggleSwitch checked={form.shared_cache} onChange={(v) => handleChange('shared_cache', v)} />
          </SettingsField>
        </div>
      )}

      {/* Max QPM (independent of caching) */}
      <SettingsField label="Max Queries per Minute" description="Rate limit for Genie API calls">
        <input type="number" min="1" value={form.max_queries_per_minute}
          onChange={(e) => handleChange('max_queries_per_minute', e.target.value)} className={inputClass} />
      </SettingsField>

      {/* Actions */}
      <div className="flex items-center gap-3 pt-2">
        <button onClick={handleSave} disabled={saving}
          className="inline-flex items-center gap-1.5 h-8 px-4 text-[13px] font-medium text-white bg-dbx-blue rounded hover:bg-dbx-blue-dark transition-colors disabled:opacity-50">
          <Save size={14} />
          {saving ? 'Saving...' : 'Save'}
        </button>
        <button onClick={handleResetDefaults}
          className="inline-flex items-center gap-1.5 h-8 px-4 text-[13px] font-medium text-dbx-text border border-dbx-border-input rounded hover:bg-dbx-neutral-hover transition-colors">
          <RotateCcw size={14} />
          Reset to Defaults
        </button>
        {saved && <span className="text-[13px] text-[#FF3621] font-medium">Settings saved</span>}
      </div>
    </div>
  )
}

function SettingsField({ label, description, children }) {
  return (
    <div>
      <label className="block text-[13px] font-medium text-dbx-text mb-1">{label}</label>
      {description && <p className="text-[13px] text-dbx-text-secondary mb-2">{description}</p>}
      {children}
    </div>
  )
}

function ToggleSwitch({ checked, onChange }) {
  return (
    <button type="button" role="switch" aria-checked={checked} onClick={() => onChange(!checked)}
      className={`relative inline-flex items-center h-5 rounded-full transition-colors duration-200 ${checked ? 'bg-dbx-blue' : 'bg-dbx-disabled'}`}
      style={{ width: '40px' }}>
      <span className={`inline-block w-4 h-4 rounded-full bg-white shadow transform transition-transform duration-200 ${checked ? 'translate-x-[21px]' : 'translate-x-[1px]'}`} />
    </button>
  )
}
