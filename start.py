"""Startup wrapper that captures and prints errors for debugging."""
import subprocess
import sys
import os

print(f"Python: {sys.version}", flush=True)
print(f"PWD: {os.getcwd()}", flush=True)
print(f"LS: {os.listdir('.')}", flush=True)
print(f"DATABRICKS_HOST: {os.getenv('DATABRICKS_HOST', 'NOT SET')}", flush=True)
print(f"DATABRICKS_TOKEN set: {bool(os.getenv('DATABRICKS_TOKEN'))}", flush=True)

# Install deps
print("=== Installing requirements ===", flush=True)
result = subprocess.run(
    [sys.executable, "-m", "pip", "install", "-r", "backend/requirements.txt"],
    capture_output=True, text=True
)
print(result.stdout[-500:] if result.stdout else "", flush=True)
if result.returncode != 0:
    print(f"PIP FAILED: {result.stderr[-500:]}", flush=True)
    sys.exit(1)
print("=== Pip done ===", flush=True)

# Test import
os.chdir("backend")
print(f"Backend PWD: {os.getcwd()}", flush=True)

try:
    print("=== Importing app ===", flush=True)
    from app.main import app
    print("=== Import OK ===", flush=True)
except Exception as e:
    print(f"IMPORT FAILED: {e}", flush=True)
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Start uvicorn
import uvicorn
uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
