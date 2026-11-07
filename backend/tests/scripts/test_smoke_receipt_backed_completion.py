from __future__ import annotations

import hashlib
import importlib.util
import json
import struct
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from solders.hash import Hash
from solders.address_lookup_table_account import derive_lookup_table_address
from solders.instruction import AccountMeta, Instruction
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.signature import Signature
from solders.transaction import Transaction

from app.services.cal_tribute_policy import (
    calculate_ride_tribute_budget,
    calculate_segment_tss_base_units,
)
from app.services.vault_completion_evidence import build_climb_completion_evidence_v2


BACKEND_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = BACKEND_DIR.parent
SMOKE_PATH = BACKEND_DIR / "scripts" / "smoke_devnet_economics.py"
WALLET_SMOKE_PATH = BACKEND_DIR / "scripts" / "smoke_wallet_signed_economics.py"
SPEC = importlib.util.spec_from_file_location("smoke_devnet_economics", SMOKE_PATH)
assert SPEC is not None and SPEC.loader is not None
smoke = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = smoke
SPEC.loader.exec_module(smoke)
WALLET_SPEC = importlib.util.spec_from_file_location(
    "smoke_wallet_signed_economics_test", WALLET_SMOKE_PATH
)
assert WALLET_SPEC is not None and WALLET_SPEC.loader is not None
wallet_smoke = importlib.util.module_from_spec(WALLET_SPEC)
WALLET_SPEC.loader.exec_module(wallet_smoke)
SETUP_EVIDENCE_PATH = BACKEND_DIR / "scripts" / "rehearsal_setup_evidence.py"
SETUP_EVIDENCE_SPEC = importlib.util.spec_from_file_location(
    "rehearsal_setup_evidence_test", SETUP_EVIDENCE_PATH
)
assert SETUP_EVIDENCE_SPEC is not None and SETUP_EVIDENCE_SPEC.loader is not None
setup_evidence = importlib.util.module_from_spec(SETUP_EVIDENCE_SPEC)
SETUP_EVIDENCE_SPEC.loader.exec_module(setup_evidence)
SETUP_COMMAND_PATH = BACKEND_DIR / "scripts" / "setup_rehearsal_usdc.py"
SETUP_COMMAND_SPEC = importlib.util.spec_from_file_location(
    "setup_rehearsal_usdc_test", SETUP_COMMAND_PATH
)
assert SETUP_COMMAND_SPEC is not None and SETUP_COMMAND_SPEC.loader is not None
setup_command = importlib.util.module_from_spec(SETUP_COMMAND_SPEC)
SETUP_COMMAND_SPEC.loader.exec_module(setup_command)

PROGRAM_ID = Pubkey.from_string("EVjP2Vdz9buHNphywPhoybf213poa8EiSW6FGbXWFqYH")


