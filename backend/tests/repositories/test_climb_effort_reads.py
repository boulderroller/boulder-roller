from copy import deepcopy
from types import SimpleNamespace
from uuid import UUID

import pytest

from app.repositories.climb_effort import ClimbEffortRepository
from app.utils.polyline import encode_gps_track


class Query:
    def __init__(self, client, table):
        self.client, self.table = client, table
        self.rows = deepcopy(client.tables.get(table, []))

    def select(self, columns):
        self.client.selects.append((self.table, columns))
        return self

    def eq(self, key, value):
        self.rows = [r for r in self.rows if r.get(key) == value]
        return self

    def in_(self, key, values):
        if self.table in {"climb_efforts", "patterns_climb"} and key in {"ride_id", "activity_id"}:
            for value in values:
                UUID(value)  # PostgreSQL UUID filters reject anonymized activity ids.
        self.rows = [r for r in self.rows if r.get(key) in values]
        return self

    def lte(self, key, value):
        self.rows = [r for r in self.rows if r.get(key) is not None and r[key] <= value]
        return self

    def limit(self, limit):
        self.rows = self.rows[:limit]
        return self

    def order(self, key):
        # One order parameter carries every sort key (postgrest_paging.order_by).
        columns = key.split(",")
        self.rows.sort(key=lambda r: tuple(r[column] for column in columns))
        return self

    def gte(self, key, value):
        self.rows = [r for r in self.rows if r[key] >= value]
        return self

    def offset(self, offset):
        self.rows = self.rows[offset:]
        return self

    def range(self, start, end):
        # The pinned postgrest-py sends Range: start-(end - 1): end-exclusive.
        self.rows = self.rows[start:end]
        return self

    def execute(self):
        return SimpleNamespace(data=self.rows)


class Client:
    def __init__(self, tables):
        self.tables, self.selects = tables, []

    def from_(self, table):
        return Query(self, table)


def evidence_for(row, times, *, ride_id="33333333-3333-4333-8333-333333333333"):
    from app.services.canon_traversal_evidence import CanonTraversalEvidence
    from backend.tests.services.test_canon_traversal_evidence import _TileService
    row["ride_id"] = row["ride"]["id"] = ride_id
    row["ride"].update(ride_hash_hex="ab" * 32, ride_parser_version=5)
    records = [{"timestamp": t, "lat": 40 + i * .003, "lon": -75}
               for i, t in enumerate(times)]
    row["ride"]["gps_track"] = encode_gps_track([
        {"timestamp": r["timestamp"], "latitude": r["lat"], "longitude": r["lon"]} for r in records
    ])
    return CanonTraversalEvidence.build(
        ride_id=UUID(row["ride_id"]), ride_hash_hex="ab" * 32, ride_parser_version=5,
        parsed_ride=SimpleNamespace(started_at=None, records=records), tile_service=_TileService(),
    ).to_row()


@pytest.mark.asyncio
async def test_fractional_canonical_span_remains_readable_and_hidden_segment_does_not():
    from backend.tests.routes.test_climb_effort_api import effort

    row = effort(start_offset_s=10.5, end_offset_s=70.5)
    evidence = evidence_for(row, range(0, 100, 10))
    client = Client({"privacy_zones": [], "canon_traversal_evidence": [evidence]})
    repo = ClimbEffortRepository(client)
    assert await repo.public_span(row)
    row["ride"]["map_visibility"] = "hide_entire"
    assert not await repo.public_span(row)


@pytest.mark.asyncio
async def test_delayed_gps_keeps_ride_origin_and_cannot_reveal_hidden_start():
    from backend.tests.routes.test_climb_effort_api import effort
    row = effort(start_offset_s=25, end_offset_s=55)
    evidence = evidence_for(row, [20, 40, 60, 80, 100])
    row["ride"].update(map_visibility="hide_start_end", map_hide_start_m=200, map_hide_end_m=200)
    repo = ClimbEffortRepository(Client({"privacy_zones": [], "canon_traversal_evidence": [evidence]}))
    assert not await repo.public_span(row)
    row.update(start_offset_s=45.5, end_offset_s=75.5)
    assert await repo.public_span(row)


