# Developer Guide - iyou_wun (WUN)

## Overview

**iyou_wun** (WUN) is a Django 5.2 OIDC Relying Party (Satellite) that authenticates users via the **iyou_idp** identity provider. Users log in with their Decentralized Identifier (DID) using the OpenID Connect flow. A local `django.contrib.auth.User` is created keyed on the `sub` claim (the DID).

The project is in active development. Authentication works end-to-end. The Omni-Social feed (Nostr Kind 1) is implemented and fetches live notes from `wss://nos.lol`.

---

## Tech Stack

| Component           | Technology                           |
| ------------------- | ------------------------------------ |
| Language            | Python 3.10                          |
| Framework           | Django 5.2.13                        |
| Auth                | mozilla-django-oidc 5.0.2            |
| Config              | django-environ 0.13+                 |
| Styling             | Tailwind CSS (CDN)                   |
| Database            | SQLite (default) / `db.sqlite3`      |
| WebSocket           | websocket-client 1.9+                |
| Package manager     | uv                                   |

---

## Quick Start

### Prerequisites
- Python >= 3.10
- A running iyou_idp instance (see `.env` for endpoints)

### Setup

```bash
# Copy environment template and fill in credentials
cp .env.example .env
# Edit .env with your OIDC_RP_CLIENT_ID and OIDC_RP_CLIENT_SECRET

# Install dependencies
uv sync

# Run migrations
uv run python manage.py migrate

# Start the dev server
uv run python manage.py runserver 8001
```

---

## OIDC Environment Variables

The following variables are required in `.env` to connect to the iyou_idp:

| Variable                            | Purpose                                          |
| ----------------------------------- | ------------------------------------------------ |
| `OIDC_OP_AUTHORIZATION_ENDPOINT`    | IdP authorization URL (user login redirect)      |
| `OIDC_OP_TOKEN_ENDPOINT`            | IdP token exchange endpoint                      |
| `OIDC_OP_USER_ENDPOINT`             | IdP userinfo endpoint (returns claims)           |
| `OIDC_OP_JWKS_ENDPOINT`             | IdP JWKS key set endpoint                        |
| `OIDC_RP_CLIENT_ID`                 | Client ID registered with the IdP                |
| `OIDC_RP_CLIENT_SECRET`             | Client secret registered with the IdP            |

Current iyou_idp values (localhost):

```ini
OIDC_OP_AUTHORIZATION_ENDPOINT=http://localhost:8000/openid/authorize/
OIDC_OP_TOKEN_ENDPOINT=http://localhost:8000/openid/token/
OIDC_OP_USER_ENDPOINT=http://localhost:8000/openid/userinfo/
OIDC_OP_JWKS_ENDPOINT=http://localhost:8000/openid/jwks/
OIDC_RP_CLIENT_ID=747582
OIDC_RP_CLIENT_SECRET=1522b34850cdd1140f889d8e0fdf6704e52659af5d9a84adabfdfea0
```

> **Note**: For Local/Sovereign mode, use `http://localhost:8000` to satisfy browser security requirements. Replace with your IdP's IP/host when using Tailscale or other environments.

> **⚠️ FINAL STANDARDIZATION RULE**: After extensive testing, we've determined that **ALL** OIDC endpoints must use `127.0.0.1` to completely eliminate the localhost/127.0.0.1 mismatch that causes session drops on ALL platforms (not just Intel Mac).

**The Winner: 127.0.0.1 Everywhere**

```ini
# FINAL CONFIGURATION - Use 127.0.0.1 for EVERYTHING
OIDC_OP_AUTHORIZATION_ENDPOINT=http://127.0.0.1:8000/openid/authorize/
OIDC_OP_TOKEN_ENDPOINT=http://127.0.0.1:8000/openid/token/
OIDC_OP_USER_ENDPOINT=http://127.0.0.1:8000/openid/userinfo/
OIDC_OP_JWKS_ENDPOINT=http://127.0.0.1:8000/openid/jwks/
OIDC_RP_CALLBACK_URL=http://127.0.0.1:8001/oidc/callback/
```

**Why This Works:**
- Eliminates ALL IPv6 ambiguity (localhost can resolve to ::1)
- Ensures exact issuer matching between IdP and RP
- Prevents browser cookie domain mismatches
- Works consistently across macOS, Linux, and Windows
- Required for OIDC library's issuer validation

**Critical Admin Step:**
Update the IdP Client at `http://127.0.0.1:8000/admin/oidc_provider/client/`:
- **Redirect URIs**: `http://127.0.0.1:8001/oidc/callback/`
- **Post-logout Redirect URI**: `http://127.0.0.1:8001/`
- Delete ANY URIs containing `localhost`

