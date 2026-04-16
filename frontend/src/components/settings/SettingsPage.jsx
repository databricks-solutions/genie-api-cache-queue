import { useState, useEffect, useRef, useCallback, useMemo } from 'react'
import { Pencil, Eye, EyeOff, Loader2, CheckCircle, XCircle, FlaskConical, Database, SlidersHorizontal, Palette, Users, Trash2 } from 'lucide-react'
import { api } from '../../services/api'
import { useTheme } from '../../context/ThemeContext'
import { useRole } from '../../context/RoleContext'

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

/* ── Toggle ── */
function ToggleSwitch({ checked, onChange }) {
  return (
    <div className="flex items-center gap-1.5">
      <span className="text-[13px] font-semibold text-dbx-text">{checked ? 'On' : 'Off'}</span>
      <button type="button" role="switch" aria-checked={checked} onClick={() => onChange(!checked)}
        className={`relative inline-flex items-center rounded-full transition-colors duration-200 ${checked ? 'bg-dbx-blue' : 'bg-dbx-disabled'}`}
        style={{ width: '28px', height: '16px' }}>
        <span className={`inline-block rounded-full bg-white shadow transform transition-transform duration-200 ${checked ? 'translate-x-[13px]' : 'translate-x-[1px]'}`}
          style={{ width: '12px', height: '12px' }} />
      </button>
    </div>
  )
}

/* ── Pencil-edit field ── */
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
          className="h-8 border border-dbx-blue rounded px-3 text-[13px] text-dbx-text bg-dbx-bg outline-none"
          style={{ width: '220px' }} />
        <button onClick={save}
          className="h-8 px-3 text-[13px] text-white bg-dbx-blue rounded hover:bg-dbx-blue-dark transition-colors">Save</button>
        <button onClick={cancel}
          className="h-8 px-3 text-[13px] text-dbx-text border border-dbx-border-input rounded hover:bg-dbx-neutral-hover transition-colors">Cancel</button>
      </div>
    )
  }

  return (
    <div className="flex items-center gap-2">
      <span className={`text-[13px] ${isEmpty ? 'text-dbx-text-secondary italic' : 'text-dbx-text'}`}>
        {displayValue}
      </span>
      <button onClick={startEdit} className="text-dbx-text-secondary hover:text-dbx-text transition-colors p-1">
        <Pencil size={14} />
      </button>
    </div>
  )
}

/* ── User search dropdown ── */
function UserSearchDropdown({ query, users, onSelect }) {
  const filtered = query
    ? users.filter(u =>
        u.email.toLowerCase().includes(query.toLowerCase()) ||
        (u.displayName && u.displayName.toLowerCase().includes(query.toLowerCase()))
      ).slice(0, 8)
    : users.slice(0, 8)

  if (filtered.length === 0) return null

  return (
    <div className="absolute z-50 mt-1 w-full bg-dbx-bg border border-dbx-border rounded shadow-lg max-h-48 overflow-y-auto">
      {filtered.map(u => (
        <button
          key={u.email}
          type="button"
          className="w-full text-left px-3 py-2 text-[13px] hover:bg-dbx-sidebar transition-colors"
          onMouseDown={(e) => {
            e.preventDefault()
            onSelect(u.email)
          }}
        >
          <div className="text-dbx-text">{u.displayName || u.email}</div>
          {u.displayName && <div className="text-dbx-text-secondary text-[11px]">{u.email}</div>}
        </button>
      ))}
    </div>
  )
}

/* ── Group search dropdown ── */
function GroupSearchDropdown({ query, groups, onSelect }) {
  const filtered = groups.filter(g =>
    g.displayName.toLowerCase().includes((query || '').toLowerCase())
  ).slice(0, 8)
  if (filtered.length === 0) return null
  return (
    <div className="absolute top-full left-0 right-0 mt-1 bg-dbx-bg border border-dbx-border rounded shadow-lg z-50 max-h-48 overflow-y-auto">
      {filtered.map(g => (
        <button key={g.displayName}
          onMouseDown={() => onSelect(g.displayName)}
          className="w-full text-left px-3 py-2 text-[13px] hover:bg-dbx-neutral-hover transition-colors flex justify-between items-center">
          <span className="text-dbx-text">{g.displayName}</span>
          <span className="text-[11px] text-dbx-text-secondary">{g.memberCount} members</span>
        </button>
      ))}
    </div>
  )
}

