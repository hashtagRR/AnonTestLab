import random

from anontestlab.traffic import PoissonTraffic, ConstantRateTraffic


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
