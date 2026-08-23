/**
 * trust_lens.js — Project Zero Trust Lens Controller
 * Resolves note author pubkeys against the local iyou_home Contact Enclave
 * bridge (RESOLVE_PEER_ALIASES) and renders local-only trust badges on the
 * feed. Purely client-memory: never persisted, never mutates relay events.
 *
 * Depends on: bridge_client.js (window.bridgeClient / window.tauriBridge)
 */
(function () {
    "use strict";

    var BADGE_CONFIG = {
        Level0: {
            classes: "border-violet-500 dark:border-violet-400 bg-violet-50 dark:bg-violet-950/40 text-violet-800 dark:text-violet-200",
            prefix: "\uD83D\uDEE1\uFE0F "
        },
        Level0_5: {
            classes: "border-emerald-500 dark:border-emerald-400 bg-emerald-50 dark:bg-emerald-950/40 text-emerald-800 dark:text-emerald-200",
            prefix: "\uD83D\uDEE1\uFE0F "
        },
        Level1: {
            classes: "border-slate-400 dark:border-slate-500 bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300",
            prefix: ""
        }
    };

    function normalizeKey(raw) {
        var key = String(raw == null ? "" : raw).trim();
        if (!key) return "";
        if (/^[0-9a-fA-F]{64}$/.test(key)) return key.toLowerCase();
        return key;
    }

    function getBridge() {
        if (window.tauriBridge && typeof window.tauriBridge.resolvePeerAliases === "function") {
            return window.tauriBridge;
        }
        if (window.bridgeClient && typeof window.bridgeClient.resolvePeerAliases === "function") {
            return window.bridgeClient;
        }
        return null;
    }

    function collectBadgeSlots(rootElement) {
        var root = rootElement || document;
        var cards = root.querySelectorAll("[data-pubkey]");
        var slotsByKey = {};

        cards.forEach(function (card) {
            var key = normalizeKey(card.getAttribute("data-pubkey"));
            if (!key) return;
            var slot = card.querySelector(".author-badge-slot");
            if (!slot || slot.getAttribute("data-trust-applied")) return;
            if (!slotsByKey[key]) slotsByKey[key] = [];
            slotsByKey[key].push(slot);
        });

        return slotsByKey;
    }

    function renderBadge(slot, match) {
        var config = BADGE_CONFIG[match.trust_level];
        if (!config) return;
        var label = match.badge || match.trust_level;
        var nickname = String(match.nickname || "");

        var badge = document.createElement("span");
        badge.className = "trust-badge inline-flex items-center gap-1 text-xs font-medium px-2 py-0.5 rounded-full border " + config.classes;
        badge.setAttribute("title", "Known locally as " + nickname + " (" + label + ")");
        badge.textContent = config.prefix + "[" + label + ": " + nickname + "]";

        slot.textContent = "";
        slot.appendChild(badge);
        slot.setAttribute("data-trust-applied", "1");
    }

    function resetAppliedBadges(rootElement) {
        var root = rootElement || document;
        root.querySelectorAll("[data-trust-applied]").forEach(function (slot) {
            slot.removeAttribute("data-trust-applied");
            slot.textContent = "";
        });
    }

    function scanFeedForTrustBadges(rootElement) {
        var bridge = getBridge();
        if (!bridge) return;

        var slotsByKey = collectBadgeSlots(rootElement);
        var keys = Object.keys(slotsByKey);
        if (keys.length === 0) return;

        bridge.resolvePeerAliases(keys).then(function (matches) {
            if (!matches) return;
            keys.forEach(function (key) {
                var match = matches[key];
                if (!match || !match.nickname) return;
                slotsByKey[key].forEach(function (slot) {
                    renderBadge(slot, match);
                });
            });
        }).catch(function () {
            /* Trust Lens is best-effort local enrichment; stay silent. */
        });
    }

    window.trustLens = {
        scan: scanFeedForTrustBadges,
        reset: resetAppliedBadges,
        renderBadge: renderBadge,
        BADGE_CONFIG: BADGE_CONFIG
    };
})();
