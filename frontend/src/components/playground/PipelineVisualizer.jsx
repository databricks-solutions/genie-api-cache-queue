import { Check, X, Loader } from 'lucide-react'

const STAGE_DEFS = {
  received:         { label: 'Received',           branch: 'common' },
  checking_cache:   { label: 'Cache Check',        branch: 'common' },
  cache_hit:        { label: 'Cache Hit',          branch: 'hit' },
  cache_miss:       { label: 'Cache Miss',         branch: 'miss' },
  queued:           { label: 'Queued',             branch: 'miss' },
  processing_genie: { label: 'Genie API',          branch: 'miss' },
  executing_sql:    { label: 'Execute SQL',        branch: 'hit' },
  completed:        { label: 'Completed',          branch: 'common' },
  failed:           { label: 'Failed',             branch: 'common' },
}

const HIT_PATH  = ['received', 'checking_cache', 'cache_hit', 'executing_sql', 'completed']
const MISS_PATH = ['received', 'checking_cache', 'cache_miss', 'processing_genie', 'completed']
const QUEUED_PATH = ['received', 'checking_cache', 'cache_miss', 'queued', 'processing_genie', 'completed']

function resolvePath(stages, fromCache) {
  if (fromCache === true)  return 'hit'
  if (fromCache === false) return 'miss'
  const seen = new Set(stages.map(s => s.name))
  if (seen.has('cache_hit'))  return 'hit'
  if (seen.has('cache_miss')) return 'miss'
  if (seen.has('queued'))     return 'queued'
  return null
}

function getOrderedStages(path) {
  if (path === 'hit')    return HIT_PATH
  if (path === 'queued') return QUEUED_PATH
  if (path === 'miss')   return MISS_PATH
  return ['received', 'checking_cache']
}

function formatDuration(ms) {
  if (ms < 1000) return `${ms}ms`
  return `${(ms / 1000).toFixed(1)}s`
}

// Colors: hit = Databricks orange (#FF3621), miss = blue (dbx-blue)
function getColors(branchColor, status) {
  if (status === 'completed') {
    if (branchColor === 'orange') return { circle: 'border-[#FF3621] bg-[#FF3621]', line: '#FF3621', label: 'text-dbx-text' }
    if (branchColor === 'blue') return { circle: 'border-dbx-blue bg-dbx-blue', line: 'var(--dbx-blue)', label: 'text-dbx-text' }
    return { circle: 'border-[#FF3621] bg-[#FF3621]', line: '#FF3621', label: 'text-dbx-text' }
  }
  if (status === 'active') return { circle: 'border-dbx-blue bg-dbx-bg', line: 'var(--dbx-blue)', label: 'text-dbx-blue font-medium' }
  if (status === 'failed') return { circle: 'border-red-500 bg-red-500', line: '#ef4444', label: 'text-red-600 font-medium' }
  // pending / skipped
  return { circle: 'border-dbx-border bg-dbx-bg', line: 'var(--dbx-border)', label: 'text-dbx-border-input' }
}

function StageNode({ stageId, status, duration, isLast, branchColor }) {
  const def = STAGE_DEFS[stageId] || { label: stageId }
  const colors = getColors(branchColor, status)

  let icon = null
  if (status === 'completed') icon = <Check className="w-3 h-3 text-white" strokeWidth={3} />
  else if (status === 'active') icon = <Loader className="w-3 h-3 text-dbx-blue animate-spin" />
  else if (status === 'failed') icon = <X className="w-3 h-3 text-white" strokeWidth={3} />

  return (
    <div className="flex items-center">
      {/* Node */}
      <div className="flex flex-col items-center gap-1 min-w-[72px]">
        <div
          className={`w-7 h-7 rounded-full border-2 flex items-center justify-center flex-shrink-0 transition-all duration-300 ${colors.circle}`}
          style={status === 'active' ? { boxShadow: '0 0 0 4px rgba(34,114,180,0.15)' } : {}}
        >
          {icon}
        </div>
        <span className={`text-[11px] leading-tight text-center transition-colors duration-200 ${colors.label}`}>
          {def.label}
        </span>
        {status === 'completed' && duration != null && (
          <span className="text-[10px] text-dbx-text-secondary -mt-0.5">{formatDuration(duration)}</span>
        )}
        {status === 'active' && (
          <span className="text-[10px] text-dbx-blue animate-pulse -mt-0.5">...</span>
        )}
      </div>

      {/* Connector arrow */}
      {!isLast && (
        <div className="flex items-center self-start mt-[13px]">
          <div
            className="h-[2px] w-6 transition-colors duration-300"
            style={{
              backgroundColor: colors.line,
              ...(status === 'pending' || status === 'skipped'
                ? { backgroundImage: `repeating-linear-gradient(to right, ${colors.line} 0px, ${colors.line} 3px, transparent 3px, transparent 6px)`, backgroundColor: 'transparent' }
                : {}),
            }}
          />
          <div
            className="w-0 h-0 border-t-[4px] border-b-[4px] border-l-[5px] border-t-transparent border-b-transparent"
            style={{ borderLeftColor: colors.line }}
          />
        </div>
      )}
    </div>
  )
}

