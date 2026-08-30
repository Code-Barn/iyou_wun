# SPRINT CHANGELOG — iyou_wun (WUN)

**Sprint Review:** 2026-08-30 — *Git Commit Audit & Canonical Documentation Sync*
**Review scope:** `2ec41c3` (responsive feed shell) → `9bb684b` (profile hero) + working-tree deltas for the progressive search / discovery rail / toast / relay-pool batch.

**Verification baseline:**
```bash
uv run python manage.py test apps.core   # Ran 296 tests — OK (skipped=1)
uv run ruff check .                      # All checks passed!
```

---

## 1. New API Route

| Route           | View             | Auth   | Purpose |
|-----------------|------------------|--------|---------|
| `GET /api/search/` | `views.api_search` | No | Tier-2 progressive search — matches public `UserLinkDeck` profiles (`handle`, `display_name`, `nip05`, `headline`) plus hashtag suggestions. |

**Params:** `q` (term or `#tag`), `limit` (1–20, default 6). **Response:**
```json
{
  "success": true, "query": "mesh",
  "counts": {"profiles": 2, "tags": 3},
  "results": {"profiles": [{ "handle", "display_name", "avatar_url", "headline", "nip05", "is_verified", "url" }],
              "tags": [{ "tag", "display_tag", "url" }]}
}
```
Backfills `api_search` behavior trace from `SEARCH_AUDIT_REPORT.md` (now archived): nav anchor → `relative`, `<nav>` overflow → `visible`, 250ms debounce + `AbortController`, `#search-results-dropdown` flyout with Profiles/Hashtags sections, `Enter`→feed search, `Esc`/click-outside→close.

---

## 2. New Template Partials

| Partial | Purpose |
|---------|---------|
| `templates/includes/_feed_right_rail.html` | Desktop-only **Discovery Rail** (`hidden lg:block`): TRENDING TOPICS (24H velocity `#` tags), SOVEREIGN CREATORS (top-4 public decks, `+ Follow` wired to ContactManager), ECOSYSTEM SPONSOR unit. Hidden in thread mode. |
| `templates/includes/_toast_container.html` | Fixed bottom-right `#toast-container` (z-50, `aria-live="polite"`), included once from `base.html`. |

---

## 3. New JS Modules

| Module | Purpose |
|--------|---------|
| `static/js/toast_manager.js` | Global typed toast engine — `window.showToast(message, type, duration)`; types `success/error/info/mesh/heart/repost/copy/enclave`; HTML-escaped, auto-dismiss 3500ms, per-toast dismiss. |
| `static/js/relay_pool.js` | Dynamic **NIP-65 (Kind 10002) relay pool**: health probing (45s + boot), latency tracking, persisted custom/NIP-65 relays, **parallel fault-tolerant double-broadcast**, and the live "Mesh Pool Active"/"Mesh Degraded"/"Mesh Offline" health indicator on the feed. |

---

## 4. Feature Deltas (by audited area)

### Progressive Search Engine
- `templates/_nav.html` — `#feed-search-input` container now `relative`, `<nav>` `overflow-visible`, autocomplete flyout `#search-results-dropdown` + `#search-dropdown-content` + `#search-dropdown-footer`.
- `static/js/circle_feed_filter.js` — `escapeHtml`, `showDropdown/hideDropdown/renderSearchResults`, `performSearchEscalation` (debounced 250ms, abortable), focus re-render, `Enter`/`Esc`/click-outside handling. Tier-1 DOM filter preserved on feed pages (`setSearchQuery` → `?q=`), tier-3 redirect for non-feed pages.

### Responsive 3-Column Shell & Right Rail
- `templates/feed.html` — outer `max-w-6xl`; flex `main` center column (`max-w-2xl`) + right rail; **Relay Mesh Health Indicator** above composer (`#relay-health-*`, driven by `relay_pool.js`); rail excluded in thread mode.
- `apps/core/views.py` — `FeedView` context: `suggested_creators` (top-4 public verified-first decks, viewer excluded), `trending_tags`, `relay_count`.

