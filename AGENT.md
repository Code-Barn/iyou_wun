## CRITICAL: OpenID Connect & Ingress Invariants

All authentication and user provisioning logic in this repository MUST conform strictly to the canonical ecosystem specifications located at:
- `docs/ecosystem_shared/OMNI_SOCIAL_AUTH_STANDARDIZATION.md`
- `docs/ecosystem_shared/AUTH_FLOW_SPECIFICATION.md`

Reference Implementation to follow: `docs/ecosystem_shared/auth_pkce.py`

Do NOT implement cleartext client secrets, do NOT use email addresses as database lookup anchors, and ensure all post-auth logic implements the `evaluate_sovereign_admin_posture` routine.

---

## Repository Overview

**iyou_wun** (WUN) is a Django 5.2 OIDC Relying Party satellite that authenticates users via the **iyou_idp** identity provider using Decentralized Identifiers (DID). Passwords are deprecated — OIDC/DID is the sole entry point.

**Core features:** Omni-Social Nostr Feed (Kind 1/7/1063/1111/30023/1112) with NIP-10 hero threading and inline media unfurling, batch reply **and reaction** counting, progressive multi-tier search (`/api/search/` + `#search-results-dropdown`), responsive 3-column discovery feed shell with right rail, global toast notification engine, dynamic NIP-65 relay pooling with autonomous failover, Media Gallery (tabbed by MIME type), Sovereign Link Deck with Proof-of-Authority verification, Unified 2-column reactive Dashboard, Sovereign Profile pages with hybrid resolution, XMPP Chat (Converse.js ES module), Poly Governance Polls, Verifiable Credential issuance.

---

## Quick Start

```bash
cp .env.example .env          # fill in WUN_SECRET_KEY (OIDC client defaults work for local dev)
uv sync
uv run python manage.py migrate
uv run python manage.py runserver 8001
```

Requires: running `iyou_idp` instance + `iyou_home` (Tauri bridge :9001, Blossom :9002, local relay :9003).

---

## Documentation Map

| Document | Location | Purpose |
|----------|----------|---------|
| Developer Guide | `docs/WUN_DEVELOPER_GUIDE.md` | Full setup, env vars, architecture, troubleshooting |
| Sprint Changelog | `docs/SPRINT_CHANGELOG.md` | Latest sprint review — new routes, partials, test suites |
| Design Doc | `docs/DESIGN_DOC.md` | Sovereign Media Stack architecture (early spec) |
| Project TODO | `TODO.md` | Current task tracking (synced from omni_social hub) |
| Auth Standard | `docs/ecosystem_shared/OMNI_SOCIAL_AUTH_STANDARDIZATION.md` | Platform-wide OIDC/PKCE rules |
| Auth Flow Spec | `docs/ecosystem_shared/AUTH_FLOW_SPECIFICATION.md` | Request/response flow diagrams |
| PKCE Reference | `docs/ecosystem_shared/auth_pkce.py` | Canonical reference implementation |
| Satellite Coordination | `docs/ecosystem_shared/satellite-coordination.md` | Multi-satellite sync patterns |

### Archive (historical reference — gitignored)

| Document | Location | Notes |
|----------|----------|-------|
| Meshing Protocol | `docs/archive/MESHING_PROTOCOL.md` | Early integration plan template |
| Strategic Roadmap | `docs/archive/STRATEGIC_ROADMAP.md` | Phase 2 roadmap (largely completed) |
| Global-Local Nostr | `docs/archive/GLOBAL_LOCAL_NOSTR.md` | Nostr relay architecture reference |
| Search Audit Report | `docs/archive/SEARCH_AUDIT_REPORT.md` | Pre-implementation search diagnostic (superseded by `docs/SPRINT_CHANGELOG.md`) |
| Architectural Audit | `docs/archive/WUN_ARCHITECTURAL_AUDIT_REPORT.md` | Completed-phase audit report (historical) |

---

## Architecture at a Glance

```
User Browser → Traefik (HTTPS) → WUN (Django :8001)
                                    ↓ OIDC PKCE
                                iyou_idp (IDP)
                                    ↓ tokens
                                WUN backend
                                    ↓ Nostr
                                Relay mesh (nos.lol, relay.iyou.me, :9003)
```

### Key Files

