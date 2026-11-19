"""Managed (Tier 1 / ``did:web``) Nostr key provisioning.

Sovereign users sign with their own ``iyou_home`` enclave or NIP-07 extension.
Managed users authenticate with a custodial ``did:web`` and have no local
signing device, so WUN provisions a secp256k1 keypair on their behalf:

* the 32-byte secret is Fernet-encrypted at rest with a key derived from
  ``settings.SECRET_KEY`` through HKDF-SHA256 (no cleartext secrets, no email
  addresses used as lookup anchors);
* the x-only public key is mirrored onto ``UserLinkDeck.nostr_pubkey`` so
  ``get_ecosystem_pubkeys()`` recognises the author's posts as iyou-native;
* provisioning is idempotent and never rotates an existing key.
"""

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from django.conf import settings

from . import nostr_signer

_MANAGED_TIERS = {"managed_free", "managed_premium", "L1", "l1", "custodial", "tier1"}
_SOVEREIGN_TIERS = {"sovereign", "L2", "l2", "tier2", "tier3"}


def _fernet():
    derived = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"iyou-wun.custodial-nostr.v1",
        info=b"bip340-secret",
    ).derive(str(settings.SECRET_KEY).encode("utf-8"))
    return Fernet(base64.urlsafe_b64encode(derived))


def encrypt_secret(secret_hex):
    return _fernet().encrypt(secret_hex.encode("ascii")).decode("ascii")


def decrypt_secret(ciphertext):
    try:
        return _fernet().decrypt(ciphertext.encode("ascii")).decode("ascii")
    except (InvalidToken, ValueError, AttributeError, TypeError):
        raise ValueError("custodial key ciphertext is invalid or was encrypted with a different SECRET_KEY")


def is_managed_account(user, request=None):
    """True for Tier 1 / custodial sessions; False for sovereign enclave users."""
    username = str(getattr(user, "username", "") or "")
    tier = ""
    did = username
    if request is not None and hasattr(request, "session"):
        tier = str(request.session.get("account_tier") or "").strip().lower()
        did = str(
            request.session.get("custodial_did")
            or request.session.get("current_session_did")
            or username
        )
    if tier in _MANAGED_TIERS:
        return True
    if tier in _SOVEREIGN_TIERS and not did.startswith("did:web:"):
        return False
    return did.startswith("did:web:")


def _ensure_deck(user):
    from .models import UserLinkDeck

    deck = UserLinkDeck.objects.filter(user=user).first()
    if deck is not None:
        return deck
    handle = "web_" + hashlib.sha256(str(user.username).encode("utf-8")).hexdigest()[:12]
    deck, _created = UserLinkDeck.objects.get_or_create(user=user, defaults={"handle": handle[:32]})
    return deck


def get_or_create_custodial_keypair(user):
    """Return ``(secret_hex, pubkey_hex, created)`` for a managed user."""
    deck = _ensure_deck(user)
    if deck.custodial_private_key_enc:
        secret_hex = decrypt_secret(deck.custodial_private_key_enc)
        if not nostr_signer.is_valid_hex32(secret_hex):
            raise ValueError("stored custodial secret is malformed")
        derived_pubkey = nostr_signer.pubkey_from_secret(secret_hex)
        if deck.custodial_pubkey_hex != derived_pubkey:
            deck.custodial_pubkey_hex = derived_pubkey
            deck.save(update_fields=["custodial_pubkey_hex", "updated_at"])
        return secret_hex, derived_pubkey, False

    secret_hex = nostr_signer.generate_secret()
    pubkey_hex = nostr_signer.pubkey_from_secret(secret_hex)
    deck.custodial_private_key_enc = encrypt_secret(secret_hex)
    deck.custodial_pubkey_hex = pubkey_hex
    if not deck.nostr_pubkey:
        deck.nostr_pubkey = pubkey_hex
    deck.save(
        update_fields=[
            "custodial_private_key_enc",
            "custodial_pubkey_hex",
            "nostr_pubkey",
            "updated_at",
        ]
    )
    _invalidate_identity_caches(pubkey_hex)
    return secret_hex, pubkey_hex, True


def get_custodial_pubkey(user):
    """Return the managed user's x-only pubkey without provisioning a new key."""
    from .models import UserLinkDeck

    deck = UserLinkDeck.objects.filter(user=user).first()
    if deck and deck.custodial_pubkey_hex:
        return deck.custodial_pubkey_hex
    if deck and deck.custodial_private_key_enc:
        return nostr_signer.pubkey_from_secret(decrypt_secret(deck.custodial_private_key_enc))
    return ""


def sign_as_managed(user, unsigned_event):
    """Provision (if needed) and sign a Nostr event with the custodial key."""
    secret_hex, _pubkey_hex, _created = get_or_create_custodial_keypair(user)
    return nostr_signer.sign_event(unsigned_event, secret_hex)


def _invalidate_identity_caches(pubkey_hex):
    try:
        from .identity import invalidate_author_identity, invalidate_ecosystem_cache

        invalidate_ecosystem_cache()
        invalidate_author_identity(pubkey_hex)
    except Exception:
        pass
