import struct
from types import SimpleNamespace
from typing import Optional
from unittest.mock import AsyncMock, patch

import base58
import pytest
from solana.rpc.types import MemcmpOpts
from solders.address_lookup_table_account import AddressLookupTableAccount
from solders.keypair import Keypair
from solders.pubkey import Pubkey

from app.account_deletion_contract import (
    VAULT_STAKE_ACTIVE_FIELDS,
    VAULT_STAKE_CLAIM_FIELDS,
    VAULT_STAKE_DELETION_U64_FIELDS,
)
from app.solana_direct import (
    DISTRIBUTION_CONFIG,
    DirectConfig,
    _derive_vault_lp_mint_pda,
    _derive_vault_position_lp_pda,
    _derive_vault_pda,
    LocalLegendData,
    TOKEN_PROGRAM_ID,
    VaultLeaderboardEntry,
    _account_discriminator,
    _derive_local_legend_pda,
    _derive_vault_leaderboard_pda,
    _derive_vault_stake_pda,
    _prepare_settlement_recipient_atas,
    _validate_settlement_token_account,
    _vault_stake_inventory_for_settlement,
    _vault_stake_account_discriminator,
    get_vault_lp_custody_observation,
    get_vault_position_quote_snapshot,
    get_vault_stake_account,
    get_vault_stake_accounts,
    get_rider_vault_stake_accounts,
    build_settlement_distribution_plan,
    make_distribute_epoch_rewards_ix,
    send_distribute_epoch_rewards,
)


PROGRAM_ID = Pubkey.new_unique()
VAULT_ID = 42


def _config() -> DirectConfig:
    return DirectConfig(
        rpc_url="http://example.invalid",
        program_id=PROGRAM_ID,
        payer=Keypair(),
    )


def _stake(
    user: Pubkey,
    *,
    cal_staked: int = 100,
    lp_tokens: int = 100,
    effective_lp_tokens: Optional[int] = None,
    pending_lp_tokens: int = 0,
    pending_effective_week_plus_one: int = 0,
) -> dict:
    pda, bump = _derive_vault_stake_pda(user, VAULT_ID, PROGRAM_ID)
    return {
        "user": str(user),
        "vault_id": VAULT_ID,
        "cal_staked": cal_staked,
        "lp_tokens": lp_tokens,
        "eligible_from_epoch": 0,
        "pending_effective_week_plus_one": pending_effective_week_plus_one,
        "effective_lp_tokens": (
            lp_tokens if effective_lp_tokens is None else effective_lp_tokens
        ),
        "rewards_earned": 0,
        "pending_lp_tokens": pending_lp_tokens,
        "pda": str(pda),
        "bump": bump,
    }


def _rpc_account(pubkey: Pubkey, data: bytes, *, owner: Pubkey = PROGRAM_ID):
    return SimpleNamespace(
        pubkey=pubkey,
        account=SimpleNamespace(data=data, owner=owner),
    )


def test_distribution_builder_rejects_sum_valid_noncanonical_policy():
    alternate = {
        **DISTRIBUTION_CONFIG,
        "leaderboard_share_bps": 5_400,
        "staker_share_bps": 2_800,
    }

    with pytest.raises(ValueError, match="canonical distribution policy"):
        make_distribute_epoch_rewards_ix(
            authority=Pubkey.new_unique(),
            vault_id=VAULT_ID,
            settlement_week=10,
            pol_account=Pubkey.new_unique(),
            protocol_treasury=Pubkey.new_unique(),
            dung_mint=Pubkey.new_unique(),
            program_id=PROGRAM_ID,
            config=alternate,
        )


@pytest.mark.asyncio
async def test_distribution_preflight_rejects_a_mismatched_dung_mint():
    config = _config()
    config.backend_authority = Keypair()
    config.dung_mint_address = Pubkey.new_unique()

    with (
        patch(
            "app.solana_direct.AsyncClient",
            return_value=_SettlementPreflightClient(set()),
        ),
        patch(
            "app.solana_direct.get_program_config_account",
            new=AsyncMock(
                return_value={
                    "dung_mint": str(Pubkey.new_unique()),
                    "epochs_per_halving": 26,
                    "pol_token_account": str(Pubkey.new_unique()),
                    "treasury_token_account": str(Pubkey.new_unique()),
                }
            ),
        ),
        pytest.raises(ValueError, match="does not match canonical ProgramConfig"),
    ):
        await send_distribute_epoch_rewards(config, VAULT_ID, settlement_week=10)


