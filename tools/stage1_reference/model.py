"""Executable, transactional OFFLINE state machine for ratified stage 1.

All money is integer base units; rates/weights are exact rationals. Caller-fed
identity, canon, rates, board and liquidity are trusted simulation inputs, not
proof of provider state or human uniqueness. See STAGE1_SPEC.md for authority.
"""

from collections import defaultdict
from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from fractions import Fraction
from functools import wraps
import json

from .arithmetic import apportion, ceil, integer, median_cap, redistribute
from .config import Config
from .merkle import ClaimSet, Context

DAY = 86400
WEEK = 7 * DAY
USDC = "USDC"
# Claude's default, revisable by Tim (STAGE1_SPEC §§6, 8.2).
BOOST_START_HORIZON = 13
BOOST_MIN_TRANCHE = 1_000_000
DUNG_TSS_CEILING = 20_000_000_000
DUNG_CLAIM_WAIT = 172800


def atomic(method):
    """Rejected actions do not partially mutate custody, receipts or snapshots."""
    @wraps(method)
    def run(self, *args, **kwargs):
        before = deepcopy(self.__dict__)
        try:
            result = method(self, *args, **kwargs)
            self.check()
            return result
        except Exception:
            self.__dict__ = before
            raise
    return run


@dataclass
class Asset:
    decimals: int
    rate: Fraction
    observed_at: int
    # Provider-specific expiry is a trusted offline input, like the rate.
    # None retains the explicit adapter-expiry input used by older scenarios.
    fresh_until: int | None = None
    # Authenticated prior-epoch quote: founding membership only, zero line value.
    lagging: bool = False
    lagging_rate: Fraction | None = None
    # An authenticated decode failure blocks new value, not cached exit rights.
    readable: bool = True


@dataclass
class Lot:
    id: str
    owner: str
    hill: str
    asset: str
    units: int
    basis: int
    lock_weeks: int
    lock_end: int | None = None
    founding: bool = False
    notice_at: int | None = None
    notice_basis: int = 0
    exiting: bool = False
    owner_units: int = 0


@dataclass
class Hill:
    id: str
    bonded_at: int | None = None
    founder: str | None = None
    board: tuple[str, ...] = ()
    legend: str | None = None
    next_settle: int = 0


@dataclass(frozen=True)
class Ride:
    receipt: str
    hill: str
    person: str
    ridden_at: int
    uploaded_at: int
    tss: int


@dataclass(frozen=True)
class Snapshot:
    week: int
    live: bool
    bonded: bool
    field: bool
    board: tuple[str, ...]
    legend: str | None
    rides: tuple[Ride, ...]
    backers: tuple[tuple[str, Fraction], ...]
    assets: tuple[str, ...]


@dataclass(frozen=True)
class Tranche:
    source: str
    hill: str
    asset: str
    amount: int
    born: int
    due: int
    kind: str                  # yield, sponsor, boost
    bucket: str = "full"      # full, ascents, top, legend, cap, pool
    ride_start: int | None = None
    ride_end: int | None = None
    last_ride_week: int | None = None
    sources: tuple[str, ...] = ()  # lineage when equivalent same-age pots coalesce
    person: str | None = None  # earned share waiting for this person's recipient


@dataclass(frozen=True)
class Boost:
    id: str
    funder: str
    hills: tuple[str, ...]
    amount: int
    start_week: int
    weeks: int
    last_ride_week: int
    schedule: tuple[tuple[str, int, int], ...]


@dataclass
class Ledger:
    deposited: int = 0         # custody input, never rider income
    returned: int = 0          # principal and pre-bond owner returns
    realized: int = 0          # cumulative units actually swept out of lots
    cash: int = 0
    fees: int = 0              # lifetime assessed = paid + due
    fees_paid: int = 0
    paid: int = 0
    custody: int = 0           # current earnings/sponsor custody


@dataclass(frozen=True)
class DungMint:
    potential: int
    riders: dict[str, int]
    backers: dict[str, int]
    unminted: int


@dataclass(frozen=True)
class Settlement:
    hill: str
    week: int
    claims: dict[str, ClaimSet]
    caps: dict[str, int]
    dung: DungMint


