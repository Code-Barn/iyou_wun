import json
import logging
import urllib.request
import urllib.error

from django.test import TestCase
from django.contrib.auth.models import User
from django.urls import reverse
from django.conf import settings

from .auth import MyOIDCAuthenticationBackend

logger = logging.getLogger(__name__)


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
        """Test that filter_users_by_claims creates a user when DID is new."""
        # Ensure no user exists initially
        self.assertFalse(User.objects.filter(username=self.did).exists())

        # Call filter_users_by_claims
        users = self.backend.filter_users_by_claims(self.claims)

        # Verify user was created
        self.assertEqual(len(users), 1)
        user = users[0]
        self.assertEqual(user.username, self.did)
        self.assertTrue(user.is_active)
        self.assertFalse(user.has_usable_password())

    def test_filter_users_by_claims_returns_existing_user(self):
        """Test that filter_users_by_claims returns existing user."""
        # Create user first
        existing_user = User.objects.create_user(username=self.did)
        existing_user.set_unusable_password()
        existing_user.save()

        # Call filter_users_by_claims
        users = self.backend.filter_users_by_claims(self.claims)

        # Verify same user is returned
        self.assertEqual(len(users), 1)
        self.assertEqual(users[0].id, existing_user.id)

    def test_filter_users_by_claims_returns_empty_for_missing_sub(self):
        """Test that filter_users_by_claims returns empty list when sub claim is missing."""
        claims_no_sub = {"some": "claim"}
        users = self.backend.filter_users_by_claims(claims_no_sub)

        # Should return empty QuerySet (len() == 0)
        self.assertEqual(len(users), 0)

    def test_get_username_returns_did(self):
        """Test that get_username extracts DID from claims."""
        username = self.backend.get_username(self.claims)
        self.assertEqual(username, self.did)

    def test_verify_claims_requires_sub(self):
        """Test that verify_claims only requires sub claim."""
        # Should return True when sub is present
        self.assertTrue(self.backend.verify_claims(self.claims))

        # Should return False when sub is missing
        self.assertFalse(self.backend.verify_claims({"other": "claim"}))


class HomeViewTest(TestCase):
    def test_home_returns_200(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)

    def test_home_uses_correct_template(self):
        response = self.client.get("/")
        self.assertTemplateUsed(response, "home.html")

    def test_home_contains_login_button(self):
        response = self.client.get("/")
        self.assertContains(response, "Login with iYou Identity")


class DashboardViewTest(TestCase):
    def test_dashboard_redirects_anonymous(self):
        response = self.client.get("/dashboard")
        self.assertEqual(response.status_code, 302)

    def test_dashboard_redirects_to_oidc_login(self):
        response = self.client.get("/dashboard")
        self.assertIn(reverse("oidc_authentication_init"), response.url)

    def test_authenticated_user_sees_did(self):
        user = User.objects.create_user(username="did:iyou:0xabc123")
        self.client.force_login(user)
        response = self.client.get("/dashboard")
        self.assertContains(response, "did:iyou:0xabc123")
        self.assertContains(response, "Decentralized Identifier")

    def test_authenticated_user_sees_dashboard_title(self):
        user = User.objects.create_user(username="did:iyou:0xdef456")
        self.client.force_login(user)
        response = self.client.get("/dashboard")
        self.assertContains(response, "Dashboard")

    def test_authenticated_user_has_logout_link(self):
        user = User.objects.create_user(username="did:iyou:0xghi789")
        self.client.force_login(user)
        response = self.client.get("/dashboard")
        self.assertContains(response, "Logout")


class JwksConnectivityTest(TestCase):
    """Pings the IdP's JWKS endpoint to verify connectivity.

    This is an integration test — it requires a running iyou_idp instance
    at the URL configured in OIDC_OP_JWKS_ENDPOINT.
    """

    def test_jwks_endpoint_returns_valid_json_with_keys(self):
        url = settings.OIDC_OP_JWKS_ENDPOINT
        if not url:
            self.skipTest("OIDC_OP_JWKS_ENDPOINT is not configured")

        try:
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=5) as resp:
                self.assertEqual(resp.status, 200)
                data = json.loads(resp.read().decode())
                self.assertIn("keys", data)
                self.assertGreater(len(data["keys"]), 0)
        except (urllib.error.URLError, ConnectionError, OSError) as e:
            self.skipTest(f"IdP not reachable at {url}: {e}")
