"""An in-memory PostgREST behind the real, pinned postgrest-py client.

The client builds every request, so a test sees its exact wire format. In
postgrest-py 0.13, ``range(a, b)`` sends ``Range: a-(b - 1)`` and every
``order()`` call is its own ``order`` parameter. The server follows PostgREST:
an inclusive Range header (a malformed one is ignored, an empty one is a 416),
``limit``/``offset`` parameters, a max-rows cap, and only the first ``order``
parameter. Rows that tie on the sort come back in an order that changes from
request to request, as an unstable top-N sort's can.
"""

from __future__ import annotations

import json
import random
import re
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Tuple

import httpx
from postgrest import SyncPostgrestClient
from postgrest.utils import SyncClient

BASE_URL = "http://postgrest.test"
_RESERVED = {"select", "order", "limit", "offset", "on_conflict", "columns"}
_RANGE = re.compile(r"^(\d+)-(\d*)$")


class PinnedPostgrest:
    def __init__(self, tables: Mapping[str, Iterable[Mapping[str, Any]]], *,
                 max_rows: int = 1000, seed: int = 0):
        self.tables: Dict[str, List[Dict[str, Any]]] = {
            name: [dict(row) for row in rows] for name, rows in tables.items()
        }
        self.max_rows = max_rows
        self.seed = seed
        self.requests: List[httpx.Request] = []
        self.client = SyncPostgrestClient(BASE_URL)
        self.client.session = SyncClient(
            base_url=BASE_URL,
            headers=dict(self.client.session.headers),
            transport=httpx.MockTransport(self._handle),
        )

    def table(self, name: str):
        return self.client.from_(name)

    from_ = table

    def reads(self, table: str) -> List[httpx.Request]:
        return [request for request in self.requests if request.url.path == f"/{table}"]

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.method != "GET":
            raise AssertionError(f"read-only fake received {request.method}")
        rows = list(self.tables.get(request.url.path.lstrip("/"), []))
        params = request.url.params
        for column, expression in params.multi_items():
            if column not in _RESERVED:
                keep = _predicate(expression)
                rows = [row for row in rows if keep(_value(row, column))]
        total = len(rows)
        orders = params.get_list("order")
        if orders:  # PostgREST keeps the first order parameter only.
            random.Random(self.seed * 1_000_003 + len(self.requests)).shuffle(rows)
            for column, descending in reversed(_order_terms(orders[0])):
                rows.sort(key=lambda row: _sort_key(_value(row, column)), reverse=descending)
        start, stop = 0, None
        header = request.headers.get("range")
        if header is not None:
            if "offset" in params or "limit" in params:
                raise AssertionError("fake does not combine Range with limit/offset")
            match = _RANGE.match(header)
            if match:
                start = int(match.group(1))
                if match.group(2):
                    stop = int(match.group(2)) + 1
                    if stop <= start:
                        return httpx.Response(416, json={
                            "code": "PGRST103", "details": None, "hint": None,
                            "message": "Requested range not satisfiable",
                        })
        if "offset" in params:
            start = int(params["offset"])
        if "limit" in params:
            stop = start + int(params["limit"])
        stop = start + self.max_rows if stop is None else min(stop, start + self.max_rows)
        page = [_project(row, params.get("select", "*")) for row in rows[start:stop]]
        end = start + len(page) - 1
        return httpx.Response(
            206 if header is not None else 200,
            headers={"Content-Range": f"{start}-{end}/{total}" if page else f"*/{total}"},
            content=json.dumps(page, default=str).encode(),
        )


def _value(row: Mapping[str, Any], column: str) -> Any:
    if "->>" in column:
        head, key = column.split("->>", 1)
        nested = row.get(head)
        value = nested.get(key) if isinstance(nested, Mapping) else None
        return None if value is None else str(value)
    return row.get(column)


def _text(value: Any) -> str:
    return str(value)


def _sort_key(value: Any) -> Tuple[int, Any]:
    if value is None:
        return (1, "")  # PostgreSQL sorts NULL last in ascending order.
    if isinstance(value, bool):
        return (0, int(value))
    if isinstance(value, (int, float)):
        return (0, value)
    return (0, str(value))


def _order_terms(order: str) -> List[Tuple[str, bool]]:
    terms = []
    for term in order.split(","):
        parts = term.split(".")
        descending = "desc" in parts[1:]
        terms.append((parts[0], descending))
    return terms


def _in_values(criteria: str) -> List[str]:
    if not (criteria.startswith("(") and criteria.endswith(")")):
        raise AssertionError(f"malformed in filter {criteria!r}")
    values, current, quoted = [], "", False
    for char in criteria[1:-1]:
        if char == '"':
            quoted = not quoted
        elif char == "," and not quoted:
            values.append(current)
            current = ""
        else:
            current += char
    if current or values:
        values.append(current)
    return values


def _compare(left: Any, right: str) -> Optional[int]:
    if left is None:
        return None
    try:
        a, b = float(left), float(right)
    except (TypeError, ValueError):
        a, b = _text(left), right
    return (a > b) - (a < b)


def _predicate(expression: str) -> Callable[[Any], bool]:
    negate = expression.startswith("not.")
    if negate:
        expression = expression[4:]
    operator, _, criteria = expression.partition(".")
    if operator == "eq":
        def test(value):
            if isinstance(value, bool):  # The client sends Python's True/False.
                return _text(value).lower() == criteria.lower()
            return value is not None and _text(value) == criteria
    elif operator == "neq":
        def test(value):
            return value is not None and _text(value) != criteria
    elif operator == "in":
        allowed = set(_in_values(criteria))
        def test(value):
            return value is not None and _text(value) in allowed
    elif operator == "is":
        if criteria != "null":
            raise AssertionError(f"unsupported is filter {criteria!r}")
        def test(value):
            return value is None
    elif operator in {"gt", "gte", "lt", "lte"}:
        def test(value):
            order = _compare(value, criteria)
            return order is not None and {
                "gt": order > 0, "gte": order >= 0, "lt": order < 0, "lte": order <= 0,
            }[operator]
    else:
        raise AssertionError(f"unsupported filter operator {operator!r}")
    return (lambda value: not test(value)) if negate else test


def _select_items(select: str) -> List[str]:
    items, current, depth = [], "", 0
    for char in select:
        if char == "," and depth == 0:
            items.append(current.strip())
            current = ""
            continue
        depth += char == "("
        depth -= char == ")"
        current += char
    if current.strip():
        items.append(current.strip())
    return items


def _project(row: Mapping[str, Any], select: str) -> Dict[str, Any]:
    items = _select_items(select)
    if "*" in items:
        return dict(row)
    projected = {}
    for item in items:
        if "(" in item:  # An embedded resource is stored on the row under its name.
            name = item.split("(", 1)[0]
            key = name.split(":", 1)[0] if ":" in name else name.split("!", 1)[0]
            projected[key] = row.get(key)
        else:
            projected[item] = row.get(item)
    return projected
