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
from django.test import TestCase, Client
from django.urls import reverse
from apps.core.views import categorize_media
from apps.core.tests.helpers import create_oidc_user


class CategorizeMediaTest(TestCase):
    """Unit tests for the categorize_media() MIME/extension classifier."""

    def _make_note(self, mime="", url="", content=""):
        return {
            "id": "abc123",
            "kind": 1063,
            "pubkey": "aa" * 32,
            "content": content,
            "created_at": 1700000000,
            "tags": [],
            "file_url": url,
            "mime_type": mime,
            "dimensions": None,
            "thumbnail_url": None,
            "alt_text": "",
            "is_sovereign": False,
            "author_name": "",
            "author_avatar": "",
            "duration": None,
            "blossom_hash": None,
            "blurhash": None,
            "summary": None,
        }

    # --- IMAGE ---

    def test_image_png(self):
        note = self._make_note(mime="image/png")
        self.assertEqual(categorize_media(note), "image")

    def test_image_jpeg(self):
        note = self._make_note(mime="image/jpeg")
        self.assertEqual(categorize_media(note), "image")

    def test_image_webp(self):
        note = self._make_note(mime="image/webp")
        self.assertEqual(categorize_media(note), "image")

    def test_image_by_extension(self):
        note = self._make_note(mime="", url="https://example.com/photo.jpg")
        self.assertEqual(categorize_media(note), "image")

    def test_image_svg_by_extension(self):
        note = self._make_note(mime="", url="https://example.com/icon.svg")
        self.assertEqual(categorize_media(note), "image")

    def test_image_fallback_svg_uppercase(self):
        note = self._make_note(mime="", url="https://example.com/logo.SVG")
        self.assertEqual(categorize_media(note), "image")

    # --- VIDEO ---

    def test_video_mp4(self):
        note = self._make_note(mime="video/mp4")
        self.assertEqual(categorize_media(note), "video")

    def test_video_webm(self):
        note = self._make_note(mime="video/webm")
        self.assertEqual(categorize_media(note), "video")

    def test_video_by_extension(self):
        note = self._make_note(mime="", url="https://example.com/clip.mov")
        self.assertEqual(categorize_media(note), "video")

    def test_video_mkv_extension(self):
        note = self._make_note(mime="", url="https://example.com/movie.mkv")
        self.assertEqual(categorize_media(note), "video")

    # --- AUDIO ---

    def test_audio_mp3(self):
        note = self._make_note(mime="audio/mpeg")
        self.assertEqual(categorize_media(note), "audio")

    def test_audio_ogg(self):
        note = self._make_note(mime="audio/ogg")
        self.assertEqual(categorize_media(note), "audio")

    def test_audio_wav(self):
        note = self._make_note(mime="audio/wav")
        self.assertEqual(categorize_media(note), "audio")

    def test_audio_by_extension(self):
        note = self._make_note(mime="", url="https://example.com/song.flac")
        self.assertEqual(categorize_media(note), "audio")

    def test_audio_m4a_extension(self):
        note = self._make_note(mime="", url="https://example.com/track.m4a")
        self.assertEqual(categorize_media(note), "audio")

    # --- OTHER ---

    def test_unknown_mime_and_url(self):
        note = self._make_note(mime="application/octet-stream", url="https://example.com/data")
        self.assertEqual(categorize_media(note), "other")

    def test_empty_mime_and_url(self):
        note = self._make_note(mime="", url="")
        self.assertEqual(categorize_media(note), "other")

    def test_pdf_is_other(self):
        note = self._make_note(mime="application/pdf", url="https://example.com/doc.pdf")
        self.assertEqual(categorize_media(note), "other")

    def test_mime_takes_precedence_over_extension(self):
        # If MIME says image but URL ends in .mp4, MIME wins
        note = self._make_note(mime="image/png", url="https://example.com/weird.mp4")
        self.assertEqual(categorize_media(note), "image")

    # --- CASE INSENSITIVE ---

    def test_mime_case_insensitive(self):
        note = self._make_note(mime="IMAGE/PNG")
        self.assertEqual(categorize_media(note), "image")

    def test_mime_case_video(self):
        note = self._make_note(mime="Video/MP4")
        self.assertEqual(categorize_media(note), "video")


