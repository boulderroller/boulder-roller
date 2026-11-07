#!/usr/bin/env python3
"""Create, fund, configure, and evidence an isolated six-decimal rehearsal USDC rail."""

from __future__ import annotations

import argparse
import asyncio
import os
import struct
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(SCRIPT_DIR.parent))

from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Finalized
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.system_program import CreateAccountParams, create_account
from spl.token.instructions import (
    InitializeMintParams,
    MintToParams,
    SetAuthorityParams,
    AuthorityType,
    create_associated_token_account,
    initialize_mint,
    mint_to,
    set_authority,
)

from app.services.solana_submit import activate_transaction_evidence_guard, submit_and_confirm
from app.solana_direct import (
    TOKEN_PROGRAM_ID,
    DirectConfig,
    _account_data_bytes,
    _derive_ata,
    get_program_config_account,
    make_configure_usdc_payment_ix,
)
from app.solana_env import DEFAULT_BOULDER_ROLLERS_PROGRAM_ID, DEFAULT_SOLANA_RPC_URL
from rehearsal_evidence import BPF_UPGRADEABLE_LOADER_ID, PROTECTED_TEST_USDC_MINT
from rehearsal_setup_evidence import (
    REHEARSAL_VAULT_CREATION_USDC,
    RehearsalSetupEvidenceManifest,
)
from smoke_devnet_economics import load_keypair


MINT_ACCOUNT_SIZE = 82
DEFAULT_INITIAL_USDC_SUPPLY = 10_000_000
DEFAULT_VAULT_CREATION_USDC = REHEARSAL_VAULT_CREATION_USDC


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Guarded operator setup for an isolated V4-B rehearsal USDC rail; "
            "requires an unused mint keypair, creates the exact rider's zero-balance "
            "CAL ATA, and writes a resumable evidence artifact."
        )
    )
    parser.add_argument("--rehearsal-lane", action="store_true", required=True)
    parser.add_argument("--rpc-url", default=DEFAULT_SOLANA_RPC_URL)
    parser.add_argument("--program-id", required=True)
    parser.add_argument("--admin-keypair", required=True)
    parser.add_argument("--backend-authority-keypair", required=True)
    parser.add_argument("--fee-payer-keypair", required=True)
    parser.add_argument(
        "--rider",
        required=True,
        help="Exact rehearsal rider; creates its zero CAL ATA and funded USDC ATA",
    )
    parser.add_argument("--usdc-mint-keypair", required=True)
    parser.add_argument(
        "--initial-usdc-supply",
        type=int,
        default=DEFAULT_INITIAL_USDC_SUPPLY,
        help="Exact six-decimal base-unit supply minted to the rehearsal rider",
    )
    parser.add_argument(
        "--vault-creation-usdc",
        type=int,
        default=DEFAULT_VAULT_CREATION_USDC,
    )
    parser.add_argument(
        "--rehearsal-setup-evidence",
        required=True,
        help="Absolute durable setup evidence path; parent must already exist",
    )
    return parser.parse_args()


def _validate_args(args: argparse.Namespace) -> None:
    if not args.rehearsal_lane:
        raise RuntimeError("setup requires explicit --rehearsal-lane")
    if args.program_id == str(DEFAULT_BOULDER_ROLLERS_PROGRAM_ID):
        raise RuntimeError("setup refuses the canonical Boulder Rollers program")
    evidence = Path(args.rehearsal_setup_evidence)
    if not evidence.is_absolute() or not evidence.parent.is_dir():
        raise RuntimeError("--rehearsal-setup-evidence requires an absolute path with existing parent")
    if args.vault_creation_usdc != DEFAULT_VAULT_CREATION_USDC:
        raise RuntimeError(
            "rehearsal Vault creation USDC cost must remain exactly "
            f"{DEFAULT_VAULT_CREATION_USDC} base units"
        )
    if args.initial_usdc_supply < args.vault_creation_usdc:
        raise RuntimeError("initial rehearsal supply must cover the Vault cost")


