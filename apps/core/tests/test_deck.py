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
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.core.models import UserLinkDeck
from apps.core.utils import (
    validate_external_bio_url,
    verify_external_profile_token,
)
from apps.core.views import (
    RESERVED_HANDLES,
    claim_handle,
    did_to_npub,
    did_to_pubkey,
)
from .helpers import make_event


def post_json(client, url, payload):
    return client.post(url, data=json.dumps(payload), content_type="application/json")


class DeckHandleClaimTests(TestCase):
    def _claim(self, user, handle):
        self.client.force_login(user)
        return post_json(self.client, reverse("api_deck_handle"), {"handle": handle})

    def test_first_claim_gets_discriminator_zero(self):
        user = User.objects.create_user(username="did:key:z6Mkalice1")
        response = self._claim(user, "alice")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["handle"], "alice")
        self.assertEqual(data["discriminator"], 0)
        self.assertEqual(data["display_handle"], "@alice")
        self.assertEqual(data["canonical_url"], "/@alice")

    def test_second_claim_increments_discriminator(self):
        first = User.objects.create_user(username="did:key:z6Mkalice1")
        second = User.objects.create_user(username="did:key:z6Mkalice2")
        self._claim(first, "alice")
        response = self._claim(second, "alice")
        data = response.json()
        self.assertEqual(data["discriminator"], 1)
        self.assertEqual(data["display_handle"], "@alice[1]")
        self.assertEqual(data["canonical_url"], "/@alice[1]")

    def test_third_claim_increments_discriminator(self):
        u1 = User.objects.create_user(username="did:key:z6Mkalice1")
        u2 = User.objects.create_user(username="did:key:z6Mkalice2")
        u3 = User.objects.create_user(username="did:key:z6Mkalice3")
        self._claim(u1, "alice")
        self._claim(u2, "alice")
        response = self._claim(u3, "alice")
        data = response.json()
        self.assertEqual(data["discriminator"], 2)
        self.assertEqual(data["display_handle"], "@alice[2]")

    def test_reserved_handle_rejected(self):
        user = User.objects.create_user(username="did:key:z6Mkreserv")
        for reserved in RESERVED_HANDLES:
            response = self._claim(user, reserved)
            self.assertEqual(response.status_code, 400, reserved)
            self.assertIn("reserved", response.json()["error"])
        self.assertFalse(UserLinkDeck.objects.filter(user=user).exists())

    def test_at_prefix_stripped_and_normalized(self):
        user = User.objects.create_user(username="did:key:z6Mknormie")
        response = self._claim(user, "@Alice")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["handle"], "alice")

    def test_invalid_format_rejected(self):
        user = User.objects.create_user(username="did:key:z6Mkinvalid")
        for bad in ["ab", "x" * 33, "Bad Handle", "has space", "no!chars"]:
            response = self._claim(user, bad)
            self.assertEqual(response.status_code, 400, bad)
        self.assertFalse(UserLinkDeck.objects.filter(user=user).exists())

    def test_idempotent_reclaim_keeps_discriminator(self):
        user = User.objects.create_user(username="did:key:z6Mkidem1")
        first = self._claim(user, "alice")
        second = self._claim(user, "alice")
        self.assertEqual(first.json()["discriminator"], 0)
        self.assertEqual(second.json()["discriminator"], 0)
        self.assertEqual(UserLinkDeck.objects.count(), 1)

    def test_rename_then_old_handle_reclaimable(self):
        u1 = User.objects.create_user(username="did:key:z6Mkrename1")
        u2 = User.objects.create_user(username="did:key:z6Mkrename2")
        u3 = User.objects.create_user(username="did:key:z6Mkrename3")
        self._claim(u1, "delta")
        self._claim(u2, "delta")
        response = self._claim(u1, "omega")
        self.assertEqual(response.status_code, 200)
        response = self._claim(u3, "delta")
        self.assertEqual(response.json()["discriminator"], 2)

    def test_headline_update_via_handle_endpoint(self):
        user = User.objects.create_user(username="did:key:z6Mkheadline1")
        deck = claim_handle(user, "owner")
        self.client.force_login(user)
        response = post_json(self.client, reverse("api_deck_handle"), {"headline": "Sovereign since day one"})
        self.assertEqual(response.status_code, 200)
        deck.refresh_from_db()
        self.assertEqual(deck.headline, "Sovereign since day one")

    def test_headline_requires_deck(self):
        other = User.objects.create_user(username="did:key:z6Mkheadline2")
        self.client.force_login(other)
        response = post_json(self.client, reverse("api_deck_handle"), {"headline": "sneaky"})
        self.assertEqual(response.status_code, 400)

    def test_anonymous_gated(self):
        response = post_json(self.client, reverse("api_deck_handle"), {"handle": "alice"})
        self.assertEqual(response.status_code, 302)

    def test_get_method_rejected(self):
        user = User.objects.create_user(username="did:key:z6Mkgetmeth")
        self.client.force_login(user)
        response = self.client.get(reverse("api_deck_handle"))
        self.assertEqual(response.status_code, 405)


class DeckRoutingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user(username="did:key:z6Mkrouteal")
        cls.bob = User.objects.create_user(username="did:key:z6Mkroutebo")
        cls.deckless = User.objects.create_user(username="did:key:z6Mroutedck")
        cls.alice_deck = claim_handle(cls.alice, "alice")
        cls.bob_deck = claim_handle(cls.bob, "alice")

    def _get_with_relays_down(self, url):
        with patch("apps.core.views.relay_req", return_value={}) as mock_relay:
            response = self.client.get(url)
        return response, mock_relay

    def test_at_handle_route_resolves(self):
        response, _ = self._get_with_relays_down("/@alice")
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "link_deck.html")
        self.assertContains(response, "@alice")

    def test_trailing_slash_tolerated(self):
        response, _ = self._get_with_relays_down("/@alice/")
        self.assertEqual(response.status_code, 200)

    def test_discriminated_route_resolves(self):
        response, _ = self._get_with_relays_down("/@alice[1]")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "@alice[1]")

    def test_unknown_discriminator_404(self):
        response, _ = self._get_with_relays_down("/@alice[10]")
        self.assertEqual(response.status_code, 404)

    def test_unknown_handle_404(self):
        response, _ = self._get_with_relays_down("/@ghost")
        self.assertEqual(response.status_code, 404)

    def test_invalid_handle_not_routed(self):
        response = self.client.get("/@BadHandle")
        self.assertEqual(response.status_code, 404)

    def test_did_fallback_redirects_to_canonical_301(self):
        response = self.client.get(f"/u/{self.alice.username}/")
        self.assertEqual(response.status_code, 301)
        self.assertEqual(response["Location"], "/@alice")

    def test_did_fallback_redirects_discriminated_canonical(self):
        response = self.client.get(f"/u/{self.bob.username}/")
        self.assertEqual(response.status_code, 301)
        self.assertEqual(response["Location"], "/@alice[1]")

    def test_deck_routes_omit_floating_chat_dock_for_anonymous(self):
        """Public /@handle/ pages must not mount the chat dock for logged-out visitors."""
        for url in ("/@alice", f"/u/{self.deckless.username}/"):
            with self.subTest(url=url):
                response, _ = self._get_with_relays_down(url)
                self.assertEqual(response.status_code, 200)
                self.assertNotContains(response, "dock_embed.js")
                self.assertNotContains(response, "floating_chat.js")

    def test_deck_routes_mount_floating_chat_dock_for_authenticated(self):
        self.client.force_login(self.deckless)
        response, _ = self._get_with_relays_down(f"/u/{self.deckless.username}/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "dock_embed.js")
        self.assertContains(response, "data-chat-origin")

    def test_did_fallback_without_deck_renders_card(self):
        response, _ = self._get_with_relays_down(f"/u/{self.deckless.username}/")
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "link_deck.html")
        self.assertContains(response, "No links on this deck yet")

    def test_profile_hero_enrichment_from_kind0(self):
        hex_pubkey = did_to_pubkey(self.alice.username)
        profile_event = make_event(
            "p1", 0, pubkey=hex_pubkey,
            content=json.dumps({"display_name": "Alice Sovereign", "picture": "https://cdn.example.com/a.png"}),
        )
        with patch("apps.core.views.relay_req", return_value={"p1": profile_event}):
            response = self.client.get("/@alice")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Alice Sovereign")

    def test_link_deck_renders_message_button_for_authenticated_viewer(self):
        # 1. Authenticated peer viewing alice's deck sees message button
        self.client.force_login(self.bob)
        response, _ = self._get_with_relays_down("/@alice")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "action-btn-direct-message")
        self.assertContains(response, "💬")
        self.assertContains(response, "Message")

        # 2. Owner viewing own deck does not see message button
        self.client.force_login(self.alice)
        owner_response, _ = self._get_with_relays_down("/@alice")
        self.assertEqual(owner_response.status_code, 200)
        self.assertNotContains(owner_response, "action-btn-direct-message")

        # 3. Anonymous user does not see message button
        self.client.logout()
        anon_response, _ = self._get_with_relays_down("/@alice")
        self.assertEqual(anon_response.status_code, 200)
        self.assertNotContains(anon_response, "action-btn-direct-message")

    def test_link_deck_json_content_negotiation_accept_header(self):
        deck = self.alice_deck
        with patch("apps.core.views.relay_req", return_value={}):
            response = self.client.get(f"/@{deck.handle}", HTTP_ACCEPT="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Content-Type"], "application/json")
        data = response.json()
        self.assertEqual(data["did"], deck.user.username)
        self.assertEqual(data["handle"], deck.handle)
        self.assertEqual(data["discriminator"], 0)
        self.assertEqual(data["canonical_handle"], "@alice")
        self.assertIn("items", data)
        self.assertIn("profile", data)
        self.assertEqual(response.headers.get("Access-Control-Allow-Origin"), "*")

    def test_link_deck_json_format_query_parameter(self):
        deck = self.alice_deck
        with patch("apps.core.views.relay_req", return_value={}):
            response = self.client.get(f"/@{deck.handle}?format=json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Content-Type"], "application/json")
        data = response.json()
        self.assertEqual(data["handle"], deck.handle)
        self.assertEqual(data["did"], deck.user.username)
        self.assertEqual(response.headers.get("Access-Control-Allow-Origin"), "*")

    def test_link_deck_json_returns_404_for_missing_handle(self):
        with patch("apps.core.views.relay_req", return_value={}):
            response = self.client.get("/@nonexistentuser", HTTP_ACCEPT="application/json")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.headers["Content-Type"], "application/json")
        data = response.json()
        self.assertIn("error", data)
        self.assertEqual(data["error"], "Deck not found")
        self.assertEqual(response.headers.get("Access-Control-Allow-Origin"), "*")

    def test_link_deck_json_content_negotiation_discriminated_handle(self):
        deck = self.bob_deck
        with patch("apps.core.views.relay_req", return_value={}):
            response = self.client.get(f"/@{deck.handle}[1]", HTTP_ACCEPT="application/json")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["canonical_handle"], "@alice[1]")
        self.assertEqual(data["discriminator"], 1)


