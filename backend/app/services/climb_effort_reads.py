"""Viewer projections shared by canonical Climb and Vault boards."""

from datetime import datetime, timezone
import math

from fastapi import HTTPException

from ..client_contracts import ClimbEffort, ClimbEffortMetrics, ClimbPatternPower, RecordBoard, RecordBoardEntry, TruthSource
from .privacy_resolver import resolve_ride_visibility, normalize_moderation_state, MODERATION_HIDDEN_STATES
from .training_eligibility import is_training_eligible

_OWNER_METRICS = {"threshold", "intensity_factor", "load", "power_zone_s", "power_zone_tops_w", "max_hr_bpm"}
_SAMPLE_DETECTORS = {"canonical", "canonical_v2", "persistence", "momentum", "legacy"}
_DIRECT_SAMPLE_DETECTORS = {"canon_traversal_v1", *{f"template_match:{d}" for d in _SAMPLE_DETECTORS}}


def _nonnegative(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0


def legacy_pattern_power(ride, pattern, *, recorded_stream=False):
    """Read retained provenance, never recompute watts or infer kind from watts.

    Generic detector markers can be rewritten by the geometry backfill, so
    those also require an independent recorded-power fact. Canon traversals
    and exact template markers are written by sample-average paths only.
    No legacy writer stores the standard-mass estimate in avg_power_w.
    """
    read = (
        ((ride.get("training_metrics") or {}).get("climbs") or {}).get(str(pattern.get("id")))
        if is_training_eligible(ride) else None
    )
    if isinstance(read, dict) and read.get("basis") == "training_engine_span":
        source = read
    else:
        detector = pattern.get("detector_version")
        direct = detector in _DIRECT_SAMPLE_DETECTORS
        recorded = (ride.get("metrics_version") == "workout_parse_metrics_v1"
                    and _nonnegative(ride.get("power_sample_count")) and ride["power_sample_count"] > 0)
        if not direct and not (detector in _SAMPLE_DETECTORS and (recorded or recorded_stream)):
            return {}
        source = pattern
    if not _nonnegative(source.get("avg_power_w")):
        return {}
    result = {"power_kind": "measured", "avg_power_w": source["avg_power_w"]}
    if _nonnegative(source.get("w_per_kg")):
        result["w_per_kg"] = source["w_per_kg"]
    return result


def _owner(row, viewer):
    return bool(viewer and getattr(viewer, "user_id", None) == str(row["user_id"]))


def _share_wkg(row, viewer):
    return _owner(row, viewer) or row["rider"].get("share_wkg") is True


def _active(row):
    return (row.get("rider", {}).get("account_state") == "active"
            and is_training_eligible(row.get("ride") or {}))


def _epoch(value):
    if isinstance(value, (float, int)) and not isinstance(value, bool):
        return int(value)
    try:
        return int(datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp())
    except (TypeError, ValueError, OverflowError):
        return None


def project_effort(row, viewer):
    metrics = dict(row["metrics"])
    if metrics.get("power_kind") == "estimated":
        metrics.pop("avg_power_w", None)
        metrics.pop("w_per_kg", None)
    if not _owner(row, viewer):
        for field in _OWNER_METRICS:
            metrics.pop(field, None)
    if not _share_wkg(row, viewer):
        metrics.pop("w_per_kg", None)
    return ClimbEffort(
        effort_id=str(row["id"]), climb_id=str(row["climb_id"]), ride_id=str(row["ride_id"]),
        canon_version=row["canon_version"], achieved_at=row["achieved_at"],
        metrics=ClimbEffortMetrics.model_validate(metrics),
    )


async def read_effort(repo, effort_id, viewer):
    try:
        row = await repo.get_effort(effort_id)
        if not row or not await can_read_effort(repo, row, viewer):
            raise HTTPException(404, "Effort not found")
        return project_effort(row, viewer)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(503, "Effort is temporarily unavailable") from exc


async def can_read_effort(repo, row, viewer):
    if not _active(row):
        return False
    decision = await resolve_ride_visibility(row["ride"], viewer, repo=repo, owner_profile=row["rider"])
    return decision.can_view and (decision.is_owner or await repo.public_span(row))


async def pattern_power(repo, ride, patterns, viewer, *, rider=None):
    """One batch effort read; a denied existing effort never falls back."""
    from uuid import UUID

    ids = []
    for pattern in patterns:
        try:
            ids.append(str(UUID(str(pattern.get("id")))))
        except ValueError:
            pass
    rows = {str(row["id"]): row for row in await repo.get_efforts(ids)}
    legacy = [p for p in patterns if str(p.get("id")) not in rows]
    legacy_allowed = False
    if isinstance(rider, dict) and rider.get("account_state") == "active":
        decision = await resolve_ride_visibility(ride, viewer, repo=repo, owner_profile=rider)
        legacy_allowed = decision.can_view
    recorded = await repo.recorded_power_rides([str(ride["id"])]) if legacy and legacy_allowed else set()
    result = {}
    for pattern in patterns:
        key = str(pattern.get("id"))
        row = rows.get(key)
        power = {}
        if row is not None:
            if (str(row["ride_id"]) == str(ride["id"]) and str(row["user_id"]) == str(ride["user_id"])
                    and await can_read_effort(repo, row, viewer)):
                metrics = project_effort(row, viewer).metrics.model_dump(exclude_none=True)
                power = ClimbPatternPower.model_validate(metrics).model_dump(exclude_none=True)
        elif legacy_allowed:
            power = legacy_pattern_power(ride, pattern, recorded_stream=str(ride["id"]) in recorded)
        result[key] = power
    return result


def _entry(row, *, viewer, rank, signature, source, position=None, tie_size=1):
    return RecordBoardEntry(
        rank=rank, position=position, competition_rank=rank, tie_size=tie_size, is_tied=tie_size > 1,
        wallet=row["rider"]["wallet"], best_time_seconds=row["time_s"],
        avg_power_w=row.get("avg_power_w") if row.get("power_kind") == "measured" else None,
        power_kind=row.get("power_kind"),
        estimated_power_w=row.get("estimated_power_w"),
        estimated_power_range_w=row.get("estimated_power_range_w"),
        effort_id=str(row["id"]) if row.get("id") else None, completion_id=row.get("completion_id"),
        ride_id=str(row["ride_id"]) if row.get("id") else None,
        achieved_at=row["achieved_at"], vault_signature=signature, place_source=source,
        w_per_kg=row.get("w_per_kg") if row.get("power_kind") == "measured" and _share_wkg(row, viewer) else None,
        user_id=str(row["user_id"]), username=row["rider"].get("username"),
        display_name=row["rider"].get("display_name"),
    )


async def _public_competitor(repo, row):
    ride, rider = row["ride"], row["rider"]
    return (
        _active(row) and rider.get("is_public") is True and ride.get("visibility") == "public"
        and ride.get("hide_from_leaderboards") is False
        and normalize_moderation_state(ride.get("moderation_state")) not in MODERATION_HIDDEN_STATES
        and normalize_moderation_state(rider.get("moderation_state")) not in MODERATION_HIDDEN_STATES
        and await repo.public_span(row)
    )


def admitted_kom(projection, entries):
    """A header cannot identify a rider removed by the fresh privacy check."""
    if any(e.wallet == projection.kom_holder and e.best_time_seconds == projection.kom_time_s
           for e in entries):
        return projection.kom_holder, projection.kom_time_s
    return None, None


async def enrich_board(repo, projection, *, vault_signature, viewer=None, window_start=None):
    """Keep public chain seats intact; separately label off-chain viewer ranks."""
    try:
        source = "offchain_completions" if window_start else "onchain"
        ids = list(set(projection.effort_ids.values()))
        by_id = {str(r["id"]): r for r in await repo.get_efforts(ids)}
        missing = [key for key in ids if key not in by_id]
        legacy = await repo.board_patterns(missing) if missing else {}
        prepare = getattr(repo, "prepare_public_spans", None)
        if prepare:
            await prepare(list(by_id.values()))
        entries = []
        for seat in projection.entries:
            wallet = str(seat["user"])
            row = by_id.get(projection.effort_ids.get(wallet))
            if row:
                if not _active(row) or row["rider"]["wallet"] != wallet or row["time_s"] != seat["time_s"]:
                    continue
                # Privacy was resolved before the exact pattern id was admitted.
                # Recheck the fresh row so a changed ride preference fails shut.
                if not await _public_competitor(repo, row):
                    continue
                entry = _entry(row, viewer=viewer, rank=int(seat["rank"]), signature=vault_signature,
                               source=source, position=int(seat["position"]), tie_size=int(seat["tie_size"]))
                # Legacy rank remains seat; explicit competition_rank carries ties.
                entry.rank = int(seat["position"])
            else:
                # Old rows awaiting the explicit backfill retain their truthful
                # chain time/date; do not invent power or an effort link.
                recorded = seat.get("recorded_at")
                achieved = datetime.fromtimestamp(int(recorded), timezone.utc).isoformat() if recorded else None
                entry = RecordBoardEntry(
                    position=int(seat["position"]), rank=int(seat["position"]),
                    competition_rank=int(seat["rank"]), tie_size=int(seat["tie_size"]),
                    is_tied=bool(seat["is_tied"]), wallet=wallet,
                    best_time_seconds=seat["time_s"], achieved_at=achieved,
                    vault_signature=vault_signature, place_source=source,
                )
                pattern_id = projection.effort_ids.get(wallet)
                old = legacy.get(pattern_id)
                if old:
                    # The receipt fixes both pattern and ride, not wallet+time.
                    if (str(old["ride_id"]) != projection.ride_ids.get(wallet)
                            or old["rider"]["wallet"] != wallet or old["time_s"] != seat["time_s"]
                            or not await _public_legacy_competitor(repo, old)):
                        continue
                    power = legacy_pattern_power(old["ride"], old["pattern"], recorded_stream=old["recorded_stream"])
                    if not _share_wkg(old, viewer):
                        power.pop("w_per_kg", None)
                    entry = entry.model_copy(update={**power, "user_id": str(old["user_id"]),
                        "username": old["rider"].get("username"), "display_name": old["rider"].get("display_name")})
            entries.append(entry)
        if not getattr(viewer, "user_id", None):
            return entries, None
        seated = next((e for e in entries if e.wallet == viewer.wallet), None)
        async def eligible_own(row):
            return _owner(row, viewer) and await _public_competitor(repo, row)
        own_candidates = await repo.completion_efforts(
            vault_signature, window_start=window_start, wallet=viewer.wallet,
            max_time_s=seated.best_time_seconds if seated else None, first_eligible=eligible_own)
        if prepare:
            await prepare(own_candidates)
        public_own = [row for row in own_candidates if await eligible_own(row)]
        if not public_own:
            return entries, seated
        own_time = min(row["time_s"] for row in public_own)
        candidates = await repo.completion_efforts(vault_signature, window_start=window_start, max_time_s=own_time)
        if prepare:
            await prepare(candidates)
        best = {}
        for row in sorted(candidates, key=lambda r: (r["time_s"], r["achieved_at"], str(r["id"]))):
            wallet = row["rider"]["wallet"]
            if wallet in best or not _active(row):
                continue
            if await _public_competitor(repo, row):
                best[wallet] = row
        own = best.get(viewer.wallet)
        seated = next((e for e in entries if e.wallet == viewer.wallet), None)
        if own is None:
            return entries, seated
        if seated and seated.best_time_seconds <= own["time_s"]:
            return entries, seated
        own_seat = next((seat for seat in projection.chain_entries
                         if seat["user"] == viewer.wallet and seat["time_s"] == own["time_s"]
                         and _epoch(seat.get("recorded_at")) is not None
                         and _epoch(seat.get("recorded_at")) == _epoch(own.get("completion_recorded_at"))), None)
        if own_seat and not window_start:
            pinned = _entry(own, viewer=viewer, rank=int(own_seat["rank"]),
                            signature=vault_signature, source="onchain",
                            position=int(own_seat["position"]), tie_size=int(own_seat["tie_size"]))
            pinned.rank = int(own_seat["position"])
            return entries, pinned
        # Include eligible on-chain competitors once even if legacy reads have
        # not yet been backfilled. Never promote off-chain rows into chain seats.
        times = {wallet: row["time_s"] for wallet, row in best.items()}
        for entry in entries:
            times[entry.wallet] = min(times.get(entry.wallet, entry.best_time_seconds), entry.best_time_seconds)
        rank = 1 + sum(time < own["time_s"] for time in times.values())
        ties = sum(time == own["time_s"] for time in times.values())
        return entries, _entry(own, viewer=viewer, rank=rank, signature=vault_signature,
                               source="offchain_completions", tie_size=ties)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(503, "Leaderboard effort data is temporarily unavailable") from exc


async def _public_legacy_competitor(repo, row):
    ride, rider = row["ride"], row["rider"]
    return (_active(row) and rider.get("is_public") is True and ride.get("visibility") == "public"
            and ride.get("hide_from_leaderboards") is False
            and normalize_moderation_state(ride.get("moderation_state")) not in MODERATION_HIDDEN_STATES
            and normalize_moderation_state(rider.get("moderation_state")) not in MODERATION_HIDDEN_STATES
            and await repo.legacy_public_span(row))


async def rides_board(repo, climb, *, viewer=None, window_start=None):
    """Sporting arithmetic over public rides, never a chain seat or a KOM."""
    try:
        rows = await repo.rides_efforts(str(climb["id"]))
        await repo.prepare_public_spans([r for r in rows if "pattern" not in r])
        best = {}
        for row in sorted(rows, key=lambda r: (r["time_s"], str(r.get("achieved_at") or ""), str(r["id"]))):
            rider_id = str(row["user_id"])
            time = row["time_s"]
            if rider_id in best or isinstance(time, bool) or not isinstance(time, int) or time <= 0:
                continue
            achieved = _epoch(row.get("achieved_at"))
            if window_start and (achieved is None or achieved < _epoch(window_start)):
                continue
            eligible = (_public_legacy_competitor if "pattern" in row else _public_competitor)
            if not await eligible(repo, row):
                continue
            decision = await resolve_ride_visibility(row["ride"], viewer, repo=repo, owner_profile=row["rider"])
            if decision.can_view:
                best[rider_id] = row
        times = [row["time_s"] for row in best.values()]
        entries, own = [], None
        for position, row in enumerate(best.values(), 1):
            if position > 10 and not _owner(row, viewer):
                continue
            if "pattern" in row:
                row = {**row, **legacy_pattern_power(row["ride"], row["pattern"])}
            entry = _entry(row, viewer=viewer, rank=1 + sum(t < row["time_s"] for t in times),
                           position=position, tie_size=times.count(row["time_s"]),
                           signature=None, source="rides")
            if "pattern" in row:
                entry.effort_id = None  # Only the ride analysis exists before the metrics backfill.
            if position <= 10:
                entries.append(entry)
            if _owner(row, viewer):
                own = entry
        return RecordBoard(
            truth_source=TruthSource.projected, source="rides", climb_id=str(climb["id"]),
            climb_name=climb.get("display_name"), entries=entries, viewer_entry=own,
            earlier_version_id=await repo.first_version_id(climb),
        ).model_dump(mode="json")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(503, "Leaderboard effort data is temporarily unavailable") from exc
