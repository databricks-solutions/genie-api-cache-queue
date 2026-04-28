"""One-shot seed: create a router from router/catalog.yaml.

Posts to the deployed Gateway's /api/v1/routers endpoints. Uses the
Databricks CLI to fetch a bearer token from the configured profile.

Usage:
    python scripts/seed_router_from_yaml.py \
        --gateway-base-url https://genie-gateway-<id>.aws.databricksapps.com \
        --profile <cli-profile> \
        --router-name "default"

The script is idempotent on router name: if a router with the given
--router-name already exists the script exits 1. Delete it first via
DELETE /api/v1/routers/{id} or pass a different --router-name.
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

import httpx
import yaml


def _resolve_bearer(args) -> str:
    if args.token:
        return args.token.strip()
    if args.profile:
        out = subprocess.check_output(
            ["databricks", "auth", "token", "--profile", args.profile], text=True
        )
        return json.loads(out)["access_token"].strip()
    sys.exit("No bearer: pass --token or --profile")


def _load_catalog(path: Path) -> list[dict]:
    with path.open() as f:
        data = yaml.safe_load(f)
    rooms = data.get("rooms") or []
    if not rooms:
        sys.exit(f"No rooms found in {path}")
    return rooms


def _member_payload(room: dict, ordinal: int) -> dict:
    return {
        "gateway_id": room["gateway_id"],
        "title": room.get("title") or room["id"],
        "when_to_use": room["when_to_use"].strip(),
        "ordinal": ordinal,
        "tables": room.get("tables") or [],
        "sample_questions": room.get("sample_questions") or [],
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--gateway-base-url", required=True)
    p.add_argument("--profile")
    p.add_argument("--token")
    p.add_argument("--router-name", default="default")
    p.add_argument(
        "--catalog",
        default=str(Path(__file__).resolve().parent.parent / "router" / "catalog.yaml"),
    )
    args = p.parse_args()

    rooms = _load_catalog(Path(args.catalog))
    bearer = _resolve_bearer(args)
    headers = {"Authorization": f"Bearer {bearer}", "Content-Type": "application/json"}
    base = args.gateway_base_url.rstrip("/")

    with httpx.Client(timeout=60.0) as c:
        existing = c.get(f"{base}/api/v1/routers", headers=headers)
        existing.raise_for_status()
        if any(r["name"].lower() == args.router_name.lower() for r in existing.json()):
            sys.exit(
                f"A router named '{args.router_name}' already exists. "
                "Delete it first or pass a different --router-name."
            )

        members = [_member_payload(r, i) for i, r in enumerate(rooms)]
        create_body = {
            "name": args.router_name,
            "description": f"Seeded from {Path(args.catalog).name}",
            "members": members,
        }
        resp = c.post(f"{base}/api/v1/routers", headers=headers, json=create_body)
        if resp.status_code >= 400:
            sys.exit(f"Create failed ({resp.status_code}): {resp.text}")
        created = resp.json()

    print(f"Created router: id={created['id']} name={created['name']}")
    print(f"Members: {len(created.get('members') or [])}")
    for m in created.get("members") or []:
        print(f"  - {m['title']} ({m['gateway_id']})")


if __name__ == "__main__":
    main()
