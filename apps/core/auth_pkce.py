import logging
import secrets
from typing import Any
from urllib.parse import urlencode

from django.conf import settings
from django.contrib.auth import logout
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.shortcuts import redirect
from django.urls import reverse
from mozilla_django_oidc.utils import absolutify, import_from_settings
from mozilla_django_oidc.views import (
    OIDCAuthenticationCallbackView,
    OIDCAuthenticationRequestView,
    OIDCLogoutView,
    add_state_and_verifier_and_nonce_to_session,
    generate_code_challenge,
)

from apps.core.auth import MyOIDCAuthenticationBackend

logger = logging.getLogger(__name__)

# Loop-safe silent SSO state (canonical SSOT: docs/ecosystem_shared/auth_pkce.py).
SESSION_KEY_SSO_SILENT_ATTEMPTED = "sso_silent_attempted"
SESSION_KEY_SSO_SILENT_INFLIGHT = "sso_silent_inflight"
SESSION_KEY_OIDC_LOGIN_NEXT = "oidc_login_next"
SSO_HINT_COOKIE = "iyou_sso_hint"
SILENT_SSO_ERRORS = {
    "login_required",
    "interaction_required",
    "consent_required",
    "account_selection_required",
}


class PKCEOIDCAuthenticationRequestView(OIDCAuthenticationRequestView):
    def get_extra_params(self, request):
        """Attach ``prompt=none`` only to a one-shot silent SSO attempt.

        Interactive clicks on the Layer 1 ``Authenticate`` link never carry
        ``prompt=none`` because the inflight flag is only latched by
        ``SilentSSOMiddleware``.
        """
        params = dict(super().get_extra_params(request) or {})
        if request.session.pop(SESSION_KEY_SSO_SILENT_INFLIGHT, False):
            params["prompt"] = "none"
        return params

    def get(self, request):
        state = import_from_settings("OIDC_STATE_SIZE", 32)
        state = secrets.token_urlsafe(state) if isinstance(state, int) else state
        redirect_field_name = self.get_settings("OIDC_REDIRECT_FIELD_NAME", "next")
        reverse_url = self.get_settings(
            "OIDC_AUTHENTICATION_CALLBACK_URL", "oidc_authentication_callback"
        )

        params = {
            "response_type": "code",
            "scope": self.get_settings("OIDC_RP_SCOPES", "openid email"),
            "client_id": self.OIDC_RP_CLIENT_ID,
            "redirect_uri": absolutify(request, reverse(reverse_url)),
            "state": state,
        }

        params.update(self.get_extra_params(request))

        if self.get_settings("OIDC_USE_NONCE", True):
            nonce_size = self.get_settings("OIDC_NONCE_SIZE", 32)
            nonce = secrets.token_urlsafe(nonce_size) if isinstance(nonce_size, int) else nonce_size
            params.update({"nonce": nonce})

        code_verifier = secrets.token_urlsafe(64)
        code_challenge = generate_code_challenge(code_verifier, "S256")

        params.update({
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        })

        request.session["pkce_code_verifier"] = code_verifier

        add_state_and_verifier_and_nonce_to_session(request, state, params, code_verifier)

        request.session[SESSION_KEY_OIDC_LOGIN_NEXT] = self.get_next_url(request, redirect_field_name)
        request.session.save()

        redirect_url = "{url}?{query}".format(
            url=self.OIDC_OP_AUTH_ENDPOINT, query=urlencode(params)
        )
        return HttpResponseRedirect(redirect_url)

    def get_next_url(self, request, redirect_field_name):
        from mozilla_django_oidc.views import get_next_url
        return get_next_url(request, redirect_field_name)


