# Developer Guide - iyou_wun (WUN)

## Overview

**iyou_wun** (WUN) is a Django 5.2 OIDC Relying Party (Satellite) that authenticates users via the **iyou_idp** identity provider. Users log in with their Decentralized Identifier (DID) using the OpenID Connect flow. A local `django.contrib.auth.User` is created keyed on the `sub` claim (the DID).

The project is in active development. The root URL (`/`) immediately redirects to the **Omni-Social Feed** — no login wall. Authentication is fully delegated to `iyou_idp`; WUN acts as a public-read satellite with authenticated capabilities (posting, voting, chat). Beyond the feed (Nostr Kind 1), WUN includes a **Media Gallery** (Kind 1063 grid), **Sovereign Profile pages**, **XMPP Chat** via Converse.js, **Poly Governance polls** (Kind 30023/1112), **Double-Broadcast** to both local and global relays, a **progressive multi-tier search** engine, a **3-column discovery feed shell** with right rail, and a **toast notification engine**.

**Identity Model — Passwords are DEPRECATED.** The OIDC/DID authentication loop is the sole entry point. No username/password forms exist. Users authenticate via their iyou_idp using their Decentralized Identifier. Local `django.contrib.auth.User` records are created with `set_unusable_password()` and exist only as session anchors.

---

## Tech Stack

| Component           | Technology                           |
| ------------------- | ------------------------------------ |
| Language            | Python 3.10+                         |
| Framework           | Django 5.2.13                        |
| Auth                | mozilla-django-oidc 5.0.2            |
| Config              | django-environ 0.13+                 |
| Styling             | Tailwind CSS (pre-compiled via `npm run build:css`) |
| Database            | PostgreSQL (production via DATABASE_URL), SQLite (default local dev) |
| WSGI server         | Gunicorn 23+                         |
| WebSocket (server)  | websocket-client 1.9+                |
| WebSocket (client)  | Native browser `WebSocket` API       |
| Nostr relays        | nos.lol, relay.iyou.me, local :9003  |
| XMPP client         | Converse.js (CDN)                    |
| Media server        | Blossom (iyou_home, port 9002)       |
| Signing bridge      | Tauri (iyou_home, port 9001)         |
| **Poly engine**     | **Headless calculation engine (POLY_ENGINE_URL env var)** |
| DID conversion      | bech32 library                       |
| VC signing          | cryptography 44+ (Ed25519)           |
| Static file serving | WhiteNoise 6.12+ (CompressedManifestStaticFilesStorage in production) |
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
# Edit .env with your WUN_SECRET_KEY (any long random string),
# and DATABASE_URL if using PostgreSQL.
# OIDC client credentials default to ecosystem PKCE standard — no edits needed for local dev.

# Install dependencies
uv sync

# Run migrations
uv run python manage.py migrate

# Start the dev server
uv run python manage.py runserver 8001
```

### Production (Docker)

```bash
# Build the production image (multi-stage, uv-compiled, collectstatic runs at build time)
docker build -t iyou-wun:latest .

# Run with required env vars
docker run -d --name iyou-wun \
  -p 8001:8000 \
  -e WUN_SECRET_KEY="<long-random-secret>" \
  -e WUN_DEBUG=False \
  -e WUN_ALLOWED_HOSTS="['localhost','127.0.0.1','wun.iyou.me']" \
  -e DATABASE_URL="postgres://user:pass@host:5432/wun" \
  -e POLY_ENGINE_URL="http://127.0.0.1:8002" \
  -e OIDC_RP_CLIENT_ID="iyou-wun-satellite-client" \
  -e OIDC_RP_CLIENT_SECRET="" \
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
| `POLY_ENGINE_URL`                 | `http://127.0.0.1:8002`         | Headless calculation engine (Poly governance voting) |
| `NODE_DID`                        | `did:key:z6Mkdevlocal...`       | Node's own DID (used as VC issuer) |
| `NODE_PRIVATE_KEY_HEX`            | *(derived from WUN_SECRET_KEY)*  | Ed25519 private key hex (32 bytes → 64 chars). If set, takes absolute precedence over WUN_SECRET_KEY derivation. |
| `IDP_HOME_URL`                    | `https://home.iyou.me/`         | iyou_home HTTP endpoint (mesh badge health check) |
| `IDP_HOME_WS_URL`                 | `wss://home.iyou.me:9001/`      | iyou_home Tauri signing bridge WebSocket |
| `XMPP_DOMAIN`                     | `127.0.0.1`                    | XMPP chat server domain for JID construction |
| `XMPP_WS_URL`                     | `ws://127.0.0.1:5222`          | XMPP WebSocket endpoint (Converse.js) |
| `WUN_USER_LEVEL`                  | `2`                            | User infrastructure level: `1` = Managed (cluster), `2` = Sovereign (local enclave) |

### OIDC Endpoints

The following variables connect to the iyou_idp. Fallback defaults target the cluster-internal DNS routing:

| Variable                            | Production Default (Cluster DNS)                          | Purpose                                          |
| ----------------------------------- | --------------------------------------------------------- | ------------------------------------------------ |
| `OIDC_OP_AUTHORIZATION_ENDPOINT`    | `https://idp.iyou.me/openid/authorize/`                   | IdP authorization URL (browser-facing redirect)  |
| `OIDC_OP_TOKEN_ENDPOINT`            | `http://iyou-idp.identity.svc.cluster.local:8000/openid/token/` | IdP token exchange (back-channel)          |
| `OIDC_OP_USER_ENDPOINT`             | `http://iyou-idp.identity.svc.cluster.local:8000/openid/userinfo/` | IdP userinfo/claims (back-channel)         |
| `OIDC_OP_JWKS_ENDPOINT`             | `http://iyou-idp.identity.svc.cluster.local:8000/openid/jwks/` | IdP JWKS key set (back-channel)                 |
| `OIDC_RP_CLIENT_ID`                 | `iyou-wun-satellite-client`    | Client ID registered with the IdP (ecosystem default) |
| `OIDC_RP_CLIENT_SECRET`             | *(empty — PKCE public client)* | Client secret (unused for PKCE public clients)  |
| `OIDC_RP_CALLBACK_URL`              | `http://127.0.0.1:8001/oidc/callback/` | OIDC callback URL                          |

Current iyou_idp development values (localhost):

