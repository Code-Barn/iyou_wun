/**
 * Dynamic NIP-65 Relay Pooling & Autonomous Failover Engine
 * 
 * Provides:
 * - Connection pooling with latency & health probing
 * - Sovereign local + decentralized public fallback bootstrap
 * - Parallel double/multi-broadcasting with fault tolerance
 * - Dynamic NIP-65 (kind: 10002) relay metadata ingestion
 * - Reactive UI health indicator updates
 */

(function (global) {
    "use strict";

    /**
     * Build the bootstrap relay pool.
     * The sovereign local relay (ws://127.0.0.1:9003) is only included when
     * running on a local HTTP dev origin (http://127.0.0.1:* or http://localhost:*).
     * Over HTTPS (production) we rely solely on the secure public pool so we never
     * push/read from an unencrypted mixed-content socket.
     */
    function isLocalDevOrigin() {
        if (typeof window === "undefined" || !window.location) return false;
        var protocol = String(window.location.protocol || "").toLowerCase();
        var hostname = String(window.location.hostname || "").toLowerCase();
        if (protocol !== "http:") return false;
        return hostname === "127.0.0.1" || hostname === "localhost" || hostname === "0.0.0.0";
    }

    function buildBootstrapRelays() {
        var relays = [
            { url: "wss://relay.iyou.me", read: true, write: true, primary: true },
            { url: "wss://nos.lol", read: true, write: true, primary: false },
            { url: "wss://relay.damus.io", read: true, write: true, primary: false },
            { url: "wss://relay.primal.net", read: true, write: true, primary: false }
        ];
        // The sovereign local loopback relay is ALWAYS retained in the pool so the
        // diagnostics drawer never loses the local enclave entry. On an HTTPS origin
        // browsers block plain ws:// sockets (mixed content), so it simply renders
        // as "Local Enclave (Desktop/WSS)" instead of being probed over the wire.
        relays.push({ url: "ws://127.0.0.1:9003", read: true, write: true, isLocal: true, primary: false });
        return relays;
    }

    var BOOTSTRAP_RELAYS = buildBootstrapRelays();

    var STORAGE_KEY = "wun_relays";
    var CUSTOM_STORAGE_KEY = "wun_custom_relays";
    var NIP65_STORAGE_KEY = "wun_nip65_relays";
    var PROBE_TIMEOUT_MS = 3500;
    var BROADCAST_TIMEOUT_MS = 4000;
    var PROBE_INTERVAL_MS = 45000;

    function normalizeUrl(url) {
        if (!url) return "";
        var u = String(url).trim();
        if (u.endsWith("/")) u = u.slice(0, -1);
        return u.toLowerCase();
    }

    function isSecureOrigin() {
        return typeof window !== "undefined" && window.location && String(window.location.protocol || "").toLowerCase() === "https:";
    }

    function isPlainWsUrl(url) {
        return String(url || "").toLowerCase().indexOf("ws://") === 0;
    }

    // Plain ws:// sockets are blocked by browser Mixed Content rules on an HTTPS
    // origin, so they are never probed/broadcast from a secure page.
    function isMixedContentRelay(url) {
        return isSecureOrigin() && isPlainWsUrl(url);
    }

    var MAX_BACKOFF_MS = 60000;
    var QUARANTINE_THRESHOLD = 3;   // consecutive drop/timeout failures to quarantine
    var QUARANTINE_COOLDOWN_MS = 90000; // re-probe window for quarantined relays

    function RelayPool() {
        this.relays = new Map(); // url -> { url, read, write, isLocal, primary, status, latencyMs, lastProbe, failCount }
        this.listeners = [];
        this.probeTimer = null;
        this._initPool();
    }

    RelayPool.prototype._initPool = function () {
        var self = this;

        // 1. Load Bootstrap Defaults
        BOOTSTRAP_RELAYS.forEach(function (r) {
            var norm = normalizeUrl(r.url);
            self.relays.set(norm, {
                url: r.url,
                read: r.read !== false,
                write: r.write !== false,
                enabled: r.enabled !== false,
                isLocal: !!r.isLocal || norm.indexOf("127.0.0.1") !== -1 || norm.indexOf("localhost") !== -1,
                primary: !!r.primary,
                status: "unknown",
                latencyMs: null,
                lastProbe: null,
                failCount: 0
            });
        });

        // 2. Load stored custom relays from localStorage
        var enabledMap = {};
        try {
            var stored = localStorage.getItem(STORAGE_KEY);
            try {
                var customStored = localStorage.getItem(CUSTOM_STORAGE_KEY);
                if (customStored) {
                    var customList = JSON.parse(customStored);
                    if (Array.isArray(customList)) {
                        customList.forEach(function (entry) {
                            var url = typeof entry === "string" ? entry : (entry && entry.url);
                            if (!url) return;
                            enabledMap[normalizeUrl(url)] = entry.enabled !== false;
                        });
                    }
                }
            } catch (e) { /* ignore */ }

            var bootstrapNorms = {};
            self.relays.forEach(function (r) { bootstrapNorms[normalizeUrl(r.url)] = true; });

            if (stored) {
                var list = JSON.parse(stored);
                if (Array.isArray(list)) {
                    list.forEach(function (entry) {
                        var url = typeof entry === "string" ? entry : (entry && entry.url);
                        if (!url) return;
                        var norm = normalizeUrl(url);
                        if (!bootstrapNorms[norm] && !self.relays.has(norm)) {
                            var enabled = entry.enabled !== false;
                            if (enabledMap.hasOwnProperty(norm)) enabled = enabledMap[norm];
                            self.relays.set(norm, {
                                url: url,
                                read: entry.read !== false,
                                write: entry.write !== false,
                                enabled: enabled,
                                isLocal: norm.indexOf("127.0.0.1") !== -1 || norm.indexOf("localhost") !== -1,
                                primary: false,
                                status: "unknown",
                                latencyMs: null,
                                lastProbe: null,
                                failCount: 0
                            });
                        }
                    });
                }
            }

            // A pure wun_custom_relays list (no wun_relays) still seeds the pool.
            if (enabledMap && Object.keys(enabledMap).length > 0) {
                customList.forEach(function (entry) {
                    var url = typeof entry === "string" ? entry : (entry && entry.url);
                    if (!url) return;
                    var norm = normalizeUrl(url);
                    if (!bootstrapNorms[norm] && !self.relays.has(norm)) {
                        self.relays.set(norm, {
                            url: url,
                            read: entry.read !== false,
                            write: entry.write !== false,
                            enabled: enabledMap[norm],
                            isLocal: norm.indexOf("127.0.0.1") !== -1 || norm.indexOf("localhost") !== -1,
                            primary: false,
                            status: "unknown",
                            latencyMs: null,
                            lastProbe: null,
                            failCount: 0
                        });
                    }
                });
            }
        } catch (e) { /* ignore */ }

        // 3. Load previously ingested NIP-65 relays
        try {
            var nip65Stored = localStorage.getItem(NIP65_STORAGE_KEY);
            if (nip65Stored) {
                var nip65Relays = JSON.parse(nip65Stored);
                if (Array.isArray(nip65Relays)) {
                    self.ingestNip65Tags(nip65Relays, false);
                }
            }
        } catch (e) { /* ignore */ }

        // Apply persisted enabled-state toggles to EXISTING pool records
        // (bootstrap + previously stored relays) so a disabled relay stays
        // demoted from read/write/broadcast loops across reloads instead of
        // reverting to the built-in enabled default.
        if (enabledMap && Object.keys(enabledMap).length > 0) {
            self.relays.forEach(function (r, norm) {
                if (enabledMap.hasOwnProperty(norm)) {
                    r.enabled = enabledMap[norm];
                    if (r.enabled === false) {
                        r.status = "offline";
                        r.lastProbe = null;
                    }
                }
            });
        }

        // 4. Initial probe and periodic probe
        if (typeof window !== "undefined") {
            setTimeout(function () { self.probeRelays(); }, 500);
            this.probeTimer = setInterval(function () { self.probeRelays(); }, PROBE_INTERVAL_MS);
        }
    };

    RelayPool.prototype.getRelays = function () {
        var urls = [];
        this.relays.forEach(function (r) {
            if (r.enabled === false) return;
            urls.push(r.url);
        });
        return urls;
    };

    RelayPool.prototype.getWriteRelays = function () {
        var urls = [];
        this.relays.forEach(function (r) {
            if (r.enabled === false) return;
            if (isMixedContentRelay(r.url)) return;
            if (r.write && r.status !== "quarantined") urls.push(r.url);
        });
        return urls.length > 0 ? urls : this.getRelays();
    };

    RelayPool.prototype.getReadRelays = function () {
        var urls = [];
        this.relays.forEach(function (r) {
            if (r.enabled === false) return;
            if (isMixedContentRelay(r.url)) return;
            if (r.read && r.status !== "quarantined") urls.push(r.url);
        });
        return urls.length > 0 ? urls : this.getRelays();
    };

    RelayPool.prototype.getRelayStatuses = function () {
        var list = [];
        this.relays.forEach(function (r) {
            list.push({
                url: r.url,
                read: r.read,
                write: r.write,
                isLocal: r.isLocal,
                primary: r.primary,
                status: r.status,
                latencyMs: r.latencyMs,
                lastProbe: r.lastProbe
            });
        });
        return list;
    };

    RelayPool.prototype.getActiveRelayCount = function () {
        var total = 0;
        var online = 0;
        var quarantined = 0;
        this.relays.forEach(function (r) {
            if (r.enabled === false) return;
            total++;
            if (r.status === "online") online++;
            else if (r.status === "quarantined") quarantined++;
        });
        return { online: online, total: total, quarantined: quarantined };
    };

    /**
     * Persist the full pool (with the Phase 33 object schema
     * `[{url, enabled, read, write}]`) so toggle state survives reloads.
     * The object schema is mirrored under `wun_custom_relays` while
     * `wun_relays` keeps a string-only list for legacy consumers.
     */
    RelayPool.prototype.persistRelays = function () {
        try {
            var list = [];
            var urls = [];
            this.relays.forEach(function (r) {
                list.push({
                    url: r.url,
                    enabled: r.enabled !== false,
                    read: r.read !== false,
                    write: r.write !== false
                });
                urls.push(r.url);
            });
            localStorage.setItem(CUSTOM_STORAGE_KEY, JSON.stringify(list));
            localStorage.setItem(STORAGE_KEY, JSON.stringify(urls));
        } catch (e) { /* ignore */ }
    };

    /**
     * Phase 33 — Relay Switchboard Toggle.
     * `window.toggleRelayState(relayUrl, isEnabled)` demotes a relay from every
     * active broadcast/subscription loop (read/write) and its diagnostics row,
     * or reconnects it back into the active pool. State is persisted under
     * `wun_custom_relays` and immediately reflected in #relay-health-widget.
     */
    RelayPool.prototype.toggleRelayState = function (relayUrl, isEnabled) {
        var norm = normalizeUrl(relayUrl);
        var record = this.relays.get(norm);
        if (!record) {
            this._addRelay(relayUrl, { read: true, write: true });
            record = this.relays.get(norm);
        }
        if (!record) return false;

        var nextEnabled = !!isEnabled;
        var changed = (record.enabled || true) !== nextEnabled;
        record.enabled = nextEnabled;

        if (!nextEnabled) {
            // Demote: close any lingering socket representation and drop from
            // active broadcast/subscription loops until re-enabled.
            record.status = "offline";
            record.lastProbe = Date.now();
        } else {
            record.failCount = 0;
            this.probeRelay(record.url);
        }

        if (changed) {
            this.persistRelays();
            this._notifyStatusChange();
            this._updateHealthUI();
            if (typeof window !== "undefined" && typeof window.showToast === "function") {
                window.showToast("Relay " + record.url + (nextEnabled ? " enabled" : " disabled"), nextEnabled ? "success" : "info");
            }
            var drawerEl = document.getElementById("relay-diagnostics-drawer");
            if (drawerEl && !drawerEl.classList.contains("hidden")) {
                this.renderDiagnosticsList();
            }
        }
        return nextEnabled;
    };

    /**
     * Quarantine a relay that has exceeded its consecutive-failure threshold.
     * The relay is demoted from the active read/write pool until an explicit
     * retry (or a healthy re-probe) clears it.
     */
    RelayPool.prototype._markQuarantined = function (url, via) {
        var norm = normalizeUrl(url);
        var record = this.relays.get(norm);
        if (!record) return;
        record.status = "quarantined";
        record.quarantineSince = Date.now();
        record.quarantineVia = via || "consecutive-failure";
        // Demote from active broadcast/read participation.
        record.write = false;
        record.read = false;
        this._notifyStatusChange();
        this._updateHealthUI();
    };

    RelayPool.prototype._pickFallbackRelay = function () {
        var self = this;
        var candidates = (typeof DEFAULT_RELAYS !== "undefined" && Array.isArray(DEFAULT_RELAYS) ? DEFAULT_RELAYS : BOOTSTRAP_RELAYS);
        for (var i = 0; i < candidates.length; i++) {
            var cand = typeof candidates[i] === "string" ? candidates[i] : candidates[i].url;
            var norm = normalizeUrl(cand);
            if (!norm) continue;
            var existing = self.relays.get(norm);
            // Prefer an unquarantined candidate not already in the pool,
            // else any candidate that is currently healthy/unknown.
            if (!existing) {
                self._addRelay(cand, { read: true, write: true });
                return norm;
            }
            if (existing.status === "online" || existing.status === "unknown") {
                return norm;
            }
        }
        return null;
    };

    RelayPool.prototype._addRelay = function (url, opts) {
        opts = opts || {};
        var norm = normalizeUrl(url);
        if (this.relays.has(norm)) return;
        this.relays.set(norm, {
            url: url,
            read: opts.read !== false,
            write: opts.write !== false,
            enabled: opts.enabled !== false,
            isLocal: !!opts.isLocal || norm.indexOf("127.0.0.1") !== -1 || norm.indexOf("localhost") !== -1,
            primary: !!opts.primary,
            status: "unknown",
            latencyMs: null,
            lastProbe: null,
            failCount: 0
        });
        this.probeRelay(url);
        this._notifyStatusChange();
    };

    /**
     * Called when a relay's broadcast fails (drop/timeout/error). Tracks a
     * rolling consecutive-failure window; once it exceeds QUARANTINE_THRESHOLD
     * the relay is quarantined and an unquarantined fallback relay is added.
     */
    RelayPool.prototype._recordBroadcastFailure = function (url) {
        var norm = normalizeUrl(url);
        var record = this.relays.get(norm);
        if (!record) return;
        record.failCount = (record.failCount || 0) + 1;
        record.lastProbe = Date.now();

        if (record.status !== "quarantined" && record.failCount >= QUARANTINE_THRESHOLD) {
            this._markQuarantined(norm, "broadcast-consecutive");
            // Auto-failover: bring in an unquarantined fallback relay.
            var fallback = this._pickFallbackRelay();
            if (fallback) {
                this.probeRelay(fallback);
                this._updateHealthUI();
            }
        } else {
            this._updateHealthUI();
        }
    };

    /**
     * Manually re-probe every quarantined relay; if it comes back online it is
     * restored to the active read/write pool. Exposed as window.retryQuarantinedRelays
     * for the mesh right rail.
     */
    RelayPool.prototype.retryQuarantinedRelays = function () {
        var self = this;
        var quarantinedUrls = [];
        this.relays.forEach(function (r) {
            if (r.status === "quarantined") quarantinedUrls.push(r.url);
        });
        if (quarantinedUrls.length === 0) {
            return Promise.resolve(0);
        }
        return Promise.all(quarantinedUrls.map(function (u) { return self.probeRelay(u); })).then(function (results) {
            var restored = 0;
            results.forEach(function (res) {
                if (res && res.status === "online") {
                    var norm = normalizeUrl(res.url);
                    var record = self.relays.get(norm);
                    if (record) {
                        record.read = true;
                        record.write = true;
                        record.failCount = 0;
                        record.quarantineSince = null;
                        restored++;
                    }
                }
            });
            if (restored > 0) {
                self._notifyStatusChange();
                self._updateHealthUI();
            }
            return restored;
        });
    };

    RelayPool.prototype.probeRelay = function (url) {
        var norm = normalizeUrl(url);
        var record = this.relays.get(norm);
        if (!record) return Promise.resolve({ url: url, status: "offline", latencyMs: null });

        // Disabled (switchboard toggle off) relays are never probed — demoted
        // until re-enabled. Prevents the periodic probe from flipping them back
        // to "online" and hitting the network on their behalf.
        if (record.enabled === false) {
            record.status = "offline";
            return Promise.resolve({ url: record.url, status: "offline", latencyMs: record.latencyMs });
        }

        // Plain ws:// relays (e.g. the loopback 127.0.0.1:9003 enclave) cannot be
        // probed from an HTTPS origin — the browser blocks the socket outright as
        // mixed content. Report them as the "Local Enclave" placeholder instead of
        // attempting (and failing) a real handshake every interval.
        if (isMixedContentRelay(url)) {
            if (record.status !== "unknown") {
                record.status = "offline";
            }
            return Promise.resolve({ url: record.url, status: record.status, latencyMs: record.latencyMs });
        }

        // Exponential backoff: if a relay has failed repeatedly, skip probing
        // until its backoff window elapses so we don't hammer an offline socket
        // and spam connection attempts.
        if (record.status === "offline" && record.failCount > 0) {
            var delay = Math.min(Math.pow(2, record.failCount - 1) * 1000, MAX_BACKOFF_MS);
            var elapsed = Date.now() - (record.lastProbe || 0);
            if (elapsed < delay) {
                return Promise.resolve({ url: record.url, status: record.status, latencyMs: record.latencyMs });
            }
        }

        var self = this;
        return new Promise(function (resolve) {
            var startTime = Date.now();
            var resolved = false;

            function finish(status, latency) {
                if (resolved) return;
                resolved = true;
                record.status = status;
                record.latencyMs = latency;
                record.lastProbe = Date.now();
                if (status === "online") {
                    record.failCount = 0;
                } else {
                    record.failCount = (record.failCount || 0) + 1;
                }
                self._notifyStatusChange();
                resolve({ url: record.url, status: status, latencyMs: latency });
            }

            try {
                var ws = new WebSocket(record.url);
                var timeout = setTimeout(function () {
                    try { ws.close(); } catch (e) {}
                    finish("offline", null);
                }, PROBE_TIMEOUT_MS);

                ws.onopen = function () {
                    var latency = Date.now() - startTime;
                    clearTimeout(timeout);
                    try { ws.close(); } catch (e) {}
                    finish("online", latency);
                };

                ws.onerror = function () {
                    clearTimeout(timeout);
                    try { ws.close(); } catch (e) {}
                    finish("offline", null);
                };
            } catch (err) {
                finish("offline", null);
            }
        });
    };

    RelayPool.prototype.probeRelays = function () {
        var promises = [];
        var self = this;
        this.relays.forEach(function (r) {
            promises.push(self.probeRelay(r.url));
        });
        return Promise.all(promises).then(function (results) {
            self._updateHealthUI();
            return results;
        });
    };

    /**
     * Ingest NIP-65 Kind 10002 tags or event
     * Tags format: [["r", "wss://...", "read"|"write"|undefined], ...]
     */
    RelayPool.prototype.ingestNip65Tags = function (tags, persist) {
        if (!Array.isArray(tags)) return;
        var self = this;
        var added = 0;
        var nip65Entries = [];

        tags.forEach(function (tag) {
            if (!Array.isArray(tag) || tag[0] !== "r" || !tag[1]) return;
            var url = tag[1].trim();
            if (!url) return;
            var mode = tag[2] ? String(tag[2]).toLowerCase() : null;
            var read = mode !== "write";
            var write = mode !== "read";
            var norm = normalizeUrl(url);

            nip65Entries.push(["r", url, mode || ""]);

            if (self.relays.has(norm)) {
                var existing = self.relays.get(norm);
                existing.read = existing.read || read;
                existing.write = existing.write || write;
            } else {
                self.relays.set(norm, {
                    url: url,
                    read: read,
                    write: write,
                    enabled: true,
                    isLocal: norm.indexOf("127.0.0.1") !== -1 || norm.indexOf("localhost") !== -1,
                    primary: false,
                    status: "unknown",
                    latencyMs: null,
                    lastProbe: null,
                    failCount: 0
                });
                added++;
                // Probe newly discovered relay
                self.probeRelay(url);
            }
        });

        if (persist !== false && nip65Entries.length > 0) {
            try {
                localStorage.setItem(NIP65_STORAGE_KEY, JSON.stringify(nip65Entries));
            } catch (e) { /* ignore */ }
        }

        if (added > 0) {
            this._notifyStatusChange();
            this._updateHealthUI();
        }
    };

    RelayPool.prototype.ingestNip65 = function (event) {
        if (!event || (event.kind !== 10002 && event.kind !== "10002")) return;
        this.ingestNip65Tags(event.tags || [], true);
    };

    /**
     * Parallel Fault-Tolerant Double-Broadcasting
     * A failure on primary relay (wss://relay.iyou.me) does NOT abort or block others.
     */
    RelayPool.prototype.broadcast = function (signedEvent, targetRelays, timeoutMs) {
        var self = this;
        var timeoutLimit = timeoutMs || BROADCAST_TIMEOUT_MS;
        var relaysToUse = (Array.isArray(targetRelays) && targetRelays.length > 0)
            ? targetRelays
            : this.getWriteRelays();

        return new Promise(function (resolve) {
            var remaining = relaysToUse.length;
            var localSuccess = false;
            var globalSuccess = false;
            var successfulRelays = [];
            var failedRelays = [];

            if (remaining === 0) {
                return resolve({
                    localSuccess: false,
                    globalSuccess: false,
                    successfulRelays: [],
                    failedRelays: []
                });
            }

            function checkDone() {
                if (remaining <= 0) {
                    self._updateHealthUI();
                    resolve({
                        localSuccess: localSuccess,
                        globalSuccess: globalSuccess,
                        successfulRelays: successfulRelays,
                        failedRelays: failedRelays
                    });
                }
            }

            relaysToUse.forEach(function (relayUrl) {
                var norm = normalizeUrl(relayUrl);
                var isLocal = norm.indexOf("127.0.0.1") !== -1 || norm.indexOf("localhost") !== -1;
                var finished = false;

                function recordResult(ok) {
                    if (finished) return;
                    finished = true;
                    remaining--;
                    if (ok) {
                        successfulRelays.push(relayUrl);
                        if (isLocal) localSuccess = true;
                        else globalSuccess = true;
                        var r = self.relays.get(norm);
                        if (r) {
                            r.status = "online";
                            r.failCount = 0;
                        }
                    } else {
                        failedRelays.push(relayUrl);
                        // Track consecutive failures; auto-quarantine on excess.
                        self._recordBroadcastFailure(relayUrl);
                    }
                    checkDone();
                }

                try {
                    var ws = new WebSocket(relayUrl);
                    var timer = setTimeout(function () {
                        try { ws.close(); } catch (e) {}
                        recordResult(false);
                    }, timeoutLimit);

                    ws.onopen = function () {
                        try {
                            ws.send(JSON.stringify(["EVENT", signedEvent]));
                        } catch (e) {
                            clearTimeout(timer);
                            recordResult(false);
                        }
                    };

                    ws.onmessage = function (event) {
                        try {
                            var msg = JSON.parse(event.data);
                            if (msg[0] === "OK") {
                                clearTimeout(timer);
                                try { ws.close(); } catch (e) {}
                                recordResult(!!msg[2]);
                                return;
                            }
                        } catch (e) { /* ignore */ }
                    };

                    ws.onerror = function () {
                        clearTimeout(timer);
                        recordResult(false);
                    };

                    ws.onclose = function () {
                        clearTimeout(timer);
                        if (!finished) recordResult(false);
                    };
                } catch (err) {
                    recordResult(false);
                }
            });
        });
    };

    RelayPool.prototype.publish = function (signedEvent, targetRelays, timeoutMs) {
        return this.broadcast(signedEvent, targetRelays, timeoutMs);
    };

    RelayPool.prototype.onStatusChange = function (callback) {
        if (typeof callback === "function") {
            this.listeners.push(callback);
        }
    };

    RelayPool.prototype._notifyStatusChange = function () {
        var statusList = this.getRelayStatuses();
        this.listeners.forEach(function (cb) {
            try { cb(statusList); } catch (e) {}
        });
        if (typeof window !== "undefined") {
            try {
                window.dispatchEvent(new CustomEvent("relayPoolUpdated", { detail: { relays: statusList } }));
            } catch (e) {}
        }
        this._updateHealthUI();
    };

    /**
     * Update the compact mobile-only mesh/bridge health pill
     * (#mobile-bridge-dot + #mobile-bridge-label). Shared with bridge_client.js
     * so both the relay pool and the local signing bridge can drive it.
     *   online  -> emerald dot, "Online"
     *   offline -> amber dot,  "Manual"
     */
    function updateMobileBridgeHealth(online) {
        if (typeof document === "undefined") return;
        var dot = document.getElementById("mobile-bridge-dot");
        var label = document.getElementById("mobile-bridge-label");
        if (dot) {
            dot.className = online
                ? "w-2 h-2 rounded-full bg-emerald-500"
                : "w-2 h-2 rounded-full bg-amber-500";
        }
        if (label) {
            label.textContent = online ? "Online" : "Manual";
            label.className = online ? "text-emerald-500" : "text-amber-500";
        }
    }

    RelayPool.prototype._updateHealthUI = function () {
        if (typeof document === "undefined") return;
        var counts = this.getActiveRelayCount();
        var dot = document.getElementById("relay-status-dot");
        var label = document.getElementById("relay-status-label");
        var countEl = document.getElementById("relay-health-count");

        if (countEl) {
            var shown = counts.online > 0
                ? counts.online
                : (counts.quarantined > 0 ? 0 : counts.online);
            countEl.textContent = shown + "/" + counts.total;
        }

        if (dot) {
            if (counts.online > 0) {
                dot.className = "w-2 h-2 rounded-full bg-emerald-500 animate-pulse shrink-0";
            } else {
                dot.className = "w-2 h-2 rounded-full bg-rose-500 shrink-0";
            }
        }

        if (label) {
            var base = "font-semibold truncate group-hover:text-violet-600 dark:group-hover:text-violet-400 transition-colors";
            if (counts.online === 0) {
                label.textContent = counts.quarantined > 0
                    ? "Mesh Quarantining Relays... (Reconnecting)"
                    : "Mesh Offline (Reconnecting...)";
                label.className = base + " text-rose-500";
            } else if (counts.quarantined > 0) {
                label.textContent = "Mesh Degraded (" + counts.quarantined + " Quarantined)";
                label.className = base + " text-amber-500 dark:text-amber-400";
            } else if (counts.online < counts.total) {
                label.textContent = "Mesh Degraded (" + counts.online + " Active)";
                label.className = base + " text-amber-500 dark:text-amber-400";
            } else {
                label.textContent = "Mesh Pool Active";
                label.className = base + " text-slate-700 dark:text-slate-200";
            }
        }

        updateMobileBridgeHealth(counts.online > 0);

        // Live-refresh the open diagnostics drawer so latency/state stay current.
        var drawer = document.getElementById("relay-diagnostics-drawer");
        if (drawer && !drawer.classList.contains("hidden")) {
            this.renderDiagnosticsList();
        }
    };

    /**
     * Escape a string for safe insertion into rendered HTML.
     */
    function escapeHtml(value) {
        return String(value == null ? "" : value)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;");
    }

    /**
     * Strip scheme/path from a relay URL for compact display:
     *   wss://relay.damus.io    -> relay.damus.io
     *   ws://127.0.0.1:9003     -> 127.0.0.1:9003
     */
    RelayPool.prototype._cleanRelayHostname = function (url) {
        try {
            var parsed = new URL(url);
            return parsed.host;
        } catch (e) {
            var stripped = String(url || "")
                .replace(/^wss?:\/\//i, "")
                .replace(/\/+$/, "");
            return stripped || url || "unknown";
        }
    };

    /**
     * Toggle the diagnostics drawer, rotate the chevron, and refresh relay rows.
     */
    RelayPool.prototype.toggleDiagnosticsPopover = function () {
        if (typeof document === "undefined") return;
        var drawer = document.getElementById("relay-diagnostics-drawer");
        if (!drawer) return;

        var toggle = document.getElementById("relay-health-toggle");
        var chevron = document.getElementById("relay-chevron");
        var willOpen = drawer.classList.contains("hidden");

        drawer.classList.toggle("hidden");
        if (chevron) {
            chevron.classList.toggle("rotate-180", willOpen);
        }
        if (toggle) {
            toggle.setAttribute("aria-expanded", willOpen ? "true" : "false");
        }
        if (willOpen) {
            this.renderDiagnosticsList();
        }
    };

    /**
     * Render one row per pooled relay:
     *        ●  nos.lol           [R][W]   42ms
     *        ●  127.0.0.1:9003    [Local]  8ms
     *   Status dot: emerald = online, amber = probing, rose = offline.
     */
    RelayPool.prototype.renderDiagnosticsList = function () {
        if (typeof document === "undefined") return;
        var listEl = document.getElementById("relay-diagnostics-list");
        if (!listEl) return;

        var self = this;
        var rows = [];
        var isHttps = isSecureOrigin();

        this.relays.forEach(function (r) {
            var statusDotClass = "bg-rose-500";
            var latencyClass = "text-slate-400";
            var latencyText = "offline";

            if (r.status === "online") {
                statusDotClass = "bg-emerald-500";
                latencyClass = "text-emerald-500 dark:text-emerald-400";
                latencyText = (r.latencyMs != null ? r.latencyMs : "?") + "ms";
            } else if (r.status === "quarantined") {
                statusDotClass = "bg-rose-500";
                latencyClass = "text-rose-500 dark:text-rose-400";
                latencyText = "quarantined";
            } else if (!r.status || r.status === "unknown") {
                statusDotClass = "bg-amber-500";
                latencyClass = "text-amber-500 dark:text-amber-400";
                latencyText = "probing";
            }

            var isLocal = !!r.isLocal;
            var hostname = escapeHtml(self._cleanRelayHostname(r.url));

            // On an HTTPS origin, plain ws:// loopback sockets cannot be probed
            // (browser Mixed Content rules) — retain the entry as a static
            // "Local Enclave (Desktop/WSS)" status instead of a dead offline row.
            if (isLocal && isHttps && isPlainWsUrl(r.url)) {
                statusDotClass = "bg-amber-500";
                latencyClass = "text-slate-500 dark:text-slate-400";
                latencyText = "Local Enclave (Desktop/WSS)";
                hostname = "127.0.0.1:9003";
            } else if (!isLocal && r.enabled === false) {
                statusDotClass = "bg-slate-300 dark:bg-slate-600";
                latencyClass = "text-slate-400 dark:text-slate-500";
                latencyText = "disabled";
            }

            var leftCol =
                '<div class="flex items-center gap-1.5 min-w-0">' +
                  '<span class="w-1.5 h-1.5 rounded-full ' + statusDotClass + ' shrink-0"></span>' +
                  '<span class="truncate text-slate-700 dark:text-slate-300 font-mono">' + hostname + '</span>' +
                  (isLocal ? '<span class="px-1 py-0.2 rounded bg-slate-100 dark:bg-slate-800 border border-slate-200 dark:border-slate-700/60 text-[9px] text-violet-600 dark:text-violet-400 font-mono shrink-0">[Local]</span>' : '') +
                '</div>';

            var readChip = r.read !== false ?
                '<span class="px-1 py-0.5 rounded bg-emerald-50 dark:bg-emerald-950/60 text-emerald-600 dark:text-emerald-400 border border-emerald-200 dark:border-emerald-800/80">R</span>' : '';
            var writeChip = r.write !== false ?
                '<span class="px-1 py-0.5 rounded bg-violet-50 dark:bg-violet-950/60 text-violet-600 dark:text-violet-400 border border-violet-200 dark:border-violet-800/80">W</span>' : '';

            var wideStatus = (isLocal && isHttps && isPlainWsUrl(r.url));
            var rightCol =
                '<div class="flex items-center gap-1 shrink-0 font-mono text-[10px]">' +
                  readChip +
                  writeChip +
                  '<span class="' + (wideStatus ? 'text-right tabular-nums whitespace-nowrap' : 'w-14 text-right tabular-nums') + ' ' + latencyClass + '">' + latencyText + '</span>' +
                '</div>';

            rows.push(
                '<div class="flex items-center justify-between gap-2 py-0.5">' +
                  leftCol +
                  rightCol +
                '</div>'
            );
        });

        if (rows.length === 0) {
            listEl.innerHTML = '<div class="text-slate-400 text-center py-2">No relays configured.</div>';
        } else {
            listEl.innerHTML = rows.join("");
        }
    };

    // Instantiate Singleton
    var poolInstance = new RelayPool();

    // Export to global window / module
    global.relayPool = poolInstance;
    global.RelayPool = poolInstance;

    global.updateMobileBridgeHealth = updateMobileBridgeHealth;

    global.retryQuarantinedRelays = function () {
        if (poolInstance && typeof poolInstance.retryQuarantinedRelays === "function") {
            return poolInstance.retryQuarantinedRelays();
        }
        return Promise.resolve(0);
    };

    global.toggleRelayState = function (relayUrl, isEnabled) {
        if (poolInstance && typeof poolInstance.toggleRelayState === "function") {
            return poolInstance.toggleRelayState(relayUrl, isEnabled);
        }
        return false;
    };

    if (typeof module !== "undefined" && module.exports) {
        module.exports = poolInstance;
    }

})(typeof window !== "undefined" ? window : globalThis);
