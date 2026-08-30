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
from apps.core.views import hex_to_npub
from apps.core.models import UserLinkDeck



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
        self.assertContains(response, "import converse from 'https://cdn.conversejs.org/10.1.7/dist/converse.min.js'")
        self.assertContains(response, "auto_join_private_chats: autoJoinChats")





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
        self.assertContains(response, "Posts (2)")
        self.assertContains(response, "Replies (1)")
        self.assertContains(response, "Media (1)")
        self.assertContains(response, "https://example.com/avatar.jpg")
        self.assertContains(response, "https://example.com/banner.jpg")

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


    def test_standard_header_renders_profile_link_for_authenticated_user(self):
        pk = "3bf0c63fcb93463407af97a5e5ee64fa883d107ef9e558472c4eb9aaaefa459d"
        npub = hex_to_npub(pk)
        user = User.objects.create_user(username=f"did:iyou:0x{pk}")
        self.client.force_login(user)
        with patch("apps.core.views.relay_req", return_value={}):
            response = self.client.get(reverse("feed"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f"/profile/{npub}/")
        self.assertContains(response, "[ ⚙️ Edit ]")

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


class FeedViewTwoTierToolbarTest(TestCase):
    """Two-tier Layer 2 toolbar & circle feed filtering contract tests."""

    @classmethod
    def setUpTestData(cls):
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

    def test_external_relay_note_does_not_contain_synthetic_did_or_static_verified_badge(self):
        # External relay note (e.g. jb55 from nos.lol)
        external_pubkey = "32e1827635450ebb3c5a7d12c1f8e7b2b514439ac10a67eef3d9fd9c5c68e245"
        relay_events = {
            "ext_note_1": make_event("ext_note_1", 1, pubkey=external_pubkey, content="Hello decentralized world!"),
        }
        with patch("apps.core.views.relay_req", return_value=relay_events):
            response = self.client.get(reverse("feed"))

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
        self.assertContains(response, f'href="/profile/{root_npub}/"')
        self.assertContains(response, "@Alice In Chains")
        # Separate parent note link
        self.assertContains(response, 'href="/feed?thread=parent_note_123"')
        self.assertContains(response, "[ parent note ↗ ]")

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

    def test_layer2_nav_renders_nsfw_shield_toggle(self):
        with patch("apps.core.views.relay_req", return_value={}):
            response = self.client.get(reverse("feed"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="nsfw-filter-toggle"')
        self.assertContains(response, 'id="nsfw-filter-status"')
        self.assertContains(response, "toggleNsfwFilter()")
        self.assertContains(response, "Shield:")

    def test_nav_renders_iyou_circle_pill(self):
        with patch("apps.core.views.relay_req", return_value={}):
            response = self.client.get(reverse("feed"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-circle="iyou"')
        self.assertContains(response, "⚡ iyou")

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

        def mock_relay_req(filter_obj, relay_urls=None):
            captured_filter.update(filter_obj)
            return {
                "note_iyou": make_event("note_iyou", 1, pubkey="3bf0c63fcb93463407af97a5e5ee64fa883d107ef9e558472c4eb9aaaefa459d", content="Local ecosystem note"),
            }

        # 1. Test FeedView context GET ?circle=iyou
        with patch("apps.core.views.relay_req", side_effect=mock_relay_req):
            response = self.client.get(reverse("feed") + "?circle=iyou")
        self.assertEqual(response.status_code, 200)
        self.assertIn("authors", captured_filter)
        self.assertTrue(len(captured_filter["authors"]) > 0)

        # 2. Test api_feed JSON GET ?circle=iyou
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
        self.assertContains(response, "#bitcoin")
        self.assertContains(response, "#nostr")
        self.assertContains(response, "#wine")
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
        self.assertGreaterEqual(len(response.context["trending_tags"]), 3)
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












