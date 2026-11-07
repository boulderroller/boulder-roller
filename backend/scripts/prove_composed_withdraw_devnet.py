#!/usr/bin/env python3
"""Devnet proof: composed collect-before-unstake is ONE atomic transaction.

Drives the fresh devnet economics lane (same helpers as
``smoke_devnet_economics.py``) far enough to leave a real VaultStake carrying
both LP and unclaimed DUNG, then executes the production composed withdraw
exactly as the route does:

    TxBuilder.build_unstake_tx(..., collect_rewards=True)
    -> rider signs once -> submit_signed_transaction

and proves, from chain state, that a single transaction signature both
collected the pending DUNG (net of the ProgramConfig harvest fee) and burned
the full LP position. Protocol rule enforced by construction: a withdraw can
never forfeit pending DUNG (boulderroller-v2-71o2v).
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import importlib.util
import os
import sys
import time
from pathlib import Path

BACKEND_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(BACKEND_ROOT / ".env")
except ImportError:
    pass


def _load_smoke_module():
    spec = importlib.util.spec_from_file_location(
        "smoke_devnet_economics",
        BACKEND_ROOT / "scripts" / "smoke_devnet_economics.py",
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Prove composed collect+withdraw on the fresh devnet lane"
    )
    parser.add_argument(
        "--existing-vault-id",
        type=int,
        default=None,
        help="Resume an existing proof vault; requires --settlement-week",
    )
    parser.add_argument(
        "--settlement-week",
        type=int,
        default=None,
        help="Exact Settlement Week to resume with --existing-vault-id",
    )
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    smoke = _load_smoke_module()

    from solders.hash import Hash
    from solders.pubkey import Pubkey
    from solders.transaction import Transaction

    from app.solana_direct import (
        DirectConfig,
        _derive_ata,
        get_program_config_account,
        get_program_settlement_clock,
        get_vault_stake_account,
        send_distribute_epoch_rewards,
        send_stake_cal_in_vault,
    )
    from app.solana_env import (
        DEFAULT_BOULDER_ROLLERS_PROGRAM_ID,
        DEFAULT_CAL_MINT_ADDRESS,
        DEFAULT_DUNG_MINT_ADDRESS,
        DEFAULT_SOLANA_RPC_URL,
    )

    rpc_url = os.getenv("SOLANA_RPC_URL", DEFAULT_SOLANA_RPC_URL)
    program_id = Pubkey.from_string(DEFAULT_BOULDER_ROLLERS_PROGRAM_ID)
    cal_mint = Pubkey.from_string(DEFAULT_CAL_MINT_ADDRESS)
    dung_mint = Pubkey.from_string(DEFAULT_DUNG_MINT_ADDRESS)

    backend_authority = smoke.load_keypair(
        os.getenv(
            "BACKEND_AUTHORITY_KEYPAIR",
            str(Path.home() / ".config/solana/boulderroller-backend-authority.json"),
        )
    )
    fee_payer = smoke.load_keypair(
        os.getenv(
            "FEE_PAYER_KEYPAIR",
            str(Path.home() / ".config/solana/boulderroller-fee-payer.json"),
        )
    )
    staker = smoke.load_keypair(
        os.getenv("USER_KEYPAIR", str(Path.home() / ".config/solana/id.json"))
    )

    config = DirectConfig(
        rpc_url=rpc_url,
        program_id=program_id,
        payer=fee_payer,
        backend_authority=backend_authority,
        cal_mint_address=cal_mint,
        dung_mint_address=dung_mint,
    )
    settlement_clock = await get_program_settlement_clock(config)
    pol_ata, treasury_ata = await smoke.read_canonical_settlement_accounts(config)
    os.environ["PROTOCOL_TREASURY_ACCOUNT"] = str(treasury_ata)

    staker_cal_ata = _derive_ata(staker.pubkey(), cal_mint)
    staker_dung_ata = _derive_ata(staker.pubkey(), dung_mint)
    now = int(time.time())

    print("=== Composed Withdraw Devnet Proof ===")
    print(f"RPC:      {rpc_url}")
    print(f"Program:  {program_id}")
    print(f"Staker:   {staker.pubkey()}")

    stake_cal = 100_000 * smoke.LAMPORT_DECIMALS
    vault_alloc_cal = 1_000_000 * smoke.LAMPORT_DECIMALS

    if args.existing_vault_id is None:
        # Program 0x4E removed admin_create_vault. V4-B creates Vaults only
        # through the wallet-signed prepare/submit reservation flow.
        raise RuntimeError(
            "Fresh proof vaults need the prepare/submit reservation flow; "
            "create one there and pass --existing-vault-id with --settlement-week"
        )
    vault_id = args.existing_vault_id
    settlement_week = int(args.settlement_week)
    print(f"resuming vault {vault_id}, week {settlement_week}")
    print(
        "resume identity: "
        f"--existing-vault-id {vault_id} --settlement-week {settlement_week}"
    )

    vault_before = await smoke.read_vault_state(config, vault_id)
    signature_hash_hex = str(vault_before.get("signature_hash_hex") or "")
    if len(signature_hash_hex) != 64:
        raise RuntimeError("vault missing canonical signature_hash_hex")

    vault_state = await smoke.read_vault_state(config, vault_id)
    stake_state = await get_vault_stake_account(config, vault_id, str(staker.pubkey()))
    distributed = int(vault_state["open_settlement_week"]) > settlement_week
    stake_stage = smoke.inspect_smoke_stake_stage(
        vault_state, stake_state, stake_cal, distributed=distributed
    )

    if stake_stage == "pristine":
        cal_balance = await smoke.token_balance(rpc_url, staker_cal_ata)
        if cal_balance < stake_cal:
            await smoke.credit_user_cal(
                config=config,
                staker=staker.pubkey(),
                total_cal_amount=250_000 * smoke.LAMPORT_DECIMALS,
                activity_id=(
                    f"composed-withdraw-proof:cal-credit:{staker.pubkey()}:"
                    f"{vault_id}:{settlement_week}"
                ),
                completed_at=now,
            )
        stake_sig = await send_stake_cal_in_vault(
            config=config,
            staker_keypair=staker,
            vault_id=vault_id,
            amount=stake_cal,
        )
        print(f"staked CAL:      {stake_sig}")

    if distributed:
        flow_plan = await smoke.ensure_receipt_backed_smoke_flow(
            config=config,
            settlement_clock=settlement_clock,
            staker=staker.pubkey(),
            vault_id=vault_id,
            settlement_week=settlement_week,
            vault_signature_hash_hex=signature_hash_hex,
            cal_amount=vault_alloc_cal,
            completion_time_s=smoke.SMOKE_COMPLETION_TIME_S,
            current_time=int(time.time()),
            initial_cal_tribute=0,
        )
        print(f"completion flow: {flow_plan.stage}")

    if not distributed:
        await smoke.wait_for_smoke_open_week(config=config, vault_id=vault_id, settlement_week=settlement_week)
        flow_plan = await smoke.ensure_receipt_backed_smoke_flow(
            config=config,
            settlement_clock=settlement_clock,
            staker=staker.pubkey(),
            vault_id=vault_id,
            settlement_week=settlement_week,
            vault_signature_hash_hex=signature_hash_hex,
            cal_amount=vault_alloc_cal,
            completion_time_s=smoke.SMOKE_COMPLETION_TIME_S,
            current_time=int(time.time()),
            initial_cal_tribute=0,
        )
        print(f"completion flow: {flow_plan.stage}")

        await smoke.wait_for_smoke_finalization(config, settlement_week)
        transport_plan = await smoke.prepare_smoke_settlement_transport(
            config=config,
            vault_id=vault_id,
            settlement_week=settlement_week,
        )
        distribute_sig = await send_distribute_epoch_rewards(
            config=config,
            vault_id=vault_id,
            settlement_week=settlement_week,
            pol_account=str(pol_ata),
            protocol_treasury=str(treasury_ata),
            transport_plan=transport_plan,
        )
        print(f"week finalized:  {distribute_sig}")
        await asyncio.sleep(5)

    # ---- The composed withdraw itself ---------------------------------
    stake_state = await get_vault_stake_account(config, vault_id, str(staker.pubkey()))
    pending = int((stake_state or {}).get("rewards_earned", 0) or 0)
    lp_tokens = int((stake_state or {}).get("lp_tokens", 0) or 0)
    if pending <= 0 or lp_tokens <= 0:
        raise RuntimeError(
            f"proof needs live LP AND pending rewards; lp={lp_tokens} pending={pending}"
        )
    dung_before = await smoke.token_balance(rpc_url, staker_dung_ata)
    cal_before = await smoke.token_balance(rpc_url, staker_cal_ata)
    print(f"pre-state:       lp={lp_tokens} pending_dung={pending} dung={dung_before}")

    program_config = await get_program_config_account(config)
    harvest_fee_bps = int(program_config.get("harvest_fee_bps") or 500)
    expected_fee = pending * harvest_fee_bps // 10_000
    expected_net = pending - expected_fee

    from app.services.tx_builder import TxBuilder

    builder = TxBuilder(
        rpc_url=rpc_url,
        program_id=program_id,
        dung_mint=dung_mint,
        cal_mint=cal_mint,
        fee_payer=fee_payer,
        backend_authority=backend_authority,
        protocol_treasury=treasury_ata,
    )
    result = await builder.build_unstake_tx(
        user_wallet=str(staker.pubkey()),
        vault_id=vault_id,
        lp_amount=lp_tokens,
        collect_rewards=True,
    )
    print(f"composed msg:    {result.message}")

    tx = Transaction.from_bytes(base64.b64decode(result.transaction))
    tx.partial_sign([staker], Hash.from_string(result.blockhash))
    signed_b64 = base64.b64encode(bytes(tx)).decode("utf-8")
    tx_signature = await builder.submit_signed_transaction(
        signed_b64,
        last_valid_block_height=result.last_valid_block_height,
    )
    print(f"composed tx:     {tx_signature}")

    stake_after = await get_vault_stake_account(config, vault_id, str(staker.pubkey()))
    pending_after = int((stake_after or {}).get("rewards_earned", 0) or 0)
    lp_after = int((stake_after or {}).get("lp_tokens", 0) or 0)
    dung_after = await smoke.token_balance(rpc_url, staker_dung_ata)
    cal_after = await smoke.token_balance(rpc_url, staker_cal_ata)

    print("=== Post-state ===")
    print(f"rewards_earned:  {pending_after} (was {pending})")
    print(f"lp_tokens:       {lp_after} (was {lp_tokens})")
    print(f"DUNG delta:      {dung_after - dung_before} (expected net {expected_net})")
    print(f"CAL delta:       {cal_after - cal_before}")

    failures = []
    if pending_after != 0:
        failures.append(f"pending rewards not collected: {pending_after}")
    if lp_after != 0:
        failures.append(f"LP not fully withdrawn: {lp_after}")
    if dung_after - dung_before != expected_net:
        failures.append(
            f"DUNG delta {dung_after - dung_before} != expected net {expected_net}"
        )
    if cal_after <= cal_before:
        failures.append("CAL principal did not return to the staker")
    if failures:
        raise RuntimeError("; ".join(failures))

    print(
        "PROOF OK: one transaction "
        f"{tx_signature} collected {expected_net} DUNG base units "
        f"(fee {expected_fee}) AND withdrew {lp_tokens} LP base units."
    )


if __name__ == "__main__":
    asyncio.run(main())
