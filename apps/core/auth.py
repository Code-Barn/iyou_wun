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
            user.save()
            logger.info(f"User created: {user.username}")
            print(f"DEBUG: User created in create_user: {user.username}, ID: {user.id}, Authenticated: {user.is_authenticated}")
            return user
        except Exception as e:
            logger.error(f"Error creating user: {e}")
            raise

    def verify_claims(self, claims):
        """
        Verify the OIDC claims.
        """
        logger.info(f"Verifying claims: {claims}")
        return super().verify_claims(claims)
