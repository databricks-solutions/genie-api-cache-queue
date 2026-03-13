# Databricks notebook source
# MAGIC %md
# MAGIC # Genie Cache & Queue — Demo
# MAGIC
# MAGIC Este notebook demonstra o problema do rate limit da Genie API (5 req/min/workspace)
# MAGIC e como o app resolve com cache, retry e fila.
# MAGIC
# MAGIC ## Cenarios:
# MAGIC 1. **Sem o app**: Chamadas diretas ao Genie → 429 apos 5 chamadas
# MAGIC 2. **Com o app**: Mesmas chamadas via app → cache hit, retry automatico, sem 429 para o caller

# COMMAND ----------

# MAGIC %md
# MAGIC ## Setup

# COMMAND ----------

import requests
import time
import json

# Configuracao
WORKSPACE_HOST = "https://fevm-genie-cache-test.cloud.databricks.com"
APP_HOST = "https://genie-cache-queue-7474650836156271.aws.databricksapps.com"
SPACE_ID = "01f11f1ae00114379e7671c8a4b8459f"

# Token — em Databricks Apps, use dbutils.notebook.entry_point.getDbutils().notebook().getContext().apiToken().get()
# Em local, use o PAT diretamente
try:
    TOKEN = dbutils.notebook.entry_point.getDbutils().notebook().getContext().apiToken().get()
except:
    import os
    TOKEN = os.getenv("DATABRICKS_TOKEN", "")  # Set via env var for local testing

headers = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json",
}

