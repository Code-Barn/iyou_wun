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

import urllib.error
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import TestCase

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

    def test_filter_shielded_events_strips_blocked_entities(self):
        """Verify events with blocked author pubkey or DID are stripped."""
        rosters = (
            {"bad_pubkey_123", "did:key:z6mkbaduser123"},
            set(),
            set(),
        )
        events = [
            {"id": "ev1", "pubkey": "bad_pubkey_123", "content": "spam"},
            {"id": "ev2", "pubkey": "good_pubkey_456", "content": "hello world"},
            {"id": "ev3", "pubkey": "other_pubkey", "author_did": "did:key:z6mkbaduser123", "content": "bad did"},
        ]

        filtered = filter_shielded_events(events, rosters=rosters)
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["id"], "ev2")

    def test_filter_shielded_events_strips_blocked_events(self):
        """Verify events with blocked event id are stripped."""
        rosters = (
            set(),
            {"blocked_ev_id_999"},
            set(),
        )
        events = [
            {"id": "blocked_ev_id_999", "pubkey": "author1", "content": "bad"},
            {"id": "allowed_ev_id_100", "pubkey": "author1", "content": "good"},
        ]

        filtered = filter_shielded_events(events, rosters=rosters)
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["id"], "allowed_ev_id_100")

    def test_filter_shielded_events_strips_blocked_media_tags(self):
        """Verify events with x or ox tags matching blocked media are stripped."""
        rosters = (
            set(),
            set(),
            {"bad_media_hash_abc"},
        )
        events = [
            {
                "id": "ev_x_tag",
                "pubkey": "author1",
                "content": "image 1",
                "tags": [["x", "bad_media_hash_abc"], ["m", "image/png"]],
            },
            {
                "id": "ev_ox_tag",
                "pubkey": "author2",
                "content": "image 2",
                "tags": [["ox", "bad_media_hash_abc"]],
            },
            {
                "id": "ev_clean_media",
                "pubkey": "author3",
                "content": "clean image",
                "tags": [["x", "clean_hash_xyz"]],
            },
        ]

        filtered = filter_shielded_events(events, rosters=rosters)
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["id"], "ev_clean_media")

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
    def test_purge_blossom_blob_success_200(self, mock_urlopen):
        """Verify purge_blossom_blob issues DELETE to port 9002 and succeeds on 200/204."""
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        result = purge_blossom_blob("aabbcc112233")
        self.assertTrue(result)

        # Check call args
        req = mock_urlopen.call_args[0][0]
        self.assertEqual(req.method, "DELETE")
        self.assertEqual(req.full_url, "http://127.0.0.1:9002/aabbcc112233")

    @patch("apps.core.moderation.urllib.request.urlopen")
    def test_purge_blossom_blob_success_404_already_purged(self, mock_urlopen):
        """Verify HTTP 404 (already purged) is treated as success."""
        mock_urlopen.side_effect = urllib.error.HTTPError(
            "http://127.0.0.1:9002/aabbcc112233",
            404,
            "Not Found",
            {},
            None,
        )
        result = purge_blossom_blob("aabbcc112233")
        self.assertTrue(result)

    @patch("apps.core.moderation.urllib.request.urlopen")
    def test_purge_blossom_blob_failure_500(self, mock_urlopen):
        """Verify HTTP 500 returns False without unhandled exceptions."""
        mock_urlopen.side_effect = urllib.error.HTTPError(
            "http://127.0.0.1:9002/aabbcc112233",
            500,
            "Internal Server Error",
            {},
            None,
        )
        result = purge_blossom_blob("aabbcc112233")
        self.assertFalse(result)

    @patch("apps.core.moderation.urllib.request.urlopen")
    def test_purge_blossom_blob_network_error(self, mock_urlopen):
        """Verify network connection errors return False without unhandled exceptions."""
        mock_urlopen.side_effect = urllib.error.URLError("Connection refused")
        result = purge_blossom_blob("aabbcc112233")
        self.assertFalse(result)

    def test_purge_blossom_blob_empty_hash(self):
        """Verify empty sha256_hex returns False."""
        self.assertFalse(purge_blossom_blob(""))
        self.assertFalse(purge_blossom_blob("   "))
