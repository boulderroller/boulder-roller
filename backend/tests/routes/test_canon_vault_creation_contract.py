from __future__ import annotations

import os
import base64
from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from solders.hash import Hash
from solders.instruction import Instruction
from solders.keypair import Keypair
from solders.message import Message
from solders.pubkey import Pubkey
from solders.transaction import Transaction

os.environ.setdefault("ACCESS_TOKEN_SECRET", "test-access-secret")
os.environ.setdefault("REFRESH_TOKEN_SECRET", "test-refresh-secret")
os.environ.setdefault("AUTH_SIGNATURE_BYPASS", "true")
os.environ.setdefault("AUTH_AUDIENCE", "test-audience")

import app.routes.vaults as vault_routes
import app.routes.admin as admin_routes
from app.routes.vaults import CanonVaultPrepareRequest, CanonVaultSubmitRequest
from app.routes.climbs import (
    build_canon_climb_response,
    get_climb,
    get_climb_leaderboard,
    get_popular_climbs,
    list_climbs,
)
from app.client_contracts import ClimbSummary, VaultCreationAvailability
from app.services.canon_vault_activation import (
    CanonVaultSource,
    CanonVaultActivationError,
    require_canon_runtime_program,
    require_generated_canon_runtime_program,
    resolve_canon_vault_source,
)
from app.services.tx_builder import BuildTxResult, SubmittedTransactionPending


CLIMB_ROW_ID = UUID("11111111-1111-1111-1111-111111111111")
CANON_ID = UUID("22222222-2222-2222-2222-222222222222")
PROFILE_HASH = "a8f2861cb321b0dcded9c3ea0ddabb26ec8d5f7d33a771923c763fdd27de1b23"


def _source() -> CanonVaultSource:
    return CanonVaultSource(
        climb_id=CLIMB_ROW_ID,
        canon_id=CANON_ID,
        version=2,
        commitment_hex="01" + CANON_ID.hex + "0002" + ("00" * 13) + PROFILE_HASH,
        commitment_hash_hex="ab" * 32,
        profile_hash_hex=PROFILE_HASH,
        climb_pda=str(Pubkey.new_unique()),
        name="Ratified Climb",
        vert_m=10.0,
        distance_m=100,
        avg_gradient_pct=10.0,
    )


def _signed_build_result() -> tuple[BuildTxResult, str]:
    signer = Keypair()
    blockhash = Hash.new_unique()
    instruction = Instruction(Pubkey.new_unique(), b"canon", [])
    message = Message.new_with_blockhash([instruction], signer.pubkey(), blockhash)
    transaction = Transaction.new_unsigned(message)
    transaction.sign([signer], blockhash)
    encoded = base64.b64encode(bytes(transaction)).decode("utf-8")
    return (
        BuildTxResult(
            transaction=encoded,
            blockhash=str(blockhash),
            last_valid_block_height=500,
            message="Create Vault for Ratified Climb",
            vault_id=7,
            pda=str(Pubkey.new_unique()),
            activation_pda=str(Pubkey.new_unique()),
        ),
        str(transaction.signatures[0]),
    )


class _Query:
    def __init__(self, rows):
        self.rows = list(rows)
        self.filters = []
        self.row_range = slice(None)

    def select(self, _columns):
        return self

    def eq(self, column, value):
        self.filters.append((column, value))
        return self

    def in_(self, column, values):
        allowed = {str(value) for value in values}
        self.rows = [row for row in self.rows if str(row.get(column)) in allowed]
        return self

    def limit(self, _limit):
        return self

    def order(self, _column, **_kwargs):
        return self

    def range(self, start, end):
        self.row_range = slice(start, end + 1)
        return self

    def ilike(self, column, pattern):
        needle = pattern.strip("%").lower()
        self.rows = [
            row for row in self.rows if needle in str(row.get(column) or "").lower()
        ]
        return self

    def execute(self):
        filtered = [
            row
            for row in self.rows
            if all(str(row.get(column)) == str(value) for column, value in self.filters)
        ]
        return SimpleNamespace(data=filtered[self.row_range])


class _Client:
    def __init__(self, tables):
        self.tables = tables

    def from_(self, table):
        return _Query(self.tables.get(table, []))

    def rpc(self, name, _params):
        return _Query(self.tables.get(f"rpc:{name}", []))


