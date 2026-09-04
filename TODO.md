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

### Phase 22: Global NIP-05 Verification & NIP-02 Contact Follow Pipeline
- [x] **22.1 Public NIP-05 verification endpoint:** `nip05_well_known()` at `/.well-known/nostr.json` resolves `?name=<handle>` (UserLinkDeck handle / username → 64-hex pubkey), `?name=_` returns the platform root key, and omitting `name` returns all verified public handles (capped at 100); emits standard `names`/`relays` schema with `Access-Control-Allow-Origin: *`.
- [x] **22.2 NIP-02 contact follow/unfollow API:** `api_contacts_follow()` (`POST /api/contacts/follow/`) loads the active user's latest Kind 3 from relays, adds/removes the `["p", target_pubkey, "wss://relay.iyou.me", petname]` tag, and returns a prepared unsigned Kind 3 event for client signing plus the refreshed contact summary.
- [x] **22.3 Server-backed follow client:** `toggleFollowUser()` in `contact_manager.js` calls the API, signs the returned Kind 3 via the Signature Bridge (`bridgeClient.signEvent`/`connect`), broadcasts across the pool relays, updates the local contact cache, toggles `[ + Follow ]` ⇄ `[ ✓ Following ]` UI, and toasts `Followed/Unfollowed @<target>`; all `[data-follow-target]` buttons now route through this pipeline. Kebab menu gains a state-aware `➕ Follow @author` / `➖ Unfollow @author` row.
- [x] **22.4 Tests & tracking:** `ApiContactsFollowTests` (Kind 3 payload prep, follow append, unfollow removal, anonymous/invalid rejection) + `NIP05EndpointTests` root `_` and all-handles cases; Phase 22 codified in TODO.md — **Done 2026-08-31**

### Phase 23: Global Discovery, NIP-05 Handle Routing & Sovereign Identity Badging
- [x] **23.1 Universal Profile Identifier Resolver (`/profile/<identifier>`):**
  - Update `ProfileView` and route regex to resolve `npub1...`, 64-character hex, and `handle@domain.com` (NIP-05 identifier).
  - Implement async/background NIP-05 lookup to fetch `https://<domain>/.well-known/nostr.json?name=<handle>` and resolve pubkey hex.
  - Auto-decorate NIP-05 handles in note cards and metadata rows as clickable profile links.
- [x] **23.2 Sovereign Enclave vs. Global Mesh Badging:**
  - Decorate authors in `_thread_post.html`, `profile.html`, and `feed_interactions.js`:
    - `[ ⚡ iyou ]`: Native sovereign peer registered in `UserLinkDeck` with active local enclave support.
    - `[ 🌐 Mesh ]`: External Nostr network peer discovered via public relay firehose.
    - `[ 🏷️ NIP-05 ]`: Verified external identifier badge.
  - Add active transport badge inside `#floating-chat-dock` (`Transport: ⚡ iyou Enclave` vs `Transport: 🌐 Nostr Relays`).
- [x] **23.3 Global Directory Search & NIP-50 Fallback (`purplepag.es` Indexing):**
  - Enhance `#feed-search-input` triage logic:
    - Bech32 string (`npub1`, `note1`, `nevent1`) -> immediate redirect.
    - NIP-05 address (`user@domain.com`) -> resolve and route to profile.
    - Plain text search (e.g. `fiatjef`, `jack`) -> query local cache first; on miss, dispatch NIP-50 search query (`{"kinds": [0], "search": "<query>", "limit": 10}`) to `wss://purplepag.es` and `wss://relay.nostr.band`.
  - Render an interactive discovery dropdown popover displaying matching avatar, display name, handle, and 1-click `[ View ]` / `[ + Follow ]` actions.

### Phase 24: iyou Circle Scoping, NSFW Hardening, Translation Fallback & Blossom BUD-01 Ingestion
- [x] **24.1 Strict iyou Circle Scoping & Zero-Bleed Fallback:**
  - `get_iyou_pubkeys()` extracts normalized 64-char hex pubkeys from all registered `UserLinkDeck` and local auth records.
  - `FeedView`, `api_feed`, `fetch_text_notes()`, and `fetch_unified_feed()` enforce zero-bleed fallback returning empty lists when no registered ecosystem pubkeys match.
  - `circle_feed_filter.js` strictly isolates the `iyou` circle with explicit empty-state messaging.
- [x] **24.2 NSFW Filter & Sensitive Content Gate:**
  - `detect_content_warning()` in `apps/core/nip10.py` detects expanded NIP-36 tags (`content-warning`, `nsfw`, `sensitive`, `nudity`, `l` ISO-3166-1 tags) and content hashtags (`#nsfw`, `#sensitive`, `#18+`, `#adult`).
  - Flagged cards render with `data-has-cw="true"` and `.blur-me` filter on media attachments, fully hidden when `wun_nsfw_pref === 'hide'`.
- [x] **24.3 Resilient Translation Engine (`POST /api/translate/`):**
  - Multi-stage translation endpoint with cache checking (`trans:{source}:{target}:{hash}`), upstream service execution, and mock/offline fallback returning guaranteed HTTP 200 JSON.
  - `translateNote()` in `feed_interactions.js` provides view toggle (`View Original` ⇄ `View Translation`) and warning toasts on connectivity issues.
- [x] **24.4 Blossom BUD-01 Media Upload Pipeline:**
  - Composer calculates in-memory SHA-256 (`crypto.subtle.digest`), performs `PUT` upload to Blossom server (`https://cdn.iyou.me/upload` with local fallback), renders thumbnail preview dock in `#composer-media-preview-dock`, and attaches NIP-94 tags to the signed note.
- [x] **24.5 Tests:** `test_nip36_expanded_sensitive_tags_flagged_properly`, `test_iyou_circle_returns_empty_when_no_registered_pubkeys`, `test_api_translate_resilient_fallback_returns_200`, `test_iyou_feed_zero_bleed_when_empty` — **Done 2026-08-31**

### Phase 25: Media Gallery Viewports, Custom Players (Plyr.js/Audio) & Infinite Scroll
- [x] **25.1 Plyr.js Video Viewport Integration:**
  - Standardized `.plyr-video-container` video players with Plyr CDN styles/scripts, 16:9 and 9:16 aspect ratio support, and responsive video cards across gallery tabs.
- [x] **25.2 Custom Audio Deck & Single-Instance Coordinator:**
  - Modern audio cards featuring vinyl disc rotating animations, metadata headers, custom range scrubbers, playtime counters, and `stopActiveMedia()` coordination preventing overlapping audio/video playback.
  - Keyboard navigation: Space (play/pause), M (mute/unmute), ArrowLeft/ArrowRight (5s seek).
- [x] **25.3 Cursor-Based Gallery Pagination & Infinite Scroll:**
  - `GET /api/gallery` endpoint supporting `until`, `type`, `pubkey`, and `limit` with JSON serialization.
  - `#gallery-pagination-sentinel` with IntersectionObserver loading more media cards and re-hydrating Plyr/audio players without page reloads.
- [x] **25.4 Tests:** `test_gallery_view_renders_plyr_and_categorized_decks`, `test_api_gallery_cursor_pagination` — **Done 2026-08-31**

### Phase 26: Feed Sanitization, Empty Note Suppression & P2P Discovery Noise Gate
- [x] **26.1 Ingestion Sanitization & Renderability Guard (`apps/core/nip10.py`):**
  - Implemented `is_renderable_note(event: dict) -> bool` to suppress empty discovery beacons (miasma-peer, p2p-beacons, relay-ping, node-discovery) and blank Kind 1 events without attached media.
  - Media tags (imeta, url, image, thumb) allow empty content to pass through.
- [x] **26.2 Server-Side Filtering in Pipeline Functions (`apps/core/views.py`):**
  - Added `is_renderable_note` filtering in `fetch_unified_feed()`, `api_feed()`, and `fetch_thread()` before building thread trees.
  - Also integrated into `process_into_feed()` for comprehensive coverage.
- [x] **26.3 Client-Side Sequential Filtering & Build Guard:**
  - Added empty/non-renderable content check in `circle_feed_filter.js` `applyFilters()` to hide cards without body text or media.
  - Added `isRenderableNote()` guard in `feed_interactions.js` `buildCardHtml()` to prevent rendering of non-renderable notes.
