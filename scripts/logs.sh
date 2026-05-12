#!/usr/bin/env bash
# Tail logs for the app deployed at $TARGET. Resolves the app name from
# `databricks bundle summary` so the same script works for dev (name varies
# by deployer's domain_friendly_name) and prod (genie-gateway).
#
# Usage:
#   ./scripts/logs.sh                       # dev, default profile
#   TARGET=prod ./scripts/logs.sh
#   TARGET=prod PROFILE=fevm ./scripts/logs.sh

set -euo pipefail

TARGET="${TARGET:-dev}"
PROFILE_ARG=()
if [ -n "${PROFILE:-}" ]; then
    PROFILE_ARG=(--profile "$PROFILE")
fi

APP_NAME=$(
    databricks bundle summary --target "$TARGET" "${PROFILE_ARG[@]}" -o json 2>/dev/null \
        | python3 -c "import sys,json; print(json.load(sys.stdin)['resources']['apps']['gateway']['name'])"
)

echo "==> tailing logs for app: $APP_NAME (target=$TARGET)"
exec databricks apps logs "$APP_NAME" "${PROFILE_ARG[@]}" --follow