/* ── Field row container ── */
function FieldRow({ label, description, children, noBorder }) {
  return (
    <div className={`py-6 ${noBorder ? '' : 'border-b border-dbx-border'}`}>
      <div className="flex items-center justify-between gap-6">
        <div className="flex-1">
          <span className="text-[13px] font-semibold text-dbx-text leading-[20px]">{label}</span>
          {description && <div className="text-[12px] text-dbx-text-secondary leading-[16px]">{description}</div>}
        </div>
        <div className="shrink-0">{children}</div>
      </div>
    </div>
  )
}

/* ── Field row for stacked content (token, test connection) ── */
function FieldRowStacked({ label, description, children, noBorder }) {
  return (
    <div className={`py-6 ${noBorder ? '' : 'border-b border-dbx-border'}`}>
      <span className="text-[13px] font-semibold text-dbx-text leading-[20px]">{label}</span>
      {description && <div className="text-[12px] text-dbx-text-secondary leading-[16px]">{description}</div>}
      <div className="mt-2">{children}</div>
    </div>
  )
}

/* ── Endpoint select ── */
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
      className="h-8 border border-dbx-border-input rounded px-3 text-[13px] text-dbx-text outline-none focus:border-dbx-blue transition-colors bg-dbx-bg"
      style={{ width: '220px' }}>
      <option value="">{placeholder || 'Select endpoint...'}</option>
      {filtered.map(ep => <option key={ep.name} value={ep.name}>{ep.name}</option>)}
    </select>
  )
}

/* ── Sidebar structure ── */
const SIDEBAR_BASE = [
  { category: 'Preferences', icon: Palette, items: [{ id: 'appearance', label: 'Appearance' }] },
  { category: 'Connection', icon: Database, items: [{ id: 'general', label: 'General' }] },
  { category: 'Gateway Defaults', icon: SlidersHorizontal, items: [
    { id: 'cache', label: 'Cache' },
    { id: 'rate-limiting', label: 'Rate Limiting' },
    { id: 'ai-pipeline', label: 'AI Pipeline' },
  ]},
]
const SIDEBAR_MANAGE = [
  { category: 'Access Control', icon: Users, items: [
    { id: 'users', label: 'Users' },
    { id: 'groups', label: 'Groups' },
  ]},
]

