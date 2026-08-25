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