class GalleryViewContextTest(TestCase):
    """Tests for GalleryView template context buckets."""

    def setUp(self):
        self.user = create_oidc_user("did:key:z6MkhaXgBZDvB9gGHgK9r")
        self.client = Client()
        self.client.force_login(self.user)

    def test_empty_gallery(self):
        with patch("apps.core.views.fetch_media_assets", return_value=[]):
            resp = self.client.get(reverse("gallery"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context["counts"]["all"], 0)
        self.assertEqual(resp.context["images"], [])
        self.assertEqual(resp.context["videos"], [])
        self.assertEqual(resp.context["audio_items"], [])
        self.assertEqual(resp.context["media_items"], [])
        self.assertEqual(resp.context["selected_type"], "all")

    def test_categorized_context(self):
        notes = [
            {"id": "1", "media_type": "image", "file_url": "img.png", "mime_type": "image/png", "pubkey": "aa" * 32,
             "kind": 1063, "content": "", "tags": [], "created_at": 1700000000, "npub": "npub1...",
             "dimensions": None, "thumbnail_url": None, "alt_text": "", "is_sovereign": False,
             "author_name": "", "author_avatar": "", "duration": None, "blossom_hash": None,
             "blurhash": None, "summary": None},
            {"id": "2", "media_type": "video", "file_url": "vid.mp4", "mime_type": "video/mp4", "pubkey": "bb" * 32,
             "kind": 1063, "content": "", "tags": [], "created_at": 1700000001, "npub": "npub2...",
             "dimensions": None, "thumbnail_url": None, "alt_text": "", "is_sovereign": False,
             "author_name": "", "author_avatar": "", "duration": "120", "blossom_hash": None,
             "blurhash": None, "summary": None},
            {"id": "3", "media_type": "audio", "file_url": "pod.mp3", "mime_type": "audio/mpeg", "pubkey": "cc" * 32,
             "kind": 1063, "content": "", "tags": [], "created_at": 1700000002, "npub": "npub3...",
             "dimensions": None, "thumbnail_url": None, "alt_text": "", "is_sovereign": False,
             "author_name": "", "author_avatar": "", "duration": "300", "blossom_hash": None,
             "blurhash": None, "summary": None},
            {"id": "4", "media_type": "other", "file_url": "doc.pdf", "mime_type": "application/pdf", "pubkey": "dd" * 32,
             "kind": 1063, "content": "", "tags": [], "created_at": 1700000003, "npub": "npub4...",
             "dimensions": None, "thumbnail_url": None, "alt_text": "", "is_sovereign": False,
             "author_name": "", "author_avatar": "", "duration": None, "blossom_hash": None,
             "blurhash": None, "summary": None},
        ]
        with patch("apps.core.views.fetch_media_assets", return_value=notes):
            resp = self.client.get(reverse("gallery"))
        ctx = resp.context
        self.assertEqual(ctx["counts"]["all"], 4)
        self.assertEqual(ctx["counts"]["images"], 1)
        self.assertEqual(ctx["counts"]["videos"], 1)
        self.assertEqual(ctx["counts"]["audio"], 1)
        self.assertEqual(len(ctx["images"]), 1)
        self.assertEqual(len(ctx["videos"]), 1)
        self.assertEqual(len(ctx["audio_items"]), 1)
        self.assertEqual(len(ctx["other_items"]), 1)
        self.assertEqual(ctx["images"][0]["id"], "1")
        self.assertEqual(ctx["videos"][0]["id"], "2")
        self.assertEqual(ctx["audio_items"][0]["id"], "3")
        self.assertEqual(ctx["other_items"][0]["id"], "4")
        # Category slices + normalized identity keys feed the 3-pane chassis.
        self.assertEqual(len(ctx["media_items"]), 4)
        self.assertEqual(len(ctx["image_items"]), 1)
        self.assertEqual(len(ctx["video_items"]), 1)
        self.assertEqual(len(ctx["audio_items"]), 1)
        for item in ctx["media_items"]:
            self.assertEqual(item["category"], item["media_type"])
            self.assertIn("author_display_name", item)
            self.assertIn("author_handle", item)
            self.assertIn("is_ecosystem_member", item)
            self.assertEqual(item["author_npub"], item["npub"])
            self.assertTrue(item["url"])
            self.assertTrue("caption" in item)

    def test_active_type_default(self):
        with patch("apps.core.views.fetch_media_assets", return_value=[]):
            resp = self.client.get(reverse("gallery"))
        self.assertEqual(resp.context["active_type"], "all")
        self.assertEqual(resp.context["selected_type"], "all")

    def test_active_type_images(self):
        with patch("apps.core.views.fetch_media_assets", return_value=[]):
            resp = self.client.get(reverse("gallery") + "?type=images")
        self.assertEqual(resp.context["active_type"], "images")
        self.assertEqual(resp.context["selected_type"], "images")


class GalleryViewAuthTest(TestCase):
    """Gallery is public-read; no auth required for browsing."""

    def setUp(self):
        self.client = Client()

    def test_anonymous_can_view_gallery(self):
        resp = self.client.get(reverse("gallery"))
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, "gallery.html")


