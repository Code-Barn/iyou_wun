import pytest
from django.contrib.auth.models import User

from .tests.helpers import VALID_PUBKEY_HEX, SAMPLE_DID


@pytest.fixture
def oidc_claims():
    return {"sub": SAMPLE_DID}


@pytest.fixture
def alt_oidc_claims():
    return {"sub": "did:iyou:0x123456789abcdef"}


@pytest.fixture
def oidc_user(django_user_model, oidc_claims):
    user = django_user_model.objects.create_user(username=oidc_claims["sub"])
    user.set_unusable_password()
    user.is_active = True
    user.save()
    return user


@pytest.fixture
def authenticated_client(client, oidc_user):
    client.force_login(oidc_user)
    return client


@pytest.fixture
def valid_hex_pubkey():
    return VALID_PUBKEY_HEX


@pytest.fixture
def sample_nostr_event(valid_hex_pubkey):
    def _make(eid="abc123", kind=1, pubkey=None, content="hello", tags=None, created_at=1000000):
        return {
            "id": eid,
            "kind": kind,
            "pubkey": pubkey or valid_hex_pubkey,
            "content": content,
            "tags": tags or [],
            "created_at": created_at,
        }
    return _make
