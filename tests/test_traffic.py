import random
import statistics

from anontestlab.traffic import PoissonTraffic, ConstantRateTraffic, ParetoTraffic


def test_poisson_traffic_stays_within_duration():
    rng = random.Random(1)
    gen = PoissonTraffic(rate=10)
    times = gen.emission_times(rng, duration=5.0)
    assert all(0 <= t < 5.0 for t in times)
    assert times == sorted(times)


def test_poisson_zero_rate_produces_nothing():
    rng = random.Random(1)
    gen = PoissonTraffic(rate=0)
    assert gen.emission_times(rng, duration=5.0) == []


def test_constant_rate_produces_evenly_spaced_packets():
    rng = random.Random(1)
    gen = ConstantRateTraffic(rate=2)  # one packet every 0.5s
    times = gen.emission_times(rng, duration=2.0)
    assert times == [0.5, 1.0, 1.5]


def test_pareto_traffic_stays_within_duration():
    rng = random.Random(1)
    gen = ParetoTraffic(rate=10)
    times = gen.emission_times(rng, duration=5.0)
    assert all(0 <= t < 5.0 for t in times)
    assert times == sorted(times)


def test_pareto_zero_rate_produces_nothing():
    rng = random.Random(1)
    gen = ParetoTraffic(rate=0)
    assert gen.emission_times(rng, duration=5.0) == []


def test_pareto_is_burstier_than_poisson_at_matched_rate():
    """Same mean rate, but Pareto's heavy tail should produce a higher
    coefficient of variation in gap sizes than Poisson's memoryless one."""
    rng_pareto = random.Random(7)
    rng_poisson = random.Random(7)
    pareto_gaps = _gaps(ParetoTraffic(rate=20).emission_times(rng_pareto, duration=200.0))
    poisson_gaps = _gaps(PoissonTraffic(rate=20).emission_times(rng_poisson, duration=200.0))

    cv_pareto = statistics.stdev(pareto_gaps) / statistics.mean(pareto_gaps)
    cv_poisson = statistics.stdev(poisson_gaps) / statistics.mean(poisson_gaps)
    assert cv_pareto > cv_poisson


def _gaps(times: list[float]) -> list[float]:
    return [b - a for a, b in zip(times, times[1:])]
