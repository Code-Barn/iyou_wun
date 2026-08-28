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
import re

IMAGE_EXT_REGEX = re.compile(r"https?://[^\s<>\"]+?\.(?:png|jpg|jpeg|gif|webp|svg)(?:\?[^\s<>\"]*)?", re.IGNORECASE)
VIDEO_EXT_REGEX = re.compile(r"https?://[^\s<>\"]+?\.(?:mp4|webm|mov|m4v)(?:\?[^\s<>\"]*)?", re.IGNORECASE)
AUDIO_EXT_REGEX = re.compile(r"https?://[^\s<>\"]+?\.(?:mp3|ogg|wav|m4a|flac)(?:\?[^\s<>\"]*)?", re.IGNORECASE)
MEDIA_HOST_REGEX = re.compile(r"https?://(?:image\.nostr\.build|cdn\.iyou\.me|blossom\.[^\s<>\"]+)/[^\s<>\"]+", re.IGNORECASE)
URL_REGEX = re.compile(r"https?://[^\s<>\"]+", re.IGNORECASE)


def extract_media_from_note(note):
    """Extract and unfurl media attachments from Kind 1063 tags or Kind 1 note content."""
    if not isinstance(note, dict):
        return note

    kind = note.get("kind")
    tags = note.get("tags") or []
    content = note.get("content") or ""
    media_attachments = []
    seen_urls = set()

    # 1. Kind 1063 (NIP-94 File Header)
    if kind == 1063:
        from .views import get_tag_value
        file_url = sanitize_media_url(get_tag_value(tags, "url"))
        mime = (get_tag_value(tags, "m") or "").lower()
        dim = get_tag_value(tags, "dim") or ""
        thumb = sanitize_media_url(get_tag_value(tags, "thumb"))
        alt = get_tag_value(tags, "alt") or get_tag_value(tags, "summary") or ""
        x_hash = get_tag_value(tags, "x") or ""

        if not file_url and content.startswith("http"):
            file_url = sanitize_media_url(content.strip())

        note["file_url"] = file_url
        note["media_url"] = file_url
        note["mime_type"] = mime
        note["dimensions"] = dim
        note["thumbnail_url"] = thumb
        note["alt_text"] = alt
        note["is_sovereign"] = bool(file_url and "127.0.0.1" in file_url)

        if file_url:
            media_type = "file"
            if "image" in mime or IMAGE_EXT_REGEX.search(file_url):
                media_type = "image"
            elif "video" in mime or VIDEO_EXT_REGEX.search(file_url):
                media_type = "video"
            elif "audio" in mime or AUDIO_EXT_REGEX.search(file_url):
                media_type = "audio"

            note["media_type"] = media_type
            media_attachments.append({
                "type": media_type,
                "url": file_url,
                "dim": dim,
                "thumb": thumb,
                "alt": alt,
                "mime": mime,
                "hash": x_hash,
            })
            seen_urls.add(file_url)

    # 2. Kind 1 & general notes: Scan content for unfurled media URLs
    media_urls_in_content = []
    for match in URL_REGEX.finditer(content):
        raw_url = match.group(0)
        clean_url = raw_url.rstrip(".,;:!?)>\"'")
        if not clean_url:
            continue

        m_type = None
        if VIDEO_EXT_REGEX.search(clean_url):
            m_type = "video"
        elif AUDIO_EXT_REGEX.search(clean_url):
            m_type = "audio"
        elif IMAGE_EXT_REGEX.search(clean_url):
            m_type = "image"
        elif MEDIA_HOST_REGEX.search(clean_url):
            m_type = "image"

        if m_type:
            sanitized = sanitize_media_url(clean_url)
            if sanitized not in seen_urls and clean_url not in seen_urls:
                media_attachments.append({
                    "type": m_type,
                    "url": sanitized,
                })
                seen_urls.add(sanitized)
                seen_urls.add(clean_url)
            media_urls_in_content.append(raw_url)

    # 3. Compute display_content
    display_content = content
    if media_urls_in_content:
        for u in media_urls_in_content:
            display_content = re.sub(rf"(?:^|\s+){re.escape(u)}(?:\s+|$)", "\n", display_content)
        display_content = display_content.strip()

    note["media_attachments"] = media_attachments
    note["display_content"] = display_content

    return note



