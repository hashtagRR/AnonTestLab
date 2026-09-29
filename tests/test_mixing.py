"""Relay-side mixing (emulator/mixing.py) and random-hop cover
termination. The Mixer tests run the real asyncio scheduling with short
delays and measure the resulting send times. The integration tests at
the bottom spawn real relays."""
import asyncio
import random
import time
import warnings

import pytest

from anontestlab.emulator import crypto_layer, wire
from anontestlab.emulator.circuit_client import wrap_layers
from anontestlab.emulator.mixing import Mixer
from anontestlab.experiment import ExperimentConfig, run_experiment


def _recorder():
    sent: list[tuple[int, float]] = []

    def make(i: int):
        async def send() -> None:
            sent.append((i, time.monotonic()))

        return send

    return sent, make


def test_none_sends_inline_in_order():
    async def main():
        sent, make = _recorder()
        m = Mixer("none")
        for i in range(5):
            await m.submit(make(i))
        return sent

    sent = asyncio.run(main())
    assert [i for i, _ in sent] == [0, 1, 2, 3, 4]


def test_constant_delay_shifts_without_reordering():
    async def main():
        sent, make = _recorder()
        m = Mixer("constant", delay_s=0.05)
        start = time.monotonic()
        for i in range(5):
            await m.submit(make(i))
        assert sent == []  # nothing leaves before its delay
        await asyncio.sleep(0.15)
        return sent, start

    sent, start = asyncio.run(main())
    assert [i for i, _ in sent] == [0, 1, 2, 3, 4]
    assert all(t - start >= 0.045 for _, t in sent)


def test_exponential_delay_has_roughly_the_configured_mean():
    async def main():
        sent, make = _recorder()
        m = Mixer("exponential", delay_s=0.02, rng=random.Random(7))
        start = time.monotonic()
        for i in range(300):
            await m.submit(make(i))
        await asyncio.sleep(0.4)
        return sent, start

    sent, start = asyncio.run(main())
    assert len(sent) == 300
    mean = sum(t - start for _, t in sent) / len(sent)
    assert 0.012 < mean < 0.035
    assert [i for i, _ in sent] != list(range(300))  # independent delays reorder cells


def test_pool_holds_cells_until_flush_then_releases_a_burst():
    async def main():
        sent, make = _recorder()
        m = Mixer("pool", interval_s=0.08, rng=random.Random(3))
        for i in range(20):
            await m.submit(make(i))
        await asyncio.sleep(0.03)
        before = len(sent)
        await asyncio.sleep(0.1)
        return before, sent

    before, sent = asyncio.run(main())
    assert before == 0
    assert sorted(i for i, _ in sent) == list(range(20))
    times = [t for _, t in sent]
    assert max(times) - min(times) < 0.02  # released as one burst
    assert [i for i, _ in sent] != list(range(20))  # shuffled on release


def test_retained_pool_conserves_cells_across_flushes():
    async def main():
        sent, make = _recorder()
        m = Mixer("pool", interval_s=1000.0, release_probability=0.3, rng=random.Random(11))
        for i in range(200):
            await m.submit(make(i))
        first = m.flush()
        await asyncio.sleep(0)
        assert first + m.pool_size == 200
        assert 20 < first < 100  # about 30% released, the rest retained
        for _ in range(60):
            m.flush()
        await asyncio.sleep(0.01)
        return sent, m.pool_size

    sent, remaining = asyncio.run(main())
    assert remaining == 0
    assert sorted(i for i, _ in sent) == list(range(200))  # nothing lost or duplicated


def test_unknown_strategy_is_rejected():
    with pytest.raises(ValueError):
        Mixer("bogus")


def _layer_kinds(n_hops: int, terminate_at):
    keys = [bytes(32)] * n_hops
    cids = [bytes(wire.CIRCUIT_ID_LEN)] * n_hops
    layer = wrap_layers(keys, cids, b"target", "none", wire.KIND_COVER, 9, terminate_at)
    kinds = []
    for hop in range(n_hops - 1):
        plaintext = crypto_layer.open_sealed("none", keys[hop], layer, aad=cids[hop])
        kind, packet_id, layer = wire.unpack_data(plaintext)
        assert packet_id == 9
        kinds.append(kind)
    return kinds


def test_random_hop_marks_exactly_the_chosen_layer():
    for hop in range(3):
        kinds = _layer_kinds(4, hop)
        assert kinds.count(wire.KIND_COVER_TERMINATE) == 1
        assert kinds[hop] == wire.KIND_COVER_TERMINATE
        assert all(k == wire.KIND_COVER for i, k in enumerate(kinds) if i != hop)


def test_no_terminate_mark_by_default():
    assert wire.KIND_COVER_TERMINATE not in _layer_kinds(4, None)


def _small(**overrides) -> ExperimentConfig:
    base = {
        "name": "mix-test",
        "seed": 5,
        "duration_s": 1.0,
        "grace_period_s": 1.5,
        "num_nodes": 5,
        "num_sessions": 3,
        "path_length": 3,
        "real_rate": 6.0,
        "crypto_algorithm": "aes256gcm",
        "adversaries": ["global_observer"],
    }
    base.update(overrides)
    return ExperimentConfig(**base)


def test_exponential_mixing_adds_latency_on_real_relays():
    plain = run_experiment(_small()).metrics
    mixed = run_experiment(_small(mix_strategy="exponential", mix_delay_ms=40.0)).metrics
    assert mixed["delivery_rate"] == 1.0
    # three hops of 40 ms mean each: well above the unmixed localhost latency
    assert mixed["avg_latency_s"] > plain["avg_latency_s"] + 0.05


def test_pool_mixing_delivers_everything_on_real_relays():
    m = run_experiment(_small(mix_strategy="pool", pool_interval_ms=50.0)).metrics
    assert m["delivery_rate"] == 1.0
    assert m["avg_latency_s"] > 0.03


def test_random_hop_cover_keeps_real_traffic_intact():
    m = run_experiment(_small(cover_rate=8.0, cover_drop_mode="random_hop")).metrics
    assert m["delivery_rate"] == 1.0
    assert m["cover_packets_sent"] > 0


def test_mixing_config_validation():
    with pytest.raises(ValueError):
        _small(mix_strategy="exponential", mix_delay_ms=0.0).validate()
    with pytest.raises(ValueError):
        _small(mix_strategy="pool", pool_release_probability=0.0).validate()
    with pytest.raises(ValueError):
        _small(cover_drop_mode="sometimes").validate()


def test_grace_period_warning_for_long_mixing():
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        _small(mix_strategy="pool", pool_interval_ms=500.0, pool_release_probability=0.2).validate()
    assert any("grace_period_s" in str(w.message) for w in caught)
