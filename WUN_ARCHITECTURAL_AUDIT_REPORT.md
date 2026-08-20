# WUN Architectural Audit Report

**Date:** 2026-08-20 (updated from 2026-08-19)
**Original Scope:** Media Compartmentalization, Nostr Threading, Profile Persistence, Route Inventory
**Updated Scope:** Phases 1–5 completed; DID implementation audit added
**Constraint:** Original audit was read-only; subsequent phases modified files

---

## 1. Executive Summary

`iyou_wun` is a Django 5.2 OIDC Relying Party satellite with a sovereign Nostr-based social stack. The codebase has undergone five implementation phases since the original audit. **Four of five original debt categories are now resolved.**

### Original Debt Status

| # | Debt Category | Status | Resolution |
|---|---|---|---|
| 1 | Media Gallery — raw HTML5, no MIME-aware layout | **RESOLVED** | Phase 3: tabbed decks, masonry, lightbox, categorize_media() |
| 2 | Nostr Threading — flat single-level, NIP-10 markers ignored | **RESOLVED** | Phase 2: nip10.py, recursive tree, threaded feed layout |
| 3 | Profile Editing — missing fields, no bridge resilience | **RESOLVED** | Phase 1: 6 NIP-01 fields, hardened bridge_client.js singleton |
| 4 | Architecture — inline JS, duplicated bridge logic | **RESOLVED** | Phase 4: 3 static JS modules, templates reduced 73% |

### Remaining Debt

| # | Category | Severity | Notes |
|---|---|---|---|
| 5 | DID layer uses custom implementation, not `did_rust` submodule | See §7 | No external DID library; `cryptography` + `bech32` + string parsing |
| 6 | No base template (`base.html`) | LOW | 5 templates still duplicate head/nav/ecosystem bar boilerplate |
| 7 | No CSP headers | LOW | Inline JS eliminated but CSP not yet enabled |
| 8 | `POLY_ENGINE_URL` not injected to template context | MEDIUM | Hardcoded `127.0.0.1:8002` in `feed_interactions.js` |
| 9 | ConverseJS loaded from CDN | LOW | `chat.html` loads `https://cdn.conversejs.org/` |
| 10 | Debug `print()` statements in auth.py | LOW | Should use `logging` module |

### Health Rating

Functional for local/sovereign desktop use. Phases 1–4 resolved all critical structural debt. Remaining items are production-hardening (CSP, base template, logging) and the DID layer decision (§7).

---

## 2. Subsystem Matrix (Updated)

| Subsystem | Source Files | Current Behavior | Remaining Work |
|---|---|---|---|
| **Media Gallery** | `views.py` (`categorize_media`, `MEDIA_CATEGORIES`), `gallery.html`, `gallery_player.js` | Server-side MIME categorization; tabbed decks (All/Images/Videos/Audio/Other); masonry image grid; 16:9 video feed; inline audio players with scrubber; lightbox with metadata sidebar; keyboard nav (←/→/Esc) | Plyr.js integration, Wavesurfer.js, infinite scroll, download button |
| **Nostr Threading** | `nip10.py` (`parse_tags`, `build_thread_tree`), `views.py` (`process_into_feed` → threaded dict), `feed.html`, `_thread_post.html`, `feed_interactions.js` | NIP-10 `e` tag markers parsed (root/reply); recursive `roots[]` + `replies{}` dict; threaded layout with indented nested cards; `submitReply()` constructs Kind 1111 with `e`/`p` tags; `broadcastReplyToRelays()` | Multi-relay merge, live updates, depth-unlimited nesting |
| **Profile Editing** | `dashboard.html`, `bridge_client.js`, `views.py` (`fetch_profile_data`) | 6 NIP-01 fields (name, NIP-05, picture, banner, about, lud16); hardened bridge with mutex/timeout; pubkey validation; fallback modal; profile sync on connect | Broadcast retry queue, localStorage persistence |
| **Static Assets** | `static/js/bridge_client.js`, `feed_interactions.js`, `gallery_player.js`, `static/css/` | Tailwind CLI pre-compiled; 3 modular JS files; total 1,431 lines extracted from templates | Base template, CSP headers, ConverseJS local bundling |
| **DID Layer** | `did_kit.py`, `views.py` (bech32 functions), `pyproject.toml` | Custom implementation on `cryptography` + `bech32`; no `didkit` or `did_rust` | See §7 — decision needed on migration path |

