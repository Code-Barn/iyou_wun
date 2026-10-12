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
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import NoReverseMatch, reverse

User = get_user_model()

FULL_HEX = "039daaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"


class ChatRedirectViewTest(TestCase):
    def test_chat_redirect_issues_302_to_iyou_chat_origin(self):
        expected_origin = getattr(
            settings,
            "IYOU_CHAT_ORIGIN",
            "http://127.0.0.1:8017" if settings.DEBUG else "https://chat.iyou.me",
        )
        response = self.client.get(reverse("chat"))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], f"{expected_origin}/")

    def test_chat_redirect_with_peer_parameter(self):
        expected_origin = getattr(
            settings,
            "IYOU_CHAT_ORIGIN",
            "http://127.0.0.1:8017" if settings.DEBUG else "https://chat.iyou.me",
        )
        peer = FULL_HEX
        response = self.client.get(f"{reverse('chat')}?peer={peer}")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], f"{expected_origin}/?peer={peer}")

    @override_settings(IYOU_CHAT_ORIGIN="https://custom-chat.iyou.me")
    def test_chat_redirect_uses_custom_origin(self):
        response = self.client.get(reverse("chat"))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "https://custom-chat.iyou.me/")

    def test_chat_redirect_for_authenticated_user(self):
        user = User.objects.create_user(username=f"did:key:z6Mk{FULL_HEX[:16]}")
        self.client.force_login(user)
        expected_origin = getattr(
            settings,
            "IYOU_CHAT_ORIGIN",
            "http://127.0.0.1:8017" if settings.DEBUG else "https://chat.iyou.me",
        )
        response = self.client.get(reverse("chat"))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], f"{expected_origin}/")


class ApiChatSessionDeprecationTest(TestCase):
    def test_api_chat_session_reverse_raises_no_reverse_match(self):
        with self.assertRaises(NoReverseMatch):
            reverse("api_chat_session")

    def test_api_chat_session_endpoint_returns_404(self):
        response = self.client.get("/api/chat/session/")
        self.assertEqual(response.status_code, 404)


class DockEmbedIntegrationTest(TestCase):
    def test_dock_embed_mounted_for_authenticated_users(self):
        user = User.objects.create_user(username=f"did:iyou:0x{FULL_HEX}")
        self.client.force_login(user)
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "dock_embed.js")
        self.assertContains(response, "data-chat-origin")

    def test_dock_embed_omitted_for_anonymous_users(self):
        with patch("apps.core.views.relay_req", return_value={}):
            response = self.client.get(reverse("feed"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "dock_embed.js")

    def test_nav_chat_toggle_btn_rendered_with_guards_and_unread_pill(self):
        with patch("apps.core.views.relay_req", return_value={}):
            response = self.client.get(reverse("feed"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="nav-chat-toggle-btn"')
        self.assertContains(response, 'id="nav-chat-unread-pill"')
        self.assertContains(response, "window.IyouChatDock.toggle()")
        self.assertContains(response, "!event.metaKey && !event.ctrlKey")

