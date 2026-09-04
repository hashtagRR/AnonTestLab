"""A single relay (mix node), run as its own OS process.

Generic behavior only: accept a HELLO, derive per-circuit forward and
backward keys via ephemeral ECDHE + HKDF, then for each RELAY_FWD frame
decrypt exactly one layer and either act on it (EXTEND the circuit, or
terminate a DATA cell addressed to this hop) or forward the revealed
plaintext downstream untouched. Every hop parses cell_type/kind from its
own layer (needed so an intermediate hop can apply the cover-drop
policy), but never sees plaintext meant for a later hop or the final
application payload unless it IS that hop. The reverse direction is
onion-encrypted too: every RELAY_BACK a hop sends upstream (whether it
originated it or is just relaying one from further downstream) gets
sealed with that hop's own backward key first, so the client peels one
layer per hop, symmetric with how the forward direction works.
"""
from __future__ import annotations

import argparse
import asyncio
import random
import struct
import sys
from dataclasses import dataclass, field

from . import crypto_layer, wire


@dataclass
class CircuitState:
    key_fwd: bytes
    key_back: bytes
    upstream_writer: asyncio.StreamWriter
    upstream_cid: bytes
    downstream_writer: asyncio.StreamWriter | None = None
    downstream_cid: bytes | None = None
    real_packet_count: int = 0


@dataclass
class RelayState:
    algorithm: str
    drop_probability: float
    keyexchange: str = "x25519"
    watermark_period: int = 0  # 0 = watermarking disabled
    watermark_delay_s: float = 0.0
    link_latency_s: float = 0.0
    link_jitter_s: float = 0.0
    link_loss_probability: float = 0.0
    link_bandwidth_kbps: float | None = None  # None = unlimited
    circuits: dict[bytes, CircuitState] = field(default_factory=dict)


async def apply_link_conditions(state: RelayState, nbytes: int) -> bool:
    """Models the link this hop is about to transmit on: real per-hop
    latency/jitter/loss/bandwidth applied uniformly to every link in the
    network (not per-edge; that would need a full topology model).
    Returns False if this transmission is lost and must not be forwarded.
    """
    if state.link_loss_probability > 0 and random.random() < state.link_loss_probability:
        return False
    delay = 0.0
    if state.link_latency_s > 0 or state.link_jitter_s > 0:
        delay += max(0.0, random.gauss(state.link_latency_s, state.link_jitter_s))
    if state.link_bandwidth_kbps:
        delay += (nbytes * 8 / 1000) / state.link_bandwidth_kbps
    if delay > 0:
        await asyncio.sleep(delay)
    return True


async def open_downstream(
    host: str, port: int, circuit_id: bytes, next_client_pub: bytes, state: RelayState
) -> tuple[asyncio.StreamReader, asyncio.StreamWriter, bytes]:
    reader, writer = await asyncio.open_connection(host, port)
    # If the HELLO itself is "lost" per link conditions, skip the write and
    # let the read below time out naturally, the same way a real sender
    # would (never told, just eventually gives up), no special-casing needed.
    if await apply_link_conditions(state, len(next_client_pub)):
        writer.write(wire.pack_frame(wire.MSG_HELLO, circuit_id, next_client_pub))
        await writer.drain()
    msg_type, _cid, body = await wire.read_frame_timeout(reader, "HELLO_REPLY")
    if msg_type != wire.MSG_HELLO_REPLY:
        raise wire.ProtocolError(f"expected HELLO_REPLY, got msg_type={msg_type}")
    return reader, writer, body


async def forward_downstream_to_upstream(
    d_reader: asyncio.StreamReader, circuit: CircuitState, state: RelayState
) -> None:
    """Relays both EXTENDED confirmations (circuit build) and DELIVERED
    confirmations (data phase) upstream, subject to this hop's link
    conditions like every other transmission. Re-seals whatever it
    receives with this hop's own backward key before forwarding (see
    circuit_client.py::unwrap_backward for how the client peels these
    layers back off), so the return path is onion-encrypted the same way
    the forward path is, not forwarded in the clear. Safe to lose one
    here now that `build_circuit`'s reads have a timeout (see
    `wire.read_frame_timeout`): a lost EXTENDED reply surfaces as a
    clear ProtocolError instead of hanging forever.
    """
    try:
        while True:
            _msg_type, _cid, body = await wire.read_frame(d_reader)
            sealed = crypto_layer.seal(state.algorithm, circuit.key_back, body, aad=circuit.upstream_cid)
            if not await apply_link_conditions(state, len(sealed)):
                continue  # lost on this hop's upstream link
            circuit.upstream_writer.write(wire.pack_frame(wire.MSG_RELAY_BACK, circuit.upstream_cid, sealed))
            await circuit.upstream_writer.drain()
    except asyncio.IncompleteReadError:
        pass


