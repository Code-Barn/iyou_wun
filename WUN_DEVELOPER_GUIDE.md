# Developer Guide - iyou_wun (WUN)

## Overview

**iyou_wun** (WUN) is a Django 5.2 OIDC Relying Party (Satellite) that authenticates users via the **iyou_idp** identity provider. Users log in with their Decentralized Identifier (DID) using the OpenID Connect flow. A local `django.contrib.auth.User` is created keyed on the `sub` claim (the DID).

The project is in active development. Authentication works end-to-end. Beyond the Omni-Social feed (Nostr Kind 1), WUN now includes a **Media Gallery** (Kind 1063 grid), **Sovereign Profile pages**, **XMPP Chat** via Converse.js, and **Double-Broadcast** to both local and global relays.

**Identity Model — Passwords are DEPRECATED.** The OIDC/DID authentication loop is the sole entry point. No username/password forms exist. Users authenticate via their iyou_idp using their Decentralized Identifier. Local `django.contrib.auth.User` records are created with `set_unusable_password()` and exist only as session anchors.

---

## Tech Stack

| Component           | Technology                           |
| ------------------- | ------------------------------------ |
| Language            | Python 3.12                          |
| Framework           | Django 5.2.13                        |
| Auth                | mozilla-django-oidc 5.0.2            |
| Config              | django-environ 0.13+                 |
| Styling             | Tailwind CSS (CDN, v3)              |
| Database            | PostgreSQL (production via DATABASE_URL), SQLite (default local dev) |
| WSGI server         | Gunicorn 23+                         |
| WebSocket (server)  | websocket-client 1.9+                |
| WebSocket (client)  | Native browser `WebSocket` API       |
| Nostr relays        | nos.lol, relay.iyou.me, local :9003  |
| XMPP client         | Converse.js (CDN)                    |
| Media server        | Blossom (iyou_home, port 9002)       |
| Signing bridge      | Tauri (iyou_home, port 9001)         |
| DID conversion      | bech32 library                       |
| Package manager     | uv                                   |
| Container runtime   | Docker (multi-stage, python:3.12-slim) |

---

## Quick Start

### Prerequisites
- Python >= 3.10
- A running iyou_idp instance (see `.env` for endpoints)
- iyou_home running (provides Tauri signing bridge :9001, Blossom :9002, local relay :9003)

### Setup

```bash
# Copy environment template and fill in credentials
cp .env.example .env
# Edit .env with your OIDC_RP_CLIENT_ID, OIDC_RP_CLIENT_SECRET,
# WUN_SECRET_KEY (any long random string), and DATABASE_URL if using PostgreSQL

# Install dependencies
uv sync

# Run migrations
uv run python manage.py migrate

# Start the dev server
uv run python manage.py runserver 8001
```

### Production (Docker)

```bash
# Build the production image (multi-stage, uv-compiled)
docker build -t iyou-wun:latest .

# Run with required env vars
docker run -d --name iyou-wun \
  -p 8001:8000 \
  -e WUN_SECRET_KEY="<long-random-secret>" \
  -e WUN_DEBUG=False \
  -e WUN_ALLOWED_HOSTS="['localhost','127.0.0.1','wun.iyou.me']" \
  -e DATABASE_URL="postgres://user:pass@host:5432/wun" \
  -e OIDC_RP_CLIENT_ID="747582" \
  -e OIDC_RP_CLIENT_SECRET="<secret>" \
  iyou-wun:latest
```

> Port mapping: `8001:8000` because the container binds internally on `8000` (Gunicorn), and Traefik/K3s exposes it as `8001` at the ingress layer.

---

## Environment Variables

### WUN_ Namespace (Django Core)

The `config/settings.py` reads operational parameters from `WUN_`-prefixed env vars. These are required for all environments:

| Variable                          | Default                         | Purpose                            |
| --------------------------------- | ------------------------------- | ---------------------------------- |
| `WUN_SECRET_KEY`                  | *(required — no default)*       | Django secret key (production-grade random string) |
| `WUN_DEBUG`                       | `False`                         | Django debug mode                  |
| `WUN_ALLOWED_HOSTS`               | `['localhost', '127.0.0.1']`    | Django allowed hosts (list format) |
| `DATABASE_URL`                    | `sqlite:///db.sqlite3`          | Database connection string (use `postgres://...` in production) |

### OIDC Endpoints

The following variables connect to the iyou_idp. Fallback defaults target the cluster-internal DNS routing:

