# iyou_wun (WUN)

Django 5.2 OIDC Relying Party (Satellite) — authenticates users via the **iyou_idp** identity provider using their Decentralized Identifier (DID).

---

## Quick Start

```bash
cp .env.example .env          # then edit with your IdP credentials
uv sync
uv run python manage.py migrate
uv run python manage.py runserver 8001
```

---

## OIDC Environment Variables (localhost:8000)

Add these to `.env`:

```ini
OIDC_OP_AUTHORIZATION_ENDPOINT=http://localhost:8000/openid/authorize/
OIDC_OP_TOKEN_ENDPOINT=http://localhost:8000/openid/token/
OIDC_OP_USER_ENDPOINT=http://localhost:8000/openid/userinfo/
OIDC_OP_JWKS_ENDPOINT=http://localhost:8000/openid/jwks/
OIDC_RP_CLIENT_ID=your-client-id
OIDC_RP_CLIENT_SECRET=your-client-secret
```

> **Note:** Use `http://localhost:8000` for Local/Sovereign mode. Replace with your IdP's Tailscale IP or hostname for remote environments.

---

## Routes

| Path          | View        | Auth? | Description        |
|---------------|-------------|-------|--------------------|
| `/`           | `home`      | No    | Landing page       |
| `/dashboard`  | `dashboard` | Yes   | DID + session info |
| `/feed`       | `feed`      | Yes   | Nostr global feed  |
| `/admin/`     | admin       | —     | Django admin       |
| `/oidc/`      | OIDC flow   | —     | Login/logout       |

---

## Developer Guide

See **[WUN_DEVELOPER_GUIDE.md](WUN_DEVELOPER_GUIDE.md)** for full documentation: architecture, auth flow, feed implementation, known issues, and testing.
