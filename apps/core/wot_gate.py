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
apps/core/wot_gate.py — Inbound DM & Chat Filtering Gate (DEP-202 & DEP-203)

Enforces client-side WoT graph distance and age-bracket boundaries inside iyou_wun
so dependent users only receive permitted direct messages per the 5-Year Trust Ladder:

- Intercepts inbound Nostr encrypted DMs (kind:4 / NIP-04) and XMPP stanzas.
- Queries the local contact trust engine.
- Rejects inbound chat handshakes if sender graph distance exceeds wot_distance_limit.
- Drops unknown messages silently without alerting the minor or exposing message previews.
- Zero PII: operates strictly on cryptographic keys and graph edge distances.
"""

import collections
import logging
import re
from typing import Any, Dict, Iterable, Optional, Set, Tuple, Union

logger = logging.getLogger(__name__)


def normalize_identifier(raw: Optional[Union[str, Any]]) -> str:
    """Normalize a pubkey hex, JID, npub, or DID string."""
    if not raw:
        return ""
    clean = str(raw).strip().lower()
    # Strip resource component from XMPP JIDs (e.g. user@domain/res -> user@domain)
    if "/" in clean and "@" in clean:
        clean = clean.split("/")[0]
    return clean


def calculate_sender_wot_distance(
    sender: str,
    recipient: Optional[str] = None,
    trust_graph: Optional[Dict[str, Iterable[str]]] = None,
    parent_did: Optional[str] = None,
    approved_contacts: Optional[Iterable[str]] = None,
) -> float:
    """
    Calculate the WoT graph distance from the sender to the dependent user / parent anchor.

    Tiers:
      0: Recipient (self) or parent anchor
      1: Approved / whitelisted contacts (direct follows or parent-whitelisted contacts)
      2: 2nd-degree connections (friends-of-friends / peer circle)
      3+: 3rd-degree and beyond (untrusted / outside radius)
    """
    s_norm = normalize_identifier(sender)
    r_norm = normalize_identifier(recipient)
    p_norm = normalize_identifier(parent_did)

    if not s_norm:
        return float("inf")

    # Distance 0: Self or Parent anchor
    if (r_norm and s_norm == r_norm) or (p_norm and s_norm == p_norm):
        return 0.0

    # Distance 1: Explicit approved contacts
    approved_set: Set[str] = set()
    if approved_contacts:
        for c in approved_contacts:
            n = normalize_identifier(c)
            if n:
                approved_set.add(n)

    if s_norm in approved_set:
        return 1.0

    # Trust graph traversal if available
    if trust_graph and isinstance(trust_graph, dict):
        normalized_graph: Dict[str, Set[str]] = {}
        for src, neighbors in trust_graph.items():
            src_n = normalize_identifier(src)
            normalized_graph[src_n] = {normalize_identifier(n) for n in neighbors if n}

        start_nodes: Set[str] = set()
        if r_norm:
            start_nodes.add(r_norm)
        if p_norm:
            start_nodes.add(p_norm)
        start_nodes.update(approved_set)

        if s_norm in start_nodes:
            return 1.0

        # BFS shortest path search
        visited: Set[str] = set(start_nodes)
        queue = collections.deque([(node, 1.0) for node in start_nodes])

        while queue:
            curr, dist = queue.popleft()
            if curr == s_norm:
                return dist

            if dist >= 4:
                continue

            for neighbor in normalized_graph.get(curr, set()):
                if neighbor == s_norm:
                    return dist + 1.0
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append((neighbor, dist + 1.0))

    # Outside radius
    return float("inf")


def evaluate_inbound_dm(
    sender: str,
    recipient: Optional[str],
    dependent_context: Dict[str, Any],
    trust_graph: Optional[Dict[str, Iterable[str]]] = None,
    is_handshake: bool = False,
) -> Tuple[bool, float, str]:
    """
    Core gate decision function for an inbound DM or chat handshake.

    Returns:
        (allowed: bool, distance: float, reason: str)
    """
    if not dependent_context or not dependent_context.get("is_dependent"):
        return True, 0.0, "Allowed: non-dependent adult session."

    bracket = str(dependent_context.get("bracket", "ADULT")).strip().upper()
    wot_limit = dependent_context.get("wot_distance_limit")
    if wot_limit is None:
        if bracket == "U14":
            wot_limit = 1.0
        elif bracket == "U14-U18":
            wot_limit = 2.0
        elif bracket == "U18":
            wot_limit = 3.0
        else:
            wot_limit = float("inf")

    parent_did = dependent_context.get("parent_did")
    approved = dependent_context.get("approved_contacts") or []

    distance = calculate_sender_wot_distance(
        sender=sender,
        recipient=recipient,
        trust_graph=trust_graph,
        parent_did=parent_did,
        approved_contacts=approved,
    )

    if distance <= wot_limit:
        return True, distance, f"Allowed: sender distance {distance} <= limit {wot_limit}."

    action = "Chat handshake rejected" if is_handshake else "Inbound message dropped silently"
    reason = (
        f"{action}: sender distance {distance} exceeds limit {wot_limit} for bracket {bracket}."
    )
    logger.debug(reason)
    return False, distance, reason


def evaluate_inbound_nostr_event(
    event: Dict[str, Any],
    dependent_context: Dict[str, Any],
    recipient: Optional[str] = None,
    trust_graph: Optional[Dict[str, Iterable[str]]] = None,
) -> Tuple[bool, float, str]:
    """
    Intercept and evaluate an inbound Nostr encrypted DM (Kind 4 / NIP-04).
    The sender is event['pubkey'].
    """
    if not event or event.get("kind") != 4:
        return True, 0.0, "Allowed: non-DM Nostr event."

    sender = event.get("pubkey", "")
    return evaluate_inbound_dm(
        sender=sender,
        recipient=recipient,
        dependent_context=dependent_context,
        trust_graph=trust_graph,
        is_handshake=False,
    )


def evaluate_inbound_xmpp_stanza(
    stanza: Union[str, Dict[str, Any]],
    dependent_context: Dict[str, Any],
    recipient: Optional[str] = None,
    trust_graph: Optional[Dict[str, Iterable[str]]] = None,
) -> Tuple[bool, float, str]:
    """
    Intercept and evaluate an inbound XMPP stanza (message or presence subscription handshake).
    """
    sender = ""
    is_handshake = False

    if isinstance(stanza, str):
        match = re.search(r'from=["\']([^"\']+)["\']', stanza, re.IGNORECASE)
        if match:
            sender = match.group(1)
        is_handshake = "type='subscribe'" in stanza or 'type="subscribe"' in stanza
    elif isinstance(stanza, dict):
        sender = stanza.get("from", "")
        is_handshake = stanza.get("type") == "subscribe"

    return evaluate_inbound_dm(
        sender=sender,
        recipient=recipient,
        dependent_context=dependent_context,
        trust_graph=trust_graph,
        is_handshake=is_handshake,
    )


def can_accept_chat_handshake(
    sender: str,
    dependent_context: Dict[str, Any],
    recipient: Optional[str] = None,
    trust_graph: Optional[Dict[str, Iterable[str]]] = None,
) -> bool:
    """Convenience helper to check if an inbound chat handshake may be accepted."""
    allowed, _, _ = evaluate_inbound_dm(
        sender=sender,
        recipient=recipient,
        dependent_context=dependent_context,
        trust_graph=trust_graph,
        is_handshake=True,
    )
    return allowed


class WoTGate:
    """Web-of-Trust Gate controller instance."""

    def __init__(
        self,
        dependent_context: Optional[Dict[str, Any]] = None,
        recipient: Optional[str] = None,
        trust_graph: Optional[Dict[str, Iterable[str]]] = None,
    ):
        self.dependent_context = dependent_context or {}
        self.recipient = recipient
        self.trust_graph = trust_graph

    def evaluate_dm(self, sender: str, is_handshake: bool = False) -> Tuple[bool, float, str]:
        return evaluate_inbound_dm(
            sender=sender,
            recipient=self.recipient,
            dependent_context=self.dependent_context,
            trust_graph=self.trust_graph,
            is_handshake=is_handshake,
        )

    def evaluate_nostr(self, event: Dict[str, Any]) -> Tuple[bool, float, str]:
        return evaluate_inbound_nostr_event(
            event=event,
            dependent_context=self.dependent_context,
            recipient=self.recipient,
            trust_graph=self.trust_graph,
        )

    def evaluate_xmpp(self, stanza: Union[str, Dict[str, Any]]) -> Tuple[bool, float, str]:
        return evaluate_inbound_xmpp_stanza(
            stanza=stanza,
            dependent_context=self.dependent_context,
            recipient=self.recipient,
            trust_graph=self.trust_graph,
        )

    def can_accept_handshake(self, sender: str) -> bool:
        return can_accept_chat_handshake(
            sender=sender,
            dependent_context=self.dependent_context,
            recipient=self.recipient,
            trust_graph=self.trust_graph,
        )
