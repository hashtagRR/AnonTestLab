"""Selectable AEAD algorithms for the per-hop encryption layer.

Real per-hop symmetric encryption, not a modeled cost. `none` is a
plaintext passthrough (still real framing/transport, useful for isolating
transport cost from crypto cost in benchmarks).
"""
from __future__ import annotations

from cryptography.hazmat.primitives.ciphers.aead import AESGCM, AESGCMSIV, AESOCB3, ChaCha20Poly1305

NONCE_LEN = 12


class _NoAEAD:
    """Passthrough "cipher": no confidentiality, fixed-format for symmetry
    with real AEADs so the wire/relay code doesn't need a special case."""

    def encrypt(self, nonce: bytes, data: bytes, aad: bytes | None) -> bytes:
        return data

    def decrypt(self, nonce: bytes, data: bytes, aad: bytes | None) -> bytes:
        return data


# AESGCM/AESGCMSIV/AESOCB3 all key off the byte length passed to their
# constructor (16/24/32 -> 128/192/256-bit), so aes128gcm and aes256gcm
# share a class; KEY_LENGTHS is what tells derive_key how many bytes to
# actually produce for each name.
ALGORITHMS = {
    "none": _NoAEAD,
    "aes128gcm": AESGCM,
    "aes256gcm": AESGCM,
    "aes256gcmsiv": AESGCMSIV,  # nonce-misuse resistant variant of GCM
    "aes256ocb3": AESOCB3,  # faster construction, needs OpenSSL with OCB support
    "chacha20poly1305": ChaCha20Poly1305,
}

KEY_LENGTHS = {
    "none": 32,  # unused by _NoAEAD, kept nonzero only so HKDF has a valid length to derive
    "aes128gcm": 16,
    "aes256gcm": 32,
    "aes256gcmsiv": 32,
    "aes256ocb3": 32,
    "chacha20poly1305": 32,
}


def key_length(algorithm: str) -> int:
    try:
        return KEY_LENGTHS[algorithm]
    except KeyError:
        raise ValueError(
            f"unknown crypto algorithm '{algorithm}', available: {sorted(ALGORITHMS)}"
        ) from None


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
