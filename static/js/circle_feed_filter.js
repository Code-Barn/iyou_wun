/**
 * circle_feed_filter.js — Two-Tier Layer 2 Circle Filtering Engine
 *
 * Provides real-time client-side circle filtering and tag/text search for both
 * the Omni-Social Feed and Media Gallery in iyou_wun:
 * - Circle scopes:
 *   - global:    Global Mesh (all relay notes / media)
 *   - following: Following (L1 contacts via Kind 3)
 *   - inner:     Inner Circle (L0 / L0_5 via Contact Enclave / Trust Lens)
 *   - mutual:    Mutual Friends (bidirectional Kind 3 follows)
 * - Real-time tag and text search input (#feed-search-input)
 * - Category count badge synchronization (#tab-count-all, #tab-count-images, etc.)
 * - Empty state feedback when 0 items match active circle/search
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

    function getGalleryCards() {
        return Array.from(document.querySelectorAll(".gallery-media-card, .gallery-card"));
    }

    function getCardNoteData(card) {
        let root = card;
        if (!root.getAttribute("data-pubkey") && !root.getAttribute("data-author-pubkey")) {
            const inner = card.querySelector(".feed-note-card, .thread-root, .gallery-media-card, .gallery-card, [data-pubkey], [data-author-pubkey]");
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
            ""
        );

        const tagsRaw = root.getAttribute("data-tags") || root.getAttribute("data-note-tags") || "";
        const mediaType = (root.getAttribute("data-media-type") || root.getAttribute("data-type") || "").toLowerCase();
        const mimeType = (root.getAttribute("data-mime") || "").toLowerCase();
        const altText = (root.getAttribute("data-alt") || "").toLowerCase();
        const author = (root.getAttribute("data-author") || "").toLowerCase();
        const textContent = (card.textContent || "").toLowerCase() + " " + altText + " " + mimeType + " " + author;

        return { root, pubkey, did, tagsRaw, mediaType, mimeType, altText, author, textContent };
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
        if (cardData.mediaType && cardData.mediaType.includes(q)) return true;
        if (cardData.mimeType && cardData.mimeType.includes(q)) return true;
        if (cardData.altText && cardData.altText.includes(q)) return true;
        if (cardData.author && cardData.author.includes(q)) return true;

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

    function getSafetyPreferences() {
        var nsfwPref = "blur";
        var langPref = "all";
        try {
            nsfwPref = localStorage.getItem("wun_nsfw_pref") || "blur";
            langPref = localStorage.getItem("wun_lang_pref") || "all";
        } catch (e) {}
        return { nsfwPref: nsfwPref, langPref: langPref };
    }

    function checkSafetyAndHygieneMatch(card, data) {
        var prefs = getSafetyPreferences();
        var nsfwPref = prefs.nsfwPref;
        var langPref = prefs.langPref;

        // 1. NSFW / Content Warning Hide check
        var hasCw = card.getAttribute("data-has-content-warning") === "true" ||
                    (data && data.root && data.root.getAttribute("data-has-content-warning") === "true") ||
                    !!card.querySelector(".content-warning-shield");
        if (nsfwPref === "hide" && hasCw) {
            return false;
        }

        // 2. Language Filter
        var cardLang = (card.getAttribute("data-lang") || (data && data.root ? data.root.getAttribute("data-lang") : "") || "").toLowerCase();
        if (langPref === "en" && cardLang && cardLang !== "en") {
            return false;
        }

        return true;
    }

    function applyNsfwBlurState(pref) {
        var nsfwPref = pref || (getSafetyPreferences().nsfwPref);
        var shields = document.querySelectorAll(".content-warning-shield");
        shields.forEach(function (shield) {
            var blurEl = shield.querySelector(".blur-me");
            var btn = shield.querySelector(".content-warning-reveal");
            if (nsfwPref === "show") {
                if (blurEl) {
                    blurEl.classList.remove("backdrop-blur-md", "blur-sm", "select-none", "pointer-events-none");
                }
                if (btn) {
                    btn.classList.add("hidden");
                }
            } else if (nsfwPref === "blur") {
                if (blurEl && !shield.classList.contains("user-revealed")) {
                    blurEl.classList.add("backdrop-blur-md", "blur-sm", "select-none", "pointer-events-none");
                }
                if (btn && !shield.classList.contains("user-revealed")) {
                    btn.classList.remove("hidden");
                }
            }
        });
    }

    function updateNsfwShieldStatusUI(pref) {
        var statusEl = document.getElementById("nsfw-filter-status");
        if (!statusEl) return;
        var nsfwPref = pref || (getSafetyPreferences().nsfwPref);
        statusEl.textContent = nsfwPref.toUpperCase();
        if (nsfwPref === "show") {
            statusEl.className = "text-emerald-600 dark:text-emerald-400 font-bold";
        } else if (nsfwPref === "hide") {
            statusEl.className = "text-rose-600 dark:text-rose-400 font-bold";
        } else {
            statusEl.className = "text-violet-600 dark:text-violet-400 font-bold";
        }
    }

    function toggleNsfwFilter() {
        var currentPref = getSafetyPreferences().nsfwPref;
        var nextPref = (currentPref === "blur") ? "show" : (currentPref === "show" ? "hide" : "blur");
        try {
            localStorage.setItem("wun_nsfw_pref", nextPref);
        } catch (e) {}

        updateNsfwShieldStatusUI(nextPref);
        applyNsfwBlurState(nextPref);
        applyFeedFilters();

        if (typeof showToast === "function") {
            showToast("Shield set to " + nextPref.toUpperCase(), "info");
        }
    }

    function applyFeedFilters() {
        const container = getFeedContainer();
        if (!container) return;

        const cards = getNoteCards();
        let visibleCount = 0;

        cards.forEach((card) => {
            if (card.id === "circle-empty-state") return;
            const data = getCardNoteData(card);

            const matchCircle = checkCircleMatch(activeCircle, data.pubkey, data.did, card);
            const matchSearch = checkSearchMatch(activeSearchQuery, data);
            const matchSafety = checkSafetyAndHygieneMatch(card, data);

            if (matchCircle && matchSearch && matchSafety) {
                card.style.display = "";
                card.classList.remove("hidden");
                visibleCount++;
            } else {
                card.style.display = "none";
                card.classList.add("hidden");
            }
        });

        applyNsfwBlurState();

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

    function applyGalleryFilters() {
        const galleryCards = getGalleryCards();
        if (galleryCards.length === 0) return;

        let visibleAllCount = 0;
        let visibleImagesCount = 0;
        let visibleVideosCount = 0;
        let visibleAudioCount = 0;

        galleryCards.forEach((card) => {
            const data = getCardNoteData(card);
            const matchCircle = checkCircleMatch(activeCircle, data.pubkey, data.did, card);
            const matchSearch = checkSearchMatch(activeSearchQuery, data);

            const isVisible = matchCircle && matchSearch;
            if (isVisible) {
                card.style.display = "";
                card.classList.remove("hidden");
            } else {
                card.style.display = "none";
                card.classList.add("hidden");
            }

            // Count per container / category
            const parentGrid = card.closest("#allGrid, #imageGrid, #videoGrid, #audioGrid");
            const gridId = parentGrid ? parentGrid.id : "";

            if (gridId === "allGrid" && isVisible) visibleAllCount++;
            if (gridId === "imageGrid" && isVisible) visibleImagesCount++;
            if (gridId === "videoGrid" && isVisible) visibleVideosCount++;
            if (gridId === "audioGrid" && isVisible) visibleAudioCount++;
        });

        // Update Tab Count Badges in #tabRibbon
        const countAllEl = document.getElementById("tab-count-all");
        if (countAllEl) countAllEl.textContent = String(visibleAllCount);

        const countImagesEl = document.getElementById("tab-count-images") || document.getElementById("tab-count-visuals");
        if (countImagesEl) countImagesEl.textContent = String(visibleImagesCount);

        const countVideosEl = document.getElementById("tab-count-videos");
        if (countVideosEl) countVideosEl.textContent = String(visibleVideosCount);

        const countAudioEl = document.getElementById("tab-count-audio");
        if (countAudioEl) countAudioEl.textContent = String(visibleAudioCount);

        // Toggle Category Empty States
        const emptyAll = document.getElementById("empty-all");
        const allGrid = document.getElementById("allGrid");
        if (emptyAll && allGrid) {
            if (visibleAllCount === 0 && allGrid.children.length > 0) {
                emptyAll.classList.remove("hidden");
            } else {
                emptyAll.classList.add("hidden");
            }
        }

        const emptyImages = document.getElementById("empty-images");
        const imageGrid = document.getElementById("imageGrid");
        if (emptyImages && imageGrid) {
            if (visibleImagesCount === 0 && imageGrid.children.length > 0) {
                emptyImages.classList.remove("hidden");
            } else {
                emptyImages.classList.add("hidden");
            }
        }

        const emptyVideos = document.getElementById("empty-videos");
        const videoGrid = document.getElementById("videoGrid");
        if (emptyVideos && videoGrid) {
            if (visibleVideosCount === 0 && videoGrid.children.length > 0) {
                emptyVideos.classList.remove("hidden");
            } else {
                emptyVideos.classList.add("hidden");
            }
        }

        const emptyAudio = document.getElementById("empty-audio");
        const audioGrid = document.getElementById("audioGrid");
        if (emptyAudio && audioGrid) {
            if (visibleAudioCount === 0 && audioGrid.children.length > 0) {
                emptyAudio.classList.remove("hidden");
            } else {
                emptyAudio.classList.add("hidden");
            }
        }
    }

    function applyFilters() {
        applyFeedFilters();
        applyGalleryFilters();
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

        // Update URL search params gracefully on feed and gallery
        if (window.location.pathname.startsWith("/feed") || window.location.pathname.startsWith("/gallery")) {
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

        if (window.location.pathname.startsWith("/feed") || window.location.pathname.startsWith("/gallery")) {
            const url = new URL(window.location.href);
            if (!activeSearchQuery) {
                url.searchParams.delete("q");
            } else {
                url.searchParams.set("q", activeSearchQuery);
            }
            window.history.replaceState({}, "", url.toString());
        }

        applyFilters();
    }

    function isFeedOrGalleryPage() {
        const path = window.location.pathname;
        return path.startsWith("/feed") || path.startsWith("/gallery") || path === "/";
    }

    function escapeHtml(str) {
        if (!str) return "";
        return String(str)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");
    }

    let searchDebounceTimer = null;
    let currentSearchAbortController = null;

    function showDropdown() {
        const dropdown = document.getElementById("search-results-dropdown");
        if (dropdown) dropdown.classList.remove("hidden");
    }

    function hideDropdown() {
        const dropdown = document.getElementById("search-results-dropdown");
        if (dropdown) dropdown.classList.add("hidden");
    }

    function renderSearchResults(data) {
        const content = document.getElementById("search-dropdown-content");
        if (!content) return;

        content.innerHTML = "";
        const profiles = (data && data.results && data.results.profiles) || [];
        const tags = (data && data.results && data.results.tags) || [];

        if (profiles.length === 0 && tags.length === 0) {
            hideDropdown();
            return;
        }

        // 1. Profiles Section
        if (profiles.length > 0) {
            const profHeader = document.createElement("div");
            profHeader.className = "px-3 py-1.5 text-[10px] uppercase font-bold tracking-wider text-slate-400 dark:text-slate-500 bg-slate-50/80 dark:bg-slate-950/60 flex items-center justify-between";
            profHeader.innerHTML = `<span>👤 Profiles (${profiles.length})</span>`;
            content.appendChild(profHeader);

            const profList = document.createElement("div");
            profList.className = "py-1";
            profiles.forEach((p) => {
                const item = document.createElement("a");
                item.href = p.url || `/@${p.handle}`;
                item.className = "flex items-center gap-2.5 px-3 py-2 hover:bg-violet-50 dark:hover:bg-slate-800/80 transition-colors";
                
                const initialChar = escapeHtml((p.display_name || p.handle || '?')[0].toUpperCase());
                const avatarHtml = p.avatar_url
                    ? `<img src="${escapeHtml(p.avatar_url)}" alt="" class="w-7 h-7 rounded-full object-cover border border-slate-200 dark:border-slate-700 shrink-0">`
                    : `<div class="w-7 h-7 rounded-full bg-violet-100 dark:bg-violet-950 text-violet-600 dark:text-violet-400 font-bold flex items-center justify-center text-[10px] shrink-0">${initialChar}</div>`;

                const verifiedBadge = p.is_verified
                    ? `<span class="text-[9px] font-semibold text-emerald-600 dark:text-emerald-400 bg-emerald-100 dark:bg-emerald-950/80 px-1 rounded border border-emerald-300 dark:border-emerald-700 shrink-0">✓</span>`
                    : "";

                const handleText = p.handle ? `@${escapeHtml(p.handle)}` : "";
                const displayNameText = escapeHtml(p.display_name || p.handle || "");

                item.innerHTML = `
                    ${avatarHtml}
                    <div class="flex-1 min-w-0">
                        <div class="flex items-center gap-1.5 truncate">
                            <span class="font-semibold text-slate-800 dark:text-slate-200 text-xs truncate">${displayNameText}</span>
                            ${verifiedBadge}
                        </div>
                        <div class="text-[11px] text-slate-400 dark:text-slate-500 truncate">${handleText}</div>
                    </div>
                    <span class="text-[11px] text-slate-400 shrink-0">↗</span>
                `;
                profList.appendChild(item);
            });
            content.appendChild(profList);
        }

        // 2. Tags Section
        if (tags.length > 0) {
            const tagHeader = document.createElement("div");
            tagHeader.className = "px-3 py-1.5 text-[10px] uppercase font-bold tracking-wider text-slate-400 dark:text-slate-500 bg-slate-50/80 dark:bg-slate-950/60 flex items-center justify-between";
            tagHeader.innerHTML = `<span>🏷️ Hashtags (${tags.length})</span>`;
            content.appendChild(tagHeader);

            const tagList = document.createElement("div");
            tagList.className = "py-1";
            tags.forEach((t) => {
                const item = document.createElement("a");
                item.href = t.url || `/feed?q=${encodeURIComponent(t.display_tag || '#' + t.tag)}`;
                item.className = "flex items-center justify-between px-3 py-1.5 hover:bg-violet-50 dark:hover:bg-slate-800/80 transition-colors text-violet-600 dark:text-violet-400 font-semibold";
                item.innerHTML = `
                    <span class="truncate">${escapeHtml(t.display_tag || '#' + t.tag)}</span>
                    <span class="text-[10px] text-slate-400 font-normal">Filter Feed →</span>
                `;
                item.addEventListener("click", function (e) {
                    if (isFeedOrGalleryPage()) {
                        e.preventDefault();
                        const searchInput = document.getElementById("feed-search-input");
                        const rawTag = t.display_tag || '#' + t.tag;
                        if (searchInput) searchInput.value = rawTag;
                        setSearchQuery(rawTag);
                        hideDropdown();
                    }
                });
                tagList.appendChild(item);
            });
            content.appendChild(tagList);
        }

        showDropdown();
    }

    function performSearchEscalation(query) {
        const q = (query || "").trim();
        if (q.length < 2) {
            hideDropdown();
            return;
        }

        if (currentSearchAbortController) {
            try { currentSearchAbortController.abort(); } catch (e) {}
        }
        if (typeof AbortController !== "undefined") {
            currentSearchAbortController = new AbortController();
        }

        const signal = currentSearchAbortController ? currentSearchAbortController.signal : undefined;
        fetch(`/api/search/?q=${encodeURIComponent(q)}&circle=${encodeURIComponent(activeCircle)}&limit=6`, {
            signal: signal
        })
        .then(res => {
            if (!res.ok) throw new Error("Search request failed");
            return res.json();
        })
        .then(data => {
            if (data && data.success) {
                renderSearchResults(data);
            }
        })
        .catch(err => {
            if (err && err.name !== "AbortError") {
                console.debug("Search API error:", err);
            }
        });
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
                    if (!isFeedOrGalleryPage()) {
                        window.location.href = "/feed?circle=" + encodeURIComponent(targetCircle);
                        return;
                    }
                    setCircle(targetCircle);
                });
            });
        }

        // 3. Bind search input & progressive dropdown
        const searchInput = document.getElementById("feed-search-input");
        if (searchInput) {
            searchInput.addEventListener("input", function () {
                const val = this.value;
                if (isFeedOrGalleryPage()) {
                    setSearchQuery(val);
                }

                if (searchDebounceTimer) clearTimeout(searchDebounceTimer);
                searchDebounceTimer = setTimeout(() => {
                    if (val.trim().length >= 2) {
                        performSearchEscalation(val);
                    } else {
                        hideDropdown();
                    }
                }, 250);
            });

            searchInput.addEventListener("keydown", function (e) {
                if (e.key === "Escape") {
                    hideDropdown();
                } else if (e.key === "Enter") {
                    const val = this.value.trim();
                    hideDropdown();
                    if (!isFeedOrGalleryPage() && val) {
                        window.location.href = "/feed?q=" + encodeURIComponent(val);
                    }
                }
            });

            searchInput.addEventListener("focus", function () {
                const val = this.value.trim();
                if (val.length >= 2) {
                    performSearchEscalation(val);
                }
            });

            document.addEventListener("click", function (e) {
                const dropdown = document.getElementById("search-results-dropdown");
                if (dropdown && !dropdown.contains(e.target) && e.target !== searchInput) {
                    hideDropdown();
                }
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

        // 5. Initial filter application & shield state
        setCircle(activeCircle);
        updateNsfwShieldStatusUI();
        applyNsfwBlurState();

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
        toggleNsfwFilter: toggleNsfwFilter,
        updateNsfwShieldStatusUI: updateNsfwShieldStatusUI,
        applyNsfwBlurState: applyNsfwBlurState,
        getActiveCircle: () => activeCircle
    };

    global.circleFeedFilter = circleFeedFilter;
    global.applyCircleFilter = setCircle;
    global.toggleNsfwFilter = toggleNsfwFilter;

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", initCircleFeedFilter);
    } else {
        initCircleFeedFilter();
    }

    if (typeof module !== "undefined" && module.exports) {
        module.exports = circleFeedFilter;
    }

})(typeof window !== "undefined" ? window : globalThis);

