/**
 * MaatLog theme runtime.
 *
 * Loaded synchronously from the document head so a stored light/dark choice is
 * applied before the first paint. The immediate part must not touch anything
 * below <html>; the banner toggle is wired up on DOMContentLoaded.
 */

(() => {
  /** @typedef {"light" | "dark"} MaatlogTheme */

  const STORAGE_KEY = "maatlog-theme";
  const DARK_QUERY = "(prefers-color-scheme: dark)";

  /**
   * Read the reader's stored choice.
   *
   * @returns {MaatlogTheme | null} null when unset, unknown, or unreadable.
   */
  function readStoredTheme() {
    try {
      const stored = window.localStorage.getItem(STORAGE_KEY);
      return stored === "light" || stored === "dark" ? stored : null;
    } catch {
      // Private windows and blocked site data throw on access, not on read.
      return null;
    }
  }

  /**
   * @param {MaatlogTheme} theme
   * @returns {void}
   */
  function storeTheme(theme) {
    try {
      window.localStorage.setItem(STORAGE_KEY, theme);
    } catch {
      // The choice stays session-only; switching still works on this page.
    }
  }

  /**
   * @returns {MaatlogTheme} the operating system preference.
   */
  function systemTheme() {
    return window.matchMedia && window.matchMedia(DARK_QUERY).matches ? "dark" : "light";
  }

  /**
   * Apply a theme, or hand control back to prefers-color-scheme when null.
   *
   * @param {MaatlogTheme | null} theme
   * @returns {void}
   */
  function applyTheme(theme) {
    const root = document.documentElement;
    if (theme === null) {
      delete root.dataset.theme;
    } else {
      root.dataset.theme = theme;
    }

    // Sphinx emits the dark Pygments sheet with media="(prefers-color-scheme: dark)".
    // Rewriting the media attribute is the only way to follow an explicit choice.
    const pygmentsDark = document.getElementById("pygments_dark_css");
    if (pygmentsDark instanceof HTMLLinkElement) {
      if (theme === null) {
        pygmentsDark.media = DARK_QUERY;
      } else {
        pygmentsDark.media = theme === "dark" ? "all" : "not all";
      }
    }
  }

  /**
   * @returns {MaatlogTheme} the theme the reader currently sees.
   */
  function effectiveTheme() {
    const attribute = document.documentElement.dataset.theme;
    return attribute === "light" || attribute === "dark" ? attribute : systemTheme();
  }

  /**
   * @param {HTMLButtonElement} button
   * @returns {void}
   */
  function syncToggle(button) {
    button.setAttribute("aria-pressed", String(effectiveTheme() === "dark"));
  }

  /**
   * Mark the heading the reader is looking at in the page TOC.
   *
   * Progressive enhancement: without IntersectionObserver, or without a TOC,
   * the sidebar stays a plain list of links, which is the whole contract.
   *
   * @returns {void}
   */
  function wireTocScrollspy() {
    const toc = document.querySelector(".maatlog-toc-headings");
    if (!(toc instanceof HTMLElement) || typeof IntersectionObserver !== "function") {
      return;
    }

    /** @type {Map<Element, HTMLAnchorElement>} */
    const linkByHeading = new Map();
    for (const link of toc.querySelectorAll('a[href^="#"]')) {
      if (!(link instanceof HTMLAnchorElement)) {
        continue;
      }
      const id = decodeURIComponent(link.hash.slice(1));
      const heading = id ? document.getElementById(id) : null;
      if (heading) {
        linkByHeading.set(heading, link);
      }
    }
    if (linkByHeading.size === 0) {
      return;
    }

    // TOC の並びは文書順。最初に見えている見出しが「いま読んでいる場所」。
    const headings = [...linkByHeading.keys()];
    /** @type {Set<Element>} */
    const visible = new Set();
    /** @type {HTMLAnchorElement | null} */
    let current = null;

    /** @returns {void} */
    function refresh() {
      const active = headings.find((heading) => visible.has(heading));
      if (!active) {
        // 交差している見出しが無い間は直前の表示を保つ。点滅させない。
        return;
      }
      const link = linkByHeading.get(active);
      if (!link || link === current) {
        return;
      }
      if (current) {
        current.removeAttribute("aria-current");
      }
      link.setAttribute("aria-current", "true");
      current = link;
    }

    // sticky ヘッダの裏に隠れている見出しは「見えている」と数えない。
    const banner = document.querySelector(".maatlog-banner");
    const offset = banner instanceof HTMLElement ? Math.round(banner.getBoundingClientRect().height) : 0;
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            visible.add(entry.target);
          } else {
            visible.delete(entry.target);
          }
        }
        refresh();
      },
      { rootMargin: `-${offset}px 0px -70% 0px` },
    );

    for (const heading of headings) {
      observer.observe(heading);
    }
  }

  document.documentElement.classList.add("maatlog-js");
  applyTheme(readStoredTheme());

  document.addEventListener("DOMContentLoaded", () => {
    wireTocScrollspy();

    const button = document.querySelector(".maatlog-theme-toggle");
    if (!(button instanceof HTMLButtonElement)) {
      // A theme may ship its own banner without the toggle; everything else still works.
      return;
    }

    syncToggle(button);

    button.addEventListener("click", () => {
      const next = effectiveTheme() === "dark" ? "light" : "dark";
      applyTheme(next);
      storeTheme(next);
      syncToggle(button);
    });

    if (window.matchMedia) {
      // Only the reported state needs updating; the palette follows the media query.
      window.matchMedia(DARK_QUERY).addEventListener("change", () => {
        if (readStoredTheme() === null) {
          syncToggle(button);
        }
      });
    }
  });
})();
