from mozilla_django_oidc.auth import OIDCAuthenticationBackend
from django.contrib.auth.models import User

class MyOIDCAuthenticationBackend(OIDCAuthenticationBackend):
    def create_user(self, claims):
        """
        Create a new user from the OIDC claims.
        """
        user = User.objects.create_user(username=claims.get('sub'))
        user.is_active = True
        user.save()
        return user