---

## 3. Detailed Findings (Original — Status Updated)

### 3.1 Multi-Modal Media Rendering — RESOLVED (Phase 3)

**What was fixed:**
- `categorize_media()` in `views.py` categorizes Kind 1063 events by MIME type into `MEDIA_CATEGORIES` dict (prefix matching + extension fallback, case-insensitive)
- `fetch_media_assets()` enriched with `duration`, `blossom_hash`, `blurhash`, `summary`, `media_type` fields
- `GalleryView` is now public-read (no `LoginRequiredMixin`)
- Gallery tabbed by MIME type with counts; masonry image grid; 16:9 video feed; audio deck with inline `<audio>` players and scrubber
- Lightbox modal with metadata sidebar (file name, MIME, sovereign status, NIP-52 timestamps)
- Keyboard navigation (←/→/Esc)
- Single-instance media coordinator: switching tabs stops active audio/video
- NIP-94 tag extraction via `_extract_nip94_tags()`

**Remaining:** Plyr.js for custom video controls, Wavesurfer.js for audio waveforms, infinite scroll, download button.

### 3.2 Nostr Threading — RESOLVED (Phase 2)

**What was fixed:**
- `apps/core/nip10.py` created: `parse_tags()` extracts NIP-10 `e` tag markers (root/reply), `build_thread_tree()` builds recursive nested structure
- `process_into_feed()` returns `{"roots": [...], "replies": {parent_id: [note, ...]}, "total_replies": int, "flat": []}` dict
- `templates/includes/_thread_post.html` — shared threaded post renderer partial
- `feed.html` rewritten with threaded layout using nested `{% for %}` loops
- `feed_interactions.js` has `submitReply()` constructing Kind 1111 with `e`/`p` tags and `broadcastReplyToRelays()`
- 31 tests in `test_feed.py` covering threading + poll governance

**Remaining:** Multi-relay merge, live WebSocket updates, depth-unlimited nesting (currently capped by template recursion).

### 3.3 Sovereign Profile Persistence — RESOLVED (Phase 1)

**What was fixed:**
- Dashboard form: 6 NIP-01 fields (Display Name, NIP-05, Picture URL, Banner URL, Bio/About, Lightning Address)
- `bridge_client.js` singleton with mutex state machine, 5s timeout, `getEffectivePubkey()`, `signEvent()`, shared fallback modal
- Pubkey validation (64-char hex check)
- Profile sync on bridge connect (`get_profile` → `profile_sync`)
- `fetch_profile_data()` in `views.py` enriched with `banner` field
- Profile page: banner hero, NIP-05 badge, lud16 tip button
- Relay broadcast in parallel with per-relay success/failure toasts

**Remaining:** Broadcast retry queue with localStorage persistence.

### 3.4 Architecture & JS Modularization — RESOLVED (Phase 4)

**What was fixed:**
- `static/js/bridge_client.js` (361 lines): WebSocket mutex, signing, fallback modal, toast, relay utils
- `static/js/feed_interactions.js` (808 lines): Feed controller — posting, NIP-10 threading, Blossom media, poll governance
- `static/js/gallery_player.js` (262 lines): Tab switching, lightbox, media playback coordinator
- Templates reduced: `feed.html` 1,310→159 lines (−88%), `dashboard.html` 699→387 lines (−45%), `gallery.html` 534→128 lines (−76%)
- Total: 2,543→674 template lines (−73%)

**Remaining:** Base template for shared boilerplate, CSP headers.

---

## 4. DID Implementation Audit

### 4.1 Executive Finding

**The project does NOT use `didkit`, `pydidkit`, `did_rust`, or any external DID library.** The entire DID layer is a custom implementation totaling ~225 lines across two files, built on:

