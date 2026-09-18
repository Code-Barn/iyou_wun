# Sovereign Moderation Shield & Node Takedown Engine Specification

**Specification Identifier:** `OMNI-SHIELD-SPEC-V1`  
**Hub:** `omni_social` / `iyou_wun`  
**Status:** Canonical Standard  
**Published:** 2026-09-18  
**Target Implementers:** `iyou_wun`, `iyou_home`, `iyou_idp`, `omni_social` satellites  

---

## 1. Executive Summary & Core Philosophy

Decentralized social networks built on Nostr and Blossom solve the existential threats of platform lock-in, shadowbanning, and centralized identity expropriation. In a pure sovereign mesh, content is cryptographically signed by user Decentralized Identifiers (DIDs) / Schnorr keypairs and gossiped across independent relays, while binary assets are content-addressed by SHA-256 digests.

However, sovereign node operators run physical infrastructure in specific legal jurisdictions. Operators face statutory liabilities, including:
- Digital Millennium Copyright Act (DMCA §512) notice-and-takedown obligations;
- EU Digital Services Act (DSA) illegal content mitigation mandates;
- Local child sexual abuse material (CSAM), non-consensual imagery, malware, or extortion statutes;
- Hosting provider and cloud infrastructure Terms of Service constraints.

The **Sovereign Moderation Shield** resolves the fundamental tension between **protocol-level censorship resistance** and **node-level safe harbor compliance**. 

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                             UPSTREAM PROTOCOL LAYER                         │
│   • Decentralized Nostr Relays (nos.lol, relay.iyou.me, relay.damus.io)    │
│   • Sovereign Keypairs & DIDs (secp256k1, Ed25519)                          │
│   • Global Blossom Network (cdn.iyou.me, nostr.download)                   │
│   ─── Immutable, Censorship-Resistant, Cryptographically Sovereign ───      │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │ Ingestion / Subscriptions
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                          NODE INSTANCE LAYER (iyou_wun)                     │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │                    SOVEREIGN MODERATION SHIELD                        │  │
│  │  • NodeBlockedEntity (Pubkey / DID / Domain Suppression)              │  │
│  │  • NodeContentTakedown (Event ID & Media Hash Suppression)            │  │
│  │  • In-Memory Shield Cache (`apps/core/moderation.py`)                 │  │
│  │  • Blossom Port 9002 REST DELETE Media Scrubber                      │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│                                      │                                      │
│        ┌─────────────────────────────┴─────────────────────────────┐        │
│        ▼                                                           ▼        │
│  ┌───────────────┐                                           ┌───────────┐  │
│  │  Social Feed  │                                           │ Civic     │  │
│  │  & Discovery  │ (Filtered by Shield)                      │ Polling   │  │
│  │  (/feed, API) │                                           │ (/api/    │  │
│  └───────────────┘                                           │  vote)    │  │
│                                                              └─────┬─────┘  │
└────────────────────────────────────────────────────────────────────┼────────┘
                                                                     ▼
                                                         Strictly Decoupled:
                                                         Poly Engine (:8002)
                                                         (Shield CANNOT block)
```

---

## 2. Architectural Scope

### 2.1 Instance-Level Defensive Kill-Switch

The Sovereign Moderation Shield is strictly an **instance-level defensive kill-switch** operating within the boundaries of the local `iyou_wun` satellite.

1. **Defensive Safe Harbor:** The shield provides the node operator with the administrative controls required to immediately halt the processing, projection, indexing, caching, and serving of illegal, infringing, or non-compliant content.
2. **Local Interface Boundary:** Enforcement occurs at the edge of the node's user-facing services:
   - Web feeds (`FeedView`, `api_feed`);
   - Thread lineage views (`fetch_thread`, note hero drill-down);
   - Profile notes and gallery views (`api_profile_notes`, `api_gallery`);
   - Search indexing and progressive search dropdowns (`api_search`);
   - Local Blossom media server filesystem (`http://127.0.0.1:9002/`).

### 2.2 Cryptographic Non-Infringement & Upstream Independence