@pytest.mark.asyncio
async def test_completion_read_is_paginated_bound_to_canon_and_validated():
    from backend.tests.routes.test_climb_effort_api import effort, CLIMB_ID

    completions, efforts, patterns, rides = [], [], [], []
    for i in range(501):
        row = effort(id=f"effort-{i:04}", ride_id=str(UUID(int=i + 1)))
        efforts.append(row)
        row["ride"].update(id=row["ride_id"], rider=row["rider"])
        rides.append(row["ride"])
        patterns.append(dict(id=row["id"], activity_id=row["ride_id"], time_s=row["time_s"],
                             detector_version="canon_traversal_v1", match_trace={
                                 "registry_id": row["climb_id"], "canon_version": 1,
                                 "best_representative": True,
                                 "gate_crossings": {"start_time_s_raw": 10, "finish_time_s_raw": 110}}))
        completions.append(dict(id=f"completion-{i:04}", activity_id=row["ride_id"],
                                wallet=row["rider"]["wallet"], time_seconds=row["time_s"],
                                completed_at="2026-10-01T00:00:00Z", vault_signature="sig", validated=True, chain_confirmation_status="confirmed"))
    # A coincidental same-time traversal of another hill must not be joined.
    efforts.append(effort(id="wrong-hill", ride_id="ride-0000", climb_id="different"))
    completions.append({**completions[0], "id": "invalid", "activity_id": "invalid", "validated": False})
    completions.append({**completions[0], "id": "deleted",
                        "activity_id": f"anonymous:{UUID(int=9000)}", "validated": True})
    client = Client({"indexed_vaults": [{"signature_hex": "sig", "canon_climb_id": CLIMB_ID}],
                     "vault_completions": completions, "climb_efforts": efforts,
                     "patterns_climb": patterns, "rides": rides})
    rows = await ClimbEffortRepository(client).completion_efforts("sig")
    assert len(rows) == 501 and all(row["climb_id"] == CLIMB_ID for row in rows)
    assert all(row["completion_id"].startswith("completion-") for row in rows)
    assert all("*" not in columns and "weight" not in columns for _, columns in client.selects)
    # Once the first public own effort is found, later history must not be
    # hydrated or scanned. The public predicate can reject an earlier pass.
    from unittest.mock import AsyncMock
    client.selects.clear()
    accept = AsyncMock(side_effect=lambda row: row['ride_id'] == str(UUID(int=2)))
    repo = ClimbEffortRepository(client)
    repo.prepare_public_spans = AsyncMock()
    best = await repo.completion_efforts('sig', wallet=efforts[0]['rider']['wallet'], first_eligible=accept)
    assert len(best) == 1 and best[0]['ride_id'] == str(UUID(int=2))
    assert sum(table == 'vault_completions' for table, _ in client.selects) == 2
    assert [len(call.args[0]) for call in repo.prepare_public_spans.call_args_list] == [1, 1]


