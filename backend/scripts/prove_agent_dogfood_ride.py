#!/usr/bin/env python3
"""Generate and optionally upload an agent-testable sensor-backed dogfood ride.

The default path is intentionally credential-free:
1. Build a current-dated TCX ride with GPS, altitude, watts, heart rate, cadence,
   and distance samples.
2. Validate the TCX shape and freshness locally.
3. Check the live API rollout status for the Collect DUNG stage.

Set BR_TEST_ACCESS_TOKEN or pass --access-token with --upload to exercise the
authenticated production upload path for a disposable dogfood account. Pass
--collect-vault-id when that account already has pending DUNG on a known vault.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
import os
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


DEFAULT_API_URL = "https://api.boulderroller.xyz"
DEFAULT_OUTPUT = Path("/tmp/boulderroller-agent-dogfood-power-current.tcx")
BACKEND_ROOT = Path(__file__).resolve().parents[1]
EXPECTED_BALANCE_ACTION_ORDER = (
    "collect_dung",
    "deposit_cal",
    "withdraw_cal",
    "add_funds",
    "create_vault_usdc",
    "withdraw_to_wallet",
)
TERMINAL_RIDE_STATUSES = {"completed", "under_review", "failed"}


@dataclass(frozen=True)
class RideFixtureSummary:
    path: str | None
    sha256: str
    size_bytes: int
    file_type: str
    first_time: str
    last_time: str
    duration_seconds: int
    trackpoints: int
    gps_points: int
    altitude_points: int
    distance_points: int
    power_points: int
    heart_rate_points: int
    cadence_points: int
    avg_power_w: float
    avg_hr_bpm: float
    total_distance_m: float
    elevation_gain_m: float
    freshness_seconds: float
    reward_grade_input: bool


@dataclass(frozen=True)
class HttpResult:
    ok: bool
    status: int
    body: Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a current sensor-backed dogfood ride and prove rollout readiness."
    )
    parser.add_argument("--api-url", default=os.getenv("BR_API_URL", DEFAULT_API_URL))
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--completed-at",
        default=None,
        help="UTC ISO timestamp for the last trackpoint. Defaults to five minutes ago.",
    )
    parser.add_argument("--duration-minutes", type=float, default=50.0)
    parser.add_argument("--sample-seconds", type=int, default=5)
    parser.add_argument("--start-lat", type=float, default=40.0069)
    parser.add_argument("--start-lon", type=float, default=-105.3059)
    parser.add_argument("--base-altitude-m", type=float, default=1688.0)
    parser.add_argument("--elevation-gain-m", type=float, default=430.0)
    parser.add_argument("--distance-m", type=float, default=9200.0)
    parser.add_argument("--skip-live-status", action="store_true")
    parser.add_argument("--upload", action="store_true", help="Upload the generated ride with a bearer token.")
    parser.add_argument(
        "--access-token",
        default=os.getenv("BR_TEST_ACCESS_TOKEN"),
        help="Disposable account access token. Defaults to BR_TEST_ACCESS_TOKEN.",
    )
    parser.add_argument("--poll", action="store_true", help="Poll ride status after upload.")
    parser.add_argument("--poll-timeout-seconds", type=int, default=180)
    parser.add_argument(
        "--collect-vault-id",
        type=int,
        default=None,
        help="Known vault id with pending DUNG for the disposable account.",
    )
    parser.add_argument(
        "--probe-pending-dung",
        action="store_true",
        help="Scan the authenticated account for vaults with pending DUNG.",
    )
    parser.add_argument(
        "--collect-first-pending",
        action="store_true",
        help="Collect DUNG from the first vault with pending rewards found by --probe-pending-dung.",
    )
    parser.add_argument(
        "--vault-scan-limit",
        type=int,
        default=100,
        help="Maximum listed vaults to scan when probing pending DUNG.",
    )
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON only.")
    return parser.parse_args()


def parse_utc_datetime(value: str | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc) - timedelta(minutes=5)
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def iso_z(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def child_text(element: ET.Element, child_name: str) -> str | None:
    for child in element.iter():
        if local_name(child.tag) == child_name and child.text is not None:
            return child.text.strip()
    return None


def numeric_child(element: ET.Element, child_name: str) -> float | None:
    raw = child_text(element, child_name)
    if raw is None or raw == "":
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def heart_rate_value(trackpoint: ET.Element) -> float | None:
    for child in trackpoint:
        if local_name(child.tag) != "HeartRateBpm":
            continue
        value = numeric_child(child, "Value")
        if value is not None:
            return value
    return None


def generate_tcx_bytes(
    *,
    completed_at: datetime,
    duration_minutes: float,
    sample_seconds: int,
    start_lat: float,
    start_lon: float,
    base_altitude_m: float,
    elevation_gain_m: float,
    distance_m: float,
) -> bytes:
    if duration_minutes <= 0:
        raise ValueError("duration_minutes must be positive")
    if sample_seconds <= 0:
        raise ValueError("sample_seconds must be positive")

    duration_seconds = int(duration_minutes * 60)
    sample_count = int(duration_seconds / sample_seconds) + 1
    started_at = completed_at - timedelta(seconds=duration_seconds)
    activity_id = iso_z(started_at)
    lines = [
        '<TrainingCenterDatabase xmlns="http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
        'xmlns:ns3="http://www.garmin.com/xmlschemas/ActivityExtension/v2">',
        "  <Activities>",
        '    <Activity Sport="Biking">',
        f"      <Id>{activity_id}</Id>",
        f'      <Lap StartTime="{activity_id}">',
        f"        <TotalTimeSeconds>{duration_seconds}</TotalTimeSeconds>",
        f"        <DistanceMeters>{distance_m:.2f}</DistanceMeters>",
        "        <MaximumSpeed>14.20</MaximumSpeed>",
        "        <Calories>845</Calories>",
        "        <AverageHeartRateBpm><Value>149</Value></AverageHeartRateBpm>",
        "        <MaximumHeartRateBpm><Value>171</Value></MaximumHeartRateBpm>",
        "        <Intensity>Active</Intensity>",
        "        <Cadence>86</Cadence>",
        "        <TriggerMethod>Manual</TriggerMethod>",
        "        <Track>",
    ]

    for index in range(sample_count):
        progress = index / max(sample_count - 1, 1)
        timestamp = started_at + timedelta(seconds=index * sample_seconds)
        distance = distance_m * progress
        altitude = base_altitude_m + (elevation_gain_m * progress) + 4.0 * math.sin(progress * math.pi * 4)
        lat = start_lat + (0.036 * progress)
        lon = start_lon + (0.010 * math.sin(progress * math.pi * 2)) + (0.008 * progress)
        heart_rate = round(132 + 31 * progress + 4 * math.sin(progress * math.pi * 8))
        cadence = round(82 + 7 * math.sin(progress * math.pi * 12))
        watts = round(214 + 35 * progress + 12 * math.sin(progress * math.pi * 10))
        lines.extend(
            [
                "          <Trackpoint>",
                f"            <Time>{iso_z(timestamp)}</Time>",
                "            <Position>",
                f"              <LatitudeDegrees>{lat:.7f}</LatitudeDegrees>",
                f"              <LongitudeDegrees>{lon:.7f}</LongitudeDegrees>",
                "            </Position>",
                f"            <AltitudeMeters>{altitude:.2f}</AltitudeMeters>",
                f"            <DistanceMeters>{distance:.2f}</DistanceMeters>",
                f"            <HeartRateBpm><Value>{heart_rate}</Value></HeartRateBpm>",
                f"            <Cadence>{cadence}</Cadence>",
                "            <Extensions>",
                "              <TPX>",
                f"                <Watts>{watts}</Watts>",
                "              </TPX>",
                "            </Extensions>",
                "          </Trackpoint>",
            ]
        )

    lines.extend(
        [
            "        </Track>",
            "      </Lap>",
            "      <Creator xsi:type=\"Device_t\">",
            "        <Name>Boulder Roller Agent Fixture</Name>",
            "      </Creator>",
            "    </Activity>",
            "  </Activities>",
            "</TrainingCenterDatabase>",
            "",
        ]
    )
    return "\n".join(lines).encode("utf-8")


def validate_tcx_bytes(tcx_bytes: bytes, *, path: Path | None = None, now: datetime | None = None) -> RideFixtureSummary:
    try:
        root = ET.fromstring(tcx_bytes)
    except ET.ParseError as exc:
        raise ValueError(f"TCX XML is invalid: {exc}") from exc

    if local_name(root.tag) != "TrainingCenterDatabase":
        raise ValueError("TCX root must be TrainingCenterDatabase")

    trackpoints = [element for element in root.iter() if local_name(element.tag) == "Trackpoint"]
    if len(trackpoints) < 100:
        raise ValueError(f"expected at least 100 trackpoints, found {len(trackpoints)}")

    times: list[datetime] = []
    power_values: list[float] = []
    heart_rate_values: list[float] = []
    altitude_values: list[float] = []
    distance_values: list[float] = []
    cadence_values: list[float] = []
    gps_points = 0

    for trackpoint in trackpoints:
        time_text = child_text(trackpoint, "Time")
        if time_text:
            times.append(parse_utc_datetime(time_text))

        lat = numeric_child(trackpoint, "LatitudeDegrees")
        lon = numeric_child(trackpoint, "LongitudeDegrees")
        if lat is not None and lon is not None:
            gps_points += 1

        altitude = numeric_child(trackpoint, "AltitudeMeters")
        if altitude is not None:
            altitude_values.append(altitude)

        distance = numeric_child(trackpoint, "DistanceMeters")
        if distance is not None:
            distance_values.append(distance)

        heart_rate = heart_rate_value(trackpoint)
        if heart_rate is not None:
            heart_rate_values.append(heart_rate)

        cadence = numeric_child(trackpoint, "Cadence")
        if cadence is not None:
            cadence_values.append(cadence)

        watts = numeric_child(trackpoint, "Watts")
        if watts is not None:
            power_values.append(watts)

    if not times:
        raise ValueError("TCX must include trackpoint times")
    if gps_points < len(trackpoints):
        raise ValueError("every trackpoint must include GPS coordinates")
    if len(power_values) < len(trackpoints):
        raise ValueError("every trackpoint must include watts")
    if len(heart_rate_values) < len(trackpoints):
        raise ValueError("every trackpoint must include heart rate")
    if len(cadence_values) < len(trackpoints):
        raise ValueError("every trackpoint must include cadence")
    if len(distance_values) < len(trackpoints):
        raise ValueError("every trackpoint must include distance")
    if len(altitude_values) < len(trackpoints):
        raise ValueError("every trackpoint must include altitude")

    first_time = min(times)
    last_time = max(times)
    current_time = now or datetime.now(timezone.utc)
    freshness_seconds = (current_time - last_time).total_seconds()
    if freshness_seconds < -600:
        raise ValueError("ride completion time is more than ten minutes in the future")
    if freshness_seconds > 30 * 24 * 60 * 60:
        raise ValueError("ride completion time is older than the automatic economics window")

    elevation_gain = max(altitude_values) - min(altitude_values)
    total_distance = max(distance_values)
    reward_grade_input = bool(power_values and heart_rate_values and total_distance > 0 and elevation_gain > 0)

    return RideFixtureSummary(
        path=str(path) if path else None,
        sha256=hashlib.sha256(tcx_bytes).hexdigest(),
        size_bytes=len(tcx_bytes),
        file_type="tcx",
        first_time=iso_z(first_time),
        last_time=iso_z(last_time),
        duration_seconds=int((last_time - first_time).total_seconds()),
        trackpoints=len(trackpoints),
        gps_points=gps_points,
        altitude_points=len(altitude_values),
        distance_points=len(distance_values),
        power_points=len(power_values),
        heart_rate_points=len(heart_rate_values),
        cadence_points=len(cadence_values),
        avg_power_w=round(sum(power_values) / len(power_values), 1),
        avg_hr_bpm=round(sum(heart_rate_values) / len(heart_rate_values), 1),
        total_distance_m=round(total_distance, 1),
        elevation_gain_m=round(elevation_gain, 1),
        freshness_seconds=round(freshness_seconds, 1),
        reward_grade_input=reward_grade_input,
    )


def assert_parser_visible_tcx(tcx_bytes: bytes) -> None:
    if str(BACKEND_ROOT) not in sys.path:
        sys.path.insert(0, str(BACKEND_ROOT))

    try:
        from app.services.workout_parse_adapter import (
            calculate_metrics_rust,
            parse_ride_file_bytes_rust,
        )
    except Exception as exc:
        raise ValueError(f"backend workout parser is unavailable: {exc}") from exc

    parsed = parse_ride_file_bytes_rust(tcx_bytes, "tcx")
    records = parsed.records
    if len(records) < 100:
        raise ValueError(f"parser saw too few records: {len(records)}")

    power_points = sum(1 for record in records if record.power_w is not None)
    heart_rate_points = sum(1 for record in records if record.heart_rate_bpm is not None)
    altitude_points = sum(1 for record in records if record.elevation_m is not None)
    gps_points = sum(1 for record in records if record.lat is not None and record.lon is not None)

    if gps_points < len(records):
        raise ValueError("backend parser did not see GPS on every record")
    if altitude_points < len(records):
        raise ValueError("backend parser did not see altitude on every record")
    if power_points < len(records):
        raise ValueError("backend parser did not see watts on every record")
    if heart_rate_points < len(records):
        raise ValueError("backend parser did not see heart rate on every record")

    metrics = calculate_metrics_rust(parsed, user_ftp_w=200)
    if not metrics.avg_power_w or not metrics.normalized_power_w or metrics.tss <= 0:
        raise ValueError(
            "backend parser did not produce reward-grade power metrics "
            f"(avg_power={metrics.avg_power_w}, np={metrics.normalized_power_w}, tss={metrics.tss})"
        )


def write_fixture(args: argparse.Namespace) -> tuple[bytes, RideFixtureSummary]:
    completed_at = parse_utc_datetime(args.completed_at)
    tcx_bytes = generate_tcx_bytes(
        completed_at=completed_at,
        duration_minutes=args.duration_minutes,
        sample_seconds=args.sample_seconds,
        start_lat=args.start_lat,
        start_lon=args.start_lon,
        base_altitude_m=args.base_altitude_m,
        elevation_gain_m=args.elevation_gain_m,
        distance_m=args.distance_m,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(tcx_bytes)
    summary = validate_tcx_bytes(tcx_bytes, path=args.output)
    assert_parser_visible_tcx(tcx_bytes)
    return tcx_bytes, summary


def api_request(
    api_url: str,
    method: str,
    path: str,
    *,
    token: str | None = None,
    payload: dict[str, Any] | None = None,
    timeout: int = 30,
) -> HttpResult:
    url = f"{api_url.rstrip('/')}/{path.lstrip('/')}"
    data = None
    headers = {
        "Accept": "application/json",
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0.0.0 Safari/537.36 BoulderRollerAgentDogfood/1.0"
        ),
    }
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"

    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body_bytes = response.read()
            body = json.loads(body_bytes.decode("utf-8")) if body_bytes else None
            return HttpResult(ok=200 <= response.status < 300, status=response.status, body=body)
    except urllib.error.HTTPError as exc:
        body_bytes = exc.read()
        try:
            body = json.loads(body_bytes.decode("utf-8")) if body_bytes else body_bytes.decode("utf-8")
        except Exception:
            body = body_bytes.decode("utf-8", errors="replace")
        return HttpResult(ok=False, status=exc.code, body=body)


def assert_live_rollout_status(api_url: str) -> dict[str, Any]:
    result = api_request(api_url, "GET", "/status")
    if not result.ok:
        raise RuntimeError(f"API /status failed with {result.status}: {result.body}")
    status_body = result.body
    rollout = status_body.get("balance_rollout") if isinstance(status_body, dict) else None
    if not isinstance(rollout, dict):
        raise RuntimeError("API /status did not include balance_rollout")

    failures: list[str] = []
    if status_body.get("environment") != "production":
        failures.append(f"environment={status_body.get('environment')}")
    if status_body.get("solana_stub_mode") is not False:
        failures.append("solana_stub_mode must be false")
    if status_body.get("auth_signature_bypass_effective") is not False:
        failures.append("auth_signature_bypass_effective must be false")
    if status_body.get("dev_routes_enabled") is not False:
        failures.append("dev_routes_enabled must be false")
    if rollout.get("enforced") is not True:
        failures.append("balance_rollout.enforced must be true")
    if rollout.get("order_valid") is not True:
        failures.append("balance_rollout.order_valid must be true")
    if rollout.get("blockers") != []:
        failures.append(f"balance_rollout.blockers={rollout.get('blockers')}")
    if rollout.get("action_order") != list(EXPECTED_BALANCE_ACTION_ORDER):
        failures.append("balance_rollout.action_order changed")
    enabled_actions = rollout.get("enabled_actions")
    if not isinstance(enabled_actions, list) or "collect_dung" not in enabled_actions:
        failures.append(f"collect_dung not enabled: {enabled_actions}")
    if failures:
        raise RuntimeError("; ".join(failures))
    return status_body


def upload_ride(api_url: str, token: str, tcx_bytes: bytes) -> dict[str, Any]:
    payload = {
        "file_data_b64": base64.b64encode(tcx_bytes).decode("ascii"),
        "file_type": "tcx",
    }
    result = api_request(api_url, "POST", "/rides/upload", token=token, payload=payload, timeout=60)
    if not result.ok:
        raise RuntimeError(f"ride upload failed with {result.status}: {result.body}")
    return result.body


def poll_ride_status(api_url: str, token: str, ride_id: str, timeout_seconds: int) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    latest: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        result = api_request(api_url, "GET", f"/rides/{ride_id}/status", token=token, timeout=30)
        if not result.ok:
            raise RuntimeError(f"ride status failed with {result.status}: {result.body}")
        latest = result.body
        status_value = str(latest.get("status") or latest.get("processing_status") or "").lower()
        if status_value in TERMINAL_RIDE_STATUSES:
            return latest
        time.sleep(5)
    raise RuntimeError(f"ride {ride_id} did not reach terminal status in {timeout_seconds}s: {latest}")


def collect_dung(api_url: str, token: str, vault_id: int) -> dict[str, Any]:
    pending = api_request(api_url, "GET", f"/vaults/{vault_id}/pending-rewards", token=token, timeout=30)
    if not pending.ok:
        raise RuntimeError(f"pending DUNG check failed with {pending.status}: {pending.body}")
    total_pending = float((pending.body or {}).get("total_pending") or (pending.body or {}).get("totalPending") or 0)
    if total_pending <= 0:
        raise RuntimeError(f"vault {vault_id} has no pending DUNG for this account")

    collected = api_request(api_url, "POST", f"/vaults/{vault_id}/harvest", token=token, payload=None, timeout=60)
    if not collected.ok:
        raise RuntimeError(f"Collect DUNG failed with {collected.status}: {collected.body}")
    return {"pending_before": pending.body, "collect_response": collected.body}


def _number_from_body(body: Any, *keys: str) -> float:
    if not isinstance(body, dict):
        return 0.0
    for key in keys:
        value = body.get(key)
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return 0.0


def probe_pending_dung(api_url: str, token: str, *, limit: int = 100) -> dict[str, Any]:
    if limit <= 0:
        raise ValueError("vault scan limit must be positive")

    stakes_result = api_request(api_url, "GET", "/vaults/my/stakes", token=token, timeout=30)
    if not stakes_result.ok:
        raise RuntimeError(f"my stakes check failed with {stakes_result.status}: {stakes_result.body}")

    vaults_result = api_request(api_url, "GET", f"/vaults?limit={limit}", token=token, timeout=30)
    if not vaults_result.ok:
        raise RuntimeError(f"vault list failed with {vaults_result.status}: {vaults_result.body}")

    stakes_body = stakes_result.body if isinstance(stakes_result.body, dict) else {}
    vaults_body = vaults_result.body if isinstance(vaults_result.body, dict) else {}
    vaults = vaults_body.get("vaults") if isinstance(vaults_body.get("vaults"), list) else []
    positive: list[dict[str, Any]] = []
    checked: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    for vault in vaults:
        if not isinstance(vault, dict) or vault.get("id") is None:
            continue
        vault_id = int(vault["id"])
        pending = api_request(api_url, "GET", f"/vaults/{vault_id}/pending-rewards", token=token, timeout=30)
        row = {
            "vault_id": vault_id,
            "vault_name": vault.get("name"),
            "on_chain_active": vault.get("on_chain_active"),
            "status": pending.status,
        }
        if pending.ok:
            total_pending = _number_from_body(pending.body, "total_pending", "totalPending")
            net_estimate = _number_from_body(pending.body, "net_estimate", "netEstimate")
            row.update({"total_pending": total_pending, "net_estimate": net_estimate})
            checked.append(row)
            if total_pending > 0:
                positive.append(row)
        else:
            detail = pending.body.get("detail") if isinstance(pending.body, dict) else pending.body
            row["detail"] = detail
            errors.append(row)

    return {
        "stake_count": len(stakes_body.get("stakes") or []),
        "vault_count": len(vaults),
        "positive": positive,
        "checked": checked,
        "errors": errors,
    }


def main() -> int:
    args = parse_args()
    evidence: dict[str, Any] = {
        "api_url": args.api_url.rstrip("/"),
        "upload_requested": bool(args.upload),
        "collect_vault_id": args.collect_vault_id,
    }

    try:
        tcx_bytes, fixture = write_fixture(args)
        evidence["ride_fixture"] = asdict(fixture)

        if not args.skip_live_status:
            evidence["live_status"] = assert_live_rollout_status(args.api_url)

        authenticated_requested = (
            args.upload
            or args.collect_vault_id is not None
            or args.probe_pending_dung
            or args.collect_first_pending
        )
        if authenticated_requested:
            if not args.access_token:
                raise RuntimeError("BR_TEST_ACCESS_TOKEN or --access-token is required for authenticated dogfood actions")

        if args.upload:
            upload_response = upload_ride(args.api_url, args.access_token, tcx_bytes)
            evidence["upload"] = upload_response
            ride_id = upload_response.get("ride_id") or upload_response.get("rideId")
            if args.poll and ride_id:
                evidence["ride_status"] = poll_ride_status(
                    args.api_url,
                    args.access_token,
                    str(ride_id),
                    args.poll_timeout_seconds,
                )
        else:
            evidence["upload"] = {
                "status": "skipped",
                "reason": "pass --upload with BR_TEST_ACCESS_TOKEN for disposable-account upload",
            }

        if args.collect_vault_id is not None:
            evidence["collect_dung"] = collect_dung(args.api_url, args.access_token, args.collect_vault_id)

        if args.probe_pending_dung or args.collect_first_pending:
            probe = probe_pending_dung(args.api_url, args.access_token, limit=args.vault_scan_limit)
            evidence["pending_dung_probe"] = probe
            if args.collect_first_pending:
                first = next(iter(probe["positive"]), None)
                if not first:
                    raise RuntimeError("no pending DUNG found for this account")
                evidence["collect_dung"] = collect_dung(args.api_url, args.access_token, int(first["vault_id"]))

    except Exception as exc:
        evidence["ok"] = False
        evidence["error"] = str(exc)
        print(json.dumps(evidence, indent=2, sort_keys=True), file=sys.stderr)
        return 1

    evidence["ok"] = True
    if args.json:
        print(json.dumps(evidence, sort_keys=True))
    else:
        print(json.dumps(evidence, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