def _validate_program_config_usdc_state(
    program_config: dict[str, object],
    *,
    admin: Pubkey,
    usdc_mint: Pubkey,
    vault_creation_usdc: int,
) -> bool:
    """Accept only the frozen bootstrap rail or its exact configured successor."""
    if vault_creation_usdc != DEFAULT_VAULT_CREATION_USDC:
        raise RuntimeError(
            "requested rehearsal USDC cost is not the frozen bootstrap constant"
        )
    try:
        configured_mint = Pubkey.from_string(str(program_config.get("usdc_mint")))
        configured_treasury = Pubkey.from_string(
            str(program_config.get("usdc_treasury_token_account"))
        )
        configured_cost = int(program_config.get("vault_creation_usdc", 0))
    except (TypeError, ValueError) as exc:
        raise RuntimeError("ProgramConfig has malformed USDC setup state") from exc
    expected_treasury = _derive_ata(admin, usdc_mint)
    if configured_mint == Pubkey.default():
        if (
            configured_treasury != Pubkey.default()
            or configured_cost != DEFAULT_VAULT_CREATION_USDC
        ):
            raise RuntimeError("ProgramConfig has a foreign partial USDC setup state")
        return False
    if (
        configured_mint != usdc_mint
        or configured_treasury != expected_treasury
        or configured_cost != vault_creation_usdc
    ):
        raise RuntimeError("ProgramConfig already has a foreign USDC configuration")
    return True


async def _program_data_address(rpc_url: str, program_id: Pubkey) -> Pubkey:
    async with AsyncClient(rpc_url, commitment=Finalized) as client:
        response = await client.get_account_info(program_id, commitment=Finalized)
    account = response.value
    if (
        account is None
        or account.owner != BPF_UPGRADEABLE_LOADER_ID
        or not account.executable
    ):
        raise RuntimeError("rehearsal program is not executable upgradeable-loader state")
    data = _account_data_bytes(account.data)
    if len(data) < 36 or struct.unpack_from("<I", data, 0)[0] != 2:
        raise RuntimeError("rehearsal program loader state is not Program")
    return Pubkey.from_bytes(data[4:36])


async def _submit(
    *,
    rpc_url: str,
    instructions: list[object],
    signers: list[Keypair],
    fee_payer: Keypair,
    stage: str,
) -> str:
    result = await submit_and_confirm(
        instructions=instructions,
        signers=signers,
        fee_payer=fee_payer.pubkey(),
        tx_type=f"rehearsal_usdc_{stage}",
        reference_type="rehearsal_setup",
        reference_id=stage,
        wallet=str(fee_payer.pubkey()),
        commitment="finalized",
        rpc_url=rpc_url,
        skip_lifecycle=True,
    )
    if result.failed or not result.signature:
        raise RuntimeError(f"rehearsal USDC {stage} failed: {result.error}")
    return result.signature