- [x] **26.4 Unit Tests (`apps/core/tests/test_feed.py`):**
  - `test_is_renderable_note_drops_empty_content_without_media`: Asserts notes with empty content and no media tags return False.
  - `test_is_renderable_note_allows_empty_content_with_media_tag`: Asserts notes with empty content but media tags return True.
  - `test_is_renderable_note_drops_p2p_discovery_beacons`: Asserts notes with P2P discovery tags return False.
  - `test_fetch_unified_feed_omits_non_renderable_events`: Verifies filtering in the feed pipeline.
- [x] **26.5 TODO.md Updated:** Documented Phase 26 implementation — **Done 2026-08-31**

### Phase 27: Language Detection Calibration & Live Translation Pipeline
- [x] **27.1 Strict ASCII & English Bias in detect_language() (`apps/core/nip10.py`):**
  - Strips URLs, mentions (`@...`, `nostr:...`), and code snippets before character distribution analysis.
  - Classifies as `"en"` when >= 85% ASCII, no foreign script characters, and no accented diacritics.
  - Preserves instant triggers for non-Latin scripts (Japanese, Korean, Chinese, Cyrillic, Arabic, Thai, Greek, Hebrew).
- [x] **27.2 Translation API Endpoint (`POST /api/translate/`):**
  - Sanitizes input, limits to 1000 characters, uses external service with 4-second timeout.
  - Returns JSON with `success`, `translated_text`, `source_lang`, `target_lang` fields.
  - Fallback message: `[Translation unavailable - network timeout]` for offline/failed requests.
- [x] **27.3 Route Registration (`apps/core/urls.py`):**
  - Registered `path("api/translate/", views.api_translate, name="api_translate")`.
- [x] **27.4 Translation UI (`templates/includes/_thread_post.html`):**
  - Added translate button rendering only when `note.lang` is present and not English.
- [x] **27.5 Client-Side Translation (`static/js/feed_interactions.js`):**
  - Implemented `translateNote(btn, noteId, sourceLang)` with toggle state, loading indicator, and cached original text.
- [x] **27.6 Unit Tests:**
  - `test_detect_language_classifies_ascii_tech_posts_as_english` in test_feed.py.
  - `test_detect_language_classifies_cjk_and_accents_correctly` in test_feed.py.
  - `test_api_translate_endpoint_post`, `test_api_translate_with_spanish_text`, `test_api_translate_empty_text_returns_400`, `test_api_translate_exceeds_max_length_returns_400` in test_views.py.
  - `test_thread_post_omits_translate_button_for_english_notes` in test_views.py.
- [x] **27.7 TODO.md Updated:** Documented Phase 27 implementation — **Done 2026-08-31**

### Phase 28: Trending Topics Real-Time Aggregator & Tag-Click Filtering
- [x] **28.1 Real-Time Tag Aggregator (`apps/core/views.py`):**
  - Purged all hardcoded mock trending dictionaries (`#nostr 1.2k`, `#sovereign 840`, `#iyou 450`).
  - `calculate_trending_tags(events, iyou_pubkeys=None) -> (global, iyou)` now aggregates real `#t` tags from the deduplicated renderable event batch via `Counter`, with case-insensitive slug normalization and exact integer frequencies.
  - iyou isolation tallies only authors present in the registered sovereign pubkey set.
  - `FeedView.get_context_data()` passes real `trending_tags_global`/`trending_tags_iyou` to the right rail; `api_feed` returns the same real-time aggregates.
- [x] **28.2 Interactive Tag Triggers (`templates/includes/_feed_right_rail.html`):**
  - `[ 🌐 Global ]`/`[ ⚡ iyou ]` scope tabs (`#trending-tab-global`/`#trending-tab-iyou`) toggle `#trending-global-list`/`#trending-iyou-list`.
  - Tag cards render real tag metadata (`{{ tag.name }}`, `{{ tag.display_count }}`) and invoke `filterByTag('<tag_slug>')` on click.
  - Empty-state notices render when a batch has no `#t` tags.
- [x] **28.3 Client-Side Tag Filter Routing (`static/js/circle_feed_filter.js`):**
  - `filterByTag(tagSlug)` injects `#<slug>` into `#feed-search-input`, applies filters, smooth-scrolls to `#feed-container`, and reflects `?q=%23<slug>` via `window.history.replaceState`; exposed as `window.filterByTag`.
- [x] **28.4 Tests & Verification:**
  - `test_calculate_trending_tags_aggregates_real_counts` and `test_calculate_trending_tags_isolates_iyou_pubkeys` in `test_feed.py`.
  - `test_feed_right_rail_renders_empty_state_when_zero_tags` and `test_feed_right_rail_renders_trending_tags_with_click_handlers` in `test_views.py`.
  - `npm run build:css`, `manage.py check`, `manage.py test apps.core`, `ruff check .` all clean — **Done 2026-09-01**

### Phase 29: Bridge Health UX, Persona Timeout, Mobile Diagnostics & Test Reconciliation
- [x] **29.1 Persona Switcher Bridge Health Timeout (`static/js/bridge_client.js`, `templates/includes/_standard_header.html`):**
  - Added `id="persona-bridge-status"` to the "Bridge Connected" pill in the "Active Enclave Personas" header divider.
  - `queryVaultPersonas()` (2500ms timeout) sends `list_profiles` + `LIST_PERSONAS` on socket open or channel open, and arms `_personaQueryTimer`.
  - `markPersonaBridgeOffline()` renders an amber "Enclave Offline" notice in `#persona-list-container` and flips the pill to `BRIDGE OFFLINE`; idempotent.
  - Persona-list responses (`profiles_list`, `LIST_PERSONAS_RESPONSE`, `personas_list`) disarm the timer and restore the connected pill.
  - `togglePersonaDropdown()` and `connect()` delegate to `queryVaultPersonas()`; socket error/close paths call `markPersonaBridgeOffline()` when a query is active.
- [x] **29.2 Mobile Mesh/Bridge Health Indicator (`templates/_nav.html`, `static/js/relay_pool.js`):**
  - Compact `lg:hidden` pill with `#mobile-bridge-dot` + `#mobile-bridge-label` ("Mesh") in the nav top-row controls.
  - `updateMobileBridgeHealth(online)` updates dot (`bg-emerald-500`/`bg-amber-500`) and label ("Online"/"Manual"); exposed as `window.updateMobileBridgeHealth`.
  - `relay_pool._updateHealthUI()` drives it from relay counts; `bridge_client` drives it from bridge socket open/close and offline path.
- [x] **29.3 Test Event Reconciliation (`apps/core/tests/test_feed.py`):**
  - Synthetic events in `ProcessIntoFeedTest` now carry non-empty content (`content="valid note"`, reactions `content="+"`, votes `content="poll-vote"`, 1063 `content="file attachment"`) so `is_renderable_note` keeps them.
  - `detect_language` (`apps/core/nip10.py`): replaced the strict pure-ASCII "return en" gate with stop-word scoring using `min_score` of 1 for accented/marker prose and 2 for accent-free prose (keeps URL/code English posts as 'en', detects accent-free French/Italian/Spanish like "Bonjour tout le monde").
- [x] **29.4 New View Tests (`apps/core/tests/test_views.py`):**
  - `test_standard_header_renders_persona_dropdown_with_timeout_container`: asserts `#persona-list-container`, `#persona-bridge-status`, and the "Querying local vault personas..." state.
  - `test_nav_renders_mobile_health_indicator`: asserts `#mobile-bridge-dot` and `#mobile-bridge-label`.
- [x] **29.5 TODO.md Updated:** Documented Phase 29 implementation — **Done 2026-09-01**

