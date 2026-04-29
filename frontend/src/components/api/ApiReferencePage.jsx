import { useState } from 'react'
import { Copy, Check, ChevronDown, ChevronRight } from 'lucide-react'

export default function ApiReferencePage() {
  const [copied, setCopied] = useState(null)
  const [expandedSections, setExpandedSections] = useState({
    genie: true,
    proxy: false,
    gateway: false,
    router: false,
  })
  const [expandedEndpoints, setExpandedEndpoints] = useState({
    'clone-start': true,
    'clone-poll': false,
    'clone-result': false,
    'clone-execute': false,
    'clone-space': false,
    'proxy-async': false,
    'proxy-poll': false,
    'proxy-sync': false,
    'gw-list': false,
    'gw-create': false,
    'gw-get': false,
    'gw-update': false,
    'gw-delete': false,
    'gw-spaces': false,
    'gw-warehouses': false,
    'rt-list': false,
    'rt-create': false,
    'rt-get': false,
    'rt-update': false,
    'rt-delete': false,
    'rt-member-add': false,
    'rt-member-update': false,
    'rt-member-delete': false,
    'rt-cache-flush': false,
    'rt-preview': false,
    'rt-query': false,
  })

  const baseUrl = window.location.origin

  const copyToClipboard = (text, id) => {
    navigator.clipboard.writeText(text)
    setCopied(id)
    setTimeout(() => setCopied(null), 2000)
  }

  const toggleSection = (key) => {
    setExpandedSections(prev => ({ ...prev, [key]: !prev[key] }))
  }

  const toggleEndpoint = (key) => {
    setExpandedEndpoints(prev => ({ ...prev, [key]: !prev[key] }))
  }

  const CopyButton = ({ text, id }) => (
    <button
      onClick={() => copyToClipboard(text, id)}
      className="absolute top-2 right-2 p-1 rounded bg-dbx-border hover:bg-dbx-border-input transition-colors"
      title="Copy to clipboard"
    >
      {copied === id ? <Check className="w-3 h-3 text-green-600" /> : <Copy className="w-3 h-3 text-dbx-text-secondary" />}
    </button>
  )

  const MethodBadge = ({ method }) => {
    const colors = {
      GET: 'bg-green-100 text-green-700',
      POST: 'bg-blue-100 text-blue-700',
      PUT: 'bg-orange-100 text-orange-700',
      DELETE: 'bg-red-100 text-red-700',
    }
    return (
      <span className={`text-[11px] font-medium px-1.5 py-0.5 rounded ${colors[method] || 'bg-gray-100 text-gray-700'}`}>
        {method}
      </span>
    )
  }

  const EndpointRow = ({ id, method, path, description, children }) => (
    <div className="border-t border-dbx-border">
      <button
        onClick={() => toggleEndpoint(id)}
        className="w-full flex items-center gap-2.5 px-4 py-3 text-left hover:bg-dbx-neutral-hover transition-colors"
      >
        {expandedEndpoints[id]
          ? <ChevronDown className="w-3.5 h-3.5 text-dbx-text-secondary flex-shrink-0" />
          : <ChevronRight className="w-3.5 h-3.5 text-dbx-text-secondary flex-shrink-0" />}
        <MethodBadge method={method} />
        <code className="text-[12px] font-mono text-dbx-text">{path}</code>
        <span className="text-[12px] text-dbx-text-secondary">-- {description}</span>
      </button>
      {expandedEndpoints[id] && (
        <div className="px-4 pb-4 pl-10 space-y-3">
          {children}
        </div>
      )}
    </div>
  )

  const CodeBlock = ({ code, id }) => (
    <div className="relative">
      <pre className="bg-dbx-sidebar rounded p-3 text-[12px] font-mono text-dbx-text overflow-x-auto leading-relaxed whitespace-pre-wrap">
        {code}
      </pre>
      <CopyButton text={code} id={id} />
    </div>
  )

  return (
    <div className="p-6 max-w-4xl">
      <h1 className="text-[22px] font-medium text-dbx-text">API Reference</h1>
      <p className="text-[13px] text-dbx-text-secondary mt-1 mb-6">Use these APIs to integrate with the Genie Cache Gateway</p>

      {/* Auth note */}
      <div className="bg-dbx-sidebar border border-dbx-border rounded p-3 mb-6">
        <p className="text-[13px] text-dbx-text">
          <span className="font-medium">Authentication:</span> All endpoints require{' '}
          <code className="bg-dbx-bg px-1 py-0.5 rounded border border-dbx-border text-[12px]">Authorization: Bearer &lt;token&gt;</code>{' '}
          (OAuth JWT or PAT).
        </p>
      </div>

      {/* Section 1: Drop-in Genie API */}
      <div className="bg-dbx-bg border border-dbx-border rounded overflow-hidden mb-4">
        <button
          onClick={() => toggleSection('genie')}
          className="w-full flex items-center gap-2.5 px-4 py-3 text-left hover:bg-dbx-neutral-hover transition-colors"
        >
          {expandedSections.genie
            ? <ChevronDown className="w-4 h-4 text-dbx-text-secondary" />
            : <ChevronRight className="w-4 h-4 text-dbx-text-secondary" />}
          <h2 className="text-[14px] font-medium text-dbx-text">Drop-in Genie API</h2>
          <span className="text-[12px] text-dbx-text-secondary">-- Same endpoints as the official Genie API. Just change the base URL.</span>
        </button>

        {expandedSections.genie && (
          <div>
            <div className="px-4 pb-3 border-t border-dbx-border pt-3 space-y-3">
              <div className="bg-dbx-sidebar rounded p-3 text-[12px]">
                <p className="text-dbx-text-secondary">
                  <span className="font-medium text-dbx-text">Before:</span>{' '}
                  <code>https://&lt;workspace&gt;.cloud.databricks.com</code>
                </p>
                <p className="text-dbx-text-secondary">
                  <span className="font-medium text-dbx-text">After:</span>{' '}
                  <code>{baseUrl}</code>
                </p>
              </div>
              <p className="text-[13px] text-dbx-text-secondary">
                Use your <strong className="text-dbx-text">Gateway ID</strong> (UUID from the Gateways list) in place of{' '}
                <code className="bg-dbx-sidebar px-1 rounded text-[12px]">{'{gateway_id}'}</code>. The gateway resolves the real Genie Space ID internally.
              </p>
            </div>

            <EndpointRow
              id="clone-start"
              method="POST"
              path="/api/2.0/genie/spaces/{gateway_id}/start-conversation"
              description="Start conversation"
            >
              <p className="text-[13px] text-dbx-text-secondary">
                Cache hit returns <code className="bg-green-50 text-green-700 px-1 rounded text-[12px]">COMPLETED</code> with executed SQL.
                Cache miss returns <code className="bg-blue-50 text-blue-700 px-1 rounded text-[12px]">EXECUTING_QUERY</code> — poll the get-message endpoint until done.
              </p>
              <div>
                <p className="text-[12px] font-medium text-dbx-text-secondary mb-1">Request Body</p>
                <CodeBlock id="body-start" code={`{ "content": "How many sales per month?" }`} />
              </div>
              <div>
                <p className="text-[12px] font-medium text-dbx-text-secondary mb-1">Response (cache miss)</p>
                <CodeBlock id="resp-start" code={`{
  "conversation_id": "ccache_...",
  "message_id": "mcache_...",
  "status": "EXECUTING_QUERY",
  "attachments": []
}`} />
              </div>
              <div>
                <p className="text-[12px] font-medium text-dbx-text-secondary mb-1">curl</p>
                <CodeBlock id="curl-start" code={`curl -X POST ${baseUrl}/api/2.0/genie/spaces/<GATEWAY_ID>/start-conversation \\
  -H "Authorization: Bearer $TOKEN" \\
  -H "Content-Type: application/json" \\
  -d '{"content": "How many sales per month?"}'`} />
              </div>
            </EndpointRow>

            <EndpointRow
              id="clone-poll"
              method="GET"
              path="/api/2.0/genie/spaces/{gateway_id}/conversations/{conv_id}/messages/{msg_id}"
              description="Poll result (get-message)"
            >
              <p className="text-[13px] text-dbx-text-secondary">
                Poll every 2s until <code className="bg-green-50 text-green-700 px-1 rounded text-[12px]">COMPLETED</code> or{' '}
                <code className="bg-red-50 text-red-700 px-1 rounded text-[12px]">FAILED</code>.
                Use the <code className="bg-dbx-sidebar px-1 rounded text-[12px]">conversation_id</code> and <code className="bg-dbx-sidebar px-1 rounded text-[12px]">message_id</code> from the start-conversation response.
              </p>
              <div>
                <p className="text-[12px] font-medium text-dbx-text-secondary mb-1">Response (completed)</p>
                <CodeBlock id="resp-poll" code={`{
  "conversation_id": "...",
  "message_id": "...",
  "status": "COMPLETED",
  "attachments": [
    {
      "attachment_id": "...",
      "query": {
        "query": "SELECT DATE_TRUNC('MONTH', ...) AS month, COUNT(*) ...",
        "description": "Monthly sales count"
      }
    }
  ]
}`} />
              </div>
            </EndpointRow>

            <EndpointRow
              id="clone-result"
              method="GET"
              path=".../messages/{msg_id}/attachments/{att_id}/query-result"
              description="Get query result data"
            >
              <p className="text-[13px] text-dbx-text-secondary">
                Returns the actual SQL execution results. Format identical to the Genie API (<code className="bg-dbx-sidebar px-1 rounded text-[12px]">statement_response</code>).
              </p>
              <div>
                <p className="text-[12px] font-medium text-dbx-text-secondary mb-1">Response</p>
                <CodeBlock id="resp-result" code={`{
  "statement_response": {
    "statement_id": "...",
    "status": "SUCCEEDED",
    "result": {
      "row_count": 12,
      "data_array": [
        ["2024-01-01T00:00:00.000Z", "10867"],
        ["2024-02-01T00:00:00.000Z", "11065"]
      ]
    }
  }
}`} />
              </div>
            </EndpointRow>

            <EndpointRow
              id="clone-execute"
              method="POST"
              path=".../messages/{msg_id}/attachments/{att_id}/execute-query"
              description="Re-execute query"
            >
              <p className="text-[13px] text-dbx-text-secondary">Re-executes the cached SQL against the warehouse. Same response format as query-result.</p>
            </EndpointRow>

            <EndpointRow
              id="clone-space"
              method="GET"
              path="/api/2.0/genie/spaces/{gateway_id}"
              description="Get gateway/space metadata"
            >
              <p className="text-[13px] text-dbx-text-secondary">Resolves the gateway and proxies to the real Genie API. Returns space metadata.</p>
            </EndpointRow>
          </div>
        )}
      </div>

      {/* Section 2: Proxy API */}
      <div className="bg-dbx-bg border border-dbx-border rounded overflow-hidden mb-4">
        <button
          onClick={() => toggleSection('proxy')}
          className="w-full flex items-center gap-2.5 px-4 py-3 text-left hover:bg-dbx-neutral-hover transition-colors"
        >
          {expandedSections.proxy
            ? <ChevronDown className="w-4 h-4 text-dbx-text-secondary" />
            : <ChevronRight className="w-4 h-4 text-dbx-text-secondary" />}
          <h2 className="text-[14px] font-medium text-dbx-text">Proxy API</h2>
          <span className="text-[12px] text-dbx-text-secondary">-- Simplified REST API for apps that don't use the Genie API directly.</span>
        </button>

        {expandedSections.proxy && (
          <div>
            <EndpointRow
              id="proxy-async"
              method="POST"
              path="/api/v1/query"
              description="Submit query (async)"
            >
              <p className="text-[13px] text-dbx-text-secondary">
                Returns <code className="bg-dbx-sidebar px-1 rounded text-[12px]">query_id</code>.
                Poll <code className="bg-dbx-sidebar px-1 rounded text-[12px]">GET /api/v1/query/{'{query_id}'}</code> for result.
              </p>
              <div>
                <p className="text-[12px] font-medium text-dbx-text-secondary mb-1">curl</p>
                <CodeBlock id="curl-proxy-async" code={`curl -X POST ${baseUrl}/api/v1/query \\
  -H "Authorization: Bearer $TOKEN" \\
  -H "Content-Type: application/json" \\
  -d '{"query": "How many sales per month?", "space_id": "<GATEWAY_ID>"}'`} />
              </div>
            </EndpointRow>

            <EndpointRow
              id="proxy-poll"
              method="GET"
              path="/api/v1/query/{query_id}"
              description="Poll query status"
            >
              <p className="text-[13px] text-dbx-text-secondary">
                Poll until <code className="bg-green-50 text-green-700 px-1 rounded text-[12px]">completed</code> or{' '}
                <code className="bg-red-50 text-red-700 px-1 rounded text-[12px]">failed</code>.
              </p>
            </EndpointRow>

            <EndpointRow
              id="proxy-sync"
              method="POST"
              path="/api/v1/query/sync"
              description="Synchronous query (blocks up to 120s)"
            >
              <p className="text-[13px] text-dbx-text-secondary">Same as POST /query but blocks until the result is ready.</p>
            </EndpointRow>
          </div>
        )}
      </div>

      {/* Section 3: Gateway Management API */}
      <div className="bg-dbx-bg border border-dbx-border rounded overflow-hidden mb-4">
        <button
          onClick={() => toggleSection('gateway')}
          className="w-full flex items-center gap-2.5 px-4 py-3 text-left hover:bg-dbx-neutral-hover transition-colors"
        >
          {expandedSections.gateway
            ? <ChevronDown className="w-4 h-4 text-dbx-text-secondary" />
            : <ChevronRight className="w-4 h-4 text-dbx-text-secondary" />}
          <h2 className="text-[14px] font-medium text-dbx-text">Gateway Management</h2>
          <span className="text-[12px] text-dbx-text-secondary">-- CRUD operations for gateways and workspace discovery.</span>
        </button>

        {expandedSections.gateway && (
          <div>
            <EndpointRow
              id="gw-list"
              method="GET"
              path="/api/gateways"
              description="List all gateways"
            >
              <p className="text-[13px] text-dbx-text-secondary">Returns an array of all configured gateways with their settings and metrics.</p>
              <div>
                <p className="text-[12px] font-medium text-dbx-text-secondary mb-1">curl</p>
                <CodeBlock id="curl-gw-list" code={`curl ${baseUrl}/api/gateways \\
  -H "Authorization: Bearer $TOKEN"`} />
              </div>
            </EndpointRow>

            <EndpointRow
              id="gw-create"
              method="POST"
              path="/api/gateways"
              description="Create a new gateway"
            >
              <p className="text-[13px] text-dbx-text-secondary">Creates a new gateway with a Genie Space and SQL Warehouse.</p>
              <div>
                <p className="text-[12px] font-medium text-dbx-text-secondary mb-1">Request Body</p>
                <CodeBlock id="body-gw-create" code={`{
  "name": "My Gateway",
  "genie_space_id": "<GENIE_SPACE_ID>",
  "sql_warehouse_id": "<WAREHOUSE_ID>",
  "similarity_threshold": 0.92,
  "cache_ttl_hours": 24,
  "max_queries_per_minute": 5,
  "question_normalization_enabled": true,
  "cache_validation_enabled": true
}`} />
              </div>
            </EndpointRow>

            <EndpointRow
              id="gw-get"
              method="GET"
              path="/api/gateways/{id}"
              description="Get gateway details"
            >
              <p className="text-[13px] text-dbx-text-secondary">Returns full configuration and metrics for a specific gateway.</p>
            </EndpointRow>

            <EndpointRow
              id="gw-update"
              method="PUT"
              path="/api/gateways/{id}"
              description="Update gateway settings"
            >
              <p className="text-[13px] text-dbx-text-secondary">Partial update -- send only the fields you want to change.</p>
              <div>
                <p className="text-[12px] font-medium text-dbx-text-secondary mb-1">Request Body</p>
                <CodeBlock id="body-gw-update" code={`{
  "similarity_threshold": 0.95,
  "cache_ttl_seconds": 172800
}`} />
              </div>
            </EndpointRow>

            <EndpointRow
              id="gw-delete"
              method="DELETE"
              path="/api/gateways/{id}"
              description="Delete a gateway"
            >
              <p className="text-[13px] text-dbx-text-secondary">Permanently deletes the gateway and its cache entries.</p>
            </EndpointRow>

            <EndpointRow
              id="gw-spaces"
              method="GET"
              path="/api/workspace/genie-spaces"
              description="List available Genie Spaces"
            >
              <p className="text-[13px] text-dbx-text-secondary">Queries the workspace for all Genie Spaces accessible to the current user or service principal.</p>
              <div>
                <p className="text-[12px] font-medium text-dbx-text-secondary mb-1">curl</p>
                <CodeBlock id="curl-gw-spaces" code={`curl ${baseUrl}/api/workspace/genie-spaces \\
  -H "Authorization: Bearer $TOKEN"`} />
              </div>
            </EndpointRow>

            <EndpointRow
              id="gw-warehouses"
              method="GET"
              path="/api/workspace/warehouses"
              description="List available SQL Warehouses"
            >
              <p className="text-[13px] text-dbx-text-secondary">Returns all SQL warehouses in the workspace.</p>
              <div>
                <p className="text-[12px] font-medium text-dbx-text-secondary mb-1">curl</p>
                <CodeBlock id="curl-gw-warehouses" code={`curl ${baseUrl}/api/workspace/warehouses \\
  -H "Authorization: Bearer $TOKEN"`} />
              </div>
            </EndpointRow>
          </div>
        )}
      </div>

      {/* Section 4: Routers */}
      <div className="bg-dbx-bg border border-dbx-border rounded overflow-hidden mb-4">
        <button
          onClick={() => toggleSection('router')}
          className="w-full flex items-center gap-2.5 px-4 py-3 text-left hover:bg-dbx-neutral-hover transition-colors"
        >
          {expandedSections.router
            ? <ChevronDown className="w-4 h-4 text-dbx-text-secondary" />
            : <ChevronRight className="w-4 h-4 text-dbx-text-secondary" />}
          <h2 className="text-[14px] font-medium text-dbx-text">Routers</h2>
          <span className="text-[12px] text-dbx-text-secondary">-- Group several gateways under one endpoint with a selector LLM that picks (and decomposes across) the right members.</span>
        </button>

        {expandedSections.router && (
          <div>
            <div className="px-4 pb-3 border-t border-dbx-border pt-3">
              <p className="text-[13px] text-dbx-text-secondary">
                Base path: <code className="bg-dbx-sidebar px-1 rounded text-[12px]">/api/v1</code>. Catalog metadata
                (<code>when_to_use</code>, <code>tables</code>, <code>sample_questions</code>) lives on each member edge,
                so the same gateway can be enrolled in multiple routers with different routing hints.
              </p>
            </div>

            <EndpointRow
              id="rt-list"
              method="GET"
              path="/api/v1/routers"
              description="List all routers"
            >
              <p className="text-[13px] text-dbx-text-secondary">Returns all routers (members not hydrated). Requires the <code className="bg-dbx-sidebar px-1 rounded text-[12px]">use</code> role.</p>
              <div>
                <p className="text-[12px] font-medium text-dbx-text-secondary mb-1">curl</p>
                <CodeBlock id="curl-rt-list" code={`curl ${baseUrl}/api/v1/routers \\
  -H "Authorization: Bearer $TOKEN"`} />
              </div>
            </EndpointRow>

            <EndpointRow
              id="rt-create"
              method="POST"
              path="/api/v1/routers"
              description="Create a router"
            >
              <p className="text-[13px] text-dbx-text-secondary">Owner role required. Optionally seed initial members in the same call.</p>
              <div>
                <p className="text-[12px] font-medium text-dbx-text-secondary mb-1">Request Body</p>
                <CodeBlock id="body-rt-create" code={`{
  "name": "Operations Router",
  "description": "Routes operations questions across finance + logistics",
  "selector_model": "databricks-claude-haiku-4-5",
  "decompose_enabled": true,
  "routing_cache_enabled": true,
  "similarity_threshold": 0.92,
  "cache_ttl_hours": 24,
  "mlflow_experiment_path": "/Users/me/router-traces",
  "members": [
    { "gateway_id": "<UUID>", "title": "Finance",   "when_to_use": "..." },
    { "gateway_id": "<UUID>", "title": "Logistics", "when_to_use": "..." }
  ]
}`} />
              </div>
            </EndpointRow>

            <EndpointRow
              id="rt-get"
              method="GET"
              path="/api/v1/routers/{router_id}"
              description="Get a router with members"
            >
              <p className="text-[13px] text-dbx-text-secondary">Members are hydrated with their full catalog metadata.</p>
            </EndpointRow>

            <EndpointRow
              id="rt-update"
              method="PUT"
              path="/api/v1/routers/{router_id}"
              description="Update router settings"
            >
              <p className="text-[13px] text-dbx-text-secondary">Manage role required. Partial update -- send only the fields you want to change. Send <code className="bg-dbx-sidebar px-1 rounded text-[12px]">"mlflow_experiment_path": null</code> to disable tracing for this router.</p>
            </EndpointRow>

            <EndpointRow
              id="rt-delete"
              method="DELETE"
              path="/api/v1/routers/{router_id}"
              description="Delete a router"
            >
              <p className="text-[13px] text-dbx-text-secondary">Owner role required. Cascades to members and routing cache.</p>
            </EndpointRow>

            <EndpointRow
              id="rt-member-add"
              method="POST"
              path="/api/v1/routers/{router_id}/members"
              description="Add a gateway as a member"
            >
              <div>
                <p className="text-[12px] font-medium text-dbx-text-secondary mb-1">Request Body</p>
                <CodeBlock id="body-rt-member-add" code={`{
  "gateway_id": "<UUID>",
  "title": "R5 -- Disbursements & Execution",
  "when_to_use": "Use for project-level cashflow and execution health...",
  "tables": ["mv_disbursement_execution", "fact_disbursement"],
  "sample_questions": ["Top 5 problem projects by disbursement ratio?"],
  "ordinal": 5
}`} />
              </div>
            </EndpointRow>

            <EndpointRow
              id="rt-member-update"
              method="PUT"
              path="/api/v1/routers/{router_id}/members/{gateway_id}"
              description="Update member catalog metadata"
            >
              <p className="text-[13px] text-dbx-text-secondary">Edit <code>when_to_use</code>, sample questions, or table list without touching the gateway itself.</p>
            </EndpointRow>

            <EndpointRow
              id="rt-member-delete"
              method="DELETE"
              path="/api/v1/routers/{router_id}/members/{gateway_id}"
              description="Remove a member"
            />

            <EndpointRow
              id="rt-cache-flush"
              method="DELETE"
              path="/api/v1/routers/{router_id}/cache"
              description="Flush the routing cache"
            >
              <p className="text-[13px] text-dbx-text-secondary">Drops all <code>(question_embedding → decision)</code> rows for this router. Use after editing <code>when_to_use</code> hints so the selector re-evaluates.</p>
            </EndpointRow>

            <EndpointRow
              id="rt-preview"
              method="POST"
              path="/api/v1/routers/{router_id}/preview"
              description="Preview routing decision (no dispatch)"
            >
              <p className="text-[13px] text-dbx-text-secondary">Runs the selector and returns the routing decision without spending warehouse time. Used by the Preview tab when iterating on catalog metadata.</p>
              <div>
                <p className="text-[12px] font-medium text-dbx-text-secondary mb-1">Request Body</p>
                <CodeBlock id="body-rt-preview" code={`{
  "question": "Compare disbursement velocity to ISR ratings by region.",
  "hints": []
}`} />
              </div>
            </EndpointRow>

            <EndpointRow
              id="rt-query"
              method="POST"
              path="/api/v1/routers/{router_id}/query"
              description="Decompose, select, dispatch (DAG)"
            >
              <p className="text-[13px] text-dbx-text-secondary">
                Runs the full pipeline: routing-cache lookup → selector LLM (with optional decomposition) → topological
                dispatch across member gateways → upstream-result binding into dependent sub-questions → merged
                per-source response. Blocks until the DAG finishes.
              </p>
              <div>
                <p className="text-[12px] font-medium text-dbx-text-secondary mb-1">Request Body</p>
                <CodeBlock id="body-rt-query" code={`{
  "question": "Which donors funded climate-themed trust funds, and what projects did those fund?",
  "hints": []
}`} />
              </div>
              <div>
                <p className="text-[12px] font-medium text-dbx-text-secondary mb-1">Response</p>
                <CodeBlock id="resp-rt-query" code={`{
  "router_id": "...",
  "question": "...",
  "routing": {
    "picks": [
      { "id": "p0", "gateway_id": "...", "sub_question": "...", "depends_on": [] },
      { "id": "p1", "gateway_id": "...", "sub_question": "...for donors {{p0.donor_id}}",
        "depends_on": ["p0"], "bind": [{ "placeholder": "p0.donor_id", "upstream": "p0", "column": "donor_id", "reducer": "list" }] }
    ],
    "decomposed": true,
    "rationale": "..."
  },
  "diagnostics": { "cache_hit": false, "selector_ms": 812, "n_stages": 2 },
  "sources": [
    { "pick_id": "p0", "status": "COMPLETED", "response": { "attachments": [...] }, "elapsed_ms": 4321 },
    { "pick_id": "p1", "status": "COMPLETED", "response": { "attachments": [...] }, "elapsed_ms": 5102 }
  ],
  "elapsed_ms": 9876,
  "trace_id": "tr-..."
}`} />
              </div>
            </EndpointRow>
          </div>
        )}
      </div>

      {/* How it works */}
      <div className="bg-dbx-bg border border-dbx-border rounded p-4">
        <h3 className="text-[14px] font-medium text-dbx-text mb-3">How It Works</h3>
        <div className="space-y-1.5 text-[13px] text-dbx-text-secondary">
          <div className="flex items-start gap-2"><span className="font-mono text-dbx-border-input w-4 text-right flex-shrink-0">1.</span><span>App sends query with Bearer token.</span></div>
          <div className="flex items-start gap-2"><span className="font-mono text-dbx-border-input w-4 text-right flex-shrink-0">2.</span><span>Semantic cache search (Lakebase/pgvector) for similar query.</span></div>
          <div className="flex items-start gap-2"><span className="font-mono text-dbx-border-input w-4 text-right flex-shrink-0">3.</span><span><strong className="text-dbx-text">Cache hit:</strong> executes cached SQL on warehouse, returns fresh data.</span></div>
          <div className="flex items-start gap-2"><span className="font-mono text-dbx-border-input w-4 text-right flex-shrink-0">4.</span><span><strong className="text-dbx-text">Cache miss:</strong> calls the Genie API respecting the rate limit.</span></div>
          <div className="flex items-start gap-2"><span className="font-mono text-dbx-border-input w-4 text-right flex-shrink-0">5.</span><span><strong className="text-dbx-text">Rate limit:</strong> query enters queue with automatic retry.</span></div>
          <div className="flex items-start gap-2"><span className="font-mono text-dbx-border-input w-4 text-right flex-shrink-0">6.</span><span>Result and SQL are cached for future similar queries.</span></div>
        </div>
      </div>
    </div>
  )
}
