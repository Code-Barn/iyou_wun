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
import hashlib
import json
import logging
import re
import ssl
import threading
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timedelta

import bech32
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import IntegrityError, transaction
from django.db.models import Max, Q
from django.http import HttpResponsePermanentRedirect, HttpResponseBadRequest, Http404, JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET
from django.views.generic import TemplateView
from django.views import View
from websocket import WebSocketApp

from services.poly_client import PolyClient, PolyConnectionError

from .did_kit import get_node_signing_key, get_public_key_hex, issue_vc
from .models import HandleVerificationChallenge, IssuedCredential, UserLinkDeck, UserLinkItem
from .utils import validate_external_bio_url, verify_external_profile_token

logger = logging.getLogger(__name__)
UserModel = get_user_model()


def get_relays_for_request(request=None):
    """Retrieve default relays, omitting unencrypted ws:// if request is served over HTTPS."""
    relays = DEFAULT_RELAYS
    if request and hasattr(request, "session"):
        relays = request.session.get("relays", DEFAULT_RELAYS)

    if request:
        is_https = request.is_secure() or request.META.get("HTTP_X_FORWARDED_PROTO") == "https"
        if is_https:
            relays = [r for r in relays if not r.startswith("ws://")]
    return relays


def home(request):
    return redirect("feed")


@login_required
def dashboard(request):
    user_pubkey = did_to_pubkey(request.user.username)
    user_npub = did_to_npub(request.user.username)
    relays = get_relays_for_request(request)
    profile = fetch_profile_data(user_pubkey, relay_urls=relays) if user_pubkey else {}
    deck = UserLinkDeck.objects.filter(user=request.user).first()
    return render(request, "dashboard.html", {
        "user_pubkey": user_pubkey,
        "user_npub": user_npub,
        "user_did": request.user.username,
        "profile": profile,
        "relays": relays,
        "deck": deck,
    })


def calculate_trending_tags(notes, scope="global"):
    """
    Calculate top trending hashtags across notes stream with support for iyou/global scopes.
    Extracts explicit #t tags and inline #hashtag tokens from note content.
    Returns top 4 tags formatted with count and scope metadata.
    """
    if not notes:
        return []

    from collections import Counter
    import re

    # 1. Author filtering for iyou scope
    filtered_notes = []
    if scope == "iyou":
        try:
            iyou_usernames = set(UserLinkDeck.objects.values_list("user__username", flat=True))
        except Exception:
            iyou_usernames = set()

        iyou_keys = set()
        for u in iyou_usernames:
            if u:
                iyou_keys.add(u.lower())
                pk = did_to_pubkey(u)
                if pk:
                    iyou_keys.add(pk.lower())
                try:
                    np = hex_to_npub(pk or u)
                    if np:
                        iyou_keys.add(np.lower())
                except Exception:
                    pass

        for n in notes:
            if not isinstance(n, dict):
                continue
            pk = str(n.get("pubkey") or n.get("pubkey_hex") or "").lower()
            did = str(n.get("author_did") or "").lower()
            npub = str(n.get("npub") or "").lower()
            if pk in iyou_keys or did in iyou_keys or npub in iyou_keys:
                filtered_notes.append(n)
    else:
        filtered_notes = [n for n in notes if isinstance(n, dict)]

    # 2. Extract tags & inline hashtags
    tag_counts = Counter()
    for n in filtered_notes:
        seen_in_note = set()
        # Tags array
        tags = n.get("tags") or []
        for t in tags:
            if isinstance(t, (list, tuple)) and len(t) > 1 and t[0] == "t" and t[1]:
                tag_val = str(t[1]).strip().lstrip("#").lower()
                if tag_val and tag_val not in seen_in_note:
                    seen_in_note.add(tag_val)
                    tag_counts[tag_val] += 1

        # Content regex for #hashtags
        content = str(n.get("content") or n.get("display_content") or "")
        for match in re.findall(r"#([a-zA-Z0-9_\-]+)", content):
            tag_val = match.strip().lower()
            if tag_val and tag_val not in seen_in_note:
                seen_in_note.add(tag_val)
                tag_counts[tag_val] += 1

    CATEGORY_MAP = {
        "bitcoin": "Finance & Sovereign Capital",
        "btc": "Finance & Sovereign Capital",
        "sats": "Finance & Sovereign Capital",
        "crypto": "Cryptography & ZK",
        "nostr": "Protocol & Relays",
        "mesh": "Protocol & Relays",
        "relay": "Protocol & Relays",
        "nip10": "Protocol & Relays",
        "iyou": "Ecosystem & Identity",
        "wine": "Agriculture & Viticulture",
    }

    top_tags = []
    for name, count in tag_counts.most_common(4):
        category = CATEGORY_MAP.get(name, "General & Sovereign Mesh")
        top_tags.append({
            "name": name,
            "count": count,
            "scope": scope,
            "category": category,
        })

    return top_tags


class FeedView(TemplateView):
    template_name = "feed.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        user_pubkey = did_to_pubkey(self.request.user.username) if self.request.user.is_authenticated else None
        user_npub = did_to_npub(self.request.user.username) if self.request.user.is_authenticated else None
        relays = get_relays_for_request(self.request)

        context["user_pubkey"] = user_pubkey
        context["user_npub"] = user_npub
        context["user_did"] = self.request.user.username if self.request.user.is_authenticated else None
        context["relays_json"] = json.dumps(relays)
        context["relays"] = relays
        context["relay_count"] = len(relays)
        context["user_credentials"] = {}
        context["og_image"] = og_fallback_image(self.request)


        thread_id = self.request.GET.get("thread") or self.request.GET.get("note") or self.request.GET.get("e")
        context["thread_id"] = thread_id

        if thread_id:
            thread_data = fetch_thread(thread_id, relay_urls=relays)
            context["thread_mode"] = True
            context["feed_mode"] = "thread"
            context["thread_root"] = thread_data.get("thread_root") or {}
            context["ancestors"] = thread_data.get("ancestors", [])
            context["notes"] = []  # Empty so flat feed loop never executes in thread mode
            context["thread_replies"] = thread_data.get("replies", {})
            context["thread_reply_count"] = thread_data.get("total_replies", 0)
            context["oldest_timestamp"] = None
        else:
            circle = self.request.GET.get("circle") or self.request.GET.get("mode") or "global"
            context["feed_mode"] = circle
            context["feed_circle"] = circle

            if circle in ("following", "network") and user_pubkey:
                contacts = fetch_contact_pubkeys(user_pubkey, relay_urls=relays)
                if contacts:
                    feed_data = fetch_unified_feed(authors=contacts, relay_urls=relays)
                else:
                    feed_data = fetch_unified_feed(authors=CURATED_AUTHORS, relay_urls=relays)
            elif circle in ("following", "network") and not user_pubkey:
                feed_data = fetch_unified_feed(authors=CURATED_AUTHORS, relay_urls=relays)
            else:
                feed_data = fetch_unified_feed(relay_urls=relays)

            notes = feed_data["roots"]
            notes = attach_social_counts(notes, relay_urls=relays)
            timestamps = []
            for n in notes:
                ts = n.get("created_at")
                if isinstance(ts, datetime):
                    epoch = int(ts.timestamp())
                elif isinstance(ts, (int, float)):
                    epoch = int(ts)
                else:
                    epoch = None
                if epoch is not None:
                    n["created_at_epoch"] = epoch
                    timestamps.append(epoch)

            context["notes"] = notes
            context["thread_replies"] = feed_data["replies"]
            context["thread_reply_count"] = feed_data["total_replies"]
            context["oldest_timestamp"] = min(timestamps) if timestamps else None

        creators_qs = (
            UserLinkDeck.objects.filter(is_public=True)
            .exclude(handle="")
            .order_by("-is_verified", "-created_at")
        )
        if self.request.user.is_authenticated:
            creators_qs = creators_qs.exclude(user=self.request.user)
        context["suggested_creators"] = list(creators_qs[:4])

        notes_for_trending = context.get("notes") or []
        trending_iyou = calculate_trending_tags(notes_for_trending, scope="iyou")
        trending_global = calculate_trending_tags(notes_for_trending, scope="global")

        default_iyou = [
            {"name": "nostr", "category": "Protocol & Relays", "count": "1.2k", "scope": "iyou"},
            {"name": "sovereign", "category": "Identity & Keys", "count": "840", "scope": "iyou"},
            {"name": "iyou", "category": "Ecosystem & Mesh", "count": "450", "scope": "iyou"},
            {"name": "bitcoin", "category": "Finance & Sovereign Capital", "count": "320", "scope": "iyou"},
        ]
        default_global = [
            {"name": "bitcoin", "category": "Finance & Sovereign Capital", "count": "1.4k", "scope": "global"},
            {"name": "nostr", "category": "Protocol & Relays", "count": "920", "scope": "global"},
            {"name": "wine", "category": "Agriculture & Viticulture", "count": "312", "scope": "global"},
            {"name": "crypto", "category": "Cryptography & ZK", "count": "280", "scope": "global"},
        ]

        context["trending_tags_iyou"] = trending_iyou if trending_iyou else default_iyou
        context["trending_tags_global"] = trending_global if trending_global else default_global
        context["trending_tags"] = context["trending_tags_iyou"]

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
        is_auth = self.request.user.is_authenticated
        user_pubkey = did_to_pubkey(self.request.user.username) if is_auth else ""
        context["user_pubkey"] = user_pubkey
        context["user_did"] = self.request.user.username if is_auth else ""

        level = getattr(settings, "WUN_USER_LEVEL", "2")
        context["user_level"] = level
        if level == "1":
            xmpp_domain = "iyou.me"
            xmpp_ws_url = "wss://xmpp.iyou.me:5222/xmpp-websocket"
        else:
            xmpp_domain = "127.0.0.1"
            xmpp_ws_url = "wss://home.iyou.me:5222/xmpp-websocket"

        context["xmpp_domain"] = xmpp_domain
        context["xmpp_ws_url"] = xmpp_ws_url
        context["xmpp_bosh_url"] = getattr(settings, "XMPP_BOSH_URL", "")

        user_jid = ""
        if user_pubkey:
            user_jid = f"{user_pubkey}@{xmpp_domain}"
        elif is_auth and self.request.user.username:
            user_jid = f"{self.request.user.username}@{xmpp_domain}"

        xmpp_token = getattr(settings, "XMPP_PASSWORD", "") or user_pubkey
        context["user_jid"] = user_jid
        context["xmpp_token"] = xmpp_token
        context["xmpp_password"] = xmpp_token
        return context