class DashboardDeckTabTests(TestCase):
    def test_dashboard_contains_migrated_deck_handoff_cta(self):
        user = User.objects.create_user(username="did:key:z6Mkdashtab")
        self.client.force_login(user)
        with patch("apps.core.views.relay_req", return_value={}):
            response = self.client.get(reverse("dashboard"))
        self.assertContains(response, "Sovereign Link Decks have migrated")
        self.assertContains(response, "https://link.iyou.me/manager")
        self.assertContains(response, "Manage Link Deck")


class ProfileDeckChipsTests(TestCase):
    CHIP_DID_WITH_DECK = "did:key:z6MkhaXgBZDvB9gCHIPS1"
    CHIP_DID_NO_DECK = "did:key:z6MkhaXgBZDvB9gCHIPSO"

    def _profile_url_for(self, user):
        npub = did_to_npub(user.username)
        return reverse("profile", kwargs={"npub": npub})

    def test_profile_shows_outbound_deck_button(self):
        user = User.objects.create_user(username=self.CHIP_DID_WITH_DECK)
        claim_handle(user, "chips")
        with patch("apps.core.views.relay_req", return_value={}):
            response = self.client.get(self._profile_url_for(user))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "View Official Link Deck")
        self.assertContains(response, "https://link.iyou.me/@chips")

    def test_profile_hides_outbound_deck_button_without_deck(self):
        user = User.objects.create_user(username=self.CHIP_DID_NO_DECK)
        with patch("apps.core.views.relay_req", return_value={}):
            response = self.client.get(self._profile_url_for(user))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "View Official Link Deck")


