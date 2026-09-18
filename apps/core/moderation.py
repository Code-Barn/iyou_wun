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

from collections import Counter
import logging
import urllib.error
import urllib.request
from typing import Any

from django.core.cache import cache
from django.db.models import Q

from .did_kit import did_to_pubkey
from .models import (
    CommunityFlagLedger,
    ModerationAppeal,
    ModerationReviewDocket,
    NodeBlockedEntity,
    NodeContentTakedown,
    UserLinkDeck,
)

logger = logging.getLogger(__name__)

TIER1_BLUR_THRESHOLD = 3
TIER2_SUPPRESS_THRESHOLD = 7
TIER3_QUARANTINE_THRESHOLD = 15

CACHE_KEY_BLOCKED_ENTITIES = "wun_shield_blocked_entities"
CACHE_KEY_BLOCKED_EVENTS = "wun_shield_blocked_events"
CACHE_KEY_BLOCKED_MEDIA = "wun_shield_blocked_media"
CACHE_KEY_TIER1_EVENTS = "wun_shield_tier1_events"
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
    """Retrieve active blocked and community-quarantined (Tier 3+) entity identifiers as an $O(1)$ lookup set."""
    cached = cache.get(CACHE_KEY_BLOCKED_ENTITIES)
    if cached is not None:
        return cached

    entities: set[str] = set()
    # 1. Operator blocked entities
    qs = NodeBlockedEntity.objects.filter(is_active=True).values_list("entity_identifier", flat=True)
    for identifier in qs:
        if identifier:
            clean = str(identifier).strip()
            entities.add(clean)
            entities.add(clean.lower())

    # 2. Community review dockets at Tier 3 (social quarantine), unless dismissed
    docket_pubkeys = (
        ModerationReviewDocket.objects.filter(
            docket_type="pubkey",
            current_tier__gte=3,
        )
        .exclude(status="DISMISSED")
        .values_list("target_identifier", flat=True)
    )
    for identifier in docket_pubkeys:
        if identifier:
            clean = str(identifier).strip()
            entities.add(clean)
            entities.add(clean.lower())

    cache.set(CACHE_KEY_BLOCKED_ENTITIES, entities, CACHE_TIMEOUT)
    return entities


def get_blocked_events() -> set[str]:
    """Retrieve active takedown and community-suppressed (Tier 2+) event IDs as an $O(1)$ lookup set."""
    cached = cache.get(CACHE_KEY_BLOCKED_EVENTS)
    if cached is not None:
        return cached

    events: set[str] = set()
    # 1. Statutory takedowns
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

    # 2. Community review dockets at Tier 2 (discovery suppression) or higher, unless dismissed
    docket_events = (
        ModerationReviewDocket.objects.filter(
            docket_type="event",
            current_tier__gte=2,
        )
        .exclude(status="DISMISSED")
        .values_list("target_identifier", flat=True)
    )
    for event_id in docket_events:
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


def get_tier1_event_ids() -> set[str]:
    """Retrieve active event IDs that reached Tier 1 progressive friction (blur)."""
    cached = cache.get(CACHE_KEY_TIER1_EVENTS)
    if cached is not None:
        return cached

    tier1_events: set[str] = set()
    docket_events = (
        ModerationReviewDocket.objects.filter(
            docket_type="event",
            current_tier__gte=1,
        )
        .exclude(status="DISMISSED")
        .values_list("target_identifier", flat=True)
    )
    for event_id in docket_events:
        if event_id:
            clean = str(event_id).strip()
            tier1_events.add(clean)
            tier1_events.add(clean.lower())

    cache.set(CACHE_KEY_TIER1_EVENTS, tier1_events, CACHE_TIMEOUT)
    return tier1_events


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
    """Invalidate all cached moderation shield rosters and friction sets."""
    for key in (
        CACHE_KEY_BLOCKED_ENTITIES,
        CACHE_KEY_BLOCKED_EVENTS,
        CACHE_KEY_BLOCKED_MEDIA,
        CACHE_KEY_TIER1_EVENTS,
    ):
        cache.delete(key)
    logger.debug("Moderation shield cache invalidated.")