@login_required
@csrf_exempt
def api_relays(request):
    if request.method == 'GET':
        relays = get_relays_for_request(request)
        return JsonResponse({'relays': relays})
    data = json.loads(request.body)
    relays = data.get('relays', DEFAULT_RELAYS)
    request.session['relays'] = relays
    return JsonResponse({'relays': relays})


def api_search(request):
    """Progressive multi-tier search endpoint returning matching profiles and hashtags."""
    q = request.GET.get("q", "").strip()
    limit_raw = request.GET.get("limit", 6)

    try:
        limit = max(1, min(int(limit_raw), 20))
    except (ValueError, TypeError):
        limit = 6

    if not q:
        return JsonResponse({
            "success": True,
            "query": "",
            "counts": {"profiles": 0, "tags": 0},
            "results": {
                "profiles": [],
                "tags": [],
            },
        })

    clean_tag = q.lstrip("#").strip()

    # 1. Profiles Query (UserLinkDeck) - database-agnostic lookups
    profile_filter = (
        Q(handle__icontains=clean_tag)
        | Q(display_name__icontains=clean_tag)
        | Q(nip05__icontains=clean_tag)
        | Q(headline__icontains=clean_tag)
    )
    matching_decks = (
        UserLinkDeck.objects.filter(is_public=True)
        .filter(profile_filter)
        .order_by("-is_verified", "handle")[:limit]
    )

    profiles_data = []
    for deck in matching_decks:
        profiles_data.append({
            "handle": deck.handle,
            "display_name": deck.display_name or deck.handle,
            "avatar_url": deck.avatar_url,
            "headline": deck.headline,
            "nip05": deck.nip05,
            "is_verified": deck.is_verified,
            "url": deck.canonical_path,
        })

    # 2. Hashtag Suggestions
    tags_data = []
    if clean_tag:
        clean_tag_lower = clean_tag.lower()
        tags_data.append({
            "tag": clean_tag_lower,
            "display_tag": f"#{clean_tag_lower}",
            "url": f"/feed?q=%23{clean_tag_lower}",
        })

        POPULAR_TAGS = ["nostr", "bitcoin", "mesh", "sovereign", "ai", "crypto", "dev", "gallery", "poly"]
        for ptag in POPULAR_TAGS:
            if clean_tag_lower in ptag and ptag != clean_tag_lower:
                tags_data.append({
                    "tag": ptag,
                    "display_tag": f"#{ptag}",
                    "url": f"/feed?q=%23{ptag}",
                })
                if len(tags_data) >= limit:
                    break

    return JsonResponse({
        "success": True,
        "query": q,
        "counts": {
            "profiles": len(profiles_data),
            "tags": len(tags_data),
        },
        "results": {
            "profiles": profiles_data,
            "tags": tags_data,
        },
    })


def api_feed(request):
    mode = request.GET.get("mode", "")
    circle = request.GET.get("circle") or mode or "global"
    until = request.GET.get("until")
    limit = request.GET.get("limit", 25)
    tag = request.GET.get("tag")

    try:
        limit = int(limit)
    except (ValueError, TypeError):
        limit = 25

    user_pubkey = did_to_pubkey(request.user.username) if (request.user and request.user.is_authenticated) else None
    relays = get_relays_for_request(request)


    filter_obj = {"kinds": [1, 7, 1063, 1111, 30023, 1112], "limit": limit}
    if until:
        try:
            filter_obj["until"] = int(until)
        except (ValueError, TypeError):
            pass

    if tag:
        clean_tag = tag.lstrip("#")
        filter_obj["#t"] = [clean_tag]

    if circle in ("following", "network") and user_pubkey:
        contacts = fetch_contact_pubkeys(user_pubkey, relay_urls=relays)
        if contacts:
            filter_obj["authors"] = contacts
        else:
            filter_obj["authors"] = CURATED_AUTHORS
    elif circle in ("following", "network") and not user_pubkey:
        filter_obj["authors"] = CURATED_AUTHORS

    raw_events = relay_req(filter_obj, relay_urls=relays)

    # Multi-relay event deduplication by ID
    deduped_events = {}
    if isinstance(raw_events, dict):
        for eid, e in raw_events.items():
            real_id = e.get("id") or eid
            if real_id and real_id not in deduped_events:
                deduped_events[real_id] = e
    elif isinstance(raw_events, list):
        for e in raw_events:
            real_id = e.get("id")
            if real_id and real_id not in deduped_events:
                deduped_events[real_id] = e
    raw_events = deduped_events

    pubkeys = set()
    for e in raw_events.values():
        pk = e.get("pubkey")
        if pk:
            pubkeys.add(pk)
        for t in e.get("tags", []):
            if t and t[0] == "p" and len(t) > 1:
                pubkeys.add(t[1])

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
            except (json.JSONDecodeError, TypeError):
                profiles[pk] = {}

    feed_data = process_into_feed(raw_events, profiles, max_items=limit)
    feed_data["roots"] = attach_social_counts(feed_data["roots"], relay_urls=relays)


    def _serialize(note):
        result = dict(note)
        dt = note.get("created_at")
        if isinstance(dt, datetime):
            epoch = int(dt.timestamp())
            formatted_date = dt.strftime("%b %d, %H:%M")
            iso_date = dt.isoformat()
        elif isinstance(dt, (int, float)):
            epoch = int(dt)
            dt_obj = datetime.fromtimestamp(epoch)
            formatted_date = dt_obj.strftime("%b %d, %H:%M")
            iso_date = dt_obj.isoformat()
        else:
            epoch = 0
            formatted_date = ""
            iso_date = ""

        result["created_at"] = epoch
        result["created_at_epoch"] = epoch
        result["created_at_formatted"] = formatted_date
        result["created_at_iso"] = iso_date

        result["pubkey_hex"] = note.get("pubkey_hex") or note.get("pubkey") or ""
        result["author_did"] = note.get("author_did") or ""
        result["is_sovereign"] = note.get("is_sovereign", False)
        result["nip05"] = note.get("nip05") or ""
        result["author_name"] = note.get("author_name") or ""
        result["author_avatar"] = note.get("author_avatar") or ""
        result["display_content"] = note.get("display_content", note.get("content", ""))
        result["media_attachments"] = [dict(m) for m in note.get("media_attachments", [])]
        result["media_url"] = note.get("media_url") or note.get("file_url") or ""
        result["mime_type"] = note.get("mime_type") or ""
        result["parent_id"] = note.get("parent_id") or ""
        result["reply_to_name"] = note.get("reply_to_name") or ""
        result["reply_to_npub"] = note.get("reply_to_npub") or ""
        result["repost_count"] = note.get("repost_count", 0)

        result["has_content_warning"] = bool(note.get("has_content_warning", False))
        result["warning_reason"] = note.get("warning_reason") or ""
        result["lang"] = note.get("lang") or "en"

        if note.get("votes"):
            result["votes"] = [dict(v) for v in note["votes"]]
        if note.get("reactions"):
            result["reactions"] = [{"id": r["id"], "pubkey": r["pubkey"], "content": r["content"]} for r in note["reactions"]]
        else:
            result["reactions"] = []
        if note.get("replies"):
            result["replies"] = [_serialize(r) for r in note["replies"]]
            result["reply_count"] = note.get("reply_count", 0)
        else:
            result["replies"] = []
            result["reply_count"] = note.get("reply_count", 0)
        return result

    roots = [_serialize(n) for n in feed_data["roots"]]

    # Serialize the flat reply map for JS client-side assembly
    replies_serialized = {}
    for pid, replies in feed_data.get("replies", {}).items():
        replies_serialized[pid] = [_serialize(r) for r in replies]

    oldest_timestamp = min((n["created_at_epoch"] for n in roots if n.get("created_at_epoch")), default=None)
    has_more = bool(roots and len(roots) > 0)

    trending_tags_iyou = calculate_trending_tags(feed_data["roots"], scope="iyou")
    trending_tags_global = calculate_trending_tags(feed_data["roots"], scope="global")

    return JsonResponse({
        "success": True,
        "notes": roots,
        "replies": replies_serialized,
        "total_replies": feed_data["total_replies"],
        "oldest_timestamp": oldest_timestamp,
        "has_more": has_more,
        "trending_tags_iyou": trending_tags_iyou,
        "trending_tags_global": trending_tags_global,
        "trending_tags": trending_tags_iyou or trending_tags_global,
    })


