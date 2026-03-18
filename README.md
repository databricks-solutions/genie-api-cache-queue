# Genie Cache & Queue

Drop-in replacement for the Databricks Genie API that adds semantic caching, rate-limit management, and automatic retry. Deploy as a Databricks App — callers only change the base URL, zero code changes.

## How It Works

The Genie API has a hard limit of **5 queries per minute per workspace**. This app sits in front of it and handles the three main scenarios:

1. **Cache hit** — Re-executes the cached SQL against the warehouse (fresh data, no Genie call)
2. **Cache miss** — Calls Genie in background, queues if rate-limited, retries with exponential backoff
3. **Rate limit** — Manages the 5 QPM limit transparently with a queue and backoff

## Architecture

```
Caller (OAuth)
    |
    v
Clone API (/api/2.0/genie/*)     <-- Same endpoints as Genie
    |
    +-- Embedding Service          <-- Databricks Foundation Model (caller's OAuth)
    +-- Cache (Lakebase/PGVector)  <-- SP OAuth (admin-configured)
    +-- Genie API                  <-- Caller's OAuth (only on cache miss)
    +-- SQL Warehouse              <-- Caller's OAuth (execute cached SQL)
```

## Quick Start

### Prerequisites

- Databricks workspace with **Apps** enabled
- [Databricks CLI](https://docs.databricks.com/dev-tools/cli/install.html) installed and configured
- A **Genie Space** and **SQL Warehouse** in your workspace
- *(Optional)* A **Lakebase** instance for persistent cache

### 1. Deploy the App

```bash
# Sync code to your workspace
databricks sync . /Workspace/Users/<your-email>/genie-cache-queue

# Deploy
databricks apps deploy genie-cache-queue \
  --source-code-path /Workspace/Users/<your-email>/genie-cache-queue
```

### 2. Configure

Open the app URL and go to the **Settings** tab:

| Field | Description |
|-------|-------------|
| **Genie Space ID** | Your Genie Space identifier (required) |
| **SQL Warehouse ID** | SQL warehouse for query execution (required) |
| **Storage Backend** | `Local` (in-memory, lost on restart) or `Lakebase` (persistent) |

For **Lakebase** (recommended), also configure:

| Field | Description |
|-------|-------------|
| **Lakebase Service Token** | SP `client_id:client_secret` or PAT for cache operations |
| **Lakebase Instance Name** | Autoscaling project name or direct hostname |
| **Lakebase Schema** | Usually `public` |

Click **Save Configuration**.

### 3. Use

Change the base URL in your application:

```python
# Before (direct Genie)
BASE = "https://<workspace>.cloud.databricks.com"

# After (with cache + retry)
BASE = "https://<app-name>.aws.databricksapps.com"

# Same code, same endpoints, same auth
r = requests.post(f"{BASE}/api/2.0/genie/spaces/{SPACE}/start-conversation",
    headers={"Authorization": f"Bearer {TOKEN}"},
    json={"content": "How many customers?"})
```

## Lakebase Setup (Persistent Cache)

For production use, Lakebase provides persistent vector-based caching with pgvector.

Inside Databricks Apps, the app automatically uses its **built-in Service Principal** (injected as `DATABRICKS_CLIENT_ID`/`SECRET`). You only need to grant this SP access to your Lakebase project — no manual credential configuration required.

### 1. Grant the App's SP Access to Lakebase

Find the app's SP name in **Workspace Settings > Compute > Apps > your app > Service Principal**, then grant it CAN_MANAGE:

```python
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.iam import AccessControlRequest, PermissionLevel

w = WorkspaceClient()
w.permissions.update('database-projects', '<project-name>',
    access_control_list=[
        AccessControlRequest(
            service_principal_name='<app-sp-display-name>',
            permission_level=PermissionLevel.CAN_MANAGE
        )
    ])
```

### 2. Create the SP's PostgreSQL Role

Connect to Lakebase as a human user and run (replace `<app-sp-client-id>` with the app's SP client ID):

```sql
CREATE EXTENSION IF NOT EXISTS databricks_auth;
SELECT databricks_create_role('<app-sp-client-id>', 'SERVICE_PRINCIPAL');

GRANT ALL ON SCHEMA public TO "<app-sp-client-id>";
GRANT ALL ON ALL TABLES IN SCHEMA public TO "<app-sp-client-id>";
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO "<app-sp-client-id>";
```

> **Important:**
> - Use `databricks_create_role()` — not `CREATE ROLE`. Only `databricks_create_role` enables OAuth JWT authentication. See: [Create Postgres roles](https://docs.databricks.com/aws/en/oltp/projects/postgres-roles)
> - **Do not create the cache tables manually.** Let the app create them on first use — this ensures the SP owns the tables and can manage indexes. If tables were already created by a different user, drop them first so the app's SP recreates them as owner.

### 3. Configure in Settings

Set the **Storage Backend** to `Lakebase`, the **Instance Name** to your project name, and the **Lakebase Service Token** to the app SP's `<client_id>:<client_secret>`.

> **Note:** Inside Databricks Apps, the actual Lakebase connection uses the app's built-in SP (auto-detected). The Lakebase Service Token in Settings is used as a fallback for local development only.

### Local Development

For local development (outside Databricks Apps), the app cannot auto-detect SP credentials. Configure the Lakebase Service Token in Settings or `.env` with either:
- **Service Principal:** `<client_id>:<client_secret>` (recommended)
- **PAT:** `dapi...` (simpler, for development)

## Authentication

| Component | Token | Source |
|-----------|-------|--------|
| Genie API | Caller's OAuth | `X-Forwarded-Access-Token` (browser) or `Authorization: Bearer` (API) |
| SQL Warehouse | Caller's OAuth | Same |
| Embeddings | Caller's OAuth | Same |
| **Lakebase cache** | **App's built-in SP** | Auto-detected from `DATABRICKS_CLIENT_ID`/`SECRET` |

**Callers don't need Lakebase access.** The app's SP handles all cache operations.

## Configuration Reference

All settings are configurable via the UI Settings tab or `PUT /api/config`:

| Field | Description | Default |
|-------|-------------|---------|
| `genie_space_id` | Genie Space ID | Required |
| `sql_warehouse_id` | SQL Warehouse for query execution | Required |
| `storage_backend` | `lakebase` or `local` | `local` |
| `lakebase_service_token` | SP credentials for local dev (auto-detected in Databricks Apps) | Local dev only |
| `lakebase_instance_name` | Autoscaling project name or hostname | Required for Lakebase |
| `similarity_threshold` | Cache match threshold (0–1) | 0.92 |
| `max_queries_per_minute` | Rate limit per workspace | 5 |
| `cache_ttl_seconds` | Cache freshness in seconds (0 = unlimited) | 86400 (24h) |
| `shared_cache` | Share cache across all users | true |

## API Reference

### Clone API (Drop-in Replacement)

All endpoints mirror the official [Databricks Genie API](https://docs.databricks.com/api/workspace/genie):

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/2.0/genie/spaces/{id}/start-conversation` | Start conversation (cache + queue) |
| POST | `.../conversations/{cid}/messages` | Follow-up message |
| GET | `.../conversations/{cid}/messages/{mid}` | Poll for result |
| GET | `.../messages/{mid}/attachments/{aid}/query-result` | Get query data |
| POST | `.../messages/{mid}/attachments/{aid}/execute-query` | Re-execute query |
| GET | `/api/2.0/genie/spaces/{id}` | Space metadata (proxy) |

### Proxy API (REST)

Simplified REST API for external applications:

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/v1/query` | Submit query (async) |
| GET | `/api/v1/query/{id}` | Poll query status |
| POST | `/api/v1/query/sync` | Submit and wait (up to 120s) |
| GET | `/api/v1/health` | Health check |
| GET | `/api/v1/config` | Get configuration |
| PUT | `/api/v1/config` | Update configuration |
| GET | `/api/v1/cache` | List cached queries |
| GET | `/api/v1/queue` | List queued queries |
| GET | `/api/v1/query-logs` | Recent query logs |

## Local Development

```bash
# Backend
cd backend
cp .env.example .env              # Edit with your DATABRICKS_TOKEN, etc.
pip install -r ../requirements.txt
python -m uvicorn app.main:app --reload --port 8000

# Frontend (separate terminal)
cd frontend
npm install
npm run dev                        # http://localhost:5173
```

## Demo Notebook

The included `demo_notebook.ipynb` fires 7 queries in parallel to demonstrate:
1. **Direct to Genie** — queries get blocked with 429 errors
2. **Via the App (first run)** — all queries complete, queue manages rate limits
3. **Via the App (second run)** — all queries served from cache instantly

Before running, copy `.env.notebook` to your Workspace home and fill in your values:

```bash
# Upload to your Workspace home directory
databricks workspace import /Workspace/Users/<your-email>/.env \
  --file .env.notebook --format RAW --profile <profile>
```

Then edit `/Workspace/Users/<your-email>/.env` in the workspace with your actual credentials. The notebook auto-detects your username and loads the `.env` from there.

> **Note:** `.env.notebook` is only for the demo notebook. The app itself is configured via the Settings UI or `PUT /api/config`.

## Continuous Deployment

```bash
# After code changes
databricks sync . /Workspace/Users/<your-email>/genie-cache-queue
databricks apps deploy genie-cache-queue \
  --source-code-path /Workspace/Users/<your-email>/genie-cache-queue
```

## View Logs

```bash
databricks apps logs genie-cache-queue --follow
```
