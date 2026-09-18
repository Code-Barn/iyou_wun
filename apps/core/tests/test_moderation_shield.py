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
import urllib.error
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from apps.core.models import NodeBlockedEntity, NodeContentTakedown
from apps.core.moderation import (
    CACHE_KEY_BLOCKED_ENTITIES,
    CACHE_KEY_BLOCKED_EVENTS,
    CACHE_KEY_BLOCKED_MEDIA,
    filter_shielded_events,
    get_shield_rosters,
    invalidate_shield_cache,
    is_event_shielded,
    purge_blossom_blob,
)


class ModerationShieldCoreTests(TestCase):
    def setUp(self):
        super().setUp()
        invalidate_shield_cache()

    def tearDown(self):
        invalidate_shield_cache()
        super().tearDown()

    def test_get_shield_rosters_and_caching(self):
        """Verify get_shield_rosters queries models, populates cache, and returns sets."""
        NodeBlockedEntity.objects.create(
            entity_identifier="pubkey111111111111111111111111111111111111111111111111111111111111",
            reason="SPAM_BOT",
            is_active=True,
        )
        NodeBlockedEntity.objects.create(
            entity_identifier="pubkey_inactive",
            reason="HARASSMENT",
            is_active=False,
        )
        NodeContentTakedown.objects.create(
            event_id="event2222222222222222222222222222222222222222222222222222222222222222",
            reason="ILLEGAL_CSAM",
        )
        NodeContentTakedown.objects.create(
            media_hash="media33333333333333333333333333333333333333333333333333333333333333",
            reason="MALWARE",
        )

        rosters = get_shield_rosters()
        self.assertIsInstance(rosters.blocked_entities, set)
        self.assertIsInstance(rosters.blocked_events, set)
        self.assertIsInstance(rosters.blocked_media, set)

        # Active pubkey is included
        self.assertIn("pubkey111111111111111111111111111111111111111111111111111111111111", rosters.blocked_entities)
        # Inactive pubkey is excluded
        self.assertNotIn("pubkey_inactive", rosters.blocked_entities)
        # Takedown event and media are included
        self.assertIn("event2222222222222222222222222222222222222222222222222222222222222222", rosters.blocked_events)
        self.assertIn("media33333333333333333333333333333333333333333333333333333333333333", rosters.blocked_media)

        # Verify cached in Django cache
        self.assertIsNotNone(cache.get(CACHE_KEY_BLOCKED_ENTITIES))
        self.assertIsNotNone(cache.get(CACHE_KEY_BLOCKED_EVENTS))
        self.assertIsNotNone(cache.get(CACHE_KEY_BLOCKED_MEDIA))

        # Test tuple unpacking and dictionary/attribute access
        entities, events, media = rosters
        self.assertEqual(entities, rosters.blocked_entities)
        self.assertEqual(events, rosters.blocked_events)
        self.assertEqual(media, rosters.blocked_media)
        self.assertEqual(rosters["blocked_entities"], rosters.blocked_entities)
        self.assertEqual(rosters.get("blocked_events"), rosters.blocked_events)
        self.assertEqual(rosters.get("non_existent", "default"), "default")

        # Invalidate cache
        invalidate_shield_cache()
        self.assertIsNone(cache.get(CACHE_KEY_BLOCKED_ENTITIES))
        self.assertIsNone(cache.get(CACHE_KEY_BLOCKED_EVENTS))
        self.assertIsNone(cache.get(CACHE_KEY_BLOCKED_MEDIA))

    def test_blocked_entity_suppression(self):
        """Events signed by a blocked pubkey are removed from filter_shielded_events()."""
        NodeBlockedEntity.objects.create(
            entity_identifier="blocked_pubkey_64hex_abc123",
            reason="SPAM_BOT",
            is_active=True,
        )
        invalidate_shield_cache()

        events = [
            {"id": "ev_spam_1", "pubkey": "blocked_pubkey_64hex_abc123", "content": "spam content"},
            {"id": "ev_clean_2", "pubkey": "clean_pubkey_64hex_def456", "content": "clean content"},
        ]
        filtered = filter_shielded_events(events)
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["id"], "ev_clean_2")
        self.assertEqual(filtered[0]["pubkey"], "clean_pubkey_64hex_def456")

    def test_blocked_event_suppression(self):
        """Specific event IDs listed in NodeContentTakedown are removed."""
        NodeContentTakedown.objects.create(
            event_id="takedown_event_64hex_999888",
            reason="ILLEGAL_CSAM",
        )
        invalidate_shield_cache()

        events = [
            {"id": "takedown_event_64hex_999888", "pubkey": "author_clean_1", "content": "illegal content"},
            {"id": "legit_event_64hex_111222", "pubkey": "author_clean_1", "content": "valid post"},
        ]
        filtered = filter_shielded_events(events)
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["id"], "legit_event_64hex_111222")

    def test_blocked_media_hash_suppression(self):
        """Events referencing suppressed SHA-256 hashes in x or ox tags are dropped."""
        NodeContentTakedown.objects.create(
            media_hash="bad_media_sha256_hash_777666",
            reason="MALWARE",
        )
        invalidate_shield_cache()

        events = [
            {
                "id": "ev_malware_media",
                "pubkey": "author_1",
                "content": "check this download",
                "tags": [["x", "bad_media_sha256_hash_777666"], ["m", "application/octet-stream"]],
            },
            {
                "id": "ev_clean_media",
                "pubkey": "author_2",
                "content": "clean image",
                "tags": [["x", "clean_media_sha256_hash_123456"], ["m", "image/png"]],
            },
            {
                "id": "ev_no_media",
                "pubkey": "author_3",
                "content": "just text",
                "tags": [],
            },
        ]
        filtered = filter_shielded_events(events)
        self.assertEqual(len(filtered), 2)
        filtered_ids = [ev["id"] for ev in filtered]
        self.assertNotIn("ev_malware_media", filtered_ids)
        self.assertIn("ev_clean_media", filtered_ids)
        self.assertIn("ev_no_media", filtered_ids)

    def test_filter_shielded_events_strips_blocked_entities_with_did(self):
        """Verify events with blocked author DID are stripped."""
        rosters = (
            {"did:key:z6mkbaduser123"},
            set(),
            set(),
        )
        events = [
            {"id": "ev1", "pubkey": "some_pubkey", "author_did": "did:key:z6mkbaduser123", "content": "bad did"},
            {"id": "ev2", "pubkey": "clean_pubkey", "content": "hello world"},
        ]

        filtered = filter_shielded_events(events, rosters=rosters)
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["id"], "ev2")

    def test_filter_shielded_events_preserves_clean_events(self):
        """Verify clean events pass through unchanged."""
        events = [
            {"id": "ev1", "pubkey": "alice", "content": "hi"},
            {"id": "ev2", "pubkey": "bob", "content": "there"},
        ]
        filtered = filter_shielded_events(events, rosters=(set(), set(), set()))
        self.assertEqual(len(filtered), 2)
        self.assertEqual(filtered, events)

    def test_is_event_shielded_helper(self):
        """Verify is_event_shielded returns boolean matching suppression rules."""
        rosters = (
            {"banned_author"},
            {"banned_event"},
            {"banned_media"},
        )
        self.assertTrue(is_event_shielded({"pubkey": "banned_author"}, rosters=rosters))
        self.assertTrue(is_event_shielded({"id": "banned_event"}, rosters=rosters))
        self.assertTrue(is_event_shielded({"tags": [["x", "banned_media"]]}, rosters=rosters))
        self.assertFalse(is_event_shielded({"id": "clean_id", "pubkey": "clean_author"}, rosters=rosters))

    @patch("apps.core.moderation.urllib.request.urlopen")
    def test_blossom_purge_handler(self, mock_urlopen):
        """Mock urllib.request.urlopen to test Blossom DELETE calls, verifying 200, 404, and network timeout handling."""
        # 1. Test 200 OK
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        res_200 = purge_blossom_blob("aabbcc200hash")
        self.assertTrue(res_200)
        req = mock_urlopen.call_args[0][0]
        self.assertEqual(req.method, "DELETE")
        self.assertEqual(req.full_url, "http://127.0.0.1:9002/aabbcc200hash")

        # 2. Test 404 Not Found (already scrubbed)
        mock_urlopen.side_effect = urllib.error.HTTPError(
            "http://127.0.0.1:9002/aabbcc404hash",
            404,
            "Not Found",
            {},
            None,
        )
        res_404 = purge_blossom_blob("aabbcc404hash")
        self.assertTrue(res_404)

        # 3. Test Network Timeout / URLError
        mock_urlopen.side_effect = urllib.error.URLError("Connection timed out")
        res_timeout = purge_blossom_blob("aabbcctimeouthash")
        self.assertFalse(res_timeout)

    def test_purge_blossom_blob_empty_hash(self):
        """Verify empty sha256_hex returns False."""
        self.assertFalse(purge_blossom_blob(""))
        self.assertFalse(purge_blossom_blob("   "))


