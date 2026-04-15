import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path
from app.api.routes import router
from app.api.genie_clone_routes import genie_clone_router
from app.api.gateway_routes import gateway_router
from app.api.mcp_routes import mcp_router
from app.api.rbac_routes import rbac_router
from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize storage backend (creates connection pool if using Lakebase/PGVector)
    from app.services.database import initialize_storage
    storage = await initialize_storage()

    # Start periodic JWT refresh for all Lakebase backends
    refresh_task = None
    if settings.storage_backend == "pgvector" and settings.lakebase_instance:
        async def _token_refresh_loop():
            while True:
                await asyncio.sleep(30 * 60)  # Every 30 minutes
                try:
                    logger.info("Background JWT refresh: checking all backends")
                    await storage.refresh_all_backends()
                except Exception as e:
                    logger.error("Background JWT refresh failed: %s", e)

        refresh_task = asyncio.create_task(_token_refresh_loop())
        logger.info("Started background JWT refresh task (every 30 min)")

    yield

    if refresh_task:
        refresh_task.cancel()
    try:
        tasks = ([refresh_task] if refresh_task else [])
        await asyncio.gather(*tasks, return_exceptions=True)
    except asyncio.CancelledError:
        pass

    from app.services.rbac import close_http_client
    from app.api.gateway_routes import close_discovery_client
    await close_http_client()
    await close_discovery_client()


app = FastAPI(
    title="Genie API with Cache & Queue",
    description="Full-stack application for Databricks Genie API with intelligent caching and queueing",
    version="1.0.0",
    lifespan=lifespan
)

if settings.is_production:
    allow_origins = [settings.databricks_host] if settings.databricks_host else ["*"]
