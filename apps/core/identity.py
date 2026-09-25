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

"""Canonical Identity Translation Service for the iyou node.

Maps Nostr pubkey hexes onto the node's registered UserLinkDeck identities and
defines the strict cryptographic membership set for the [ ⚡ iyou ] circle:
a note belongs to the ecosystem iff its author pubkey is a registered local
User account (DID-derived or raw hex). Hashtags never grant membership.
"""

import re

from django.core.cache import cache
from django.db import connections

from .did_kit import did_to_pubkey_hex
from .models import UserLinkDeck

CACHE_KEY_ECOSYSTEM_PUBKEYS = "wun_ecosystem_pubkeys_set"
CACHE_KEY_IDENTITY_PREFIX = "wun_id_resolve_"
CACHE_TTL = 300

_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")


def _cache_active() -> bool:
    """Whether process-level identity caching is safe.

    Django's test runner reuses one locmem cache across test transactions, so
    caching DB-derived membership/identity here would leak stale state between
    tests. The runner renames the *connection* database (``test_*``, or an
    in-memory ``file:memorydb_*`` for SQLite) — detect that to bypass the cache
    in test suites.
    """
    db_name = (connections["default"].settings_dict or {}).get("NAME") or ""
    return not (
        str(db_name).startswith("test_")
        or str(db_name).startswith("file:memorydb")
        or str(db_name) == ":memory:"
    )


def _cache_get(key):
    if not _cache_active():
        return None
    return cache.get(key)


def _cache_set(key, value):
    if _cache_active():
        cache.set(key, value, CACHE_TTL)


def _cache_delete(key):
    if _cache_active():
        cache.delete(key)


def get_ecosystem_pubkeys(force_refresh=False) -> set:
    """Return the cached set of ecosystem pubkey hexes for this node.

    Membership is computed purely from registered local auth accounts
    (``User.username``) resolved through :func:`did_to_pubkey_hex`, so the
    iyou circle is cryptographically scoped to this node's own users.
    """
    if not force_refresh:
        cached = _cache_get(CACHE_KEY_ECOSYSTEM_PUBKEYS)
        if cached is not None:
            return set(cached)
    keys = set()
    try:
        from django.contrib.auth import get_user_model

        usernames = (
            get_user_model()
            .objects.exclude(username__isnull=True)
            .exclude(username="")
            .values_list("username", flat=True)
        )
        for username in usernames:
            pk = did_to_pubkey_hex(username)
            if pk:
                keys.add(pk.lower())
    except Exception:
        keys = set()
    _cache_set(CACHE_KEY_ECOSYSTEM_PUBKEYS, keys)
    return keys


def invalidate_ecosystem_cache() -> None:
    """Drop the cached ecosystem membership set (call after account changes)."""
    _cache_delete(CACHE_KEY_ECOSYSTEM_PUBKEYS)


def invalidate_author_identity(pubkey_hex) -> None:
    """Drop the cached Identity Translation Service entry for one pubkey."""
    pk = (pubkey_hex or "").strip().lower()
    if pk:
        _cache_delete(f"{CACHE_KEY_IDENTITY_PREFIX}{pk}")


def _deck_for_pubkey(pk):
    """Resolve the UserLinkDeck backing a pubkey via DID/hex/nostr_pubkey."""
    candidates = [pk, f"did:iyou:0x{pk}"]
    deck = UserLinkDeck.objects.filter(user__username__in=candidates).first()
    if deck is None:
        deck = UserLinkDeck.objects.filter(nostr_pubkey=pk).first()
    if deck is None:
        for d in (
            UserLinkDeck.objects.filter(nostr_pubkey="")
            .select_related("user")
            .iterator()
        ):
            if did_to_pubkey_hex(d.user.username) == pk:
                deck = d
                break
    return deck


def resolve_author_identity(pubkey_hex) -> dict:
    """Resolve the canonical deck-backed identity for a Nostr pubkey hex.

    Returns ``{"display_name", "handle", "avatar_url", "is_member", "did"}``.
    ``is_member`` reflects strict ecosystem membership, so it is consistent
    with the [ ⚡ iyou ] circle filter. Results are cached per pubkey.
    """
    pk = (pubkey_hex or "").strip().lower()
    if not _HEX64_RE.fullmatch(pk):
        return {"display_name": "", "handle": "", "avatar_url": "", "is_member": False, "did": ""}

    cache_key = f"{CACHE_KEY_IDENTITY_PREFIX}{pk}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    identity = {
        "display_name": "",
        "handle": "",
        "avatar_url": "",
        "is_member": pk in get_ecosystem_pubkeys(),
        "did": "",
    }
    deck = _deck_for_pubkey(pk)
    if deck is not None:
        identity.update({
            "display_name": deck.display_name or "",
            "handle": deck.handle or "",
            "avatar_url": deck.avatar_url or "",
            "did": deck.user.username or "",
        })
    _cache_set(cache_key, identity)
    return identity


def npub_short(pubkey_hex, length: int = 8) -> str:
    """Short display prefix for a pubkey hex (``3bf0c63f...``)."""
    pk = (pubkey_hex or "").strip().lower()
    if len(pk) > length:
        return f"{pk[:length]}…"
    return pk


def decorate_author_identity(note: dict) -> dict:
    """Attach canonical identity keys to a note dict (mutating, returns note).

    Sets ``author_display_name``, ``author_handle``, ``is_ecosystem_member``,
    ``author_avatar`` and ``author_url`` so every card (root, reply, quoted,
    hero, ancestor) renders the node's registered identity.
    """
    pk = (note.get("pubkey") or "").strip().lower()
    identity = resolve_author_identity(pk)
    existing_name = note.get("author_name") or ""
    note["author_display_name"] = identity["display_name"] or existing_name or npub_short(pk)
    note["author_handle"] = identity["handle"] or ""
    note["is_ecosystem_member"] = identity["is_member"]
    note["author_avatar"] = identity["avatar_url"] or note.get("author_avatar") or ""
    if identity["handle"]:
        note["author_url"] = f"/@{identity['handle']}/"
    else:
        npub = note.get("npub") or ""
        note["author_url"] = f"/profile/{npub}/" if npub else ""
    return note