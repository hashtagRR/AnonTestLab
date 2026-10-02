"""Spins up the relay subprocesses, drives sessions of real traffic
through real telescoping circuits, and tears everything down.

Determinism note: each session gets its own RNG seeded from
`(config.seed, session_id)`, so *which* paths are chosen and *when*
packets are scheduled is fully reproducible from the seed, but sessions
run concurrently over real sockets, so the actual measured latency/
delivery timing will vary run to run like any real system's would; only
the experiment design is pinned.
"""
from __future__ import annotations

import asyncio
import os
import random
import socket
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..adversary import SessionObservation, SimulationContext
from ..core.packet import Packet
from ..metrics import MetricsCollector
from ..routing import get_strategy
from ..traffic import get_generator
from . import wire
from .circuit_client import Circuit, build_circuit
from .splitting import LegScheduler

if TYPE_CHECKING:
    # Only needed for type hints; importing it at module level would
    # pull in anontestlab.experiment's __init__, which imports back into this
    # module (experiment.runner -> emulator.orchestrator), a real
    # circular-import hazard depending on which module is imported first.
    from ..experiment.config import ExperimentConfig

PAYLOAD_SIZE = 256
READY_TIMEOUT_S = 10.0


@dataclass
class RelayHandle:
    node_id: str
    host: str
    port: int
    process: asyncio.subprocess.Process
    bandwidth_weight: float = 1.0  # relative capacity, for bandwidth-weighted routing


_relay_host = wire.relay_host


def _find_free_port(host: str) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((host, 0))
        return s.getsockname()[1]


WATERMARK_NODE_INDEX = 0  # n0 is always the designated compromised-entry node when watermarking is on


async def spawn_relays(
    num_nodes: int,
    algorithm: str,
    drop_probability: float,
    watermark_period: int = 0,
    watermark_delay_ms: float = 0.0,
    link_latency_ms: float = 0.0,
    link_jitter_ms: float = 0.0,
    link_loss_probability: float = 0.0,
    link_bandwidth_kbps: float | None = None,
    link_factors: list[float] | None = None,
    keyexchange: str = "x25519",
    per_edge: bool = False,
    link_seed: int = 0,
    link_heterogeneity_spread: float = 0.5,
    mixing: dict | None = None,
    mix_seed: int = 0,
) -> list[RelayHandle]:
    """link_factors, if given, is one multiplicative scale per node index
    (node i's actual latency/jitter/loss/bandwidth = base * link_factors[i]),
    for a heterogeneous network instead of every relay sharing identical
    conditions. loss_probability is clamped to [0, 1] since a factor > 1
    could otherwise push it out of range.

    per_edge, if set, additionally scales each relay's forward-direction
    send to whichever peer it extends a circuit to, by a factor specific
    to that (relay, peer) pair rather than the relay's own single value;
    see relay_process.py::edge_factor for the directional-only scope of
    this (the receiving side's own upstream-facing sends aren't scaled
    by it, a disclosed simplification).

    mixing, if given, holds the relay-side mixing settings (strategy,
    delay_ms, pool_interval_ms, release_probability, interval_jitter),
    identical on every relay; each relay's mixing RNG is seeded from
    mix_seed + its index.
    """
    mixing = mixing or {}
    handles = []
    for i in range(num_nodes):
        host = _relay_host(i)
        port = _find_free_port(host)
        is_watermark_node = watermark_period > 0 and i == WATERMARK_NODE_INDEX
        factor = link_factors[i] if link_factors is not None else 1.0
        node_bandwidth_kbps = (link_bandwidth_kbps * factor) if link_bandwidth_kbps else 0.0
        args = [
            sys.executable,
            "-m",
            "anontestlab.emulator.relay_process",
            "--host",
            host,
            "--port",
            str(port),
            "--algorithm",
            algorithm,
            "--drop-probability",
            str(drop_probability),
            "--watermark-period",
            str(watermark_period if is_watermark_node else 0),
            "--watermark-delay-ms",
            str(watermark_delay_ms if is_watermark_node else 0.0),
            "--link-latency-ms",
            str(link_latency_ms * factor),
            "--link-jitter-ms",
            str(link_jitter_ms * factor),
            "--link-loss-probability",
            str(min(1.0, link_loss_probability * factor)),
            "--link-bandwidth-kbps",
            str(node_bandwidth_kbps),
            "--keyexchange",
            keyexchange,
            "--own-index",
            str(i),
            "--link-seed",
            str(link_seed),
            "--link-heterogeneity-spread",
            str(link_heterogeneity_spread),
            "--mix-strategy",
            str(mixing.get("strategy", "none")),
            "--mix-delay-ms",
            str(mixing.get("delay_ms", 0.0)),
            "--pool-interval-ms",
            str(mixing.get("pool_interval_ms", 100.0)),
            "--pool-release-probability",
            str(mixing.get("release_probability", 1.0)),
            "--pool-interval-jitter",
            str(mixing.get("interval_jitter", 0.0)),
            "--mix-seed",
            str(mix_seed + i),
        ]
        if per_edge:
            args.append("--per-edge")
        process = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        handles.append(
            RelayHandle(node_id=f"n{i}", host=host, port=port, process=process, bandwidth_weight=factor)
        )

    for h in handles:
        try:
            line = await asyncio.wait_for(h.process.stdout.readline(), timeout=READY_TIMEOUT_S)
        except asyncio.TimeoutError:
            await terminate_relays(handles)
            raise RuntimeError(f"relay {h.node_id} on port {h.port} did not start in time") from None
        if not line.startswith(b"READY"):
            stderr = (await h.process.stderr.read()).decode(errors="replace")
            await terminate_relays(handles)
            raise RuntimeError(f"relay {h.node_id} failed to start: {stderr}")
    return handles