@pytest.mark.asyncio
async def test_unbackfilled_canonical_competitor_still_counts_in_viewer_place():
    from app.services.climb_effort_reads import enrich_board
    from app.services.public_record_board_privacy import PublicRecordBoardProjection
    from backend.tests.routes.test_climb_effort_api import effort, OWNER, CLIMB_ID
    own = effort(ride_id=str(UUID(int=1)))
    other = effort(ride_id=str(UUID(int=2)), user_id="competitor", time_s=90)
    other["rider"].update(id="competitor", wallet="wallet-competitor")
    other["ride"].update(id=other["ride_id"], user_id="competitor", rider=other["rider"])
    completions = [
        dict(id=f"c{i}", activity_id=r["ride_id"], wallet=r["rider"]["wallet"],
             time_seconds=r["time_s"], completed_at=r["achieved_at"], validated=True, chain_confirmation_status="confirmed", vault_signature="sig")
        for i, r in enumerate([own, other])
    ]
    pattern = dict(id="unbackfilled", activity_id=other["ride_id"], time_s=90,
                   detector_version="canon_traversal_v1", match_trace={
                       "registry_id": CLIMB_ID, "canon_version": 1, "best_representative": True,
                       "gate_crossings": {"start_time_s_raw": 10, "finish_time_s_raw": 100}})
    repo = ClimbEffortRepository(Client({
        "indexed_vaults": [{"signature_hex": "sig", "canon_climb_id": CLIMB_ID}],
        "vault_completions": completions, "climb_efforts": [own],
        "patterns_climb": [pattern, {**pattern, "id": own["id"], "activity_id": own["ride_id"],
                                   "time_s": 100}],
        "rides": [other["ride"], {**own["ride"], "id": own["ride_id"], "rider": own["rider"]}],
    }))
    from unittest.mock import AsyncMock
    repo.public_span = AsyncMock(return_value=True)
    rows, pinned = await enrich_board(
        repo, PublicRecordBoardProjection(entries=[], kom_holder=None, kom_time_s=None),
        vault_signature="sig", viewer=OWNER,
    )
    assert rows == [] and pinned.rank == 2
    assert pinned.place_source == "offchain_completions"


@pytest.mark.asyncio
async def test_viewer_scan_skips_faster_private_ride_before_selecting_public_best():
    from unittest.mock import AsyncMock
    from app.services.climb_effort_reads import enrich_board
    from app.services.public_record_board_privacy import PublicRecordBoardProjection
    from backend.tests.routes.test_climb_effort_api import effort, OWNER, CLIMB_ID

    private = effort(id='private', ride_id=str(UUID(int=1)), time_s=80)
    private['ride']['visibility'] = 'private'
    public = effort(id='public', ride_id=str(UUID(int=2)), time_s=100)
    rows = [private, public]
    rides, completions, patterns = [], [], []
    for i, row in enumerate(rows):
        rides.append({**row['ride'], 'id': row['ride_id'], 'rider': row['rider']})
        completions.append(dict(id=f'c{i}', activity_id=row['ride_id'], wallet=OWNER.wallet,
            time_seconds=row['time_s'], completed_at=row['achieved_at'], validated=True,
            chain_confirmation_status='confirmed', vault_signature='sig'))
        patterns.append(dict(id=row['id'], activity_id=row['ride_id'], time_s=row['time_s'],
            detector_version='canon_traversal_v1', match_trace={
                'registry_id': CLIMB_ID, 'canon_version': 1, 'best_representative': True,
                'gate_crossings': {'start_time_s_raw': 10, 'finish_time_s_raw': 10 + row['time_s']}}))
    repo = ClimbEffortRepository(Client({
        'indexed_vaults': [{'signature_hex': 'sig', 'canon_climb_id': CLIMB_ID}],
        'vault_completions': completions, 'climb_efforts': rows, 'patterns_climb': patterns, 'rides': rides,
    }))
    repo.public_span = AsyncMock(return_value=True)
    repo.prepare_public_spans = AsyncMock()
    _, pinned = await enrich_board(repo,
        PublicRecordBoardProjection(entries=[], kom_holder=None, kom_time_s=None),
        vault_signature='sig', viewer=OWNER)
    assert pinned.effort_id == 'public' and pinned.best_time_seconds == 100 and pinned.rank == 1


