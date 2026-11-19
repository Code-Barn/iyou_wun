from django.conf import settings


def bookmark_ids(request):
    """Set of the signed-in user's bookmarked event_ids for kebab-menu toggling."""
    if not request.user.is_authenticated:
        return {"user_bookmark_ids": set()}
    from .models import Bookmark

    ids = Bookmark.objects.filter(user=request.user).values_list("event_id", flat=True)[:200]
    return {"user_bookmark_ids": set(ids)}


def satellite_urls(request):
    level = getattr(settings, "WUN_USER_LEVEL", "2")
    if level == "1":
        xmpp_domain = "iyou.me"
        xmpp_ws_url = "wss://xmpp.iyou.me:5222/xmpp-websocket"
    else:
        xmpp_domain = "127.0.0.1"
        xmpp_ws_url = "wss://home.iyou.me:5222/xmpp-websocket"

    return {
        "idp_home_url": getattr(settings, "IDP_HOME_URL", "https://home.iyou.me/"),
        "idp_home_ws_url": getattr(settings, "IDP_HOME_WS_URL", "wss://home.iyou.me:9001/"),
        "BRIDGE_WS_URL": getattr(settings, "BRIDGE_WS_URL", getattr(settings, "IDP_HOME_WS_URL", "wss://home.iyou.me:9001/")),
        "xmpp_domain": xmpp_domain,
        "xmpp_ws_url": xmpp_ws_url,
        "xmpp_bosh_url": getattr(settings, "XMPP_BOSH_URL", ""),
        "blossom_server_url": getattr(settings, "BLOSSOM_SERVER_URL", "http://127.0.0.1:9002"),
        "BLOSSOM_SERVER_URL": getattr(settings, "BLOSSOM_SERVER_URL", "http://127.0.0.1:9002"),
        "blossom_cdn_url": getattr(settings, "BLOSSOM_CDN_URL", "https://cdn.iyou.me"),
        "BLOSSOM_CDN_URL": getattr(settings, "BLOSSOM_CDN_URL", "https://cdn.iyou.me"),
        "POLY_BASE_DOMAIN": getattr(settings, "POLY_BASE_DOMAIN", "poly.iyou.me"),
        "IYOU_CHAT_ORIGIN": getattr(
            settings,
            "IYOU_CHAT_ORIGIN",
            "http://127.0.0.1:8017" if getattr(settings, "DEBUG", False) else "https://chat.iyou.me",
        ),
        "iyou_chat_origin": getattr(
            settings,
            "IYOU_CHAT_ORIGIN",
            "http://127.0.0.1:8017" if getattr(settings, "DEBUG", False) else "https://chat.iyou.me",
        ),
    }