class GalleryCircleFilteringAndTagSearchTest(TestCase):
    """Verifies gallery 3-pane rendering, category slices, scripts, and rails."""

    def setUp(self):
        self.client = Client()

    def test_gallery_stream_renders_category_slices_and_scripts(self):
        notes = [
            {
                "id": "img1",
                "media_type": "image",
                "file_url": "https://example.com/photo.png",
                "mime_type": "image/png",
                "pubkey": "aa" * 32,
                "pubkey_hex": "aa" * 32,
                "author_did": "did:key:z6Mkgallerytest",
                "tags_json": '[["t", "nostr"], ["t", "art"]]',
                "kind": 1063,
                "content": "Sovereign photography",
                "tags": [["t", "nostr"], ["t", "art"]],
                "created_at": 1700000000,
                "npub": "npub1galleryauthor...",
                "dimensions": "1920x1080",
                "thumbnail_url": None,
                "alt_text": "Sample photograph",
                "is_sovereign": False,
                "author_name": "Alice",
                "author_avatar": "https://example.com/alice.png",
                "duration": None,
                "blossom_hash": "hash123",
                "blurhash": None,
                "summary": "Sample summary",
            },
            {
                "id": "vid1",
                "media_type": "video",
                "file_url": "https://example.com/movie.mp4",
                "mime_type": "video/mp4",
                "pubkey": "bb" * 32,
                "pubkey_hex": "bb" * 32,
                "author_did": "did:key:z6Mkgallerytest2",
                "tags_json": '[["t", "video"]]',
                "kind": 1063,
                "content": "Sovereign video",
                "tags": [["t", "video"]],
                "created_at": 1700000001,
                "npub": "npub1galleryauthor2...",
                "dimensions": "1920x1080",
                "thumbnail_url": None,
                "alt_text": "Sample video",
                "is_sovereign": False,
                "author_name": "Bob",
                "author_avatar": "https://example.com/bob.png",
                "duration": "120",
                "blossom_hash": "hash456",
                "blurhash": None,
                "summary": "Sample video summary",
            },
            {
                "id": "aud1",
                "media_type": "audio",
                "file_url": "https://example.com/podcast.mp3",
                "mime_type": "audio/mpeg",
                "pubkey": "cc" * 32,
                "pubkey_hex": "cc" * 32,
                "author_did": "did:key:z6Mkgallerytest3",
                "tags_json": '[["t", "podcast"]]',
                "kind": 1063,
                "content": "Sovereign audio",
                "tags": [["t", "podcast"]],
                "created_at": 1700000002,
                "npub": "npub1galleryauthor3...",
                "dimensions": None,
                "thumbnail_url": None,
                "alt_text": "Sample audio",
                "is_sovereign": False,
                "author_name": "Charlie",
                "author_avatar": "https://example.com/charlie.png",
                "duration": "300",
                "blossom_hash": "hash789",
                "blurhash": None,
                "summary": "Sample audio summary",
            },
        ]
        with patch("apps.core.views.fetch_media_assets", return_value=notes):
            resp = self.client.get(reverse("gallery"))

        self.assertEqual(resp.status_code, 200)
        # 3-pane chassis: sticky lightbox modal + category slices in the stream.
        self.assertContains(resp, 'id="lightbox-modal"')
        self.assertContains(resp, 'id="gallery-container"')
        self.assertContains(resp, 'id="gallery-image-grid"')
        self.assertContains(resp, 'id="gallery-video-deck"')
        self.assertContains(resp, 'id="gallery-audio-deck"')
        self.assertContains(resp, "https://example.com/photo.png")
        self.assertContains(resp, "https://example.com/movie.mp4")
        self.assertContains(resp, "https://example.com/podcast.mp3")
        # MIME filter tabs route through ?type= selectors.
        self.assertContains(resp, "?type=image")
        self.assertContains(resp, "?type=video")
        self.assertContains(resp, "?type=audio")
        # Lightbox triggers from the image masonry.
        self.assertContains(resp, "openLightbox(")
        # Required global + page scripts mounted.
        self.assertContains(resp, "gallery_player.js")
        self.assertContains(resp, "trust_lens.js")
        self.assertContains(resp, "contact_manager.js")
        self.assertContains(resp, "circle_feed_filter.js")

    def test_gallery_right_rail_renders_discovery_hub(self):
        with patch("apps.core.views.fetch_media_assets", return_value=[]):
            resp = self.client.get(reverse("gallery"))

        self.assertEqual(resp.status_code, 200)
        # Standard right discovery rail (same hub as /feed).
        self.assertContains(resp, 'id="relay-health-widget"')
        self.assertContains(resp, 'id="live-rooms-card"')
        self.assertContains(resp, 'id="trending-global-list"')
        self.assertContains(resp, 'id="sovereign-creators-list"')
        # The left navigation rail and stream column mount from base.html.
        self.assertContains(resp, 'id="left-rail"')
        self.assertContains(resp, 'id="stream-column"')


