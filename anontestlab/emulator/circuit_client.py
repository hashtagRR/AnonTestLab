"""Client side of the telescoping circuit protocol: build a circuit hop by
hop through the existing chain, then send onion-wrapped DATA cells."""
from __future__ import annotations

import asyncio
import os
import struct
from dataclasses import dataclass, field

from . import crypto_layer, wire


def wrap_layers(
    keys_in_order: list[bytes],
    circuit_ids_in_order: list[bytes],
    target_cell: bytes,
    algorithm: str,
    kind: int = wire.KIND_CONTROL,
    packet_id: int = 0,
) -> bytes:
    """Build the onion for a cell addressed to the *deepest* established
    hop (`target_cell`, a raw EXTEND or DATA cell, whatever that hop
    should act on directly).

    Every hop *above* the deepest one only ever forwards, so its layer
    must itself be a well-formed DATA cell (kind/packet_id + the next
    layer as `inner`) rather than opaque ciphertext, which is what lets an
    intermediate hop apply the cover-drop policy without needing to
    understand what it's forwarding. Only the innermost seal (for the
    deepest hop) carries the real target cell as-is.

    Each layer's AEAD is bound (as associated data) to the circuit ID
    that hop will actually see on its own connection (hop-local IDs, not
    one ID shared across the whole path), so `circuit_ids_in_order` must
    line up index-for-index with `keys_in_order`.
    """
    *intermediate, (last_key, last_cid) = zip(keys_in_order, circuit_ids_in_order)
    layer = crypto_layer.seal(algorithm, last_key, target_cell, aad=last_cid)
    for key, cid in reversed(intermediate):
        cell = wire.pack_data(kind, packet_id, layer)
        layer = crypto_layer.seal(algorithm, key, cell, aad=cid)
    return layer


def pad_to_cell_size(target_cell: bytes, cell_size: int, algorithm: str, hops_established: int) -> bytes:
    """Pad `target_cell` (the raw EXTEND or DATA cell for the deepest
    established hop, before any sealing) with random filler so that after
    `hops_established` layers of AEAD wrapping, the frame sent on the wire
    is exactly `cell_size` bytes, regardless of cell type or real content
    length, so an observer can't distinguish EXTEND from DATA, or real
    from cover, by size alone. Neither `unpack_data` nor `unpack_extend`
    validate total length, so no length-prefix/recovery is needed: nothing
    reads the filler back.

    Sizes still shrink by a fixed, predictable amount per hop (this isn't
    Tor's non-expanding CTR construction): same size at the same hop
    position for every circuit of that length, not truly hop-invariant.
    """
    target_len = cell_size - wire.layer_overhead(algorithm) * hops_established + wire.PACK_DATA_HEADER_LEN
    if len(target_cell) > target_len:
        raise ValueError(
            f"{len(target_cell)}-byte cell exceeds the {target_len}-byte budget for "
            f"cell_size={cell_size} at {hops_established} hop(s)"
        )
    return target_cell + os.urandom(target_len - len(target_cell))


@dataclass
class Circuit:
    circuit_id: bytes
    reader: asyncio.StreamReader
    writer: asyncio.StreamWriter
    keys: list[bytes]
    circuit_ids: list[bytes]
    algorithm: str
    path: list[tuple[str, int]]
    cell_size: int | None = None
    _next_id: int = field(default=1)

    async def send(self, kind: int, payload: bytes) -> int:
        packet_id = self._next_id
        self._next_id += 1
        target_cell = wire.pack_data(kind, packet_id, payload)
        if self.cell_size is not None:
            target_cell = pad_to_cell_size(target_cell, self.cell_size, self.algorithm, len(self.keys))
        sealed = wrap_layers(self.keys, self.circuit_ids, target_cell, self.algorithm, kind, packet_id)
        self.writer.write(wire.pack_frame(wire.MSG_RELAY_FWD, self.circuit_id, sealed))
        await self.writer.drain()
        return packet_id

    async def recv_delivery(self) -> int:
        msg_type, _cid, body = await wire.read_frame(self.reader)
        if msg_type != wire.MSG_RELAY_BACK:
            raise wire.ProtocolError(f"expected RELAY_BACK, got msg_type={msg_type}")
        (packet_id,) = struct.unpack(">Q", body)
        return packet_id

    async def close(self) -> None:
        self.writer.close()


async def build_circuit(path: list[tuple[str, int]], algorithm: str, cell_size: int | None = None) -> Circuit:
    circuit_id = os.urandom(wire.CIRCUIT_ID_LEN)
    reader, writer = await asyncio.open_connection(*path[0])

    priv1, pub1 = crypto_layer.generate_ephemeral_keypair()
    writer.write(wire.pack_frame(wire.MSG_HELLO, circuit_id, pub1))
    await writer.drain()
    msg_type, _cid, body = await wire.read_frame(reader)
    if msg_type != wire.MSG_HELLO_REPLY:
        raise wire.ProtocolError(f"expected HELLO_REPLY, got msg_type={msg_type}")
    keys = [crypto_layer.derive_key(priv1, body)]
    circuit_ids = [circuit_id]

    for host, port in path[1:]:
        priv_i, pub_i = crypto_layer.generate_ephemeral_keypair()
        # A fresh ID for the *next* hop-link. The previous hop uses this on
        # its own connection to this hop, so no circuit ID is shared by two
        # links along the path.
        next_circuit_id = os.urandom(wire.CIRCUIT_ID_LEN)
        plaintext = wire.pack_extend(host, port, pub_i, next_circuit_id)
        if cell_size is not None:
            plaintext = pad_to_cell_size(plaintext, cell_size, algorithm, len(keys))
        sealed = wrap_layers(keys, circuit_ids, plaintext, algorithm)
        writer.write(wire.pack_frame(wire.MSG_RELAY_FWD, circuit_id, sealed))
        await writer.drain()
        msg_type, _cid, body = await wire.read_frame(reader)
        if msg_type != wire.MSG_RELAY_BACK:
            raise wire.ProtocolError(f"expected RELAY_BACK (EXTENDED reply), got msg_type={msg_type}")
        keys.append(crypto_layer.derive_key(priv_i, body))
        circuit_ids.append(next_circuit_id)

    return Circuit(
        circuit_id=circuit_id,
        reader=reader,
        writer=writer,
        keys=keys,
        circuit_ids=circuit_ids,
        algorithm=algorithm,
        path=path,
        cell_size=cell_size,
    )
