"""Per-hop key agreement and AEAD sealing.

X25519 ECDHE per hop (fresh ephemeral keys each circuit build, no long-
term relay identity, so there's no directory/PKI question to answer for
v0.1), HKDF-SHA256 to derive a symmetric key, then the chosen AEAD
(anontestlab.crypto) for both the EXTEND control cells and DATA cells.
"""
from __future__ import annotations

import os

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from ..crypto import NONCE_LEN, new_cipher

HKDF_INFO = b"anontestlab-hop-key-v1"


def generate_ephemeral_keypair() -> tuple[X25519PrivateKey, bytes]:
    priv = X25519PrivateKey.generate()
    pub_bytes = priv.public_key().public_bytes_raw()
    return priv, pub_bytes


def derive_key(priv: X25519PrivateKey, peer_pub_bytes: bytes) -> bytes:
    shared_secret = priv.exchange(X25519PublicKey.from_public_bytes(peer_pub_bytes))
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=HKDF_INFO).derive(shared_secret)


def seal(algorithm: str, key: bytes, plaintext: bytes, aad: bytes = b"") -> bytes:
    nonce = os.urandom(NONCE_LEN)
    cipher = new_cipher(algorithm, key)
    ciphertext = cipher.encrypt(nonce, plaintext, aad)
    return nonce + ciphertext


def open_sealed(algorithm: str, key: bytes, sealed: bytes, aad: bytes = b"") -> bytes:
    nonce, ciphertext = sealed[:NONCE_LEN], sealed[NONCE_LEN:]
    cipher = new_cipher(algorithm, key)
    return cipher.decrypt(nonce, ciphertext, aad)
