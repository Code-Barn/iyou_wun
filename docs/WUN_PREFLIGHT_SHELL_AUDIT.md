# WUN Pre-Flight Shell Audit

**Status:** Read-only audit · **Date:** 2026-09-23 · **Repository:** `iyou_wun`
**Purpose:** Prepare zero-regression integration of the desktop 3-column shell (sticky left rail) and mobile bottom dock staged in `EXTERNAL/docs/staged_templates/`
**Consumes:** `EXTERNAL/docs/comparative_audits/AUDIT-005_wun_left_rail_migration_rfc.md`
**Scope:** No production application code was modified during this pass. Deliverable is this document plus the committed baseline.

---

## 0. Baseline Locked at Audit Time

| Check | Result |
| :--- | :--- |
| Test suite | **577 tests, 1 skipped, all OK** in 78.7s (`uv run python manage.py test apps.core`) |
| Lint | **8 pre-existing ruff errors, all in `docs/ecosystem_shared/auth_pkce.py`** (F401 unused imports in an external reference doc). No errors anywhere in `apps/`, `config/`, `templates/`, or `static/`. |
| Working tree | Clean before audit (no uncommitted changes) |
| Brief's "279 green" | **Stale.** AGENT.md names 347; empirical baseline today is **577**. Any regression threshold must be set against 577 (`OK (skipped=1)`), not 279. |

---

## 1. Layout Shell & Main Container

### 1.1 `templates/base.html` (164 lines)

Document-bone order inside `<body class="min-h-screen flex flex-col ... bg-slate-50 ... overflow-x-hidden">`:

```
L0  includes/_ecosystem_bar.html              (fixed top-0 z-[9999] overlay, hover-to-open lip)
L1  includes/_standard_header.html            (relative z-30 border-b max-w-7xl h-16 glass)
L2  _nav.html                                  (relative z-10 border-b; 2-row on feed/gallery, 1-row elsewhere)
MAIN <main class="flex-1 w-full">{% block content %}{% endblock %}</main>
FOOTER includes/_footer.html
GLOBAL SCRIPTS toast_manager / bridge_client / relay_pool / theme / contact_manager / wot_gate
PAGE `{% block extra_js %}`, window.userPubkey / DEPENDENT_CONTEXT bootstrap
notification_manager.js + circle_feed_filter.js (defer)
#image-lightbox-modal + open/closeImageModal()
includes/_toast_container.html
[if auth] includes/_notification_drawer.html
[if auth AND url_name != 'chat'] includes/_floating_chat_dock.html + static/js/floating_chat.js
#jump-to-top-btn          fixed bottom-6 right-6 z-40 (opacity-0 until scrolled)
SW registration + enclave pubkey sync
```

Notes:
- There is **no application-level grid** in `base.html`; every child template supplies its own `max-w-*` container inside `{% block content %}`.
- The floating chat dock and notification drawer are **auth-gated and duplicate-safe** (`url_name != 'chat'` guard at `base.html:124`). Test suite hard-depends on this guard: `test_views.py:135,562` assert `floating-chat-root`/`floating_chat.js` absence on anonymous and `/chat` responses.
- `#jump-to-top-btn` currently `fixed bottom-6 right-6 z-40` — will collide with the bottom dock + FAB cell on `<768px` unless bumped (RFC §4.3 → `max-md:bottom-20 max-md:right-20`).

### 1.2 `templates/feed.html` (310 lines)

Within `{% block content %}`:

```
max-w-7xl mx-auto px-4 sm:px-6 py-4 sm:py-6
  └─ messages block
  └─ grid grid-cols-1 {% if feed_mode != 'thread' %}lg:grid-cols-12{% endif %} gap-6 items-start   (feed.html:40)
      ├─ Main column:
      │     lg:col-span-8                              (main mode)            (feed.html:43)
      │     ─ or ─ max-w-2xl mx-auto w-full            (thread mode)
      │     └─ thread deck (ancestors / hero / replies)   (feed.html:45-149)
      │     └─ main stream (post-composer → skeleton → #feed-container → pagination sentinel)
      └─ Right rail (main mode ONLY):
            {% if feed_mode != 'thread' %} assertTrue  (feed.html:247)
              <aside class="hidden lg:block lg:col-span-4 sticky top-4
                            max-h-[calc(100vh-2rem)] overflow-y-auto no-scrollbar space-y-4">
                {% include "includes/_feed_right_rail.html" %}
              </aside>
            {% endif %}}
```

