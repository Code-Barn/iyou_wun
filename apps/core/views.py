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

import base64
import json
import re
import ssl
import threading
import time
from datetime import datetime

import bech32
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from urllib.parse import urlencode
from django.http import JsonResponse, HttpResponseBadRequest
from django.shortcuts import redirect, render
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET
from django.views.generic import TemplateView
from django.views import View
from websocket import WebSocketApp

from services.poly_client import PolyClient, PolyConnectionError

from .did_kit import get_public_key_hex, issue_vc
from .models import IssuedCredential


def home(request):
    return redirect("feed")


@login_required
def dashboard(request):
    user_pubkey = did_to_pubkey(request.user.username)
    user_npub = did_to_npub(request.user.username)
    relays = request.session.get("relays", DEFAULT_RELAYS)
    profile = fetch_profile_data(user_pubkey, relay_urls=relays) if user_pubkey else {}
    return render(request, "dashboard.html", {
        "user_pubkey": user_pubkey,
        "user_npub": user_npub,
        "user_did": request.user.username,
        "profile": profile,
        "relays": relays,
    })


class FeedView(TemplateView):
    template_name = "feed.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        user_pubkey = did_to_pubkey(self.request.user.username) if self.request.user.is_authenticated else None
        user_npub = did_to_npub(self.request.user.username) if self.request.user.is_authenticated else None
        relays = self.request.session.get("relays", DEFAULT_RELAYS)

        context["user_pubkey"] = user_pubkey
        context["user_npub"] = user_npub
        context["user_did"] = self.request.user.username if self.request.user.is_authenticated else None
        context["relays_json"] = json.dumps(relays)
        context["user_credentials"] = {}

        thread_id = self.request.GET.get("thread")
        context["thread_id"] = thread_id

        if thread_id:
            thread_data = fetch_thread(thread_id, relay_urls=relays)
            context["thread_mode"] = True
            context["feed_mode"] = "thread"
            context["notes"] = thread_data["roots"]
            context["thread_replies"] = thread_data["replies"]
            context["thread_reply_count"] = thread_data["total_replies"]
        else:
            mode = self.request.GET.get("mode", "network")
            context["feed_mode"] = mode

            if mode == "network" and user_pubkey:
                contacts = fetch_contact_pubkeys(user_pubkey, relay_urls=relays)
                if contacts:
                    feed_data = fetch_unified_feed(authors=contacts, relay_urls=relays)
                else:
                    feed_data = fetch_unified_feed(authors=CURATED_AUTHORS, relay_urls=relays)
            else:
                feed_data = fetch_unified_feed(relay_urls=relays)

            context["notes"] = feed_data["roots"]
            context["thread_replies"] = feed_data["replies"]
            context["thread_reply_count"] = feed_data["total_replies"]

        return context

    def get(self, request, *args, **kwargs):
        if request.user.is_authenticated and not request.session.get("has_seen_feed_welcome", False):
            from django.contrib import messages

            messages.success(
                request,
                "Welcome to the Omni-Social Feed. Your identity is verified and sovereign.",
            )
            request.session["has_seen_feed_welcome"] = True

        return super().get(request, *args, **kwargs)


class ChatView(LoginRequiredMixin, TemplateView):
    template_name = "chat.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user_pubkey = did_to_pubkey(self.request.user.username)
        context["user_pubkey"] = user_pubkey
        context["user_did"] = self.request.user.username

        level = settings.WUN_USER_LEVEL
        context["user_level"] = level
        if level == "1":
            context["xmpp_domain"] = "iyou.me"
            context["xmpp_ws_url"] = "wss://xmpp.iyou.me:5222/xmpp-websocket"
        else:
            context["xmpp_domain"] = "127.0.0.1"
            context["xmpp_ws_url"] = "wss://home.iyou.me:5222/xmpp-websocket"

        context["xmpp_password"] = settings.XMPP_PASSWORD or user_pubkey
        return context


@login_required
@csrf_exempt
def api_relays(request):
    if request.method == 'GET':
        relays = request.session.get('relays', DEFAULT_RELAYS)
        return JsonResponse({'relays': relays})
    data = json.loads(request.body)
    relays = data.get('relays', DEFAULT_RELAYS)
    request.session['relays'] = relays
    return JsonResponse({'relays': relays})