def api_save_profile(request):
    """Server-side profile save fallback endpoint for browser sessions."""
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)

    if not request.user.is_authenticated:
        return JsonResponse({"error": "Authentication required"}, status=401)

    try:
        data = json.loads(request.body) if request.body else {}
    except (json.JSONDecodeError, TypeError):
        data = request.POST.dict()

    name = data.get("name") or data.get("display_name", "")
    about = data.get("about", "")
    picture = data.get("picture", "")
    banner = data.get("banner", "")
    nip05 = data.get("nip05", "")
    lud16 = data.get("lud16", "")

    deck = UserLinkDeck.objects.filter(user=request.user).first()
    if deck:
        if name:
            deck.display_name = name[:100]
        if about is not None:
            deck.headline = about[:160]
        if picture is not None:
            deck.avatar_url = picture[:2048]
        if banner is not None:
            deck.banner_url = banner[:2048]
        if nip05 is not None:
            deck.nip05 = nip05[:300]
        if lud16 is not None:
            deck.lud16 = lud16[:300]
        deck.save(update_fields=["display_name", "headline", "avatar_url", "banner_url", "nip05", "lud16"])
    else:
        # Create deck if not exists with a safe default handle
        default_handle = request.user.username.split(":")[-1][:32] or "user"
        clean_handle = re.sub(r"[^a-z0-9_-]", "", default_handle.lower()) or "user"
        deck = UserLinkDeck.objects.create(
            user=request.user,
            handle=clean_handle[:32],
            display_name=name[:100],
            headline=about[:160],
            avatar_url=picture[:2048],
            banner_url=banner[:2048],
            nip05=nip05[:300],
            lud16=lud16[:300],
        )

    profile_data = {
        "name": deck.display_name or deck.handle or name,
        "display_name": deck.display_name or name,
        "about": deck.headline or about,
        "picture": deck.avatar_url or picture,
        "banner": deck.banner_url or banner,
        "nip05": deck.nip05 or nip05,
        "lud16": deck.lud16 or lud16,
    }
    request.session["user_profile_cache"] = profile_data

    return JsonResponse({
        "success": True,
        "message": "Profile saved successfully.",
        "profile": profile_data,
    })


def npub_to_hex(npub_str):
    """Convert npub1... to hex pubkey (also accepts hex or DID)."""
    if not npub_str or not isinstance(npub_str, str):
        return None
    clean = npub_str.strip()
    if re.match(r"^[0-9a-fA-F]{64}$", clean):
        return clean.lower()
    if clean.startswith("did:"):
        return did_to_pubkey(clean)
    try:
        hrp, data = bech32.bech32_decode(clean)
        if hrp != "npub" or data is None:
            return None
        decoded = bech32.convertbits(data, 5, 8, False)
        if decoded is None:
            return None
        return bytes(decoded).hex()
    except Exception:
        return None


def fetch_profile_data(hex_pubkey, relay_urls=None):
    """Fetch Kind 0 profile metadata for a pubkey across relays, picking latest, sanitizing URLs, and resolving local UserLinkDeck."""
    from .nip10 import sanitize_media_url

    # 1. Resolve local UserLinkDeck baseline if available
    local_deck = None
    if hex_pubkey:
        for deck in UserLinkDeck.objects.select_related("user").all():
            if did_to_pubkey(deck.user.username) == hex_pubkey or deck.user.username == hex_pubkey:
                local_deck = deck
                break

    profile = {}
    if local_deck:
        profile = {
            "name": getattr(local_deck, "display_name", "") or local_deck.handle or "",
            "display_name": getattr(local_deck, "display_name", "") or "",
            "about": local_deck.headline or "",
            "picture": sanitize_media_url(getattr(local_deck, "avatar_url", "")) if getattr(local_deck, "avatar_url", "") else "",
            "banner": sanitize_media_url(getattr(local_deck, "banner_url", "")) if getattr(local_deck, "banner_url", "") else "",
            "nip05": getattr(local_deck, "nip05", "") or "",
            "lud16": getattr(local_deck, "lud16", "") or "",
        }

    # 2. Query relays for Kind 0 metadata events
    events = relay_req({"kinds": [0], "authors": [hex_pubkey], "limit": 5}, relay_urls=relay_urls) if hex_pubkey else {}
    if not events:
        return profile

    raw_list = list(events.values()) if isinstance(events, dict) else (events if isinstance(events, list) else [])
    k0_events = [e for e in raw_list if e.get("kind") == 0]
    candidate_list = k0_events if k0_events else raw_list
    latest_event = max(candidate_list, key=lambda e: e.get("created_at", 0)) if candidate_list else {}

    try:
        content = json.loads(latest_event.get("content", "{}"))
    except (json.JSONDecodeError, TypeError):
        content = {}

    if content:
        name = content.get("display_name") or content.get("name", "")
        if name or not profile.get("name"):
            profile["name"] = name or profile.get("name", "")
            profile["display_name"] = content.get("display_name") or name or profile.get("display_name", "")
        if content.get("about"):
            profile["about"] = content.get("about")
        if content.get("picture"):
            profile["picture"] = sanitize_media_url(content.get("picture"))
        if content.get("banner"):
            profile["banner"] = sanitize_media_url(content.get("banner"))
        if content.get("nip05"):
            profile["nip05"] = content.get("nip05")
        if content.get("lud16"):
            profile["lud16"] = content.get("lud16")

    return profile




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


def resolve_author_did(hex_pubkey):
    """Resolve a Nostr hex pubkey to a registered sovereign User DID, or return empty string."""
    if not hex_pubkey:
        return ""
    try:
        from django.contrib.auth import get_user_model
        UserModel = get_user_model()
        for u in UserModel.objects.filter(username__startswith="did:").only("username").iterator():
            if did_to_pubkey(u.username) == hex_pubkey:
                return u.username
    except Exception:
        pass
    return ""


def _extract_display_title(content, summary="", alt_text=""):
    """Extract a clean, human-readable display title from content, summary, or alt_text.

    If content or summary is a JSON string (e.g. {"title": "...", "queryKey": "..."}),
    safely parse the JSON and extract relevant title / caption keys without curly braces.
    """
    for candidate in (content, summary, alt_text):
        if not candidate or not isinstance(candidate, str):
            continue
        trimmed = candidate.strip()
        if trimmed.startswith("{") and trimmed.endswith("}"):
            try:
                data = json.loads(trimmed)
                if isinstance(data, dict):
                    extracted = (
                        data.get("title")
                        or data.get("caption")
                        or data.get("text")
                        or data.get("queryKey")
                        or data.get("prompt")
                        or data.get("alt")
                        or data.get("description")
                        or data.get("name")
                    )
                    if extracted and isinstance(extracted, str):
                        return extracted.strip()
            except (json.JSONDecodeError, TypeError):
                pass
        elif trimmed:
            return trimmed
    return ""


