# WUN Architectural Audit Report

**Date:** 2026-08-19
**Scope:** Media Compartmentalization, Nostr Threading, Profile Persistence, Route Inventory
**Constraint:** Read-only audit — no files modified

---

## 1. Executive Summary

`iyou_wun` is a Django 5.2 OIDC Relying Party satellite with a sovereign Nostr-based social stack. The codebase is structurally clean with proper OIDC/PKCE auth, a well-scoped model layer, and functional multi-kind feed/gallery/profile/chat views. However, **four structural debt categories** require attention:

1. **Media Gallery** uses raw HTML5 `<video>`/`<audio>` elements with no dedicated players, no MIME-type-aware layout, and no media metadata display. The grid is functional but generic.
2. **Nostr Threading** is flat single-level grouping — `e` tag markers (`root`/`reply` per NIP-10) are completely ignored, making recursive reply trees impossible. There is no server-side thread indexing.
3. **Profile Editing** is purely client-side (Tauri bridge signing) with missing form fields (banner, NIP-05, lud16), no bridge reconnection, and no broadcast retry.
4. **Architecture** has significant inline JavaScript (~800 lines in feed.html), duplicated WebSocket bridge logic across templates, hardcoded localhost endpoints, and no base template inheritance.

**Health Rating:** Functional for local/sovereign desktop use; requires hardening for production multi-user deployment.

---

## 2. Subsystem Matrix

| Subsystem | Source Files | Current Behavior | Target State | Identified Bottlenecks |
|---|---|---|---|---|
| **Media Gallery** | `gallery.html`, `views.py:240-292,617-632`, `feed.html:207-259` | Generic responsive grid (1-4 cols), MIME filter bar, basic modal with native HTML5 controls, no poster/waveform/metadata, fixed limit=50 | YouTube/Spotify/Instagram-style dedicated viewports with rich players | No custom players; no video poster; no waveform; no metadata in modal; no download; no srcset; no CORS/PNA |
| **Nostr Threading** | `feed.html:158-304,421-1224`, `views.py:342-367,456-567,370-378` | Flat single-level grouping; `e` tag marker ignored; no reply UI; orphan comments as standalone cards | Recursive tree with NIP-10 markers, indented rendering, reply form, live updates | `get_tag_value()` ignores `e` tag[3]; no `parent_id`/`root_id` models; no recursive fetch; no reply button |
| **Profile Editing** | `dashboard.html:170-416`, `profile.html`, `views.py:48-60,222-237,635-661` | Client-side Kind 0 construction -> Tauri bridge -> relay broadcast; 3/6 fields editable; no reconnection; no retry | Full fields, resilient bridge, retry queue, fallback modal | Missing fields; no reconnection; no retry; no pubkey validation; inconsistent relay defaults |
| **Static Assets** | `static/css/`, `tailwind.config.js`, `package.json`, all templates | Tailwind CLI v3.4 pipeline (DONE); WhiteNoise compression; `STATICFILES_DIRS` configured | CSP headers; base template to eliminate 5x boilerplate duplication | Inline JS prevents CSP; no base template; ConverseJS CDN in chat.html |

---

## 3. Detailed Findings

### 3.1 Multi-Modal Media Rendering

**Data Flow:**
```
Nostr Relay (Kind 1063) -> views.py: fetch_media_assets() / process_into_feed()
  -> Tag extraction: url, m (MIME), dim, thumb, alt
  -> GalleryView.get_context_data() -> gallery.html
  -> Client-side: filterGallery() (show/hide by data-type)
```

**Tag Parsing** (views.py:282-288, 505-512):
- `"url"` tag → `file_url`, `"m"` → `mime_type`, `"dim"` → `dimensions`, `"thumb"` → `thumbnail_url`, `"alt"` → `alt_text`
- Sovereign flag: `is_sovereign = True` if `file_url` contains `"127.0.0.1"`

**Template Rendering:**

| Media Type | Grid Card | Modal | Limitations |
|---|---|---|---|
| Image | `<img>` with thumbnail fallback, `object-cover`, lazy load | Full `<img>` `max-h-[85vh]` | No srcset, no caption, no download |
| Video | `<video preload="metadata">` + play overlay | `<video controls autoplay>` | Native controls only, no poster, no custom UI |
| Audio | Gradient bg + music note emoji (no playback in grid) | `<audio controls autoplay>` in white card | Native controls only, no waveform, no playlist |
| Other | File icon emoji | External link | No preview |

