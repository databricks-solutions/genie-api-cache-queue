# Databricks notebook source
# MAGIC %md
# MAGIC # Initialize Lakebase SP role + grants for genie-gateway
# MAGIC
# MAGIC Bootstraps the Postgres role + grants + schema needed by the gateway app.
# MAGIC Idempotent — safe to re-run on every deploy.
# MAGIC
# MAGIC **What it does:**
# MAGIC 1. Resolves the deployed app's service principal (SP).
# MAGIC 2. Grants the SP `CAN_MANAGE` on the Lakebase project (so it can self-manage tables/extensions).
# MAGIC 3. Connects to Postgres as the deployer (project creator).
# MAGIC 4. Runs `databricks_create_role(<sp-uuid>, 'SERVICE_PRINCIPAL')` (idempotent).
# MAGIC 5. Grants `CONNECT` + `CREATE` on `databricks_postgres` to the SP.
# MAGIC 6. Creates the cache schema with `AUTHORIZATION <sp>` (so the SP owns it).
# MAGIC
# MAGIC Replaces the legacy `scripts/install.sh` SP-bootstrap path (lines 559-813).
# MAGIC See `docs/dab_chicken_egg_findings.md` for the wider Option C migration.

# COMMAND ----------

# MAGIC %pip install --quiet 'psycopg[binary]>=3.1'

# COMMAND ----------

dbutils.library.restartPython()

# COMMAND ----------

dbutils.widgets.text("project_id",  "",              "Lakebase project ID")
dbutils.widgets.text("branch_id",   "",              "Lakebase branch ID")
dbutils.widgets.text("app_name",    "",              "Databricks App name")
dbutils.widgets.text("schema_name", "genie_gateway", "Postgres schema (owned by app SP)")

project_id  = dbutils.widgets.get("project_id").strip()
branch_id   = dbutils.widgets.get("branch_id").strip()
app_name    = dbutils.widgets.get("app_name").strip()
schema_name = dbutils.widgets.get("schema_name").strip()

assert project_id,  "project_id widget is required"
assert branch_id,   "branch_id widget is required"
assert app_name,    "app_name widget is required"
assert schema_name, "schema_name widget is required"

endpoint_path = f"projects/{project_id}/branches/{branch_id}/endpoints/primary"
print(f"Initializing Lakebase role for app={app_name}")
print(f"  project={project_id} branch={branch_id} schema={schema_name}")
print(f"  endpoint={endpoint_path}")

# COMMAND ----------

# Use raw API calls throughout — the Lakebase Autoscaling SDK surface in
# databricks-sdk varies across runtimes (`w.postgres` may not exist on the
# serverless workload runtime). The HTTP API is stable.
import uuid
import psycopg
from psycopg import errors as pg_errors
from databricks.sdk import WorkspaceClient

w = WorkspaceClient()
api = w.api_client

# 1. Resolve the app's SP client_id from the apps API.
app_resp = api.do("GET", f"/api/2.0/apps/{app_name}")
sp_id = app_resp.get("service_principal_client_id")
sp_name = app_resp.get("service_principal_name") or sp_id
assert sp_id, f"Could not resolve SP client_id from app '{app_name}': {app_resp!r}"
print(f"App SP: client_id={sp_id} name={sp_name}")

# COMMAND ----------

# 2. Grant the SP CAN_MANAGE on the Lakebase project.
# Use PATCH semantics (additive — preserves existing grants for other principals).
try:
    api.do(
        "PATCH",
        f"/api/2.0/permissions/database-projects/{project_id}",
        body={
            "access_control_list": [
                {
                    "service_principal_name": sp_name,
                    "permission_level": "CAN_MANAGE",
                }
            ]
        },
    )
    print(f"Granted CAN_MANAGE on database-projects/{project_id} to SP {sp_name}")
except Exception as e:  # noqa: BLE001
    # Non-fatal — if the grant already exists at the right level, the API may
    # return errors that don't actually break anything. The SP role creation
    # below requires CAN_MANAGE, so a real failure surfaces there.
    print(f"WARNING: project permission grant returned: {e!r}")

# COMMAND ----------

# 3. Resolve endpoint host + mint deployer credential (raw API).
def _resolve_host(project_id: str, branch_id: str, endpoint_path: str) -> str:
    resp = api.do(
        "GET",
        f"/api/2.0/postgres/projects/{project_id}/branches/{branch_id}/endpoints",
    )
    endpoints = resp.get("endpoints", []) if isinstance(resp, dict) else []
    # Match by full resource path; fall back to the trailing endpoint id; else first.
    for ep in endpoints:
        if ep.get("name") == endpoint_path:
            status = ep.get("status") or {}
            hosts = status.get("hosts") or {}
            return hosts.get("host") or status.get("host") or ep.get("read_write_dns")
    if endpoints:
        ep = endpoints[0]
        status = ep.get("status") or {}
        hosts = status.get("hosts") or {}
        return hosts.get("host") or status.get("host") or ep.get("read_write_dns")
    return None