def fetch_media_assets(authors=None, limit=50, relay_urls=None):
    """Fetch Kind 1063 media attachments and resolve Kind 0 profiles."""
    filter_obj = {"kinds": [1063], "limit": limit}
    if authors:
        filter_obj["authors"] = authors


    raw_events = relay_req(filter_obj, relay_urls=relay_urls)
    if not raw_events:
        return []

    # Multi-relay event deduplication by ID
    deduped_events = {}
    if isinstance(raw_events, dict):
        for eid, e in raw_events.items():
            real_id = e.get("id") or eid
            if real_id and real_id not in deduped_events:
                deduped_events[real_id] = e
    elif isinstance(raw_events, list):
        for e in raw_events:
            real_id = e.get("id")
            if real_id and real_id not in deduped_events:
                deduped_events[real_id] = e
    raw_events = deduped_events

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
        file_url = sanitize_media_url(get_tag_value(tags, "url"))
        nip94 = _extract_nip94_tags(tags)
        raw_content = e.get("content", "")
        alt_val = get_tag_value(tags, "alt") or get_tag_value(tags, "summary") or ""
        display_title = _extract_display_title(raw_content, nip94["summary"], alt_val)

        note = {
            "id": e.get("id", ""),
            "kind": 1063,
            "pubkey": pk,
            "pubkey_hex": pk,
            "author_did": resolve_author_did(pk),
            "tags_json": json.dumps(tags),
            "npub": npub_val,
            "nip05": profile.get("nip05") or "",
            "lud16": profile.get("lud16") or "",
            "content": raw_content,
            "display_title": display_title,
            "created_at": datetime.fromtimestamp(e.get("created_at", 0)),
            "tags": tags,
            "file_url": file_url,
            "media_url": file_url or "",
            "mime_type": get_tag_value(tags, "m"),
            "dimensions": get_tag_value(tags, "dim"),
            "thumbnail_url": sanitize_media_url(get_tag_value(tags, "thumb")),
            "alt_text": alt_val,
            "is_sovereign": bool(file_url and "127.0.0.1" in file_url),
            "author_name": profile.get("display_name") or profile.get("name") or "",
            "author_avatar": sanitize_media_url(profile.get("picture", "")),
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
    """Fetch Kind 1 & 1063 notes for given authors, with profile and media enrichment."""
    filter_obj = {"kinds": [1, 1063], "limit": limit}
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

    from .nip10 import extract_media_from_note

    result = []
    for e in raw_events.values():
        pk = e.get("pubkey", "")
        npub_val = hex_to_npub(pk) if pk else ""
        profile = profiles.get(pk, {})
        tags = e.get("tags", [])
        note_dict = {
            "id": e.get("id", ""),
            "kind": e.get("kind", 1),
            "pubkey": pk,
            "pubkey_hex": pk,
            "author_did": resolve_author_did(pk),
            "tags_json": json.dumps(tags),
            "npub": npub_val,
            "nip05": profile.get("nip05") or "",
            "lud16": profile.get("lud16") or "",
            "content": e.get("content", ""),
            "created_at": datetime.fromtimestamp(e.get("created_at", 0)),
            "tags": tags,
            "author_name": profile.get("display_name") or profile.get("name") or "",
            "author_avatar": profile.get("picture", ""),
        }
        result.append(extract_media_from_note(note_dict))

    result.sort(key=lambda x: x["created_at"], reverse=True)
    return result[:limit]



MAX_ANCESTOR_DEPTH = 32


def og_fallback_image(request):
    """Absolute URL of the branded Open Graph fallback image."""
    from django.templatetags.static import static

    scheme = request.scheme if request.scheme else "https"
    host = request.get_host()
    return f"{scheme}://{host}{static('img/iyou_symbol.png')}"


INDEXING_FALLBACK_RELAYS = [
    "wss://relay.nostr.band",
    "wss://purplepag.es",
    "wss://nos.lol",
    "wss://relay.damus.io",
]


def fetch_thread(thread_id, relay_urls=None):
    """Fetch a target event (Hero), its full root→…→parent ancestor chain, and direct 1-level replies."""
    from .nip10 import parse_nip10_tags, resolve_ancestor_ids

    target_raw = relay_req({"ids": [thread_id], "limit": 1}, relay_urls=relay_urls)
    if not target_raw:
        fallback_pool = list(dict.fromkeys((relay_urls or DEFAULT_RELAYS) + INDEXING_FALLBACK_RELAYS))
        target_raw = relay_req({"ids": [thread_id], "limit": 1}, relay_urls=fallback_pool)

    if not target_raw:
        return {"thread_root": None, "ancestors": [], "roots": [], "replies": {}, "total_replies": 0}

    target_event = list(target_raw.values())[0]
    tags = target_event.get("tags", [])
    root_id, parent_id, marker, mention_ids, _ = parse_nip10_tags(tags)

    # ---- Backfill the full ancestor chain (root → … → parent) ----
    # The target only expresses its immediate parent + root; intermediate
    # ancestors are resolved by walking each hop's own e-tags and batch-requiring
    # any missing ids until the root is reached (bounded by MAX_ANCESTOR_DEPTH).
    pool = dict(target_raw)
    queue = [aid for aid in resolve_ancestor_ids(target_event) if aid != thread_id]
    seen = set(queue)
    seen.add(thread_id)
    ancestor_relay_pool = list(dict.fromkeys((relay_urls or DEFAULT_RELAYS) + INDEXING_FALLBACK_RELAYS))

    for _ in range(MAX_ANCESTOR_DEPTH):
        if not queue:
            break
        missing = [q for q in queue if q not in pool]
        if missing:
            batch = list(dict.fromkeys(missing))[:20]
            fetched = relay_req(
                {"ids": batch, "kinds": [1, 1111], "limit": 20},
                relay_urls=ancestor_relay_pool,
            )
            pool.update(fetched)
            seen.update(fetched)
        newly_discovered = []
        for q in queue:
            ev = pool.get(q)
            if not ev:
                continue
            for aid in resolve_ancestor_ids(ev):
                if aid and aid != thread_id and aid not in seen:
                    seen.add(aid)
                    newly_discovered.append(aid)
        queue = newly_discovered

    query_ids = [thread_id]
    if root_id and root_id != thread_id:
        query_ids.append(root_id)

    descendants_raw = relay_req({"#e": query_ids, "kinds": [1, 1111], "limit": 100}, relay_urls=relay_urls)

    combined = {**pool, **descendants_raw}

    pubkeys = set()
    for e in combined.values():
        pk = e.get("pubkey")
        if pk:
            pubkeys.add(pk)
        for tag in e.get("tags", []):
            if tag and len(tag) > 1 and tag[0] == "p":
                pubkeys.add(tag[1])

    profiles = {}
    if pubkeys:
        profile_events = relay_req({"kinds": [0], "authors": list(pubkeys)[:100]}, relay_urls=relay_urls)
        for e in profile_events.values():
            pk = e.get("pubkey", "")
            try:
                profiles[pk] = json.loads(e.get("content", "{}"))
            except (json.JSONDecodeError, TypeError):
                profiles.setdefault(pk, {})

    from .nip10 import _enrich_root

    all_enriched = {}
    for eid, e in combined.items():
        kind = e.get("kind", 1)
        tags = e.get("tags", [])
        root_id, parent_id, marker, mention_ids, reply_to_pubkey = parse_nip10_tags(tags)
        all_enriched[eid] = _enrich_root(
            e,
            kind,
            profiles,
            datetime.fromtimestamp,
            root_id=root_id or "",
            parent_id=parent_id or root_id or "",
            reply_to_pubkey=reply_to_pubkey or "",
        )

    # 1. Resolve Target Note (Hero)
    thread_root = all_enriched.get(thread_id)
    if not thread_root:
        return {"thread_root": None, "ancestors": [], "roots": [], "replies": {}, "total_replies": 0}

    # 2. Ancestor Resolution: Build strictly ordered list [root, …, grandparent, parent]
    ancestors = []
    curr_id = thread_root.get("parent_id") or thread_root.get("root_id")
    visited_ancestors = set()
    while curr_id and curr_id not in visited_ancestors and curr_id != thread_id:
        visited_ancestors.add(curr_id)
        anc = all_enriched.get(curr_id)
        if anc:
            ancestors.insert(0, anc)
            curr_id = anc.get("parent_id")
            if not curr_id and anc.get("root_id") and anc.get("root_id") != anc.get("id"):
                curr_id = anc.get("root_id")
            if curr_id == thread_id:
                curr_id = None
        else:
            break

    # 3. Direct Replies Only (1-Level Down)
    direct_replies = []
    parent_cite_counts = {}
    for eid, note in all_enriched.items():
        pid = note.get("parent_id")
        if pid:
            parent_cite_counts[pid] = parent_cite_counts.get(pid, 0) + 1

    for eid, note in all_enriched.items():
        if eid == thread_id:
            continue
        if any(a["id"] == eid for a in ancestors):
            continue

        p_id = note.get("parent_id")
        r_id = note.get("root_id")

        if p_id == thread_id or (not p_id and r_id == thread_id):
            sub_count = parent_cite_counts.get(eid, 0)
            note["reply_count"] = sub_count
            direct_replies.append(note)

    direct_replies.sort(key=lambda x: x["created_at"])
    thread_root["replies"] = direct_replies
    thread_root["reply_count"] = len(direct_replies)

    return {
        "thread_root": thread_root,
        "ancestors": ancestors,
        "roots": [thread_root],
        "replies": {thread_id: direct_replies},
        "total_replies": len(direct_replies),
    }





def sanitize_media_url(url):
    """Ensure media attachments, Blossom assets, and avatars use HTTPS unless local."""
    if not url:
        return ""
    url = str(url).strip()
    if url.startswith("http://") and not ("127.0.0.1" in url or "localhost" in url):
        return "https://" + url[7:]
    return url


def get_tag_value(tags, tag_name, index=1, default=""):
    """Extract a value from a Nostr event's tags array.

    e.g. get_tag_value(event["tags"], "e") returns the parent event id.
    """
    for tag in tags:
        if tag and len(tag) > index and tag[0] == tag_name:
            return tag[index]
    return default


DEFAULT_RELAYS = [
    "wss://relay.iyou.me",
    "wss://nos.lol",
    "wss://relay.damus.io",
    "wss://relay.primal.net",
    "wss://relay.nostr.band",
    "ws://127.0.0.1:9003",
]



CURATED_AUTHORS = [
    "3bf0c63fcb93463407af97a5e5ee64fa883d107ef9e558472c4eb9aaaefa459d",
    "32e1827635450ebb3c5a7d12c1f8e7b2b514439ac10a67eef3d9fd9c5c68e245",
]


def _connect_relay(relay_url, sub_id, filter_obj, timeout):
    """Connect to a single relay and fetch events with defensive error handling."""
    events = {}
    done = threading.Event()

    def on_open(ws):
        try:
            ws.send(json.dumps(["REQ", sub_id, filter_obj]))
        except Exception:
            done.set()

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

    try:
        ws = WebSocketApp(
            relay_url,
            on_open=on_open,
            on_message=on_message,
            on_error=on_error,
            on_close=on_close,
        )

        t = threading.Thread(
            target=ws.run_forever,
            kwargs={"sslopt": {"cert_reqs": ssl.CERT_NONE}},
            daemon=True,
        )
        t.start()
        done.wait(timeout=timeout)
        try:
            ws.close()
        except Exception:
            pass
    except Exception as e:
        logger.debug("_connect_relay error on %s: %s", relay_url, e)

    return events


def relay_req(filter_obj, sub_id=None, timeout=10, relay_urls=None):
    """Try multiple relays with autonomous failover, returning events from first responsive one."""
    if sub_id is None:
        sub_id = "wun_" + str(int(time.time() * 1000000))[-8:]

    if relay_urls is None:
        relay_urls = DEFAULT_RELAYS

    for relay_url in relay_urls:
        try:
            events = _connect_relay(relay_url, sub_id, filter_obj, timeout)
            if events:
                return events
        except Exception as e:
            logger.debug("relay_req failed on %s: %s", relay_url, e)
            continue

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

    from .nip10 import build_thread_tree, sanitize_event_content
    from datetime import datetime

    # Normalize and deduplicate input raw_events
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
        sanitized = sanitize_event_content(e)
        if not sanitized["is_valid"]:
            continue
        e["has_content_warning"] = sanitized["has_content_warning"]
        e["warning_reason"] = sanitized["warning_reason"]
        e["lang"] = sanitized["lang"]

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
                if reply_note["id"] not in root_by_id:
                    reply_note["reactions"] = []
                    reply_note["reply_count"] = 0
                    reply_note["replies"] = []
                    root_by_id[reply_note["id"]] = reply_note
                    roots.append(reply_note)

    # Deduplicate roots strictly by ID and ensure reply_count is set
    seen_final_root_ids = set()
    unique_roots = []
    for r in roots:
        if r["id"] not in seen_final_root_ids:
            seen_final_root_ids.add(r["id"])
            r["reply_count"] = r.get("reply_count") or len(r.get("replies", []))
            unique_roots.append(r)
    roots = unique_roots


    roots.sort(key=lambda x: x["created_at"], reverse=True)

    return {
        "roots": roots[:max_items],
        "replies": reply_map,
        "total_replies": tree["total_reply_count"],
        "flat": [],  # deprecated — kept for backward compat with /api/feed serializer
    }


def attach_social_counts(notes, relay_urls=None):
    """
    Unified batch social-counts query.

    Issues a single relay filter over kinds [1, 6, 7, 1111] for every root
    note ID (via '#' e tags) and sets note['reply_count'],
    note['repost_count'], note['like_count'], and note['reactions_count'].
    """
    if not notes:
        return notes

    root_ids = [n["id"] for n in notes if n.get("id")]
    if not root_ids:
        return notes

    relays = relay_urls or DEFAULT_RELAYS
    filter_obj = {
        "kinds": [1, 6, 7, 1111],
        "#e": root_ids,
        "limit": 800,
    }

    raw_events = relay_req(filter_obj, relay_urls=relays)
    events = list(raw_events.values()) if isinstance(raw_events, dict) else (raw_events if isinstance(raw_events, list) else [])

    reply_counts = {rid: 0 for rid in root_ids}
    repost_counts = {rid: 0 for rid in root_ids}
    like_counts = {rid: 0 for rid in root_ids}

    for event in events:
        kind = event.get("kind")
        content = (event.get("content") or "").strip()
        # Exclude explicit downvotes/dislikes from the reaction tally
        if kind == 7 and content == "-":
            continue

        for tag in event.get("tags", []):
            if len(tag) < 2 or tag[0] != "e":
                continue
            target_id = tag[1]
            if target_id not in reply_counts:
                continue
            if kind in (1, 1111):
                reply_counts[target_id] += 1
            elif kind == 6:
                repost_counts[target_id] += 1
            elif kind == 7:
                like_counts[target_id] += 1

    for note in notes:
        nid = note.get("id")

        existing_reply_count = note.get("reply_count")
        try:
            existing_reply_int = int(existing_reply_count) if existing_reply_count is not None else 0
        except (ValueError, TypeError):
            existing_reply_int = 0
        existing_replies = len(note.get("replies", []))
        note["reply_count"] = max(existing_reply_int, existing_replies, reply_counts.get(nid, 0))

        existing_reposts = note.get("repost_count")
        try:
            existing_reposts_int = int(existing_reposts) if existing_reposts is not None else 0
        except (ValueError, TypeError):
            existing_reposts_int = 0
        note["repost_count"] = max(existing_reposts_int, repost_counts.get(nid, 0))

        existing_likes = note.get("like_count") or note.get("reactions") or 0
        if isinstance(existing_likes, dict):
            existing_likes = sum(existing_likes.values())
        elif isinstance(existing_likes, list):
            existing_likes = len(existing_likes)
        try:
            existing_likes_int = int(existing_likes)
        except (ValueError, TypeError):
            existing_likes_int = 0
        note["like_count"] = max(existing_likes_int, like_counts.get(nid, 0))
        note["reactions_count"] = note["like_count"]

    return notes


def attach_reply_counts(notes, relay_urls=None):
    """Backward-compatible wrapper: reply tally from the unified social-counts query."""
    return attach_social_counts(notes, relay_urls=relay_urls)


def attach_reaction_counts(notes, relay_urls=None):
    """Backward-compatible wrapper: reaction tally from the unified social-counts query."""
    return attach_social_counts(notes, relay_urls=relay_urls)


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
            except (json.JSONDecodeError, TypeError):
                profiles.setdefault(pk, {})

    return process_into_feed(raw_events, profiles, max_items=limit)


def fetch_contact_pubkeys(user_pubkey, relay_urls=None):
    """Fetch Kind 3 (Contact List) for a user and return followed pubkeys."""
    events = relay_req({"kinds": [3], "authors": [user_pubkey], "limit": 1}, relay_urls=relay_urls)
    for e in events.values():
        tags = e.get("tags", [])
        return [tag[1] for tag in tags if tag and tag[0] == "p" and len(tag) > 1]
    return []


NOTIFICATION_KINDS = [1, 6, 7, 9735]
NOTIFICATION_CATEGORY_LABELS = {
    "mentions": "Mentions / Replies",
    "reposts": "Reposts",
    "reactions": "Reactions",
    "zaps": "Zaps",
}
NOTIFICATION_CATEGORY_ICONS = {
    "mentions": "💬",
    "reposts": "🔁",
    "reactions": "❤️",
    "zaps": "⚡",
}

NOTIFICATION_CATEGORY_OF_KIND = {
    1: "mentions",
    6: "reposts",
    7: "reactions",
    9735: "zaps",
}


def build_notification_preview(kind, content, tags=None):
    """Human-readable preview snippet for a notification event."""
    tags = tags or []
    content = (content or "").strip()

    if kind == 9735:
        comment = ""
        if content:
            try:
                zap_req = json.loads(content)
            except (ValueError, TypeError):
                zap_req = content
            if isinstance(zap_req, dict):
                comment = (zap_req.get("content") or "").strip() or (zap_req.get("description") or "").strip()
            elif isinstance(zap_req, str):
                comment = zap_req.strip()
        amount = get_tag_value(tags, "amount") or ""
        suffix = ""
        if amount:
            try:
                suffix = f" · {int(amount) / 1000:g} sats"
            except (ValueError, TypeError):
                suffix = ""
        if comment:
            return "⚡ " + comment[:120] + suffix
        return "⚡ Zapped your note" + suffix

    if kind == 7:
        if not content or content in ("+", "−", "-", "Like", "like", "❤️"):
            return "Liked your note"
        return f"Reacted {content[:8]} to your note"

    if kind == 6:
        snippet = content.replace("\n", " ").strip()[:80]
        if snippet and snippet != content.replace("\n", " ").strip():
            return "Reposted: " + snippet
        return "Reposted your note"

    collapsed = content.replace("\n", " ").strip()
    if not collapsed:
        return "Mentioned you"
    return collapsed[:140] + ("…" if len(collapsed) > 140 else "")


def fetch_notifications(user_pubkey, relay_urls=None, categories=None):
    """Fetch inbound social interactions (`{"#p": [...]}`) and enrich actors.

    Kinds: 1 mentions/replies, 6 reposts, 7 reactions, 9735 zaps (NIP-57).

    Returns (items, counts) where items are sorted newest-first and each item
    carries actor identity, a category, and a deep link into the matching thread.
    """
    if categories is None:
        categories = list(NOTIFICATION_CATEGORY_LABELS.keys())
    if not user_pubkey:
        return [], {c: 0 for c in categories}

    relays = relay_urls or DEFAULT_RELAYS
    filter_obj = {"#p": [user_pubkey], "kinds": NOTIFICATION_KINDS, "limit": 40}
    raw_events = relay_req(filter_obj, relay_urls=relays)
    events = (
        list(raw_events.values())
        if isinstance(raw_events, dict)
        else (raw_events if isinstance(raw_events, list) else [])
    )

    actor_pubkeys = {e.get("pubkey") for e in events if e.get("pubkey")}
    profiles = {}
    for pk in actor_pubkeys:
        if pk == user_pubkey:
            profiles[pk] = {}
        else:
            profiles[pk] = fetch_profile_data(pk, relay_urls=relays)

    items = []
    for e in events:
        kind = e.get("kind")
        category = NOTIFICATION_CATEGORY_OF_KIND.get(kind)
        if category not in categories:
            continue

        tags = e.get("tags") or []
        target_id = ""
        for tag in tags:
            if tag and tag[0] == "e" and len(tag) > 1 and tag[1]:
                target_id = tag[1]
                break
        if not target_id:
            target_id = e.get("id", "") or ""

        pk = e.get("pubkey") or ""
        prof = profiles.get(pk, {})
        npub = hex_to_npub(pk) if pk else ""
        actor_name = (
            prof.get("display_name")
            or prof.get("name")
            or (npub[:20] if pk else "Anonymous")
        )

        items.append({
            "id": e.get("id", ""),
            "kind": kind,
            "category": category,
            "icon": NOTIFICATION_CATEGORY_ICONS.get(category, "🔔"),
            "pubkey": pk,
            "npub": npub,
            "actor_name": actor_name,
            "actor_avatar": prof.get("picture") or "",
            "target_id": target_id,
            "thread_url": f"/feed?thread={target_id}",
            "content": (e.get("content") or ""),
            "preview": build_notification_preview(kind, e.get("content", ""), tags),
            "created_at_epoch": e.get("created_at") or 0,
            "is_self": pk == user_pubkey,
        })

    items.sort(key=lambda n: n["created_at_epoch"], reverse=True)
    counts = {c: 0 for c in categories}
    for item in items:
        counts[item["category"]] += 1

    return items, counts


class NotificationsView(LoginRequiredMixin, TemplateView):
    template_name = "notifications.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user_pubkey = did_to_pubkey(self.request.user.username)
        relays = get_relays_for_request(self.request)

        context["user_pubkey"] = user_pubkey
        context["user_npub"] = did_to_npub(self.request.user.username) if user_pubkey else ""
        context["relays_json"] = json.dumps(relays)
        context["relays"] = relays

        notifications, counts = fetch_notifications(user_pubkey, relay_urls=relays)
        context["notifications"] = notifications
        context["category_counts"] = counts
        context["notification_total"] = len(notifications)
        context["category_tabs"] = [
            {"key": k, "label": NOTIFICATION_CATEGORY_LABELS[k], "count": counts.get(k, 0)}
            for k in NOTIFICATION_CATEGORY_LABELS
        ]
        return context


def fetch_user_nip65_relays(pubkey, relay_urls=None):
    """Fetch NIP-65 (Kind 10002) relay list metadata for a user pubkey."""
    if not pubkey:
        return {"read": [], "write": [], "all": []}
    events = relay_req({"kinds": [10002], "authors": [pubkey], "limit": 1}, relay_urls=relay_urls)
    read_relays = []
    write_relays = []
    all_relays = []
    for e in events.values():
        tags = e.get("tags", [])
        for tag in tags:
            if tag and tag[0] == "r" and len(tag) > 1:
                url = tag[1].strip()
                if not url:
                    continue
                all_relays.append(url)
                marker = tag[2].lower() if len(tag) > 2 else None
                if marker == "read":
                    read_relays.append(url)
                elif marker == "write":
                    write_relays.append(url)
                else:
                    read_relays.append(url)
                    write_relays.append(url)
        break
    return {
        "read": list(dict.fromkeys(read_relays)),
        "write": list(dict.fromkeys(write_relays)),
        "all": list(dict.fromkeys(all_relays)),
    }


class GalleryView(TemplateView):
    template_name = "gallery.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user_pubkey = did_to_pubkey(self.request.user.username) if self.request.user.is_authenticated else ""
        relays = get_relays_for_request(self.request)
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
        og_image = (
            (notes[0].get("media_attachments") or [{}])[0].get("url")
            or notes[0].get("thumbnail_url")
            or notes[0].get("file_url")
            or og_fallback_image(self.request)
        ) if notes else og_fallback_image(self.request)
        context["og_image"] = og_image
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
        target_npub = hex_to_npub(hex_pubkey) if hex_pubkey else npub
        context["hex_pubkey"] = hex_pubkey
        context["target_pubkey_hex"] = hex_pubkey
        context["target_nostr_pubkey_hex"] = hex_pubkey
        context["npub"] = target_npub
        context["target_npub"] = target_npub
        context["og_image"] = og_fallback_image(self.request)

        if not hex_pubkey:
            context["error"] = f"Invalid npub: {npub}"
            return context

        profile = fetch_profile_data(hex_pubkey)
        context["profile"] = profile

        # Owner resolution & UserLinkDeck
        owner_user = None
        for candidate in UserModel.objects.only("username").iterator():
            if did_to_pubkey(candidate.username) == hex_pubkey:
                owner_user = candidate
                break

        author_did = owner_user.username if owner_user else ""
        context["target_did"] = author_did
        context["profile_did"] = author_did

        is_owner = bool(
            self.request.user.is_authenticated and (
                self.request.user.username == author_did
                or did_to_pubkey(self.request.user.username) == hex_pubkey
            )
        )
        context["is_owner"] = is_owner

        owner_deck = getattr(owner_user, "link_deck", None) if owner_user else None
        context["owner_deck"] = owner_deck
        context["link_deck"] = owner_deck
        context["deck_items"] = list(owner_deck.items.filter(is_active=True)) if owner_deck else []
        context["profile_handle"] = owner_deck.handle if owner_deck else (profile.get("name") or "")

        context["user_pubkey"] = (
            did_to_pubkey(self.request.user.username)
            if self.request.user.is_authenticated
            else ""
        )

        # Author Activity Streams: query notes authored by this user
        from .nip10 import parse_nip10_tags, _enrich_root
        raw_events = relay_req({"kinds": [1, 1063, 1111, 30023], "authors": [hex_pubkey], "limit": 50})

        deduped_events = {}
        if isinstance(raw_events, dict):
            for eid, e in raw_events.items():
                real_id = e.get("id") or eid
                if real_id and real_id not in deduped_events:
                    deduped_events[real_id] = e
        elif isinstance(raw_events, list):
            for e in raw_events:
                real_id = e.get("id")
                if real_id and real_id not in deduped_events:
                    deduped_events[real_id] = e

        profiles_cache = {hex_pubkey: profile}

        def _ts_to_dt(ts):
            if isinstance(ts, datetime):
                return ts
            return datetime.fromtimestamp(ts or 0)

        posts = []
        replies = []
        media_assets = []

        for eid, e in deduped_events.items():
            kind = e.get("kind", 1)
            if kind not in (1, 1063, 1111, 30023):
                continue
            tags = e.get("tags", [])

            root_id, parent_id, marker, mention_ids, reply_to_pubkey = parse_nip10_tags(tags)

            note = _enrich_root(e, kind, profiles_cache, _ts_to_dt, root_id=root_id, parent_id=parent_id, reply_to_pubkey=reply_to_pubkey)
            note["author_avatar"] = profile.get("picture", "")
            note["author_name"] = profile.get("name", "")

            # If Kind 1063 or has media attachments
            if note.get("media_attachments") or kind == 1063 or note.get("media_url"):
                for m in note.get("media_attachments", []):
                    media_assets.append({
                        "id": note["id"],
                        "media_url": m.get("url"),
                        "media_type": m.get("type", "image"),
                        "display_title": note.get("display_content", note.get("content", "")),
                        "is_sovereign": note.get("is_sovereign", False),
                        "created_at": note["created_at"],
                    })
                if kind == 1063 and not note.get("media_attachments") and note.get("media_url"):
                    media_assets.append({
                        "id": note["id"],
                        "media_url": note.get("media_url"),
                        "media_type": note.get("media_type", "image"),
                        "display_title": note.get("alt_text", "") or note.get("content", ""),
                        "is_sovereign": note.get("is_sovereign", False),
                        "created_at": note["created_at"],
                    })

            is_reply = bool(kind == 1111 or parent_id or marker == "reply")
            if is_reply:
                replies.append(note)
            else:
                posts.append(note)

        relays = get_relays_for_request(self.request)
        posts = attach_social_counts(posts, relay_urls=relays)
        replies = attach_social_counts(replies, relay_urls=relays)
        posts.sort(key=lambda x: x["created_at"], reverse=True)
        replies.sort(key=lambda x: x["created_at"], reverse=True)
        media_assets.sort(key=lambda x: x["created_at"], reverse=True)


        context["posts"] = posts
        context["replies"] = replies
        context["media_assets"] = media_assets
        context["broadcasts"] = posts  # backwards compatibility

        sovereign_score = sum(1 for m in media_assets if m.get("is_sovereign"))
        context["sovereign_score"] = sovereign_score
        context["media"] = media_assets

        return context



RESERVED_HANDLES = {
    "admin", "iyou", "wun", "poly", "idp", "api",
    "dev", "mods", "system", "help", "official",
}

HANDLE_PATTERN = re.compile(r"^[a-z0-9_-]{3,32}$")
MAX_HANDLE_CLAIM_ATTEMPTS = 5

ECOSYSTEM_SEED_ITEMS = [
    ("Blog", "https://blog.iyou.me", "blog"),
    ("Talk", "https://talk.iyou.me", "talk"),
    ("Poly", "https://poly.iyou.me", "poly"),
    ("Gallery", "/gallery", "gallery"),
]


class HandleValidationError(Exception):
    pass


def normalize_handle(raw_handle):
    return (raw_handle or "").strip().lstrip("@").lower()


def seed_default_deck_items(deck):
    items = [
        UserLinkItem(
            deck=deck,
            title=title,
            url=url,
            icon_category=category,
            is_ecosystem_link=True,
            is_active=False,
            order=position,
        )
        for position, (title, url, category) in enumerate(ECOSYSTEM_SEED_ITEMS)
    ]
    UserLinkItem.objects.bulk_create(items)


def claim_handle(user, raw_handle):
    handle = normalize_handle(raw_handle)
    if not HANDLE_PATTERN.match(handle):
        raise HandleValidationError(
            "Handle must be 3-32 chars: lowercase letters, digits, '_' or '-'."
        )
    if handle in RESERVED_HANDLES:
        raise HandleValidationError("That handle is reserved.")

    for _attempt in range(MAX_HANDLE_CLAIM_ATTEMPTS):
        try:
            with transaction.atomic():
                deck = UserLinkDeck.objects.filter(user=user).first()
                if deck is not None and deck.handle == handle:
                    return deck
                max_disc = UserLinkDeck.objects.filter(handle=handle).aggregate(
                    Max("discriminator")
                )["discriminator__max"]
                discriminator = 0 if max_disc is None else max_disc + 1
                created = False
                if deck is None:
                    deck = UserLinkDeck(user=user, handle=handle, discriminator=discriminator)
                    deck.save()
                    created = True
                else:
                    deck.handle = handle
                    deck.discriminator = discriminator
                    deck.save()
                if created:
                    seed_default_deck_items(deck)
                return deck
        except IntegrityError:
            continue

    raise HandleValidationError("Handle claim failed due to contention. Try again.")


def _get_user_deck(user):
    return UserLinkDeck.objects.filter(user=user).first()


def _serialize_deck_item(item):
    return {
        "id": item.id,
        "title": item.title,
        "url": item.url,
        "icon_category": item.icon_category,
        "icon_emoji": item.icon_emoji,
        "is_ecosystem_link": item.is_ecosystem_link,
        "order": item.order,
        "is_active": item.is_active,
    }


class LinkDeckView(TemplateView):
    template_name = "link_deck.html"

    def get(self, request, *args, **kwargs):
        handle = kwargs.get("handle")
        disc_raw = kwargs.get("disc")
        did_key = kwargs.get("did_key")

        if did_key:
            owner = UserModel.objects.filter(username=did_key).first()
            target_deck = getattr(owner, "link_deck", None) if owner else None
            if target_deck is not None and target_deck.is_public:
                return HttpResponsePermanentRedirect(target_deck.canonical_path)
            owner_did = did_key
        else:
            disc = int(disc_raw) if disc_raw else 0
            target_deck = (
                UserLinkDeck.objects.select_related("user")
                .filter(handle=(handle or "").lower(), discriminator=disc)
                .first()
            )
            if target_deck is None or not target_deck.is_public:
                raise Http404("Unknown handle.")
            owner_did = target_deck.user.username

        hex_pubkey = did_to_pubkey(owner_did)
        relays = request.session.get("relays", DEFAULT_RELAYS)
        profile = fetch_profile_data(hex_pubkey, relay_urls=relays) if hex_pubkey else {}

        items = list(target_deck.items.filter(is_active=True)) if target_deck else []

        context = {
            "deck": target_deck,
            "display_handle": target_deck.display_handle if target_deck else "",
            "headline": target_deck.headline if target_deck else "",
            "owner_did": owner_did,
            "hex_pubkey": hex_pubkey,
            "target_nostr_pubkey_hex": hex_pubkey,
            "target_did": owner_did,
            "profile_did": owner_did,
            "profile_handle": target_deck.handle if target_deck else "",
            "npub": hex_to_npub(hex_pubkey) if hex_pubkey else owner_did,
            "profile": profile,
            "items": items,
            "feed_url": f"/feed?author={hex_pubkey}" if hex_pubkey else "/feed",
            "user_pubkey": (
                did_to_pubkey(request.user.username)
                if request.user.is_authenticated
                else ""
            ),
        }
        return self.render_to_response(context)


@login_required
def api_deck_handle(request):
    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=405)
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "invalid JSON body"}, status=400)

    raw_handle = data.get("handle")
    headline = data.get("headline")

    if raw_handle:
        try:
            deck = claim_handle(request.user, raw_handle)
        except HandleValidationError as exc:
            return JsonResponse({"error": str(exc)}, status=400)
    else:
        deck = _get_user_deck(request.user)
        if deck is None:
            return JsonResponse({"error": "Claim a handle first."}, status=400)

    if isinstance(headline, str):
        deck.headline = headline.strip()[:160]
        deck.save(update_fields=["headline", "updated_at"])

    return JsonResponse({
        "ok": True,
        "handle": deck.handle,
        "discriminator": deck.discriminator,
        "display_handle": deck.display_handle,
        "canonical_url": deck.canonical_path,
        "headline": deck.headline,
    })