| Dependency | Version | Purpose |
|---|---|---|
| `cryptography` | 47.0.0 | Ed25519 key generation, signing, verification |
| `bech32` | 1.2.0 | Nostr npub ↔ hex pubkey conversion |

No `.gitmodules` file exists. No `did_rust` directory exists. No `didkit` import exists anywhere in the codebase.

### 4.2 DID Layer Architecture

```
┌─────────────────────────────────────────────────────┐
│                  DID Operations                      │
│                                                      │
│  did_kit.py (145 lines)     views.py (~80 lines)    │
│  ┌──────────────────────┐   ┌─────────────────────┐ │
│  │ Ed25519 key mgmt     │   │ did_to_pubkey()     │ │
│  │ ├─ get_node_signing  │   │ ├─ did:key:z... →   │ │
│  │ │  _key()            │   │ │  base64url decode  │ │
│  │ ├─ load_signing_key()│   │ │  strip multicodec  │ │
│  │ └─ get_public_key_   │   │ └─ return 32B hex   │ │
│  │    hex()             │   │                      │ │
│  │                      │   │ npub_to_hex()        │ │
│  │ VC Operations        │   │ ├─ bech32_decode()   │ │
│  │ ├─ build_unsigned_vc │   │ └─ convertbits(5→8) │ │
│  │ ├─ sign_vc()         │   │                      │ │
│  │ ├─ verify_vc_sig()   │   │ hex_to_npub()        │ │
│  │ └─ issue_vc()        │   │ ├─ convertbits(8→5) │ │
│  │                      │   │ └─ bech32_encode()   │ │
│  │ Crypto:              │   │                      │ │
│  │ cryptography.hazmat   │   │ did_to_npub()        │ │
│  │ └─ Ed25519PrivateKey │   │ ├─ did_to_pubkey()   │ │
│  │ └─ Ed25519PublicKey  │   │ └─ hex_to_npub()     │ │
│  └──────────────────────┘   └─────────────────────┘ │
└─────────────────────────────────────────────────────┘
```

### 4.3 DID Method Support

| DID Method | Format | Resolution Method | Cryptographic Verification |
|---|---|---|---|
| `did:key` | `did:key:z<base64url-multicodec-pubkey>` | **Inline extraction** — base64url decode, strip 2-byte multicodec prefix (`ed01` for Ed25519), return raw 32-byte pubkey | **Yes** — Ed25519 sign/verify via `cryptography` library |
| `did:iyou` | `did:iyou:0x<hex-pubkey>` | **Inline extraction** — strip prefix, hex-decode | **Partial** — pubkey extracted but no DID document resolution |
| `did:example` | `did:example:<opaque>` | **None** — test-only format | **No** |
| `did:web` | Not supported | N/A | N/A |
| `did:peer` | Not supported | N/A | N/A |

**Key limitation:** Resolution is entirely inline string parsing — no actual DID resolution (HTTP(S) DID resolution, DID document retrieval, or key agreement verification). This is acceptable for `did:key` (self-certifying) but would be insufficient for `did:web` or other methods requiring resolution.

### 4.4 What `did_rust` Would Provide (Not Currently Used)

The ecosystem standard routine imports a `did_rust` submodule. If integrated, it would provide:

| Capability | Current (custom) | With `did_rust` |
|---|---|---|
| `did:key` resolution | Inline base64url decode | Full DID document resolution |
| `did:web` resolution | Not supported | HTTP(S) DID document fetch |
| `did:peer` resolution | Not supported | Peer DID exchange |
| VC proof verification | Ed25519 only (cryptography lib) | Multi-algorithm via DID document |
| Key agreement | Not implemented | X25519 for encryption |
| DID document parsing | Not implemented | Full W3C DID Core spec |
| NIP-59 gift wrap | Not implemented | Seal + encrypt to recipient |
| secp256k1 support | Not implemented (Nostr keys) | Full secp256k1 operations |

### 4.5 Ed25519 Signing Deep Dive

All Ed25519 operations use `cryptography.hazmat.primitives.asymmetric.ed25519`:

