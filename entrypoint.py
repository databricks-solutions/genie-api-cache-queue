"""Entry point for Databricks Apps."""
import sys
import os
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

logger.info("Starting app.py entry point")
logger.info("Python: %s", sys.version)
logger.info("CWD: %s", os.getcwd())
logger.info("DATABRICKS_HOST: %s", os.getenv("DATABRICKS_HOST", "NOT SET"))

# Add backend/ to Python path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "backend"))
logger.info("Python path updated, importing FastAPI app...")

try:
    from app.main import app  # noqa: E402, F401
    logger.info("FastAPI app imported successfully")
except Exception as exc:
    import_error = f"{type(exc).__name__}: {exc}"
    logger.error("Failed to import app: %s", import_error, exc_info=True)

    from fastapi import FastAPI
    app = FastAPI()

    @app.get("/")
    def root():
        return {"error": import_error, "status": "import_failed"}

    @app.get("/api/health")
    def health():
        return {"status": "degraded", "error": import_error}

    @app.get("/api/v1/health")
    def health_v1():
        return {"status": "degraded", "error": import_error}