@login_required
def api_deck_items(request):
    if request.method == "GET":
        deck = _get_user_deck(request.user)
        items = list(deck.items.all()) if deck else []
        return JsonResponse({
            "handle": deck.handle if deck else None,
            "display_handle": deck.display_handle if deck else None,
            "canonical_url": deck.canonical_path if deck else None,
            "headline": deck.headline if deck else "",
            "is_verified": deck.is_verified if deck else False,
            "verified_source_url": deck.verified_source_url if deck else "",
            "verified_at": (
                deck.verified_at.isoformat()
                if deck and deck.verified_at else None
            ),
            "items": [_serialize_deck_item(i) for i in items],
        })

    if request.method != "POST":
        return JsonResponse({"error": "GET or POST required"}, status=405)

    deck = _get_user_deck(request.user)
    if deck is None:
        return JsonResponse({"error": "Claim a handle first."}, status=400)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "invalid JSON body"}, status=400)

    title = (data.get("title") or "").strip()
    url = (data.get("url") or "").strip()
    icon_category = data.get("icon_category") or "link"

    if not title or len(title) > 64:
        return JsonResponse({"error": "title is required (max 64 chars)"}, status=400)
    if not url or len(url) > 2048:
        return JsonResponse({"error": "url is required (max 2048 chars)"}, status=400)
    if icon_category not in dict(UserLinkItem.ICON_CATEGORY_CHOICES):
        return JsonResponse({"error": f"unknown icon_category: {icon_category}"}, status=400)

    max_order = deck.items.aggregate(Max("order"))["order__max"]
    item = UserLinkItem.objects.create(
        deck=deck,
        title=title,
        url=url,
        icon_category=icon_category,
        order=0 if max_order is None else max_order + 1,
    )
    return JsonResponse({"ok": True, "item": _serialize_deck_item(item)}, status=201)


