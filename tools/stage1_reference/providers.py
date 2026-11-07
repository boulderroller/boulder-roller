"""Offline parsing/admission of the SAME provider account bytes as the program.

This verifies snapshots and simulated epoch transitions, not provider execution.
Authority and pinned source/layout citations: STAGE1_SPEC section 3.1.
"""
from copy import deepcopy
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
import base64
import json
import struct

TOKEN = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
IDENTITIES = {
    "jitoSOL": ("jito-pool", "jito-mint", "SPoo1Ku8WFXoNDMHPsrGSTSG1Y47rzgn41SLUNakuHy", "Jito4APyf642JPZPx3hGc6WWJ8zPKtRbRs4P815Awbb", "J1toso1uCk3RLmjorhTtrVwY9HJ7X8V9yYac6Y7kGCPn"),
    "mSOL": ("msol-state", "msol-mint", "MarBmsSgKXdrN1egZf5sqe1TMai9K1rChYNDJgjq7aD", "8szGkuLTAux9XMgZ2vtY39jVSowEcpBfFfD8hXSEqdGC", "mSoLzYCxHdYgdzU16g5QSh3i5K3z3KZK7ytfqcJm7So"),
    "JupSOL": ("jup-pool", "jup-mint", "SPMBzsVUuoHA4Jm6KunbsotaahvVikZs1JyTW6iJvbn", "8VpRhuxa7sUUepdY3kQiTmX9rS5vx4WgaXiAnXq4KCtr", "jupSoLaHXQiZZTSfEWMTRRgpnyFm8f6sZdosWBjx93v"),
}
FIXTURES = Path(__file__).resolve().parents[2] / "protocol/anchor/tests/fixtures/stage1_providers"


def pubkey(value):
    number = 0
    for char in value:
        number = number * 58 + "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz".index(char)
    return number.to_bytes(32, "big")


def check(condition):
    if not condition:
        raise ValueError("invalid provider identity, layout or mint")


@dataclass(frozen=True)
class Account:
    address: str
    owner: str
    data: bytes
    executable: bool = False


def snapshot(name):
    result = []
    for filename in IDENTITIES[name][:2]:
        raw = json.loads((FIXTURES / f"{filename}.json").read_text())
        account = raw["account"]
        result.append(Account(raw["pubkey"], account["owner"], base64.b64decode(account["data"][0]), account["executable"]))
    return tuple(result)


@dataclass(frozen=True)
class Observation:
    numerator: int
    denominator: int
    current: bool
    update_epoch: int | None
    exits_verified: bool

    @property
    def rate(self):
        return Fraction(self.numerator, self.denominator)


def validate_identity(name, accounts, epoch):
    check(name in IDENTITIES and len(accounts) == 2 and type(epoch) is int and epoch >= 0)
    state, mint = accounts
    _, _, owner, address, mint_address = IDENTITIES[name]
    check(state.address == address and state.owner == owner and not state.executable
          and mint.address == mint_address and mint.owner == TOKEN and not mint.executable)


def observe(name, accounts, epoch):
    validate_identity(name, accounts, epoch)
    state, mint = accounts
    mint_address = IDENTITIES[name][4]
    data, token = state.data, mint.data
    check(len(token) == 82 and token[44:46] == b"\x09\x01"
          and int.from_bytes(token[:4], "little") in (0, 1)
          and int.from_bytes(token[46:50], "little") in (0, 1))
    def u64(at):
        return struct.unpack_from("<Q", data, at)[0]
    if name == "mSOL":
        check(len(data) == 2616 and data[:8] == bytes.fromhex("d8926b5e684bb6b1")
              and data[8:40] == pubkey(mint_address) and data[608] in (0, 1)
              and data[617] in (0, 1) and data[638] in (0, 1, 2))
        total = sum(u64(at) for at in (376, 226, 496, 568))
        check(total <= 2**64 - 1 and total >= u64(528))
        n, d = total - u64(528), u64(504)
        current, updated, exits = True, None, True
    else:
        check(len(data) == 611 and data[0] == 1 and data[162:194] == pubkey(mint_address)
              and data[226:258] == pubkey(TOKEN))
        n, d, updated = u64(258), u64(266), u64(274)
        check(updated <= epoch)
        cursor = 330
        def fee():
            nonlocal cursor
            denominator, numerator = struct.unpack_from("<QQ", data, cursor)
            cursor += 16
            check(numerator <= denominator)
            return numerator, denominator
        def tag(width, maximum):
            nonlocal cursor
            value = data[cursor]
            cursor += 1
            check(value <= maximum)
            if value:
                if width == 16:
                    fee()
                else:
                    cursor += width
            check(cursor <= len(data))
            return bool(value)
        fee(); tag(16, 2); tag(32, 1)
        preferred = tag(32, 1)
        fee(); stake_fee = fee(); next_stake = tag(16, 2)
        check(data[cursor] <= 100); cursor += 1
        tag(32, 1); fee()
        check(data[cursor] <= 100); cursor += 1
        authority = tag(32, 1)
        sol_fee = fee(); next_sol = tag(16, 2)
        check(cursor + 16 <= len(data))
        current = updated == epoch
        exits = not any((preferred, authority, next_stake, next_sol)) and not any(data[282:330]) and stake_fee == sol_fee == (1, 1000)
    check(n > 0 and d > 0 and int.from_bytes(token[36:44], "little") <= d)
    return Observation(n, d, current, updated, exits)


