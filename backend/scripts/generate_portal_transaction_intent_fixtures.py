#!/usr/bin/env python3
"""Generate deterministic legacy transactions for the portal intent firewall."""

from __future__ import annotations

import base64
import hashlib
import json
import sys
from uuid import UUID

from solders.hash import Hash
from solders.message import Message
from solders.pubkey import Pubkey
from solders.transaction import Transaction

from app.solana_direct import (
    _derive_ata,
    _derive_local_legend_pda,
    _derive_rider_balance_token_pda,
    _derive_vault_activation_pda,
    _derive_vault_counter_pda,
    _derive_vault_leaderboard_pda,
    _derive_vault_pda,
    make_collect_stake_rewards_for_ix,
    make_create_ata_ix,
    make_create_vault_ix,
    make_create_vault_with_usdc_ix,
    make_initialize_vault_cal_escrow_ix,
    make_initialize_vault_lp_mint_ix,
    make_initialize_vault_position_lp_ix,
    make_spl_transfer_checked_ix,
    make_stake_cal_in_vault_ix,
    make_unstake_cal_from_vault_ix,
    make_withdraw_to_wallet_ix,
)


def _key(value: str) -> Pubkey:
    return Pubkey.from_string(value)


PROGRAM = _key("EVjP2Vdz9buHNphywPhoybf213poa8EiSW6FGbXWFqYH")
FEE_PAYER = _key("9h6UJdZqUPNnShaUHkSoxvEeZ7gBeNxzXGQcShhBnzEP")
BACKEND_AUTHORITY = _key("CJz8PUyNVvLuXJvjsYXgSKD9utZVP2XoTEZq6M973Gha")
WALLET = _key("GmaDrppBC7P5ARKV8g3djiwP89vz1jLK23V2GBjuAEGB")
CAL_MINT = _key("4bxTCxEQp993cXs5nqhfWthRCPSTDv5K6PMgsfunEaJh")
DUNG_MINT = _key("CqDFJWLpr49tB8xjHegy5JR5jwMCfmhicjuWawtKLeCk")
USDC_MINT = _key("DpLPBaRuLnBsR3P3meU1tmiNUxreXwskXBebTYKvNGne")
DUNG_TREASURY = _key("9wkFkPSH9eL1XdifxzM7ASfqyVtSZWAuLGUXTx5ijwPr")
USDC_TREASURY = _key("GEL1JhavEKPuqVBvUiezUgNG2VYK1jtzsUazo2Scm1jA")

VAULT_ID = 42
STAKE_AMOUNT = 123_000_000_000
UNSTAKE_AMOUNT = 456_789
BALANCE_AMOUNT = 987_654_321
BLOCKHASH = Hash.default()
LAST_VALID_BLOCK_HEIGHT = 123_456
CLIMB_ID = "11111111-1111-1111-1111-111111111111"
CANON_ID = "22222222-2222-2222-2222-222222222222"
CANON_VERSION = 2
PROFILE_HASH = bytes.fromhex(
    "a8f2861cb321b0dcded9c3ea0ddabb26ec8d5f7d33a771923c763fdd27de1b23"
)
COMMITMENT = (
    b"\x01"
    + UUID(CANON_ID).bytes
    + CANON_VERSION.to_bytes(2, "big")
    + bytes(13)
    + PROFILE_HASH
)
COMMITMENT_HASH = hashlib.sha256(COMMITMENT).digest()
CLIMB_PDA, _ = Pubkey.find_program_address([b"climb", COMMITMENT_HASH], PROGRAM)