def _registry_row(**overrides):
    row = {
        "id": str(CLIMB_ROW_ID),
        "canon_id": str(CANON_ID),
        "version": 2,
        "status": "ratified",
        "display_name": "Ratified Climb",
        "canonical_profile": [
            {"dist_m": 0.0, "elev_m": 100.0},
            {"dist_m": 100.0, "elev_m": 110.0},
        ],
        "length_m": 100.0,
        "vert_m": 10.0,
        "avg_gradient_pct": 10.0,
        "record_continuity_policy": "new_record_board",
        "provenance": {
            "canonical_profile_hash": {
                "algorithm": "blake3_canonical_profile_v1",
                "value": PROFILE_HASH,
            }
        },
    }
    row.update(overrides)
    return row


def _indexed_climb_row(**overrides):
    row = {
        "canon_climb_id": str(CLIMB_ROW_ID),
        "pda": "climb-pda",
        "canon_commitment_hex": (
            "01" + CANON_ID.hex + "0002" + ("00" * 13) + PROFILE_HASH
        ),
        "canonical_profile_hash_hex": PROFILE_HASH,
        "canon_version": 2,
        "record_continuity_policy": "new_record_board",
        "successor_climb_pda": None,
        "vault_pda": None,
        "name": "Ratified Climb",
        "vert_m": 10.0,
        "distance_m": 100,
        "avg_gradient_pct": 10.0,
        "quarantined": False,
    }
    row.update(overrides)
    return row


def test_prepare_and_submit_models_expose_only_server_authoritative_seams() -> None:
    prepare = CanonVaultPrepareRequest(
        climb_id=CLIMB_ROW_ID,
        payment_method="dung",
        client_request_id="request-1",
    )
    submit = CanonVaultSubmitRequest(
        preparation_id=UUID("33333333-3333-3333-3333-333333333333"),
        signed_transaction="signed-b64",
    )

    assert prepare.climb_id == CLIMB_ROW_ID
    assert submit.signed_transaction == "signed-b64"
    with pytest.raises(ValidationError, match="signature_hex"):
        CanonVaultPrepareRequest(
            climb_id=CLIMB_ROW_ID,
            payment_method="dung",
            signature_hex="01" * 64,
        )
    with pytest.raises(ValidationError, match="climb_id"):
        CanonVaultSubmitRequest(
            preparation_id=submit.preparation_id,
            signed_transaction="signed-b64",
            climb_id=CLIMB_ROW_ID,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("payment_method", "builder_method"),
    [
        ("dung", "build_create_vault_tx"),
        ("cal_usdc", "build_create_vault_with_usdc_tx"),
    ],
)
async def test_canon_builder_selects_exact_instruction_variant_without_identity_args(
    monkeypatch: pytest.MonkeyPatch,
    payment_method: str,
    builder_method: str,
) -> None:
    result, _ = _signed_build_result()
    builder = MagicMock()
    builder.build_create_vault_tx = AsyncMock(return_value=result)
    builder.build_create_vault_with_usdc_tx = AsyncMock(return_value=result)
    monkeypatch.setattr(vault_routes, "get_tx_builder", lambda: builder)
    source = _source()

    observed = await vault_routes._build_canon_vault_transaction(
        source=source,
        creator_wallet="wallet-1",
        payment_method=payment_method,
    )

    assert observed is result
    selected = getattr(builder, builder_method)
    selected.assert_awaited_once_with(
        user_wallet="wallet-1",
        climb_pda=source.climb_pda,
        display_name=source.name,
        blockhash=None,
        last_valid_block_height=None,
        vault_id=None,
    )
    other = (
        builder.build_create_vault_with_usdc_tx
        if builder_method == "build_create_vault_tx"
        else builder.build_create_vault_tx
    )
    other.assert_not_awaited()


@pytest.mark.asyncio
async def test_canon_prepare_reserves_the_exact_serialized_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _source()
    result, _ = _signed_build_result()
    preparation_id = uuid4()
    build = AsyncMock(return_value=result)
    reserve = MagicMock(return_value=preparation_id)
    builder = MagicMock()
    monkeypatch.setattr(vault_routes, "require_generated_canon_runtime_program", lambda: None)
    monkeypatch.setattr(vault_routes, "resolve_canon_vault_source", lambda **_: source)
    monkeypatch.setattr(vault_routes, "_build_canon_vault_transaction", build)
    monkeypatch.setattr(vault_routes, "get_tx_builder", lambda: builder)
    monkeypatch.setattr(
        vault_routes,
        "load_canon_vault_release_candidate",
        lambda **_: None,
    )
    monkeypatch.setattr(vault_routes, "reserve_canon_vault_activation", reserve)

    handler = getattr(vault_routes.prepare_canon_vault, "__wrapped__", vault_routes.prepare_canon_vault)
    response = await handler(
        vault_request=CanonVaultPrepareRequest(
            climb_id=source.climb_id,
            payment_method="dung",
            client_request_id="request-1",
        ),
        request=MagicMock(),
        current_user=SimpleNamespace(wallet="wallet-1"),
        repo=SimpleNamespace(client=MagicMock()),
    )

    assert response.preparation_id == preparation_id
    assert response.transaction == result.transaction
    assert response.canon_commitment_hex == source.commitment_hex
    reserve.assert_called_once_with(
        client=ANY,
        source=source,
        creator_wallet="wallet-1",
        payment_method="dung",
        client_request_id="request-1",
        vault_id=7,
        vault_pda=result.pda,
        vault_activation_pda=result.activation_pda,
        blockhash=result.blockhash,
        last_valid_block_height=500,
    )


