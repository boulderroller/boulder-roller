"""BACKEND_TRUTHS Gate 1 — runtime-enforceable invariants.

Parent: `docs/BACKEND_TRUTHS.md` (ACTIVE, ratified 2026-04-17).
Mirror of the protocol lane's Gate 1 / Gate 2 concept:

  * Gate 1 (this file) — every §N invariant that can be programmatically
    verified has a named test. A failure points the reviewer directly at
    the truth that regressed.
  * Gate 2 (planned) — full-stack integration smoke on live devnet.

Reviewer etiquette:
  * Every test name cites the § it enforces.
  * Docstrings declare current state: ``PASS``, ``PENDING`` (documented gap
    the backend does not yet enforce, deferred to a tracked repair item),
    or ``DRIFT`` (failing because the current code violates the truth;
    failure is a feature of the gate, not a bug).

Out of scope for this gate (covered elsewhere):
  * Protocol / Anchor program tests — protocol lane Gate 1.
  * Mobile TRUTHS — mobile lane Gate 1.
  * Pre-existing unrelated test failures (points-removal drift, mfab.5
    flagged units tests) — left untouched.
"""

from __future__ import annotations

import re

import pytest

from ._helpers import (
    CallSite,
    backend_root,
    call_sites,
    grep_source,
    is_wall_clock_call,
    line_has_backcompat_marker,
    read_module_tree,
    read_source,
    repo_root,
    refers_to_file_time,
)


# Modules the gate scans. Centralised so a rename has one edit point.
RIDE_PROCESSOR = "services/ride_processor.py"
RIDE_EXECUTOR = "services/ride_executor.py"
THRESHOLD_RELEASE_EXECUTOR = "services/threshold_release_executor.py"
RIDE_ECONOMIC_COORDINATOR = "services/ride_economic_coordinator.py"
RIDE_ECONOMIC_TERMINAL_PROJECTOR = "services/ride_economic_terminal_projector.py"
RIDE_ATTESTER = "services/ride_attester.py"
RIDE_PROJECTION_STORE = "services/ride_projection_store.py"
RIDE_ENRICHMENT_SERVICE = "services/ride_enrichment_service.py"
CLIMB_ECONOMY_PROCESSOR = "services/climb_economy_processor.py"
PROJECTION_WRITER = "services/projection_writer.py"
EPOCH_PROCESSOR = "services/epoch_processor.py"
SETTLEMENT_CHAIN = "services/settlement_chain.py"
SOLANA_DIRECT = "solana_direct.py"
LEADERBOARD_SYNC = "services/leaderboard_sync_service.py"
RIDES_ROUTE = "routes/rides.py"
ROUTES_DIR = "routes"


# Functions whose call sites we scan across backend modules.
SEND_CREDIT_CAL = "send_credit_cal"
SEND_RECORD_RIDE = "send_record_ride"
EXECUTOR_CREDIT_CAL = "_credit_cal"
EXECUTOR_RECORD_RIDE = "_record_ride"


LEGACY_LEADERBOARD_SQL_MIGRATION = "087_retire_legacy_leaderboard_write_side.sql"
POST_GATE2_SQL_REPAIR_MIGRATION = "088_fix_leaderboard_sync_notifications.sql"
LEGACY_LEADERBOARD_WRITE_RPC_NAMES = (
    "record_vault_completion_with_best_time",
    "update_vault_leaderboard",
    "update_vault_leaderboard_with_notifications",
    "rebuild_vault_leaderboard",
    "rebuild_all_vault_leaderboards",
    "snapshot_vault_leaderboard",
    "snapshot_all_leaderboards_for_epoch",
)


# ---------------------------------------------------------------------------
# §2.2 — Ride Attestation referenced by every credit_cal
# ---------------------------------------------------------------------------


def test_section_2_2_every_send_credit_cal_carries_ride_hash() -> None:
    """§2.2 RideAttestation — STATUS: PASS.

    Every `credit_cal` call must reference a `RideAttestation` via a
    `ride_hash` kwarg. No CAL credit flows without attestation lineage
    (BACKEND_TRUTHS §2.2, §2.3, §6.4).

    Scan: backend/app/solana_direct.py plus the processor/executor
    orchestration path. If a new caller appears without `ride_hash=`,
    Gate 1 fails.
    """
    scanned_modules = [SOLANA_DIRECT, RIDE_PROCESSOR, RIDE_EXECUTOR]
    offenders: list[str] = []

    for module in scanned_modules:
        targets = (
            [SEND_CREDIT_CAL, EXECUTOR_CREDIT_CAL]
            if module == RIDE_EXECUTOR
            else [SEND_CREDIT_CAL]
        )
        for site in call_sites(module, targets):
            # The definition site in solana_direct.py binds ``ride_hash`` as
            # a formal parameter — inside that definition there is no caller
            # to check. Skip the definition by guarding on the kwarg set.
            if not site.has_kwarg("ride_hash"):
                offenders.append(f"{module}:{site.lineno} missing ride_hash kwarg")

    # Also sanity-check there is at least one positively-passing caller so
    # this test cannot pass by accident when the symbol is renamed.
    caller_in_executor_or_processor = [
        s
        for module in [RIDE_PROCESSOR, RIDE_EXECUTOR]
        for s in call_sites(
            module,
            [SEND_CREDIT_CAL, EXECUTOR_CREDIT_CAL]
            if module == RIDE_EXECUTOR
            else [SEND_CREDIT_CAL],
        )
        if s.has_kwarg("ride_hash")
    ]
    assert caller_in_executor_or_processor, (
        "expected at least one RideProcessor/RideExecutor caller of "
        "send_credit_cal with ride_hash= kwarg; scan may be stale"
    )

    assert not offenders, (
        "§2.2 RideAttestation drift — send_credit_cal called without a "
        "ride_hash attestation reference:\n  " + "\n  ".join(offenders)
    )


# ---------------------------------------------------------------------------
# §3 — Three Times: completed_at is the economic clock
# ---------------------------------------------------------------------------


