import { useState } from 'react';
import {
  CheckCircle,
  Circle,
  XCircle,
  Clock,
  Loader,
} from 'lucide-react';

const FlowDiagram = ({ chatTabs, activeChatTabId }) => {
  const activeTab = chatTabs.find(tab => tab.id === activeChatTabId);
  const [viewMode, setViewMode] = useState('current');

  const stages = [
    { id: 'received', label: 'Received' },
    { id: 'checking_cache', label: 'Checking Cache' },
    { id: 'cache_hit', label: 'Cache Hit (Execute SQL)', path: 'cache_hit' },
    { id: 'cache_miss', label: 'Cache Miss', path: 'cache_miss' },
    { id: 'queued', label: 'Queued', path: 'queued' },
    { id: 'processing_genie', label: 'Processing (Genie)', path: 'genie' },
    { id: 'executing_sql', label: 'Executing SQL', path: 'cache_hit' },
    { id: 'completed', label: 'Completed' },
    { id: 'failed', label: 'Failed' },
  ];

  const getStageIcon = (isActive, isCompleted, isFailed) => {
    if (isFailed) return <XCircle className="w-5 h-5" />;
    if (isCompleted) return <CheckCircle className="w-5 h-5" />;
    if (isActive) return <Clock className="w-5 h-5 animate-pulse" />;
    return <Circle className="w-5 h-5" />;
  };

  const getQueryPath = (status) => {
    if (!status) return null;
    if (status.from_cache) return 'cache_hit';
    if (status.stage === 'queued') return 'queued';
    return 'genie';
  };

  const isStageInPath = (stageId, path) => {
    if (!path) return true;
    const pathStages = {
      'cache_hit': ['received', 'checking_cache', 'cache_hit', 'executing_sql', 'completed', 'failed'],
      'genie': ['received', 'checking_cache', 'cache_miss', 'processing_genie', 'completed', 'failed'],
      'queued': ['received', 'checking_cache', 'cache_miss', 'queued', 'processing_genie', 'completed', 'failed'],
    };
    return pathStages[path]?.includes(stageId) || false;
  };

  const getStageStatus = (stageId, path) => {
    if (!activeTab || !activeTab.status) return 'inactive';
    if (!isStageInPath(stageId, path)) return 'not_in_path';

    const currentStage = activeTab.status.stage;
    const allStages = stages.map(s => s.id);
    const stageIndex = allStages.indexOf(stageId);
    const currentIndex = allStages.indexOf(currentStage);

    if (stageId === currentStage) {
      if (currentStage === 'failed') return 'failed';
      if (currentStage === 'completed') return 'completed';
      return 'active';
    }

    if (stageIndex < currentIndex) return 'completed';
    return 'inactive';
  };

  const getAllQueries = () => {
    const queries = [];
    chatTabs.forEach(tab => {
      if (tab.status) {
        queries.push({
          tabId: tab.id,
          tabName: tab.name,
          query: tab.status.query_text,
          stage: tab.status.stage,
          path: getQueryPath(tab.status),
          from_cache: tab.status.from_cache,
          timestamp: tab.status.created_at,
          completed: tab.status.stage === 'completed' || tab.status.stage === 'failed',
        });
      }
    });
    return queries.sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp));
  };

  const queryPath = activeTab?.status ? getQueryPath(activeTab.status) : null;
  const allQueries = getAllQueries();

  return (
    <div className="bg-gray-100 rounded-lg border h-[calc(100vh-200px)] flex flex-col">
      {/* Header */}
      <div className="px-4 py-3 border-b">
        <div className="flex items-center justify-between mb-2">
          <h2 className="text-lg font-semibold text-gray-900">Flow Diagram</h2>
          <div className="flex gap-4">
            <button
              onClick={() => setViewMode('current')}
              className={`px-1 py-1 text-xs transition-colors ${
                viewMode === 'current'
                  ? 'text-gray-900 font-medium border-b-2 border-db-lava'
                  : 'text-gray-500 hover:text-gray-900'
              }`}
            >
              Current
            </button>
            <button
              onClick={() => setViewMode('history')}
              className={`px-1 py-1 text-xs transition-colors ${
                viewMode === 'history'
                  ? 'text-gray-900 font-medium border-b-2 border-db-lava'
                  : 'text-gray-500 hover:text-gray-900'
              }`}
            >
              History ({allQueries.length})
            </button>
          </div>
        </div>
        <p className="text-xs text-gray-500">
          {viewMode === 'current' ? 'Real-time query tracking' : 'All queries processed'}
        </p>
      </div>

      {/* Current Query Info */}
      {activeTab ? (
        <div className="px-4 py-3 bg-gray-200 border-b">
          <div className="text-xs font-medium text-gray-900 mb-1">
            Current Tab: {activeTab.name}
          </div>
          {activeTab.status ? (
            <>
              <div className="text-sm text-gray-900 truncate">
                {activeTab.status.query_text || 'Processing...'}
              </div>
              <div className="flex items-center gap-2 mt-2">
                {activeTab.polling && <Loader className="w-3 h-3 animate-spin text-gray-900" />}
                <span className="text-xs text-gray-500">
                  Stage: {activeTab.status.stage}
                </span>
              </div>
            </>
          ) : (
            <div className="text-sm text-gray-500 italic">No active query</div>
          )}
        </div>
      ) : (
        <div className="px-4 py-3 bg-gray-200 border-b">
          <div className="text-sm text-gray-500 italic">No tab selected</div>
        </div>
      )}

      {/* Content Area */}
      <div className="flex-1 overflow-y-auto">
        {viewMode === 'current' ? (
          <div className="p-4">
            <div className="space-y-0">
              {stages.map((stage) => {
                const status = getStageStatus(stage.id, queryPath);
                const isActive = status === 'active';
                const isCompleted = status === 'completed';
                const isFailed = status === 'failed';
                const isInactive = status === 'inactive';
                const notInPath = status === 'not_in_path';

                if (notInPath) return null;

                const visibleStages = stages.filter(s => isStageInPath(s.id, queryPath));
                const visibleIndex = visibleStages.findIndex(s => s.id === stage.id);
                const isLastVisible = visibleIndex === visibleStages.length - 1;

                return (
                  <div key={stage.id}>
                    <div
                      className={`p-3 rounded-lg border-l-4 bg-gray-200 transition-all ${
                        isFailed
                          ? 'border-l-db-lava'
                          : isCompleted
                          ? 'border-l-db-navy'
                          : isActive
                          ? 'border-l-db-navy border border-gray-900 shadow-sm'
                          : 'border-l-gray-300'
                      }`}
                    >
                      <div className="flex items-center gap-2">
                        <span className={
                          isFailed
                            ? 'text-db-lava'
                            : isCompleted
                            ? 'text-db-navy'
                            : isActive
                            ? 'text-gray-900'
                            : 'text-gray-400'
                        }>
                          {getStageIcon(isActive, isCompleted, isFailed)}
                        </span>
                        <span className={`font-medium text-sm ${isInactive ? 'text-gray-400' : 'text-gray-900'}`}>
                          {stage.label}
                        </span>
                      </div>
                    </div>
                    {!isLastVisible && (
                      <div className="flex justify-center py-0">
                        <div className={`w-px h-4 ${isCompleted ? 'bg-db-navy' : 'bg-gray-300'}`} />
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        ) : (
          <div className="p-4">
            {allQueries.length === 0 ? (
              <div className="text-center py-8 text-gray-500">
                <p className="text-sm">No queries yet</p>
                <p className="text-xs mt-1">Submit a query to see it here</p>
              </div>
            ) : (
              <div className="space-y-3">
                {allQueries.map((query, idx) => (
                  <div
                    key={`${query.tabId}-${idx}`}
                    className={`p-3 rounded-lg border bg-gray-200 ${
                      query.tabId === activeChatTabId
                        ? 'border-l-4 border-l-db-lava'
                        : ''
                    }`}
                  >
                    <div className="flex items-start justify-between mb-2">
                      <div className="flex-1 min-w-0">
                        <div className="text-xs font-medium mb-1 text-gray-500">{query.tabName}</div>
                        <div className="text-sm text-gray-900 truncate">{query.query}</div>
                      </div>
                      <div className="ml-2">
                        {query.stage === 'completed' ? (
                          <CheckCircle className="w-5 h-5 text-db-navy" />
                        ) : query.stage === 'failed' ? (
                          <XCircle className="w-5 h-5 text-db-lava" />
                        ) : (
                          <Loader className="w-5 h-5 text-gray-900 animate-spin" />
                        )}
                      </div>
                    </div>
                    <div className="flex items-center gap-2 text-xs">
                      {query.from_cache ? (
                        <span className="px-2 py-0.5 rounded font-medium border bg-gray-200 text-db-navy border-gray-300">
                          From Cache
                        </span>
                      ) : (
                        <span className="px-2 py-0.5 rounded font-medium border bg-gray-200 text-gray-900 border-gray-300">
                          Via Genie
                        </span>
                      )}
                      {query.path === 'queued' && (
                        <span className="px-2 py-0.5 rounded font-medium border bg-gray-200 text-db-yellow border-gray-300">
                          Queued
                        </span>
                      )}
                      <span className="text-gray-500">
                        {new Date(query.timestamp).toLocaleTimeString()}
                      </span>
                    </div>
                    <div className="mt-2 text-xs text-gray-500">
                      Status: <span className="font-medium text-gray-900">{query.stage}</span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Legend */}
      {viewMode === 'current' && (
        <div className="p-4 border-t">
          <div className="text-xs text-gray-500 space-y-2">
            <div className="flex items-center gap-2 mb-1">
              <Circle className="w-3 h-3 text-gray-500" />
              <span>Active: In progress</span>
            </div>
            <div className="flex items-center gap-2 mb-1">
              <CheckCircle className="w-3 h-3 text-db-navy" />
              <span>Completed step</span>
            </div>
            <div className="flex items-center gap-2">
              <XCircle className="w-3 h-3 text-db-lava" />
              <span>Failed step</span>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default FlowDiagram;