@pytest.mark.asyncio
async def test_expired_abandoned_reservation_releases_only_after_finalized_absence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _source()
    result, _ = _signed_build_result()
    old_preparation_id = uuid4()
    new_preparation_id = uuid4()
    candidate = {
        "preparation_id": str(old_preparation_id),
        "canon_climb_id": str(source.climb_id),
        "creator_wallet": "wallet-old",
        "client_request_id": "request-old",
        "payment_method": "dung",
        "canon_commitment_hex": source.commitment_hex,
        "commitment_hash_hex": source.commitment_hash_hex,
        "climb_pda": source.climb_pda,
        "vault_id": 7,
        "vault_pda": result.pda,
        "vault_activation_pda": result.activation_pda,
        "prepared_blockhash": result.blockhash,
        "last_valid_block_height": 500,
        "activation_status": "confirmed",
    }
    builder = MagicMock()
    builder.get_finalized_block_height = AsyncMock(return_value=501)
    builder.observe_finalized_canon_reservation_absence = AsyncMock(
        return_value=SimpleNamespace(slot=777, block_height=501)
    )
    release = MagicMock(return_value=True)
    reserve = MagicMock(return_value=new_preparation_id)
    monkeypatch.setattr(vault_routes, "require_generated_canon_runtime_program", lambda: None)
    monkeypatch.setattr(vault_routes, "resolve_canon_vault_source", lambda **_: source)
    monkeypatch.setattr(
        vault_routes,
        "_build_canon_vault_transaction",
        AsyncMock(return_value=result),
    )
    monkeypatch.setattr(vault_routes, "get_tx_builder", lambda: builder)
    monkeypatch.setattr(
        vault_routes,
        "load_canon_vault_release_candidate",
        lambda **_: candidate,
    )
    monkeypatch.setattr(
        vault_routes,
        "release_canon_vault_activation_after_absence",
        release,
    )
    monkeypatch.setattr(vault_routes, "reserve_canon_vault_activation", reserve)

    handler = getattr(
        vault_routes.prepare_canon_vault,
        "__wrapped__",
        vault_routes.prepare_canon_vault,
    )
    response = await handler(
        vault_request=CanonVaultPrepareRequest(
            climb_id=source.climb_id,
            payment_method="dung",
            client_request_id="request-new",
        ),
        request=MagicMock(),
        current_user=SimpleNamespace(wallet="wallet-new"),
        repo=SimpleNamespace(client=MagicMock()),
    )

    assert response.preparation_id == new_preparation_id
    builder.observe_finalized_canon_reservation_absence.assert_awaited_once_with(
        climb_pda=source.climb_pda,
        vault_pda=result.pda,
        vault_activation_pda=result.activation_pda,
        canon_commitment_hex=source.commitment_hex,
        commitment_hash_hex=source.commitment_hash_hex,
    )
    release.assert_called_once_with(
        client=ANY,
        preparation_id=old_preparation_id,
        creator_wallet="wallet-old",
        observed_finalized_slot=777,
        observed_finalized_block_height=501,
        reason=ANY,
    )
    reserve.assert_called_once()


