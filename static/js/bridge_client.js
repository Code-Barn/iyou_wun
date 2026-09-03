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
    var PERSONA_QUERY_TIMEOUT_MS = 2500;

    // The sovereign local relay (ws://127.0.0.1:9003) is only included on a local
    // HTTP dev origin; over HTTPS we rely solely on the secure public pool.
    function localDevOrigin() {
        return typeof window !== "undefined" && window.location &&
            window.location.protocol === "http:" &&
            (window.location.hostname === "127.0.0.1" || window.location.hostname === "localhost" || window.location.hostname === "0.0.0.0");
    }

    function buildDefaultRelays() {
        var list = [
            "wss://relay.iyou.me",
            "wss://nos.lol",
            "wss://relay.damus.io",
            "wss://relay.primal.net"
        ];
        if (localDevOrigin()) list.push("ws://127.0.0.1:9003");
        return list;
    }

    var DEFAULT_RELAYS = buildDefaultRelays();

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

    function getCsrfToken() {
        var cookieToken = getCookie("csrftoken");
        if (cookieToken && cookieToken.length >= 32) return cookieToken;
        var input = document.querySelector("[name=csrfmiddlewaretoken]");
        var inputToken = input && input.value ? input.value : "";
        if (inputToken && inputToken.length >= 32) return inputToken;
        return "";
    }

    function getRelays() {
        if (typeof window !== "undefined" && window.relayPool && typeof window.relayPool.getRelays === "function") {
            return sanitizeRelays(window.relayPool.getRelays());
        }
        var stored = localStorage.getItem("wun_relays");
        if (stored) {
            try { return sanitizeRelays(JSON.parse(stored)); } catch (e) { /* ignore */ }
        }
        return sanitizeRelays(DEFAULT_RELAYS);
    }

    // Strip unencrypted ws:// relays over HTTPS production to avoid mixed-content.
    function sanitizeRelays(list) {
        if (!Array.isArray(list)) return [];
        if (typeof window !== "undefined" && window.location && window.location.protocol === "https:") {
            return list.filter(function (r) { return String(r).toLowerCase().indexOf("ws://") !== 0; });
        }
        return list;
    }

    function setRelays(list) {
        localStorage.setItem("wun_relays", JSON.stringify(list));
    }

    function uuidv4() {
        return "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx".replace(/x/g, function () {
            return Math.floor(Math.random() * 16).toString(16);
        });
    }

    function isHex64(str) {
        return typeof str === "string" && /^[0-9a-fA-F]{64}$/.test(str);
    }

    function bytesToBase64(bytes) {
        var bin = "";
        for (var i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]);
        return btoa(bin);
    }

    function base64ToBytes(b64) {
        var bin = atob(String(b64).replace(/-/g, "+").replace(/_/g, "/"));
        var bytes = new Uint8Array(bin.length);
        for (var i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
        return bytes;
    }

    // ---------- NIP-04 Web Crypto fallback helpers ----------
    //
    // The iyou_home enclave performs real NIP-04 (ECDH + AES-CBC) encryption.
    // When the bridge is offline and no local private key material exists in
    // memory, these helpers derive a per-conversation AES-256-CBC session key
    // from the in-memory identity pair so offline DMs stay round-trippable.
    // This is a degraded cipher, never a substitute for enclave signing.

    function nip04LocalIdentityHex() {
        var profile = (typeof window !== "undefined" && window.activeProfile) ? window.activeProfile : null;
        if (profile) {
            var hex = profile.nostr_pubkey_hex || profile.pubkey_hex || profile.pubkey || "";
            if (isHex64(hex)) return hex.toLowerCase();
        }
        if (typeof window !== "undefined" && isHex64(window.userPubkey)) {
            return String(window.userPubkey).toLowerCase();
        }
        return "";
    }

    function nip04FallbackSeed(peerHex) {
        // SHA-256 over "<localIdentityHex>:<peerHex>" — stable per conversation pair.
        var local = nip04LocalIdentityHex() || "iyou-local-enclave-fallback";
        return crypto.subtle.digest("SHA-256", new TextEncoder().encode(local + ":" + peerHex));
    }

    function nip04WebCryptoKey(peerHex) {
        if (typeof crypto === "undefined" || !crypto.subtle) {
            return Promise.reject(new Error("Web Crypto unavailable"));
        }
        return nip04FallbackSeed(peerHex)
            .then(function (digest) {
                return crypto.subtle.importKey("raw", digest, { name: "AES-CBC" }, false, ["encrypt", "decrypt"]);
            });
    }

    function nip04WebCryptoEncrypt(peerHex, plaintext) {
        if (typeof crypto === "undefined" || !crypto.subtle) {
            return Promise.reject(new Error("Web Crypto unavailable"));
        }
        var iv = crypto.getRandomValues(new Uint8Array(16));
        return nip04WebCryptoKey(peerHex)
            .then(function (key) {
                return crypto.subtle.encrypt({ name: "AES-CBC", iv: iv }, key, new TextEncoder().encode(plaintext));
            })
            .then(function (cipherBuffer) {
                return bytesToBase64(new Uint8Array(cipherBuffer)) + "?iv=" + bytesToBase64(iv);
            });
    }

    function nip04WebCryptoDecrypt(senderHex, encryptedPayload) {
        if (typeof crypto === "undefined" || !crypto.subtle) {
            return Promise.reject(new Error("Web Crypto unavailable"));
        }
        var parts = String(encryptedPayload || "").split("?iv=");
        if (parts.length !== 2) return Promise.reject(new Error("Invalid NIP-04 payload shape"));
        var cipherBytes = base64ToBytes(parts[0]);
        var ivBytes = base64ToBytes(parts[1]);
        if (!cipherBytes || !ivBytes || ivBytes.length !== 16) {
            return Promise.reject(new Error("Invalid NIP-04 ciphertext or IV"));
        }
        return nip04WebCryptoKey(senderHex)
            .then(function (key) {
                return crypto.subtle.decrypt({ name: "AES-CBC", iv: ivBytes }, key, cipherBytes);
            })
            .then(function (plainBuffer) {
                return new TextDecoder().decode(plainBuffer);
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
        this._personaQueryTimer = null;        // enclave persona list query timeout
        this._personaQueryActive = false;      // waiting on an enclave persona list response
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
        if (typeof window !== "undefined" && window.talkContext && window.talkContext.bridgeWsUrl) {
            return window.talkContext.bridgeWsUrl;
        }
        var scriptTag = document.querySelector('script[src*="bridge_client.js"]');
        var url = (scriptTag && scriptTag.getAttribute("data-bridge-url")) || "";
        if (url) return url;
        if (typeof window !== "undefined" && window.TAURI_SIGNING_BRIDGE) return window.TAURI_SIGNING_BRIDGE;
        if (typeof window !== "undefined" && window.BRIDGE_WS_URL) return window.BRIDGE_WS_URL;
        return (typeof window !== "undefined" && window.location && window.location.protocol === "https:")
            ? "wss://home.iyou.me:9001/"
            : "ws://127.0.0.1:9001/";
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
                if (typeof window.updateMobileBridgeHealth === "function") {
                    window.updateMobileBridgeHealth(true);
                }
                if (self.pendingSignedPayload) return;
                socket.send(JSON.stringify({ type: "get_profile" }));
                self.queryVaultPersonas();
            };
            socket.onmessage = function (event) {
                self._handleMessage(event.data);
            };
            socket.onerror = function () {
                clearTimeout(connectTimeout);
                if (!connected) {
                    self.connectionLock = "IDLE";
                    if (self._personaQueryActive) self.markPersonaBridgeOffline();
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
                if (typeof window.updateMobileBridgeHealth === "function") {
                    window.updateMobileBridgeHealth(false);
                }
                if (self._personaQueryActive) self.markPersonaBridgeOffline();
            };
        } catch (err) {
            this.connectionLock = "IDLE";
            if (this._personaQueryActive) this.markPersonaBridgeOffline();
            if (this.isProcessing) this.showFallbackModal();
        }
    };

    TauriBridgeClient.prototype.updateActivePersonaUI = function (profile) {
        if (!profile) return;
        var labelEl = document.getElementById("active-persona-display-name") || document.getElementById("active-persona-label");
        var altLabelEl = document.getElementById("active-persona-label");
        var levelEl = document.getElementById("active-persona-level");
        var dotEl = document.getElementById("active-persona-dot");

        var nameStr = "";
        if (profile.handle) {
            nameStr = "@" + String(profile.handle).replace(/^@/, "");
        } else if (profile.name || profile.profile_name || profile.label) {
            nameStr = profile.name || profile.profile_name || profile.label;
        } else if (profile.npub) {
            nameStr = profile.npub.slice(0, 14) + "...";
        } else if (profile.did) {
            nameStr = profile.did.slice(0, 16) + "...";
        } else if (profile.nostr_pubkey_hex) {
            nameStr = profile.nostr_pubkey_hex.slice(0, 12) + "...";
        } else {
            nameStr = "Sovereign";
        }

        if (labelEl) {
            labelEl.textContent = nameStr;
            labelEl.title = profile.did || profile.nostr_pubkey_hex || nameStr;
        }
        if (altLabelEl && altLabelEl !== labelEl) {
            altLabelEl.textContent = nameStr;
            altLabelEl.title = profile.did || profile.nostr_pubkey_hex || nameStr;
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

    /**
     * Realign the Django session with the enclave's newly-activated persona.
     * Fires whenever the bridge reports a persona whose DID diverges from the
     * server-rendered session DID (`window.CURRENT_SESSION_DID`). On success the
     * session is re-anchored to the persona's isolated link deck; the page is
     * refreshed except on the dashboard, which self-heals via the
     * `persona:session-reanchored` event so the bridge socket is never dropped.
     */
    TauriBridgeClient.prototype.handlePersonaChanged = function (profile) {
        if (!profile) return;
        var did = profile.did || profile.active_did || "";
        var sessionDid = (typeof window.CURRENT_SESSION_DID === "string") ? window.CURRENT_SESSION_DID : "";
        if (!did || !sessionDid || did === sessionDid) return;

        var name = profile.name || profile.profile_name || profile.label || "";
        var level = profile.level !== undefined ? profile.level : (profile.derivation_index || 1);
        if (typeof level === "string") level = parseInt(level, 10) || 1;

        var payload = {
            did: did,
            persona_name: String(name),
            level: level
        };
        var csrfToken = (typeof getCsrfToken === "function")
            ? getCsrfToken()
            : ((typeof getCookie === "function") ? getCookie("csrftoken") : "");

        try {
            fetch("/api/auth/persona-switch/", {
                method: "POST",
                credentials: "same-origin",
                headers: {
                    "Content-Type": "application/json",
                    "X-CSRFToken": csrfToken
                },
                body: JSON.stringify(payload)
            }).then(function (res) {
                return res.json().catch(function () { return null; });
            }).then(function (data) {
                if (data && data.success) {
                    window.CURRENT_SESSION_DID = did;
                    window.dispatchEvent(new CustomEvent("persona:session-reanchored", { detail: data }));
                    var label = data.handle ? "@" + String(data.handle).replace(/^@/, "") : (name || did);
                    if (typeof showToast === "function") {
                        showToast("Session re-anchored to " + label);
                    }
                    if (window.location.pathname !== "/dashboard") {
                        window.location.reload();
                    }
                } else {
                    console.warn("Persona re-anchor rejected:", data && data.error ? data.error : "unknown response");
                }
            }).catch(function (err) {
                console.error("Persona re-anchor failed:", err);
            });
        } catch (e) {
            console.warn("Persona switch failed with exception:", e.message || e);
        }
    };

    /**
     * Query the iyou_home enclave for the active persona list with a bounded
     * timeout. Arms a 2500ms timer; if the bridge never answers (or the socket
     * dies), the dropdown degrades to an explicit offline state.
     */
    TauriBridgeClient.prototype.queryVaultPersonas = function () {
        var self = this;
        if (this._personaQueryActive) return;
        this._personaQueryActive = true;

        var container = document.getElementById("persona-list-container");
        if (container) {
            container.innerHTML = '<div class="px-2 py-2 text-slate-400 text-center text-[11px] animate-pulse">Querying local vault personas...</div>';
        }

        var socket = this.socket;
        if (socket && socket.readyState === WebSocket.OPEN) {
            socket.send(JSON.stringify({ type: "list_profiles" }));
            socket.send(JSON.stringify({ type: "LIST_PERSONAS" }));
        } else {
            this.connect();
        }

        if (this._personaQueryTimer) clearTimeout(this._personaQueryTimer);
        this._personaQueryTimer = setTimeout(function () {
            self._personaQueryTimer = null;
            if (self._personaQueryActive) self.markPersonaBridgeOffline();
        }, PERSONA_QUERY_TIMEOUT_MS);
    };

    /**
     * Degrade the persona switcher to an explicit offline state: replace the
     * list with an "Enclave Offline" notice and flip the bridge status pill to
     * amber. Idempotent — safe to call repeatedly.
     */
    TauriBridgeClient.prototype.markPersonaBridgeOffline = function () {
        this._personaQueryActive = false;
        if (this._personaQueryTimer) {
            clearTimeout(this._personaQueryTimer);
            this._personaQueryTimer = null;
        }
        var container = document.getElementById("persona-list-container");
        if (container) {
            container.innerHTML = '<div class="px-3 py-3 text-center">' +
                '<div class="text-[11px] font-mono text-amber-500 font-semibold mb-1">⚠️ Enclave Offline</div>' +
                '<p class="text-[10px] text-slate-400 leading-tight">Start iyou_home to enable contextual persona switching and local signing.</p>' +
                '</div>';
        }
        var pill = document.getElementById("persona-bridge-status");
        if (pill) {
            pill.textContent = "BRIDGE OFFLINE";
            pill.className = "text-amber-500 font-normal";
        }
        if (typeof window.updateMobileBridgeHealth === "function") {
            window.updateMobileBridgeHealth(false);
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

            var name = "";
            if (p.handle) {
                name = "@" + String(p.handle).replace(/^@/, "");
            } else if (p.name || p.profile_name || p.label) {
                name = p.name || p.profile_name || p.label;
            } else if (p.npub) {
                name = p.npub.slice(0, 14) + "...";
            } else if (p.did) {
                name = p.did.slice(0, 16) + "...";
            } else if (pPk) {
                name = pPk.slice(0, 10) + "...";
            } else {
                name = "Persona";
            }
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
                // The enclave answered: disarm the persona query timeout and
                // restore the default connected pill state.
                this._personaQueryActive = false;
                if (this._personaQueryTimer) {
                    clearTimeout(this._personaQueryTimer);
                    this._personaQueryTimer = null;
                }
                var bridgeStatusEl = document.getElementById("persona-bridge-status");
                if (bridgeStatusEl) {
                    bridgeStatusEl.textContent = "Bridge Connected";
                    bridgeStatusEl.className = "text-emerald-500 font-normal";
                }
                this.renderPersonaDropdownList(validProfiles);
                return;
            }

            if (message.type === "profile_sync" || message.type === "profile_activated" || message.type === "active_profile_changed" || message.type === "SET_ACTIVE_PERSONA_RESPONSE") {
                var prof = message.profile || message.active_profile || message.persona;
                if (prof) {
                    var previousPubkey = window.activeProfile ? (window.activeProfile.nostr_pubkey_hex || window.activeProfile.pubkey_hex) : null;
                    window.activeProfile = prof;
                    this.updateActivePersonaUI(prof);
                    this.handlePersonaChanged(prof);
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
                if (this._signResolvers && this._signResolvers.length) {
                    var resolver = this._signResolvers.shift();
                    resolver(this.pendingEvent || signedEvent);
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
        var self = this;
        var promise = new Promise(function (resolve) {
            self._signResolvers = self._signResolvers || [];
            self._signResolvers.push(resolve);
            setTimeout(function () {
                var idx = self._signResolvers.indexOf(resolve);
                if (idx !== -1) {
                    self._signResolvers.splice(idx, 1);
                    resolve(self.pendingEvent || event);
                }
            }, SOCKET_POLL_TIMEOUT + 1000);
        });

        if (!this.socket || this.socket.readyState !== WebSocket.OPEN) {
            this.connect();
        }

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

    // ---------- NIP-04 End-to-End DM Cryptography ----------
    //
    // Primary path: the iyou_home enclave bridge performs real NIP-04
    // encryption/decryption (secp256k1 ECDH + AES-256-CBC). Frames are
    // correlated by peer pubkey, mirroring the sign_event/list_profiles
    // request pattern. When the bridge is offline, Web Crypto helpers fall
    // back to a per-conversation session cipher so offline DMs stay readable.

    TauriBridgeClient.prototype.nip04Encrypt = function (recipientPubkeyHex, plaintext) {
        var self = this;
        var peerHex = String(recipientPubkeyHex || "").toLowerCase();
        plaintext = String(plaintext == null ? "" : plaintext);
        if (!isHex64(peerHex) || !plaintext) {
            return Promise.reject(new Error("NIP-04 encrypt requires a valid 64-char peer pubkey and a message"));
        }
        if (this.socket && this.socket.readyState === WebSocket.OPEN) {
            return this._nip04BridgeRequest("NIP04_ENCRYPT", "NIP04_ENCRYPT_RESPONSE", peerHex, plaintext)
                .then(function (msg) {
                    if (msg.encrypted_payload) return msg.encrypted_payload;
                    throw new Error("NIP-04 response missing encrypted_payload");
                })
                .catch(function () {
                    return nip04WebCryptoEncrypt(peerHex, plaintext);
                });
        }
        return nip04WebCryptoEncrypt(peerHex, plaintext);
    };

    TauriBridgeClient.prototype.nip04Decrypt = function (senderPubkeyHex, encryptedPayload) {
        var self = this;
        var senderHex = String(senderPubkeyHex || "").toLowerCase();
        if (!isHex64(senderHex) || !encryptedPayload) {
            return Promise.reject(new Error("NIP-04 decrypt requires a valid 64-char sender pubkey and a payload"));
        }
        var gracefulFallback = "[Encrypted Message — Open Enclave to Decrypt]";
        if (this.socket && this.socket.readyState === WebSocket.OPEN) {
            return this._nip04BridgeRequest("NIP04_DECRYPT", "NIP04_DECRYPT_RESPONSE", senderHex, encryptedPayload)
                .then(function (msg) {
                    return msg.plaintext || msg.payload || msg.content || gracefulFallback;
                })
                .catch(function () {
                    return nip04WebCryptoDecrypt(senderHex, encryptedPayload).catch(function () {
                        return gracefulFallback;
                    });
                });
        }
        return nip04WebCryptoDecrypt(senderHex, encryptedPayload).catch(function () {
            return gracefulFallback;
        });
    };

    TauriBridgeClient.prototype._nip04BridgeRequest = function (frameType, responseType, peerHex, content) {
        var self = this;
        var frame = { type: frameType, peer_pubkey: peerHex, content: content };
        return new Promise(function (resolve, reject) {
            function awaitResponse(event) {
                var msg = null;
                try { msg = JSON.parse(event.data); } catch (err) { return; }
                if (msg && msg.type === responseType && String(msg.peer_pubkey || "").toLowerCase() === peerHex) {
                    cleanup();
                    resolve(msg);
                }
            }
            function cleanup() {
                clearTimeout(deadline);
                try { self.socket.removeEventListener("message", awaitResponse); } catch (err) {}
            }
            var deadline = setTimeout(function () {
                cleanup();
                reject(new Error("NIP-04 bridge request timed out"));
            }, SOCKET_POLL_TIMEOUT);
            try { self.socket.addEventListener("message", awaitResponse); } catch (err) {
                cleanup();
                reject(err);
                return;
            }
            try {
                self.socket.send(JSON.stringify(frame));
            } catch (err) {
                cleanup();
                reject(err);
            }
        });
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
            var client = window.bridgeClient;
            if (client && typeof client.queryVaultPersonas === "function") {
                client.queryVaultPersonas();
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
    window.getCsrfToken = getCsrfToken;
    window.getRelays = getRelays;
    window.setRelays = setRelays;
    window.showToast = window.showToast || showToast;
    window.showSovereignToast = showSovereignToast;
    window.switchTab = switchTab;
    window.uuidv4 = uuidv4;
})();
