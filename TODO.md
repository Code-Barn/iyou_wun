# TODO — iyou_wun (Social Hub)

**Orchestrated from:** `omni_social` (central hub)
**Last synced:** 2026-07-20

---

## Layer 0 — Ecosystem Standardization

> Templates generated via `omni_social/generate_templates.py`. Do not edit
> `_ecosystem_bar.html` or `_standard_header.html` manually — changes will be
> overwritten on next regeneration. Edit the canonical source in omni_social instead.

- [x] OIDC client credentials aligned to ecosystem PKCE standard — `iyou-wun-satellite-client`, empty secret — **Done 2026-07-20**

## Layer 1 — PKCE / Auth

- [x] Relying Party Hardening: fixed library method boundary data drop using Instance State Relay pattern (`get_backend_kwargs()` override); anchored username lookups to `sub` claim DID strings; centralized `ADMIN_DID` evaluation via `os.environ.get()` — **Done 2026-07-13**

## Layer 2 — App-Specific

- [x] **Phase 1 — Profile Editing (Kind 0):** Dashboard rewritten with 6 NIP-01 fields, hardened Tauri bridge, banner/NIP-05/tip display on profile page — **Done 2026-07-20**
- [x] **Phase 2 — NIP-10 Threading Engine:** `apps/core/nip10.py` with `parse_tags()` and `build_thread_tree()`; feed rewritten with threaded layout using `_thread_post.html` partial — **Done 2026-07-20**
- [x] **Phase 3 — Multi-Modal Media Gallery:** `MEDIA_CATEGORIES` dict, `categorize_media()`, `_extract_nip94_tags()`; gallery rewritten with tabbed decks (images/video/audio/other), masonry grid, 16:9 video feed, audio deck with inline players, lightbox modal — **Done 2026-07-20**
- [x] **Phase 4 — JavaScript Modularization:** Three static JS modules extracted (`bridge_client.js`, `feed_interactions.js`, `gallery_player.js`); total template reduction: 2,543→674 lines (−73%) — **Done 2026-07-20**
- [x] **Documentation Accuracy Audit:** `AGENT.md`, `docs/DEVELOPER_GUIDE.md`, `TODO.md` updated to reflect current codebase — **Done 2026-07-20**

- [ ] **Ecosystem Doc Organization:** Standardize repo layout to match iyou_wun precedent — root: `AGENT.md`, `README.md`; `docs/`: `DEVELOPER_GUIDE.md`, `DESIGN_DOC.md`, `TODO.md`, `ecosystem_shared/`, `archive/`.

---
