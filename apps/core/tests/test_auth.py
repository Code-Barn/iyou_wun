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

from django.conf import settings
from django.contrib.auth.models import AnonymousUser, User
from django.contrib.messages import get_messages
from django.http import HttpResponse
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from ..auth import MyOIDCAuthenticationBackend
from .helpers import make_claims


class MyOIDCAuthenticationBackendTest(TestCase):
    def test_create_user_uses_sub_claim_as_username(self):
        backend = MyOIDCAuthenticationBackend()
        claims = {"sub": "did:iyou:0x123456789abcdef"}
        user = backend.create_user(claims)
        self.assertEqual(user.username, "did:iyou:0x123456789abcdef")
        self.assertTrue(user.is_active)

    def test_create_user_with_different_did_format(self):
        backend = MyOIDCAuthenticationBackend()
        claims = {"sub": "did:key:z6MkhaXgBZDvB9gGHgK9r"}
        user = backend.create_user(claims)
        self.assertEqual(user.username, "did:key:z6MkhaXgBZDvB9gGHgK9r")

    def test_create_user_sets_active_true(self):
        backend = MyOIDCAuthenticationBackend()
        claims = {"sub": "did:example:alice"}
        user = backend.create_user(claims)
        self.assertTrue(user.is_active)

    def test_create_user_persists_to_database(self):
        backend = MyOIDCAuthenticationBackend()
        claims = {"sub": "did:iyou:0xpersist"}
        backend.create_user(claims)
        self.assertTrue(User.objects.filter(username="did:iyou:0xpersist").exists())

    def test_create_user_raises_on_missing_sub(self):
        backend = MyOIDCAuthenticationBackend()
        with self.assertRaises(Exception):
            backend.create_user({})


class SovereignOnboardingTest(TestCase):
    """Test DID-based user creation and authentication flow."""

    def setUp(self):
        self.backend = MyOIDCAuthenticationBackend()
        self.did = "did:iyou:0x123456789abcdef"
        self.claims = {"sub": self.did}

    def test_filter_users_by_claims_returns_empty_when_no_user(self):
        users = self.backend.filter_users_by_claims(self.claims)
        self.assertEqual(len(users), 0)

    def test_filter_users_by_claims_returns_existing_user(self):
        existing_user = User.objects.create_user(username=self.did)
        existing_user.set_unusable_password()
        existing_user.save()
        users = self.backend.filter_users_by_claims(self.claims)
        self.assertEqual(len(users), 1)
        self.assertEqual(users[0].id, existing_user.id)

    def test_filter_users_by_claims_returns_empty_for_missing_sub(self):
        claims_no_sub = {"some": "claim"}
        users = self.backend.filter_users_by_claims(claims_no_sub)
        self.assertEqual(len(users), 0)

    def test_get_username_returns_did(self):
        username = self.backend.get_username(self.claims)
        self.assertEqual(username, self.did)

    def test_verify_claims_requires_sub(self):
        self.assertTrue(self.backend.verify_claims(self.claims))
        self.assertFalse(self.backend.verify_claims({"other": "claim"}))


class PasswordRejectionTest(TestCase):
    """WUN must reject password-based login and enforce OIDC-only auth."""

    def test_oidc_user_has_unusable_password(self):
        backend = MyOIDCAuthenticationBackend()
        claims = make_claims("did:key:z6Mkpwdreject1")
        user = backend.create_user(claims)
        self.assertFalse(user.has_usable_password())

    def test_created_user_sets_unusable_password(self):
        backend = MyOIDCAuthenticationBackend()
        claims = make_claims("did:key:z6Mkpwdreject2")
        user = backend.create_user(claims)
        self.assertFalse(user.has_usable_password())

    def test_existing_user_keeps_unusable_password(self):
        backend = MyOIDCAuthenticationBackend()
        claims = make_claims("did:key:z6Mkpwdreject3")
        user = User.objects.create_user(username=claims["sub"])
        user.set_unusable_password()
        user.save()
        users = backend.filter_users_by_claims(claims)
        self.assertEqual(len(users), 1)
        self.assertFalse(users[0].has_usable_password())

    def test_model_backend_cannot_auth_oidc_user(self):
        from django.contrib.auth.backends import ModelBackend
        user = User.objects.create_user(username="did:key:z6Mkmodelreject")
        user.set_unusable_password()
        user.save()
        backend = ModelBackend()
        result = backend.authenticate(
            request=None,
            username=user.username,
            password="any_password",
        )
        self.assertIsNone(result)