def test_section_3_1_send_record_ride_completed_at_sourced_from_file() -> None:
    """§3.1 completed_at — STATUS: PASS.

    The `completed_at` passed to `send_record_ride` must come from the
    parsed ride file (``parsed_ride.completed_at`` etc.), never from an
    ambient wall-clock call. BACKEND_TRUTHS §3.1 names `completed_at` as
    the economic clock; §13.2 flags upload-time-as-economic-time as a drift
    to repair.

    This is a per-callsite check on each keyword argument: reject if the
    expression is a `datetime.utcnow()` / `time.time()` / `datetime.now()`
    shape.
    """
    offenders: list[str] = []
    positive_sites: list[CallSite] = []

    for module in [RIDE_PROCESSOR, RIDE_EXECUTOR, EPOCH_PROCESSOR]:
        targets = (
            [SEND_RECORD_RIDE, EXECUTOR_RECORD_RIDE]
            if module == RIDE_EXECUTOR
            else [SEND_RECORD_RIDE]
        )
        for site in call_sites(module, targets):
            expr = site.kwarg("completed_at")
            # A positional call in the call path would still be caught when
            # we require at least one positively-passing site below.
            if expr is None:
                continue
            positive_sites.append(site)
            if is_wall_clock_call(expr):
                offenders.append(
                    f"{module}:{site.lineno} completed_at= uses wall-clock "
                    "call (violates §3.1)"
                )
            elif not refers_to_file_time(expr):
                # Defensive: any expression we can't tie back to a ride-file
                # source gets flagged for reviewer eyeball. Keeps the gate
                # from rubber-stamping silently renamed aliases.
                offenders.append(
                    f"{module}:{site.lineno} completed_at= expression could "
                    "not be tied to a ride-file timestamp; review manually"
                )

    assert positive_sites, (
        "expected at least one send_record_ride call with completed_at= "
        "kwarg in ride_processor.py / epoch_processor.py; scan may be stale"
    )
    assert not offenders, (
        "§3.1 completed_at drift — on-chain ride event time must source "
        "from the ride file:\n  " + "\n  ".join(offenders)
    )


# ---------------------------------------------------------------------------
# §3.3 — finalized_at is chain-derived settlement time
# ---------------------------------------------------------------------------


def test_section_3_3_indexed_distribution_finalized_at_is_generated_from_block_time() -> None:
    """§3.3 finalized_at — STATUS: PASS.

    `indexed_epoch_distributions.finalized_at` must be generated from the
    on-chain event's `block_time`. A plain backend-writable column would
    recreate the old drift where services could fabricate settlement time
    from wall clock.
    """
    sql_paths = [
        repo_root() / "backend" / "sql" / "086_indexed_settlement_projections.sql",
        repo_root()
        / "backend"
        / "supabase"
        / "migrations"
        / "20260417_096_finalized_at_timestamps.sql",
        repo_root()
        / "backend"
        / "supabase"
        / "migrations"
        / "20260420_097_finalized_at_settlement_projection.sql",
    ]

    missing: list[str] = []
    for path in sql_paths:
        text = path.read_text(encoding="utf-8")
        if "finalized_at TIMESTAMPTZ" not in text:
            missing.append(f"{path.name}: no finalized_at column definition")
            continue
        if "GENERATED ALWAYS AS" not in text:
            missing.append(f"{path.name}: finalized_at is not GENERATED ALWAYS")
        if "to_timestamp(block_time)" not in text:
            missing.append(f"{path.name}: finalized_at not derived from block_time")

    assert not missing, (
        "§3.3 finalized_at drift — settlement timestamps must be generated "
        "from indexed chain event block_time:\n  " + "\n  ".join(missing)
    )


def test_section_3_3_rides_finalized_at_flows_from_distribution_projection_trigger() -> None:
    """§3.3 finalized_at — STATUS: PASS.

    Ride-level finalization must flow from `indexed_epoch_distributions`,
    not from backend services. The migration installs DB-side triggers that
    refresh `rides.finalized_at` when a chain distribution event lands or a
    chain-recorded vault completion is mirrored later.
    """
    migration = (
        repo_root()
        / "backend"
        / "sql"
        / "089_finalized_at_settlement_projection.sql"
    ).read_text(encoding="utf-8")

    required_fragments = [
        "CREATE OR REPLACE FUNCTION br_settlement_week",
        "CREATE OR REPLACE FUNCTION br_refresh_ride_finalized_at",
        "CREATE OR REPLACE FUNCTION br_sync_epoch_distribution_finalized_at",
        "CREATE TRIGGER br_indexed_epoch_distribution_finalized_at_trigger",
        "CREATE TRIGGER br_vault_completion_finalized_at_trigger",
        "FROM vault_completions vc",
        "JOIN indexed_epoch_distributions ied",
        "vc.on_chain_tx IS NOT NULL",
        "UPDATE rides",
        "SET finalized_at = v_finalized_at",
        "UPDATE epoch_distributions ed",
    ]
    missing = [fragment for fragment in required_fragments if fragment not in migration]
    assert not missing, (
        "§3.3 finalized_at projection drift — migration 089 must propagate "
        "chain-derived settlement finalization to ride/queue read models. "
        "Missing fragments:\n  " + "\n  ".join(missing)
    )

    forbidden_wall_clock = [
        "NOW()",
        "CURRENT_TIMESTAMP",
        "clock_timestamp",
        "datetime.utcnow",
        "datetime.now",
    ]
    offenders = [token for token in forbidden_wall_clock if token in migration]
    assert not offenders, (
        "§3.3 finalized_at projection drift — migration 089 fabricates "
        "settlement time from wall clock tokens: " + ", ".join(offenders)
    )


def test_section_3_3_finalized_at_proof_script_is_rollback_scoped() -> None:
    """§3.3 finalized_at — STATUS: PASS.

    The operational smoke for finalized_at must be safe to run against the
    configured database. It proves the DB trigger behavior in an isolated schema
    and rolls back, instead of mutating production ride/distribution rows.
    """
    script = (
        repo_root()
        / "backend"
        / "scripts"
        / "prove_finalized_at_projection.py"
    ).read_text(encoding="utf-8")

    required_fragments = [
        "async with conn.transaction():",
        'CREATE SCHEMA "{schema}"',
        'SET LOCAL search_path = "{schema}", public',
        "raise RollbackProof",
        "completion exists first; distribution event finalizes it",
        "distribution exists first; later completion backfills",
        "multi-vault ride locks only after all completions settle",
    ]
    missing = [fragment for fragment in required_fragments if fragment not in script]
    assert not missing, (
        "§3.3 finalized_at proof drift — proof script must remain "
        "transaction-scoped and cover both trigger directions plus the "
        "multi-vault all-settled rule. Missing fragments:\n  "
        + "\n  ".join(missing)
    )