class _FakeAsyncClient:
    def __init__(self, response):
        self.response = response
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    async def get_program_accounts(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.response


class _FakeAccountInfoClient:
    def __init__(self, value):
        self.value = value

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    async def get_account_info(self, _pubkey):
        return SimpleNamespace(value=self.value)


class _FakeMultipleAccountsClient:
    def __init__(self, values):
        self.values = values
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    async def get_multiple_accounts(self, pubkeys):
        self.calls.append(pubkeys)
        return SimpleNamespace(
            value=self.values,
            context=SimpleNamespace(slot=123_456),
        )


class _SettlementPreflightClient:
    def __init__(
        self,
        existing_accounts: set[Pubkey],
        *,
        program_data: Optional[dict[Pubkey, bytes]] = None,
        token_accounts: Optional[dict[Pubkey, tuple[Pubkey, Pubkey]]] = None,
    ):
        self.existing_accounts = existing_accounts
        self.program_data = program_data or {}
        self.token_accounts = token_accounts or {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    async def get_account_info(self, pubkey: Pubkey, **_kwargs):
        if pubkey in self.token_accounts:
            mint, owner = self.token_accounts[pubkey]
            data = bytearray(165)
            data[:32] = bytes(mint)
            data[32:64] = bytes(owner)
            data[108] = 1
            value = SimpleNamespace(data=bytes(data), owner=TOKEN_PROGRAM_ID)
        elif pubkey in self.existing_accounts:
            value = SimpleNamespace(
                data=self.program_data.get(pubkey, b""),
                owner=PROGRAM_ID,
            )
        else:
            value = None
        return SimpleNamespace(value=value)


def _token_account_data(
    *,
    mint: Pubkey,
    authority: Pubkey,
    amount: int,
    state: int,
) -> bytes:
    data = bytearray(165)
    data[0:32] = bytes(mint)
    data[32:64] = bytes(authority)
    struct.pack_into("<Q", data, 64, amount)
    data[108] = state
    return bytes(data)


def _mint_account_data(
    *,
    mint_authority: Optional[Pubkey],
    freeze_authority: Optional[Pubkey],
    initialized: bool = True,
    supply: int = 0,
) -> bytes:
    data = bytearray(82)
    if mint_authority is not None:
        struct.pack_into("<I", data, 0, 1)
        data[4:36] = bytes(mint_authority)
    struct.pack_into("<Q", data, 36, supply)
    data[45] = 1 if initialized else 0
    if freeze_authority is not None:
        struct.pack_into("<I", data, 46, 1)
        data[50:82] = bytes(freeze_authority)
    return bytes(data)


@pytest.mark.asyncio
async def test_withdrawal_quote_snapshot_reads_all_inputs_at_one_slot():
    user = Pubkey.new_unique()
    vault, _ = _derive_vault_pda(VAULT_ID, PROGRAM_ID)
    vault_stake, bump = _derive_vault_stake_pda(user, VAULT_ID, PROGRAM_ID)
    vault_lp_mint, _ = _derive_vault_lp_mint_pda(VAULT_ID, PROGRAM_ID)
    position_lp, _ = _derive_vault_position_lp_pda(user, VAULT_ID, PROGRAM_ID)
    stake = {
        **_stake(user, lp_tokens=1001),
        "bump": bump,
    }
    accounts = [
        SimpleNamespace(data=b"vault", owner=PROGRAM_ID),
        SimpleNamespace(data=b"stake", owner=PROGRAM_ID),
        SimpleNamespace(
            data=_token_account_data(
                mint=vault_lp_mint,
                authority=vault_stake,
                amount=1001,
                state=2,
            ),
            owner=TOKEN_PROGRAM_ID,
        ),
        SimpleNamespace(
            data=_mint_account_data(
                mint_authority=vault,
                freeze_authority=vault,
                supply=2000,
            ),
            owner=TOKEN_PROGRAM_ID,
        ),
    ]
    client = _FakeMultipleAccountsClient(accounts)

    with (
        patch("app.solana_direct.AsyncClient", return_value=client),
        patch(
            "app.solana_direct._decode_anchor_vault_account",
            return_value={"id": VAULT_ID, "total_cal_staked": 2003},
        ),
        patch(
            "app.solana_direct._decode_anchor_vault_stake_account",
            return_value=stake,
        ),
    ):
        snapshot = await get_vault_position_quote_snapshot(
            _config(),
            VAULT_ID,
            str(user),
        )

    assert snapshot is not None
    assert snapshot.slot == 123_456
    assert snapshot.vault["total_cal_staked"] == 2003
    assert snapshot.stake["lp_tokens"] == 1001
    assert snapshot.custody.sealed is True
    assert snapshot.custody.lp_supply_base_units == 2000
    assert client.calls == [[vault, vault_stake, position_lp, vault_lp_mint]]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("case", "expected_status", "expected_amount"),
    [
        ("missing", "missing", None),
        ("wrong_program", "invalid_program_owner", None),
        ("short_data", "invalid_data_length", None),
        ("wrong_mint", "invalid_mint", 100),
        ("wrong_authority", "invalid_authority", 100),
        ("initialized", "not_frozen", 100),
        ("short_balance", "amount_mismatch", 99),
        ("overfilled", "amount_mismatch", 101),
    ],
)
async def test_lp_custody_observation_fails_closed(
    case,
    expected_status,
    expected_amount,
):
    user = Pubkey.new_unique()
    vault_stake, _ = _derive_vault_stake_pda(user, VAULT_ID, PROGRAM_ID)
    vault_lp_mint, _ = _derive_vault_lp_mint_pda(VAULT_ID, PROGRAM_ID)
    mint = Pubkey.new_unique() if case == "wrong_mint" else vault_lp_mint
    authority = Pubkey.new_unique() if case == "wrong_authority" else vault_stake
    amount = 99 if case == "short_balance" else 101 if case == "overfilled" else 100
    token_state = 1 if case == "initialized" else 2
    data = (
        b"short"
        if case == "short_data"
        else _token_account_data(
            mint=mint,
            authority=authority,
            amount=amount,
            state=token_state,
        )
    )
    account = None
    if case != "missing":
        account = SimpleNamespace(
            data=data,
            owner=Pubkey.new_unique() if case == "wrong_program" else TOKEN_PROGRAM_ID,
        )
    vault, _ = Pubkey.find_program_address(
        [b"vault", VAULT_ID.to_bytes(8, "little")],
        PROGRAM_ID,
    )
    mint_account = SimpleNamespace(
        data=_mint_account_data(
            mint_authority=vault,
            freeze_authority=vault,
        ),
        owner=TOKEN_PROGRAM_ID,
    )

    with patch(
        "app.solana_direct.AsyncClient",
        return_value=_FakeMultipleAccountsClient([account, mint_account]),
    ):
        observation = await get_vault_lp_custody_observation(
            _config(),
            VAULT_ID,
            str(user),
            100,
        )

    position_lp, _ = _derive_vault_position_lp_pda(user, VAULT_ID, PROGRAM_ID)
    assert observation.status == expected_status
    assert observation.sealed is False
    assert observation.amount_base_units == expected_amount
    assert observation.token_account == str(position_lp)
    assert observation.token_authority == str(vault_stake)
    assert observation.mint == str(vault_lp_mint)
    assert observation.slot == 123_456


@pytest.mark.asyncio
async def test_lp_custody_observation_requires_exact_frozen_balance():
    user = Pubkey.new_unique()
    vault_stake, _ = _derive_vault_stake_pda(user, VAULT_ID, PROGRAM_ID)
    vault_lp_mint, _ = _derive_vault_lp_mint_pda(VAULT_ID, PROGRAM_ID)
    account = SimpleNamespace(
        data=_token_account_data(
            mint=vault_lp_mint,
            authority=vault_stake,
            amount=100,
            state=2,
        ),
        owner=TOKEN_PROGRAM_ID,
    )
    vault, _ = Pubkey.find_program_address(
        [b"vault", VAULT_ID.to_bytes(8, "little")],
        PROGRAM_ID,
    )
    mint_account = SimpleNamespace(
        data=_mint_account_data(
            mint_authority=vault,
            freeze_authority=vault,
        ),
        owner=TOKEN_PROGRAM_ID,
    )

    with patch(
        "app.solana_direct.AsyncClient",
        return_value=_FakeMultipleAccountsClient([account, mint_account]),
    ):
        observation = await get_vault_lp_custody_observation(
            _config(),
            VAULT_ID,
            str(user),
            100,
        )

    assert observation.status == "sealed"
    assert observation.sealed is True
    assert observation.amount_base_units == 100
    assert observation.token_state == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("case", "expected_status"),
    [
        ("missing", "missing_lp_mint"),
        ("wrong_program", "invalid_lp_mint_program_owner"),
        ("short_data", "invalid_lp_mint_data_length"),
        ("uninitialized", "uninitialized_lp_mint"),
        ("wrong_mint_authority", "invalid_lp_mint_authority"),
        ("missing_mint_authority", "invalid_lp_mint_authority"),
        ("wrong_freeze_authority", "invalid_lp_freeze_authority"),
        ("missing_freeze_authority", "invalid_lp_freeze_authority"),
    ],
)
async def test_lp_custody_observation_requires_vault_owned_lp_mint(
    case,
    expected_status,
):
    user = Pubkey.new_unique()
    vault_stake, _ = _derive_vault_stake_pda(user, VAULT_ID, PROGRAM_ID)
    vault_lp_mint, _ = _derive_vault_lp_mint_pda(VAULT_ID, PROGRAM_ID)
    vault, _ = Pubkey.find_program_address(
        [b"vault", VAULT_ID.to_bytes(8, "little")],
        PROGRAM_ID,
    )
    position_account = SimpleNamespace(
        data=_token_account_data(
            mint=vault_lp_mint,
            authority=vault_stake,
            amount=100,
            state=2,
        ),
        owner=TOKEN_PROGRAM_ID,
    )
    mint_authority = (
        None
        if case == "missing_mint_authority"
        else Pubkey.new_unique()
        if case == "wrong_mint_authority"
        else vault
    )
    freeze_authority = (
        None
        if case == "missing_freeze_authority"
        else Pubkey.new_unique()
        if case == "wrong_freeze_authority"
        else vault
    )
    mint_account = None
    if case != "missing":
        mint_account = SimpleNamespace(
            data=(
                b"short"
                if case == "short_data"
                else _mint_account_data(
                    mint_authority=mint_authority,
                    freeze_authority=freeze_authority,
                    initialized=case != "uninitialized",
                )
            ),
            owner=(
                Pubkey.new_unique()
                if case == "wrong_program"
                else TOKEN_PROGRAM_ID
            ),
        )

    with patch(
        "app.solana_direct.AsyncClient",
        return_value=_FakeMultipleAccountsClient([position_account, mint_account]),
    ):
        observation = await get_vault_lp_custody_observation(
            _config(),
            VAULT_ID,
            str(user),
            100,
        )

    assert observation.status == expected_status
    assert observation.sealed is False


