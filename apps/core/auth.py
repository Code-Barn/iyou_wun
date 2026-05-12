import logging
from mozilla_django_oidc.auth import OIDCAuthenticationBackend
from django.contrib.auth.models import User

logger = logging.getLogger(__name__)

class MyOIDCAuthenticationBackend(OIDCAuthenticationBackend):
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
        """
        try:
            logger.info(f"Filtering users by claims: {claims}")
            did = claims.get('sub')
            if not did:
                logger.error("No 'sub' claim found")
                print("!!! OIDC AUTH ERROR: No 'sub' claim found !!!")
                return None

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

            print(f"DEBUG: OIDC Backend returning user: {user.username}")
            return user
        except Exception as e:
            logger.error(f"OIDC authentication error: {str(e)}")
            print(f"!!! OIDC AUTH ERROR: {str(e)} !!!")
            raise

    def verify_claims(self, claims):
        """
        Verify the OIDC claims.
        """
        logger.info(f"Verifying claims: {claims}")
        return super().verify_claims(claims)
