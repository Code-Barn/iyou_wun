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

"""
Unit & Integration Tests for Dependent Inbound WoT Gate & Feed Filtering (DEP-202 & DEP-203)

Covers:
1. Token Ingress & Session State (apps/core/context.py & src/auth/session.ts):
   - Parse id_token.dep on OIDC callback
   - Store dependent context: is_dependent, bracket, wot_distance_limit
   - Handle revocation and expiry
2. Feed Filtering Policy (apps/feed/selectors.py & src/components/Feed.tsx):
   - Stage 1 (U14): Global timeline disabled; notes exclusively from approved contacts (distance <= 1);
     public persona publishing (kind:0/1 to public relays) suppressed (local-cache only)
   - Stage 2 (U14-U18): Peer-circle discovery enabled (distance <= 2); 3rd-degree dropped before render
3. Inbound DM & Chat Filtering (src/chat/wot_gate.ts & apps/core/wot_gate.py):
   - Inbound Nostr encrypted DMs (kind:4 / NIP-04) and XMPP stanzas
   - Reject inbound chat handshakes if graph distance exceeds wot_distance_limit
   - Drop unknown messages silently without alerting minor or exposing previews
   - DM from WoT distance 2 is accepted for U14-U18 but rejected for U14
4. Zero PII Leakage:
   - Verification that no date of birth, legal name, or PII is required or leaked
"""

import base64
import json
import time
from django.contrib.auth.models import User
from django.test import RequestFactory, TestCase

from apps.core.context import (
    DependentAttestationError,
    get_dependent_context,
    parse_dependent_claim,
    store_dependent_context,
)
from apps.core.wot_gate import (
    calculate_sender_wot_distance,
    can_accept_chat_handshake,
    evaluate_inbound_dm,
    evaluate_inbound_nostr_event,
    evaluate_inbound_xmpp_stanza,
    WoTGate,
)
from apps.feed.selectors import (
    calculate_wot_distance,
    filter_feed_for_dependent,
    get_allowed_publishing_relays,
    is_feed_circle_allowed,
    is_public_publishing_suppressed,
    select_feed,
)


def make_mock_jwt(payload: dict) -> str:
    """Create an unsigned mock JWT string header.payload.signature."""
    header = {"alg": "ES256", "typ": "JWT"}
    h_b64 = base64.urlsafe_b64encode(json.dumps(header).encode()).decode().rstrip("=")
    p_b64 = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    return f"{h_b64}.{p_b64}.mock_sig_value"


