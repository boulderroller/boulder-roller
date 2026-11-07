#!/usr/bin/env python3
"""Reject edits to SQL migrations already recorded in production."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path


LOCKED_THROUGH = 142
EXPECTED_LOCKED_DIGEST = (
    "517449b6953766b565f6567a78b71dbfb70c0ae258747b5f3fe8800d4384ce2a"
)
MIGRATION_PATTERN = re.compile(r"^(\d{3})_.+\.sql$")
RETIRED_ROOT_MIGRATION_CHECKSUMS = {
    "20260108094900_raw_file_storage.sql": (
        "2283d2ff734cf432ea2c65faf12aa6cf90b953493b06c290ce6078fad17d6589"
    ),
    "20260129120000_session_revocation_reason.sql": (
        "3ee5ae1a9e6905f09a0f9dff9972c3b5a2000d2faf7d55bec0d22f56ff091064"
    ),
    "20260130100000_privacy_zones.sql": (
        "72d4e8453375b881074d01025d53f034288825c8f5ec1e463589889449420476"
    ),
    "20260211000000_cal_allocation_tables.sql": (
        "9bc7b8fc0181c5bd1df8504039b4c901e5130e49b610faabbd08e4e38aebe47e"
    ),
    "20260303010000_strava_webhooks.sql": (
        "e838936b9819ee826ef87ac8c495c0ba298dc3c786f0a452df9f9ff7f174184a"
    ),
    "20260818_device_evidence.sql": (
        "1a3ba37ada6515c06380fbb7a89285d1299b1b944aceccd3059bd0bd15cf0910"
    ),
    "20260818_laps_balance.sql": (
        "8383100f9b3f4241095cc41f23fcac8871d949c496964c809a5d31b8e5d2aa88"
    ),
    "20260818_ride_depth_fields.sql": (
        "6dda9c1ea8258214622c2603f7056d824bc762b4e9a5fb9babf531ae0b689de4"
    ),
}


def baseline_digest(sql_dir: Path) -> str:
    records: list[str] = []

    for path in sorted(sql_dir.glob("[0-9][0-9][0-9]_*.sql")):
        match = MIGRATION_PATTERN.match(path.name)
        if match is None or int(match.group(1)) > LOCKED_THROUGH:
            continue

        checksum = hashlib.sha256(path.read_bytes()).hexdigest()
        records.append(f"{checksum}  {path.name}\n")

    return hashlib.sha256("".join(records).encode("utf-8")).hexdigest()


def validate_retired_root_migrations(retired_dir: Path) -> None:
    actual = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in retired_dir.glob("*.sql")
    }
    if actual != RETIRED_ROOT_MIGRATION_CHECKSUMS:
        raise SystemExit(
            "The retired root supabase/migrations directory changed. "
            "Its filenames and bytes are frozen; put forward migrations in "
            "backend/sql instead."
        )


def main() -> None:
    backend_root = Path(__file__).resolve().parents[1]
    sql_dir = backend_root / "sql"
    actual_digest = baseline_digest(sql_dir)

    if actual_digest != EXPECTED_LOCKED_DIGEST:
        raise SystemExit(
            f"Ledgered SQL migrations 001-{LOCKED_THROUGH} changed. Add a forward migration "
            "instead of editing an applied file. "
            f"Expected {EXPECTED_LOCKED_DIGEST}, got {actual_digest}."
        )

    retired_dir = backend_root.parent / "supabase" / "migrations"
    validate_retired_root_migrations(retired_dir)

    print(f"Ledgered SQL migrations 001-{LOCKED_THROUGH} are immutable")


if __name__ == "__main__":
    main()
