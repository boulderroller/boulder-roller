#!/usr/bin/env python3
"""Export the canonical client.v1 JSON Schema bundle.

Usage:
  python backend/scripts/export_client_contract_schema.py
  python backend/scripts/export_client_contract_schema.py --out /tmp/client_v1.schema.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR.parent))

from app.client_contracts import client_contract_json_schema


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, help="Optional destination path.")
    args = parser.parse_args()

    payload = json.dumps(client_contract_json_schema(), indent=2, sort_keys=True)
    if args.out:
        args.out.write_text(payload + "\n", encoding="utf-8")
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
