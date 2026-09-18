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

import logging
import urllib.error
import urllib.request
from typing import Any

from django.core.cache import cache

from .models import NodeBlockedEntity, NodeContentTakedown

logger = logging.getLogger(__name__)

CACHE_KEY_BLOCKED_ENTITIES = "wun_shield_blocked_entities"
CACHE_KEY_BLOCKED_EVENTS = "wun_shield_blocked_events"
CACHE_KEY_BLOCKED_MEDIA = "wun_shield_blocked_media"
CACHE_TIMEOUT = 300  # 5 minutes


class ShieldRosters(tuple):
    """
    Named collection of active suppression sets.
    Supports tuple unpacking, attribute access, and dictionary-style access.
    """

    def __new__(cls, blocked_entities: set[str], blocked_events: set[str], blocked_media: set[str]):
        return super().__new__(cls, (blocked_entities, blocked_events, blocked_media))

    @property
    def blocked_entities(self) -> set[str]:
        return self[0]

    @property
    def blocked_events(self) -> set[str]:
        return self[1]

    @property
    def blocked_media(self) -> set[str]:
        return self[2]

    def __getitem__(self, key: Any) -> Any:
        if isinstance(key, str):
            if key == "blocked_entities":
                return self[0]
            if key == "blocked_events":
                return self[1]
            if key == "blocked_media":
                return self[2]
            raise KeyError(key)
        return tuple.__getitem__(self, key)

    def get(self, key: str, default: Any = None) -> Any:
        try:
            return self[key]
        except KeyError:
            return default


def get_blocked_entities() -> set[str]:
    """Retrieve active blocked entity identifiers (pubkey hex, DIDs) as an $O(1)$ lookup set."""
    cached = cache.get(CACHE_KEY_BLOCKED_ENTITIES)
    if cached is not None:
        return cached

    entities: set[str] = set()
    qs = NodeBlockedEntity.objects.filter(is_active=True).values_list("entity_identifier", flat=True)
    for identifier in qs:
        if identifier:
            clean = str(identifier).strip()
            entities.add(clean)
            entities.add(clean.lower())

    cache.set(CACHE_KEY_BLOCKED_ENTITIES, entities, CACHE_TIMEOUT)
    return entities


def get_blocked_events() -> set[str]:
    """Retrieve active takedown event IDs as an $O(1)$ lookup set."""
    cached = cache.get(CACHE_KEY_BLOCKED_EVENTS)
    if cached is not None:
        return cached

    events: set[str] = set()
    qs = (
        NodeContentTakedown.objects.filter(event_id__isnull=False)
        .exclude(event_id="")
        .values_list("event_id", flat=True)
    )
    for event_id in qs:
        if event_id:
            clean = str(event_id).strip()
            events.add(clean)
            events.add(clean.lower())

    cache.set(CACHE_KEY_BLOCKED_EVENTS, events, CACHE_TIMEOUT)
    return events


def get_blocked_media() -> set[str]:
    """Retrieve active takedown media hashes (SHA-256) as an $O(1)$ lookup set."""
    cached = cache.get(CACHE_KEY_BLOCKED_MEDIA)
    if cached is not None:
        return cached

    media: set[str] = set()
    qs = (
        NodeContentTakedown.objects.filter(media_hash__isnull=False)
        .exclude(media_hash="")
        .values_list("media_hash", flat=True)
    )
    for media_hash in qs:
        if media_hash:
            clean = str(media_hash).strip()
            media.add(clean)
            media.add(clean.lower())

    cache.set(CACHE_KEY_BLOCKED_MEDIA, media, CACHE_TIMEOUT)
    return media


def get_shield_rosters() -> ShieldRosters:
    """
    Return all active moderation shield rosters as a cached tuple of sets:
    (blocked_entities, blocked_events, blocked_media).
    """
    return ShieldRosters(
        blocked_entities=get_blocked_entities(),
        blocked_events=get_blocked_events(),
        blocked_media=get_blocked_media(),
    )


