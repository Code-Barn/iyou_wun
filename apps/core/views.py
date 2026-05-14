import base64
import json
import ssl
import threading
import time
from datetime import datetime

import bech32
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect, render
from django.views.generic import TemplateView
from websocket import WebSocketApp


def home(request):
    print(f"DEBUG: Middleware check - User in request: {request.user}")
    print(f"DEBUG: Cookies received at index: {request.COOKIES.keys()}")
    print(
        f"DEBUG: Session user at index: {request.user}, Authenticated: {request.user.is_authenticated}"
    )
    print(
        f"!!! ACCESSING HOME - USER: {request.user} - AUTH: {request.user.is_authenticated} !!!"
    )
    if hasattr(request, "session"):
        print(f"DEBUG: Session ID: {request.session.session_key}")
        print(f"DEBUG: Session data: {dict(request.session)}")
    else:
        print("DEBUG: No session object found!")

    if not request.user.is_authenticated:
        print(
            f"DEBUG: HOME VIEW - SESSION_KEY: {request.session.session_key if hasattr(request, 'session') else 'NO_SESSION'}"
        )
        print(f"DEBUG: ALL COOKIES AT HOME: {request.COOKIES}")

    if request.user.is_authenticated:
        return redirect("feed")
    return render(request, "home.html")


@login_required
def dashboard(request):
    user_pubkey = did_to_pubkey(request.user.username)
    user_npub = did_to_npub(request.user.username)
    profile = fetch_profile_data(user_pubkey) if user_pubkey else {}
    return render(request, "dashboard.html", {
        "user_pubkey": user_pubkey,
        "user_npub": user_npub,
        "user_did": request.user.username,
        "profile": profile,
    })


class FeedView(LoginRequiredMixin, TemplateView):
    template_name = "feed.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        print(f"DEBUG: Rendering feed for user {self.request.user}")

        user_pubkey = did_to_pubkey(self.request.user.username)
        user_npub = did_to_npub(self.request.user.username)

        context["user_pubkey"] = user_pubkey
        context["user_npub"] = user_npub
        context["user_did"] = self.request.user.username

        mode = self.request.GET.get("mode", "network")
        context["feed_mode"] = mode

        if mode == "network" and user_pubkey:
            contacts = fetch_contact_pubkeys(user_pubkey)
            if contacts:
                notes = fetch_unified_feed(authors=contacts)
            else:
                notes = fetch_unified_feed(authors=CURATED_AUTHORS)
        else:
            notes = fetch_unified_feed()

        context["notes"] = notes

        return context

    def get(self, request, *args, **kwargs):
        # Add welcome message for first-time users
        if not request.session.get("has_seen_feed_welcome", False):
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


def fetch_profile_data(hex_pubkey):
    """Fetch Kind 0 profile metadata for a pubkey."""
    events = relay_req({"kinds": [0], "authors": [hex_pubkey], "limit": 1})
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


def fetch_media_assets(authors=None, limit=50):
    """Fetch only Kind 1063 media events, flat sorted list."""
    filter_obj = {"kinds": [1063], "limit": limit}
    if authors:
        filter_obj["authors"] = authors

    raw_events = relay_req(filter_obj)
    if not raw_events:
        return []

    pubkeys = set()
    for e in raw_events.values():
        pk = e.get("pubkey")
        if pk:
            pubkeys.add(pk)

    profiles = {}
    if pubkeys:
        profile_events = relay_req({"kinds": [0], "authors": list(pubkeys)[:100]})
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


def fetch_text_notes(authors=None, limit=20):
    """Fetch Kind 1 text notes for given authors, with profile enrichment."""
    filter_obj = {"kinds": [1], "limit": limit}
    if authors:
        filter_obj["authors"] = authors

    raw_events = relay_req(filter_obj)
    if not raw_events:
        return []

    pubkeys = set()
    for e in raw_events.values():
        pk = e.get("pubkey")
        if pk:
            pubkeys.add(pk)

    profiles = {}
    if pubkeys:
        profile_events = relay_req({"kinds": [0], "authors": list(pubkeys)[:100]})
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


