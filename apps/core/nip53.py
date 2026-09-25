"""
NIP-53: Live Activities & Audio Spaces (Kind 30311).
Parses parameterized replaceable events into structured live space metadata.
"""
from typing import Any, Dict, List, Optional


def parse_nip53_event(event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Parse a Kind 30311 Nostr event into a structured Live Room dictionary."""
    if not isinstance(event, dict) or event.get("kind") != 30311:
        return None

    tags = event.get("tags", [])
    if not isinstance(tags, list):
        tags = []
    d_tag = ""
    title = ""
    summary = ""
    streaming_url = ""
    status = "planned"
    current_participants = 0
    image_url = ""
    host_pubkey = event.get("pubkey", "")
    starts = None
    relays = []

    for tag in tags:
        if not isinstance(tag, list) or len(tag) < 2:
            continue
        key, val = tag[0], tag[1]
        if key == "d":
            d_tag = val
        elif key == "title":
            title = val
        elif key == "summary":
            summary = val
        elif key == "streaming":
            streaming_url = val
        elif key == "status":
            status = val.lower()
        elif key == "current_participants":
            try:
                current_participants = int(val)
            except (ValueError, TypeError):
                current_participants = 0
        elif key == "image":
            image_url = val
        elif key == "relays":
            relays = tag[1:]
        elif key == "p" and len(tag) >= 4 and tag[3].lower() == "host":
            host_pubkey = val

    # Fallback title from summary or d-tag
    if not title:
        title = summary[:40] if summary else (d_tag or "Untitled Space")

    return {
        "id": event.get("id", ""),
        "d_tag": d_tag,
        "title": title,
        "summary": summary,
        "streaming_url": streaming_url,
        "status": status,
        "current_participants": current_participants,
        "image_url": image_url,
        "host_pubkey": host_pubkey,
        "starts": starts,
        "relays": relays,
        "created_at": event.get("created_at", 0),
    }


def filter_active_live_rooms(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Filter and order active live rooms (live status first).

    Deduplicates parameterized replaceable events by ``(pubkey, d_tag)``,
    keeping the most recently published state for each live room identifier.
    """
    rooms_by_key: Dict[tuple, Dict[str, Any]] = {}
    for ev in events:
        room = parse_nip53_event(ev)
        if not room:
            continue
        # Deduplicate parameterized replaceable events by (pubkey, d_tag),
        # preserving the latest state (highest created_at) per identifier.
        key = (room["host_pubkey"], room["d_tag"])
        existing = rooms_by_key.get(key)
        if existing is None or (room["created_at"] or 0) >= (existing["created_at"] or 0):
            rooms_by_key[key] = room

    rooms = list(rooms_by_key.values())
    # Order: status == 'live' first, then participant count descending
    rooms.sort(
        key=lambda r: (1 if r["status"] == "live" else 0, r["current_participants"]),
        reverse=True,
    )
    return rooms