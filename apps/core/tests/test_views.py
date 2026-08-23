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

import hashlib
import json
import logging
import urllib.request
import urllib.error
from unittest.mock import patch, MagicMock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.contrib.auth.models import User
from django.urls import reverse
from django.conf import settings

from .helpers import make_event

logger = logging.getLogger(__name__)


class HomeViewTest(TestCase):
    def test_home_redirects_to_feed(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, "/feed")


class DashboardViewTest(TestCase):
    def test_dashboard_redirects_anonymous(self):
        response = self.client.get("/dashboard")
        self.assertEqual(response.status_code, 302)

    def test_dashboard_redirects_to_idp_login(self):
        response = self.client.get("/dashboard")
        self.assertIn("/oidc/authenticate/", response.url)

    def test_authenticated_user_sees_did(self):
        user = User.objects.create_user(username="did:iyou:0xabc123")
        self.client.force_login(user)
        response = self.client.get("/dashboard")
        self.assertContains(response, "did:iyou:0xabc123")
        self.assertContains(response, "Decentralized Identifier")

    def test_authenticated_user_sees_dashboard_title(self):
        user = User.objects.create_user(username="did:iyou:0xdef456")
        self.client.force_login(user)
        response = self.client.get("/dashboard")
        self.assertContains(response, "Dashboard")

    def test_authenticated_user_has_logout_link(self):
        user = User.objects.create_user(username="did:iyou:0xghi789")
        self.client.force_login(user)
        response = self.client.get("/dashboard")
        self.assertContains(response, "Sign Out")


class JwksConnectivityTest(TestCase):
    """Pings the IdP's JWKS endpoint to verify connectivity.

    This is an integration test — it requires a running iyou_idp instance
    at the URL configured in OIDC_OP_JWKS_ENDPOINT.
    """

    def test_jwks_endpoint_returns_valid_json_with_keys(self):
        url = settings.OIDC_OP_JWKS_ENDPOINT
        if not url:
            self.skipTest("OIDC_OP_JWKS_ENDPOINT is not configured")

        try:
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=5) as resp:
                self.assertEqual(resp.status, 200)
                data = json.loads(resp.read().decode())
                self.assertIn("keys", data)
                self.assertGreater(len(data["keys"]), 0)
        except (urllib.error.URLError, ConnectionError, OSError) as e:
            self.skipTest(f"IdP not reachable at {url}: {e}")