The shield MUST NOT compromise or attempt to compromise upstream protocol integrity:
- **No Upstream Relay Tampering:** The node DOES NOT broadcast synthetic deletion events or tombstone records masquerading as network consensus. Events on third-party Nostr relays remain unmodified.
- **No DID Key Invalidation:** The node DOES NOT and CANNOT revoke, alter, or seize user cryptographic keypairs (`did:key:...` or Nostr secp256k1 pubkeys). Cryptographic ownership remains intact.
- **Zero Network Censorship:** An entity or event suppressed on `iyou_wun` instance $A$ remains discoverable on independent instance $B$ or native Nostr desktop/mobile clients querying the relay mesh directly.
- **Operator Self-Defense Exclusivity:** The engine’s sole jurisdiction is the local node's digital footprint and physical disks.

---

## 3. Database Architecture & The Postgres Indexing Invariant

### 3.1 The Canonical Rule: "Postgres is for Indexing, Not Ownership"

The ecosystem enforces a strict architectural invariant:
> **Relational databases serve exclusively as transient local projection caches. The canonical source of truth consists exclusively of signed Nostr events and content-addressed Blossom blobs. Postgres owns nothing.**

In the context of the Moderation Shield:
1. **Disposable Suppression Indices:** The suppression tables (`NodeBlockedEntity`, `NodeContentTakedown`) are disposable local indices rather than authoritative state.
2. **Crash & Purge Resilience:** A node operator can execute `DROP DATABASE`, re-provision PostgreSQL, run standard migrations, and re-import or re-index without corrupting sovereign identities or user assets.
3. **Canonical Identifier Anchoring:** Records reference universal cryptographic primitives:
   - 64-character hexadecimal Nostr pubkeys (`nostr_pubkey`);
   - W3C Decentralized Identifiers (`entity_did`);
   - 64-character hexadecimal Nostr Event IDs (`event_id`);
   - SHA-256 hexadecimal digests for Blossom media (`media_sha256`).
   No synthetic database auto-increment IDs are treated as universal foreign keys across systems.

### 3.2 Data Models (`apps/core/models.py`)

#### `NodeBlockedEntity`
Suppresses all incoming and cached content produced by a specific cryptographic actor or domain.

```python
class NodeBlockedEntity(models.Model):
    ENTITY_TYPE_CHOICES = [
        ("pubkey", "Nostr Pubkey (64-hex)"),
        ("did", "Decentralized Identifier (DID)"),
        ("domain", "Domain / NIP-05"),
    ]

    identifier = models.CharField(
        max_length=512,
        unique=True,
        db_index=True,
        help_text="Target 64-hex pubkey, DID URI, or NIP-05 domain to suppress.",
    )
    entity_type = models.CharField(
        max_length=16,
        choices=ENTITY_TYPE_CHOICES,
        default="pubkey",
    )
    reason = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Operator reason or legal classification (e.g. DMCA, CSAM, Spam, Harassment).",
    )
    legal_reference = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="External case number, court order ID, or takedown notice ticket.",
    )
    blocked_by_did = models.CharField(
        max_length=512,
        help_text="Sovereign DID of the operator who enacted this block.",
    )
    is_active = models.BooleanField(
        default=True,
        db_index=True,
        help_text="Whether this block rule is actively enforced.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Node Blocked Entity"
        verbose_name_plural = "Node Blocked Entities"

    def __str__(self):
        return f"<NodeBlockedEntity {self.entity_type}:{self.identifier[:16]}... active={self.is_active}>"
```

#### `NodeContentTakedown`
Suppresses specific message events or purges/blocks specific media blobs.