else:
    allow_origins = ["http://localhost:5173", "http://localhost:3000", "http://127.0.0.1:5173"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api")
app.include_router(gateway_router, prefix="/api")
app.include_router(rbac_router, prefix="/api")
app.include_router(genie_clone_router, prefix="/api/2.0/genie")
app.include_router(mcp_router, prefix="/api/2.0/mcp")

# Serve static files (frontend build)
# Databricks Apps deploys code to /app; local dev uses relative paths
possible_dist_paths = [
    Path(__file__).parent.parent.parent / "frontend" / "dist",
    Path(__file__).parent.parent / "frontend" / "dist",
    Path("../frontend/dist"),
    Path("/app/python/source_code/frontend/dist"),
    Path("/app/frontend/dist"),
    Path("/workspace/frontend/dist"),
]

dist_dir = None
for path in possible_dist_paths:
    if path.exists():
        dist_dir = path
        logger.info("Found frontend dist at: %s", dist_dir)
        break


def _sync_frontend_from_workspace(dist_dir: Path):
    """Sync frontend dist from workspace snapshot to runtime filesystem.

    Databricks Apps runtime doesn't replace existing static files on redeploy.
    This function uses the Databricks SDK to download the latest frontend build
    from the workspace and overwrite the stale runtime copy.
    """
    try:
        from databricks.sdk import WorkspaceClient
        w = WorkspaceClient()
        # Find the active deployment's source code path (the SP has access to its own snapshot)
        app_name = os.environ.get("DATABRICKS_APP_NAME", "genie-cache-queue")
        app_info = w.apps.get(app_name)
        snapshot_path = app_info.active_deployment.deployment_artifacts.source_code_path
        ws_dist = f"{snapshot_path}/frontend/dist"
        logger.info("Syncing frontend from deployment snapshot: %s", ws_dist)
        local_assets = dist_dir / "assets"
        local_assets.mkdir(parents=True, exist_ok=True)

        # Export index.html
        content = w.workspace.export(ws_dist + "/index.html").content
        if content:
            import base64
            (dist_dir / "index.html").write_bytes(base64.b64decode(content))
            logger.info("Synced index.html from workspace")

        # Export assets
        items = w.workspace.list(ws_dist + "/assets")
        for item in items:
            content = w.workspace.export(item.path).content
            if content:
                fname = Path(item.path).name
                (local_assets / fname).write_bytes(base64.b64decode(content))
                logger.info("Synced asset: %s", fname)

        # Clean up old assets that don't match the new index.html
        index_html = (dist_dir / "index.html").read_text()
        for f in local_assets.iterdir():
            if f.name.startswith("index-") and f.name not in index_html:
                f.unlink()
                logger.info("Removed stale asset: %s", f.name)

        return "OK"
    except Exception as e:
        logger.warning("Frontend sync from workspace failed (will use local files): %s", e)
        return f"FAILED: {e}"


# Sync frontend on startup if running in Databricks Apps
if os.environ.get("DATABRICKS_APP_NAME") and dist_dir:
    _sync_frontend_from_workspace(dist_dir)


def _build_index_html(assets_dir: Path) -> str:
    """Generate index.html dynamically from whatever assets exist on disk.

    Databricks Apps runtime keeps stale files across deploys, so the static
    index.html may reference JS/CSS bundles that no longer match the deployed
    code.  This function scans the assets directory at startup and builds a
    fresh index.html that points to the actual files present on disk.
    """
    js_file = css_file = None
    if assets_dir.exists():
        for f in sorted(assets_dir.iterdir()):
            if f.suffix == ".js" and f.name.startswith("index-"):
                js_file = f"/assets/{f.name}"
            elif f.suffix == ".css" and f.name.startswith("index-"):
                css_file = f"/assets/{f.name}"
    return (
        '<!doctype html>\n<html lang="en">\n<head>\n'
        '  <meta charset="UTF-8" />\n'
        '  <link rel="icon" type="image/svg+xml" href="/favicon.svg" />\n'
        '  <meta name="viewport" content="width=device-width, initial-scale=1.0" />\n'
        '  <link rel="preconnect" href="https://fonts.googleapis.com">\n'
        '  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>\n'
        '  <link href="https://fonts.googleapis.com/css2?family=DM+Sans:ital,opsz,wght@0,9..40,300;0,9..40,400;0,9..40,500;0,9..40,600;0,9..40,700;1,9..40,400&display=swap" rel="stylesheet">\n'
        '  <title>Genie Cache Gateway</title>\n'
        + (f'  <script type="module" crossorigin src="{js_file}"></script>\n' if js_file else '')
        + (f'  <link rel="stylesheet" crossorigin href="{css_file}">\n' if css_file else '')
        + '</head>\n<body>\n  <div id="root"></div>\n</body>\n</html>\n'
    )


if dist_dir and (dist_dir / "assets").exists():
    assets_dir = dist_dir / "assets"
    # Build index.html dynamically so it always matches the actual assets on disk
    _dynamic_index = _build_index_html(assets_dir)
    logger.info("Dynamic index.html built, JS/CSS from: %s", [f.name for f in assets_dir.iterdir()])

    app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

    @app.get("/")
    async def serve_root():
        from fastapi.responses import HTMLResponse
        return HTMLResponse(_dynamic_index)

    @app.get("/{full_path:path}")
    async def catch_all(full_path: str):
        if full_path.startswith("api/") or full_path.startswith("docs") or full_path.startswith("openapi.json"):
            return {"error": "Not found"}
        file_path = dist_dir / full_path
        if file_path.is_file():
            return FileResponse(str(file_path))
        from fastapi.responses import HTMLResponse
        return HTMLResponse(_dynamic_index)
else:
    logger.warning("Frontend dist not found. Serving API only.")

    @app.get("/")
    async def root():
        return {
            "message": "Genie API Backend",
            "environment": settings.app_env,
            "frontend": "Frontend not built. Run 'npm run build' in frontend directory.",
            "docs": "/docs",
            "checked_paths": [str(p) for p in possible_dist_paths]
        }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=not settings.is_production
    )