@pytest.mark.asyncio
async def test_equal_time_passes_bind_only_the_frozen_completion_pattern():
    from backend.tests.routes.test_climb_effort_api import effort, CLIMB_ID
    early = effort(ride_id=str(UUID(int=1)))
    later = effort(id="later", ride_id=early["ride_id"], start_offset_s=500, end_offset_s=600)
    ride = {**early["ride"], "id": early["ride_id"], "rider": early["rider"]}
    patterns = [
        dict(id=r["id"], activity_id=r["ride_id"], time_s=100, detector_version="canon_traversal_v1",
             match_trace={"registry_id": CLIMB_ID, "canon_version": 1, "best_representative": i == 0,
                          "gate_crossings": {"start_time_s_raw": r["start_offset_s"],
                                             "finish_time_s_raw": r["end_offset_s"]}})
        for i, r in enumerate([early, later])
    ]
    client = Client({
        "indexed_vaults": [{"signature_hex": "sig", "canon_climb_id": CLIMB_ID}],
        "vault_completions": [dict(id="completion", activity_id=early["ride_id"],
            wallet=early["rider"]["wallet"], time_seconds=100, completed_at=early["achieved_at"],
            vault_signature="sig", validated=True, chain_confirmation_status="confirmed")],
        "climb_efforts": [early, later], "patterns_climb": patterns, "rides": [ride],
    })
    assert await ClimbEffortRepository(client).completion_efforts("sig") == []
    # A trim can make the actual selected pass differ from best_representative.
    client.tables["vault_completions"][0]["completion_receipt_pda"] = "receipt"
    client.tables["ride_economic_completion_steps"] = [
        dict(expected_receipt_pda="receipt", pattern_id="later", completion_time_s=100,
             completed_at=early["achieved_at"])]
    rows = await ClimbEffortRepository(client).completion_efforts("sig")
    assert len(rows) == 1 and rows[0]["id"] == "later"
    # Never choose a publicly visible substitute if the frozen pass is hidden.
    from app.services.climb_effort_reads import enrich_board
    from app.services.public_record_board_privacy import PublicRecordBoardProjection
    from backend.tests.routes.test_climb_effort_api import OTHER
    from unittest.mock import AsyncMock
    repo = ClimbEffortRepository(client)
    repo.public_span = AsyncMock(side_effect=lambda r: r["start_offset_s"] < 500)
    entries, pinned = await enrich_board(
        repo, PublicRecordBoardProjection(entries=[], kom_holder=None, kom_time_s=None),
        vault_signature="sig", viewer=OTHER)
    assert entries == [] and pinned is None


def test_user_embeds_name_the_user_id_foreign_key():
    import inspect
    import re
    from app.repositories import climb_effort
    selects = climb_effort._COLUMNS + inspect.getsource(climb_effort.ClimbEffortRepository)
    embeds = re.findall(r'\busers((?:![^\(]+)?)\(', selects)
    assert embeds and all('!user_id!' in embed or '!rides_user_id_fkey!' in embed for embed in embeds)


@pytest.mark.asyncio
async def test_evidence_decode_and_digest_do_not_run_on_the_event_loop(monkeypatch):
    import threading
    from app.services.canon_traversal_evidence import CanonTraversalEvidence
    from backend.tests.routes.test_climb_effort_api import effort
    row = effort(start_offset_s=10, end_offset_s=20)
    evidence = evidence_for(row, range(0, 100, 10))
    loop_thread = threading.get_ident()
    decode = CanonTraversalEvidence.from_row
    def checked_decode(record):
        assert threading.get_ident() != loop_thread
        return decode(record)
    monkeypatch.setattr(CanonTraversalEvidence, 'from_row', checked_decode)
    assert await ClimbEffortRepository(Client({'canon_traversal_evidence': [evidence]})).public_span(row)


@pytest.mark.asyncio
async def test_evidence_and_zone_pages_include_the_last_row():
    from backend.tests.routes.test_climb_effort_api import effort
    row = effort(start_offset_s=10, end_offset_s=20)
    valid = evidence_for(row, range(0, 100, 10))
    older = [{**valid, 'ride_hash_hex': f'{i:064x}', 'ride_parser_version': 4} for i in range(500)]
    zones = [dict(id=f'zone-{i:03d}', user_id=row['user_id'], latitude=0, longitude=i*.001, radius_m=200)
             for i in range(500)]
    zones.append(dict(id='zone-last', user_id=row['user_id'], latitude=40.003, longitude=-75, radius_m=400))
    class PagedQuery(Query):
        def range(self, start, end):
            self.paged = True
            return super().range(start, end)
        def execute(self):
            assert getattr(self, 'paged', False), 'every evidence/zone page must specify its range'
            return super().execute()
    client = Client({'canon_traversal_evidence': [*older, valid], 'privacy_zones': zones})
    client.from_ = lambda table: PagedQuery(client, table)
    repo = ClimbEffortRepository(client)
    assert not await repo.public_span(row)  # last zone hides the effort
    key = (row['ride_id'], row['ride']['ride_hash_hex'], 5)
    assert repo._points[key] is not None and len(repo._zones[row['user_id']]) == 501
    # A full 499-row page from the end-exclusive range, then the short last page.
    assert sum(table == 'canon_traversal_evidence' for table, _ in client.selects) == 2
    assert sum(table == 'privacy_zones' for table, _ in client.selects) == 2


