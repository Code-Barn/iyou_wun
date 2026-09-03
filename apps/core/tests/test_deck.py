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
from datetime import timedelta
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.core.models import (
    HandleVerificationChallenge,
    UserLinkDeck,
    UserLinkItem,
)
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


def patch_json(client, url, payload):
    return client.patch(url, data=json.dumps(payload), content_type="application/json")


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

    def test_seeded_ecosystem_items_created_on_first_deck(self):
        user = User.objects.create_user(username="did:key:z6Mkseedme")
        self._claim(user, "seeder")
        deck = UserLinkDeck.objects.get(user=user)
        seeds = deck.items.filter(is_ecosystem_link=True)
        self.assertEqual(seeds.count(), 4)
        categories = set(seeds.values_list("icon_category", flat=True))
        self.assertEqual(categories, {"blog", "talk", "poly", "gallery"})
        self.assertFalse(seeds.filter(is_active=True).exists())

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

    def test_did_fallback_without_deck_renders_card(self):
        response, _ = self._get_with_relays_down(f"/u/{self.deckless.username}/")
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "link_deck.html")
        self.assertContains(response, "No links on this deck yet")

    def test_active_items_rendered_inactive_hidden(self):
        UserLinkItem.objects.create(
            deck=self.alice_deck, title="Visible Link", url="https://example.com",
            icon_category="website", order=10,
        )
        hidden = UserLinkItem.objects.create(
            deck=self.alice_deck, title="Hidden Link", url="https://secret.example.com",
            icon_category="website", order=11,
        )
        hidden.is_active = False
        hidden.save()
        response, _ = self._get_with_relays_down("/@alice")
        self.assertContains(response, "Visible Link")
        self.assertNotContains(response, "Hidden Link")

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


