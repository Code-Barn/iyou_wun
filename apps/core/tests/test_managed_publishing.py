"""Tier 1 (did:web) custodial Nostr signing and /api/notes/publish/ coverage."""

import json
from unittest.mock import patch

from django.conf import settings
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


class MobileChromeTemplateTests(TestCase):
    """Phase 5 mobile chrome contracts (source-level guards)."""

    def test_layer1_header_is_not_sticky(self):
        src = (settings.BASE_DIR / "templates" / "includes" / "_standard_header.html").read_text()
        header_line = next(
            line for line in src.splitlines() if 'id="layer-1-standard-header"' in line
        )
        self.assertIn("relative z-30", header_line)
        self.assertNotIn("sticky", header_line)
        self.assertNotIn("top-0", header_line)

    def test_compact_mobile_persona_symbol_and_identity_card(self):
        src = (settings.BASE_DIR / "templates" / "includes" / "_persona_enclave.html").read_text()
        self.assertIn('sm:hidden text-xs leading-none', src)
        self.assertIn("🪪", src)
        self.assertIn("hidden sm:inline truncate max-w-[180px]", src)
        self.assertIn("Signed-In Identity", src)
        self.assertIn("break-all", src)
        self.assertIn("Copy DID", src)

    def test_mobile_dock_chat_route_and_scroll_autohide(self):
        src = (settings.BASE_DIR / "templates" / "includes" / "_mobile_bottom_dock.html").read_text()
        self.assertIn("mobile-nav-chat-btn", src)
        self.assertIn("window.IyouChatDock.toggle", src)
        self.assertIn("DELTA_THRESHOLD = 12", src)
        self.assertIn("translate-y-full", src)
        self.assertIn("requestAnimationFrame", src)

    def test_toast_stack_clears_mobile_dock(self):
        src = (settings.BASE_DIR / "templates" / "includes" / "_toast_container.html").read_text()
        self.assertIn("bottom-20 md:bottom-6", src)
        self.assertIn("z-50", src)


class ManagedBroadcastAckTests(TestCase):
    @patch("apps.core.views.create_connection")
    def test_broadcast_waits_for_ok_acknowledgement(self, create_connection):
        from apps.core.views import _broadcast_signed_event

        class FakeSocket:
            def __init__(self):
                self.frame = json.dumps(["OK", "event-id", True])
                self.sent = None
                self.closed = False

            def send(self, payload):
                self.sent = payload

            def recv(self):
                frame, self.frame = self.frame, None
                if frame is None:
                    raise TimeoutError()
                return frame

            def close(self):
                self.closed = True

        socket = FakeSocket()
        create_connection.return_value = socket
        signed_event = {"id": "event-id", "kind": 1, "tags": [], "content": "x"}
        published = _broadcast_signed_event(signed_event, ["wss://relay.iyou.me"], timeout=1.0)
        self.assertEqual(published, ["wss://relay.iyou.me"])
        self.assertIn('"EVENT"', socket.sent)
        self.assertTrue(socket.closed)


