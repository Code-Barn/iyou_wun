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

"""Tests for the cataloged-but-disabled-by-default relay fleet.

Two things are guarded here:

1. The relay catalog in ``static/js/relay_pool.js`` and the Python-side catalog
   used to render the Switchboard must not drift. The client is the source of
   truth for participation; the server only renders defaults, so a mismatch would
   show a relay as OFF in the UI while the pool dials it, or vice versa.
2. Disabled relays must never leak into a read/write set, an outbox selection, or
   a quality score.
"""

import os
import re

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from apps.core.models import UserLinkDeck
from apps.core.views import (
    DEFAULT_RELAYS,
    PUBLIC_RELAYS,
    READ_ONLY_RELAYS,
    relay_catalog,
)

REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)
RELAY_POOL_JS = os.path.join(REPO_ROOT, "static", "js", "relay_pool.js")


def parse_js_catalog():
    """Extract url/enabled/write triples from buildBootstrapRelays() in the JS."""
    with open(RELAY_POOL_JS, "r", encoding="utf-8") as fh:
        source = fh.read()
    start = source.index("function buildBootstrapRelays()")
    body = source[start : source.index("var BOOTSTRAP_RELAYS", start)]
    entries = []
    pattern = re.compile(
        r'\{\s*url:\s*"(?P<url>[^"]+)"\s*,\s*read:\s*(?P<read>true|false)\s*,'
        r"\s*write:\s*(?P<write>true|false)\s*,\s*isLocal:\s*(?P<local>true|false)"
        r"\s*,\s*primary:\s*(?P<primary>true|false)\s*,\s*enabled:\s*(?P<enabled>true|false)"
    )
    for match in pattern.finditer(body):
        entries.append(
            {
                "url": match.group("url"),
                "read": match.group("read") == "true",
                "write": match.group("write") == "true",
                "enabled": match.group("enabled") == "true",
            }
        )
    return entries


class RelayCatalogParityTests(TestCase):
    """The JS and Python catalogs must describe the same fleet."""

    def test_js_catalog_matches_python_catalog(self):
        js_entries = {e["url"]: e for e in parse_js_catalog()}
        py_entries = {e["url"]: e for e in relay_catalog()}

        self.assertEqual(
            sorted(js_entries), sorted(py_entries),
            "relay catalog drift: JS buildBootstrapRelays() and relay_catalog() "
            "must list the same relay URLs",
        )

    def test_enabled_defaults_match(self):
        js_entries = {e["url"]: e for e in parse_js_catalog()}
        for url, py in ((e["url"], e) for e in relay_catalog()):
            self.assertEqual(
                js_entries[url]["enabled"], py["enabled"],
                "enabled default drifted for %s" % url,
            )

    def test_write_policy_matches(self):
        js_entries = {e["url"]: e for e in parse_js_catalog()}
        for py in relay_catalog():
            self.assertEqual(
                js_entries[py["url"]]["write"], py["write"],
                "write policy drifted for %s" % py["url"],
            )

    def test_sovereign_relays_enabled_public_relays_disabled(self):
        catalog = {e["url"]: e for e in relay_catalog()}
        for url in DEFAULT_RELAYS:
            self.assertTrue(catalog[url]["enabled"], "%s must default to enabled" % url)
            self.assertTrue(catalog[url]["sovereign"])
        for url in PUBLIC_RELAYS:
            self.assertFalse(
                catalog[url]["enabled"],
                "%s is cataloged but must default to disabled" % url,
            )
            self.assertFalse(catalog[url]["sovereign"])

    def test_read_only_relay_is_never_a_write_target(self):
        catalog = {e["url"]: e for e in relay_catalog()}
        for url in READ_ONLY_RELAYS:
            self.assertIn(url, catalog)
            self.assertFalse(catalog[url]["write"], "%s must be read-only" % url)

    def test_catalog_has_no_duplicates(self):
        urls = [e["url"] for e in relay_catalog()]
        self.assertEqual(len(urls), len(set(urls)))


