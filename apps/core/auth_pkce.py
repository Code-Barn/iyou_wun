import logging
import secrets
from urllib.parse import urlencode

from django.conf import settings
from django.contrib.auth import logout
from django.http import HttpResponseRedirect
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


class PKCEOIDCAuthenticationRequestView(OIDCAuthenticationRequestView):
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

        request.session["oidc_login_next"] = self.get_next_url(request, redirect_field_name)
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

    def login_success(self):
        if hasattr(self, "request") and self.request and hasattr(self.request, "session"):
            raw_id_token = self.request.session.get("oidc_id_token")
            if raw_id_token and "dependent_context" not in self.request.session:
                from apps.core.context import store_dependent_context
                try:
                    store_dependent_context(self.request.session, raw_id_token)
                except Exception as exc:
                    logger.debug(f"Could not parse dependent context from oidc_id_token: {exc}")
        return super().login_success()


class PKCEOIDCLogoutView(OIDCLogoutView):
    """
    Handles both GET and POST requests for user logout.
    Flushes the local Django session and redirects to LOGOUT_REDIRECT_URL.
    """
    def get(self, request, *args, **kwargs):
        return self.post(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        from apps.core.context import clear_dependent_context
        clear_dependent_context(request.session)
        logout(request)
        redirect_url = getattr(settings, "LOGOUT_REDIRECT_URL", "/")
        return redirect(redirect_url)


class PKCEAuthenticationBackend(MyOIDCAuthenticationBackend):
    pass

