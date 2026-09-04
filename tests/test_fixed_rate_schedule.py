"""Fast pure-Python tests for the fixed-rate traffic schedule. No
subprocesses/sockets needed."""
import pytest

from anontestlab.emulator.orchestrator import _fixed_rate_schedule
from anontestlab.experiment.config import ExperimentConfig


def _config(**overrides):
    base = dict(name="t", fixed_rate=10.0, duration_s=1.0)
    base.update(overrides)
    return ExperimentConfig(**base)


def test_no_real_demand_fills_every_slot_with_cover():
    events = _fixed_rate_schedule([], _config())
    assert len(events) == 10  # 1.0s at 10 slots/sec
    assert all(kind == "cover" for _t, kind in events)


def test_real_demand_consumes_a_slot_instead_of_cover():
    events = _fixed_rate_schedule([0.05], _config())
    kinds = [kind for _t, kind in events]
    assert kinds.count("real") == 1
    assert kinds.count("cover") == len(events) - 1


def test_output_rate_is_constant_regardless_of_real_rate():
    """The whole point: total packets out equals the fixed rate schedule,
    not the real traffic rate: same total whether demand is low or high."""
    low_demand = _fixed_rate_schedule([0.5], _config())
    high_demand = _fixed_rate_schedule([0.01 * i for i in range(1, 9)], _config())
    assert len(low_demand) == len(high_demand) == 10


def test_backlog_beyond_last_slot_still_gets_sent():
    """More real demand than the fixed rate can drain within duration:
    don't silently drop it, keep draining it after the schedule ends."""
    events = _fixed_rate_schedule([0.99] * 20, _config(fixed_rate=1.0, duration_s=1.0))
    real_count = sum(1 for _t, kind in events if kind == "real")
    assert real_count == 20


def test_backlog_keeps_draining_at_the_fixed_rate_not_bursted():
    """The whole point of fixed_rate mode: overflow must not violate the
    rate guarantee by bursting out immediately at the original arrival
    time. It should continue at the same slot spacing instead."""
    config = _config(fixed_rate=2.0, duration_s=1.0)  # gap = 0.5s
    events = _fixed_rate_schedule([0.99] * 4, config)
    real_times = sorted(t for t, kind in events if kind == "real")
    gaps = [b - a for a, b in zip(real_times, real_times[1:])]
    assert all(g == pytest.approx(0.5) for g in gaps)
    # None of the overflow should be bursted at the original 0.99 arrival time.
    assert real_times[-1] > 1.5


def test_events_are_sorted_by_time():
    events = _fixed_rate_schedule([0.5] * 30, _config(fixed_rate=2.0, duration_s=1.0))
    times = [t for t, _kind in events]
    assert times == sorted(times)
