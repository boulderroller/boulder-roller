"""Idempotent, bounded training-only replay of retained original files."""

import asyncio
import logging
from postgrest.exceptions import APIError

from .training_metrics import ENGINE_VERSION, TrainingMetricsService
from .training_eligibility import is_training_eligible


def error_class(exc):
    # PyO3 panics are BaseException; cancellation and process exits still escape.
    if not isinstance(exc, Exception) and type(exc).__name__ != "PanicException":
        raise exc
    if (
        isinstance(exc, APIError)
        and exc.code == "P0001"
        and exc.message == "training date conflict"
    ):
        return "training_date_conflict"
    return type(exc).__name__


async def record_result(repo, ride, failure=None):
    try:
        await repo.finish_training_replay(
            ride["id"], ride["user_id"], failure, scoring_inputs=ride
        )
    except Exception as exc:
        # Claim's durable lease expires independently of any ride-row trigger.
        logging.getLogger(__name__).warning(
            "Training replay state unavailable: %s %s", ride["id"], type(exc).__name__
        )


async def backfill_training(
    repo, rides, parse, *, apply=False, force=False, force_terminal=False
):
    counts = dict(eligible=0, scored=0, skipped=0, unavailable=0, failed=0, errors=[])
    ordered = sorted(
        rides,
        key=lambda r: (
            r.get("started_at") is None,
            str(r.get("started_at") or ""),
            str(r["id"]),
        ),
    )
    service = TrainingMetricsService(repo)
    for ride in ordered:
        if not is_training_eligible(ride):
            counts["skipped"] += 1
            continue
        state = ride.get("training_replay_state") or {}
        terminal_version = state.get("terminal_engine_version")
        if terminal_version is not None and terminal_version >= ENGINE_VERSION and not force_terminal:
            counts["skipped"] += 1
            continue
        version = (ride.get("training_metrics") or {}).get("engine_version") or 0
        if version > ENGINE_VERSION or (
            not force and not (force_terminal and terminal_version is not None)
            and not ride.get("training_error") and not state.get("error_class")
            and version == ENGINE_VERSION
        ):
            counts["skipped"] += 1
            continue
        if not ride.get("raw_file_path"):
            counts["unavailable"] += 1
            counts["errors"].append(
                {"ride_id": str(ride["id"]), "error_class": "missing_original"}
            )
            if apply:
                await record_result(repo, ride, "missing_original")
            continue
        counts["eligible"] += 1
        if not apply:  # no file read and no write in dry run
            continue
        try:
            parsed = await parse(ride)
            await service.score(
                ride_id=str(ride["id"]),
                user_id=str(ride["user_id"]),
                parsed_ride=parsed,
            )
            counts["scored"] += 1
            await record_result(repo, ride)
        except BaseException as exc:
            # No file contents, physiology, or provider values in job output.
            counts["failed"] += 1
            failure = error_class(exc)
            counts["errors"].append(
                {"ride_id": str(ride["id"]), "error_class": failure}
            )
            await record_result(repo, ride, failure)
    return counts


async def replay_training_batch(repo, *, limit=10, parse=None):
    """A leased, bounded batch. Payment processing never calls this worker."""
    rides = await repo.claim_training_replay(limit)
    if parse is None:
        from .file_storage import FileStorageService
        from .workout_parse_adapter import parse_ride_file_bytes_rust

        storage = FileStorageService(repo.client)

        async def parse(ride):
            raw = await storage.download_ride_file(ride["raw_file_path"])
            return await asyncio.to_thread(
                parse_ride_file_bytes_rust, raw, ride.get("file_type") or "auto"
            )

    return await backfill_training(repo, rides, parse, apply=True, force=True)
