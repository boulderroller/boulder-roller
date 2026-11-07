"""
Transaction Builder Service

Builds unsigned Solana transactions for user signing.
Backend builds → returns serialized tx → frontend signs → submits.

This is the STEPN-style pattern where:
1. Backend has full context (PDAs, accounts, instruction data)
2. User wallet only needs to sign
3. Power users can still build client-side with IDL

Usage:
    from app.services.tx_builder import TxBuilder
    
    builder = TxBuilder()
    tx_data = await builder.build_stake_tx(user_wallet, vault_id, amount)
    # Returns: {"transaction": base64_tx, "blockhash": "...", "last_valid_block_height": N}
"""

from __future__ import annotations

import base64
import logging
import os
import struct
from dataclasses import dataclass
from typing import Optional

from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Confirmed, Finalized
from solders.hash import Hash
from solders.instruction import AccountMeta, Instruction
from solders.keypair import Keypair
from solders.message import Message
from solders.pubkey import Pubkey
from solders.transaction import Transaction

from ..solana_direct import (
    DirectConfig,
    _derive_user_pda,
    _derive_vault_pda,
    _derive_vault_leaderboard_pda,
    _derive_vault_stake_pda,
    _derive_vault_lp_mint_pda,
    _derive_vault_activation_pda,
    _derive_vault_cal_escrow_pda,
    _derive_local_legend_pda,
    _derive_dung_mint_state_pda,
    _derive_dung_mint_auth_pda,
    _derive_program_config_pda,
    _derive_ata,
    _derive_vault_counter_pda,
    _derive_rider_balance_token_pda,
    _discriminator,
    _get_boulder_accounts_coder,
    TOKEN_PROGRAM_ID,
    DEFAULT_BOULDER_PROGRAM_ID,
    DEFAULT_CAL_MINT_ADDRESS,
    DEFAULT_DUNG_MINT_ADDRESS,
    make_create_vault_ix,
    make_create_vault_with_usdc_ix,
    make_create_ata_ix,
    make_initialize_vault_lp_mint_ix,
    make_initialize_vault_position_lp_ix,
    make_initialize_vault_cal_escrow_ix,
    make_stake_cal_in_vault_ix,
    make_unstake_cal_from_vault_ix,
    make_collect_stake_rewards_for_ix,
    make_spl_transfer_checked_ix,
    make_withdraw_to_wallet_ix,
    load_backend_authority_keypair,
    load_default_config,
    get_program_config_account,
    _unique_signers,
)
from ..solana_env import solana_rpc_url
from .solana_submit import (
    BlockhashExpiredError,
    TransactionConfirmationTimeout,
    TransactionExecutionError,
    confirm_signature_with_retry,
    guard_finalized_transaction,
    guard_prepared_transaction,
    guard_terminal_transaction,
    is_blockhash_valid_compat,
)

logger = logging.getLogger(__name__)

BALANCE_FUNDING_DECIMALS = {
    "CAL": 9,
    "USDC": 6,
    "DUNG": 9,
}
NULL_PUBKEY = str(Pubkey.default())


def _anchor_account_field(fields: dict[str, object], *names: str) -> object:
    for name in names:
        if name in fields:
            return fields[name]
    raise KeyError(names[0])


def _is_new_record_board(value: object) -> bool:
    if type(value).__name__ == "NewRecordBoard":
        return True
    return isinstance(value, str) and value in {"NewRecordBoard", "new_record_board"}


def _definitive_send_error(exc: Exception) -> object | None:
    """Extract a structured preflight/chain error from a Solana RPC exception."""
    for candidate in (exc, *exc.args):
        direct_error = getattr(candidate, "err", None)
        if direct_error is not None:
            return direct_error
        data = getattr(candidate, "data", None)
        data_error = getattr(data, "err", None)
        if data_error is not None:
            return data_error
    return None


@dataclass
class BuildTxResult:
    """Result from building an unsigned transaction."""
    transaction: str  # Base64-encoded serialized transaction
    blockhash: str
    last_valid_block_height: int
    message: str  # Human-readable description
    vault_id: Optional[int] = None
    pda: Optional[str] = None
    activation_pda: Optional[str] = None


@dataclass(frozen=True)
class FinalizedCanonReservationObservation:
    """Finalized proof required before an expired VaultCounter id is released."""

    slot: int
    block_height: int
    exact_source_unbound: bool = True
    vault_absent: bool = True
    activation_absent: bool = True


class SubmittedTransactionError(RuntimeError):
    """Base error for a wallet-signed transaction with a known signature."""

    def __init__(self, signature: str, message: str) -> None:
        self.signature = signature
        super().__init__(message)


class SubmittedTransactionFailed(SubmittedTransactionError):
    """The signature has an authoritative chain execution error."""


class SubmittedTransactionExpired(SubmittedTransactionError):
    """The signature remained absent after its blockhash expired."""


class SubmittedTransactionPending(SubmittedTransactionError):
    """Submission may have been accepted but confirmation is still ambiguous."""