def _mint_credential(endpoint_path: str) -> str:
    """Generate a short-lived OAuth-as-PG credential for the caller's identity.

    Lakebase has two credential APIs and the right one depends on what kind of
    name you're passing:
      - /api/2.0/postgres/credentials wants an *endpoint* resource path
        (`projects/<p>/branches/<b>/endpoints/<id>`). This is what we have.
      - /api/2.0/database/credentials wants instance/database names. Useful
        for provisioned instances, not Autoscaling endpoints.
    Try postgres credentials first; if that 404s on a future API change, fall
    back to the database-credentials path with the database resource name.
    """
    try:
        resp = api.do(
            "POST",
            "/api/2.0/postgres/credentials",
            body={"endpoint": endpoint_path},
        )
        token = resp.get("token") if isinstance(resp, dict) else None
        if token:
            return token
    except Exception as e:  # noqa: BLE001
        print(f"postgres/credentials failed: {e!r} — trying database/credentials")

    # Fallback: resolve the auto-DB name and use the new credentials API.
    parts = endpoint_path.split("/")
    project, branch = parts[1], parts[3]
    dbs = api.do(
        "GET",
        f"/api/2.0/postgres/projects/{project}/branches/{branch}/databases",
    )
    for db in (dbs.get("databases") or []):
        db_name = db.get("name")
        if not db_name:
            continue
        resp = api.do(
            "POST",
            "/api/2.0/database/credentials",
            body={"instance_names": [db_name], "request_id": str(uuid.uuid4())},
        )
        token = resp.get("token") if isinstance(resp, dict) else None
        if token:
            return token
    return None


host = _resolve_host(project_id, branch_id, endpoint_path)
token = _mint_credential(endpoint_path)
assert host,  f"Could not resolve PG host for endpoint {endpoint_path}"
assert token, f"Could not generate database credential for endpoint {endpoint_path}"

deployer = w.current_user.me().user_name
print(f"Connecting to PG: host={host} user={deployer} db=databricks_postgres")

# COMMAND ----------

# 4. Run idempotent SQL: extension, role, grants, schema.
conn = psycopg.connect(
    host=host,
    dbname="databricks_postgres",
    user=deployer,
    password=token,
    sslmode="require",
)
try:
    with conn:
        with conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS databricks_auth;")

            # databricks_create_role raises 'role already exists' on re-run.
            try:
                cur.execute(
                    "SELECT databricks_create_role(%s, 'SERVICE_PRINCIPAL');",
                    (sp_id,),
                )
                print(f"Created PG role for SP {sp_id}")
            except (pg_errors.DuplicateObject, pg_errors.UniqueViolation):
                print(f"PG role for SP {sp_id} already exists (idempotent re-run)")
            except pg_errors.InternalError as e:
                if "already exists" in str(e).lower():
                    print(f"PG role for SP {sp_id} already exists (matched on message)")
                else:
                    raise

            # Quote-escape identifiers (UUID / known-valid schema name) for
            # double-quoted PG identifier interpolation.
            sp_quoted = '"' + sp_id.replace('"', '""') + '"'
            schema_quoted = '"' + schema_name.replace('"', '""') + '"'

            # GRANTs are naturally idempotent.
            cur.execute(f"GRANT CONNECT ON DATABASE databricks_postgres TO {sp_quoted};")
            cur.execute(f"GRANT CREATE  ON DATABASE databricks_postgres TO {sp_quoted};")
            print(f"Granted CONNECT + CREATE on databricks_postgres to {sp_id}")

            # Postgres requires "must be able to SET ROLE <target>" for
            # `CREATE SCHEMA ... AUTHORIZATION <target>`. Make the deployer a
            # member of the SP role so the AUTHORIZATION clause works.
            # Idempotent — re-grant is a no-op.
            deployer_quoted = '"' + deployer.replace('"', '""') + '"'
            cur.execute(f"GRANT {sp_quoted} TO {deployer_quoted};")
            print(f"Granted SP role {sp_id} to deployer {deployer} (for AUTHORIZATION)")

            cur.execute(
                f"CREATE SCHEMA IF NOT EXISTS {schema_quoted} AUTHORIZATION {sp_quoted};"
            )
            print(f"Schema {schema_name} ready (AUTHORIZATION {sp_id})")
finally:
    conn.close()

print(f"\nOK: Lakebase role + grants + schema initialized")
print(f"  SP:       {sp_id}")
print(f"  Schema:   {schema_name}")
print(f"  Endpoint: {endpoint_path}")
