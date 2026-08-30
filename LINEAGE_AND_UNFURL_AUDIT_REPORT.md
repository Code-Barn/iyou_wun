# LINEAGE_AND_UNFURL_AUDIT_REPORT.md

Read-only diagnostic audit of the thread-lineage pipeline (`fetch_thread` / `build_thread_tree`), the Open Graph head scaffolding, and the 5-button reaction bar. No code was modified. Findings reference `repo-relative:path:line`.

---

## 1. NIP-10 Ancestor Lineage Resolution

### 1.1 How the backend tells root vs deep reply

`fetch_thread(thread_id)` (`apps/core/views.py:858`) loads the target event in isolation, then parses its `tags` with `parse_nip10_tags(tags)` (`apps/core/nip10.py:245`), which reads every `["e", <id>, <relay>, <marker>]` tag:

- marker `"root"` → `root_id` (`nip10.py:276`)
- marker `"reply"` → `parent_id` (immediate parent) (`nip10.py:278`)
- unmarked / legacy positional → first unmarked `e` becomes `parent_id`, and doubles as `root_id` when nothing else sets it (`nip10.py:281-285`)

So the classification is purely **tag-driven, per-event**: an event is a *reply* iff it has any `e` tag carrying a `"reply"`/`"root"` marker, or an unmarked `e` as its first positional tag (`nip10.py:402-408`). There is no DB/ancestry table; lineage is rederived from on-mesh event tags on every request.

### 1.2 Root / intermediate extraction (`event.tags`)

`parse_nip10_tags` returns `(root_id, parent_id, reply_marker, mention_ids, reply_to_pubkey)` and treats *every* `e` id as a mention (`nip10.py:274`). The default markers in NIP-10 (January 2024+ wording) are honored: `root`, `reply`, `mention`. The `p` tag is parsed for `reply_to_pubkey` (the "reply" `p` marker wins; else first `p`) at `nip10.py:286-290`.

**Constraint to keep in mind:** most relays only index what the client sent. A standard reply carries only `["e", <root>,"","root"]` + `["e", <parent>,"","reply"]` — the *intermediate chain between parent and root is not expressed in the child's tags* and must be recovered by walking each ancestor's own tags.

### 1.3 Does the relay query fetch the full ancestor chain?

**No — it clips.** Target's own tags feed `ancestor_ids = [root_id, parent_id]` (`views.py:871-875`) and exactly those ids (plus target) are fetched (`views.py:877-879`).

The ancestor walk (`views.py:930-943`) then does:
```
curr = thread_root.parent_id → walk curr = anc.parent_id, inserting at position 0
```
Because only `root` and `parent` were fetched, a 3+-hop chain (`target → P → G → root`) breaks at `G`: `G` is not in `all_enriched`, so `anc = all_enriched.get(curr_id)` returns `None` and the loop `break`s (`views.py:938-943`). The `root_id` fallback at `views.py:940-941` only helps when an ancestor carries its own `root` tag that happens to match an already-fetched event.

**Verified behavior:** root + immediate parent resolve; **any intermediate ancestors are silently omitted** (they never render in the ancestor deck).

### 1.4 Descendant query over-reads, then under-attaches

`descendants_raw = relay_req({"#e": [thread_id, root_id], "kinds":[1,1111], "limit":100})` (`views.py:885`). Nostr `#e` matching is *any-match*, so this returns:
- direct replies (reference `thread_id`), **and**
- every deeper descendant that still carries the root `e`-tag — i.e. the whole thread, often including replies from *other* branches off `G`/ancestors.

But the attach pass (`views.py:946-969`) only keeps events whose `parent_id == thread_id` (or a bare `root_id == thread_id`). Everything deeper is fetched then **discarded**; deep branches are only reachable through the per-reply `?thread=<id>` drill-down (feed.html:87-91). Weirdly, “orphan promotion” for clipped batches exists in `build_thread_tree` (`nip10.py:446-453`) but not here.

Also: `reply_count` set to `len(direct_replies)` (`views.py:969`) is the *direct* count, while the drill-down pill relies on `reply.reply_count` from `parent_cite_counts` (`views.py:946-951`), which is also 1-hop only.