Key structural facts:
- **The 2-column feed/right-rail layout is 100% owned by `feed.html`**, not `base.html`. `_feed_right_rail.html` is included only from `feed.html:249`, only in main (non-thread) mode, only at `lg+` (`hidden lg:block`), and only on `/feed`.
- Right-rail height math is already `max-h-[calc(100vh-2rem)]` + `overflow-y-auto no-scrollbar` — the new shell's `h-[calc(100vh-128px)]` is the same family of utilities (see §2).

### 1.3 Thread mode (`?thread=`)

- `FeedView` (apps/core/views.py) sets `feed_mode = "thread"` + `thread_mode = True` whenever a `thread` / `note` / `e` param resolves (views.py:714–748); otherwise `feed_mode` is the **selected circle name** (e.g. `iyou`, `global`), *never* the string `"main"`.
- Layout effect: grid loses `lg:grid-cols-12` (`feed.html:40`), the main column becomes `max-w-2xl mx-auto w-full` (`feed.html:43`), and the **right rail is suppressed** (`feed.html:247`). Left-of-stream is completely empty in thread mode today.
- Test-locked: `test_views.py:2438` (`test_feed_hides_discovery_rail_in_thread_mode`), `:2513` (relay-health widget hidden in thread). Any new shell must preserve **right-rail suppression in thread mode**.
- Because `feed_mode == 'thread'` is `False`/undefined on every non-feed route, a base-shell right rail condition **cannot** be `{% if feed_mode != 'thread' %}` alone — it must also assert the route is `feed` (see §6.2).

### 1.4 Non-feed routed templates (shell re-parenting blast radius)

| Template | `{% extends "base.html" %}` | Own content wrapper | Notes |
| :--- | :--- | :--- | :--- |
| `gallery.html` | yes | `max-w-7xl mx-auto px-4 py-8` | 12-col grids inside |
| `notifications.html` | yes | `max-w-3xl w-full mx-auto px-2 sm:px-4 py-4 sm:py-6` | |
| `dashboard.html` | yes | `max-w-6xl mx-auto px-3 sm:px-6 py-6 sm:py-8` | itself a 12-col `lg:grid-cols-12` inside |
| `chat.html` | yes | `max-w-7xl mx-auto px-2 sm:px-4 py-2` | |
| `profile.html` | yes | `max-w-5xl mx-auto px-2 sm:px-4 py-4 sm:py-6` | |
| `link_deck.html` | **no — standalone `<html>`** | its own `<main class="max-w-md ...">` (link_deck.html:23) | does NOT even include `_nav.html` |

Implication: a `base.html` grid that re-parents `<main>` will affect six templates; `link_deck.html` will be entirely unaffected (separate document) unless migrated to `{% extends %}`. This makes `link_deck` the odd-one-out and a conscious decision point (§6.5).

---

## 2. Tailwind Scanning & CSS Initialization

### 2.1 Scanning (CONFIRMED — includes are scanned)

`tailwind.config.js` content globs:

```js
content: [
  './templates/**/*.html',                 // ← recursive; templates/includes/*.html IS scanned
  './apps/**/templates/**/*.html',
  './static/**/*.js',                       // JS class strings scanned too
  './docs/ecosystem_shared/**/*.html',
],
darkMode: 'class'
```

- `templates/includes/*.html` is matched by `./templates/**/*.html`. No config change is needed to pick up the four staged partials once they are copied into `templates/includes/`.
- `preflight` is default-on (`@tailwind base` in `static/css/input.css`), `no-scrollbar` is a hand-written utility in `input.css:33-41` (already compiled into `static/css/output.css`).

### 2.2 Build pipeline & artifact

