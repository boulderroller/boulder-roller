#!/usr/bin/env python3
"""
Wallet-signed devnet economics smoke test.

This proves the V4-B prepare/sign/submit flow with a real user signer:
1. Fund the synthetic rider through deterministic record_ride + credit_cal
2. Build, sign, and submit CAL+USDC creation for one registered Climb
3. Bind the run to one exact, already-finalizable Settlement Week
4. Record a receipt-backed completion and credit its CAL
5. Top up CAL only if the canonical completion did not cover the exact stake
6. Build, sign, and submit the exact stake if it is not already present
7. Finalize the bound Settlement Week
8. Collect DUNG and withdraw the exact LP atomically; recover only a legacy
   already-withdrawn prefix with a separate harvest
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import json
import os
import struct
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(SCRIPT_DIR.parent))

try:
    from dotenv import load_dotenv

    load_dotenv(SCRIPT_DIR.parent / ".env")
except ImportError:
    pass

from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.transaction import Transaction
from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Finalized

from app.services.solana_submit import activate_transaction_evidence_guard
from app.services.tx_builder import TxBuilder
from app.solana_direct import (
    DirectConfig,
    SPL_TOKEN_ACCOUNT_AMOUNT_OFFSET,
    SPL_TOKEN_ACCOUNT_LEN,
    SPL_TOKEN_ACCOUNT_STATE_OFFSET,
    TOKEN_PROGRAM_ID,
    _account_data_bytes,
    _derive_ata,
    _get_boulder_accounts_coder,
    get_program_config_account,
    get_program_settlement_clock,
    get_vault_stake_account,
)
from app.solana_env import (
    DEFAULT_BOULDER_ROLLERS_PROGRAM_ID,
    DEFAULT_CAL_MINT_ADDRESS,
    DEFAULT_DUNG_MINT_ADDRESS,
    DEFAULT_SOLANA_RPC_URL,
)
from smoke_devnet_economics import (
    wait_for_smoke_open_week,
    wait_for_smoke_finalization,
    LAMPORT_DECIMALS,
    SMOKE_COMPLETION_TIME_S,
    ensure_user_cal_credit,
    ensure_receipt_backed_smoke_flow,
    inspect_smoke_settlement_stage,
    inspect_smoke_stake_stage,
    load_keypair,
    measured_smoke_cal_tribute,
    prepare_smoke_settlement_transport,
    preflight_smoke_settlement_transport_prerequisites,
    read_canonical_settlement_accounts,
    read_vault_state,
    token_balance,
    validate_smoke_resume_args,
    send_distribute_epoch_rewards,
    smoke_completion_identity,
)
from rehearsal_evidence import (
    PROTECTED_SHAWMONT_CLIMB,
    PROTECTED_TEST_USDC_MINT,
    RehearsalEvidenceManifest,
)

REHEARSAL_VAULT_CREATION_USDC = 2_000_000
REHEARSAL_USDC_DECIMALS = 6
REHEARSAL_SETUP_SCHEMA = "boulderroller_v4b_rehearsal_setup_v1"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Smoke test wallet-signed devnet economics")
    parser.add_argument(
        "--backend-authority-keypair",
        default=os.getenv(
            "BACKEND_AUTHORITY_KEYPAIR",
            os.getenv(
                "SOLANA_BACKEND_AUTHORITY_PATH",
                str(Path.home() / ".config/solana/boulderroller-backend-authority.json"),
            ),
        ),
        help="Backend authority keypair path",
    )
    parser.add_argument(
        "--fee-payer-keypair",
        default=os.getenv(
            "FEE_PAYER_KEYPAIR",
            os.getenv(
                "SOLANA_PAYER_PATH",
                str(Path.home() / ".config/solana/boulderroller-fee-payer.json"),
            ),
        ),
        help="Sponsored fee payer keypair path",
    )
    parser.add_argument(
        "--user-keypair",
        default=os.getenv("USER_KEYPAIR", str(Path.home() / ".config/solana/id.json")),
        help="User signer keypair path",
    )
    parser.add_argument(
        "--user-cal",
        type=int,
        default=250_000 * LAMPORT_DECIMALS,
        help="CAL base units to credit to the user if the wallet is short",
    )
    parser.add_argument(
        "--stake-cal",
        type=int,
        default=100_000 * LAMPORT_DECIMALS,
        help="CAL base units to stake into the vault",
    )
    parser.add_argument(
        "--vault-alloc-cal",
        type=int,
        default=1_000_000 * LAMPORT_DECIMALS,
        help="CAL base units earned and tributed through a receipt-backed completion",
    )
    parser.add_argument(
        "--sleep-seconds",
        type=int,
        default=10,
        help="Seconds to wait between distribution and cleanup",
    )
    parser.add_argument(
        "--existing-vault-id",
        type=int,
        default=None,
        help="Resume an existing smoke vault; requires --settlement-week",
    )
    parser.add_argument(
        "--settlement-week",
        type=int,
        default=None,
        help="Exact smoke Settlement Week to resume with --existing-vault-id",
    )
    parser.add_argument(
        "--rpc-url",
        default=DEFAULT_SOLANA_RPC_URL,
        help="RPC URL for the fresh lane",
    )
    parser.add_argument(
        "--program-id",
        default=os.getenv("REHEARSAL_PROGRAM_ID"),
        help="Explicit non-registry rehearsal Boulder Rollers program ID",
    )
    parser.add_argument(
        "--cal-mint",
        default=os.getenv("REHEARSAL_CAL_MINT"),
        help="Explicit non-registry rehearsal CAL mint address",
    )
    parser.add_argument(
        "--dung-mint",
        default=os.getenv("REHEARSAL_DUNG_MINT"),
        help="Explicit non-registry rehearsal DUNG mint address",
    )
    parser.add_argument(
        "--rehearsal-lane",
        action="store_true",
        help=(
            "Require the explicit non-registry rehearsal program and mints for "
            "both fresh and resume modes"
        ),
    )
    parser.add_argument(
        "--rehearsal-transport-state",
        default=os.getenv("REHEARSAL_TRANSPORT_STATE"),
        help=(
            "Required absolute JSON path for the rehearsal-only durable ALT "
            "lifecycle. Its parent must exist; production Supabase is never used."
        ),
    )
    parser.add_argument(
        "--rehearsal-evidence",
        default=os.getenv("REHEARSAL_EVIDENCE_PATH"),
        help=(
            "Required absolute JSON path for atomic protected-account baselines, "
            "transaction signatures/slots, instruction order, and reconciliations."
        ),
    )
    parser.add_argument(
        "--rehearsal-setup-evidence",
        default=os.getenv("REHEARSAL_SETUP_EVIDENCE_PATH"),
        help=(
            "Required absolute guarded setup artifact freezing the isolated "
            "USDC mint, treasury, rider, signer roles, supply, and balances."
        ),
    )
    parser.add_argument(
        "--climb-pda",
        default=os.getenv("REHEARSAL_CLIMB_PDA"),
        help="Already-registered V4-B Climb PDA (required for a fresh Vault)",
    )
    parser.add_argument(
        "--climb-name",
        default=os.getenv("REHEARSAL_CLIMB_NAME", "Registered rehearsal climb"),
        help="Human-readable name for the registered rehearsal Climb",
    )
    return parser.parse_args()


class WalletRehearsalPreflight:
    def __init__(
        self,
        *,
        transport_database: object,
        usdc_mint: Pubkey | None = None,
        usdc_treasury: Pubkey | None = None,
        vault_creation_usdc: int = 0,
        vault_creation_cal: int = 0,
        harvest_fee_bps: int = 0,
        setup_evidence_sha256: str | None = None,
        initial_usdc_supply: int = 0,
        initial_rider_cal_balance: int = 0,
        initial_rider_usdc_balance: int = 0,
        initial_treasury_usdc_balance: int = 0,
    ) -> None:
        self.transport_database = transport_database
        self.usdc_mint = usdc_mint
        self.usdc_treasury = usdc_treasury
        self.vault_creation_usdc = vault_creation_usdc
        self.vault_creation_cal = vault_creation_cal
        self.harvest_fee_bps = harvest_fee_bps
        self.setup_evidence_sha256 = setup_evidence_sha256
        self.initial_usdc_supply = initial_usdc_supply
        self.initial_rider_cal_balance = initial_rider_cal_balance
        self.initial_rider_usdc_balance = initial_rider_usdc_balance
        self.initial_treasury_usdc_balance = initial_treasury_usdc_balance


def validate_wallet_rehearsal_args(args: argparse.Namespace) -> None:
    """Keep this command isolated from every registry/default deployment."""
    validate_smoke_resume_args(
        existing_vault_id=args.existing_vault_id,
        settlement_week=args.settlement_week,
    )
    if not args.rehearsal_lane:
        raise RuntimeError(
            "wallet economics smoke requires explicit --rehearsal-lane in fresh "
            "and --existing-vault-id resume modes"
        )

    identities = (
        ("program-id", args.program_id, DEFAULT_BOULDER_ROLLERS_PROGRAM_ID),
        ("cal-mint", args.cal_mint, DEFAULT_CAL_MINT_ADDRESS),
        ("dung-mint", args.dung_mint, DEFAULT_DUNG_MINT_ADDRESS),
    )
    for flag, value, registry_value in identities:
        if not str(value or "").strip():
            raise RuntimeError(f"--rehearsal-lane requires an explicit --{flag}")
        if str(value).strip() == str(registry_value):
            raise RuntimeError(
                f"--rehearsal-lane requires an explicit non-registry --{flag}"
            )

    for flag, value in (
        ("rehearsal-transport-state", args.rehearsal_transport_state),
        ("rehearsal-evidence", args.rehearsal_evidence),
        ("rehearsal-setup-evidence", args.rehearsal_setup_evidence),
    ):
        if not str(value or "").strip():
            raise RuntimeError(f"--rehearsal-lane requires --{flag} <absolute-path>")
        if not Path(str(value)).is_absolute():
            raise RuntimeError(f"--{flag} must be an absolute path")
    if Path(str(args.rehearsal_transport_state)).resolve() == Path(
        str(args.rehearsal_evidence)
    ).resolve():
        raise RuntimeError(
            "--rehearsal-transport-state and --rehearsal-evidence must be distinct"
        )
    evidence_paths = {
        Path(str(args.rehearsal_transport_state)).resolve(),
        Path(str(args.rehearsal_evidence)).resolve(),
        Path(str(args.rehearsal_setup_evidence)).resolve(),
    }
    if len(evidence_paths) != 3:
        raise RuntimeError("rehearsal transport, setup, and loop artifacts must be distinct")

    if args.existing_vault_id is None:
        if not str(args.climb_pda or "").strip():
            raise RuntimeError(
                "fresh V4-B wallet smoke requires an already-registered --climb-pda"
            )
        if str(args.climb_pda).strip() == str(PROTECTED_SHAWMONT_CLIMB):
            raise RuntimeError(
                "fresh V4-B wallet smoke requires a rehearsal-only Climb; the "
                "protected canonical Shawmont Climb is forbidden"
            )
        if args.user_cal <= 0:
            raise RuntimeError("--user-cal must be positive for V4-B Vault funding")


def _decode_rehearsal_token_account(
    account: object,
    *,
    expected_mint: Pubkey,
    expected_owner: Pubkey | None,
    label: str,
) -> int:
    if Pubkey.from_string(str(getattr(account, "owner"))) != TOKEN_PROGRAM_ID:
        raise RuntimeError(f"{label} is not owned by the SPL Token program")
    data = _account_data_bytes(getattr(account, "data"))
    if len(data) != SPL_TOKEN_ACCOUNT_LEN:
        raise RuntimeError(f"{label} has an invalid SPL token account layout")
    if Pubkey.from_bytes(data[0:32]) != expected_mint:
        raise RuntimeError(f"{label} does not use the configured mint")
    if expected_owner is not None and Pubkey.from_bytes(data[32:64]) != expected_owner:
        raise RuntimeError(f"{label} does not belong to the rehearsal rider")
    if data[SPL_TOKEN_ACCOUNT_STATE_OFFSET] not in (1, 2):
        raise RuntimeError(f"{label} is not initialized")
    return struct.unpack_from("<Q", data, SPL_TOKEN_ACCOUNT_AMOUNT_OFFSET)[0]


def _decode_rehearsal_usdc_mint(
    account: object,
    *,
    admin: Pubkey,
) -> dict[str, object]:
    if Pubkey.from_string(str(getattr(account, "owner"))) != TOKEN_PROGRAM_ID:
        raise RuntimeError("rehearsal USDC mint is not owned by the SPL Token program")
    data = _account_data_bytes(getattr(account, "data"))
    if len(data) != 82:
        raise RuntimeError("rehearsal USDC mint is not a classic SPL Mint")
    mint_authority = (
        Pubkey.from_bytes(data[4:36])
        if struct.unpack_from("<I", data, 0)[0] == 1
        else None
    )
    freeze_authority = (
        Pubkey.from_bytes(data[50:82])
        if struct.unpack_from("<I", data, 46)[0] == 1
        else None
    )
    if data[44] != REHEARSAL_USDC_DECIMALS:
        raise RuntimeError("rehearsal USDC mint must have exactly 6 decimals")
    if not bool(data[45]):
        raise RuntimeError("rehearsal USDC mint is not initialized")
    if mint_authority is not None:
        raise RuntimeError("rehearsal USDC mint authority was not revoked by setup")
    if freeze_authority is not None:
        raise RuntimeError("rehearsal USDC mint must have no freeze authority")
    return {
        "supply": struct.unpack_from("<Q", data, 36)[0],
        "mint_authority": str(mint_authority) if mint_authority is not None else None,
        "freeze_authority": None,
        "decimals": REHEARSAL_USDC_DECIMALS,
    }


def _load_rehearsal_setup_handoff(
    path: Path,
    *,
    program_id: Pubkey,
    user: Pubkey,
    backend_authority: Pubkey | None,
    fee_payer: Pubkey | None,
) -> tuple[dict[str, object], str]:
    if not path.is_absolute() or not path.is_file():
        raise RuntimeError("--rehearsal-setup-evidence must be an existing absolute file")
    raw = path.read_bytes()
    try:
        state = json.loads(raw)
    except Exception as exc:
        raise RuntimeError("rehearsal setup evidence is unreadable") from exc
    if not isinstance(state, dict) or state.get("schema") != REHEARSAL_SETUP_SCHEMA:
        raise RuntimeError("rehearsal setup evidence schema does not match")
    handoff = state.get("handoff") or {}
    if not isinstance(handoff, dict) or handoff.get("status") != "ready":
        raise RuntimeError("rehearsal setup evidence has no finalized ready handoff")
    if handoff.get("mint_authority_revoked") is not True:
        raise RuntimeError("rehearsal setup handoff does not prove mint-authority revocation")
    expected = {
        "program_id": str(program_id),
        "rider": str(user),
    }
    for field, value in expected.items():
        if handoff.get(field) != value:
            raise RuntimeError(f"rehearsal setup handoff {field} does not match")
    if backend_authority is not None and handoff.get("backend_authority") != str(
        backend_authority
    ):
        raise RuntimeError("loaded backend signer does not match setup evidence")
    if fee_payer is not None and handoff.get("fee_payer") != str(fee_payer):
        raise RuntimeError("loaded fee payer does not match setup evidence")
    if state.get("identity") != {
        key: handoff.get(key)
        for key in (
            "program_id",
            "program_data",
            "admin",
            "backend_authority",
            "fee_payer",
            "rider",
            "cal_mint",
            "rider_cal_ata",
            "usdc_mint",
            "usdc_treasury",
            "rider_usdc_ata",
            "initial_usdc_supply",
            "vault_creation_usdc",
        )
    }:
        raise RuntimeError("rehearsal setup handoff does not match its frozen identity")
    try:
        handoff_cal_mint = Pubkey.from_string(str(handoff["cal_mint"]))
        handoff_cal_ata = Pubkey.from_string(str(handoff["rider_cal_ata"]))
    except (KeyError, ValueError) as exc:
        raise RuntimeError("rehearsal setup CAL handoff identity is malformed") from exc
    if handoff_cal_ata != _derive_ata(user, handoff_cal_mint):
        raise RuntimeError("rehearsal setup rider CAL ATA is not canonical")
    if int(handoff.get("initial_rider_cal_balance", -1)) != 0:
        raise RuntimeError("rehearsal setup rider CAL ATA did not begin at zero")

    required_tx_stages = {
        "mint_created",
        "atas_created",
        "supply_minted",
        "mint_authority_revoked",
        "configured",
    }
    finalized_stages: set[str] = set()
    finalized_stage_order: list[str] = []
    protected = set((state.get("protected_addresses") or {}).values())
    for transaction in state.get("transactions") or ():
        metadata = transaction.get("metadata") or {}
        tx_type = str(metadata.get("tx_type") or "")
        prefix = "rehearsal_usdc_"
        account_set = set(transaction.get("account_set") or ())
        if account_set.intersection(protected):
            raise RuntimeError("rehearsal setup transaction overlaps protected accounts")
        if transaction.get("status") in {"expired", "failed"}:
            if not tx_type.startswith(prefix):
                raise RuntimeError("rehearsal setup terminal attempt is foreign")
            continue
        if tx_type.startswith(prefix):
            setup_stage = tx_type[len(prefix) :]
            finalized_stages.add(setup_stage)
            finalized_stage_order.append(setup_stage)
        if (
            transaction.get("status") != "finalized"
            or int(transaction.get("slot") or 0) <= 0
            or not transaction.get("signature")
            or not transaction.get("instruction_order")
        ):
            raise RuntimeError("rehearsal setup has incomplete transaction evidence")
    if not required_tx_stages.issubset(finalized_stages):
        missing = sorted(required_tx_stages - finalized_stages)
        raise RuntimeError(
            "rehearsal setup is missing finalized guarded stages: "
            + ", ".join(missing)
        )
    expected_stage_order = [
        "mint_created",
        "atas_created",
        "supply_minted",
        "mint_authority_revoked",
        "configured",
    ]
    if finalized_stage_order != expected_stage_order:
        raise RuntimeError("rehearsal setup guarded transaction order is invalid")
    reconciled = [
        str(item.get("stage")) for item in state.get("reconciliations") or ()
    ]
    if reconciled != [*expected_stage_order, "setup_ready"]:
        raise RuntimeError("rehearsal setup stage reconciliations are incomplete")
    baseline = state.get("baseline") or {}
    setup_baseline = baseline.get("setup") or {}
    if any(
        (setup_baseline.get(label) or {}).get("exists")
        for label in (
            "setup_usdc_mint",
            "setup_usdc_treasury",
            "setup_rider_usdc_ata",
            "setup_rider_cal_ata",
        )
    ):
        raise RuntimeError("rehearsal setup did not begin from an unused mint rail")
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
    if not required_protected.issubset(set((state.get("protected_addresses") or {}))):
        raise RuntimeError("rehearsal setup protected baseline is incomplete")
    return handoff, hashlib.sha256(raw).hexdigest()


async def preflight_wallet_rehearsal(
    *,
    config: DirectConfig,
    user: Pubkey,
    climb_pda: Pubkey | None,
    user_cal: int,
    transport_state_path: Path,
    setup_evidence_path: Path | None = None,
    backend_authority: Pubkey | None = None,
    fee_payer: Pubkey | None = None,
) -> WalletRehearsalPreflight:
    """Read every fresh-mode prerequisite before record/credit/create writes."""
    transport_database = (
        await preflight_smoke_settlement_transport_prerequisites(
            state_path=transport_state_path,
            program_id=config.program_id,
            authority=config.payer.pubkey(),
        )
    )
    program_config = await get_program_config_account(config)
    if not program_config or not program_config.get("initialized"):
        raise RuntimeError("rehearsal ProgramConfig is unavailable or uninitialized")
    if str(program_config.get("cal_mint")) != str(config.cal_mint_address):
        raise RuntimeError("rehearsal ProgramConfig CAL mint does not match --cal-mint")
    if str(program_config.get("dung_mint")) != str(config.dung_mint_address):
        raise RuntimeError("rehearsal ProgramConfig DUNG mint does not match --dung-mint")
    try:
        configured_admin = Pubkey.from_string(str(program_config["admin_authority"]))
        configured_backend = Pubkey.from_string(str(program_config["backend_authority"]))
    except (KeyError, ValueError) as exc:
        raise RuntimeError("rehearsal ProgramConfig signer roles are malformed") from exc
    if backend_authority is not None and configured_backend != backend_authority:
        raise RuntimeError("loaded backend signer does not match ProgramConfig")

    try:
        usdc_mint = Pubkey.from_string(str(program_config["usdc_mint"]))
        usdc_treasury = Pubkey.from_string(
            str(program_config["usdc_treasury_token_account"])
        )
        vault_creation_usdc = int(program_config["vault_creation_usdc"])
        vault_creation_cal = int(program_config["vault_creation_cal"])
        harvest_fee_bps = int(program_config["harvest_fee_bps"])
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError("rehearsal ProgramConfig creation costs are malformed") from exc
    if usdc_mint == Pubkey.default() or usdc_treasury == Pubkey.default():
        raise RuntimeError("rehearsal ProgramConfig USDC mint/treasury is not configured")
    if usdc_mint == PROTECTED_TEST_USDC_MINT:
        raise RuntimeError(
            "rehearsal ProgramConfig uses the protected test-USDC mint; configure "
            "a rehearsal-only USDC mint before running this command"
        )
    if vault_creation_usdc <= 0 or vault_creation_cal <= 0:
        raise RuntimeError("rehearsal ProgramConfig CAL/USDC creation cost is invalid")
    if vault_creation_usdc != REHEARSAL_VAULT_CREATION_USDC:
        raise RuntimeError(
            "rehearsal ProgramConfig Vault creation USDC cost must be exactly "
            f"{REHEARSAL_VAULT_CREATION_USDC} base units"
        )
    setup_handoff: dict[str, object] | None = None
    setup_sha256: str | None = None
    if setup_evidence_path is not None:
        setup_handoff, setup_sha256 = _load_rehearsal_setup_handoff(
            setup_evidence_path,
            program_id=config.program_id,
            user=user,
            backend_authority=backend_authority,
            fee_payer=fee_payer,
        )
        if setup_handoff.get("admin") != str(configured_admin):
            raise RuntimeError("setup admin does not match ProgramConfig admin authority")
        if setup_handoff.get("cal_mint") != str(config.cal_mint_address):
            raise RuntimeError("setup CAL mint does not match ProgramConfig")
        if setup_handoff.get("rider_cal_ata") != str(
            _derive_ata(user, config.cal_mint_address)
        ):
            raise RuntimeError("setup rider CAL ATA does not match rehearsal rider")
        if setup_handoff.get("usdc_mint") != str(usdc_mint) or setup_handoff.get(
            "usdc_treasury"
        ) != str(usdc_treasury):
            raise RuntimeError("setup USDC identities do not match ProgramConfig")
        if int(setup_handoff.get("vault_creation_usdc", -1)) != vault_creation_usdc:
            raise RuntimeError("setup Vault creation cost does not match ProgramConfig")
    if climb_pda is None:
        return WalletRehearsalPreflight(
            transport_database=transport_database,
            usdc_mint=usdc_mint,
            usdc_treasury=usdc_treasury,
            vault_creation_usdc=vault_creation_usdc,
            vault_creation_cal=vault_creation_cal,
            harvest_fee_bps=harvest_fee_bps,
            setup_evidence_sha256=setup_sha256,
            initial_usdc_supply=int(
                (setup_handoff or {}).get("initial_usdc_supply", 0)
            ),
            initial_rider_cal_balance=int(
                (setup_handoff or {}).get("initial_rider_cal_balance", 0)
            ),
            initial_rider_usdc_balance=int(
                (setup_handoff or {}).get("initial_rider_usdc_balance", 0)
            ),
            initial_treasury_usdc_balance=int(
                (setup_handoff or {}).get("initial_treasury_usdc_balance", 0)
            ),
        )

    user_cal_ata = _derive_ata(user, config.cal_mint_address)
    user_usdc_ata = _derive_ata(user, usdc_mint)
    addresses = (usdc_mint, user_cal_ata, user_usdc_ata, usdc_treasury, climb_pda)
    async with AsyncClient(config.rpc_url, commitment=Finalized) as client:
        response = await client.get_multiple_accounts(list(addresses))
    accounts = tuple(response.value)
    if len(accounts) != len(addresses):
        raise RuntimeError("rehearsal fresh-mode account preflight is incomplete")
    mint_account, cal_account, usdc_account, treasury_account, climb_account = accounts
    missing = [
        label
        for label, account in (
            (f"rider CAL ATA {user_cal_ata}", cal_account),
            (f"rehearsal USDC mint {usdc_mint}", mint_account),
            (f"rider USDC ATA {user_usdc_ata}", usdc_account),
            (f"USDC treasury {usdc_treasury}", treasury_account),
            (f"registered Climb {climb_pda}", climb_account),
        )
        if account is None
    ]
    if missing:
        raise RuntimeError(
            "rehearsal fresh-mode preflight is missing: " + ", ".join(missing)
        )
    cal_balance = _decode_rehearsal_token_account(
        cal_account,
        expected_mint=config.cal_mint_address,
        expected_owner=user,
        label=f"rider CAL ATA {user_cal_ata}",
    )
    usdc_balance = _decode_rehearsal_token_account(
        usdc_account,
        expected_mint=usdc_mint,
        expected_owner=user,
        label=f"rider USDC ATA {user_usdc_ata}",
    )
    treasury_balance = _decode_rehearsal_token_account(
        treasury_account,
        expected_mint=usdc_mint,
        expected_owner=configured_admin,
        label=f"USDC treasury {usdc_treasury}",
    )
    mint_state = _decode_rehearsal_usdc_mint(
        mint_account,
        admin=configured_admin,
    )
    if setup_handoff is not None:
        initial_supply = int(setup_handoff["initial_usdc_supply"])
        if int(mint_state["supply"]) != initial_supply:
            raise RuntimeError("rehearsal USDC mint initial supply does not match setup")
        if initial_supply != usdc_balance + treasury_balance:
            raise RuntimeError("rehearsal USDC supply is not fully reconciled")
    if Pubkey.from_string(str(getattr(climb_account, "owner"))) != config.program_id:
        raise RuntimeError("registered rehearsal Climb is not owned by --program-id")
    try:
        decoded_climb = _get_boulder_accounts_coder().parse(
            _account_data_bytes(getattr(climb_account, "data"))
        )
        if decoded_climb.name != "Climb":
            raise ValueError("account discriminator is not Climb")
        climb_fields = vars(decoded_climb.data)
        bound_vault = climb_fields.get("vault")
        successor = climb_fields.get(
            "successorClimb",
            climb_fields.get("successor_climb"),
        )
        continuity = climb_fields.get(
            "recordContinuityPolicy",
            climb_fields.get("record_continuity_policy"),
        )
    except Exception as exc:
        raise RuntimeError("registered rehearsal Climb failed exact decoding") from exc
    new_record_board = type(continuity).__name__ == "NewRecordBoard" or (
        isinstance(continuity, str)
        and continuity in {"NewRecordBoard", "new_record_board"}
    )
    if (
        bound_vault != Pubkey.default()
        or successor != Pubkey.default()
        or not new_record_board
    ):
        raise RuntimeError(
            "registered rehearsal Climb is stale, already bound, or not a new "
            "record board"
        )
    planned_initial_cal = int(
        (setup_handoff or {}).get("initial_rider_cal_balance", 0)
    )
    vault_creation_cal_base_units = vault_creation_cal * LAMPORT_DECIMALS
    if planned_initial_cal + user_cal < vault_creation_cal_base_units:
        raise RuntimeError(
            "planned rider CAL plus deterministic credit is below the configured "
            f"Vault creation cost {vault_creation_cal_base_units} base units"
        )
    planned_initial_usdc = int(
        (setup_handoff or {}).get("initial_rider_usdc_balance", usdc_balance)
    )
    if planned_initial_usdc < vault_creation_usdc:
        raise RuntimeError(
            f"planned rider USDC balance {planned_initial_usdc} is below configured "
            f"Vault creation cost {vault_creation_usdc}"
        )
    return WalletRehearsalPreflight(
        transport_database=transport_database,
        usdc_mint=usdc_mint,
        usdc_treasury=usdc_treasury,
        vault_creation_usdc=vault_creation_usdc,
        vault_creation_cal=vault_creation_cal,
        harvest_fee_bps=harvest_fee_bps,
        setup_evidence_sha256=setup_sha256,
        initial_usdc_supply=int(mint_state["supply"]),
        initial_rider_cal_balance=int(
            (setup_handoff or {}).get("initial_rider_cal_balance", cal_balance)
        ),
        initial_rider_usdc_balance=int(
            (setup_handoff or {}).get("initial_rider_usdc_balance", usdc_balance)
        ),
        initial_treasury_usdc_balance=int(
            (setup_handoff or {}).get(
                "initial_treasury_usdc_balance", treasury_balance
            )
        ),
    )


async def preflight_fresh_wallet_balances(
    *,
    config: DirectConfig,
    user: Pubkey,
    preflight: WalletRehearsalPreflight,
    evidence: RehearsalEvidenceManifest,
    deterministic_cal_credit: int,
) -> None:
    """Validate mutable pre-create balances against the recovered evidence cursor."""
    if preflight.usdc_mint is None or preflight.usdc_treasury is None:
        raise RuntimeError("rehearsal balance preflight has no frozen USDC identity")
    addresses = (
        _derive_ata(user, config.cal_mint_address),
        _derive_ata(user, preflight.usdc_mint),
        preflight.usdc_treasury,
    )
    async with AsyncClient(config.rpc_url, commitment=Finalized) as client:
        response = await client.get_multiple_accounts(
            list(addresses), commitment=Finalized
        )
    accounts = tuple(response.value)
    if len(accounts) != 3 or any(account is None for account in accounts):
        raise RuntimeError("rehearsal mutable balance preflight is incomplete")
    cal_balance = _decode_rehearsal_token_account(
        accounts[0],
        expected_mint=config.cal_mint_address,
        expected_owner=user,
        label=f"rider CAL ATA {addresses[0]}",
    )
    rider_usdc = _decode_rehearsal_token_account(
        accounts[1],
        expected_mint=preflight.usdc_mint,
        expected_owner=user,
        label=f"rider USDC ATA {addresses[1]}",
    )
    config_account = await get_program_config_account(config)
    if not config_account:
        raise RuntimeError("rehearsal ProgramConfig disappeared before balance preflight")
    try:
        admin = Pubkey.from_string(str(config_account["admin_authority"]))
    except (KeyError, ValueError) as exc:
        raise RuntimeError("rehearsal ProgramConfig admin is malformed") from exc
    treasury_usdc = _decode_rehearsal_token_account(
        accounts[2],
        expected_mint=preflight.usdc_mint,
        expected_owner=admin,
        label=f"USDC treasury {addresses[2]}",
    )
    expected_cal = (
        preflight.initial_rider_cal_balance + deterministic_cal_credit
        if evidence.has_reconciliation("vault_funding")
        else preflight.initial_rider_cal_balance
    )
    if cal_balance != expected_cal:
        raise RuntimeError(
            "rehearsal rider CAL balance does not match the recovered funding stage: "
            f"expected {expected_cal}, found {cal_balance}"
        )
    if (
        rider_usdc != preflight.initial_rider_usdc_balance
        or treasury_usdc != preflight.initial_treasury_usdc_balance
    ):
        raise RuntimeError(
            "rehearsal USDC balances changed before the evidenced Vault creation"
        )
    creation_cal = preflight.vault_creation_cal * LAMPORT_DECIMALS
    available_cal = cal_balance + (
        0 if evidence.has_reconciliation("vault_funding") else deterministic_cal_credit
    )
    if available_cal < creation_cal:
        raise RuntimeError(
            "rider CAL plus deterministic funding is below the configured Vault "
            f"creation cost {creation_cal} base units"
        )
    if rider_usdc < preflight.vault_creation_usdc:
        raise RuntimeError(
            f"rider USDC balance {rider_usdc} is below configured Vault creation "
            f"cost {preflight.vault_creation_usdc}"
        )


def sign_prepared_transaction(transaction_b64: str, signer: Keypair) -> str:
    tx = Transaction.from_bytes(base64.b64decode(transaction_b64))
    tx.partial_sign([signer], tx.message.recent_blockhash)
    if not tx.is_signed():
        raise RuntimeError("Prepared transaction is still missing signatures after user signing")
    return base64.b64encode(bytes(tx)).decode("utf-8")


def _state_value(fields: dict[str, object], *names: str) -> object:
    for name in names:
        if name in fields:
            return fields[name]
    return None


def _state_int(fields: dict[str, object], *names: str, default: int = 0) -> int:
    value = _state_value(fields, *names)
    return default if value is None else int(value)


def _require_pristine_created_vault(
    *,
    vault: dict[str, object],
    accounts: dict[str, dict[str, object]],
    rider: Pubkey,
    vault_id: int,
    climb: Pubkey,
    expected_vault: Pubkey,
) -> None:
    zero_vault_fields = (
        "cal_tribute_accumulated",
        "cal_tribute_accumulated_next",
        "total_cal_burned",
        "total_dung_emitted",
        "total_completions",
        "total_cal_staked",
        "staker_count",
        "pending_rewards",
        "pending_rewards_next_week",
        "carry_record_royalty",
        "carry_stakers",
        "carry_local_legend",
        "carry_pol",
        "carry_treasury",
        "total_staked",
        "last_distribution_epoch",
        "kom_time_s",
        "kom_set_epoch",
    )
    violations = [
        field for field in zero_vault_fields if int(vault.get(field, 0) or 0) != 0
    ]
    if (
        int(vault.get("id", -1)) != vault_id
        or str(vault.get("minter")) != str(rider)
        or str(vault.get("climb")) != str(climb)
        or vault.get("kom_holder") not in (None, str(Pubkey.default()))
        or violations
    ):
        raise RuntimeError(
            "resume Vault is not the pristine V4-B creation bound to this evidence"
        )

    def decoded(label: str, account_type: str) -> dict[str, object]:
        item = accounts.get(label) or {}
        value = item.get("decoded") or {}
        if not item.get("exists", True) or value.get("account_type") != account_type:
            raise RuntimeError(f"resume is missing exact {account_type} evidence")
        fields = value.get("fields") or {}
        if not isinstance(fields, dict):
            raise RuntimeError(f"resume {account_type} evidence is malformed")
        return fields

    activation = decoded("rehearsal_vault_activation", "VaultActivation")
    created_at = int(_state_value(activation, "created_at", "createdAt") or 0)
    expected_hash = hashlib.sha256(
        b"BR_VAULT_EMPTY_HISTORY_V2" + bytes(climb) + bytes(expected_vault)
    ).hexdigest()
    evidence_hash = _state_value(activation, "evidence_hash", "evidenceHash")
    if isinstance(evidence_hash, list):
        evidence_hash = bytes(evidence_hash).hex()
    if (
        _state_int(activation, "vault_id", "vaultId", default=-1) != vault_id
        or not bool(_state_value(activation, "is_active", "isActive"))
        or _state_int(
            activation, "seed_completions_written", "seedCompletionsWritten"
        )
        != 0
        or not bool(
            _state_value(activation, "leaderboard_seeded", "leaderboardSeeded")
        )
        or _state_int(activation, "seed_generation", "seedGeneration")
        != 2
        or _state_int(activation, "matched_users", "matchedUsers")
        != 0
        or _state_int(activation, "matched_completions", "matchedCompletions")
        != 0
        or _state_int(activation, "activated_at", "activatedAt")
        != created_at
        or _state_int(activation, "last_seed_at", "lastSeedAt")
        != created_at
        or _state_int(activation, "seed_cutoff_at", "seedCutoffAt")
        != created_at
        or str(evidence_hash) != expected_hash
    ):
        raise RuntimeError("resume VaultActivation is not exact automatic V4-B state")
    creation_week = int(vault["open_settlement_week"])
    if _state_int(
        activation, "economics_start_epoch", "economicsStartEpoch", default=-1
    ) != creation_week:
        raise RuntimeError("resume Vault activation week does not match creation week")

    board = decoded("rehearsal_record_board", "VaultLeaderboard")
    if (
        _state_int(board, "vault_id", "vaultId", default=-1) != vault_id
        or list(_state_value(board, "entries") or [])
        or _state_int(board, "last_updated", "lastUpdated") != 0
    ):
        raise RuntimeError("resume Record Board is not pristine")
    legend = decoded("rehearsal_local_legend", "LocalLegend")
    if (
        _state_int(legend, "vault_id", "vaultId", default=-1) != vault_id
        or str(_state_value(legend, "holder")) != str(rider)
        or int(
            _state_value(
                legend, "completions_at_election", "completionsAtElection"
            )
            or 0
        )
        != 0
        or str(_state_value(legend, "runner_up", "runnerUp"))
        != str(Pubkey.default())
        or int(
            _state_value(legend, "runner_up_completions", "runnerUpCompletions")
            or 0
        )
        != 0
        or int(_state_value(legend, "total_earned", "totalEarned") or 0) != 0
        or not bool(_state_value(legend, "is_active", "isActive"))
        or not bool(_state_value(legend, "is_bootstrap", "isBootstrap"))
    ):
        raise RuntimeError("resume Local Legend is not the pristine bootstrap seat")


async def ensure_resume_created_vault(
    *, config: DirectConfig, evidence: RehearsalEvidenceManifest,
    rider: Pubkey, vault_id: int, settlement_week: int,
) -> None:
    """Compatibility name: validate the ordinary created Vault; never rewind it."""
    if not evidence.has_finalized_instruction("create_vault_with_usdc"):
        raise RuntimeError("resume evidence has no finalized create_vault_with_usdc transaction")
    vault = await read_vault_state(config, vault_id)
    if not vault or int(vault["open_settlement_week"]) > settlement_week + 1:
        raise RuntimeError("resume Vault is outside the frozen settlement flow")
    if not evidence.has_reconciliation("create_vault_with_usdc"):
        await evidence.finalize_stage("create_vault_with_usdc")


async def main() -> None:
    args = parse_args()
    validate_wallet_rehearsal_args(args)

    rpc_url = args.rpc_url
    program_id = Pubkey.from_string(args.program_id)
    cal_mint = Pubkey.from_string(args.cal_mint)
    dung_mint = Pubkey.from_string(args.dung_mint)

    backend_authority = load_keypair(args.backend_authority_keypair)
    fee_payer = load_keypair(args.fee_payer_keypair)
    user = load_keypair(args.user_keypair)

    admin_config = DirectConfig(
        rpc_url=rpc_url,
        program_id=program_id,
        payer=fee_payer,
        backend_authority=backend_authority,
        cal_mint_address=cal_mint,
        dung_mint_address=dung_mint,
    )
    climb_pda = (
        Pubkey.from_string(str(args.climb_pda).strip())
        if args.existing_vault_id is None
        else None
    )
    rehearsal_preflight = await preflight_wallet_rehearsal(
        config=admin_config,
        user=user.pubkey(),
        climb_pda=climb_pda,
        user_cal=args.user_cal,
        transport_state_path=Path(args.rehearsal_transport_state),
        setup_evidence_path=Path(args.rehearsal_setup_evidence),
        backend_authority=backend_authority.pubkey(),
        fee_payer=fee_payer.pubkey(),
    )
    transport_database = getattr(
        rehearsal_preflight,
        "transport_database",
        rehearsal_preflight,
    )
    if rehearsal_preflight.usdc_mint is None or rehearsal_preflight.usdc_treasury is None:
        raise RuntimeError("rehearsal preflight did not return frozen USDC identities")
    evidence = await RehearsalEvidenceManifest.open(
        path=Path(args.rehearsal_evidence),
        rpc_url=rpc_url,
        program_id=program_id,
        cal_mint=cal_mint,
        dung_mint=dung_mint,
        user=user.pubkey(),
        climb_pda=climb_pda,
        existing_vault_id=args.existing_vault_id,
        settlement_week=args.settlement_week,
        usdc_mint=rehearsal_preflight.usdc_mint,
        usdc_treasury=rehearsal_preflight.usdc_treasury,
        transport_state_path=Path(args.rehearsal_transport_state),
        vault_creation_cal=rehearsal_preflight.vault_creation_cal,
        vault_creation_usdc=rehearsal_preflight.vault_creation_usdc,
        harvest_fee_bps=rehearsal_preflight.harvest_fee_bps,
        user_cal=args.user_cal,
        stake_cal=args.stake_cal,
        vault_alloc_cal=args.vault_alloc_cal,
        setup_evidence_path=Path(args.rehearsal_setup_evidence),
        setup_evidence_sha256=rehearsal_preflight.setup_evidence_sha256,
        initial_usdc_supply=rehearsal_preflight.initial_usdc_supply,
    )
    if args.existing_vault_id is None and evidence.vault_id < 0:
        raise RuntimeError("rehearsal evidence returned a negative Vault ID")
    evidence.claim_run_lock()
    activate_transaction_evidence_guard(evidence)
    await evidence.reconcile_prepared_transactions()
    settlement_clock = await get_program_settlement_clock(admin_config)
    pol_ata, treasury_ata = await read_canonical_settlement_accounts(admin_config)

    builder = TxBuilder(
        rpc_url=rpc_url,
        program_id=program_id,
        cal_mint=cal_mint,
        dung_mint=dung_mint,
        fee_payer=fee_payer,
        backend_authority=backend_authority,
        protocol_treasury=treasury_ata,
    )

    user_cal_ata = _derive_ata(user.pubkey(), cal_mint)
    user_dung_ata = _derive_ata(user.pubkey(), dung_mint)

    print("=== Wallet-Signed Devnet Economics Smoke ===")
    print(f"RPC:               {rpc_url}")
    print(f"Program:           {program_id}")
    print(f"Backend authority: {backend_authority.pubkey()}")
    print(f"Fee payer:         {fee_payer.pubkey()}")
    print(f"User signer:       {user.pubkey()}")
    print(f"CAL ATA:           {user_cal_ata}")
    print(f"DUNG ATA:          {user_dung_ata}")

    now = int(time.time())
    settlement_week = (
        settlement_clock.week_at(now) + 1
        if args.existing_vault_id is None
        else int(args.settlement_week)
    )
    evidence.set_settlement_week(settlement_week)
    funding_activity_id: str | None = None
    if args.existing_vault_id is None:
        funding_activity_id = (
            "smoke-wallet-economics:v4b-vault-funding:"
            f"{program_id}:{user.pubkey()}:{climb_pda}:{args.user_cal}"
        )
        evidence.register_cal_credit_evidence(
            label="vault_funding",
            activity_id=funding_activity_id,
        )
    completion_completed_at = settlement_clock.week_start(settlement_week) + 86_400
    _, completion_ride_hash = smoke_completion_identity(
        user.pubkey(),
        evidence.vault_id,
        args.vault_alloc_cal,
        SMOKE_COMPLETION_TIME_S,
        completion_completed_at,
    )
    evidence.register_completion_evidence(ride_hash=completion_ride_hash)
    top_up_activity_id = (
        f"smoke-wallet-economics:cal-credit:{user.pubkey()}:"
        f"{evidence.vault_id}:{settlement_week}:{args.user_cal}"
    )
    evidence.register_cal_credit_evidence(
        label="stake_cal_top_up",
        activity_id=top_up_activity_id,
    )
    await evidence.recover_one_loop_stage()
    if args.existing_vault_id is None:
        await preflight_fresh_wallet_balances(
            config=admin_config,
            user=user.pubkey(),
            preflight=rehearsal_preflight,
            evidence=evidence,
            deterministic_cal_credit=args.user_cal,
        )
        climb_pda_str = str(climb_pda)
        climb_name = str(args.climb_name).strip() or "Registered rehearsal climb"
        assert funding_activity_id is not None
        funding_sig = await ensure_user_cal_credit(
            config=admin_config,
            staker=user.pubkey(),
            total_cal_amount=args.user_cal,
            activity_id=funding_activity_id,
            completed_at=now - 60,
        )
        if not evidence.has_reconciliation("vault_funding"):
            await evidence.finalize_stage("vault_funding", funding_sig)
        prepared_create = await builder.build_create_vault_with_usdc_tx(
            user_wallet=str(user.pubkey()),
            climb_pda=climb_pda_str,
            display_name=climb_name,
            vault_id=evidence.vault_id,
        )
        if prepared_create.vault_id is None:
            raise RuntimeError("Prepared create transaction did not return a vault_id")
        vault_id = int(prepared_create.vault_id)
        if vault_id < 0:
            raise RuntimeError("Prepared create transaction returned a negative vault_id")
        if vault_id != evidence.vault_id:
            raise RuntimeError(
                "Prepared create Vault ID does not match the frozen evidence identity"
            )
        print(
            "create recovery:     "
            f"--existing-vault-id {vault_id} --settlement-week {settlement_week}"
        )
        create_sig = await builder.submit_signed_transaction(
            sign_prepared_transaction(prepared_create.transaction, user),
            last_valid_block_height=prepared_create.last_valid_block_height,
        )
        await evidence.finalize_stage("create_vault_with_usdc", create_sig)

        print(f"prepared vault id:  {vault_id}")
        print(f"registered climb:   {climb_pda_str} ({climb_name})")
        print(f"vault funding CAL:  {funding_sig}")
        print(f"wallet create tx:   {create_sig}")

    else:
        vault_id = args.existing_vault_id
        print(f"using existing vault: {vault_id}")
        await ensure_resume_created_vault(
            config=admin_config,
            evidence=evidence,
            rider=user.pubkey(),
            vault_id=vault_id,
            settlement_week=settlement_week,
        )

    print(
        "resume identity:    "
        f"--existing-vault-id {vault_id} --settlement-week {settlement_week}"
    )

    vault_before = await read_vault_state(admin_config, vault_id)
    vault_signature_hash_hex = str(vault_before.get("signature_hash_hex") or "")
    if len(vault_signature_hash_hex) != 64:
        raise RuntimeError(
            f"Vault {vault_id} missing canonical signature_hash_hex for evidence hash"
        )
    vault_state = await read_vault_state(admin_config, vault_id)
    stake_state = await get_vault_stake_account(
        admin_config, vault_id, str(user.pubkey())
    )
    distributed = int(vault_state["open_settlement_week"]) > settlement_week
    stake_stage = inspect_smoke_stake_stage(
        vault_state,
        stake_state,
        args.stake_cal,
        distributed=distributed,
    )

    if stake_stage == "pristine":
        cal_balance = await token_balance(rpc_url, user_cal_ata)
        if cal_balance < args.stake_cal:
            print(
                f"user CAL balance {cal_balance} is short; "
                f"crediting deterministic {args.user_cal} CAL top-up"
            )
            top_up_sig = await ensure_user_cal_credit(
                config=admin_config,
                staker=user.pubkey(),
                total_cal_amount=args.user_cal,
                activity_id=top_up_activity_id,
                completed_at=now,
            )
            await evidence.finalize_stage("stake_cal_top_up", top_up_sig)
            cal_balance = await token_balance(rpc_url, user_cal_ata)
        if cal_balance < args.stake_cal:
            raise RuntimeError(
                f"user CAL balance {cal_balance} remains below stake {args.stake_cal}"
            )

        prepared_stake = await builder.build_stake_tx(
            user_wallet=str(user.pubkey()),
            vault_id=vault_id,
            amount=args.stake_cal,
        )
        stake_sig = await builder.submit_signed_transaction(
            sign_prepared_transaction(prepared_stake.transaction, user),
            last_valid_block_height=prepared_stake.last_valid_block_height,
        )
        await evidence.finalize_stage("stake_cal", stake_sig)
        print(f"wallet stake tx:    {stake_sig}")
        vault_state = await read_vault_state(admin_config, vault_id)
        stake_state = await get_vault_stake_account(
            admin_config, vault_id, str(user.pubkey())
        )
        stake_stage = inspect_smoke_stake_stage(
            vault_state,
            stake_state,
            args.stake_cal,
            distributed=False,
        )
    elif stake_stage == "staked":
        print("stake state:        exact smoke position already present")

    if distributed:
        flow_plan = await ensure_receipt_backed_smoke_flow(
            config=admin_config,
            settlement_clock=settlement_clock,
            staker=user.pubkey(),
            vault_id=vault_id,
            settlement_week=settlement_week,
            vault_signature_hash_hex=vault_signature_hash_hex,
            cal_amount=args.vault_alloc_cal,
            completion_time_s=SMOKE_COMPLETION_TIME_S,
            current_time=int(time.time()),
        )
        await evidence.finalize_stage("receipt_backed_completion")
        print(
            f"completion flow:    {flow_plan.stage} "
            f"pending={flow_plan.expected_pending_rewards} "
            f"remainder={flow_plan.expected_cal_remainder}"
        )

    if not distributed:
        if stake_stage != "staked":
            raise RuntimeError("smoke flow cannot distribute without the exact stake")
        await wait_for_smoke_open_week(config=admin_config, vault_id=vault_id, settlement_week=settlement_week)
        await evidence.finalize_stage("ordinary_week_open")
        flow_plan = await ensure_receipt_backed_smoke_flow(
            config=admin_config,
            settlement_clock=settlement_clock,
            staker=user.pubkey(),
            vault_id=vault_id,
            settlement_week=settlement_week,
            vault_signature_hash_hex=vault_signature_hash_hex,
            cal_amount=args.vault_alloc_cal,
            completion_time_s=SMOKE_COMPLETION_TIME_S,
            current_time=int(time.time()),
        )
        await evidence.finalize_stage("receipt_backed_completion")
        print(
            f"completion flow:    {flow_plan.stage} "
            f"pending={flow_plan.expected_pending_rewards} "
            f"remainder={flow_plan.expected_cal_remainder}"
        )

        await wait_for_smoke_finalization(admin_config, settlement_week)
        transport_plan = await prepare_smoke_settlement_transport(
            config=admin_config,
            vault_id=vault_id,
            settlement_week=settlement_week,
            database=transport_database,
            on_plan=evidence.register_settlement_transport_plan,
        )
        evidence.confirm_settlement_transport_ready(transport_plan)
        if not evidence.has_reconciliation("settlement_transport_ready"):
            await evidence.finalize_stage("settlement_transport_ready")
        print(
            "settlement v0:      "
            f"{transport_plan['planned_serialized_bytes']} bytes via "
            f"{transport_plan['lookup_table_address']}"
        )

        distribute_sig = await send_distribute_epoch_rewards(
            config=admin_config,
            vault_id=vault_id,
            settlement_week=settlement_week,
            pol_account=str(pol_ata),
            protocol_treasury=str(treasury_ata),
            transport_plan=transport_plan,
        )
        await evidence.finalize_stage("distribute_epoch_rewards", distribute_sig)
        print(f"epoch distributed:  {distribute_sig}")

        print(f"sleeping {args.sleep_seconds}s before cleanup...")
        await asyncio.sleep(args.sleep_seconds)
    else:
        print(f"epoch state:        Settlement Week {settlement_week} already distributed")

    vault_state = await read_vault_state(admin_config, vault_id)
    distributed_plan = inspect_smoke_settlement_stage(
        vault_state,
        settlement_clock,
        settlement_week,
        int(time.time()),
        measured_smoke_cal_tribute(
            args.vault_alloc_cal,
            SMOKE_COMPLETION_TIME_S,
        ),
    )
    if distributed_plan.stage != "distributed":
        raise RuntimeError("distribution transaction did not advance the exact smoke flow")
    stake_state = await get_vault_stake_account(
        admin_config, vault_id, str(user.pubkey())
    )
    stake_stage = inspect_smoke_stake_stage(
        vault_state,
        stake_state,
        args.stake_cal,
        distributed=True,
    )

    if stake_stage == "staked":
        lp_tokens = int((stake_state or {}).get("lp_tokens", 0) or 0)
        if lp_tokens <= 0:
            raise RuntimeError("exact smoke stake disappeared before unstake")
        prepared_unstake = await builder.build_unstake_tx(
            user_wallet=str(user.pubkey()),
            vault_id=vault_id,
            lp_amount=lp_tokens,
            collect_rewards=True,
        )
        unstake_sig = await builder.submit_signed_transaction(
            sign_prepared_transaction(prepared_unstake.transaction, user),
            last_valid_block_height=prepared_unstake.last_valid_block_height,
        )
        await evidence.finalize_stage("collect_then_unstake", unstake_sig)
        print(f"wallet unstake tx:  {unstake_sig} (exact LP={lp_tokens})")

        vault_state = await read_vault_state(admin_config, vault_id)
        stake_state = await get_vault_stake_account(
            admin_config, vault_id, str(user.pubkey())
        )
        stake_stage = inspect_smoke_stake_stage(
            vault_state,
            stake_state,
            args.stake_cal,
            distributed=True,
        )
        if stake_stage != "complete":
            raise RuntimeError(
                "atomic smoke cleanup did not collect rewards and withdraw LP"
            )

    if stake_stage == "withdrawn":
        prepared_harvest = await builder.build_harvest_tx(
            user_wallet=str(user.pubkey()),
            vault_id=vault_id,
        )
        harvest_sig = await builder.submit_signed_transaction(
            sign_prepared_transaction(prepared_harvest.transaction, user),
            last_valid_block_height=prepared_harvest.last_valid_block_height,
        )
        await evidence.finalize_stage("legacy_withdrawn_harvest", harvest_sig)
        print(f"wallet harvest tx:  {harvest_sig}")

        final_vault_state = await read_vault_state(admin_config, vault_id)
        final_stake_state = await get_vault_stake_account(
            admin_config, vault_id, str(user.pubkey())
        )
        stake_stage = inspect_smoke_stake_stage(
            final_vault_state,
            final_stake_state,
            args.stake_cal,
            distributed=True,
        )
    if stake_stage != "complete":
        raise RuntimeError("smoke cleanup did not reach the durable complete state")
    await evidence.finalize_stage("economic_loop_complete")
    print("stake state:        fully withdrawn and harvested")

    print("=== Final Balances ===")
    print(f"user CAL balance:   {await token_balance(rpc_url, user_cal_ata)}")
    print(f"user DUNG balance:  {await token_balance(rpc_url, user_dung_ata)}")
    print(f"POL DUNG balance:   {await token_balance(rpc_url, pol_ata)}")
    print(f"treasury balance:   {await token_balance(rpc_url, treasury_ata)}")


if __name__ == "__main__":
    asyncio.run(main())