| Variable                            | Production Default (Cluster DNS)                          | Purpose                                          |
| ----------------------------------- | --------------------------------------------------------- | ------------------------------------------------ |
| `OIDC_OP_AUTHORIZATION_ENDPOINT`    | `https://idp.iyou.me/openid/authorize/`                   | IdP authorization URL (browser-facing redirect)  |
| `OIDC_OP_TOKEN_ENDPOINT`            | `http://iyou-idp.identity.svc.cluster.local:8000/openid/token/` | IdP token exchange (back-channel)          |
| `OIDC_OP_USER_ENDPOINT`             | `http://iyou-idp.identity.svc.cluster.local:8000/openid/userinfo/` | IdP userinfo/claims (back-channel)         |
| `OIDC_OP_JWKS_ENDPOINT`             | `http://iyou-idp.identity.svc.cluster.local:8000/openid/jwks/` | IdP JWKS key set (back-channel)                 |
| `OIDC_RP_CLIENT_ID`                 | *(required — no default)*       | Client ID registered with the IdP                |
| `OIDC_RP_CLIENT_SECRET`             | *(required — no default)*       | Client secret registered with the IdP            |
| `OIDC_RP_CALLBACK_URL`              | `http://127.0.0.1:8001/oidc/callback/` | OIDC callback URL                          |

Current iyou_idp development values (localhost):

```ini
OIDC_OP_AUTHORIZATION_ENDPOINT=http://127.0.0.1:8000/openid/authorize/
OIDC_OP_TOKEN_ENDPOINT=http://127.0.0.1:8000/openid/token/
OIDC_OP_USER_ENDPOINT=http://127.0.0.1:8000/openid/userinfo/
OIDC_OP_JWKS_ENDPOINT=http://127.0.0.1:8000/openid/jwks/
OIDC_RP_CALLBACK_URL=http://127.0.0.1:8001/oidc/callback/
OIDC_RP_CLIENT_ID=747582
OIDC_RP_CLIENT_SECRET=1522b34850cdd1140f889d8e0fdf6704e52659af5d9a84adabfdfea0
```

> **⚠️ FINAL STANDARDIZATION RULE**: After extensive testing, we've determined that **ALL** OIDC endpoints must use `127.0.0.1` to completely eliminate the localhost/127.0.0.1 mismatch that causes session drops on ALL platforms (not just Intel Mac).

### 127.0.0.1 Binding Rule

```ini
# FINAL CONFIGURATION - Use 127.0.0.1 for EVERYTHING
OIDC_OP_AUTHORIZATION_ENDPOINT=http://127.0.0.1:8000/openid/authorize/
OIDC_OP_TOKEN_ENDPOINT=http://127.0.0.1:8000/openid/token/
OIDC_OP_USER_ENDPOINT=http://127.0.0.1:8000/openid/userinfo/
OIDC_OP_JWKS_ENDPOINT=http://127.0.0.1:8000/openid/jwks/
OIDC_RP_CALLBACK_URL=http://127.0.0.1:8001/oidc/callback/
```

**Why 127.0.0.1 everywhere:**
- Eliminates ALL IPv6 ambiguity (localhost can resolve to ::1)
- Ensures exact issuer matching between IdP and RP
- Prevents browser cookie domain mismatches
- Works consistently across macOS, Linux, and Windows
- Required for OIDC library's issuer validation

**PNA (Private Network Access) headers**: Browsers (especially Safari) require the `Access-Control-Allow-Private-Network: true` header on responses from local services (Blossom :9002, Tauri bridge :9001) when accessed from a public origin. iyou_home now sends this header. If you see `TypeError: Load failed` in the console during media upload, verify the header is present.

**Critical Admin Step:**
Update the IdP Client at `http://127.0.0.1:8000/admin/oidc_provider/client/`:
- **Redirect URIs**: `http://127.0.0.1:8001/oidc/callback/`
- **Post-logout Redirect URI**: `http://127.0.0.1:8001/`
- Delete ANY URIs containing `localhost`

> Without this URI registered, you'll get `redirect_uri_mismatch` errors.

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

## Signature Bridge (Port 9001 — Tauri)

**File:** `templates/feed.html` / `templates/dashboard.html` (inline JavaScript)

The Tauri signing bridge at `ws://127.0.0.1:9001` is a WebSocket endpoint provided by iyou_home that signs Nostr events with the user's local key. The browser never has access to the private key.

### Supported Message Types