@login_required
def api_feed(request):
    until = request.GET.get('until')
    mode = request.GET.get('mode', 'network')
    limit = 30

    user_pubkey = did_to_pubkey(request.user.username)
    relays = request.session.get('relays', DEFAULT_RELAYS)

    filter_obj = {"kinds": [1, 7, 1063, 1111, 30023, 1112], "limit": limit}
    if until:
        filter_obj["until"] = int(until)

    if mode == "network" and user_pubkey:
        contacts = fetch_contact_pubkeys(user_pubkey, relay_urls=relays)
        if contacts:
            filter_obj["authors"] = contacts
        else:
            filter_obj["authors"] = CURATED_AUTHORS

    raw_events = relay_req(filter_obj, relay_urls=relays)

    pubkeys = set()
    for e in raw_events.values():
        pk = e.get("pubkey")
        if pk:
            pubkeys.add(pk)
        for tag in e.get("tags", []):
            if tag and tag[0] == "p" and len(tag) > 1:
                pubkeys.add(tag[1])

    profiles = {}
    if pubkeys:
        profile_events = relay_req(
            {"kinds": [0], "authors": list(pubkeys)[:100]},
            relay_urls=relays,
        )
        for e in profile_events.values():
            pk = e.get("pubkey", "")
            try:
                profiles[pk] = json.loads(e.get("content", "{}"))
            except json.JSONDecodeError:
                profiles[pk] = {}

    feed_data = process_into_feed(raw_events, profiles, max_items=limit)

    def _serialize(note):
        result = dict(note)
        result["created_at"] = note["created_at"].timestamp()
        if note.get("votes"):
            result["votes"] = [dict(v) for v in note["votes"]]
        if note.get("reactions"):
            result["reactions"] = [{"id": r["id"], "pubkey": r["pubkey"], "content": r["content"]} for r in note["reactions"]]
        if note.get("replies"):
            result["replies"] = [_serialize(r) for r in note["replies"]]
            result["reply_count"] = note.get("reply_count", 0)
        return result

    roots = [_serialize(n) for n in feed_data["roots"]]

    # Serialize the flat reply map for JS client-side assembly
    replies_serialized = {}
    for pid, replies in feed_data.get("replies", {}).items():
        replies_serialized[pid] = [_serialize(r) for r in replies]

    return JsonResponse({
        "notes": roots,
        "replies": replies_serialized,
        "total_replies": feed_data["total_replies"],
    })


def npub_to_hex(npub_str):
    """Convert npub1... to hex pubkey."""
    try:
        hrp, data = bech32.bech32_decode(npub_str)
        if hrp != "npub" or data is None:
            return None
        decoded = bech32.convertbits(data, 5, 8, False)
        if decoded is None:
            return None
        return bytes(decoded).hex()
    except Exception:
        return None


def fetch_profile_data(hex_pubkey, relay_urls=None):
    """Fetch Kind 0 profile metadata for a pubkey."""
    events = relay_req({"kinds": [0], "authors": [hex_pubkey], "limit": 1}, relay_urls=relay_urls)
    for e in events.values():
        try:
            content = json.loads(e.get("content", "{}"))
        except (json.JSONDecodeError, TypeError):
            content = {}
        return {
            "name": content.get("display_name") or content.get("name", ""),
            "about": content.get("about", ""),
            "picture": content.get("picture", ""),
            "banner": content.get("banner", ""),
            "nip05": content.get("nip05", ""),
            "lud16": content.get("lud16", ""),
        }
    return {}


MEDIA_CATEGORIES = {
    "image": {
        "mime_prefixes": ("image/",),
        "extensions": (".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg", ".bmp", ".tiff"),
    },
    "video": {
        "mime_prefixes": ("video/",),
        "extensions": (".mp4", ".webm", ".mov", ".m4v", ".avi", ".mkv"),
    },
    "audio": {
        "mime_prefixes": ("audio/",),
        "extensions": (".mp3", ".ogg", ".wav", ".m4a", ".flac", ".aac", ".wma"),
    },
}