class ChatViewTest(TestCase):
    def test_redirects_anonymous(self):
        response = self.client.get(reverse("chat"))
        self.assertEqual(response.status_code, 302)

    def test_redirects_to_idp_login(self):
        response = self.client.get(reverse("chat"))
        self.assertIn("/oidc/authenticate/", response.url)

    def test_authenticated_user_sees_chat(self):
        user = User.objects.create_user(username="did:key:z6Mkchat123")
        self.client.force_login(user)
        response = self.client.get(reverse("chat"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "chat.html")

    def test_chat_contains_xmpp_init(self):
        user = User.objects.create_user(username="did:key:z6Mkchat456")
        self.client.force_login(user)
        response = self.client.get(reverse("chat"))
        self.assertContains(response, "converse.initialize")
        self.assertContains(response, "home.iyou.me:5222")

    def test_chat_shows_nav(self):
        user = User.objects.create_user(username="did:key:z6Mknav")
        self.client.force_login(user)
        response = self.client.get(reverse("chat"))
        self.assertContains(response, "Dashboard")
        self.assertContains(response, "Feed")

    def test_authenticated_user_sees_logout_in_chat(self):
        user = User.objects.create_user(username="did:key:z6Mklogout")
        self.client.force_login(user)
        response = self.client.get(reverse("chat"))
        self.assertContains(response, "Sign Out")

    def test_chat_persistent_store_local(self):
        user = User.objects.create_user(username="did:key:z6Mkomemo1")
        self.client.force_login(user)
        response = self.client.get(reverse("chat"))
        self.assertContains(response, "persistent_store: 'local'")

    def test_chat_allow_non_roster_messaging(self):
        user = User.objects.create_user(username="did:key:z6Mkomemo2")
        self.client.force_login(user)
        response = self.client.get(reverse("chat"))
        self.assertContains(response, "allow_non_roster_messaging: true")

    def test_chat_keepalive_enabled(self):
        user = User.objects.create_user(username="did:key:z6Mkomemo3")
        self.client.force_login(user)
        response = self.client.get(reverse("chat"))
        self.assertContains(response, "keepalive: true")

    def test_chat_jid_uses_pubkey_hex(self):
        user = User.objects.create_user(username="did:key:z6Mkjidtest")
        self.client.force_login(user)
        response = self.client.get(reverse("chat"))
        content = response.content.decode()
        self.assertIn("jid:", content)
        self.assertNotIn("did:key:", content.split("jid:")[1].split("@")[0])


class GalleryViewTest(TestCase):
    def test_anonymous_can_view_gallery(self):
        response = self.client.get(reverse("gallery"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "gallery.html")

    def test_authenticated_user_sees_gallery(self):
        user = User.objects.create_user(username="did:key:z6Mkgallery")
        self.client.force_login(user)
        response = self.client.get(reverse("gallery"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "gallery.html")

    def test_gallery_contains_media_heading(self):
        user = User.objects.create_user(username="did:key:z6Mkgallery2")
        self.client.force_login(user)
        response = self.client.get(reverse("gallery"))
        self.assertContains(response, "Media Gallery")

    def test_gallery_shows_nav(self):
        user = User.objects.create_user(username="did:key:z6Mkgallery3")
        self.client.force_login(user)
        response = self.client.get(reverse("gallery"))
        self.assertContains(response, "Dashboard")
        self.assertContains(response, "Gallery")


class ProfileViewTest(TestCase):
    def test_invalid_npub_returns_error(self):
        response = self.client.get(reverse("profile", kwargs={"npub": "invalid"}))
        self.assertContains(response, "Invalid npub")

    def test_valid_npub_renders_profile_page(self):
        response = self.client.get(
            reverse("profile", kwargs={"npub": "npub1qqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqq6ctk5d"})
        )
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "profile.html")


class DashboardProfileTest(TestCase):
    def test_dashboard_contains_profile_section(self):
        user = User.objects.create_user(username="did:key:z6Mkdashprofile")
        self.client.force_login(user)
        response = self.client.get(reverse("dashboard"))
        self.assertContains(response, "Sovereign Profile")

    def test_dashboard_contains_publish_button(self):
        user = User.objects.create_user(username="did:key:z6Mkdashpub")
        self.client.force_login(user)
        response = self.client.get(reverse("dashboard"))
        self.assertContains(response, "Publish Profile")


class MediaUploadProxyViewTest(TestCase):
    def test_upload_proxy_success_multipart(self):
        file_content = b"fake_image_bytes_12345"
        expected_hash = hashlib.sha256(file_content).hexdigest()
        uploaded_file = SimpleUploadedFile("photo.jpg", file_content, content_type="image/jpeg")

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_cm = MagicMock()
            mock_cm.__enter__.return_value = MagicMock(status=201)
            mock_urlopen.return_value = mock_cm

            response = self.client.post(
                reverse("media_upload_proxy"),
                {"file": uploaded_file},
            )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["sha256"], expected_hash)
        self.assertEqual(data["url"], f"https://cdn.iyou.me/{expected_hash}")
        self.assertEqual(data["size"], len(file_content))
        self.assertEqual(data["type"], "image/jpeg")
        self.assertTrue(mock_urlopen.called)

    def test_upload_proxy_no_file_returns_400(self):
        response = self.client.post(reverse("media_upload_proxy"), {})
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertIn("error", data)

    def test_upload_proxy_get_returns_405(self):
        response = self.client.get(reverse("media_upload_proxy"))
        self.assertEqual(response.status_code, 405)
        data = response.json()
        self.assertIn("error", data)

    def test_upload_proxy_raw_body_upload(self):
        raw_content = b"audio_raw_data_stream_6789"
        expected_hash = hashlib.sha256(raw_content).hexdigest()

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_cm = MagicMock()
            mock_cm.__enter__.return_value = MagicMock(status=200)
            mock_urlopen.return_value = mock_cm

            response = self.client.post(
                reverse("media_upload_proxy"),
                data=raw_content,
                content_type="audio/ogg",
            )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["sha256"], expected_hash)
        self.assertEqual(data["url"], f"https://cdn.iyou.me/{expected_hash}")
        self.assertEqual(data["type"], "audio/ogg")

    def test_upload_proxy_upstream_fallback_on_404(self):
        file_content = b"video_sample_content"
        expected_hash = hashlib.sha256(file_content).hexdigest()
        uploaded_file = SimpleUploadedFile("clip.mp4", file_content, content_type="video/mp4")

        # First call raises HTTPError(404), second call succeeds
        http_err = urllib.error.HTTPError("http://127.0.0.1:9002/upload", 404, "Not Found", {}, None)
        success_cm = MagicMock()
        success_cm.__enter__.return_value = MagicMock(status=201)

        with patch("urllib.request.urlopen", side_effect=[http_err, success_cm]) as mock_urlopen:
            response = self.client.post(
                reverse("media_upload_proxy"),
                {"file": uploaded_file},
            )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["sha256"], expected_hash)
        self.assertEqual(data["url"], f"https://cdn.iyou.me/{expected_hash}")
        self.assertEqual(mock_urlopen.call_count, 2)

    def test_upload_proxy_upstream_exception_resilient(self):
        file_content = b"document_data"
        expected_hash = hashlib.sha256(file_content).hexdigest()
        uploaded_file = SimpleUploadedFile("doc.pdf", file_content, content_type="application/pdf")

        # Network error to upstream Blossom
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("Connection refused")):
            response = self.client.post(
                reverse("media_upload_proxy"),
                {"file": uploaded_file},
            )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["sha256"], expected_hash)
        self.assertEqual(data["url"], f"https://cdn.iyou.me/{expected_hash}")