@pytest.mark.asyncio
async def test_evidence_is_batched_and_reused_for_all_seats_of_a_ride():
    from backend.tests.routes.test_climb_effort_api import effort
    first = effort(start_offset_s=10, end_offset_s=20)
    evidence = evidence_for(first, list(range(0, 100, 10)))
    second = deepcopy(first); second.update(id='second', start_offset_s=30, end_offset_s=40)
    client = Client({'privacy_zones':[], 'canon_traversal_evidence':[evidence]})
    repo = ClimbEffortRepository(client)
    await repo.prepare_public_spans([first, second])
    assert await repo.public_span(first) and await repo.public_span(second)
    assert sum(table == 'canon_traversal_evidence' for table, _ in client.selects) == 1
    assert sum(table == 'privacy_zones' for table, _ in client.selects) == 1


@pytest.mark.asyncio
async def test_visibility_batches_bound_filter_size_for_large_rank_scans():
    from backend.tests.routes.test_climb_effort_api import effort
    rows = [effort(ride_id=str(UUID(int=i + 1)), user_id=str(UUID(int=i + 1000)),
                   start_offset_s=10, end_offset_s=20) for i in range(201)]
    class BoundedQuery(Query):
        def in_(self, key, values):
            assert len(values) <= 100
            return super().in_(key, values)
    client = Client({'privacy_zones': [], 'canon_traversal_evidence': [
        evidence_for(row, list(range(0, 100, 10)), ride_id=row['ride_id']) for row in rows]})
    client.from_ = lambda table: BoundedQuery(client, table)
    repo = ClimbEffortRepository(client)
    await repo.prepare_public_spans(rows)
    assert all([await repo.public_span(row) for row in rows])
    assert sum(table == 'canon_traversal_evidence' for table, _ in client.selects) == 3
    assert sum(table == 'privacy_zones' for table, _ in client.selects) == 3


@pytest.mark.asyncio
async def test_all_time_scan_is_confirmed_and_stops_at_viewer_time():
    from backend.tests.routes.test_climb_effort_api import CLIMB_ID
    class BoundedQuery(Query):
        def eq(self, key, value):
            if self.table == 'vault_completions' and key == 'chain_confirmation_status':
                assert value == 'confirmed'
                self.client.confirmed = True
            return super().eq(key, value)
        def lte(self, key, value):
            assert key == 'time_seconds' and value == 100
            self.client.bound = value
            return super().lte(key, value)
        def execute(self):
            if self.table == 'vault_completions':
                assert self.client.confirmed and self.client.bound == 100
                assert all(r['time_seconds'] <= 100 and r['chain_confirmation_status'] == 'confirmed' for r in self.rows)
            return super().execute()
    client = Client({'indexed_vaults':[{'signature_hex':'sig','canon_climb_id':CLIMB_ID}],
        'vault_completions':[dict(id='too-slow', activity_id=str(UUID(int=2)), wallet='w', time_seconds=101,
                                 validated=True, chain_confirmation_status='confirmed', vault_signature='sig'),
                             dict(id='unconfirmed', activity_id=str(UUID(int=3)), wallet='w', time_seconds=90,
                                  validated=True, chain_confirmation_status='pending', vault_signature='sig')]})
    client.from_ = lambda table: BoundedQuery(client, table)
    assert await ClimbEffortRepository(client).completion_efforts('sig', max_time_s=100) == []