@login_required
def api_deck_item_detail(request, pk):
    item = UserLinkItem.objects.select_related("deck").filter(pk=pk).first()
    if item is None:
        return JsonResponse({"error": "item not found"}, status=404)
    if item.deck.user_id != request.user.id:
        return JsonResponse({"error": "not your deck item"}, status=403)

    if request.method == "PATCH":
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({"error": "invalid JSON body"}, status=400)

        if "title" in data:
            title = (data.get("title") or "").strip()
            if not title or len(title) > 64:
                return JsonResponse({"error": "title is required (max 64 chars)"}, status=400)
            item.title = title
        if "url" in data:
            url = (data.get("url") or "").strip()
            if not url or len(url) > 2048:
                return JsonResponse({"error": "url is required (max 2048 chars)"}, status=400)
            item.url = url
        if "icon_category" in data:
            if data["icon_category"] not in dict(UserLinkItem.ICON_CATEGORY_CHOICES):
                return JsonResponse(
                    {"error": f"unknown icon_category: {data['icon_category']}"}, status=400
                )
            item.icon_category = data["icon_category"]
        if "is_active" in data:
            item.is_active = bool(data["is_active"])
        item.save()
        return JsonResponse({"ok": True, "item": _serialize_deck_item(item)})

    if request.method == "DELETE":
        item.delete()
        return JsonResponse({"ok": True})

    return JsonResponse({"error": "PATCH or DELETE required"}, status=405)