- `package.json`: `build:css` → `npx tailwindcss -i ./static/css/input.css -o ./static/css/output.css --minify`; `watch:css` for dev.
- **`static/css/output.css` is `gitignore`d** (`.gitignore: line "Tailwind build artifact"`), as is `staticfiles/`. Any merged work therefore depends on running `npm run build:css` before serving — engines must compile, or the new classes silently 404. The audit's own hermetic probe ran a clean build successfully (`Done in ~2s`).

### 2.3 Arbitrary-value classes (COMPILATION VERIFIED)

A hermetic probe (same `input.css`, same theme, probe HTML outside the repo) confirmed every arbitrary class used by the RFC/staged partials compiles with zero config changes. No CSS custom-property mapping is required for compilation:

| Class (from staged partials) | Compiled output |
| :--- | :--- |
| `lg:grid-cols-[184px_minmax(0,1fr)_348px]` | `grid-template-columns:184px minmax(0,1fr) 348px` @ ≥1024px |
| `grid-cols-[48px_minmax(0,1fr)_300px]` | `grid-template-columns:48px minmax(0,1fr) 300px` |
| `grid-cols-5` | `grid-template-columns:repeat(5,minmax(0,1fr))` |
| `sticky top-[128px]` | `top:128px` |
| `h-[calc(100vh-128px)]` / `max-h-[calc(100vh-128px)]` | `calc(100vh - 128px)` |
| `pb-[env(safe-area-inset-bottom)]` | `padding-bottom:env(safe-area-inset-bottom)` |
| `max-md:bottom-20 max-md:right-20` | `bottom:5rem; right:5rem` under `@media not all and (min-width:768px)` |
| `max-xl:!w-9 max-xl:!h-9 max-xl:rounded-lg max-xl:mx-auto` | forced 36px square CTA under `@media not all and (min-width:1280px)` |

- `top-[128px]` rasterizes to a literal `128px`; recommended design intent (RFC §2.2: `--rail-top = var(--l1-height,64px) + var(--l2-height,64px)`) is best expressed as a `:root` CSS variable *documented but technically optional* — Tailwind needs no mapping. If the var route is chosen, use it in arbitrary values `top-[var(--rail-top)]`.

### 2.4 Sticky-top assumption that must hold at runtime

| Layer | Template | Height | In flow? |
| :--- | :--- | :--- | :--- |
| L0 | `_ecosystem_bar.html` | ~4px resting lip → full on hover | `fixed top-0 z-[9999]` (overlay, never pushes) |
| L1 | `_standard_header.html` | `h-16` = **64px** | relative, in flow |
| L2 | `_nav.html` | 2-row ≈ **64px** on feed/gallery; **1-row ≈ 44px** elsewhere | relative, in flow |

`sticky top-[128px]` = L1(64) + L2(full 64). It rides L1/L2 correctly wherever `_nav` renders two rows. **On chat/dashboard/notifications/profile the rail will sit ~20px lower than the compact L2 bottom** — cosmetic gap only, sticky math remains valid. See edge case §6.5-companion.

---

## 3. Client-Side DOM & Script Hooks (all CONFIRMED)

| Hook | Location / source of truth | Notes |
| :--- | :--- | :--- |
| `#floating-chat-root` | `_floating_chat_dock.html:5` | `fixed bottom-0 right-20 z-40 flex items-end`; **only on non-`/chat` auth pages** (`base.html:124`) |
| `#docked-chat-windows` | `_floating_chat_dock.html:8` | where `_live_audio_tray.html` must mount |
| `#floating-chat-toggle-btn` + `#chat-roster-popover` | `_floating_chat_dock.html:39,13` | |
| `#floating-chat-unread-badge` | `_floating_chat_dock.html:45` | driven by `static/js/floating_chat.js` (`UNREAD_BADGE`); **absent on `/chat` and anon pages — mirror scripts must be source-absent-safe (they are)** |
| `#notification-unread-dot` | `_standard_header.html:50` | driven by `notification_manager.js` (`DOT_ID`); test-locked at `test_views.py:3007` |
| Composer trigger | **No global `openPostComposer` exists yet** | Current path: `#btn-compose-note` click → `circle_feed_filter.js:1166-1175` → scrollIntoView(`#postContent`) → focus; fallback `location.href = "/feed#compose"`. The staged rail/dock **polyfill** `window.openPostComposer` (`_left_rail.html:134`, `_mobile_bottom_dock.html:132`) with the same `#postContent` + `/feed#compose` behavior — idempotent (`||`), no conflict with existing binding |
| `#postContent` | `_post_composer.html:10` | textarea rendered **only when `user_pubkey` is truthy**; absent on dashboard/gallery/notifications/chat → `openPostComposer()` falls back to `/feed#compose`. |
| `#relay-status-dot` / `#relay-health-widget` | `_feed_right_rail.html:14,5` | naming differs from legacy `relay-health-indicator` (asserted-absent in `test_feed.py:759-761` — already the case today, not a regression) |

