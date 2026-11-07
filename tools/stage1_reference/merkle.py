"""Versioned SHA-256 Merkle-sum commitments, including namespace and recipient."""

from dataclasses import dataclass
import hashlib
import json

from .arithmetic import integer

MAX_SUM = 2**128 - 1


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def digest(domain, data):
    return hashlib.sha256(b"BR-stage1-v1:" + domain + b"\0" + data).digest()


def sum_bytes(value):
    integer(value)
    if value > MAX_SUM:
        raise ValueError("sum overflows u128")
    return value.to_bytes(16, "big")


@dataclass(frozen=True)
class Context:
    deployment: str
    city: str
    hill: str
    week: int
    asset: str

    def data(self):
        return [self.deployment, self.city, self.hill, self.week, self.asset]


@dataclass(frozen=True)
class Node:
    hash: bytes
    total: int


@dataclass(frozen=True)
class Leaf:
    index: int
    person: str
    recipient: str
    amount: int

    def node(self, context):
        integer(self.index)
        integer(self.amount, 1)
        sum_bytes(self.amount)
        return Node(digest(b"leaf", encode([context.data(), self.index, self.person, self.recipient, self.amount])), self.amount)


def empty(context):
    return Node(digest(b"empty", encode(context.data())), 0)


def parent(left, right):
    total = left.total + right.total
    sum_bytes(total)
    return Node(digest(b"parent", left.hash + sum_bytes(left.total) + right.hash + sum_bytes(right.total)), total)


@dataclass(frozen=True)
class ClaimSet:
    context: Context
    leaves: tuple[Leaf, ...]
    levels: tuple[tuple[Node, ...], ...]

    @classmethod
    def build(cls, context, payments, recipients):
        integer(context.week)
        if any(not isinstance(part, str) or not part for part in (context.deployment, context.city, context.hill, context.asset)):
            raise ValueError("empty claim namespace")
        for person, amount in payments.items():
            integer(amount)
            if not person or person not in recipients or not recipients[person]:
                raise ValueError("missing identity or recipient")
        people = sorted((person for person, amount in payments.items() if amount), key=lambda p: p.encode("utf-8"))
        leaves = tuple(Leaf(i, person, recipients[person], payments[person]) for i, person in enumerate(people))
        nodes = tuple(leaf.node(context) for leaf in leaves) or (empty(context),)
        levels = [nodes]
        while len(nodes) > 1:
            nodes = tuple(parent(nodes[i], nodes[i + 1] if i + 1 < len(nodes) else empty(context)) for i in range(0, len(nodes), 2))
            levels.append(nodes)
        return cls(context, leaves, tuple(levels))

    @property
    def root(self):
        return self.levels[-1][0]

    def proof(self, index):
        integer(index)
        if index >= len(self.leaves):
            raise ValueError("leaf index out of range")
        proof = []
        for level in self.levels[:-1]:
            sibling = index ^ 1
            proof.append(level[sibling] if sibling < len(level) else empty(self.context))
            index //= 2
        return tuple(proof)

    def verify(self, leaf, proof):
        try:
            if not 0 <= leaf.index < len(self.leaves) or len(proof) != len(self.levels) - 1:
                return False
            node, index = leaf.node(self.context), leaf.index
            for sibling in proof:
                if len(sibling.hash) != 32:
                    return False
                node = parent(sibling, node) if index % 2 else parent(node, sibling)
                index //= 2
            return node == self.root
        except (ValueError, TypeError, OverflowError, AttributeError):
            return False
