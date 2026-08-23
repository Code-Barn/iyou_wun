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
        var button = document.getElementById("postButton");
        var textSpan = document.getElementById("postButtonText");
        var loadingSpan = document.getElementById("postButtonLoading");
        if (button) button.disabled = loading;
        if (textSpan) { loadingSpan && loading ? textSpan.classList.add("hidden") : textSpan.classList.remove("hidden"); }
        if (loadingSpan) { loading ? loadingSpan.classList.remove("hidden") : loadingSpan.classList.add("hidden"); }
    }

    // ---------- NIP-10 Threading: Reply Editor ----------

    function showReplyEditor(rootId) {
        var editor = document.getElementById("reply-editor-" + rootId);
        var trigger = document.getElementById("reply-trigger-" + rootId);
        if (editor) editor.classList.remove("hidden");
        if (trigger) trigger.classList.add("hidden");
        var textarea = document.getElementById("reply-content-" + rootId);
        if (textarea) textarea.focus();
    }

    function cancelReply(rootId) {
        var editor = document.getElementById("reply-editor-" + rootId);
        var trigger = document.getElementById("reply-trigger-" + rootId);
        var textarea = document.getElementById("reply-content-" + rootId);
        if (editor) editor.classList.add("hidden");
        if (trigger) trigger.classList.remove("hidden");
        if (textarea) textarea.value = "";
        pendingReply = null;
        window.pendingReply = null;
    }

    async function submitReply(rootId, parentPubkey) {
        var textarea = document.getElementById("reply-content-" + rootId);
        var btn = document.getElementById("reply-btn-" + rootId);
        if (!textarea || !textarea.value.trim()) return;

        var pk;
        try { pk = await bridgeClient.getEffectivePubkey(); }
        catch (e) { showToast(e.message, true); return; }

        var timestamp = Math.floor(Date.now() / 1000);
        var tags = [
            ["e", rootId, "", "root"],
            ["e", rootId, "", "reply"],
            ["p", parentPubkey, ""],
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
                showToast("Reply posted.");
                appendReplyToThread(signedEvent, rootId);
            } else {
                showToast("Failed to broadcast reply.", true);
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
            repliesDiv.className = "thread-replies ml-6 pl-4 border-l-2 border-indigo-200 space-y-4";
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

        replyEl.innerHTML = '<div class="flex items-start gap-4">' +
            '<div class="flex-shrink-0">' +
            '<div class="w-10 h-10 bg-indigo-100 rounded-full flex items-center justify-center">' +
            '<span class="text-indigo-600 font-mono text-sm">Y</span>' +
            '</div></div>' +
            '<div class="flex-1 min-w-0">' +
            '<div class="flex items-center gap-2 mb-2">' +
            '<span class="font-semibold text-gray-900">' + npub + '</span>' +
            '<span class="author-badge-slot" data-author-slot="' + escapeAttr(event.pubkey) + '"></span>' +
            '<span class="bg-gray-100 text-gray-600 text-xs font-medium px-2 py-0.5 rounded-full">Reply</span>' +
            '<span class="text-xs text-gray-500">' + formattedDate + '</span>' +
            '</div>' +
            '<p class="text-gray-700 whitespace-pre-wrap">' + escapeHtml(event.content) + '</p>' +
            '</div></div>';

        repliesDiv.appendChild(replyEl);
        var textarea = document.getElementById("reply-content-" + rootId);
        if (textarea) textarea.value = "";
        cancelReply(rootId);
        if (window.trustLens && typeof window.trustLens.scan === "function") {
            window.trustLens.scan(repliesDiv);
        }
    }

    // ---------- Optimistic Feed Insert ----------

    function addNoteToFeed(event) {
        var container = document.getElementById("feedContainer");
        if (!container) return;

        var wrapper = document.createElement("div");
        var noteElement = document.createElement("div");
        noteElement.className = "thread-root border border-gray-200 rounded-lg p-6 hover:shadow-md transition-shadow";
        noteElement.setAttribute("data-kind", event.kind);
        noteElement.setAttribute("data-note-id", event.id);
        noteElement.setAttribute("data-pubkey", event.pubkey);
        noteElement.setAttribute("data-created-at", event.created_at);

        var date = new Date(event.created_at * 1000);
        var formattedDate = date.toLocaleString();
        var npub = window.userNpub || (window.userPubkey ? window.userPubkey.substring(0, 12) + "..." : "You");

        if (event.kind === 1063) {
            var tags = event.tags || [];
            var urlTag = tags.find(function (t) { return t[0] === "url"; });
            var mimeTag = tags.find(function (t) { return t[0] === "m"; });
            var url = urlTag ? urlTag[1] : "";
            var mime = mimeTag ? mimeTag[1] : "";
            var mediaHtml = "";
            if (mime.indexOf("image") !== -1) {
                mediaHtml = '<div class="mb-3 rounded-lg overflow-hidden bg-gray-100"><img src="' + url + '" alt="" class="w-full h-auto max-h-96 object-contain" loading="lazy" /></div>';
            } else if (mime.indexOf("video") !== -1) {
                mediaHtml = '<div class="mb-3 rounded-lg overflow-hidden bg-gray-100"><video src="' + url + '" controls class="w-full max-h-96" preload="metadata"></video></div>';
            } else if (mime.indexOf("audio") !== -1) {
                mediaHtml = '<div class="mb-3"><audio src="' + url + '" controls class="w-full" preload="metadata"></audio></div>';
            } else {
                mediaHtml = '<div class="mb-3 p-4 bg-gray-50 rounded-lg border border-gray-200"><a href="' + url + '" target="_blank" rel="noopener noreferrer" class="text-indigo-600 hover:text-indigo-800 underline break-all">' + escapeHtml(url) + '</a></div>';
            }
            noteElement.innerHTML = '<div class="flex items-start gap-4">' +
                '<div class="flex-shrink-0"><div class="w-10 h-10 bg-violet-100 rounded-full flex items-center justify-center"><span class="text-violet-600 font-mono text-sm">M</span></div></div>' +
                '<div class="flex-1 min-w-0">' +
                '<div class="flex items-center gap-2 mb-2">' +
                '<span class="font-semibold text-gray-900">' + npub + '</span>' +
                '<span class="author-badge-slot" data-author-slot="' + escapeAttr(event.pubkey) + '"></span>' +
                '<span class="bg-amber-100 text-amber-800 text-xs font-medium px-2 py-0.5 rounded-full">Sovereign</span>' +
                '<span class="text-xs text-gray-500">' + formattedDate + '</span>' +
                '</div>' + mediaHtml +
                (event.content ? '<p class="text-gray-700 whitespace-pre-wrap mb-2">' + escapeHtml(event.content) + '</p>' : '') +
                '</div></div>';
        } else {
            noteElement.innerHTML = '<div class="flex items-start gap-4">' +
                '<div class="flex-shrink-0"><div class="w-10 h-10 bg-indigo-100 rounded-full flex items-center justify-center"><span class="text-indigo-600 font-mono text-sm">Y</span></div></div>' +
                '<div class="flex-1 min-w-0">' +
                '<div class="flex items-center gap-2 mb-2">' +
                '<span class="font-semibold text-gray-900">' + npub + '</span>' +
                '<span class="author-badge-slot" data-author-slot="' + escapeAttr(event.pubkey) + '"></span>' +
                '<span class="bg-green-100 text-green-800 text-xs font-medium px-2 py-0.5 rounded-full">Verified</span>' +
                '<span class="text-xs text-gray-500">' + formattedDate + '</span>' +
                '</div>' +
                '<p class="text-gray-700 whitespace-pre-wrap">' + escapeHtml(event.content) + '</p>' +
                '</div></div>';
        }

        var editorWrap = document.createElement("div");
        editorWrap.className = "ml-6 pl-4 border-l-2 border-transparent";
        editorWrap.id = "reply-editor-wrap-" + event.id;
        editorWrap.innerHTML = '<div class="flex items-start gap-3 hidden" id="reply-editor-' + event.id + '">' +
            '<div class="flex-shrink-0 mt-2"><div class="w-8 h-8 bg-indigo-100 rounded-full flex items-center justify-center"><span class="text-indigo-600 font-mono text-xs">Y</span></div></div>' +
            '<div class="flex-1">' +
            '<textarea id="reply-content-' + event.id + '" class="w-full border border-gray-300 rounded-lg px-4 py-3 text-gray-700 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent resize-none text-sm" rows="2" placeholder="Write a reply..."></textarea>' +
            '<div class="flex items-center gap-2 mt-2">' +
            '<button onclick="cancelReply(\'' + event.id + '\')" class="text-xs text-gray-500 hover:text-gray-700 transition-colors">Cancel</button>' +
            '<button onclick="submitReply(\'' + event.id + '\', \'' + event.pubkey + '\')" class="bg-indigo-600 hover:bg-indigo-700 text-white text-xs font-medium px-4 py-1.5 rounded-lg transition-colors" id="reply-btn-' + event.id + '">Reply</button>' +
            '</div></div></div>' +
            '<button onclick="showReplyEditor(\'' + event.id + '\')" class="text-xs text-gray-500 hover:text-indigo-600 font-medium transition-colors mt-1" id="reply-trigger-' + event.id + '">\u21a9 Reply</button>';

        wrapper.appendChild(noteElement);
        wrapper.appendChild(editorWrap);

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
    }

    // ---------- Append Note from JSON API ----------

    function appendNoteToFeed(note, container, repliesMap) {
        var wrapper = document.createElement("div");
        var el = document.createElement("div");
        el.className = "thread-root border border-gray-200 rounded-lg p-6 hover:shadow-md transition-shadow";
        el.setAttribute("data-kind", note.kind);
        el.setAttribute("data-note-id", note.id);
        el.setAttribute("data-pubkey", note.pubkey);
        el.setAttribute("data-created-at", Math.floor(note.created_at));
        var date = new Date(note.created_at * 1000);
        var formattedDate = date.toLocaleString();
        var npub = note.npub || note.pubkey.substring(0, 12) + "...";

        if (note.kind === 1) {
            el.innerHTML = '<div class="flex items-start gap-4">' +
                '<div class="flex-shrink-0">' +
                (note.author_avatar ? '<img src="' + note.author_avatar + '" alt="' + escapeAttr(note.author_name) + '" class="w-10 h-10 rounded-full object-cover" />' :
                    '<div class="w-10 h-10 bg-indigo-100 rounded-full flex items-center justify-center"><span class="text-indigo-600 font-mono text-sm">' + (note.author_name || "N").charAt(0).toUpperCase() + '</span></div>') +
                '</div>' +
                '<div class="flex-1 min-w-0">' +
                '<div class="flex items-center gap-2 mb-2">' +
                '<a href="/profile/' + npub + '/" class="font-semibold text-gray-900 hover:text-indigo-600">' + escapeHtml(note.author_name || npub) + '</a>' +
                '<span class="author-badge-slot" data-author-slot="' + escapeAttr(note.pubkey) + '"></span>' +
                '<span class="bg-green-100 text-green-800 text-xs font-medium px-2 py-0.5 rounded-full">Verified</span>' +
                '<span class="text-xs text-gray-500">' + formattedDate + '</span>' +
                '</div>' +
                '<p class="text-gray-700 whitespace-pre-wrap">' + escapeHtml(note.content) + '</p>' +
                (note.reactions && note.reactions.length ? '<div class="flex items-center gap-4 mt-3 pt-3 border-t border-gray-100"><span class="flex items-center gap-1 text-sm text-pink-600">\u2764\ufe0f ' + note.reactions.length + '</span></div>' : '') +
                (note.reply_count ? '<div class="flex items-center gap-4 mt-3 pt-3 border-t border-gray-100"><span class="flex items-center gap-1 text-sm text-indigo-600 font-medium">\ud83d\udcac ' + note.reply_count + '</span></div>' : '') +
                '</div></div>';
        } else if (note.kind === 1063) {
            var mime = (note.mime_type || "").toLowerCase();
            var mediaHtml = "";
            if (mime.indexOf("image") !== -1) {
                mediaHtml = '<div class="mb-3 rounded-lg overflow-hidden bg-gray-100"><img src="' + note.file_url + '" alt="" class="w-full h-auto max-h-96 object-contain" loading="lazy" /></div>';
            } else if (mime.indexOf("video") !== -1) {
                mediaHtml = '<div class="mb-3 rounded-lg overflow-hidden bg-gray-100"><video src="' + note.file_url + '" controls class="w-full max-h-96" preload="metadata"></video></div>';
            } else if (mime.indexOf("audio") !== -1) {
                mediaHtml = '<div class="mb-3"><audio src="' + note.file_url + '" controls class="w-full" preload="metadata"></audio></div>';
            } else {
                mediaHtml = '<div class="mb-3 p-4 bg-gray-50 rounded-lg border border-gray-200"><a href="' + note.file_url + '" target="_blank" rel="noopener noreferrer" class="text-indigo-600 hover:text-indigo-800 underline break-all">' + escapeHtml(note.file_url) + '</a></div>';
            }
            var badge = note.is_sovereign ? "Sovereign" : "Verified";
            var badgeClass = note.is_sovereign ? "bg-amber-100 text-amber-800" : "bg-green-100 text-green-800";
            el.innerHTML = '<div class="flex items-start gap-4">' +
                '<div class="flex-shrink-0">' +
                (note.author_avatar ? '<img src="' + note.author_avatar + '" alt="' + escapeAttr(note.author_name) + '" class="w-10 h-10 rounded-full object-cover" />' :
                    '<div class="w-10 h-10 bg-violet-100 rounded-full flex items-center justify-center"><span class="text-violet-600 font-mono text-sm">M</span></div>') +
                '</div>' +
                '<div class="flex-1 min-w-0">' +
                '<div class="flex items-center gap-2 mb-2">' +
                '<a href="/profile/' + npub + '/" class="font-semibold text-gray-900 hover:text-indigo-600">' + escapeHtml(note.author_name || npub) + '</a>' +
                '<span class="author-badge-slot" data-author-slot="' + escapeAttr(note.pubkey) + '"></span>' +
                '<span class="' + badgeClass + ' text-xs font-medium px-2 py-0.5 rounded-full">' + badge + '</span>' +
                '<span class="text-xs text-gray-500">' + formattedDate + '</span>' +
                '</div>' +
                mediaHtml +
                (note.content ? '<p class="text-gray-700 whitespace-pre-wrap mb-2">' + escapeHtml(note.content) + '</p>' : '') +
                '</div></div>';
        } else if (note.kind === 30023) {
            el.setAttribute("data-poll-id", note.id);
            el.setAttribute("data-poll-pubkey", note.pubkey || "");
            el.setAttribute("data-poll-dtag", note.poll_d_tag || "");
            var pollOptions = note.poll_options || [];
            var optionsHtml = "";
            if (window.userPubkey) {
                optionsHtml = '<form class="poll-vote-form" data-poll-id="' + escapeHtml(note.id) + '"><div class="space-y-2">';
                for (var oi = 0; oi < pollOptions.length; oi++) {
                    optionsHtml += '<label class="flex items-center gap-3 p-3 border border-gray-200 rounded-lg cursor-pointer hover:bg-amber-50 transition-colors">' +
                        '<input type="radio" name="selection" value="' + escapeHtml(pollOptions[oi]) + '" class="accent-amber-600">' +
                        '<span class="text-sm text-gray-700">' + escapeHtml(pollOptions[oi]) + '</span></label>';
                }
                optionsHtml += '</div><button type="submit" class="mt-3 bg-amber-600 hover:bg-amber-700 text-white text-sm font-medium px-5 py-2 rounded-lg transition-colors">Cast Vote</button></form>';
            } else {
                optionsHtml = '<div class="space-y-2 opacity-60">';
                for (var oi = 0; oi < pollOptions.length; oi++) {
                    optionsHtml += '<div class="flex items-center gap-3 p-3 border border-gray-200 rounded-lg bg-gray-50">' +
                        '<span class="w-4 h-4 rounded-full border-2 border-gray-300 inline-block"></span>' +
                        '<span class="text-sm text-gray-500">' + escapeHtml(pollOptions[oi]) + '</span></div>';
                }
                optionsHtml += '</div>';
            }
            el.innerHTML = '<div class="flex items-start gap-4">' +
                '<div class="flex-shrink-0">' +
                (note.author_avatar ? '<img src="' + note.author_avatar + '" alt="' + escapeAttr(note.author_name || "") + '" class="w-10 h-10 rounded-full object-cover hover:ring-2 hover:ring-amber-300" />' :
                    '<div class="w-10 h-10 bg-amber-100 rounded-full flex items-center justify-center hover:ring-2 hover:ring-amber-300"><span class="text-amber-600 font-mono text-sm">P</span></div>') +
                '</div>' +
                '<div class="flex-1 min-w-0">' +
                '<div class="flex items-center gap-2 mb-2">' +
                '<a href="/profile/' + npub + '/" class="font-semibold text-gray-900 hover:text-indigo-600">' + escapeHtml(note.author_name || npub) + '</a>' +
                '<span class="author-badge-slot" data-author-slot="' + escapeAttr(note.pubkey) + '"></span>' +
                '<span class="bg-amber-100 text-amber-800 text-xs font-medium px-2 py-0.5 rounded-full">Poll</span>' +
                '<span class="text-xs text-gray-500">' + formattedDate + '</span>' +
                '</div>' +
                '<p class="text-gray-900 font-medium mb-3">' + escapeHtml(note.content) + '</p>' +
                optionsHtml +
                '</div></div>';
        }

        wrapper.appendChild(el);

        var noteReplies = (repliesMap && repliesMap[note.id]) || note.replies || [];
        if (noteReplies.length > 0) {
            var repliesDiv = document.createElement("div");
            repliesDiv.className = "thread-replies ml-6 pl-4 border-l-2 border-indigo-200 space-y-4";
            repliesDiv.id = "replies-" + note.id;
            repliesDiv.setAttribute("data-parent-id", note.id);
            noteReplies.forEach(function (reply) {
                var replyEl = document.createElement("div");
                replyEl.className = "thread-reply";
                replyEl.setAttribute("data-kind", "1111");
                replyEl.setAttribute("data-note-id", reply.id);
                replyEl.setAttribute("data-pubkey", reply.pubkey);
                replyEl.setAttribute("data-parent-id", note.id);
                var rDate = new Date(reply.created_at * 1000);
                var rNpub = reply.npub || reply.pubkey.substring(0, 12) + "...";
                replyEl.innerHTML = '<div class="flex items-start gap-4">' +
                    '<div class="flex-shrink-0">' +
                    (reply.author_avatar ? '<img src="' + reply.author_avatar + '" alt="' + escapeAttr(reply.author_name) + '" class="w-10 h-10 rounded-full object-cover" />' :
                        '<div class="w-10 h-10 bg-indigo-100 rounded-full flex items-center justify-center"><span class="text-indigo-600 font-mono text-sm">' + (reply.author_name || "R").charAt(0).toUpperCase() + '</span></div>') +
                    '</div>' +
                    '<div class="flex-1 min-w-0">' +
                    '<div class="flex items-center gap-2 mb-2">' +
                    '<a href="/profile/' + rNpub + '/" class="font-semibold text-gray-900 hover:text-indigo-600">' + escapeHtml(reply.author_name || rNpub) + '</a>' +
                    '<span class="author-badge-slot" data-author-slot="' + escapeAttr(reply.pubkey) + '"></span>' +
                    '<span class="bg-gray-100 text-gray-600 text-xs font-medium px-2 py-0.5 rounded-full">Reply</span>' +
                    '<span class="text-xs text-gray-500">' + rDate.toLocaleString() + '</span>' +
                    '</div>' +
                    '<p class="text-gray-700 whitespace-pre-wrap">' + escapeHtml(reply.content) + '</p>' +
                    '</div></div>';
                repliesDiv.appendChild(replyEl);
            });
            wrapper.appendChild(repliesDiv);
        } else if (note.reply_count) {
            var showBtn = document.createElement("div");
            showBtn.className = "ml-6 pl-4 border-l-2 border-indigo-200";
            showBtn.innerHTML = '<button onclick="toggleReplies(\'' + note.id + '\')" class="text-sm text-indigo-600 hover:text-indigo-800 font-medium transition-colors" id="toggle-replies-' + note.id + '">Show ' + note.reply_count + ' repl' + (note.reply_count === 1 ? "y" : "ies") + '</button>';
            wrapper.appendChild(showBtn);
        }

        var editorWrap = document.createElement("div");
        editorWrap.className = "ml-6 pl-4 border-l-2 border-transparent";
        editorWrap.id = "reply-editor-wrap-" + note.id;
        editorWrap.innerHTML = '<div class="flex items-start gap-3 hidden" id="reply-editor-' + note.id + '">' +
            '<div class="flex-shrink-0 mt-2"><div class="w-8 h-8 bg-indigo-100 rounded-full flex items-center justify-center"><span class="text-indigo-600 font-mono text-xs">Y</span></div></div>' +
            '<div class="flex-1">' +
            '<textarea id="reply-content-' + note.id + '" class="w-full border border-gray-300 rounded-lg px-4 py-3 text-gray-700 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent resize-none text-sm" rows="2" placeholder="Write a reply..."></textarea>' +
            '<div class="flex items-center gap-2 mt-2">' +
            '<button onclick="cancelReply(\'' + note.id + '\')" class="text-xs text-gray-500 hover:text-gray-700 transition-colors">Cancel</button>' +
            '<button onclick="submitReply(\'' + note.id + '\', \'' + note.pubkey + '\')" class="bg-indigo-600 hover:bg-indigo-700 text-white text-xs font-medium px-4 py-1.5 rounded-lg transition-colors" id="reply-btn-' + note.id + '">Reply</button>' +
            '</div></div></div>' +
            '<button onclick="showReplyEditor(\'' + note.id + '\')" class="text-xs text-gray-500 hover:text-indigo-600 font-medium transition-colors mt-1" id="reply-trigger-' + note.id + '">\u21a9 Reply</button>';
        wrapper.appendChild(editorWrap);

        container.appendChild(wrapper);

        if (note.kind === 30023) {
            var newForm = el.querySelector(".poll-vote-form");
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

        if (window.trustLens && typeof window.trustLens.scan === "function") {
            window.trustLens.scan(container);
        }
    }

    // ---------- Load More ----------

    function loadMoreNotes() {
        var container = document.getElementById("feedContainer");
        if (!container) return;
        var roots = container.querySelectorAll(".thread-root");
        if (roots.length === 0) return;
        var lastRoot = roots[roots.length - 1];
        var until = lastRoot.getAttribute("data-created-at");
        if (!until) return;

        var btn = document.getElementById("loadMoreBtn");
        var spinner = document.getElementById("loadMoreSpinner");
        var endMsg = document.getElementById("loadMoreEnd");
        if (btn) btn.classList.add("hidden");
        if (spinner) spinner.classList.remove("hidden");

        var mode = new URLSearchParams(window.location.search).get("mode") || "network";
        fetch("/api/feed?until=" + until + "&mode=" + mode)
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (spinner) spinner.classList.add("hidden");
                var newNotes = data.notes || [];
                var newReplies = data.replies || {};
                if (newNotes.length === 0) {
                    if (endMsg) endMsg.classList.remove("hidden");
                    return;
                }
                newNotes.forEach(function (note) { appendNoteToFeed(note, container, newReplies); });
                if (btn) btn.classList.remove("hidden");
            })
            .catch(function () {
                if (spinner) spinner.classList.add("hidden");
                if (btn) btn.classList.remove("hidden");
            });
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
            var tags = [
                ["url", uploadedUrl],
                ["x", hash],
                ["m", file.type || "application/octet-stream"],
            ];
            if (file.size) {
                tags.push(["size", String(file.size)]);
            }

            var event = {
                kind: 1063,
                content: "",
                pubkey: pk,
                created_at: Math.floor(Date.now() / 1000),
                tags: tags,
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

    // ---------- Global Click (close gear dropdowns) ----------

    document.addEventListener("click", function () {
        document.querySelectorAll(".gear-dropdown").forEach(function (d) { d.classList.add("hidden"); });
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
    });

    // ---------- Public API ----------

    window.postToNostr = postToNostr;
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
    window.castPollVote = castPollVote;
    window.openPollModal = openPollModal;
    window.closePollModal = closePollModal;
    window.addPollOption = addPollOption;
    window.removeOption = removeOption;
    window.createPoll = createPoll;
})();