class BioScraperSSRFTests(TestCase):
    def test_https_enforced(self):
        ok, reason = validate_external_bio_url("http://github.com/user")
        self.assertFalse(ok)
        self.assertIn("https", reason)

    def test_ftp_scheme_rejected(self):
        ok, _ = validate_external_bio_url("ftp://github.com/user")
        self.assertFalse(ok)

    def test_javascript_scheme_rejected(self):
        ok, _ = validate_external_bio_url("javascript://github.com/alert(1)")
        self.assertFalse(ok)

    def test_missing_hostname_rejected(self):
        ok, reason = validate_external_bio_url("https:///only-a-path")
        self.assertFalse(ok)
        self.assertIn("hostname", reason)

    def test_loopback_ip_blocked(self):
        for url in ["https://127.0.0.1/token", "https://127.1.1.9/x"]:
            ok, _ = validate_external_bio_url(url)
            self.assertFalse(ok, url)

    def test_localhost_blocked(self):
        ok, _ = validate_external_bio_url("https://localhost/x")
        self.assertFalse(ok)

    def test_zero_address_blocked(self):
        ok, _ = validate_external_bio_url("https://0.0.0.0/x")
        self.assertFalse(ok)

    def test_private_ranges_blocked(self):
        for url in ["https://10.0.0.5/", "https://192.168.1.10/", "https://172.16.0.9/"]:
            ok, _ = validate_external_bio_url(url)
            self.assertFalse(ok, url)

    def test_link_local_metadata_blocked(self):
        ok, _ = validate_external_bio_url("https://169.254.169.254/latest/meta-data/")
        self.assertFalse(ok)

    def test_ipv6_loopback_blocked(self):
        ok, _ = validate_external_bio_url("https://[::1]/x")
        self.assertFalse(ok)

    def test_internal_tlds_blocked(self):
        for url in ["https://relay.local/", "https://svc.internal/"]:
            ok, reason = validate_external_bio_url(url)
            self.assertFalse(ok, url)
            self.assertIn("blocked", reason.lower())

    def test_non_allowlisted_domain_blocked(self):
        ok, reason = validate_external_bio_url("https://example.com/profile")
        self.assertFalse(ok)
        self.assertIn("allowlist", reason.lower())

    def test_subdomain_spoof_blocked(self):
        ok, _ = validate_external_bio_url("https://github.com.evil.com/user")
        self.assertFalse(ok)

    def test_embedded_credentials_rejected(self):
        ok, _ = validate_external_bio_url("https://user:pass@github.com/user")
        self.assertFalse(ok)

    def test_allowlisted_hosts_accepted(self):
        for url in [
            "https://github.com/user",
            "https://gist.github.com/someone/abc",
            "https://www.x.com/handle",
            "https://mastodon.social/@someone",
            "https://bsky.app/profile/someone.bsky.social",
            "https://threads.net/@someone",
            "https://twitter.com/someone",
        ]:
            ok, _ = validate_external_bio_url(url)
            self.assertTrue(ok, url)

    def test_verify_blocks_before_any_network_call(self):
        with patch("apps.core.utils._OPENER") as opener:
            opener.open.side_effect = AssertionError("network access attempted")
            ok, _ = verify_external_profile_token("http://127.0.0.1/token-page", "tok")
        self.assertFalse(ok)


