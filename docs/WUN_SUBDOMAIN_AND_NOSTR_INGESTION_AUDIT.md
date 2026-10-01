# Audit: WUN Subdomain Ingress & Nostr Kind 30023/1112 Ingestion

**Target:** `dkc.il.us.wun.iyou.me` as the community "Paper of Record" for social traffic and civic polls.  
**Audited Scope:**
1. Ingress, session, CSRF, and routing configuration in `config/settings.py`
2. Nostr filter construction and Kind 30023/1112 lifecycle in `apps/core/views.py` and `apps/core/nip10.py`
3. Client-side signing and geographic tag injection in `static/js/bridge_client.js` and `static/js/feed_interactions.js`

---

## Executive Summary & Gap Matrix

| Architectural Layer | Target Requirement (`dkc.il.us.wun.iyou.me`) | Current Status in `iyou_wun` | Severity |
| :--- | :--- | :--- | :--- |
| **Ingress Hosts** | Allow `dkc.il.us.wun.iyou.me` and wildcard subdomains | `ALLOWED_HOSTS` defaults strictly to `["localhost", "127.0.0.1"]` via `WUN_ALLOWED_HOSTS`. Fails with `DisallowedHost` (HTTP 400). | **CRITICAL** |
| **CSRF Origins** | Accept state-changing actions from `https://*.wun.iyou.me` | `CSRF_TRUSTED_ORIGINS` is missing entirely (typoed as `SESSION_TRUSTED_ORIGINS`). Fails with HTTP 403. | **CRITICAL** |
| **Session Cookies** | Share authenticated session across `*.wun.iyou.me` | `SESSION_COOKIE_DOMAIN = None` (host-only). User logging in at apex appears logged out on locality subdomain. | **CRITICAL** |
| **Geographic Middleware** | Parse `dkc.il.us` from host and populate `request.geographic_scope` | `GeographicRoutingMiddleware` is NOT registered in `MIDDLEWARE` and does not exist in `apps/core/`. `request.geographic_scope` is always `None`. | **BLOCKER** |
| **Nostr Event Filters** | Query `#geo` / `#geohash` tags for local feed containment | Filters in `api_feed` and `fetch_unified_feed` only support `#t` (hashtags). Zero support for `#geo` or `#geohash`. | **BLOCKER** |
| **Kind 1112 (Vote) Ingestion** | Ingest Kind 1112 votes to tally poll outcomes | `fetch_unified_feed` and `api_feed` filter only `kinds: [1, 1063, 1111, 30023]`. Kind 1112 is never requested from relays. | **HIGH** |
| **Kind 30023 Client Hydration** | Render poll voting form and options in feed cards | Dynamic feed renderer (`renderNoteCard`) omits `.poll-vote-form` and poll options entirely; only renders contextual button. | **HIGH** |
| **Client Geo-Tag Injection** | Inject `["geo", "<scope>"]` or `["geohash", ...]` on submit | `submitPost()` (Kind 1) only injects `client` and `t` tags. `createPoll()` (Kind 30023) hardcodes `["geohash", "global"]`. | **BLOCKER** |

---

## 1. Subdomain Ingress & Middleware Audit (`config/settings.py`)

### 1.1 `ALLOWED_HOSTS`
- **Current setting (`config/settings.py:47`):**
  ```python
  ALLOWED_HOSTS = env.list("WUN_ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])
  ```
- **Finding:** If `WUN_ALLOWED_HOSTS` is not explicitly overridden in production `.env` with wildcard or subdomain coverage, any request to `dkc.il.us.wun.iyou.me` is rejected immediately by Django's `SecurityMiddleware` with an HTTP 400 (`SuspiciousOperation: Invalid HTTP_HOST header`).
- **Required Remediation:** Ensure `WUN_ALLOWED_HOSTS` includes `".wun.iyou.me"` or default to:
  ```python
  ALLOWED_HOSTS = env.list("WUN_ALLOWED_HOSTS", default=["localhost", "127.0.0.1", ".wun.iyou.me", "wun.iyou.me"])
  ```

### 1.2 `CSRF_TRUSTED_ORIGINS`
- **Current setting (`config/settings.py:118`):**
  ```python
  SESSION_TRUSTED_ORIGINS = [f"https://{APP_NAME_PREFIX}.iyou.me"]
  ```