```ini
OIDC_OP_AUTHORIZATION_ENDPOINT=http://127.0.0.1:8000/openid/authorize/
OIDC_OP_TOKEN_ENDPOINT=http://127.0.0.1:8000/openid/token/
OIDC_OP_USER_ENDPOINT=http://127.0.0.1:8000/openid/userinfo/
OIDC_OP_JWKS_ENDPOINT=http://127.0.0.1:8000/openid/jwks/
OIDC_RP_CALLBACK_URL=http://127.0.0.1:8001/oidc/callback/
OIDC_RP_CLIENT_ID=iyou-wun-satellite-client
OIDC_RP_CLIENT_SECRET=
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
User  ──GET /──>  WUN (redirects to /feed — no login wall)
  │
  ├──Click "Sign In"──>  IdP /openid/authorize/?next=/feed/
  │                           │
  │                     User authenticates at IdP
  │                           │
  │  <──Auth code redirect────┘
  │
  ├──WUN exchanges code at IdP /openid/token/
  │
  ├──WUN fetches claims at IdP /openid/userinfo/
  │
  └──User created/logged in locally ──> /feed (with authenticated nav)
```

The `mozilla-django-oidc` library handles the token exchange, userinfo retrieval, and local user creation automatically.

---

## Signature Bridge (Port 9001 — Tauri)

**Files:** `static/js/bridge_client.js`, `templates/dashboard.html`, `templates/feed.html`

The Tauri signing bridge at `ws://127.0.0.1:9001` is a WebSocket endpoint provided by iyou_home that signs Nostr events with the user's local key. The browser never has access to the private key.

The bridge logic is centralized in `static/js/bridge_client.js` — a singleton `TauriBridgeClient` instance shared across all templates. Feed and dashboard controllers import it via `<script src="{% static 'js/bridge_client.js' %}">`.

### Supported Message Types

| Type (client → bridge)   | Type (bridge → client)    | Purpose                                  |
|--------------------------|---------------------------|------------------------------------------|
| `get_profile`            | `profile_sync`            | Sovereign state handshake (see below)    |
| `sign_event`             | `signed_event`            | Sign a Nostr event (any kind)            |
| `sign`                   | `signed_message`          | Sign an arbitrary string                 |
| `sign_credential`        | `signed_credential`       | Sign a Verifiable Credential (VC)        |

