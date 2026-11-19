"""NIP-01 canonical event builder and BIP-340 Schnorr signer.

Tier 1 (``did:web`` / managed) accounts have no local ``iyou_home`` enclave to
sign with, so WUN holds a secp256k1 key on their behalf.  This module contains
the pure-Python curve arithmetic needed to produce and verify BIP-340 Schnorr
signatures over secp256k1 (the scheme Nostr uses for kind 1/1111 events).

The implementation follows the BIP-340 reference algorithm exactly:

* ``tagged_hash(tag, msg) = SHA256(SHA256(tag) || SHA256(tag) || msg)``
* secret is negated when the corresponding curve point has odd Y, so every
  x-only public key has an even-Y representative
* nonce is derived from ``aux_rand || secret || pubkey_x || msg`` and negated
  when ``R.y`` is odd
* signature is ``R.x || (k + e*d) mod n``

No third-party secp256k1 binding is required: ``coincurve`` and ``secp256k1``
are not installed in this project, but ``cryptography`` is available for
Fernet at-rest encryption of the custodial secret (see ``custodial_keys.py``).
"""

import hashlib
import json
import os
import re

# secp256k1 domain parameters (BIP-340 uses the x-only coordinate).
P = 2**256 - 2**32 - 977
N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
G_X = 0x79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798
G_Y = 0x483ADA7726A3C4655DA4FBFC0E1108A8FD17B448A68554199C47D08FFB10D4B8
G = (G_X, G_Y)

_HEX64 = re.compile(r"^[0-9a-fA-F]{64}$")
_HEX128 = re.compile(r"^[0-9a-fA-F]{128}$")


def is_valid_hex32(value):
    """True for a 32-byte value encoded as 64 hex characters."""
    return isinstance(value, str) and bool(_HEX64.fullmatch(value))


def is_valid_hex64(value):
    """True for a 64-byte value (e.g. a BIP-340 signature) as 128 hex chars."""
    return isinstance(value, str) and bool(_HEX128.fullmatch(value))


# ---------- Minimal Jacobian secp256k1 arithmetic ----------

_INF = (0, 1, 0)  # Jacobian Z == 0 represents the point at infinity.


def _jacobian_double(point):
    x, y, z = point
    if z == 0 or y == 0:
        return _INF
    yy = (y * y) % P
    s = (4 * x * yy) % P
    m = (3 * x * x) % P
    x3 = (m * m - 2 * s) % P
    y3 = (m * (s - x3) - 8 * yy * yy) % P
    z3 = (2 * y * z) % P
    return (x3, y3, z3)


def _jacobian_add(p1, p2):
    x1, y1, z1 = p1
    x2, y2, z2 = p2
    if z1 == 0:
        return p2
    if z2 == 0:
        return p1
    z1z1 = (z1 * z1) % P
    z2z2 = (z2 * z2) % P
    u1 = (x1 * z2z2) % P
    u2 = (x2 * z1z1) % P
    s1 = (y1 * z2 * z2z2) % P
    s2 = (y2 * z1 * z1z1) % P
    if u1 == u2:
        if s1 != s2:
            return _INF
        return _jacobian_double(p1)
    h = (u2 - u1) % P
    i = (2 * h) ** 2 % P
    j = (h * i) % P
    r = (2 * (s2 - s1)) % P
    v = (u1 * i) % P
    x3 = (r * r - j - 2 * v) % P
    y3 = (r * (v - x3) - 2 * s1 * j) % P
    z3 = (((z1 + z2) ** 2 - z1z1 - z2z2) * h) % P
    return (x3, y3, z3)


def _jacobian_mul(scalar, point):
    result = _INF
    addend = (point[0], point[1], 1) if len(point) == 2 else point
    scalar %= N
    while scalar:
        if scalar & 1:
            result = _jacobian_add(result, addend)
        addend = _jacobian_double(addend)
        scalar >>= 1
    return result


def _to_affine(point):
    x, y, z = point
    if z == 0:
        return None
    inv_z = pow(z, P - 2, P)
    inv_z2 = (inv_z * inv_z) % P
    return ((x * inv_z2) % P, (y * inv_z2 * inv_z) % P)


def _g_mul(scalar):
    return _jacobian_mul(scalar, G)