Badge-mirror contract in the staged partials matches reality:
- Notification dot → `#notification-unread-dot` ✓ (exists, violet, `animate-pulse`, toggled `hidden`).
- Chat numeric pill → `#floating-chat-unread-badge` ✓ (exists, hidden until >0, textContent is the count). Absent on `/chat` — mirror gracefully skips.

---

## 4. Route & Context Processor Mapping

### 4.1 Route inventory (`apps/core/urls.py`)

| Named route | Pattern | Consumed by staged partials |
| :--- | :--- | :--- |
| `home` | `/` | brand lockup |
| `feed` | `/feed` (FeedView) | Stream + Explore (`?explore=1`) + brand |
| `notifications` | `/notifications/` | Notifications slot |
| `gallery` | `/gallery` | Gallery slot |
| `chat` | `/chat` | Chat slot / dock / mobile pill |
| `profile` | `/profile/<npub>/` | — (right rail creator links) |
| `dashboard` | `/dashboard` | Bookmarks slot (`#deck`), Dashboard slot, mini-rail identity + CTA |
| `link_deck` | `/@<handle>` | Link Deck slot (**LANDMINE, §6.1**) |
| `link_deck_did` | `/u/<did_key>/` | recommended Link Deck fallback target |
| `logout` / `oidc_logout` | external | — |
| `moderation_console`, `api_*` | various | not referenced by shell |

**Explore gap:** `?explore=1` is **handled nowhere** in `apps/core/` (grep of views.py and repo for `explore` = no matches). The staged roster uses it only for `aria-current` active-state cosmetics. Until FeedView (or `circle_feed_filter.js`) is taught to consume `?explore=1`, the Explore slot is a pretty link with no behavioral change. Non-blocking; log it.

### 4.2 Context processors (CONFIRMED global)

`config/settings.py:123-130` registers, among others:

- `apps.core.context_processors.satellite_urls` — `idp_home_url`, `idp_home_ws_url`, `BRIDGE_WS_URL`, `xmpp_*`, `blossom_*`.
- `apps.core.context_processors.user_identity` — returns, for **every request**:
  - anonymous: `user_display_label=""`, `current_session_did=""`, `user_avatar_url=""` (plus dependent defaults).
  - authenticated: `user_display_label`, `user_avatar_url` (deck avatar), `current_session_did`, `user_pubkey_hex`, `user_npub`, **`user_handle`** (clean legacy handle), `user_profile_url`, persona (`active_persona_level/name`), and dependent/WOT keys.

**Answer to the audit question:** `user_display_label` and `user_avatar_url` are provided **globally by `user_identity` on all views**, not view-specifically. Both staged identity UI (`_left_rail.html:71-77`) and dock/rail placeholder contexts resolve against every route. The rail's Slack-required `rail_slots` iterable is **not** produced anywhere yet — the staged partials ship a deploy-ready `{% empty %}` static roster, so no context processor work is strictly required to launch.

---

## 5. Staged Partials — File Readiness

All four files reside in `EXTERNAL/docs/staged_templates/` and are self-contained (only `{% url %}`, `{% static %}`, `{% firstof %}` plus inline JS):

