"""Finalized, genesis-gated transport for the composed Stage 1 ABI.

Localnet by default; devnet requires explicit admission, mainnet also requires
the separate release gate. Endpoint credentials exist only in process memory.
"""
import base64
import base58
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import fields, is_dataclass
import hashlib
import json
import logging
import re
from pathlib import Path
import struct
from urllib.parse import urlparse
import uuid

import httpx
from anchorpy import Idl
from anchorpy.coder.coder import Coder
from solders.address_lookup_table_account import AddressLookupTableAccount
from solders.compute_budget import set_compute_unit_limit
from solders.hash import Hash
from solders.instruction import AccountMeta, Instruction
from solders.keypair import Keypair
from solders.message import MessageV0, to_bytes_versioned
from solders.pubkey import Pubkey
from solders.transaction import VersionedTransaction
from solders.signature import Signature
from spl.token.instructions import get_associated_token_address
from spl.token.constants import ASSOCIATED_TOKEN_PROGRAM_ID

from .stage1_keeper_worker import Blocked
from .stage1_keeper_paths import IDL
from .stage1_keeper_abi import LAYOUTS, validate_layouts, cash_terms

GENESIS_CLUSTERS = {"5eykt4UsFv8P8NJdTREpY1vzqKqZKvdpKuc147dw2N9d": "mainnet-beta",
                    "EtWTRABZaYq6iMfeYKouRu166VU2xqa1wcaWoxPkrZBG": "devnet",
                    "4uhcVJyU9pJkvQyS88uRDiswHXSCkY3zQawwpjk2NsNY": "testnet"}
_PRIVATE_RPC = ContextVar("stage1_private_rpc", default=False)


class _TransportLogFilter(logging.Filter):
    def filter(self, record):
        # HTTPX logs full URLs; HTTPCore debug logs can include response headers
        # and exception text. Suppress only this task's keeper transport events.
        return not _PRIVATE_RPC.get()


for _logger in ("httpx", "httpcore.connection", "httpcore.http11", "httpcore.http2", "httpcore.proxy", "httpcore.socks"):
    logging.getLogger(_logger).addFilter(_TransportLogFilter())
SYSTEM = "11111111111111111111111111111111"
CLOCK = "SysvarC1ock11111111111111111111111111111111"
TOKEN = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
LOOKUP = "AddressLookupTab1e1111111111111111111111111"
SLOT_HASHES = "SysvarS1otHashes111111111111111111111111111"
TYPES = ("ProgramConfig", "Stage1CityConfig", "Stage1AssetConfig", "Stage1HillBond", "Stage1SettlementCursor",
         "Stage1WeekFunding", "Stage1ClaimSet", "Stage1PledgeLot", "Stage1Recipient",
         "Stage1Boost", "Stage1BoostHill", "Stage1DungMint", "Stage1DungClaimSet", "Stage1DungState")


