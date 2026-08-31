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

- [ ] **Phase 16 — v1.0 Release Hardening & Social Polish:**
  - [x] **16.1 Dynamic Open Graph & Social Unfurling Engine:**
    - Inject context-aware `<meta property="og:*">` and `<meta name="twitter:*">` tags for `/feed?thread=<id>`, `/@<handle>`, and `/gallery` so external link shares (Facebook, X, Discord, iMessage) render branded preview cards with author avatar, excerpt, and media thumbnails.
    - Add branded fallback image `static/img/iyou_symbol.png` for root routes.
  - [x] **16.2 NIP-10 Full-Lineage Ancestor Ladder:**
    - Refactor `fetch_thread()` in `views.py` and `nip10.py` to resolve complete root-to-leaf ancestor chains (`root` → `intermediate ancestors` → `focused note` → `direct replies`) instead of clipping at single-hop parents.
    - Add vertical connective thread guides in `_thread_post.html` and `feed_interactions.js`.
  - [x] **16.3 Custom SVG Reaction Icons & Micro-Animations:**
    - Replace generic system emojis (`❤️`, `🔁`, `💬`, `⚡`, `📤`) with themed Lucide/Heroicon SVGs in `_thread_post.html`, `gallery.html`, and `feed_interactions.js`.
    - Add interactive active states (pink fill on like, rotating transition on repost, amber pulse on zap).
  - [x] **16.4 Web Share API & Mobile Action Sheet:**
    - Wire the Share button to invoke native `navigator.share()` on supported mobile browsers, falling back to clipboard copying on desktop.
  - [x] **16.5 Cyber-Grit Branded Error Views:**
    - Author custom `templates/404.html` and `templates/500.html` extending `base.html` with theme reactivity, return-to-mesh buttons, and error diagnostic codes.
- [x] **16.6 NIP-56 Report/Flag Moderation (implementation):**
  - Kebab-menu 🚩 Report / Flag Note action opens a reason-picker modal (spam, nudity, illegal, malware, profanity, other), publishes a signed NIP-56 Kind 1984 report, removes the card from the DOM, and confirms via toast.

- [x] **Phase 17 — Internationalization, Language Filtering & Inline Note Translation:**
  - [x] **17.1 UI Localization & gettext Infrastructure:**
    - Configure Django `LocaleMiddleware` and translation settings (`LANGUAGES = [('en', 'English'), ('es', 'Español'), ...]`).
    - Wrap core UI labels, navigation buttons, and modal dialogs across templates in `{% trans %}` tags.
    - Compile initial `.po`/`.mo` localization message catalogs for Tier 1 languages (`en`, `es`) — **Done 2026-08-30**
  - [x] **17.2 Dashboard Language & Content Preferences:**
    - Add a **Language & Locale** preference card in `/dashboard#settings`.
    - Store interface language choice in `django_language` cookie and `localStorage`.
    - Add **Feed Stream Language Preferences** selector (`English Only`, `Spanish Only`, `Global / All`) — **Done 2026-08-30**
  - [x] **17.3 Stream Language Gate & Ingestion Filter:**
    - Enhance `detect_language()` in `apps/core/nip10.py` to parse NIP-01 `["lang", "<code>"]` tags and evaluate lightweight script heuristics.
    - Expose `data-lang="<code>"` on all server-rendered and client-rendered note cards.
    - Update `static/js/circle_feed_filter.js` to hide notes outside the user's preferred stream languages when filtering is active — **Done 2026-08-30**
  - [x] **17.4 On-Demand Note Translation API (`POST /api/translate/`):**
    - Implement a backend translation endpoint accepting `{ "text": "...", "source_lang": "...", "target_lang": "..." }`.
    - Wire to a self-hosted translation backend (LibreTranslate / translation service) with response caching — **Done 2026-08-30**
  - [x] **17.5 Inline Translation UI Action:**
    - Render a subtle `[ 🌐 Translate ]` link in `_thread_post.html` and `feed_interactions.js` whenever `note.lang` differs from the active interface language.
    - Wire smooth in-place text replacement with a `[ Translated from <Source> — View Original ]` revert toggle — **Done 2026-08-30**

### Phase 18: Floating Dock Messenger & Live Peer Chat Overlay
- [x] **18.1 Minimized Floating Chat Dock:**
  - Anchor a fixed bottom-right dock trigger (`#floating-chat-dock` / `#floating-chat-root`) across all views with unread counter badges and contact roster popover — **Done 2026-08-30**
