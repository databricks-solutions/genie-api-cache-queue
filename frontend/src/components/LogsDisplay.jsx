import { useState, useEffect, useRef } from 'react';
import { Terminal, Trash2, Pause, Play } from 'lucide-react';

const LogsDisplay = ({ chatTabs }) => {
  const [logs, setLogs] = useState([]);
  const [isPaused, setIsPaused] = useState(false);
  const logsEndRef = useRef(null);

  useEffect(() => {
    if (isPaused) return;

    chatTabs.forEach((tab) => {
      const tabId = tab.id;
      if (!tab.status) return;

      // Extract query text from the first user message in the tab
      const queryText = tab.status.query_text
        || tab.messages?.find((m) => m.role === 'user')?.content
        || '';

      // Iterate over all seen stages (including transient ones like 'queued')
      const stagesToCheck = tab.seenStages
        ? Array.from(tab.seenStages)
        : [tab.status.stage];

      stagesToCheck.forEach((stage) => {
        const existingLog = logs.find(
          (log) => log.tabId === tabId && log.stage === stage
        );

        if (!existingLog) {
          const logEntry = {
            id: `${tabId}-${stage}-${Date.now()}`,
            tabId,
            timestamp: new Date(),
            stage,
            query: queryText,
            level: getLogLevel(stage),
            message: getLogMessage(stage, queryText),
          };

          setLogs((prev) => [...prev, logEntry].slice(-50));
        }
      });
    });
  }, [chatTabs, isPaused]);

  useEffect(() => {
    if (!isPaused) {
      logsEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }
  }, [logs, isPaused]);

  const getLogLevel = (stage) => {
    if (stage === 'failed') return 'error';
    if (stage === 'completed') return 'success';
    if (stage === 'queued') return 'warning';
    return 'info';
  };

  const getLogMessage = (stage, query) => {
    const messages = {
      received: `Query received: "${query?.substring(0, 50)}..."`,
      checking_cache: 'Checking cache for similar queries',
      cache_hit: 'Found in cache - using cached SQL',
      cache_miss: 'Not found in cache, routing to Genie API',
      queued: 'Rate limit reached, query queued',
      processing_genie: 'Processing with Genie API',
      executing_sql: 'Executing SQL query',
      completed: 'Query completed successfully',
      failed: 'Query failed',
    };
    return messages[stage] || stage;
  };

  const getLevelColor = (level) => {
    const colors = {
      info: 'text-db-gray',
      success: 'text-db-navy',
      warning: 'text-db-gold',
      error: 'text-db-lava',
    };
    return colors[level] || 'text-db-gray';
  };

  const getLevelBg = (level) => {
    const colors = {
      info: 'bg-db-oat',
      success: 'bg-db-oat',
      warning: 'bg-db-bg',
      error: 'bg-db-bg',
    };
    return colors[level] || 'bg-db-bg';
  };

  const clearLogs = () => {
    setLogs([]);
  };

  const formatTime = (date) => {
    return date.toLocaleTimeString('en-US', {
      hour12: false,
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      fractionalSecondDigits: 3,
    });
  };

  return (
    <div className="bg-gray-100 rounded-lg border mt-4">
      {/* Header */}
      <div className="px-4 py-3 border-b flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Terminal className="w-4 h-4 text-gray-900" />
          <h3 className="text-sm font-semibold text-gray-900">Activity Logs</h3>
          <span className="text-xs text-gray-500">({logs.length} entries)</span>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setIsPaused(!isPaused)}
            className="p-1.5 hover:bg-gray-200 rounded transition-colors"
            title={isPaused ? 'Resume' : 'Pause'}
          >
            {isPaused ? (
              <Play className="w-4 h-4 text-gray-500" />
            ) : (
              <Pause className="w-4 h-4 text-gray-500" />
            )}
          </button>
          <button
            onClick={clearLogs}
            className="p-1.5 hover:bg-gray-200 rounded transition-colors"
            title="Clear logs"
          >
            <Trash2 className="w-4 h-4 text-gray-500" />
          </button>
        </div>
      </div>

      {/* Logs */}
      <div className="h-64 overflow-y-auto font-mono text-xs">
        {logs.length === 0 ? (
          <div className="flex items-center justify-center h-full text-gray-500">
            <div className="text-center">
              <Terminal className="w-8 h-8 mx-auto mb-2 opacity-50" />
              <p>No activity yet</p>
              <p className="text-xs mt-1">Submit a query to see logs</p>
            </div>
          </div>
        ) : (
          <div className="p-2 space-y-1">
            {logs.map((log) => (
              <div
                key={log.id}
                className={`flex gap-2 p-2 rounded ${getLevelBg(log.level)}`}
              >
                <span className="text-gray-500 select-none">
                  {formatTime(log.timestamp)}
                </span>
                <span className={`font-semibold ${getLevelColor(log.level)}`}>
                  [{log.level.toUpperCase()}]
                </span>
                <span className="text-gray-900 flex-1">{log.message}</span>
              </div>
            ))}
            <div ref={logsEndRef} />
          </div>
        )}
      </div>

      {/* Footer */}
      <div className="px-4 py-2 border-t">
        <div className="flex items-center gap-4 text-xs text-gray-500">
          <div className="flex items-center gap-1">
            <div className="w-2 h-2 rounded-full bg-db-gray"></div>
            <span>Info</span>
          </div>
          <div className="flex items-center gap-1">
            <div className="w-2 h-2 rounded-full bg-db-navy"></div>
            <span>Success</span>
          </div>
          <div className="flex items-center gap-1">
            <div className="w-2 h-2 rounded-full bg-db-gold"></div>
            <span>Warning</span>
          </div>
          <div className="flex items-center gap-1">
            <div className="w-2 h-2 rounded-full bg-db-lava"></div>
            <span>Error</span>
          </div>
        </div>
      </div>
    </div>
  );
};

export default LogsDisplay;