### Phase 30: NIP-04 End-to-End DM Cryptography & Session Decryption Pipeline
- [x] **30.1 Bridge NIP-04 Crypto Contract (`static/js/bridge_client.js`):**
  - `nip04Encrypt(recipientPubkeyHex, plaintext)` + `nip04Decrypt(senderPubkeyHex, encryptedPayload)` + `_nip04BridgeRequest()` RPC helper.
  - When the bridge socket (`ws://127.0.0.1:9001` / `wss://home.iyou.me:9001`) is OPEN, dispatches `NIP04_ENCRYPT`/`NIP04_DECRYPT` frames (`peer_pubkey` + `content`) and awaits the correlated `NIP04_ENCRYPT_RESPONSE` (`encrypted_payload`) / `NIP04_DECRYPT_RESPONSE` (plaintext) per-peer.
  - Web Crypto fallback helpers (`nip04WebCryptoEncrypt`/`nip04WebCryptoDecrypt`, `nip04WebCryptoKey`, `nip04LocalIdentityHex`, `bytesToBase64`/`base64ToBytes`, `isHex64`): AES-256-CBC, 16-byte IV, output `${base64Ciphertext}?iv=${base64Iv}` per NIP-04. Decrypt failures fall back to the clean `"[Encrypted Message — Open Enclave to Decrypt]"` string.
- [x] **30.2 Floating Chat Encrypt + Decrypt Wiring (`static/js/floating_chat.js`):**
  - `sendViaNostr()` now prefers `bridge.nip04Encrypt` (async) over legacy `nip04_encrypt`/`window.nip04_encrypt`.
  - `sendDockedMessage()` resolves the peer target early and renders a subtle `🔒 ` prefix on optimistic Nostr bubbles (Kind 4 `["p", peerHex]` still signed via `bridgeClient.signEvent()` and broadcast across relays).
  - Incoming Kind 4 listener: decrypts via `await window.bridgeClient.nip04Decrypt(ev.pubkey, ev.content)` (with legacy `window.nip04_decrypt` fallback) before dispatching the bubble.
- [x] **30.3 Encryption Badge Containers (`static/js/floating_chat.js`, `templates/includes/_floating_chat_dock.html`):**
  - Extracted `buildDockedChatWindowHtml(peerId, peerName, peerAvatar)`; pane header now shows `<span class="text-[10px] text-emerald-400 ...">🔒 NIP-04 E2EE Session</span>` for Nostr peers and `<span class="text-[10px] text-violet-400 ...">⚡ Sovereign Enclave Mesh</span>` for XMPP mesh peers.
  - Dock template gained `#floating-dock-security-status` with `#dock-security-badge-e2ee` + `#dock-security-badge-mesh` containers (same copy) in the roster footer.
- [x] **30.4 New Tests (`apps/core/tests/test_chat_engine.py`):**
  - `test_chat_view_context_includes_nip04_bridge_contracts`: asserts `bridge_client.js` carries `NIP04_ENCRYPT`/`NIP04_DECRYPT`/`nip04Encrypt`/`nip04Decrypt`/`encrypted_payload` and `floating_chat.js` carries `nip04Encrypt`/`nip04Decrypt`/`kind: 4` + both banner strings.
  - `test_floating_dock_template_renders_encryption_badge_containers`: renders the authenticated dashboard and asserts `#docked-chat-windows`, `#floating-dock-security-status`, `#dock-security-badge-e2ee`, `#dock-security-badge-mesh`, and both security banner strings.
- [x] **30.5 TODO.md Updated:** Documented Phase 30 implementation — **Done 2026-09-01**

### Pre-Flight Hotfix Pass
- [x] **HOTFIX-1 `static/js/feed_interactions.js` — Syntax Halt Repair:** Removed the orphaned duplicate `.catch(...).finally(...)` block (was `prevBtnHtml`) in the translate handler that made `node --check` fail with `Unexpected token '.'`; `node --check` passes and `window.handleSignedEvent` (declared L92, exported L205, consumed in `feed.html:259`) resolves correctly.
- [x] **HOTFIX-2 `static/js/circle_feed_filter.js` — Circle Transition Toasts:** Added `CIRCLE_TOASTS` map (global → "Switched to Global Mesh", following → "Filtered to Following (L1 Contacts)", inner → "Filtered to Inner Circle (L0 Enclave Peers)", mutual → "Filtered to Mutual Friends", iyou → "Filtered to iyou Sovereign Mesh"; all type "info") fired only on real circle transitions, suppressed via `suppressCircleToasts = true` until hydration completes in `initCircleFeedFilter`.
- [x] **HOTFIX-3 `templates/includes/_feed_right_rail.html` — Sovereign Creator Profile Routing:** Creator rows now wrap their avatar/name/badge/handle block in `<a href="{% url 'profile' ... %}" ...>` so the whole row is clickable with an active/hover state; the nav identifier is built via `{% with profile_id=creator.handle|cut:"@" %}` (leading `@` stripped so the `^profile/[a-zA-Z0-9_@.-]+/?$` route always resolves); added `id="sovereign-creators-list"` to the container; Follow button stays outside the anchor with `data-follow-target`/`data-follow-petname`.
- [x] **HOTFIX-4 `templates/dashboard.html` — Phantom Toast & Mount Audit:** The legacy `#toast` element used the `.hide` class which has **no CSS definition**, so it rendered visibly on every load; added Tailwind `hidden` so server HTML ships it hidden (real toasts flow through `toast_manager.js` → `window.showToast`). Audited: no unconditional `showToast()`/`alert()` runs on `DOMContentLoaded` (load-time handler only does switchTab/loadRelays/loadFeedHygienePreferences/renderModerationRoster/updatePreview/initDeckManager) and `bridge_client.connect()` performs no mount-time persona/reset dispatch (`switchPersona` fires only on explicit header clicks) — nothing to remove there.
- [x] **HOTFIX-5 Regression Tests (`apps/core/tests/test_views.py`, `DashboardProfileTest`):**
  - `test_sovereign_creators_render_valid_profile_links`: public verified `UserLinkDeck` with a leading-`@` handle renders under `#sovereign-creators-list` with `href="/profile/verified_creator"`, display name, `@handle` line, and avatar.
  - `test_dashboard_toast_is_hidden_by_default`: authenticated dashboard response ships `#toast` with the `hidden` class in its opening tag and no inline `alert()` calls.
  - Full `DashboardProfileTest` (15 tests) green. Note: the `creator.npub|default:creator.pubkey` fallback chain from the original spec cannot exist — `UserLinkDeck` has no such attributes and Django raises `VariableDoesNotExist` resolving them inside `{% url %}`/`{% with %}` arg resolution; since the queryset is `exclude(handle="")`, `handle|cut:"@"` is the guaranteed route-safe identifier.
- [x] **HOTFIX-6 Validation:** `/usr/local/Cellar/node/26.7.0/bin/node --check` on both edited JS files, CSS build via direct tailwind CLI, `manage.py check`, full `apps.core` suite, `ruff check .` — all clean — **Done 2026-09-01**

### Phase 31: Blossom Fallback Cascade, Relay Auto-Failover & Sovereign Graph Backup
- [x] **31.1 Multi-Source Blossom Fallback Cascade (`static/js/feed_interactions.js`):**
  - `window.handleMediaError(imgEl, sha256)` walks a fixed mirror cascade — 1. Local Loopback Daemon `http://127.0.0.1:9002/<sha>` → 2. Sovereign CDN `https://cdn.iyou.me/<sha>` → 3. Public Fallback Blossom Node `https://nostr.download/<sha>` — reading the current tier from `data-fallback-tier` (default 0), advancing a tier per failed probe, and rendering the compact placeholder `[⚠️ Media Unavailable on Mesh]` once all mirrors exhaust.
  - `mediaOnErrorAttr(media)` attaches `onerror="window.handleMediaError(this, '<sha>')"` to card `<img>` tags whenever a 64-hex NIP-94 `x`/`sha256` hash is present; `extractMediaFromNote` now carries the Kind 1063 `x` tag into `media.hash` for client-side extraction.
