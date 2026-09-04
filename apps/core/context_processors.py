from django.conf import settings


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
    }


def user_identity(request):
    context = {}
    if not request.user.is_authenticated:
        context["user_display_label"] = ""
        context["current_session_did"] = ""
        return context
    from .views import did_to_pubkey, hex_to_npub
    from .models import UserLinkDeck

    deck = UserLinkDeck.objects.filter(user=request.user).first()
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

    pubkey = did_to_pubkey(request.user.username)
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

    context.update(
        user_display_label=display_label,
        active_persona_level=level,
        active_persona_name=persona_name,
        current_session_did=request.user.username,
        user_pubkey_hex=pubkey,
        user_npub=npub,
        user_handle=legacy_handle,
        user_profile_url=f"/profile/{npub}/" if npub else "/dashboard",
        is_dependent=dep_ctx["is_dependent"],
        dependent_bracket=dep_ctx["bracket"],
        wot_distance_limit=limit,
        wot_distance_limit_json=limit_json,
        parent_did=dep_ctx.get("parent_did") or "",
    )
    return context



