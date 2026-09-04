"""Pure-Python regression tests for the wire format and layered
encryption. No subprocesses/sockets needed. These specifically guard
against a bug where an intermediate hop's peeled layer wasn't itself a
well-formed cell (it needs to be, so an intermediate hop can read
kind/packet_id to apply cover-drop without understanding the payload)."""
import asyncio
import struct

import pytest

from anontestlab.emulator import crypto_layer, wire
from anontestlab.emulator.circuit_client import pad_to_cell_size, unwrap_backward, wrap_layers


def test_pack_unpack_extend_roundtrip():
    body = wire.pack_extend("127.0.0.1", 54321, b"P" * 32, b"Q" * 8)
    host, port, pub, next_cid = wire.unpack_extend(body)
    assert (host, port, pub, next_cid) == ("127.0.0.1", 54321, b"P" * 32, b"Q" * 8)


@pytest.mark.parametrize("pubkey_len", [32, 56, 65])  # x25519, x448, p256 (uncompressed)
def test_pack_unpack_extend_roundtrip_at_every_curve_pubkey_length(pubkey_len):
    """The pubkey field is length-prefixed, not a fixed 32 bytes, since
    the curve is an experiment-wide config choice, not fixed at 32 bytes
    like x25519 alone would be."""
    body = wire.pack_extend("127.0.0.1", 54321, b"P" * pubkey_len, b"Q" * 8)
    host, port, pub, next_cid = wire.unpack_extend(body)
    assert (host, port, pub, next_cid) == ("127.0.0.1", 54321, b"P" * pubkey_len, b"Q" * 8)


def test_pack_unpack_data_roundtrip():
    body = wire.pack_data(wire.KIND_COVER, 7, b"payload-bytes")
    kind, packet_id, inner = wire.unpack_data(body)
    assert (kind, packet_id, inner) == (wire.KIND_COVER, 7, b"payload-bytes")


def test_frame_pack_read_roundtrip():
    async def _run():
        circuit_id = b"abcdefgh"
        frame = wire.pack_frame(wire.MSG_RELAY_FWD, circuit_id, b"body-bytes")
        reader = asyncio.StreamReader()
        reader.feed_data(frame)
        reader.feed_eof()
        return await wire.read_frame(reader)

    msg_type, cid, body = asyncio.run(_run())
    assert (msg_type, cid, body) == (wire.MSG_RELAY_FWD, b"abcdefgh", b"body-bytes")


@pytest.mark.parametrize(
    "algorithm",
    ["none", "aes128gcm", "aes256gcm", "aes256gcmsiv", "aes256ocb3", "chacha20poly1305"],
)
def test_seal_open_roundtrip(algorithm):
    from anontestlab.crypto import key_length

    key = b"k" * key_length(algorithm)
    sealed = crypto_layer.seal(algorithm, key, b"secret message", aad=b"circuit1")
    opened = crypto_layer.open_sealed(algorithm, key, sealed, aad=b"circuit1")
    assert opened == b"secret message"


@pytest.mark.parametrize("keyexchange", ["x25519", "x448", "p256"])
def test_ecdh_handshake_derives_matching_keys(keyexchange):
    priv_a, pub_a = crypto_layer.generate_ephemeral_keypair(keyexchange)
    priv_b, pub_b = crypto_layer.generate_ephemeral_keypair(keyexchange)
    fwd_a, back_a = crypto_layer.derive_key(priv_a, pub_b, "aes256gcm", keyexchange)
    fwd_b, back_b = crypto_layer.derive_key(priv_b, pub_a, "aes256gcm", keyexchange)
    assert fwd_a == fwd_b
    assert back_a == back_b
    assert len(fwd_a) == 32
    assert len(back_a) == 32


