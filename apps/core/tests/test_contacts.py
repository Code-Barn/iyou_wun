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

import json
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from apps.core.views import (
    claim_handle,
    did_to_npub,
    did_to_pubkey,
    hex_to_npub,
    npub_to_hex,
)



class ContactManagerProfileTests(TestCase):
    def setUp(self):
        self.target_user = User.objects.create_user(username="did:key:z6Mktargetcontact1")
        self.viewer_user = User.objects.create_user(username="did:key:z6Mkviewercontact2")
        self.target_hex = did_to_pubkey(self.target_user.username)
        self.target_npub = did_to_npub(self.target_user.username)

    def _get_profile(self, npub_str):
        with patch("apps.core.views.relay_req", return_value={}):
            return self.client.get(reverse("profile", kwargs={"npub": npub_str}))

    def test_profile_renders_follow_button_for_authenticated_viewer(self):
        """Ensures viewers see follow buttons on other profiles, but not their own."""
        # 1. Authenticated viewer viewing another user's profile
        self.client.force_login(self.viewer_user)
        response = self._get_profile(self.target_npub)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="follow-action-btn"')
        self.assertContains(response, f'data-follow-target="{self.target_hex}"')
        self.assertContains(response, "+ Follow")

        # 2. Target viewing their own profile -> no follow button
        self.client.force_login(self.target_user)
        self_response = self._get_profile(self.target_npub)
        self.assertEqual(self_response.status_code, 200)
        self.assertNotContains(self_response, 'id="follow-action-btn"')

    def test_profile_context_contains_target_nostr_pubkey(self):
        """Verifies hex pubkey and DID are passed to template context."""
        self.client.force_login(self.viewer_user)
        response = self._get_profile(self.target_npub)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["target_nostr_pubkey_hex"], self.target_hex)
        self.assertEqual(response.context["target_did"], self.target_user.username)
        self.assertEqual(response.context["profile_did"], self.target_user.username)
        self.assertEqual(response.context["hex_pubkey"], self.target_hex)

    def test_anonymous_viewer_does_not_see_interactive_follow_button(self):
        """Verifies unauthenticated visitors see read-only profile state."""
        response = self._get_profile(self.target_npub)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'id="follow-action-btn"')
        self.assertNotContains(response, 'data-follow-target')


class ContactManagerDeckTests(TestCase):
    def setUp(self):
        self.deck_owner = User.objects.create_user(username="did:key:z6Mkdeckowner1")
        self.viewer = User.objects.create_user(username="did:key:z6Mkdeckviewer2")
        self.deck = claim_handle(self.deck_owner, "deckfriend")
        self.owner_hex = did_to_pubkey(self.deck_owner.username)

    def _get_deck(self, url):
        with patch("apps.core.views.relay_req", return_value={}):
            return self.client.get(url)

    def test_deck_renders_follow_button_for_authenticated_viewer(self):
        """Ensures viewers see follow buttons on link decks of other users."""
        self.client.force_login(self.viewer)
        response = self._get_deck("/@deckfriend")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="follow-action-btn"')
        self.assertContains(response, f'data-follow-target="{self.owner_hex}"')
        self.assertContains(response, 'data-follow-petname="deckfriend"')

        # Owner viewing their own link deck -> no follow button
        self.client.force_login(self.deck_owner)
        self_response = self._get_deck("/@deckfriend")
        self.assertEqual(self_response.status_code, 200)
        self.assertNotContains(self_response, 'id="follow-action-btn"')

    def test_deck_context_contains_target_nostr_pubkey(self):
        """Verifies target_nostr_pubkey_hex and target_did in LinkDeckView context."""
        self.client.force_login(self.viewer)
        response = self._get_deck("/@deckfriend")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["target_nostr_pubkey_hex"], self.owner_hex)
        self.assertEqual(response.context["target_did"], self.deck_owner.username)
        self.assertEqual(response.context["profile_did"], self.deck_owner.username)
        self.assertEqual(response.context["profile_handle"], "deckfriend")

    def test_anonymous_deck_viewer_does_not_see_follow_button(self):
        """Verifies anonymous visitors see read-only link deck."""
        response = self._get_deck("/@deckfriend")
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'id="follow-action-btn"')


