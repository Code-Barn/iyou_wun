/**
 * live_audio_player.js — NIP-53 (Kind 30311) persistent floating audio tray.
 *
 * Consumed by the right-rail discovery widget (server-rendered tune-in
 * buttons) and by the real-time live_rooms.js cards via the LiveAudioTray
 * compatibility alias. Handles stream playback, mute/unmute volume, play/pause
 * and minimize/maximize states on the DOM of templates/includes/_live_audio_tray.html.
 */
(function (window) {
  'use strict';
  if (window.__wunLiveAudioPlayerBound) return;
  window.__wunLiveAudioPlayerBound = true;

  function LiveAudioPlayer() {
    this.tray = null;
    this.audio = null;
    this.playBtn = null;
    this.playIcon = null;
    this.pauseIcon = null;
    this.titleEl = null;
    this.hostEl = null;
    this.listenersEl = null;
    this.currentRoom = null;
    this.isMinimized = false;
    this.hls = null;
  }

  function shortPub(pubkey) {
    pubkey = String(pubkey || "").trim();
    if (!pubkey) return "";
    if (pubkey.length > 12) return pubkey.substring(0, 6) + "…" + pubkey.substring(pubkey.length - 4);
    return pubkey;
  }

  function resolveRoom(arg) {
    // Accept either a room object (LiveAudioTray.attach / direct tuneIn) or a
    // server-rendered tune-in <button> whose data-* attributes carry the room.
    if (arg && arg.dataset) {
      var btn = arg;
      return {
        id: btn.dataset.roomId || "",
        d_tag: btn.dataset.roomDTag || "",
        title: btn.dataset.roomTitle || btn.dataset.streamUrl || "Audio Space",
        summary: btn.dataset.roomSummary || "",
        streaming_url: btn.dataset.streamUrl || "",
        status: btn.dataset.roomStatus || "live",
        current_participants: parseInt(btn.dataset.roomParticipants || "0", 10) || 0,
        host_pubkey: btn.dataset.roomHost || ""
      };
    }
    return arg || null;
  }

  LiveAudioPlayer.prototype.init = function () {
    this.tray = document.getElementById('live-audio-tray');
    this.audio = document.getElementById('live-audio-element');
    this.playBtn = document.getElementById('audio-tray-play-btn');
    this.playIcon = document.getElementById('audio-tray-play-icon');
    this.pauseIcon = document.getElementById('audio-tray-pause-icon');
    this.titleEl = document.getElementById('audio-tray-title');
    this.hostEl = document.getElementById('audio-tray-host');
    this.listenersEl = document.getElementById('audio-tray-listeners');

    if (!this.audio) return;

    var self = this;
    this.audio.addEventListener('play', function () {
      self.updatePlayState(true);
    });
    this.audio.addEventListener('pause', function () {
      self.updatePlayState(false);
    });
    this.audio.addEventListener('ended', function () {
      self.updatePlayState(false);
    });
    this.audio.addEventListener('error', function () {
      if (window.showToast) {
        window.showToast('Audio stream encountered connection fault', 'warn');
      }
      self.updatePlayState(false);
    });
  };

  LiveAudioPlayer.prototype.tuneIn = function (roomOrButton) {
    if (!this.audio) this.init();
    var room = resolveRoom(roomOrButton);
    if (!room || !room.streaming_url) {
      if (window.showToast) window.showToast('Room has no active stream URL', 'warn');
      return;
    }

    this.currentRoom = room;
    if (this.titleEl) this.titleEl.textContent = room.title || 'Audio Space';
    var host = room.host_pubkey || room.host_name || '';
    if (this.hostEl) {
      this.hostEl.textContent = host ? 'Host: ' + shortPub(host) : 'Host: Anonymous';
    }
    if (this.listenersEl) {
      this.listenersEl.textContent = room.current_participants ? '👥 ' + room.current_participants : '';
    }

    if (this.tray) this.tray.classList.remove('hidden');

    this._loadStream(room.streaming_url);
    var playPromise = this.audio.play();
    if (playPromise !== undefined) {
      playPromise.catch(function (err) {
        console.warn('[NIP-53] Autoplay prevented or stream error:', err);
      });
    }

    if (window.showToast) {
      window.showToast('Tuned into ' + (room.title || 'Audio Space'), 'info');
    }
  };

  LiveAudioPlayer.prototype._loadStream = function (url) {
    if (!this.audio) return;
    // Preserve hls.js transport for .m3u8 live streams when the library is
    // present (previous tray footprint supported it), else native <audio>.
    this._teardownHls();
    var isHls = /\.m3u8([?#].*)?$/i.test(url);
    if (isHls && window.Hls && window.Hls.isSupported()) {
      try {
        this.hls = new window.Hls();
        this.hls.loadSource(url);
        this.hls.attachMedia(this.audio);
        return;
      } catch (e) {
        console.warn('[NIP-53] hls.js attach failed, falling back to native audio:', e);
        this._teardownHls();
      }
    }
    this.audio.src = url;
  };

  LiveAudioPlayer.prototype._teardownHls = function () {
    if (this.hls) {
      try { this.hls.destroy(); } catch (e) { /* ignore */ }
      this.hls = null;
    }
  };

  LiveAudioPlayer.prototype.togglePlay = function () {
    if (!this.audio || !this.audio.src) return;
    if (this.audio.paused) {
      this.audio.play();
    } else {
      this.audio.pause();
    }
  };

  LiveAudioPlayer.prototype.updatePlayState = function (isPlaying) {
    if (this.playIcon && this.pauseIcon) {
      this.playIcon.classList.toggle('hidden', isPlaying);
      this.pauseIcon.classList.toggle('hidden', !isPlaying);
    }
  };

  LiveAudioPlayer.prototype.setVolume = function (vol) {
    if (this.audio) {
      this.audio.volume = parseFloat(vol);
    }
  };

  LiveAudioPlayer.prototype.toggleMinimize = function () {
    var body = document.getElementById('audio-tray-body');
    if (body) {
      this.isMinimized = !this.isMinimized;
      body.classList.toggle('hidden', this.isMinimized);
    }
  };

  LiveAudioPlayer.prototype.disconnect = function () {
    if (this.audio) {
      this.audio.pause();
      this._teardownHls();
      this.audio.removeAttribute('src');
      this.audio.load();
    }
    if (this.tray) {
      this.tray.classList.add('hidden');
    }
    var body = document.getElementById('audio-tray-body');
    if (body) body.classList.remove('hidden');
    this.isMinimized = false;
    this.currentRoom = null;
  };

  var player = new LiveAudioPlayer();
  window.liveAudioPlayer = player;

  // ---- Backward-compat alias for legacy consumers -----------------------
  // live_rooms.js (real-time relay cards) and any external caller that used
  // the previous inline tray controller keep working through this mapping.
  window.LiveAudioTray = {
    attach: function (room) { window.liveAudioPlayer.tuneIn(room); },
    hide: function () { window.liveAudioPlayer.disconnect(); },
    stop: function () { window.liveAudioPlayer.disconnect(); }
  };

  function boot() {
    window.liveAudioPlayer.init();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})(window);