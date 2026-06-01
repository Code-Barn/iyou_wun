from django.conf import settings


def satellite_urls(request):
    return {
        "idp_home_url": settings.IDP_HOME_URL,
        "idp_home_ws_url": settings.IDP_HOME_WS_URL,
        "xmpp_domain": settings.XMPP_DOMAIN,
        "xmpp_ws_url": settings.XMPP_WS_URL,
    }
