import base64
import hashlib
import logging
import secrets

from django.urls import reverse
from mozilla_django_oidc.views import (
    OIDCAuthenticationCallbackView,
    OIDCAuthenticationRequestView,
    add_state_and_verifier_and_nonce_to_session,
    generate_code_challenge,
)
from mozilla_django_oidc.utils import absolutify, import_from_settings

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

        from urllib.parse import urlencode
        from django.http import HttpResponseRedirect

        redirect_url = "{url}?{query}".format(
            url=self.OIDC_OP_AUTH_ENDPOINT, query=urlencode(params)
        )
        return HttpResponseRedirect(redirect_url)

    def get_next_url(self, request, redirect_field_name):
        from mozilla_django_oidc.utils import get_next_url
        return get_next_url(request, redirect_field_name)


class PKCEOIDCAuthenticationCallbackView(OIDCAuthenticationCallbackView):
    def get(self, request):
        code_verifier = request.session.pop("pkce_code_verifier", None)
        return super().get(request)


class PKCEAuthenticationBackend(MyOIDCAuthenticationBackend):
    def __init__(self, *args, **kwargs):
        self.OIDC_OP_TOKEN_ENDPOINT = self.get_settings("OIDC_OP_TOKEN_ENDPOINT")
        self.OIDC_OP_USER_ENDPOINT = self.get_settings("OIDC_OP_USER_ENDPOINT")
        self.OIDC_OP_JWKS_ENDPOINT = self.get_settings("OIDC_OP_JWKS_ENDPOINT", None)
        self.OIDC_RP_CLIENT_ID = self.get_settings("OIDC_RP_CLIENT_ID")
        self.OIDC_RP_CLIENT_SECRET = self.get_settings("OIDC_RP_CLIENT_SECRET", "")
        self.OIDC_RP_SIGN_ALGO = self.get_settings("OIDC_RP_SIGN_ALGO", "HS256")
        self.OIDC_RP_IDP_SIGN_KEY = self.get_settings("OIDC_RP_IDP_SIGN_KEY", None)

        from django.contrib.auth import get_user_model
        self.UserModel = get_user_model()
