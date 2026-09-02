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

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.core.views import did_to_pubkey

User = get_user_model()

FULL_HEX = "039daaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"


class ApiChatSessionTest(TestCase):
    def test_api_chat_session_requires_auth(self):
        response = self.client.get(reverse("api_chat_session"))
        self.assertEqual(response.status_code, 401)
        payload = response.json()
        self.assertIs(payload.get("success"), False)

    def test_api_chat_session_returns_canonical_jid_and_ws(self):
        user = User.objects.create_user(username=f"did:iyou:0x{FULL_HEX}")
        self.client.force_login(user)

        response = self.client.get(reverse("api_chat_session"))
        self.assertEqual(response.status_code, 200)
        payload = response.json()

        resolved_hex = did_to_pubkey(user.username)
        domain = getattr(settings, "XMPP_DOMAIN", "127.0.0.1")
        ws_url = getattr(
            settings,
            "XMPP_WS_URL",
            "wss://home.iyou.me:5222/xmpp-websocket",
        )

        self.assertEqual(payload.get("success"), True)
        self.assertEqual(payload.get("pubkey_hex"), resolved_hex)
        self.assertEqual(payload.get("domain"), domain)
        self.assertEqual(payload.get("ws_url"), ws_url)
        self.assertEqual(payload.get("jid"), f"{resolved_hex}@{domain}")
        self.assertTrue(payload.get("jid").startswith(f"{FULL_HEX}@"))

    def test_api_chat_session_persists_xmpp_token(self):
        user = User.objects.create_user(username=f"did:iyou:0x{FULL_HEX}")
        self.client.force_login(user)

        self.client.get(reverse("api_chat_session"))
        session = self.client.session
        self.assertIn("xmpp_token", session)
        self.assertTrue(session["xmpp_token"])


class ChatSessionBootstrapTest(TestCase):
    def test_chat_view_renders_session_bootstrap_script(self):
        user = User.objects.create_user(username=f"did:iyou:0x{FULL_HEX}")
        self.client.force_login(user)
        response = self.client.get(reverse("chat"))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn("/api/chat/session/", content)
        self.assertIn("converse.initialize", content)
        # The bootstrap must reference the session-driven credentials.
        self.assertIn("session.ws_url", content)
        self.assertIn("session.jid", content)


class Nip04CryptoContractTest(TestCase):
    def test_chat_view_context_includes_nip04_bridge_contracts(self):
        bridge_src = (settings.BASE_DIR / "static" / "js" / "bridge_client.js").read_text()
        chat_src = (settings.BASE_DIR / "static" / "js" / "floating_chat.js").read_text()
        for marker in (
            "NIP04_ENCRYPT",
            "NIP04_DECRYPT",
            "nip04Encrypt",
            "nip04Decrypt",
            "encrypted_payload",
        ):
            self.assertIn(marker, bridge_src)
        for marker in (
            "nip04Encrypt",
            "nip04Decrypt",
            "kind: 4",
            "NIP-04 E2EE Session",
            "Sovereign Enclave Mesh",
        ):
            self.assertIn(marker, chat_src)

    def test_floating_dock_template_renders_encryption_badge_containers(self):
        user = User.objects.create_user(username=f"did:iyou:0x{FULL_HEX}")
        self.client.force_login(user)
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('id="docked-chat-windows"', content)
        self.assertIn('id="floating-dock-security-status"', content)
        self.assertIn('id="dock-security-badge-e2ee"', content)
        self.assertIn('id="dock-security-badge-mesh"', content)
        self.assertIn("NIP-04 E2EE Session", content)
        self.assertIn("Sovereign Enclave Mesh", content)
