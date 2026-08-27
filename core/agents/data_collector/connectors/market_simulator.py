"""Deterministic market simulator connector.

Generates plausible competitor price ticks via a seeded pseudo-random walk.
The seed is derived from (sku, current UTC hour), so results are stable
within an hour and drift over time. No network access, no global random state.
"""
from __future__ import annotations

import hashlib
import random
from datetime import datetime, timedelta, timezone
from typing import Optional

# Maximum deviation from base_price (fraction)
_MAX_DEVIATION = 0.08


def _seed_for(sku: str, hour_bucket: str) -> int:
    """Stable seed independent of PYTHONHASHSEED."""
    digest = hashlib.sha256(f"{sku}|{hour_bucket}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")


def generate_ticks(
    sku: str,
    title: str,
    base_price: float,
    depth: int = 5,
    horizon_minutes: int = 60,
    now: Optional[datetime] = None,
) -> list[dict]:
    """Generate `depth` deterministic competitor price ticks for a product.

    Prices follow a bounded random walk within +/-8% of base_price. Timestamps
    are spread evenly over the trailing `horizon_minutes` window ending at the
    top of the current hour-bucket (so repeated calls in the same hour produce
    identical output).
    """
    if depth <= 0 or base_price is None or base_price <= 0:
        return []

    now = now or datetime.now(timezone.utc)
    hour_bucket = now.strftime("%Y-%m-%dT%H")
    rng = random.Random(_seed_for(sku, hour_bucket))

    # Anchor timestamps to the start of the current hour so that two runs
    # within the same hour emit identical ticks (prices AND timestamps).
    anchor = now.replace(minute=0, second=0, microsecond=0)
    step = timedelta(minutes=horizon_minutes) / max(depth, 1)

    lo = base_price * (1.0 - _MAX_DEVIATION)
    hi = base_price * (1.0 + _MAX_DEVIATION)

    # Random walk: start near base, drift with small steps, clamp to bounds.
    price = base_price * (1.0 + rng.uniform(-0.03, 0.03))
    ticks: list[dict] = []
    for i in range(depth):
        price += base_price * rng.uniform(-0.02, 0.02)
        price = min(max(price, lo), hi)
        ts = anchor - step * (depth - 1 - i)
        ticks.append(
            {
                "sku": sku,
                "product_name": title,
                "competitor_price": round(price, 2),
                "demand_index": round(0.5 + rng.random() * 0.5, 3),
                "ts": ts.isoformat(),
                "source": "simulator",
            }
        )
    return ticks