- [x] **31.2 Relay Health Auto-Quarantine & Failover (`static/js/relay_pool.js`, `templates/includes/_feed_right_rail.html`):**
  - `QUARANTINE_THRESHOLD = 3`; `broadcast()` calls `_recordBroadcastFailure(url)` on each WebSocket drop/timeout/error, and once a relay exceeds 3 consecutive failures it is transitioned `ONLINE → QUARANTINED`, demoted from the active read/write pool, and an unquarantined fallback from `BOOTSTRAP_RELAYS`/`DEFAULT_RELAYS` is added and probed (`_pickFallbackRelay`/`_addRelay`).
  - `getWriteRelays()`/`getReadRelays()` skip quarantined relays; `renderDiagnosticsList` shows a slate pulsing dot + "quarantined" latency; `_updateHealthUI` reports "Mesh Degraded (N Quarantined)" / "Mesh Quartantining Relays... (Reconnecting)" and `getActiveRelayCount` now tracks quarantined count.
  - `window.retryQuarantinedRelays()` re-probes every quarantined relay, restoring read/write on an online result; surfaced as a `↻ Retry Quarantined Relays` button in the mesh right-rail diagnostics drawer (`#relay-retry-quarantined`).
- [x] **31.3 Sovereign Graph Disaster Snapshot Export & Import (`apps/core/views.py`, `apps/core/urls.py`, `templates/dashboard.html`):**
  - `@login_required api_backup_export`: serializes the user's `UserLinkDeck` + claimed handle + `UserLinkItem`s plus the client-local graph (contacts/relays/circles/muted) into a versioned snapshot (`BACKUP_VERSION = 1`); returns a downloadable `Content-Disposition: attachment; filename="iyou_wun_backup_<timestamp>.json"`.
  - `@csrf_exempt @login_required api_backup_import`: accepts a JSON body or multipart `backup` field, validates schema (requires deck/contacts/relays), and restores the deck + link items inside a single `transaction.atomic()` block (409 on handle conflict); returns `{ "success": true, "restored_contacts": N, "restored_relays": M }` for client-side localStorage reconciliation.
  - Registered `api/backup/export/` + `api/backup/import/`; the Account & Key Info tab gained the `#sovereign-backup` card with an `📥 Export Mesh Snapshot` link, a JSON file-input dropzone + `📤 Restore from Backup` submit (form handled via `setupBackupRestore()`, which rehydrates `wun_contacts`/`wun_relays`/`wun_circles`/`wun_muted_pubkeys` in localStorage and reloads on success).
- [x] **31.4 Tests (`apps/core/tests/test_views.py`, `BackupGraphTest`):**
  - `test_api_backup_export_requires_auth`: anonymous GET returns 302/401.
  - `test_api_backup_export_returns_valid_json_schema`: validates `version`/`exported_at`/`user`/`deck`/`contacts`/`relays`/`circles`/`muted` keys + deck handle/items serialization.
  - `test_api_backup_import_restores_user_graph`: round-trip rehydration of deck, handle, and link items from a mock snapshot (asserts `restored_contacts`/`restored_relays` counts).
  - `test_dashboard_renders_backup_recovery_controls`: asserts `#sovereign-backup`, the export href, and `#backup-restore-form` render in the authenticated dashboard.
  - Plus JS contract tests `test_feed_interactions_carries_blossom_fallback_cascade` and `test_relay_pool_carries_auto_quarantine_contract`.
- [x] **31.5 Validation:** `node --check` on both edited JS files, CSS build via direct tailwind CLI, `manage.py check`, full `apps.core` suite, `ruff check .` — all clean — **Done 2026-09-01**

### Phase 32: Persona Session Re-Anchoring & Multi-Deck Isolation
- [x] **32.1 Session Re-Anchoring Endpoint (`apps/core/views.py`, `apps/core/urls.py`):**
  - `api_persona_switch(request)`: POST JSON `{"did", "persona_name", "level"}` gated by an authenticated session (unauth returns 401 pending a challenge-signature flow). Resolves/provisions `User(username=did)` with an unusable password (+ honors an optional `account_tier` extension column), provisions an isolated `UserLinkDeck` per DID via `claim_handle` with a DID-derived handle, then `login(request, target_user, ModelBackend)` and caches `session["active_persona_name"]`/`session["active_persona_level"]`. Returns `{"success", "did", "persona_name", "level", "handle"}`.
  - Registered route `api/auth/persona-switch/` (`api_persona_switch`).
- [x] **32.2 Bridge Alignment & Auto Re-Anchoring (`static/js/bridge_client.js`):**
  - New `handlePersonaChanged(profile)` called from the `_handleMessage` persona-activation branch (`profile_sync`/`profile_activated`/`active_profile_changed`/`SET_ACTIVE_PERSONA_RESPONSE`): compares `profile.did` against the header-injected `window.CURRENT_SESSION_DID`; on divergence POSTs `/api/auth/persona-switch/` with CSRF header, updates `CURRENT_SESSION_DID`, dispatches `persona:session-reanchored`, toasts the re-anchor, and reloads the page on every route except `/dashboard`.
- [x] **32.3 Header Display Hierarchy (`apps/core/context_processors.py`, `templates/includes/_standard_header.html`):**
  - `user_identity` now renders `user_display_label` via a priority chain — authenticated deck `@handle` > `active_persona_name (L{level})` > `Primary Identity (L1)` > `{username[:16]}... (L{level})` — plus `current_session_did` (legacy `user_pubkey_hex`/`user_npub`/`user_handle`/`user_profile_url` preserved).
  - `_standard_header.html` ships `<script>window.CURRENT_SESSION_DID = "{{ current_session_did|escapejs }}";</script>` and the `#active-persona-display-name` span renders `{{ user_display_label }}`.
- [x] **32.4 Smooth Dashboard Re-Anchor (`templates/dashboard.html`):**
  - Identity block got `#dashboard-deck-handle` + `#dashboard-user-did` ids; a `persona:session-reanchored` listener rewrites them from the switch response so the dashboard re-renders its deck identity without dropping the bridge socket (no full reload).
- [x] **32.5 Tests (`apps/core/tests/test_views.py`, `PersonaSessionSwitchTest`):**
  - `test_api_persona_switch_updates_session_user`: swapping DIDs re-anchors `request.user`, provisions an isolated deck per DID, leaves the original handle untouched on round-trip.
  - `test_api_persona_switch_gates_method_and_did`: 405 on GET, 400 on non-DID target, 401 anonymous.
  - `test_header_display_hierarchy_rules`: handle precedence, persona+level fallback, generic L1 placeholder, L2 truncated-DID burner formatting.
  - `test_header_injects_current_session_did`: asserts `window.CURRENT_SESSION_DID` is rendered server-side.
- [x] **32.6 Validation:** `node --check` on `bridge_client.js`, CSS build via direct tailwind CLI, `manage.py check`, full `apps.core` suite, `ruff check .` — all clean — **Done 2026-09-01**

### Phase 33: Relay Switchboard Toggles, Local Relay Diagnostics, Media Proxy & Documentation Sync
- [x] **33.1 Dashboard Relay Toggle Switches (`templates/includes/_relay_manager.html`, `static/js/relay_pool.js`, `templates/dashboard.html`):**
  - Each Sovereign Switchboard row renders an accessible peer-checked toggle (`<label>` + `<input type="checkbox" class="sr-only peer relay-toggle-checkbox" data-relay-url="…" onchange="toggleRelayState('…', this.checked)">`) — server-rendered from the new `relay_objs` dashboard context and re-rendered identically by `renderRelayList()` after `/api/relays` refreshes; `{% if relay.enabled != False %}checked{% endif %}` semantics preserved (plain strings back-compat default to enabled).
  - `window.toggleRelayState(relayUrl, isEnabled)` persists the Phase 33 object schema `[{url, enabled, read, write}]` under `wun_custom_relays` (with a string-only `wun_relays` mirror for legacy consumers), gracefully closes/demotes a disabled relay from every read/write broadcast & subscription loop (plus the health/diagnostics UI) and reconnects + re-probes on enable; `persistRelays()` mirrors both stores; toast `Relay <url> enabled/disabled`.
  - `saveRelays()` writes object schema + URL-string list, `addRelay()`/`removeRelay(url)` operate on `data-relay-url`, and `loadRelays()` merges persisted `enabled` flags from `wun_custom_relays` over the server list.
