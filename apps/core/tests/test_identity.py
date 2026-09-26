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

"""Tests for the canonical Identity Translation Service (``apps.core.identity``).

Covers the aliasing rule that lets one registered account resolve through both
its enclave-synced ``nostr_pubkey`` and its DID-derived signing key, and the
``display_name`` fallback that keeps feed cards aligned with ``ProfileView``.
"""

import json
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from apps.core.did_kit import b58encode
from apps.core.identity import (
    CACHE_KEY_ECOSYSTEM_PUBKEYS,
    CACHE_KEY_IDENTITY_PREFIX,
    decorate_author_identity,
    get_ecosystem_pubkeys,
    resolve_author_identity,
)
from apps.core.models import UserLinkDeck
from apps.core.views import _find_user_by_pubkey, hex_to_npub

# DID-derived signing key for `did:key:z6MkujsSdMm1j7QqUNaZo8U8kkcJNfFNikUQYJzmZX4wwgND`,
# the account that regressed to a raw npub in feed cards.
DID_DERIVED_PUBKEY = "e3209edcf5b8f82aa6db74747585f1ae642f9a2e5eb73b9a69697c051a23d97a"
DID_DERIVED_DID = (
    "did:key:z" + b58encode(bytes([0xED, 0x01]) + bytes.fromhex(DID_DERIVED_PUBKEY))
)
# A *different* key the enclave bridge synced onto the same deck.
ENCLAVE_PUBKEY = "4072dc50d7c58ce839e8bbcd842b2357efc8634e538c19eb82e9e0e650e051d5"

assert DID_DERIVED_DID == "did:key:z6MkujsSdMm1j7QqUNaZo8U8kkcJNfFNikUQYJzmZX4wwgND"


def make_user_with_deck(username, handle, display_name="", nostr_pubkey=""):
    user = User.objects.create_user(username=username)
    user.set_unusable_password()
    user.save()
    deck = UserLinkDeck.objects.create(
        user=user,
        handle=handle,
        display_name=display_name,
        nostr_pubkey=nostr_pubkey,
    )
    return user, deck


class ResolveAuthorIdentityTests(TestCase):
    def test_blank_display_name_falls_back_to_handle(self):
        _, deck = make_user_with_deck(
            DID_DERIVED_DID, "primary_identity_9e7db757", display_name="", nostr_pubkey=ENCLAVE_PUBKEY
        )

        identity = resolve_author_identity(DID_DERIVED_PUBKEY)

        # Mirrors ProfileView's `display_name or handle` name resolution
        # (apps/core/views.py) so a card and a profile agree.
        self.assertEqual(identity["display_name"], deck.handle)
        self.assertEqual(identity["display_name"], "primary_identity_9e7db757")
        self.assertEqual(identity["handle"], "primary_identity_9e7db757")
        self.assertEqual(identity["did"], DID_DERIVED_DID)

    def test_explicit_display_name_wins_over_handle(self):
        _, deck = make_user_with_deck(
            DID_DERIVED_DID, "primary_identity_9e7db757", display_name="Zork", nostr_pubkey=ENCLAVE_PUBKEY
        )

        identity = resolve_author_identity(DID_DERIVED_PUBKEY)

        self.assertEqual(identity["display_name"], "Zork")
        self.assertEqual(identity["display_name"], deck.display_name)
        self.assertEqual(identity["handle"], "primary_identity_9e7db757")

    def test_did_derived_key_resolves_despite_differing_enclave_pubkey(self):
        """The regression: deck.nostr_pubkey is non-blank, so the old
        blank-only scan skipped it and cards fell back to a raw npub."""
        _, deck = make_user_with_deck(
            DID_DERIVED_DID, "primary_identity_9e7db757", nostr_pubkey=ENCLAVE_PUBKEY
        )
        self.assertNotEqual(deck.nostr_pubkey, DID_DERIVED_PUBKEY)

        identity = resolve_author_identity(DID_DERIVED_PUBKEY)

        self.assertEqual(identity["did"], DID_DERIVED_DID)
        self.assertEqual(identity["display_name"], "primary_identity_9e7db757")

    def test_enclave_pubkey_still_resolves_to_same_deck(self):
        make_user_with_deck(DID_DERIVED_DID, "primary_identity_9e7db757", nostr_pubkey=ENCLAVE_PUBKEY)

        for pk in (DID_DERIVED_PUBKEY, ENCLAVE_PUBKEY):
            with self.subTest(pubkey=pk):
                self.assertEqual(resolve_author_identity(pk)["did"], DID_DERIVED_DID)

    def test_ecosystem_membership_follows_did_derived_key(self):
        make_user_with_deck(DID_DERIVED_DID, "primary_identity_9e7db757", nostr_pubkey=ENCLAVE_PUBKEY)

        self.assertIn(DID_DERIVED_PUBKEY, get_ecosystem_pubkeys(force_refresh=True))
        self.assertTrue(resolve_author_identity(DID_DERIVED_PUBKEY)["is_member"])

    def test_unknown_pubkey_stays_blank(self):
        identity = resolve_author_identity("ab" * 32)
        self.assertEqual(identity["display_name"], "")
        self.assertEqual(identity["handle"], "")
        self.assertFalse(identity["is_member"])

    def test_non_hex_input_is_rejected(self):
        identity = resolve_author_identity("npub1uvsfah84hruz4fkmw368tp034ejzlx3wt6mnhxnfd97q2x3rm9aqud8wpk")
        self.assertEqual(identity["display_name"], "")
        self.assertEqual(identity["did"], "")