async def main() -> None:
    args = parse_args()
    _validate_args(args)
    program_id = Pubkey.from_string(args.program_id)
    admin = load_keypair(args.admin_keypair)
    backend = load_keypair(args.backend_authority_keypair)
    fee_payer = load_keypair(args.fee_payer_keypair)
    rider = Pubkey.from_string(args.rider)
    usdc_mint = load_keypair(args.usdc_mint_keypair)
    if usdc_mint.pubkey() == PROTECTED_TEST_USDC_MINT:
        raise RuntimeError("setup refuses the protected test-USDC mint")

    config = DirectConfig(
        rpc_url=args.rpc_url,
        program_id=program_id,
        payer=fee_payer,
        backend_authority=backend,
    )
    program_config = await get_program_config_account(config)
    if not program_config or not program_config.get("initialized"):
        raise RuntimeError("rehearsal ProgramConfig is unavailable")
    if str(admin.pubkey()) != str(program_config.get("admin_authority")):
        raise RuntimeError("loaded admin signer does not match ProgramConfig")
    if str(backend.pubkey()) != str(program_config.get("backend_authority")):
        raise RuntimeError("loaded backend signer does not match ProgramConfig")
    try:
        cal_mint = Pubkey.from_string(str(program_config["cal_mint"]))
    except (KeyError, ValueError) as exc:
        raise RuntimeError("ProgramConfig has a malformed CAL mint identity") from exc
    if cal_mint == Pubkey.default():
        raise RuntimeError("ProgramConfig has no configured CAL mint")
    _validate_program_config_usdc_state(
        program_config,
        admin=admin.pubkey(),
        usdc_mint=usdc_mint.pubkey(),
        vault_creation_usdc=args.vault_creation_usdc,
    )

    program_data = await _program_data_address(args.rpc_url, program_id)
    evidence = await RehearsalSetupEvidenceManifest.open(
        path=Path(args.rehearsal_setup_evidence),
        rpc_url=args.rpc_url,
        program_id=program_id,
        program_data=program_data,
        admin=admin.pubkey(),
        backend_authority=backend.pubkey(),
        fee_payer=fee_payer.pubkey(),
        rider=rider,
        cal_mint=cal_mint,
        usdc_mint=usdc_mint.pubkey(),
        initial_usdc_supply=args.initial_usdc_supply,
        vault_creation_usdc=args.vault_creation_usdc,
    )
    evidence.claim_run_lock()
    activate_transaction_evidence_guard(evidence)
    await evidence.reconcile_prepared_transactions()
    await evidence.preflight_setup_progress()
    addresses = evidence._setup_addresses()
    setup = await evidence._read_accounts(args.rpc_url, addresses)
    _, snapshot = setup

    if not snapshot["setup_usdc_mint"]["exists"]:
        async with AsyncClient(args.rpc_url, commitment=Finalized) as client:
            rent = await client.get_minimum_balance_for_rent_exemption(MINT_ACCOUNT_SIZE)
        signature = await _submit(
            rpc_url=args.rpc_url,
            instructions=[
                create_account(
                    CreateAccountParams(
                        from_pubkey=fee_payer.pubkey(),
                        to_pubkey=usdc_mint.pubkey(),
                        lamports=int(rent.value),
                        space=MINT_ACCOUNT_SIZE,
                        owner=TOKEN_PROGRAM_ID,
                    )
                ),
                initialize_mint(
                    InitializeMintParams(
                        decimals=6,
                        program_id=TOKEN_PROGRAM_ID,
                        mint=usdc_mint.pubkey(),
                        mint_authority=admin.pubkey(),
                        freeze_authority=None,
                    )
                ),
            ],
            signers=[fee_payer, usdc_mint],
            fee_payer=fee_payer,
            stage="mint_created",
        )
        await evidence.finalize_setup_stage("mint_created", signature)

    await evidence.preflight_setup_progress()
    _, snapshot = await evidence._read_accounts(args.rpc_url, addresses)
    missing_atas = [
        label
        for label in (
            "setup_usdc_treasury",
            "setup_rider_usdc_ata",
            "setup_rider_cal_ata",
        )
        if not snapshot[label]["exists"]
    ]
    if missing_atas:
        instructions = []
        for label, owner, mint_address in (
            ("setup_usdc_treasury", admin.pubkey(), usdc_mint.pubkey()),
            ("setup_rider_usdc_ata", rider, usdc_mint.pubkey()),
            ("setup_rider_cal_ata", rider, cal_mint),
        ):
            if label in missing_atas:
                instructions.append(
                    create_associated_token_account(
                        fee_payer.pubkey(), owner, mint_address
                    )
                )
        signature = await _submit(
            rpc_url=args.rpc_url,
            instructions=instructions,
            signers=[fee_payer],
            fee_payer=fee_payer,
            stage="atas_created",
        )
        await evidence.finalize_setup_stage("atas_created", signature)

    await evidence.preflight_setup_progress()
    _, snapshot = await evidence._read_accounts(args.rpc_url, addresses)
    supply = int(
        (snapshot["setup_usdc_mint"].get("decoded") or {}).get(
            "supply_base_units", 0
        )
    )
    if supply == 0:
        signature = await _submit(
            rpc_url=args.rpc_url,
            instructions=[
                mint_to(
                    MintToParams(
                        program_id=TOKEN_PROGRAM_ID,
                        mint=usdc_mint.pubkey(),
                        dest=_derive_ata(rider, usdc_mint.pubkey()),
                        mint_authority=admin.pubkey(),
                        amount=args.initial_usdc_supply,
                        signers=[],
                    )
                )
            ],
            signers=[fee_payer, admin],
            fee_payer=fee_payer,
            stage="supply_minted",
        )
        await evidence.finalize_setup_stage("supply_minted", signature)
    elif supply != args.initial_usdc_supply:
        raise RuntimeError("rehearsal USDC supply is a foreign partial state")

    await evidence.preflight_setup_progress()
    _, snapshot = await evidence._read_accounts(args.rpc_url, addresses)
    mint_authority = (snapshot["setup_usdc_mint"].get("decoded") or {}).get(
        "mint_authority"
    )
    if mint_authority == str(admin.pubkey()):
        signature = await _submit(
            rpc_url=args.rpc_url,
            instructions=[
                set_authority(
                    SetAuthorityParams(
                        program_id=TOKEN_PROGRAM_ID,
                        account=usdc_mint.pubkey(),
                        authority=AuthorityType.MINT_TOKENS,
                        current_authority=admin.pubkey(),
                        signers=[],
                        new_authority=None,
                    )
                )
            ],
            signers=[fee_payer, admin],
            fee_payer=fee_payer,
            stage="mint_authority_revoked",
        )
        await evidence.finalize_setup_stage("mint_authority_revoked", signature)
    elif mint_authority is not None:
        raise RuntimeError("rehearsal USDC mint authority is a foreign partial state")

    await evidence.preflight_setup_progress()
    _, snapshot = await evidence._read_accounts(args.rpc_url, addresses)
    if (snapshot["setup_usdc_mint"].get("decoded") or {}).get(
        "mint_authority"
    ) is not None:
        raise RuntimeError("rehearsal USDC mint authority revocation did not finalize")

    program_config = await get_program_config_account(config)
    expected_treasury = _derive_ata(admin.pubkey(), usdc_mint.pubkey())
    if not _validate_program_config_usdc_state(
        program_config,
        admin=admin.pubkey(),
        usdc_mint=usdc_mint.pubkey(),
        vault_creation_usdc=args.vault_creation_usdc,
    ):
        signature = await _submit(
            rpc_url=args.rpc_url,
            instructions=[
                make_configure_usdc_payment_ix(
                    admin=admin.pubkey(),
                    usdc_mint=usdc_mint.pubkey(),
                    usdc_treasury_token_account=expected_treasury,
                    vault_creation_usdc=args.vault_creation_usdc,
                    program_id=program_id,
                )
            ],
            signers=[fee_payer, admin],
            fee_payer=fee_payer,
            stage="configured",
        )
        await evidence.finalize_setup_stage("configured", signature)

    await evidence.preflight_setup_progress()
    await evidence.capture_setup_stage("setup_ready")
    print(f"setup evidence: {evidence.path}")
    print(f"rehearsal USDC: {usdc_mint.pubkey()}")
    print(f"treasury: {expected_treasury}")
    print(f"rider USDC ATA: {_derive_ata(rider, usdc_mint.pubkey())}")
    print(f"rider CAL ATA: {_derive_ata(rider, cal_mint)}")


if __name__ == "__main__":
    asyncio.run(main())