class ManagedProfilePersistenceTests(TestCase):
    def test_deck_key_is_ecosystem_member_and_profile_author(self):
        user = User.objects.create_user(username="did:web:iyou.me:user:persist")
        _secret, pubkey, _created = get_or_create_custodial_keypair(user)
        from apps.core.identity import get_ecosystem_pubkeys
        from apps.core.views import _resolve_profile_candidates

        self.assertIn(pubkey, get_ecosystem_pubkeys(force_refresh=True))
        _carried, owner, deck, hex_pubkey, candidates = _resolve_profile_candidates(user.username)
        self.assertEqual(owner, user)
        self.assertEqual(hex_pubkey, pubkey)
        self.assertIn(pubkey, candidates)


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

    @patch("apps.core.views._broadcast_signed_event", return_value=["wss://relay.iyou.me"])
    def test_tier1_poll_and_media_authoring_kinds(self, _broadcast):
        self._login_managed()
        for kind, content in ((30023, "Civic poll description"), (1063, "Media announcement")):
            response = self.client.post(
                self.url,
                data=json.dumps(
                    {
                        "content": content,
                        "kind": kind,
                        "tags": [["d", "poll-1"], ["title", "Poll"], ["option", "Yes"], ["option", "No"]],
                    }
                ),
                content_type="application/json",
            )
            self.assertEqual(response.status_code, 200, response.content)
            event = response.json()["event"]
            self.assertEqual(event["kind"], kind)
            self.assertTrue(nostr_signer.verify_event(event))
            self.assertIn(["t", "iyou"], event["tags"])
            self.assertIn(["client", "iyou_wun"], event["tags"])

    @patch("apps.core.views._broadcast_signed_event", return_value=["wss://relay.iyou.me"])
    def test_oversized_content_rejected(self, _broadcast):
        self._login_managed()
        response = self.client.post(
            self.url,
            data=json.dumps({"content": "x" * 2501, "kind": 1}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)


class ApiInteractNoteTests(TestCase):
    url = reverse("api_interact_note")

    def setUp(self):
        self.managed = User.objects.create_user(username="did:web:iyou.me:user:interactor")
        self.sovereign = User.objects.create_user(username="did:key:z6Mkinteractor")
        self.target = "ab" * 32
        self.author = "cd" * 32

    def _login_managed(self):
        self.client.force_login(self.managed)
        session = self.client.session
        session["account_tier"] = "managed_free"
        session.save()

    @patch("apps.core.views._broadcast_signed_event", return_value=["wss://relay.iyou.me"])
    def test_managed_interaction_kinds(self, _broadcast):
        self._login_managed()
        for kind, content in ((7, ""), (6, ""), (1112, '{"poll_id":"x"}'), (1984, "Report: SPAM")):
            response = self.client.post(
                self.url,
                data=json.dumps(
                    {
                        "kind": kind,
                        "content": content,
                        "tags": [["e", self.target], ["p", self.author]],
                    }
                ),
                content_type="application/json",
            )
            self.assertEqual(response.status_code, 200, response.content)
            data = response.json()
            self.assertTrue(data["ok"])
            self.assertTrue(nostr_signer.verify_event(data["event"]))
            self.assertEqual(data["event"]["kind"], kind)
            if kind == 7:
                self.assertEqual(data["event"]["content"], "+")

    def test_invalid_hex_reference_rejected(self):
        self._login_managed()
        response = self.client.post(
            self.url,
            data=json.dumps({"kind": 7, "tags": [["e", "not-hex"]]}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)

    def test_sovereign_rejected(self):
        self.client.force_login(self.sovereign)
        session = self.client.session
        session["account_tier"] = "sovereign"
        session.save()
        response = self.client.post(
            self.url, data=json.dumps({"kind": 7, "tags": []}), content_type="application/json"
        )
        self.assertEqual(response.status_code, 403)


class ManagedContactsAndBroadcastTests(TestCase):
    def setUp(self):
        self.managed = User.objects.create_user(username="did:web:iyou.me:user:contacts")
        self.client.force_login(self.managed)
        session = self.client.session
        session["account_tier"] = "managed_free"
        session.save()
        self.first = "ab" * 32
        self.second = "cd" * 32

    @patch("apps.core.views._broadcast_signed_event", return_value=["wss://relay.iyou.me"])
    def test_follow_unfollow_is_non_destructive_and_signed(self, broadcast):
        follow_url = reverse("api_contacts_follow")
        for target in (self.first, self.second):
            response = self.client.post(
                follow_url,
                data=json.dumps({"target_pubkey": target, "action": "follow", "petname": "peer"}),
                content_type="application/json",
            )
            self.assertEqual(response.status_code, 200, response.content)
            data = response.json()
            self.assertTrue(data["ok"])
            self.assertTrue(nostr_signer.verify_event(data["event"]))
            self.assertEqual(data["event"]["kind"], 3)
            self.assertIn(["p", target, "wss://relay.iyou.me", "peer"], data["event"]["tags"])

        response = self.client.post(
            follow_url,
            data=json.dumps({"target_pubkey": self.first, "action": "unfollow"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["count"], 1)

        listing = self.client.get(reverse("api_get_contacts")).json()
        self.assertEqual(listing["following"], [self.second])
        self.assertEqual(len(listing["contacts"]), 1)
        self.assertTrue(broadcast.called)

    @patch("apps.core.views._broadcast_signed_event", return_value=["wss://relay.iyou.me"])
    def test_profile_save_signs_kind0(self, _broadcast):
        response = self.client.post(
            reverse("api_save_profile"),
            data=json.dumps({"name": "Managed User", "about": "hello", "picture": "", "banner": "", "lud16": ""}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        event = response.json()["kind0_event"]
        self.assertEqual(event["kind"], 0)
        self.assertTrue(nostr_signer.verify_event(event))
        metadata = json.loads(event["content"])
        self.assertEqual(metadata["name"], "Managed User")
        self.assertTrue(metadata["nip05"])

    @patch("apps.core.views._broadcast_signed_event", return_value=["wss://relay.iyou.me"])
    def test_bookmark_toggle_signs_kind10004(self, broadcast):
        response = self.client.post(
            reverse("api_toggle_bookmark"),
            data=json.dumps({"event_id": "ef" * 32}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["bookmarked"])
        signed_event = broadcast.call_args[0][0]
        self.assertEqual(signed_event["kind"], 10004)
        self.assertEqual(signed_event["tags"], [["e", "ef" * 32]])
        self.assertTrue(nostr_signer.verify_event(signed_event))