class DeckItemAPITests(TestCase):
    @classmethod
    def setUpTestData(cls):
        pass

    def setUp(self):
        self.owner = User.objects.create_user(username="did:key:z6Mkapiown")
        self.other = User.objects.create_user(username="did:key:z6Mkapioth")
        self.deck = claim_handle(self.owner, "owner")

    def _create_item(self, **overrides):
        payload = {
            "title": overrides.pop("title", "My X"),
            "url": overrides.pop("url", "https://x.com/owner"),
            "icon_category": overrides.pop("icon_category", "x"),
        }
        payload.update(overrides)
        return post_json(self.client, reverse("api_deck_items"), payload)

    def test_create_item_returns_201(self):
        self.client.force_login(self.owner)
        response = self._create_item()
        self.assertEqual(response.status_code, 201)
        item = response.json()["item"]
        self.assertEqual(item["title"], "My X")
        self.assertEqual(item["icon_category"], "x")
        self.assertTrue(item["is_active"])

    def test_create_requires_claimed_deck(self):
        self.client.force_login(self.other)
        response = self._create_item()
        self.assertEqual(response.status_code, 400)

    def test_create_validates_fields(self):
        self.client.force_login(self.owner)
        self.assertEqual(self._create_item(title="   ").status_code, 400)
        self.assertEqual(self._create_item(url="").status_code, 400)
        long_title = "t" * 65
        self.assertEqual(self._create_item(title=long_title).status_code, 400)
        self.assertEqual(self._create_item(icon_category="bitcoin").status_code, 400)

    def test_list_returns_all_items_including_inactive(self):
        UserLinkItem.objects.create(deck=self.deck, title="Off Item", url="https://off.example.com", is_active=False)
        self.client.force_login(self.owner)
        response = self.client.get(reverse("api_deck_items"))
        data = response.json()
        self.assertEqual(data["handle"], "owner")
        titles = [i["title"] for i in data["items"]]
        self.assertIn("Off Item", titles)
        self.assertEqual(len(titles), 5)  # 4 ecosystem seeds + 1 custom

    def test_patch_toggle_is_active(self):
        item = UserLinkItem.objects.create(deck=self.deck, title="Blog", url="https://blog.example.com")
        self.client.force_login(self.owner)
        response = patch_json(self.client, reverse("api_deck_item_detail", kwargs={"pk": item.id}), {"is_active": False})
        self.assertTrue(response.json()["ok"])
        item.refresh_from_db()
        self.assertFalse(item.is_active)

    def test_patch_updates_fields(self):
        item = UserLinkItem.objects.create(deck=self.deck, title="Old", url="https://old.example.com")
        self.client.force_login(self.owner)
        response = patch_json(
            self.client,
            reverse("api_deck_item_detail", kwargs={"pk": item.id}),
            {"title": "New", "url": "https://new.example.com", "icon_category": "github"},
        )
        data = response.json()["item"]
        self.assertEqual(data["title"], "New")
        self.assertEqual(data["url"], "https://new.example.com")
        self.assertEqual(data["icon_category"], "github")

    def test_delete_item(self):
        item = UserLinkItem.objects.create(deck=self.deck, title="Doomed", url="https://doom.example.com")
        self.client.force_login(self.owner)
        response = self.client.delete(reverse("api_deck_item_detail", kwargs={"pk": item.id}))
        self.assertTrue(response.json()["ok"])
        self.assertFalse(UserLinkItem.objects.filter(pk=item.id).exists())

    def test_non_owner_cannot_modify_or_delete(self):
        foreign_item = UserLinkItem.objects.create(deck=self.deck, title="Mine", url="https://mine.example.com")
        self.client.force_login(self.other)
        patch_response = patch_json(
            self.client,
            reverse("api_deck_item_detail", kwargs={"pk": foreign_item.id}),
            {"title": "Hacked"},
        )
        delete_response = self.client.delete(reverse("api_deck_item_detail", kwargs={"pk": foreign_item.id}))
        self.assertEqual(patch_response.status_code, 403)
        self.assertEqual(delete_response.status_code, 403)
        foreign_item.refresh_from_db()
        self.assertEqual(foreign_item.title, "Mine")

    def test_non_owner_cannot_add_to_foreign_deck(self):
        self.client.force_login(self.other)
        response = self._create_item()
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.deck.items.filter(is_ecosystem_link=False).count(), 0)

    def test_anonymous_gated(self):
        item = UserLinkItem.objects.create(deck=self.deck, title="Gate", url="https://gate.example.com")
        self.assertEqual(self.client.get(reverse("api_deck_items")).status_code, 302)
        self.assertEqual(post_json(self.client, reverse("api_deck_items"), {}).status_code, 302)
        self.assertEqual(
            patch_json(self.client, reverse("api_deck_item_detail", kwargs={"pk": item.id}), {}).status_code, 302
        )
        self.assertEqual(
            self.client.delete(reverse("api_deck_item_detail", kwargs={"pk": item.id})).status_code, 302
        )

    def test_missing_item_404(self):
        self.client.force_login(self.owner)
        response = patch_json(self.client, reverse("api_deck_item_detail", kwargs={"pk": 99999}), {})
        self.assertEqual(response.status_code, 404)

    def test_headline_update_via_handle_endpoint(self):
        self.client.force_login(self.owner)
        response = post_json(self.client, reverse("api_deck_handle"), {"headline": "Sovereign since day one"})
        self.assertEqual(response.status_code, 200)
        self.deck.refresh_from_db()
        self.assertEqual(self.deck.headline, "Sovereign since day one")

    def test_headline_requires_deck(self):
        self.client.force_login(self.other)
        response = post_json(self.client, reverse("api_deck_handle"), {"headline": "sneaky"})
        self.assertEqual(response.status_code, 400)


class DeckReorderTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="did:key:z6Mkordrow")
        self.intruder = User.objects.create_user(username="did:key:z6Mkordinv")
        self.deck = claim_handle(self.owner, "reorder")
        self.foreign_deck = claim_handle(self.intruder, "intruder")
        self.a = UserLinkItem.objects.create(deck=self.deck, title="A", url="https://a.example.com", order=10)
        self.b = UserLinkItem.objects.create(deck=self.deck, title="B", url="https://b.example.com", order=11)
        self.c = UserLinkItem.objects.create(deck=self.deck, title="C", url="https://c.example.com", order=12)
        self.foreign = UserLinkItem.objects.create(deck=self.foreign_deck, title="F", url="https://f.example.com", order=50)

    def _reorder(self, ids):
        self.client.force_login(self.owner)
        return post_json(self.client, reverse("api_deck_reorder"), {"item_ids": ids})

    def test_reorder_persists(self):
        response = self._reorder([self.c.id, self.a.id, self.b.id])
        self.assertTrue(response.json()["ok"])
        orders = {i.title: i.order for i in UserLinkItem.objects.filter(deck=self.deck)}
        self.assertEqual(orders["C"], 0)
        self.assertEqual(orders["A"], 1)
        self.assertEqual(orders["B"], 2)

    def test_reordered_deck_serves_public_order(self):
        self._reorder([self.c.id, self.a.id, self.b.id])
        with patch("apps.core.views.relay_req", return_value={}):
            response = self.client.get("/@reorder")
        body = response.content.decode()
        c_pos = body.find(">C<")
        a_pos = body.find(">A<")
        b_pos = body.find(">B<")
        self.assertLess(c_pos, a_pos)
        self.assertLess(a_pos, b_pos)

    def test_reorder_scoped_to_own_deck(self):
        response = self._reorder([self.b.id, self.foreign.id, self.a.id])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["updated"], 2)
        self.foreign.refresh_from_db()
        self.assertEqual(self.foreign.order, 50)

    def test_reorder_rejects_non_list(self):
        self.client.force_login(self.owner)
        response = post_json(self.client, reverse("api_deck_reorder"), {"item_ids": "not-a-list"})
        self.assertEqual(response.status_code, 400)

    def test_reorder_anonymous_gated(self):
        response = post_json(self.client, reverse("api_deck_reorder"), {"item_ids": [1]})
        self.assertEqual(response.status_code, 302)


class DashboardDeckTabTests(TestCase):
    def test_dashboard_contains_deck_tab_and_script(self):
        user = User.objects.create_user(username="did:key:z6Mkdashtab")
        self.client.force_login(user)
        with patch("apps.core.views.relay_req", return_value={}):
            response = self.client.get(reverse("dashboard"))
        self.assertContains(response, "Link Deck Manager")
        self.assertContains(response, "link_deck_manager.js")
        self.assertContains(response, "deckHandleDisplay")

    def test_deck_items_api_serves_claimed_handle(self):
        user = User.objects.create_user(username="did:key:z6Mkdashban")
        claim_handle(user, "banner")
        self.client.force_login(user)
        response = self.client.get(reverse("api_deck_items"))
        data = response.json()
        self.assertEqual(data["handle"], "banner")
        self.assertEqual(data["canonical_url"], "/@banner")


class ProfileDeckChipsTests(TestCase):
    CHIP_DID_WITH_DECK = "did:key:z6MkhaXgBZDvB9gCHIPS1"
    CHIP_DID_NO_DECK = "did:key:z6MkhaXgBZDvB9gCHIPSO"

    def _profile_url_for(self, user):
        npub = did_to_npub(user.username)
        return reverse("profile", kwargs={"npub": npub})

    def test_profile_shows_active_deck_chips(self):
        user = User.objects.create_user(username=self.CHIP_DID_WITH_DECK)
        deck = claim_handle(user, "chips")
        UserLinkItem.objects.create(deck=deck, title="Chip Target", url="https://chip.example.com", icon_category="github")
        with patch("apps.core.views.relay_req", return_value={}):
            response = self.client.get(self._profile_url_for(user))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Chip Target")

    def test_profile_hides_chips_without_deck(self):
        user = User.objects.create_user(username=self.CHIP_DID_NO_DECK)
        with patch("apps.core.views.relay_req", return_value={}):
            response = self.client.get(self._profile_url_for(user))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Chip Target")


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
        html = f'<html><head></head><body>bio text {self.TOKEN} more</body></html>'.encode()
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