class TxBuilder:
    """
    Builds unsigned transactions for user signing.

    The backend partially signs with the configured fee payer and backend
    sponsor when required. The frontend only needs to add the user's signature.
    """
    
    def __init__(
        self,
        rpc_url: Optional[str] = None,
        program_id: Optional[Pubkey] = None,
        dung_mint: Optional[Pubkey] = None,
        cal_mint: Optional[Pubkey] = None,
        fee_payer: Optional[Keypair] = None,
        backend_authority: Optional[Keypair] = None,
        protocol_treasury: Optional[Pubkey] = None,
    ):
        config = load_default_config()
        self.rpc_url = rpc_url or config.rpc_url or solana_rpc_url()
        self.program_id = program_id or config.program_id or DEFAULT_BOULDER_PROGRAM_ID
        self.dung_mint = dung_mint or config.dung_mint_address or DEFAULT_DUNG_MINT_ADDRESS
        self.cal_mint = cal_mint or config.cal_mint_address or DEFAULT_CAL_MINT_ADDRESS
        self.fee_payer = fee_payer or config.payer
        self.backend_authority = (
            backend_authority
            or config.backend_authority
            or load_backend_authority_keypair()
        )

        protocol_treasury_key = protocol_treasury
        if protocol_treasury_key is None:
            protocol_treasury_str = os.getenv("PROTOCOL_TREASURY_ACCOUNT")
            protocol_treasury_key = (
                Pubkey.from_string(protocol_treasury_str)
                if protocol_treasury_str
                else None
            )
        self.protocol_treasury = protocol_treasury_key

    def _direct_config(self) -> DirectConfig:
        return DirectConfig(
            rpc_url=self.rpc_url,
            program_id=self.program_id,
            payer=self.fee_payer,
            backend_authority=self.backend_authority,
            dung_mint_address=self.dung_mint,
            cal_mint_address=self.cal_mint,
        )

    async def get_finalized_block_height(self) -> int:
        """Return a finalized height suitable for transaction-expiry decisions."""
        async with AsyncClient(self.rpc_url, commitment=Finalized) as client:
            response = await client.get_block_height(commitment=Finalized)
        block_height = response.value
        if isinstance(block_height, bool) or not isinstance(block_height, int) or block_height < 0:
            raise ValueError("finalized block height is unavailable")
        return block_height

    async def observe_finalized_canon_reservation_absence(
        self,
        *,
        climb_pda: str,
        vault_pda: str,
        vault_activation_pda: str,
        canon_commitment_hex: str,
        commitment_hash_hex: str,
    ) -> FinalizedCanonReservationObservation:
        """Prove an expired constructor never bound its exact source Climb."""
        expected_commitment = bytes.fromhex(canon_commitment_hex)
        expected_hash = bytes.fromhex(commitment_hash_hex)
        if len(expected_commitment) != 64 or len(expected_hash) != 32:
            raise ValueError("canonical reservation commitment is invalid")
        pubkeys = [
            Pubkey.from_string(climb_pda),
            Pubkey.from_string(vault_pda),
            Pubkey.from_string(vault_activation_pda),
        ]
        async with AsyncClient(self.rpc_url, commitment=Finalized) as client:
            height_response = await client.get_block_height(commitment=Finalized)
            accounts_response = await client.get_multiple_accounts(
                pubkeys,
                commitment=Finalized,
            )
        block_height = height_response.value
        if isinstance(block_height, bool) or not isinstance(block_height, int) or block_height < 0:
            raise ValueError("finalized block height is unavailable")
        accounts = list(accounts_response.value or [])
        slot = int(accounts_response.context.slot)
        if len(accounts) != 3 or slot < 0:
            raise ValueError("finalized canonical reservation accounts are unavailable")
        climb_account, vault_account, activation_account = accounts
        if vault_account is not None or activation_account is not None:
            raise ValueError("reserved Vault or VaultActivation exists on-chain")
        if climb_account is None or climb_account.owner != self.program_id:
            raise ValueError("exact source Climb is unavailable on-chain")
        decoded = _get_boulder_accounts_coder().parse(bytes(climb_account.data))
        if decoded.name != "Climb":
            raise ValueError("reserved source account is not a Climb")
        fields = vars(decoded.data)
        commitment = bytes(
            _anchor_account_field(fields, "canonCommitment", "canon_commitment")
        )
        commitment_hash = bytes(
            _anchor_account_field(fields, "commitmentHash", "commitment_hash")
        )
        bound_vault = _anchor_account_field(fields, "vault")
        continuity_policy = _anchor_account_field(
            fields,
            "recordContinuityPolicy",
            "record_continuity_policy",
        )
        if (
            commitment != expected_commitment
            or commitment_hash != expected_hash
            or bound_vault != Pubkey.default()
            or not _is_new_record_board(continuity_policy)
        ):
            raise ValueError("exact source Climb changed or is already bound")
        return FinalizedCanonReservationObservation(
            slot=slot,
            block_height=block_height,
        )

    async def _resolve_program_config(self) -> Optional[dict]:
        return await get_program_config_account(self._direct_config())

    @staticmethod
    def _configured_pubkey(value: object) -> Optional[Pubkey]:
        if value is None:
            return None
        value_str = str(value)
        if not value_str or value_str == NULL_PUBKEY:
            return None
        return Pubkey.from_string(value_str)

    async def _resolve_protocol_treasury(self) -> Optional[Pubkey]:
        """
        Resolve the canonical treasury token account.

        V4-A treats ProgramConfig as the source of truth for payout destinations.
        Keep the env var as a compatibility fallback only.
        """
        if self.protocol_treasury is not None:
            return self.protocol_treasury

        program_config = await self._resolve_program_config()
        treasury_token_account = program_config.get("treasury_token_account") if program_config else None
        treasury = self._configured_pubkey(treasury_token_account)
        if treasury is not None:
            return treasury

        return None

    async def _resolve_usdc_mint(self, explicit_usdc_mint: Optional[str] = None) -> Pubkey:
        """Resolve the USDC mint from ProgramConfig, with explicit test override."""
        explicit = self._configured_pubkey(explicit_usdc_mint)
        if explicit is not None:
            return explicit

        program_config = await self._resolve_program_config()
        usdc_mint = (
            self._configured_pubkey(program_config.get("usdc_mint"))
            if program_config
            else None
        )
        if usdc_mint is None:
            raise ValueError("ProgramConfig USDC mint not configured")
        return usdc_mint

    async def _resolve_usdc_payment_config(
        self,
        *,
        explicit_usdc_mint: Optional[str] = None,
        explicit_protocol_usdc_account: Optional[str] = None,
    ) -> tuple[Pubkey, Pubkey]:
        """Resolve CAL+USDC vault creation payment accounts from ProgramConfig."""
        explicit_mint = self._configured_pubkey(explicit_usdc_mint)
        explicit_treasury = self._configured_pubkey(explicit_protocol_usdc_account)
        if explicit_mint is not None and explicit_treasury is not None:
            return explicit_mint, explicit_treasury

        program_config = await self._resolve_program_config()
        usdc_mint = explicit_mint
        protocol_usdc = explicit_treasury
        if program_config:
            usdc_mint = usdc_mint or self._configured_pubkey(program_config.get("usdc_mint"))
            protocol_usdc = protocol_usdc or self._configured_pubkey(
                program_config.get("usdc_treasury_token_account")
            )

        missing: list[str] = []
        if usdc_mint is None:
            missing.append("USDC mint")
        if protocol_usdc is None:
            missing.append("USDC treasury token account")
        if missing:
            raise ValueError(f"ProgramConfig {' and '.join(missing)} not configured")
        return usdc_mint, protocol_usdc
    
    async def _get_recent_blockhash(self) -> tuple[Hash, int]:
        """Get recent blockhash and last valid block height."""
        async with AsyncClient(self.rpc_url, commitment=Confirmed) as client:
            result = await client.get_latest_blockhash()
            return result.value.blockhash, result.value.last_valid_block_height
    
    async def _check_ata_exists(self, owner: Pubkey, mint: Pubkey) -> bool:
        """Check if an ATA exists."""
        ata = _derive_ata(owner, mint)
        async with AsyncClient(self.rpc_url, commitment=Confirmed) as client:
            result = await client.get_account_info(ata)
            return result.value is not None

    async def _check_account_exists(self, address: Pubkey) -> bool:
        """Check if an arbitrary account exists."""
        async with AsyncClient(self.rpc_url, commitment=Confirmed) as client:
            result = await client.get_account_info(address)
            return result.value is not None

    async def _get_token_account_balance(self, address: Pubkey) -> int:
        """Return an SPL token account balance in base units."""
        async with AsyncClient(self.rpc_url, commitment=Confirmed) as client:
            result = await client.get_token_account_balance(address)
            return int(result.value.amount)

    def _build_unsigned_tx(
        self,
        fee_payer: Pubkey,
        instructions: list[Instruction],
        blockhash: Hash,
        partial_signers: Optional[list[Keypair]] = None,
    ) -> bytes:
        """Build an unsigned transaction and return serialized bytes."""
        message = Message.new_with_blockhash(
            instructions,
            fee_payer,
            blockhash,
        )
        tx = Transaction.new_unsigned(message)
        if partial_signers:
            tx.partial_sign(partial_signers, blockhash)
        return bytes(tx)

    @staticmethod
    def decode_signed_transaction(transaction_b64: str) -> Transaction:
        """Deserialize and verify a signed transaction."""
        tx = Transaction.from_bytes(base64.b64decode(transaction_b64))
        tx.verify()
        return tx

    def check_signed_transaction_before_send(self, tx) -> None:
        """Optional builder-specific admission after the last preflight await."""

    async def submit_signed_transaction(
        self,
        transaction_b64: str,
        *,
        last_valid_block_height: int,
    ) -> str:
        """Submit and reconcile a fully signed transaction through confirmation."""
        if isinstance(last_valid_block_height, bool) or last_valid_block_height <= 0:
            raise ValueError("last_valid_block_height must be a positive integer")

        tx = self.decode_signed_transaction(transaction_b64)
        prepared_signature = str(tx.signatures[0])
        recent_blockhash = tx.message.recent_blockhash
        evidence_metadata = {
            "tx_type": "wallet_signed",
            "attempt": 0,
            "commitment": "confirmed",
            "recent_blockhash": str(recent_blockhash),
            "last_valid_block_height": int(last_valid_block_height),
        }
        guard_prepared_transaction(tx, (), evidence_metadata)

        async with AsyncClient(self.rpc_url, commitment=Confirmed) as client:
            existing_status = None
            try:
                statuses = await client.get_signature_statuses(
                    [tx.signatures[0]],
                    search_transaction_history=True,
                )
                existing_status = statuses.value[0] if statuses.value else None
            except Exception:
                logger.warning(
                    "[TxBuilder] Pre-submit signature lookup failed for %s",
                    prepared_signature,
                    exc_info=True,
                )

            should_send = existing_status is None
            if should_send:
                try:
                    block_height = await client.get_block_height(commitment=Confirmed)
                    blockhash_valid = await is_blockhash_valid_compat(
                        client,
                        recent_blockhash,
                        commitment=Confirmed,
                    )
                    if (
                        block_height.value > last_valid_block_height
                        or not bool(blockhash_valid.value)
                    ):
                        await confirm_signature_with_retry(
                            client=client,
                            signature=tx.signatures[0],
                            commitment_obj=Confirmed,
                            commitment_str="confirmed",
                            last_valid_block_height=last_valid_block_height,
                            tx_type="wallet_signed",
                            recent_blockhash=recent_blockhash,
                        )
                        should_send = False
                except TransactionExecutionError as exc:
                    guard_terminal_transaction(
                        prepared_signature,
                        "failed",
                        {**evidence_metadata, "error": str(exc)},
                    )
                    raise SubmittedTransactionFailed(
                        prepared_signature,
                        f"wallet transaction failed: {exc}",
                    ) from exc
                except BlockhashExpiredError as exc:
                    guard_terminal_transaction(
                        prepared_signature,
                        "expired",
                        {**evidence_metadata, "error": str(exc)},
                    )
                    raise SubmittedTransactionExpired(
                        prepared_signature,
                        f"wallet transaction expired: {exc}",
                    ) from exc
                except TransactionConfirmationTimeout as exc:
                    raise SubmittedTransactionPending(
                        prepared_signature,
                        f"wallet transaction confirmation is pending: {exc}",
                    ) from exc
                except SubmittedTransactionError:
                    raise
                except Exception:
                    logger.warning(
                        "[TxBuilder] Pre-submit expiry check failed for %s",
                        prepared_signature,
                        exc_info=True,
                    )

            if should_send:
                # Outside the send exception handler: no bytes have been sent.
                self.check_signed_transaction_before_send(tx)
                try:
                    resp = await client.send_raw_transaction(bytes(tx))
                    rpc_signature = str(resp.value)
                    if rpc_signature != prepared_signature:
                        raise SubmittedTransactionPending(
                            prepared_signature,
                            "RPC returned a signature that did not match the signed transaction",
                        )
                except SubmittedTransactionPending:
                    raise
                except Exception as exc:
                    chain_error = _definitive_send_error(exc)
                    if chain_error is not None:
                        guard_terminal_transaction(
                            prepared_signature,
                            "failed",
                            {**evidence_metadata, "error": str(chain_error)},
                        )
                        raise SubmittedTransactionFailed(
                            prepared_signature,
                            f"wallet transaction failed: {chain_error}",
                        ) from exc
                    logger.warning(
                        "[TxBuilder] Send response ambiguous for %s: %s",
                        prepared_signature,
                        exc,
                    )

            try:
                confirmation = await confirm_signature_with_retry(
                    client=client,
                    signature=tx.signatures[0],
                    commitment_obj=Confirmed,
                    commitment_str="confirmed",
                    last_valid_block_height=last_valid_block_height,
                    tx_type="wallet_signed",
                    recent_blockhash=recent_blockhash,
                )
            except TransactionExecutionError as exc:
                guard_terminal_transaction(
                    prepared_signature,
                    "failed",
                    {**evidence_metadata, "error": str(exc)},
                )
                raise SubmittedTransactionFailed(
                    prepared_signature,
                    f"wallet transaction failed: {exc}",
                ) from exc
            except BlockhashExpiredError as exc:
                guard_terminal_transaction(
                    prepared_signature,
                    "expired",
                    {**evidence_metadata, "error": str(exc)},
                )
                raise SubmittedTransactionExpired(
                    prepared_signature,
                    f"wallet transaction expired: {exc}",
                ) from exc
            except TransactionConfirmationTimeout as exc:
                raise SubmittedTransactionPending(
                    prepared_signature,
                    f"wallet transaction confirmation is pending: {exc}",
                ) from exc
            except SubmittedTransactionError:
                raise
            except Exception as exc:
                raise SubmittedTransactionPending(
                    prepared_signature,
                    f"wallet transaction confirmation is pending: {exc}",
                ) from exc

            slot = getattr(confirmation, "slot", None)
            guard_finalized_transaction(
                prepared_signature,
                int(slot) if slot is not None else None,
                "confirmed",
                evidence_metadata,
            )
            return prepared_signature
    
    async def build_stake_tx(
        self,
        user_wallet: str,
        vault_id: int,
        amount: int,
        blockhash: Optional[Hash] = None,
    ) -> BuildTxResult:
        """
        Build stake_cal_in_vault transaction.
        
        Args:
            user_wallet: User's wallet address
            vault_id: Vault ID to stake in
            amount: CAL amount to stake
            
        Returns:
            BuildTxResult with base64 transaction
        """
        user = Pubkey.from_string(user_wallet)
        vault_lp_mint, _ = _derive_vault_lp_mint_pda(vault_id, self.program_id)
        vault_cal_escrow, _ = _derive_vault_cal_escrow_pda(vault_id, self.program_id)

        instructions: list[Instruction] = []

        if not await self._check_account_exists(vault_lp_mint):
            instructions.append(
                make_initialize_vault_lp_mint_ix(
                    payer=self.fee_payer.pubkey(),
                    vault_id=vault_id,
                    program_id=self.program_id,
                )
            )

        if not await self._check_account_exists(vault_cal_escrow):
            instructions.append(
                make_initialize_vault_cal_escrow_ix(
                    payer=self.fee_payer.pubkey(),
                    vault_id=vault_id,
                    cal_mint=self.cal_mint,
                    program_id=self.program_id,
                )
            )

        instructions.append(
            make_initialize_vault_position_lp_ix(
                sponsor_authority=self.backend_authority.pubkey(),
                rider=user,
                vault_id=vault_id,
                program_id=self.program_id,
            )
        )

        if not await self._check_ata_exists(user, self.cal_mint):
            raise ValueError("Staker has no CAL token account")

        instructions.append(
            make_stake_cal_in_vault_ix(
                sponsor_authority=self.backend_authority.pubkey(),
                staker=user,
                vault_id=vault_id,
                amount=amount,
                cal_mint=self.cal_mint,
                program_id=self.program_id,
            )
        )

        if blockhash is None:
            blockhash, last_valid = await self._get_recent_blockhash()
        else:
            _, last_valid = await self._get_recent_blockhash()
        tx_bytes = self._build_unsigned_tx(
            self.fee_payer.pubkey(),
            instructions,
            blockhash,
            partial_signers=_unique_signers(self.fee_payer, self.backend_authority),
        )

        return BuildTxResult(
            transaction=base64.b64encode(tx_bytes).decode('utf-8'),
            blockhash=str(blockhash),
            last_valid_block_height=last_valid,
            message=f"Stake {amount} CAL in vault {vault_id}",
        )
    
    async def build_unstake_tx(
        self,
        user_wallet: str,
        vault_id: int,
        lp_amount: int,
        blockhash: Optional[Hash] = None,
        collect_rewards: bool = False,
    ) -> BuildTxResult:
        """
        Build unstake_cal_from_vault transaction.

        When ``collect_rewards`` is True the transaction composes the
        permissionless-for-rider ``collect_stake_rewards_for`` instruction
        BEFORE the unstake in the same atomic transaction, so a withdraw can
        never leave pending DUNG behind (protocol rule: collect first).
        Callers must only request composition when the on-chain
        ``VaultStake.rewards_earned`` is positive — the collect instruction
        fails the whole transaction on a zero balance.

        Args:
            user_wallet: User's wallet address
            vault_id: Vault ID to unstake from
            lp_amount: Exact LP base units to burn (returns proportional CAL)
            collect_rewards: Prepend collect_stake_rewards_for atomically

        Returns:
            BuildTxResult with base64 transaction
        """
        user = Pubkey.from_string(user_wallet)
        instructions: list[Instruction] = []

        if collect_rewards:
            protocol_treasury = await self._resolve_protocol_treasury()
            if protocol_treasury is None:
                raise ValueError("PROTOCOL_TREASURY_ACCOUNT not configured")
            if not await self._check_ata_exists(user, self.dung_mint):
                instructions.append(
                    make_create_ata_ix(
                        payer=self.fee_payer.pubkey(),
                        owner=user,
                        mint=self.dung_mint,
                    )
                )
            instructions.append(
                make_collect_stake_rewards_for_ix(
                    staker=user,
                    payer=self.fee_payer.pubkey(),
                    vault_id=vault_id,
                    protocol_treasury=protocol_treasury,
                    dung_mint=self.dung_mint,
                    program_id=self.program_id,
                )
            )

        if not await self._check_ata_exists(user, self.cal_mint):
            instructions.append(
                make_create_ata_ix(
                    payer=self.fee_payer.pubkey(),
                    owner=user,
                    mint=self.cal_mint,
                )
            )

        instructions.append(
            make_unstake_cal_from_vault_ix(
                staker=user,
                vault_id=vault_id,
                lp_amount=lp_amount,
                cal_mint=self.cal_mint,
                program_id=self.program_id,
            )
        )

        if blockhash is None:
            blockhash, last_valid = await self._get_recent_blockhash()
        else:
            _, last_valid = await self._get_recent_blockhash()
        tx_bytes = self._build_unsigned_tx(
            self.fee_payer.pubkey(),
            instructions,
            blockhash,
            partial_signers=[self.fee_payer],
        )

        return BuildTxResult(
            transaction=base64.b64encode(tx_bytes).decode('utf-8'),
            blockhash=str(blockhash),
            last_valid_block_height=last_valid,
            message=(
                f"Collect DUNG and withdraw CAL from vault {vault_id}"
                if collect_rewards
                else f"Withdraw CAL from vault {vault_id}"
            ),
        )
    
    async def build_harvest_tx(
        self,
        user_wallet: str,
        vault_id: int,
        blockhash: Optional[Hash] = None,
    ) -> BuildTxResult:
        """
        Build collect_stake_rewards_for transaction.
        
        Claims pending DUNG rewards without unstaking CAL.
        
        Args:
            user_wallet: User's wallet address
            vault_id: Vault ID to harvest from
            
        Returns:
            BuildTxResult with base64 transaction
        """
        protocol_treasury = await self._resolve_protocol_treasury()
        if protocol_treasury is None:
            raise ValueError("PROTOCOL_TREASURY_ACCOUNT not configured")

        user = Pubkey.from_string(user_wallet)
        destination_ata = _derive_ata(user, self.dung_mint)

        instructions: list[Instruction] = []

        if not await self._check_ata_exists(user, self.dung_mint):
            instructions.append(
                make_create_ata_ix(
                    payer=self.fee_payer.pubkey(),
                    owner=user,
                    mint=self.dung_mint,
                )
            )

        instructions.append(
            make_collect_stake_rewards_for_ix(
                staker=user,
                payer=self.fee_payer.pubkey(),
                vault_id=vault_id,
                protocol_treasury=protocol_treasury,
                dung_mint=self.dung_mint,
                program_id=self.program_id,
            )
        )

        if blockhash is None:
            blockhash, last_valid = await self._get_recent_blockhash()
        else:
            _, last_valid = await self._get_recent_blockhash()
        tx_bytes = self._build_unsigned_tx(
            self.fee_payer.pubkey(),
            instructions,
            blockhash,
            partial_signers=[self.fee_payer],
        )

        return BuildTxResult(
            transaction=base64.b64encode(tx_bytes).decode('utf-8'),
            blockhash=str(blockhash),
            last_valid_block_height=last_valid,
            message=f"Collect DUNG from vault {vault_id}",
            pda=str(destination_ata),
        )

    async def _balance_asset_mint(self, asset: str) -> tuple[Pubkey, int]:
        normalized_asset = asset.strip().upper()
        if normalized_asset == "CAL":
            return self.cal_mint, BALANCE_FUNDING_DECIMALS["CAL"]
        if normalized_asset == "DUNG":
            return self.dung_mint, BALANCE_FUNDING_DECIMALS["DUNG"]
        if normalized_asset == "USDC":
            return await self._resolve_usdc_mint(), BALANCE_FUNDING_DECIMALS["USDC"]
        raise ValueError("Boulder Roller Balance supports CAL, USDC, and DUNG.")

    async def _balance_funding_mint(self, asset: str) -> tuple[Pubkey, int]:
        normalized_asset = asset.strip().upper()
        if normalized_asset not in ("CAL", "USDC"):
            raise ValueError("Add funds supports CAL and USDC.")
        return await self._balance_asset_mint(normalized_asset)

    async def build_add_funds_to_balance_tx(
        self,
        user_wallet: str,
        asset: str,
        amount: int,
        blockhash: Optional[Hash] = None,
    ) -> BuildTxResult:
        """Build a wallet-confirmed token transfer into Boulder Roller Balance."""
        if amount <= 0:
            raise ValueError("Amount must be positive.")

        normalized_asset = asset.strip().upper()
        mint, decimals = await self._balance_funding_mint(normalized_asset)
        user = Pubkey.from_string(user_wallet)
        source_token_account = _derive_ata(user, mint)
        rider_balance_token, _ = _derive_rider_balance_token_pda(
            user,
            mint,
            self.program_id,
        )

        if not await self._check_ata_exists(user, mint):
            raise ValueError(f"Wallet has no {normalized_asset} available.")
        if not await self._check_account_exists(rider_balance_token):
            raise ValueError(f"Set up {normalized_asset} in Boulder Roller Balance first.")

        transfer_ix = make_spl_transfer_checked_ix(
            source=source_token_account,
            mint=mint,
            destination=rider_balance_token,
            owner=user,
            amount=amount,
            decimals=decimals,
        )

        if blockhash is None:
            blockhash, last_valid = await self._get_recent_blockhash()
        else:
            _, last_valid = await self._get_recent_blockhash()
        tx_bytes = self._build_unsigned_tx(
            self.fee_payer.pubkey(),
            [transfer_ix],
            blockhash,
            partial_signers=[self.fee_payer],
        )

        return BuildTxResult(
            transaction=base64.b64encode(tx_bytes).decode("utf-8"),
            blockhash=str(blockhash),
            last_valid_block_height=last_valid,
            message=f"Add {normalized_asset} to Boulder Roller Balance",
            pda=str(rider_balance_token),
        )

    async def build_withdraw_to_wallet_tx(
        self,
        user_wallet: str,
        asset: str,
        amount: int,
        blockhash: Optional[Hash] = None,
    ) -> BuildTxResult:
        """Build a wallet-confirmed withdrawal from Boulder Roller Balance."""
        if amount <= 0:
            raise ValueError("Amount must be positive.")

        normalized_asset = asset.strip().upper()
        mint, _decimals = await self._balance_asset_mint(normalized_asset)
        user = Pubkey.from_string(user_wallet)
        rider_balance_source, _ = _derive_rider_balance_token_pda(
            user,
            mint,
            self.program_id,
        )
        rider_wallet_destination = _derive_ata(user, mint)

        if not await self._check_account_exists(rider_balance_source):
            raise ValueError(f"Set up {normalized_asset} in Boulder Roller Balance first.")
        balance_base_units = await self._get_token_account_balance(rider_balance_source)
        if balance_base_units < amount:
            raise ValueError(f"Not enough {normalized_asset} in Boulder Roller Balance.")

        instructions: list[Instruction] = []
        if not await self._check_ata_exists(user, mint):
            instructions.append(
                make_create_ata_ix(
                    payer=self.fee_payer.pubkey(),
                    owner=user,
                    mint=mint,
                )
            )
        instructions.append(
            make_withdraw_to_wallet_ix(
                rider=user,
                mint=mint,
                amount=amount,
                program_id=self.program_id,
            )
        )

        if blockhash is None:
            blockhash, last_valid = await self._get_recent_blockhash()
        else:
            _, last_valid = await self._get_recent_blockhash()
        tx_bytes = self._build_unsigned_tx(
            self.fee_payer.pubkey(),
            instructions,
            blockhash,
            partial_signers=[self.fee_payer],
        )

        return BuildTxResult(
            transaction=base64.b64encode(tx_bytes).decode("utf-8"),
            blockhash=str(blockhash),
            last_valid_block_height=last_valid,
            message=f"Withdraw {normalized_asset} to wallet",
            pda=str(rider_balance_source),
        )
    
    async def build_create_vault_tx(
        self,
        user_wallet: str,
        climb_pda: str,
        display_name: str,
        blockhash: Optional[Hash] = None,
        last_valid_block_height: Optional[int] = None,
        vault_id: Optional[int] = None,
    ) -> BuildTxResult:
        """Build the DUNG constructor for one server-resolved V4-B Climb."""
        user = Pubkey.from_string(user_wallet)
        climb = Pubkey.from_string(climb_pda)
        
        vault_counter_pda, _ = _derive_vault_counter_pda(self.program_id)
        next_vault_id = vault_id
        if next_vault_id is None:
            async with AsyncClient(self.rpc_url, commitment=Confirmed) as client:
                account_info = await client.get_account_info(vault_counter_pda)
                if account_info.value is None:
                    raise ValueError("VaultCounter not initialized")
                data = bytes(account_info.value.data)
                next_vault_id = struct.unpack_from("<Q", data, 8)[0]

        vault_pda, _ = _derive_vault_pda(next_vault_id, self.program_id)
        vault_leaderboard_pda, _ = _derive_vault_leaderboard_pda(
            next_vault_id, self.program_id
        )
        local_legend_pda, _ = _derive_local_legend_pda(next_vault_id, self.program_id)
        vault_activation_pda, _ = _derive_vault_activation_pda(next_vault_id, self.program_id)
        user_dung_account = _derive_ata(user, self.dung_mint)

        if not await self._check_ata_exists(user, self.dung_mint):
            raise ValueError("Creator has no DUNG token account")
        
        create_ix = make_create_vault_ix(
            sponsor_authority=self.backend_authority.pubkey(),
            creator=user,
            creator_dung_account=user_dung_account,
            dung_mint=self.dung_mint,
            vault_counter_pda=vault_counter_pda,
            vault_pda=vault_pda,
            climb_pda=climb,
            vault_leaderboard_pda=vault_leaderboard_pda,
            local_legend_pda=local_legend_pda,
            vault_activation_pda=vault_activation_pda,
            program_id=self.program_id,
        )

        if blockhash is None:
            blockhash, last_valid = await self._get_recent_blockhash()
        else:
            if last_valid_block_height is None or last_valid_block_height <= 0:
                raise ValueError(
                    "last_valid_block_height is required with an existing blockhash"
                )
            last_valid = last_valid_block_height
        tx_bytes = self._build_unsigned_tx(
            self.fee_payer.pubkey(),
            [create_ix],
            blockhash,
            partial_signers=_unique_signers(self.fee_payer, self.backend_authority),
        )

        return BuildTxResult(
            transaction=base64.b64encode(tx_bytes).decode('utf-8'),
            blockhash=str(blockhash),
            last_valid_block_height=last_valid,
            message=f"Create Vault for {display_name}",
            vault_id=next_vault_id,
            pda=str(vault_pda),
            activation_pda=str(vault_activation_pda),
        )
    
    async def build_create_vault_with_usdc_tx(
        self,
        user_wallet: str,
        climb_pda: str,
        display_name: str,
        blockhash: Optional[Hash] = None,
        last_valid_block_height: Optional[int] = None,
        vault_id: Optional[int] = None,
        usdc_mint: Optional[str] = None,
        protocol_usdc_account: Optional[str] = None,
    ) -> BuildTxResult:
        """Build the CAL+USDC constructor for one server-resolved V4-B Climb."""
        user = Pubkey.from_string(user_wallet)
        climb = Pubkey.from_string(climb_pda)
        usdc_mint_pubkey, protocol_usdc = await self._resolve_usdc_payment_config(
            explicit_usdc_mint=usdc_mint,
            explicit_protocol_usdc_account=protocol_usdc_account,
        )

        vault_counter_pda, _ = _derive_vault_counter_pda(self.program_id)
        next_vault_id = vault_id
        if next_vault_id is None:
            async with AsyncClient(self.rpc_url, commitment=Confirmed) as client:
                account_info = await client.get_account_info(vault_counter_pda)
                if account_info.value is None:
                    raise ValueError("VaultCounter not initialized")
                data = bytes(account_info.value.data)
                next_vault_id = struct.unpack_from("<Q", data, 8)[0]

        # Derive PDAs
        vault_pda, _ = _derive_vault_pda(next_vault_id, self.program_id)
        vault_leaderboard_pda, _ = _derive_vault_leaderboard_pda(
            next_vault_id, self.program_id
        )
        local_legend_pda, _ = _derive_local_legend_pda(next_vault_id, self.program_id)
        vault_activation_pda, _ = _derive_vault_activation_pda(next_vault_id, self.program_id)
        user_usdc_account = _derive_ata(user, usdc_mint_pubkey)
        user_cal_account = _derive_ata(user, self.cal_mint)

        if not await self._check_ata_exists(user, self.cal_mint):
            raise ValueError("Creator has no CAL token account")
        if not await self._check_ata_exists(user, usdc_mint_pubkey):
            raise ValueError("Creator has no USDC token account")

        create_ix = make_create_vault_with_usdc_ix(
            sponsor_authority=self.backend_authority.pubkey(),
            creator=user,
            creator_cal_account=user_cal_account,
            cal_mint=self.cal_mint,
            creator_usdc_account=user_usdc_account,
            protocol_usdc_account=protocol_usdc,
            vault_counter_pda=vault_counter_pda,
            vault_pda=vault_pda,
            climb_pda=climb,
            vault_leaderboard_pda=vault_leaderboard_pda,
            local_legend_pda=local_legend_pda,
            vault_activation_pda=vault_activation_pda,
            program_id=self.program_id,
        )

        if blockhash is None:
            blockhash, last_valid = await self._get_recent_blockhash()
        else:
            if last_valid_block_height is None or last_valid_block_height <= 0:
                raise ValueError(
                    "last_valid_block_height is required with an existing blockhash"
                )
            last_valid = last_valid_block_height
        tx_bytes = self._build_unsigned_tx(
            self.fee_payer.pubkey(),
            [create_ix],
            blockhash,
            partial_signers=_unique_signers(self.fee_payer, self.backend_authority),
        )

        return BuildTxResult(
            transaction=base64.b64encode(tx_bytes).decode('utf-8'),
            blockhash=str(blockhash),
            last_valid_block_height=last_valid,
            message=f"Create Vault for {display_name} with CAL + USDC",
            vault_id=next_vault_id,
            pda=str(vault_pda),
            activation_pda=str(vault_activation_pda),
        )


# Singleton instance
_builder: Optional[TxBuilder] = None


def get_tx_builder() -> TxBuilder:
    """Get or create the singleton TxBuilder instance."""
    global _builder
    if _builder is None:
        _builder = TxBuilder()
    return _builder
