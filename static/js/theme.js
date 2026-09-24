document.addEventListener('DOMContentLoaded', () => {
  const themeToggle = document.getElementById('theme-toggle');
  const iconSun = document.getElementById('icon-sun');
  const iconMoon = document.getElementById('icon-moon');

  function getActiveTheme() {
    const cookieMatch = document.cookie.match(/(?:^|; )wun_theme=([^;]*)/);
    if (cookieMatch) return decodeURIComponent(cookieMatch[1]);
    return localStorage.getItem('wun_theme') || 'light';
  }

  function updateIcons(isDark) {
    if (!iconSun || !iconMoon) return;
    if (isDark) {
      iconSun.classList.remove('hidden');
      iconMoon.classList.add('hidden');
    } else {
      iconSun.classList.add('hidden');
      iconMoon.classList.remove('hidden');
    }
  }

  function setTheme(theme) {
    const isDark = theme === 'dark' || theme === 'stealth';
    if (isDark) {
      document.documentElement.classList.add('dark');
    } else {
      document.documentElement.classList.remove('dark');
    }
    document.cookie = `wun_theme=${theme}; path=/; max-age=31536000; SameSite=Lax`;
    localStorage.setItem('wun_theme', theme);
    updateIcons(isDark);
  }

  const initialTheme = getActiveTheme();
  setTheme(initialTheme);

  if (themeToggle) {
    themeToggle.addEventListener('click', () => {
      const currentTheme = getActiveTheme();
      const nextTheme = (currentTheme === 'dark' || currentTheme === 'stealth') ? 'light' : 'dark';
      setTheme(nextTheme);
    });
  }
});

window.toggleL2Header = function (forceCollapse) {
  var isCollapsed = document.body.classList.contains('l2-collapsed');
  var nextState = (typeof forceCollapse === 'boolean') ? forceCollapse : !isCollapsed;

  document.body.classList.toggle('l2-collapsed', nextState);
  document.documentElement.classList.toggle('l2-collapsed', nextState);
  localStorage.setItem('wun_l2_collapsed', nextState ? 'true' : 'false');

  var btn = document.getElementById('l2-toggle-header-btn');
  if (btn) {
    btn.classList.toggle('text-violet-600', !nextState);
    btn.classList.toggle('dark:text-violet-400', !nextState);
  }
};

document.addEventListener('DOMContentLoaded', function () {
  var ribbon = document.getElementById('app-l2-ribbon');
  var btn = document.getElementById('l2-toggle-header-btn');

  // Satellites / standalone views that lack an L2 ribbon: the collapser would
  // appear broken, so auto-hide it even when SHOW_L2_TOGGLE is enabled.
  if (btn && !ribbon) {
    btn.style.display = 'none';
  }

  var isCollapsed = localStorage.getItem('wun_l2_collapsed') === 'true';
  if (isCollapsed) {
    document.body.classList.add('l2-collapsed');
    document.documentElement.classList.add('l2-collapsed');
  }
  if (ribbon && btn) {
    btn.classList.toggle('text-violet-600', !isCollapsed);
    btn.classList.toggle('dark:text-violet-400', !isCollapsed);
  }
});