@pytest.mark.asyncio
async def test_live_idempotent_reservation_reuses_exact_blockhash_and_pdas(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _source()
    result, _ = _signed_build_result()
    preparation_id = uuid4()
    candidate = {
        "preparation_id": str(preparation_id),
        "canon_climb_id": str(source.climb_id),
        "creator_wallet": "wallet-1",
        "client_request_id": "request-1",
        "payment_method": "dung",
        "canon_commitment_hex": source.commitment_hex,
        "commitment_hash_hex": source.commitment_hash_hex,
        "climb_pda": source.climb_pda,
        "vault_id": 7,
        "vault_pda": result.pda,
        "vault_activation_pda": result.activation_pda,
        "prepared_blockhash": result.blockhash,
        "last_valid_block_height": 500,
        "activation_status": "reserved",
    }
    build = AsyncMock(side_effect=[result, result])
    builder = MagicMock()
    builder.get_finalized_block_height = AsyncMock(return_value=500)
    builder.observe_finalized_canon_reservation_absence = AsyncMock()
    monkeypatch.setattr(vault_routes, "require_generated_canon_runtime_program", lambda: None)
    monkeypatch.setattr(vault_routes, "resolve_canon_vault_source", lambda **_: source)
    monkeypatch.setattr(vault_routes, "_build_canon_vault_transaction", build)
    monkeypatch.setattr(vault_routes, "get_tx_builder", lambda: builder)
    monkeypatch.setattr(
        vault_routes,
        "load_canon_vault_release_candidate",
        lambda **_: candidate,
    )
    monkeypatch.setattr(
        vault_routes,
        "reserve_canon_vault_activation",
        MagicMock(return_value=preparation_id),
    )

    handler = getattr(
        vault_routes.prepare_canon_vault,
        "__wrapped__",
        vault_routes.prepare_canon_vault,
    )
    response = await handler(
        vault_request=CanonVaultPrepareRequest(
            climb_id=source.climb_id,
            payment_method="dung",
            client_request_id="request-1",
        ),
        request=MagicMock(),
        current_user=SimpleNamespace(wallet="wallet-1"),
        repo=SimpleNamespace(client=MagicMock()),
    )

    assert response.preparation_id == preparation_id
    assert build.await_count == 2
    assert build.await_args_list[1].kwargs["blockhash"] == Hash.from_string(
        result.blockhash
    )
    assert build.await_args_list[1].kwargs["last_valid_block_height"] == 500
    builder.observe_finalized_canon_reservation_absence.assert_not_awaited()

@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("runtime_state", "submission_pending", "expected_state", "expected_confirmation"),
    [
        ("active", False, "active", "finalized"),
        ("reserved", False, "pending", "confirmed"),
        ("reserved", True, "pending", "pending"),
    ],
)
async def test_canon_submit_requires_exact_message_and_never_promotes_queue_state(
    monkeypatch: pytest.MonkeyPatch,
    runtime_state: str,
    submission_pending: bool,
    expected_state: str,
    expected_confirmation: str,
) -> None:
    source = _source()
    result, tx_signature = _signed_build_result()
    preparation_id = uuid4()
    preparation = {
        "preparation_id": str(preparation_id),
        "canon_climb_id": str(source.climb_id),
        "creator_wallet": "wallet-1",
        "payment_method": "dung",
        "canon_commitment_hex": source.commitment_hex,
        "commitment_hash_hex": source.commitment_hash_hex,
        "climb_pda": source.climb_pda,
        "vault_id": 7,
        "vault_pda": result.pda,
        "vault_activation_pda": result.activation_pda,
        "prepared_blockhash": result.blockhash,
        "last_valid_block_height": 500,
        "activation_status": "reserved",
    }
    builder = MagicMock()
    if submission_pending:
        builder.submit_signed_transaction = AsyncMock(
            side_effect=SubmittedTransactionPending(tx_signature, "pending")
        )
    else:
        builder.submit_signed_transaction = AsyncMock(return_value=tx_signature)
    confirm = MagicMock()
    monkeypatch.setattr(vault_routes, "require_generated_canon_runtime_program", lambda: None)
    monkeypatch.setattr(vault_routes, "load_canon_vault_preparation", lambda **_: preparation)
    monkeypatch.setattr(vault_routes, "resolve_canon_vault_source", lambda **_: source)
    monkeypatch.setattr(vault_routes, "_build_canon_vault_transaction", AsyncMock(return_value=result))
    monkeypatch.setattr(
        vault_routes,
        "_decode_signed_transaction_or_400",
        lambda value: Transaction.from_bytes(base64.b64decode(value)),
    )
    monkeypatch.setattr(vault_routes, "get_tx_builder", lambda: builder)
    monkeypatch.setattr(vault_routes, "confirm_canon_vault_activation", confirm)
    monkeypatch.setattr(
        vault_routes,
        "load_canon_climb_runtime_states",
        lambda **_: {str(source.climb_id): runtime_state},
    )

    handler = getattr(vault_routes.submit_canon_vault, "__wrapped__", vault_routes.submit_canon_vault)
    response = await handler(
        vault_request=CanonVaultSubmitRequest(
            preparation_id=preparation_id,
            signed_transaction=result.transaction,
        ),
        request=MagicMock(),
        current_user=SimpleNamespace(wallet="wallet-1"),
        repo=SimpleNamespace(client=MagicMock()),
    )

    assert response.activation_state == expected_state
    assert response.projection_status == expected_state
    assert response.confirmation_status == expected_confirmation
    assert "recorded" not in response.model_dump().values()
    confirm.assert_called_once()