def categorize_media(note):
    """Classify a media note into image/video/audio/other by MIME and extension."""
    mime = (note.get("mime_type") or "").lower()
    url = (note.get("file_url") or "").lower()

    for cat, spec in MEDIA_CATEGORIES.items():
        for prefix in spec["mime_prefixes"]:
            if mime.startswith(prefix):
                return cat
        for ext in spec["extensions"]:
            if url.endswith(ext):
                return cat
    return "other"


def _extract_nip94_tags(tags):
    """Extract extended NIP-94 metadata from a Kind 1063 event's tags."""
    return {
        "duration": get_tag_value(tags, "duration"),
        "blossom_hash": get_tag_value(tags, "x"),
        "blurhash": get_tag_value(tags, "blurhash"),
        "summary": get_tag_value(tags, "summary"),
    }


def fetch_media_assets(authors=None, limit=50, relay_urls=None):
    """Fetch only Kind 1063 media events, flat sorted list."""
    filter_obj = {"kinds": [1063], "limit": limit}
    if authors:
        filter_obj["authors"] = authors

    raw_events = relay_req(filter_obj, relay_urls=relay_urls)
    if not raw_events:
        return []

    pubkeys = set()
    for e in raw_events.values():
        pk = e.get("pubkey")
        if pk:
            pubkeys.add(pk)

    profiles = {}
    if pubkeys:
        profile_events = relay_req({"kinds": [0], "authors": list(pubkeys)[:100]}, relay_urls=relay_urls)
        for e in profile_events.values():
            pk = e.get("pubkey", "")
            try:
                profiles[pk] = json.loads(e.get("content", "{}"))
            except (json.JSONDecodeError, TypeError):
                profiles[pk] = {}

    result = []
    for e in raw_events.values():
        tags = e.get("tags", [])
        pk = e.get("pubkey", "")
        npub_val = hex_to_npub(pk) if pk else ""
        profile = profiles.get(pk, {})
        file_url = get_tag_value(tags, "url")
        nip94 = _extract_nip94_tags(tags)
        note = {
            "id": e.get("id", ""),
            "kind": 1063,
            "pubkey": pk,
            "npub": npub_val,
            "content": e.get("content", ""),
            "created_at": datetime.fromtimestamp(e.get("created_at", 0)),
            "tags": tags,
            "file_url": file_url,
            "mime_type": get_tag_value(tags, "m"),
            "dimensions": get_tag_value(tags, "dim"),
            "thumbnail_url": get_tag_value(tags, "thumb"),
            "alt_text": get_tag_value(tags, "alt") or get_tag_value(tags, "summary") or "",
            "is_sovereign": bool(file_url and "127.0.0.1" in file_url),
            "author_name": profile.get("display_name") or profile.get("name") or "",
            "author_avatar": profile.get("picture", ""),
            "duration": nip94["duration"],
            "blossom_hash": nip94["blossom_hash"],
            "blurhash": nip94["blurhash"],
            "summary": nip94["summary"],
        }
        note["media_type"] = categorize_media(note)
        result.append(note)

    result.sort(key=lambda x: x["created_at"], reverse=True)
    return result[:limit]


def fetch_text_notes(authors=None, limit=20, relay_urls=None):
    """Fetch Kind 1 text notes for given authors, with profile enrichment."""
    filter_obj = {"kinds": [1], "limit": limit}
    if authors:
        filter_obj["authors"] = authors

    raw_events = relay_req(filter_obj, relay_urls=relay_urls)
    if not raw_events:
        return []

    pubkeys = set()
    for e in raw_events.values():
        pk = e.get("pubkey")
        if pk:
            pubkeys.add(pk)

    profiles = {}
    if pubkeys:
        profile_events = relay_req({"kinds": [0], "authors": list(pubkeys)[:100]}, relay_urls=relay_urls)
        for e in profile_events.values():
            pk = e.get("pubkey", "")
            try:
                profiles[pk] = json.loads(e.get("content", "{}"))
            except (json.JSONDecodeError, TypeError):
                profiles[pk] = {}

    result = []
    for e in raw_events.values():
        pk = e.get("pubkey", "")
        npub_val = hex_to_npub(pk) if pk else ""
        profile = profiles.get(pk, {})
        result.append({
            "id": e.get("id", ""),
            "kind": 1,
            "pubkey": pk,
            "npub": npub_val,
            "content": e.get("content", ""),
            "created_at": datetime.fromtimestamp(e.get("created_at", 0)),
            "tags": e.get("tags", []),
            "author_name": profile.get("display_name") or profile.get("name") or "",
            "author_avatar": profile.get("picture", ""),
        })

    result.sort(key=lambda x: x["created_at"], reverse=True)
    return result[:limit]


