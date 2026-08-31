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


from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

from ..views import process_into_feed
from .helpers import make_event, VALID_PUBKEY_HEX



class ProcessIntoFeedTest(TestCase):
    """process_into_feed must never crash and must correctly structure events.

    process_into_feed returns a dict: {"roots": [...], "replies": {...}, ...}
    All tests access result["roots"] for the root-level feed list.
    """

    def setUp(self):
        self.pk = VALID_PUBKEY_HEX

    def _roots(self, events, **kwargs):
        """Helper: call process_into_feed and return the roots list."""
        return process_into_feed(events, **kwargs)["roots"]

    def test_empty_events_returns_empty_roots(self):
        result = process_into_feed({})
        self.assertEqual(result["roots"], [])

    def test_empty_events_with_max_items_zero(self):
        result = process_into_feed({}, max_items=0)
        self.assertEqual(result["roots"], [])

    def test_kind_1_appears_in_feed(self):
        events = {"e1": make_event("e1", 1, content="hello world")}
        roots = self._roots(events)
        self.assertEqual(len(roots), 1)
        self.assertEqual(roots[0]["id"], "e1")
        self.assertEqual(roots[0]["content"], "hello world")
        self.assertEqual(roots[0]["reactions"], [])
        self.assertEqual(roots[0]["replies"], [])

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
        roots = self._roots(events)
        self.assertEqual(len(roots), 1)
        item = roots[0]
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
        roots = self._roots(events)
        self.assertTrue(roots[0]["is_sovereign"])

    def test_kind_1063_sovereign_flag_false_for_external_url(self):
        events = {
            "e1": make_event("e1", 1063, tags=[
                ["url", "https://cdn.example.com/img.png"],
            ])
        }
        roots = self._roots(events)
        self.assertFalse(roots[0]["is_sovereign"])

    def test_kind_1063_sovereign_flag_false_no_url(self):
        events = {"e1": make_event("e1", 1063)}
        roots = self._roots(events)
        self.assertFalse(roots[0]["is_sovereign"])

    def test_reaction_grouped_under_parent(self):
        events = {
            "parent": make_event("parent", 1),
            "r1": make_event("r1", 7, tags=[["e", "parent"]]),
        }
        roots = self._roots(events)
        self.assertEqual(len(roots), 1)
        self.assertEqual(len(roots[0]["reactions"]), 1)
        self.assertEqual(roots[0]["reactions"][0]["id"], "r1")

    def test_reaction_without_parent_dropped(self):
        events = {
            "r1": make_event("r1", 7, tags=[["e", "nonexistent_parent"]]),
            "parent": make_event("parent", 1),
        }
        roots = self._roots(events)
        self.assertEqual(len(roots), 1)
        self.assertEqual(roots[0]["id"], "parent")
        self.assertEqual(len(roots[0]["reactions"]), 0)

    def test_reply_grouped_under_parent(self):
        events = {
            "parent": make_event("parent", 1),
            "c1": make_event("c1", 1111, content="reply", tags=[["e", "parent", "reply"]]),
        }
        result = process_into_feed(events)
        self.assertEqual(len(result["roots"]), 1)
        self.assertEqual(result["roots"][0]["id"], "parent")
        self.assertEqual(len(result["roots"][0]["replies"]), 1)
        self.assertEqual(result["roots"][0]["replies"][0]["id"], "c1")

    def test_orphan_reply_still_appears_as_root(self):
        events = {
            "c1": make_event("c1", 1111, content="orphan comment", tags=[["e", "nonexistent_parent"]]),
        }
        result = process_into_feed(events)
        # Orphan Kind 1111 should appear as a root
        self.assertTrue(len(result["roots"]) >= 1)
        ids = {r["id"] for r in result["roots"]}
        self.assertIn("c1", ids)

    def test_reaction_dedup_by_pubkey(self):
        events = {
            "parent": make_event("parent", 1),
            "r1": make_event("r1", 7, tags=[["e", "parent"]]),
            "r2": make_event("r2", 7, pubkey=VALID_PUBKEY_HEX, tags=[["e", "parent"]]),
        }
        roots = self._roots(events)
        self.assertEqual(len(roots[0]["reactions"]), 1)

    def test_max_items_truncates_output(self):
        events = {
            f"e{i}": make_event(f"e{i}", 1, created_at=1000000 + i)
            for i in range(10)
        }
        roots = self._roots(events, max_items=3)
        self.assertEqual(len(roots), 3)

    def test_events_sorted_by_created_at_desc(self):
        events = {
            "old": make_event("old", 1, created_at=100),
            "mid": make_event("mid", 1, created_at=200),
            "new": make_event("new", 1, created_at=300),
        }
        roots = self._roots(events, max_items=10)
        self.assertEqual(roots[0]["id"], "new")
        self.assertEqual(roots[1]["id"], "mid")
        self.assertEqual(roots[2]["id"], "old")

    def test_profile_enrichment_sets_author_name_and_avatar(self):
        events = {"e1": make_event("e1", 1)}
        profiles = {
            VALID_PUBKEY_HEX: {
                "display_name": "Alice",
                "name": "alice",
                "picture": "http://example.com/avatar.png",
            }
        }
        roots = self._roots(events, profiles=profiles)
        self.assertEqual(roots[0]["author_name"], "Alice")
        self.assertEqual(roots[0]["author_avatar"], "https://example.com/avatar.png")


    def test_profile_enrichment_falls_back_to_name(self):
        events = {"e1": make_event("e1", 1)}
        profiles = {
            VALID_PUBKEY_HEX: {
                "name": "bob",
                "picture": "",
            }
        }
        roots = self._roots(events, profiles=profiles)
        self.assertEqual(roots[0]["author_name"], "bob")

    def test_profile_enrichment_empty_when_no_profile(self):
        events = {"e1": make_event("e1", 1)}
        roots = self._roots(events, profiles={})
        self.assertEqual(roots[0]["author_name"], "")
        self.assertEqual(roots[0]["author_avatar"], "")

    def test_none_profiles_does_not_crash(self):
        events = {"e1": make_event("e1", 1)}
        roots = self._roots(events, profiles=None)
        self.assertEqual(len(roots), 1)
        self.assertEqual(roots[0]["author_name"], "")

    def test_malformed_missing_pubkey(self):
        events = {"e1": {"id": "e1", "kind": 1, "content": "no pubkey", "tags": [], "created_at": 1000}}
        roots = self._roots(events)
        self.assertEqual(len(roots), 1)
        self.assertEqual(roots[0]["pubkey"], "")

    def test_missing_tags_field_does_not_crash(self):
        events = {"e1": {"id": "e1", "kind": 1, "pubkey": self.pk, "content": "no tags", "created_at": 1000}}
        roots = self._roots(events)
        self.assertEqual(len(roots), 1)
        self.assertEqual(roots[0]["tags"], [])

    def test_kind_0_profile_events_ignored(self):
        events = {
            "note": make_event("note", 1, content="real note"),
            "profile": make_event("profile", 0, content='{"name":"test"}'),
        }
        roots = self._roots(events)
        self.assertEqual(len(roots), 1)
        self.assertEqual(roots[0]["id"], "note")

    def test_kind_7_with_multiple_parents(self):
        events = {
            "p1": make_event("p1", 1, content="parent one"),
            "p2": make_event("p2", 1063, tags=[["url", "http://example.com/img.png"]]),
            "r1": make_event("r1", 7, tags=[["e", "p1"]]),
            "r2": make_event("r2", 7, tags=[["e", "p2"]]),
        }
        roots = self._roots(events)
        self.assertEqual(len(roots), 2)
        p1 = next(i for i in roots if i["id"] == "p1")
        p2 = next(i for i in roots if i["id"] == "p2")
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
        ids = {i["id"] for i in result["roots"]}
        self.assertIn("note", ids)
        self.assertIn("media", ids)
        self.assertIn("orphan", ids)

    def test_npub_field_is_populated(self):
        events = {"e1": make_event("e1", 1)}
        roots = self._roots(events)
        self.assertIn("npub", roots[0])
        self.assertIsInstance(roots[0]["npub"], str)
        self.assertTrue(len(roots[0]["npub"]) > 0)

    # --- Poll governance tests (Kind 30023 / 1112) ---

    def test_kind_30023_appears_in_feed(self):
        events = {"poll": make_event("poll", 30023, content="Test Poll?")}
        roots = self._roots(events)
        self.assertEqual(len(roots), 1)
        self.assertEqual(roots[0]["id"], "poll")
        self.assertEqual(roots[0]["kind"], 30023)

    def test_kind_30023_extracts_poll_options(self):
        events = {
            "poll": make_event("poll", 30023, content="Favorite color?", tags=[
                ["option", "Red"],
                ["option", "Blue"],
                ["option", "Green"],
            ])
        }
        roots = self._roots(events)
        self.assertEqual(roots[0]["poll_options"], ["Red", "Blue", "Green"])

    def test_kind_30023_no_options_returns_empty_list(self):
        events = {"poll": make_event("poll", 30023, content="No options?")}
        roots = self._roots(events)
        self.assertEqual(roots[0]["poll_options"], [])

    def test_kind_30023_extracts_scope_tags(self):
        events = {
            "poll": make_event("poll", 30023, tags=[
                ["option", "Yes"],
                ["geohash", "9q8yy"],
                ["org", "iyou"],
                ["expires", "20261201"],
            ])
        }
        roots = self._roots(events)
        self.assertEqual(roots[0]["poll_scope_geohash"], "9q8yy")
        self.assertEqual(roots[0]["poll_scope_org"], "iyou")
        self.assertEqual(roots[0]["poll_closes_at"], "20261201")

    def test_kind_1112_vote_grouped_under_parent_poll(self):
        events = {
            "poll": make_event("poll", 30023, content="Test poll?", tags=[["option", "A"]]),
            "vote": make_event("vote", 1112, tags=[["e", "poll"]]),
        }
        roots = self._roots(events)
        self.assertEqual(len(roots), 1)
        self.assertEqual(roots[0]["id"], "poll")
        self.assertIn("votes", roots[0])
        self.assertEqual(len(roots[0]["votes"]), 1)
        self.assertEqual(roots[0]["votes"][0]["id"], "vote")

    def test_kind_1112_vote_dropped_without_parent(self):
        events = {
            "vote": make_event("vote", 1112, tags=[["e", "nonexistent"]]),
            "poll": make_event("poll", 30023, content="Real poll?", tags=[["option", "A"]]),
        }
        roots = self._roots(events)
        self.assertEqual(len(roots), 1)
        self.assertEqual(roots[0]["id"], "poll")
        self.assertEqual(roots[0].get("votes", []), [])

    def test_mixed_kinds_includes_poll(self):
        events = {
            "note": make_event("note", 1, content="text"),
            "poll": make_event("poll", 30023, content="Poll?", tags=[["option", "A"]]),
        }
        result = process_into_feed(events)
        ids = {i["id"] for i in result["roots"]}
        self.assertEqual(ids, {"note", "poll"})

    def test_external_relay_note_author_did_is_empty(self):
        external_pk = "32e1827635450ebb3c5a7d12c1f8e7b2b514439ac10a67eef3d9fd9c5c68e245"
        events = {"ext": make_event("ext", 1, pubkey=external_pk, content="external note")}
        roots = self._roots(events)
        self.assertEqual(roots[0]["author_did"], "")
        self.assertNotIn("did:iyou:", roots[0]["author_did"])

    def test_nip05_and_lud16_populated_from_profile(self):
        events = {"e1": make_event("e1", 1)}
        profiles = {
            VALID_PUBKEY_HEX: {
                "display_name": "JB",
                "nip05": "jb55@jb55.com",
                "lud16": "jb55@zbd.gg",
            }
        }
        roots = self._roots(events, profiles=profiles)
        self.assertEqual(roots[0]["nip05"], "jb55@jb55.com")
        self.assertEqual(roots[0]["lud16"], "jb55@zbd.gg")

    def test_sovereign_registered_user_resolves_author_did(self):
        from django.contrib.auth.models import User
        # User with a matching pubkey DID
        User.objects.create_user(username="did:key:z6MkuG2validuser", first_name="Sovereign")
        # In views.py, resolve_author_did will match when did_to_pubkey matches
        with patch("apps.core.views.did_to_pubkey", return_value=VALID_PUBKEY_HEX):
            events = {"e1": make_event("e1", 1, pubkey=VALID_PUBKEY_HEX)}
            roots = self._roots(events)
            self.assertEqual(roots[0]["author_did"], "did:key:z6MkuG2validuser")

    def test_nip10_thread_tree_preserves_parent_and_reply_to_metadata(self):
        from apps.core.nip10 import build_thread_tree

        parent_pk = "3bf0c63fcb93463407af97a5e5ee64fa883d107ef9e558472c4eb9aaaefa459d"
        raw_events = {
            "root_post": make_event("root_post", 1, pubkey=parent_pk, content="Root post content"),
            "reply_post": make_event("reply_post", 1111, pubkey=VALID_PUBKEY_HEX, content="Reply content", tags=[
                ["e", "root_post", "", "root"],
                ["e", "root_post", "", "reply"],
                ["p", parent_pk, "", "reply"],
            ]),
        }
        profiles = {
            parent_pk: {"display_name": "SovereignParent", "name": "parent"},
        }
        tree = build_thread_tree(raw_events, profiles=profiles)
        self.assertEqual(len(tree["roots"]), 1)
        root = tree["roots"][0]
        self.assertEqual(root["id"], "root_post")
        self.assertEqual(root["reply_count"], 1)
        self.assertEqual(len(root["replies"]), 1)

        reply = root["replies"][0]
        self.assertEqual(reply["id"], "reply_post")
        self.assertEqual(reply["parent_id"], "root_post")
        self.assertEqual(reply["root_id"], "root_post")
        self.assertEqual(reply["reply_to_pubkey"], parent_pk)
        self.assertEqual(reply["reply_to_name"], "SovereignParent")
        self.assertTrue(reply["reply_to_npub"].startswith("npub1"))

    def test_kind_1_with_reply_marker_recognized_as_reply(self):
        from apps.core.nip10 import build_thread_tree

        raw_events = {
            "root_note": make_event("root_note", 1, content="Top note"),
            "k1_reply": make_event("k1_reply", 1, content="Kind 1 reply", tags=[
                ["e", "root_note", "", "reply"],
            ]),
        }
        tree = build_thread_tree(raw_events)
        self.assertEqual(len(tree["roots"]), 1)
        root = tree["roots"][0]
        self.assertEqual(root["id"], "root_note")
        self.assertEqual(len(root["replies"]), 1)
        self.assertEqual(root["replies"][0]["id"], "k1_reply")
        self.assertEqual(root["replies"][0]["parent_id"], "root_note")

    def test_sanitize_media_url_upgrades_http_to_https(self):
        from apps.core.nip10 import sanitize_media_url

        self.assertEqual(sanitize_media_url("http://cdn.iyou.me/image.png"), "https://cdn.iyou.me/image.png")
        self.assertEqual(sanitize_media_url("https://cdn.iyou.me/image.png"), "https://cdn.iyou.me/image.png")
        # Localhost / 127.0.0.1 stays http
        self.assertEqual(sanitize_media_url("http://127.0.0.1:9003/blob"), "http://127.0.0.1:9003/blob")
        self.assertEqual(sanitize_media_url(""), "")

    def test_fetch_thread_hero_reconstruction_with_ancestors_and_direct_replies(self):
        from apps.core.views import fetch_thread

        parent_pk = "3bf0c63fcb93463407af97a5e5ee64fa883d107ef9e558472c4eb9aaaefa459d"
        hero_pk = "32e1827635450ebb3c5a7d12c1f8e7b2b514439ac10a67eef3d9fd9c5c68e245"
        child_pk = "0000000000000000000000000000000000000000000000000000000000000002"

        raw_events = {
            "grandparent": make_event("grandparent", 1, pubkey=parent_pk, content="Grandparent root"),
            "parent_post": make_event("parent_post", 1111, pubkey=parent_pk, content="Parent note", tags=[
                ["e", "grandparent", "", "root"],
                ["e", "grandparent", "", "reply"],
                ["p", parent_pk, "", "reply"],
            ]),
            "hero_note": make_event("hero_note", 1111, pubkey=hero_pk, content="Hero note being inspected", tags=[
                ["e", "grandparent", "", "root"],
                ["e", "parent_post", "", "reply"],
                ["p", parent_pk, "", "reply"],
            ]),
            "direct_child": make_event("direct_child", 1111, pubkey=child_pk, content="Direct child of hero", tags=[
                ["e", "grandparent", "", "root"],
                ["e", "hero_note", "", "reply"],
                ["p", hero_pk, "", "reply"],
            ]),
            "sub_child": make_event("sub_child", 1111, pubkey=child_pk, content="Sub-reply under direct child", tags=[
                ["e", "grandparent", "", "root"],
                ["e", "direct_child", "", "reply"],
                ["p", child_pk, "", "reply"],
            ]),
        }

        with patch("apps.core.views.relay_req", return_value=raw_events):
            result = fetch_thread("hero_note")

        hero = result["thread_root"]
        self.assertEqual(hero["id"], "hero_note")
        self.assertEqual(len(result["ancestors"]), 2)
        self.assertEqual(result["ancestors"][0]["id"], "grandparent")
        self.assertEqual(result["ancestors"][1]["id"], "parent_post")

        # Direct replies to hero
        self.assertEqual(len(hero["replies"]), 1)
        self.assertEqual(hero["replies"][0]["id"], "direct_child")
        # Sub-reply count under direct_child
        self.assertEqual(hero["replies"][0]["reply_count"], 1)

    def test_fetch_thread_resolves_multi_hop_ancestors(self):
        from apps.core.views import fetch_thread

        root_pk = "3bf0c63fcb93463407af97a5e5ee64fa883d107ef9e558472c4eb9aaaefa459d"
        g_pk = "32e1827635450ebb3c5a7d12c1f8e7b2b514439ac10a67eef3d9fd9c5c68e245"
        m_pk = "0000000000000000000000000000000000000000000000000000000000000002"
        t_pk = "1111111111111111111111111111111111111111111111111111111111111111"

        raw_events = {
            "root_post": make_event("root_post", 1, pubkey=root_pk, content="Root"),
            "grand_reply": make_event("grand_reply", 1111, pubkey=g_pk, content="Hop 1", tags=[
                ["e", "root_post", "", "root"],
                ["e", "root_post", "", "reply"],
                ["p", root_pk, "", "reply"],
            ]),
            "intermediate": make_event("intermediate", 1111, pubkey=m_pk, content="Hop 2", tags=[
                ["e", "root_post", "", "root"],
                ["e", "grand_reply", "", "reply"],
                ["p", g_pk, "", "reply"],
            ]),
            "deep_target": make_event("deep_target", 1111, pubkey=t_pk, content="Deep target", tags=[
                ["e", "root_post", "", "root"],
                ["e", "intermediate", "", "reply"],
                ["p", m_pk, "", "reply"],
            ]),
        }

        with patch("apps.core.views.relay_req", return_value=raw_events):
            result = fetch_thread("deep_target")

        self.assertEqual(result["thread_root"]["id"], "deep_target")
        self.assertEqual(
            [a["id"] for a in result["ancestors"]],
            ["root_post", "grand_reply", "intermediate"],
        )

    def test_kind_1_extracts_embedded_image_and_video_urls(self):
        from apps.core.nip10 import extract_media_from_note

        note = {
            "kind": 1,
            "content": "Check out this visual\nhttps://cdn.iyou.me/pic.png\nAnd video https://cdn.iyou.me/clip.mp4",
            "tags": [],
        }
        enriched = extract_media_from_note(note)
        attachments = enriched.get("media_attachments", [])
        self.assertEqual(len(attachments), 2)
        self.assertEqual(attachments[0]["type"], "image")
        self.assertEqual(attachments[0]["url"], "https://cdn.iyou.me/pic.png")
        self.assertEqual(attachments[1]["type"], "video")
        self.assertEqual(attachments[1]["url"], "https://cdn.iyou.me/clip.mp4")
        self.assertEqual(enriched["display_content"], "Check out this visual\nAnd video")

    def test_kind_1063_populates_media_attachments_from_nip94_tags(self):
        from apps.core.nip10 import extract_media_from_note

        note = {
            "kind": 1063,
            "content": "Blossom file upload",
            "tags": [
                ["url", "http://cdn.iyou.me/image.jpg"],
                ["m", "image/jpeg"],
                ["dim", "1920x1080"],
                ["thumb", "http://cdn.iyou.me/thumb.jpg"],
                ["alt", "Mountain landscape"],
                ["x", "abc123hash"],
            ],
        }
        enriched = extract_media_from_note(note)
        attachments = enriched.get("media_attachments", [])
        self.assertEqual(len(attachments), 1)
        self.assertEqual(attachments[0]["type"], "image")
        self.assertEqual(attachments[0]["url"], "https://cdn.iyou.me/image.jpg")
        self.assertEqual(attachments[0]["dim"], "1920x1080")
        self.assertEqual(attachments[0]["thumb"], "https://cdn.iyou.me/thumb.jpg")
        self.assertEqual(attachments[0]["alt"], "Mountain landscape")
        self.assertEqual(attachments[0]["hash"], "abc123hash")
        self.assertEqual(enriched["media_url"], "https://cdn.iyou.me/image.jpg")

    def test_process_into_feed_deduplicates_duplicate_event_ids(self):
        from apps.core.views import process_into_feed

        e1 = make_event("dup_1", 1, content="Original note", created_at=1700000000)
        e1_dup = make_event("dup_1", 1, content="Duplicate note copy", created_at=1700000000)
        e2 = make_event("dup_2", 1, content="Second note", created_at=1700000100)

        # Pass as list with duplicates
        raw_list = [e1, e1_dup, e2]
        feed = process_into_feed(raw_list)
        roots = feed["roots"]
        self.assertEqual(len(roots), 2)
        root_ids = [r["id"] for r in roots]
        self.assertEqual(len(root_ids), len(set(root_ids)))
        self.assertIn("dup_1", root_ids)
        self.assertIn("dup_2", root_ids)

    def test_build_thread_tree_deduplicates_duplicate_events_and_replies(self):
        from apps.core.nip10 import build_thread_tree

        root_ev = make_event("root_1", 1, content="Root post")
        reply_ev1 = make_event("reply_1", 1111, content="Reply", tags=[["e", "root_1", "", "reply"]])
        reply_ev1_dup = make_event("reply_1", 1111, content="Duplicate reply", tags=[["e", "root_1", "", "reply"]])

        raw_events = [root_ev, root_ev, reply_ev1, reply_ev1_dup]
        tree = build_thread_tree(raw_events)
        self.assertEqual(len(tree["roots"]), 1)
        self.assertEqual(tree["roots"][0]["id"], "root_1")
        self.assertEqual(len(tree["roots"][0]["replies"]), 1)
        self.assertEqual(tree["roots"][0]["replies"][0]["id"], "reply_1")

    def test_root_reply_counter_fallback_when_unset(self):
        from apps.core.nip10 import build_thread_tree
        from apps.core.views import process_into_feed

        root_ev = make_event("root_rep_1", 1, content="Root post")
        reply_1 = make_event("reply_rep_1", 1111, content="Reply 1", tags=[["e", "root_rep_1", "", "reply"]])
        reply_2 = make_event("reply_rep_2", 1111, content="Reply 2", tags=[["e", "root_rep_1", "", "reply"]])

        tree = build_thread_tree([root_ev, reply_1, reply_2])
        self.assertEqual(tree["roots"][0]["reply_count"], 2)

        feed = process_into_feed([root_ev, reply_1, reply_2])
        self.assertEqual(feed["roots"][0]["reply_count"], 2)

    def test_attach_reply_counts_tallies_e_tags_accurately(self):
        from apps.core.views import attach_reply_counts

        notes = [
            {"id": "note_alpha", "content": "Root A", "replies": []},
            {"id": "note_beta", "content": "Root B", "replies": []},
            {"id": "note_gamma", "content": "Root C", "replies": []},
        ]

        reply_events = {
            "rep_1": make_event("rep_1", 1, content="reply to alpha", tags=[["e", "note_alpha"]]),
            "rep_2": make_event("rep_2", 1111, content="another reply to alpha", tags=[["e", "note_alpha"]]),
            "rep_3": make_event("rep_3", 1, content="reply to beta", tags=[["e", "note_beta"]]),
        }

        with patch("apps.core.views.relay_req", return_value=reply_events):
            result = attach_reply_counts(notes)

        self.assertEqual(result[0]["reply_count"], 2)
        self.assertEqual(result[1]["reply_count"], 1)
        self.assertEqual(result[2]["reply_count"], 0)


    def test_attach_reaction_counts_tallies_kind_7_accurately(self):
        from apps.core.views import attach_reaction_counts

        notes = [
            {"id": "note_alpha", "content": "Root A"},
            {"id": "note_beta", "content": "Root B"},
            {"id": "note_gamma", "content": "Root C"},
        ]

        reaction_events = {
            "like_1": make_event("like_1", 7, content="+", tags=[["e", "note_alpha"]]),
            "like_2": make_event("like_2", 7, content="❤️", tags=[["e", "note_alpha"]]),
            "like_3": make_event("like_3", 7, content="", tags=[["e", "note_beta"]]),
            "dislike_1": make_event("dislike_1", 7, content="-", tags=[["e", "note_alpha"]]),
            "like_other": make_event("like_other", 7, content="+", tags=[["e", "note_unknown"]]),
        }

        with patch("apps.core.views.relay_req", return_value=reaction_events):
            result = attach_reaction_counts(notes)

        self.assertEqual(result[0]["like_count"], 2)
        self.assertEqual(result[1]["like_count"], 1)
        self.assertEqual(result[2]["like_count"], 0)


    def test_attach_reaction_counts_respects_existing_like_count(self):
        from apps.core.views import attach_reaction_counts

        notes = [{"id": "note_a", "content": "Root A", "like_count": 5}]
        reaction_events = {
            "like_1": make_event("like_1", 7, content="+", tags=[["e", "note_a"]]),
        }

        with patch("apps.core.views.relay_req", return_value=reaction_events):
            result = attach_reaction_counts(notes)

        self.assertEqual(result[0]["like_count"], 5)

    def test_attach_reaction_counts_empty_notes_returns_unchanged(self):
        from apps.core.views import attach_reaction_counts

        with patch("apps.core.views.relay_req", return_value={}) as mock_req:
            result = attach_reaction_counts([])
        self.assertEqual(result, [])
        mock_req.assert_not_called()


