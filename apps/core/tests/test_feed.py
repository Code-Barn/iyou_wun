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

from datetime import datetime
from unittest.mock import patch

from django.test import TestCase

from ..views import process_into_feed
from .helpers import make_event, VALID_PUBKEY_HEX


class ProcessIntoFeedTest(TestCase):
    """process_into_feed must never crash and must correctly structure events."""

    def setUp(self):
        self.pk = VALID_PUBKEY_HEX

    def test_empty_events_returns_empty_list(self):
        result = process_into_feed({})
        self.assertEqual(result, [])

    def test_empty_events_with_max_items_zero(self):
        result = process_into_feed({}, max_items=0)
        self.assertEqual(result, [])

    def test_kind_1_appears_in_feed(self):
        events = {"e1": make_event("e1", 1, content="hello world")}
        result = process_into_feed(events)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], "e1")
        self.assertEqual(result[0]["content"], "hello world")
        self.assertEqual(result[0]["reactions"], [])
        self.assertEqual(result[0]["comments"], [])

    def test_kind_1063_has_media_fields(self):
        events = {
            "e1": make_event("e1", 1063, tags=[
                ["url", "http://127.0.0.1:9000/img.png"],
                ["m", "image/png"],
                ["dim", "800x600"],
                ["thumb", "http://127.0.0.1:9000/thumb.png"],
                ["alt", "example image"],
            ])
        }
        result = process_into_feed(events)
        self.assertEqual(len(result), 1)
        item = result[0]
        self.assertEqual(item["file_url"], "http://127.0.0.1:9000/img.png")
        self.assertEqual(item["mime_type"], "image/png")
        self.assertEqual(item["dimensions"], "800x600")
        self.assertEqual(item["thumbnail_url"], "http://127.0.0.1:9000/thumb.png")
        self.assertEqual(item["alt_text"], "example image")

    def test_kind_1063_sovereign_flag_sets_true_for_127_0_0_1(self):
        events = {
            "e1": make_event("e1", 1063, tags=[
                ["url", "http://127.0.0.1:9000/img.png"],
            ])
        }
        result = process_into_feed(events)
        self.assertTrue(result[0]["is_sovereign"])

    def test_kind_1063_sovereign_flag_false_for_external_url(self):
        events = {
            "e1": make_event("e1", 1063, tags=[
                ["url", "https://cdn.example.com/img.png"],
            ])
        }
        result = process_into_feed(events)
        self.assertFalse(result[0]["is_sovereign"])

    def test_kind_1063_sovereign_flag_false_no_url(self):
        events = {"e1": make_event("e1", 1063)}
        result = process_into_feed(events)
        self.assertFalse(result[0]["is_sovereign"])

    def test_reaction_grouped_under_parent(self):
        events = {
            "parent": make_event("parent", 1),
            "r1": make_event("r1", 7, tags=[["e", "parent"]]),
        }
        result = process_into_feed(events)
        self.assertEqual(len(result), 1)
        self.assertEqual(len(result[0]["reactions"]), 1)
        self.assertEqual(result[0]["reactions"][0]["id"], "r1")

    def test_reaction_without_parent_dropped(self):
        events = {
            "r1": make_event("r1", 7, tags=[["e", "nonexistent_parent"]]),
            "parent": make_event("parent", 1),
        }
        result = process_into_feed(events)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], "parent")
        self.assertEqual(len(result[0]["reactions"]), 0)

    def test_orphan_comment_preserved(self):
        events = {
            "c1": make_event("c1", 1111, content="orphan comment", tags=[["e", "nonexistent_parent"]]),
        }
        result = process_into_feed(events)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], "c1")
        self.assertEqual(result[0]["content"], "orphan comment")

    def test_comment_grouped_under_parent(self):
        events = {
            "parent": make_event("parent", 1),
            "c1": make_event("c1", 1111, content="comment", tags=[["e", "parent"]]),
        }
        result = process_into_feed(events)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], "parent")
        self.assertEqual(len(result[0]["comments"]), 1)
        self.assertEqual(result[0]["comments"][0]["id"], "c1")

    def test_reaction_dedup_by_pubkey(self):
        events = {
            "parent": make_event("parent", 1),
            "r1": make_event("r1", 7, tags=[["e", "parent"]]),
            "r2": make_event("r2", 7, pubkey=VALID_PUBKEY_HEX, tags=[["e", "parent"]]),
        }
        result = process_into_feed(events)
        self.assertEqual(len(result[0]["reactions"]), 1)

    def test_max_items_truncates_output(self):
        events = {
            f"e{i}": make_event(f"e{i}", 1, created_at=1000000 + i)
            for i in range(10)
        }
        result = process_into_feed(events, max_items=3)
        self.assertEqual(len(result), 3)

    def test_events_sorted_by_created_at_desc(self):
        events = {
            "old": make_event("old", 1, created_at=100),
            "mid": make_event("mid", 1, created_at=200),
            "new": make_event("new", 1, created_at=300),
        }
        result = process_into_feed(events, max_items=10)
        self.assertEqual(result[0]["id"], "new")
        self.assertEqual(result[1]["id"], "mid")
        self.assertEqual(result[2]["id"], "old")

    def test_profile_enrichment_sets_author_name_and_avatar(self):
        events = {"e1": make_event("e1", 1)}
        profiles = {
            VALID_PUBKEY_HEX: {
                "display_name": "Alice",
                "name": "alice",
                "picture": "http://example.com/avatar.png",
            }
        }
        result = process_into_feed(events, profiles=profiles)
        self.assertEqual(result[0]["author_name"], "Alice")
        self.assertEqual(result[0]["author_avatar"], "http://example.com/avatar.png")

    def test_profile_enrichment_falls_back_to_name(self):
        events = {"e1": make_event("e1", 1)}
        profiles = {
            VALID_PUBKEY_HEX: {
                "name": "bob",
                "picture": "",
            }
        }
        result = process_into_feed(events, profiles=profiles)
        self.assertEqual(result[0]["author_name"], "bob")

    def test_profile_enrichment_empty_when_no_profile(self):
        events = {"e1": make_event("e1", 1)}
        result = process_into_feed(events, profiles={})
        self.assertEqual(result[0]["author_name"], "")
        self.assertEqual(result[0]["author_avatar"], "")

    def test_none_profiles_does_not_crash(self):
        events = {"e1": make_event("e1", 1)}
        result = process_into_feed(events, profiles=None)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["author_name"], "")

    def test_malformed_missing_pubkey(self):
        events = {"e1": {"id": "e1", "kind": 1, "content": "no pubkey", "tags": [], "created_at": 1000}}
        result = process_into_feed(events)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["pubkey"], "")

    def test_missing_tags_field_does_not_crash(self):
        events = {"e1": {"id": "e1", "kind": 1, "pubkey": self.pk, "content": "no tags", "created_at": 1000}}
        result = process_into_feed(events)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["tags"], [])

    def test_kind_0_profile_events_ignored(self):
        events = {
            "note": make_event("note", 1, content="real note"),
            "profile": make_event("profile", 0, content='{"name":"test"}'),
        }
        result = process_into_feed(events)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], "note")

    def test_kind_7_with_multiple_parents(self):
        events = {
            "p1": make_event("p1", 1, content="parent one"),
            "p2": make_event("p2", 1063, tags=[["url", "http://example.com/img.png"]]),
            "r1": make_event("r1", 7, tags=[["e", "p1"]]),
            "r2": make_event("r2", 7, tags=[["e", "p2"]]),
        }
        result = process_into_feed(events)
        self.assertEqual(len(result), 2)
        p1 = next(i for i in result if i["id"] == "p1")
        p2 = next(i for i in result if i["id"] == "p2")
        self.assertEqual(len(p1["reactions"]), 1)
        self.assertEqual(len(p2["reactions"]), 1)
        self.assertEqual(p1["reactions"][0]["id"], "r1")
        self.assertEqual(p2["reactions"][0]["id"], "r2")

    def test_mixed_kinds_includes_kind_1_1063_and_orphan_1111(self):
        events = {
            "note": make_event("note", 1, content="text note"),
            "media": make_event("media", 1063, tags=[["url", "http://example.com/img.png"]]),
            "orphan": make_event("orphan", 1111, content="orphan", tags=[["e", "missing"]]),
        }
        result = process_into_feed(events)
        ids = {i["id"] for i in result}
        self.assertEqual(ids, {"note", "media", "orphan"})

    def test_npub_field_is_populated(self):
        events = {"e1": make_event("e1", 1)}
        result = process_into_feed(events)
        self.assertIn("npub", result[0])
        self.assertIsInstance(result[0]["npub"], str)
        self.assertTrue(len(result[0]["npub"]) > 0)