@pytest.mark.asyncio
async def test_canon_submit_rejects_a_different_signed_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _source()
    expected, _ = _signed_build_result()
    submitted, _ = _signed_build_result()
    preparation_id = uuid4()
    preparation = {
        "canon_climb_id": str(source.climb_id),
        "payment_method": "dung",
        "canon_commitment_hex": source.commitment_hex,
        "commitment_hash_hex": source.commitment_hash_hex,
        "climb_pda": source.climb_pda,
        "vault_id": 7,
        "vault_pda": expected.pda,
        "vault_activation_pda": expected.activation_pda,
        "prepared_blockhash": submitted.blockhash,
        "last_valid_block_height": 500,
    }
    monkeypatch.setattr(vault_routes, "require_generated_canon_runtime_program", lambda: None)
    monkeypatch.setattr(vault_routes, "load_canon_vault_preparation", lambda **_: preparation)
    monkeypatch.setattr(vault_routes, "resolve_canon_vault_source", lambda **_: source)
    monkeypatch.setattr(vault_routes, "_build_canon_vault_transaction", AsyncMock(return_value=expected))
    monkeypatch.setattr(
        vault_routes,
        "_decode_signed_transaction_or_400",
        lambda value: Transaction.from_bytes(base64.b64decode(value)),
    )

    handler = getattr(vault_routes.submit_canon_vault, "__wrapped__", vault_routes.submit_canon_vault)
    with pytest.raises(vault_routes.HTTPException, match="do not match"):
        await handler(
            vault_request=CanonVaultSubmitRequest(
                preparation_id=preparation_id,
                signed_transaction=submitted.transaction,
            ),
            request=MagicMock(),
            current_user=SimpleNamespace(wallet="wallet-1"),
            repo=SimpleNamespace(client=MagicMock()),
        )


@pytest.mark.asyncio
async def test_v4b_disables_detector_signature_matching_before_repository_access() -> None:
    vault_repo = MagicMock()
    vault_repo.find_vaults_by_signatures = AsyncMock()
    handler = getattr(vault_routes.match_signatures, "__wrapped__", vault_routes.match_signatures)

    with pytest.raises(vault_routes.HTTPException) as exc_info:
        await handler(
            match_request=vault_routes.SignatureMatchRequest(signatures=["ab" * 32]),
            request=MagicMock(),
            current_user=SimpleNamespace(wallet="wallet-1"),
            vault_repo=vault_repo,
        )

    assert exc_info.value.status_code == 410
    vault_repo.find_vaults_by_signatures.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("route_name", ["prepare_create_vault", "create_vault"])
async def test_v4b_disables_legacy_arbitrary_signature_creation_before_access(
    route_name: str,
) -> None:
    vault_repo = MagicMock()
    vault_repo.get_vault_by_signature = AsyncMock()
    repo = SimpleNamespace(client=MagicMock())
    request_model = vault_routes.CreateVaultRequest(
        signature_hex="01" * 64,
        name="Legacy Detector Vault",
        vert_m=10,
        distance_m=100,
        avg_gradient_pct=10,
    )
    route = getattr(vault_routes, route_name)
    handler = getattr(route, "__wrapped__", route)

    with pytest.raises(vault_routes.HTTPException) as exc_info:
        await handler(
            vault_request=request_model,
            request=MagicMock(),
            current_user=SimpleNamespace(wallet="wallet-1"),
            vault_repo=vault_repo,
            repo=repo,
        )

    assert exc_info.value.status_code == 410
    vault_repo.get_vault_by_signature.assert_not_awaited()
    repo.client.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("route_name", "extra_kwargs"),
    [
        ("admin_seed_activate_vault", {"vault_id": 7}),
        ("admin_seed_activate_all", {}),
    ],
)
async def test_v4b_disables_legacy_seed_activation_before_service_access(
    monkeypatch: pytest.MonkeyPatch,
    route_name: str,
    extra_kwargs: dict,
) -> None:
    get_service = MagicMock()
    monkeypatch.setattr(vault_routes, "_get_activation_service", get_service)
    route = getattr(vault_routes, route_name)
    handler = getattr(route, "__wrapped__", route)

    with pytest.raises(vault_routes.HTTPException) as exc_info:
        await handler(
            request=MagicMock(),
            admin_ctx=(uuid4(), "admin"),
            repo=SimpleNamespace(client=MagicMock()),
            **extra_kwargs,
        )

    assert exc_info.value.status_code == 410
    get_service.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("route_name", "extra_kwargs"),
    [
        (
            "trigger_vault_backfill",
            {"vault_id": 7, "body": admin_routes.BackfillRequest(priority=0)},
        ),
        ("trigger_all_pending_backfills", {"force": False}),
    ],
)
async def test_v4b_disables_legacy_backfill_before_repository_or_queue_access(
    monkeypatch: pytest.MonkeyPatch,
    route_name: str,
    extra_kwargs: dict,
) -> None:
    enqueue = AsyncMock()
    monkeypatch.setattr(admin_routes, "enqueue_vault_backfill_job", enqueue)
    client = MagicMock()
    route = getattr(admin_routes, route_name)
    handler = getattr(route, "__wrapped__", route)

    with pytest.raises(admin_routes.HTTPException) as exc_info:
        await handler(
            request=SimpleNamespace(client=None, headers={}),
            admin_ctx=(uuid4(), "admin"),
            repo=SimpleNamespace(client=client),
            **extra_kwargs,
        )

    assert exc_info.value.status_code == 410
    client.from_.assert_not_called()
    enqueue.assert_not_awaited()


