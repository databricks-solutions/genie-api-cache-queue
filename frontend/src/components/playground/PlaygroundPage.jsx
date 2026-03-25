import { useState, useEffect, useRef, useCallback } from 'react'
import { useParams } from 'react-router-dom'
import axios from 'axios'
import { api } from '../../services/api'
import PipelineVisualizer from './PipelineVisualizer'
import { Play, Copy, Check, Loader, ChevronDown, Database, Zap, Plus, X, Trash2 } from 'lucide-react'

const POLL_INTERVAL = 2000

function ResultTable({ data }) {
  if (!data) return null

  // Handle structured result: {columns, data_array, row_count}
  if (data.columns && Array.isArray(data.data_array)) {
    const columns = data.columns
    const rows = data.data_array
    if (columns.length === 0 && rows.length === 0) {
      return <p className="text-[13px] text-[#6F6F6F] mt-2">No data returned.</p>
    }
    return (
      <div className="mt-2 overflow-auto max-h-[400px] border border-[#EBEBEB] rounded">
        <table className="w-full">
          <thead>
            <tr>
              {columns.map((col, i) => (
                <th key={i} className="text-left text-[12px] font-medium text-[#161616] bg-[#F7F7F7] sticky top-0"
                  style={{ padding: '6px 10px', borderBottom: '1px solid #EBEBEB' }}>
                  {typeof col === 'string' ? col : col.name || col}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.slice(0, 200).map((row, ri) => (
              <tr key={ri} className="hover:bg-[#F7F7F7]">
                {(Array.isArray(row) ? row : Object.values(row)).map((cell, ci) => (
                  <td key={ci} className="text-[12px] text-[#161616]"
                    style={{ padding: '5px 10px', borderBottom: '1px solid #EBEBEB' }}>
                    {cell == null ? <span className="text-[#CBCBCB] italic">null</span> : String(cell)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
        {rows.length > 200 && (
          <div className="text-[12px] text-[#6F6F6F] p-2 bg-[#F7F7F7] text-center">
            Showing 200 of {data.row_count || rows.length} rows
          </div>
        )}
      </div>
    )
  }

  // Legacy fallback: array of objects (old format)
  if (Array.isArray(data) && data.length > 0 && typeof data[0] === 'object') {
    // Skip Genie attachment format (has 'query' as object)
    if (typeof data[0].query === 'object') {
      return <p className="text-[12px] text-[#6F6F6F] mt-1 italic">Result format not displayable. See SQL above.</p>
    }
    const cols = Object.keys(data[0])
    return (
      <div className="mt-2 overflow-auto max-h-[400px] border border-[#EBEBEB] rounded">
        <table className="w-full">
          <thead>
            <tr>
              {cols.map((col, i) => (
                <th key={i} className="text-left text-[12px] font-medium text-[#161616] bg-[#F7F7F7] sticky top-0"
                  style={{ padding: '6px 10px', borderBottom: '1px solid #EBEBEB' }}>{col}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.slice(0, 200).map((row, ri) => (
              <tr key={ri} className="hover:bg-[#F7F7F7]">
                {cols.map((col, ci) => (
                  <td key={ci} className="text-[12px] text-[#161616]"
                    style={{ padding: '5px 10px', borderBottom: '1px solid #EBEBEB' }}>
                    {row[col] == null ? <span className="text-[#CBCBCB] italic">null</span> : String(row[col])}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    )
  }

  // Last resort: JSON
  return (
    <div className="bg-[#F7F7F7] rounded p-3 mt-2 overflow-auto max-h-[200px]">
      <pre className="text-[12px] text-[#161616] font-mono whitespace-pre-wrap">
        {JSON.stringify(data, null, 2)}
      </pre>
    </div>
  )
}

function ChatMessage({ item }) {
  const [sqlCopied, setSqlCopied] = useState(false)
  const isCompleted = item.stage === 'completed'
  const isFailed = item.stage === 'failed'
  const isRunning = !isCompleted && !isFailed

  const handleCopySQL = () => {
    if (item.sql_query) {
      navigator.clipboard.writeText(item.sql_query)
      setSqlCopied(true)
      setTimeout(() => setSqlCopied(false), 2000)
    }
  }

  return (
    <div className="space-y-3 pb-6 border-b border-[#EBEBEB] last:border-0">
      {/* User question */}
      <div className="flex items-start gap-2">
        <div className="w-6 h-6 rounded-full bg-[#FF3621] flex items-center justify-center flex-shrink-0 mt-0.5">
          <span className="text-[10px] text-white font-medium">U</span>
        </div>
        <p className="text-[14px] font-medium text-[#161616] pt-0.5">{item.query}</p>
      </div>

      {/* Pipeline */}
      <div className="ml-8">
        <PipelineVisualizer
          stages={item.stages || []}
          currentStage={item.stage}
          fromCache={item.from_cache}
          error={item.error}
        />
      </div>

      {/* Result */}
      <div className="ml-8">
        {isRunning && (
          <div className="flex items-center gap-2 text-[13px] text-[#6F6F6F]">
            <Loader className="w-3.5 h-3.5 animate-spin text-[#2272B4]" />
            {stageLabel(item.stage)}
          </div>
        )}

        {isCompleted && (
          <div className="space-y-3">
            {/* Source badge */}
            <div className="flex items-center gap-2">
              {item.from_cache ? (
                <span className="inline-flex items-center gap-1 px-2 py-0.5 bg-[rgba(255,54,33,0.08)] text-[#FF3621] rounded text-[12px] font-medium">
                  <Zap className="w-3 h-3" /> Cache Hit
                </span>
              ) : (
                <span className="inline-flex items-center gap-1 px-2 py-0.5 bg-[rgba(34,114,180,0.08)] text-[#2272B4] rounded text-[12px] font-medium">
                  <Database className="w-3 h-3" /> Via Genie
                </span>
              )}
            </div>

            {/* SQL */}
            {item.sql_query ? (
              <div>
                <div className="flex items-center justify-between mb-1">
                  <span className="text-[11px] font-medium text-[#6F6F6F] uppercase tracking-wide">SQL</span>
                  <button onClick={handleCopySQL}
                    className="flex items-center gap-1 text-[11px] text-[#6F6F6F] hover:text-[#161616] transition-colors">
                    {sqlCopied ? <Check className="w-3 h-3 text-[#FF3621]" /> : <Copy className="w-3 h-3" />}
                    {sqlCopied ? 'Copied' : 'Copy'}
                  </button>
                </div>
                <div className="bg-[#F7F7F7] rounded p-3 overflow-auto max-h-[180px]">
                  <pre className="text-[12px] text-[#161616] font-mono whitespace-pre-wrap">{item.sql_query}</pre>
                </div>
              </div>
            ) : (
              <p className="text-[13px] text-[#6F6F6F] italic">A pergunta não retornou uma query SQL.</p>
            )}

            {/* Results table */}
            {item.result && (
              <div>
                <span className="text-[11px] font-medium text-[#6F6F6F] uppercase tracking-wide">Results</span>
                <ResultTable data={item.result} />
              </div>
            )}
          </div>
        )}

        {isFailed && (
          <div className="bg-red-50 border border-red-200 rounded p-3">
            <p className="text-[13px] text-red-700">{item.error || 'An unknown error occurred'}</p>
          </div>
        )}
      </div>

      {/* Timestamp */}
      <div className="ml-8 text-[11px] text-[#CBCBCB]">
        {item.timestamp ? new Date(item.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : ''}
        {item.identity && item.identity !== 'playground-user' && ` · ${item.identity}`}
      </div>
    </div>
  )
}

export default function PlaygroundPage() {
  const { id: routeGatewayId } = useParams()

  const [gateways, setGateways] = useState([])
  const [selectedGatewayId, setSelectedGatewayId] = useState(routeGatewayId || '')
  const [gatewayDropdownOpen, setGatewayDropdownOpen] = useState(false)
  const [loadingGateways, setLoadingGateways] = useState(true)

  const [queryText, setQueryText] = useState('')
  const [identity, setIdentity] = useState('')

  // Multi-tab conversation state — ephemeral, no persistence
  const [tabs, setTabs] = useState(() => [{ id: Date.now(), label: 'Conversation 1', messages: [], running: false }])
  const [activeTabId, setActiveTabId] = useState(() => tabs[0]?.id)
  const nextTabNumber = useRef(2)

  // Per-tab polling: Map<tabId, { interval, queryId, stageTimestamps }>
  const pollMapRef = useRef(new Map())
  const dropdownRef = useRef(null)
  const messagesEndRef = useRef(null)
  const activeTabIdRef = useRef(activeTabId)
  useEffect(() => { activeTabIdRef.current = activeTabId }, [activeTabId])

  const activeTab = tabs.find(t => t.id === activeTabId) || tabs[0]
  const messages = activeTab?.messages || []
  const running = activeTab?.running || false

  // Per-tab message updater (uses explicit tabId to avoid stale closures in polling)
  const setTabMessages = useCallback((tabId, updater) => {
    setTabs(prev => prev.map(t =>
      t.id === tabId
        ? { ...t, messages: typeof updater === 'function' ? updater(t.messages) : updater }
        : t
    ))
  }, [])

  // Convenience: update messages on the currently active tab
  const setMessages = useCallback((updater) => {
    setTabMessages(activeTabIdRef.current, updater)
  }, [setTabMessages])

  const setTabRunning = useCallback((tabId, value) => {
    setTabs(prev => prev.map(t => t.id === tabId ? { ...t, running: value } : t))
  }, [])

  const handleNewTab = () => {
    const newId = Date.now()
    setTabs(prev => {
      // Find the next available number that doesn't clash with any existing tab label
      const usedNumbers = new Set(prev.map(t => {
        const m = t.label.match(/^Conversation (\d+)$/)
        return m ? parseInt(m[1], 10) : 0
      }))
      let num = 1
      while (usedNumbers.has(num)) num++
      const newTab = { id: newId, label: `Conversation ${num}`, messages: [], running: false }
      return [...prev, newTab]
    })
    setActiveTabId(newId)
    setQueryText('')
  }

  const handleCloseTab = (tabId, e) => {
    e.stopPropagation()
    // Cancel any running poll for this tab
    const tabPoll = pollMapRef.current.get(tabId)
    if (tabPoll?.interval) clearInterval(tabPoll.interval)
    pollMapRef.current.delete(tabId)

    setTabs(prev => {
      const remaining = prev.filter(t => t.id !== tabId)
      if (remaining.length === 0) {
        const num = nextTabNumber.current++
        const newTab = { id: Date.now(), label: `Conversation ${num}`, messages: [], running: false }
        setActiveTabId(newTab.id)
        return [newTab]
      }
      if (activeTabId === tabId) {
        setActiveTabId(remaining[remaining.length - 1].id)
      }
      return remaining
    })
  }

  useEffect(() => {
    let mounted = true
    // Auto-populate identity from logged-in user
    api.healthCheck().then((h) => {
      if (mounted && h.user_email) setIdentity(h.user_email)
    }).catch(() => {})
    api.listGateways()
      .then((data) => {
        if (!mounted) return
        const list = Array.isArray(data) ? data : []
        setGateways(list)
        if (routeGatewayId && list.some(g => g.id === routeGatewayId)) {
          setSelectedGatewayId(routeGatewayId)
        } else if (!selectedGatewayId && list.length > 0) {
          setSelectedGatewayId(list[0].id)
        }
      })
      .catch(() => { if (mounted) setGateways([]) })
      .finally(() => { if (mounted) setLoadingGateways(false) })
    return () => { mounted = false }
  }, []) // eslint-disable-line

  useEffect(() => {
    function handleClick(e) {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target)) {
        setGatewayDropdownOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [])

  useEffect(() => {
    return () => {
      // Cleanup all polling intervals on unmount
      for (const entry of pollMapRef.current.values()) {
        if (entry.interval) clearInterval(entry.interval)
      }
      pollMapRef.current.clear()
    }
  }, [])

  const selectedGateway = gateways.find(g => g.id === selectedGatewayId)

  const updateTabMessage = useCallback((tabId, queryId, updates) => {
    setTabMessages(tabId, prev => {
      const idx = prev.findIndex(m => m.id === queryId)
      if (idx === -1) return prev
      const updated = [...prev]
      updated[idx] = { ...updated[idx], ...updates }
      return updated
    })
  }, [setTabMessages])

  const startPolling = useCallback((tabId, queryId) => {
    // Cancel any existing poll for this tab
    const existing = pollMapRef.current.get(tabId)
    if (existing?.interval) clearInterval(existing.interval)

    const stageTimestamps = { received: Date.now() }
    const interval = setInterval(async () => {
      try {
        const status = await api.getQueryStatus(queryId)
        const now = Date.now()

        if (!stageTimestamps[status.stage]) {
          stageTimestamps[status.stage] = now
        }

        const stageOrder = ['received', 'checking_cache', 'cache_hit', 'cache_miss', 'queued', 'processing_genie', 'executing_sql', 'completed', 'failed']
        const seenStages = []
        for (const s of stageOrder) {
          if (stageTimestamps[s]) {
            const nextStage = stageOrder.find(ns => stageOrder.indexOf(ns) > stageOrder.indexOf(s) && stageTimestamps[ns])
            const dur = nextStage && stageTimestamps[nextStage] ? stageTimestamps[nextStage] - stageTimestamps[s] : null
            seenStages.push({ name: s, status: 'completed', timestamp: stageTimestamps[s], duration: dur })
          }
        }

        updateTabMessage(tabId, queryId, {
          stages: seenStages,
          stage: status.stage,
          from_cache: status.from_cache || false,
        })

        if (status.stage === 'completed' || status.stage === 'failed') {
          clearInterval(interval)
          pollMapRef.current.delete(tabId)
          setTabRunning(tabId, false)
          updateTabMessage(tabId, queryId, {
            stages: seenStages,
            stage: status.stage,
            sql_query: status.sql_query,
            result: status.result,
            from_cache: status.from_cache || false,
            error: status.error,
          })
        }
      } catch {
        clearInterval(interval)
        pollMapRef.current.delete(tabId)
        setTabRunning(tabId, false)
        updateTabMessage(tabId, queryId, { stage: 'failed', error: 'Failed to poll query status' })
      }
    }, POLL_INTERVAL)

    pollMapRef.current.set(tabId, { interval, queryId, stageTimestamps })
  }, [updateTabMessage, setTabRunning])

  const handleSubmit = async () => {
    if (!queryText.trim() || running) return

    // Capture tabId at submit time so polling targets the correct tab
    const tabId = activeTabIdRef.current

    const newMessage = {
      id: null, // will be filled after API call
      query: queryText.trim(),
      identity: identity,
      stage: 'received',
      stages: [],
      from_cache: null,
      sql_query: null,
      result: null,
      error: null,
      timestamp: new Date(),
    }

    setMessages(prev => [...prev, newMessage])
    setTabRunning(tabId, true)
    setQueryText('')

    try {
      const payload = {
        query: newMessage.query,
        gateway_id: selectedGatewayId || undefined,
      }
      if (selectedGateway) {
        payload.config = {
          gateway_id: selectedGateway.id,
          genie_space_id: selectedGateway.genie_space_id,
          sql_warehouse_id: selectedGateway.sql_warehouse_id,
          similarity_threshold: selectedGateway.similarity_threshold,
          max_queries_per_minute: selectedGateway.max_queries_per_minute,
          cache_ttl_hours: selectedGateway.cache_ttl_hours,
          embedding_provider: selectedGateway.embedding_provider,
          databricks_embedding_endpoint: selectedGateway.databricks_embedding_endpoint,
          shared_cache: selectedGateway.shared_cache,
          storage_backend: 'lakebase',
        }
      }

      const response = await axios.post('/api/query', payload)
      const queryId = response.data.query_id

      setTabMessages(tabId, prev => {
        const updated = [...prev]
        const idx = updated.findLastIndex(m => m.id === null)
        if (idx !== -1) updated[idx] = { ...updated[idx], id: queryId }
        return updated
      })

      startPolling(tabId, queryId)
    } catch (err) {
      setTabRunning(tabId, false)
      // Update the last message (the one with id=null) in that tab
      setTabMessages(tabId, prev => {
        const updated = [...prev]
        const idx = updated.findLastIndex(m => m.id === null || m.stage === 'received')
        if (idx !== -1) updated[idx] = { ...updated[idx], stage: 'failed', error: err.response?.data?.detail || err.message }
        return updated
      })
    }
  }

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSubmit()
    }
  }

  const handleClearChat = () => {
    const tabId = activeTabIdRef.current
    // Cancel any running poll for this tab
    const tabPoll = pollMapRef.current.get(tabId)
    if (tabPoll?.interval) clearInterval(tabPoll.interval)
    pollMapRef.current.delete(tabId)
    // Reset messages and running state
    setTabMessages(tabId, [])
    setTabRunning(tabId, false)
    setQueryText('')
  }

  return (
    <div className="h-full flex flex-col">
      {/* Tabs bar + gateway selector — separate containers so the dropdown isn't clipped by overflow-x-auto */}
      <div className="flex items-stretch border-b border-[#EBEBEB] flex-shrink-0 bg-white">
        {/* Tabs (scrollable) */}
        <div className="flex items-center gap-1 overflow-x-auto flex-1 px-4 pt-3">
          {tabs.map(tab => (
            <button
              key={tab.id}
              onClick={() => setActiveTabId(tab.id)}
              className={`group flex items-center gap-1.5 px-3 py-1.5 text-[13px] rounded-t border-b-2 whitespace-nowrap transition-colors flex-shrink-0 ${
                tab.id === activeTabId
                  ? 'border-[#2272B4] text-[#0E538B] font-medium bg-white'
                  : 'border-transparent text-[#6F6F6F] hover:text-[#161616] hover:bg-[#F7F7F7]'
              }`}
            >
              {tab.label}
              {tabs.length > 1 && (
                <span
                  onClick={(e) => handleCloseTab(tab.id, e)}
                  className="w-3.5 h-3.5 rounded-full flex items-center justify-center opacity-0 group-hover:opacity-100 hover:bg-[#EBEBEB] transition-opacity"
                >
                  <X size={9} />
                </span>
              )}
            </button>
          ))}
          <button
            onClick={handleNewTab}
            className="flex items-center justify-center w-6 h-6 rounded hover:bg-[#F7F7F7] transition-colors flex-shrink-0 ml-1 mb-1.5"
            title="New conversation"
          >
            <Plus size={13} className="text-[#6F6F6F]" />
          </button>
        </div>

        {/* Gateway selector — outside overflow-x-auto so the dropdown isn't clipped */}
        <div className="relative flex-shrink-0 px-4 py-2 flex items-center" ref={dropdownRef}>
          <button
            onClick={() => setGatewayDropdownOpen(!gatewayDropdownOpen)}
            className="flex items-center gap-2 h-8 px-3 border border-[#CBCBCB] rounded text-[13px] text-[#161616] bg-white hover:border-[#2272B4] transition-colors min-w-[250px]"
            disabled={loadingGateways}
          >
            {loadingGateways ? (
              <span className="text-[#6F6F6F]">Loading gateways...</span>
            ) : selectedGateway ? (
              <span className="truncate">{selectedGateway.name}</span>
            ) : gateways.length === 0 ? (
              <span className="text-[#6F6F6F]">No gateways available</span>
            ) : (
              <span className="text-[#6F6F6F]">Select a gateway</span>
            )}
            <ChevronDown className={`w-4 h-4 text-[#6F6F6F] ml-auto flex-shrink-0 transition-transform ${gatewayDropdownOpen ? 'rotate-180' : ''}`} />
          </button>

          {gatewayDropdownOpen && gateways.length > 0 && (
            <div className="absolute right-4 top-full mt-1 bg-white border border-[#EBEBEB] rounded shadow-lg z-50 min-w-[300px] max-h-[300px] overflow-auto">
              {gateways.map((gw) => (
                <button key={gw.id} onClick={() => { setSelectedGatewayId(gw.id); setGatewayDropdownOpen(false) }}
                  className={`w-full text-left px-3 py-2.5 hover:bg-[#F7F7F7] transition-colors first:rounded-t-lg last:rounded-b-lg ${gw.id === selectedGatewayId ? 'bg-[#F7F7F7]' : ''}`}>
                  <div className="text-[13px] font-medium text-[#161616]">{gw.name}</div>
                  <div className="text-[11px] text-[#6F6F6F] mt-0.5 font-mono">{gw.id?.substring(0, 12)}…</div>
                </button>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Chat messages area */}
      <div className="flex-1 overflow-auto px-6 py-4 space-y-6">
        {messages.length === 0 && (
          <div className="flex flex-col items-center justify-center h-full text-center">
            <div className="w-12 h-12 rounded-full bg-[#F7F7F7] flex items-center justify-center mb-3">
              <Play className="w-5 h-5 text-[#6F6F6F]" />
            </div>
            <p className="text-[14px] font-medium text-[#161616] mb-1">Ask a question about your data</p>
            <p className="text-[13px] text-[#6F6F6F]">
              {selectedGateway ? `Using gateway: ${selectedGateway.name}` : 'Select a gateway to get started'}
            </p>
          </div>
        )}
        {messages.map((msg, i) => (
          <ChatMessage key={msg.id || i} item={msg} />
        ))}
        <div ref={messagesEndRef} />
      </div>

      {/* Input area */}
      <div className="flex-shrink-0 border-t border-[#EBEBEB] px-6 py-4 bg-white">
        <div className="flex gap-3 items-end">
          <textarea
            value={queryText}
            onChange={(e) => setQueryText(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={!selectedGateway && !loadingGateways ? 'Select a gateway above to start querying...' : 'Ask a question about your data...'}
            rows={2}
            className="flex-1 border border-[#CBCBCB] rounded p-3 text-[13px] text-[#161616] placeholder-[#CBCBCB] resize-none focus:outline-none focus:border-[#2272B4] focus:ring-1 focus:ring-[#2272B4]/20 disabled:bg-[#F7F7F7] disabled:cursor-not-allowed"
            disabled={running || (!selectedGateway && !loadingGateways)}
          />
          <div className="flex flex-col gap-1.5 items-stretch">
            <button
              id="playground-run-btn"
              onClick={handleSubmit}
              disabled={running || !queryText.trim() || (!selectedGateway && gateways.length > 0)}
              className="flex items-center justify-center gap-2 h-8 px-4 bg-[#2272B4] text-white rounded text-[13px] font-medium hover:bg-[#1b5e96] disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {running ? <Loader className="w-3.5 h-3.5 animate-spin" /> : <Play className="w-3.5 h-3.5" />}
              {running ? 'Running' : 'Run'}
            </button>
            <button
              onClick={handleClearChat}
              disabled={messages.length === 0}
              className="flex items-center justify-center gap-1.5 h-7 px-3 text-[12px] text-[#6F6F6F] hover:text-[#161616] hover:bg-[#F7F7F7] rounded transition-colors disabled:opacity-30 disabled:cursor-not-allowed disabled:hover:text-[#6F6F6F] disabled:hover:bg-transparent"
              title="Clear conversation"
            >
              <Trash2 className="w-3 h-3" />
              Clear
            </button>
          </div>
        </div>
        <div className="flex justify-end mt-1">
          <span className="text-[11px] text-[#CBCBCB]">Enter to run · Shift+Enter for new line</span>
        </div>
      </div>
    </div>
  )
}

function stageLabel(stage) {
  const labels = {
    received: 'Query received...',
    checking_cache: 'Checking cache...',
    cache_hit: 'Cache hit! Executing SQL...',
    cache_miss: 'Cache miss, sending to Genie...',
    queued: 'Rate limited, queued...',
    processing_genie: 'Processing with Genie API...',
    executing_sql: 'Executing SQL...',
    completed: 'Completed',
    failed: 'Failed',
  }
  return labels[stage] || stage
}