class GalleryThreePaneSmokeTest(TestCase):
    """Smoke-level assertions guarding the canonical 3-pane gallery mount."""

    def test_gallery_empty_state_is_contained_in_stream_column(self):
        with patch("apps.core.views.fetch_media_assets", return_value=[]):
            resp = self.client.get(reverse("gallery"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "No media discovered in this stream.")

    def test_gallery_lightbox_include_renders_lb_controls(self):
        with patch("apps.core.views.fetch_media_assets", return_value=[]):
            resp = self.client.get(reverse("gallery"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'id="lbMediaPane"')
        self.assertContains(resp, 'id="lbAuthor"')
        self.assertContains(resp, 'id="lbCaption"')
        self.assertContains(resp, 'id="lbMeta"')
        self.assertContains(resp, 'id="lbPrev"')
        self.assertContains(resp, 'id="lbNext"')


class GalleryCardModernizationAndAttributionTest(TestCase):
    """Verifies human-readable title extraction, false badge elimination, and author metadata in gallery cards."""

    def setUp(self):
        self.client = Client()

    def test_json_summary_and_content_parsed_to_clean_display_title(self):
        from apps.core.views import _extract_display_title

        # Test various JSON payloads
        title1 = _extract_display_title('{"title": "Scenic Mountain Sunset", "queryKey": "abc"}')
        self.assertEqual(title1, "Scenic Mountain Sunset")

        title2 = _extract_display_title('{"caption": "Decentralized Audio Broadcast"}')
        self.assertEqual(title2, "Decentralized Audio Broadcast")

        title3 = _extract_display_title('{"text": "Mesh Protocol Walkthrough"}')
        self.assertEqual(title3, "Mesh Protocol Walkthrough")

        title4 = _extract_display_title('{"queryKey": "relay:media:999"}')
        self.assertEqual(title4, "relay:media:999")

        # Test plain text fallback
        title5 = _extract_display_title("Plain human note content")
        self.assertEqual(title5, "Plain human note content")

        # Test malformed JSON fallback
        title6 = _extract_display_title("{invalid json content")
        self.assertEqual(title6, "{invalid json content")

    def test_gallery_renders_clean_display_title_without_json_braces(self):
        notes = [
            {
                "id": "img_json",
                "media_type": "image",
                "file_url": "https://example.com/photo.png",
                "mime_type": "image/png",
                "pubkey": "11" * 32,
                "pubkey_hex": "11" * 32,
                "author_did": "",
                "tags_json": '[]',
                "kind": 1063,
                "content": '{"title": "Clean Photo Title", "queryKey": "q123"}',
                "display_title": "Clean Photo Title",
                "tags": [],
                "created_at": 1700000000,
                "npub": "npub1author...",
                "dimensions": "1920x1080",
                "thumbnail_url": None,
                "alt_text": "",
                "is_sovereign": False,
                "author_name": "SovereignArtist",
                "nip05": "artist@nostr.me",
                "author_avatar": "https://example.com/avatar.png",
                "duration": None,
                "blossom_hash": "hash123",
                "blurhash": None,
                "summary": '{"title": "Clean Photo Title"}',
            }
        ]
        with patch("apps.core.views.fetch_media_assets", return_value=notes):
            resp = self.client.get(reverse("gallery"))

        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Clean Photo Title")
        # Ensure raw JSON curly braces are not exposed in title text
        self.assertNotContains(resp, '{"title":')
        self.assertNotContains(resp, '"queryKey":')

    def test_unverified_external_media_does_not_render_static_verified_badge(self):
        notes = [
            {
                "id": "ext_media",
                "media_type": "image",
                "file_url": "https://external.relay/photo.jpg",
                "mime_type": "image/jpeg",
                "pubkey": "33" * 32,
                "pubkey_hex": "33" * 32,
                "author_did": "",
                "tags_json": '[]',
                "kind": 1063,
                "content": "External photo",
                "display_title": "External photo",
                "tags": [],
                "created_at": 1700000000,
                "npub": "npub1externalauthor...",
                "dimensions": None,
                "thumbnail_url": None,
                "alt_text": "",
                "is_sovereign": False,
                "author_name": "ExternalUser",
                "nip05": "",
                "author_avatar": "",
                "duration": None,
                "blossom_hash": "hash333",
                "blurhash": None,
                "summary": "",
            }
        ]
        with patch("apps.core.views.fetch_media_assets", return_value=notes):
            resp = self.client.get(reverse("gallery"))

        self.assertEqual(resp.status_code, 200)
        # Static Verified badge must NOT exist in the DOM
        self.assertNotContains(resp, ">Verified<")
        self.assertNotContains(resp, "bg-green-900/50 text-green-300")

    def test_link_deck_identity_renders_name_and_handle_on_cards(self):
        from django.contrib.auth import get_user_model
        from apps.core.models import UserLinkDeck

        pk = "44" * 32
        deck_user = get_user_model().objects.create_user(username=f"did:iyou:0x{pk}")
        UserLinkDeck.objects.create(
            user=deck_user,
            handle="creatorprime",
            display_name="CreatorPrime",
            avatar_url="https://example.com/avatar.jpg",
        )
        notes = [
            {
                "id": "note_attributed",
                "media_type": "image",
                "file_url": "https://example.com/art.png",
                "mime_type": "image/png",
                "pubkey": pk,
                "pubkey_hex": pk,
                "author_did": f"did:iyou:0x{pk}",
                "tags_json": '[]',
                "kind": 1063,
                "content": "Digital Sovereign Art",
                "display_title": "Digital Sovereign Art",
                "tags": [],
                "created_at": 1700000000,
                "npub": "npub1customauthor...",
                "dimensions": "1080x1080",
                "thumbnail_url": None,
                "alt_text": "",
                "is_sovereign": False,
                "author_name": "CreatorPrime",
                "nip05": "creator@iyou.me",
                "author_avatar": "https://example.com/avatar.jpg",
                "duration": None,
                "blossom_hash": "hash444",
                "blurhash": None,
                "summary": "",
            }
        ]
        with patch("apps.core.views.fetch_media_assets", return_value=notes):
            resp = self.client.get(reverse("gallery"))

        self.assertEqual(resp.status_code, 200)
        # Canonical Identity Translation Service keys surface on the card.
        self.assertContains(resp, "CreatorPrime")
        self.assertContains(resp, "@creatorprime")
        self.assertContains(resp, 'href="/@creatorprime"')




class FetchMediaAssetsUnifiedIngestionTest(TestCase):
    """fetch_media_assets() must surface Kind 1 media alongside Kind 1063.

    Kind 1063 (NIP-94) file-header events are a small minority of real Nostr
    media; most media arrives as an ordinary text note with an unfurled URL.
    The gallery tabs were chronically sparse because the relay filter only ever
    asked for Kind 1063.
    """

    def _patch_relay_req(self, events):
        """Patch relay_req so the first call (the media query) returns `events`
        and the second (the Kind 0 profile hydration) returns nothing."""
        calls = []

        def fake_relay_req(filter_obj, **kwargs):
            calls.append(filter_obj)
            if filter_obj.get("kinds") == [0]:
                return {}
            return events

        return patch("apps.core.views.relay_req", side_effect=fake_relay_req), calls

    def test_relay_filter_requests_both_kinds_with_overfetch(self):
        from apps.core.views import fetch_media_assets

        patcher, calls = self._patch_relay_req({})
        with patcher:
            fetch_media_assets(limit=24)

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["kinds"], [1, 1063])
        # Over-fetch headroom: one event can expand to many cards and the tab
        # split runs after categorization.
        self.assertEqual(calls[0]["limit"], 24 * 3)

    def test_authors_and_until_filters_preserved(self):
        from apps.core.views import fetch_media_assets

        patcher, calls = self._patch_relay_req({})
        with patcher:
            fetch_media_assets(authors=["ab" * 32], limit=10, until=1700000000)

        self.assertEqual(calls[0]["authors"], ["ab" * 32])
        self.assertEqual(calls[0]["until"], 1700000000)

    def test_kind1_image_note_flattens_to_image_card(self):
        from apps.core.views import fetch_media_assets

        events = {
            "e1": {
                "id": "e1",
                "kind": 1,
                "pubkey": "aa" * 32,
                "content": "sunset over the mesh https://cdn.example.com/sunset.jpg",
                "tags": [],
                "created_at": 1700000000,
            }
        }
        patcher, _ = self._patch_relay_req(events)
        with patcher:
            items = fetch_media_assets(limit=24)

        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual(item["media_type"], "image")
        self.assertEqual(item["file_url"], "https://cdn.example.com/sunset.jpg")
        self.assertTrue(item["is_kind1"])
        self.assertEqual(item["parent_event_id"], "e1")
        # The media URL is stripped from the human label.
        self.assertIn("sunset over the mesh", item["display_title"])
        self.assertNotIn("sunset.jpg", item["display_title"])
        # Author envelope is populated even without a Kind 0 profile.
        self.assertEqual(item["pubkey"], "aa" * 32)
        self.assertIn("npub", item)

    def test_kind1_multi_media_note_flattens_to_distinct_cards(self):
        from apps.core.views import fetch_media_assets

        events = {
            "e1": {
                "id": "e1",
                "kind": 1,
                "pubkey": "aa" * 32,
                "content": (
                    "three files: "
                    "https://cdn.example.com/a.png "
                    "https://cdn.example.com/clip.mp4 "
                    "https://cdn.example.com/track.mp3"
                ),
                "tags": [],
                "created_at": 1700000000,
            }
        }
        patcher, _ = self._patch_relay_req(events)
        with patcher:
            items = fetch_media_assets(limit=24)

        # One event, three distinct cards.
        self.assertEqual(len(items), 3)
        self.assertEqual({i["media_type"] for i in items}, {"image", "video", "audio"})
        self.assertEqual(len({i["file_url"] for i in items}), 3)
        # All three share the parent event.
        self.assertEqual({i["parent_event_id"] for i in items}, {"e1"})

    def test_mixed_kinds_categorize_into_separate_tabs(self):
        from apps.core.views import fetch_media_assets

        events = {
            "e1063": {
                "id": "e1063",
                "kind": 1063,
                "pubkey": "bb" * 32,
                "content": "NIP-94 header",
                "tags": [["url", "https://cdn.example.com/header.png"], ["m", "image/png"]],
                "created_at": 1700000005,
            },
            "e1img": {
                "id": "e1img",
                "kind": 1,
                "pubkey": "aa" * 32,
                "content": "note with https://cdn.example.com/inline.jpg",
                "tags": [],
                "created_at": 1700000010,
            },
            "e1vid": {
                "id": "e1vid",
                "kind": 1,
                "pubkey": "cc" * 32,
                "content": "clip https://cdn.example.com/inline.mp4",
                "tags": [],
                "created_at": 1700000001,
            },
        }
        patcher, _ = self._patch_relay_req(events)
        with patcher:
            items = fetch_media_assets(limit=24)

        by_type = {}
        for i in items:
            by_type.setdefault(i["media_type"], []).append(i)

        self.assertEqual(len(by_type.get("image", [])), 2)   # one 1063 + one kind 1
        self.assertEqual(len(by_type.get("video", [])), 1)
        # The 1063 card is not flagged as a text note.
        header = [i for i in items if i["id"] == "e1063"][0]
        self.assertFalse(header["is_kind1"])
        self.assertEqual(header["mime_type"], "image/png")
        self.assertEqual(header["media_type"], "image")

    def test_blossom_url_with_query_string_still_categorizes(self):
        from apps.core.views import fetch_media_assets

        events = {
            "e1": {
                "id": "e1",
                "kind": 1,
                "pubkey": "aa" * 32,
                "content": "blossom https://blossom.example.com/abcdef123456?x=deadbeef",
                "tags": [],
                "created_at": 1700000000,
            }
        }
        patcher, _ = self._patch_relay_req(events)
        with patcher:
            items = fetch_media_assets(limit=24)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["media_type"], "image")

    def test_kind1_note_without_media_yields_no_cards(self):
        from apps.core.views import fetch_media_assets

        events = {
            "e1": {
                "id": "e1",
                "kind": 1,
                "pubkey": "aa" * 32,
                "content": "just text, no media here",
                "tags": [],
                "created_at": 1700000000,
            }
        }
        patcher, _ = self._patch_relay_req(events)
        with patcher:
            items = fetch_media_assets(limit=24)

        self.assertEqual(items, [])

    def test_results_truncated_to_limit_after_sorting(self):
        from apps.core.views import fetch_media_assets

        events = {}
        for idx in range(10):
            events["e%d" % idx] = {
                "id": "e%d" % idx,
                "kind": 1,
                "pubkey": "aa" * 32,
                "content": "n%d https://cdn.example.com/i%d.png" % (idx, idx),
                "tags": [],
                "created_at": 1700000000 + idx,
            }
        patcher, _ = self._patch_relay_req(events)
        with patcher:
            items = fetch_media_assets(limit=3)

        self.assertEqual(len(items), 3)
        # Newest first.
        self.assertEqual([i["created_at_ts"] for i in items],
                         [1700000009, 1700000008, 1700000007])

    def test_1063_card_without_url_is_dropped(self):
        from apps.core.views import fetch_media_assets

        events = {
            "e1": {
                "id": "e1",
                "kind": 1063,
                "pubkey": "aa" * 32,
                "content": "no url tag here",
                "tags": [["m", "image/png"]],
                "created_at": 1700000000,
            }
        }
        patcher, _ = self._patch_relay_req(events)
        with patcher:
            items = fetch_media_assets(limit=24)

        self.assertEqual(items, [])

    def test_duplicate_url_within_one_note_is_deduped(self):
        from apps.core.views import fetch_media_assets

        url = "https://cdn.example.com/same.png"
        # The same asset referenced twice by a single text note (unfurl plus an
        # explicit link) must not produce two cards.
        events = {
            "e1": {
                "id": "e1",
                "kind": 1,
                "pubkey": "aa" * 32,
                "content": "look %s and again %s" % (url, url),
                "tags": [],
                "created_at": 1700000000,
            }
        }
        patcher, _ = self._patch_relay_req(events)
        with patcher:
            items = fetch_media_assets(limit=24)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["file_url"], url)

    def test_same_url_from_distinct_events_yields_distinct_cards(self):
        from apps.core.views import fetch_media_assets

        url = "https://cdn.example.com/shared.png"
        events = {
            "e1063": {
                "id": "e1063",
                "kind": 1063,
                "pubkey": "aa" * 32,
                "content": "header",
                "tags": [["url", url], ["m", "image/png"]],
                "created_at": 1700000000,
            },
            "e1": {
                "id": "e1",
                "kind": 1,
                "pubkey": "aa" * 32,
                "content": "note %s" % url,
                "tags": [],
                "created_at": 1700000001,
            },
        }
        patcher, _ = self._patch_relay_req(events)
        with patcher:
            items = fetch_media_assets(limit=24)

        # Deduplication is scoped to (parent_event_id, url): two genuinely
        # distinct events are two distinct posts and both stay visible.
        self.assertEqual(len(items), 2)
        self.assertEqual({i["file_url"] for i in items}, {url})
