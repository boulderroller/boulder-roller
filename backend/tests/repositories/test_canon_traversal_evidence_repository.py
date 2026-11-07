from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.repositories.ride import RideRepository


class _Query:
    def __init__(self, client, table: str) -> None:
        self.client = client
        self.table = table
        self.filters = []
        self.payload = None
        self.on_conflict = None

    def select(self, columns: str):
        self.columns = columns
        return self

    def eq(self, column: str, value):
        self.filters.append((column, value))
        return self

    def limit(self, value: int):
        self.limit_value = value
        return self

    def upsert(self, payload: dict, on_conflict: str, returning: str):
        self.payload = dict(payload)
        self.on_conflict = on_conflict
        self.returning = returning
        return self

    def execute(self):
        self.client.queries.append(self)
        if self.payload is not None:
            self.client.rows = [self.payload]
            return SimpleNamespace(data=[self.payload])
        rows = [
            row
            for row in self.client.rows
            if all(str(row.get(column)) == str(value) for column, value in self.filters)
        ]
        return SimpleNamespace(data=rows[: getattr(self, "limit_value", len(rows))])


class _Client:
    def __init__(self) -> None:
        self.rows = []
        self.queries = []

    def table(self, table: str):
        assert table == "canon_traversal_evidence"
        return _Query(self, table)


@pytest.mark.asyncio
async def test_store_and_load_canon_evidence_uses_full_identity_key() -> None:
    client = _Client()
    repository = RideRepository(client)
    ride_id = uuid4()
    row = {
        "ride_id": str(ride_id),
        "ride_hash_hex": "ab" * 32,
        "ride_parser_version": 7,
        "evidence_version": "canon_traversal_evidence_v1",
        "sample_count": 1,
        "sample_digest": "cd" * 32,
        "samples": [{"source_index": 0, "t": 0.125}],
    }

    await repository.store_canon_traversal_evidence(row)
    loaded = await repository.get_canon_traversal_evidence(
        ride_id=ride_id,
        ride_hash_hex="ab" * 32,
        ride_parser_version=7,
        evidence_version="canon_traversal_evidence_v1",
    )

    assert loaded == row
    store_query, load_query = client.queries
    assert store_query.on_conflict == (
        "ride_id,ride_hash_hex,ride_parser_version,evidence_version"
    )
    assert store_query.returning == "minimal"
    assert load_query.filters == [
        ("ride_id", str(ride_id)),
        ("ride_hash_hex", "ab" * 32),
        ("ride_parser_version", 7),
        ("evidence_version", "canon_traversal_evidence_v1"),
    ]