def _mock_fetch_response(body):
    cm = MagicMock()
    response = MagicMock()
    response.read.return_value = body
    response.headers.get_content_charset.return_value = "utf-8"
    cm.__enter__.return_value = response
    return cm


class BioScraperFetchTests(TestCase):
    TOKEN = "iyou-verify-wun-abcdef1234567890"

    def test_token_found_in_body(self):
        html = f"<html><head></head><body>bio text {self.TOKEN} more</body></html>".encode()
        with patch("apps.core.utils._OPENER") as opener:
            opener.open.return_value = _mock_fetch_response(html)
            ok, message = verify_external_profile_token("https://github.com/u", self.TOKEN)
        self.assertTrue(ok)
        self.assertEqual(message, "Token verified successfully")

    def test_token_absent_in_body(self):
        html = b"<html><body>some unrelated bio</body></html>"
        with patch("apps.core.utils._OPENER") as opener:
            opener.open.return_value = _mock_fetch_response(html)
            ok, reason = verify_external_profile_token("https://github.com/u", self.TOKEN)
        self.assertFalse(ok)
        self.assertEqual(reason, "Token not found in bio content")

    def test_response_truncated_at_512kb(self):
        padding = b"x" * (512 * 1024)
        body = padding + self.TOKEN.encode()
        with patch("apps.core.utils._OPENER") as opener:
            opener.open.return_value = _mock_fetch_response(body)
            ok, reason = verify_external_profile_token("https://github.com/u", self.TOKEN)
        self.assertFalse(ok)
        self.assertEqual(reason, "Token not found in bio content")

    def test_fetch_error_returns_false(self):
        with patch("apps.core.utils._OPENER") as opener:
            opener.open.side_effect = OSError("connection refused")
            ok, reason = verify_external_profile_token("https://github.com/u", self.TOKEN)
        self.assertFalse(ok)
        self.assertIn("Fetch failed", reason)

    def test_empty_token_short_circuits(self):
        ok, reason = verify_external_profile_token("https://github.com/u", "   ")
        self.assertFalse(ok)
        self.assertIn("missing", reason.lower())