class DecorateAuthorIdentityTests(TestCase):
    def _note(self, pubkey):
        return {
            "id": "e" * 64,
            "kind": 1,
            "pubkey": pubkey,
            "pubkey_hex": pubkey,
            "npub": hex_to_npub(pubkey),
            "author_name": "",
            "content": "zork",
        }

    def test_note_signed_by_did_key_renders_handle_not_npub(self):
        make_user_with_deck(DID_DERIVED_DID, "primary_identity_9e7db757", nostr_pubkey=ENCLAVE_PUBKEY)

        note = decorate_author_identity(self._note(DID_DERIVED_PUBKEY))

        self.assertEqual(note["author_display_name"], "primary_identity_9e7db757")
        self.assertEqual(note["author_handle"], "primary_identity_9e7db757")
        self.assertEqual(note["author_url"], "/@primary_identity_9e7db757/")
        self.assertNotIn("npub1", note["author_display_name"])

    def test_unknown_author_falls_back_to_short_hex_not_npub(self):
        note = decorate_author_identity(self._note("cd" * 32))

        self.assertEqual(note["author_display_name"], "cdcdcdcd…")
        self.assertEqual(note["author_handle"], "")
        self.assertTrue(note["author_url"].startswith("/profile/npub1"))

    def test_relay_kind0_name_is_used_when_no_deck_matches(self):
        note = self._note("cd" * 32)
        note["author_name"] = "Zork Sifter"
        note = decorate_author_identity(note)

        self.assertEqual(note["author_display_name"], "Zork Sifter")

    def test_registered_deck_name_overrides_relay_kind0_name(self):
        make_user_with_deck(DID_DERIVED_DID, "primary_identity_9e7db757", display_name="Zork", nostr_pubkey=ENCLAVE_PUBKEY)
        note = self._note(DID_DERIVED_PUBKEY)
        note["author_name"] = "Impostor Relay Name"

        note = decorate_author_identity(note)

        self.assertEqual(note["author_display_name"], "Zork")


