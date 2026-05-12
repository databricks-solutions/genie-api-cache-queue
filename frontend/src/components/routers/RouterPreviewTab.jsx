import { useState } from 'react'
import { Loader2, Play } from 'lucide-react'
import { api } from '../../services/api'

export default function RouterPreviewTab({ routerCfg }) {
  const [question, setQuestion] = useState('')
  const [hints, setHints] = useState('')
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)

  const run = async () => {
    if (!question.trim()) { setError('Enter a question'); return }
    setLoading(true)
    setError(null)
    setResult(null)
    try {
      const hintList = hints.split('\n').map((s) => s.trim()).filter(Boolean)
      const res = await api.routerPreview(routerCfg.id, question, hintList.length ? hintList : undefined)
      setResult(res)
    } catch (err) {
      setError(err.response?.data?.detail || err.message || 'Preview failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="max-w-3xl">
      <div className="mb-4">
        <h2 className="text-[15px] font-medium text-dbx-text">What would this route to?</h2>
        <p className="text-[13px] text-dbx-text-secondary">
          Runs the selector without dispatching to any gateway. Use this to iterate on member <code>when_to_use</code> hints
          without spending warehouse or Genie quota.
        </p>
      </div>

      <label className="block text-[12px] font-medium text-dbx-text-secondary mb-1">Question</label>
      <textarea
        value={question}
        onChange={(e) => setQuestion(e.target.value)}
        placeholder="e.g. Which 10 donors have the highest cumulative USD received?"
        rows={3}
        className="w-full px-3 py-2 border border-dbx-border-input rounded text-[13px] bg-dbx-bg resize-y mb-3"
      />

      <label className="block text-[12px] font-medium text-dbx-text-secondary mb-1">Hints (optional, one per line)</label>
      <textarea
        value={hints}
        onChange={(e) => setHints(e.target.value)}
        placeholder="Extra context the selector should read"
        rows={2}
        className="w-full px-3 py-2 border border-dbx-border-input rounded text-[13px] bg-dbx-bg resize-y mb-4"
      />

      <button
        onClick={run}
        disabled={loading || !question.trim()}
        className="flex items-center gap-2 h-9 px-4 text-[13px] font-medium text-white bg-dbx-blue rounded hover:bg-dbx-blue-dark disabled:opacity-50"
      >
        {loading ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} />}
        {loading ? 'Routing…' : 'Preview routing'}
      </button>

      {error && (
        <div className="mt-4 px-3 py-2 rounded bg-red-50 border border-red-200 text-red-700 text-[13px]">
          {error}
        </div>
      )}

      {result && (
        <div className="mt-6 space-y-4">
          <DecisionPanel result={result} routerCfg={routerCfg} />
          <DiagnosticsPanel result={result} />
        </div>
      )}
    </div>
  )
}

function DecisionPanel({ result, routerCfg }) {
  const routing = result.routing || {}
  const picks = routing.picks || []
  const memberById = Object.fromEntries((routerCfg.members || []).map((m) => [m.gateway_id, m]))

  return (
    <div className="border border-dbx-border rounded px-4 py-3">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-[14px] font-medium text-dbx-text">Routing decision</h3>
        <span className="text-[12px] text-dbx-text-secondary">
          {routing.decomposed ? `Decomposed into ${picks.length}` : `Single-pick`} · {result.elapsed_ms} ms
        </span>
      </div>

      {routing.rationale && (
        <div className="text-[13px] text-dbx-text-secondary italic mb-3">“{routing.rationale}”</div>
      )}

      {picks.length === 0 ? (
        <div className="text-[13px] text-dbx-text-secondary">
          No picks — the selector decided no member can answer this question.
        </div>
      ) : (
        <div className="space-y-2">
          {picks.map((p, i) => {
            const member = memberById[p.gateway_id]
            return (
              <div key={i} className="border border-dbx-border rounded px-3 py-2">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="text-[13px] font-medium text-dbx-text">
                      {member?.title || p.gateway_id}
                    </div>
                    <div className="text-[12px] text-dbx-text-secondary">
                      <code>{p.gateway_id}</code>
                    </div>
                  </div>
                  <div className="text-[11px] text-dbx-text-secondary">pick {i + 1}</div>
                </div>
                <div className="text-[13px] text-dbx-text mt-2">
                  <span className="text-dbx-text-secondary">Sub-question: </span>
                  {p.sub_question}
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

function DiagnosticsPanel({ result }) {
  const d = result.diagnostics || {}
  return (
    <div className="border border-dbx-border rounded px-4 py-3">
      <h3 className="text-[14px] font-medium text-dbx-text mb-2">Diagnostics</h3>
      <div className="grid grid-cols-2 gap-x-6 gap-y-1 text-[13px]">
        <Row label="Routing cache" value={d.cache_hit ? 'HIT' : 'MISS'} />
        {d.cache_hit && <Row label="Cached question" value={d.cached_question} />}
        {d.cache_hit && <Row label="Similarity" value={(d.cached_similarity ?? 0).toFixed(3)} />}
        <Row label="Embedding" value={`${d.embedding_ms ?? 0} ms`} />
        <Row label="Selector" value={`${d.selector_ms ?? 0} ms`} />
      </div>
    </div>
  )
}

function Row({ label, value }) {
  return (
    <>
      <div className="text-dbx-text-secondary">{label}</div>
      <div className="text-dbx-text">{value ?? '—'}</div>
    </>
  )
}
