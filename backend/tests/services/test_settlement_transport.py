from __future__ import annotations

import struct
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from solders.address_lookup_table_account import AddressLookupTable, LookupTableMeta
from solders.address_lookup_table_account import derive_lookup_table_address
from solders.instruction import AccountMeta
from solders.keypair import Keypair
from solders.pubkey import Pubkey

from app.services.settlement_transport import (
    LookupTableGeneration,
    SettlementTransportManager,
    SettlementTransportStaleError,
    _make_create_lookup_table_ix,
    _make_extend_lookup_table_ix,
    validate_frozen_settlement_transport,
)
from app.solana_direct import (
    DirectConfig,
    SETTLEMENT_COMPUTE_UNIT_LIMIT,
    SettlementDistributionPlan,
    make_distribute_epoch_rewards_ix,
)


def _config() -> DirectConfig:
    return DirectConfig(
        rpc_url="http://example.invalid",
        program_id=Pubkey.new_unique(),
        payer=Keypair(),
        backend_authority=Keypair(),
        dung_mint_address=Pubkey.new_unique(),
    )


def _full_distribution(config: DirectConfig):
    extra = [
        AccountMeta(Pubkey.new_unique(), is_signer=False, is_writable=True)
        for _ in range(21)
    ]
    return make_distribute_epoch_rewards_ix(
        authority=config.backend_authority.pubkey(),
        vault_id=42,
        settlement_week=10,
        pol_account=Pubkey.new_unique(),
        protocol_treasury=Pubkey.new_unique(),
        dung_mint=config.dung_mint_address,
        program_id=config.program_id,
        local_legend=Pubkey.new_unique(),
        extra_accounts=extra,
    )


def test_lookup_table_instruction_encoding_matches_solana_abi() -> None:
    authority = Pubkey.new_unique()
    payer = Pubkey.new_unique()
    create, address = _make_create_lookup_table_ix(
        authority=authority,
        payer=payer,
        recent_slot=123,
    )

    assert create.data[:12] == struct.pack("<IQ", 0, 123)
    assert create.data[12] in range(256)
    assert create.accounts[0].pubkey == address
    assert create.accounts[1].pubkey == authority
    assert create.accounts[2].pubkey == payer

    addresses = [Pubkey.new_unique(), Pubkey.new_unique()]
    extend = _make_extend_lookup_table_ix(
        lookup_table=address,
        authority=authority,
        payer=payer,
        addresses=addresses,
    )
    assert extend.data == (
        struct.pack("<IQ", 2, 2) + bytes(addresses[0]) + bytes(addresses[1])
    )


@pytest.mark.asyncio
async def test_transport_manager_extends_full_manifest_and_freezes_sub_900_bytes() -> None:
    config = _config()
    instruction = _full_distribution(config)
    distribution = SettlementDistributionPlan(
        instruction=instruction,
        recipient_ata_instructions=(),
        leaderboard_recipient_count=10,
        local_legend_recipient_count=1,
        stake_inventory_count=10,
        recipient_token_accounts=(
            (
                Pubkey.new_unique(),
                Pubkey.new_unique(),
                config.dung_mint_address,
            ),
        ),
    )
    generation = LookupTableGeneration(
        id="generation-1",
        vault_id=42,
        program_id=str(config.program_id),
        generation=1,
        lookup_table_address=derive_lookup_table_address(
            config.payer.pubkey(), 99
        )[0],
        authority=config.payer.pubkey(),
        recent_slot=99,
        status="planned",
        create_tx_signature=None,
    )
    empty_state = AddressLookupTable(
        LookupTableMeta(
            last_extended_slot=0,
            authority=config.payer.pubkey(),
        ),
        [],
    )
    required = list({meta.pubkey: None for meta in instruction.accounts if not meta.is_signer})
    ready_state = AddressLookupTable(
        LookupTableMeta(
            last_extended_slot=100,
            authority=config.payer.pubkey(),
        ),
        required,
    )
    manager = SettlementTransportManager(db=object(), config=config)
    manager._get_or_plan = AsyncMock(return_value=generation)
    frozen_plans: list[dict] = []

    async def freeze_plan(plan: dict) -> None:
        frozen_plans.append(plan)

    async def create_after_freeze(*args, **kwargs):
        assert len(frozen_plans) == 1
        return empty_state, "create-signature"

    manager._create_if_missing = AsyncMock(side_effect=create_after_freeze)
    submit = AsyncMock(
        return_value=SimpleNamespace(
            failed=False,
            signature="extend-signature",
            error=None,
            status="finalized",
        )
    )
    record = AsyncMock(return_value=SimpleNamespace(data=True))

    with (
        patch(
            "app.services.settlement_transport._fetch_lookup_table_state",
            new=AsyncMock(return_value=(ready_state, 101)),
        ),
        patch(
            "app.services.settlement_transport.submit_and_confirm",
            new=submit,
        ),
        patch("app.services.settlement_transport._rpc", new=record),
    ):
        plan = await manager.prepare(
            vault_id=42,
            settlement_week=10,
            distribution=distribution,
            compute_unit_limit=SETTLEMENT_COMPUTE_UNIT_LIMIT,
            on_plan=freeze_plan,
        )

    assert submit.await_count == 2
    assert plan["transaction_version"] == "0"
    assert plan["stake_inventory_count"] == "10"
    assert int(plan["planned_serialized_bytes"]) <= 900
    assert len(plan["manifest_sha256"]) == 64
    assert frozen_plans[0]["expected_manifest_sha256"] == plan["manifest_sha256"]
    assert len(frozen_plans[0]["recipient_token_accounts"]) == 1
    assert record.await_args.args[1] == "br_record_settlement_lookup_table_ready"


