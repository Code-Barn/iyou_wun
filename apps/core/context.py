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
apps/core/context.py — Dependent Identity, Token Ingress & Session State (DEP-202 & DEP-203)

Implements OIDC Token Ingress and session lifecycle management for parent-stewarded
dependents per OMNI-DEP-GRAD-SPEC-V1:
- Extracts and validates the `dep` (DependentTokenSlot) claim from OIDC `id_token`.
- Enforces the 5-Year Trust Ladder age brackets: "U14", "U14-U18", "U18", "ADULT".
- Maps brackets to strict client-side Web-of-Trust graph distance limits:
    - U14: 1 (parent + explicitly approved contacts only)
    - U14-U18: 2 (peer-circle discovery, 2nd-degree mesh)
    - U18: 3 (near-autonomous, graduation pending)
    - ADULT: infinity (no distance restriction)
- Rejects revoked or expired attestations fail-closed.
- Zero PII: operates strictly on cryptographic DIDs and bracket classifications,
  never storing or exposing dates of birth or legal names.
"""

import base64
import json
import logging
import time
from typing import Any, Dict, Union

logger = logging.getLogger(__name__)

# Canonical WoT distance limits per age bracket
WOT_DISTANCE_LIMITS: Dict[str, float] = {
    "U14": 1,
    "U14-U18": 2,
    "U18": 3,
    "ADULT": float("inf"),
}

VALID_BRACKETS = set(WOT_DISTANCE_LIMITS.keys())

DEFAULT_ADULT_CONTEXT: Dict[str, Any] = {
    "is_dependent": False,
    "bracket": "ADULT",
    "wot_distance_limit": float("inf"),
    "parent_did": None,
    "attestation_vc": None,
    "issued_at": None,
    "expires_at": None,
    "revoked": False,
    "approved_contacts": [],
}


class DependentAttestationError(Exception):
    """Raised when a dependent attestation is revoked, expired, or malformed."""
    pass


def decode_jwt_unverified(jwt_token: str) -> Dict[str, Any]:
    """
    Decodes the payload section of a JWT string without cryptographic verification.
    Cryptographic verification is performed upstream by OIDCAuthenticationBackend.
    """
    if not isinstance(jwt_token, str):
        raise ValueError("JWT token must be a string")

    parts = jwt_token.strip().split(".")
    if len(parts) != 3:
        raise ValueError("Invalid JWT format: expected 3 dot-separated segments")

    payload_b64 = parts[1]
    remainder = len(payload_b64) % 4
    if remainder:
        payload_b64 += "=" * (4 - remainder)

    try:
        decoded_bytes = base64.urlsafe_b64decode(payload_b64.encode("utf-8"))
        return json.loads(decoded_bytes.decode("utf-8"))
    except Exception as exc:
        raise ValueError(f"Failed to decode JWT payload: {exc}") from exc


def parse_dependent_claim(id_token_or_claims: Union[str, Dict[str, Any]]) -> Dict[str, Any]:
    """
    Parse `id_token.dep` on OIDC callback or from token exchange claims.

    Accepts:
    - Raw JWT string: decodes payload and inspects `dep` claim.
    - Decoded claims dict: e.g. {"sub": ..., "dep": {...}}
    - Direct `dep` claim dict: e.g. {"bracket": "U14", "parent_did": ...}

    Returns a standardized dependent context dict:
        is_dependent: bool
        bracket: "U14" | "U14-U18" | "U18" | "ADULT"
        wot_distance_limit: number (1 for U14, 2 for U14-U18, 3 for U18, inf for ADULT)
        parent_did: Optional[str]
        attestation_vc: Optional[Union[str, dict]]
        issued_at: Optional[int]
        expires_at: Optional[int]
        revoked: bool
        approved_contacts: list[str]
    """
    if not id_token_or_claims:
        return dict(DEFAULT_ADULT_CONTEXT)

    claims: Dict[str, Any] = {}
    if isinstance(id_token_or_claims, str):
        claims = decode_jwt_unverified(id_token_or_claims)
    elif isinstance(id_token_or_claims, dict):
        claims = id_token_or_claims
    else:
        raise ValueError(f"Unsupported token/claims type: {type(id_token_or_claims)}")

    # Check if input was already the dep claim dict or a full claims set
    if "bracket" in claims and "sub" not in claims:
        dep = claims
    else:
        dep = claims.get("dep")

    if not dep or not isinstance(dep, dict):
        return dict(DEFAULT_ADULT_CONTEXT)

    # Validate revocation status
    if dep.get("revoked") is True:
        logger.warning("Dependent token rejected: attestation is marked revoked.")
        raise DependentAttestationError("Dependent attestation has been revoked by guardian.")

    # Validate expiration timestamp if present
    expires_at = dep.get("expires_at")
    if expires_at is not None:
        try:
            exp_val = float(expires_at)
            if time.time() > exp_val:
                logger.warning(f"Dependent token rejected: attestation expired at {exp_val}.")
                raise DependentAttestationError("Dependent attestation has expired.")
        except (ValueError, TypeError) as exc:
            if not isinstance(exc, DependentAttestationError):
                logger.warning(f"Invalid expires_at format in dep claim: {expires_at}")

    # Determine age bracket
    raw_bracket = str(dep.get("bracket", "ADULT")).strip().upper()
    if raw_bracket not in VALID_BRACKETS:
        logger.warning(f"Unknown age bracket '{raw_bracket}'; defaulting to U14 for minor safety.")
        bracket = "U14"
    else:
        bracket = raw_bracket

    # Determine dependency boolean
    if "is_dependent" in dep:
        is_dep = bool(dep["is_dependent"])
    else:
        is_dep = bracket != "ADULT"

    wot_limit = WOT_DISTANCE_LIMITS.get(bracket, float("inf"))

    # Extract parent DID and approved contacts
    parent_did = dep.get("parent_did")
    approved = dep.get("approved_contacts") or []
    if not isinstance(approved, list):
        approved = []

    # Clean approved contacts
    approved_cleaned = [str(c).strip().lower() for c in approved if c]

    context: Dict[str, Any] = {
        "is_dependent": is_dep,
        "bracket": bracket,
        "wot_distance_limit": wot_limit,
        "parent_did": parent_did,
        "attestation_vc": dep.get("attestation_vc"),
        "issued_at": dep.get("issued_at"),
        "expires_at": expires_at,
        "revoked": False,
        "approved_contacts": approved_cleaned,
    }
    return context


def store_dependent_context(session: Any, token_or_claims: Union[str, Dict[str, Any]]) -> Dict[str, Any]:
    """
    Parse and persist the dependent context into the active session.
    Sets both the consolidated `dependent_context` dict and individual convenience keys.
    """
    context = parse_dependent_claim(token_or_claims)

    session["dependent_context"] = context
    session["is_dependent"] = context["is_dependent"]
    session["bracket"] = context["bracket"]
    session["dependent_bracket"] = context["bracket"]
    session["wot_distance_limit"] = context["wot_distance_limit"]
    session["parent_did"] = context.get("parent_did")
    session["approved_contacts"] = context.get("approved_contacts", [])

    if hasattr(session, "modified"):
        session.modified = True

    logger.info(
        f"Stored dependent context in session: is_dependent={context['is_dependent']}, "
        f"bracket={context['bracket']}, limit={context['wot_distance_limit']}"
    )
    return context


def get_dependent_context(session_or_request: Any) -> Dict[str, Any]:
    """
    Retrieve the current dependent context from an HttpRequest or Session object.
    Falls back to safe ADULT defaults if unauthenticated or unconfigured.
    """
    if not session_or_request:
        return dict(DEFAULT_ADULT_CONTEXT)

    session = getattr(session_or_request, "session", session_or_request)
    if not hasattr(session, "get"):
        return dict(DEFAULT_ADULT_CONTEXT)

    ctx = session.get("dependent_context")
    if isinstance(ctx, dict) and "bracket" in ctx:
        return dict(ctx)

    # Reassemble from top-level session keys if present
    if "is_dependent" in session or "dependent_bracket" in session or "bracket" in session:
        bracket = session.get("dependent_bracket") or session.get("bracket") or "ADULT"
        if bracket not in VALID_BRACKETS:
            bracket = "ADULT"
        is_dep = session.get("is_dependent", bracket != "ADULT")
        limit = WOT_DISTANCE_LIMITS.get(bracket, float("inf"))
        return {
            "is_dependent": bool(is_dep),
            "bracket": bracket,
            "wot_distance_limit": limit,
            "parent_did": session.get("parent_did"),
            "attestation_vc": None,
            "issued_at": None,
            "expires_at": None,
            "revoked": False,
            "approved_contacts": session.get("approved_contacts", []),
        }

    return dict(DEFAULT_ADULT_CONTEXT)


def clear_dependent_context(session: Any) -> None:
    """Clear dependent context from the session on logout or persona switch."""
    if hasattr(session, "pop"):
        session.pop("dependent_context", None)
        session.pop("is_dependent", None)
        session.pop("bracket", None)
        session.pop("dependent_bracket", None)
        session.pop("wot_distance_limit", None)
        session.pop("parent_did", None)
        session.pop("approved_contacts", None)
        if hasattr(session, "modified"):
            session.modified = True
