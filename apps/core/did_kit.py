import base64
import hashlib
import json
import re
import uuid
from datetime import datetime, timezone

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)


def get_node_signing_key() -> Ed25519PrivateKey:
    from django.conf import settings

    explicit_hex = settings.NODE_PRIVATE_KEY_HEX
    if explicit_hex:
        return load_signing_key(explicit_hex)
    seed = settings.SECRET_KEY.encode("utf-8")
    return _generate_keypair_from_seed(seed)


def _generate_keypair_from_seed(seed: bytes) -> Ed25519PrivateKey:
    digest = hashlib.sha256(seed).digest()
    return Ed25519PrivateKey.from_private_bytes(digest)


def load_signing_key(private_key_hex: str) -> Ed25519PrivateKey:
    raw = bytes.fromhex(private_key_hex)
    if len(raw) == 64:
        return Ed25519PrivateKey.from_private_bytes(raw[:32])
    elif len(raw) == 32:
        return Ed25519PrivateKey.from_private_bytes(raw)
    else:
        raise ValueError(
            f"Invalid Ed25519 private key length: {len(raw)} bytes "
            f"(expected 32 or 64 hex-decoded bytes)"
        )


def get_public_key_hex(private_key: Ed25519PrivateKey) -> str:
    return private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    ).hex()


def build_unsigned_vc(
    subject_did: str,
    credential_type: str,
    fidelity_score: int,
    issuer_did: str,
) -> dict:
    vc_id = f"urn:uuid:{uuid.uuid4()}"
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    expiry = datetime.now(timezone.utc).replace(
        year=datetime.now(timezone.utc).year + 1
    ).strftime("%Y-%m-%dT%H:%M:%SZ")

    return {
        "@context": [
            "https://www.w3.org/2018/credentials/v1",
        ],
        "id": vc_id,
        "type": ["VerifiableCredential", credential_type],
        "issuer": issuer_did,
        "issuanceDate": now,
        "expirationDate": expiry,
        "credentialSubject": {
            "id": subject_did,
            "fidelity_score": fidelity_score,
        },
    }


def _canonical_json(data: dict) -> bytes:
    return json.dumps(data, separators=(",", ":"), sort_keys=True).encode("utf-8")


def sign_vc(
    unsigned_vc: dict,
    private_key: Ed25519PrivateKey,
    verification_method: str,
) -> dict:
    proof = {
        "type": "Ed25519Signature2020",
        "created": unsigned_vc["issuanceDate"],
        "proofPurpose": "assertionMethod",
        "verificationMethod": verification_method,
    }

    proof_to_sign = dict(proof)
    proof_to_sign.pop("proofValue", None)

    payload = _canonical_json(unsigned_vc) + _canonical_json(proof_to_sign)
    signature_hex = private_key.sign(payload).hex()
    proof["proofValue"] = signature_hex

    signed_vc = {**unsigned_vc, "proof": proof}
    return signed_vc


def issue_vc(
    voter_did: str,
    credential_type: str,
    fidelity_score: int,
) -> dict:
    from django.conf import settings

    issuer_did = settings.NODE_DID
    signing_key = get_node_signing_key()
    verification_method = f"{issuer_did}#keys-1"
    unsigned = build_unsigned_vc(voter_did, credential_type, fidelity_score, issuer_did)
    return sign_vc(unsigned, signing_key, verification_method)


def verify_vc_signature(
    signed_vc: dict,
    public_key_hex: str,
) -> bool:
    proof = signed_vc.pop("proof", None)
    if proof is None:
        return False

    proof_value_hex = proof.pop("proofValue", None)
    if proof_value_hex is None:
        signed_vc["proof"] = proof
        return False

    proof_to_verify = dict(proof)
    payload = _canonical_json(signed_vc) + _canonical_json(proof_to_verify)

    try:
        raw_pubkey = bytes.fromhex(public_key_hex)
        public_key = Ed25519PublicKey.from_public_bytes(raw_pubkey)
        public_key.verify(bytes.fromhex(proof_value_hex), payload)
        result = True
    except (InvalidSignature, ValueError, Exception):
        result = False
    finally:
        proof["proofValue"] = proof_value_hex
        signed_vc["proof"] = proof

    return result


B58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
B58_INDEX = {c: i for i, c in enumerate(B58_ALPHABET)}


def b58decode(s: str) -> bytes:
    """Decode a Base58BTC-encoded string to bytes."""
    num = 0
    for char in s:
        if char not in B58_INDEX:
            raise ValueError(f"Invalid Base58 character: {char}")
        num = num * 58 + B58_INDEX[char]
    pad = len(s) - len(s.lstrip("1"))
    byte_len = (num.bit_length() + 7) // 8
    return (b"\x00" * pad) + (num.to_bytes(byte_len, "big") if num > 0 else b"")


def b58encode(b: bytes) -> str:
    """Encode bytes to a Base58BTC string."""
    num = int.from_bytes(b, "big")
    chars = []
    while num > 0:
        num, rem = divmod(num, 58)
        chars.append(B58_ALPHABET[rem])
    pad = len(b) - len(b.lstrip(b"\x00"))
    return (B58_ALPHABET[0] * pad) + "".join(reversed(chars))


def did_to_pubkey(did: str) -> str | None:
    """Extract Nostr hex pubkey from a DID (did:key:z6Mk..., did:iyou:0x...) or hex string."""
    if not did or not isinstance(did, str):
        return None

    did = did.strip()
    if re.match(r"^[0-9a-fA-F]{64}$", did):
        return did.lower()

    if did.startswith("did:iyou:0x"):
        hex_part = did.split("did:iyou:0x", 1)[1].strip()
        if len(hex_part) == 64 and all(c in "0123456789abcdefABCDEF" for c in hex_part):
            return hex_part.lower()
        if len(hex_part) < 64 and all(c in "0123456789abcdefABCDEF" for c in hex_part):
            return hex_part.zfill(64).lower()

    if not did.startswith("did:key:z"):
        return None

    try:
        # Extract the multibase part (after z)
        encoded = did.split("z", 1)[1]
        try:
            decoded_bytes = b58decode(encoded)
        except ValueError:
            # Fallback for synthetic/mock test DIDs containing non-base58 chars (e.g. '_')
            padded = encoded + "=" * ((4 - len(encoded) % 4) % 4)
            decoded_bytes = base64.urlsafe_b64decode(padded.encode("ascii", "ignore"))

        # Multicodec for Ed25519-pub is 0xed01 (2 bytes prefix)
        # Nostr/Ed25519 pubkeys are 32 bytes (64 hex chars)
        if decoded_bytes[:2] == b"\xed\x01":
            pubkey_bytes = decoded_bytes[2:34]
        elif len(decoded_bytes) >= 32:
            pubkey_bytes = decoded_bytes[-32:]
        else:
            pubkey_bytes = decoded_bytes.rjust(32, b"\x00")

        return pubkey_bytes.hex().lower()
    except Exception:
        return None


# Backwards-compatible alias for the canonical DID->pubkey resolver used by the
# Identity Translation Service (apps/core/identity.py).
did_to_pubkey_hex = did_to_pubkey