async def terminate_relays(handles: list[RelayHandle]) -> None:
    for h in handles:
        if h.process.returncode is None:
            h.process.terminate()
    for h in handles:
        try:
            await asyncio.wait_for(h.process.wait(), timeout=5.0)
        except asyncio.TimeoutError:
            h.process.kill()
            await h.process.wait()


def make_scheduler(config: ExperimentConfig) -> LegScheduler:
    """A fresh split-policy state for one session (see emulator/splitting.py)."""
    return LegScheduler(
        config.split_strategy,
        config.num_paths,
        weights=config.split_weights,
        batch_mean_s=config.split_batch_mean_s,
        leg_rtt_s=[ms / 1000.0 for ms in config.split_leg_rtt_ms] if config.split_leg_rtt_ms else None,
        leg_window=config.split_leg_window,
    )


def select_node_paths(config: ExperimentConfig, node_ids: list[str], rng: random.Random, weights) -> list[list[str]]:
    """Relays for every leg of one session. With merge == "common_exit" all
    legs end at one exit relay (Conflux-style) and their other hops are
    drawn without reuse across legs, so every leg has its own entry guard."""
    specs = config.paths
    if config.merge != "common_exit" or len(specs) == 1:
        return [get_strategy(s.strategy).select_path(node_ids, rng, s.path_length, weights) for s in specs]
    exit_node = rng.choice(node_ids)
    used = {exit_node}
    paths = []
    for spec in specs:
        pool = [n for n in node_ids if n not in used]
        head = get_strategy(spec.strategy).select_path(pool, rng, spec.path_length - 1, weights)
        used.update(head)
        paths.append([*head, exit_node])
    return paths


def _fixed_rate_schedule(real_times: list[float], config: ExperimentConfig) -> list[tuple[float, str]]:
    """Constant-output-rate schedule (Loopix-style baseline): a packet
    goes out at every fixed slot regardless of real demand: a real one
    if any is due, a dummy "cover" one otherwise.

    If real demand exceeds the fixed rate's capacity within duration_s,
    the backlog keeps draining at that *same* fixed rate rather than
    bursting out immediately, since honoring the rate is the entire
    point of this mode: bursting would silently break the constant-rate
    guarantee an experiment is specifically trying to test. This can run
    the session past duration_s; ExperimentConfig.validate() warns when
    real_rate looks likely to exceed fixed_rate's capacity so that isn't
    a silent surprise.
    """
    gap = 1.0 / config.fixed_rate
    pending_real = list(real_times)
    events: list[tuple[float, str]] = []
    i = 0
    n_slots = int(config.duration_s / gap)
    for slot_index in range(n_slots):
        slot = slot_index * gap
        if i < len(pending_real) and pending_real[i] <= slot:
            events.append((slot, "real"))
            i += 1
        else:
            events.append((slot, "cover"))
    slot_index = n_slots
    while i < len(pending_real):
        events.append((slot_index * gap, "real"))
        i += 1
        slot_index += 1
    return events