class SeedDevIdentityCommandTests(TestCase):
    """The @dcbyers13 dev seed must be idempotent and must not clobber handles."""

    OTHER_DID = "did:key:z6Mkseedtestowner000000000000000000000000000000000000"
    CONFLICT_DID = "did:key:z6MkujsSdMm1j7QqUNaZo8U8kkcJNfFNikUQYJzmZX4wwgND"

    def test_creates_deck_for_production_did(self):
        call_command("seed_dev_identity", "--did", self.OTHER_DID, verbosity=0)

        deck = UserLinkDeck.objects.get(handle="dcbyers13")
        self.assertEqual(deck.user.username, self.OTHER_DID)
        # Production parity: no synced Nostr key, so resolution falls back to the
        # DID-derived author candidate.
        self.assertEqual(deck.nostr_pubkey, "")

    def test_is_idempotent(self):
        call_command("seed_dev_identity", "--did", self.OTHER_DID, verbosity=0)
        first_pk = UserLinkDeck.objects.get(handle="dcbyers13").pk
        call_command("seed_dev_identity", "--did", self.OTHER_DID, verbosity=0)

        self.assertEqual(UserLinkDeck.objects.filter(handle="dcbyers13").count(), 1)
        self.assertEqual(UserLinkDeck.objects.get(handle="dcbyers13").pk, first_pk)

    def test_refuses_to_rename_a_deck_the_owner_already_has(self):
        """user is one-to-one, so a second handle for the same DID is a rename.

        Renaming silently destroyed a real local handle during development; the
        command must refuse unless --force is passed.
        """
        user = get_user_model().objects.create_user(username=self.CONFLICT_DID, password=None)
        existing = UserLinkDeck.objects.create(
            user=user, handle="primary_identity_9e7db757", nostr_pubkey="a" * 64
        )

        with self.assertRaises(CommandError):
            call_command("seed_dev_identity", "--did", self.CONFLICT_DID, verbosity=0)

        existing.refresh_from_db()
        self.assertEqual(existing.handle, "primary_identity_9e7db757")
        self.assertEqual(existing.nostr_pubkey, "a" * 64)

    def test_force_reassigns_the_handle(self):
        user = get_user_model().objects.create_user(username=self.CONFLICT_DID, password=None)
        UserLinkDeck.objects.create(user=user, handle="primary_identity_9e7db757")

        call_command(
            "seed_dev_identity", "--did", self.CONFLICT_DID, "--force", verbosity=0
        )

        self.assertTrue(UserLinkDeck.objects.filter(handle="dcbyers13").exists())
        self.assertFalse(UserLinkDeck.objects.filter(handle="primary_identity_9e7db757").exists())

    def test_rejects_malformed_nostr_pubkey(self):
        with self.assertRaises(CommandError):
            call_command(
                "seed_dev_identity",
                "--did",
                self.OTHER_DID,
                "--nostr-pubkey",
                "abc",
                verbosity=0,
            )
        self.assertFalse(UserLinkDeck.objects.filter(handle="dcbyers13").exists())

    def test_seeded_handle_resolves_through_the_profile_resolver(self):
        call_command("seed_dev_identity", "--did", self.OTHER_DID, verbosity=0)

        from apps.core.views import _resolve_profile_candidates

        carried, _user, owner_deck, hex_pubkey, candidates = _resolve_profile_candidates(
            "dcbyers13"
        )

        self.assertEqual(carried, "handle")
        self.assertIsNotNone(owner_deck)
        # Inclusive resolution: the DID-derived author candidate keeps the
        # enclave-transition notes reachable for a keyless deck.
        self.assertTrue(candidates)
        self.assertEqual(hex_pubkey, candidates[0])


