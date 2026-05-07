# Genie Gateway deploy chain.
#
# Standard flow:   make deploy                  (defaults to TARGET=dev)
#                  make deploy TARGET=prod
# Source-only:     make build bundle-deploy bundle-run
# Validate only:   make validate
#
# Lakebase Autoscaling branch+DB ordering:
#   1. The bundle declares a postgres_branch. On create, the platform also
#      auto-creates a `databricks_postgres` database with a generated
#      resource ID (e.g. db-xxxx).
#   2. The app's `apps.resources[].postgres.database` field needs the full
#      resource path of that auto-created DB — but the ID isn't knowable
#      until step 1 completes.
#   3. `make deploy` works around this by running `bundle deploy` first
#      (which creates branches but errors on the app), looking up the DB
#      path via scripts/resolve_database.sh, then re-running `bundle deploy
#      --var database_path=...` for the full app create.

# DAB target (dev | prod). Drives which Lakebase branch + endpoint the app
# attaches to (see databricks.yml targets:).
TARGET ?= dev

# Databricks CLI profile. Empty by default — the CLI then resolves via
# DATABRICKS_CONFIG_PROFILE env var or the DEFAULT profile. Override per
# invocation: `make deploy PROFILE=my-profile`.
PROFILE ?=
PROFILE_ARG = $(if $(PROFILE),--profile $(PROFILE),)

# Per-developer dev branch suffix (Lakebase branch IDs are lowercase + hyphens).
# Defaults to a sanitized $USER but you can override on the command line:
#   make deploy DEV_USER=jane-doe
DEV_USER ?= $(shell echo "$$USER" | tr '_.' '-')

# Bundle vars set on every command. ${branch_id} resolves automatically per
# target (dev → dev-${DEV_USER}, prod → production).
BUNDLE_VARS = --var "dev_user=$(DEV_USER)"

# Bypass the legacy Terraform-based deploy engine (which currently fails with
# "openpgp: key expired" when downloading Terraform binaries — a HashiCorp
# signing-key rotation issue). The direct engine talks to the workspace
# resource APIs without spawning Terraform.
export DATABRICKS_BUNDLE_ENGINE = direct

.PHONY: deploy build bundle-deploy bundle-deploy-postgres bundle-deploy-app \
        bundle-run validate logs destroy resolve-db

# Shared helpers — read variable values from `databricks bundle summary` so
# we don't duplicate defaults from databricks.yml. The summary respects the
# active target + bundle vars.
BUNDLE_SUMMARY_CMD = databricks bundle summary --target $(TARGET) $(PROFILE_ARG) $(BUNDLE_VARS) -o json 2>/dev/null

# Full deploy: build → ensure postgres → resolve DB → deploy app → start.
deploy: build bundle-deploy-postgres bundle-deploy-app bundle-run

build:
	./scripts/build.sh

# Stage 1: deploy postgres resources. The first `bundle deploy` may error on
# the app (missing database_path), but `|| true` lets us continue — the
# branch+DB get provisioned regardless. Re-runs are idempotent and silent.
bundle-deploy-postgres:
	@echo "==> Stage 1: ensuring Lakebase project + branch exist"
	databricks bundle deploy --target $(TARGET) $(PROFILE_ARG) $(BUNDLE_VARS) || true

# Stage 2: resolve the auto-created database path and deploy the app.
bundle-deploy-app:
	@SUMMARY=$$($(BUNDLE_SUMMARY_CMD)) && \
	BRANCH_ID=$$(printf '%s' "$$SUMMARY" | python3 -c "import sys,json;d=json.load(sys.stdin);print(d['variables']['branch_id']['value'])") && \
	PROJECT_ID=$$(printf '%s' "$$SUMMARY" | python3 -c "import sys,json;d=json.load(sys.stdin);print(d['variables']['project_id']['value'])") && \
	DB_PATH=$$(./scripts/resolve_database.sh $$PROJECT_ID $$BRANCH_ID $(PROFILE)) && \
	echo "==> Stage 2: resolved database = $$DB_PATH" && \
	databricks bundle deploy --target $(TARGET) $(PROFILE_ARG) $(BUNDLE_VARS) --var "database_path=$$DB_PATH"

# Generic single-shot deploy. Use this only when you know the branch + DB
# already exist and just want to re-push code/config.
bundle-deploy:
	@SUMMARY=$$($(BUNDLE_SUMMARY_CMD)) && \
	BRANCH_ID=$$(printf '%s' "$$SUMMARY" | python3 -c "import sys,json;d=json.load(sys.stdin);print(d['variables']['branch_id']['value'])") && \
	PROJECT_ID=$$(printf '%s' "$$SUMMARY" | python3 -c "import sys,json;d=json.load(sys.stdin);print(d['variables']['project_id']['value'])") && \
	DB_PATH=$$(./scripts/resolve_database.sh $$PROJECT_ID $$BRANCH_ID $(PROFILE)) && \
	databricks bundle deploy --target $(TARGET) $(PROFILE_ARG) $(BUNDLE_VARS) --var "database_path=$$DB_PATH"

bundle-run:
	databricks bundle run gateway --target $(TARGET) $(PROFILE_ARG) $(BUNDLE_VARS)

validate:
	databricks bundle validate --target $(TARGET) $(PROFILE_ARG) $(BUNDLE_VARS)

resolve-db:
	@SUMMARY=$$($(BUNDLE_SUMMARY_CMD)) && \
	BRANCH_ID=$$(printf '%s' "$$SUMMARY" | python3 -c "import sys,json;d=json.load(sys.stdin);print(d['variables']['branch_id']['value'])") && \
	PROJECT_ID=$$(printf '%s' "$$SUMMARY" | python3 -c "import sys,json;d=json.load(sys.stdin);print(d['variables']['project_id']['value'])") && \
	./scripts/resolve_database.sh $$PROJECT_ID $$BRANCH_ID $(PROFILE)

# Resolves the deployed app's name from the bundle summary so logs follow
# both targets (dev → dev-${DEV_USER}-genie-gateway, prod → genie-gateway)
# without hardcoding either form.
logs:
	@APP_NAME=$$($(BUNDLE_SUMMARY_CMD) | python3 -c "import sys,json;d=json.load(sys.stdin);print(d['resources']['apps']['gateway']['name'])") && \
	databricks apps logs $$APP_NAME $(PROFILE_ARG) --follow

destroy:
	@echo "This will destroy the $(TARGET) stack. Press Ctrl-C to abort."
	@sleep 5
	databricks bundle destroy --target $(TARGET) $(PROFILE_ARG) $(BUNDLE_VARS)
