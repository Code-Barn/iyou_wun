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

from mozilla_django_oidc.auth import OIDCAuthenticationBackend
from django.contrib.auth.models import User
from django.conf import settings

logger = logging.getLogger(__name__)

class MyOIDCAuthenticationBackend(OIDCAuthenticationBackend):
    def authenticate(self, request, **kwargs):
        print("DEBUG: OIDC Authenticate Method STARTED")
        print("!!! SUCCESS: THE PROTOCOL HAS FINALLY STARTED !!!")
        try:
            result = super().authenticate(request, **kwargs)
            print(f"DEBUG: OIDC Authenticate returned: {result}")
            return result
        except Exception as e:
            print(f"!!! OIDC AUTHENTICATE ERROR: {str(e)} !!!")
            print(f"!!! ERROR TYPE: {type(e).__name__} !!!")
            import traceback
            print("!!! FULL TRACEBACK:")
            traceback.print_exc()
            raise

    def create_user(self, claims):
        """
        Create a new user from the OIDC claims.
        """
        logger.info(f"Creating user with claims: {claims}")
        try:
            user = User.objects.create_user(username=claims.get('sub'))
            user.is_active = True
            user.set_unusable_password()
            user.save()
            logger.info(f"User created: {user.username}")
            print(f"DEBUG: User created in create_user: {user.username}, ID: {user.id}, Authenticated: {user.is_authenticated}")
            return self._evaluate_admin_elevation(user, claims)
        except Exception as e:
            logger.error(f"Error creating user: {e}")
            raise

    def filter_users_by_claims(self, claims):
        """
        Get or create user based on claims.
        This ensures auto-user creation for any valid DID.

        CRITICAL: Must return a QuerySet, NOT a list or single User object.
        The OIDC library calls len() on the return value to check if a user was found.
        QuerySet is the NATIVE type the library expects - it has len() and other methods.
        Returning User.objects.filter() ensures maximum compatibility with the library.
        """
        try:
            logger.info(f"Filtering users by claims: {claims}")
            did = claims.get('sub')
            if not did:
                logger.error("No 'sub' claim found")
                print("!!! OIDC AUTH ERROR: No 'sub' claim found !!!")
                # Return empty QuerySet for len() == 0 (user not found)
                return User.objects.none()

            # 1. Get or create the user first
            user, created = User.objects.get_or_create(username=did)

            # 2. NOW we can log/print because 'user' exists
            if created:
                user.set_unusable_password()
                user.is_active = True
                user.save()
                logger.info(f"Auto-created user: {user.username}")
                print(f"DEBUG: New Sovereign User created: {user.username}")
                print(f"!!! SUCCESS: NEW SOVEREIGN USER CREATED: {did} !!!")
                print(f"!!! HAMMERING SESSION FOR DID: {did} !!!")
                print(f"DEBUG: OIDC Back-channel successful for DID: {did}")
            else:
                logger.info(f"Found existing user: {user.username}")
                print(f"DEBUG: Found existing user: {user.username}")
                print(f"!!! SUCCESS: MAPPED TO EXISTING USER: {user.username} !!!")
                print(f"DEBUG: OIDC Back-channel successful for DID: {did}")

            # 3. Apply admin elevation
            self._evaluate_admin_elevation(user, claims)

            # 4. Return the QuerySet
            return User.objects.filter(id=user.id)
        except Exception as e:
            logger.error(f"OIDC authentication error: {str(e)}")
            print(f"!!! OIDC AUTH ERROR: {str(e)} !!!")
            raise

    def verify_claims(self, claims):
        """
        Verify the OIDC claims.
        Just check for 'sub' (DID) - we don't need email for sovereign identity.
        """
        logger.info(f"Verifying claims: {claims}")
        print(f"DEBUG: Verifying claims: {claims}")
        # Just require that we have a DID (sub claim)
        return 'sub' in claims

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
