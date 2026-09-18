# WUN REBUILD VS. REFACTOR FEASIBILITY ASSESSMENT
**Target System:** `iyou_wun` (Omni-Social Nostr & Sovereign Identity Satellite)  
**Lead Systems Architect & Senior Django/Nostr Engineer Diagnostic Report**  
**Status:** Read-Only Architectural Health & Refactor Feasibility Audit  
**Date:** September 2026  

---

## 1. Executive Architecture Scorecard

| Architectural Pillar | Grade | Critical Status & Bottlenecks |
| :--- | :---: | :--- |
| **Ingestion Concurrency** | **F** | **Blocking Synchronous I/O in WSGI Worker Loop.** Sequential relay failover over 8 default relays (`apps/core/views.py:2245-2275`). Spawns orphaned threads with blocking `Event.wait(timeout)`. Up to 20s Gunicorn worker freeze on network stalls. 4 Gunicorn sync workers easily starved to total 502/504 outage by 4 concurrent users. |
| **Frontend State Hygiene** | **D-** | **DOM-as-Database & Fragile Mutexes.** State splintered across 15+ `window.*` globals, 12+ `localStorage` keys, server sessions, and DOM attributes (`dataset.searchCache`, `data-tags`). Pervasive `querySelectorAll` queries and JSON deserialization on every keystroke. Zero tab sleep/resume lifecycle hooks (`visibilitychange` missing), causing silent socket death. |
| **Identity Cohesion** | **D+** | **Cryptographic Key Mismatch & Fragile Post-Login Sync.** OIDC `sub` claim is a DID (Ed25519/web) stored in `User.username`, while Nostr requires Secp256k1 (BIP-340). Flawed `did_to_pubkey` attempts Base64 URL decoding on Base58 multibase strings. Post-login key sync relies on a client-side Tauri WebSocket bridge POST to `/api/auth/sync-keys/`, which fails completely on mobile/web browsers. `FeedView` derives `user_pubkey` and `user_npub` from mismatched keys. |
| **Test Coverage** | **C-** | **Heavy Backend Mocking, 0% Real Frontend Coverage, Broken 500 Handler.** 524 backend tests run in 190s with 1 failing test (`test_custom_500_template_renders` throws `KeyError: 'user'`). Backend tests mock `relay_req` with canned dicts, ignoring real socket timeouts and thread deadlocks. Over 8,000 lines of complex vanilla frontend JS have only 1 test file (`test/wot_gate.test.js`, 3 tests). |
| **OVERALL ARCHITECTURAL HEALTH** | **D+** | **High Technical Debt; Unviable for High-Concurrency Production.** |

---

## 2. Top 5 Critical Flaws

