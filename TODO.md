# TODO — iyou_wun (Social Hub)

**Orchestrated from:** `omni_social` (central hub)
**Last synced:** 2026-08-30

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
- [x] **Phase 5 — Feed Modernization & Hero Threading:** Modernized feed cards with 5-button action bar, kebab menu with ecosystem actions, inline media extraction & URL unfurling, and hero-centric conversation view (`/feed?thread=<id>`) with ancestor chains and 1-level descendant drilldown — **Done 2026-08-27**
- [x] **Phase 6 — Batch NIP-10 Reply Ingestion:** Implemented `attach_reply_counts()` batch relay queries against `#e` tags across root notes to ensure instantaneous, accurate reply counts without N+1 bottlenecks — **Done 2026-08-27**
- [x] **Phase 7 — Sovereign Link Deck & Hybrid Profile Resolution:** Implemented `UserLinkDeck`/`UserLinkItem` models, handle claiming, Proof-of-Authority bio challenge verification, hybrid profile resolution (local DB fallback + Kind 0 overlay), and independent handle vs display name separation — **Done 2026-08-27**
- [x] **Phase 8 — Unified Reactive Dashboard Command Center:** Single-card workspace with stateful URL-hash tabs (`#profile`, `#deck`, `#settings`, `#account`), 2-column reactive profile editor with real-time live preview data binding, integrated Link Deck manager, and Sovereign Switchboard — **Done 2026-08-27**
- [x] **Phase 9 — Converse.js ES Module Chat Integration:** Modernized XMPP chat with ESM CDN imports, dynamic multi-tier layout preservation, and automatic JID credential binding — **Done 2026-08-27**
- [x] **Phase 10 — Test Suite Expansion:** 279 passing unit tests across 6 modules with 100% check cleanliness — **Done 2026-08-27**
- [x] **Phase 11 — Progressive Multi-Tier Search Engine:** `/api/search/` (profile + hashtag JSON), `#search-results-dropdown` flyout with 250ms debounced escalation, `circle_feed_filter.js` Tier-1 DOM filter with `?q=` history sync, Tier-3 relay/tag deep-links; replaces nav `overflow-x-hidden` clipping with `overflow-visible` + `relative` anchoring — **Done 2026-08-30**
- [x] **Phase 12 — 3-Column Discovery Feed Shell & Right Rail:** `max-w-6xl` center stream + sticky `_feed_right_rail.html` (TRENDING TOPICS, SOVEREIGN CREATORS, sponsor unit; desktop-only, hidden in thread mode) with `suggested_creators`/`trending_tags`/`relay_count` feed context — **Done 2026-08-30**
- [x] **Phase 13 — Toast & Notification Engine:** `toast_manager.js` (`window.showToast` typed stack) + `_toast_container.html`; feed/contact/bridge controllers migrated to typed toasts — **Done 2026-08-30**
- [x] **Phase 14 — Dynamic Relay Pooling & NIP-65:** `relay_pool.js` (health probing, persisted pools, parallel double-broadcast, mesh health indicator) + server `fetch_user_nip65_relays()` and hardened `relay_req` failover — **Done 2026-08-30**
- [x] **Phase 15 — Batch Reaction (Kind 7) Counting:** `attach_reaction_counts()` single-query like tallies surfaced on feed, profile, and `/api/feed` — **Done 2026-08-30**

- [ ] **Ecosystem Doc Organization:** Standardize repo layout to match iyou_wun precedent — root: `AGENT.md`, `README.md`; `docs/`: `DEVELOPER_GUIDE.md`, `DESIGN_DOC.md`, `TODO.md`, `ecosystem_shared/`, `archive/`. *(Progress: README + DEVELOPER_GUIDE + AGENT + TODO synced; `SPRINT_CHANGELOG.md` added; superseded audit reports archived to `docs/archive/`.)*

---

