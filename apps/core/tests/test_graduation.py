"""Atomic did:web -> did:key graduation consolidation tests."""

from django.contrib.auth import get_user_model
from django.contrib.sessions.middleware import SessionMiddleware
from django.test import RequestFactory, TestCase
from django.urls import reverse

from apps.core.auth import MyOIDCAuthenticationBackend
from apps.core.custodial_keys import encrypt_secret
from apps.core.models import Bookmark, UserLinkDeck, UserLinkItem
from apps.core.nostr_signer import generate_secret

User = get_user_model()
LEGACY_DID = "did:web:iyou.me:user:graduate-me"
SOVEREIGN_DID = "did:key:z6Mkgraduatedsovereign"
CONTACTS = [
    {"pubkey": "ab" * 32, "relay": "wss://relay.iyou.me", "petname": "Alice"},
    {"pubkey": "cd" * 32, "relay": "wss://relay.iyou.me", "petname": ""},
]


class GraduationConsolidationTests(TestCase):
    def setUp(self):
        self.legacy_user = User.objects.create_user(username=LEGACY_DID)
        self.legacy_deck = UserLinkDeck.objects.create(
            user=self.legacy_user,
            did=LEGACY_DID,
            handle="graduated",
            display_name="Graduated User",
            nostr_pubkey="ef" * 32,
            custodial_pubkey_hex="ef" * 32,
            custodial_private_key_enc=encrypt_secret(generate_secret()),
            custodial_contacts=CONTACTS,
        )
        self.item_a = UserLinkItem.objects.create(
            user=self.legacy_user, title="Website", url="https://example.com", order=1
        )
        self.item_b = UserLinkItem.objects.create(
            user=self.legacy_user, title="Email", url="mailto:me@example.com", order=2
        )
        Bookmark.objects.create(user=self.legacy_user, event_id="11" * 32)
        Bookmark.objects.create(user=self.legacy_user, event_id="22" * 32)

        self.request = RequestFactory().post("/oidc/callback/")
        SessionMiddleware(lambda r: None).process_request(self.request)
        self.backend = MyOIDCAuthenticationBackend()
        self.backend.request = self.request

    def _claims(self):
        return {
            "sub": SOVEREIGN_DID,
            "graduated_from_did": LEGACY_DID,
            "account_tier": "sovereign",
        }

    def test_create_user_transfers_deck_items_bookmarks_and_queues_graph(self):
        user = self.backend.create_user(self._claims())

        self.legacy_deck.refresh_from_db()
        self.assertEqual(self.legacy_deck.user_id, user.pk)
        self.assertEqual(self.legacy_deck.did, SOVEREIGN_DID)
        self.assertEqual(self.legacy_deck.handle, "graduated")
        self.assertEqual(self.legacy_deck.custodial_contacts, CONTACTS)
        self.assertIsNone(self.legacy_deck.custodial_private_key_enc)
        self.assertEqual(self.legacy_deck.custodial_pubkey_hex, "")
        # did:key z6Mk encodes Ed25519, never a secp256k1 Nostr key.
        self.assertEqual(self.legacy_deck.nostr_pubkey, "")

        self.assertEqual(UserLinkItem.objects.filter(user=user).count(), 2)
        self.assertEqual(UserLinkItem.objects.filter(user=self.legacy_user).count(), 0)
        self.assertEqual(
            set(Bookmark.objects.filter(user=user).values_list("event_id", flat=True)),
            {"11" * 32, "22" * 32},
        )
        self.assertEqual(Bookmark.objects.filter(user=self.legacy_user).count(), 0)

        self.legacy_user.refresh_from_db()
        self.assertFalse(self.legacy_user.is_active)
        self.assertFalse(self.legacy_user.has_usable_password())

        pending = self.request.session["pending_sovereign_graph_migration"]
        self.assertEqual(pending["contacts"], CONTACTS)
        self.assertEqual(set(pending["bookmarks"]), {"11" * 32, "22" * 32})

    def test_update_user_dedupes_existing_bookmarks(self):
        user = User.objects.create_user(username=SOVEREIGN_DID)
        Bookmark.objects.create(user=user, event_id="11" * 32)
        # A placeholder deck auto-created for the sovereign DID must be removed.
        UserLinkDeck.objects.create(user=user, handle="placeholder")

        self.backend.update_user(user, self._claims())

        self.legacy_deck.refresh_from_db()
        self.assertEqual(self.legacy_deck.user_id, user.pk)
        self.assertEqual(UserLinkDeck.objects.filter(user=user).count(), 1)
        self.assertEqual(
            set(Bookmark.objects.filter(user=user).values_list("event_id", flat=True)),
            {"11" * 32, "22" * 32},
        )
        self.assertEqual(Bookmark.objects.filter(user=self.legacy_user).count(), 0)

    def test_non_graduation_claims_do_not_mutate_deck(self):
        user = self.backend.create_user({"sub": SOVEREIGN_DID, "account_tier": "sovereign"})
        self.legacy_deck.refresh_from_db()
        self.assertEqual(self.legacy_deck.user_id, self.legacy_user.pk)
        self.assertEqual(self.legacy_deck.handle, "graduated")
        self.assertNotIn("pending_sovereign_graph_migration", self.request.session)
        self.assertTrue(user.is_active)


class GraduationAckTests(TestCase):
    def test_ack_clears_migration_flag(self):
        user = User.objects.create_user(username=SOVEREIGN_DID)
        self.client.force_login(user)
        session = self.client.session
        session["pending_sovereign_graph_migration"] = {"contacts": [], "bookmarks": ["11" * 32]}
        session.save()

        response = self.client.post(reverse("api_graduation_ack"))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])
        self.assertNotIn("pending_sovereign_graph_migration", self.client.session)

    def test_ack_requires_authentication(self):
        response = self.client.post(reverse("api_graduation_ack"))
        self.assertIn(response.status_code, (302, 401))

    def test_base_html_exposes_pending_migration(self):
        user = User.objects.create_user(username=SOVEREIGN_DID)
        self.client.force_login(user)
        session = self.client.session
        session["pending_sovereign_graph_migration"] = {
            "contacts": CONTACTS,
            "bookmarks": ["11" * 32],
        }
        session.save()
        response = self.client.get(reverse("feed"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "pending-sovereign-migration-data")
        self.assertContains(response, "PENDING_SOVEREIGN_MIGRATION")