### Flaw 1: Synchronous Sequential WebSocket Relay Probing in Request-Response Cycle
- **Files & Lines:** 
  - [`apps/core/views.py:2245-2275`](file:///Users/macuser/CODE_BASE/iyou_wun/apps/core/views.py#L2245-L2275) (`relay_req`)
  - [`apps/core/views.py:2190-2242`](file:///Users/macuser/CODE_BASE/iyou_wun/apps/core/views.py#L2190-L2242) (`_connect_relay`)
  - [`apps/core/views.py:2165-2174`](file:///Users/macuser/CODE_BASE/iyou_wun/apps/core/views.py#L2165-L2174) (`DEFAULT_RELAYS`)
  - [`docker-entrypoint.sh:11-15`](file:///Users/macuser/CODE_BASE/iyou_wun/docker-entrypoint.sh#L11-L15) (`gunicorn --workers 4 --timeout 120`)
- **Mechanism:**
  - `relay_req` iterates through `DEFAULT_RELAYS` (8 relays) sequentially: `for relay_url in relay_urls:`.
  - For each relay, `_connect_relay` spawns a daemon thread running `ws.run_forever()` and blocks the caller with `done.wait(timeout=effective_timeout)`.
  - On endpoints without explicit deadlines (e.g. `api_profile_notes` L1813, `fetch_contact_pubkeys` L2728, `api_raw_event` L2916, `node_config` L3009), 8 unreachable or hanging relays cause an aggregate synchronous block of **20 seconds** (`8 * 2.5s`).
  - Even in `api_feed` where `feed_deadline = time.time() + 4.0`, each call can consume up to 4 full seconds of worker time across multiple sequential passes (raw events, tag queries, profiles, quoted notes, social counts).
  - With Gunicorn configured for exactly **4 sync workers**, just 4 concurrent users or browser tabs querying the feed will 100% saturate the process pool, causing reverse proxy queueing and HTTP 504 Gateway Timeouts across the entire site.
  - Furthermore, `relay_req` halts on the *first* responsive relay (`if events: return events`), which prevents multi-relay event aggregation. Feed views are artificially partitioned based on whichever relay answers fastest.

### Flaw 2: State Desynchronization & DOM Race Conditions in Empty States & Circle Switching
- **Files & Lines:**
  - [`static/js/circle_feed_filter.js:518-547`](file:///Users/macuser/CODE_BASE/iyou_wun/static/js/circle_feed_filter.js#L518-L547) (`ensureEmptyStateElement` and `#circle-empty-state`)
  - [`static/js/circle_feed_filter.js:694-701`](file:///Users/macuser/CODE_BASE/iyou_wun/static/js/circle_feed_filter.js#L694-L701) (`applyFilters()` before `reloadFeedForCircle()`)
  - [`static/js/feed_interactions.js:1213-1229`](file:///Users/macuser/CODE_BASE/iyou_wun/static/js/feed_interactions.js#L1213-L1229) (`#feed-empty-state` generation)
  - [`static/js/feed_interactions.js:1383-1403`](file:///Users/macuser/CODE_BASE/iyou_wun/static/js/feed_interactions.js#L1383-L1403) (`reloadFeedForCircle`)
  - [`templates/feed.html:196-204`](file:///Users/macuser/CODE_BASE/iyou_wun/templates/feed.html#L196-L204) (`#feed-empty-state` SSR partial)
- **Mechanism:**
  - Two distinct empty state DOM elements coexist without synchronization: `#feed-empty-state` (SSR/hydration) and `#circle-empty-state` (client filter).
  - When switching circle tabs (e.g. from "iyou" to "Following"), `setCircle()` synchronously calls `applyFilters()` at L694. `applyFilters()` immediately scans existing DOM cards; since existing cards belong to the old circle, 0 match, prompting `ensureEmptyStateElement()` to reveal `#circle-empty-state` ("No notes in Following Circle").
  - Immediately following (L699), `setCircle()` calls `window.reloadFeedForCircle()`, which deletes all `.feed-note-card` elements, hides `#circle-empty-state`, unhides the spinner, and initiates an asynchronous `fetch('/api/feed?circle=following')`.
  - This results in a jarring UX double-flash: (1) old feed vanishes -> (2) empty state flashes on screen -> (3) empty state disappears and spinner appears -> (4) new notes arrive. If the network returns 0 notes, `feed_interactions.js` reveals `#feed-empty-state`, while subsequent DOM filter passes trigger `#circle-empty-state`, frequently rendering duplicate stacked empty notices.

### Flaw 3: Dual Identity Decoupling & Fragile Post-Login Enclave Key Sync Race
- **Files & Lines:**
  - [`apps/core/auth.py:77-82`](file:///Users/macuser/CODE_BASE/iyou_wun/apps/core/auth.py#L77-L82) (`create_user` maps OIDC `sub` to `username`)
  - [`apps/core/views.py:310-367`](file:///Users/macuser/CODE_BASE/iyou_wun/apps/core/views.py#L310-L367) (`api_sync_keys`)
  - [`apps/core/views.py:369-393`](file:///Users/macuser/CODE_BASE/iyou_wun/apps/core/views.py#L369-L393) (`get_effective_user_pubkey`)
  - [`apps/core/views.py:690-691`](file:///Users/macuser/CODE_BASE/iyou_wun/apps/core/views.py#L690-L691) (`FeedView` context key derivations)
  - [`apps/core/views.py:3784-3804`](file:///Users/macuser/CODE_BASE/iyou_wun/apps/core/views.py#L3784-L3804) (`did_to_pubkey` Base64 decoding of Base58)
  - [`static/js/bridge_client.js:637-660`](file:///Users/macuser/CODE_BASE/iyou_wun/static/js/bridge_client.js#L637-L660) (`syncKeysToServer`)
- **Mechanism:**
  - Architectural schizophrenia between the identity layer and the Nostr signing layer: `auth.User.username` stores the OIDC DID (`sub`), which is typically an Ed25519 multicodec key or DID:Web string. Nostr operations require a 32-byte Secp256k1 Schnorr public key.
  - In `apps/core/views.py:3784-3804`, `did_to_pubkey` erroneously attempts to parse multibase `did:key:z...` strings using `base64.urlsafe_b64decode`. Standard multibase `z` denotes **Base58BTC**, not Base64URL. This causes silent decoding exceptions or garbage truncated slices.
  - The OIDC handshake does not supply the user's Nostr pubkey. On initial post-login redirect to `/feed`, `request.session["nostr_pubkey_hex"]` is null, and `deck.nostr_pubkey` is empty. The server renders the feed with an empty or corrupted author identity.
  - The platform depends entirely on `bridge_client.js` running in the user's browser, successfully connecting to a local desktop Tauri enclave socket (`ws://127.0.0.1:9001`), extracting the Secp256k1 key, and POSTing it to `/api/auth/sync-keys/`.
  - On mobile browsers, standalone web logins, or when Tauri is closed, this sync never fires. The session remains permanently orphaned from the user's Nostr pubkey.
  - In `FeedView.get_context_data` (L690-691), `user_pubkey` is assigned from `get_effective_user_pubkey()`, while `user_npub` is assigned from `did_to_npub(self.request.user.username)`. As a result, `context["user_pubkey"]` and `context["user_npub"]` frequently reference two entirely different, incompatible cryptographic identities.

### Flaw 4: Silent Socket Death on Tab Sleep/Backgrounding (Missing Lifecycle Events)
- **Files & Lines:**
  - [`static/js/relay_pool.js:578-641`](file:///Users/macuser/CODE_BASE/iyou_wun/static/js/relay_pool.js#L578-L641) (`ensureConnection`)
  - [`static/js/relay_pool.js:673-694`](file:///Users/macuser/CODE_BASE/iyou_wun/static/js/relay_pool.js#L673-L694) (`_startHeartbeat`)
  - [`static/js/bridge_client.js:980-1020`](file:///Users/macuser/CODE_BASE/iyou_wun/static/js/bridge_client.js#L980-L1020) (`initBridge`)
- **Mechanism:**
  - Zero browser tab lifecycle management: `grep_search` across `static/js/` reveals **zero** event listeners for `document.addEventListener("visibilitychange")`, `window.addEventListener("focus")`, or `window.addEventListener("online")`.
  - When mobile devices or desktop browsers background the tab or the OS enters sleep mode, JavaScript timers (`setInterval` / `setTimeout`) are paused or throttled by browser power management.
  - The 25-second synthetic NIP-01 heartbeat in `_startHeartbeat` halts. During sleep, stateful NAT firewalls, mobile carrier gateways, and cloud load balancers drop the idle TCP connection without transmitting TCP FIN/RST packets.
  - When the user awakens their laptop or switches back to the tab, the browser's WebSocket instances remain in an unacknowledged half-open or dead state (`readyState === 1` or `3`).
  - Because no `visibilitychange` handler checks socket health or triggers reconnection, the user is stranded on a dead feed. New note submissions or relay subscriptions fail silently until the background `probeTimer` (45-second period) eventually detects the timeout.

### Flaw 5: Broken XMPP Protocol Wiring & Race in Converse.js Module Initialization
- **Files & Lines:**
  - [`apps/core/views.py:920-930`](file:///Users/macuser/CODE_BASE/iyou_wun/apps/core/views.py#L920-L930) (`api_chat_session` port 5222 misconfiguration)
  - [`apps/core/views.py:934-942`](file:///Users/macuser/CODE_BASE/iyou_wun/apps/core/views.py#L934-L942) (`api_chat_session` fake token generation)
  - [`templates/chat.html:7-10`](file:///Users/macuser/CODE_BASE/iyou_wun/templates/chat.html#L7-L10) (Unbundled third-party CDN assets)
  - [`templates/chat.html:46-71`](file:///Users/macuser/CODE_BASE/iyou_wun/templates/chat.html#L46-L71) (`<script type="module">` race condition)
- **Mechanism:**
  - In `api_chat_session` (L923, L929), the WebSocket URL defaults to `wss://xmpp.iyou.me:5222/xmpp-websocket` or `wss://home.iyou.me:5222/xmpp-websocket`. Port 5222 is the standard plain TCP / STARTTLS c2s port, NOT an HTTP/WebSocket port (which runs on 5280/5281 or 443). Browsers initiating a WebSocket upgrade against port 5222 encounter immediate protocol errors and connection resets.
  - In `api_chat_session` (L934-941), the session password is generated on the fly as a random SHA256 hash of the timestamp and username. Because this credential is never provisioned on the XMPP server (ejabberd/prosody), SASL authentication fails with `not-authorized`.
  - In `templates/chat.html:46-71`, bootstrap logic is encapsulated within `<script type="module">`. Module scripts are deferred by default. It binds `document.addEventListener("DOMContentLoaded", ...)`. In scenarios where assets are cached or the document is already interactive, `DOMContentLoaded` has already dispatched before the module executes. The listener never fires, leaving the spinner overlay visible until a 6-second emergency timeout trips.
  - The fallback routine `showOfflineRoster()` is invoked on virtually every session, meaning XMPP chat has degraded into a non-functional shell that displays an offline Nostr DM placeholder.

---

## 3. Deep-Dive Directive Audits

### Directive 1: Relay Ingestion & Concurrency Pipeline
- **Synchronous vs. Asynchronous:** Ingestion is 100% synchronous in the WSGI request thread. In `apps/core/views.py`, `relay_req()` uses Python's synchronous `threading.Event()` to wait on a daemonized `websocket.WebSocketApp`. 
- **Sequential Failover vs. Fan-Out:** Failover is purely sequential. It iterates through an array of relays one by one:
  ```python
  for relay_url in relay_urls:
      events = _connect_relay(relay_url, sub_id, filter_obj, effective_timeout)
      if events:
          return events
  ```
  It neither fans out requests concurrently nor aggregates results across relays.
- **Worker Starvation:** Gunicorn runs with 4 sync workers (`--workers 4`). Without a deadline, a failure across the 8 default relays holds a worker for 20 seconds. 4 concurrent requests against unresponsive relays completely stalls the web tier.
- **Deduplication & Chronological Sorting:**
  - Deduplication is performed by event ID in `nip10.py` (`seen_root_ids`, `seen_reply_ids`) and again redundantly in `views.py:process_into_feed` (`deduped_raw`, `seen_final_root_ids`).
  - Sorting relies on event `created_at` timestamps:
    ```python
    roots.sort(key=lambda x: x["created_at"], reverse=True)
    ```
  - Nostr event timestamps are set by client clocks without monotonic guarantees. Relays routinely accept timestamps skewed up to 2 hours into the future. Because `relay_req()` returns solely from the first responsive relay, sorting is strictly chronological only with respect to the subset returned by that specific relay.

### Directive 2: Frontend Lifecycle & State Synchronization
- **State Fragmentation:** State is split across global window properties (`window.relayPool`, `window.bridgeClient`, `window.circleFeedFilter`, `window.activeProfile`, `window.userPubkey`), localStorage (`wun_relays`, `wun_custom_relays`, `wun_active_persona`), and the DOM.
- **DOM Scraping Overhead:** `circle_feed_filter.js` queries `document.querySelectorAll(".feed-note-card, .thread-root")` on every filter execution. It reads and writes directly to `dataset.searchCache` and executes `JSON.parse(card.getAttribute("data-tags"))` on every card during search keystrokes.
- **Visual Flashing & Desynchronization:** During circle changes, `circle_feed_filter.js` evaluates existing DOM cards before the network fetch begins, instantly rendering an empty state before clearing cards and initiating the fetch.
- **Tab Sleep/Resume:** No lifecycle event listeners (`visibilitychange`, `freeze`, `resume`, `focus`) exist. Sockets that die during backgrounding remain dead until active user interaction triggers an error.

### Directive 3: Identity Model & Key Mapping
- **Entity Model:**
  - `auth.User.username`: Stores OIDC `sub` claim (DID).
  - `UserLinkDeck`: One-to-one with `User`. Stores `handle` (indexed), `nostr_pubkey` (indexed, 64-char hex), and metadata.
  - Events/Notes: Not stored in database. All feed items are ephemeral.
- **Key Resolution & Bech32 Overhead:**
  - `npub` strings are never indexed or stored in the database. Every render cycle invokes `hex_to_npub()` and `npub_to_hex()` dozens to hundreds of times in nested loops.
  - Multibase parsing in `did_to_pubkey` incorrectly uses Base64URL decoding on Base58BTC multibase strings (`did:key:z...`), resulting in failure for standard W3C DIDs.
- **Post-Login Key Sync Race:**
  - OIDC callback does not populate `UserLinkDeck.nostr_pubkey` or session pubkeys.
  - Desktop client relies on an asynchronous post-login AJAX handshake from `bridge_client.js` to `/api/auth/sync-keys/`.
  - Non-Tauri web clients never complete this handshake, breaking author queries and profile streams.

### Directive 4: Ancillary Modules (`gallery`, `chat`, `governance`)
- **Media Gallery:**
  - `templates/gallery.html` does not extend `base.html`; it duplicates HTML `<head>`, scripts, and styles.
  - `gallery_player.js` manages its own infinite scroll observer and lightbox (`#lightboxModal`), duplicating the infinite scroll observer and lightbox (`#image-lightbox-modal`) in `feed_interactions.js` and `base.html`.
  - Feed video rendering uses unstyled `<video controls>` without coordination with Plyr.js in the gallery.
- **XMPP Chat:**
  - Hardcoded or defaulted to port 5222 for WebSockets (protocol mismatch).
  - Ephemeral token generation is uncoordinated with XMPP server storage.
  - Deferred module script execution races with `DOMContentLoaded`.
- **Governance (`poly`):**
  - `services/poly_client.py:PolyClient.cast_vote` performs synchronous `urllib.request.urlopen` with a 10-second blocking timeout inside the WSGI worker thread.

---

## 4. Test Suite Audit & Findings

A full execution of the backend test suite (`uv run python manage.py test apps.core`) yielded:
- **Total Tests:** 524 tests.
- **Execution Time:** 189.856 seconds (~3.2 minutes).
- **Results:** 522 passed, 1 skipped, **1 failed**.
- **Failing Test:** `apps.core.tests.test_views.CyberGritErrorViewTests.test_custom_500_template_renders`
  ```
  django.template.base.VariableDoesNotExist: Failed lookup for key [user] in [{'True': True, 'False': False, 'None': None}]
  ```
  *Root Cause:* The custom 500 error handler renders `500.html` via Django's default `server_error()`, which renders without `RequestContext` (context processors are omitted). The template attempts to resolve `user.is_authenticated`, raising an unhandled `VariableDoesNotExist` exception.
- **Frontend Test Coverage:** Only 1 test file exists (`test/wot_gate.test.js`, 3 passing assertions). 0 unit tests exist for `relay_pool.js`, `circle_feed_filter.js`, `feed_interactions.js`, or `bridge_client.js`.
- **Linting (`ruff check .`):** 8 errors in `docs/ecosystem_shared/auth_pkce.py`, including `F821 Undefined name 'params'`.

---

## 5. Greenfield vs. In-Place Recommendation

### The Dilemma
Should `iyou_wun` undergo an **in-place modular refactor** within Django 5.2, or a **clean-slate greenfield rebuild** (`iyou_wun_v2`, adopting a headless architecture similar to `iyou_hive`)?

### Evaluation Matrix

| Metric | Option A: In-Place Modular Refactor | Option B: Clean-Slate Greenfield Rebuild (`iyou_wun_v2`) |
| :--- | :--- | :--- |
| **Architecture** | Hybrid Django SSR + Vanilla JS scripts + WSGI/ASGI mix | Headless Async API (FastAPI / Django Ninja ASGI) + React 19 / Vite SPA |
| **Relay Ingestion** | Refactor `relay_req` to thread pool or client-side mesh | Native client-side WebSocket pool (NIP-01/65) + optional async background cache |
| **State Management** | Refactor vanilla JS into custom ES modules with custom events | Standardized reactive store (Zustand / TanStack Query) |
| **Identity Cohesion** | Patch `did_to_pubkey` and force IDP session injection | First-class Nostr pubkey OIDC claim from IDP; zero client sync race |
| **Preservation of Assets** | Keeps 524 Django tests, existing templates, routing | Requires porting business logic, NIP-10 parser, and re-authoring tests |
| **Estimated Effort** | **6 – 8 Engineering Days** (32 – 44 hours) | **14 – 18 Engineering Days** (75 – 95 hours) |
| **Long-Term Maintainability**| Moderate (still bound to 4,200-line monolithic views and SSR quirks) | **High (Clean separation of concerns, matches `iyou_hive` flagship standard)** |
| **Risk Profile** | Lower immediate risk; high regression surface on legacy templates | High initial rewrite risk; low long-term architectural risk |

### Recommendation: Targeted 2-Phase Modular Overhaul (Option A with Clean Boundary Decoupling)

**Verdict:** An immediate clean-slate greenfield rebuild is **NOT recommended at this stage**, despite architectural flaws. 

**Architectural Rationale:**
1. **Business Logic Density:** `iyou_wun` contains substantial, verified domain logic:
   - NIP-10 Hero Thread Tree Builder & Lineage Parser ([`apps/core/nip10.py`](file:///Users/macuser/CODE_BASE/iyou_wun/apps/core/nip10.py), 954 lines)
   - Sovereign Link Deck CRUD & Proof-of-Authority verification ([`apps/core/models.py`](file:///Users/macuser/CODE_BASE/iyou_wun/apps/core/models.py), [`apps/core/views.py`](file:///Users/macuser/CODE_BASE/iyou_wun/apps/core/views.py))
   - Verifiable Credential Ed25519 Issuance & Cryptographic Validation ([`apps/core/did_kit.py`](file:///Users/macuser/CODE_BASE/iyou_wun/apps/core/did_kit.py))
   - Dependent Trust Ladder & Web-of-Trust perimeter enforcement (DEP-202/203)
   - 523 passing tests verifying these specific behaviors.
2. **Rebuild Risk:** A greenfield rebuild would require re-implementing and re-certifying all OIDC PKCE invariants, WoT gating, VC issuance, and NIP-10 threading from scratch, likely taking 3–4 weeks and stalling feature delivery.
3. **Feasibility of In-Place Cure:** The core bottlenecks (blocking relay I/O, empty state flashes, key sync races, missing socket lifecycles) can be completely eradicated in-place with **surgical architectural decoupling** without discarding the Django foundation.

---

## 6. Estimated Effort Matrix

### Option A: Targeted Modular In-Place Overhaul (Recommended)

| Sprint / Phase | Scope of Work | Estimated Hours |
| :--- | :--- | :---: |
| **Phase 1: Ingestion Concurrency & Instant Shell** | - Refactor `relay_req()` to use concurrent fan-out (`concurrent.futures.ThreadPoolExecutor`) with global hard deadlines.<br>- Enforce Instant Shell architecture across all feed views (`?async=1` default behavior; zero blocking relay queries during initial SSR page load).<br>- Decouple backend from external relay mesh; delegate live feed reading to client-side WebSockets and async `/api/feed/`.<br>- Fix `test_custom_500_template_renders` in `500.html`. | 10 – 12 hrs |
| **Phase 2: Identity Model & Key Handshake Hardening** | - Fix multibase Base58BTC decoding in `did_to_pubkey()` (remove `base64.urlsafe_b64decode`).<br>- Coordinate with `iyou_idp` to include `nostr_pubkey` as an authenticated OIDC ID token claim, eliminating post-login `/api/auth/sync-keys/` race.<br>- Harmonize `FeedView` context: bind `user_npub` strictly to `hex_to_npub(user_pubkey)`. | 8 – 10 hrs |
| **Phase 3: Frontend State Hygiene & Lifecycle Engine** | - Add `document.addEventListener("visibilitychange")`, `online`, and `focus` handlers in `relay_pool.js` and `bridge_client.js` with instant reconnect.<br>- Eliminate dual empty states: delete dynamic `#circle-empty-state` in `circle_feed_filter.js`; establish single reactive empty state manager.<br>- Eliminate circle switching flash: immediately clear cards and show skeleton loader before triggering fetch.<br>- Replace DOM attribute caching (`dataset.searchCache`, `data-tags`) with an in-memory FeedStore array. | 10 – 12 hrs |
| **Phase 4: Ancillary Cleanup & Test Modernization** | - Refactor `gallery.html` to extend `base.html`; deduplicate infinite scroll and lightbox controllers.<br>- Fix XMPP WebSocket endpoint in `api_chat_session` (port 5281/443, SASL anonymous/guest handling); resolve ESM `DOMContentLoaded` race.<br>- Add Jest/Playwright frontend test suite covering `relay_pool.js` and `circle_feed_filter.js`. | 6 – 8 hrs |
| **TOTAL EFFORT** | **4 Phases / 1 Release Cycle** | **34 – 42 hrs (1.0 eng-wk)** |

---

### Option B: Clean-Slate Greenfield Rebuild (`iyou_wun_v2`)

| Phase | Scope of Work | Estimated Hours |
| :--- | :--- | :---: |
| **Phase 1: Architecture & API Foundation** | Scaffold Headless ASGI project (FastAPI / Django Ninja), configure PostgreSQL, Redis event bus, Docker runtime, and OIDC PKCE authentication with `iyou_idp`. | 16 – 20 hrs |
| **Phase 2: Domain Logic & Crypto Port** | Port `nip10.py` threading tree builder, `did_kit.py` VC issuance, Link Deck models, and WoT dependent trust ladders into modern typed Pydantic models. | 20 – 24 hrs |
| **Phase 3: Client-Side Nostr & SPA Interface** | Scaffold React 19 + Vite SPA (matching `iyou_hive`), implement client-side Nostr relay pool (NDK / Nostr-Tools), reactive TanStack Query feeds, unified Plyr media deck, and Converse.js/Matrix chat. | 28 – 34 hrs |
| **Phase 4: Testing & Parity Verification** | Author comprehensive end-to-end Playwright tests, port 500+ unit test scenarios, perform cross-browser verification, and configure CI/CD. | 18 – 22 hrs |
| **TOTAL EFFORT** | **Full System Greenfield Rewrite** | **82 – 100 hrs (2.5 eng-wks)** |

---

## 7. Conclusion & Architectural Roadmap

`iyou_wun` suffers from classic architectural drift: a system originally built for simple Django server-rendered pages has accumulated decentralized WebSocket relay queries, cryptographic key mappings, client-side DOM filtering, and external desktop bridge integrations without an asynchronous architectural foundation.

However, because its core domain services (NIP-10 threading, VC issuance, Link Deck, and WoT perimeter gating) are mathematically sound and heavily unit-tested, **a targeted modular refactor (Option A) delivers 100% of the required UX responsiveness and concurrency resilience at less than half the time and risk of a greenfield rebuild.**

By executing Phase 1 (Instant Shell & Concurrent Fan-Out) and Phase 3 (Frontend State & Tab Lifecycle), all observed UX clunkiness, worker starvation, visual flashes, and socket drops will be permanently resolved.
