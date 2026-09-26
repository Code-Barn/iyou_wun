# Sovereign Architecture & Product Roadmap (v1.0 → v1.1)

**Status:** Living Engineering Blueprint  
**Target Release:** v1.0 Pre-Release Stabilization → v1.1 Live Media & Governance  
**Repository:** `iyou_wun` (Social Hub Satellite)  
**Last Updated:** 2026-09-26  

---

## 1. The Architectural Topology & Root Friction

The friction experienced across deployments is rooted in a fundamental boundary mismatch between three distinct execution topologies:

### Topology Comparison Matrix

| Topology | Network Context | Local Enclave (`:9003`) | Signing Bridge (`:9001`) | Mesh Relay (`relay.iyou.me`) |
| :--- | :--- | :--- | :--- | :--- |
| **Local Dev**<br>*(Fully Functional)* | Browser at `http://127.0.0.1:8001` | • Direct `ws://127.0.0.1:9003`<br>• Zero-latency local gossip | • Direct `ws://127.0.0.1:9001`<br>• No mixed-content / PNA restrictions | Optional secondary peer |
| **Native Enclave Dispatch**<br>*(`iyou_home` Desktop)* | Tauri Rust Host on macOS/Linux | • Native loopback socket<br>• Local SQLite outbox | • Internal IPC / Unix domain socket / TLS bridge | Mesh synchronization uplink |
| **Remote Web Satellite**<br>*(The Sandbox Wall)* | Browser at `https://wun.iyou.me`<br>*(Running inside K3s Pod)* | • **BLOCKED** by loopback boundary<br>• Explicitly marked `DISABLED` | • **BLOCKED BY PNA** without pre-flight headers<br>• Triggers Safari sandbox kills | • Primary single source of truth<br>• Relies entirely on mesh gossip |

---

### The Private Network Access (PNA) Wall (`wun.iyou.me` → `home.iyou.me:9001`)

When Safari loads `https://wun.iyou.me` (public HTTPS), any fetch or WebSocket connection directed to `wss://home.iyou.me:9001` (which resolves to `127.0.0.1`) triggers an automatic W3C Private Network Access pre-flight check.

- **Failure Symptoms:**
  - Safari immediately aborts the connection with `The network connection was lost` or `Fetch API cannot load due to access control checks`.
  - The web composer hangs indefinitely on `"Waiting for Signature..."` before the user is presented with the approval popup.
- **Required Invariants:**
  1. The Rust HTTP/TLS router in `iyou_home` (`src-tauri/src/bridge.rs`) must explicitly answer the `OPTIONS` request on port 9001 with:
     ```http
     Access-Control-Allow-Origin: https://wun.iyou.me
     Access-Control-Allow-Methods: GET, POST, OPTIONS
     Access-Control-Allow-Headers: *
     Access-Control-Allow-Private-Network: true
     ```
  2. **Dual-Stack Socket Binding:** The Rust TLS server must bind to `[::]:9001` (dual-stack loopback) to prevent macOS IPv6/IPv4 lookup stalls where Safari attempts `::1` before falling back to `127.0.0.1`.
  3. **Signing Queue Buffer Flush:** `submit_ws_response` in Rust must flush its socket output buffers prior to unmounting `WsSignPopup.tsx` so Safari does not perceive a dropped connection at the exact moment of user approval.
  4. **Manual Paste Fallback UI:** If the WebSocket connection fails or times out, the web composer must seamlessly open a challenge/signature copy-paste modal rather than staying hung.

---

### The Local-Relay Isolation Wall (`127.0.0.1:9003`)

In remote deployments, `https://wun.iyou.me` displays `127.0.0.1:9003` as `Local Enclave (DISABLED)`:

- **The Issue:** The remote web application executing in the cluster cannot route packets to the user's local loopback relay.
- **Root Cause of Missing Feed Events:** When a user authored a note in `iyou_home`, `iyou_home` published only to its local port 9003. Because the event never bridged to `wss://relay.iyou.me`, the remote web satellite had no visibility into the note's existence.
- **Remediation:**
  1. **Dual-Broadcast Dispatch in `iyou_home`:** When `iyou_home` dispatches an event via the Quick Dispatcher, it must publish to both `ws://127.0.0.1:9003` AND `wss://relay.iyou.me` (or active mesh relays in outbox).
  2. **HTTPS Context Guard in `relay_pool.js`:** When `wun` is loaded over HTTPS, `relay_pool.js` automatically marks `127.0.0.1:9003` as unconnectable in the client pool without spamming retry errors or polluting the console.

---

## 2. Current Subsystem Status Matrix

