(function () {
  'use strict';

  const TOAST_ICONS = {
    success: '✓',
    error: '✕',
    info: '✦',
    mesh: '🌐',
    heart: '❤️',
    repost: '🔁',
    copy: '🔗',
    enclave: '🛡️'
  };

  const TOAST_STYLES = {
    success: 'border-emerald-500/60 bg-emerald-950/90 text-emerald-200',
    error: 'border-rose-500/60 bg-rose-950/90 text-rose-200',
    info: 'border-violet-500/60 bg-slate-900/95 text-violet-200',
    mesh: 'border-blue-500/60 bg-slate-900/95 text-blue-200',
    heart: 'border-pink-500/60 bg-slate-900/95 text-pink-200',
    repost: 'border-emerald-500/60 bg-slate-900/95 text-emerald-200',
    copy: 'border-slate-500/60 bg-slate-900/95 text-slate-200',
    enclave: 'border-amber-500/60 bg-slate-900/95 text-amber-200'
  };

  function escapeHtml(str) {
    if (str === null || str === undefined) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  function showToast(message, type, duration) {
    if (typeof type === 'boolean') {
      type = type ? 'error' : 'success';
    }
    if (!type) {
      type = 'info';
    }
    if (typeof duration !== 'number') {
      duration = 3500;
    }

    const container = document.getElementById('toast-container');
    if (!container) {
      console.log(`[Toast] ${message}`);
      return;
    }

    const icon = TOAST_ICONS[type] || TOAST_ICONS.info;
    const style = TOAST_STYLES[type] || TOAST_STYLES.info;

    const toast = document.createElement('div');
    toast.className = `pointer-events-auto flex items-center justify-between gap-3 px-3.5 py-2.5 rounded-xl border backdrop-blur-md shadow-2xl transition-all duration-300 transform translate-y-4 opacity-0 ${style}`;
    toast.innerHTML = `
      <div class="flex items-center gap-2.5 min-w-0">
        <span class="text-sm shrink-0">${icon}</span>
        <span class="truncate leading-snug">${escapeHtml(message)}</span>
      </div>
      <button type="button" class="text-slate-400 hover:text-white shrink-0 ml-1 text-xs" onclick="this.parentElement.remove()">✕</button>
    `;

    container.appendChild(toast);

    // Animate In
    requestAnimationFrame(() => {
      toast.classList.remove('translate-y-4', 'opacity-0');
    });

    // Auto Dismiss
    setTimeout(() => {
      toast.classList.add('opacity-0', 'translate-y-2');
      setTimeout(() => {
        if (toast.parentElement) {
          toast.parentElement.removeChild(toast);
        }
      }, 300);
    }, duration);
  }

  window.showToast = showToast;
})();
