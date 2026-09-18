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

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.core.models import (
    CommunityFlagLedger,
    ModerationReviewDocket,
    NodeBlockedEntity,
    NodeContentTakedown,
)
from apps.core.moderation import (
    TIER1_BLUR_THRESHOLD,
    TIER2_SUPPRESS_THRESHOLD,
    TIER3_QUARANTINE_THRESHOLD,
    annotate_progressive_friction,
    filter_shielded_events,
    invalidate_shield_cache,
    is_event_shielded,
    record_community_flag,
)


class CommunityModerationTests(TestCase):
    def setUp(self):
        super().setUp()
        invalidate_shield_cache()
        self.User = get_user_model()
        self.admin_user = self.User.objects.create_user(
            username="did:key:z6MkAdminOperator123",
            is_staff=True,
            is_superuser=True,
        )
        self.reporter1 = "did:key:z6MkReporterAlpha"
        self.reporter2 = "did:key:z6MkReporterBeta"
        self.reporter3 = "did:key:z6MkReporterGamma"
        self.console_url = reverse("moderation_console")

    def tearDown(self):
        invalidate_shield_cache()
        super().tearDown()

    def test_flag_deduplication(self):
        """Same reporter cannot flag the same event twice; counts remain idempotent."""
        event_id = "test_event_dedup_001"
        author_pk = "target_author_pubkey_001"

        res1 = record_community_flag(
            reporter_did=self.reporter1,
            target_pubkey=author_pk,
            target_event_id=event_id,
            reason="SPAM",
        )
        self.assertTrue(res1["success"])
        self.assertEqual(res1["flag_count"], 1)

        # Duplicate flag by same reporter
        res2 = record_community_flag(
            reporter_did=self.reporter1,
            target_pubkey=author_pk,
            target_event_id=event_id,
            reason="HARASSMENT",
        )
        self.assertTrue(res2["success"])
        self.assertEqual(res2["flag_count"], 1)

        # Verify only 1 record exists in CommunityFlagLedger for this event and reporter
        self.assertEqual(
            CommunityFlagLedger.objects.filter(target_event_id=event_id, reporter_did=self.reporter1).count(),
            1,
        )
        self.assertEqual(
            CommunityFlagLedger.objects.filter(target_event_id=event_id).count(),
            1,
        )

    def test_tier1_triggers_nip36_blur(self):
        """3 flags cause annotate_progressive_friction() to set has_content_warning=True."""
        event_id = "test_event_tier1_blur_002"
        author_pk = "target_author_pubkey_002"

        # 1 and 2 flags -> Tier 0
        for i in range(1, TIER1_BLUR_THRESHOLD):
            record_community_flag(
                reporter_did=f"did:key:z6Peer_{i}",
                target_pubkey=author_pk,
                target_event_id=event_id,
                reason="NUDITY_NSFW",
            )

        events = [{"id": event_id, "pubkey": author_pk, "content": "Sensitive media preview"}]
        self.assertFalse(annotate_progressive_friction(events)[0].get("has_content_warning", False))

        # 3rd flag -> Tier 1
        res = record_community_flag(
            reporter_did=f"did:key:z6Peer_{TIER1_BLUR_THRESHOLD}",
            target_pubkey=author_pk,
            target_event_id=event_id,
            reason="NUDITY_NSFW",
        )
        self.assertEqual(res["tier"], 1)
        self.assertEqual(res["flag_count"], 3)

        docket = ModerationReviewDocket.objects.get(target_identifier=event_id)
        self.assertEqual(docket.current_tier, 1)
        self.assertEqual(docket.docket_type, "event")

        # Note is preserved in feed, but annotated with dynamic NIP-36 blur
        filtered = filter_shielded_events(events)
        self.assertEqual(len(filtered), 1)

        annotated = annotate_progressive_friction(filtered)
        self.assertTrue(annotated[0].get("has_content_warning"))
        self.assertEqual(annotated[0].get("warning_reason"), "Flagged by community review")

    def test_tier2_suppresses_event(self):
        """7 flags suppress the event from filter_shielded_events()."""
        event_id = "test_event_tier2_suppress_003"
        author_pk = "target_author_pubkey_003"

        for i in range(TIER2_SUPPRESS_THRESHOLD):
            res = record_community_flag(
                reporter_did=f"did:key:z6Citizen_{i}",
                target_pubkey=author_pk,
                target_event_id=event_id,
                reason="MALWARE",
            )

        self.assertEqual(res["tier"], 2)
        self.assertEqual(res["flag_count"], 7)

        docket = ModerationReviewDocket.objects.get(target_identifier=event_id)
        self.assertEqual(docket.current_tier, 2)

        # Discovery feed suppression: event is completely filtered out
        events = [{"id": event_id, "pubkey": author_pk, "content": "Malicious exploit link"}]
        filtered = filter_shielded_events(events)
        self.assertEqual(len(filtered), 0)

    def test_tier3_quarantines_author_and_dockets(self):
        """15 flags put author into ModerationReviewDocket with current_tier=3."""
        author_pk = "target_spammer_pubkey_004"

        for i in range(TIER3_QUARANTINE_THRESHOLD):
            note_id = f"spam_campaign_note_{i:02d}"
            record_community_flag(
                reporter_did=f"did:key:z6Sentinel_{i}",
                target_pubkey=author_pk,
                target_event_id=note_id,
                reason="SPAM",
            )

        pk_docket = ModerationReviewDocket.objects.get(target_identifier=author_pk, docket_type="pubkey")
        self.assertEqual(pk_docket.current_tier, 3)
        self.assertEqual(pk_docket.flag_count, TIER3_QUARANTINE_THRESHOLD)

        # All events by this author are suppressed across feed views
        events = [
            {"id": "note_alpha", "pubkey": author_pk, "content": "spam"},
            {"id": "note_beta", "pubkey": "good_citizen_pubkey", "content": "legitimate message"},
        ]
        filtered = filter_shielded_events(events)
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["id"], "note_beta")

    def test_admin_can_confirm_or_dismiss_docket(self):
        """Tests admin dismissal and confirmation mutations from moderation desk."""
        self.client.force_login(self.admin_user)

        event_id = "docket_event_under_review_005"
        pubkey_target = "docket_pubkey_under_review_006"

        # Create event docket via community flags
        for i in range(TIER2_SUPPRESS_THRESHOLD):
            record_community_flag(
                reporter_did=f"did:key:z6User_{i}",
                target_pubkey="some_author",
                target_event_id=event_id,
                reason="HARASSMENT",
            )

        docket_event = ModerationReviewDocket.objects.get(target_identifier=event_id)
        self.assertEqual(docket_event.status, "PENDING")
        self.assertEqual(docket_event.current_tier, 2)

        # 1. Dismiss event docket
        dismiss_resp = self.client.post(
            self.console_url,
            data={
                "action": "docket_dismiss",
                "docket_id": docket_event.id,
            },
        )
        self.assertEqual(dismiss_resp.status_code, 302)
        docket_event.refresh_from_db()
        self.assertEqual(docket_event.status, "DISMISSED")
        self.assertEqual(docket_event.reviewed_by_did, self.admin_user.username)

        # Verify event is restored from suppression
        events = [{"id": event_id, "pubkey": "some_author", "content": "Restored message"}]
        self.assertEqual(len(filter_shielded_events(events)), 1)

        # 2. Confirm pubkey docket
        for i in range(TIER3_QUARANTINE_THRESHOLD):
            record_community_flag(
                reporter_did=f"did:key:z6Citizen_{i}",
                target_pubkey=pubkey_target,
                target_event_id=f"author_flagged_note_{i}",
                reason="ILLEGAL",
            )

        docket_pk = ModerationReviewDocket.objects.get(target_identifier=pubkey_target, docket_type="pubkey")
        self.assertEqual(docket_pk.status, "PENDING")

        confirm_resp = self.client.post(
            self.console_url,
            data={
                "action": "docket_confirm",
                "docket_id": docket_pk.id,
            },
        )
        self.assertEqual(confirm_resp.status_code, 302)
        docket_pk.refresh_from_db()
        self.assertEqual(docket_pk.status, "CONFIRMED")
        self.assertEqual(docket_pk.reviewed_by_did, self.admin_user.username)

        # Verify elevated to permanent NodeBlockedEntity
        self.assertTrue(
            NodeBlockedEntity.objects.filter(
                entity_identifier=pubkey_target,
                is_active=True,
            ).exists()
        )

        # 3. Confirm event docket
        event_id_2 = "docket_event_confirm_takedown_007"
        for i in range(TIER2_SUPPRESS_THRESHOLD):
            record_community_flag(
                reporter_did=f"did:key:z6Peer_{i}",
                target_pubkey="another_author",
                target_event_id=event_id_2,
                reason="MALWARE",
            )
        docket_event_2 = ModerationReviewDocket.objects.get(target_identifier=event_id_2)

        confirm_ev_resp = self.client.post(
            self.console_url,
            data={
                "action": "docket_confirm",
                "docket_id": docket_event_2.id,
            },
        )
        self.assertEqual(confirm_ev_resp.status_code, 302)
        docket_event_2.refresh_from_db()
        self.assertEqual(docket_event_2.status, "CONFIRMED")
        self.assertTrue(
            NodeContentTakedown.objects.filter(
                event_id=event_id_2,
            ).exists()
        )

    @patch("apps.core.views.PolyClient.cast_vote")
    def test_poly_vote_enfranchisement_unaffected_by_flags(self, mock_cast_vote):
        """Asserts that an author with 50 flags can still cast signed ballots via /api/vote/ without rejection."""
        mock_cast_vote.return_value = {"receipt": "receipt_tx_poly_enfranchised_ballot_50flags"}

        flagged_author_did = "did:key:z6Mk50FlagsAuthorDemocraticCitizen"
        flagged_user = self.User.objects.create_user(
            username=flagged_author_did,
            is_staff=False,
        )

        # Accumulate 50 community flags across multiple reports
        for i in range(50):
            record_community_flag(
                reporter_did=f"did:key:z6Reporter_{i:03d}",
                target_pubkey=flagged_author_did,
                target_event_id=f"flagged_controversial_post_{i:03d}",
                reason="OTHER",
            )

        self.assertEqual(
            CommunityFlagLedger.objects.filter(target_pubkey=flagged_author_did).count(),
            50,
        )

        # Verify author is shielded on social feed
        self.assertTrue(is_event_shielded({"pubkey": "some_pk", "author_did": flagged_author_did}))

        # Post signed ballot to /api/vote/
        self.client.force_login(flagged_user)
        vote_payload = {
            "voter_did": flagged_author_did,
            "signature": "valid_schnorr_or_did_sig_hex",
            "vote_envelope": {
                "poll_id": "poly_constitutional_amendment_10",
                "choice": "AYE",
            },
        }
        resp = self.client.post(
            "/api/vote/",
            data=json.dumps(vote_payload),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("valid"))
        self.assertEqual(data.get("receipt"), "receipt_tx_poly_enfranchised_ballot_50flags")
        mock_cast_vote.assert_called_once()
