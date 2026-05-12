# DABs Lakebase + App Chicken-and-Egg: Findings and Recommended Path

**Date:** 2026-05-08
**Author:** Alex (with Claude Code research)
**Project:** genie-api-cache-queue
**Status:** Research complete; implementation deferred

## TL;DR

The two-stage Makefile + `install.sh` workaround in this repo exists because Lakebase Autoscaling auto-creates a `databricks_postgres` database with a non-deterministic resource ID (`db-xxxx-yyyyyyy`), and DABs has no way to reference it (`${resources.postgres_branches.X.default_database_id}` does not exist). This is widely reported across customers and acknowledged by the Lakebase team.

**A platform fix lands in prod 2026-05-21** that gives the initial database a stable resource name `databricks-postgres`. After that, this entire chicken-and-egg disappears for pure-DAB deploys.

**Recommended path: bridge-then-migrate.** Ship a pure-DAB single-deploy pattern *now* using a `resources.jobs` init notebook (Option C), then rewrite to the platform-stable-name pattern after May 21 (Option A). Both are single-`bundle deploy` patterns with no Makefile chain, no `install.sh`, no manual DB-ID lookup.

## The problem, restated

Today's `databricks.yml` declares:

```yaml
apps:
  gateway:
    resources:
      - name: postgres
        postgres:
          branch: ${resources.postgres_branches.gateway_branch.id}
          database: ${var.database_path}        # ← unknown until branch exists
          permission: CAN_CONNECT_AND_CREATE
```

`var.database_path` is empty on first deploy. The current `Makefile` workaround (lines 60-71) is:
1. `bundle deploy || true` — fails on the app step but creates the project + branch + auto-DB
2. `scripts/resolve_database.sh` — `databricks api get .../databases | jq` to read the auto-DB's resource ID
3. `bundle deploy --var "database_path=$DB_PATH"` — second pass to create the app

`scripts/install.sh` takes a different route: `apps create` (no deploy), connect to Postgres directly to run `databricks_create_role` + grants, PATCH the app's `user_api_scopes` and `resources` in one call, then `apps deploy`.

Both fall outside "single bundle deploy."

## Research findings

### 1. The platform gap is acknowledged and a fix is shipping

**Slack #databricks-asset-bundles, thread ts `1776620327.343189`** (Sean Lobo opened the ticket; multiple SAs replying with the same blocker). On 2026-05-08 Boris (Lakebase eng, message ts `1778222676.950669`) confirmed:

> "Hello, below are the changes in behavior for the initial Role and the initial Database. ETA for prod: May 21.
> - The initial database now gets resource name like `projects/<pr-id>/branches/<br-id>/databases/databricks-postgres` (notice the `-`, the database in PG is visible with `_` as `databricks_postgres`, there is no way to make them equal).
> - The initial role gets resource name derived from the identity that created the Lakebase Project. This is usually a User or Service Principal (SP). Here are a couple of examples...
>   - User identity `alice.smith@example.com` → Role name `projects/<pr-id>/branches/<br-id>/roles/alice-smith`
>   - SP identity `e86d787a-464c-47d3-a8d0-3e2485d78e44` → Role name `projects/<pr-id>/branches/<br-id>/roles/sp-e86d787a-464c-47d3-a8d0-3e2485d78e44`"

Earlier in the same thread (ts `1776929480.516899`):
> "this will be addressed in [LKB-11750](https://databricks.atlassian.net/browse/LKB-11750), see 'support stable resource names'. Initial Database and Initial Role will have a documented stable name so the user does not have to guess."

### 2. Multiple customers hitting this; eng has a JIRA