class VerifyChallengeAPITests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="did:key:z6Mkchalown")
        self.deckless = User.objects.create_user(username="did:key:z6Mkchalno")
        claim_handle(self.owner, "bioseeker")

    def _create_challenge(self, handle="testcreator", url="https://github.com/u"):
        return post_json(self.client, reverse("api_deck_verify_challenge"), {
            "target_handle": handle,
            "external_url": url,
        })

    def test_create_challenge_returns_token_and_expiry(self):
        self.client.force_login(self.owner)
        before = timezone.now()
        response = self._create_challenge()
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["token"].startswith("iyou-verify-wun-"))
        suffix = data["token"][len("iyou-verify-wun-"):]
        self.assertEqual(len(suffix), 16)
        expires = timezone.datetime.fromisoformat(data["expires_at"])
        delta = expires - before.replace(microsecond=0)
        self.assertAlmostEqual(delta.total_seconds(), 30 * 60, delta=5)
        self.assertIn("bio", data["instructions"].lower())
        challenge = HandleVerificationChallenge.objects.get(token=data["token"])
        self.assertEqual(challenge.target_handle, "testcreator")
        self.assertFalse(challenge.is_completed)

    def test_requires_deck(self):
        self.client.force_login(self.deckless)
        response = self._create_challenge()
        self.assertEqual(response.status_code, 400)

    def test_anonymous_gated(self):
        response = post_json(self.client, reverse("api_deck_verify_challenge"), {})
        self.assertEqual(response.status_code, 302)

    def test_invalid_target_handle_rejected(self):
        self.client.force_login(self.owner)
        self.assertEqual(self._create_challenge(handle="ab").status_code, 400)
        self.assertEqual(self._create_challenge(handle="Bad Handle").status_code, 400)

    def test_reserved_target_handle_rejected(self):
        self.client.force_login(self.owner)
        response = self._create_challenge(handle="admin")
        self.assertEqual(response.status_code, 400)
        self.assertIn("reserved", response.json()["error"])

    def test_disallowed_external_url_rejected(self):
        self.client.force_login(self.owner)
        response = self._create_challenge(url="https://evil.example.com/bio")
        self.assertEqual(response.status_code, 400)
        self.assertIn("allowlist", response.json()["error"].lower())

    def test_get_method_rejected(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse("api_deck_verify_challenge"))
        self.assertEqual(response.status_code, 405)