# ---------------------------------------------------------------------------
# §5 — Role boundaries are visible in code
# ---------------------------------------------------------------------------


def test_section_5_ride_processor_delegates_attester_executor_projector_roles() -> None:
    """§5 Role Separation — STATUS: PASS.

    The ride processor may coordinate, but it must not collapse Attester,
    Executor, and Projector responsibilities back into one monolith. This gate
    keeps the three role seams visible and blocks the most important regressions:
    parser/canonicalization helpers in the processor and direct on-chain
    economic calls bypassing RideExecutor.
    """
    source = read_source(RIDE_PROCESSOR)
    combined_source = "\n".join(
        (
            source,
            read_source(RIDE_ECONOMIC_COORDINATOR),
            read_source(CLIMB_ECONOMY_PROCESSOR),
        )
    )

    required_fragments = [
        "self.ride_attester = ride_attester or RideAttester()",
        "self.ride_executor = ride_executor or RideExecutor()",
        "self.projection_writer = projection_writer or ProjectionWriter(self._client)",
        "self.ride_projection_store = ride_projection_store or RideProjectionStore(",
        "self.climb_economy_processor = (",
        "self.ride_economic_coordinator = (",
        "self.ride_enrichment_service = (",
        "self.ride_attester.prepare_ride(",
        "self.ride_projection_store.store_activity_streams(",
        "self.ride_enrichment_service.detect_and_store_patterns(",
        "self.ride_economic_coordinator.freeze_plan(",
        "self.ride_economic_coordinator.execute(",
        "self.executor.record_ride_attestation(",
        "self.executor.record_climb_completion_receipt(",
        "self.executor.credit_cal_receipt(",
    ]
    missing = [
        fragment
        for fragment in required_fragments
        if fragment not in combined_source
    ]
    assert not missing, (
        "§5 role-boundary drift — RideProcessor no longer delegates through "
        "the Attester/Executor/Projector seams. Missing fragments:\n  "
        + "\n  ".join(missing)
    )

    forbidden_patterns = {
        "parse_ride_file_bytes": r"\bparse_ride_file_bytes\b",
        "parse_ride_file(": r"\bparse_ride_file\s*\(",
        "compute_ride_identity_bytes": r"\bcompute_ride_identity_bytes\b",
        "direct calculate_metrics(": r"(?<!\.)\bcalculate_metrics\s*\(",
        "send_record_ride(": r"\bsend_record_ride\s*\(",
        "send_credit_cal(": r"\bsend_credit_cal\s*\(",
        "send_record_climb_completion(": r"\bsend_record_climb_completion\s*\(",
        "load_default_config(": r"\bload_default_config\s*\(",
    }
    offenders = [
        label
        for label, pattern in forbidden_patterns.items()
        if re.search(pattern, source)
    ]
    assert not offenders, (
        "§5 role-boundary drift — RideProcessor reacquired Attester/Executor "
        "implementation details:\n  " + "\n  ".join(offenders)
    )

    tree = read_module_tree(RIDE_PROCESSOR)
    processor_class = next(
        node
        for node in tree.body
        if getattr(node, "name", None) == "RideProcessor"
    )
    method_names = [
        node.name
        for node in processor_class.body
        if node.__class__.__name__ in ("FunctionDef", "AsyncFunctionDef")
    ]
    allowed_methods = {
        "__init__",
        "_emit_notification",
        "_emit_record_board_notifications",
        "_emit_ride_failed_notification",
        "_emit_ride_finalized_notification",
        "_bind_reward_ftp_snapshot",
        "_freeze_ride_economic_plan",
        "_publish_nats_event",
        "process_ride",
        "process_phase1_core",
        "process_phase2_enrichment",
        "process_phase3_rewards",
    }
    extra_methods = sorted(set(method_names) - allowed_methods)
    assert not extra_methods, (
        "§5 coordinator drift — RideProcessor should expose only orchestration "
        "entrypoints plus NATS publish helper. Move implementation helpers to "
        "role services:\n  " + "\n  ".join(extra_methods)
    )

    service_modules = [
        RIDE_ATTESTER,
        RIDE_EXECUTOR,
        THRESHOLD_RELEASE_EXECUTOR,
        RIDE_ECONOMIC_COORDINATOR,
        RIDE_ECONOMIC_TERMINAL_PROJECTOR,
        PROJECTION_WRITER,
        RIDE_PROJECTION_STORE,
        RIDE_ENRICHMENT_SERVICE,
        CLIMB_ECONOMY_PROCESSOR,
    ]
    role_service_line_limit = 550
    oversized = []
    for module in service_modules:
        line_count = len(read_source(module).splitlines())
        if line_count >= role_service_line_limit:
            oversized.append(f"{module}: {line_count} LOC")
    assert not oversized, (
        "§5 role service drift — extracted services must stay reviewable "
        f"and single-purpose (<{role_service_line_limit} LOC):\n  "
        + "\n  ".join(oversized)
    )


# ---------------------------------------------------------------------------
# §6.1 — Parser Version Binding
# ---------------------------------------------------------------------------


def test_section_6_1_parser_version_on_every_record_ride() -> None:
    """§6.1 Parser Version Binding — STATUS: PASS.

    Every `send_record_ride` call must pass `parser_version` so the
    attestation is stamped with the canonical form that produced the hash
    (BACKEND_TRUTHS §6.1). Silent reinterpretation of old rides is
    forbidden.
    """
    offenders: list[str] = []
    caller_sites: list[CallSite] = []

    for module in [RIDE_PROCESSOR, RIDE_EXECUTOR, EPOCH_PROCESSOR]:
        targets = (
            [SEND_RECORD_RIDE, EXECUTOR_RECORD_RIDE]
            if module == RIDE_EXECUTOR
            else [SEND_RECORD_RIDE]
        )
        for site in call_sites(module, targets):
            caller_sites.append(site)
            if not site.has_kwarg("parser_version"):
                offenders.append(
                    f"{module}:{site.lineno} send_record_ride missing "
                    "parser_version= kwarg"
                )

    assert caller_sites, (
        "expected at least one send_record_ride caller; scan may be stale"
    )
    assert not offenders, (
        "§6.1 Parser Version Binding drift — send_record_ride must stamp "
        "parser_version on every attestation:\n  " + "\n  ".join(offenders)
    )


