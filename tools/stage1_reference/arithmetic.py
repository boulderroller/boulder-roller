"""Exact allocation in base units, with stable UTF-8 tie breaks."""

from fractions import Fraction


def integer(value, minimum=0):
    if type(value) is not int or value < minimum:
        raise ValueError("expected an integer within bounds")
    return value


def ceil(value: Fraction) -> int:
    return -(-value.numerator // value.denominator)


def apportion(amount: int, weights: dict[str, int | Fraction], tie_ranks=None) -> dict[str, int]:
    """Hamilton largest remainders; no rounding dust disappears."""
    integer(amount)
    if any(not isinstance(weight, (int, Fraction)) or isinstance(weight, bool) or weight < 0 for weight in weights.values()):
        raise ValueError("weights must be nonnegative exact numbers")
    positive = {key: Fraction(weight) for key, weight in weights.items() if weight > 0}
    if not positive:
        return {}
    total = sum(positive.values())
    exact = {key: amount * weight / total for key, weight in positive.items()}
    result = {key: value.numerator // value.denominator for key, value in exact.items()}
    order = sorted(exact, key=lambda key: (-(exact[key] - result[key]), tie_ranks[key] if tie_ranks is not None else key.encode("utf-8")))
    for key in order[:amount - sum(result.values())]:
        result[key] += 1
    return result


def median_cap(entitlements: dict[str, int], multiplier: Fraction) -> int:
    values = sorted(value for value in entitlements.values() if value > 0)
    if not values:
        return 0
    n = len(values)
    median = Fraction(values[n // 2]) if n % 2 else Fraction(values[n // 2 - 1] + values[n // 2], 2)
    value = median * multiplier
    return value.numerator // value.denominator


def redistribute(amount, weights, paid, cap):
    """Water fill against a FIXED cap. Return payments and unallocatable remainder."""
    added = {}
    while amount:
        eligible = {person: weight for person, weight in weights.items() if weight > 0 and paid.get(person, 0) + added.get(person, 0) < cap}
        if not eligible:
            break
        proposal = apportion(amount, eligible)
        moved = 0
        for person, share in proposal.items():
            take = min(share, cap - paid.get(person, 0) - added.get(person, 0))
            added[person] = added.get(person, 0) + take
            moved += take
        if not moved:
            break
        amount -= moved
    return added, amount