def test_forward_and_backward_keys_are_independent():
    """Reusing one key both directions would be a protocol weakness, not
    just a missed optimization: confirm they're genuinely different."""
    priv_a, pub_a = crypto_layer.generate_ephemeral_keypair()
    priv_b, pub_b = crypto_layer.generate_ephemeral_keypair()
    key_fwd, key_back = crypto_layer.derive_key(priv_a, pub_b, "aes256gcm")
    assert key_fwd != key_back


@pytest.mark.parametrize("algorithm,expected_len", [("aes128gcm", 16), ("aes256gcm", 32)])
def test_derive_key_length_matches_algorithm(algorithm, expected_len):
    priv_a, pub_a = crypto_layer.generate_ephemeral_keypair()
    priv_b, pub_b = crypto_layer.generate_ephemeral_keypair()
    key_fwd, key_back = crypto_layer.derive_key(priv_a, pub_b, algorithm)
    assert len(key_fwd) == expected_len
    assert len(key_back) == expected_len


def test_mismatched_keyexchange_between_peers_fails_or_mismatches():
    """Nothing in the wire format tells a peer which curve to use (it's a
    whole-experiment setting), so this is a configuration error to avoid,
    not something the protocol detects. Guard that it fails loudly (wrong
    key size for that curve) rather than silently deriving usable keys."""
    priv_a, pub_a = crypto_layer.generate_ephemeral_keypair("x25519")
    priv_b, pub_b = crypto_layer.generate_ephemeral_keypair("x448")
    with pytest.raises(ValueError):
        crypto_layer.derive_key(priv_a, pub_b, "aes256gcm", "x25519")


def test_wrap_layers_peels_correctly_through_intermediate_hops():
    """A 3-hop DATA cell: hop 1 and hop 2 must each see a forwardable
    pack_data cell (not opaque ciphertext) after peeling their own layer,
    and only hop 3 (the deepest) recovers the real payload. Each layer is
    bound to its own hop-local circuit ID, not one ID shared path-wide."""
    keys = [b"0" * 32, b"1" * 32, b"2" * 32]
    cids = [b"11111111", b"22222222", b"33333333"]
    payload = b"hello-world-payload"
    kind, packet_id = wire.KIND_REAL, 42
    target_cell = wire.pack_data(kind, packet_id, payload)

    sealed = wrap_layers(keys, cids, target_cell, "aes256gcm", kind, packet_id)

    layer1 = crypto_layer.open_sealed("aes256gcm", keys[0], sealed, aad=cids[0])
    assert wire.cell_type(layer1) == wire.CELL_DATA
    k1, pid1, inner1 = wire.unpack_data(layer1)
    assert (k1, pid1) == (kind, packet_id)

    layer2 = crypto_layer.open_sealed("aes256gcm", keys[1], inner1, aad=cids[1])
    assert wire.cell_type(layer2) == wire.CELL_DATA
    k2, pid2, inner2 = wire.unpack_data(layer2)
    assert (k2, pid2) == (kind, packet_id)

    layer3 = crypto_layer.open_sealed("aes256gcm", keys[2], inner2, aad=cids[2])
    assert layer3 == target_cell
    _k3, _pid3, payload3 = wire.unpack_data(layer3)
    assert payload3 == payload


def _seal_backward_through_hops(keys_back, cids, content, algorithm="aes256gcm"):
    """Mirrors relay_process.py::forward_downstream_to_upstream: the
    deepest hop seals first, then each hop closer to the client re-seals
    what it relays with its own backward key, so the hop nearest the
    client ends up outermost."""
    sealed = content
    for key, cid in reversed(list(zip(keys_back, cids))):
        sealed = crypto_layer.seal(algorithm, key, sealed, aad=cid)
    return sealed


def test_backward_layers_peel_correctly_through_intermediate_hops():
    """The return path mirrors the forward one: a confirmation from the
    deepest hop gets re-sealed by every hop on the way back, so it's
    actually encrypted on the wire (not forwarded in the clear), and
    unwrap_backward must peel it using the keys in forward hop order."""
    keys_back = [b"0" * 32, b"1" * 32, b"2" * 32]
    cids = [b"11111111", b"22222222", b"33333333"]
    confirmation = struct.pack(">Q", 42)

    sealed = _seal_backward_through_hops(keys_back, cids, confirmation)
    assert sealed != confirmation

    recovered = unwrap_backward(keys_back, cids, sealed, "aes256gcm")
    assert recovered == confirmation


