# Copyright (C) 2026 David Byers dba Byers Brands
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.

"""Ship-readiness test suite verifying Modules 1-4.

Tests profile navigation reachability, Secp256k1 key resolution without Ed25519
masquerading, key sync with UserLinkDeck creation, relay topology security isolation,
favicon redirection, and author identity decoration.
"""

import json
from django.contrib.auth import get_user_model
from django.template import Context, Template
from django.test import RequestFactory, TestCase
from django.urls import reverse

from apps.core.identity import decorate_author_identity
from apps.core.models import UserLinkDeck
from apps.core.views import (
    LOCAL_RELAY,
    _resolve_profile_candidates,
    api_sync_keys,
    get_effective_user_pubkey,
    order_relays,
)

UserModel = get_user_model()


class ShipReadinessNavigationTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = UserModel.objects.create_user(username="did:key:z6Mkujsd89testuser123")
        self.deck = UserLinkDeck.objects.create(
            user=self.user,
            handle="testpilot",
            display_name="Test Pilot",
            nostr_pubkey="4072dc50bc14f85e48d3bc31bf90df2aa982ee33c6ce091605330e25866164f9",
        )

    def test_left_rail_profile_slot_rendered(self):
        """Profile slot in _left_rail_slots.html renders link to user profile."""
        template = Template(
            '{% load static %}{% include "includes/_left_rail_slots.html" %}'
        )
        context = Context({
            "user": self.user,
            "user_profile_url": "/profile/testpilot/",
            "user_avatar_url": "",
        })
        rendered = template.render(context)
        self.assertIn('/profile/testpilot/', rendered)
        self.assertIn('Profile', rendered)

    def test_mobile_bottom_dock_profile_destination(self):
        """Mobile bottom dock renders profile link for 1-tap navigation."""
        template = Template(
            '{% load static %}{% include "includes/_mobile_bottom_dock.html" %}'
        )
        context = Context({
            "user": self.user,
            "user_profile_url": "/profile/testpilot/",
        })
        rendered = template.render(context)
        self.assertIn('/profile/testpilot/', rendered)
        self.assertIn('Profile', rendered)

    def test_resolve_profile_candidates_strips_leading_at(self):
        """_resolve_profile_candidates handles @handle lookups cleanly."""
        _carried, owner_user, owner_deck, hex_pubkey, candidates = _resolve_profile_candidates("@testpilot")
        self.assertEqual(owner_deck, self.deck)
        self.assertEqual(owner_user, self.user)
        self.assertIn(self.deck.nostr_pubkey, candidates)


class ShipReadinessKeyAndSyncTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.secp_hex = "4072dc50bc14f85e48d3bc31bf90df2aa982ee33c6ce091605330e25866164f9"

    def test_get_effective_user_pubkey_unsynced_ed25519_returns_empty(self):
        """Unsynced Ed25519 DID user must return empty string, never Ed25519 bytes."""
        user = UserModel.objects.create_user(username="did:key:z6Mkujsd89unsynced")
        request = self.factory.get("/")
        request.user = user
        request.session = {}

        pubkey = get_effective_user_pubkey(request)
        self.assertEqual(pubkey, "")

    def test_get_effective_user_pubkey_synced_returns_lowercase_hex(self):
        """Synced Secp256k1 key in session or deck returns lowercase 64-char hex."""
        user = UserModel.objects.create_user(username="did:key:z6Mkujsd89synced")
        request = self.factory.get("/")
        request.user = user
        request.session = {"nostr_pubkey_hex": self.secp_hex.upper()}

        pubkey = get_effective_user_pubkey(request)
        self.assertEqual(pubkey, self.secp_hex.lower())

    def test_api_sync_keys_creates_deck_and_sets_nostr_pubkey(self):
        """api_sync_keys ensures UserLinkDeck exists and persists nostr_pubkey."""
        user = UserModel.objects.create_user(username="did:key:z6Mkujsd89synckey")
        request = self.factory.post(
            reverse("api_sync_keys"),
            data=json.dumps({"nostr_pubkey_hex": self.secp_hex}),
            content_type="application/json",
        )
        request.user = user
        request.session = self.client.session

        response = api_sync_keys(request)
        self.assertEqual(response.status_code, 200)

        data = json.loads(response.content)
        self.assertTrue(data.get("success"))
        self.assertEqual(data.get("nostr_pubkey_hex"), self.secp_hex)

        deck = UserLinkDeck.objects.filter(user=user).first()
        self.assertIsNotNone(deck)
        self.assertEqual(deck.nostr_pubkey, self.secp_hex)
        self.assertEqual(request.session.get("nostr_pubkey_hex"), self.secp_hex)


class ShipReadinessTopologyAndAssetTests(TestCase):
    def test_order_relays_omits_local_relay_on_https(self):
        """order_relays must omit loopback ws://127.0.0.1:9003 when is_secure=True."""
        fleet = ["wss://relay.iyou.me", "wss://nos.lol"]
        secure_relays = order_relays(fleet, is_secure=True)
        self.assertNotIn(LOCAL_RELAY, secure_relays)
        self.assertFalse(any("127.0.0.1" in r or "localhost" in r for r in secure_relays))

        insecure_relays = order_relays(fleet, is_secure=False)
        self.assertEqual(insecure_relays[0], LOCAL_RELAY)

    def test_favicon_ico_redirect(self):
        """/static/favicon.ico must redirect cleanly to logo_square.png."""
        response = self.client.get("/static/favicon.ico")
        self.assertIn(response.status_code, (301, 302))
        self.assertIn("logo_square.png", response.headers.get("Location", ""))

    def test_decorate_author_identity_scrubs_primary_identity(self):
        """decorate_author_identity replaces generic Primary Identity with deck info."""
        user = UserModel.objects.create_user(username="did:key:z6Mkujsd89deckuser")
        deck = UserLinkDeck.objects.create(
            user=user,
            handle="dcbyers13",
            display_name="David Byers",
            nostr_pubkey="4072dc50bc14f85e48d3bc31bf90df2aa982ee33c6ce091605330e25866164f9",
        )

        note = {
            "pubkey": deck.nostr_pubkey,
            "author_name": "Primary Identity (L1)",
            "content": "Hello Sovereign Web",
        }
        decorated = decorate_author_identity(note)
        self.assertEqual(decorated["author_display_name"], "David Byers")
        self.assertEqual(decorated["author_handle"], "dcbyers13")
        from apps.core.views import hex_to_npub

        self.assertEqual(decorated["author_url"], f"/profile/{hex_to_npub(deck.nostr_pubkey)}/")
        self.assertFalse(decorated["author_url"].startswith("/@"))