# ---------------------------------------------------------------------------
# §6.3 — Hash Compare Is The Attestation Gate (PENDING)
# ---------------------------------------------------------------------------


def test_section_6_3_hash_compare_is_attestation_gate() -> None:
    """§6.3 Hash Compare — STATUS: LANDED (upgraded from PENDING 2026-04-17).

    BACKEND_TRUTHS §6.3: when a mobile-stamped preliminary hash is present,
    the backend must recompute and compare. A mismatch must be surfaced
    (telemetry / Sentry / review state) and MUST NOT be silently laundered
    into a successful attestation.

    This sentinel was PENDING while the handshake was half-built. The
    wire break was closed in commit 9392ce1c (UploadInitRequest accepts
    preliminary_ride_hash + parser_version). The compare function
    `evaluate_preliminary_attestation` lives in `ride_processor.py` and
    sets `review_reason` on mismatch; downstream code gates on
    `requires_review`.

    This test now asserts the compare path positively: the function
    exists, emits named review_reason values on mismatch, and the
    result flows to a gate that short-circuits economic consequences.

    When `evaluate_preliminary_attestation` moves to `ride_attester.py`
    per mfab.1 next slice, the file check below flips to attester — the
    invariant (not the location) is what matters.
    """
    # The compare function exists and is callable today.
    processor_source = read_source("services/ride_processor.py")
    attester_source = read_source("services/ride_attester.py")
    compare_fn_landed = (
        "def evaluate_preliminary_attestation" in processor_source
        or "def evaluate_preliminary_attestation" in attester_source
    )
    assert compare_fn_landed, (
        "§6.3 regression: evaluate_preliminary_attestation not defined in "
        "ride_processor.py or ride_attester.py. The compare gate is gone."
    )

    # Mismatch produces named review_reason values — not silent success.
    # These are the four documented mismatch classes from the handshake.
    required_review_reasons = [
        "parser_version_mismatch",
        "preliminary_hash_mismatch",
        "invalid_preliminary_hash_length",
        "incomplete_preliminary_attestation",
    ]
    for reason in required_review_reasons:
        assert reason in processor_source or reason in attester_source, (
            f"§6.3 regression: review_reason='{reason}' no longer emitted "
            "on mismatch. Mismatches may be silently laundered."
        )

    # GPX parity has landed. Do not reintroduce a file-type bypass that
    # silently accepts stamped GPS-only rides without comparing hashes.
    bypass_markers = [
        'file_type or "").strip().lower() != "fit"',
        "only enforce equality on FIT",
        "GPX canonical parity lands",
        "canonical_match=None",
    ]
    offenders = [marker for marker in bypass_markers if marker in attester_source]
    assert not offenders, (
        "§6.3 regression: preliminary-hash compare contains a file-type "
        "bypass marker after GPX parity landed. Stamped GPX uploads must "
        "compare the same as FIT uploads. Offenders: " + ", ".join(offenders)
    )

    # A downstream gate must read requires_review / review_reason and
    # short-circuit economic consequences. Grep for the gate signal.
    gate_present = (
        "requires_review" in processor_source
        or "review_reason" in processor_source
    )
    assert gate_present, (
        "§6.3 regression: ride_processor.py no longer references "
        "requires_review / review_reason — mismatch result may not flow "
        "to a downstream gate."
    )

    # Existence proof: preliminary hash references are present — the
    # compare path is alive. When it moves per mfab.1 Attester extraction,
    # update the file target above.
    hash_refs = grep_source(
        "services/ride_processor.py",
        r"preliminary.*hash|prelim_hash|prelim_ride_hash",
        flags=re.IGNORECASE,
    )
    assert hash_refs, (
        "§6.3 regression: ride_processor.py no longer mentions a "
        "preliminary hash — the compare path may have been removed. "
        "Restore the handshake or move it (and update this test)."
    )



# ---------------------------------------------------------------------------
# §6.4 — Economic Consequences Are Derived Once (structural replay guard)
# ---------------------------------------------------------------------------


def test_section_6_4_economic_send_fns_short_circuit_on_existing_receipt_pda() -> None:
    """§6.4 Economic Consequences Derived Once — STATUS: PASS.

    BACKEND_TRUTHS §6.4 / FIX_PLAN P5: replay protection is structural.
    Child receipts keyed on `(ride_attestation, rider)` and
    `(ride_attestation, climb_id)` use on-chain `init` semantics to prevent
    duplicates. The backend must NOT rely on its own tables to prevent
    double-spend.

    Static shape check on `solana_direct.py`:
      * `send_record_ride` short-circuits if the RideAttestation PDA
        already exists (no duplicate attestation).
      * `send_credit_cal` short-circuits if the CAL mint receipt already
        exists (no duplicate CAL credit per attestation).
      * `send_record_climb_completion` short-circuits if the climb-
        completion receipt already exists.

    If any of these loses its `_account_exists(...)` guard, the structural
    replay protection degrades to "first writer wins on-chain, backend
    burns a transaction per retry" — fails BACKEND_TRUTHS §6.4.
    """
    source = read_source(SOLANA_DIRECT)

    # Get each send_* function body and verify the short-circuit.
    fn_bodies: dict[str, str] = {}
    for fn_name in [
        "send_record_ride",
        "send_credit_cal",
        "send_record_climb_completion",
    ]:
        pattern = re.compile(
            rf"^async def\s+{re.escape(fn_name)}\b", re.MULTILINE
        )
        match = pattern.search(source)
        if not match:
            pytest.fail(
                f"§6.4 drift — {fn_name} not found in {SOLANA_DIRECT}; "
                "scan may be stale"
            )
        start = match.start()
        tail = source[match.end():]
        next_top = re.search(r"\n(async def|def|class)\s", tail)
        end = len(source) if not next_top else match.end() + next_top.start()
        fn_bodies[fn_name] = source[start:end]

    missing_short_circuits: list[str] = []
    for fn_name, body in fn_bodies.items():
        # The minimum shape: somewhere in the function body there is an
        # `await _account_exists(...)` with an early return. Both tokens
        # must appear; missing either is a drift signal.
        if "_account_exists(" not in body:
            missing_short_circuits.append(
                f"{fn_name}: no _account_exists(...) guard"
            )
            continue
        # The guard must gate a return or raise, not merely log.
        if not re.search(r"_account_exists\([^)]*\)", body):
            missing_short_circuits.append(
                f"{fn_name}: _account_exists() reference found but shape "
                "is unexpected"
            )
            continue
        if "return f\"exists:" not in body and "exists:" not in body:
            missing_short_circuits.append(
                f"{fn_name}: _account_exists() guard does not early-return "
                "with 'exists:' sentinel (replay guard weakened)"
            )

    assert not missing_short_circuits, (
        "§6.4 Structural Replay Protection drift:\n  "
        + "\n  ".join(missing_short_circuits)
    )