def parse_nip10_tags(tags):
    """Parse NIP-10 reply tags from an event's tags array.

    Returns (root_id, parent_id, reply_marker, mention_ids, reply_to_pubkey) where:
      - root_id:   the root event id (from the "root" marker), or None
      - parent_id: the direct parent id (from the "reply" marker or first "e" tag), or None
      - reply_marker: "root" | "reply" | None
      - mention_ids: list of all mentioned event ids (from "e" tags)
      - reply_to_pubkey: the target author hex pubkey (from "p" tags), or None
    """
    root_id = None
    parent_id = None
    reply_marker = None
    mention_ids = []
    reply_to_pubkey = None

    for tag in tags:
        if not tag or len(tag) < 2:
            continue

        tag_type = tag[0]
        if tag_type == "e":
            eid = tag[1]
            marker = ""
            if len(tag) > 3 and tag[3] in ("root", "reply", "mention"):
                marker = tag[3]
            elif len(tag) > 2 and tag[2] in ("root", "reply", "mention"):
                marker = tag[2]

            mention_ids.append(eid)

            if marker == "root":
                root_id = eid
            elif marker == "reply":
                parent_id = eid
                reply_marker = "reply"
            elif not parent_id:
                # Legacy positional or unmarked
                parent_id = eid
                if not root_id:
                    root_id = eid
        elif tag_type == "p":
            pk = tag[1]
            marker = tag[3] if len(tag) > 3 else (tag[2] if len(tag) > 2 else "")
            if marker == "reply" or not reply_to_pubkey:
                reply_to_pubkey = pk

    return root_id, parent_id, reply_marker, mention_ids, reply_to_pubkey



def sanitize_media_url(url):
    """Ensure media attachments, Blossom assets, and avatars use HTTPS unless local."""
    if not url:
        return ""
    url = str(url).strip()
    if url.startswith("http://") and not ("127.0.0.1" in url or "localhost" in url):
        return "https://" + url[7:]
    return url


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

    from .views import hex_to_npub, resolve_author_did

    def _ts_to_datetime(ts):
        from datetime import datetime
        if isinstance(ts, datetime):
            return ts
        return datetime.fromtimestamp(ts or 0)

    def enrich(e, root_id=None, parent_id=None, reply_to_pubkey=None):
        pk = e.get("pubkey", "")
        prof = profiles.get(pk, {})
        tags = e.get("tags", [])

        reply_npub = hex_to_npub(reply_to_pubkey) if reply_to_pubkey else ""
        reply_prof = profiles.get(reply_to_pubkey, {}) if reply_to_pubkey else {}
        reply_name = reply_prof.get("display_name") or reply_prof.get("name") or ""

        note = {
            "id": e.get("id", ""),
            "kind": e.get("kind"),
            "pubkey": pk,
            "pubkey_hex": pk,
            "author_did": e.get("author_did") or resolve_author_did(pk),
            "tags_json": json.dumps(tags),
            "npub": hex_to_npub(pk) if pk else "",
            "nip05": prof.get("nip05") or "",
            "lud16": prof.get("lud16") or "",
            "content": e.get("content", ""),
            "created_at": _ts_to_datetime(e.get("created_at", 0)),
            "tags": tags,
            "author_name": prof.get("display_name") or prof.get("name") or "",
            "author_avatar": sanitize_media_url(prof.get("picture", "")),
            "parent_id": parent_id or "",
            "root_id": root_id or "",
            "reply_to_pubkey": reply_to_pubkey or "",
            "reply_to_npub": reply_npub,
            "reply_to_name": reply_name,
            "reply_count": 0,
            "reactions": [],
            "replies": [],
        }
        return extract_media_from_note(note)


    if isinstance(raw_events, list):
        deduped_raw = {}
        for e in raw_events:
            if isinstance(e, dict) and e.get("id"):
                if e["id"] not in deduped_raw:
                    deduped_raw[e["id"]] = e
        raw_events = deduped_raw
    elif isinstance(raw_events, dict):
        deduped_raw = {}
        for eid, e in raw_events.items():
            if isinstance(e, dict):
                real_id = e.get("id") or eid
                if real_id not in deduped_raw:
                    deduped_raw[real_id] = e
        raw_events = deduped_raw

    # --- first pass: classify root notes vs replies ---
    parsed = {}
    roots = []
    seen_root_ids = set()
    reply_map = {}      # parent_id → [note]
    all_replies = []
    seen_reply_ids = set()

    for eid, e in raw_events.items():
        kind = e.get("kind")
        tags = e.get("tags", [])
        root_id, parent_id, marker, mention_ids, reply_to_pubkey = parse_nip10_tags(tags)

        is_reply = False
        if kind == 1111:
            is_reply = True
        elif kind == 1:
            # Kind 1 note with explicit reply marker or e tags
            if parent_id or marker == "reply":
                is_reply = True

        if is_reply:
            if eid not in seen_reply_ids:
                note = enrich(e, root_id=root_id, parent_id=parent_id or root_id, reply_to_pubkey=reply_to_pubkey)
                parsed[eid] = note
                all_replies.append(note)
                seen_reply_ids.add(eid)
        else:
            if eid not in seen_root_ids:
                note = _enrich_root(e, kind, profiles, _ts_to_datetime, root_id=root_id, parent_id=parent_id, reply_to_pubkey=reply_to_pubkey)
                roots.append(note)
                seen_root_ids.add(eid)

    # --- second pass: attach replies to parents ---
    reply_count = 0
    seen_reply_by_parent = set()
    for note in all_replies:
        pid = note.get("parent_id") or note.get("root_id")
        if pid:
            key = (pid, note["id"])
            if key not in seen_reply_by_parent:
                seen_reply_by_parent.add(key)
                reply_map.setdefault(pid, []).append(note)
                reply_count += 1

    # Sort replies by created_at ascending (oldest first = thread order)
    for pid in reply_map:
        reply_map[pid].sort(key=lambda n: n["created_at"])

    # Attach direct replies and recursive reply counts to root notes
    root_ids = set(seen_root_ids)
    for root in roots:
        direct_replies = reply_map.get(root["id"], [])
        root["replies"] = direct_replies
        root["reply_count"] = _count_all_replies(root["id"], reply_map) or len(direct_replies)

    # If any reply is an orphan (parent is not in current roots batch), promote to roots so it's not silently lost
    for note in all_replies:
        pid = note.get("parent_id") or note.get("root_id")
        if pid and pid not in root_ids and note["id"] not in root_ids:
            direct_replies = reply_map.get(note["id"], [])
            note["replies"] = direct_replies
            note["reply_count"] = _count_all_replies(note["id"], reply_map) or len(direct_replies)
            roots.append(note)
            root_ids.add(note["id"])


    roots.sort(key=lambda x: x["created_at"], reverse=True)

    return {
        "roots": roots,
        "replies_by_parent": reply_map,
        "total_reply_count": reply_count,
    }



