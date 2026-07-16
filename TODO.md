# TODO — iyou_wun (Social Hub)

**Orchestrated from:** `omni_social` (central hub)
**Last synced:** 2026-07-13

---

## Layer 0 — Ecosystem Standardization

> Templates generated via `omni_social/generate_templates.py`. Do not edit
> `_ecosystem_bar.html` or `_standard_header.html` manually — changes will be
> overwritten on next regeneration. Edit the canonical source in omni_social instead.

- [ ]

## Layer 1 — PKCE / Auth

- [x] Relying Party Hardening: fixed library method boundary data drop using Instance State Relay pattern (`get_backend_kwargs()` override); anchored username lookups to `sub` claim DID strings; centralized `ADMIN_DID` evaluation via `os.environ.get()` — **Done 2026-07-13**

## Layer 2 — App-Specific

- [ ] **Ecosystem Doc Organization:** Standardize repo layout to match iyou_wun precedent — root: `AGENT.md`, `README.md`; `docs/`: `DEVELOPER_GUIDE.md`, `DESIGN_DOC.md`, `TODO.md`, `ecosystem_shared/`, `archive/`.

---