@login_required
def api_deck_reorder(request):
    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=405)
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "invalid JSON body"}, status=400)

    item_ids = data.get("item_ids")
    if not isinstance(item_ids, list):
        return JsonResponse({"error": "item_ids must be a list"}, status=400)

    deck = _get_user_deck(request.user)
    if deck is None:
        return JsonResponse({"error": "Claim a handle first."}, status=400)

    valid_ids = [i for i in item_ids if isinstance(i, int)]
    order_by_id = {iid: pos for pos, iid in enumerate(valid_ids)}
    updated = 0
    with transaction.atomic():
        for item in deck.items.filter(id__in=valid_ids):
            item.order = order_by_id[item.id]
            item.save(update_fields=["order"])
            updated += 1
    return JsonResponse({"ok": True, "updated": updated})


VERIFY_CHALLENGE_TTL_MINUTES = 30


@login_required
def api_deck_verify_challenge(request):
    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=405)

    deck = _get_user_deck(request.user)
    if deck is None:
        return JsonResponse({"error": "Claim a handle first."}, status=400)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "invalid JSON body"}, status=400)

    target_handle = normalize_handle(data.get("target_handle"))
    if not HANDLE_PATTERN.match(target_handle):
        return JsonResponse(
            {"error": "Handle must be 3-32 chars: lowercase letters, digits, '_' or '-'."},
            status=400,
        )
    if target_handle in RESERVED_HANDLES:
        return JsonResponse({"error": "That handle is reserved."}, status=400)

    external_url = (data.get("external_url") or "").strip()
    url_allowed, url_reason = validate_external_bio_url(external_url)
    if not url_allowed:
        return JsonResponse({"error": url_reason}, status=400)

    token = f"iyou-verify-wun-{uuid.uuid4().hex[:16]}"
    challenge = HandleVerificationChallenge.objects.create(
        deck=deck,
        token=token,
        target_handle=target_handle,
        external_url=external_url,
        expires_at=timezone.now() + timedelta(minutes=VERIFY_CHALLENGE_TTL_MINUTES),
    )
    return JsonResponse({
        "token": challenge.token,
        "target_handle": challenge.target_handle,
        "external_url": challenge.external_url,
        "expires_at": challenge.expires_at.isoformat(),
        "instructions": (
            "Paste this token into your public bio on the linked profile, "
            "then run Check & Claim Handle before it expires."
        ),
    })


