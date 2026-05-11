# Developer Guide - iyou_wun (WUN)

## Overview

**iyou_wun** (WUN) is a Django 5.2 OIDC Relying Party (Satellite) that authenticates users via the **iyou_idp** identity provider. Users log in with their Decentralized Identifier (DID) using the OpenID Connect flow. A local `django.contrib.auth.User` is created keyed on the `sub` claim (the DID).

The project is in active development. Authentication works end-to-end. Next up: the Omni-Social feed (Nostr + IPFS/Blossom integration).

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

---

## Quick Start

### Prerequisites
- Python >= 3.10
- A running iyou_idp instance (see `.env` for endpoints)

### Setup

```bash
# Activate the virtual environment
source .venv/bin/activate

# Install dependencies
pip install -e .

# Copy environment template and fill in credentials
cp .env.example .env
# Edit .env with your OIDC_RP_CLIENT_ID and OIDC_RP_CLIENT_SECRET

# Run migrations
python manage.py migrate

# Start the dev server
python manage.py runserver
```

---

## OIDC Environment Variables

The following variables are required in `.env` to connect to the iyou_idp:

| Variable                            | Purpose                                          |
| ----------------------------------- | ------------------------------------------------ |
| `OIDC_OP_AUTHORIZATION_ENDPOINT`    | IdP authorization URL (user login redirect)      |
| `OIDC_OP_TOKEN_ENDPOINT`            | IdP token exchange endpoint                      |
| `OIDC_OP_USER_ENDPOINT`             | IdP userinfo endpoint (returns claims)           |
| `OIDC_RP_CLIENT_ID`                 | Client ID registered with the IdP                |
| `OIDC_RP_CLIENT_SECRET`             | Client secret registered with the IdP            |

Current iyou_idp values:

```
OIDC_OP_AUTHORIZATION_ENDPOINT=http://localhost:8000/openid/authorize/
OIDC_OP_TOKEN_ENDPOINT=http://localhost:8000/openid/token/
OIDC_OP_USER_ENDPOINT=http://localhost:8000/openid/userinfo/
```

The JWKS endpoint is configured via `OIDC_OP_JWKS_ENDPOINT` and should use the same host as the other endpoints.

> **Note**: For Local/Sovereign mode, use `http://localhost:8000` to satisfy browser security requirements. Replace with your IdP's IP/host when using Tailscale or other environments.

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
│   ├── views.py                     # home(), dashboard(), feed()
│   ├── urls.py                      # App-level URL routing
│   ├── auth.py                      # MyOIDCAuthenticationBackend
│   ├── models.py                    # (empty -- no models yet)
│   ├── admin.py                     # (empty -- no admin registrations)
│   └── tests.py                     # OIDC auth + view tests
└── templates/
    ├── home.html                    # Landing page with login button
    ├── dashboard.html               # Authenticated user dashboard (DID display)
    └── feed.html                    # Omni-Social feed placeholder
```

### URL Map

| Path              | View        | Auth Required | Notes                        |
| ----------------- | ----------- | ------------- | ---------------------------- |
| `/`               | `home`      | No            | Landing page                 |
| `/dashboard`      | `dashboard` | Yes           | Shows user DID & session     |
| `/feed`           | `feed`      | Yes           | Omni-Social feed placeholder |
| `/admin/`         | Django admin               |
| `/oidc/`          | OIDC flow   | --            | Provided by mozilla-django-oidc |

---

## Running Tests

```bash
source .venv/bin/activate
python manage.py test
```

Tests cover:
- `MyOIDCAuthenticationBackend.create_user` -- ensures a user is created with the DID from the `sub` claim
- Dashboard view -- authenticated users see their DID; unauthenticated users are redirected to login
- Home page -- unauthenticated users see the login prompt

---

## Known Issues

- `.env` was previously committed to git -- now removed from tracking and gitignored. **DO NOT re-commit it.**
- `OIDC_USERNAME_ALGO` lambda and `MyOIDCAuthenticationBackend.create_user` both derive the username from `sub` -- redundant but not harmful. Clean up by choosing one approach.
- No domain models yet (`models.py` is empty).
- `main.py` is a stub with unclear purpose.
- Production hardening needed: `DEBUG = True`, default `SECRET_KEY`, empty `ALLOWED_HOSTS`, Tailwind via CDN.
- No lock file (`poetry.lock` / `requirements.txt`) for reproducible builds.
- `apps/core/admin.py` is empty -- no models registered for the admin interface.