| Subsystem | State / Health | Key Remaining Action |
| :--- | :--- | :--- |
| **Identity & DIDs** | 🟢 Stable | Polymorphic resolution (`/@handle`, `/profile/<hex>`), dual-candidate querying (`deck.nostr_pubkey` + DID-derived key). Wipe legacy test data on release. |
| **K3s Project Relay** | 🟢 Operational | Traefik HTTP/1.1 ALPN, 30s heartbeats, persistent SQLite WAL. Enable write permissions for authenticated mesh nodes. |
| **Desktop Enclave Bridge** | 🔴 Blocked by PNA | Port 9001 WebSocket listener. Add `Access-Control-Allow-Private-Network: true` header to OPTIONS pre-flight in `src-tauri/src/bridge.rs`. |
| **Relay Fleet Management** | 🟢 Stable | 9-relay catalog, public WAN disabled by default, circle-driven budgets. Suppress `127.0.0.1:9003` probing when on public HTTPS. |
| **Media Gallery** | 🟢 Verified | Kind 1 + 1063 ingestion, 3-pane theater expand, decoupled lightbox. Add in-app Blossom audio stream player. |
| **Feed Stream UI** | 🟢 Verified | Decoupled routing IDs, deduplicated sublabels, single-row dashboard tabs. Fix circle filter evaluation for `[ ⚡ iyou ]`. |

---

## 3. Release Stabilization & Debugging Punch List

Before onboarding external users or cutting the v1.0 release, these plumbing defects must be resolved and verified across the ecosystem:

### Track A: Desktop Enclave Bridge & Safari PNA Hardening (`iyou_home`)
- [ ] **PNA Pre-Flight Compliance:** Update `src-tauri/src/bridge.rs` so the HTTP router responds to `OPTIONS` on port 9001 with:
  ```http
  Access-Control-Allow-Origin: https://wun.iyou.me
  Access-Control-Allow-Methods: GET, POST, OPTIONS
  Access-Control-Allow-Headers: *
  Access-Control-Allow-Private-Network: true
  ```
- [ ] **Dual-Stack Socket Binding:** Ensure the Rust TLS server binds to `[::]:9001` to prevent macOS IPv6/IPv4 loopback stalls.
- [ ] **Signing Queue Buffer Flush:** Confirm that `submit_ws_response` in Rust flushes the response buffer before unmounting `WsSignPopup.tsx` so Safari doesn't see a dropped connection right as the user approves.
- [ ] **Manual Paste Fallback UI:** Ensure that if the WebSocket fails or times out, the web composer seamlessly opens the manual challenge/signature copy-paste modal rather than staying hung on "Waiting for Signature...".

