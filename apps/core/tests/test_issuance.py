import json

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse

from ..did_kit import (
    build_unsigned_vc,
    get_public_key_hex,
    load_signing_key,
    sign_vc,
    verify_vc_signature,
)

TEST_PRIVATE_KEY_HEX = "a" * 64  # 32 raw bytes hex-encoded = 64 hex chars
TEST_PUBLIC_KEY_HEX = ""


def _ephemeral_keypair():
    pk = Ed25519PrivateKey.generate()
    key_hex = pk.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    ).hex()
    pub_hex = get_public_key_hex(pk)
    return key_hex, pub_hex, pk


def _derive_pubkey(private_key_hex: str) -> str:
    sk = load_signing_key(private_key_hex)
    return get_public_key_hex(sk)


EPHEM_KEY_HEX, EPHEM_PUB_HEX, EPHEM_KEY_OBJ = _ephemeral_keypair()

TEST_SETTINGS = override_settings(
    NODE_DID="did:key:z6Mktest",
    NODE_PRIVATE_KEY_HEX=EPHEM_KEY_HEX,
    SECRET_KEY="test-secret-key-not-used-when-NODE_PRIVATE_KEY_HEX-set",
)


class DIDKitUnitTest(TestCase):
    def test_load_signing_key_32_bytes(self):
        sk = load_signing_key(EPHEM_KEY_HEX)
        self.assertIsInstance(sk, Ed25519PrivateKey)

    def test_load_signing_key_64_bytes(self):
        long_hex = EPHEM_KEY_HEX + "0" * 64  # pad to 64 bytes
        # At 64 bytes (512 bits) this will fail because Ed25519 keys are 32 bytes
        # Let's use a proper 64-byte seed format
        seed = bytes.fromhex(EPHEM_KEY_HEX[:64])  # 32 bytes
        combined = seed + seed  # 64 bytes (seed + seed as "seed + public key")
        sk = load_signing_key(combined.hex())
        self.assertIsInstance(sk, Ed25519PrivateKey)

    def test_build_unsigned_vc_structure(self):
        vc = build_unsigned_vc(
            subject_did="did:key:z6Mktestsubject",
            credential_type="voter_credential",
            fidelity_score=85,
            issuer_did="did:key:z6Mkissuer",
        )
        self.assertIn("@context", vc)
        self.assertIn("id", vc)
        self.assertIn("type", vc)
        self.assertIn("VerifiableCredential", vc["type"])
        self.assertIn("voter_credential", vc["type"])
        self.assertEqual(vc["issuer"], "did:key:z6Mkissuer")
        self.assertEqual(vc["credentialSubject"]["id"], "did:key:z6Mktestsubject")
        self.assertEqual(vc["credentialSubject"]["fidelity_score"], 85)
        self.assertIn("issuanceDate", vc)
        self.assertIn("expirationDate", vc)

    def test_sign_and_verify_vc_round_trip(self):
        vc = build_unsigned_vc(
            subject_did="did:key:z6Mkverifytest",
            credential_type="voter_credential",
            fidelity_score=42,
            issuer_did="did:key:z6Mkverifier",
        )
        signed = sign_vc(vc, EPHEM_KEY_OBJ, "did:key:z6Mkverifier#keys-1")
        self.assertIn("proof", signed)
        proof = signed["proof"]
        self.assertEqual(proof["type"], "Ed25519Signature2020")
        self.assertEqual(proof["proofPurpose"], "assertionMethod")
        self.assertEqual(proof["verificationMethod"], "did:key:z6Mkverifier#keys-1")
        self.assertIn("proofValue", proof)
        # proofValue must be hex
        self.assertRegex(proof["proofValue"], r"^[0-9a-f]+$")
        # verify
        self.assertTrue(verify_vc_signature(signed, EPHEM_PUB_HEX))

    def test_verify_wrong_key_fails(self):
        vc = build_unsigned_vc(
            subject_did="did:key:z6Mkwrongkey",
            credential_type="voter_credential",
            fidelity_score=1,
            issuer_did="did:key:z6Mkissuer",
        )
        signed = sign_vc(vc, EPHEM_KEY_OBJ, "did:key:z6Mkissuer#keys-1")
        wrong_pub_hex = "ff" * 32
        self.assertFalse(verify_vc_signature(signed, wrong_pub_hex))

    def test_verify_tampered_vc_fails(self):
        vc = build_unsigned_vc(
            subject_did="did:key:z6Mktamper",
            credential_type="voter_credential",
            fidelity_score=99,
            issuer_did="did:key:z6Mkissuer",
        )
        signed = sign_vc(vc, EPHEM_KEY_OBJ, "did:key:z6Mkissuer#keys-1")
        signed["credentialSubject"]["fidelity_score"] = 0
        self.assertFalse(verify_vc_signature(signed, EPHEM_PUB_HEX))


