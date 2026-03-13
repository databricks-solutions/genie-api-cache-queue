import { useState, useEffect, useRef } from 'react';
import { api } from '../services/api';
import { Send, X, Loader, CheckCircle, XCircle, Plus } from 'lucide-react';

const ChatInterface = ({ tabs, setTabs, activeTabId, setActiveTabId }) => {
  const [inputValue, setInputValue] = useState('');
  const messagesEndRef = useRef(null);
  const activeTabMessages = tabs.find(t => t.id === activeTabId)?.messages;

  useEffect(() => {
    if (messagesEndRef.current) {
      messagesEndRef.current.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }
  }, [activeTabMessages]);

  const createNewTab = () => {
    const tabNumber = tabs.length + 1;
    const newTab = {
      id: `tab-${Date.now()}`,
      name: `Chat ${tabNumber}`,
      queryIds: [],
      status: null,
      messages: [],
      polling: false,
      conversationId: null,
      conversationSynced: true,
      conversationHistory: [],
    };
    setTabs([...tabs, newTab]);
    setActiveTabId(newTab.id);
  };

  const closeTab = (tabId) => {
    const newTabs = tabs.filter((t) => t.id !== tabId);
    setTabs(newTabs);
    if (activeTabId === tabId && newTabs.length > 0) {
      setActiveTabId(newTabs[0].id);
    }
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!inputValue.trim()) return;

    const query = inputValue;
    setInputValue('');

    if (tabs.length === 0) {
      const newTabId = `tab-${Date.now()}`;
      const newTab = {
        id: newTabId,
        name: `Chat 1`,
        queryIds: [],
        status: null,
        messages: [
          {
            role: 'user',
            content: query,
            timestamp: new Date(),
          },
        ],
        polling: true,
        conversationId: null,
        conversationSynced: true,
        conversationHistory: [],
      };

      setTabs([newTab]);
      setActiveTabId(newTabId);

      try {
        // First message in new tab — no conversation context
        const response = await api.submitQuery(query, 'system', {});

        const queryLog = {
          query_id: response.query_id,
          query_text: query,
          identity: 'system',
          stage: 'received',
          created_at: new Date().toISOString(),
          from_cache: false,
        };
        const existingLogs = JSON.parse(localStorage.getItem('query_logs') || '[]');
        existingLogs.unshift(queryLog);
        localStorage.setItem('query_logs', JSON.stringify(existingLogs.slice(0, 100)));

        const config = api.getConfig();
        if (config.storage_backend === 'lakebase') {
          api.saveQueryLog(
            response.query_id, query, 'system', 'received', false, config.genie_space_id
          ).catch(() => {});
        }

        setTabs((prevTabs) =>
          prevTabs.map((tab) => {
            if (tab.id === newTabId) {
              return {
                ...tab,
                queryIds: [response.query_id],
                conversationHistory: [query],
              };
            }
            return tab;
          })
        );

        pollQueryStatus(newTabId, response.query_id);
      } catch (error) {
        setTabs((prevTabs) =>
          prevTabs.map((tab) => {
            if (tab.id === newTabId) {
              return {
                ...tab,
                messages: [
                  ...tab.messages,
                  { role: 'error', content: `Error: ${error.message}`, timestamp: new Date() },
                ],
                polling: false,
              };
            }
            return tab;
          })
        );
      }
      return;
    }

    let currentTabId = activeTabId;
    if (!currentTabId && tabs.length > 0) {
      currentTabId = tabs[0].id;
      setActiveTabId(currentTabId);
    }

    try {
      setTabs((prevTabs) => {
        return prevTabs.map((tab) => {
          if (tab.id === currentTabId) {
            return {
              ...tab,
              messages: [
                ...(tab.messages || []),
                { role: 'user', content: query, timestamp: new Date() },
              ],
              polling: true,
            };
          }
          return tab;
        });
      });

      // Gather conversation context from current tab
      const currentTab = tabs.find(t => t.id === currentTabId);
      const conversationContext = {
        conversationId: currentTab?.conversationId || null,
        conversationSynced: currentTab?.conversationSynced ?? true,
        conversationHistory: currentTab?.conversationHistory || [],
      };

      const response = await api.submitQuery(query, 'system', conversationContext);

      const queryLog = {
        query_id: response.query_id,
        query_text: query,
        identity: 'system',
        stage: 'received',
        created_at: new Date().toISOString(),
        from_cache: false,
      };
      const existingLogs = JSON.parse(localStorage.getItem('query_logs') || '[]');
      existingLogs.unshift(queryLog);
      localStorage.setItem('query_logs', JSON.stringify(existingLogs.slice(0, 100)));

      const config = api.getConfig();
      if (config.storage_backend === 'lakebase') {
        api.saveQueryLog(
          response.query_id, query, 'system', 'received', false, config.genie_space_id
        ).catch(() => {});
      }

      setTabs((prevTabs) => {
        return prevTabs.map((tab) => {
          if (tab.id === currentTabId) {
            return {
              ...tab,
              queryIds: [...(tab.queryIds || []), response.query_id],
              conversationHistory: [...(tab.conversationHistory || []), query],
            };
          }
          return tab;
        });
      });

      pollQueryStatus(currentTabId, response.query_id);
    } catch (error) {
      setTabs((prevTabs) =>
        prevTabs.map((tab) => {
          if (tab.id === currentTabId) {
            return {
              ...tab,
              messages: [
                ...(tab.messages || []),
                { role: 'error', content: `Error: ${error.message}`, timestamp: new Date() },
              ],
              polling: false,
            };
          }
          return tab;
        })
      );
    }
  };

  const pollQueryStatus = async (tabId, queryId) => {
    const pollInterval = setInterval(async () => {
      try {
        const status = await api.getQueryStatus(queryId);

        const existingLogs = JSON.parse(localStorage.getItem('query_logs') || '[]');
        const logIndex = existingLogs.findIndex(log => log.query_id === queryId);
        if (logIndex !== -1) {
          existingLogs[logIndex] = {
            ...existingLogs[logIndex],
            stage: status.stage,
            from_cache: status.from_cache || false,
          };
          localStorage.setItem('query_logs', JSON.stringify(existingLogs));

          const config = api.getConfig();
          if (config.storage_backend === 'lakebase') {
            api.saveQueryLog(
              queryId, existingLogs[logIndex].query_text, existingLogs[logIndex].identity,
              status.stage, status.from_cache || false, config.genie_space_id
            ).catch(() => {});
          }
        }

        setTabs((prevTabs) => {
          const updatedTabs = prevTabs.map((tab) => {
            if (tab.id === tabId) {
              const prevSeenStages = tab.seenStages || new Set();
              const seenStages = new Set(prevSeenStages);
              seenStages.add(status.stage);
              const updatedTab = { ...tab, status, seenStages };

              const lastMessage = updatedTab.messages[updatedTab.messages.length - 1];
              if (!lastMessage || lastMessage.stage !== status.stage) {
                updatedTab.messages = [...updatedTab.messages, {
                  role: 'system',
                  content: getStageMessage(status.stage),
                  stage: status.stage,
                  timestamp: new Date(),
                }];
              }

              if (status.stage === 'completed' || status.stage === 'failed') {
                clearInterval(pollInterval);
                updatedTab.polling = false;

                if (status.stage === 'completed') {
                  // Update conversation tracking
                  if (status.conversation_id) {
                    // Genie was called — conversation is synced
                    updatedTab.conversationId = status.conversation_id;
                    updatedTab.conversationSynced = true;
                  } else if (status.from_cache) {
                    // Cache hit — Genie was NOT called, conversation is desynced
                    updatedTab.conversationSynced = false;
                  }

                  updatedTab.messages = [...updatedTab.messages, {
                    role: 'assistant',
                    content: formatResult(status),
                    timestamp: new Date(),
                  }];
                } else {
                  updatedTab.messages = [...updatedTab.messages, {
                    role: 'error',
                    content: status.error || 'Query failed',
                    timestamp: new Date(),
                  }];
                }
              }

              return updatedTab;
            }
            return tab;
          });

          return updatedTabs;
        });
      } catch {
        clearInterval(pollInterval);
      }
    }, 2000);
  };

  const getStageMessage = (stage) => {
    const messages = {
      received: 'Query received',
      checking_cache: 'Checking cache for similar queries...',
      cache_hit: 'Found in cache! Executing SQL...',
      cache_miss: 'Not in cache, sending to Genie API...',
      queued: 'Rate limit reached, query queued',
      processing_genie: 'Processing with Genie API...',
      executing_sql: 'Executing SQL query...',
      completed: 'Query completed',
      failed: 'Query failed',
    };
    return messages[stage] || stage;
  };

  const formatResult = (status) => {
    let text = '';

    if (status.from_cache) {
      text += '**From Cache**\n\n';
    }

    if (status.sql_query) {
      text += `**SQL Query:**\n\`\`\`sql\n${status.sql_query}\n\`\`\`\n\n`;
    }

    if (status.result) {
      text += `**Result:**\n${JSON.stringify(status.result, null, 2)}`;
    }

    return text;
  };

  const activeTab = tabs.find((t) => t.id === activeTabId);

  return (
    <div className="bg-white rounded-lg border border-gray-300 h-[calc(100vh-200px)] flex flex-col">
      {/* Tabs */}
      <div className="flex border-b border-gray-300 overflow-x-auto">
        {tabs.map((tab) => (
          <div
            key={tab.id}
            className={`flex items-center gap-2 px-4 py-2 border-r border-gray-300 cursor-pointer transition-colors ${
              activeTabId === tab.id
                ? 'border-b-2 border-b-db-lava text-gray-900 font-medium'
                : 'text-gray-500 hover:bg-gray-100'
            }`}
            onClick={() => setActiveTabId(tab.id)}
          >
            {tab.polling && <Loader className="w-3 h-3 animate-spin text-gray-900" />}
            {!tab.polling && tab.status?.stage === 'completed' && (
              <CheckCircle className="w-3 h-3 text-db-navy" />
            )}
            {!tab.polling && tab.status?.stage === 'failed' && (
              <XCircle className="w-3 h-3 text-db-lava" />
            )}
            <span className="text-sm truncate max-w-[150px]">
              {tab.name || 'New Chat'}
            </span>
            <button
              onClick={(e) => {
                e.stopPropagation();
                closeTab(tab.id);
              }}
              className="text-gray-500 hover:bg-gray-200 rounded p-0.5"
            >
              <X className="w-3 h-3" />
            </button>
          </div>
        ))}

        <button
          onClick={createNewTab}
          className="flex items-center gap-2 px-4 py-2 text-gray-500 hover:bg-gray-100 border-r border-gray-300 transition-colors"
          title="New chat tab"
        >
          <Plus className="w-4 h-4" />
          <span className="text-sm">New</span>
        </button>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {!activeTab && tabs.length === 0 && (
          <div className="text-center mt-20 text-gray-500">
            <p className="text-lg font-medium">No chat tabs open</p>
            <p className="text-sm mt-1">Click "New" to create a tab, or submit a query below.</p>
          </div>
        )}

        {!activeTab && tabs.length > 0 && (
          <div className="text-center mt-20 text-gray-500">
            <p className="text-lg font-medium">Select a tab to view the conversation.</p>
          </div>
        )}

        {activeTab && activeTab.messages.length === 0 && (
          <div className="text-center mt-20 text-gray-500">
            <p className="text-sm">Submit a query below to begin.</p>
          </div>
        )}

        {activeTab && activeTab.messages && activeTab.messages.length > 0 &&
          activeTab.messages.map((msg, idx) => (
            <div
              key={idx}
              className={`flex ${
                msg.role === 'user' ? 'justify-end' : 'justify-start'
              }`}
            >
              <div
                className={`max-w-[80%] rounded-lg px-4 py-2 ${
                  msg.role === 'user'
                    ? 'bg-gray-900 text-white'
                    : msg.role === 'error'
                    ? 'bg-gray-100 text-db-lava border border-gray-300'
                    : msg.role === 'system'
                    ? 'bg-gray-200 text-gray-500 text-sm'
                    : 'bg-white text-gray-900 border border-gray-300'
                }`}
              >
                <pre className="whitespace-pre-wrap font-sans">
                  {msg.content}
                </pre>
              </div>
            </div>
          ))}
        <div ref={messagesEndRef} />
      </div>

      {/* Input */}
      <div className="border-t border-gray-300 p-4">
        {activeTab && (
          <div className="text-xs mb-2 text-gray-500">
            Chatting in: <span className="font-semibold text-gray-900">{activeTab.name}</span>
          </div>
        )}
        <form onSubmit={handleSubmit} className="flex gap-2">
          <input
            type="text"
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            placeholder={
              tabs.length === 0
                ? "Type a message to start a new conversation..."
                : activeTab
                ? "Type your message..."
                : "Select or create a tab first..."
            }
            className="flex-1 px-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-db-lava focus:border-transparent"
          />
          <button
            type="submit"
            disabled={!inputValue.trim()}
            className="px-6 py-2 text-white rounded-lg bg-gray-900 disabled:bg-gray-300 disabled:cursor-not-allowed flex items-center gap-2 transition-colors"
          >
            <Send className="w-4 h-4" />
            Send
          </button>
        </form>
      </div>
    </div>
  );
};

export default ChatInterface;