### 1.5 Where ancestor cards attach in the view context

They already have a home and render in correct chronological order:

- `FeedView.get_context_data()` (`views.py:117`) puts `context["ancestors"]` (a list built `[grandparent, ..., parent]` by `insert(0,...)`, so oldest-first) alongside `thread_root`.
- `feed.html:43-51` renders them top-to-bottom *before* the hero card in a `border-l-2` indented ladder, delegating each card to `_thread_post.html` with `is_ancestor=True`.

So the *rendering slot* is done; the only gap is populating intermediate ancestors (see § modifications).

### 1.6 Required modifications

**`apps/core/views.py` — `fetch_thread`:**

1. Make the ancestor walk *recursive and relay-backed*. After enriching `target + root + parent`, walk upward; whenever the next ancestor id is missing from `all_enriched`, issue a follow-up `relay_req({"ids": [missing], ...})` and fold results into `combined`/`all_enriched` before continuing. Loop until the walk returns no new id or hits `thread_root`/`visited_ancestors` (guard against cycles — `visited_ancestors` already exists at `views.py:933`).
2. Bound depth (e.g. `MAX_ANCESTOR_DEPTH = 32`) so a pathological reply doesn't fan out N sequential round-trips.
3. Optionally de-duplicate the `#e` descendant query by *target only* and instead augment direct replies with a second pass that re-keys `parent_cite_counts` for 2-hop (grand-parented) replies when the missing intermediate ids get resolved.

**`apps/core/nip10.py` — `parse_nip10_tags` (no change required for correctness), plus a new helper used by the fetch walk:**

4. Add `resolve_ancestor_ids(event)` → ordered `[root, ...intermediate from tags..., parent]` that returns every distinct `e`-tag id in tag order, so the fetch loop can request *all* known chain members in one batched `ids` query instead of 1-hop, 1-hop, 1-hop.
5. Keep `build_thread_tree` untouched for the flat feed path; it already promotes orphaned replies (`nip10.py:446-453`) and sorts `reply_map` ascending (`nip10.py:434-436`).

**Verification hook:** `apps/core/tests/test_feed.py:387` asserts `reply["root_id"] == "root_post"` for the tree builder — extend with a 3-hop `target → P → G → root` fixture and assert `fetch_thread` returns `ancestors == [root, G, P]`.

---

## 2. Open Graph & Social Card Scaffolding

### 2.1 Current `<head>` state

`templates/base.html:4-37` is nearly bare of social meta:

- `<title>{% block title %}` overridable sub-block only.
- `{% block extra_head %}{% endblock %}` at `base.html:36` is the only head extension point.
- **No `og:*`, no `twitter:*`, no canonical, no `meta[name=description]`.**

`feed.html` overrides `{% block title %}` (`feed.html:4`) but its `extra_head` (`feed.html:6-13`) injects only a `<style>` block. `profile.html`/`gallery.html` follow the same pattern. Nothing emits social tags on any route.

### 2.2 Fields available per view for generating tags

**Thread/feed mode — `FeedView`:** `context["thread_root"]` is a fully enriched hero note (`_enrich_root`, `views.py:466`) exposing:
- `author_name` / `npub` / `nip05` → `og:title` author segment
- `content` + `display_content` → `og:description` (plaintext, media URLs already stripped by `extract_media_from_note` `nip10.py:231-239`; sanitizable with existing `sanitize_event_content`)
- `author_avatar` / `media_attachments[0].url` / `file_url` (Kind 1063) → `og:image`
- `id` and route `feed` → canonical `og:url`

**Profile — `ProfileView`:** `context["profile"]` from `fetch_profile_data` (`views.py:561`) carries `name`, `display_name`, `about`, `picture`, `banner`, `nip05`; plus `owner_deck` / `deck_items` and `profile_handle`.

**Gallery — `GalleryView`:** `context["notes"]`, `context["images"]` (each note has `media_attachments[].url`), `filter_pubkey`. First image thumbnail is the natural `og:image`.

### 2.3 `request.build_absolute_uri()` behind the proxy

