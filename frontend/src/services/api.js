import axios from 'axios';

const API_BASE_URL = '/api';

const getConfig = () => {
  const savedConfig = localStorage.getItem('databricks_config');
  return savedConfig ? JSON.parse(savedConfig) : {};
};

const isConfigValid = (config) => {
  return config.genie_space_id && config.sql_warehouse_id;
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
    return {
      ...data,
      config: {
        auth_mode: config.auth_mode || 'app',
        user_pat: config.user_pat || undefined,
        storage_backend: config.storage_backend || 'local',
        genie_space_id: config.genie_space_id,
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

  getConfig: getConfig,
  computeTtlHours: computeTtlHours,
};
