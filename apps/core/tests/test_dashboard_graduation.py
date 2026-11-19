"""Dashboard graduation trigger and @handle/NIP-05 anchor coverage."""

import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.core.models import UserLinkDeck

User = get_user_model()
GRADUATION_URL = "https://iyou.me/auth/dashboard/#graduation"


class DashboardGraduationTests(TestCase):
    def setUp(self):
        self.managed = User.objects.create_user(username="did:web:iyou.me:user:dashboard")
        self.sovereign = User.objects.create_user(username="did:key:z6Mkdashboard")

    def _login(self, user, tier):
        self.client.force_login(user)
        session = self.client.session
        session["account_tier"] = tier
        session.save()

    @patch("apps.core.views.relay_req", return_value={})
    def test_didweb_user_sees_graduation_link(self, _relay):
        self._login(self.managed, "managed_free")
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Graduate to Sovereign Custody")
        self.assertContains(response, GRADUATION_URL)

    @patch("apps.core.views.relay_req", return_value={})
    def test_sovereign_user_does_not_see_graduation_link(self, _relay):
        self._login(self.sovereign, "sovereign")
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, GRADUATION_URL)

    @patch("apps.core.views._broadcast_signed_event", return_value=["wss://relay.iyou.me"])
    @patch("apps.core.views.relay_req", return_value={})
    def test_handle_claim_form_is_rendered_and_persists_nip05(self, _relay, _broadcast):
        self._login(self.managed, "managed_free")
        response = self.client.get(reverse("dashboard"))
        self.assertContains(response, "Network Handle")
        self.assertContains(response, 'id="profileHandleInput"')

        claimed = self.client.post(
            reverse("api_deck_handle"),
            data=json.dumps({"handle": "@sovereign_alice"}),
            content_type="application/json",
        )
        self.assertEqual(claimed.status_code, 200)
        data = claimed.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["handle"], "sovereign_alice")
        self.assertEqual(data["nip05"], "sovereign_alice@iyou.me")

        deck = UserLinkDeck.objects.get(user=self.managed)
        self.assertEqual(deck.handle, "sovereign_alice")
        self.assertEqual(deck.nip05, "sovereign_alice@iyou.me")

        # Idempotent reclaim keeps the same handle/discriminator.
        again = self.client.post(
            reverse("api_deck_handle"),
            data=json.dumps({"handle": "sovereign_alice"}),
            content_type="application/json",
        )
        self.assertEqual(again.status_code, 200)
        self.assertEqual(again.json()["nip05"], "sovereign_alice@iyou.me")
        deck.refresh_from_db()
        self.assertEqual(deck.discriminator, 0)

        response = self.client.get(reverse("dashboard"))
        self.assertContains(response, "@sovereign_alice")
        self.assertContains(response, "sovereign_alice@iyou.me")
        self.assertContains(response, "?handle=sovereign_alice")
