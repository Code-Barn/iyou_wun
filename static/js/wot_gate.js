/**
 * static/js/wot_gate.js — Inbound DM & Chat Filtering Gate (DEP-202 & DEP-203)
 *
 * Intercepts inbound Nostr encrypted DMs (kind:4 / NIP-04) and XMPP stanzas:
 * - Queries the local contact trust engine (contactManager, trustLens, bridgeClient).
 * - Rejects inbound chat handshakes if the sender's graph distance exceeds wot_distance_limit.
 * - Drops unknown messages silently without alerting the minor or exposing message previews.
 * - Zero PII: verifies cryptographic keys and graph edge distances only.
 */
(function (global) {
    "use strict";

    function normalizeKey(raw) {
        if (!raw) return "";
        var clean = String(raw).trim().toLowerCase();
        if (clean.indexOf("/") !== -1 && clean.indexOf("@") !== -1) {
            clean = clean.split("/")[0];
        }
        return clean;
    }

    function getContext() {
        if (global.DEPENDENT_CONTEXT) {
            return global.DEPENDENT_CONTEXT;
        }
        try {
            var stored = localStorage.getItem("wun_dependent_context");
            if (stored) return JSON.parse(stored);
        } catch (e) { /* ignore */ }

        return {
            is_dependent: false,
            bracket: "ADULT",
            wot_distance_limit: Infinity,
            parent_did: null,
            approved_contacts: []
        };
    }

    /**
     * Compute the sender's WoT graph distance using the local contact trust engine.
     */
    function getSenderWoTDistance(sender) {
        var clean = normalizeKey(sender);
        if (!clean) return Infinity;

        var ctx = getContext();
        var parentDid = normalizeKey(ctx.parent_did);
        var myPubkey = normalizeKey(global.userPubkey || (global.activeProfile && global.activeProfile.nostr_pubkey_hex) || "");
        var myDid = normalizeKey(global.CURRENT_SESSION_DID || global.userDid || "");

        // Distance 0: self or parent anchor
        if ((myPubkey && clean === myPubkey) || (myDid && clean === myDid) || (parentDid && clean === parentDid)) {
            return 0;
        }

        // Explicit parent-whitelisted contacts
        var approved = (ctx.approved_contacts || []).map(normalizeKey);
        if (approved.indexOf(clean) !== -1) {
            return 1;
        }

        // Trust Lens check (Level0 / Level0_5 / Level1 = distance 1)
        var tl = global.TrustLens || global.trustLens;
        if (tl && typeof tl.getTrustTier === "function") {
            var tier = tl.getTrustTier(clean);
            if (tier === "Level0" || tier === "Level0_5" || tier === "Level1") {
                return 1;
            } else if (tier === "Level2") {
                return 2;
            }
        }

        // Contact Manager check (Kind 3 direct follow = distance 1)
        var cm = global.ContactManager || global.contactManager;
        if (cm) {
            if (typeof cm.isFollowing === "function" && cm.isFollowing(clean)) {
                return 1;
            }
            if (typeof cm.isMutualFriend === "function" && cm.isMutualFriend(clean)) {
                return 2;
            }
        }

        // Default: sender outside trust perimeter
        return Infinity;
    }

    /**
     * Intercept an inbound message or handshake.
     * Returns true if allowed, false if dropped/rejected silently.
     */
    function interceptInboundMessage(sender, isHandshake) {
        var ctx = getContext();
        if (!ctx.is_dependent) {
            return true;
        }

        var limit = typeof ctx.wot_distance_limit === "number" ? ctx.wot_distance_limit : Infinity;
        if (ctx.bracket === "U14" && (limit === null || isNaN(limit))) limit = 1;
        if (ctx.bracket === "U14-U18" && (limit === null || isNaN(limit))) limit = 2;
        if (ctx.bracket === "U18" && (limit === null || isNaN(limit))) limit = 3;

        var distance = getSenderWoTDistance(sender);

        if (distance <= limit) {
            return true;
        }

        // Outside WoT perimeter: drop silently without alerting minor
        if (isHandshake) {
            console.debug("[WoTGate] Rejected inbound chat handshake from outside trust perimeter:", sender);
        } else {
            console.debug("[WoTGate] Silently dropped inbound message from outside trust perimeter:", sender);
        }
        return false;
    }

    function interceptInboundNostr(event) {
        if (!event || event.kind !== 4) return true;
        var sender = event.pubkey;
        return interceptInboundMessage(sender, false);
    }

    function interceptInboundXMPP(from, isHandshake) {
        return interceptInboundMessage(from, !!isHandshake);
    }

    var wotGate = {
        getContext: getContext,
        getSenderWoTDistance: getSenderWoTDistance,
        interceptInboundMessage: interceptInboundMessage,
        interceptInboundNostr: interceptInboundNostr,
        interceptInboundXMPP: interceptInboundXMPP,
        canAcceptChatHandshake: function (sender) {
            return interceptInboundMessage(sender, true);
        }
    };

    global.wotGate = wotGate;
    global.WoTGate = wotGate;

    if (typeof module !== "undefined" && module.exports) {
        module.exports = wotGate;
    }
})(typeof window !== "undefined" ? window : globalThis);