def inspect(name, accounts, epoch):
    """Wrong identity is fatal; authentic unreadable accounting is unavailable."""
    validate_identity(name, accounts, epoch)
    try:
        return observe(name, accounts, epoch)
    except (ValueError, IndexError, struct.error, OverflowError):
        return None


def outage_marker(observation):
    # Opaque byte churn cannot indefinitely strand principal. No update-history
    # claim is possible for opaque state; native SPL epochs retain their witness.
    return ("opaque",) if observation is None else ("epoch", observation.update_epoch)


@dataclass
class Admission:
    quote: Observation | None = None
    epoch: int | None = None
    numeric_revision: int = 0
    stale_since: int | None = None
    outage_marker: tuple | None = None


class ProviderBook:
    def __init__(self):
        self.assets = {name: Admission() for name in IDENTITIES}

    def fresh(self, name, epoch):
        return self.assets[name].epoch == epoch and self.assets[name].quote is not None

    def refresh(self, name, accounts, epoch):
        observation = observe(name, accounts, epoch)
        if not observation.current:
            raise ValueError("stale provider epoch")
        admitted = self.assets[name]
        check(admitted.epoch is None or admitted.epoch <= epoch)
        admitted.stale_since = admitted.outage_marker = None
        if self.fresh(name, epoch):
            return admitted.quote.rate
        if admitted.quote is None or admitted.quote.rate != observation.rate:
            admitted.numeric_revision += 1
        admitted.quote, admitted.epoch = observation, epoch
        admitted.stale_since = admitted.outage_marker = None
        return admitted.quote.rate

    def refresh_backed(self, names, accounts, epoch):
        """Atomic bounded slot refresh. Missing/substituted input never means stale."""
        before = deepcopy(self.assets)
        try:
            check(set(names) == set(accounts))
            readable = set()
            for name in names:
                observation = inspect(name, accounts[name], epoch)
                if observation is not None:
                    readable.add(name)
                    if observation.current:
                        self.refresh(name, accounts[name], epoch)
            return {name: self.assets[name].quote.rate for name in names
                    if name in readable and self.fresh(name, epoch)
                    and not self.lagging(name, accounts[name], epoch)}
        except Exception:
            self.assets = before
            raise

    def lagging(self, name, accounts, epoch):
        observation = inspect(name, accounts, epoch)
        return (observation is not None and observation.update_epoch is not None
                and observation.update_epoch == epoch - 1)

    def campaign_quotes(self, names, accounts, epoch):
        fresh = self.refresh_backed(names, accounts, epoch)
        lagging = {name: observe(name, accounts[name], epoch).rate for name in names
                   if self.lagging(name, accounts[name], epoch)}
        return fresh, lagging

    def apply_campaign(self, model, names, accounts, epoch):
        """Apply every backed slot's classification anew before a bond attempt."""
        before, model_before = deepcopy(self.assets), deepcopy(model.__dict__)
        try:
            fresh, lagging = self.campaign_quotes(names, accounts, epoch)
            for name in names:
                if self.fresh(name, epoch):
                    # Preserve the quote for exits even when it cannot support
                    # intake, founding membership, threshold value or harvest.
                    model.observe_rate(name, self.assets[name].quote.rate)
                else:
                    model.mark_rate_stale(name)
                if name in lagging:
                    model.mark_rate_lagging(name, lagging[name])
                model.assets[name].readable = inspect(name, accounts[name], epoch) is not None
            return fresh, lagging
        except Exception:
            self.assets, model.__dict__ = before, model_before
            raise

    def record_outage(self, name, accounts, epoch, now):
        observation = inspect(name, accounts, epoch)
        check((observation is None or not observation.current) and not self.fresh(name, epoch)
              and not self.lagging(name, accounts, epoch))
        admitted = self.assets[name]
        check(admitted.epoch is not None and admitted.epoch < epoch)
        marker = outage_marker(observation)
        if admitted.stale_since is None or admitted.outage_marker != marker:
            admitted.stale_since, admitted.outage_marker = now, marker

    def exit_rate(self, name, accounts, epoch, now):
        observation = inspect(name, accounts, epoch)
        if self.fresh(name, epoch):
            return self.assets[name].quote.rate
        if observation is not None and observation.current:
            raise ValueError("current rate must be admitted")
        check(not self.lagging(name, accounts, epoch))
        admitted = self.assets[name]
        check(admitted.outage_marker == outage_marker(observation)
              and admitted.stale_since is not None and now >= admitted.stale_since + 604800)
        return None