def fetch_thread(parent_id, relay_urls=None):
    """Fetch a parent event and its replies, return threaded feed dict."""
    parent_raw = relay_req({"ids": [parent_id], "limit": 1}, relay_urls=relay_urls)
    if not parent_raw:
        return {"roots": [], "replies": {}, "total_replies": 0, "flat": []}

    comments_raw = relay_req({"#e": [parent_id], "kinds": [1111], "limit": 50}, relay_urls=relay_urls)

    pubkeys = set()
    for e in list(parent_raw.values()) + list(comments_raw.values()):
        pk = e.get("pubkey")
        if pk:
            pubkeys.add(pk)

    profiles = {}
    if pubkeys:
        profile_events = relay_req({"kinds": [0], "authors": list(pubkeys)[:100]}, relay_urls=relay_urls)
        for e in profile_events.values():
            pk = e.get("pubkey", "")
            try:
                profiles[pk] = json.loads(e.get("content", "{}"))
            except (json.JSONDecodeError, TypeError):
                profiles[pk] = {}

    combined = {**parent_raw, **comments_raw}
    return process_into_feed(combined, profiles, max_items=50)


def get_tag_value(tags, tag_name, index=1, default=""):
    """Extract a value from a Nostr event's tags array.

    e.g. get_tag_value(event["tags"], "e") returns the parent event id.
    """
    for tag in tags:
        if tag and len(tag) > index and tag[0] == tag_name:
            return tag[index]
    return default


DEFAULT_RELAYS = ["wss://nos.lol", "wss://relay.iyou.me", "ws://127.0.0.1:9003"]

CURATED_AUTHORS = [
    "3bf0c63fcb93463407af97a5e5ee64fa883d107ef9e558472c4eb9aaaefa459d",
    "32e1827635450ebb3c5a7d12c1f8e7b2b514439ac10a67eef3d9fd9c5c68e245",
]


def _connect_relay(relay_url, sub_id, filter_obj, timeout):
    """Connect to a single relay and fetch events."""
    events = {}
    done = threading.Event()

    def on_open(ws):
        ws.send(json.dumps(["REQ", sub_id, filter_obj]))

    def on_message(ws, raw):
        try:
            msg = json.loads(raw)
            if msg[0] == "EVENT" and msg[1] == sub_id:
                e = msg[2]
                if e.get("id") and e["id"] not in events:
                    events[e["id"]] = e
            elif msg[0] == "EOSE":
                done.set()
        except Exception:
            pass

    def on_error(ws, err):
        done.set()

    def on_close(ws, status, msg):
        done.set()

    ws = WebSocketApp(
        relay_url,
        on_open=on_open,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close,
    )

    try:
        t = threading.Thread(
            target=ws.run_forever,
            kwargs={"sslopt": {"cert_reqs": ssl.CERT_NONE}},
            daemon=True,
        )
        t.start()
        done.wait(timeout=timeout)
        ws.close()
    except Exception as e:
        print(f"_connect_relay error on {relay_url}: {e}")

    return events


def relay_req(filter_obj, sub_id=None, timeout=10, relay_urls=None):
    """Try multiple relays, return events from first responsive one."""
    if sub_id is None:
        sub_id = "wun_" + str(int(time.time() * 1000000))[-8:]

    if relay_urls is None:
        relay_urls = DEFAULT_RELAYS

    for relay_url in relay_urls:
        events = _connect_relay(relay_url, sub_id, filter_obj, timeout)
        if events:
            return events

    return {}


