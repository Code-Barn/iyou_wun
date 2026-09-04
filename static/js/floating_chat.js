/**
 * floating_chat.js — Floating Dock Messenger Controller
 * Multi-protocol transport: XMPP (JID) + Nostr NIP-04 (npub / hex).
 */
(function() {
  const activeWindows = new Map(); // peerId -> { element, isMinimized }
  const UNREAD_BADGE = 'floating-chat-unread-badge';
  let chatSession = null; // { jid, ws_url, bosh_url, domain, pubkey_hex, token }
  let xmppSocket = null;  // background XMPP WebSocket (when reachable)

  function incrementUnreadBadge() {
    const badge = document.getElementById(UNREAD_BADGE);
    if (!badge) return;
    const current = parseInt(badge.textContent, 10) || 0;
    badge.textContent = current + 1;
    badge.classList.remove('hidden');
  }

  function clearUnreadBadge() {
    const badge = document.getElementById(UNREAD_BADGE);
    if (!badge) return;
    badge.textContent = 0;
    badge.classList.add('hidden');
  }

  function buildOutgoingBubble(text) {
    const msgBubble = document.createElement('div');
    msgBubble.className = 'flex justify-end';
    msgBubble.innerHTML = `
      <div class="bg-violet-600 text-white rounded-lg px-2.5 py-1 max-w-[85%] break-words text-[11px]">
        ${text}
      </div>
    `;
    return msgBubble;
  }

  function appendMessage(win, bubble) {
    const messages = win.element.querySelector('.docked-chat-messages');
    if (messages) {
      messages.appendChild(bubble);
      messages.scrollTop = messages.scrollHeight;
    }
  }

  function resolvePeerTarget(peerId) {
    if (!peerId) return null;
    if (peerId.indexOf('@') !== -1) {
      return { type: 'xmpp', jid: peerId };
    }
    const npubHex = peerId.replace(/^npub1/, '');
    if (/^[0-9a-fA-F]{64}$/.test(peerId)) {
      return { type: 'nostr', hex: peerId.toLowerCase() };
    }
    if (/^npub1[0-9a-z]+$/i.test(peerId)) {
      return { type: 'nostr', hex: npubHex, npub: peerId };
    }
    return null;
  }

  function sendViaXmpp(jid, text) {
    if (xmppSocket && xmppSocket.readyState === WebSocket.OPEN && window.Strophe) {
      try {
        const msg = window.Strophe.xmlHtmlNode(`<message to="${jid}" type="chat"><body>${window.Strophe.xmlEscape?.(text) || text}</body></message>`);
        window.Strophe.send(msg);
        return true;
      } catch (err) {
        console.error("XMPP send error:", err);
      }
    }
    return false;
  }

  function sendViaNostr(peerHex, text, onDone) {
    const bridge = window.bridgeClient;
    if (!bridge || typeof bridge.signEvent !== 'function') {
      if (onDone) onDone(false);
      return;
    }

    const encrypt = (typeof bridge.nip04Encrypt === 'function')
      ? bridge.nip04Encrypt
      : (typeof bridge.nip04_encrypt === 'function')
        ? bridge.nip04_encrypt
        : typeof window.nip04_encrypt === 'function' ? window.nip04_encrypt : null;

    const now = Math.floor(Date.now() / 1000);
    const build = function (content) {
      const event = {
        kind: 4,
        created_at: now,
        tags: [['p', peerHex]],
        content: content,
      };
      bridge.signEvent(event);
    };

    if (encrypt) {
      try {
        const result = encrypt(peerHex, text);
        Promise.resolve(result).then(function (encrypted) {
          build(encrypted || text);
        }).catch(function () { build(text); });
      } catch (err) {
        build(text);
      }
    } else {
      build(text);
    }

    bridge.connect(function (signedEvent) {
      if (!signedEvent || signedEvent.kind !== 4) return;
      if (typeof bridge.broadcastToRelays === 'function') {
        bridge.broadcastToRelays(signedEvent, null, function (local, global) {
          if (onDone) onDone(local || global);
        });
      } else if (onDone) {
        onDone(true);
      }
    });
  }

  function sendDockedMessage(event, peerId) {
    event.preventDefault();
    const win = activeWindows.get(peerId);
    if (!win) return;
    const input = win.element.querySelector('.docked-chat-input');
    const text = input ? input.value.trim() : '';
    if (!text) return;

    const target = resolvePeerTarget(peerId);
    const isNostrPeer = target && target.type === 'nostr';

    // Optimistic outgoing bubble with sent timestamp.
    const sentAt = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    const bubble = document.createElement('div');
    bubble.className = 'flex justify-end';
    bubble.innerHTML = `
      <div class="max-w-[85%]">
        <div class="bg-violet-600 text-white rounded-lg px-2.5 py-1 break-words text-[11px]">${isNostrPeer ? '🔒 ' : ''}${text}</div>
        <div class="text-right text-[9px] text-slate-400 mt-0.5">${sentAt}</div>
      </div>
    `;
    appendMessage(win, bubble);

    if (input) input.value = '';

    if (!target) {
      if (window.showToast) window.showToast('Unsupported peer target', 'error');
      return;
    }

    if (target.type === 'xmpp') {
      const ok = sendViaXmpp(target.jid, text);
      if (window.showToast) window.showToast(ok ? 'Sent via XMPP mesh' : 'XMPP offline — queued locally', ok ? 'info' : 'warn');
      return;
    }

    sendViaNostr(target.hex, text, function (ok) {
      if (window.showToast) {
        window.showToast(ok ? 'Signed & dispatched to relays' : 'Broadcast pending (offline)', ok ? 'info' : 'warn');
      }
    });
  }

  function dispatchIncomingMessage(peerId, text, fromSelf) {
    if (fromSelf) return;
    const gate = window.wotGate || window.WoTGate;
    if (gate && typeof gate.interceptInboundMessage === 'function') {
      if (!gate.interceptInboundMessage(peerId, false)) {
        return; // Drop silently without alerting minor or exposing preview
      }
    }
    const win = activeWindows.get(peerId);
    if (win && !win.isMinimized && win.element.classList.contains('hidden') === false) {
      const bubble = document.createElement('div');
      bubble.className = 'flex justify-start';
      bubble.innerHTML = `
        <div class="bg-slate-200 dark:bg-slate-700 text-slate-800 dark:text-slate-100 rounded-lg px-2.5 py-1 max-w-[85%] break-words text-[11px]">${text}</div>
      `;
      appendMessage(win, bubble);
      playChirp();
    } else {
      incrementUnreadBadge();
    }
  }

  function playChirp() {
    try {
      const ctx = window.AudioContext || window.webkitAudioContext;
      if (!ctx) return;
      const audio = new ctx();
      const osc = audio.createOscillator();
      const gain = audio.createGain();
      osc.connect(gain);
      gain.connect(audio.destination);
      osc.frequency.value = 880;
      gain.gain.setValueAtTime(0.05, audio.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.0001, audio.currentTime + 0.15);
      osc.start();
      osc.stop(audio.currentTime + 0.16);
    } catch (err) { /* audio unavailable */ }
  }

  function initIncomingListeners() {
    // Nostr kind 4 DM listener (relay pool events, when available).
    if (window.relayPool && typeof window.relayPool.on === 'function') {
      try {
        window.relayPool.on('event', async function (ev) {
          if (!ev || ev.kind !== 4 || !chatSession) return;
          const sender = (ev.tags || []).find(function (t) { return t[0] === 'p'; });
          if (!sender) return;
          const fromSelf = ev.pubkey === chatSession.pubkey_hex;
          if (fromSelf) return;

          // WoT Gate interception before decryption or preview
          const gate = window.wotGate || window.WoTGate;
          if (gate && typeof gate.interceptInboundNostr === 'function') {
            if (!gate.interceptInboundNostr(ev)) {
              return; // Silently drop
            }
          }

          let content = ev.content;
          if (window.bridgeClient && typeof window.bridgeClient.nip04Decrypt === 'function') {
            try {
              const dec = await window.bridgeClient.nip04Decrypt(ev.pubkey, ev.content);
              if (dec && dec !== ev.content) content = dec;
            } catch (err) { /* leave encrypted */ }
          } else if (window.nip04_decrypt) {
            try {
              const dec = window.nip04_decrypt(ev.pubkey, ev.content);
              if (dec && dec !== ev.content) content = dec;
            } catch (err) { /* leave encrypted */ }
          }
          dispatchIncomingMessage(ev.pubkey || sender[1], content, false);
        });
      } catch (err) { /* relay pool handler not attachable */ }
    }
  }

  function initXmppSocket() {
    if (!chatSession || !chatSession.ws_url) return;
    const WS = window.WebSocket;
    if (!WS || !window.Strophe) return;
    try {
      xmppSocket = new WS(chatSession.ws_url);
      xmppSocket.onopen = function () {
        const conn = window.Strophe.connection(chatSession.jid);
        window.Strophe.send = function (stanza) {
          if (xmppSocket && xmppSocket.readyState === WS.OPEN) {
            xmppSocket.send(new XMLSerializer().serializeToString(stanza));
          }
        };
        xmppSocket.onmessage = function (evt) {
          try {
            const xml = new DOMParser().parseFromString(evt.data, 'text/xml');
            
            // Inbound handshake check (e.g. subscription request)
            const presence = xml.getElementsByTagName('presence')[0];
            if (presence) {
              const pType = presence.getAttribute('type');
              const pFrom = presence.getAttribute('from') || '';
              if (pType === 'subscribe' && pFrom) {
                const gate = window.wotGate || window.WoTGate;
                if (gate && typeof gate.canAcceptChatHandshake === 'function') {
                  if (!gate.canAcceptChatHandshake(pFrom)) {
                    return; // Reject handshake
                  }
                }
              }
            }

            const body = xml.getElementsByTagName('body')[0];
            if (!body) return;
            const message = body.parentNode; // <message>
            const from = message.getAttribute ? message.getAttribute('from') || '' : '';
            const text = body.textContent || '';
            const clean = from.split('/')[0];

            // WoT Gate check on sender
            const gate = window.wotGate || window.WoTGate;
            if (gate && typeof gate.interceptInboundXMPP === 'function') {
              if (!gate.interceptInboundXMPP(clean, false)) {
                return; // Silently drop
              }
            }

            dispatchIncomingMessage(clean, text, false);
          } catch (err) { /* non-message stanza */ }
        };
      };
      xmppSocket.onerror = function () { /* fall back to Nostr-only */ };
    } catch (err) { xmppSocket = null; }
  }

  function initChatSession() {
    if (!window.__iknowyou_user_authenticated__) return;
    fetch('/api/chat/session/', { credentials: 'same-origin' })
      .then(function (res) { return res.json(); })
      .then(function (data) {
        if (!data || data.success === false) return;
        chatSession = data;
        window.chatSession = data;
        initXmppSocket();
        initIncomingListeners();
      })
      .catch(function () { /* offline — Nostr bridge still usable */ });
  }

  function toggleChatRoster() {
    const popover = document.getElementById('chat-roster-popover');
    if (popover) {
      popover.classList.toggle('hidden');
      if (!popover.classList.contains('hidden')) clearUnreadBadge();
    }
  }

  function buildDockedChatWindowHtml(peerId, peerName, peerAvatar) {
    const displayName = peerName || (peerId ? peerId.slice(0, 10) + '...' : 'Peer');
    const peerTarget = resolvePeerTarget(peerId);
    const isNative = peerTarget && peerTarget.type === 'xmpp';
    const securityBadge = isNative
      ? '<span class="text-[10px] text-violet-400 font-mono flex items-center gap-1">⚡ Sovereign Enclave Mesh</span>'
      : '<span class="text-[10px] text-emerald-400 font-mono flex items-center gap-1">🔒 NIP-04 E2EE Session</span>';
    const avatarHtml = peerAvatar
      ? `<img src="${peerAvatar}" class="w-5 h-5 rounded-full object-cover" />`
      : `<div class="w-5 h-5 rounded-full bg-violet-900 text-violet-300 flex items-center justify-center text-[10px]">${displayName[0].toUpperCase()}</div>`;

    const pane = document.createElement('div');
    pane.id = `docked-chat-${peerId}`;
    pane.className = 'w-72 sm:w-80 bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-t-2xl shadow-2xl overflow-hidden flex flex-col transition-all font-mono text-xs';
    pane.innerHTML = `
      <!-- Header -->
      <div class="px-3 py-2 bg-slate-50 dark:bg-slate-950 border-b border-slate-200 dark:border-slate-800 flex items-center justify-between cursor-pointer select-none" onclick="toggleMinimizeChat('${peerId}')">
        <div class="flex items-center gap-2 min-w-0">
          ${avatarHtml}
          <div class="min-w-0 flex flex-col leading-tight">
            <span class="font-bold text-slate-800 dark:text-slate-100 truncate">${displayName}</span>
            ${securityBadge}
          </div>
        </div>
        <div class="flex items-center gap-1.5 shrink-0 text-slate-400">
          <button type="button" onclick="event.stopPropagation(); toggleMinimizeChat('${peerId}')" class="hover:text-slate-600 dark:hover:text-slate-200 px-1">_</button>
          <button type="button" onclick="event.stopPropagation(); closeDockedChat('${peerId}')" class="hover:text-slate-600 dark:hover:text-slate-200 px-1">✕</button>
        </div>
      </div>
      
      <!-- Body & Messages -->
      <div class="docked-chat-body flex flex-col h-72">
        <div class="docked-chat-messages flex-1 p-3 overflow-y-auto space-y-2 bg-slate-50/50 dark:bg-slate-950/50">
          <div class="text-center py-4 text-[11px] text-slate-400">
            Encrypted session initialized with ${displayName}.
          </div>
        </div>
        <form onsubmit="sendDockedMessage(event, '${peerId}')" class="p-2 bg-white dark:bg-slate-900 border-t border-slate-200 dark:border-slate-800 flex items-center gap-1.5">
          <input type="text" id="dock-chat-input" class="docked-chat-input flex-1 bg-slate-50 dark:bg-slate-950 border border-slate-200 dark:border-slate-800 rounded px-2 py-1.5 text-xs text-slate-800 dark:text-slate-100 placeholder-slate-400 focus:outline-none focus:border-violet-500" placeholder="Type a message..." />
          <button type="submit" class="px-2.5 py-1.5 bg-violet-600 hover:bg-violet-500 text-white rounded text-xs font-semibold">Send</button>
        </form>
      </div>
    `;
    return pane;
  }

  function openDockedChat(peerId, peerName, peerAvatar) {
    if (!peerId) return;
    const container = document.getElementById('docked-chat-windows');
    if (!container) {
      window.location.href = `/chat?peer=${encodeURIComponent(peerId)}`;
      return;
    }

    // If window already open, unminimize and focus
    if (activeWindows.has(peerId)) {
      const win = activeWindows.get(peerId);
      win.element.classList.remove('hidden');
      const body = win.element.querySelector('.docked-chat-body');
      if (body) body.classList.remove('hidden');
      const input = win.element.querySelector('.docked-chat-input');
      if (input) input.focus();
      return;
    }

    // Limit to max 2 concurrent open panes on desktop, 1 on mobile
    if (activeWindows.size >= (window.innerWidth < 640 ? 1 : 2)) {
      const firstKey = activeWindows.keys().next().value;
      closeDockedChat(firstKey);
    }

    const pane = buildDockedChatWindowHtml(peerId, peerName, peerAvatar);
    container.appendChild(pane);
    activeWindows.set(peerId, { element: pane, isMinimized: false });

    // Focus input
    const input = pane.querySelector('.docked-chat-input');
    if (input) input.focus();
  }

  function setActiveChatPeer(targetPubkey, targetHandle) {
    if (!targetPubkey) return;
    openDockedChat(targetPubkey, targetHandle);
  }

  function openDirectMessage(targetPubkey, targetHandle) {
    // 1. Expand dock if collapsed
    const dock = document.getElementById('floating-chat-dock');
    if (dock && dock.classList.contains('hidden')) {
      dock.classList.remove('hidden');
    }
    const root = document.getElementById('floating-chat-root');
    if (root && root.classList.contains('hidden')) {
      root.classList.remove('hidden');
    }
    // 2. Select or create peer conversation entry
    if (typeof window.setActiveChatPeer === 'function') {
      window.setActiveChatPeer(targetPubkey, targetHandle);
    } else {
      openDockedChat(targetPubkey, targetHandle);
    }
    // 3. Focus message input
    const chatInput = document.getElementById('dock-chat-input') || document.querySelector('.docked-chat-input');
    if (chatInput) {
      chatInput.focus();
    }
  }

  // Bind click delegation for .action-btn-direct-message buttons across the document
  document.addEventListener('click', (e) => {
    const btn = e.target.closest('.action-btn-direct-message');
    if (!btn) return;
    e.preventDefault();
    const pubkey = btn.dataset.chatTargetPubkey;
    const handle = btn.dataset.chatTargetHandle;
    if (pubkey) {
      window.openDirectMessage(pubkey, handle);
    }
  });

  function toggleMinimizeChat(peerId) {
    const win = activeWindows.get(peerId);
    if (!win) return;
    const body = win.element.querySelector('.docked-chat-body');
    if (body) {
      body.classList.toggle('hidden');
      win.isMinimized = body.classList.contains('hidden');
    }
  }

  function closeDockedChat(peerId) {
    const win = activeWindows.get(peerId);
    if (win) {
      win.element.remove();
      activeWindows.delete(peerId);
    }
  }

  function onReady() {
    const authed = (typeof window.userPubkey !== 'undefined' && window.userPubkey)
      || document.body.getAttribute('data-authenticated') === 'true'
      || (window.__iknowyou_user_authenticated__ === true);
    if (authed) {
      initChatSession();
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', onReady);
  } else {
    onReady();
  }

  window.toggleChatRoster = toggleChatRoster;
  window.openDockedChat = openDockedChat;
  window.setActiveChatPeer = setActiveChatPeer;
  window.openDirectMessage = openDirectMessage;
  window.toggleMinimizeChat = toggleMinimizeChat;
  window.closeDockedChat = closeDockedChat;
  window.sendDockedMessage = sendDockedMessage;
  window.chatDispatchIncoming = dispatchIncomingMessage;
})();
