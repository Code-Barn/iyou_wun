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

import logging
import re
from django.conf import settings
from django.contrib.auth import get_user_model
from mozilla_django_oidc.auth import OIDCAuthenticationBackend

logger = logging.getLogger(__name__)
UserModel = get_user_model()


class MyOIDCAuthenticationBackend(OIDCAuthenticationBackend):
    def get_token(self, payload):
        # Inject PKCE code_verifier into the back-channel token POST
        if hasattr(self, 'pkce_code_verifier') and self.pkce_code_verifier:
            payload['code_verifier'] = self.pkce_code_verifier
            logger.info("Injected PKCE code_verifier into token exchange payload.")
        elif 'pkce_code_verifier' in payload:
            logger.info("PKCE code_verifier already present in payload.")
        return super().get_token(payload)

    def authenticate(self, request, **kwargs):
        self.pkce_code_verifier = kwargs.get('pkce_code_verifier') or kwargs.get('code_verifier')
        if not self.pkce_code_verifier and request and hasattr(request, 'session'):
            self.pkce_code_verifier = request.session.pop('pkce_code_verifier', None)
        return super().authenticate(request, **kwargs)

    def verify_claims(self, claims):
        verified = "sub" in claims
        if not verified:
            logger.warning(f"OIDC claims missing 'sub': {claims}")
        return verified

    def filter_users_by_claims(self, claims):
        sub = claims.get("sub")
        if not sub:
            return UserModel.objects.none()
        return UserModel.objects.filter(username=sub)

    def get_userinfo(self, access_token, id_token, payload):
        user_info = super().get_userinfo(access_token, id_token, payload)
        if isinstance(user_info, dict) and hasattr(self, "request") and self.request and hasattr(self.request, "session"):
            public_emails = user_info.get("public_emails", [])
            self.request.session["verified_public_emails"] = public_emails
        return user_info

    def get_or_create_user(self, access_token, id_token, payload):
        if hasattr(self, "request") and self.request and hasattr(self.request, "session"):
            if payload and isinstance(payload, dict) and "public_emails" in payload:
                self.request.session["verified_public_emails"] = payload.get("public_emails", [])
        if payload and "dep" in payload:
            dep_claim = payload.get("dep")
            if isinstance(dep_claim, dict) and dep_claim.get("revoked") is True:
                logger.warning(f"Rejecting authentication for revoked dependent: {payload.get('sub')}")
                return None
            if hasattr(self, "request") and self.request and hasattr(self.request, "session"):
                from .context import store_dependent_context, DependentAttestationError
                try:
                    store_dependent_context(self.request.session, payload)
                except DependentAttestationError as exc:
                    logger.warning(f"Rejecting dependent login: {exc}")
                    return None
        elif id_token and hasattr(self, "request") and self.request and hasattr(self.request, "session"):
            from .context import store_dependent_context, DependentAttestationError
            try:
                store_dependent_context(self.request.session, id_token)
            except DependentAttestationError as exc:
                logger.warning(f"Rejecting dependent login: {exc}")
                return None
            except Exception:
                pass
        return super().get_or_create_user(access_token, id_token, payload)

    def create_user(self, claims):
        sub = claims.get("sub")
        user = UserModel.objects.create_user(username=sub, email=None)
        user.set_unusable_password()
        user.save()
        logger.info(f"Created new sovereign user via OIDC: {sub}")
        if hasattr(self, "request") and self.request and hasattr(self.request, "session"):
            if claims and isinstance(claims, dict) and "public_emails" in claims:
                self.request.session["verified_public_emails"] = claims.get("public_emails", [])
            if claims and "dep" in claims:
                from .context import store_dependent_context
                try:
                    store_dependent_context(self.request.session, claims)
                except Exception as e:
                    logger.debug(f"Failed to store dependent context in create_user: {e}")
        try:
            self._sync_user_deck(user, claims)
        except Exception as e:
            logger.debug(f"Failed to sync user deck in create_user: {e}")
        return self._evaluate_admin_elevation(user, claims)

    def update_user(self, user, claims):
        if hasattr(self, "request") and self.request and hasattr(self.request, "session"):
            if claims and isinstance(claims, dict) and "public_emails" in claims:
                self.request.session["verified_public_emails"] = claims.get("public_emails", [])
            if claims and "dep" in claims:
                from .context import store_dependent_context
                try:
                    store_dependent_context(self.request.session, claims)
                except Exception as e:
                    logger.debug(f"Failed to store dependent context in update_user: {e}")
        try:
            self._sync_user_deck(user, claims)
        except Exception as e:
            logger.debug(f"Failed to sync user deck in update_user: {e}")
        return self._evaluate_admin_elevation(user, claims)

    def _sync_user_deck(self, user, claims=None):
        if not user or user.is_anonymous:
            return
        from .models import UserLinkDeck
        deck = UserLinkDeck.objects.filter(user=user).first()
        if not deck:
            handle = ""
            if claims and isinstance(claims, dict):
                handle = claims.get("preferred_username") or claims.get("handle") or claims.get("name") or ""
            handle = str(handle or user.username or "user")[:32].lstrip("@").lower()
            try:
                from .views import claim_handle
                deck = claim_handle(user, handle)
            except Exception:
                deck, _ = UserLinkDeck.objects.get_or_create(user=user, defaults={"handle": handle[:32]})

        nostr_pk = ""
        if claims and isinstance(claims, dict):
            nostr_pk = claims.get("nostr_pubkey_hex") or claims.get("nostr_pubkey") or ""
        if not nostr_pk and hasattr(self, "request") and self.request and hasattr(self.request, "session"):
            nostr_pk = self.request.session.get("nostr_pubkey_hex") or ""

        nostr_pk = str(nostr_pk or "").strip().lower()
        if deck and nostr_pk and re.fullmatch(r"[0-9a-f]{64}", nostr_pk):
            if deck.nostr_pubkey != nostr_pk:
                deck.nostr_pubkey = nostr_pk
                deck.save(update_fields=["nostr_pubkey", "updated_at"])

        if deck and claims and isinstance(claims, dict):
            update_fields = []
            display_name = claims.get("display_name") or claims.get("name")
            if display_name and not deck.display_name:
                deck.display_name = str(display_name)[:80]
                update_fields.append("display_name")
            avatar_url = claims.get("avatar_url") or claims.get("picture")
            if avatar_url and not deck.avatar_url:
                deck.avatar_url = str(avatar_url)
                update_fields.append("avatar_url")
            if update_fields:
                update_fields.append("updated_at")
                deck.save(update_fields=update_fields)

    def get_username(self, claims):
        return claims.get("sub")

    def _evaluate_admin_elevation(self, user, claims=None):
        if not user or user.is_anonymous:
            return user
        if user.username == getattr(settings, "ADMIN_DID", None):
            user.is_staff = True
            user.is_superuser = True
            user.save()
        return user