@pytest.mark.asyncio
async def test_frozen_transport_rejects_account_manifest_drift() -> None:
    config = _config()
    instruction = _full_distribution(config)
    required = list({meta.pubkey: None for meta in instruction.accounts if not meta.is_signer})
    table_address = derive_lookup_table_address(config.payer.pubkey(), 99)[0]
    state = AddressLookupTable(
        LookupTableMeta(
            last_extended_slot=100,
            authority=config.payer.pubkey(),
        ),
        required,
    )

    manager = SettlementTransportManager(db=object(), config=config)
    generation = LookupTableGeneration(
        id="generation-1",
        vault_id=42,
        program_id=str(config.program_id),
        generation=1,
        lookup_table_address=table_address,
        authority=config.payer.pubkey(),
        recent_slot=99,
        status="planned",
        create_tx_signature="create-signature",
    )
    manager._get_or_plan = AsyncMock(return_value=generation)
    manager._create_if_missing = AsyncMock(
        return_value=(state, "create-signature")
    )
    record = AsyncMock(return_value=SimpleNamespace(data=True))
    distribution = SettlementDistributionPlan(instruction, (), 10, 1, 10)
    with (
        patch(
            "app.services.settlement_transport._fetch_lookup_table_state",
            new=AsyncMock(return_value=(state, 101)),
        ),
        patch("app.services.settlement_transport._rpc", new=record),
    ):
        plan = await manager.prepare(
            vault_id=42,
            settlement_week=10,
            distribution=distribution,
            compute_unit_limit=SETTLEMENT_COMPUTE_UNIT_LIMIT,
        )
        await validate_frozen_settlement_transport(
            config=config,
            vault_id=42,
            settlement_week=10,
            instruction=instruction,
            transport_plan=plan,
            compute_unit_limit=SETTLEMENT_COMPUTE_UNIT_LIMIT,
        )

        drifted = make_distribute_epoch_rewards_ix(
            authority=config.backend_authority.pubkey(),
            vault_id=42,
            settlement_week=10,
            pol_account=Pubkey.new_unique(),
            protocol_treasury=Pubkey.new_unique(),
            dung_mint=config.dung_mint_address,
            program_id=config.program_id,
            local_legend=Pubkey.new_unique(),
            extra_accounts=[
                AccountMeta(key, is_signer=False, is_writable=True)
                for key in required[:21]
            ],
        )
        with pytest.raises(
            SettlementTransportStaleError,
            match="missing.*required|manifest changed",
        ):
            await validate_frozen_settlement_transport(
                config=config,
                vault_id=42,
                settlement_week=10,
                instruction=drifted,
                transport_plan=plan,
                compute_unit_limit=SETTLEMENT_COMPUTE_UNIT_LIMIT,
            )