/* ── Main component ── */
export default function SettingsPage() {
  const { themeMode, setThemeMode } = useTheme()
  const { isOwner, isManage } = useRole()
  const [activeSection, setActiveSection] = useState('appearance')

  // Users management state (manage role and above)
  const [users, setUsers] = useState([])
  const [usersLoading, setUsersLoading] = useState(false)
  const [userError, setUserError] = useState(null)
  const [newUserEmail, setNewUserEmail] = useState('')
  const [newUserRole, setNewUserRole] = useState('use')
  const [userSaving, setUserSaving] = useState(false)
  const [workspaceUsers, setWorkspaceUsers] = useState([])
  const [showUserDropdown, setShowUserDropdown] = useState(false)
  const [groups, setGroups] = useState([])
  const [groupsLoading, setGroupsLoading] = useState(false)
  const [groupError, setGroupError] = useState(null)
  const [newGroupName, setNewGroupName] = useState('')
  const [newGroupRole, setNewGroupRole] = useState('use')
  const [groupSaving, setGroupSaving] = useState(false)
  const [workspaceGroups, setWorkspaceGroups] = useState([])
  const [showGroupDropdown, setShowGroupDropdown] = useState(false)
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
    return () => { if (saveTimerRef.current) clearTimeout(saveTimerRef.current) }
  }, [])

  // Load users and workspace users when manage/owner navigates to the users section
  useEffect(() => {
    if (isManage && activeSection === 'users') {
      setUsersLoading(true)
      Promise.all([
        api.listUsers().catch(() => []),
        api.listWorkspaceUsers().catch(() => []),
      ]).then(([roleUsers, wsUsers]) => {
        setUsers(roleUsers)
        setWorkspaceUsers(wsUsers)
      }).finally(() => setUsersLoading(false))
    }
  }, [isManage, activeSection])

  useEffect(() => {
    if (isManage && activeSection === 'groups') {
      setGroupsLoading(true)
      Promise.all([
        api.listGroups().catch(() => []),
        api.listWorkspaceGroups().catch(() => []),
      ]).then(([roleGroups, wsGroups]) => {
        setGroups(roleGroups)
        setWorkspaceGroups(wsGroups)
      }).finally(() => setGroupsLoading(false))
    }
  }, [isManage, activeSection])

  const handleAddUser = async () => {
    if (!newUserEmail.trim()) return
    setUserSaving(true)
    setUserError(null)
    try {
      const saved = await api.setUserRole(newUserEmail.trim(), newUserRole)
      setUsers(prev => {
        const without = prev.filter(u => u.identity !== saved.identity)
        return [...without, saved]
      })
      setNewUserEmail('')
      setNewUserRole('use')
    } catch (err) {
      const msg = err.response?.data?.detail || 'Failed to assign role.'
      setUserError(msg)
    } finally { setUserSaving(false) }
  }

  const handleRemoveUser = async (email) => {
    if (!window.confirm(`Remove role assignment for ${email}? They will revert to the default 'use' role.`)) return
    setUserError(null)
    try {
      await api.deleteUserRole(email)
      setUsers(prev => prev.filter(u => u.identity !== email))
    } catch (err) {
      const msg = err.response?.data?.detail || 'Failed to remove user.'
      setUserError(msg)
    }
  }

  const handleAddGroup = async () => {
    if (!newGroupName.trim()) return
    setGroupSaving(true)
    setGroupError(null)
    try {
      const saved = await api.setGroupRole(newGroupName.trim(), newGroupRole)
      setGroups(prev => {
        const without = prev.filter(g => g.group_name !== saved.group_name)
        return [...without, saved]
      })
      setNewGroupName('')
      setNewGroupRole('use')
    } catch (err) {
      setGroupError(err.response?.data?.detail || 'Failed to assign group role.')
    } finally { setGroupSaving(false) }
  }

  const handleRemoveGroup = async (groupName) => {
    if (!window.confirm(`Remove role for group "${groupName}"?`)) return
    setGroupError(null)
    try {
      await api.deleteGroupRole(groupName)
      setGroups(prev => prev.filter(g => g.group_name !== groupName))
    } catch (err) {
      setGroupError(err.response?.data?.detail || 'Failed to remove group role.')
    }
  }

  const SIDEBAR = useMemo(
    () => (isManage ? [...SIDEBAR_BASE, ...SIDEBAR_MANAGE] : SIDEBAR_BASE),
    [isManage]
  )

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
      try {
        const local = JSON.parse(localStorage.getItem('databricks_config') || '{}')
        localStorage.setItem('databricks_config', JSON.stringify({ ...local,
          storage_backend: c.storage_backend, similarity_threshold: c.similarity_threshold,
          max_queries_per_minute: c.max_queries_per_minute, shared_cache: c.shared_cache,
          embedding_provider: c.embedding_provider, databricks_embedding_endpoint: c.databricks_embedding_endpoint,
          question_normalization_enabled: c.question_normalization_enabled, cache_validation_enabled: c.cache_validation_enabled,
          lakebase_instance_name: c.lakebase_instance_name, lakebase_catalog: c.lakebase_catalog,
          lakebase_schema: c.lakebase_schema, cache_table_name: c.cache_table_name, query_log_table_name: c.query_log_table_name,
        }))
      } catch { /* localStorage sync is best-effort */ }
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
    if (saveTimerRef.current) clearTimeout(saveTimerRef.current)
    setConfig(prev => {
      const next = { ...prev, [field]: value }
      configRef.current = next
      return next
    })
    setTimeout(() => persistSettings(), 50)
  }, [persistSettings])

  const scrollToSection = (id) => {
    setActiveSection(id)
    sectionRefs.current[id]?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  const inputClass = 'h-8 border border-dbx-border-input rounded px-3 text-[13px] text-dbx-text bg-dbx-bg outline-none focus:border-dbx-blue transition-colors'

  if (loading) {
    return (
      <div className="flex h-full" style={systemStyle}>
        <div style={{ width: '240px' }} className="shrink-0 border-r border-dbx-border" />
        <div className="flex-1 p-6"><div className="text-[13px] text-dbx-text-secondary">Loading...</div></div>
      </div>
    )
  }

  return (
    <div className="flex h-full" style={systemStyle}>
      {/* ── Sidebar ── */}
      <div style={{ width: '240px' }} className="shrink-0 border-r border-dbx-border">
        <div className="px-6 pt-6 pb-6">
          <h2 className="text-[22px] font-semibold text-dbx-text leading-[28px]">Settings</h2>
        </div>
        <nav className="px-4">
          {SIDEBAR.map(({ category, icon: Icon, items }, idx) => (
            <div key={category} className={idx > 0 ? 'mt-6' : ''}>
              {category && (
                <div className="flex items-center gap-2 px-2 mb-1 text-[13px] text-dbx-text-secondary">
                  <Icon size={20} strokeWidth={1.5} />
                  <span>{category}</span>
                </div>
              )}
              <div className={category ? 'ml-3' : ''}>
                {items.map(({ id, label }) => (
                  <button key={id} onClick={() => scrollToSection(id)}
                    className={`w-full text-left rounded text-[13px] leading-[20px] transition-colors py-2 px-3 ${
                      activeSection === id
                        ? 'bg-dbx-sidebar text-dbx-text'
                        : 'text-dbx-text hover:bg-dbx-sidebar'
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
                saveStatus === 'saving' ? 'bg-dbx-bg text-dbx-text-secondary border border-dbx-border' :
                saveStatus === 'saved' ? 'bg-dbx-status-green-bg text-green-700 border border-green-200' :
                'bg-red-50 text-red-700 border border-red-200'
              }`}>
                {saveStatus === 'saving' && <Loader2 size={12} className="animate-spin" />}
                {saveStatus === 'saving' ? 'Saving...' : saveStatus === 'saved' ? 'Saved' : 'Save failed'}
              </div>
            </div>
          )}

          {/* ── Appearance ── */}
          <div ref={el => sectionRefs.current['appearance'] = el} className="mb-10">
            <h2 className="text-[22px] font-semibold text-dbx-text leading-[28px] pb-3 border-b border-dbx-border">Appearance</h2>

            <FieldRow
              label="Theme"
              description="'Follow Databricks workspace' reads your setting from User Settings → Preferences → Appearance; falls back to OS preference if unavailable."
              noBorder
            >
              <select
                value={themeMode}
                onChange={(e) => setThemeMode(e.target.value)}
                className={`${inputClass} bg-dbx-bg`}
                style={{ width: '220px' }}
              >
                <option value="light">Light</option>
                <option value="dark">Dark</option>
                <option value="system">Follow Databricks workspace</option>
              </select>
            </FieldRow>
          </div>

          {/* ── General ── */}
          <div ref={el => sectionRefs.current['general'] = el} className="mb-10">
            <h2 className="text-[22px] font-semibold text-dbx-text leading-[28px] pb-3 border-b border-dbx-border">General</h2>

            <FieldRow label="Storage Backend" description="Cached queries are persisted in Lakebase (PostgreSQL with pgvector)">
              <span className="inline-flex items-center px-3 py-1 text-[12px] font-medium bg-dbx-blue-hover text-dbx-text-link rounded">Lakebase</span>
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
              tokenSource === 'auto' ? 'Using app service principal credentials (DATABRICKS_CLIENT_ID/SECRET). Set a custom token to override.'
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
                  className="inline-flex items-center gap-1.5 h-8 px-3 text-[13px] text-dbx-text border border-dbx-border-input rounded hover:bg-dbx-neutral-hover transition-colors disabled:opacity-50">
                  {testingConn ? <Loader2 size={14} className="animate-spin" /> : <FlaskConical size={14} />}
                  {testingConn ? 'Testing...' : 'Test Connection'}
                </button>
                {connResult && (
                  <div className={`rounded p-3 text-[13px] border ${connResult.connected ? 'bg-dbx-status-green-bg border-green-200' : 'bg-red-50 border-red-200'}`}>
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
            <h3 className="text-[18px] font-semibold text-dbx-text leading-[24px] mb-2">Cache</h3>

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
                  className={`${inputClass} bg-dbx-bg`}>
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
            <h3 className="text-[18px] font-semibold text-dbx-text leading-[24px] mb-2">Rate Limiting</h3>

            <FieldRow label="Max Queries per Minute" description="Rate limit for Genie API calls per user" noBorder>
              <input type="number" min="1" max="100" value={config.max_queries_per_minute}
                onChange={(e) => handleChange('max_queries_per_minute', e.target.value)}
                className={inputClass} style={{ width: '80px' }} />
            </FieldRow>
          </div>

          {/* ── Users (manage+) ── */}
          {isManage && (
            <div ref={el => sectionRefs.current['users'] = el} className="mb-10">
              <h2 className="text-[22px] font-semibold text-dbx-text leading-[28px] pb-3 border-b border-dbx-border">Users</h2>

              <div className="py-4 text-[12px] text-dbx-text-secondary">
                Workspace admins always have <span className="font-semibold text-dbx-text">Owner</span> access regardless of this list.
              </div>

              {/* Role matrix */}
              <div className="mb-6 rounded border border-dbx-border overflow-hidden text-[12px]">
                <table className="w-full">
                  <thead>
                    <tr className="bg-dbx-sidebar text-dbx-text-secondary">
                      <th className="text-left px-3 py-2 font-medium">Role</th>
                      <th className="text-left px-3 py-2 font-medium">Query</th>
                      <th className="text-left px-3 py-2 font-medium">Configure</th>
                      <th className="text-left px-3 py-2 font-medium">Create/Delete</th>
                      <th className="text-left px-3 py-2 font-medium">Manage Users</th>
                    </tr>
                  </thead>
                  <tbody>
                    {[
                      { role: 'use',    q: true,  c: false, cd: false, mu: false },
                      { role: 'manage', q: true,  c: true,  cd: false, mu: true  },
                      { role: 'owner',  q: true,  c: true,  cd: true,  mu: true  },
                    ].map(({ role, q, c, cd, mu }) => (
                      <tr key={role} className="border-t border-dbx-border">
                        <td className="px-3 py-2 font-medium capitalize text-dbx-text">{role}</td>
                        {[q, c, cd, mu].map((v, i) => (
                          <td key={i} className="px-3 py-2">
                            <span className={v ? 'text-dbx-blue' : 'text-dbx-border-input'}>{v ? '●' : '○'}</span>
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {userError && (
                <div className="mb-3 px-3 py-2 rounded bg-red-50 border border-red-200 text-red-700 text-[13px]">
                  {userError}
                </div>
              )}

              {/* User list */}
              {usersLoading ? (
                <div className="flex items-center gap-2 py-4 text-[13px] text-dbx-text-secondary">
                  <Loader2 size={14} className="animate-spin" /> Loading users...
                </div>
              ) : (
                <div className="rounded border border-dbx-border overflow-hidden mb-4 text-[13px]">
                  {users.length === 0 ? (
                    <div className="px-4 py-6 text-center text-dbx-text-secondary">
                      No explicit role assignments. Add users below.
                    </div>
                  ) : (
                    <table className="w-full">
                      <thead>
                        <tr className="bg-dbx-sidebar text-dbx-text-secondary text-[12px]">
                          <th className="text-left px-3 py-2 font-medium">User</th>
                          <th className="text-left px-3 py-2 font-medium">Role</th>
                          <th className="text-left px-3 py-2 font-medium">Granted by</th>
                          <th className="px-3 py-2" />
                        </tr>
                      </thead>
                      <tbody>
                        {users.map((u) => (
                          <tr key={u.identity} className="border-t border-dbx-border">
                            <td className="px-3 py-2 text-dbx-text">{u.identity}</td>
                            <td className="px-3 py-2 capitalize text-dbx-text">{u.role}</td>
                            <td className="px-3 py-2 text-dbx-text-secondary">{u.granted_by || '—'}</td>
                            <td className="px-3 py-2 text-right">
                              <button
                                onClick={() => handleRemoveUser(u.identity)}
                                className="text-dbx-text-secondary hover:text-red-600 transition-colors p-1"
                                title="Remove role"
                              >
                                <Trash2 size={13} />
                              </button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                </div>
              )}

              {/* Add user */}
              <div className="flex items-center gap-2">
                <div className="relative flex-1" style={{ maxWidth: '260px' }}>
                  <input
                    type="email"
                    placeholder="user@company.com"
                    value={newUserEmail}
                    onChange={(e) => {
                      setNewUserEmail(e.target.value)
                      setShowUserDropdown(true)
                    }}
                    onFocus={() => setShowUserDropdown(true)}
                    onBlur={() => setTimeout(() => setShowUserDropdown(false), 150)}
                    onKeyDown={(e) => e.key === 'Enter' && handleAddUser()}
                    className={`${inputClass} w-full`}
                  />
                  {showUserDropdown && workspaceUsers.length > 0 && (
                    <UserSearchDropdown
                      query={newUserEmail}
                      users={workspaceUsers}
                      onSelect={(email) => {
                        setNewUserEmail(email)
                        setShowUserDropdown(false)
                      }}
                    />
                  )}
                </div>
                <select
                  value={newUserRole}
                  onChange={(e) => setNewUserRole(e.target.value)}
                  className={`${inputClass} bg-dbx-bg`}
                  style={{ width: '110px' }}
                >
                  <option value="use">Use</option>
                  <option value="manage">Manage</option>
                  {isOwner && <option value="owner">Owner</option>}
                </select>
                <button
                  onClick={handleAddUser}
                  disabled={userSaving || !newUserEmail.trim()}
                  className="h-8 px-3 text-[13px] text-white bg-dbx-blue rounded hover:bg-dbx-blue-dark transition-colors disabled:opacity-50"
                >
                  {userSaving ? <Loader2 size={13} className="animate-spin" /> : 'Add'}
                </button>
              </div>
            </div>
          )}

          {isManage && (
            <div ref={el => sectionRefs.current['groups'] = el} className="mb-10">
              <h2 className="text-[22px] font-semibold text-dbx-text leading-[28px] pb-3 border-b border-dbx-border">Groups</h2>

              <div className="py-4 text-[12px] text-dbx-text-secondary">
                Assign roles to workspace groups. When a user belongs to multiple groups, the highest privilege wins.
              </div>

              {groupError && (
                <div className="mb-3 px-3 py-2 rounded bg-red-50 border border-red-200 text-red-700 text-[13px]">
                  {groupError}
                </div>
              )}

              {groupsLoading ? (
                <div className="flex items-center gap-2 py-4 text-[13px] text-dbx-text-secondary">
                  <Loader2 size={14} className="animate-spin" /> Loading groups...
                </div>
              ) : (
                <div className="rounded border border-dbx-border overflow-hidden mb-4 text-[13px]">
                  {groups.length === 0 ? (
                    <div className="px-4 py-6 text-center text-dbx-text-secondary">
                      No group role assignments. Add groups below.
                    </div>
                  ) : (
                    <table className="w-full">
                      <thead>
                        <tr className="bg-dbx-sidebar text-dbx-text-secondary text-[12px]">
                          <th className="text-left px-3 py-2 font-medium">Group</th>
                          <th className="text-left px-3 py-2 font-medium">Role</th>
                          <th className="text-left px-3 py-2 font-medium">Granted by</th>
                          <th className="px-3 py-2" />
                        </tr>
                      </thead>
                      <tbody>
                        {groups.map((g) => (
                          <tr key={g.group_name} className="border-t border-dbx-border">
                            <td className="px-3 py-2 text-dbx-text">{g.group_name}</td>
                            <td className="px-3 py-2 capitalize text-dbx-text">{g.role}</td>
                            <td className="px-3 py-2 text-dbx-text-secondary">{g.granted_by || '—'}</td>
                            <td className="px-3 py-2 text-right">
                              <button onClick={() => handleRemoveGroup(g.group_name)}
                                className="text-dbx-text-secondary hover:text-red-600 transition-colors p-1" title="Remove group role">
                                <Trash2 size={13} />
                              </button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                </div>
              )}

              {/* Add group */}
              <div className="flex items-center gap-2">
                <div className="relative flex-1" style={{ maxWidth: '260px' }}>
                  <input type="text" placeholder="Group name"
                    value={newGroupName}
                    onChange={(e) => { setNewGroupName(e.target.value); setShowGroupDropdown(true) }}
                    onFocus={() => setShowGroupDropdown(true)}
                    onBlur={() => setTimeout(() => setShowGroupDropdown(false), 150)}
                    onKeyDown={(e) => e.key === 'Enter' && handleAddGroup()}
                    className={`${inputClass} w-full`}
                  />
                  {showGroupDropdown && workspaceGroups.length > 0 && (
                    <GroupSearchDropdown
                      query={newGroupName}
                      groups={workspaceGroups}
                      onSelect={(name) => { setNewGroupName(name); setShowGroupDropdown(false) }}
                    />
                  )}
                </div>
                <select value={newGroupRole} onChange={(e) => setNewGroupRole(e.target.value)}
                  className={`${inputClass} bg-dbx-bg`} style={{ width: '110px' }}>
                  <option value="use">Use</option>
                  <option value="manage">Manage</option>
                  {isOwner && <option value="owner">Owner</option>}
                </select>
                <button onClick={handleAddGroup} disabled={groupSaving || !newGroupName.trim()}
                  className="h-8 px-4 text-[13px] rounded bg-dbx-blue text-white hover:bg-dbx-blue-hover disabled:opacity-50 transition-colors">
                  {groupSaving ? 'Adding...' : 'Add'}
                </button>
              </div>
            </div>
          )}

          {/* ── AI Pipeline ── */}
          <div ref={el => sectionRefs.current['ai-pipeline'] = el} className="mb-10">
            <h3 className="text-[18px] font-semibold text-dbx-text leading-[24px] mb-2">AI Pipeline</h3>

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
                className={`${inputClass} bg-dbx-bg`} style={{ width: '140px' }}>
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