class DependentTokenIngressTest(TestCase):
    """Directive 1: Token Ingress & Session State parsing."""

    def test_parse_dependent_claim_u14(self):
        claims = {
            "sub": "did:key:z6MkChildU14",
            "dep": {
                "bracket": "U14",
                "wot_distance": 1,
                "parent_did": "did:key:z6MkParentAnchor",
                "attestation_vc": "eyJhbGciOi...",
                "issued_at": int(time.time()),
                "expires_at": int(time.time()) + 86400,
                "revoked": False,
            },
        }
        ctx = parse_dependent_claim(claims)
        self.assertTrue(ctx["is_dependent"])
        self.assertEqual(ctx["bracket"], "U14")
        self.assertEqual(ctx["wot_distance_limit"], 1)
        self.assertEqual(ctx["parent_did"], "did:key:z6MkParentAnchor")
        self.assertFalse(ctx["revoked"])

    def test_parse_dependent_claim_u14_u18(self):
        claims = {
            "sub": "did:key:z6MkChildU14U18",
            "dep": {
                "bracket": "U14-U18",
                "wot_distance": 2,
                "parent_did": "did:key:z6MkParentAnchor",
                "revoked": False,
            },
        }
        ctx = parse_dependent_claim(claims)
        self.assertTrue(ctx["is_dependent"])
        self.assertEqual(ctx["bracket"], "U14-U18")
        self.assertEqual(ctx["wot_distance_limit"], 2)

    def test_parse_dependent_claim_u18(self):
        claims = {
            "sub": "did:key:z6MkChildU18",
            "dep": {
                "bracket": "U18",
                "wot_distance": 3,
                "parent_did": "did:key:z6MkParentAnchor",
                "revoked": False,
            },
        }
        ctx = parse_dependent_claim(claims)
        self.assertTrue(ctx["is_dependent"])
        self.assertEqual(ctx["bracket"], "U18")
        self.assertEqual(ctx["wot_distance_limit"], 3)

    def test_parse_dependent_claim_adult(self):
        claims = {
            "sub": "did:key:z6MkAdult",
            "dep": {
                "bracket": "ADULT",
                "wot_distance": 0,
                "revoked": False,
            },
        }
        ctx = parse_dependent_claim(claims)
        self.assertFalse(ctx["is_dependent"])
        self.assertEqual(ctx["bracket"], "ADULT")
        self.assertEqual(ctx["wot_distance_limit"], float("inf"))

    def test_parse_from_encoded_jwt_string(self):
        payload = {
            "sub": "did:key:z6MkJwtChild",
            "dep": {
                "bracket": "U14",
                "parent_did": "did:key:z6MkParent",
            },
        }
        jwt_str = make_mock_jwt(payload)
        ctx = parse_dependent_claim(jwt_str)
        self.assertTrue(ctx["is_dependent"])
        self.assertEqual(ctx["bracket"], "U14")
        self.assertEqual(ctx["wot_distance_limit"], 1)

    def test_revoked_attestation_raises_error(self):
        claims = {
            "sub": "did:key:z6MkRevokedChild",
            "dep": {
                "bracket": "U14",
                "revoked": True,
            },
        }
        with self.assertRaises(DependentAttestationError):
            parse_dependent_claim(claims)

    def test_expired_attestation_raises_error(self):
        claims = {
            "sub": "did:key:z6MkExpiredChild",
            "dep": {
                "bracket": "U14",
                "expires_at": int(time.time()) - 3600,  # 1 hour ago
                "revoked": False,
            },
        }
        with self.assertRaises(DependentAttestationError):
            parse_dependent_claim(claims)

    def test_session_storage_and_retrieval(self):
        factory = RequestFactory()
        request = factory.get("/")
        request.session = {}

        claims = {
            "sub": "did:key:z6MkSessionChild",
            "dep": {
                "bracket": "U14-U18",
                "parent_did": "did:key:z6MkParent",
            },
        }
        store_dependent_context(request.session, claims)

        retrieved = get_dependent_context(request)
        self.assertTrue(retrieved["is_dependent"])
        self.assertEqual(retrieved["bracket"], "U14-U18")
        self.assertEqual(retrieved["wot_distance_limit"], 2)


