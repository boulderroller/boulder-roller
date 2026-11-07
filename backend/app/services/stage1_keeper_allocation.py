"""Integer cash allocation for frozen Stage 1 inputs; no floating point money."""
from collections import defaultdict

from .stage1_keeper_merkle import uint

BUCKETS = ("full", "ascents", "top", "legend", "cap")
SPLIT = {"every_rider_by_ascents": 65, "top_ten": 25, "local_legend": 10}
SPLIT_BUCKET = {"every_rider_by_ascents": 1, "top_ten": 2, "local_legend": 3}


def hamilton(amount, weights, tie_ranks=None):
    uint(amount)
    for weight in weights.values():
        uint(weight,128)
    weights = {k: w for k, w in weights.items() if w}
    denominator = sum(weights.values())
    if not denominator:
        return {}
    parts = {p: divmod(amount * w, denominator) for p, w in weights.items()}
    result = {p: q for p, (q, _) in parts.items()}
    if tie_ranks is not None and (not set(parts)<=set(tie_ranks) or any(type(v) is not int or v<0 for v in tie_ranks.values()) or len(set(tie_ranks.values()))!=len(tie_ranks)):
        raise ValueError('missing or duplicate frozen allocation order')
    order = sorted(parts, key=lambda p: (-parts[p][1], tie_ranks[p] if tie_ranks is not None else p.encode("utf-8")))
    for person in order[:amount - sum(result.values())]:
        result[person] += 1
    return result


def allocate(snapshot, sources):
    week = uint(snapshot["context"][3])
    if type(snapshot["live"]) is not bool or type(snapshot["field"]) is not bool:
        raise ValueError("missing frozen live/field truth")
    board = snapshot["board"]
    if len(board) > 10 or len(set(board)) != len(board):
        raise ValueError("duplicate or excessive board seats")
    people = set(board) | set(snapshot["ascents"]) | ({snapshot["legend"]} if snapshot["legend"] else set())
    holds, pool, reserved, entries = {}, {}, {}, []
    if len({s["id"] for s in sources}) != len(sources):
        raise ValueError("duplicate source")
    for source in sources:
        ident, born, due = source["id"], uint(source["born"]), uint(source["due"])
        buckets = source["buckets"]
        if len(buckets) != 5 or due < born or source["kind"] not in ("yield", "sponsor", "boost"):
            raise ValueError("invalid source")
        for amount in buckets:
            uint(amount)
        holds[ident], pool[ident], reserved[ident] = [0] * 5, 0, {}
        attributed = source.get("reserved", {})
        if sum(uint(n) for n in attributed.values()) > buckets[4]:
            raise ValueError("person holds exceed aggregate cap hold")
        if due > week:
            holds[ident] = list(buckets)
            reserved[ident] = dict(attributed)
            continue
        if week - born >= 26:
            pool[ident] = sum(buckets)
            continue
        buckets = list(buckets)
        buckets[4] -= sum(attributed.values())
        for person, amount in attributed.items():
            if person in snapshot["recipients"]:
                entries.append((born, ident, "reserved:" + person, {person: amount}, {}))
            else:
                reserved[ident][person] = amount
                holds[ident][4] += amount
        if (source["kind"] == "yield" and not snapshot["live"]) or (source.get("last_ride_week") is not None and week > source["last_ride_week"]):
            holds[ident] = [a+b for a,b in zip(holds[ident], buckets)]
            continue
        # A future sponsor adapter supplies its own frozen, window-qualified
        # ascents. It cannot reuse the ordinary population by omission.
        ascents = source["ascents"] if source["kind"] == "boost" else snapshot["ascents"]
        pieces = [(i, amount) for i, amount in enumerate(buckets) if i and amount]
        pieces += [(SPLIT_BUCKET[name], amount) for name, amount in hamilton(buckets[0], SPLIT).items() if amount]
        for bucket, amount in pieces:
            weights = (ascents if bucket in (1, 4) else dict.fromkeys(board, 1) if bucket == 2 and snapshot["field"]
                       else {snapshot["legend"]: 1} if bucket == 3 and snapshot["field"] and snapshot["legend"] else {})
            proposed = hamilton(amount, weights)
            if proposed:
                entries.append((born, ident, BUCKETS[bucket], proposed, ascents))
            else:
                holds[ident][bucket] += amount
    entries.sort(key=lambda e: (e[0], e[1].encode("utf-8"), e[2].encode("utf-8")))
    combined = defaultdict(int)
    for _, _, _, proposed, _ in entries:
        for p, amount in proposed.items():
            combined[p] += amount
    values = sorted(n for n in combined.values() if n > 0)
    n = len(values)
    cap = uint((3 * values[n // 2] if n % 2 else 3 * (values[n // 2 - 1] + values[n // 2]) // 2) if n else 0)
    paid, assigned, excesses = defaultdict(int), defaultdict(lambda: defaultdict(int)), []
    for _, ident, bucket, proposed, ascents in entries:
        excess = 0
        for p, amount in proposed.items():
            take = min(amount, cap - paid[p])
            paid[p] += take
            assigned[ident][p] += take
            excess += amount - take
        if bucket.startswith("reserved:") and excess:
            person = bucket[len("reserved:"):]
            reserved[ident][person] = reserved[ident].get(person, 0) + excess
            holds[ident][4] += excess
        else:
            excesses.append((ident, ascents, excess))
    for ident, ascents, excess in excesses:
        while excess:
            eligible = {p: weight for p, weight in ascents.items() if weight and paid[p] < cap}
            if not eligible:
                break
            moved = 0
            for p, amount in hamilton(excess, eligible).items():
                take = min(amount, cap - paid[p])
                paid[p] += take
                assigned[ident][p] += take
                moved += take
            if not moved:
                break
            excess -= moved
        holds[ident][4] += excess
    for ident, shares in assigned.items():
        for person, amount in shares.items():
            if person not in snapshot["recipients"] and amount:
                paid[person] -= amount
                reserved[ident][person] = reserved[ident].get(person, 0) + amount
                holds[ident][4] += amount
    payments = {p: uint(n) for p, n in paid.items() if n}
    if sum(payments.values()) + sum(map(sum, holds.values())) + sum(pool.values()) != sum(sum(s["buckets"]) for s in sources):
        raise ValueError("allocation does not conserve funding")
    return {"payments": payments, "cap": cap, "holds": holds, "pool": pool, "reserved": reserved}