def process_into_feed(raw_events, profiles=None, max_items=50, use_thread_tree=True):
    """Convert raw Nostr events into a structured, threaded feed.

    When use_thread_tree=True (default), delegates to the NIP-10 thread
    tree builder for proper threaded display. Reactions and votes are
    still attached in a flat pass. Falls back to flat grouping when
    use_thread_tree=False.

    Returns a dict:
        {
          "roots":       [ note, ... ],
          "replies":     { parent_id: [note, ...] },
          "total_replies": int,
          "flat":        [ note, ... ],   # legacy flat list (deprecated)
        }
    """
    if profiles is None:
        profiles = {}

    from .nip10 import build_thread_tree, parse_nip10_tags
    from datetime import datetime

    def _ts_to_dt(ts):
        if isinstance(ts, datetime):
            return ts
        return datetime.fromtimestamp(ts or 0)

    def enrich_item(pk):
        prof = profiles.get(pk, {})
        return {
            "author_name": prof.get("display_name") or prof.get("name") or "",
            "author_avatar": prof.get("picture", ""),
        }

    # Classify events by kind
    kind_1 = {}
    kind_1063 = {}
    kind_30023 = {}
    reactions = []
    kind_1111_events = {}
    votes = []

    for eid, e in raw_events.items():
        kind = e.get("kind")
        if kind == 1:
            kind_1[eid] = e
        elif kind == 1063:
            kind_1063[eid] = e
        elif kind == 30023:
            kind_30023[eid] = e
        elif kind == 7:
            reactions.append(e)
        elif kind == 1111:
            kind_1111_events[eid] = e
        elif kind == 1112:
            votes.append(e)

    # Build thread tree from Kind 1111 replies + root events
    all_thread_events = {}
    all_thread_events.update(kind_1)
    all_thread_events.update(kind_1063)
    all_thread_events.update(kind_30023)
    all_thread_events.update(kind_1111_events)

    tree = build_thread_tree(all_thread_events, profiles)
    roots = tree["roots"]
    reply_map = tree["replies_by_parent"]

    # Attach reactions to all root events (deduplicated by pubkey)
    seen_reactions = set()
    root_by_id = {r["id"]: r for r in roots}

    # Also index non-thread roots (Kind 1, 1063, 30023 that have no
    # replies but are still root-level content)
    for kind_dict in (kind_1, kind_1063, kind_30023):
        for eid, e in kind_dict.items():
            if eid not in root_by_id:
                from .nip10 import _enrich_root
                r = _enrich_root(e, e.get("kind"), profiles, _ts_to_dt)
                root_by_id[eid] = r
                roots.append(r)

    for r_raw in reactions:
        tags = r_raw.get("tags", [])
        parent_id = get_tag_value(tags, "e")
        if parent_id in root_by_id:
            pk = r_raw.get("pubkey", "")
            key = (parent_id, pk)
            if key in seen_reactions:
                continue
            seen_reactions.add(key)
            item = {
                "id": r_raw.get("id", ""),
                "kind": 7,
                "pubkey": pk,
                "content": r_raw.get("content", ""),
                "created_at": _ts_to_dt(r_raw.get("created_at", 0)),
            }
            item.update(enrich_item(pk))
            root_by_id[parent_id].setdefault("reactions", []).append(item)

    # Attach votes to root polls
    for v_raw in votes:
        tags = v_raw.get("tags", [])
        parent_id = get_tag_value(tags, "e")
        if parent_id in root_by_id:
            item = {
                "id": v_raw.get("id", ""),
                "kind": 1112,
                "pubkey": v_raw.get("pubkey", ""),
                "content": v_raw.get("content", ""),
                "created_at": _ts_to_dt(v_raw.get("created_at", 0)),
            }
            root_by_id[parent_id].setdefault("votes", []).append(item)

    # Add orphan Kind 1111 replies as standalone root items
    for pid, replies in reply_map.items():
        if pid not in root_by_id:
            for reply_note in replies:
                reply_note["reactions"] = []
                reply_note["reply_count"] = 0
                reply_note["replies"] = []
                root_by_id[reply_note["id"]] = reply_note
                roots.append(reply_note)

    roots.sort(key=lambda x: x["created_at"], reverse=True)

    return {
        "roots": roots[:max_items],
        "replies": reply_map,
        "total_replies": tree["total_reply_count"],
        "flat": [],  # deprecated — kept for backward compat with /api/feed serializer
    }