def test_climb_contract_uses_immutable_registry_row_id_and_explicit_lineage() -> None:
    summary = ClimbSummary(
        id=str(CLIMB_ROW_ID),
        canon_id=CANON_ID,
        version=2,
        revision_state="current",
        name="Ratified Climb",
        vault_creation=VaultCreationAvailability(
            state="available",
            payment_methods=["dung", "cal_usdc"],
        ),
    )

    assert summary.id == str(CLIMB_ROW_ID)
    assert summary.canon_id == CANON_ID
    assert summary.version == 2
    assert summary.vault_creation.state == "available"


def test_canon_climb_response_never_uses_vault_or_detector_id_as_climb_id() -> None:
    response = build_canon_climb_response(
        _registry_row(centerline_polyline=None),
        indexed_climb={"pda": "climb-pda"},
        vault_row={"id": 42, "signature_hex": "01" * 64, "total_completions": 3},
    )

    assert response.id == str(CLIMB_ROW_ID)
    assert response.canon_id == CANON_ID
    assert response.version == 2
    assert response.vault_economy.vault_id == 42
    assert response.vault_creation.state == "active"


def test_canon_climb_response_rejects_projection_runtime_mismatch() -> None:
    with pytest.raises(ValueError, match="projection and activation"):
        build_canon_climb_response(
            _registry_row(),
            indexed_climb={"pda": "climb-pda"},
            vault_row=None,
            runtime_state="active",
        )


@pytest.mark.asyncio
async def test_canon_leaderboard_returns_empty_board_when_ratified_row_has_no_vault() -> None:
    client = _Client(
        {
            "canon_climbs": [_registry_row()],
            "indexed_climbs": [],
            "climb_vault": [
                {
                    "id": str(CLIMB_ROW_ID),
                    "name": "Legacy row must not authorize this request",
                    "signature_hex": "ff" * 64,
                }
            ],
        }
    )

    response = await get_climb_leaderboard(
        climb_id=str(CLIMB_ROW_ID),
        request=SimpleNamespace(
            url=SimpleNamespace(path=f"/climbs/{CLIMB_ROW_ID}/leaderboard")
        ),
        repo=SimpleNamespace(client=client),
    )

    assert response["climb_id"] == str(CLIMB_ROW_ID)
    assert response["climb_name"] == "Ratified Climb"
    assert response["vault_id"] is None
    assert response["entries"] == []


@pytest.mark.asyncio
async def test_canon_leaderboard_does_not_surface_vault_without_active_runtime_proof() -> None:
    client = _Client(
        {
            "canon_climbs": [_registry_row()],
            "indexed_climbs": [
                {
                    "pda": "climb-pda",
                    "canon_climb_id": str(CLIMB_ROW_ID),
                    "vault_pda": "vault-pda",
                    "quarantined": False,
                }
            ],
            "indexed_vaults": [
                {
                    "id": 42,
                    "name": "Must stay hidden",
                    "signature_hex": "01" * 64,
                    "kom_holder": "wallet-kom",
                    "kom_time_s": 60,
                    "climb_pda": "climb-pda",
                    "canon_binding_status": "active",
                }
            ],
            "indexed_leaderboards": [
                {
                    "vault_id": 42,
                    "entries": [{"user": "wallet-kom", "time_s": 60}],
                }
            ],
            "rpc:get_canon_climb_runtime_states": [
                {
                    "canon_climb_id": str(CLIMB_ROW_ID),
                    "runtime_state": "available",
                }
            ],
        }
    )

    response = await get_climb_leaderboard(
        climb_id=str(CLIMB_ROW_ID),
        request=SimpleNamespace(
            url=SimpleNamespace(path=f"/climbs/{CLIMB_ROW_ID}/leaderboard")
        ),
        repo=SimpleNamespace(client=client),
    )

    assert response["climb_id"] == str(CLIMB_ROW_ID)
    assert response["vault_id"] is None
    assert response["entries"] == []