export default function PipelineVisualizer({ stages = [], currentStage, fromCache, error }) {
  const path = resolvePath(stages, fromCache)
  const orderedStages = getOrderedStages(path)
  const stageMap = new Map(stages.map(s => [s.name, s]))

  const displayStages = currentStage === 'failed'
    ? [...orderedStages.filter(s => s !== 'completed'), 'failed']
    : orderedStages

  function getStatus(stageId) {
    if (stageId === currentStage) {
      if (stageId === 'completed') return 'completed'
      if (stageId === 'failed') return 'failed'
      return 'active'
    }
    const entry = stageMap.get(stageId)
    if (entry) return 'completed'
    const currentIdx = displayStages.indexOf(currentStage)
    const stageIdx = displayStages.indexOf(stageId)
    if (currentIdx >= 0 && stageIdx >= 0 && stageIdx < currentIdx) return 'completed'
    return 'pending'
  }

  function getBranchColor(stageId) {
    const def = STAGE_DEFS[stageId]
    if (!def) return 'blue'
    // Hit path = orange (Databricks), Miss path = blue
    if (def.branch === 'hit') return 'orange'
    if (def.branch === 'miss') return 'blue'
    // Common stages follow the path color
    if (path === 'hit') return 'orange'
    return 'blue'
  }

  return (
    <div className="bg-dbx-bg border border-dbx-border rounded p-4">
      <h3 className="text-[13px] font-medium text-dbx-text mb-3">Query Pipeline</h3>

      {stages.length === 0 && !currentStage ? (
        <div className="py-3 text-center">
          <div className="text-[13px] text-dbx-text-secondary mb-3">Submit a query to see the pipeline</div>
          <div className="flex items-center justify-center">
            {['received', 'checking_cache'].map((id, i) => (
              <StageNode key={id} stageId={id} status="pending" isLast={i === 1} branchColor="blue" />
            ))}
          </div>
          <div className="mt-3 flex justify-center gap-5">
            <div className="text-[11px] text-dbx-border-input flex items-center gap-1">
              <span className="inline-block w-2 h-2 rounded-full bg-[#FF3621]" />
              Cache Hit
            </div>
            <div className="text-[11px] text-dbx-border-input flex items-center gap-1">
              <span className="inline-block w-2 h-2 rounded-full bg-dbx-blue" />
              Cache Miss
            </div>
          </div>
        </div>
      ) : (
        <div>
          {/* Horizontal pipeline */}
          <div className="flex items-start overflow-x-auto pb-2">
            {displayStages.map((id, i) => (
              <StageNode
                key={id}
                stageId={id}
                status={getStatus(id)}
                duration={stageMap.get(id)?.duration}
                isLast={i === displayStages.length - 1}
                branchColor={getBranchColor(id)}
              />
            ))}
          </div>

          {/* Error detail */}
          {error && currentStage === 'failed' && (
            <div className="mt-3 bg-red-50 border border-red-200 rounded p-2.5">
              <div className="text-[12px] text-red-700 break-words">{error}</div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
