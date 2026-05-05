# Genie Gateway v2 deploy chain — replaces scripts/install.sh.
#
# Standard flow:   make deploy
# Source-only:     make build bundle-deploy bundle-run
# Config-only:     make bundle-deploy bundle-run
#
# Per-step verification: see /Users/alex.witt/.claude/plans/peppy-forging-acorn.md
# (or .claude/plans equivalent) for the end-to-end test plan.

TARGET ?= fevm

# Bypass the legacy Terraform-based deploy engine (which currently fails with
# "openpgp: key expired" when downloading Terraform binaries — a HashiCorp
# signing-key rotation issue). The direct engine talks to the workspace
# resource APIs without spawning Terraform.
export DATABRICKS_BUNDLE_ENGINE = direct

.PHONY: deploy build bundle-deploy bundle-run post-deploy validate logs destroy

# Order matters: post-deploy runs BEFORE bundle-run so the SP's Postgres
# role + Lakebase resource attachment are in place when the app starts.
# Otherwise the app boots into ERROR ("Role <uuid> not found in instance")
# because the apps service tries to grant the SP CAN_CONNECT_AND_CREATE on
# a role that doesn't exist yet.
deploy: build bundle-deploy post-deploy bundle-run

build:
	./scripts/build.sh

bundle-deploy:
	databricks bundle deploy --target $(TARGET)

bundle-run:
	databricks bundle run gateway --target $(TARGET)

post-deploy:
	python3 scripts/post_deploy.py --target $(TARGET)

validate:
	databricks bundle validate --target $(TARGET)

logs:
	databricks apps logs genie-gateway-v2 --profile $(TARGET) --follow

destroy:
	@echo "This will destroy the v2 stack on $(TARGET). Press Ctrl-C to abort."
	@sleep 5
	databricks bundle destroy --target $(TARGET)
