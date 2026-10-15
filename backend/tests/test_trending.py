import math
from datetime import datetime, timedelta, timezone

from app.services.trending_calculator import QueryState, TrendingCalculator


def test_new_query_starts_at_delta():
    [u] = TrendingCalculator(0.5).compute_decayed_updates({"q": 4}, [])
    assert (u.historical_count, u.new_recent_count) == (4, 4.0)


def test_exponential_decay_matches_closed_form():
    last = datetime.now(timezone.utc) - timedelta(hours=2)
    row = QueryState("q", historical_count=100, recent_count=10.0, last_decay_at=last)
    [u] = TrendingCalculator(0.5).compute_decayed_updates({"q": 3}, [row])
    assert u.historical_count == 103
    assert math.isclose(u.new_recent_count, 10.0 * math.exp(-1.0) + 3, rel_tol=1e-3)


def test_half_life_semantics_and_naive_datetimes_are_treated_as_utc():
    last = (datetime.now(timezone.utc) - timedelta(hours=math.log(2) / 0.5)).replace(tzinfo=None)
    row = QueryState("q", 0, 8.0, last)
    [u] = TrendingCalculator(0.5).compute_decayed_updates({"q": 0}, [row])
    assert math.isclose(u.new_recent_count, 4.0, rel_tol=1e-3)