@pytest.fixture(autouse=True)
def _protocol_scale_measured_smoke_tribute(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep mocked chain-state arithmetic small without restoring fixed 10%."""

    contribution = calculate_segment_tss_base_units(
        segment_np_duration_s=2_200,
        segment_np_milliwatts=16,
        reward_ftp_w=250,
    )
    assert contribution == 250

    def measured_tribute(cal_amount: int, completion_time_s: int) -> int:
        assert completion_time_s > 0
        return calculate_ride_tribute_budget(cal_amount, [contribution])

    monkeypatch.setattr(smoke, "measured_smoke_cal_tribute", measured_tribute)
    monkeypatch.setattr(
        wallet_smoke,
        "measured_smoke_cal_tribute",
        measured_tribute,
    )


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


async def _async_value(value: Any) -> Any:
    return value


class _FakeEvidence:
    def __init__(
        self,
        vault_id: int,
        events: list[tuple[str, Any]] | None = None,
    ) -> None:
        self.vault_id = vault_id
        self.events = events
        self.settlement_weeks: list[int] = []

    def set_settlement_week(self, settlement_week: int) -> None:
        self.settlement_weeks.append(settlement_week)
        if self.events is not None:
            self.events.append(("freeze_week", settlement_week))

    def claim_run_lock(self) -> None:
        return None

    def record_prepared_transaction(self, *args: Any, **kwargs: Any) -> None:
        return None

    def record_finalized_transaction(self, *args: Any, **kwargs: Any) -> None:
        return None

    async def finalize_stage(self, *args: Any, **kwargs: Any) -> None:
        return None

    async def reconcile_prepared_transactions(self) -> None:
        return None

    async def recover_one_loop_stage(self) -> str | None:
        return None

    def has_reconciliation(self, stage: str) -> bool:
        return stage == "create_vault_with_usdc"

    def has_finalized_instruction(self, name: str) -> bool:
        return name == "create_vault_with_usdc"

    def finalized_signature_for_instruction(self, instruction_name: str) -> str | None:
        return None

    def register_cal_credit_evidence(self, *args: Any, **kwargs: Any) -> None:
        return None

    def register_completion_evidence(self, *args: Any, **kwargs: Any) -> None:
        return None

    async def register_settlement_transport_plan(
        self, *args: Any, **kwargs: Any
    ) -> None:
        return None

    def confirm_settlement_transport_ready(
        self, *args: Any, **kwargs: Any
    ) -> None:
        return None


def _vault_state(**overrides: int) -> dict[str, int]:
    state = {
        "open_settlement_week": 42,
        "last_distribution_epoch": 41,
        "cal_tribute_accumulated": 0,
        "cal_tribute_accumulated_next": 0,
        "pending_rewards": 0,
        "pending_rewards_next_week": 0,
        "carry_record_royalty": 0,
        "carry_stakers": 0,
        "carry_local_legend": 0,
        "carry_pol": 0,
        "carry_treasury": 0,
        "total_cal_staked": 0,
        "staker_count": 0,
    }
    state.update(overrides)
    return state


def test_executable_python_surface_has_no_legacy_completion_builder() -> None:
    executable_paths = sorted((BACKEND_DIR / "app").rglob("*.py")) + sorted(
        (BACKEND_DIR / "scripts").rglob("*.py")
    )
    prohibited = (
        "make_record_vault_completion_ix",
        "send_record_vault_completion",
        "async def record_vault_completion(",
        ".record_vault_completion(",
    )
    offenders = {
        str(path.relative_to(REPO_ROOT)): [
            marker for marker in prohibited if marker in _source(path)
        ]
        for path in executable_paths
        if any(marker in _source(path) for marker in prohibited)
    }

    assert offenders == {}


@pytest.mark.asyncio
async def test_smoke_completion_submits_attestation_completion_then_cal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    helper = getattr(smoke, "record_receipt_backed_tribute", None)
    assert callable(helper)

    calls: list[tuple[str, dict[str, Any]]] = []

    async def record_ride(**kwargs: Any) -> str:
        calls.append(("record_ride", kwargs))
        return "ride-signature"

    async def record_completion(**kwargs: Any) -> str:
        calls.append(("record_climb_completion", kwargs))
        return "completion-signature"

    async def credit_cal(**kwargs: Any) -> str:
        calls.append(("credit_cal", kwargs))
        return "cal-signature"

    monkeypatch.setattr(smoke, "send_record_ride", record_ride)
    monkeypatch.setattr(smoke, "send_record_climb_completion", record_completion)
    monkeypatch.setattr(smoke, "send_credit_cal", credit_cal)

    staker = Pubkey.from_string("Ch8uwuNxXkQBTJfBNbCq57yhaKdADCTiLLHqzb7G9uXF")
    signature_hash = hashlib.sha256(b"smoke-vault-signature").digest()
    completed_at = 1_713_456_789
    completion_time_s = 2_275
    cal_amount = 1_000_000_000_000_000

    result = await helper(
        config=SimpleNamespace(program_id=PROGRAM_ID),
        staker=staker,
        vault_id=42,
        vault_signature_hash_hex=signature_hash.hex(),
        cal_amount=cal_amount,
        completion_time_s=completion_time_s,
        completed_at=completed_at,
    )

    assert result == "completion-signature"
    assert [name for name, _ in calls] == [
        "record_ride",
        "record_climb_completion",
        "credit_cal",
    ]

    activity_id = (
        f"smoke-devnet:receipt-backed:{staker}:42:{completed_at}:"
        f"{completion_time_s}:{cal_amount}"
    )
    expected_ride_hash = hashlib.sha256(activity_id.encode("utf-8")).digest()
    attestation, _ = smoke._derive_ride_attestation_pda(
        staker, expected_ride_hash, PROGRAM_ID
    )
    vault, _ = smoke._derive_vault_pda(42, PROGRAM_ID)
    expected_evidence_hash = build_climb_completion_evidence_v2(
        ride_attestation=attestation,
        vault=vault,
        completion_time_s=completion_time_s,
        cal_tribute=smoke.measured_smoke_cal_tribute(cal_amount, completion_time_s),
    )

    ride_args = calls[0][1]
    completion_args = calls[1][1]
    credit_args = calls[2][1]
    assert ride_args["ride_hash"] == expected_ride_hash
    assert ride_args["attestation_commitment"] == expected_ride_hash
    assert ride_args["cal_earned"] == cal_amount
    assert ride_args["climbs_crossed"] == 1
    # record_ride's bound: one whole CAL per TSS, IF 40 over the elapsed ride.
    assert ride_args["total_tss"] == 1_000_000
    assert ride_args["completed_at"] - ride_args["started_at"] == 22_500
    assert completion_args["ride_hash"] == expected_ride_hash
    assert completion_args["completion_evidence_version"] == 2
    assert completion_args["completion_evidence_hash"] == expected_evidence_hash
    assert completion_args["cal_tribute"] == smoke.measured_smoke_cal_tribute(
        cal_amount, completion_time_s
    )
    assert credit_args["ride_hash"] == expected_ride_hash
    assert credit_args["amount"] == cal_amount


def test_smoke_rides_declare_the_tss_record_ride_admits() -> None:
    whole = smoke.LAMPORT_DECIMALS
    # Sub-CAL credits declare no TSS and keep the minimum duration.
    assert smoke.smoke_ride_economics(250_000, 3_600) == (0, 3_600)
    # Up to 160,000 CAL fits one hour at IF 40; more stretches the ride.
    assert smoke.smoke_ride_economics(160_000 * whole, 3_600) == (160_000, 3_600)
    assert smoke.smoke_ride_economics(250_000 * whole + 7, 3_600) == (250_000, 5_625)
    assert smoke.smoke_ride_economics(5_760_000 * whole, 1) == (5_760_000, 129_600)
    with pytest.raises(RuntimeError, match="one admissible ride"):
        smoke.smoke_ride_economics(5_760_001 * whole, 1)


def test_resumed_smoke_ride_accepts_bounded_and_pre_bound_shapes() -> None:
    whole = smoke.LAMPORT_DECIMALS
    attestation = Pubkey.default()

    def check(started_at: int, total_tss: int) -> None:
        smoke.require_smoke_ride_shape(
            SimpleNamespace(completed_at=100_000, started_at=started_at, total_tss=total_tss),
            attestation=attestation,
            cal_earned=250_000 * whole,
            minimum_duration_s=3_600,
        )

    check(100_000 - 5_625, 250_000)
    check(100_000 - 3_600, 0)
    for started_at, total_tss in ((100_000 - 3_600, 250_000), (100_000 - 5_625, 0)):
        with pytest.raises(RuntimeError, match="foreign deterministic duration"):
            check(started_at, total_tss)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("receipt_stage", "expected_calls", "expected_result"),
    [
        (
            "attested",
            ["record_climb_completion", "credit_cal"],
            "completion-signature",
        ),
        ("completion_recorded", ["credit_cal"], "cal-signature"),
    ],
)
async def test_smoke_completion_resumes_only_missing_receipt_suffix(
    monkeypatch: pytest.MonkeyPatch,
    receipt_stage: str,
    expected_calls: list[str],
    expected_result: str,
) -> None:
    calls: list[str] = []

    async def record_ride(**kwargs: Any) -> str:
        calls.append("record_ride")
        return "ride-signature"

    async def record_completion(**kwargs: Any) -> str:
        calls.append("record_climb_completion")
        return "completion-signature"

    async def credit_cal(**kwargs: Any) -> str:
        calls.append("credit_cal")
        return "cal-signature"

    monkeypatch.setattr(smoke, "send_record_ride", record_ride)
    monkeypatch.setattr(smoke, "send_record_climb_completion", record_completion)
    monkeypatch.setattr(smoke, "send_credit_cal", credit_cal)

    result = await smoke.record_receipt_backed_tribute(
        config=SimpleNamespace(program_id=PROGRAM_ID),
        staker=Pubkey.from_string(
            "Ch8uwuNxXkQBTJfBNbCq57yhaKdADCTiLLHqzb7G9uXF"
        ),
        vault_id=42,
        vault_signature_hash_hex=hashlib.sha256(b"vault").hexdigest(),
        cal_amount=2_500,
        completion_time_s=2_275,
        completed_at=1_713_456_789,
        receipt_stage=receipt_stage,
    )

    assert calls == expected_calls
    assert result == expected_result


@pytest.mark.asyncio
async def test_smoke_cal_top_up_uses_current_ride_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    async def record_ride(**kwargs: Any) -> str:
        calls.append(("record_ride", kwargs))
        return "ride-signature"

    async def credit_cal(**kwargs: Any) -> str:
        calls.append(("credit_cal", kwargs))
        return "cal-signature"

    monkeypatch.setattr(smoke, "send_record_ride", record_ride)
    monkeypatch.setattr(smoke, "send_credit_cal", credit_cal)
    monkeypatch.setattr(smoke.time, "time", lambda: 1_713_456_789)

    staker = Pubkey.from_string("Ch8uwuNxXkQBTJfBNbCq57yhaKdADCTiLLHqzb7G9uXF")
    result = await smoke.credit_user_cal(
        config=object(),
        staker=staker,
        total_cal_amount=250_000_000_000_000,
    )

    assert result == "cal-signature"
    assert [name for name, _ in calls] == ["record_ride", "credit_cal"]
    ride_args = calls[0][1]
    credit_args = calls[1][1]
    assert ride_args["attestation_commitment"] == ride_args["ride_hash"]
    assert ride_args["climbs_crossed"] == 0
    assert credit_args["ride_hash"] == ride_args["ride_hash"]


def test_wallet_smoke_supplies_vault_signature_hash_to_receipt_path() -> None:
    source = _source(BACKEND_DIR / "scripts" / "smoke_wallet_signed_economics.py")

    assert "ensure_receipt_backed_smoke_flow(" in source
    assert "vault_signature_hash_hex=vault_signature_hash_hex" in source


@pytest.mark.asyncio
async def test_smoke_settlement_accounts_come_from_program_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolver = getattr(smoke, "read_canonical_settlement_accounts", None)
    assert callable(resolver)

    pol_account = Keypair().pubkey()
    treasury_account = Keypair().pubkey()

    async def get_program_config(config: object) -> dict[str, str]:
        return {
            "pol_token_account": str(pol_account),
            "treasury_token_account": str(treasury_account),
        }

    monkeypatch.setattr(smoke, "get_program_config_account", get_program_config)

    assert await resolver(object()) == (pol_account, treasury_account)


@pytest.mark.asyncio
async def test_smoke_prepares_frozen_v0_transport_with_production_manager(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    helper = getattr(smoke, "prepare_smoke_settlement_transport", None)
    assert callable(helper)

    distribution = SimpleNamespace(recipient_ata_instructions=(object(),))
    expected_transport = {"transaction_version": "0", "manifest_sha256": "ab" * 32}
    calls: dict[str, Any] = {}

    async def build_distribution(**kwargs: Any) -> Any:
        calls["build"] = kwargs
        return distribution

    class Manager:
        def __init__(self, *, db: object, config: object) -> None:
            calls["manager"] = {"db": db, "config": config}

        async def prepare(self, **kwargs: Any) -> dict[str, str]:
            calls["prepare"] = kwargs
            return expected_transport

    database = object()
    config = object()
    monkeypatch.setattr(smoke, "build_settlement_distribution_plan", build_distribution)
    monkeypatch.setattr(smoke, "SettlementTransportManager", Manager)
    monkeypatch.setattr(smoke, "get_supabase_client", lambda: database)

    result = await helper(config=config, vault_id=42, settlement_week=131)

    assert result == expected_transport
    assert calls["build"] == {
        "config": config,
        "vault_id": 42,
        "settlement_week": 131,
    }
    assert calls["manager"] == {"db": database, "config": config}
    assert calls["prepare"]["distribution"] is distribution
    assert calls["prepare"]["compute_unit_limit"] == smoke.SETTLEMENT_COMPUTE_UNIT_LIMIT


def test_smoke_settlement_stage_is_exact_and_age_bounded() -> None:
    inspect_stage = getattr(smoke, "inspect_smoke_settlement_stage", None)
    assert callable(inspect_stage)

    class Clock:
        @staticmethod
        def week_finalization_time(settlement_week: int) -> int:
            assert settlement_week == 42
            return 100

        @staticmethod
        def week_start(settlement_week: int) -> int:
            return 30 - 86_400

        @staticmethod
        def week_end(settlement_week: int) -> int:
            assert settlement_week == 42
            return 90

    assert inspect_stage(_vault_state(), Clock(), 42, 99, 2_500).stage == "pristine"

    pristine = inspect_stage(_vault_state(), Clock(), 42, 100, 2_500)
    assert pristine.stage == "pristine"
    assert pristine.completed_at == 30
    assert pristine.expected_pending_rewards == 2
    assert pristine.expected_cal_remainder == 500

    with pytest.raises(RuntimeError, match="unexpected settlement flow"):
        inspect_stage(_vault_state(pending_rewards=1), Clock(), 42, 100, 2_500)
    assert (
        inspect_stage(
            _vault_state(pending_rewards=2, cal_tribute_accumulated=500),
            Clock(),
            42,
            100,
            2_500,
        ).stage
        == "completed"
    )
    with pytest.raises(RuntimeError, match="unexpected settlement flow"):
        inspect_stage(_vault_state(pending_rewards=4), Clock(), 42, 100, 2_500)
    with pytest.raises(RuntimeError, match="unexpected settlement flow"):
        inspect_stage(
            _vault_state(cal_tribute_accumulated_next=1),
            Clock(),
            42,
            100,
            2_500,
        )

    distributed = inspect_stage(
        _vault_state(
            open_settlement_week=43,
            last_distribution_epoch=42,
            carry_stakers=7,
        ),
        Clock(),
        42,
        100,
        2_500,
    )
    assert distributed.stage == "distributed"

    admin_deposit = smoke.SMOKE_ADMIN_VAULT_CAL_DEPOSIT
    admin_plan = inspect_stage(
        _vault_state(cal_tribute_accumulated=admin_deposit),
        Clock(),
        42,
        100,
        2_500,
        initial_cal_tribute=admin_deposit,
    )
    assert admin_plan.stage == "pristine"
    assert admin_plan.expected_pending_rewards == (admin_deposit + 2_500) // 1_000
    assert admin_plan.expected_cal_remainder == (admin_deposit + 2_500) % 1_000


def test_smoke_admission_window_uses_immutable_attestation_clock_on_retry() -> None:
    validate_admission = getattr(smoke, "validate_smoke_admission_window", None)
    assert callable(validate_admission)

    completed_at = 1_000
    with pytest.raises(RuntimeError, match="30-day ride admission"):
        validate_admission(
            completed_at=completed_at,
            current_time=completed_at + smoke.MAX_RIDE_AGE_SECONDS + 1,
            settled_at=None,
        )

    validate_admission(
        completed_at=completed_at,
        current_time=completed_at + smoke.MAX_RIDE_AGE_SECONDS + 10_000,
        settled_at=completed_at + smoke.MAX_RIDE_AGE_SECONDS,
    )
    with pytest.raises(RuntimeError, match="attestation admission clock"):
        validate_admission(
            completed_at=completed_at,
            current_time=completed_at,
            settled_at=completed_at + smoke.MAX_RIDE_AGE_SECONDS + 1,
        )


def test_aggregate_completion_requires_matching_receipt_progress() -> None:
    require_consistency = getattr(smoke, "require_smoke_flow_consistency", None)
    assert callable(require_consistency)

    require_consistency("pristine", "absent")
    require_consistency("seeded", "attested")
    require_consistency("completed", "completion_recorded")
    require_consistency("completed", "settled")
    require_consistency("distributed", "settled")
    with pytest.raises(RuntimeError, match="receipt evidence"):
        require_consistency("completed", "absent")
    with pytest.raises(RuntimeError, match="receipt evidence"):
        require_consistency("distributed", "completion_recorded")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("present", "expected_stage"),
    [
        ((False, False, False), "absent"),
        ((True, False, False), "attested"),
        ((True, True, False), "completion_recorded"),
        ((True, True, True), "settled"),
    ],
)
async def test_receipt_stage_uses_one_decoded_finalized_prefix(
    monkeypatch: pytest.MonkeyPatch,
    present: tuple[bool, bool, bool],
    expected_stage: str,
) -> None:
    program_id = Pubkey.from_string("BPFLoaderUpgradeab1e11111111111111111111111")
    raw = SimpleNamespace(owner=program_id, data=b"account")

    async def read_snapshot(rpc_url: str, addresses: tuple[Pubkey, ...]) -> Any:
        assert rpc_url == "https://rpc.invalid"
        assert len(addresses) == 3
        return SimpleNamespace(
            slot=123,
            accounts=tuple(raw if exists else None for exists in present),
        )

    monkeypatch.setattr(smoke, "read_finalized_chain_snapshot", read_snapshot)
    monkeypatch.setattr(
        smoke,
        "decode_ride_attestation",
        lambda data: SimpleNamespace(
            settled_at=100, completed_at=30, started_at=0, total_tss=0
        ),
    )
    monkeypatch.setattr(smoke, "decode_climb_completion_receipt", lambda data: object())
    monkeypatch.setattr(smoke, "decode_cal_mint_receipt", lambda data: object())
    monkeypatch.setattr(smoke, "validate_ride_attestation", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        smoke, "validate_climb_completion_receipt", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(smoke, "validate_cal_mint_receipt", lambda *args, **kwargs: None)

    stage = await smoke.read_smoke_receipt_stage(
        config=SimpleNamespace(program_id=program_id, rpc_url="https://rpc.invalid"),
        staker=Pubkey.from_string("Ch8uwuNxXkQBTJfBNbCq57yhaKdADCTiLLHqzb7G9uXF"),
        vault_id=42,
        vault_signature_hash_hex=hashlib.sha256(b"vault").hexdigest(),
        cal_amount=2_500,
        completion_time_s=2_275,
        completed_at=30,
        current_time=100,
    )

    assert stage == expected_stage


@pytest.mark.asyncio
async def test_receipt_stage_rejects_non_prefix_or_foreign_accounts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    program_id = Pubkey.from_string("BPFLoaderUpgradeab1e11111111111111111111111")
    raw = SimpleNamespace(owner=program_id, data=b"account")

    async def invalid_prefix(rpc_url: str, addresses: tuple[Pubkey, ...]) -> Any:
        return SimpleNamespace(slot=123, accounts=(raw, None, raw))

    monkeypatch.setattr(smoke, "read_finalized_chain_snapshot", invalid_prefix)
    monkeypatch.setattr(
        smoke,
        "decode_ride_attestation",
        lambda data: SimpleNamespace(
            settled_at=100, completed_at=30, started_at=0, total_tss=0
        ),
    )
    monkeypatch.setattr(smoke, "validate_ride_attestation", lambda *args, **kwargs: None)

    kwargs = {
        "config": SimpleNamespace(program_id=program_id, rpc_url="https://rpc.invalid"),
        "staker": Pubkey.from_string(
            "Ch8uwuNxXkQBTJfBNbCq57yhaKdADCTiLLHqzb7G9uXF"
        ),
        "vault_id": 42,
        "vault_signature_hash_hex": hashlib.sha256(b"vault").hexdigest(),
        "cal_amount": 2_500,
        "completion_time_s": 2_275,
        "completed_at": 30,
        "current_time": 100,
    }
    with pytest.raises(RuntimeError, match="valid prefix"):
        await smoke.read_smoke_receipt_stage(**kwargs)

    foreign = SimpleNamespace(owner=Pubkey.default(), data=b"account")

    async def foreign_owner(rpc_url: str, addresses: tuple[Pubkey, ...]) -> Any:
        return SimpleNamespace(slot=123, accounts=(foreign, None, None))

    monkeypatch.setattr(smoke, "read_finalized_chain_snapshot", foreign_owner)
    with pytest.raises(RuntimeError, match="not owned"):
        await smoke.read_smoke_receipt_stage(**kwargs)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    (
        "initial_state",
        "initial_receipt_stage",
        "expected_seed_calls",
        "expected_completion_calls",
    ),
    [
        (_vault_state(), "absent", 0, 1),
        (_vault_state(), "absent", 0, 1),
        (_vault_state(), "attested", 0, 1),
        (
            _vault_state(pending_rewards=0, cal_tribute_accumulated=250),
            "completion_recorded",
            0,
            1,
        ),
        (
            _vault_state(pending_rewards=0, cal_tribute_accumulated=250),
            "settled",
            0,
            0,
        ),
    ],
)
async def test_receipt_flow_resumes_exact_pre_distribution_stage(
    monkeypatch: pytest.MonkeyPatch,
    initial_state: dict[str, int],
    initial_receipt_stage: str,
    expected_seed_calls: int,
    expected_completion_calls: int,
) -> None:
    ensure_flow = getattr(smoke, "ensure_receipt_backed_smoke_flow", None)
    assert callable(ensure_flow)

    class Clock:
        @staticmethod
        def week_finalization_time(settlement_week: int) -> int:
            return 100

        @staticmethod
        def week_start(settlement_week: int) -> int:
            return 30 - 86_400

        @staticmethod
        def week_end(settlement_week: int) -> int:
            return 90

    states = [
        initial_state,
        _vault_state(pending_rewards=0, cal_tribute_accumulated=250),
    ]
    calls: list[str] = []
    receipt_stages = [initial_receipt_stage, "settled"]

    async def read_state(config: object, vault_id: int) -> dict[str, int]:
        assert vault_id == 42
        return states.pop(0)

    async def seed(**kwargs: Any) -> str:
        calls.append("seed")
        assert kwargs["pending_rewards"] == 1
        return "seed-signature"

    async def complete(**kwargs: Any) -> str:
        calls.append("complete")
        assert kwargs["receipt_stage"] == initial_receipt_stage
        return "completion-signature"

    async def receipt_stage(**kwargs: Any) -> str:
        calls.append("receipts")
        return receipt_stages.pop(0)

    monkeypatch.setattr(smoke, "read_vault_state", read_state)
    monkeypatch.setattr(smoke, "send_admin_seed_pending_rewards", seed, raising=False)
    monkeypatch.setattr(smoke, "record_receipt_backed_tribute", complete)
    monkeypatch.setattr(smoke, "read_smoke_receipt_stage", receipt_stage)

    plan = await ensure_flow(
        config=object(),
        settlement_clock=Clock(),
        staker=Pubkey.from_string("Ch8uwuNxXkQBTJfBNbCq57yhaKdADCTiLLHqzb7G9uXF"),
        vault_id=42,
        settlement_week=42,
        vault_signature_hash_hex=hashlib.sha256(b"vault").hexdigest(),
        cal_amount=2_500,
        completion_time_s=2_275,
        current_time=100,
        retry_delay_s=0,
    )

    assert plan.stage == "completed"
    assert calls.count("seed") == expected_seed_calls
    assert calls.count("complete") == expected_completion_calls
    assert calls[-1] == "receipts"


@pytest.mark.asyncio
async def test_receipt_flow_retries_transient_post_mutation_snapshot_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Clock:
        @staticmethod
        def week_finalization_time(settlement_week: int) -> int:
            return 100

        @staticmethod
        def week_start(settlement_week: int) -> int:
            return 30 - 86_400

        @staticmethod
        def week_end(settlement_week: int) -> int:
            return 90

    states = [
        _vault_state(),
        _vault_state(pending_rewards=0, cal_tribute_accumulated=250),
        _vault_state(pending_rewards=0, cal_tribute_accumulated=250),
    ]
    receipt_stages = ["absent", "attested", "settled"]

    async def read_state(config: object, vault_id: int) -> dict[str, int]:
        return states.pop(0)

    async def receipts(**kwargs: Any) -> str:
        return receipt_stages.pop(0)

    async def seed(**kwargs: Any) -> str:
        return "seed-signature"

    async def complete(**kwargs: Any) -> str:
        return "completion-signature"

    monkeypatch.setattr(smoke, "read_vault_state", read_state)
    monkeypatch.setattr(smoke, "read_smoke_receipt_stage", receipts)
    monkeypatch.setattr(smoke, "send_admin_seed_pending_rewards", seed, raising=False)
    monkeypatch.setattr(smoke, "record_receipt_backed_tribute", complete)

    plan = await smoke.ensure_receipt_backed_smoke_flow(
        config=object(),
        settlement_clock=Clock(),
        staker=Pubkey.from_string("Ch8uwuNxXkQBTJfBNbCq57yhaKdADCTiLLHqzb7G9uXF"),
        vault_id=42,
        settlement_week=42,
        vault_signature_hash_hex=hashlib.sha256(b"vault").hexdigest(),
        cal_amount=2_500,
        completion_time_s=2_275,
        current_time=100,
        retry_attempts=3,
        retry_delay_s=0,
    )

    assert plan.stage == "completed"
    assert states == []
    assert receipt_stages == []


@pytest.mark.asyncio
async def test_aggregate_collision_fails_before_second_completion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_flow = getattr(smoke, "ensure_receipt_backed_smoke_flow", None)
    assert callable(ensure_flow)

    class Clock:
        @staticmethod
        def week_finalization_time(settlement_week: int) -> int:
            return 100

        @staticmethod
        def week_start(settlement_week: int) -> int:
            return 30 - 86_400

        @staticmethod
        def week_end(settlement_week: int) -> int:
            return 90

    async def read_state(config: object, vault_id: int) -> dict[str, int]:
        return _vault_state(pending_rewards=0, cal_tribute_accumulated=250)

    async def receipt_stage(**kwargs: Any) -> str:
        return "absent"

    async def forbidden(**kwargs: Any) -> str:
        raise AssertionError("aggregate collision must fail before mutation")

    monkeypatch.setattr(smoke, "read_vault_state", read_state)
    monkeypatch.setattr(smoke, "read_smoke_receipt_stage", receipt_stage)
    monkeypatch.setattr(smoke, "record_receipt_backed_tribute", forbidden)

    with pytest.raises(RuntimeError, match="receipt evidence"):
        await ensure_flow(
            config=object(),
            settlement_clock=Clock(),
            staker=Pubkey.from_string(
                "Ch8uwuNxXkQBTJfBNbCq57yhaKdADCTiLLHqzb7G9uXF"
            ),
            vault_id=42,
            settlement_week=42,
            vault_signature_hash_hex=hashlib.sha256(b"vault").hexdigest(),
            cal_amount=2_500,
            completion_time_s=2_275,
            current_time=100,
            retry_attempts=1,
            retry_delay_s=0,
        )


@pytest.mark.asyncio
async def test_receipt_flow_distributed_resume_only_verifies_receipts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_flow = getattr(smoke, "ensure_receipt_backed_smoke_flow", None)
    assert callable(ensure_flow)

    class Clock:
        @staticmethod
        def week_finalization_time(settlement_week: int) -> int:
            return 100

        @staticmethod
        def week_start(settlement_week: int) -> int:
            return 30 - 86_400

        @staticmethod
        def week_end(settlement_week: int) -> int:
            return 90

    calls: list[str] = []

    async def read_state(config: object, vault_id: int) -> dict[str, int]:
        return _vault_state(open_settlement_week=43, last_distribution_epoch=42)

    async def forbidden(**kwargs: Any) -> str:
        raise AssertionError("distributed resume must not mutate completion flow")

    async def receipts(**kwargs: Any) -> str:
        calls.append("receipts")
        return "settled"

    monkeypatch.setattr(smoke, "read_vault_state", read_state)
    monkeypatch.setattr(smoke, "send_admin_seed_pending_rewards", forbidden, raising=False)
    monkeypatch.setattr(smoke, "record_receipt_backed_tribute", forbidden)
    monkeypatch.setattr(smoke, "read_smoke_receipt_stage", receipts)

    plan = await ensure_flow(
        config=object(),
        settlement_clock=Clock(),
        staker=Pubkey.from_string("Ch8uwuNxXkQBTJfBNbCq57yhaKdADCTiLLHqzb7G9uXF"),
        vault_id=42,
        settlement_week=42,
        vault_signature_hash_hex=hashlib.sha256(b"vault").hexdigest(),
        cal_amount=2_500,
        completion_time_s=2_275,
        current_time=100,
        retry_delay_s=0,
    )

    assert plan.stage == "distributed"
    assert calls == ["receipts"]


def test_smoke_stake_stage_rejects_foreign_or_fractional_positions() -> None:
    inspect_stake = getattr(smoke, "inspect_smoke_stake_stage", None)
    assert callable(inspect_stake)

    assert inspect_stake(_vault_state(), None, 100, distributed=False) == "pristine"
    assert (
        inspect_stake(
            _vault_state(total_cal_staked=100, staker_count=1),
            {"cal_staked": 100, "lp_tokens": 100},
            100,
            distributed=False,
        )
        == "staked"
    )
    with pytest.raises(RuntimeError, match="persistent stake account"):
        inspect_stake(_vault_state(), None, 100, distributed=True)
    with pytest.raises(RuntimeError, match="zero staker reward"):
        inspect_stake(
            _vault_state(total_cal_staked=100, staker_count=1),
            {"cal_staked": 100, "lp_tokens": 100, "rewards_earned": 0},
            100,
            distributed=True,
        )
    assert (
        inspect_stake(
            _vault_state(total_cal_staked=100, staker_count=1),
            {"cal_staked": 100, "lp_tokens": 100, "rewards_earned": 7},
            100,
            distributed=True,
        )
        == "staked"
    )
    assert (
        inspect_stake(
            _vault_state(staker_count=1),
            {
                "cal_staked": 0,
                "lp_tokens": 0,
                "rewards_earned": 7,
                "effective_lp_tokens": 100,
            },
            100,
            distributed=True,
        )
        == "withdrawn"
    )
    assert (
        inspect_stake(
            _vault_state(staker_count=1),
            {
                "cal_staked": 0,
                "lp_tokens": 0,
                "rewards_earned": 0,
                "effective_lp_tokens": 100,
            },
            100,
            distributed=True,
        )
        == "complete"
    )
    with pytest.raises(RuntimeError, match="unexpected stake state"):
        inspect_stake(
            _vault_state(total_cal_staked=101, staker_count=1),
            {"cal_staked": 101, "lp_tokens": 100},
            100,
            distributed=False,
        )


def test_smoke_resume_arguments_require_exact_flow_identity() -> None:
    validate_args = getattr(smoke, "validate_smoke_resume_args", None)
    assert callable(validate_args)

    validate_args(existing_vault_id=None, settlement_week=None)
    validate_args(existing_vault_id=0, settlement_week=41)
    validate_args(existing_vault_id=42, settlement_week=41)
    with pytest.raises(RuntimeError, match="--settlement-week is required"):
        validate_args(existing_vault_id=42, settlement_week=None)
    with pytest.raises(RuntimeError, match="--existing-vault-id is required"):
        validate_args(existing_vault_id=None, settlement_week=41)
    with pytest.raises(RuntimeError, match="non-negative"):
        validate_args(existing_vault_id=-1, settlement_week=41)


def test_wallet_rehearsal_identity_is_required_for_fresh_and_resume() -> None:
    validate = getattr(wallet_smoke, "validate_wallet_rehearsal_args", None)
    assert callable(validate)

    rehearsal_program = str(Keypair().pubkey())
    rehearsal_cal = str(Keypair().pubkey())
    rehearsal_dung = str(Keypair().pubkey())
    rehearsal_climb = str(Keypair().pubkey())

    def args(**overrides: Any) -> SimpleNamespace:
        values = {
            "existing_vault_id": 0,
            "settlement_week": 41,
            "rehearsal_lane": True,
            "program_id": rehearsal_program,
            "cal_mint": rehearsal_cal,
            "dung_mint": rehearsal_dung,
            "climb_pda": None,
            "user_cal": 250_000,
            "rehearsal_transport_state": "/tmp/rehearsal-transport.json",
            "rehearsal_evidence": "/tmp/rehearsal-evidence.json",
            "rehearsal_setup_evidence": "/tmp/rehearsal-setup.json",
        }
        values.update(overrides)
        return SimpleNamespace(**values)

    validate(args())
    validate(
        args(
            existing_vault_id=None,
            settlement_week=None,
            climb_pda=rehearsal_climb,
        )
    )

    with pytest.raises(RuntimeError, match="--rehearsal-lane"):
        validate(args(rehearsal_lane=False))
    with pytest.raises(RuntimeError, match="non-registry --program-id"):
        validate(args(program_id=str(wallet_smoke.DEFAULT_BOULDER_ROLLERS_PROGRAM_ID)))
    with pytest.raises(RuntimeError, match="non-registry --cal-mint"):
        validate(args(cal_mint=str(wallet_smoke.DEFAULT_CAL_MINT_ADDRESS)))
    with pytest.raises(RuntimeError, match="non-registry --dung-mint"):
        validate(args(dung_mint=str(wallet_smoke.DEFAULT_DUNG_MINT_ADDRESS)))
    with pytest.raises(RuntimeError, match="explicit --program-id"):
        validate(args(program_id=None))
    with pytest.raises(RuntimeError, match="already-registered --climb-pda"):
        validate(args(existing_vault_id=None, settlement_week=None))
    with pytest.raises(RuntimeError, match="protected canonical Shawmont"):
        validate(
            args(
                existing_vault_id=None,
                settlement_week=None,
                climb_pda=str(wallet_smoke.PROTECTED_SHAWMONT_CLIMB),
            )
        )


@pytest.mark.asyncio
async def test_smoke_cal_top_up_can_use_deterministic_resume_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ride_hashes: list[bytes] = []

    async def record_ride(**kwargs: Any) -> str:
        ride_hashes.append(kwargs["ride_hash"])
        return "ride-signature"

    async def credit_cal(**kwargs: Any) -> str:
        assert kwargs["ride_hash"] == ride_hashes[-1]
        return "cal-signature"

    monkeypatch.setattr(smoke, "send_record_ride", record_ride)
    monkeypatch.setattr(smoke, "send_credit_cal", credit_cal)
    staker = Pubkey.from_string("Ch8uwuNxXkQBTJfBNbCq57yhaKdADCTiLLHqzb7G9uXF")

    for wall_time in (1_713_456_789, 1_713_456_999):
        monkeypatch.setattr(smoke.time, "time", lambda: wall_time)
        await smoke.credit_user_cal(
            config=object(),
            staker=staker,
            total_cal_amount=250_000,
            activity_id="smoke-top-up:42:41",
            completed_at=1_713_400_000,
        )

    assert ride_hashes[0] == ride_hashes[1]


@pytest.mark.asyncio
async def test_smoke_cal_credit_resumes_exact_receipt_prefix_without_re_recording(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    helper = getattr(smoke, "ensure_user_cal_credit", None)
    assert callable(helper)

    staker = Keypair().pubkey()
    config = SimpleNamespace(program_id=PROGRAM_ID, rpc_url="http://rpc.test")
    attestation_account = SimpleNamespace(owner=PROGRAM_ID, data=b"attestation")
    receipt_account = SimpleNamespace(owner=PROGRAM_ID, data=b"receipt")
    snapshots = iter(
        (
            SimpleNamespace(slot=11, accounts=(attestation_account, None)),
            SimpleNamespace(
                slot=12,
                accounts=(attestation_account, receipt_account),
            ),
        )
    )
    calls: list[str] = []

    async def read_snapshot(rpc_url: str, addresses: tuple[Pubkey, Pubkey]) -> Any:
        assert rpc_url == config.rpc_url
        assert len(addresses) == 2
        return next(snapshots)

    async def reject_record(**kwargs: Any) -> str:
        raise AssertionError("an existing attestation must not be recorded again")

    async def credit(**kwargs: Any) -> str:
        calls.append("credit")
        return "credit-signature"

    decoded_attestation = SimpleNamespace(completed_at=3_700, started_at=100, total_tss=0)
    monkeypatch.setattr(smoke, "read_finalized_chain_snapshot", read_snapshot)
    monkeypatch.setattr(smoke, "decode_ride_attestation", lambda data: decoded_attestation)
    monkeypatch.setattr(smoke, "decode_cal_mint_receipt", lambda data: object())
    monkeypatch.setattr(smoke, "validate_ride_attestation", lambda *args, **kwargs: None)
    monkeypatch.setattr(smoke, "validate_cal_mint_receipt", lambda *args, **kwargs: None)
    monkeypatch.setattr(smoke, "send_record_ride", reject_record)
    monkeypatch.setattr(smoke, "send_credit_cal", credit)

    first = await helper(
        config=config,
        staker=staker,
        total_cal_amount=250_000,
        activity_id="exact-rehearsal-funding",
        completed_at=123,
    )
    second = await helper(
        config=config,
        staker=staker,
        total_cal_amount=250_000,
        activity_id="exact-rehearsal-funding",
        completed_at=999,
    )

    assert first == "credit-signature"
    assert calls == ["credit"]
    assert "CalMintReceipt" in second


@pytest.mark.asyncio
async def test_settlement_transport_config_is_checked_read_only_before_smoke_mutation(
    tmp_path: Path,
) -> None:
    helper = getattr(
        smoke,
        "preflight_smoke_settlement_transport_prerequisites",
        None,
    )
    assert callable(helper)

    program_id = Keypair().pubkey()
    authority = Keypair().pubkey()
    state_path = tmp_path / "transport.json"
    database = await helper(
        state_path=state_path,
        program_id=program_id,
        authority=authority,
    )
    assert state_path.exists()
    assert database.path == state_path
    assert "generations" in state_path.read_text(encoding="utf-8")
    database.release_run_lock()

    resumed = await helper(
        state_path=state_path,
        program_id=program_id,
        authority=authority,
    )
    assert resumed.path == state_path
    resumed.release_run_lock()

    with pytest.raises(RuntimeError, match="absolute JSON path"):
        await helper(
            state_path=Path("relative.json"),
            program_id=program_id,
            authority=authority,
        )


def test_rehearsal_transport_store_resumes_planned_and_active_generations(
    tmp_path: Path,
) -> None:
    program_id = Keypair().pubkey()
    authority = Keypair().pubkey()
    first_lookup = Keypair().pubkey()
    second_lookup = Keypair().pubkey()
    state_path = tmp_path / "transport.json"

    first = smoke.RehearsalSettlementTransportStore(
        path=state_path,
        program_id=program_id,
        authority=authority,
    )
    planned = first.rpc(
        "br_get_or_plan_settlement_lookup_table",
        {
            "p_vault_id": "0",
            "p_program_id": str(program_id),
            "p_authority": str(authority),
            "p_recent_slot": "11",
            "p_lookup_table_address": str(first_lookup),
        },
    ).execute().data[0]
    assert planned["status"] == "planned"

    resumed_planned = smoke.RehearsalSettlementTransportStore(
        path=state_path,
        program_id=program_id,
        authority=authority,
    ).rpc(
        "br_get_or_plan_settlement_lookup_table",
        {
            "p_vault_id": "0",
            "p_program_id": str(program_id),
            "p_authority": str(authority),
            "p_recent_slot": "12",
            "p_lookup_table_address": str(second_lookup),
        },
    ).execute().data[0]
    assert resumed_planned["id"] == planned["id"]
    assert resumed_planned["lookup_table_address"] == str(first_lookup)

    first.rpc(
        "br_record_settlement_lookup_table_ready",
        {
            "p_generation_id": planned["id"],
            "p_create_tx_signature": "create-signature",
            "p_last_tx_signature": "extend-signature",
            "p_last_extended_slot": "13",
            "p_address_count": 9,
            "p_manifest_sha256": "ab" * 32,
        },
    ).execute()
    resumed_active = smoke.RehearsalSettlementTransportStore(
        path=state_path,
        program_id=program_id,
        authority=authority,
    ).rpc(
        "br_get_or_plan_settlement_lookup_table",
        {
            "p_vault_id": "0",
            "p_program_id": str(program_id),
            "p_authority": str(authority),
            "p_recent_slot": "14",
            "p_lookup_table_address": str(second_lookup),
        },
    ).execute().data[0]
    assert resumed_active["id"] == planned["id"]
    assert resumed_active["status"] == "active"
    assert json.loads(state_path.read_text(encoding="utf-8"))["generations"][0][
        "manifest_sha256"
    ] == "ab" * 32


@pytest.mark.asyncio
async def test_rehearsal_transport_preflight_rejects_malformed_active_state(
    tmp_path: Path,
) -> None:
    program_id = Keypair().pubkey()
    authority = Keypair().pubkey()
    state_path = tmp_path / "transport.json"
    state_path.write_text(
        json.dumps(
            {
                "schema": smoke.REHEARSAL_TRANSPORT_SCHEMA,
                "program_id": str(program_id),
                "authority": str(authority),
                "generations": [
                    {
                        "id": "generation-1",
                        "vault_id": "0",
                        "program_id": str(program_id),
                        "generation": 1,
                        "lookup_table_address": str(Keypair().pubkey()),
                        "authority": str(authority),
                        "recent_slot": "12",
                        "status": "active",
                        "create_tx_signature": None,
                        "last_tx_signature": None,
                        "last_extended_slot": None,
                        "address_count": 0,
                        "manifest_sha256": None,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="not ready before chain mutation"):
        await smoke.preflight_smoke_settlement_transport_prerequisites(
            state_path=state_path,
            program_id=program_id,
            authority=authority,
        )


def _evidence_state(
    *,
    protected: Pubkey,
    program_id: Pubkey,
    cal_mint: Pubkey,
    dung_mint: Pubkey,
    user: Pubkey,
    climb: Pubkey,
    vault_id: int,
    expected_vault: Pubkey,
    transport_path: Path,
    settlement_week: int | None = 42,
) -> dict[str, Any]:
    baseline_account = {
        "address": str(protected),
        "exists": True,
        "owner": str(program_id),
        "lamports": 1,
        "executable": False,
        "data_len": 1,
        "data_sha256": "ab" * 32,
        "decoded": None,
    }
    return {
        "schema": "boulderroller_v4b_rehearsal_evidence_v2",
        "identity": {
            "program_id": str(program_id),
            "cal_mint": str(cal_mint),
            "dung_mint": str(dung_mint),
            "usdc_mint": str(Keypair().pubkey()),
            "usdc_treasury": str(Keypair().pubkey()),
            "user": str(user),
            "climb_pda": str(climb),
            "vault_id": vault_id,
            "expected_vault": str(expected_vault),
            "settlement_week": settlement_week,
            "transport_state_path": str(transport_path.resolve()),
            "vault_creation_cal": 0,
            "vault_creation_cal_base_units": 0,
            "vault_creation_usdc": 0,
            "harvest_fee_bps": 0,
            "user_cal": 0,
            "stake_cal": 0,
            "vault_alloc_cal": 0,
            "setup_evidence_path": None,
            "setup_evidence_sha256": None,
            "initial_usdc_supply": 0,
        },
        "protected_addresses": {"protected": str(protected)},
        "rehearsal_addresses": {},
        "dynamic_rehearsal_addresses": {},
        "baseline": {
            "protected_slot": 1,
            "rehearsal_slot": 1,
            "protected": {"protected": baseline_account},
            "rehearsal": {},
        },
        "transactions": [],
        "reconciliations": [],
    }


def test_rehearsal_evidence_refuses_protected_accounts_and_records_order(
    tmp_path: Path,
) -> None:
    program_id = Keypair().pubkey()
    protected = Keypair().pubkey()
    payer = Keypair()
    state = _evidence_state(
        protected=protected,
        program_id=program_id,
        cal_mint=Keypair().pubkey(),
        dung_mint=Keypair().pubkey(),
        user=Keypair().pubkey(),
        climb=Keypair().pubkey(),
        vault_id=0,
        expected_vault=Keypair().pubkey(),
        transport_path=tmp_path / "transport.json",
    )
    evidence_path = tmp_path / "evidence.json"
    manifest = wallet_smoke.RehearsalEvidenceManifest(
        path=evidence_path,
        rpc_url="http://rpc.test",
        state=state,
    )
    discriminator = lambda name: hashlib.sha256(
        f"global:{name}".encode("utf-8")
    ).digest()[:8]
    protected_ix = Instruction(
        program_id=program_id,
        accounts=[AccountMeta(protected, False, False)],
        data=discriminator("credit_cal"),
    )
    protected_tx = Transaction.new_signed_with_payer(
        [protected_ix],
        payer.pubkey(),
        [payer],
        Hash.default(),
    )
    with pytest.raises(RuntimeError, match="protected canonical accounts"):
        manifest.record_prepared_transaction(protected_tx, (), {"tx_type": "test"})
    assert not evidence_path.exists()

    raw_spl_ix = Instruction(
        program_id=wallet_smoke.TOKEN_PROGRAM_ID,
        accounts=[AccountMeta(protected, False, True)],
        data=b"\x07" + (1).to_bytes(8, "little"),
    )
    raw_spl_tx = Transaction.new_signed_with_payer(
        [raw_spl_ix],
        payer.pubkey(),
        [payer],
        Hash.default(),
    )
    with pytest.raises(RuntimeError, match="protected canonical accounts"):
        manifest.record_prepared_transaction(
            raw_spl_tx, (), {"tx_type": "rehearsal_usdc_mint_to"}
        )
    assert not evidence_path.exists()

    collect_ix = Instruction(
        program_id=program_id,
        accounts=[],
        data=discriminator("collect_stake_rewards_for"),
    )
    unstake_ix = Instruction(
        program_id=program_id,
        accounts=[],
        data=discriminator("unstake_cal_from_vault"),
    )
    safe_tx = Transaction.new_signed_with_payer(
        [collect_ix, unstake_ix],
        payer.pubkey(),
        [payer],
        Hash.default(),
    )
    manifest.record_prepared_transaction(safe_tx, (), {"tx_type": "wallet_signed"})
    signature = str(safe_tx.signatures[0])
    manifest.record_finalized_transaction(signature, 77, "finalized", {})
    saved = json.loads(evidence_path.read_text(encoding="utf-8"))
    tx = saved["transactions"][0]
    assert tx["signature"] == signature
    assert tx["slot"] == 77
    assert [
        instruction["instruction_name"] for instruction in tx["instruction_order"]
    ] == ["collect_stake_rewards_for", "unstake_cal_from_vault"]


@pytest.mark.asyncio
@pytest.mark.parametrize("persisted_status", ("prepared", "confirmed"))
async def test_rehearsal_evidence_recovers_pending_create_once_without_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    persisted_status: str,
) -> None:
    program_id = Keypair().pubkey()
    payer = Keypair()
    evidence_path = tmp_path / "confirmed-create.json"
    manifest = wallet_smoke.RehearsalEvidenceManifest(
        path=evidence_path,
        rpc_url="http://rpc.test",
        state=_evidence_state(
            protected=Keypair().pubkey(),
            program_id=program_id,
            cal_mint=Keypair().pubkey(),
            dung_mint=Keypair().pubkey(),
            user=Keypair().pubkey(),
            climb=Keypair().pubkey(),
            vault_id=0,
            expected_vault=Keypair().pubkey(),
            transport_path=tmp_path / "transport.json",
        ),
    )
    create_ix = Instruction(
        program_id=program_id,
        accounts=[],
        data=hashlib.sha256(b"global:create_vault_with_usdc").digest()[:8],
    )
    transaction = Transaction.new_signed_with_payer(
        [create_ix], payer.pubkey(), [payer], Hash.default()
    )
    manifest.record_prepared_transaction(
        transaction,
        (),
        {
            "tx_type": "wallet_signed",
            "recent_blockhash": str(Hash.default()),
            "last_valid_block_height": 100,
        },
    )
    signature = str(transaction.signatures[0])
    if persisted_status == "confirmed":
        manifest.record_finalized_transaction(signature, 77, "confirmed", {})
    before = json.loads(evidence_path.read_text(encoding="utf-8"))["transactions"][0]
    recovered: list[str] = []

    async def reconcile(value: str) -> int:
        recovered.append(value)
        manifest.record_finalized_transaction(value, 77, "finalized", {})
        return 77

    async def reconcile_entry(entry: dict[str, Any]) -> None:
        await reconcile(str(entry["signature"]))

    monkeypatch.setattr(manifest, "reconcile_prepared_transaction", reconcile_entry)
    await manifest.reconcile_prepared_transactions()
    await manifest.reconcile_prepared_transactions()

    after = json.loads(evidence_path.read_text(encoding="utf-8"))["transactions"][0]
    assert recovered == [signature]
    assert after["status"] == "finalized"
    assert after["slot"] == 77
    assert after["account_set"] == before["account_set"]
    assert after["instruction_order"] == before["instruction_order"]
    assert manifest.has_finalized_instruction("create_vault_with_usdc")
    with pytest.raises(RuntimeError, match="status cannot regress"):
        manifest.record_finalized_transaction(signature, 77, "confirmed", {})


@pytest.mark.asyncio
async def test_prepared_attempt_round_trips_to_proven_expiry_then_explicit_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    program_id = Keypair().pubkey()
    payer = Keypair()
    evidence_path = tmp_path / "expiry-retry.json"
    state = _evidence_state(
        protected=Keypair().pubkey(),
        program_id=program_id,
        cal_mint=Keypair().pubkey(),
        dung_mint=Keypair().pubkey(),
        user=Keypair().pubkey(),
        climb=Keypair().pubkey(),
        vault_id=0,
        expected_vault=Keypair().pubkey(),
        transport_path=tmp_path / "transport.json",
    )
    first_hash = Hash.new_unique()
    instruction = Instruction(
        program_id=program_id,
        accounts=[],
        data=hashlib.sha256(b"global:create_vault_with_usdc").digest()[:8],
    )
    first = Transaction.new_signed_with_payer(
        [instruction], payer.pubkey(), [payer], first_hash
    )
    first_manifest = wallet_smoke.RehearsalEvidenceManifest(
        path=evidence_path, rpc_url="http://rpc.test", state=state
    )
    first_manifest.record_prepared_transaction(
        first,
        (),
        {
            "tx_type": "wallet_signed",
            "recent_blockhash": str(first_hash),
            "last_valid_block_height": 100,
        },
    )

    class Provider:
        async def make_request(self, request: object, response_type: object) -> Any:
            assert "isBlockhashValid" in request.to_json()
            return SimpleNamespace(value=False)

    class Client:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self._provider = Provider()

        async def __aenter__(self) -> "Client":
            return self

        async def __aexit__(self, *args: Any) -> None:
            return None

        async def get_signature_statuses(self, *args: Any, **kwargs: Any) -> Any:
            return SimpleNamespace(value=[None])

        async def get_block_height(self, *args: Any, **kwargs: Any) -> Any:
            return SimpleNamespace(value=101)

    evidence_module = sys.modules[first_manifest.__class__.__module__]
    monkeypatch.setattr(evidence_module, "AsyncClient", Client)
    resumed = wallet_smoke.RehearsalEvidenceManifest(
        path=evidence_path,
        rpc_url="http://rpc.test",
        state=json.loads(evidence_path.read_text(encoding="utf-8")),
    )
    await resumed.reconcile_prepared_transactions()
    expired = json.loads(evidence_path.read_text(encoding="utf-8"))[
        "transactions"
    ][0]
    assert expired["status"] == "expired"
    assert expired["terminal_metadata"]["finalized_block_height"] == 101

    second_hash = Hash.new_unique()
    second = Transaction.new_signed_with_payer(
        [instruction], payer.pubkey(), [payer], second_hash
    )
    resumed.record_prepared_transaction(
        second,
        (),
        {
            "tx_type": "wallet_signed",
            "recent_blockhash": str(second_hash),
            "last_valid_block_height": 200,
        },
    )
    second_signature = str(second.signatures[0])
    resumed.record_finalized_transaction(second_signature, 102, "finalized", {})
    saved = json.loads(evidence_path.read_text(encoding="utf-8"))["transactions"]
    assert [item["status"] for item in saved] == ["expired", "finalized"]
    assert [item["signature"] for item in resumed._unclaimed_finalized_transactions()] == [
        second_signature
    ]
def test_rehearsal_evidence_refuses_changed_prepared_instruction_evidence(
    tmp_path: Path,
) -> None:
    program_id = Keypair().pubkey()
    payer = Keypair()
    evidence_path = tmp_path / "changed-prepared.json"
    manifest = wallet_smoke.RehearsalEvidenceManifest(
        path=evidence_path,
        rpc_url="http://rpc.test",
        state=_evidence_state(
            protected=Keypair().pubkey(),
            program_id=program_id,
            cal_mint=Keypair().pubkey(),
            dung_mint=Keypair().pubkey(),
            user=Keypair().pubkey(),
            climb=Keypair().pubkey(),
            vault_id=0,
            expected_vault=Keypair().pubkey(),
            transport_path=tmp_path / "transport.json",
        ),
    )
    transaction = Transaction.new_signed_with_payer(
        [
            Instruction(
                program_id=program_id,
                accounts=[],
                data=hashlib.sha256(b"global:create_vault_with_usdc").digest()[:8],
            )
        ],
        payer.pubkey(),
        [payer],
        Hash.default(),
    )
    manifest.record_prepared_transaction(transaction, (), {"tx_type": "wallet_signed"})
    persisted = json.loads(evidence_path.read_text(encoding="utf-8"))
    persisted["transactions"][0]["instruction_order"][0]["data_sha256"] = "00" * 32
    evidence_path.write_text(json.dumps(persisted), encoding="utf-8")

    with pytest.raises(RuntimeError, match="prepared.*evidence changed"):
        manifest.record_finalized_transaction(
            str(transaction.signatures[0]), 77, "finalized", {}
        )


def _finalized_recovery_transaction(
    *,
    program_id: Pubkey,
    payer: Keypair,
    instruction_names: tuple[str, ...],
    metadata: dict[str, Any] | None = None,
    account_set: tuple[str, ...] = (),
) -> dict[str, Any]:
    instructions = [
        Instruction(
            program_id=program_id,
            accounts=[],
            data=hashlib.sha256(f"global:{name}".encode()).digest()[:8],
        )
        for name in instruction_names
    ]
    tx = Transaction.new_signed_with_payer(
        instructions, payer.pubkey(), [payer], Hash.new_unique()
    )
    signature = str(tx.signatures[0])
    entry = {
        "signature": signature,
        "stage": "+".join(instruction_names),
        "status": "finalized",
        "slot": 77,
        "metadata": metadata or {"tx_type": "wallet_signed"},
        "account_set": list(account_set),
        "instruction_order": [
            {
                "instruction_name": name,
                "index": index,
                "program_id": str(program_id),
                "account_indices": [],
                "data_len": 8,
                "data_hex": bytes(ix.data).hex(),
                "data_sha256": hashlib.sha256(bytes(ix.data)).hexdigest(),
                "discriminator_hex": bytes(ix.data).hex(),
            }
            for index, (name, ix) in enumerate(zip(instruction_names, instructions))
        ],
    }
    entry["prepared_fingerprint"] = (
        wallet_smoke.RehearsalEvidenceManifest._prepared_fingerprint(entry)
    )
    return entry


@pytest.mark.asyncio
async def test_generic_loop_recovery_captures_each_exact_crash_boundary_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    program_id = Keypair().pubkey()
    payer = Keypair()
    state = _evidence_state(
        protected=Keypair().pubkey(),
        program_id=program_id,
        cal_mint=Keypair().pubkey(),
        dung_mint=Keypair().pubkey(),
        user=Keypair().pubkey(),
        climb=Keypair().pubkey(),
        vault_id=0,
        expected_vault=Keypair().pubkey(),
        transport_path=tmp_path / "transport.json",
    )
    topup_receipt = str(Keypair().pubkey())
    state["dynamic_rehearsal_addresses"] = {
        "rehearsal_stake_cal_top_up_cal_receipt": topup_receipt
    }
    manifest = wallet_smoke.RehearsalEvidenceManifest(
        path=tmp_path / "recovery.json", rpc_url="http://rpc.test", state=state
    )
    captured: list[str] = []

    async def capture(stage: str) -> None:
        captured.append(stage)
        suffix = manifest._unreconciled_transaction_suffix()
        manifest._state["reconciliations"].append(
            {
                "stage": stage,
                "transaction_cursor": len(manifest._state["transactions"]),
                "transaction_signatures": [item["signature"] for item in suffix],
                "transaction_fingerprints": [
                    item["prepared_fingerprint"] for item in suffix
                ],
            }
        )

    monkeypatch.setattr(manifest, "capture_reconciliation", capture)
    cases = (
        (("credit_cal",), (topup_receipt,), "stake_cal_top_up"),
        (("stake_cal_in_vault",), (), "stake_cal"),
        (("distribute_epoch_rewards",), (), "distribute_epoch_rewards"),
        (
            ("collect_stake_rewards_for", "unstake_cal_from_vault"),
            (),
            "collect_then_unstake",
        ),
        (("collect_stake_rewards_for",), (), "legacy_withdrawn_harvest"),
    )
    for names, accounts, expected in cases:
        manifest._state["transactions"].append(
            _finalized_recovery_transaction(
                program_id=program_id,
                payer=payer,
                instruction_names=names,
                account_set=accounts,
            )
        )
        assert await manifest.recover_one_loop_stage() == expected
    assert captured == [case[2] for case in cases]


def test_generic_loop_recovery_refuses_two_unreconciled_boundaries(
    tmp_path: Path,
) -> None:
    program_id = Keypair().pubkey()
    payer = Keypair()
    state = _evidence_state(
        protected=Keypair().pubkey(),
        program_id=program_id,
        cal_mint=Keypair().pubkey(),
        dung_mint=Keypair().pubkey(),
        user=Keypair().pubkey(),
        climb=Keypair().pubkey(),
        vault_id=0,
        expected_vault=Keypair().pubkey(),
        transport_path=tmp_path / "transport.json",
    )
    receipt = str(Keypair().pubkey())
    state["dynamic_rehearsal_addresses"] = {
        "rehearsal_stake_cal_top_up_cal_receipt": receipt
    }
    state["transactions"] = [
        _finalized_recovery_transaction(
            program_id=program_id,
            payer=payer,
            instruction_names=("credit_cal",),
            account_set=(receipt,),
        ),
        _finalized_recovery_transaction(
            program_id=program_id,
            payer=payer,
            instruction_names=("stake_cal_in_vault",),
        ),
    ]
    manifest = wallet_smoke.RehearsalEvidenceManifest(
        path=tmp_path / "ambiguous.json", rpc_url="http://rpc.test", state=state
    )
    with pytest.raises(RuntimeError, match="multiple unreconciled.*ambiguous"):
        manifest._recoverable_loop_stage(manifest._unclaimed_finalized_transactions())


@pytest.mark.asyncio
async def test_transport_evidence_allows_exactly_one_absent_stale_supersession(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    program_id = Keypair().pubkey()
    payer = Keypair().pubkey()
    state = _evidence_state(
        protected=Keypair().pubkey(),
        program_id=program_id,
        cal_mint=Keypair().pubkey(),
        dung_mint=Keypair().pubkey(),
        user=Keypair().pubkey(),
        climb=Keypair().pubkey(),
        vault_id=0,
        expected_vault=Keypair().pubkey(),
        transport_path=tmp_path / "transport.json",
        settlement_week=42,
    )
    manifest = wallet_smoke.RehearsalEvidenceManifest(
        path=tmp_path / "transport-evidence.json",
        rpc_url="http://rpc.test",
        state=state,
    )

    async def absent_accounts(
        rpc_url: str, addresses: dict[str, Pubkey]
    ) -> tuple[int, dict[str, dict[str, Any]]]:
        return 1, {
            label: {
                "address": str(address),
                "exists": False,
                "owner": None,
                "decoded": None,
            }
            for label, address in addresses.items()
        }

    monkeypatch.setattr(manifest, "_read_accounts", absent_accounts)

    def plan(generation: int, slot: int, supersedes: dict | None = None) -> dict:
        address = derive_lookup_table_address(payer, slot)[0]
        value = {
            "program_id": str(program_id),
            "vault_id": "0",
            "settlement_week": "42",
            "payer": str(payer),
            "lookup_table_generation_id": f"generation-{generation}",
            "lookup_table_address": str(address),
            "lookup_table_generation": str(generation),
            "lookup_table_authority": str(payer),
            "lookup_table_recent_slot": str(slot),
            "distribution_instruction": {
                "program_id": str(program_id),
                "data_sha256": "11" * 32,
                "accounts": [],
            },
            "required_addresses": [],
            "recipient_token_accounts": [],
            "expected_manifest_sha256": "22" * 32,
        }
        if supersedes is not None:
            value["supersedes"] = supersedes
        value["plan_sha256"] = hashlib.sha256(
            json.dumps(value, sort_keys=True, separators=(",", ":")).encode(
                "ascii"
            )
        ).hexdigest()
        return value

    first = plan(1, 99)
    await manifest.register_settlement_transport_plan(first)
    supersedes = {
        "status": "expired",
        "generation_id": "generation-1",
        "lookup_table_address": first["lookup_table_address"],
        "lookup_table_generation": "1",
        "lookup_table_recent_slot": "99",
        "proof": "finalized create rejection after recent slot",
    }
    second = plan(2, 100, supersedes)
    await manifest.register_settlement_transport_plan(second)
    saved = json.loads(manifest.path.read_text(encoding="utf-8"))
    assert [item["status"] for item in saved["settlement_transport_plan_history"]] == [
        "expired",
        "planned",
    ]
    third_supersedes = {
        **supersedes,
        "generation_id": "generation-2",
        "lookup_table_address": second["lookup_table_address"],
        "lookup_table_generation": "2",
        "lookup_table_recent_slot": "100",
    }
    with pytest.raises(RuntimeError, match="one supersession"):
        await manifest.register_settlement_transport_plan(
            plan(3, 101, third_supersedes)
        )


@pytest.mark.asyncio
async def test_confirmed_vault_zero_create_requires_exact_resume_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    program_id = Keypair().pubkey()
    user = Keypair().pubkey()
    climb = Keypair().pubkey()
    cal_mint = Keypair().pubkey()
    dung_mint = Keypair().pubkey()
    expected_vault, _ = smoke._derive_vault_pda(0, program_id)
    transport_path = tmp_path / "transport.json"
    state = _evidence_state(
        protected=Keypair().pubkey(),
        program_id=program_id,
        cal_mint=cal_mint,
        dung_mint=dung_mint,
        user=user,
        climb=climb,
        vault_id=0,
        expected_vault=expected_vault,
        transport_path=transport_path,
    )
    state["transactions"] = [
        {
            "signature": str(Signature.default()),
            "stage": "create_vault_with_usdc",
            "status": "confirmed",
            "slot": 77,
            "metadata": {"tx_type": "wallet_signed"},
            "account_set": [],
            "instruction_order": [
                {"instruction_name": "create_vault_with_usdc"}
            ],
        }
    ]
    evidence_path = tmp_path / "confirmed-vault-zero.json"
    evidence_path.write_text(json.dumps(state), encoding="utf-8")

    async def refuse_rpc(*args: Any, **kwargs: Any) -> dict[str, Pubkey]:
        raise AssertionError("confirmed create was not stopped before RPC discovery")

    monkeypatch.setattr(
        wallet_smoke.RehearsalEvidenceManifest,
        "_resolve_protected_addresses",
        classmethod(refuse_rpc),
    )
    with pytest.raises(RuntimeError, match="resume with --existing-vault-id 0"):
        await wallet_smoke.RehearsalEvidenceManifest.open(
            path=evidence_path,
            rpc_url="http://rpc.test",
            program_id=program_id,
            cal_mint=cal_mint,
            dung_mint=dung_mint,
            user=user,
            climb_pda=climb,
            existing_vault_id=None,
            settlement_week=None,
            usdc_mint=Pubkey.from_string(state["identity"]["usdc_mint"]),
            usdc_treasury=Pubkey.from_string(state["identity"]["usdc_treasury"]),
            transport_state_path=transport_path,
        )


def test_rehearsal_evidence_refuses_mismatched_protected_baseline() -> None:
    expected = {
        "protected": {
            "address": str(Keypair().pubkey()),
            "exists": True,
            "owner": str(Keypair().pubkey()),
            "data_len": 82,
            "data_sha256": "ab" * 32,
            "decoded": {"supply_base_units": "10"},
        }
    }
    actual = json.loads(json.dumps(expected))
    actual["protected"]["decoded"]["supply_base_units"] = "11"
    with pytest.raises(RuntimeError, match="protected account baseline changed"):
        wallet_smoke.RehearsalEvidenceManifest._assert_protected_baseline(
            expected,
            actual,
        )


def test_rehearsal_evidence_baseline_includes_configured_usdc_accounts() -> None:
    program_id = Keypair().pubkey()
    cal_mint = Keypair().pubkey()
    dung_mint = Keypair().pubkey()
    usdc_mint = Keypair().pubkey()
    usdc_treasury = Keypair().pubkey()
    addresses = wallet_smoke.RehearsalEvidenceManifest._rehearsal_addresses(
        program_id=program_id,
        cal_mint=cal_mint,
        dung_mint=dung_mint,
        usdc_mint=usdc_mint,
        usdc_treasury=usdc_treasury,
        user=Keypair().pubkey(),
        climb_pda=Keypair().pubkey(),
        vault_id=0,
        expected_vault=Keypair().pubkey(),
    )

    assert addresses["rehearsal_usdc_mint"] == usdc_mint
    assert addresses["rehearsal_usdc_treasury"] == usdc_treasury


def test_rehearsal_evidence_refuses_a_concurrent_writer(tmp_path: Path) -> None:
    evidence_path = tmp_path / "evidence.json"
    manifest = wallet_smoke.RehearsalEvidenceManifest(
        path=evidence_path,
        rpc_url="http://rpc.test",
        state=_evidence_state(
            protected=Keypair().pubkey(),
            program_id=Keypair().pubkey(),
            cal_mint=Keypair().pubkey(),
            dung_mint=Keypair().pubkey(),
            user=Keypair().pubkey(),
            climb=Keypair().pubkey(),
            vault_id=0,
            expected_vault=Keypair().pubkey(),
            transport_path=tmp_path / "transport.json",
        ),
    )

    duplicate = wallet_smoke.RehearsalEvidenceManifest(
        path=evidence_path,
        rpc_url="http://rpc.test",
        state=json.loads(json.dumps(manifest._state)),
    )
    manifest.claim_run_lock()
    try:
        with pytest.raises(RuntimeError, match="another rehearsal process"):
            duplicate.claim_run_lock()
    finally:
        manifest.release_run_lock()


@pytest.mark.asyncio
async def test_rehearsal_evidence_resume_requires_frozen_vault_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    program_id = Keypair().pubkey()
    cal_mint = Keypair().pubkey()
    dung_mint = Keypair().pubkey()
    user = Keypair().pubkey()
    climb = Keypair().pubkey()
    protected = Keypair().pubkey()
    expected_vault, _ = smoke._derive_vault_pda(0, program_id)
    transport_path = tmp_path / "transport.json"
    evidence_path = tmp_path / "evidence.json"
    state = _evidence_state(
        protected=protected,
        program_id=program_id,
        cal_mint=cal_mint,
        dung_mint=dung_mint,
        user=user,
        climb=climb,
        vault_id=0,
        expected_vault=expected_vault,
        transport_path=transport_path,
    )
    evidence_path.write_text(json.dumps(state), encoding="utf-8")

    with pytest.raises(RuntimeError, match="resume Vault ID does not match"):
        await wallet_smoke.RehearsalEvidenceManifest.open(
            path=evidence_path,
            rpc_url="http://rpc.test",
            program_id=program_id,
            cal_mint=cal_mint,
            dung_mint=dung_mint,
            user=user,
                climb_pda=None,
                existing_vault_id=1,
                settlement_week=42,
                usdc_mint=Pubkey.from_string(state["identity"]["usdc_mint"]),
                usdc_treasury=Pubkey.from_string(
                    state["identity"]["usdc_treasury"]
                ),
                transport_state_path=transport_path,
            )

    with pytest.raises(RuntimeError, match="resume Settlement Week does not match"):
        await wallet_smoke.RehearsalEvidenceManifest.open(
            path=evidence_path,
            rpc_url="http://rpc.test",
            program_id=program_id,
            cal_mint=cal_mint,
            dung_mint=dung_mint,
            user=user,
            climb_pda=None,
            existing_vault_id=0,
            settlement_week=43,
            usdc_mint=Pubkey.from_string(state["identity"]["usdc_mint"]),
            usdc_treasury=Pubkey.from_string(state["identity"]["usdc_treasury"]),
            transport_state_path=transport_path,
        )

    protected_snapshot = state["baseline"]["protected"]
    rehearsal_snapshot = {
        "rehearsal_climb": {
            "address": str(climb),
            "exists": True,
            "owner": str(program_id),
            "lamports": 1,
            "executable": False,
            "data_len": 1,
            "data_sha256": "cd" * 32,
            "decoded": None,
        },
        "rehearsal_expected_vault": {
            "address": str(expected_vault),
            "exists": True,
            "owner": str(program_id),
            "lamports": 1,
            "executable": False,
            "data_len": 1,
            "data_sha256": "ef" * 32,
            "decoded": None,
        },
    }

    async def protected_addresses(cls: object, rpc_url: str) -> dict[str, Pubkey]:
        return {"protected": protected}

    async def rehearsal_addresses(cls: object, **kwargs: Any) -> dict[str, Pubkey]:
        return {
                "rehearsal_climb": climb,
                "rehearsal_expected_vault": expected_vault,
                "rehearsal_usdc_mint": Pubkey.from_string(
                    state["identity"]["usdc_mint"]
                ),
                "rehearsal_usdc_treasury": Pubkey.from_string(
                    state["identity"]["usdc_treasury"]
                ),
            }

    monkeypatch.setattr(
        wallet_smoke.RehearsalEvidenceManifest,
        "_resolve_protected_addresses",
        classmethod(protected_addresses),
    )
    monkeypatch.setattr(
        wallet_smoke.RehearsalEvidenceManifest,
        "_resolve_rehearsal_addresses",
        classmethod(rehearsal_addresses),
    )
    monkeypatch.setattr(
        wallet_smoke.RehearsalEvidenceManifest,
        "_require_baseline_accounts",
        staticmethod(lambda *args, **kwargs: None),
    )
    monkeypatch.setattr(
        wallet_smoke.RehearsalEvidenceManifest,
        "_validate_rehearsal_authorities",
        staticmethod(lambda *args, **kwargs: None),
    )

    async def read_accounts(
        cls: object,
        rpc_url: str,
        addresses: dict[str, Pubkey],
    ) -> tuple[int, dict[str, dict[str, Any]]]:
        if "protected" in addresses:
            return 2, protected_snapshot
        return 3, rehearsal_snapshot

    monkeypatch.setattr(
        wallet_smoke.RehearsalEvidenceManifest,
        "_read_accounts",
        classmethod(read_accounts),
    )
    resumed = await wallet_smoke.RehearsalEvidenceManifest.open(
        path=evidence_path,
        rpc_url="http://rpc.test",
        program_id=program_id,
        cal_mint=cal_mint,
        dung_mint=dung_mint,
        user=user,
        climb_pda=None,
        existing_vault_id=0,
        settlement_week=42,
        usdc_mint=Pubkey.from_string(state["identity"]["usdc_mint"]),
        usdc_treasury=Pubkey.from_string(state["identity"]["usdc_treasury"]),
        transport_state_path=transport_path,
    )
    assert resumed.vault_id == 0


@pytest.mark.asyncio
async def test_rehearsal_resume_refuses_unbound_new_evidence_path(
    tmp_path: Path,
) -> None:
    with pytest.raises(RuntimeError, match="exact existing rehearsal evidence"):
        await wallet_smoke.RehearsalEvidenceManifest.open(
            path=tmp_path / "new-resume-evidence.json",
            rpc_url="http://rpc.test",
            program_id=Keypair().pubkey(),
            cal_mint=Keypair().pubkey(),
            dung_mint=Keypair().pubkey(),
            user=Keypair().pubkey(),
            climb_pda=None,
            existing_vault_id=0,
            settlement_week=42,
            usdc_mint=Keypair().pubkey(),
            usdc_treasury=Keypair().pubkey(),
            transport_state_path=tmp_path / "transport.json",
        )


@pytest.mark.asyncio
async def test_wallet_fresh_preflight_validates_config_climb_and_funded_atas(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    program_id = Keypair().pubkey()
    cal_mint = Keypair().pubkey()
    dung_mint = Keypair().pubkey()
    usdc_mint = Keypair().pubkey()
    user = Keypair().pubkey()
    fee_payer = Keypair()
    backend_authority = Keypair()
    climb = Keypair().pubkey()
    treasury = Keypair().pubkey()
    treasury_owner = fee_payer.pubkey()

    def token_account(mint: Pubkey, owner: Pubkey, amount: int) -> Any:
        data = bytearray(wallet_smoke.SPL_TOKEN_ACCOUNT_LEN)
        data[0:32] = bytes(mint)
        data[32:64] = bytes(owner)
        struct.pack_into(
            "<Q",
            data,
            wallet_smoke.SPL_TOKEN_ACCOUNT_AMOUNT_OFFSET,
            amount,
        )
        data[wallet_smoke.SPL_TOKEN_ACCOUNT_STATE_OFFSET] = 1
        return SimpleNamespace(owner=wallet_smoke.TOKEN_PROGRAM_ID, data=bytes(data))

    def mint_account(supply: int) -> Any:
        data = bytearray(82)
        struct.pack_into("<Q", data, 36, supply)
        data[44] = 6
        data[45] = 1
        return SimpleNamespace(owner=wallet_smoke.TOKEN_PROGRAM_ID, data=bytes(data))

    accounts = [
        mint_account(2_000_000),
        token_account(cal_mint, user, 0),
        token_account(usdc_mint, user, 2_000_000),
        token_account(usdc_mint, treasury_owner, 0),
        SimpleNamespace(owner=program_id, data=b"climb"),
    ]

    class Client:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def __aenter__(self) -> "Client":
            return self

        async def __aexit__(self, *args: Any) -> None:
            return None

        async def get_multiple_accounts(self, addresses: list[Pubkey]) -> Any:
            assert addresses[-1] == climb
            return SimpleNamespace(value=list(accounts))

    async def program_config(config: object) -> dict[str, Any]:
        return {
            "initialized": True,
            "admin_authority": str(fee_payer.pubkey()),
            "backend_authority": str(backend_authority.pubkey()),
            "cal_mint": str(cal_mint),
            "dung_mint": str(dung_mint),
            "usdc_mint": str(usdc_mint),
            "usdc_treasury_token_account": str(treasury),
            "vault_creation_usdc": 2_000_000,
            "vault_creation_cal": 1_000,
            "harvest_fee_bps": 500,
        }

    coder = SimpleNamespace(
        parse=lambda data: SimpleNamespace(
            name="Climb",
            data=SimpleNamespace(
                vault=Pubkey.default(),
                successor_climb=Pubkey.default(),
                record_continuity_policy="new_record_board",
            ),
        )
    )
    database = object()
    monkeypatch.setattr(
        wallet_smoke,
        "preflight_smoke_settlement_transport_prerequisites",
        lambda **kwargs: _async_value(database),
    )
    monkeypatch.setattr(wallet_smoke, "get_program_config_account", program_config)
    monkeypatch.setattr(wallet_smoke, "AsyncClient", Client)
    monkeypatch.setattr(wallet_smoke, "_get_boulder_accounts_coder", lambda: coder)

    config = wallet_smoke.DirectConfig(
        rpc_url="http://rpc.test",
        program_id=program_id,
        payer=fee_payer,
        backend_authority=backend_authority,
        cal_mint_address=cal_mint,
        dung_mint_address=dung_mint,
    )
    result = await wallet_smoke.preflight_wallet_rehearsal(
        config=config,
        user=user,
        climb_pda=climb,
        user_cal=1_000 * wallet_smoke.LAMPORT_DECIMALS,
        transport_state_path=tmp_path / "transport.json",
    )
    assert result.transport_database is database
    assert result.usdc_mint == usdc_mint
    assert result.vault_creation_usdc == 2_000_000

    protected_usdc = Pubkey.from_string(
        "DpLPBaRuLnBsR3P3meU1tmiNUxreXwskXBebTYKvNGne"
    )

    async def protected_program_config(config: object) -> dict[str, Any]:
        value = await program_config(config)
        value["usdc_mint"] = str(protected_usdc)
        return value

    monkeypatch.setattr(
        wallet_smoke,
        "get_program_config_account",
        protected_program_config,
    )
    with pytest.raises(RuntimeError, match="protected test-USDC mint"):
        await wallet_smoke.preflight_wallet_rehearsal(
            config=config,
            user=user,
            climb_pda=climb,
            user_cal=1_000 * wallet_smoke.LAMPORT_DECIMALS,
            transport_state_path=tmp_path / "transport.json",
        )
    monkeypatch.setattr(wallet_smoke, "get_program_config_account", program_config)

    with pytest.raises(RuntimeError, match="Vault creation cost.*base units"):
        await wallet_smoke.preflight_wallet_rehearsal(
            config=config,
            user=user,
            climb_pda=climb,
            user_cal=999 * wallet_smoke.LAMPORT_DECIMALS,
            transport_state_path=tmp_path / "transport.json",
        )

    accounts[2] = token_account(usdc_mint, user, 1_999_999)
    with pytest.raises(RuntimeError, match="below configured Vault creation cost"):
        await wallet_smoke.preflight_wallet_rehearsal(
            config=config,
            user=user,
            climb_pda=climb,
            user_cal=1_000 * wallet_smoke.LAMPORT_DECIMALS,
            transport_state_path=tmp_path / "transport.json",
        )


def test_smokes_deposit_before_waiting_and_recording_eligible_tribute() -> None:
    direct_main = _source(SMOKE_PATH).split("async def main()", 1)[1]
    wallet_main = _source(
        BACKEND_DIR / "scripts" / "smoke_wallet_signed_economics.py"
    ).split("async def main()", 1)[1]
    direct_flow = direct_main.index("ensure_receipt_backed_smoke_flow(")
    wallet_flow = wallet_main.index("ensure_receipt_backed_smoke_flow(")

    assert direct_main.index("send_stake_cal_in_vault(") < direct_flow
    assert direct_main.index("credit_user_cal(") < direct_flow
    assert wallet_main.index("builder.build_stake_tx(") < wallet_flow
    assert wallet_main.index("ensure_user_cal_credit(") < wallet_flow
    assert direct_main.index("send_unstake_cal_from_vault(") < direct_main.index(
        "send_harvest_rewards("
    )
    composed_start = wallet_main.index("builder.build_unstake_tx(")
    composed_end = wallet_main.index("prepared_unstake.transaction", composed_start)
    assert "collect_rewards=True" in wallet_main[composed_start:composed_end]
    assert composed_start < wallet_main.index("builder.build_harvest_tx(")


@pytest.mark.asyncio
async def test_wallet_fresh_path_funds_then_builds_registered_climb_with_cal_usdc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FreshPrefixComplete(RuntimeError):
        pass

    backend_authority = Keypair()
    fee_payer = Keypair()
    user = Keypair()
    program_id = Keypair().pubkey()
    cal_mint = Keypair().pubkey()
    dung_mint = Keypair().pubkey()
    climb_pda = Keypair().pubkey()
    keypairs = iter((backend_authority, fee_payer, user))
    events: list[tuple[str, Any]] = []

    args = SimpleNamespace(
        backend_authority_keypair="backend.json",
        fee_payer_keypair="payer.json",
        user_keypair="user.json",
        user_cal=250_000,
        stake_cal=100_000,
        vault_alloc_cal=1_000_000,
        sleep_seconds=0,
        existing_vault_id=None,
        settlement_week=None,
        rpc_url="https://api.devnet.solana.com",
        program_id=str(program_id),
        cal_mint=str(cal_mint),
        dung_mint=str(dung_mint),
        rehearsal_lane=True,
        rehearsal_transport_state="/tmp/rehearsal-transport.json",
        rehearsal_evidence="/tmp/rehearsal-evidence.json",
        rehearsal_setup_evidence="/tmp/rehearsal-setup.json",
        climb_pda=str(climb_pda),
        climb_name="Barren Hill Road",
    )

    class Clock:
        @staticmethod
        def week_at(now: int) -> int:
            assert now == 1_713_456_789
            return 41

        @staticmethod
        def week_start(settlement_week: int) -> int:
            return 30 - 86_400

        @staticmethod
        def week_end(settlement_week: int) -> int:
            assert settlement_week == 42
            return 1_713_456_000

    class Builder:
        async def build_create_vault_with_usdc_tx(self, **kwargs: Any) -> Any:
            events.append(("build", kwargs))
            return SimpleNamespace(
                transaction="unsigned-create",
                last_valid_block_height=999,
                vault_id=0,
            )

        async def submit_signed_transaction(
            self,
            transaction_b64: str,
            *,
            last_valid_block_height: int,
        ) -> str:
            events.append(
                (
                    "submit",
                    (transaction_b64, last_valid_block_height),
                )
            )
            return "create-signature"

    async def get_clock(config: object) -> Clock:
        return Clock()

    async def get_settlement_accounts(config: object) -> tuple[Pubkey, Pubkey]:
        return Keypair().pubkey(), Keypair().pubkey()

    async def preflight(**kwargs: Any) -> object:
        events.append(("preflight", kwargs))
        return wallet_smoke.WalletRehearsalPreflight(
            transport_database=object(),
            usdc_mint=Keypair().pubkey(),
            usdc_treasury=Keypair().pubkey(),
            vault_creation_usdc=2_000_000,
        )

    async def fund_cal(**kwargs: Any) -> str:
        events.append(("fund", kwargs))
        return "cal-credit-signature"

    async def mutable_balance_preflight(**kwargs: Any) -> None:
        events.append(("mutable_preflight", kwargs))

    async def override_week(**kwargs: Any) -> str:
        events.append(("override", kwargs))
        return "week-override-signature"

    async def stop_after_prefix(config: object, vault_id: int) -> dict[str, Any]:
        assert vault_id == 0
        raise FreshPrefixComplete

    async def reject_legacy(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("fresh V4-B path used legacy DUNG/admin vault setup")

    def sign_create(transaction_b64: str, signer: Keypair) -> str:
        events.append(("sign", (transaction_b64, signer.pubkey())))
        return "signed-create"

    monkeypatch.setattr(wallet_smoke, "parse_args", lambda: args)
    monkeypatch.setattr(wallet_smoke, "load_keypair", lambda path: next(keypairs))
    monkeypatch.setattr(wallet_smoke, "TxBuilder", lambda **kwargs: Builder())
    evidence = _FakeEvidence(0, events)
    monkeypatch.setattr(
        wallet_smoke.RehearsalEvidenceManifest,
        "open",
        lambda **kwargs: _async_value(evidence),
    )
    monkeypatch.setattr(
        wallet_smoke,
        "activate_transaction_evidence_guard",
        lambda evidence: None,
    )
    monkeypatch.setattr(wallet_smoke, "preflight_wallet_rehearsal", preflight)
    monkeypatch.setattr(wallet_smoke, "get_program_settlement_clock", get_clock)
    monkeypatch.setattr(
        wallet_smoke,
        "read_canonical_settlement_accounts",
        get_settlement_accounts,
    )
    monkeypatch.setattr(wallet_smoke, "ensure_user_cal_credit", fund_cal)
    monkeypatch.setattr(
        wallet_smoke,
        "preflight_fresh_wallet_balances",
        mutable_balance_preflight,
    )
    monkeypatch.setattr(
        wallet_smoke,
        "send_admin_override_open_settlement_week",
        override_week,
        raising=False,
    )
    monkeypatch.setattr(wallet_smoke, "read_vault_state", stop_after_prefix)
    monkeypatch.setattr(wallet_smoke, "sign_prepared_transaction", sign_create)
    monkeypatch.setattr(
        wallet_smoke,
        "ensure_token_ata",
        reject_legacy,
        raising=False,
    )
    monkeypatch.setattr(
        wallet_smoke,
        "seed_and_activate_vault",
        reject_legacy,
        raising=False,
    )
    monkeypatch.setattr(wallet_smoke.time, "time", lambda: 1_713_456_789)

    with pytest.raises(FreshPrefixComplete):
        await wallet_smoke.main()

    expected_activity_id = (
        "smoke-wallet-economics:v4b-vault-funding:"
        f"{program_id}:{user.pubkey()}:{climb_pda}:{args.user_cal}"
    )
    assert [event[0] for event in events] == [
        "preflight",
        "freeze_week",
        "mutable_preflight",
        "fund",
        "build",
        "sign",
        "submit",
    ]
    assert events[0][1]["user"] == user.pubkey()
    assert events[0][1]["climb_pda"] == climb_pda
    assert events[1][1] == 42
    assert events[3][1]["activity_id"] == expected_activity_id
    assert events[3][1]["completed_at"] == 1_713_456_729
    assert events[3][1]["total_cal_amount"] == args.user_cal
    assert events[4][1] == {
        "user_wallet": str(user.pubkey()),
        "climb_pda": str(climb_pda),
        "display_name": "Barren Hill Road",
        "vault_id": 0,
    }
    assert events[5][1] == ("unsigned-create", user.pubkey())
    assert events[6][1] == ("signed-create", 999)
    assert not any(name == "override" for name, _ in events)


@pytest.mark.asyncio
async def test_wallet_main_routes_resume_through_shared_canonical_flow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend_authority = Keypair()
    fee_payer = Keypair()
    user = Keypair()
    program_id = Keypair().pubkey()
    cal_mint = Keypair().pubkey()
    dung_mint = Keypair().pubkey()
    keypairs = iter((backend_authority, fee_payer, user))
    calls: list[dict[str, Any]] = []

    args = SimpleNamespace(
        backend_authority_keypair="backend.json",
        fee_payer_keypair="payer.json",
        user_keypair="user.json",
        user_cal=250,
        stake_cal=100,
        vault_alloc_cal=2_500,
        sleep_seconds=0,
        existing_vault_id=42,
        settlement_week=42,
        rpc_url="https://api.devnet.solana.com",
        program_id=str(program_id),
        cal_mint=str(cal_mint),
        dung_mint=str(dung_mint),
        rehearsal_lane=True,
        rehearsal_transport_state="/tmp/rehearsal-transport.json",
        rehearsal_evidence="/tmp/rehearsal-evidence.json",
        rehearsal_setup_evidence="/tmp/rehearsal-setup.json",
        climb_pda=None,
        climb_name="unused on resume",
    )

    class Clock:
        @staticmethod
        def week_finalization_time(settlement_week: int) -> int:
            return 1

        @staticmethod
        def week_start(settlement_week: int) -> int:
            return 30 - 86_400

        @staticmethod
        def week_end(settlement_week: int) -> int:
            return 100

    vault_state = _vault_state(
        open_settlement_week=43,
        last_distribution_epoch=42,
        staker_count=1,
    )
    vault_state["signature_hash_hex"] = hashlib.sha256(b"vault").hexdigest()
    complete_stake = {
        "cal_staked": 0,
        "lp_tokens": 0,
        "rewards_earned": 0,
        "effective_lp_tokens": 100,
        "pending_lp_tokens": 0,
    }

    async def get_clock(config: object) -> Clock:
        return Clock()

    async def get_settlement_accounts(config: object) -> tuple[Pubkey, Pubkey]:
        return Keypair().pubkey(), Keypair().pubkey()

    async def read_vault(config: object, vault_id: int) -> dict[str, Any]:
        assert vault_id == 42
        return vault_state

    async def read_stake(
        config: object, vault_id: int, rider_wallet: str
    ) -> dict[str, int]:
        assert vault_id == 42
        assert rider_wallet == str(user.pubkey())
        return complete_stake

    async def ensure_flow(**kwargs: Any) -> Any:
        calls.append(kwargs)
        return smoke.SmokeSettlementPlan(
            stage="distributed",
            completed_at=99,
            expected_pending_rewards=3,
            expected_cal_remainder=500,
        )

    async def balance(rpc_url: str, token_account: Pubkey) -> int:
        return 0

    monkeypatch.setattr(wallet_smoke, "parse_args", lambda: args)
    monkeypatch.setattr(wallet_smoke, "load_keypair", lambda path: next(keypairs))
    monkeypatch.setattr(wallet_smoke, "TxBuilder", lambda **kwargs: SimpleNamespace())
    monkeypatch.setattr(
        wallet_smoke.RehearsalEvidenceManifest,
        "open",
        lambda **kwargs: _async_value(_FakeEvidence(42)),
    )
    monkeypatch.setattr(
        wallet_smoke,
        "activate_transaction_evidence_guard",
        lambda evidence: None,
    )
    monkeypatch.setattr(
        wallet_smoke,
        "preflight_wallet_rehearsal",
        lambda **kwargs: _async_value(
            wallet_smoke.WalletRehearsalPreflight(
                transport_database=object(),
                usdc_mint=Keypair().pubkey(),
                usdc_treasury=Keypair().pubkey(),
                vault_creation_usdc=2_000_000,
            )
        ),
    )
    monkeypatch.setattr(wallet_smoke, "get_program_settlement_clock", get_clock)
    monkeypatch.setattr(
        wallet_smoke,
        "read_canonical_settlement_accounts",
        get_settlement_accounts,
    )
    monkeypatch.setattr(wallet_smoke, "read_vault_state", read_vault)
    monkeypatch.setattr(wallet_smoke, "get_vault_stake_account", read_stake)
    monkeypatch.setattr(wallet_smoke, "ensure_receipt_backed_smoke_flow", ensure_flow)
    monkeypatch.setattr(wallet_smoke, "token_balance", balance)

    await wallet_smoke.main()

    assert len(calls) == 1
    assert calls[0]["vault_id"] == 42
    assert calls[0]["settlement_week"] == 42
    assert calls[0]["staker"] == user.pubkey()
    assert calls[0]["cal_amount"] == 2_500


@pytest.mark.asyncio
async def test_wallet_distributed_stake_collects_before_unstake_atomically(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend_authority = Keypair()
    fee_payer = Keypair()
    user = Keypair()
    program_id = Keypair().pubkey()
    cal_mint = Keypair().pubkey()
    dung_mint = Keypair().pubkey()
    keypairs = iter((backend_authority, fee_payer, user))
    build_calls: list[dict[str, Any]] = []
    submissions: list[str] = []

    args = SimpleNamespace(
        backend_authority_keypair="backend.json",
        fee_payer_keypair="payer.json",
        user_keypair="user.json",
        user_cal=250,
        stake_cal=100,
        vault_alloc_cal=2_500,
        sleep_seconds=0,
        existing_vault_id=0,
        settlement_week=42,
        rpc_url="https://api.devnet.solana.com",
        program_id=str(program_id),
        cal_mint=str(cal_mint),
        dung_mint=str(dung_mint),
        rehearsal_lane=True,
        rehearsal_transport_state="/tmp/rehearsal-transport.json",
        rehearsal_evidence="/tmp/rehearsal-evidence.json",
        rehearsal_setup_evidence="/tmp/rehearsal-setup.json",
        climb_pda=None,
        climb_name="unused on resume",
    )

    class Clock:
        @staticmethod
        def week_start(settlement_week: int) -> int:
            return 30 - 86_400

        @staticmethod
        def week_end(settlement_week: int) -> int:
            return 100

    class Builder:
        async def build_unstake_tx(self, **kwargs: Any) -> Any:
            build_calls.append(kwargs)
            return SimpleNamespace(
                transaction="unsigned-composed-withdraw",
                last_valid_block_height=99,
            )

        async def submit_signed_transaction(
            self,
            transaction_b64: str,
            *,
            last_valid_block_height: int,
        ) -> str:
            submissions.append(transaction_b64)
            assert last_valid_block_height == 99
            return "composed-signature"

        async def build_harvest_tx(self, **kwargs: Any) -> Any:
            raise AssertionError("freshly staked cleanup must not split harvest")

    vault_state = _vault_state(
        open_settlement_week=43,
        last_distribution_epoch=42,
        total_cal_staked=100,
        staker_count=1,
    )
    vault_state["signature_hash_hex"] = hashlib.sha256(b"vault-zero").hexdigest()
    complete_vault_state = dict(vault_state)
    complete_vault_state["total_cal_staked"] = 0
    vault_reads = 0
    stake_states = iter(
        (
            {"cal_staked": 100, "lp_tokens": 100, "rewards_earned": 7},
            {"cal_staked": 100, "lp_tokens": 100, "rewards_earned": 7},
            {
                "cal_staked": 0,
                "lp_tokens": 0,
                "rewards_earned": 0,
                "effective_lp_tokens": 100,
                "pending_lp_tokens": 0,
            },
        )
    )

    async def read_stake(*args: Any, **kwargs: Any) -> dict[str, int]:
        return next(stake_states)

    async def ensure_flow(**kwargs: Any) -> Any:
        return smoke.SmokeSettlementPlan(
            stage="distributed",
            completed_at=99,
            expected_pending_rewards=3,
            expected_cal_remainder=500,
        )

    async def read_vault(*args: Any, **kwargs: Any) -> dict[str, Any]:
        nonlocal vault_reads
        vault_reads += 1
        return complete_vault_state if submissions else vault_state

    async def balance(*args: Any, **kwargs: Any) -> int:
        return 0

    monkeypatch.setattr(wallet_smoke, "parse_args", lambda: args)
    monkeypatch.setattr(wallet_smoke, "load_keypair", lambda path: next(keypairs))
    monkeypatch.setattr(wallet_smoke, "TxBuilder", lambda **kwargs: Builder())
    monkeypatch.setattr(
        wallet_smoke.RehearsalEvidenceManifest,
        "open",
        lambda **kwargs: _async_value(_FakeEvidence(0)),
    )
    monkeypatch.setattr(
        wallet_smoke,
        "activate_transaction_evidence_guard",
        lambda evidence: None,
    )
    monkeypatch.setattr(
        wallet_smoke,
        "preflight_wallet_rehearsal",
        lambda **kwargs: _async_value(
            wallet_smoke.WalletRehearsalPreflight(
                transport_database=object(),
                usdc_mint=Keypair().pubkey(),
                usdc_treasury=Keypair().pubkey(),
                vault_creation_usdc=2_000_000,
            )
        ),
    )
    monkeypatch.setattr(
        wallet_smoke,
        "get_program_settlement_clock",
        lambda config: _async_value(Clock()),
    )
    monkeypatch.setattr(
        wallet_smoke,
        "read_canonical_settlement_accounts",
        lambda config: _async_value((Keypair().pubkey(), Keypair().pubkey())),
    )
    monkeypatch.setattr(wallet_smoke, "read_vault_state", read_vault)
    monkeypatch.setattr(wallet_smoke, "get_vault_stake_account", read_stake)
    monkeypatch.setattr(wallet_smoke, "ensure_receipt_backed_smoke_flow", ensure_flow)
    monkeypatch.setattr(
        wallet_smoke,
        "inspect_smoke_settlement_stage",
        lambda *args, **kwargs: smoke.SmokeSettlementPlan(
            stage="distributed",
            completed_at=99,
            expected_pending_rewards=3,
            expected_cal_remainder=500,
        ),
    )
    monkeypatch.setattr(wallet_smoke, "token_balance", balance)
    monkeypatch.setattr(
        wallet_smoke,
        "sign_prepared_transaction",
        lambda transaction, signer: "signed-composed-withdraw",
    )

    await wallet_smoke.main()

    assert build_calls == [
        {
            "user_wallet": str(user.pubkey()),
            "vault_id": 0,
            "lp_amount": 100,
            "collect_rewards": True,
        }
    ]
    assert submissions == ["signed-composed-withdraw"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("creation_week", "settlement_week"),
    ((41, 42), (42, 42), (1, 1)),
)
async def test_resume_after_finalized_vault_zero_create_recovers_frozen_week(
    monkeypatch: pytest.MonkeyPatch,
    creation_week: int,
    settlement_week: int,
) -> None:
    program_id = Keypair().pubkey()
    rider = Keypair().pubkey()
    climb = Keypair().pubkey()
    expected_vault, _ = smoke._derive_vault_pda(0, program_id)
    events: list[tuple[str, Any]] = []

    vault = _vault_state(
        open_settlement_week=creation_week,
        last_distribution_epoch=0,
    )
    vault.update(
        {
            "id": 0,
            "minter": str(rider),
            "climb": str(climb),
            "total_cal_burned": 0,
            "total_dung_emitted": 0,
            "total_completions": 0,
            "total_staked": 0,
            "kom_holder": None,
            "kom_time_s": 0,
            "kom_set_epoch": 0,
        }
    )

    class Evidence(_FakeEvidence):
        def __init__(self) -> None:
            super().__init__(0)
            self.climb_pda = climb
            self.expected_vault = expected_vault

        def has_reconciliation(self, stage: str) -> bool:
            return False

        def has_finalized_instruction(self, instruction_name: str) -> bool:
            return instruction_name == "create_vault_with_usdc"

        async def read_rehearsal_accounts(self) -> dict[str, dict[str, Any]]:
            return {
                "rehearsal_vault_activation": {
                    "decoded": {
                        "account_type": "VaultActivation",
                        "fields": {
                            "vault_id": 0,
                            "is_active": True,
                            "seed_completions_written": 0,
                            "leaderboard_seeded": True,
                            "created_at": 100,
                            "activated_at": 100,
                            "last_seed_at": 100,
                            "seed_generation": 2,
                            "seed_cutoff_at": 100,
                            "economics_start_epoch": creation_week,
                            "matched_users": 0,
                            "matched_completions": 0,
                            "evidence_hash": hashlib.sha256(
                                b"BR_VAULT_EMPTY_HISTORY_V2"
                                + bytes(climb)
                                + bytes(expected_vault)
                            ).hexdigest(),
                        },
                    }
                },
                "rehearsal_record_board": {
                    "decoded": {
                        "account_type": "VaultLeaderboard",
                        "fields": {"vault_id": 0, "entries": [], "last_updated": 0},
                    }
                },
                "rehearsal_local_legend": {
                    "decoded": {
                        "account_type": "LocalLegend",
                        "fields": {
                            "vault_id": 0,
                            "holder": str(rider),
                            "completions_at_election": 0,
                            "runner_up": str(Pubkey.default()),
                            "runner_up_completions": 0,
                            "total_earned": 0,
                            "is_active": True,
                            "is_bootstrap": True,
                        },
                    }
                },
            }

        async def finalize_stage(
            self, stage: str, signature: str | None = None
        ) -> None:
            events.append(("reconcile", (stage, signature)))

    async def read_vault(*args: Any, **kwargs: Any) -> dict[str, Any]:
        events.append(("read_vault", None))
        return vault

    async def override_week(**kwargs: Any) -> str:
        events.append(("override", kwargs))
        return "override-signature"

    monkeypatch.setattr(wallet_smoke, "read_vault_state", read_vault)
    monkeypatch.setattr(
        wallet_smoke,
        "send_admin_override_open_settlement_week",
        override_week,
        raising=False,
    )

    await wallet_smoke.ensure_resume_created_vault(
        config=SimpleNamespace(program_id=program_id),
        evidence=Evidence(),
        rider=rider,
        vault_id=0,
        settlement_week=settlement_week,
    )

    assert [event[0] for event in events] == [
        "read_vault",
        "reconcile",
    ]
    assert events[1][1] == ("create_vault_with_usdc", None)
    assert vault["open_settlement_week"] == creation_week


def test_protected_plan_covers_every_canonical_mutation_family() -> None:
    program_data = Keypair().pubkey()
    canonical_rider = Keypair().pubkey()
    config = {
        "cal_mint": str(wallet_smoke.DEFAULT_CAL_MINT_ADDRESS),
        "dung_mint": str(wallet_smoke.DEFAULT_DUNG_MINT_ADDRESS),
        "usdc_mint": str(wallet_smoke.PROTECTED_TEST_USDC_MINT),
        "usdc_treasury_token_account": "GEL1JhavEKPuqVBvUiezUgNG2VYK1jtzsUazo2Scm1jA",
        "pol_token_account": str(Keypair().pubkey()),
        "treasury_token_account": str(Keypair().pubkey()),
    }

    addresses = wallet_smoke.RehearsalEvidenceManifest._protected_addresses_from_config(
        program_data=program_data,
        program_config=config,
        vault_actors=(canonical_rider,),
    )

    required = {
        "protected_program",
        "protected_program_data",
        "protected_program_config",
        "protected_vault_counter",
        "protected_dung_mint_state",
        "protected_cal_mint",
        "protected_dung_mint",
        "protected_test_usdc_mint",
        "protected_usdc_treasury",
        "protected_dung_pol",
        "protected_dung_treasury",
        "protected_shawmont_climb",
        "protected_shawmont_vault_0",
        "protected_shawmont_activation",
        "protected_shawmont_record_board",
        "protected_shawmont_local_legend",
        "protected_shawmont_lp_mint",
        "protected_shawmont_cal_escrow",
        "protected_shawmont_dung_pot",
        "protected_shawmont_actor_0_stake",
        "protected_shawmont_actor_0_position_lp",
    }
    assert required <= set(addresses)


def test_economic_reconciliation_refuses_wrong_usdc_and_nonzero_final_position() -> None:
    def token(amount: int) -> dict[str, Any]:
        return {"exists": True, "decoded": {"amount_base_units": str(amount)}}

    def mint(supply: int) -> dict[str, Any]:
        return {"exists": True, "decoded": {"supply_base_units": str(supply)}}

    def account(**fields: Any) -> dict[str, Any]:
        return {
            "exists": True,
            "decoded": {"account_type": "test", "fields": fields},
        }

    identity = {
        "vault_creation_usdc": 2_000_000,
        "vault_creation_cal": 1_000,
        "stake_cal": 100_000,
        "harvest_fee_bps": 500,
    }
    funded = {
        "rehearsal_user_cal_ata": token(10_000),
        "rehearsal_cal_mint": mint(50_000),
        "rehearsal_user_usdc_ata": token(9_000_000),
        "rehearsal_usdc_treasury": token(1_000_000),
        "rehearsal_usdc_mint": mint(10_000_000),
        "rehearsal_vault_counter": account(count=0),
    }
    wrong_create = {
        **funded,
        "rehearsal_user_cal_ata": token(9_000),
        "rehearsal_cal_mint": mint(49_000),
        "rehearsal_user_usdc_ata": token(7_000_001),
        "rehearsal_usdc_treasury": token(2_999_999),
        "rehearsal_vault_counter": account(count=1),
    }
    with pytest.raises(RuntimeError, match="USDC creation cost"):
        wallet_smoke.RehearsalEvidenceManifest._validate_economic_reconciliation(
            "create_vault_with_usdc",
            baseline=funded,
            previous=funded,
            current=wrong_create,
            identity=identity,
        )

    distributed = {
        "rehearsal_user_cal_ata": token(1_000),
        "rehearsal_cal_mint": mint(40_000),
        "rehearsal_user_dung_ata": token(100),
        "rehearsal_dung_treasury": token(200),
        "rehearsal_dung_mint": mint(1_000),
        "rehearsal_vault_stake": account(
            cal_staked=100_000, lp_tokens=100_000, rewards_earned=1_000
        ),
        "rehearsal_vault_lp_mint": mint(100_000),
        "rehearsal_position_lp": token(100_000),
        "rehearsal_cal_escrow": token(100_000),
        "rehearsal_expected_vault": account(total_cal_staked=100_000),
    }
    nonzero_final = {
        **distributed,
        "rehearsal_user_cal_ata": token(100_500),
        "rehearsal_cal_mint": mint(39_500),
        "rehearsal_user_dung_ata": token(1_050),
        "rehearsal_dung_treasury": token(250),
        "rehearsal_dung_mint": mint(2_000),
        "rehearsal_vault_stake": account(
            cal_staked=0, lp_tokens=1, rewards_earned=0
        ),
        "rehearsal_vault_lp_mint": mint(1),
        "rehearsal_position_lp": token(1),
        "rehearsal_cal_escrow": token(0),
        "rehearsal_expected_vault": account(total_cal_staked=0),
    }
    with pytest.raises(RuntimeError, match="zero final LP/stake"):
        wallet_smoke.RehearsalEvidenceManifest._validate_economic_reconciliation(
            "collect_then_unstake",
            baseline=distributed,
            previous=distributed,
            current=nonzero_final,
            identity=identity,
        )


@pytest.mark.asyncio
async def test_reconciled_receipt_completion_resumes_without_fresh_cal_delta(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    protected = Keypair().pubkey()
    program_id = Keypair().pubkey()

    def account(label: str, *, exists: bool = True, **fields: Any) -> dict[str, Any]:
        return {
            "address": str(Keypair().pubkey()),
            "exists": exists,
            "owner": str(program_id) if exists else None,
            "data_len": 1 if exists else 0,
            "data_sha256": hashlib.sha256(label.encode()).hexdigest() if exists else None,
            "decoded": (
                {"account_type": label, "fields": fields} if exists else None
            ),
        }

    def token(label: str, amount: int) -> dict[str, Any]:
        item = account(label)
        item["owner"] = str(wallet_smoke.TOKEN_PROGRAM_ID)
        item["decoded"] = {"amount_base_units": str(amount)}
        return item

    def mint(label: str, supply: int) -> dict[str, Any]:
        item = account(label)
        item["owner"] = str(wallet_smoke.TOKEN_PROGRAM_ID)
        item["decoded"] = {"supply_base_units": str(supply)}
        return item

    baseline = {
        "rehearsal_user_cal_ata": token("user_cal", 100),
        "rehearsal_cal_mint": mint("cal_mint", 1_000),
        "rehearsal_expected_vault": account("Vault", total_cal_burned=0),
    }
    completed = {
        **baseline,
        "rehearsal_user_cal_ata": token("user_cal_after", 1_100),
        "rehearsal_cal_mint": mint("cal_mint_after", 2_000),
        "rehearsal_expected_vault": account("Vault", total_cal_burned=250),
        "rehearsal_completion_ride_attestation": account("RideAttestation"),
        "rehearsal_completion_tribute_budget": account(
            "RideTributeBudget", total_cal_tributed=250
        ),
        "rehearsal_completion_cal_receipt": account("CalMintReceipt", amount=1_000),
        "rehearsal_completion_receipt": account("ClimbCompletionReceiptV2"),
        "rehearsal_vault_completion": account(
            "VaultCompletion", total_cal_tributed=250
        ),
    }
    identity = {"vault_alloc_cal": 1_000}
    economic_checks = (
        wallet_smoke.RehearsalEvidenceManifest._validate_economic_reconciliation(
            "receipt_backed_completion",
            baseline=baseline,
            previous=baseline,
            current=completed,
            identity=identity,
        )
    )
    protected_snapshot = {
        "protected": {
            "address": str(protected),
            "exists": False,
            "owner": None,
            "data_len": 0,
            "data_sha256": None,
            "decoded": None,
        }
    }
    state = {
        "schema": "boulderroller_v4b_rehearsal_evidence_v2",
        "identity": identity,
        "protected_addresses": {"protected": str(protected)},
        "rehearsal_addresses": {
            label: item["address"] for label, item in completed.items()
        },
        "dynamic_rehearsal_addresses": {},
        "baseline": {
            "protected": protected_snapshot,
            "rehearsal": baseline,
        },
        "transactions": [],
        "reconciliations": [
            {
                "stage": "receipt_backed_completion",
                "protected": protected_snapshot,
                "rehearsal": completed,
                "economic_checks": economic_checks,
            }
        ],
    }
    evidence_path = tmp_path / "receipt-resume.json"
    evidence_path.write_text(json.dumps(state), encoding="utf-8")
    manifest = wallet_smoke.RehearsalEvidenceManifest(
        path=evidence_path,
        rpc_url="http://rpc.test",
        state=state,
    )

    async def read_accounts(
        cls: object,
        rpc_url: str,
        addresses: dict[str, Pubkey],
    ) -> tuple[int, dict[str, dict[str, Any]]]:
        if "protected" in addresses:
            return 50, protected_snapshot
        return 51, completed

    monkeypatch.setattr(
        wallet_smoke.RehearsalEvidenceManifest,
        "_read_accounts",
        classmethod(read_accounts),
    )
    monkeypatch.setattr(
        wallet_smoke.RehearsalEvidenceManifest,
        "_validate_rehearsal_authorities",
        staticmethod(lambda *args, **kwargs: None),
    )

    before = evidence_path.read_bytes()
    await manifest.capture_reconciliation("receipt_backed_completion")
    assert evidence_path.read_bytes() == before
    assert len(manifest._state["reconciliations"]) == 1

    completed["rehearsal_completion_cal_receipt"]["decoded"]["fields"][
        "amount"
    ] = 999
    with pytest.raises(RuntimeError, match="frozen receipt-backed completion"):
        await manifest.capture_reconciliation("receipt_backed_completion")


@pytest.mark.parametrize(
    ("decimals", "mint_authority", "freeze_authority", "message"),
    (
        (5, None, None, "exactly 6 decimals"),
        (6, "foreign", None, "mint authority"),
        (6, "admin", None, "mint authority"),
        (6, None, "present", "no freeze authority"),
    ),
)
def test_fresh_preflight_refuses_wrong_usdc_mint_authority_shape(
    decimals: int,
    mint_authority: str | None,
    freeze_authority: str | None,
    message: str,
) -> None:
    admin = Keypair().pubkey()
    data = bytearray(82)
    if mint_authority is not None:
        struct.pack_into("<I", data, 0, 1)
        data[4:36] = bytes(
            admin if mint_authority == "admin" else Keypair().pubkey()
        )
    struct.pack_into("<Q", data, 36, 10_000_000)
    data[44] = decimals
    data[45] = 1
    if freeze_authority is not None:
        struct.pack_into("<I", data, 46, 1)
        data[50:82] = bytes(Keypair().pubkey())
    account = SimpleNamespace(owner=wallet_smoke.TOKEN_PROGRAM_ID, data=bytes(data))
    with pytest.raises(RuntimeError, match=message):
        wallet_smoke._decode_rehearsal_usdc_mint(account, admin=admin)


def test_setup_evidence_refuses_wrong_initial_owner_balance_and_supply(
    tmp_path: Path,
) -> None:
    admin = Keypair().pubkey()
    rider = Keypair().pubkey()
    mint = Keypair().pubkey()
    program = Keypair().pubkey()
    cal_mint = Keypair().pubkey()
    rider_cal_ata = Keypair().pubkey()
    cal_authority, _ = setup_evidence._derive_cal_mint_auth_pda(program)
    state = {
        "schema": setup_evidence.SETUP_SCHEMA,
        "identity": {
            "program_id": str(program),
            "admin": str(admin),
            "backend_authority": str(Keypair().pubkey()),
            "fee_payer": str(Keypair().pubkey()),
            "rider": str(rider),
            "cal_mint": str(cal_mint),
            "rider_cal_ata": str(rider_cal_ata),
            "usdc_mint": str(mint),
            "usdc_treasury": str(Keypair().pubkey()),
            "rider_usdc_ata": str(Keypair().pubkey()),
            "initial_usdc_supply": 10_000_000,
            "vault_creation_usdc": 2_000_000,
        },
        "protected_addresses": {},
        "setup_addresses": {},
        "baseline": {"protected": {}},
        "transactions": [],
        "reconciliations": [],
    }
    manifest = setup_evidence.RehearsalSetupEvidenceManifest(
        path=tmp_path / "setup.json",
        rpc_url="http://rpc.test",
        state=state,
    )
    snapshot = {
        "setup_cal_mint": {
            "exists": True,
            "address": str(cal_mint),
            "owner": str(wallet_smoke.TOKEN_PROGRAM_ID),
            "decoded": {
                "decimals": 9,
                "initialized": True,
                "supply_base_units": "0",
                "mint_authority": str(cal_authority),
                "freeze_authority": None,
            },
        },
        "setup_rider_cal_ata": {
            "exists": True,
            "owner": str(wallet_smoke.TOKEN_PROGRAM_ID),
            "decoded": {
                "mint": str(cal_mint),
                "token_owner": str(rider),
                "amount_base_units": "0",
                "state": 1,
            },
        },
        "setup_usdc_mint": {
            "exists": True,
            "decoded": {
                "decimals": 6,
                "initialized": True,
                "mint_authority": None,
                "freeze_authority": None,
                "supply_base_units": "10_000_000".replace("_", ""),
            },
        },
        "setup_usdc_treasury": {
            "exists": True,
            "decoded": {
                "mint": str(mint),
                "token_owner": str(rider),
                "amount_base_units": "1",
            },
        },
        "setup_rider_usdc_ata": {
            "exists": True,
            "decoded": {
                "mint": str(mint),
                "token_owner": str(rider),
                "amount_base_units": "9999999",
            },
        },
        "setup_program_config": {
            "exists": True,
            "decoded": {"fields": {}},
        },
    }
    with pytest.raises(RuntimeError, match="treasury.*owner"):
        manifest._validate_stage_snapshot("setup_ready", snapshot)


def test_setup_evidence_binds_exact_cal_mint_and_zero_rider_ata(
    tmp_path: Path,
) -> None:
    admin = Keypair().pubkey()
    backend = Keypair().pubkey()
    rider = Keypair().pubkey()
    program = Keypair().pubkey()
    program_data = Keypair().pubkey()
    cal_mint = Keypair().pubkey()
    usdc_mint = Keypair().pubkey()
    rider_cal_ata = Keypair().pubkey()
    treasury = Keypair().pubkey()
    rider_usdc_ata = Keypair().pubkey()
    cal_authority, _ = setup_evidence._derive_cal_mint_auth_pda(program)
    manifest = setup_evidence.RehearsalSetupEvidenceManifest(
        path=tmp_path / "setup-cal.json",
        rpc_url="http://rpc.test",
        state={
            "schema": setup_evidence.SETUP_SCHEMA,
            "identity": {
                "program_id": str(program),
                "program_data": str(program_data),
                "admin": str(admin),
                "backend_authority": str(backend),
                "fee_payer": str(Keypair().pubkey()),
                "rider": str(rider),
                "cal_mint": str(cal_mint),
                "rider_cal_ata": str(rider_cal_ata),
                "usdc_mint": str(usdc_mint),
                "usdc_treasury": str(treasury),
                "rider_usdc_ata": str(rider_usdc_ata),
                "initial_usdc_supply": 10_000_000,
                "vault_creation_usdc": 2_000_000,
            },
            "protected_addresses": {},
            "setup_addresses": {},
            "baseline": {"protected": {}},
            "transactions": [],
            "reconciliations": [],
        },
    )
    snapshot = {
        "setup_cal_mint": {
            "exists": True,
            "owner": str(wallet_smoke.TOKEN_PROGRAM_ID),
            "address": str(cal_mint),
            "decoded": {
                "decimals": 9,
                "initialized": True,
                "supply_base_units": "0",
                "mint_authority": str(cal_authority),
                "freeze_authority": None,
            },
        },
        "setup_rider_cal_ata": {
            "exists": True,
            "owner": str(wallet_smoke.TOKEN_PROGRAM_ID),
            "decoded": {
                "mint": str(cal_mint),
                "token_owner": str(rider),
                "amount_base_units": "1",
                "state": 1,
            },
        },
        "setup_usdc_mint": {
            "exists": True,
            "decoded": {
                "decimals": 6,
                "initialized": True,
                "mint_authority": str(admin),
                "freeze_authority": None,
                "supply_base_units": "0",
            },
        },
        "setup_usdc_treasury": {
            "exists": True,
            "decoded": {
                "mint": str(usdc_mint),
                "token_owner": str(admin),
                "amount_base_units": "0",
            },
        },
        "setup_rider_usdc_ata": {
            "exists": True,
            "decoded": {
                "mint": str(usdc_mint),
                "token_owner": str(rider),
                "amount_base_units": "0",
            },
        },
    }

    with pytest.raises(RuntimeError, match="rider CAL ATA.*zero"):
        manifest._validate_stage_snapshot("atas_created", snapshot)


def test_setup_evidence_refuses_program_config_signer_mismatch() -> None:
    program = Keypair().pubkey()
    program_data = Keypair().pubkey()
    admin = Keypair().pubkey()
    backend = Keypair().pubkey()
    cal_mint = Keypair().pubkey()
    setup = {
        "setup_program": {
            "exists": True,
            "owner": str(setup_evidence.BPF_UPGRADEABLE_LOADER_ID),
            "executable": True,
            "decoded": {"program_data_address": str(program_data)},
        },
        "setup_program_data": {
            "exists": True,
            "owner": str(setup_evidence.BPF_UPGRADEABLE_LOADER_ID),
            "decoded": {"loader_state": "ProgramData"},
        },
        "setup_program_config": {
            "exists": True,
            "owner": str(program),
            "decoded": {
                "account_type": "ProgramConfig",
                "fields": {
                    "admin_authority": str(admin),
                    "backend_authority": str(Keypair().pubkey()),
                    "cal_mint": str(cal_mint),
                },
            },
        },
    }

    with pytest.raises(RuntimeError, match="backend signer"):
        setup_evidence.RehearsalSetupEvidenceManifest._validate_setup_program_baseline(
            setup,
            program_id=program,
            program_data=program_data,
            admin=admin,
            backend_authority=backend,
            cal_mint=cal_mint,
        )


def test_setup_program_config_decodes_only_for_frozen_4jjn_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    program = Pubkey.from_string("4JjnqN6fDqXNyokz62d4pNDirNs9ffVgQA6rLojPfKmF")
    config = Keypair().pubkey()
    account = SimpleNamespace(
        owner=program,
        data=b"live-shaped-program-config",
        lamports=1,
        executable=False,
    )
    coder = SimpleNamespace(
        parse=lambda data: SimpleNamespace(
            name="ProgramConfig",
            data=SimpleNamespace(
                admin_authority=Keypair().pubkey(),
                backend_authority=Keypair().pubkey(),
            ),
        )
    )
    monkeypatch.setattr(setup_evidence, "_get_boulder_accounts_coder", lambda: coder)

    decoded = setup_evidence.RehearsalSetupEvidenceManifest._setup_account_evidence(
        "setup_program_config",
        config,
        account,
        program_id=program,
    )
    assert decoded["decoded"]["account_type"] == "ProgramConfig"

    wrong_owner = SimpleNamespace(**{**vars(account), "owner": Keypair().pubkey()})
    with pytest.raises(RuntimeError, match="not owned by the setup program"):
        setup_evidence.RehearsalSetupEvidenceManifest._setup_account_evidence(
            "setup_program_config",
            config,
            wrong_owner,
            program_id=program,
        )

    wrong_type = SimpleNamespace(
        parse=lambda data: SimpleNamespace(
            name="VaultCounter", data=SimpleNamespace(count=0)
        )
    )
    monkeypatch.setattr(
        setup_evidence,
        "_get_boulder_accounts_coder",
        lambda: wrong_type,
    )
    with pytest.raises(RuntimeError, match="expected ProgramConfig"):
        setup_evidence.RehearsalSetupEvidenceManifest._setup_account_evidence(
            "setup_program_config",
            config,
            account,
            program_id=program,
        )


def test_setup_operator_refuses_partial_program_config_before_writes() -> None:
    admin = Keypair().pubkey()
    mint = Keypair().pubkey()
    with pytest.raises(RuntimeError, match="foreign partial USDC setup"):
        setup_command._validate_program_config_usdc_state(
            {
                "usdc_mint": str(Pubkey.default()),
                "usdc_treasury_token_account": str(Keypair().pubkey()),
                "vault_creation_usdc": 2_000_000,
            },
            admin=admin,
            usdc_mint=mint,
            vault_creation_usdc=2_000_000,
        )


def test_setup_operator_accepts_live_blank_rail_only_at_frozen_bootstrap_cost() -> None:
    admin = Keypair().pubkey()
    mint = Keypair().pubkey()
    blank_live_config = {
        "usdc_mint": str(Pubkey.default()),
        "usdc_treasury_token_account": str(Pubkey.default()),
        "vault_creation_usdc": 2_000_000,
    }

    assert (
        setup_command._validate_program_config_usdc_state(
            blank_live_config,
            admin=admin,
            usdc_mint=mint,
            vault_creation_usdc=2_000_000,
        )
        is False
    )

    for invalid_cost in (0, 1, 1_999_999, 2_000_001):
        with pytest.raises(RuntimeError, match="foreign partial USDC setup"):
            setup_command._validate_program_config_usdc_state(
                {**blank_live_config, "vault_creation_usdc": invalid_cost},
                admin=admin,
                usdc_mint=mint,
                vault_creation_usdc=2_000_000,
            )
    with pytest.raises(RuntimeError, match="frozen bootstrap constant"):
        setup_command._validate_program_config_usdc_state(
            blank_live_config,
            admin=admin,
            usdc_mint=mint,
            vault_creation_usdc=2_000_001,
        )

    treasury = setup_command._derive_ata(admin, mint)
    assert setup_command._validate_program_config_usdc_state(
        {
            "usdc_mint": str(mint),
            "usdc_treasury_token_account": str(treasury),
            "vault_creation_usdc": 2_000_000,
        },
        admin=admin,
        usdc_mint=mint,
        vault_creation_usdc=2_000_000,
    )
    for foreign_config in (
        {
            "usdc_mint": str(Keypair().pubkey()),
            "usdc_treasury_token_account": str(treasury),
            "vault_creation_usdc": 2_000_000,
        },
        {
            "usdc_mint": str(mint),
            "usdc_treasury_token_account": str(Keypair().pubkey()),
            "vault_creation_usdc": 2_000_000,
        },
        {
            "usdc_mint": str(mint),
            "usdc_treasury_token_account": str(treasury),
            "vault_creation_usdc": 2_000_001,
        },
    ):
        with pytest.raises(RuntimeError, match="foreign USDC configuration"):
            setup_command._validate_program_config_usdc_state(
                foreign_config,
                admin=admin,
                usdc_mint=mint,
                vault_creation_usdc=2_000_000,
            )


@pytest.mark.asyncio
async def test_setup_evidence_open_accepts_live_bootstrap_rail_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    program = Keypair().pubkey()
    program_data = Keypair().pubkey()
    admin = Keypair().pubkey()
    backend = Keypair().pubkey()
    payer = Keypair().pubkey()
    rider = Keypair().pubkey()
    cal_mint = Keypair().pubkey()
    usdc_mint = Keypair().pubkey()
    config_cost = 2_000_000
    config_treasury = str(Pubkey.default())

    async def resolve_protected(
        cls: object, rpc_url: str
    ) -> dict[str, Pubkey]:
        return {}

    async def read_accounts(
        cls: object,
        rpc_url: str,
        addresses: dict[str, Pubkey],
    ) -> tuple[int, dict[str, dict[str, Any]]]:
        snapshot = {
            label: {"exists": False, "address": str(address)}
            for label, address in addresses.items()
        }
        if "setup_program_config" in snapshot:
            snapshot["setup_program_config"] = {
                "exists": True,
                "address": str(addresses["setup_program_config"]),
                "decoded": {
                    "fields": {
                        "usdc_mint": str(Pubkey.default()),
                        "usdc_treasury_token_account": config_treasury,
                        "vault_creation_usdc": config_cost,
                    }
                },
            }
        return 1, snapshot

    monkeypatch.setattr(
        setup_evidence.RehearsalSetupEvidenceManifest,
        "_resolve_protected_addresses",
        classmethod(resolve_protected),
    )
    monkeypatch.setattr(
        setup_evidence.RehearsalSetupEvidenceManifest,
        "_read_accounts",
        classmethod(read_accounts),
    )
    monkeypatch.setattr(
        setup_evidence.RehearsalSetupEvidenceManifest,
        "_validate_setup_program_baseline",
        classmethod(lambda cls, *args, **kwargs: None),
    )

    async def open_at(name: str) -> object:
        return await setup_evidence.RehearsalSetupEvidenceManifest.open(
            path=tmp_path / name,
            rpc_url="http://rpc.test",
            program_id=program,
            program_data=program_data,
            admin=admin,
            backend_authority=backend,
            fee_payer=payer,
            rider=rider,
            cal_mint=cal_mint,
            usdc_mint=usdc_mint,
            initial_usdc_supply=10_000_000,
            vault_creation_usdc=2_000_000,
        )

    assert await open_at("live-bootstrap.json")

    for index, invalid_cost in enumerate((0, 1, 2_000_001)):
        config_cost = invalid_cost
        with pytest.raises(RuntimeError, match="bootstrap ProgramConfig USDC rail"):
            await open_at(f"invalid-cost-{index}.json")

    config_cost = 2_000_000
    config_treasury = str(Keypair().pubkey())
    with pytest.raises(RuntimeError, match="bootstrap ProgramConfig USDC rail"):
        await open_at("foreign-treasury.json")


@pytest.mark.asyncio
async def test_setup_ready_resume_preserves_frozen_handoff_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin = Keypair().pubkey()
    rider = Keypair().pubkey()
    mint = Keypair().pubkey()
    cal_mint = Keypair().pubkey()
    program = Keypair().pubkey()
    protected_address = Keypair().pubkey()
    setup_addresses = {
        label: Keypair().pubkey()
        for label in (
            "setup_program",
            "setup_program_data",
            "setup_program_config",
            "setup_cal_mint",
            "setup_rider_cal_ata",
            "setup_usdc_mint",
            "setup_usdc_treasury",
            "setup_rider_usdc_ata",
        )
    }
    setup_addresses["setup_cal_mint"] = cal_mint
    treasury = setup_addresses["setup_usdc_treasury"]
    cal_authority, _ = setup_evidence._derive_cal_mint_auth_pda(program)
    identity = {
        "program_id": str(program),
        "program_data": str(setup_addresses["setup_program_data"]),
        "admin": str(admin),
        "backend_authority": str(Keypair().pubkey()),
        "fee_payer": str(Keypair().pubkey()),
        "rider": str(rider),
        "cal_mint": str(cal_mint),
        "rider_cal_ata": str(setup_addresses["setup_rider_cal_ata"]),
        "usdc_mint": str(mint),
        "usdc_treasury": str(treasury),
        "rider_usdc_ata": str(setup_addresses["setup_rider_usdc_ata"]),
        "initial_usdc_supply": 10_000_000,
        "vault_creation_usdc": 2_000_000,
    }
    protected_snapshot = {
        "protected": {
            "address": str(protected_address),
            "exists": False,
            "owner": None,
            "lamports": 0,
            "executable": False,
            "data_len": 0,
            "data_sha256": None,
            "decoded": None,
        }
    }
    setup_snapshot = {
        "setup_cal_mint": {
            "exists": True,
            "address": str(cal_mint),
            "owner": str(wallet_smoke.TOKEN_PROGRAM_ID),
            "decoded": {
                "decimals": 9,
                "initialized": True,
                "supply_base_units": "0",
                "mint_authority": str(cal_authority),
                "freeze_authority": None,
            },
        },
        "setup_rider_cal_ata": {
            "exists": True,
            "owner": str(wallet_smoke.TOKEN_PROGRAM_ID),
            "decoded": {
                "mint": str(cal_mint),
                "token_owner": str(rider),
                "amount_base_units": "0",
                "state": 1,
            },
        },
        "setup_usdc_mint": {
            "exists": True,
            "decoded": {
                "decimals": 6,
                "initialized": True,
                "mint_authority": None,
                "freeze_authority": None,
                "supply_base_units": "10000000",
            },
        },
        "setup_usdc_treasury": {
            "exists": True,
            "decoded": {
                "mint": str(mint),
                "token_owner": str(admin),
                "amount_base_units": "0",
            },
        },
        "setup_rider_usdc_ata": {
            "exists": True,
            "decoded": {
                "mint": str(mint),
                "token_owner": str(rider),
                "amount_base_units": "10000000",
            },
        },
        "setup_program_config": {
            "exists": True,
            "decoded": {
                "fields": {
                    "usdc_mint": str(mint),
                    "usdc_treasury_token_account": str(treasury),
                    "vault_creation_usdc": 2_000_000,
                }
            },
        },
    }
    evidence_path = tmp_path / "setup.json"
    state = {
        "schema": setup_evidence.SETUP_SCHEMA,
        "mode": "usdc_setup",
        "identity": identity,
        "protected_addresses": {"protected": str(protected_address)},
        "setup_addresses": {
            label: str(address) for label, address in setup_addresses.items()
        },
        "baseline": {"protected": protected_snapshot, "setup": {}},
        "transactions": [],
        "reconciliations": [],
        "handoff": None,
    }
    evidence_path.write_text(json.dumps(state), encoding="utf-8")
    manifest = setup_evidence.RehearsalSetupEvidenceManifest(
        path=evidence_path,
        rpc_url="http://rpc.test",
        state=state,
    )

    async def read_accounts(
        cls: object,
        rpc_url: str,
        addresses: dict[str, Pubkey],
    ) -> tuple[int, dict[str, dict[str, Any]]]:
        if "protected" in addresses:
            return 10, protected_snapshot
        return 11, setup_snapshot

    monkeypatch.setattr(
        setup_evidence.RehearsalSetupEvidenceManifest,
        "_read_accounts",
        classmethod(read_accounts),
    )

    await manifest.capture_setup_stage("setup_ready")
    first_bytes = evidence_path.read_bytes()
    await manifest.capture_setup_stage("setup_ready")

    assert evidence_path.read_bytes() == first_bytes
    saved = json.loads(first_bytes)
    assert len(saved["reconciliations"]) == 1
    assert saved["handoff"]["mint_authority_revoked"] is True
    assert saved["handoff"]["initial_rider_cal_balance"] == 0


@pytest.mark.asyncio
async def test_setup_progress_recovers_only_latest_finalized_stage_and_freezes_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    protected = Keypair().pubkey()
    program = Keypair().pubkey()
    admin = Keypair().pubkey()
    rider = Keypair().pubkey()
    cal_mint = Keypair().pubkey()
    cal_authority, _ = setup_evidence._derive_cal_mint_auth_pda(program)
    setup_addresses = {
        label: Keypair().pubkey()
        for label in (
            "setup_program",
            "setup_program_data",
            "setup_program_config",
            "setup_cal_mint",
            "setup_rider_cal_ata",
            "setup_usdc_mint",
            "setup_usdc_treasury",
            "setup_rider_usdc_ata",
        )
    }
    setup_addresses["setup_cal_mint"] = cal_mint
    protected_snapshot = {"protected": {"address": str(protected), "exists": False}}
    baseline_setup = {
        label: {"address": str(address), "exists": False}
        for label, address in setup_addresses.items()
    }
    baseline_setup["setup_cal_mint"] = {
        "address": str(cal_mint),
        "exists": True,
        "owner": str(wallet_smoke.TOKEN_PROGRAM_ID),
        "decoded": {
            "decimals": 9,
            "initialized": True,
            "mint_authority": str(cal_authority),
            "freeze_authority": None,
            "supply_base_units": "0",
        },
    }
    current_setup = {
        **baseline_setup,
        "setup_usdc_mint": {
            "address": str(setup_addresses["setup_usdc_mint"]),
            "exists": True,
            "decoded": {
                "decimals": 6,
                "initialized": True,
                "mint_authority": str(admin),
                "freeze_authority": None,
                "supply_base_units": "0",
            },
        },
    }
    state = {
        "schema": setup_evidence.SETUP_SCHEMA,
        "identity": {
            "program_id": str(program),
            "admin": str(admin),
            "initial_usdc_supply": 10_000_000,
            "cal_mint": str(cal_mint),
            "rider_cal_ata": str(setup_addresses["setup_rider_cal_ata"]),
            "usdc_mint": str(setup_addresses["setup_usdc_mint"]),
            "rider": str(rider),
            "vault_creation_usdc": 2_000_000,
        },
        "protected_addresses": {"protected": str(protected)},
        "setup_addresses": {
            label: str(address) for label, address in setup_addresses.items()
        },
        "baseline": {
            "protected": protected_snapshot,
            "setup": baseline_setup,
        },
        "transactions": [
            {
                "signature": str(Signature.default()),
                "status": "finalized",
                "metadata": {"tx_type": "rehearsal_usdc_mint_created"},
            }
        ],
        "reconciliations": [],
        "handoff": None,
    }
    evidence_path = tmp_path / "setup-progress.json"
    evidence_path.write_text(json.dumps(state), encoding="utf-8")
    manifest = setup_evidence.RehearsalSetupEvidenceManifest(
        path=evidence_path,
        rpc_url="http://rpc.test",
        state=state,
    )

    async def read_accounts(
        cls: object,
        rpc_url: str,
        addresses: dict[str, Pubkey],
    ) -> tuple[int, dict[str, dict[str, Any]]]:
        if "protected" in addresses:
            return 20, protected_snapshot
        return 21, current_setup

    async def reconcile(signature: str) -> int:
        return 21

    monkeypatch.setattr(
        setup_evidence.RehearsalSetupEvidenceManifest,
        "_read_accounts",
        classmethod(read_accounts),
    )
    monkeypatch.setattr(manifest, "reconcile_signature", reconcile)

    await manifest.preflight_setup_progress()
    saved = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert [item["stage"] for item in saved["reconciliations"]] == ["mint_created"]

    current_setup["setup_usdc_mint"]["decoded"]["supply_base_units"] = "1"
    with pytest.raises(RuntimeError, match="changed after its latest durable stage"):
        await manifest.preflight_setup_progress()


def test_setup_handoff_refuses_wrong_loaded_signers(tmp_path: Path) -> None:
    program = Keypair().pubkey()
    rider = Keypair().pubkey()
    backend = Keypair().pubkey()
    payer = Keypair().pubkey()
    artifact = tmp_path / "setup.json"
    artifact.write_text(
        json.dumps(
            {
                "schema": wallet_smoke.REHEARSAL_SETUP_SCHEMA,
                "handoff": {
                    "status": "ready",
                    "mint_authority_revoked": True,
                    "program_id": str(program),
                    "rider": str(rider),
                    "backend_authority": str(backend),
                    "fee_payer": str(payer),
                },
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="backend signer"):
        wallet_smoke._load_rehearsal_setup_handoff(
            artifact,
            program_id=program,
            user=rider,
            backend_authority=Keypair().pubkey(),
            fee_payer=payer,
        )


def test_setup_handoff_requires_complete_guarded_transaction_chain(
    tmp_path: Path,
) -> None:
    program = Keypair().pubkey()
    rider = Keypair().pubkey()
    backend = Keypair().pubkey()
    payer = Keypair().pubkey()
    admin = Keypair().pubkey()
    cal_mint = Keypair().pubkey()
    rider_cal_ata = wallet_smoke._derive_ata(rider, cal_mint)
    identity = {
        "program_id": str(program),
        "program_data": str(Keypair().pubkey()),
        "admin": str(admin),
        "backend_authority": str(backend),
        "fee_payer": str(payer),
        "rider": str(rider),
        "cal_mint": str(cal_mint),
        "rider_cal_ata": str(rider_cal_ata),
        "usdc_mint": str(Keypair().pubkey()),
        "usdc_treasury": str(Keypair().pubkey()),
        "rider_usdc_ata": str(Keypair().pubkey()),
        "initial_usdc_supply": 10_000_000,
        "vault_creation_usdc": 2_000_000,
    }
    required_protected = {
        "protected_program",
        "protected_program_data",
        "protected_program_config",
        "protected_vault_counter",
        "protected_dung_mint_state",
        "protected_cal_mint",
        "protected_dung_mint",
        "protected_test_usdc_mint",
        "protected_usdc_treasury",
        "protected_dung_pol",
        "protected_dung_treasury",
        "protected_shawmont_climb",
        "protected_shawmont_vault_0",
        "protected_shawmont_activation",
        "protected_shawmont_record_board",
        "protected_shawmont_local_legend",
        "protected_shawmont_lp_mint",
        "protected_shawmont_cal_escrow",
        "protected_shawmont_dung_pot",
    }
    tx_stages = (
        "mint_created",
        "atas_created",
        "supply_minted",
        "mint_authority_revoked",
        "configured",
    )
    state = {
        "schema": wallet_smoke.REHEARSAL_SETUP_SCHEMA,
        "identity": identity,
        "handoff": {
            "status": "ready",
            **identity,
            "mint_authority_revoked": True,
            "initial_rider_cal_balance": 0,
            "initial_rider_usdc_balance": 10_000_000,
            "initial_treasury_usdc_balance": 0,
        },
        "protected_addresses": {
            label: str(Keypair().pubkey()) for label in required_protected
        },
        "baseline": {
            "setup": {
                "setup_usdc_mint": {"exists": False},
                "setup_usdc_treasury": {"exists": False},
                "setup_rider_usdc_ata": {"exists": False},
                "setup_rider_cal_ata": {"exists": False},
            }
        },
        "transactions": [
            {
                "signature": f"signature-{index}",
                "status": "finalized",
                "slot": index + 1,
                "metadata": {"tx_type": f"rehearsal_usdc_{stage}"},
                "account_set": [str(program)],
                "instruction_order": [{"index": 0}],
            }
            for index, stage in enumerate(tx_stages)
        ],
        "reconciliations": [
            {"stage": stage} for stage in (*tx_stages, "setup_ready")
        ],
    }
    artifact = tmp_path / "guarded-setup.json"
    artifact.write_text(json.dumps(state), encoding="utf-8")

    handoff, digest = wallet_smoke._load_rehearsal_setup_handoff(
        artifact,
        program_id=program,
        user=rider,
        backend_authority=backend,
        fee_payer=payer,
    )
    assert handoff["mint_authority_revoked"] is True
    assert digest == hashlib.sha256(artifact.read_bytes()).hexdigest()

    state["transactions"] = state["transactions"][:-2] + state["transactions"][-1:]
    artifact.write_text(json.dumps(state), encoding="utf-8")
    with pytest.raises(RuntimeError, match="mint_authority_revoked"):
        wallet_smoke._load_rehearsal_setup_handoff(
            artifact,
            program_id=program,
            user=rider,
            backend_authority=backend,
            fee_payer=payer,
        )


@pytest.mark.asyncio
async def test_guarded_usdc_setup_first_run_revokes_authority_and_resume_is_noop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    program = Keypair().pubkey()
    program_data = Keypair().pubkey()
    admin = Keypair()
    backend = Keypair()
    fee_payer = Keypair()
    rider = Keypair().pubkey()
    cal_mint = Keypair().pubkey()
    mint = Keypair()
    evidence_path = tmp_path / "setup-evidence.json"
    args = SimpleNamespace(
        rehearsal_lane=True,
        rpc_url="http://rpc.test",
        program_id=str(program),
        admin_keypair="admin.json",
        backend_authority_keypair="backend.json",
        fee_payer_keypair="payer.json",
        rider=str(rider),
        usdc_mint_keypair="mint.json",
        initial_usdc_supply=10_000_000,
        vault_creation_usdc=2_000_000,
        rehearsal_setup_evidence=str(evidence_path),
    )
    treasury = setup_command._derive_ata(admin.pubkey(), mint.pubkey())
    rider_ata = setup_command._derive_ata(rider, mint.pubkey())
    rider_cal_ata = setup_command._derive_ata(rider, cal_mint)
    cal_authority, _ = setup_evidence._derive_cal_mint_auth_pda(program)
    configured = False
    activated = False
    submitted: list[tuple[str, tuple[str, ...]]] = []
    finalized: list[str] = []
    captures: list[str] = []
    snapshot: dict[str, dict[str, Any]] = {
        "setup_program": {"exists": True},
        "setup_program_data": {"exists": True},
        "setup_program_config": {"exists": True, "decoded": {"fields": {}}},
        "setup_cal_mint": {
            "exists": True,
            "address": str(cal_mint),
            "owner": str(wallet_smoke.TOKEN_PROGRAM_ID),
            "decoded": {
                "decimals": 9,
                "initialized": True,
                "mint_authority": str(cal_authority),
                "freeze_authority": None,
                "supply_base_units": "0",
            },
        },
        "setup_rider_cal_ata": {"exists": False, "decoded": None},
        "setup_usdc_mint": {"exists": False, "decoded": None},
        "setup_usdc_treasury": {"exists": False, "decoded": None},
        "setup_rider_usdc_ata": {"exists": False, "decoded": None},
    }

    class FakeEvidence:
        path = evidence_path

        def claim_run_lock(self) -> None:
            return None

        async def reconcile_prepared_transactions(self) -> None:
            return None

        async def preflight_setup_progress(self) -> None:
            return None

        def _setup_addresses(self) -> dict[str, Pubkey]:
            return {
                "setup_program": program,
                "setup_program_data": program_data,
                "setup_program_config": Keypair().pubkey(),
                "setup_cal_mint": cal_mint,
                "setup_rider_cal_ata": rider_cal_ata,
                "setup_usdc_mint": mint.pubkey(),
                "setup_usdc_treasury": treasury,
                "setup_rider_usdc_ata": rider_ata,
            }

        async def _read_accounts(
            self, rpc_url: str, addresses: dict[str, Pubkey]
        ) -> tuple[int, dict[str, dict[str, Any]]]:
            return 1, snapshot

        async def finalize_setup_stage(
            self, stage: str, signature: str | None = None
        ) -> None:
            assert signature == f"{stage}-signature"
            finalized.append(stage)

        async def capture_setup_stage(self, stage: str) -> None:
            assert stage == "setup_ready"
            assert snapshot["setup_usdc_mint"]["decoded"]["mint_authority"] is None
            captures.append(stage)

    evidence = FakeEvidence()

    async def open_evidence(cls: object, **kwargs: Any) -> FakeEvidence:
        assert kwargs["usdc_mint"] == mint.pubkey()
        assert kwargs["cal_mint"] == cal_mint
        assert kwargs["admin"] == admin.pubkey()
        return evidence

    async def program_config(config: object) -> dict[str, Any]:
        if configured:
            return {
                "initialized": True,
                "admin_authority": str(admin.pubkey()),
                "backend_authority": str(backend.pubkey()),
                "cal_mint": str(cal_mint),
                "usdc_mint": str(mint.pubkey()),
                "usdc_treasury_token_account": str(treasury),
                "vault_creation_usdc": 2_000_000,
            }
        return {
            "initialized": True,
            "admin_authority": str(admin.pubkey()),
            "backend_authority": str(backend.pubkey()),
            "cal_mint": str(cal_mint),
            "usdc_mint": str(Pubkey.default()),
            "usdc_treasury_token_account": str(Pubkey.default()),
            "vault_creation_usdc": 2_000_000,
        }

    class Client:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def __aenter__(self) -> "Client":
            return self

        async def __aexit__(self, *args: Any) -> None:
            return None

        async def get_minimum_balance_for_rent_exemption(self, size: int) -> Any:
            assert size == setup_command.MINT_ACCOUNT_SIZE
            return SimpleNamespace(value=1_000_000)

    async def submit(**kwargs: Any) -> str:
        nonlocal configured
        assert activated
        stage = str(kwargs["stage"])
        instructions = tuple(str(ix.program_id) for ix in kwargs["instructions"])
        submitted.append((stage, instructions))
        if stage == "mint_created":
            snapshot["setup_usdc_mint"] = {
                "exists": True,
                "decoded": {
                    "decimals": 6,
                    "initialized": True,
                    "mint_authority": str(admin.pubkey()),
                    "freeze_authority": None,
                    "supply_base_units": "0",
                },
            }
        elif stage == "atas_created":
            snapshot["setup_usdc_treasury"] = {
                "exists": True,
                "decoded": {
                    "mint": str(mint.pubkey()),
                    "token_owner": str(admin.pubkey()),
                    "amount_base_units": "0",
                },
            }
            snapshot["setup_rider_usdc_ata"] = {
                "exists": True,
                "decoded": {
                    "mint": str(mint.pubkey()),
                    "token_owner": str(rider),
                    "amount_base_units": "0",
                },
            }
            snapshot["setup_rider_cal_ata"] = {
                "exists": True,
                "owner": str(wallet_smoke.TOKEN_PROGRAM_ID),
                "decoded": {
                    "mint": str(cal_mint),
                    "token_owner": str(rider),
                    "amount_base_units": "0",
                    "state": 1,
                },
            }
        elif stage == "supply_minted":
            snapshot["setup_usdc_mint"]["decoded"]["supply_base_units"] = str(
                args.initial_usdc_supply
            )
            snapshot["setup_rider_usdc_ata"]["decoded"][
                "amount_base_units"
            ] = str(args.initial_usdc_supply)
        elif stage == "mint_authority_revoked":
            snapshot["setup_usdc_mint"]["decoded"]["mint_authority"] = None
        elif stage == "configured":
            configured = True
        else:
            raise AssertionError(f"unexpected setup stage {stage}")
        return f"{stage}-signature"

    def activate(guard: object) -> None:
        nonlocal activated
        assert guard is evidence
        activated = True

    keypairs = {
        "admin.json": admin,
        "backend.json": backend,
        "payer.json": fee_payer,
        "mint.json": mint,
    }
    monkeypatch.setattr(setup_command, "parse_args", lambda: args)
    monkeypatch.setattr(setup_command, "load_keypair", keypairs.__getitem__)
    monkeypatch.setattr(setup_command, "get_program_config_account", program_config)
    monkeypatch.setattr(
        setup_command,
        "_program_data_address",
        lambda *unused: _async_value(program_data),
    )
    monkeypatch.setattr(setup_command, "AsyncClient", Client)
    monkeypatch.setattr(setup_command, "_submit", submit)
    monkeypatch.setattr(setup_command, "activate_transaction_evidence_guard", activate)
    monkeypatch.setattr(
        setup_command.RehearsalSetupEvidenceManifest,
        "open",
        classmethod(open_evidence),
    )

    await setup_command.main()

    assert [stage for stage, _ in submitted] == [
        "mint_created",
        "atas_created",
        "supply_minted",
        "mint_authority_revoked",
        "configured",
    ]
    token_program = str(setup_command.TOKEN_PROGRAM_ID)
    assert token_program in dict(submitted)["mint_created"]
    assert token_program in dict(submitted)["supply_minted"]
    assert token_program in dict(submitted)["mint_authority_revoked"]
    assert snapshot["setup_rider_cal_ata"]["exists"] is True
    assert snapshot["setup_rider_cal_ata"]["decoded"]["amount_base_units"] == "0"
    assert finalized == [stage for stage, _ in submitted]
    assert captures == ["setup_ready"]

    submitted.clear()
    finalized.clear()
    await setup_command.main()

    assert submitted == []
    assert finalized == []
    assert captures == ["setup_ready", "setup_ready"]


def _account_with_fields(**fields: Any) -> dict[str, Any]:
    return {
        "exists": True,
        "decoded": {"account_type": "VaultStake", "fields": fields},
    }


def _vault_with_fields(**fields: Any) -> dict[str, Any]:
    return {
        "exists": True,
        "decoded": {"account_type": "Vault", "fields": fields},
    }


def _token_amount(
    amount: int,
    *,
    exists: bool = True,
    **decoded: Any,
) -> dict[str, Any]:
    return {
        "exists": exists,
        "decoded": ({"amount_base_units": str(amount), **decoded} if exists else None),
    }


def _mint_supply(supply: int, **decoded: Any) -> dict[str, Any]:
    return {
        "exists": True,
        "decoded": {"supply_base_units": str(supply), **decoded},
    }


def test_stake_reconciliation_accepts_new_escrow_and_refuses_wrong_delta() -> None:
    user = Keypair().pubkey()
    vault = Keypair().pubkey()
    stake = Keypair().pubkey()
    cal_mint = Keypair().pubkey()
    lp_mint = Keypair().pubkey()
    stake_cal = 100_000
    identity = {
        "user": str(user),
        "vault_id": 0,
        "expected_vault": str(vault),
        "cal_mint": str(cal_mint),
        "stake_cal": stake_cal,
        "settlement_week": 135,
    }
    previous = {
        "rehearsal_user_cal_ata": _token_amount(1_249_000),
        "rehearsal_cal_mint": _mint_supply(1_249_000),
        "rehearsal_cal_escrow": _token_amount(0, exists=False),
    }
    current = {
        "rehearsal_user_cal_ata": _token_amount(1_149_000),
        "rehearsal_cal_mint": _mint_supply(1_249_000),
        "rehearsal_cal_escrow": _token_amount(
            stake_cal,
            mint=str(cal_mint),
            token_owner=str(vault),
            state=1,
        ),
        "rehearsal_vault_stake": _account_with_fields(
            user=user,
            vault_id=0,
            cal_staked=stake_cal,
            lp_tokens=stake_cal,
            staked_at=1,
            pending_effective_week_plus_one=138,
            effective_lp_tokens=0,
            rewards_earned=0,
            pending_lp_tokens=stake_cal,
            bump=254,
        ),
        "rehearsal_vault_lp_mint": _mint_supply(stake_cal),
        "rehearsal_position_lp": _token_amount(
            stake_cal,
            mint=str(lp_mint),
            token_owner=str(stake),
            state=2,
        ),
    }

    result = wallet_smoke.RehearsalEvidenceManifest._validate_economic_reconciliation(
        "stake_cal",
        baseline=previous,
        previous=previous,
        current=current,
        identity=identity,
    )
    assert result["cal_staked"] == stake_cal
    assert result["lp_minted"] == stake_cal

    preexisting = {
        **previous,
        "rehearsal_cal_escrow": _token_amount(7),
    }
    with pytest.raises(RuntimeError, match="CAL stake transfer"):
        wallet_smoke.RehearsalEvidenceManifest._validate_economic_reconciliation(
            "stake_cal",
            baseline=preexisting,
            previous=preexisting,
            current=current,
            identity=identity,
        )


def test_stake_eligibility_reconciliation_matches_weekly_snapshot_layout() -> None:
    program_id = Keypair().pubkey()
    user = Keypair().pubkey()
    identity = {
        "program_id": str(program_id),
        "user": str(user),
        "vault_id": 0,
        "settlement_week": 42,
    }
    previous_fields = {
        "user": user,
        "vault_id": 0,
        "cal_staked": 100_000,
        "lp_tokens": 100_000,
        "staked_at": 123,
        "pending_effective_week_plus_one": 45,
        "effective_lp_tokens": 0,
        "rewards_earned": 0,
        "pending_lp_tokens": 100_000,
        "bump": 254,
    }
    current_fields = {
        **previous_fields,
        "pending_effective_week_plus_one": 0,
        "effective_lp_tokens": 100_000,
        "pending_lp_tokens": 0,
    }
    previous = {
        "rehearsal_vault_stake": _account_with_fields(**previous_fields),
        "rehearsal_expected_vault": _vault_with_fields(
            id=0, open_settlement_week=42
        ),
    }
    current = {
        "rehearsal_vault_stake": _account_with_fields(**current_fields),
        "rehearsal_expected_vault": _vault_with_fields(
            id=0, open_settlement_week=42
        ),
    }
    result = wallet_smoke.RehearsalEvidenceManifest._validate_economic_reconciliation(
        "override_stake_eligibility",
        baseline={},
        previous=previous,
        current=current,
        identity=identity,
    )
    assert result["effective_lp_tokens"] == 100_000

    for field, wrong_value in (
        ("user", Keypair().pubkey()),
        ("vault_id", 1),
        ("cal_staked", 99_999),
        ("lp_tokens", 99_999),
        ("effective_lp_tokens", 0),
        ("pending_lp_tokens", 1),
        ("pending_effective_week_plus_one", 43),
    ):
        wrong = {
            "rehearsal_vault_stake": _account_with_fields(
                **{**current_fields, field: wrong_value}
            ),
            "rehearsal_expected_vault": current["rehearsal_expected_vault"],
        }
        with pytest.raises(RuntimeError, match="VaultStake"):
            wallet_smoke.RehearsalEvidenceManifest._validate_economic_reconciliation(
                "override_stake_eligibility",
                baseline={},
                previous=previous,
                current=wrong,
                identity=identity,
            )

    wrong_week = {
        **current,
        "rehearsal_expected_vault": _vault_with_fields(
            id=0, open_settlement_week=41
        ),
    }
    with pytest.raises(RuntimeError, match="Settlement Week"):
        wallet_smoke.RehearsalEvidenceManifest._validate_economic_reconciliation(
            "override_stake_eligibility",
            baseline={},
            previous=previous,
            current=wrong_week,
            identity=identity,
        )


def test_stake_eligibility_transaction_binds_exact_frozen_week() -> None:
    program_id = Keypair().pubkey()
    identity = {
        "program_id": str(program_id),
        "settlement_week": 42,
    }
    discriminator = hashlib.sha256(
        b"global:admin_override_stake_eligibility"
    ).digest()[:8]

    def transaction(
        *,
        program: Pubkey = program_id,
        week: int = 42,
        data: bytes | None = None,
    ) -> dict[str, Any]:
        instruction_data = data or discriminator + week.to_bytes(8, "little")
        return {
            "signature": str(Signature.default()),
            "status": "finalized",
            "instruction_order": [
                {
                    "instruction_name": "admin_override_stake_eligibility",
                    "program_id": str(program),
                    "data_len": len(instruction_data),
                    "data_hex": instruction_data.hex(),
                    "data_sha256": hashlib.sha256(instruction_data).hexdigest(),
                    "discriminator_hex": instruction_data[:8].hex(),
                }
            ],
        }

    assert (
        wallet_smoke.RehearsalEvidenceManifest._validate_stake_eligibility_transaction(
            [transaction()], identity
        )
        == 42
    )

    for bad_transaction in (
        transaction(week=41),
        transaction(program=Keypair().pubkey()),
        transaction(data=discriminator),
        transaction(data=b"wrong_ix" + (42).to_bytes(8, "little")),
    ):
        with pytest.raises(RuntimeError, match="eligibility.*transaction"):
            wallet_smoke.RehearsalEvidenceManifest._validate_stake_eligibility_transaction(
                [bad_transaction], identity
            )


def test_gate_one_documents_runnable_receipt_backed_command() -> None:
    source = _source(REPO_ROOT / "docs" / "design" / "PROTOCOL_ALIGNMENT_FIX_PLAN.md")

    assert "blocked until `boulderroller-v2-29rm`" not in source
    assert "python3 backend/scripts/smoke_devnet_economics.py" in source
    assert "record_ride → credit_cal → record_climb_completion" not in source
    assert "`record_ride` → `credit_cal` → `record_climb_completion`" not in source

    for smoke_path in (SMOKE_PATH, WALLET_SMOKE_PATH):
        result = subprocess.run(
            [sys.executable, str(smoke_path), "--help"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        assert "--settlement-week" in result.stdout
        if smoke_path == WALLET_SMOKE_PATH:
            assert "--rehearsal-transport-state" in result.stdout
            assert "production Supabase is never used" in result.stdout
            assert "--rehearsal-evidence" in result.stdout
