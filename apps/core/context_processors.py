from django.conf import settings


def satellite_urls(request):
    return {
        "idp_home_url": getattr(settings, "IDP_HOME_URL", "https://home.iyou.me/"),
        "idp_home_ws_url": getattr(settings, "IDP_HOME_WS_URL", "wss://home.iyou.me:9001/"),
        "BRIDGE_WS_URL": getattr(settings, "BRIDGE_WS_URL", getattr(settings, "IDP_HOME_WS_URL", "wss://home.iyou.me:9001/")),
        "xmpp_domain": getattr(settings, "XMPP_DOMAIN", "127.0.0.1"),
        "xmpp_ws_url": getattr(settings, "XMPP_WS_URL", "ws://127.0.0.1:5222"),
        "blossom_server_url": getattr(settings, "BLOSSOM_SERVER_URL", "http://127.0.0.1:9002"),
        "BLOSSOM_SERVER_URL": getattr(settings, "BLOSSOM_SERVER_URL", "http://127.0.0.1:9002"),
        "blossom_cdn_url": getattr(settings, "BLOSSOM_CDN_URL", "https://cdn.iyou.me"),
        "BLOSSOM_CDN_URL": getattr(settings, "BLOSSOM_CDN_URL", "https://cdn.iyou.me"),
    }