def record_community_flag(
    reporter_did: str,
    target_pubkey: str,
    target_event_id: str = "",
    reason: str = "SPAM",
) -> dict:
    """
    Ingest and deduplicate a community report/flag, update flag tallies,
    upsert ModerationReviewDocket, dynamically update suppression caches,
    and invalidate the shield cache.
    """
    clean_reporter = str(reporter_did or "").strip()
    clean_pubkey = str(target_pubkey or "").strip()
    clean_event_id = str(target_event_id or "").strip()
    clean_reason = str(reason or "SPAM").strip().upper()

    valid_reasons = {c[0] for c in CommunityFlagLedger.REASON_CHOICES}
    if clean_reason not in valid_reasons:
        clean_reason = "SPAM"

    if not clean_event_id and not clean_pubkey:
        return {"success": False, "tier": 0, "flag_count": 0}

    # Deduplicate & persist to CommunityFlagLedger
    if clean_event_id:
        flag, created = CommunityFlagLedger.objects.get_or_create(
            target_event_id=clean_event_id,
            reporter_did=clean_reporter,
            defaults={
                "target_pubkey": clean_pubkey,
                "reason": clean_reason,
            },
        )
        if not created and (flag.reason != clean_reason or (clean_pubkey and not flag.target_pubkey)):
            flag.reason = clean_reason
            if clean_pubkey and not flag.target_pubkey:
                flag.target_pubkey = clean_pubkey
            flag.save(update_fields=["reason", "target_pubkey"])
    else:
        flag, created = CommunityFlagLedger.objects.get_or_create(
            target_pubkey=clean_pubkey,
            reporter_did=clean_reporter,
            target_event_id="",
            defaults={
                "reason": clean_reason,
            },
        )
        if not created and flag.reason != clean_reason:
            flag.reason = clean_reason
            flag.save(update_fields=["reason"])

    # Tally total unique flags
    event_flag_count = 0
    if clean_event_id:
        event_flag_count = CommunityFlagLedger.objects.filter(target_event_id=clean_event_id).count()

    pubkey_flag_count = 0
    if clean_pubkey:
        pubkey_flag_count = CommunityFlagLedger.objects.filter(target_pubkey=clean_pubkey).count()

    # Calculate tiers
    def _calc_tier(count: int) -> int:
        if count >= TIER3_QUARANTINE_THRESHOLD:
            return 3
        if count >= TIER2_SUPPRESS_THRESHOLD:
            return 2
        if count >= TIER1_BLUR_THRESHOLD:
            return 1
        return 0

    event_tier = _calc_tier(event_flag_count) if clean_event_id else 0
    pubkey_tier = _calc_tier(pubkey_flag_count) if clean_pubkey else 0

    # Upsert ModerationReviewDocket
    if clean_event_id:
        docket, _ = ModerationReviewDocket.objects.get_or_create(
            target_identifier=clean_event_id,
            defaults={
                "docket_type": "event",
                "flag_count": event_flag_count,
                "current_tier": event_tier,
                "status": "PENDING",
            },
        )
        if docket.flag_count != event_flag_count or docket.current_tier != event_tier:
            docket.flag_count = event_flag_count
            docket.current_tier = event_tier
            docket.save(update_fields=["flag_count", "current_tier", "updated_at"])

    if clean_pubkey and (pubkey_flag_count >= TIER1_BLUR_THRESHOLD or pubkey_tier > 0):
        pk_docket, _ = ModerationReviewDocket.objects.get_or_create(
            target_identifier=clean_pubkey,
            defaults={
                "docket_type": "pubkey",
                "flag_count": pubkey_flag_count,
                "current_tier": pubkey_tier,
                "status": "PENDING",
            },
        )
        if pk_docket.flag_count != pubkey_flag_count or pk_docket.current_tier != pubkey_tier:
            pk_docket.flag_count = pubkey_flag_count
            pk_docket.current_tier = pubkey_tier
            pk_docket.save(update_fields=["flag_count", "current_tier", "updated_at"])

    # If tally >= TIER2, add target_event_id to dynamic suppression cache
    if clean_event_id and event_flag_count >= TIER2_SUPPRESS_THRESHOLD:
        cached_blocked_events = cache.get(CACHE_KEY_BLOCKED_EVENTS)
        if cached_blocked_events is not None:
            cached_blocked_events.add(clean_event_id)
            cached_blocked_events.add(clean_event_id.lower())
            cache.set(CACHE_KEY_BLOCKED_EVENTS, cached_blocked_events, CACHE_TIMEOUT)

    # If tally >= TIER3, add target_pubkey to dynamic quarantine cache
    if clean_pubkey and pubkey_flag_count >= TIER3_QUARANTINE_THRESHOLD:
        cached_blocked_entities = cache.get(CACHE_KEY_BLOCKED_ENTITIES)
        if cached_blocked_entities is not None:
            cached_blocked_entities.add(clean_pubkey)
            cached_blocked_entities.add(clean_pubkey.lower())
            cache.set(CACHE_KEY_BLOCKED_ENTITIES, cached_blocked_entities, CACHE_TIMEOUT)

    invalidate_shield_cache()

    target_tier = event_tier if clean_event_id else pubkey_tier
    target_count = event_flag_count if clean_event_id else pubkey_flag_count

    return {
        "success": True,
        "tier": target_tier,
        "flag_count": target_count,
    }


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


