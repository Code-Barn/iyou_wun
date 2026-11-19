"""Phase 6: custodial pubkey self-heal, profile routing and curated deck card."""

import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.core.custodial_keys import ensure_custodial_keypair
from apps.core.identity import decorate_author_identity, get_ecosystem_pubkeys, resolve_author_identity
from apps.core.models import UserLinkDeck, UserLinkItem
from apps.core.views import hex_to_npub

User = get_user_model()
STALE_HASH = "a1" * 32


class CustodialPubkeySyncTests(TestCase):
    def test_stale_did_hash_is_replaced_by_custodial_signing_pubkey(self):
        user = User.objects.create_user(username="did:web:iyou.me:user:sync")
        deck = UserLinkDeck.objects.create(
            user=user, handle="syncuser", display_name="Sync User", nostr_pubkey=STALE_HASH
        )
        pubkey = ensure_custodial_keypair(user)
        deck.refresh_from_db()
        self.assertNotEqual(pubkey, STALE_HASH)
        self.assertEqual(deck.nostr_pubkey, pubkey)
        self.assertEqual(deck.custodial_pubkey_hex, pubkey)
        self.assertIn(pubkey, get_ecosystem_pubkeys(force_refresh=True))
        identity = resolve_author_identity(pubkey)
        self.assertEqual(identity["display_name"], "Sync User")

    @patch("apps.core.views._broadcast_signed_event", return_value=["wss://relay.iyou.me"])
    def test_publish_endpoint_self_heals_pubkey_before_signing(self, _broadcast):
        user = User.objects.create_user(username="did:web:iyou.me:user:publishsync")
        deck = UserLinkDeck.objects.create(user=user, handle="pubsync", nostr_pubkey=STALE_HASH)
        self.client.force_login(user)
        session = self.client.session
        session["account_tier"] = "managed_free"
        session.save()
        response = self.client.post(
            reverse("api_publish_note"),
            data=json.dumps({"content": "hello", "kind": 1}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        event = response.json()["event"]
        deck.refresh_from_db()
        self.assertEqual(event["pubkey"], deck.nostr_pubkey)
        self.assertNotEqual(deck.nostr_pubkey, STALE_HASH)


class AuthorRoutingTests(TestCase):
    def test_decorated_author_url_uses_profile_npub(self):
        note = decorate_author_identity(
            {"pubkey": "3bf0c63fcb93463407af97a5e5ee64fa883d107ef9e558472c4eb9aaaefa459d",
             "content": "hello", "npub": ""}
        )
        self.assertTrue(note["author_url"].startswith("/profile/npub1"))
        self.assertFalse(note["author_url"].startswith("/@"))

    def test_client_card_builder_does_not_route_to_handle_urls(self):
        from django.conf import settings

        src = (settings.BASE_DIR / "static" / "js" / "feed_interactions.js").read_text()
        self.assertIn("function hexToNpub", src)
        self.assertNotIn('"/@" + routingId', src)
        self.assertIn('"/profile/" + encodeURIComponent(routingId)', src)


class CuratedDeckTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="did:web:iyou.me:user:curate")
        self.deck = UserLinkDeck.objects.create(
            user=self.user, handle="curator", display_name="Curated Person", nostr_pubkey="b2" * 32
        )
        self.items = [
            UserLinkItem.objects.create(user=self.user, title=f"Link {index}", url=f"https://example.com/{index}",
                                        is_featured=index < 2, order=index)
            for index in range(4)
        ]

    def test_profile_view_embeds_featured_items_with_expand_toggle(self):
        npub = hex_to_npub(self.deck.nostr_pubkey)
        response = self.client.get(f"/profile/{npub}/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Curated Links")
        self.assertContains(response, "Link 0")
        self.assertContains(response, "Link 1")
        self.assertContains(response, "Show all 4 links")
        self.assertContains(response, "Standalone Card")
        self.assertContains(response, "toggleAllDeckItems")

    def test_api_deck_item_featured_toggle(self):
        self.client.force_login(self.user)
        created = self.client.post(
            reverse("api_deck_items"),
            data=json.dumps({"title": "New Link", "url": "https://example.com/new"}),
            content_type="application/json",
        )
        self.assertEqual(created.status_code, 201)
        item_id = created.json()["item"]["id"]
        self.assertTrue(created.json()["item"]["is_featured"])
        patched = self.client.patch(
            reverse("api_deck_item_detail", kwargs={"pk": item_id}),
            data=json.dumps({"is_featured": False}),
            content_type="application/json",
        )
        self.assertEqual(patched.status_code, 200)
        listing = self.client.get(reverse("api_deck_items")).json()
        entry = next(item for item in listing["items"] if item["id"] == item_id)
        self.assertFalse(entry["is_featured"])

    def test_link_deck_social_feed_links_to_profile_and_uses_display_name(self):
        with patch("apps.core.views.relay_req", return_value={}):
            response = self.client.get("/@curator")
        self.assertEqual(response.status_code, 200)
        npub = hex_to_npub(self.deck.nostr_pubkey)
        profile_url = reverse("profile", kwargs={"npub": npub})
        self.assertContains(response, f'href="{profile_url}"')
        self.assertContains(response, "Curated Person")
        self.assertNotContains(response, "Anonymous")