@pytest.mark.asyncio
async def test_canon_list_and_detail_surface_live_reservation_as_not_available() -> None:
    indexed = {
        "canon_climb_id": str(CLIMB_ROW_ID),
        "pda": "climb-pda",
        "vault_pda": None,
        "quarantined": False,
    }
    client = _Client(
        {
            "canon_climbs": [_registry_row(worthiness_score=90)],
            "indexed_climbs": [indexed],
            "indexed_vaults": [],
            "rpc:get_canon_climb_runtime_states": [
                {
                    "canon_climb_id": str(CLIMB_ROW_ID),
                    "runtime_state": "reserved",
                }
            ],
        }
    )
    repo = SimpleNamespace(client=client)

    listed = await list_climbs(q=None, bbox=None, limit=50, repo=repo)
    detailed = await get_climb(climb_id=str(CLIMB_ROW_ID), repo=repo)

    assert listed.climbs[0].vault_creation.state == "reserved"
    assert listed.climbs[0].vault_creation.payment_methods == []
    assert detailed.vault_creation.state == "reserved"
    assert detailed.vault_creation.payment_methods == []


@pytest.mark.asyncio
async def test_popular_climbs_use_registry_uuids_and_never_detector_fallback() -> None:
    client = _Client(
        {
            "indexed_vaults": [],
            "canon_climbs": [
                _registry_row(
                    centerline_polyline=None,
                    worthiness_score=90,
                    provenance={
                        "region": "Philadelphia",
                        "canonical_profile_hash": {
                            "algorithm": "blake3_canonical_profile_v1",
                            "value": PROFILE_HASH,
                        },
                    },
                )
            ],
            "climb_vault": [
                {"id": 42, "name": "Detector row must remain discovery-only"}
            ],
        }
    )

    response = await get_popular_climbs(limit=6, repo=SimpleNamespace(client=client))

    assert [climb.id for climb in response.climbs] == [str(CLIMB_ROW_ID)]
    assert response.climbs[0].has_vault is False
    assert all(climb.id != "42" for climb in response.climbs)


def test_v4b_runtime_gate_rejects_v4a_and_accepts_only_exact_family() -> None:
    with pytest.raises(CanonVaultActivationError, match="V4-B"):
        require_canon_runtime_program(program_version=0x44, family="V4-A")
    with pytest.raises(CanonVaultActivationError, match="V4-B"):
        require_canon_runtime_program(program_version=0x4B, family="V4-B-next")
    require_canon_runtime_program(program_version=0x4B, family="V4-B")


def test_v4b_runtime_gate_accepts_later_append_only_patches() -> None:
    # Main advanced to 0x4C (DUNG reservation) and stage 1 is 0x4D; both keep the canon ABI.
    for version in (0x4C, 0x4D):
        require_canon_runtime_program(program_version=version, family="V4-B")
    for version in (0x4A, 0x100, True, "0x4c"):
        with pytest.raises(CanonVaultActivationError, match="V4-B"):
            require_canon_runtime_program(program_version=version, family="V4-B")


def test_generated_program_version_can_create_canon_vaults() -> None:
    require_generated_canon_runtime_program()


def test_source_resolution_requires_exact_ratified_row_and_indexed_climb_binding() -> None:
    commitment = (
        "01"
        + CANON_ID.hex
        + "0002"
        + ("00" * 13)
        + PROFILE_HASH
    )
    client = _Client(
        {
            "canon_climbs": [_registry_row()],
            "indexed_climbs": [_indexed_climb_row()],
        }
    )

    source = resolve_canon_vault_source(client=client, climb_id=CLIMB_ROW_ID)

    assert source.climb_id == CLIMB_ROW_ID
    assert source.canon_id == CANON_ID
    assert source.version == 2
    assert source.commitment_hex == commitment
    assert source.climb_pda == "climb-pda"
    assert source.name == "Ratified Climb"
    assert source.vert_m == 10.0


@pytest.mark.parametrize(
    "indexed_overrides",
    [
        {"name": "Different Climb"},
        {"vert_m": 10.1},
        {"distance_m": 101},
        {"avg_gradient_pct": 10.01},
    ],
)
def test_source_resolution_rejects_onchain_name_or_metric_drift(
    indexed_overrides,
) -> None:
    client = _Client(
        {
            "canon_climbs": [_registry_row()],
            "indexed_climbs": [_indexed_climb_row(**indexed_overrides)],
        }
    )

    with pytest.raises(CanonVaultActivationError, match="metrics"):
        resolve_canon_vault_source(client=client, climb_id=CLIMB_ROW_ID)


