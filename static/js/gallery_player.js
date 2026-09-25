/**
 * gallery_player.js — Media & Lightbox Controller (Phase 25 / 3-pane chassis)
 * Drives the canonical NIP-94 Blossom gallery lightbox (#lightbox-modal) plus
 * single-instance media coordination, keyboard navigation and Plyr viewports.
 *
 * - openLightbox(url, type, caption, authorDisplayName, authorHandle)
 *   string-first signature used by the 2-column masonry image cards.
 * - Cardinal-lightbox fallback: openLightbox(card) keeps legacy data-* cards
 *   working (infinite-scroll pipelines still emit them).
 */
(function () {
    "use strict";

    // ---------- State ----------
    var lightboxItems = [];
    var lightboxIndex = 0;
    var activeMedia = null;

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

    // ---------- Single-Instance Media Coordinator ----------

    function stopActiveMedia(except) {
        if (activeMedia) {
            var media = activeMedia.element || (activeMedia.player && activeMedia.player.media);
            if (media && media !== except && typeof media.pause === "function") {
                try { media.pause(); } catch (e) {}
            }
            activeMedia = null;
        }

        // Pause any Plyr-managed gallery viewports.
        document.querySelectorAll("video.gallery-video-player").forEach(function (vid) {
            if (vid._plyr && vid._plyr !== except) {
                try { vid._plyr.pause(); } catch (e) {}
            } else if (vid !== except && !vid.paused) {
                try { vid.pause(); } catch (e) {}
            }
        });

        // Pause all native video / audio elements (stream cards + lightbox).
        document.querySelectorAll("video, audio").forEach(function (el) {
            if (el !== except && !el.paused) {
                try { el.pause(); } catch (e) {}
            }
        });
    }

    // ---------- Plyr Video Initialization (kept for legacy slide-in decks) ----------

    function initPlyrPlayers(container) {
        if (typeof Plyr === "undefined") return;
        var root = container || document;
        root.querySelectorAll("video.gallery-video-player").forEach(function (el) {
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

    // ---------- Lightbox Modal Controls ----------

    function lbModal() {
        return document.getElementById("lightbox-modal");
    }

    function isModalOpen() {
        var modal = lbModal();
        return modal && !modal.classList.contains("hidden");
    }

    function openModal() {
        var modal = lbModal();
        if (!modal) return;
        modal.classList.remove("hidden");
        modal.classList.add("show");
        document.body.classList.add("modal-open");
    }

    function hideModal() {
        var modal = lbModal();
        if (!modal) return;
        modal.classList.add("hidden");
        modal.classList.remove("show");
        document.body.classList.remove("modal-open");
    }

    // ---------- Item Collection for Prev/Next ----------

    function collectLightboxItems(type) {
        var items = [];
        var container;
        if (type === "video") {
            container = document.getElementById("gallery-video-deck");
            if (container) {
                container.querySelectorAll(".rounded-2xl").forEach(function (card) {
                    var video = card.querySelector("video");
                    var captionEl = card.querySelector(".p-3 p");
                    var authorA = card.querySelector(".p-3 a");
                    var dateEl = card.querySelector(".p-3 span:last-child");
                    if (!video) return;
                    items.push({
                        url: video.getAttribute("src") || "",
                        type: "video",
                        caption: captionEl ? captionEl.textContent : "",
                        author: authorA ? authorA.textContent.replace(/^\s*@/, "") : "",
                        authorUrl: authorA ? authorA.getAttribute("href") : "",
                        date: dateEl ? dateEl.textContent.trim() : ""
                    });
                });
            }
        } else if (type === "audio") {
            container = document.getElementById("gallery-audio-deck");
            if (container) {
                container.querySelectorAll(".p-3.rounded-2xl").forEach(function (card) {
                    var aud = card.querySelector("audio");
                    var captionEl = card.querySelector(".truncate");
                    var authorA = card.querySelector("a");
                    if (!aud) return;
                    items.push({
                        url: aud.getAttribute("src") || "",
                        type: "audio",
                        caption: captionEl ? captionEl.textContent : "",
                        author: authorA ? authorA.textContent.replace(/^\s*@/, "") : "",
                        authorUrl: authorA ? authorA.getAttribute("href") : "",
                        date: ""
                    });
                });
            }
        } else {
            container = document.getElementById("gallery-image-grid");
            if (container) {
                container.querySelectorAll(".break-inside-avoid").forEach(function (card) {
                    var img = card.querySelector("img");
                    var authorA = card.querySelector(".p-2 a");
                    var dateEl = card.querySelector(".p-2 span");
                    if (!img) return;
                    items.push({
                        url: img.getAttribute("src") || "",
                        type: "image",
                        caption: img.getAttribute("alt") || "",
                        author: authorA ? authorA.textContent.replace(/^\s*@/, "") : "",
                        authorUrl: authorA ? authorA.getAttribute("href") : "",
                        date: dateEl ? dateEl.textContent.trim() : ""
                    });
                });
            }
        }
        return items.filter(function (it) { return it.url; });
    }

    // ---------- Lightbox Controller ----------

    function renderLightbox(item) {
        var mediaPane = document.getElementById("lbMediaPane");
        if (!mediaPane) return;
        mediaPane.innerHTML = "";

        var type = item.type || "image";
        var url = item.url || "";

        if (type === "image") {
            var img = document.createElement("img");
            img.src = url;
            img.alt = item.caption || "";
            img.className = "max-w-full max-h-[80vh] object-contain rounded-lg";
            mediaPane.appendChild(img);
        } else if (type === "video") {
            var vidWrap = document.createElement("div");
            vidWrap.className = "w-full max-w-4xl aspect-video";
            var vid = document.createElement("video");
            vid.src = url;
            vid.controls = true;
            vid.autoplay = true;
            vid.playsInline = true;
            vid.className = "w-full h-full object-contain bg-black rounded-lg";
            vidWrap.appendChild(vid);
            mediaPane.appendChild(vidWrap);
            activeMedia = { element: vid, type: "video" };
        } else if (type === "audio") {
            var wrap = document.createElement("div");
            wrap.className = "text-center p-8 flex flex-col items-center justify-center";
            var icon = document.createElement("div");
            icon.className = "text-7xl mb-6";
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
            link.rel = "noopener noreferrer";
            link.className = "text-violet-400 text-lg underline hover:text-violet-300";
            link.textContent = "Open file ↗";
            mediaPane.appendChild(link);
        }

        var authorHtml = "";
        if (item.author) {
            var name = item.author.replace(/^@/, "");
            if (item.authorUrl) {
                authorHtml += '<a href="' + escapeAttr(item.authorUrl) + '" class="text-sm text-white font-medium hover:text-violet-400">@' + escapeHtml(name) + '</a>';
            } else {
                authorHtml += '<p class="text-sm text-white font-medium">@' + escapeHtml(name) + '</p>';
            }
        }
        if (item.date) {
            authorHtml += '<p class="text-xs text-slate-400 font-mono pl-2 border-l border-slate-800">' + escapeHtml(item.date) + '</p>';
        }
        var lbAuthor = document.getElementById("lbAuthor");
        if (lbAuthor) lbAuthor.innerHTML = authorHtml;

        var lbCap = document.getElementById("lbCaption");
        if (lbCap) lbCap.textContent = item.caption || "No caption";

        var metaHtml = '<div class="flex justify-between font-mono"><span>Type</span><span class="text-slate-300">' + escapeHtml(type) + '</span></div>';
        if (url) metaHtml += '<div class="mt-2"><a href="' + escapeAttr(url) + '" target="_blank" rel="noopener noreferrer" class="text-violet-400 hover:text-violet-300 text-xs underline font-mono">Open original ↗</a></div>';
        var lbMeta = document.getElementById("lbMeta");
        if (lbMeta) lbMeta.innerHTML = metaHtml;

        var total = lightboxItems.length || 1;
        var counter = document.getElementById("lbCounter");
        if (counter) counter.textContent = (lightboxIndex + 1) + " / " + total;

        var prevBtn = document.getElementById("lbPrev");
        var nextBtn = document.getElementById("lbNext");
        if (prevBtn) prevBtn.style.display = total > 1 ? "" : "none";
        if (nextBtn) nextBtn.style.display = total > 1 ? "" : "none";
    }

    function openLightbox(url, type, caption, authorName, authorHandle) {
        // Legacy card-based invocation: openLightbox(card)
        if (typeof url === "object" && url !== null) {
            openLightboxFromCard(url);
            return;
        }
        if (!url) return;

        var itemType = type || "image";
        lightboxItems = collectLightboxItems(itemType);
        var idx = -1;
        for (var i = 0; i < lightboxItems.length; i++) {
            if (lightboxItems[i].url === url) { idx = i; break; }
        }
        if (idx === -1) {
            lightboxItems.push({
                url: url,
                type: itemType,
                caption: caption || "",
                author: authorHandle || authorName || "",
                authorUrl: authorHandle ? "/@" + authorHandle + "/" : "",
                date: ""
            });
            idx = lightboxItems.length - 1;
        }
        lightboxIndex = idx;

        stopActiveMedia();
        openModal();
        renderLightbox(lightboxItems[idx]);
    }

    function openLightboxFromCard(card) {
        if (!card) return;
        var url = card.getAttribute ? card.getAttribute("data-url") : card;
        if (!url && card.querySelector) {
            var img = card.querySelector("img");
            if (img) url = img.src;
        }
        if (!url) return;

        if (typeof window.openImageModal === "function") {
            window.openImageModal(url);
            return;
        }
        lightboxItems = collectLightboxItems(card.getAttribute("data-type") || "image");
        var idx = -1;
        for (var i = 0; i < lightboxItems.length; i++) {
            if (lightboxItems[i].url === url) { idx = i; break; }
        }
        lightboxIndex = idx === -1 ? 0 : idx;
        stopActiveMedia();
        openModal();
        renderLightbox(lightboxItems[lightboxIndex] || {
            url: url,
            type: card.getAttribute("data-type") || "image",
            caption: card.getAttribute("data-alt") || "",
            author: card.getAttribute("data-author") || "",
            date: card.getAttribute("data-date") || ""
        });
    }

    function closeLightbox(e) {
        if (e) {
            var target = e.target;
            if (!target) return;
            var isBackdrop = target.id === "lightbox-modal" || (typeof target.classList !== "undefined" && target.classList.contains("close-lb-btn"));
            if (!isBackdrop) return;
        }
        stopActiveMedia();
        hideModal();
    }

    function navigateLightbox(dir) {
        if (lightboxItems.length === 0) {
            return; // nothing to navigate
        }
        stopActiveMedia();
        lightboxIndex = (lightboxIndex + dir + lightboxItems.length) % lightboxItems.length;
        renderLightbox(lightboxItems[lightboxIndex]);
    }

    // ---------- Keyboard Navigation Coordinator ----------

    document.addEventListener("keydown", function (e) {
        var tag = e.target ? e.target.tagName.toLowerCase() : "";
        if (tag === "input" || tag === "textarea" || (e.target && e.target.isContentEditable)) {
            return;
        }

        var modalOpen = isModalOpen();

        // 1. Escape: Close Lightbox
        if (e.key === "Escape" && modalOpen) {
            closeLightbox({ target: lbModal() });
            return;
        }

        // Left / Right arrow navigation when lightbox is open
        if (modalOpen && (e.key === "ArrowLeft" || e.key === "ArrowRight")) {
            e.preventDefault();
            navigateLightbox(e.key === "ArrowLeft" ? -1 : 1);
            return;
        }

        // 2. Spacebar: Play / Pause Coordinator
        if (e.code === "Space" || e.keyCode === 32) {
            if (activeMedia) {
                e.preventDefault();
                var media = activeMedia.element || (activeMedia.player && activeMedia.player.media);
                if (activeMedia.player && typeof activeMedia.player.togglePlay === "function") {
                    activeMedia.player.togglePlay();
                } else if (media) {
                    if (media.paused) {
                        media.play();
                    } else {
                        media.pause();
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

        // 4. Arrow Left / Right Seek
        if (e.key === "ArrowLeft") {
            if (activeMedia && activeMedia.element && !activeMedia.element.paused) {
                e.preventDefault();
                activeMedia.element.currentTime = Math.max(0, activeMedia.element.currentTime - 5);
            }
        } else if (e.key === "ArrowRight") {
            if (activeMedia && activeMedia.element && !activeMedia.element.paused) {
                e.preventDefault();
                activeMedia.element.currentTime = Math.min(activeMedia.element.duration || 9999, activeMedia.element.currentTime + 5);
            }
        }
    });

    // ---------- Legacy Tab / Vinyl Deck Bridges ----------

    function switchGalleryTab(tab) {
        var url = new URL(window.location);
        if (tab === "all") url.searchParams.delete("type");
        else url.searchParams.set("type", String(tab).replace(/s$/, ""));
        window.location.href = url.toString();
    }

    function toggleAudioPlayer(src) {
        if (!src) return;
        stopActiveMedia();
        var audio = document.createElement("audio");
        audio.src = src;
        audio.autoplay = true;
        document.body.appendChild(audio);
        activeMedia = { element: audio, type: "audio" };
        audio.onended = function () { activeMedia = null; };
    }

    // ---------- Initialization ----------

    document.addEventListener("DOMContentLoaded", function () {
        initPlyrPlayers(document);
    });

    // ---------- Public API ----------

    window.switchTab = switchGalleryTab;
    window.openLightbox = openLightbox;
    window.closeLightbox = closeLightbox;
    window.navigateLightbox = navigateLightbox;
    window.toggleAudioPlayer = toggleAudioPlayer;
    window.stopActiveMedia = stopActiveMedia;
    window.initPlyrPlayers = initPlyrPlayers;
})();