def _empty_leaderboard_data() -> bytes:
    return (
        _account_discriminator("VaultLeaderboard")
        + struct.pack("<Q", VAULT_ID)
        + struct.pack("<I", 0)
        + struct.pack("<q", 0)
        + b"\x00"
    )


def test_settlement_token_account_validation_rejects_wrong_mint_and_recipient():
    mint = Pubkey.new_unique()
    recipient = Pubkey.new_unique()
    address = Pubkey.new_unique()
    data = bytearray(165)
    data[:32] = bytes(Pubkey.new_unique())
    data[32:64] = bytes(recipient)
    data[108] = 1
    account = SimpleNamespace(data=bytes(data), owner=TOKEN_PROGRAM_ID)

    with pytest.raises(ValueError, match="mint mismatch"):
        _validate_settlement_token_account(
            account=account,
            address=address,
            dung_mint=mint,
            expected_owner=recipient,
        )

    data[:32] = bytes(mint)
    account.data = bytes(data)
    with pytest.raises(ValueError, match="recipient mismatch"):
        _validate_settlement_token_account(
            account=account,
            address=address,
            dung_mint=mint,
            expected_owner=Pubkey.new_unique(),
        )


def test_inventory_requires_live_pending_and_effective_tombstone_positions():
    eligible = _stake(Pubkey.new_unique())
    pending = _stake(
        Pubkey.new_unique(),
        effective_lp_tokens=0,
        pending_lp_tokens=100,
        pending_effective_week_plus_one=100,
    )
    tombstone = _stake(
        Pubkey.new_unique(),
        cal_staked=0,
        lp_tokens=0,
        effective_lp_tokens=100,
    )
    inactive = _stake(Pubkey.new_unique(), cal_staked=0, lp_tokens=0)

    inventory = _vault_stake_inventory_for_settlement(
        [inactive, tombstone, pending, eligible],
        vault_id=VAULT_ID,
        expected_inventory_count=3,
        program_id=PROGRAM_ID,
    )

    assert [row["pda"] for row in inventory] == sorted(
        [eligible["pda"], pending["pda"], tombstone["pda"]]
    )
    assert inactive not in inventory


