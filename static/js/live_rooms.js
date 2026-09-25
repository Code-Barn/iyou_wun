/*
  live_rooms.js — NIP-53 (Kind 30311) live-room cards for the feed right rail.

  Tracks AUDIT-005 §5.2 (docked LiveAudioTray wiring) and AUDIT-003 §7
  (NIP-53 Kind-30311 reader footprint, phase-1 transport).

  Flow:
    - Subscribes the managed relay pool (window.relayPool) to live rooms via
      ensureConnection(url, filter, onSocketMessage) on every enabled read relay.
      Filter: { kinds: [30311], "#status": ["live"], limit: 10 }.
    - Parses inbound ["EVENT", subId, nostrEvent] frames defensively: d/title
      tags, image/cover, streaming/recording, current_participants/participants,
      starts, status, and the p-tag Host role with the event pubkey fallback.
    - Renders 16:9 cover cards into #live-rooms-list; hides #live-rooms-card
      until at least one live room is observed and re-hides when zero remain.
    - Clicking a card calls window.LiveAudioTray.attach(room) so the docked
      tray pill appears and can play the stream (native <audio> / hls.js).

  Empty/absence contract: when the right rail is not mounted (thread mode,
  anonymous feed), #live-rooms-list is absent and this module no-ops without
  opening any relay sockets.
*/
(function (global) {
  "use strict";
  if (global.__wunLiveRoomsBound) return;
  global.__wunLiveRoomsBound = true;

  var CARD_LIMIT = 10;
  var FILTER = { kinds: [30311], "#status": ["live"], limit: 10 };

  var cardEl = null;
  var listEl = null;
  var countEl = null;
  var rooms = {}; // roomId -> room
  var order = []; // roomIds in first-seen order
  var seen = {};  // eventId -> true (de-dupe across relays)

  function $(id) { return document.getElementById(id); }

  function escapeHtml(s) {
    s = String(s == null ? "" : s);
    return s.replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function shortPub(pubkey) {
    pubkey = String(pubkey || "");
    if (!pubkey) return "anonymous";
    if (pubkey.indexOf("@") === 0) return pubkey;
    return pubkey.length > 12
      ? pubkey.slice(0, 6) + "…" + pubkey.slice(-4)
      : (pubkey || "anonymous");
  }

  // ---- NIP-53 defensive tag parsing ------------------------------------
  function tagValue(tags, name) {
    if (!Array.isArray(tags)) return "";
    for (var i = 0; i < tags.length; i++) {
      var t = tags[i];
      if (t && t[0] === name && t[1] != null && t[1] !== "") return String(t[1]);
    }
    return "";
  }

  function intTag(tags, name, fallback) {
    var v = parseInt(tagValue(tags, name), 10);
    return isNaN(v) ? (fallback || 0) : v;
  }

  function hostPubkey(ev) {
    // p-tag with a "host" role wins; the room author/owner is the fallback.
    if (Array.isArray(ev.tags)) {
      for (var i = 0; i < ev.tags.length; i++) {
        var t = ev.tags[i];
        if (t && t[0] === "p" && String(t[3] || "").toLowerCase() === "host") {
          if (t[1]) return String(t[1]);
        }
      }
    }
    return ev.pubkey || "";
  }

  function contentField(ev, field) {
    try {
      var parsed = JSON.parse(ev.content || "");
      if (parsed && typeof parsed === "object" && parsed[field]) return String(parsed[field]);
    } catch (e) { /* ignore */ }
    return "";
  }

  function parseRoom(ev) {
    if (!ev || ev.kind !== 30311) return null;
    var tags = Array.isArray(ev.tags) ? ev.tags : [];
    var status = (tagValue(tags, "status") || "live").toLowerCase();
    if (status !== "live") return null; // only surface active rooms

    var title = tagValue(tags, "title") || tagValue(tags, "d") || contentField(ev, "title");
    var streamUrl = tagValue(tags, "streaming") || contentField(ev, "streaming_url");
    var hostPub = hostPubkey(ev);
    var participants = intTag(tags, "participants", 0);
    var current = intTag(tags, "current_participants", participants);

    return {
      id: ev.id || (hostPub + "/" + (title || "untitled")),
      title: title || "Untitled Room",
      host_name: tagValue(tags, "host") || tagValue(tags, "name") || shortPub(hostPub),
      host_avatar: tagValue(tags, "host_avatar") || tagValue(tags, "avatar") || contentField(ev, "host_avatar") || "",
      cover: tagValue(tags, "image") || tagValue(tags, "cover") || "",
      status: "live",
      streaming_url: streamUrl,
      recording_url: tagValue(tags, "recording") || "",
      current_participants: current,
      participants: participants,
      started_at: intTag(tags, "starts", 0)
    };
  }

  // ---- Rendering --------------------------------------------------------
  function render() {
    if (!listEl) return;

    var ids = order.filter(function (id) { return rooms[id]; }).slice(0, CARD_LIMIT);

    // No live-rooms observed: keep the card visible (server owns visibility)
    // and restore the clean "no live audio spaces" fallback state so the
    // real-time refresh never leaves a blank rail module.
    if (ids.length === 0) {
      listEl.innerHTML = '<div class="py-3 text-center text-slate-400 text-[11px]">No live audio spaces active on mesh.</div>';
      if (countEl) countEl.textContent = "0 online";
      if (cardEl) cardEl.classList.remove("hidden");
      return;
    }

    listEl.innerHTML = ids.map(function (id) {
      var room = rooms[id];
      var cover = room.cover
        ? '<img src="' + escapeHtml(room.cover) + '" alt="" class="w-full h-full object-cover" referrerpolicy="no-referrer" onerror="this.classList.add(\'hidden\');var p=this.parentNode;if(p)p.classList.add(\'bg-violet-600/20\');">'
        : "";
      var count = (room.current_participants > 0)
        ? '<span class="absolute bottom-1.5 right-1.5 px-1.5 py-0.5 rounded-full bg-black/60 text-white text-[9px] font-mono flex items-center gap-1">👁 ' + escapeHtml(room.current_participants) + "</span>"
        : "";
      return (
        '<div class="live-room-card relative group overflow-hidden rounded-lg border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-950 cursor-pointer hover:border-violet-500/60 transition" ' +
        'role="button" tabindex="0" data-room-id="' + escapeHtml(id) + '" ' +
        'aria-label="Listen in to ' + escapeHtml(room.title) + '">' +
          '<div class="relative aspect-video w-full overflow-hidden bg-slate-200 dark:bg-slate-800">' +
            '<span class="absolute inset-0 flex items-center justify-center text-slate-400 text-lg">▶</span>' +
            cover +
            '<span class="absolute top-1.5 left-1.5 px-1.5 py-0.5 rounded bg-violet-600 text-white text-[9px] font-bold flex items-center gap-1 animate-pulse">' +
              '<span class="w-1.5 h-1.5 rounded-full bg-white/90"></span>LIVE' +
            "</span>" +
            count +
          "</div>" +
          '<div class="p-2">' +
            '<div class="text-[10px] text-violet-500 dark:text-violet-400 truncate font-mono">@' + escapeHtml(room.host_name) + "</div>" +
            '<div class="text-[11px] font-semibold text-slate-900 dark:text-slate-100 truncate">' + escapeHtml(room.title) + "</div>" +
          "</div>" +
        "</div>"
      );
    }).join("");

    if (countEl) countEl.textContent = ids.length + " online";
    // The server-rendered card shell owns module visibility; never re-hide it.
    if (cardEl) cardEl.classList.remove("hidden");
  }

  function attach(room) {
    if (global.LiveAudioTray && typeof global.LiveAudioTray.attach === "function") {
      try { global.LiveAudioTray.attach(room); } catch (e) { /* ignore */ }
      return true;
    }
    return false;
  }

  function bindCardEvents() {
    if (!listEl || listEl._wunLiveRoomsBound) return;
    listEl._wunLiveRoomsBound = true;
    listEl.addEventListener("click", function (e) {
      var card = e.target.closest ? e.target.closest(".live-room-card") : null;
      if (!card) return;
      var id = card.getAttribute("data-room-id");
      if (id && rooms[id]) attach(rooms[id]);
    });
    listEl.addEventListener("keydown", function (e) {
      if (e.key !== "Enter" && e.key !== " ") return;
      var card = e.target.closest ? e.target.closest(".live-room-card") : null;
      if (!card) return;
      e.preventDefault();
      var id = card.getAttribute("data-room-id");
      if (id && rooms[id]) attach(rooms[id]);
    });
  }

  // ---- Inbound subscription frames --------------------------------------
  function handleEvent(ev) {
    if (!ev || !ev.id || seen[ev.id]) return;
    var room = parseRoom(ev);
    if (!room) return;
    seen[ev.id] = true;
    if (!rooms[room.id]) order.push(room.id);
    rooms[room.id] = room;
    render();
  }

  function onSocketMessage(mEvent) {
    var raw = mEvent && mEvent.data;
    if (typeof raw !== "string") return;
    var frame;
    try { frame = JSON.parse(raw); } catch (e) { return; }
    if (!Array.isArray(frame) || frame.length < 2) return;
    var type = frame[0];
    if (type === "EVENT") {
      handleEvent(frame[2]);
    } else if (type === "EOSE") {
      // Initial snapshot done — hide when absolutely nothing arrived yet.
      if (Object.keys(rooms).length === 0 && listEl) render();
    }
  }

  function subscribe() {
    if (!window.relayPool || typeof window.relayPool.ensureConnection !== "function") return;
    var relays = [];
    try {
      relays = (typeof window.relayPool.getReadRelays === "function")
        ? window.relayPool.getReadRelays()
        : [];
    } catch (e) { /* ignore */ }
    (relays || []).forEach(function (url) {
      try { window.relayPool.ensureConnection(url, FILTER, onSocketMessage); } catch (e) { /* ignore */ }
    });
  }

  function init() {
    cardEl = $("live-rooms-card");
    listEl = $("live-rooms-list");
    if (!cardEl || !listEl) return; // right rail not mounted (thread/anon feed)
    countEl = $("live-rooms-count");
    bindCardEvents();
    subscribe();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

  // Test / debug surface.
  global.LiveRooms = {
    parse: parseRoom,
    attach: attach,
    count: function () { return Object.keys(rooms).length; }
  };
})(typeof window !== "undefined" ? window : globalThis);