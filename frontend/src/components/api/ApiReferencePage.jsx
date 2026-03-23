import { useState } from 'react'
import { Copy, Check, ChevronDown, ChevronRight } from 'lucide-react'

export default function ApiReferencePage() {
  const [copied, setCopied] = useState(null)
  const [expandedSections, setExpandedSections] = useState({
    genie: true,
    proxy: false,
    gateway: false,
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
      className="absolute top-2 right-2 p-1 rounded bg-[#EBEBEB] hover:bg-[#CBCBCB] transition-colors"
      title="Copy to clipboard"
    >
      {copied === id ? <Check className="w-3 h-3 text-green-600" /> : <Copy className="w-3 h-3 text-[#6F6F6F]" />}
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
    <div className="border-t border-[#EBEBEB]">
      <button
        onClick={() => toggleEndpoint(id)}
        className="w-full flex items-center gap-2.5 px-4 py-3 text-left hover:bg-[#FAFAFA] transition-colors"
      >
        {expandedEndpoints[id]
          ? <ChevronDown className="w-3.5 h-3.5 text-[#6F6F6F] flex-shrink-0" />
          : <ChevronRight className="w-3.5 h-3.5 text-[#6F6F6F] flex-shrink-0" />}
        <MethodBadge method={method} />
        <code className="text-[12px] font-mono text-[#161616]">{path}</code>
        <span className="text-[12px] text-[#6F6F6F]">-- {description}</span>
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
      <pre className="bg-[#F7F7F7] rounded p-3 text-[12px] font-mono text-[#161616] overflow-x-auto leading-relaxed whitespace-pre-wrap">
        {code}
      </pre>
      <CopyButton text={code} id={id} />
    </div>
  )

  return (
    <div className="p-6 max-w-4xl">
      <h1 className="text-[22px] font-medium text-[#161616]">API Reference</h1>
      <p className="text-[13px] text-[#6F6F6F] mt-1 mb-6">Use these APIs to integrate with the Genie Cache Gateway</p>

      {/* Auth note */}
      <div className="bg-[#F7F7F7] border border-[#EBEBEB] rounded p-3 mb-6">
        <p className="text-[13px] text-[#161616]">
          <span className="font-medium">Authentication:</span> All endpoints require{' '}
          <code className="bg-white px-1 py-0.5 rounded border border-[#EBEBEB] text-[12px]">Authorization: Bearer &lt;token&gt;</code>{' '}
          (OAuth JWT or PAT).
        </p>
      </div>

      {/* Section 1: Drop-in Genie API */}
      <div className="bg-white border border-[#EBEBEB] rounded overflow-hidden mb-4">
        <button
          onClick={() => toggleSection('genie')}
          className="w-full flex items-center gap-2.5 px-4 py-3 text-left hover:bg-[#FAFAFA] transition-colors"
        >
          {expandedSections.genie
            ? <ChevronDown className="w-4 h-4 text-[#6F6F6F]" />
            : <ChevronRight className="w-4 h-4 text-[#6F6F6F]" />}
          <h2 className="text-[14px] font-medium text-[#161616]">Drop-in Genie API</h2>
          <span className="text-[12px] text-[#6F6F6F]">-- Same endpoints as the official Genie API. Just change the base URL.</span>
        </button>

        {expandedSections.genie && (
          <div>
            <div className="px-4 pb-3 border-t border-[#EBEBEB] pt-3 space-y-3">
              <div className="bg-[#F7F7F7] rounded p-3 text-[12px]">
                <p className="text-[#6F6F6F]">
                  <span className="font-medium text-[#161616]">Before:</span>{' '}
                  <code>https://&lt;workspace&gt;.cloud.databricks.com</code>
                </p>
                <p className="text-[#6F6F6F]">
                  <span className="font-medium text-[#161616]">After:</span>{' '}
                  <code>{baseUrl}</code>
                </p>
              </div>
              <p className="text-[13px] text-[#6F6F6F]">
                Use your <strong className="text-[#161616]">Gateway ID</strong> (UUID from the Gateways list) in place of{' '}
                <code className="bg-[#F7F7F7] px-1 rounded text-[12px]">{'{gateway_id}'}</code>. The gateway resolves the real Genie Space ID internally.
              </p>
            </div>

            <EndpointRow
              id="clone-start"
              method="POST"
              path="/api/2.0/genie/spaces/{gateway_id}/start-conversation"
              description="Start conversation"
            >
              <p className="text-[13px] text-[#6F6F6F]">
                Cache hit returns <code className="bg-green-50 text-green-700 px-1 rounded text-[12px]">COMPLETED</code> with executed SQL.
                Cache miss returns <code className="bg-blue-50 text-blue-700 px-1 rounded text-[12px]">EXECUTING_QUERY</code> — poll the get-message endpoint until done.
              </p>
              <div>
                <p className="text-[12px] font-medium text-[#6F6F6F] mb-1">Request Body</p>
                <CodeBlock id="body-start" code={`{ "content": "How many sales per month?" }`} />
              </div>
              <div>
                <p className="text-[12px] font-medium text-[#6F6F6F] mb-1">Response (cache miss)</p>
                <CodeBlock id="resp-start" code={`{
  "conversation_id": "ccache_...",
  "message_id": "mcache_...",
  "status": "EXECUTING_QUERY",
  "attachments": []
}`} />
              </div>
              <div>
                <p className="text-[12px] font-medium text-[#6F6F6F] mb-1">curl</p>
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
              <p className="text-[13px] text-[#6F6F6F]">
                Poll every 2s until <code className="bg-green-50 text-green-700 px-1 rounded text-[12px]">COMPLETED</code> or{' '}
                <code className="bg-red-50 text-red-700 px-1 rounded text-[12px]">FAILED</code>.
                Use the <code className="bg-[#F7F7F7] px-1 rounded text-[12px]">conversation_id</code> and <code className="bg-[#F7F7F7] px-1 rounded text-[12px]">message_id</code> from the start-conversation response.
              </p>
              <div>
                <p className="text-[12px] font-medium text-[#6F6F6F] mb-1">Response (completed)</p>
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
              <p className="text-[13px] text-[#6F6F6F]">
                Returns the actual SQL execution results. Format identical to the Genie API (<code className="bg-[#F7F7F7] px-1 rounded text-[12px]">statement_response</code>).
              </p>
              <div>
                <p className="text-[12px] font-medium text-[#6F6F6F] mb-1">Response</p>
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
              <p className="text-[13px] text-[#6F6F6F]">Re-executes the cached SQL against the warehouse. Same response format as query-result.</p>
            </EndpointRow>

            <EndpointRow
              id="clone-space"
              method="GET"
              path="/api/2.0/genie/spaces/{gateway_id}"
              description="Get gateway/space metadata"
            >
              <p className="text-[13px] text-[#6F6F6F]">Resolves the gateway and proxies to the real Genie API. Returns space metadata.</p>
            </EndpointRow>
          </div>
        )}
      </div>

      {/* Section 2: Proxy API */}
      <div className="bg-white border border-[#EBEBEB] rounded overflow-hidden mb-4">
        <button
          onClick={() => toggleSection('proxy')}
          className="w-full flex items-center gap-2.5 px-4 py-3 text-left hover:bg-[#FAFAFA] transition-colors"
        >
          {expandedSections.proxy
            ? <ChevronDown className="w-4 h-4 text-[#6F6F6F]" />
            : <ChevronRight className="w-4 h-4 text-[#6F6F6F]" />}
          <h2 className="text-[14px] font-medium text-[#161616]">Proxy API</h2>
          <span className="text-[12px] text-[#6F6F6F]">-- Simplified REST API for apps that don't use the Genie API directly.</span>
        </button>

        {expandedSections.proxy && (
          <div>
            <EndpointRow
              id="proxy-async"
              method="POST"
              path="/api/v1/query"
              description="Submit query (async)"
            >
              <p className="text-[13px] text-[#6F6F6F]">
                Returns <code className="bg-[#F7F7F7] px-1 rounded text-[12px]">query_id</code>.
                Poll <code className="bg-[#F7F7F7] px-1 rounded text-[12px]">GET /api/v1/query/{'{query_id}'}</code> for result.
              </p>
              <div>
                <p className="text-[12px] font-medium text-[#6F6F6F] mb-1">curl</p>
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
              <p className="text-[13px] text-[#6F6F6F]">
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
              <p className="text-[13px] text-[#6F6F6F]">Same as POST /query but blocks until the result is ready.</p>
            </EndpointRow>
          </div>
        )}
      </div>

      {/* Section 3: Gateway Management API */}
      <div className="bg-white border border-[#EBEBEB] rounded overflow-hidden mb-4">
        <button
          onClick={() => toggleSection('gateway')}
          className="w-full flex items-center gap-2.5 px-4 py-3 text-left hover:bg-[#FAFAFA] transition-colors"
        >
          {expandedSections.gateway
            ? <ChevronDown className="w-4 h-4 text-[#6F6F6F]" />
            : <ChevronRight className="w-4 h-4 text-[#6F6F6F]" />}
          <h2 className="text-[14px] font-medium text-[#161616]">Gateway Management</h2>
          <span className="text-[12px] text-[#6F6F6F]">-- CRUD operations for gateways and workspace discovery.</span>
        </button>

        {expandedSections.gateway && (
          <div>
            <EndpointRow
              id="gw-list"
              method="GET"
              path="/api/gateways"
              description="List all gateways"
            >
              <p className="text-[13px] text-[#6F6F6F]">Returns an array of all configured gateways with their settings and metrics.</p>
              <div>
                <p className="text-[12px] font-medium text-[#6F6F6F] mb-1">curl</p>
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
              <p className="text-[13px] text-[#6F6F6F]">Creates a new gateway with a Genie Space and SQL Warehouse.</p>
              <div>
                <p className="text-[12px] font-medium text-[#6F6F6F] mb-1">Request Body</p>
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
              <p className="text-[13px] text-[#6F6F6F]">Returns full configuration and metrics for a specific gateway.</p>
            </EndpointRow>

            <EndpointRow
              id="gw-update"
              method="PUT"
              path="/api/gateways/{id}"
              description="Update gateway settings"
            >
              <p className="text-[13px] text-[#6F6F6F]">Partial update -- send only the fields you want to change.</p>
              <div>
                <p className="text-[12px] font-medium text-[#6F6F6F] mb-1">Request Body</p>
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
              <p className="text-[13px] text-[#6F6F6F]">Permanently deletes the gateway and its cache entries.</p>
            </EndpointRow>

            <EndpointRow
              id="gw-spaces"
              method="GET"
              path="/api/workspace/genie-spaces"
              description="List available Genie Spaces"
            >
              <p className="text-[13px] text-[#6F6F6F]">Queries the workspace for all Genie Spaces accessible to the current user or service principal.</p>
              <div>
                <p className="text-[12px] font-medium text-[#6F6F6F] mb-1">curl</p>
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
              <p className="text-[13px] text-[#6F6F6F]">Returns all SQL warehouses in the workspace.</p>
              <div>
                <p className="text-[12px] font-medium text-[#6F6F6F] mb-1">curl</p>
                <CodeBlock id="curl-gw-warehouses" code={`curl ${baseUrl}/api/workspace/warehouses \\
  -H "Authorization: Bearer $TOKEN"`} />
              </div>
            </EndpointRow>
          </div>
        )}
      </div>

      {/* How it works */}
      <div className="bg-white border border-[#EBEBEB] rounded p-4">
        <h3 className="text-[14px] font-medium text-[#161616] mb-3">How It Works</h3>
        <div className="space-y-1.5 text-[13px] text-[#6F6F6F]">
          <div className="flex items-start gap-2"><span className="font-mono text-[#CBCBCB] w-4 text-right flex-shrink-0">1.</span><span>App sends query with Bearer token.</span></div>
          <div className="flex items-start gap-2"><span className="font-mono text-[#CBCBCB] w-4 text-right flex-shrink-0">2.</span><span>Semantic cache search (Lakebase/pgvector) for similar query.</span></div>
          <div className="flex items-start gap-2"><span className="font-mono text-[#CBCBCB] w-4 text-right flex-shrink-0">3.</span><span><strong className="text-[#161616]">Cache hit:</strong> executes cached SQL on warehouse, returns fresh data.</span></div>
          <div className="flex items-start gap-2"><span className="font-mono text-[#CBCBCB] w-4 text-right flex-shrink-0">4.</span><span><strong className="text-[#161616]">Cache miss:</strong> calls the Genie API respecting the rate limit.</span></div>
          <div className="flex items-start gap-2"><span className="font-mono text-[#CBCBCB] w-4 text-right flex-shrink-0">5.</span><span><strong className="text-[#161616]">Rate limit:</strong> query enters queue with automatic retry.</span></div>
          <div className="flex items-start gap-2"><span className="font-mono text-[#CBCBCB] w-4 text-right flex-shrink-0">6.</span><span>Result and SQL are cached for future similar queries.</span></div>
        </div>
      </div>
    </div>
  )
}
