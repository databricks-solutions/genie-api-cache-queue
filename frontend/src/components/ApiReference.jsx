import { useState } from 'react';
import { Copy, Check, ChevronDown, ChevronRight } from 'lucide-react';
import { api } from '../services/api';

const ApiReference = () => {
  const [copied, setCopied] = useState(null);
  const [expandedSections, setExpandedSections] = useState({
    'clone-start': true,
    'clone-poll': true,
    'clone-result': false,
    'clone-execute': false,
    'clone-space': false,
    'proxy-async': false,
    'proxy-poll': false,
    'proxy-sync': false,
    'config-get': false,
    'config-put': false,
    'mgmt-cache': false,
    'mgmt-queue': false,
    'mgmt-logs': false,
    'notebook': false,
  });

  const baseUrl = window.location.origin;
  const config = api.getConfig();
  const spaceId = api.getActiveSpaceId() || config.genie_space_id || '<SPACE_ID>';
  const spaceName = api.getSpaceName(spaceId);
  const genieSpaces = config.genie_spaces || [];
  const warehouseId = config.sql_warehouse_id || '<WAREHOUSE_ID>';

  const copyToClipboard = (text, id) => {
    navigator.clipboard.writeText(text);
    setCopied(id);
    setTimeout(() => setCopied(null), 2000);
  };

  const toggleSection = (key) => {
    setExpandedSections((prev) => ({ ...prev, [key]: !prev[key] }));
  };

  const CopyButton = ({ text, id }) => (
    <button
      onClick={() => copyToClipboard(text, id)}
      className="absolute top-2 right-2 p-1.5 rounded bg-gray-700 hover:bg-gray-600 transition-colors"
      title="Copy to clipboard"
    >
      {copied === id ? <Check className="w-3.5 h-3.5 text-green-400" /> : <Copy className="w-3.5 h-3.5 text-gray-300" />}
    </button>
  );

  const SectionHeader = ({ id, title, method, path }) => (
    <button onClick={() => toggleSection(id)} className="w-full flex items-center gap-3 text-left">
      {expandedSections[id] ? <ChevronDown className="w-4 h-4 text-gray-400 flex-shrink-0" /> : <ChevronRight className="w-4 h-4 text-gray-400 flex-shrink-0" />}
      <div className="flex items-center gap-2 flex-wrap">
        {method && (
          <span className={`text-xs font-bold px-2 py-0.5 rounded ${method === 'POST' ? 'bg-green-100 text-green-700' : method === 'PUT' ? 'bg-yellow-100 text-yellow-700' : 'bg-blue-100 text-blue-700'}`}>
            {method}
          </span>
        )}
        <code className="text-sm font-mono text-gray-900">{path}</code>
        <span className="text-sm text-gray-500">— {title}</span>
      </div>
    </button>
  );

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      {/* Header */}
      <div className="bg-white rounded-lg shadow-sm border">
        <div className="px-6 py-4 border-b">
          <h2 className="text-xl font-semibold text-gray-900">API Reference</h2>
          <p className="text-sm text-gray-500 mt-1">
            Duas APIs disponiveis: <strong>Drop-in Genie API</strong> (substitui a API do Genie sem mudar codigo) e <strong>Proxy API</strong> (REST simplificada).
          </p>
        </div>
        <div className="p-6 space-y-4">
          <div className="p-4 rounded-lg border bg-gray-200 border-gray-300">
            <p className="text-sm font-medium text-gray-900 mb-1">Autenticacao</p>
            <p className="text-xs text-gray-700">
              Todos os endpoints requerem <code className="bg-gray-300 px-1 rounded">Authorization: Bearer &lt;token&gt;</code> (OAuth JWT ou PAT).
            </p>
          </div>
          {(genieSpaces.length > 0 || config.genie_space_id) && (
            <div className="p-3 rounded-lg bg-gray-100 border text-xs text-gray-600 space-y-1">
              <div>
                <span className="font-medium">Config atual:</span>{' '}
                warehouse_id={config.sql_warehouse_id || 'nao definido'}
              </div>
              {genieSpaces.length > 0 ? (
                <div className="flex flex-wrap gap-1.5 mt-1">
                  {genieSpaces.map((s) => (
                    <span
                      key={s.id}
                      className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs ${
                        s.id === spaceId
                          ? 'bg-[#0B2026] text-white'
                          : 'bg-gray-200 text-gray-700'
                      }`}
                    >
                      {s.name || s.id.slice(0, 8)}
                      <span className="opacity-60 font-mono">{s.id.slice(0, 8)}</span>
                    </span>
                  ))}
                </div>
              ) : (
                <div>space_id={config.genie_space_id}</div>
              )}
            </div>
          )}
        </div>
      </div>

      {/* ===== DROP-IN GENIE API ===== */}
      <div className="bg-white rounded-lg shadow-sm border">
        <div className="px-6 py-4 border-b bg-green-50">
          <h3 className="text-lg font-semibold text-gray-900">Drop-in Genie API</h3>
          <p className="text-xs text-gray-600 mt-1">
            Mesmos endpoints da API oficial do Genie. So troca a URL base — zero mudanca no codigo do client.
          </p>
          <div className="mt-3 p-3 rounded-lg bg-white border border-green-200 text-xs">
            <span className="font-medium text-green-800">Antes:</span>{' '}
            <code className="text-green-700">https://&lt;workspace&gt;.cloud.databricks.com</code>
            <br />
            <span className="font-medium text-green-800">Depois:</span>{' '}
            <code className="text-green-700">{baseUrl}</code>
          </div>
        </div>

        <div className="divide-y">
          {/* POST start-conversation */}
          <div className="p-6 space-y-4">
            <SectionHeader id="clone-start" title="Iniciar conversa" method="POST" path={`/api/2.0/genie/spaces/{space_id}/start-conversation`} />
            {expandedSections['clone-start'] && (
              <div className="pl-7 space-y-3">
                <p className="text-sm text-gray-600">
                  Cache hit → retorna <code className="bg-green-100 text-green-700 px-1 rounded">COMPLETED</code> com SQL executada.
                  Cache miss → retorna <code className="bg-blue-100 text-blue-700 px-1 rounded">EXECUTING_QUERY</code>, processa no background.
                </p>
                <div>
                  <p className="text-xs font-medium text-gray-500 mb-1">Request Body</p>
                  <pre className="bg-gray-900 text-gray-100 rounded-lg p-4 text-xs overflow-x-auto">
{`{ "content": "How many customers are there?" }`}
                  </pre>
                </div>
                <div>
                  <p className="text-xs font-medium text-gray-500 mb-1">Response (cache miss)</p>
                  <pre className="bg-gray-900 text-gray-100 rounded-lg p-4 text-xs overflow-x-auto">
{`{
  "conversation_id": "ccache_...",
  "message_id": "mcache_...",
  "status": "EXECUTING_QUERY",
  "attachments": []
}`}
                  </pre>
                </div>
                <div>
                  <p className="text-xs font-medium text-gray-500 mb-1">curl</p>
                  <div className="relative">
                    <pre className="bg-gray-900 text-gray-100 rounded-lg p-4 text-xs overflow-x-auto pr-12">
{`curl -X POST ${baseUrl}/api/2.0/genie/spaces/${spaceId}/start-conversation \\
  -H "Authorization: Bearer $TOKEN" \\
  -H "Content-Type: application/json" \\
  -d '{"content": "How many customers are there?"}'`}
                    </pre>
                    <CopyButton text={`curl -X POST ${baseUrl}/api/2.0/genie/spaces/${spaceId}/start-conversation -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{"content": "How many customers are there?"}'`} id="curl-clone-start" />
                  </div>
                </div>
              </div>
            )}
          </div>

          {/* GET get-message (poll) */}
          <div className="p-6 space-y-4">
            <SectionHeader id="clone-poll" title="Poll resultado (get-message)" method="GET" path={`/api/2.0/genie/spaces/{space_id}/conversations/{conv_id}/messages/{msg_id}`} />
            {expandedSections['clone-poll'] && (
              <div className="pl-7 space-y-3">
                <p className="text-sm text-gray-600">
                  Pollar a cada 2s ate <code className="bg-green-100 text-green-700 px-1 rounded">COMPLETED</code> ou <code className="bg-red-100 text-red-700 px-1 rounded">FAILED</code>.
                </p>
                <div>
                  <p className="text-xs font-medium text-gray-500 mb-1">Response (completed)</p>
                  <pre className="bg-gray-900 text-gray-100 rounded-lg p-4 text-xs overflow-x-auto">
{`{
  "conversation_id": "...",
  "message_id": "...",
  "status": "COMPLETED",
  "attachments": [
    {
      "attachment_id": "...",
      "query": {
        "query": "SELECT COUNT(*) FROM ...",
        "description": "...",
        "statement_id": "...",
        "query_result_metadata": { "row_count": 1 }
      }
    },
    { "text": { "content": "There are 750,000 customers." } }
  ]
}`}
                  </pre>
                </div>
              </div>
            )}
          </div>

          {/* GET query-result */}
          <div className="p-6 space-y-4">
            <SectionHeader id="clone-result" title="Obter dados da query" method="GET" path={`.../messages/{msg_id}/attachments/{att_id}/query-result`} />
            {expandedSections['clone-result'] && (
              <div className="pl-7 space-y-3">
                <p className="text-sm text-gray-600">
                  Retorna os dados reais da execucao SQL. Formato identico a API do Genie (<code className="bg-gray-100 px-1 rounded">statement_response</code>).
                </p>
                <div>
                  <p className="text-xs font-medium text-gray-500 mb-1">Response</p>
                  <pre className="bg-gray-900 text-gray-100 rounded-lg p-4 text-xs overflow-x-auto">
{`{
  "statement_response": {
    "statement_id": "...",
    "status": "SUCCEEDED",
    "result": {
      "row_count": 3,
      "data_array": [
        ["IRAQ", "44199396357.7281"],
        ["INDONESIA", "44156732316.9634"],
        ["GERMANY", "43966473754.5423"]
      ]
    }
  }
}`}
                  </pre>
                </div>
              </div>
            )}
          </div>

          {/* POST execute-query */}
          <div className="p-6 space-y-4">
            <SectionHeader id="clone-execute" title="Re-executar query" method="POST" path={`.../messages/{msg_id}/attachments/{att_id}/execute-query`} />
            {expandedSections['clone-execute'] && (
              <div className="pl-7">
                <p className="text-sm text-gray-600">Re-executa a SQL contra o warehouse. Mesmo formato de resposta do query-result.</p>
              </div>
            )}
          </div>

          {/* GET space */}
          <div className="p-6 space-y-4">
            <SectionHeader id="clone-space" title="Metadata do space" method="GET" path={`/api/2.0/genie/spaces/{space_id}`} />
            {expandedSections['clone-space'] && (
              <div className="pl-7">
                <p className="text-sm text-gray-600">Proxy direto para a API do Genie. Retorna metadata do space.</p>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* ===== NOTEBOOK EXAMPLE ===== */}
      <div className="bg-white rounded-lg shadow-sm border">
        <div className="p-6 space-y-4">
          <button onClick={() => toggleSection('notebook')} className="w-full flex items-center gap-3 text-left">
            {expandedSections.notebook ? <ChevronDown className="w-4 h-4 text-gray-400" /> : <ChevronRight className="w-4 h-4 text-gray-400" />}
            <span className="text-sm font-medium text-gray-900">Exemplo Python — Drop-in (mesmo codigo para Genie e App)</span>
          </button>
          {expandedSections.notebook && (
            <div className="relative">
              <pre className="bg-gray-900 text-gray-100 rounded-lg p-4 text-xs overflow-x-auto pr-12">
{`import requests, time

# So muda esta linha para trocar entre Genie direto e App
BASE = "${baseUrl}"   # ou "https://<workspace>.cloud.databricks.com"
SPACE = "${spaceId}"
H = {"Authorization": f"Bearer {'{TOKEN}'}", "Content-Type": "application/json"}

# 1. Configurar (so precisa uma vez)
requests.put(f"{'{BASE}'}/api/v1/config", headers=H, json={
    "genie_spaces": [{"id": SPACE, "name": "${spaceName || 'My Space'}"}],
    "sql_warehouse_id": "${warehouseId}",
    "similarity_threshold": 0.92,
    "cache_ttl_seconds": 86400,
})

# 2. start-conversation
r = requests.post(f"{'{BASE}'}/api/2.0/genie/spaces/{'{SPACE}'}/start-conversation",
    headers=H, json={"content": "How many customers?"})
data = r.json()
conv_id, msg_id = data["conversation_id"], data["message_id"]

# 3. Poll get-message
if data.get("status") != "COMPLETED":
    for _ in range(60):
        time.sleep(2)
        data = requests.get(
            f"{'{BASE}'}/api/2.0/genie/spaces/{'{SPACE}'}/conversations/{'{conv_id}'}/messages/{'{msg_id}'}",
            headers=H).json()
        if data.get("status") in ("COMPLETED", "FAILED"):
            break

# 4. Extrair SQL e buscar dados
for att in data.get("attachments", []):
    if att.get("query"):
        att_id = att["attachment_id"]
        sql = att["query"]["query"]
        # Buscar dados reais
        qr = requests.get(
            f"{'{BASE}'}/api/2.0/genie/spaces/{'{SPACE}'}/conversations/{'{conv_id}'}"
            f"/messages/{'{msg_id}'}/attachments/{'{att_id}'}/query-result",
            headers=H).json()
        result = qr.get("statement_response", qr).get("result", {})
        print(f"SQL: {'{sql}'}")
        print(f"Dados: {result.get('data_array', [])}")`}
              </pre>
              <CopyButton text="(veja o demo_notebook.ipynb para o exemplo completo)" id="notebook" />
            </div>
          )}
        </div>
      </div>

      {/* ===== CONFIGURATION ===== */}
      <div className="bg-white rounded-lg shadow-sm border divide-y">
        <div className="px-6 py-4 border-b">
          <h3 className="text-lg font-semibold text-gray-900">Configuracao</h3>
          <p className="text-xs text-gray-500 mt-1">Mesma config usada pela UI (Settings) e pela Clone API. Mudanca em um reflete no outro.</p>
        </div>

        <div className="p-6 space-y-4">
          <SectionHeader id="config-get" title="Ler configuracao" method="GET" path="/api/v1/config" />
          {expandedSections['config-get'] && (
            <div className="pl-7 space-y-3">
              <div className="relative">
                <pre className="bg-gray-900 text-gray-100 rounded-lg p-4 text-xs overflow-x-auto pr-12">
{`curl ${baseUrl}/api/v1/config \\
  -H "Authorization: Bearer $TOKEN"`}
                </pre>
                <CopyButton text={`curl ${baseUrl}/api/v1/config -H "Authorization: Bearer $TOKEN"`} id="curl-config-get" />
              </div>
            </div>
          )}
        </div>

        <div className="p-6 space-y-4">
          <SectionHeader id="config-put" title="Atualizar configuracao" method="PUT" path="/api/v1/config" />
          {expandedSections['config-put'] && (
            <div className="pl-7 space-y-3">
              <p className="text-sm text-gray-600">Envia apenas os campos que quer alterar.</p>
              <div className="relative">
                <pre className="bg-gray-900 text-gray-100 rounded-lg p-4 text-xs overflow-x-auto pr-12">
{`curl -X PUT ${baseUrl}/api/v1/config \\
  -H "Authorization: Bearer $TOKEN" \\
  -H "Content-Type: application/json" \\
  -d '{
    "genie_spaces": ${JSON.stringify(genieSpaces.length > 0 ? genieSpaces : [{ id: spaceId, name: "My Space" }])},
    "sql_warehouse_id": "${warehouseId}",
    "similarity_threshold": 0.92,
    "max_queries_per_minute": 5,
    "cache_ttl_seconds": 86400
  }'`}
                </pre>
                <CopyButton text={`curl -X PUT ${baseUrl}/api/v1/config -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{"genie_spaces": ${JSON.stringify(genieSpaces.length > 0 ? genieSpaces : [{ id: spaceId, name: "My Space" }])}, "sql_warehouse_id": "${warehouseId}", "similarity_threshold": 0.92, "max_queries_per_minute": 5, "cache_ttl_seconds": 86400}'`} id="curl-config-put" />
              </div>
            </div>
          )}
        </div>
      </div>

      {/* ===== PROXY API ===== */}
      <div className="bg-white rounded-lg shadow-sm border divide-y">
        <div className="px-6 py-4 border-b">
          <h3 className="text-lg font-semibold text-gray-900">Proxy API (REST simplificada)</h3>
          <p className="text-xs text-gray-500 mt-1">API propria do app com interface simplificada. Para apps que nao usam a API Genie diretamente.</p>
        </div>

        <div className="p-6 space-y-4">
          <SectionHeader id="proxy-async" title="Submeter query (async)" method="POST" path="/api/v1/query" />
          {expandedSections['proxy-async'] && (
            <div className="pl-7 space-y-3">
              <p className="text-sm text-gray-600">Retorna <code className="bg-gray-100 px-1 rounded">query_id</code>. Pollar <code className="bg-gray-100 px-1 rounded">GET /api/v1/query/{'{query_id}'}</code> para resultado.</p>
              <div className="relative">
                <pre className="bg-gray-900 text-gray-100 rounded-lg p-4 text-xs overflow-x-auto pr-12">
{`curl -X POST ${baseUrl}/api/v1/query \\
  -H "Authorization: Bearer $TOKEN" \\
  -H "Content-Type: application/json" \\
  -d '{"query": "How many customers?", "space_id": "${spaceId}", "warehouse_id": "${warehouseId}"}'`}
                </pre>
                <CopyButton text={`curl -X POST ${baseUrl}/api/v1/query -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{"query": "How many customers?", "space_id": "${spaceId}", "warehouse_id": "${warehouseId}"}'`} id="curl-proxy-async" />
              </div>
            </div>
          )}
        </div>

        <div className="p-6 space-y-4">
          <SectionHeader id="proxy-poll" title="Poll status" method="GET" path="/api/v1/query/{query_id}" />
          {expandedSections['proxy-poll'] && (
            <div className="pl-7">
              <p className="text-sm text-gray-600">Pollar ate <code className="bg-green-100 text-green-700 px-1 rounded">completed</code> ou <code className="bg-red-100 text-red-700 px-1 rounded">failed</code>.</p>
            </div>
          )}
        </div>

        <div className="p-6 space-y-4">
          <SectionHeader id="proxy-sync" title="Query sincrona (bloqueia ate 120s)" method="POST" path="/api/v1/query/sync" />
          {expandedSections['proxy-sync'] && (
            <div className="pl-7">
              <p className="text-sm text-gray-600">Mesmo que POST /query mas bloqueia ate o resultado estar pronto.</p>
            </div>
          )}
        </div>
      </div>

      {/* ===== MANAGEMENT ===== */}
      <div className="bg-white rounded-lg shadow-sm border divide-y">
        <div className="px-6 py-4 border-b">
          <h3 className="text-lg font-semibold text-gray-900">Gerenciamento</h3>
        </div>

        <div className="p-6 space-y-4">
          <SectionHeader id="mgmt-cache" title="Listar cache" method="GET" path="/api/v1/cache" />
          {expandedSections['mgmt-cache'] && (
            <div className="pl-7">
              <p className="text-sm text-gray-600">Retorna todas as queries cacheadas com SQL, uso e timestamps.</p>
            </div>
          )}
        </div>

        <div className="p-6 space-y-4">
          <SectionHeader id="mgmt-queue" title="Listar fila" method="GET" path="/api/v1/queue" />
          {expandedSections['mgmt-queue'] && (
            <div className="pl-7">
              <p className="text-sm text-gray-600">Queries aguardando na fila de rate limit.</p>
            </div>
          )}
        </div>

        <div className="p-6 space-y-4">
          <SectionHeader id="mgmt-logs" title="Logs de queries" method="GET" path="/api/v1/query-logs" />
          {expandedSections['mgmt-logs'] && (
            <div className="pl-7">
              <p className="text-sm text-gray-600">Ultimas 50 queries processadas com stage e cache hit info.</p>
            </div>
          )}
        </div>
      </div>

      {/* How it works */}
      <div className="bg-white rounded-lg shadow-sm border p-6">
        <h3 className="text-sm font-medium text-gray-900 mb-3">Como funciona</h3>
        <div className="space-y-2 text-xs text-gray-600">
          <div className="flex items-start gap-2"><span className="font-mono text-gray-400 w-4 text-right flex-shrink-0">1.</span><span>App envia query com Bearer token.</span></div>
          <div className="flex items-start gap-2"><span className="font-mono text-gray-400 w-4 text-right flex-shrink-0">2.</span><span>Busca no cache semantico (Lakebase/pgvector) por query similar.</span></div>
          <div className="flex items-start gap-2"><span className="font-mono text-gray-400 w-4 text-right flex-shrink-0">3.</span><span><strong>Cache hit:</strong> executa a SQL cacheada no warehouse e retorna dados frescos.</span></div>
          <div className="flex items-start gap-2"><span className="font-mono text-gray-400 w-4 text-right flex-shrink-0">4.</span><span><strong>Cache miss:</strong> chama a API Genie respeitando o limite de 5/min.</span></div>
          <div className="flex items-start gap-2"><span className="font-mono text-gray-400 w-4 text-right flex-shrink-0">5.</span><span><strong>Rate limit:</strong> query entra na fila com retry automatico.</span></div>
          <div className="flex items-start gap-2"><span className="font-mono text-gray-400 w-4 text-right flex-shrink-0">6.</span><span>Resultado e SQL sao cacheados para queries futuras similares.</span></div>
        </div>
      </div>
    </div>
  );
};

export default ApiReference;
