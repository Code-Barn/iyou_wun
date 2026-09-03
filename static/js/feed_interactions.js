/**
 * feed_interactions.js — Feed & Threading Controller
 * Handles post creation, NIP-10 threading, replies, polls, votes, media upload,
 * and all feed DOM rendering logic.
 *
 * Depends on: bridge_client.js (window.bridgeClient, window.escapeHtml, etc.)
 */
(function () {
    "use strict";

    // ---------- State ----------
    var pendingReply = null;
    var pendingVote = null;
    var pendingPoll = false;
    var pendingReaction = null;
    var pendingRepost = null;
    var pendingNomination = null;
    var pendingReport = null;
    var quotedTarget = null;
    var attachedMedia = null;

    window.pendingReply = null;

    // ---------- Renderability Check ----------

    function isRenderableNote(note) {
        if (!note) return false;
        var content = (note.content || "").trim();
        var tags = note.tags || [];

        // Suppress P2P mesh discovery tags and multiaddr beacons
        var p2pTags = ["miasma-peer", "p2p-beacon", "relay-ping", "node-discovery"];
        for (var i = 0; i < tags.length; i++) {
            var tag = tags[i];
            if (!Array.isArray(tag) || tag.length < 2) continue;
            if (tag[0] === "t" && p2pTags.indexOf(tag[1].toLowerCase()) !== -1) return false;
            if (["multiaddr", "peer_addr", "peer_id"].indexOf(tag[0]) !== -1) return false;
        }

        // If content is present, it is renderable
        if (content) return true;

        // If content is empty, check if media tags exist (NIP-94 / imeta / image URLs)
        for (var j = 0; j < tags.length; j++) {
            var t = tags[j];
            if (Array.isArray(t) && t.length >= 2 && ["imeta", "url", "image", "thumb"].indexOf(t[0]) !== -1) {
                return true;
            }
        }

        return false;
    }

    // ---------- Post (Kind 1) ----------

    async function postToNostr() {
        var content = document.getElementById("postContent");
        var text = content ? content.value.trim() : "";
        if (!text && !attachedMedia) {
            showToast("Please enter some content or attach media to post.", true);
            return;
        }
        var pk;
        try { pk = await bridgeClient.getEffectivePubkey(); }
        catch (e) { showToast(e.message, true); return; }
        setButtonLoading(true);
        bridgeClient.isProcessing = true;
        var tags = [];
        if (quotedTarget && quotedTarget.id) {
            tags.push(["q", quotedTarget.id, "wss://relay.iyou.me", quotedTarget.pubkey || ""]);
            if (quotedTarget.pubkey) tags.push(["p", quotedTarget.pubkey]);
        }
        if (attachedMedia && attachedMedia.url) {
            tags.push(["url", attachedMedia.url]);
            if (attachedMedia.hash) tags.push(["x", attachedMedia.hash]);
            if (attachedMedia.mimeType) tags.push(["m", attachedMedia.mimeType]);
            if (attachedMedia.size) tags.push(["size", String(attachedMedia.size)]);
        }
        var kind = (attachedMedia && !text) ? 1063 : 1;
        var event = {
            kind: kind,
            content: text,
            pubkey: pk,
            created_at: Math.floor(Date.now() / 1000),
            tags: tags,
        };
        bridgeClient.signEvent(event);
    }

    // ---------- Broadcast Callback ----------

    function handleSignedEvent(pendingEvent, signedEvent) {
        if (pendingReply) {
            var replyRootId = pendingReply.rootId;
            var replyBtn = document.getElementById("reply-btn-" + replyRootId);
            broadcastReplyToRelays(signedEvent, replyRootId);
            pendingReply = null;
            window.pendingReply = null;
            bridgeClient.pendingEvent = null;
            bridgeClient.isProcessing = false;
            if (replyBtn) { replyBtn.disabled = false; replyBtn.textContent = "Reply"; }
        } else if (pendingVote) {
            fetch("http://127.0.0.1:8002/api/nostr/ingest/", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(signedEvent)
            })
            .then(function (r) {
                var btn = pendingVote.btn;
                if (r.ok) {
                    btn.textContent = "Vote Cast";
                    btn.classList.remove("bg-amber-600", "hover:bg-amber-700");
                    btn.classList.add("bg-green-500", "cursor-default");
                    pendingVote.form.querySelectorAll("input").forEach(function (i) { i.disabled = true; });
                } else {
                    btn.textContent = "Error \u2014 try again";
                    btn.disabled = false;
                }
            })
            .catch(function () {
                pendingVote.btn.textContent = "Network Error";
                pendingVote.btn.disabled = false;
            });
            pendingVote = null;
            bridgeClient.pendingEvent = null;
            bridgeClient.isProcessing = false;
        } else if (pendingPoll) {
            fetch("http://127.0.0.1:8002/api/nostr/ingest/", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(signedEvent)
            })
            .then(function (r) {
                if (!r.ok) console.error("Direct poly ingestion failed, falling back to passive relay sync.");
            })
            .catch(function (err) { console.error("Network error during direct poly ingestion:", err); });
            bridgeClient.broadcastToRelays(pendingEvent);
            closePollModal();
            pendingPoll = false;
            bridgeClient.pendingEvent = null;
            bridgeClient.isProcessing = false;
        } else if (pendingReaction) {
            bridgeClient.broadcastToRelays(signedEvent, null, function (localOk, anyOk) {
                if (anyOk || localOk) {
                    showToast("Reaction published to mesh", "heart");
                } else {
                    showToast("Failed to broadcast reaction.", "error");
                }
            });
            pendingReaction = null;
            bridgeClient.pendingEvent = null;
            bridgeClient.isProcessing = false;
        } else if (pendingRepost) {
            bridgeClient.broadcastToRelays(signedEvent, null, function (localOk, anyOk) {
                if (anyOk || localOk) {
                    showToast("Note reposted to mesh relays", "repost");
                } else {
                    showToast("Failed to broadcast repost.", "error");
                }
            });
            pendingRepost = null;
            bridgeClient.pendingEvent = null;
            bridgeClient.isProcessing = false;
        } else if (pendingReport) {
            bridgeClient.broadcastToRelays(signedEvent, null, function (localOk, anyOk) {
                if (anyOk || localOk) {
                    showToast("Note reported and hidden from feed", "success");
                } else {
                    showToast("Failed to broadcast report.", "error");
                }
            });
            pendingReport = null;
            bridgeClient.pendingEvent = null;
            bridgeClient.isProcessing = false;
        } else if (pendingNomination) {
            fetch("http://127.0.0.1:8002/api/nostr/ingest/", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(signedEvent)
            }).catch(function () {});
            bridgeClient.broadcastToRelays(signedEvent, null, function () {
                showToast("🏆 Nominated for Post of the Day!");
            });
            pendingNomination = null;
            bridgeClient.pendingEvent = null;
            bridgeClient.isProcessing = false;
        } else {

            bridgeClient.broadcastToRelays(pendingEvent, null, function (localOk, anyOk) {
                if (anyOk) {
                    showToast("Sovereign Event Broadcasted Successfully.");
                    addNoteToFeed(pendingEvent);
                } else if (!localOk) {
                    showToast("Failed to broadcast to all relays. Event may not be visible.", true);
                }
                bridgeClient.resetPostState();
                var editor = document.getElementById("postContent");
                if (editor) editor.value = "";
                clearQuoteAttachment();
                clearMediaAttachment();
            });
        }
    }

    window.handleSignedEvent = handleSignedEvent;

    // ---------- Relay Pool Sync Helpers ----------

    function getActiveRelays() {
        // Try to get custom relays from localStorage first
        var customRelays = [];
        try {
            var stored = localStorage.getItem("wun_custom_relays");
            if (stored) {
                customRelays = JSON.parse(stored);
            }
        } catch (e) {
            console.debug("Could not read wun_custom_relays from localStorage:", e);
        }
        
        // If no custom relays or error, try window.relayPool
        if (!customRelays || customRelays.length === 0) {
            if (window.relayPool && typeof window.relayPool.getRelays === "function") {
                try {
                    var poolRelays = window.relayPool.getRelays();
                    if (poolRelays && poolRelays.length > 0) {
                        customRelays = poolRelays;
                    }
                } catch (e) {
                    console.debug("Could not get relays from window.relayPool:", e);
                }
            }
        }
        
        // Filter to only enabled/active relay URLs
        var enabledRelays = [];
        if (Array.isArray(customRelays)) {
            enabledRelays = customRelays.filter(function(relay) {
                // Handle objects with url/enabled properties or just strings
                if (typeof relay === "string") {
                    return relay.trim().length > 0 && (relay.startsWith("ws://") || relay.startsWith("wss://"));
                } else if (relay && typeof relay === "object") {
                    return relay.enabled !== false && relay.url && relay.url.trim().length > 0 && (relay.url.startsWith("ws://") || relay.url.startsWith("wss://"));
                }
                return false;
            }).map(function(relay) {
                return typeof relay === "string" ? relay.trim() : relay.url.trim();
            });
        }
        
        return enabledRelays.length > 0 ? enabledRelays : null;
    }

    // ---------- Button Loading State ----------

    function setButtonLoading(loading) {
        var button = document.getElementById("btn-publish-note") || document.getElementById("postButton");
        var textSpan = document.getElementById("postButtonText");
        var loadingSpan = document.getElementById("postButtonLoading");
        if (button) button.disabled = loading;
        if (textSpan) { loadingSpan && loading ? textSpan.classList.add("hidden") : textSpan.classList.remove("hidden"); }
        if (loadingSpan) { loading ? loadingSpan.classList.remove("hidden") : loadingSpan.classList.add("hidden"); }
    }

    // ---------- NIP-10 Threading: Reply Editor ----------

    function showReplyEditor(rootId) {
        var box = document.getElementById("reply-box-" + rootId) || document.getElementById("reply-editor-" + rootId);
        if (box) {
            box.classList.remove("hidden");
        }
        var textarea = document.getElementById("reply-input-" + rootId) || document.getElementById("reply-content-" + rootId);
        if (textarea) {
            textarea.focus();
        }
    }

    function cancelReply(rootId) {
        var box = document.getElementById("reply-box-" + rootId) || document.getElementById("reply-editor-" + rootId);
        if (box) {
            box.classList.add("hidden");
        }
        var textarea = document.getElementById("reply-input-" + rootId) || document.getElementById("reply-content-" + rootId);
        if (textarea) {
            textarea.value = "";
        }
        pendingReply = null;
        window.pendingReply = null;
    }

    async function submitReply(rootId, parentPubkey) {
        var textarea = document.getElementById("reply-input-" + rootId) || document.getElementById("reply-content-" + rootId);
        var btn = document.getElementById("reply-btn-" + rootId);
        if (!textarea || !textarea.value.trim()) return;

        var pk;
        try { pk = await bridgeClient.getEffectivePubkey(); }
        catch (e) { showToast(e.message, true); return; }

        var timestamp = Math.floor(Date.now() / 1000);
        var tags = [
            ["e", rootId, "", "root"],
            ["e", rootId, "", "reply"],
            ["p", parentPubkey || "", ""],
            ["p", pk, ""],
        ];

        var event = {
            kind: 1111,
            content: textarea.value.trim(),
            pubkey: pk,
            created_at: timestamp,
            tags: tags,
        };

        pendingReply = { rootId: rootId, parentPubkey: parentPubkey };
        window.pendingReply = pendingReply;
        if (btn) { btn.disabled = true; btn.textContent = "Signing..."; }
        bridgeClient.isProcessing = true;
        bridgeClient.signEvent(event);
    }


    function toggleReplies(rootId) {
        var repliesDiv = document.getElementById("replies-" + rootId);
        var btn = document.getElementById("toggle-replies-" + rootId);
        if (repliesDiv) {
            repliesDiv.classList.toggle("hidden");
            if (btn) {
                var isHidden = repliesDiv.classList.contains("hidden");
                btn.textContent = isHidden ? btn.textContent.replace("Hide", "Show") : btn.textContent.replace("Show", "Hide");
            }
        }
    }

    // ---------- Broadcast Reply ----------

    function broadcastReplyToRelays(signedEvent, rootId) {
        var remaining = getRelays().length;
        var localOk = false;
        var anyOk = false;

        function checkDone() {
            if (remaining > 0) return;
            if (anyOk || localOk) {
                showToast("Reply broadcasted to mesh", "success");
                appendReplyToThread(signedEvent, rootId);
            } else {
                showToast("Failed to broadcast reply.", "error");
            }
        }

        getRelays().forEach(function (relayUrl) {
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
                ws.onmessage = function (ev) {
                    try {
                        var msg = JSON.parse(ev.data);
                        if (msg[0] === "OK") {
                            if (isLocal) localOk = true;
                            else anyOk = true;
                        }
                    } catch (e) { /* ignore */ }
                    try { ws.close(); } catch (e) { /* ignore */ }
                    done();
                };
                ws.onerror = function () { done(); };
                ws.onclose = function () { done(); };
                setTimeout(function () { try { ws.close(); } catch (e) { /* ignore */ } done(); }, 3000);
            } catch (err) { done(); }
        });
    }

    // ---------- Append Reply to Thread DOM ----------

    function appendReplyToThread(event, rootId) {
        var repliesDiv = document.getElementById("replies-" + rootId);
        if (!repliesDiv) {
            repliesDiv = document.createElement("div");
            repliesDiv.className = "thread-replies ml-6 pl-4 border-l-2 border-indigo-200 space-y-4 mt-4";
            repliesDiv.id = "replies-" + rootId;
            repliesDiv.setAttribute("data-parent-id", rootId);
            var rootPost = document.querySelector('[data-note-id="' + rootId + '"]');
            if (rootPost && rootPost.nextElementSibling) {
                rootPost.parentNode.insertBefore(repliesDiv, rootPost.nextElementSibling);
            }
        }
        repliesDiv.classList.remove("hidden");

        var replyEl = document.createElement("div");
        replyEl.className = "thread-reply";
        replyEl.setAttribute("data-kind", "1111");
        replyEl.setAttribute("data-note-id", event.id);
        replyEl.setAttribute("data-pubkey", event.pubkey);
        replyEl.setAttribute("data-parent-id", rootId);

        var date = new Date(event.created_at * 1000);
        var formattedDate = date.toLocaleString();
        var npub = window.userNpub || (window.userPubkey ? window.userPubkey.substring(0, 12) + "..." : "You");
        var replyObj = {
            id: event.id,
            kind: event.kind || 1111,
            pubkey: event.pubkey,
            npub: npub,
            author_name: npub,
            content: event.content,
            created_at: event.created_at,
            parent_id: rootId,
            tags: event.tags || [],
            reply_count: 0
        };

        replyEl.innerHTML = buildCardHtml(replyObj);

        repliesDiv.appendChild(replyEl);
        var textarea = document.getElementById("reply-input-" + rootId) || document.getElementById("reply-content-" + rootId);
        if (textarea) textarea.value = "";
        cancelReply(rootId);
        if (window.trustLens && typeof window.trustLens.scan === "function") {
            window.trustLens.scan(repliesDiv);
        }
    }

    // ---------- Media Extraction & Unfurling ----------

    function extractMediaFromNote(note) {

        if (note.media_attachments && note.media_attachments.length) {
            return {
                attachments: note.media_attachments,
                displayContent: note.display_content !== undefined ? note.display_content : (note.content || "")
            };
        }

        var attachments = [];
        var content = note.content || "";
        var displayContent = content;

        // 1. Kind 1063 or explicit media tags
        if (note.kind === 1063 || note.media_url || note.file_url) {
            var url = note.media_url || note.file_url || "";
            if (!url && note.tags) {
                var urlTag = note.tags.find(function (t) { return t[0] === "url"; });
                if (urlTag && urlTag[1]) url = urlTag[1];
            }
            var mime = (note.mime_type || "").toLowerCase();
            if (!mime && note.tags) {
                var mTag = note.tags.find(function (t) { return t[0] === "m"; });
                if (mTag && mTag[1]) mime = mTag[1].toLowerCase();
            }
            var hashTag = "";
            if (note.tags) {
                var xTag = note.tags.find(function (t) { return t[0] === "x"; });
                if (xTag && xTag[1]) hashTag = String(xTag[1]).trim();
            }
            if (url) {
                var type = "file";
                if (mime.indexOf("image") !== -1 || /\.(png|jpg|jpeg|gif|webp|svg)(\?.*)?$/i.test(url)) {
                    type = "image";
                } else if (mime.indexOf("video") !== -1 || /\.(mp4|webm|mov|m4v)(\?.*)?$/i.test(url)) {
                    type = "video";
                } else if (mime.indexOf("audio") !== -1 || /\.(mp3|ogg|wav|m4a|flac)(\?.*)?$/i.test(url)) {
                    type = "audio";
                }
                var mediaEntry = { type: type, url: url };
                if (hashTag) mediaEntry.hash = hashTag;
                attachments.push(mediaEntry);
            }
        }

        // 2. Scan Kind 1 or general notes content for unfurled media URLs
        var urlRegex = /https?:\/\/[^\s<>\"]+/gi;
        var urlsFound = [];
        var match;
        while ((match = urlRegex.exec(content)) !== null) {
            var rawUrl = match[0].replace(/[.,;:!?)>\"']+$/, "");
            if (!rawUrl) continue;
            var uType = null;
            if (/\.(mp4|webm|mov|m4v)(\?.*)?$/i.test(rawUrl)) {
                uType = "video";
            } else if (/\.(mp3|ogg|wav|m4a|flac)(\?.*)?$/i.test(rawUrl)) {
                uType = "audio";
            } else if (/\.(png|jpg|jpeg|gif|webp|svg)(\?.*)?$/i.test(rawUrl) || /https?:\/\/(?:image\.nostr\.build|cdn\.iyou\.me|blossom\.[^\s<>\"]+)\/[^\s<>\"]+/i.test(rawUrl)) {
                uType = "image";
            }

            if (uType && !attachments.some(function (a) { return a.url === rawUrl; })) {
                attachments.push({ type: uType, url: rawUrl });
                urlsFound.push(match[0]);
            }
        }

        if (urlsFound.length > 0) {
            urlsFound.forEach(function (u) {
                displayContent = displayContent.replace(u, "").trim();
            });
        }

        return {
            attachments: attachments,
            displayContent: displayContent
        };
    }

    function formatLocalTimestamp(ts) {
        if (!ts) return '';
        var sec = Number(ts);
        var date;
        if (!isNaN(sec) && sec > 0) {
            if (sec > 1000000000000) {
                date = new Date(sec);
            } else {
                date = new Date(sec * 1000);
            }
        } else {
            date = new Date(ts);
        }
        if (isNaN(date.getTime())) return '';
        var now = new Date();
        var diffSec = Math.floor((now - date) / 1000);
        if (diffSec < 60 && diffSec >= 0) return 'just now';
        if (diffSec < 3600 && diffSec >= 60) return Math.floor(diffSec / 60) + 'm ago';
        if (diffSec < 86400 && diffSec >= 3600) return Math.floor(diffSec / 3600) + 'h ago';
        return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
    }

    function hydrateLocalTimestamps(root) {
        var context = root || document;
        var elements = context.querySelectorAll('.note-timestamp[data-timestamp]');
        elements.forEach(function (el) {
            var ts = el.getAttribute('data-timestamp') || (el.dataset && el.dataset.timestamp);
            if (ts) {
                var formatted = formatLocalTimestamp(ts);
                if (formatted) {
                    el.textContent = formatted;
                }
            }
        });
    }

    // ---------- Blossom Fallback Cascade ----------

    var MEDIA_FALLBACK_CASCADE = [
        function (sha) { return "http://127.0.0.1:9002/" + sha; },        // Local Loopback Daemon
        function (sha) { return "https://cdn.iyou.me/" + sha; },          // Sovereign CDN
        function (sha) { return "https://nostr.download/" + sha; }        // Public Fallback Blossom Node
    ];

    /**
     * `handleMediaError(imgEl, sha256)` — called via inline onerror on <img>
     * tags that carry a known SHA-256 content hash. Walks a fixed cascade of
     * mirror routes, swapping src up a tier each time the current mirror fails.
     * If every mirror fails, it renders a compact unavailable placeholder.
     *
     * Tier navigation is persisted on the element via `data-fallback-tier`.
     */
    window.handleMediaError = function (imgEl, sha256) {
        if (!imgEl || !sha256) return;
        var tier = parseInt(imgEl.getAttribute("data-fallback-tier") || "0", 10);
        if (isNaN(tier)) tier = 0;
        if (tier < MEDIA_FALLBACK_CASCADE.length) {
            var nextSrc = MEDIA_FALLBACK_CASCADE[tier](sha256);
            tier += 1;
            imgEl.setAttribute("data-fallback-tier", String(tier));
            if (imgEl.parentNode) {
                var wrap = document.createElement("div");
                wrap.className = "w-full h-full flex items-center justify-center bg-slate-100 dark:bg-slate-900 text-slate-500 dark:text-slate-400 font-mono text-xs";
                wrap.textContent = "⏳";
                imgEl.parentNode.replaceChild(wrap, imgEl);
                // Preserve the swap through the new placeholder container.
                var probe = new Image();
                probe.onload = function () {
                    try {
                        var host = imgEl.tagName.toLowerCase() === "image" ? imgEl : imgEl;
                        var img = document.createElement("img");
                        img.src = nextSrc;
                        img.alt = imgEl.getAttribute("alt") || "Attached visual";
                        img.loading = "lazy";
                        img.className = imgEl.className.includes("h-full w-full object-cover") ? "w-full h-full object-cover" : "w-full h-full object-contain max-h-[500px]";
                        img.onclick = imgEl.onclick;
                        img.onerror = function () { window.handleMediaError(img, sha256); };
                        wrap.replaceWith(img);
                    } catch (e) { /* ignore */ }
                };
                probe.onerror = function () {
                    try { wrap.textContent = ""; } catch (e) {}
                    // The probe failed, so we recorded the tier advance already;
                    // bail out entirely rather than churn.
                };
                probe.src = nextSrc;
            }
        } else {
            // All mirrors exhausted.
            var parent = imgEl.parentNode;
            if (parent) {
                var placeholder = document.createElement("div");
                placeholder.className = "w-full h-full flex items-center justify-center bg-slate-100 dark:bg-slate-900 text-slate-500 dark:text-slate-400 font-mono text-xs";
                placeholder.textContent = "[⚠️ Media Unavailable on Mesh]";
                parent.replaceChild(placeholder, imgEl);
            }
        }
    };

    // ---------- Template Builder for Cards ----------

    /**
     * Build an inline `onerror="handleMediaError(this, '<hash>')"` attribute
     * when a media attachment carries a NIP-94 `x` hash (or explicit sha256),
     * enabling the Blossom fallback cascade. Returns "" when no hash is known.
     */
    function mediaOnErrorAttr(media) {
        if (!media) return "";
        var sha = media.hash || media.sha256 || media.sha || "";
        sha = String(sha || "").trim();
        if (!sha) return "";
        // Only a 64-char hex digest can address mirrors reliably.
        if (!/^[a-fA-F0-9]{64}$/.test(sha)) return "";
        return ' onerror="window.handleMediaError(this, \'' + sha + '\')"';
    }

    /**
     * Phase 34 — Scoped Avatar Brand Protection.
     * External mesh peers with no verified avatar get the neutral slate globe
     * (mesh_avatar_default.svg); only iyou-native / sovereign peers fall back
     * to the protected iyou_symbol.png brand mark.
     */
    function resolveAvatarUrl(note) {
        if (note.author_avatar && note.author_avatar.trim()) return note.author_avatar;
        if (note.is_iyou_native || note.is_sovereign) return '/static/img/iyou_symbol.png';
        return '/static/img/mesh_avatar_default.svg';
    }

    function buildCardHtml(note) {
        if (!note) return "";
        if (!isRenderableNote(note)) {
            return '';
        }
        var noteId = note.id || "";
        var pubkey = note.pubkey || note.pubkey_hex || "";
        var npub = note.npub || (pubkey ? pubkey.substring(0, 12) + "..." : "You");
        var authorName = note.author_name || npub;
        var authorAvatar = note.author_avatar || "";
        var authorDid = note.author_did || "";
        var nip05 = note.nip05 || "";
        var noteContent = note.content != null ? String(note.content) : "";
        var parentId = note.parent_id || "";
        var replyToName = note.reply_to_name || "";
        var replyToNpub = note.reply_to_npub || "";

        var tsSec = note.created_at_epoch || (typeof note.created_at === 'number' ? note.created_at : (note.created_at_ts || Math.floor(Date.now() / 1000)));
        var date = new Date(Number(tsSec) * 1000);
        var formattedDate = formatLocalTimestamp(tsSec) || date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
        var reactionLikeCount = (note.like_count && note.like_count > 0) ? String(note.like_count) : ((note.reactions && note.reactions.length) ? String(note.reactions.length) : "");
        var repliesCount = (note.reply_count && note.reply_count > 0) ? String(note.reply_count) : "Reply";
        var repostCount = note.repost_count ? String(note.repost_count) : "Repost";

        var mediaInfo = extractMediaFromNote(note);
        var mediaAttachments = mediaInfo.attachments || [];
        var displayContent = note.display_content !== undefined ? (note.display_content != null ? String(note.display_content) : "") : (mediaInfo.displayContent != null ? String(mediaInfo.displayContent) : "");

        var mediaHtml = "";
        if (mediaAttachments && mediaAttachments.length > 0) {
            var imageAttachments = mediaAttachments.filter(function (m) { return m && m.type === "image"; });
            if (imageAttachments.length > 4) {
                mediaHtml = '<div class="mt-3 grid grid-cols-2 gap-1.5 rounded-xl overflow-hidden border border-slate-200 dark:border-slate-800 bg-slate-950/10">';
                imageAttachments.slice(0, 4).forEach(function (media, idx) {
                    if (!media || !media.url) return;
                    var mUrl = escapeAttr(media.url);
                    var onErr = mediaOnErrorAttr(media);
                    mediaHtml += '<div class="relative aspect-square overflow-hidden cursor-pointer">' +
                        '<img src="' + mUrl + '" alt="Attached visual" loading="lazy" class="w-full h-full object-cover hover:scale-[1.02] transition-transform duration-200" onclick="openImageModal(\'' + mUrl + '\')"' + onErr + ' />';
                    if (idx === 3) {
                        mediaHtml += '<div class="absolute inset-0 bg-black/60 flex items-center justify-center"><span class="text-white font-mono font-bold text-2xl">+' + (imageAttachments.length - 4) + '</span></div>';
                    }
                    mediaHtml += '</div>';
                });
                mediaHtml += '</div>';
            } else {
                mediaHtml = '<div class="mt-3 space-y-2">';
                mediaAttachments.forEach(function (media) {
                    if (!media || !media.url) return;
                    var mUrl = escapeAttr(media.url);
                    if (media.type === "image") {
                        var onErr = mediaOnErrorAttr(media);
                        mediaHtml += '<div class="rounded-xl overflow-hidden border border-slate-200 dark:border-slate-800 bg-slate-950/20 max-h-[500px]">' +
                            '<img src="' + mUrl + '" alt="Attached visual" loading="lazy" class="w-full h-full object-contain max-h-[500px] hover:scale-[1.01] transition-transform duration-200 cursor-pointer" onclick="openImageModal(\'' + mUrl + '\')"' + onErr + ' />' +
                            '</div>';
                    } else if (media.type === "video") {
                        mediaHtml += '<div class="rounded-xl overflow-hidden border border-slate-200 dark:border-slate-800 bg-black max-h-[500px]">' +
                            '<video src="' + mUrl + '" controls playsinline preload="metadata" class="w-full max-h-[500px]"></video>' +
                            '</div>';
                    } else if (media.type === "audio") {
                        mediaHtml += '<div class="p-3 rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-950/60 flex items-center gap-3">' +
                            '<span class="text-xl">🎵</span>' +
                            '<audio src="' + mUrl + '" controls class="w-full"></audio>' +
                            '</div>';
                    } else if (media.url) {
                        mediaHtml += '<div class="p-3 rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-950/60">' +
                            '<a href="' + mUrl + '" target="_blank" rel="noopener noreferrer" class="text-indigo-600 dark:text-violet-400 hover:underline break-all text-xs font-mono">📎 ' + escapeHtml(media.url) + '</a>' +
                            '</div>';
                    }
                });
                mediaHtml += '</div>';
            }
        }

        var isNativePeer = !!(note.is_iyou_native || note.is_sovereign);
        var avatarUrl = resolveAvatarUrl(note);
        var avatarClasses = isNativePeer
            ? "w-10 h-10 rounded-full object-cover border border-slate-200 dark:border-slate-700 bg-violet-950 p-1 hover:ring-2 hover:ring-violet-400 transition aspect-square"
            : "w-10 h-10 rounded-full object-cover border border-slate-200 dark:border-slate-700 bg-slate-800 p-1 hover:ring-2 hover:ring-violet-400 transition aspect-square";
        var avatarAlt = authorAvatar ? authorName : (isNativePeer ? "iyou Sovereign Peer" : "Mesh Peer");
        var avatarHtml = '<img src="' + escapeAttr(avatarUrl) + '" alt="' + escapeAttr(avatarAlt) + '" class="' + avatarClasses + '" />';

        var nip05Badge = nip05 ?
            '<span class="inline-flex items-center gap-1 text-[11px] font-mono text-violet-600 dark:text-violet-400 bg-violet-50 dark:bg-violet-950/40 px-1.5 py-0.5 rounded border border-violet-200 dark:border-violet-800/60" title="' + escapeAttr(nip05) + '"><svg class="w-3 h-3 text-violet-500" fill="currentColor" viewBox="0 0 20 20"><path fill-rule="evenodd" d="M6.267 3.455a3.066 3.066 0 001.745-.723 3.066 3.066 0 013.976 0 3.066 3.066 0 012.812 2.812c.051.643.304 1.254.723 1.745a3.066 3.066 0 010 3.976 3.066 3.066 0 01-.723 1.745 3.066 3.066 0 01-2.812 2.812 3.066 3.066 0 00-1.745.723 3.066 3.066 0 01-3.976 0 3.066 3.066 0 00-1.745-.723 3.066 3.066 0 01-2.812-2.812 3.066 3.066 0 00-.723-1.745 3.066 3.066 0 010-3.976 3.066 3.066 0 00.723-1.745 3.066 3.066 0 012.812-2.812zm7.44 5.252a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clip-rule="evenodd"></path></svg>' + escapeHtml(nip05) + '</span>' :
            (authorDid ? '<span class="font-mono text-[10px] text-slate-400 dark:text-slate-500 truncate max-w-[120px]" title="' + escapeAttr(authorDid) + '">' + escapeHtml(authorDid.substring(0, 14) + "...") + '</span>' :
            '<span class="font-mono text-[10px] text-slate-400 dark:text-slate-500" title="' + escapeAttr(npub) + '">' + escapeHtml(npub.substring(0, 12) + "...") + '</span>');

        var sovereignBadge = (note.kind === 1063 && note.is_sovereign) ?
            '<span class="bg-amber-100 text-amber-800 dark:bg-amber-950/60 dark:text-amber-300 text-[10px] font-mono px-1.5 py-0.2 rounded border border-amber-300 dark:border-amber-700">Sovereign</span>' : "";

        var snippetEscaped = escapeAttr(noteContent.substring(0, 100));

        var replyingToHtml = "";
        if (parentId) {
            var replyTarget = replyToName || replyToNpub || parentId;
            var replyLink = replyToNpub ? ('/profile/' + encodeURIComponent(replyToNpub) + '/') : ('/feed?thread=' + encodeURIComponent(parentId));
            var displayTarget = replyTarget.length > 14 ? (replyTarget.substring(0, 14) + "...") : replyTarget;
            replyingToHtml = '<div class="text-xs font-mono text-slate-400 dark:text-slate-500 mb-1 flex items-center gap-1"><span>↳ Replying to</span> <a href="' + replyLink + '" class="text-violet-600 dark:text-violet-400 hover:underline">@' + escapeHtml(displayTarget) + '</a></div>';
        }

        var clampedContent = function (text) {
            return '<div class="note-content-wrapper relative" data-clamped="false">' +
                '<div class="note-body-content text-sm sm:text-[15px] text-slate-800 dark:text-slate-100 font-normal leading-relaxed break-words max-h-60 overflow-hidden transition-all duration-300">' + text + '</div>' +
                '<button type="button" class="expand-note-btn hidden mt-1 text-xs font-mono text-violet-600 dark:text-violet-400 hover:underline font-semibold" onclick="toggleNoteClamp(this)">Show more ▾</button>' +
                '</div>';
        };

        var contentAndMediaHtml = (displayContent ? clampedContent(escapeHtml(displayContent)) : (noteContent && (!mediaAttachments || !mediaAttachments.length) ? clampedContent(escapeHtml(noteContent)) : ''));
        contentAndMediaHtml += mediaHtml;

        var ICON_REPLY = '<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" viewBox="0 0 24 24"><path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"></path></svg>';
        var ICON_REPOST = '<svg class="w-3.5 h-3.5 transition-transform duration-500 group-hover/repost:rotate-180" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" viewBox="0 0 24 24"><path d="m17 2 4 4-4 4"></path><path d="M3 11v-1a4 4 0 0 1 4-4h14"></path><path d="m7 22-4-4 4-4"></path><path d="M21 13v1a4 4 0 0 1-4 4H3"></path></svg>';
        var ICON_HEART = '<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" viewBox="0 0 24 24"><path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"></path></svg>';
        var ICON_VOTE = '<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" viewBox="0 0 24 24"><path d="m18 9-1-1-1-1h-8l-1 1-1 1v5a2 2 0 0 0 2 2h8a2 2 0 0 0 2-2V9z"></path><path d="M6 5V3h12v2"></path></svg>';
        var ICON_ZAP = '<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" viewBox="0 0 24 24"><path d="M13 2 3 14h9l-1 8 10-12h-9l1-8z"></path></svg>';
        var ICON_SHARE = '<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" viewBox="0 0 24 24"><path d="M4 12v8a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-8"></path><path d="m16 6-4-4-4 4"></path><path d="M12 2v13"></path></svg>';

        if (note.has_content_warning) {
            var nsfwPref = "blur";
            try { nsfwPref = localStorage.getItem("wun_nsfw_pref") || "blur"; } catch(e){}
            var isUnblurred = nsfwPref === "show";
            var cwReason = note.warning_reason || "Sensitive Content";
            contentAndMediaHtml = '<div class="content-warning-shield relative rounded-xl border border-amber-200 dark:border-amber-900/70 overflow-hidden mb-3">' +
                '<div class="blur-me ' + (isUnblurred ? '' : 'backdrop-blur-md blur-sm select-none pointer-events-none') + '">' + contentAndMediaHtml + '</div>' +
                '<button type="button" class="content-warning-reveal ' + (isUnblurred ? 'hidden' : '') + ' absolute inset-0 z-10 w-full h-full flex items-center justify-center" onclick="revealContentWarning(this)">' +
                '<span class="px-4 py-2 rounded-full bg-amber-100 dark:bg-amber-950/90 border border-amber-300 dark:border-amber-800/80 text-xs font-mono font-medium text-amber-800 dark:text-amber-300 shadow-lg">⚠️ ' + escapeHtml(cwReason) + ' — Click to View</span>' +
                '</button></div>';
        }

        var replyDrawerHtml = '<div id="reply-box-' + escapeAttr(noteId) + '" class="hidden mt-3 pt-3 border-t border-slate-100 dark:border-slate-800">' +
            '<div class="flex items-start gap-2.5">' +
            '<textarea id="reply-input-' + escapeAttr(noteId) + '" class="w-full bg-slate-50 dark:bg-slate-950 border border-slate-200 dark:border-slate-800 rounded-lg p-2.5 text-xs text-slate-800 dark:text-slate-100 placeholder-slate-400 focus:outline-none focus:border-violet-500 focus:ring-1 focus:ring-violet-500 transition resize-none overflow-x-hidden overflow-y-auto" rows="2" wrap="soft" placeholder="Write a sovereign reply..."></textarea>' +
            '<div class="flex flex-col gap-1.5 flex-shrink-0">' +
            '<button type="button" id="reply-btn-' + escapeAttr(noteId) + '" class="px-3 py-1.5 bg-violet-600 hover:bg-violet-500 text-white rounded text-xs font-mono font-medium transition" onclick="submitReply(\'' + escapeAttr(noteId) + '\', \'' + escapeAttr(pubkey) + '\')">Reply</button>' +
            '<button type="button" class="px-3 py-1 text-slate-500 hover:text-slate-700 dark:hover:text-slate-300 text-xs font-mono transition" onclick="cancelReply(\'' + escapeAttr(noteId) + '\')">Cancel</button>' +
            '</div></div></div>';

        var translateBtnHtml = (note.lang && note.lang !== 'en') ?
            '<button type="button" class="translate-btn text-[11px] font-mono text-slate-400 hover:text-violet-500 transition inline-flex items-center gap-1 mr-2" data-note-id="' + escapeAttr(noteId) + '" data-source-lang="' + escapeAttr(note.lang) + '" onclick="translateNote(\'' + escapeAttr(noteId) + '\', \'' + escapeAttr(note.lang) + '\', \'en\')"><span>🌐 Translate</span></button>' : '';

        var translatedBoxHtml = '<div id="translated-box-' + escapeAttr(noteId) + '" class="hidden mt-2 p-2.5 rounded-lg bg-violet-50/50 dark:bg-violet-950/30 border border-violet-200/60 dark:border-violet-800/40 text-sm sm:text-[15px] leading-relaxed">' +
            '<div class="text-[10px] font-mono text-violet-600 dark:text-violet-400 font-semibold mb-1 flex items-center justify-between">' +
            '<span id="trans-label-' + escapeAttr(noteId) + '">TRANSLATED</span>' +
            '<button type="button" class="hover:underline text-slate-500" onclick="toggleOriginalNote(\'' + escapeAttr(noteId) + '\')">View Original</button>' +
            '</div>' +
            '<div id="trans-text-' + escapeAttr(noteId) + '" class="text-slate-800 dark:text-slate-100"></div>' +
            '</div>';

        return '<div class="flex items-start gap-3.5 sm:gap-4 relative group" data-note-card-id="' + escapeAttr(noteId) + '" data-lang="' + escapeAttr(note.lang || 'en') + '">' +
            '<div class="flex-shrink-0"><a href="/profile/' + npub + '/">' + avatarHtml + '</a></div>' +
            '<div class="flex-1 min-w-0">' +
            '<div class="flex items-center justify-between gap-2 mb-1.5">' +
            '<div class="flex items-center gap-2 flex-wrap min-w-0">' +
            '<a href="/profile/' + npub + '/" class="font-semibold text-sm text-slate-900 dark:text-slate-100 hover:text-violet-600 dark:hover:text-violet-400 truncate">' + escapeHtml(authorName) + '</a>' +
            nip05Badge +
            '<span class="author-badge-slot" data-author-slot="' + escapeAttr(pubkey) + '"></span>' +
            sovereignBadge +
            '</div>' +
            '<div class="flex items-center gap-2">' +
            translateBtnHtml +
            '<a href="/feed?thread=' + encodeURIComponent(noteId) + '" class="text-xs text-slate-400 hover:text-violet-500 dark:hover:text-violet-400 font-mono whitespace-nowrap transition" title="View full conversation thread">' +
            '<time class="note-timestamp text-slate-400 dark:text-slate-500 hover:underline" data-timestamp="' + escapeAttr(String(tsSec)) + '" title="' + escapeAttr(date.toISOString()) + '">' +
            escapeHtml(formattedDate) +
            '</time>' +
            '</a>' +
            '<div class="relative kebab-menu-wrap">' +
            '<button type="button" class="kebab-toggle-btn text-slate-400 hover:text-slate-200 p-1 rounded hover:bg-slate-100 dark:hover:bg-slate-800 transition" aria-label="Post actions" onclick="toggleKebabMenu(event)">' +
            '<svg class="w-4 h-4" fill="currentColor" viewBox="0 0 20 20"><path d="M10 6a2 2 0 110-4 2 2 0 010 4zM10 12a2 2 0 110-4 2 2 0 010 4zM10 18a2 2 0 110-4 2 2 0 010 4z"></path></svg>' +
            '</button>' +
            '<div class="kebab-dropdown hidden absolute right-0 top-full mt-1 w-52 rounded-lg bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 shadow-2xl py-1 text-xs font-mono z-40">' +
            '<button type="button" class="w-full text-left px-3 py-2 text-slate-700 dark:text-slate-200 hover:bg-violet-50 dark:hover:bg-violet-950/50 hover:text-violet-600 dark:hover:text-violet-400 flex items-center gap-2" onclick="openDockedChat(\'' + escapeAttr(npub || pubkey) + '\', \'' + escapeAttr(authorName || '') + '\', \'' + escapeAttr(authorAvatar || '') + '\')">💬 Message</button>' +
            '<button type="button" class="w-full text-left px-3 py-2 text-slate-700 dark:text-slate-200 hover:bg-violet-50 dark:hover:bg-violet-950/50 hover:text-violet-600 dark:hover:text-violet-400 flex items-center gap-2" onclick="suggestToDev(\'' + escapeAttr(noteId) + '\', \'' + escapeAttr(pubkey) + '\', \'' + snippetEscaped + '\')">💡 Suggest to Dev</button>' +
            '<button type="button" class="w-full text-left px-3 py-2 text-slate-700 dark:text-slate-200 hover:bg-amber-50 dark:hover:bg-amber-950/50 hover:text-amber-600 dark:hover:text-amber-400 flex items-center gap-2" onclick="nominatePostOfTheDay(\'' + escapeAttr(noteId) + '\', \'' + escapeAttr(pubkey) + '\')">🏆 Post of the Day</button>' +
            '<button type="button" class="w-full text-left px-3 py-2 text-slate-700 dark:text-slate-200 hover:bg-emerald-50 dark:hover:bg-emerald-950/50 hover:text-emerald-600 dark:hover:text-emerald-400 flex items-center gap-2" onclick="setEnclavePetname(\'' + escapeAttr(pubkey) + '\', \'' + escapeAttr(authorName) + '\')">🛡️ Set Enclave Petname</button>' +
            '<div class="border-t border-slate-100 dark:border-slate-800 my-1"></div>' +
            '<button type="button" class="w-full text-left px-3 py-1.5 text-slate-500 hover:text-slate-800 dark:hover:text-slate-300 flex items-center gap-2" onclick="viewRawEventJson(\'' + escapeAttr(noteId) + '\')">📄 View Raw JSON</button>' +
            '<button type="button" class="w-full text-left px-3 py-1.5 text-slate-500 hover:text-slate-800 dark:hover:text-slate-300 flex items-center gap-2" onclick="copyNotePermalink(\'' + escapeAttr(noteId) + '\')">🔗 Copy Event ID / Link</button>' +
            '<div class="border-t border-slate-100 dark:border-slate-800 my-1"></div>' +
            '<button type="button" class="w-full text-left px-3 py-1.5 text-slate-600 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-800 flex items-center gap-2" onclick="hideNote(\'' + escapeAttr(noteId) + '\')">🙈 Hide this Note</button>' +
            '<button type="button" class="w-full text-left px-3 py-1.5 text-slate-600 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-800 flex items-center gap-2" onclick="muteAuthor(\'' + escapeAttr(pubkey) + '\', \'' + escapeAttr(authorName || npub || '') + '\')">🔇 Mute @' + escapeHtml((authorName || npub || '').slice(0, 12)) + '</button>' +
            '<button type="button" class="w-full text-left px-3 py-1.5 text-rose-600 dark:text-rose-400 hover:bg-rose-50 dark:hover:bg-rose-950/50 flex items-center gap-2" onclick="blockAuthor(\'' + escapeAttr(pubkey) + '\', \'' + escapeAttr(authorName || npub || '') + '\')">🚫 Block @' + escapeHtml((authorName || npub || '').slice(0, 12)) + '</button>' +
            '<div class="border-t border-slate-100 dark:border-slate-800 my-1"></div>' +
            '<button type="button" class="w-full text-left px-3 py-1.5 text-rose-600 dark:text-rose-400 hover:bg-rose-50 dark:hover:bg-rose-950/50 flex items-center gap-2" onclick="openReportModal(\'' + escapeAttr(noteId) + '\', \'' + escapeAttr(pubkey) + '\')">🚩 Report / Flag Note</button>' +
            '</div></div></div></div>' +
            replyingToHtml +
            contentAndMediaHtml +
            translatedBoxHtml +
            '<div class="flex items-center justify-between gap-1 sm:gap-4 mt-3 pt-2.5 border-t border-slate-100 dark:border-slate-800/80 text-xs font-mono text-slate-500 dark:text-slate-400 select-none">' +
            '<button type="button" class="action-btn-reply flex items-center gap-1.5 hover:text-violet-600 dark:hover:text-violet-400 transition-colors px-2 py-1 rounded hover:bg-slate-100 dark:hover:bg-slate-800/50" onclick="showReplyEditor(\'' + escapeAttr(noteId) + '\')"><span class="action-svg w-3.5 h-3.5 shrink-0">' + ICON_REPLY + '</span><span class="action-count reply-count-label">' + repliesCount + '</span></button>' +
            '<button type="button" class="action-btn-repost group/repost flex items-center gap-1.5 hover:text-emerald-600 dark:hover:text-emerald-400 transition-colors px-2 py-1 rounded hover:bg-slate-100 dark:hover:bg-slate-800/50" onclick="repostNote(\'' + escapeAttr(noteId) + '\', \'' + escapeAttr(pubkey) + '\')"><span class="action-svg w-3.5 h-3.5 shrink-0">' + ICON_REPOST + '</span><span class="action-count repost-count-label">' + repostCount + '</span></button>' +
            '<button type="button" class="action-btn-like flex items-center gap-1.5 hover:text-pink-600 dark:hover:text-pink-400 transition-colors px-2 py-1 rounded hover:bg-slate-100 dark:hover:bg-slate-800/50" onclick="likeNote(\'' + escapeAttr(noteId) + '\', \'' + escapeAttr(pubkey) + '\')"><span class="heart-icon action-svg w-3.5 h-3.5 shrink-0">' + ICON_HEART + '</span><span class="action-count like-count-label">' + reactionLikeCount + '</span></button>' +
            ((note.kind === 30023 || note.is_proposal || note.lud16) ? '<button type="button" class="action-btn-contextual flex items-center gap-1.5 text-amber-600 dark:text-amber-400 hover:bg-amber-50 dark:hover:bg-amber-950/40 px-2 py-1 rounded transition-colors font-semibold" onclick="handleContextualAction(\'' + escapeAttr(noteId) + '\', \'' + escapeAttr(note.kind) + '\', \'' + escapeAttr(note.lud16 || '') + '\')"><span class="action-svg w-3.5 h-3.5 shrink-0">' + ((note.kind === 30023 || note.is_proposal) ? ICON_VOTE : ICON_ZAP) + '</span><span>' + ((note.kind === 30023 || note.is_proposal) ? 'Vote' : 'Tip') + '</span></button>' : '') +
            '<button type="button" class="action-btn-share flex items-center gap-1.5 hover:text-blue-600 dark:hover:text-blue-400 transition-colors px-2 py-1 rounded hover:bg-slate-100 dark:hover:bg-slate-800/50" onclick="shareNote(\'' + escapeAttr(noteId) + '\', \'' + escapeAttr(authorName || "") + '\', \'' + escapeAttr((displayContent || noteContent || "").slice(0, 140)) + '\')"><span class="action-svg w-3.5 h-3.5 shrink-0">' + ICON_SHARE + '</span><span class="hidden sm:inline">Share</span></button>' +
            '</div>' +
            replyDrawerHtml +
            '</div></div>';
    }

    // ---------- NIP-36 Content Warning Reveal ----------

    function revealContentWarning(btn) {
        var shield = btn && btn.closest ? btn.closest(".content-warning-shield") : null;
        if (!shield) return;
        shield.classList.add("user-revealed");
        var blurEl = shield.querySelector(".blur-me");
        if (blurEl) {
            blurEl.classList.remove("backdrop-blur-md", "blur-sm", "select-none", "pointer-events-none");
        }
        btn.classList.add("hidden");
    }

    // ---------- "Read More" Post Clamping ----------

    function checkAndApplyClamping(scope) {
        var rootEl = scope || document;
        var wrappers = rootEl.querySelectorAll ? rootEl.querySelectorAll('.note-body-content') : [];
        wrappers.forEach(function (body) {
            var wrapper = body.closest ? body.closest('.note-content-wrapper') : null;
            if (!wrapper) return;
            var btn = wrapper.querySelector('.expand-note-btn');
            if (!btn) return;
            if (wrapper.getAttribute('data-clamped') !== 'true' && body.scrollHeight > body.clientHeight + 20) {
                btn.classList.remove('hidden');
                wrapper.setAttribute('data-clamped', 'true');
            }
        });
    }

    function toggleNoteClamp(btn) {
        if (!btn) return;
        var wrapper = btn.closest('.note-content-wrapper');
        if (!wrapper) return;
        var body = wrapper.querySelector('.note-body-content');
        if (!body) return;
        var isClamped = wrapper.getAttribute('data-clamped') === 'true';
        if (isClamped) {
            body.classList.remove('max-h-60');
            btn.textContent = 'Show less ▴';
            wrapper.setAttribute('data-clamped', 'false');
        } else {
            body.classList.add('max-h-60');
            btn.textContent = 'Show more ▾';
            wrapper.setAttribute('data-clamped', 'true');
        }
    }

    // ---------- Optimistic Feed Insert ----------

    function addNoteToFeed(event) {
        var container = document.getElementById("feed-container") || document.getElementById("feedContainer") || document.getElementById("tab-posts");
        if (!container || !event) return;

        if (event.id) {
            var existing = document.querySelector('[data-note-card-id="' + event.id + '"]') || document.querySelector('.feed-note-card[data-note-id="' + event.id + '"]');
            if (existing) return;
        }

        var wrapper = document.createElement("div");
        wrapper.className = "feed-note-card bg-white dark:bg-slate-900 rounded-xl p-4 border border-slate-200 dark:border-slate-800";
        wrapper.setAttribute("data-note-card-id", event.id);
        wrapper.setAttribute("data-kind", event.kind);
        wrapper.setAttribute("data-note-id", event.id);
        wrapper.setAttribute("data-pubkey", event.pubkey_hex || event.pubkey || "");
        wrapper.setAttribute("data-author-pubkey", event.pubkey_hex || event.pubkey || "");
        wrapper.setAttribute("data-author-did", event.author_did || "");
        wrapper.setAttribute("data-note-tags", JSON.stringify(event.tags || []));
        if (event.has_content_warning || (event.tags && event.tags.some(function (t) { return t[0] === "content-warning"; }))) {
            wrapper.setAttribute("data-has-content-warning", "true");
        }
        if (event.lang) {
            wrapper.setAttribute("data-lang", event.lang);
        }
        wrapper.setAttribute("data-created-at", Math.floor(event.created_at || (Date.now() / 1000)));

        var npub = window.userNpub || (window.userPubkey ? window.userPubkey.substring(0, 12) + "..." : "You");
        var mediaUrl = (event.tags && event.tags.find(function (t) { return t[0] === "url"; })) ? event.tags.find(function (t) { return t[0] === "url"; })[1] : "";
        var mimeType = (event.tags && event.tags.find(function (t) { return t[0] === "m"; })) ? event.tags.find(function (t) { return t[0] === "m"; })[1] : "";

        var mediaAttachments = event.media_attachments || [];
        if (!mediaAttachments.length && mediaUrl) {
            var mType = "file";
            if (mimeType.indexOf("image") !== -1) mType = "image";
            else if (mimeType.indexOf("video") !== -1) mType = "video";
            else if (mimeType.indexOf("audio") !== -1) mType = "audio";
            mediaAttachments.push({ type: mType, url: mediaUrl });
        }

        var noteObj = {
            id: event.id,
            kind: event.kind,
            pubkey: event.pubkey,
            pubkey_hex: event.pubkey,
            author_did: event.author_did || window.userDid || "",
            npub: npub,
            author_name: npub,
            content: event.content,
            display_content: event.display_content,
            created_at: event.created_at,
            tags: event.tags || [],
            media_attachments: mediaAttachments,
            media_url: mediaUrl,
            mime_type: mimeType,
            is_sovereign: true,
            reactions: [],
            reply_count: 0
        };

        wrapper.innerHTML = buildCardHtml(noteObj);

        if (container.firstChild) {
            container.insertBefore(wrapper, container.firstChild);
        } else {
            container.appendChild(wrapper);
        }
        hydrateLocalTimestamps(wrapper);

        if (window.trustLens && typeof window.trustLens.scan === "function") {
            window.trustLens.scan(container);
        }

        checkAndApplyClamping(wrapper);

        var postContent = document.getElementById("postContent");
        if (postContent) postContent.value = "";
        var uploadStatus = document.getElementById("uploadStatus");
        if (uploadStatus) uploadStatus.classList.add("hidden");

        if (container.id === "tab-posts") {
            incrementProfilePostCount();
        }
    }

    function incrementProfilePostCount() {
        var postsTab = document.querySelector('.profile-tab[data-target="tab-posts"]');
        if (!postsTab) return;
        var match = postsTab.textContent.match(/\((\d+)\)/);
        var count = match ? parseInt(match[1], 10) : 0;
        postsTab.textContent = postsTab.textContent.replace(/\(\d+\)/, "(" + (count + 1) + ")");
    }


    // ---------- Append Note from JSON API ----------

    function appendNoteToFeed(note, container, repliesMap) {
        if (!container || !note) return;

        const activeCircle = window.CircleFilter?.activeCircle || 'iyou';
        if (activeCircle === 'iyou') {
            const isIyouAuthor = (window.IYOU_ECOSYSTEM_KEYS && window.IYOU_ECOSYSTEM_KEYS.includes(note.pubkey_hex)) || note.is_sovereign || note.author_did;
            if (!isIyouAuthor) {
                return; // Discard non-ecosystem notes before touching the DOM
            }
        }

        try {
            if (note.id) {
                var existing = document.querySelector('[data-note-card-id="' + note.id + '"]') || document.querySelector('.feed-note-card[data-note-id="' + note.id + '"]');
                if (existing) return;
            }

            var wrapper = document.createElement("div");
            wrapper.className = "feed-note-card bg-white dark:bg-slate-900 rounded-xl p-4 border border-slate-200 dark:border-slate-800";
            wrapper.setAttribute("data-note-card-id", note.id || "");
            wrapper.setAttribute("data-kind", note.kind || 1);
            wrapper.setAttribute("data-note-id", note.id || "");
            wrapper.setAttribute("data-pubkey", note.pubkey_hex || note.pubkey || "");
            wrapper.setAttribute("data-author-pubkey", note.pubkey_hex || note.pubkey || "");
            wrapper.setAttribute("data-author-did", note.author_did || "");
            wrapper.setAttribute("data-note-tags", JSON.stringify(note.tags || []));
            if (note.has_content_warning || (note.tags && note.tags.some(function (t) { return t[0] === "content-warning"; }))) {
                wrapper.setAttribute("data-has-content-warning", "true");
            }
            if (note.lang) {
                wrapper.setAttribute("data-lang", note.lang);
            }
            wrapper.setAttribute("data-created-at", Math.floor(note.created_at_epoch || note.created_at || (Date.now() / 1000)));

            wrapper.innerHTML = buildCardHtml(note);

            var noteReplies = (repliesMap && repliesMap[note.id]) || note.replies || [];
            if (noteReplies.length > 0) {
                var repliesDiv = document.createElement("div");
                repliesDiv.className = "mt-3 pl-4 border-l-2 border-slate-200 dark:border-slate-800 space-y-3";
                repliesDiv.id = "replies-" + (note.id || "");
                repliesDiv.setAttribute("data-parent-id", note.id || "");
                noteReplies.forEach(function (reply) {
                    try {
                        var replyWrapper = document.createElement("div");
                        replyWrapper.className = "bg-slate-50/80 dark:bg-slate-950/60 rounded-xl p-3.5 border border-slate-200/80 dark:border-slate-800/80";
                        replyWrapper.innerHTML = buildCardHtml(reply);
                        if (reply && reply.reply_count && reply.reply_count > 0) {
                            var drilldownDiv = document.createElement("div");
                            drilldownDiv.className = "mt-2.5 pt-2 border-t border-slate-100 dark:border-slate-800 flex justify-end";
                            drilldownDiv.innerHTML = '<a href="/feed?thread=' + encodeURIComponent(reply.id) + '" class="inline-flex items-center gap-1 text-[11px] font-mono text-violet-600 dark:text-violet-400 hover:underline"><span>View ' + reply.reply_count + ' more repl' + (reply.reply_count === 1 ? 'y' : 'ies') + ' →</span></a>';
                            replyWrapper.appendChild(drilldownDiv);
                        }
                        repliesDiv.appendChild(replyWrapper);
                    } catch (replyErr) {
                        console.warn("Failed to render reply note:", reply, replyErr);
                    }
                });
                wrapper.appendChild(repliesDiv);
            }

            container.appendChild(wrapper);
            checkAndApplyClamping(wrapper);
            hydrateLocalTimestamps(wrapper);
            
            // Hide empty state elements when cards are rendered
            var feedEmptyState = document.getElementById("feed-empty-state");
            var circleEmptyState = document.getElementById("circle-empty-state");
            if (feedEmptyState) {
                feedEmptyState.classList.add("hidden");
            }
            if (circleEmptyState) {
                circleEmptyState.classList.add("hidden");
            }

            if (note.kind === 30023) {
                var newForm = wrapper.querySelector(".poll-vote-form");
                if (newForm) {
                    newForm.addEventListener("submit", function (ev) {
                        ev.preventDefault();
                        var pid = this.getAttribute("data-poll-id");
                        var sel = this.querySelector("input[name='selection']:checked");
                        if (!sel) return;
                        var allInputs = this.querySelectorAll("input[name='selection']");
                        var idx = Array.prototype.indexOf.call(allInputs, sel);
                        castPollVote(pid, idx);
                    });
                }
            }
        } catch (err) {
            console.warn("Failed to append note to feed:", note, err);
        }
    }


    // ---------- Cursor-Based Infinite Scroll & Load More ----------

    var _isLoadingFeedNotes = false;

    // ---------- Phase 34: Progressive Stream Hydration ----------
    // When the server renders the instant HTML shell (empty #feed-container
    // flagged with data-hydrate), this async path pulls the first batch from
    // /api/feed/ (the dedicated asynchronous batch payload supplier), removes
    // the skeleton, and hydrates real cards — then rescans TrustLens and
    // re-hydrates local timestamps.

    var _hydratingInitialFeed = false;

    function fetchInitialFeedStream() {
        if (_hydratingInitialFeed) return;
        var container = document.getElementById("feed-container");
        if (!container || container.getAttribute("data-hydrate") !== "true") return;
        _hydratingInitialFeed = true;

        var urlParams = new URLSearchParams(window.location.search);
        var circle = urlParams.get("circle") || "global";
        var mode = urlParams.get("mode") || (circle === "global" ? "global" : "network");
        var activeCircleBtn = document.querySelector(".circle-tab.active, .circle-tab[data-active='true']");
        if (activeCircleBtn && activeCircleBtn.dataset && activeCircleBtn.dataset.circle) {
            circle = activeCircleBtn.dataset.circle;
        }
        var tag = urlParams.get("tag") || "";

        var queryUrl = "/api/feed?limit=25&circle=" + encodeURIComponent(circle) + "&mode=" + encodeURIComponent(mode);
        if (tag) queryUrl += "&tag=" + encodeURIComponent(tag);
        
        // Add active relays from client storage to sync with server
        var activeRelays = getActiveRelays();
        if (activeRelays && activeRelays.length > 0) {
            queryUrl += "&relays=" + encodeURIComponent(JSON.stringify(activeRelays));
        }

        fetch(queryUrl)
            .then(function (r) { return r.json(); })
            .then(function (data) {
                var skeleton = document.getElementById("feed-skeleton-container");
                if (skeleton) skeleton.remove();

                var notes = data.notes || [];
                var repliesMap = data.replies || {};
                notes.forEach(function (note) {
                    appendNoteToFeed(note, container, repliesMap);
                });

                if (data.oldest_timestamp) {
                    var sentinel = document.getElementById("feed-pagination-sentinel");
                    if (sentinel && sentinel.dataset) {
                        sentinel.dataset.oldestTimestamp = data.oldest_timestamp;
                    }
                }

                var emptyState = document.getElementById("feed-empty-state");
                if (notes.length === 0 && !emptyState) {
                    var emptyDiv = document.createElement("div");
                    emptyDiv.id = "feed-empty-state";
                    emptyDiv.className = "text-center py-12 text-slate-400 font-mono text-xs";
                    emptyDiv.textContent = "No notes found in this circle.";
                    container.appendChild(emptyDiv);
                }

                container.removeAttribute("data-hydrate");

                if (window.TrustLens && typeof window.TrustLens.scanDOM === "function") {
                    window.TrustLens.scanDOM();
                } else if (window.trustLens && typeof window.trustLens.scan === "function") {
                    window.trustLens.scan(container);
                }
                hydrateLocalTimestamps(document);
                checkAndApplyClamping(document);
                initFeedPaginationObserver();
            })
            .catch(function (err) {
                console.error("Failed to hydrate initial feed stream:", err);
                var skeleton = document.getElementById("feed-skeleton-container");
                if (skeleton) skeleton.remove();
                container.removeAttribute("data-hydrate");
            })
            .finally(function () {
                _hydratingInitialFeed = false;
            });
    }

    function loadMoreNotes() {
        if (_isLoadingFeedNotes) return;

        var sentinel = document.getElementById("feed-pagination-sentinel");
        var container = document.getElementById("feed-container") || document.getElementById("feedContainer");
        if (!container) return;

        var oldestTimestamp = sentinel && sentinel.dataset ? sentinel.dataset.oldestTimestamp : null;
        if (!oldestTimestamp) {
            var cards = container.querySelectorAll(".feed-note-card");
            if (cards.length > 0) {
                var lastCard = cards[cards.length - 1];
                oldestTimestamp = lastCard.dataset.createdAt || lastCard.getAttribute("data-created-at");
            }
        }

        if (!oldestTimestamp || isNaN(parseInt(oldestTimestamp, 10))) {
            return;
        }

        _isLoadingFeedNotes = true;

        var spinner = document.getElementById("feed-loading-spinner") || document.getElementById("loadMoreSpinner");
        var btn = document.getElementById("load-more-btn") || document.getElementById("loadMoreBtn");
        var endMsg = document.getElementById("feed-end-notice") || document.getElementById("loadMoreEnd");

        if (btn) btn.classList.add("hidden");
        if (spinner) spinner.classList.remove("hidden");

        var urlParams = new URLSearchParams(window.location.search);
        var activeCircle = (window.CircleFilter && window.CircleFilter.activeCircle) || urlParams.get("circle") || "iyou";
        var circle = activeCircle;
        var mode = urlParams.get("mode") || (circle === "global" ? "global" : "network");
        var tag = urlParams.get("tag") || "";

        var until = parseInt(oldestTimestamp, 10) - 1;
        var queryUrl = "/api/feed?until=" + until + "&limit=25&circle=" + encodeURIComponent(circle) + "&mode=" + encodeURIComponent(mode);
        if (tag) {
            queryUrl += "&tag=" + encodeURIComponent(tag);
        }
        
        // Add active relays from client storage to sync with server
        var activeRelays = getActiveRelays();
        if (activeRelays && activeRelays.length > 0) {
            queryUrl += "&relays=" + encodeURIComponent(JSON.stringify(activeRelays));
        }

        fetch(queryUrl)
            .then(function (r) { return r.json(); })
            .then(function (data) {
                var notes = data.notes || [];
                var repliesMap = data.replies || {};

                if (!data.has_more || notes.length === 0) {
                    if (window.feedObserver && sentinel) {
                        window.feedObserver.unobserve(sentinel);
                    }
                    var spinnerEl = document.getElementById("feed-loading-spinner");
                    var loadBtnEl = document.getElementById("load-more-btn");
                    if (spinnerEl) spinnerEl.classList.add("hidden");
                    if (loadBtnEl) loadBtnEl.classList.add("hidden");
                    if (endMsg) endMsg.classList.remove("hidden");

                    var visibleCards = container.querySelectorAll(".feed-note-card:not(.hidden)");
                    if (visibleCards.length === 0) {
                        var emptyState = document.getElementById("feed-empty-state");
                        if (emptyState) emptyState.classList.remove("hidden");
                        return;
                    }
                } else {
                    if (btn) btn.classList.remove("hidden");
                }

                if (notes.length > 0) {
                    notes.forEach(function (note) {
                        appendNoteToFeed(note, container, repliesMap);
                    });

                    if (data.oldest_timestamp && sentinel) {
                        sentinel.dataset.oldestTimestamp = data.oldest_timestamp;
                    }

                    // Trigger TrustLens & CircleFilter re-scans on newly appended items
                    if (window.TrustLens && typeof window.TrustLens.scanDOM === "function") {
                        window.TrustLens.scanDOM();
                    } else if (window.trustLens && typeof window.trustLens.scan === "function") {
                        window.trustLens.scan(container);
                    }

                    if (window.CircleFilter && typeof window.CircleFilter.applyFilters === "function") {
                        window.CircleFilter.applyFilters();
                    } else if (window.circleFilter && typeof window.circleFilter.applyFilter === "function") {
                        window.circleFilter.applyFilter();
                    }
                }
            })
            .catch(function (err) {
                console.error("Failed to load more feed notes:", err);
                if (btn) btn.classList.remove("hidden");
            })
            .finally(function () {
                _isLoadingFeedNotes = false;
                if (spinner) spinner.classList.add("hidden");
            });
    }


    // ---------- Sentinel Observer for Infinite Scroll ----------

    var _isObserverThrottled = false;

    function initFeedPaginationObserver() {
        var sentinel = document.getElementById("feed-pagination-sentinel");
        if (!sentinel || typeof IntersectionObserver === "undefined") return;

        if (window.feedObserver) {
            try { window.feedObserver.disconnect(); } catch (e) {}
        }

        window.feedObserver = new IntersectionObserver(function (entries) {
            entries.forEach(function (entry) {
                if (entry.isIntersecting) {
                    if (_isObserverThrottled) return;

                    var emptyState = document.getElementById("feed-empty-state");
                    var container = document.getElementById("feed-container") || document.getElementById("feedContainer");
                    var cards = container ? container.querySelectorAll(".feed-note-card:not(.hidden)") : [];

                    // If #feed-empty-state is visible or no cards are rendered, do not trigger loadMoreNotes()
                    if ((emptyState && !emptyState.classList.contains("hidden")) || cards.length === 0) {
                        return;
                    }

                    _isObserverThrottled = true;
                    setTimeout(function () {
                        _isObserverThrottled = false;
                    }, 1500);

                    loadMoreNotes();
                }
            });
        }, {
            root: null,
            rootMargin: "300px",
            threshold: 0.1
        });

        window.feedObserver.observe(sentinel);
    }


    // ---------- Blossom Base URL & Media Upload (Kind 1063) ----------

    function getBlossomBaseUrl() {
        // 1. Check if configured via script data attribute or window global
        if (window.BLOSSOM_SERVER_URL && window.BLOSSOM_SERVER_URL.trim()) {
            return window.BLOSSOM_SERVER_URL.trim().replace(/\/+$/, "");
        }
        var feedScript = document.querySelector("script[data-blossom-url]");
        if (feedScript && feedScript.dataset && feedScript.dataset.blossomUrl && feedScript.dataset.blossomUrl.trim()) {
            return feedScript.dataset.blossomUrl.trim().replace(/\/+$/, "");
        }

        // 2. HTTPS Production Context -> Use CDN / TLS Gateway
        if (window.location.protocol === "https:") {
            return "https://cdn.iyou.me";
        }

        // 3. HTTP Local Dev Context -> Use local Blossom server
        return "http://127.0.0.1:9002";
    }

    function getCsrfToken() {
        var cookieMatch = document.cookie.match(/(?:^|;\s*)(?:wun_csrftoken|csrftoken)=([^;]+)/);
        if (cookieMatch) return decodeURIComponent(cookieMatch[1]);
        var input = document.querySelector('input[name="csrfmiddlewaretoken"]');
        return input ? input.value : "";
    }

    async function uploadViaServerProxy(file, hash) {
        // Phase 33 — resilient media proxy: try the dedicated /api/blossom/proxy/
        // route first, then fall back to the original /api/media/upload/ alias so
        // uploads keep working if one route is ever removed or mis-routed.
        var routes = ["/api/blossom/proxy/", "/api/media/upload/"];
        var lastErr = null;
        for (var i = 0; i < routes.length; i++) {
            try {
                var formData = new FormData();
                formData.append("file", file);
                if (hash) formData.append("sha256", hash);
                var headers = {};
                var csrf = getCsrfToken();
                if (csrf) {
                    headers["X-CSRFToken"] = csrf;
                }
                var res = await fetch(routes[i], {
                    method: "POST",
                    headers: headers,
                    body: formData,
                });
                if (!res.ok) {
                    throw new Error("Server proxy upload failed with status " + res.status);
                }
                return await res.json();
            } catch (err) {
                lastErr = err;
                // Route failed — try the next proxy route before giving up.
            }
        }
        throw lastErr || new Error("All server proxy routes failed.");
    }

    async function sha256Hex(data) {
        var hashBuffer = await crypto.subtle.digest("SHA-256", data);
        var hashArray = Array.from(new Uint8Array(hashBuffer));
        return hashArray.map(function (b) { return b.toString(16).padStart(2, "0"); }).join("");
    }

    function setUploadStatus(text) {
        var el = document.getElementById("uploadStatus");
        if (!el) return;
        el.textContent = text;
        el.classList.remove("hidden");
    }

    function clearMediaAttachment() {
        attachedMedia = null;
        var dock = document.getElementById("composer-media-preview-dock");
        if (dock) dock.classList.add("hidden");
        var previewImg = document.getElementById("composer-media-preview-img");
        if (previewImg) { previewImg.src = ""; previewImg.classList.add("hidden"); }
        var previewVid = document.getElementById("composer-media-preview-video");
        if (previewVid) { previewVid.src = ""; previewVid.classList.add("hidden"); }
        var previewIcon = document.getElementById("composer-media-preview-icon");
        if (previewIcon) previewIcon.classList.add("hidden");
        var fileInput = document.getElementById("composer-file-input");
        if (fileInput) fileInput.value = "";
        var mediaInput = document.getElementById("mediaInput");
        if (mediaInput) mediaInput.value = "";
        var status = document.getElementById("uploadStatus");
        if (status) status.classList.add("hidden");
    }
    window.clearMediaAttachment = clearMediaAttachment;

    async function handleMediaSelected(file) {
        if (!file) return;
        setUploadStatus("Hashing file...");
        try {
            var arrayBuffer = await file.arrayBuffer();
            var hash = await sha256Hex(arrayBuffer);
            var baseUrl = getBlossomBaseUrl();
            var uploadedUrl = null;
            var blobExists = false;

            setUploadStatus("Checking Blossom...");
            try {
                var headRes = await fetch(baseUrl + "/" + hash, {
                    method: "HEAD",
                });
                if (headRes.ok) {
                    blobExists = true;
                    uploadedUrl = baseUrl + "/" + hash;
                }
            } catch (e) {
                // Direct HEAD failed (PNA / CORS / network), continue to upload attempts
            }

            if (!blobExists) {
                setUploadStatus("Uploading to Blossom...");
                var directUploaded = false;
                try {
                    var mimeType = file.type || "application/octet-stream";
                    var putRes = await fetch(baseUrl + "/upload", {
                        method: "PUT",
                        headers: {
                            "Content-Type": mimeType,
                            "X-SHA-256": hash,
                        },
                        body: arrayBuffer,
                    });
                    if (putRes.status === 200 || putRes.status === 201) {
                        directUploaded = true;
                        try {
                            var putData = await putRes.json();
                            if (putData && putData.url) {
                                uploadedUrl = putData.url;
                            }
                        } catch (err) {
                            /* ignore JSON parse */
                        }
                        if (!uploadedUrl) {
                            uploadedUrl = baseUrl + "/" + hash;
                        }
                    } else if (putRes.status === 404 || putRes.status === 405) {
                        var putHashRes = await fetch(baseUrl + "/" + hash, {
                            method: "PUT",
                            headers: {
                                "Content-Type": mimeType,
                                "X-SHA-256": hash,
                            },
                            body: arrayBuffer,
                        });
                        if (putHashRes.status === 200 || putHashRes.status === 201) {
                            directUploaded = true;
                            uploadedUrl = baseUrl + "/" + hash;
                        }
                    }
                } catch (directErr) {
                    console.warn("Direct Blossom upload failed, trying server proxy:", directErr);
                }

                if (!directUploaded) {
                    setUploadStatus("Proxying upload via server...");
                    try {
                        var proxyData = await uploadViaServerProxy(file, hash);
                        if (proxyData && proxyData.url) {
                            uploadedUrl = proxyData.url;
                        } else {
                            uploadedUrl = baseUrl + "/" + hash;
                        }
                    } catch (proxyErr) {
                        console.warn("Server proxy upload also failed:", proxyErr);
                        uploadedUrl = baseUrl + "/" + hash;
                    }
                }
            }

            var ext = file.name ? file.name.split('.').pop().toLowerCase() : '';
            var canonicalUrl = "https://cdn.iyou.me/" + hash + (ext ? "." + ext : "");
            var finalUrl = uploadedUrl || canonicalUrl;
            var mime = file.type || "application/octet-stream";

            attachedMedia = {
                url: finalUrl,
                hash: hash,
                mimeType: mime,
                size: file.size,
                name: file.name
            };

            // Preview attachment in composer dock
            var dock = document.getElementById("composer-media-preview-dock");
            var previewImg = document.getElementById("composer-media-preview-img");
            var previewVid = document.getElementById("composer-media-preview-video");
            var previewIcon = document.getElementById("composer-media-preview-icon");
            var nameEl = document.getElementById("composer-media-filename");
            var hashEl = document.getElementById("composer-media-hash");
            var urlEl = document.getElementById("composer-media-url");

            if (nameEl) nameEl.textContent = file.name || "Media File";
            if (hashEl) hashEl.textContent = "SHA-256: " + hash.slice(0, 16) + "...";
            if (urlEl) urlEl.textContent = finalUrl;

            var objectUrl = URL.createObjectURL(file);
            if (mime.indexOf("image") !== -1 && previewImg) {
                previewImg.src = objectUrl;
                previewImg.classList.remove("hidden");
                if (previewVid) previewVid.classList.add("hidden");
                if (previewIcon) previewIcon.classList.add("hidden");
            } else if (mime.indexOf("video") !== -1 && previewVid) {
                previewVid.src = objectUrl;
                previewVid.classList.remove("hidden");
                if (previewImg) previewImg.classList.add("hidden");
                if (previewIcon) previewIcon.classList.add("hidden");
            } else if (previewIcon) {
                previewIcon.textContent = mime.indexOf("audio") !== -1 ? "🎵" : "📄";
                previewIcon.classList.remove("hidden");
                if (previewImg) previewImg.classList.add("hidden");
                if (previewVid) previewVid.classList.add("hidden");
            }
            if (dock) dock.classList.remove("hidden");

            setUploadStatus("Media attached ready to post.");
            setTimeout(function () {
                var el = document.getElementById("uploadStatus");
                if (el) el.classList.add("hidden");
            }, 2500);

        } catch (err) {
            setUploadStatus("Error: " + err.message);
            setTimeout(function () {
                var el = document.getElementById("uploadStatus");
                if (el) el.classList.add("hidden");
            }, 3000);
        }
    }


    // ---------- Poll Governance ----------

    function toggleGear(event) {
        event.stopPropagation();
        var btn = event.currentTarget;
        var dropdown = btn.parentElement.querySelector(".gear-dropdown");
        if (!dropdown) return;
        var isHidden = dropdown.classList.contains("hidden");
        document.querySelectorAll(".gear-dropdown").forEach(function (d) { d.classList.add("hidden"); });
        if (isHidden) dropdown.classList.remove("hidden");
    }

    async function castPollVote(pollId, selectOptionIndex) {
        var card = document.querySelector('[data-poll-id="' + pollId + '"]');
        if (!card) return;
        var options = card.querySelectorAll("input[name='selection']");
        if (!options || selectOptionIndex < 0 || selectOptionIndex >= options.length) return;
        var selectedInput = options[selectOptionIndex];
        if (!selectedInput) return;
        var selectedValue = selectedInput.value;
        var pk;
        try { pk = await bridgeClient.getEffectivePubkey(); }
        catch (e) { showToast(e.message, true); return; }

        var pubkey = card.getAttribute("data-poll-pubkey") || "";
        var dtag = card.getAttribute("data-poll-dtag") || "";
        var form = card.querySelector(".poll-vote-form");
        var btn = form ? form.querySelector("button[type='submit']") : null;
        var timestamp = Math.floor(Date.now() / 1000);
        var voteEnvelope = {
            poll_id: pollId,
            selection: selectedValue,
            timestamp: timestamp
        };

        var tags = [];
        if (pubkey && dtag) {
            tags.push(["a", "30023:" + pubkey + ":" + dtag]);
        } else {
            tags.push(["e", pollId]);
        }
        tags.push(["vote", selectedValue]);

        var event = {
            kind: 1112,
            content: JSON.stringify(voteEnvelope),
            pubkey: pk,
            created_at: timestamp,
            tags: tags
        };

        if (btn) { btn.disabled = true; btn.textContent = "Signing..."; }
        pendingVote = { pollId: pollId, selection: selectedValue, timestamp: timestamp, form: form, btn: btn };
        bridgeClient.signEvent(event);
    }

    // ---------- Poll Creation ----------

    function openPollModal() {
        document.getElementById("pollModal").classList.remove("hidden");
    }

    function closePollModal() {
        var modal = document.getElementById("pollModal");
        var form = document.getElementById("pollForm");
        if (modal) modal.classList.add("hidden");
        if (form) form.reset();
    }

    function addPollOption() {
        var container = document.getElementById("pollOptionsContainer");
        if (!container) return;
        var count = container.querySelectorAll(".option-row").length;
        var div = document.createElement("div");
        div.className = "option-row flex items-center gap-2";
        div.innerHTML =
            '<input type="text" class="poll-option flex-1 border border-gray-300 rounded-lg px-4 py-2 text-gray-700 focus:outline-none focus:ring-2 focus:ring-amber-500 focus:border-transparent" placeholder="Option ' +
            (count + 1) + '" required />' +
            '<button type="button" onclick="removeOption(this)" class="text-red-400 hover:text-red-600 transition-colors p-1" title="Remove option">' +
            '<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path></svg>' +
            '</button>';
        container.appendChild(div);
    }

    function removeOption(btn) {
        var row = btn.closest(".option-row");
        if (row && document.querySelectorAll(".option-row").length > 2) {
            row.remove();
        }
    }

    async function createPoll() {
        var pk;
        try { pk = await bridgeClient.getEffectivePubkey(); }
        catch (e) { showToast(e.message, true); return; }
        var title = document.getElementById("pollTitle").value.trim();
        var description = document.getElementById("pollDescription").value.trim();
        var scope = document.getElementById("pollScope").value;
        var fidelity = parseInt(document.getElementById("pollFidelity").value, 10);
        var optionInputs = document.querySelectorAll(".poll-option");
        var options = [];
        optionInputs.forEach(function (inp) {
            var val = inp.value.trim();
            if (val) options.push(val);
        });
        if (!title) { showToast("Please enter a poll title.", true); return; }
        if (options.length < 2) { showToast("Please provide at least 2 options.", true); return; }

        var tags = [
            ["d", uuidv4()],
            ["title", title],
            ["fidelity_min", String(fidelity)]
        ];
        options.forEach(function (opt) { tags.push(["option", opt]); });
        if (scope === "regional") {
            tags.push(["geohash", "global"]);
        } else if (scope === "family") {
            tags.push(["org", "iyou"]);
        }
        var expires = Math.floor(Date.now() / 1000) + 30 * 24 * 60 * 60;
        tags.push(["expires", String(expires)]);

        var event = {
            kind: 30023,
            content: description || title,
            pubkey: pk,
            created_at: Math.floor(Date.now() / 1000),
            tags: tags
        };

        bridgeClient.isProcessing = true;
        pendingPoll = true;
        document.getElementById("publishPollBtn").disabled = true;
        document.getElementById("publishPollBtn").textContent = "Signing...";
        bridgeClient.signEvent(event);
    }

    // ---------- Reactions, Reposts & Kebab Actions ----------

    async function likeNote(noteId, authorPubkey) {
        if (!noteId) return;
        var pk;
        try { pk = await bridgeClient.getEffectivePubkey(); }
        catch (e) { showToast(e.message || "Sign in with a sovereign key to like notes.", "error"); return; }

        var btn = document.querySelector('[data-note-card-id="' + noteId + '"] .action-btn-like, [data-note-id="' + noteId + '"] .action-btn-like');
        var countLabel = btn ? btn.querySelector(".like-count-label") : null;
        if (btn) {
            btn.classList.add("text-pink-600", "dark:text-pink-400", "font-bold", "liked");
            var heartSvg = btn.querySelector(".heart-icon svg");
            if (heartSvg) {
                heartSvg.setAttribute("fill", "#ec4899");
                heartSvg.setAttribute("stroke", "#ec4899");
            }
        }
        if (countLabel) {
            var curr = parseInt(countLabel.textContent, 10);
            countLabel.textContent = isNaN(curr) ? "1" : String(curr + 1);
        }

        var event = {
            kind: 7,
            content: "+",
            pubkey: pk,
            created_at: Math.floor(Date.now() / 1000),
            tags: [
                ["e", noteId, "wss://relay.iyou.me"],
                ["p", authorPubkey || "", "wss://relay.iyou.me"]
            ]
        };

        pendingReaction = { noteId: noteId };
        bridgeClient.isProcessing = true;
        bridgeClient.signEvent(event);
    }

    async function repostNote(noteId, authorPubkey) {
        if (!noteId) return;
        var pk;
        try { pk = await bridgeClient.getEffectivePubkey(); }
        catch (e) { showToast(e.message || "Sign in with a sovereign key to repost notes.", "error"); return; }

        var btn = document.querySelector('[data-note-card-id="' + noteId + '"] .action-btn-repost, [data-note-id="' + noteId + '"] .action-btn-repost');
        if (btn) btn.classList.add("text-emerald-600", "dark:text-emerald-400", "font-bold");

        var event = {
            kind: 6,
            content: "",
            pubkey: pk,
            created_at: Math.floor(Date.now() / 1000),
            tags: [
                ["e", noteId, "wss://relay.iyou.me"],
                ["p", authorPubkey || "", "wss://relay.iyou.me"]
            ]
        };

        pendingRepost = { noteId: noteId };
        bridgeClient.isProcessing = true;
        bridgeClient.signEvent(event);
    }

    function toggleRepostDropdown(noteId) {
        var menu = document.getElementById("repost-menu-" + noteId);
        if (!menu) return;
        var isHidden = menu.classList.contains("hidden");
        document.querySelectorAll(".repost-menu-container [id^='repost-menu-']").forEach(function (m) {
            m.classList.add("hidden");
        });
        if (isHidden) menu.classList.remove("hidden");
    }

    function openQuoteComposer(noteId, pubkey, authorName, snippet, mediaUrl) {
        quotedTarget = { id: noteId, pubkey: pubkey || "" };
        var dock = document.getElementById("quote-preview-dock");
        if (!dock) return;
        dock.classList.remove("hidden");
        var authorEl = document.getElementById("quote-preview-author");
        if (authorEl) authorEl.textContent = "@" + (authorName || (pubkey ? pubkey.slice(0, 12) + "…" : "user"));
        var snippetEl = document.getElementById("quote-preview-snippet");
        if (snippetEl) snippetEl.textContent = snippet || "";
        var mediaWrap = document.getElementById("quote-preview-media");
        var mediaImg = document.getElementById("quote-preview-media-img");
        if (mediaUrl && mediaImg) {
            mediaImg.src = mediaUrl;
            if (mediaWrap) mediaWrap.classList.remove("hidden");
        } else if (mediaWrap) {
            mediaWrap.classList.add("hidden");
        }
        window.scrollTo({ top: 0, behavior: "smooth" });
        var editor = document.getElementById("postContent");
        if (editor) { editor.focus(); editor.scrollIntoView({ behavior: "smooth", block: "center" }); }
    }

    function clearQuoteAttachment() {
        quotedTarget = null;
        var dock = document.getElementById("quote-preview-dock");
        if (dock) dock.classList.add("hidden");
        var mediaWrap = document.getElementById("quote-preview-media");
        if (mediaWrap) mediaWrap.classList.add("hidden");
    }

    document.addEventListener("click", function (e) {
        var isInside = false;
        var el = e.target;
        while (el) {
            if (el.classList && (el.classList.contains("repost-menu-container") || el.id && el.id.indexOf("repost-menu-") === 0)) {
                isInside = true;
                break;
            }
            el = el.parentNode;
        }
        if (!isInside) {
            document.querySelectorAll(".repost-menu-container [id^='repost-menu-']").forEach(function (m) {
                m.classList.add("hidden");
            });
        }
    });

    function suggestToDev(noteId, authorPubkey, snippet) {
        var url = "https://dev.iyou.me/suggest?event_id=" + encodeURIComponent(noteId || "") +
            "&author=" + encodeURIComponent(authorPubkey || "") +
            "&snippet=" + encodeURIComponent(snippet || "") +
            "&ref=iyou_wun";
        window.open(url, "_blank");
    }

    function openReportModal(noteId, pubkey) {
        var existing = document.getElementById("reportModal");
        if (existing) existing.remove();

        var reasons = ["spam", "nudity", "illegal", "malware", "profanity", "other"];
        var options = reasons.map(function (r) {
            return '<label class="flex items-center gap-2 p-2 rounded-lg border border-slate-200 dark:border-slate-700 hover:bg-slate-50 dark:hover:bg-slate-800 cursor-pointer transition-colors text-xs">' +
                '<input type="radio" name="report-reason" value="' + r + '" class="accent-rose-600">' +
                '<span class="text-slate-700 dark:text-slate-200">' + r.charAt(0).toUpperCase() + r.slice(1) + '</span>' +
                '</label>';
        }).join("");

        var modal = document.createElement("div");
        modal.id = "reportModal";
        modal.className = "fixed inset-0 z-50 hidden items-center justify-center bg-black/60 p-4";
        modal.innerHTML =
            '<div class="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl shadow-2xl w-full max-w-md font-mono text-xs">' +
            '<div class="p-4 border-b border-slate-200 dark:border-slate-800 flex items-center justify-between">' +
            '<h3 class="font-semibold text-slate-900 dark:text-slate-100 text-sm">Report / Flag Note</h3>' +
            '<button type="button" onclick="document.getElementById(\'reportModal\').remove()" class="text-slate-400 hover:text-slate-700 dark:hover:text-slate-200 text-base leading-none">&times;</button>' +
            '</div>' +
            '<div class="p-4 space-y-2">' +
            '<p class="text-slate-500 dark:text-slate-400 mb-1">Select a reason:</p>' +
            options +
            '</div>' +
            '<div class="p-4 border-t border-slate-200 dark:border-slate-800 flex items-center justify-end gap-2">' +
            '<button type="button" onclick="document.getElementById(\'reportModal\').remove()" class="px-3 py-1.5 bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300 rounded transition">Cancel</button>' +
            '<button type="button" id="report-submit-btn" class="px-3 py-1.5 bg-rose-600 hover:bg-rose-500 text-white rounded transition">Submit Report</button>' +
            '</div>' +
            '</div>';

        document.body.appendChild(modal);
        modal.classList.remove("hidden");
        modal.querySelector("#report-submit-btn").addEventListener("click", function () {
            var selected = modal.querySelector("input[name='report-reason']:checked");
            var reason = selected ? selected.value : "other";
            submitReport(noteId, pubkey, reason);
        });
    }

    async function submitReport(noteId, pubkey, reason) {
        if (!noteId) return;
        var pk;
        try { pk = await bridgeClient.getEffectivePubkey(); }
        catch (e) { showToast(e.message || "Sign in with a sovereign key to report notes.", true); return; }

        var modal = document.getElementById("reportModal");
        if (modal) modal.remove();

        var card = document.querySelector('[data-note-card-id="' + noteId + '"], [data-note-id="' + noteId + '"]');
        var wrapper = card ? (card.closest(".feed-note-card") || card) : null;
        if (wrapper) wrapper.remove();

        var event = {
            kind: 1984,
            content: "Report: " + reason,
            pubkey: pk,
            created_at: Math.floor(Date.now() / 1000),
            tags: [
                ["e", noteId, "wss://relay.iyou.me", reason],
                ["p", pubkey || "", "wss://relay.iyou.me"]
            ]
        };

        pendingReport = { noteId: noteId };
        bridgeClient.isProcessing = true;
        bridgeClient.signEvent(event);
    }

    async function nominatePostOfTheDay(noteId, authorPubkey) {
        if (!noteId) return;
        var pk;
        try { pk = await bridgeClient.getEffectivePubkey(); }
        catch (e) { showToast("Sign in with a sovereign key to nominate notes.", true); return; }

        var today = new Date().toISOString().slice(0, 10);
        var event = {
            kind: 1112,
            content: "Post of the Day nomination",
            pubkey: pk,
            created_at: Math.floor(Date.now() / 1000),
            tags: [
                ["e", noteId, "", "nomination"],
                ["p", authorPubkey || "", ""],
                ["d", "potd-" + today],
                ["vote", "nominate"],
                ["app", "iyou_wun"]
            ]
        };

        pendingNomination = { noteId: noteId };
        bridgeClient.isProcessing = true;
        bridgeClient.signEvent(event);
    }

    function setEnclavePetname(authorPubkey, defaultName) {
        if (!authorPubkey) return;
        var name = prompt("Enter a local petname for this contact in the Enclave:", defaultName || "");
        if (name && name.trim()) {
            var bridge = window.tauriBridge || window.bridgeClient;
            if (bridge && typeof bridge.setPeerAlias === "function") {
                bridge.setPeerAlias(authorPubkey, name.trim(), "Level0")
                    .then(function () {
                        showToast("Petname saved in Enclave.");
                        if (window.trustLens && typeof window.trustLens.scan === "function") {
                            window.trustLens.scan();
                        }
                    })
                    .catch(function () {
                        showToast("Saved petname locally.");
                    });
            } else {
                showToast("Petname assigned: " + name.trim());
            }
        }
    }

    function viewRawEventJson(noteId) {
        var card = document.querySelector('[data-note-card-id="' + noteId + '"], [data-note-id="' + noteId + '"]');
        var tagsRaw = card ? card.getAttribute("data-note-tags") : "";
        var pubkey = card ? (card.getAttribute("data-author-pubkey") || card.getAttribute("data-pubkey")) : "";
        var kind = card ? card.getAttribute("data-kind") : "1";
        var contentEl = card ? card.querySelector(".note-text-content") : null;
        var content = contentEl ? contentEl.textContent.trim() : "";

        var tags = [];
        try { tags = tagsRaw ? JSON.parse(tagsRaw) : []; } catch (e) { tags = []; }

        var mockEvent = {
            id: noteId,
            pubkey: pubkey,
            kind: parseInt(kind, 10) || 1,
            created_at: Math.floor(Date.now() / 1000),
            tags: tags,
            content: content
        };

        var existingModal = document.getElementById("rawEventJsonModal");
        if (existingModal) existingModal.remove();

        var modal = document.createElement("div");
        modal.id = "rawEventJsonModal";
        modal.className = "fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-xs";
        modal.innerHTML = '<div class="bg-slate-900 border border-slate-700 rounded-xl shadow-2xl w-full max-w-2xl max-h-[85vh] flex flex-col font-mono text-xs">' +
            '<div class="p-4 border-b border-slate-800 flex items-center justify-between">' +
            '<h3 class="font-bold text-slate-200 text-sm">Raw Nostr Event JSON</h3>' +
            '<button type="button" onclick="document.getElementById(\'rawEventJsonModal\').remove()" class="text-slate-400 hover:text-white p-1 text-base">&times;</button>' +
            '</div>' +
            '<div class="p-4 overflow-y-auto flex-1">' +
            '<pre class="bg-slate-950 p-4 rounded-lg text-violet-300 overflow-x-auto text-[11px] leading-relaxed border border-slate-800 select-all">' + escapeHtml(JSON.stringify(mockEvent, null, 2)) + '</pre>' +
            '</div>' +
            '<div class="p-4 border-t border-slate-800 flex justify-end gap-2">' +
            '<button type="button" id="copyJsonBtn" class="px-3 py-1.5 bg-violet-600 hover:bg-violet-700 text-white rounded font-medium transition">Copy JSON</button>' +
            '<button type="button" onclick="document.getElementById(\'rawEventJsonModal\').remove()" class="px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded transition">Close</button>' +
            '</div>' +
            '</div>';

        document.body.appendChild(modal);

        modal.querySelector("#copyJsonBtn").addEventListener("click", function () {
            navigator.clipboard.writeText(JSON.stringify(mockEvent, null, 2)).then(function () {
                showToast("JSON copied to clipboard.");
            });
        });
    }

    function copyNotePermalink(noteId) {
        var permalink = window.location.origin + "/feed?thread=" + encodeURIComponent(noteId);
        if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(permalink).then(function () {
                showToast("Permalink copied to clipboard", "copy");
            });
        } else {
            prompt("Copy permalink:", permalink);
        }
    }

    function shareNote(noteId, authorName, snippet) {
        var permalink = window.location.origin + "/feed?thread=" + encodeURIComponent(noteId);
        if (navigator.share) {
            navigator.share({
                title: (authorName || "Author") + " on iyou_wun",
                text: snippet || "Shared from iyou_wun",
                url: permalink
            }).catch(function (err) {
                if (err && err.name === "AbortError") {
                    return;
                }
                copyNotePermalink(noteId);
            });
        } else {
            copyNotePermalink(noteId);
        }
    }

    function handleContextualAction(noteId, kind, lud16) {
        if (kind === "30023" || kind === 30023) {
            var form = document.querySelector('[data-poll-id="' + noteId + '"]');
            if (form) {
                form.scrollIntoView({ behavior: "smooth", block: "center" });
            } else {
                openPollModal();
            }
        } else if (lud16) {
            window.location.href = "lightning:" + encodeURIComponent(lud16);
        } else {
            showToast("Contextual action triggered.");
        }
    }

    function toggleKebabMenu(event) {
        event.stopPropagation();
        var btn = event.currentTarget;
        var wrap = btn.closest(".kebab-menu-wrap");
        if (!wrap) return;
        var dropdown = wrap.querySelector(".kebab-dropdown");
        if (!dropdown) return;
        var isHidden = dropdown.classList.contains("hidden");
        document.querySelectorAll(".kebab-dropdown, .gear-dropdown").forEach(function (d) {
            d.classList.add("hidden");
        });
        if (isHidden) dropdown.classList.remove("hidden");
    }

    // ---------- Global Click (close dropdowns) ----------

    document.addEventListener("click", function () {
        document.querySelectorAll(".gear-dropdown, .kebab-dropdown").forEach(function (d) { d.classList.add("hidden"); });
    });

    // ---------- Poll Form Init ----------

    document.addEventListener("DOMContentLoaded", function () {
        document.querySelectorAll(".poll-vote-form").forEach(function (form) {
            form.addEventListener("submit", function (e) {
                e.preventDefault();
                var pollId = form.getAttribute("data-poll-id");
                var selected = form.querySelector("input[name='selection']:checked");
                if (!selected) return;
                var allInputs = form.querySelectorAll("input[name='selection']");
                var index = Array.prototype.indexOf.call(allInputs, selected);
                castPollVote(pollId, index);
            });
        });

        initFeedPaginationObserver();
    });

    if (document.readyState === "complete" || document.readyState === "interactive") {
        initFeedPaginationObserver();
    }

    // ---------- Inline Note Translation Engine ----------

    function translateNote(btn, noteId, sourceLang) {
        var targetLang = "en";
        
        // Locate the note body element
        var card = btn.closest('[data-note-card-id]') || btn.closest('.feed-note-card');
        var bodyContent = card.querySelector('.note-body-content');
        if (!bodyContent) return;

        // Toggle state
        // If currently showing translation: restore cached original text and set label back to Translate
        var translateLabel = card.querySelector('.translate-label');
        if (btn.getAttribute('data-showing-translation') === 'true') {
            var originalText = btn.getAttribute('data-original-content');
            if (originalText) {
                bodyContent.innerHTML = originalText;
            }
            btn.removeAttribute('data-showing-translation');
            btn.removeAttribute('data-original-content');
            if (translateLabel) translateLabel.textContent = 'Translate';
            return;
        }

        // If showing original: display loading indicator, call API, cache original, replace body, update label
        var originalText = bodyContent.innerHTML || bodyContent.textContent || "";
        if (!originalText.trim()) return;

        // Store original content
        btn.setAttribute('data-original-content', originalText);
        
        // Show loading state
        if (translateLabel) translateLabel.textContent = 'Translating...';
        btn.disabled = true;

        fetch('/api/translate/', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCsrfToken()
            },
            body: JSON.stringify({
                text: originalText.trim(),
                source_lang: sourceLang,
                target_lang: targetLang
            })
        })
        .then(function (res) {
            if (!res.ok) {
                throw new Error('Translation failed with HTTP ' + res.status);
            }
            return res.json();
        })
        .then(function (data) {
            if (data && data.success && data.translated_text) {
                bodyContent.innerHTML = data.translated_text;
                btn.setAttribute('data-showing-translation', 'true');
                if (translateLabel) translateLabel.textContent = 'View Original';
            } else {
                throw new Error((data && data.error) || 'Translation error');
            }
        })
        .catch(function (err) {
            if (typeof showToast === 'function') {
                showToast('Translation unavailable: ' + err.message, 'warning');
            }
        })
        .finally(function () {
            btn.disabled = false;
        });
    }

    function toggleOriginalNote(noteId) {
        var card = document.querySelector('[data-note-card-id="' + noteId + '"]') || document.querySelector('.feed-note-card[data-note-id="' + noteId + '"]');
        if (!card) return;

        var btn = card.querySelector('.translate-btn[data-note-id="' + noteId + '"]') || card.querySelector('.translate-btn');
        var transBox = document.getElementById('translated-box-' + noteId);
        var bodyContent = card.querySelector('.note-body-content');
        if (!transBox || !bodyContent) return;

        if (bodyContent.classList.contains('hidden')) {
            bodyContent.classList.remove('hidden');
            transBox.classList.add('hidden');
            if (btn) btn.innerHTML = '<span>🌐 View Translation</span>';
        } else {
            bodyContent.classList.add('hidden');
            transBox.classList.remove('hidden');
            if (btn) btn.innerHTML = '<span>🌐 View Original</span>';
        }
    }

    // ---------- Public API ----------

    window.postToNostr = postToNostr;
    window.publishPost = postToNostr;
    window.showReplyEditor = showReplyEditor;
    window.cancelReply = cancelReply;
    window.submitReply = submitReply;
    window.toggleReplies = toggleReplies;
    window.broadcastReplyToRelays = broadcastReplyToRelays;

    window.appendReplyToThread = appendReplyToThread;
    window.addNoteToFeed = addNoteToFeed;
    window.revealContentWarning = revealContentWarning;
    window.checkAndApplyClamping = checkAndApplyClamping;
    window.toggleNoteClamp = toggleNoteClamp;
    window.appendNoteToFeed = appendNoteToFeed;
    window.loadMoreNotes = loadMoreNotes;
    window.getBlossomBaseUrl = getBlossomBaseUrl;
    window.handleMediaSelected = handleMediaSelected;
    window.toggleGear = toggleGear;
    window.toggleKebabMenu = toggleKebabMenu;
    window.likeNote = likeNote;
    window.repostNote = repostNote;
    window.toggleRepostDropdown = toggleRepostDropdown;
    window.openQuoteComposer = openQuoteComposer;
    window.clearQuoteAttachment = clearQuoteAttachment;
    window.suggestToDev = suggestToDev;
    window.nominatePostOfTheDay = nominatePostOfTheDay;
    window.setEnclavePetname = setEnclavePetname;
    window.viewRawEventJson = viewRawEventJson;
    window.copyNotePermalink = copyNotePermalink;
    window.shareNote = shareNote;
    window.handleContextualAction = handleContextualAction;
    window.openReportModal = openReportModal;
    window.submitReport = submitReport;
    window.castPollVote = castPollVote;
    window.openPollModal = openPollModal;
    window.openPollCreateModal = openPollModal;
    window.closePollModal = closePollModal;
    window.addPollOption = addPollOption;
    window.removeOption = removeOption;
    window.formatLocalTimestamp = formatLocalTimestamp;
    window.hydrateLocalTimestamps = hydrateLocalTimestamps;
    // ---------- Self-Moderation Actions (Hide, Mute, Block) ----------

    function getStorageArray(key) {
        try {
            var raw = localStorage.getItem(key);
            return raw ? JSON.parse(raw) : [];
        } catch (e) {
            return [];
        }
    }

    function setStorageArray(key, arr) {
        try {
            localStorage.setItem(key, JSON.stringify(arr));
        } catch (e) {
            console.error("Failed to save to localStorage:", e);
        }
    }

    function hideNote(noteId) {
        if (!noteId) return;
        var hiddenNotes = getStorageArray("wun_hidden_notes");
        if (!hiddenNotes.includes(noteId)) {
            hiddenNotes.push(noteId);
            setStorageArray("wun_hidden_notes", hiddenNotes);
        }
        var cards = document.querySelectorAll('.feed-note-card[data-note-card-id="' + CSS.escape(noteId) + '"], [data-note-id="' + CSS.escape(noteId) + '"]');
        cards.forEach(function(card) {
            card.remove();
        });
        if (typeof showToast === "function") {
            showToast("Note hidden from feed", "info");
        }
    }

    function muteAuthor(pubkey, authorName) {
        if (!pubkey) return;
        var muted = getStorageArray("wun_muted_pubkeys");
        if (!muted.includes(pubkey)) {
            muted.push(pubkey);
            setStorageArray("wun_muted_pubkeys", muted);
        }
        var cards = document.querySelectorAll('.feed-note-card[data-pubkey="' + CSS.escape(pubkey) + '"], .feed-note-card[data-author-pubkey="' + CSS.escape(pubkey) + '"]');
        cards.forEach(function(card) {
            card.remove();
        });
        var label = authorName ? "@" + authorName : "Author";
        if (typeof showToast === "function") {
            showToast("Muted " + label, "info");
        }
    }

    function blockAuthor(pubkey, authorName) {
        if (!pubkey) return;
        var blocked = getStorageArray("wun_blocked_pubkeys");
        if (!blocked.includes(pubkey)) {
            blocked.push(pubkey);
            setStorageArray("wun_blocked_pubkeys", blocked);
        }
        var cards = document.querySelectorAll('.feed-note-card[data-pubkey="' + CSS.escape(pubkey) + '"], .feed-note-card[data-author-pubkey="' + CSS.escape(pubkey) + '"]');
        cards.forEach(function(card) {
            card.remove();
        });
        if (typeof closeDockedChat === "function") {
            closeDockedChat(pubkey);
        }
        var label = authorName ? "@" + authorName : "Author";
        if (typeof showToast === "function") {
            showToast("Blocked " + label, "warning");
        }
    }

    window.hideNote = hideNote;
    window.muteAuthor = muteAuthor;
    window.blockAuthor = blockAuthor;
    window.createPoll = createPoll;
    window.translateNote = translateNote;
    window.toggleOriginalNote = toggleOriginalNote;

    // ---------- Phase 23: Global Directory Search (NIP-50) ----------

    const BECH32_CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l";
    const GLOBAL_DIRECTORY_RELAYS = ["wss://purplepag.es", "wss://relay.nostr.band"];

    function decodeBech32(str) {
        // Minimal bech32 decoder -> { hrp, data(bytes[]) } | null
        if (!str || typeof str !== "string") return null;
        const clean = str.toLowerCase().replace(/\s*/g, "");
        const pos = clean.lastIndexOf("1");
        if (pos < 1 || pos + 1 > clean.length - 1) return null;
        const hrp = clean.slice(0, pos);
        const dataStr = clean.slice(pos + 1);
        let acc = 0, bits = 0;
        const values = [];
        for (let i = 0; i < dataStr.length; i++) {
            const c = dataStr.charCodeAt(i);
            const d = BECH32_CHARSET.indexOf(dataStr[i]);
            if (d === -1) return null;
            acc = (acc << 5) | d;
            bits += 5;
            if (bits >= 8) {
                bits -= 8;
                values.push((acc >> bits) & 0xff);
            }
        }
        return { hrp: hrp, bytes: values };
    }

    function decodeEventId(noteLike) {
        // Decode note1.../nevent1... to a 64-char hex event id, or null.
        const dec = decodeBech32(noteLike);
        if (!dec || (dec.hrp !== "note" && dec.hrp !== "nevent")) return null;
        let bytes = dec.bytes;
        if (dec.hrp === "nevent") {
            // NIP-19 nevent: [0,32] = event id hex bytes
            if (bytes.length < 32) return null;
            bytes = bytes.slice(0, 32);
        }
        let hex = "";
        for (let i = 0; i < bytes.length; i++) {
            hex += ("0" + bytes[i].toString(16)).slice(-2);
        }
        return hex.length === 64 ? hex : null;
    }

    function isIdentifierLike(q) {
        return /^npub1[0-9a-z]{10,}$/i.test(q) ||
            /^(note|nevent)1[0-9a-z]{10,}$/i.test(q) ||
            /^[0-9a-fA-F]{64}$/.test(q) ||
            /^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$/.test(q);
    }

    function routeGlobalQuery(query) {
        const q = (query || "").trim();
        if (!q) return;
        if (/^npub1[0-9a-z]{10,}$/i.test(q) || /^[0-9a-fA-F]{64}$/.test(q)) {
            window.location.href = "/profile/" + encodeURIComponent(q);
            return;
        }
        if (/^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$/.test(q)) {
            window.location.href = "/profile/" + encodeURIComponent(q);
            return;
        }
        if (/^(note|nevent)1[0-9a-z]{10,}$/i.test(q)) {
            const hex = decodeEventId(q);
            window.location.href = "/feed?thread=" + (hex || encodeURIComponent(q));
            return;
        }
    }

    function showGlobalPopover() {
        const p = document.getElementById("search-results-popover");
        const legacy = document.getElementById("search-results-dropdown");
        if (p) p.classList.remove("hidden");
        if (legacy) legacy.classList.add("hidden");
    }

    function hideGlobalPopover() {
        const p = document.getElementById("search-results-popover");
        if (p) p.classList.add("hidden");
    }

    function renderGlobalResults(results) {
        const list = document.getElementById("search-results-list");
        if (!list) return;
        list.innerHTML = "";
        const items = results || [];
        if (items.length === 0) {
            list.innerHTML = '<div class="px-3 py-3 text-center text-slate-400">No global directory matches for this query.</div>';
            showGlobalPopover();
            return;
        }
        items.forEach(function (p) {
            const pk = p.pubkey;
            const prof = (typeof p.content === "string") ? (function () { try { return JSON.parse(p.content); } catch (e) { return {}; } })() : {};
            const name = prof.name || prof.display_name || pk.slice(0, 8);
            const display = prof.display_name || prof.name || "";
            const handle = prof.nip05 || "";
            const avatar = prof.picture || "";
            const initialChar = (name[0] || "N").toUpperCase();
            const avatarHtml = avatar
                ? '<img src="' + avatar + '" alt="" class="w-7 h-7 rounded-full object-cover border border-slate-200 dark:border-slate-700 shrink-0">'
                : '<div class="w-7 h-7 rounded-full bg-violet-100 dark:bg-violet-950 text-violet-600 dark:text-violet-400 font-bold flex items-center justify-center text-[10px] shrink-0">' + initialChar + '</div>';

            const item = document.createElement("div");
            item.className = "flex items-center gap-2.5 px-2.5 py-2 rounded-lg hover:bg-slate-50 dark:hover:bg-slate-800/70 transition-colors";
            item.innerHTML =
                avatarHtml +
                '<div class="flex-1 min-w-0">' +
                '<div class="font-semibold text-slate-800 dark:text-slate-200 text-xs truncate">' + name + '</div>' +
                '<div class="text-[10px] text-slate-400 truncate">' + (handle || pk.slice(0, 12)) + '</div>' +
                '</div>' +
                '<a href="/profile/' + pk + '" class="px-2 py-1 bg-violet-600 hover:bg-violet-500 text-white rounded text-[10px] font-semibold shrink-0">[ View Profile ]</a>';

            list.appendChild(item);
        });
        showGlobalPopover();
    }

    function queryGlobalDirectory(query) {
        // NIP-50 SEARCH against indexing directory relays
        const q = (query || "").trim();
        if (q.length < 2) {
            hideGlobalPopover();
            return;
        }
        const subId = "gsearch_" + Math.random().toString(36).substring(2, 10);
        const filter = { kinds: [0], search: q, limit: 6 };
        const collected = {};
        let remaining = GLOBAL_DIRECTORY_RELAYS.length;

        function finish() {
            const results = Object.keys(collected).map(function (k) { return collected[k]; });
            renderGlobalResults(results);
        }

        GLOBAL_DIRECTORY_RELAYS.forEach(function (relayUrl) {
            let ws;
            try {
                ws = new WebSocket(relayUrl);
            } catch (e) {
                remaining--;
                return;
            }
            const timer = setTimeout(function () {
                try { ws.close(); } catch (e) {}
                remaining--;
                if (remaining <= 0) finish();
            }, 3000);

            ws.onopen = function () {
                try { ws.send(JSON.stringify(["REQ", subId, filter])); } catch (e) {}
            };
            ws.onmessage = function (ev) {
                try {
                    const msg = JSON.parse(ev.data);
                    if (msg[0] === "EVENT" && msg[1] === subId && msg[2]) {
                        const eid = msg[2].id || "";
                        if (eid && !collected[eid]) collected[eid] = msg[2];
                    } else if (msg[0] === "EOSE" && msg[1] === subId) {
                        clearTimeout(timer);
                        try { ws.close(); } catch (e) {}
                        remaining--;
                        if (remaining <= 0) finish();
                    }
                } catch (e) {}
            };
            ws.onerror = function () {
                clearTimeout(timer);
                try { ws.close(); } catch (e) {}
                remaining--;
                if (remaining <= 0) finish();
            };
            ws.onclose = function () {
                remaining--;
                if (remaining <= 0) finish();
            };
        });
    }

    function initGlobalDirectorySearch() {
        const input = document.getElementById("feed-search-input");
        if (!input) return;

        let debounceTimer = null;

        input.addEventListener("keydown", function (e) {
            if (e.key === "Enter") {
                const val = input.value.trim();
                if (isIdentifierLike(val)) {
                    // Intercept identifier routing before feed-search handler
                    e.preventDefault();
                    if (e.stopImmediatePropagation) e.stopImmediatePropagation();
                    routeGlobalQuery(val);
                } else {
                    hideGlobalPopover();
                }
            } else if (e.key === "Escape") {
                hideGlobalPopover();
            }
        }, true); // capture phase so identifier routing takes precedence

        input.addEventListener("input", function () {
            const val = input.value.trim();
            if (debounceTimer) clearTimeout(debounceTimer);
            debounceTimer = setTimeout(function () {
                if (val.length >= 2) {
                    queryGlobalDirectory(val);
                } else {
                    hideGlobalPopover();
                }
            }, 350);
        });

        document.addEventListener("click", function (e) {
            const popover = document.getElementById("search-results-popover");
            const listEl = document.getElementById("search-results-list");
            if (popover && e.target !== input && (!listEl || !popover.contains(e.target))) {
                hideGlobalPopover();
            }
        });
    }

    // Persona Switcher & Composer Active Badge Listener
    window.addEventListener('persona:changed', function (e) {
        var profile = e.detail;
        if (!profile) return;
        var composerBadge = document.getElementById('composer-active-persona-badge');
        if (composerBadge) {
            var level = profile.level !== undefined ? profile.level : profile.derivation_index;
            var levelStr = (level === 1) ? 'L1' : (level ? 'L' + level : 'L2');
            var nameStr = profile.name || profile.profile_name || (profile.handle ? '@' + profile.handle : 'Primary');
            composerBadge.textContent = 'Posting as: ' + nameStr + ' (' + levelStr + ')';
        }
    });

    // Jump to Top button visibility & initialization listener
    document.addEventListener('DOMContentLoaded', function() {
        // Phase 34 — Instant Shell progressive hydration: if the server rendered
        // an empty shell (marked data-hydrate), kick off the background stream
        // fetch immediately on DOMContentLoaded for fast perceived load.
        fetchInitialFeedStream();

        // Apply "Read More" clamping to server-rendered note bodies
        checkAndApplyClamping(document);

        // Hydrate local timestamps on server-rendered cards
        hydrateLocalTimestamps(document);

        initGlobalDirectorySearch();

        var topBtn = document.getElementById('jump-to-top-btn');
        if (topBtn) {
            window.addEventListener('scroll', function() {
                if (window.scrollY > 400) {
                    topBtn.classList.remove('opacity-0', 'translate-y-4', 'pointer-events-none');
                    topBtn.classList.add('opacity-100', 'translate-y-0', 'pointer-events-auto');
                } else {
                    topBtn.classList.add('opacity-0', 'translate-y-4', 'pointer-events-none');
                    topBtn.classList.remove('opacity-100', 'translate-y-0', 'pointer-events-auto');
                }
            }, { passive: true });
        }
    });

    if (document.readyState === "complete" || document.readyState === "interactive") {
        hydrateLocalTimestamps(document);
    }
})();

