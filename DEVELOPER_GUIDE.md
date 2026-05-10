# Developer Guide - iyou-wun (Project Alpha)

## Overview

**iyou-wun** is a Django 5.2 application that serves as a web frontend (Relying Party) for an OpenID Connect (OIDC) identity provider. It uses the `mozilla-django-oidc` library to authenticate users via a decentralized identity (DID) system.

The project is in its **early stages** -- the authentication flow works but there are no domain models, tests, or production-hardening yet.

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
- A running OIDC provider (IdP) on port 8000 (see `.env` for endpoints)

### Setup

```bash
# Activate the existing virtual environment
source .venv/bin/activate

# Install dependencies (if starting fresh)
pip install -e .

# Ensure the database is up to date
python manage.py migrate

# Run the development server
python manage.py runserver
```

The app runs at `http://localhost:8000` by default.

---

## Project Layout

```
.
├── main.py                          # CLI entry point (stub -- unused)
├── pyproject.toml                   # Project metadata & dependencies
├── .env                             # Environment variables (OIDC creds)
├── .python-version                  # Python 3.10
├── .gitignore
├── config/
│   ├── settings.py                  # Django settings (OIDC, auth, apps)
│   ├── urls.py                      # Root URL configuration
│   ├── wsgi.py                      # WSGI entrypoint
│   └── asgi.py                      # ASGI entrypoint
├── apps/core/
│   ├── __init__.py
│   ├── apps.py                      # Django app config
│   ├── views.py                     # home() & dashboard() views
│   ├── urls.py                      # App-level URL routing
│   ├── auth.py                      # Custom OIDC auth backend
│   ├── models.py                    # (empty -- no models yet)
│   ├── admin.py                     # (empty -- no admin registrations)
│   └── tests.py                     # (empty -- no tests yet)
└── templates/
    ├── home.html                    # Landing page with login button
    └── dashboard.html               # Authenticated user dashboard
```

---

## Architecture & Data Flow

1. **Unauthenticated users** hit `/` (home page) and see a "Login with iYou Identity" button.
2. Clicking login redirects to the OIDC provider's authorization endpoint configured in `.env`.
3. After authentication, the IdP redirects back; `mozilla-django-oidc` handles the token exchange.
4. A local `django.contrib.auth.User` is created (or reused) keyed by the `sub` claim (the DID).
5. The user lands on `/dashboard` where their DID is displayed.

### URL Map

| Path              | View        | Auth Required | Notes                        |
| ----------------- | ----------- | ------------- | ---------------------------- |
| `/`               | `home`      | No            | Landing page                 |
| `/dashboard`      | `dashboard` | Yes           | Shows user DID               |
| `/admin/`         | Django admin               |
| `/oidc/`          | OIDC flow   | --            | Provided by mozilla-django-oidc |

### Authentication Backends

Two backends are configured in `settings.py`:
1. `django.contrib.auth.backends.ModelBackend` -- standard Django auth
2. `mozilla_django_oidc.auth.OIDCAuthenticationBackend` -- OIDC RP auth

A custom backend exists at `apps.core.auth.MyOIDCAuthenticationBackend` but is **not wired into `AUTHENTICATION_BACKENDS`** (see Issues below).

---

## Strengths

- **Clean Django layout** -- standard project/app structure, easy for any Django dev to understand.
- **Proper use of environment variables** -- secrets (OIDC credentials) come from `.env`, not hardcoded.
- **Solid dependency choices** -- uses the well-maintained `mozilla-django-oidc` library instead of rolling custom OIDC.
- **No premature abstraction** -- no custom user model, no over-engineered auth flows; the simplest thing that works.
- **Django system checks pass cleanly** -- no import errors, no configuration issues detected.
- **Database is migrated and ready** -- all Django system migrations applied, no pending migrations.
- **Tailwind CSS out of the box** -- utility-first styling via CDN for rapid prototyping.
- **Virtual environment is set up and working** -- no dependency resolution issues.

---

## Issues & Areas for Improvement

### 1. CRITICAL: `.env` file is committed to version control
The `.env` file contains `OIDC_RP_CLIENT_SECRET` and is tracked by git. This is a security risk.
- **Fix:** Add `.env` to `.gitignore`, remove it from git history (`git rm --cached .env`), and create a `.env.example` template.

### 2. Custom auth backend is not wired in
`apps/core/auth.py` defines `MyOIDCAuthenticationBackend` (which creates users from OIDC claims), but `settings.py` line 134 references `mozilla_django_oidc.auth.OIDCAuthenticationBackend` directly. The custom backend's `create_user` logic is never used.
- **Fix:** Change `AUTHENTICATION_BACKENDS[1]` to `'apps.core.auth.MyOIDCAuthenticationBackend'`.
- Alternatively, delete `auth.py` if the custom logic is not needed.

### 3. `OIDC_USERNAME_ALGO` vs `auth.py` naming conflict
`settings.py:160` sets `OIDC_USERNAME_ALGO` (used by mozilla-django-oidc to derive the local username), and `auth.py:9` also uses `claims.get('sub')`. This creates ambiguity -- which mechanism controls username generation?
- **Fix:** Pick one approach and remove the other.

### 4. No tests
`tests.py` is empty. The project needs at minimum:
- View tests (home page loads, dashboard redirects unauthenticated users)
- Auth backend tests
- Smoke tests for the OIDC flow

### 5. Empty/placeholder files
- `main.py` is a `print("Hello")` stub -- unclear if this is meant to be a Django management command or something else.
- `models.py`, `admin.py` are empty -- no domain model yet.

### 6. Production-readiness gaps
- `DEBUG = True`
- `SECRET_KEY` is the default `django-insecure-...` key (hardcoded)
- `ALLOWED_HOSTS = []` -- will reject all requests in production
- Tailwind CSS loaded via CDN (no build pipeline, no offline support, no purging)
- No database connection pooling or production DB config

### 7. Naming inconsistency
Templates refer to "Project Alpha" (`<h1>Welcome to Project Alpha</h1>`) but the project is named `iyou-wun`. These should be aligned.

### 8. Missing `.env.example`
Developers need a reference for what environment variables to set. Create `.env.example` with placeholder values.

### 9. Empty README.md
New developers get no guidance from the repository root.

### 10. No lock file
`pyproject.toml` specifies loose version ranges (`django>=5.2.13`). No `poetry.lock` or `requirements.txt` to pin dependencies for reproducible builds.

### 11. Hardcoded IdP endpoints
`settings.py:149-152` hardcodes the IdP URLs. Some are overridden by `.env` values, but the env vars aren't actually used by those settings -- there's a disconnect. The settings use hardcoded strings, and the `.env` file also defines the same URLs. The env vars are never read in settings except for `OIDC_RP_CLIENT_ID` and `OIDC_RP_CLIENT_SECRET`.

---

## Development Roadmap Suggestions

1. **Secure the credentials** - gitignore `.env`, rotate the leaked secret.
2. **Fix the auth backend wiring** - decide which username mechanism to keep.
3. **Write tests** - start with view tests, then auth backend tests.
4. **Add domain models** - build out the core data model for the application.
5. **Production config** - move secrets to env, configure `ALLOWED_HOSTS`, disable DEBUG.
6. **Add CI pipeline** - run tests, linting on every PR.
7. **Replace Tailwind CDN** - set up proper asset pipeline or migrate to a build system.
8. **Create `.env.example`** and fill in the README.