def normal(value):
    if isinstance(value, Pubkey):
        return str(value)
    if is_dataclass(value):
        return {f.name: normal(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, dict):
        return {k: normal(v) for k, v in value.items() if not k.startswith("_")}
    if isinstance(value, (tuple, list)):
        return [normal(v) for v in value]
    return value


def key(value):
    return Pubkey.from_string(value)


class SettlementPaused(RuntimeError):
    pass


class SponsorUnfunded(RuntimeError):
    pass


class KeeperChain:
    def __init__(self, rpc, program, publisher_path, *, idl_path=None, allowed_clusters=("localnet",), mainnet_release=False, publisher_keys=None):
        try:
            url = urlparse(rpc)
            hostname = url.hostname
            # Validate before handing the URL to HTTPX; neither parser's error
            # text is safe to expose for credential-bearing endpoints.
            httpx.URL(rpc)
            url.port
        except (ValueError, httpx.InvalidURL):
            raise ValueError("invalid keeper RPC URL") from None
        configured = frozenset(allowed_clusters)
        if not configured or not configured <= {"localnet", "devnet", "mainnet-beta"}:
            raise ValueError("invalid Stage 1 cluster allowlist")
        self.allowed_clusters = configured | {"localnet"}
        self.loopback = hostname in ("127.0.0.1", "localhost", "::1")
        local = self.loopback and url.scheme == "http" and not (url.username or url.password or url.query or url.fragment) and url.path in ("", "/")
        remote = url.scheme == "https" and url.hostname and not url.fragment and bool(self.allowed_clusters - {"localnet"})
        if not (local or remote):
            raise ValueError("Stage 1 keeper requires loopback RPC or explicitly configured HTTPS cluster")
        if publisher_keys is not None:
            if set(publisher_keys) != {'localnet', 'devnet', 'mainnet-beta'} or len(set(publisher_keys.values())) != 3:
                raise ValueError('publisher keys must be distinct for each cluster')
            for value in publisher_keys.values():
                key(value)
        self.publisher_keys = publisher_keys
        self.version_pool = None
        self.mainnet_release = mainnet_release
        self.rpc_url, self.program = rpc, key(program)
        self.publisher_path = Path(publisher_path)
        idl_path = idl_path or IDL
        self.idl = json.loads(Path(idl_path).read_text())
        validate_layouts(self.idl)
        self.coder = Coder(Idl.from_json(json.dumps(self.idl)))
        self.client = httpx.AsyncClient(timeout=30, trust_env=False)
        self.discriminators = {hashlib.sha256(f"account:{name}".encode()).digest()[:8]: name for name in TYPES}
        self.signer = None
        self.genesis = None
        self.claim_cache = {}
        self.in_cycle = False
        self.reserved_lamports = 0
        self.rent_cache = {}

    @asynccontextmanager
    async def cycle(self):
        # All public-network checks still precede any work in every cycle.
        await self.start()
        if self.version_pool is not None:
            (await self.compatibility(self.version_pool)).require_stage1()
        self.in_cycle, self.reserved_lamports, self.rent_cache = True, 0, {}
        try:
            yield
        finally:
            self.in_cycle = False

    @staticmethod
    def insufficient_funds(error):
        # Classify privately; never retain provider-controlled messages/logs.
        text = json.dumps(error).lower()
        return any(s in text for s in ('insufficientfunds', 'insufficient funds', 'insufficient lamports',
                                       'insufficient lamport', 'insufficientfundsforrent'))

    async def close(self):
        token = _PRIVATE_RPC.set(True)
        try:
            await self.client.aclose()
        finally:
            _PRIVATE_RPC.reset(token)

    async def rpc(self, method, params):
        token = _PRIVATE_RPC.set(True)
        try:
            response = await self.client.post(self.rpc_url, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
            response.raise_for_status()
            result = response.json()
        except (httpx.HTTPError, httpx.InvalidURL, ValueError):
            raise RuntimeError("keeper RPC transport failed") from None
        finally:
            _PRIVATE_RPC.reset(token)
        if "error" in result:
            error = result["error"]
            code = error.get("code") if type(error.get("code")) is int else None
            data = error.get("data") or {}
            refusal = data.get("err") if isinstance(data, dict) else None
            if self.insufficient_funds(error):
                raise SponsorUnfunded('sponsor_unfunded')
            if isinstance(refusal, dict) and "InstructionError" in refusal:
                # Do not persist provider-controlled error strings or logs;
                # a provider may echo credentials even inside error.data.
                if self.paused_error(refusal):
                    raise SettlementPaused('settlement_paused')
                raise Blocked("program_refusal", {"method": method, "code": code})
            if error.get("code") in (-32600, -32601, -32602):
                raise Blocked("rpc_configuration", {"method": method, "code": error["code"]})
            raise RuntimeError(f"keeper RPC {method} failed")
        return result["result"]

    def paused_error(self, error):
        paused = next((e['code'] for e in self.idl['errors'] if e['name']=='Stage1SettlementPaused'),None)
        instruction = error.get('InstructionError') if isinstance(error,dict) else None
        return bool(paused is not None and isinstance(instruction,list) and len(instruction)==2 and instruction[1]=={'Custom':paused})

    async def start(self):
        if self.in_cycle:
            return
        genesis = await self.rpc("getGenesisHash", [])
        cluster = GENESIS_CLUSTERS.get(genesis, "localnet" if self.loopback else "unknown")
        if cluster not in self.allowed_clusters or (cluster == "mainnet-beta" and not self.mainnet_release):
            raise ValueError("public network or cluster not admitted by keeper release configuration")
        if self.genesis and genesis != self.genesis:
            raise ValueError("cluster genesis changed during keeper execution")
        self.cluster = cluster
        self.genesis = genesis
        if self.signer is None:
            self.signer = Keypair.from_bytes(bytes(json.loads(self.publisher_path.read_text())))
        if self.publisher_keys is not None and self.publisher_keys.get(cluster) != str(self.signer.pubkey()):
            raise ValueError('publisher key does not belong to the admitted cluster')
        if cluster != 'localnet' and self.publisher_keys is None:
            raise ValueError('distinct cluster publisher keys must be configured')

    async def get_genesis_hash(self):
        # SDK-compatible response for the shared compatibility helper.
        from types import SimpleNamespace
        return SimpleNamespace(value=self.genesis or await self.rpc('getGenesisHash', []))

    async def compatibility(self, pool):
        from app.program_compatibility import observe_program_version
        address = self.pda('program_config')
        _, rows = await self.multiple([address])
        row = rows[address]
        if not row or row['owner'] != str(self.program) or row['executable']:
            raise ValueError('invalid ProgramConfig account')
        raw = base64.b64decode(row['data'][0])
        if len(raw) < 73 or raw[:8] != hashlib.sha256(b'account:ProgramConfig').digest()[:8]:
            raise ValueError('invalid ProgramConfig layout')
        self.version_pool = pool
        return await observe_program_version(self, self.rpc_url, str(self.program), raw[72], pool=pool)

    async def authorize(self, kind, floor=0):
        address = self.pda('s1v1_city')
        floor, rows = await self.multiple([address], floor)
        if not rows[address]:
            raise ValueError('configured publisher city is unavailable')
        city = self.decode(rows[address], 'Stage1CityConfig')
        if city['publisher'] != str(self.signer.pubkey()):
            raise ValueError('configured publisher is not authorized on observed chain')
        # Intake pause stops intake instructions only. Published cash is still
        # claimable during settlement pause; DUNG claims explicitly are not.
        if city.get('settlement_paused') and kind not in {'cash_claim', 'cash_close', 'dung_close', 'funding_close', 'dung_mint_close', 'prepare_set', 'dung_prepare', 'lookup', 'lookup_deactivate', 'lookup_close'}:
            raise SettlementPaused('settlement_paused')
        return floor

    async def transaction_evidence(self, signature, floor=0, *, allow_failed=False):
        from anchorpy.program.event import EventParser
        result = await self.rpc('getTransaction', [signature, {'encoding': 'json', 'commitment': 'finalized', 'maxSupportedTransactionVersion': 0}])
        if not result or result['slot'] < floor:
            raise RuntimeError('finalized transaction evidence unavailable')
        if result['meta']['err'] and not allow_failed:
            raise Blocked('transaction_failed', {'signature': signature})
        events = []
        EventParser(self.program, self.coder).parse_logs(result['meta'].get('logMessages') or [], lambda e: events.append({'name': e.name, 'data': normal(e.data)}))
        meta = result['meta']
        # ATA rent remains in recipient custody. Report the sponsor's actual
        # outlay separately from refundable weekly program-account deposits.
        token_accounts = {a['accountIndex'] for a in meta.get('postTokenBalances',[])}
        sponsored_ata = sum(meta['postBalances'][i] for i in token_accounts if meta.get('preBalances',[1]*(i+1))[i]==0)
        return {'signature': signature, 'slot': result['slot'], 'fee': meta['fee'], 'events': events,
                'sponsored_ata_deposits_lamports':sponsored_ata,
                'unfunded':self.insufficient_funds({'err':meta['err'],'logs':meta.get('logMessages',[])})}

    async def closure_witness(self, address, rent_payer, kind, published_slot, scope=None, week=None):
        """Recover a permissionless close from successful finalized execution."""
        name = {'cash':'close_stage1_claim_set','dung':'close_stage1_dung_claim_set',
                'funding':'close_stage1_week_funding','dung_mint':'close_stage1_dung_mint'}[kind]
        expected = [address,rent_payer]
        if kind=='funding':
            expected = [address,self.cursor_address(scope),self.pda('s1v1_asset',bytes(key(scope['mint']))),
                        self.pda('s1v1_earnings',bytes(key(scope['mint']))),self.claim_address(scope,week),rent_payer]
        elif kind=='dung_mint':
            expected = [address,scope['hill'],self.dung_claim_address(scope,week,0),self.dung_claim_address(scope,week,1),rent_payer]
        discriminator = hashlib.sha256(f'global:{name}'.encode()).digest()[:8]
        before = None
        while True:
            options = {'commitment':'finalized', 'limit':1000}
            if before:
                options['before'] = before
            signatures = await self.rpc('getSignaturesForAddress',[address,options])
            for row in signatures:
                if row['slot'] < published_slot:
                    return None
                if row['err'] is not None:
                    continue
                tx = await self.rpc('getTransaction',[row['signature'],{'encoding':'json','commitment':'finalized','maxSupportedTransactionVersion':0}])
                if not tx or tx['meta']['err'] is not None or tx['slot'] < published_slot:
                    continue
                keys = tx['transaction']['message']['accountKeys']
                loaded = tx['meta'].get('loadedAddresses') or {}
                keys = keys + loaded.get('writable',[]) + loaded.get('readonly',[])
                instructions = list(tx['transaction']['message']['instructions'])
                instructions += [ix for group in tx['meta'].get('innerInstructions') or [] for ix in group['instructions']]
                for ix in instructions:
                    if (keys[ix['programIdIndex']]==str(self.program) and base58.b58decode(ix['data'])==discriminator
                        and [keys[i] for i in ix['accounts']]==expected):
                        return {'signature':row['signature'],'slot':tx['slot'],'fee':tx['meta']['fee'],
                                'fully_claimed_close':True,'external':True}
            if len(signatures)<1000:
                return None
            before = signatures[-1]['signature']

    def pda(self, seed, *parts):
        return str(Pubkey.find_program_address([seed.encode(), *parts], self.program)[0])

    def funding(self, scope, week):
        return self.pda("s1v1_funding", bytes(key(scope["hill"])), bytes(key(scope["mint"])), struct.pack("<Q", week))

    def claim_address(self, scope, week):
        return self.pda("s1v1_claims", bytes(key(scope["hill"])), bytes(key(scope["mint"])), struct.pack("<Q", week))

    def cursor_address(self, scope):
        return self.pda("s1v1_cursor", bytes(key(scope["hill"])), bytes(key(scope["mint"])))

    def decode(self, account, kind):
        raw = base64.b64decode(account["data"][0])
        if (account["owner"] != str(self.program) or account["executable"]
            or self.discriminators.get(raw[:8]) != kind):
            raise ValueError("invalid Stage 1 account owner or type")
        obj = normal(self.coder.accounts.decode(raw))
        for field in ("lineage", "snapshot", "root", "proposal_snapshot", "source_lineage", "release_commitment", "commitment_hash", "metadata_hash", "boost_commitment"):
            if field in obj:
                obj[field] = bytes(obj[field]).hex()
        if kind=='Stage1SettlementCursor':
            for hold in obj['carried_holds']:
                for field in ('lineage','proposal_snapshot'):
                    hold[field] = bytes(hold[field]).hex()
        return obj

    async def multiple(self, addresses, floor=0, *, data_slice=None):
        accounts = {}
        for start in range(0, len(addresses), 100):
            batch = addresses[start:start+100]
            options = {"encoding": "base64", "commitment": "finalized", "minContextSlot": floor}
            if data_slice is not None:
                options['dataSlice'] = data_slice
            result = await self.rpc("getMultipleAccounts", [batch, options])
            if result["context"]["slot"] < floor or len(result["value"]) != len(batch):
                raise RuntimeError("stale or incomplete finalized account read")
            floor = result["context"]["slot"]
            accounts.update(zip(batch, result["value"]))
        return floor, accounts

    async def filtered(self, kind, offset, address, floor=0):
        discriminator = hashlib.sha256(f"account:{kind}".encode()).digest()[:8]
        result = await self.rpc("getProgramAccounts", [str(self.program), {
            "encoding": "base64", "commitment": "finalized", "withContext": True, "minContextSlot": floor,
            "filters": [{"memcmp": {"offset": 0, "bytes": base58.b58encode(discriminator).decode()}},
                        {"memcmp": {"offset": offset, "bytes": address}}]}])
        if result["context"]["slot"] < floor:
            raise RuntimeError("stale finalized inventory read")
        decoded = {}
        for row in result["value"]:
            raw = base64.b64decode(row["account"]["data"][0])
            if raw[offset:offset+32] != bytes(key(address)):
                raise ValueError("RPC returned an account outside the requested scope")
            decoded[row["pubkey"]] = {**self.decode(row["account"], kind), 'lamports':row['account'].get('lamports',0)}
        return result["context"]["slot"], decoded

    async def cash_claim_inventory(self, scope, floor=0, *, kind='Stage1ClaimSet'):
        """One 12-byte counter inventory; fetch immutable header once, bits on change.

        The cache is per admitted process/genesis. A restart safely reacquires
        headers and paid bitmaps; final reconciliation still fences the asset.
        """
        layout = LAYOUTS[kind]
        discriminator = hashlib.sha256(f'account:{kind}'.encode()).digest()[:8]
        filters = [{'memcmp': {'offset': 0, 'bytes': base58.b58encode(discriminator).decode()}}]
        if kind == 'Stage1ClaimSet':
            filters.append({'memcmp': {'offset': layout['mint'], 'bytes': scope['mint']}})
        result = await self.rpc('getProgramAccounts', [str(self.program), {
            'encoding': 'base64', 'commitment': 'finalized', 'withContext': True, 'minContextSlot': floor,
            'filters': filters,
            'dataSlice': {'offset': layout['paid'], 'length': 12}}])
        if result['context']['slot'] < floor:
            raise RuntimeError('stale finalized claim counters')
        slot, counters, balances = result['context']['slot'], {}, {}
        for row in result['value']:
            account = row['account']
            raw = base64.b64decode(account['data'][0])
            if account['owner'] != str(self.program) or account['executable'] or len(raw) != 12:
                raise ValueError('invalid claim counter account')
            counters[row['pubkey']] = struct.unpack('<QI', raw)
            balances[row['pubkey']] = account['lamports']
        missing = [address for address in counters if address not in self.claim_cache or not self.claim_cache[address]['sealed']]
        slot, headers = await self.multiple(missing, slot, data_slice={'offset': 0, 'length': layout['$header']})
        for address, row in headers.items():
            if not row:
                raise RuntimeError('claim set changed during inventory')
            header = self.decode(row, kind)
            if header['storage_version'] != 2:
                raise ValueError('invalid composed claim storage version')
            if kind == 'Stage1ClaimSet':
                if header['mint'] != scope['mint'] or address != self.claim_address({'hill':header['hill'],'mint':header['mint']},header['week']):
                    raise ValueError('invalid composed claim inventory')
            elif header['role'] not in (0,1) or address != self.pda('s1v1_dung_claims',bytes(key(header['dung'])),bytes([header['role']])):
                raise ValueError('invalid DUNG claim inventory')
            if (header['paid'], header['claimed_count']) != counters[address]:
                raise RuntimeError('claim counters changed during header read')
            self.claim_cache[address] = {**header, 'bitmap': None}
        changed = [address for address, count in counters.items()
                   if self.claim_cache[address]['bitmap'] is None or
                   (self.claim_cache[address]['paid'], self.claim_cache[address]['claimed_count']) != count]
        paid_changes = [address for address in changed if counters[address] != (0, 0)]
        slot, bitmaps = await self.multiple(paid_changes, slot)
        for address in changed:
            saved = self.claim_cache[address]
            if counters[address] == (0, 0):
                if saved['paid'] or saved['claimed_count']:
                    raise ValueError('claim counters regressed')
                bitmap = bytes((saved['leaf_count'] + 7) // 8)
                header = saved
            else:
                row = bitmaps[address]
                if not row:
                    raise RuntimeError('claim set disappeared during inventory')
                header = self.decode(row, kind)
                raw = base64.b64decode(row['data'][0])
                bitmap = raw[layout['$header']:]
                if (header['paid'], header['claimed_count']) != counters[address]:
                    raise RuntimeError('claim counters changed during bitmap read')
                immutable = set(saved) - {'paid', 'claimed_count', 'bitmap', 'lamports'}
                if any(header[k] != saved[k] for k in immutable):
                    raise ValueError('claim set immutable header changed')
            if (len(bitmap) != (header['leaf_count'] + 7) // 8
                or sum(b.bit_count() for b in bitmap) != counters[address][1]
                or (header['leaf_count'] % 8 and bitmap and bitmap[-1] >> (header['leaf_count'] % 8))
                or counters[address][0] > header['total']):
                raise ValueError('invalid claim bitmap or counters')
            self.claim_cache[address] = {**header, 'bitmap': bitmap.hex()}
        return slot, {address: {**self.claim_cache[address], 'lamports': balances[address]} for address in counters}

    def validate_scope(self, scope, city, hill):
        if (scope['program'] != str(self.program) or scope['city'] != self.pda('s1v1_city')
            or hill['city'] != scope['city'] or scope['hill'] != self.pda('s1v1_hill',bytes(hill['canon_id']))
            or str(uuid.UUID(bytes=bytes(hill['canon_id']))) != str(scope['canon_id'])
            or city['season_anchor'] != scope['launch'] or city['publisher'] != str(self.signer.pubkey())):
            raise ValueError('admitted scope namespace or publisher changed')

    async def admission_bond(self, scope, floor=0):
        slot, rows = await self.multiple([scope['city'],scope['hill'],CLOCK],floor)
        hill = self.decode(rows[scope['hill']],'Stage1HillBond')
        self.validate_scope(scope,self.decode(rows[scope['city']],'Stage1CityConfig'),hill)
        return {'hill':scope['hill'],'city':scope['city'],'bonded':hill['bonded'],
                'bonded_at':hill['bonded_at'],'slot':slot,
                'now':struct.unpack_from('<q',base64.b64decode(rows[CLOCK]['data'][0]),32)[0],
                'evidence':hashlib.sha256(base64.b64decode(rows[scope['hill']]['data'][0])).hexdigest()}

    async def clock(self, floor=0):
        # Reads reuse the startup admission. Signing, submission and status
        # recovery still recheck genesis on every attempt.
        if self.genesis is None:
            await self.start()
        slot, rows = await self.multiple([CLOCK], floor)
        return {"slot": slot, "now": struct.unpack_from("<q", base64.b64decode(rows[CLOCK]["data"][0]), 32)[0]}

    async def recipient_registrations(self, people, floor=0):
        people = sorted(p for p in set(people) if not p.startswith("anonymous:"))
        addresses = {self.pda("s1v1_recipient", bytes(key(p))): p for p in people}
        slot, rows = await self.multiple(list(addresses), floor)
        registrations = {}
        for address, row in rows.items():
            if row is None:
                continue
            recipient = self.decode(row, "Stage1Recipient")
            if recipient["person"] != addresses[address]:
                raise ValueError("noncanonical recipient registration")
            registrations[recipient["person"]] = {k: recipient[k] for k in ("recipient", "registered_at")}
        return slot, registrations

    async def discover(self):
        await self.start()
        city_key = self.pda("s1v1_city")
        slot, rows = await self.multiple([city_key])
        city = self.decode(rows[city_key], "Stage1CityConfig")
        if city["publisher"] != str(self.signer.pubkey()):
            raise ValueError("configured publisher is not authorized")
        slot, hills = await self.filtered("Stage1HillBond", LAYOUTS["Stage1HillBond"]["city"], city_key, slot)
        slot, assets = await self.filtered("Stage1AssetConfig", LAYOUTS["Stage1AssetConfig"]["city"], city_key, slot)
        result = []
        for hill_key, hill in hills.items():
            for asset in assets.values():
                if not hill["bonded"] and asset["adapter"] != 254:
                    continue
                result.append({"program": str(self.program), "city": city_key, "hill": hill_key, "mint": asset["mint"],
                    "canon_id": str(uuid.UUID(bytes=bytes(hill["canon_id"]))), "launch": city["season_anchor"],
                    "next_week": hill["admitted_week"]})
        _, cursors = await self.multiple([self.cursor_address(s) for s in result], slot)
        for scope in result:
            row = cursors[self.cursor_address(scope)]
            if row:
                scope["next_week"] = self.decode(row, "Stage1SettlementCursor")["next_week"]
        if city['dung_start_week_plus_one']:
            config_key = self.pda('program_config')
            _, configs = await self.multiple([config_key], slot)
            config = self.decode(configs[config_key], 'ProgramConfig')
            for hill_key, hill in hills.items():
                if hill['bonded']:
                    result.append({'program':str(self.program),'city':city_key,'hill':hill_key,'mint':config['dung_mint'],
                        'kind':'dung','canon_id':str(uuid.UUID(bytes=bytes(hill['canon_id']))),'launch':city['season_anchor'],
                        'next_week':max(hill['dung_next_week'],city['dung_start_week_plus_one']-1)})
        return result

    async def observe_dung(self, scope, week, floor):
        if self.genesis is None:
            await self.start()
        state_key = self.pda('s1v1_dung_state')
        config_key = self.pda('program_config')
        slot, rows = await self.multiple([scope['city'],scope['hill'],CLOCK,state_key,config_key], floor)
        city = self.decode(rows[scope['city']], 'Stage1CityConfig')
        hill = self.decode(rows[scope['hill']], 'Stage1HillBond')
        self.validate_scope(scope,city,hill)
        if self.decode(rows[config_key],'ProgramConfig')['dung_mint'] != scope['mint']:
            raise ValueError('DUNG mint namespace changed')
        slot, mints = await self.filtered('Stage1DungMint', LAYOUTS['Stage1DungMint']['mint'], scope['mint'], slot)
        slot, sets = await self.cash_claim_inventory(scope, slot, kind='Stage1DungClaimSet')
        if any(v['dung'] not in mints for v in sets.values()) or mints and not rows[state_key]:
            raise RuntimeError('DUNG inventory changed during observation')
        if any(a != self.dung_address({**scope,'hill':m['hill']},m['week']) or m['city']!=scope['city'] for a,m in mints.items()):
            raise ValueError('noncanonical DUNG mint inventory')
        sets = {a:{**v,'week':mints[v['dung']]['week'],'hill':mints[v['dung']]['hill']}
                for a,v in sets.items()}
        slot, closing = await self.multiple([scope['city'],scope['hill'],state_key,config_key],slot)
        if any(rows[a] != closing[a] for a in closing):
            raise RuntimeError('DUNG scope changed during observation')
        return {'kind':'dung','slot':slot,'now':struct.unpack_from('<q',base64.b64decode(rows[CLOCK]['data'][0]),32)[0],
                'city':city,'hill':hill,'mints':mints,'sets':sets,'recipients':{},'receipts':[],
                'state':self.decode(rows[state_key],'Stage1DungState') if rows[state_key] else {'allocated_lifetime':0,'minted_lifetime':0}}

    async def observe(self, scope, week, floor):
        if scope.get('kind') == 'dung':
            return await self.observe_dung(scope, week, floor)
        if self.genesis is None:
            await self.start()
        asset_key = self.pda("s1v1_asset", bytes(key(scope["mint"])))
        earnings_key = self.pda("s1v1_earnings", bytes(key(scope["mint"])))
        cursor_key = self.cursor_address(scope)
        slot, rows = await self.multiple([scope["city"], scope["hill"], asset_key, cursor_key, CLOCK], floor)
        city = self.decode(rows[scope["city"]], "Stage1CityConfig")
        hill = self.decode(rows[scope["hill"]], "Stage1HillBond")
        asset = self.decode(rows[asset_key], "Stage1AssetConfig")
        cursor = self.decode(rows[cursor_key], "Stage1SettlementCursor") if rows[cursor_key] else None
        if (scope["program"] != str(self.program) or scope["city"] != self.pda("s1v1_city")
            or city["publisher"] != str(self.signer.pubkey()) or hill["city"] != scope["city"]
            or asset["city"] != scope["city"] or asset["mint"] != scope["mint"]
            or city["season_anchor"] != scope["launch"] or (not hill["bonded"] and asset["adapter"] != 254)
            or str(uuid.UUID(bytes=bytes(hill["canon_id"]))) != str(scope["canon_id"])):
            raise ValueError("admitted scope or publisher changed")
        # The ledger is token-wide: all hills for this mint are necessary, but
        # other mints and unrelated program accounts are not.
        slot, books = await self.filtered("Stage1WeekFunding", LAYOUTS["Stage1WeekFunding"]["mint"], scope["mint"], slot)
        slot, cursors = await self.filtered('Stage1SettlementCursor',LAYOUTS['Stage1SettlementCursor']['mint'],scope['mint'],slot)
        carried = {}
        for record in cursors.values():
            for hold in record.get('carried_holds',[]):
                if hold['source'] in books:
                    raise RuntimeError('funding closed during observation')
                if hold['source'] in carried:
                    raise ValueError('duplicate carried funding source')
                carried[hold['source']] = {**hold,'city':record['city'],'hill':record['hill'],'mint':record['mint'],
                    'asset':record['asset'],'due_week':hold['week'],'available':0,'harvested_net':0,'published':True,'closed_source':True}
        books.update(carried)
        slot, sets = await self.cash_claim_inventory(scope, slot)
        slot, lots = await self.filtered("Stage1PledgeLot", LAYOUTS['Stage1PledgeLot']['mint'], scope["mint"], slot)
        slot, boosts = await self.filtered('Stage1Boost', LAYOUTS['Stage1Boost']['mint'], scope['mint'], slot)
        streams = {}
        for address in boosts:
            slot, found = await self.filtered('Stage1BoostHill', LAYOUTS['Stage1BoostHill']['boost'], address, slot)
            streams.update(found)
        slot, closing_cursors = await self.filtered('Stage1SettlementCursor',LAYOUTS['Stage1SettlementCursor']['mint'],scope['mint'],slot)
        if cursors != closing_cursors:
            raise RuntimeError('funding cursors changed during observation')
        receipts, recipients = [], {}
        # Fence above EVERY read, including receipt and recipient batches. A
        # concurrent claim/harvest/publication changes the asset; retry instead
        # of treating a mixed-slot inventory as a durable accounting mismatch.
        slot, closing = await self.multiple([asset_key, earnings_key, scope["city"], scope["hill"], cursor_key], slot)
        if any(closing[k] != rows[k] for k in (asset_key, scope["city"], scope["hill"], cursor_key)):
            raise RuntimeError("asset or scope changed during inventory read")
        earnings = closing[earnings_key]
        token = base64.b64decode(earnings["data"][0])
        if earnings["owner"] != TOKEN or token[:32] != bytes(key(scope["mint"])) or token[32:64] != bytes(key(asset_key)):
            raise ValueError("wrong earnings custody")
        for addr, book in books.items():
            if addr != self.funding({**scope, "hill": book["hill"]}, book["week"]) or book["due_week"] != book["week"]:
                raise ValueError("noncanonical funding inventory")
        return {"slot": slot, "now": struct.unpack_from("<q", base64.b64decode(rows[CLOCK]["data"][0]), 32)[0],
            "city": city, "hill": hill, "boosts": boosts, "streams": streams, "asset": asset, "books": books, "sets": sets, "lots": list(lots.values()), "receipts": receipts,
            "recipients": recipients, "cursor": cursor, "carried":carried,"earnings_balance": struct.unpack_from("<Q", token, 64)[0]}

    def lookup_plan(self, slot, addresses):
        return {"kind": "lookup", "addresses": sorted(addresses)}

    async def lookup_exists(self, address, floor):
        return await self.lookup_deposit(address,floor) is not None

    async def lookup_deposit(self, address, floor):
        row = await self.rpc("getAccountInfo", [address, {"commitment": "finalized", "encoding": "base64", "minContextSlot": floor}])
        if row["context"]["slot"] < floor:
            raise RuntimeError("stale lookup read")
        if row['value'] and row['value']['owner']!=LOOKUP:
            raise ValueError('wrong lookup owner')
        return row['value']['lamports'] if row['value'] else None

    def dung_address(self, scope, week):
        return self.pda('s1v1_dung', bytes(key(scope['hill'])), struct.pack('<Q', week))

    def dung_claim_address(self, scope, week, role):
        return self.pda('s1v1_dung_claims', bytes(key(self.dung_address(scope, week))), bytes([role]))

    def encoded_instruction(self, name, args, addresses, remaining=()):
        snake = lambda n: re.sub(r'(?<!^)(?=[A-Z])', '_', n).lower()
        spec = next(i for i in self.idl['instructions'] if snake(i['name']) == name)
        def metas(accounts):
            result = []
            for account in accounts:
                if 'accounts' in account:
                    result.extend(metas(account['accounts']))
                else:
                    result.append(AccountMeta(key(addresses[snake(account['name'])]), account['isSigner'], account['isMut']))
            return result
        return Instruction(self.program, self.coder.instruction.encode(name, args), metas(spec['accounts']) + list(remaining))

    def packet_size(self, scope, op):
        tables = [AddressLookupTableAccount(Pubkey.default(),[key(a) for a in op['lookup_addresses']])] if op.get('lookup_addresses') else []
        message = MessageV0.try_compile(self.signer.pubkey(), [set_compute_unit_limit(1_400_000), *self.instructions(scope, op)], tables, Hash.default())
        return len(bytes(VersionedTransaction.populate(message, [Signature.default()])))

    def payout_batches(self, scope, leaves, *, dung=False):
        # One recipient across distinct sets; never multiple people in a batch.
        result, group = [], []
        def candidate(leaves):
            return {'kind': 'dung_claim' if dung else 'cash_claim', 'leaves': leaves,
                    'create_ata':leaves[0].get('create_ata',True)}
        for leaf in leaves:
            if group and (len(group)==4 or any(leaf[k]!=group[0][k] for k in ('person','recipient'))
                          or leaf['claim_set'] in {p['claim_set'] for p in group}):
                result.append(candidate(group))
                group = []
            if group and self.packet_size(scope,candidate(group+[leaf]))>1232:
                result.append(candidate(group))
                group = []
            group.append(leaf)
        if group:
            result.append(candidate(group))
        for op in result:
            if self.packet_size(scope,op)>1232:
                # Only a single unusually deep proof may need a temporary ALT.
                op['lookup_addresses'] = sorted({str(m.pubkey) for ix in self.instructions(scope,op) for m in ix.accounts if not m.is_signer})
                if self.packet_size(scope,op)>1232:
                    raise Blocked('payout_packet_too_large', {'index':op['leaves'][0]['index']})
        return result

    def composed_instructions(self, scope, op):
        kind, pub = op['kind'], str(self.signer.pubkey())
        addresses = dict(city=scope['city'], hill=scope['hill'], mint=scope['mint'],
                         publisher=pub, system_program=SYSTEM, token_program=TOKEN,
                         asset=self.pda('s1v1_asset', bytes(key(scope['mint']))), cursor=self.cursor_address(scope),
                         earnings=self.pda('s1v1_earnings', bytes(key(scope['mint']))),
                         program_config=self.pda('program_config'), state=self.pda('s1v1_dung_state'),
                         dung_mint_auth=self.pda('dung_mint_auth'))
        args, remaining, before = {}, [], []
        if kind in ('cash_claim', 'dung_claim'):
            leaves = op['leaves']
            first = leaves[0]
            if not 1 <= len(leaves) <= 4 or len({l['claim_set'] for l in leaves}) != len(leaves):
                raise ValueError('invalid payout batch')
            if any((l['person'], l['recipient']) != (first['person'], first['recipient']) for l in leaves):
                raise ValueError('payout batch recipients differ')
            addresses['registration'] = self.pda('s1v1_recipient', bytes(key(first['person'])))
            addresses['destination'] = str(get_associated_token_address(key(first['recipient']), key(scope['mint'])))
            before = [Instruction(ASSOCIATED_TOKEN_PROGRAM_ID, b'\x01', [
                AccountMeta(self.signer.pubkey(), True, True), AccountMeta(key(addresses['destination']), False, True),
                AccountMeta(key(first['recipient']), False, False), AccountMeta(key(scope['mint']), False, False),
                AccountMeta(key(SYSTEM), False, False), AccountMeta(key(TOKEN), False, False)])]
            if not op.get('create_ata',True):
                before = []
            args = {'person': key(first['person']), 'leaves': []}
            for leaf in leaves:
                item = {k: leaf[k] for k in ('index', 'amount')}
                item['proof'] = [{'hash': list(bytes.fromhex(p['hash'])), 'sum': p['sum']} for p in leaf['proof']]
                if kind == 'cash_claim':
                    item['terms'] = {**leaf['terms'], 'audit_hash': list(bytes.fromhex(leaf['terms']['audit_hash']))}
                else:
                    remaining.append(AccountMeta(key(leaf['dung']), False, True))
                remaining.append(AccountMeta(key(leaf['claim_set']), False, True))
                args['leaves'].append(item)
            name = 'claim_stage1_batch' if kind == 'cash_claim' else 'claim_stage1_dung_batch'
        elif kind == 'prepare_set':
            name, args = 'prepare_stage1_claim_set', {'leaf_count': op['count']}
            addresses.update(funding=self.funding(scope, op['week']), claim_set=self.claim_address(scope, op['week']))
        elif kind == 'boost':
            name, args = 'process_stage1_boost', {'remaining': op['remaining']}
            addresses.update(funding=self.funding(scope, op['week']), stream=op['stream'])
        elif kind in ('dung_publish', 'dung_prepare', 'dung_root'):
            addresses['dung'] = self.dung_address(scope, op['week'])
            if kind == 'dung_publish':
                name, args = 'publish_stage1_dung', {'week': op['week'], 'input': {**op['input'], 'source_snapshot': list(bytes.fromhex(op['input']['source_snapshot']))}}
            else:
                addresses['claim_set'] = self.dung_claim_address(scope, op['week'], op['role'])
                if kind == 'dung_prepare':
                    name, args = 'prepare_stage1_dung_claim_set', {'role': op['role'], 'leaf_count': op['count']}
                else:
                    name, args = 'publish_stage1_dung_claim_set', {'role': op['role'], 'root': {'root': list(bytes.fromhex(op['root'])), 'total': op['total'], 'leaf_count': op['count']}}
        elif kind == 'dung_skip':
            name, args = 'skip_stage1_dung_weeks', {'through': op['through'], 'snapshot': list(bytes.fromhex(op['snapshot'])), 'max_field_count': op['field_count'], 'total_postbond_tss_micros': op['tss']}
        elif kind in ('cash_close', 'dung_close'):
            name = 'close_stage1_claim_set' if kind == 'cash_close' else 'close_stage1_dung_claim_set'
            addresses.update(claim_set=op['claim_set'], rent_payer=op['rent_payer'])
        elif kind == 'funding_close':
            name = 'close_stage1_week_funding'
            addresses.update(funding=op['funding'],claim_set=self.claim_address(scope,op['week']),rent_payer=op['rent_payer'])
        elif kind == 'dung_mint_close':
            name = 'close_stage1_dung_mint'
            addresses.update(dung=op['dung'],rider_set=self.dung_claim_address(scope,op['week'],0),
                             backer_set=self.dung_claim_address(scope,op['week'],1),rent_payer=op['rent_payer'])
        else:
            return None
        return before + [self.encoded_instruction(name, args, addresses, remaining)]

    def instructions(self, scope, op):
        composed = self.composed_instructions(scope, op)
        if composed is not None:
            return composed
        pub = str(self.signer.pubkey())
        def meta(address, writable=False, signer=False):
            return AccountMeta(key(address), signer, writable)
        city, hill = scope["city"], scope["hill"]
        asset = self.pda("s1v1_asset", bytes(key(scope["mint"])))
        cursor = self.cursor_address(scope)
        earnings = self.pda("s1v1_earnings", bytes(key(scope["mint"])))
        kind, args = op["kind"], b""
        common = [meta(city), meta(hill, kind in ("init", "open")), meta(asset)]
        if kind == "lookup":
            account = key(op["address"])
            create = Instruction(key(LOOKUP), struct.pack("<IQB", 0, op["slot"], op["bump"]),
                [AccountMeta(account, False, True), meta(pub, False, True), meta(pub, True, True), meta(SYSTEM)])
            extend = Instruction(key(LOOKUP), struct.pack("<IQ", 2, len(op["addresses"])) + b"".join(bytes(key(p)) for p in op["addresses"]),
                [AccountMeta(account, False, True), meta(pub, False, True), meta(pub, True, True), meta(SYSTEM)])
            return [create, extend]
        if kind in ('lookup_deactivate','lookup_close'):
            metas = [meta(op['address'],True),meta(pub,False,True)]
            if kind=='lookup_close':
                metas.append(meta(pub,True))
            return [Instruction(key(LOOKUP),struct.pack('<I',3 if kind=='lookup_deactivate' else 4),metas)]
        if kind == "init":
            name, metas = "init_stage1_settlement", common + [meta(cursor, True), meta(pub, True, True), meta(SYSTEM)]
        elif kind == "open":
            name, args = "open_stage1_week", struct.pack("<Q", op["week"])
            metas = common + [meta(self.funding(scope, op["week"]), True), meta(pub, True, True), meta(SYSTEM), meta(cursor)]
        elif kind == "skip":
            name, args = "skip_stage1_empty_weeks", struct.pack("<Q", op["through"])
            metas = common + [meta(cursor, True), meta(earnings), meta(pub, False, True)]
            metas += [meta(self.funding(scope, w)) for w in range(op["from"], op["through"] + 1)]
        elif kind == "freeze":
            name, args = "freeze_stage1_snapshot", bytes.fromhex(op["snapshot"]) + struct.pack("<Q", op["cap"])
            metas = common + [meta(self.funding(scope, op["week"]), True), meta(str(self.program)), meta(pub, False, True), meta(cursor)]
        elif kind in ("prepare", "expire"):
            name = "prepare_stage1_hold" if kind == "prepare" else "expire_stage1_hold"
            args = struct.pack("<5Q", *op["remaining"]) if kind == "prepare" else struct.pack("<Q", op["week"])
            metas = [meta(city), meta(hill), meta(asset, kind == "expire"), meta(op["source"], True),
                     meta(self.funding(scope, op["week"])), meta(earnings), meta(pub, False, True)]
            metas.append(meta(cursor, True))
        elif kind == "publish":
            name = "publish_stage1_claim_set"
            args = bytes.fromhex(op["root"]) + op["total"].to_bytes(16, "little") + struct.pack("<I5Q", op["count"], *op["holds"])
            metas = [meta(city), meta(hill, True), meta(asset, True), meta(self.funding(scope, op["week"]), True),
                     meta(self.claim_address(scope, op["week"]), True), meta(earnings), meta(pub, True, True), meta(SYSTEM), meta(cursor, True)]
            metas += [meta(p, True) for p in sorted(op["sources"], key=lambda p: bytes(key(p)))]
        else:
            raise ValueError("unknown keeper instruction")
        return [Instruction(self.program, hashlib.sha256(f"global:{name}".encode()).digest()[:8] + args, metas)]

    async def prepare(self, scope, op, floor=0):
        await self.start()
        if self.version_pool is not None and not self.in_cycle:
            (await self.compatibility(self.version_pool)).require_stage1()
        floor = await self.authorize(op['kind'], floor)
        witness = None
        if op['kind'] in ('publish','dung_root'):
            address = self.claim_address(scope,op['week']) if op['kind']=='publish' else self.dung_claim_address(scope,op['week'],op['role'])
            addresses = [address]+([self.funding(scope,op['week'])] if op['kind']=='publish' else [])
            floor, rows = await self.multiple(addresses,floor)
            kind = 'Stage1ClaimSet' if op['kind']=='publish' else 'Stage1DungClaimSet'
            account = {**self.decode(rows[address],kind),'lamports':rows[address]['lamports'],
                       'bitmap':base64.b64decode(rows[address]['data'][0])[LAYOUTS[kind]['$header']:].hex()}
            witness = {'set':account,'slot':floor}
            if len(addresses)==2:
                witness['funding'] = {**self.decode(rows[addresses[1]],'Stage1WeekFunding'),'lamports':rows[addresses[1]]['lamports']}
        if op["kind"] == "lookup":
            history = await self.rpc('getAccountInfo',[SLOT_HASHES,{'encoding':'base64','commitment':'finalized','minContextSlot':floor}])
            if history['context']['slot'] < floor or not history['value']:
                raise RuntimeError("stale lookup creation slot")
            raw = base64.b64decode(history['value']['data'][0])
            if len(raw)<48 or struct.unpack_from('<Q',raw)[0]==0:
                raise RuntimeError('recent completed slot unavailable')
            # The current finalized bank's own slot need not yet appear in its
            # SlotHashes. Use the same completed-slot witness as the 1c runner.
            slot = struct.unpack_from('<Q',raw,8)[0]
            table, bump = Pubkey.find_program_address([bytes(self.signer.pubkey()), struct.pack("<Q", slot)], key(LOOKUP))
            await self.store.reserve_lookup(scope,op,str(table))
            op = {**op, "address": str(table), "slot": slot, "bump": bump}
        latest = await self.rpc("getLatestBlockhash", [{"commitment": "finalized", "minContextSlot": floor}])
        if latest["context"]["slot"] < floor:
            raise RuntimeError("stale blockhash read")
        tables = []
        if op.get("lookup"):
            row = await self.rpc("getAccountInfo", [op["lookup"], {"encoding": "base64", "commitment": "finalized", "minContextSlot": floor}])
            if row["context"]["slot"] < floor:
                raise RuntimeError("stale lookup read")
            if not row["value"] or row["value"]["owner"] != LOOKUP:
                raise ValueError("missing finalized lookup table")
            data = base64.b64decode(row["value"]["data"][0])
            if struct.unpack_from("<Q", data, 4)[0] != (1 << 64) - 1:
                raise ValueError("lookup table deactivated")
            if row['context']['slot'] <= struct.unpack_from('<Q',data,12)[0]:
                raise RuntimeError('lookup extension is not yet rooted')
            tables = [AddressLookupTableAccount(key(op["lookup"]), [Pubkey.from_bytes(data[i:i+32]) for i in range(56, len(data), 32)])]
        message = MessageV0.try_compile(self.signer.pubkey(), [set_compute_unit_limit(1_400_000), *self.instructions(scope, op)], tables, Hash.from_string(latest["value"]["blockhash"]))
        reserve = await self.check_sol(op,message,floor)
        tx = VersionedTransaction(message, [self.signer])
        if len(bytes(tx)) > 1232:
            raise ValueError("keeper transaction exceeds packet limit")
        if self.in_cycle:
            self.reserved_lamports += reserve
        return {"signature": str(tx.signatures[0]), "bytes": base64.b64encode(bytes(tx)).decode(),
                "last_valid_block_height": latest["value"]["lastValidBlockHeight"], "genesis": self.genesis, "operation_kind":op["kind"],
                **({'publication_witness':witness} if witness else {}),
                **({"lookup_address": op["address"]} if op["kind"] == "lookup" else {})}

    def verify_signed_operation(self, scope, op, signed):
        """Bind durable DUNG send/resend bytes to the checked publication plan."""
        try:
            tx = VersionedTransaction.from_bytes(base64.b64decode(signed['bytes'], validate=True))
            tx.verify_and_hash_message()
            # DUNG publication operations never use lookup transport. Recompile
            # with the retained blockhash to compare data, accounts and privileges.
            expected = MessageV0.try_compile(self.signer.pubkey(),
                [set_compute_unit_limit(1_400_000), *self.instructions(scope,op)], [], tx.message.recent_blockhash)
            if (tx.message != expected or str(tx.signatures[0]) != signed['signature'] or
                signed['genesis'] != self.genesis or signed.get('operation_kind') != op['kind']):
                raise ValueError('signed operation differs')
        except Exception:
            raise Blocked('dung_signed_operation_mismatch', {'week':op['week'], 'operation':op['kind']}) from None

    async def submit(self, signed):
        await self.start()
        if signed["genesis"] != self.genesis:
            raise ValueError("signed keeper transaction belongs to a different genesis")
        if signed.get('operation_kind'):
            await self.authorize(signed['operation_kind'])
        # No new blockhash or transaction rebuilding here.
        returned = await self.rpc("sendTransaction", [signed["bytes"], {"encoding": "base64", "preflightCommitment": "finalized", "skipPreflight": False, "maxRetries": 0}])
        if returned != signed["signature"]:
            raise RuntimeError("RPC returned a different transaction signature")

    async def check_sol(self, op, message, floor):
        # The publisher is also the ATA sponsor and transaction fee payer.
        balance = await self.rpc('getBalance',[str(self.signer.pubkey()),{'commitment':'finalized','minContextSlot':floor}])
        fee = await self.rpc('getFeeForMessage',[base64.b64encode(to_bytes_versioned(message)).decode(),{'commitment':'finalized','minContextSlot':floor}])
        if min(balance['context']['slot'],fee['context']['slot']) < floor or fee['value'] is None:
            raise RuntimeError('fresh sponsor balance/fee unavailable')
        definitions={v['name']:v['type'] for v in self.idl.get('types',[])+self.idl['accounts']}
        def width(t):
            if isinstance(t,str):
                return {'u8':1,'bool':1,'u16':2,'u32':4,'i32':4,'u64':8,'i64':8,'u128':16,'publicKey':32}[t]
            if 'array' in t: return width(t['array'][0])*t['array'][1]
            if 'option' in t: return 1+width(t['option'])
            return sum(width(f['type']) for f in definitions[t['defined']]['fields'])
        def account_size(name):
            total=8
            for f in definitions[name]['fields']:
                if isinstance(f['type'],dict) and 'vec' in f['type']:
                    if (name,f['name'])!=('Stage1SettlementCursor','carriedHolds'):
                        raise ValueError('unknown variable rent layout')
                    total+=4+26*width(f['type']['vec'])  # Rust #[max_len(26)].
                else:
                    total+=width(f['type'])
            return total
        sizes = {'init':[account_size('Stage1SettlementCursor')],
                 'open':[account_size('Stage1WeekFunding')],
                 'dung_publish':[account_size('Stage1DungMint'),account_size('Stage1DungState')],
                 'prepare_set':[275+(op.get('count',0)+7)//8],
                 'dung_prepare':[140+(op.get('count',0)+7)//8],
                 'lookup':[56+32*len(op.get('addresses',[]))]}.get(op['kind'],[])
        if op['kind'] in ('cash_claim','dung_claim') and op.get('create_ata',True):
            sizes=[165]
        rent=0
        for size in sizes:
            if size not in self.rent_cache:
                self.rent_cache[size]=await self.rpc('getMinimumBalanceForRentExemption',[size,{'commitment':'finalized'}])
            rent+=self.rent_cache[size]
        required = fee['value']+rent
        if balance['value'] < required+(self.reserved_lamports if self.in_cycle else 0):
            raise SponsorUnfunded('sponsor_unfunded')
        return required

    def destination(self, scope, leaf):
        return str(get_associated_token_address(key(leaf['recipient']),key(scope['mint'])))

    def destination_fingerprint(self, scope, leaf):
        from .stage1_keeper_merkle import digest
        # The database itself is immutably genesis-bound.
        return digest(['stage1-sponsored-ata-v1',str(self.program),scope['mint'],self.destination(scope,leaf)])

    async def destinations(self, scope, leaves, floor):
        addresses = {self.destination(scope,l):l for l in leaves}
        slot, rows = await self.multiple(list(addresses),floor)
        result = {}
        for address,leaf in addresses.items():
            row = rows[address]
            if row is None:
                result[address] = 'missing'
                continue
            raw = base64.b64decode(row['data'][0])
            if (row['owner']!=TOKEN or row['executable'] or len(raw)!=165 or
                raw[:32]!=bytes(key(scope['mint'])) or raw[32:64]!=bytes(key(leaf['recipient']))):
                result[address] = 'wrong_owner'
            else:
                result[address] = 'valid' if raw[108]==1 else 'frozen' if raw[108]==2 else 'closed'
        return slot,result

    async def sponsorship_evidence(self,scope,fingerprint,signature):
        from .stage1_keeper_merkle import digest
        tx=await self.rpc('getTransaction',[signature,{'encoding':'json','commitment':'finalized','maxSupportedTransactionVersion':0}])
        if not tx:
            return None
        meta=tx['meta']
        if meta['err']:
            return {'established':False,'slot':tx['slot']}
        if meta.get('postTokenBalances') is None:
            return None
        message=tx['transaction']['message'];loaded=meta.get('loadedAddresses') or {}
        keys=message['accountKeys']+loaded.get('writable',[])+loaded.get('readonly',[])
        for token in meta['postTokenBalances']:
            if token['mint']!=scope['mint']:
                continue
            i=token['accountIndex']
            if digest(['stage1-sponsored-ata-v1',str(self.program),scope['mint'],keys[i]])==fingerprint:
                return {'established':True,'slot':tx['slot'],'signature':signature,
                    'sponsored_ata_deposits_lamports':meta['postBalances'][i] if meta['preBalances'][i]==0 else 0}
        # RPC token metadata can be incomplete. Only a finalized failure proves
        # this atomic create+claim attempt did not establish the destination.
        return None

    async def lookup_state(self, address, floor):
        slot,rows = await self.multiple([address,SLOT_HASHES],floor)
        row=rows[address]
        if not row:
            return 'missing',0
        if row['owner']!=LOOKUP:
            raise ValueError('wrong lookup owner')
        raw=base64.b64decode(row['data'][0])
        if len(raw)<56 or raw[21]!=1 or raw[22:54]!=bytes(self.signer.pubkey()):
            raise Blocked('lookup_authority_mismatch',{})
        deactivated=struct.unpack_from('<Q',raw,4)[0]
        if deactivated==(1<<64)-1:
            return 'active',row['lamports']
        history=base64.b64decode(rows[SLOT_HASHES]['data'][0])
        slots=[struct.unpack_from('<Q',history,i)[0] for i in range(8,len(history),40)]
        return ('cooling' if deactivated>=slot or deactivated in slots else 'closeable'),row['lamports']

    async def lookup_close_witness(self,address):
        """Exact successful ALT close to its signing authority, never absence alone."""
        history=await self.rpc('getSignaturesForAddress',[address,{'commitment':'finalized','limit':1000}])
        for row in history:
            if row['err'] or row.get('confirmationStatus')!='finalized':
                continue
            tx=await self.rpc('getTransaction',[row['signature'],{'encoding':'json','commitment':'finalized','maxSupportedTransactionVersion':0}])
            if not tx or tx['meta']['err']:
                continue
            message=tx['transaction']['message'];meta=tx['meta']
            loaded=meta.get('loadedAddresses') or {}
            keys=message['accountKeys']+loaded.get('writable',[])+loaded.get('readonly',[])
            for ix in message['instructions']:
                if keys[ix['programIdIndex']]!=LOOKUP or base58.b58decode(ix['data'])!=struct.pack('<I',4):
                    continue
                if [keys[i] for i in ix['accounts']]!=[address,str(self.signer.pubkey()),str(self.signer.pubkey())]:
                    continue
                index=keys.index(address)
                if meta['postBalances'][index]!=0 or meta['preBalances'][index]<=0:
                    continue
                return {'signature':row['signature'],'slot':tx['slot'],
                    'fee':meta['fee'] if keys[0]==str(self.signer.pubkey()) else 0,
                    'lookup_refund_lamports':meta['preBalances'][index]}
        return None

    async def status(self, signed):
        return (await self.status_batch([signed]))[signed['signature']]

    async def status_batch(self, signed):
        await self.start()
        if any(s['genesis'] != self.genesis for s in signed):
            raise ValueError('persisted signature belongs to a different genesis')
        result,absent = {},[]
        for start in range(0,len(signed),256):
            chunk=signed[start:start+256]
            response=await self.rpc('getSignatureStatuses',[[s['signature'] for s in chunk],{'searchTransactionHistory':True}])
            if len(response['value'])!=len(chunk):
                raise RuntimeError('incomplete signature batch')
            for s,row in zip(chunk,response['value']):
                if row:
                    result[s['signature']] = ({'state':'failed' if row['err'] else 'finalized','slot':row['slot'],
                        'paused':self.paused_error(row['err']),'unfunded':self.insufficient_funds(row['err'])}
                        if row['confirmationStatus']=='finalized' else {'state':'pending'})
                else:
                    absent.append(s)
        if not absent:
            return result
        slot=await self.rpc('getSlot',[{'commitment':'finalized'}])
        block=await self.rpc('getBlock',[slot,{'commitment':'finalized','transactionDetails':'none','rewards':False,'maxSupportedTransactionVersion':0}])
        expired=[]
        for s in absent:
            if not block or block.get('blockHeight') is None:
                result[s['signature']]={'state':'unknown'}
            elif block['blockHeight'] <= s['last_valid_block_height']:
                result[s['signature']]={'state':'absent'}
            else:
                expired.append(s)
        for start in range(0,len(expired),256):
            chunk=expired[start:start+256]
            witness=await self.rpc('getSignatureStatuses',[[s['signature'] for s in chunk],{'searchTransactionHistory':True}])
            if witness['context']['slot']<slot or len(witness['value'])!=len(chunk):
                raise RuntimeError('stale signature absence after expiry')
            for s,row in zip(chunk,witness['value']):
                result[s['signature']]={'state':'pending'} if row else {'state':'expired','slot':witness['context']['slot']}
        return result

    def operation_applied(self, scope, op, observed):
        kind = op["kind"]
        if kind.startswith('dung_'):
            if kind == 'dung_skip':
                return observed['hill']['dung_next_week'] == op['through']+1
            dung = observed['mints'].get(self.dung_address(scope,op['week']))
            if kind == 'dung_publish':
                return bool(dung and dung['week']==op['week'] and observed['hill']['dung_next_week']==op['week']+1)
            s = observed['sets'].get(self.dung_claim_address(scope,op['week'],op['role']))
            if kind == 'dung_prepare':
                return bool(s and s['leaf_count']==op['count'])
            return bool(s and s['sealed'] and s['root']==op['root'] and s['total']==op['total'] and s['leaf_count']==op['count'])
        if kind == "init":
            return observed["cursor"] is not None
        if kind == "skip":
            return bool(observed["cursor"] and observed["cursor"]["next_week"] == op["through"] + 1)
        if kind == "lookup":
            # An expired creation needs explicit inspection; never blindly
            # recreate a table whose historic signature has become unavailable.
            return True
        if kind == 'prepare_set':
            claim_set = observed['sets'].get(self.claim_address(scope, op['week']))
            return bool(claim_set and claim_set['leaf_count'] == op['count'])
        if kind == 'boost':
            stream = observed['streams'].get(op['stream'])
            return bool(stream and stream['processed'] and stream['processed_week'] == op['week'] and stream['holds'] == op['remaining'])
        if kind in ("prepare", "expire"):
            source = observed["books"].get(op["source"])
            if not source:
                return kind=='expire' and op.get('closed_source') and observed['cursor']['holds'][op['born']%26]==0
            return (source["proposed"] and source["proposal_week"] == op["week"] and source["proposal_remaining"] == op["remaining"]) if kind == "prepare" else not any(source["holds"])
        book = observed["books"].get(self.funding(scope, op["week"]))
        if kind == "open":
            return book is not None
        if kind == "freeze":
            return bool(book and book["snapshot"] == op["snapshot"] and book["cap"] == op["cap"])
        s = observed["sets"].get(self.claim_address(scope, op["week"]))
        return bool(s and s["root"] == op["root"] and s["total"] == op["total"] and s["leaf_count"] == op["count"] and s["sealed"] and book and book["holds"] == op["holds"])

    def verify_operation(self, scope, op, observed):
        if not self.operation_applied(scope, op, observed):
            raise Blocked("finalized_effect_mismatch", {"operation": op["kind"], "slot": observed["slot"]})

    def verify_plan(self, scope, job, observed):
        if scope.get('kind') == 'dung':
            if observed['hill']['dung_next_week'] != job['through_week']+1:
                raise Blocked('dung_cursor_mismatch', {'week':job['week']})
            for op in job['operations']:
                self.verify_operation(scope,op,observed)
            return
        if observed["cursor"]["next_week"] != job["through_week"] + 1:
            raise Blocked("cursor_mismatch", {"week": job["week"]})
        for source in job["sources"]:
            if source['kind'] == 'boost':
                stream = observed['streams'].get(source['stream'])
                if not stream or stream['holds'][source['tranche']] != job['allocation']['holds'][source['id']]:
                    raise Blocked('boost_hold_mismatch', {'source': source['id']})
                continue
            book = observed["books"].get(source["id"])
            if any(op["kind"] == "skip" for op in job["operations"]):
                if book and (book["available"] or book["harvested_net"] or book["lineage"] != "00" * 32 or book["published"]):
                    raise Blocked("skip_mismatch", {"source": source["id"]})
            elif not book or book["holds"] != job["allocation"]["holds"][source["id"]] or book["pool"] != job["allocation"]["pool"][source["id"]]:
                raise Blocked("hold_mismatch", {"source": source["id"]})
