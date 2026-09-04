"""Wire framing for the emulator's control/relay protocol.

Frame:  [4-byte big-endian length][1-byte msg_type][8-byte circuit_id][body]

msg_type:
  HELLO       body = client ephemeral public key (length depends on the
              experiment's keyexchange curve: 32 bytes for x25519, 56 for
              x448, 65 for p256's uncompressed point)
  HELLO_REPLY body = server ephemeral public key, same curve as HELLO
  RELAY_FWD   body = nonce(12) + AEAD ciphertext, addressed to whichever
              hop owns the circuit key on the connection it arrives on
  RELAY_BACK  body = opaque bytes, always forwarded upstream verbatim by
              any hop that isn't the originator or the client

circuit_id is hop-local, not shared across the whole path: each EXTEND
carries the next hop-link's ID, so a link tap can't correlate sessions
by matching IDs across hops. Known simplification: RELAY_BACK bodies
aren't re-wrapped per hop on the way back. That's a disclosed scope
trim, not a claim of traffic-analysis resistance.
"""
from __future__ import annotations

import asyncio
import struct

HEADER = struct.Struct(">IB8s")  # length, msg_type, circuit_id
MSG_HELLO = 0x01
MSG_HELLO_REPLY = 0x02
MSG_RELAY_FWD = 0x03
MSG_RELAY_BACK = 0x04

CIRCUIT_ID_LEN = 8
NONCE_LEN = 12
PACK_DATA_HEADER_LEN = 10  # struct ">BBQ": cell_type + kind + packet_id
MAX_FRAME_LEN = 1 << 20  # 1 MiB, comfortably above any real cell_size, bounds a malformed length field

MAX_RELAYS_PER_SUBNET = 254  # 127.0.0.1 .. 127.0.0.254


def relay_host(index: int) -> str:
    """Each relay gets its own loopback IP (127.0.0.<n>) rather than
    sharing 127.0.0.1 on a random port. Avoids port exhaustion on large
    sweeps and makes tcpdump/Wireshark filtering sane (filter by IP, not
    an ephemeral port list). Every address in 127.0.0.0/8 is loopback on
    Linux with no extra configuration; macOS needs `ifconfig lo0 alias
    127.0.0.x` first for anything beyond 127.0.0.1. Shared between
    orchestrator.py (spawning relays) and relay_process.py (a relay
    recovering a peer's index from its EXTEND-cell host, for per-edge
    link conditions), so the two stay in sync by construction.
    """
    if index >= MAX_RELAYS_PER_SUBNET:
        raise ValueError(f"more than {MAX_RELAYS_PER_SUBNET} relays not supported yet (got index {index})")
    return f"127.0.0.{index + 1}"


def relay_index_from_host(host: str) -> int:
    """Inverse of relay_host. Raises ValueError for anything not in that
    exact 127.0.0.<n> form (e.g. an address a relay wasn't spawned at)."""
    prefix = "127.0.0."
    if not host.startswith(prefix):
        raise ValueError(f"'{host}' is not a relay_host()-formatted address")
    return int(host[len(prefix) :]) - 1


class ProtocolError(Exception):
    """A peer sent something that doesn't conform to the wire protocol.
    Distinct from a bug in this codebase (an AssertionError): this is
    for untrusted-input validation, which should never be silently
    disabled by running Python with -O."""


def layer_overhead(algorithm: str) -> int:
    """Bytes added by wrapping one more onion layer: an AEAD nonce, an
    authentication tag (0 for the "none" passthrough cipher), and the
    pack_data header re-added at each non-innermost layer."""
    tag_len = 0 if algorithm == "none" else 16
    return NONCE_LEN + tag_len + PACK_DATA_HEADER_LEN


def pack_frame(msg_type: int, circuit_id: bytes, body: bytes) -> bytes:
    assert len(circuit_id) == CIRCUIT_ID_LEN
    payload_len = 1 + CIRCUIT_ID_LEN + len(body)
    return struct.pack(">I", payload_len) + struct.pack(">B8s", msg_type, circuit_id) + body