def test_source_resolution_projects_real_compiler_metrics_half_up() -> None:
    client = _Client(
        {
            "canon_climbs": [
                _registry_row(
                    display_name="Jefferson Street / North Woodbine Avenue",
                    length_m=2031.31,
                    vert_m=87.36,
                    avg_gradient_pct=4.301,
                )
            ],
            "indexed_climbs": [
                _indexed_climb_row(
                    name="Jefferson Street / North Woodbine Avenue",
                    distance_m=2031,
                    vert_m=87.4,
                    avg_gradient_pct=4.3,
                )
            ],
        }
    )

    source = resolve_canon_vault_source(client=client, climb_id=CLIMB_ROW_ID)

    assert source.distance_m == 2031
    assert source.vert_m_fixed == 874
    assert source.avg_gradient_pct_fixed == 430
    assert source.vert_m == 87.4
    assert source.avg_gradient_pct == 4.3


def test_source_resolution_rejects_overprecise_indexed_projection() -> None:
    client = _Client(
        {
            "canon_climbs": [
                _registry_row(length_m=2031.31, vert_m=87.36, avg_gradient_pct=4.301)
            ],
            "indexed_climbs": [
                _indexed_climb_row(
                    distance_m=2031,
                    vert_m=87.36,
                    avg_gradient_pct=4.301,
                )
            ],
        }
    )

    with pytest.raises(CanonVaultActivationError, match="metrics"):
        resolve_canon_vault_source(client=client, climb_id=CLIMB_ROW_ID)


@pytest.mark.parametrize(
    ("registry_overrides", "message"),
    [
        ({"vert_m": 0}, "metrics"),
        ({"vert_m": 0.01}, "metrics"),
        ({"vert_m": (2**32) / 10 + 0.1}, "metrics"),
        ({"length_m": 2**32}, "metrics"),
        ({"avg_gradient_pct": 655.36}, "metrics"),
        ({"avg_gradient_pct": float("nan")}, "metrics"),
    ],
)
def test_source_resolution_rejects_metrics_that_cannot_fit_anchor_encoding(
    registry_overrides,
    message,
) -> None:
    commitment = "01" + CANON_ID.hex + "0002" + ("00" * 13) + PROFILE_HASH
    client = _Client(
        {
            "canon_climbs": [_registry_row(**registry_overrides)],
            "indexed_climbs": [_indexed_climb_row()],
        }
    )

    with pytest.raises(CanonVaultActivationError, match=message):
        resolve_canon_vault_source(client=client, climb_id=CLIMB_ROW_ID)


@pytest.mark.parametrize(
    ("registry_overrides", "indexed_rows", "message"),
    [
        ({"status": "candidate"}, [], "ratified"),
        ({}, [], "indexed V4-B Climb"),
        (
            {},
            [_indexed_climb_row(canon_commitment_hex="00" * 64)],
            "commitment",
        ),
    ],
)
def test_source_resolution_never_falls_back_to_detector_identity(
    registry_overrides,
    indexed_rows,
    message,
) -> None:
    client = _Client(
        {
            "canon_climbs": [_registry_row(**registry_overrides)],
            "indexed_climbs": indexed_rows,
            "patterns_climb": [{"id": "legacy-detector-row"}],
        }
    )

    with pytest.raises(CanonVaultActivationError, match=message):
        resolve_canon_vault_source(client=client, climb_id=CLIMB_ROW_ID)


def test_source_resolution_rejects_onchain_climb_with_registered_successor() -> None:
    commitment = (
        "01" + CANON_ID.hex + "0002" + ("00" * 13) + PROFILE_HASH
    )
    client = _Client(
        {
            "canon_climbs": [_registry_row()],
            "indexed_climbs": [
                _indexed_climb_row(
                    pda="old-climb-pda",
                    successor_climb_pda="new-climb-pda",
                )
            ],
        }
    )

    with pytest.raises(CanonVaultActivationError, match="commitment"):
        resolve_canon_vault_source(client=client, climb_id=CLIMB_ROW_ID)


def test_source_resolution_rejects_already_attached_onchain_climb() -> None:
    client = _Client(
        {
            "canon_climbs": [_registry_row()],
            "indexed_climbs": [_indexed_climb_row(vault_pda="already-attached-vault")],
        }
    )

    with pytest.raises(CanonVaultActivationError, match="already attached"):
        resolve_canon_vault_source(client=client, climb_id=CLIMB_ROW_ID)