# ---------------------------------------------------------------------------
# §7.4 — Per-Bucket Carry Preserved
# ---------------------------------------------------------------------------


def test_section_7_4_settlement_snapshot_reads_all_five_carry_buckets() -> None:
    """§7.4 Per-Bucket Carry — STATUS: PASS.

    Per-bucket carry keeps bucket identity (BACKEND_TRUTHS §7.4,
    FIX_PLAN P10). No cross-bucket leakage. The authoritative settlement
    snapshot builder must read
    ALL FIVE carry fields from the on-chain Vault account when it computes
    pending distribution value: record royalty, stakers, local legend,
    POL, treasury.

    This test asserts all five ``carry_*`` fields appear in
    settlement_chain.py so the gate catches the case where a future edit
    silently drops one bucket's carry (which would silently fund a
    different bucket on the next week).
    """
    source = read_source(SETTLEMENT_CHAIN)
    expected_fields = [
        "carry_record_royalty",
        "carry_stakers",
        "carry_local_legend",
        "carry_pol",
        "carry_treasury",
    ]
    missing = [f for f in expected_fields if f not in source]
    assert not missing, (
        "§7.4 Per-Bucket Carry drift — settlement_chain.py must read all "
        f"five on-chain carry fields; missing: {missing}"
    )


# ---------------------------------------------------------------------------
# §7.3 — Finalization One-Way (PENDING: backend does not yet enforce)
# ---------------------------------------------------------------------------


def test_section_7_3_finalization_one_way_pending_backend_does_not_yet_enforce() -> None:
    """§7.3 Finalization One-Way — STATUS: PENDING.

    BACKEND_TRUTHS §7.3: once a Settlement Week is finalized, no backend
    operation can reverse it. Rides completed inside a finalized window
    that arrive after finalization are recorded for provenance but MUST
    earn nothing.

    Current state (2026-04-17): the chain enforces this via on-chain
    invariants (RideAttestation PDA + child receipts against VaultPDA
    finalised-epoch state). The BACKEND does not pre-gate credit_cal based
    on `completed_at` vs `last_distribution_epoch`. Chain-level rejection
    is the safety net.

    This PENDING test documents the absence explicitly so that when the
    pre-gate lands, the reviewer knows to upgrade the scan.

    Flip path: once `services/ride_processor.py` (or a new service) checks
    `completed_at`'s epoch against `last_distribution_epoch` before
    calling `send_credit_cal`, rewrite this test to assert that gate.
    """
    # Confirm the gate does NOT exist today. If someone lands it quietly
    # without repairing this test, the test flips status — a reviewer
    # reads this file and knows they need to rewrite the assertion.
    rp_source = read_source(RIDE_PROCESSOR)
    routes_source = read_source(RIDES_ROUTE)

    # Tokens that would almost certainly appear if a real pre-gate landed
    # in either file. Any of them → time to upgrade the test.
    gate_markers = [
        "last_distribution_epoch",
        "finalized_epoch",
        "is_epoch_finalized",
        "epoch_finalized",
    ]
    for marker in gate_markers:
        assert marker not in rp_source, (
            f"§7.3 state changed — ride_processor.py now references "
            f"'{marker}'. Upgrade this PENDING test to assert that "
            "finalized-epoch rides do not get credit_cal."
        )
        assert marker not in routes_source, (
            f"§7.3 state changed — routes/rides.py now references "
            f"'{marker}'. Upgrade this PENDING test to assert the gate."
        )

    pytest.skip(
        "§7.3 PENDING — backend does not currently enforce finalization "
        "one-way server-side; chain layer enforces via on-chain invariants. "
        "This test documents the gap. Upgrade when backend adds the gate."
    )


# ---------------------------------------------------------------------------
# §8.2 — Backend Authority Is Scoped
# ---------------------------------------------------------------------------


