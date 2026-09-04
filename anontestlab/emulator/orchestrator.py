"""Spins up the relay subprocesses, drives sessions of real traffic
through real telescoping circuits, and tears everything down.

Determinism note: each session gets its own RNG seeded from
`(config.seed, session_id)`, so *which* paths are chosen and *when*
packets are scheduled is fully reproducible from the seed, but sessions
run concurrently over real sockets, so the actual measured latency/
delivery timing will vary run to run like any real system's would. That's
real system behavior, not a bug; only the experiment design is pinned.
"""
from __future__ import annotations

import asyncio
import os
import random
import socket
import sys
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..adversary import SessionObservation, SimulationContext
from ..core.packet import Packet
from ..metrics import MetricsCollector
from ..routing import get_strategy
from ..traffic import get_generator
from . import wire
from .circuit_client import Circuit, build_circuit

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


MAX_RELAYS_PER_SUBNET = 254  # 127.0.0.1 .. 127.0.0.254


def _relay_host(index: int) -> str:
    """Each relay gets its own loopback IP (127.0.0.<n>) rather than
    sharing 127.0.0.1 on a random port. Avoids port exhaustion on large
    sweeps and makes tcpdump/Wireshark filtering sane (filter by IP, not
    an ephemeral port list). Every address in 127.0.0.0/8 is loopback on
    Linux with no extra configuration; macOS needs `ifconfig lo0 alias
    127.0.0.x` first for anything beyond 127.0.0.1.
    """
    if index >= MAX_RELAYS_PER_SUBNET:
        raise ValueError(f"more than {MAX_RELAYS_PER_SUBNET} relays not supported yet (got index {index})")
    return f"127.0.0.{index + 1}"


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
) -> list[RelayHandle]:
    handles = []
    for i in range(num_nodes):
        host = _relay_host(i)
        port = _find_free_port(host)
        is_watermark_node = watermark_period > 0 and i == WATERMARK_NODE_INDEX
        process = await asyncio.create_subprocess_exec(
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
            str(link_latency_ms),
            "--link-jitter-ms",
            str(link_jitter_ms),
            "--link-loss-probability",
            str(link_loss_probability),
            "--link-bandwidth-kbps",
            str(link_bandwidth_kbps or 0.0),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        handles.append(RelayHandle(node_id=f"n{i}", host=host, port=port, process=process))

    for h in handles:
        try:
            line = await asyncio.wait_for(h.process.stdout.readline(), timeout=READY_TIMEOUT_S)
        except asyncio.TimeoutError:
            await terminate_relays(handles)
            raise RuntimeError(f"relay {h.node_id} on port {h.port} did not start in time")
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


class PathSplitter:
    def __init__(self, strategy: str, num_paths: int):
        self.strategy = strategy
        self.num_paths = num_paths
        self._counters: dict[int, int] = {}

    def assign(self, session_id: int, rng: random.Random) -> int:
        if self.num_paths == 1:
            return 0
        if self.strategy == "random":
            return rng.randrange(self.num_paths)
        i = self._counters.get(session_id, 0)
        self._counters[session_id] = i + 1
        return i % self.num_paths


def _fixed_rate_schedule(real_times: list[float], config: ExperimentConfig) -> list[tuple[float, str]]:
    """Constant-output-rate schedule (Loopix-style baseline): a packet
    goes out at every fixed slot regardless of real demand: a real one
    if any is due, a dummy "cover" one otherwise. Real packets queue if
    they arrive faster than the fixed rate can drain them; this is
    deliberately simple, not adaptive.
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
    # Anything still queued past the last slot is real traffic the fixed
    # rate couldn't keep up with. Send it anyway, right away, rather
    # than silently dropping demand the experiment asked for.
    events += [(t, "real") for t in pending_real[i:]]
    events.sort(key=lambda e: e[0])
    return events


async def run_session(
    session_id: int,
    addr_paths: list[list[tuple[str, int]]],
    config: ExperimentConfig,
    rng: random.Random,
    splitter: PathSplitter,
    observed_entry_indices: set[int],
    observed_exit_indices: set[int],
    experiment_start: float,
) -> tuple[list[Packet], SessionObservation, float]:
    real_gen = get_generator(config.real_traffic_distribution, config.real_rate)
    cover_gen = (
        get_generator(config.cover_traffic_distribution, config.cover_rate)
        if config.cover_rate > 0
        else None
    )

    build_start = time.monotonic()
    circuits: list[Circuit] = await asyncio.gather(
        *[build_circuit(p, config.crypto_algorithm, config.cell_size) for p in addr_paths]
    )
    build_delay = time.monotonic() - build_start

    obs = SessionObservation(session_id=session_id)
    packets: list[Packet] = []
    pending: dict[tuple[int, int], Packet] = {}
    next_packet_id = 0

    async def listen(path_idx: int, circuit: Circuit) -> None:
        try:
            while True:
                packet_id = await circuit.recv_delivery()
                t = time.monotonic() - experiment_start
                pkt = pending.pop((path_idx, packet_id), None)
                if pkt is not None:
                    pkt.delivered_at = t
                    if path_idx in observed_exit_indices:
                        obs.egress_times.append(t)
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

        path_idx = splitter.assign(session_id, rng)
        circuit = circuits[path_idx]
        packet_id = await circuit.send(
            wire.KIND_REAL if kind == "real" else wire.KIND_COVER, os.urandom(PAYLOAD_SIZE)
        )
        t_send = time.monotonic() - experiment_start

        next_packet_id += 1
        pkt = Packet(packet_id=next_packet_id, session_id=session_id, kind=kind, path=[], created_at=t_send)
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
) -> tuple[MetricsCollector, SimulationContext, float]:
    handles = await spawn_relays(
        config.num_nodes,
        config.crypto_algorithm,
        config.cover_drop_probability,
        config.watermark_period,
        config.watermark_delay_ms,
        config.link_latency_ms,
        config.link_jitter_ms,
        config.link_loss_probability,
        config.link_bandwidth_kbps,
    )
    node_ids = [h.node_id for h in handles]
    addr_of = {h.node_id: (h.host, h.port) for h in handles}

    try:
        collector = MetricsCollector()
        observations: dict[int, SessionObservation] = {}
        session_paths: dict[int, list[list[str]]] = {}
        build_delays: list[float] = []

        path_specs = config.paths
        splitter = PathSplitter(config.split_strategy, len(path_specs))
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

            node_paths = [
                get_strategy(spec.strategy).select_path(node_ids, session_rng, spec.path_length)
                for spec in path_specs
            ]
            if config.watermark_period > 0:
                # The watermark relay only makes sense as hop 1. Pin it
                # there on the first path (swap rather than overwrite, to
                # keep the path's nodes distinct). It's not excluded from
                # other paths/positions it might land in by chance; a
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
            else:
                k = config.observed_path_count or len(path_specs)
                observed_entry_indices = observed_exit_indices = set(
                    session_rng.sample(range(len(path_specs)), min(k, len(path_specs)))
                )

            packets, obs, build_delay = await run_session(
                session_id,
                addr_paths,
                config,
                session_rng,
                splitter,
                observed_entry_indices,
                observed_exit_indices,
                experiment_start,
            )
            for p in packets:
                collector.record(p)
            observations[session_id] = obs
            build_delays.append(build_delay)

        await asyncio.gather(*[run_one(sid) for sid in range(config.num_sessions)])

        ctx = SimulationContext(sessions=observations, session_paths=session_paths, node_ids=node_ids)
        avg_build_delay = sum(build_delays) / len(build_delays) if build_delays else 0.0
        return collector, ctx, avg_build_delay
    finally:
        await terminate_relays(handles)


def run_experiment(config: ExperimentConfig) -> tuple[MetricsCollector, SimulationContext, float]:
    return asyncio.run(run_experiment_async(config))
