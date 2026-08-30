# iyou_wun (WUN)

Django 5.2 OIDC Relying Party (Satellite) — authenticates users via the **iyou_idp** identity provider using their Decentralized Identifier (DID), with PKCE and **no passwords**. Sovereign social stack: multi-tier **Omni-Social Nostr Feed** (Kind 1/7/1063/1111/30023/1112), **progressive search**, a **3-column discovery feed shell** with right rail, a **toast notification engine**, media gallery, sovereign profile pages, and XMPP chat.

---

## Quick Start

```bash
cp .env.example .env          # then edit with WUN_SECRET_KEY (OIDC client defaults work for local dev)
uv sync
uv run python manage.py migrate
uv run python manage.py runserver 8001
```

Requires running **iyou_idp** (OIDC provider) and **iyou_home** (Tauri signing bridge :9001, Blossom :9002, local relay :9003, XMPP :5222).

---

## Feature Highlights

- **Progressive Multi-Tier Search** — The nav tag filter doubles as a live search box:
  - **Tier 1 (DOM):** Instant client-side filtering of loaded feed/gallery cards by tag, text, pubkey/DID (`circle_feed_filter.js`).
  - **Tier 2 (DB):** `/api/search/` returns matching sovereign profiles (`UserLinkDeck`) and hashtag suggestions with a 250ms debounce, rendered in the `#search-results-dropdown` flyout.
  - **Tier 3 (Relays):** `#t` tag searches still push through the feed's `?q=` filter for network-wide discovery.
- **Responsive 3-Column Feed Shell** — Desktop feed renders center stream + right **Discovery Rail** (`_feed_right_rail.html`) topped with a Mesh Relay **health widget** (click-to-expand per-relay diagnostics), TRENDING TOPICS (24H velocity tags), SOVEREIGN CREATORS (+ Follow), and an ecosystem sponsor unit. Collapses gracefully on mobile; hidden in thread mode.
- **Toast & Notification Engine** — Global `window.showToast()` (`toast_manager.js`) with typed feedback (success/error/info/mesh/heart/repost/copy/enclave) rendered in the fixed `#toast-container` partial and wired through all feed/contact controllers and the Tauri bridge.
- **Dynamic Relay Pooling & NIP-65** — `relay_pool.js` probes relay health (latency/status), persists custom + NIP-65 relay lists in localStorage, parallel double-broadcasts with per-relay fault tolerance, and drives the feed's live "Mesh Pool Active" health indicator. Server-side `relay_req()` gained autonomous failover and `fetch_user_nip65_relays()` (Kind 10002) parsing.
- **Batch Reaction (Kind 7) Counting** — `attach_reaction_counts()` tallies likes across the whole feed in a single relay query; like buttons render real counts instead of a static label.
- **Decoupled Profile Hero & Avatar Straddle** — Avatar independently overlaps the banner (`-mt` pull) while the action cluster (Edit / Follow / Message / Tip) floats over the banner's top edge; identity block sits cleanly in whitespace below.

Full architecture detail: **[docs/WUN_DEVELOPER_GUIDE.md](docs/WUN_DEVELOPER_GUIDE.md)**. Latest sprint deltas: **[docs/SPRINT_CHANGELOG.md](docs/SPRINT_CHANGELOG.md)**.

---

## Routes