def fetch_unified_feed(authors=None, limit=50, relay_urls=None):
    """Fetch multi-kind events from relay and resolve Kind 0 profiles.

    Phase 1: Fetch kinds [1, 7, 1063, 1111] with optional authors filter.
    Phase 2: Fetch Kind 0 metadata for all unique pubkeys discovered.
    Returns a structured feed with author_name/author_avatar populated.
    """
    filter_obj = {"kinds": [1, 7, 1063, 1111, 30023, 1112], "limit": limit}
    if authors:
        filter_obj["authors"] = authors

    raw_events = relay_req(filter_obj, relay_urls=relay_urls)

    pubkeys = set()
    for e in raw_events.values():
        pk = e.get("pubkey")
        if pk:
            pubkeys.add(pk)
        for tag in e.get("tags", []):
            if tag and tag[0] == "p" and len(tag) > 1:
                pubkeys.add(tag[1])

    profiles = {}
    if pubkeys:
        profile_events = relay_req(
            {"kinds": [0], "authors": list(pubkeys)[:100]},
            relay_urls=relay_urls,
        )
        for e in profile_events.values():
            pk = e.get("pubkey", "")
            try:
                profiles[pk] = json.loads(e.get("content", "{}"))
            except json.JSONDecodeError:
                profiles[pk] = {}

    return process_into_feed(raw_events, profiles, max_items=limit)


def fetch_contact_pubkeys(user_pubkey, relay_urls=None):
    """Fetch Kind 3 (Contact List) for a user and return followed pubkeys."""
    events = relay_req({"kinds": [3], "authors": [user_pubkey], "limit": 1}, relay_urls=relay_urls)
    for e in events.values():
        tags = e.get("tags", [])
        return [tag[1] for tag in tags if tag and tag[0] == "p" and len(tag) > 1]
    return []


class GalleryView(TemplateView):
    template_name = "gallery.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user_pubkey = did_to_pubkey(self.request.user.username) if self.request.user.is_authenticated else ""
        relays = self.request.session.get("relays", DEFAULT_RELAYS)
        context["user_pubkey"] = user_pubkey
        context["user_did"] = self.request.user.username if self.request.user.is_authenticated else ""

        filter_pubkey = self.request.GET.get("pubkey")
        media_type = self.request.GET.get("type", "all")
        authors = [filter_pubkey] if filter_pubkey else None
        notes = fetch_media_assets(authors=authors, relay_urls=relays)

        images = [n for n in notes if n["media_type"] == "image"]
        videos = [n for n in notes if n["media_type"] == "video"]
        audio = [n for n in notes if n["media_type"] == "audio"]
        other = [n for n in notes if n["media_type"] == "other"]

        context["notes"] = notes
        context["images"] = images
        context["videos"] = videos
        context["audio_items"] = audio
        context["other_items"] = other
        context["filter_pubkey"] = filter_pubkey
        context["active_type"] = media_type
        context["counts"] = {
            "all": len(notes),
            "images": len(images),
            "videos": len(videos),
            "audio": len(audio),
        }
        return context


class ProfileView(TemplateView):
    template_name = "profile.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        npub = kwargs.get("npub")
        hex_pubkey = npub_to_hex(npub)
        context["hex_pubkey"] = hex_pubkey
        context["npub"] = npub

        if not hex_pubkey:
            context["error"] = f"Invalid npub: {npub}"
            return context

        profile = fetch_profile_data(hex_pubkey)
        context["profile"] = profile

        broadcasts = fetch_text_notes(authors=[hex_pubkey])
        context["broadcasts"] = broadcasts

        media = fetch_media_assets(authors=[hex_pubkey])
        context["media"] = media

        sovereign_score = sum(1 for m in media if m.get("is_sovereign"))
        context["sovereign_score"] = sovereign_score

        return context


def hex_to_npub(hex_pubkey):
    """Convert hex pubkey to NIP-19 npub format."""
    try:
        # Convert hex to bytes
        data = bytes.fromhex(hex_pubkey)
        # Encode using bech32
        converted = bech32.bech32_encode("npub", bech32.convertbits(data, 8, 5))
        return converted
    except Exception:
        return hex_pubkey[:12] + "..."  # Fallback to truncated hex