```python
class NodeContentTakedown(models.Model):
    TAKEDOWN_TYPE_CHOICES = [
        ("event", "Nostr Event"),
        ("media", "Blossom Media Blob (SHA-256)"),
        ("both", "Event & Associated Media"),
    ]

    target_id = models.CharField(
        max_length=64,
        unique=True,
        db_index=True,
        help_text="Nostr Event ID (64-hex) or Blossom Blob SHA-256 (64-hex).",
    )
    takedown_type = models.CharField(
        max_length=16,
        choices=TAKEDOWN_TYPE_CHOICES,
        default="event",
    )
    author_pubkey = models.CharField(
        max_length=64,
        blank=True,
        default="",
        db_index=True,
        help_text="Author pubkey (if known) for correlation.",
    )
    media_sha256 = models.CharField(
        max_length=64,
        blank=True,
        default="",
        db_index=True,
        help_text="Specific Blossom SHA-256 hash scrubbed.",
    )
    reason = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Statutory ground or takedown justification.",
    )
    legal_reference = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Court order, DMCA notice ID, or law enforcement docket.",
    )
    taken_down_by_did = models.CharField(
        max_length=512,
        help_text="Sovereign DID of the operator who executed the takedown.",
    )
    scrubbed_from_blossom = models.BooleanField(
        default=False,
        help_text="Indicates whether REST DELETE was confirmed against local Blossom daemon (:9002).",
    )
    is_active = models.BooleanField(
        default=True,
        db_index=True,
        help_text="Whether this takedown is actively suppressing content.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Node Content Takedown"
        verbose_name_plural = "Node Content Takedowns"

    def __str__(self):
        return f"<NodeContentTakedown {self.takedown_type}:{self.target_id[:16]}... active={self.is_active}>"
```

### 3.3 High-Performance In-Memory Filter Cache (`apps/core/moderation.py`)

Evaluating database rows for every note card across high-concurrency feeds creates intolerable $N+1$ query latency. `apps/core/moderation.py` implements an atomic in-memory cache layer:

```python
class ModerationShieldCache:
    """
    Thread-safe, in-memory cache of active suppression identifiers.
    Synchronized lazily with DB state or eagerly on desk mutations.
    """
    _instance = None
    _lock = threading.Lock()

    def __init__(self):
        self._blocked_pubkeys: set[str] = set()
        self._blocked_dids: set[str] = set()
        self._blocked_domains: set[str] = set()
        self._takedown_events: set[str] = set()
        self._takedown_media: set[str] = set()
        self._last_loaded: float = 0.0
        self._ttl: float = 60.0  # Periodic refresh fallback
```

- **Warmup:** Loaded on application startup and cached in memory.
- **Sub-Millisecond Check:** Checking `is_event_shielded(event)` performs zero SQL queries, doing set lookups:
  ```python
  event_id in cache.takedown_events or pubkey in cache.blocked_pubkeys
  ```
- **Cache Invalidation:** Any administrative mutation through `/desk/moderation/` immediately calls `moderation_shield_cache.invalidate()`, forcing a synchronous reload.

---

## 4. Decoupled Governance Invariant (The Poly Separation of Powers)

### 4.1 Constitutional Separation: Social Speech vs. Civic Franchise

A cornerstone of the sovereign media ecosystem is the constitutional separation between social media curation and democratic governance rights.

- **Social Feed Curation:** Node operators have the right and legal duty to curate, moderate, and suppress speech presented on their private domain or public web feed.
- **Democratic Franchise:** A user’s civic voting rights stem from their cryptographic DID, identity attestations, and verifiable credentials. Democratic franchise is NOT a privilege granted by a social media feed administrator.

### 4.2 Strict Isolation of `/api/vote` & `POLY_ENGINE_URL`

The headless Poly governance engine operates at `POLY_ENGINE_URL` (standard port `:8002`). Votes are cast via `POST /api/vote` in `apps/core/views.py`:

```
┌────────────────────────────────────────────────────────────────────────┐
│                        INGRESS REQUEST ROUTING                         │
└───────────────────┬────────────────────────────────┬───────────────────┘
                    │                                │
                    ▼                                ▼
     Social Feed Request (/feed, API)       Civic Ballot (/api/vote)
                    │                                │
                    ▼                                │
     ┌─────────────────────────────┐                 │
     │   Moderation Shield Gate    │                 │
     │  `filter_shielded_events()` │                 │
     │  Checks: NodeBlockedEntity  │                 │
     │          NodeContentTakedown│                 │
     └──────────────┬──────────────┘                 │
                    │ Passes                         │
                    ▼                                ▼
     ┌─────────────────────────────┐    ┌───────────────────────────┐
     │ Render Stream / JSON Cards  │    │ Direct Pass-Through:      │
     │                             │    │ Validate DID & Signature  │
     │                             │    │ Proxy to POLY_ENGINE_URL  │
     │                             │    │ (:8002) via PolyClient    │
     └─────────────────────────────┘    └───────────────────────────┘
                                                     │
                                         [SHIELD IS STRICTLY BYPASSED]
```

