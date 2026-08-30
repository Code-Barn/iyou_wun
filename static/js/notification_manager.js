/**
 * Layer 1 Notification Bell, Slide-Out Activity Drawer, and client-side
 * notification ingestion engine.
 *
 * - Subscribes to the relay pool for `{"#p": [viewer_pubkey], "kinds": [1, 6, 7, 9735], "limit": 40}`
 * - Renders structured activity cards (avatar, name, relative time, icon, preview)
 * - Tracks read state in localStorage via `last_read_notification_timestamp`
 * - Controls the pulsating unread dot on the header bell
 * - Powers the slide-out drawer (backdrop click + Escape dismissal)
 * - Powers the filter tabs on the /notifications ledger page
 */

(function (global) {
    "use strict";

    var STORAGE_KEY = "last_read_notification_timestamp";
    var DOT_ID = "notification-unread-dot";
    var DRAWER_ID = "notification-drawer";
    var BACKDROP_ID = "notification-drawer-backdrop";
    var LIST_ID = "notification-items-list";
    var LEDGER_ID = "notification-ledger";

    var KIND_ICONS = { 1: "💬", 6: "🔁", 7: "❤️", 9735: "⚡" };
    var KIND_CATEGORY = { 1: "mentions", 6: "reposts", 7: "reactions", 9735: "zaps" };
    var DEFAULT_RELAYS = [
        "wss://relay.iyou.me",
        "wss://nos.lol",
        "wss://relay.damus.io",
        "wss://relay.primal.net",
        "ws://127.0.0.1:9003"
    ];
    var TAB_BASE_CLASS = "notification-tab flex items-center gap-1 whitespace-nowrap px-2.5 py-1 rounded-full text-xs font-mono border transition ";
    var TAB_ACTIVE_CLASS = "active text-violet-600 dark:text-violet-400 bg-violet-50 dark:bg-violet-950/40 border-violet-200 dark:border-violet-800/60";
    var TAB_INACTIVE_CLASS = "text-slate-500 hover:text-violet-600 dark:text-slate-400 dark:hover:text-violet-400 border-slate-200 dark:border-slate-800";
    var VALID_FILTERS = { all: true, mentions: true, reposts: true, reactions: true, zaps: true };

    function escapeHtml(value) {
        return String(value == null ? "" : value)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;");
    }

    function relativeTime(ts) {
        if (!ts) return "";
        var diff = Math.floor(Date.now() / 1000) - ts;
        if (diff < 60) return "now";
        if (diff < 3600) return Math.floor(diff / 60) + "m";
        if (diff < 86400) return Math.floor(diff / 3600) + "h";
        if (diff < 604800) return Math.floor(diff / 86400) + "d";
        return new Date(ts * 1000).toLocaleDateString(undefined, { month: "short", day: "numeric" });
    }

    function NotificationManager() {
        this.pubkey = null;
        this.relays = [];
        this.items = [];
        this.profiles = {};
        this._profileFetched = {};
        this._seenIds = {};
        this._sockets = [];
        this.activeFilter = "all";
        this.lastRead = 0;
        this.drawerOpen = false;
        this._init();
    }

    NotificationManager.prototype._init = function () {
        var pk = global.userPubkey;
        if (pk && /^[0-9a-fA-F]{64}$/.test(pk)) {
            this.pubkey = pk.toLowerCase();
        }
        try {
            var stored = global.localStorage ? global.localStorage.getItem(STORAGE_KEY) : null;
            this.lastRead = parseFloat(stored) || 0;
        } catch (e) {
            this.lastRead = 0;
        }
        this.relays = this._relayList();
        this._seenIds = {};
        this._sockets = [];

        this._bindEscapeAndBackdrop();

        if (document.readyState === "loading") {
            document.addEventListener("DOMContentLoaded", this._bootstrap.bind(this));
        } else {
            this._bootstrap();
        }
    };

    NotificationManager.prototype._bootstrap = function () {
        this._refreshTabStates();
        this._initRelativeTimes();
        this._applyUnreadBadges();
        this._updateUnreadDot();
        if (this.pubkey && this.relays.length) {
            this.subscribe();
        }
    };

    NotificationManager.prototype._relayList = function () {
        if (global.relayPool && typeof global.relayPool.getReadRelays === "function") {
            var list = global.relayPool.getReadRelays();
            if (list && list.length) return list;
        }
        return DEFAULT_RELAYS.slice();
    };

    /**
     * Open a relay subscription for inbound `#p` activity targeting the viewer.
     */
    NotificationManager.prototype.subscribe = function () {
        var self = this;
        if (!this.pubkey) return;
        var subId = "notify_" + Math.random().toString(36).substring(2, 10);

        this.relays.forEach(function (url) {
            var ws;
            try {
                ws = new WebSocket(url);
            } catch (e) {
                return;
            }
            self._sockets.push(ws);

            ws.onopen = function () {
                try {
                    ws.send(JSON.stringify(["REQ", subId, {
                        "#p": [self.pubkey],
                        "kinds": [1, 6, 7, 9735],
                        "limit": 40
                    }]));
                } catch (e) { /* ignore */ }
            };

            ws.onmessage = function (ev) {
                var data;
                try {
                    data = JSON.parse(ev.data);
                } catch (e) {
                    return;
                }
                if (data[0] === "EVENT" && data[1] === subId && data[2]) {
                    self._ingestEvent(data[2]);
                } else if (data[0] === "EOSE" && data[1] === subId) {
                    try { ws.close(); } catch (e) { /* ignore */ }
                }
            };

            ws.onerror = function () {
                try { ws.close(); } catch (e) { /* ignore */ }
            };
        });
    };

    /**
     * Fetch a Kind 0 profile for an actor over the relay pool and re-render.
     */
    NotificationManager.prototype._fetchProfile = function (pubkey) {
        var self = this;
        if (this._profileFetched[pubkey]) return;
        this._profileFetched[pubkey] = true;
        var subId = "prof_" + Math.random().toString(36).substring(2, 10);

        this.relays.forEach(function (url) {
            var ws;
            try {
                ws = new WebSocket(url);
            } catch (e) {
                return;
            }
            ws.onopen = function () {
                try {
                    ws.send(JSON.stringify(["REQ", subId, { kinds: [0], authors: [pubkey], limit: 1 }]));
                } catch (e) { /* ignore */ }
            };
            ws.onmessage = function (ev) {
                var data;
                try {
                    data = JSON.parse(ev.data);
                } catch (e) {
                    return;
                }
                if (data[0] === "EVENT" && data[1] === subId && data[2]) {
                    var prof = {};
                    try {
                        prof = JSON.parse(data[2].content || "{}") || {};
                    } catch (e) {
                        prof = {};
                    }
                    self.profiles[pubkey] = prof;
                    self.renderDrawer();
                    self._initRelativeTimes();
                    try { ws.close(); } catch (e) { /* ignore */ }
                }
            };
            ws.onerror = function () {
                try { ws.close(); } catch (e) { /* ignore */ }
            };
        });
    };

    NotificationManager.prototype._ingestEvent = function (event) {
        var self = this;
        if (!event || !event.id) return;
        if (this._seenIds[event.id]) return;
        this._seenIds[event.id] = true;

        var category = KIND_CATEGORY[event.kind];
        if (!category) return;

        var pk = event.pubkey || "";
        var item = {
            id: event.id,
            kind: event.kind,
            category: category,
            icon: KIND_ICONS[event.kind] || "🔔",
            pubkey: pk,
            actor_name: this._actorName(pk),
            actor_avatar: this._actorAvatar(pk),
            target_id: this._targetId(event),
            thread_url: this._threadUrl(event),
            content: event.content || "",
            preview: this._preview(event),
            created_at: event.created_at || 0,
            is_self: pk === this.pubkey
        };

        this.items.push(item);
        this.items.sort(function (a, b) { return b.created_at - a.created_at; });

        if (pk && !this._profileFetched[pk]) {
            this._fetchProfile(pk);
        }

        this.renderDrawer();
        this._updateUnreadDot();
    };

    NotificationManager.prototype._targetId = function (event) {
        var tags = event.tags || [];
        for (var i = 0; i < tags.length; i++) {
            if (tags[i] && tags[i][0] === "e" && tags[i][1]) return tags[i][1];
        }
        return event.id || "";
    };

    NotificationManager.prototype._threadUrl = function (event) {
        return "/feed?thread=" + encodeURIComponent(this._targetId(event));
    };

    NotificationManager.prototype._tagValue = function (tags, name) {
        for (var i = 0; i < tags.length; i++) {
            if (tags[i] && tags[i][0] === name && tags[i][1]) return tags[i][1];
        }
        return "";
    };

    NotificationManager.prototype._preview = function (event) {
        var content = (event.content || "").trim();
        var kind = event.kind;
        var tags = event.tags || [];

        if (kind === 9735) {
            var comment = "";
            var parsed = null;
            try {
                parsed = JSON.parse(content);
            } catch (e) {
                parsed = content;
            }
            if (parsed && typeof parsed === "object") {
                comment = (parsed.content || "").trim() || (parsed.description || "").trim();
            } else if (typeof parsed === "string") {
                comment = parsed.trim();
            }
            var amount = this._tagValue(tags, "amount");
            var suffix = "";
            if (amount && !isNaN(parseFloat(amount))) {
                suffix = " · " + (parseFloat(amount) / 1000) + " sats";
            }
            if (comment) return "⚡ " + comment.slice(0, 120) + suffix;
            return "⚡ Zapped your note" + suffix;
        }

        if (kind === 7) {
            if (!content || content === "+" || content === "−" || content === "-" ||
                    content === "Like" || content === "like" || content === "❤️") {
                return "Liked your note";
            }
            return "Reacted " + content.slice(0, 8) + " to your note";
        }

        if (kind === 6) {
            var snapped = content.replace(/\n/g, " ").trim();
            if (snapped.length > 80) return "Reposted: " + snapped.slice(0, 80);
            return "Reposted your note";
        }

        var collapsed = content.replace(/\n/g, " ").trim();
        if (!collapsed) return "Mentioned you";
        return collapsed.slice(0, 140) + (collapsed.length > 140 ? "…" : "");
    };

    NotificationManager.prototype._actorName = function (pubkey) {
        var prof = this.profiles[pubkey];
        if (prof) return String(prof.display_name || prof.name || "").trim() || this._shortPubkey(pubkey);
        return this._shortPubkey(pubkey);
    };

    NotificationManager.prototype._actorAvatar = function (pubkey) {
        var prof = this.profiles[pubkey];
        return (prof && prof.picture) || "";
    };

    NotificationManager.prototype._shortPubkey = function (pubkey) {
        if (!pubkey) return "Anonymous";
        return pubkey.slice(0, 4) + "…" + pubkey.slice(-4);
    };

    NotificationManager.prototype._itemHtml = function (item) {
        var avatar = item.actor_avatar
            ? '<img src="' + escapeHtml(item.actor_avatar) + '" alt="" referrerpolicy="no-referrer" class="w-9 h-9 rounded-full object-cover bg-slate-100 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 shrink-0" />'
            : '<span class="w-9 h-9 rounded-full bg-slate-100 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 flex items-center justify-center text-sm shrink-0">' + item.icon + '</span>';

        var unread = item.created_at > this.lastRead;

        return '<a href="' + escapeHtml(item.thread_url) + '" ' +
            'class="notification-item notification-board-item relative flex items-start gap-3 p-3 rounded-xl border border-slate-200 dark:border-slate-800 hover:border-violet-500/60 hover:shadow-md transition' +
            (unread ? ' notification-item-unread' : '') + '" ' +
            'data-notify-category="' + item.category + '" data-notify-ts="' + item.created_at + '" data-notify-id="' + escapeHtml(item.id) + '">' +
            (unread ? '<span class="absolute top-2 right-2 w-2 h-2 rounded-full bg-violet-500 animate-pulse"></span>' : '') +
            avatar +
            '<div class="min-w-0 flex-1">' +
                '<div class="flex items-center gap-1.5 flex-wrap">' +
                    '<span class="notification-actor text-xs font-semibold text-slate-800 dark:text-slate-200 truncate">' + escapeHtml(item.actor_name) + '</span>' +
                    '<span class="text-sm" title="' + item.category + '">' + item.icon + '</span>' +
                '</div>' +
                '<p class="notification-preview mt-0.5 text-xs text-slate-600 dark:text-slate-400 leading-relaxed break-words">' + escapeHtml(item.preview) + '</p>' +
                '<div class="mt-1 text-[10px] text-slate-400 font-mono">' +
                    '<span class="notification-time tabular-nums" data-ts="' + item.created_at + '">–</span>' +
                '</div>' +
            '</div>' +
        '</a>';
    };

    NotificationManager.prototype.renderDrawer = function () {
        var self = this;
        var listEl = document.getElementById(LIST_ID);
        if (!listEl) return;

        var filtered = this.items.filter(function (it) {
            return self.activeFilter === "all" || it.category === self.activeFilter;
        });

        if (!filtered.length) {
            listEl.innerHTML = '<div class="text-center text-slate-400 font-mono text-xs py-8">No ' +
                (self.activeFilter === "all" ? "" : self.activeFilter + " ") + 'activity yet.</div>';
            return;
        }

        var html = filtered.map(function (it) { return self._itemHtml(it); }).join("");
        listEl.innerHTML = html;
        this._initRelativeTimes();
    };

    NotificationManager.prototype._initRelativeTimes = function () {
        var els = document.querySelectorAll(".notification-time[data-ts]");
        for (var i = 0; i < els.length; i++) {
            var ts = parseFloat(els[i].getAttribute("data-ts") || "0");
            if (ts) els[i].textContent = relativeTime(ts);
        }
    };

    NotificationManager.prototype._unreadItems = function () {
        var self = this;
        var read = this.lastRead;
        var fromClient = this.items.filter(function (it) {
            return (it.created_at || 0) > read;
        });
        if (fromClient.length > 0) return fromClient;
        var ledger = document.getElementById(LEDGER_ID);
        if (!ledger) return [];
        var out = [];
        var rows = ledger.querySelectorAll(".notification-item[data-notify-ts]");
        for (var i = 0; i < rows.length; i++) {
            var ts = parseFloat(rows[i].getAttribute("data-notify-ts") || "0");
            if (ts > read) out.push(rows[i]);
        }
        return out;
    };

    NotificationManager.prototype._updateUnreadDot = function () {
        var dot = document.getElementById(DOT_ID);
        if (!dot) return;
        if (this._unreadItems().length > 0) {
            dot.classList.remove("hidden");
        } else {
            dot.classList.add("hidden");
        }
    };

    /**
     * Apply unread emphasis to server-rendered ledger rows on /notifications.
     */
    NotificationManager.prototype._applyUnreadBadges = function () {
        var read = this.lastRead;
        var ledger = document.getElementById(LEDGER_ID);
        if (!ledger) return;
        var rows = ledger.querySelectorAll(".notification-item[data-notify-ts]");
        for (var i = 0; i < rows.length; i++) {
            var el = rows[i];
            var ts = parseFloat(el.getAttribute("data-notify-ts") || "0");
            var existing = el.querySelector(".notification-unread-badge");
            if (ts > read) {
                el.classList.add("notification-item-unread");
                if (!existing) {
                    var badge = document.createElement("span");
                    badge.className = "notification-unread-badge absolute top-2 right-2 w-2 h-2 rounded-full bg-violet-500 animate-pulse";
                    el.appendChild(badge);
                }
            } else {
                el.classList.remove("notification-item-unread");
                if (existing) existing.remove();
            }
        }
    };

    NotificationManager.prototype.openDrawer = function () {
        var drawer = document.getElementById(DRAWER_ID);
        if (!drawer) return;
        var backdrop = document.getElementById(BACKDROP_ID);
        drawer.classList.remove("translate-x-full");
        drawer.setAttribute("aria-hidden", "false");
        if (backdrop) backdrop.classList.remove("hidden");
        this.drawerOpen = true;
        this._updateUnreadDot();
        this.renderDrawer();
    };

    NotificationManager.prototype.closeDrawer = function () {
        var drawer = document.getElementById(DRAWER_ID);
        var backdrop = document.getElementById(BACKDROP_ID);
        if (drawer) {
            drawer.classList.add("translate-x-full");
            drawer.setAttribute("aria-hidden", "true");
        }
        if (backdrop) backdrop.classList.add("hidden");
        this.drawerOpen = false;
    };

    NotificationManager.prototype.toggleDrawer = function () {
        if (this.drawerOpen) this.closeDrawer();
        else this.openDrawer();
    };

    NotificationManager.prototype.markAllRead = function () {
        var newest = 0;
        this.items.forEach(function (it) {
            if ((it.created_at || 0) > newest) newest = it.created_at;
        });
        var ledgerRows = document.querySelectorAll("#" + LEDGER_ID + " [data-notify-ts]");
        for (var i = 0; i < ledgerRows.length; i++) {
            var ts = parseFloat(ledgerRows[i].getAttribute("data-notify-ts") || "0");
            if (ts > newest) newest = ts;
        }
        if (!newest) newest = Math.floor(Date.now() / 1000);
        this.lastRead = newest;
        try {
            global.localStorage.setItem(STORAGE_KEY, String(newest));
        } catch (e) { /* ignore */ }

        var dot = document.getElementById(DOT_ID);
        if (dot) dot.classList.add("hidden");
        this._applyUnreadBadges();
        this.renderDrawer();
    };

    NotificationManager.prototype._refreshTabStates = function () {
        var self = this;
        var tabs = document.querySelectorAll(".notification-tab");
        for (var i = 0; i < tabs.length; i++) {
            var on = tabs[i].getAttribute("data-notify-tab") === this.activeFilter;
            tabs[i].className = TAB_BASE_CLASS + (on ? TAB_ACTIVE_CLASS : TAB_INACTIVE_CLASS);
        }
    };

    NotificationManager.prototype.setFilter = function (filter, btnEl) {
        this.activeFilter = VALID_FILTERS[filter] ? filter : "all";
        this._refreshTabStates();
        this.renderDrawer();
        this._applyLedgerFilter();
    };

    NotificationManager.prototype._applyLedgerFilter = function () {
        var ledger = document.getElementById(LEDGER_ID);
        if (!ledger) return;
        var rows = ledger.querySelectorAll(".notification-item[data-notify-category]");
        for (var i = 0; i < rows.length; i++) {
            var cat = rows[i].getAttribute("data-notify-category");
            rows[i].style.display = (this.activeFilter === "all" || cat === this.activeFilter) ? "" : "none";
        }
    };

    NotificationManager.prototype._bindEscapeAndBackdrop = function () {
        var self = this;
        document.addEventListener("keydown", function (e) {
            if (e.key === "Escape" && self.drawerOpen) self.closeDrawer();
        });
        var backdrop = document.getElementById(BACKDROP_ID);
        if (backdrop && !backdrop._wunBound) {
            backdrop._wunBound = true;
            backdrop.addEventListener("click", function () { self.closeDrawer(); });
        }
    };

    // ---------- Singleton & Global API ----------

    var app = new NotificationManager();

    global.NotificationManager = NotificationManager;
    global.wunNotifications = app;
    global.toggleNotificationDrawer = function () { app.toggleDrawer(); };
    global.closeNotificationDrawer = function () { app.closeDrawer(); };
    global.markAllNotificationsRead = function () { app.markAllRead(); };
    global.setNotificationFilter = function (filter, btn) { app.setFilter(filter || "all", btn); };

})(typeof window !== "undefined" ? window : globalThis);