def test_inventory_rejects_an_omitted_position_of_any_state():
    with pytest.raises(RuntimeError, match="expected 2 VaultStake inventory accounts, found 1"):
        _vault_stake_inventory_for_settlement(
            [_stake(Pubkey.new_unique())],
            vault_id=VAULT_ID,
            expected_inventory_count=2,
            program_id=PROGRAM_ID,
        )


def test_inventory_rejects_duplicates_and_invalid_snapshot_units():
    stake = _stake(Pubkey.new_unique())
    with pytest.raises(ValueError, match="duplicate VaultStake PDA"):
        _vault_stake_inventory_for_settlement(
            [stake, stake],
            vault_id=VAULT_ID,
            expected_inventory_count=2,
            program_id=PROGRAM_ID,
        )


def test_shared_deletion_stake_contract_is_validated_by_settlement_inventory():
    assert VAULT_STAKE_DELETION_U64_FIELDS == (
        *VAULT_STAKE_ACTIVE_FIELDS,
        *VAULT_STAKE_CLAIM_FIELDS,
    )
    for field in VAULT_STAKE_DELETION_U64_FIELDS:
        malformed = _stake(Pubkey.new_unique())
        malformed[field] = -1
        with pytest.raises(ValueError, match=f"invalid {field}"):
            _vault_stake_inventory_for_settlement(
                [malformed],
                vault_id=VAULT_ID,
                expected_inventory_count=1,
                program_id=PROGRAM_ID,
            )