```python
# Key generation (did_kit.py:24-28)
digest = hashlib.sha256(seed).digest()          # SHA-256 of WUN_SECRET_KEY
key = Ed25519PrivateKey.from_private_bytes(digest)

# Public key extraction (did_kit.py:32-36)
pub_bytes = private_key.public_key().public_bytes(
    encoding=serialization.Encoding.Raw,
    format=serialization.PublicFormat.Raw,
)

# VC signing (did_kit.py:97-99)
payload = _canonical_json(unsigned_vc) + _canonical_json(proof)
signature_hex = private_key.sign(payload).hex()

# VC verification (did_kit.py:112-117)
public_key = Ed25519PublicKey.from_public_bytes(bytes.fromhex(pubkey_hex))
public_key.verify(bytes.fromhex(proof_value_hex), payload)
```

**Proof type:** `Ed25519Signature2020` (W3C Data Integrity proof)
**Canonicalization:** Custom `_canonical_json()` — sorted keys, compact separators, no whitespace

### 4.6 Bech32 Conversion Chain

```
DID string                hex pubkey              npub string
─────────────            ─────────────           ─────────────
did:key:z6Mkpw...   →   did_to_pubkey()    →   hex_to_npub()
  │ base64url decode       │                      │
  │ strip multicodec       │                      bech32_encode("npub",
  │ return 32B hex         │                       convertbits(8→5))
  │                        │
  └── Used in:             └── Used in:
      auth.py                  views.py (profile URLs)
      test_auth.py             nip10.py (note author display)
      views.py (validation)    feed_interactions.js (via API)
```

### 4.7 Risk Assessment: DID Layer

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| `did:iyou` extraction works for current test vectors but may fail for edge cases (no DID doc) | Medium | Medium | Add `did:iyou` test vectors; consider `did_rust` for production |
| Ed25519 proof type mismatch with verifiers expecting `Ed25519Signature2018` or JSON Web Signature | Medium | Low | Current proof type matches ecosystem convention; verify with iyou_poly |
| secp256k1 Nostr keys cannot be used for VC signing (Ed25519 only) | Low | High | By design — VCs use DID key, not Nostr key |
| `did:web` / `did:peer` not supported | Low | Low | Not needed for current satellite scope |
| Custom `_canonical_json()` may diverge from W3C canonicalization spec | Low | Medium | Test against W3C VC test suite if needed |

### 4.8 Recommendation

The current custom DID layer is **fit for purpose** for the satellite's scope:
- `did:key` is self-certifying — inline extraction is correct
- Ed25519 signing/verification via `cryptography` is production-grade
- `bech32` conversion is standard Nostr protocol

**If/when the project needs** `did:web`, `did:peer`, NIP-59 gift wrap, or multi-algorithm VC verification, migrating to `did_rust` would be the correct path. Until then, the custom implementation has zero external attack surface and no native compilation dependencies.

---

## 5. Route Inventory (Updated)

| URL | View | Template | Auth | Notes |
|---|---|---|---|---|
| `/` | `home()` | redirect → `/feed` | No | |
| `/feed` | `FeedView` | `feed.html` | No | Threaded NIP-10 layout |
| `/feed?thread=<id>` | `FeedView` | `feed.html` | No | Thread-focused view |
| `/dashboard` | `dashboard()` | `dashboard.html` | Yes | 6 NIP-01 fields |
| `/gallery` | `GalleryView` | `gallery.html` | **No** | Changed from Yes (Phase 3) |
| `/gallery?type=image` | `GalleryView` | `gallery.html` | No | MIME-filtered decks |
| `/profile/<npub>/` | `ProfileView` | `profile.html` | No | Banner hero, NIP-05, lud16 |
| `/chat` | `ChatView` | `chat.html` | Yes | Converse.js XMPP |
| `/api/feed` | `api_feed()` | JSON | Yes | JSON feed endpoint |
| `/api/relays` | `api_relays()` | JSON | Yes | GET/POST relay config |
| `/api/vote` | `api_cast_vote()` | JSON | Yes | POST signed vote envelopes |
| `/api/credentials/issue/` | `IssueCredentialView` | JSON | Yes+staff | VC issuance |
| `/api/config/` | `node_config()` | JSON | No | Public node identity |