class Model:
    def __init__(self, config: Config, launch: int, city="philadelphia", deployment="offline-stage1-v1"):
        integer(launch)
        date = datetime.fromtimestamp(launch, timezone.utc)
        if (date.weekday(), date.hour, date.minute, date.second) != (config.weekday, config.hour, 0, 0):
            raise ValueError("city launch must be a configured week boundary")
        self.config = config
        self.launch = self.now = launch
        self.city, self.deployment = city, deployment
        self.assets = {}
        self.hills = {}
        self.lots = {}
        self.ledgers = {USDC: Ledger()}
        self.recipients = {}
        self.rides = []
        self.receipts = set()
        self.fields = defaultdict(set)
        self.openings = {}     # (hill, week): immutable opening live/backer state
        self.snapshots = {}
        self.tranches = []
        self.settlements = {}
        self.funding_records = {}  # (hill, week, asset): immutable rent payer
        self.income_weeks = set()  # Includes gross harvest entirely consumed by fee.
        self.claim_bits = {}
        self.dung_claim_bits = {}
        self.dung_minted = 0
        self.dung_allocated = 0  # Lifetime issuance ledger survives weekly closure.
        self.dung_mint = None
        self.dung_tss_ceiling = 0
        self.dung_start_week = None
        self.dung_records = {}
        self.dung_next_week = {}
        self.dung_published_sets = {}
        self.dung_roles = {}
        self.dung_week_minted = defaultdict(int)
        self.dung_rent_payers = {}
        self.serial = 0
        self.caps = (config.token_cap, config.hill_cap, config.total_cap)
        self.pending_caps = None
        self.boosts = {}
        self.held_basis = 0
        self.asset_basis = defaultdict(int)
        self.hill_basis = defaultdict(int)

    @property
    def week(self):
        return (self.now - self.launch) // WEEK

    def uid(self, prefix):
        self.serial += 1
        return f"{prefix}-{self.serial:08d}"

    def rate(self, lot):
        return self.assets[lot.asset].rate

    def backing(self, hill):
        campaign = self.hills[hill].bonded_at is None
        # Fresh slots alone reach the line. After bonding, excluded lots
        # remain inactive until owner conversion. Active weekly valuation still
        # uses the most recent admitted rate, as specified in section 2.
        return sum(min(lot.basis, int(lot.units * self.rate(lot))) for lot in self.lots.values()
                   if lot.hill == hill and not lot.exiting
                   and (self._fresh(lot.asset) and self.assets[lot.asset].readable
                        and not self.assets[lot.asset].lagging
                        if campaign else lot.lock_end is not None))

    def _change_basis(self, asset, hill, amount):
        self.held_basis += amount
        self.asset_basis[asset] += amount
        self.hill_basis[hill] += amount

    def _fresh(self, asset):
        expiry = self.assets[asset].fresh_until
        return expiry is None or self.now < expiry

    def _exit_rate(self, asset):
        if self._fresh(asset):
            return self.assets[asset].rate
        if self.now < self.assets[asset].fresh_until + WEEK:
            raise ValueError("rate stale for less than seven days")
        return None

    @atomic
    def allow_asset(self, asset, decimals, rate):
        if not asset or asset in self.ledgers or not isinstance(asset, str):
            raise ValueError("asset already exists or is reserved")
        integer(decimals)
        if decimals > 18 or not isinstance(rate, (int, Fraction)) or isinstance(rate, bool) or rate <= 0:
            raise ValueError("invalid exact rate or decimals")
        self.assets[asset] = Asset(decimals, Fraction(rate), self.now)
        self.ledgers[asset] = Ledger()

    @atomic
    def add_hill(self, hill):
        if not isinstance(hill, str) or not hill or hill in self.hills:
            raise ValueError("hill identity must be unique")
        self.hills[hill] = Hill(hill, next_settle=self.week)
        self.openings[hill, self.week] = (False, False, ())

    @atomic
    def register_person(self, person, recipient):
        if not person or not recipient or person in self.recipients:
            raise ValueError("identity already registered or empty")
        self.recipients[person] = recipient

    @atomic
    def observe_rate(self, asset, rate, *, observed_at=None, fresh_until=None):
        if not isinstance(rate, (int, Fraction)) or isinstance(rate, bool) or rate <= 0:
            raise ValueError("positive exact redemption rate required")
        observed_at = self.now if observed_at is None else integer(observed_at)
        if fresh_until is not None:
            integer(fresh_until, observed_at + 1)
        if observed_at > self.now or (fresh_until is not None and self.now >= fresh_until):
            return False  # Rejection never changes the admitted quote or expiry.
        if fresh_until is not None:
            fresh_until = max(fresh_until, self.assets[asset].fresh_until or fresh_until)
        self.assets[asset].rate = Fraction(rate)
        self.assets[asset].observed_at = observed_at
        self.assets[asset].fresh_until = fresh_until
        self.assets[asset].lagging = False
        self.assets[asset].lagging_rate = None
        self.assets[asset].readable = True
        return True

    @atomic
    def mark_rate_stale(self, asset):
        """Trusted expiry input, never a rejected observation or early revocation."""
        expiry = self.assets[asset].fresh_until
        if expiry is not None and self.now < expiry:
            raise ValueError("admitted freshness has not expired")
        if expiry is None:
            self.assets[asset].fresh_until = self.now
        self.assets[asset].lagging = False
        self.assets[asset].lagging_rate = None

    @atomic
    def mark_rate_lagging(self, asset, provider_rate):
        """Trusted ProviderBook grace input; never a current price for intake."""
        if not isinstance(provider_rate, Fraction) or provider_rate <= 0:
            raise ValueError("positive provider rational required")
        self.assets[asset].lagging_rate = provider_rate
        self.assets[asset].lagging = True
        self.assets[asset].readable = True

    @atomic
    def propose_caps(self, token, hill, total):
        proposed = tuple(integer(value, 1) for value in (token, hill, total))
        if any(new > old for new, old in zip(proposed, self.caps)):
            self.pending_caps = (self.now + self.config.cap_delay, proposed)
        else:
            self.caps = proposed
            self.pending_caps = None

    @atomic
    def execute_caps(self):
        if self.pending_caps is None or self.now < self.pending_caps[0]:
            raise ValueError("cap increase is timelocked")
        self.caps = self.pending_caps[1]
        self.pending_caps = None

    @atomic
    def pledge(self, owner, hill, asset, units, lock_weeks=0):
        integer(units, 1)
        state = self.hills[hill]
        if not owner or lock_weeks not in self.config.lock_weights:
            raise ValueError("owner or lock unsupported")
        if (not self._fresh(asset) or not self.assets[asset].readable
                or self.assets[asset].lagging):
            raise ValueError("rate stale")
        # Rounding down could classify up to a lamport of deposited tokens as
        # yield immediately at an unchanged rate. Conservatively protect ceil.
        basis = ceil(units * self.assets[asset].rate)
        integer(basis, 1)
        exposures = (self.asset_basis[asset], self.hill_basis[hill], self.held_basis)
        if any(value + basis > cap for value, cap in zip(exposures, self.caps)):
            raise ValueError("pilot cap exceeded")
        lot = Lot(self.uid("lot"), owner, hill, asset, units, basis, lock_weeks)
        self.lots[lot.id] = lot
        self.ledgers[asset].deposited += units
        self._change_basis(asset, hill, basis)
        if state.bonded_at is not None:
            lot.lock_end = self.now + lock_weeks * WEEK
        elif self.backing(hill) >= self.config.line:
            self._bond(hill, owner)
        return lot.id

    def _bond(self, hill, founder):
        state = self.hills[hill]
        state.bonded_at, state.founder = self.now, founder
        for lot in self.lots.values():
            if lot.hill == hill and self.assets[lot.asset].readable and (self._fresh(lot.asset) or self.assets[lot.asset].lagging):
                asset = self.assets[lot.asset]
                quote = asset.lagging_rate if asset.lagging else asset.rate
                lot.owner_units = max(0, lot.units - ceil(Fraction(lot.basis) / quote))
                lot.units -= lot.owner_units
                lot.founding = True
                lot.lock_weeks = self.config.bond_lock_weeks
                lot.lock_end = self.now + lot.lock_weeks * WEEK

    def _owner(self, lot_id, owner):
        lot = self.lots[lot_id]
        if lot.owner != owner:
            raise ValueError("wrong lot owner")
        return lot

    @atomic
    def cancel(self, lot_id, owner):
        lot = self._owner(lot_id, owner)
        if lot.lock_end is not None:
            raise ValueError("bonded pledge cannot be cancelled")
        amount = lot.units
        self.ledgers[lot.asset].returned += amount
        self._change_basis(lot.asset, lot.hill, -lot.basis)
        del self.lots[lot_id]
        return amount

    @atomic
    def convert(self, lot_id, owner, lock_weeks):
        lot = self._owner(lot_id, owner)
        if self.hills[lot.hill].bonded_at is None or lot.lock_end is not None or lot.exiting:
            raise ValueError("conversion requires an excluded pre-bond lot")
        if lock_weeks not in self.config.lock_weights:
            raise ValueError("lock unsupported")
        if not self._fresh(lot.asset):
            raise ValueError("rate stale")
        lot.owner_units = max(0, lot.units - ceil(Fraction(lot.basis) / self.rate(lot)))
        lot.units -= lot.owner_units
        lot.lock_weeks = lock_weeks
        lot.lock_end = self.now + lock_weeks * WEEK

    @atomic
    def withdraw_prebond(self, lot_id, owner):
        lot = self._owner(lot_id, owner)
        if lot.exiting:
            raise ValueError("exit dust returns only when the exit is liquid")
        amount, lot.owner_units = lot.owner_units, 0
        self.ledgers[lot.asset].returned += amount
        return amount

    def _harvest(self, lot, amount=None):
        if lot.lock_end is None:
            raise ValueError("pre-bond yield belongs to owner")
        if not self._fresh(lot.asset):
            raise ValueError("rate stale")
        surplus = max(0, lot.units - ceil(Fraction(lot.basis) / self.rate(lot)))
        amount = surplus if amount is None else integer(amount)
        if amount > surplus:
            raise ValueError("harvest would consume protected basis")
        if not amount:
            return 0
        lot.units -= amount
        ledger = self.ledgers[lot.asset]
        ledger.realized += amount
        fee = int(ledger.realized * self.config.fee) - ledger.fees
        ledger.fees += fee
        ledger.custody += amount
        self.income_weeks.add((lot.hill, self.week))
        if amount > fee:
            self.tranches.append(Tranche(self.uid("harvest"), lot.hill, lot.asset, amount - fee, self.week, self.week, "yield"))
        return amount

    @atomic
    def harvest(self, lot_id, amount=None):
        if amount == 0:
            raise ValueError("zero harvest")
        if not self.assets[self.lots[lot_id].asset].readable:
            raise ValueError("provider accounting unreadable")
        return self._harvest(self.lots[lot_id], amount)

    @atomic
    def notice(self, lot_id, owner, basis):
        lot = self._owner(lot_id, owner)
        integer(basis, 1)
        if lot.exiting or lot.lock_end is None or self.now < lot.lock_end or lot.notice_at is not None or basis > lot.basis:
            raise ValueError("notice requires an unlocked, unreserved basis")
        lot.notice_at, lot.notice_basis = self.now, basis

    @atomic
    def cancel_notice(self, lot_id, owner):
        lot = self._owner(lot_id, owner)
        if lot.exiting or lot.notice_at is None:
            raise ValueError("no cancellable notice")
        lot.notice_at, lot.notice_basis = None, 0

    @atomic
    def begin_exit(self, lot_id, owner):
        lot = self._owner(lot_id, owner)
        if lot.exiting or lot.notice_at is None or self.now < lot.notice_at + self.config.notice_weeks * WEEK:
            raise ValueError("notice not complete")
        rate = self._exit_rate(lot.asset)
        if rate is None and lot.notice_basis != lot.basis:
            raise ValueError("stale escape requires full remaining basis notice")
        if rate is not None:
            self._harvest(lot)
        basis = lot.notice_basis
        units = lot.units * basis // lot.basis
        exit_lot = Lot(self.uid("exit"), lot.owner, lot.hill, lot.asset, units, basis, lot.lock_weeks, lot.lock_end, lot.founding, exiting=True)
        self.lots[exit_lot.id] = exit_lot
        lot.units -= units
        lot.basis -= basis
        # Splitting integer basis can expose at most one residual token unit
        # previously retained by ceil(basis/rate). It belongs to this owner,
        # never to rider income. Return it with this authorized exit.
        for part in (lot, exit_lot):
            dust = 0 if rate is None else max(0, part.units - ceil(Fraction(part.basis) / rate))
            part.units -= dust
            exit_lot.owner_units += dust
        if lot.basis and not exit_lot.units + exit_lot.owner_units:
            raise ValueError("partial exit is smaller than one token base unit")
        lot.notice_at, lot.notice_basis = None, 0
        return exit_lot.id

    @atomic
    def finish_exit(self, lot_id, owner, liquid):
        lot = self._owner(lot_id, owner)
        if not lot.exiting or liquid is not True:
            raise ValueError("redemption is not liquid")
        if self._exit_rate(lot.asset) is not None:
            self._harvest(lot)
        amount = lot.units + lot.owner_units
        self.ledgers[lot.asset].returned += amount
        self._change_basis(lot.asset, lot.hill, -lot.basis)
        del self.lots[lot_id]
        return amount

    @atomic
    def sponsor(self, hill, amount):
        integer(amount, 1)
        if hill not in self.hills:
            raise ValueError("unknown hill")
        self.ledgers[USDC].cash += amount
        self.ledgers[USDC].custody += amount
        self.tranches.append(Tranche(self.uid("sponsor"), hill, USDC, amount, self.week, self.week, "sponsor"))

    @atomic
    def boost(self, funder, hills, amount, start_week, weeks, *, boost_id=None):
        integer(amount, 1)
        integer(start_week)
        integer(weeks, 1)
        if not self.config.boosts_enabled or not funder or not 1 <= len(hills) <= 16 or len(set(hills)) != len(hills) or any(hill not in self.hills for hill in hills):
            raise ValueError("invalid boost")
        if not self.week < start_week <= self.week + BOOST_START_HORIZON:
            raise ValueError("boost must start 1..13 weeks after the current city week")
        if not self.config.boost_min <= weeks <= self.config.boost_max:
            raise ValueError("boost duration must be 1..13 weeks")
        boost_id = self.uid("boost") if boost_id is None else boost_id
        if not isinstance(boost_id, str) or not boost_id:
            raise ValueError("invalid boost ID")
        source = json.dumps([funder, boost_id], separators=(",", ":"))
        if source in self.boosts:
            raise ValueError("boost ID already belongs to this funder")
        last = start_week + weeks - 1
        slots = {f"{hill}\0{week:020d}": (hill, week) for hill in hills for week in range(start_week, last + 1)}
        schedule = []
        for key, share in apportion(amount, dict.fromkeys(slots, 1)).items():
            if share < BOOST_MIN_TRANCHE:
                raise ValueError("every boost hill-week tranche must be at least 1 USDC")
            hill, week = slots[key]
            schedule.append((hill, week, share))
            if share:
                self.tranches.append(Tranche(source, hill, USDC, share, week, week, "boost", ride_start=self.launch + start_week * WEEK, ride_end=self.launch + (start_week + weeks) * WEEK, last_ride_week=last))
        self.ledgers[USDC].cash += amount
        self.ledgers[USDC].custody += amount
        self.boosts[source] = Boost(source, funder, tuple(sorted(hills)), amount, start_week, weeks, last, tuple(sorted(schedule)))
        return source

    @atomic
    def set_board(self, hill, board, legend=None):
        if len(board) > 10 or len(set(board)) != len(board) or any(not person for person in board) or legend == "":
            raise ValueError("one top-ten seat per known person; earned legend required")
        self.hills[hill].board, self.hills[hill].legend = tuple(board), legend

    @atomic
    def upload(self, receipt, hill, person, ridden_at, tss):
        integer(ridden_at)
        integer(tss)
        if hill not in self.hills or not person or not receipt or receipt in self.receipts:
            raise ValueError("unknown identity/hill or duplicate receipt")
        if ridden_at < self.launch or not 0 <= self.now - ridden_at <= self.config.upload_days * DAY:
            raise ValueError("ride outside upload window")
        ride = Ride(receipt, hill, person, ridden_at, self.now, tss)
        self.receipts.add(receipt)
        self.rides.append(ride)
        self.fields[hill, self.week // self.config.season_weeks].add(person)

    def _ascents(self, snapshot, tranche=None):
        result = defaultdict(int)
        # Dedup globally across upload weeks by original ride UTC day; the earliest
        # trusted upload owns that day's paid ascent, even across boost windows.
        first = {}
        for ride in self.rides:
            key = (ride.hill, ride.person, ride.ridden_at // DAY)
            first.setdefault(key, [])
            if len(first[key]) < self.config.daily_ascents:
                first[key].append(ride.receipt)
        rides = snapshot.rides
        if tranche and tranche.kind == "boost":
            start = self.launch + snapshot.week * WEEK
            end = start + WEEK
            # Boost money belongs to the riding week. Its late uploads share
            # that week's escrow until the fixed finalization cutoff, without
            # changing ordinary upload-week records, field, board or DUNG.
            rides = (ride for ride in self.rides if ride.hill == tranche.hill
                     and start <= ride.ridden_at < end
                     and ride.uploaded_at < end + self.config.grace)
        for ride in rides:
            if ride.receipt not in first[ride.hill, ride.person, ride.ridden_at // DAY]:
                continue
            if tranche and tranche.kind == "boost" and not tranche.ride_start <= ride.ridden_at < tranche.ride_end:
                continue
            result[ride.person] += 1
        return dict(result)

    def _backers(self, hill, week):
        result = defaultdict(Fraction)
        bond = self.hills[hill].bonded_at
        for lot in self.lots.values():
            if lot.hill != hill or lot.exiting or lot.lock_end is None:
                continue
            boundary = self.launch + week * WEEK
            weight = self.config.lock_weights[lot.lock_weeks if boundary < lot.lock_end else 0]
            first_bonded_week = (bond - self.launch) // WEEK + 1
            if lot.founding and first_bonded_week <= week < first_bonded_week + self.config.season_weeks:
                weight *= self.config.founder_multiplier
            result[lot.owner] += min(lot.basis, int(lot.units * self.rate(lot))) * weight
        return tuple(sorted(result.items()))

    @atomic
    def advance(self, timestamp):
        integer(timestamp)
        if timestamp < self.now:
            raise ValueError("clock cannot go backwards")
        while self.launch + (self.week + 1) * WEEK <= timestamp:
            week = self.week
            for hill, state in self.hills.items():
                live, bonded, backers = self.openings[hill, week]
                rides = tuple(ride for ride in self.rides if ride.hill == hill and (ride.uploaded_at - self.launch) // WEEK == week)
                self.snapshots[hill, week] = Snapshot(week, live, bonded, len(self.fields[hill, week // self.config.season_weeks]) >= self.config.field, state.board, state.legend, rides, backers, tuple(sorted(self.ledgers)))
            self.now = self.launch + (week + 1) * WEEK
            for hill, state in self.hills.items():
                bonded = state.bonded_at is not None
                live = bonded and self.backing(hill) >= self.config.line * self.config.live_fraction
                self.openings[hill, self.week] = (live, bonded, self._backers(hill, self.week))
        self.now = timestamp

    def _dung(self, hill, snapshot):
        if not snapshot.field or not snapshot.bonded:
            return DungMint(0, {}, {}, 0)
        bond = self.hills[hill].bonded_at
        eligible = replace(snapshot, rides=tuple(ride for ride in snapshot.rides if bond is not None and ride.ridden_at >= bond))
        tss = sum(ride.tss for ride in eligible.rides)
        potential = int(Fraction(tss * self.config.dung_scale, self.config.tss_scale) * self.config.dung_per_tss)
        halves = apportion(potential, self.config.dung_split)
        pieces = apportion(halves.get("riders", 0), self.config.rider_dung_split)
        riders = defaultdict(int)
        weights = {"every_rider_by_ascents": self._ascents(eligible), "top_ten": dict.fromkeys(snapshot.board, 1), "local_legend": {snapshot.legend: 1} if snapshot.legend else {}}
        for bucket, amount in pieces.items():
            for person, paid in apportion(amount, weights[bucket]).items():
                if person in self.recipients:
                    riders[person] += paid
        backers = {p:n for p,n in apportion(halves.get("backers", 0), dict(snapshot.backers)).items() if p in self.recipients}
        return DungMint(potential, dict(riders), backers, potential - sum(riders.values()) - sum(backers.values()))

    def _pieces(self, tranche):
        if tranche.bucket != "full":
            return [tranche]
        mapping = {"every_rider_by_ascents": "ascents", "top_ten": "top", "local_legend": "legend"}
        return [replace(tranche, amount=amount, bucket=mapping[name]) for name, amount in apportion(tranche.amount, self.config.split).items() if amount]

    def _coalesced(self):
        # No per-transfer rounding. Coalesce only equal ages and eligibility;
        # retained source lineage remains bound to its original hill and window.
        grouped = {}
        for tranche in self.tranches:
            key = (tranche.hill, tranche.asset, tranche.born, tranche.due, tranche.kind, tranche.bucket, tranche.ride_start, tranche.ride_end, tranche.last_ride_week, tranche.person)
            sources = tranche.sources or (tranche.source,)
            if key in grouped:
                prior = grouped[key]
                grouped[key] = replace(prior, amount=prior.amount + tranche.amount, sources=tuple(sorted(set(prior.sources + sources))))
            else:
                grouped[key] = replace(tranche, sources=sources)
        return grouped.values()

    @atomic
    def skip_empty(self, hill, through):
        """Whole-hill counterpart of the per-asset chain cursor.

        Quiet holds may cross skipped weeks, never their original maturity or
        a future boost due week. No ledger or tranche changes on a skip. The
        oracle additionally refuses fresh income or DUNG across ALL assets.
        """
        integer(through)
        start = self.hills[hill].next_settle
        if through < start or through - start >= 16 or self.now < self.launch + (through + 1) * WEEK + self.config.grace:
            raise ValueError("empty skip must be bounded, in order and finalizable")
        for t in self.tranches:
            if t.hill != hill or not t.amount or t.bucket == "pool":
                continue
            if t.born < start:
                if through >= t.born + self.config.held_weeks:
                    raise ValueError("skip reaches an original hold maturity")
            elif t.due <= through:
                raise ValueError("skip reaches new income or a boost tranche due week")
        for week in range(start, through + 1):
            if (hill, week) in self.income_weeks or self._dung(hill, self.snapshots[hill, week]).potential:
                raise ValueError("income or DUNG requires settlement")
        self.hills[hill].next_settle = through + 1

    @atomic
    def open_funding(self, hill, week, asset, *, payer='publisher'):
        integer(week)
        if not self.hills[hill].next_settle <= week <= self.week or asset not in self.ledgers:
            raise ValueError('funding week closed, skipped, future or invalid asset')
        self.funding_records.setdefault((hill, week, asset), payer)

    @atomic
    def settle(self, hill, week):
        integer(week)
        if week != self.hills[hill].next_settle or self.now < self.launch + (week + 1) * WEEK + self.config.grace:
            raise ValueError("week not finalizable, already settled, or out of sequence")
        snapshot = self.snapshots[hill, week]
        keep, candidates = [], defaultdict(list)
        for tranche in self._coalesced():
            if tranche.hill != hill or tranche.due > week or tranche.bucket == "pool":
                keep.append(tranche)
                continue
            if week - tranche.born >= self.config.held_weeks:
                keep.append(replace(tranche, bucket="pool", person=None))
                continue
            if tranche.person:
                if tranche.person in self.recipients:
                    candidates[tranche.asset].append((tranche, {tranche.person: tranche.amount}, {}))
                else:
                    keep.append(tranche)
                continue
            if ((tranche.kind == "yield" or self.config.cash_requires_live) and not snapshot.live) or (tranche.last_ride_week is not None and week > tranche.last_ride_week):
                keep.append(tranche)
                continue
            ascents = self._ascents(snapshot, tranche)
            for piece in self._pieces(tranche):
                weights = ascents if piece.bucket in ("ascents", "cap") else dict.fromkeys(snapshot.board, 1) if piece.bucket == "top" and snapshot.field else {snapshot.legend: 1} if piece.bucket == "legend" and snapshot.field and snapshot.legend else {}
                entitlements = apportion(piece.amount, weights)
                if entitlements:
                    candidates[piece.asset].append((piece, entitlements, ascents))
                else:
                    keep.append(piece)
        caps, claims = {}, {}
        for asset, entries in candidates.items():
            entries.sort(key=lambda entry: (entry[0].born, entry[0].source,
                'reserved:'+entry[0].person if entry[0].person else entry[0].bucket))
            combined = defaultdict(int)
            for _, entitlements, _ in entries:
                for person, amount in entitlements.items():
                    combined[person] += amount
            cap = caps[asset] = median_cap(combined, self.config.cap_multiplier)
            paid, assigned, excesses = defaultdict(int), defaultdict(lambda: defaultdict(int)), []
            for piece, entitlements, ascents in entries:
                excess = 0
                for person, amount in entitlements.items():
                    take = min(amount, cap - paid[person])
                    paid[person] += take
                    assigned[piece][person] += take
                    excess += amount - take
                if piece.person and excess:
                    keep.append(replace(piece, amount=excess))
                else:
                    excesses.append((piece, ascents, excess))
            for piece, ascents, excess in excesses:
                added, held = redistribute(excess, ascents, paid, cap)
                for person, amount in added.items():
                    paid[person] += amount
                    assigned[piece][person] += amount
                if held:
                    keep.append(replace(piece, amount=held, bucket="cap"))
            for piece, shares in assigned.items():
                for person, amount in shares.items():
                    if person not in self.recipients and amount:
                        paid[person] -= amount
                        keep.append(replace(piece, amount=amount, bucket="cap", person=person))
            claims[asset] = ClaimSet.build(Context(self.deployment, self.city, hill, week, asset), {p:a for p,a in paid.items() if a}, self.recipients)
        for asset in snapshot.assets:
            claims.setdefault(asset, ClaimSet.build(Context(self.deployment, self.city, hill, week, asset), {}, self.recipients))
        self.tranches = keep
        settlement = Settlement(hill, week, claims, caps, self._dung(hill, snapshot))
        self.settlements[hill, week] = settlement
        for asset, claim_set in claims.items():
            self.claim_bits[hill, week, asset] = bytearray((len(claim_set.leaves) + 7) // 8)
            self.funding_records.setdefault((hill, week, asset), 'publisher')
        self.hills[hill].next_settle += 1
        return settlement

    @atomic
    def claim(self, hill, week, asset, leaf, proof, person, recipient):
        settlement = self.settlements.get((hill, week))
        if settlement is None or asset not in settlement.claims:
            raise ValueError('closed or unpublished claim set')
        claims = settlement.claims[asset]
        if person != leaf.person or recipient != leaf.recipient or not claims.verify(leaf, proof):
            raise ValueError("invalid or replayed claim")
        bits = self.claim_bits[hill, week, asset]
        owner = (hill, week, asset, person)
        if bits[leaf.index // 8] & (1 << (leaf.index % 8)):
            raise ValueError("invalid or replayed claim")
        bits[leaf.index // 8] |= 1 << (leaf.index % 8)
        self.ledgers[asset].paid += leaf.amount
        self.ledgers[asset].custody -= leaf.amount
        return leaf.amount

    @atomic
    def claim_batch(self, asset, entries, person, recipient):
        if not 1 <= len(entries) <= 4 or len({(e[0], e[1]) for e in entries}) != len(entries):
            raise ValueError('invalid claim batch')
        return sum(self.claim(hill, week, asset, leaf, proof, person, recipient)
                   for hill, week, leaf, proof in entries)

    @atomic
    def close_cash_claim_set(self, hill, week, asset):
        claims = self.settlements[hill, week].claims[asset]
        bits = self.claim_bits[hill, week, asset]
        if any(not bits[leaf.index // 8] & (1 << (leaf.index % 8)) for leaf in claims.leaves):
            raise ValueError('unpaid cash claim set')
        del self.settlements[hill, week].claims[asset]
        del self.claim_bits[hill, week, asset]

    @atomic
    def close_funding(self, hill, week, asset):
        key = (hill, week, asset)
        settlement = self.settlements.get((hill, week))
        if key not in self.funding_records or self.hills[hill].next_settle <= week or (settlement and asset in settlement.claims):
            raise ValueError('funding still needed or absent')
        # Tranches already live outside weekly records, retaining born/due,
        # bucket, source lineage and boost restrictions. Pool remains held.
        payer = self.funding_records.pop(key)
        if settlement and not settlement.claims and not any(k[:2] == (hill, week) for k in self.funding_records):
            del self.settlements[hill, week]
        return payer

    @atomic
    def pay_fees(self, asset):
        ledger = self.ledgers[asset]
        amount = ledger.fees - ledger.fees_paid
        ledger.fees_paid += amount
        ledger.custody -= amount
        return amount

    def dung_claim_sets(self, hill, week, mint):
        """Pure allocation preview, not publication or permission to mint."""
        dung = self.dung_records.get((hill, week)) or self._dung(hill, self.snapshots[hill, week])
        return {role: ClaimSet.build(Context(self.deployment, self.city, hill, week, f'{mint}:{role}'),
                                    getattr(dung, role), self.recipients)
                for role in ('riders', 'backers')}

    @atomic
    def configure_dung(self, ceiling, start_week, *, authority='admin'):
        """Trusted admin identity; external multisig delay is not simulated here."""
        integer(ceiling)
        if authority != 'admin' or not 0 <= ceiling < 2**64 or (ceiling == 0 and start_week is not None):
            raise ValueError('invalid DUNG admin or ceiling')
        if start_week is not None:
            integer(start_week)
            opening = self.launch + start_week * WEEK
            if start_week >= 2**64 or opening >= 2**63 or (start_week != self.dung_start_week and opening < self.now):
                raise ValueError('DUNG start must be prospective')
        self.dung_tss_ceiling, self.dung_start_week = ceiling, start_week

    def _dung_cursor(self, hill):
        if self.dung_start_week is None or self.dung_tss_ceiling == 0:
            raise ValueError('DUNG start unset')
        bond = self.hills[hill].bonded_at
        if bond is None:
            raise ValueError('DUNG hill not bonded')
        return max(self.dung_start_week, self.dung_next_week.get(hill, (bond - self.launch) // WEEK + 1))

    @atomic
    def publish_dung(self, hill, week):
        integer(week)
        if week != self._dung_cursor(hill) or self.now < self.launch + (week + 1) * WEEK + self.config.grace:
            raise ValueError('DUNG week not finalizable or before start')
        snapshot = self.snapshots[hill, week]
        if not snapshot.bonded or not snapshot.field:
            raise ValueError('DUNG opening or field not eligible')
        tss = sum(r.tss for r in snapshot.rides if r.ridden_at >= self.hills[hill].bonded_at)
        if tss > self.dung_tss_ceiling:
            raise ValueError('DUNG TSS ceiling')
        self.dung_records[hill, week] = self._dung(hill, snapshot)
        record = self.dung_records[hill, week]
        self.dung_allocated += sum(record.riders.values()) + sum(record.backers.values())
        self.dung_roles[hill, week] = set()
        self.dung_rent_payers[hill, week] = 'publisher'
        self.dung_next_week[hill] = week + 1
        return self.dung_records[hill, week]

    @atomic
    def skip_dung_empty(self, hill, through):
        integer(through)
        start = self._dung_cursor(hill)
        if through < start or through - start >= 16 or self.now < self.launch + (through + 1) * WEEK + self.config.grace:
            raise ValueError('DUNG skip not finalizable or out of sequence')
        if any(self._dung(hill, self.snapshots[hill, w]).potential for w in range(start, through + 1)):
            raise ValueError('DUNG nonempty week')
        self.dung_next_week[hill] = through + 1

    @atomic
    def publish_dung_claim_set(self, hill, week, mint, role):
        key = (hill, week, role)
        if (hill, week) not in self.dung_records or role not in ('riders', 'backers') or role in self.dung_roles[hill, week]:
            raise ValueError('invalid or already published DUNG claim set')
        if self.dung_mint is not None and self.dung_mint != mint:
            raise ValueError('invalid DUNG namespace')
        claims = self.dung_claim_sets(hill, week, mint)[role]
        self.dung_published_sets[key] = (claims, self.now)
        self.dung_roles[hill, week].add(role)
        self.dung_claim_bits[key] = bytearray((len(claims.leaves) + 7) // 8)
        self.dung_mint = mint
        return claims

    @atomic
    def claim_dung(self, hill, week, mint, role, leaf, proof, person, recipient):
        if role not in ('riders', 'backers') or (self.dung_mint is not None and self.dung_mint != mint):
            raise ValueError('invalid DUNG namespace')
        if (hill, week, role) not in self.dung_published_sets:
            raise ValueError('closed or unpublished DUNG claim set')
        claims, published_at = self.dung_published_sets[hill, week, role]
        if self.now < published_at + DUNG_CLAIM_WAIT:
            raise ValueError('DUNG claim wait')
        if person != leaf.person or recipient != leaf.recipient or not claims.verify(leaf, proof):
            raise ValueError('invalid or replayed DUNG claim')
        bits = self.dung_claim_bits[hill, week, role]
        owner = (hill, week, role, person)
        if bits[leaf.index // 8] & (1 << (leaf.index % 8)):
            raise ValueError('invalid or replayed DUNG claim')
        bits[leaf.index // 8] |= 1 << (leaf.index % 8)
        self.dung_mint = mint
        self.dung_minted += leaf.amount
        self.dung_week_minted[hill, week] += leaf.amount
        return leaf.amount

    @atomic
    def claim_dung_batch(self, mint, entries, person, recipient):
        if not 1 <= len(entries) <= 4 or len({tuple(e[:3]) for e in entries}) != len(entries):
            raise ValueError('invalid DUNG claim batch')
        return sum(self.claim_dung(hill, week, mint, role, leaf, proof, person, recipient)
                   for hill, week, role, leaf, proof in entries)

    @atomic
    def close_dung_claim_set(self, hill, week, role):
        key = (hill, week, role)
        claims, _ = self.dung_published_sets[key]
        bits = self.dung_claim_bits[key]
        if any(not bits[leaf.index // 8] & (1 << (leaf.index % 8)) for leaf in claims.leaves):
            raise ValueError('unpaid DUNG claim set')
        del self.dung_published_sets[key]
        del self.dung_claim_bits[key]

    @atomic
    def close_dung_mint(self, hill, week):
        key = (hill, week)
        record = self.dung_records.get(key)
        if record is None or self.dung_next_week[hill] <= week or self.dung_roles[key] != {'riders', 'backers'} or any(k[:2] == key for k in self.dung_published_sets):
            raise ValueError('DUNG record still needed or absent')
        if self.dung_week_minted[key] != sum(record.riders.values()) + sum(record.backers.values()):
            raise ValueError('unpaid DUNG allocation')
        del self.dung_records[key], self.dung_roles[key], self.dung_week_minted[key]
        return self.dung_rent_payers.pop(key)

    def balances(self, asset):
        ledger = self.ledgers[asset]
        claimable = sum(leaf.amount for (hill, week), settlement in self.settlements.items() for mint, claims in settlement.claims.items() if mint == asset for leaf in claims.leaves if not self.claim_bits[hill, week, asset][leaf.index // 8] & (1 << (leaf.index % 8)))
        held = sum(tranche.amount for tranche in self.tranches if tranche.asset == asset)
        return {"paid": ledger.paid, "fees": ledger.fees, "claimable": claimable, "held": held, "realized": ledger.realized, "cash": ledger.cash, "custody": ledger.custody, "fees_due": ledger.fees - ledger.fees_paid}

    def check(self):
        for settlement in self.settlements.values():
            dung = settlement.dung
            total = sum(dung.riders.values()) + sum(dung.backers.values())
            assert total + dung.unminted == dung.potential
        assert self.dung_minted <= self.dung_allocated
        assert self.held_basis == sum(lot.basis for lot in self.lots.values())
        for asset in self.assets:
            assert self.asset_basis[asset] == sum(lot.basis for lot in self.lots.values() if lot.asset == asset)
        for hill in self.hills:
            assert self.hill_basis[hill] == sum(lot.basis for lot in self.lots.values() if lot.hill == hill)
        for lot in self.lots.values():
            assert all(type(value) is int and value >= 0 for value in (lot.units, lot.basis, lot.owner_units))
        for tranche in self.tranches:
            assert type(tranche.amount) is int and tranche.amount > 0
        for asset, ledger in self.ledgers.items():
            balance = self.balances(asset)
            assert all(type(value) is int and value >= 0 for value in balance.values())
            assert balance["paid"] + balance["fees"] + balance["claimable"] + balance["held"] == balance["realized"] + balance["cash"], (asset, balance)
            assert balance["custody"] == balance["claimable"] + balance["held"] + balance["fees_due"]
            lot_units = sum(lot.units + lot.owner_units for lot in self.lots.values() if lot.asset == asset)
            assert ledger.deposited + ledger.cash == lot_units + ledger.returned + ledger.custody + ledger.paid + ledger.fees_paid
        return True