def test_inventory_rejects_more_than_compute_proven_staker_bound():
    stakes = [_stake(Pubkey.new_unique()) for _ in range(11)]

    with pytest.raises(
        ValueError,
        match="at most 10 settlement-relevant VaultStake accounts",
    ):
        _vault_stake_inventory_for_settlement(
            stakes,
            vault_id=VAULT_ID,
            expected_inventory_count=11,
            program_id=PROGRAM_ID,
        )


def test_inventory_rejects_a_noncanonical_pda():
    malformed = _stake(Pubkey.new_unique())
    malformed["pda"] = str(Pubkey.new_unique())

    with pytest.raises(ValueError, match="PDA or bump mismatch"):
        _vault_stake_inventory_for_settlement(
            [malformed],
            vault_id=VAULT_ID,
            expected_inventory_count=1,
            program_id=PROGRAM_ID,
        )


@pytest.mark.asyncio
async def test_rpc_inventory_scans_all_program_accounts_and_sorts_by_pda():
    first = _stake(Pubkey.new_unique())
    second = _stake(
        Pubkey.new_unique(),
        effective_lp_tokens=0,
        pending_lp_tokens=100,
        pending_effective_week_plus_one=100,
    )
    decoded_by_pda = {first["pda"]: first, second["pda"]: second}
    first_pda = Pubkey.from_string(first["pda"])
    second_pda = Pubkey.from_string(second["pda"])
    non_stake_pda = Pubkey.new_unique()
    response = SimpleNamespace(
        value=[
            _rpc_account(second_pda, _vault_stake_account_discriminator() + b"second"),
            _rpc_account(non_stake_pda, b"notstake"),
            _rpc_account(first_pda, _vault_stake_account_discriminator() + b"first"),
        ]
    )
    client = _FakeAsyncClient(response)

    with (
        patch("app.solana_direct.AsyncClient", return_value=client),
        patch(
            "app.solana_direct._decode_anchor_vault_stake_account",
            side_effect=lambda _data, pda: decoded_by_pda[str(pda)],
        ),
    ):
        stakes = await get_vault_stake_accounts(_config(), VAULT_ID)

    assert [row["pda"] for row in stakes] == sorted(decoded_by_pda)
    assert client.calls == [
        (
            (PROGRAM_ID,),
            {"commitment": "confirmed", "encoding": "base64"},
        )
    ]