- **Finding:** Django has no setting named `SESSION_TRUSTED_ORIGINS`. This is a non-functional typo. `CSRF_TRUSTED_ORIGINS` is completely undefined and defaults to `[]`.
- **Consequence:** Even if ingress routing succeeds, any POST request (e.g. casting votes, submitting replies, bookmarking, flagging) made to `https://dkc.il.us.wun.iyou.me` will be rejected by `CsrfViewMiddleware` with HTTP 403 Forbidden ("Origin checking failed").
- **Required Remediation:** Replace with canonical Django CSRF trusted origins supporting wildcard subdomains:
  ```python
  CSRF_TRUSTED_ORIGINS = env.list(
      "WUN_CSRF_TRUSTED_ORIGINS",
      default=[f"https://{APP_NAME_PREFIX}.iyou.me", f"https://*.{APP_NAME_PREFIX}.iyou.me"],
  )
  ```

### 1.3 Cookie Domains (`SESSION_COOKIE_DOMAIN`)
- **Current setting (`config/settings.py:115`):**
  ```python
  SESSION_COOKIE_DOMAIN = None
  ```
- **Finding:** A `None` value instructs the browser to bind cookies strictly to the exact host in the response URL (Host-Only Cookie RFC 6265).
- **Consequence:** An authenticated session established at `https://wun.iyou.me/` (or via `/oidc/callback/`) will not be sent to `https://dkc.il.us.wun.iyou.me`. Users will be treated as anonymous visitors whenever navigating to the community subdomain.
- **Required Remediation:** Set domain to permit subdomain inheritance in production (while retaining `None` for local loopback development):
  ```python
  SESSION_COOKIE_DOMAIN = None if DEBUG else env.str("WUN_SESSION_COOKIE_DOMAIN", default=f".{APP_NAME_PREFIX}.iyou.me")
  CSRF_COOKIE_DOMAIN = SESSION_COOKIE_DOMAIN
  ```

### 1.4 `GeographicRoutingMiddleware` Audit
- **Current `MIDDLEWARE` order (`config/settings.py:157-167`):**
  ```python
  MIDDLEWARE = [
      "django.middleware.security.SecurityMiddleware",
      "whitenoise.middleware.WhiteNoiseMiddleware",
      "django.contrib.sessions.middleware.SessionMiddleware",
      "django.middleware.locale.LocaleMiddleware",
      "django.middleware.common.CommonMiddleware",
      "django.middleware.csrf.CsrfViewMiddleware",
      "django.contrib.auth.middleware.AuthenticationMiddleware",
      "django.contrib.messages.middleware.MessageMiddleware",
      "django.middleware.clickjacking.XFrameOptionsMiddleware",
  ]
  ```
- **Finding:**
  1. `GeographicRoutingMiddleware` is **missing entirely** from `MIDDLEWARE`.
  2. The middleware class is not defined anywhere in `apps/core/` (unlike `iyou_talk`, `iyou_poly`, `iyou_life`, etc.).
  3. Consequently, `request.geographic_scope` is never set on any request. In `templates/includes/_standard_header.html:51`, the geo-capsule check `{% if request.geographic_scope %}` always evaluates to false, falling back to `GLOBAL MESH`.
- **Architectural Position Relative to `SessionMiddleware`:**
  - Conforming to `docs/ecosystem_shared/OMNI_SOCIAL_AUTH_STANDARDIZATION.md` §7:
    > "The session middleware MUST load before any custom middleware that touches `request.session`."
  - If placed before `SessionMiddleware` (as currently done incorrectly in `iyou_poly`), accessing `request.session` in the middleware raises an `AttributeError` on uninitialized session backends.
  - In `iyou_wun`, `GeographicRoutingMiddleware` must be positioned **after `SessionMiddleware`** (index 3 or 5, after `SessionMiddleware` and `CommonMiddleware`), and before `AuthenticationMiddleware` or views.

---

## 2. Nostr Filter Construction & Ingestion Audit (`apps/core/views.py`)

### 2.1 Nostr Event Filter Construction
- **In `apps/core/views.py:relay_req` (lines 3051–3173):**
  - Takes a raw NIP-01 `filter_obj` dictionary.
  - Spawns worker threads across `relay_urls` via `ThreadPoolExecutor`.
  - Dispatches `["REQ", sub_id, filter_obj]` directly over WebSocket via `_connect_relay`.
  - Filters are forwarded verbatim without automated tag decoration.
