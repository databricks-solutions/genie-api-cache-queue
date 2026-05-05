#!/usr/bin/env python3
"""Post-bundle-deploy hook for Genie Gateway v2.

Runs the steps a Databricks Asset Bundle cannot express:

1. Wait for the app's compute to reach ACTIVE so we can read its SP client_id.
2. Grant the SP CAN_MANAGE on the database instance (idempotent).
3. Connect to Lakebase as the deployer (via ephemeral OAuth creds), then:
   - CREATE EXTENSION databricks_auth
   - SELECT databricks_create_role(<sp-uuid>, 'SERVICE_PRINCIPAL')
   - GRANT CONNECT, CREATE ON DATABASE
   - Resolve schema fallback if the desired schema is owned by a stale SP.
4. PATCH the app's effective config if the schema fell back, or if user_api_scopes
   / app-attached resources didn't make it through bundle deploy.
5. Best-effort health check.

Idempotent. Safe to re-run. Mirrors install.sh:559-1000 with the project→instance
API swap (DABs creates `database_instances`, not the legacy `postgres_projects`).

Usage:
    python3 scripts/post_deploy.py --target fevm
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import ssl
import subprocess
import sys
import time
from typing import Optional

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("post_deploy")

# Names mirror databricks.yml variables. If those defaults change, change here too.
APP_NAME = "genie-gateway-v2"
INSTANCE_NAME = "genie-gateway-v2"
DESIRED_SCHEMA = "genie_cache_v2"
DESIRED_SCOPES = ["sql", "serving.serving-endpoints", "dashboards.genie"]

UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
IDENT_RE = re.compile(r"^[a-z_][a-z0-9_]*$")


def cli(*args: str, profile: str, capture_stderr: bool = False) -> str:
    """Run `databricks <args> --profile <profile> -o json` and return stdout."""
    cmd = ["databricks", *args, "--profile", profile, "-o", "json"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        msg = r.stderr.strip() or r.stdout.strip()
        if capture_stderr:
            return msg
        raise RuntimeError(f"`{' '.join(cmd)}` failed: {msg}")
    return r.stdout


def cli_api(method: str, path: str, *, profile: str, body: Optional[dict] = None) -> dict:
    cmd = ["databricks", "api", method, path, "--profile", profile, "-o", "json"]
    if body is not None:
        cmd.extend(["--json", json.dumps(body)])
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"api {method} {path} failed: {r.stderr.strip() or r.stdout.strip()}")
    out = r.stdout.strip()
    return json.loads(out) if out else {}


def wait_for_app_settled(profile: str, timeout_s: int = 360) -> dict:
    """Poll `databricks apps get` until compute is in a settled state (STOPPED,
    ACTIVE, or RUNNING). Return the app JSON.

    This hook runs BEFORE `bundle run`, so the app is typically STOPPED — the
    SP UUID is already populated, which is all we need to grant the Postgres
    role. We don't require ACTIVE because the app's resource attachment isn't
    set yet, so a STARTING app might be in the process of failing.
    """
    deadline = time.time() + timeout_s
    last_state: Optional[str] = None
    while time.time() < deadline:
        try:
            app = json.loads(cli("apps", "get", APP_NAME, profile=profile))
        except RuntimeError as e:
            log.warning("apps get failed (will retry): %s", e)
            time.sleep(5)
            continue
        state = app.get("compute_status", {}).get("state") or app.get("status", {}).get("state")
        if state != last_state:
            log.info("app compute state: %s", state)
            last_state = state
        if state in ("STOPPED", "ACTIVE", "RUNNING"):
            return app
        if state in ("ERROR", "FAILED"):
            raise RuntimeError(f"app entered terminal state {state}: {app.get('compute_status',{}).get('message')}")
        time.sleep(10)
    raise TimeoutError(f"app {APP_NAME} did not settle within {timeout_s}s")


def resolve_instance_host(profile: str) -> tuple[str, str]:
    """Return (host, endpoint_name_or_instance_name) for the v2 database instance.

    Tries the new database_instances API first; falls back to the legacy
    postgres_projects API if the bundle is talking to a workspace that still
    routes through projects.
    """
    try:
        inst = cli_api("get", f"/api/2.0/database/instances/{INSTANCE_NAME}", profile=profile)
        host = inst.get("read_write_dns") or inst.get("pg_hostname") or inst.get("hostname")
        endpoint = inst.get("name") or INSTANCE_NAME
        if host:
            return host, endpoint
        log.warning("database_instances response had no host field: keys=%s", sorted(inst.keys()))
    except RuntimeError as e:
        log.info("database_instances API not available, falling back to projects: %s", e)
    # Fallback: legacy projects API (matches install.sh:622-638).
    eps = cli_api(
        "get",
        f"/api/2.0/postgres/projects/{INSTANCE_NAME}/branches/production/endpoints",
        profile=profile,
    )
    endpoints = eps.get("endpoints", [])
    if not endpoints:
        raise RuntimeError(f"no endpoints found for instance {INSTANCE_NAME}")
    ep = endpoints[0]
    return ep["status"]["hosts"]["host"], ep["name"]


def grant_sp_manage_on_instance(profile: str, sp_name: str) -> None:
    """Grant the app SP CAN_MANAGE on the database instance (idempotent)."""
    payload = {
        "access_control_list": [
            {"service_principal_name": sp_name, "permission_level": "CAN_MANAGE"}
        ]
    }
    # Try the new permissions endpoint; fall back to the legacy projects path.
    for path in (
        f"/api/2.0/permissions/database-instances/{INSTANCE_NAME}",
        f"/api/2.0/permissions/database-projects/{INSTANCE_NAME}",
    ):
        try:
            cli_api("patch", path, profile=profile, body=payload)
            log.info("granted CAN_MANAGE on %s via %s", INSTANCE_NAME, path)
            return
        except RuntimeError as e:
            log.info("permissions PATCH at %s failed (will try fallback): %s", path, e)
    log.warning("could not grant SP CAN_MANAGE on instance — may need a manual grant")


def get_ephemeral_pg_token(profile: str, endpoint: str) -> tuple[str, str]:
    """Return (token, deployer_username) for a Postgres connection as the deployer.

    Tries the new /api/2.0/database/credentials first (works for instances created
    via resources.database_instances). Falls back to the legacy
    /api/2.0/postgres/credentials for projects-API instances.
    """
    import uuid as _uuid
    request_id = f"post-deploy-{_uuid.uuid4()}"
    try:
        cred = cli_api(
            "post",
            "/api/2.0/database/credentials",
            profile=profile,
            body={"instance_names": [INSTANCE_NAME], "request_id": request_id},
        )
    except RuntimeError as e:
        log.info("/api/2.0/database/credentials failed (will try legacy): %s", e)
        cred = cli_api(
            "post",
            "/api/2.0/postgres/credentials",
            profile=profile,
            body={"endpoint": endpoint},
        )
    me = json.loads(cli("current-user", "me", profile=profile))
    return cred["token"], me["userName"]


async def configure_postgres(
    *, host: str, deployer_user: str, token: str, sp_id: str, desired_schema: str
) -> str:
    """Create SP role + grants, return the resolved schema name (may be a fallback)."""
    import asyncpg  # local import so the module imports even without asyncpg.

    if not UUID_RE.match(sp_id):
        raise ValueError(f"sp_id is not a valid UUID: {sp_id!r}")
    if desired_schema and not IDENT_RE.match(desired_schema):
        raise ValueError(f"schema is not a safe identifier: {desired_schema!r}")

    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    conn = await asyncpg.connect(
        host=host,
        port=5432,
        database="databricks_postgres",
        user=deployer_user,
        password=token,
        ssl=ctx,
    )
    try:
        await conn.execute("CREATE EXTENSION IF NOT EXISTS databricks_auth")
        try:
            await conn.execute(
                "SELECT databricks_create_role($1, 'SERVICE_PRINCIPAL')", sp_id
            )
        except Exception as e:
            if "already exists" not in str(e).lower():
                raise
        # sp_id is UUID-validated; safe to embed as a quoted identifier.
        await conn.execute(f'GRANT CONNECT ON DATABASE databricks_postgres TO "{sp_id}"')
        await conn.execute(f'GRANT CREATE ON DATABASE databricks_postgres TO "{sp_id}"')

        # Schema-ownership resolution (mirror of install.sh:719-756).
        if not desired_schema or desired_schema == "public":
            return desired_schema or "public"
        row = await conn.fetchrow(
            "SELECT pg_get_userbyid(nspowner) AS owner FROM pg_namespace WHERE nspname = $1",
            desired_schema,
        )
        if row is None or row["owner"] == sp_id:
            return desired_schema
        # Desired schema exists but is owned by someone else.
        sp_prefix = sp_id.replace("-", "")[:16]
        fallback = f"{desired_schema}_{sp_prefix}"
        if not IDENT_RE.match(fallback):
            raise ValueError(f"derived fallback is not safe: {fallback!r}")
        row2 = await conn.fetchrow(
            "SELECT pg_get_userbyid(nspowner) AS owner FROM pg_namespace WHERE nspname = $1",
            fallback,
        )
        if row2 is not None and row2["owner"] != sp_id:
            # If the deployer (us) owns it AND it's empty, drop it; else fail.
            if row2["owner"] == deployer_user:
                tcount = await conn.fetchval(
                    "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = $1",
                    fallback,
                )
                if tcount and tcount > 0:
                    raise RuntimeError(
                        f"fallback schema {fallback} owned by deployer contains "
                        f"{tcount} tables — refusing to drop. Remove manually or "
                        f"change DESIRED_SCHEMA."
                    )
                await conn.execute(f'DROP SCHEMA "{fallback}" CASCADE')
                log.warning("dropped empty stale fallback schema %s", fallback)
            else:
                raise RuntimeError(
                    f"fallback schema {fallback} owned by {row2['owner']} "
                    f"(neither SP nor deployer)"
                )
        log.warning(
            "desired schema %s owned by %s, using fallback %s",
            desired_schema, row["owner"], fallback,
        )
        return fallback
    finally:
        await conn.close()


def patch_app_config(profile: str, *, resolved_schema: str, app: dict) -> None:
    """PATCH `/api/2.0/apps/{name}` with the FULL intended state.

    The Apps PATCH API has no update_mask AND clears any top-level field not
    present in the body (install.sh:914-917). Sending a partial body wipes
    user_api_scopes / resources / config. So this hook always sends all three,
    even when only one of them is "off."
    """
    # Decide whether we need to PATCH at all.
    # We only check scopes + db resource — env vars are not stored in the
    # API's config field (the direct deploy engine drops `config`), they live
    # in app.yaml at the source root and are read on every container boot.
    effective = app.get("effective_user_api_scopes") or []
    scopes_ok = all(s in effective for s in DESIRED_SCOPES)

    have_resources = app.get("resources") or []
    have_db_resource = any(r.get("database") for r in have_resources)

    if scopes_ok and have_db_resource:
        log.info("app already has scopes + db resource — no PATCH needed")
        if resolved_schema != DESIRED_SCHEMA:
            log.error("Schema fallback fired (%s -> %s) but app.yaml is static. "
                      "Update app.yaml LAKEBASE_SCHEMA to %s and re-run "
                      "`make bundle-deploy bundle-run`.",
                      DESIRED_SCHEMA, resolved_schema, resolved_schema)
        return
    log.info("PATCHing app to add Lakebase resource attachment "
             "(scopes_ok=%s db_resource_ok=%s)",
             scopes_ok, have_db_resource)


    # Send the FULL desired state for fields we PATCH. The API has no
    # update_mask and clears any top-level field present in the body but
    # missing/null. We deliberately omit `config` — the direct engine
    # doesn't persist it and including it just wipes itself.
    payload = {
        "user_api_scopes": DESIRED_SCOPES,
        "resources": [
            {
                "name": "postgres",
                "description": "Lakebase Postgres for the cache + governance tables",
                "database": {
                    "instance_name": INSTANCE_NAME,
                    "database_name": "databricks_postgres",
                    "permission": "CAN_CONNECT_AND_CREATE",
                },
            }
        ],
    }
    cli_api("patch", f"/api/2.0/apps/{APP_NAME}", profile=profile, body=payload)
    log.info("PATCH applied — reading back to verify")
    app2 = json.loads(cli("apps", "get", APP_NAME, profile=profile))
    eff2 = app2.get("effective_user_api_scopes") or []
    res2 = app2.get("resources") or []
    log.info("post-PATCH effective_user_api_scopes: %s", eff2)
    log.info("post-PATCH resources: %d entries (db=%s)", len(res2),
             any(r.get("database") for r in res2))


def health_check(profile: str, app: dict) -> None:
    """Best-effort. Skipped if compute is STOPPED (still pre-`bundle run`)."""
    state = app.get("compute_status", {}).get("state")
    if state != "ACTIVE":
        log.info("skipping health check (compute_state=%s; run `make bundle-run` to start)", state)
        return
    url = app.get("url")
    if not url:
        log.info("no app URL yet — skipping health check")
        return
    try:
        import urllib.request
        token = json.loads(cli("auth", "token", profile=profile))["access_token"]
        req = urllib.request.Request(
            f"{url}/api/v1/health", headers={"Authorization": f"Bearer {token}"}
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            log.info("health check: %s -> %d", req.full_url, r.status)
    except Exception as e:
        log.warning("health check failed (non-fatal): %s", e)


def main() -> int:
    global APP_NAME, INSTANCE_NAME, DESIRED_SCHEMA  # noqa: PLW0603 — keep module-level for asyncpg
    p = argparse.ArgumentParser()
    p.add_argument("--target", default=os.environ.get("DATABRICKS_BUNDLE_TARGET", "fevm"))
    p.add_argument("--app", default=APP_NAME)
    p.add_argument("--instance", default=INSTANCE_NAME)
    p.add_argument("--schema", default=DESIRED_SCHEMA)
    args = p.parse_args()
    APP_NAME = args.app
    INSTANCE_NAME = args.instance
    DESIRED_SCHEMA = args.schema
    profile = args.target  # bundle target name == databricks profile (per databricks.yml)

    log.info("post-deploy: app=%s instance=%s schema=%s profile=%s",
             APP_NAME, INSTANCE_NAME, DESIRED_SCHEMA, profile)

    # 1. Wait for app to settle (STOPPED is fine — we only need the SP UUID).
    app = wait_for_app_settled(profile)
    sp_id = app.get("service_principal_client_id")
    sp_name = app.get("service_principal_name") or sp_id
    if not sp_id:
        raise RuntimeError("could not resolve service_principal_client_id from app")
    log.info("app SP: %s (%s)", sp_name, sp_id)

    # 2. Grant SP CAN_MANAGE on the database instance.
    grant_sp_manage_on_instance(profile, sp_name)

    # 3. Resolve Lakebase host + endpoint, get ephemeral creds, run Postgres SQL.
    host, endpoint = resolve_instance_host(profile)
    log.info("Lakebase host: %s endpoint: %s", host, endpoint)
    token, deployer_user = get_ephemeral_pg_token(profile, endpoint)
    resolved_schema = asyncio.run(
        configure_postgres(
            host=host,
            deployer_user=deployer_user,
            token=token,
            sp_id=sp_id,
            desired_schema=DESIRED_SCHEMA,
        )
    )
    log.info("postgres role + grants OK; schema = %s", resolved_schema)

    # 4. PATCH app config if anything is missing or the schema fell back.
    patch_app_config(profile, resolved_schema=resolved_schema, app=app)

    # 5. Best-effort health check.
    health_check(profile, app)

    log.info("post-deploy complete")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        log.error("post-deploy failed: %s", e)
        sys.exit(1)
