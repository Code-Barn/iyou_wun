"""Tier 1 (did:web) custodial Nostr signing and /api/notes/publish/ coverage."""

import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.core import nostr_signer
from apps.core.custodial_keys import (
    decrypt_secret,
    get_or_create_custodial_keypair,
    is_managed_account,
)
from apps.core.models import UserLinkDeck

User = get_user_model()


class BIP340SignerTests(TestCase):
    """BIP-340 reference vector plus NIP-01 canonical event signing."""

    VECTOR_SECRET = "0000000000000000000000000000000000000000000000000000000000000003"
    VECTOR_PUBKEY = "F9308A019258C31049344F85F89D5229B531C845836F99B08601F113BCE036F9"
    VECTOR_SIGNATURE = (
        "E907831F80848D1069A5371B402410364BDF1C5F8307B0084C55F1CE2DCA82152"
        "5F66A4A85EA8B71E482A74F382D2CE5EBEEE8FDB2172F477DF4900D310536C0"
    )

    def test_bip340_reference_vector(self):
        message = bytes(32)
        aux = bytes(32)
        self.assertEqual(
            nostr_signer.pubkey_from_secret(self.VECTOR_SECRET),
            self.VECTOR_PUBKEY.lower(),
        )
        self.assertEqual(
            nostr_signer.schnorr_sign(message, self.VECTOR_SECRET, aux).hex().lower(),
            self.VECTOR_SIGNATURE.lower(),
        )
        self.assertTrue(
            nostr_signer.schnorr_verify(
                self.VECTOR_SIGNATURE.lower(), message, self.VECTOR_PUBKEY.lower()
            )
        )

    def test_nip01_event_signing_self_verifies_and_detects_tampering(self):
        secret = nostr_signer.generate_secret()
        unsigned = {
            "created_at": 1700000000,
            "kind": 1,
            "tags": [["t", "iyou"], ["client", "iyou_wun"]],
            "content": "custodial hello — ☃",
        }
        signed = nostr_signer.sign_event(unsigned, secret, aux_rand=bytes(32))
        self.assertTrue(nostr_signer.verify_event(signed))
        self.assertEqual(
            nostr_signer.event_id_bytes(
                signed["pubkey"], signed["created_at"], signed["kind"], signed["tags"], signed["content"]
            ).hex(),
            signed["id"],
        )
        tampered = dict(signed)
        tampered["content"] = "tampered"
        self.assertFalse(nostr_signer.verify_event(tampered))


class ManagedKeyProvisioningTests(TestCase):
    def test_didweb_user_gets_persistent_encrypted_keypair_linked_to_deck(self):
        user = User.objects.create_user(username="did:web:iyou.me:user:phase3")
        session = self.client.session
        session["account_tier"] = "managed_free"
        session.save()
        self.assertTrue(is_managed_account(user))

        secret, pubkey, created = get_or_create_custodial_keypair(user)
        self.assertTrue(created)
        deck = UserLinkDeck.objects.get(user=user)
        self.assertEqual(deck.nostr_pubkey, pubkey)
        self.assertEqual(deck.custodial_pubkey_hex, pubkey)
        self.assertNotEqual(deck.custodial_private_key_enc, secret)
        self.assertEqual(decrypt_secret(deck.custodial_private_key_enc), secret)

        secret_again, pubkey_again, created_again = get_or_create_custodial_keypair(user)
        self.assertFalse(created_again)
        self.assertEqual(secret, secret_again)
        self.assertEqual(pubkey, pubkey_again)


class ManagedContextTests(TestCase):
    def test_user_identity_exposes_tier_did_and_custodial_pubkey(self):
        from django.test import RequestFactory

        from apps.core.context_processors import user_identity

        user = User.objects.create_user(username="did:web:iyou.me:user:context")
        request = RequestFactory().get("/feed")
        request.user = user
        request.session = {"account_tier": "managed_free"}
        context = user_identity(request)
        self.assertEqual(context["user_account_tier"], "L1")
        self.assertEqual(context["user_did"], user.username)
        self.assertTrue(context["is_custodial"])
        deck = UserLinkDeck.objects.get(user=user)
        self.assertEqual(context["user_pubkey"], deck.custodial_pubkey_hex)


class ApiPublishNoteTests(TestCase):
    url = reverse("api_publish_note")

    def setUp(self):
        self.managed = User.objects.create_user(username="did:web:iyou.me:user:poster")
        self.sovereign = User.objects.create_user(username="did:key:z6Mksovereign")

    def _login_managed(self):
        self.client.force_login(self.managed)
        session = self.client.session
        session["account_tier"] = "managed_free"
        session["custodial_did"] = self.managed.username
        session.save()

    @patch("apps.core.views._broadcast_signed_event", return_value=["wss://relay.iyou.me"])
    def test_authenticated_tier1_publishes_signed_kind1(self, _broadcast):
        self._login_managed()
        response = self.client.post(
            self.url,
            data=json.dumps({"content": "hello from managed account", "kind": 1}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["ok"])
        event = data["event"]
        self.assertEqual(event["kind"], 1)
        self.assertTrue(nostr_signer.verify_event(event))
        self.assertIn(["t", "iyou"], event["tags"])
        self.assertIn(["client", "iyou_wun"], event["tags"])
        self.assertEqual(data["relays_published"], ["wss://relay.iyou.me"])

    @patch("apps.core.views._broadcast_signed_event", return_value=["wss://relay.iyou.me"])
    def test_tier1_reply_kind1111(self, _broadcast):
        self._login_managed()
        response = self.client.post(
            self.url,
            data=json.dumps(
                {
                    "content": "a reply",
                    "kind": 1111,
                    "tags": [["e", "ab" * 32, "", "root"]],
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["event"]["kind"], 1111)

    def test_unauthenticated_is_rejected(self):
        response = self.client.post(
            self.url,
            data=json.dumps({"content": "anonymous"}),
            content_type="application/json",
        )
        self.assertIn(response.status_code, (302, 401))

    def test_sovereign_without_custodial_key_is_rejected(self):
        self.client.force_login(self.sovereign)
        session = self.client.session
        session["account_tier"] = "sovereign"
        session.save()
        response = self.client.post(
            self.url,
            data=json.dumps({"content": "must sign locally"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            response.json()["error"],
            "Sovereign accounts must sign via local enclave or NIP-07",
        )