def build_records() -> list[dict[str, object]]:
    records: list[dict[str, object]] = []

    def emit(
        name: str,
        instructions: list,
        intent: dict[str, object],
        message: str,
        **prepared: object,
    ) -> None:
        compiled = Message.new_with_blockhash(instructions, FEE_PAYER, BLOCKHASH)
        transaction = Transaction.new_unsigned(compiled)
        records.append(
            {
                "name": name,
                "wallet": str(WALLET),
                "prepared": {
                    "transaction": base64.b64encode(bytes(transaction)).decode("ascii"),
                    "blockhash": str(BLOCKHASH),
                    "lastValidBlockHeight": LAST_VALID_BLOCK_HEIGHT,
                    "message": message,
                    **prepared,
                },
                "intent": intent,
            }
        )

    position = make_initialize_vault_position_lp_ix(
        BACKEND_AUTHORITY, WALLET, VAULT_ID, PROGRAM
    )
    stake = make_stake_cal_in_vault_ix(
        BACKEND_AUTHORITY, WALLET, VAULT_ID, STAKE_AMOUNT, CAL_MINT, PROGRAM
    )
    initialize_lp = make_initialize_vault_lp_mint_ix(FEE_PAYER, VAULT_ID, PROGRAM)
    initialize_escrow = make_initialize_vault_cal_escrow_ix(
        FEE_PAYER, VAULT_ID, CAL_MINT, PROGRAM
    )
    for name, prefix in (
        ("stake_base", []),
        ("stake_lp_only", [initialize_lp]),
        ("stake_escrow_only", [initialize_escrow]),
        ("stake_all_initializers", [initialize_lp, initialize_escrow]),
    ):
        emit(
            name,
            [*prefix, position, stake],
            {
                "kind": "stake",
                "vaultId": VAULT_ID,
                "amountBaseUnits": str(STAKE_AMOUNT),
            },
            f"Stake {STAKE_AMOUNT} CAL in vault {VAULT_ID}",
            vaultId=VAULT_ID,
        )

    create_dung_ata = make_create_ata_ix(FEE_PAYER, WALLET, DUNG_MINT)
    collect = make_collect_stake_rewards_for_ix(
        WALLET, FEE_PAYER, VAULT_ID, DUNG_TREASURY, DUNG_MINT, PROGRAM
    )
    create_cal_ata = make_create_ata_ix(FEE_PAYER, WALLET, CAL_MINT)
    unstake = make_unstake_cal_from_vault_ix(
        WALLET, VAULT_ID, UNSTAKE_AMOUNT, CAL_MINT, PROGRAM
    )
    for name, prefix in (
        ("unstake_base", []),
        ("unstake_cal_ata", [create_cal_ata]),
        ("unstake_collect", [collect]),
        ("unstake_collect_cal_ata", [collect, create_cal_ata]),
        ("unstake_create_dung_collect", [create_dung_ata, collect]),
        ("unstake_all_optional", [create_dung_ata, collect, create_cal_ata]),
    ):
        emit(
            name,
            [*prefix, unstake],
            {
                "kind": "unstake",
                "vaultId": VAULT_ID,
                "lpAmountBaseUnits": str(UNSTAKE_AMOUNT),
            },
            f"Withdraw CAL from vault {VAULT_ID}",
            vaultId=VAULT_ID,
        )

    for symbol, mint, decimals in (
        ("cal", CAL_MINT, 9),
        ("usdc", USDC_MINT, 6),
    ):
        source = _derive_ata(WALLET, mint)
        destination, _ = _derive_rider_balance_token_pda(WALLET, mint, PROGRAM)
        transfer = make_spl_transfer_checked_ix(
            source=source,
            mint=mint,
            destination=destination,
            owner=WALLET,
            amount=BALANCE_AMOUNT,
            decimals=decimals,
        )
        emit(
            f"add_{symbol}",
            [transfer],
            {
                "kind": "balance_add_funds",
                "asset": symbol.upper(),
                "amountBaseUnits": str(BALANCE_AMOUNT),
            },
            f"Add {symbol.upper()} to Boulder Roller Balance",
            pda=str(destination),
        )

    for symbol, mint in (
        ("cal", CAL_MINT),
        ("dung", DUNG_MINT),
        ("usdc", USDC_MINT),
    ):
        withdraw = make_withdraw_to_wallet_ix(WALLET, mint, BALANCE_AMOUNT, PROGRAM)
        source, _ = _derive_rider_balance_token_pda(WALLET, mint, PROGRAM)
        intent = {
            "kind": "balance_withdraw",
            "asset": symbol.upper(),
            "amountBaseUnits": str(BALANCE_AMOUNT),
        }
        prepared = {
            "message": f"Withdraw {symbol.upper()} to wallet",
            "pda": str(source),
        }
        emit(f"withdraw_{symbol}", [withdraw], intent, **prepared)
        emit(
            f"withdraw_{symbol}_create_ata",
            [make_create_ata_ix(FEE_PAYER, WALLET, mint), withdraw],
            intent,
            **prepared,
        )

    counter, _ = _derive_vault_counter_pda(PROGRAM)
    vault, _ = _derive_vault_pda(VAULT_ID, PROGRAM)
    leaderboard, _ = _derive_vault_leaderboard_pda(VAULT_ID, PROGRAM)
    legend, _ = _derive_local_legend_pda(VAULT_ID, PROGRAM)
    activation, _ = _derive_vault_activation_pda(VAULT_ID, PROGRAM)
    create_intent = {
        "kind": "create_vault",
        "climbId": CLIMB_ID,
        "canonId": CANON_ID,
        "canonVersion": CANON_VERSION,
    }
    create_prepared = {
        "preparationId": "33333333-3333-3333-3333-333333333333",
        "climbId": CLIMB_ID,
        "canonCommitmentHex": COMMITMENT.hex(),
        "message": "Create Vault for Ratified Climb",
        "vaultId": VAULT_ID,
        "pda": str(vault),
    }
    emit(
        "create_dung",
        [
            make_create_vault_ix(
                BACKEND_AUTHORITY,
                WALLET,
                _derive_ata(WALLET, DUNG_MINT),
                DUNG_MINT,
                counter,
                vault,
                CLIMB_PDA,
                leaderboard,
                legend,
                activation,
                PROGRAM,
            )
        ],
        {**create_intent, "paymentMethod": "dung"},
        **create_prepared,
    )
    emit(
        "create_cal_usdc",
        [
            make_create_vault_with_usdc_ix(
                BACKEND_AUTHORITY,
                WALLET,
                _derive_ata(WALLET, CAL_MINT),
                CAL_MINT,
                _derive_ata(WALLET, USDC_MINT),
                USDC_TREASURY,
                counter,
                vault,
                CLIMB_PDA,
                leaderboard,
                legend,
                activation,
                PROGRAM,
            )
        ],
        {**create_intent, "paymentMethod": "cal_usdc"},
        **create_prepared,
    )

    if len(records) != 20:  # pragma: no cover - generator invariant
        raise AssertionError("portal transaction fixture count drifted")
    return records


def main() -> None:
    json.dump(build_records(), sys.stdout, indent=2, sort_keys=True)
    print()


if __name__ == "__main__":
    main()