def user_identity(request):
    import json
    from .identity import get_ecosystem_pubkeys

    ecosystem_pubkeys = sorted(list(get_ecosystem_pubkeys()))
    ecosystem_pubkeys_json = json.dumps(ecosystem_pubkeys)

    context = {
        "SHOW_L2_TOGGLE": getattr(settings, "SHOW_L2_TOGGLE", True),
        "ecosystem_pubkeys_json": ecosystem_pubkeys_json,
    }
    if not request.user.is_authenticated:
        context["user_display_label"] = ""
        context["current_session_did"] = ""
        context["user_avatar_url"] = ""
        context["account_tier"] = ""
        context["user_account_tier"] = ""
        context["user_did"] = ""
        context["user_pubkey"] = ""
        context["is_custodial"] = False
        return context
    from .views import hex_to_npub
    from .models import UserLinkDeck

    deck = UserLinkDeck.objects.filter(user=request.user).first()
    avatar_url = deck.avatar_url if (deck and deck.avatar_url) else ""
    handle = ""
    if deck and deck.handle:
        handle = f"@{deck.handle.lstrip('@')}"

    persona_name = request.session.get("active_persona_name", "")
    level = request.session.get("active_persona_level", 1)
    try:
        level = int(level)
    except (TypeError, ValueError):
        level = 1

    if handle:
        display_label = handle
    elif persona_name:
        display_label = f"{persona_name} (L{level})"
    elif level == 1:
        display_label = "Primary Identity (L1)"
    else:
        display_label = f"{request.user.username[:16]}... (L{level})"

    if deck and deck.display_name:
        display_name = deck.display_name
    elif deck and deck.handle:
        display_name = deck.handle.lstrip("@")
    elif persona_name:
        display_name = persona_name
    else:
        display_name = ""

    session_did = (
        request.session.get("custodial_did")
        if hasattr(request, "session")
        else None
    )
    username = getattr(request.user, "username", "") or ""
    user_did = session_did or username
    is_did_key = str(user_did).startswith("did:key:") or str(username).startswith("did:key:")

    account_tier = request.session.get("account_tier") if hasattr(request, "session") else None
    if is_did_key:
        if not account_tier or account_tier in ("managed_free", "none"):
            account_tier = "sovereign"
            if hasattr(request, "session"):
                request.session["account_tier"] = "sovereign"
                if hasattr(request.session, "modified"):
                    request.session.modified = True

    from .custodial_keys import (
        get_custodial_pubkey,
        get_or_create_custodial_keypair,
        is_managed_account,
    )
    from .views import get_effective_user_pubkey

    pubkey = get_effective_user_pubkey(request)
    is_custodial = False if is_did_key else is_managed_account(request.user, request)
    if not account_tier:
        account_tier = "managed_free" if is_custodial else "sovereign"
    if is_custodial:
        # Tier 1 accounts have no enclave key. Provision lazily (idempotent) and
        # fall back to their custodial secp256k1 key when no enclave key exists.
        try:
            get_or_create_custodial_keypair(request.user)
        except Exception:
            pass
        if not pubkey:
            pubkey = get_custodial_pubkey(request.user)
    npub = hex_to_npub(pubkey) if pubkey else ""
    legacy_handle = ""
    if deck and deck.handle:
        legacy_handle = deck.handle.lstrip("@")
    elif request.user.username and not request.user.username.startswith("did:"):
        legacy_handle = request.user.username

    from .context import get_dependent_context
    dep_ctx = get_dependent_context(request)
    limit = dep_ctx["wot_distance_limit"]
    limit_json = "Infinity" if limit == float("inf") else str(limit)

    from django.urls import reverse
    profile_target = legacy_handle or npub or pubkey or request.user.username
    try:
        user_profile_url = reverse("profile", kwargs={"npub": profile_target}) if profile_target else "/dashboard"
    except Exception:
        user_profile_url = f"/profile/{profile_target}/" if profile_target else "/dashboard"

    context.update(
        user_display_label=display_label,
        user_display_name=display_name,
        user_is_verified=bool(deck and deck.is_verified),
        active_persona_level=level,
        active_persona_name=persona_name,
        current_session_did=request.user.username,
        account_tier=account_tier,
        user_account_tier="L1" if is_custodial else "L2",
        user_did=user_did,
        user_pubkey=pubkey,
        is_custodial=is_custodial,
        user_pubkey_hex=pubkey,
        user_npub=npub,
        user_handle=legacy_handle,
        user_profile_url=user_profile_url,
        user_avatar_url=avatar_url,
        is_dependent=dep_ctx["is_dependent"],
        dependent_bracket=dep_ctx["bracket"],
        wot_distance_limit=limit,
        wot_distance_limit_json=limit_json,
        parent_did=dep_ctx.get("parent_did") or "",
        ecosystem_pubkeys_json=ecosystem_pubkeys_json,
    )
    return context


def geographic_context(request):
    return {
        "GEOGRAPHIC_SCOPE": getattr(request, "geographic_scope", "") or "",
        "JURISDICTION_LEVEL": getattr(request, "jurisdiction_level", "") or "",
        "POLY_BASE_DOMAIN": getattr(settings, "POLY_BASE_DOMAIN", "poly.iyou.me"),
    }