def _lift_x(x_int):
    """Lift an x-only coordinate to the even-Y curve point (BIP-340)."""
    if x_int >= P:
        raise ValueError("x coordinate outside secp256k1 field")
    alpha = (x_int * x_int * x_int + 7) % P
    y = pow(alpha, (P + 1) // 4, P)
    if (y * y) % P != alpha:
        raise ValueError("x coordinate is not on secp256k1")
    if y % 2:
        y = P - y
    return (x_int, y)


def tagged_hash(tag, message):
    tag_hash = hashlib.sha256(tag.encode("utf-8")).digest()
    return hashlib.sha256(tag_hash + tag_hash + message).digest()


# ---------- Key handling ----------

def generate_secret():
    """Return a uniformly random, valid 32-byte secp256k1 secret as hex."""
    while True:
        candidate = int.from_bytes(os.urandom(32), "big")
        if 1 <= candidate < N:
            return candidate.to_bytes(32, "big").hex()


def pubkey_from_secret(secret_hex):
    """Return the x-only (64-hex) BIP-340 public key for a secret."""
    if not is_valid_hex32(secret_hex):
        raise ValueError("secret must be 32-byte hex")
    secret = int(secret_hex, 16)
    if not 1 <= secret < N:
        raise ValueError("secret outside secp256k1 order")
    point = _to_affine(_g_mul(secret))
    return point[0].to_bytes(32, "big").hex()


def _signing_secret(secret_hex, pubkey_hex):
    """Negate d when P.y is odd so the x-only key stays consistent.

    The square-root lift returns an arbitrary one of the two Y roots, so the
    parity must be read from the actual scalar multiplication of d*G, not from
    the unnormalised root.
    """
    if pubkey_from_secret(secret_hex).lower() != pubkey_hex.lower():
        raise ValueError("secret does not match public key")
    secret = int(secret_hex, 16)
    point = _to_affine(_g_mul(secret))
    if point[1] % 2:
        secret = N - secret
    return secret


# ---------- NIP-01 canonical serialization ----------

def serialize_event(pubkey_hex, created_at, kind, tags, content):
    """Canonical NIP-01 JSON payload: [0, pubkey, created_at, kind, tags, content]."""
    payload = [0, str(pubkey_hex).lower(), int(created_at), int(kind), tags, content]
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def event_id_bytes(pubkey_hex, created_at, kind, tags, content):
    return hashlib.sha256(
        serialize_event(pubkey_hex, created_at, kind, tags, content)
    ).digest()


# ---------- BIP-340 sign / verify ----------

def schnorr_sign(message32, secret_hex, aux_rand=None):
    """Sign a 32-byte message with BIP-340; return the 64-byte signature."""
    if len(message32) != 32:
        raise ValueError("message must be exactly 32 bytes")
    pubkey_hex = pubkey_from_secret(secret_hex)
    if aux_rand is None:
        aux_rand = os.urandom(32)
    if len(aux_rand) != 32:
        raise ValueError("aux_rand must be exactly 32 bytes")

    secret = _signing_secret(secret_hex, pubkey_hex)
    aux = int.from_bytes(tagged_hash("BIP0340/aux", aux_rand), "big")
    t_bytes = (secret ^ aux).to_bytes(32, "big")
    pubkey_bytes = bytes.fromhex(pubkey_hex)

    nonce = int.from_bytes(
        tagged_hash("BIP0340/nonce", t_bytes + pubkey_bytes + message32), "big"
    ) % N
    if nonce == 0:
        raise ValueError("invalid BIP-340 nonce")

    big_r = _to_affine(_g_mul(nonce))
    if big_r[1] % 2:
        nonce = N - nonce

    r_bytes = big_r[0].to_bytes(32, "big")
    challenge = int.from_bytes(
        tagged_hash("BIP0340/challenge", r_bytes + pubkey_bytes + message32), "big"
    ) % N
    signature_scalar = (nonce + challenge * secret) % N
    return r_bytes + signature_scalar.to_bytes(32, "big")


def schnorr_verify(signature_hex, message32, pubkey_hex):
    """Verify a 64-hex BIP-340 signature over a 32-byte message."""
    try:
        if not is_valid_hex64(signature_hex) or not is_valid_hex32(pubkey_hex):
            return False
        if len(message32) != 32:
            return False
        sig = bytes.fromhex(signature_hex)
        r_int = int.from_bytes(sig[:32], "big")
        s_int = int.from_bytes(sig[32:], "big")
        if s_int >= N:
            return False
        big_r = _lift_x(r_int)
        pubkey_bytes = bytes.fromhex(pubkey_hex)
        challenge = int.from_bytes(
            tagged_hash("BIP0340/challenge", sig[:32] + pubkey_bytes + message32), "big"
        ) % N
        point_p = _lift_x(int(pubkey_hex, 16))
        left = _to_affine(_g_mul(s_int))
        right = _to_affine(
            _jacobian_add(
                (big_r[0], big_r[1], 1),
                _jacobian_mul(challenge, point_p),
            )
        )
        return bool(left and right and left[0] == right[0] and left[1] == right[1])
    except (ValueError, OverflowError):
        return False


def sign_event(unsigned_event, secret_hex, aux_rand=None):
    """Build, hash, sign and self-verify a Nostr event. Returns the signed dict.

    ``unsigned_event`` must contain ``created_at``, ``kind``, ``tags`` and
    ``content``. ``pubkey`` is overwritten with the signer's x-only key.
    """
    pubkey_hex = pubkey_from_secret(secret_hex)
    created_at = int(unsigned_event["created_at"])
    kind = int(unsigned_event["kind"])
    tags = unsigned_event.get("tags") or []
    content = unsigned_event.get("content") or ""

    message = event_id_bytes(pubkey_hex, created_at, kind, tags, content)
    signature = schnorr_sign(message, secret_hex, aux_rand=aux_rand)
    signed = {
        "id": message.hex(),
        "pubkey": pubkey_hex,
        "created_at": created_at,
        "kind": kind,
        "tags": tags,
        "content": content,
        "sig": signature.hex(),
    }
    if not verify_event(signed):
        raise ValueError("generated BIP-340 signature failed self-verification")
    return signed


def verify_event(event):
    """Verify both the NIP-01 id and the BIP-340 signature of a signed event."""
    try:
        pubkey_hex = str(event.get("pubkey") or "").lower()
        signature_hex = str(event.get("sig") or "").lower()
        expected_id = event_id_bytes(
            pubkey_hex,
            event["created_at"],
            event["kind"],
            event.get("tags") or [],
            event.get("content") or "",
        )
        if expected_id.hex() != str(event.get("id") or "").lower():
            return False
        return schnorr_verify(signature_hex, expected_id, pubkey_hex)
    except (KeyError, TypeError, ValueError):
        return False