| Partial | Verdict |
| :--- | :--- |
| `_left_rail.html` (144 ln) | Solid. Sticky `lg:flex` rail `top-[128px] h-[calc(100vh-128px)]`; 48px brand band; CTA morph (`max-xl:!w-9`); identity footer incl. `_persona_enclave.html` (xl+) + mini avatar dot; badge-mirror + `openPostComposer` polyfill. Attribute this to Primal (ATT-001). |
| `_left_rail_slots.html` (224 ln) | Solid pattern; **has two blockers**: (a) Link Deck `{% url 'link_deck' handle=user_display_label|default:user.username %}` fails reverse (§6.1); (b) stray `-->` at line 36 (double comment close → literal `-->` in output) — strip before staging. |
| `_mobile_bottom_dock.html` (142 ln) | Solid. 5-cell `grid-cols-5 h-14 pb-[env(safe-area-inset-bottom)]`, `lg:hidden`, dot-not-count + rose numeric chat pill, FAB cell, badge mirror + polyfill. Damus ATT-003. |
| `_live_audio_tray.html` (271 ln) | Solid. Mounts inside `#floating-chat-root`; `window.LiveAudioTray.attach()`; `hidden` until attached; native `<audio>` + hls.js + replay. Nostrich ATT-002. |

---

## 6. Edge Cases, Conflicts & Landmines (severity-ordered)

### 6.1 🔴 CRITICAL — Link Deck URL reversal raises `NoReverseMatch` on every authenticated page

`_left_rail_slots.html` static fallback renders `{% url 'link_deck' handle=user_display_label|default:user.username %}`.

**Proven empirically against the real URLconf:**

```
LINK_DECK FAIL : 'did:key:z6Mkglobalbridge1... (L2)'      ← default display_label shape for no-deck users
LINK_DECK FAIL : 'firstname.lastname'
LINK_DECK FAIL : 'did:iyou:0x3bf0'
LINK_DECK OK   : 'bob'                                      ← only bare [a-z0-9_-] handles reverse
```

The `link_deck` pattern is `^@(?P<handle>[a-z0-9_-]{3,32})(?:\[(?P<disc>\d+)\])?/?$`. DID usernames (`did:key:...`, `did:iyou:...`) and the L-panel display label (uppercase, colons, spaces, dots, `...`) **never** match → Django raises `NoReverseMatch` → **HTTP 500 on the whole base shell for almost every real account the moment `_left_rail.html` is included in `base.html`.** Because the guard is `{% if user.is_authenticated or user_display_label %}` (true for all logged-in users), this is a hard ship-blocker.

**Required fix (pick one):**
1. **Recommended:** resolve via `user_handle` (clean legacy handle), falling back to `link_deck_did` which never fails:
   ```html
   {% if user_handle %}
     <a href="{% url 'link_deck' handle=user_handle %}">
   {% else %}
     <a href="{% url 'link_deck_did' did_key=current_session_did|default:user.username %}">
   {% endif %}
   ```
2. Simpler: drop the Link Deck slot from the static fallback until a `rail_slots` context processor exists.

### 6.2 🔴 HIGH — The right discovery rail must stay feed-scoped, or tests break

`_feed_right_rail.html`'s empty-limits render fallback avatars `{% static 'img/mesh_avatar_default.svg' %}` (`_feed_right_rail.html:187,203`). The suite asserts **`assertNotContains(response, "img/mesh_avatar_default.svg")` on the authenticated profile page** (`test_views.py:848-852`, `test_profile_uses_iyou_symbol...`). If the right rail were globlaly included from `base.html`, the profile/dashboard responses would render those fallbacks → **immediate test failure + visual leak**. Right-rail context keys (`suggested_creators`, `trending_tags_global/iyou`, `is_sovereign`) exist **only in FeedView** (views.py:866,875,1398).

