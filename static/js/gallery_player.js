/**
 * gallery_player.js — Media & Lightbox Controller
 * Handles tab switching, single-instance media coordination, lightbox modal,
 * keyboard navigation, and inline audio player controls.
 *
 * Depends on: bridge_client.js (for URL state utilities)
 */
(function () {
    "use strict";

    // ---------- State ----------
    var currentTab = "all";
    var lightboxCards = [];
    var lightboxIndex = 0;
    var activeMedia = null;

    // ---------- Tab Switching ----------

    function switchGalleryTab(tab) {
        currentTab = tab;
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
    }

    // ---------- Lightbox ----------

    function collectLightboxCards() {
        var activePanel = document.getElementById("panel-" + currentTab);
        if (!activePanel) return [];
        return Array.from(activePanel.querySelectorAll(".gallery-card"));
    }

    function openLightbox(card) {
        lightboxCards = collectLightboxCards();
        lightboxIndex = lightboxCards.indexOf(card);
        if (lightboxIndex === -1) lightboxIndex = 0;
        renderLightbox();
        document.getElementById("lightboxModal").classList.add("show");
        document.body.classList.add("modal-open");
    }

    function closeLightbox(e) {
        if (e && e.target && e.target.id !== "lightboxModal" && e.target !== document.getElementById("lightboxModal")) return;
        stopActiveMedia();
        document.getElementById("lightboxModal").classList.remove("show");
        document.body.classList.remove("modal-open");
        document.getElementById("lbMediaPane").innerHTML = "";
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
        mediaPane.innerHTML = "";

        var type = card.getAttribute("data-type");
        var url = card.getAttribute("data-url");
        var alt = card.getAttribute("data-alt") || "";
        var author = card.getAttribute("data-author") || "";
        var avatar = card.getAttribute("data-avatar") || "";
        var date = card.getAttribute("data-date") || "";
        var dims = card.getAttribute("data-dims") || "";
        var hash = card.getAttribute("data-hash") || "";
        var dur = card.getAttribute("data-dur") || "";
        var sovereign = card.getAttribute("data-sovereign") === "True";

        // Render media pane
        if (type === "image") {
            var img = document.createElement("img");
            img.src = url;
            img.alt = alt;
            img.className = "max-w-full max-h-[80vh] object-contain rounded-lg";
            mediaPane.appendChild(img);
        } else if (type === "video") {
            var vid = document.createElement("video");
            vid.src = url;
            vid.controls = true;
            vid.autoplay = true;
            vid.className = "max-w-full max-h-[80vh] rounded-lg";
            mediaPane.appendChild(vid);
            activeMedia = { element: vid, type: "video" };
        } else if (type === "audio") {
            var wrap = document.createElement("div");
            wrap.className = "text-center p-8";
            var icon = document.createElement("div");
            icon.className = "text-7xl mb-6";
            icon.textContent = "\uD83C\uDFB5";
            var aud = document.createElement("audio");
            aud.src = url;
            aud.controls = true;
            aud.autoplay = true;
            aud.className = "w-full max-w-md";
            wrap.appendChild(icon);
            wrap.appendChild(aud);
            mediaPane.appendChild(wrap);
            activeMedia = { element: aud, type: "audio" };
        } else {
            var link = document.createElement("a");
            link.href = url;
            link.target = "_blank";
            link.className = "text-violet-400 text-lg underline hover:text-violet-300";
            link.textContent = "Open file \u2197";
            mediaPane.appendChild(link);
        }

        // Metadata sidebar
        var authorHtml = "";
        if (avatar) {
            authorHtml += '<img src="' + avatar + '" class="w-10 h-10 rounded-full object-cover" alt="">';
        }
        authorHtml += '<div><p class="text-sm text-white font-medium">' + author + '</p>';
        authorHtml += '<p class="text-xs text-gray-500">' + date + '</p></div>';
        if (sovereign) {
            authorHtml += '<span class="ml-auto bg-amber-900/50 text-amber-300 text-xs px-2 py-0.5 rounded-full">Sovereign</span>';
        }
        document.getElementById("lbAuthor").innerHTML = authorHtml;
        document.getElementById("lbCaption").textContent = alt || "No caption";

        var metaHtml = "";
        if (dims) metaHtml += '<div class="flex justify-between"><span>Dimensions</span><span class="text-gray-300">' + dims + '</span></div>';
        if (dur) metaHtml += '<div class="flex justify-between"><span>Duration</span><span class="text-gray-300">' + dur + 's</span></div>';
        if (hash) metaHtml += '<div class="flex justify-between"><span>SHA-256</span><span class="text-gray-300 font-mono text-xs break-all">' + hash + '</span></div>';
        metaHtml += '<div class="flex justify-between"><span>Type</span><span class="text-gray-300">' + (card.getAttribute("data-mime") || type) + '</span></div>';
        if (url) metaHtml += '<div class="mt-3"><a href="' + url + '" target="_blank" rel="noopener noreferrer" class="text-violet-400 hover:text-violet-300 text-xs underline">Open original \u2197</a></div>';
        document.getElementById("lbMeta").innerHTML = metaHtml;

        document.getElementById("lbPrev").style.display = lightboxCards.length > 1 ? "" : "none";
        document.getElementById("lbNext").style.display = lightboxCards.length > 1 ? "" : "none";
    }

    // ---------- Keyboard Navigation ----------

    document.addEventListener("keydown", function (e) {
        var modal = document.getElementById("lightboxModal");
        if (!modal || !modal.classList.contains("show")) return;
        if (e.key === "Escape") closeLightbox({ target: modal });
        else if (e.key === "ArrowLeft") navigateLightbox(-1);
        else if (e.key === "ArrowRight") navigateLightbox(1);
    });

    // ---------- Single-Instance Media Coordinator ----------

    function stopActiveMedia() {
        if (activeMedia && activeMedia.element) {
            activeMedia.element.pause();
            activeMedia.element.currentTime = 0;
            activeMedia = null;
        }
        document.querySelectorAll("audio").forEach(function (a) { a.pause(); a.currentTime = 0; });
        document.querySelectorAll(".audio-play-btn").forEach(function (btn) {
            btn.querySelector("span").innerHTML = "&#9654;";
        });
    }

    // ---------- Inline Audio Player ----------

    function toggleAudioPlayer(src, btn) {
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

        // Stop others
        document.querySelectorAll("audio").forEach(function (a) {
            if (a !== audio) { a.pause(); a.currentTime = 0; }
        });
        document.querySelectorAll(".audio-play-btn").forEach(function (b) {
            if (b !== btn) { b.querySelector("span").innerHTML = "&#9654;"; }
        });

        if (audio.paused) {
            audio.play();
            btn.querySelector("span").innerHTML = "&#9646;&#9646;";
            activeMedia = { element: audio, type: "audio" };

            audio.ontimeupdate = function () {
                var scrubbers = document.querySelectorAll('.scrubber[data-src="' + src + '"]');
                var times = document.querySelectorAll('.audio-current[data-src="' + src + '"]');
                if (audio.duration) {
                    scrubbers.forEach(function (s) { s.value = (audio.currentTime / audio.duration) * 100; });
                }
                times.forEach(function (t) {
                    var m = Math.floor(audio.currentTime / 60);
                    var s = Math.floor(audio.currentTime % 60);
                    t.textContent = m + ":" + (s < 10 ? "0" : "") + s;
                });
            };
            audio.onended = function () {
                btn.querySelector("span").innerHTML = "&#9654;";
                activeMedia = null;
            };
        } else {
            audio.pause();
            btn.querySelector("span").innerHTML = "&#9654;";
            activeMedia = null;
        }
    }

    // ---------- Scrubber Seek ----------

    document.addEventListener("DOMContentLoaded", function () {
        document.querySelectorAll(".scrubber").forEach(function (scrubber) {
            scrubber.addEventListener("input", function () {
                var src = this.getAttribute("data-src");
                var audio = document.querySelector('audio[data-src="' + src + '"]');
                if (audio && audio.duration) {
                    audio.currentTime = (this.value / 100) * audio.duration;
                }
            });
        });

        // Video auto-pause
        document.querySelectorAll("video").forEach(function (vid) {
            vid.addEventListener("play", function () {
                document.querySelectorAll("video").forEach(function (other) {
                    if (other !== vid) other.pause();
                });
            });
        });

        // Init tab from URL
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
})();
