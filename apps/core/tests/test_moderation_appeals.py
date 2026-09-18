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

import json
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.core.models import (
    ModerationAppeal,
    ModerationReviewDocket,
    UserLinkDeck,
)
from apps.core.moderation import (
    annotate_progressive_friction,
    get_author_active_frictions,
    invalidate_shield_cache,
    record_community_flag,
    submit_moderation_appeal,
)


class ModerationAppealsTests(TestCase):
    def setUp(self):
        super().setUp()
        invalidate_shield_cache()
        self.User = get_user_model()
        self.admin_user = self.User.objects.create_user(
            username="did:key:z6MkAdminStaffOperator",
            is_staff=True,
            is_superuser=True,
        )
        self.author_did = "did:key:z6MkAuthorAppellantCitizen"
        self.author_pk = "f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1"
        self.author_user = self.User.objects.create_user(username=self.author_did)
        self.author_deck = UserLinkDeck.objects.create(
            user=self.author_user,
            handle="appellant",
            nostr_pubkey=self.author_pk,
        )
        self.reporter1 = "did:key:z6MkReporterOne"
        self.reporter2 = "did:key:z6MkReporterTwo"
        self.reporter3 = "did:key:z6MkReporterThree"
        self.console_url = reverse("moderation_console")

    def tearDown(self):
        invalidate_shield_cache()
        super().tearDown()

    def test_get_author_active_frictions_identifies_flagged_notes(self):
        """Verifies active dockets surface for author DID, including reasons and status."""
        event_id = "test_appeals_flagged_note_101"
        record_community_flag(self.reporter1, self.author_pk, event_id, "SPAM")
        record_community_flag(self.reporter2, self.author_pk, event_id, "SPAM")
        record_community_flag(self.reporter3, self.author_pk, event_id, "HARASSMENT")

        frictions = get_author_active_frictions(self.author_did)
        self.assertTrue(len(frictions) >= 1)
        event_friction = next((f for f in frictions if f["type"] == "event"), None)
        self.assertIsNotNone(event_friction)
        self.assertEqual(event_friction["target_identifier"], event_id)
        self.assertEqual(event_friction["tier"], 1)
        self.assertEqual(event_friction["flag_count"], 3)
        self.assertEqual(event_friction["reasons"], {"SPAM": 2, "HARASSMENT": 1})
        self.assertFalse(event_friction["has_appeal"])
        self.assertIsNone(event_friction["appeal_status"])

    def test_submit_moderation_appeal(self):
        """Verifies appeal persistence and duplicate pending prevention."""
        event_id = "test_appeals_flagged_note_102"
        record_community_flag(self.reporter1, self.author_pk, event_id, "SPAM")
        record_community_flag(self.reporter2, self.author_pk, event_id, "SPAM")
        record_community_flag(self.reporter3, self.author_pk, event_id, "MISINFO")

        docket = ModerationReviewDocket.objects.get(target_identifier=event_id)

        # 1. Author submits legitimate appeal
        res = submit_moderation_appeal(
            docket_id=docket.id,
            appellant_did=self.author_did,
            statement="Context: this note was educational satire, not malicious misinformation.",
        )
        self.assertTrue(res["success"])
        appeal_id = res["appeal_id"]

        appeal = ModerationAppeal.objects.get(id=appeal_id)
        self.assertEqual(appeal.docket_id, docket.id)
        self.assertEqual(appeal.appellant_did, self.author_did)
        self.assertEqual(appeal.status, "PENDING")
        self.assertIn("educational satire", appeal.statement)

        # 2. Duplicate pending appeal attempt is rejected
        dup_res = submit_moderation_appeal(
            docket_id=docket.id,
            appellant_did=self.author_did,
            statement="Submitting another appeal while the first is pending.",
        )
        self.assertFalse(dup_res["success"])
        self.assertIn("already pending", dup_res["error"])

    def test_admin_accept_appeal_restores_event(self):
        """Verifies operator acceptance dismisses docket, clears active friction, and restores feed availability."""
        event_id = "test_appeals_flagged_note_103"
        record_community_flag(self.reporter1, self.author_pk, event_id, "SPAM")
        record_community_flag(self.reporter2, self.author_pk, event_id, "SPAM")
        record_community_flag(self.reporter3, self.author_pk, event_id, "SPAM")

        # Prior to appeal acceptance, progressive friction blurs the note
        blurred = annotate_progressive_friction([{"id": event_id, "pubkey": self.author_pk}])
        self.assertTrue(blurred[0].get("has_content_warning"))

        docket = ModerationReviewDocket.objects.get(target_identifier=event_id)
        appeal_res = submit_moderation_appeal(
            docket_id=docket.id,
            appellant_did=self.author_did,
            statement="Explanation of community value.",
        )
        appeal_id = appeal_res["appeal_id"]

        # Operator views moderation desk with pending appeal badge
        self.client.force_login(self.admin_user)
        desk_resp = self.client.get(self.console_url)
        self.assertEqual(desk_resp.status_code, 200)
        self.assertContains(desk_resp, "Appeal Submitted")
        self.assertContains(desk_resp, "Explanation of community value.")

        # Operator accepts appeal
        post_resp = self.client.post(
            self.console_url,
            {
                "action": "appeal_resolve",
                "appeal_id": appeal_id,
                "decision": "accept",
            },
        )
        self.assertEqual(post_resp.status_code, 302)

        # Verify DB mutations
        appeal = ModerationAppeal.objects.get(id=appeal_id)
        self.assertEqual(appeal.status, "ACCEPTED")
        self.assertEqual(appeal.reviewed_by_did, self.admin_user.username)

        docket.refresh_from_db()
        self.assertEqual(docket.status, "DISMISSED")
        self.assertEqual(docket.reviewed_by_did, self.admin_user.username)

        # Verify feed availability is restored (no content warning blur)
        restored = annotate_progressive_friction([{"id": event_id, "pubkey": self.author_pk}])
        self.assertFalse(restored[0].get("has_content_warning", False))

        # Active frictions for this event is now cleared
        frictions = get_author_active_frictions(self.author_did)
        self.assertFalse(any(f["target_identifier"] == event_id for f in frictions))

    def test_admin_reject_appeal_maintains_tier(self):
        """Verifies rejection preserves enforcement tier and maintains active friction."""
        event_id = "test_appeals_flagged_note_104"
        record_community_flag(self.reporter1, self.author_pk, event_id, "SPAM")
        record_community_flag(self.reporter2, self.author_pk, event_id, "SPAM")
        record_community_flag(self.reporter3, self.author_pk, event_id, "SPAM")

        docket = ModerationReviewDocket.objects.get(target_identifier=event_id)
        appeal_res = submit_moderation_appeal(
            docket_id=docket.id,
            appellant_did=self.author_did,
            statement="Spurious appeal with no merits.",
        )
        appeal_id = appeal_res["appeal_id"]

        # Operator rejects appeal
        self.client.force_login(self.admin_user)
        post_resp = self.client.post(
            self.console_url,
            {
                "action": "appeal_resolve",
                "appeal_id": appeal_id,
                "decision": "reject",
            },
        )
        self.assertEqual(post_resp.status_code, 302)

        appeal = ModerationAppeal.objects.get(id=appeal_id)
        self.assertEqual(appeal.status, "REJECTED")
        self.assertEqual(appeal.reviewed_by_did, self.admin_user.username)

        docket.refresh_from_db()
        self.assertEqual(docket.status, "PENDING")
        self.assertEqual(docket.current_tier, 1)

        # Enforcement continues: note remains blurred
        annotated = annotate_progressive_friction([{"id": event_id, "pubkey": self.author_pk}])
        self.assertTrue(annotated[0].get("has_content_warning"))

        # Author still sees active friction with REJECTED appeal status
        frictions = get_author_active_frictions(self.author_did)
        ev_f = next(f for f in frictions if f["target_identifier"] == event_id)
        self.assertTrue(ev_f["has_appeal"])
        self.assertEqual(ev_f["appeal_status"], "REJECTED")

    def test_raw_mesh_sensitivity_bypasses_blur(self):
        """Verifies client filter logic for raw mesh mode and settings exposure."""
        # 1. Verify dashboard settings exposure
        self.client.force_login(self.author_user)
        resp = self.client.get(reverse("dashboard"))
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode("utf-8")
        self.assertIn("setting-shield-sensitivity", html)
        self.assertIn("wun_shield_sensitivity", html)
        self.assertIn("Standard (Default: blur Tier 1, hide Tier 2)", html)
        self.assertIn("Strict (Hide Tier 1 and Tier 2)", html)
        self.assertIn("Raw Mesh (Never hide Tier 1/2; display unblurred with subtle flag badge)", html)

        # 2. Verify static/js/circle_feed_filter.js logic
        filter_js = (settings.BASE_DIR / "static" / "js" / "circle_feed_filter.js").read_text()
        self.assertIn("wun_shield_sensitivity", filter_js)
        self.assertIn("raw_mesh", filter_js)
        self.assertIn("raw-mesh-warning-chip", filter_js)
        self.assertIn("blur-me", filter_js)
        self.assertIn("strict", filter_js)

    @patch("apps.core.views.PolyClient.cast_vote")
    def test_governance_voting_enfranchised_during_appeal(self, mock_cast_vote):
        """Confirms user can cast ballots via /api/vote/ while an appeal is pending."""
        mock_cast_vote.return_value = {"receipt": "receipt_appeal_ballot_enfranchised_999"}

        event_id = "test_appeals_flagged_note_105"
        record_community_flag(self.reporter1, self.author_pk, event_id, "SPAM")
        record_community_flag(self.reporter2, self.author_pk, event_id, "SPAM")
        record_community_flag(self.reporter3, self.author_pk, event_id, "SPAM")

        docket = ModerationReviewDocket.objects.get(target_identifier=event_id)
        submit_moderation_appeal(
            docket_id=docket.id,
            appellant_did=self.author_did,
            statement="Appeal is pending review.",
        )
        self.assertTrue(docket.has_pending_appeal)

        # Author logs in and casts ballot
        self.client.force_login(self.author_user)
        vote_payload = {
            "voter_did": self.author_did,
            "signature": "valid_signature_hex_citizen",
            "vote_envelope": {
                "poll_id": "poly_poll_community_council_2026",
                "choice": "NAY",
            },
        }
        vote_resp = self.client.post(
            "/api/vote/",
            data=json.dumps(vote_payload),
            content_type="application/json",
        )
        self.assertEqual(vote_resp.status_code, 200)
        data = vote_resp.json()
        self.assertTrue(data.get("valid"))
        self.assertEqual(data.get("receipt"), "receipt_appeal_ballot_enfranchised_999")
        mock_cast_vote.assert_called_once()