---

## 6. File Reference Index (Updated)

| File | Lines | Role in Audit |
|---|---|---|
| `apps/core/views.py` | 930 | All server logic: feed, gallery (categorize_media, MEDIA_CATEGORIES), profile, threading, relay connections |
| `apps/core/nip10.py` | 213 | NIP-10 threading — parse_tags(), build_thread_tree() |
| `apps/core/did_kit.py` | 145 | Ed25519 key management, VC build/sign/verify (custom — no didkit) |
| `apps/core/models.py` | 29 | Only `IssuedCredential` — no social/event models |
| `apps/core/urls.py` | 31 | All app routes |
| `apps/core/context_processors.py` | 10 | Injects `idp_home_ws_url`, `xmpp_ws_url` |
| `apps/core/auth.py` | 125 | OIDC backend with debug prints |
| `apps/core/auth_pkce.py` | 88 | PKCE authentication views |
| `static/js/bridge_client.js` | 361 | TauriBridgeClient — WebSocket mutex, signing, fallback modal |
| `static/js/feed_interactions.js` | 808 | Feed controller — posting, NIP-10 threading, polls, Blossom |
| `static/js/gallery_player.js` | 262 | Gallery — tab switching, lightbox, media playback coordinator |
| `templates/feed.html` | 159 | Threaded feed layout + NIP-10 nested comments |
| `templates/dashboard.html` | 387 | Dashboard + Edit Profile (6 NIP-01 fields) |
| `templates/gallery.html` | 128 | Tabbed media decks + masonry + lightbox |
| `templates/profile.html` | 157 | Sovereign profile (banner hero, NIP-05, lud16) |
| `templates/chat.html` | 53 | Converse.js XMPP chat |
| `templates/poll_modal.html` | 73 | Poll creation modal |
| `templates/includes/_thread_post.html` | 103 | Shared threaded post renderer partial |
| `templates/includes/_standard_header.html` | 41 | Header with auth state |
| `templates/includes/_ecosystem_bar.html` | 47 | Sovereign mesh top bar (generated) |
| `config/settings.py` | 278 | All Django configuration (OIDC defaults updated) |
| `services/poly_client.py` | 59 | Poly governance HTTP client |
| `apps/core/tests/test_gallery.py` | 220 | 26 tests: MIME categorization + gallery context |
| `apps/core/tests/test_feed.py` | 327 | 31 tests: NIP-10 threading + poll governance |
| `tailwind.config.js` | 25 | Tailwind content paths + theme |
| `package.json` | 22 | npm scripts: build:css, watch:css |

**Total test count:** 115 across 5 modules — `test_auth` (17), `test_views` (21), `test_feed` (31), `test_issuance` (19), `test_gallery` (26).

---

## 7. Remaining Work (Post-Phase 5)

### High Priority

| Step | Task | Impact |
|---|---|---|
| 6.1 | **DID layer decision:** Evaluate `did_rust` integration vs. maintaining custom implementation (see §4.8) | Strategic |
| 6.2 | Inject `POLY_ENGINE_URL` and `BLOSSOM_URL` via context processor, replace hardcoded JS values | Correctness |
| 6.3 | Replace `print()` debug statements with `logging` module in `auth.py` | Production |

### Medium Priority

| Step | Task | Impact |
|---|---|---|
| 6.4 | Create `templates/base.html` — shared head, nav, ecosystem bar, Tailwind config, toast styles | Maintainability |
| 6.5 | Broadcast retry queue in `feed_interactions.js` (localStorage persistence) | Reliability |
| 6.6 | Add CSP headers after base template eliminates remaining inline patterns | Security |

### Low Priority

| Step | Task | Impact |
|---|---|---|
| 6.7 | Bundle ConverseJS locally (remove CDN dependency) | Offline resilience |
| 6.8 | Delete dead assets if still present (`_tailwind_safe_init.html`, stale constants) | Hygiene |
| 6.9 | Multi-relay fan-out and merge for feed/profile fetches | Performance |
| 6.10 | Django cache layer for relay fetches (60s profiles, 30s feeds) | Performance |