class VerifiedBadgeRenderingTests(TestCase):
    def test_public_deck_renders_verified_badge(self):
        owner = User.objects.create_user(username="did:key:z6Mkbadgeon")
        deck = claim_handle(owner, "badged")
        deck.is_verified = True
        deck.verified_source_url = "https://github.com/badged"
        deck.verified_at = timezone.now()
        deck.save()
        with patch("apps.core.views.relay_req", return_value={}):
            response = self.client.get("/@badged")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "\u2713 VERIFIED")
        self.assertContains(response, "Verified Sovereign Ownership via https://github.com/badged")

    def test_public_deck_hides_badge_when_unverified(self):
        owner = User.objects.create_user(username="did:key:z6Mkbadgeoff")
        claim_handle(owner, "plainbadge")
        with patch("apps.core.views.relay_req", return_value={}):
            response = self.client.get("/@plainbadge")
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "VERIFIED")

    def test_profile_hero_renders_verified_badge(self):
        owner = User.objects.create_user(username="did:key:z6MkhaXgBZDvB9gBADGE")
        deck = claim_handle(owner, "profbadge")
        deck.is_verified = True
        deck.verified_source_url = "https://x.com/profbadge"
        deck.save()
        npub = did_to_npub(owner.username)
        with patch("apps.core.views.relay_req", return_value={}):
            response = self.client.get(reverse("profile", kwargs={"npub": npub}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "VERIFIED")


class Phase37NIP05DerivationTest(TestCase):
    """Phase 37: Automated Handle-to-NIP-05 Derivation tests."""

    def setUp(self):
        self.user = User.objects.create_user(username="did:test:user123")

    def test_user_link_deck_automatically_derives_nip05_on_save(self):
        """Test that claiming handle='alice' sets nip05='alice@iyou.me'."""
        deck = UserLinkDeck.objects.create(
            user=self.user,
            handle="alice",
            discriminator=0
        )
        self.assertEqual(deck.nip05, "alice@iyou.me")

    def test_user_link_deck_derives_discriminator_nip05(self):
        """Test that discriminator=2 yields 'alice_2@iyou.me'."""
        deck = UserLinkDeck.objects.create(
            user=self.user,
            handle="alice",
            discriminator=2
        )
        self.assertEqual(deck.nip05, "alice_2@iyou.me")

    def test_user_link_deck_updates_nip05_on_handle_change(self):
        """Test that updating handle updates NIP-05 automatically."""
        deck = UserLinkDeck.objects.create(
            user=self.user,
            handle="alice",
            discriminator=0
        )
        self.assertEqual(deck.nip05, "alice@iyou.me")

        # Change handle
        deck.handle = "bob"
        deck.save()

        # Refresh from DB
        deck.refresh_from_db()
        self.assertEqual(deck.nip05, "bob@iyou.me")

    def test_user_link_deck_handles_mixed_case_handle(self):
        """Test that mixed-case handles are normalized to lowercase."""
        deck = UserLinkDeck.objects.create(
            user=self.user,
            handle="Alice",
            discriminator=0
        )
        self.assertEqual(deck.nip05, "alice@iyou.me")

    def test_user_link_deck_strips_at_symbol(self):
        """Test that @ symbol is stripped from handle."""
        deck = UserLinkDeck.objects.create(
            user=self.user,
            handle="@alice",
            discriminator=0
        )
        self.assertEqual(deck.nip05, "alice@iyou.me")


class VerifiedEmailBadgeTests(TestCase):
    """OIDC userinfo extraction captures public_emails in session."""

    def test_oidc_userinfo_extraction_records_verified_public_emails(self):
        from apps.core.auth import MyOIDCAuthenticationBackend
        from apps.core.auth_pkce import PKCEAuthenticationBackend
        from django.test.client import RequestFactory

        rf = RequestFactory()
        request = rf.get("/oidc/callback/")
        request.session = self.client.session

        backend = MyOIDCAuthenticationBackend()
        backend.request = request

        user_info = {
            "sub": "did:key:z6Mkoidcemailtest",
            "public_emails": ["verified.user@company.com"],
        }
        with patch.object(
            MyOIDCAuthenticationBackend,
            "get_userinfo",
            wraps=backend.get_userinfo,
        ):
            with patch("mozilla_django_oidc.auth.OIDCAuthenticationBackend.get_userinfo", return_value=user_info):
                result = backend.get_userinfo("access_tok", "id_tok", {})
                self.assertEqual(result["public_emails"], ["verified.user@company.com"])
                self.assertEqual(
                    request.session.get("verified_public_emails"),
                    ["verified.user@company.com"],
                )

        # Test PKCEAuthenticationBackend as well
        pkce_backend = PKCEAuthenticationBackend()
        pkce_backend.request = request
        with patch("mozilla_django_oidc.auth.OIDCAuthenticationBackend.get_userinfo", return_value=user_info):
            result_pkce = pkce_backend.get_userinfo("access_tok", "id_tok", {})
            self.assertEqual(result_pkce["public_emails"], ["verified.user@company.com"])
            self.assertEqual(
                request.session.get("verified_public_emails"),
                ["verified.user@company.com"],
            )