- [x] **33.2 Local Relay Retained + Diagnostics Styling (`static/js/relay_pool.js`, `templates/includes/_feed_right_rail.html`):**
  - The local loopback relay (`ws://127.0.0.1:9003`) is ALWAYS retained in the pool/diagnostics list regardless of origin; over HTTPS the plain-`ws://` socket is exposed as `127.0.0.1:9003` with a `[Local]` chip and status `Local Enclave (Desktop/WSS)` and is never probed/broadcast (`isMixedContentRelay` guard) to avoid browser Mixed Content failures.
  - Diagnostics restored: emerald/amber/rose status dots, latency indicator, hostname, conditional `[R]`/`[W]` scope chips, `[Local]` chip, disabled state (grey dot + "disabled"), quarantined rose; right-rail drawer gained an `R / W / [Local]` legend row.
- [x] **33.3 Resilient Media Upload Proxy (`apps/core/views.py` `api_blossom_upload_proxy`, `apps/core/urls.py`, `static/js/feed_interactions.js`):**
  - Upgraded server-side proxy accepts multipart `file` or raw body and forwards to the configured Blossom upstream (`http://127.0.0.1:9002/upload` local loopback → `https://cdn.iyou.me/upload` CDN fallback) using an unverified TLS context (`ssl.CERT_NONE`, `check_hostname=False`) so staging cert issues never block uploads; returns `{"success": true, "url", "sha256", "size", "type", "forwarded"}` with graceful degradation.
  - New route alias `api/blossom/proxy/` (`api_blossom_proxy`); `api/media/upload/` name preserved. `uploadViaServerProxy()` tries `/api/blossom/proxy/` then `/api/media/upload/`; `handleMediaSelected()` renders the SHA-256 attachment card without throwing on direct-upload `TypeError`/Load-failed/SSL errors.
- [x] **33.4 Documentation Sync & Tests:**
  - `docs/WUN_DEVELOPER_GUIDE.md` gained a **Phase 20–32 Delivery Summary** (dual-engine chat + NIP-04, NIP-18/27 quotes, NIP-05/NIP-02 pipeline, directory search & NIP-50 triage, language heuristics/translation, trending Counter, noise gate & beacon suppression, Blossom cascade + relay quarantine, persona re-anchoring).
  - Tests: `test_feed_interactions_carries_phase33_proxy_fallback`, `test_relay_pool_carries_phase33_toggle_schema`, `test_dashboard_renders_relay_switchboard_toggles`, plus `test_upload_proxy_success_returns_phase33_schema`, `test_blossom_proxy_route_accepts_uploads`, and `test_upload_proxy_uses_unverified_ssl_context_for_https_upstream`.
- [x] **33.5 Validation:** CSS build via direct tailwind CLI, `manage.py check`, full `apps.core` suite, `ruff check .`, `node --check` on `relay_pool.js`/`feed_interactions.js`/`dashboard.html` — all clean — **Done 2026-09-01**

### Phase 34: Instant Shell Architecture, Progressive Stream Hydration & Scoped Avatar Brand Protection
- [x] **34.1 Scoped Avatar Brand Protection (`static/img/mesh_avatar_default.svg`, `templates/includes/_thread_post.html`, `_quote_card.html`, `_feed_right_rail.html`, `static/js/feed_interactions.js`):**
  - Added a neutral slate SVG globe milestone (`mesh_avatar_default.svg`) — slate-700 sphere (`#64748b` grid on `#1e293b` radial) with mesh-network node dots/lines — representing an unverified external mesh relay peer.
  - Avatar fallbacks are now scoped strictly by origin in every note renderer: verified `author_avatar` wins; otherwise iyou-native/sovereign peers (`note.is_iyou_native`) get the protected `iyou_symbol.png` violet-brand mark, and every other external peer gets the neutral `mesh_avatar_default.svg` globe.
  - Client-side `resolveAvatarUrl(note)` in `feed_interactions.js` mirrors the same server-side scoping inside `buildCardHtml()` with matching slate/violet ring/padding classes.

- [x] **34.2 Instant Shell & Progressive Stream Hydration (`templates/feed.html`, `apps/core/views.py`, `static/js/feed_interactions.js`):**
  - `feed.html` renders `#feed-skeleton-container` (3 pulsing placeholder cards mimicking headers/text/action bars) above an empty `#feed-container` flagged `data-hydrate="true"` whenever the stream has no server-rendered roots.
  - `FeedView.get_context_data()` bounds the initial render to `INITIAL_FEED_SHELL_TIMEOUT` (1.2s) by threading a wall-clock `deadline` through `relay_req()` (hard per-call cap + skip past deadline), `fetch_unified_feed()`, `attach_social_counts()`, `attach_quoted_notes()`, `fetch_contact_pubkeys()`, and `fetch_thread()` — fast relays still yield a full server-rendered feed; slow/blackhole relays degrade to the instant shell instead of stalling the HTTP worker. `?async=1` requests the bare shell immediately with no relay I/O at all.
  - `fetchInitialFeedStream()` runs on `DOMContentLoaded` when `#feed-container` carries `data-hydrate`; it pulls the first batch from `/api/feed/` (the dedicated async payload supplier), removes the skeleton, hydrates cards via `appendNoteToFeed()`, re-runs `trustLens.scan()`, `hydrateLocalTimestamps()`, clamping, and re-arms the infinite-scroll pagination observer — with an error path that clears the skeleton rather than hanging.

- [x] **34.3 Tests & Docs:**
  - `test_avatar_fallback_uses_iyou_symbol_only_for_native_peers`, `test_avatar_fallback_uses_mesh_default_for_external_peers`, `test_feed_renders_skeleton_placeholder_markup`, `test_feed_async_shell_skips_blocking_relay_io`, `test_feed_serializes_avatar_resolution_with_client_side_pool`; updated strict `relay_req` mocks for the new `timeout`/`deadline` kwargs.
- [x] **34.4 Validation:** CSS build via direct tailwind CLI, `manage.py check`, full `apps.core` suite, `ruff check .`, `node --check` on `feed_interactions.js` — all clean — **Done 2026-09-01**

### Phase 35: Profile Hero Avatar Origin Scoping, Adaptive Sticky Right Rail & NIP-36 Shield Scanner
- [x] **35.1 Profile Hero Avatar Origin Scoping (`apps/core/views.py`, `templates/profile.html`):**
  - `ProfileView.get_context_data()` now computes and injects `context["is_iyou_native"]` from `is_owner` OR an owned/`UserLinkDeck` handle on the target OR a `UserLinkDeck` whose user username matches the target pubkey hex.
  - The avatar hero block proxies the fallback strictly by origin: verified `profile.picture` wins; iyou-native creators render the protected `iyou_symbol.png` violet-brand mark; unverified external mesh peers render the neutral `mesh_avatar_default.svg` globe (slate ring/padding) — mirroring the Phase 34 feed scoping.
- [x] **35.2 Adaptive Sticky Right Rail (`templates/feed.html`, `static/css/input.css`):**
  - The right rail `<aside>` became `sticky top-4 max-h-[calc(100vh-2rem)] overflow-y-auto no-scrollbar`, so the Discovery Rail scrolls within its own pane and stays locked into the viewport without native OS scrollbars.
  - Added the `.no-scrollbar` utility (`scrollbar-width: none; -ms-overflow-style: none; &::-webkit-scrollbar { display: none; }`) to `input.css`.
- [x] **35.3 Heuristic NIP-36 Sensitive Content Scanner (`apps/core/nip10.py`):**
  - `detect_content_warning(event)` still parses standard NIP-36 tags (`content-warning`, `nsfw`, `sensitive`, `nudity`, plus `l`/`label` namespaces) and now additionally scans raw `content` via new `EXPLICIT_CONTENT_REGEXES` heuristics (illicit/adult/spam patterns like onlyfans, nsfw, nude/nudity, webcam, escort, viagra, drug terms).
  - When matched it annotates the event in place with `event["has_content_warning"] = True` and `event["content_warning_reason"]`; the enrichment emitters surface it as `note.has_content_warning` / `note.warning_reason` (`content_warning_reason` fallback honored) so `circle_feed_filter.js` blurs/hides flagged cards per `wun_nsfw_pref`.
- [x] **35.4 Tests & Docs:**
  - `test_profile_hero_avatar_uses_mesh_default_for_external_peers` (external `npub` renders the globe), `test_profile_hero_avatar_uses_iyou_symbol_for_native_creators` (sovereign user renders the brand mark), and `test_detect_content_warning_flags_nip36_and_heuristics` (NIP-36 tag parsing + heuristic regex + in-place event annotation + end-to-end enrichment).
  - Existing `test_profile_page_uses_iyou_symbol_when_profile_has_no_picture` migrated to `test_profile_hero_avatar_uses_mesh_default_for_external_peers` (avatarless external peers no longer receive the protected brand mark).
