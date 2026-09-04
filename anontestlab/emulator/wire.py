"""Wire framing for the emulator's control/relay protocol.

Frame:  [4-byte big-endian length][1-byte msg_type][8-byte circuit_id][body]

msg_type:
  HELLO       body = client ephemeral X25519 public key (32 bytes)
  HELLO_REPLY body = server ephemeral X25519 public key (32 bytes)
  RELAY_FWD   body = nonce(12) + AEAD ciphertext, addressed to whichever
              hop owns the circuit key on the connection it arrives on
  RELAY_BACK  body = opaque bytes, always forwarded upstream verbatim by
              any hop that isn't the originator or the client

Known simplification (v0.1): the circuit_id is constant across the whole
path rather than re-randomized per hop, and RELAY_BACK bodies aren't
re-wrapped per hop on the way back. That's a disclosed scope trim, not a
claim of traffic-analysis resistance.
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
PUBKEY_LEN = 32
NONCE_LEN = 12
PACK_DATA_HEADER_LEN = 10  # struct ">BBQ": cell_type + kind + packet_id


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


async def read_frame(reader: asyncio.StreamReader) -> tuple[int, bytes, bytes] | None:
    length_bytes = await reader.readexactly(4)
    (payload_len,) = struct.unpack(">I", length_bytes)
    payload = await reader.readexactly(payload_len)
    msg_type, circuit_id = struct.unpack(">B8s", payload[:9])
    return msg_type, circuit_id, payload[9:]


def pack_extend(host: str, port: int, next_client_pub: bytes, next_circuit_id: bytes) -> bytes:
    host_bytes = host.encode("ascii")
    return (
        struct.pack(">BB", 0x01, len(host_bytes))
        + host_bytes
        + struct.pack(">H", port)
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
    next_client_pub = body[offset : offset + PUBKEY_LEN]
    offset += PUBKEY_LEN
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