| Path                      | View                | Auth   | Description                                      |
| ------------------------- | ------------------- | ------ | ------------------------------------------------ |
| `/`                       | `home`              | No     | Redirects to `/feed`                             |
| `/feed`                   | `FeedView`          | No     | Unified Nostr feed, thread view, discovery rail  |
| `/feed?q=`                | (client-side)       | No     | Tier-1 tag/text/circle filter                    |
| `/gallery`                | `GalleryView`       | No     | Media grid with MIME tabs + lightbox             |
| `/profile/<npub>/`        | `ProfileView`       | No     | Sovereign profile (Kind 0/1/1063, deck, media)   |
| `/@<handle>`              | `LinkDeckView`      | No     | Sovereign link deck card page                    |
| `/u/<did>/`               | `LinkDeckView`      | No     | Deck by DID (301 → handle)                       |
| `/dashboard`              | `dashboard`         | Yes    | Unified command center (profile/deck/settings/account) |
| `/chat`                   | `ChatView`          | Yes    | XMPP sovereign chat (Converse.js)                |
| `/oidc/`                  | OIDC flow           | —      | PKCE login/logout (mozilla-django-oidc + PKCE)   |
| `/api/feed`               | `api_feed`          | Yes    | JSON feed stream (pagination, like counts)       |
| `/api/search/`            | `api_search`        | No     | Tier-2 profile + hashtag search (JSON)           |
| `/api/relays`             | `api_relays`        | Yes    | GET/POST relay config                            |
| `/api/profile/save/`      | `api_save_profile`  | Yes    | Kind 0 profile metadata persistence              |
| `/api/vote`               | `api_cast_vote`     | Yes    | POST signed vote envelopes to Poly               |
| `/api/media/upload/`      | `MediaUploadProxyView` | Yes | Blossom upload proxy with dynamic endpoint resolve |
| `/api/deck/*`             | deck APIs          | Yes    | Link deck CRUD, reorder, POA challenge/confirm   |
| `/api/credentials/issue/` | `IssueCredentialView` | Staff | Issue a signed W3C Verifiable Credential         |
| `/api/config/`            | `node_config`       | No     | Public node identity discovery                   |
| `/admin/`                 | Django admin        | —      |                                                   |

---

## OIDC Environment Variables (127.0.0.1)

```ini
OIDC_OP_AUTHORIZATION_ENDPOINT=http://127.0.0.1:8000/openid/authorize/
OIDC_OP_TOKEN_ENDPOINT=http://127.0.0.1:8000/openid/token/
OIDC_OP_USER_ENDPOINT=http://127.0.0.1:8000/openid/userinfo/
OIDC_OP_JWKS_ENDPOINT=http://127.0.0.1:8000/openid/jwks/
OIDC_RP_CLIENT_ID=iyou-wun-satellite-client
OIDC_RP_CLIENT_SECRET=            # PKCE public client — empty
```

**Always use `127.0.0.1`** — never `localhost`. This prevents IPv6 ambiguity, OIDC issuer mismatches, and browser cookie domain issues across macOS, Linux, and Windows.

---

## Documentation Map

| Document | Location | Purpose |
|----------|----------|---------|
| Developer Guide | `docs/WUN_DEVELOPER_GUIDE.md` | Full setup, env vars, architecture, troubleshooting |
| Sprint Changelog | `docs/SPRINT_CHANGELOG.md` | Latest sprint review — new routes, partials, tests |
| Design Doc | `docs/DESIGN_DOC.md` | Early Sovereign Media Stack design spec |
| Project TODO | `TODO.md` | Current task tracking (synced from omni_social hub) |
| Agent Brief | `AGENT.md` | Canonical AI-agent invariants + repo overview |
| Auth Standard | `docs/ecosystem_shared/OMNI_SOCIAL_AUTH_STANDARDIZATION.md` | Platform-wide OIDC/PKCE rules |
| Auth Flow Spec | `docs/ecosystem_shared/AUTH_FLOW_SPECIFICATION.md` | Request/response flow diagrams |
| PKCE Reference | `docs/ecosystem_shared/auth_pkce.py` | Canonical reference implementation |
| Satellite Coordination | `docs/ecosystem_shared/satellite-coordination.md` | Multi-satellite sync patterns |

Archive (historical, gitignored): `docs/archive/` — `MESHING_PROTOCOL.md`, `STRATEGIC_ROADMAP.md`, `GLOBAL_LOCAL_NOSTR.md`, `SEARCH_AUDIT_REPORT.md`, `WUN_ARCHITECTURAL_AUDIT_REPORT.md`.

---

## Testing

```bash
uv run python manage.py test apps.core   # 296 tests / 7 modules
uv run ruff check .
```

296 unit tests across 7 modules — see [docs/WUN_DEVELOPER_GUIDE.md](docs/WUN_DEVELOPER_GUIDE.md#running-tests) for the breakdown.