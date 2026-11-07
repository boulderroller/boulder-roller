"""Stage 1 wire commitments. Deliberately independent of the offline oracle."""
import hashlib
import json


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def uint(value, bits=64):
    if type(value) is not int or not 0 <= value < 1 << bits:
        raise ValueError(f"expected unsigned {bits}-bit integer")
    return value


def _hash(domain, data):
    return hashlib.sha256(b"BR-stage1-v1:" + domain + b"\0" + data).digest()


def leaf_hash(context, index, person, recipient, amount):
    return _hash(b"leaf", canonical([context, index, person, recipient, amount])).hex()


def root_from_hashes(context, leaves):
    empty = (_hash(b"empty", canonical(context)), 0)
    level = [(bytes.fromhex(l["leaf_hash"]), uint(l["amount"])) for l in sorted(leaves, key=lambda l:l["index"])] or [empty]
    while len(level) > 1:
        pairs = [(level[i], level[i+1] if i+1<len(level) else empty) for i in range(0,len(level),2)]
        level = [(_hash(b"parent", a[0]+a[1].to_bytes(16,"big")+b[0]+b[1].to_bytes(16,"big")), uint(a[1]+b[1],128)) for a,b in pairs]
    return level[0][0].hex(), level[0][1]


def claim_set(context, payments, recipients):
    if len(context) != 5 or any(not isinstance(context[i], str) or not context[i] for i in [0, 1, 2, 4]):
        raise ValueError("invalid claim namespace")
    uint(context[3])
    for person, amount in payments.items():
        uint(amount)
        if not person or not recipients.get(person):
            raise ValueError("missing fixed recipient")
    people = sorted((p for p, n in payments.items() if n), key=lambda p: p.encode("utf-8"))
    if len(people) > 65536:
        raise ValueError("claim set exceeds depth 16")
    empty = (_hash(b"empty", canonical(context)), 0)
    leaves = [{"index": i, "person": p, "recipient": recipients[p], "amount": payments[p]}
              for i, p in enumerate(people)]
    level = [(_hash(b"leaf", canonical([context, l["index"], l["person"], l["recipient"], l["amount"]])), l["amount"])
             for l in leaves] or [empty]
    levels = [level]
    while len(level) > 1:
        following = []
        for i in range(0, len(level), 2):
            left, right = level[i], level[i + 1] if i + 1 < len(level) else empty
            total = uint(left[1] + right[1], 128)
            following.append((_hash(b"parent", left[0] + left[1].to_bytes(16, "big") + right[0] + right[1].to_bytes(16, "big")), total))
        level = following
        levels.append(level)
    for leaf in leaves:
        leaf["leaf_hash"] = leaf_hash(context, leaf["index"], leaf["person"], leaf["recipient"], leaf["amount"])
        index, proof = leaf["index"], []
        for level in levels[:-1]:
            sibling = level[index ^ 1] if index ^ 1 < len(level) else empty
            proof.append({"hash": sibling[0].hex(), "sum": sibling[1]})
            index //= 2
        leaf["proof"] = proof
    return {"context": context, "root": levels[-1][0][0].hex(), "total": uint(levels[-1][0][1]),
            "count": len(leaves), "leaves": leaves}