- [x] **35.5 Validation:** CSS build via direct tailwind CLI, `manage.py check`, full `apps.core` suite (434 passing), `ruff check .` — all clean — **Done 2026-09-01**

### Phase 36: Global Bridge Client Ingestion, CSRF Persona-Switch Hardening & Chat Import Fix
- [x] **36.1 Hoist `bridge_client.js` to `base.html` (`templates/base.html`, `templates/feed.html`, `templates/dashboard.html`):**
  - `bridge_client.js` is now injected globally in `base.html` right after `toast_manager.js`, so a single singleton `TauriBridgeClient` serves every view (feed, dashboard, gallery, chat, profile) with no duplicate WebSocket instances.
  - `base.html` also renders `window.CURRENT_SESSION_DID` so all sub-pages carry the active session identity context (guarded with `||` to preserve the earlier `_standard_header.html` value).
  - Removed the redundant per-page `<script src="...bridge_client.js">` tags from `feed.html` and `dashboard.html`; each page keeps its inline `window.TAURI_SIGNING_BRIDGE` (bridge WebSocket) so `getBridgeUrl()` resolves exactly as before.
- [x] **36.2 CSRF Cookie & Persona-Switch Hardening (`apps/core/views.py`, `static/js/bridge_client.js`):**
  - `api_persona_switch` is now `@csrf_exempt` so the local bridge can re-anchor the session even when the `csrftoken` cookie is absent on a first connect (POST guarded by `request.user.is_authenticated`).
  - App-shell views (`FeedView`, `ChatView`, `GalleryView`, `ProfileView`) plus the `dashboard` function are decorated with `ensure_csrf_cookie` so every shell response seeds the CSRF cookie for subsequent fetch mutation endpoints.
  - Added `getCsrfToken()` fallback in `bridge_client.js` — prefers the `csrftoken` cookie, else a `csrfmiddlewaretoken` input, requiring `>= 32` chars; `handlePersonaChanged` now uses it and it's exported as `window.getCsrfToken`.
- [x] **36.3 Converse.js ESM Syntax Fix (`templates/chat.html`):**
  - Replaced the broken `import converse from '...converse.min.js'` (UMD bundle has no default ESM export → SyntaxError) with the classic UMD `<script src="...converse.min.js">` build in `extra_head` and an ES-module-safe `const converse = window.converse || self.converse;` bootstrap.
- [x] **36.4 Tests & Docs:**
  - `GlobalBridgeClientContractTest`: `test_base_loads_bridge_client_globally_and_session_did`, `test_feed_and_dashboard_do_not_duplicate_bridge_script`, `test_persona_switch_accepts_post_without_csrf_token` (enforce_csrf_checks stub), `test_bridge_client_carries_csrf_fallback_and_global_session_did`.
  - Updated `test_chat_renders_script_type_module` (UMD/`window.converse`) and hardened `test_chat_jid_uses_pubkey_hex` to assert the rendered pubkey-based JID without the brittle `split("jid:")[1]` heuristic that the base.html session-DID injection disturbed.
- [x] **36.5 Validation:** `node --check static/js/bridge_client.js`, `manage.py check`, full `apps.core` suite (438 passing), `ruff check .` — all clean — **Done 2026-09-01**

### Phase 36 (Cont): Relay Switchboard Sync, Instant Profile Shell, Empty State Fix & NIP-05 Endpoint
- [x] **36.6 Relay Switchboard Sync (`static/js/feed_interactions.js`, `apps/core/views.py`):**
  - Added `getActiveRelays()` helper function to read enabled relay URLs from `localStorage` (`wun_custom_relays`) or `window.relayPool.getRelays()`.
  - Modified `fetchInitialFeedStream()` and `loadMoreNotes()` to serialize enabled relay URLs and append as `&relays=` parameter to `/api/feed` requests.
- [x] **36.7 Empty State Teardown (`static/js/feed_interactions.js`):**
  - Enhanced `appendNoteToFeed()` to explicitly add `hidden` class to `#feed-empty-state` and `#circle-empty-state` elements when note cards are rendered.
- [x] **36.8 Client Relays Parameter Support (`apps/core/views.py`):**
  - Updated `api_feed()` to parse `request.GET.get("relays")` JSON list, validate relay URLs, and pass to `relay_req(filter_obj, relay_urls=client_relays)`. Falls back to default relays when parameter is absent or empty.
- [x] **36.9 Instant Profile Shell (`apps/core/views.py`, `templates/profile.html`):**
  - Refactored `ProfileView` to resolve local metadata immediately without blocking on remote relay fetches.
  - Returns profile shell immediately with `hydrate_profile=True` flag, empty `posts`/`replies`/`media_assets` for client-side async loading.
  - Implemented `api_profile_notes()` endpoint at `/api/profile/<str:identifier>/notes/` with 2.0s deadline, returns `{"notes": [...], "has_more": bool}`.
- [x] **36.10 Profile Shell Hydration (`templates/profile.html`):**
  - Added 3 pulsing skeleton cards in posts container while notes load.
  - Added client-side fetch script calling `api_profile_notes` on DOMContentLoaded, swapping skeleton cards for rendered notes via `appendNoteToFeed()`.
- [x] **36.11 Z-Index Stacking Fix (`templates/includes/_standard_header.html`):**
  - Updated `#persona-switcher-dropdown` to include `z-50` and `overflow-hidden` classes with `mt-2` spacing for Layer 1 dropdown isolation.
- [x] **36.12 NIP-05 Endpoint Enhancement (`apps/core/views.py`, `apps/core/urls.py`):**
  - Existing `nip05_well_known()` endpoint already supports `?name=<handle>` resolution with CORS header, returns proper JSON mapping.
  - Verified URL registration at `.well-known/nostr.json`.
- [x] **36.13 Phase 36 Tests (`apps/core/tests/test_views.py`):**
  - Added `Phase36RelaySyncTest`, `Phase36NIP05EndpointTest`, `Phase36ProfileNotesAPITest` with comprehensive test coverage.

### Phase 37: Automated Handle-to-NIP-05 Derivation, Global Script Isolation & Stacking Context Repair
- [x] **37.1 Automated Handle-to-NIP-05 Derivation (`apps/core/models.py`):**
  - Implemented `UserLinkDeck.save()` method to automatically derive NIP-05 address from handle and discriminator: `handle@iyou.me` or `handle_discriminator@iyou.me`.
  - Normalizes handles to lowercase and strips `@` symbols for consistency.
- [x] **37.2 Canonical NIP-05 in Profile Save (`apps/core/views.py`, `templates/dashboard.html`):**
  - Updated `api_save_profile()` to use automatically derived NIP-05 from UserLinkDeck, ignoring client-provided NIP-05 values.
  - Removed manual NIP-05 text input from dashboard in favor of automated badge display.
- [x] **37.3 Discriminator Lookup Support (`apps/core/views.py`):**
  - Enhanced `nip05_well_known()` to handle discriminator format lookups (`name.replace('_', '[') + ']'`), enabling resolution of handles like `alice_2` to decks with discriminator=2.
- [x] **37.4 Automated NIP-05 Badge UI (`templates/dashboard.html`):**
  - Replaced manual NIP-05 input with automated badge showing `🏷️ <deck.nip05>` with "ACTIVE" status indicator.
  - Shows "Claim handle to activate @iyou.me" when no NIP-05 is available.
- [x] **37.5 Global Script Hoisting (`templates/base.html`):**
  - Moved `toast_manager.js`, `bridge_client.js`, `relay_pool.js`, `theme.js` completely outside of `{% block extra_js %}` with explicit comments.
  - Added `{% block.super %}` to child template extra_js blocks in `dashboard.html`, `chat.html`, `profile.html`, `feed.html`.