**Without this standardization:**
- Sessions will be dropped randomly
- OIDC issuer validation will fail silently
- Browser cookies may be rejected
- 403/401 errors will appear intermittently

> **Also update the IdP Client's Redirect URIs** in the admin at `http://127.0.0.1:8000/admin/oidc_provider/client/` to include both:
> - `http://localhost:8001/oidc/callback/`
> - `http://127.0.0.1:8001/oidc/callback/`

> Without both URIs registered, you'll get `redirect_uri_mismatch` errors.

### How authentication flows

```
User  ──GET /──>  WUN (home page: login button)
  │
  ├──Click "Login"──>  IdP /openid/authorize/
  │                        │
  │                  User authenticates at IdP
  │                        │
  │  <──Auth code redirect──┘
  │
  ├──WUN exchanges code at IdP /openid/token/
  │
  ├──WUN fetches claims at IdP /openid/userinfo/
  │
  └──User created/logged in locally ──> /dashboard
```

The `mozilla-django-oidc` library handles the token exchange, userinfo retrieval, and local user creation automatically.

---

## MyOIDCAuthenticationBackend: User Mapping Logic

**File:** `apps/core/auth.py`

```python
class MyOIDCAuthenticationBackend(OIDCAuthenticationBackend):
    def create_user(self, claims):
        user = User.objects.create_user(username=claims.get('sub'))
        user.is_active = True
        user.save()
        return user
```

### How it works

1. **Trigger**: Called by `mozilla-django-oidc` when a user authenticates via the IdP and no local user exists for the given `sub` claim.

2. **Claim extraction**: The `claims` dict is the parsed JSON from the IdP's `/openid/userinfo/` endpoint. The `sub` claim contains the user's DID (e.g. `did:iyou:0xabcd...`).

3. **User creation**: `User.objects.create_user(username=claims.get('sub'))` creates a standard Django user with the DID as the username. No email or password is set -- authentication is delegated entirely to the IdP.

4. **Active by default**: `user.is_active = True` ensures the user can log in immediately.

5. **Subsequent logins**: On repeat visits, `filter_users_by_claims` (inherited from the base backend) finds the existing user by the `sub` claim, and `update_user` refreshes their attributes. The base backend's default `update_user` is a no-op, which is fine for now.

### `OIDC_USERNAME_ALGO`

In `settings.py`, `OIDC_USERNAME_ALGO = lambda claims: claims.get('sub')` provides a second mechanism for deriving the username. This is used by the base backend's `create_user` when it is not overridden. Since we override `create_user`, this lambda is effectively redundant but harmless.

---

## Omni-Social Feed (Nostr Kind 1)

**File:** `apps/core/views.py` — `fetch_nostr_notes()` / `FeedView`

The feed connects to `wss://nos.lol` via the `websocket-client` library and fetches the last 20 Kind-1 (Short Text Note) events using the NIP-01 `REQ` message format.

### How it works

1. `FeedView.get_context_data()` calls `fetch_nostr_notes(limit=20)`
2. A `WebSocketApp` is opened to `wss://nos.lol` in a daemon thread
3. On connect, a `["REQ", "wun_feed", {"kinds": [1], "limit": 20}]` message is sent
4. Incoming `EVENT` messages are parsed and collected as dicts (pubkey, content, created_at)
5. `EOSE` (End of Stored Events) or a 10-second timeout signals completion
6. Notes are sorted reverse-chronologically and capped at `limit`

### Why not `nostr==0.0.2` package?

The `nostr` PyPI package was initially used but had critical API mismatches:
- `Relay(relay_url)` — constructor requires 4 positional args, not just a URL
- `relay.subscribe()` — method doesn't exist
- `Event.from_message()` — static method doesn't exist
- `relay.connect()` — calls `run_forever()` which blocks indefinitely (needs threading)
- No REQ message was ever sent to the relay (subscriptions stored locally only)

The package also transitively depends on `secp256k1==0.14.0`, which requires a C compiler and `make` to build. Since we bypass the library entirely, `nostr` was removed from dependencies in favor of direct `websocket-client` usage.

### Template

**File:** `templates/feed.html`

Tailwind-styled card list showing each note's pubkey (truncated), timestamp, and content. Shows "Loading notes..." when empty. Includes nav to Dashboard and Logout.

---

## Settings Ghosting (Fixed)

**Problem:** `OIDC_RP_CLIENT_ID` and `OIDC_RP_CLIENT_SECRET` had fallback defaults:

```python
# BEFORE — silent fallback masked broken .env config
OIDC_RP_CLIENT_ID = env.str('OIDC_RP_CLIENT_ID', 'wun-client')
OIDC_RP_CLIENT_SECRET = env.str('OIDC_RP_CLIENT_SECRET', 'wun-secret')
```

