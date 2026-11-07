"""Private read storage. Every caller must project an explicit viewer."""

import asyncio
from datetime import datetime, timedelta
from uuid import UUID

from .base import BaseRepository
from ..services.canon_traversal_evidence import CanonTraversalEvidence, CanonTraversalEvidenceError
from ..services.climb_effort_metrics import canonical_span
from ..services.public_record_board_privacy import route_span_is_public
from ..services.ride_privacy import RidePrivacyPolicy, PrivacySettingsUnavailable, project_route_points
from ..utils.polyline import decode_gps_track
from ..utils.postgrest_paging import PageCursor, order_by, window

_RIDER_COLUMNS = "id,wallet,share_wkg,is_public,account_state,moderation_state,username,display_name"
_RIDE_COLUMNS = (
    "id,user_id,visibility,map_visibility,map_hide_start_m,map_hide_end_m,"
    "hide_from_leaderboards,moderation_state,processing_status,ride_hash_hex,ride_parser_version"
)

_COLUMNS = (
    "id,ride_id,user_id,climb_id,canon_version,start_offset_s,end_offset_s,"
    "achieved_at,time_s,avg_power_w,estimated_power_w,estimated_power_range_w,power_kind,w_per_kg,metrics,"
    f"ride:rides!inner({_RIDE_COLUMNS}),rider:users!user_id!inner({_RIDER_COLUMNS})"
)


