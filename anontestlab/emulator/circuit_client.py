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


def unwrap_backward(
    keys_in_order: list[bytes], circuit_ids_in_order: list[bytes], sealed: bytes, algorithm: str
) -> bytes:
    """Peel the return-path layers a RELAY_BACK message picked up as it
    traveled from wherever it originated back to the client. Each hop
    re-seals whatever it forwards upstream with its own backward key
    (see relay_process.py::forward_downstream_to_upstream), so the hop
    closest to the client seals last, making its layer the outermost:
    this peels using keys_in_order/circuit_ids_in_order in the same
    forward order used to build the circuit (hop 1 first), the mirror of
    wrap_layers building outermost-to-innermost in reverse order for the
    forward direction. Pass only the keys established so far (not the
    full circuit) when unwrapping an EXTENDED reply mid-build, since
    fewer hops have had a chance to add their own layer at that point.
    """
    layer = sealed
    for key, cid in zip(keys_in_order, circuit_ids_in_order):
        layer = crypto_layer.open_sealed(algorithm, key, layer, aad=cid)
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
    keys_fwd: list[bytes]
    keys_back: list[bytes]
    circuit_ids: list[bytes]
    algorithm: str
    path: list[tuple[str, int]]
    cell_size: int | None = None
    _next_id: int = field(default=1)

    async def _send_cell(self, kind: int, packet_id: int, chunk: bytes) -> None:
        target_cell = wire.pack_data(kind, packet_id, chunk)
        if self.cell_size is not None:
            target_cell = pad_to_cell_size(target_cell, self.cell_size, self.algorithm, len(self.keys_fwd))
        sealed = wrap_layers(self.keys_fwd, self.circuit_ids, target_cell, self.algorithm, kind, packet_id)
        self.writer.write(wire.pack_frame(wire.MSG_RELAY_FWD, self.circuit_id, sealed))
        await self.writer.drain()

    async def send(self, kind: int, payload: bytes) -> int:
        """Sends `payload` as one cell, or, if it doesn't fit the fixed
        cell_size budget, splits it across multiple cells (fragmented
        the same way regardless of why it didn't fit: a payload larger
        than the budget, or a cell_size just too tight). All fragments
        share this one packet_id; only the last is sent with the real
        `kind` (KIND_REAL becomes KIND_REAL_FRAGMENT for every fragment
        before it, so the terminal hop knows not to confirm early, see
        relay_process.py::process_relay_fwd). cover payloads never need
        the distinction: nothing confirms cover traffic either way, so
        every fragment can just stay KIND_COVER.
        """
        packet_id = self._next_id
        self._next_id += 1

        if self.cell_size is None:
            await self._send_cell(kind, packet_id, payload)
            return packet_id

        max_chunk = self.cell_size - wire.layer_overhead(self.algorithm) * len(self.keys_fwd)
        if max_chunk <= 0:
            raise ValueError(
                f"cell_size={self.cell_size} is too small to fit even an empty cell at "
                f"{len(self.keys_fwd)} hop(s) with {self.algorithm}"
            )

        chunks = [payload[i : i + max_chunk] for i in range(0, len(payload), max_chunk)] or [b""]
        fragment_kind = wire.KIND_REAL_FRAGMENT if kind == wire.KIND_REAL else kind
        for chunk in chunks[:-1]:
            await self._send_cell(fragment_kind, packet_id, chunk)
        await self._send_cell(kind, packet_id, chunks[-1])
        return packet_id

    async def recv_delivery(self) -> int:
        msg_type, _cid, body = await wire.read_frame(self.reader)
        if msg_type != wire.MSG_RELAY_BACK:
            raise wire.ProtocolError(f"expected RELAY_BACK, got msg_type={msg_type}")
        plaintext = unwrap_backward(self.keys_back, self.circuit_ids, body, self.algorithm)
        (packet_id,) = struct.unpack(">Q", plaintext)
        return packet_id

    async def close(self) -> None:
        self.writer.close()


async def build_circuit(
    path: list[tuple[str, int]],
    algorithm: str,
    cell_size: int | None = None,
    keyexchange: str = "x25519",
) -> Circuit:
    circuit_id = os.urandom(wire.CIRCUIT_ID_LEN)
    reader, writer = await asyncio.open_connection(*path[0])

    priv1, pub1 = crypto_layer.generate_ephemeral_keypair(keyexchange)
    writer.write(wire.pack_frame(wire.MSG_HELLO, circuit_id, pub1))
    await writer.drain()
    msg_type, _cid, body = await wire.read_frame_timeout(reader, "HELLO_REPLY")
    if msg_type != wire.MSG_HELLO_REPLY:
        raise wire.ProtocolError(f"expected HELLO_REPLY, got msg_type={msg_type}")
    key_fwd1, key_back1 = crypto_layer.derive_key(priv1, body, algorithm, keyexchange)
    keys_fwd = [key_fwd1]
    keys_back = [key_back1]
    circuit_ids = [circuit_id]

    for host, port in path[1:]:
        priv_i, pub_i = crypto_layer.generate_ephemeral_keypair(keyexchange)
        # A fresh ID for the *next* hop-link. The previous hop uses this on
        # its own connection to this hop, so no circuit ID is shared by two
        # links along the path.
        next_circuit_id = os.urandom(wire.CIRCUIT_ID_LEN)
        plaintext = wire.pack_extend(host, port, pub_i, next_circuit_id)
        if cell_size is not None:
            plaintext = pad_to_cell_size(plaintext, cell_size, algorithm, len(keys_fwd))
        sealed = wrap_layers(keys_fwd, circuit_ids, plaintext, algorithm)
        writer.write(wire.pack_frame(wire.MSG_RELAY_FWD, circuit_id, sealed))
        await writer.drain()
        msg_type, _cid, reply_body = await wire.read_frame_timeout(reader, "RELAY_BACK (EXTENDED reply)")
        if msg_type != wire.MSG_RELAY_BACK:
            raise wire.ProtocolError(f"expected RELAY_BACK (EXTENDED reply), got msg_type={msg_type}")
        # Only the hops established so far had a chance to add their own
        # backward layer to this reply, so unwrap with keys_back as it
        # stands right now, not the full (not-yet-complete) circuit.
        server_pub = unwrap_backward(keys_back, circuit_ids, reply_body, algorithm)
        key_fwd_i, key_back_i = crypto_layer.derive_key(priv_i, server_pub, algorithm, keyexchange)
        keys_fwd.append(key_fwd_i)
        keys_back.append(key_back_i)
        circuit_ids.append(next_circuit_id)

    return Circuit(
        circuit_id=circuit_id,
        reader=reader,
        writer=writer,
        keys_fwd=keys_fwd,
        keys_back=keys_back,
        circuit_ids=circuit_ids,
        algorithm=algorithm,
        path=path,
        cell_size=cell_size,
    )
