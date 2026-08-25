/**
 * link_deck_manager.js — Sovereign Link Deck Manager (Dashboard tab controller)
 * Handle claiming, headline editing, item CRUD + drag-free reordering.
 * Depends on bridge_client.js globals: escapeHtml, showToast, getCookie.
 */
(function () {
    "use strict";

    var deckItems = [];
    var deckInfo = {
        handle: null,
        display_handle: null,
        canonical_url: null,
        is_verified: false,
        verified_source_url: "",
    };
    var activeChallenge = null;

    function deckCsrf() {
        var cookieToken = (typeof getCookie === "function") ? getCookie("wun_csrftoken") : "";
        if (cookieToken) return cookieToken;
        var input = document.querySelector("[name=csrfmiddlewaretoken]");
        return input ? input.value : "";
    }

    function deckFetch(url, options) {
        options = options || {};
        options.headers = Object.assign({
            "Content-Type": "application/json",
            "X-CSRFToken": deckCsrf(),
        }, options.headers || {});
        return fetch(url, options).then(function (r) {
            return r.json().then(function (data) {
                if (!r.ok) throw new Error(data.error || ("Request failed (" + r.status + ")"));
                return data;
            });
        });
    }

    function showDeckStatus(message, isError) {
        var el = document.getElementById("deckStatus");
        if (!el) return;
        el.textContent = message;
        el.className = "text-xs " + (isError ? "text-red-500" : "text-green-600");
        el.classList.remove("hidden");
        setTimeout(function () { el.classList.add("hidden"); }, 3000);
    }

    function absoluteDeckUrl(path) {
        if (!path) return "";
        return window.location.origin + path;
    }

    function renderHandleBanner() {
        var displayEl = document.getElementById("deckHandleDisplay");
        var urlEl = document.getElementById("deckCanonicalUrl");
        var inputEl = document.getElementById("deckHandleInput");
        if (!displayEl || !urlEl) return;
        if (deckInfo.handle) {
            displayEl.textContent = deckInfo.display_handle || ("@" + deckInfo.handle);
            urlEl.textContent = absoluteDeckUrl(deckInfo.canonical_url);
            if (inputEl) inputEl.value = deckInfo.handle;
        } else {
            displayEl.textContent = "Unclaimed";
            urlEl.textContent = "—";
        }
    }

    function renderVerifyCard() {
        var badgeEl = document.getElementById("deckVerifyBadge");
        var promptEl = document.getElementById("deckVerifyPrompt");
        if (!badgeEl || !promptEl) return;
        if (deckInfo.handle && deckInfo.is_verified) {
            badgeEl.classList.remove("hidden");
            promptEl.classList.add("hidden");
            var sourceEl = document.getElementById("deckVerifySource");
            if (sourceEl) {
                sourceEl.href = deckInfo.verified_source_url || "#";
                sourceEl.textContent = deckInfo.verified_source_url || "";
            }
        } else {
            badgeEl.classList.add("hidden");
            promptEl.classList.remove("hidden");
        }
    }

    function showVerifyStatus(message, isError) {
        var el = document.getElementById("verifyStatus");
        if (!el) return;
        el.textContent = message;
        el.className = "text-xs block " + (isError ? "text-red-500" : "text-green-600");
        el.classList.remove("hidden");
    }

    function renderDeckItems() {
        var list = document.getElementById("deckItemsList");
        if (!list) return;
        list.innerHTML = "";

        if (!deckInfo.handle) {
            list.innerHTML = '<p class="text-xs text-gray-400 border border-dashed border-gray-300 rounded-lg px-4 py-6 text-center">Claim a handle above to unlock your Link Deck.</p>';
            return;
        }
        if (deckItems.length === 0) {
            list.innerHTML = '<p class="text-xs text-gray-400 border border-dashed border-gray-300 rounded-lg px-4 py-6 text-center">No links yet. Add your first below.</p>';
            return;
        }

        deckItems.forEach(function (item, index) {
            var row = document.createElement("div");
            row.className = "flex items-center gap-2 bg-gray-50 border rounded-lg px-3 py-2" +
                (item.is_active ? " border-gray-200" : " border-dashed border-gray-300 opacity-60");

            var info = document.createElement("span");
            info.className = "flex items-center gap-2 min-w-0 flex-1";
            info.innerHTML =
                '<span class="w-7 h-7 flex-shrink-0 flex items-center justify-center rounded bg-white border border-gray-200 text-sm">' + escapeHtml(item.icon_emoji) + "</span>" +
                '<span class="min-w-0">' +
                '<span class="block text-sm font-medium text-gray-800 truncate">' + escapeHtml(item.title) + "</span>" +
                '<span class="block font-mono text-[11px] text-gray-400 truncate">' + escapeHtml(item.url) + "</span>" +
                "</span>" +
                (item.is_ecosystem_link ? '<span class="flex-shrink-0 text-[10px] uppercase font-mono bg-violet-100 text-violet-700 px-1.5 py-0.5 rounded-full">mesh</span>' : "") +
                '<span class="flex-shrink-0 text-[10px] uppercase font-mono ' +
                (item.is_active ? "bg-green-100 text-green-800" : "bg-gray-200 text-gray-500") +
                ' px-1.5 py-0.5 rounded-full">' + (item.is_active ? "on" : "off") + "</span>";
            row.appendChild(info);

            var controls = document.createElement("span");
            controls.className = "flex items-center gap-1 flex-shrink-0";

            function ctlButton(label, title, handler, extraClass) {
                var b = document.createElement("button");
                b.type = "button";
                b.textContent = label;
                b.title = title;
                b.className = "px-1.5 py-0.5 rounded text-xs font-medium transition-colors " + extraClass;
                b.onclick = handler;
                return b;
            }

            controls.appendChild(ctlButton("&uarr;", "Move up", function () { moveDeckItem(index, -1); }, "text-gray-600 hover:bg-gray-200 disabled:opacity-30"));
            controls.appendChild(ctlButton("&darr;", "Move down", function () { moveDeckItem(index, 1); }, "text-gray-600 hover:bg-gray-200 disabled:opacity-30"));
            controls.appendChild(ctlButton(item.is_active ? "Hide" : "Show", "Toggle visibility", function () { toggleDeckItem(item); }, "bg-gray-200 hover:bg-gray-300 text-gray-700"));
            controls.appendChild(ctlButton("Delete", "Delete link", function () { deleteDeckItem(item); }, "text-red-500 hover:text-red-700"));

            controls.querySelectorAll("button")[0].disabled = index === 0;
            controls.querySelectorAll("button")[1].disabled = index === deckItems.length - 1;
            row.appendChild(controls);
            list.appendChild(row);
        });
    }

    function applyDeckPayload(data) {
        deckInfo.handle = data.handle || null;
        deckInfo.display_handle = data.display_handle || null;
        deckInfo.canonical_url = data.canonical_url || null;
        deckInfo.is_verified = Boolean(data.is_verified);
        deckInfo.verified_source_url = data.verified_source_url || "";
        deckItems = data.items || [];
        var headlineEl = document.getElementById("deckHeadlineInput");
        if (headlineEl && typeof data.headline === "string") headlineEl.value = data.headline;
        renderHandleBanner();
        renderVerifyCard();
        renderDeckItems();
    }

    function refreshDeck() {
        return deckFetch("/api/deck/items").then(applyDeckPayload).catch(function () {});
    }

    function initDeckManager() {
        renderDeckItems();
        refreshDeck();
    }

    function claimDeckHandle(event) {
        event.preventDefault();
        var input = document.getElementById("deckHandleInput");
        var handle = (input && input.value || "").trim();
        if (!handle) { showDeckStatus("Enter a handle first.", true); return false; }
        var btn = document.getElementById("deckClaimBtn");
        btn.disabled = true;
        deckFetch("/api/deck/handle", { method: "POST", body: JSON.stringify({ handle: handle }) })
            .then(function () { return refreshDeck(); })
            .then(function () { showDeckStatus("Handle claimed."); })
            .catch(function (err) { showDeckStatus(err.message, true); })
            .finally(function () { btn.disabled = false; });
        return false;
    }

    function saveDeckHeadline() {
        var input = document.getElementById("deckHeadlineInput");
        var headline = (input && input.value || "").trim();
        deckFetch("/api/deck/handle", { method: "POST", body: JSON.stringify({ headline: headline }) })
            .then(function () { showDeckStatus("Headline saved."); })
            .catch(function (err) { showDeckStatus(err.message, true); });
    }

    function copyDeckUrl() {
        if (!deckInfo.canonical_url) { showToast("No claimed handle yet.", true); return; }
        var full = absoluteDeckUrl(deckInfo.canonical_url);
        if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(full).then(function () { showToast("Canonical URL copied."); });
        } else {
            showToast(full);
        }
    }

    function addDeckItem(event) {
        event.preventDefault();
        if (!deckInfo.handle) { showDeckStatus("Claim a handle first.", true); return false; }
        var titleEl = document.getElementById("deckItemTitle");
        var urlEl = document.getElementById("deckItemUrl");
        var iconEl = document.getElementById("deckItemIcon");
        var payload = {
            title: (titleEl.value || "").trim(),
            url: (urlEl.value || "").trim(),
            icon_category: iconEl ? iconEl.value : "link",
        };
        if (!payload.title || !payload.url) { showDeckStatus("Title and URL are required.", true); return false; }
        deckFetch("/api/deck/items", { method: "POST", body: JSON.stringify(payload) })
            .then(function () {
                titleEl.value = "";
                urlEl.value = "";
                return refreshDeck();
            })
            .then(function () { showDeckStatus("Link added."); })
            .catch(function (err) { showDeckStatus(err.message, true); });
        return false;
    }

    function toggleDeckItem(item) {
        deckFetch("/api/deck/items/" + item.id, { method: "PATCH", body: JSON.stringify({ is_active: !item.is_active }) })
            .then(function () { return refreshDeck(); })
            .then(function () { showDeckStatus(item.is_active ? "Link hidden." : "Link visible."); })
            .catch(function (err) { showDeckStatus(err.message, true); });
    }

    function deleteDeckItem(item) {
        deckFetch("/api/deck/items/" + item.id, { method: "DELETE" })
            .then(function () { return refreshDeck(); })
            .then(function () { showDeckStatus("Link deleted."); })
            .catch(function (err) { showDeckStatus(err.message, true); });
    }

    function moveDeckItem(index, direction) {
        var target = index + direction;
        if (target < 0 || target >= deckItems.length) return;
        var ids = deckItems.map(function (i) { return i.id; });
        var swapped = ids.slice();
        swapped[index] = ids[target];
        swapped[target] = ids[index];
        deckFetch("/api/deck/reorder", { method: "POST", body: JSON.stringify({ item_ids: swapped }) })
            .then(function () { return refreshDeck(); })
            .catch(function (err) { showDeckStatus(err.message, true); });
    }

    function openVerifyModal() {
        if (!deckInfo.handle) { showToast("Claim a handle first.", true); return; }
        var handleEl = document.getElementById("verifyTargetHandle");
        var urlEl = document.getElementById("verifyExternalUrl");
        var tokenBox = document.getElementById("verifyTokenBox");
        var confirmBtn = document.getElementById("confirmVerifyBtn");
        var statusEl = document.getElementById("verifyStatus");
        if (handleEl && !handleEl.value) handleEl.value = deckInfo.handle;
        if (urlEl) urlEl.value = "";
        if (tokenBox) tokenBox.classList.add("hidden");
        if (confirmBtn) confirmBtn.disabled = true;
        if (statusEl) statusEl.classList.add("hidden");
        activeChallenge = null;
        var modal = document.getElementById("verifyModal");
        modal.classList.remove("hidden");
        modal.classList.add("flex");
    }

    function closeVerifyModal() {
        var modal = document.getElementById("verifyModal");
        modal.classList.add("hidden");
        modal.classList.remove("flex");
    }

    function generateVerifyToken() {
        var handleEl = document.getElementById("verifyTargetHandle");
        var urlEl = document.getElementById("verifyExternalUrl");
        var btn = document.getElementById("generateTokenBtn");
        var payload = {
            target_handle: (handleEl && handleEl.value || "").trim(),
            external_url: (urlEl && urlEl.value || "").trim(),
        };
        btn.disabled = true;
        deckFetch("/api/deck/verify/challenge", { method: "POST", body: JSON.stringify(payload) })
            .then(function (data) {
                activeChallenge = data;
                var box = document.getElementById("verifyTokenBox");
                var valueEl = document.getElementById("verifyTokenValue");
                var expiryEl = document.getElementById("verifyTokenExpiry");
                if (valueEl) valueEl.textContent = data.token;
                if (expiryEl) expiryEl.textContent = "Expires " + new Date(data.expires_at).toLocaleString();
                if (box) box.classList.remove("hidden");
                var confirmBtn = document.getElementById("confirmVerifyBtn");
                if (confirmBtn) confirmBtn.disabled = false;
                showVerifyStatus("Token generated. Paste it into your bio, then Check & Claim Handle.");
            })
            .catch(function (err) {
                showVerifyStatus(err.message, true);
            })
            .finally(function () { btn.disabled = false; });
    }

    function copyVerifyToken() {
        if (!activeChallenge || !activeChallenge.token) return;
        if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(activeChallenge.token).then(function () { showToast("Verification token copied."); });
        } else {
            showToast(activeChallenge.token);
        }
    }

    function confirmVerification() {
        if (!activeChallenge || !activeChallenge.token) { showVerifyStatus("Generate a token first.", true); return; }
        var btn = document.getElementById("confirmVerifyBtn");
        var generateBtn = document.getElementById("generateTokenBtn");
        btn.disabled = true;
        if (generateBtn) generateBtn.disabled = true;
        deckFetch("/api/deck/verify/confirm", {
            method: "POST",
            body: JSON.stringify({ token: activeChallenge.token }),
        })
            .then(function () {
                showToast("Handle verified and promoted to canonical @handle!");
                setTimeout(function () { window.location.reload(); }, 900);
            })
            .catch(function (err) {
                showVerifyStatus(err.message, true);
                btn.disabled = false;
                if (generateBtn) generateBtn.disabled = false;
            });
    }

    window.initDeckManager = initDeckManager;
    window.claimDeckHandle = claimDeckHandle;
    window.saveDeckHeadline = saveDeckHeadline;
    window.copyDeckUrl = copyDeckUrl;
    window.addDeckItem = addDeckItem;
    window.toggleDeckItem = toggleDeckItem;
    window.deleteDeckItem = deleteDeckItem;
    window.moveDeckItem = moveDeckItem;
    window.openVerifyModal = openVerifyModal;
    window.closeVerifyModal = closeVerifyModal;
    window.generateVerifyToken = generateVerifyToken;
    window.copyVerifyToken = copyVerifyToken;
    window.confirmVerification = confirmVerification;
})();