class KeyDerivationTests(TestCase):
    def test_did_key_derivation(self):
        sample_did = "did:key:z6MkhaXgBZDvB9gGHgK9r"
        pubkey = did_to_pubkey(sample_did)
        self.assertIsNotNone(pubkey)
        self.assertEqual(len(pubkey), 64)

    def test_did_iyou_derivation(self):
        sample_hex = "3bf0c63fcb93463407af97a5e5ee64fa883d107ef9e558472c4eb9aaaefa459d"
        sample_did = f"did:iyou:0x{sample_hex}"
        pubkey = did_to_pubkey(sample_did)
        self.assertEqual(pubkey, sample_hex)

    def test_raw_hex_derivation(self):
        sample_hex = "3bf0c63fcb93463407af97a5e5ee64fa883d107ef9e558472c4eb9aaaefa459d"
        pubkey = did_to_pubkey(sample_hex)
        self.assertEqual(pubkey, sample_hex)

    def test_npub_to_hex_derivation(self):
        sample_hex = "3bf0c63fcb93463407af97a5e5ee64fa883d107ef9e558472c4eb9aaaefa459d"
        sample_npub = hex_to_npub(sample_hex)
        self.assertIsNotNone(sample_npub)
        self.assertTrue(sample_npub.startswith("npub1"))
        hex_pubkey = npub_to_hex(sample_npub)
        self.assertEqual(hex_pubkey, sample_hex)


class ContactFollowAPITests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="did:key:z6Mkfollowuser1")
        self.user_pubkey = did_to_pubkey(self.user.username)
        self.target_pubkey = "3bf0c63fcb93463407af97a5e5ee64fa883d107ef9e558472c4eb9aaaefa459d"
        self.other_target_pubkey = "79be667ef9dcbbac55a06295ce870b07029bfcdb2dce28d959f2815b16f81798"

    def test_follow_action_requires_authentication(self):
        response = self.client.post(
            reverse("api_contacts_follow"),
            data=json.dumps({"target_pubkey": self.target_pubkey, "action": "follow"}),
            content_type="application/json",
        )
        self.assertIn(response.status_code, [302, 401])

    def test_follow_action_appends_target_pubkey_to_kind3_tags(self):
        self.client.force_login(self.user)
        with patch("apps.core.views.relay_req", return_value={}):
            response = self.client.post(
                reverse("api_contacts_follow"),
                data=json.dumps({"target_pubkey": self.target_pubkey, "action": "follow"}),
                content_type="application/json",
            )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["action"], "follow")
        self.assertEqual(data["target_pubkey"], self.target_pubkey)
        unsigned = data["unsigned_event"]
        self.assertEqual(unsigned["kind"], 3)
        self.assertEqual(unsigned["pubkey"], self.user_pubkey)
        self.assertIn(["p", self.target_pubkey, "", ""], unsigned["tags"])

    def test_unfollow_action_removes_target_pubkey(self):
        self.client.force_login(self.user)
        existing_event = {
            "kind": 3,
            "pubkey": self.user_pubkey,
            "created_at": 1000,
            "tags": [
                ["p", self.target_pubkey, "", ""],
                ["p", self.other_target_pubkey, "", ""],
            ],
            "content": "",
        }
        with patch("apps.core.views.relay_req", return_value={"relay1": existing_event}):
            response = self.client.post(
                reverse("api_contacts_follow"),
                data=json.dumps({"target_pubkey": self.target_pubkey, "action": "unfollow"}),
                content_type="application/json",
            )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["action"], "unfollow")
        unsigned = data["unsigned_event"]
        self.assertNotIn(["p", self.target_pubkey, "", ""], unsigned["tags"])
        self.assertIn(["p", self.other_target_pubkey, "", ""], unsigned["tags"])

    def test_self_follow_rejected(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("api_contacts_follow"),
            data=json.dumps({"target_pubkey": self.user_pubkey, "action": "follow"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertFalse(data["success"])
        self.assertIn("own profile", data["error"])

    def test_invalid_pubkey_format_rejected(self):
        self.client.force_login(self.user)
        for invalid_pubkey in ["not-a-hex", "1234", "zz" * 32, ""]:
            response = self.client.post(
                reverse("api_contacts_follow"),
                data=json.dumps({"target_pubkey": invalid_pubkey, "action": "follow"}),
                content_type="application/json",
            )
            self.assertEqual(response.status_code, 400)
            data = response.json()
            self.assertFalse(data["success"])