class OIDCBackendEnforcementTest(TestCase):
    """Only OIDC authentication backends should handle DID users."""

    def test_oidc_backend_is_configured(self):
        backends = settings.AUTHENTICATION_BACKENDS
        self.assertIn(
            "apps.core.auth.MyOIDCAuthenticationBackend",
            backends,
        )

    def test_login_url_points_to_idp(self):
        self.assertEqual(settings.LOGIN_URL, "oidc_authentication_init")

    def test_oidc_backend_creates_user_with_unusable_password(self):
        backend = MyOIDCAuthenticationBackend()
        claims = make_claims("did:key:z6Mkoidcenforce1")
        user = backend.create_user(claims)
        self.assertEqual(user.username, "did:key:z6Mkoidcenforce1")
        self.assertFalse(user.has_usable_password())


class OIDCLogoutViewTest(TestCase):
    EXPECTED_LOGOUT_URL = "https://iyou.me/auth/logout/?next=%2F"

    def _prime_session(self):
        session = self.client.session
        session["dependent_context"] = {"is_dependent": True, "bracket": "U14"}
        session.save()

    def test_logout_get_flushes_session_and_chains_to_idp(self):
        user = User.objects.create_user(username="did:key:z6Mklogoutget")
        self.client.force_login(user)
        self._prime_session()
        self.client.cookies["iyou_sso_hint"] = "1"
        response = self.client.get(reverse("oidc_logout"))
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(
            response, self.EXPECTED_LOGOUT_URL, fetch_redirect_response=False
        )
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertNotIn("dependent_context", self.client.session)
        self.assertEqual(response.cookies["iyou_sso_hint"].value, "")

    def test_logout_post_flushes_session_and_chains_to_idp(self):
        user = User.objects.create_user(username="did:key:z6Mklogoutpost")
        self.client.force_login(user)
        self._prime_session()
        self.client.cookies["iyou_sso_hint"] = "1"
        response = self.client.post(reverse("oidc_logout"))
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(
            response, self.EXPECTED_LOGOUT_URL, fetch_redirect_response=False
        )
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertNotIn("dependent_context", self.client.session)
        self.assertEqual(response.cookies["iyou_sso_hint"].value, "")

    def test_logout_aliases(self):
        user = User.objects.create_user(username="did:key:z6Mklogoutalias")
        self.client.force_login(user)
        response = self.client.get(reverse("logout"))
        self.assertEqual(response.status_code, 302)
        self.assertNotIn("_auth_user_id", self.client.session)

        self.client.force_login(user)
        response = self.client.get("/logout/")
        self.assertEqual(response.status_code, 302)
        self.assertNotIn("_auth_user_id", self.client.session)


