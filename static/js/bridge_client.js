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

    var DEFAULT_RELAYS = ["ws://127.0.0.1:9003", "wss://relay.iyou.me"];

    // ---------- Utilities ----------

    function escapeHtml(str) {
        if (!str) return "";
        var div = document.createElement("div");
        div.appendChild(document.createTextNode(str));
        return div.innerHTML;
    }

    function escapeAttr(str) {
        if (!str) return "";
        return str.replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/'/g, "&#39;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    }

    function getCookie(name) {
        var match = document.cookie.match(new RegExp("(^| )" + name + "=([^;]+)"));
        return match ? decodeURIComponent(match[2]) : "";
    }

    function getRelays() {
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

    function showToast(message, isError) {
        var toast = document.getElementById("toast");
        if (!toast) return;
        var span = toast.querySelector("span");
        if (span) span.textContent = message;
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
    }

    TauriBridgeClient.prototype.getBridgeUrl = function () {
        var scriptTag = document.querySelector('script[src*="bridge_client.js"]');
        return (scriptTag && scriptTag.getAttribute("data-bridge-url")) || "";
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
                if (self.pendingSignedPayload) return;
                socket.send(JSON.stringify({ type: "get_profile" }));
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
                self.connectionLock = "IDLE";
            };
        } catch (err) {
            this.connectionLock = "IDLE";
            if (this.isProcessing) this.showFallbackModal();
        }
    };

    TauriBridgeClient.prototype._handleMessage = function (data) {
        try {
            var message = JSON.parse(data);

            if (message.type === "profile_sync") {
                window.activeProfile = message.profile;
                return;
            }

            if (message.type === "signed_event" && this.pendingEvent) {
                var signedEvent = message.event;
                this.pendingEvent.id = signedEvent.id;
                this.pendingEvent.sig = signedEvent.sig;

                if (this._onMessage) {
                    this._onMessage(this.pendingEvent, signedEvent);
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
        var bridgePk = window.activeProfile ? window.activeProfile.nostr_pubkey_hex : null;
        var templatePk = (typeof window.userPubkey !== "undefined" && window.userPubkey) ? window.userPubkey : null;
        var pk = (bridgePk && bridgePk.length === 64) ? bridgePk : templatePk;
        if (!pk || pk.length !== 64 || !/^[a-fA-F0-9]{64}$/.test(pk)) {
            throw new Error("Identity Synchronization Required: No valid secp256k1 pubkey found");
        }
        return pk;
    };

    TauriBridgeClient.prototype.broadcastToRelays = function (signedEvent, relayList, onDone) {
        var relays = relayList || getRelays();
        var remaining = relays.length;
        var localRelaySuccess = false;
        var anyGlobalSuccess = false;

        var self = this;

        function checkDone() {
            if (remaining > 0) return;
            if (localRelaySuccess) showSovereignToast("Sovereign Copy Saved.");
            if (onDone) {
                onDone(localRelaySuccess, anyGlobalSuccess);
            }
        }

        relays.forEach(function (relayUrl) {
            var isLocal = relayUrl.indexOf("127.0.0.1:9003") !== -1;
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

    function switchTab(name) {
        document.querySelectorAll(".tab-panel").forEach(function (el) {
            el.classList.add("hidden");
        });
        var panel = document.getElementById("tab-" + name);
        if (panel) panel.classList.remove("hidden");
        document.querySelectorAll(".tab-btn").forEach(function (btn) {
            btn.classList.remove("text-indigo-600", "border-indigo-600");
            btn.classList.add("text-gray-500", "border-transparent");
        });
        var active = document.querySelector('.tab-btn[data-tab="' + name + '"]');
        if (active) {
            active.classList.remove("text-gray-500", "border-transparent");
            active.classList.add("text-indigo-600", "border-indigo-600");
        }
    }

    // ---------- Public API ----------

    window.bridgeClient = new TauriBridgeClient();
    window.escapeHtml = escapeHtml;
    window.escapeAttr = escapeAttr;
    window.getCookie = getCookie;
    window.getRelays = getRelays;
    window.setRelays = setRelays;
    window.showToast = showToast;
    window.showSovereignToast = showSovereignToast;
    window.switchTab = switchTab;
    window.uuidv4 = uuidv4;
})();
