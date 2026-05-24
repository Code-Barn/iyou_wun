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

import json
import urllib.error
import urllib.request
from urllib.parse import urljoin

from django.conf import settings


class PolyConnectionError(Exception):
    pass


class PolyClient:
    def __init__(self, engine_url=None):
        self.engine_url = (engine_url or settings.POLY_ENGINE_URL).rstrip("/")

    def cast_vote(self, poll_id, vote_payload, timeout=10):
        url = urljoin(f"{self.engine_url}/", f"api/v2/polls/{poll_id}/cast/")
        body = json.dumps(vote_payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "X-Iyou-Wun-Proxy": "true",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, urllib.error.HTTPError, OSError) as exc:
            raise PolyConnectionError(str(exc)) from exc

        if not isinstance(data, dict) or not data.get("valid"):
            raise PolyConnectionError(
                data.get("error", "Poly engine returned invalid response")
            )

        details = data.get("details", {})
        if details.get("duplicate"):
            return {"duplicate": True, "poll_id": poll_id}

        return {"duplicate": False, "poll_id": poll_id, "details": details}