@TEST_SETTINGS
class IssueCredentialAPITest(TestCase):
    def setUp(self):
        self.url = reverse("api_issue_credential")
        self.staff_user = User.objects.create_user(
            username="did:key:z6Mkadmin",
            is_staff=True,
        )
        self.non_staff_user = User.objects.create_user(
            username="did:key:z6Mkregular",
            is_staff=False,
        )
        self.payload = {
            "voter_did": "did:key:z6Mkvoter123456789",
            "credential_type": "voter_credential",
            "fidelity_score": 85,
        }

    def test_anonymous_gets_302(self):
        response = self.client.post(
            self.url,
            data=json.dumps(self.payload),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 302)

    def test_non_staff_gets_403(self):
        self.client.force_login(self.non_staff_user)
        response = self.client.post(
            self.url,
            data=json.dumps(self.payload),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)

    def test_staff_can_issue_credential(self):
        self.client.force_login(self.staff_user)
        response = self.client.post(
            self.url,
            data=json.dumps(self.payload),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertIn("@context", data)
        self.assertIn("proof", data)
        self.assertIn("VerifiableCredential", data["type"])
        self.assertIn("voter_credential", data["type"])
        self.assertEqual(data["issuer"], "did:key:z6Mktest")
        self.assertEqual(data["credentialSubject"]["id"], "did:key:z6Mkvoter123456789")
        self.assertEqual(data["credentialSubject"]["fidelity_score"], 85)
        self.assertRegex(data["proof"]["proofValue"], r"^[0-9a-f]+$")

    def test_response_vc_is_cryptographically_valid(self):
        self.client.force_login(self.staff_user)
        response = self.client.post(
            self.url,
            data=json.dumps(self.payload),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        signed_vc = response.json()
        self.assertTrue(
            verify_vc_signature(signed_vc, EPHEM_PUB_HEX),
            "VC signature must be verifiable with the ephemeral test public key",
        )

    def test_get_returns_405(self):
        self.client.force_login(self.staff_user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 405)

    def test_missing_voter_did_returns_400(self):
        self.client.force_login(self.staff_user)
        payload = {"credential_type": "voter_credential", "fidelity_score": 50}
        response = self.client.post(
            self.url,
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)

    def test_missing_credential_type_returns_400(self):
        self.client.force_login(self.staff_user)
        payload = {"voter_did": "did:key:z6Mkxyz", "fidelity_score": 50}
        response = self.client.post(
            self.url,
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)

    def test_missing_fidelity_score_returns_400(self):
        self.client.force_login(self.staff_user)
        payload = {"voter_did": "did:key:z6Mkxyz", "credential_type": "voter_credential"}
        response = self.client.post(
            self.url,
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)

    def test_invalid_did_format_returns_400(self):
        self.client.force_login(self.staff_user)
        payload = {
            "voter_did": "not-a-did",
            "credential_type": "voter_credential",
            "fidelity_score": 50,
        }
        response = self.client.post(
            self.url,
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)

    def test_invalid_json_returns_400(self):
        self.client.force_login(self.staff_user)
        response = self.client.post(
            self.url,
            data="not json",
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)

    def test_fidelity_score_out_of_range_returns_400(self):
        self.client.force_login(self.staff_user)
        for score in [-1, 101]:
            payload = {
                "voter_did": "did:key:z6Mkabc",
                "credential_type": "voter_credential",
                "fidelity_score": score,
            }
            response = self.client.post(
                self.url,
                data=json.dumps(payload),
                content_type="application/json",
            )
            self.assertEqual(response.status_code, 400)

    def test_issued_credential_is_persisted(self):
        from ..models import IssuedCredential

        self.client.force_login(self.staff_user)
        response = self.client.post(
            self.url,
            data=json.dumps(self.payload),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        vc = response.json()
        record = IssuedCredential.objects.get(vc_id=vc["id"])
        self.assertEqual(record.subject_did, "did:key:z6Mkvoter123456789")
        self.assertEqual(record.credential_type, "voter_credential")
        self.assertIsNotNone(record.issued_at)

    def test_issuance_creates_db_record(self):
        self.client.force_login(self.staff_user)
        self.client.post(
            self.url,
            data=json.dumps(self.payload),
            content_type="application/json",
        )
        from ..models import IssuedCredential

        self.assertEqual(IssuedCredential.objects.count(), 1)
