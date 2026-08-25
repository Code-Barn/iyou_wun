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

import ipaddress
import urllib.error
import urllib.parse
import urllib.request

ALLOWED_BIO_HOSTS = {
    "github.com",
    "x.com",
    "twitter.com",
    "mastodon.social",
    "threads.net",
    "bsky.app",
}

BLOCKED_HOSTNAMES = {"localhost", "0.0.0.0", "::1"}
BLOCKED_HOST_SUFFIXES = (".local", ".internal")

MAX_RESPONSE_BYTES = 512 * 1024
BIO_VERIFY_TIMEOUT = 5.0

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


def _host_is_allowlisted(host):
    host = (host or "").lower().rstrip(".")
    return host in ALLOWED_BIO_HOSTS or any(
        host.endswith(f".{entry}") for entry in ALLOWED_BIO_HOSTS
    )


def _is_ip_literal(host):
    try:
        ipaddress.ip_address((host or "").strip("[]"))
        return True
    except ValueError:
        return False


def _is_blocked_host(host):
    host = (host or "").lower().rstrip(".")
    bare = host.strip("[]")
    if bare in BLOCKED_HOSTNAMES:
        return True
    if bare.endswith(BLOCKED_HOST_SUFFIXES):
        return True
    if _is_ip_literal(bare):
        return True
    return False


def validate_external_bio_url(target_url):
    parsed = urllib.parse.urlparse(target_url or "")
    if parsed.scheme != "https":
        return False, "Only https:// URLs are allowed."
    if not parsed.hostname:
        return False, "URL is missing a hostname."
    if parsed.username or parsed.password:
        return False, "Credentials embedded in URLs are not allowed."
    host = parsed.hostname.lower()
    if _is_blocked_host(host):
        return False, f"Host is blocked for security reasons: {parsed.hostname}"
    if not _host_is_allowlisted(host):
        return False, (
            "Domain is not in the verification allowlist "
            f"({', '.join(sorted(ALLOWED_BIO_HOSTS))})."
        )
    return True, ""


class _AllowlistRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        allowed, reason = validate_external_bio_url(newurl)
        if not allowed:
            raise urllib.error.HTTPError(
                newurl, code, f"Blocked redirect: {reason}", headers, fp
            )
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_OPENER = urllib.request.build_opener(_AllowlistRedirectHandler())


def verify_external_profile_token(target_url, token):
    allowed, reason = validate_external_bio_url(target_url)
    if not allowed:
        return False, reason
    token = (token or "").strip()
    if not token:
        return False, "Verification token is missing."

    request = urllib.request.Request(
        target_url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        },
    )
    try:
        with _OPENER.open(request, timeout=BIO_VERIFY_TIMEOUT) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            body = response.read(MAX_RESPONSE_BYTES + 1)[:MAX_RESPONSE_BYTES]
    except urllib.error.HTTPError as exc:
        return False, f"Fetch failed with HTTP {exc.code}."
    except Exception as exc:
        return False, f"Fetch failed: {exc}"

    html = body.decode(charset, errors="replace")
    if token in html:
        return True, "Token verified successfully"
    return False, "Token not found in bio content"
