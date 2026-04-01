import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { Copy, ChevronDown, ChevronRight, Terminal, Play } from 'lucide-react'
import { api } from '../../services/api'
import StatusBadge from '../shared/StatusBadge'

export default function GatewayOverviewTab({ gateway }) {
  const navigate = useNavigate()
  const [codeOpen, setCodeOpen] = useState(false)
  const [codeTab, setCodeTab] = useState('curl')
  const [copied, setCopied] = useState(false)
  const [metrics, setMetrics] = useState(null)

  const endpointUrl = `${window.location.origin}/api/2.0/genie/spaces/${gateway.id}/start-conversation`

  useEffect(() => {
    const fetchMetrics = async () => {
      try {
        const data = await api.getGatewayMetrics(gateway.id)
        setMetrics(data)
      } catch {
        // metrics may not be available yet
      }
    }
    fetchMetrics()
  }, [gateway.id])

  const copyUrl = () => {
    navigator.clipboard.writeText(endpointUrl)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }

  const curlCode = `curl -X POST '${endpointUrl}' \\
  -H 'Authorization: Bearer <your-token>' \\
  -H 'Content-Type: application/json' \\
  -d '{
    "content": "What are the top selling products?"
  }'`

  const pythonCode = `import requests

url = "${endpointUrl}"
headers = {
    "Authorization": "Bearer <your-token>",
    "Content-Type": "application/json"
}
payload = {
    "content": "What are the top selling products?"
}

response = requests.post(url, json=payload, headers=headers)
print(response.json())`

  const cacheEntries = metrics?.cache_entries ?? 0
  const totalQueries = metrics?.total_queries ?? 0
  const hitRate = metrics?.cache_hit_rate != null
    ? (metrics.cache_hit_rate * 100).toFixed(1)
    : '0.0'

  return (
    <div className="space-y-6">
      {/* Endpoint URL bar */}
      <div className="flex items-center gap-3">
        <StatusBadge status="active" />
        <div className="flex-1 flex items-center h-8 border border-dbx-border-input rounded overflow-hidden bg-dbx-bg">
          <input
            type="text"
            readOnly
            value={endpointUrl}
            className="flex-1 h-full px-3 text-[13px] text-dbx-text bg-transparent border-none outline-none"
          />
          <button
            onClick={copyUrl}
            className="h-full px-3 text-dbx-text-secondary hover:text-dbx-text hover:bg-dbx-neutral-hover transition-colors border-l border-dbx-border-input"
            title={copied ? 'Copied!' : 'Copy URL'}
          >
            <Copy size={14} />
          </button>
        </div>
        <button
          onClick={() => navigate(`/playground/${gateway.id}`)}
          className="inline-flex items-center gap-1.5 h-8 px-3 text-[13px] font-medium text-dbx-text border border-dbx-border-input rounded hover:bg-dbx-neutral-hover transition-colors whitespace-nowrap"
        >
          <Play size={14} />
          Chat in playground
        </button>
      </div>

      {/* View starter code */}
      <div className="rounded border border-dbx-border overflow-hidden">
        <button
          onClick={() => setCodeOpen(!codeOpen)}
          className="w-full flex items-center gap-2 px-4 py-3 bg-dbx-sidebar hover:bg-dbx-neutral-hover transition-colors text-left"
        >
          {codeOpen ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
          <Terminal size={16} className="text-dbx-text-secondary" />
          <span className="text-[13px] font-medium text-dbx-text">View starter code</span>
          <span className="ml-auto text-[13px] text-dbx-text-secondary border border-dbx-border-input rounded px-2 py-0.5 bg-dbx-bg">
            Genie Cache API
          </span>
        </button>

        {codeOpen && (
          <div className="border-t border-dbx-border">
            {/* Code tabs */}
            <div className="flex border-b border-dbx-border bg-dbx-sidebar">
              <button
                onClick={() => setCodeTab('curl')}
                className={`px-4 py-2 text-[13px] font-medium transition-colors ${
                  codeTab === 'curl'
                    ? 'text-dbx-text border-b-2 border-dbx-text'
                    : 'text-dbx-text-secondary border-b-2 border-transparent'
                }`}
              >
                cURL
              </button>
              <button
                onClick={() => setCodeTab('python')}
                className={`px-4 py-2 text-[13px] font-medium transition-colors ${
                  codeTab === 'python'
                    ? 'text-dbx-text border-b-2 border-dbx-text'
                    : 'text-dbx-text-secondary border-b-2 border-transparent'
                }`}
              >
                Python
              </button>
            </div>

            {/* Code block */}
            <div className="relative">
              <pre className="p-4 text-[13px] font-mono text-dbx-text bg-dbx-sidebar overflow-x-auto whitespace-pre-wrap">
                {codeTab === 'curl' ? curlCode : pythonCode}
              </pre>
              <button
                onClick={() => {
                  navigator.clipboard.writeText(codeTab === 'curl' ? curlCode : pythonCode)
                }}
                className="absolute top-3 right-3 p-1.5 text-dbx-text-secondary hover:text-dbx-text hover:bg-dbx-bg rounded transition-colors"
                title="Copy code"
              >
                <Copy size={14} />
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Quick stats row */}
      <div className="grid grid-cols-3 gap-4">
        <div className="bg-dbx-bg border border-dbx-border rounded p-4">
          <div className="text-[22px] font-medium text-dbx-text">{cacheEntries}</div>
          <div className="text-[13px] text-dbx-text-secondary">Cache entries</div>
        </div>
        <div className="bg-dbx-bg border border-dbx-border rounded p-4">
          <div className="text-[22px] font-medium text-dbx-text">{totalQueries}</div>
          <div className="text-[13px] text-dbx-text-secondary">Total queries (7d)</div>
        </div>
        <div className="bg-dbx-bg border border-dbx-border rounded p-4">
          <div className="text-[22px] font-medium text-dbx-text">{hitRate}%</div>
          <div className="text-[13px] text-dbx-text-secondary">Cache hit rate</div>
        </div>
      </div>
    </div>
  )
}
