/**
 * contact_manager.js — NIP-02 Contact List (Kind 3) & Decentralized Social Graph Manager
 *
 * Implements decentralized friending, following, and mutual friend (Level 1 Peer)
 * detection in iyou_wun:
 * - Queries and maintains cached Kind 3 contact tag list.
 * - Manages Follow / Unfollow state transitions and constructs fresh Kind 3 events.
 * - Dispatches signing requests to iyou_home Signature Bridge (wss://home.iyou.me:9001).
 * - Broadcasts signed contact lists to local (:9003) and remote relays.
 * - Detects mutual follows (Level 1 Peers / Mutual Friends).
 * - Scans and dynamically updates [data-follow-target] buttons in DOM.
 */
(function (global) {
    "use strict";

    // ---------- Constants & Defaults ----------
    // The sovereign local relay (ws://127.0.0.1:9003) is only used on a local HTTP
    // dev origin. Over HTTPS we rely solely on the secure public relay pool so we
    // never touch an unencrypted mixed-content socket.
    function getDefaultRelays() {
        const local = (typeof window !== "undefined" && window.location &&
            window.location.protocol === "http:" &&
            (window.location.hostname === "127.0.0.1" || window.location.hostname === "localhost" || window.location.hostname === "0.0.0.0"))
            ? ["ws://127.0.0.1:9003"]
            : [];
        return ["wss://relay.iyou.me"].concat(local);
    }
    let DEFAULT_RELAYS = getDefaultRelays();
    const DEFAULT_BRIDGE_WS_URL = "wss://home.iyou.me:9001";
    const RELAY_QUERY_TIMEOUT_MS = 3000;
    const RELAY_BROADCAST_TIMEOUT_MS = 4000;
    const SIGNING_TIMEOUT_MS = 8000;

    // Visual styles for button states
    const BUTTON_STYLES = {
        none: {
            classes: "px-2.5 py-1 bg-violet-600 hover:bg-violet-500 text-white rounded text-[10px] sm:text-xs font-semibold transition shrink-0 shadow-sm",
            label: "+ Follow",
            ariaLabel: "Follow this profile"
        },
        follower: {
            classes: "px-2.5 py-1 bg-blue-600 hover:bg-blue-500 text-white rounded text-[10px] sm:text-xs font-semibold transition shrink-0 shadow-sm",
            label: "+ Follow Back",
            ariaLabel: "Follow back this profile"
        },
        following: {
            classes: "px-2.5 py-1 rounded text-[10px] sm:text-xs font-semibold transition shrink-0 border border-slate-700 bg-slate-800 text-slate-300 hover:border-rose-500/60 hover:bg-rose-950/60 hover:text-rose-200 shadow-sm",
            label: "✓ Following",
            ariaLabel: "Following this profile (click to unfollow)"
        },
        mutual: {
            classes: "px-2.5 py-1 rounded text-[10px] sm:text-xs font-semibold transition shrink-0 border border-emerald-500/60 bg-emerald-950/60 text-emerald-300 hover:bg-emerald-900/60 shadow-sm",
            label: "🤝 Friends",
            ariaLabel: "Mutual Friend"
        },
        loading: {
            classes: "px-2.5 py-1 rounded text-[10px] sm:text-xs font-semibold transition shrink-0 border border-slate-700 bg-slate-800 text-slate-400 cursor-wait opacity-80",
            label: "Updating...",
            ariaLabel: "Updating contact status"
        }
    };

    // ---------- State & Cache ----------
    let currentContactList = []; // [["p", "<pubkey_hex>", "<relay_url>", "<petname>"], ...]
    let currentContactEvent = null; // Full latest signed Kind 3 event
    const targetFollowsCache = new Map(); // targetPubkeyHex -> Array of tags
    let isInitialized = false;
    let initPromise = null;

    // ---------- Helper Utilities ----------

    function normalizePubkey(raw) {
        if (!raw) return "";
        const clean = String(raw).trim().toLowerCase();
        if (/^[0-9a-f]{64}$/.test(clean)) return clean;
        return clean;
    }

    function getRelays() {
        if (typeof global.getRelays === "function") {
            return sanitizeRelays(global.getRelays());
        }
        const stored = localStorage.getItem("wun_relays");
        if (stored) {
            try { return sanitizeRelays(JSON.parse(stored)); } catch (e) { /* ignore */ }
        }
        return sanitizeRelays(DEFAULT_RELAYS);
    }

    // Strip unencrypted ws:// relays (e.g. the sovereign 9003 socket) over HTTPS
    // so mixed-content connections are never attempted in production.
    function sanitizeRelays(list) {
        if (!Array.isArray(list)) return [];
        const proto = (typeof window !== "undefined" && window.location) ? window.location.protocol : "";
        if (proto === "https:") {
            return list.filter((r) => !String(r).toLowerCase().startsWith("ws://"));
        }
        return list;
    }

    function getBridgeWsUrl() {
        if (typeof window !== "undefined" && window.talkContext && window.talkContext.bridgeWsUrl) {
            return window.talkContext.bridgeWsUrl;
        }
        if (global.bridgeClient && typeof global.bridgeClient.getBridgeUrl === "function") {
            const url = global.bridgeClient.getBridgeUrl();
            if (url) return url;
        }
        if (global.TAURI_SIGNING_BRIDGE) return global.TAURI_SIGNING_BRIDGE;
        if (global.BRIDGE_WS_URL) return global.BRIDGE_WS_URL;
        const scriptTag = typeof document !== "undefined" ? document.querySelector('script[data-bridge-url]') : null;
        if (scriptTag && scriptTag.getAttribute('data-bridge-url')) {
            return scriptTag.getAttribute('data-bridge-url');
        }
        return (typeof window !== "undefined" && window.location && window.location.protocol === 'https:')
            ? 'wss://home.iyou.me:9001/'
            : 'ws://127.0.0.1:9001/';
    }

    function getBridgeUrl() {
        return getBridgeWsUrl();
    }


    async function getCurrentUserPubkey() {
        if (global.bridgeClient && typeof global.bridgeClient.getEffectivePubkey === "function") {
            try {
                const pk = await global.bridgeClient.getEffectivePubkey();
                if (pk) return normalizePubkey(pk);
            } catch (e) {
                // fall through to window globals
            }
        }
        if (global.activeProfile && global.activeProfile.nostr_pubkey_hex) {
            return normalizePubkey(global.activeProfile.nostr_pubkey_hex);
        }
        if (typeof global.userPubkey !== "undefined" && global.userPubkey) {
            return normalizePubkey(global.userPubkey);
        }
        return null;
    }

    function notifyToast(message, type = "info") {
        if (typeof global.showToast === "function") {
            global.showToast(message, type);
        }
    }

    function notifySovereignToast(message) {
        if (typeof global.showSovereignToast === "function") {
            global.showSovereignToast(message);
        }
    }

    // ---------- Relay Communication ----------

    /**
     * Query Kind 3 event for a given author from all configured relays in parallel.
     * Returns the newest Kind 3 event or null if not found.
     */
    function queryKind3FromRelays(pubkeyHex, timeoutMs = RELAY_QUERY_TIMEOUT_MS) {
        if (!pubkeyHex) return Promise.resolve(null);
        const cleanPubkey = normalizePubkey(pubkeyHex);
        const relays = getRelays();
        const subId = "k3_" + Math.random().toString(36).substring(2, 10);

        return new Promise((resolve) => {
            let latestEvent = null;
            let remaining = relays.length;

            if (remaining === 0) {
                resolve(null);
                return;
            }

            let settled = false;
            function finish() {
                if (settled) return;
                settled = true;
                resolve(latestEvent);
            }

            const timer = setTimeout(finish, timeoutMs);

            relays.forEach((relayUrl) => {
                let ws;
                try {
                    ws = new WebSocket(relayUrl);
                } catch (e) {
                    remaining--;
                    if (remaining <= 0) {
                        clearTimeout(timer);
                        finish();
                    }
                    return;
                }

                ws.onopen = function () {
                    try {
                        ws.send(JSON.stringify(["REQ", subId, { kinds: [3], authors: [cleanPubkey], limit: 1 }]));
                    } catch (e) { /* ignore */ }
                };

                ws.onmessage = function (ev) {
                    try {
                        const data = JSON.parse(ev.data);
                        if (data[0] === "EVENT" && data[1] === subId && data[2]) {
                            const event = data[2];
                            if (event.kind === 3) {
                                if (!latestEvent || (event.created_at && event.created_at > (latestEvent.created_at || 0))) {
                                    latestEvent = event;
                                }
                            }
                        } else if (data[0] === "EOSE" && data[1] === subId) {
                            try { ws.close(); } catch (e) { /* ignore */ }
                        }
                    } catch (e) { /* ignore */ }
                };

                ws.onerror = function () {
                    try { ws.close(); } catch (e) { /* ignore */ }
                };

                ws.onclose = function () {
                    remaining--;
                    if (remaining <= 0) {
                        clearTimeout(timer);
                        finish();
                    }
                };
            });
        });
    }

    /**
     * Broadcast a signed Kind 3 contact list event to local (:9003) and remote relays.
     */
    function broadcastContactEvent(signedEvent, timeoutMs = RELAY_BROADCAST_TIMEOUT_MS) {
        const relays = getRelays();
        let remaining = relays.length;
        let localRelaySuccess = false;
        let anyRemoteSuccess = false;

        return new Promise((resolve) => {
            if (remaining === 0) {
                resolve({ localSuccess: false, anySuccess: false });
                return;
            }

            let settled = false;
            function checkDone() {
                if (settled) return;
                if (remaining <= 0) {
                    settled = true;
                    if (localRelaySuccess) {
                        notifySovereignToast("Sovereign Copy Saved.");
                    }
                    resolve({ localSuccess: localRelaySuccess, anySuccess: anyRemoteSuccess || localRelaySuccess });
                }
            }

            const timer = setTimeout(() => {
                if (!settled) {
                    settled = true;
                    resolve({ localSuccess: localRelaySuccess, anySuccess: anyRemoteSuccess || localRelaySuccess });
                }
            }, timeoutMs);

            relays.forEach((relayUrl) => {
                const isLocal = relayUrl.indexOf("127.0.0.1:9003") !== -1;
                let finished = false;
                const done = function () {
                    if (finished) return;
                    finished = true;
                    remaining--;
                    checkDone();
                };

                try {
                    const ws = new WebSocket(relayUrl);
                    ws.onopen = function () {
                        ws.send(JSON.stringify(["EVENT", signedEvent]));
                    };
                    ws.onmessage = function (ev) {
                        try {
                            const msg = JSON.parse(ev.data);
                            if (msg[0] === "OK" && msg[2] !== false) {
                                if (isLocal) localRelaySuccess = true;
                                else anyRemoteSuccess = true;
                            }
                        } catch (e) { /* ignore */ }
                        try { ws.close(); } catch (e) { /* ignore */ }
                        done();
                    };
                    ws.onerror = function () { done(); };
                    ws.onclose = function () { done(); };
                    setTimeout(function () {
                        try { ws.close(); } catch (e) { /* ignore */ }
                        done();
                    }, timeoutMs);
                } catch (e) {
                    done();
                }
            });
        });
    }

    /**
     * Request a Schnorr signature for the unsigned Kind 3 event via iyou_home Signature Bridge.
     */
    function requestSignatureFromBridge(unsignedEvent, timeoutMs = SIGNING_TIMEOUT_MS) {
        const bridgeUrl = getBridgeUrl();

        return new Promise((resolve, reject) => {
            let settled = false;
            let ws;

            const timer = setTimeout(() => {
                if (!settled) {
                    settled = true;
                    try { if (ws) ws.close(); } catch (e) { /* ignore */ }
                    reject(new Error("Signature Bridge request timed out"));
                }
            }, timeoutMs);

            try {
                ws = new WebSocket(bridgeUrl);
                ws.onopen = function () {
                    try {
                        ws.send(JSON.stringify({ type: "sign_event", event: unsignedEvent }));
                    } catch (err) {
                        if (!settled) {
                            settled = true;
                            clearTimeout(timer);
                            reject(err);
                        }
                    }
                };

                ws.onmessage = function (event) {
                    try {
                        const message = JSON.parse(event.data);
                        if (message.type === "signed_event" && message.event) {
                            if (!settled) {
                                settled = true;
                                clearTimeout(timer);
                                try { ws.close(); } catch (e) { /* ignore */ }
                                resolve(message.event);
                            }
                        }
                    } catch (err) {
                        console.error("Error parsing bridge signing response:", err);
                    }
                };

                ws.onerror = function (err) {
                    if (!settled) {
                        settled = true;
                        clearTimeout(timer);
                        reject(new Error("Unable to connect to Signature Bridge at " + bridgeUrl));
                    }
                };

                ws.onclose = function () {
                    if (!settled) {
                        settled = true;
                        clearTimeout(timer);
                        reject(new Error("Signature Bridge connection closed without response"));
                    }
                };
            } catch (err) {
                if (!settled) {
                    settled = true;
                    clearTimeout(timer);
                    reject(err);
                }
            }
        });
    }

    // ---------- Contact Manager Operations ----------

    /**
     * Initialize contact manager by loading the current user's Kind 3 event from relays.
     */
    async function initContactManager() {
        if (initPromise) return initPromise;

        initPromise = (async () => {
            try {
                const myPubkey = await getCurrentUserPubkey();
                if (myPubkey) {
                    const event = await queryKind3FromRelays(myPubkey);
                    if (event && Array.isArray(event.tags)) {
                        currentContactEvent = event;
                        currentContactList = event.tags.filter(t => Array.isArray(t) && t[0] === "p" && t[1]);
                    }
                }
            } catch (e) {
                console.warn("Contact list initialization warning:", e);
            } finally {
                isInitialized = true;
                bindFollowButtons();
            }
        })();

        return initPromise;
    }

    /**
     * Check the social graph relationship between current user and target pubkey:
     * - 'none': neither follows the other
     * - 'following': current user follows target
     * - 'follower': target follows current user
     * - 'mutual': mutual follows (Level 1 Peer / Mutual Friend)
     */
    async function checkRelationship(targetPubkeyHex) {
        if (!targetPubkeyHex) return "none";
        const cleanTarget = normalizePubkey(targetPubkeyHex);
        const myPubkey = await getCurrentUserPubkey();

        if (!myPubkey) return "none";
        if (cleanTarget === myPubkey) return "self";

        // 1. Does current user follow target?
        const isFollowing = currentContactList.some(
            tag => tag[0] === "p" && tag[1] && normalizePubkey(tag[1]) === cleanTarget
        );

        // 2. Does target follow current user back?
        let targetTags = targetFollowsCache.get(cleanTarget);
        if (targetTags === undefined) {
            try {
                const targetEvent = await queryKind3FromRelays(cleanTarget);
                targetTags = (targetEvent && Array.isArray(targetEvent.tags)) ? targetEvent.tags : [];
                targetFollowsCache.set(cleanTarget, targetTags);
            } catch (e) {
                targetTags = [];
                targetFollowsCache.set(cleanTarget, targetTags);
            }
        }

        const followsBack = targetTags.some(
            tag => tag[0] === "p" && tag[1] && normalizePubkey(tag[1]) === myPubkey
        );

        if (isFollowing && followsBack) return "mutual";
        if (isFollowing) return "following";
        if (followsBack) return "follower";
        return "none";
    }

    /**
     * Follow or unfollow a target pubkey (NIP-02 Kind 3):
     * - If target is already followed -> remove tag (Unfollow)
     * - If target is not followed -> append ["p", targetPubkey, "wss://relay.iyou.me", petname] (Follow)
     * - Dispatches for signature over Bridge and broadcasts to relays.
     */
    async function toggleFollow(targetPubkeyHex, petname = "") {
        if (!targetPubkeyHex) {
            notifyToast("Target public key missing.", true);
            return;
        }

        const cleanTarget = normalizePubkey(targetPubkeyHex);
        const myPubkey = await getCurrentUserPubkey();

        if (!myPubkey) {
            notifyToast("Sign in with a sovereign key to follow contacts.", true);
            return;
        }

        if (cleanTarget === myPubkey) {
            notifyToast("Cannot follow own profile.", true);
            return;
        }

        // Set visual loading state on relevant buttons
        setButtonLoadingState(cleanTarget, true);

        const isCurrentlyFollowing = currentContactList.some(
            tag => tag[0] === "p" && tag[1] && normalizePubkey(tag[1]) === cleanTarget
        );

        let updatedTags;
        if (isCurrentlyFollowing) {
            // Unfollow: remove tag
            updatedTags = currentContactList.filter(
                tag => !(tag[0] === "p" && tag[1] && normalizePubkey(tag[1]) === cleanTarget)
            );
        } else {
            // Follow: append tag
            const followTag = ["p", cleanTarget, "wss://relay.iyou.me", petname || ""];
            updatedTags = [...currentContactList, followTag];
        }

        const unsignedEvent = {
            kind: 3,
            pubkey: myPubkey,
            created_at: Math.floor(Date.now() / 1000),
            tags: updatedTags,
            content: ""
        };

        try {
            // 1. Request signature from bridge
            const signedEvent = await requestSignatureFromBridge(unsignedEvent);

            // 2. Broadcast signed event to relays
            await broadcastContactEvent(signedEvent);

            // 3. Update cached state on success
            currentContactList = updatedTags;
            currentContactEvent = signedEvent;

            // Invalidate target cache
            targetFollowsCache.delete(cleanTarget);

            if (isCurrentlyFollowing) {
                notifyToast("Unfollowed contact", "info");
            } else {
                notifyToast("Follow list updated (Kind 3)", "success");
            }
        } catch (err) {
            console.error("Failed to toggle follow:", err);
            notifyToast("Follow action failed: " + err.message, "error");

            // Fallback modal support if bridgeClient modal is in DOM
            if (global.bridgeClient && typeof global.bridgeClient.showFallbackModal === "function") {
                global.bridgeClient.pendingEvent = unsignedEvent;
                global.bridgeClient.showFallbackModal();
            }
        } finally {
            setButtonLoadingState(cleanTarget, false);
            await updateButtonsForTarget(cleanTarget);
        }
    }

    /**
     * Server-backed follow/unfollow (Phase 22). Prepares the unsigned NIP-02
     * Kind 3 contact-list event via POST /api/contacts/follow/, signs it through
     * the Signature Bridge, broadcasts it across the active pool relays, and
     * updates local cache + button state.
     */
    async function toggleFollowUser(targetPubkey, targetName) {
        if (!targetPubkey) {
            notifyToast("Target public key missing.", true);
            return;
        }
        const cleanTarget = normalizePubkey(targetPubkey);
        const myPubkey = await getCurrentUserPubkey();
        if (!myPubkey) {
            notifyToast("Sign in with a sovereign key to follow contacts.", true);
            return;
        }
        if (cleanTarget === myPubkey) {
            notifyToast("Cannot follow own profile.", true);
            return;
        }

        const isCurrentlyFollowing = currentContactList.some(
            tag => tag[0] === "p" && tag[1] && normalizePubkey(tag[1]) === cleanTarget
        );
        const action = isCurrentlyFollowing ? "unfollow" : "follow";

        setButtonLoadingState(cleanTarget, true);

        let payload;
        try {
            const resp = await fetch("/api/contacts/follow/", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "X-CSRFToken": (global.csrfToken || (document.querySelector('[name=csrfmiddlewaretoken]') || {}).value) || "",
                },
                credentials: "same-origin",
                body: JSON.stringify({
                    target_pubkey: cleanTarget,
                    action: action,
                    target_name: targetName || "",
                }),
            });
            payload = await resp.json().catch(function () { return {}; });
            if (!resp.ok || !payload.success) {
                throw new Error(payload.error || "Follow action failed.");
            }
        } catch (err) {
            setButtonLoadingState(cleanTarget, false);
            notifyToast("Follow action failed: " + err.message, "error");
            return;
        }

        const unsigned = payload.event;
        if (!unsigned) {
            setButtonLoadingState(cleanTarget, false);
            notifyToast("Server did not return a contact event to sign.", "error");
            return;
        }

        const bridge = global.bridgeClient;
        const freshlySignedTags = (unsigned.tags || []).filter(t => Array.isArray(t) && t[0] === "p" && t[1]);

        function finalize() {
            currentContactList = freshlySignedTags;
            targetFollowsCache.delete(cleanTarget);
            setButtonLoadingState(cleanTarget, false);
            updateButtonsForTarget(cleanTarget);
            const who = targetName ? "@" + targetName : "contact";
            if (action === "follow") notifyToast("Followed " + who, "success");
            else notifyToast("Unfollowed " + who, "info");
            if (typeof global.dispatchEvent === "function") {
                try {
                    global.dispatchEvent(new CustomEvent("contactsUpdated", { detail: { contacts: currentContactList } }));
                } catch (e) { /* ignore */ }
            }
        }

        // Prefer the Signature Bridge connect() + signEvent() flow, falling back
        // to the direct bridge WebSocket signer when that API is unavailable.
        if (bridge && typeof bridge.signEvent === "function" && typeof bridge.connect === "function") {
            const onSigned = function (signedEvent) {
                if (!signedEvent || signedEvent.kind !== 3) return;
                Promise.resolve().then(function () {
                    if (typeof bridge.broadcastToRelays === "function") {
                        bridge.broadcastToRelays(signedEvent, null, function () {
                            currentContactEvent = signedEvent;
                            finalize();
                        });
                    } else {
                        broadcastContactEvent(signedEvent).then(function () {
                            currentContactEvent = signedEvent;
                            finalize();
                        });
                    }
                });
            };
            bridge.connect(onSigned);
            bridge.signEvent(unsigned);
        } else {
            try {
                const signedEvent = await requestSignatureFromBridge(unsigned);
                await broadcastContactEvent(signedEvent);
                currentContactEvent = signedEvent;
                finalize();
            } catch (err) {
                setButtonLoadingState(cleanTarget, false);
                notifyToast("Follow failed to sign: " + err.message, "error");
            }
        }
    }

    // ---------- DOM Rendering & Binding ----------

    function setButtonLoadingState(targetPubkey, isLoading) {
        const cleanTarget = normalizePubkey(targetPubkey);
        const buttons = document.querySelectorAll(`[data-follow-target]`);

        buttons.forEach((btn) => {
            const btnTarget = normalizePubkey(btn.getAttribute("data-follow-target"));
            if (btnTarget !== cleanTarget) return;

            btn.disabled = isLoading;
            const spinner = btn.querySelector(".btn-spinner");
            const label = btn.querySelector(".btn-label");

            if (isLoading) {
                if (!(btn.dataset && btn.dataset.followMenu === "true")) {
                    btn.className = BUTTON_STYLES.loading.classes;
                }
                if (spinner) spinner.classList.remove("hidden");
                if (label) label.textContent = "Signing...";
            } else {
                if (spinner) spinner.classList.add("hidden");
            }
        });
    }

    async function updateButtonsForTarget(targetPubkey) {
        const cleanTarget = normalizePubkey(targetPubkey);
        const buttons = document.querySelectorAll(`[data-follow-target]`);

        for (const btn of buttons) {
            const btnTarget = normalizePubkey(btn.getAttribute("data-follow-target"));
            if (btnTarget !== cleanTarget) continue;

            const state = await checkRelationship(cleanTarget);
            applyButtonState(btn, state);
        }
    }

    function applyButtonState(btn, state) {
        if (!btn) return;
        const config = BUTTON_STYLES[state] || BUTTON_STYLES.none;
        const isMenuRow = btn.dataset && btn.dataset.followMenu === "true";

        if (!isMenuRow) {
            btn.className = config.classes;
        }
        btn.setAttribute("data-relationship-state", state);
        btn.setAttribute("aria-label", config.ariaLabel);

        const label = btn.querySelector(".btn-label");
        const spinner = btn.querySelector(".btn-spinner");

        if (spinner) spinner.classList.add("hidden");

        if (isMenuRow) {
            const who = btn.getAttribute("data-follow-petname") || "author";
            const menuLabel = (state === "following")
                ? "➖ Unfollow @" + who
                : "➕ Follow @" + who;
            if (label) {
                label.textContent = menuLabel;
            } else {
                btn.textContent = menuLabel;
            }
            return;
        }

        if (label) {
            label.textContent = config.label;
        } else {
            btn.textContent = config.label;
        }

        if (state === "following") {
            btn.onmouseenter = function () {
                if (label) label.textContent = "Unfollow";
                else btn.textContent = "Unfollow";
            };
            btn.onmouseleave = function () {
                if (label) label.textContent = config.label;
                else btn.textContent = config.label;
            };
        } else {
            btn.onmouseenter = null;
            btn.onmouseleave = null;
        }
    }

    /**
     * Scan DOM for [data-follow-target] buttons and bind handlers & state.
     */
    function bindFollowButtons(rootElement = document) {
        const root = rootElement || document;
        const buttons = root.querySelectorAll("[data-follow-target]");

        buttons.forEach((btn) => {
            const target = normalizePubkey(btn.getAttribute("data-follow-target"));
            const petname = btn.getAttribute("data-follow-petname") || "";
            if (!target) return;

            if (!btn.dataset.contactBound) {
                btn.dataset.contactBound = "true";
                btn.addEventListener("click", async function (e) {
                    e.preventDefault();
                    e.stopPropagation();
                    await toggleFollowUser(target, petname);
                });
            }

            // Asynchronously resolve and render current relationship state
            checkRelationship(target).then((state) => {
                applyButtonState(btn, state);
            });
        });
    }

    function isFollowing(pubkey) {
        if (!pubkey) return false;
        const clean = normalizePubkey(pubkey);
        const myPubkey = (global.userPubkey || (global.activeProfile && global.activeProfile.nostr_pubkey_hex) || "").toLowerCase();
        if (myPubkey && clean === myPubkey) return true;
        return currentContactList.some(
            tag => tag[0] === "p" && tag[1] && normalizePubkey(tag[1]) === clean
        );
    }

    function isMutualFriend(pubkey) {
        if (!pubkey) return false;
        const clean = normalizePubkey(pubkey);
        const myPubkey = (global.userPubkey || (global.activeProfile && global.activeProfile.nostr_pubkey_hex) || "").toLowerCase();
        if (myPubkey && clean === myPubkey) return true;
        if (!isFollowing(clean)) return false;
        const targetTags = targetFollowsCache.get(clean);
        if (targetTags && Array.isArray(targetTags)) {
            return targetTags.some(
                tag => tag[0] === "p" && tag[1] && normalizePubkey(tag[1]) === myPubkey
            );
        }
        return false;
    }

    // ---------- Public API & Auto-Initialization ----------

    const contactManager = {
        init: initContactManager,
        toggleFollow: toggleFollow,
        toggleFollowUser: toggleFollowUser,
        checkRelationship: checkRelationship,
        isFollowing: isFollowing,
        isMutualFriend: isMutualFriend,
        bindButtons: bindFollowButtons,
        scanFollowButtons: bindFollowButtons,
        getCurrentContactList: () => [...currentContactList],
        getRelays: getRelays,
        BUTTON_STYLES: BUTTON_STYLES
    };

    // Attach to global window
    global.contactManager = contactManager;
    global.ContactManager = contactManager;
    global.toggleFollow = toggleFollow;
    global.toggleFollowUser = toggleFollowUser;
    global.checkRelationship = checkRelationship;
    global.scanFollowButtons = bindFollowButtons;

    // Auto-initialize when DOM is ready
    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", function () {
            initContactManager().then(() => {
                try {
                    window.dispatchEvent(new CustomEvent("contactsUpdated", { detail: { contacts: currentContactList } }));
                } catch (e) { /* ignore */ }
            });
        });
    } else {
        initContactManager().then(() => {
            try {
                window.dispatchEvent(new CustomEvent("contactsUpdated", { detail: { contacts: currentContactList } }));
            } catch (e) { /* ignore */ }
        });
    }

    // Export module if in module context
    if (typeof module !== "undefined" && module.exports) {
        module.exports = contactManager;
    }

})(typeof window !== "undefined" ? window : globalThis);

