"""Per-hop key agreement and AEAD sealing.

ECDHE per hop (fresh ephemeral keys each circuit build, no long-term
relay identity, so there's no directory/PKI question to answer for
v0.1), HKDF-SHA256 to derive independent forward/backward symmetric keys
from the same shared secret, then the chosen AEAD (anontestlab.crypto)
seals both the forward EXTEND/DATA cells and the return-path RELAY_BACK
confirmations, each hop re-encrypting what it forwards in its own
direction's key (see circuit_client.py::unwrap_backward).

x25519 (Curve25519) is the default curve; x448 (RFC 7748, larger keys,
higher security margin) and p256 (NIST secp256r1, for interop-focused
comparisons) are also selectable. The keyexchange choice is a whole-
experiment setting, not negotiated per hop, so every relay in a circuit
must agree on it (threaded through RelayState/build_circuit, not
inferred from the wire: see wire.py::pack_extend's length-prefixed
pubkey field for how the wire format stays curve-agnostic).
"""
from __future__ import annotations

import os
from typing import Union

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.asymmetric.x448 import X448PrivateKey, X448PublicKey
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from ..crypto import NONCE_LEN, key_length, new_cipher

HKDF_INFO_FWD = b"anontestlab-hop-key-fwd-v1"
HKDF_INFO_BACK = b"anontestlab-hop-key-back-v1"

# Union[...], not X | Y | Z: this is a real runtime assignment, not an
# annotation, so it isn't covered by `from __future__ import annotations`
# and must work on the project's Python 3.9 floor, where the `|` union
# operator between type objects doesn't exist yet (added in 3.10).
EphemeralPrivateKey = Union[X25519PrivateKey, X448PrivateKey, ec.EllipticCurvePrivateKey]

KEYEXCHANGES = ("x25519", "x448", "p256")


def generate_ephemeral_keypair(keyexchange: str = "x25519") -> tuple[EphemeralPrivateKey, bytes]:
    if keyexchange == "x25519":
        priv = X25519PrivateKey.generate()
        return priv, priv.public_key().public_bytes_raw()
    if keyexchange == "x448":
        priv = X448PrivateKey.generate()
        return priv, priv.public_key().public_bytes_raw()
    if keyexchange == "p256":
        priv = ec.generate_private_key(ec.SECP256R1())
        pub_bytes = priv.public_key().public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
        return priv, pub_bytes
    raise ValueError(f"unknown key exchange '{keyexchange}', available: {KEYEXCHANGES}")


def derive_key(
    priv: EphemeralPrivateKey, peer_pub_bytes: bytes, algorithm: str, keyexchange: str = "x25519"
) -> tuple[bytes, bytes]:
    """Returns (key_fwd, key_back): independent keys for the two
    directions, both derived from the same ECDH shared secret via HKDF
    with different info strings. Separate directional keys (rather than
    reusing one key both ways) is standard protocol hygiene, matching how
    Tor itself derives distinct forward/backward key material from a
    single handshake."""
    if keyexchange == "x25519":
        shared_secret = priv.exchange(X25519PublicKey.from_public_bytes(peer_pub_bytes))
    elif keyexchange == "x448":
        shared_secret = priv.exchange(X448PublicKey.from_public_bytes(peer_pub_bytes))
    elif keyexchange == "p256":
        peer_pub = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), peer_pub_bytes)
        shared_secret = priv.exchange(ec.ECDH(), peer_pub)
    else:
        raise ValueError(f"unknown key exchange '{keyexchange}', available: {KEYEXCHANGES}")
    length = key_length(algorithm)
    key_fwd = HKDF(algorithm=hashes.SHA256(), length=length, salt=None, info=HKDF_INFO_FWD).derive(
        shared_secret
    )
    key_back = HKDF(algorithm=hashes.SHA256(), length=length, salt=None, info=HKDF_INFO_BACK).derive(
        shared_secret
    )
    return key_fwd, key_back


def seal(algorithm: str, key: bytes, plaintext: bytes, aad: bytes = b"") -> bytes:
    nonce = os.urandom(NONCE_LEN)
    cipher = new_cipher(algorithm, key)
    ciphertext = cipher.encrypt(nonce, plaintext, aad)
    return nonce + ciphertext


def open_sealed(algorithm: str, key: bytes, sealed: bytes, aad: bytes = b"") -> bytes:
    nonce, ciphertext = sealed[:NONCE_LEN], sealed[NONCE_LEN:]
    cipher = new_cipher(algorithm, key)
    return cipher.decrypt(nonce, ciphertext, aad)