def test_backward_layers_cannot_be_read_with_only_the_deepest_hops_key():
    """A relay that only knows its own key can't read a confirmation that
    picked up outer hops' re-encryption on the way back to the client,
    the same onion property the forward direction already has."""
    keys_back = [b"0" * 32, b"1" * 32, b"2" * 32]
    cids = [b"11111111", b"22222222", b"33333333"]
    sealed = _seal_backward_through_hops(keys_back, cids, struct.pack(">Q", 42))

    with pytest.raises(Exception):
        crypto_layer.open_sealed("aes256gcm", keys_back[2], sealed, aad=cids[2])


def test_wrap_layers_rejects_wrong_hop_local_circuit_id():
    """Opening a layer with the wrong (e.g. path-wide-shared) circuit ID
    as AAD must fail. This is what makes hop-local IDs actually binding
    rather than cosmetic."""
    keys = [b"0" * 32, b"1" * 32]
    cids = [b"11111111", b"22222222"]
    target_cell = wire.pack_data(wire.KIND_REAL, 1, b"payload")
    sealed = wrap_layers(keys, cids, target_cell, "aes256gcm", wire.KIND_REAL, 1)
    layer1 = crypto_layer.open_sealed("aes256gcm", keys[0], sealed, aad=cids[0])
    _kind, _pid, inner1 = wire.unpack_data(layer1)

    with pytest.raises(Exception):
        crypto_layer.open_sealed("aes256gcm", keys[1], inner1, aad=cids[0])  # wrong AAD


def test_wrap_layers_for_extend_through_an_established_hop():
    """Extending to a 3rd hop while hop 1<->hop 2 is already built: hop 1
    must see a forwardable cell, and only hop 2 (deepest so far) recovers
    the raw EXTEND instruction, including the next hop-local circuit ID."""
    keys = [b"0" * 32, b"1" * 32]  # 2 hops already established
    cids = [b"11111111", b"22222222"]
    extend_cell = wire.pack_extend("127.0.0.1", 9999, b"P" * 32, b"33333333")

    sealed = wrap_layers(keys, cids, extend_cell, "aes256gcm")

    layer1 = crypto_layer.open_sealed("aes256gcm", keys[0], sealed, aad=cids[0])
    assert wire.cell_type(layer1) == wire.CELL_DATA
    kind1, _pid1, inner1 = wire.unpack_data(layer1)
    assert kind1 == wire.KIND_CONTROL  # never mistaken for real traffic (cover-drop, watermark counting, ...)

    layer2 = crypto_layer.open_sealed("aes256gcm", keys[1], inner1, aad=cids[1])
    assert layer2 == extend_cell
    host, port, _pub, next_cid = wire.unpack_extend(layer2)
    assert (host, port, next_cid) == ("127.0.0.1", 9999, b"33333333")


def test_wrap_layers_single_hop_needs_no_intermediate_wrapping():
    keys = [b"0" * 32]
    cids = [b"11111111"]
    target_cell = wire.pack_data(wire.KIND_REAL, 1, b"payload")
    sealed = wrap_layers(keys, cids, target_cell, "aes256gcm", wire.KIND_REAL, 1)
    opened = crypto_layer.open_sealed("aes256gcm", keys[0], sealed, aad=cids[0])
    assert opened == target_cell


def _wire_size_at_hop1(cell, keys, cids, algorithm, kind=wire.KIND_REAL, packet_id=1):
    """What actually goes out on the wire from the client to hop 1."""
    return len(wrap_layers(keys, cids, cell, algorithm, kind, packet_id))