class SyncKeysCacheInvalidationTests(TestCase):
    """api_sync_keys must not leave a 300s-stale identity for the old key."""

    def setUp(self):
        self.user, self.deck = make_user_with_deck(
            DID_DERIVED_DID, "primary_identity_9e7db757", nostr_pubkey=ENCLAVE_PUBKEY
        )
        self.client.force_login(self.user)

    def _sync(self, pubkey):
        return self.client.post(
            reverse("api_sync_keys"),
            data=json.dumps({"nostr_pubkey_hex": pubkey}),
            content_type="application/json",
        )

    def test_sync_keys_clears_old_and_new_identity_entries(self):
        superseded = "aa" * 32
        self.deck.nostr_pubkey = superseded
        self.deck.save(update_fields=["nostr_pubkey"])

        with patch("apps.core.identity._cache_active", return_value=True):
            # Warm: superseded key resolves to this deck, ecosystem is cached.
            self.assertEqual(resolve_author_identity(superseded)["did"], DID_DERIVED_DID)
            get_ecosystem_pubkeys(force_refresh=True)
            self.assertIsNotNone(cache.get(f"{CACHE_KEY_IDENTITY_PREFIX}{superseded}"))
            self.assertIsNotNone(cache.get(CACHE_KEY_ECOSYSTEM_PUBKEYS))

            response = self._sync(ENCLAVE_PUBKEY)
            self.assertEqual(response.status_code, 200)

            self.assertIsNone(cache.get(f"{CACHE_KEY_IDENTITY_PREFIX}{superseded}"))
            self.assertIsNone(cache.get(f"{CACHE_KEY_IDENTITY_PREFIX}{ENCLAVE_PUBKEY}"))
            self.assertIsNone(cache.get(CACHE_KEY_ECOSYSTEM_PUBKEYS))

    def test_sync_keys_clears_find_user_by_pubkey_memo(self):
        self.assertEqual(_find_user_by_pubkey(ENCLAVE_PUBKEY).username, DID_DERIVED_DID)
        self.assertTrue(_find_user_by_pubkey._cache)

        self._sync(ENCLAVE_PUBKEY)

        self.assertEqual(_find_user_by_pubkey._cache, {})
        # Re-resolves from the DB, not from a memoized stale entry.
        self.assertEqual(_find_user_by_pubkey(DID_DERIVED_PUBKEY).username, DID_DERIVED_DID)

    def test_unchanged_key_still_invalidates_its_own_entry(self):
        with patch("apps.core.identity._cache_active", return_value=True):
            resolve_author_identity(ENCLAVE_PUBKEY)
            self.assertIsNotNone(cache.get(f"{CACHE_KEY_IDENTITY_PREFIX}{ENCLAVE_PUBKEY}"))

            self._sync(ENCLAVE_PUBKEY)

            self.assertIsNone(cache.get(f"{CACHE_KEY_IDENTITY_PREFIX}{ENCLAVE_PUBKEY}"))

    def test_rejects_non_hex_pubkey_without_touching_deck(self):
        response = self._sync("not-a-pubkey")

        self.assertEqual(response.status_code, 400)
        self.deck.refresh_from_db()
        self.assertEqual(self.deck.nostr_pubkey, ENCLAVE_PUBKEY)