**Blossom Integration** (feed.html:631-684): Upload only — PUT to `http://127.0.0.1:9002/{sha256}`. No NIP-98 auth, no CDN fallback, URL hardcoded in JS.

**Missing:** No custom video/audio players, no lightbox keyboard nav, no media metadata in modal, no download button, no infinite scroll, no API endpoint, no media caching, no CORS/PNA handling.

---

### 3.2 Nostr Threading & Conversation Flow

**Event Kinds:**

| Kind | Purpose | Can Be Parent? |
|---|---|---|
| 1 | Text note | Yes |
| 7 | Reaction | No (child only) |
| 1063 | Media entry | Yes |
| 1111 | Comment/reply | **No** (treated as child only; replies to other Kind 1111 → orphan) |
| 30023 | Long-form article | Yes |
| 1112 | Poll vote | No (child only) |

**`process_into_feed()`** (views.py:456-567) performs single-pass flat grouping:
```python
parent_lookup = {**kind_1, **kind_1063, **kind_30023}  # Only these can be parents
for c in comments:
    parent_id = get_tag_value(c["tags"], "e")  # First "e" tag only — marker ignored
    if parent_id in parent_lookup:
        parent_lookup[parent_id]["comments"].append(c)
    else:
        orphan_comments.append(c)
```

**`get_tag_value()`** (views.py:370-378) reads only `tag[1]` (event ID), **completely ignoring `tag[3]`** (NIP-10 marker: `"root"` or `"reply"`). This means:
- Reply-to-reply treated identically to reply-to-root
- No distinction between root and reply references
- Multi-level nesting impossible

**DOM Rendering:** All comments render at the same visual depth — `pl-4 border-l-2 border-gray-200` (single indentation level). No dynamic indentation based on depth.

**Missing:** No NIP-10 marker parsing, no recursive thread tree builder, no reply composition UI (no "Reply" button), no JS function to construct Kind 1111 events with `e`/`p` tags, no live thread updates, single-relay read with no merge.

**Data Flow Bottlenecks:**
1. Synchronous relay fetches: 2-4 sequential WebSocket connections per page load, 10s timeout each (worst case: 120s)
2. No caching: every page load triggers fresh relay queries
3. Profile fetch capped at 100 unique pubkeys
4. No WebSocket subscription: feed is static until manual refresh

---

### 3.3 Sovereign Profile Persistence Pipeline (Kind 0)

**Complete Flow:**
```
/dashboard -> fetch_profile_data() from relay -> render form
  -> editProfile() constructs Kind 0 JSON
  -> sendEventToTauri() via WebSocket (wss://home.iyou.me:9001/)
  -> Bridge signs -> returns signed_event
  -> broadcastProfile() to each relay (3s timeout each)
  -> Success/failure toast
```

**Editable Fields:**

| Field | Editable? | In Kind 0 Payload? | Displayed? |
|---|---|---|---|
| Display Name | Yes | Yes | Yes |
| Bio/About | Yes | Yes | Yes |
| Avatar URL | Yes | Yes | Yes |
| Banner URL | **No** (no form field) | No | No |
| NIP-05 | **No** (no form field) | No | Yes (read-only from relay) |
| Lightning/lud16 | **No** (no form field) | No | Yes (read-only from relay) |

**Bridge Connection Comparison:**

| Feature | dashboard.html | feed.html |
|---|---|---|
| Mutex/lock guard | No | Yes (`feedConnectionLock`) |
| Profile sync on connect | No | Yes (`{ type: "get_profile" }`) |
| Pubkey validation | No | Yes (64-char hex check) |
| `onclose` handler | Console log only | Resets lock to IDLE |
| Reconnection | **No** | **No** |

**Failure Points:**

