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

    var BOOTSTRAP_RELAYS = [
        { url: "wss://relay.iyou.me", read: true, write: true, primary: true },
        { url: "wss://nos.lol", read: true, write: true, primary: false },
        { url: "wss://relay.damus.io", read: true, write: true, primary: false },
        { url: "wss://relay.primal.net", read: true, write: true, primary: false },
        { url: "ws://127.0.0.1:9003", read: true, write: true, isLocal: true, primary: false }
    ];

    var STORAGE_KEY = "wun_relays";
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

    function RelayPool() {
        this.relays = new Map(); // url -> { url, read, write, isLocal, primary, status, latencyMs, lastProbe }
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
                isLocal: !!r.isLocal || norm.indexOf("127.0.0.1") !== -1 || norm.indexOf("localhost") !== -1,
                primary: !!r.primary,
                status: "unknown",
                latencyMs: null,
                lastProbe: null
            });
        });

        // 2. Load stored custom relays from localStorage
        try {
            var stored = localStorage.getItem(STORAGE_KEY);
            if (stored) {
                var list = JSON.parse(stored);
                if (Array.isArray(list)) {
                    list.forEach(function (entry) {
                        var url = typeof entry === "string" ? entry : (entry && entry.url);
                        if (!url) return;
                        var norm = normalizeUrl(url);
                        if (!self.relays.has(norm)) {
                            self.relays.set(norm, {
                                url: url,
                                read: entry.read !== false,
                                write: entry.write !== false,
                                isLocal: norm.indexOf("127.0.0.1") !== -1 || norm.indexOf("localhost") !== -1,
                                primary: false,
                                status: "unknown",
                                latencyMs: null,
                                lastProbe: null
                            });
                        }
                    });
                }
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

        // 4. Initial probe and periodic probe
        if (typeof window !== "undefined") {
            setTimeout(function () { self.probeRelays(); }, 500);
            this.probeTimer = setInterval(function () { self.probeRelays(); }, PROBE_INTERVAL_MS);
        }
    };

    RelayPool.prototype.getRelays = function () {
        var urls = [];
        this.relays.forEach(function (r) {
            urls.push(r.url);
        });
        return urls;
    };

    RelayPool.prototype.getWriteRelays = function () {
        var urls = [];
        this.relays.forEach(function (r) {
            if (r.write) urls.push(r.url);
        });
        return urls.length > 0 ? urls : this.getRelays();
    };

    RelayPool.prototype.getReadRelays = function () {
        var urls = [];
        this.relays.forEach(function (r) {
            if (r.read) urls.push(r.url);
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
        var total = this.relays.size;
        var online = 0;
        this.relays.forEach(function (r) {
            if (r.status === "online") online++;
        });
        return { online: online, total: total };
    };

    RelayPool.prototype.probeRelay = function (url) {
        var norm = normalizeUrl(url);
        var record = this.relays.get(norm);
        if (!record) return Promise.resolve({ url: url, status: "offline", latencyMs: null });

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
                    isLocal: norm.indexOf("127.0.0.1") !== -1 || norm.indexOf("localhost") !== -1,
                    primary: false,
                    status: "unknown",
                    latencyMs: null,
                    lastProbe: null
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
                        if (r) r.status = "online";
                    } else {
                        failedRelays.push(relayUrl);
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

    RelayPool.prototype._updateHealthUI = function () {
        if (typeof document === "undefined") return;
        var counts = this.getActiveRelayCount();
        var dot = document.getElementById("relay-status-dot");
        var label = document.getElementById("relay-status-label");
        var countEl = document.getElementById("relay-health-count");

        if (countEl) {
            countEl.textContent = counts.online + "/" + counts.total;
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
                label.textContent = "Mesh Offline (Reconnecting...)";
                label.className = base + " text-rose-500";
            } else if (counts.online < counts.total) {
                label.textContent = "Mesh Degraded (" + counts.online + " Active)";
                label.className = base + " text-amber-500 dark:text-amber-400";
            } else {
                label.textContent = "Mesh Pool Active";
                label.className = base + " text-slate-700 dark:text-slate-200";
            }
        }

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

        this.relays.forEach(function (r) {
            var statusDotClass = "bg-rose-500";
            var latencyClass = "text-slate-400";
            var latencyText = "offline";

            if (r.status === "online") {
                statusDotClass = "bg-emerald-500";
                latencyClass = "text-emerald-500 dark:text-emerald-400";
                latencyText = (r.latencyMs != null ? r.latencyMs : "?") + "ms";
            } else if (!r.status || r.status === "unknown") {
                statusDotClass = "bg-amber-500";
                latencyClass = "text-amber-500 dark:text-amber-400";
                latencyText = "probing";
            }

            var isLocal = !!r.isLocal;
            var hostname = escapeHtml(self._cleanRelayHostname(r.url));

            var leftCol =
                '<div class="flex items-center gap-1.5 min-w-0">' +
                  '<span class="w-1.5 h-1.5 rounded-full ' + statusDotClass + ' shrink-0"></span>' +
                  '<span class="truncate text-slate-700 dark:text-slate-300 font-mono">' + hostname + '</span>' +
                  (isLocal ? '<span class="px-1 py-0.2 rounded bg-slate-100 dark:bg-slate-800 border border-slate-200 dark:border-slate-700/60 text-[9px] text-slate-500 font-mono shrink-0">Local</span>' : '') +
                '</div>';

            var rightCol =
                '<div class="flex items-center gap-1 shrink-0 font-mono text-[10px]">' +
                  '<span class="px-1 py-0.5 rounded bg-emerald-50 dark:bg-emerald-950/60 text-emerald-600 dark:text-emerald-400 border border-emerald-200 dark:border-emerald-800/80">R</span>' +
                  '<span class="px-1 py-0.5 rounded bg-violet-50 dark:bg-violet-950/60 text-violet-600 dark:text-violet-400 border border-violet-200 dark:border-violet-800/80">W</span>' +
                  '<span class="w-14 text-right tabular-nums ' + latencyClass + '">' + latencyText + '</span>' +
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

    if (typeof module !== "undefined" && module.exports) {
        module.exports = poolInstance;
    }

})(typeof window !== "undefined" ? window : globalThis);