### Track B: Relay Mesh Synchronization (`iyou_home` ↔ `relay.iyou.me`)
- [ ] **Dual-Broadcast Dispatch in `iyou_home`:** When `iyou_home` dispatches an event via the Quick Dispatcher, it must publish to both `ws://127.0.0.1:9003` AND `wss://relay.iyou.me` (or any active mesh relays configured in the user's outbox).
- [ ] **Write Permissions on `relay.iyou.me`:** Update the K3s cluster relay configuration so authenticated mesh peers can write Kind 1, Kind 0, and Kind 1063 events to `relay.iyou.me` instead of treating it as read-only.
- [ ] **HTTPS Context Guard in `relay_pool.js`:** When the web app is loaded over HTTPS, automatically mark `127.0.0.1:9003` as unconnectable in the client pool without spamming retry errors or polluting the console.

### Track C: Circle Filtering & Empty States (`iyou_wun`)
- [ ] **Inspect the `[ ⚡ iyou ]` Filter Rule:** Investigate why `[ ⚡ iyou ]` reports *"No notes from registered sovereign accounts found"* even when notes are returned. Audit `apps/core/views.py:fetch_unified_feed` and `static/js/circle_feed_filter.js` to verify how author DIDs are matched against `UserLinkDeck` records and ensure circle membership queries don't drop valid local authors.
- [ ] **Empty State Guidance:** When a circle returns empty, provide clear diagnostic text indicating whether the relay returned zero records or whether all returned notes were filtered out by the circle's trust criteria.

### Track D: Clean Database Genesis Ceremony
- [ ] **K3s PostgreSQL Wipe:** Wipe the remote subpath (`/var/lib/k3s-data/iyou-wun/postgres`) and run migrations fresh to clear out legacy test decks and constraint fragments.
- [ ] **Clean Account Provisioning:** Run a single, clean provisioning routine that registers primary identity `@dcbyers13` directly from the L1 public persona key, ensuring one-to-one parity between DID, Nostr pubkey, and Link Deck.

---

## 4. Product & Feature Roadmap (v1.0 → v1.1)

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           FEATURE ROADMAP                               │
├─────────────────┬───────────────────────────────────────────────────────┤
│ Phase 1: v1.0   │ • Enclave bridge PNA compliance                       │
│ Core Stability  │ • Outbox sync: iyou_home dispatches to relay.iyou.me  │
│                 │ • Clean database wipe & genesis provisioning          │
│                 │ • Single-row dashboard tabs & polymorphic profiles    │
├─────────────────┼───────────────────────────────────────────────────────┤
│ Phase 2: v1.1   │ • Sovereign Spaces (NIP-53 Signaling + LiveKit SFU)   │
│ Live Media &    │ • Age-Bracket Trust Ladder (U14 Gating / Adult WAN)   │
│ Governance      │ • Blossom auto-archival for ended Spaces              │
│                 │ • Converse.js XMPP token exchange (/api/chat/auth/)   │
└─────────────────┴───────────────────────────────────────────────────────┘
```

---

### Feature 1: Sovereign Spaces (Live Audio Mesh Specification)

Sovereign Spaces provides an open, decentralized live audio broadcasting mesh combining Nostr decentralized signaling with high-performance WebRTC SFU media forwarding.

```
┌──────────────┐   WHIP (Audio Ingress)   ┌──────────────────┐   WHEP / HLS (.m3u8)   ┌────────────────┐
│  Space Host  │ ───────────────────────> │  K3s LiveKit SFU │ ─────────────────────> │ Audience Peers │
└──────────────┘                          └──────────────────┘                        └────────────────┘
       │                                            │                                          │
       │ Kind 30311 (Room State)                    │ Concluded Audio                          │ Kind 1311
       ▼                                            ▼                                          ▼
┌──────────────────────────────────────────────────────────────────────────────────────────────────────┐
│                              Relay Mesh (wss://relay.iyou.me) & Blossom                              │
└──────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

1. **Signaling Protocol (NIP-53):**
   - **Room Lifecycle Management (Kind 30311 - Live Activity):**
     - Lifecycle states: `planned` → `live` → `ended`.
     - Roles defined via `p` tags with role markers: `["p", <pubkey>, <relay>, "Host"]`, `["p", <pubkey>, <relay>, "Speaker"]`.
     - Room metadata tags: `["d", <unique_room_id>]`, `["title", "..."]`, `["summary", "..."]`, `["starts", <timestamp>]`, `["streaming", <whip_url>]`.
   - **Live Synchronized Room Chat (Kind 1311):**
     - Ephemeral, synchronized live room chat anchored via `["a", "30311:<host_pubkey>:<d_identifier>"]`.
2. **Media Transport (LiveKit SFU in `k3s_vm`):**
   - Containerized WebRTC SFU (LiveKit or Galène) deployed via Helm in the K3s cluster.
   - Hosts broadcast audio over WHIP (WebRTC HTTP Ingress Protocol).
   - Listeners receive ultra-low-latency audio via WHEP (WebRTC HTTP Egress Protocol) or scaled HLS fallback (`.m3u8`).
   - Persistent mini-player audio dock embedded in the right rail across `/feed` and `/gallery` views.
3. **Blossom Archival & Audio Deck Hydration:**
   - When a space concludes, the SFU recording daemon automatically transfers the recorded audio file to Blossom storage (`cdn.iyou.me`).
   - The concluding Kind 30311 event transitions to `status = "ended"` with a permanent `["recording", "https://cdn.iyou.me/<sha256>"]` tag.
   - The recording immediately becomes playable in the **Media Gallery Audio Deck** (`/gallery#tab-audio`).

---

### Feature 2: Trust Ladder & Public Firehose Firewall

1. **Default-Safe Community:** All new accounts strictly participate in the `[ ⚡ iyou ]` circle. External WAN relays remain disabled by default.
2. **Age-Bracket Enforcement:**
   - **U14 / Dependent Accounts:** The Switchboard's external WAN relay toggles and the `[ 🌐 Global ]` circle tab are completely suppressed in the UI. All communications are gated to WoT distance $\le 1$.
   - **Adults (18+):** The Sovereign Switchboard provides a deliberate safety interstitial explaining the risks of unmoderated WAN content before unlocking external relay toggles.

---

### Feature 3: Native Messaging & Chat Dock

1. **XMPP Session Exchange (`/api/chat/auth/`):** Replace manual XMPP credential configuration with an authenticated backend endpoint that exchanges the user's active DID session for an ephemeral Prosody token.
2. **NIP-17 DM Fallback:** If a peer lacks an active XMPP JID, the chat dock automatically falls back to NIP-17 direct encrypted messaging routed through the mesh relays.

---

## 5. Track E Execution Milestones (v1.1 Sovereign Spaces)

- [ ] Deploy LiveKit / Galène SFU Helm chart in `k3s_vm`.
- [ ] Implement NIP-53 Kind 30311 / Kind 1311 parser in `iyou_wun` (`apps/core/spaces.py` / `nip53.py`).
- [ ] Add persistent bottom-dock mini-player for live spaces in the feed right rail (`_spaces_dock.html`).
- [ ] Implement Blossom audio recording archival on space completion and wire to Media Gallery Audio Deck.