def test_section_8_2_backend_authority_resolved_through_helper() -> None:
    """§8.2 Backend Authority Is Scoped — STATUS: PASS.

    Every backend_authority signer inside tx-construction paths must be
    resolved via `resolve_backend_authority()`. The key must not be read
    from an env var directly at the call site, and must not be hardcoded.

    Additionally, `_validate_expected_backend_authority()` must exist and
    be wired into the load path so that misconfigured staging / mainnet
    keys fail loud instead of silently minting.

    See BACKEND_TRUTHS §8.2 ("chain → backend → rider audits"): the grant
    direction is single; authority flows from on-chain ProgramConfig, not
    from ambient env.
    """
    source = read_source(SOLANA_DIRECT)

    # 1. resolve_backend_authority is the single entry point.
    assert "def resolve_backend_authority" in source, (
        "§8.2 drift — resolve_backend_authority helper not defined in "
        f"{SOLANA_DIRECT}"
    )

    # 2. the expected-authority guard exists and is wired through the
    # load path (called from load_backend_authority_keypair).
    assert "def _validate_expected_backend_authority" in source, (
        "§8.2 drift — _validate_expected_backend_authority guard missing"
    )

    load_body = _extract_function_body(source, "load_backend_authority_keypair")
    assert load_body is not None, (
        "§8.2 drift — load_backend_authority_keypair helper not found"
    )
    assert "_validate_expected_backend_authority" in load_body, (
        "§8.2 drift — load_backend_authority_keypair does not call "
        "_validate_expected_backend_authority (silent key-swap risk)"
    )

    # 3. Every `authority = ...` assignment that binds a local name used in
    # tx-construction must come from resolve_backend_authority(...) — not
    # from os.getenv, not from a literal.
    #
    # Exclude the keypair loaders themselves: they ARE the authority
    # resolution machinery (they call `_validate_expected_backend_authority`
    # before returning), so it is correct for them to call
    # `_load_keypair` / `load_fee_payer_keypair`. A bypass would be a
    # caller that binds `authority` from anywhere else and uses it as a
    # signer.
    loader_spans = _function_line_spans(
        source, {"load_backend_authority_keypair", "load_default_config"}
    )

    offending_lines: list[str] = []
    for lineno, line in grep_source(
        SOLANA_DIRECT,
        r"^\s*(backend_authority|sponsor_authority|authority)\s*=\s*",
    ):
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        # Inside the loader bodies is allowed — that is where authority is
        # resolved from env / fallback and then validated.
        if _line_inside_any(lineno, loader_spans):
            continue
        # Allow: resolve_backend_authority(...) result binding.
        if "resolve_backend_authority(" in stripped:
            continue
        # Allow dataclass default typing lines (the field declaration).
        if re.search(r"Optional\[Keypair\]\s*=\s*None", stripped):
            continue
        # Allow parameter-passing within make_* or send_* definitions where
        # the RHS is ``authority`` / ``backend_authority`` (just rebinding).
        if re.match(
            r"^(backend_authority|sponsor_authority|authority)"
            r"\s*=\s*(backend_authority|sponsor_authority|authority)\b",
            stripped,
        ):
            continue
        offending_lines.append(f"{SOLANA_DIRECT}:{lineno} {stripped}")

    assert not offending_lines, (
        "§8.2 drift — backend_authority bound via a path that bypasses "
        "resolve_backend_authority() / load_backend_authority_keypair():\n"
        "  " + "\n  ".join(offending_lines)
    )


def _extract_function_body(source: str, name: str) -> str | None:
    """Return the body of the top-level ``def {name}`` in ``source``.

    Naive but sufficient: stops at the next top-level ``def``/``class`` or
    module end. Used only for local-grep assertions inside
    solana_direct.py.
    """
    pattern = re.compile(rf"^def\s+{re.escape(name)}\b", re.MULTILINE)
    match = pattern.search(source)
    if not match:
        return None
    start = match.start()
    tail = source[match.end():]
    # Advance until a line that starts with `def ` or `class ` at column 0.
    next_top = re.search(r"\n(def|class|async def)\s", tail)
    end = len(source) if not next_top else match.end() + next_top.start()
    return source[start:end]


def _function_line_spans(source: str, names: set[str]) -> list[tuple[int, int]]:
    """Return 1-indexed ``(start_lineno, end_lineno)`` spans for each named
    top-level function in ``source``. Used to exclude loader-internal lines
    from §8.2 scanning.
    """
    import ast as _ast

    tree = _ast.parse(source)
    spans: list[tuple[int, int]] = []
    for node in tree.body:
        if isinstance(node, (_ast.FunctionDef, _ast.AsyncFunctionDef)) and node.name in names:
            end_lineno = getattr(node, "end_lineno", None) or node.lineno
            spans.append((node.lineno, end_lineno))
    return spans


def _line_inside_any(lineno: int, spans: list[tuple[int, int]]) -> bool:
    return any(start <= lineno <= end for start, end in spans)


# ---------------------------------------------------------------------------
# §10.1 — Indexer Is A Cache (tx construction reads RPC, not indexer)
# ---------------------------------------------------------------------------


def test_section_10_1_tx_builder_reads_program_config_from_rpc_not_supabase() -> None:
    """§10.1 Indexer Boundary — STATUS: PASS.

    BACKEND_TRUTHS §10.1 / §10.2: transaction builders bypass the indexer.
    Canonical fields (`ProgramConfig`, `last_distribution_epoch`, POL /
    treasury token accounts, `backend_authority`) must be read via RPC,
    not via Supabase tables.

    Concrete check: `solana_direct.py` must not import Supabase and must
    not reference any indexer table name. `services/tx_builder.py` must
    resolve `treasury_token_account` through
    `get_program_config_account()`, which itself is RPC-only.
    """
    source = read_source(SOLANA_DIRECT)

    # No Supabase / table reads at the tx-construction surface.
    forbidden = [
        r"from\s+supabase",
        r"import\s+supabase",
        r"\.table\(",
        r"\.from_\(['\"]indexed_",
        r"get_supabase_client",
    ]
    hits: list[str] = []
    for pattern in forbidden:
        for lineno, line in grep_source(SOLANA_DIRECT, pattern):
            hits.append(f"{SOLANA_DIRECT}:{lineno} {line.strip()}")
    assert not hits, (
        "§10.1 drift — tx construction path pulls indexer/Supabase data:\n"
        "  " + "\n  ".join(hits)
    )

    # Positive: the canonical RPC reader exists.
    assert "async def get_program_config_account(" in source, (
        "§10.1 drift — get_program_config_account (RPC reader) missing "
        f"from {SOLANA_DIRECT}"
    )

    # tx_builder.py must resolve treasury via that RPC reader — not via
    # a Supabase table lookup.
    tx_builder_source = read_source("services/tx_builder.py")
    assert "get_program_config_account(" in tx_builder_source, (
        "§10.1 drift — services/tx_builder.py no longer resolves treasury "
        "via get_program_config_account(); review tx-construction authority"
    )
    for pattern in [r"\.table\(", r"\.from_\(['\"]indexed_"]:
        matches = grep_source("services/tx_builder.py", pattern)
        assert not matches, (
            "§10.1 drift — services/tx_builder.py reads indexer tables for "
            f"tx construction: {matches}"
        )


# ---------------------------------------------------------------------------
# §10.1 — Leaderboard Direction
# ---------------------------------------------------------------------------