class VerifyConfirmSwapTests(TestCase):
    def setUp(self):
        self.user_a = User.objects.create_user(username="did:key:z6Mkswapaaa")
        self.user_b = User.objects.create_user(username="did:key:z6Mkswapbbb")
        self.user_c = User.objects.create_user(username="did:key:z6Mkswapccc")
        claim_handle(self.user_a, "testcreator")
        claim_handle(self.user_b, "testcreator")

    def _challenge_token_for_b(self):
        self.client.force_login(self.user_b)
        response = post_json(self.client, reverse("api_deck_verify_challenge"), {
            "target_handle": "testcreator",
            "external_url": "https://github.com/testcreator",
        })
        self.assertEqual(response.status_code, 200)
        return response.json()["token"]

    def _confirm(self, user, token):
        self.client.force_login(user)
        return post_json(self.client, reverse("api_deck_verify_confirm"), {"token": token})

    @patch("apps.core.views.verify_external_profile_token", return_value=(True, "Token verified successfully"))
    def test_full_swap_promotes_verifier_and_demotes_squatter(self, mock_verify):
        token = self._challenge_token_for_b()
        response = self._confirm(self.user_b, token)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["valid"])
        self.assertEqual(data["handle"], "testcreator")
        self.assertEqual(data["discriminator"], 0)
        self.assertTrue(data["is_verified"])

        deck_a = UserLinkDeck.objects.get(user=self.user_a)
        deck_b = UserLinkDeck.objects.get(user=self.user_b)
        self.assertEqual((deck_b.handle, deck_b.discriminator), ("testcreator", 0))
        self.assertTrue(deck_b.is_verified)
        self.assertEqual(deck_b.verified_source_url, "https://github.com/testcreator")
        self.assertIsNotNone(deck_b.verified_at)
        self.assertEqual(deck_a.discriminator, 2)
        self.assertFalse(deck_a.is_verified)
        challenge = HandleVerificationChallenge.objects.get(token=token)
        self.assertTrue(challenge.is_completed)
        mock_verify.assert_called_once_with("https://github.com/testcreator", token)

    @patch("apps.core.views.verify_external_profile_token", return_value=(True, "ok"))
    def test_swapped_routes_resolve_correctly(self, mock_verify):
        token = self._challenge_token_for_b()
        self._confirm(self.user_b, token)
        with patch("apps.core.views.relay_req", return_value={}):
            canonical = self.client.get("/@testcreator")
            demoted = self.client.get("/@testcreator[2]")
        self.assertEqual(canonical.status_code, 200)
        self.assertContains(canonical, "VERIFIED")
        self.assertEqual(demoted.status_code, 200)
        did_redirect = self.client.get(f"/u/{self.user_b.username}/")
        self.assertEqual(did_redirect["Location"], "/@testcreator")

    @patch("apps.core.views.verify_external_profile_token", return_value=(False, "Token not found in bio content"))
    def test_failed_verification_leaves_handles_intact(self, mock_verify):
        token = self._challenge_token_for_b()
        response = self._confirm(self.user_b, token)
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()["valid"])
        deck_a = UserLinkDeck.objects.get(user=self.user_a)
        deck_b = UserLinkDeck.objects.get(user=self.user_b)
        self.assertEqual((deck_a.handle, deck_a.discriminator), ("testcreator", 0))
        self.assertEqual((deck_b.handle, deck_b.discriminator), ("testcreator", 1))
        self.assertFalse(UserLinkDeck.objects.filter(is_verified=True).exists())
        challenge = HandleVerificationChallenge.objects.get(token=token)
        self.assertFalse(challenge.is_completed)

    def test_expired_challenge_rejected(self):
        token = self._challenge_token_for_b()
        past = timezone.now() - timedelta(minutes=1)
        HandleVerificationChallenge.objects.update(expires_at=past)
        with patch("apps.core.views.verify_external_profile_token") as mock_verify:
            response = self._confirm(self.user_b, token)
        self.assertEqual(response.status_code, 400)
        self.assertIn("expired", response.json()["error"].lower())
        mock_verify.assert_not_called()

    @patch("apps.core.views.verify_external_profile_token", return_value=(True, "ok"))
    def test_completed_challenge_not_reusable(self, mock_verify):
        token = self._challenge_token_for_b()
        self.assertEqual(self._confirm(self.user_b, token).status_code, 200)
        response = self._confirm(self.user_b, token)
        self.assertEqual(response.status_code, 400)
        self.assertIn("completed", response.json()["error"].lower())
        mock_verify.assert_called_once()

    def test_unknown_token_rejected(self):
        response = self._confirm(self.user_b, "iyou-verify-wun-doesnotexist1234")
        self.assertEqual(response.status_code, 404)

    def test_foreign_deck_cannot_confirm_anothers_challenge(self):
        claim_handle(self.user_c, "bystander")
        token = self._challenge_token_for_b()
        response = self._confirm(self.user_c, token)
        self.assertEqual(response.status_code, 404)
        deck_b = UserLinkDeck.objects.get(user=self.user_b)
        self.assertEqual(deck_b.discriminator, 1)

    def test_anonymous_gated(self):
        response = post_json(self.client, reverse("api_deck_verify_confirm"), {"token": "x"})
        self.assertEqual(response.status_code, 302)

    def test_get_method_rejected(self):
        self.client.force_login(self.user_a)
        response = self.client.get(reverse("api_deck_verify_confirm"))
        self.assertEqual(response.status_code, 405)


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

    def test_dashboard_contains_verification_card_and_modal(self):
        user = User.objects.create_user(username="did:key:z6Mkdashvrf")
        claim_handle(user, "dashverify")
        self.client.force_login(user)
        with patch("apps.core.views.relay_req", return_value={}):
            response = self.client.get(reverse("dashboard"))
        self.assertContains(response, "Proof-of-Authority Verification")
        self.assertContains(response, "Verify Profile / Claim Canonical Handle")
        self.assertContains(response, 'id="verifyModal"')
        self.assertContains(response, "link_deck_manager.js")


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