class RelayPoolAndFailoverTests(TestCase):
    """Tests for dynamic relay pooling, autonomous failover, and NIP-65 ingestion."""

    def test_relay_req_failover_when_primary_fails(self):
        from apps.core.views import relay_req

        events_fallback = {"e1": make_event("e1", 1, content="Recovered via fallback relay")}

        def mock_connect(relay_url, sub_id, filter_obj, timeout):
            if "relay.iyou.me" in relay_url:
                raise ConnectionError("Primary upstream down")
            return events_fallback

        with patch("apps.core.views._connect_relay", side_effect=mock_connect):
            result = relay_req(
                {"kinds": [1]},
                relay_urls=["wss://relay.iyou.me", "wss://nos.lol"]
            )

        self.assertEqual(result, events_fallback)

    def test_relay_req_returns_empty_dict_if_all_fail(self):
        from apps.core.views import relay_req

        def mock_connect(relay_url, sub_id, filter_obj, timeout):
            raise TimeoutError("All relays unreachable")

        with patch("apps.core.views._connect_relay", side_effect=mock_connect):
            result = relay_req(
                {"kinds": [1]},
                relay_urls=["wss://relay.iyou.me", "wss://relay.damus.io"]
            )

        self.assertEqual(result, {})

    def test_fetch_user_nip65_relays_parsing(self):
        from apps.core.views import fetch_user_nip65_relays

        nip65_event = make_event(
            "nip65_1",
            10002,
            pubkey="test_pk",
            tags=[
                ["r", "wss://relay.damus.io", "read"],
                ["r", "wss://relay.primal.net", "write"],
                ["r", "wss://nos.lol"],
            ]
        )

        with patch("apps.core.views.relay_req", return_value={"nip65_1": nip65_event}):
            res = fetch_user_nip65_relays("test_pk")

        self.assertIn("wss://relay.damus.io", res["read"])
        self.assertNotIn("wss://relay.damus.io", res["write"])

        self.assertIn("wss://relay.primal.net", res["write"])
        self.assertNotIn("wss://relay.primal.net", res["read"])

        self.assertIn("wss://nos.lol", res["read"])
        self.assertIn("wss://nos.lol", res["write"])

        self.assertEqual(len(res["all"]), 3)

    def test_fetch_user_nip65_relays_empty_pubkey(self):
        from apps.core.views import fetch_user_nip65_relays

        res = fetch_user_nip65_relays("")
        self.assertEqual(res, {"read": [], "write": [], "all": []})

    def test_fetch_unified_feed_handles_relay_outage_gracefully(self):
        from apps.core.views import fetch_unified_feed

        with patch("apps.core.views.relay_req", return_value={}):
            feed = fetch_unified_feed()

        self.assertEqual(feed["roots"], [])
        self.assertEqual(feed["total_replies"], 0)