def get_tag_value(tags, tag_name, index=1, default=""):
    """Extract a value from a Nostr event's tags array.

    e.g. get_tag_value(event["tags"], "e") returns the parent event id.
    """
    for tag in tags:
        if tag and len(tag) > index and tag[0] == tag_name:
            return tag[index]
    return default


RELAY_URL = "wss://nos.lol"

CURATED_AUTHORS = [
    "3bf0c63fcb93463407af97a5e5ee64fa883d107ef9e558472c4eb9aaaefa459d",
    "32e1827635450ebb3c5a7d12c1f8e7b2b514439ac10a67eef3d9fd9c5c68e245",
]


def relay_req(filter_obj, sub_id=None, timeout=10):
    """Open a WebSocket to the relay, send a Nostr REQ, collect events until EOSE or timeout."""
    if sub_id is None:
        sub_id = "wun_" + str(int(time.time() * 1000000))[-8:]

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
        RELAY_URL,
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
        print(f"relay_req error: {e}")

    return events


def process_into_feed(raw_events, profiles=None, max_items=50):
    """Convert raw Nostr events into a structured, grouped feed.

    Groups Kind 7 (reactions) and Kind 1111 (comments) under their
    parent Kind 1 or Kind 1063 events. Injects author_name and
    author_avatar from Kind 0 profile data. Deduplicates reactions
    by pubkey per parent. Drops orphan Kind 7; allows orphan Kind 1111.
    """
    if profiles is None:
        profiles = {}

    kind_1 = {}
    kind_1063 = {}
    reactions = []
    comments = []

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
        elif kind == 7:
            reactions.append(base)
        elif kind == 1111:
            base["reactions"] = []
            base["comments"] = []
            comments.append(enrich(base))

    parent_lookup = {**kind_1, **kind_1063}

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

    feed = list(kind_1.values()) + list(kind_1063.values()) + orphan_comments
    feed.sort(key=lambda x: x["created_at"], reverse=True)

    return feed[:max_items]


def fetch_unified_feed(authors=None, limit=50):
    """Fetch multi-kind events from relay and resolve Kind 0 profiles.

    Phase 1: Fetch kinds [1, 7, 1063, 1111] with optional authors filter.
    Phase 2: Fetch Kind 0 metadata for all unique pubkeys discovered.
    Returns a structured feed with author_name/author_avatar populated.
    """
    filter_obj = {"kinds": [1, 7, 1063, 1111], "limit": limit}
    if authors:
        filter_obj["authors"] = authors

    raw_events = relay_req(filter_obj)

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
            {"kinds": [0], "authors": list(pubkeys)[:100]}
        )
        for e in profile_events.values():
            pk = e.get("pubkey", "")
            try:
                profiles[pk] = json.loads(e.get("content", "{}"))
            except json.JSONDecodeError:
                profiles[pk] = {}

    return process_into_feed(raw_events, profiles, limit)


def fetch_contact_pubkeys(user_pubkey):
    """Fetch Kind 3 (Contact List) for a user and return followed pubkeys."""
    events = relay_req({"kinds": [3], "authors": [user_pubkey], "limit": 1})
    for e in events.values():
        tags = e.get("tags", [])
        return [tag[1] for tag in tags if tag and tag[0] == "p" and len(tag) > 1]
    return []


class GalleryView(LoginRequiredMixin, TemplateView):
    template_name = "gallery.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user_pubkey = did_to_pubkey(self.request.user.username)
        context["user_pubkey"] = user_pubkey
        context["user_did"] = self.request.user.username

        filter_pubkey = self.request.GET.get("pubkey")
        authors = [filter_pubkey] if filter_pubkey else None
        notes = fetch_media_assets(authors=authors)
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
