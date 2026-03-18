import axios from 'axios';

const API_BASE_URL = '/api';

// Sync server config to localStorage on first load so all API calls
// use the global config even if the user never opens Settings.
let _configSynced = false;
const _syncServerConfig = async () => {
  if (_configSynced) return;
  _configSynced = true;
  try {
    const response = await axios.get(`${API_BASE_URL}/config`);
    const server = response.data;
    if (server.genie_space_id || (server.genie_spaces && server.genie_spaces.length > 0)) {
      const local = JSON.parse(localStorage.getItem('databricks_config') || '{}');
      const merged = {
        ...local,
        auth_mode: server.auth_mode || local.auth_mode || 'app',
        genie_space_id: server.genie_space_id || local.genie_space_id,
        genie_spaces: (server.genie_spaces && server.genie_spaces.length > 0)
          ? server.genie_spaces
          : local.genie_spaces || [],
        sql_warehouse_id: server.sql_warehouse_id || local.sql_warehouse_id,
        similarity_threshold: String(server.similarity_threshold || local.similarity_threshold || 0.92),
        max_queries_per_minute: String(server.max_queries_per_minute || local.max_queries_per_minute || 5),
        shared_cache: server.shared_cache ?? local.shared_cache ?? true,
        embedding_provider: server.embedding_provider || local.embedding_provider || 'databricks',
        databricks_embedding_endpoint: server.databricks_embedding_endpoint || local.databricks_embedding_endpoint || 'databricks-bge-large-en',
        storage_backend: server.storage_backend === 'pgvector' ? 'lakebase' : (server.storage_backend || local.storage_backend || 'local'),
        lakebase_instance_name: server.lakebase_instance_name || local.lakebase_instance_name || '',
        lakebase_catalog: server.lakebase_catalog || local.lakebase_catalog || '',
        lakebase_schema: server.lakebase_schema || local.lakebase_schema || 'public',
        cache_table_name: server.cache_table_name || local.cache_table_name || 'cached_queries',
        query_log_table_name: server.query_log_table_name || local.query_log_table_name || 'query_logs',
      };
      localStorage.setItem('databricks_config', JSON.stringify(merged));
    }
  } catch { /* server unreachable — use whatever localStorage has */ }
};
_syncServerConfig();

const getConfig = () => {
  const savedConfig = localStorage.getItem('databricks_config');
  return savedConfig ? JSON.parse(savedConfig) : {};
};

// --- Multi-space helpers ---

const getActiveSpaceId = () => {
  const config = getConfig();
  const stored = localStorage.getItem('active_space_id');
  const spaces = config.genie_spaces || [];
  // If stored ID is still in the spaces list, use it
  if (stored && spaces.some(s => s.id === stored)) return stored;
  // Fallback: first space in list, or legacy single space
  if (spaces.length > 0) return spaces[0].id;
  return config.genie_space_id || '';
};

const setActiveSpaceId = (id) => {
  localStorage.setItem('active_space_id', id);
};

const getSpaceName = (spaceId) => {
  const config = getConfig();
  const spaces = config.genie_spaces || [];
  const found = spaces.find(s => s.id === spaceId);
  return found ? found.name : spaceId ? spaceId.substring(0, 8) + '...' : 'Unknown';
};

const isConfigValid = (config) => {
  const hasSpaces = (config.genie_spaces && config.genie_spaces.length > 0) || config.genie_space_id;
  return hasSpaces && config.sql_warehouse_id;
};

const computeTtlHours = (config) => {
  const val = parseFloat(config.cache_ttl_value) || 24;
  const unit = config.cache_ttl_unit || 'hours';
  if (val === 0) return 0;
  if (unit === 'minutes') return val / 60;
  if (unit === 'days') return val * 24;
  return val;
};

