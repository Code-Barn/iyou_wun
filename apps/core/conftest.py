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

import pytest

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
