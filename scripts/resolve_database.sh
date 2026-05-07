#!/usr/bin/env bash
# Resolves the auto-created Postgres database resource path for a given
# Lakebase Autoscaling branch.
#
# When you create a Lakebase branch via DAB, the platform auto-creates a
# `databricks_postgres` PG database under a generated resource ID
# (e.g. db-xxxxxxxx). The app's bundle resource attachment requires
# that full resource path. Since the ID is only known after the branch
# exists, we look it up here and emit it as a value usable by `--var`.
#
# Usage:
#   ./scripts/resolve_database.sh <project_id> <branch_id> [profile]
#
# `profile` is optional. If empty, the Databricks CLI resolves via
# DATABRICKS_CONFIG_PROFILE env var or the DEFAULT profile.
#
# Output: the database resource path (e.g.
#   projects/<project>/branches/<branch>/databases/db-xxxxxxxx)
set -euo pipefail

PROJECT_ID="${1:?project_id required}"
BRANCH_ID="${2:?branch_id required}"
PROFILE="${3:-}"

PROFILE_ARG=()
if [ -n "$PROFILE" ]; then
  PROFILE_ARG=(--profile "$PROFILE")
fi

databricks api get \
  "/api/2.0/postgres/projects/${PROJECT_ID}/branches/${BRANCH_ID}/databases" \
  "${PROFILE_ARG[@]}" \
  | python3 -c "import sys, json; d = json.load(sys.stdin); print(d['databases'][0]['name'])"
