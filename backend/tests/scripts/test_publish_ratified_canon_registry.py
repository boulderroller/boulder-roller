from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


SCRIPT_PATH = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "publish_ratified_canon_registry.py"
)
SPEC = importlib.util.spec_from_file_location(
    "publish_ratified_canon_registry",
    SCRIPT_PATH,
)
assert SPEC is not None and SPEC.loader is not None
publisher = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = publisher
SPEC.loader.exec_module(publisher)


class _Cursor:
    def __init__(self, rows: list[tuple[str, str, int]]) -> None:
        self.rows = rows

    def execute(self, _sql: str, _params=None) -> None:
        return None

    def fetchall(self) -> list[tuple[str, str, int]]:
        return self.rows

    def close(self) -> None:
        return None


class _Connection:
    def __init__(self, rows: list[tuple[str, str, int]] | None = None) -> None:
        self.rows = rows or []
        self.commits = 0
        self.rollbacks = 0
        self.closes = 0

    def cursor(self) -> _Cursor:
        return _Cursor(self.rows)

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1

    def close(self) -> None:
        self.closes += 1


def test_registry_state_accepts_only_empty_or_exact_launch_set() -> None:
    expected = {"a" * 64, "b" * 64}

    assert publisher.inspect_registry_state(_Connection(), expected) == "empty"
    assert (
        publisher.inspect_registry_state(
            _Connection(
                [
                    ("a" * 64, "ratified", 1),
                    ("b" * 64, "ratified", 1),
                ]
            ),
            expected,
        )
        == "exact"
    )

    with pytest.raises(publisher.RegistryPublicationError, match="partial or drifted"):
        publisher.inspect_registry_state(
            _Connection([("a" * 64, "ratified", 1)]),
            expected,
        )


def test_deferred_connection_holds_commit_and_close_until_outer_transaction() -> None:
    connection = _Connection()
    deferred = publisher.DeferredCommitConnection(connection)

    deferred.commit()
    deferred.close()

    assert connection.commits == 0
    assert connection.closes == 0

    deferred.rollback()
    assert connection.rollbacks == 1


def test_publish_payloads_atomically_commits_once_after_all_rows() -> None:
    connection = _Connection()
    payloads = [
        {"climb": {"candidate_fingerprint": "a" * 64}},
        {"climb": {"candidate_fingerprint": "b" * 64}},
    ]
    published: list[str] = []

    def publish_one(payload, *, connection_factory):
        shared = connection_factory()
        fingerprint = payload["climb"]["candidate_fingerprint"]
        published.append(fingerprint)
        shared.commit()
        shared.close()
        return {"fingerprint": fingerprint}

    results = publisher.publish_payloads_atomically(
        payloads,
        connection=connection,
        publish_one=publish_one,
        verify=lambda: None,
    )

    assert published == ["a" * 64, "b" * 64]
    assert results == [
        {"fingerprint": "a" * 64},
        {"fingerprint": "b" * 64},
    ]
    assert connection.commits == 1
    assert connection.rollbacks == 0


def test_publish_payloads_atomically_rolls_back_every_row_on_failure() -> None:
    connection = _Connection()
    payloads = [
        {"climb": {"candidate_fingerprint": "a" * 64}},
        {"climb": {"candidate_fingerprint": "b" * 64}},
    ]

    def publish_one(payload, *, connection_factory):
        shared = connection_factory()
        if payload["climb"]["candidate_fingerprint"].startswith("b"):
            raise RuntimeError("synthetic second-row failure")
        shared.commit()
        return {"ok": True}

    with pytest.raises(RuntimeError, match="second-row failure"):
        publisher.publish_payloads_atomically(
            payloads,
            connection=connection,
            publish_one=publish_one,
            verify=lambda: None,
        )

    assert connection.commits == 0
    assert connection.rollbacks >= 1