@pytest.mark.asyncio
async def test_deletion_inventory_filters_to_target_rider_before_decoding_at_finalized_commitment():
    rider = Pubkey.new_unique()
    target = _stake(rider, pending_lp_tokens=9, pending_effective_week_plus_one=12)
    decoded_by_pda = {target["pda"]: target}
    response = SimpleNamespace(
        value=[
            _rpc_account(
                Pubkey.from_string(target["pda"]),
                _vault_stake_account_discriminator() + bytes(rider) + b"target",
            ),
        ]
    )
    client = _FakeAsyncClient(response)

    with (
        patch("app.solana_direct.AsyncClient", return_value=client),
        patch(
            "app.solana_direct._decode_anchor_vault_stake_account",
            side_effect=lambda _data, pda: decoded_by_pda[str(pda)],
        ),
    ):
        stakes = await get_rider_vault_stake_accounts(
            str(rider),
            rpc_url=_config().rpc_url,
            program_id=PROGRAM_ID,
        )

    assert stakes == [target]
    assert client.calls == [
        (
            (PROGRAM_ID,),
            {
                "commitment": "finalized",
                "encoding": "base64",
                "filters": [
                    MemcmpOpts(
                        offset=0,
                        bytes=base58.b58encode(
                            _vault_stake_account_discriminator()
                        ).decode(),
                    ),
                    MemcmpOpts(offset=8, bytes=str(rider)),
                ],
            },
        )
    ]


@pytest.mark.asyncio
async def test_deletion_inventory_skips_unrelated_corrupt_stake_before_anchor_decode():
    rider = Pubkey.new_unique()
    other = Pubkey.new_unique()
    response = SimpleNamespace(
        value=[
            _rpc_account(
                Pubkey.new_unique(),
                _vault_stake_account_discriminator() + bytes(other) + b"corrupt",
            ),
            _rpc_account(
                Pubkey.new_unique(),
                _vault_stake_account_discriminator() + b"truncated",
            ),
        ]
    )
    client = _FakeAsyncClient(response)

    with (
        patch("app.solana_direct.AsyncClient", return_value=client),
        patch("app.solana_direct._decode_anchor_vault_stake_account") as decode,
    ):
        stakes = await get_rider_vault_stake_accounts(
            str(rider),
            rpc_url=_config().rpc_url,
            program_id=PROGRAM_ID,
        )

    assert stakes == []
    decode.assert_not_called()


@pytest.mark.asyncio
async def test_deletion_inventory_fails_closed_for_malformed_target_rider_stake():
    rider = Pubkey.new_unique()
    response = SimpleNamespace(
        value=[
            _rpc_account(
                Pubkey.new_unique(),
                _vault_stake_account_discriminator() + bytes(rider) + b"corrupt",
            )
        ]
    )
    client = _FakeAsyncClient(response)

    with (
        patch("app.solana_direct.AsyncClient", return_value=client),
        patch(
            "app.solana_direct._decode_anchor_vault_stake_account",
            side_effect=ValueError("bad target stake"),
        ),
        pytest.raises(RuntimeError, match="Failed to decode VaultStake"),
    ):
        await get_rider_vault_stake_accounts(
            str(rider),
            rpc_url=_config().rpc_url,
            program_id=PROGRAM_ID,
        )


@pytest.mark.asyncio
async def test_deletion_inventory_validates_every_shared_position_and_claim_field():
    rider = Pubkey.new_unique()
    for field in VAULT_STAKE_DELETION_U64_FIELDS:
        malformed = _stake(rider)
        malformed[field] = -1
        response = SimpleNamespace(
            value=[
                _rpc_account(
                    Pubkey.from_string(malformed["pda"]),
                    _vault_stake_account_discriminator() + bytes(rider) + b"target",
                )
            ]
        )
        client = _FakeAsyncClient(response)
        with (
            patch("app.solana_direct.AsyncClient", return_value=client),
            patch(
                "app.solana_direct._decode_anchor_vault_stake_account",
                return_value=malformed,
            ),
            pytest.raises(ValueError, match=f"invalid {field}"),
        ):
            await get_rider_vault_stake_accounts(
                str(rider),
                rpc_url=_config().rpc_url,
                program_id=PROGRAM_ID,
            )


@pytest.mark.asyncio
async def test_rpc_inventory_fails_closed_for_malformed_vault_stake_data():
    response = SimpleNamespace(
        value=[
            _rpc_account(
                Pubkey.new_unique(),
                _vault_stake_account_discriminator() + b"malformed",
            )
        ]
    )
    client = _FakeAsyncClient(response)

    with (
        patch("app.solana_direct.AsyncClient", return_value=client),
        patch(
            "app.solana_direct._decode_anchor_vault_stake_account",
            side_effect=ValueError("bad stake"),
        ),
        pytest.raises(RuntimeError, match="Failed to decode VaultStake"),
    ):
        await get_vault_stake_accounts(_config(), VAULT_ID)