async def run_session(
    session_id: int,
    addr_paths: list[list[tuple[str, int]]],
    config: ExperimentConfig,
    rng: random.Random,
    scheduler: LegScheduler,
    observed_entry_indices: set[int],
    observed_exit_indices: set[int],
    experiment_start: float,
) -> tuple[list[Packet], SessionObservation, float]:
    real_gen = get_generator(
        config.real_traffic_distribution,
        config.real_rate,
        burst_mean_cells=config.burst_mean_cells,
        burst_gap_ms=config.burst_gap_ms,
    )
    cover_gen = (
        get_generator(config.cover_traffic_distribution, config.cover_rate)
        if config.cover_rate > 0
        else None
    )

    build_start = time.monotonic()
    circuits: list[Circuit] = await asyncio.gather(
        *[
            build_circuit(p, config.crypto_algorithm, config.cell_size, config.crypto_keyexchange)
            for p in addr_paths
        ]
    )
    build_delay = time.monotonic() - build_start

    obs = SessionObservation(session_id=session_id, leg_real_counts=[0] * len(circuits))
    # Timestamps are measured from the experiment start, so concurrent flows
    # share one clock. In wave mode (max_concurrent_sessions) sessions run at
    # different times, and each one is measured from its own start instead,
    # so all flows line up on [0, duration_s] as if they had run together.
    origin = time.monotonic() if config.max_concurrent_sessions else experiment_start
    packets: list[Packet] = []
    pending: dict[tuple[int, int], Packet] = {}
    next_packet_id = 0
    real_seq_counter = 0  # 1-indexed count of real sends only, matching how the
    # watermark relay counts real cells reaching it (see relay_process.py);
    # nothing can be lost between client and hop 1 in this model, so this
    # stays in lockstep with the relay's own count

    async def listen(path_idx: int, circuit: Circuit) -> None:
        try:
            while True:
                packet_id, exit_t = await circuit.recv_delivery()
                t = time.monotonic() - origin
                pkt = pending.pop((path_idx, packet_id), None)
                if pkt is not None:
                    pkt.delivered_at = t
                    pkt.exit_at = exit_t - origin
                    if path_idx in observed_exit_indices:
                        # exit_t, not t: t is when the confirmation finished
                        # its own round trip back through every hop (with
                        # each hop's link conditions applied again on the
                        # way back), not when the packet actually left the
                        # exit hop, which is what a passive exit observer
                        # would actually see.
                        obs.egress_times.append(exit_t - origin)
                        obs.egress_seq.append(pkt.real_seq)
        except (asyncio.IncompleteReadError, ConnectionError, OSError):
            pass

    listener_tasks = [asyncio.create_task(listen(i, c)) for i, c in enumerate(circuits)]

    if config.traffic_mode == "fixed_rate":
        events = _fixed_rate_schedule(real_gen.emission_times(rng, config.duration_s), config)
    else:
        events = [(t, "real") for t in real_gen.emission_times(rng, config.duration_s)]
        if cover_gen is not None:
            events += [(t, "cover") for t in cover_gen.emission_times(rng, config.duration_s)]
        events.sort(key=lambda e: e[0])

    session_start = time.monotonic()
    for t, kind in events:
        target = session_start + t
        now = time.monotonic()
        if target > now:
            await asyncio.sleep(target - now)

        path_idx = scheduler.assign(t, rng)
        if kind == "real":
            obs.leg_real_counts[path_idx] += 1
        circuit = circuits[path_idx]
        terminate_at = None
        if kind == "cover" and config.cover_drop_mode == "random_hop":
            terminate_at = rng.randrange(len(circuit.path))  # the last index means the exit, which absorbs cover anyway
        packet_id = await circuit.send(
            wire.KIND_REAL if kind == "real" else wire.KIND_COVER, os.urandom(PAYLOAD_SIZE), terminate_at
        )
        t_send = time.monotonic() - origin

        next_packet_id += 1  # noqa: SIM113 - a Packet.packet_id counter, not this loop's index
        if kind == "real":
            real_seq_counter += 1
        pkt = Packet(
            packet_id=next_packet_id,
            session_id=session_id,
            kind=kind,
            path=[],
            created_at=t_send,
            real_seq=real_seq_counter if kind == "real" else None,
        )
        packets.append(pkt)
        if kind == "real":
            pending[(path_idx, packet_id)] = pkt
        if path_idx in observed_entry_indices:
            obs.ingress_times.append(t_send)

    await asyncio.sleep(config.grace_period_s)

    for task in listener_tasks:
        task.cancel()
    await asyncio.gather(*listener_tasks, return_exceptions=True)
    for circuit in circuits:
        await circuit.close()

    return packets, obs, build_delay


