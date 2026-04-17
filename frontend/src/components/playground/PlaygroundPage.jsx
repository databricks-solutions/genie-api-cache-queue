import { useState, useEffect, useRef, useCallback } from 'react'
import { useParams } from 'react-router-dom'
import axios from 'axios'
import { api } from '../../services/api'
import { useRole } from '../../context/RoleContext'
import PipelineVisualizer from './PipelineVisualizer'
import { Play, Copy, Check, Loader, ChevronDown, Database, Zap, Plus, X, Trash2 } from 'lucide-react'

const POLL_INTERVAL = 2000
// Bump whenever the persisted payload shape changes in a non-backward-compatible way.
// The `:v1` suffix on STORAGE_KEY_PREFIX namespaces the key; `SCHEMA_VERSION` is a
// second gate so a payload written before a shape change is rejected rather than
// rendered with stale fields.
const SCHEMA_VERSION = 1
const STORAGE_KEY_PREFIX = 'playground_session_v1'

// Scope localStorage by the caller's email so user A's conversation can't
// restore under user B's login on a shared workstation. `_anon` is used
// before the role context resolves and for the (rare) unauthenticated path.
function _storageKeyFor(identity) {
  const scope = identity ? encodeURIComponent(identity) : '_anon'
  return `${STORAGE_KEY_PREFIX}:${scope}`
}

// Monotonic counter for tab ids. `Date.now()` collides when two tabs are
// created in the same millisecond (rapid clicks, test double-invocation);
// the counter guarantees uniqueness within a session.
let _tabIdCounter = 0
const _nextTabId = () => {
  _tabIdCounter += 1
  return `${Date.now()}-${_tabIdCounter}`
}

// Strip the `result` payload when persisting: it can hold hundreds of rows
// and quickly blows past localStorage's ~5 MB quota. We keep a small
// placeholder so the restored UI can hint that results were not persisted.
function _stripHeavyFields(messages) {
  if (!Array.isArray(messages)) return []
  return messages.map(m => {
    if (!m || !m.result) return m
    const { columns, row_count, data_array } = m.result
    const rows = Array.isArray(data_array) ? data_array.length : 0
    return {
      ...m,
      result: null,
      result_summary: {
        columns: Array.isArray(columns) ? columns : undefined,
        row_count: typeof row_count === 'number' ? row_count : rows,
        dropped: true,
      },
    }
  })
}

function _loadPersistedSession(identity) {
  try {
    const raw = localStorage.getItem(_storageKeyFor(identity))
    if (!raw) return null
    const parsed = JSON.parse(raw)
    // Refuse payloads from a different schema rather than render with stale fields.
    if (!parsed || parsed.version !== SCHEMA_VERSION) return null
    if (!Array.isArray(parsed.tabs) || parsed.tabs.length === 0) return null
    const tabs = parsed.tabs.map(t => ({
      id: t.id ?? _nextTabId(),
      label: t.label || 'Conversation',
      running: false, // always restart cold
      messages: Array.isArray(t.messages) ? t.messages.map(m => {
        const wasRunning = m && m.stage && m.stage !== 'completed' && m.stage !== 'failed'
        return wasRunning
          ? { ...m, stage: 'failed', error: m.error || 'Query interrupted — you navigated away before it finished.' }
          : m
      }) : [],
    }))
    return {
      tabs,
      activeTabId: tabs.some(t => t.id === parsed.activeTabId) ? parsed.activeTabId : tabs[0].id,
      selectedGatewayId: parsed.selectedGatewayId || '',
    }
  } catch (e) {
    // eslint-disable-next-line no-console
    console.warn('Playground: could not read persisted conversation state from localStorage', e)
    return null
  }
}

// Compute the next free "Conversation N" number given the current tab set.
// Used to initialize `nextTabNumber` so restored tabs don't collide with
// labels chosen by the unique-number search in handleNewTab.
function _nextFreeConversationNumber(tabs) {
  const used = new Set((tabs || []).map(t => {
    const m = (t.label || '').match(/^Conversation (\d+)$/)
    return m ? parseInt(m[1], 10) : 0
  }))
  let n = 1
  while (used.has(n)) n++
  return n
}

