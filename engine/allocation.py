"""Deterministic weighted allocation with shared plant and recipe constraints.

Progressive filling redistributes unused capacity when a position reaches its
target or an ingredient runs out. It is a fair feasible allocation, not a claim
of globally optimal commercial profit. No optional solver dependency is needed.
"""
import math


def allocate(caps, weights, capacity, raw, recipes):
    result = {p: 0.0 for p in caps}
    remaining = dict(raw)
    active = {p for p in caps if caps[p] > 0 and weights[p] > 0}
    room = max(0.0, capacity)
    while active and room > 1e-7:
        total = sum(weights[p] for p in sorted(active))
        step = min(room / total, min((caps[p]-result[p])/weights[p] for p in active))
        consumption = {m: sum(weights[p]*recipes[p].get(m, 0) for p in sorted(active)) for m in remaining}
        step = min([step] + [max(0, remaining[m])/v for m, v in consumption.items() if v > 0])
        if step > 1e-10:
            for p in sorted(active):
                result[p] += weights[p]*step
            room -= total*step
            for m, amount in consumption.items():
                remaining[m] = max(0, remaining[m]-amount*step)
        blocked = {m for m in remaining if remaining[m] < 1e-7}
        saturated = {p for p in active if caps[p]-result[p] < 1e-7 or any(recipes[p].get(m, 0)>0 for m in blocked)}
        if not saturated:
            break  # Shared plant capacity was exhausted.
        active -= saturated
    # Flooring preserves every shared material/capacity constraint.
    return {p: max(0, math.floor(v+1e-9)) for p, v in result.items()}
