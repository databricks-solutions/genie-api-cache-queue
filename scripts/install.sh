#!/usr/bin/env bash
set -euo pipefail

# ---------------------------------------------------------------------------
# install.sh — Guided installer for Genie Gateway
#
# Ordering is load-bearing: the app's Postgres role + grants must exist
# BEFORE the container boots, or FastAPI's lifespan crashes on password
# auth. Steps:
#   1-6. Prereqs + prompts (profile, app name, workspace path, Lakebase)
#   7.   Build frontend
#   8.   Write .env.deploy
#   9.   Stage project files locally (no upload yet)
#  10.   apps create + wait for compute ACTIVE (no deploy)
#  11.   Resolve SP, grant CAN_MANAGE, create Postgres role + grants,
#        resolve schema name (fallback to "<name>_<sp-prefix>" if the
#        desired schema is owned by a different SP)
#  12.   Patch app.yaml with resolved values, upload to workspace
#  13.   Combined PATCH for user_api_scopes + resources
#  14.   apps deploy (blocking — safe now that DB is ready)
#  15.   Wait for RUNNING + health check
#
# Re-run with --update to skip interactive prompts (reads .env.deploy).
# Idempotent: safe to re-run after delete + recreate (the SP rotates, and
# Step 11 auto-picks a fresh schema name when the old one is orphan-owned).
# ---------------------------------------------------------------------------

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

_info()   { echo -e "${BLUE}i${NC} $*"; }
_ok()     { echo -e "${GREEN}✓${NC} $*"; }
_warn()   { echo -e "${YELLOW}⚠${NC} $*"; }
_error()  { echo -e "${RED}✗${NC} $*" >&2; }
_header() { echo -e "\n${BOLD}${CYAN}── $* ──${NC}\n"; }

_prompt() {
    local varname="$1"
    local prompt_text="$2"
    local default="${3:-}"
    local result

    if [ -n "$default" ]; then
        echo -en "  ${prompt_text} ${BOLD}[$default]${NC}: "
    else
        echo -en "  ${prompt_text}: "
    fi
    read -r result
    result="${result:-$default}"
    printf -v "$varname" '%s' "$result"
}

_prompt_yn() {
    local varname="$1"
    local prompt_text="$2"
    local default="${3:-Y}"
    local result

    echo -en "  ${prompt_text} [${default}]: "
    read -r result
    result="${result:-$default}"
    case "$result" in
        [Yy]*) printf -v "$varname" '%s' "Y" ;;
        *)     printf -v "$varname" '%s' "N" ;;
    esac
}

# ── Parse flags ──────────────────────────────────────────────────────────
UPDATE_MODE=false
for arg in "$@"; do
    case "$arg" in
        --update) UPDATE_MODE=true ;;
        --help|-h)
            echo "Usage: $0 [--update]"
            echo ""
            echo "  --update   Skip interactive prompts, re-deploy from .env.deploy"
            exit 0
            ;;
    esac
done

# ══════════════════════════════════════════════════════════════════════════
# Step 0: Banner
# ══════════════════════════════════════════════════════════════════════════
echo ""
echo -e "${BOLD}╔══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}║              Genie Gateway — Guided Installer               ║${NC}"
echo -e "${BOLD}║                                                             ║${NC}"
echo -e "${BOLD}║  Builds the frontend, syncs to workspace, and deploys       ║${NC}"
echo -e "${BOLD}║  your Databricks App with correct OAuth scopes.             ║${NC}"
echo -e "${BOLD}╚══════════════════════════════════════════════════════════════╝${NC}"
echo ""

# ══════════════════════════════════════════════════════════════════════════
# Step 1: Check prerequisites
# ══════════════════════════════════════════════════════════════════════════
_header "Step 1: Checking prerequisites"

MISSING=()

if command -v databricks &>/dev/null; then
    DB_VERSION=$(databricks --version 2>/dev/null || echo "unknown")
    _ok "databricks CLI ($DB_VERSION)"
else
    MISSING+=("databricks CLI — https://docs.databricks.com/dev-tools/cli/install.html")
fi

if command -v node &>/dev/null; then
    NODE_VERSION=$(node --version 2>/dev/null || echo "unknown")
    _ok "Node.js ($NODE_VERSION)"
else
    MISSING+=("Node.js — https://nodejs.org/")
fi

if command -v npm &>/dev/null; then
    _ok "npm ($(npm --version 2>/dev/null))"
else
    MISSING+=("npm — installed with Node.js")
fi

if command -v python3 &>/dev/null; then
    PY_VERSION=$(python3 --version 2>/dev/null || echo "unknown")
    _ok "Python ($PY_VERSION)"
else
    MISSING+=("Python 3 — https://python.org/")
fi