@pytest.mark.asyncio
async def test_rpc_inventory_rejects_wrong_owner_even_if_rpc_returns_it():
    response = SimpleNamespace(
        value=[
            _rpc_account(
                Pubkey.new_unique(),
                _vault_stake_account_discriminator() + b"stake",
                owner=Pubkey.new_unique(),
            )
        ]
    )
    client = _FakeAsyncClient(response)

    with (
        patch("app.solana_direct.AsyncClient", return_value=client),
        pytest.raises(RuntimeError, match="owner mismatch"),
    ):
        await get_vault_stake_accounts(_config(), VAULT_ID)


@pytest.mark.asyncio
async def test_single_stake_read_rejects_wrong_program_owner():
    user = Pubkey.new_unique()
    decoded = _stake(user)
    account = SimpleNamespace(data=b"stake", owner=Pubkey.new_unique())

    with (
        patch(
            "app.solana_direct.AsyncClient",
            return_value=_FakeAccountInfoClient(account),
        ),
        patch(
            "app.solana_direct._decode_anchor_vault_stake_account",
            return_value=decoded,
        ) as decode,
        pytest.raises(ValueError, match="unexpected owner"),
    ):
        await get_vault_stake_account(_config(), VAULT_ID, str(user))

    decode.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("user", str(Pubkey.new_unique()), "rider mismatch"),
        ("vault_id", VAULT_ID + 1, "vault mismatch"),
        ("bump", -1, "invalid bump"),
    ],
)
async def test_single_stake_read_rejects_identity_mismatch(field, value, message):
    user = Pubkey.new_unique()
    decoded = _stake(user)
    decoded[field] = value
    account = SimpleNamespace(data=b"stake", owner=PROGRAM_ID)

    with (
        patch(
            "app.solana_direct.AsyncClient",
            return_value=_FakeAccountInfoClient(account),
        ),
        patch(
            "app.solana_direct._decode_anchor_vault_stake_account",
            return_value=decoded,
        ),
        pytest.raises(ValueError, match=message),
    ):
        await get_vault_stake_account(_config(), VAULT_ID, str(user))


@pytest.mark.asyncio
async def test_distribution_supplies_complete_settlement_relevant_inventory():
    config = _config()
    config.backend_authority = Keypair()
    config.dung_mint_address = Pubkey.new_unique()
    pol = Pubkey.new_unique()
    treasury = Pubkey.new_unique()
    leaderboard_pda, _ = _derive_vault_leaderboard_pda(VAULT_ID, PROGRAM_ID)
    eligible = _stake(Pubkey.new_unique())
    pending = _stake(
        Pubkey.new_unique(),
        effective_lp_tokens=0,
        pending_lp_tokens=100,
        pending_effective_week_plus_one=100,
    )
    tombstone = _stake(
        Pubkey.new_unique(),
        cal_staked=0,
        lp_tokens=0,
        effective_lp_tokens=100,
    )
    inactive = _stake(Pubkey.new_unique(), cal_staked=0, lp_tokens=0)
    submit = AsyncMock(
        return_value=SimpleNamespace(failed=False, signature="settlement-signature")
    )
    vault_read = AsyncMock(return_value={"staker_count": 3})
    stake_inventory_read = AsyncMock(
        return_value=[pending, inactive, tombstone, eligible]
    )

    with (
        patch(
            "app.solana_direct.AsyncClient",
            return_value=_SettlementPreflightClient(
                {leaderboard_pda},
                program_data={leaderboard_pda: _empty_leaderboard_data()},
                token_accounts={
                    pol: (config.dung_mint_address, Pubkey.new_unique()),
                    treasury: (config.dung_mint_address, Pubkey.new_unique()),
                },
            ),
        ),
        patch(
            "app.solana_direct.get_program_config_account",
            new=AsyncMock(
                return_value={
                    "dung_mint": str(config.dung_mint_address),
                    "epochs_per_halving": 26,
                    "pol_token_account": str(pol),
                    "treasury_token_account": str(treasury),
                }
            ),
        ),
        patch(
            "app.solana_direct.get_vault_account",
            new=vault_read,
        ),
        patch(
            "app.solana_direct.get_vault_stake_accounts",
            new=stake_inventory_read,
        ),
        patch(
            "app.services.settlement_transport.validate_frozen_settlement_transport",
            new=AsyncMock(
                return_value=AddressLookupTableAccount(
                    Pubkey.new_unique(),
                    [Pubkey.new_unique()],
                )
            ),
        ),
        patch("app.services.solana_submit.submit_and_confirm", new=submit),
    ):
        signature = await send_distribute_epoch_rewards(
            config,
            VAULT_ID,
            settlement_week=10,
            transport_plan={},
        )

    assert signature == "settlement-signature"
    distribution_ix = submit.await_args.kwargs["instructions"][-1]
    assert [str(meta.pubkey) for meta in distribution_ix.accounts[-3:]] == sorted(
        [eligible["pda"], pending["pda"], tombstone["pda"]]
    )
    assert submit.await_args.kwargs["compute_units"] == 450_000
    assert len(submit.await_args.kwargs["address_lookup_table_accounts"]) == 1
    assert vault_read.await_args.kwargs["commitment"] == "finalized"
    assert stake_inventory_read.await_args.kwargs["commitment"] == "finalized"


