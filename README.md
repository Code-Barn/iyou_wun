# iyou_wun (WUN)

Django 5.2 OIDC Relying Party (Satellite) — authenticates users via the **iyou_idp** identity provider using their Decentralized Identifier (DID). Sovereign social features: Nostr feed with double-broadcast, media gallery, profile pages, and XMPP chat.

---

## Quick Start

```bash
cp .env.example .env          # then edit with your IdP credentials
uv sync
uv run python manage.py migrate
uv run python manage.py runserver 8001
```

Requires a running iyou_idp instance and iyou_home (Tauri bridge + Blossom + local relay + XMPP).

---

## Routes

| Path                  | View           | Auth Required | Description                          |
| --------------------- | -------------- | ------------- | ------------------------------------ |
| `/`                   | `home`         | No            | Landing page                         |
| `/dashboard`          | `dashboard`    | Yes           | DID display + Edit Profile (Kind 0)  |
| `/feed`               | `FeedView`     | Yes           | Unified Nostr feed + thread view     |
| `/gallery`            | `GalleryView`  | Yes           | Media grid with MIME filters + modal |
| `/profile/<npub>/`    | `ProfileView`  | No            | Sovereign profile pages              |
| `/chat`               | `ChatView`     | Yes           | XMPP sovereign chat (Converse.js)    |
| `/admin/`             | Django admin   | —             |                                      |
| `/oidc/`              | OIDC flow      | —             | Login/logout                         |

---

## OIDC Environment Variables (127.0.0.1)

```ini
OIDC_OP_AUTHORIZATION_ENDPOINT=http://127.0.0.1:8000/openid/authorize/
OIDC_OP_TOKEN_ENDPOINT=http://127.0.0.1:8000/openid/token/
OIDC_OP_USER_ENDPOINT=http://127.0.0.1:8000/openid/userinfo/
OIDC_OP_JWKS_ENDPOINT=http://127.0.0.1:8000/openid/jwks/
OIDC_RP_CLIENT_ID=your-client-id
OIDC_RP_CLIENT_SECRET=your-client-secret
```

**Always use `127.0.0.1`** — never `localhost`. This prevents IPv6 ambiguity, OIDC issuer mismatches, and browser cookie domain issues across macOS, Linux, and Windows.

---

## Developer Guide

See **[WUN_DEVELOPER_GUIDE.md](WUN_DEVELOPER_GUIDE.md)** for full documentation: architecture, auth flow, Signature Bridge protocol, mesh awareness, feed implementation, profile pages, gallery, chat, known issues, and testing.
