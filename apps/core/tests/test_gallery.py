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

    def test_active_type_default(self):
        with patch("apps.core.views.fetch_media_assets", return_value=[]):
            resp = self.client.get(reverse("gallery"))
        self.assertEqual(resp.context["active_type"], "all")

    def test_active_type_images(self):
        with patch("apps.core.views.fetch_media_assets", return_value=[]):
            resp = self.client.get(reverse("gallery") + "?type=images")
        self.assertEqual(resp.context["active_type"], "images")


class GalleryViewAuthTest(TestCase):
    """Gallery is public-read; no auth required for browsing."""

    def setUp(self):
        self.client = Client()

    def test_anonymous_can_view_gallery(self):
        resp = self.client.get(reverse("gallery"))
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, "gallery.html")


class GalleryCircleFilteringAndTagSearchTest(TestCase):
    """Verifies gallery media decoration, circle filtering markup, empty states, and scripts."""

    def setUp(self):
        self.client = Client()

    def test_gallery_media_cards_have_circle_and_tag_attributes(self):
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
        self.assertContains(resp, "gallery-media-card")
        self.assertContains(resp, f'data-author-pubkey="{"aa" * 32}"')
        self.assertContains(resp, 'data-author-did="did:key:z6Mkgallerytest"')
        self.assertContains(resp, 'data-media-type="image"')
        self.assertContains(resp, 'data-media-type="video"')
        self.assertContains(resp, 'data-media-type="audio"')
        self.assertContains(resp, 'id="tab-count-all"')
        self.assertContains(resp, 'id="tab-count-images"')
        self.assertContains(resp, 'id="tab-count-videos"')
        self.assertContains(resp, 'id="tab-count-audio"')
        self.assertContains(resp, 'id="empty-all"')
        self.assertContains(resp, 'id="empty-images"')
        self.assertContains(resp, 'id="empty-videos"')
        self.assertContains(resp, 'id="empty-audio"')
        self.assertContains(resp, "contact_manager.js")
        self.assertContains(resp, "trust_lens.js")
        self.assertContains(resp, "circle_feed_filter.js")


    def test_gallery_renders_layer2_bottom_track_circle_filters(self):
        with patch("apps.core.views.fetch_media_assets", return_value=[]):
            resp = self.client.get(reverse("gallery"))

        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'id="circle-filter-group"')
        self.assertContains(resp, 'data-circle="global"')
        self.assertContains(resp, 'data-circle="following"')
        self.assertContains(resp, 'data-circle="inner"')
        self.assertContains(resp, 'data-circle="mutual"')
        self.assertContains(resp, 'id="active-circle-label"')


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

    def test_author_name_nip05_and_trust_lens_slot_render_in_card_footer(self):
        notes = [
            {
                "id": "note_attributed",
                "media_type": "image",
                "file_url": "https://example.com/art.png",
                "mime_type": "image/png",
                "pubkey": "44" * 32,
                "pubkey_hex": "44" * 32,
                "author_did": "did:key:z6Mkcustomkey",
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
        self.assertContains(resp, "CreatorPrime")
        self.assertContains(resp, "creator@iyou.me")
        self.assertContains(resp, 'class="author-badge-slot"')
        self.assertContains(resp, f'data-author-slot="{"44" * 32}"')