@pytest.mark.parametrize("algorithm", ["none", "aes256gcm", "chacha20poly1305"])
def test_fixed_cell_size_hides_real_payload_length(algorithm):
    """Two DATA cells with very different real payload sizes must produce
    the identical wire size once padded, which is the whole point."""
    keys = [b"0" * 32, b"1" * 32, b"2" * 32]
    cids = [b"1" * 8, b"2" * 8, b"3" * 8]
    cell_size = 512

    small = pad_to_cell_size(wire.pack_data(wire.KIND_REAL, 1, b"x"), cell_size, algorithm, len(keys))
    large = pad_to_cell_size(wire.pack_data(wire.KIND_REAL, 1, b"y" * 200), cell_size, algorithm, len(keys))

    assert _wire_size_at_hop1(small, keys, cids, algorithm) == cell_size
    assert _wire_size_at_hop1(large, keys, cids, algorithm) == cell_size


def test_fixed_cell_size_hides_extend_vs_data():
    """An EXTEND cell and a DATA cell at the same hop position, once
    padded, must be indistinguishable by wire size."""
    keys = [b"0" * 32]
    cids = [b"1" * 8]
    cell_size = 512
    algorithm = "aes256gcm"

    extend_cell = pad_to_cell_size(
        wire.pack_extend("127.0.0.1", 9999, b"P" * 32, b"Q" * 8), cell_size, algorithm, len(keys)
    )
    data_cell = pad_to_cell_size(
        wire.pack_data(wire.KIND_REAL, 1, b"payload"), cell_size, algorithm, len(keys)
    )

    assert _wire_size_at_hop1(extend_cell, keys, cids, algorithm) == cell_size
    assert _wire_size_at_hop1(data_cell, keys, cids, algorithm) == cell_size


def test_fixed_cell_size_shrinks_by_a_fixed_amount_per_hop():
    """Disclosed simplification: size is constant per hop *position*
    across circuits of the same length, not truly hop-invariant like
    Tor's non-expanding construction: it still decreases hop to hop."""
    keys = [b"0" * 32, b"1" * 32, b"2" * 32]
    cids = [b"1" * 8, b"2" * 8, b"3" * 8]
    algorithm = "aes256gcm"
    cell_size = 512
    overhead = wire.layer_overhead(algorithm)

    target_cell = pad_to_cell_size(wire.pack_data(wire.KIND_REAL, 1, b"x"), cell_size, algorithm, len(keys))
    sealed = wrap_layers(keys, cids, target_cell, algorithm, wire.KIND_REAL, 1)
    assert len(sealed) == cell_size  # what hop 1 receives

    layer1 = crypto_layer.open_sealed(algorithm, keys[0], sealed, aad=cids[0])
    _kind, _pid, inner1 = wire.unpack_data(layer1)
    assert len(inner1) == cell_size - overhead  # what hop 1 forwards to hop 2

    layer2 = crypto_layer.open_sealed(algorithm, keys[1], inner1, aad=cids[1])
    _kind, _pid, inner2 = wire.unpack_data(layer2)
    assert len(inner2) == cell_size - 2 * overhead  # what hop 2 forwards to hop 3


def test_pad_to_cell_size_rejects_oversized_content():
    with pytest.raises(ValueError):
        pad_to_cell_size(b"x" * 1000, 512, "aes256gcm", 3)


def test_read_frame_rejects_oversized_length():
    async def _run():
        reader = asyncio.StreamReader()
        reader.feed_data(struct.pack(">I", wire.MAX_FRAME_LEN + 1))
        reader.feed_eof()
        return await wire.read_frame(reader)

    with pytest.raises(wire.ProtocolError):
        asyncio.run(_run())


def test_read_frame_rejects_undersized_length():
    async def _run():
        reader = asyncio.StreamReader()
        reader.feed_data(struct.pack(">I", 3))
        reader.feed_eof()
        return await wire.read_frame(reader)

    with pytest.raises(wire.ProtocolError):
        asyncio.run(_run())
