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
apps/feed/selectors.py — Dependent Feed Filtering Policy (DEP-202 & DEP-203)

Enforces age-bracket and client-side Web-of-Trust graph distance boundaries
for notes rendered on the feed per OMNI-DEP-GRAD-SPEC-V1:

- Stage 1 (U14):
    - Global public timeline is disabled.
    - Feed displays notes exclusively from approved contacts (WoT distance <= 1,
      parent-whitelisted contacts).
    - Public persona publishing (kind:0 / kind:1 to public relays) is suppressed;
      events are local-cache only.

- Stage 2 (U14-U18):
    - Peer-circle discovery enabled (WoT distance <= 2).
    - Notes from 3rd-degree connections and beyond are dropped before rendering.

- Zero PII: operates strictly on cryptographic identifiers (DIDs/pubkeys) and
  graph distance, never touching or leaking date of birth or legal names.
"""

import collections
import logging
from typing import Any, Dict, Iterable, List, Optional, Set, Union

logger = logging.getLogger(__name__)


def normalize_identifier(raw: Optional[Union[str, Any]]) -> str:
    """Normalize a pubkey hex, npub, or DID string."""
    if not raw:
        return ""
    return str(raw).strip().lower()


def is_feed_circle_allowed(circle: str, dependent_context: Dict[str, Any]) -> bool:
    """
    Check if a circle scope is permitted for the given dependent context.
    For Stage 1 (U14), the global public timeline is strictly disabled.
    """
    if not dependent_context or not dependent_context.get("is_dependent"):
        return True

    bracket = str(dependent_context.get("bracket", "ADULT")).strip().upper()
    circle_norm = str(circle or "").strip().lower()

    if bracket == "U14" and circle_norm in ("global", "public", "world"):
        return False

    return True


def calculate_wot_distance(
    author_id: str,
    viewer_id: Optional[str] = None,
    trust_graph: Optional[Dict[str, Iterable[str]]] = None,
    parent_did: Optional[str] = None,
    approved_contacts: Optional[Iterable[str]] = None,
    note: Optional[Dict[str, Any]] = None,
) -> float:
    """
    Calculates the Web-of-Trust graph distance between an author and the viewer/parent anchor.

    Distance tiers:
      0: Self (viewer) or direct anchor (parent_did)
      1: Approved / whitelisted contacts (direct 1st degree follows or parent-whitelisted)
      2: 2nd-degree connections (friends-of-friends / peer circle)
      3+: 3rd-degree and beyond (untrusted / outside trust radius)
    """
    author = normalize_identifier(author_id)
    viewer = normalize_identifier(viewer_id)
    parent = normalize_identifier(parent_did)

    if not author:
        return float("inf")

    # Distance 0: viewer or parent
    if (viewer and author == viewer) or (parent and author == parent):
        return 0.0

    # Explicit note distance annotation (e.g. from upstream graph enricher)
    if note and isinstance(note, dict):
        for dist_key in ("wot_distance", "author_wot_distance", "distance"):
            if dist_key in note and note[dist_key] is not None:
                try:
                    return float(note[dist_key])
                except (ValueError, TypeError):
                    pass

    # Clean approved contacts set
    approved_set: Set[str] = set()
    if approved_contacts:
        for c in approved_contacts:
            norm = normalize_identifier(c)
            if norm:
                approved_set.add(norm)

    if author in approved_set:
        return 1.0

    # Trust level badge tags (Level0, Level0_5, Level1 = distance 1)
    if note and isinstance(note, dict):
        tier = note.get("trust_tier") or note.get("trust_level")
        if tier in ("Level0", "Level0_5", "Level1"):
            return 1.0
        elif tier == "Level2":
            return 2.0

    # Graph BFS calculation if trust graph is provided
    if trust_graph and isinstance(trust_graph, dict):
        normalized_graph: Dict[str, Set[str]] = {}
        for src, neighbors in trust_graph.items():
            s_norm = normalize_identifier(src)
            normalized_graph[s_norm] = {normalize_identifier(n) for n in neighbors if n}

        # Starting nodes for distance search: viewer, parent, approved contacts
        start_nodes: Set[str] = set()
        if viewer:
            start_nodes.add(viewer)
        if parent:
            start_nodes.add(parent)
        start_nodes.update(approved_set)

        if author in start_nodes:
            return 1.0

        # Run BFS up to depth 4
        visited: Set[str] = set(start_nodes)
        queue = collections.deque([(node, 1.0) for node in start_nodes])

        while queue:
            curr, dist = queue.popleft()
            if curr == author:
                return dist

            if dist >= 4:
                continue

            for neighbor in normalized_graph.get(curr, set()):
                if neighbor == author:
                    return dist + 1.0
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append((neighbor, dist + 1.0))

    # Without explicit proof of proximity, untrusted external authors are distance >= 3
    return float("inf")


def filter_feed_for_dependent(
    notes: List[Dict[str, Any]],
    dependent_context: Dict[str, Any],
    viewer_id: Optional[str] = None,
    trust_graph: Optional[Dict[str, Iterable[str]]] = None,
) -> List[Dict[str, Any]]:
    """
    Filters notes for a dependent user based on their age bracket and WoT distance limit.

    - Stage 1 (U14): distance limit 1. Displays notes EXCLUSIVELY from approved
      contacts (WoT distance <= 1). Unapproved senders are dropped.
    - Stage 2 (U14-U18): distance limit 2. Peer-circle discovery enabled. Notes
      from 3rd-degree connections and beyond (distance >= 3) are dropped.
    - ADULT: all notes retained.
    """
    if not dependent_context or not dependent_context.get("is_dependent"):
        return list(notes)

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
    approved_contacts = dependent_context.get("approved_contacts") or []

    filtered_notes: List[Dict[str, Any]] = []

    for note in notes:
        if not isinstance(note, dict):
            continue

        author = (
            note.get("pubkey")
            or note.get("author_pubkey")
            or note.get("author_did")
            or ""
        )

        dist = calculate_wot_distance(
            author_id=author,
            viewer_id=viewer_id,
            trust_graph=trust_graph,
            parent_did=parent_did,
            approved_contacts=approved_contacts,
            note=note,
        )

        if dist <= wot_limit:
            filtered_notes.append(note)
        else:
            logger.debug(
                f"Dropping note {note.get('id')} from author {author[:12]}... "
                f"(WoT distance {dist} exceeds limit {wot_limit} for {bracket})"
            )

    return filtered_notes


def is_public_publishing_suppressed(kind: int, dependent_context: Dict[str, Any]) -> bool:
    """
    Check if public persona publishing is suppressed for this event kind.
    For Stage 1 (U14), public persona publishing (kind:0 / kind:1) to public relays
    is strictly suppressed; events are local-cache only.
    """
    if not dependent_context or not dependent_context.get("is_dependent"):
        return False

    bracket = str(dependent_context.get("bracket", "ADULT")).strip().upper()
    if bracket == "U14" and int(kind) in (0, 1):
        return True

    return False


def get_allowed_publishing_relays(
    kind: int,
    relays: Iterable[str],
    dependent_context: Dict[str, Any],
) -> List[str]:
    """
    Returns the list of relay URLs permitted for publishing an event.
    If public publishing is suppressed (e.g. Stage 1 U14 for kind:0/1), all public
    relays are stripped, leaving only local loopback relays (127.0.0.1 / localhost)
    or an empty list (local cache only).
    """
    relay_list = list(relays or [])
    if not is_public_publishing_suppressed(kind, dependent_context):
        return relay_list

    # Suppress all public external relays; retain local loopback only
    local_relays = [
        r for r in relay_list
        if "127.0.0.1" in r or "localhost" in r
    ]
    return local_relays


def select_feed(
    notes: List[Dict[str, Any]],
    circle: str,
    dependent_context: Dict[str, Any],
    viewer_id: Optional[str] = None,
    trust_graph: Optional[Dict[str, Iterable[str]]] = None,
) -> List[Dict[str, Any]]:
    """
    Selector entrypoint that applies both circle-scope restrictions and
    WoT distance boundaries for the active dependent context.
    """
    if not is_feed_circle_allowed(circle, dependent_context):
        # Global public timeline is disabled for U14
        return []

    return filter_feed_for_dependent(
        notes=notes,
        dependent_context=dependent_context,
        viewer_id=viewer_id,
        trust_graph=trust_graph,
    )