def _enrich_root(e, kind, profiles, ts_fn, root_id="", parent_id="", reply_to_pubkey=""):
    """Enrich a root event (Kind 1, 1063, 30023) with author profile."""
    from .views import hex_to_npub, get_tag_value, resolve_author_did
    pk = e.get("pubkey", "")
    prof = profiles.get(pk, {})
    tags = e.get("tags", [])

    reply_npub = hex_to_npub(reply_to_pubkey) if reply_to_pubkey else ""
    reply_prof = profiles.get(reply_to_pubkey, {}) if reply_to_pubkey else {}
    reply_name = reply_prof.get("display_name") or reply_prof.get("name") or ""

    note = {
        "id": e.get("id", ""),
        "kind": kind,
        "pubkey": pk,
        "pubkey_hex": pk,
        "author_did": e.get("author_did") or resolve_author_did(pk),
        "tags_json": json.dumps(tags),
        "npub": hex_to_npub(pk) if pk else "",
        "nip05": prof.get("nip05") or "",
        "lud16": prof.get("lud16") or "",
        "content": e.get("content", ""),
        "created_at": ts_fn(e.get("created_at", 0)),
        "tags": tags,
        "author_name": prof.get("display_name") or prof.get("name") or "",
        "author_avatar": sanitize_media_url(prof.get("picture", "")),
        "parent_id": parent_id or "",
        "root_id": root_id or "",
        "reply_to_pubkey": reply_to_pubkey or "",
        "reply_to_npub": reply_npub,
        "reply_to_name": reply_name,
        "reply_count": 0,
        "reactions": [],
        "replies": [],
    }

    if kind == 1063:
        note["file_url"] = sanitize_media_url(get_tag_value(tags, "url"))
        note["media_url"] = note["file_url"] or ""
        mime = (get_tag_value(tags, "m") or "").lower()
        note["mime_type"] = mime
        note["dimensions"] = get_tag_value(tags, "dim")
        note["thumbnail_url"] = sanitize_media_url(get_tag_value(tags, "thumb"))
        note["alt_text"] = get_tag_value(tags, "alt") or get_tag_value(tags, "summary") or ""
        note["is_sovereign"] = bool(note.get("file_url") and "127.0.0.1" in note.get("file_url", ""))
        if "image" in mime:
            note["media_type"] = "image"
        elif "video" in mime:
            note["media_type"] = "video"
        elif "audio" in mime:
            note["media_type"] = "audio"
        else:
            note["media_type"] = "other"

    if kind == 30023:
        note["poll_options"] = [t[1] for t in tags if t and t[0] == "option" and len(t) > 1]
        note["poll_d_tag"] = get_tag_value(tags, "d")
        note["poll_scope_geohash"] = get_tag_value(tags, "geohash")
        note["poll_scope_org"] = get_tag_value(tags, "org")
        note["poll_closes_at"] = get_tag_value(tags, "expires")

    return extract_media_from_note(note)




def _count_all_replies(parent_id, reply_map):
    """Recursively count all replies under a parent (including nested replies)."""
    total = 0
    for note in reply_map.get(parent_id, []):
        total += 1
        total += _count_all_replies(note["id"], reply_map)
    return total

