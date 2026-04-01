// =============================================================================
// backend/app/static/js/theme-toggle.js
// =============================================================================

(function () {
  const STORAGE_KEY = "color-theme";
  const ROOT = document.documentElement;
  const TOGGLE_SELECTOR = "[data-theme-toggle]";

  function readStoredTheme() {
    try {
      const value = localStorage.getItem(STORAGE_KEY);
      if (value === "dark" || value === "light") {
        return value;
      }
    } catch (_) {}
    return null;
  }

  function writeTheme(value) {
    try {
      localStorage.setItem(STORAGE_KEY, value);
    } catch (_) {}
  }

  function systemPrefersDark() {
    return !!(
      window.matchMedia &&
      window.matchMedia("(prefers-color-scheme: dark)").matches
    );
  }

  function resolveTheme() {
    const stored = readStoredTheme();
    if (stored) return stored;
    return systemPrefersDark() ? "dark" : "light";
  }

  function isDark() {
    return ROOT.classList.contains("dark");
  }

  function setRootTheme(theme) {
    ROOT.classList.toggle("dark", theme === "dark");
  }

  function applySwitchVisual(toggle, darkMode) {
    toggle.setAttribute("aria-checked", darkMode ? "true" : "false");
    toggle.classList.toggle("bg-gray-100", !darkMode);
    toggle.classList.toggle("bg-gray-700", darkMode);

    const thumb = toggle.querySelector("[data-theme-thumb]");
    if (thumb) {
      thumb.classList.toggle("translate-x-0", !darkMode);
      thumb.classList.toggle("translate-x-6", darkMode);
    }

    const thumbLight = toggle.querySelector("[data-theme-thumb-icon-light]");
    const thumbDark = toggle.querySelector("[data-theme-thumb-icon-dark]");
    if (thumbLight && thumbDark) {
      thumbLight.classList.toggle("hidden", darkMode);
      thumbDark.classList.toggle("hidden", !darkMode);
    }

    const trackLight = toggle.querySelector("[data-theme-track-icon-light]");
    const trackDark = toggle.querySelector("[data-theme-track-icon-dark]");
    if (trackLight && trackDark) {
      trackLight.classList.toggle("opacity-100", !darkMode);
      trackLight.classList.toggle("opacity-30", darkMode);
      trackDark.classList.toggle("opacity-30", !darkMode);
      trackDark.classList.toggle("opacity-100", darkMode);
    }
  }

  function syncSwitches() {
    const darkMode = isDark();
    document.querySelectorAll(TOGGLE_SELECTOR).forEach((toggle) => {
      applySwitchVisual(toggle, darkMode);
    });
  }

  function setTheme(theme, persist) {
    setRootTheme(theme);
    if (persist) {
      writeTheme(theme);
    }
    syncSwitches();
  }

  function toggleTheme() {
    const next = isDark() ? "light" : "dark";
    setTheme(next, true);
  }

  function onDocumentClick(event) {
    const toggle = event.target.closest(TOGGLE_SELECTOR);
    if (!toggle) return;
    event.preventDefault();
    toggleTheme();
  }

  function bindSystemThemeChanges() {
    if (!window.matchMedia) return;
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const listener = (event) => {
      // Segui il tema di sistema solo se l'utente non ha scelto manualmente.
      if (readStoredTheme() === null) {
        setTheme(event.matches ? "dark" : "light", false);
      }
    };
    if (typeof media.addEventListener === "function") {
      media.addEventListener("change", listener);
    } else if (typeof media.addListener === "function") {
      media.addListener(listener);
    }
  }

  function initThemeToggle() {
    setTheme(resolveTheme(), false);
    document.addEventListener("click", onDocumentClick);
    document.addEventListener("htmx:afterSwap", syncSwitches);
    document.addEventListener("htmx:afterSettle", syncSwitches);
    bindSystemThemeChanges();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initThemeToggle);
  } else {
    initThemeToggle();
  }
})();