| # | Failure | Severity | Location |
|---|---|---|---|
| 1 | Bridge not running — socket state not cleaned; subsequent sends poll dead socket for 5s | HIGH | dashboard.html:191-192 |
| 2 | Bridge drops mid-session — `onclose` only logs; editing broken until reload | HIGH | dashboard.html:198 |
| 3 | All relays unreachable — valid signed event discarded, no retry | HIGH | dashboard.html:252-253 |
| 4 | Bridge timeout (5s) — state reset, user must manually re-click | MEDIUM | dashboard.html:229-235 |
| 5 | Invalid pubkey — no validation (unlike feed.html) | MEDIUM | dashboard.html:297 |
| 6 | `pendingEvent` collision on rapid double-click | LOW | dashboard.html:175,218 |

**Missing:** Bridge reconnection, broadcast retry queue, fallback modal, pubkey validation, profile sync on connect, local persistence of signed events. Relay defaults inconsistent (dashboard: 2, feed: 3, views.py: 3).

---

### 3.4 Codebase Architecture & Route Inventory

**Complete Route Map:**

| URL | View | Template | Auth |
|---|---|---|---|
| `/` | `home()` | redirect → `/feed` | No |
| `/feed` | `FeedView` | `feed.html` | No |
| `/dashboard` | `dashboard()` | `dashboard.html` | Yes |
| `/gallery` | `GalleryView` | `gallery.html` | Yes |
| `/profile/<npub>/` | `ProfileView` | `profile.html` | No |
| `/chat` | `ChatView` | `chat.html` | Yes |
| `/api/relays` | `api_relays()` | JSON | Yes |
| `/api/feed` | `api_feed()` | JSON | Yes |
| `/api/vote` | `api_cast_vote()` | JSON | Yes |
| `/api/credentials/issue/` | `IssueCredentialView` | JSON | Yes+staff |
| `/api/config/` | `node_config()` | JSON | No |

**Models:** Only `IssuedCredential` (subject_did, credential_type, vc_id, issued_at). No social/event models — all data fetched live from relays.

**Dead Assets:**
- `templates/includes/_tailwind_safe_init.html` — never included by any template
- `RELAY_URL` constant (views.py:381) — defined, never referenced
- `getCookie()` function (feed.html:1214) — defined, never called

**Hardcoded Endpoints in JS (not configurable):**
- `http://127.0.0.1:9002/` — Blossom (feed.html:653,669)
- `http://127.0.0.1:8002/api/nostr/ingest/` — Poly engine (feed.html:522,550) — `POLY_ENGINE_URL` exists in settings but is NOT injected to template context
- `https://cdn.conversejs.org/` — ConverseJS CDN (chat.html:20,31)

**Inline JS:** feed.html ~800 lines, dashboard.html ~250 lines, gallery.html ~75 lines. Significant duplication of bridge logic, toast functions, and relay management between feed.html and dashboard.html.

---

## 4. Implementation Roadmap

### Phase 1: Foundation Hardening (Low Risk, High Impact)

| Step | Task | Files |
|---|---|---|
| 1.1 | Extract shared JS into `static/js/bridge.js` (WebSocket bridge, toast, relay mgmt) | `static/js/bridge.js`, `feed.html`, `dashboard.html` |
| 1.2 | Create `templates/base.html` with shared head, nav, header, ecosystem bar, Tailwind config, toast styles | `base.html`, all 5 page templates |
| 1.3 | Inject configurable endpoints via context processor: `BLOSSOM_URL`, `POLY_ENGINE_URL` | `context_processors.py`, `settings.py`, `feed.html` |
| 1.4 | Delete dead assets: `_tailwind_safe_init.html`, `RELAY_URL`, `getCookie()` | 3 files |
| 1.5 | Add CSP headers after base template eliminates inline scripts | `settings.py` or middleware |

### Phase 2: Nostr Threading (High Complexity, High Value)

| Step | Task | Files |
|---|---|---|
| 2.1 | Extend `get_tag_value()` to parse NIP-10 `e` tag markers (`root`/`reply`) | `views.py` |
| 2.2 | Build recursive thread tree in `process_into_feed()`: `root_id`/`parent_id` relationships, nest children | `views.py` |
| 2.3 | Depth-aware rendering in `feed.html`: dynamic indentation based on comment depth | `feed.html` |
| 2.4 | Reply composition UI: "Reply" button, textarea, Kind 1111 construction with `e`/`p` tags | `feed.html` |
| 2.5 | Add `api/thread/<event_id>` endpoint for recursive thread fetching | `views.py`, `urls.py` |
| 2.6 | Fetch missing parents for orphan comments | `views.py` |

