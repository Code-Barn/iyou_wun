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

"""
NIP-10 Threading Engine — reply tree builder for Nostr Kind 1111 events.

Implements:
  - parse_nip10_tags(event)  → root_id, parent_id, reply_marker, mention_ids
  - build_thread_tree(raw_events, profiles) → {roots: [...], replies_by_parent: {...}, total_reply_count: int}

NIP-10 tag format:
  ["e", <root_event_id>, <relay_url>, "root"]
  ["e", <parent_event_id>, <relay_url>, "reply"]
  ["p", <author_pubkey>, <relay_url>]
"""


def parse_nip10_tags(tags):
    """Parse NIP-10 reply tags from a Kind 1111 event's tags array.

    Returns (root_id, parent_id, reply_marker, mention_ids) where:
      - root_id:   the root event id (from the "root" marker), or None
      - parent_id: the direct parent id (from the "reply" marker or first "e" tag), or None
      - reply_marker: "root" | "reply" | None
      - mention_ids: list of all mentioned event ids (from "e" tags)
    """
    root_id = None
    parent_id = None
    reply_marker = None
    mention_ids = []

    for tag in tags:
        if not tag or len(tag) < 2 or tag[0] != "e":
            continue

        eid = tag[1]
        marker = tag[2] if len(tag) > 2 else ""
        mention_ids.append(eid)

        if marker == "root":
            root_id = eid
        elif marker == "reply":
            parent_id = eid
            reply_marker = "reply"
        elif not parent_id and len(mention_ids) <= 2:
            # Legacy or unmarked: first "e" without marker
            # Treat as the parent; if root is already set, use it
            parent_id = eid
            if not root_id:
                root_id = eid

    return root_id, parent_id, reply_marker, mention_ids


def build_thread_tree(raw_events, profiles=None):
    """Build a threaded reply tree from raw Nostr events.

    Args:
        raw_events: dict mapping event_id → raw event dict
        profiles:   dict mapping hex_pubkey → Kind 0 content dict

    Returns:
        {
          "roots": [ enriched_note, ... ],
          "replies_by_parent": { parent_id: [ enriched_note, ... ], ... },
          "total_reply_count": int,
        }

    Roots are Kind 1 or Kind 1063 or Kind 30023 events that have no
    parent_id, or whose parent_id is not in the current batch.
    """
    if profiles is None:
        profiles = {}

    from .views import hex_to_npub

    # --- first pass: parse every Kind 1111 reply ---
    parsed = {}
    roots = []
    reply_map = {}      # parent_id → [note]
    all_replies = []

    def enrich(e):
        pk = e.get("pubkey", "")
        prof = profiles.get(pk, {})
        return {
            "id": e.get("id", ""),
            "kind": e.get("kind"),
            "pubkey": pk,
            "npub": hex_to_npub(pk) if pk else "",
            "content": e.get("content", ""),
            "created_at": _ts_to_datetime(e.get("created_at", 0)),
            "tags": e.get("tags", []),
            "author_name": prof.get("display_name") or prof.get("name") or "",
            "author_avatar": prof.get("picture", ""),
        }

    def _ts_to_datetime(ts):
        from datetime import datetime
        if isinstance(ts, datetime):
            return ts
        return datetime.fromtimestamp(ts or 0)

    for eid, e in raw_events.items():
        kind = e.get("kind")
        if kind in (1, 1063, 30023):
            note = _enrich_root(e, kind, profiles, _ts_to_datetime)
            roots.append(note)
        elif kind == 1111:
            root_id, parent_id, marker, _ = parse_nip10_tags(e.get("tags", []))
            note = enrich(e)
            note["_root_id"] = root_id
            note["_parent_id"] = parent_id
            note["_marker"] = marker
            parsed[eid] = note
            all_replies.append(note)

    # --- second pass: attach replies to parents ---
    reply_count = 0
    for note in all_replies:
        pid = note["_parent_id"] or note["_root_id"]
        if pid:
            reply_map.setdefault(pid, []).append(note)
            reply_count += 1

    # Sort replies by created_at ascending (oldest first = thread order)
    for pid in reply_map:
        reply_map[pid].sort(key=lambda n: n["created_at"])

    # Attach reply counts to root notes and clean up internal keys
    for root in roots:
        direct_replies = reply_map.get(root["id"], [])
        root["reply_count"] = _count_all_replies(root["id"], reply_map)
        root["replies"] = direct_replies
        for key in ("_root_id", "_parent_id", "_marker"):
            root.pop(key, None)

    # Clean up internal keys from replies
    for note in all_replies:
        for key in ("_root_id", "_parent_id", "_marker"):
            note.pop(key, None)

    # Roots that are not in the raw_events batch but referenced as root_id
    # get their reply_count from reply_map
    roots.sort(key=lambda x: x["created_at"], reverse=True)

    return {
        "roots": roots,
        "replies_by_parent": reply_map,
        "total_reply_count": reply_count,
    }


def _enrich_root(e, kind, profiles, ts_fn):
    """Enrich a root event (Kind 1, 1063, 30023) with author profile."""
    from .views import hex_to_npub, get_tag_value
    pk = e.get("pubkey", "")
    prof = profiles.get(pk, {})
    tags = e.get("tags", [])

    note = {
        "id": e.get("id", ""),
        "kind": kind,
        "pubkey": pk,
        "npub": hex_to_npub(pk) if pk else "",
        "content": e.get("content", ""),
        "created_at": ts_fn(e.get("created_at", 0)),
        "tags": tags,
        "author_name": prof.get("display_name") or prof.get("name") or "",
        "author_avatar": prof.get("picture", ""),
        "reply_count": 0,
        "reactions": [],
        "replies": [],
    }

    if kind == 1063:
        note["file_url"] = get_tag_value(tags, "url")
        note["mime_type"] = get_tag_value(tags, "m")
        note["dimensions"] = get_tag_value(tags, "dim")
        note["thumbnail_url"] = get_tag_value(tags, "thumb")
        note["alt_text"] = get_tag_value(tags, "alt")
        note["is_sovereign"] = bool(note.get("file_url") and "127.0.0.1" in note.get("file_url", ""))

    if kind == 30023:
        note["poll_options"] = [t[1] for t in tags if t and t[0] == "option" and len(t) > 1]
        note["poll_d_tag"] = get_tag_value(tags, "d")
        note["poll_scope_geohash"] = get_tag_value(tags, "geohash")
        note["poll_scope_org"] = get_tag_value(tags, "org")
        note["poll_closes_at"] = get_tag_value(tags, "expires")

    return note


def _count_all_replies(parent_id, reply_map):
    """Recursively count all replies under a parent (including nested replies)."""
    total = 0
    for note in reply_map.get(parent_id, []):
        total += 1
        total += _count_all_replies(note["id"], reply_map)
    return total
