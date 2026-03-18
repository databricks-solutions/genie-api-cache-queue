import { useState, useEffect } from 'react';
import { Settings as SettingsIcon, Save, Eye, EyeOff, Trash2 } from 'lucide-react';
import { api } from '../services/api';

// Convert seconds to best-fit value + unit
const secondsToTtl = (seconds) => {
  if (!seconds || seconds === 0) return { value: '0', unit: 'hours' };
  if (seconds >= 86400 && seconds % 86400 === 0) return { value: String(seconds / 86400), unit: 'days' };
  if (seconds >= 3600 && seconds % 3600 === 0) return { value: String(seconds / 3600), unit: 'hours' };
  return { value: String(seconds / 60), unit: 'minutes' };
};

// Convert value + unit to seconds
const ttlToSeconds = (value, unit) => {
  const v = parseFloat(value) || 0;
  if (v === 0) return 0;
  if (unit === 'minutes') return Math.round(v * 60);
  if (unit === 'days') return Math.round(v * 86400);
  return Math.round(v * 3600);
};

const Settings = () => {
  const [config, setConfig] = useState({
    auth_mode: 'app',
    user_pat: '',
    genie_space_id: '',
    sql_warehouse_id: '',
    similarity_threshold: '0.92',
    max_queries_per_minute: '5',
    cache_ttl_value: '24',
    cache_ttl_unit: 'hours',
    embedding_provider: 'databricks',
    databricks_embedding_endpoint: 'databricks-bge-large-en',
    shared_cache: true,
    storage_backend: 'local',
    lakebase_instance_name: '',
    lakebase_catalog: '',
    lakebase_schema: 'public',
    cache_table_name: 'cached_queries',
    query_log_table_name: 'query_logs',
  });
  const [saved, setSaved] = useState(false);
  const [saving, setSaving] = useState(false);
  const [showUserPat, setShowUserPat] = useState(false);
  const [showClearConfirm, setShowClearConfirm] = useState(false);
  const [clearing, setClearing] = useState(false);

  useEffect(() => {
    // Load from server (source of truth), merge with localStorage for client-only fields
    const loadConfig = async () => {
      const local = localStorage.getItem('databricks_config');
      const localParsed = local ? JSON.parse(local) : {};

      try {
        const server = await api.getServerConfig();
        const ttl = secondsToTtl(server.cache_ttl_seconds);

        setConfig(prev => ({
          ...prev,
          // Server fields (source of truth)
          genie_space_id: server.genie_space_id || '',
          sql_warehouse_id: server.sql_warehouse_id || '',
          similarity_threshold: String(server.similarity_threshold || 0.92),
          max_queries_per_minute: String(server.max_queries_per_minute || 5),
          cache_ttl_value: ttl.value,
          cache_ttl_unit: ttl.unit,
          shared_cache: server.shared_cache ?? true,
          embedding_provider: server.embedding_provider || 'databricks',
          databricks_embedding_endpoint: server.databricks_embedding_endpoint || 'databricks-bge-large-en',
          storage_backend: server.storage_backend === 'pgvector' ? 'lakebase' : (server.storage_backend || 'local'),
          lakebase_instance_name: server.lakebase_instance_name || '',
          lakebase_catalog: server.lakebase_catalog || '',
          lakebase_schema: server.lakebase_schema || 'public',
          cache_table_name: server.cache_table_name || 'cached_queries',
          query_log_table_name: server.query_log_table_name || 'query_logs',
          // All fields from server (global across users)
          auth_mode: server.auth_mode || localParsed.auth_mode || 'app',
          user_pat: localParsed.user_pat || (server.lakebase_service_token_set ? '••••••••' : ''),
          _server_token_set: server.lakebase_service_token_set || false,
        }));
      } catch {
        // Server unreachable — fall back to localStorage
        if (localParsed.genie_space_id) {
          if (localParsed.cache_ttl_hours && !localParsed.cache_ttl_value) {
            localParsed.cache_ttl_value = localParsed.cache_ttl_hours;
            localParsed.cache_ttl_unit = 'hours';
          }
          setConfig(prev => ({ ...prev, ...localParsed }));
        }
      }
    };
    loadConfig();
  }, []);

  const handleChange = (e) => {
    const { name, value } = e.target;
    setConfig((prev) => ({ ...prev, [name]: value }));
    setSaved(false);
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      // Save all fields to server (global config)
      await api.updateServerConfig({
        auth_mode: config.auth_mode || undefined,
        lakebase_service_token: (config.user_pat && config.user_pat !== '••••••••') ? config.user_pat : undefined,
        genie_space_id: config.genie_space_id || undefined,
        sql_warehouse_id: config.sql_warehouse_id || undefined,
        similarity_threshold: parseFloat(config.similarity_threshold) || undefined,
        max_queries_per_minute: parseInt(config.max_queries_per_minute) || undefined,
        cache_ttl_seconds: ttlToSeconds(config.cache_ttl_value, config.cache_ttl_unit),
        shared_cache: config.shared_cache,
        embedding_provider: config.embedding_provider || undefined,
        databricks_embedding_endpoint: config.databricks_embedding_endpoint || undefined,
        storage_backend: config.storage_backend || undefined,
        lakebase_instance_name: config.lakebase_instance_name || undefined,
        lakebase_catalog: config.lakebase_catalog || undefined,
        lakebase_schema: config.lakebase_schema || undefined,
        cache_table_name: config.cache_table_name || undefined,
        query_log_table_name: config.query_log_table_name || undefined,
      });
    } catch (e) {
      console.warn('Failed to save to server, saving locally only:', e);
    }
    // Always save to localStorage (cache + client-only fields)
    localStorage.setItem('databricks_config', JSON.stringify(config));
    setSaving(false);
    setSaved(true);
    setTimeout(() => setSaved(false), 3000);
  };

  const hasLakebaseToken = config.user_pat || config._server_token_set;
  const isConfigured = config.genie_space_id && config.sql_warehouse_id &&
    (config.storage_backend === 'local' ||
     (config.storage_backend === 'lakebase' && config.lakebase_instance_name && hasLakebaseToken));

  return (
    <div className="max-w-4xl mx-auto">
      <div className="bg-white rounded-lg shadow-sm border">
        {/* Header */}
        <div className="px-6 py-4 border-b">
          <div className="flex items-center gap-3">
            <SettingsIcon className="w-6 h-6 text-gray-900" />
            <div>
              <h2 className="text-xl font-semibold text-gray-900">Configuration</h2>
              <p className="text-sm text-gray-500">
                Configure your Databricks credentials and application settings
              </p>
            </div>
          </div>
        </div>

        {/* Configuration Form */}
        <div className="p-6 space-y-6">
          {/* Status Banner */}
          {isConfigured ? (
            <div className="p-4 rounded-lg border-l-4 bg-gray-100 border-l-db-navy">
              <div className="flex items-center justify-between">
                <p className="text-sm font-medium text-gray-900">
                  Configuration complete - Ready to use
                </p>
                <span className="text-xs px-3 py-1 rounded-full font-medium bg-gray-200 text-db-navy">
                  Cache: {config.storage_backend === 'lakebase' ? 'Lakebase' : 'Local'}
                </span>
              </div>
            </div>
          ) : (
            <div className="p-4 rounded-lg border-l-4 bg-gray-100 border-l-db-lava">
              <p className="text-sm font-medium text-gray-900">
                Please configure all required fields to get started
                {config.auth_mode === 'user' && !config.user_pat && (
                  <span className="block mt-1 text-db-lava">- Personal Access Token is required for User Auth</span>
                )}
              </p>
            </div>
          )}

          {/* Authentication Info Banner */}
          <div className="p-4 rounded-lg border bg-gray-200 border-gray-300">
            <p className="text-sm font-medium mb-2 text-gray-900">
              Authentication
            </p>
            <p className="text-xs text-gray-900">
              Databricks Apps automatically handles authentication. Choose between App Auth (service principal)
              for app-wide operations or User Auth to respect individual user permissions.
            </p>
          </div>

          {/* Authentication Mode */}
          <div className="space-y-4">
            <h3 className="text-lg font-medium text-gray-900">Authentication Mode</h3>

            <div>
              <label className="block text-sm font-medium mb-2 text-gray-500">
                Auth Mode *
              </label>
              <div className="grid grid-cols-2 gap-3">
                <button
                  type="button"
                  onClick={() => setConfig(prev => ({ ...prev, auth_mode: 'app' }))}
                  className={`p-4 border-2 rounded-lg text-left transition-all ${
                    config.auth_mode === 'app' ? 'border-db-lava bg-gray-200' : 'border-gray-200 bg-white'
                  }`}
                >
                  <div className="font-medium mb-1 text-gray-900">App Auth</div>
                  <div className="text-xs text-gray-500">
                    Service Principal - App-wide access
                  </div>
                </button>
                <button
                  type="button"
                  onClick={() => setConfig(prev => ({ ...prev, auth_mode: 'user' }))}
                  className={`p-4 border-2 rounded-lg text-left transition-all ${
                    config.auth_mode === 'user' ? 'border-db-lava bg-gray-200' : 'border-gray-200 bg-white'
                  }`}
                >
                  <div className="font-medium mb-1 text-gray-900">User Auth</div>
                  <div className="text-xs text-gray-500">
                    User Token - Respects user permissions
                  </div>
                </button>
              </div>
              <p className="text-xs mt-2 text-gray-500">
                {config.auth_mode === 'app'
                  ? 'Using service principal credentials from DATABRICKS_CLIENT_ID/SECRET'
                  : 'Using user access token. Provide your PAT below for full API access.'}
              </p>
            </div>



          {/* Databricks Resources */}
          <div className="space-y-4 pt-4 border-t">
            <h3 className="text-lg font-medium text-gray-900">Databricks Resources</h3>

            <div>
              <label className="block text-sm font-medium mb-1 text-gray-500">
                Genie Space ID *
              </label>
              <input
                type="text"
                name="genie_space_id"
                value={config.genie_space_id}
                onChange={handleChange}
                placeholder="Enter your Genie Space ID"
                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-db-lava focus:border-transparent"
              />
              <p className="text-xs mt-1 text-gray-500">Your Genie space identifier</p>
            </div>

            <div>
              <label className="block text-sm font-medium mb-1 text-gray-500">
                SQL Warehouse ID *
              </label>
              <input
                type="text"
                name="sql_warehouse_id"
                value={config.sql_warehouse_id}
                onChange={handleChange}
                placeholder="Enter your SQL Warehouse ID"
                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-db-lava focus:border-transparent"
              />
              <p className="text-xs mt-1 text-gray-500">SQL warehouse for query execution</p>
            </div>
          </div>

          </div>

          {/* Application Settings */}
          <div className="space-y-4 pt-4 border-t">
            <h3 className="text-lg font-medium text-gray-900">Application Settings</h3>

            <div className="grid grid-cols-3 gap-4">
              <div>
                <label className="block text-sm font-medium mb-1 text-gray-500">
                  Similarity Threshold
                </label>
                <input
                  type="number"
                  name="similarity_threshold"
                  value={config.similarity_threshold}
                  onChange={handleChange}
                  min="0"
                  max="1"
                  step="0.05"
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-db-lava focus:border-transparent"
                />
                <p className="text-xs mt-1 text-gray-500">Cache matching (0.92 = 92%)</p>
              </div>

              <div>
                <label className="block text-sm font-medium mb-1 text-gray-500">
                  Max Queries/Minute
                </label>
                <input
                  type="number"
                  name="max_queries_per_minute"
                  value={config.max_queries_per_minute}
                  onChange={handleChange}
                  min="1"
                  max="100"
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-db-lava focus:border-transparent"
                />
                <p className="text-xs mt-1 text-gray-500">Rate limit per user</p>
              </div>

              <div>
                <label className="block text-sm font-medium mb-1 text-gray-500">
                  Cache Freshness
                </label>
                <div className="flex gap-2">
                  <input
                    type="number"
                    name="cache_ttl_value"
                    value={config.cache_ttl_value}
                    onChange={handleChange}
                    min="0"
                    step="1"
                    className="flex-1 min-w-0 px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-db-lava focus:border-transparent"
                  />
                  <select
                    name="cache_ttl_unit"
                    value={config.cache_ttl_unit}
                    onChange={handleChange}
                    className="w-28 px-2 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-db-lava focus:border-transparent text-sm"
                  >
                    <option value="minutes">minutes</option>
                    <option value="hours">hours</option>
                    <option value="days">days</option>
                  </select>
                </div>
                <p className="text-xs mt-1 text-gray-500">0 = no limit</p>
              </div>
            </div>

            <div>
              <label className="block text-sm font-medium mb-1 text-gray-500">
                Cache Mode
              </label>
              <div className="grid grid-cols-2 gap-3">
                <button
                  type="button"
                  onClick={() => setConfig(prev => ({ ...prev, shared_cache: true }))}
                  className={`p-3 border-2 rounded-lg text-left transition-all ${
                    config.shared_cache !== false ? 'border-db-lava bg-gray-200' : 'border-gray-200 bg-white'
                  }`}
                >
                  <div className="font-medium text-sm text-gray-900">Global</div>
                  <div className="text-xs text-gray-500">All users share cache</div>
                </button>
                <button
                  type="button"
                  onClick={() => setConfig(prev => ({ ...prev, shared_cache: false }))}
                  className={`p-3 border-2 rounded-lg text-left transition-all ${
                    config.shared_cache === false ? 'border-db-lava bg-gray-200' : 'border-gray-200 bg-white'
                  }`}
                >
                  <div className="font-medium text-sm text-gray-900">Per User</div>
                  <div className="text-xs text-gray-500">Cache isolated by identity</div>
                </button>
              </div>
              <p className="text-xs mt-1 text-gray-500">Global cache maximizes rate limit mitigation</p>
            </div>

            <div>
              <label className="block text-sm font-medium mb-1 text-gray-500">
                Embedding Provider
              </label>
              <select
                name="embedding_provider"
                value={config.embedding_provider}
                onChange={handleChange}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-db-lava focus:border-transparent"
              >
                <option value="databricks">Databricks (Recommended)</option>
                <option value="local">Local (Requires sentence-transformers)</option>
              </select>
            </div>

            <div>
              <label className="block text-sm font-medium mb-1 text-gray-500">
                Databricks Embedding Endpoint
              </label>
              <input
                type="text"
                name="databricks_embedding_endpoint"
                value={config.databricks_embedding_endpoint}
                onChange={handleChange}
                placeholder="databricks-bge-large-en"
                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-db-lava focus:border-transparent"
              />
              <p className="text-xs mt-1 text-gray-500">Databricks Foundation Model endpoint</p>
            </div>
          </div>

          {/* Cache Storage Selection */}
          <div className="border-t pt-6">
            <h3 className="text-lg font-medium mb-4 text-gray-900">
              Cache Storage
            </h3>

            <div className="mb-6">
              <label className="block text-sm font-medium mb-3 text-gray-500">
                Storage Backend
              </label>
              <div className="flex gap-4">
                <label className={`flex items-center gap-3 p-4 border-2 rounded-lg cursor-pointer transition-all hover:bg-gray-50 ${
                  config.storage_backend === 'local' ? 'border-db-lava bg-gray-200' : 'border-gray-200 bg-white'
                }`}>
                  <input
                    type="radio"
                    name="storage_backend"
                    value="local"
                    checked={config.storage_backend === 'local'}
                    onChange={handleChange}
                    className="w-4 h-4 accent-db-lava"
                  />
                  <div>
                    <div className="font-semibold text-gray-900">Local File Storage</div>
                    <div className="text-xs text-gray-500">Fast, in-memory (lost on restart)</div>
                  </div>
                </label>

                <label className={`flex items-center gap-3 p-4 border-2 rounded-lg cursor-pointer transition-all hover:bg-gray-50 ${
                  config.storage_backend === 'lakebase' ? 'border-db-lava bg-gray-200' : 'border-gray-200 bg-white'
                }`}>
                  <input
                    type="radio"
                    name="storage_backend"
                    value="lakebase"
                    checked={config.storage_backend === 'lakebase'}
                    onChange={handleChange}
                    className="w-4 h-4 accent-db-lava"
                  />
                  <div>
                    <div className="font-semibold text-gray-900">Databricks Lakebase</div>
                    <div className="text-xs text-gray-500">PostgreSQL + PGVector (persistent)</div>
                  </div>
                </label>
              </div>
            </div>

            {config.storage_backend === 'lakebase' && (
              <>
                <div className="rounded-lg p-4 mb-4 border bg-gray-200 border-gray-300">
                  <p className="text-sm text-gray-900">
                    <strong>Lakebase Service Token:</strong> A Service Principal or PAT token used exclusively for Lakebase cache operations.
                    This token is NOT used for Genie API calls — callers authenticate with their own OAuth token.
                  </p>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  {/* Lakebase Service Token */}
                  <div className="md:col-span-2">
                    <label className="block text-sm font-medium mb-1 text-gray-500">
                      Lakebase Service Token <span className="text-db-lava">*</span>
                    </label>
                    <div className="relative">
                      <input
                        type={showUserPat ? 'text' : 'password'}
                        name="user_pat"
                        value={config.user_pat}
                        onChange={handleChange}
                        placeholder="dapi... (PAT) or client_id:client_secret (SP)"
                        className="w-full px-3 py-2 border border-gray-300 rounded-lg pr-10 focus:outline-none focus:ring-2 focus:ring-db-lava focus:border-transparent"
                      />
                      <button
                        type="button"
                        onClick={() => setShowUserPat(!showUserPat)}
                        className="absolute right-2 top-1/2 -translate-y-1/2 hover:opacity-70 text-gray-500"
                      >
                        {showUserPat ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                      </button>
                    </div>
                    <p className="text-xs mt-1 text-gray-500">
                      Formats: <strong>PAT</strong> (<code className="bg-gray-100 px-1 rounded">dapi...</code>) or <strong>Service Principal</strong> (<code className="bg-gray-100 px-1 rounded">client_id:client_secret</code>).
                      The SP must have CAN_MANAGE on the Lakebase project.
                      Also configurable via <code className="bg-gray-100 px-1 rounded">PUT /api/config</code> with field <code className="bg-gray-100 px-1 rounded">lakebase_service_token</code>.
                    </p>
                  </div>

                  <div className="md:col-span-2">
                    <label className="block text-sm font-medium mb-1 text-gray-500">
                      Lakebase Instance Name <span className="text-db-lava">*</span>
                    </label>
                    <input
                      type="text"
                      name="lakebase_instance_name"
                      value={config.lakebase_instance_name}
                      onChange={handleChange}
                      placeholder="genie-cache or ep-xxx.database.us-east-1.cloud.databricks.com"
                      className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-db-lava focus:border-transparent"
                      required={config.storage_backend === 'lakebase'}
                    />
                    <p className="text-xs mt-1 text-gray-500">
                      Autoscaling project name (e.g. "genie-cache"), Provisioned instance name, or direct hostname.
                    </p>
                  </div>

                  <div>
                    <label className="block text-sm font-medium mb-1 text-gray-500">
                      Lakebase Catalog
                    </label>
                    <input
                      type="text"
                      name="lakebase_catalog"
                      value={config.lakebase_catalog}
                      onChange={handleChange}
                      placeholder="my_catalog"
                      className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-db-lava focus:border-transparent"
                    />
                    <p className="text-xs mt-1 text-gray-500">Catalog name (optional for Autoscaling instances)</p>
                  </div>

                  <div>
                    <label className="block text-sm font-medium mb-1 text-gray-500">
                      Lakebase Schema
                    </label>
                    <input
                      type="text"
                      name="lakebase_schema"
                      value={config.lakebase_schema}
                      onChange={handleChange}
                      placeholder="public"
                      className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-db-lava focus:border-transparent"
                    />
                    <p className="text-xs mt-1 text-gray-500">Schema (usually 'public')</p>
                  </div>

                  {/* Table Names */}
                  <div className="md:col-span-2 pt-4 border-t">
                    <h4 className="text-sm font-medium mb-3 text-gray-900">Table Names</h4>
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                      <div>
                        <label className="block text-sm font-medium mb-1 text-gray-500">
                          Cache Table Name
                        </label>
                        <input
                          type="text"
                          name="cache_table_name"
                          value={config.cache_table_name}
                          onChange={handleChange}
                          placeholder="cached_queries"
                          className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-db-lava focus:border-transparent"
                        />
                        <p className="text-xs mt-1 text-gray-500">Table for cached queries with embeddings</p>
                      </div>

                      <div>
                        <label className="block text-sm font-medium mb-1 text-gray-500">
                          Query Log Table Name
                        </label>
                        <input
                          type="text"
                          name="query_log_table_name"
                          value={config.query_log_table_name}
                          onChange={handleChange}
                          placeholder="query_logs"
                          className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-db-lava focus:border-transparent"
                        />
                        <p className="text-xs mt-1 text-gray-500">Table for query submission history</p>
                      </div>
                    </div>
                  </div>
                </div>
              </>
            )}
          </div>

          {/* Save Button */}
          <div className="flex items-center gap-3 pt-4">
            <button
              onClick={handleSave}
              disabled={!config.genie_space_id || !config.sql_warehouse_id || saving}
              className="flex items-center gap-2 px-6 py-2 rounded-lg font-medium text-white bg-gray-900 disabled:bg-gray-300 disabled:text-gray-400 disabled:cursor-not-allowed"
            >
              <Save className="w-4 h-4" />
              {saving ? 'Saving...' : 'Save Configuration'}
            </button>

            {saved && (
              <span className="text-sm font-medium text-db-navy">
                Saved
              </span>
            )}
          </div>

          {/* Info Box */}
          <div className="p-4 rounded-lg border bg-gray-100 border-gray-200">
            <p className="text-sm font-medium mb-2 text-gray-900">
              How It Works
            </p>
            <ul className="text-xs space-y-1 text-gray-500">
              <li>- <strong>Genie API:</strong> Uses caller's OAuth token (from Databricks Apps proxy or Authorization header)</li>
              <li>- <strong>Lakebase Cache:</strong> Uses the app's built-in Service Principal (auto-detected)</li>
              <li>- <strong>Host:</strong> Automatically detected from DATABRICKS_HOST environment variable</li>
              <li>- <strong>Configuration:</strong> Synced with server — changes here apply to both UI and Clone API</li>
            </ul>
          </div>

          {/* Danger Zone */}
          <div className="border-t border-red-200 pt-6">
            <h3 className="text-lg font-medium text-db-lava mb-3">Danger Zone</h3>
            <div className="p-4 rounded-lg border border-red-200 bg-red-50">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm font-medium text-gray-900">Clear Cache</p>
                  <p className="text-xs text-gray-500">Delete all cached queries from Lakebase. This cannot be undone.</p>
                </div>
                <button
                  onClick={() => setShowClearConfirm(true)}
                  className="flex items-center gap-2 px-4 py-2 rounded-lg font-medium text-white bg-db-lava hover:opacity-90"
                >
                  <Trash2 className="w-4 h-4" />
                  Clear Cache
                </button>
              </div>
            </div>
          </div>

          {/* Clear Cache Confirmation Modal */}
          {showClearConfirm && (
            <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
              <div className="bg-white rounded-xl shadow-2xl max-w-md w-full mx-4 overflow-hidden">
                <div className="p-6">
                  <div className="flex items-center gap-3 mb-4">
                    <div className="w-10 h-10 rounded-full bg-red-100 flex items-center justify-center">
                      <Trash2 className="w-5 h-5 text-db-lava" />
                    </div>
                    <h3 className="text-lg font-semibold text-gray-900">Clear All Cached Queries</h3>
                  </div>
                  <p className="text-sm text-gray-600 mb-2">
                    This will permanently delete all cached queries and their embeddings from Lakebase.
                  </p>
                  <p className="text-sm text-gray-600">
                    Future queries will need to go through the Genie API until the cache is rebuilt. This action cannot be undone.
                  </p>
                </div>
                <div className="flex gap-3 px-6 py-4 bg-gray-50 justify-end">
                  <button
                    onClick={() => setShowClearConfirm(false)}
                    disabled={clearing}
                    className="px-4 py-2 rounded-lg font-medium text-gray-700 bg-white border border-gray-300 hover:bg-gray-50"
                  >
                    Cancel
                  </button>
                  <button
                    onClick={async () => {
                      setClearing(true);
                      try {
                        const result = await api.clearCache();
                        setShowClearConfirm(false);
                        setSaved(false);
                        setTimeout(() => { setSaved(true); setTimeout(() => setSaved(false), 3000); }, 0);
                      } catch (e) {
                        setShowClearConfirm(false);
                      }
                      setClearing(false);
                    }}
                    disabled={clearing}
                    className="px-4 py-2 rounded-lg font-medium text-white bg-db-lava hover:opacity-90 disabled:opacity-50"
                  >
                    {clearing ? 'Clearing...' : 'Yes, Clear Cache'}
                  </button>
                </div>
              </div>
            </div>
          )}

        </div>
      </div>
    </div>
  );
};

export default Settings;