`config/settings.py` already enables the two settings that make it work:
- `USE_X_FORWARDED_HOST = True` (`settings.py:50`) → `get_host()` honors `X-Forwarded-Host`.
- `SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")` (`settings.py:49`) → `is_secure()` ⇒ `build_absolute_uri()` builds `https://`.

Caveats for prod (Traefik/Cloudflare):
- the proxy must send **both** `X-Forwarded-Proto: https` **and** `X-Forwarded-Host` on every origin request; Cloudflare sends proto by default, host is proxied via `Host` normally — confirm Traefik middleware strips `X-Forwarded-*` from *inbound* client headers to prevent spoofing (this trust boundary is exactly why `SECURE_PROXY_SSL_HEADER` must only be active when behind the proxy);
- if a load balancer *also* rewrites `Host`, `X-Forwarded-Host` may double-hop — verify `og:url` on one production share;
- safest design: compute `og:url = request.build_absolute_uri(request.path)` server-side in each view (`ProfileView` uses `request.path` with the `@handle`/npub; `feed.html` appends `?thread=<id>` — better: emit `og:url` for the dedicated `/feed?thread=<id>`).

### 2.4 Template block inheritance strategy

Use a dedicated overridable block, not piggybacking `extra_head` (which is already used for CSS):

1. **`base.html` head** — add defaults guarded by the block, so unscoped pages still unfurl:
   ```
   {% block og_tags %}
   <meta property="og:type" content="website">
   <meta property="og:title" content="iyou_wun — Omni-Social Mesh">
   <meta property="og:description" content="...">
   <meta property="og:image" content="{% static 'img/iyou_symbol.png' %}">   <!-- Phase 16 branded fallback -->
   <meta property="og:url" content="{{ request.build_absolute_uri }}">
   <meta name="twitter:card" content="summary_large_image">
   <meta name="twitter:site" content="@...">
   {% endblock %}
   ```
2. **`feed.html`** — override `{% block og_tags %}`: in thread mode emit `article` type with `thread_root` fields (author avatar or first media attachment → `og:image`, content snippet → `og:title`/`og:description`); in feed mode keep base defaults but emit `og:url` for the current circle.
3. **`profile.html`** — override with `profile.name`/`about`/`picture` (fallback to `iyou_symbol.png`) and `og:type=profile`.
4. **`gallery.html`** — override with first `images[0]` thumbnail, `summary_large_image` card.

The block-in-head pattern keeps every page’s tags server-rendered (crawlers never execute the SPA/infinite-scroll JS), which is the requirement for Facebook/X/Discord/iMessage unfurls.

---

## 3. Reaction Bar UI & Icon Inventory

### 3.1 Where emojis live today

| Slot | HTML `_thread_post.html` | JS `buildCardHtml` (`feed_interactions.js`) | Emoji |
|---|---|---|---|
| Reply | `:200` `<span>💬</span>` | `:524` `><span>💬</span><` | 💬 |
| Repost | `:214` `<span>🔁</span>` | `:525` | 🔁 |
| Like | `:220` `<span class="heart-icon">❤️</span>` | `:526` `<span class="heart-icon">❤️</span>` | ❤️ |
| Contextual (Zap/Vote) | `:229` `<span>🗳️ Vote / ⚡ Tip</span>` | `:527` | 🗳️ / ⚡ |
| Share | `:235` `<span>↗️</span>` | `:528` | ↗️ |

Related emoji surfaces for consistency (not in the 5-bar but share the same glyph vocabulary): kebab menu `💡🏆🛡️📄🔗` (`_thread_post.html:70-84`, JS `:514-519`), media fallbacks 🎵📎, `notification_manager.js:23` `KIND_ICONS`, `toast_manager.js:9-10`.

### 3.2 Container sizing / state-fill hooks already present

- All five buttons share `class="action-btn-{reply|repost|like|...} flex items-center gap-1.5 px-2 py-1 rounded hover:bg-* transition-colors"` — a `.action-svg` child sized `w-3.5 h-3.5` drops straight in.
- Like state already flips classes dynamically: `likeNote` adds `text-pink-600 dark:text-pink-400 font-bold` to the *button* (`feed_interactions.js:1172`) — with an SVG you just add `text-pink-600 fill-pink-500` on the `<svg>` and it inherits from the button.
- Repost flips `text-emerald-600 dark:text-emerald-400 font-bold` (`:1203`). Zap/Share/JVote have hover colors (`text-amber-*`, `text-blue-*`) but no active state.
- Dark theme handled via existing `dark:` utilities everywhere; no extra CSS needed if icons use `fill="currentColor"`.

