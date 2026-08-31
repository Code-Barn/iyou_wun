/**
 * bridge_client.js — Tauri Signing Bridge Client
 * Singleton WebSocket connection to ws://127.0.0.1:9001 with mutex state machine,
 * 5-second timeout fallback modal, and relay broadcast utilities.
 *
 * Exposes: window.bridgeClient
 */
(function () {
    "use strict";

    var RELAY_BROADCAST_TIMEOUT = 3000;
    var CONNECTION_TIMEOUT = 5000;
    var SOCKET_POLL_INTERVAL = 100;
    var SOCKET_POLL_TIMEOUT = 6000;
    var ALIAS_DEBOUNCE_MS = 200;
    var ALIAS_CONNECT_POLL_MAX_ATTEMPTS = 60;

    var DEFAULT_RELAYS = [
        "wss://relay.iyou.me",
        "wss://nos.lol",
        "wss://relay.damus.io",
        "wss://relay.primal.net",
        "ws://127.0.0.1:9003"
    ];

    // ---------- Utilities ----------

    function escapeHtml(str) {
        if (str === null || str === undefined) return '';
        var s = String(str);
        return s
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
    }

    function escapeAttr(str) {
        if (str === null || str === undefined) return '';
        var s = String(str);
        return s
            .replace(/&/g, '&amp;')
            .replace(/'/g, '&#39;')
            .replace(/"/g, '&quot;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;');
    }

    function getCookie(name) {
        var match = document.cookie.match(new RegExp("(^| )" + name + "=([^;]+)"));
        return match ? decodeURIComponent(match[2]) : "";
    }

    function getRelays() {
        if (typeof window !== "undefined" && window.relayPool && typeof window.relayPool.getRelays === "function") {
            return window.relayPool.getRelays();
        }
        var stored = localStorage.getItem("wun_relays");
        if (stored) {
            try { return JSON.parse(stored); } catch (e) { /* ignore */ }
        }
        return DEFAULT_RELAYS;
    }

    function setRelays(list) {
        localStorage.setItem("wun_relays", JSON.stringify(list));
    }

    function uuidv4() {
        return "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx".replace(/x/g, function () {
            return Math.floor(Math.random() * 16).toString(16);
        });
    }

    // ---------- Toast ----------

    function showToast(message, type, duration) {
        if (typeof window !== "undefined" && typeof window.showToast === "function" && window.showToast !== showToast) {
            return window.showToast(message, type, duration);
        }
        var toast = document.getElementById("toast");
        if (!toast) return;
        var span = toast.querySelector("span");
        if (span) span.textContent = message;
        var isError = type === true || type === "error";
        toast.className = toast.className.replace(/bg-\S+/g, "") +
            " fixed top-4 right-4 px-6 py-3 rounded-lg shadow-lg toast " +
            (isError ? "bg-red-500 text-white" : "bg-green-500 text-white");
        toast.classList.remove("hide");
        setTimeout(function () { toast.classList.add("hide"); }, 3000);
    }

    function showSovereignToast(message) {
        var toast = document.getElementById("sovereignToast");
        if (!toast) return;
        var span = toast.querySelector("span");
        if (span) span.textContent = message;
        toast.className = "fixed top-4 right-4 bg-emerald-600 text-white px-6 py-3 rounded-lg shadow-lg toast";
        toast.classList.remove("hide");
        setTimeout(function () { toast.classList.add("hide"); }, 3000);
    }

    // ---------- TauriBridgeClient ----------

    function TauriBridgeClient() {
        this.socket = null;
        this.connectionLock = "IDLE"; // IDLE | CONNECTING | OPEN
        this.pendingEvent = null;
        this.isProcessing = false;
        this.pendingSignedPayload = null;
        this._onMessage = null;
        // Project Zero Trust Lens alias store (purely in-memory, never persisted)
        this._aliasCache = new Map();          // normalized key -> { nickname, trust_level, badge } | null
        this._aliasQueue = new Set();          // normalized keys awaiting dispatch
        this._aliasWaiters = [];               // pending Promise resolve callbacks
        this._aliasPendingBatches = [];        // FIFO of { keys, waiters } sent over the wire
        this._aliasTimer = null;
    }

    TauriBridgeClient.prototype._normalizeAliasKey = function (raw) {
        var key = String(raw == null ? "" : raw).trim();
        if (!key) return "";
        if (/^[0-9a-fA-F]{64}$/.test(key)) return key.toLowerCase();
        return key; // preserve DID casing (did:key:..., did:iyou:...)
    };

    /**
     * Resolve peer aliases via the iyou_home Contact Enclave bridge.
     * Returns a Promise resolving to a matches dictionary keyed by the
     * normalized queried pubkey: { "<key>": { nickname, trust_level, badge } }.
     * Keys absent from the result were unknown to the enclave (negative-cached).
     */
    TauriBridgeClient.prototype.resolvePeerAliases = function (pubkeys) {
        var self = this;
        var tokens = Array.isArray(pubkeys) ? pubkeys : [pubkeys];
        var hits = {};
        var misses = [];

        tokens.forEach(function (raw) {
            var key = self._normalizeAliasKey(raw);
            if (!key) return;
            if (self._aliasCache.has(key)) {
                var cached = self._aliasCache.get(key);
                if (cached) hits[key] = cached;
            } else {
                self._aliasQueue.add(key);
                misses.push(key);
            }
        });

        if (misses.length === 0) {
            return Promise.resolve(hits);
        }

        return new Promise(function (resolve) {
            self._aliasWaiters.push(resolve);
            if (self._aliasTimer === null) {
                self._aliasTimer = setTimeout(function () {
                    self._flushAliasQueue();
                }, ALIAS_DEBOUNCE_MS);
            }
        });
    };

    TauriBridgeClient.prototype.isProcessingAliasFlush = function () {
        return this._aliasPendingBatches.length > 0;
    };

    TauriBridgeClient.prototype._flushAliasQueue = function () {
        this._aliasTimer = null;
        var self = this;
        var keys = Array.from(this._aliasQueue);
        this._aliasQueue.clear();

        var waiters = this._aliasWaiters.splice(0, this._aliasWaiters.length);
        if (keys.length === 0) {
            waiters.forEach(function (w) { w({}); });
            return;
        }

        this._aliasPendingBatches.push({ keys: keys, waiters: waiters });

        var dispatch = function () {
            try {
                self.socket.send(JSON.stringify({ type: "RESOLVE_PEER_ALIASES", pubkeys: keys }));
            } catch (err) {
                console.error("Failed to send RESOLVE_PEER_ALIASES:", err);
                self._failAliasBatch(self._dequeueAliasBatch(keys));
            }
        };

        if (this.socket && this.socket.readyState === WebSocket.OPEN) {
            dispatch();
            return;
        }

        this.connect();
        var attempts = 0;
        var pollSocket = setInterval(function () {
            attempts++;
            if (self.socket && self.socket.readyState === WebSocket.OPEN) {
                clearInterval(pollSocket);
                dispatch();
            } else if (attempts >= ALIAS_CONNECT_POLL_MAX_ATTEMPTS) {
                clearInterval(pollSocket);
                self._failAliasBatch(self._dequeueAliasBatch(keys));
            }
        }, SOCKET_POLL_INTERVAL);
    };

    TauriBridgeClient.prototype._dequeueAliasBatch = function (keys) {
        for (var i = 0; i < this._aliasPendingBatches.length; i++) {
            if (this._aliasPendingBatches[i].keys === keys ||
                this._aliasPendingBatches[i].keys.length === keys.length &&
                this._aliasPendingBatches[i].keys.every(function (k, idx) { return k === keys[idx]; })) {
                return this._aliasPendingBatches.splice(i, 1)[0];
            }
        }
        return null;
    };

    TauriBridgeClient.prototype._failAliasBatch = function (batch) {
        if (!batch || !batch.waiters) return;
        batch.waiters.forEach(function (w) {
            try { w({}); } catch (e) { /* ignore */ }
        });
    };

    TauriBridgeClient.prototype._onPeerAliasesResolved = function (message) {
        var self = this;
        var matches = message.matches || {};
        var unknown = message.unknown || [];
        var waiters = [];

        Object.keys(matches).forEach(function (key) {
            var normalized = self._normalizeAliasKey(key);
            self._aliasCache.set(normalized, matches[key]);
        });
        unknown.forEach(function (key) {
            self._aliasCache.set(self._normalizeAliasKey(key), null);
        });

        var batch = this._aliasPendingBatches.shift();
        if (batch && batch.waiters) {
            waiters = batch.waiters;
        } else {
            waiters = this._aliasWaiters.splice(0, this._aliasWaiters.length);
        }
        waiters.forEach(function (w) {
            try { w(matches); } catch (e) { /* ignore */ }
        });
    };

    TauriBridgeClient.prototype.clearAliasCache = function () {
        this._aliasCache.clear();
        this._aliasQueue.clear();
    };

    TauriBridgeClient.prototype.getBridgeUrl = function () {
        var scriptTag = document.querySelector('script[src*="bridge_client.js"]');
        var url = (scriptTag && scriptTag.getAttribute("data-bridge-url")) || "";
        if (url) return url;
        if (typeof window !== "undefined" && window.TAURI_SIGNING_BRIDGE) return window.TAURI_SIGNING_BRIDGE;
        return "wss://home.iyou.me:9001/";
    };

    TauriBridgeClient.prototype.connect = function (onMessage) {
        this._onMessage = onMessage || null;
        if (this.connectionLock === "CONNECTING" || this.connectionLock === "OPEN") return;
        if (this.socket && this.socket.readyState <= 1) return;

        var self = this;
        var bridgeUrl = this.getBridgeUrl();
        if (!bridgeUrl) return;

        this.connectionLock = "CONNECTING";
        try {
            var socket = new WebSocket(bridgeUrl);
            var connected = false;
            var connectTimeout = setTimeout(function () {
                if (!connected) {
                    self.connectionLock = "IDLE";
                    try { socket.close(); } catch (x) { /* ignore */ }
                    if (self.isProcessing) self.showFallbackModal();
                }
            }, CONNECTION_TIMEOUT);

            socket.onopen = function () {
                connected = true;
                clearTimeout(connectTimeout);
                self.connectionLock = "OPEN";
                self.socket = socket;
                window.activeFeedSocket = socket;
                var bridgeStatusEl = document.getElementById("persona-bridge-status");
                if (bridgeStatusEl) {
                    bridgeStatusEl.textContent = "Bridge Connected";
                    bridgeStatusEl.className = "text-emerald-500 font-normal";
                }
                if (self.pendingSignedPayload) return;
                socket.send(JSON.stringify({ type: "get_profile" }));
                socket.send(JSON.stringify({ type: "list_profiles" }));
                socket.send(JSON.stringify({ type: "LIST_PERSONAS" }));
            };
            socket.onmessage = function (event) {
                self._handleMessage(event.data);
            };
            socket.onerror = function () {
                clearTimeout(connectTimeout);
                if (!connected) {
                    self.connectionLock = "IDLE";
                    if (self.isProcessing) self.showFallbackModal();
                }
            };
            socket.onclose = function () {
                clearTimeout(connectTimeout);
                self.socket = null;
                window.activeFeedSocket = null;
                self.connectionLock = "IDLE";
                var bridgeStatusEl = document.getElementById("persona-bridge-status");
                if (bridgeStatusEl) {
                    bridgeStatusEl.textContent = "Bridge Offline";
                    bridgeStatusEl.className = "text-slate-400 font-normal";
                }
            };
        } catch (err) {
            this.connectionLock = "IDLE";
            if (this.isProcessing) this.showFallbackModal();
        }
    };

    TauriBridgeClient.prototype.updateActivePersonaUI = function (profile) {
        if (!profile) return;
        var labelEl = document.getElementById("active-persona-label");
        var levelEl = document.getElementById("active-persona-level");
        var dotEl = document.getElementById("active-persona-dot");

        var nameStr = profile.name || profile.profile_name || profile.label || "";
        if (!nameStr) {
            if (profile.did) {
                nameStr = profile.did.slice(0, 16) + "...";
            } else if (profile.nostr_pubkey_hex) {
                nameStr = profile.nostr_pubkey_hex.slice(0, 12) + "...";
            } else {
                nameStr = "Sovereign";
            }
        }

        if (labelEl) {
            labelEl.textContent = nameStr;
            labelEl.title = profile.did || profile.nostr_pubkey_hex || nameStr;
        }

        var level = profile.level !== undefined ? profile.level : profile.derivation_index;
        var levelStr = (level === 1) ? "L1" : (level ? "L" + level : "L2");
        if (levelEl) {
            levelEl.textContent = levelStr;
            levelEl.className = "text-[10px] px-1 py-0.5 rounded font-bold " +
                (levelStr === "L1" 
                    ? "bg-violet-100 dark:bg-violet-950/80 text-violet-700 dark:text-violet-300"
                    : "bg-amber-100 dark:bg-amber-950/80 text-amber-700 dark:text-amber-300");
        }

        if (dotEl) {
            dotEl.className = "w-2 h-2 rounded-full bg-emerald-500 animate-pulse inline-block";
            dotEl.title = "Active: " + nameStr + " (" + levelStr + ")";
        }
    };

    TauriBridgeClient.prototype.renderPersonaDropdownList = function (profiles) {
        var container = document.getElementById("persona-list-container");
        if (!container) return;

        if (!profiles || profiles.length === 0) {
            container.innerHTML = '<div class="px-2 py-2 text-slate-400 text-center text-[11px]">No active personas found in vault.</div>';
            return;
        }

        var activePk = window.activeProfile ? (window.activeProfile.nostr_pubkey_hex || window.activeProfile.pubkey_hex || window.activeProfile.pubkey) : null;
        var activeId = window.activeProfile ? (window.activeProfile.id || window.activeProfile.profile_id) : null;

        var html = "";
        profiles.forEach(function (p) {
            var pId = p.id || p.profile_id || p.nostr_pubkey_hex || "";
            var pPk = p.nostr_pubkey_hex || p.pubkey_hex || p.pubkey || "";
            var isActive = (activeId && pId && String(activeId) === String(pId)) || (activePk && pPk && String(activePk).toLowerCase() === String(pPk).toLowerCase());

            var name = p.name || p.profile_name || p.label || (p.did ? p.did.slice(0, 16) + '...' : (pPk ? pPk.slice(0, 10) + '...' : 'Persona'));
            var level = p.level !== undefined ? p.level : p.derivation_index;
            var levelStr = (level === 1) ? "L1" : (level ? "L" + level : "L2");

            var badgeClass = (levelStr === "L1")
                ? "bg-violet-100 dark:bg-violet-950/80 text-violet-700 dark:text-violet-300"
                : "bg-amber-100 dark:bg-amber-950/80 text-amber-700 dark:text-amber-300";

            var activeDot = isActive
                ? '<span class="w-1.5 h-1.5 rounded-full bg-emerald-500 shrink-0"></span>'
                : '<span class="w-1.5 h-1.5 rounded-full bg-transparent shrink-0"></span>';

            var activeBg = isActive
                ? 'bg-violet-50/80 dark:bg-violet-950/40 text-violet-900 dark:text-violet-200 font-semibold border-violet-300 dark:border-violet-700/60'
                : 'hover:bg-slate-50 dark:hover:bg-slate-800/60 text-slate-700 dark:text-slate-300 border-transparent';

            html += '<button type="button" ' +
                'onclick="switchPersona(\'' + escapeAttr(pId) + '\')" ' +
                'class="w-full text-left px-2.5 py-1.5 rounded-lg flex items-center justify-between gap-2 border transition text-xs ' + activeBg + '">' +
                '<div class="flex items-center gap-2 min-w-0">' +
                activeDot +
                '<span class="truncate">' + escapeHtml(name) + '</span>' +
                '</div>' +
                '<span class="text-[10px] px-1 py-0.5 rounded font-bold shrink-0 ' + badgeClass + '">' +
                escapeHtml(levelStr) +
                '</span>' +
                '</button>';
        });

        container.innerHTML = html;
    };

    TauriBridgeClient.prototype._handleMessage = function (data) {
        try {
            var message = JSON.parse(data);

            if (message.type === "profiles_list" || message.type === "LIST_PERSONAS_RESPONSE" || message.type === "personas_list") {
                var rawProfiles = message.profiles || message.personas || message.payload || [];
                // Filter out Level 0 Anchor identity (level === 0, derivation_index === 0, is_anchor, or ANCHOR role)
                var validProfiles = rawProfiles.filter(function (p) {
                    if (!p) return false;
                    if (p.level === 0 || p.derivation_index === 0) return false;
                    if (p.is_anchor === true || p.role === "ANCHOR" || p.name === "ANCHOR") return false;
                    return true;
                });
                window.enclavePersonas = validProfiles;
                this.renderPersonaDropdownList(validProfiles);
                return;
            }

            if (message.type === "profile_sync" || message.type === "profile_activated" || message.type === "active_profile_changed" || message.type === "SET_ACTIVE_PERSONA_RESPONSE") {
                var prof = message.profile || message.active_profile || message.persona;
                if (prof) {
                    var previousPubkey = window.activeProfile ? (window.activeProfile.nostr_pubkey_hex || window.activeProfile.pubkey_hex) : null;
                    window.activeProfile = prof;
                    this.updateActivePersonaUI(prof);
                    if (window.enclavePersonas && window.enclavePersonas.length > 0) {
                        this.renderPersonaDropdownList(window.enclavePersonas);
                    }
                    window.dispatchEvent(new CustomEvent('persona:changed', { detail: prof }));

                    var newPubkey = prof.nostr_pubkey_hex || prof.pubkey_hex;
                    if (previousPubkey && newPubkey && previousPubkey !== newPubkey) {
                        // Identity switch: local trust view is stale, invalidate and re-scan.
                        this.clearAliasCache();
                        if (window.trustLens && typeof window.trustLens.reset === "function") {
                            window.trustLens.reset();
                        }
                        if (window.trustLens && typeof window.trustLens.scan === "function") {
                            window.trustLens.scan();
                        }
                    }
                }
                return;
            }

            if (message.type === "peer_aliases_resolved") {
                this._onPeerAliasesResolved(message);
                return;
            }

            if (message.type === "signed_event") {
                var signedEvent = message.event;
                if (this.pendingEvent && signedEvent) {
                    this.pendingEvent.id = signedEvent.id;
                    this.pendingEvent.sig = signedEvent.sig;
                }
                if (this._onMessage) {
                    this._onMessage(this.pendingEvent || signedEvent, signedEvent);
                }
            }

        } catch (err) {
            console.error("Error handling Tauri message:", err);
            showToast("Error processing bridge response.", true);
            this._resetProcessing();
        }
    };

    TauriBridgeClient.prototype.signEvent = function (event) {
        this.pendingEvent = event;
        if (!this.socket || this.socket.readyState !== WebSocket.OPEN) {
            this.connect();
        }

        var self = this;
        var request = { type: "sign_event", event: event };
        var checkSocket = setInterval(function () {
            if (self.socket && self.socket.readyState === WebSocket.OPEN) {
                clearInterval(checkSocket);
                try {
                    self.socket.send(JSON.stringify(request));
                } catch (err) {
                    clearInterval(checkSocket);
                    self.showFallbackModal();
                }
            }
        }, SOCKET_POLL_INTERVAL);
        setTimeout(function () {
            if (self.isProcessing) {
                clearInterval(checkSocket);
                self.showFallbackModal();
            }
        }, SOCKET_POLL_TIMEOUT);
    };

    TauriBridgeClient.prototype.getEffectivePubkey = async function () {
        var bridgePk = window.activeProfile ? (window.activeProfile.nostr_pubkey_hex || window.activeProfile.pubkey_hex || window.activeProfile.pubkey) : null;
        var templatePk = (typeof window.userPubkey !== "undefined" && window.userPubkey) ? window.userPubkey : null;
        var pk = (bridgePk && bridgePk.length === 64) ? bridgePk : templatePk;
        if (!pk || pk.length !== 64 || !/^[a-fA-F0-9]{64}$/.test(pk)) {
            throw new Error("Identity Synchronization Required: No valid secp256k1 pubkey found");
        }
        return pk.toLowerCase();
    };

    TauriBridgeClient.prototype.broadcastToRelays = function (signedEvent, relayList, onDone) {
        if (typeof window !== "undefined" && window.relayPool && typeof window.relayPool.broadcast === "function") {
            window.relayPool.broadcast(signedEvent, relayList).then(function (res) {
                if (res.localSuccess) showSovereignToast("Sovereign Copy Saved.");
                if (onDone) {
                    onDone(res.localSuccess, res.globalSuccess);
                }
            }).catch(function () {
                if (onDone) onDone(false, false);
            });
            return;
        }

        var relays = relayList || getRelays();
        var remaining = relays.length;
        var localRelaySuccess = false;
        var anyGlobalSuccess = false;

        function checkDone() {
            if (remaining > 0) return;
            if (localRelaySuccess) showSovereignToast("Sovereign Copy Saved.");
            if (onDone) {
                onDone(localRelaySuccess, anyGlobalSuccess);
            }
        }

        relays.forEach(function (relayUrl) {
            var isLocal = relayUrl.indexOf("127.0.0.1:9003") !== -1 || relayUrl.indexOf("localhost:9003") !== -1;
            var finished = false;
            var done = function () {
                if (finished) return;
                finished = true;
                remaining--;
                checkDone();
            };

            try {
                var ws = new WebSocket(relayUrl);
                ws.onopen = function () { ws.send(JSON.stringify(["EVENT", signedEvent])); };
                ws.onmessage = function (event) {
                    try {
                        var msg = JSON.parse(event.data);
                        if (msg[0] === "OK") {
                            if (isLocal) localRelaySuccess = true;
                            else anyGlobalSuccess = true;
                        }
                    } catch (e) { /* ignore */ }
                    try { ws.close(); } catch (e) { /* ignore */ }
                    done();
                };
                ws.onerror = function () { done(); };
                ws.onclose = function () { done(); };
                setTimeout(function () { try { ws.close(); } catch (e) { /* ignore */ } done(); }, RELAY_BROADCAST_TIMEOUT);
            } catch (err) {
                done();
            }
        });
    };

    TauriBridgeClient.prototype.showFallbackModal = function () {
        var event = this.pendingEvent;
        if (!event) return;
        var modal = document.getElementById("fallbackModal");
        var unsignedField = document.getElementById("fallbackUnsigned");
        var signedField = document.getElementById("fallbackSigned");
        if (!modal || !unsignedField) return;
        unsignedField.value = JSON.stringify(event, null, 2);
        if (signedField) signedField.value = "";
        this.pendingSignedPayload = event;
        modal.classList.remove("hidden");
    };

    TauriBridgeClient.prototype.closeFallbackModal = function () {
        var modal = document.getElementById("fallbackModal");
        if (modal) modal.classList.add("hidden");
        this.pendingSignedPayload = null;
    };

    TauriBridgeClient.prototype.submitSignedEvent = function () {
        var signedField = document.getElementById("fallbackSigned");
        if (!signedField) return;
        var raw = signedField.value.trim();
        if (!raw) {
            showToast("Paste a signed event JSON first.", true);
            return;
        }
        var signedEvent;
        try {
            signedEvent = JSON.parse(raw);
        } catch (e) {
            showToast("Invalid JSON. Please check the signed event.", true);
            return;
        }
        if (!signedEvent.id || !signedEvent.sig) {
            showToast("Signed event must contain 'id' and 'sig' fields.", true);
            return;
        }
        this.closeFallbackModal();
        this.pendingEvent = signedEvent;
        if (this._onMessage) {
            this._onMessage(signedEvent, signedEvent);
        }
    };

    TauriBridgeClient.prototype._resetProcessing = function () {
        this.isProcessing = false;
        this.pendingEvent = null;
        var btnText = document.getElementById("profileBtnText");
        var btnLoading = document.getElementById("profileBtnLoading");
        var saveBtn = document.getElementById("profileSaveBtn");
        if (btnText) btnText.classList.remove("hidden");
        if (btnLoading) btnLoading.classList.add("hidden");
        if (saveBtn) saveBtn.disabled = false;
    };

    TauriBridgeClient.prototype.resetPostState = function () {
        this.isProcessing = false;
        this.pendingEvent = null;
        this.pendingVote = null;
        this.pendingPoll = false;
        if (typeof window.pendingReply !== "undefined") window.pendingReply = null;

        var btn = document.getElementById("postButton");
        var textSpan = document.getElementById("postButtonText");
        var loadingSpan = document.getElementById("postButtonLoading");
        if (btn) btn.disabled = false;
        if (textSpan) textSpan.classList.remove("hidden");
        if (loadingSpan) loadingSpan.classList.add("hidden");

        var pubBtn = document.getElementById("publishPollBtn");
        if (pubBtn) { pubBtn.disabled = false; pubBtn.textContent = "Publish Poll"; }
    };

    // ---------- Tab Switching ----------

    function switchTab(tabName) {
        var validTabs = ["profile", "deck", "settings", "account"];
        if (validTabs.indexOf(tabName) === -1) tabName = "profile";

        document.querySelectorAll(".tab-panel").forEach(function (panel) {
            panel.classList.toggle("hidden", panel.id !== ("tab-" + tabName));
        });

        document.querySelectorAll(".tab-btn").forEach(function (btn) {
            var isActive = btn.dataset.tab === tabName;
            btn.classList.toggle("border-violet-600", isActive);
            btn.classList.toggle("text-violet-600", isActive);
            btn.classList.toggle("dark:text-violet-400", isActive);
            btn.classList.toggle("font-bold", isActive);
            btn.classList.toggle("border-transparent", !isActive);
            btn.classList.toggle("text-slate-500", !isActive);
        });

        if (window.history && window.history.replaceState) {
            window.history.replaceState(null, null, "#" + tabName);
        } else {
            window.location.hash = "#" + tabName;
        }
        try {
            localStorage.setItem("wun_dashboard_active_tab", tabName);
        } catch (e) { /* ignore */ }
    }

    // ---------- Persona Switcher API ----------

    window.switchPersona = function (profileId) {
        var socket = window.activeFeedSocket || (window.bridgeClient && window.bridgeClient.socket);
        if (!socket || socket.readyState !== WebSocket.OPEN) {
            console.warn('Bridge socket not connected');
            showToast("Bridge socket not connected.", true);
            return;
        }
        socket.send(JSON.stringify({
            type: "set_active_profile",
            profile_id: profileId
        }));
        socket.send(JSON.stringify({
            type: "SET_ACTIVE_PERSONA",
            profile_id: profileId,
            persona_id: profileId
        }));
        var dropdown = document.getElementById('persona-switcher-dropdown');
        if (dropdown) dropdown.classList.add('hidden');
        var btn = document.getElementById('persona-switcher-btn');
        if (btn) btn.setAttribute('aria-expanded', 'false');
    };

    function togglePersonaDropdown() {
        var dropdown = document.getElementById('persona-switcher-dropdown');
        var btn = document.getElementById('persona-switcher-btn');
        if (!dropdown) return;
        var isHidden = dropdown.classList.contains('hidden');
        if (isHidden) {
            dropdown.classList.remove('hidden');
            if (btn) btn.setAttribute('aria-expanded', 'true');
            var socket = window.activeFeedSocket || (window.bridgeClient && window.bridgeClient.socket);
            if (socket && socket.readyState === WebSocket.OPEN) {
                socket.send(JSON.stringify({ type: "list_profiles" }));
                socket.send(JSON.stringify({ type: "LIST_PERSONAS" }));
            }
        } else {
            dropdown.classList.add('hidden');
            if (btn) btn.setAttribute('aria-expanded', 'false');
        }
    }
    window.togglePersonaDropdown = togglePersonaDropdown;

    document.addEventListener('click', function (e) {
        var container = document.getElementById('persona-switcher-container');
        var dropdown = document.getElementById('persona-switcher-dropdown');
        var btn = document.getElementById('persona-switcher-btn');
        if (dropdown && container && !container.contains(e.target)) {
            dropdown.classList.add('hidden');
            if (btn) btn.setAttribute('aria-expanded', 'false');
        }
    });

    // ---------- Public API ----------

    window.bridgeClient = new TauriBridgeClient();
    window.tauriBridge = window.bridgeClient;
    window.escapeHtml = escapeHtml;
    window.escapeAttr = escapeAttr;
    window.getCookie = getCookie;
    window.getRelays = getRelays;
    window.setRelays = setRelays;
    window.showToast = window.showToast || showToast;
    window.showSovereignToast = showSovereignToast;
    window.switchTab = switchTab;
    window.uuidv4 = uuidv4;
})();