**Slack thread ts `1776705172.139629`** (SRAM customer): three related DAB+Lakebase issues filed.
- Issue 1 (`${resources.*}` not interpolated in `config.env[*].value`) — fixed in [CLI v0.297.0](https://github.com/databricks/cli/releases/tag/v0.297.0)
- Issue 2 (auto-DB ID not referenceable) — "in progress by the Lakebase team" → this is LKB-11750
- Issue 3 (endpoint settings not configurable on `postgres_branches` in DABs) — not supported by the [Lakebase API](https://docs.databricks.com/api/workspace/postgres/updatebranch#spec)

**Slack thread ts `1774648854.238289`** (C05E5R3F57B): another customer with same blocker. Their workaround (which informs Option C below): omit `apps.resources[].postgres` entirely, pass `LAKEBASE_ENDPOINT` and `PGDATABASE=databricks_postgres` as env vars, run a notebook to create the SP role + grants before app start.

### 3. DAB resources for Lakebase, today

Per [bundle resources docs](https://docs.databricks.com/aws/en/dev-tools/bundles/resources) and [PR #4423](https://github.com/databricks/cli/pull/4423) (merged 2026-02-04):

- `database_instances` — provisioned (legacy; stable names; works with apps today)
- `postgres_projects`, `postgres_branches`, `postgres_endpoints` — Autoscaling
- **No `postgres_databases` top-level resource.** The branch's auto-created database cannot be declared or named explicitly.
- **Permissions can't be declared in a bundle** ([docs](https://docs.databricks.com/aws/en/oltp/projects/manage-with-bundles)): *"Project permissions (CAN_USE, CAN_MANAGE) cannot be declared in a bundle. The `permissions` field is not supported on `postgres_projects` resources. Manage permissions separately using the Permissions API, CLI, or SDK as a post-deploy step."*

### 4. DAB pre/post-deploy hooks: closed as "not planned"

[GitHub issue #3801](https://github.com/databricks/cli/issues/3801) was closed not-planned. Officially mentioned workarounds: (a) abusing `artifacts.build`, (b) the `databricks-bundles` Python library. There's no first-class hook mechanism today.

### 5. The only official template combining App + Lakebase uses provisioned

`databricks/app-templates/e2e-chatbot-app-next/databricks.yml`:

```yaml
resources:
  database_instances:
    chatbot_lakebase:
      name: ${var.database_instance_name}-${var.resource_name_suffix}
      capacity: CU_1
  apps:
    databricks_chatbot:
      resources:
        - name: database
          database:
            database_name: databricks_postgres
            instance_name: ${resources.database_instances.chatbot_lakebase.name}
            permission: CAN_CONNECT_AND_CREATE
```

This works in a single `bundle deploy` because both `instance_name` and `database_name` are stable strings. It does NOT work for `postgres_projects` (Autoscaling).

### 6. Terraform has the same gap

The internal "Lakebase Autoscaling Terraform State as of April 29, 2026" doc (Anna Stepanyan) lists Friction #1 (CRITICAL):
> "No App resource support for autoscaling. `databricks_app`'s database binding only accepts `instance_name` (provisioned). No field exists for autoscaling projects, branches, or endpoints. Blocks provisioned-to-autoscaling migration for any customer using Apps."

So this isn't a DAB-specific limitation — Terraform has the same gap. LKB-11750 unblocks both.

## Three viable single-deploy patterns

| Option | Works today? | Stays on Autoscaling? | Single `bundle deploy`? | Notes |
|--------|--------------|------------------------|--------------------------|-------|
| **A — wait for May 21 stable name** | After 2026-05-21 | Yes | Yes | Cleanest. Hardcode `databricks-postgres` as the DB name. Platform auto-creates SP role + grants when `apps.resources[].postgres` is declared. |
| **B — switch to provisioned `database_instances`** | Yes | No (legacy) | Yes | Mirrors the official `e2e-chatbot-app-next` template. Trade-off: provisioned is being phased out — Lakebase eng is steering all new functionality to Autoscaling. |
| **C — pure-DAB init job** | Yes | Yes | Yes (deploy) + one `bundle run` | Omit `apps.resources[].postgres`, declare a `resources.jobs` notebook in the bundle that creates the SP role + grants. App authenticates via the Autoscaling SDK. Both steps are bundle-defined. |

## Selected path: Bridge-then-migrate (C → A)

Ship Option C now to remove the Makefile chain. After 2026-05-21, rewrite to Option A. Both end states are single-`bundle deploy` patterns; the rewrite from C to A is small.

### Stage 1 (today): Option C — pure-DAB init job

Files to change in this repo:

#### `databricks.yml`

- **Delete** the `database_path` variable (lines 48-58)
- **Delete** the `apps.gateway.resources:` block under both `dev` and `prod` targets (lines 105-114, 136-142)
- **Update** the lines 12-16 comment block to describe the init-job pattern (the current comment claims the platform handles SP-role creation when `apps.resources[].postgres` is declared, which is true but irrelevant once we drop that block).
- **Add** a `resources.jobs.init_sp_role` job under both `dev` and `prod` targets:

```yaml
jobs:
  init_sp_role:
    name: ${var.app_name}-init-sp-role
    tasks:
      - task_key: grant
        notebook_task:
          notebook_path: ./setup_notebooks/init_lakebase_role
          base_parameters:
            project_id: ${var.project_id}
            branch_id: ${var.branch_id}
            app_sp_client_id: ${resources.apps.gateway.service_principal_client_id}
            schema_name: ${var.schema_name}
        # Use serverless compute via the standard DAB job environments pattern
```

#### `app.yaml`

`LAKEBASE_ENDPOINT: valueFrom: postgres` (line ~31) only works when `apps.resources[].postgres` is declared. Replace with a hardcoded value, and add `PGDATABASE` (no longer auto-injected once the resource binding is gone):

```yaml
- name: LAKEBASE_ENDPOINT
  value: projects/genie-gateway/branches/${BRANCH_ID}/endpoints/primary
- name: PGDATABASE
  value: databricks_postgres
```

(`${BRANCH_ID}` would need to be passed in via the bundle as a substitution or as a separate env var. Simpler: don't templatize and just pin it per-target via two separate `app.yaml` files or via the bundle's app-config injection if/when that lands.)

#### `setup_notebooks/init_lakebase_role.py` (new)

Port the SP-role + grant logic from `scripts/install.sh` lines 559-813:

```python
# Databricks notebook source
# MAGIC %md
# MAGIC # Initialize Lakebase SP role + grants for genie-gateway

dbutils.widgets.text("project_id", "")
dbutils.widgets.text("branch_id", "")
dbutils.widgets.text("app_sp_client_id", "")
dbutils.widgets.text("schema_name", "genie_cache")

project_id = dbutils.widgets.get("project_id")
branch_id  = dbutils.widgets.get("branch_id")
sp_id      = dbutils.widgets.get("app_sp_client_id")
schema     = dbutils.widgets.get("schema_name")

from databricks.sdk import WorkspaceClient
import psycopg

w = WorkspaceClient()

# 1. Grant the app SP CAN_MANAGE on the Lakebase project (idempotent).
w.permissions.set(
    request_object_type="postgres-projects",
    request_object_id=project_id,
    access_control_list=[{
        "service_principal_name": sp_id,
        "permission_level": "CAN_MANAGE",
    }],
)

# 2. Connect to Postgres as deployer via ephemeral OAuth creds.
endpoint = f"projects/{project_id}/branches/{branch_id}/endpoints/primary"
cred = w.postgres.generate_database_credential(endpoint=endpoint)
host = w.postgres.endpoints.get(endpoint).status.hosts.host

with psycopg.connect(host=host, dbname="databricks_postgres",
                     user=w.current_user.me().user_name,
                     password=cred.token, sslmode="require") as conn:
    with conn.cursor() as cur:
        cur.execute("CREATE EXTENSION IF NOT EXISTS databricks_auth;")
        cur.execute("SELECT databricks_create_role(%s, 'SERVICE_PRINCIPAL');", (sp_id,))
        cur.execute(f'GRANT CONNECT ON DATABASE databricks_postgres TO "{sp_id}";')
        cur.execute(f'GRANT CREATE ON DATABASE databricks_postgres TO "{sp_id}";')
        cur.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}" AUTHORIZATION "{sp_id}";')
    conn.commit()
```

The notebook runs as the deploying user, who has CAN_MANAGE on the project by virtue of having created it. Schema-fallback logic from `install.sh` lines 700-780 can be ported if the simpler form above ever conflicts.

#### `Makefile`

Collapse the two-stage chain. Delete `bundle-deploy-postgres`, `bundle-deploy-app`, `resolve-db` targets. Replace with:

```makefile
deploy: build bundle-deploy bundle-init bundle-run

bundle-deploy:
	databricks bundle deploy --target $(TARGET) $(PROFILE_ARG) $(BUNDLE_VARS)

bundle-init:
	databricks bundle run init_sp_role --target $(TARGET) $(PROFILE_ARG) $(BUNDLE_VARS)
```

The canonical install path (documentable in README) is now three pure-DAB commands:
```
databricks bundle deploy
databricks bundle run init_sp_role
databricks bundle run gateway
```

#### `scripts/resolve_database.sh` and `scripts/install.sh`

Delete. The relevant logic lives in the init notebook now.

#### Note: `scripts/install.sh` was 1000+ lines and did a lot more than role creation

Before deleting it, audit for any logic *not* related to the role/grant work that needs to live somewhere else:
- Frontend build steps (move to `scripts/build.sh` if not already)
- `.env.deploy` writing — probably no longer needed under DAB-only
- `CAN_MANAGE` grant on the project — covered by the notebook
- Schema fallback logic (lines 700-780) — port if needed

### Stage 2 (after 2026-05-21): Option A

Once LKB-11750 ships and you've verified the stable name on FEVM:

```
databricks api get /api/2.0/postgres/projects/<pr>/branches/<br>/databases --profile fevm
# Expect a database with name ending in /databases/databricks-postgres
```

Then refactor:

#### `databricks.yml`

Restore `apps.gateway.resources[].postgres` with the stable name (no variable):

```yaml
apps:
  gateway:
    resources:
      - name: postgres
        postgres:
          branch: ${resources.postgres_branches.gateway_branch.id}
          database: ${resources.postgres_branches.gateway_branch.id}/databases/databricks-postgres
          permission: CAN_CONNECT_AND_CREATE
```

(Note `databricks-postgres` with a hyphen — that's the *resource name*. The Postgres-visible DB name remains `databricks_postgres` with an underscore. They're not equal by design.)

Delete `resources.jobs.init_sp_role` from both targets.

#### `app.yaml`

Restore `LAKEBASE_ENDPOINT: valueFrom: postgres` and remove the hardcoded `PGDATABASE`. Once the resource binding is back, the platform auto-injects `PGDATABASE`, `PGHOST`, `PGUSER`, `PGPORT`, `PGSSLMODE`.

#### `setup_notebooks/init_lakebase_role.py`

Delete. The platform auto-creates the SP role with CONNECT + CREATE when `apps.resources[].postgres` is declared (this is the behavior the existing comment in `databricks.yml` lines 12-16 already documents).

#### `Makefile`

Drop the `bundle-init` target. `make deploy` becomes `build && bundle-deploy && bundle-run`.

## Verification

### Stage 1 (Option C, today)

On FEVM:
1. `make destroy TARGET=dev PROFILE=fevm` (clean slate)
2. `make deploy TARGET=dev PROFILE=fevm` — must succeed without `|| true` and without manual DB lookup
3. Open the app URL, exercise an endpoint that touches Postgres
4. `databricks apps logs ${app_name} --profile fevm --follow` — confirm no `Role <uuid> not found in instance` errors at boot
5. Re-run `make deploy` — confirm idempotent

### Stage 2 (Option A, after May 21)

Same sequence, plus:
1. Before committing: confirm the auto-created database has `name` ending in `/databases/databricks-postgres` via the API call above
2. After deploy: confirm `PGDATABASE`, `PGHOST`, `PGUSER`, `PGPORT`, `PGSSLMODE` are populated in the app environment (visible via `databricks apps get-env` or inside the container)

## Sources

### Slack
- #databricks-asset-bundles thread ts `1776620327.343189` — Sean Lobo + Boris (Lakebase eng); LKB-11750 confirmation, stable-name announcement May 8, prod ETA 2026-05-21
- #databricks-asset-bundles thread ts `1776705172.139629` — SRAM customer report; CLI 0.297.0 fix for `${resources.*}` interpolation
- Thread ts `1774648854.238289` (C05E5R3F57B) — origin of the Option C bypass-`apps.resources[].postgres` pattern

### Docs
- [Manage Lakebase with DABs](https://docs.databricks.com/aws/en/oltp/projects/manage-with-bundles)
- [DAB resources reference](https://docs.databricks.com/aws/en/dev-tools/bundles/resources)
- [Lakebase API: createdatabase](https://docs.databricks.com/api/workspace/postgres/createdatabase)

### Code
- `databricks/app-templates/e2e-chatbot-app-next/databricks.yml` — official App + Lakebase template (provisioned only)
- `databricks/cli` PR [#4423](https://github.com/databricks/cli/pull/4423) — adds `postgres_projects/branches/endpoints` to DABs (merged 2026-02-04)
- `databricks/cli` issue [#3801](https://github.com/databricks/cli/issues/3801) — pre/post-deploy hooks closed not-planned
- This repo: `scripts/install.sh` lines 559-813 — source for the SP-role notebook port

### Internal docs
- "Lakebase Autoscaling Terraform State as of April 29, 2026" (Anna Stepanyan) — Friction #1 confirms TF has the same gap
- "Integrating with Lakebase Autoscaling" (Sean Lobo, updated Feb 2026) — explains Database Instance vs Database Project model
