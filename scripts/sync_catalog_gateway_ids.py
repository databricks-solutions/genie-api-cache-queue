"""Inject seed/<target>_state.json gateway UUIDs into router/catalog.yaml.

`seed_app.py` writes a state file mapping gateway titles → UUIDs after
provisioning. The eval harness (eval.run_eval) reads gateway UUIDs from
`router/catalog.yaml` (room.gateway_id field). This script bridges them by
copying UUIDs from the state file into the catalog so the eval can pick
the right gateway per room.

Usage:
    python scripts/sync_catalog_gateway_ids.py seed/dev_state.json
    python scripts/sync_catalog_gateway_ids.py seed/prod_state.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
CATALOG = REPO / "router" / "catalog.yaml"


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    state_path = Path(sys.argv[1])
    state = json.loads(state_path.read_text())
    name_to_id = state.get("gateways") or {}
    if not name_to_id:
        print(f"No gateways in {state_path}", file=sys.stderr)
        return 1

    catalog = yaml.safe_load(CATALOG.read_text())
    rooms = catalog.get("rooms") or []
    matched = 0
    for room in rooms:
        title = room.get("title", "")
        if title in name_to_id:
            room["gateway_id"] = name_to_id[title]
            matched += 1

    CATALOG.write_text(yaml.safe_dump(catalog, sort_keys=False, allow_unicode=True))
    print(f"Updated {matched}/{len(rooms)} gateway_ids in {CATALOG.relative_to(REPO)} from {state_path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
