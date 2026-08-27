from datetime import datetime, timezone

from core.agents.data_collector.connectors.market_simulator import generate_ticks

NOW = datetime(2026, 8, 27, 10, 30, tzinfo=timezone.utc)


def test_generates_requested_depth():
    ticks = generate_ticks("LAPTOP-001", "MacBook Pro", 1999.0, depth=7, now=NOW)
    assert len(ticks) == 7
    for t in ticks:
        assert t["sku"] == "LAPTOP-001"
        assert t["source"] == "simulator"
        assert t["competitor_price"] > 0
        assert t["ts"]


def test_prices_within_8_percent_of_base():
    base = 1999.0
    for depth in (1, 5, 25):
        for t in generate_ticks("LAPTOP-001", "MacBook Pro", base, depth=depth, now=NOW):
            assert base * 0.92 <= t["competitor_price"] <= base * 1.08


def test_deterministic_within_same_hour():
    a = generate_ticks("LAPTOP-001", "MacBook Pro", 1999.0, depth=5, now=NOW)
    b = generate_ticks(
        "LAPTOP-001", "MacBook Pro", 1999.0, depth=5,
        now=NOW.replace(minute=59, second=59),
    )
    assert a == b


def test_drifts_across_hours_and_skus():
    a = generate_ticks("LAPTOP-001", "MacBook Pro", 1999.0, depth=5, now=NOW)
    later = generate_ticks(
        "LAPTOP-001", "MacBook Pro", 1999.0, depth=5,
        now=NOW.replace(hour=11),
    )
    other = generate_ticks("LAPTOP-002", "Dell XPS", 1999.0, depth=5, now=NOW)
    assert [t["competitor_price"] for t in a] != [t["competitor_price"] for t in later]
    assert [t["competitor_price"] for t in a] != [t["competitor_price"] for t in other]


def test_timestamps_spread_over_horizon():
    ticks = generate_ticks(
        "LAPTOP-001", "MacBook Pro", 1999.0, depth=4, horizon_minutes=60, now=NOW
    )
    stamps = [datetime.fromisoformat(t["ts"]) for t in ticks]
    assert stamps == sorted(stamps)
    assert (stamps[-1] - stamps[0]).total_seconds() <= 60 * 60
    assert stamps[-1] == NOW.replace(minute=0)


def test_invalid_inputs_return_empty():
    assert generate_ticks("X", "X", 0.0, depth=5, now=NOW) == []
    assert generate_ticks("X", "X", 100.0, depth=0, now=NOW) == []