def test_section_10_1_leaderboard_sync_does_not_claim_db_is_source_of_truth() -> None:
    """§10.1 Projection-Direction — STATUS: PASS.

    BACKEND_TRUTHS §10.1 and §5.3: the chain is truth, the projection is a
    cache. The indexer is downstream of on-chain state. It may lag. When it
    lags, UX surfaces must show truth is pending — NEVER fabricate it, and
    NEVER treat the cache as authoritative over the chain.

    This gate prevents the old inverted framing from returning. The chain
    is truth; DB mirrors the chain.
    """
    source = read_source(LEADERBOARD_SYNC)

    # The drift is concentrated in two well-known phrases. Match either.
    drift_patterns = [
        r"DB\s*\([^)]*vault_leaderboards[^)]*\)\s+is\s+the\s+source\s+of\s+truth",
        r"source\s+of\s+truth.*leaderboard\s+entries",
        r"Reads\s+current\s+DB\s+leaderboard\s+\(source\s+of\s+truth\)",
    ]
    drifts: list[str] = []
    for pattern in drift_patterns:
        compiled = re.compile(pattern, re.IGNORECASE)
        for idx, line in enumerate(source.splitlines(), start=1):
            if compiled.search(line):
                drifts.append(f"{LEADERBOARD_SYNC}:{idx} {line.strip()}")

    assert not drifts, (
        "§10.1 Leaderboard Direction DRIFT — leaderboard_sync_service.py "
        "docstring claims DB is the source of truth for leaderboard "
        "entries. §10.1 is explicit: chain is truth, projection is a "
        "cache. Lines:\n  " + "\n  ".join(drifts)
    )


def test_section_10_1_backend_runtime_does_not_call_legacy_leaderboard_writers() -> None:
    """§10.1 Projection-Direction — STATUS: PASS.

    The backend runtime must not call DB-native Record Board writer RPCs.
    Record Board updates happen on-chain; backend repair is reindex from
    chain/indexer projection, never invoking a Supabase function that mutates
    ``vault_leaderboards`` as truth.
    """
    offenders: list[str] = []

    for path in sorted(backend_root().rglob("*.py")):
        rel_path = path.relative_to(backend_root())
        text = path.read_text(encoding="utf-8")
        for rpc_name in LEGACY_LEADERBOARD_WRITE_RPC_NAMES:
            pattern = rf"\.rpc\(\s*['\"]{re.escape(rpc_name)}['\"]"
            for match in re.finditer(pattern, text):
                lineno = text.count("\n", 0, match.start()) + 1
                offenders.append(f"{rel_path}:{lineno} calls legacy RPC {rpc_name}")

        wrapper_call = re.compile(r"\.update_leaderboard_with_notifications\s*\(")
        for match in wrapper_call.finditer(text):
            lineno = text.count("\n", 0, match.start()) + 1
            offenders.append(
                f"{rel_path}:{lineno} calls legacy update_leaderboard_with_notifications wrapper"
            )

    assert not offenders, (
        "§10.1 drift — backend runtime calls DB-native Record Board writer "
        "RPCs:\n  " + "\n  ".join(offenders)
    )


def test_section_10_1_backend_runtime_does_not_write_vault_leaderboards() -> None:
    """§10.1 Projection-Direction — STATUS: PASS.

    ``vault_leaderboards`` is legacy read cache only. Backend runtime may read
    it for compatibility verification, but must not insert/update/upsert/delete
    it as an authoritative Record Board source.
    """
    offenders: list[str] = []
    supabase_write = re.compile(r"\.(insert|update|upsert|delete)\s*\(")
    raw_sql_write = re.compile(
        r"\b(INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+vault_leaderboards\b",
        re.IGNORECASE,
    )

    for path in sorted(backend_root().rglob("*.py")):
        rel_path = path.relative_to(backend_root())
        lines = path.read_text(encoding="utf-8").splitlines()
        for idx, line in enumerate(lines, start=1):
            if raw_sql_write.search(line):
                offenders.append(f"{rel_path}:{idx} raw SQL writes vault_leaderboards")

            if "vault_leaderboards" not in line:
                continue
            if ".from_(" not in line and ".table(" not in line:
                continue

            call_window = "\n".join(lines[idx - 1 : idx + 6])
            if supabase_write.search(call_window):
                offenders.append(
                    f"{rel_path}:{idx} Supabase write chain targets vault_leaderboards"
                )

    assert not offenders, (
        "§10.1 drift — backend runtime writes legacy vault_leaderboards "
        "cache:\n  " + "\n  ".join(offenders)
    )


def test_section_10_1_legacy_leaderboard_write_sql_is_neutralized() -> None:
    """§10.1 Projection-Direction — STATUS: PASS.

    Historical migrations can define old functions, but the live migration
    chain must end by dropping/revoking those DB-native Record Board writers
    and installing a fail-closed table guard.
    """
    migration_path = (
        repo_root()
        / "backend"
        / "sql"
        / LEGACY_LEADERBOARD_SQL_MIGRATION
    )
    migration = migration_path.read_text(encoding="utf-8")

    required_fragments = [
        "DROP FUNCTION IF EXISTS record_vault_completion_with_best_time",
        "DROP FUNCTION IF EXISTS update_vault_leaderboard(TEXT, TEXT, INTEGER, INTEGER, UUID)",
        "DROP FUNCTION IF EXISTS update_vault_leaderboard(TEXT, TEXT, INTEGER, INTEGER, UUID, TIMESTAMPTZ)",
        "DROP FUNCTION IF EXISTS update_vault_leaderboard(TEXT, TEXT, INTEGER, INTEGER, UUID, TIMESTAMPTZ, TEXT, UUID)",
        "DROP FUNCTION IF EXISTS update_vault_leaderboard_with_notifications",
        "DROP FUNCTION IF EXISTS rebuild_vault_leaderboard",
        "DROP FUNCTION IF EXISTS rebuild_all_vault_leaderboards",
        "DROP FUNCTION IF EXISTS snapshot_vault_leaderboard",
        "DROP FUNCTION IF EXISTS snapshot_all_leaderboards_for_epoch",
        "CREATE TRIGGER trg_prevent_legacy_vault_leaderboards_write",
        "BEFORE INSERT OR UPDATE OR DELETE ON vault_leaderboards",
        "br.allow_legacy_leaderboard_projection_write",
    ]
    missing = [fragment for fragment in required_fragments if fragment not in migration]
    assert not missing, (
        f"{LEGACY_LEADERBOARD_SQL_MIGRATION} does not neutralize all legacy "
        "Record Board write surfaces. Missing fragments:\n  "
        + "\n  ".join(missing)
    )

    sql_dir = repo_root() / "backend" / "sql"
    recreate_pattern = re.compile(
        r"CREATE\s+OR\s+REPLACE\s+FUNCTION\s+"
        r"(record_vault_completion_with_best_time|update_vault_leaderboard|"
        r"update_vault_leaderboard_with_notifications|rebuild_vault_leaderboard|"
        r"rebuild_all_vault_leaderboards|snapshot_vault_leaderboard|"
        r"snapshot_all_leaderboards_for_epoch)\b",
        re.IGNORECASE,
    )
    recreations: list[str] = []
    for sql_path in sorted(sql_dir.glob("[0-9][0-9][0-9]_*.sql")):
        try:
            migration_number = int(sql_path.name.split("_", 1)[0])
        except ValueError:
            continue
        if migration_number < 87:
            continue
        text = sql_path.read_text(encoding="utf-8")
        for match in recreate_pattern.finditer(text):
            lineno = text.count("\n", 0, match.start()) + 1
            recreations.append(f"{sql_path.name}:{lineno} recreates {match.group(1)}")

    assert not recreations, (
        "§10.1 drift — a post-retirement migration recreates legacy DB-native "
        "Record Board writers:\n  " + "\n  ".join(recreations)
    )