- [x] **37.6 Stacking Context Repair (`templates/includes/_standard_header.html`, `templates/_nav.html`):**
  - Added `relative z-30` to Layer 1 header element for explicit stacking context.
  - Retained `z-50` on `#persona-switcher-dropdown` for dropdown isolation.
  - Added `relative z-10` to Layer 2 toolbar container (`<nav>` in `_nav.html`) to ensure persona menu opens cleanly over search toolbar.
- [x] **37.7 Bridge Protocol Normalization (`static/js/bridge_client.js`):**
  - Confirmed `getBridgeUrl()` already respects protocol: `wss://home.iyou.me:9001/` for HTTPS, `ws://127.0.0.1:9001/` for HTTP.
  - Added `credentials: 'same-origin'` to persona switch POST request.
  - Wrapped persona switch fetch call in `try...catch` with clean warning logging.
- [x] **37.8 Phase 37 Tests (`apps/core/tests/test_deck.py`, `test_views.py`):**
  - `Phase37NIP05DerivationTest`: `test_user_link_deck_automatically_derives_nip05_on_save`, `test_user_link_deck_derives_discriminator_nip05`, `test_user_link_deck_updates_nip05_on_handle_change`, `test_user_link_deck_handles_mixed_case_handle`, `test_user_link_deck_strips_at_symbol`.
  - `Phase36NIP05EndpointTest`: Added `test_nip05_well_known_resolves_discriminator_format`.
  - `Phase37GlobalScriptTest`: `test_base_html_renders_global_bridge_scripts_on_all_views`.

### Phase 38: [ ⚡ iyou ] Default Landing Circle & Feed View
- [x] **38.1 Backend Route & View Defaults (`apps/core/views.py`):**
  - Updated fallback logic for `circle` in `FeedView.get_context_data()` and `FeedView.get()` to default to `"iyou"`.
  - Added `selected_circle` context variable.
  - Verified and enforced `fetch_text_notes()` and `api_feed()` default to `authors=get_iyou_pubkeys()` when no circle is specified.
- [x] **38.2 Layer 2 Nav & Client Initialization (`templates/_nav.html`, `static/js/circle_feed_filter.js`, `templates/feed.html`):**
  - Updated `#circle-filter-group` buttons in `_nav.html` to render `data-circle="iyou"` active with active pill styling and `data-circle="global"` inactive on initial load.
  - Set default scope badge to `IYOU ECOSYSTEM`.
  - Updated `static/js/circle_feed_filter.js` to resolve `initialCircle = urlParams.get('circle') || 'iyou'`.
  - Scanned initial cards with `checkCircleMatch(card, initialCircle)` and updated empty states in feed template and JS filter for the `iyou` ecosystem.
- [x] **38.3 Verification & Unit Tests (`apps/core/tests/test_views.py`, `apps/core/tests/test_feed.py`):**
  - Added contract tests verifying `/feed` and `/api/feed` without parameters default to `selected_circle == 'iyou'` and invoke `get_iyou_pubkeys()`.
  - Rebuilt CSS and verified full test suite passes.

### Phase 39: Wire Direct Message Deep-Links to Docked Chat Interface
- [x] **39.1 Profile & Link Deck Message Actions (`templates/profile.html`, `templates/link_deck.html`):**
  - Added `.action-btn-direct-message` with `data-chat-target-pubkey`, `data-chat-target-did`, and `data-chat-target-handle` to `profile.html` and `link_deck.html` for authenticated non-owners.
  - Embedded floating chat dock partial and script in `link_deck.html`.
- [x] **39.2 Floating Chat Dock Deep-Link Handler (`static/js/floating_chat.js`, `templates/includes/_floating_chat_dock.html`):**
  - Exposed `window.openDirectMessage(targetPubkey, targetHandle)` and `window.setActiveChatPeer(targetPubkey, targetHandle)`.
  - Added `#floating-chat-dock` ID to master dock container and `#dock-chat-input` to input element.
  - Bound global document click delegation for `.action-btn-direct-message` buttons.
- [x] **39.3 Verification & Unit Tests (`apps/core/tests/test_views.py`, `apps/core/tests/test_deck.py`):**
  - Added `test_profile_renders_message_button_for_authenticated_viewer` covering authenticated peer, profile owner, and unauthenticated viewer.
  - Added `test_link_deck_renders_message_button_for_authenticated_viewer` covering authenticated peer, link deck owner, and unauthenticated viewer.

### Phase 40: Implement Link Deck JSON Content Negotiation
- [x] **40.1 Content Negotiation in `LinkDeckView` (`apps/core/views.py`):**
  - Added detection of `Accept: application/json` and `?format=json`.
  - Serialized resolved deck attributes, NIP-05, profile object, and active link items as structured JSON with `Access-Control-Allow-Origin: *`.
  - Handled missing or non-public decks with `{"error": "Deck not found"}` and status 404.
- [x] **40.2 Unit Tests (`apps/core/tests/test_deck.py`):**
  - Added `test_link_deck_json_content_negotiation_accept_header` asserting 200, Content-Type, payload keys, and CORS header.
  - Added `test_link_deck_json_format_query_parameter` asserting 200 with `format=json`.
  - Added `test_link_deck_json_returns_404_for_missing_handle` asserting 404 with JSON error.
  - Added `test_link_deck_json_content_negotiation_discriminated_handle`.

### Phase 41: NIP-02 Follow Pipeline & Kind 3 Contact Management
- [x] **41.1 Backend Endpoint (`apps/core/views.py`, `apps/core/urls.py`):**
  - Implemented `api_contacts_follow` endpoint taking `{"target_pubkey": "<hex>", "action": "follow"|"unfollow"}`.
  - Validated 64-char hex pubkey and self-follow rejection.
  - Extracted latest Kind 3 tags/content, formatted unsigned event payload, and returned `unsigned_event` dictionary.
- [x] **41.2 Client Follow Controller (`static/js/contact_manager.js`, `templates/base.html`):**
  - Updated `window.toggleFollowUser(targetPubkey, buttonElement)` with optimistic button updates, CSRF-authenticated POST, bridge signing (`window.bridgeClient.signEvent`), relay pool broadcast (`window.relayPool.publish`), and user toast feedback.
  - Bound global document click delegation for `.action-btn-toggle-follow` and `#follow-action-btn`.
  - Moved `contact_manager.js` into canonical global scripts bundle in `base.html`.
- [x] **41.3 Template Wiring (`templates/profile.html`, `templates/link_deck.html`):**
  - Attached `.action-btn-toggle-follow`, `data-target-pubkey="{{ target_nostr_pubkey_hex }}"`, and `data-following="false"` to follow action buttons.
- [x] **41.4 Unit Tests (`apps/core/tests/test_contacts.py`):**
  - Added `ContactFollowAPITests` testing auth requirement (302/401), follow appending `["p", target_pubkey, "", ""]`, unfollow removing target, self-follow rejection (400), and invalid pubkey format rejection (400).

### Phase 42: Resilient PostgreSQL Full-Text Search with SQLite Fallback
- [x] **42.1 Resilient Backend Search Execution (`apps/core/views.py`):**
  - Updated `api_search` to detect active database engine (`connection.vendor == "postgresql"`).
  - Implemented PostgreSQL full-text search with `SearchVector` (weights on handle, display name, and headline), `SearchQuery`, and `SearchRank(rank__gte=0.1)`.
  - Implemented automatic fallback to SQLite-compatible `Q(icontains)` matching across handle, display name, headline, and NIP-05.
- [x] **42.2 Unit Tests (`apps/core/tests/test_views.py`):**
  - Added `test_api_search_handles_queries_resiliently_on_sqlite` verifying 200 OK and profile schema fields.
  - Added `test_api_search_empty_query_returns_clean_schema` verifying empty queries return clean count/results schema.
  - Added `test_api_search_postgresql_branch_uses_search_rank_and_vector` testing PostgreSQL FTS branch invocation.

### Phase 43: Eliminate Persona Badge Flash & Harmonize Standalone Template Script Bundles
- [x] **43.1 Server Context Hydration (`apps/core/context_processors.py`):**
  - Updated `user_identity(request)` to export `active_persona_level` and `active_persona_name` to template context.
