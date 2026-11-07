"""Small, short-lived owner-scoped cache for interactive span reads."""

import asyncio
from collections import OrderedDict
import time

_entries = OrderedDict()
_pending = {}


async def activity_for_span(ride, user_id):
    # The route authorizes every request before entering this function.
    key = (str(user_id), str(ride["id"]), ride["raw_file_path"])
    entry = _entries.get(key)
    if entry and entry[0] > time.monotonic():
        _entries.move_to_end(key)
        return entry[1]
    if key in _pending:
        return await asyncio.shield(_pending[key])

    async def load():
        from .file_storage import FileStorageService
        from .workout_parse_adapter import parse_ride_file_bytes_rust

        raw = await FileStorageService().download_ride_file(ride["raw_file_path"])
        parsed = await asyncio.to_thread(
            parse_ride_file_bytes_rust, raw, ride.get("file_type") or "auto"
        )
        activity = parsed._native_activity
        if len(activity.time_ms) <= 100_000:
            _entries[key] = (time.monotonic() + 60, activity)
            while len(_entries) > 4:
                _entries.popitem(last=False)
        return activity

    task = _pending[key] = asyncio.create_task(load())
    try:
        return await task
    finally:
        _pending.pop(key, None)