### 3.3 Proposed SVG icon set (Lucide-style stroke paths, `fill="none" stroke="currentColor" stroke-width="2"`)

| Icon | `viewBox` | Path(s) |
|---|---|---|
| Reply 💬 | `0 0 24 24` | `M8 12h8M12 8v8` over bubble: `M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z` |
| Repost 🔁 | `0 0 24 24` | `M17 2l4 4-4 4` + `M3 11v-1a4 4 0 0 1 4-4h14` + `M7 22l-4-4 4-4` + `M21 13v1a4 4 0 0 1-4 4H3` |
| Like ❤️ (filled variant) | `0 0 24 24` | stroke: `M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z`; filled state: same path with `fill="currentColor"` |
| Zap ⚡ | `0 0 24 24` | `M13 2L3 14h9l-1 8 10-12h-9l1-8z` (fill for amber pulse) |
| Vote 🗳️ | `0 0 24 24` | `M18 8h2a1 1 0 0 1 1 1v11a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V9a1 1 0 0 1 1-1h2` + `M8 4h8v4H8z` |
| Share ↗️ | `0 0 24 24` | `M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6` + `M15 3h6v6` + `M10 14L21 3` |

(Wire-frames shown; finalize pixel-for-pixel against the Heroicons viewer when implementing.)

### 3.4 Class mapping for `_thread_post.html` + `feed_interactions.js`

Replace `<span>💬</span>` etc. with:
```html
<span class="action-svg w-3.5 h-3.5 shrink-0"><svg ...>...</svg></span>
```
and drive state purely from the button:
- Reply active (editor open): `text-violet-600`
- Repost active: `text-emerald-600 dark:text-emerald-400` + `rotate-180 transition-transform duration-500` on the `.action-svg` wrapper (`repostNote` already flips classes — extend `:1203`)
- Like active: `text-pink-600 dark:text-pink-400` + `fill-pink-500` **on the svg** (`likeNote` icon swap instead of button-text-only `:1172`)
- Zap (Kind 30023 / lud16 / proposal): `text-amber-500` + `.animate-pulse` on hover
- Share: wire `shareNote` (`feed_interactions.js:1339`) — `navigator.share` already exists (`:1341`), keep clipboard fallback via `copyNotePermalink` (`:1328`)

Do the same string surgery in `buildCardHtml` at `feed_interactions.js:524-528` so client-side-inserted cards (reply optimistic insert `:316`, `addNoteToFeed`, gallery JS) match server-rendered cards. Because these icons are injected from JS, prefer **inline `<svg>` strings** (as the existing kebab/NIP-05 SVGs do) rather than a `<use href>` sprite.

---

## 4. Summary

1. **Lineage:** `fetch_thread` resolves only `target + root + parent`; intermediate ancestors are dropped (`views.py:930-943`). Fix = recursive relay fetch of missing ancestor ids + `resolve_ancestor_ids()` helper in `nip10.py`; rendering slot already exists at `feed.html:43-51` and is correctly ordered.
2. **Unfurling:** zero `og:*`/`twitter:*` tags exist; introduce an `{% block og_tags %}` in `base.html:36`-adjacent, override per view with already-enriched context (`thread_root`, `profile`, `images`), `og:image` defaulting to `static/img/iyou_symbol.png`. `build_absolute_uri` is proxy-safe today given `settings.py:49-50` and upstream `X-Forwarded-*` hygiene.
3. **Icons:** all 5-bar glyphs are emojis rendered in `_thread_post.html:200-235` and mirrored in `feed_interactions.js:524-528`; replace with `.action-svg` inline SVGs, drive colors via existing button state classes (`likeNote:1172`, `repostNote:1203`), and extend `shareNote:1339` for the native Web Share sheet (already implemented).