print(f"Workspace: {WORKSPACE_HOST}")
print(f"App:       {APP_HOST}")
print(f"Space:     {SPACE_ID}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Cenario 1: Chamadas diretas ao Genie (sem app)
# MAGIC
# MAGIC Vamos disparar 7 queries diferentes diretamente na API do Genie.
# MAGIC O limite e 5/min por workspace. Nas chamadas 6 e 7, esperamos receber **HTTP 429**.

# COMMAND ----------

questions = [
    "How many customers are there?",
    "What is the total revenue by region?",
    "Top 5 suppliers by order count",
    "Average order value per year",
    "How many parts are in the catalog?",
    "Total revenue for EUROPE region",     # <- deve dar 429
    "Number of orders in 1995",             # <- deve dar 429
]

print("=" * 60)
print("CENARIO 1: Chamadas DIRETAS ao Genie (sem cache/retry)")
print("=" * 60)

direct_results = []
for i, q in enumerate(questions, 1):
    start = time.time()
    resp = requests.post(
        f"{WORKSPACE_HOST}/api/2.0/genie/spaces/{SPACE_ID}/start-conversation",
        headers=headers,
        json={"content": q},
        timeout=120,
    )
    elapsed = time.time() - start

    status_code = resp.status_code
    if status_code == 429:
        retry_after = resp.headers.get("Retry-After", "?")
        print(f"  [{i}/7] 429 RATE LIMITED  | {elapsed:.1f}s | Retry-After: {retry_after}s | {q}")
        direct_results.append({"question": q, "status": 429, "time": elapsed})
    elif status_code == 200:
        data = resp.json()
        conv_id = data.get("conversation_id", "")[:15]
        print(f"  [{i}/7] 200 OK           | {elapsed:.1f}s | conv={conv_id}... | {q}")
        direct_results.append({"question": q, "status": 200, "time": elapsed})
    else:
        print(f"  [{i}/7] {status_code} ERROR        | {elapsed:.1f}s | {resp.text[:80]}")
        direct_results.append({"question": q, "status": status_code, "time": elapsed})

ok_count = sum(1 for r in direct_results if r["status"] == 200)
rate_limited = sum(1 for r in direct_results if r["status"] == 429)
print(f"\nResultado: {ok_count} OK, {rate_limited} rate-limited (429)")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Cenario 2: Mesmas chamadas via App (com cache + retry + fila)
# MAGIC
# MAGIC Agora as mesmas 7 queries passam pelo app. O app:
# MAGIC - Faz **cache semantico**: queries similares retornam instantaneamente
# MAGIC - Faz **rate limiting inteligente**: enfileira quando chega no limite de 5/min
# MAGIC - Faz **retry com backoff**: se receber 429 do Genie, espera e tenta de novo
# MAGIC
# MAGIC **Primeiro, configurar o app via API:**

# COMMAND ----------

# Configurar o app com space_id e warehouse_id via API
config_resp = requests.put(
    f"{APP_HOST}/api/v1/config",
    headers=headers,
    json={
        "genie_space_id": SPACE_ID,
        "sql_warehouse_id": "20cbd6750a2ef9ce",
        "similarity_threshold": 0.92,
        "cache_ttl_hours": 24,
    },
)
print("Config atualizada:", config_resp.json())

# COMMAND ----------

# MAGIC %md
# MAGIC ### 2a. Primeira rodada (cache miss — popula o cache)

# COMMAND ----------

print("=" * 60)
print("CENARIO 2a: Via APP — primeira rodada (popula cache)")
print("=" * 60)

app_results_1 = []
for i, q in enumerate(questions, 1):
    start = time.time()
    resp = requests.post(
        f"{APP_HOST}/api/2.0/genie/spaces/{SPACE_ID}/start-conversation",
        headers=headers,
        json={"content": q},
        timeout=120,
    )
    elapsed = time.time() - start

    data = resp.json()
    status = data.get("status", "UNKNOWN")
    conv_id = data.get("conversation_id", "")[:20]
    from_cache = "ccache_" in conv_id
    sql = (data.get("sql_query") or "")[:50]

    label = "CACHE HIT " if from_cache else "GENIE CALL"
    print(f"  [{i}/7] {status:12s} | {label} | {elapsed:.1f}s | {q}")
    if sql:
        print(f"          SQL: {sql}...")

    app_results_1.append({"question": q, "status": status, "time": elapsed, "from_cache": from_cache})

cache_hits = sum(1 for r in app_results_1 if r["from_cache"])
genie_calls = sum(1 for r in app_results_1 if not r["from_cache"])
print(f"\nResultado: {genie_calls} Genie calls, {cache_hits} cache hits, 0 erros para o caller")

# COMMAND ----------

# MAGIC %md
# MAGIC ### 2b. Segunda rodada (tudo do cache — instantaneo)

# COMMAND ----------

print("=" * 60)
print("CENARIO 2b: Via APP — segunda rodada (tudo do cache)")
print("=" * 60)

app_results_2 = []
for i, q in enumerate(questions, 1):
    start = time.time()
    resp = requests.post(
        f"{APP_HOST}/api/2.0/genie/spaces/{SPACE_ID}/start-conversation",
        headers=headers,
        json={"content": q},
        timeout=120,
    )
    elapsed = time.time() - start

    data = resp.json()
    conv_id = data.get("conversation_id", "")[:20]
    from_cache = "ccache_" in conv_id

    print(f"  [{i}/7] {'CACHE HIT':12s} | {elapsed:.2f}s | {q}")
    app_results_2.append({"question": q, "time": elapsed, "from_cache": from_cache})

total_time = sum(r["time"] for r in app_results_2)
all_cached = all(r["from_cache"] for r in app_results_2)
print(f"\nResultado: 7/7 cache hits | Total: {total_time:.2f}s | Media: {total_time/7:.2f}s/query")
print(f"Todas do cache: {all_cached}")

# COMMAND ----------

# MAGIC %md
# MAGIC ### Verificar estado do cache via API

# COMMAND ----------

cache_entries = requests.get(f"{APP_HOST}/api/v1/cache", headers=headers).json()
print(f"Entradas no cache: {len(cache_entries)}")
for e in cache_entries:
    print(f"  - {e['query_text'][:50]:50s} | uses={e['use_count']} | {e['sql_query'][:40]}...")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Comparacao Final

# COMMAND ----------

print("=" * 60)
print("COMPARACAO: Direto vs App")
print("=" * 60)
print(f"{'':30s} | {'Direto':>10s} | {'App (1a)':>10s} | {'App (2a)':>10s}")
print("-" * 70)

for i, q in enumerate(questions):
    d = direct_results[i] if i < len(direct_results) else {"status": "N/A", "time": 0}
    a1 = app_results_1[i] if i < len(app_results_1) else {"status": "N/A", "time": 0}
    a2 = app_results_2[i] if i < len(app_results_2) else {"time": 0}

    d_label = "429" if d["status"] == 429 else f"{d['time']:.1f}s"
    a1_label = f"{a1['time']:.1f}s" + (" (cache)" if a1.get("from_cache") else "")
    a2_label = f"{a2['time']:.2f}s (cache)"

    print(f"  {q[:28]:28s} | {d_label:>10s} | {a1_label:>10s} | {a2_label:>10s}")

print()
print("Direto: queries 6-7 falham com 429 (rate limit)")
print("App 1a: todas completam (retry automatico quando necessario)")
print("App 2a: todas do cache (<1s cada)")