@login_required
def api_deck_verify_confirm(request):
    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=405)

    deck = _get_user_deck(request.user)
    if deck is None:
        return JsonResponse({"error": "Claim a handle first."}, status=400)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "invalid JSON body"}, status=400)

    token = (data.get("token") or "").strip()
    if not token:
        return JsonResponse({"error": "token is required"}, status=400)

    challenge = deck.challenges.filter(token=token).first()
    if challenge is None:
        return JsonResponse({"error": "No pending challenge found for this token."}, status=404)
    if challenge.is_completed:
        return JsonResponse({"error": "Challenge already completed."}, status=400)
    if challenge.expires_at <= timezone.now():
        return JsonResponse(
            {"error": "Challenge expired. Generate a new token."}, status=400
        )

    verified, reason = verify_external_profile_token(challenge.external_url, challenge.token)
    if not verified:
        return JsonResponse({"valid": False, "error": reason}, status=400)

    try:
        with transaction.atomic():
            squatter = (
                UserLinkDeck.objects.select_for_update()
                .filter(handle=challenge.target_handle, discriminator=0)
                .exclude(pk=deck.pk)
                .first()
            )
            if squatter is not None:
                max_disc = (
                    UserLinkDeck.objects.filter(handle=challenge.target_handle)
                    .aggregate(Max("discriminator"))["discriminator__max"]
                    or 0
                )
                squatter.discriminator = max_disc + 1
                squatter.save(update_fields=["discriminator", "updated_at"])

            deck.handle = challenge.target_handle
            deck.discriminator = 0
            deck.is_verified = True
            deck.verified_source_url = challenge.external_url
            deck.verified_at = timezone.now()
            deck.save()

            challenge.is_completed = True
            challenge.save(update_fields=["is_completed"])
    except IntegrityError:
        return JsonResponse(
            {"valid": False, "error": "Handle ownership changed during verification. Try again."},
            status=409,
        )

    return JsonResponse({
        "valid": True,
        "handle": deck.handle,
        "discriminator": deck.discriminator,
        "is_verified": True,
        "canonical_url": deck.canonical_path,
    })


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
    """Extract Nostr hex pubkey from a DID (did:key:z6Mk..., did:iyou:0x...) or hex string."""
    if not did or not isinstance(did, str):
        return None

    did = did.strip()
    if re.match(r"^[0-9a-fA-F]{64}$", did):
        return did.lower()

    if did.startswith("did:iyou:0x"):
        hex_part = did.split("did:iyou:0x", 1)[1].strip()
        if len(hex_part) == 64 and all(c in "0123456789abcdefABCDEF" for c in hex_part):
            return hex_part.lower()
        if len(hex_part) < 64 and all(c in "0123456789abcdefABCDEF" for c in hex_part):
            return hex_part.zfill(64).lower()

    if not did.startswith("did:key:z"):
        return None

    try:
        # Extract the multibase part (after z)
        encoded = did.split("z", 1)[1]
        if len(encoded) % 4 == 1:
            encoded = encoded[:-1]
        padding = (4 - len(encoded) % 4) % 4
        if padding:
            encoded += "=" * padding

        # Convert from base64url to standard base64
        decoded_bytes = base64.urlsafe_b64decode(encoded)

        # Nostr pubkeys are 32 bytes (64 hex chars) for secp256k1
        if len(decoded_bytes) > 32:
            return decoded_bytes[-32:].hex()
        elif len(decoded_bytes) < 32:
            return decoded_bytes.hex().rjust(64, "0")

        return decoded_bytes.hex()
    except Exception:
        return None




def did_to_npub(did):
    """Convert DID directly to npub format."""
    hex_pubkey = did_to_pubkey(did)
    if hex_pubkey:
        return hex_to_npub(hex_pubkey)
    return None


def nip05_well_known(request):
    """NIP-05 identity verification document, served at /.well-known/nostr.json.

    External clients (Damus, Primal, Amethyst) query this to confirm that a
    handle maps to a public key. Intentionally public: no login required.
    """
    name = request.GET.get("name", "").strip().lower()
    payload = {"names": {}, "relays": {}, "nip46": {}}

    if name:
        deck = (
            UserLinkDeck.objects.filter(is_public=True)
            .filter(Q(handle__iexact=name) | Q(user__username__iexact=name))
            .select_related("user")
            .first()
        )
        if deck:
            username = deck.user.username or ""
            if re.match(r"^[0-9a-fA-F]{64}$", username):
                pubkey_hex = username.lower()
            elif username.startswith("did:"):
                pubkey_hex = did_to_pubkey(username)
            elif username.startswith("npub1"):
                pubkey_hex = npub_to_hex(username)
            else:
                pubkey_hex = None

            if pubkey_hex:
                payload["names"][name] = pubkey_hex
                payload["relays"][pubkey_hex] = [
                    "wss://relay.iyou.me",
                    "wss://nos.lol",
                    "wss://relay.damus.io",
                ]

    response = JsonResponse(payload)
    response["Access-Control-Allow-Origin"] = "*"
    response["Content-Type"] = "application/json; charset=utf-8"
    return response


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


@method_decorator(csrf_exempt, name="dispatch")
class MediaUploadProxyView(View):
    """Server-side proxy for Blossom media uploads to handle mixed content and PNA blocking."""

    def post(self, request):
        uploaded_file = request.FILES.get("file")
        if not uploaded_file and request.FILES:
            uploaded_file = next(iter(request.FILES.values()))

        if uploaded_file:
            content = uploaded_file.read()
            mime_type = uploaded_file.content_type or "application/octet-stream"
            size = uploaded_file.size
        else:
            try:
                content = request.body
            except Exception:
                content = b""
            if content:
                mime_type = request.content_type or "application/octet-stream"
                size = len(content)
            else:
                return JsonResponse({"error": "No file provided"}, status=400)


        sha256_hex = hashlib.sha256(content).hexdigest()
        blossom_server_url = getattr(settings, "BLOSSOM_SERVER_URL", "http://127.0.0.1:9002").rstrip("/")
        cdn_base = getattr(settings, "BLOSSOM_CDN_URL", "https://cdn.iyou.me").rstrip("/")

        # Forward binary stream to upstream Blossom server
        try:
            req = urllib.request.Request(
                f"{blossom_server_url}/upload",
                data=content,
                headers={
                    "Content-Type": mime_type,
                    "X-SHA-256": sha256_hex,
                },
                method="PUT",
            )
            with urllib.request.urlopen(req, timeout=10):
                pass
        except urllib.error.HTTPError as exc:
            if exc.code in (404, 405):
                try:
                    req_hash = urllib.request.Request(
                        f"{blossom_server_url}/{sha256_hex}",
                        data=content,
                        headers={
                            "Content-Type": mime_type,
                            "X-SHA-256": sha256_hex,
                        },
                        method="PUT",
                    )
                    with urllib.request.urlopen(req_hash, timeout=10):
                        pass
                except Exception:
                    pass
        except Exception:
            # When Blossom server is unreachable, allow graceful degradation
            pass

        return JsonResponse(
            {
                "url": f"{cdn_base}/{sha256_hex}",
                "sha256": sha256_hex,
                "size": size,
                "type": mime_type,
            },
            status=200,
        )

    def get(self, request):
        return JsonResponse({"error": "POST required"}, status=405)