**Normative Invariant:**
> **The Sovereign Moderation Shield MUST NOT intercept, evaluate, or reject requests to `/api/vote`.**
> Even if a pubkey or DID is actively suppressed in `NodeBlockedEntity` or `NodeContentTakedown`, `api_cast_vote()` SHALL process their cryptographically signed vote envelope without prejudice.
> Social muting or legal takedowns SHALL NEVER disenfranchise a user from civic voting.

---

## 5. Blossom Media Scrubbing Engine

### 5.1 BUD-01 / BUD-02 REST DELETE Contract

The Blossom protocol defines content-addressed media storage. Media files uploaded by users are stored on the local media daemon at `http://127.0.0.1:9002/<sha256>`.

Under BUD-01 and BUD-02, the local daemon exposes a REST `DELETE` interface:

```http
DELETE /{sha256} HTTP/1.1
Host: 127.0.0.1:9002
Authorization: Nostr <base64-encoded-nip98-or-bud02-signed-event>
```

### 5.2 Local Storage Scrubbing Lifecycle

When a takedown order targeting media is processed at the Moderation Desk:

```
[Admin Desk: Takedown Action]
            │
            ├────────────────────────────────────────────────┐
            ▼                                                ▼
 1. Write `NodeContentTakedown`                    2. Issue REST DELETE Call
    target_id = <sha256>                              http://127.0.0.1:9002/<sha256>
    takedown_type = "media"                           (Local Media Daemon)
    scrubbed_from_blossom = False                            │
            │                                                ▼
            │                                     3. Local Disk Eviction
            │                                        File wiped from block store
            │                                                │
            │◀─────── Confirm 200/204 / 404 ─────────────────┘
            ▼
 4. Update `scrubbed_from_blossom = True`
 5. Invalidate In-Memory Shield Cache
 6. Return Clean Status to Admin Desk
```

### 5.3 Implementation Contract (`apps/core/moderation.py`)

```python
def scrub_blossom_media(sha256_hash: str, timeout: float = 3.0) -> bool:
    """
    Executes REST DELETE against the local Blossom daemon at port 9002.
    Confirms physical eviction of the blob from local node disks.
    """
    clean_hash = sha256_hash.strip().lower()
    daemon_url = f"http://127.0.0.1:9002/{clean_hash}"
    
    req = urllib.request.Request(daemon_url, method="DELETE")
    req.add_header("User-Agent", "iyou-wun-moderation-shield/1.0")
    
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status in (200, 204):
                logger.info(f"Successfully scrubbed Blossom blob {clean_hash} from local daemon.")
                return True
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            logger.warning(f"Blossom blob {clean_hash} already absent on daemon (404).")
            return True
        logger.error(f"HTTP error during Blossom scrubbing for {clean_hash}: {exc.code}")
    except Exception as exc:
        logger.error(f"Failed to connect to local Blossom daemon at {daemon_url}: {exc}")
    
    return False
```

### 5.4 Multi-Tier Media Proxy Defense

Even if an asset remains on public mirrors (`https://cdn.iyou.me/<sha256>`, `https://nostr.download/<sha256>`), the local node:
1. Refuses to proxy or serve the asset via `/media/` endpoints;
2. Filters out or censors `<img>` / `<video>` embeds pointing to `target_id == sha256`;
3. Ensures zero bytes of the contraband material exist on the operator's physical host storage.

---

## 6. Sovereign Access Control & Administration

### 6.1 `ADMIN_DID` Posture Evaluation

Administrative access to the Sovereign Moderation Shield is strictly guarded by the sovereign identity posture evaluation routine:

1. **Passwordless Ingress:** Password authentication is deprecated across the ecosystem. User authentication is managed exclusively via OIDC PKCE against `iyou_idp`.
2. **DID Matching:** In `apps/core/auth.py`, `_evaluate_admin_elevation()` compares the user's `sub` claim DID against `settings.ADMIN_DID`:
   ```python
   def _evaluate_admin_elevation(self, user, claims=None):
       if not user or user.is_anonymous:
           return user
       if user.username == getattr(settings, "ADMIN_DID", None):
           user.is_staff = True
           user.is_superuser = True
           user.save(update_fields=["is_staff", "is_superuser"])
       return user
   ```