const withConfig = (data = {}) => {
  const config = getConfig();

  if (isConfigValid(config)) {
    // Use active space ID (from dropdown) as genie_space_id for this request
    const activeSpaceId = getActiveSpaceId();
    return {
      ...data,
      config: {
        auth_mode: config.auth_mode || 'app',
        user_pat: (config.user_pat && config.user_pat !== '••••••••') ? config.user_pat : undefined,
        storage_backend: config.storage_backend || 'local',
        genie_space_id: activeSpaceId,
        sql_warehouse_id: config.sql_warehouse_id,
        similarity_threshold: parseFloat(config.similarity_threshold) || 0.92,
        max_queries_per_minute: parseInt(config.max_queries_per_minute) || 5,
        cache_ttl_hours: computeTtlHours(config),
        embedding_provider: config.embedding_provider || 'databricks',
        databricks_embedding_endpoint: config.databricks_embedding_endpoint || 'databricks-bge-large-en',
        lakebase_instance_name: config.storage_backend === 'lakebase' ? config.lakebase_instance_name : undefined,
        lakebase_catalog: config.storage_backend === 'lakebase' ? config.lakebase_catalog : undefined,
        lakebase_schema: config.storage_backend === 'lakebase' ? config.lakebase_schema : undefined,
        cache_table_name: config.storage_backend === 'lakebase' ? config.cache_table_name : undefined,
        query_log_table_name: config.storage_backend === 'lakebase' ? config.query_log_table_name : undefined,
      }
    };
  }

  return data;
};

export const api = {
  submitQuery: async (query, identity, conversationContext = {}) => {
    const response = await axios.post(`${API_BASE_URL}/query`,
      withConfig({
        query,
        identity,
        conversation_id: conversationContext.conversationId || null,
        conversation_synced: conversationContext.conversationSynced ?? null,
        conversation_history: conversationContext.conversationHistory || null,
      })
    );
    return response.data;
  },

  getQueryStatus: async (queryId) => {
    const response = await axios.post(`${API_BASE_URL}/query/${queryId}/status`,
      withConfig({})
    );
    return response.data;
  },

  getCachedQueries: async (identity = null) => {
    const data = { identity: identity || null };
    const payload = withConfig(data);
    const response = await axios.post(`${API_BASE_URL}/cache`, payload);
    return response.data;
  },

  healthCheck: async () => {
    const response = await axios.get(`${API_BASE_URL}/health`);
    return response.data;
  },

  saveQueryLog: async (queryId, queryText, identity, stage, fromCache = false, genieSpaceId = null) => {
    try {
      const response = await axios.post(`${API_BASE_URL}/query-logs/save`, withConfig({
        query_id: queryId,
        query_text: queryText,
        identity,
        stage,
        from_cache: fromCache,
        genie_space_id: genieSpaceId
      }));
      return response.data;
    } catch {
      return { success: false };
    }
  },

  getQueryLogs: async (identity = null) => {
    try {
      const data = { identity: identity || null };
      const response = await axios.post(`${API_BASE_URL}/query-logs`, withConfig(data));
      return response.data;
    } catch {
      return [];
    }
  },

  getServerConfig: async () => {
    const response = await axios.get(`${API_BASE_URL}/config`);
    return response.data;
  },

  updateServerConfig: async (configUpdate) => {
    const response = await axios.put(`${API_BASE_URL}/config`, configUpdate);
    return response.data;
  },

  clearCache: async (spaceId = null) => {
    const url = spaceId
      ? `${API_BASE_URL}/cache?space_id=${encodeURIComponent(spaceId)}`
      : `${API_BASE_URL}/cache`;
    const response = await axios.delete(url);
    return response.data;
  },

  getCacheCount: async () => {
    const response = await axios.get(`${API_BASE_URL}/cache/count`);
    return response.data;
  },

  fetchSpaceInfo: async (spaceId) => {
    const response = await axios.get(`${API_BASE_URL}/space-info/${encodeURIComponent(spaceId)}`);
    return response.data;
  },

  getConfig: getConfig,
  getActiveSpaceId: getActiveSpaceId,
  setActiveSpaceId: setActiveSpaceId,
  getSpaceName: getSpaceName,
  computeTtlHours: computeTtlHours,
};
