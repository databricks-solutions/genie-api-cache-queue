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
from app.services.query_processor import query_processor
from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize storage backend (creates connection pool if using Lakebase/PGVector)
    from app.services.database import initialize_storage
    storage = await initialize_storage()

    # Start background queue processor
    queue_task = asyncio.create_task(query_processor.process_queue())

    # Start periodic OAuth token refresh for default Lakebase backend
    refresh_task = None
    if settings.storage_backend == "pgvector" and settings.lakebase_instance:
        async def _token_refresh_loop():
            while True:
                await asyncio.sleep(45 * 60)  # Every 45 minutes
                try:
                    logger.info("Background token refresh: checking default backend")
                    await storage.refresh_default_backend()
                except Exception as e:
                    logger.error("Background token refresh failed: %s", e)

        refresh_task = asyncio.create_task(_token_refresh_loop())
        logger.info("Started async OAuth token refresh task (every 45 min)")

    yield

    queue_task.cancel()
    if refresh_task:
        refresh_task.cancel()
    try:
        tasks = [queue_task] + ([refresh_task] if refresh_task else [])
        await asyncio.gather(*tasks, return_exceptions=True)
    except asyncio.CancelledError:
        pass


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
app.include_router(genie_clone_router, prefix="/api/2.0/genie")

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

if dist_dir and (dist_dir / "index.html").exists():
    assets_dir = dist_dir / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

    @app.get("/")
    async def serve_root():
        return FileResponse(str(dist_dir / "index.html"))

    @app.get("/{full_path:path}")
    async def catch_all(full_path: str):
        if full_path.startswith("api/") or full_path.startswith("docs") or full_path.startswith("openapi.json"):
            return {"error": "Not found"}
        file_path = dist_dir / full_path
        if file_path.is_file():
            return FileResponse(str(file_path))
        return FileResponse(str(dist_dir / "index.html"))
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
