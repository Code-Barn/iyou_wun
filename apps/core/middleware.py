"""Geographic Subdomain Routing & Jurisdictional Containment Middleware.

Intercepts all HTTP requests, tokenizing host subdomains right-to-left against
WUN_BASE_DOMAIN to enforce jurisdictional scoping and fail closed on invalid regions.
Conforms strictly to ecosystem specification SPEC-008.
"""

from __future__ import annotations

import ipaddress
from typing import Callable

from django.conf import settings
from django.http import Http404, HttpRequest, HttpResponse

from .geo_data import JURISDICTION_TIERS, SYSTEM_SUBDOMAINS, VALID_COUNTRIES, VALID_US_STATES


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


class GeographicRoutingMiddleware:
    """Extracts geographic locality from right-to-left subdomain tokens."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        try:
            host = request.get_host().split(":")[0].strip().lower()
        except Exception:
            host = (request.META.get("HTTP_HOST") or "localhost").split(":")[0].strip().lower()
        raw_host = host

        base_domain = getattr(settings, "WUN_BASE_DOMAIN", "wun.iyou.me").lower()

        # 1. Health checks and cluster probes bypass for un-scoped hosts
        is_scoped_host = raw_host.endswith("." + base_domain) or raw_host.endswith(".localhost") or raw_host.endswith(".testserver")
        if request.path_info == "/health/" or (request.path_info == "/healthz" and not is_scoped_host):
            self._set_global_scope(request)
            return self.get_response(request)

        # 2. Development, cluster IP, and apex root bypass
        if (
            host == base_domain
            or host in ("localhost", "127.0.0.1", "testserver")
            or _is_ip(host)
            or host.endswith(".cluster.local")
        ):
            self._set_global_scope(request)
            return self.get_response(request)

        # 3. Strip base domain / localhost dev suffix
        subdomain = ""
        if host.endswith("." + base_domain):
            subdomain = host[: -len("." + base_domain)]
        elif host.endswith(".localhost"):
            subdomain = host[: -len(".localhost")]
        elif host.endswith(".testserver"):
            subdomain = host[: -len(".testserver")]
        else:
            self._set_global_scope(request)
            return self.get_response(request)

        # Strip www. / www if present
        if subdomain.startswith("www."):
            subdomain = subdomain[4:]
        elif subdomain == "www":
            subdomain = ""

        if not subdomain:
            self._set_global_scope(request)
            return self.get_response(request)

        # 4. Check for system subdomains
        tokens = subdomain.split(".")
        if tokens[0] in SYSTEM_SUBDOMAINS or tokens[-1] in SYSTEM_SUBDOMAINS:
            self._set_global_scope(request)
            return self.get_response(request)

        # 5. Right-to-left evaluation
        # Country token (tokens[-1])
        country = tokens[-1]
        if country not in VALID_COUNTRIES:
            raise Http404(f"Invalid country code in geographic scope: '{country}'")

        # State token (tokens[-2])
        if len(tokens) >= 2 and country == "us":
            state = tokens[-2]
            if state not in VALID_US_STATES:
                raise Http404(f"Invalid state code in geographic scope: '{state}'")

        # 6. Reconstruct canonical scope & jurisdiction level
        depth = len(tokens)
        if tokens[0].startswith("ward") or depth >= 5:
            jurisdiction_level = "ward"
        elif depth == 4:
            jurisdiction_level = "city"
        elif depth == 3:
            jurisdiction_level = "county"
        elif depth == 2:
            jurisdiction_level = "state"
        elif depth == 1:
            jurisdiction_level = "country"
        else:
            jurisdiction_level = JURISDICTION_TIERS.get(depth, "locality")

        request.geographic_scope = ".".join(tokens)
        request.scope_tokens = tuple(tokens)
        request.jurisdiction_level = jurisdiction_level

        return self.get_response(request)

    @staticmethod
    def _set_global_scope(request: HttpRequest) -> None:
        request.geographic_scope = None
        request.scope_tokens = ()
        request.jurisdiction_level = None
