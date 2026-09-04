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
import ssl
import urllib.request
import urllib.error
from unittest.mock import patch, MagicMock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.contrib.auth.models import User
from django.urls import reverse
from django.conf import settings

from .helpers import make_event, VALID_PUBKEY_HEX
from apps.core.views import hex_to_npub
from apps.core.models import UserLinkDeck, UserLinkItem



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

    def test_dashboard_renders_stream_language_selector(self):
        user = User.objects.create_user(username="did:iyou:0xlanguagetesthub")
        self.client.force_login(user)
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="setting-stream-lang"')
        self.assertContains(response, "Stream Language Filter")
        self.assertContains(response, 'value="all"')
        self.assertContains(response, 'value="en"')
        self.assertContains(response, 'value="es"')

    def test_dashboard_settings_renders_all_three_hygiene_controls(self):
        user = User.objects.create_user(username="did:iyou:0xhygienecards")
        self.client.force_login(user)
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="setting-nsfw-pref"')
        self.assertContains(response, 'id="setting-stream-lang"')
        self.assertContains(response, 'id="setting-noise-gate"')
        self.assertContains(response, "Sensitive Media / NSFW (NIP-36)")
        self.assertContains(response, "Stream Language Filter")
        self.assertContains(response, "Machine Noise Gate (Bot Filter)")

    def test_base_template_renders_jump_to_top_button(self):
        user = User.objects.create_user(username="did:iyou:0xtopbuttonuser")
        self.client.force_login(user)
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="jump-to-top-btn"')
        self.assertContains(response, 'aria-label="Jump to top"')

    def test_base_template_renders_floating_chat_dock_for_authenticated_users(self):
        user = User.objects.create_user(username="did:iyou:0xdockchatuser")
        self.client.force_login(user)
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="floating-chat-root"')
        self.assertContains(response, 'id="floating-chat-toggle-btn"')
        self.assertContains(response, 'id="chat-roster-popover"')
        self.assertContains(response, "floating_chat.js")

    def test_floating_chat_dock_rendered_on_feed_and_dashboard(self):
        user = User.objects.create_user(username="did:iyou:0xdockfeedgal")
        self.client.force_login(user)

        # Authenticated Feed + Dashboard (relay_req patched to stay hermetic)
        with patch("apps.core.views.relay_req", return_value={}):
            feed_response = self.client.get(reverse("feed"))
            dashboard_response = self.client.get(reverse("dashboard"))
        self.assertEqual(feed_response.status_code, 200)
        self.assertContains(feed_response, 'id="floating-chat-root"')
        self.assertContains(feed_response, "floating_chat.js")
        self.assertEqual(dashboard_response.status_code, 200)
        self.assertContains(dashboard_response, 'id="floating-chat-root"')
        self.assertContains(dashboard_response, "floating_chat.js")

    def test_floating_chat_dock_omitted_on_chat_view(self):
        user = User.objects.create_user(username="did:iyou:0xdockchatomit")
        self.client.force_login(user)
        response = self.client.get(reverse("chat"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'id="floating-chat-root"')
        self.assertNotContains(response, "floating_chat.js")

    def test_dashboard_renders_moderation_management_roster(self):
        user = User.objects.create_user(username="did:iyou:0xmodroster")
        self.client.force_login(user)
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="moderation-roster-container"')
        self.assertContains(response, 'id="muted-accounts-list"')
        self.assertContains(response, 'id="blocked-accounts-list"')
        self.assertContains(response, 'id="hidden-notes-list"')
        self.assertContains(response, "Client-Side Moderation &amp; Muted Accounts")

    def test_dashboard_renders_moderation_empty_placeholders(self):
        user = User.objects.create_user(username="did:iyou:0xmodempty")
        self.client.force_login(user)
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No muted accounts.")
        self.assertContains(response, "No blocked accounts.")
        self.assertContains(response, "No hidden notes.")


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
        # The Converse JID localpart must be the 64-char pubkey hex derived from
        # the DID, not the raw `did:key:...` string.
        from apps.core.views import did_to_pubkey
        pubkey_hex = did_to_pubkey("did:key:z6Mkjidtest")
        self.assertTrue(pubkey_hex)
        self.assertIn(f"{pubkey_hex}@127.0.0.1", content)
        self.assertNotIn("did:key:z6Mkjidtest@", content)

    def test_chat_renders_embedded_layout_and_loading_spinner(self):
        user = User.objects.create_user(username="did:key:z6Mkspin123")
        self.client.force_login(user)
        response = self.client.get(reverse("chat"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="chat-loading-overlay"')
        self.assertContains(response, 'id="conversejs-wrap"')
        self.assertContains(response, "view_mode: 'embedded'")
        self.assertContains(response, "show_controlbox_by_default: true")
        self.assertContains(response, "singleton: false")
        self.assertContains(response, "converse.plugins.add('iyou-lifecycle'")
        self.assertContains(response, "_converse.api.listen.on('connected', dismissLoadingSpinner)")
        self.assertContains(response, "_converse.api.listen.on('statusInitialized', dismissLoadingSpinner)")

    def test_chat_retains_l1_and_l2_headers(self):
        user = User.objects.create_user(username="did:key:z6Mklayers123")
        self.client.force_login(user)
        response = self.client.get(reverse("chat"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "sovereign-ecosystem-topbar")
        self.assertContains(response, "iyou")
        self.assertContains(response, "_wun")
        self.assertContains(response, "[ 💬 Chat ]")

    def test_chat_renders_script_type_module(self):
        user = User.objects.create_user(username="did:key:z6Mkesmtest")
        self.client.force_login(user)
        response = self.client.get(reverse("chat"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '<script type="module">')
        # Converse loads via the UMD build (window.converse) — no broken ESM
        # default import from the minified bundle.
        self.assertContains(response, "cdn.conversejs.org/10.1.7/dist/converse.min.js")
        self.assertNotContains(response, "import converse from 'https://cdn.conversejs.org/10.1.7/dist/converse.min.js'")
        self.assertContains(response, "const converse = window.converse || self.converse;")
        self.assertContains(response, "auto_join_private_chats: autoJoinChats")

    def test_chat_view_passes_peer_context(self):
        user = User.objects.create_user(username="did:key:z6Mkpeerctx")
        self.client.force_login(user)
        response = self.client.get(reverse("chat") + "?peer=npub1testpeer123")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["peer_target"], "npub1testpeer123")
        self.assertContains(response, 'window.peerTarget = "npub1testpeer123"')
        self.assertContains(response, "auto-open-peer")





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

    def test_gallery_view_renders_plyr_and_categorized_decks(self):
        pk = "a" * 64
        img_event = make_event("k1063_img", 1063, pubkey=pk, created_at=1700000100, tags=[
            ["url", "https://cdn.example.com/art.jpg"],
            ["m", "image/jpeg"],
            ["alt", "Sovereign Painting"]
        ])
        vid_event = make_event("k1063_vid", 1063, pubkey=pk, created_at=1700000200, tags=[
            ["url", "https://cdn.example.com/video.mp4"],
            ["m", "video/mp4"],
            ["alt", "Mesh Demo"],
            ["dim", "1920x1080"],
            ["duration", "45"]
        ])
        aud_event = make_event("k1063_aud", 1063, pubkey=pk, created_at=1700000300, tags=[
            ["url", "https://cdn.example.com/podcast.mp3"],
            ["m", "audio/mpeg"],
            ["alt", "Decentralized Podcast"],
            ["duration", "120"]
        ])
        relay_events = {"img": img_event, "vid": vid_event, "aud": aud_event}

        with patch("apps.core.views.relay_req", return_value=relay_events):
            response = self.client.get(reverse("gallery"))
            self.assertEqual(response.status_code, 200)
            self.assertTemplateUsed(response, "gallery.html")
            self.assertContains(response, "plyr.css")
            self.assertContains(response, "plyr.polyfilled.js")
            self.assertContains(response, "plyr-video-container")
            self.assertContains(response, "gallery-video-player")
            self.assertContains(response, "audio-play-btn")
            self.assertContains(response, "scrubber")
            self.assertContains(response, "gallery-pagination-sentinel")
            self.assertEqual(response.context["counts"]["images"], 1)
            self.assertEqual(response.context["counts"]["videos"], 1)
            self.assertEqual(response.context["counts"]["audio"], 1)
            self.assertEqual(response.context["counts"]["all"], 3)

    def test_api_gallery_cursor_pagination(self):
        pk = "b" * 64
        img_event = make_event("k1063_img2", 1063, pubkey=pk, created_at=1700000010, tags=[
            ["url", "https://cdn.example.com/pic.png"],
            ["m", "image/png"]
        ])
        vid_event = make_event("k1063_vid2", 1063, pubkey=pk, created_at=1700000020, tags=[
            ["url", "https://cdn.example.com/short.mp4"],
            ["m", "video/mp4"],
            ["dim", "1080x1920"]
        ])
        aud_event = make_event("k1063_aud2", 1063, pubkey=pk, created_at=1700000030, tags=[
            ["url", "https://cdn.example.com/song.mp3"],
            ["m", "audio/mpeg"]
        ])
        relay_events = {"img": img_event, "vid": vid_event, "aud": aud_event}

        with patch("apps.core.views.relay_req", return_value=relay_events):
            # 1. Fetch All
            res = self.client.get(reverse("api_gallery"), {"until": "1700000100", "type": "all"})
            self.assertEqual(res.status_code, 200)
            data = res.json()
            self.assertTrue(data["success"])
            self.assertEqual(len(data["media"]), 3)
            self.assertEqual(data["oldest_timestamp"], 1700000010)

            # 2. Fetch Videos Only
            res_vid = self.client.get(reverse("api_gallery"), {"type": "videos"})
            self.assertEqual(res_vid.status_code, 200)
            data_vid = res_vid.json()
            self.assertEqual(len(data_vid["media"]), 1)
            self.assertEqual(data_vid["media"][0]["media_type"], "video")

            # 3. Fetch Audio Only
            res_aud = self.client.get(reverse("api_gallery"), {"type": "audio"})
            self.assertEqual(res_aud.status_code, 200)
            data_aud = res_aud.json()
            self.assertEqual(len(data_aud["media"]), 1)
            self.assertEqual(data_aud["media"][0]["media_type"], "audio")

            # 4. Fetch Images Only
            res_img = self.client.get(reverse("api_gallery"), {"type": "images"})
            self.assertEqual(res_img.status_code, 200)
            data_img = res_img.json()
            self.assertEqual(len(data_img["media"]), 1)
            self.assertEqual(data_img["media"][0]["media_type"], "image")


class ProfileViewTest(TestCase):
    def test_invalid_npub_returns_error(self):
        response = self.client.get(reverse("profile", kwargs={"npub": "invalid"}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Peer Not Found on Mesh")

    def test_valid_npub_renders_profile_page_with_streams_and_actions(self):
        pk = "3bf0c63fcb93463407af97a5e5ee64fa883d107ef9e558472c4eb9aaaefa459d"
        npub = hex_to_npub(pk)

        k0_event = make_event("k0_prof_1", 0, pubkey=pk, created_at=1700000000, content=json.dumps({
            "name": "Alice Creator",
            "about": "Decentralized builder",
            "picture": "http://example.com/avatar.jpg",
            "banner": "http://example.com/banner.jpg",
            "nip05": "alice@iyou.me",
            "lud16": "alice@getalby.com"
        }))
        k1_post = make_event("k1_post_1", 1, pubkey=pk, created_at=1700000100, content="Hello from my profile!")
        k1_reply = make_event("k1_reply_1", 1, pubkey=pk, created_at=1700000200, content="Replying here", tags=[["e", "some_parent_id", "", "reply"]])
        k1063_media = make_event("k1063_media_1", 1063, pubkey=pk, created_at=1700000300, content="Media asset note", tags=[
            ["url", "https://cdn.iyou.me/profile_art.png"],
            ["m", "image/png"],
        ])

        relay_data = {
            "k0_1": k0_event,
            "k1_1": k1_post,
            "k1_2": k1_reply,
            "k1063_1": k1063_media,
        }

        peer_user = User.objects.create_user(username="did:key:z6Mkpeeruser1")
        self.client.force_login(peer_user)

        with patch("apps.core.views.relay_req", return_value=relay_data):
            response = self.client.get(reverse("profile", kwargs={"npub": npub}))


        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "profile.html")
        self.assertTemplateUsed(response, "base.html")
        self.assertContains(response, "Alice Creator")
        self.assertContains(response, "alice@iyou.me")
        self.assertContains(response, "follow-action-btn")
        self.assertContains(response, "author-badge-slot")
        self.assertContains(response, "Posts (0)")
        self.assertContains(response, "Replies (0)")
        self.assertContains(response, "Media (0)")
        self.assertContains(response, 'data-hydrate-profile="true"')
        self.assertContains(response, "http://example.com/avatar.jpg")
        self.assertContains(response, "http://example.com/banner.jpg")

    def test_profile_owner_shows_edit_button_and_hides_follow_btn(self):
        pk = "3bf0c63fcb93463407af97a5e5ee64fa883d107ef9e558472c4eb9aaaefa459d"
        npub = hex_to_npub(pk)
        user = User.objects.create_user(username=f"did:iyou:0x{pk}")
        self.client.force_login(user)

        with patch("apps.core.views.relay_req", return_value={}):
            response = self.client.get(reverse("profile", kwargs={"npub": npub}))

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["is_owner"])
        self.assertContains(response, "Edit Profile")
        self.assertNotContains(response, "id=\"follow-action-btn\"")

    def test_profile_view_falls_back_to_local_deck_when_relays_have_no_kind0(self):
        pk = "1111111111111111111111111111111111111111111111111111111111111111"
        npub = hex_to_npub(pk)
        user = User.objects.create_user(username=f"did:iyou:0x{pk}")
        UserLinkDeck.objects.create(
            user=user,
            handle="localdeckmaster",
            display_name="Local Deck Master",
            headline="Decentralized mesh engineer from DB",
            avatar_url="https://example.com/db_avatar.png",
            banner_url="https://example.com/db_banner.png",
            nip05="master@iyou.me",
            lud16="master@getalby.com",
        )

        with patch("apps.core.views.relay_req", return_value={}):
            response = self.client.get(reverse("profile", kwargs={"npub": npub}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Local Deck Master")
        self.assertContains(response, "Decentralized mesh engineer from DB")
        self.assertContains(response, "https://example.com/db_avatar.png")
        self.assertContains(response, "https://example.com/db_banner.png")
        self.assertContains(response, "master@iyou.me")

    def test_profile_renders_message_button_for_authenticated_viewer(self):
        pk = "3bf0c63fcb93463407af97a5e5ee64fa883d107ef9e558472c4eb9aaaefa459d"
        npub = hex_to_npub(pk)

        # 1. Authenticated user viewing another profile sees .action-btn-direct-message with valid data-chat-target-pubkey
        peer_user = User.objects.create_user(username="did:key:z6Mkpeeruser2")
        self.client.force_login(peer_user)

        with patch("apps.core.views.relay_req", return_value={}):
            response = self.client.get(reverse("profile", kwargs={"npub": npub}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "action-btn-direct-message")
        self.assertContains(response, f'data-chat-target-pubkey="{pk}"')
        self.assertContains(response, "💬")
        self.assertContains(response, "Message")

        # 2. Authenticated user viewing their own profile does not render the button
        owner_user = User.objects.create_user(username=f"did:iyou:0x{pk}")
        self.client.force_login(owner_user)

        with patch("apps.core.views.relay_req", return_value={}):
            owner_response = self.client.get(reverse("profile", kwargs={"npub": npub}))

        self.assertEqual(owner_response.status_code, 200)
        self.assertNotContains(owner_response, "action-btn-direct-message")

        # 3. Unauthenticated user does not render the button
        self.client.logout()

        with patch("apps.core.views.relay_req", return_value={}):
            anon_response = self.client.get(reverse("profile", kwargs={"npub": npub}))

        self.assertEqual(anon_response.status_code, 200)
        self.assertNotContains(anon_response, "action-btn-direct-message")

    def test_profile_renders_direct_message_button(self):
        self.test_profile_renders_message_button_for_authenticated_viewer()

    def test_base_template_omits_floating_chat_dock_for_anonymous_users(self):
        with patch("apps.core.views.relay_req", return_value={}):
            response = self.client.get(reverse("feed"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'id="floating-chat-root"')
        self.assertNotContains(response, "floating_chat.js")


class DashboardProfileTest(TestCase):
    def test_dashboard_contains_profile_section(self):
        user = User.objects.create_user(username="did:key:z6Mkdashprofile")
        self.client.force_login(user)
        response = self.client.get(reverse("dashboard"))
        self.assertContains(response, "Sovereign Profile")

    def test_dashboard_renders_relay_switchboard_toggles(self):
        user = User.objects.create_user(username="did:key:z6Mkdashrelay")
        self.client.force_login(user)
        with patch("apps.core.views.relay_req", return_value={}):
            response = self.client.get(reverse("dashboard"))
        self.assertContains(response, "Sovereign Switchboard")
        self.assertContains(response, "relay-toggle-checkbox")
        self.assertContains(response, "data-relay-url=")
        self.assertContains(response, "toggleRelayState(")
        self.assertContains(response, "Save Relays")

    def test_dashboard_contains_publish_button(self):
        user = User.objects.create_user(username="did:key:z6Mkdashpub")
        self.client.force_login(user)
        response = self.client.get(reverse("dashboard"))
        self.assertContains(response, "Publish Profile")

    def test_api_save_profile_persists_metadata(self):
        user = User.objects.create_user(username="did:key:z6Mksaveprof1")
        self.client.force_login(user)
        payload = {
            "name": "Sovereign Alice",
            "about": "Decentralized mesh architect",
            "picture": "https://example.com/alice.png",
            "banner": "https://example.com/banner.png",
            "nip05": "alice@iyou.me",
            "lud16": "alice@getalby.com",
        }
        response = self.client.post(
            reverse("api_save_profile"),
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["profile"]["name"], "Sovereign Alice")
        self.assertEqual(data["profile"]["lud16"], "alice@getalby.com")

    def test_api_save_profile_persists_display_name_independently_from_handle(self):
        user = User.objects.create_user(username="did:key:z6Mkhandletest1")
        deck = UserLinkDeck.objects.create(
            user=user,
            handle="constant_handle",
            display_name="Initial Name",
            headline="Initial bio",
        )
        self.client.force_login(user)

        payload = {
            "name": "Updated Mutable Name",
            "about": "Updated mutable bio",
            "picture": "https://example.com/new_pic.png",
        }
        response = self.client.post(
            reverse("api_save_profile"),
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        deck.refresh_from_db()
        self.assertEqual(deck.handle, "constant_handle")
        self.assertEqual(deck.display_name, "Updated Mutable Name")
        self.assertEqual(deck.headline, "Updated mutable bio")
        self.assertEqual(deck.avatar_url, "https://example.com/new_pic.png")


    def test_standard_header_renders_persona_switcher_for_authenticated_user(self):
        pk = "3bf0c63fcb93463407af97a5e5ee64fa883d107ef9e558472c4eb9aaaefa459d"
        user = User.objects.create_user(username=f"did:iyou:0x{pk}")
        self.client.force_login(user)
        with patch("apps.core.views.relay_req", return_value={}):
            response = self.client.get(reverse("feed"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="persona-switcher-container"')
        self.assertContains(response, 'id="persona-switcher-btn"')
        self.assertContains(response, 'id="active-persona-dot"')
        self.assertContains(response, 'id="active-persona-display-name"')
        self.assertContains(response, 'id="active-persona-level"')
        self.assertContains(response, 'id="persona-switcher-dropdown"')
        self.assertContains(response, 'id="persona-list-container"')
        self.assertContains(response, "togglePersonaDropdown()")
        self.assertContains(response, "Active Enclave Personas")
        self.assertContains(response, "Manage in iyou_home")
        self.assertContains(response, "[ ⚙️ Edit ]")

    def test_standard_header_renders_persona_dropdown_with_timeout_container(self):
        pk = "3bf0c63fcb93463407af97a5e5ee64fa883d107ef9e558472c4eb9aaaefa459d"
        user = User.objects.create_user(username=f"did:iyou:0x{pk}")
        self.client.force_login(user)
        with patch("apps.core.views.relay_req", return_value={}):
            response = self.client.get(reverse("feed"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="persona-list-container"')
        self.assertContains(response, 'id="persona-bridge-status"')
        self.assertContains(response, "Querying local vault personas...")

    def test_nav_renders_mobile_health_indicator(self):
        with patch("apps.core.views.relay_req", return_value={}):
            response = self.client.get(reverse("feed"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="mobile-bridge-dot"')
        self.assertContains(response, 'id="mobile-bridge-label"')

    def test_standard_header_displays_user_handle_when_available(self):
        pk = "3bf0c63fcb93463407af97a5e5ee64fa883d107ef9e558472c4eb9aaaefa459d"
        user = User.objects.create_user(username=f"did:iyou:0x{pk}")
        UserLinkDeck.objects.create(user=user, handle="@alice_sovereign")
        self.client.force_login(user)
        with patch("apps.core.views.relay_req", return_value={}):
            response = self.client.get(reverse("feed"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "@alice_sovereign")
        self.assertContains(response, 'id="active-persona-display-name"')

    def test_feed_view_renders_two_column_layout_and_right_rail(self):
        with patch("apps.core.views.relay_req", return_value={}):
            response = self.client.get(reverse("feed"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "lg:col-span-8")
        self.assertContains(response, "lg:col-span-4")
        self.assertContains(response, "TRENDING TOPICS")

    def test_sovereign_creators_render_valid_profile_links(self):
        viewer_pk = "3bf0c63fcb93463407af97a5e5ee64fa883d107ef9e558472c4eb9aaaefa459d"
        viewer = User.objects.create_user(username=f"did:iyou:0x{viewer_pk}")
        creator_user = User.objects.create_user(username="did:key:z6Mkcreatorlink1")
        UserLinkDeck.objects.create(
            user=creator_user,
            handle="@verified_creator",
            display_name="Verified Creator",
            avatar_url="https://example.com/creator_avatar.png",
            is_public=True,
            is_verified=True,
        )
        self.client.force_login(viewer)
        with patch("apps.core.views.relay_req", return_value={}):
            response = self.client.get(reverse("feed"))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('id="sovereign-creators-list"', content)
        # The whole creator row links to /profile/<handle>/ with the leading
        # @ stripped so the route resolves without 404/regex mismatches.
        self.assertIn('href="/profile/verified_creator"', content)
        self.assertIn("Verified Creator", content)
        self.assertIn("@verified_creator", content)
        self.assertIn("https://example.com/creator_avatar.png", content)

    def test_dashboard_toast_is_hidden_by_default(self):
        user = User.objects.create_user(username="did:key:z6Mktoasthidden1")
        self.client.force_login(user)
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        # The legacy #toast element must carry the hidden state in server HTML
        # so no phantom toast renders on initial page load.
        toast_snippet = content.split('id="toast"', 1)
        self.assertEqual(len(toast_snippet), 2)
        opening_tag = toast_snippet[1].split(">", 1)[0]
        self.assertIn("hidden", opening_tag)
        self.assertNotIn("alert(", content)

    def test_standard_header_omits_persona_switcher_when_anonymous(self):
        with patch("apps.core.views.relay_req", return_value={}):
            response = self.client.get(reverse("feed"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'id="persona-switcher-container"')
        self.assertNotContains(response, 'id="persona-switcher-btn"')

    def test_post_composer_renders_active_persona_badge(self):
        pk = "3bf0c63fcb93463407af97a5e5ee64fa883d107ef9e558472c4eb9aaaefa459d"
        user = User.objects.create_user(username=f"did:iyou:0x{pk}")
        self.client.force_login(user)
        with patch("apps.core.views.relay_req", return_value={}):
            response = self.client.get(reverse("feed"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="composer-active-persona-badge"')
        self.assertContains(response, "Posting as:")

    def test_global_feed_queries_relays_without_authors_filter(self):
        with patch("apps.core.views.relay_req", return_value={}) as mock_relay_req:
            response = self.client.get(reverse("feed") + "?circle=global")
            self.assertEqual(response.status_code, 200)
            self.assertTrue(mock_relay_req.called)
            filter_obj = mock_relay_req.call_args[0][0]
            self.assertNotIn("authors", filter_obj)

    def test_api_feed_global_queries_relays_without_authors_filter(self):
        with patch("apps.core.views.relay_req", return_value={}) as mock_relay_req:
            response = self.client.get(reverse("api_feed") + "?circle=global")
            self.assertEqual(response.status_code, 200)
            self.assertTrue(mock_relay_req.called)
            filter_obj = mock_relay_req.call_args[0][0]
            self.assertNotIn("authors", filter_obj)

    def test_api_feed_global_returns_non_empty_notes_without_authors_filter(self):
        pk = "b1c6d3f8a2e94c705d2a97c13b6f4e283ad0f19c64e8b527a3d7f6c0e12ab845"
        mock_events = {
            "ev_global_1": {
                "id": "ev_global_1",
                "pubkey": pk,
                "created_at": 1700000000,
                "kind": 1,
                "tags": [],
                "content": "Global mesh broadcast note",
                "sig": "sig_mock",
            }
        }
        with patch("apps.core.views.relay_req", return_value=mock_events) as mock_relay_req:
            response = self.client.get(reverse("api_feed") + "?circle=global")
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertTrue(data.get("success"))
            self.assertEqual(len(data.get("notes", [])), 1)
            self.assertEqual(data["notes"][0]["id"], "ev_global_1")
            self.assertTrue(mock_relay_req.called)
            filter_obj = mock_relay_req.call_args[0][0]
            self.assertNotIn("authors", filter_obj)

    def test_api_feed_iyou_maintains_scoped_authors_requirement(self):
        with patch("apps.core.views.get_iyou_pubkeys", return_value=["pk1", "pk2"]), patch("apps.core.views.relay_req", return_value={}) as mock_relay_req:
            response = self.client.get(reverse("api_feed") + "?circle=iyou")
            self.assertEqual(response.status_code, 200)
            self.assertTrue(mock_relay_req.called)
            filter_obj = mock_relay_req.call_args[0][0]
            self.assertEqual(filter_obj.get("authors"), ["pk1", "pk2"])



class DefaultAvatarFallbackTest(TestCase):
    def test_profile_hero_avatar_uses_mesh_default_for_external_peers(self):
        pk = "3bf0c63fcb93463407af97a5e5ee64fa883d107ef9e558472c4eb9aaaefa459d"
        npub = hex_to_npub(pk)
        k0_event = make_event("k0_nopic_1", 0, pubkey=pk, created_at=1700000000, content=json.dumps({
            "name": "Avatarless Alice",
            "about": "No picture yet",
        }))
        k1_post = make_event("k1_nopic_1", 1, pubkey=pk, created_at=1700000100, content="First post")

        relay_data = {"k0_1": k0_event, "k1_1": k1_post}
        user = User.objects.create_user(username="did:key:z6Mkdefaultav1")
        self.client.force_login(user)
        with patch("apps.core.views.relay_req", return_value=relay_data):
            response = self.client.get(reverse("profile", kwargs={"npub": npub}))
        self.assertEqual(response.status_code, 200)
        # An external mesh peer without an avatar renders the neutral globe,
        # not the protected iyou brand mark.
        self.assertContains(response, "img/mesh_avatar_default.svg")

    def test_profile_hero_avatar_uses_iyou_symbol_for_native_creators(self):
        pk = "3bf0c63fcb93463407af97a5e5ee64fa883d107ef9e558472c4eb9aaaefa459d"
        npub = hex_to_npub(pk)
        owner_user = User.objects.create_user(username=pk)
        UserLinkDeck.objects.create(
            user=owner_user,
            handle="brandcreator",
            display_name="Brand Creator",
            is_public=True,
        )
        k0_event = make_event("k0_nopic_1", 0, pubkey=pk, created_at=1700000000, content=json.dumps({
            "name": "Avatarless Alice",
            "about": "No picture yet",
        }))
        k1_post = make_event("k1_nopic_1", 1, pubkey=pk, created_at=1700000100, content="First post")

        relay_data = {"k0_1": k0_event, "k1_1": k1_post}
        user = User.objects.create_user(username="did:key:z6Mkdefaultav1")
        self.client.force_login(user)
        with patch("apps.core.views.relay_req", return_value=relay_data):
            response = self.client.get(reverse("profile", kwargs={"npub": npub}))
        self.assertEqual(response.status_code, 200)
        # Sovereign creators render the protected iyou brand mark.
        self.assertContains(response, "img/iyou_symbol.png")
        self.assertNotContains(response, "img/mesh_avatar_default.svg")

    def test_dashboard_uses_iyou_symbol_when_no_avatar_set(self):
        user = User.objects.create_user(username="did:key:z6Mkdashdefav1")
        self.client.force_login(user)
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "img/iyou_symbol.png")

    def test_right_rail_sovereign_creator_without_avatar_uses_iyou_symbol(self):
        viewer_pk = "3bf0c63fcb93463407af97a5e5ee64fa883d107ef9e558472c4eb9aaaefa459d"
        viewer = User.objects.create_user(username=f"did:iyou:0x{viewer_pk}")
        creator_user = User.objects.create_user(username="did:key:z6Mkcreatordef1")
        UserLinkDeck.objects.create(
            user=creator_user,
            handle="@symbol_creator",
            display_name="Symbol Creator",
            is_public=True,
        )
        self.client.force_login(viewer)
        with patch("apps.core.views.relay_req", return_value={}):
            response = self.client.get(reverse("feed"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Symbol Creator")
        self.assertContains(response, "img/iyou_symbol.png")


class PersonaSessionSwitchTest(TestCase):
    ANCHOR_PK = "3bf0c63fcb93463407af97a5e5ee64fa883d107ef9e558472c4eb9aaaefa459d"

    def _login(self, username):
        user = User.objects.create_user(username=username)
        self.client.force_login(user)
        return user

    def test_api_persona_switch_updates_session_user(self):
        did1 = f"did:iyou:0x{self.ANCHOR_PK}"
        did2 = "did:key:z6Mkpersonaswtest22"
        user1 = self._login(did1)
        UserLinkDeck.objects.create(user=user1, handle="alice_sov", display_name="Alice Sovereign")

        response = self.client.post(
            reverse("api_persona_switch"),
            data=json.dumps({"did": did2, "persona_name": "Burner Runner", "level": 2}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["did"], did2)
        self.assertEqual(data["persona_name"], "Burner Runner")
        self.assertEqual(data["level"], 2)
        self.assertTrue(data["handle"])

        # The new DID is provisioned with its own isolated link deck.
        switched = User.objects.get(username=did2)
        deck2 = UserLinkDeck.objects.get(user=switched)
        self.assertTrue(deck2.handle)
        self.assertNotEqual(deck2.handle, "alice_sov")

        # Subsequent requests run as the new persona.
        dash = self.client.get(reverse("dashboard"))
        self.assertEqual(dash.status_code, 200)
        self.assertContains(dash, did2)
        self.assertNotContains(dash, did1)

        # Switching back restores the original deck untouched (per-DID isolation).
        resp_back = self.client.post(
            reverse("api_persona_switch"),
            data=json.dumps({"did": did1, "persona_name": "", "level": 1}),
            content_type="application/json",
        )
        self.assertEqual(resp_back.status_code, 200)
        self.assertTrue(resp_back.json()["success"])
        user1.refresh_from_db()
        self.assertEqual(UserLinkDeck.objects.get(user=user1).handle, "alice_sov")

    def test_api_persona_switch_gates_method_and_did(self):
        self._login(f"did:iyou:0x{self.ANCHOR_PK}")

        # GET is not allowed.
        get_resp = self.client.get(reverse("api_persona_switch"))
        self.assertEqual(get_resp.status_code, 405)

        # Malformed / non-DID targets are rejected.
        bad_resp = self.client.post(
            reverse("api_persona_switch"),
            data=json.dumps({"did": "3bf0c63fcb93463407af97a5e5ee64fa883d107ef9e558472c4eb9aaaefa459d"}),
            content_type="application/json",
        )
        self.assertEqual(bad_resp.status_code, 400)

        # Anonymous callers are rejected without a challenge signature.
        anon_client = Client()
        anon_resp = anon_client.post(
            reverse("api_persona_switch"),
            data=json.dumps({"did": "did:key:z6Mkanonreject1"}),
            content_type="application/json",
        )
        self.assertEqual(anon_resp.status_code, 401)

    def test_header_display_hierarchy_rules(self):
        anchor_did = f"did:iyou:0x{self.ANCHOR_PK}"
        burner_username = "did:key:z6MknoHandleCCCC"

        with patch("apps.core.views.relay_req", return_value={}):
            # (a) Deck handle outranks persona name.
            u1 = User.objects.create_user(username=anchor_did)
            UserLinkDeck.objects.create(user=u1, handle="carol_sov", display_name="Carol")
            c1 = Client()
            c1.force_login(u1)
            s1 = c1.session
            s1["active_persona_name"] = "Burner"
            s1["active_persona_level"] = 2
            s1.save()
            r1 = c1.get(reverse("feed"))
            self.assertContains(r1, "@carol_sov")
            self.assertNotContains(r1, "Burner (L2)")

            # (b) Persona name (with level) renders when there is no handle.
            u2 = User.objects.create_user(username=burner_username)
            c2 = Client()
            c2.force_login(u2)
            s2 = c2.session
            s2["active_persona_name"] = "Burner"
            s2["active_persona_level"] = 2
            s2.save()
            r2 = c2.get(reverse("feed"))
            self.assertContains(r2, "Burner (L2)")

            # (c) No persona state and level 1 fall back to the generic label.
            c3 = Client()
            c3.force_login(u2)
            r3 = c3.get(reverse("feed"))
            self.assertContains(r3, "Primary Identity (L1)")

            # (d) Higher-level persona without a name formats as truncated DID + level.
            c4 = Client()
            c4.force_login(u2)
            s4 = c4.session
            s4["active_persona_level"] = 2
            s4.save()
            r4 = c4.get(reverse("feed"))
            content = r4.content.decode()
            self.assertIn(burner_username[:16] + "... (L2)", content)
            self.assertNotIn("Primary Identity (L1)", content)

    def test_header_injects_current_session_did(self):
        with patch("apps.core.views.relay_req", return_value={}):
            self._login(f"did:iyou:0x{self.ANCHOR_PK}")
            response = self.client.get(reverse("feed"))
            self.assertContains(
                response,
                f'window.CURRENT_SESSION_DID = "did:iyou:0x{self.ANCHOR_PK}";',
            )

    def test_feed_view_exposes_active_persona_level_and_renders_amber_l2(self):
        user = User.objects.create_user(username=f"did:iyou:0x{self.ANCHOR_PK}")
        client = Client()
        client.force_login(user)
        session = client.session
        session["active_persona_level"] = 2
        session["active_persona_name"] = "Burner Persona"
        session.save()

        with patch("apps.core.views.relay_req", return_value={}):
            response = client.get(reverse("feed"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context.get("active_persona_level"), 2)
        self.assertEqual(response.context.get("active_persona_name"), "Burner Persona")
        content = response.content.decode()
        self.assertIn('id="active-persona-level"', content)
        self.assertIn("L2", content)
        self.assertIn("bg-amber-100", content)
        self.assertIn("text-amber-700", content)

    def test_feed_view_defaults_to_violet_l1_when_level_is_one(self):
        user = User.objects.create_user(username=f"did:iyou:0x{self.ANCHOR_PK}")
        client = Client()
        client.force_login(user)

        with patch("apps.core.views.relay_req", return_value={}):
            response = client.get(reverse("feed"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context.get("active_persona_level"), 1)
        content = response.content.decode()
        self.assertIn('id="active-persona-level"', content)
        self.assertIn("L1", content)
        self.assertIn("bg-violet-100", content)
        self.assertIn("text-violet-700", content)

    def test_persona_switch_idempotent_when_already_active(self):
        did = f"did:iyou:0x{self.ANCHOR_PK}"
        self._login(did)
        initial_session_key = self.client.session.session_key

        resp = self.client.post(
            reverse("api_persona_switch"),
            data=json.dumps({"did": did, "persona_name": "Anchor Sovereign", "level": 1}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["success"])
        self.assertFalse(data["reanchored"])
        self.assertEqual(data["active_did"], did)
        self.assertEqual(data["persona_name"], "Anchor Sovereign")
        # Session key is not cycled/invalidated
        self.assertEqual(self.client.session.session_key, initial_session_key)

    def test_persona_switch_handles_concurrent_linkdeck_creation(self):
        self._login(f"did:iyou:0x{self.ANCHOR_PK}")
        target_did = "did:key:z6MkconcurrentDeck999"

        # Switch to brand new persona without a link deck
        resp = self.client.post(
            reverse("api_persona_switch"),
            data=json.dumps({"did": target_did, "persona_name": "Concurrent Persona", "level": 2}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["success"])
        self.assertTrue(data["reanchored"])
        self.assertTrue(UserLinkDeck.objects.filter(user__username=target_did).exists())

        # Switch again to verify idempotent recovery and existing record reuse
        resp2 = self.client.post(
            reverse("api_persona_switch"),
            data=json.dumps({"did": target_did, "persona_name": "Concurrent Persona", "level": 2}),
            content_type="application/json",
        )
        self.assertEqual(resp2.status_code, 200)
        data2 = resp2.json()
        self.assertTrue(data2["success"])
        self.assertFalse(data2["reanchored"])
        self.assertEqual(UserLinkDeck.objects.filter(user__username=target_did).count(), 1)


class GlobalBridgeClientContractTest(TestCase):
    """Phase 36: bridge_client hoisted to base.html + persona-switch CSRF hardening."""

    def _login(self, username):
        user = User.objects.create_user(username=username)
        self.client.force_login(user)
        return user

    def test_base_loads_bridge_client_globally_and_session_did(self):
        self._login("did:key:z6Mkglobalbridge1")
        with patch("apps.core.views.relay_req", return_value={}):
            response = self.client.get(reverse("feed"))
        content = response.content.decode()
        # bridge_client.js ships once from base.html.
        self.assertEqual(content.count("js/bridge_client.js"), 1)
        # Sub-pages carry the active session identity context.
        self.assertIn("window.CURRENT_SESSION_DID", content)
        self.assertIn('CURRENT_SESSION_DID = "did:key:z6Mkglobalbridge1"', content)

    def test_feed_and_dashboard_do_not_duplicate_bridge_script(self):
        self._login("did:key:z6Mkglobalbridge2")
        with patch("apps.core.views.relay_req", return_value={}):
            feed_resp = self.client.get(reverse("feed"))
            dash_resp = self.client.get(reverse("dashboard"))
        # No per-page bridge_client.js tags remain in page-specific extra_js.
        self.assertEqual(feed_resp.content.decode().count("js/bridge_client.js"), 1)
        self.assertEqual(dash_resp.content.decode().count("js/bridge_client.js"), 1)

    def test_persona_switch_accepts_post_without_csrf_token(self):
        # CSRF enforcement skipped server-side, so the local bridge can re-anchor
        # the session even when the csrftoken cookie is absent on first connect.
        self._login("did:key:z6Mkglobalbridge3")
        from django.test import Client as RawClient
        raw = RawClient(enforce_csrf_checks=True)
        raw.force_login(User.objects.get(username="did:key:z6Mkglobalbridge3"))
        resp = raw.post(
            reverse("api_persona_switch"),
            data=json.dumps({"did": "did:key:z6Mkswitchtarget1", "persona_name": "Sov", "level": 2}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["success"])

    def test_bridge_client_carries_csrf_fallback_and_global_session_did(self):
        src = (settings.BASE_DIR / "static" / "js" / "bridge_client.js").read_text()
        self.assertIn("function getCsrfToken", src)
        self.assertIn('getCookie("csrftoken")', src)
        self.assertIn("name=csrfmiddlewaretoken", src)
        self.assertIn("window.CURRENT_SESSION_DID", src)
        self.assertIn("window.getCsrfToken = getCsrfToken", src)


class BackupGraphTest(TestCase):
    def test_api_backup_export_requires_auth(self):
        response = self.client.get(reverse("api_backup_export"))
        self.assertIn(response.status_code, (302, 401))

    def test_api_backup_export_returns_valid_json_schema(self):
        user = User.objects.create_user(username="did:key:z6Mkbackupexport1")
        deck = UserLinkDeck.objects.create(user=user, handle="@export_handle")
        UserLinkItem.objects.create(
            deck=deck, title="Site", url="https://example.com", icon_category="website", order=0
        )
        self.client.force_login(user)
        response = self.client.get(reverse("api_backup_export"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("attachment", response.get("Content-Disposition", ""))
        data = response.json()
        for key in ("version", "exported_at", "user", "deck", "contacts", "relays", "circles", "muted"):
            self.assertIn(key, data)
        self.assertEqual(data["deck"]["handle"], "@export_handle")
        self.assertEqual(data["deck"]["items"][0]["title"], "Site")

    def test_api_backup_import_restores_user_graph(self):
        user = User.objects.create_user(username="did:key:z6Mkbackupimport1")
        self.client.force_login(user)
        snapshot = {
            "version": 1,
            "user": user.username,
            "deck": {
                "handle": "@restored_handle",
                "display_name": "Restored Sovereign",
                "items": [{"title": "Git", "url": "https://github.com/x", "icon_category": "github"}],
            },
            "contacts": [{"pubkey": "a" * 64, "petname": "alice"}],
            "relays": ["wss://restored.example"],
            "circles": ["inner"],
            "muted": ["b" * 64],
        }
        response = self.client.post(
            reverse("api_backup_import"),
            data=json.dumps(snapshot),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["restored_contacts"], 1)
        self.assertEqual(data["restored_relays"], 1)

        deck = UserLinkDeck.objects.get(user=user)
        self.assertEqual(deck.handle, "restored_handle")
        self.assertEqual(deck.display_name, "Restored Sovereign")
        self.assertEqual(deck.items.count(), 1)
        self.assertEqual(deck.items.first().title, "Git")

    def test_dashboard_renders_backup_recovery_controls(self):
        user = User.objects.create_user(username="did:key:z6Mkbackupcontrols1")
        self.client.force_login(user)
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn("sovereign-backup", content.lower().replace("&amp;", "&"))
        self.assertIn(reverse("api_backup_export"), content)
        self.assertIn("backup-restore-form", content)

    def test_feed_interactions_carries_blossom_fallback_cascade(self):
        src = (settings.BASE_DIR / "static" / "js" / "feed_interactions.js").read_text()
        self.assertIn("handleMediaError", src)
        self.assertIn("http://127.0.0.1:9002/", src)
        self.assertIn("https://cdn.iyou.me/", src)
        self.assertIn("https://nostr.download/", src)
        self.assertIn("data-fallback-tier", src)
        self.assertIn("Media Unavailable on Mesh", src)
        self.assertIn("onerror=\"window.handleMediaError", src)

    def test_relay_pool_carries_auto_quarantine_contract(self):
        src = (settings.BASE_DIR / "static" / "js" / "relay_pool.js").read_text()
        self.assertIn("quarantined", src)
        self.assertIn("QUARANTINE_THRESHOLD", src)
        self.assertIn("retryQuarantinedRelays", src)
        self.assertIn("_recordBroadcastFailure", src)
        self.assertIn("status !== \"quarantined\"", src)

    def test_relay_pool_carries_phase33_toggle_schema(self):
        src = (settings.BASE_DIR / "static" / "js" / "relay_pool.js").read_text()
        self.assertIn("toggleRelayState", src)
        self.assertIn("wun_custom_relays", src)
        self.assertIn("enabled: r.enabled !== false", src)
        self.assertIn("Local Enclave (Desktop/WSS)", src)
        self.assertIn("127.0.0.1:9003", src)
        self.assertIn("isMixedContentRelay", src)
        self.assertIn("window.showToast", src)

    def test_relay_pool_persists_enabled_toggles_across_reloads(self):
        src = (settings.BASE_DIR / "static" / "js" / "relay_pool.js").read_text()
        self.assertIn("getActiveRelayCount", src)
        self.assertIn("if (r.enabled === false) return;", src)
        self.assertIn("persistRelays", src)
        self.assertIn("enabled: r.enabled !== false", src)
        self.assertIn("if (enabledMap.hasOwnProperty(norm)) {\n                    r.enabled = enabledMap[norm];", src)
        self.assertIn("if (record.enabled === false) {\n            record.status = \"offline\";", src)

    def test_feed_interactions_carries_phase33_proxy_fallback(self):
        src = (settings.BASE_DIR / "static" / "js" / "feed_interactions.js").read_text()
        self.assertIn("/api/blossom/proxy/", src)
        self.assertIn('"/api/media/upload/"', src)
        self.assertIn("handleMediaSelected", src)
        self.assertIn("SHA-256", src)


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

    def test_upload_proxy_success_returns_phase33_schema(self):
        file_content = b"schema_probe_bytes"
        uploaded_file = SimpleUploadedFile("schema_probe.jpg", file_content, content_type="image/jpeg")

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_cm = MagicMock()
            mock_cm.__enter__.return_value = MagicMock(status=201)
            mock_urlopen.return_value = mock_cm

            response = self.client.post(
                reverse("media_upload_proxy"),
                {"file": uploaded_file},
            )

        data = response.json()
        self.assertTrue(data["success"])
        self.assertTrue(data["forwarded"])
        self.assertEqual(data["sha256"], hashlib.sha256(file_content).hexdigest())
        self.assertEqual(data["url"], f"https://cdn.iyou.me/{hashlib.sha256(file_content).hexdigest()}")

    def test_blossom_proxy_route_accepts_uploads(self):
        file_content = b"blossom_proxy_route_bytes"
        expected_hash = hashlib.sha256(file_content).hexdigest()
        uploaded_file = SimpleUploadedFile("route.jpg", file_content, content_type="image/jpeg")

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_cm = MagicMock()
            mock_cm.__enter__.return_value = MagicMock(status=201)
            mock_urlopen.return_value = mock_cm

            response = self.client.post(
                reverse("api_blossom_proxy"),
                {"file": uploaded_file},
            )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["sha256"], expected_hash)

    @override_settings(BLOSSOM_SERVER_URL="https://cdn.iyou.me")
    def test_upload_proxy_uses_unverified_ssl_context_for_https_upstream(self):
        file_content = b"tls_verify_off_bytes"
        uploaded_file = SimpleUploadedFile("tls.jpg", file_content, content_type="image/jpeg")

        captured = {}

        def fake_urlopen(req, **kwargs):
            captured["context"] = kwargs.get("context")
            mock_cm = MagicMock()
            mock_cm.__enter__.return_value = MagicMock(status=201)
            return mock_cm

        with patch("urllib.request.urlopen", side_effect=fake_urlopen) as mock_urlopen:
            response = self.client.post(
                reverse("media_upload_proxy"),
                {"file": uploaded_file},
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["success"])
        self.assertTrue(mock_urlopen.called)
        ctx = captured.get("context")
        self.assertIsNotNone(ctx)
        self.assertEqual(ctx.verify_mode, ssl.CERT_NONE)
        self.assertFalse(ctx.check_hostname)

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
        User.objects.create_user(username=f"did:iyou:0x{VALID_PUBKEY_HEX}")
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

    def test_nav_renders_search_results_popover(self):
        response = self._get_feed()
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="search-results-popover"')
        self.assertContains(response, 'id="search-results-list"')
        self.assertContains(response, 'id="feed-search-input"')


class FeedViewTwoTierToolbarTest(TestCase):
    """Two-tier Layer 2 toolbar & circle feed filtering contract tests."""

    @classmethod
    def setUpTestData(cls):
        User.objects.create_user(username=f"did:iyou:0x{VALID_PUBKEY_HEX}")
        cls.relay_events = {
            "e1": make_event("e1", 1, content="circle filter test note", tags=[["t", "nostr"], ["t", "mesh"]]),
        }

    def _get_feed(self):
        with patch("apps.core.views.relay_req", return_value=self.relay_events):
            return self.client.get(reverse("feed"))

    def test_feed_renders_layer2_two_tier_toolbar(self):
        response = self._get_feed()
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="circle-filter-group"')
        self.assertContains(response, 'data-circle="global"')
        self.assertContains(response, 'data-circle="iyou"')
        self.assertContains(response, 'data-circle="following"')
        self.assertContains(response, 'data-circle="inner"')
        self.assertContains(response, 'data-circle="mutual"')
        self.assertContains(response, 'id="active-circle-label"')
        self.assertContains(response, 'id="feed-search-input"')
        self.assertContains(response, "[ 🌐 Global ]")
        self.assertContains(response, "[ ⚡ iyou ]")
        self.assertContains(response, "[ 👥 Following ]")
        self.assertContains(response, "[ 🛡️ Inner Circle ]")
        self.assertContains(response, "[ 🤝 Mutual ]")

    def test_feed_renders_compose_button_for_authenticated_user(self):
        user = User.objects.create_user(username="did:key:z6Mktoolbaruser")
        self.client.force_login(user)
        response = self._get_feed()
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="btn-compose-note"')
        self.assertContains(response, "+ New Note")

    def test_feed_note_cards_have_circle_and_trust_metadata(self):
        response = self._get_feed()
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "feed-note-card")
        self.assertContains(response, "data-author-pubkey=")
        self.assertContains(response, "data-author-did=")
        self.assertContains(response, "data-note-tags=")
        self.assertContains(response, "author-badge-slot")

    def test_feed_loads_circle_feed_filter_script(self):
        response = self._get_feed()
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "circle_feed_filter.js")

    def test_circle_filters_hidden_on_dashboard_and_chat(self):
        user = User.objects.create_user(username="did:key:z6Mkdashuser")
        self.client.force_login(user)

        # Dashboard: circle filter group should NOT be present
        resp_dash = self.client.get(reverse("dashboard"))
        self.assertEqual(resp_dash.status_code, 200)
        self.assertNotContains(resp_dash, 'id="circle-filter-group"')

        # Chat: circle filter group should NOT be present
        resp_chat = self.client.get(reverse("chat"))
        self.assertEqual(resp_chat.status_code, 200)
        self.assertNotContains(resp_chat, 'id="circle-filter-group"')


class FeedModernizationAndExternalAttributionTest(TestCase):

    """Verifies feed modernization, external identity attribution, and 5-button action bar."""

    def setUp(self):
        User.objects.create_user(username=f"did:iyou:0x{VALID_PUBKEY_HEX}")

    def test_external_relay_note_does_not_contain_synthetic_did_or_static_verified_badge(self):
        # External relay note (e.g. jb55 from nos.lol)
        external_pubkey = "32e1827635450ebb3c5a7d12c1f8e7b2b514439ac10a67eef3d9fd9c5c68e245"
        relay_events = {
            "ext_note_1": make_event("ext_note_1", 1, pubkey=external_pubkey, content="Hello decentralized world!"),
        }
        with patch("apps.core.views.relay_req", return_value=relay_events):
            response = self.client.get(reverse("feed") + "?circle=global")

        self.assertEqual(response.status_code, 200)
        # Verify no synthetic did:iyou:0x appears in the HTML
        self.assertNotContains(response, f"did:iyou:0x{external_pubkey}")
        # Verify no static green "Verified" badge is stamped on the unverified external note
        self.assertNotContains(response, '<span class="bg-green-100 text-green-800 text-xs font-medium px-2 py-0.5 rounded-full">Verified</span>')
        self.assertNotContains(response, "Verified</span>")

    def test_feed_renders_5_button_action_bar(self):
        relay_events = {
            "action_note_1": make_event("action_note_1", 1, content="Testing 5-button action bar!"),
        }
        with patch("apps.core.views.relay_req", return_value=relay_events):
            response = self.client.get(reverse("feed"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "action-btn-reply")
        self.assertContains(response, "action-btn-repost")
        self.assertContains(response, "action-btn-like")
        self.assertContains(response, "action-btn-share")
        self.assertContains(response, '<span class="action-svg w-3.5 h-3.5 shrink-0"><svg')

    def test_feed_renders_kebab_menu_with_ecosystem_actions(self):
        relay_events = {
            "kebab_note_1": make_event("kebab_note_1", 1, content="Testing kebab dropdown!"),
        }
        with patch("apps.core.views.relay_req", return_value=relay_events):
            response = self.client.get(reverse("feed"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "kebab-menu-wrap")
        self.assertContains(response, "kebab-toggle-btn")
        self.assertContains(response, "kebab-dropdown")
        self.assertContains(response, "Suggest to Dev")
        self.assertContains(response, "Post of the Day")
        self.assertContains(response, "Set Enclave Petname")
        self.assertContains(response, "View Raw JSON")
        self.assertContains(response, "Copy Event ID / Link")

    def test_kebab_menu_contains_self_moderation_actions(self):
        relay_events = {
            "kebab_mod_note": make_event("kebab_mod_note", 1, content="Testing moderation actions in kebab!"),
        }
        with patch("apps.core.views.relay_req", return_value=relay_events):
            response = self.client.get(reverse("feed"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "hideNote('kebab_mod_note')")
        self.assertContains(response, "muteAuthor(")
        self.assertContains(response, "blockAuthor(")
        self.assertContains(response, "Hide this Note")
        self.assertContains(response, "Mute @")
        self.assertContains(response, "Block @")

    def test_inline_reply_composer_rendered_and_no_legacy_reply_triggers(self):
        relay_events = {
            "inline_reply_note": make_event("inline_reply_note", 1, content="Testing inline reply!"),
        }
        with patch("apps.core.views.relay_req", return_value=relay_events):
            response = self.client.get(reverse("feed"))

        self.assertEqual(response.status_code, 200)
        # Assert no legacy reply trigger / wrapping markup exists in DOM
        self.assertNotContains(response, "&#8617; Reply")
        self.assertNotContains(response, "reply-trigger-")
        self.assertNotContains(response, "reply-editor-wrap-")
        # Assert canonical action bar reply button exists
        self.assertContains(response, "action-btn-reply")
        # Assert clean inline reply drawer exists
        self.assertContains(response, 'id="reply-box-inline_reply_note"')
        self.assertContains(response, 'id="reply-input-inline_reply_note"')
        self.assertContains(response, "Write a sovereign reply...")

    def test_feed_renders_clickable_timestamp_permalink(self):
        relay_events = {
            "perm_note_1": make_event("perm_note_1", 1, content="Testing timestamp permalink!"),
        }
        with patch("apps.core.views.relay_req", return_value=relay_events):
            response = self.client.get(reverse("feed"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'href="/feed?thread=perm_note_1"')
        self.assertContains(response, 'title="View full conversation thread"')

    def test_feed_renders_replying_to_subheader_when_parent_id_present(self):
        parent_pk = "3bf0c63fcb93463407af97a5e5ee64fa883d107ef9e558472c4eb9aaaefa459d"
        relay_events = {
            "parent_post": make_event("parent_post", 1, pubkey=parent_pk, content="Parent note"),
            "reply_post": make_event("reply_post", 1111, pubkey="32e1827635450ebb3c5a7d12c1f8e7b2b514439ac10a67eef3d9fd9c5c68e245", content="Child reply", tags=[
                ["e", "parent_post", "", "root"],
                ["e", "parent_post", "", "reply"],
                ["p", parent_pk, "", "reply"],
            ]),
        }
        with patch("apps.core.views.relay_req", return_value=relay_events):
            response = self.client.get(reverse("feed"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "↳ Replying to")
        self.assertContains(response, "parent_post")

    def test_feed_view_handles_thread_and_note_query_params(self):
        root_event = make_event("target_thread_1", 1, content="Target thread root")
        with patch("apps.core.views.relay_req", return_value={"target_thread_1": root_event}):
            # Test ?thread=
            resp_thread = self.client.get(reverse("feed") + "?thread=target_thread_1")
            self.assertEqual(resp_thread.status_code, 200)
            self.assertTrue(resp_thread.context.get("thread_mode"))
            self.assertEqual(resp_thread.context.get("thread_id"), "target_thread_1")

            # Test ?note=
            resp_note = self.client.get(reverse("feed") + "?note=target_thread_1")
            self.assertEqual(resp_note.status_code, 200)
            self.assertTrue(resp_note.context.get("thread_mode"))
            self.assertEqual(resp_note.context.get("thread_id"), "target_thread_1")

    def test_feed_mode_thread_renders_hero_container_back_button_and_replies(self):
        root_pk = "3bf0c63fcb93463407af97a5e5ee64fa883d107ef9e558472c4eb9aaaefa459d"
        reply_pk = "32e1827635450ebb3c5a7d12c1f8e7b2b514439ac10a67eef3d9fd9c5c68e245"
        relay_events = {
            "hero_root_1": make_event("hero_root_1", 1, pubkey=root_pk, content="Hero thread discussion"),
            "hero_reply_1": make_event("hero_reply_1", 1111, pubkey=reply_pk, content="First thoughtful reply", tags=[
                ["e", "hero_root_1", "", "root"],
                ["e", "hero_root_1", "", "reply"],
                ["p", root_pk, "", "reply"],
            ]),
        }
        with patch("apps.core.views.relay_req", return_value=relay_events):
            response = self.client.get(reverse("feed") + "?thread=hero_root_1")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context.get("notes"), [])
        self.assertEqual(response.context.get("thread_root", {}).get("id"), "hero_root_1")
        self.assertContains(response, "Back to Feed")
        self.assertContains(response, "ring-violet-500/20")
        self.assertContains(response, 'id="reply-input-hero_root_1"')
        self.assertContains(response, "Replies (1)")
        self.assertContains(response, "First thoughtful reply")
        # Global compose button is not rendered in thread mode
        self.assertNotContains(response, 'id="btn-compose-note"')

    def test_open_graph_tags_rendered_in_thread_and_profile(self):
        pk = "3bf0c63fcb93463407af97a5e5ee64fa883d107ef9e558472c4eb9aaaefa459d"
        k0_event = make_event("og_k0_1", 0, pubkey=pk, created_at=1700000000, content=json.dumps({
            "name": "OG Alice",
            "about": "Thread OG test creator",
            "picture": "https://cdn.iyou.me/og_avatar.png",
        }))
        hero_event = make_event("og_hero_1", 1, pubkey=pk, created_at=1700000100, content="OG thread hero note")
        relay_data = {"og_k0_1": k0_event, "og_hero_1": hero_event}

        # Thread mode: og:title + og:image with author avatar fallback
        with patch("apps.core.views.relay_req", return_value=relay_data):
            response = self.client.get(reverse("feed") + "?thread=og_hero_1")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '<meta property="og:title" content="OG Alice on iyou_wun"')
        self.assertContains(response, '<meta property="og:image" content="https://cdn.iyou.me/og_avatar.png"')

        # Profile mode: profile metadata populates the og tags
        npub = hex_to_npub(pk)
        with patch("apps.core.views.relay_req", return_value=relay_data):
            response = self.client.get(reverse("profile", kwargs={"npub": npub}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '<meta property="og:title" content="OG Alice on iyou_wun"')
        self.assertContains(response, '<meta property="og:image" content="https://cdn.iyou.me/og_avatar.png"')

    def test_nip56_report_action_markup_present_in_kebab_menu(self):
        with patch("apps.core.views.relay_req", return_value={
            "e1": make_event("e1", 1, content="reportable fixture note"),
        }):
            response = self.client.get(reverse("feed"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Report / Flag Note")
        self.assertContains(response, "openReportModal('e1'")




    def test_feed_mode_thread_direct_replies_and_drilldown_link(self):
        root_pk = "3bf0c63fcb93463407af97a5e5ee64fa883d107ef9e558472c4eb9aaaefa459d"
        child_pk = "32e1827635450ebb3c5a7d12c1f8e7b2b514439ac10a67eef3d9fd9c5c68e245"
        grandchild_pk = "0000000000000000000000000000000000000000000000000000000000000001"

        relay_events = {
            "root_hero": make_event("root_hero", 1, pubkey=root_pk, content="Top conversation note"),
            "direct_child": make_event("direct_child", 1111, pubkey=child_pk, content="Direct reply note", tags=[
                ["e", "root_hero", "", "root"],
                ["e", "root_hero", "", "reply"],
                ["p", root_pk, "", "reply"],
            ]),
            "sub_child": make_event("sub_child", 1111, pubkey=grandchild_pk, content="Sub reply under direct child", tags=[
                ["e", "root_hero", "", "root"],
                ["e", "direct_child", "", "reply"],
                ["p", child_pk, "", "reply"],
            ]),
        }
        with patch("apps.core.views.relay_req", return_value=relay_events):
            response = self.client.get(reverse("feed") + "?thread=root_hero")

        self.assertEqual(response.status_code, 200)
        thread_root = response.context.get("thread_root", {})
        # Only 1 direct reply under root_hero
        self.assertEqual(len(thread_root.get("replies", [])), 1)
        direct_reply = thread_root["replies"][0]
        self.assertEqual(direct_reply["id"], "direct_child")
        # Sub-reply count on direct_child is 1
        self.assertEqual(direct_reply["reply_count"], 1)

        # Drilldown link is rendered in HTML
        self.assertContains(response, 'href="/feed?thread=direct_child"')
        self.assertContains(response, "View 1 more reply →")

    def test_thread_subheader_renders_separate_author_and_parent_links(self):
        root_pk = "3bf0c63fcb93463407af97a5e5ee64fa883d107ef9e558472c4eb9aaaefa459d"
        reply_pk = "32e1827635450ebb3c5a7d12c1f8e7b2b514439ac10a67eef3d9fd9c5c68e245"
        root_npub = hex_to_npub(root_pk)

        k0_event = make_event("k0_root", 0, pubkey=root_pk, content=json.dumps({
            "name": "Alice Root",
            "display_name": "Alice In Chains",
        }))
        reply_event = make_event(
            "child_reply_1",
            1,
            pubkey=reply_pk,
            content="Replying to Alice",
            tags=[
                ["e", "parent_note_123", "", "reply"],
                ["p", root_pk, "", "reply"],
            ],
        )

        relay_events = {
            "child_reply_1": reply_event,
            "k0_root": k0_event,
        }

        with patch("apps.core.views.relay_req", return_value=relay_events):
            response = self.client.get(reverse("feed"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "↳ Replying to")
        # Separate author profile link
        self.assertContains(response, f'href="/profile/{root_npub}"')
        self.assertContains(response, "@Alice In Chains")
        # Separate parent note link
        self.assertContains(response, 'href="/feed?thread=parent_note_123"')
        self.assertContains(response, "[parent ↗]")
        # Parent and root links are NOT duplicated (single deduplicated subheader)
        self.assertEqual(response.content.decode().count("↳ Replying to"), 1)

    def test_thread_post_renders_single_deduplicated_reply_subheader(self):
        root_pk = "3bf0c63fcb93463407af97a5e5ee64fa883d107ef9e558472c4eb9aaaefa459d"
        reply_pk = "32e1827635450ebb3c5a7d12c1f8e7b2b514439ac10a67eef3d9fd9c5c68e245"
        root_npub = hex_to_npub(root_pk)

        k0_event = make_event("k0_dedup_root", 0, pubkey=root_pk, content=json.dumps({
            "name": "Alice Root",
            "display_name": "Alice In Chains",
        }))
        reply_event = make_event(
            "dedup_child_1",
            1,
            pubkey=reply_pk,
            content="A deduplicated reply",
            tags=[
                ["e", "dedup_parent_999", "", "reply"],
                ["p", root_pk, "", "reply"],
            ],
        )

        with patch("apps.core.views.relay_req", return_value={"dedup_child_1": reply_event, "k0_dedup_root": k0_event}):
            response = self.client.get(reverse("feed"))

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        # Exactly one "↳ Replying to" attribution block is rendered per reply note
        self.assertEqual(content.count("↳ Replying to"), 1)
        # A single parent note link ([parent ↗]) is rendered, not duplicated as a sub-subheader
        self.assertEqual(content.count("[parent ↗]"), 1)
        self.assertContains(response, "dedup_parent_999")
        self.assertContains(response, f'href="/profile/{root_npub}"')
        self.assertContains(response, "@Alice In Chains")

    def test_thread_header_renders_jump_to_root_link_when_reply(self):
        root_pk = "3bf0c63fcb93463407af97a5e5ee64fa883d107ef9e558472c4eb9aaaefa459d"
        reply_pk = "32e1827635450ebb3c5a7d12c1f8e7b2b514439ac10a67eef3d9fd9c5c68e245"

        root_event = make_event("grandparent_root_1", 1, pubkey=root_pk, content="Original root note")
        child_hero = make_event(
            "hero_reply_99",
            1,
            pubkey=reply_pk,
            content="Hero reply note deep in thread",
            tags=[
                ["e", "grandparent_root_1", "", "root"],
                ["e", "parent_intermediate_2", "", "reply"],
                ["p", root_pk, "", "reply"],
            ],
        )

        relay_events = {
            "grandparent_root_1": root_event,
            "hero_reply_99": child_hero,
        }

        with patch("apps.core.views.relay_req", return_value=relay_events):
            response = self.client.get(reverse("feed") + "?thread=hero_reply_99")

        self.assertEqual(response.status_code, 200)
        # Root jump link rendered
        self.assertContains(response, 'href="/feed?thread=grandparent_root_1"')
        self.assertContains(response, "🧵 Jump to Root Post →")
        # When ancestor parent_intermediate_2 is missing from pool, unresolved placeholder is rendered
        self.assertContains(response, "↳ In reply to parent event")
        self.assertContains(response, "parent_inter")
        self.assertContains(response, "Attempt Fetch ↻")

    def test_contact_manager_script_contains_wss_home_iyou_me_target(self):
        import os
        from django.conf import settings

        cm_path = os.path.join(settings.BASE_DIR, "static", "js", "contact_manager.js")
        with open(cm_path, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn("getBridgeWsUrl", content)
        self.assertIn("wss://home.iyou.me:9001/", content)
        self.assertIn("ws://127.0.0.1:9001/", content)

    def test_feed_view_context_includes_oldest_timestamp(self):
        event1 = make_event("event_ts_1", 1, created_at=1700001000, content="Note 1")
        event2 = make_event("event_ts_2", 1, created_at=1700000500, content="Note 2")
        with patch("apps.core.views.relay_req", return_value={"event_ts_1": event1, "event_ts_2": event2}):
            response = self.client.get(reverse("feed"))

        self.assertEqual(response.status_code, 200)
        self.assertIn("oldest_timestamp", response.context)
        self.assertEqual(response.context["oldest_timestamp"], 1700000500)
        self.assertEqual(response.context["notes"][0]["created_at_epoch"], 1700001000)

    def test_feed_renders_pagination_sentinel_in_main_mode_and_hides_in_thread_mode(self):
        event1 = make_event("sentinel_event_1", 1, created_at=1700000000, content="Sentinel Note")
        with patch("apps.core.views.relay_req", return_value={"sentinel_event_1": event1}):
            # 1. Main Feed Mode
            resp_main = self.client.get(reverse("feed"))
            self.assertEqual(resp_main.status_code, 200)
            self.assertContains(resp_main, 'id="feed-pagination-sentinel"')
            self.assertContains(resp_main, 'id="load-more-btn"')
            self.assertContains(resp_main, 'data-oldest-timestamp="1700000000"')
            self.assertContains(resp_main, "Load More Notes")

            # 2. Thread Mode
            resp_thread = self.client.get(reverse("feed") + "?thread=sentinel_event_1")
            self.assertEqual(resp_thread.status_code, 200)
            self.assertNotContains(resp_thread, 'id="feed-pagination-sentinel"')
            self.assertNotContains(resp_thread, 'id="load-more-btn"')

    def test_api_feed_cursor_pagination_and_structure(self):
        pk = "3bf0c63fcb93463407af97a5e5ee64fa883d107ef9e558472c4eb9aaaefa459d"
        event1 = make_event("api_ev_1", 1, pubkey=pk, created_at=1699999000, content="Older note from API")
        event2 = make_event("api_ev_2", 1063, pubkey=pk, created_at=1699998000, content="Media Note", tags=[
            ["url", "https://cdn.iyou.me/image.jpg"],
            ["m", "image/jpeg"],
        ])

        with patch("apps.core.views.relay_req", return_value={"api_ev_1": event1, "api_ev_2": event2}):
            response = self.client.get(reverse("api_feed") + "?until=1700000000&limit=10")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data.get("success"))
        self.assertEqual(data.get("oldest_timestamp"), 1699998000)
        self.assertTrue(data.get("has_more"))
        self.assertEqual(len(data.get("notes", [])), 2)

        note = data["notes"][0]
        self.assertEqual(note["id"], "api_ev_1")
        self.assertEqual(note["pubkey_hex"], pk)
        self.assertEqual(note["created_at_epoch"], 1699999000)
        self.assertIn("author_name", note)
        self.assertIn("author_avatar", note)
        self.assertIn("media_attachments", note)

        # Second note (Kind 1063) has image attachment
        note2 = data["notes"][1]
        self.assertEqual(note2["id"], "api_ev_2")
        self.assertEqual(len(note2["media_attachments"]), 1)
        self.assertEqual(note2["media_attachments"][0]["type"], "image")
        self.assertEqual(note2["media_attachments"][0]["url"], "https://cdn.iyou.me/image.jpg")

    def test_api_feed_serializes_like_count(self):
        pk = "3bf0c63fcb93463407af97a5e5ee64fa883d107ef9e558472c4eb9aaaefa459d"
        event1 = make_event("api_like_1", 1, pubkey=pk, created_at=1699999000, content="Liked note")
        event2 = make_event("api_like_2", 1, pubkey=pk, created_at=1699998000, content="Another note")

        def _fake_attach_reaction_counts(notes, relay_urls=None):
            counts = {"api_like_1": 12, "api_like_2": 0}
            for n in notes:
                nid = n.get("id")
                if nid in counts:
                    n["like_count"] = counts[nid]
            return notes

        with patch("apps.core.views.relay_req", return_value={"api_like_1": event1, "api_like_2": event2}), \
             patch("apps.core.views.attach_social_counts", side_effect=_fake_attach_reaction_counts):
            response = self.client.get(reverse("api_feed") + "?until=1700000000&limit=10")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        notes = {n["id"]: n for n in data.get("notes", [])}
        self.assertEqual(notes["api_like_1"]["like_count"], 12)
        self.assertEqual(notes["api_like_2"]["like_count"], 0)

    def test_feed_renders_inline_media_attachments_and_unfurls_urls(self):
        pk = "3bf0c63fcb93463407af97a5e5ee64fa883d107ef9e558472c4eb9aaaefa459d"
        k1_media_event = make_event("k1_media_1", 1, pubkey=pk, created_at=1700000000, content="Check this out:\nhttps://cdn.iyou.me/photo.png")
        k1063_event = make_event("k1063_1", 1063, pubkey=pk, created_at=1700000100, tags=[
            ["url", "https://cdn.iyou.me/video.mp4"],
            ["m", "video/mp4"],
        ])

        with patch("apps.core.views.relay_req", return_value={"k1_media_1": k1_media_event, "k1063_1": k1063_event}):
            response = self.client.get(reverse("feed"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '<img src="https://cdn.iyou.me/photo.png"')
        self.assertContains(response, '<video src="https://cdn.iyou.me/video.mp4"')
        self.assertContains(response, "Check this out:")

    def test_feed_renders_multi_image_grid_with_more_badge(self):
        pk = "3bf0c63fcb93463407af97a5e5ee64fa883d107ef9e558472c4eb9aaaefa459d"
        grid_urls = "\n".join(f"https://cdn.iyou.me/grid{_i}.png" for _i in range(5))
        event = make_event("multi_img_1", 1, pubkey=pk, content=f"Gallery note:\n{grid_urls}")

        with patch("apps.core.views.relay_req", return_value={"multi_img_1": event}):
            response = self.client.get(reverse("feed"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "grid grid-cols-2")
        # 2x2 deck with a +N badge on the 4th image
        self.assertContains(response, ">+1</span>")

    def test_thread_post_renders_note_content_clamp_wrapper(self):
        pk = "3bf0c63fcb93463407af97a5e5ee64fa883d107ef9e558472c4eb9aaaefa459d"
        event = make_event("clamp_note_1", 1, pubkey=pk, content="A long note that should be clamped")

        with patch("apps.core.views.relay_req", return_value={"clamp_note_1": event}):
            response = self.client.get(reverse("feed"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'class="note-content-wrapper relative"')
        self.assertContains(response, 'class="expand-note-btn hidden')
        self.assertContains(response, "Show more")

    def test_thread_post_renders_repost_dropdown_and_quote_card(self):
        root_pk = "3bf0c63fcb93463407af97a5e5ee64fa883d107ef9e558472c4eb9aaaefa459d"
        quoted_pk = "32e1827635450ebb3c5a7d12c1f8e7b2b514439ac10a67eef3d9fd9c5c68e245"
        quoted_id = "quoted_event_id_1234567890abcdef1234567890abcdef"
        root_note = make_event(
            "quote_root_1", 1, pubkey=root_pk,
            content="My hot take on the quoted post",
            tags=[["q", quoted_id, "wss://relay.iyou.me", quoted_pk]],
        )
        quoted_event = make_event(
            quoted_id, 1, pubkey=quoted_pk,
            content="The original note that was quoted",
            tags=[],
        )

        relay_data = {
            "quote_root_1": root_note,
            quoted_id: quoted_event,
        }
        with patch("apps.core.views.relay_req", return_value=relay_data):
            response = self.client.get(reverse("feed"))

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        # Repost / Quote toggle dropdown renders
        self.assertIn("repost-menu-container", content)
        self.assertIn('id="repost-menu-quote_root_1"', content)
        self.assertIn("Quote Note", content)
        self.assertIn("openQuoteComposer", content)
        # Embedded quote card partial renders with quoted content + navigation
        self.assertIn("quoted-note-embed", content)
        self.assertIn("The original note that was quoted", content)
        self.assertIn("?thread=quoted_event_id_1234567890abcdef1234567890abcdef", content)

    def test_trending_topics_renders_scope_switcher(self):
        with patch("apps.core.views.relay_req", return_value={}):
            response = self.client.get(reverse("feed"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "[ ⚡ iyou ]")
        self.assertContains(response, "[ 🌐 Global ]")
        self.assertContains(response, 'id="trending-tab-iyou"')
        self.assertContains(response, 'id="trending-tab-global"')
        self.assertContains(response, 'id="trending-iyou-list"')
        self.assertContains(response, 'id="trending-global-list"')

    def test_trending_topics_global_and_iyou_lists_bound_correctly(self):
        from django.contrib.auth import get_user_model
        from apps.core.models import UserLinkDeck
        from apps.core.views import did_to_pubkey

        User = get_user_model()
        alice_did = "did:key:z6Mkalice_bound1"
        user_alice, _ = User.objects.get_or_create(username=alice_did)
        UserLinkDeck.objects.get_or_create(user=user_alice, handle="alice", display_name="Alice")

        alice_pk = did_to_pubkey(alice_did)
        self.assertIsNotNone(alice_pk)
        bob_pk = "32e1827635450ebb3c5a7d12c1f8e7b2b514439ac10a67eef3d9fd9c5c68e245"

        relay_events = {
            "bound_iyou_note": make_event(
                "bound_iyou_note", 1, pubkey=alice_pk,
                content="alice #alice_iyou tag", tags=[["t", "alice_iyou"]],
            ),
            "bound_global_note": make_event(
                "bound_global_note", 1, pubkey=bob_pk,
                content="bob #bob_global tag", tags=[["t", "bob_global"]],
            ),
        }
        with patch("apps.core.views.relay_req", return_value=relay_events):
            response = self.client.get(reverse("feed"))

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        iyou_marker = content.index('id="trending-iyou-list"')
        global_marker = content.index('id="trending-global-list"')
        if iyou_marker < global_marker:
            iyou_block = content[iyou_marker:global_marker]
            global_block = content[global_marker:]
        else:
            global_block = content[global_marker:iyou_marker]
            iyou_block = content[iyou_marker:]

        # The iyou list renders iyou-scoped tags (from LinkDeck authors) only
        self.assertIn("#alice_iyou", iyou_block)
        self.assertNotIn("#bob_global", iyou_block)
        # The global list renders the full incoming batch tags (both authors)
        self.assertIn("#alice_iyou", global_block)
        self.assertIn("#bob_global", global_block)

    def test_feed_right_rail_renders_empty_state_when_zero_tags(self):
        with patch("apps.core.views.relay_req", return_value={}):
            response = self.client.get(reverse("feed"))

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('id="trending-global-list"', content)
        self.assertIn('id="trending-iyou-list"', content)
        # Event batch has no #t tags, so the real-time lists fall to empty notices.
        self.assertIn("No active trending tags in mesh.", content)
        self.assertIn("No trending tags in iyou circle yet.", content)
        # No hardcoded mock tag cards or click handlers render without real tags.
        self.assertNotIn("filterByTag(", content)
        self.assertNotIn("#nostr", content)
        self.assertNotIn("#sovereign", content)

    def test_feed_right_rail_renders_trending_tags_with_click_handlers(self):
        from django.contrib.auth import get_user_model
        from apps.core.models import UserLinkDeck
        from apps.core.views import did_to_pubkey

        User = get_user_model()
        alice_did = "did:key:z6Mkalice_trendclick1"
        user_alice, _ = User.objects.get_or_create(username=alice_did)
        UserLinkDeck.objects.get_or_create(user=user_alice, handle="alice", display_name="Alice")
        alice_pk = did_to_pubkey(alice_did)
        self.assertIsNotNone(alice_pk)
        bob_pk = "32e1827635450ebb3c5a7d12c1f8e7b2b514439ac10a67eef3d9fd9c5c68e245"

        relay_events = {
            "trend_i_note": make_event(
                "trend_i_note", 1, pubkey=alice_pk,
                content="native mesh", tags=[["t", "sovereign"]],
            ),
            "trend_g_note": make_event(
                "trend_g_note", 1, pubkey=bob_pk,
                content="mesh world", tags=[["t", "bitcoin"]],
            ),
        }
        with patch("apps.core.views.relay_req", return_value=relay_events):
            response = self.client.get(reverse("feed"))

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        # Tag cards route through the interactive filterByTag click handler with
        # the real tag slug, and render the #-prefixed name + exact frequency.
        self.assertIn("filterByTag('sovereign')", content)
        self.assertIn("filterByTag('bitcoin')", content)
        self.assertIn(">#sovereign<", content)
        self.assertIn(">#bitcoin<", content)
        self.assertIn("1 note", content)

    def test_layer2_nav_renders_nsfw_shield_toggle(self):
        with patch("apps.core.views.relay_req", return_value={}):
            response = self.client.get(reverse("feed"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="nsfw-filter-toggle"')
        self.assertContains(response, 'id="nsfw-filter-status"')
        self.assertContains(response, "toggleNsfwFilter()")
        self.assertContains(response, "Shield:")

    def test_nav_renders_iyou_circle_pill(self):
        with patch("apps.core.views.get_iyou_pubkeys", return_value=["3bf0c63fcb93463407af97a5e5ee64fa883d107ef9e558472c4eb9aaaefa459d"]) as mock_get_iyou:
            with patch("apps.core.views.relay_req", return_value={}):
                response = self.client.get(reverse("feed"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-circle="iyou"')
        self.assertContains(response, "⚡ iyou")
        self.assertEqual(response.context["selected_circle"], "iyou")
        self.assertTrue(mock_get_iyou.called)

    def test_iyou_circle_scopes_feed_to_linkdeck_authors(self):
        from django.contrib.auth import get_user_model
        User = get_user_model()
        user_deck, _ = User.objects.get_or_create(username="did:key:z6Mkiyou_author_1")
        UserLinkDeck.objects.get_or_create(
            user=user_deck,
            handle="iyoucreator",
            display_name="IYOU Creator",
            is_public=True,
        )

        captured_filter = {}

        def mock_relay_req(filter_obj, relay_urls=None, timeout=10, deadline=None):
            captured_filter.update(filter_obj)
            return {
                "note_iyou": make_event("note_iyou", 1, pubkey="3bf0c63fcb93463407af97a5e5ee64fa883d107ef9e558472c4eb9aaaefa459d", content="Local ecosystem note"),
            }

        # 1. Test FeedView context GET without parameters defaults to iyou
        with patch("apps.core.views.relay_req", side_effect=mock_relay_req):
            response = self.client.get(reverse("feed"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["selected_circle"], "iyou")
        self.assertIn("authors", captured_filter)
        self.assertTrue(len(captured_filter["authors"]) > 0)

        # 2. Test FeedView context GET ?circle=iyou
        captured_filter.clear()
        with patch("apps.core.views.relay_req", side_effect=mock_relay_req):
            response = self.client.get(reverse("feed") + "?circle=iyou")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["selected_circle"], "iyou")
        self.assertIn("authors", captured_filter)
        self.assertTrue(len(captured_filter["authors"]) > 0)

        # 3. Test api_feed JSON GET without parameters defaults to iyou
        captured_filter.clear()
        with patch("apps.core.views.relay_req", side_effect=mock_relay_req):
            response_api = self.client.get(reverse("api_feed"))
        self.assertEqual(response_api.status_code, 200)
        self.assertIn("authors", captured_filter)
        self.assertTrue(len(captured_filter["authors"]) > 0)

        # 4. Test api_feed JSON GET ?circle=iyou
        captured_filter.clear()
        with patch("apps.core.views.relay_req", side_effect=mock_relay_req):
            response_api = self.client.get(reverse("api_feed") + "?circle=iyou")
        self.assertEqual(response_api.status_code, 200)
        self.assertIn("authors", captured_filter)
        self.assertTrue(len(captured_filter["authors"]) > 0)

    def test_thread_post_renders_data_lang_attribute(self):
        pk = "3bf0c63fcb93463407af97a5e5ee64fa883d107ef9e558472c4eb9aaaefa459d"
        event_es = make_event("es_note", 1, pubkey=pk, content="¡Hola mundo nostr! ¿Cómo estás?", tags=[["lang", "es"]])
        with patch("apps.core.views.relay_req", return_value={"es_note": event_es}):
            response = self.client.get(reverse("feed"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-lang="es"')

    def test_avatar_fallback_uses_iyou_symbol_only_for_native_peers(self):
        from apps.core.views import did_to_pubkey
        iyou_did = "did:key:z6Mkiyoubrandpeer"
        iyou_user, _ = User.objects.get_or_create(username=iyou_did)
        UserLinkDeck.objects.get_or_create(
            user=iyou_user,
            handle="iyoubrandom",
            display_name="Iyou Brand Peer",
            is_public=True,
        )
        native_pk = did_to_pubkey(iyou_did)
        native_event = make_event(
            "native_avatar_1", 1, pubkey=native_pk, content="A native sovereign peer without an avatar"
        )
        with patch("apps.core.views.relay_req", return_value={"native_avatar_1": native_event}):
            response = self.client.get(reverse("feed"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "/static/img/iyou_symbol.png")
        self.assertNotContains(response, "/static/img/mesh_avatar_default.svg")

    def test_avatar_fallback_uses_mesh_default_for_external_peers(self):
        external_event = make_event(
            "external_avatar_1", 1, content="An unverified external mesh relay peer"
        )
        with patch("apps.core.views.relay_req", return_value={"external_avatar_1": external_event}):
            response = self.client.get(reverse("feed"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "/static/img/mesh_avatar_default.svg")

    def test_feed_renders_skeleton_placeholder_markup(self):
        with patch("apps.core.views.relay_req", return_value={}):
            response = self.client.get(reverse("feed") + "?async=1")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="feed-skeleton-container"')
        self.assertContains(response, "animate-pulse")
        self.assertContains(response, 'data-hydrate="true"')
        self.assertContains(response, 'id="feed-container"')

    def test_feed_async_shell_skips_blocking_relay_io(self):
        with patch("apps.core.views.relay_req", return_value={}) as mock_relay:
            response = self.client.get(reverse("feed") + "?async=1")
        self.assertEqual(response.status_code, 200)
        mock_relay.assert_not_called()

    def test_feed_serializes_avatar_resolution_with_client_side_pool(self):
        src = (settings.BASE_DIR / "static" / "js" / "feed_interactions.js").read_text()
        self.assertIn("function resolveAvatarUrl(note)", src)
        self.assertIn("/static/img/iyou_symbol.png", src)
        self.assertIn("/static/img/mesh_avatar_default.svg", src)
        self.assertIn("note.is_iyou_native || note.is_sovereign", src)
        self.assertIn("function fetchInitialFeedStream", src)
        self.assertIn('container.getAttribute("data-hydrate") !== "true"', src)
        self.assertIn("/api/feed?limit=25", src)

    def test_thread_post_renders_translate_button_for_non_english(self):
        pk = "3bf0c63fcb93463407af97a5e5ee64fa883d107ef9e558472c4eb9aaaefa459d"
        event_es = make_event("es_note_trans", 1, pubkey=pk, content="¡Hola mundo nostr! ¿Cómo estás?", tags=[["lang", "es"]])
        event_en = make_event("en_note_trans", 1, pubkey=pk, content="Standard english text note", tags=[["lang", "en"]])
        with patch("apps.core.views.relay_req", return_value={"es_note_trans": event_es, "en_note_trans": event_en}):
            response = self.client.get(reverse("feed"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'class="translate-btn')
        self.assertContains(response, 'data-note-id="es_note_trans"')
        self.assertContains(response, 'id="translated-box-es_note_trans"')
        self.assertContains(response, "translateNote(this, 'es_note_trans', 'es')")

    def test_api_translate_endpoint_returns_translated_payload(self):
        from django.core.cache import cache
        cache.clear()

        # 1. Reject non-POST
        resp_get = self.client.get(reverse("api_translate"))
        self.assertEqual(resp_get.status_code, 405)

        # 2. Reject empty text
        resp_empty = self.client.post(
            reverse("api_translate"),
            data=json.dumps({"text": "", "source_lang": "es", "target_lang": "en"}),
            content_type="application/json",
        )
        self.assertEqual(resp_empty.status_code, 400)

        # 3. Valid translation payload
        payload = {
            "text": "¡Hola mundo nostr! ¿Cómo estás?",
            "source_lang": "es",
            "target_lang": "en",
        }
        resp_post = self.client.post(
            reverse("api_translate"),
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(resp_post.status_code, 200)
        data = resp_post.json()
        self.assertTrue(data["success"])
        self.assertIn("Hello nostr world", data["translated_text"])
        self.assertEqual(data["source_lang"], "es")
        self.assertEqual(data["target_lang"], "en")
        self.assertFalse(data["cached"])

        # 4. Verify Caching on second request
        resp_cached = self.client.post(
            reverse("api_translate"),
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(resp_cached.status_code, 200)
        data_cached = resp_cached.json()
        self.assertTrue(data_cached["cached"])
        self.assertEqual(data_cached["translated_text"], data["translated_text"])

    def test_api_feed_deduplicates_and_returns_valid_notes(self):
        pk = "3bf0c63fcb93463407af97a5e5ee64fa883d107ef9e558472c4eb9aaaefa459d"
        event1 = make_event("api_dup_1", 1, pubkey=pk, created_at=1699999000, content="Original note text")
        event1_dup = make_event("api_dup_1", 1, pubkey=pk, created_at=1699999000, content="Duplicate copy")
        event2 = make_event("api_note_2", 1063, pubkey=pk, created_at=1699998000, tags=[
            ["url", "https://cdn.iyou.me/pic.png"],
            ["m", "image/png"],
        ])

        with patch("apps.core.views.relay_req", return_value={"e1": event1, "e1_dup": event1_dup, "e2": event2}):
            response = self.client.get(reverse("api_feed") + "?until=1700000000&limit=10")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        notes = data["notes"]
        self.assertEqual(len(notes), 2)
        note_ids = [n["id"] for n in notes]
        self.assertEqual(len(note_ids), len(set(note_ids)))
        self.assertIn("api_dup_1", note_ids)
        self.assertIn("api_note_2", note_ids)

        first = notes[0]
        self.assertIn("created_at_epoch", first)
        self.assertIn("created_at_formatted", first)
        self.assertIn("pubkey_hex", first)
        self.assertIn("media_attachments", first)
        self.assertIn("reply_to_name", first)
        self.assertIn("reply_count", first)

    def test_feed_view_renders_numeric_reply_count_when_replies_exist(self):
        pk = "3bf0c63fcb93463407af97a5e5ee64fa883d107ef9e558472c4eb9aaaefa459d"
        root_event = make_event("root_rep_card", 1, pubkey=pk, content="Testing reply counts display")
        reply_event = make_event("reply_rep_card", 1, pubkey=pk, content="First reply", tags=[["e", "root_rep_card"]])

        with patch("apps.core.views.relay_req") as mock_relay:
            mock_relay.side_effect = [
                {"root": root_event},
                {},
                {"rep": reply_event},
                {},  # attach_reaction_counts => no reactions
            ]
            response = self.client.get(reverse("feed"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "action-btn-reply")
        self.assertContains(response, "1")

    def test_feed_renders_discovery_rail_placeholders_in_main_mode(self):
        with patch("apps.core.views.relay_req", return_value={}):
            response = self.client.get(reverse("feed"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "TRENDING TOPICS")
        # No real batch tags -> real-time aggregator renders empty notices, not mocks.
        self.assertContains(response, "No active trending tags in mesh.")
        self.assertContains(response, "No trending tags in iyou circle yet.")
        self.assertContains(response, "SOVEREIGN CREATORS")
        self.assertContains(response, "Ben Justman")
        self.assertContains(response, "Dan Byers")
        self.assertContains(response, "+ Follow")

    def test_feed_hides_discovery_rail_in_thread_mode(self):
        root_pk = "3bf0c63fcb93463407af97a5e5ee64fa883d107ef9e558472c4eb9aaaefa459d"
        relay_events = {
            "hero_root_1": make_event("hero_root_1", 1, pubkey=root_pk, content="Hero thread discussion"),
        }
        with patch("apps.core.views.relay_req", return_value=relay_events):
            response = self.client.get(reverse("feed") + "?thread=hero_root_1")
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "TRENDING TOPICS")
        self.assertNotContains(response, "SOVEREIGN CREATORS")

    def test_feed_context_provides_suggested_creators_and_tags(self):
        u1 = User.objects.create_user(username="did:key:z6Mkcreatorcontext1")
        UserLinkDeck.objects.create(
            user=u1,
            handle="creatorone",
            display_name="Creator One",
            is_public=True,
            is_verified=True,
        )
        with patch("apps.core.views.relay_req", return_value={}):
            response = self.client.get(reverse("feed"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("suggested_creators", response.context)
        self.assertIn("trending_tags", response.context)
        self.assertIn("trending_tags_global", response.context)
        self.assertIn("trending_tags_iyou", response.context)
        # No event batch means no mock tags: both real-time lists are empty.
        self.assertEqual(response.context["trending_tags_global"], [])
        self.assertEqual(response.context["trending_tags_iyou"], [])
        creators = response.context["suggested_creators"]
        self.assertTrue(any(c.handle == "creatorone" for c in creators))

    def test_right_rail_renders_dynamic_creator_cards(self):
        u = User.objects.create_user(username="did:key:z6Mkcreatorcard1")
        UserLinkDeck.objects.create(
            user=u,
            handle="testcreator",
            display_name="Test Creator",
            is_public=True,
            is_verified=True,
        )
        with patch("apps.core.views.relay_req", return_value={}):
            response = self.client.get(reverse("feed"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "@testcreator")
        self.assertContains(response, "Test Creator")
        self.assertContains(response, 'data-follow-target="did:key:z6Mkcreatorcard1"')
        self.assertContains(response, 'data-follow-petname="testcreator"')

    def test_feed_renders_relay_health_widget_in_right_rail_main_mode(self):
        with patch("apps.core.views.relay_req", return_value={}):
            response = self.client.get(reverse("feed"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="relay-health-widget"')
        self.assertContains(response, 'id="relay-health-toggle"')
        self.assertContains(response, 'id="relay-status-dot"')
        self.assertContains(response, 'id="relay-status-label"')
        self.assertContains(response, 'id="relay-health-count"')
        self.assertContains(response, 'id="relay-diagnostics-drawer"')
        self.assertContains(response, 'id="relay-diagnostics-list"')
        self.assertContains(response, "Active Relays")
        self.assertContains(response, "Configure ↗")
        self.assertContains(response, "/dashboard#settings")
        self.assertContains(response, "window.relayPool?.toggleDiagnosticsPopover()")

    def test_feed_relay_health_indicator_removed_from_composer_area(self):
        with patch("apps.core.views.relay_req", return_value={}):
            response = self.client.get(reverse("feed"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="relay-health-widget"')
        self.assertNotContains(response, 'id="relay-health-indicator"')
        self.assertNotContains(response, 'id="relay-health-dot"')
        self.assertNotContains(response, 'id="relay-health-text"')

    def test_feed_hides_relay_health_widget_in_thread_mode(self):
        root_pk = "3bf0c63fcb93463407af97a5e5ee64fa883d107ef9e558472c4eb9aaaefa459d"
        relay_events = {
            "hero_root_2": make_event("hero_root_2", 1, pubkey=root_pk, content="Thread health widget"),
        }
        with patch("apps.core.views.relay_req", return_value=relay_events):
            response = self.client.get(reverse("feed") + "?thread=hero_root_2")
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'id="relay-health-widget"')



class CyberGritErrorViewTests(TestCase):
    """Verifies branded cyber-grit 404/500 error views render with themed copy."""

    def test_custom_404_template_renders(self):
        from django.test.utils import override_settings

        with override_settings(DEBUG=False):
            response = self.client.get("/nonexistent-route-xyz/")

        self.assertEqual(response.status_code, 404)
        self.assertContains(response, "Mesh Node Not Found", status_code=404)
        self.assertContains(response, "STATUS 404 // ROUTE_DISCONNECTED", status_code=404)
        self.assertContains(response, "GOSSIP_ACTIVE", status_code=404)
        self.assertContains(response, 'rel="stylesheet" href="/static/css/output.css"', status_code=404)

    def test_custom_500_template_renders(self):
        from django.test import RequestFactory
        from django.views.defaults import server_error

        request = RequestFactory().get("/boom")
        response = server_error(request)

        self.assertEqual(response.status_code, 500)
        self.assertContains(response, "Relay Pipeline Exception", status_code=500)
        self.assertContains(response, "STATUS 500 // INTERNAL_TRANSMISSION_FAULT", status_code=500)
        self.assertContains(response, "SECURE_LOG_RECORDED", status_code=500)
        self.assertContains(response, "Retry Socket", status_code=500)


class SearchAPITests(TestCase):
    def setUp(self):
        self.user_alice = User.objects.create_user(username="did:key:z6Mkalice123")
        self.deck_alice = UserLinkDeck.objects.create(
            user=self.user_alice,
            handle="alice",
            display_name="Alice Sovereign",
            headline="Cryptography researcher",
            nip05="alice@iyou.me",
            avatar_url="https://example.com/alice.png",
            is_verified=True,
            is_public=True,
        )

        self.user_bob = User.objects.create_user(username="did:key:z6Mkbob456")
        self.deck_bob = UserLinkDeck.objects.create(
            user=self.user_bob,
            handle="bob",
            display_name="Bob Builder",
            headline="Hardware hacker",
            nip05="bob@iyou.me",
            avatar_url="https://example.com/bob.png",
            is_verified=False,
            is_public=True,
        )

    def test_api_search_endpoint_returns_json_schema(self):
        response = self.client.get(reverse("api_search") + "?q=nostr")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["query"], "nostr")
        self.assertIn("counts", data)
        self.assertIn("profiles", data["counts"])
        self.assertIn("tags", data["counts"])
        self.assertIn("results", data)
        self.assertIn("profiles", data["results"])
        self.assertIn("tags", data["results"])

    def test_api_search_filters_profiles_by_handle_and_name(self):
        # Search by handle "alice"
        response = self.client.get(reverse("api_search") + "?q=alice")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        handles = [p["handle"] for p in data["results"]["profiles"]]
        self.assertIn("alice", handles)
        self.assertNotIn("bob", handles)

        # Search by display name substring "Sovereign"
        response_sov = self.client.get(reverse("api_search") + "?q=Sovereign")
        self.assertEqual(response_sov.status_code, 200)
        data_sov = response_sov.json()
        handles_sov = [p["handle"] for p in data_sov["results"]["profiles"]]
        self.assertIn("alice", handles_sov)
        self.assertNotIn("bob", handles_sov)

        # Search by hashtag prefix "#alice"
        response_tag = self.client.get(reverse("api_search") + "?q=%23alice")
        self.assertEqual(response_tag.status_code, 200)
        data_tag = response_tag.json()
        handles_tag = [p["handle"] for p in data_tag["results"]["profiles"]]
        self.assertIn("alice", handles_tag)

    def test_api_search_handles_queries_resiliently_on_sqlite(self):
        response = self.client.get(reverse("api_search") + "?q=alice")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertGreaterEqual(data["counts"]["profiles"], 1)
        profile = data["results"]["profiles"][0]
        self.assertEqual(profile["handle"], "alice")
        self.assertIn("display_name", profile)
        self.assertIn("avatar_url", profile)
        self.assertIn("nip05", profile)

    def test_api_search_empty_query_returns_clean_schema(self):
        response = self.client.get(reverse("api_search") + "?q=")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["counts"]["profiles"], 0)
        self.assertEqual(data["counts"]["tags"], 0)
        self.assertEqual(data["results"]["profiles"], [])
        self.assertEqual(data["results"]["tags"], [])

    def test_api_search_postgresql_branch_uses_search_rank_and_vector(self):
        with patch("django.db.connection.vendor", "postgresql"), \
             patch("django.contrib.postgres.search.SearchVector") as mock_vector, \
             patch("django.contrib.postgres.search.SearchQuery") as mock_query, \
             patch("django.contrib.postgres.search.SearchRank") as mock_rank:
            mock_qs = [self.deck_alice]
            with patch.object(UserLinkDeck.objects, "filter") as mock_filter:
                mock_filter.return_value.annotate.return_value.filter.return_value.order_by.return_value.__getitem__.return_value = mock_qs
                response = self.client.get(reverse("api_search") + "?q=alice")
                self.assertEqual(response.status_code, 200)
                data = response.json()
                self.assertTrue(data["success"])
                self.assertEqual(data["counts"]["profiles"], 1)
                self.assertEqual(data["results"]["profiles"][0]["handle"], "alice")
                mock_vector.assert_called()
                mock_query.assert_called()
                mock_rank.assert_called()

    def test_nav_search_dropdown_elements_render(self):
        with patch("apps.core.views.relay_req", return_value={}):
            response = self.client.get(reverse("feed"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="feed-search-input"')
        self.assertContains(response, 'id="search-results-dropdown"')
        self.assertContains(response, 'id="search-dropdown-content"')
        self.assertContains(response, 'id="search-dropdown-footer"')

    def test_base_template_renders_toast_container(self):
        with patch("apps.core.views.relay_req", return_value={}):
            response = self.client.get(reverse("feed"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="toast-container"')
        self.assertContains(response, "toast_manager.js")


class NIP05EndpointTests(TestCase):
    NIP05_RELAYS = ["wss://relay.iyou.me", "wss://nos.lol", "wss://relay.damus.io"]

    def test_nip05_returns_cors_header_wildcard(self):
        response = self.client.get("/.well-known/nostr.json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Access-Control-Allow-Origin"], "*")

    def test_nip05_resolves_known_handle_to_pubkey(self):
        pubkey_hex = "3bf0c63fcb93463407af97a5e5ee64fa883d107ef9e558472c4eb9aaaefa459d"
        user = User.objects.create_user(username=pubkey_hex)
        UserLinkDeck.objects.create(
            user=user,
            handle="alice",
            display_name="Alice Sovereign",
            is_public=True,
        )

        response = self.client.get("/.well-known/nostr.json?name=alice")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Access-Control-Allow-Origin"], "*")
        data = response.json()
        self.assertEqual(data["names"]["alice"], pubkey_hex)
        self.assertIn(pubkey_hex, data["relays"])
        self.assertEqual(data["relays"][pubkey_hex], self.NIP05_RELAYS)

    def test_nip05_unknown_handle_returns_empty_mapping(self):
        response = self.client.get("/.well-known/nostr.json?name=ghost")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["names"], {})
        self.assertEqual(data["relays"], {})
        self.assertEqual(data["nip46"], {})

    def test_nip05_root_underscore_returns_platform_key(self):
        from apps.core.views import get_public_key_hex, get_node_signing_key

        response = self.client.get("/.well-known/nostr.json?name=_")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Access-Control-Allow-Origin"], "*")
        data = response.json()
        self.assertEqual(data["names"]["_"], get_public_key_hex(get_node_signing_key()))
        self.assertIn(data["names"]["_"], data["relays"])

    def test_nip05_without_name_returns_all_public_handles(self):
        user = User.objects.create_user(
            username="3bf0c63fcb93463407af97a5e5ee64fa883d107ef9e558472c4eb9aaaefa459d"
        )
        UserLinkDeck.objects.create(user=user, handle="audrey", is_public=True)

        response = self.client.get("/.well-known/nostr.json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Access-Control-Allow-Origin"], "*")
        data = response.json()
        self.assertIn("audrey", data["names"])
        self.assertEqual(
            data["names"]["audrey"],
            "3bf0c63fcb93463407af97a5e5ee64fa883d107ef9e558472c4eb9aaaefa459d",
        )


class ApiContactsFollowTests(TestCase):
    ME = "3bf0c63fcb93463407af97a5e5ee64fa883d107ef9e558472c4eb9aaaefa459d"
    TARGET = "b1c6d3f8a2e94c705d2a97c13b6f4e283ad0f19c64e8b527a3d7f6c0e12ab845"
    EXISTING = "c43a9e7d1f2b4805a6e3c9d0f7b1a2456e8c0d3f4a7b9c2e5d1f0a3b6c4d8e1f"

    def setUp(self):
        self.user = User.objects.create_user(username=self.ME)
        self.client.force_login(self.user)

    def _post(self, **payload):
        return self.client.post(
            "/api/contacts/follow/",
            data=json.dumps(payload),
            content_type="application/json",
        )

    def test_api_contacts_follow_prepares_kind_3_payload(self):
        existing = {
            "eid_old": {
                "id": "eid_old",
                "kind": 3,
                "pubkey": self.ME,
                "created_at": 100,
                "tags": [["p", self.EXISTING, "wss://relay.iyou.me", "maria"]],
                "content": "",
            }
        }
        with patch("apps.core.views.relay_req", return_value=existing):
            resp = self._post(
                target_pubkey=self.TARGET,
                action="follow",
                target_name="Alice",
            )

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["action"], "follow")
        event = data["event"]
        # NIP-02 Kind 3 contact list event
        self.assertEqual(event["kind"], 3)
        self.assertEqual(event["pubkey"], self.ME)
        # Preserved the pre-existing contact AND appended the new follow tag
        self.assertIn(["p", self.EXISTING, "wss://relay.iyou.me", "maria"], event["tags"])
        self.assertIn([self.TARGET, "wss://relay.iyou.me", "Alice"],
                      [t[1:] for t in event["tags"] if t[0] == "p"])
        self.assertEqual(data["contacts_count"], 2)

    def test_api_contacts_follow_unfollow_removes_tag(self):
        existing = {
            "eid_old": {
                "id": "eid_old",
                "kind": 3,
                "pubkey": self.ME,
                "created_at": 100,
                "tags": [
                    ["p", self.TARGET, "wss://relay.iyou.me", "alice"],
                    ["p", self.EXISTING, "wss://relay.iyou.me", "maria"],
                ],
                "content": "",
            }
        }
        with patch("apps.core.views.relay_req", return_value=existing):
            resp = self._post(target_pubkey=self.TARGET, action="unfollow")

        self.assertEqual(resp.status_code, 200)
        event = resp.json()["event"]
        tags = [t for t in event["tags"] if t[0] == "p"]
        self.assertEqual([t[1] for t in tags], [self.EXISTING])
        self.assertEqual(resp.json()["contacts_count"], 1)

    def test_api_contacts_follow_rejects_anonymous_and_invalid(self):
        self.client.logout()
        resp = self._post(target_pubkey=self.TARGET, action="follow")
        self.assertEqual(resp.status_code, 302)  # @login_required redirect for browser clients

        self.client.force_login(self.user)
        bad = self._post(target_pubkey="not-a-pubkey", action="follow")
        self.assertEqual(bad.status_code, 400)
        self.assertFalse(bad.json()["success"])


class _FakeNip05Resp:
    """Minimal urllib response-style object supporting read() + context manager."""

    def __init__(self, payload):
        self._body = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self._body


class UniversalProfileResolverTests(TestCase):
    PUBKEY = "3bf0c63fcb93463407af97a5e5ee64fa883d107ef9e558472c4eb9aaaefa459d"

    def _get_profile(self, identifier):
        with (
            patch("apps.core.views.relay_req", return_value={}),
            patch("apps.core.views.fetch_profile_data", return_value={"name": "alice"}),
        ):
            return self.client.get(reverse("profile", args=[identifier]))

    def test_profile_view_resolves_hex_and_npub(self):
        from apps.core.views import hex_to_npub

        npub = hex_to_npub(self.PUBKEY)
        self.assertTrue(npub)

        hex_resp = self._get_profile(self.PUBKEY)
        npub_resp = self._get_profile(npub)

        self.assertEqual(hex_resp.status_code, 200)
        self.assertEqual(hex_resp.context["hex_pubkey"], self.PUBKEY)
        self.assertEqual(npub_resp.status_code, 200)
        self.assertEqual(npub_resp.context["hex_pubkey"], self.PUBKEY)

    def test_profile_view_resolves_nip05_identifier(self):
        payload = {"names": {"alice": self.PUBKEY}, "relays": {self.PUBKEY: []}}
        with (
            patch("urllib.request.urlopen", return_value=_FakeNip05Resp(payload)),
            patch("apps.core.views.relay_req", return_value={}),
            patch("apps.core.views.fetch_profile_data", return_value={"name": "alice"}),
        ):
            resp = self.client.get(reverse("profile", args=["alice@example.com"]))

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context["hex_pubkey"], self.PUBKEY)

    def test_profile_view_unknown_identifier_renders_error_card(self):
        resp = self._get_profile("ghost")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Peer Not Found on Mesh", resp.content.decode())


class ProfileComposerTests(TestCase):
    PUBKEY_OWNER = "3bf0c63fcb93463407af97a5e5ee64fa883d107ef9e558472c4eb9aaaefa459d"
    PUBKEY_PEER = "b1c6d3f8a2e94c705d2a97c13b6f4e283ad0f19c64e8b527a3d7f6c0e12ab845"

    def _get_profile(self, npub):
        with (
            patch("apps.core.views.relay_req", return_value={}),
            patch("apps.core.views.fetch_profile_data", return_value={}),
        ):
            return self.client.get(reverse("profile", args=[npub]))

    def test_profile_renders_composer_when_owner(self):
        owner = User.objects.create_user(username=self.PUBKEY_OWNER)
        UserLinkDeck.objects.create(
            user=owner,
            handle="owner",
            display_name="Owner",
            is_public=True,
        )
        self.client.force_login(owner)

        response = self._get_profile(hex_to_npub(self.PUBKEY_OWNER))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["is_owner"])
        self.assertContains(response, "Post to Nostr")
        self.assertContains(response, 'id="postContent"')
        self.assertContains(response, 'id="btn-publish-note"')

    def test_profile_omits_composer_when_visiting_peer(self):
        peer = User.objects.create_user(username=self.PUBKEY_PEER)
        UserLinkDeck.objects.create(
            user=peer,
            handle="peer",
            display_name="Peer",
            is_public=True,
        )
        viewer = User.objects.create_user(username=self.PUBKEY_OWNER)
        self.client.force_login(viewer)

        response = self._get_profile(hex_to_npub(self.PUBKEY_PEER))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["is_owner"])
        self.assertNotContains(response, 'id="postContent"')
        self.assertNotContains(response, "Post to Nostr")


class NotificationViewTests(TestCase):
    """Layer 1 notification bell, slide-out drawer & /notifications ledger contract tests."""

    PUBKEY_VIEWER = "3bf0c63fcb93463407af97a5e5ee64fa883d107ef9e558472c4eb9aaaefa459d"
    PUBKEY_ACTOR = "b1c6d3f8a2e94c705d2a97c13b6f4e283ad0f19c64e8b527a3d7f6c0e12ab845"

    def _notify_events(self):
        return {
            "ntf_mention": make_event(
                "ntf_mention",
                1,
                pubkey=self.PUBKEY_ACTOR,
                created_at=1700000600,
                content="Replied with a thought",
                tags=[["e", "root_a"], ["p", self.PUBKEY_VIEWER]],
            ),
            "ntf_like": make_event(
                "ntf_like",
                7,
                pubkey=self.PUBKEY_ACTOR,
                created_at=1700000700,
                content="❤️",
                tags=[["e", "root_a"], ["p", self.PUBKEY_VIEWER]],
            ),
            "ntf_repost": make_event(
                "ntf_repost",
                6,
                pubkey=self.PUBKEY_ACTOR,
                created_at=1700000800,
                content="",
                tags=[["e", "root_a"], ["p", self.PUBKEY_VIEWER]],
            ),
            "ntf_zap": make_event(
                "ntf_zap",
                9735,
                pubkey=self.PUBKEY_ACTOR,
                created_at=1700000900,
                content='{"content":"Great post","description":""}',
                tags=[["p", self.PUBKEY_VIEWER], ["amount", "21000"]],
            ),
        }

    def _auth(self):
        viewer = User.objects.create_user(username=self.PUBKEY_VIEWER)
        self.client.force_login(viewer)

    def test_notifications_view_auth_gated(self):
        response = self.client.get(reverse("notifications"))
        self.assertIn(response.status_code, (302, 401))

    def test_notifications_view_renders_template_with_tabs(self):
        self._auth()
        with (
            patch("apps.core.views.relay_req", return_value=self._notify_events()),
            patch(
                "apps.core.views.fetch_profile_data",
                return_value={
                    "name": "Actor",
                    "display_name": "Actor Name",
                    "picture": "https://cdn.iyou.me/avatar.png",
                },
            ),
        ):
            response = self.client.get(reverse("notifications"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "ACTIVITY &amp; NOTIFICATIONS")
        self.assertContains(response, "Mentions / Replies")
        self.assertContains(response, "Reactions")
        self.assertContains(response, "Zaps")
        self.assertContains(response, "id=\"notification-ledger\"")
        self.assertContains(response, "Actor Name")
        self.assertContains(response, "Replied with a thought")
        self.assertContains(response, "❤️")
        self.assertContains(response, "/feed?thread=root_a")
        self.assertContains(response, "💬")
        self.assertContains(response, "🔁")
        self.assertContains(response, "⚡")

    def test_standard_header_renders_notification_bell_when_authenticated(self):
        self._auth()
        with patch("apps.core.views.relay_req", return_value={}):
            response = self.client.get(reverse("feed"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="notification-bell-btn"')
        self.assertContains(response, 'id="notification-unread-dot"')
        self.assertContains(response, "toggleNotificationDrawer()")
        self.assertContains(response, "Activity Notifications")

    def test_standard_header_omits_notification_bell_when_anonymous(self):
        with patch("apps.core.views.relay_req", return_value={}):
            response = self.client.get(reverse("feed"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'id="notification-bell-btn"')


class I18nViewTest(TestCase):
    def test_i18n_set_language_sets_cookie_and_redirects(self):
        response = self.client.post("/i18n/setlanguage/", data={"language": "es", "next": "/feed"})
        self.assertEqual(response.status_code, 302)
        self.assertIn("django_language", response.cookies)
        self.assertEqual(response.cookies["django_language"].value, "es")

    def test_feed_renders_spanish_when_language_cookie_is_set(self):
        self.client.cookies.load({"django_language": "es"})
        with patch("apps.core.views.relay_req", return_value={}):
            response = self.client.get(reverse("feed"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Malla")
        self.assertContains(response, "Galería")
class Phase24ViewsTest(TestCase):
    """Phase 24 tests for translation pipeline and iyou scoping."""

    def test_api_translate_resilient_fallback_returns_200(self):
        url = reverse("api_translate")
        payload = {
            "text": "¡hola mundo nostr! ¿cómo estás?",
            "source_lang": "es",
            "target_lang": "en",
        }
        response = self.client.post(
            url,
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["translated_text"], "Hello nostr world! How are you?")
        self.assertEqual(data["source_lang"], "es")
        self.assertEqual(data["target_lang"], "en")

        # Test unknown text fallback
        unknown_payload = {
            "text": "Un texte inconnu",
            "source_lang": "fr",
            "target_lang": "en",
        }
        res_unknown = self.client.post(
            url,
            data=json.dumps(unknown_payload),
            content_type="application/json",
        )
        self.assertEqual(res_unknown.status_code, 200)
        data_unknown = res_unknown.json()
        self.assertTrue(data_unknown["success"])
        self.assertIn("[Translation unavailable", data_unknown["translated_text"])

    def test_api_translate_empty_text_returns_400(self):
        url = reverse("api_translate")
        response = self.client.post(
            url,
            data=json.dumps({"text": ""}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertIn("error", data)

    def test_iyou_feed_zero_bleed_when_empty(self):
        url = reverse("api_feed") + "?circle=iyou"
        with patch("apps.core.views.get_iyou_pubkeys", return_value=[]), patch("apps.core.views.relay_req") as mock_relay:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertTrue(data.get("success"))
            self.assertEqual(data["notes"], [])
            self.assertEqual(data["replies"], {})
            self.assertFalse(data["has_more"])
            mock_relay.assert_not_called()

    def test_api_translate_endpoint_post(self):
        """Asserts POST /api/translate/ returns 200 with JSON payload."""
        url = reverse("api_translate")
        response = self.client.post(
            url,
            data=json.dumps({"text": "Hello world", "source_lang": "en", "target_lang": "es"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertIn("translated_text", data)
        self.assertIn("source_lang", data)
        self.assertIn("target_lang", data)

    def test_api_translate_with_spanish_text(self):
        """Asserts Spanish text gets translated in mock fallback."""
        url = reverse("api_translate")
        response = self.client.post(
            url,
            data=json.dumps({"text": "¡hola mundo!", "source_lang": "es", "target_lang": "en"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        # The offline mock translator handles this known phrase deterministically
        # (no external network), so the exact translation is asserted.
        self.assertEqual(data["translated_text"], "Hello world!")

    @override_settings(TRANSLATION_API_URL="http://translator.test/translate")
    def test_api_translate_backend_success_is_hermetic(self):
        """Hermetic: the external backend call is mocked; no network is touched."""
        url = reverse("api_translate")
        with patch("apps.core.views._translate_via_backend", return_value="Hola mundo") as mock_backend:
            response = self.client.post(
                url,
                data=json.dumps({"text": "Hello world", "source_lang": "en", "target_lang": "es"}),
                content_type="application/json",
            )
        mock_backend.assert_called_once()
        mock_backend.assert_called_once_with("Hello world", "en", "es", "http://translator.test/translate")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["translated_text"], "Hola mundo")
        self.assertFalse(data["cached"])

    @override_settings(TRANSLATION_API_URL="http://translator.test/translate")
    def test_api_translate_backend_timeout_falls_back_gracefully(self):
        """Hermetic: a backend timeout degrades to 200 with offline fallback text."""
        url = reverse("api_translate")
        with patch("apps.core.views._translate_via_backend", return_value=None) as mock_backend:
            response = self.client.post(
                url,
                data=json.dumps({"text": "¡hola mundo!", "source_lang": "es", "target_lang": "en"}),
                content_type="application/json",
            )
        mock_backend.assert_called_once()
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["translated_text"], "Hello world!")

    @override_settings(TRANSLATION_API_URL="http://translator.test/translate")
    def test_api_translate_backend_exception_returns_200_fallback(self):
        """Hermetic: any backend exception is suppressed and returns 200 fallback."""
        url = reverse("api_translate")
        with patch("apps.core.views._translate_via_backend", side_effect=Exception("boom")) as mock_backend:
            response = self.client.post(
                url,
                data=json.dumps({"text": "guten morgen", "source_lang": "de", "target_lang": "en"}),
                content_type="application/json",
            )
        mock_backend.assert_called_once()
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["translated_text"], "good morning")

    def test_api_translate_unknown_phrase_offline_fallback(self):
        """Hermetic: unknown text degrades to the offline unavailable marker, still 200."""
        url = reverse("api_translate")
        response = self.client.post(
            url,
            data=json.dumps({"text": "xq virtual phrase zz", "source_lang": "fr", "target_lang": "en"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertIn("translated_text", data)
        self.assertIn("Translation unavailable", data["translated_text"])

    def test_api_translate_exceeds_max_length_returns_400(self):
        """Asserts text exceeding 1000 characters returns 400 error."""
        url = reverse("api_translate")
        long_text = "a" * 1001
        response = self.client.post(
            url,
            data=json.dumps({"text": long_text, "source_lang": "en", "target_lang": "es"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)


class TranslationUITest(TestCase):
    """Phase 27: Translation UI Tests."""

    def setUp(self):
        User.objects.create_user(username=f"did:iyou:0x{VALID_PUBKEY_HEX}")

    def test_thread_post_omits_translate_button_for_english_notes(self):
        """Asserts notes with lang='en' do not render .translate-btn."""
        from unittest.mock import patch
        from .helpers import make_event
        
        # Create an English note
        english_event = make_event("e1", 1, content="Hello world", tags=[])
        
        with patch("apps.core.views.relay_req", return_value={"e1": english_event}):
            response = self.client.get(reverse("feed"))
        
        self.assertEqual(response.status_code, 200)
        # Check that translate-btn is NOT in the response for English notes
        self.assertNotContains(response, 'class="translate-btn')
        
        # Now test with a non-English note
        spanish_event = make_event("e2", 1, content="Hola mundo", tags=[["lang", "es"]])
        
        with patch("apps.core.views.relay_req", return_value={"e2": spanish_event}):
            response = self.client.get(reverse("feed"))
        
        self.assertEqual(response.status_code, 200)
        # Check that translate-btn IS in the response for Spanish notes
        self.assertContains(response, 'class="translate-btn')


class Phase36RelaySyncTest(TestCase):
    """Phase 36: Relay Switchboard Sync tests."""

    def setUp(self):
        User.objects.create_user(username=f"did:iyou:0x{VALID_PUBKEY_HEX}")

    def test_api_feed_respects_client_relays_parameter(self):
        """Test that api_feed endpoint uses client-provided relays when available."""
        custom_relays = ["wss://custom.relay.com", "wss://another.relay.com"]
        
        with patch("apps.core.views.relay_req", return_value={}) as mock_relay_req:
            # Call without custom relays
            response = self.client.get("/api/feed")
            self.assertEqual(response.status_code, 200)
            
            # Call with custom relays
            response = self.client.get("/api/feed?relays=" + json.dumps(custom_relays))
            self.assertEqual(response.status_code, 200)
            
            # Verify that relay_req was called with the custom relays
            self.assertTrue(mock_relay_req.called)
            # Get the last call's kwargs
            last_call_kwargs = mock_relay_req.call_args[1]
            self.assertIn("relay_urls", last_call_kwargs)
            self.assertEqual(last_call_kwargs["relay_urls"], custom_relays)

    def test_api_feed_falls_back_to_default_relays(self):
        """Test that api_feed falls back to default relays when client relays not provided."""
        with patch("apps.core.views.relay_req", return_value={}) as mock_relay_req:
            with patch("apps.core.views.get_relays_for_request", return_value=["wss://default.relay.com"]):
                response = self.client.get("/api/feed")
                self.assertEqual(response.status_code, 200)
                
                # Verify fallback to default relays
                last_call_kwargs = mock_relay_req.call_args[1]
                self.assertIn("relay_urls", last_call_kwargs)
                self.assertEqual(last_call_kwargs["relay_urls"], ["wss://default.relay.com"])


class Phase36NIP05EndpointTest(TestCase):
    """Phase 36: NIP-05 endpoint tests."""

    def setUp(self):
        self.user = User.objects.create_user(username="did:test:123")
        self.deck = UserLinkDeck.objects.create(
            user=self.user,
            handle="testuser",
            is_public=True
        )

    def test_nip05_well_known_resolves_claimed_handle(self):
        """Test that GET /.well-known/nostr.json?name=testuser returns proper JSON mapping."""
        # Patch did_to_pubkey to return a known pubkey
        with patch("apps.core.views.did_to_pubkey", return_value="abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890"):
            response = self.client.get("/.well-known/nostr.json", {"name": "testuser"})
            
            self.assertEqual(response.status_code, 200)
            data = response.json()
            
            # Check JSON structure
            self.assertIn("names", data)
            self.assertIn("relays", data)
            
            # Check handle mapping
            self.assertIn("testuser", data["names"])
            self.assertEqual(data["names"]["testuser"], "abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890")
            
            # Check CORS header
            self.assertEqual(response["Access-Control-Allow-Origin"], "*")

    def test_nip05_well_known_returns_empty_for_missing_handle(self):
        """Test that non-existent handles return empty names dict."""
        response = self.client.get("/.well-known/nostr.json", {"name": "nonexistent"})
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("names", data)
        self.assertEqual(data["names"], {})

    def test_nip05_well_known_returns_empty_for_missing_name(self):
        """Test that missing name parameter returns empty names dict."""
        response = self.client.get("/.well-known/nostr.json")
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("names", data)

    def test_nip05_well_known_resolves_discriminator_format(self):
        """Test that NIP-05 handles with discriminator format (handle_disc) are resolved correctly."""
        # Create a deck with discriminator
        user2 = User.objects.create_user(username="did:test:discuser")
        UserLinkDeck.objects.create(
            user=user2,
            handle="discuser",
            discriminator=2,
            is_public=True
        )
        
        # Patch did_to_pubkey to return a known pubkey
        with patch("apps.core.views.did_to_pubkey", return_value="discpubkey1234567890abcdef1234567890abcdef1234567890abcdef1234567890"):
            # Test lookup with discriminator format (handle_disc)
            response = self.client.get("/.well-known/nostr.json", {"name": "discuser_2"})
            
            self.assertEqual(response.status_code, 200)
            data = response.json()
            
            # Check JSON structure
            self.assertIn("names", data)
            self.assertIn("relays", data)
            
            # Check handle with discriminator mapping
            self.assertIn("discuser_2", data["names"])
            self.assertEqual(data["names"]["discuser_2"], "discpubkey1234567890abcdef1234567890abcdef1234567890abcdef1234567890")
            
            # Check CORS header
            self.assertEqual(response["Access-Control-Allow-Origin"], "*")


class Phase36ProfileNotesAPITest(TestCase):
    """Phase 36: Profile notes API tests."""

    def test_api_profile_notes_returns_json_stream(self):
        """Test that the profile notes API returns 200 response with proper JSON structure."""
        test_pubkey = "abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890"
        
        # Mock the resolve_universal_identifier to return our test pubkey
        with patch("apps.core.views.resolve_universal_identifier", return_value=(test_pubkey, "npub1test")):
            with patch("apps.core.views.relay_req", return_value={}):
                response = self.client.get("/api/profile/npub1test/notes/")
                
                self.assertEqual(response.status_code, 200)
                data = response.json()
                
                # Check JSON structure
                self.assertIn("notes", data)
                self.assertIn("has_more", data)
                self.assertIsInstance(data["notes"], list)
                self.assertIsInstance(data["has_more"], bool)

    def test_api_profile_notes_handles_invalid_identifier(self):
        """Test that invalid identifier returns 400 response."""
        with patch("apps.core.views.resolve_universal_identifier", return_value=(None, None)):
            response = self.client.get("/api/profile/invalid/notes/")
            
            self.assertEqual(response.status_code, 400)
            data = response.json()
            self.assertIn("error", data)

    def test_api_profile_notes_with_limit_and_until_params(self):
        """Test that limit and until parameters are processed correctly."""
        test_pubkey = "abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890"
        
        with patch("apps.core.views.resolve_universal_identifier", return_value=(test_pubkey, "npub1test")):
            with patch("apps.core.views.relay_req", return_value={}) as mock_relay_req:
                response = self.client.get("/api/profile/npub1test/notes/?limit=25&until=1234567890")
                
                self.assertEqual(response.status_code, 200)
                
                # Verify that relay_req was called with correct parameters
                first_call_args = mock_relay_req.call_args_list[0]
                filter_obj = first_call_args[0][0] if first_call_args and first_call_args[0] else {}
                
                self.assertEqual(filter_obj.get("limit"), 25)
                self.assertEqual(filter_obj.get("until"), 1234567890)
                self.assertEqual(filter_obj.get("kinds"), [1])
                self.assertIn(test_pubkey, filter_obj.get("authors", []))


class Phase37GlobalScriptTest(TestCase):
    """Phase 37: Global script hoisting tests."""

    def setUp(self):
        self.user = User.objects.create_user(username="did:key:z6MkhaXgBZDvotDkL5257faiztiGiC2QtKLGpbnnEGta2doK")

    def test_base_html_renders_global_bridge_scripts_on_all_views(self):
        """Test that bridge_client.js is rendered across feed, gallery, chat, and profile."""
        self.client.force_login(self.user)

        # 1. Feed view
        res_feed = self.client.get("/feed")
        self.assertEqual(res_feed.status_code, 200)
        self.assertIn(b"bridge_client.js", res_feed.content)
        self.assertIn(b"toast_manager.js", res_feed.content)

        # 2. Gallery view
        res_gallery = self.client.get("/gallery")
        self.assertEqual(res_gallery.status_code, 200)
        self.assertIn(b"bridge_client.js", res_gallery.content)
        self.assertIn(b"toast_manager.js", res_gallery.content)

        # 3. Chat view
        res_chat = self.client.get("/chat")
        self.assertEqual(res_chat.status_code, 200)
        self.assertIn(b"bridge_client.js", res_chat.content)
        self.assertIn(b"toast_manager.js", res_chat.content)

        # 4. Profile view
        res_profile = self.client.get("/profile/testuser")
        self.assertEqual(res_profile.status_code, 200)
        self.assertIn(b"bridge_client.js", res_profile.content)
        self.assertIn(b"toast_manager.js", res_profile.content)
