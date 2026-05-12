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

        CRITICAL: Must return a list or QuerySet, NOT a single User object.
        The OIDC library calls len() on the return value to check if a user was found.
        Returning a single User object causes a TypeError when len(user) is called.
        Returning [user] (a list) allows len([user]) == 1, which the library expects.
        Returning User.objects.none() (empty QuerySet) for errors allows len() == 0.
        """
        try:
            logger.info(f"Filtering users by claims: {claims}")
            did = claims.get('sub')
            if not did:
                logger.error("No 'sub' claim found")
                print("!!! OIDC AUTH ERROR: No 'sub' claim found !!!")
                # Return empty QuerySet for len() == 0 (user not found)
                return User.objects.none()

            # Get or create user
            user, created = User.objects.get_or_create(username=did)
            if created:
                user.set_unusable_password()
                user.is_active = True
                user.save()
                logger.info(f"Auto-created user: {user.username}")
                print(f"DEBUG: Auto-created user: {user.username}, ID: {user.id}")
            else:
                logger.info(f"Found existing user: {user.username}")
                print(f"DEBUG: Found existing user: {user.username}, ID: {user.id}")

            print(f"DEBUG: COMMITING SESSION FOR: {user.username}")
            print(f"DEBUG: New Sovereign User created: {user.username}")
            print(f"DEBUG: OIDC Backend returning user: {user.username}")
            # CRITICAL: Return as list for len() compatibility
            return [user]
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