If `.env` was missing or malformed, Django silently used `'wun-client'` / `'wun-secret'` instead of crashing with a clear error. This "ghost" config made it seem like authentication was set up when it was pointing at nothing.

**Fix:** Removed all default values:

```python
# AFTER — crashes fast if .env is broken
OIDC_RP_CLIENT_ID = env.str('OIDC_RP_CLIENT_ID')
OIDC_RP_CLIENT_SECRET = env.str('OIDC_RP_CLIENT_SECRET')
```

Now Django raises `ImproperlyConfigured` immediately if these variables are missing, which makes debugging trivial.

---

## Project Layout

```
.
├── main.py                          # CLI entry point (stub)
├── pyproject.toml                   # Project metadata & dependencies
├── .env                             # Environment variables (git-ignored)
├── .env.example                     # Template for .env (safe to commit)
├── WUN_DEVELOPER_GUIDE.md           # This file
├── config/
│   ├── settings.py                  # Django settings (OIDC, auth, apps)
│   ├── urls.py                      # Root URL configuration
│   ├── wsgi.py                      # WSGI entrypoint
│   └── asgi.py                      # ASGI entrypoint
├── apps/core/
│   ├── __init__.py
│   ├── apps.py                      # Django app config
│   ├── views.py                     # home(), dashboard(), FeedView, fetch_nostr_notes()
│   ├── urls.py                      # App-level URL routing
│   ├── auth.py                      # MyOIDCAuthenticationBackend
│   ├── models.py                    # (empty -- no models yet)
│   ├── admin.py                     # (empty -- no admin registrations)
│   └── tests.py                     # OIDC auth, view & JWKS connectivity tests
└── templates/
    ├── home.html                    # Landing page with login button
    ├── dashboard.html               # Authenticated user dashboard (DID display)
    └── feed.html                    # Omni-Social feed (Nostr Kind 1 notes)
```

### URL Map

| Path              | View         | Auth Required | Notes                         |
| ----------------- | ------------ | ------------- | ----------------------------- |
| `/`               | `home`       | No            | Landing page                  |
| `/dashboard`      | `dashboard`  | Yes           | Shows user DID & session      |
| `/feed`           | `FeedView`   | Yes           | Nostr global feed (Kind 1)    |
| `/admin/`         | Django admin | —             |                               |
| `/oidc/`          | OIDC flow    | —             | Provided by mozilla-django-oidc |

---

## Running Tests

```bash
uv run python manage.py test
```

Tests cover:
- `MyOIDCAuthenticationBackend.create_user` — ensures a user is created with the DID from the `sub` claim (5 tests)
- Dashboard view — authenticated users see their DID; unauthenticated users are redirected to login (5 tests)
- Home page — unauthenticated users see the login prompt (3 tests)
- `JwksConnectivityTest` — pings the IdP's JWKS endpoint and validates the key set response (skips gracefully if IdP is down)

---

## Troubleshooting / War Stories

### `secp256k1` build failure

```
× Failed to build `secp256k1==0.14.0`
  subprocess.CalledProcessError: Command '['make']' returned non-zero exit status 2.
```

**Cause:** The `nostr==0.0.2` package transitively depends on `secp256k1==0.14.0`, which requires a working C compiler and `make`. Not all environments have these, and the C extension can fail to compile on macOS ARM or minimal containers.

**Fix:** Removed `nostr` from `pyproject.toml`. The Nostr feed now uses `websocket-client` directly with raw NIP-01 JSON messages over WebSocket. No C extensions needed.

### `nostr` library API was completely wrong

The `nostr==0.0.2` PyPI package has a unique API that doesn't match common examples. Every call in the initial implementation was wrong:
- Wrong constructor signature
- Wrong method names
- Wrong event parsing
- No actual REQ message sent to relays

**Fix:** Bypassed the library entirely. The current implementation uses `websocket-client` directly, sending raw `["REQ", ...]` JSON messages per the NIP-01 spec and parsing `["EVENT", ...]` responses. This is simpler, faster, and has zero native dependencies.

---

## Known Issues

- `.env` was previously committed to git — now removed from tracking and gitignored. **DO NOT re-commit it.**
- `OIDC_USERNAME_ALGO` lambda and `MyOIDCAuthenticationBackend.create_user` both derive the username from `sub` — redundant but not harmful. Clean up by choosing one approach.
- No domain models yet (`models.py` is empty).
- `main.py` is a stub with unclear purpose.
- Production hardening needed: `DEBUG = True`, default `SECRET_KEY`, empty `ALLOWED_HOSTS`, Tailwind via CDN.
- `apps/core/admin.py` is empty — no models registered for the admin interface.
- `uv.lock` exists but should be regenerated after dependency changes with `uv sync`.
