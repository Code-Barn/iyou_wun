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

from django.contrib.auth.models import User

VALID_PUBKEY_HEX = "3bf0c63fcb93463407af97a5e5ee64fa883d107ef9e558472c4eb9aaaefa459d"
SAMPLE_DID = "did:key:z6MkhaXgBZDvB9gGHgK9r"
SAMPLE_IYOU_DID = "did:iyou:0x123456789abcdef"


def create_oidc_user(username=None):
    if username is None:
        username = SAMPLE_DID
    user = User.objects.create_user(username=username)
    user.set_unusable_password()
    user.is_active = True
    user.save()
    return user


def make_claims(sub=None):
    return {"sub": sub or SAMPLE_DID}


def make_event(eid, kind, pubkey=None, content="", tags=None, created_at=None):
    return {
        "id": eid,
        "kind": kind,
        "pubkey": pubkey or VALID_PUBKEY_HEX,
        "content": content,
        "tags": tags or [],
        "created_at": created_at or 1000000,
    }