| Type (client → bridge)   | Type (bridge → client)    | Purpose                                  |
|--------------------------|---------------------------|------------------------------------------|
| `sign_event`             | `signed_event`            | Sign a Nostr event (any kind)            |
| `sign`                   | `signed_message`          | Sign an arbitrary string                 |
| `sign_credential`        | `signed_credential`       | Sign a Verifiable Credential (VC)        |

### sign_event Flow

1. Browser sends `{"type": "sign_event", "event": {kind, content, pubkey, created_at, tags}}`
2. Tauri bridge signs with the local key, returns `{"type": "signed_event", "event": {id, sig, ...}}`
3. Browser copies `id` and `sig` into the pending event, then broadcasts to relays

### Connection Management

- The WebSocket is opened lazily on first post (`initTauriSocket()`)
- A 5-second timeout abandons signing if the bridge is unreachable
- The `isProcessing` flag prevents concurrent signing requests

### Events Signed by the Bridge

| Kind | Description          | Source View      |
|------|----------------------|------------------|
| 1    | Short text note      | Feed             |
| 0    | Profile metadata     | Dashboard        |
| 1063 | Media (Blossom hash) | Feed             |

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

    def filter_users_by_claims(self, claims):
        did = claims.get('sub')
        if not did:
            return User.objects.none()

        user, created = User.objects.get_or_create(username=did)

        if created:
            user.set_unusable_password()
            user.is_active = True
            user.save()

        return User.objects.filter(id=user.id)

    def verify_claims(self, claims):
        return 'sub' in claims

    def get_username(self, claims):
        return claims.get('sub')
```

### Identity Model — Passwords DEPRECATED

- **No password-based login.** The OIDC/DID loop is the only authentication path.
- `set_unusable_password()` is called on every new user. Password-based auth is impossible.
- Django's `ModelBackend` is kept in `AUTHENTICATION_BACKENDS` only for `force_login` in tests.
- The `sub` claim (the raw DID, e.g. `did:key:z6Mkpw...`) is the Django username.
- Email is not required, not collected, and not used.

### How it works

1. **Trigger**: The OIDC library calls these methods during authentication to map IdP claims to local users.

2. **Claim extraction**: The `claims` dict contains parsed data from the IdP's `/openid/userinfo/` endpoint. The `sub` claim contains the user's DID.

3. **User creation/lookup**: 
   - `filter_users_by_claims`: Primary method that finds or creates users
   - Uses `get_or_create()` for atomic operations
   - Returns QuerySet (required by OIDC library)
   - Sets unusable password for security

4. **Claims verification**: `verify_claims` only requires the `sub` claim (DID), no email needed

5. **Username mapping**: `get_username` extracts the DID from claims for use as Django username

6. **Subsequent logins**: The OIDC library calls `filter_users_by_claims` on repeat visits, which returns the existing user as a QuerySet.

---

## Omni-Social Feed (Nostr)

**File:** `apps/core/views.py` — `FeedView`, `relay_req()`

### How It Works Today

1. `FeedView.get_context_data()` fetches a multi-kind feed: Kind 1 (text), Kind 7 (reactions), Kind 1063 (media), Kind 1111 (comments)
2. A `WebSocketApp` connects to `wss://nos.lol` and sends a NIP-01 `REQ` message
3. `EOSE` or a 10-second timeout signals completion
4. `process_into_feed()` groups reactions/comments under parents, injects Kind 0 profile data, and sorts reverse-chronologically
5. **Double-Broadcast**: When posting, the signed event is sent simultaneously to:
   - `ws://127.0.0.1:9003` (local relay — triggers "Sovereign Copy Saved" toast)
   - `wss://relay.iyou.me` (project relay)
   - `wss://nos.lol` (global relay)
6. Broadcasting is **parallel** — one relay failure does not block others
7. **Thread View**: `?thread=<event_id>` fetches a parent event and its children for focused conversation viewing

### Media Support (Kind 1063)

Media files are uploaded to the local Blossom server at `http://127.0.0.1:9002/<sha256>` via HTTP PUT. A signed Kind 1063 event is then broadcast with the URL and MIME type. Events with `file_url` containing `127.0.0.1` are marked `is_sovereign` and display an amber badge.

### Gallery View

The **Media Gallery** (`/gallery`) renders all Kind 1063 events in a responsive CSS grid with MIME-type filtering (All / Images / Video / Audio). Clicking a card opens a fullscreen modal with native `<video>`, `<audio>`, or full-resolution `<img>` playback.

---

## Sovereign Profile Pages

**Routes:** `/profile/<npub>/`

**File:** `apps/core/views.py` — `ProfileView`, `fetch_profile_data()`, `fetch_text_notes()`, `fetch_media_assets()`

