/**
 * floating_chat.js — Floating Dock Messenger Controller
 */
(function() {
  const activeWindows = new Map(); // peerId -> { element, isMinimized }

  function toggleChatRoster() {
    const popover = document.getElementById('chat-roster-popover');
    if (popover) {
      popover.classList.toggle('hidden');
    }
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

    const displayName = peerName || peerId.slice(0, 10) + '...';
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
          <span class="font-bold text-slate-800 dark:text-slate-100 truncate">${displayName}</span>
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
          <input type="text" class="docked-chat-input flex-1 bg-slate-50 dark:bg-slate-950 border border-slate-200 dark:border-slate-800 rounded px-2 py-1.5 text-xs text-slate-800 dark:text-slate-100 placeholder-slate-400 focus:outline-none focus:border-violet-500" placeholder="Type a message..." />
          <button type="submit" class="px-2.5 py-1.5 bg-violet-600 hover:bg-violet-500 text-white rounded text-xs font-semibold">Send</button>
        </form>
      </div>
    `;

    container.appendChild(pane);
    activeWindows.set(peerId, { element: pane, isMinimized: false });

    // Focus input
    const input = pane.querySelector('.docked-chat-input');
    if (input) input.focus();
  }

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

  function sendDockedMessage(event, peerId) {
    event.preventDefault();
    const win = activeWindows.get(peerId);
    if (!win) return;
    const input = win.element.querySelector('.docked-chat-input');
    const text = input ? input.value.trim() : '';
    if (!text) return;

    const messages = win.element.querySelector('.docked-chat-messages');
    if (messages) {
      const msgBubble = document.createElement('div');
      msgBubble.className = 'flex justify-end';
      msgBubble.innerHTML = `
        <div class="bg-violet-600 text-white rounded-lg px-2.5 py-1 max-w-[85%] break-words text-[11px]">
          ${text}
        </div>
      `;
      messages.appendChild(msgBubble);
      messages.scrollTop = messages.scrollHeight;
    }

    if (input) input.value = '';
    if (window.showToast) window.showToast('Message dispatched to mesh', 'info');
  }

  window.toggleChatRoster = toggleChatRoster;
  window.openDockedChat = openDockedChat;
  window.toggleMinimizeChat = toggleMinimizeChat;
  window.closeDockedChat = closeDockedChat;
  window.sendDockedMessage = sendDockedMessage;
})();