PROTOCOL_TIMEOUT_S = 5.0  # bound for a single expected reply to something just sent. Comfortably
                           # above any realistic configured link_latency_ms + jitter, but short
                           # enough that a lost handshake packet doesn't stall local iteration.


async def read_frame_timeout(reader: asyncio.StreamReader, what: str) -> tuple[int, bytes, bytes]:
    """Use for a single expected reply to something just sent (a handshake
    step). Never for a loop awaiting an arbitrary future frame, where a
    long legitimate gap between events would falsely trip the timeout."""
    try:
        return await asyncio.wait_for(read_frame(reader), timeout=PROTOCOL_TIMEOUT_S)
    except asyncio.TimeoutError:
        raise ProtocolError(f"timed out after {PROTOCOL_TIMEOUT_S}s waiting for {what}") from None


async def read_frame(reader: asyncio.StreamReader) -> tuple[int, bytes, bytes] | None:
    length_bytes = await reader.readexactly(4)
    (payload_len,) = struct.unpack(">I", length_bytes)
    if payload_len < 9 or payload_len > MAX_FRAME_LEN:
        raise ProtocolError(f"frame length {payload_len} outside allowed range (9..{MAX_FRAME_LEN})")
    payload = await reader.readexactly(payload_len)
    msg_type, circuit_id = struct.unpack(">B8s", payload[:9])
    return msg_type, circuit_id, payload[9:]


def pack_extend(host: str, port: int, next_client_pub: bytes, next_circuit_id: bytes) -> bytes:
    """The pubkey field is length-prefixed (not a fixed width) since its
    size depends on the experiment's keyexchange curve (32/56/65 bytes
    for x25519/x448/p256), and every hop must be able to parse an EXTEND
    cell without being separately told which curve is in use."""
    host_bytes = host.encode("ascii")
    return (
        struct.pack(">BB", 0x01, len(host_bytes))
        + host_bytes
        + struct.pack(">H", port)
        + struct.pack(">B", len(next_client_pub))
        + next_client_pub
        + next_circuit_id
    )


def unpack_extend(body: bytes) -> tuple[str, int, bytes, bytes]:
    _cell_type, host_len = struct.unpack(">BB", body[:2])
    offset = 2
    host = body[offset : offset + host_len].decode("ascii")
    offset += host_len
    (port,) = struct.unpack(">H", body[offset : offset + 2])
    offset += 2
    (pub_len,) = struct.unpack(">B", body[offset : offset + 1])
    offset += 1
    next_client_pub = body[offset : offset + pub_len]
    offset += pub_len
    next_circuit_id = body[offset : offset + CIRCUIT_ID_LEN]
    return host, port, next_client_pub, next_circuit_id


def pack_data(kind: int, packet_id: int, inner: bytes) -> bytes:
    return struct.pack(">BBQ", 0x02, kind, packet_id) + inner


def unpack_data(body: bytes) -> tuple[int, int, bytes]:
    _cell_type, kind, packet_id = struct.unpack(">BBQ", body[:10])
    return kind, packet_id, body[10:]


def cell_type(plaintext: bytes) -> int:
    return plaintext[0]


CELL_EXTEND = 0x01
CELL_DATA = 0x02

KIND_REAL = 0
KIND_COVER = 1
KIND_CONTROL = 2  # an EXTEND cell in transit through an already-established
                  # intermediate hop, wrapped as pack_data so it can be
                  # forwarded uniformly. Must not be mistaken for real
                  # user traffic by kind-sensitive hop behavior (cover-drop,
                  # watermark counting, etc).
KIND_REAL_FRAGMENT = 3  # a non-final fragment of a real payload split across
                  # multiple cells (see circuit_client.py::Circuit.send).
                  # Forwarded exactly like KIND_REAL (including watermark
                  # counting), but the terminal hop must not confirm it:
                  # only the final fragment, sent as plain KIND_REAL,
                  # triggers a delivery confirmation.