**Constraint:** the right rail must be included only when `request.resolver_match.url_name == 'feed' AND feed_mode != 'thread'` (never rely on `feed_mode != 'thread'` alone, since non-feed routes don't define it → would default True). Cleanest form: an empty `{% block right_rail %}` in `base.html` that `feed.html` overrides, or a feed-only include guarded by both conditions.

### 6.3 🔴 HIGH — Thread mode must keep right-rail suppression and a 48px rail

`feed.html:247`/`:2513` lock right-rail hiding in thread mode. The planned base shell carries this condition out of feed.html — it must be preserved exactly. Additionally RFC §2.4 asks the **left rail to collapse to 48px in thread mode even at >1280px**; the staged `_left_rail.html` collapses on **viewport breakpoints** (`max-xl`), not mode. Thread mode at >1280px would show the full 184px rail. Decide: (a) accept full rail in thread mode, or (b) add a thread-mode grid variant `lg:grid-cols-[48px_minmax(0,1fr)]` when `feed_mode == 'thread'`.

### 6.4 🟠 MEDIUM — MD–LG (768–1024px) falls into a navigation void

- Left rail: `hidden lg:flex` → hidden below 1024px.
- Bottom dock: `lg:hidden` → visible below 1024px.
- ⇒ Unlike the RFC's three-tier ladder, the rail/dock pair leaves **768–1024px with neither**. RFC §7.3 requires an **L1 hamburger flyout** reusing `_left_rail_slots.html` (RFC plan item #10). **That flyout is not in the staged set** — it must be implemented, or MD–LG users only have the L2 `_nav` ribbon + L1. If the flyout ships, give it a **distinct list id** (e.g. `left-rail-flyout-list`); the badge mirror queries `#left-rail-slot-list` and would otherwise update only the first duplicate node.

### 6.5 🟠 MEDIUM — Sticky offset & shell geometry deltas

- `top-[128px]` assumes a 2-row `_nav` (feed/gallery). On 1-row-L2 routes the rail floats ~20px lower than the nav bottom. Cosmetic; acceptable, or make offset a `:root` `--rail-top` token.
- Shell `max-w-[1520px]` widens pages beyond today's `max-w-7xl` (1280px) at +1280px viewports. Intentional per RFC, but a visible change for >1280 screens.
- `link_deck.html` is a **standalone document** (own `<html>`/`<main>`, no `{% extends %}`, no `_nav.html`). The new rail/dock/badges will not appear on it. Decide: migrate to `{% extends "base.html" %}` (gets the whole shell + breaks the auth test that expects no `_nav` on deck? verify: `test_deck` uses `@/<handle>` → standalone page today; migrating changes its DOM materially) or explicitly leave deck out of the shell.

### 6.6 🟡 LOW — Layout collisions on mobile once the dock lands

- **Jump-to-top** vs dock+FAB: `fixed bottom-6 right-6 z-40` overlaps the dock's rightmost FAB cell → must become `max-md:bottom-20 max-md:right-20` (RFC §4.3; verified compiles to `bottom:5rem/right:5rem`).
- **Floating chat root** (`bottom-0 right-20 z-40`) overlaps the dock (z-30, `bottom-0`): on `<768px` the chat trigger sits inside/behind the dock's last cells. Needs `max-md:bottom-16` (≈64px, above `h-14` + safe-area) so the dock acts as the persistent slat and chat rises above it (RFC §4.2).
- `_live_audio_tray.html` mounts inside `#floating-chat-root` and inherits its offsets — on mobile it will float above the chat trigger; verify it also clears the dock (`bottom-16`).
- z-ladder after change: L0 `z-[9999]` > drawer/modal `z-50` > toasts `z-50` > jump `z-40` > floating chat `z-40` > **dock `z-30`** > header `z-30` > nav `z-10`. Dock under floating chat by both offset and z — consistent.

### 6.7 🟡 LOW — Both partials always in the DOM

Rail is present on mobile (CSS-hidden) and dock on desktop (CSS-hidden); both inline scripts execute on every page (guards `__wunLeftRailBadgesBound` / `__wunMobileDockBadgesBound` / `||` make the polyfills idempotent; both MutationObservers on `document.body` are cheap and only fire on class/text changes of the mirrored targets). Acceptable; no action beyond noting.

### 6.8 🟡 LOW — Output artifact hygiene

`static/css/output.css` and `staticfiles/` are gitignored. Post-merge, the new classes exist **only after `npm run build:css`** and Deploy stoning `collectstatic`. No B&C step may assume the committed CSS contains shell utilities.

---

## 7. Step-by-Step Implementation Plan (zero-regression)

Each phase ends with the full verification gate (§8). Do **not** merge phases 2–4 until the phase-1 blockers (§6.1, §6.2) are fixed.

### Phase 0 — Pre-flight (DONE, this audit)
- Locked baseline: 577 tests / OK(+1 skipped); 8 ruff pre-errs (all in `docs/ecosystem_shared/auth_pkce.py`).

### Phase 1 — Stage partials + harden them (templates/includes/)
1. Copy `_left_rail.html`, `_left_rail_slots.html`, `_mobile_bottom_dock.html`, `_live_audio_tray.html` → `templates/includes/`.
2. **Fix §6.1:** replace the Link Deck `{% url %}` in `_left_rail_slots.html` with the `user_handle`→`link_deck_did` dual-path (or drop the slot).
3. **Fix §6.1b:** strip the stray `-->` at `_left_rail_slots.html:36`.
4. Keep the `openPostComposer` polyfills and both badge mirrors as-is (they are compatible with `circle_feed_filter.js` + `notification_manager.js` + `floating_chat.js`).
5. `npm run build:css` and confirm every §2.3 class exists in `output.css`.

### Phase 2 — `templates/base.html` (shell re-parenting; non-feed pages visually unchanged apart from the rail) (child-block order preserved)
6. Add optional `:root` rail tokens (`--l1-height:64px; --l2-height:64px; --rail-top:calc(64px + 64px)`) next to the existing lightbox styles, and use `top-[var(--rail-top)]` / `h-[calc(100vh-var(--rail-top))]` if you adopt the token route (literal `128px` also fine).
7. Re-parent `<main>`:
   ```html
   <main class="flex-1 w-full">
     <div class="max-w-[1520px] mx-auto px-4 sm:px-6 lg:grid lg:items-start lg:gap-6
                 lg:grid-cols-[48px_minmax(0,1fr)_300px] xl:grid-cols-[184px_minmax(0,1fr)_348px]">
       <aside id="left-rail" class="hidden lg:flex lg:col-span-1 min-w-0">
         {% include "includes/_left_rail.html" %}
       </aside>
       <div id="stream-column" class="lg:col-span-1 min-w-0 mx-auto w-full max-w-[640px]">
         {% block content %}{% endblock %}
       </div>
       <aside id="right-rail" class="hidden lg:block lg:col-span-1 min-w-0">
         {% block right_rail %}{% endblock %}      {# empty by default — §6.2 gate lives in feed.html #}
       </aside>
     </div>
   </main>
   ```
   When the thread-mode variant (§6.3) is adopted, feed.html overrides the container class or adds `{% if feed_mode == 'thread' %}lg:grid-cols-[48px_minmax(0,1fr)]{% endif %}` via a `block` hook — do **not** hard-code thread logic into base.html (feed_only state lives in the child).
8. After the floating-chat include block (line ~127), add `{% include "includes/_mobile_bottom_dock.html" %}` (the partial self-gates on auth). Keep it **after** the chat dock so z/offset math reads in order.
9. Bump jump-to-top: `class="fixed z-40 bottom-6 right-6 max-md:bottom-20 max-md:right-20 ..."`.
10. Inside `_floating_chat_dock.html`, nest `{% include "includes/_live_audio_tray.html" %}` inside `#floating-chat-root` (as a sibling of `#docked-chat-windows`), and give the root `max-md:bottom-16` mobile stacking.

### Phase 3 — `templates/feed.html` (right-rail wiring, feed-scoped)
11. Remove the local 12-col grid wrapper + its `lg:grid-cols-12` class (now supplied by the shell); keep the thread-mode `max-w-2xl mx-auto w-full` centering on the main column.
12. Fill the right-rail gap with the **feed-scoped gate**:
    ```html
    {% block right_rail %}
      {% if request.resolver_match.url_name == 'feed' and feed_mode != 'thread' %}
        <aside class="hidden lg:block sticky top-[var(--rail-top,128px)]
                      max-h-[calc(100vh-var(--rail-top,128px))] overflow-y-auto no-scrollbar space-y-4">
          {% include "includes/_feed_right_rail.html" %}
        </aside>
      {% endif %}
    {% endblock %}
    ```
    (Also preserves `test_feed_hides_discovery_rail_in_thread_mode`.)
13. Give the main feed thread container `pb-28 lg:pb-0` clearance for the dock (mobile).

### Phase 4 — Companion clearance (no layout change; pure whitespace padding)
14. `gallery.html`, `notifications.html`, `dashboard.html`, `profile.html`: main column + `pb-28 lg:pb-0` (or `max-md:pb-28`) so the last items clear the dock.
15. (Optional, non-blocking) implement the **MD–LG L1 flyout** in `_standard_header.html` with a **distinct list id** (`left-rail-flyout-list`) reusing `_left_rail_slots.html` with `slot_style="flyout"` (RFC §7.3).
16. (Optional) migrate `link_deck.html` to `{% extends "base.html" %}` or explicitly document deck-out-of-shell (§6.5).

### Phase 5 — Explore & badges follow-ups (logged, not blockers)
- Teach FeedView / `circle_feed_filter.js` to consume `?explore=1` for the Explore slot (§4.1).
- Route the existing `/api/search/` triage into the Explore slot (RFC §3).
- NIP-51 bookmarks model (`kind 10003/10004`) for the Bookmarks slot (RFC §3.3).

---

## 8. Verification Gate (repeat after every phase)

```bash
npm run build:css                                  # new classes must appear in output.css
uv run python manage.py test apps.core            # EXPECT: same 577 tests, 1 skipped, OK
uv run ruff check .                               # EXPECT: same 8 pre-existing, ZERO new
```

Targeted regression probes after integration:
1. Anonymous `/feed` → no `#left-rail-nav`, no `#mobile-bottom-dock`, no persona containers (mirrors `test_standard_header_omits_persona_switcher_when_anonymous`).
2. Authenticated `/feed` → rail + dock present, `openPostComposer` defines, `#floating-chat-root` + `#notification-unread-dot` intact.
3. Authenticated `/chat` → no `#floating-chat-root`, rail Chat pill mirror source-absent → stays hidden.
4. Thread view `/feed?thread=<id>` → no right rail, `#relay-health-widget` absent.
5. Authenticated `/profile/<npub>` → **no `img/mesh_avatar_default.svg`** (right rail not global).
6. More than 99 unread chat → dock/rail pill clamps `99+`.
7. Breakpoint manuel pass at <768 / 768–1024 / 1024–1280 / >1280 against the §2.3 compiled classes.

---

## 9. Summary of Answers to the Brief's Questions

| Audit task | Answer |
| :--- | :--- |
| 1. Layout shell / main / 2-col feed / thread | `<main class="flex-1 w-full">` is a plain pass-through; the 2-col feed+`_feed_right_rail` live **entirely in `feed.html`** (12-col grid `lg:grid-cols-12`, `lg:col-span-8/4`, gated by `feed_mode != 'thread'`); thread mode drops the right rail and centers `max-w-2xl` (§1). |
| 2. Tailwind scanning & arbitrary classes | Confirmed scanned (`templates/**/*.html` incl. `includes/`); all §2.3 arbitrary classes **compile cleanly** in a hermetic build — no custom-property mapping required; `output.css` is a gitignored build artifact that must be rebuilt `npm run build:css`. |
| 3. DOM/script hooks | `#floating-chat-root` (dock root, non-`/chat` auth only), `#floating-chat-unread-badge` + `#notification-unread-dot` (both confirmed live), composer = **no global `openPostComposer` yet** → staged polyfill parallels the existing `#postContent`/`#btn-compose-note` path (§3). |
| 4. Routes & context | All needed named routes exist (`feed`, `notifications`, `gallery`, `chat`, `dashboard`, `link_deck`/`link_deck_did`); `user_display_label` + `user_avatar_url` are **global** via `apps.core.context_processors.user_identity`; `rail_slots` iterable does **not** exist yet — static fallback covers launch (§4). |
| Ship-blockers | §6.1 Link Deck `NoReverseMatch` (500-everywhere), §6.2 right-rail globalization test leak, §6.3 thread-mode rail/right-rail degradation. |