def test_section_10_1_post_gate2_sql_drift_is_repaired() -> None:
    """§10.1 Projection-Direction — STATUS: PASS.

    Gate 2 exposed two live SQL drifts after the Record Board truth inversion:
    `get_vaults_needing_sync` returned a schema-dependent CHAR/VARCHAR
    signature where Supabase expected TEXT, and wallet notifications still
    inherited the older user_id-not-null table contract. The repair migration
    must keep sync as projection audit and make wallet-addressed notifications
    valid without reintroducing DB-native Record Board writes.
    """
    migration_path = repo_root() / "backend" / "sql" / POST_GATE2_SQL_REPAIR_MIGRATION
    migration = migration_path.read_text(encoding="utf-8")

    required_fragments = [
        "iv.signature_hex::TEXT AS vault_signature",
        "Projection-audit helper",
        "ALTER COLUMN user_id DROP NOT NULL",
        "notifications_user_or_wallet_check",
        "CHECK (user_id IS NOT NULL OR wallet IS NOT NULL)",
    ]
    missing = [fragment for fragment in required_fragments if fragment not in migration]
    assert not missing, (
        f"{POST_GATE2_SQL_REPAIR_MIGRATION} does not repair the post-Gate-2 "
        "SQL drift. Missing fragments:\n  " + "\n  ".join(missing)
    )


# ---------------------------------------------------------------------------
# §12 — Naming Discipline
# ---------------------------------------------------------------------------


def test_section_12_no_unguarded_segments_in_response_schemas() -> None:
    """§12 Naming — STATUS: PASS (with documented back-compat aliases).

    Canonical vocabulary in response schemas: ``Climb`` / ``climb_id`` /
    ``climbs`` (BACKEND_TRUTHS §12). The only allowed `segments:` /
    `segment_id` occurrences in `backend/app/routes/` are explicit
    back-compat aliases — flagged on the same line or clearly within a
    response file whose docstring declares the back-compat contract.

    The router `routes/climbs.py` is mounted at both `/climbs` (canonical)
    and `/segments` (compat alias) in `app/main.py`. Its field names keep
    the legacy shape so existing clients don't break during the rollout
    tracked under wdvr.8 + 0uv8.

    This test catches any NEW `segments:` / `segment_id` leaking outside
    `routes/climbs.py` without a back-compat comment.
    """
    routes_dir = backend_root() / "routes"
    offenders: list[str] = []

    # Any .py under routes/ that is not the declared back-compat router.
    for path in sorted(routes_dir.rglob("*.py")):
        rel = path.relative_to(backend_root())
        rel_str = rel.as_posix()

        # climbs.py is the declared back-compat surface — skip in full.
        if rel_str == "routes/climbs.py":
            continue

        text = path.read_text(encoding="utf-8")

        # Pydantic-style schema field definitions only: ``segments:`` or
        # ``segment_id:`` at the start of a stripped line (with optional
        # indentation), followed by a colon. Docstrings and HTML strings
        # use 'segments' as freeform prose and are out of scope.
        field_pattern = re.compile(
            r"^\s*(segments|segment_id)\s*:\s*\S", re.MULTILINE
        )
        for match in field_pattern.finditer(text):
            # Locate the full line for back-compat marker inspection.
            line_start = text.rfind("\n", 0, match.start()) + 1
            line_end = text.find("\n", match.end())
            if line_end == -1:
                line_end = len(text)
                line_text = text[line_start:]
            else:
                line_text = text[line_start:line_end]
            lineno = text.count("\n", 0, line_start) + 1

            # Back-compat marker on the same line or immediately above.
            prev_line_start = text.rfind("\n", 0, line_start - 1) + 1
            prev_line = text[prev_line_start:line_start - 1]
            if line_has_backcompat_marker(line_text) or line_has_backcompat_marker(
                prev_line
            ):
                continue

            offenders.append(f"{rel_str}:{lineno} {line_text.strip()}")

    assert not offenders, (
        "§12 Naming drift — response schemas outside routes/climbs.py use "
        "legacy 'segments'/'segment_id' without a back-compat marker:\n"
        "  " + "\n  ".join(offenders)
    )


def test_section_12_climbs_route_back_compat_alias_is_documented() -> None:
    """§12 Naming — STATUS: PASS.

    The one intentional exception (``routes/climbs.py``) must carry the
    back-compat declaration at the top of the module and must still be
    mounted at both `/climbs` and `/segments` from `main.py`. If either
    goes away, this guardrail would silently let other files follow.
    """
    climbs_source = read_source("routes/climbs.py")
    assert (
        "back-compat alias" in climbs_source or "compat alias" in climbs_source
    ), (
        "§12 Naming — routes/climbs.py must declare the back-compat "
        "contract in its module docstring so the exception is auditable"
    )

    main_source = read_source("main.py")
    assert 'include_router(climbs.router, prefix="/climbs")' in main_source, (
        "§12 Naming — main.py no longer mounts climbs.router at /climbs"
    )
    assert 'include_router(climbs.router, prefix="/segments")' in main_source, (
        "§12 Naming — main.py no longer mounts the /segments back-compat "
        "alias; either remove the back-compat marker in climbs.py or "
        "restore the alias mount"
    )