- [x] **43.2 Dynamic Template Markup (`templates/includes/_standard_header.html`, `_post_composer.html`):**
  - Updated `#active-persona-level` in `_standard_header.html` with dynamic level evaluation (`L{{ active_persona_level|default:1 }}`) and reactive Tailwind color classes (violet for L1, amber for L2+).
  - Updated `composer-active-persona-badge` in `_post_composer.html` to dynamically format level across all fallback branches.
- [x] **43.3 Instant LocalStorage Hydration Cache (`static/js/bridge_client.js`):**
  - Cached active persona snapshots in `localStorage` under `wun_active_persona` in `updateActivePersonaUI`.
  - Implemented synchronous pre-hydration in `hydrateCachedPersona()` on initialization and DOMContentLoaded.
- [x] **43.4 Standalone Template Script Bundles (`templates/gallery.html`, `link_deck.html`):**
  - Added `relay_pool.js`, `notification_manager.js`, and `floating_chat.js` to `gallery.html`.
  - Added `bridge_client.js`, `toast_manager.js`, and `notification_manager.js` to `link_deck.html`.
- [x] **43.5 Filter Reflow Mitigation (`static/js/circle_feed_filter.js`):**
  - Cached card search text on `card.dataset.searchCache` to prevent repetitive DOM queries.
  - Batched DOM reads and writes in `applyFeedFilters()` into grouped arrays to eliminate layout thrashing.
- [x] **43.6 Unit Tests (`apps/core/tests/test_views.py`):**
  - Added tests verifying `active_persona_level` context exposure and dynamic amber/violet badge rendering.

### Phase 44: Concurrency Lock for Persona Switching & SQLite Connection Resilience
- [x] **44.1 In-Flight Mutex & Frame Deduplication (`static/js/bridge_client.js`):**
  - Added `_isSwitchingPersona` and `_lastSwitchedProfileId` to `TauriBridgeClient`.
  - Filtered duplicate switch frames in `handlePersonaChanged`, ensuring only one `/api/auth/persona-switch/` call is in flight at a time with lock release in `.finally()`.
  - Sent only canonical `set_active_profile` in `switchPersona`, removing redundant `SET_ACTIVE_PERSONA` frame.
- [x] **44.2 Idempotent Session Re-Anchoring & Defensive LinkDeck Claims (`apps/core/views.py`):**
  - Updated `api_persona_switch` to return `reanchored: False` when the active user already matches the target DID without cycling session credentials.
  - Hardened `claim_handle` defensively with atomic transactions, checking existing records on `(IntegrityError, OperationalError)` contention.
- [x] **44.3 SQLite Connection Resilience (`config/settings.py`):**
  - Configured 20-second busy timeout and WAL journal mode (`PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;`) in database `OPTIONS`.
### Phase 45: Session Hardening, High-Resilience Relay Pipeline & Feed Empty-State Unification
- [x] **45.1 Session Hardening (`config/settings.py`, `apps/core/views.py`):**
  - Set `SESSION_SAVE_EVERY_REQUEST = False` in `config/settings.py` so sessions only write to DB upon mutation.
  - Enforced read-only session behavior at entry of `api_feed` and `api_profile_notes` (`request.session.modified = False; request.session.save = lambda *args, **kwargs: None`), eliminating `SessionInterrupted` on concurrent persona switches.
- [x] **45.2 High-Resilience Relay Pipeline (`apps/core/views.py`, `static/js/relay_pool.js`):**
  - Updated `DEFAULT_RELAYS` and `buildBootstrapRelays()` to prioritize responsive, indexed relays (`relay.primal.net`, `relay.nostr.band`, `purplerelay.com`, `nostr.mom`) ahead of unstable endpoints (`nos.lol`, `relay.damus.io`).
  - Reduced `relay_req` default timeout from 10s to 2.5s and enforced a remaining deadline check (`remaining <= 0.2: break`).
  - Added strict wall-clock deadline (`feed_deadline = time.time() + 4.0`) to `api_feed` with `timeout=1.5` for secondary queries.
- [x] **45.3 Feed Empty-State Unification (`static/js/circle_feed_filter.js`, `static/js/feed_interactions.js`):**
  - Excluded `#feed-empty-state` and `#feed-pagination-sentinel` from `getNoteCards()` in `circle_feed_filter.js`.
  - Coordinated mutual exclusion between `#feed-empty-state` and `#circle-empty-state` in `ensureEmptyStateElement`, `applyFeedFilters`, `fetchInitialFeedStream`, and `loadMoreNotes`.
- [x] **45.4 Unit Tests (`apps/core/tests/test_views.py`, `apps/core/tests/test_feed.py`):**
  - Added `test_session_save_every_request_is_false` and `test_api_feed_does_not_fail_on_cycled_session` in `test_views.py`.
  - Added `test_relay_req_respects_deadline_with_dead_relays` in `test_feed.py`.

### Phase 46: Dependent Inbound WoT Gate & Feed Filtering (DEP-202 & DEP-203)
- [x] **46.1 Token Ingress & Session State (`apps/core/context.py`, `src/auth/session.ts`, `apps/core/auth.py`, `apps/core/auth_pkce.py`, `apps/core/context_processors.py`):**
  - Implemented `parse_dependent_claim`, `store_dependent_context`, and `get_dependent_context` to parse `id_token.dep` on OIDC callback and persist `is_dependent`, `bracket` ("U14" | "U14-U18" | "U18" | "ADULT"), and `wot_distance_limit` (1, 2, 3, inf).
  - Enforced fail-closed rejection for revoked (`dep.revoked == true`) or expired attestations (`dep.expires_at`).
  - Added TypeScript companion module `src/auth/session.ts`.
  - Exposed `window.DEPENDENT_CONTEXT` in `templates/base.html` and `user_identity` in `context_processors.py`.
- [x] **46.2 Feed Filtering Policy (`apps/feed/selectors.py`, `src/components/Feed.tsx`, `apps/core/views.py`, `static/js/circle_feed_filter.js`, `templates/_nav.html`):**
  - **Stage 1 (U14):** Disabled global public timeline (`is_feed_circle_allowed` returns `false`, `data-circle="global"` button hidden in `_nav.html`); feed displays notes exclusively from approved contacts (WoT distance <= 1, parent-whitelisted contacts); public persona publishing (`kind:0` / `kind:1` to public relays) is suppressed to local-cache only in `relay_pool.js`, `bridge_client.js`, and `selectors.py`.
  - **Stage 2 (U14-U18):** Enabled peer-circle discovery (WoT distance <= 2); dropped notes from 3rd-degree connections and beyond before rendering.
  - Implemented React/TS companion component `src/components/Feed.tsx`.
- [x] **46.3 Inbound DM & Chat Filtering (`apps/core/wot_gate.py`, `src/chat/wot_gate.ts`, `static/js/wot_gate.js`, `static/js/floating_chat.js`):**
  - Intercepted inbound Nostr encrypted DMs (`kind:4` / NIP-04) and XMPP stanzas.
  - Queried local contact trust engine: rejected inbound chat handshakes and dropped unknown messages silently without alerting the minor or exposing message previews when sender distance > `wot_distance_limit`.
- [x] **46.4 Unit & Integration Tests & Zero-PII Verification:**
  - Added comprehensive test suite in `apps/core/tests/test_dependent_wot.py` (19 passing) and Node test runner `test/wot_gate.test.js` (3 passing).
  - Verified feed returns empty/restricted list when authenticated with `bracket: "U14"` and viewing unapproved senders.
  - Verified DM from WoT distance 2 is accepted for `U14-U18` but rejected for `U14`.
  - Verified zero PII leakage during trust-distance checks.
- [x] **46.5 Verification:** `npm run test`, `npm run lint`, `uv run python manage.py test apps.core.tests.test_dependent_wot`, `uv run pytest apps/core/tests/test_dependent_wot.py` — all clean — **Done 2026-09-04**

- [ ] **Ecosystem Doc Organization:** Standardize repo layout to match iyou_wun precedent — root: `AGENT.md`, `README.md`; `docs/`: `DEVELOPER_GUIDE.md`, `DESIGN_DOC.md`, `TODO.md`, `ecosystem_shared/`, `archive/`. *(Progress: README + DEVELOPER_GUIDE + AGENT + TODO synced; `SPRINT_CHANGELOG.md` added; superseded audit reports archived to `docs/archive/`.)*

---