class SilentSSOMiddlewareTest(TestCase):
    class FakeSession(dict):
        def save(self):
            pass

    def _middleware(self):
        from apps.core.auth_pkce import SilentSSOMiddleware

        return SilentSSOMiddleware(lambda request: HttpResponse("ok"))

    def _request(self, path="/feed", method="GET", user=None, hint=True, session=None):
        request = getattr(RequestFactory(), method.lower())(path)
        request.user = user if user is not None else AnonymousUser()
        if session is None:
            request.session = self.FakeSession()
        elif isinstance(session, self.FakeSession):
            request.session = session
        else:
            request.session = self.FakeSession(session)
        request.COOKIES = {"iyou_sso_hint": "1"} if hint else {}
        return request

    @override_settings(SSO_SILENT_ENABLED=True)
    def test_anonymous_with_hint_latches_inflight_and_redirects_once(self):
        middleware = self._middleware()
        session = self.FakeSession()
        request = self._request(session=session)
        response = middleware(request)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("oidc_authentication_init"))
        self.assertTrue(session["sso_silent_inflight"])
        self.assertEqual(session["oidc_login_next"], "/feed")
        # A second pass while inflight is latched does not re-probe.
        self.assertEqual(middleware(self._request(session=session)).content, b"ok")

    @override_settings(SSO_SILENT_ENABLED=True)
    def test_exempt_paths_authenticated_and_attempted_do_not_redirect(self):
        middleware = self._middleware()
        for path in ("/oidc/authenticate/", "/oidc/callback/", "/oidc/logout/",
                     "/admin/", "/static/app.css", "/health"):
            self.assertEqual(
                middleware(self._request(path=path)).content,
                b"ok",
                msg=f"{path} should be exempt",
            )
        user = User.objects.create_user(username="did:key:z6Mksilentuser")
        self.assertEqual(middleware(self._request(user=user)).content, b"ok")
        self.assertEqual(
            middleware(self._request(session={"sso_silent_attempted": True})).content,
            b"ok",
        )
        self.assertEqual(middleware(self._request(hint=False)).content, b"ok")
        self.assertEqual(middleware(self._request(method="POST")).content, b"ok")

    @override_settings(SSO_SILENT_ENABLED=True)
    def test_silent_probe_adds_prompt_none_but_interactive_click_does_not(self):
        session = self.FakeSession({"sso_silent_inflight": True})
        request = self._request(session=session)
        from apps.core.auth_pkce import PKCEOIDCAuthenticationRequestView

        view = PKCEOIDCAuthenticationRequestView()
        view.request = request
        params = view.get_extra_params(request)
        self.assertEqual(params.get("prompt"), "none")
        self.assertNotIn("sso_silent_inflight", session)

        interactive = self._request(session={})
        self.assertNotIn("prompt", view.get_extra_params(interactive))

        # End-to-end outbound authorize URL check.
        session = self.client.session
        session["sso_silent_inflight"] = True
        session.save()
        response = self.client.get(reverse("oidc_authentication_init"))
        from urllib.parse import parse_qs, urlparse

        self.assertEqual(
            parse_qs(urlparse(response.url).query).get("prompt"), ["none"]
        )

        # An interactive click has no inflight latch and no prompt=none.
        response = self.client.get(reverse("oidc_authentication_init"))
        self.assertNotIn(
            "prompt", parse_qs(urlparse(response.url).query)
        )

    @override_settings(SSO_SILENT_ENABLED=True)
    def test_callback_error_during_silent_attempt_redirects_without_banner(self):
        session = self.client.session
        session["sso_silent_inflight"] = True
        session["oidc_login_next"] = "/feed?circle=global"
        session.save()
        self.client.cookies["iyou_sso_hint"] = "1"
        response = self.client.get(
            reverse("oidc_authentication_callback"), {"error": "login_required"}
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/feed?circle=global")
        self.assertTrue(self.client.session["sso_silent_attempted"])
        self.assertEqual(list(get_messages(response.wsgi_request)), [])

        # The attempted latch prevents any further automatic probe.
        self.assertEqual(self.client.get("/feed").status_code, 200)


class PKCEOIDCAuthenticationCallbackViewTest(TestCase):
    def test_success_url_defaults_to_map_open(self):
        from apps.core.auth_pkce import PKCEOIDCAuthenticationCallbackView
        from django.test import RequestFactory
        from django.contrib.sessions.middleware import SessionMiddleware

        request = RequestFactory().get("/oidc/callback/")
        middleware = SessionMiddleware(lambda r: None)
        middleware.process_request(request)
        request.session.save()

        view = PKCEOIDCAuthenticationCallbackView()
        view.request = request
        self.assertEqual(view.success_url, "/?map=open")

    def test_success_url_root_next_defaults_to_map_open(self):
        from apps.core.auth_pkce import PKCEOIDCAuthenticationCallbackView
        from django.test import RequestFactory
        from django.contrib.sessions.middleware import SessionMiddleware

        request = RequestFactory().get("/oidc/callback/")
        middleware = SessionMiddleware(lambda r: None)
        middleware.process_request(request)
        request.session["oidc_login_next"] = "/"
        request.session.save()

        view = PKCEOIDCAuthenticationCallbackView()
        view.request = request
        self.assertEqual(view.success_url, "/?map=open")

    def test_success_url_preserves_explicit_deep_next(self):
        from apps.core.auth_pkce import PKCEOIDCAuthenticationCallbackView
        from django.test import RequestFactory
        from django.contrib.sessions.middleware import SessionMiddleware

        request = RequestFactory().get("/oidc/callback/")
        middleware = SessionMiddleware(lambda r: None)
        middleware.process_request(request)
        request.session["oidc_login_next"] = "/thread/post-123"
        request.session.save()

        view = PKCEOIDCAuthenticationCallbackView()
        view.request = request
        self.assertEqual(view.success_url, "/thread/post-123")


class DidKeySovereignFloorContextProcessorTest(TestCase):
    def test_did_key_legacy_managed_free_resolves_sovereign_in_user_identity(self):
        """A did:key: user with legacy 'managed_free' session resolves sovereign and non-custodial."""
        from apps.core.context_processors import user_identity

        user = User.objects.create_user(username="did:key:z6MkujsSdMm1j7QqUNaZo8U8kkcJNfFNikUQYJzmZX4wwgND")
        request = RequestFactory().get("/feed")
        request.user = user
        request.session = {"account_tier": "managed_free"}

        context = user_identity(request)

        self.assertIs(context["is_custodial"], False)
        self.assertEqual(context["account_tier"], "sovereign")
        self.assertEqual(context["user_account_tier"], "L2")
        self.assertEqual(request.session.get("account_tier"), "sovereign")

    def test_did_key_none_session_resolves_sovereign_in_user_identity(self):
        """A did:key: user with no account_tier in session resolves sovereign and non-custodial."""
        from apps.core.context_processors import user_identity

        user = User.objects.create_user(username="did:key:z6MkujsSdMm1j7QqUNaZo8U8kkcJNfFNikUQYJzmZX4wwgND")
        request = RequestFactory().get("/feed")
        request.user = user
        request.session = {}

        context = user_identity(request)

        self.assertIs(context["is_custodial"], False)
        self.assertEqual(context["account_tier"], "sovereign")
        self.assertEqual(context["user_account_tier"], "L2")
        self.assertEqual(request.session.get("account_tier"), "sovereign")

    def test_did_key_custodial_did_legacy_managed_free_resolves_sovereign(self):
        """If custodial_did in session starts with did:key:, coerce to sovereign."""
        from apps.core.context_processors import user_identity

        user = User.objects.create_user(username="legacy_account_name")
        request = RequestFactory().get("/feed")
        request.user = user
        request.session = {
            "custodial_did": "did:key:z6MkujsSdMm1j7QqUNaZo8U8kkcJNfFNikUQYJzmZX4wwgND",
            "account_tier": "managed_free",
        }

        context = user_identity(request)

        self.assertIs(context["is_custodial"], False)
        self.assertEqual(context["account_tier"], "sovereign")
        self.assertEqual(context["user_account_tier"], "L2")
        self.assertEqual(request.session.get("account_tier"), "sovereign")

    def test_did_web_managed_free_preserved_as_custodial(self):
        """A did:web: user with managed_free is preserved as custodial."""
        from apps.core.context_processors import user_identity

        user = User.objects.create_user(username="did:web:iyou.me:user:alice")
        request = RequestFactory().get("/feed")
        request.user = user
        request.session = {"account_tier": "managed_free"}

        context = user_identity(request)

        self.assertIs(context["is_custodial"], True)
        self.assertEqual(context["account_tier"], "managed_free")
        self.assertEqual(context["user_account_tier"], "L1")
        self.assertEqual(request.session.get("account_tier"), "managed_free")

    def test_pkce_login_success_persists_account_tier_from_id_token(self):
        """login_success persists account_tier claim from oidc_id_token into session."""
        from apps.core.auth_pkce import PKCEOIDCAuthenticationCallbackView
        from django.contrib.sessions.middleware import SessionMiddleware

        user = User.objects.create_user(username="did:key:z6MkujsSdMm1j7QqUNaZo8U8kkcJNfFNikUQYJzmZX4wwgND")
        request = RequestFactory().get("/oidc/callback/")
        middleware = SessionMiddleware(lambda r: None)
        middleware.process_request(request)
        request.user = user
        request.session["oidc_id_token"] = {
            "sub": user.username,
            "account_tier": "sovereign",
        }
        request.session.save()

        view = PKCEOIDCAuthenticationCallbackView()
        view.request = request
        view.user = user
        view.login_success()

        self.assertEqual(request.session.get("account_tier"), "sovereign")