Each profile page displays:
- **Kind 0 metadata**: Avatar (picture), display name, bio, nip05 identifier
- **Sovereign Score**: Count of the user's Kind 1063 events whose `file_url` points to `127.0.0.1` (local Blossom server)
- **Recent Broadcasts**: Kind 1 text notes, enriched with profile data
- **Media Assets**: Kind 1063 media in a compact grid with sovereign/verified badges

Profile pages are public (no login required).

### Dashboard — Edit Profile

**File:** `templates/dashboard.html`

Authenticated users can publish a Kind 0 profile event from the Dashboard:
1. Form fields: Display Name, Picture URL, Bio/About
2. On submit, constructs a Kind 0 event with JSON-stringified content
3. Sends to the Tauri signing bridge (`ws://127.0.0.1:9001`) for signing
4. Broadcasts the signed event to all three relays in parallel
5. Toast feedback on success/failure

---

## XMPP Chat

**Route:** `/chat`

**File:** `templates/chat.html`

A minimal sovereign chat interface using [Converse.js](https://conversejs.org/) loaded via CDN:
- **WebSocket endpoint**: `ws://127.0.0.1:5222`
- **JID format**: `{nostr_hex_pubkey}@127.0.0.1`
- **Password**: `{nostr_hex_pubkey}` (same as JID user part)
- **Fullscreen mode**: Converse.js fills the viewport below the nav bar
- **Auto-login**: Connects on page load using the derived credentials

All messages remain local to the :5222 XMPP server and are NEVER stored in the WUN database.

---

## Mesh Awareness

### Port Map

| Service          | Port | Protocol | Purpose                         |
|------------------|------|----------|---------------------------------|
| iyou_idp         | 8000 | HTTP     | OpenID Provider                 |
| iyou_wun (Django)| 8001 | HTTP     | This application                |
| Tauri bridge     | 9001 | WebSocket| Nostr event signing             |
| Blossom media    | 9002 | HTTP     | File storage (PUT/GET by hash)  |
| Local relay      | 9003 | WebSocket| Local Nostr event relay         |
| XMPP server      | 5222 | WebSocket| Sovereign chat messaging        |

### 127.0.0.1 Binding Rule

**ALL** services must bind to `127.0.0.1` — never `localhost`. This eliminates IPv6 ambiguity (localhost can resolve to `::1`), ensures OIDC issuer matching, prevents browser cookie domain mismatches, and satisfies Safari's Private Network Access (PNA) requirements.

### PNA Headers

Safari and Chrome enforce Private Network Access for requests from public pages to local network services. iyou_home sends:

```
Access-Control-Allow-Private-Network: true
```

on responses from the Blossom server (:9002), Tauri bridge (:9001), and local relay (:9003). Without this header, the browser blocks requests with `TypeError: Load failed`.

### Sovereign Mesh Badge

The navigation bar (`_nav.html`) probes `http://127.0.0.1:9001/` with a 300ms timeout on page load. If the Tauri bridge responds, a green **"Sovereign Mesh Active"** badge appears. No badge = bridge is offline.

---

## Project Layout

```
.
├── main.py                          # CLI entry point (stub)
├── pyproject.toml                   # Project metadata & dependencies
├── Dockerfile                       # Multi-stage production build (uv + gunicorn)
├── docker-entrypoint.sh             # Container init (migrate → gunicorn on :8000)
├── .dockerignore                    # Excludes garbage from Docker context
├── .env                             # Environment variables (git-ignored)
├── .env.example                     # Template for .env (safe to commit)
├── WUN_DEVELOPER_GUIDE.md           # This file
├── config/
│   ├── settings.py                  # Django settings (OIDC, auth, apps, CSRF)
│   ├── urls.py                      # Root URL configuration
│   ├── wsgi.py                      # WSGI entrypoint
│   └── asgi.py                      # ASGI entrypoint
├── apps/core/
│   ├── __init__.py
│   ├── apps.py                      # Django app config
│   ├── views.py                     # home(), dashboard(), FeedView, GalleryView,
│   │                                # ProfileView, ChatView, + Nostr helpers
│   ├── urls.py                      # App-level URL routing
│   ├── auth.py                      # MyOIDCAuthenticationBackend
│   ├── models.py                    # (empty -- no models yet)
│   ├── admin.py                     # (empty -- no admin registrations)
│   ├── conftest.py                  # pytest fixtures (OIDC claims, users, Nostr events)
│   └── tests/
│       ├── __init__.py
│       ├── helpers.py               # Reusable test utilities (create_oidc_user, make_event, etc.)
│       ├── test_auth.py             # 17 tests: auth backend, password rejection, OIDC enforcement
│       ├── test_views.py            # 23 tests: home, dashboard, chat, gallery, profile
│       └── test_feed.py             # 24 tests: process_into_feed threading integrity
└── templates/
    ├── _nav.html                    # Shared navigation (DRY — included by all views)
    ├── home.html                    # Landing page with login button
    ├── dashboard.html               # Dashboard + Edit Profile (Kind 0 broadcast)
    ├── feed.html                    # Omni-Social feed (Kind 1, 1063, 1111)
    ├── gallery.html                 # Media gallery (Kind 1063 grid + modal)
    ├── profile.html                 # Sovereign profile pages
    └── chat.html                    # XMPP chat (Converse.js)
```

### URL Map

| Path                  | View           | Auth Required | Notes                                |
| --------------------- | -------------- | ------------- | ------------------------------------ |
| `/`                   | `home`         | No            | Landing page                         |
| `/dashboard`          | `dashboard`    | Yes           | DID display + Edit Profile (Kind 0)  |
| `/feed`               | `FeedView`     | Yes           | Unified Nostr feed + thread view     |
| `/gallery`            | `GalleryView`  | Yes           | Media grid with MIME filters + modal |
| `/profile/<npub>/`    | `ProfileView`  | No            | Sovereign profile (Kind 0, 1, 1063)  |
| `/chat`               | `ChatView`     | Yes           | XMPP sovereign chat                  |
| `/admin/`             | Django admin   | —             |                                      |
| `/oidc/`              | OIDC flow      | —             | Provided by mozilla-django-oidc      |

---

## Running Tests

```bash
uv run python manage.py test apps.core.tests
```

Tests cover (64 total across 3 modules):

### `test_auth.py` (17 tests)
- `MyOIDCAuthenticationBackendTest` — DID-based user creation (5 tests)
- `SovereignOnboardingTest` — filter_users_by_claims, get_username, verify_claims (5 tests)
- `PasswordRejectionTest` — OIDC users have unusable passwords, ModelBackend rejects them (4 tests)
- `OIDCBackendEnforcementTest` — OIDC backend registered, LOGIN_URL points to oidc (3 tests)

### `test_views.py` (23 tests)
- `HomeViewTest` — landing page rendering (3 tests)
- `DashboardViewTest` — authenticated DID display, logout link (5 tests)
- `ChatViewTest` — anonymous redirect, XMPP init, nav links (6 tests)
- `GalleryViewTest` — anonymous redirect, media heading, nav links (4 tests)
- `ProfileViewTest` — invalid npub error, valid npub page render (2 tests)
- `DashboardProfileTest` — profile section, publish button (2 tests)
- `JwksConnectivityTest` — IdP JWKS endpoint integration (1 test, skips if IdP is down)

### `test_feed.py` (24 tests)
- `ProcessIntoFeedTest` — empty input, kind 1/1063/7/1111 routing, reaction grouping/dedup,
  orphan comment preservation, sovereign flag, profile enrichment, sort order,
  max_items truncation, malformed events, missing fields, mixed kinds, npub generation

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

### CORS / Private Network Access errors on media upload

If `handleMediaSelected()` fails with `TypeError: Load failed`, the iyou_home Blossom server at `:9002` may be missing the `Access-Control-Allow-Private-Network: true` response header. Verify the header using browser DevTools (Network tab) on the PUT request to `http://127.0.0.1:9002/<hash>`.

### 403 Forbidden across apps on 127.0.0.1

If you get 403 CSRF errors when switching between WUN and another app on 127.0.0.1, ensure both apps use unique cookie names:

```python
# config/settings.py
SESSION_COOKIE_NAME = 'wun_sessionid'
CSRF_COOKIE_NAME = 'wun_csrftoken'
```

---

## Known Issues

- `.env` was previously committed to git — now removed from tracking and gitignored. **DO NOT re-commit it.**
- `OIDC_USERNAME_ALGO` lambda and `MyOIDCAuthenticationBackend.create_user` both derive the username from `sub` — redundant but not harmful. Clean up by choosing one approach.
- No domain models yet (`models.py` is empty).
- `main.py` is a stub with unclear purpose.
- `apps/core/admin.py` is empty — no models registered for the admin interface.
- Tailwind CSS is loaded via CDN — consider a build step for production offline resilience.
- Profile pages (`/profile/<npub>/`) are public but the feed/gallery links to them are only visible to authenticated users.
