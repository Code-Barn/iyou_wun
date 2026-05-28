import hashlib
import json
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
