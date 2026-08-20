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