class PolymorphicProfileIdentifierTests(TestCase):
    """``/profile/<identifier>/`` must accept a claimed Link Deck handle.

    resolve_universal_identifier() only understands npub1..., 64-char hex and
    "@"-bearing NIP-05, so a bare handle like ``dcbyers13`` fell through every
    branch and rendered "Peer Not Found on Mesh" for a peer that is registered
    in our own database.
    """

    HEX_A = "a" * 64
    HEX_B = "b" * 64

    def _user(self, username="did:key:z6MkhFNrAUrHnkQ2S2t4LrPQqT7jV2mR9dYcXbN3qW5eK"):
        from django.contrib.auth import get_user_model

        return get_user_model().objects.create_user(username=username, password=None)

    def _deck(self, username, handle, **kwargs):
        from apps.core.models import UserLinkDeck

        return UserLinkDeck.objects.create(
            user=self._user(username), handle=handle, **kwargs
        )

    def _resolve(self, identifier):
        from apps.core.views import _resolve_profile_candidates

        return _resolve_profile_candidates(identifier)

    def test_handle_resolves_to_deck_and_nostr_pubkey(self):
        deck = self._deck("did:key:zA", "dcbyers13", nostr_pubkey=self.HEX_A)

        carried, _user, owner_deck, hex_pubkey, candidates = self._resolve("dcbyers13")

        self.assertEqual(carried, "handle")
        self.assertEqual(owner_deck.pk, deck.pk)
        self.assertEqual(hex_pubkey, self.HEX_A)
        self.assertIn(self.HEX_A, candidates)

    def test_handle_lookup_is_case_insensitive(self):
        deck = self._deck("did:key:zB", "dcbyers13", nostr_pubkey=self.HEX_A)

        _carried, _user, owner_deck, hex_pubkey, _c = self._resolve("DCByers13")

        self.assertEqual(owner_deck.pk, deck.pk)
        self.assertEqual(hex_pubkey, self.HEX_A)

    def test_enclave_synced_npub_handle_key_decodes_to_hex(self):
        from apps.core.views import hex_to_npub

        self._deck("did:key:zC", "npubholder", nostr_pubkey=hex_to_npub(self.HEX_B))

        _carried, _user, _deck, hex_pubkey, candidates = self._resolve("npubholder")

        self.assertEqual(hex_pubkey, self.HEX_B)
        self.assertIn(self.HEX_B, candidates)

    def test_handle_without_nostr_key_falls_back_to_did_derived_key(self):
        from apps.core.did_kit import did_to_pubkey

        user = self._user("did:iyou:0x" + "c" * 64)
        from apps.core.models import UserLinkDeck

        UserLinkDeck.objects.create(user=user, handle="deckonly", nostr_pubkey="")

        _carried, owner_user, _deck, hex_pubkey, _c = self._resolve("deckonly")

        self.assertEqual(owner_user.pk, user.pk)
        self.assertEqual(hex_pubkey, did_to_pubkey(user.username))

    def test_handle_with_no_key_at_all_still_returns_the_deck(self):
        """A deck that has never linked a key is still a real sovereign identity.

        hex_pubkey is empty here -- the username is not a DID and the deck has no
        nostr_pubkey -- so the caller must key off owner_deck rather than
        reporting the peer as absent from the mesh.
        """
        deck = self._deck("plain_unresolvable_username", "keyless", nostr_pubkey="")

        carried, _user, owner_deck, hex_pubkey, _c = self._resolve("keyless")

        self.assertEqual(carried, "handle")
        self.assertEqual(owner_deck.pk, deck.pk)
        self.assertEqual(hex_pubkey, "")

    def test_duplicate_handle_prefers_lowest_discriminator(self):
        user = self._user("did:iyou:0x" + "e" * 64)
        from apps.core.models import UserLinkDeck

        base = UserLinkDeck.objects.create(
            user=user, handle="reclaimed", discriminator=0, nostr_pubkey=self.HEX_A
        )
        UserLinkDeck.objects.create(
            user=self._user("did:iyou:0x" + "f" * 64),
            handle="reclaimed",
            discriminator=1,
            nostr_pubkey=self.HEX_B,
        )

        _carried, _user, owner_deck, hex_pubkey, _c = self._resolve("reclaimed")

        self.assertEqual(owner_deck.pk, base.pk)
        self.assertEqual(hex_pubkey, self.HEX_A)

    def test_unknown_handle_resolves_to_nothing(self):
        self._deck("did:iyou:0x" + "1" * 64, "someoneelse", nostr_pubkey=self.HEX_A)

        carried, owner_user, owner_deck, hex_pubkey, _c = self._resolve("ghost")

        self.assertEqual(carried, "")
        self.assertIsNone(owner_deck)
        self.assertEqual(hex_pubkey, "")

    def test_nip05_is_not_shadowed_by_handle_lookup(self):
        """A NIP-05 still goes to the universal resolver, never the local index."""
        from apps.core.views import resolve_universal_identifier

        self._deck("did:iyou:0x" + "2" * 64, "alice", nostr_pubkey=self.HEX_A)

        pubkey, carried = resolve_universal_identifier("alice@elsewhere.example")

        self.assertIsNone(pubkey)
        self.assertIsNone(carried)

    def test_hex_identifier_is_not_treated_as_a_handle(self):
        from apps.core.models import UserLinkDeck

        UserLinkDeck.objects.create(
            user=self._user("did:iyou:0x" + "3" * 64),
            handle=self.HEX_A[:32],
            nostr_pubkey=self.HEX_A,
        )

        carried, _user, _deck, hex_pubkey, _c = self._resolve(self.HEX_A)

        self.assertEqual(carried, "hex")
        self.assertEqual(hex_pubkey, self.HEX_A)