@pytest.mark.asyncio
async def test_distribution_prepares_missing_recipient_atas_before_economic_send():
    config = _config()
    config.backend_authority = Keypair()
    config.dung_mint_address = Pubkey.new_unique()
    pol = Pubkey.new_unique()
    treasury = Pubkey.new_unique()
    leaderboard_pda, _ = _derive_vault_leaderboard_pda(VAULT_ID, PROGRAM_ID)
    local_legend_pda, _ = _derive_local_legend_pda(VAULT_ID, PROGRAM_ID)
    board_user = Pubkey.new_unique()
    legend_user = Pubkey.new_unique()
    submit = AsyncMock(
        side_effect=[
            SimpleNamespace(failed=False, signature="board-ata"),
            SimpleNamespace(failed=False, signature="legend-ata"),
        ]
    )

    with (
        patch(
            "app.solana_direct.AsyncClient",
            return_value=_SettlementPreflightClient(
                {leaderboard_pda, local_legend_pda},
                program_data={
                    leaderboard_pda: _empty_leaderboard_data(),
                    local_legend_pda: (
                        _account_discriminator("LocalLegend")
                        + struct.pack("<Q", VAULT_ID)
                    ),
                },
                token_accounts={
                    pol: (config.dung_mint_address, Pubkey.new_unique()),
                    treasury: (config.dung_mint_address, Pubkey.new_unique()),
                },
            ),
        ),
        patch(
            "app.solana_direct.get_program_config_account",
            new=AsyncMock(
                return_value={
                    "dung_mint": str(config.dung_mint_address),
                    "epochs_per_halving": 26,
                    "pol_token_account": str(pol),
                    "treasury_token_account": str(treasury),
                }
            ),
        ),
        patch(
            "app.solana_direct.parse_vault_leaderboard",
            return_value=[VaultLeaderboardEntry(board_user, 100, 1)],
        ),
        patch(
            "app.solana_direct.parse_local_legend",
            return_value=LocalLegendData(legend_user, True, False, 1, 2),
        ),
        patch(
            "app.solana_direct.get_vault_account",
            new=AsyncMock(return_value={"staker_count": 0}),
        ),
        patch(
            "app.solana_direct.get_vault_stake_accounts",
            new=AsyncMock(return_value=[]),
        ),
        patch("app.services.solana_submit.submit_and_confirm", new=submit),
    ):
        plan = await build_settlement_distribution_plan(
            config=config,
            vault_id=VAULT_ID,
            settlement_week=10,
        )
        recipient_ata_signatures = await _prepare_settlement_recipient_atas(
            rpc_url=config.rpc_url,
            payer=config.payer,
            vault_id=VAULT_ID,
            instructions=list(plan.recipient_ata_instructions),
        )

    assert len(plan.recipient_ata_instructions) == 2
    assert recipient_ata_signatures == ["board-ata", "legend-ata"]
    assert submit.await_count == 2
    for call in submit.await_args_list:
        assert call.kwargs["tx_type"] == "settlement_recipient_ata_prepare"
        assert call.kwargs["instructions"][0].data == bytes([1])
        assert "on_prepared" not in call.kwargs
        assert "on_submitted" not in call.kwargs