class FeedFilteringPolicyTest(TestCase):
    """Directive 2: Feed Filtering Policy (Stage 1 U14 and Stage 2 U14-U18)."""

    def setUp(self):
        self.parent_did = "did:key:z6MkParentAnchor"
        self.child_did = "did:key:z6MkChildU14"
        self.approved_pk = "3bf0c63fcb93463407af97a5e5ee64fa883d107ef9e558472c4eb9aaaefa459d"
        self.friend_of_friend_pk = "4bf0c63fcb93463407af97a5e5ee64fa883d107ef9e558472c4eb9aaaefa459e"
        self.stranger_pk = "9999c63fcb93463407af97a5e5ee64fa883d107ef9e558472c4eb9aaaefa4599"

        # Trust graph: child -> approved (dist 1) -> friend_of_friend (dist 2) -> stranger (dist 3)
        self.trust_graph = {
            self.child_did: [self.approved_pk],
            self.approved_pk: [self.friend_of_friend_pk],
            self.friend_of_friend_pk: [self.stranger_pk],
        }

    def test_feed_returns_empty_list_when_u14_and_viewing_unapproved_senders(self):
        """Directive 4: Test feed returns empty/restricted list when authenticated with bracket: 'U14' and viewing unapproved senders."""
        u14_ctx = {
            "is_dependent": True,
            "bracket": "U14",
            "wot_distance_limit": 1,
            "parent_did": self.parent_did,
            "approved_contacts": [self.approved_pk],
        }

        # Notes solely from unapproved senders (distance 2 and distance 3)
        unapproved_notes = [
            {"id": "note_fof", "pubkey": self.friend_of_friend_pk, "content": "Friend of friend post"},
            {"id": "note_stranger", "pubkey": self.stranger_pk, "content": "Stranger post"},
        ]

        # Feed filtering must drop all unapproved senders and return empty list
        filtered = filter_feed_for_dependent(
            unapproved_notes,
            dependent_context=u14_ctx,
            viewer_id=self.child_did,
            trust_graph=self.trust_graph,
        )
        self.assertEqual(len(filtered), 0)
        self.assertEqual(filtered, [])

    def test_feed_returns_restricted_list_for_u14_with_mixed_senders(self):
        """U14 feed retains approved contacts (dist <= 1) and drops distance >= 2."""
        u14_ctx = {
            "is_dependent": True,
            "bracket": "U14",
            "wot_distance_limit": 1,
            "parent_did": self.parent_did,
            "approved_contacts": [self.approved_pk],
        }

        mixed_notes = [
            {"id": "note_parent", "author_did": self.parent_did, "content": "From parent"},
            {"id": "note_approved", "pubkey": self.approved_pk, "content": "From approved friend"},
            {"id": "note_fof", "pubkey": self.friend_of_friend_pk, "content": "From 2nd degree peer"},
            {"id": "note_stranger", "pubkey": self.stranger_pk, "content": "From unknown stranger"},
        ]

        filtered = filter_feed_for_dependent(
            mixed_notes,
            dependent_context=u14_ctx,
            viewer_id=self.child_did,
            trust_graph=self.trust_graph,
        )
        self.assertEqual(len(filtered), 2)
        note_ids = [n["id"] for n in filtered]
        self.assertIn("note_parent", note_ids)
        self.assertIn("note_approved", note_ids)
        self.assertNotIn("note_fof", note_ids)
        self.assertNotIn("note_stranger", note_ids)

    def test_global_timeline_disabled_for_stage_1_u14(self):
        """Stage 1 U14: Global public timeline is strictly disabled."""
        u14_ctx = {"is_dependent": True, "bracket": "U14", "wot_distance_limit": 1}
        self.assertFalse(is_feed_circle_allowed("global", u14_ctx))
        self.assertFalse(is_feed_circle_allowed("public", u14_ctx))
        self.assertTrue(is_feed_circle_allowed("following", u14_ctx))
        self.assertTrue(is_feed_circle_allowed("inner", u14_ctx))
        self.assertTrue(is_feed_circle_allowed("iyou", u14_ctx))

        notes = [{"id": "n1", "pubkey": self.approved_pk, "content": "Hello"}]
        result = select_feed(notes, circle="global", dependent_context=u14_ctx)
        self.assertEqual(result, [])

    def test_stage_2_peer_circle_discovery_allows_distance_2_and_drops_distance_3(self):
        """Stage 2 U14-U18: Peer-circle discovery enabled (distance <= 2); 3rd-degree dropped."""
        u14_u18_ctx = {
            "is_dependent": True,
            "bracket": "U14-U18",
            "wot_distance_limit": 2,
            "parent_did": self.parent_did,
            "approved_contacts": [self.approved_pk],
        }

        notes = [
            {"id": "note_dist1", "pubkey": self.approved_pk, "content": "Dist 1 note"},
            {"id": "note_dist2", "pubkey": self.friend_of_friend_pk, "content": "Dist 2 peer note"},
            {"id": "note_dist3", "pubkey": self.stranger_pk, "content": "Dist 3 note"},
        ]

        filtered = filter_feed_for_dependent(
            notes,
            dependent_context=u14_u18_ctx,
            viewer_id=self.child_did,
            trust_graph=self.trust_graph,
        )
        self.assertEqual(len(filtered), 2)
        note_ids = [n["id"] for n in filtered]
        self.assertIn("note_dist1", note_ids)
        self.assertIn("note_dist2", note_ids)
        self.assertNotIn("note_dist3", note_ids)

    def test_u14_public_persona_publishing_suppressed(self):
        """Stage 1 U14: Public persona publishing (kind:0 / kind:1 to public relays) is suppressed."""
        u14_ctx = {"is_dependent": True, "bracket": "U14", "wot_distance_limit": 1}
        u14_u18_ctx = {"is_dependent": True, "bracket": "U14-U18", "wot_distance_limit": 2}

        # kind:0 (metadata) and kind:1 (note) are suppressed for U14
        self.assertTrue(is_public_publishing_suppressed(kind=0, dependent_context=u14_ctx))
        self.assertTrue(is_public_publishing_suppressed(kind=1, dependent_context=u14_ctx))
        self.assertFalse(is_public_publishing_suppressed(kind=7, dependent_context=u14_ctx))  # reaction

        # U14-U18 can publish kind:1
        self.assertFalse(is_public_publishing_suppressed(kind=1, dependent_context=u14_u18_ctx))

        # Allowed relays test: public relays stripped for U14 kind:1
        relays = ["wss://relay.iyou.me", "ws://127.0.0.1:9003", "wss://relay.damus.io"]
        allowed = get_allowed_publishing_relays(kind=1, relays=relays, dependent_context=u14_ctx)
        self.assertEqual(allowed, ["ws://127.0.0.1:9003"])

        # U14-U18 retains full relay list
        allowed_u18 = get_allowed_publishing_relays(kind=1, relays=relays, dependent_context=u14_u18_ctx)
        self.assertEqual(allowed_u18, relays)