- [x] **18.2 Multi-Window Docked Chat Panes:**
  - Support minimized/expanded bottom conversation windows for active 1-on-1 peer chats without leaving `/feed` or `/gallery` — **Done 2026-08-30**
### Phase 19: Client-Side Self-Moderation & Mute Lists
- [x] **19.1 Kebab Dropdown Moderation Actions:**
  - Add `[ 🙈 Hide this Note ]`, `[ 🔇 Mute @author ]`, and `[ 🚫 Block @author ]` actions inside card kebab menus across `_thread_post.html` and `feed_interactions.js` — **Done 2026-08-30**
- [x] **19.2 Real-Time Stream Filtration:**
  - Enhance `circle_feed_filter.js` to dynamically filter out hidden notes, muted pubkeys, and blocked pubkeys stored in `localStorage` — **Done 2026-08-30**
- [x] **19.3 Dashboard Moderation Management Roster:**
  - Add client-side moderation management card under `/dashboard#settings` with dynamic item removal and list clearing (`[ Unmute ]`, `[ Unblock ]`, `[ Unhide ]`) — **Done 2026-08-30**

### Phase 20: XMPP / Converse.js Live Provisioning & Floating Messenger Sync
- [x] **20.1 Prosody Account Provisioning & Token Exchange:**
  - Implement `/api/chat/session/` backend endpoint to verify authenticated DID session, derive canonical JID from pubkey hex, resolve WS/BOSH URLs, and return/reuse an ephemeral `xmpp_token` for the XMPP session.
- [ ] **20.2 Converse.js Headless Binding to Floating Chat:**
  - Bind Converse.js headless connection events directly to `#floating-chat-root` and active `#docked-chat-windows` for bi-directional live delivery across all views. *(In progress: chat.html now fetches `/api/chat/session/` before `converse.initialize()`, passes `jid`/`websocket_url`/`domain`, and falls back to an offline roster + Nostr bridge after 6s; floating_chat.js adds a background XMPP WebSocket listener + unread badge + live bubble dispatch.)*
- [x] **20.3 Fallback NIP-04/NIP-17 Nostr DM Transport:**
  - Implement encrypted direct message fallback over Nostr relays when peer XMPP JID is offline or unreachable — `sendDockedMessage` dispatches JIDs over XMPP and npub/hex peers over a signed Kind 4 NIP-04 event via `window.bridgeClient`.

### Phase 21: NIP-18 / NIP-27 Quote Repost Engine & Embedded Preview Cards
- [x] **21.1 NIP-18/NIP-27 quote tag parsing & enrichment:** `parse_nip18_quote_tags()` extracts `["q", event_id, relay, pubkey]` tags plus `nostr:note1…`/`nostr:nevent1…` URIs in content; `enrich()`/`_enrich_root()` expose `quoted_id`/`quoted_pubkey`; `attach_quoted_notes()` batch-fetches quoted events and attaches enriched `quoted_note` in `fetch_unified_feed()`, `api_feed()`, and `fetch_thread()`.
- [x] **21.2 Embedded quoted card partial:** `templates/includes/_quote_card.html` renders a compact nested quote embed (author, handle, timestamp, truncated text, media thumbnail) and is included by `_thread_post.html` when `note.quoted_note` is present.
- [x] **21.3 Repost / Quote toggle menu:** `_thread_post.html` replaces the static Repost button with a `toggleRepostDropdown()` menu providing Repost & Quote Note actions.
- [x] **21.4 Composer quote attachment:** `_post_composer.html` adds a collapsible `#quote-preview-dock`; `feed_interactions.js` implements `openQuoteComposer()`, `clearQuoteAttachment()`, and appends NIP-18 `["q", …]` + `["p", …]` tags to the signed Kind 1 quote note.
- [x] **21.5 Tests:** `test_nip18_quote_tag_parsing`, `test_quote_composer_attaches_nip18_tags`, `test_thread_post_renders_repost_dropdown_and_quote_card` — **Done 2026-08-30**

- [ ] **Ecosystem Doc Organization:** Standardize repo layout to match iyou_wun precedent — root: `AGENT.md`, `README.md`; `docs/`: `DEVELOPER_GUIDE.md`, `DESIGN_DOC.md`, `TODO.md`, `ecosystem_shared/`, `archive/`. *(Progress: README + DEVELOPER_GUIDE + AGENT + TODO synced; `SPRINT_CHANGELOG.md` added; superseded audit reports archived to `docs/archive/`.)*

---