def invalidate_shield_cache() -> None:
    """Invalidate all cached moderation shield rosters."""
    for key in (
        CACHE_KEY_BLOCKED_ENTITIES,
        CACHE_KEY_BLOCKED_EVENTS,
        CACHE_KEY_BLOCKED_MEDIA,
    ):
        cache.delete(key)
    logger.debug("Moderation shield cache invalidated.")


def purge_blossom_blob(
    sha256_hex: str,
    blossom_host: str = "http://127.0.0.1:9002",
) -> bool:
    """
    Issue an HTTP DELETE to the local Blossom media daemon at http://127.0.0.1:9002/<sha256_hex>.

    Performs local binary purging to shield the node operator from statutory liability.
    HTTP 404 (already scrubbed / absent) is handled gracefully as a success condition.
    Catches network/HTTP errors without raising unhandled exceptions.
    """
    clean_hash = (sha256_hex or "").strip().lower()
    if not clean_hash:
        logger.warning("purge_blossom_blob called with empty sha256_hex")
        return False

    url = f"{blossom_host.rstrip('/')}/{clean_hash}"
    req = urllib.request.Request(url, method="DELETE")
    req.add_header("User-Agent", "iyou-wun-moderation-shield/1.0")

    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            status = getattr(resp, "status", 200)
            logger.info("Successfully purged Blossom blob %s (status %s)", clean_hash, status)
            return True
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            logger.info("Blossom blob %s already scrubbed / absent (404)", clean_hash)
            return True
        logger.error("HTTP error purging Blossom blob %s from %s: %s", clean_hash, blossom_host, exc)
        return False
    except urllib.error.URLError as exc:
        logger.error("Connection error purging Blossom blob %s from %s: %s", clean_hash, blossom_host, exc)
        return False
    except Exception as exc:
        logger.error("Unexpected error purging Blossom blob %s from %s: %s", clean_hash, blossom_host, exc)
        return False


def is_event_shielded(
    event: dict,
    rosters: ShieldRosters | tuple[set[str], set[str], set[str]] | None = None,
) -> bool:
    """
    Check if a single event matches any active moderation shield rule.
    Returns True if the event should be suppressed/withheld, False otherwise.
    """
    if not isinstance(event, dict):
        return False

    if rosters is None:
        rosters = get_shield_rosters()

    blocked_entities, blocked_events, blocked_media = rosters

    # 1. Author pubkey / DID match
    pubkey = event.get("pubkey")
    if pubkey:
        str_pk = str(pubkey).strip()
        if str_pk in blocked_entities or str_pk.lower() in blocked_entities:
            return True

    author_did = event.get("author_did") or event.get("did")
    if author_did:
        str_did = str(author_did).strip()
        if str_did in blocked_entities or str_did.lower() in blocked_entities:
            return True

    # 2. Event ID match
    event_id = event.get("id")
    if event_id:
        str_id = str(event_id).strip()
        if str_id in blocked_events or str_id.lower() in blocked_events:
            return True

    # 3. Media tag match (["x", hash] or ["ox", hash])
    tags = event.get("tags")
    if tags and isinstance(tags, (list, tuple)) and blocked_media:
        for tag in tags:
            if isinstance(tag, (list, tuple)) and len(tag) >= 2:
                if tag[0] in ("x", "ox"):
                    media_val = str(tag[1]).strip()
                    if media_val in blocked_media or media_val.lower() in blocked_media:
                        return True

    return False


def filter_shielded_events(
    raw_events: list[dict],
    rosters: ShieldRosters | tuple[set[str], set[str], set[str]] | None = None,
) -> list[dict]:
    """
    Filter raw Nostr events against active moderation shield rosters.

    - Strips any event whose pubkey matches blocked_entities.
    - Strips any event whose id matches blocked_events.
    - Strips any event with tags ["x", hash] or ["ox", hash] matching blocked_media.
    - Preserves all other events intact.
    """
    if not raw_events:
        return []

    if rosters is None:
        rosters = get_shield_rosters()

    blocked_entities, blocked_events, blocked_media = rosters
    if not blocked_entities and not blocked_events and not blocked_media:
        return list(raw_events)

    return [ev for ev in raw_events if not is_event_shielded(ev, rosters=rosters)]
