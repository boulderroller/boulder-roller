#!/usr/bin/env python3
"""Inventory devnet Vault LP custody before the account-bound migration."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import struct
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Finalized
from solana.rpc.types import MemcmpOpts
from solders.pubkey import Pubkey

from app.solana_direct import (
    DEFAULT_BOULDER_PROGRAM_ID,
    SPL_TOKEN_ACCOUNT_AMOUNT_OFFSET,
    SPL_TOKEN_ACCOUNT_LEN,
    SPL_TOKEN_ACCOUNT_STATE_OFFSET,
    SPL_TOKEN_MINT_LEN,
    TOKEN_PROGRAM_ID,
    _account_data_bytes,
    _decode_anchor_vault_stake_account,
    _derive_ata,
    _derive_rider_balance_auth_pda,
    _derive_rider_balance_token_pda,
    _derive_vault_activation_pda,
    _derive_vault_lp_mint_pda,
    _derive_vault_position_lp_pda,
    _derive_vault_stake_pda,
    _vault_stake_account_discriminator,
)


TOKEN_STATE_NAMES = {0: "uninitialized", 1: "initialized", 2: "frozen"}
RETIREMENT_SCHEMA = "boulderroller.lp-custody-retirements.v1"
DEVNET_GENESIS_HASH = "EtWTRABZaYq6iMfeYKouRu166VU2xqa1wcaWoxPkrZBG"
VAULT_ACTIVATION_LEN = 107
VAULT_ACTIVATION_DISCRIMINATOR = hashlib.sha256(
    b"account:VaultActivation"
).digest()[:8]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rpc-url", default="https://api.devnet.solana.com")
    parser.add_argument("--program-id", default=str(DEFAULT_BOULDER_PROGRAM_ID))
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--retirement-manifest",
        type=Path,
        help=(
            "Explicit hash-pinned devnet fixture retirement ledger. It changes "
            "inventory classification only and never submits a transaction."
        ),
    )
    parser.add_argument("--request-delay", type=float, default=0.75)
    parser.add_argument("--max-attempts", type=int, default=8)
    return parser.parse_args()


async def _rpc_with_retry(call, *, label: str, max_attempts: int):
    for attempt in range(1, max_attempts + 1):
        try:
            return await call()
        except Exception:
            if attempt == max_attempts:
                raise
            await asyncio.sleep(min(2 ** (attempt - 1), 20))


def _token_account(row: Any) -> dict[str, Any]:
    if row.account.owner != TOKEN_PROGRAM_ID:
        raise RuntimeError(f"token account {row.pubkey} has wrong program owner")
    data = _account_data_bytes(row.account.data)
    if len(data) != SPL_TOKEN_ACCOUNT_LEN:
        raise RuntimeError(f"token account {row.pubkey} has {len(data)} bytes")
    state = data[SPL_TOKEN_ACCOUNT_STATE_OFFSET]
    return {
        "address": str(row.pubkey),
        "mint": str(Pubkey.from_bytes(data[0:32])),
        "authority": str(Pubkey.from_bytes(data[32:64])),
        "amount_base_units": struct.unpack_from(
            "<Q", data, SPL_TOKEN_ACCOUNT_AMOUNT_OFFSET
        )[0],
        "state": TOKEN_STATE_NAMES.get(state, f"unknown:{state}"),
        "account_sha256": hashlib.sha256(data).hexdigest(),
    }


async def _load_stakes(client: AsyncClient, program_id: Pubkey) -> list[dict[str, Any]]:
    response = await client.get_program_accounts(
        program_id,
        commitment=Finalized,
        encoding="base64",
    )
    discriminator = _vault_stake_account_discriminator()
    stakes: list[dict[str, Any]] = []
    for row in response.value:
        data = _account_data_bytes(row.account.data)
        if data[:8] != discriminator:
            continue
        stake = _decode_anchor_vault_stake_account(data, row.pubkey)
        expected, expected_bump = _derive_vault_stake_pda(
            Pubkey.from_string(stake["user"]),
            stake["vault_id"],
            program_id,
        )
        if expected != row.pubkey or stake["bump"] != expected_bump:
            raise RuntimeError(f"noncanonical VaultStake {row.pubkey}")
        stake["account_sha256"] = hashlib.sha256(data).hexdigest()
        stakes.append(stake)
    stakes.sort(key=lambda stake: (stake["vault_id"], stake["user"]))
    return stakes


async def _load_mint_inventory(
    client: AsyncClient,
    mint: Pubkey,
    *,
    max_attempts: int,
) -> tuple[int, list[dict[str, Any]], str]:
    mint_response = await _rpc_with_retry(
        lambda: client.get_account_info(mint, commitment=Finalized),
        label=f"get LP mint {mint}",
        max_attempts=max_attempts,
    )
    accounts_response = await _rpc_with_retry(
        lambda: client.get_program_accounts(
            TOKEN_PROGRAM_ID,
            commitment=Finalized,
            encoding="base64",
            filters=[SPL_TOKEN_ACCOUNT_LEN, MemcmpOpts(offset=0, bytes=str(mint))],
        ),
        label=f"get LP holders {mint}",
        max_attempts=max_attempts,
    )
    if mint_response.value is None:
        raise RuntimeError(f"missing Vault LP mint {mint}")
    if mint_response.value.owner != TOKEN_PROGRAM_ID:
        raise RuntimeError(f"Vault LP mint {mint} has wrong program owner")
    mint_data = _account_data_bytes(mint_response.value.data)
    if len(mint_data) != SPL_TOKEN_MINT_LEN or mint_data[45] != 1:
        raise RuntimeError(f"Vault LP mint {mint} is not an initialized SPL mint")
    supply = struct.unpack_from("<Q", mint_data, 36)[0]
    accounts = [_token_account(row) for row in accounts_response.value]
    accounts.sort(key=lambda account: account["address"])
    return supply, accounts, hashlib.sha256(mint_data).hexdigest()


def _decode_vault_activation(
    address: Pubkey,
    data: bytes,
    *,
    vault_id: int,
    expected_bump: int,
) -> dict[str, Any]:
    if len(data) != VAULT_ACTIVATION_LEN:
        raise RuntimeError(
            f"VaultActivation {address} has {len(data)} bytes, expected {VAULT_ACTIVATION_LEN}"
        )
    if data[:8] != VAULT_ACTIVATION_DISCRIMINATOR:
        raise RuntimeError(f"VaultActivation {address} has the wrong discriminator")
    observed_vault_id = struct.unpack_from("<Q", data, 8)[0]
    if observed_vault_id != vault_id or data[-1] != expected_bump:
        raise RuntimeError(f"noncanonical VaultActivation {address}")
    return {
        "address": str(address),
        "vault_id": observed_vault_id,
        "is_active": bool(data[16]),
        "seed_generation": struct.unpack_from("<I", data, 46)[0],
        "economics_start_epoch": struct.unpack_from("<Q", data, 58)[0],
        "account_sha256": hashlib.sha256(data).hexdigest(),
    }


async def _load_activation_inventory(
    client: AsyncClient,
    vault_ids: list[int],
    program_id: Pubkey,
    *,
    max_attempts: int,
) -> dict[int, dict[str, Any]]:
    addresses_and_bumps = [
        (vault_id, *_derive_vault_activation_pda(vault_id, program_id))
        for vault_id in vault_ids
    ]
    response = await _rpc_with_retry(
        lambda: client.get_multiple_accounts(
            [address for _, address, _ in addresses_and_bumps],
            commitment=Finalized,
            encoding="base64",
        ),
        label="get VaultActivation inventory",
        max_attempts=max_attempts,
    )
    observations: dict[int, dict[str, Any]] = {}
    if len(response.value) != len(addresses_and_bumps):
        raise RuntimeError("VaultActivation inventory response length mismatch")
    for (vault_id, address, bump), account in zip(addresses_and_bumps, response.value):
        if account is None:
            raise RuntimeError(f"missing VaultActivation {address}")
        if account.owner != program_id:
            raise RuntimeError(f"VaultActivation {address} has wrong program owner")
        observations[vault_id] = _decode_vault_activation(
            address,
            _account_data_bytes(account.data),
            vault_id=vault_id,
            expected_bump=bump,
        )
    return observations


def _classify_stake(
    stake: dict[str, Any],
    accounts: list[dict[str, Any]],
    activation: dict[str, Any],
    program_id: Pubkey,
) -> dict[str, Any]:
    rider = Pubkey.from_string(stake["user"])
    vault_id = int(stake["vault_id"])
    mint, _ = _derive_vault_lp_mint_pda(vault_id, program_id)
    stake_pda, _ = _derive_vault_stake_pda(rider, vault_id, program_id)
    position, _ = _derive_vault_position_lp_pda(rider, vault_id, program_id)
    balance, _ = _derive_rider_balance_token_pda(rider, mint, program_id)
    balance_authority, _ = _derive_rider_balance_auth_pda(rider, program_id)
    wallet_ata = _derive_ata(rider, mint)
    by_address = {account["address"]: account for account in accounts}
    canonical = by_address.get(str(position))
    rider_sources = [
        account
        for account in accounts
        if account["amount_base_units"] > 0
        and account["address"] != str(position)
        and (
            account["authority"] == str(rider)
            or account["address"] == str(balance)
        )
    ]
    canonical_amount = canonical["amount_base_units"] if canonical else 0
    source_amount = sum(source["amount_base_units"] for source in rider_sources)
    recorded = int(stake["lp_tokens"])
    accounted = canonical_amount + source_amount
    reasons: list[str] = []

    if canonical:
        if canonical["authority"] != str(stake_pda):
            reasons.append("canonical position has wrong token authority")
        if canonical["state"] not in {"initialized", "frozen"}:
            reasons.append("canonical position has invalid token state")
    if accounted > recorded:
        reasons.append("rider-attributable LP exceeds VaultStake.lp_tokens")
    if accounted < recorded:
        reasons.append("rider-attributable LP is short of VaultStake.lp_tokens")

    if recorded == 0 and accounted == 0 and not reasons:
        decision = "no_position"
    elif reasons:
        decision = "quarantine"
    elif canonical_amount == recorded and not rider_sources:
        decision = "ready" if canonical and canonical["state"] == "frozen" else "seal"
    else:
        decision = "restore"

    actions: list[dict[str, Any]] = []
    if decision in {"seal", "restore"} and canonical and canonical["state"] == "initialized":
        actions.append({"action": "seal_canonical_position", "account": str(position)})
    if decision == "restore":
        remaining = recorded - canonical_amount
        for source in rider_sources:
            restore_amount = min(source["amount_base_units"], remaining)
            if restore_amount == 0:
                continue
            source_kind = (
                "legacy_balance"
                if source["address"] == str(balance)
                else "legacy_wallet_ata"
                if source["address"] == str(wallet_ata)
                else "rider_owned_custom"
            )
            actions.append(
                {
                    "action": "restore",
                    "source_kind": source_kind,
                    "source": source["address"],
                    "amount_base_units": restore_amount,
                }
            )
            remaining -= restore_amount

    return {
        "vault_id": vault_id,
        "rider": str(rider),
        "vault_stake": str(stake_pda),
        "lp_mint": str(mint),
        "recorded_lp_tokens": recorded,
        "vault_stake_observation": {
            "account_sha256": stake["account_sha256"],
            "cal_staked": int(stake["cal_staked"]),
            "effective_lp_tokens": int(stake["effective_lp_tokens"]),
            "pending_lp_tokens": int(stake["pending_lp_tokens"]),
            "pending_effective_week_plus_one": int(
                stake["pending_effective_week_plus_one"]
            ),
            "rewards_earned": int(stake["rewards_earned"]),
            "snapshot_layout": stake["snapshot_layout"],
        },
        "vault_activation_observation": activation,
        "canonical_position": str(position),
        "canonical_observation": canonical,
        "legacy_balance_account": str(balance),
        "legacy_balance_authority": str(balance_authority),
        "legacy_wallet_ata": str(wallet_ata),
        "attributable_sources": rider_sources,
        "attributable_total": accounted,
        "decision": decision,
        "reasons": reasons,
        "actions": actions,
    }


def _manifest_content_sha256(manifest: dict[str, Any]) -> str:
    content = {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    encoded = json.dumps(content, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _load_retirement_manifest(path: Path) -> tuple[dict[str, Any], str]:
    manifest = json.loads(path.read_text())
    if manifest.get("schema") != RETIREMENT_SCHEMA:
        raise RuntimeError(f"unsupported LP retirement schema in {path}")
    manifest_sha256 = _manifest_content_sha256(manifest)
    if manifest.get("manifest_sha256") != manifest_sha256:
        raise RuntimeError(f"LP retirement manifest hash mismatch in {path}")
    fixtures = manifest.get("fixtures")
    if not isinstance(fixtures, list) or not fixtures:
        raise RuntimeError("LP retirement manifest must name at least one fixture")
    fixture_keys = [(row.get("vault_id"), row.get("rider")) for row in fixtures]
    if len(fixture_keys) != len(set(fixture_keys)):
        raise RuntimeError("LP retirement manifest contains duplicate fixtures")
    return manifest, manifest_sha256


def _require_fixture(condition: bool, vault_id: int, message: str) -> None:
    if not condition:
        raise RuntimeError(f"retired fixture vault {vault_id}: {message}")


def _apply_retirement_manifest(
    rows: list[dict[str, Any]],
    vaults: list[dict[str, Any]],
    manifest: dict[str, Any],
    *,
    genesis_hash: str,
    program_id: str,
) -> dict[str, Any]:
    if manifest.get("network") != "devnet":
        raise RuntimeError("retirement manifest network must be devnet")
    if manifest.get("genesis_hash") != genesis_hash:
        raise RuntimeError("retirement genesis hash mismatch")
    if manifest.get("program_id") != program_id:
        raise RuntimeError("retirement program id mismatch")
    if manifest.get("mutation") != "none":
        raise RuntimeError("retirement mutation must be none")
    if manifest.get("transaction_signatures") != []:
        raise RuntimeError("non-mutating retirement cannot contain transaction signatures")

    by_position = {(row["vault_id"], row["rider"]): row for row in rows}
    by_vault = {vault["vault_id"]: vault for vault in vaults}
    retired_keys: set[tuple[int, str]] = set()

    for fixture in manifest["fixtures"]:
        vault_id = int(fixture["vault_id"])
        rider = str(fixture["rider"])
        key = (vault_id, rider)
        row = by_position.get(key)
        vault = by_vault.get(vault_id)
        _require_fixture(row is not None, vault_id, "position is missing")
        _require_fixture(vault is not None, vault_id, "vault inventory is missing")
        assert row is not None and vault is not None

        _require_fixture(row["decision"] == "restore", vault_id, "raw decision is not restore")
        _require_fixture(row["vault_stake"] == fixture["vault_stake"], vault_id, "VaultStake address drift")
        _require_fixture(row["lp_mint"] == fixture["lp_mint"], vault_id, "LP mint address drift")
        _require_fixture(
            row["canonical_position"] == fixture["canonical_position"],
            vault_id,
            "canonical position address drift",
        )
        _require_fixture(row["canonical_observation"] is None, vault_id, "canonical custody unexpectedly exists")
        _require_fixture(len(row["attributable_sources"]) == 1, vault_id, "expected one legacy LP source")
        _require_fixture(len(row["actions"]) == 1, vault_id, "expected one restoration action")

        source = row["attributable_sources"][0]
        action = row["actions"][0]
        amount = int(fixture["amount_base_units"])
        _require_fixture(
            action.get("source_kind") == "legacy_wallet_ata",
            vault_id,
            "source is not the rider wallet ATA",
        )
        _require_fixture(
            row["legacy_wallet_ata"] == fixture["source_lp_account"],
            vault_id,
            "source is not the derived rider wallet ATA",
        )
        _require_fixture(
            source["address"] == fixture["source_lp_account"]
            and action["source"] == fixture["source_lp_account"],
            vault_id,
            "source LP account address drift",
        )
        _require_fixture(source["authority"] == rider, vault_id, "source authority is not the rider")
        _require_fixture(source["mint"] == fixture["lp_mint"], vault_id, "source LP mint drift")
        _require_fixture(source["state"] == "initialized", vault_id, "source LP account is not initialized")
        _require_fixture(
            row["recorded_lp_tokens"] == amount
            and row["attributable_total"] == amount
            and source["amount_base_units"] == amount
            and action["amount_base_units"] == amount,
            vault_id,
            "LP amount drift",
        )

        hashes = fixture["account_sha256"]
        stake_observation = row["vault_stake_observation"]
        activation = row["vault_activation_observation"]
        _require_fixture(
            stake_observation["account_sha256"] == hashes["vault_stake"],
            vault_id,
            "VaultStake account hash drift",
        )
        _require_fixture(
            source["account_sha256"] == hashes["source_lp_account"],
            vault_id,
            "source LP account hash drift",
        )
        _require_fixture(
            vault["lp_mint_account_sha256"] == hashes["lp_mint"],
            vault_id,
            "LP mint account hash drift",
        )
        _require_fixture(
            activation["address"] == fixture["vault_activation"]
            and activation["account_sha256"] == hashes["vault_activation"],
            vault_id,
            "VaultActivation account hash or address drift",
        )
        _require_fixture(
            activation["is_active"] is True and activation["seed_generation"] == 1,
            vault_id,
            "position is outside the generation-1 quarantine",
        )
        _require_fixture(
            stake_observation["snapshot_layout"] == "legacy"
            and stake_observation["cal_staked"] == amount
            and stake_observation["effective_lp_tokens"] == 0
            and stake_observation["pending_lp_tokens"] == 0
            and stake_observation["pending_effective_week_plus_one"] == 0,
            vault_id,
            "legacy stake lifecycle drift",
        )
        _require_fixture(
            stake_observation["rewards_earned"] == fixture["rewards_earned"],
            vault_id,
            "legacy reward liability drift",
        )
        _require_fixture(
            activation["economics_start_epoch"] == fixture["economics_start_epoch"],
            vault_id,
            "economics start epoch drift",
        )
        _require_fixture(
            vault["mint_supply"] == amount
            and vault["token_account_total"] == amount
            and vault["vault_stake_recorded_total"] == amount
            and not vault["unattributed_holders"],
            vault_id,
            "vault conservation drift",
        )

        row["decision"] = "retired_fixture"
        row["actions"] = []
        row["retirement"] = {
            "retirement_id": manifest["retirement_id"],
            "retired_at": manifest["retired_at"],
            "reason": fixture["reason"],
            "account_state_mutated": False,
            "transaction_signatures": [],
        }
        retired_keys.add(key)

    for vault in vaults:
        vault_rows = rows_by_vault(rows, vault["vault_id"])
        vault["retired_stake_recorded_total"] = sum(
            row["recorded_lp_tokens"]
            for row in vault_rows
            if (row["vault_id"], row["rider"]) in retired_keys
        )
        vault["surviving_stake_recorded_total"] = sum(
            row["recorded_lp_tokens"]
            for row in vault_rows
            if (row["vault_id"], row["rider"]) not in retired_keys
        )

    return {
        "retirement_id": manifest["retirement_id"],
        "retirement_count": len(retired_keys),
        "mutation": "none",
        "transaction_signatures": [],
    }


def _validate_surviving_positions(
    rows: list[dict[str, Any]], vaults: list[dict[str, Any]]
) -> None:
    by_vault = {vault["vault_id"]: vault for vault in vaults}
    for row in rows:
        if row["recorded_lp_tokens"] == 0 or row["decision"] == "retired_fixture":
            continue
        canonical = row["canonical_observation"]
        if (
            row["decision"] != "ready"
            or canonical is None
            or canonical.get("state") != "frozen"
            or canonical.get("amount_base_units") != row["recorded_lp_tokens"]
        ):
            raise RuntimeError(
                f"surviving vault {row['vault_id']} position lacks frozen canonical custody"
            )
        vault = by_vault[row["vault_id"]]
        surviving_total = vault.get(
            "surviving_stake_recorded_total", vault["vault_stake_recorded_total"]
        )
        if not (
            surviving_total
            == vault["mint_supply"]
            == vault["token_account_total"]
            and not vault["unattributed_holders"]
        ):
            raise RuntimeError(
                f"surviving vault {row['vault_id']} does not conserve exact LP supply"
            )


async def _inventory(args: argparse.Namespace) -> dict[str, Any]:
    program_id = Pubkey.from_string(args.program_id)
    retirement_manifest = None
    retirement_manifest_sha256 = None
    if getattr(args, "retirement_manifest", None):
        retirement_manifest, retirement_manifest_sha256 = _load_retirement_manifest(
            args.retirement_manifest
        )
    async with AsyncClient(args.rpc_url, commitment=Finalized) as client:
        start_slot = int((await client.get_slot(commitment=Finalized)).value)
        genesis_hash = str(
            (
                await _rpc_with_retry(
                    client.get_genesis_hash,
                    label="get genesis hash",
                    max_attempts=args.max_attempts,
                )
            ).value
        )
        stakes = await _load_stakes(client, program_id)
        by_vault: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for stake in stakes:
            by_vault[int(stake["vault_id"])].append(stake)

        activation_inventories = await _load_activation_inventory(
            client,
            sorted(by_vault),
            program_id,
            max_attempts=args.max_attempts,
        )
        mint_inventories: dict[int, tuple[int, list[dict[str, Any]], str]] = {}
        for vault_id in sorted(by_vault):
            mint, _ = _derive_vault_lp_mint_pda(vault_id, program_id)
            mint_inventories[vault_id] = await _load_mint_inventory(
                client,
                mint,
                max_attempts=args.max_attempts,
            )
            await asyncio.sleep(args.request_delay)
        end_slot = int((await client.get_slot(commitment=Finalized)).value)

    rows = [
        _classify_stake(
            stake,
            mint_inventories[int(stake["vault_id"])][1],
            activation_inventories[int(stake["vault_id"])],
            program_id,
        )
        for stake in stakes
    ]
    vaults = []
    for vault_id, vault_stakes in sorted(by_vault.items()):
        supply, accounts, mint_account_sha256 = mint_inventories[vault_id]
        known_riders = {stake["user"] for stake in vault_stakes}
        known_addresses = {
            row["canonical_position"]
            for row in rows
            if row["vault_id"] == vault_id
        }
        known_addresses.update(
            row["legacy_balance_account"]
            for row in rows
            if row["vault_id"] == vault_id
        )
        attributable_accounts = [
            account
            for account in accounts
            if account["address"] in known_addresses
            or account["authority"] in known_riders
        ]
        unattributed = [
            account
            for account in accounts
            if account["amount_base_units"] > 0
            and account not in attributable_accounts
        ]
        vaults.append(
            {
                "vault_id": vault_id,
                "lp_mint": rows_by_vault(rows, vault_id)[0]["lp_mint"],
                "lp_mint_account_sha256": mint_account_sha256,
                "mint_supply": supply,
                "token_account_total": sum(
                    account["amount_base_units"] for account in accounts
                ),
                "vault_stake_recorded_total": sum(
                    int(stake["lp_tokens"]) for stake in vault_stakes
                ),
                "unattributed_holders": unattributed,
                "retired_stake_recorded_total": 0,
                "surviving_stake_recorded_total": sum(
                    int(stake["lp_tokens"]) for stake in vault_stakes
                ),
            }
        )

    if any(vault["unattributed_holders"] for vault in vaults):
        for row in rows:
            if row["decision"] == "quarantine" and "short" in " ".join(row["reasons"]):
                row["reasons"].append(
                    "unattributed holder ownership cannot be assigned automatically"
                )

    retirement = None
    if retirement_manifest is not None:
        retirement = _apply_retirement_manifest(
            rows,
            vaults,
            retirement_manifest,
            genesis_hash=genesis_hash,
            program_id=str(program_id),
        )
        retirement["manifest_sha256"] = retirement_manifest_sha256
        _validate_surviving_positions(rows, vaults)

    decision_counts = Counter(row["decision"] for row in rows)
    evidence = {"positions": rows, "vaults": vaults}
    evidence_json = json.dumps(evidence, sort_keys=True, separators=(",", ":"))
    return {
        "schema": "boulderroller.lp-custody-inventory.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "network": "devnet" if genesis_hash == DEVNET_GENESIS_HASH else "custom",
        "genesis_hash": genesis_hash,
        "rpc_url": args.rpc_url,
        "program_id": str(program_id),
        "finalized_slot_start": start_slot,
        "finalized_slot_end": end_slot,
        "evidence_sha256": hashlib.sha256(evidence_json.encode()).hexdigest(),
        "summary": {
            "position_count": len(rows),
            "surviving_position_count": sum(
                row["recorded_lp_tokens"] > 0
                and row["decision"] != "retired_fixture"
                for row in rows
            ),
            "retired_fixture_count": sum(
                row["decision"] == "retired_fixture" for row in rows
            ),
            "vault_count": len(vaults),
            "decision_counts": dict(sorted(decision_counts.items())),
            "rollout_ready": not any(
                row["decision"] in {"restore", "seal", "quarantine"} for row in rows
            ),
        },
        "retirement": retirement,
        **evidence,
    }


def rows_by_vault(rows: list[dict[str, Any]], vault_id: int) -> list[dict[str, Any]]:
    return [row for row in rows if row["vault_id"] == vault_id]


def main() -> None:
    args = _parse_args()
    report = asyncio.run(_inventory(args))
    payload = f"{json.dumps(report, indent=2, sort_keys=True)}\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload)
    print(payload, end="")


if __name__ == "__main__":
    main()