- **In `apps/core/views.py:api_feed` (lines 1339–1468):**
  - Construct:
    ```python
    filter_obj = {"kinds": [1, 1063, 1111, 30023], "limit": limit}
    if until_ts is not None:
        filter_obj["until"] = until_ts - 1
    if tag:
        clean_tag = tag.lstrip("#")
        filter_obj["#t"] = [clean_tag]
    ```
- **In `apps/core/views.py:fetch_unified_feed` (lines 3628–3699):**
  - Construct:
    ```python
    filter_obj = {"kinds": [1, 1063, 1111, 30023], "limit": limit}
    if authors:
        filter_obj["authors"] = authors
    ```
- **In `apps/core/views.py:attach_social_counts` (lines 3418–3450):**
  - Construct:
    ```python
    filter_obj = {
        "kinds": [1, 6, 7, 1111],
        "#e": root_ids,
        "limit": 800,
    }
    ```

### 2.2 Support for `#geo` or `#geohash` Filter Tags
- **Findings:**
  - **Zero support in query filters:** Neither `api_feed` nor `fetch_unified_feed` exposes or builds filter keys for `"#geo"`, `"#geohash"`, or `"#g"`.
  - The only tag filtering implemented is `filter_obj["#t"] = [clean_tag]` for hashtag exploration.
  - In `apps/core/nip10.py:1046`, `note["poll_scope_geohash"] = get_tag_value(tags, "geohash")` parses incoming tags on Kind 30023, but no query filter ever requests notes matching a locality's scope.
  - Consequently, hitting `dkc.il.us.wun.iyou.me` queries the global relay without scoping notes to `dkc.il.us`.

### 2.3 Kind 30023 (Polls) and Kind 1112 (Votes) Lifecycle

#### A. Kind 30023 (Poll Proposals)
- **Parsing:**
  - In `apps/core/nip10.py` (`_enrich_root` lines 1043–1049):
    ```python
    if kind == 30023:
        note["poll_options"] = [t[1] for t in tags if t and t[0] == "option" and len(t) > 1]
        note["poll_d_tag"] = get_tag_value(tags, "d")
        note["poll_scope_geohash"] = get_tag_value(tags, "geohash")
        note["poll_scope_org"] = get_tag_value(tags, "org")
        note["poll_closes_at"] = get_tag_value(tags, "expires")
    ```
  - Correctly captures options and metadata when events arrive.
- **Rendering:**
  - **Server-Side Template (`templates/includes/_thread_post.html:308-334`):**
    - Renders `<form class="poll-vote-form" data-poll-id="{{ note.id }}">` with options as radio buttons when `note.kind == 30023 and note.poll_options`.
  - **Client-Side Dynamic Feed (`static/js/feed_interactions.js:renderNoteCard`):**
    - Under the default **Instant Shell Architecture**, the initial page load renders skeletons and hydrates from `/api/feed/`.
    - `renderNoteCard(note)` builds cards in JavaScript. While it includes an action row button with `ICON_VOTE`, **it completely omits the `.poll-vote-form` and option list**.
    - In `feed_interactions.js:1398`, `wrapper.querySelector(".poll-vote-form")` returns `null`. The voting interface is never rendered on dynamically hydrated poll cards.

#### B. Kind 1112 (Poll Votes)
- **Parsing:**
  - In `apps/core/views.py:process_into_feed` (lines 3323–3385):
    - Collects `kind == 1112` events into `votes`.
    - Matches vote parent `["e", parent_id]` to `root_by_id[parent_id]["votes"]`.
- **Query Defect (Starvation):**
  - Kind 1112 is **omitted from all relay query filters**:
    - `api_feed`: `filter_obj = {"kinds": [1, 1063, 1111, 30023]}`
    - `fetch_unified_feed`: `filter_obj = {"kinds": [1, 1063, 1111, 30023]}`
    - `attach_social_counts`: `filter_obj = {"kinds": [1, 6, 7, 1111]}`
  - Because Kind 1112 is never requested from relays, `votes` is always empty in production.
- **Rendering:**
  - Neither `_thread_post.html` nor `feed_interactions.js` includes any markup, tally, or visualization for `note.votes`. Vote totals and outcome bars are completely absent from the presentation layer.

