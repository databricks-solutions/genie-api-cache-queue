import { useState, useEffect } from 'react';
import ChatInterface from './components/ChatInterface';
import CacheTable from './components/CacheTable';
import QueueTable from './components/QueueTable';
import FlowDiagram from './components/FlowDiagram';
import LogsDisplay from './components/LogsDisplay';
import Settings from './components/Settings';
import Debug from './components/Debug';
import ApiReference from './components/ApiReference';
import { Database, ListOrdered, MessageSquare, Settings as SettingsIcon, Bug, Code2 } from 'lucide-react';

function App() {
  const [activeTab, setActiveTab] = useState('chat');
  const [showConfigWarning, setShowConfigWarning] = useState(false);

  const [chatTabs, setChatTabs] = useState([]);
  const [activeChatTabId, setActiveChatTabId] = useState(null);

  useEffect(() => {
    const config = localStorage.getItem('databricks_config');
    if (!config) {
      setShowConfigWarning(true);
      setActiveTab('settings');
    } else {
      const parsed = JSON.parse(config);
      const hasSpaces = (parsed.genie_spaces && parsed.genie_spaces.length > 0) || parsed.genie_space_id;
      if (!hasSpaces || !parsed.sql_warehouse_id) {
        setShowConfigWarning(true);
      }
    }
  }, []);

  const getStorageLabel = () => {
    const config = localStorage.getItem('databricks_config');
    if (config) {
      const parsed = JSON.parse(config);
      return parsed.storage_backend === 'lakebase' ? 'Cache (Lakebase)' : 'Cache (Local)';
    }
    return 'Cache';
  };

  const tabs = [
    { id: 'chat', name: 'Chat & Flow', icon: MessageSquare },
    { id: 'cache', name: getStorageLabel(), icon: Database },
    { id: 'queue', name: 'Query Logs', icon: ListOrdered },
    { id: 'api', name: 'API', icon: Code2 },
    { id: 'settings', name: 'Settings', icon: SettingsIcon },
    { id: 'debug', name: 'Debug', icon: Bug },
  ];

  return (
    <div className="min-h-screen bg-db-bg">
      {/* Header */}
      <header className="bg-db-navy shadow-md">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex justify-between items-center py-4">
            <div className="flex items-center gap-3">
              {/* Databricks Logo Mark */}
              <svg width="32" height="32" viewBox="0 0 40 40" fill="none" xmlns="http://www.w3.org/2000/svg">
                <path d="M20 2L4 11.2V20L20 29.2L36 20V11.2L20 2Z" fill="#FF3621"/>
                <path d="M20 29.2L4 20V28.8L20 38L36 28.8V20L20 29.2Z" fill="#FF3621" opacity="0.7"/>
              </svg>
              <div>
                <h1 className="text-2xl font-bold text-white font-sans">
                  Genie Cache & Queue
                </h1>
                <p className="text-sm text-white/50">
                  Intelligent query caching and rate limiting
                </p>
              </div>
            </div>
          </div>

          {/* Tabs */}
          <div className="flex space-x-1">
            {tabs.map((tab) => {
              const Icon = tab.icon;
              return (
                <button
                  key={tab.id}
                  onClick={() => setActiveTab(tab.id)}
                  className={`flex items-center gap-2 px-4 py-2.5 font-medium text-sm transition-colors border-b-2 ${
                    activeTab === tab.id
                      ? 'text-white border-db-lava'
                      : 'text-white/60 border-transparent hover:text-white/90 hover:border-white/20'
                  }`}
                >
                  <Icon className="w-4 h-4" />
                  {tab.name}
                </button>
              );
            })}
          </div>
        </div>
      </header>

      {/* Configuration Warning */}
      {showConfigWarning && activeTab !== 'settings' && (
        <div className="max-w-[1920px] mx-auto px-4 sm:px-6 lg:px-8 py-4">
          <div className="bg-db-oat border-l-4 border-db-navy p-4 rounded-r-lg">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <SettingsIcon className="w-5 h-5 text-db-navy" />
                <div>
                  <p className="text-sm font-medium text-db-navy">
                    Configuration Required
                  </p>
                  <p className="text-xs text-db-gray mt-1">
                    Please configure your Databricks credentials in Settings to use the app
                  </p>
                </div>
              </div>
              <button
                onClick={() => setActiveTab('settings')}
                className="px-4 py-2 bg-db-navy text-white text-sm rounded-lg hover:bg-db-navy/90"
              >
                Go to Settings
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Main Content */}
      <main className="max-w-[1920px] mx-auto px-4 sm:px-6 lg:px-8 py-6">
        {activeTab === 'chat' && (
          <div className="space-y-6">
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
              <div className="lg:col-span-2">
                <ChatInterface
                  tabs={chatTabs}
                  setTabs={setChatTabs}
                  activeTabId={activeChatTabId}
                  setActiveTabId={setActiveChatTabId}
                />
              </div>
              <div className="lg:col-span-1">
                <FlowDiagram
                  chatTabs={chatTabs}
                  activeChatTabId={activeChatTabId}
                />
              </div>
            </div>
            <div>
              <LogsDisplay chatTabs={chatTabs} />
            </div>
          </div>
        )}
        {activeTab === 'cache' && <CacheTable />}
        {activeTab === 'queue' && <QueueTable />}
        {activeTab === 'api' && <ApiReference />}
        {activeTab === 'settings' && <Settings />}
        {activeTab === 'debug' && <Debug />}
      </main>
    </div>
  );
}

export default App;
