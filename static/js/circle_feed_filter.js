/**
 * circle_feed_filter.js — Two-Tier Layer 2 Circle Feed Filtering Engine
 *
 * Provides real-time client-side circle filtering and tag/text search for the
 * Omni-Social Feed in iyou_wun:
 * - Circle scopes:
 *   - global:    Global Mesh (all relay notes)
 *   - following: Following (L1 contacts via Kind 3)
 *   - inner:     Inner Circle (L0 / L0_5 via Contact Enclave / Trust Lens)
 *   - mutual:    Mutual Friends (bidirectional Kind 3 follows)
 * - Real-time tag and text search input (#feed-search-input)
 * - Empty state feedback when 0 notes match active circle/search
 * - Fast navigation & compose action (#btn-compose-note)
 */
(function (global) {
    "use strict";

    let activeCircle = "global";
    let activeSearchQuery = "";

    const CIRCLE_LABELS = {
        global: "GLOBAL MESH",
        following: "FOLLOWING (L1)",
        inner: "INNER CIRCLE (L0)",
        mutual: "MUTUAL FRIENDS"
    };

    const ACTIVE_TAB_CLASSES = [
        "bg-violet-600", "text-white", "font-bold",
        "dark:bg-violet-500", "dark:text-slate-950"
    ];

    const INACTIVE_TAB_CLASSES = [
        "text-slate-600", "dark:text-slate-400",
        "hover:text-slate-900", "dark:hover:text-slate-200",
        "bg-slate-200", "dark:bg-slate-800/60"
    ];

    function normalizeKey(raw) {
        if (!raw) return "";
        return String(raw).trim().toLowerCase();
    }

    function getFeedContainer() {
        return document.getElementById("feedContainer") || document.getElementById("feed-container");
    }

    function getNoteCards() {
        const container = getFeedContainer();
        if (!container) return [];

        // Select top-level note elements or items with note data
        const directChildren = Array.from(container.children).filter(
            el => el.id !== "circle-empty-state" && el.id !== "loadMoreSpinner" && el.id !== "loadMoreEnd"
        );

        if (directChildren.length > 0) {
            return directChildren;
        }

        return Array.from(document.querySelectorAll(".feed-note-card, .thread-root"));
    }

    function getCardNoteData(card) {
        let root = card;
        if (!root.getAttribute("data-pubkey") && !root.getAttribute("data-author-pubkey")) {
            const inner = card.querySelector(".feed-note-card, .thread-root, [data-pubkey], [data-author-pubkey]");
            if (inner) root = inner;
        }

        const pubkey = normalizeKey(
            root.getAttribute("data-author-pubkey") ||
            root.getAttribute("data-pubkey") ||
            ""
        );

        const did = normalizeKey(
            root.getAttribute("data-author-did") ||
            root.getAttribute("data-did") ||
            (pubkey ? "did:iyou:0x" + pubkey : "")
        );

        const tagsRaw = root.getAttribute("data-note-tags") || "";
        const textContent = (card.textContent || "").toLowerCase();

        return { root, pubkey, did, tagsRaw, textContent };
    }

    function isAuthorMatchingUser(pubkey, did) {
        const currentPubkey = normalizeKey(
            global.userPubkey ||
            (global.activeProfile && global.activeProfile.nostr_pubkey_hex) ||
            ""
        );
        const currentDid = normalizeKey(global.userDid || "");

        if (currentPubkey && pubkey && currentPubkey === pubkey) return true;
        if (currentDid && did && currentDid === did) return true;
        return false;
    }

    function checkCircleMatch(circleMode, pubkey, did, card) {
        if (circleMode === "global") {
            return true;
        }

        if (isAuthorMatchingUser(pubkey, did)) {
            return true;
        }

        if (circleMode === "following") {
            const cm = global.ContactManager || global.contactManager;
            if (cm && typeof cm.isFollowing === "function") {
                return cm.isFollowing(pubkey);
            }
            return false;
        }

        if (circleMode === "inner") {
            const tl = global.TrustLens || global.trustLens;
            let tier = null;
            if (tl && typeof tl.getTrustTier === "function") {
                tier = tl.getTrustTier(did) || tl.getTrustTier(pubkey);
            }

            if (tier === "Level0" || tier === "Level0_5") {
                return true;
            }

            // Inspect DOM for rendered trust badges
            const badge = card.querySelector(".trust-badge");
            if (badge) {
                const text = badge.textContent || "";
                if (text.includes("Level0") || text.includes("Level0_5")) return true;
                if (badge.classList.contains("border-violet-500") || badge.classList.contains("border-emerald-500")) {
                    return true;
                }
            }

            return false;
        }

        if (circleMode === "mutual") {
            const cm = global.ContactManager || global.contactManager;
            if (cm && typeof cm.isMutualFriend === "function") {
                return cm.isMutualFriend(pubkey);
            }
            return false;
        }

        return true;
    }

    function checkSearchMatch(query, cardData) {
        if (!query) return true;
        const q = query.toLowerCase().trim();
        const tagClean = q.replace(/^#+/, "");

        if (cardData.textContent.includes(q)) return true;
        if (cardData.pubkey.includes(q)) return true;
        if (cardData.did.includes(q)) return true;

        if (cardData.tagsRaw) {
            try {
                const tags = JSON.parse(cardData.tagsRaw);
                if (Array.isArray(tags)) {
                    const hasTag = tags.some(t => {
                        if (!Array.isArray(t)) return false;
                        if (t[0] === "t" && t[1] && t[1].toLowerCase().includes(tagClean)) return true;
                        return t.some(val => String(val).toLowerCase().includes(q));
                    });
                    if (hasTag) return true;
                }
            } catch (e) {
                if (cardData.tagsRaw.toLowerCase().includes(q)) return true;
            }
        }

        return false;
    }

    function ensureEmptyStateElement(container) {
        let el = document.getElementById("circle-empty-state");
        if (!el) {
            el = document.createElement("div");
            el.id = "circle-empty-state";
            el.className = "text-center py-12 px-6 text-slate-500 dark:text-slate-400 font-mono text-xs border border-dashed border-slate-300 dark:border-slate-800 rounded-lg my-6";
            container.appendChild(el);
        }
        return el;
    }

    function applyFilters() {
        const container = getFeedContainer();
        if (!container) return;

        const cards = getNoteCards();
        let visibleCount = 0;

        cards.forEach((card) => {
            if (card.id === "circle-empty-state") return;
            const data = getCardNoteData(card);

            const matchCircle = checkCircleMatch(activeCircle, data.pubkey, data.did, card);
            const matchSearch = checkSearchMatch(activeSearchQuery, data);

            if (matchCircle && matchSearch) {
                card.style.display = "";
                card.classList.remove("hidden");
                visibleCount++;
            } else {
                card.style.display = "none";
                card.classList.add("hidden");
            }
        });

        // Handle empty state banner
        const emptyState = ensureEmptyStateElement(container);
        if (visibleCount === 0 && cards.length > 0) {
            emptyState.style.display = "";
            emptyState.classList.remove("hidden");
            if (activeSearchQuery) {
                emptyState.innerHTML = '<p class="text-sm font-semibold text-slate-700 dark:text-slate-300 mb-1">No notes match the active filter and search query.</p>' +
                    '<p class="text-xs text-slate-500">Try refining your search keyword or switching circle scope.</p>';
            } else if (activeCircle === "following") {
                emptyState.innerHTML = '<p class="text-sm font-semibold text-slate-700 dark:text-slate-300 mb-1">No notes in Following Circle.</p>' +
                    '<p class="text-xs text-slate-500">Follow more creators on the feed or link deck to populate your network.</p>';
            } else if (activeCircle === "inner") {
                emptyState.innerHTML = '<p class="text-sm font-semibold text-slate-700 dark:text-slate-300 mb-1">No notes from Inner Circle (Level 0 / 0.5).</p>' +
                    '<p class="text-xs text-slate-500">Add trusted peer aliases in the iyou_home Contact Enclave.</p>';
            } else if (activeCircle === "mutual") {
                emptyState.innerHTML = '<p class="text-sm font-semibold text-slate-700 dark:text-slate-300 mb-1">No notes from Mutual Friends (Level 1 Peers).</p>' +
                    '<p class="text-xs text-slate-500">Mutual friends are peers who follow you back on the decentralized mesh.</p>';
            } else {
                emptyState.innerHTML = '<p class="text-sm font-semibold text-slate-700 dark:text-slate-300 mb-1">No notes in this circle.</p>' +
                    '<p class="text-xs text-slate-500">Follow more creators or add contacts in the Enclave.</p>';
            }
        } else {
            emptyState.style.display = "none";
            emptyState.classList.add("hidden");
        }
    }

    function setCircle(circleMode) {
        activeCircle = circleMode || "global";

        // Update tabs UI
        const tabGroup = document.getElementById("circle-filter-group");
        if (tabGroup) {
            const tabs = tabGroup.querySelectorAll(".circle-tab");
            tabs.forEach((tab) => {
                const targetCircle = tab.getAttribute("data-circle");
                if (targetCircle === activeCircle) {
                    INACTIVE_TAB_CLASSES.forEach(cls => tab.classList.remove(cls));
                    ACTIVE_TAB_CLASSES.forEach(cls => tab.classList.add(cls));
                } else {
                    ACTIVE_TAB_CLASSES.forEach(cls => tab.classList.remove(cls));
                    INACTIVE_TAB_CLASSES.forEach(cls => tab.classList.add(cls));
                }
            });
        }

        // Update scope badge label
        const scopeLabel = document.getElementById("active-circle-label");
        if (scopeLabel) {
            scopeLabel.textContent = CIRCLE_LABELS[activeCircle] || activeCircle.toUpperCase();
        }

        // Update URL search params gracefully on feed
        if (window.location.pathname.startsWith("/feed")) {
            const url = new URL(window.location.href);
            if (activeCircle === "global") {
                url.searchParams.delete("circle");
            } else {
                url.searchParams.set("circle", activeCircle);
            }
            window.history.replaceState({}, "", url.toString());
        }

        applyFilters();
    }

    function setSearchQuery(query) {
        activeSearchQuery = (query || "").trim();
        applyFilters();
    }

    function initCircleFeedFilter() {
        // 1. Check URL parameters
        const urlParams = new URLSearchParams(window.location.search);
        const urlCircle = urlParams.get("circle");
        const urlQuery = urlParams.get("q");

        if (urlCircle && CIRCLE_LABELS[urlCircle]) {
            activeCircle = urlCircle;
        }
        if (urlQuery) {
            activeSearchQuery = urlQuery;
            const searchInput = document.getElementById("feed-search-input");
            if (searchInput) searchInput.value = urlQuery;
        }

        // 2. Bind circle tabs
        const tabGroup = document.getElementById("circle-filter-group");
        if (tabGroup) {
            const tabs = tabGroup.querySelectorAll(".circle-tab");
            tabs.forEach((tab) => {
                tab.addEventListener("click", function (e) {
                    e.preventDefault();
                    const targetCircle = this.getAttribute("data-circle");
                    if (!window.location.pathname.startsWith("/feed") && window.location.pathname !== "/") {
                        window.location.href = "/feed?circle=" + encodeURIComponent(targetCircle);
                        return;
                    }
                    setCircle(targetCircle);
                });
            });
        }

        // 3. Bind search input
        const searchInput = document.getElementById("feed-search-input");
        if (searchInput) {
            let debounceTimer = null;
            searchInput.addEventListener("input", function () {
                const val = this.value;
                if (!window.location.pathname.startsWith("/feed") && window.location.pathname !== "/") {
                    if (debounceTimer) clearTimeout(debounceTimer);
                    debounceTimer = setTimeout(() => {
                        window.location.href = "/feed?q=" + encodeURIComponent(val);
                    }, 400);
                    return;
                }
                setSearchQuery(val);
            });
        }

        // 4. Bind compose note button
        const composeBtn = document.getElementById("btn-compose-note");
        if (composeBtn) {
            composeBtn.addEventListener("click", function (e) {
                e.preventDefault();
                const postContent = document.getElementById("postContent");
                if (postContent) {
                    postContent.scrollIntoView({ behavior: "smooth", block: "center" });
                    postContent.focus();
                } else {
                    window.location.href = "/feed#compose";
                }
            });
        }

        // 5. Initial filter application
        setCircle(activeCircle);

        // 6. Reactive listeners for trust lens & contacts updates
        window.addEventListener("trustLensUpdated", function () {
            applyFilters();
        });

        window.addEventListener("contactsUpdated", function () {
            applyFilters();
        });
    }

    // Public API
    const circleFeedFilter = {
        init: initCircleFeedFilter,
        setCircle: setCircle,
        setSearchQuery: setSearchQuery,
        applyFilters: applyFilters,
        getActiveCircle: () => activeCircle
    };

    global.circleFeedFilter = circleFeedFilter;
    global.applyCircleFilter = setCircle;

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", initCircleFeedFilter);
    } else {
        initCircleFeedFilter();
    }

    if (typeof module !== "undefined" && module.exports) {
        module.exports = circleFeedFilter;
    }

})(typeof window !== "undefined" ? window : globalThis);
