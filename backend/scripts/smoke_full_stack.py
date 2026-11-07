#!/usr/bin/env python3
"""
Gate 2 full-stack smoke for the fresh V4-A devnet lane.

This drives the real backend graph:
1. Create a deterministic synthetic climb ride for a finalizable Settlement Week
2. Create and activate a matching on-chain vault on the fresh lane
3. Mirror that vault into indexed_vaults and load the backend vault cache
4. Start the FastAPI app lifespan (NATS client + consumer; no autonomous EpochProcessor)
5. Stake through the real wallet-signed /vaults routes
6. Upload the ride through /rides/upload and wait for RideProcessor completion
7. Force Settlement Week processing via EpochProcessor service methods
8. Verify indexer-backed distribution history routes
9. Harvest through the real wallet-signed /vaults routes
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import math
import os
import socket
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Optional
from urllib.parse import urlparse

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(SCRIPT_DIR.parent))

try:
    from dotenv import load_dotenv

    load_dotenv(SCRIPT_DIR.parent / ".env")
except ImportError:
    pass

from fastapi.testclient import TestClient
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.transaction import Transaction

from app.config import load_auth_settings
from app.main import create_app
from app.repositories import (
    create_ride_repository,
    create_user_repository,
    get_supabase_client,
)
from app.repositories.vault import VaultRepository
from app.security.token import create_access_token
from app.services.epoch_processor import get_epoch_processor
from app.services.file_storage import create_file_storage_service
from app.services.pattern_engine import UserProfile
from app.services.ride_parser import _parse_gpx
from app.services.ride_processor import RideProcessor
from app.services.vault_indexer import get_vault_signature_cache
from app.solana_direct import (
    DirectConfig,
    _derive_vault_pda,
    get_program_settlement_clock,
    require_direct_vault_creation_supported,
)
from app.solana_env import (
    DEFAULT_BOULDER_ROLLERS_PROGRAM_ID,
    DEFAULT_CAL_MINT_ADDRESS,
    DEFAULT_DUNG_MINT_ADDRESS,
    DEFAULT_SOLANA_RPC_URL,
)
from smoke_devnet_economics import (
    wait_for_smoke_open_week,
    wait_for_smoke_finalization,
    LAMPORT_DECIMALS,
    credit_user_cal,
    ensure_token_ata,
    load_keypair,
    read_vault_state,
    seed_and_activate_vault,
    token_balance,
)
@dataclass
class SmokeClimb:
    gpx_bytes: bytes
    signature_hex: str
    signature_v2_hex: str
    start_lat: float
    start_lon: float
    end_lat: float
    end_lon: float
    vert_m: float
    distance_m: float
    avg_gradient_pct: float
    completion_time_s: int
    completed_at: datetime


@dataclass(frozen=True)
class PreflightCheck:
    name: str
    ok: bool
    detail: str
    required: bool = True


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Gate 2 full-stack smoke")
    parser.add_argument(
        "--preflight-only",
        action="store_true",
        help="Validate smoke prerequisites and exit before mutating devnet or Supabase",
    )
    parser.add_argument(
        "--allow-live-mutation",
        action="store_true",
        help="Required for the real smoke because it creates devnet accounts and Supabase rows",
    )
    parser.add_argument(
        "--require-nats",
        action="store_true",
        help="Fail preflight if NATS is unreachable instead of using inline ride processing fallback",
    )
    parser.add_argument(
        "--backend-authority-keypair",
        default=os.getenv(
            "BACKEND_AUTHORITY_KEYPAIR",
            os.getenv(
                "SOLANA_BACKEND_AUTHORITY_SECRET",
                os.getenv(
                    "SOLANA_BACKEND_AUTHORITY_PATH",
                    str(Path.home() / ".config/solana/boulderroller-backend-authority.json"),
                ),
            ),
        ),
        help="Backend authority keypair path or inline JSON/base64 secret",
    )
    parser.add_argument(
        "--fee-payer-keypair",
        default=os.getenv(
            "FEE_PAYER_KEYPAIR",
            os.getenv(
                "SOLANA_PAYER_SECRET",
                os.getenv(
                    "SOLANA_PAYER_PATH",
                    str(Path.home() / ".config/solana/boulderroller-fee-payer.json"),
                ),
            ),
        ),
        help="Fee payer keypair path or inline JSON/base64 secret",
    )
    parser.add_argument(
        "--stake-cal",
        type=int,
        default=100_000,
        help="Whole CAL units to stake through the wallet-signed route",
    )
    parser.add_argument(
        "--bootstrap-cal",
        type=int,
        default=250_000 * LAMPORT_DECIMALS,
        help="CAL base units to credit to the smoke rider before staking",
    )
    parser.add_argument(
        "--ride-cal-buffer",
        type=int,
        default=0,
        help="Extra CAL base units to credit beyond bootstrap stake funding",
    )
    parser.add_argument(
        "--rpc-url",
        default=DEFAULT_SOLANA_RPC_URL,
        help="Fresh-lane RPC URL",
    )
    parser.add_argument(
        "--program-id",
        default=DEFAULT_BOULDER_ROLLERS_PROGRAM_ID,
        help="Fresh-lane Boulder Rollers program ID",
    )
    parser.add_argument(
        "--cal-mint",
        default=DEFAULT_CAL_MINT_ADDRESS,
        help="Fresh-lane CAL mint address",
    )
    parser.add_argument(
        "--dung-mint",
        default=DEFAULT_DUNG_MINT_ADDRESS,
        help="Fresh-lane DUNG mint address",
    )
    parser.add_argument(
        "--ride-timeout-seconds",
        type=int,
        default=180,
        help="Max seconds to wait for the uploaded ride to reach completed",
    )
    parser.add_argument(
        "--indexer-timeout-seconds",
        type=int,
        default=390,
        help="Max seconds to wait for indexed distribution projections; default covers staging's 5-minute replay poll",
    )
    return parser.parse_args()


def _has_any_env(*names: str) -> bool:
    return any(bool(os.getenv(name)) for name in names)


def _describe_keypair_source(source: str) -> str:
    expanded = Path(source).expanduser()
    if expanded.exists():
        return str(expanded)
    return "inline secret"


def _check_keypair_source(label: str, source: str) -> PreflightCheck:
    try:
        keypair = load_keypair(source)
    except Exception as exc:
        expanded = Path(source).expanduser()
        if expanded.suffix == ".json" or "/" in source:
            detail = f"missing or invalid file: {expanded}"
        else:
            detail = f"invalid inline secret: {exc}"
        return PreflightCheck(label, False, detail)
    return PreflightCheck(label, True, f"{_describe_keypair_source(source)} ({keypair.pubkey()})")


def _check_pubkey(label: str, value: str) -> PreflightCheck:
    try:
        Pubkey.from_string(value)
    except Exception as exc:
        return PreflightCheck(label, False, f"invalid pubkey {value!r}: {exc}")
    return PreflightCheck(label, True, value)


def run_preflight(args: argparse.Namespace) -> bool:
    nats_url = os.getenv("NATS_URL", "nats://localhost:4222")
    nats_reachable = is_nats_reachable(nats_url)
    nats_required = bool(args.require_nats)
    supabase_url_set = _has_any_env("SUPABASE_URL")
    supabase_key_set = _has_any_env("SUPABASE_SERVICE_KEY", "SUPABASE_SERVICE_ROLE_KEY")

    checks = [
        PreflightCheck(
            "SUPABASE_URL",
            supabase_url_set,
            "set" if supabase_url_set else "missing",
        ),
        PreflightCheck(
            "Supabase service key",
            supabase_key_set,
            "set" if supabase_key_set else "missing",
        ),
        _check_keypair_source("Backend authority keypair", args.backend_authority_keypair),
        _check_keypair_source("Fee payer keypair", args.fee_payer_keypair),
        _check_pubkey("Boulder Rollers program", args.program_id),
        _check_pubkey("CAL mint", args.cal_mint),
        _check_pubkey("DUNG mint", args.dung_mint),
        PreflightCheck(
            "Live mutation acknowledgement",
            args.preflight_only or args.allow_live_mutation,
            "preflight only"
            if args.preflight_only
            else ("set" if args.allow_live_mutation else "missing --allow-live-mutation"),
        ),
        PreflightCheck(
            "NATS",
            nats_reachable,
            f"{nats_url} reachable"
            if nats_reachable
            else f"{nats_url} unreachable; inline fallback enabled",
            required=nats_required,
        ),
    ]

    print("=== Gate 2 Preflight ===")
    for check in checks:
        marker = "OK" if check.ok else ("WARN" if not check.required else "FAIL")
        print(f"{marker:<5} {check.name:<28} {check.detail}")

    required_ok = all(check.ok for check in checks if check.required)
    if required_ok:
        print("preflight: ready")
    else:
        print("preflight: blocked")
    return required_ok


def sign_prepared_transaction(transaction_b64: str, signer: Keypair) -> str:
    tx = Transaction.from_bytes(base64.b64decode(transaction_b64))
    tx.partial_sign([signer], tx.message.recent_blockhash)
    if not tx.is_signed():
        raise RuntimeError("Prepared transaction is still missing signatures after user signing")
    return base64.b64encode(bytes(tx)).decode("utf-8")


def latest_finalizable_settlement_week(settlement_clock) -> int:
    return settlement_clock.latest_finalizable_week(int(time.time()))


def is_nats_reachable(url: str) -> bool:
    parsed = urlparse(url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 4222
    try:
        with socket.create_connection((host, port), timeout=1.0):
            return True
    except OSError:
        return False


def build_synthetic_smoke_gpx(settlement_week: int, seed: int, settlement_clock) -> bytes:
    # Use a 1 Hz sample stream so the parser sees a realistic ride and the
    # climb detector has enough fidelity to derive a stable signature.
    duration_s = 2275
    total_vert_m = 560.0 + ((seed % 233) * 2.35)
    total_lat_delta = 0.052 + ((seed % 97) * 0.00011)
    total_lon_delta = 0.0016 + (((seed // 7) % 89) * 0.00004)
    start_lat = 39.96 + (((seed // 17) % 701) * 0.00002)
    start_lon = -105.04 + (((seed // 29) % 701) * 0.00002)
    lat_wave_amp = 0.00018 + (((seed // 5) % 13) * 0.00001)
    lon_wave_amp = 0.00022 + (((seed // 11) % 17) * 0.00001)
    elevation_wave_amp = 8.0 + ((seed % 19) * 0.7)
    lat_wave_cycles = 2 + (seed % 4)
    lon_wave_cycles = 3 + ((seed // 3) % 5)
    start_time = datetime.fromtimestamp(
        settlement_clock.week_start(settlement_week) + 12 * 3600,
        tz=timezone.utc,
    )
    base_elevation_m = 1450.0 + ((seed // 13) % 120)

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<gpx version="1.1" creator="BoulderRoller Full Stack Smoke">',
        "<trk><name>Smoke Climb</name><trkseg>",
    ]

    point_count = duration_s + 1
    for i in range(point_count):
        frac = i / duration_s
        lat = (
            start_lat
            + total_lat_delta * frac
            + lat_wave_amp * math.sin(frac * math.pi * lat_wave_cycles)
        )
        lon = (
            start_lon
            + total_lon_delta * (frac ** 1.18)
            + lon_wave_amp * math.cos(frac * math.pi * lon_wave_cycles)
        )
        ele = (
            base_elevation_m
            + total_vert_m * frac
            + elevation_wave_amp * math.sin(frac * math.pi * (1 + (seed % 3)))
        )
        timestamp = start_time + timedelta(seconds=i)
        lines.append(
            f'<trkpt lat="{lat:.7f}" lon="{lon:.7f}">'
            f"<ele>{ele:.2f}</ele>"
            f"<time>{timestamp.isoformat().replace('+00:00', 'Z')}</time>"
            "</trkpt>"
        )

    lines.extend(["</trkseg></trk></gpx>"])
    return "\n".join(lines).encode("utf-8")


async def derive_smoke_climb(gpx_bytes: bytes) -> SmokeClimb:
    parsed = _parse_gpx(gpx_bytes)
    processor = RideProcessor()
    record_points = processor.ride_projection_store.records_to_dicts(parsed.records)
    tile_runs = await processor.tile_service.project_points_to_tile_runs(
        points=record_points,
        start_time=parsed.started_at,
    )
    raw_climb_samples = [
        {
            "tile_id": sample.tile_id,
            "t": int(sample.t),
            "lat": sample.lat,
            "lon": sample.lon,
            "elevation_m": sample.elevation_m,
            "power_w": sample.power_w,
            "hr_bpm": sample.hr_bpm,
            "speed_mps": sample.speed_mps,
        }
        for sample in processor.tile_service.get_tile_sequence(
            record_points,
            resolution=10,
            start_time=parsed.started_at,
        )
    ]

    results = await processor.pattern_engine.detect_patterns(
        activity_id=__import__("uuid").uuid4(),
        tile_samples=tile_runs,
        raw_climb_samples=raw_climb_samples,
        user_profile=UserProfile(
            wallet="11111111111111111111111111111111",
            weight_kg=75.0,
            ftp_w=250,
        ),
        wallet_tile_history=set(),
        ride_start_time=parsed.started_at,
    )

    climbs = [
        climb
        for climb in results.climb_patterns
        if getattr(climb, "signature_hex", None)
        and getattr(climb, "signature_v2_hex", None)
        and all(
            getattr(climb, field, None) is not None
            for field in ("start_lat", "start_lon", "end_lat", "end_lon")
        )
    ]
    if not climbs:
        raise RuntimeError(
            "Synthetic GPX did not yield canonical v2 climb identity evidence"
        )

    climb = max(climbs, key=lambda value: (float(value.vert_m or 0), -(int(value.time_s or 0))))
    return SmokeClimb(
        gpx_bytes=gpx_bytes,
        signature_hex=str(climb.signature_hex),
        signature_v2_hex=str(climb.signature_v2_hex),
        start_lat=float(climb.start_lat),
        start_lon=float(climb.start_lon),
        end_lat=float(climb.end_lat),
        end_lon=float(climb.end_lon),
        vert_m=float(climb.vert_m or 0),
        distance_m=float(climb.distance_m or 0),
        avg_gradient_pct=float(climb.avg_gradient_pct or 0),
        completion_time_s=int(climb.time_s or 0),
        completed_at=parsed.completed_at,
    )


def build_auth_header(wallet: str) -> dict[str, str]:
    settings = load_auth_settings()
    token = create_access_token(
        subject=wallet,
        secret=settings.access_token_secret,
        audience=settings.audience,
        minutes=settings.access_token_minutes,
        extra_claims={"device_id": "smoke-full-stack"},
    )
    return {"Authorization": f"Bearer {token}"}


async def upsert_indexed_vault(
    vault_id: int,
    signature_hex: str,
    signature_v2_hex: str,
    start_lat: float,
    start_lon: float,
    end_lat: float,
    end_lon: float,
    name: str,
    vert_m: float,
    distance_m: int,
    avg_gradient_pct: float,
    minter: str,
    program_id: Pubkey,
) -> dict[str, Any]:
    supabase = get_supabase_client()
    pda, _ = _derive_vault_pda(vault_id, program_id)
    signature_hash_hex = hashlib.sha256(bytes.fromhex(signature_hex)).hexdigest()
    repo = VaultRepository(supabase)
    existing = await repo.get_vault_by_id(vault_id)
    if existing is None:
        await repo.create_vault(
            vault_id=vault_id,
            signature_hex=signature_hex,
            signature_hash_hex=signature_hash_hex,
            name=name,
            vert_m=vert_m,
            distance_m=distance_m,
            avg_gradient_pct=avg_gradient_pct,
            minter=minter,
            pda=str(pda),
            signature_v2_hex=signature_v2_hex,
            start_lat=start_lat,
            start_lon=start_lon,
            end_lat=end_lat,
            end_lon=end_lon,
        )

    supabase.table("indexed_vaults").update(
        {
            "name": name,
            "signature_hex": signature_hex,
            "signature_v2_hex": signature_v2_hex,
            "signature_version": 2,
            "start_lat": start_lat,
            "start_lon": start_lon,
            "end_lat": end_lat,
            "end_lon": end_lon,
            "signature_hash_hex": signature_hash_hex,
            "vert_m": vert_m,
            "distance_m": distance_m,
            "avg_gradient_pct": avg_gradient_pct,
            "minter": minter,
            "pda": str(pda),
            "on_chain_seeding_status": "active",
        }
    ).eq("id", vault_id).execute()

    refreshed = await repo.get_vault_by_id(vault_id)
    if refreshed is None:
        raise RuntimeError(f"indexed_vaults row missing for smoke vault {vault_id}")
    return refreshed


async def wait_for_vault_completion(
    ride_id: str,
    vault_signature: Optional[str] = None,
    timeout_seconds: int = 60,
) -> dict[str, Any]:
    supabase = get_supabase_client()
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        query = supabase.table("vault_completions").select(
            "id, vault_signature, on_chain_tx, on_chain_tx_error, activity_id, "
            "wallet, time_seconds, validated, validation_notes"
        ).eq("activity_id", ride_id)
        if vault_signature:
            query = query.eq("vault_signature", vault_signature)
        resp = query.limit(1).execute()
        if resp.data:
            row = resp.data[0]
            if row.get("on_chain_tx"):
                return row
            if row.get("on_chain_tx_error"):
                raise RuntimeError(f"vault completion hit on-chain error: {row['on_chain_tx_error']}")
        time.sleep(2)
    raise RuntimeError(f"Timed out waiting for vault completion row for ride {ride_id}")


def wait_for_record_board_projection(
    client: TestClient,
    vault_id: int,
    wallet: str,
    timeout_seconds: int,
) -> dict[str, Any]:
    deadline = time.time() + timeout_seconds
    last_body: Optional[dict[str, Any]] = None
    while time.time() < deadline:
        response = client.get(f"/vaults/{vault_id}/leaderboard")
        if response.status_code == 200:
            body = response.json()
            last_body = body
            for entry in body.get("leaderboard", []):
                if entry.get("wallet") == wallet:
                    return entry
        time.sleep(2)

    raise RuntimeError(
        f"Timed out waiting for Record Board projection for vault {vault_id}; last={last_body}"
    )


async def process_uploaded_ride_inline(
    *,
    ride_id: str,
    wallet: str,
) -> dict[str, Any]:
    ride_repo = create_ride_repository()
    user_repo = create_user_repository()
    ride = await ride_repo.get_ride(ride_id)
    if ride is None:
        raise RuntimeError(f"Ride row missing for inline processing fallback: {ride_id}")

    user_id = await user_repo.get_user_id(wallet)
    if user_id is None:
        raise RuntimeError(f"User row missing for inline processing fallback: {wallet}")

    profile = await user_repo.get_user_profile(wallet)
    user_weight_kg = float(profile.get("weight_kg") or 75.0) if profile else 75.0
    user_ftp_w = int(profile.get("ftp_w") or 200) if profile else 200

    file_path = ride.get("raw_file_path")
    file_type = ride.get("file_type") or "fit"
    if not file_path:
        raise RuntimeError(f"Ride {ride_id} has no raw_file_path for inline processing fallback")

    storage = create_file_storage_service()
    raw_file_bytes = await storage.download_ride_file(file_path)
    file_data_b64 = base64.b64encode(raw_file_bytes).decode("utf-8")

    processor = RideProcessor(ride_repo=ride_repo, user_repo=user_repo)
    return await processor.process_ride(
        ride_id=__import__("uuid").UUID(ride_id),
        file_data_b64=file_data_b64,
        file_type=file_type,
        user_id=__import__("uuid").UUID(user_id),
        user_weight_kg=user_weight_kg,
        user_ftp_w=user_ftp_w,
        file_bytes=raw_file_bytes,
    )


async def run_epoch_settlement_for_vault(vault_id: int, settlement_week: int, config=None) -> str:
    supabase = get_supabase_client()
    await get_vault_signature_cache().load(supabase)
    from app.services.epoch_processor import EpochProcessor
    processor = EpochProcessor(supabase, solana_config=config) if config is not None else get_epoch_processor(supabase)

    deadline = time.time() + 120
    while time.time() < deadline:
        await processor.process_settlement_cycle(vault_id=vault_id)
        resp = supabase.table("settlement_jobs").select(
            "id, state, tx_signature, prepared_tx_signature, blocked_reason, "
            "expected_pre_open_week"
        ).eq("vault_id", vault_id).eq("settlement_week", settlement_week).eq(
            "source_kind", "authoritative"
        ).limit(1).execute()
        if resp.data:
            row = resp.data[0]
            state = row.get("state")
            if state == "blocked":
                raise RuntimeError(f"settlement blocked: {row.get('blocked_reason')}")

            indexed = supabase.table("indexed_epoch_distributions").select(
                "tx_signature, vault_id, epoch, total_distributed, slot"
            ).eq("vault_id", vault_id).eq("epoch", settlement_week).order(
                "slot", desc=True
            ).limit(1).execute()
            indexed_signature = (
                str(indexed.data[0]["tx_signature"])
                if indexed.data and indexed.data[0].get("tx_signature")
                else None
            )
            signature = (
                indexed_signature
                or row.get("tx_signature")
                or row.get("prepared_tx_signature")
            )
            if processor._settlement_chain is None:
                raise RuntimeError("settlement chain reader was not initialized")
            chain_evidence = await processor._settlement_chain.read_reconciliation_evidence(
                SimpleNamespace(vault_id=vault_id, tx_signature=signature),
                signature=signature,
            )
            if chain_evidence.open_settlement_week is None:
                raise RuntimeError(
                    f"settlement vault {vault_id} has no open settlement week in chain evidence"
                )
            if (
                state == "confirmed"
                and signature
                and chain_evidence.chain_commitment == "finalized"
                and chain_evidence.open_settlement_week > settlement_week
                and chain_evidence.signature_state == "finalized"
            ):
                return str(signature)
            if (
                state == "advanced_unproven"
                and indexed_signature
                and chain_evidence.chain_commitment == "finalized"
                and chain_evidence.open_settlement_week > settlement_week
                and chain_evidence.signature_state == "finalized"
            ):
                return indexed_signature
        await asyncio.sleep(2)

    raise RuntimeError(
        f"Timed out waiting for durable settlement for vault {vault_id} week {settlement_week}"
    )


def wait_for_ride_status(
    client: TestClient,
    headers: dict[str, str],
    ride_id: str,
    expected_status: str,
    timeout_seconds: int,
) -> dict[str, Any]:
    deadline = time.time() + timeout_seconds
    last_body: Optional[dict[str, Any]] = None
    while time.time() < deadline:
        response = client.get(f"/rides/{ride_id}/status", headers=headers)
        if response.status_code != 200:
            raise RuntimeError(f"ride status request failed: {response.status_code} {response.text}")
        body = response.json()
        last_body = body
        status_value = body.get("status")
        if status_value == expected_status:
            return body
        if status_value == "failed":
            raise RuntimeError(f"ride processing failed: {body.get('error_message')}")
        time.sleep(2)

    raise RuntimeError(
        f"Timed out waiting for ride {ride_id} to reach {expected_status}; last={last_body}"
    )


def wait_for_distribution_projection(
    client: TestClient,
    vault_id: int,
    settlement_week: int,
    timeout_seconds: int,
) -> dict[str, Any]:
    deadline = time.time() + timeout_seconds
    last_body: Optional[dict[str, Any]] = None
    while time.time() < deadline:
        response = client.get(f"/distributions/vault/{vault_id}")
        if response.status_code == 200:
            body = response.json()
            last_body = body
            for row in body.get("distributions", []):
                if int(row.get("epoch") or -1) == settlement_week:
                    return row
        time.sleep(2)

    raise RuntimeError(
        f"Timed out waiting for indexed vault distribution history for vault {vault_id}; last={last_body}"
    )


def wait_for_staker_projection(
    client: TestClient,
    headers: dict[str, str],
    vault_id: int,
    settlement_week: int,
    timeout_seconds: int,
) -> Optional[dict[str, Any]]:
    # User-level staker history is still a compatibility surface in V4-A:
    # the route must stay healthy, but exact per-user projected rows may lag
    # until the dedicated indexed allocation tables are fully live.
    deadline = time.time() + min(timeout_seconds, 12)
    last_body: Optional[dict[str, Any]] = None
    saw_healthy_route = False
    while time.time() < deadline:
        response = client.get("/distributions/my?limit=50&offset=0", headers=headers)
        if response.status_code == 200:
            saw_healthy_route = True
            body = response.json()
            last_body = body
            for row in body.get("distributions", []):
                dist_id = str(row.get("distribution_id") or "")
                if dist_id == f"v4a:{vault_id}:{settlement_week}":
                    return row
        time.sleep(2)

    if saw_healthy_route:
        return None

    raise RuntimeError(
        f"Timed out waiting for /distributions/my route health for vault {vault_id}; last={last_body}"
    )


def post_json_or_raise(
    client: TestClient,
    path: str,
    *,
    headers: Optional[dict[str, str]] = None,
    body: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    if body is None:
        response = client.post(path, headers=headers or {})
    else:
        response = client.post(path, headers=headers or {}, json=body)
    if response.status_code != 200:
        raise RuntimeError(f"{path} failed: {response.status_code} {response.text}")
    return response.json()


def get_json_or_raise(
    client: TestClient,
    path: str,
    *,
    headers: Optional[dict[str, str]] = None,
) -> dict[str, Any]:
    response = client.get(path, headers=headers or {})
    if response.status_code != 200:
        raise RuntimeError(f"{path} failed: {response.status_code} {response.text}")
    return response.json()


async def create_smoke_vault(**_vault_fields: Any) -> dict[str, Any]:
    """V4-A vault bootstrap; program 0x4E removed admin_create_vault.

    V4-B creates Vaults only through the wallet-signed prepare/submit
    reservation flow, which this smoke does not drive.
    """
    raise RuntimeError(
        "admin_create_vault no longer exists; create the smoke Vault through "
        "the prepare/submit reservation flow"
    )


async def async_setup(args: argparse.Namespace) -> dict[str, Any]:
    require_direct_vault_creation_supported()
    program_id = Pubkey.from_string(args.program_id)
    cal_mint = Pubkey.from_string(args.cal_mint)
    dung_mint = Pubkey.from_string(args.dung_mint)

    backend_authority = load_keypair(args.backend_authority_keypair)
    fee_payer = load_keypair(args.fee_payer_keypair)
    smoke_user = Keypair()

    config = DirectConfig(
        rpc_url=args.rpc_url,
        program_id=program_id,
        payer=fee_payer,
        backend_authority=backend_authority,
        cal_mint_address=cal_mint,
        dung_mint_address=dung_mint,
    )

    user_cal_ata = await ensure_token_ata(
        rpc_url=args.rpc_url,
        payer=fee_payer,
        owner=smoke_user.pubkey(),
        mint=cal_mint,
        tx_type="create_ata",
        reference_id=str(smoke_user.pubkey()),
    )
    user_dung_ata = await ensure_token_ata(
        rpc_url=args.rpc_url,
        payer=fee_payer,
        owner=smoke_user.pubkey(),
        mint=dung_mint,
        tx_type="create_ata",
        reference_id=str(smoke_user.pubkey()),
    )

    bootstrap_amount = args.bootstrap_cal + args.ride_cal_buffer
    await credit_user_cal(config, smoke_user.pubkey(), bootstrap_amount)

    settlement_clock = await get_program_settlement_clock(config)
    settlement_week = settlement_clock.week_at(int(time.time())) + 1
    smoke_seed = int(time.time())
    smoke_climb = await derive_smoke_climb(
        build_synthetic_smoke_gpx(
            settlement_week=settlement_week,
            seed=smoke_seed,
            settlement_clock=settlement_clock,
        )
    )

    create_result = await create_smoke_vault(
        config=config,
        creator_wallet=str(smoke_user.pubkey()),
        signature_hex=smoke_climb.signature_hex,
        name=f"Full Stack Smoke {smoke_seed}",
        vert_m=smoke_climb.vert_m,
        distance_m=int(smoke_climb.distance_m),
        avg_gradient_pct=smoke_climb.avg_gradient_pct,
        cal_deposited=1000,
    )
    vault_id = int(create_result["vault_id"])
    print(f"smoke vault created:   {create_result['tx_signature']} (vault {vault_id})")

    seed_sig, leaderboard_sig, activate_sig = await seed_and_activate_vault(
        config=config,
        vault_id=vault_id,
        best_time_holder=smoke_user.pubkey(),
        best_time_s=smoke_climb.completion_time_s + 60,
    )
    print(f"summary seeded:       {seed_sig}")
    print(f"leaderboard seeded:   {leaderboard_sig}")
    print(f"vault activated:      {activate_sig}")

    indexed_vault = await upsert_indexed_vault(
        vault_id=vault_id,
        signature_hex=smoke_climb.signature_hex,
        signature_v2_hex=smoke_climb.signature_v2_hex,
        start_lat=smoke_climb.start_lat,
        start_lon=smoke_climb.start_lon,
        end_lat=smoke_climb.end_lat,
        end_lon=smoke_climb.end_lon,
        name=f"Full Stack Smoke {smoke_seed}",
        vert_m=smoke_climb.vert_m,
        distance_m=int(smoke_climb.distance_m),
        avg_gradient_pct=smoke_climb.avg_gradient_pct,
        minter=str(smoke_user.pubkey()),
        program_id=program_id,
    )
    await get_vault_signature_cache().load(get_supabase_client())

    return {
        "config": config,
        "user": smoke_user,
        "user_cal_ata": user_cal_ata,
        "user_dung_ata": user_dung_ata,
        "vault_id": vault_id,
        "vault_signature": indexed_vault["signature_hex"],
        "settlement_week": settlement_week,
        "smoke_climb": smoke_climb,
    }


def main() -> None:
    args = parse_args()
    if not run_preflight(args):
        raise SystemExit(2)
    if args.preflight_only:
        return

    setup = asyncio.run(async_setup(args))

    user = setup["user"]
    vault_id = int(setup["vault_id"])
    settlement_week = int(setup["settlement_week"])
    smoke_climb: SmokeClimb = setup["smoke_climb"]

    headers = build_auth_header(str(user.pubkey()))
    nats_url = os.getenv("NATS_URL", "nats://localhost:4222")
    nats_available = is_nats_reachable(nats_url)
    if not nats_available:
        os.environ["NATS_ENABLED"] = "false"
        os.environ["ENABLE_NATS_RIDE_CONSUMER"] = "false"
        print(f"nats unavailable:     {nats_url} -> inline fallback")
    os.environ["ENABLE_EPOCH_PROCESSOR"] = "false"
    app = create_app()

    with TestClient(app) as client:
        bootstrap = get_json_or_raise(client, "/auth/bootstrap", headers=headers)
        if not bootstrap.get("authenticated"):
            raise RuntimeError(f"bootstrap did not authenticate smoke user: {bootstrap}")

        prepared_stake = post_json_or_raise(
            client,
            f"/vaults/{vault_id}/stake/prepare",
            headers=headers,
            body={"cal_amount": args.stake_cal},
        )
        stake_body = post_json_or_raise(
            client,
            f"/vaults/{vault_id}/stake",
            headers=headers,
            body={
                "cal_amount": args.stake_cal,
                "signed_transaction": sign_prepared_transaction(
                    prepared_stake["transaction"],
                    user,
                ),
                "last_valid_block_height": prepared_stake["last_valid_block_height"],
                "client_request_id": f"smoke-stake-{vault_id}-{settlement_week}",
            },
        )
        print(f"route stake tx:       {stake_body.get('tx_signature')}")

        async def advance_week(earlier_vault, earlier_week):
            return await run_epoch_settlement_for_vault(earlier_vault, earlier_week, config=setup["config"])
        asyncio.run(wait_for_smoke_open_week(config=setup["config"], vault_id=vault_id, settlement_week=settlement_week, advance_week=advance_week))
        headers = build_auth_header(str(user.pubkey()))

        upload = post_json_or_raise(
            client,
            "/rides/upload?force=true",
            headers=headers,
            body={
                "file_data_b64": base64.b64encode(smoke_climb.gpx_bytes).decode("utf-8"),
                "file_type": "gpx",
            },
        )
        ride_id = str(upload["ride_id"])
        print(f"ride uploaded:        {ride_id} ({upload.get('status')})")

        if upload.get("status") == "pending":
            inline_result = asyncio.run(
                process_uploaded_ride_inline(
                    ride_id=ride_id,
                    wallet=str(user.pubkey()),
                )
            )
            print(f"inline ride process:  ok (cal={inline_result.get('cal_earned')})")

        ride_status = wait_for_ride_status(
            client,
            headers,
            ride_id,
            expected_status="completed",
            timeout_seconds=args.ride_timeout_seconds,
        )
        print(f"ride completed:       {ride_status.get('status')}")

        completion_row = asyncio.run(
            wait_for_vault_completion(
                ride_id=ride_id,
            )
        )
        if not completion_row.get("validated", True):
            raise RuntimeError(
                "vault completion failed Record Board time validation: "
                f"time={completion_row.get('time_seconds')} "
                f"reason={completion_row.get('validation_notes')}"
            )
        print(f"on-chain completion:  {completion_row['on_chain_tx']}")

        actual_vault_signature = str(completion_row.get("vault_signature") or "")
        matched_vault = asyncio.run(
            VaultRepository(get_supabase_client()).get_vault_by_signature(actual_vault_signature)
        )
        if matched_vault is None:
            raise RuntimeError(
                f"Could not resolve completed vault from signature {actual_vault_signature[:16]}..."
            )
        matched_vault_id = int(matched_vault["id"])
        if matched_vault_id != vault_id:
            raise RuntimeError(f"completion matched vault {matched_vault_id}, expected fresh vault {vault_id}")
        vault_id = matched_vault_id

        asyncio.run(wait_for_smoke_finalization(setup["config"], settlement_week))
        headers = build_auth_header(str(user.pubkey()))

        distribution_sig = asyncio.run(
            run_epoch_settlement_for_vault(
                vault_id=vault_id,
                settlement_week=settlement_week,
                config=setup["config"],
            )
        )
        print(f"epoch distributed:    {distribution_sig}")

        vault_distribution = wait_for_distribution_projection(
            client,
            vault_id=vault_id,
            settlement_week=settlement_week,
            timeout_seconds=args.indexer_timeout_seconds,
        )
        staker_distribution = wait_for_staker_projection(
            client,
            headers=headers,
            vault_id=vault_id,
            settlement_week=settlement_week,
            timeout_seconds=args.indexer_timeout_seconds,
        )
        record_board_entry = wait_for_record_board_projection(
            client,
            vault_id=vault_id,
            wallet=str(user.pubkey()),
            timeout_seconds=args.indexer_timeout_seconds,
        )
        print(f"vault history ready:  {vault_distribution['distribution_id']}")
        if staker_distribution:
            print(f"staker history ready: {staker_distribution['distribution_id']}")
        else:
            print("staker history:      route healthy; exact user projection pending compatibility lane")
        print(
            "record board ready:   "
            f"rank={record_board_entry.get('rank')} "
            f"time={record_board_entry.get('best_time_seconds')}"
        )

        pending = get_json_or_raise(
            client,
            f"/vaults/{vault_id}/pending-rewards",
            headers=headers,
        )
        if float(pending.get("total_pending") or 0) <= 0:
            raise RuntimeError(f"pending rewards stayed empty: {pending}")
        print(f"pending rewards:      {pending['total_pending']}")

        before_dung = asyncio.run(token_balance(args.rpc_url, setup["user_dung_ata"]))
        prepared_harvest = post_json_or_raise(
            client,
            f"/vaults/{vault_id}/harvest/prepare",
            headers=headers,
            body=None,
        )
        harvest = post_json_or_raise(
            client,
            f"/vaults/{vault_id}/harvest",
            headers=headers,
            body={
                "signed_transaction": sign_prepared_transaction(
                    prepared_harvest["transaction"],
                    user,
                ),
                "last_valid_block_height": prepared_harvest["last_valid_block_height"],
                "client_request_id": f"smoke-harvest-{vault_id}-{ride_id}",
            },
        )
        after_dung = asyncio.run(token_balance(args.rpc_url, setup["user_dung_ata"]))
        print(f"route harvest tx:     {harvest.get('tx_signature')}")
        print(f"user DUNG delta:      {after_dung - before_dung}")

        prepared_unstake = post_json_or_raise(
            client,
            f"/vaults/{vault_id}/unstake/prepare",
            headers=headers,
            body={"withdraw_all": True},
        )
        unstake = post_json_or_raise(
            client,
            f"/vaults/{vault_id}/unstake",
            headers=headers,
            body={
                "withdraw_all": True,
                "signed_transaction": sign_prepared_transaction(
                    prepared_unstake["transaction"],
                    user,
                ),
                "last_valid_block_height": prepared_unstake["last_valid_block_height"],
                "client_request_id": f"smoke-unstake-{vault_id}-{ride_id}",
            },
        )
        print(f"route unstake tx:     {unstake.get('tx_signature')}")

        vault_state = asyncio.run(read_vault_state(setup["config"], vault_id))
        print("=== Final State ===")
        print(f"vault id:             {vault_id}")
        print(f"settlement week:      {settlement_week}")
        print(f"ride id:              {ride_id}")
        print(f"user wallet:          {user.pubkey()}")
        print(f"user CAL balance:     {asyncio.run(token_balance(args.rpc_url, setup['user_cal_ata']))}")
        print(f"user DUNG balance:    {after_dung}")
        print(f"vault open week:      {vault_state.get('open_settlement_week')}")
        print(f"vault pending:        {vault_state.get('pending_rewards')}")
        print(f"vault pending next:   {vault_state.get('pending_rewards_next_week')}")


if __name__ == "__main__":
    main()