def annotate_progressive_friction(
    events: list[dict],
    tier1_event_ids: set[str] | None = None,
) -> list[dict]:
    """
    Annotate events whose ID has reached Tier 1 progressive friction with:
    has_content_warning = True
    warning_reason = "Flagged by community review"
    """
    if not events:
        return []

    if tier1_event_ids is None:
        tier1_event_ids = get_tier1_event_ids()

    if not tier1_event_ids:
        return events

    def _annotate_single(ev: Any) -> Any:
        if isinstance(ev, dict):
            ev_id = str(ev.get("id") or "").strip()
            if ev_id and (ev_id in tier1_event_ids or ev_id.lower() in tier1_event_ids):
                ev["has_content_warning"] = True
                if not ev.get("warning_reason"):
                    ev["warning_reason"] = "Flagged by community review"
            if "replies" in ev and isinstance(ev["replies"], list):
                for reply in ev["replies"]:
                    _annotate_single(reply)
            return ev
        else:
            ev_id = str(getattr(ev, "id", "") or "").strip()
            if ev_id and (ev_id in tier1_event_ids or ev_id.lower() in tier1_event_ids):
                try:
                    setattr(ev, "has_content_warning", True)
                    if not getattr(ev, "warning_reason", None):
                        setattr(ev, "warning_reason", "Flagged by community review")
                except Exception:
                    pass
            return ev

    return [_annotate_single(ev) for ev in events]


def get_author_active_frictions(author_identifier: str) -> list[dict]:
    """
    Inspect ModerationReviewDocket for active friction dockets matching the author's
    pubkey, DID, or notes authored by the pubkey.

    Returns a list of structured friction notices:
    [
        {
            "docket_id": int,
            "target_identifier": str,
            "type": str,
            "tier": int,
            "flag_count": int,
            "reasons": dict[str, int],
            "has_appeal": bool,
            "appeal_status": str | None,
            "appeal_id": int | None,
            "has_pending_appeal": bool,
        },
        ...
    ]
    """
    clean_author = str(author_identifier or "").strip()
    if not clean_author:
        return []

    candidate_keys = {clean_author, clean_author.lower()}
    resolved_pk = did_to_pubkey(clean_author)
    if resolved_pk:
        candidate_keys.add(resolved_pk.lower())

    decks = UserLinkDeck.objects.filter(
        Q(user__username__iexact=clean_author)
        | Q(handle__iexact=clean_author.lstrip("@"))
        | Q(nostr_pubkey__iexact=clean_author)
    )
    for deck in decks:
        if deck.nostr_pubkey:
            candidate_keys.add(deck.nostr_pubkey.lower())
        if deck.user and deck.user.username:
            candidate_keys.add(deck.user.username)
            candidate_keys.add(deck.user.username.lower())
            d_pk = did_to_pubkey(deck.user.username)
            if d_pk:
                candidate_keys.add(d_pk.lower())

    authored_event_ids = set(
        CommunityFlagLedger.objects.filter(
            target_pubkey__in=candidate_keys
        ).exclude(target_event_id="").values_list("target_event_id", flat=True)
    )
    authored_event_ids |= {eid.lower() for eid in authored_event_ids}

    dockets = (
        ModerationReviewDocket.objects.filter(
            Q(docket_type="pubkey", target_identifier__in=candidate_keys)
            | Q(docket_type="event", target_identifier__in=authored_event_ids)
            | Q(target_identifier__in=candidate_keys)
            | Q(target_identifier__in=authored_event_ids)
        )
        .filter(Q(current_tier__gte=1) | Q(flag_count__gte=TIER1_BLUR_THRESHOLD))
        .exclude(status="DISMISSED")
        .order_by("-current_tier", "-flag_count", "-created_at")
        .distinct()
    )

    frictions = []
    seen_docket_ids = set()
    for docket in dockets:
        if docket.id in seen_docket_ids:
            continue
        seen_docket_ids.add(docket.id)

        if docket.docket_type == "event":
            reason_list = CommunityFlagLedger.objects.filter(
                target_event_id=docket.target_identifier
            ).values_list("reason", flat=True)
        else:
            reason_list = CommunityFlagLedger.objects.filter(
                target_pubkey=docket.target_identifier
            ).values_list("reason", flat=True)

        reasons_dict = dict(Counter(reason_list))

        latest_appeal = docket.appeals.order_by("-created_at").first()
        has_appeal = latest_appeal is not None
        appeal_status = latest_appeal.status if latest_appeal else None
        appeal_id = latest_appeal.id if latest_appeal else None

        frictions.append(
            {
                "docket_id": docket.id,
                "target_identifier": docket.target_identifier,
                "type": docket.docket_type,
                "tier": docket.current_tier,
                "flag_count": docket.flag_count,
                "reasons": reasons_dict,
                "has_appeal": has_appeal,
                "appeal_status": appeal_status,
                "appeal_id": appeal_id,
                "has_pending_appeal": docket.has_pending_appeal,
            }
        )

    return frictions


