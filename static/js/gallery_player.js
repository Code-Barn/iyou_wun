/**
 * gallery_player.js — Media & Lightbox Controller (Phase 25)
 * Handles tab switching, Plyr.js video viewports, single-instance media coordination,
 * custom audio deck with vinyl scrubber, keyboard navigation, and cursor-based infinite scroll.
 */
(function () {
    "use strict";

    // ---------- State ----------
    var currentTab = "all";
    var lightboxCards = [];
    var lightboxIndex = 0;
    var activeMedia = null;
    var _isLoadingMore = false;
    var _paginationObserver = null;

    function escapeHtml(str) {
        if (!str) return "";
        return String(str)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");
    }

    function escapeAttr(str) {
        if (!str) return "";
        return String(str)
            .replace(/&/g, "&amp;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#39;");
    }

    // ---------- Tab Switching ----------

    function switchGalleryTab(tab) {
        currentTab = tab;
        stopActiveMedia();

        var url = new URL(window.location);
        url.searchParams.set("type", tab);
        history.replaceState(null, "", url);

        document.querySelectorAll(".tab-btn").forEach(function (btn) {
            var isActive = btn.getAttribute("data-tab") === tab;
            btn.className = "tab-btn flex-shrink-0 px-5 py-2.5 text-sm font-semibold rounded-full transition-all duration-200 " +
                (isActive ? "tab-active" : "tab-inactive bg-gray-800 hover:bg-gray-700");
        });

        document.querySelectorAll(".gallery-panel").forEach(function (p) { p.classList.add("hidden"); });
        var panel = document.getElementById("panel-" + tab);
        if (panel) panel.classList.remove("hidden");

        // Re-evaluate sentinel visibility and trigger load if needed
        checkSentinel();
    }

    // ---------- Single-Instance Media Coordinator ----------

    function stopActiveMedia(except) {
        // 1. Lightbox active media
        if (activeMedia) {
            if (activeMedia.player && activeMedia.player !== except && typeof activeMedia.player.pause === "function") {
                try { activeMedia.player.pause(); } catch (e) {}
            } else if (activeMedia.element && activeMedia.element !== except && typeof activeMedia.element.pause === "function") {
                try { activeMedia.element.pause(); } catch (e) {}
            }
            if (activeMedia.player !== except && activeMedia.element !== except) {
                activeMedia = null;
            }
        }

        // 2. Pause all Plyr video players
        document.querySelectorAll("video.gallery-video-player").forEach(function (vid) {
            if (vid._plyr && vid._plyr !== except) {
                try { vid._plyr.pause(); } catch (e) {}
            } else if (vid !== except && !vid.paused) {
                try { vid.pause(); } catch (e) {}
            }
        });

        // 3. Pause all plain HTML5 audio elements
        document.querySelectorAll("audio").forEach(function (aud) {
            if (aud !== except && !aud.paused) {
                try { aud.pause(); } catch (e) {}
            }
        });

        // 4. Reset audio play buttons & vinyl discs
        document.querySelectorAll(".audio-play-btn").forEach(function (btn) {
            var src = btn.getAttribute("data-src");
            var aud = document.querySelector('audio[data-src="' + src + '"]');
            if (!aud || aud.paused) {
                var span = btn.querySelector("span");
                if (span) span.innerHTML = "&#9654;";
                var card = btn.closest(".gallery-card");
                if (card) {
                    var vinyl = card.querySelector(".vinyl-disc");
                    if (vinyl) vinyl.classList.remove("animate-spin-slow");
                }
            }
        });
    }

    // ---------- Plyr Video Initialization ----------

    function initPlyrPlayers(container) {
        if (typeof Plyr === "undefined") return;
        var root = container || document;
        var videoEls = root.querySelectorAll("video.gallery-video-player");
        videoEls.forEach(function (el) {
            if (el._plyr) return;
            try {
                var player = new Plyr(el, {
                    controls: ["play-large", "play", "progress", "current-time", "mute", "volume", "fullscreen"],
                    tooltips: { controls: true, seek: true },
                    keyboard: { focused: false, global: false }
                });
                el._plyr = player;
                player.on("play", function () {
                    stopActiveMedia(player);
                    activeMedia = { player: player, type: "plyr_video", element: el };
                });
                player.on("ended", function () {
                    if (activeMedia && activeMedia.player === player) activeMedia = null;
                });
            } catch (e) {
                console.warn("Plyr init error:", e);
            }
        });
    }

    // ---------- Inline Audio Player & Deck ----------

    function toggleAudioPlayer(src, btn) {
        if (!src) return;
        var existing = document.querySelector('audio[data-src="' + src + '"]');
        var audio;
        if (existing) {
            audio = existing;
        } else {
            audio = document.createElement("audio");
            audio.src = src;
            audio.dataset.src = src;
            audio.preload = "auto";
            document.body.appendChild(audio);
        }

        var card = btn ? btn.closest(".gallery-card") : null;
        var vinyl = card ? card.querySelector(".vinyl-disc") : null;

        if (audio.paused) {
            stopActiveMedia(audio);
            audio.play().then(function () {
                if (btn) {
                    var span = btn.querySelector("span");
                    if (span) span.innerHTML = "&#9646;&#9646;";
                }
                if (vinyl) vinyl.classList.add("animate-spin-slow");
                activeMedia = { element: audio, type: "audio", button: btn, card: card };
            }).catch(function (err) {
                console.warn("Audio playback prevented:", err);
            });

            audio.ontimeupdate = function () {
                var scrubbers = document.querySelectorAll('.scrubber[data-src="' + src + '"]');
                var times = document.querySelectorAll('.audio-current[data-src="' + src + '"]');
                if (audio.duration && !isNaN(audio.duration)) {
                    scrubbers.forEach(function (s) {
                        if (!s._isDragging) {
                            s.value = (audio.currentTime / audio.duration) * 100;
                        }
                    });
                }
                times.forEach(function (t) {
                    var m = Math.floor(audio.currentTime / 60);
                    var s = Math.floor(audio.currentTime % 60);
                    t.textContent = m + ":" + (s < 10 ? "0" : "") + s;
                });
            };

            audio.onended = function () {
                if (btn) {
                    var span = btn.querySelector("span");
                    if (span) span.innerHTML = "&#9654;";
                }
                if (vinyl) vinyl.classList.remove("animate-spin-slow");
                if (activeMedia && activeMedia.element === audio) activeMedia = null;
            };
        } else {
            audio.pause();
            if (btn) {
                var span = btn.querySelector("span");
                if (span) span.innerHTML = "&#9654;";
            }
            if (vinyl) vinyl.classList.remove("animate-spin-slow");
            if (activeMedia && activeMedia.element === audio) activeMedia = null;
        }
    }

    function initScrubbers(container) {
        var root = container || document;
        root.querySelectorAll(".scrubber").forEach(function (scrubber) {
            if (scrubber._bound) return;
            scrubber._bound = true;
            scrubber.addEventListener("mousedown", function () { this._isDragging = true; });
            scrubber.addEventListener("touchstart", function () { this._isDragging = true; });
            scrubber.addEventListener("input", function () {
                var src = this.getAttribute("data-src");
                var audio = document.querySelector('audio[data-src="' + src + '"]');
                if (audio && audio.duration && !isNaN(audio.duration)) {
                    audio.currentTime = (this.value / 100) * audio.duration;
                }
            });
            scrubber.addEventListener("mouseup", function () { this._isDragging = false; });
            scrubber.addEventListener("touchend", function () { this._isDragging = false; });
        });
    }

    // ---------- Lightbox Controller ----------

    function collectLightboxCards() {
        var activePanel = document.getElementById("panel-" + currentTab);
        if (!activePanel) return [];
        return Array.from(activePanel.querySelectorAll(".gallery-card"));
    }

    function openLightbox(card) {
        if (!card) return;
        lightboxCards = collectLightboxCards();
        lightboxIndex = lightboxCards.indexOf(card);
        if (lightboxIndex === -1) lightboxIndex = 0;
        renderLightbox();
        var modal = document.getElementById("lightboxModal");
        if (modal) {
            modal.classList.add("show");
            document.body.classList.add("modal-open");
        }
    }

    function closeLightbox(e) {
        if (e && e.target && e.target.id !== "lightboxModal" && e.target !== document.getElementById("lightboxModal") && !e.target.classList.contains("close-lb-btn")) {
            return;
        }
        stopActiveMedia();
        var modal = document.getElementById("lightboxModal");
        if (modal) modal.classList.remove("show");
        document.body.classList.remove("modal-open");
        var pane = document.getElementById("lbMediaPane");
        if (pane) pane.innerHTML = "";
    }

    function navigateLightbox(dir) {
        if (lightboxCards.length === 0) return;
        stopActiveMedia();
        lightboxIndex = (lightboxIndex + dir + lightboxCards.length) % lightboxCards.length;
        renderLightbox();
    }

    function renderLightbox() {
        var card = lightboxCards[lightboxIndex];
        if (!card) return;
        var mediaPane = document.getElementById("lbMediaPane");
        if (!mediaPane) return;
        mediaPane.innerHTML = "";

        var type = card.getAttribute("data-type") || card.getAttribute("data-media-type");
        var url = card.getAttribute("data-url");
        var alt = card.getAttribute("data-alt") || "";
        var author = card.getAttribute("data-author") || "";
        var avatar = card.getAttribute("data-avatar") || "";
        var date = card.getAttribute("data-date") || "";
        var dims = card.getAttribute("data-dims") || "";
        var hash = card.getAttribute("data-hash") || "";
        var dur = card.getAttribute("data-dur") || "";
        var sovereign = card.getAttribute("data-sovereign") === "True" || card.getAttribute("data-sovereign") === "true";

        if (type === "image") {
            var img = document.createElement("img");
            img.src = url;
            img.alt = alt;
            img.className = "max-w-full max-h-[80vh] object-contain rounded-lg";
            mediaPane.appendChild(img);
        } else if (type === "video") {
            var vidWrap = document.createElement("div");
            vidWrap.className = "w-full max-w-4xl plyr-video-container aspect-video";
            var vid = document.createElement("video");
            vid.src = url;
            vid.controls = true;
            vid.autoplay = true;
            vid.playsInline = true;
            vid.className = "gallery-video-player w-full h-full object-cover";
            vidWrap.appendChild(vid);
            mediaPane.appendChild(vidWrap);
            if (typeof Plyr !== "undefined") {
                try {
                    var plyrInst = new Plyr(vid, { controls: ["play-large", "play", "progress", "current-time", "mute", "volume", "fullscreen"] });
                    vid._plyr = plyrInst;
                    activeMedia = { player: plyrInst, type: "video", element: vid };
                } catch (e) {
                    activeMedia = { element: vid, type: "video" };
                }
            } else {
                activeMedia = { element: vid, type: "video" };
            }
        } else if (type === "audio") {
            var wrap = document.createElement("div");
            wrap.className = "text-center p-8 flex flex-col items-center justify-center";
            var icon = document.createElement("div");
            icon.className = "text-7xl mb-6 vinyl-disc animate-spin-slow";
            icon.textContent = "🎵";
            var aud = document.createElement("audio");
            aud.src = url;
            aud.controls = true;
            aud.autoplay = true;
            aud.className = "w-full max-w-md mt-4";
            wrap.appendChild(icon);
            wrap.appendChild(aud);
            mediaPane.appendChild(wrap);
            activeMedia = { element: aud, type: "audio" };
        } else {
            var link = document.createElement("a");
            link.href = url;
            link.target = "_blank";
            link.className = "text-violet-400 text-lg underline hover:text-violet-300";
            link.textContent = "Open file ↗";
            mediaPane.appendChild(link);
        }

        var authorHtml = "";
        if (avatar) {
            authorHtml += '<img src="' + escapeAttr(avatar) + '" class="w-10 h-10 rounded-full object-cover" alt="">';
        }
        authorHtml += '<div><p class="text-sm text-white font-medium">' + escapeHtml(author) + '</p>';
        authorHtml += '<p class="text-xs text-gray-500 font-mono">' + escapeHtml(date) + '</p></div>';
        if (sovereign) {
            authorHtml += '<span class="ml-auto bg-amber-900/50 text-amber-300 text-xs px-2 py-0.5 rounded-full font-mono">Sovereign</span>';
        }
        var lbAuth = document.getElementById("lbAuthor");
        if (lbAuth) lbAuth.innerHTML = authorHtml;

        var lbCap = document.getElementById("lbCaption");
        if (lbCap) lbCap.textContent = alt || "No caption";

        var metaHtml = "";
        if (dims) metaHtml += '<div class="flex justify-between font-mono"><span>Dimensions</span><span class="text-gray-300">' + escapeHtml(dims) + '</span></div>';
        if (dur) metaHtml += '<div class="flex justify-between font-mono"><span>Duration</span><span class="text-gray-300">' + escapeHtml(dur) + 's</span></div>';
        if (hash) metaHtml += '<div class="flex justify-between font-mono"><span>SHA-256</span><span class="text-gray-300 font-mono text-xs break-all">' + escapeHtml(hash) + '</span></div>';
        metaHtml += '<div class="flex justify-between font-mono"><span>Type</span><span class="text-gray-300">' + escapeHtml(card.getAttribute("data-mime") || type) + '</span></div>';
        if (url) metaHtml += '<div class="mt-3"><a href="' + escapeAttr(url) + '" target="_blank" rel="noopener noreferrer" class="text-violet-400 hover:text-violet-300 text-xs underline font-mono">Open original ↗</a></div>';
        var lbMeta = document.getElementById("lbMeta");
        if (lbMeta) lbMeta.innerHTML = metaHtml;

        var prevBtn = document.getElementById("lbPrev");
        var nextBtn = document.getElementById("lbNext");
        if (prevBtn) prevBtn.style.display = lightboxCards.length > 1 ? "" : "none";
        if (nextBtn) nextBtn.style.display = lightboxCards.length > 1 ? "" : "none";
    }

    // ---------- Keyboard Navigation Coordinator ----------

    document.addEventListener("keydown", function (e) {
        var tag = e.target ? e.target.tagName.toLowerCase() : "";
        if (tag === "input" || tag === "textarea" || (e.target && e.target.isContentEditable)) {
            return;
        }

        var modal = document.getElementById("lightboxModal");
        var isModalOpen = modal && modal.classList.contains("show");

        // 1. Escape: Close Lightbox
        if (e.key === "Escape" && isModalOpen) {
            closeLightbox({ target: modal });
            return;
        }

        // 2. Spacebar: Play / Pause Coordinator
        if (e.code === "Space" || e.keyCode === 32) {
            if (activeMedia) {
                e.preventDefault();
                if (activeMedia.player && typeof activeMedia.player.togglePlay === "function") {
                    activeMedia.player.togglePlay();
                } else if (activeMedia.element) {
                    if (activeMedia.element.paused) {
                        activeMedia.element.play();
                        if (activeMedia.button) {
                            var s = activeMedia.button.querySelector("span");
                            if (s) s.innerHTML = "&#9646;&#9646;";
                        }
                        if (activeMedia.card) {
                            var v = activeMedia.card.querySelector(".vinyl-disc");
                            if (v) v.classList.add("animate-spin-slow");
                        }
                    } else {
                        activeMedia.element.pause();
                        if (activeMedia.button) {
                            var s = activeMedia.button.querySelector("span");
                            if (s) s.innerHTML = "&#9654;";
                        }
                        if (activeMedia.card) {
                            var v = activeMedia.card.querySelector(".vinyl-disc");
                            if (v) v.classList.remove("animate-spin-slow");
                        }
                    }
                }
            }
            return;
        }

        // 3. Mute / Unmute
        if (e.key === "m" || e.key === "M") {
            if (activeMedia) {
                if (activeMedia.player) {
                    activeMedia.player.muted = !activeMedia.player.muted;
                } else if (activeMedia.element) {
                    activeMedia.element.muted = !activeMedia.element.muted;
                }
            }
            return;
        }

        // 4. Arrow Left / Right Seek or Lightbox Navigation
        if (e.key === "ArrowLeft") {
            if (isModalOpen && (!activeMedia || (activeMedia.element && activeMedia.element.paused))) {
                navigateLightbox(-1);
            } else if (activeMedia) {
                e.preventDefault();
                if (activeMedia.player) {
                    activeMedia.player.currentTime = Math.max(0, activeMedia.player.currentTime - 5);
                } else if (activeMedia.element) {
                    activeMedia.element.currentTime = Math.max(0, activeMedia.element.currentTime - 5);
                }
            }
        } else if (e.key === "ArrowRight") {
            if (isModalOpen && (!activeMedia || (activeMedia.element && activeMedia.element.paused))) {
                navigateLightbox(1);
            } else if (activeMedia) {
                e.preventDefault();
                if (activeMedia.player) {
                    activeMedia.player.currentTime = Math.min(activeMedia.player.duration || 9999, activeMedia.player.currentTime + 5);
                } else if (activeMedia.element) {
                    activeMedia.element.currentTime = Math.min(activeMedia.element.duration || 9999, activeMedia.element.currentTime + 5);
                }
            }
        }
    });

    // ---------- Dynamic Card Builder for Infinite Scroll ----------

    function buildGalleryCardElement(note) {
        if (!note) return null;
        var card = document.createElement("div");
        var mType = note.media_type || "other";
        card.className = "gallery-media-card gallery-card group relative bg-gray-900 border border-gray-800 rounded-xl overflow-hidden hover:border-violet-500/50 transition-all duration-200" + (mType === "image" ? " masonry-item" : "");
        card.setAttribute("data-author-pubkey", note.pubkey_hex || note.pubkey || "");
        card.setAttribute("data-author-did", note.author_did || "");
        card.setAttribute("data-tags", note.tags_json || "");
        card.setAttribute("data-media-type", mType);
        card.setAttribute("data-type", mType);
        card.setAttribute("data-id", note.id || "");
        card.setAttribute("data-url", note.file_url || "");
        card.setAttribute("data-alt", escapeAttr(note.display_title || note.alt_text || note.content || ""));
        card.setAttribute("data-mime", note.mime_type || "");
        card.setAttribute("data-author", note.author_name || note.npub || "");
        card.setAttribute("data-avatar", note.author_avatar || "");
        card.setAttribute("data-date", note.created_at || "");
        card.setAttribute("data-dims", note.dimensions || "");
        card.setAttribute("data-hash", note.blossom_hash || "");
        card.setAttribute("data-dur", note.duration || "");
        card.setAttribute("data-npub", note.npub || "");
        card.setAttribute("data-pubkey", note.pubkey_hex || note.pubkey || "");
        card.setAttribute("data-sovereign", note.is_sovereign ? "true" : "false");

        var mediaHtml = "";
        if (mType === "image") {
            mediaHtml = '<div class="overflow-hidden cursor-pointer" onclick="openLightbox(this.closest(\'.gallery-card\'))"><img src="' + escapeAttr(note.thumbnail_url || note.file_url) + '" alt="' + escapeAttr(note.display_title || note.alt_text || '') + '" class="w-full h-auto object-cover group-hover:scale-105 transition-transform duration-300" loading="lazy"></div>';
        } else if (mType === "video") {
            mediaHtml = '<div class="plyr-video-container aspect-video bg-gray-950 overflow-hidden relative">' +
                '<video class="gallery-video-player w-full h-full object-cover" playsinline controls preload="metadata" data-poster="' + escapeAttr(note.thumbnail_url || '') + '">' +
                '<source src="' + escapeAttr(note.file_url) + '" type="' + escapeAttr(note.mime_type || 'video/mp4') + '" />' +
                '</video>' +
                (note.duration ? '<span class="absolute bottom-3 right-3 z-10 bg-black/80 text-white text-xs px-2 py-0.5 rounded font-mono pointer-events-none">' + note.duration + 's</span>' : '') +
                '</div>';
        } else if (mType === "audio") {
            mediaHtml = '<div class="flex items-center gap-4 p-4">' +
                '<div class="relative w-16 h-16 rounded-xl overflow-hidden flex-shrink-0 bg-gradient-to-br from-violet-900 to-indigo-950 flex items-center justify-center shadow-inner border border-violet-800/40 cursor-pointer" onclick="openLightbox(this.closest(\'.gallery-card\'))">' +
                (note.author_avatar ? '<img src="' + escapeAttr(note.author_avatar) + '" class="vinyl-disc w-full h-full object-cover rounded-xl" alt="">' : '<span class="vinyl-disc text-3xl">🎵</span>') +
                '</div>' +
                '<div class="min-w-0 flex-1">' +
                '<p class="text-sm text-white font-medium truncate">' + escapeHtml(note.display_title || note.content || note.alt_text || 'Audio Track') + '</p>' +
                '<div class="flex items-center gap-1.5 mt-1">' +
                '<a href="/profile/' + escapeAttr(note.npub) + '/" class="text-xs font-mono text-gray-400 hover:text-violet-400 truncate max-w-[120px]" title="' + escapeAttr(note.author_name || note.npub) + '">' +
                escapeHtml((note.author_name || note.npub || '').substring(0, 14)) +
                '</a>' +
                (note.nip05 ? '<span class="inline-flex items-center gap-0.5 text-[10px] text-violet-400 bg-violet-950/60 px-1 py-0.2 rounded border border-violet-800/60" title="' + escapeAttr(note.nip05) + '"><svg class="w-2.5 h-2.5 text-violet-400" fill="currentColor" viewBox="0 0 20 20"><path fill-rule="evenodd" d="M6.267 3.455a3.066 3.066 0 001.745-.723 3.066 3.066 0 013.976 0 3.066 3.066 0 012.812 2.812c.051.643.304 1.254.723 1.745a3.066 3.066 0 010 3.976 3.066 3.066 0 01-.723 1.745 3.066 3.066 0 01-2.812 2.812 3.066 3.066 0 00-1.745.723 3.066 3.066 0 01-3.976 0 3.066 3.066 0 00-1.745-.723 3.066 3.066 0 010-3.976 3.066 3.066 0 00.723-1.745 3.066 3.066 0 012.812-2.812zm7.44 5.252a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clip-rule="evenodd"></path></svg></span>' : '') +
                '<span class="author-badge-slot" data-author-slot="' + escapeAttr(note.pubkey_hex || note.pubkey) + '"></span>' +
                '</div>' +
                '<div class="flex items-center gap-2 mt-1">' +
                '<span class="text-xs text-gray-500 font-mono">' + escapeHtml(note.created_at || '') + '</span>' +
                (note.duration ? '<span class="text-xs text-gray-500 font-mono">' + note.duration + 's</span>' : '') +
                '</div></div></div>' +
                '<div class="px-4 pb-4">' +
                '<div class="bg-gray-950 rounded-xl p-3.5 flex items-center gap-3 border border-slate-800/80">' +
                '<button onclick="toggleAudioPlayer(\'' + escapeAttr(note.file_url) + '\', this)" class="audio-play-btn w-10 h-10 rounded-full bg-violet-600 hover:bg-violet-500 flex items-center justify-center flex-shrink-0 transition-colors shadow-lg shadow-violet-900/30" data-src="' + escapeAttr(note.file_url) + '"><span class="text-white text-lg ml-0.5">&#9654;</span></button>' +
                '<div class="flex-1 min-w-0">' +
                '<input type="range" min="0" max="100" value="0" class="scrubber audio-scrubber w-full h-1 appearance-none rounded-full bg-gray-800 cursor-pointer" data-src="' + escapeAttr(note.file_url) + '">' +
                '<div class="flex justify-between mt-1.5 font-mono text-[11px] text-gray-400">' +
                '<span class="audio-current" data-src="' + escapeAttr(note.file_url) + '">0:00</span>' +
                '<span>' + (note.duration ? note.duration + 's' : '--:--') + '</span>' +
                '</div></div></div></div>';
        } else {
            mediaHtml = '<div class="aspect-square bg-gray-800 flex items-center justify-center cursor-pointer" onclick="openLightbox(this.closest(\'.gallery-card\'))"><span class="text-4xl text-gray-500">📄</span></div>';
        }

        var footerHtml = '<div class="p-3 bg-slate-900/90 border-t border-slate-800 text-xs font-mono">' +
            '<div class="flex items-center justify-between gap-1.5 mb-1.5">' +
            '<div class="flex items-center gap-1.5 min-w-0">' +
            '<a href="/profile/' + escapeAttr(note.npub) + '/" class="font-semibold text-slate-200 hover:text-violet-400 truncate max-w-[130px]" title="' + escapeAttr(note.author_name || note.npub) + '">' +
            escapeHtml((note.author_name || note.npub || '').substring(0, 14)) +
            '</a>' +
            (note.nip05 ? '<span class="inline-flex items-center gap-0.5 text-[10px] text-violet-400 bg-violet-950/60 px-1 py-0.2 rounded border border-violet-800/60" title="' + escapeAttr(note.nip05) + '"><svg class="w-2.5 h-2.5 text-violet-400" fill="currentColor" viewBox="0 0 20 20"><path fill-rule="evenodd" d="M6.267 3.455a3.066 3.066 0 001.745-.723 3.066 3.066 0 013.976 0 3.066 3.066 0 012.812 2.812c.051.643.304 1.254.723 1.745a3.066 3.066 0 010 3.976 3.066 3.066 0 01-2.812 2.812 3.066 3.066 0 00-1.745.723 3.066 3.066 0 01-3.976 0 3.066 3.066 0 00-1.745-.723 3.066 3.066 0 010-3.976 3.066 3.066 0 00.723-1.745 3.066 3.066 0 012.812-2.812zm7.44 5.252a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clip-rule="evenodd"></path></svg></span>' : '') +
            '<span class="author-badge-slot" data-author-slot="' + escapeAttr(note.pubkey_hex || note.pubkey) + '"></span>' +
            '</div>' +
            '<span class="text-[10px] text-slate-500 whitespace-nowrap">' + escapeHtml(note.created_at || '') + '</span>' +
            '</div>' +
            (note.display_title || note.content ? '<p class="text-xs text-slate-300 font-sans line-clamp-2 leading-snug break-words">' + escapeHtml(note.display_title || note.content) + '</p>' : '') +
            '</div>';

        card.innerHTML = mediaHtml + footerHtml;
        return card;
    }

    // ---------- Cursor-Based Infinite Scroll ----------

    function loadMoreGalleryMedia() {
        if (_isLoadingMore) return;
        var sentinel = document.getElementById("gallery-pagination-sentinel");
        if (!sentinel) return;

        var hasMore = sentinel.getAttribute("data-has-more");
        if (hasMore === "false") return;

        var oldestTimestamp = sentinel.getAttribute("data-oldest-timestamp");
        if (!oldestTimestamp) return;

        var spinner = document.getElementById("gallery-loading-spinner");
        if (spinner) spinner.classList.remove("hidden");
        _isLoadingMore = true;

        var params = new URLSearchParams(window.location.search);
        var pubkey = params.get("pubkey") || "";

        var apiUrl = "/api/gallery?until=" + encodeURIComponent(oldestTimestamp) + "&type=" + encodeURIComponent(currentTab);
        if (pubkey) apiUrl += "&pubkey=" + encodeURIComponent(pubkey);

        fetch(apiUrl)
            .then(function (res) { return res.json(); })
            .then(function (data) {
                if (data.success && Array.isArray(data.media) && data.media.length > 0) {
                    var targetGridId = currentTab === "images" ? "imageGrid" :
                        (currentTab === "videos" ? "videoGrid" :
                        (currentTab === "audio" ? "audioGrid" : "allGrid"));
                    var container = document.getElementById(targetGridId);
                    if (container) {
                        data.media.forEach(function (item) {
                            var cardEl = buildGalleryCardElement(item);
                            if (cardEl) {
                                container.appendChild(cardEl);
                                initPlyrPlayers(cardEl);
                                initScrubbers(cardEl);
                            }
                        });
                    }

                    if (data.oldest_timestamp) {
                        sentinel.setAttribute("data-oldest-timestamp", data.oldest_timestamp);
                    }
                    sentinel.setAttribute("data-has-more", data.has_more ? "true" : "false");
                    if (!data.has_more) {
                        sentinel.style.display = "none";
                    }

                    if (window.TrustLens && typeof window.TrustLens.scanDOM === "function") {
                        window.TrustLens.scanDOM();
                    }
                } else {
                    sentinel.setAttribute("data-has-more", "false");
                    sentinel.style.display = "none";
                }
            })
            .catch(function (err) {
                console.warn("Failed to load more gallery media:", err);
            })
            .finally(function () {
                _isLoadingMore = false;
                if (spinner) spinner.classList.add("hidden");
            });
    }

    function checkSentinel() {
        var sentinel = document.getElementById("gallery-pagination-sentinel");
        if (sentinel && sentinel.getAttribute("data-has-more") !== "false") {
            sentinel.style.display = "";
        }
    }

    function initGalleryPaginationObserver() {
        var sentinel = document.getElementById("gallery-pagination-sentinel");
        if (!sentinel || typeof IntersectionObserver === "undefined") return;

        if (_paginationObserver) {
            _paginationObserver.disconnect();
        }

        _paginationObserver = new IntersectionObserver(function (entries) {
            if (entries[0] && entries[0].isIntersecting) {
                loadMoreGalleryMedia();
            }
        }, { rootMargin: "300px" });

        _paginationObserver.observe(sentinel);
    }

    // ---------- Initialization ----------

    document.addEventListener("DOMContentLoaded", function () {
        initPlyrPlayers(document);
        initScrubbers(document);
        initGalleryPaginationObserver();

        var params = new URLSearchParams(window.location.search);
        var type = params.get("type");
        if (type && ["all", "images", "videos", "audio"].indexOf(type) !== -1) {
            switchGalleryTab(type);
        }
    });

    // ---------- Public API ----------

    window.switchTab = switchGalleryTab;
    window.openLightbox = openLightbox;
    window.closeLightbox = closeLightbox;
    window.navigateLightbox = navigateLightbox;
    window.toggleAudioPlayer = toggleAudioPlayer;
    window.stopActiveMedia = stopActiveMedia;
    window.loadMoreGalleryMedia = loadMoreGalleryMedia;
    window.initPlyrPlayers = initPlyrPlayers;
})();