### Phase 3: Media Gallery (Medium Complexity, High UX Impact)

| Step | Task | Files |
|---|---|---|
| 3.1 | Integrate Plyr.js for video: custom controls, poster, responsive aspect ratio | `gallery.html`, `static/js/` |
| 3.2 | Integrate Wavesurfer.js for audio: waveform, tracklist, duration | `gallery.html`, `static/js/` |
| 3.3 | Enhance lightbox: keyboard nav, swipe, metadata panel, download button | `gallery.html` |
| 3.4 | Add infinite scroll with IntersectionObserver | `gallery.html`, `views.py` |
| 3.5 | Add `?type=image/video/audio` server-side filtering | `views.py`, `gallery.html` |

### Phase 4: Profile Pipeline (Medium Complexity, High Reliability)

| Step | Task | Files |
|---|---|---|
| 4.1 | Add missing form fields: Banner URL, NIP-05, lud16 | `dashboard.html` |
| 4.2 | Include missing fields in Kind 0 payload | `dashboard.html` |
| 4.3 | Bridge reconnection with exponential backoff on `onclose` | `dashboard.html` |
| 4.4 | Add pubkey validation (64-char hex check) | `dashboard.html` |
| 4.5 | Broadcast retry queue: persist signed event in localStorage | `dashboard.html` |
| 4.6 | Profile sync on dashboard bridge connect | `dashboard.html` |
| 4.7 | Fallback error modal for persistent bridge disconnection | `dashboard.html` |
| 4.8 | Unify relay defaults across Python and all JS templates | `views.py`, `feed.html`, `dashboard.html` |

### Phase 5: Production Readiness (Cross-Cutting)

| Step | Task | Files |
|---|---|---|
| 5.1 | Django cache layer for relay fetches (60s profiles, 30s feeds) | `views.py`, `settings.py` |
| 5.2 | Multi-relay fan-out and merge (replace sequential single-relay reads) | `views.py` |
| 5.3 | Rate limiting on API endpoints | `settings.py`, middleware |
| 5.4 | Replace debug `print()` with proper logging | `auth.py`, `views.py` |
| 5.5 | WebSocket subscription for live feed updates (optional, advanced) | `feed.html`, async view |

---

## 5. Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Production fails due to hardcoded localhost URLs | High | Critical | Step 1.3 |
| Thread replies render incorrectly for nested conversations | High | High | Phase 2 |
| Profile save silently fails when bridge is down | High | High | Steps 4.3-4.5 |
| Media gallery feels dated vs. competitors | Medium | Medium | Phase 3 |
| CSP headers break ConverseJS or inline JS | Medium | Medium | Steps 1.1 + 1.2 |
| Relay fetch latency degrades UX | Medium | Medium | Steps 5.1 + 5.2 |

---

## 6. File Reference Index

| File | Lines | Role in Audit |
|---|---|---|
| `apps/core/views.py` | 825 | All server logic: feed, gallery, profile, threading, relay connections |
| `apps/core/models.py` | 29 | Only `IssuedCredential` — no social/event models |
| `apps/core/urls.py` | 31 | All app routes |
| `apps/core/context_processors.py` | 10 | Template context injection |
| `apps/core/auth.py` | 125 | OIDC backend with debug prints |
| `apps/core/auth_pkce.py` | 88 | PKCE authentication views |
| `templates/feed.html` | 1225 | Feed + ~800 lines inline JS |
| `templates/dashboard.html` | 417 | Profile edit + ~250 lines inline JS |
| `templates/gallery.html` | 192 | Media gallery + modal |
| `templates/profile.html` | 132 | Read-only profile display |
| `templates/chat.html` | 52 | Converse.js XMPP chat |
| `templates/poll_modal.html` | 73 | Poll creation modal |
| `templates/_nav.html` | 12 | Navigation bar |
| `templates/includes/_standard_header.html` | 41 | Header with auth state |
| `templates/includes/_ecosystem_bar.html` | 47 | Sovereign mesh top bar |
| `templates/includes/_tailwind_safe_init.html` | 21 | **DEAD** — never included |
| `config/settings.py` | 264 | All Django configuration |
| `services/poly_client.py` | 59 | Poly governance HTTP client |
| `tailwind.config.js` | 22 | Tailwind content paths + theme |