class ClimbEffortRepository(BaseRepository):
    async def rides_efforts(self, climb_id):
        """Exact registry revision, including canonical times awaiting metrics.

        Page both populations; an existing effort never falls back to a legacy
        pattern after a failed privacy check. The caller projects every row.
        """
        efforts = {}
        cursor = PageCursor(500)  # range() is end-exclusive here; see postgrest_paging.
        while True:
            page = await self._rows(self.client.from_("climb_efforts").select(_COLUMNS)
                .eq("climb_id", climb_id).order("id").range(cursor.offset, cursor.offset + 499))
            efforts.update((str(row["id"]), row) for row in page)
            if not cursor.advance(page):
                break
        result = list(efforts.values())
        cursor = PageCursor(500)
        while True:
            page = await self._rows(self.client.from_("patterns_climb")
                .select("id,activity_id,time_s,start_offset_s,end_offset_s,detector_version,match_trace,avg_power_w,w_per_kg")
                .eq("detector_version", "canon_traversal_v1")
                .eq("match_trace->>registry_id", climb_id)
                .order("id").range(cursor.offset, cursor.offset + 499))
            missing = [p for p in page if str(p["id"]) not in efforts]
            ride_ids = set()
            for pattern in missing:
                try:
                    ride_ids.add(str(UUID(str(pattern.get("activity_id")))))
                except ValueError:
                    continue  # Deletion detaches retained patterns from the UUID ride table.
            ride_ids = sorted(ride_ids)
            rides = {}
            for start in range(0, len(ride_ids), 100):
                rows = await self._rows(self.client.from_("rides")
                    .select(f"{_RIDE_COLUMNS},started_at,gps_track,training_metrics,metrics_version,power_sample_count,"
                            f"rider:users!user_id!inner({_RIDER_COLUMNS})")
                    .in_("id", ride_ids[start:start + 100]))
                rides.update((str(r["id"]), r) for r in rows)
            for pattern in missing:
                ride = rides.get(str(pattern.get("activity_id")))
                if not ride:
                    continue
                try:
                    start, end = canonical_span(pattern)
                except (ValueError, TypeError, KeyError):
                    continue
                achieved_at = None
                if ride.get("started_at"):
                    achieved_at = (datetime.fromisoformat(ride["started_at"].replace("Z", "+00:00"))
                                   + timedelta(seconds=end)).isoformat()
                result.append({
                    "id": pattern["id"], "ride_id": ride["id"], "user_id": ride["user_id"],
                    "climb_id": climb_id, "time_s": pattern["time_s"], "achieved_at": achieved_at,
                    "ride": ride, "rider": ride["rider"], "pattern": pattern,
                })
            if not cursor.advance(page):
                break
        return result

    async def first_version_id(self, climb):
        if not climb.get("canon_id") or (climb.get("version") or 1) <= 1:
            return None
        rows = await self._rows(self.client.from_("canon_climbs").select("id")
            .eq("canon_id", climb["canon_id"]).eq("version", 1)
            .in_("status", ["ratified", "retired"]).limit(1))
        return str(rows[0]["id"]) if rows else None

    async def _rows(self, query):
        response = await self._run(lambda: query.execute())
        if not isinstance(response.data, list):
            raise RuntimeError("effort storage unavailable")
        return response.data

    async def get_effort(self, effort_id):
        rows = await self.get_efforts([effort_id])
        return rows[0] if rows else None

    async def get_efforts(self, effort_ids):
        rows = []
        for start in range(0, len(effort_ids), 100):
            rows.extend(await self._rows(self.client.from_("climb_efforts")
                        .select(_COLUMNS).in_("id", effort_ids[start:start + 100])))
        return rows

    async def recorded_power_rides(self, ride_ids):
        """Only stream metadata is needed; never load raw sensor values here."""
        result = set()
        for start in range(0, len(ride_ids), 100):
            rows = await self._rows(self.client.from_("activity_streams")
                .select("ride_id,sample_count").eq("stream_type", "power")
                .in_("ride_id", ride_ids[start:start + 100]))
            result.update(str(row["ride_id"]) for row in rows
                          if isinstance(row.get("sample_count"), int) and row["sample_count"] > 0)
        return result

    async def board_patterns(self, pattern_ids):
        """Only exact receipt-bound ids enter this fallback; no guessed joins."""
        result = {}
        for start in range(0, len(pattern_ids), 100):
            patterns = await self._rows(self.client.from_("patterns_climb")
                .select("id,activity_id,time_s,start_offset_s,end_offset_s,detector_version,avg_power_w,w_per_kg")
                .in_("id", pattern_ids[start:start + 100]))
            ride_ids = sorted({str(p["activity_id"]) for p in patterns})
            if not ride_ids:
                continue
            rides = {str(r["id"]): r for r in await self._rows(self.client.from_("rides")
                .select(f"{_RIDE_COLUMNS},gps_track,training_metrics,metrics_version,power_sample_count,"
                        f"rider:users!user_id!inner({_RIDER_COLUMNS})").in_("id", ride_ids))}
            recorded = await self.recorded_power_rides(ride_ids)
            for pattern in patterns:
                ride = rides.get(str(pattern["activity_id"]))
                if not ride:
                    continue
                result[str(pattern["id"])] = {
                    "ride_id": ride["id"], "user_id": ride["user_id"], "ride": ride,
                    "rider": ride["rider"], "time_s": pattern["time_s"], "pattern": pattern,
                    "recorded_stream": str(ride["id"]) in recorded,
                }
        return result

    async def legacy_public_span(self, row):
        """Retain the legacy board's GPS/offset policy, not D11 reconstruction."""
        ride, pattern = row["ride"], row["pattern"]
        try:
            policy = RidePrivacyPolicy.from_values(
                visibility=ride.get("visibility"), map_visibility=ride.get("map_visibility"),
                map_hide_start_m=ride.get("map_hide_start_m"), map_hide_end_m=ride.get("map_hide_end_m"))
            points = decode_gps_track(ride.get("gps_track"))
            zones = []
            cursor = PageCursor(500)
            while True:
                page = await self._rows(self.client.from_("privacy_zones")
                    .select("latitude,longitude,radius_m").eq("user_id", row["user_id"])
                    .order("id").range(cursor.offset, cursor.offset + 499))
                zones.extend(page)
                if not cursor.advance(page):
                    break
            return route_span_is_public(project_route_points(points, policy, privacy_zones=zones),
                start_offset_s=pattern.get("start_offset_s"), end_offset_s=pattern.get("end_offset_s"))
        except (PrivacySettingsUnavailable, ValueError, TypeError, KeyError, IndexError):
            return False

    async def get_follow(self, viewer_id, owner_id):
        return bool(await self._rows(self.client.from_("follows").select("follower_id")
                                    .eq("follower_id", viewer_id).eq("following_id", owner_id).limit(1)))

    async def public_span(self, effort):
        ride = effort["ride"]
        try:
            await self.prepare_public_spans([effort])
            policy = RidePrivacyPolicy.from_values(
                visibility=ride.get("visibility"), map_visibility=ride.get("map_visibility"),
                map_hide_start_m=ride.get("map_hide_start_m"), map_hide_end_m=ride.get("map_hide_end_m"),
            )
            zones = self._zones.get(str(effort["user_id"]), [])
            key = (str(effort["ride_id"]), ride.get("ride_hash_hex"), ride.get("ride_parser_version"))
            points = self._points.get(key)
            if not points:
                return False
            def check_span():
                return route_span_is_public(
                    project_route_points(points, policy, privacy_zones=zones),
                    start_offset_s=effort["start_offset_s"], end_offset_s=effort["end_offset_s"],
                    ride_relative=True,
                )
            return await asyncio.to_thread(check_span)
        except (CanonTraversalEvidenceError, PrivacySettingsUnavailable, ValueError, TypeError, KeyError, IndexError):
            return False

    async def prepare_public_spans(self, efforts):
        """Batch and reuse evidence per request, including repeated ride passes."""
        if not hasattr(self, "_points"):
            self._points, self._zones = {}, {}
        missing = { (str(e["ride_id"]), e["ride"].get("ride_hash_hex"), e["ride"].get("ride_parser_version"))
                    for e in efforts } - self._points.keys()
        if missing:
            rows = []
            ride_ids = sorted({k[0] for k in missing})
            for batch_start in range(0, len(ride_ids), 100):
                cursor = PageCursor(500)
                while True:
                    page = await self._rows(order_by(self.client.from_("canon_traversal_evidence")
                        .select("ride_id,ride_hash_hex,ride_parser_version,evidence_version,sample_count,sample_digest,samples")
                        .in_("ride_id", ride_ids[batch_start:batch_start + 100])
                        .eq("evidence_version", "canon_traversal_evidence_v1"),
                        "ride_id", "ride_hash_hex", "ride_parser_version")
                        .range(cursor.offset, cursor.offset + 499))
                    rows.extend(page)
                    if not cursor.advance(page):
                        break
            self._points.update((key, None) for key in missing)
            for row in rows:
                key = (str(row["ride_id"]), row["ride_hash_hex"], row["ride_parser_version"])
                if key not in missing:
                    continue
                self._points[key] = await asyncio.to_thread(self._decode_points, row)
        owners = sorted({str(e["user_id"]) for e in efforts} - self._zones.keys())
        if owners:
            self._zones.update((owner, []) for owner in owners)
            for batch_start in range(0, len(owners), 100):
                cursor = PageCursor(500)
                while True:
                    rows = await self._rows(order_by(self.client.from_("privacy_zones")
                        .select("user_id,latitude,longitude,radius_m")
                        .in_("user_id", owners[batch_start:batch_start + 100]),
                        "user_id", "latitude", "longitude", "radius_m", "id")
                        .range(cursor.offset, cursor.offset + 499))
                    for row in rows:
                        self._zones[str(row["user_id"])].append(row)
                    if not cursor.advance(rows):
                        break

    @staticmethod
    def _decode_points(row):
        try:
            evidence = CanonTraversalEvidence.from_row(row)
            return [{"latitude": s["lat"], "longitude": s["lon"], "timestamp": s["t"]}
                    for s in evidence.samples]
        except CanonTraversalEvidenceError:
            return None

    async def completion_efforts(self, vault_signature, *, window_start=None, wallet=None,
                                 max_time_s=None, first_eligible=None):
        """Validated off-chain completions, tied to an authoritative traversal.

        Page both reads: PostgREST's default row cap must not truncate a rank.
        No chain confirmation or on-chain seat is inferred from these rows.
        Metric availability must not affect a competitor's place.
        """
        vaults = await self._rows(self.client.from_("indexed_vaults")
                                 .select("canon_climb_id").eq("signature_hex", vault_signature).limit(1))
        if not vaults or not vaults[0].get("canon_climb_id"):
            return []
        climb_id = vaults[0]["canon_climb_id"]
        completions = []
        page_size = 1 if first_eligible else 500
        # The viewer scan reads one completion per step until one is public.
        cursor = PageCursor(page_size, max_pages=100_000 if first_eligible else 1000)
        while True:
            query = (self.client.from_("vault_completions")
                     .select("id,activity_id,wallet,time_seconds,completed_at,completion_receipt_pda")
                     .eq("vault_signature", vault_signature).eq("validated", True)
                     .eq("chain_confirmation_status", "confirmed"))
            if wallet:
                query = query.eq("wallet", wallet)
            if max_time_s is not None:
                query = query.lte("time_seconds", max_time_s)
            if window_start:
                query = query.gte("completed_at", window_start)
            # One completion per scan step needs an exact window, not range().
            page = await self._rows(window(order_by(query, "time_seconds", "id"),
                                           cursor.offset, page_size))
            if first_eligible:
                candidates = await self._bind_completions(climb_id, page)
                await self.prepare_public_spans(candidates)
                for row in sorted(candidates, key=lambda r: (r["time_s"], r["achieved_at"], str(r["id"]))):
                    if await first_eligible(row):
                        return [row]
            else:
                completions.extend(page)
            if not cursor.advance(page):
                break
        return await self._bind_completions(climb_id, completions)

    async def _bind_completions(self, climb_id, completions):
        if not completions:
            return []
        # Equal whole-second passes need the receipt's frozen pattern identity;
        # a ride/time join alone is not an effort identity.
        by_key = {}
        for completion in sorted(completions, key=lambda c: (str(c.get("completed_at") or ""), str(c["id"]))):
            try:
                ride_id = str(UUID(str(completion.get("activity_id"))))
            except ValueError:
                continue  # deleted/anonymized and legacy non-UUID activities
            key = (ride_id, completion.get("wallet"),
                   completion.get("time_seconds"))
            by_key.setdefault(key, completion)
        rows = []
        ride_ids = sorted({key[0] for key in by_key})
        for batch_start in range(0, len(ride_ids), 100):
            batch = ride_ids[batch_start:batch_start + 100]
            metrics = {}
            cursor = PageCursor(500)
            while True:
                page = await self._rows(self.client.from_("climb_efforts")
                                       .select(_COLUMNS).eq("climb_id", climb_id)
                                       .in_("ride_id", batch)
                                       .order("id").range(cursor.offset, cursor.offset + 499))
                metrics.update((str(e["id"]), e) for e in page)
                if not cursor.advance(page):
                    break
            rides = {str(r["id"]): r for r in await self._rows(self.client.from_("rides")
                .select(f"{_RIDE_COLUMNS},rider:users!user_id!inner({_RIDER_COLUMNS})").in_("id", batch))}
            receipts = sorted({str(c["completion_receipt_pda"]) for key, c in by_key.items()
                               if key[0] in batch and c.get("completion_receipt_pda")})
            receipt_patterns = {}
            if receipts:
                for table in ("ride_economic_completion_steps", "reward_threshold_release_steps"):
                    steps = await self._rows(self.client.from_(table)
                        .select("expected_receipt_pda,pattern_id,completion_time_s,completed_at")
                        .in_("expected_receipt_pda", receipts))
                    for step in steps:
                        receipt_patterns.setdefault(step["expected_receipt_pda"], set()).add(str(step["pattern_id"]))
            candidates = {}
            cursor = PageCursor(500)
            while True:
                page = await self._rows(self.client.from_("patterns_climb")
                    .select("id,activity_id,time_s,detector_version,match_trace")
                    .in_("activity_id", batch).eq("detector_version", "canon_traversal_v1")
                    .order("id").range(cursor.offset, cursor.offset + 499))
                for pattern in page:
                    ride = rides.get(str(pattern["activity_id"]))
                    trace = pattern.get("match_trace") or {}
                    if not ride or str(trace.get("registry_id")) != str(climb_id):
                        continue
                    key = (str(ride["id"]), ride["rider"]["wallet"], pattern["time_s"])
                    if key not in by_key:
                        continue
                    try:
                        start, end = canonical_span(pattern)
                    except ValueError:
                        continue
                    candidates.setdefault(key, []).append((pattern, ride, start, end))
                if not cursor.advance(page):
                    break
            for key, matches in candidates.items():
                completion = by_key[key]
                frozen_ids = receipt_patterns.get(completion.get("completion_receipt_pda"))
                if frozen_ids:
                    matches = [match for match in matches if str(match[0]["id"]) in frozen_ids]
                # A legacy completion without receipt identity is usable only
                # when the canonical traversal is demonstrably unique.
                if len(matches) != 1:
                    continue
                pattern, ride, start, end = matches[0]
                row = metrics.get(str(pattern["id"])) or {
                    "id": None, "ride_id": ride["id"], "user_id": ride["user_id"],
                    "climb_id": climb_id, "canon_version": pattern["match_trace"]["canon_version"],
                    "time_s": pattern["time_s"], "start_offset_s": start, "end_offset_s": end,
                    "achieved_at": completion["completed_at"],
                }
                rows.append({**row, "ride": ride, "rider": ride["rider"],
                             "completion_id": str(completion["id"]),
                             "completion_recorded_at": completion["completed_at"]})
        return rows