class PKCEOIDCAuthenticationCallbackView(OIDCAuthenticationCallbackView):
    def get_backend_kwargs(self, *args, **kwargs):
        base_kwargs = super().get_backend_kwargs(*args, **kwargs) if hasattr(super(), "get_backend_kwargs") else {}
        base_kwargs['pkce_code_verifier'] = self.request.session.pop('pkce_code_verifier', None)
        return base_kwargs

    @property
    def success_url(self):
        next_url = self.request.session.get("oidc_login_next")
        if next_url and next_url not in ("/", ""):
            return next_url
        return getattr(settings, "LOGIN_REDIRECT_URL", "/?map=open")

    def login_success(self):
        # Clear silent-SSO latches so a later logout/re-login starts clean.
        if hasattr(self, "request") and self.request and hasattr(self.request, "session"):
            self.request.session.pop(SESSION_KEY_SSO_SILENT_ATTEMPTED, None)
            self.request.session.pop(SESSION_KEY_SSO_SILENT_INFLIGHT, None)
        if hasattr(self, "request") and self.request and hasattr(self.request, "session"):
            raw_id_token = self.request.session.get("oidc_id_token")
            claims = {}
            if raw_id_token:
                from apps.core.context import decode_jwt_unverified
                try:
                    claims = decode_jwt_unverified(raw_id_token) if isinstance(raw_id_token, str) else raw_id_token
                except Exception as exc:
                    logger.debug(f"Could not parse claims from oidc_id_token: {exc}")
                if not isinstance(claims, dict):
                    claims = {}
                if "dependent_context" not in self.request.session and "dep" in claims:
                    from apps.core.context import store_dependent_context
                    try:
                        store_dependent_context(self.request.session, claims)
                    except Exception as exc:
                        logger.debug(f"Could not parse dependent context from oidc_id_token: {exc}")
                if "verified_public_emails" not in self.request.session and "public_emails" in claims:
                    self.request.session["verified_public_emails"] = claims.get("public_emails", [])

            tier = claims.get("account_tier") if isinstance(claims, dict) else None
            subject = str(
                (claims.get("sub") if isinstance(claims, dict) else None)
                or self.request.session.get("custodial_did")
                or getattr(getattr(self.request, "user", None), "username", "")
                or ""
            )
            if subject.startswith("did:key:") and (not tier or tier in {"managed_free", "none"}):
                tier = "sovereign"
            if tier:
                self.request.session["account_tier"] = tier
                if hasattr(self.request.session, "modified"):
                    self.request.session.modified = True
        return super().login_success()

    def login_failure(self):
        """Recover cleanly from a silent ``prompt=none`` probe.

        iyou_idp answers ``login_required`` / ``interaction_required`` when no
        master session exists. For a silent attempt this is not an error: latch
        the session, return to the originally requested URL, and show no error
        banner. Interactive failures keep the library's normal behavior.
        """
        request = getattr(self, "request", None)
        if (
            request is not None
            and hasattr(request, "session")
            and request.GET.get("error") in SILENT_SSO_ERRORS
            and (
                request.session.pop(SESSION_KEY_SSO_SILENT_INFLIGHT, False)
                or request.COOKIES.get(SSO_HINT_COOKIE) == "1"
            )
        ):
            request.session[SESSION_KEY_SSO_SILENT_ATTEMPTED] = True
            next_url = request.session.pop(SESSION_KEY_OIDC_LOGIN_NEXT, None)
            return HttpResponseRedirect(
                next_url or getattr(settings, "LOGIN_REDIRECT_URL", "/")
            )
        return super().login_failure()


class PKCEOIDCLogoutView(OIDCLogoutView):
    """Seamless GET/POST logout with federated IdP session termination.

    Flushes WUN's local session + dependent context, then chains to the master
    IdP's ``/auth/logout/?next=...`` so a still-authenticated IdP cannot
    silently restore the user on another satellite. The silent-SSO hint cookie
    is removed in the same response.
    """
    def get(self, request, *args, **kwargs):
        return self.post(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        from apps.core.context import clear_dependent_context
        clear_dependent_context(request.session)
        logout(request)
        idp_base = getattr(settings, "IDP_BASE_PUBLIC_URL", "https://iyou.me").rstrip("/")
        next_url = getattr(settings, "IDP_LOGOUT_RETURN_URL", "/")
        response = redirect(f"{idp_base}/auth/logout/?{urlencode({'next': next_url})}")
        response.delete_cookie(
            SSO_HINT_COOKIE,
            domain=None if getattr(settings, "DEBUG", False) else ".iyou.me",
        )
        return response


class PKCEAuthenticationBackend(MyOIDCAuthenticationBackend):
    def get_userinfo(self, access_token, id_token, payload):
        user_info = super().get_userinfo(access_token, id_token, payload)
        if isinstance(user_info, dict) and hasattr(self, "request") and self.request and hasattr(self.request, "session"):
            public_emails = user_info.get("public_emails", [])
            self.request.session["verified_public_emails"] = public_emails
        return user_info


class SilentSSOMiddleware:
    """One-shot, loop-safe ``prompt=none`` probe for anonymous GET requests.

    Runs after ``SessionMiddleware`` and ``AuthenticationMiddleware``. A
    returning visitor with ``iyou_sso_hint=1`` gets exactly one silent chance
    to re-authenticate from the master IdP session; both the in-flight redirect
    and its outcome are latched so probes cannot recur in one session.
    """

    EXEMPT_PREFIXES = (
        "/oidc/authenticate/",
        "/oidc/callback/",
        "/oidc/logout/",
        "/auth/logout/",
        "/admin/",
        "/static/",
        "/health",
    )

    def __init__(self, get_response: Any) -> None:
        self.get_response = get_response
        self.enabled = getattr(settings, "SSO_SILENT_ENABLED", True)

    def __call__(self, request: HttpRequest) -> HttpResponse:
        if self.enabled and self._should_probe(request):
            session = request.session
            session[SESSION_KEY_SSO_SILENT_INFLIGHT] = True
            session[SESSION_KEY_OIDC_LOGIN_NEXT] = request.get_full_path()
            session.save()
            return HttpResponseRedirect(reverse("oidc_authentication_init"))
        return self.get_response(request)

    def _should_probe(self, request: HttpRequest) -> bool:
        if getattr(request, "method", None) != "GET":
            return False
        path = str(getattr(request, "path", "") or "")
        if any(path.startswith(prefix) for prefix in self.EXEMPT_PREFIXES):
            return False
        if "error" in getattr(request, "GET", {}):
            return False

        user = getattr(request, "user", None)
        if user is None or getattr(user, "is_authenticated", False):
            return False
        if getattr(request, "COOKIES", {}).get(SSO_HINT_COOKIE) != "1":
            return False

        session = getattr(request, "session", None)
        if session is None:
            return False
        if session.get(SESSION_KEY_SSO_SILENT_ATTEMPTED):
            return False
        if session.get(SESSION_KEY_SSO_SILENT_INFLIGHT):
            return False
        return True