async def run_experiment_async(
    config: ExperimentConfig,
    on_progress: Callable[[dict], None] | None = None,
) -> tuple[MetricsCollector, SimulationContext, float, int]:
    def emit(event_type: str, **fields) -> None:
        if on_progress is not None:
            on_progress({"type": event_type, **fields})

    link_factors = None
    if config.link_heterogeneous:
        het_rng = random.Random(config.seed)
        spread = config.link_heterogeneity_spread
        link_factors = [het_rng.uniform(1 - spread, 1 + spread) for _ in range(config.num_nodes)]

    handles = await spawn_relays(
        config.num_nodes,
        config.crypto_algorithm,
        config.cover_drop_probability if config.cover_drop_mode == "per_hop" else 0.0,
        config.watermark_period,
        config.watermark_delay_ms,
        config.link_latency_ms,
        config.link_jitter_ms,
        config.link_loss_probability,
        config.link_bandwidth_kbps,
        link_factors,
        config.crypto_keyexchange,
        config.link_per_edge,
        config.seed * 7919 + 17,  # decorrelated from other seeded RNGs derived from config.seed
        config.link_heterogeneity_spread,
        {
            "strategy": config.mix_strategy,
            "delay_ms": config.mix_delay_ms,
            "pool_interval_ms": config.pool_interval_ms,
            "release_probability": config.pool_release_probability,
            "interval_jitter": config.pool_interval_jitter,
        },
        config.seed * 104729 + 31,  # decorrelated from the other seed-derived RNGs
    )
    node_ids = [h.node_id for h in handles]
    addr_of = {h.node_id: (h.host, h.port) for h in handles}
    node_weights = {h.node_id: h.bandwidth_weight for h in handles}
    # pids let a caller signal these specific OS processes directly (a stop
    # request, or future live-topology instrumentation) without reaching
    # back into this coroutine, which may be running on another thread's
    # event loop by the time the caller wants to act on them.
    emit("relays_ready", num_nodes=len(handles), pids=[h.process.pid for h in handles])

    try:
        collector = MetricsCollector()
        observations: dict[int, SessionObservation] = {}
        session_paths: dict[int, list[list[str]]] = {}
        build_delays: list[float] = []
        sessions_failed = 0
        sessions_completed = 0

        path_specs = config.paths
        experiment_start = time.monotonic()

        # AS-level partial observer: a structural property of where the
        # adversary sits in the network, fixed once for the whole
        # experiment (not re-rolled per session like path-count sampling).
        as_of = {node_id: i % config.num_as_groups for i, node_id in enumerate(node_ids)}
        if config.num_as_groups > 1:
            structural_rng = random.Random(config.seed)
            k_as = config.observed_as_count or config.num_as_groups
            observed_as_ids = set(structural_rng.sample(range(config.num_as_groups), min(k_as, config.num_as_groups)))

        async def run_one(session_id: int) -> None:
            session_rng = random.Random(config.seed * 1_000_003 + session_id + 1)

            node_paths = select_node_paths(config, node_ids, session_rng, node_weights)
            if config.watermark_period > 0:
                # The watermark relay only makes sense as hop 1. Pin it
                # there on the first path (swap rather than overwrite, to
                # keep the path's nodes distinct). It may still land in
                # other paths/positions by chance; a
                # known edge case for a deliberately simple model.
                watermark_node_id = node_ids[WATERMARK_NODE_INDEX]
                first_path = node_paths[0]
                if first_path[0] != watermark_node_id:
                    if watermark_node_id in first_path:
                        j = first_path.index(watermark_node_id)
                        first_path[0], first_path[j] = first_path[j], first_path[0]
                    else:
                        first_path[0] = watermark_node_id
            session_paths[session_id] = node_paths
            addr_paths = [[addr_of[n] for n in p] for p in node_paths]

            if config.num_as_groups > 1:
                observed_entry_indices = {i for i, p in enumerate(node_paths) if as_of[p[0]] in observed_as_ids}
                observed_exit_indices = {i for i, p in enumerate(node_paths) if as_of[p[-1]] in observed_as_ids}
            elif config.observed_legs is not None:
                observed_entry_indices = observed_exit_indices = set(config.observed_legs)
            else:
                k = config.observed_path_count or len(path_specs)
                observed_entry_indices = observed_exit_indices = set(
                    session_rng.sample(range(len(path_specs)), min(k, len(path_specs)))
                )
            if config.egress_observation == "merged":
                # the exit-side observer sees the whole flow after the legs merge
                observed_exit_indices = set(range(len(path_specs)))

            # A lost handshake packet (under configured link_loss_probability)
            # surfaces here as a ProtocolError (see wire.read_frame_timeout) or
            # a connection-level failure. That is realistic behavior worth
            # seeing; it must fail only *this* session and leave the rest of
            # the experiment running. session_paths above is already
            # recorded regardless, so path_compromise is unaffected.
            nonlocal sessions_failed, sessions_completed
            try:
                packets, obs, build_delay = await run_session(
                    session_id,
                    addr_paths,
                    config,
                    session_rng,
                    make_scheduler(config),
                    observed_entry_indices,
                    observed_exit_indices,
                    experiment_start,
                )
            except (wire.ProtocolError, OSError, ConnectionError) as e:
                sessions_failed += 1
                sessions_completed += 1
                emit(
                    "session_failed",
                    session_id=session_id,
                    completed=sessions_completed,
                    total=config.num_sessions,
                    error=str(e),
                    paths=node_paths,
                )
                return
            for p in packets:
                collector.record(p)
            observations[session_id] = obs
            build_delays.append(build_delay)
            sessions_completed += 1
            real_sent = sum(1 for p in packets if p.kind == "real")
            real_delivered = sum(1 for p in packets if p.kind == "real" and p.delivered)
            emit(
                "session_complete",
                session_id=session_id,
                completed=sessions_completed,
                total=config.num_sessions,
                paths=node_paths,
                real_sent=real_sent,
                real_delivered=real_delivered,
                build_delay_s=build_delay,
            )

        if config.max_concurrent_sessions:
            gate = asyncio.Semaphore(config.max_concurrent_sessions)

            async def gated(sid: int) -> None:
                async with gate:
                    await run_one(sid)

            await asyncio.gather(*[gated(sid) for sid in range(config.num_sessions)])
        else:
            await asyncio.gather(*[run_one(sid) for sid in range(config.num_sessions)])
        emit("experiment_complete", sessions_failed=sessions_failed, total=config.num_sessions)

        ctx = SimulationContext(sessions=observations, session_paths=session_paths, node_ids=node_ids)
        avg_build_delay = sum(build_delays) / len(build_delays) if build_delays else 0.0
        return collector, ctx, avg_build_delay, sessions_failed
    finally:
        await terminate_relays(handles)


def run_experiment(
    config: ExperimentConfig, on_progress: Callable[[dict], None] | None = None
) -> tuple[MetricsCollector, SimulationContext, float, int]:
    return asyncio.run(run_experiment_async(config, on_progress))