class FeedRelayHealthWidgetLayoutTest(TestCase):
    """Relay health indicator relocation contract.

    The mesh status widget lives at the top of the discovery rail
    (`templates/includes/_feed_right_rail.html`) in main feed mode — it must
    no longer render above the top post composer.
    """

    def _get_feed(self):
        with patch("apps.core.views.relay_req", return_value={}):
            return self.client.get(reverse("feed"))

    def test_feed_renders_relay_health_widget_in_discovery_rail(self):
        response = self._get_feed()
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="relay-health-widget"')
        self.assertContains(response, "TRENDING TOPICS")

    def test_feed_composer_has_no_relay_health_indicator_above_it(self):
        response = self._get_feed()
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="relay-health-widget"')
        self.assertNotContains(response, 'id="relay-health-indicator"')
        self.assertNotContains(response, 'id="relay-health-dot"')
        self.assertNotContains(response, 'id="relay-health-text"')


class FeedSanitizerTests(TestCase):
    """Heuristic noise / NIP-36 content-warning sanitizer contract."""

    def test_machine_noise_events_dropped_from_feed(self):
        clean = make_event("clean_card", 1, content="Just a friendly note from the grid")
        json_noise = make_event("noise_json", 1, content='{"device":"sensor-7","ts":1700000000,"payload":{"temp":22.4}}')
        trace_noise = make_event(
            "noise_trace",
            1,
            content='Traceback (most recent call last):\n  File "main.py", line 4, in <module>\n    boom()',
        )
        hex_noise = make_event("noise_hex", 1, content="a3b7" * 60)
        b64_noise = make_event("noise_b64", 1, content="U29tZSBiaW5hcnkgYmxvYiBkYXRhIGhlcmUgdGhhdCBpcyBxdWl0ZSBsb25nIGFuZCBuZWVkcyBwYXJzaW5nIGNhcmVmdWxseTk4ODc2NTQzMjE=")

        feed = process_into_feed(
            {
                "clean_card": clean,
                "noise_json": json_noise,
                "noise_trace": trace_noise,
                "noise_hex": hex_noise,
                "noise_b64": b64_noise,
            }
        )

        roots = feed["roots"]
        self.assertEqual(len(roots), 1)
        self.assertEqual(roots[0]["id"], "clean_card")

    def test_roster_telemetry_and_hex_dumps_dropped_as_noise(self):
        clean_note = make_event("clean_human", 1, content="Hello mesh peers, welcome to iyou_wun!")
        roster_note1 = make_event("roster_1", 1, content='{"channel:__roster": ["3bf0c63fcb93463407af97a5e5ee64fa883d107ef9e558472c4eb9aaaefa459d"]}')
        roster_note2 = make_event("roster_2", 1, content="channel:__roster telemetry ping active")
        hex_unbroken = make_event("hex_dump_128", 1, content="a" * 128)
        repeated_hex = make_event(
            "hex_repeated_64",
            1,
            content="3bf0c63fcb93463407af97a5e5ee64fa883d107ef9e558472c4eb9aaaefa459d\n32e1827635450ebb3c5a7d12c1f8e7b2b514439ac10a67eef3d9fd9c5c68e245\n0000000000000000000000000000000000000000000000000000000000000001",
        )

        feed = process_into_feed(
            {
                "clean_human": clean_note,
                "roster_1": roster_note1,
                "roster_2": roster_note2,
                "hex_dump_128": hex_unbroken,
                "hex_repeated_64": repeated_hex,
            }
        )

        roots = feed["roots"]
        self.assertEqual(len(roots), 1)
        self.assertEqual(roots[0]["id"], "clean_human")

    def test_nip36_content_warning_flags_and_reasons_parsed(self):
        tagged_with_reason = make_event(
            "cw_1",
            1,
            content="Medical imagery ahead",
            tags=[["content-warning", "Medical imagery"]],
        )
        tagged_no_reason = make_event("cw_2", 1, content="risky post", tags=[["content-warning"]])
        marker_note = make_event("cw_3", 1, content="check this out #nsfw link hero")
        french_note = make_event("cw_4", 1, content="Bonjour le monde", tags=[["lang", "fr"]])

        feed = process_into_feed(
            {
                "cw_1": tagged_with_reason,
                "cw_2": tagged_no_reason,
                "cw_3": marker_note,
                "cw_4": french_note,
            }
        )

        by_id = {r["id"]: r for r in feed["roots"]}

        self.assertTrue(by_id["cw_1"]["has_content_warning"])
        self.assertEqual(by_id["cw_1"]["warning_reason"], "Medical imagery")

        self.assertTrue(by_id["cw_2"]["has_content_warning"])
        self.assertEqual(by_id["cw_2"]["warning_reason"], "Sensitive Content")

        self.assertTrue(by_id["cw_3"]["has_content_warning"])
        self.assertEqual(by_id["cw_3"]["warning_reason"], "Sensitive Content")

        self.assertFalse(by_id["cw_4"]["has_content_warning"])
        self.assertFalse(by_id["cw_4"]["warning_reason"])
        self.assertEqual(by_id["cw_4"]["lang"], "fr")

    def test_sanitize_defaults_lang_to_en(self):
        from apps.core.nip10 import sanitize_event_content

        result = sanitize_event_content(make_event("plain", 1, content="plain note"))
        self.assertTrue(result["is_valid"])
        self.assertEqual(result["lang"], "en")
        self.assertFalse(result["has_content_warning"])

    def test_detect_language_parses_tags_and_heuristics(self):
        from apps.core.nip10 import detect_language

        # 1. NIP-01 explicit tag
        tagged_de = {"tags": [["lang", "de"]], "content": "Guten Morgen"}
        self.assertEqual(detect_language(tagged_de), "de")

        tagged_es_regional = {"tags": [["lang", "es-MX"]], "content": "Hola amigos"}
        self.assertEqual(detect_language(tagged_es_regional), "es")

        # 2. Japanese kana heuristic
        ja_note = {"tags": [], "content": "こんにちは、ノストラ！"}
        self.assertEqual(detect_language(ja_note), "ja")

        # 3. Chinese Han characters heuristic
        zh_note = {"tags": [], "content": "去中心化网络开发"}
        self.assertEqual(detect_language(zh_note), "zh")

        # 4. Cyrillic heuristic
        ru_note = {"tags": [], "content": "Привет, суверенная сеть!"}
        self.assertEqual(detect_language(ru_note), "ru")

        # 5. Arabic heuristic
        ar_note = {"tags": [], "content": "مرحبا بكم في شبكة نوستر"}
        self.assertEqual(detect_language(ar_note), "ar")

        # 6. Spanish markers in Latin prose
        es_note1 = {"tags": [], "content": "¡Hola! ¿Cómo estás hoy en la red?"}
        self.assertEqual(detect_language(es_note1), "es")
        es_note2 = {"tags": [], "content": "Muchas gracias por el apoyo sovereign"}
        self.assertEqual(detect_language(es_note2), "es")

        # 7. Default English Latin prose
        en_note = {"tags": [], "content": "Decentralized mesh networks empower digital sovereignty."}
        self.assertEqual(detect_language(en_note), "en")


