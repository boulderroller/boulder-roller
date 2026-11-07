"""Guarded, durable evidence authority for isolated rehearsal USDC setup."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Finalized
from solders.pubkey import Pubkey

from app.solana_direct import (
    TOKEN_PROGRAM_ID,
    _account_data_bytes,
    _derive_ata,
    _derive_cal_mint_auth_pda,
    _derive_program_config_pda,
    _get_boulder_accounts_coder,
)

from rehearsal_evidence import (
    BPF_UPGRADEABLE_LOADER_ID,
    PROTECTED_PROGRAM_ID,
    PROTECTED_TEST_USDC_MINT,
    RehearsalEvidenceManifest,
    _atomic_write,
    _decoded_fields,
    _exclusive_manifest_lock,
    _field_value,
    _json_value,
)


SETUP_SCHEMA = "boulderroller_v4b_rehearsal_setup_v1"
REHEARSAL_VAULT_CREATION_USDC = 2_000_000
SETUP_TRANSACTION_STAGES = (
    "mint_created",
    "atas_created",
    "supply_minted",
    "mint_authority_revoked",
    "configured",
)


class RehearsalSetupEvidenceManifest(RehearsalEvidenceManifest):
    """Pre-configuration protected baseline plus resumable setup transactions."""

    SETUP_ANCHOR_ACCOUNT_TYPES = {
        "setup_program_config": "ProgramConfig",
    }

    @classmethod
    def _setup_account_evidence(
        cls,
        label: str,
        address: Pubkey,
        account: object | None,
        *,
        program_id: Pubkey,
    ) -> dict[str, Any]:
        evidence = RehearsalEvidenceManifest._account_evidence(
            label, address, account
        )
        expected_type = cls.SETUP_ANCHOR_ACCOUNT_TYPES.get(label)
        if expected_type is None or account is None:
            return evidence
        if Pubkey.from_string(str(getattr(account, "owner"))) != program_id:
            raise RuntimeError(f"{label} is not owned by the setup program")
        try:
            parsed = _get_boulder_accounts_coder().parse(
                _account_data_bytes(getattr(account, "data"))
            )
        except Exception as exc:
            raise RuntimeError(f"{label} failed exact Anchor decoding") from exc
        if parsed.name != expected_type:
            raise RuntimeError(
                f"{label} decoded as {parsed.name}, expected {expected_type}"
            )
        evidence["decoded"] = {
            "account_type": parsed.name,
            "fields": _json_value(vars(parsed.data)),
        }
        return evidence

    @classmethod
    async def _read_accounts(
        cls,
        rpc_url: str,
        addresses: dict[str, Pubkey],
    ) -> tuple[int, dict[str, dict[str, Any]]]:
        labels = tuple(addresses)
        program_id = addresses.get("setup_program")
        async with AsyncClient(rpc_url, commitment=Finalized) as client:
            response = await client.get_multiple_accounts(
                [addresses[label] for label in labels],
                commitment=Finalized,
            )
        values = tuple(response.value)
        if len(values) != len(labels):
            raise RuntimeError("rehearsal setup evidence snapshot is incomplete")
        if program_id is None and any(
            label in cls.SETUP_ANCHOR_ACCOUNT_TYPES for label in labels
        ):
            raise RuntimeError("setup Anchor decoding requires setup_program identity")
        snapshot = {
            label: cls._setup_account_evidence(
                label,
                addresses[label],
                account,
                program_id=program_id,
            )
            for label, account in zip(labels, values)
        }
        return int(response.context.slot), snapshot

    @classmethod
    async def open(
        cls,
        *,
        path: Path,
        rpc_url: str,
        program_id: Pubkey,
        program_data: Pubkey,
        admin: Pubkey,
        backend_authority: Pubkey,
        fee_payer: Pubkey,
        rider: Pubkey,
        cal_mint: Pubkey,
        usdc_mint: Pubkey,
        initial_usdc_supply: int,
        vault_creation_usdc: int,
    ) -> "RehearsalSetupEvidenceManifest":
        if not path.is_absolute():
            raise RuntimeError("--rehearsal-setup-evidence must be an absolute path")
        if vault_creation_usdc != REHEARSAL_VAULT_CREATION_USDC:
            raise RuntimeError(
                "rehearsal Vault creation USDC cost does not match the frozen "
                "bootstrap constant"
            )
        if initial_usdc_supply < vault_creation_usdc:
            raise RuntimeError("rehearsal USDC supply must cover the Vault cost")
        if program_id == PROTECTED_PROGRAM_ID or usdc_mint == PROTECTED_TEST_USDC_MINT:
            raise RuntimeError("setup identity overlaps protected canonical deployment")
        resolved = path.resolve()
        config, _ = _derive_program_config_pda(program_id)
        treasury = _derive_ata(admin, usdc_mint)
        rider_usdc_ata = _derive_ata(rider, usdc_mint)
        rider_cal_ata = _derive_ata(rider, cal_mint)
        protected_addresses = await cls._resolve_protected_addresses(rpc_url)
        setup_addresses = {
            "setup_program": program_id,
            "setup_program_data": program_data,
            "setup_program_config": config,
            "setup_cal_mint": cal_mint,
            "setup_rider_cal_ata": rider_cal_ata,
            "setup_usdc_mint": usdc_mint,
            "setup_usdc_treasury": treasury,
            "setup_rider_usdc_ata": rider_usdc_ata,
        }
        protected_set = {str(value) for value in protected_addresses.values()}
        overlap = [
            f"{label}={address}"
            for label, address in setup_addresses.items()
            if str(address) in protected_set
        ]
        if overlap:
            raise RuntimeError(
                "rehearsal setup overlaps protected canonical accounts: "
                + ", ".join(overlap)
            )
        protected_slot, protected = await cls._read_accounts(
            rpc_url, protected_addresses
        )
        setup_slot, setup = await cls._read_accounts(rpc_url, setup_addresses)
        cls._validate_setup_program_baseline(
            setup,
            program_id=program_id,
            program_data=program_data,
            admin=admin,
            backend_authority=backend_authority,
            cal_mint=cal_mint,
        )
        identity = {
            "program_id": str(program_id),
            "program_data": str(program_data),
            "admin": str(admin),
            "backend_authority": str(backend_authority),
            "fee_payer": str(fee_payer),
            "rider": str(rider),
            "cal_mint": str(cal_mint),
            "rider_cal_ata": str(rider_cal_ata),
            "usdc_mint": str(usdc_mint),
            "usdc_treasury": str(treasury),
            "rider_usdc_ata": str(rider_usdc_ata),
            "initial_usdc_supply": int(initial_usdc_supply),
            "vault_creation_usdc": int(vault_creation_usdc),
        }
        if resolved.exists():
            try:
                state = json.loads(resolved.read_text(encoding="utf-8"))
            except Exception as exc:
                raise RuntimeError("rehearsal setup evidence is unreadable") from exc
            if state.get("schema") != SETUP_SCHEMA or state.get("identity") != identity:
                raise RuntimeError("rehearsal setup resume identity does not match")
            cls._assert_protected_baseline(
                state.get("baseline", {}).get("protected", {}), protected
            )
        else:
            fields = _decoded_fields(setup["setup_program_config"])
            if (
                _field_value(fields, "usdc_mint", "usdcMint")
                != str(Pubkey.default())
                or _field_value(
                    fields,
                    "usdc_treasury_token_account",
                    "usdcTreasuryTokenAccount",
                )
                != str(Pubkey.default())
                or int(
                    _field_value(
                        fields,
                        "vault_creation_usdc",
                        "vaultCreationUsdc",
                        default=0,
                    )
                    or 0
                )
                != vault_creation_usdc
            ):
                raise RuntimeError(
                    "new setup evidence requires the exact bootstrap ProgramConfig "
                    "USDC rail"
                )
            if any(
                setup[label]["exists"]
                for label in (
                    "setup_usdc_mint",
                    "setup_usdc_treasury",
                    "setup_rider_usdc_ata",
                    "setup_rider_cal_ata",
                )
            ):
                raise RuntimeError(
                    "new setup evidence requires an unused mint and absent token accounts"
                )
            state = {
                "schema": SETUP_SCHEMA,
                "mode": "usdc_setup",
                "identity": identity,
                "protected_addresses": {
                    label: str(address)
                    for label, address in protected_addresses.items()
                },
                "setup_addresses": {
                    label: str(address) for label, address in setup_addresses.items()
                },
                "baseline": {
                    "protected_slot": protected_slot,
                    "setup_slot": setup_slot,
                    "protected": protected,
                    "setup": setup,
                },
                "transactions": [],
                "reconciliations": [],
                "handoff": None,
            }
            with _exclusive_manifest_lock(resolved):
                if resolved.exists():
                    raise RuntimeError("setup evidence appeared concurrently")
                _atomic_write(resolved, state)
        return cls(path=resolved, rpc_url=rpc_url, state=state)

    @staticmethod
    def _validate_setup_program_baseline(
        setup: dict[str, dict[str, Any]],
        *,
        program_id: Pubkey,
        program_data: Pubkey,
        admin: Pubkey,
        backend_authority: Pubkey,
        cal_mint: Pubkey,
    ) -> None:
        program = setup["setup_program"]
        loader = program.get("decoded") or {}
        if (
            not program.get("exists")
            or program.get("owner") != str(BPF_UPGRADEABLE_LOADER_ID)
            or not program.get("executable")
            or loader.get("program_data_address") != str(program_data)
        ):
            raise RuntimeError("rehearsal setup program/ProgramData link is invalid")
        if (
            not setup["setup_program_data"].get("exists")
            or setup["setup_program_data"].get("owner")
            != str(BPF_UPGRADEABLE_LOADER_ID)
            or (setup["setup_program_data"].get("decoded") or {}).get(
                "loader_state"
            )
            != "ProgramData"
        ):
            raise RuntimeError("rehearsal setup ProgramData is invalid")
        program_config = setup["setup_program_config"]
        if (
            not program_config.get("exists")
            or program_config.get("owner") != str(program_id)
            or (program_config.get("decoded") or {}).get("account_type")
            != "ProgramConfig"
        ):
            raise RuntimeError("rehearsal setup ProgramConfig is invalid")
        fields = _decoded_fields(program_config)
        if _field_value(fields, "admin_authority", "adminAuthority") != str(admin):
            raise RuntimeError("setup admin signer does not match ProgramConfig")
        if (
            _field_value(fields, "backend_authority", "backendAuthority")
            != str(backend_authority)
        ):
            raise RuntimeError("setup backend signer does not match ProgramConfig")
        if _field_value(fields, "cal_mint", "calMint") != str(cal_mint):
            raise RuntimeError("setup CAL mint does not match ProgramConfig")
        cal = setup["setup_cal_mint"]
        decoded_cal = cal.get("decoded") or {}
        expected_authority, _ = _derive_cal_mint_auth_pda(program_id)
        if (
            not cal.get("exists")
            or cal.get("address") != str(cal_mint)
            or cal.get("owner") != str(TOKEN_PROGRAM_ID)
            or decoded_cal.get("decimals") != 9
            or not decoded_cal.get("initialized")
            or int(decoded_cal.get("supply_base_units", -1)) != 0
            or decoded_cal.get("mint_authority") != str(expected_authority)
            or decoded_cal.get("freeze_authority") is not None
        ):
            raise RuntimeError("setup CAL mint identity/authority/state is invalid")

    @staticmethod
    def _validate_rider_cal_ata(
        setup: dict[str, dict[str, Any]],
        *,
        cal_mint: Pubkey,
        rider: Pubkey,
        required: bool,
    ) -> None:
        item = setup["setup_rider_cal_ata"]
        if not item.get("exists"):
            if required:
                raise RuntimeError("setup stage is missing the rider CAL ATA")
            return
        decoded = item.get("decoded") or {}
        if (
            item.get("owner") != str(TOKEN_PROGRAM_ID)
            or decoded.get("mint") != str(cal_mint)
            or decoded.get("token_owner") != str(rider)
            or decoded.get("state") not in (1, 2)
        ):
            raise RuntimeError("setup rider CAL ATA mint/owner/state is invalid")
        if int(decoded.get("amount_base_units", -1)) != 0:
            raise RuntimeError("setup rider CAL ATA must begin at zero balance")

    def _reload_current_state(self) -> None:
        if not self.path.exists():
            raise RuntimeError("rehearsal setup evidence disappeared")
        try:
            current = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise RuntimeError("rehearsal setup evidence is unreadable") from exc
        if (
            not isinstance(current, dict)
            or current.get("schema") != SETUP_SCHEMA
            or current.get("identity") != self._state.get("identity")
        ):
            raise RuntimeError("rehearsal setup evidence identity changed")
        self._state = current

    def _setup_addresses(self) -> dict[str, Pubkey]:
        return {
            label: Pubkey.from_string(address)
            for label, address in self._state["setup_addresses"].items()
        }

    async def preflight_setup_progress(self) -> None:
        """Recover only the latest finalized stage, then freeze exact resume state."""
        self._reload_current_state()
        transactions_by_stage: dict[str, dict[str, Any]] = {}
        prefix = "rehearsal_usdc_"
        for transaction in self._state.get("transactions", []):
            tx_type = str((transaction.get("metadata") or {}).get("tx_type") or "")
            if not tx_type.startswith(prefix):
                raise RuntimeError("setup evidence contains a foreign transaction type")
            stage = tx_type[len(prefix) :]
            if stage not in SETUP_TRANSACTION_STAGES:
                raise RuntimeError("setup evidence transaction stage is foreign")
            if transaction.get("status") in {"expired", "failed"}:
                continue
            if stage in transactions_by_stage:
                raise RuntimeError("setup evidence has duplicate live/finalized stages")
            if transaction.get("status") != "finalized":
                raise RuntimeError(f"setup transaction {stage} is not finalized")
            transactions_by_stage[stage] = transaction

        transaction_stages = [
            stage for stage in SETUP_TRANSACTION_STAGES if stage in transactions_by_stage
        ]
        if transaction_stages != list(
            SETUP_TRANSACTION_STAGES[: len(transaction_stages)]
        ):
            raise RuntimeError("setup transaction stages are not a contiguous prefix")

        reconciled_stages = [
            str(item.get("stage"))
            for item in self._state.get("reconciliations", [])
            if item.get("stage") in SETUP_TRANSACTION_STAGES
        ]
        if len(set(reconciled_stages)) != len(reconciled_stages) or reconciled_stages != list(
            SETUP_TRANSACTION_STAGES[: len(reconciled_stages)]
        ):
            raise RuntimeError("setup reconciliation stages are duplicated or out of order")
        if len(reconciled_stages) > len(transaction_stages):
            raise RuntimeError("setup reconciliation has no finalized transaction")
        if len(transaction_stages) - len(reconciled_stages) > 1:
            raise RuntimeError("setup evidence skipped a durable stage reconciliation")
        if len(transaction_stages) == len(reconciled_stages) + 1:
            stage = transaction_stages[-1]
            await self.finalize_setup_stage(
                stage,
                str(transactions_by_stage[stage]["signature"]),
            )
            self._reload_current_state()

        protected_addresses = {
            label: Pubkey.from_string(address)
            for label, address in self._state["protected_addresses"].items()
        }
        _, protected = await self._read_accounts(self.rpc_url, protected_addresses)
        _, setup = await self._read_accounts(self.rpc_url, self._setup_addresses())
        self._assert_protected_baseline(
            self._state["baseline"]["protected"], protected
        )
        if transaction_stages:
            last = next(
                item
                for item in reversed(self._state["reconciliations"])
                if item.get("stage") == transaction_stages[-1]
            )
            if last.get("protected") != protected or last.get("setup") != setup:
                raise RuntimeError(
                    "setup chain state changed after its latest durable stage"
                )
        elif (
            self._state["baseline"].get("protected") != protected
            or self._state["baseline"].get("setup") != setup
        ):
            raise RuntimeError("unused setup baseline changed before the first write")

        ready = [
            item
            for item in self._state.get("reconciliations", [])
            if item.get("stage") == "setup_ready"
        ]
        if len(ready) > 1:
            raise RuntimeError("setup ready reconciliation is duplicated")
        if ready and len(transaction_stages) != len(SETUP_TRANSACTION_STAGES):
            raise RuntimeError("setup ready exists before every guarded stage finalized")

    async def capture_setup_stage(self, stage: str) -> None:
        protected_addresses = {
            label: Pubkey.from_string(address)
            for label, address in self._state["protected_addresses"].items()
        }
        protected_slot, protected = await self._read_accounts(
            self.rpc_url, protected_addresses
        )
        setup_slot, setup = await self._read_accounts(
            self.rpc_url, self._setup_addresses()
        )
        self._assert_protected_baseline(
            self._state["baseline"]["protected"], protected
        )
        self._validate_stage_snapshot(stage, setup)
        with self._lock:
            with self._write_lock():
                self._reload_current_state()
                existing = next(
                    (
                        item
                        for item in self._state["reconciliations"]
                        if item.get("stage") == stage
                    ),
                    None,
                )
                if existing is not None:
                    if (
                        existing.get("protected") != protected
                        or existing.get("setup") != setup
                    ):
                        raise RuntimeError(
                            f"setup stage {stage} changed after it was evidenced"
                        )
                    if stage == "setup_ready":
                        identity = self._state["identity"]
                        expected_handoff = {
                            "status": "ready",
                            **identity,
                            "mint_authority_revoked": True,
                            "initial_rider_cal_balance": 0,
                            "initial_rider_usdc_balance": identity[
                                "initial_usdc_supply"
                            ],
                            "initial_treasury_usdc_balance": 0,
                        }
                        if self._state.get("handoff") != expected_handoff:
                            raise RuntimeError(
                                "setup ready handoff changed after it was evidenced"
                            )
                    return
                self._state["reconciliations"].append(
                    {
                        "stage": stage,
                        "protected_slot": protected_slot,
                        "setup_slot": setup_slot,
                        "protected": protected,
                        "setup": setup,
                    }
                )
                if stage == "setup_ready":
                    identity = self._state["identity"]
                    self._state["handoff"] = {
                        "status": "ready",
                        **identity,
                        "mint_authority_revoked": True,
                        "initial_rider_cal_balance": 0,
                        "initial_rider_usdc_balance": identity[
                            "initial_usdc_supply"
                        ],
                        "initial_treasury_usdc_balance": 0,
                    }
                _atomic_write(self.path, self._state)

    async def finalize_setup_stage(
        self, stage: str, signature: str | None = None
    ) -> None:
        if signature:
            await self.reconcile_signature(signature)
        await self.capture_setup_stage(stage)

    def _validate_stage_snapshot(
        self, stage: str, setup: dict[str, dict[str, Any]]
    ) -> None:
        identity = self._state["identity"]
        cal = setup["setup_cal_mint"]
        decoded_cal = cal.get("decoded") or {}
        expected_cal_authority, _ = _derive_cal_mint_auth_pda(
            Pubkey.from_string(identity["program_id"])
        )
        if (
            not cal.get("exists")
            or cal.get("address") != identity["cal_mint"]
            or cal.get("owner") != str(TOKEN_PROGRAM_ID)
            or decoded_cal.get("decimals") != 9
            or not decoded_cal.get("initialized")
            or int(decoded_cal.get("supply_base_units", -1)) != 0
            or decoded_cal.get("mint_authority") != str(expected_cal_authority)
            or decoded_cal.get("freeze_authority") is not None
        ):
            raise RuntimeError("setup CAL mint identity/authority/state is invalid")
        self._validate_rider_cal_ata(
            setup,
            cal_mint=Pubkey.from_string(identity["cal_mint"]),
            rider=Pubkey.from_string(identity["rider"]),
            required=stage != "mint_created",
        )
        mint = setup["setup_usdc_mint"]
        if stage in {
            "mint_created",
            "atas_created",
            "supply_minted",
            "mint_authority_revoked",
            "configured",
            "setup_ready",
        }:
            if not mint.get("exists"):
                raise RuntimeError("setup stage is missing the rehearsal USDC mint")
            decoded = mint.get("decoded") or {}
            if (
                decoded.get("decimals") != 6
                or not decoded.get("initialized")
                or decoded.get("mint_authority") not in (identity["admin"], None)
                or decoded.get("freeze_authority") is not None
            ):
                raise RuntimeError("setup USDC mint authority/decimals/freeze state is invalid")
        if stage == "mint_created":
            if int((mint.get("decoded") or {}).get("supply_base_units", -1)) != 0:
                raise RuntimeError("new setup USDC mint did not begin at zero supply")
            if setup["setup_usdc_treasury"].get("exists") or setup[
                "setup_rider_usdc_ata"
            ].get("exists"):
                raise RuntimeError("setup token accounts appeared before their guarded stage")
        if stage in {"mint_authority_revoked", "configured", "setup_ready"}:
            if (mint.get("decoded") or {}).get("mint_authority") is not None:
                raise RuntimeError(
                    "setup USDC mint authority must be revoked before configuration"
                )
        if stage in {
            "atas_created",
            "supply_minted",
            "mint_authority_revoked",
            "configured",
            "setup_ready",
        }:
            for label, owner in (
                ("setup_usdc_treasury", identity["admin"]),
                ("setup_rider_usdc_ata", identity["rider"]),
            ):
                item = setup[label]
                decoded = item.get("decoded") or {}
                if (
                    not item.get("exists")
                    or decoded.get("mint") != identity["usdc_mint"]
                    or decoded.get("token_owner") != owner
                ):
                    raise RuntimeError(f"{label} mint/owner is invalid")
        if stage == "atas_created":
            if int((mint.get("decoded") or {}).get("supply_base_units", -1)) != 0:
                raise RuntimeError("setup USDC supply changed before guarded minting")
            if any(
                int(
                    (setup[label].get("decoded") or {}).get(
                        "amount_base_units", -1
                    )
                )
                != 0
                for label in ("setup_usdc_treasury", "setup_rider_usdc_ata")
            ):
                raise RuntimeError("setup token accounts were not created empty")
        if stage in {
            "supply_minted",
            "mint_authority_revoked",
            "configured",
            "setup_ready",
        }:
            supply = int((mint.get("decoded") or {}).get("supply_base_units", -1))
            rider = int(
                (setup["setup_rider_usdc_ata"].get("decoded") or {}).get(
                    "amount_base_units", -1
                )
            )
            treasury = int(
                (setup["setup_usdc_treasury"].get("decoded") or {}).get(
                    "amount_base_units", -1
                )
            )
            if (
                supply != int(identity["initial_usdc_supply"])
                or rider != supply
                or treasury != 0
            ):
                raise RuntimeError("setup USDC initial supply/balances do not reconcile")
        if stage in {"configured", "setup_ready"}:
            config = setup["setup_program_config"].get("decoded") or {}
            fields = config.get("fields") or {}
            if (
                fields.get("usdc_mint", fields.get("usdcMint"))
                != identity["usdc_mint"]
                or fields.get(
                    "usdc_treasury_token_account",
                    fields.get("usdcTreasuryTokenAccount"),
                )
                != identity["usdc_treasury"]
                or int(
                    fields.get(
                        "vault_creation_usdc", fields.get("vaultCreationUsdc", -1)
                    )
                )
                != int(identity["vault_creation_usdc"])
            ):
                raise RuntimeError("setup ProgramConfig USDC handoff is invalid")
