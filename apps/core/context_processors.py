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
    if not request.user.is_authenticated:
        return {}
    from .views import did_to_pubkey, hex_to_npub
    from .models import UserLinkDeck

    pubkey = did_to_pubkey(request.user.username)
    npub = hex_to_npub(pubkey) if pubkey else ""
    deck = UserLinkDeck.objects.filter(user=request.user).first()
    handle = deck.handle if deck else ""

    return {
        "user_pubkey_hex": pubkey,
        "user_npub": npub,
        "user_handle": handle,
        "user_profile_url": f"/profile/{npub}/" if npub else "/dashboard",
    }



