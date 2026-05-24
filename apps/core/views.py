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
import ssl
import threading
import time
from datetime import datetime

import bech32
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from urllib.parse import urlencode
from django.http import JsonResponse, HttpResponseBadRequest
from django.shortcuts import redirect, render
from django.views.decorators.csrf import csrf_exempt
from django.views.generic import TemplateView
from websocket import WebSocketApp

from services.poly_client import PolyClient, PolyConnectionError


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
            notes = fetch_thread(thread_id, relay_urls=relays)
            context["thread_mode"] = True
            context["feed_mode"] = "thread"
        else:
            mode = self.request.GET.get("mode", "network")
            context["feed_mode"] = mode

            if mode == "network" and user_pubkey:
                contacts = fetch_contact_pubkeys(user_pubkey, relay_urls=relays)
                if contacts:
                    notes = fetch_unified_feed(authors=contacts, relay_urls=relays)
                else:
                    notes = fetch_unified_feed(authors=CURATED_AUTHORS, relay_urls=relays)
            else:
                notes = fetch_unified_feed(relay_urls=relays)

        context["notes"] = notes

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

    notes = process_into_feed(raw_events, profiles, max_items=limit)

    def _serialize(note):
        result = dict(note)
        result["created_at"] = note["created_at"].timestamp()
        if note.get("comments"):
            result["comments"] = [_serialize(c) for c in note["comments"]]
        if note.get("reactions"):
            result["reactions"] = [{"id": r["id"], "pubkey": r["pubkey"], "content": r["content"]} for r in note["reactions"]]
        return result

    return JsonResponse({"notes": [_serialize(n) for n in notes]})


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
            "nip05": content.get("nip05", ""),
            "lud16": content.get("lud16", ""),
        }
    return {}


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
        result.append({
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
            "alt_text": get_tag_value(tags, "alt"),
            "is_sovereign": bool(file_url and "127.0.0.1" in file_url),
            "author_name": profile.get("display_name") or profile.get("name") or "",
            "author_avatar": profile.get("picture", ""),
        })

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
    """Fetch a parent event and its comments, return structured feed list."""
    parent_raw = relay_req({"ids": [parent_id], "limit": 1}, relay_urls=relay_urls)
    if not parent_raw:
        return []

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


RELAY_URL = "wss://nos.lol"

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


def process_into_feed(raw_events, profiles=None, max_items=50):
    """Convert raw Nostr events into a structured, grouped feed.

    Groups Kind 7 (reactions) and Kind 1111 (comments) under their
    parent Kind 1 or Kind 1063 events. Injects author_name and
    author_avatar from Kind 0 profile data. Deduplicates reactions
    by pubkey per parent. Drops orphan Kind 7; allows orphan Kind 1111.

    Also handles Kind 30023 (Poll Definitions) and Kind 1112 (Vote
    Envelopes) for the Poly governance integration.
    """
    if profiles is None:
        profiles = {}

    kind_1 = {}
    kind_1063 = {}
    kind_30023 = {}
    reactions = []
    comments = []
    votes = []

    def enrich(item):
        pk = item.get("pubkey", "")
        profile = profiles.get(pk, {})
        item["author_name"] = profile.get("display_name") or profile.get("name") or ""
        item["author_avatar"] = profile.get("picture", "")
        return item

    for eid, e in raw_events.items():
        kind = e.get("kind")
        pubkey = e.get("pubkey", "")
        npub = hex_to_npub(pubkey) if pubkey else ""
        base = {
            "id": eid,
            "kind": kind,
            "pubkey": pubkey,
            "npub": npub,
            "content": e.get("content", ""),
            "created_at": datetime.fromtimestamp(e.get("created_at", 0)),
            "tags": e.get("tags", []),
        }

        if kind == 1:
            base["reactions"] = []
            base["comments"] = []
            kind_1[eid] = enrich(base)
        elif kind == 1063:
            base["reactions"] = []
            base["comments"] = []
            base["file_url"] = get_tag_value(base["tags"], "url")
            base["mime_type"] = get_tag_value(base["tags"], "m")
            base["dimensions"] = get_tag_value(base["tags"], "dim")
            base["thumbnail_url"] = get_tag_value(base["tags"], "thumb")
            base["alt_text"] = get_tag_value(base["tags"], "alt")
            base["is_sovereign"] = bool(
                base["file_url"] and "127.0.0.1" in base["file_url"]
            )
            kind_1063[eid] = enrich(base)
        elif kind == 30023:
            base["reactions"] = []
            base["comments"] = []
            base["poll_options"] = [
                tag[1] for tag in base["tags"]
                if tag and tag[0] == "option" and len(tag) > 1
            ]
            base["poll_scope_geohash"] = get_tag_value(base["tags"], "geohash")
            base["poll_scope_org"] = get_tag_value(base["tags"], "org")
            base["poll_closes_at"] = get_tag_value(base["tags"], "expires")
            kind_30023[eid] = enrich(base)
        elif kind == 7:
            reactions.append(base)
        elif kind == 1111:
            base["reactions"] = []
            base["comments"] = []
            comments.append(enrich(base))
        elif kind == 1112:
            votes.append(base)

    parent_lookup = {**kind_1, **kind_1063, **kind_30023}

    # Group reactions under parents, deduplicate by pubkey per parent
    seen_reactions = set()
    for r in reactions:
        parent_id = get_tag_value(r["tags"], "e")
        if parent_id not in parent_lookup:
            continue
        key = (parent_id, r["pubkey"])
        if key in seen_reactions:
            continue
        seen_reactions.add(key)
        parent_lookup[parent_id]["reactions"].append(r)

    # Group comments under parents; allow orphans as standalone items
    orphan_comments = []
    for c in comments:
        parent_id = get_tag_value(c["tags"], "e")
        if parent_id in parent_lookup:
            parent_lookup[parent_id]["comments"].append(c)
        else:
            orphan_comments.append(c)

    # Group votes under their parent poll
    for v in votes:
        parent_id = get_tag_value(v["tags"], "e")
        if parent_id in parent_lookup:
            parent_lookup[parent_id].setdefault("votes", []).append(v)

    feed = list(kind_1.values()) + list(kind_1063.values()) + list(kind_30023.values()) + orphan_comments
    feed.sort(key=lambda x: x["created_at"], reverse=True)

    return feed[:max_items]


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


class GalleryView(LoginRequiredMixin, TemplateView):
    template_name = "gallery.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user_pubkey = did_to_pubkey(self.request.user.username)
        relays = self.request.session.get("relays", DEFAULT_RELAYS)
        context["user_pubkey"] = user_pubkey
        context["user_did"] = self.request.user.username

        filter_pubkey = self.request.GET.get("pubkey")
        authors = [filter_pubkey] if filter_pubkey else None
        notes = fetch_media_assets(authors=authors, relay_urls=relays)
        context["notes"] = notes
        context["filter_pubkey"] = filter_pubkey
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