The server can also **issue** VCs directly (see [Credential Issuance API](#credential-issuance-api)).

### Sovereign State Handshake

Upon WebSocket connection (`socket.onopen`), the client must immediately emit a profile sync request:

```json
{"type": "get_profile"}
```

The bridge responds with:

```json
{"type": "profile_sync", "profile": {"nostr_pubkey_hex": "<64-char-hex>", ...}}
```

The message loop dispatches this via the `profile_sync` handler, populating `window.activeProfile` with the live vault profile. This makes `nostr_pubkey_hex` available to `getEffectivePubkey()` before any signing request is issued.

### Identity Resolution Guard: `getEffectivePubkey()`

All event-emitting functions (`postToNostr`, `handleMediaSelected`, `castPollVote`, `createPoll`) resolve the event's `pubkey` field through this centralized async helper:

1. **Priority 1** — `window.activeProfile?.nostr_pubkey_hex` (from the Tauri bridge handshake)
2. **Priority 2** — `userPubkey` (legacy Django template variable)

If neither is a valid 64-character hex string (`/^[a-fA-F0-9]{64}$/`), the helper throws:

> `"Identity Synchronization Required: No valid secp256k1 pubkey found"`

An additional runtime guard in `sendEventToTauri()` logs `SENDING_EVENT_WITH_PUBKEY` with the key and length, and **aborts** the WebSocket send if the pubkey is not exactly 64 characters. This ensures no malformed payload ever reaches the Rust bridge.

### sign_event Flow

1. Client resolves a valid 64-char hex pubkey via `getEffectivePubkey()`
2. Browser sends `{"type": "sign_event", "event": {kind, content, pubkey, created_at, tags}}`
3. Tauri bridge signs with the local key, returns `{"type": "signed_event", "event": {id, sig, ...}}`
4. Browser copies `id` and `sig` into the pending event, then broadcasts to relays

### Connection Management

- `TauriBridgeClient` (singleton in `bridge_client.js`) manages a single WebSocket with a **mutex state machine**: states are `"IDLE"` → `"CONNECTING"` → `"OPEN"`.
- `bridgeClient.socket` is the singleton WebSocket reference; `readyState` is checked before any new connection is spawned.
- Immediately after `onopen`, the client sends `{"type": "get_profile"}` to populate `window.activeProfile`.
- A 5-second timeout abandons signing if the bridge is unreachable.
- The `isProcessing` flag prevents concurrent signing requests.

### Events Signed by the Bridge

| Kind | Description          | Source View      |
|------|----------------------|------------------|
| 1    | Short text note      | Feed             |
| 0    | Profile metadata     | Dashboard        |
| 1063 | Media (Blossom hash) | Feed             |
| 1112 | Vote envelope        | Feed (poll card) |
| 30023| Poll definition      | Feed (poll creation modal) |

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

**File:** `apps/core/views.py` — `FeedView`, `api_feed()`, `attach_reply_counts()`, `attach_reaction_counts()`, `relay_req()`

### How It Works Today

1. `FeedView.get_context_data()` fetches a multi-kind feed: Kind 1 (text notes), Kind 7 (reactions), Kind 1063 (file metadata / Blossom media), Kind 1111 (comments), Kind 30023 (poll definitions), Kind 1112 (vote envelopes).
2. **Batch NIP-10 Reply Ingestion (`attach_reply_counts`)**:
   - Queries connected relays with a single batch `filter_obj = {"kinds": [1, 1111], "#e": root_ids, "limit": 500}` across all discovered root notes.
   - Tallies replies per root note ID and sets `note["reply_count"] = max(existing_replies, counts.get(nid, 0))`.
   - Ensures fast, single-pass reply counter accuracy for both server-rendered feed/profile templates and `/api/feed` JSON streams without N+1 relay queries.
3. **Batch Reaction Counting (`attach_reaction_counts`)**:
   - Same pattern for likes: one batch Kind 7 query (`"kinds": [7], "#e": root_ids, "limit": 1000`), tallying non-`-` reactions per target note id and setting `note["like_count"]`.
   - Like buttons render the real count on server-rendered cards, `/api/feed` streams, and profile posts/replies.
4. **Inline URL Unfurling & Media Extraction (`extract_media_from_note()`)**:
   - Parses raw Kind 1 note content for embedded image, video, and audio URLs (`.png`, `.jpg`, `.mp4`, `.mp3`, Blossom URLs, etc.).
   - Extracts URLs into structured `media_attachments` dictionaries and strips URLs from the note's main text body to render clean text with embedded media cards.
5. **Hero-Centric Conversation Threading (`?thread=<event_id>`)**:
   - When `?thread=<id>` (or `?note=<id>`) is provided, `FeedView` activates focused thread mode.
   - Displays the target note in a prominent hero container, renders recursive ancestor chains (`ancestors`), and loads 1-level direct descendant replies (`thread_replies`) with full interaction bars.
6. **Deduplication Guard**:
   - Ingests raw events from all configured relays in `DEFAULT_RELAYS` and filters duplicate IDs in memory before tree processing in `apps/core/nip10.py`.
7. **Relay Auto-Failover (`relay_req` / `_connect_relay`)**:
   - Defensive error handling on open/message/close; a failing or unresponsive upstream relay is skipped and the next relay is tried autonomously until the first responsive one returns events.
   - `DEFAULT_RELAYS` order: `relay.iyou.me`, `nos.lol`, `relay.damus.io`, `relay.primal.net`, local `:9003`.
8. **Double-Broadcast**: When posting or replying, the signed event is sent simultaneously to:
   - `ws://127.0.0.1:9003` (local relay — triggers "Sovereign Copy Saved" toast)
   - `wss://relay.iyou.me` (project relay)
   - `wss://nos.lol`, `wss://relay.damus.io`, `wss://relay.primal.net` (global relays)
   - Broadcasting is **parallel** — one relay failure does not block others (see [Dynamic Relay Pooling](#dynamic-relay-pooling--nip-65)).

### 3-Column Discovery Feed Shell & Right Rail

Desktop feed renders a left-free **center stream column** (`max-w-2xl`) plus a sticky right **Discovery Rail** (`_feed_right_rail.html`, `w-72 xl:w-80`). The rail is hidden on mobile (`hidden lg:block`) and in thread mode (`feed_mode == 'thread'`). Modules:

1. **TRENDING TOPICS / 24H VELOCITY** — `trending_tags` context list; clicking a tag writes `#tag` into `#feed-search-input`, dispatches an `input` event (live Tier-1 filter), and fires a toast (`showToast(..., 'info')`).
2. **SOVEREIGN CREATORS** — top 4 public `UserLinkDeck` profiles (`suggested_creators`, verified first, current viewer excluded) with avatar, verified badge, `@handle` link, and a `+ Follow` button (`data-follow-target` / `data-follow-petname`) wired into `ContactManager`; falls back to a curated seat (Ben Justman, Dan Byers) when the DB is empty.
3. **ECOSYSTEM SPONSOR** — bordered placeholder unit for managed (`WUN_USER_LEVEL=1`) non-sovereign viewers.

The feed also renders a **Relay Mesh Health Widget** at the top of the right rail (`#relay-health-widget` — status dot, online/total pill, click-to-expand per-relay diagnostics drawer with latency + read/write/local scopes and a `/dashboard#settings` configure link), driven by `relay_pool.js`. It replaced the former `#relay-health-indicator` that sat above the composer.

### Media Support (Kind 1063)

Media files are uploaded to the local Blossom server at `http://127.0.0.1:9002/<sha256>` via HTTP PUT. A signed Kind 1063 event is then broadcast with the URL and MIME type. Events with `file_url` containing `127.0.0.1` are marked `is_sovereign` and display an amber badge.


### Gallery View

The **Media Gallery** (`/gallery`) renders Kind 1063 events with server-side MIME categorization into tabbed decks — **All**, **Images** (CSS masonry grid), **Videos** (16:9 feed cards), **Audio** (inline players with scrubber), and **Other**. Counts are shown on each tab. Clicking an image opens a fullscreen lightbox with metadata sidebar (file name, MIME, sovereign status, NIP-52 timestamps) and keyboard navigation (←/→/Esc). Audio auto-pauses when navigating between tabs. Gallery is public-read (no login required).

**Files:** `apps/core/views.py` (GalleryView + `categorize_media()`), `templates/gallery.html`, `static/js/gallery_player.js`

---

## Progressive Search Engine (Multi-Tier)

**Files:** `apps/core/views.py` — `api_search()`; `static/js/circle_feed_filter.js` — search escalation + dropdown renderer; `templates/_nav.html` — `#feed-search-input` + `#search-results-dropdown`

The nav tag filter doubles as a live search box with three escalating tiers:

```
[ User Types into #feed-search-input ]
        │
        ▼
Tier 1 (DOM, <2ms)        Tier 2 (DB, <20ms)         Tier 3 (Relay, async)
setSearchQuery() ─────►   /api/search/ fetch ─────►   #tag feed filter ?q=
Live client-side filter   250ms debounce,             ("Search Relays" via
of .feed-note-card          AbortController cancel     /feed?q=#tag)
by tag/text/pubkey/DID      ⇒ #search-results-dropdown
```

- **Tier 1 — DOM Filter (instant):** `checkSearchMatch()` evaluates `textContent`, pubkey/DID attributes, and parsed `#t` tags against the query; combined AND-wise with circle scope (`global`/`following`/`inner`/`mutual`, with self-author bypass). Updates `?q=` via `history.replaceState`.
- **Tier 2 — `GET /api/search/?q=...&limit=6` (250ms debounce):** Matches public `UserLinkDeck` profiles across `handle`, `display_name`, `nip05`, and `headline` via `icontains`, ordered verified-first then by handle. Returns profiles plus computed hashtag suggestions (exact `#term` + related popular tag prefixes). Rendered as a popover flyout grouped into **👤 Profiles** and **🏷️ Hashtags** sections, keyboard-aware (`Enter` → search feed, `Esc` → close), click-outside dismisses, and tag items re-trigger the live Tier-1 filter on feed pages.
- **Tier 3 — Relay/tag search:** On non-feed pages a `400ms` debounce redirects to `/feed?q=<encoded>`. On the feed, `Enter` filters in-place; hashtag results deep-link into `?q=` for the network-wide stream.

**Response schema:**
```json
{
  "success": true,
  "query": "mesh",
  "counts": {"profiles": 2, "tags": 3},
  "results": {
    "profiles": [{"handle": "meshmaster", "display_name": "Mesh Master",
                  "avatar_url": "", "headline": "...", "nip05": "", 
                  "is_verified": true, "url": "/@meshmaster"}],
    "tags": [{"tag": "mesh", "display_tag": "#mesh", "url": "/feed?q=%23mesh"}]
  }
}
```

Route lookup: `apps/core/urls.py` → `path('api/search/', views.api_search, name='api_search')`. See `docs/SPRINT_CHANGELOG.md` for the audit-to-implementation trace.

---

## Toast & Notification Engine

**Files:** `static/js/toast_manager.js`, `templates/includes/_toast_container.html`, `templates/base.html`

A global, typed toast stack replaces ad-hoc inline feedback calls:

- **Container:** `<div id="toast-container">` fixed bottom-right (`z-50`, `aria-live="polite"`), included once in `base.html`.
- **API:** `window.showToast(message, type, duration)` with `type ∈ success | error | info | mesh | heart | repost | copy | enclave` (boolean `true/false` still maps to error/success for backwards compat). Default auto-dismiss `3500ms`, entrance/exit transitions, per-toast dismiss button, HTML-escaped message.
- **Delegation:** `bridge_client.js` and `contact_manager.js` route their feedback through `window.showToast` (falling back to their own `#toast` element when toast_manager is absent), so feed/user actions ("Reaction published to mesh", "Follow list updated (Kind 3)", "Sovereign Copy Saved") render consistently.
- **Hosting:** `base.html` loads `toast_manager.js` (+ `relay_pool.js`) before `theme.js` for all views.

---

## Dynamic Relay Pooling & NIP-65

**Files:** `static/js/relay_pool.js` (client), `apps/core/views.py` — `fetch_user_nip65_relays()` (server), `templates/feed.html` (health indicator)

Relay infrastructure gained a **client-side pool** and **NIP-65 (Kind 10002) ingestion**:

- **Connection pool:** Bootstrap set (`relay.iyou.me`, `nos.lol`, `relay.damus.io`, `relay.primal.net`, local `:9003`) plus persisted custom relays and previously-ingested NIP-65 relays, each with read/write flags, local/primary markers, `status`, `latencyMs`, and `lastProbe`.
- **Health probing:** Every `45s` (and on boot) each relay is probed via a short-live WebSocket; the **Relay Mesh Health Indicator** shows `online/total`, pulsing green "Mesh Pool Active", amber "Mesh Degraded", or rose "Mesh Offline (Reconnecting...)".
- **Parallel fault-tolerant double-broadcast:** `relayPool.broadcast(signedEvent, relays)` opens one WebSocket per relay, treats any `["OK", ...]` as success, and resolves `{localSuccess, globalSuccess, successfulRelays, failedRelays}` without letting a primary failure block others. `bridge_client.broadcastToRelays` delegates to it when present.
- **NIP-65 ingestion:** `ingestNip65(event)` consumes Kind 10002 `["r", url, "read"|"write"]` tags into the pool and persists them (`wun_nip65_relays`). Server side, `fetch_user_nip65_relays(pubkey)` returns `{read, write, all}` from the most recent Kind 10002 event for bulk relay-aware queries.
- **Backwards fallback:** `bridge_client` uses `window.relayPool.getRelays()` when the pool exists, else its legacy `localStorage` `wun_relays` path.

---

## Poly Governance (Poll Definitions & Voting)

**Files:**
- `services/poly_client.py` — HTTP proxy client to the headless calculation engine
- `apps/core/views.py` — `api_cast_vote()`, `process_into_feed()` kind 30023/1112 handling
- `templates/feed.html` — inline poll card rendering with Gear ⚙️ dropdown

WUN integrates with the Poly governance system using two dedicated Nostr event kinds, and now includes a front-end panel for creating polls directly from the feed:

### Kind 30023 — Poll Definitions

Polls appear inline in the feed with:
- **Question text** from the event `content` field
- **Options** extracted from `option` tags (e.g., `["option", "Yes"]`)
- **Scope metadata** from `geohash` / `org` tags (used for Auditor Mode)
- **Expiry** from optional `expires` tag

### Kind 1112 — Vote Envelopes

Vote submissions follow a cryptographically signed flow:

1. **User selects** an option in the poll card and clicks "Cast Vote"
2. **JS constructs** a kind 1112 Nostr event with `vote_envelope` as JSON content:
   ```json
   {"poll_id": "<event_id>", "selection": "Yes", "timestamp": 1234567890}
   ```
3. **Tauri bridge signs** the event via `ws://127.0.0.1:9001` — browser never touches the private key
4. **JS packages** the signed result into the V2 Omni-Social proxy format:
   ```json
   {
     "voter_did": "did:key:z6Mk...",
     "signature": "<hex_sig_from_tauri>",
     "vote_envelope": {"poll_id": "...", "selection": "...", "timestamp": ...}
   }
   ```
5. **WUN proxies** to the headless calculation engine at `{POLY_ENGINE_URL}/api/v2/polls/{id}/cast/` with `X-Iyou-Wun-Proxy: true`
6. **Engine validates** the signature and returns `{"valid": true, "details": {...}}`
   - Duplicate votes (`"duplicate": true`) are treated as a success state

### Poll Creation (Kind 30023)

**Files:**
- `templates/poll_modal.html` — hidden Tailwind modal overlay
- `templates/feed.html` — "Add Poll" button, `createPoll()` JS, Tauri handshake, direct ingest

Authenticated users can create polls via the **"Add Poll"** button in the compose box. The flow:

1. **Form fields**: Title (text), Description (textarea), Scope (Public / Family Scoped / Local Regional), Minimum Fidelity (1=Social, 2=Institutional, 3=Hardware), dynamic option slots (2+ with "+ Add Option")
2. **Event construction** (`createPoll()`): Builds a Kind 30023 parameterized replaceable event with tags: `d` (UUID), `title`, `fidelity_min`, `option` (×N), `geohash`/`org` (based on scope), `expires` (+30 days)
3. **Signing**: Passes the unsigned event to the Tauri bridge via the existing `sendEventToTauri()` WebSocket pipeline
4. **Dual dispatch** (`handleTauriMessage()` pendingPoll branch):
   - **Direct ingest**: Fire-and-forget `POST http://127.0.0.1:8002/api/nostr/ingest/` to iyou_poly (eliminates relay ingestion lag)
   - **Relay broadcast**: `broadcastToRelays()` sends to all three Nostr relays for passive sync
5. **Cleanup**: Modal closes, state resets, poll card appears in feed on successful relay acknowledgment

Tag format:
```
["d", "<uuid_hex>"]           — parameterized replaceable identifier
["title", "<poll title>"]
["fidelity_min", "1|2|3"]
["option", "Option 1"]
["option", "Option 2"]
["geohash", "global"]         — if scope == "Local Regional"
["org", "iyou"]               — if scope == "Family Scoped"
["expires", "<+30d_unix>"]
```

### Auditor Mode

Anonymous users see polls in **read-only Auditor Mode**:
- Options are displayed with reduced opacity and disabled inputs
- A status message explains what credential scope is required to vote
- Future iterations will check Verifiable Credentials (geohash/org) against poll scope

### Gear Icon (⚙️) Verification Dropdown

Every poll card has a gear icon that toggles a provenance dropdown showing:
- **Voter DID**: The poll author's pubkey
- **Relay Source**: Which relay returned the poll event
- **Verification Status**: `⏳ Carrier Payload (Signature Verification Pending Bridge Hook)`
- **Scope Geohash/Org**: If present on the poll tags

---

## Credential Issuance API

**Files:**
- `apps/core/did_kit.py` — Ed25519 VC signing/verification (hex `proofValue`)
- `apps/core/models.py` — `IssuedCredential` tracking model
- `apps/core/views.py` — `IssueCredentialView`, `node_config`

WUN can issue W3C Verifiable Credentials to registered DIDs. The signing key is either provided explicitly via `NODE_PRIVATE_KEY_HEX` or derived from `WUN_SECRET_KEY` (dev fallback).

### Public Discovery — `GET /api/config/`

Unauthenticated endpoint that lets iyou_home discover the server's identity before requesting or verifying a credential:

```json
{
  "node_did": "did:key:z6Mk...",
  "node_public_key_hex": "4fde42c0f9...",
  "supported_credentials": ["voter_credential"]
}
```

### Issue a Credential — `POST /api/credentials/issue/`

**Auth:** OIDC-authenticated user with `is_staff=True`

**Payload:**
```json
{
  "voter_did": "did:key:z6Mk...",
  "credential_type": "voter_credential",
  "fidelity_score": 85
}
```

**Response** (201 Created):
```json
{
  "@context": ["https://www.w3.org/2018/credentials/v1"],
  "id": "urn:uuid:<uuid>",
  "type": ["VerifiableCredential", "voter_credential"],
  "issuer": "did:key:z6Mk...",
  "issuanceDate": "2026-05-27T12:00:00Z",
  "expirationDate": "2027-05-27T12:00:00Z",
  "credentialSubject": {
    "id": "did:key:z6Mk...",
    "fidelity_score": 85
  },
  "proof": {
    "type": "Ed25519Signature2020",
    "created": "2026-05-27T12:00:00Z",
    "proofPurpose": "assertionMethod",
    "verificationMethod": "did:key:z6Mk...#keys-1",
    "proofValue": "<hex_signature>"
  }
}
```

The `proofValue` is a hex-encoded Ed25519 signature (matching iyou_poly's verification convention). An `IssuedCredential` record is persisted for revocation tracking (subject_did, credential_type, vc_id, issued_at). The full VC payload is NOT stored — only the tracking metadata.

### Key Hierarchy

| Priority | Source | Use Case |
|----------|--------|----------|
| 1 (highest) | `NODE_PRIVATE_KEY_HEX` env var | Production: explicit 32-byte Ed25519 key as 64 hex chars |
| 2 (fallback) | SHA256(`WUN_SECRET_KEY`) | Local dev: deterministic, no extra config |

---

## Sovereign Profile Pages & Identity Resolution

**Routes:** `/profile/<npub>/`, `/u/<did>/`, `/@<handle>`

**Files:** `apps/core/views.py` — `ProfileView`, `fetch_profile_data()`, `apps/core/models.py` (`UserLinkDeck`, `UserLinkItem`)

### Hybrid Profile Resolution

`ProfileView` uses a hybrid resolution pipeline to guarantee profile data availability even when external relays have not yet indexed or returned a Kind 0 metadata event:
1. **Local DB Baseline**: Checks for a registered `UserLinkDeck` matching the user's DID or pubkey hex. Populates `display_name`, `headline`, `avatar_url`, `banner_url`, `nip05`, and `lud16` from local PostgreSQL/SQLite storage.
2. **Relay Kind 0 Overlay**: Queries connected relays for Kind 0 events and non-destructively overlays fresh metadata.
3. **Handle vs Display Name Separation**:
   - `@handle`: Canonical, immutable/claimed routing anchor (`/@handle`) managed via the Sovereign Link Deck system.
   - `Display Name`: Mutable, human-friendly presentation label rendered throughout feed cards and profile heroes.
4. **Sovereign Link Deck & Proof-of-Authority (POA)**:
   - Users can link external bios (GitHub, X, Mastodon, Bluesky) and verify them using one-time challenge tokens to claim canonical `@handle` identities (discriminator 0).
   - Serves structured links with custom icons and bio badges.
5. **Decoupled Profile Hero & Avatar Straddle**:
   - The hero header uses a flexbox **decoupled controls row** with an *independent* `-mt` pull on the circular avatar (straddling the banner), while the action cluster (Edit / Follow / Message / Petname / Tip) is absolutely positioned over the banner's top edge.
   - The identity/metadata block (display name, `@handle`, NIP-05 badge, VERIFIED badge, pubkey, bio) sits fully in the whitespace below the banner for clean vertical breathing room.
   - Avatars/banners open a fullscreen lightbox (`openImageModal`); avatar is `aspect-square` with `shrink-0` to prevent flex collapse on narrow viewports.

---

## Unified Dashboard Command Center

**Route:** `/dashboard`

**Files:** `templates/dashboard.html`, `templates/includes/_deck_manager.html`, `templates/includes/_relay_manager.html`, `static/js/bridge_client.js`, `static/js/link_deck_manager.js`

The dashboard is structured as a unified command center extending `base.html` within a single responsive container:
1. **Stateful URL-Hash Navigation**:
   - Manages four stateful tab panels (`#profile`, `#deck`, `#settings`, `#account`) synced to `window.location.hash` and `localStorage.getItem('wun_dashboard_active_tab')`.
   - Uses `history.replaceState` to maintain smooth tab transitions without jump scrolling.
2. **Reactive 2-Column Profile Editor (`#tab-profile`)**:
   - **Left Column**: Form inputs for Display Name, Avatar URL, Bio/Headline, Banner URL, NIP-05, and Lightning Address (LUD-16).
   - **Right Column (Live Preview)**: Reactive mini-hero card with immediate 2-way data binding on `updatePreview()` (swaps avatar image vs initial monogram placeholder, dynamically updates banner background, displays NIP-05/LUD-16 badges).
   - **Tauri Bridge Signing with Server Fallback**: Submitting signs a Kind 0 event via the local Tauri bridge (`ws://127.0.0.1:9001`) and broadcasts across relays; automatically falls back to `/api/profile/save/` if the bridge is offline.
3. **Link Deck Manager (`#tab-deck`)**:
   - Integrated handle claiming, POA bio verification modal, headline editor, and link item CRUD/reordering.
4. **Sovereign Switchboard (`#tab-settings`)**:
   - Active relay status indicators, dynamic relay addition/removal, and session sync.
5. **Account & Key Info (`#tab-account`)**:
   - Displays DID string, Nostr pubkey hex, npub, and mesh join date.

---

## XMPP Sovereign Chat

**Route:** `/chat`

**Files:** `templates/chat.html`

A minimal sovereign chat interface using [Converse.js](https://conversejs.org/) integrated via ES Module imports (`import converse from`) with embedded 3-tier layout preservation.
The XMPP endpoint is selected dynamically based on `WUN_USER_LEVEL`:

| Level | Mode | XMPP Domain | WebSocket Endpoint |
|---|---|---|---|
| `1` | Managed (cluster) | `iyou.me` | `wss://xmpp.iyou.me:5222/xmpp-websocket` |
| `2` | Sovereign (local enclave) | `127.0.0.1` | `wss://home.iyou.me:5222/xmpp-websocket` |

- **ES Module Loading**: Loaded via `<script type="module">` importing the default `converse` export from the CDN (10.1.7); initialization is a promise chain with a `.catch()` that force-dismisses the loading overlay.
- **Lifecycle Plugin (`iyou-lifecycle`)**: Registers `connected` / `statusInitialized` listeners via `this._converse.api.listen.on(...)` (whitelisted plugin), replacing the fragile `converse.listen('connected', ...)` binding.
- **Peer Deep-Link / Auto-Join**: `?peer=<npub-or-jid>` builds `auto_join_private_chats` (suffixing `@iyou.me` when bare), so profile "Message" buttons open a direct chat immediately.
- **JID format**: `{nostr_pubkey_hex}@{domain}` (hex pubkey derived from DID, RFC 7622 nodeprep compliant).
- **Password**: `{nostr_hex_pubkey}` (derived from the DID).
- **Fullscreen Embedded Viewport**: Converse.js fits seamlessly into the responsive app shell below the unified navigation bar (`root: #conversejs`, `singleton: false`).
- **Auto-login**: Connects on page load using derived credentials.
- **Discovery disabled**: `discover_connection_methods: false` eliminates host-meta loops (BOSH removed; WebSocket-only).

All messages remain local to the :5222 XMPP server and are NEVER stored in the WUN database.


---

## Mesh Awareness

### Port Map

| Service          | Port | Protocol | Purpose                         |
|------------------|------|----------|---------------------------------|
| iyou_idp         | 8000 | HTTP     | OpenID Provider                     |
| iyou_poly        | 8002 | HTTP     | Governance engine (poll intake)     |
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

## v1.0 Release Polish Milestones

The following release-readiness milestones (tracked in `TODO.md` as **Phase 16**) are outstanding work items that ship ahead of the v1.0 tag. Each is documented as a checklist item with planned implementation files.

### 16.1 Dynamic Open Graph & Social Unfurling Engine

**Files (planned):** `apps/core/views.py` (per-route `og:*` / `twitter:*` context), `templates/base.html` + view templates (`extra_head` blocks), `static/img/iyou_symbol.png`

- Inject context-aware `<meta property="og:*">` and `<meta name="twitter:*">` tags for `/feed?thread=<id>`, `/@<handle>`, and `/gallery` so external link shares (Facebook, X, Discord, iMessage) render branded preview cards with author avatar, excerpt, and media thumbnails.
- **Fallback image:** use `static/img/iyou_symbol.png` as the branded `og:image` for root routes. Source asset currently lives at `/iyou_symbol.png` (repo root) and must be moved under `static/img/` (plus `collectstatic` on the production build).
- Meta tags should be authored server-side per route: hero thread notes pull the focused note's author avatar + excerpt; `/@<handle>` pulls the deck card avatar + headline; `/gallery` pulls the front-most media thumbnail.

### 16.2 NIP-10 Full-Lineage Ancestor Ladder

**Files (planned):** `apps/core/views.py` — `fetch_thread()`; `apps/core/nip10.py`; `templates/includes/_thread_post.html`; `static/js/feed_interactions.js`

- Refactor `fetch_thread()` in `views.py` and the tree helpers in `nip10.py` to resolve complete root-to-leaf ancestor chains (`root` → `intermediate ancestors` → `focused note` → `direct replies`) instead of clipping at single-hop parents.
- Add vertical connective thread guides in `_thread_post.html` and `feed_interactions.js` so interacting participants see the full lineage visual.

### 16.3 Custom SVG Reaction Icons & Micro-Animations

**Files (planned):** `templates/includes/_thread_post.html`, `templates/gallery.html`, `static/js/feed_interactions.js`

- Replace generic system emojis (`❤️`, `🔁`, `💬`, `⚡`, `📤`) with themed Lucide/Heroicon SVGs.
- Add interactive active states: pink fill on like, rotating transition on repost, amber pulse on zap.

### 16.4 Web Share API & Mobile Action Sheet

**Files (planned):** `static/js/feed_interactions.js` (Share handler)

- Wire the Share button to invoke native `navigator.share()` on supported mobile browsers (`canShare`/`share` feature detection), falling back to clipboard copying on desktop (existing `copyNotePermalink`).

### 16.5 Cyber-Grit Branded Error Views

**Files (planned):** `templates/404.html`, `templates/500.html`

- Author custom `404` and `500` templates extending `base.html` with theme reactivity (light/dark/stealth), return-to-mesh buttons (back to `/feed` + reload), and human-readable error diagnostic codes.

---

## Project Layout

```
.
├── manage.py                       # Django management entry point
├── pyproject.toml                   # Project metadata & dependencies
├── package.json                     # Tailwind CSS build scripts
├── tailwind.config.js               # Tailwind content paths + theme
├── postcss.config.js                # PostCSS plugin config (tailwindcss + autoprefixer)
├── Dockerfile                       # Multi-stage production build (uv + gunicorn)
├── docker-entrypoint.sh             # Container init (migrate → gunicorn on :8000)
├── .dockerignore                    # Excludes garbage from Docker context
├── .env                             # Environment variables (git-ignored)
├── .env.example                     # Template for .env (safe to commit)
├── services/
│   ├── __init__.py
│   └── poly_client.py               # PolyClient — HTTP proxy to governance engine
├── static/
│   ├── css/
│   │   ├── input.css                # Tailwind source (directives only)
│   │   └── output.css               # Compiled Tailwind (gitignored, built via npm)
│   ├── js/
│       ├── bridge_client.js         # TauriBridgeClient — WebSocket mutex, signing, fallback modal
│       ├── feed_interactions.js     # Feed controller — posting, NIP-10 threading, polls, toasts
│       ├── gallery_player.js        # Gallery — tab switching, lightbox, media playback
│       ├── theme.js                 # Zero-flash theme engine (wun_theme cookie + localStorage)
│       ├── circle_feed_filter.js    # Circle scopes, tag/text/DOM filtering, progressive search flyout
│       ├── contact_manager.js       # NIP-02 Kind 3 contacts, follow buttons, mutual detection
│       ├── trust_lens.js            # Project Zero trust pills (author-badge-slot)
│       ├── link_deck_manager.js     # Link Deck CRUD, handle claiming, POA verification
│       ├── toast_manager.js         # Global typed toast engine (window.showToast)
│       ├── relay_pool.js            # NIP-65 relay pool, health probing, parallel broadcast
│       └── sw.js                    # PWA service worker (offline cache)
│   ├── img/                         # App icons, logos (logo, logo_square, icon-192/512)
│   └── manifest.json                # PWA web manifest
├── config/
│   ├── settings.py                  # Django settings (OIDC, auth, apps, CSRF, POLY_ENGINE_URL)
│   ├── urls.py                      # Root URL configuration
│   ├── wsgi.py                      # WSGI entrypoint
│   └── asgi.py                      # ASGI entrypoint
├── apps/core/
│   ├── __init__.py
│   ├── apps.py                      # Django app config
│   ├── did_kit.py                   # Ed25519 VC signing/verification (hex proofValue)
│   ├── nip10.py                     # NIP-10 threading — parse_tags(), build_thread_tree()
│   ├── views.py                     # FeedView, GalleryView, ProfileView, ChatView,
│   │                                # home(), dashboard(), Nostr helpers, api_cast_vote(),
│   │                                # IssueCredentialView, node_config(), categorize_media()
│   ├── urls.py                      # App-level URL routing
│   ├── auth.py                      # MyOIDCAuthenticationBackend
│   ├── auth_pkce.py                 # PKCE views + backend with code_verifier relay
│   ├── models.py                    # IssuedCredential — tracks VC issuance events
│   ├── admin.py                     # IssuedCredential admin registration
│   ├── conftest.py                  # pytest fixtures (OIDC claims, users, Nostr events)
│   └── tests/
│       ├── __init__.py
│       ├── helpers.py               # Reusable test utilities (create_oidc_user, make_event, etc.)
│       ├── test_auth.py             # 20 tests: auth backend, password rejection, OIDC + logout
│       ├── test_views.py            # 77 tests: home, dashboard, chat, gallery, profile, search API, trust lens
│       ├── test_feed.py             # 52 tests: process_into_feed threading + reaction counts + relay failover
│       ├── test_gallery.py          # 32 tests: MIME categorization, circle filtering, card attribution
│       ├── test_issuance.py         # 20 tests: did_kit sign/verify + credential API (real Ed25519)
│       ├── test_contacts.py         # 10 tests: NIP-02 contact profile/deck derivation, key derivation
│       └── test_deck.py             # 85 tests: handle claims, routing, deck APIs, POA verification
├── templates/
│   ├── _nav.html                    # Shared navigation (DRY — included by all views)
│   ├── _ecosystem_bar.html          # Sovereign mesh top bar (generated — do not edit)
│   ├── includes/
│   │   ├── _thread_post.html        # Shared threaded post renderer partial (NIP-10)
│   │   ├── _post_composer.html      # Top-of-feed composer (text/poll/media controls)
│   │   ├── _feed_right_rail.html    # Discovery rail — trending tags, sovereign creators, sponsor
│   │   ├── _toast_container.html    # Floating toast stack container (#toast-container)
│   │   ├── _deck_manager.html       # Dashboard Link Deck manager tab
│   │   ├── _relay_manager.html      # Dashboard relay manager tab
│   │   ├── _ecosystem_bar.html      # Sovereign mesh top bar (generated — do not edit)
│   │   └── _standard_header.html    # Cortex/ecosystem standard header (generated — do not edit)
│   ├── dashboard.html               # Dashboard + Edit Profile (Kind 0 broadcast, 6 NIP-01 fields)
│   ├── feed.html                    # Omni-Social feed with threaded layout + poll creation
│   ├── poll_modal.html              # Poll creation modal (Tailwind overlay)
│   ├── gallery.html                 # Media gallery — tabbed decks + masonry + lightbox
│   ├── profile.html                 # Sovereign profile (banner hero, NIP-05 badge, lud16 tip)
│   └── chat.html                    # XMPP chat (Converse.js)
```

### URL Map

| Path                  | View           | Auth Required | Notes                                |
| --------------------- | -------------- | ------------- | ------------------------------------ |
| `/`                   | `home`         | No            | Redirects to /feed                   |
| `/dashboard`          | `dashboard`    | Yes           | DID display + Edit Profile (Kind 0)  |
| `/feed`               | `FeedView`     | No            | Public unified Nostr feed + polls    |
| `/gallery`            | `GalleryView`  | No            | Media tabbed decks + masonry + lightbox  |
| `/profile/<npub>/`    | `ProfileView`  | No            | Sovereign profile (Kind 0, 1, 1063)  |
| `/@<handle>`          | `LinkDeckView` | No            | Sovereign link deck card page        |
| `/u/<did_key>/`       | `LinkDeckView` | No            | Deck by DID (301 → canonical handle) |
| `/chat`               | `ChatView`     | Yes           | XMPP sovereign chat (+ `?peer=` auto-join) |
| `/admin/`             | Django admin   | —             |                                      |
| `/oidc/`              | OIDC flow      | —             | Provided by mozilla-django-oidc      |
| `/api/feed`           | `api_feed`     | Yes           | JSON feed endpoint (Load More)       |
| `/api/search/`        | `api_search`   | No            | JSON profile + hashtag search (flyout) |
| `/api/relays`         | `api_relays`   | Yes           | GET/POST relay config                |
| `/api/profile/save/`  | `api_save_profile` | Yes        | Kind 0 profile metadata persistence  |
| `/api/vote`           | `api_cast_vote`| Yes           | POST signed vote envelopes to Poly   |
| `/api/media/upload/`  | `MediaUploadProxyView` | Yes    | Blossom upload proxy                 |
| `/api/deck/*`         | deck APIs      | Yes           | Deck CRUD, reorder, POA challenge/confirm |
| `/api/credentials/issue/` | `IssueCredentialView` | Staff (+ OIDC) | POST issue a signed Verifiable Credential |
| `/api/config/`        | `node_config`  | No            | Public node identity discovery       |

---

## Running Tests

```bash
uv run python manage.py test apps.core
uv run ruff check .
```

Tests cover (**336 total across 7 test modules**; ruff clean):

### `test_auth.py` (20 tests)
- `MyOIDCAuthenticationBackendTest` — DID-based user creation (5)
- `SovereignOnboardingTest` — filter_users_by_claims, get_username, verify_claims (5)
- `PasswordRejectionTest` — OIDC users have unusable passwords, ModelBackend rejects them (4)
- `OIDCBackendEnforcementTest` — OIDC backend registered, LOGIN_URL points to IdP (3)
- `OIDCLogoutViewTest` — PKCE logout accepts GET + POST and redirects to IdP (3)

### `test_views.py` (104 tests)
- `HomeViewTest` — root redirect to /feed (1)
- `DashboardViewTest` — anonymous redirect to IdP, authenticated DID display, logout link, stream language filter selector, feed hygiene controls verification (7)
- `JwksConnectivityTest` — JWKS discovery/connectivity (1)
- `ChatViewTest` — anonymous redirect, Converse init + lifecycle plugin, `?peer=` auto-join, nav links (13)
- `GalleryViewTest` — media heading, nav links, tab context (4 — public-read)
- `ProfileViewTest` — invalid npub error, valid render, hybrid local DB baseline fallback (4)
- `DashboardProfileTest` — profile section, publish, handle vs display name persistence (7)
- `MediaUploadProxyViewTest` — Blossom proxy behavior incl. dynamic endpoint resolution (6)
- `FeedViewTrustLensContractTest` — Level0/0.5/1 trust pill contract (6)
- `FeedViewTwoTierToolbarTest` — two-tier nav toolbar, circle scope badge, live tag search (5)
- `FeedModernizationAndExternalAttributionTest` — inline media, hero threading, action bar, cursor pagination, batch reply + like counts, kebab actions, Open Graph metadata, NIP-56 report actions, separate subheader links & jump to root conversation, scoped trending switcher & NSFW shield toggle, [ ⚡ iyou ] circle filter pill & LinkDeck author scoping, data-lang card decoration, on-demand note translation endpoint (`/api/translate/`) & inline UI trigger button (19)
- `SearchAPITests` — `/api/search/` JSON schema, handle/name/hashtag filtering, nav dropdown DOM, toast container (4)
- `CyberGritErrorViewTests` — branded cyber-grit 404 & 500 error views, route disconnected / internal transmission fault copy, socket retry (18)
- `NotificationViewTests` — authenticated bell toggle, slide-out drawer markup, `/notifications` ledger tabs (Mentions/Reactions/Zaps) (4)
- `NIP05EndpointTests` — `/.well-known/nostr.json` verification endpoint, name querying & JSON schema (3)
- `ProfileComposerTests` — profile view quick note composer rendering and submission (2)

### `test_feed.py` (65 tests)
- `ProcessIntoFeedTest` — kind routing, reaction grouping/dedup, sovereignty flag, profile enrichment, sort/truncation, malformed events, poll extraction + scope tags + vote grouping, multi-relay dedup, NIP-10 tree builder, positional/unmarked tag parsing, batch reply counts, **batch Kind-7 reaction counts** (50)
- `RelayPoolAndFailoverTests` — `relay_req` failover on primary down, all-relays-down → `{}`, NIP-65 (Kind 10002) relay parsing, empty-pubkey guard, unified-feed relay-outage grace, federated ancestor fallback relays (6)
- `FeedSanitizerTests` — XSS sanitization, HTML stripping, URI scheme filtering, auto-linkification, roster telemetry & hex concatenation noise pruning, NIP-01/heuristic language detection (5)
- `AttachSocialCountsTests` — social reaction and reply count aggregation across relay responses, scoped trending tags stream calculation (3)
- `FeedRelayHealthWidgetLayoutTest` — relay health indicator widget layout and dynamic state rendering (2)

### `test_gallery.py` (32 tests)
- `CategorizeMediaTest` — MIME grouping, NIP-94 extraction, duration/blurhash/blossom_hash, mixed media, wildcards (21)
- `GalleryViewContextTest` — 200 status, context keys, public access, type filter (4)
- `GalleryViewAuthTest` — anonymous 200 (1)
- `GalleryCircleFilteringAndTagSearchTest` — circle scope + tag search on gallery (2)
- `GalleryCardModernizationAndAttributionTest` — author/nip05/trust-lens rendering (4)

### `test_issuance.py` (20 tests)
- `DIDKitUnitTest` — key loading, VC structure, sign/verify round-trip, wrong-key rejection, tamper detection (6)
- `IssueCredentialAPITest` — anonymous 302, non-staff 403, staff issue, cryptographic validity, 405, field validation, fidelity bounds, DB persistence (14)

### `test_contacts.py` (10 tests)
- `ContactManagerProfileTests` — contact profile resolution (3)
- `ContactManagerDeckTests` — deck enrichment from contact Kind 3 (3)
- `KeyDerivationTests` — npub → pubkey-hex derivation guards (4)

### `test_deck.py` (85 tests)
- `DeckHandleClaimTests` — availability, reserved handles, discriminator assignment (11)
- `DeckRoutingTests` — `@handle[n]`, `/u/<did>` redirects, fallbacks (11)
- `DeckItemAPITests` — Link item CRUD, active toggle, ordering (13)
- `DeckReorderTests` — reorder persistence (5)
- `DashboardDeckTabTests` + `ProfileDeckChipsTests` — dashboard/deck/profile integration (4)
- `BioScraperSSRFTests` + `BioScraperFetchTests` — SSRF guards, allowlist, 512KB cap, scrape flow (21)
- `VerifyChallengeAPITests` + `VerifyConfirmSwapTests` — POA challenge/confirm + discriminator swap (16)
- `VerifiedBadgeRenderingTests` — verified badges on deck card/profile hero (4)


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

### Ed25519 signature validation failure on poly ingest

Poll creation (Kind 30023) gets a 400 from `POST /api/nostr/ingest/` with `InvalidSignature` even though frontend hex conversion is correct.

**Symptoms:**
- Browser logs show valid 64-char `id` and 128-char `sig` hex strings in the POST body
- iyou_poly logs `[ED25519_DIAG]` with correct-length hex for event_id, pubkey, and sig
- Ed25519 `verify()` still raises `InvalidSignature`

**Current hypothesis (WIP):** The key material or signing scheme differs between iyou_home (Ed25519 vault key) and what iyou_poly expects. iyou_home signs with its vault Ed25519 key, but iyou_poly may be verifying against the user's Nostr pubkey (which is a secp256k1 key derived from the OIDC DID). These are different key types on different curves. The fix likely lives in:
- `iyou_home`: whether it's signing with the correct user key vs its own vault key
- `iyou_poly`: whether verification should use Ed25519 at all, or switch to secp256k1/NIP-26 delegation

---

## Known Issues

- `.env` was previously committed to git — now removed from tracking and gitignored. **DO NOT re-commit it.**
- Profile pages (`/profile/<npub>/`) are public but the feed/gallery links to them are only visible to authenticated users.
- **Ed25519 signature mismatch** between iyou_home signing and iyou_poly verification — see Troubleshooting section above.
- **NIP-05 `/.well-known/nostr.json` endpoint is NOT yet implemented.** Profile metadata carries a `nip05` field (`UserLinkDeck` + Kind 0 overlay) and renders a badge, but WUN does not yet serve a `/.well-known/nostr.json` identity file (e.g. `{"names": {"handle": "<pubkey-hex>"}, "relays": {...}}`). Tracked as outstanding work — see `docs/SPRINT_CHANGELOG.md`.
- `docs/archive/` holds superseded/historical reports (design-era specs and completed-phase audits) and is gitignored.