class ModerationDeskViewTests(TestCase):
    def setUp(self):
        super().setUp()
        invalidate_shield_cache()
        self.User = get_user_model()
        self.staff_user = self.User.objects.create_user(
            username="did:key:z6MkAdminStaff",
            is_staff=True,
        )
        self.regular_user = self.User.objects.create_user(
            username="did:key:z6MkRegularUser",
            is_staff=False,
        )
        self.url = reverse("moderation_console")

    def tearDown(self):
        invalidate_shield_cache()
        super().tearDown()

    def test_admin_desk_permissions(self):
        """Non-staff/anonymous users receive 302 redirects; users with is_staff=True (elevated via ADMIN_DID) can view and POST takedowns."""
        # 1. Anonymous user GET -> 302 redirect to login
        anon_resp = self.client.get(self.url)
        self.assertEqual(anon_resp.status_code, 302)
        self.assertIn("oidc", anon_resp.url.lower())

        # 2. Non-staff user GET -> 302 redirect
        self.client.force_login(self.regular_user)
        non_staff_resp = self.client.get(self.url)
        self.assertEqual(non_staff_resp.status_code, 302)

        # 3. Staff user (ADMIN_DID elevated) GET -> 200 OK
        self.client.force_login(self.staff_user)
        staff_resp = self.client.get(self.url)
        self.assertEqual(staff_resp.status_code, 200)
        self.assertTemplateUsed(staff_resp, "admin/moderation_desk.html")

        # 4. Staff user POST takedown -> 302 redirect and record created
        post_resp = self.client.post(
            self.url,
            {
                "action": "takedown_event",
                "event_id": "event_id_taken_down_by_admin_12345",
                "reason": "ILLEGAL_CSAM",
            },
        )
        self.assertEqual(post_resp.status_code, 302)
        self.assertTrue(
            NodeContentTakedown.objects.filter(
                event_id="event_id_taken_down_by_admin_12345",
                reason="ILLEGAL_CSAM",
            ).exists()
        )

    def test_post_block_entity_creates_record_and_invalidates_cache(self):
        self.client.force_login(self.staff_user)
        cache.set(CACHE_KEY_BLOCKED_ENTITIES, {"some_cached_val"})

        resp = self.client.post(
            self.url,
            {
                "action": "block_entity",
                "entity_identifier": "did:key:z6MkBannedBot123",
                "reason": "SPAM_BOT",
                "notes": "Spam bot report #42",
            },
        )
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(
            NodeBlockedEntity.objects.filter(
                entity_identifier="did:key:z6MkBannedBot123",
                reason="SPAM_BOT",
                is_active=True,
            ).exists()
        )
        # Verify cache invalidated
        self.assertIsNone(cache.get(CACHE_KEY_BLOCKED_ENTITIES))

    def test_post_unblock_entity_revokes_block(self):
        self.client.force_login(self.staff_user)
        entity = NodeBlockedEntity.objects.create(
            entity_identifier="did:key:z6MkToUnblock",
            reason="HARASSMENT",
            is_active=True,
        )
        resp = self.client.post(
            self.url,
            {
                "action": "unblock_entity",
                "entity_id": entity.id,
            },
        )
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(NodeBlockedEntity.objects.filter(id=entity.id).exists())

    @patch("apps.core.views_admin.purge_blossom_blob")
    def test_post_purge_media_calls_blossom_and_records_takedown(self, mock_purge):
        mock_purge.return_value = True
        self.client.force_login(self.staff_user)
        resp = self.client.post(
            self.url,
            {
                "action": "purge_media",
                "media_hash": "deadbeef1234567890",
                "reason": "MALWARE",
            },
        )
        self.assertEqual(resp.status_code, 302)
        mock_purge.assert_called_once_with("deadbeef1234567890", blossom_host="http://127.0.0.1:9002")
        self.assertTrue(
            NodeContentTakedown.objects.filter(
                media_hash="deadbeef1234567890",
                purged_from_blossom=True,
            ).exists()
        )

    def test_context_limits_to_25_most_recent(self):
        self.client.force_login(self.staff_user)
        # Create 30 blocked entities
        for i in range(30):
            NodeBlockedEntity.objects.create(
                entity_identifier=f"entity_{i:03d}",
                reason="ADMIN_OVERRIDE",
            )
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.context["blocked_entities"]), 25)

    @patch("apps.core.views.PolyClient.cast_vote")
    def test_poly_vote_enfranchisement_preserved(self, mock_cast_vote):
        """Ensure quarantined DIDs can still cast votes via /api/vote/."""
        mock_cast_vote.return_value = {"receipt": "receipt_tx_poly_999888"}

        quarantined_did = "did:key:z6MkQuarantinedCitizen123"
        quarantined_user = self.User.objects.create_user(
            username=quarantined_did,
            is_staff=False,
        )

        # Quarantined in social feed suppression list
        NodeBlockedEntity.objects.create(
            entity_identifier=quarantined_did,
            reason="HARASSMENT",
            is_active=True,
        )
        invalidate_shield_cache()

        # Verify they are shielded on social feeds
        self.assertTrue(is_event_shielded({"pubkey": "some_pk", "author_did": quarantined_did}))

        # But when casting a civic ballot via /api/vote/
        self.client.force_login(quarantined_user)
        vote_payload = {
            "voter_did": quarantined_did,
            "signature": "valid_mock_signature_hex",
            "vote_envelope": {
                "poll_id": "referendum_prop_42",
                "choice": "AYE",
            },
        }
        vote_resp = self.client.post(
            "/api/vote/",
            data=json.dumps(vote_payload),
            content_type="application/json",
        )
        self.assertEqual(vote_resp.status_code, 200)
        data = vote_resp.json()
        self.assertTrue(data.get("valid"))
        self.assertEqual(data.get("receipt"), "receipt_tx_poly_999888")
        mock_cast_vote.assert_called_once()
