import { useState } from 'react'
import { Save, Trash2, Loader2 } from 'lucide-react'
import { api } from '../../services/api'

export default function RouterSettingsTab({ routerCfg, onUpdate }) {
  const [form, setForm] = useState({
    name: routerCfg.name,
    description: routerCfg.description || '',
    status: routerCfg.status,
    selector_model: routerCfg.selector_model || '',
    selector_system_prompt: routerCfg.selector_system_prompt || '',
    decompose_enabled: !!routerCfg.decompose_enabled,
    routing_cache_enabled: !!routerCfg.routing_cache_enabled,
    similarity_threshold: routerCfg.similarity_threshold ?? 0.92,
    cache_ttl_hours: routerCfg.cache_ttl_hours ?? 24,
    mlflow_experiment_path: routerCfg.mlflow_experiment_path || '',
  })
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)
  const [success, setSuccess] = useState(null)
  const [flushing, setFlushing] = useState(false)
  const [flushResult, setFlushResult] = useState(null)

  const setField = (k, v) => setForm((f) => ({ ...f, [k]: v }))

  const save = async () => {
    setSaving(true)
    setError(null)
    setSuccess(null)
    try {
      await api.updateRouter(routerCfg.id, {
        name: form.name,
        description: form.description,
        status: form.status,
        selector_model: form.selector_model,
        selector_system_prompt: form.selector_system_prompt,
        decompose_enabled: form.decompose_enabled,
        routing_cache_enabled: form.routing_cache_enabled,
        similarity_threshold: Number(form.similarity_threshold),
        cache_ttl_hours: Math.round(Number(form.cache_ttl_hours)),
        mlflow_experiment_path: (form.mlflow_experiment_path || '').trim(),
      })
      setSuccess('Saved')
      onUpdate?.()
    } catch (err) {
      setError(err.response?.data?.detail || err.message || 'Save failed')
    } finally {
      setSaving(false)
    }
  }

  const flush = async () => {
    if (!window.confirm('Delete all routing cache entries for this router? The selector will re-learn on the next few questions.')) return
    setFlushing(true)
    setFlushResult(null)
    try {
      const res = await api.flushRouterCache(routerCfg.id)
      setFlushResult(`Cleared ${res.deleted} entries.`)
    } catch (err) {
      setFlushResult(err.response?.data?.detail || err.message || 'Flush failed')
    } finally {
      setFlushing(false)
    }
  }

  return (
    <div className="max-w-2xl">
      <h2 className="text-[15px] font-medium text-dbx-text mb-3">Settings</h2>

      <Section title="Identity">
        <Field label="Name">
          <input
            type="text"
            value={form.name}
            onChange={(e) => setField('name', e.target.value)}
            className="w-full h-8 px-2 border border-dbx-border-input rounded text-[13px] bg-dbx-bg"
          />
        </Field>
        <Field label="Description">
          <textarea
            value={form.description}
            onChange={(e) => setField('description', e.target.value)}
            rows={2}
            className="w-full px-2 py-1.5 border border-dbx-border-input rounded text-[13px] bg-dbx-bg resize-y"
          />
        </Field>
        <Field label="Status">
          <select
            value={form.status}
            onChange={(e) => setField('status', e.target.value)}
            className="w-32 h-8 px-2 border border-dbx-border-input rounded text-[13px] bg-dbx-bg"
          >
            <option value="active">active</option>
            <option value="disabled">disabled</option>
          </select>
        </Field>
      </Section>

      <Section title="Selector">
        <Field label="Selector model endpoint (leave blank for default databricks-llama-4-maverick)">
          <input
            type="text"
            value={form.selector_model}
            onChange={(e) => setField('selector_model', e.target.value)}
            placeholder="databricks-llama-4-maverick"
            className="w-full h-8 px-2 border border-dbx-border-input rounded text-[13px] bg-dbx-bg font-mono"
          />
        </Field>
        <Field label="System prompt override (leave blank for default)">
          <textarea
            value={form.selector_system_prompt}
            onChange={(e) => setField('selector_system_prompt', e.target.value)}
            rows={6}
            placeholder="Custom system prompt for the selector LLM"
            className="w-full px-2 py-1.5 border border-dbx-border-input rounded text-[12px] bg-dbx-bg resize-y font-mono"
          />
        </Field>
        <label className="flex items-center gap-2 text-[13px] text-dbx-text mb-2">
          <input
            type="checkbox"
            checked={form.decompose_enabled}
            onChange={(e) => setField('decompose_enabled', e.target.checked)}
          />
          Decompose multi-intent questions across multiple members
        </label>
      </Section>

      <Section title="Routing cache">
        <label className="flex items-center gap-2 text-[13px] text-dbx-text mb-3">
          <input
            type="checkbox"
            checked={form.routing_cache_enabled}
            onChange={(e) => setField('routing_cache_enabled', e.target.checked)}
          />
          Cache routing decisions (question → gateway pick)
        </label>
        <Field label="Similarity threshold">
          <input
            type="number"
            step="0.01" min="0" max="1"
            value={form.similarity_threshold}
            onChange={(e) => setField('similarity_threshold', e.target.value)}
            className="w-32 h-8 px-2 border border-dbx-border-input rounded text-[13px] bg-dbx-bg"
          />
        </Field>
        <Field label="Cache TTL (hours)">
          <input
            type="number"
            min="0"
            value={form.cache_ttl_hours}
            onChange={(e) => setField('cache_ttl_hours', e.target.value)}
            className="w-32 h-8 px-2 border border-dbx-border-input rounded text-[13px] bg-dbx-bg"
          />
        </Field>
        <button
          onClick={flush}
          disabled={flushing}
          className="inline-flex items-center gap-2 h-8 px-3 text-[13px] text-dbx-text border border-dbx-border-input rounded hover:bg-dbx-neutral-hover disabled:opacity-50"
        >
          {flushing ? <Loader2 size={13} className="animate-spin" /> : <Trash2 size={13} />}
          Flush routing cache
        </button>
        {flushResult && (
          <div className="text-[12px] text-dbx-text-secondary mt-2">{flushResult}</div>
        )}
      </Section>

      <Section title="Tracing">
        <Field label="MLflow experiment path">
          <input
            type="text"
            value={form.mlflow_experiment_path}
            onChange={(e) => setField('mlflow_experiment_path', e.target.value)}
            placeholder="/Users/you@databricks.com/router-traces"
            className="w-full h-8 px-2 border border-dbx-border-input rounded text-[13px] bg-dbx-bg font-mono"
          />
        </Field>
        <div className="text-[12px] text-dbx-text-secondary -mt-2">
          Workspace path for MLflow traces. Leave empty to disable tracing for this router. The
          experiment is auto-created on save if it doesn't exist. Multiple routers can share a
          path to combine traces.
        </div>
      </Section>

      {error && (
        <div className="px-3 py-2 rounded bg-red-50 border border-red-200 text-red-700 text-[13px] mb-3">
          {error}
        </div>
      )}
      {success && (
        <div className="px-3 py-2 rounded bg-green-50 border border-green-200 text-green-700 text-[13px] mb-3">
          {success}
        </div>
      )}

      <button
        onClick={save}
        disabled={saving}
        className="flex items-center gap-2 h-9 px-4 text-[13px] font-medium text-white bg-dbx-blue rounded hover:bg-dbx-blue-dark disabled:opacity-50"
      >
        {saving ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
        {saving ? 'Saving…' : 'Save changes'}
      </button>
    </div>
  )
}

function Section({ title, children }) {
  return (
    <div className="mb-6">
      <h3 className="text-[13px] font-medium text-dbx-text mb-2">{title}</h3>
      <div className="border border-dbx-border rounded px-4 py-3 bg-dbx-bg">
        {children}
      </div>
    </div>
  )
}

function Field({ label, children }) {
  return (
    <div className="mb-3">
      <label className="block text-[12px] font-medium text-dbx-text-secondary mb-1">{label}</label>
      {children}
    </div>
  )
}
