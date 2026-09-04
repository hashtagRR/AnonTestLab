"""Selectable AEAD algorithms for the per-hop encryption layer.

Real per-hop symmetric encryption, not a modeled cost. `none` is a
plaintext passthrough (still real framing/transport, useful for isolating
transport cost from crypto cost in benchmarks).
"""
from __future__ import annotations

from cryptography.hazmat.primitives.ciphers.aead import AESGCM, ChaCha20Poly1305

NONCE_LEN = 12


class _NoAEAD:
    """Passthrough "cipher": no confidentiality, fixed-format for symmetry
    with real AEADs so the wire/relay code doesn't need a special case."""

    def encrypt(self, nonce: bytes, data: bytes, aad: bytes | None) -> bytes:
        return data

    def decrypt(self, nonce: bytes, data: bytes, aad: bytes | None) -> bytes:
        return data


ALGORITHMS = {
    "none": _NoAEAD,
    "aes256gcm": AESGCM,
    "chacha20poly1305": ChaCha20Poly1305,
}


def new_cipher(algorithm: str, key: bytes):
    try:
        cls = ALGORITHMS[algorithm]
    except KeyError:
        raise ValueError(
            f"unknown crypto algorithm '{algorithm}', available: {sorted(ALGORITHMS)}"
        ) from None
    if algorithm == "none":
        return cls()
    return cls(key)