class InboundDMChatFilteringTest(TestCase):
    """Directive 3: Inbound DM & Chat Filtering (NIP-04 Kind 4 and XMPP)."""

    def setUp(self):
        self.child_did = "did:key:z6MkChild"
        self.parent_did = "did:key:z6MkParent"
        self.contact_dist1 = "contact_1"
        self.contact_dist2 = "contact_2"
        self.contact_dist3 = "contact_3"

        self.trust_graph = {
            self.child_did: [self.contact_dist1],
            self.contact_dist1: [self.contact_dist2],
            self.contact_dist2: [self.contact_dist3],
        }

    def test_dm_distance_2_accepted_for_u14_u18_rejected_for_u14(self):
        """Directive 4: Test DM from WoT distance 2 is accepted for 'U14-U18' but rejected for 'U14'."""
        u14_ctx = {
            "is_dependent": True,
            "bracket": "U14",
            "wot_distance_limit": 1,
            "parent_did": self.parent_did,
            "approved_contacts": [self.contact_dist1],
        }
        u14_u18_ctx = {
            "is_dependent": True,
            "bracket": "U14-U18",
            "wot_distance_limit": 2,
            "parent_did": self.parent_did,
            "approved_contacts": [self.contact_dist1],
        }

        # 1. Verify distance is 2
        dist = calculate_sender_wot_distance(
            sender=self.contact_dist2,
            recipient=self.child_did,
            trust_graph=self.trust_graph,
            parent_did=self.parent_did,
            approved_contacts=[self.contact_dist1],
        )
        self.assertEqual(dist, 2.0)

        # 2. Evaluate DM for U14-U18: MUST BE ACCEPTED
        allowed_u18, d18, reason18 = evaluate_inbound_dm(
            sender=self.contact_dist2,
            recipient=self.child_did,
            dependent_context=u14_u18_ctx,
            trust_graph=self.trust_graph,
        )
        self.assertTrue(allowed_u18)
        self.assertEqual(d18, 2.0)

        # 3. Evaluate DM for U14: MUST BE REJECTED
        allowed_u14, d14, reason14 = evaluate_inbound_dm(
            sender=self.contact_dist2,
            recipient=self.child_did,
            dependent_context=u14_ctx,
            trust_graph=self.trust_graph,
        )
        self.assertFalse(allowed_u14)
        self.assertEqual(d14, 2.0)
        self.assertIn("exceeds limit 1", reason14)

    def test_nostr_kind_4_dm_interception(self):
        """Kind 4 NIP-04 encrypted direct messages are intercepted before decryption."""
        u14_ctx = {
            "is_dependent": True,
            "bracket": "U14",
            "wot_distance_limit": 1,
            "approved_contacts": [self.contact_dist1],
        }

        event_dist1 = {"kind": 4, "pubkey": self.contact_dist1, "content": "ciphertext?iv=123"}
        event_dist2 = {"kind": 4, "pubkey": self.contact_dist2, "content": "ciphertext?iv=456"}

        allowed1, _, _ = evaluate_inbound_nostr_event(
            event_dist1, dependent_context=u14_ctx, recipient=self.child_did, trust_graph=self.trust_graph
        )
        allowed2, _, _ = evaluate_inbound_nostr_event(
            event_dist2, dependent_context=u14_ctx, recipient=self.child_did, trust_graph=self.trust_graph
        )

        self.assertTrue(allowed1)
        self.assertFalse(allowed2)

    def test_xmpp_stanza_interception_and_handshake_rejection(self):
        """XMPP stanzas and chat handshakes beyond WoT limit are rejected."""
        u14_ctx = {
            "is_dependent": True,
            "bracket": "U14",
            "wot_distance_limit": 1,
            "approved_contacts": [self.contact_dist1],
        }

        # Subscription handshake from distance 2 peer
        handshake_stanza = f'<presence from="{self.contact_dist2}@xmpp.iyou.me/res" type="subscribe"/>'
        allowed, _, reason = evaluate_inbound_xmpp_stanza(
            handshake_stanza, dependent_context=u14_ctx, recipient=self.child_did, trust_graph=self.trust_graph
        )
        self.assertFalse(allowed)
        self.assertIn("Chat handshake rejected", reason)

        # Handshake check convenience function
        can_handshake = can_accept_chat_handshake(
            self.contact_dist2, dependent_context=u14_ctx, recipient=self.child_did, trust_graph=self.trust_graph
        )
        self.assertFalse(can_handshake)

    def test_unknown_message_dropped_silently(self):
        """Unknown message from untrusted sender (outside radius) is dropped silently without raising."""
        u14_ctx = {
            "is_dependent": True,
            "bracket": "U14",
            "wot_distance_limit": 1,
            "approved_contacts": [],
        }
        gate = WoTGate(dependent_context=u14_ctx, recipient=self.child_did, trust_graph=self.trust_graph)
        allowed, dist, reason = gate.evaluate_dm("untrusted_random_sender_123")
        self.assertFalse(allowed)
        self.assertEqual(dist, float("inf"))
        self.assertIn("dropped silently", reason)


