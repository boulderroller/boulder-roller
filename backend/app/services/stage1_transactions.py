"""Owner-signed Stage 1 transactions for the release-pinned 0x4E ABI.

The fee payer sponsors fees and recipient registration. Owners fund pledge,
notice and exit accounts; self-claim and withdrawal ATA creation is owner-paid.
No arbitrary instructions, accounts, recipient or wallet come from a request.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import re
import struct
import time
from copy import copy

from anchorpy import Idl
from anchorpy.coder.coder import Coder
from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Confirmed
from solders.instruction import AccountMeta, Instruction
from solders.pubkey import Pubkey
from solders.address_lookup_table_account import AddressLookupTable, AddressLookupTableAccount
from solders.message import Message, MessageV0, to_bytes_versioned
from solders.transaction import Transaction, VersionedTransaction
from solders.hash import Hash
from solders.signature import Signature
from solders.system_program import create_lookup_table, extend_lookup_table, deactivate_lookup_table, close_lookup_table

from .. import solana_direct
from ..generated_program_version import PROGRAM_ABI_SHA256
from .stage1_keeper_abi import cash_terms
from .stage1_keeper_chain import normal
from .stage1_keeper_paths import IDL
from .tx_builder import BuildTxResult, TxBuilder

ABI = "c0811f476ca9deaf5942e574588bbd68181d701cdc5bfc1719e6fc27a18cd441"
SYSTEM = Pubkey.default()
TOKEN = solana_direct.TOKEN_PROGRAM_ID
ASSOCIATED_TOKEN = Pubkey.from_string("ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL")
RENT = Pubkey.from_string("SysvarRent111111111111111111111111111111111")
LOOKUP = Pubkey.from_string("AddressLookupTab1e1111111111111111111111111")
CLOCK = Pubkey.from_string("SysvarC1ock11111111111111111111111111111111")
ASSET_ACCOUNT_SIZE = 367  # IDL layout unchanged since 0x4D, including discriminator.
SPONSOR_CASH_ADAPTER = 254  # No staking slot; its zero `slot` is not a provider.


def key(value):
    return value if isinstance(value, Pubkey) else Pubkey.from_string(value)


def unpack(value):
    return json.loads(value) if isinstance(value, str) else value


def snake(value):
    return re.sub(r"(?<!^)(?=[A-Z])", "_", value).lower()


class Stage1LookupRequired(ValueError):
    pass


class Stage1WithdrawalPaused(ValueError):
    def __init__(self, retry_at):
        super().__init__('Stage 1 withdrawal pause')
        self.retry_at = retry_at


def withdrawal_pause_until(now=None):
    # Finalized CLOCK trails execution; use server UTC for this safety window.
    now = time.time() if now is None else now
    utc = datetime.fromtimestamp(now, timezone.utc)
    if utc.weekday() == 0 and utc.hour == 12 and utc.minute == 0:
        return int(now) - utc.second + 60
    return None


def require_withdrawal_window(action):
    if action in ('begin-withdrawal', 'complete-withdrawal'):
        retry_at = withdrawal_pause_until()
        if retry_at is not None:
            raise Stage1WithdrawalPaused(retry_at)


def require_pinned_abi(idl):
    def strip(value):
        if isinstance(value, dict):
            return {k: strip(v) for k, v in value.items() if k not in ("docs", "msg", "metadata")}
        if isinstance(value, list):
            return [strip(v) for v in value]
        return value
    surface = {"name": idl.get("name"), **{name: sorted(idl.get(name, []), key=lambda v: v["name"])
                for name in ("instructions", "accounts", "types", "events")},
               "errors": sorted(idl.get("errors", []), key=lambda v: v["code"])}
    digest = hashlib.sha256((json.dumps(strip(surface), indent=2, sort_keys=True, ensure_ascii=True) + "\n").encode()).hexdigest()
    if PROGRAM_ABI_SHA256 != ABI or digest != ABI:
        raise ValueError("Stage 1 transaction ABI changed")


@dataclass
class Stage1Plan:
    instructions: list[Instruction]
    asset: str
    amount: int
    source: str
    destination: str
    reference: str
    rent_payer: str
    intent: dict | None = None
    lookup: AddressLookupTableAccount | None = None


class Stage1TxBuilder(TxBuilder):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.idl = json.loads(IDL.read_text())
        require_pinned_abi(self.idl)
        self.coder = Coder(Idl.from_json(json.dumps(self.idl)))

    def pda(self, seed, *parts):
        return Pubkey.find_program_address([seed.encode(), *parts], self.program_id)[0]

    def ix(self, name, args, addresses, remaining=()):
        spec = next(i for i in self.idl["instructions"] if snake(i["name"]) == name)
        def flatten(accounts):
            result = []
            for account in accounts:
                if "accounts" in account:
                    result.extend(flatten(account["accounts"]))
                else:
                    result.append(AccountMeta(key(addresses[snake(account["name"])]), account["isSigner"], account["isMut"]))
            return result
        return Instruction(self.program_id, self.coder.instruction.encode(name, args), flatten(spec["accounts"]) + list(remaining))

    async def require_enabled_chain(self):
        # This rereads the chain and uses the existing durable version window.
        return await solana_direct.get_stage1_program_config_account(self._direct_config())

    async def genesis(self):
        async with AsyncClient(self.rpc_url) as client:
            return str((await client.get_genesis_hash()).value)

    async def raw_account(self, address):
        async with AsyncClient(self.rpc_url, commitment=Confirmed) as client:
            return (await client.get_account_info(key(address))).value

    def discovery_reader(self):
        # Only a single discovery request shares raw reads. Signing plans use
        # the original builder and always reread current chain state.
        observed = getattr(self, "observed_genesis", None)
        reader, accounts, network = copy(self), {}, [observed] if observed else []
        async def raw_account(address):
            address = str(address)
            if address not in accounts:
                accounts[address] = await self.raw_account(address)
            return accounts[address]
        async def genesis():
            if not network:
                network.append(await self.genesis())
            return network[0]
        reader.raw_account, reader.genesis = raw_account, genesis
        return reader

    async def account(self, address, kind, *, optional=False):
        account = await self.raw_account(address)
        if account is None and optional:
            return None
        discriminator = hashlib.sha256(f"account:{kind}".encode()).digest()[:8]
        if (account is None or account.owner != self.program_id or account.executable
                or bytes(account.data)[:8] != discriminator):
            raise ValueError("Stage 1 account unavailable")
        return normal(self.coder.accounts.decode(bytes(account.data)))

    async def clock(self):
        # Eligibility, preparation and reconstruction use the same commitment.
        async with AsyncClient(self.rpc_url) as rpc:
            row = (await rpc.get_account_info(CLOCK, commitment='finalized')).value
        if row is None or len(row.data) != 40:
            raise ValueError('Stage 1 clock unavailable')
        return struct.unpack_from('<q', row.data, 32)[0]

    async def finalized_success(self, signature):
        async with AsyncClient(self.rpc_url) as rpc:
            row = (await rpc.get_signature_statuses([Signature.from_string(signature)], search_transaction_history=True)).value[0]
        return row is not None and row.err is None and str(row.confirmation_status).lower().endswith('finalized')

    async def lookup_state(self, address, owner):
        async with AsyncClient(self.rpc_url) as rpc:
            response = await rpc.get_multiple_accounts([key(address), Pubkey.from_string('SysvarS1otHashes111111111111111111111111111')], commitment='finalized')
        row, history = response.value
        if row is None:
            return 'missing'
        if row.owner != LOOKUP or row.executable:
            raise ValueError('Stage 1 lookup unavailable')
        table = AddressLookupTable.deserialize(bytes(row.data))
        if table.meta.authority != owner:
            raise ValueError('Stage 1 lookup owner mismatch')
        deactivated = table.meta.deactivation_slot
        if deactivated == (1 << 64) - 1:
            return 'active'
        if history is None or len(history.data) < 8:
            raise ValueError('Stage 1 slot history unavailable')
        raw = bytes(history.data)
        count = struct.unpack_from('<Q', raw)[0]
        if len(raw) != 8 + count * 40:
            raise ValueError('Stage 1 slot history invalid')
        slots = {struct.unpack_from('<Q', raw, 8 + i * 40)[0] for i in range(count)}
        return 'cooling' if deactivated >= response.context.slot or deactivated in slots else 'closeable'

    def create_ata(self, owner, mint):
        destination = solana_direct._derive_ata(owner, mint)
        return Instruction(ASSOCIATED_TOKEN, b"\x01", [
            AccountMeta(owner, True, True), AccountMeta(destination, False, True),
            AccountMeta(owner, False, False), AccountMeta(mint, False, False),
            AccountMeta(SYSTEM, False, False), AccountMeta(TOKEN, False, False)])

    async def provider_accounts(self, asset):
        if asset["adapter"] == 1:
            return []
        return [AccountMeta(key(asset["provider_account"]), False, False),
                AccountMeta(key(asset["mint"]), False, False)]

    async def pledge_providers(self, city, hill, incoming):
        if hill["bonded"]:
            return await self.provider_accounts(incoming)
        # The program requires all backed provider slots, including disabled
        # assets, in slot order. Incoming asset/mint may repeat fixed accounts.
        from solana.rpc.types import MemcmpOpts
        import base58
        discriminator = hashlib.sha256(b"account:Stage1AssetConfig").digest()[:8]
        if not 0 <= city["asset_count"] <= 32:
            raise ValueError("Stage 1 provider inventory exceeds release slots")
        async with AsyncClient(self.rpc_url, commitment=Confirmed) as client:
            rows = (await client.get_program_accounts(self.program_id, encoding="base64", filters=[
                ASSET_ACCOUNT_SIZE,
                MemcmpOpts(offset=0, bytes=base58.b58encode(discriminator).decode()),
                MemcmpOpts(offset=9, bytes=str(self.pda("s1v1_city"))),
            ])).value
        if len(rows) > 33:
            raise ValueError("Stage 1 provider inventory exceeds release slots")
        assets, cash = [], 0
        for row in rows:
            data = bytes(row.account.data)
            if (row.account.owner != self.program_id or row.account.executable
                    or len(data) != ASSET_ACCOUNT_SIZE or data[:8] != discriminator):
                raise ValueError("Stage 1 provider inventory account mismatch")
            asset = normal(self.coder.accounts.decode(data))
            if (asset["city"] != str(self.pda("s1v1_city"))
                    or row.pubkey != self.pda("s1v1_asset", bytes(key(asset["mint"])))):
                raise ValueError("Stage 1 provider inventory identity mismatch")
            if asset["adapter"] == SPONSOR_CASH_ADAPTER:
                # The singleton cash asset shares the city filter but is never
                # a backed provider; the program rejects it in this list.
                cash += 1
                continue
            if not 0 <= asset["slot"] < city["asset_count"]:
                raise ValueError("Stage 1 provider inventory identity mismatch")
            assets.append(asset)
        if cash > 1 or len(assets) > 32:
            raise ValueError("Stage 1 provider inventory exceeds release slots")
        selected = sorted((a for a in assets if city["provider_slots"] & (1 << a["slot"])
                           and (hill["asset_lots"][a["slot"]] or a["slot"] == incoming["slot"])), key=lambda a: a["slot"])
        required = {slot for slot in range(city["asset_count"]) if city["provider_slots"] & (1 << slot)
                    and (hill["asset_lots"][slot] or slot == incoming["slot"])}
        if {a["slot"] for a in selected} != required or len(selected) != len(required):
            raise ValueError("Stage 1 provider inventory incomplete")
        result = []
        for asset in selected:
            result += [AccountMeta(self.pda("s1v1_asset", bytes(key(asset["mint"]))), False, True)]
            result += await self.provider_accounts(asset)
        return result

    async def funded_sweep(self, addresses, city, asset, *, chain_time=None):
        # Use the backend fee payer for shared weekly book rent. Idempotent
        # setup is always included, so account-creation races cannot broaden
        # the transaction reconstructed at submission.
        week = ((await self.clock() if chain_time is None else chain_time) - city["season_anchor"]) // 604800
        if week < 0:
            raise ValueError("Stage 1 season not started")
        hill, mint = addresses["hill"], key(asset["mint"])
        addresses.update(payer=self.fee_payer.pubkey(),
                         cursor=self.pda("s1v1_cursor", bytes(hill), bytes(mint)),
                         funding=self.pda("s1v1_funding", bytes(hill), bytes(mint), struct.pack("<Q", week)))
        before = [self.ix("init_stage1_settlement", {}, addresses),
                  self.ix("open_stage1_week", {"week": week}, addresses)]
        remaining = await self.provider_accounts(asset)
        remaining.append(AccountMeta(addresses["funding"], False, True))
        return before, remaining

    async def lookup_table(self, address, owner, *, active=True):
        async with AsyncClient(self.rpc_url) as rpc:
            response = await rpc.get_account_info(key(address), commitment="finalized")
        row = response.value
        if row is None or row.owner != LOOKUP or row.executable:
            raise ValueError("Stage 1 lookup unavailable")
        table = AddressLookupTable.deserialize(bytes(row.data))
        if table.meta.authority != owner:
            raise ValueError("Stage 1 lookup owner mismatch")
        if active and (table.meta.deactivation_slot != (1 << 64) - 1 or table.meta.last_extended_slot >= response.context.slot):
            raise ValueError("Stage 1 lookup inactive or warming up")
        return AddressLookupTableAccount(key(address), table.addresses)

    async def transport_plan(self, payload, owner, connection, addresses):
        if payload.mode == "create":
            if len(payload.claims) != 1 or payload.recent_slot is None or payload.lookup_table is not None:
                raise ValueError("One unpaid leaf and recent slot required")
            plan = await self.claim_plan(payload, owner, connection, addresses, single=True)
            keys = sorted({m.pubkey for ix in plan.instructions for m in ix.accounts if not m.is_signer and m.pubkey != owner}, key=bytes)
            create, address = create_lookup_table({"authority_address": owner, "payer_address": owner, "recent_slot": int(payload.recent_slot)})
            extend = extend_lookup_table({"lookup_table_address": address, "authority_address": owner, "payer_address": owner, "new_addresses": keys})
            intent = {"kind": "stage1_claim_transport", "mode": "create", "recentSlot": payload.recent_slot,
                      "lookupTable": str(address), "addresses": list(map(str, keys))}
            return Stage1Plan([create, extend], "SOL", 0, str(owner), str(owner), str(address), str(owner), intent)
        if payload.claims or not payload.lookup_table or payload.recent_slot is not None:
            raise ValueError("Lookup cleanup requires only the owned table")
        await self.lookup_table(payload.lookup_table, owner, active=False)
        args = {"lookup_table_address": key(payload.lookup_table), "authority_address": owner}
        ix = (deactivate_lookup_table(args) if payload.mode == "deactivate" else close_lookup_table({**args, "recipient_address": owner}))
        return Stage1Plan([ix], "SOL", 0, str(owner), str(owner), payload.lookup_table, str(owner),
            {"kind": "stage1_claim_transport", "mode": payload.mode, "lookupTable": payload.lookup_table})

    @staticmethod
    def decode_signed_transaction(transaction_b64):
        raw = base64.b64decode(transaction_b64, validate=True)
        tx = VersionedTransaction.from_bytes(raw)
        if bytes(tx) != raw or len(raw) > 1232 or not all(tx.verify_with_results()):
            raise ValueError("Invalid signed Stage 1 transaction")
        return tx

    @staticmethod
    def message_bytes(tx):
        return to_bytes_versioned(tx.message)

    def check_signed_transaction_before_send(self, tx):
        # Match only pinned Stage 1 instructions; other signed actions keep
        # their existing submission policy. No await may follow this check
        # before the transport's send_raw_transaction call.
        withdrawals = {hashlib.sha256(f'global:{name}'.encode()).digest()[:8]
                       for name in ('begin_withdrawal', 'complete_withdrawal')}
        for instruction in tx.message.instructions:
            if (tx.message.account_keys[instruction.program_id_index] == self.program_id
                    and bytes(instruction.data)[:8] in withdrawals):
                require_withdrawal_window('begin-withdrawal')

    async def plan(self, action, payload, wallet, connection=None, *, chain_time=None):
        require_withdrawal_window(action)
        if action in ('begin-withdrawal', 'complete-withdrawal') and chain_time is None:
            chain_time = await self.clock()
        owner = key(wallet)
        if owner in (SYSTEM, self.fee_payer.pubkey(), self.backend_authority.pubkey(), self.program_id):
            raise ValueError("Invalid Stage 1 owner")
        addresses = dict(city=self.pda("s1v1_city"), owner=owner, person=owner,
                         payer=self.fee_payer.pubkey(), token_program=TOKEN,
                         system_program=SYSTEM, rent=RENT)
        if action == "registration":
            registration = self.pda("s1v1_recipient", bytes(owner))
            if await self.raw_account(registration) is not None:
                raise ValueError("Stage 1 recipient already registered")
            addresses["registration"] = registration
            return Stage1Plan([self.ix("register_stage1_recipient", {"recipient": owner}, addresses)],
                              "SOL", 0, wallet, wallet, str(registration), str(self.fee_payer.pubkey()), {"kind": "stage1_registration"})
        if action == "claim-transport":
            return await self.transport_plan(payload, owner, connection, addresses)
        if action == "self-claim":
            return await self.claim_plan(payload, owner, connection, addresses)

        before, remaining, args = [], [], {}
        amount = 0
        if action == "pledge":
            hill_key, mint = key(payload.hill), key(payload.mint)
            lot_key = self.pda("s1v1_lot", bytes(owner), struct.pack("<Q", int(payload.deposit_id)))
            if await self.raw_account(lot_key) is not None:
                raise ValueError("Stage 1 deposit ID already used")
            hill = await self.account(hill_key, "Stage1HillBond")
            addresses["climb"] = key(hill["climb"])
            amount = int(payload.amount_base_units)
            args = {"deposit_id": int(payload.deposit_id), "units": amount, "lock_weeks": payload.lock_weeks}
            name = "pledge"
        else:
            lot_key = key(payload.lot)
            lot = await self.account(lot_key, "Stage1PledgeLot")
            if lot["owner"] != wallet or lot["city"] != str(addresses["city"]):
                raise ValueError("Stage 1 lot does not belong to the signed-in wallet")
            canonical = (self.pda("s1v1_exit", bytes(key(lot["exit_request"]))) if lot["exiting"] else
                         self.pda("s1v1_lot", bytes(owner), struct.pack("<Q", lot["deposit_id"])))
            if lot_key != canonical:
                raise ValueError("Noncanonical Stage 1 lot")
            hill_key, mint = key(lot["hill"]), key(lot["mint"])
            hill = await self.account(hill_key, "Stage1HillBond")
            if action == "withdrawal-notice":
                request_key = self.pda("s1v1_request", bytes(lot_key), struct.pack("<Q", int(payload.request_id)))
                if await self.raw_account(request_key) is not None:
                    raise ValueError("Stage 1 request ID already used")
                amount = int(payload.basis_lamports)
                if amount > lot["basis_lamports"]:
                    raise ValueError("Stage 1 notice exceeds lot basis")
                addresses["request"] = request_key
                args = {"request_id": int(payload.request_id), "basis": amount}
                name = "request_withdrawal"
            elif action in ("cancel-notice", "begin-withdrawal", "complete-withdrawal"):
                request_key = key(payload.request)
                request = await self.account(request_key, "Stage1WithdrawalRequest")
                expected = self.pda("s1v1_request", bytes(key(request["lot"])), struct.pack("<Q", request["request_id"]))
                if (request_key != expected or request["owner"] != wallet or
                        request["exit_lot" if action == "complete-withdrawal" else "lot"] != str(lot_key)):
                    raise ValueError("Stage 1 request does not belong to this lot and wallet")
                addresses["request"] = request_key
                amount = request["basis_lamports"]
                name = {"cancel-notice": "cancel_withdrawal", "begin-withdrawal": "begin_withdrawal",
                        "complete-withdrawal": "complete_withdrawal"}[action]
            elif action == "cancel-pledge":
                name = "cancel_pledge"
            else:
                name = "convert_excluded_pledge"
                args = {"lock_weeks": payload.lock_weeks}

        city = await self.account(addresses["city"], "Stage1CityConfig")
        if hill["city"] != str(addresses["city"]) or self.pda("s1v1_hill", bytes(hill["canon_id"])) != hill_key:
            raise ValueError("Invalid Stage 1 hill")
        asset_key = self.pda("s1v1_asset", bytes(mint))
        asset = await self.account(asset_key, "Stage1AssetConfig")
        if asset["city"] != str(addresses["city"]) or asset["mint"] != str(mint):
            raise ValueError("Invalid Stage 1 asset")
        addresses.update(hill=hill_key, mint=mint, lot=lot_key, asset=asset_key,
                         custody=self.pda("s1v1_custody", bytes(lot_key)),
                         owner_reserve=self.pda("s1v1_owner", bytes(lot_key)),
                         earnings=self.pda("s1v1_earnings", bytes(mint)),
                         source=solana_direct._derive_ata(owner, mint), destination=solana_direct._derive_ata(owner, mint))
        if action == "cancel-pledge":
            before.append(self.create_ata(owner, mint))
        if action == "pledge":
            remaining = await self.pledge_providers(city, hill, asset)
        elif action == "convert-pledge":
            remaining = await self.provider_accounts(asset)
        elif action in ("begin-withdrawal", "complete-withdrawal"):
            before, remaining = await self.funded_sweep(addresses, city, asset, chain_time=chain_time)
            if action == "begin-withdrawal":
                exit_lot = self.pda("s1v1_exit", bytes(addresses["request"]))
                addresses.update(exit_lot=exit_lot, exit_custody=self.pda("s1v1_custody", bytes(exit_lot)),
                                 exit_reserve=self.pda("s1v1_owner", bytes(exit_lot)))
            else:
                before.append(self.create_ata(owner, mint))
        # A healthy provider must be admitted in the current epoch before an
        # exit/conversion can price it. Outage recovery explicitly omits this
        # refresh; the program still enforces the canonical stale-exit rules.
        if action in ("convert-pledge", "begin-withdrawal", "complete-withdrawal") and asset["adapter"] != 1 and payload.refresh_rate:
            before.insert(0, self.ix("refresh_stage1_rate", {}, {
                **addresses, "provider": key(asset["provider_account"])}))
        intent = {"kind": "stage1_" + action.replace("-", "_")}
        if action == "pledge":
            intent.update(hill=str(hill_key), climb=str(addresses["climb"]), mint=str(mint), depositId=payload.deposit_id,
                amountBaseUnits=payload.amount_base_units, lockWeeks=payload.lock_weeks,
                providerMode="bonded" if hill["bonded"] else "prebond",
                backingMints=[] if hill["bonded"] else [str(remaining[i].pubkey) for i in range(2, len(remaining), 3)])
        else:
            if action == "complete-withdrawal":
                parent = await self.account(key(request["lot"]), "Stage1PledgeLot")
                if (parent["owner"] != wallet or parent["hill"] != str(hill_key) or parent["mint"] != str(mint)
                        or self.pda("s1v1_lot", bytes(owner), struct.pack("<Q", parent["deposit_id"])) != key(request["lot"])):
                    raise ValueError("Stage 1 original lot mismatch")
                intent["depositId"] = str(parent["deposit_id"])
            else:
                intent["depositId"] = str(lot["deposit_id"])
            if action == "withdrawal-notice":
                intent.update(hill=str(hill_key), requestId=payload.request_id, basisLamports=payload.basis_lamports)
            elif action == "cancel-pledge":
                intent.update(hill=str(hill_key), mint=str(mint))
            elif action == "convert-pledge":
                intent.update(hill=str(hill_key), mint=str(mint), lockWeeks=payload.lock_weeks, refreshRate=payload.refresh_rate)
            else:
                intent["requestId"] = str(request["request_id"])
                if action != "cancel-notice":
                    intent.update(hill=str(hill_key), mint=str(mint), week=str((chain_time - city["season_anchor"]) // 604800), refreshRate=payload.refresh_rate)
        return Stage1Plan([*before, self.ix(name, args, addresses, remaining)],
                          str(mint), amount, str(addresses["source"] if action == "pledge" else lot_key),
                          str(addresses["destination"] if action == "complete-withdrawal" else lot_key),
                          str(addresses.get("request", lot_key)), wallet, intent)

    async def claim_plan(self, payload, owner, connection, addresses, *, single=False):
        single = single or bool(getattr(payload, "lookup_table", None))
        if single and len(payload.claims) != 1:
            raise ValueError("Lookup transport admits one leaf per transaction")
        if connection is None:
            raise ValueError("Stage 1 durable proofs unavailable")
        genesis = await self.genesis()
        if await connection.fetchval("SELECT genesis FROM stage1_keeper_network") != genesis:
            raise ValueError("Stage 1 proof network differs")
        registration = self.pda("s1v1_recipient", bytes(owner))
        registered = await self.account(registration, "Stage1Recipient")
        if registered["person"] != str(owner) or registered["recipient"] != str(owner):
            raise ValueError("Stage 1 recipient differs from signed-in wallet")
        leaves, descriptors, remaining, sets, mint, kind, total = [], [], [], set(), None, None, 0
        for ref in payload.claims:
            row = await connection.fetchrow("""SELECT p.leaf,s.mint,s.kind,s.hill,s.city,j.week,j.publications
                FROM stage1_keeper_proofs p JOIN stage1_keeper_jobs j ON j.id=p.job_id
                JOIN stage1_keeper_scopes s ON s.id=j.scope_id
                WHERE p.job_id=$1 AND p.role=$2 AND p.leaf_index=$3 AND p.person=$4
                AND p.paid_slot IS NULL AND j.state='complete' AND NOT j.export_suspended
                AND s.program=$5""", ref.job_id, ref.role, ref.index, str(owner), str(self.program_id))
            if not row:
                raise ValueError("Stage 1 unpaid owner proof unavailable")
            leaf = unpack(row["leaf"])
            if (leaf["person"] != str(owner) or leaf["recipient"] != str(owner) or leaf["index"] != ref.index
                    or row["city"] != str(addresses["city"])):
                raise ValueError("Stage 1 proof owner mismatch")
            if mint is not None and (mint, kind) != (key(row["mint"]), row["kind"]):
                raise ValueError("Stage 1 batch assets differ")
            mint, kind = key(row["mint"]), row["kind"]
            hill, week = bytes(key(row["hill"])), struct.pack("<Q", row["week"])
            dung = self.pda("s1v1_dung", hill, week)
            address = (self.pda("s1v1_dung_claims", bytes(dung), bytes([ref.role])) if kind == "dung" and ref.role in (0, 1)
                       else self.pda("s1v1_claims", hill, bytes(mint), week) if kind == "cash" and ref.role == -1 else None)
            if address is None or address in sets:
                raise ValueError("Stage 1 batch claim sets must be distinct")
            sets.add(address)
            publication = unpack(row["publications"]).get(str(address))
            if not publication or publication.get("closed"):
                raise ValueError("Stage 1 publication unavailable")
            account = await self.account(address, "Stage1ClaimSet" if kind == "cash" else "Stage1DungClaimSet")
            raw = await self.raw_account(address)
            from .stage1_keeper_abi import LAYOUTS
            header = LAYOUTS["Stage1ClaimSet" if kind == "cash" else "Stage1DungClaimSet"]["$header"]
            if kind == "dung" and await self.clock() < int(account["published_at"]) + 172800:
                raise ValueError("Stage 1 DUNG claim not open")
            bitmap = bytes(raw.data)[header:]
            if (ref.index >= account["leaf_count"] or ref.index // 8 >= len(bitmap)
                    or bitmap[ref.index // 8] & (1 << (ref.index % 8))):
                raise ValueError("Stage 1 leaf already paid or absent")
            item = {"index": ref.index, "amount": leaf["amount"], "proof": [
                {"hash": list(bytes.fromhex(p["hash"])), "sum": p["sum"]} for p in leaf["proof"]]}
            descriptor = {"hill": row["hill"], "week": str(row["week"]), "index": ref.index,
                "amountBaseUnits": str(leaf["amount"]), "proof": [
                    {"hash": p["hash"], "sum": str(p["sum"])} for p in leaf["proof"]]}
            if kind == "cash":
                terms = cash_terms(str(address), publication["event"], account)
                item["terms"] = {**terms, "audit_hash": list(bytes.fromhex(terms["audit_hash"]))}
                descriptor.update(capBaseUnits=str(terms["cap"]), frozenAt=str(terms["frozen_at"]), auditHash=terms["audit_hash"])
            else:
                remaining.append(AccountMeta(dung, False, True))
                descriptor["role"] = ref.role
            remaining.append(AccountMeta(address, False, True))
            leaves.append(item)
            descriptors.append(descriptor)
            total += leaf["amount"]
        addresses.update(registration=registration, mint=mint, destination=solana_direct._derive_ata(owner, mint),
                         asset=self.pda("s1v1_asset", bytes(mint)), earnings=self.pda("s1v1_earnings", bytes(mint)),
                         state=self.pda("s1v1_dung_state"), program_config=self.pda("program_config"),
                         dung_mint_auth=self.pda("dung_mint_auth"))
        name = "claim_stage1_batch" if kind == "cash" else "claim_stage1_dung_batch"
        args = {"person": owner, "leaves": leaves}
        if single:
            name = "claim_stage1" if kind == "cash" else "claim_stage1_dung"
            args = {"person": owner, **leaves[0]}
            addresses["claim_set"] = remaining[-1].pubkey
            if kind == "dung": addresses["dung"] = remaining[0].pubkey
            remaining = []
        lookup = await self.lookup_table(payload.lookup_table, owner) if getattr(payload, "lookup_table", None) else None
        return Stage1Plan([self.create_ata(owner, mint), self.ix(name, args, addresses, remaining)],
                          str(mint), total, ",".join(str(s) for s in sorted(sets, key=bytes)),
                          str(addresses["destination"]), str(registration), str(owner),
                          {"kind": "stage1_self_claim", "mint": str(mint), "claimType": kind, "claims": descriptors, **({"single": True} if single else {})}, lookup)

    async def build(self, plan, *, blockhash=None):
        if blockhash is None:
            blockhash, height = await self._get_recent_blockhash()
        else:
            height = 0  # Only message bytes are used when rebuilding a signed submit.
        if plan.lookup:
            message = MessageV0.try_compile(self.fee_payer.pubkey(), plan.instructions, [plan.lookup], blockhash)
            signatures = [self.fee_payer.sign_message(to_bytes_versioned(message)), *[Signature.default()] * (message.header.num_required_signatures - 1)]
            raw = bytes(VersionedTransaction.populate(message, signatures))
        else:
            raw = self._build_unsigned_tx(self.fee_payer.pubkey(), plan.instructions, blockhash, [self.fee_payer])
        if len(raw) > 1232:
            raise Stage1LookupRequired("Prepare a single claim with owner-paid lookup transport")
        return BuildTxResult(base64.b64encode(raw).decode(), str(blockhash), height,
                             "TIM: stage1_confirmation", pda=plan.reference)

    async def simulate(self, plan):
        prepared = await self.build(plan)
        transaction = VersionedTransaction.from_bytes(base64.b64decode(prepared.transaction))
        async with AsyncClient(self.rpc_url) as rpc:
            result = await rpc.simulate_transaction(transaction, sig_verify=False,
                replace_recent_blockhash=True, commitment="confirmed")
        return result.value.err is None

    def requires_lookup(self, plan):
        message = Message.new_with_blockhash(plan.instructions, self.fee_payer.pubkey(), Hash.default())
        return len(bytes(Transaction.new_unsigned(message))) > 1232


def get_stage1_tx_builder():
    return Stage1TxBuilder()
