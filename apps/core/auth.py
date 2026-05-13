import logging
from mozilla_django_oidc.auth import OIDCAuthenticationBackend
from django.contrib.auth.models import User

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
            return user
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

            # Use QuerySet throughout - this is the library's native language
            users = User.objects.filter(username=did)

            if not users.exists():
                # Create new user
                user = User.objects.create_user(username=did)
                user.set_unusable_password()
                user.is_active = True
                user.save()
                logger.info(f"Auto-created user: {user.username}")
                print(f"DEBUG: New Sovereign User created: {user.username}")
                print(f"!!! SUCCESS: MAPPED DID {did} TO USER {user.id} !!!")
                print(f"!!! HAMMERING SESSION FOR DID: {did} !!!")
                # Return QuerySet with the new user
                return User.objects.filter(username=did)
            else:
                logger.info(f"Found existing user: {user.username}")
                print(f"DEBUG: Found existing user: {user.username}")
                print(f"!!! SUCCESS: MAPPED DID {did} TO USER {users.first().id} !!!")
                # Return existing user as QuerySet
                return users
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
        """
        Use the DID as the Django username.
        """
        did = claims.get('sub')
        print(f"DEBUG: Mapping DID to username: {did}")
        return did