class ZeroPIILeakageTest(TestCase):
    """Directive 4: Test zero PII leakage during trust-distance checks."""

    def test_zero_pii_leakage_during_trust_distance_checks(self):
        """
        Omni-Social replaces cloud age verification with client-side Web-of-Trust graph distance.
        The system must never require, store, process, or leak cleartext birthdates,
        legal names, government IDs, phone numbers, or physical addresses.
        """
        pii_forbidden_fields = {
            "dob",
            "birth_date",
            "birthdate",
            "date_of_birth",
            "birth_place",
            "nationality",
            "document_number",
            "ssn",
            "legal_name",
            "real_name",
            "phone",
            "phone_number",
            "address",
        }

        # 1. Inspect parsed dependent context
        claims = {
            "sub": "did:key:z6MkChildDID123",
            "dep": {
                "bracket": "U14",
                "wot_distance": 1,
                "parent_did": "did:key:z6MkParentDID456",
                "attestation_vc": "eyJhbGciOi...",
                "issued_at": int(time.time()) - 3600,
                "expires_at": int(time.time()) + 86400 * 365,
                "revoked": False,
            },
        }
        ctx = parse_dependent_claim(claims)

        for pii in pii_forbidden_fields:
            self.assertNotIn(pii, ctx, f"PII field '{pii}' leaked in dependent context!")
            self.assertNotIn(pii, claims["dep"], f"PII field '{pii}' present in dep claim slot!")

        # 2. Inspect trust distance calculation parameters and results
        dist = calculate_wot_distance(
            author_id="3bf0c63fcb93463407af97a5e5ee64fa883d107ef9e558472c4eb9aaaefa459d",
            viewer_id="did:key:z6MkChildDID123",
            parent_did=ctx["parent_did"],
            approved_contacts=ctx["approved_contacts"],
        )
        self.assertIsInstance(dist, float)

        # 3. Inspect WoT gate evaluation
        allowed, evaluated_dist, reason = evaluate_inbound_dm(
            sender="3bf0c63fcb93463407af97a5e5ee64fa883d107ef9e558472c4eb9aaaefa459d",
            recipient="did:key:z6MkChildDID123",
            dependent_context=ctx,
        )
        for pii in pii_forbidden_fields:
            self.assertNotIn(pii, reason.lower(), f"PII string '{pii}' found in gate reason string!")

        # 4. Verify no PII in feed note selector output
        notes = [{"id": "n1", "pubkey": "3bf0c63f...", "content": "Safe post"}]
        filtered = filter_feed_for_dependent(notes, ctx, viewer_id="did:key:z6MkChildDID123")
        self.assertEqual(len(filtered), 0)  # Unapproved dropped without asking for age/ID proof


class IntegrationViewEndpointsTest(TestCase):
    """Integration tests on views and endpoints for U14 / U14-U18 dependent sessions."""

    def setUp(self):
        self.user = User.objects.create_user(username="did:key:z6MkVendorTestUser")
        self.user.set_unusable_password()
        self.user.save()

    def test_api_feed_u14_global_disabled_returns_empty(self):
        """api_feed with circle=global returns empty notes list for U14 session."""
        self.client.force_login(self.user)
        session = self.client.session
        session["dependent_context"] = {
            "is_dependent": True,
            "bracket": "U14",
            "wot_distance_limit": 1,
            "approved_contacts": [],
        }
        session.save()

        response = self.client.get("/api/feed?circle=global")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data.get("success"))
        self.assertEqual(data.get("notes"), [])
