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

    window.pendingReply = null;


    // ---------- Post (Kind 1) ----------

    async function postToNostr() {
        var content = document.getElementById("postContent");
        if (!content || !content.value.trim()) {
            showToast("Please enter some content to post.", true);
            return;
        }
        var pk;
        try { pk = await bridgeClient.getEffectivePubkey(); }
        catch (e) { showToast(e.message, true); return; }
        setButtonLoading(true);
        bridgeClient.isProcessing = true;
        var event = {
            kind: 1,
            content: content.value.trim(),
            pubkey: pk,
            created_at: Math.floor(Date.now() / 1000),
            tags: [],
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
            });
        }
    }

    window.handleSignedEvent = handleSignedEvent;

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
            if (url) {
                var type = "file";
                if (mime.indexOf("image") !== -1 || /\.(png|jpg|jpeg|gif|webp|svg)(\?.*)?$/i.test(url)) {
                    type = "image";
                } else if (mime.indexOf("video") !== -1 || /\.(mp4|webm|mov|m4v)(\?.*)?$/i.test(url)) {
                    type = "video";
                } else if (mime.indexOf("audio") !== -1 || /\.(mp3|ogg|wav|m4a|flac)(\?.*)?$/i.test(url)) {
                    type = "audio";
                }
                attachments.push({ type: type, url: url });
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

    // ---------- Template Builder for Cards ----------

    function buildCardHtml(note) {
        if (!note) return "";
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

        var date = new Date((note.created_at || (Date.now() / 1000)) * 1000);
        var formattedDate = date.toLocaleDateString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
        var reactionLikeCount = (note.like_count && note.like_count > 0) ? String(note.like_count) : ((note.reactions && note.reactions.length) ? String(note.reactions.length) : "Like");
        var repliesCount = (note.reply_count && note.reply_count > 0) ? String(note.reply_count) : "Reply";
        var repostCount = note.repost_count ? String(note.repost_count) : "Repost";

        var mediaInfo = extractMediaFromNote(note);
        var mediaAttachments = mediaInfo.attachments || [];
        var displayContent = note.display_content !== undefined ? (note.display_content != null ? String(note.display_content) : "") : (mediaInfo.displayContent != null ? String(mediaInfo.displayContent) : "");

        var mediaHtml = "";
        if (mediaAttachments && mediaAttachments.length > 0) {
            mediaHtml = '<div class="mt-3 space-y-2">';
            mediaAttachments.forEach(function (media) {
                if (!media || !media.url) return;
                var mUrl = escapeAttr(media.url);
                if (media.type === "image") {
                    mediaHtml += '<div class="rounded-xl overflow-hidden border border-slate-200 dark:border-slate-800 bg-slate-950/20 max-h-[500px]">' +
                        '<img src="' + mUrl + '" alt="Attached visual" loading="lazy" class="w-full h-full object-contain max-h-[500px] hover:scale-[1.01] transition-transform duration-200 cursor-pointer" onclick="openImageModal(\'' + mUrl + '\')" />' +
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

        var avatarHtml = authorAvatar ?
            '<img src="' + escapeAttr(authorAvatar) + '" alt="' + escapeAttr(authorName) + '" class="w-10 h-10 rounded-full object-cover border border-slate-200 dark:border-slate-700 hover:ring-2 hover:ring-violet-400 transition" />' :
            '<div class="w-10 h-10 bg-violet-100 dark:bg-violet-950/60 rounded-full flex items-center justify-center border border-violet-200 dark:border-violet-800"><span class="text-violet-600 dark:text-violet-400 font-mono text-sm font-bold">' + escapeHtml((authorName || "N").charAt(0).toUpperCase()) + '</span></div>';

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

        var replyDrawerHtml = '<div id="reply-box-' + escapeAttr(noteId) + '" class="hidden mt-3 pt-3 border-t border-slate-100 dark:border-slate-800">' +
            '<div class="flex items-start gap-2.5">' +
            '<textarea id="reply-input-' + escapeAttr(noteId) + '" class="w-full bg-slate-50 dark:bg-slate-950 border border-slate-200 dark:border-slate-800 rounded-lg p-2.5 text-xs text-slate-800 dark:text-slate-100 placeholder-slate-400 focus:outline-none focus:border-violet-500 focus:ring-1 focus:ring-violet-500 transition resize-none" rows="2" placeholder="Write a sovereign reply..."></textarea>' +
            '<div class="flex flex-col gap-1.5 flex-shrink-0">' +
            '<button type="button" id="reply-btn-' + escapeAttr(noteId) + '" class="px-3 py-1.5 bg-violet-600 hover:bg-violet-500 text-white rounded text-xs font-mono font-medium transition" onclick="submitReply(\'' + escapeAttr(noteId) + '\', \'' + escapeAttr(pubkey) + '\')">Reply</button>' +
            '<button type="button" class="px-3 py-1 text-slate-500 hover:text-slate-700 dark:hover:text-slate-300 text-xs font-mono transition" onclick="cancelReply(\'' + escapeAttr(noteId) + '\')">Cancel</button>' +
            '</div></div></div>';

        return '<div class="flex items-start gap-3.5 sm:gap-4 relative group" data-note-card-id="' + escapeAttr(noteId) + '">' +
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
            '<a href="/feed?thread=' + encodeURIComponent(noteId) + '" class="text-xs text-slate-400 hover:text-violet-500 dark:hover:text-violet-400 font-mono whitespace-nowrap transition" title="View full conversation thread">' + formattedDate + '</a>' +
            '<div class="relative kebab-menu-wrap">' +
            '<button type="button" class="kebab-toggle-btn text-slate-400 hover:text-slate-200 p-1 rounded hover:bg-slate-100 dark:hover:bg-slate-800 transition" aria-label="Post actions" onclick="toggleKebabMenu(event)">' +
            '<svg class="w-4 h-4" fill="currentColor" viewBox="0 0 20 20"><path d="M10 6a2 2 0 110-4 2 2 0 010 4zM10 12a2 2 0 110-4 2 2 0 010 4zM10 18a2 2 0 110-4 2 2 0 010 4z"></path></svg>' +
            '</button>' +
            '<div class="kebab-dropdown hidden absolute right-0 top-full mt-1 w-52 rounded-lg bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 shadow-2xl py-1 text-xs font-mono z-40">' +
            '<button type="button" class="w-full text-left px-3 py-2 text-slate-700 dark:text-slate-200 hover:bg-violet-50 dark:hover:bg-violet-950/50 hover:text-violet-600 dark:hover:text-violet-400 flex items-center gap-2" onclick="suggestToDev(\'' + escapeAttr(noteId) + '\', \'' + escapeAttr(pubkey) + '\', \'' + snippetEscaped + '\')">💡 Suggest to Dev</button>' +
            '<button type="button" class="w-full text-left px-3 py-2 text-slate-700 dark:text-slate-200 hover:bg-amber-50 dark:hover:bg-amber-950/50 hover:text-amber-600 dark:hover:text-amber-400 flex items-center gap-2" onclick="nominatePostOfTheDay(\'' + escapeAttr(noteId) + '\', \'' + escapeAttr(pubkey) + '\')">🏆 Post of the Day</button>' +
            '<button type="button" class="w-full text-left px-3 py-2 text-slate-700 dark:text-slate-200 hover:bg-emerald-50 dark:hover:bg-emerald-950/50 hover:text-emerald-600 dark:hover:text-emerald-400 flex items-center gap-2" onclick="setEnclavePetname(\'' + escapeAttr(pubkey) + '\', \'' + escapeAttr(authorName) + '\')">🛡️ Set Enclave Petname</button>' +
            '<div class="border-t border-slate-100 dark:border-slate-800 my-1"></div>' +
            '<button type="button" class="w-full text-left px-3 py-1.5 text-slate-500 hover:text-slate-800 dark:hover:text-slate-300 flex items-center gap-2" onclick="viewRawEventJson(\'' + escapeAttr(noteId) + '\')">📄 View Raw JSON</button>' +
            '<button type="button" class="w-full text-left px-3 py-1.5 text-slate-500 hover:text-slate-800 dark:hover:text-slate-300 flex items-center gap-2" onclick="copyNotePermalink(\'' + escapeAttr(noteId) + '\')">🔗 Copy Event ID / Link</button>' +
            '</div></div></div></div>' +
            replyingToHtml +
            (displayContent ? '<div class="note-text-content text-slate-800 dark:text-slate-200 text-sm leading-relaxed whitespace-pre-wrap break-words">' + escapeHtml(displayContent) + '</div>' : (noteContent && (!mediaAttachments || !mediaAttachments.length) ? '<div class="note-text-content text-slate-800 dark:text-slate-200 text-sm leading-relaxed whitespace-pre-wrap break-words">' + escapeHtml(noteContent) + '</div>' : '')) +
            mediaHtml +
            '<div class="flex items-center justify-between gap-1 sm:gap-4 mt-3 pt-2.5 border-t border-slate-100 dark:border-slate-800/80 text-xs font-mono text-slate-500 dark:text-slate-400 select-none">' +
            '<button type="button" class="action-btn-reply flex items-center gap-1.5 hover:text-violet-600 dark:hover:text-violet-400 transition-colors px-2 py-1 rounded hover:bg-slate-100 dark:hover:bg-slate-800/50" onclick="showReplyEditor(\'' + escapeAttr(noteId) + '\')"><span>💬</span><span class="action-count reply-count-label">' + repliesCount + '</span></button>' +
            '<button type="button" class="action-btn-repost flex items-center gap-1.5 hover:text-emerald-600 dark:hover:text-emerald-400 transition-colors px-2 py-1 rounded hover:bg-slate-100 dark:hover:bg-slate-800/50" onclick="repostNote(\'' + escapeAttr(noteId) + '\', \'' + escapeAttr(pubkey) + '\')"><span>🔁</span><span class="action-count repost-count-label">' + repostCount + '</span></button>' +
            '<button type="button" class="action-btn-like flex items-center gap-1.5 hover:text-pink-600 dark:hover:text-pink-400 transition-colors px-2 py-1 rounded hover:bg-slate-100 dark:hover:bg-slate-800/50" onclick="likeNote(\'' + escapeAttr(noteId) + '\', \'' + escapeAttr(pubkey) + '\')"><span class="heart-icon">❤️</span><span class="action-count like-count-label">' + reactionLikeCount + '</span></button>' +
            ((note.kind === 30023 || note.is_proposal || note.lud16) ? '<button type="button" class="action-btn-contextual flex items-center gap-1.5 text-amber-600 dark:text-amber-400 hover:bg-amber-50 dark:hover:bg-amber-950/40 px-2 py-1 rounded transition-colors font-semibold" onclick="handleContextualAction(\'' + escapeAttr(noteId) + '\', \'' + escapeAttr(note.kind) + '\', \'' + escapeAttr(note.lud16 || '') + '\')"><span>' + ((note.kind === 30023 || note.is_proposal) ? '🗳️ Vote' : '⚡ Tip') + '</span></button>' : '') +
            '<button type="button" class="action-btn-share flex items-center gap-1.5 hover:text-blue-600 dark:hover:text-blue-400 transition-colors px-2 py-1 rounded hover:bg-slate-100 dark:hover:bg-slate-800/50" onclick="shareNote(\'' + escapeAttr(noteId) + '\')"><span>↗️</span><span class="hidden sm:inline">Share</span></button>' +
            '</div>' +
            replyDrawerHtml +
            '</div></div>';
    }

    // ---------- Optimistic Feed Insert ----------

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

        if (window.trustLens && typeof window.trustLens.scan === "function") {
            window.trustLens.scan(container);
        }

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
        var circle = urlParams.get("circle") || "global";
        var mode = urlParams.get("mode") || (circle === "global" ? "global" : "network");
        var tag = urlParams.get("tag") || "";
        var activeCircleBtn = document.querySelector(".circle-tab.active, .circle-tab[data-active='true']");
        if (activeCircleBtn && activeCircleBtn.dataset && activeCircleBtn.dataset.circle) {
            circle = activeCircleBtn.dataset.circle;
        }

        var until = parseInt(oldestTimestamp, 10) - 1;
        var queryUrl = "/api/feed?until=" + until + "&limit=25&circle=" + encodeURIComponent(circle) + "&mode=" + encodeURIComponent(mode);
        if (tag) {
            queryUrl += "&tag=" + encodeURIComponent(tag);
        }

        fetch(queryUrl)
            .then(function (r) { return r.json(); })
            .then(function (data) {
                var notes = data.notes || [];
                var repliesMap = data.replies || {};

                if (notes.length === 0 || data.has_more === false) {
                    if (btn) btn.classList.add("hidden");
                    if (endMsg) endMsg.classList.remove("hidden");
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

    function initFeedPaginationObserver() {
        var sentinel = document.getElementById("feed-pagination-sentinel");
        if (!sentinel || typeof IntersectionObserver === "undefined") return;

        var observer = new IntersectionObserver(function (entries) {
            entries.forEach(function (entry) {
                if (entry.isIntersecting) {
                    loadMoreNotes();
                }
            });
        }, {
            root: null,
            rootMargin: "300px",
            threshold: 0.1
        });

        observer.observe(sentinel);
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
        var formData = new FormData();
        formData.append("file", file);
        if (hash) formData.append("sha256", hash);
        var headers = {};
        var csrf = getCsrfToken();
        if (csrf) {
            headers["X-CSRFToken"] = csrf;
        }
        var res = await fetch("/api/media/upload/", {
            method: "POST",
            headers: headers,
            body: formData,
        });
        if (!res.ok) {
            throw new Error("Server proxy upload failed with status " + res.status);
        }
        return await res.json();
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

    async function handleMediaSelected(file) {
        if (!file) return;
        setUploadStatus("Hashing...");
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
                        if (typeof showToast === "function") {
                            showToast("Media upload offline; drafting event with hash.", true);
                        }
                    }
                }
            }

            if (!uploadedUrl) {
                uploadedUrl = baseUrl + "/" + hash;
            }

            setUploadStatus("Requesting signature...");
            var pk;
            try {
                pk = await bridgeClient.getEffectivePubkey();
            } catch (e) {
                setUploadStatus(e.message);
                setTimeout(function () {
                    var el = document.getElementById("uploadStatus");
                    if (el) el.classList.add("hidden");
                }, 3000);
                return;
            }

            bridgeClient.isProcessing = true;
            var mimeType = file.type || "application/octet-stream";
            var mimePrefix = "file";
            if (mimeType.indexOf("image") !== -1) mimePrefix = "image";
            else if (mimeType.indexOf("video") !== -1) mimePrefix = "video";
            else if (mimeType.indexOf("audio") !== -1) mimePrefix = "audio";

            var tags = [
                ["url", uploadedUrl],
                ["x", hash],
                ["m", mimeType],
            ];
            if (file.size) {
                tags.push(["size", String(file.size)]);
            }

            var event = {
                kind: 1063,
                content: "",
                display_content: "",
                pubkey: pk,
                created_at: Math.floor(Date.now() / 1000),
                tags: tags,
                media_attachments: [
                    { type: mimePrefix, url: uploadedUrl, hash: hash, mime: mimeType }
                ]
            };
            bridgeClient.signEvent(event);

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
        if (btn) btn.classList.add("text-pink-600", "dark:text-pink-400", "font-bold");
        if (countLabel) {
            var curr = parseInt(countLabel.textContent, 10);
            countLabel.textContent = isNaN(curr) ? "1" : String(curr + 1);
        }

        showToast("Reaction published to mesh", "heart");

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

        showToast("Note reposted to mesh relays", "repost");

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

    function suggestToDev(noteId, authorPubkey, snippet) {
        var url = "https://dev.iyou.me/suggest?event_id=" + encodeURIComponent(noteId || "") +
            "&author=" + encodeURIComponent(authorPubkey || "") +
            "&snippet=" + encodeURIComponent(snippet || "") +
            "&ref=iyou_wun";
        window.open(url, "_blank");
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

    function shareNote(noteId) {
        var permalink = window.location.origin + "/feed?thread=" + encodeURIComponent(noteId);
        if (navigator.share) {
            navigator.share({
                title: "Nostr Note on iyou_wun",
                url: permalink
            }).catch(function () {
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
    window.appendNoteToFeed = appendNoteToFeed;
    window.loadMoreNotes = loadMoreNotes;
    window.getBlossomBaseUrl = getBlossomBaseUrl;
    window.handleMediaSelected = handleMediaSelected;
    window.toggleGear = toggleGear;
    window.toggleKebabMenu = toggleKebabMenu;
    window.likeNote = likeNote;
    window.repostNote = repostNote;
    window.suggestToDev = suggestToDev;
    window.nominatePostOfTheDay = nominatePostOfTheDay;
    window.setEnclavePetname = setEnclavePetname;
    window.viewRawEventJson = viewRawEventJson;
    window.copyNotePermalink = copyNotePermalink;
    window.shareNote = shareNote;
    window.handleContextualAction = handleContextualAction;
    window.castPollVote = castPollVote;
    window.openPollModal = openPollModal;
    window.openPollCreateModal = openPollModal;
    window.closePollModal = closePollModal;
    window.addPollOption = addPollOption;
    window.removeOption = removeOption;
    window.createPoll = createPoll;
})();

