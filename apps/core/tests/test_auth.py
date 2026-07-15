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

from django.test import TestCase
from django.contrib.auth.models import User
from django.conf import settings

from ..auth import MyOIDCAuthenticationBackend
from .helpers import create_oidc_user, make_claims


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

    def test_filter_users_by_claims_creates_new_user(self):
        users = self.backend.filter_users_by_claims(self.claims)
        self.assertEqual(len(users), 1)
        user = users[0]
        self.assertEqual(user.username, self.did)
        self.assertTrue(user.is_active)
        self.assertFalse(user.has_usable_password())

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

    def test_filter_users_by_claims_sets_unusable_password(self):
        backend = MyOIDCAuthenticationBackend()
        claims = make_claims("did:key:z6Mkpwdreject2")
        users = backend.filter_users_by_claims(claims)
        self.assertFalse(users[0].has_usable_password())

    def test_existing_user_keeps_unusable_password(self):
        backend = MyOIDCAuthenticationBackend()
        claims = make_claims("did:key:z6Mkpwdreject3")
        user = User.objects.create_user(username=claims["sub"])
        user.set_unusable_password()
        user.save()
        users = backend.filter_users_by_claims(claims)
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
            "apps.core.auth_pkce.PKCEAuthenticationBackend",
            backends,
        )

    def test_login_url_points_to_idp(self):
        self.assertEqual(settings.LOGIN_URL, "oidc_authentication_init")

    def test_oidc_backend_creates_user_with_unusable_password(self):
        backend = MyOIDCAuthenticationBackend()
        claims = make_claims("did:key:z6Mkoidcenforce1")
        users = backend.filter_users_by_claims(claims)
        user = users[0]
        self.assertEqual(user.username, "did:key:z6Mkoidcenforce1")
        self.assertFalse(user.has_usable_password())