def submit_moderation_appeal(
    docket_id: int,
    appellant_did: str,
    statement: str,
) -> dict:
    """
    Validate and record a restorative moderation appeal against a ModerationReviewDocket.

    - Validates docket existence.
    - Verifies appellant identity matches target or note author.
    - Prevents duplicate pending appeals per docket.
    - Creates ModerationAppeal and logs the submission.
    """
    try:
        docket = ModerationReviewDocket.objects.get(id=int(docket_id))
    except (ModerationReviewDocket.DoesNotExist, ValueError, TypeError):
        return {"success": False, "error": "Review docket not found."}

    clean_did = str(appellant_did or "").strip()
    clean_statement = str(statement or "").strip()

    if not clean_did:
        return {"success": False, "error": "Appellant DID is required."}
    if not clean_statement:
        return {"success": False, "error": "Appeal statement cannot be blank."}

    # Verify appellant identity matches target or note author
    candidate_keys = {clean_did, clean_did.lower()}
    resolved_pk = did_to_pubkey(clean_did)
    if resolved_pk:
        candidate_keys.add(resolved_pk.lower())

    decks = UserLinkDeck.objects.filter(
        Q(user__username__iexact=clean_did)
        | Q(handle__iexact=clean_did.lstrip("@"))
        | Q(nostr_pubkey__iexact=clean_did)
    )
    for deck in decks:
        if deck.nostr_pubkey:
            candidate_keys.add(deck.nostr_pubkey.lower())
        if deck.user and deck.user.username:
            candidate_keys.add(deck.user.username)
            candidate_keys.add(deck.user.username.lower())
            d_pk = did_to_pubkey(deck.user.username)
            if d_pk:
                candidate_keys.add(d_pk.lower())

    is_authorized = False
    if (
        docket.target_identifier in candidate_keys
        or docket.target_identifier.lower() in candidate_keys
    ):
        is_authorized = True
    elif docket.docket_type == "event":
        is_authorized = CommunityFlagLedger.objects.filter(
            target_event_id=docket.target_identifier,
            target_pubkey__in=candidate_keys,
        ).exists()

    if not is_authorized:
        logger.warning(
            "Unauthorized appeal attempt for docket #%s by %s",
            docket.id,
            clean_did,
        )
        return {
            "success": False,
            "error": "Unauthorized: Appellant is not the author or target of this docket.",
        }

    # Prevent duplicate pending appeals per docket
    if docket.has_pending_appeal:
        return {
            "success": False,
            "error": "An appeal is already pending review for this docket.",
        }

    appeal = ModerationAppeal.objects.create(
        docket=docket,
        appellant_did=clean_did,
        statement=clean_statement,
        status="PENDING",
    )
    logger.info(
        "Moderation appeal #%s submitted for docket #%s by %s",
        appeal.id,
        docket.id,
        clean_did,
    )
    return {
        "success": True,
        "appeal_id": appeal.id,
        "status": appeal.status,
    }