class FeedViewTrustLensContractTest(TestCase):
    """Trust Lens DOM contract: badge slots, pubkey attributes, script wiring.

    relay_req is patched with one synthetic Kind 1 note so tests stay hermetic
    and fast while still rendering real card markup through feed.html.
    """

    @classmethod
    def setUpTestData(cls):
        cls.relay_events = {
            "e1": make_event("e1", 1, content="trust lens fixture note"),
        }

    def _get_feed(self):
        with patch("apps.core.views.relay_req", return_value=self.relay_events):
            return self.client.get(reverse("feed"))

    def test_anonymous_feed_returns_200(self):
        response = self._get_feed()
        self.assertEqual(response.status_code, 200)

    def test_authenticated_feed_returns_200(self):
        user = User.objects.create_user(username="did:key:z6Mktrustlens")
        self.client.force_login(user)
        response = self._get_feed()
        self.assertEqual(response.status_code, 200)

    def test_feed_contains_author_pubkey_attribute(self):
        response = self._get_feed()
        self.assertContains(response, "data-pubkey=")

    def test_feed_contains_author_badge_slot(self):
        response = self._get_feed()
        self.assertContains(response, 'class="author-badge-slot"')
        self.assertContains(response, "data-author-slot=")

    def test_feed_loads_trust_lens_script(self):
        response = self._get_feed()
        self.assertContains(response, "trust_lens.js")

    def test_feed_wires_trust_lens_scan_on_domContentLoaded(self):
        response = self._get_feed()
        self.assertContains(response, "trustLens.scan")