def did_to_pubkey(did):
    """Extract Nostr hex pubkey from a DID (did:key:z6Mk...).

    DID format: did:key:z6MkqRYqQ273hve3ZxTj1T51G5R163z6Fy2Sx8qYm7tK
    The part after 'z' is base64url-encoded multibase.
    We decode it and convert to hex.
    """
    if not did or not did.startswith("did:key:z"):
        return None

    try:
        # Extract the multibase part (after z)
        encoded = did.split("z")[1]

        # Decode base64url (multibase)
        # Add padding if needed
        padding = 4 - len(encoded) % 4
        if padding != 4:
            encoded += "=" * padding

        # Convert from base64url to standard base64
        decoded_bytes = base64.urlsafe_b64decode(encoded)

        # Convert to hex
        hex_pubkey = decoded_bytes.hex()

        # Nostr pubkeys are 32 bytes (64 hex chars) for secp256k1
        # DID keys might have a prefix byte, so we take the last 32 bytes
        if len(decoded_bytes) > 32:
            hex_pubkey = decoded_bytes[-32:].hex()

        return hex_pubkey
    except Exception as e:
        print(f"Error converting DID to pubkey: {e}")
        return None


def did_to_npub(did):
    """Convert DID directly to npub format."""
    hex_pubkey = did_to_pubkey(did)
    if hex_pubkey:
        return hex_to_npub(hex_pubkey)
    return None


@login_required
@csrf_exempt
def api_cast_vote(request):
    if request.method != "POST":
        return JsonResponse({"valid": False, "error": "POST required"}, status=405)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return HttpResponseBadRequest(json.dumps({"valid": False, "error": "invalid JSON"}))

    voter_did = data.get("voter_did")
    signature = data.get("signature")
    vote_envelope = data.get("vote_envelope")

    if not voter_did or not signature or not vote_envelope:
        return JsonResponse(
            {"valid": False, "error": "voter_did, signature, and vote_envelope required"},
            status=400,
        )

    poll_id = vote_envelope.get("poll_id")

    proxy_payload = {
        "voter_did": voter_did,
        "signature": signature,
        "vote_envelope": vote_envelope,
        "proxy": "iyou_wun",
    }

    try:
        client = PolyClient()
        result = client.cast_vote(poll_id, proxy_payload)
        return JsonResponse({"valid": True, **result})
    except PolyConnectionError as exc:
        return JsonResponse({"valid": False, "error": str(exc)}, status=502)


DID_PATTERN = re.compile(r"^did:[a-z0-9]+:.*")


@method_decorator(login_required, name="dispatch")
class IssueCredentialView(View):
    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_staff:
            return JsonResponse(
                {"error": "administrator privileges required"},
                status=403,
            )
        return super().dispatch(request, *args, **kwargs)

    def post(self, request):
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse(
                {"error": "invalid JSON body"}, status=400
            )

        voter_did = data.get("voter_did")
        credential_type = data.get("credential_type")
        fidelity_score = data.get("fidelity_score")

        if not voter_did or not credential_type or fidelity_score is None:
            return JsonResponse(
                {
                    "error": "voter_did, credential_type, and fidelity_score are required"
                },
                status=400,
            )

        if not isinstance(fidelity_score, int) or not (0 <= fidelity_score <= 100):
            return JsonResponse(
                {"error": "fidelity_score must be an integer between 0 and 100"},
                status=400,
            )

        if not DID_PATTERN.match(voter_did):
            return JsonResponse(
                {"error": f"voter_did is not a valid DID: {voter_did}"},
                status=400,
            )

        signed_vc = issue_vc(voter_did, credential_type, fidelity_score)

        IssuedCredential.objects.create(
            subject_did=voter_did,
            credential_type=credential_type,
            vc_id=signed_vc["id"],
        )

        return JsonResponse(signed_vc, status=201)

    def get(self, request):
        return JsonResponse({"error": "POST required"}, status=405)


@require_GET
def node_config(request):
    pubkey_hex = get_public_key_hex(get_node_signing_key())
    return JsonResponse({
        "node_did": settings.NODE_DID,
        "node_public_key_hex": pubkey_hex,
        "supported_credentials": ["voter_credential"],
    })