@pytest.mark.asyncio
async def test_transport_resume_extends_only_remaining_frozen_chunk_then_noops() -> None:
    config = _config()
    instruction = _full_distribution(config)
    distribution = SettlementDistributionPlan(instruction, (), 10, 1, 10)
    required = list(
        {meta.pubkey: None for meta in instruction.accounts if not meta.is_signer}
    )
    recent_slot = 99
    table = derive_lookup_table_address(config.payer.pubkey(), recent_slot)[0]
    generation = LookupTableGeneration(
        id="generation-1",
        vault_id=42,
        program_id=str(config.program_id),
        generation=1,
        lookup_table_address=table,
        authority=config.payer.pubkey(),
        recent_slot=recent_slot,
        status="planned",
        create_tx_signature="create-signature",
    )
    partial = AddressLookupTable(
        LookupTableMeta(last_extended_slot=100, authority=config.payer.pubkey()),
        required[:20],
    )
    ready = AddressLookupTable(
        LookupTableMeta(last_extended_slot=101, authority=config.payer.pubkey()),
        required,
    )
    manager = SettlementTransportManager(db=object(), config=config)
    manager._get_or_plan = AsyncMock(return_value=generation)
    manager._create_if_missing = AsyncMock(
        side_effect=[(partial, "create-signature"), (ready, "create-signature")]
    )
    submit = AsyncMock(
        return_value=SimpleNamespace(
            failed=False,
            signature="remaining-extend",
            error=None,
            status="finalized",
        )
    )
    record = AsyncMock(return_value=SimpleNamespace(data=True))
    plans: list[dict] = []

    async def freeze(plan: dict) -> None:
        plans.append(plan)

    with (
        patch(
            "app.services.settlement_transport._fetch_lookup_table_state",
            new=AsyncMock(side_effect=[(ready, 102), (ready, 103)]),
        ),
        patch("app.services.settlement_transport.submit_and_confirm", new=submit),
        patch("app.services.settlement_transport._rpc", new=record),
    ):
        first = await manager.prepare(
            vault_id=42,
            settlement_week=10,
            distribution=distribution,
            compute_unit_limit=SETTLEMENT_COMPUTE_UNIT_LIMIT,
            on_plan=freeze,
        )
        first_count = submit.await_count
        second = await manager.prepare(
            vault_id=42,
            settlement_week=10,
            distribution=distribution,
            compute_unit_limit=SETTLEMENT_COMPUTE_UNIT_LIMIT,
            on_plan=freeze,
        )

    assert first_count == 1
    assert submit.await_count == first_count
    assert plans[0] == plans[1]
    assert first["manifest_sha256"] == second["manifest_sha256"]


@pytest.mark.asyncio
async def test_frozen_planned_generation_supersedes_once_only_after_proven_stale_create() -> None:
    config = _config()
    instruction = _full_distribution(config)
    distribution = SettlementDistributionPlan(instruction, (), 10, 1, 10)
    required = list(
        {meta.pubkey: None for meta in instruction.accounts if not meta.is_signer}
    )

    def generation(number: int, slot: int) -> LookupTableGeneration:
        return LookupTableGeneration(
            id=f"generation-{number}",
            vault_id=42,
            program_id=str(config.program_id),
            generation=number,
            lookup_table_address=derive_lookup_table_address(
                config.payer.pubkey(), slot
            )[0],
            authority=config.payer.pubkey(),
            recent_slot=slot,
            status="planned",
            create_tx_signature=None,
        )

    first_generation = generation(1, 99)
    second_generation = generation(2, 100)
    ready = AddressLookupTable(
        LookupTableMeta(last_extended_slot=101, authority=config.payer.pubkey()),
        required,
    )
    manager = SettlementTransportManager(db=object(), config=config)
    manager._get_or_plan = AsyncMock(return_value=first_generation)
    manager._rotate = AsyncMock(return_value=second_generation)
    manager._create_if_missing = AsyncMock(
        side_effect=[
            SettlementTransportStaleError(
                "planned settlement lookup-table slot expired before creation"
            ),
            (ready, "second-create"),
        ]
    )
    plans: list[dict] = []

    async def freeze(plan: dict) -> None:
        plans.append(plan)

    with (
        patch(
            "app.services.settlement_transport._fetch_lookup_table_state",
            new=AsyncMock(return_value=(ready, 102)),
        ),
        patch(
            "app.services.settlement_transport._rpc",
            new=AsyncMock(return_value=SimpleNamespace(data=True)),
        ),
    ):
        result = await manager.prepare(
            vault_id=42,
            settlement_week=10,
            distribution=distribution,
            compute_unit_limit=SETTLEMENT_COMPUTE_UNIT_LIMIT,
            on_plan=freeze,
        )

    assert len(plans) == 2
    assert plans[0]["lookup_table_generation"] == "1"
    assert plans[1]["lookup_table_generation"] == "2"
    assert plans[1]["supersedes"] == {
        "status": "expired",
        "generation_id": "generation-1",
        "lookup_table_address": str(first_generation.lookup_table_address),
        "lookup_table_generation": "1",
        "lookup_table_recent_slot": "99",
        "proof": "finalized create rejection after recent slot",
    }
    assert result["lookup_table_address"] == str(
        second_generation.lookup_table_address
    )
    manager._rotate.assert_awaited_once_with(first_generation)