async def process_relay_fwd(state: RelayState, circuit: CircuitState, plaintext: bytes) -> None:
    ctype = wire.cell_type(plaintext)

    if ctype == wire.CELL_EXTEND:
        host, port, next_pub, next_circuit_id = wire.unpack_extend(plaintext)
        _d_reader, d_writer, server_pub = await open_downstream(host, port, next_circuit_id, next_pub, state)
        circuit.downstream_writer = d_writer
        circuit.downstream_cid = next_circuit_id
        asyncio.create_task(forward_downstream_to_upstream(_d_reader, circuit, state))
        sealed_pub = crypto_layer.seal(state.algorithm, circuit.key_back, server_pub, aad=circuit.upstream_cid)
        if await apply_link_conditions(state, len(sealed_pub)):
            circuit.upstream_writer.write(wire.pack_frame(wire.MSG_RELAY_BACK, circuit.upstream_cid, sealed_pub))
            await circuit.upstream_writer.drain()
        return

    if ctype == wire.CELL_DATA:
        kind, packet_id, inner = wire.unpack_data(plaintext)
        if circuit.downstream_writer is not None:
            if (
                kind == wire.KIND_COVER
                and state.drop_probability > 0
                and random.random() < state.drop_probability
            ):
                return  # dropped at this hop
            if kind == wire.KIND_REAL and state.watermark_period > 0:
                circuit.real_packet_count += 1
                if circuit.real_packet_count % state.watermark_period == 0:
                    await asyncio.sleep(state.watermark_delay_s)
            if not await apply_link_conditions(state, len(inner)):
                return  # lost on this hop's outbound link
            circuit.downstream_writer.write(wire.pack_frame(wire.MSG_RELAY_FWD, circuit.downstream_cid, inner))
            await circuit.downstream_writer.drain()
        elif kind == wire.KIND_REAL:
            confirmation = struct.pack(">Q", packet_id)
            sealed = crypto_layer.seal(state.algorithm, circuit.key_back, confirmation, aad=circuit.upstream_cid)
            if not await apply_link_conditions(state, len(sealed)):
                return
            circuit.upstream_writer.write(wire.pack_frame(wire.MSG_RELAY_BACK, circuit.upstream_cid, sealed))
            await circuit.upstream_writer.drain()
        # cover packet at the terminal hop: silently discarded, no confirmation


async def handle_connection(
    reader: asyncio.StreamReader, writer: asyncio.StreamWriter, state: RelayState
) -> None:
    try:
        msg_type, circuit_id, body = await wire.read_frame(reader)
        if msg_type != wire.MSG_HELLO:
            return
        client_pub = body
        priv, server_pub = crypto_layer.generate_ephemeral_keypair(state.keyexchange)
        key_fwd, key_back = crypto_layer.derive_key(priv, client_pub, state.algorithm, state.keyexchange)
        if await apply_link_conditions(state, len(server_pub)):
            writer.write(wire.pack_frame(wire.MSG_HELLO_REPLY, circuit_id, server_pub))
            await writer.drain()

        circuit = CircuitState(
            key_fwd=key_fwd, key_back=key_back, upstream_writer=writer, upstream_cid=circuit_id
        )
        state.circuits[circuit_id] = circuit

        while True:
            msg_type, cid, body = await wire.read_frame(reader)
            if msg_type != wire.MSG_RELAY_FWD:
                continue
            plaintext = crypto_layer.open_sealed(state.algorithm, circuit.key_fwd, body, aad=cid)
            await process_relay_fwd(state, circuit, plaintext)
    except asyncio.IncompleteReadError:
        pass
    finally:
        writer.close()


async def run_relay(
    host: str,
    port: int,
    algorithm: str,
    drop_probability: float,
    watermark_period: int = 0,
    watermark_delay_s: float = 0.0,
    link_latency_s: float = 0.0,
    link_jitter_s: float = 0.0,
    link_loss_probability: float = 0.0,
    link_bandwidth_kbps: float | None = None,
    keyexchange: str = "x25519",
) -> None:
    state = RelayState(
        algorithm=algorithm,
        drop_probability=drop_probability,
        keyexchange=keyexchange,
        watermark_period=watermark_period,
        watermark_delay_s=watermark_delay_s,
        link_latency_s=link_latency_s,
        link_jitter_s=link_jitter_s,
        link_loss_probability=link_loss_probability,
        link_bandwidth_kbps=link_bandwidth_kbps,
    )
    server = await asyncio.start_server(
        lambda r, w: handle_connection(r, w, state), host=host, port=port
    )
    print(f"READY {port}", flush=True)
    async with server:
        await server.serve_forever()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", type=str, default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--algorithm", type=str, default="none")
    parser.add_argument("--drop-probability", type=float, default=0.0)
    parser.add_argument("--watermark-period", type=int, default=0)
    parser.add_argument("--watermark-delay-ms", type=float, default=0.0)
    parser.add_argument("--link-latency-ms", type=float, default=0.0)
    parser.add_argument("--link-jitter-ms", type=float, default=0.0)
    parser.add_argument("--link-loss-probability", type=float, default=0.0)
    parser.add_argument("--link-bandwidth-kbps", type=float, default=0.0)
    parser.add_argument("--keyexchange", type=str, default="x25519")
    args = parser.parse_args()
    try:
        asyncio.run(
            run_relay(
                args.host,
                args.port,
                args.algorithm,
                args.drop_probability,
                args.watermark_period,
                args.watermark_delay_ms / 1000.0,
                args.link_latency_ms / 1000.0,
                args.link_jitter_ms / 1000.0,
                args.link_loss_probability,
                args.link_bandwidth_kbps or None,
                args.keyexchange,
            )
        )
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
