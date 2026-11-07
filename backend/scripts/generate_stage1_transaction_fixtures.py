"""Offline firewall vectors from production Stage1TxBuilder plans, never chain evidence."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import struct
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from anchorpy import Idl
from anchorpy.coder.coder import Coder
from solders.hash import Hash
from solders.instruction import AccountMeta
from solders.message import Message, MessageV0
from solders.address_lookup_table_account import AddressLookupTableAccount
from solders.signature import Signature
from solders.transaction import VersionedTransaction
from solders.pubkey import Pubkey
from solders.transaction import Transaction

from app.routes.stage1_actions import ActionRequest, CancelPledgeRequest, PledgeRequest, NoticeRequest, WithdrawalRequest, ConvertRequest, ClaimRequest, TransportRequest
from app.services.stage1_transactions import Stage1TxBuilder, IDL

PROGRAM = Pubkey.from_string("EVjP2Vdz9buHNphywPhoybf213poa8EiSW6FGbXWFqYH")
FEE_PAYER = Pubkey.from_string("9h6UJdZqUPNnShaUHkSoxvEeZ7gBeNxzXGQcShhBnzEP")
AUTHORITY = Pubkey.from_string("CJz8PUyNVvLuXJvjsYXgSKD9utZVP2XoTEZq6M973Gha")
WALLET = Pubkey.from_string("GmaDrppBC7P5ARKV8g3djiwP89vz1jLK23V2GBjuAEGB")
JITO = "J1toso1uCk3RLmjorhTtrVwY9HJ7X8V9yYac6Y7kGCPn"
MSOL = "mSoLzYCxHdYgdzU16g5QSh3i5K3z3KZK7ytfqcJm7So"
JUP = "jupSoLaHXQiZZTSfEWMTRRgpnyFm8f6sZdosWBjx93v"
USDC = "DpLPBaRuLnBsR3P3meU1tmiNUxreXwskXBebTYKvNGne"
DUNG = "CqDFJWLpr49tB8xjHegy5JR5jwMCfmhicjuWawtKLeCk"
PROVIDERS = {JITO: "Jito4APyf642JPZPx3hGc6WWJ8zPKtRbRs4P815Awbb", MSOL: "8szGkuLTAux9XMgZ2vtY39jVSowEcpBfFfD8hXSEqdGC", JUP: "8VpRhuxa7sUUepdY3kQiTmX9rS5vx4WgaXiAnXq4KCtr"}


def fixture_builder():
    b = object.__new__(Stage1TxBuilder)
    b.program_id, b.rpc_url = PROGRAM, "http://127.0.0.1:1"
    b.fee_payer, b.backend_authority = SimpleNamespace(pubkey=lambda: FEE_PAYER), SimpleNamespace(pubkey=lambda: AUTHORITY)
    b.idl = json.loads(IDL.read_text()); b.coder = Coder(Idl.from_json(json.dumps(b.idl)))
    canon = bytes([42] * 16)
    hill = b.pda("s1v1_hill", canon)
    climb = b.pda("climb", bytes([24] * 32))
    city = b.pda("s1v1_city")
    lot = b.pda("s1v1_lot", bytes(WALLET), struct.pack("<Q", 7))
    request = b.pda("s1v1_request", bytes(lot), struct.pack("<Q", 8))
    exit_lot = b.pda("s1v1_exit", bytes(request))
    rows = {
        str(city): {"season_anchor": 0, "provider_slots": 7, "asset_count": 3},
        str(hill): {"city": str(city), "canon_id": list(canon), "climb": str(climb), "bonded": False, "asset_lots": [1, 1, 1] + [0] * 29},
        str(lot): {"owner": str(WALLET), "city": str(city), "hill": str(hill), "mint": JITO,
                   "deposit_id": 7, "exiting": False, "basis_lamports": 200},
        str(request): {"owner": str(WALLET), "lot": str(lot), "request_id": 8, "exit_lot": str(exit_lot), "basis_lamports": 100},
        str(exit_lot): {"owner": str(WALLET), "city": str(city), "hill": str(hill), "mint": JITO,
                       "deposit_id": 0, "exiting": True, "exit_request": str(request), "basis_lamports": 100},
        str(b.pda("s1v1_recipient", bytes(WALLET))): {"person": str(WALLET), "recipient": str(WALLET)},
    }
    for slot, (mint, provider) in enumerate(PROVIDERS.items()):
        rows[str(b.pda("s1v1_asset", bytes(Pubkey.from_string(mint))))] = {"city": str(city), "mint": mint,
            "adapter": slot + 2, "slot": slot, "provider_account": provider}
    b.account = AsyncMock(side_effect=lambda address, kind, **kw: rows[str(address)])
    b.raw_account = AsyncMock(return_value=None)
    b.genesis = AsyncMock(return_value="offline-genesis")
    b.clock = AsyncMock(return_value=604800 * 40 + 10)
    async def provider_inventory(city, hill, incoming):
        if hill["bonded"]:
            return await b.provider_accounts(incoming)
        result = []
        for mint in PROVIDERS:
            asset = b.pda("s1v1_asset", bytes(Pubkey.from_string(mint)))
            result += [AccountMeta(asset, False, True), *await b.provider_accounts(rows[str(asset)])]
        return result
    b.pledge_providers = provider_inventory
    return b, rows, hill, climb, lot, request, exit_lot


async def build_records():
    b, rows, hill, climb, lot, request, exit_lot = fixture_builder()
    records = []
    async def emit(name, action, payload, intent, connection=None):
        plan = await b.plan(action, payload, str(WALLET), connection)
        message = Message.new_with_blockhash(plan.instructions, FEE_PAYER, Hash.default())
        if plan.lookup:
            message = MessageV0.try_compile(FEE_PAYER, plan.instructions, [plan.lookup], Hash.default())
            raw = bytes(VersionedTransaction.populate(message, [Signature.default()] * message.header.num_required_signatures))
        else:
            raw = bytes(Transaction.new_unsigned(message))
        assert len(raw) <= 1232, (name, len(raw))
        records.append({"name": name, "wallet": str(WALLET), "action": action,
            "request": payload.model_dump(), "prepared": {"transaction": base64.b64encode(raw).decode(),
            "blockhash": str(Hash.default()), "lastValidBlockHeight": 123456, "message": "TIM: stage1_confirmation", "pda": plan.reference}, "intent": intent or plan.intent, **({"lookup": {"address": str(plan.lookup.key), "addresses": list(map(str, plan.lookup.addresses))}} if plan.lookup else {})})
    await emit("registration", "registration", ActionRequest(), {"kind": "stage1_registration"})
    for lock in (0, 13, 26, 52):
        await emit(f"pledge_prebond_{lock}", "pledge", PledgeRequest(hill=str(hill), mint=JITO, deposit_id="7", amount_base_units="123", lock_weeks=lock),
            {"kind": "stage1_pledge", "hill": str(hill), "climb": str(climb), "mint": JITO, "depositId": "7", "amountBaseUnits": "123", "lockWeeks": lock, "providerMode": "prebond", "backingMints": list(PROVIDERS)})
    await emit("cancel-pledge", "cancel-pledge", CancelPledgeRequest(lot=str(lot)), None)
    rows[str(hill)]["bonded"] = True
    await emit("pledge_bonded", "pledge", PledgeRequest(hill=str(hill), mint=JITO, deposit_id="7", amount_base_units="123", lock_weeks=13),
        {"kind": "stage1_pledge", "hill": str(hill), "climb": str(climb), "mint": JITO, "depositId": "7", "amountBaseUnits": "123", "lockWeeks": 13, "providerMode": "bonded", "backingMints": []})
    await emit("notice", "withdrawal-notice", NoticeRequest(lot=str(lot), request_id="8", basis_lamports="100"),
        {"kind": "stage1_withdrawal_notice", "hill": str(hill), "depositId": "7", "requestId": "8", "basisLamports": "100"})
    for action in ("cancel-notice", "begin-withdrawal", "complete-withdrawal"):
        intent = {"kind": "stage1_" + action.replace("-", "_"), "depositId": "7", "requestId": "8"}
        if action != "cancel-notice": intent.update(hill=str(hill), mint=JITO, week="40")
        await emit(action, action, WithdrawalRequest(lot=str(exit_lot if action == "complete-withdrawal" else lot), request=str(request)), intent)
    for lock in (0, 13, 26, 52):
        await emit(f"convert_{lock}", "convert-pledge", ConvertRequest(lot=str(lot), lock_weeks=lock),
            {"kind": "stage1_convert_pledge", "hill": str(hill), "mint": JITO, "depositId": "7", "lockWeeks": lock})
    for action in ("convert-pledge", "begin-withdrawal", "complete-withdrawal"):
        payload = (ConvertRequest(lot=str(lot), lock_weeks=13, refresh_rate=False) if action == "convert-pledge" else
                   WithdrawalRequest(lot=str(exit_lot if action == "complete-withdrawal" else lot), request=str(request), refresh_rate=False))
        await emit(action + "_outage", action, payload, None)
    for kind, mint in (("cash", USDC), ("dung", DUNG)):
        proofs = []
        for count in (1, 2):
            refs, leaves, proof_rows = [], [], []
            for n in range(count):
                role, week = (-1, 30 + n) if kind == "cash" else (n, 30)
                claim_set = (b.pda("s1v1_claims", bytes(hill), bytes(Pubkey.from_string(mint)), struct.pack("<Q", week)) if kind == "cash" else
                    b.pda("s1v1_dung_claims", bytes(b.pda("s1v1_dung", bytes(hill), struct.pack("<Q", week))), bytes([role])))
                audit = {k: "00" * 32 for k in ("snapshot", "source_lineage", "release_commitment", "boost_commitment")}
                audit["new_holds"] = [0] * 5
                audit_hash = hashlib.sha256(b"BR-stage1-v2:cash-audit\0" + bytes(128) + struct.pack("<5Q", *audit["new_holds"])).digest()
                terms = {"cap": 200, "frozen_at": 100, "audit_hash": list(audit_hash)}
                metadata = hashlib.sha256(b"BR-stage1-v2:claim-terms\0" + bytes(claim_set) + struct.pack("<Qq", 200, 100) + audit_hash).digest()
                rows[str(claim_set)] = {"published_at": 0, "leaf_count": 2, "total": 200, "root": [0] * 32, "metadata_hash": list(metadata)}
                event = {"terms": terms, "audit": audit, "claim_set": str(claim_set), "total": 200, "leaf_count": 2, "root": [0] * 32}
                leaf = {"person": str(WALLET), "recipient": str(WALLET), "index": 0, "amount": 100, "proof": [{"hash": "11" * 32, "sum": 100}]}
                proof_rows.append({"leaf": leaf, "mint": mint, "kind": kind, "hill": str(hill), "city": str(b.pda("s1v1_city")), "week": week,
                    "publications": {str(claim_set): {"event": event, "closed": None}}})
                refs.append({"job_id": f"offline-{kind}-{n}", "role": role, "index": 0})
                leaves.append({"hill": str(hill), "week": str(week), "index": 0, "amountBaseUnits": "100", "proof": [{"hash": "11" * 32, "sum": "100"}],
                    **({"capBaseUnits": "200", "frozenAt": "100", "auditHash": audit_hash.hex()} if kind == "cash" else {"role": role})})
            b.raw_account = AsyncMock(return_value=SimpleNamespace(data=bytes(276 if kind == "cash" else 141)))
            connection = SimpleNamespace(fetchval=AsyncMock(return_value="offline-genesis"), fetchrow=AsyncMock(side_effect=proof_rows))
            with patch("app.services.stage1_transactions.AsyncClient") as client:
                client.return_value.__aenter__.return_value.get_genesis_hash = AsyncMock(return_value=SimpleNamespace(value="offline-genesis"))
                await emit(f"{kind}_claim_{count}", "self-claim", ClaimRequest(claims=refs),
                    {"kind": "stage1_self_claim", "mint": mint, "claimType": kind, "claims": leaves}, connection)
                if count == 1:
                    proof_rows[0]["leaf"]["proof"] *= 16
                    connection.fetchrow = AsyncMock(side_effect=proof_rows)
                    setup = TransportRequest(mode="create", claims=refs, recent_slot="1234")
                    transport = await b.plan("claim-transport", setup, str(WALLET), connection)
                    connection.fetchrow = AsyncMock(side_effect=proof_rows)
                    await emit(f"{kind}_lookup_create", "claim-transport", setup, None, connection)
                    table = AddressLookupTableAccount(Pubkey.from_string(transport.reference), [Pubkey.from_string(k) for k in transport.intent["addresses"]])
                    b.lookup_table = AsyncMock(return_value=table)
                    connection.fetchrow = AsyncMock(side_effect=proof_rows)
                    await emit(f"{kind}_claim_depth16", "self-claim", ClaimRequest(claims=refs, lookup_table=transport.reference), None, connection)
                    for mode in ("deactivate", "close"):
                        await emit(f"{kind}_lookup_{mode}", "claim-transport", TransportRequest(mode=mode, lookup_table=transport.reference), None, connection)

    return records


if __name__ == "__main__":
    print(json.dumps(asyncio.run(build_records()), indent=2))
