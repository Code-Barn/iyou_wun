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
import logging
import urllib.request
import urllib.error

from django.test import TestCase
from django.contrib.auth.models import User
from django.urls import reverse
from django.conf import settings

logger = logging.getLogger(__name__)


class HomeViewTest(TestCase):
    def test_home_returns_200(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)

    def test_home_uses_correct_template(self):
        response = self.client.get("/")
        self.assertTemplateUsed(response, "home.html")

    def test_home_contains_login_button(self):
        response = self.client.get("/")
        self.assertContains(response, "Login with iYou Identity")


class DashboardViewTest(TestCase):
    def test_dashboard_redirects_anonymous(self):
        response = self.client.get("/dashboard")
        self.assertEqual(response.status_code, 302)

    def test_dashboard_redirects_to_oidc_login(self):
        response = self.client.get("/dashboard")
        self.assertIn(reverse("oidc_authentication_init"), response.url)

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
        self.assertContains(response, "Logout")


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

    def test_redirects_to_oidc_login(self):
        response = self.client.get(reverse("chat"))
        self.assertIn(reverse("oidc_authentication_init"), response.url)

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
        self.assertContains(response, "127.0.0.1:5222")

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
        self.assertContains(response, "Logout")


class GalleryViewTest(TestCase):
    def test_redirects_anonymous(self):
        response = self.client.get(reverse("gallery"))
        self.assertEqual(response.status_code, 302)

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
