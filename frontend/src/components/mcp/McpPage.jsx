import { useState } from 'react'
import { Copy, Check } from 'lucide-react'

export default function McpPage() {
  const [copied, setCopied] = useState(null)
  const baseUrl = window.location.origin

  const copyToClipboard = (text, id) => {
    navigator.clipboard.writeText(text)
    setCopied(id)
    setTimeout(() => setCopied(null), 2000)
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
      <h1 className="text-[22px] font-medium text-dbx-text">MCP Server</h1>
      <p className="text-[13px] text-dbx-text-secondary mt-1 mb-6">
        Drop-in replacement for the Databricks managed Genie MCP. Same protocol, same tools — just change the URL.
      </p>

      {/* Before / After — same style as API Reference */}
      <div className="bg-dbx-sidebar border border-dbx-border rounded p-3 mb-4 space-y-3">
        <div className="text-[12px]">
          <p className="text-dbx-text-secondary">
            <span className="font-medium text-dbx-text">Before:</span>{' '}
            <code>https://&lt;workspace&gt;.cloud.databricks.com/api/2.0/mcp/genie/&#123;space_id&#125;</code>
          </p>
          <p className="text-dbx-text-secondary">
            <span className="font-medium text-dbx-text">After:</span>{' '}
            <code>{baseUrl}/api/2.0/mcp/genie/&#123;gateway_id&#125;</code>
          </p>
        </div>
        <p className="text-[13px] text-dbx-text-secondary">
          Use your <strong className="text-dbx-text">Gateway ID</strong> (UUID from the Gateways list) in place of{' '}
          <code className="bg-dbx-bg px-1 py-0.5 rounded border border-dbx-border text-[12px]">{'space_id'}</code>. The gateway resolves the real Genie Space ID internally.
        </p>
      </div>

      {/* Hint: Normalization */}
      <div className="bg-[#FFF4EC] border border-[#FFD4B0] rounded p-3 mb-6">
        <p className="text-[13px] text-[#6B2B00]">
          <span className="font-medium">Recommended:</span> Enable <strong>Question Normalization</strong> on the gateway when using MCP.
          LLM agents are non-deterministic — the same user intent can produce different phrasings on each call,
          which reduces cache hit rates. Normalization maps these variations to a canonical form before embedding,
          significantly improving cache effectiveness.
        </p>
      </div>

      {/* Connect */}
      <div className="bg-dbx-bg border border-dbx-border rounded overflow-hidden mb-4">
        <div className="px-4 py-3 border-b border-dbx-border">
          <h2 className="text-[14px] font-medium text-dbx-text">Connect</h2>
          <p className="text-[12px] text-dbx-text-secondary mt-0.5">Any MCP client that supports Streamable HTTP works. Just provide the URL and auth header.</p>
        </div>
        <div className="px-4 py-3 space-y-3">
          <div>
            <p className="text-[12px] font-medium text-dbx-text mb-1">Transport</p>
            <p className="text-[12px] text-dbx-text-secondary">HTTP / Streamable HTTP</p>
          </div>
          <div>
            <p className="text-[12px] font-medium text-dbx-text mb-1">Server URL</p>
            <CodeBlock
              code={`${baseUrl}/api/2.0/mcp/genie/{gateway_id}`}
              id="mcp-url"
            />
          </div>
          <div>
            <p className="text-[12px] font-medium text-dbx-text mb-1">Auth Header</p>
            <CodeBlock code="Bearer <your-databricks-oauth-token>" id="mcp-auth" />
          </div>
        </div>
      </div>

      {/* Tools */}
      <div className="bg-dbx-bg border border-dbx-border rounded overflow-hidden mb-4">
        <div className="px-4 py-3 border-b border-dbx-border">
          <h2 className="text-[14px] font-medium text-dbx-text">Tools</h2>
          <p className="text-[12px] text-dbx-text-secondary mt-0.5">The server exposes two tools per gateway, identical to the managed MCP.</p>
        </div>
        <div className="divide-y divide-dbx-border">
          <div className="px-4 py-3">
            <code className="text-[12px] font-mono text-dbx-text-link">query_space_&#123;gateway_id&#125;</code>
            <p className="text-[12px] text-dbx-text-secondary mt-1">Ask a natural language question. Returns immediately on cache hit, or starts background processing on cache miss.</p>
            <div className="mt-2 space-y-1">
              <p className="text-[11px] text-dbx-text-secondary"><code className="bg-dbx-sidebar px-1 rounded">query</code> <span className="text-dbx-text-danger">required</span> — Natural language question</p>
              <p className="text-[11px] text-dbx-text-secondary"><code className="bg-dbx-sidebar px-1 rounded">conversation_id</code> optional — Continue an existing conversation</p>
            </div>
          </div>
          <div className="px-4 py-3">
            <code className="text-[12px] font-mono text-dbx-text-link">poll_response_&#123;gateway_id&#125;</code>
            <p className="text-[12px] text-dbx-text-secondary mt-1">Poll for the result of a pending query until it reaches a completed state.</p>
            <div className="mt-2 space-y-1">
              <p className="text-[11px] text-dbx-text-secondary"><code className="bg-dbx-sidebar px-1 rounded">conversation_id</code> <span className="text-dbx-text-danger">required</span></p>
              <p className="text-[11px] text-dbx-text-secondary"><code className="bg-dbx-sidebar px-1 rounded">message_id</code> <span className="text-dbx-text-danger">required</span></p>
            </div>
          </div>
        </div>
      </div>

      {/* Example */}
      <div className="bg-dbx-bg border border-dbx-border rounded overflow-hidden mb-4">
        <div className="px-4 py-3 border-b border-dbx-border">
          <h2 className="text-[14px] font-medium text-dbx-text">Example — OpenAI Agents SDK</h2>
        </div>
        <div className="px-4 py-3">
          <CodeBlock
            id="example-oai"
            code={`from agents import Agent, Runner
from agents.mcp import MCPServerStreamableHttp

CLONE_URL = "${baseUrl}/api/2.0/mcp/genie/{gateway_id}"
AUTH = {"Authorization": "Bearer <token>"}

async with MCPServerStreamableHttp(params={"url": CLONE_URL, "headers": AUTH}) as mcp:
    agent = Agent(name="analyst", model=model, mcp_servers=[mcp])
    result = await Runner.run(agent, "Top 3 nations by revenue?")`}
          />
        </div>
      </div>
    </div>
  )
}