class DisabledRelayIsolationTests(TestCase):
    """A disabled relay must not participate anywhere."""

    def test_disabled_defaults_do_not_leak_into_read_or_write_sets(self):
        """The rendered defaults keep public relays out of the active fleet."""
        active = [e["url"] for e in relay_catalog() if e["enabled"]]

        for url in PUBLIC_RELAYS:
            self.assertNotIn(url, active)

    def test_js_getters_filter_disabled_records(self):
        """getRelays/getReadRelays/getWriteRelays all skip enabled === false."""
        with open(RELAY_POOL_JS, "r", encoding="utf-8") as fh:
            source = fh.read()

        for getter in ("getRelays", "getReadRelays", "getWriteRelays"):
            start = source.index("RelayPool.prototype.%s = function" % getter)
            body = source[start : source.index("};", start)]
            self.assertIn(
                "r.enabled === false", body,
                "%s must skip disabled relays" % getter,
            )

    def test_quality_score_is_zero_for_disabled_relay(self):
        with open(RELAY_POOL_JS, "r", encoding="utf-8") as fh:
            source = fh.read()

        start = source.index("RelayPool.prototype.getRelayQuality = function")
        body = source[start : source.index("};", start)]

        self.assertIn("record.enabled === false", body)
        # A disabled relay must be rejected before the `primary` shortcut, or a
        # disabled primary would still claim top-tier outbox weight.
        self.assertLess(
            body.index("record.enabled === false"), body.index("record.primary")
        )

    def test_outbox_padding_respects_disabled_state(self):
        """The MIN_RELAY_FLOOR padding must not re-add a disabled catalog entry."""
        with open(RELAY_POOL_JS, "r", encoding="utf-8") as fh:
            source = fh.read()

        start = source.index("RelayPool.prototype.selectRelaysForAuthors = function")
        body = source[start : source.index("return picked;", start)]

        self.assertIn("BOOTSTRAP_RELAYS.forEach", body)
        self.assertIn("getRelayQuality(r.url) <= 0", body)

    def test_disabled_relay_is_never_probed(self):
        """probeRelay() short-circuits before touching the network."""
        with open(RELAY_POOL_JS, "r", encoding="utf-8") as fh:
            source = fh.read()

        start = source.index("RelayPool.prototype.probeRelay = function")
        body = source[start : source.index("RelayPool.prototype.", start + 10)]

        self.assertIn(
            "if (record.enabled === false)", body,
            "probeRelay must skip disabled relays before dialling them",
        )

    def test_disabled_relay_blocks_read_write_and_connect(self):
        with open(RELAY_POOL_JS, "r", encoding="utf-8") as fh:
            source = fh.read()

        # getRelays / getReadRelays / getWriteRelays each skip disabled records.
        self.assertGreaterEqual(source.count("if (r.enabled === false) return;"), 3)
        # getRelayQuality scores a disabled relay 0.
        self.assertIn("if (!record || record.enabled === false) return 0;", source)
        # The connect path bails on a disabled relay.
        self.assertIn("if (record && record.enabled === false) return;", source)
        # Reconnect scheduling is suppressed for disabled relays.
        self.assertIn("if (rec && rec.enabled !== false)", source)

    def test_probing_disabled_relay_does_not_flip_it_online(self):
        """The periodic probe must not resurrect a relay the user switched off."""
        with open(RELAY_POOL_JS, "r", encoding="utf-8") as fh:
            source = fh.read()

        start = source.index("if (record.enabled === false) {")
        body = source[start : source.index("}", start)]

        self.assertIn('record.status = "offline"', body)

    def test_toggle_persists_when_turning_a_disabled_relay_on(self):
        """Regression: the enabled-diff must survive `enabled === false`.

        The change detector used to read `(record.enabled || true) !== next`.
        For a cataloged public relay `enabled` is `false`, so `false || true`
        collapsed back to `true` and the diff came out `false` -- the toggle
        took effect in memory but persistRelays() was never called, so the
        preference was silently dropped and reverted on reload.
        """
        with open(RELAY_POOL_JS, "r", encoding="utf-8") as fh:
            source = fh.read()

        start = source.index("RelayPool.prototype.toggleRelayState = function")
        body = source[start : source.index("RelayPool.prototype.", start + 10)]

        self.assertIn("record.enabled !== false) !== nextEnabled", body)
        self.assertNotIn("record.enabled || true) !== nextEnabled", body)
        # The diff must still gate persistence and the UI refresh.
        self.assertIn("if (changed) {", body)
        self.assertIn("this.persistRelays();", body)

    def test_dashboard_prefers_only_explicit_boolean_preferences(self):
        """Switchboard hydration must agree with _initPool()'s enabledMap.

        Reading a legacy bare-string entry as "on" would re-enable a
        disabled-by-default public relay on the next page load, so the
        dashboard and the pool have to apply the identical rule.
        """
        with open(
            os.path.join(REPO_ROOT, "templates", "dashboard.html"), "r", encoding="utf-8"
        ) as fh:
            source = fh.read()

        start = source.index("function readStoredPreferences()")
        body = source[start : source.index("function findRelayEntry", start)]

        self.assertIn("typeof entry.enabled === \"boolean\"", body)
        self.assertNotIn(
            "typeof entry === \"string\") {", body,
            "a bare-string entry must not be read as an enabled preference",
        )