---

## 3. Client-Side Tag Injection Audit (`bridge_client.js` & `feed_interactions.js`)

### 3.1 Kind 1 Note Creation (`static/js/feed_interactions.js:submitPost`)
- **Inspection of lines 106–122:**
  ```javascript
  if (!tags.some(function (t) { return t[0] === "client" && t[1] === "iyou"; })) {
      tags.push(["client", "iyou"]);
  }
  if (!tags.some(function (t) { return t[0] === "t" && t[1] === "iyou"; })) {
      tags.push(["t", "iyou"]);
  }
  var kind = (attachedMedia && stagedMedia.length === 0 && !originalText) ? 1063 : 1;
  var event = {
      kind: kind,
      content: text,
      pubkey: pk,
      created_at: Math.floor(Date.now() / 1000),
      tags: tags,
  };
  bridgeClient.signEvent(event);
  ```
- **Finding:** Only `client: iyou` and `t: iyou` tags are injected.
- **Result:** When posting from `dkc.il.us.wun.iyou.me`, **no geographic tags (`["geo", ...]` or `["geohash", ...]`) are injected**.

### 3.2 Kind 30023 Poll Creation (`static/js/feed_interactions.js:createPoll`)
- **Inspection of lines 2469–2489:**
  ```javascript
  var tags = [
      ["d", uuidv4()],
      ["title", title],
      ["fidelity_min", String(fidelity)]
  ];
  options.forEach(function (opt) { tags.push(["option", opt]); });
  if (scope === "regional") {
      tags.push(["geohash", "global"]);
  } else if (scope === "family") {
      tags.push(["org", "iyou"]);
  }
  var expires = Math.floor(Date.now() / 1000) + 30 * 24 * 60 * 60;
  tags.push(["expires", String(expires)]);
  ```
- **Finding:**
  - When the user selects "Local Regional", the tag pushed is literally hardcoded as `["geohash", "global"]`.
  - It does not inspect `window.location.hostname` or `request.geographic_scope`.
  - It **does not inject `["geo", request.geographic_scope]`**.

### 3.3 Bridge Client (`static/js/bridge_client.js`)
- **Inspection of `TauriBridgeClient.prototype.signEvent` (line 938):**
  - Takes `event` as passed, validates socket connection, and forwards `{ type: "sign_event", event: event }` to the Port 9001 bridge.
  - Does not mutate, inspect, or enrich `event.tags`.

---

## 4. Remediation Blueprint for "Paper of Record" Scoping

To allow `dkc.il.us.wun.iyou.me` to function as the scoped "Paper of Record":

1. **Host Ingress & CSRF (`config/settings.py`):**
   - Add `.wun.iyou.me` to `ALLOWED_HOSTS`.
   - Define `CSRF_TRUSTED_ORIGINS = ["https://wun.iyou.me", "https://*.wun.iyou.me"]`.
   - Set `SESSION_COOKIE_DOMAIN = ".wun.iyou.me"` in non-DEBUG mode.

2. **Middleware Registration:**
   - Implement `GeographicRoutingMiddleware` in `apps/core/middleware.py` (extracting `dkc.il.us` from `<scope>.wun.iyou.me`).
   - Register in `MIDDLEWARE` immediately after `SessionMiddleware`.
   - Expose `request.geographic_scope` in template contexts via `context_processors.py`.

3. **Nostr Query Containment (`apps/core/views.py`):**
   - In `api_feed` and `fetch_unified_feed`, if `request.geographic_scope` is active:
     - Add `filter_obj["#geo"] = [request.geographic_scope]` (or equivalent `#g` geohash).
   - In `attach_social_counts` and `api_feed`, include `1112` in `kinds` or issue a batch `#e` query for Kind 1112 to tally votes.

4. **Feed Card Rendering (`static/js/feed_interactions.js`):**
   - Update `renderNoteCard()` to render `.poll-vote-form` and radio options for Kind 30023.
   - Render vote tally distributions when `note.votes` is present.

5. **Client Signing Injection (`static/js/feed_interactions.js`):**
   - In `submitPost()` and `createPoll()`, read active geographic scope from `window.GEOGRAPHIC_SCOPE` (or `window.location.hostname`).
   - If active, automatically inject `["geo", activeScope]` into `event.tags` prior to signing.