if [ ${#MISSING[@]} -gt 0 ]; then
    echo ""
    _error "Missing prerequisites:"
    for dep in "${MISSING[@]}"; do
        echo "    - $dep"
    done
    exit 1
fi

# ══════════════════════════════════════════════════════════════════════════
# --update mode: load .env.deploy and skip interactive prompts
# ══════════════════════════════════════════════════════════════════════════
ENV_DEPLOY_FILE="$PROJECT_DIR/.env.deploy"

if [ "$UPDATE_MODE" = true ]; then
    _header "Update mode: loading .env.deploy"

    if [ ! -f "$ENV_DEPLOY_FILE" ]; then
        _error ".env.deploy not found. Run without --update first."
        exit 1
    fi

    # shellcheck source=/dev/null
    source "$ENV_DEPLOY_FILE"

    PROFILE="${GENIE_DEPLOY_PROFILE:?GENIE_DEPLOY_PROFILE not set in .env.deploy}"
    APP_NAME="${GENIE_APP_NAME:?GENIE_APP_NAME not set in .env.deploy}"
    WS_PATH="${GENIE_WS_PATH:?GENIE_WS_PATH not set in .env.deploy}"
    STORAGE_BACKEND="pgvector"
    LAKEBASE_INSTANCE="${GENIE_LAKEBASE_INSTANCE:-}"
    LAKEBASE_CATALOG="${GENIE_LAKEBASE_CATALOG:-default}"
    LAKEBASE_SCHEMA="${GENIE_LAKEBASE_SCHEMA:-genie_cache}"

    _ok "Profile:  $PROFILE"
    _ok "App:      $APP_NAME"
    _ok "WS Path:  $WS_PATH"
    _ok "Storage:  $STORAGE_BACKEND"

    # Validate auth
    if ! databricks current-user me --profile "$PROFILE" -o json &>/dev/null; then
        _error "Could not authenticate with profile '$PROFILE'."
        exit 1
    fi

    # Skip to build step
    _info "Skipping interactive prompts (loaded from .env.deploy)"
else

# ══════════════════════════════════════════════════════════════════════════
# Step 2: Databricks profile
# ══════════════════════════════════════════════════════════════════════════
_header "Step 2: Databricks profile"

_info "Available profiles:"
databricks auth profiles 2>/dev/null | head -20 || echo "  (could not list profiles)"
echo ""

_prompt PROFILE "Databricks CLI profile" "DEFAULT"

if databricks current-user me --profile "$PROFILE" -o json &>/dev/null; then
    DEPLOYER=$(databricks current-user me --profile "$PROFILE" -o json \
        | python3 -c "import sys,json; print(json.load(sys.stdin)['userName'])")
    _ok "Authenticated as $DEPLOYER"
else
    _error "Could not authenticate with profile '$PROFILE'."
    _info "Run: databricks configure --profile $PROFILE"
    exit 1
fi

# ══════════════════════════════════════════════════════════════════════════
# Step 3: App name
# ══════════════════════════════════════════════════════════════════════════
_header "Step 3: App name"

_prompt APP_NAME "Databricks App name" "genie-gateway"

if [[ ! "$APP_NAME" =~ ^[a-z0-9][a-z0-9-]*$ ]]; then
    _error "App name must contain only lowercase letters, numbers, and hyphens."
    exit 1
fi

# ══════════════════════════════════════════════════════════════════════════
# Step 4: Workspace path
# ══════════════════════════════════════════════════════════════════════════
_header "Step 4: Workspace path"

_info "Source code will be synced to this workspace location."
echo ""
_prompt WS_PATH "Workspace path" "/Workspace/Users/$DEPLOYER/$APP_NAME"

# ══════════════════════════════════════════════════════════════════════════
# Step 5: Lakebase configuration
# ══════════════════════════════════════════════════════════════════════════
_header "Step 5: Lakebase configuration"

STORAGE_BACKEND="pgvector"

_info "Lakebase Autoscaling (Serverless) is the required storage backend."
_info "Enter the project name from Catalog Explorer > Lakebase."
_info "A custom schema is recommended — the SP owns it automatically,"
_info "so no manual GRANTs on the public schema are needed."
echo ""
_prompt LAKEBASE_INSTANCE "Lakebase Autoscaling project name" "$APP_NAME"
_prompt LAKEBASE_CATALOG  "Lakebase catalog" "default"
_prompt LAKEBASE_SCHEMA   "Lakebase schema" "genie_cache"
_ok "Storage: Lakebase Autoscaling ($LAKEBASE_INSTANCE, $LAKEBASE_CATALOG.$LAKEBASE_SCHEMA)"

fi  # end of interactive prompts (--update skips to here)

# Resolve deployer if not set (update mode)
if [ -z "${DEPLOYER:-}" ]; then
    DEPLOYER=$(databricks current-user me --profile "$PROFILE" -o json \
        | python3 -c "import sys,json; print(json.load(sys.stdin)['userName'])" 2>/dev/null || echo "unknown")
fi

# ══════════════════════════════════════════════════════════════════════════
# Step 6: Provision Lakebase Autoscaling project (if pgvector)
# ══════════════════════════════════════════════════════════════════════════
if [ "$STORAGE_BACKEND" = "pgvector" ] && [ -n "$LAKEBASE_INSTANCE" ]; then
    _header "Step 6: Provisioning Lakebase Autoscaling project"

    # Check if the project already exists
    if databricks api get "/api/2.0/postgres/projects/$LAKEBASE_INSTANCE" \
            --profile "$PROFILE" &>/dev/null; then
        _ok "Lakebase project '$LAKEBASE_INSTANCE' already exists"
    else
        # Retry create to tolerate soft-delete reservation windows (the
        # control plane may still hold the name for ~minutes after a prior
        # delete, returning "already exists" even though GET says missing).
        _info "Creating Lakebase Autoscaling project '$LAKEBASE_INSTANCE' ..."
        CREATE_OK=false
        for i in 1 2 3 4 5 6; do  # up to ~3 min, 30s between attempts
            CREATE_ERR=$(databricks api post "/api/2.0/postgres/projects?project_id=$LAKEBASE_INSTANCE" \
                    --profile "$PROFILE" \
                    --json "{\"display_name\": \"$LAKEBASE_INSTANCE\"}" 2>&1 >/dev/null || true)
            if [ -z "$CREATE_ERR" ]; then
                CREATE_OK=true
                break
            fi
            if echo "$CREATE_ERR" | grep -qi 'already exists'; then
                _info "Name not yet released after prior delete (attempt $i/6), retrying in 30s ..."
                sleep 30
            else
                _error "Lakebase create failed: $CREATE_ERR"
                break
            fi
        done
        if [ "$CREATE_OK" = true ]; then
            _ok "Lakebase project creation initiated"
        else
            _error "Failed to create Lakebase project '$LAKEBASE_INSTANCE'."
            echo "  Remediation: create it manually in Catalog Explorer > Lakebase,"
            echo "  or try again in a few minutes (soft-delete reservation ~5 min)."
            exit 1
        fi
    fi

    # Wait for the endpoint to become ACTIVE
    _info "Waiting for Lakebase endpoint to become ACTIVE ..."
    LAKEBASE_READY=false
    for i in $(seq 1 30); do  # 30 * 10s = 5 minutes
        EP_STATE=$(databricks api get \
            "/api/2.0/postgres/projects/$LAKEBASE_INSTANCE/branches/production/endpoints" \
            --profile "$PROFILE" -o json 2>/dev/null \
            | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    eps = data.get('endpoints', [])
    if eps:
        print(eps[0].get('status',{}).get('current_state','UNKNOWN'))
    else:
        print('NO_ENDPOINTS')
except:
    print('UNKNOWN')
" 2>/dev/null || echo "UNKNOWN")

        echo "    [$i/30] endpoint=$EP_STATE"
        if [ "$EP_STATE" = "ACTIVE" ]; then
            LAKEBASE_READY=true
            break
        fi
        if [ "$EP_STATE" = "FAILED" ]; then
            _error "Lakebase endpoint entered FAILED state."
            break
        fi
        sleep 10
    done

    if [ "$LAKEBASE_READY" = true ]; then
        _ok "Lakebase endpoint is ACTIVE"
    else
        _error "Lakebase endpoint did not become ACTIVE (state: $EP_STATE)."
        echo "  Cannot proceed without a ready Lakebase. Try again in a few minutes."
        exit 1
    fi
fi

# ══════════════════════════════════════════════════════════════════════════
# Step 7: Build frontend
# ══════════════════════════════════════════════════════════════════════════
_header "Step 7: Building frontend"

FRONTEND_DIR="$PROJECT_DIR/frontend"

if [ "$UPDATE_MODE" = true ]; then
    # Always rebuild in update mode (no interactive prompt)
    REBUILD="Y"
elif [ -f "$FRONTEND_DIR/dist/index.html" ]; then
    _info "Frontend already built (frontend/dist/index.html exists)."
    _prompt_yn REBUILD "Rebuild frontend?" "Y"
else
    REBUILD="Y"
fi

if [ "$REBUILD" = "Y" ]; then
    _info "Running npm install + build..."

    if ! (cd "$FRONTEND_DIR" && npm install --no-audit --no-fund 2>&1); then
        _error "npm install failed."
        echo "  Remediation:"
        echo "    1. Check Node.js version (need 18+): node --version"
        echo "    2. Try manually: cd frontend && npm install"
        echo "    3. Check npm registry access (corporate proxy?)"
        exit 1
    fi

    if ! (cd "$FRONTEND_DIR" && npm run build 2>&1); then
        _error "Frontend build failed."
        echo "  Remediation:"
        echo "    1. Try manually: cd frontend && npm run build"
        echo "    2. Check for build errors above"
        exit 1
    fi

    if [ ! -f "$FRONTEND_DIR/dist/index.html" ]; then
        _error "Build completed but frontend/dist/index.html not found."
        exit 1
    fi

    _ok "Frontend built successfully"
else
    _ok "Using existing frontend build"
fi

# ══════════════════════════════════════════════════════════════════════════
# Step 7b: Resolve app version from git
# ══════════════════════════════════════════════════════════════════════════
_header "Step 7b: Resolving app version"

APP_VERSION=$(git -C "$PROJECT_DIR" describe --tags --always --dirty 2>/dev/null || echo "unknown")
cat > "$PROJECT_DIR/backend/app/_version.py" <<EOF
# Auto-generated by install.sh — do not edit.
__version__ = "$APP_VERSION"
EOF
_ok "App version: $APP_VERSION"

# ══════════════════════════════════════════════════════════════════════════
# Step 8: Write .env.deploy
# ══════════════════════════════════════════════════════════════════════════
_header "Step 8: Writing configuration"

cat > "$ENV_DEPLOY_FILE" <<EOF
# Genie Gateway — Deployment Configuration
# Generated by install.sh on $(date -u +"%Y-%m-%dT%H:%M:%SZ")

GENIE_APP_NAME=$APP_NAME
GENIE_DEPLOY_PROFILE=$PROFILE
GENIE_WS_PATH=$WS_PATH
GENIE_STORAGE_BACKEND=$STORAGE_BACKEND
GENIE_LAKEBASE_INSTANCE=$LAKEBASE_INSTANCE
GENIE_LAKEBASE_CATALOG=$LAKEBASE_CATALOG
GENIE_LAKEBASE_SCHEMA=$LAKEBASE_SCHEMA
EOF

_ok "Configuration written to .env.deploy"
echo ""
echo "  ┌─ Configuration Summary ───────────────────────────────────┐"
echo "  │  Profile:    $PROFILE"
echo "  │  App name:   $APP_NAME"
echo "  │  WS path:    $WS_PATH"
echo "  │  Storage:    $STORAGE_BACKEND"
if [ "$STORAGE_BACKEND" = "pgvector" ]; then
echo "  │  Lakebase:   $LAKEBASE_INSTANCE (Autoscaling, $LAKEBASE_CATALOG.$LAKEBASE_SCHEMA)"
fi
echo "  └───────────────────────────────────────────────────────────┘"

# ══════════════════════════════════════════════════════════════════════════
# Step 9: Stage project files (local only — sync happens after SP resolution)
# ══════════════════════════════════════════════════════════════════════════
# We defer the workspace upload until Step 12 because app.yaml's
# LAKEBASE_SCHEMA may be auto-adjusted in Step 11 (see the schema-ownership
# fallback). Staging a clean copy locally now lets us patch once and sync
# the final version.
_header "Step 9: Staging project files"

STAGING_DIR=$(mktemp -d)
trap 'rm -rf "$STAGING_DIR"' EXIT

rsync -a \
    --exclude='.git' \
    --exclude='.claude' \
    --exclude='.vscode' \
    --exclude='.databricks' \
    --exclude='.idea' \
    --exclude='docs' \
    --exclude='notebooks' \
    --exclude='scripts' \
    --exclude='test-evidence' \
    --exclude='node_modules' \
    --exclude='__pycache__' \
    --exclude='.pytest_cache' \
    --exclude='htmlcov' \
    --exclude='.DS_Store' \
    --exclude='.env' \
    --exclude='.env.*' \
    --exclude='CLAUDE.md' \
    --exclude='docker-compose.pgvector.yml' \
    --exclude='*.pyc' \
    --exclude='venv' \
    --exclude='.venv' \
    --exclude='backend/venv' \
    --exclude='backend/.venv' \
    "$PROJECT_DIR/" "$STAGING_DIR/"

# Copy the built frontend into the staging dir
cp -r "$FRONTEND_DIR/dist" "$STAGING_DIR/frontend/dist"

_ok "Files staged ($(du -sh "$STAGING_DIR" | cut -f1) total)"

# ══════════════════════════════════════════════════════════════════════════
# Step 10: Create or resume the app (no deploy yet)
# ══════════════════════════════════════════════════════════════════════════
# We split create vs. deploy so the DB role and schema (Step 11) can be
# provisioned BEFORE the container boots. A fresh deploy would otherwise
# race the `initialize_storage()` lifespan and crash on password auth.
_header "Step 10: Creating / waking the app"

APP_EXISTS=false
if databricks apps get "$APP_NAME" --profile "$PROFILE" &>/dev/null; then
    APP_EXISTS=true
    _ok "App '$APP_NAME' already exists"
else
    _info "Creating app '$APP_NAME' ..."
    if ! databricks apps create "$APP_NAME" \
            --description "Genie Gateway — Performance and governance layer for Databricks Genie API" \
            --profile "$PROFILE" --no-wait 2>&1; then
        _error "Failed to create app '$APP_NAME'."
        echo "  Remediation:"
        echo "    databricks apps create $APP_NAME --profile $PROFILE"
        exit 1
    fi
    _ok "App created"
fi

# Wait for compute to be ACTIVE before deploying.
# On a fresh app, app_status stays STARTING until the first deploy succeeds,
# but compute_status goes ACTIVE once the container is ready — that's the
# real gate for 'apps deploy'.
_get_compute_state() {
    databricks apps get "$APP_NAME" --profile "$PROFILE" -o json 2>/dev/null \
        | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    print(d.get('compute_status', {}).get('state', 'UNKNOWN'))
except:
    print('UNKNOWN')
" 2>/dev/null || echo "UNKNOWN"
}

_get_app_state() {
    databricks apps get "$APP_NAME" --profile "$PROFILE" -o json 2>/dev/null \
        | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    print(d.get('app_status', {}).get('state', 'UNKNOWN'))
except:
    print('UNKNOWN')
" 2>/dev/null || echo "UNKNOWN"
}

COMPUTE_STATE=$(_get_compute_state)
APP_STATE=$(_get_app_state)

# If the app exists but compute is stopped, start it
if [ "$COMPUTE_STATE" != "ACTIVE" ]; then
    if [ "$APP_EXISTS" = true ]; then
        _info "Compute is $COMPUTE_STATE. Starting app ..."
        databricks apps start "$APP_NAME" --profile "$PROFILE" --no-wait 2>/dev/null || true
    fi

    _info "Waiting for compute to become ACTIVE ..."
    for i in $(seq 1 36); do  # 36 * 10s = 6 minutes
        sleep 10
        COMPUTE_STATE=$(_get_compute_state)
        APP_STATE=$(_get_app_state)
        echo "    [$i/36] compute=$COMPUTE_STATE  app=$APP_STATE"
        if [ "$COMPUTE_STATE" = "ACTIVE" ]; then
            break
        fi
        if [ "$COMPUTE_STATE" = "ERROR" ] || [ "$APP_STATE" = "DELETED" ]; then
            _error "App compute entered $COMPUTE_STATE state."
            echo "  Check: databricks apps get $APP_NAME --profile $PROFILE"
            exit 1
        fi
    done

    if [ "$COMPUTE_STATE" != "ACTIVE" ]; then
        _error "Compute did not become ACTIVE (currently: $COMPUTE_STATE)."
        echo "  The app may need more time. Check status and deploy manually:"
        echo "    databricks apps get $APP_NAME --profile $PROFILE"
        echo "    databricks apps deploy $APP_NAME --source-code-path $WS_PATH --profile $PROFILE"
        exit 1
    fi
fi

_ok "Compute is ACTIVE (app=$APP_STATE)"

# ══════════════════════════════════════════════════════════════════════════
# Step 11: Resolve SP and configure Lakebase (role, grants, schema name)
# ══════════════════════════════════════════════════════════════════════════
# Critical: this runs BEFORE `apps deploy` so the app's SP can authenticate
# against Postgres on its very first boot. If the schema already exists
# under a different SP (e.g. after delete + reinstall, which rotates the
# SP), fall back to "${schema}_${sp-prefix}" instead of fighting for
# ownership.
_header "Step 11: Resolving SP and configuring Lakebase"

APP_JSON=$(databricks apps get "$APP_NAME" --profile "$PROFILE" -o json 2>/dev/null || echo "{}")
SP_CLIENT_ID=$(echo "$APP_JSON" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    print(d.get('service_principal_client_id', ''))
except:
    print('')
" 2>/dev/null || echo "")

if [ -z "$SP_CLIENT_ID" ]; then
    _error "Could not resolve app service principal."
    echo "  Check: databricks apps get $APP_NAME --profile $PROFILE"
    exit 1
fi

SP_DISPLAY_NAME=$(echo "$APP_JSON" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    print(d.get('service_principal_name', '') or '')
except:
    print('')
" 2>/dev/null || echo "")

_ok "App SP: ${SP_DISPLAY_NAME:-$SP_CLIENT_ID} ($SP_CLIENT_ID)"

ROLE_CREATED="SKIP"
LAKEBASE_DB_RESOURCE=""

if [ "$STORAGE_BACKEND" = "pgvector" ] && [ -n "$LAKEBASE_INSTANCE" ]; then
    # Grant CAN_MANAGE to the SP on the Lakebase project (idempotent)
    _info "Granting CAN_MANAGE to SP on Lakebase project '$LAKEBASE_INSTANCE' ..."
    PERM_PAYLOAD="{\"access_control_list\": [{\"service_principal_name\": \"${SP_DISPLAY_NAME:-$SP_CLIENT_ID}\", \"permission_level\": \"CAN_MANAGE\"}]}"
    if databricks api patch "/api/2.0/permissions/database-projects/$LAKEBASE_INSTANCE" \
            --profile "$PROFILE" --json "$PERM_PAYLOAD" &>/dev/null; then
        _ok "SP granted CAN_MANAGE on Lakebase project"
    else
        _warn "Could not grant SP permissions. Continuing — may need manual grant."
    fi

    # Resolve the Lakebase database + endpoint
    LAKEBASE_DB_RESOURCE=$(databricks api get \
        "/api/2.0/postgres/projects/$LAKEBASE_INSTANCE/branches/production/databases" \
        --profile "$PROFILE" -o json 2>/dev/null \
        | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    dbs = data.get('databases', [])
    if dbs: print(dbs[0]['name'])
except Exception: pass
" 2>/dev/null || true)

    ENDPOINT_INFO=$(databricks api get \
        "/api/2.0/postgres/projects/$LAKEBASE_INSTANCE/branches/production/endpoints" \
        --profile "$PROFILE" -o json 2>/dev/null || echo "{}")
    ENDPOINT_NAME=$(echo "$ENDPOINT_INFO" | python3 -c "
import sys, json
try:
    eps = json.load(sys.stdin).get('endpoints', [])
    print(eps[0]['name'] if eps else '')
except: print('')
" 2>/dev/null)
    LAKEBASE_HOST=$(echo "$ENDPOINT_INFO" | python3 -c "
import sys, json
try:
    eps = json.load(sys.stdin).get('endpoints', [])
    print(eps[0]['status']['hosts']['host'] if eps else '')
except: print('')
" 2>/dev/null)

    if [ -z "$LAKEBASE_DB_RESOURCE" ] || [ -z "$ENDPOINT_NAME" ] || [ -z "$LAKEBASE_HOST" ]; then
        _error "Could not resolve Lakebase database/endpoint info."
        echo "  LAKEBASE_DB_RESOURCE='$LAKEBASE_DB_RESOURCE'"
        echo "  ENDPOINT_NAME='$ENDPOINT_NAME'"
        echo "  LAKEBASE_HOST='$LAKEBASE_HOST'"
        exit 1
    fi

    _ok "Lakebase endpoint: $LAKEBASE_HOST"

    # Create SP's Postgres role + grants, and resolve the final schema name.
    # We deliberately DO NOT create the schema here — the app's
    # storage_pgvector.initialize() does `CREATE SCHEMA IF NOT EXISTS` as
    # the SP, which makes the SP the owner automatically. (If we created it
    # as the deployer and tried ALTER OWNER, Postgres requires membership
    # in the target role, which we don't have.)
    _info "Configuring Postgres role and resolving schema name ..."

    DB_SETUP_OUTPUT=$(LB_PROFILE="$PROFILE" LB_ENDPOINT="$ENDPOINT_NAME" \
        LB_HOST="$LAKEBASE_HOST" LB_SP_ID="$SP_CLIENT_ID" \
        LB_DESIRED_SCHEMA="$LAKEBASE_SCHEMA" \
        python3 << 'PYEOF'
import subprocess, json, sys, os, asyncio, re

profile = os.environ['LB_PROFILE']
endpoint = os.environ['LB_ENDPOINT']
host = os.environ['LB_HOST']
sp_id = os.environ['LB_SP_ID']
desired_schema = os.environ['LB_DESIRED_SCHEMA']

def fail(tag, msg):
    print(f'REASON={tag}: {msg}')
    print(f'SCHEMA={desired_schema}')
    print('STATUS=FAIL')
    sys.exit(0)

try:
    r = subprocess.run(
        ['databricks', 'api', 'post', '/api/2.0/postgres/credentials',
         '--profile', profile, '--json', json.dumps({'endpoint': endpoint}), '-o', 'json'],
        capture_output=True, text=True, check=True)
    token = json.loads(r.stdout)['token']
    r = subprocess.run(
        ['databricks', 'current-user', 'me', '--profile', profile, '-o', 'json'],
        capture_output=True, text=True, check=True)
    username = json.loads(r.stdout)['userName']
except Exception as e:
    fail('creds', str(e))

try:
    import asyncpg
except ImportError:
    fail('deps', 'asyncpg not installed — run: pip install asyncpg')

_UUID_RE = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')
_IDENT_RE = re.compile(r'^[a-z_][a-z0-9_]*$')

async def run():
    import ssl as ssl_module
    if not _UUID_RE.match(sp_id):
        fail('input', f'sp_id is not a valid UUID: {sp_id!r}')
    if desired_schema and not _IDENT_RE.match(desired_schema):
        fail('input', f'schema name is not a safe identifier: {desired_schema!r}')
    ctx = ssl_module.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl_module.CERT_NONE
    conn = await asyncpg.connect(host=host, port=5432, database='databricks_postgres',
                                 user=username, password=token, ssl=ctx)
    try:
        await conn.execute('CREATE EXTENSION IF NOT EXISTS databricks_auth')
        try:
            await conn.execute("SELECT databricks_create_role($1, 'SERVICE_PRINCIPAL')", sp_id)
        except Exception as e:
            if 'already exists' not in str(e).lower():
                raise
        # sp_id is UUID-validated above; safe to interpolate as a quoted identifier
        await conn.execute(f'GRANT CONNECT ON DATABASE databricks_postgres TO "{sp_id}"')
        await conn.execute(f'GRANT CREATE ON DATABASE databricks_postgres TO "{sp_id}"')

        final_schema = desired_schema
        if desired_schema and desired_schema != 'public':
            row = await conn.fetchrow(
                "SELECT pg_get_userbyid(nspowner) AS owner FROM pg_namespace WHERE nspname = $1",
                desired_schema)
            if row is not None and row['owner'] != sp_id:
                # 16 hex chars from the SP UUID — effectively zero collision risk.
                sp_prefix = sp_id.replace('-', '')[:16]
                final_schema = f"{desired_schema}_{sp_prefix}"
                if not _IDENT_RE.match(final_schema):
                    fail('input', f'derived fallback schema is not a safe identifier: {final_schema!r}')
                row2 = await conn.fetchrow(
                    "SELECT pg_get_userbyid(nspowner) AS owner FROM pg_namespace WHERE nspname = $1",
                    final_schema)
                if row2 is not None and row2['owner'] != sp_id:
                    # Fallback is stale. If the deployer (us) owns it — e.g.
                    # leftover from a prior install attempt where the ALTER
                    # OWNER couldn't transfer to the SP — AND it contains no
                    # tables, drop it so the app can recreate cleanly.
                    # Otherwise fail loudly to avoid silent data loss.
                    if row2['owner'] == username:
                        table_count = await conn.fetchval(
                            "SELECT COUNT(*) FROM information_schema.tables "
                            "WHERE table_schema = $1",
                            final_schema)
                        if table_count and table_count > 0:
                            print(f"REASON=fallback schema {final_schema} owned by deployer contains {table_count} tables — refusing to drop. Remove manually or rename LAKEBASE_SCHEMA.")
                            print(f"SCHEMA={desired_schema}")
                            print('STATUS=FAIL')
                            return
                        await conn.execute(f'DROP SCHEMA "{final_schema}" CASCADE')
                        print(f'NOTE=dropped empty stale fallback schema "{final_schema}" owned by deployer')
                    else:
                        print(f"REASON=fallback schema {final_schema} owned by {row2['owner']} (neither SP nor deployer)")
                        print(f"SCHEMA={desired_schema}")
                        print('STATUS=FAIL')
                        return
                print(f'NOTE=desired schema "{desired_schema}" owned by {row["owner"]}, using "{final_schema}"')
        print(f'SCHEMA={final_schema}')
        print('STATUS=OK')
    finally:
        await conn.close()

try:
    asyncio.run(run())
except Exception as e:
    fail('sql', str(e))
PYEOF
)

    # Parse the structured output — use `|| true` so a missing line (e.g. no
    # NOTE when nothing unusual happened) doesn't trip `set -e`.
    FINAL_SCHEMA=$(echo "$DB_SETUP_OUTPUT" | { grep '^SCHEMA=' || true; } | head -1 | sed 's/^SCHEMA=//')
    STATUS=$(echo "$DB_SETUP_OUTPUT" | { grep '^STATUS=' || true; } | head -1 | sed 's/^STATUS=//')
    NOTE=$(echo "$DB_SETUP_OUTPUT" | { grep '^NOTE=' || true; } | head -1 | sed 's/^NOTE=//')
    REASON=$(echo "$DB_SETUP_OUTPUT" | { grep '^REASON=' || true; } | head -1 | sed 's/^REASON=//')

    if [ "$STATUS" = "OK" ] && [ -n "$FINAL_SCHEMA" ]; then
        ROLE_CREATED="OK"
        if [ -n "$NOTE" ]; then
            _warn "$NOTE"
        fi
        if [ "$FINAL_SCHEMA" != "$LAKEBASE_SCHEMA" ]; then
            LAKEBASE_SCHEMA="$FINAL_SCHEMA"
            # Persist for future --update runs
            python3 -c "
import re
p = '$ENV_DEPLOY_FILE'
s = open(p).read()
if re.search(r'^GENIE_LAKEBASE_SCHEMA=', s, flags=re.MULTILINE):
    s = re.sub(r'^GENIE_LAKEBASE_SCHEMA=.*\$', 'GENIE_LAKEBASE_SCHEMA=$LAKEBASE_SCHEMA', s, flags=re.MULTILINE)
else:
    s += '\nGENIE_LAKEBASE_SCHEMA=$LAKEBASE_SCHEMA\n'
open(p, 'w').write(s)
"
        fi
        _ok "Postgres role + grants configured for SP"
        _ok "Schema: $LAKEBASE_SCHEMA (app will create it on first boot, owned by SP)"
    else
        ROLE_CREATED="FAIL"
        _warn "DB setup failed: ${REASON:-unknown}"
        echo ""
        echo "  Connect to Lakebase as a human user with CAN_MANAGE and run:"
        echo "    CREATE EXTENSION IF NOT EXISTS databricks_auth;"
        echo "    SELECT databricks_create_role('$SP_CLIENT_ID', 'SERVICE_PRINCIPAL');"
        echo "    GRANT CONNECT ON DATABASE databricks_postgres TO \"$SP_CLIENT_ID\";"
        echo "    GRANT CREATE ON DATABASE databricks_postgres TO \"$SP_CLIENT_ID\";"
        # In --update mode there's no interactive user to run the manual
        # remediation above — bail so we don't deploy against an unusable schema.
        if [ "$UPDATE_MODE" = true ]; then
            _error "DB setup failed in --update mode; refusing to deploy. Fix manually and re-run."
            exit 1
        fi
    fi
fi

# ══════════════════════════════════════════════════════════════════════════
# Step 12: Patch app.yaml with resolved values and sync to workspace
# ══════════════════════════════════════════════════════════════════════════
_header "Step 12: Syncing files to workspace"

PATCHED_APP_YAML=$(mktemp)
trap 'rm -rf "$STAGING_DIR" "$PATCHED_APP_YAML"' EXIT

python3 -c "
import re, sys
content = open('$PROJECT_DIR/app.yaml').read()
content = re.sub(r'^(name:).*\$', r'\1 $APP_NAME', content, flags=re.MULTILINE)
replacements = {
    'STORAGE_BACKEND': '$STORAGE_BACKEND',
    'LAKEBASE_INSTANCE': '$LAKEBASE_INSTANCE',
    'LAKEBASE_CATALOG': '$LAKEBASE_CATALOG',
    'LAKEBASE_SCHEMA': '$LAKEBASE_SCHEMA',
}
for key, val in replacements.items():
    content = re.sub(
        rf'(- name: {key}\n\s+value:).*',
        rf'\1 {val}',
        content
    )
sys.stdout.write(content)
" > "$PATCHED_APP_YAML"

cp "$PATCHED_APP_YAML" "$STAGING_DIR/app.yaml"
_ok "Patched app.yaml (LAKEBASE_SCHEMA=$LAKEBASE_SCHEMA)"

_info "Uploading to $WS_PATH ..."
if ! databricks workspace import-dir "$STAGING_DIR" "$WS_PATH" \
        --profile "$PROFILE" --overwrite 2>&1; then
    _error "Failed to upload files to workspace."
    echo "  Remediation:"
    echo "    1. Check workspace permissions for $WS_PATH"
    echo "    2. Try: databricks workspace import-dir . $WS_PATH --profile $PROFILE --overwrite"
    exit 1
fi
_ok "Files uploaded to workspace"

# ══════════════════════════════════════════════════════════════════════════
# Step 13: Configure OAuth scopes and Lakebase resource (combined PATCH)
# ══════════════════════════════════════════════════════════════════════════
# The apps PATCH endpoint ignores the `update_mask` query param — any PATCH
# replaces the whole record for the fields in the body and clears fields not
# present. So we must send `user_api_scopes` and `resources` in the SAME
# payload, or the second PATCH wipes whatever the first one set.
_header "Step 13: Configuring OAuth scopes and app resources"

# LAKEBASE_DB_RESOURCE was resolved in Step 11 if pgvector + instance set.
_info "Setting user_api_scopes and resources in a single PATCH ..."

# Build the combined payload.  Resources are included only if we resolved a
# Lakebase database in Step 11.
PATCH_PAYLOAD=$(LAKEBASE_DB_RESOURCE="$LAKEBASE_DB_RESOURCE" python3 -c "
import json, os

payload = {
    'user_api_scopes': ['sql', 'serving.serving-endpoints', 'dashboards.genie'],
}

db = os.environ.get('LAKEBASE_DB_RESOURCE', '')
if db:
    branch = '/'.join(db.split('/')[:4])
    payload['resources'] = [{
        'name': 'postgres',
        'postgres': {
            'branch': branch,
            'database': db,
            'permission': 'CAN_CONNECT_AND_CREATE',
        }
    }]

print(json.dumps(payload))
")

# Retry up to 3 times to tolerate transient errors.  Surface the API
# response on the final attempt so failures are diagnosable.
SCOPES_SET="FAIL"
PATCH_STDERR="$(mktemp)"
trap 'rm -rf "$STAGING_DIR" "$PATCHED_APP_YAML" "$PATCH_STDERR"' EXIT
for SCOPE_ATTEMPT in 1 2 3; do
    databricks api patch "/api/2.0/apps/$APP_NAME" \
        --profile "$PROFILE" --json "$PATCH_PAYLOAD" > /dev/null 2>"$PATCH_STDERR" || true

    # Verify by reading back `effective_user_api_scopes` (the actually-applied
    # scope list; `user_api_scopes` is the requested list).
    SCOPES_SET=$(databricks apps get "$APP_NAME" --profile "$PROFILE" -o json 2>/dev/null \
        | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    scopes = d.get('effective_user_api_scopes', []) or []
    print('OK' if 'dashboards.genie' in scopes else 'FAIL')
except:
    print('FAIL')
" 2>/dev/null || echo "FAIL")

    if [ "$SCOPES_SET" = "OK" ]; then
        break
    fi
    if [ "$SCOPE_ATTEMPT" -lt 3 ]; then
        _info "Scopes not yet applied (attempt $SCOPE_ATTEMPT/3), retrying in 10s ..."
        sleep 10
    fi
done

if [ "$SCOPES_SET" = "OK" ]; then
    _ok "OAuth scopes configured: sql, serving.serving-endpoints, dashboards.genie"
    if [ -n "$LAKEBASE_DB_RESOURCE" ]; then
        _ok "Postgres resource configured on app (CAN_CONNECT_AND_CREATE)"
    fi
else
    _warn "Could not verify OAuth scopes were set after 3 attempts."
    if [ -s "$PATCH_STDERR" ]; then
        echo ""
        echo "  Last PATCH response:"
        sed 's/^/    /' "$PATCH_STDERR"
    fi
    echo ""
    echo "  Set scopes manually via REST API:"
    echo "    databricks api patch \"/api/2.0/apps/$APP_NAME\" \\"
    echo "      --profile $PROFILE --json '$PATCH_PAYLOAD'"
    echo ""
    _warn "Without these scopes the app will get 403 errors on Genie API calls."
    _warn "After setting scopes, users must sign out and sign back into the app to get a fresh OAuth token."
fi

# ══════════════════════════════════════════════════════════════════════════
# Step 14: Deploy source code
# ══════════════════════════════════════════════════════════════════════════
# DB role, grants, schema name and app resources are all in place — the
# container's lifespan() can safely connect on boot.
_header "Step 14: Deploying source code"

_info "Deploying (blocks until the container is up) ..."
if ! databricks apps deploy "$APP_NAME" \
        --source-code-path "$WS_PATH" \
        --profile "$PROFILE" 2>&1; then
    _error "Deployment failed."
    echo "  Remediation:"
    echo "    databricks apps deploy $APP_NAME --source-code-path $WS_PATH --profile $PROFILE"
    echo "    databricks apps logs $APP_NAME --profile $PROFILE --follow"
    exit 1
fi
_ok "Deployment complete"

# ══════════════════════════════════════════════════════════════════════════
# Step 15: Wait for app to reach RUNNING + health check
# ══════════════════════════════════════════════════════════════════════════
_header "Step 15: Waiting for app to reach RUNNING"

APP_URL=""
DEPLOY_OK=false

for i in $(seq 1 24); do  # 24 * 10s = 4 minutes
    sleep 10

    APP_JSON=$(databricks apps get "$APP_NAME" --profile "$PROFILE" -o json 2>/dev/null || echo "{}")

    DEPLOY_STATE=$(echo "$APP_JSON" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    ad = d.get('active_deployment') or d.get('pending_deployment') or {}
    print(ad.get('status', {}).get('state', 'UNKNOWN'))
except:
    print('UNKNOWN')
" 2>/dev/null || echo "UNKNOWN")

    APP_STATE=$(echo "$APP_JSON" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    print(d.get('app_status', {}).get('state', 'UNKNOWN'))
except:
    print('UNKNOWN')
" 2>/dev/null || echo "UNKNOWN")

    APP_URL=$(echo "$APP_JSON" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    print(d.get('url', ''))
except:
    print('')
" 2>/dev/null || echo "")

    echo "    [$i/24] deploy=$DEPLOY_STATE  app=$APP_STATE"

    if [ "$DEPLOY_STATE" = "SUCCEEDED" ] && [ "$APP_STATE" = "RUNNING" ]; then
        DEPLOY_OK=true
        break
    fi

    if [ "$DEPLOY_STATE" = "FAILED" ]; then
        _error "Deployment failed."
        echo "  Check logs: databricks apps logs $APP_NAME --profile $PROFILE --follow"
        break
    fi
done

if [ "$DEPLOY_OK" = true ]; then
    _ok "App is running!"
else
    _warn "App has not reached RUNNING state yet. It may still be starting."
    _info "Check status: databricks apps get $APP_NAME --profile $PROFILE"
    _info "Check logs:   databricks apps logs $APP_NAME --profile $PROFILE --follow"
fi

# Health check (best effort)
if [ -n "$APP_URL" ]; then
    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "$APP_URL/api/v1/health" 2>/dev/null || echo "000")
    if [ "$HTTP_CODE" = "200" ]; then
        _ok "Health check passed ($APP_URL/api/v1/health)"
    elif [ "$HTTP_CODE" != "000" ]; then
        _info "Health check returned HTTP $HTTP_CODE (app may still be starting)"
    fi
fi

# ══════════════════════════════════════════════════════════════════════════
# Summary
# ══════════════════════════════════════════════════════════════════════════
echo ""
echo -e "${BOLD}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}${BOLD}  Installation complete!${NC}"
echo ""
echo "  App:       $APP_NAME"
echo "  Deployer:  $DEPLOYER"
if [ -n "$SP_CLIENT_ID" ]; then
echo "  SP:        ${SP_DISPLAY_NAME:-$SP_CLIENT_ID} ($SP_CLIENT_ID)"
fi
echo ""
if [ -n "$APP_URL" ]; then
    echo -e "  ${BOLD}URL: ${CYAN}${APP_URL}${NC}"
else
    echo "  URL: (available once the app finishes starting)"
    echo "       databricks apps get $APP_NAME --profile $PROFILE"
fi

# ── Automated (done) ─────────────────────────────────────────────────────
echo ""
echo -e "  ${GREEN}${BOLD}Automated (done):${NC}"
echo -e "    ${GREEN}✓${NC} Frontend built and synced to workspace"
echo -e "    ${GREEN}✓${NC} Source code synced to $WS_PATH"
echo -e "    ${GREEN}✓${NC} App deployed"
echo -e "    ${GREEN}✓${NC} OAuth scopes: sql, serving.serving-endpoints, dashboards.genie"
echo -e "    ${GREEN}✓${NC} Storage backend: $STORAGE_BACKEND"
if [ -n "$LAKEBASE_INSTANCE" ]; then
    echo -e "    ${GREEN}✓${NC} Lakebase Autoscaling project: $LAKEBASE_INSTANCE"
fi
if [ -n "$SP_CLIENT_ID" ]; then
    if [ "${ROLE_CREATED:-}" = "OK" ]; then
        echo -e "    ${GREEN}✓${NC} SP granted CAN_MANAGE on Lakebase project"
        echo -e "    ${GREEN}✓${NC} SP Postgres role + CONNECT/CREATE grants"
        echo -e "    ${GREEN}✓${NC} Schema: $LAKEBASE_SCHEMA (created by app on first boot, owned by SP)"
    fi
fi

# ── Remaining manual steps (if any) ─────────────────────────────────────
SP_ID_FOR_DISPLAY="${SP_CLIENT_ID:-<app-sp-client-id>}"
HAS_MANUAL_STEPS=false

if [ "${ROLE_CREATED:-}" != "OK" ] && [ -n "$SP_CLIENT_ID" ]; then
    HAS_MANUAL_STEPS=true
    echo ""
    echo -e "  ${YELLOW}${BOLD}Remaining manual step:${NC}"
    echo ""
    echo -e "    ${BOLD}Create the SP's PostgreSQL role and schema${NC}"
    echo "       Connect to Lakebase as a human user and run:"
    echo ""
    echo -e "       ${CYAN}CREATE EXTENSION IF NOT EXISTS databricks_auth;"
    echo -e "       SELECT databricks_create_role('$SP_ID_FOR_DISPLAY', 'SERVICE_PRINCIPAL');"
    echo -e "       GRANT CONNECT ON DATABASE databricks_postgres TO \"$SP_ID_FOR_DISPLAY\";"
    echo -e "       GRANT CREATE ON DATABASE databricks_postgres TO \"$SP_ID_FOR_DISPLAY\";"
    if [ "$LAKEBASE_SCHEMA" != "public" ]; then
    echo -e "       CREATE SCHEMA IF NOT EXISTS \"$LAKEBASE_SCHEMA\";"
    echo -e "       ALTER SCHEMA \"$LAKEBASE_SCHEMA\" OWNER TO \"$SP_ID_FOR_DISPLAY\";"
    fi
    echo -e "${NC}"
fi

if [ "$HAS_MANUAL_STEPS" = false ]; then
    echo ""
    echo -e "  ${GREEN}${BOLD}All Lakebase setup completed automatically!${NC}"
fi

# ── Update instructions ──────────────────────────────────────────────────
echo ""
echo -e "  ${BOLD}Updating code later:${NC}"
echo ""
echo -e "    ${CYAN}./scripts/install.sh --update${NC}"
echo ""
echo "  Or manually:"
echo "    cd frontend && npm install && npm run build && cd .."
echo "    databricks sync . $WS_PATH --profile $PROFILE --full"
echo "    databricks apps deploy $APP_NAME --source-code-path $WS_PATH --profile $PROFILE"
echo ""
echo -e "${BOLD}═══════════════════════════════════════════════════════════════${NC}"
