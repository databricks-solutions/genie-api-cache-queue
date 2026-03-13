import { useState } from 'react';
import { Copy, Check, ChevronDown, ChevronRight } from 'lucide-react';

const ApiReference = () => {
  const [copied, setCopied] = useState(null);
  const [expandedSections, setExpandedSections] = useState({
    async: true,
    poll: true,
    sync: false,
    health: false,
    mgmt: false,
    python: false,
  });

  const baseUrl = window.location.origin;

  const getConfig = () => {
    const saved = localStorage.getItem('databricks_config');
    return saved ? JSON.parse(saved) : {};
  };

  const config = getConfig();
  const spaceId = config.genie_space_id || '<SPACE_ID>';
  const warehouseId = config.sql_warehouse_id || '<WAREHOUSE_ID>';

  const copyToClipboard = (text, id) => {
    navigator.clipboard.writeText(text);
    setCopied(id);
    setTimeout(() => setCopied(null), 2000);
  };

  const toggleSection = (key) => {
    setExpandedSections((prev) => ({ ...prev, [key]: !prev[key] }));
  };

  const CopyButton = ({ text, id }) => (
    <button
      onClick={() => copyToClipboard(text, id)}
      className="absolute top-2 right-2 p-1.5 rounded bg-gray-700 hover:bg-gray-600 transition-colors"
      title="Copy to clipboard"
    >
      {copied === id ? (
        <Check className="w-3.5 h-3.5 text-green-400" />
      ) : (
        <Copy className="w-3.5 h-3.5 text-gray-300" />
      )}
    </button>
  );

  const SectionHeader = ({ id, title, method, path }) => (
    <button
      onClick={() => toggleSection(id)}
      className="w-full flex items-center gap-3 text-left"
    >
      {expandedSections[id] ? (
        <ChevronDown className="w-4 h-4 text-gray-400 flex-shrink-0" />
      ) : (
        <ChevronRight className="w-4 h-4 text-gray-400 flex-shrink-0" />
      )}
      <div className="flex items-center gap-2">
        {method && (
          <span
            className={`text-xs font-bold px-2 py-0.5 rounded ${
              method === 'POST'
                ? 'bg-green-100 text-green-700'
                : 'bg-blue-100 text-blue-700'
            }`}
          >
            {method}
          </span>
        )}
        <code className="text-sm font-mono text-gray-900">{path}</code>
        <span className="text-sm text-gray-500">— {title}</span>
      </div>
    </button>
  );

  const curlAsync = `curl -X POST ${baseUrl}/api/v1/query \\
  -H "Authorization: Bearer \$DATABRICKS_TOKEN" \\
  -H "Content-Type: application/json" \\
  -d '{
    "query": "receita total por estado",
    "space_id": "${spaceId}",
    "warehouse_id": "${warehouseId}"
  }'`;

  const curlPoll = `curl ${baseUrl}/api/v1/query/<QUERY_ID> \\
  -H "Authorization: Bearer \$DATABRICKS_TOKEN"`;

  const curlSync = `curl -X POST ${baseUrl}/api/v1/query/sync \\
  -H "Authorization: Bearer \$DATABRICKS_TOKEN" \\
  -H "Content-Type: application/json" \\
  -d '{
    "query": "receita total por estado",
    "space_id": "${spaceId}",
    "warehouse_id": "${warehouseId}"
  }'`;

  const pythonExample = `import requests
import time

BASE_URL = "${baseUrl}/api/v1"
TOKEN = "dapi..."  # Your Databricks PAT or OAuth token

headers = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json",
}

# Option 1: Synchronous (blocks until result, max 120s)
response = requests.post(f"{BASE_URL}/query/sync", headers=headers, json={
    "query": "receita total por estado",
    "space_id": "${spaceId}",
    "warehouse_id": "${warehouseId}",
})
result = response.json()
print(result["sql_query"])
print(result["result"])

# Option 2: Async (submit + poll)
resp = requests.post(f"{BASE_URL}/query", headers=headers, json={
    "query": "receita total por estado",
    "space_id": "${spaceId}",
    "warehouse_id": "${warehouseId}",
})
query_id = resp.json()["query_id"]

while True:
    status = requests.get(f"{BASE_URL}/query/{query_id}", headers=headers).json()
    if status["status"] in ("completed", "failed", "timeout"):
        break
    time.sleep(2)

print(status)`;

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      {/* Header */}
      <div className="bg-white rounded-lg shadow-sm border">
        <div className="px-6 py-4 border-b">
          <h2 className="text-xl font-semibold text-gray-900">API Reference</h2>
          <p className="text-sm text-gray-500 mt-1">
            Use this REST API to query Genie with automatic caching, rate-limit management, and retry.
            Your application calls this API instead of the Genie API directly.
          </p>
        </div>

        <div className="p-6 space-y-4">
          {/* Base URL */}
          <div>
            <label className="block text-sm font-medium text-gray-500 mb-1">
              Base URL
            </label>
            <div className="flex items-center gap-2">
              <code className="flex-1 px-3 py-2 bg-gray-100 rounded-lg text-sm font-mono text-gray-900 border">
                {baseUrl}/api/v1
              </code>
              <button
                onClick={() => copyToClipboard(`${baseUrl}/api/v1`, 'base-url')}
                className="px-3 py-2 rounded-lg border hover:bg-gray-50 transition-colors"
              >
                {copied === 'base-url' ? (
                  <Check className="w-4 h-4 text-green-600" />
                ) : (
                  <Copy className="w-4 h-4 text-gray-500" />
                )}
              </button>
            </div>
          </div>

          {/* Auth info */}
          <div className="p-4 rounded-lg border bg-gray-200 border-gray-300">
            <p className="text-sm font-medium text-gray-900 mb-1">Authentication</p>
            <p className="text-xs text-gray-700">
              All endpoints require a <code className="bg-gray-300 px-1 rounded">Authorization: Bearer &lt;token&gt;</code> header
              with your Databricks PAT or OAuth token. The token is forwarded to the Genie API, preserving your data permissions.
            </p>
          </div>

          {/* Server defaults */}
          {config.genie_space_id && (
            <div className="p-3 rounded-lg bg-gray-100 border text-xs text-gray-600">
              <span className="font-medium">Server defaults:</span>{' '}
              space_id={config.genie_space_id}, warehouse_id={config.sql_warehouse_id || 'not set'}.
              These are used when not provided in the request body.
            </div>
          )}
        </div>
      </div>

      {/* Endpoints */}
      <div className="bg-white rounded-lg shadow-sm border divide-y">
        {/* POST /query (async) */}
        <div className="p-6 space-y-4">
          <SectionHeader
            id="async"
            title="Submit query (async)"
            method="POST"
            path="/query"
          />
          {expandedSections.async && (
            <div className="pl-7 space-y-3">
              <p className="text-sm text-gray-600">
                Submits a query and returns immediately with a <code className="bg-gray-100 px-1 rounded">query_id</code>.
                Poll <code className="bg-gray-100 px-1 rounded">GET /query/{'<query_id>'}</code> for results.
              </p>

              <div>
                <p className="text-xs font-medium text-gray-500 mb-1">Request Body</p>
                <div className="relative">
                  <pre className="bg-gray-900 text-gray-100 rounded-lg p-4 text-xs overflow-x-auto">
{`{
  "query": "receita total por estado",  // required
  "space_id": "01f0f168...",            // optional
  "warehouse_id": "4b9b953...",         // optional
  "identity": "user@example.com",      // optional
  "conversation_id": "..."             // optional (multi-turn)
}`}
                  </pre>
                </div>
              </div>

              <div>
                <p className="text-xs font-medium text-gray-500 mb-1">Response</p>
                <pre className="bg-gray-900 text-gray-100 rounded-lg p-4 text-xs overflow-x-auto">
{`{ "query_id": "uuid", "status": "received" }`}
                </pre>
              </div>

              <div>
                <p className="text-xs font-medium text-gray-500 mb-1">curl</p>
                <div className="relative">
                  <pre className="bg-gray-900 text-gray-100 rounded-lg p-4 text-xs overflow-x-auto pr-12">
                    {curlAsync}
                  </pre>
                  <CopyButton text={curlAsync} id="curl-async" />
                </div>
              </div>
            </div>
          )}
        </div>

        {/* GET /query/:id (poll) */}
        <div className="p-6 space-y-4">
          <SectionHeader
            id="poll"
            title="Poll query status"
            method="GET"
            path="/query/{query_id}"
          />
          {expandedSections.poll && (
            <div className="pl-7 space-y-3">
              <p className="text-sm text-gray-600">
                Returns the current status and result of a submitted query.
                Poll until <code className="bg-gray-100 px-1 rounded">status</code> is
                <code className="bg-green-100 text-green-700 px-1 rounded ml-1">completed</code> or
                <code className="bg-red-100 text-red-700 px-1 rounded ml-1">failed</code>.
              </p>

              <div>
                <p className="text-xs font-medium text-gray-500 mb-1">Response (completed)</p>
                <pre className="bg-gray-900 text-gray-100 rounded-lg p-4 text-xs overflow-x-auto">
{`{
  "query_id": "uuid",
  "status": "completed",
  "stage": "completed",
  "sql_query": "SELECT state, SUM(revenue) ...",
  "result": { "data_array": [...], "columns": [...] },
  "from_cache": true,
  "conversation_id": "..."
}`}
                </pre>
              </div>

              <div>
                <p className="text-xs font-medium text-gray-500 mb-1">Status values</p>
                <div className="grid grid-cols-2 gap-2 text-xs">
                  <div className="flex items-center gap-2">
                    <span className="w-2 h-2 rounded-full bg-blue-400"></span>
                    <code>processing</code> — query is being processed
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="w-2 h-2 rounded-full bg-yellow-400"></span>
                    <code>queued</code> — rate-limited, waiting in queue
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="w-2 h-2 rounded-full bg-green-400"></span>
                    <code>completed</code> — result ready
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="w-2 h-2 rounded-full bg-red-400"></span>
                    <code>failed</code> — query failed
                  </div>
                </div>
              </div>

              <div>
                <p className="text-xs font-medium text-gray-500 mb-1">curl</p>
                <div className="relative">
                  <pre className="bg-gray-900 text-gray-100 rounded-lg p-4 text-xs overflow-x-auto pr-12">
                    {curlPoll}
                  </pre>
                  <CopyButton text={curlPoll} id="curl-poll" />
                </div>
              </div>
            </div>
          )}
        </div>

        {/* POST /query/sync */}
        <div className="p-6 space-y-4">
          <SectionHeader
            id="sync"
            title="Submit query (synchronous)"
            method="POST"
            path="/query/sync"
          />
          {expandedSections.sync && (
            <div className="pl-7 space-y-3">
              <p className="text-sm text-gray-600">
                Same as <code className="bg-gray-100 px-1 rounded">POST /query</code> but blocks until the
                result is ready (max 120s timeout). No polling needed.
              </p>

              <div>
                <p className="text-xs font-medium text-gray-500 mb-1">curl</p>
                <div className="relative">
                  <pre className="bg-gray-900 text-gray-100 rounded-lg p-4 text-xs overflow-x-auto pr-12">
                    {curlSync}
                  </pre>
                  <CopyButton text={curlSync} id="curl-sync" />
                </div>
              </div>
            </div>
          )}
        </div>

        {/* GET /health */}
        <div className="p-6 space-y-4">
          <SectionHeader
            id="health"
            title="Health check (no auth required)"
            method="GET"
            path="/health"
          />
          {expandedSections.health && (
            <div className="pl-7">
              <pre className="bg-gray-900 text-gray-100 rounded-lg p-4 text-xs overflow-x-auto">
{`{ "status": "healthy", "service": "genie-cache-queue-api", "timestamp": "..." }`}
              </pre>
            </div>
          )}
        </div>
      </div>

      {/* Management Endpoints */}
      <div className="bg-white rounded-lg shadow-sm border divide-y">
        {/* GET /config */}
        <div className="p-6 space-y-4">
          <SectionHeader id="mgmt-config-get" title="Get server configuration" method="GET" path="/config" />
          {expandedSections['mgmt-config-get'] && (
            <div className="pl-7 space-y-3">
              <p className="text-sm text-gray-600">Returns the current server configuration including all tunable parameters.</p>
              <div>
                <p className="text-xs font-medium text-gray-500 mb-1">Response</p>
                <pre className="bg-gray-900 text-gray-100 rounded-lg p-4 text-xs overflow-x-auto">
{`{
  "genie_space_id": "01f0f168...",
  "sql_warehouse_id": "4b9b953...",
  "similarity_threshold": 0.92,
  "max_queries_per_minute": 5,
  "cache_ttl_hours": 24.0,
  "embedding_provider": "databricks",
  "storage_backend": "local",
  "shared_cache": true,
  "databricks_host": "workspace.cloud.databricks.com"
}`}
                </pre>
              </div>
            </div>
          )}
        </div>

        {/* PUT /config */}
        <div className="p-6 space-y-4">
          <SectionHeader id="mgmt-config-put" title="Update server configuration" method="PUT" path="/config" />
          {expandedSections['mgmt-config-put'] && (
            <div className="pl-7 space-y-3">
              <p className="text-sm text-gray-600">
                Update one or more configuration fields. Changes persist in memory for the app lifetime.
                Only send the fields you want to change.
              </p>
              <div>
                <p className="text-xs font-medium text-gray-500 mb-1">Request Body (all fields optional)</p>
                <pre className="bg-gray-900 text-gray-100 rounded-lg p-4 text-xs overflow-x-auto">
{`{
  "genie_space_id": "01f0f168...",       // Genie Space ID
  "sql_warehouse_id": "4b9b953...",      // SQL Warehouse ID
  "similarity_threshold": 0.95,          // Cache match threshold (0-1)
  "max_queries_per_minute": 5,           // Rate limit per workspace
  "cache_ttl_hours": 48,                 // Cache freshness (0 = no limit)
  "embedding_provider": "databricks",    // "databricks" or "local"
  "shared_cache": true                   // true = global, false = per-user
}`}
                </pre>
              </div>
              <div>
                <p className="text-xs font-medium text-gray-500 mb-1">Response</p>
                <pre className="bg-gray-900 text-gray-100 rounded-lg p-4 text-xs overflow-x-auto">
{`{
  "updated": { "similarity_threshold": 0.95, "cache_ttl_hours": 48 },
  "message": "Configuration updated successfully"
}`}
                </pre>
              </div>
              <div>
                <p className="text-xs font-medium text-gray-500 mb-1">curl</p>
                <div className="relative">
                  <pre className="bg-gray-900 text-gray-100 rounded-lg p-4 text-xs overflow-x-auto pr-12">
{`curl -X PUT ${baseUrl}/api/v1/config \\
  -H "Authorization: Bearer $DATABRICKS_TOKEN" \\
  -H "Content-Type: application/json" \\
  -d '{"similarity_threshold": 0.95, "cache_ttl_hours": 48}'`}
                  </pre>
                  <CopyButton text={`curl -X PUT ${baseUrl}/api/v1/config -H "Authorization: Bearer $DATABRICKS_TOKEN" -H "Content-Type: application/json" -d '{"similarity_threshold": 0.95, "cache_ttl_hours": 48}'`} id="curl-config" />
                </div>
              </div>
            </div>
          )}
        </div>

        {/* GET /cache */}
        <div className="p-6 space-y-4">
          <SectionHeader id="mgmt-cache" title="List cached queries" method="GET" path="/cache" />
          {expandedSections['mgmt-cache'] && (
            <div className="pl-7 space-y-3">
              <p className="text-sm text-gray-600">Returns all cached query entries with their SQL, similarity scores, and usage stats.</p>
              <div>
                <p className="text-xs font-medium text-gray-500 mb-1">Response</p>
                <pre className="bg-gray-900 text-gray-100 rounded-lg p-4 text-xs overflow-x-auto">
{`[
  {
    "id": 1,
    "query_text": "How many customers are there?",
    "sql_query": "SELECT COUNT(DISTINCT c_custkey) ...",
    "identity": "user@example.com",
    "genie_space_id": "01f0f168...",
    "created_at": "2026-03-13T20:00:00Z",
    "last_used": "2026-03-13T21:30:00Z",
    "use_count": 5,
    "similarity": null
  }
]`}
                </pre>
              </div>
            </div>
          )}
        </div>

        {/* GET /queue */}
        <div className="p-6 space-y-4">
          <SectionHeader id="mgmt-queue" title="List queued queries" method="GET" path="/queue" />
          {expandedSections['mgmt-queue'] && (
            <div className="pl-7 space-y-3">
              <p className="text-sm text-gray-600">Returns queries currently waiting in the rate-limit queue.</p>
              <div>
                <p className="text-xs font-medium text-gray-500 mb-1">Response</p>
                <pre className="bg-gray-900 text-gray-100 rounded-lg p-4 text-xs overflow-x-auto">
{`[
  {
    "query_id": "uuid",
    "query_text": "Total revenue by region",
    "identity": "user@example.com",
    "queued_at": "2026-03-13T21:00:00Z",
    "position": 1
  }
]`}
                </pre>
              </div>
            </div>
          )}
        </div>

        {/* GET /query-logs */}
        <div className="p-6 space-y-4">
          <SectionHeader id="mgmt-logs-get" title="List query logs (last 50)" method="GET" path="/query-logs" />
          {expandedSections['mgmt-logs-get'] && (
            <div className="pl-7 space-y-3">
              <p className="text-sm text-gray-600">Returns the most recent 50 query log entries.</p>
              <div>
                <p className="text-xs font-medium text-gray-500 mb-1">Response</p>
                <pre className="bg-gray-900 text-gray-100 rounded-lg p-4 text-xs overflow-x-auto">
{`[
  {
    "query_id": "uuid",
    "query_text": "How many customers?",
    "identity": "user@example.com",
    "stage": "completed",
    "from_cache": true,
    "genie_space_id": "01f0f168...",
    "created_at": "2026-03-13T21:00:00Z"
  }
]`}
                </pre>
              </div>
            </div>
          )}
        </div>

        {/* POST /query-logs */}
        <div className="p-6 space-y-4">
          <SectionHeader id="mgmt-logs-post" title="Save a query log entry" method="POST" path="/query-logs" />
          {expandedSections['mgmt-logs-post'] && (
            <div className="pl-7 space-y-3">
              <p className="text-sm text-gray-600">Manually save a query log entry for tracking.</p>
              <div>
                <p className="text-xs font-medium text-gray-500 mb-1">Request Body</p>
                <pre className="bg-gray-900 text-gray-100 rounded-lg p-4 text-xs overflow-x-auto">
{`{
  "query_id": "uuid",                    // required
  "query_text": "How many customers?",   // required
  "identity": "user@example.com",        // required
  "stage": "completed",                  // required
  "from_cache": true,                    // optional, default false
  "genie_space_id": "01f0f168..."        // optional
}`}
                </pre>
              </div>
              <div>
                <p className="text-xs font-medium text-gray-500 mb-1">Response</p>
                <pre className="bg-gray-900 text-gray-100 rounded-lg p-4 text-xs overflow-x-auto">
{`{ "success": true, "log_id": 42 }`}
                </pre>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Python Example */}
      <div className="bg-white rounded-lg shadow-sm border">
        <div className="p-6 space-y-4">
          <button
            onClick={() => toggleSection('python')}
            className="w-full flex items-center gap-3 text-left"
          >
            {expandedSections.python ? (
              <ChevronDown className="w-4 h-4 text-gray-400" />
            ) : (
              <ChevronRight className="w-4 h-4 text-gray-400" />
            )}
            <span className="text-sm font-medium text-gray-900">Python Example</span>
          </button>
          {expandedSections.python && (
            <div className="relative">
              <pre className="bg-gray-900 text-gray-100 rounded-lg p-4 text-xs overflow-x-auto pr-12">
                {pythonExample}
              </pre>
              <CopyButton text={pythonExample} id="python" />
            </div>
          )}
        </div>
      </div>

      {/* Drop-in Replacement */}
      <div className="bg-white rounded-lg shadow-sm border">
        <div className="p-6 space-y-4">
          <div>
            <h3 className="text-sm font-medium text-gray-900 mb-1">Drop-in Genie API Replacement</h3>
            <p className="text-xs text-gray-500">
              If your app already uses the Genie API, just change the base URL. Same endpoints, same payloads, same responses
              — with automatic caching, rate-limit management, and retry.
            </p>
          </div>

          <div className="p-3 rounded-lg bg-green-50 border border-green-200 text-xs">
            <span className="font-medium text-green-800">Before:</span>{' '}
            <code className="text-green-700">https://&lt;workspace&gt;.cloud.databricks.com/api/2.0/genie/...</code>
            <br />
            <span className="font-medium text-green-800">After:</span>{' '}
            <code className="text-green-700">{baseUrl}/api/2.0/genie/...</code>
          </div>

          <div className="text-xs space-y-2">
            <p className="font-medium text-gray-700">Compatible endpoints:</p>
            <div className="grid gap-1">
              <code className="bg-gray-100 px-2 py-1 rounded text-gray-700">POST /api/2.0/genie/spaces/{'<id>'}/start-conversation</code>
              <code className="bg-gray-100 px-2 py-1 rounded text-gray-700">POST /api/2.0/genie/spaces/{'<id>'}/conversations/{'<cid>'}/messages</code>
              <code className="bg-gray-100 px-2 py-1 rounded text-gray-700">GET&nbsp; /api/2.0/genie/spaces/{'<id>'}/conversations/{'<cid>'}/messages/{'<mid>'}</code>
              <code className="bg-gray-100 px-2 py-1 rounded text-gray-700">GET&nbsp; ...messages/{'<mid>'}/attachments/{'<aid>'}/query-result</code>
              <code className="bg-gray-100 px-2 py-1 rounded text-gray-700">POST ...messages/{'<mid>'}/attachments/{'<aid>'}/execute-query</code>
            </div>
          </div>

          <div>
            <p className="text-xs font-medium text-gray-500 mb-1">Example</p>
            <div className="relative">
              <pre className="bg-gray-900 text-gray-100 rounded-lg p-4 text-xs overflow-x-auto pr-12">
{`curl -X POST ${baseUrl}/api/2.0/genie/spaces/${spaceId}/start-conversation \\
  -H "Authorization: Bearer $DATABRICKS_TOKEN" \\
  -H "Content-Type: application/json" \\
  -d '{"content": "How many customers are there?"}'`}
              </pre>
              <CopyButton text={`curl -X POST ${baseUrl}/api/2.0/genie/spaces/${spaceId}/start-conversation -H "Authorization: Bearer $DATABRICKS_TOKEN" -H "Content-Type: application/json" -d '{"content": "How many customers are there?"}'`} id="curl-genie-clone" />
            </div>
          </div>
        </div>
      </div>

      {/* How it works */}
      <div className="bg-white rounded-lg shadow-sm border p-6">
        <h3 className="text-sm font-medium text-gray-900 mb-3">How it works</h3>
        <div className="space-y-2 text-xs text-gray-600">
          <div className="flex items-start gap-2">
            <span className="font-mono text-gray-400 w-4 text-right flex-shrink-0">1.</span>
            <span>Your app sends a query to this API with a Bearer token.</span>
          </div>
          <div className="flex items-start gap-2">
            <span className="font-mono text-gray-400 w-4 text-right flex-shrink-0">2.</span>
            <span>The app checks the vector cache (Lakebase/pgvector) for a semantically similar previous query.</span>
          </div>
          <div className="flex items-start gap-2">
            <span className="font-mono text-gray-400 w-4 text-right flex-shrink-0">3.</span>
            <span><strong>Cache hit:</strong> returns the cached SQL immediately, executes it, and returns results.</span>
          </div>
          <div className="flex items-start gap-2">
            <span className="font-mono text-gray-400 w-4 text-right flex-shrink-0">4.</span>
            <span><strong>Cache miss:</strong> calls the Genie API using your token, respecting the 5/min rate limit.</span>
          </div>
          <div className="flex items-start gap-2">
            <span className="font-mono text-gray-400 w-4 text-right flex-shrink-0">5.</span>
            <span><strong>Rate-limited:</strong> the query is queued and retried automatically (up to 3 retries with backoff).</span>
          </div>
          <div className="flex items-start gap-2">
            <span className="font-mono text-gray-400 w-4 text-right flex-shrink-0">6.</span>
            <span>The result and SQL are cached for future similar queries.</span>
          </div>
        </div>
      </div>
    </div>
  );
};

export default ApiReference;
