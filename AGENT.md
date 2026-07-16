## CRITICAL: OpenID Connect & Ingress Invariants

All authentication and user provisioning logic in this repository MUST conform strictly to the canonical ecosystem specifications located at:
- `docs/ecosystem_shared/OMNI_SOCIAL_AUTH_STANDARDIZATION.md`
- `docs/ecosystem_shared/AUTH_FLOW_SPECIFICATION.md`

Reference Implementation to follow: `docs/ecosystem_shared/auth_pkce.py`

Do NOT implement cleartext client secrets, do NOT use email addresses as database lookup anchors, and ensure all post-auth logic implements the `evaluate_sovereign_admin_posture` routine.

---

## Repository Overview

**iyou_wun** (WUN) is a Django 5.2 OIDC Relying Party satellite that authenticates users via the **iyou_idp** identity provider using Decentralized Identifiers (DID). Passwords are deprecated — OIDC/DID is the sole entry point.

**Core features:** Omni-Social Nostr Feed (Kind 1/7/1063/1111/30023/1112), Media Gallery, Sovereign Profile pages, XMPP Chat (Converse.js), Poly Governance Polls, Verifiable Credential issuance.

---

## Quick Start

```bash
cp .env.example .env          # fill in OIDC_RP_CLIENT_ID, WUN_SECRET_KEY
uv sync
uv run python manage.py migrate
uv run python manage.py runserver 8001
```

Requires: running `iyou_idp` instance + `iyou_home` (Tauri bridge :9001, Blossom :9002, local relay :9003).

---

## Documentation Map

| Document | Location | Purpose |
|----------|----------|---------|
| Developer Guide | `docs/DEVELOPER_GUIDE.md` | Full setup, env vars, architecture, troubleshooting |
| Design Doc | `docs/DESIGN_DOC.md` | Sovereign Media Stack architecture (Django + React + Rust) |
| Project TODO | `docs/TODO.md` | Current task tracking (synced from omni_social hub) |
| Auth Standard | `docs/ecosystem_shared/OMNI_SOCIAL_AUTH_STANDARDIZATION.md` | Platform-wide OIDC/PKCE rules |
| Auth Flow Spec | `docs/ecosystem_shared/AUTH_FLOW_SPECIFICATION.md` | Request/response flow diagrams |
| PKCE Reference | `docs/ecosystem_shared/auth_pkce.py` | Canonical reference implementation |
| Satellite Coordination | `docs/ecosystem_shared/satellite-coordination.md` | Multi-satellite sync patterns |

### Archive (historical reference)

| Document | Location | Notes |
|----------|----------|-------|
| Meshing Protocol | `docs/archive/MESHING_PROTOCOL.md` | Early integration plan template |
| Strategic Roadmap | `docs/archive/STRATEGIC_ROADMAP.md` | Phase 2 roadmap (largely completed) |
| Global-Local Nostr | `docs/archive/GLOBAL_LOCAL_NOSTR.md` | Nostr relay architecture reference |

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
| `apps/core/views.py` | Feed, Dashboard, Gallery, Profile, Chat, API endpoints |
| `apps/core/models.py` | `IssuedCredential` — VC issuance tracking |
| `apps/core/did_kit.py` | Ed25519 VC signing/verification |

---

## Authentication Flow

1. Anonymous user hits any `@login_required` view → 302 to `oidc_authentication_init`
2. `PKCEOIDCAuthenticationRequestView` generates `code_verifier` + `code_challenge` (S256), stores verifier in session, redirects to IDP with `scope=openid profile email`
3. User authenticates at IDP, IDP redirects back to `/oidc/callback/?code=...&state=...`
4. `PKCEOIDCAuthenticationCallbackView.get_backend_kwargs()` pops `pkce_code_verifier` from session, injects into backend kwargs
5. `PKCEAuthenticationBackend.authenticate()` stores verifier on `self` instance, calls library's `authenticate()`
6. Library calls `get_token()` → our override injects `code_verifier` into POST payload → token exchange with IDP
7. `MyOIDCAuthenticationBackend.filter_users_by_claims()` does `get_or_create(username=claims["sub"])` — DID is the username
8. `_evaluate_admin_elevation()` checks `settings.ADMIN_DID` match → grants staff/superuser
9. Session established, user redirected to `LOGIN_REDIRECT_URL` = `/`

---

## Running Tests

```bash
uv run python manage.py test apps.core.tests
```

89 tests across 4 modules: `test_auth` (17), `test_views` (21), `test_feed` (31), `test_issuance` (19).

---

## Key Settings Reference

```python
# OIDC (config/settings.py)
OIDC_RP_CLIENT_ID       = env.str("OIDC_RP_CLIENT_ID")
OIDC_RP_CLIENT_SECRET   = env.str("OIDC_RP_CLIENT_SECRET", default="")  # PKCE-only, no secret needed
OIDC_RP_SCOPES          = "openid profile email"
OIDC_RP_SIGN_ALGO       = "RS256"
OIDC_VERIFY_SSL         = False
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
USE_X_FORWARDED_HOST    = True

# Auth
AUTHENTICATION_BACKENDS = ["apps.core.auth_pkce.PKCEAuthenticationBackend", "django.contrib.auth.backends.ModelBackend"]
LOGIN_URL               = "oidc_authentication_init"
LOGIN_REDIRECT_URL      = "/"
ADMIN_DID               = env.str("ADMIN_DID", default="")

# Session
SESSION_COOKIE_NAME     = "wun_sessionid"
SESSION_COOKIE_SECURE   = True
SESSION_COOKIE_SAMESITE = "Lax"
```