class AttachSocialCountsTests(TestCase):
    """Unified batch social-counts (replies, reposts, reactions) contract."""

    def test_attach_social_counts_tallies_kind7_reactions_and_kind1_replies(self):
        from apps.core.views import attach_social_counts

        notes = [
            {"id": "root_a", "content": "Root A", "replies": []},
            {"id": "root_b", "content": "Root B", "replies": []},
        ]

        events = {
            "like_1": make_event("like_1", 7, content="+", tags=[["e", "root_a"]]),
            "like_2": make_event("like_2", 7, content="❤️", tags=[["e", "root_a"]]),
            "like_b": make_event("like_b", 7, content="+", tags=[["e", "root_b"]]),
            "dislike": make_event("dislike", 7, content="-", tags=[["e", "root_a"]]),
            "reply": make_event("reply", 1, content="reply!", tags=[["e", "root_a"]]),
            "repost": make_event("repost", 6, content="", tags=[["e", "root_b"]]),
        }

        with patch("apps.core.views.relay_req", return_value=events):
            result = attach_social_counts(notes)

        self.assertEqual(result[0]["like_count"], 2)
        self.assertEqual(result[0]["reactions_count"], 2)
        self.assertEqual(result[0]["reply_count"], 1)
        self.assertEqual(result[0]["repost_count"], 0)

        self.assertEqual(result[1]["like_count"], 1)
        self.assertEqual(result[1]["reply_count"], 0)
        self.assertEqual(result[1]["repost_count"], 1)

    def test_attach_social_counts_empty_notes_returns_unchanged(self):
        from apps.core.views import attach_social_counts

        with patch("apps.core.views.relay_req", return_value={}) as mock_req:
            result = attach_social_counts([])
        self.assertEqual(result, [])
        mock_req.assert_not_called()

    def test_parse_nip10_tags_positional_and_unmarked_tags(self):
        from apps.core.nip10 import parse_nip10_tags

        # Single unmarked e-tag
        r1, p1, m1, mentions1, _ = parse_nip10_tags([["e", "event_root_only"]])
        self.assertEqual(r1, "event_root_only")
        self.assertEqual(p1, "event_root_only")
        self.assertIsNone(m1)

        # Two unmarked e-tags (positional: first=root, second=parent)
        r2, p2, m2, mentions2, _ = parse_nip10_tags([["e", "first_root"], ["e", "second_parent"]])
        self.assertEqual(r2, "first_root")
        self.assertEqual(p2, "second_parent")

        # Three unmarked e-tags (first=root, last=parent, middle=mention)
        r3, p3, m3, mentions3, _ = parse_nip10_tags([["e", "first_root"], ["e", "middle_mention"], ["e", "last_parent"]])
        self.assertEqual(r3, "first_root")
        self.assertEqual(p3, "last_parent")
        self.assertEqual(mentions3, ["first_root", "middle_mention", "last_parent"])

    def test_fetch_thread_includes_indexing_fallback_relays_for_ancestors(self):
        from apps.core.views import fetch_thread

        target = make_event("target_reply", 1, content="Hero reply", tags=[
            ["e", "missing_parent_id", "", "reply"],
        ])
        parent = make_event("missing_parent_id", 1, content="Recovered ancestor note")

        captured_relays = []

        def mock_relay_req(filter_obj, relay_urls=None):
            if "ids" in filter_obj and "target_reply" in filter_obj["ids"]:
                return {"target_reply": target}
            if "ids" in filter_obj and "missing_parent_id" in filter_obj["ids"]:
                captured_relays.extend(relay_urls or [])
                return {"missing_parent_id": parent}
            return {}

        with patch("apps.core.views.relay_req", side_effect=mock_relay_req):
            result = fetch_thread("target_reply", relay_urls=["wss://relay.iyou.me"])

        self.assertIn("wss://relay.nostr.band", captured_relays)
        self.assertIn("wss://purplepag.es", captured_relays)
        self.assertEqual(len(result["ancestors"]), 1)
        self.assertEqual(result["ancestors"][0]["id"], "missing_parent_id")

    def test_calculate_trending_tags_aggregates_from_note_stream(self):
        from apps.core.views import calculate_trending_tags
        from apps.core.models import UserLinkDeck
        from django.contrib.auth import get_user_model

        User = get_user_model()
        user_alice, _ = User.objects.get_or_create(username="did:key:z6Mkalice_trend")
        UserLinkDeck.objects.get_or_create(user=user_alice, handle="alice", display_name="Alice")

        notes = [
            {
                "id": "note1",
                "pubkey": "3bf0c63fcb93463407af97a5e5ee64fa883d107ef9e558472c4eb9aaaefa459d",
                "author_did": "did:key:z6Mkalice_trend",
                "content": "Excited about #nostr and #bitcoin development!",
                "tags": [["t", "nostr"], ["t", "mesh"]],
            },
            {
                "id": "note2",
                "pubkey": "3bf0c63fcb93463407af97a5e5ee64fa883d107ef9e558472c4eb9aaaefa459d",
                "author_did": "did:key:z6Mkalice_trend",
                "content": "Another update regarding #nostr protocol.",
                "tags": [["t", "nostr"]],
            },
            {
                "id": "note3",
                "pubkey": "32e1827635450ebb3c5a7d12c1f8e7b2b514439ac10a67eef3d9fd9c5c68e245",
                "author_did": "did:key:z6Mkbob_external",
                "content": "Global wine notes with #wine and #bitcoin",
                "tags": [["t", "wine"]],
            },
        ]

        # 1. Global scope aggregates across all authors
        global_tags = calculate_trending_tags(notes, scope="global")
        self.assertTrue(len(global_tags) >= 3)
        tag_names = [t["name"] for t in global_tags]
        self.assertIn("nostr", tag_names)
        self.assertIn("bitcoin", tag_names)
        self.assertIn("wine", tag_names)
        nostr_item = next(t for t in global_tags if t["name"] == "nostr")
        self.assertEqual(nostr_item["count"], 2)
        self.assertEqual(nostr_item["scope"], "global")

        # 2. iyou scope aggregates only for authors in UserLinkDeck
        iyou_tags = calculate_trending_tags(notes, scope="iyou")
        iyou_names = [t["name"] for t in iyou_tags]
        self.assertIn("nostr", iyou_names)
        self.assertIn("bitcoin", iyou_names)
        self.assertNotIn("wine", iyou_names)


class FeedModerationContractTest(TestCase):
    """Verifies that feed notes carry author and id metadata required for self-moderation."""

    def test_feed_notes_contain_moderation_identifiers(self):
        events = {
            "mod1": make_event(
                "mod1",
                1,
                pubkey="3bf0c63fcb93463407af97a5e5ee64fa883d107ef9e558472c4eb9aaaefa459d",
                content="Self-moderation target post",
            ),
        }
        res = process_into_feed(events)
        self.assertEqual(len(res["roots"]), 1)
        root = res["roots"][0]
        self.assertEqual(root["id"], "mod1")
        self.assertEqual(root["pubkey"], "3bf0c63fcb93463407af97a5e5ee64fa883d107ef9e558472c4eb9aaaefa459d")
        self.assertTrue(root["npub"].startswith("npub1"))