3. **Staff Gating:** The administration views in `apps/core/views_admin.py` are strictly protected:
   ```python
   @user_passes_test(lambda u: u.is_authenticated and u.is_staff)
   def moderation_desk_view(request): ...
   ```

### 6.2 Administrative Desk (`/desk/moderation/`)

The Moderation Desk provides a dedicated workspace for the sovereign operator:
- **Entity Blocklist:** Add, toggle, or remove blocked Nostr pubkeys, DIDs, or NIP-05 domains.
- **Content Takedowns:** Enter specific 64-hex Nostr Event IDs to instantly scrub from all feeds and thread discussions.
- **Media Purge Tool:** Enter a 64-hex Blossom SHA-256 hash to trigger an immediate port 9002 `DELETE` call and blacklist the hash locally.
- **Audit Logs:** Full visibility into `blocked_by_did`, `taken_down_by_did`, timestamps, and legal references (`legal_reference`).

### 6.3 UI Partial (`templates/admin/moderation_desk.html`)

The UI partial integrates seamlessly into the ecosystem's dark-mode Tailwind CSS aesthetic:
- **Status Banners:** Real-time metrics for active blocked entities, suppressed events, and scrubbed media blobs.
- **Cyber-Grit Styling:** Zinc/slate backgrounds (`bg-zinc-900/80`), emerald accents for active safe harbors, rose accents for immediate takedowns.
- **One-Click Actions:** Unblock, restore, or export suppression rules as portable JSON configuration snapshots.

---

## 7. Integration & Enforcement Points

### 7.1 The Filter Shield Routine (`apps/core/moderation.py`)

The primary enforcement hook is `filter_shielded_events(events)`:

```python
def filter_shielded_events(events: list[dict]) -> list[dict]:
    """
    Takes a list of Nostr event dicts (or note objects) and drops any
    event matching an active NodeBlockedEntity or NodeContentTakedown.
    """
    if not events:
        return []
    
    cache = ModerationShieldCache.get_instance()
    filtered = []
    
    for ev in events:
        event_id = ev.get("id", "")
        pubkey = ev.get("pubkey", "")
        
        # Check event takedown
        if event_id and event_id in cache.takedown_events:
            continue
            
        # Check pubkey block
        if pubkey and pubkey in cache.blocked_pubkeys:
            continue
            
        filtered.append(ev)
        
    return filtered
```

### 7.2 Hook Integration Across `apps/core/views.py`

1. **Feed View (`FeedView`):**
   Calls `filter_shielded_events()` on the unified feed list before passing notes to the template context.
2. **Feed API (`api_feed`):**
   Filters notes before JSON serialization, preventing raw suppressed events from reaching the client DOM.
3. **Thread Lookup (`fetch_thread`):**
   If the focused note or any ancestor/descendant note matches an active takedown, it is scrubbed or replaced with a standard `[Note withheld by instance safe harbor]` placeholder.
4. **Gallery API (`api_gallery`):**
   Media events containing `x` tags or URLs matching scrubbed SHA-256 hashes are omitted from the gallery stream.

---

## 8. Verification & Test Suite

The test suite in `apps/core/tests/test_moderation_shield.py` must achieve 100% pass rate across the following critical vectors:

1. **Model Persistence & Index Invariant:** Test CRUD on `NodeBlockedEntity` and `NodeContentTakedown`. Verify that dropping tables does not affect user credentials or link decks.
2. **Filter Shield Execution:** Verify that notes authored by a blocked pubkey or matching a takedown ID are silently purged by `filter_shielded_events()`.
3. **Blossom Port 9002 DELETE Scrubbing:** Mock `urllib.request.urlopen` and verify correct REST `DELETE` invocation against `http://127.0.0.1:9002/<sha256>`.
4. **Decoupled Governance Immunity:** Verify that a user whose pubkey is in `NodeBlockedEntity` can still successfully post to `api_cast_vote` and have their vote proxied to `POLY_ENGINE_URL`.
5. **Access Control & Staff Security:** Verify that anonymous or non-staff users receive HTTP 302 or HTTP 403 when requesting `/desk/moderation/`, while users authenticated with `ADMIN_DID` are granted access.
6. **In-Memory Cache Invalidation:** Verify that modifying a record via the admin desk immediately updates the in-memory cache without requiring a server restart.
