# Genie API Cache & Queue

Reference implementation for intelligent caching and rate limiting for Databricks Genie API queries using PGVector similarity search in Lakebase.

## Features

- **Semantic Query Caching**: Vector embeddings find similar queries and return cached results
- **Rate Limiting & Queueing**: Automatically queues queries when rate limits are exceeded
- **Retry with Backoff**: Failed queries retry with exponential backoff (5s, 15s, 30s)
- **Lakebase Integration**: Persistent storage via Databricks Lakebase (managed PostgreSQL with pgvector)
- **Multi-turn Conversations**: Context-aware caching for follow-up queries
- **Real-time Tracking**: Monitor query status, flow diagram, and cache effectiveness

## Architecture

```
User Query
    |
Embedding Service (Databricks Foundation Model API)
    |
Cache Lookup (PGVector cosine similarity in Lakebase)
    |-- Cache Hit (>= threshold) --> Execute cached SQL --> Return result
    |-- Cache Miss
            |
        Rate Limit Check
            |-- Below limit --> Genie API --> Cache result --> Return
            |-- Exceeded --> Queue for later processing
                                |
                            Background processor (retry with backoff)
```

## Prerequisites

- Databricks Workspace with Genie Space, SQL Warehouse, and Databricks Apps enabled
- Lakebase instance (recommended for persistent storage)
- Personal Access Token with Genie API, SQL Warehouse, and Lakebase permissions

## Quick Start

### Deploy to Databricks Apps

```bash
# Sync code to workspace
databricks sync . /Workspace/Users/<your-email>/genie-cache-queue

# Deploy the app
databricks apps deploy genie-cache-queue \
  --source-code-path /Workspace/Users/<your-email>/genie-cache-queue
```

### Configure in UI

Open the deployed app and go to **Settings**:

**Required:**
- Genie Space ID
- SQL Warehouse ID
- User PAT (Databricks Personal Access Token)

**For Lakebase (Recommended):**
- Storage Backend: "Databricks Lakebase"
- Lakebase Instance Name
- Lakebase Catalog and Schema

Click **Save Configuration**.

### Test

1. Go to **Chat** tab
2. Submit a query: "Show me sales by region"
3. Check **Query Logs** to see it processed
4. Submit the same query again — should be served from cache (faster)

## Local Development

### Backend

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
cd backend
cp .env.example .env  # Configure your environment
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Frontend at http://localhost:5173, backend at http://localhost:8000.

## Database Schema

### Cached Queries

```sql
CREATE TABLE cached_queries (
    id SERIAL PRIMARY KEY,
    query_text TEXT NOT NULL,
    query_embedding vector(1024),
    sql_query TEXT NOT NULL,
    identity VARCHAR(255) NOT NULL,
    genie_space_id VARCHAR(255) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT (CURRENT_TIMESTAMP AT TIME ZONE 'UTC'),
    last_used TIMESTAMPTZ DEFAULT (CURRENT_TIMESTAMP AT TIME ZONE 'UTC'),
    use_count INTEGER DEFAULT 1
);

CREATE INDEX cached_queries_embedding_idx
    ON cached_queries USING ivfflat (query_embedding vector_cosine_ops);
```

### Query Logs

```sql
CREATE TABLE query_logs (
    id SERIAL PRIMARY KEY,
    query_id VARCHAR(255) NOT NULL UNIQUE,
    query_text TEXT NOT NULL,
    identity VARCHAR(255) NOT NULL,
    stage VARCHAR(50) NOT NULL,
    genie_space_id VARCHAR(255),
    from_cache BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT (CURRENT_TIMESTAMP AT TIME ZONE 'UTC'),
    updated_at TIMESTAMPTZ DEFAULT (CURRENT_TIMESTAMP AT TIME ZONE 'UTC')
);
```

## Configuration

### Storage Backends

| Backend | Persistence | Setup | Use Case |
|---------|------------|-------|----------|
| Local (default) | In-memory, lost on restart | None | Testing |
| Lakebase | Persistent, shared across users | Lakebase instance | Production |

### Key Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| Similarity Threshold | 0.92 | Minimum cosine similarity for cache hit |
| Rate Limit | 5/min | Max Genie API calls per minute |
| Cache TTL | 24h | Time-to-live for cached entries (0 = no limit) |

## Tech Stack

**Backend:** FastAPI, asyncpg, pgvector, Databricks SDK, httpx
**Frontend:** React, Vite, TailwindCSS, Axios, Lucide React
**Infrastructure:** Databricks Apps, Lakebase, Databricks Foundation Model API

## Troubleshooting

**App won't start:** Check logs with `databricks apps logs <app-name> --follow`

**Cache not working:** Verify Lakebase instance is running, PAT has permissions, table names match

**Queries failing:** Verify Genie Space ID and SQL Warehouse are correct and running

**Debug endpoint:** Available at `/api/debug/config` in development mode (disabled in production)