function ResultTable({ data }) {
  if (!data) return null

  // Handle structured result: {columns, data_array, row_count}
  if (data.columns && Array.isArray(data.data_array)) {
    const columns = data.columns
    const rows = data.data_array
    if (columns.length === 0 && rows.length === 0) {
      return <p className="text-[13px] text-dbx-text-secondary mt-2">No data returned.</p>
    }
    return (
      <div className="mt-2 overflow-auto max-h-[400px] border border-dbx-border rounded">
        <table className="w-full">
          <thead>
            <tr>
              {columns.map((col, i) => (
                <th key={i} className="text-left text-[12px] font-medium text-dbx-text bg-dbx-sidebar sticky top-0"
                  style={{ padding: '6px 10px', borderBottom: '1px solid var(--dbx-border)' }}>
                  {typeof col === 'string' ? col : col.name || col}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.slice(0, 200).map((row, ri) => (
              <tr key={ri} className="hover:bg-dbx-neutral-hover">
                {(Array.isArray(row) ? row : Object.values(row)).map((cell, ci) => (
                  <td key={ci} className="text-[12px] text-dbx-text"
                    style={{ padding: '5px 10px', borderBottom: '1px solid var(--dbx-border)' }}>
                    {cell == null ? <span className="text-dbx-border-input italic">null</span> : String(cell)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
        {rows.length > 200 && (
          <div className="text-[12px] text-dbx-text-secondary p-2 bg-dbx-sidebar text-center">
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
      return <p className="text-[12px] text-dbx-text-secondary mt-1 italic">Result format not displayable. See SQL above.</p>
    }
    const cols = Object.keys(data[0])
    return (
      <div className="mt-2 overflow-auto max-h-[400px] border border-dbx-border rounded">
        <table className="w-full">
          <thead>
            <tr>
              {cols.map((col, i) => (
                <th key={i} className="text-left text-[12px] font-medium text-dbx-text bg-dbx-sidebar sticky top-0"
                  style={{ padding: '6px 10px', borderBottom: '1px solid var(--dbx-border)' }}>{col}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.slice(0, 200).map((row, ri) => (
              <tr key={ri} className="hover:bg-dbx-neutral-hover">
                {cols.map((col, ci) => (
                  <td key={ci} className="text-[12px] text-dbx-text"
                    style={{ padding: '5px 10px', borderBottom: '1px solid var(--dbx-border)' }}>
                    {row[col] == null ? <span className="text-dbx-border-input italic">null</span> : String(row[col])}
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
    <div className="bg-dbx-sidebar rounded p-3 mt-2 overflow-auto max-h-[200px]">
      <pre className="text-[12px] text-dbx-text font-mono whitespace-pre-wrap">
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
    <div className="space-y-3 pb-6 border-b border-dbx-border last:border-0">
      {/* User question */}
      <div className="flex items-start gap-2">
        <div className="w-6 h-6 rounded-full bg-[#FF3621] flex items-center justify-center flex-shrink-0 mt-0.5">
          <span className="text-[10px] text-white font-medium">U</span>
        </div>
        <p className="text-[14px] font-medium text-dbx-text pt-0.5">{item.query}</p>
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
          <div className="flex items-center gap-2 text-[13px] text-dbx-text-secondary">
            <Loader className="w-3.5 h-3.5 animate-spin text-dbx-blue" />
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
                <span className="inline-flex items-center gap-1 px-2 py-0.5 bg-dbx-blue-hover text-dbx-blue rounded text-[12px] font-medium">
                  <Database className="w-3 h-3" /> Via Genie
                </span>
              )}
            </div>

            {/* SQL */}
            {item.sql_query ? (
              <div>
                <div className="flex items-center justify-between mb-1">
                  <span className="text-[11px] font-medium text-dbx-text-secondary uppercase tracking-wide">SQL</span>
                  <button onClick={handleCopySQL}
                    className="flex items-center gap-1 text-[11px] text-dbx-text-secondary hover:text-dbx-text transition-colors">
                    {sqlCopied ? <Check className="w-3 h-3 text-[#FF3621]" /> : <Copy className="w-3 h-3" />}
                    {sqlCopied ? 'Copied' : 'Copy'}
                  </button>
                </div>
                <div className="bg-dbx-sidebar rounded p-3 overflow-auto max-h-[180px]">
                  <pre className="text-[12px] text-dbx-text font-mono whitespace-pre-wrap">{item.sql_query}</pre>
                </div>
              </div>
            ) : (
              <p className="text-[13px] text-dbx-text-secondary italic">The question did not return a SQL query.</p>
            )}

            {/* Results table */}
            {item.result && (
              <div>
                <span className="text-[11px] font-medium text-dbx-text-secondary uppercase tracking-wide">Results</span>
                <ResultTable data={item.result} />
              </div>
            )}
            {!item.result && item.result_summary?.dropped && (
              <p className="text-[12px] text-dbx-text-secondary italic">
                Results not restored after reload ({item.result_summary.row_count ?? 0} row{item.result_summary.row_count === 1 ? '' : 's'}). Re-run the query to see them.
              </p>
            )}
          </div>
        )}

        {isFailed && (
          <div className="bg-dbx-status-red-bg border border-dbx-danger-border rounded p-3">
            <p className="text-[13px] text-dbx-text-danger">{item.error || 'An unknown error occurred'}</p>
          </div>
        )}
      </div>

      {/* Timestamp */}
      <div className="ml-8 text-[11px] text-dbx-border-input">
        {item.timestamp ? new Date(item.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : ''}
        {item.identity && item.identity !== 'playground-user' && ` · ${item.identity}`}
      </div>
    </div>
  )
}

export default function PlaygroundPage() {
  const { id: routeGatewayId } = useParams()
  const { identity: userIdentity, loading: roleLoading } = useRole()

  const [gateways, setGateways] = useState([])
  const [selectedGatewayId, setSelectedGatewayId] = useState(() => routeGatewayId || '')
  const [gatewayDropdownOpen, setGatewayDropdownOpen] = useState(false)
  const [loadingGateways, setLoadingGateways] = useState(true)

  const [queryText, setQueryText] = useState('')
  const [identity, setIdentity] = useState('')

  // Multi-tab conversation state. Persisted to localStorage under a user-scoped
  // key (see `_storageKeyFor`) so user A's conversation can't restore under
  // user B's login. Restore is deferred to a useEffect that fires once the role
  // context resolves — we cannot read the right key synchronously since the
  // identity isn't known at first render. In-flight queries are marked
  // 'failed/interrupted' on restore rather than resumed.
  const [tabs, setTabs] = useState(() => (
    [{ id: _nextTabId(), label: 'Conversation 1', messages: [], running: false }]
  ))
  const [activeTabId, setActiveTabId] = useState(() => tabs[0]?.id)
  // Reconciled against restored tabs so a "Conversation N" label never collides
  // after a reload. handleNewTab re-checks against live state too; this is the
  // fallback used when all tabs are closed at once.
  const nextTabNumber = useRef(1)

  // Per-tab polling: Map<tabId, { interval, queryId, stageTimestamps }>
  const pollMapRef = useRef(new Map())
  const dropdownRef = useRef(null)
  const messagesEndRef = useRef(null)
  const activeTabIdRef = useRef(activeTabId)
  useEffect(() => { activeTabIdRef.current = activeTabId }, [activeTabId])

  // Restore from localStorage keyed by the current user's identity. Tracks which
  // identity's data is currently loaded in memory so a same-tab user switch
  // (A → B) flushes A's state back to A's key *before* hydrating B's — otherwise
  // the next debounced snapshot would write A's conversation under B's key and
  // overwrite B's own persisted state. `undefined` means "no identity loaded
  // yet"; any other value (including empty string for anonymous) is a loaded
  // identity and flushable.
  const restoredForIdentityRef = useRef(undefined)

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
    const newId = _nextTabId()
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
        const newTab = { id: _nextTabId(), label: `Conversation ${num}`, messages: [], running: false }
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
          return
        }
        // Drop a persisted selectedGatewayId if the gateway no longer exists
        // (deleted while the user was away) — otherwise the dropdown shows
        // "Select a gateway" with no explanation and submit stays disabled.
        if (selectedGatewayId && !list.some(g => g.id === selectedGatewayId)) {
          setSelectedGatewayId(list.length > 0 ? list[0].id : '')
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

  // Persist conversation state to localStorage so it survives navigation /
  // reloads. running flags are not persisted — on restore they default to
  // false and any in-flight messages are marked 'failed'.
  //
  // Two persistence paths:
  //   1. Debounced write while idle (any-tab-not-running). Polling updates the
  //      tab state every ~2s and we don't want to JSON.stringify every tab on
  //      every poll, so we skip the debounced write while any tab is running
  //      and rely on path #2 to capture unmount-during-poll.
  //   2. Synchronous flush on unmount, route-navigation (visibilitychange +
  //      pagehide). This runs even while polling, so a user who submits a
  //      query and navigates away mid-flight still gets their messages
  //      persisted — the restore path will then mark them 'interrupted'.
  const anyTabRunning = tabs.some(t => t.running)
  // Flipped to true on the first localStorage write failure (quota exceeded,
  // storage disabled by the browser, private-mode restrictions). Surfaces a
  // one-time dismissible banner so the user knows conversations won't survive
  // navigation — otherwise they'd silently lose state on the next route change.
  const [persistFailed, setPersistFailed] = useState(false)
  const persistWarnedRef = useRef(false)

  // latestSnapshotRef mirrors the current state synchronously so the
  // lifecycle handler (which sees the closure's snapshot at registration
  // time, not at fire time) can read the latest without re-registering on
  // every state change.
  const latestSnapshotRef = useRef(null)
  latestSnapshotRef.current = { tabs, activeTabId, selectedGatewayId }

  // Write the current in-memory snapshot under the key scoped to `identity`.
  // Exposed as a parameterized helper so the identity-change handler can flush
  // the *previous* user's state to *their* key before hydrating the new user.
  const writeSnapshotForIdentity = useCallback((identity) => {
    // Skip writes until we've had a chance to restore — otherwise the initial
    // empty-tab state would clobber a user's existing persisted conversation
    // before the restore effect runs.
    if (restoredForIdentityRef.current === undefined) return
    const snap = latestSnapshotRef.current
    if (!snap) return
    try {
      const payload = {
        version: SCHEMA_VERSION,
        tabs: snap.tabs.map(t => ({
          id: t.id,
          label: t.label,
          messages: _stripHeavyFields(t.messages),
        })),
        activeTabId: snap.activeTabId,
        selectedGatewayId: snap.selectedGatewayId,
      }
      localStorage.setItem(_storageKeyFor(identity), JSON.stringify(payload))
    } catch (e) {
      if (!persistWarnedRef.current) {
        persistWarnedRef.current = true
        // eslint-disable-next-line no-console
        console.warn(
          'Playground: could not persist conversation state to localStorage. ' +
          'Conversations will not survive navigation/reload in this session.',
          e
        )
        setPersistFailed(true)
      }
    }
  }, [])

  // Default path: always write under the identity we last restored for — not
  // `userIdentity` directly — so a transition from A → B can't re-key A's
  // still-in-memory state under B.
  const writeSnapshot = useCallback(() => {
    writeSnapshotForIdentity(restoredForIdentityRef.current)
  }, [writeSnapshotForIdentity])

  // Identity-aware hydrate. Runs on first resolve of `userIdentity` and on
  // any subsequent change (e.g. same tab, different login on a shared
  // workstation). The first branch flushes the outgoing user's in-memory
  // state to *their* key before loading the new user's snapshot, so user B
  // never sees user A's conversation and A's persisted state is preserved.
  useEffect(() => {
    if (roleLoading) return
    if (restoredForIdentityRef.current === userIdentity) return

    // Flush outgoing identity's state before swapping. Skipped on initial
    // hydrate (ref === undefined) because there's no prior identity to flush to.
    if (restoredForIdentityRef.current !== undefined) {
      writeSnapshotForIdentity(restoredForIdentityRef.current)
    }

    restoredForIdentityRef.current = userIdentity
    const persisted = _loadPersistedSession(userIdentity)
    if (persisted) {
      setTabs(persisted.tabs)
      setActiveTabId(persisted.activeTabId)
      if (!routeGatewayId && persisted.selectedGatewayId) {
        setSelectedGatewayId(persisted.selectedGatewayId)
      }
      nextTabNumber.current = _nextFreeConversationNumber(persisted.tabs)
    } else {
      // No snapshot for the incoming user — reset to a fresh blank conversation
      // so user A's tabs don't linger on screen after user B logs in.
      const freshId = _nextTabId()
      setTabs([{ id: freshId, label: 'Conversation 1', messages: [], running: false }])
      setActiveTabId(freshId)
      if (!routeGatewayId) setSelectedGatewayId('')
      nextTabNumber.current = 2
    }
  }, [roleLoading, userIdentity, routeGatewayId, writeSnapshotForIdentity])

  useEffect(() => {
    if (anyTabRunning) return
    const handle = setTimeout(writeSnapshot, 1500)
    return () => clearTimeout(handle)
  }, [tabs, activeTabId, selectedGatewayId, anyTabRunning, writeSnapshot])

  useEffect(() => {
    // Flush on tab hide (user switches tabs / minimizes) and on pagehide
    // (works for Safari where visibilitychange isn't always fired on unload).
    // Also flush on unmount — covers client-side route navigation where the
    // page itself stays alive but the component goes away.
    const onHide = () => {
      if (document.visibilityState === 'hidden') writeSnapshot()
    }
    const onPageHide = () => writeSnapshot()
    document.addEventListener('visibilitychange', onHide)
    window.addEventListener('pagehide', onPageHide)
    return () => {
      document.removeEventListener('visibilitychange', onHide)
      window.removeEventListener('pagehide', onPageHide)
      writeSnapshot()
    }
  }, [writeSnapshot])

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
      <div className="flex items-stretch border-b border-dbx-border flex-shrink-0 bg-dbx-bg">
        {/* Tabs (scrollable) */}
        <div className="flex items-center gap-1 overflow-x-auto flex-1 px-4 pt-3">
          {tabs.map(tab => (
            <button
              key={tab.id}
              onClick={() => setActiveTabId(tab.id)}
              className={`group flex items-center gap-1.5 px-3 py-1.5 text-[13px] rounded-t border-b-2 whitespace-nowrap transition-colors flex-shrink-0 ${
                tab.id === activeTabId
                  ? 'border-dbx-blue text-dbx-text-link font-medium bg-dbx-bg'
                  : 'border-transparent text-dbx-text-secondary hover:text-dbx-text hover:bg-dbx-neutral-hover'
              }`}
            >
              {tab.label}
              {tabs.length > 1 && (
                <span
                  onClick={(e) => handleCloseTab(tab.id, e)}
                  className="w-3.5 h-3.5 rounded-full flex items-center justify-center opacity-0 group-hover:opacity-100 hover:bg-dbx-border transition-opacity"
                >
                  <X size={9} />
                </span>
              )}
            </button>
          ))}
          <button
            onClick={handleNewTab}
            className="flex items-center justify-center w-6 h-6 rounded hover:bg-dbx-neutral-hover transition-colors flex-shrink-0 ml-1 mb-1.5"
            title="New conversation"
          >
            <Plus size={13} className="text-dbx-text-secondary" />
          </button>
        </div>

        {/* Gateway selector — outside overflow-x-auto so the dropdown isn't clipped */}
        <div className="relative flex-shrink-0 px-4 py-2 flex items-center" ref={dropdownRef}>
          <button
            onClick={() => setGatewayDropdownOpen(!gatewayDropdownOpen)}
            className="flex items-center gap-2 h-8 px-3 border border-dbx-border-input rounded text-[13px] text-dbx-text bg-dbx-bg hover:border-dbx-blue transition-colors min-w-[250px]"
            disabled={loadingGateways}
          >
            {loadingGateways ? (
              <span className="text-dbx-text-secondary">Loading gateways...</span>
            ) : selectedGateway ? (
              <span className="truncate">{selectedGateway.name}</span>
            ) : gateways.length === 0 ? (
              <span className="text-dbx-text-secondary">No gateways available</span>
            ) : (
              <span className="text-dbx-text-secondary">Select a gateway</span>
            )}
            <ChevronDown className={`w-4 h-4 text-dbx-text-secondary ml-auto flex-shrink-0 transition-transform ${gatewayDropdownOpen ? 'rotate-180' : ''}`} />
          </button>

          {gatewayDropdownOpen && gateways.length > 0 && (
            <div className="absolute right-4 top-full mt-1 bg-dbx-bg border border-dbx-border rounded shadow-lg z-50 min-w-[300px] max-h-[300px] overflow-auto">
              {gateways.map((gw) => (
                <button key={gw.id} onClick={() => { setSelectedGatewayId(gw.id); setGatewayDropdownOpen(false) }}
                  className={`w-full text-left px-3 py-2.5 hover:bg-dbx-neutral-hover transition-colors first:rounded-t-lg last:rounded-b-lg ${gw.id === selectedGatewayId ? 'bg-dbx-neutral-hover' : ''}`}>
                  <div className="text-[13px] font-medium text-dbx-text">{gw.name}</div>
                  <div className="text-[11px] text-dbx-text-secondary mt-0.5 font-mono">{gw.id?.substring(0, 12)}…</div>
                </button>
              ))}
            </div>
          )}
        </div>
      </div>

      {persistFailed && (
        <div className="flex items-center justify-between gap-2 px-4 py-2 bg-amber-50 border-b border-amber-200 text-[12px] text-amber-900 flex-shrink-0">
          <span>
            Conversation persistence is off — browser storage is full or blocked. Your active conversation won't survive navigation or reload.
          </span>
          <button
            onClick={() => setPersistFailed(false)}
            className="flex-shrink-0 w-5 h-5 rounded hover:bg-dbx-neutral-hover flex items-center justify-center"
            title="Dismiss"
          >
            <X size={12} className="text-dbx-text-secondary" />
          </button>
        </div>
      )}

      {/* Chat messages area */}
      <div className="flex-1 overflow-auto px-6 py-4 space-y-6">
        {messages.length === 0 && (
          <div className="flex flex-col items-center justify-center h-full text-center">
            <div className="w-12 h-12 rounded-full bg-dbx-sidebar flex items-center justify-center mb-3">
              <Play className="w-5 h-5 text-dbx-text-secondary" />
            </div>
            <p className="text-[14px] font-medium text-dbx-text mb-1">Ask a question about your data</p>
            <p className="text-[13px] text-dbx-text-secondary">
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
      <div className="flex-shrink-0 border-t border-dbx-border px-6 py-4 bg-dbx-bg">
        <div className="flex gap-3 items-end">
          <textarea
            value={queryText}
            onChange={(e) => setQueryText(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={!selectedGateway && !loadingGateways ? 'Select a gateway above to start querying...' : 'Ask a question about your data...'}
            rows={2}
            className="flex-1 border border-dbx-border-input rounded p-3 text-[13px] text-dbx-text bg-dbx-bg placeholder-dbx-border-input resize-none focus:outline-none focus:border-dbx-blue focus:ring-1 focus:ring-[rgba(34,114,180,0.2)] disabled:bg-dbx-sidebar disabled:cursor-not-allowed"
            disabled={running || (!selectedGateway && !loadingGateways)}
          />
          <div className="flex flex-col gap-1.5 items-stretch">
            <button
              id="playground-run-btn"
              onClick={handleSubmit}
              disabled={running || !queryText.trim() || (!selectedGateway && gateways.length > 0)}
              className="flex items-center justify-center gap-2 h-8 w-[100px] bg-dbx-blue text-white rounded text-[13px] font-medium hover:bg-dbx-blue-dark disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {running ? <Loader className="w-3.5 h-3.5 animate-spin" /> : <Play className="w-3.5 h-3.5" />}
              {running ? 'Running' : 'Run'}
            </button>
            <button
              onClick={handleClearChat}
              disabled={messages.length === 0}
              className="flex items-center justify-center gap-1.5 h-7 px-3 text-[12px] text-dbx-text-secondary hover:text-dbx-text hover:bg-dbx-neutral-hover rounded transition-colors disabled:opacity-30 disabled:cursor-not-allowed disabled:hover:text-dbx-text-secondary disabled:hover:bg-transparent"
              title="Clear conversation"
            >
              <Trash2 className="w-3 h-3" />
              Clear
            </button>
          </div>
        </div>
        <div className="flex justify-end mt-1">
          <span className="text-[11px] text-dbx-border-input">Enter to run · Shift+Enter for new line</span>
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