| File | Purpose |
|------|---------|
| `config/settings.py` | All OIDC, session, auth, and infrastructure config |
| `config/urls.py` | Root URL routing (OIDC views wired here) |
| `apps/core/auth.py` | `MyOIDCAuthenticationBackend` — DID user creation, admin elevation |
| `apps/core/auth_pkce.py` | PKCE views + backend with code_verifier relay |
| `apps/core/views.py` | Feed, Dashboard, Gallery, Profile, Chat, Link Deck, API endpoints |
| `apps/core/nip10.py` | NIP-10 threading parser — tree builder for reply threading & deduplication |
| `apps/core/models.py` | `UserLinkDeck`, `UserLinkItem`, `IssuedCredential` — Link deck and VC models |
| `apps/core/did_kit.py` | Ed25519 VC signing/verification |
| `static/js/bridge_client.js` | Tauri WebSocket bridge — mutex, signing, stateful tab router, fallback modal |
| `static/js/link_deck_manager.js` | Link Deck CRUD, handle claiming, proof-of-authority bio challenges |
| `static/js/feed_interactions.js` | Feed controller — posting, replies, hero threading, polls, inline media, toasts |
| `static/js/gallery_player.js` | Gallery controller — tab switching, lightbox, media playback |
| `static/js/circle_feed_filter.js` | Circle scopes + tag/text DOM filter + progressive search flyout (`/api/search/`) |
| `static/js/contact_manager.js` | NIP-02 Kind 3 contacts, follow buttons, mutual-follow detection |
| `static/js/toast_manager.js` | Global typed toast engine — `window.showToast(message, type, duration)` |
| `static/js/relay_pool.js` | NIP-65 relay pooling, health probing, parallel double-broadcast |

---

## Authentication Flow

1. Anonymous user hits any `@login_required` view → 302 to `oidc_authentication_init`
2. `PKCEOIDCAuthenticationRequestView` generates `code_verifier` + `code_challenge` (S256), stores verifier in session, redirects to IDP with `scope=openid profile email`
3. User authenticates at IDP, IDP redirects back to `/oidc/callback/?code=...&state=...`
4. `PKCEOIDCAuthenticationCallbackView.get_backend_kwargs()` pops `pkce_code_verifier` from session, injects into backend kwargs
5. `MyOIDCAuthenticationBackend.authenticate()` stores verifier on `self` instance, calls library's `authenticate()`
6. Library calls `get_token()` → our override injects `code_verifier` into POST payload → token exchange with IDP
7. `MyOIDCAuthenticationBackend.filter_users_by_claims()` filters by `username=claims["sub"]` and `create_user()` creates sovereign user with unusable password
8. `_evaluate_admin_elevation()` checks `settings.ADMIN_DID` match → grants staff/superuser
9. Session established, user redirected to `LOGIN_REDIRECT_URL` = `/`

---

## Running Tests

```bash
uv run python manage.py test apps.core
uv run ruff check .
```

296 unit tests across 7 modules: `test_auth` (20), `test_views` (77), `test_feed` (52), `test_deck` (85), `test_gallery` (32), `test_issuance` (20), `test_contacts` (10). Ruff: clean.


---

## Key Settings Reference

```python
# OIDC (config/settings.py)
OIDC_RP_CLIENT_ID       = env.str("OIDC_RP_CLIENT_ID", default="iyou-wun-satellite-client")
OIDC_RP_CLIENT_SECRET   = env.str("OIDC_RP_CLIENT_SECRET", default="")  # PKCE-only, no secret needed
OIDC_RP_SCOPES          = env.str("OIDC_RP_SCOPES", default="openid profile email")
OIDC_RP_SIGN_ALGO       = "RS256"
OIDC_VERIFY_SSL         = False
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
USE_X_FORWARDED_HOST    = True

# Auth
AUTHENTICATION_BACKENDS = ["apps.core.auth.MyOIDCAuthenticationBackend", "django.contrib.auth.backends.ModelBackend"]
LOGIN_URL               = "oidc_authentication_init"
LOGIN_REDIRECT_URL      = "/"
ADMIN_DID               = env.str("ADMIN_DID", default="")

# Session
SESSION_COOKIE_NAME     = "wun_sessionid"
SESSION_COOKIE_SECURE   = False
SESSION_COOKIE_SAMESITE = "Lax"
```
