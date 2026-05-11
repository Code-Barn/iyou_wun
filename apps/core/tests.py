from django.test import TestCase
from django.contrib.auth.models import User
from django.urls import reverse

from .auth import MyOIDCAuthenticationBackend


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