### Toast & Notification Stack
- `templates/base.html` — loads `toast_manager.js` + `relay_pool.js` before `theme.js`; includes `_toast_container.html`.
- `static/js/bridge_client.js` — `showToast` now 3-arg and delegates to `window.showToast` (legacy `#toast` fallback); `broadcastToRelays` delegates to `relayPool.broadcast` (local+global success toasts); `getRelays` prefers `window.relayPool`.
- `static/js/feed_interactions.js` / `contact_manager.js` — all user-feedback migrated to typed toasts ("Reaction published to mesh"→`heart`, "Reposted"→`repost`, "Reply broadcasted"→`success`, follow updates→`info/success/error`).

### Decoupled Profile Hero & Avatar Straddle
- `templates/profile.html` — flexbox "decoupled controls row": avatar straddles banner via independent `-mt-16/-mt-20` pull (`aspect-square`, `shrink-0`); action cluster absolutely positioned over banner top edge (`-top-12/-top-14`, backdropped glass buttons); identity block sits fully in whitespace below.

### Batch Reaction Counting & Relay Hardening (backend)
- `apps/core/views.py` — **`attach_reaction_counts()`**: one batch Kind-7 query (`#e` across roots), tallies non-`-` reactions → `like_count` (used by feed, profile, `/api/feed`); `DEFAULT_RELAYS` reordered (`relay.iyou.me` first); **`_connect_relay`/`relay_req` defensive failover** (no unhandled exceptions, next-relay autonomy); **`fetch_user_nip65_relays()`** (Kind 10002 → `{read, write, all}`).
- `templates/includes/_thread_post.html` + `feed_interactions.js` — like button renders real `like_count`.

### XMPP Chat (Converse.js)
- `templates/chat.html` — `import converse from` (default export); `iyou-lifecycle` plugin registering `connected`/`statusInitialized` via `_converse.api.listen.on`; promise-based `initialize().then/catch`; `singleton: false`; `discover_connection_methods: false`; BOSH removed; **`?peer=` deep-link → `auto_join_private_chats`**.

---

## 5. Test Suites (296 — 7 modules)

New/expanded suites this sprint:
- `SearchAPITests` (4) — `/api/search/` schema, handle/name/hashtag filtering, nav dropdown DOM, toast container.
- `RelayPoolAndFailoverTests` (5) — relay failover, all-down → `{}`, NIP-65 parsing, unified-feed outage grace.
- `ProcessIntoFeedTest` +3 reaction-count tests; `FeedModernizationAndExternalAttributionTest` +4 discovery-rail / like-count tests; `ChatViewTest` updated for the lifecycle-plugin/auto-join contract.

| Module | Tests |
|--------|-------|
| `test_auth.py` | 20 |
| `test_views.py` | 77 |
| `test_feed.py` | 52 |
| `test_gallery.py` | 32 |
| `test_issuance.py` | 20 |
| `test_contacts.py` | 10 |
| `test_deck.py` | 85 |
| **Total** | **296** (1 skipped) |

---

## 6. Audit Finding — Outstanding

- **NIP-05 Identity Endpoint (`/.well-known/nostr.json`) is NOT implemented.** The profile `nip05` field and badge exist, but WUN serves no well-known identity file. Requires a route + view mapping verified handles → pubkey hex (`{"names": {...}, "relays": {...}}`). Deferred.

---

## 7. Documentation Reconciliation

Updated: `README.md`, `docs/WUN_DEVELOPER_GUIDE.md`, `AGENT.md`, `TODO.md`.
Created: this changelog (`docs/SPRINT_CHANGELOG.md`).
Archived (historical/superseded → `docs/archive/`, now gitignored): `docs/SEARCH_AUDIT_REPORT.md`, `WUN_ARCHITECTURAL_AUDIT_REPORT.md`.