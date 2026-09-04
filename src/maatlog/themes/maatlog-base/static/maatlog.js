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
   * @typedef {object} MaatlogEnhancer
   * @property {string} selector CSS selector of the elements this feature owns.
   * @property {(element: Element) => void} apply Upgrade one matching element.
   */

  /** @type {Map<string, MaatlogEnhancer>} */
  const enhancers = new Map();
  /** Elements already upgraded, per enhancer. @type {Map<string, WeakSet<Element>>} */
  const enhancedElements = new Map();

  /**
   * Register one feature of the theme runtime.
   *
   * Every feature goes through this single mechanism so that content appended
   * later (infinite scroll) can be upgraded by exactly the same code path.
   *
   * @param {string} name
   * @param {MaatlogEnhancer} enhancer
   * @returns {void}
   */
  function registerEnhancer(name, enhancer) {
    enhancers.set(name, enhancer);
    if (!enhancedElements.has(name)) {
      enhancedElements.set(name, new WeakSet());
    }
  }

  /**
   * Apply every registered enhancer to *root* and its descendants.
   *
   * Idempotent: an element already upgraded by an enhancer is skipped, so the
   * same subtree may be enhanced again without duplicating listeners or UI.
   * A throwing enhancer is contained: the page and the other features survive.
   *
   * @param {Document | Element} [root]
   * @returns {void}
   */
  function enhance(root = document) {
    for (const [name, enhancer] of enhancers) {
      const seen = enhancedElements.get(name);
      if (seen === undefined) {
        continue;
      }
      /** @type {Element[]} */
      const targets = [];
      if (root instanceof Element && root.matches(enhancer.selector)) {
        targets.push(root);
      }
      for (const element of root.querySelectorAll(enhancer.selector)) {
        targets.push(element);
      }
      for (const element of targets) {
        if (seen.has(element)) {
          continue;
        }
        seen.add(element);
        try {
          enhancer.apply(element);
        } catch {
          // One broken feature must not take the page or the other features down.
        }
      }
    }
  }

  /**
   * Mark the heading the reader is looking at in the page TOC.
   *
   * Progressive enhancement: without IntersectionObserver, or without a TOC,
   * the sidebar stays a plain list of links, which is the whole contract.
   *
   * @param {Element} toc
   * @returns {void}
   */
  function enhanceTocScrollspy(toc) {
    if (typeof IntersectionObserver !== "function") {
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

  /**
   * Wire the banner light/dark button.
   *
   * A theme may ship its own banner without the toggle; everything else still
   * works, so a non-button element is simply ignored.
   *
   * @param {Element} element
   * @returns {void}
   */
  function enhanceThemeToggle(element) {
    if (!(element instanceof HTMLButtonElement)) {
      return;
    }

    syncToggle(element);

    element.addEventListener("click", () => {
      const next = effectiveTheme() === "dark" ? "light" : "dark";
      applyTheme(next);
      storeTheme(next);
      syncToggle(element);
    });

    if (window.matchMedia) {
      // Only the reported state needs updating; the palette follows the media query.
      window.matchMedia(DARK_QUERY).addEventListener("change", () => {
        if (readStoredTheme() === null) {
          syncToggle(element);
        }
      });
    }
  }

  /**
   * Absolutize a single ``href``／``src`` value against *pageUrl*.
   *
   * Mirrors Python ``absolutize_url``: ``mailto``／``tel``／``data`` and existing
   * absolute ``http``／``https`` URLs are left unchanged; fragment-only hashes
   * stay as-is; everything else is resolved with ``new URL``.
   *
   * @param {string} url
   * @param {string} pageUrl
   * @returns {string}
   */
  function absolutizeUrl(url, pageUrl) {
    if (url === "") {
      return url;
    }
    if (url.startsWith("#")) {
      return url;
    }
    const colon = url.indexOf(":");
    if (colon !== -1) {
      const scheme = url.slice(0, colon).toLowerCase();
      if (scheme === "mailto" || scheme === "tel" || scheme === "data") {
        return url;
      }
      if (scheme === "http" || scheme === "https") {
        return url;
      }
      // Unknown schemes (javascript:, etc.): leave unchanged.
      return url;
    }
    try {
      return new URL(url, pageUrl).href;
    } catch {
      return url;
    }
  }

  /**
   * Rewrite relative ``href``／``src`` on *root* and its descendants.
   *
   * After ``document.importNode``, attribute values still resolve against the
   * *current* document when clicked; *pageUrl* is the fetched archive page.
   *
   * @param {Node} root
   * @param {string} pageUrl
   * @returns {void}
   */
  function rewriteImportedUrls(root, pageUrl) {
    if (!(root instanceof Element)) {
      return;
    }
    /** @type {Element[]} */
    const elements = [];
    if (root.hasAttribute("href") || root.hasAttribute("src")) {
      elements.push(root);
    }
    elements.push(...root.querySelectorAll("[href], [src]"));
    for (const element of elements) {
      const href = element.getAttribute("href");
      if (href !== null) {
        element.setAttribute("href", absolutizeUrl(href, pageUrl));
      }
      const src = element.getAttribute("src");
      if (src !== null) {
        element.setAttribute("src", absolutizeUrl(src, pageUrl));
      }
    }
  }

  /**
   * Absolute, same-origin URL of the next archive page, or null.
   *
   * ``rel="next"`` also sits on ``.maatlog-pagination-more``; the class is the
   * key, not the relation.
   *
   * Resolves the raw ``href`` attribute against *baseUrl* rather than reading
   * the anchor's resolved ``.href`` property. Once pagination markup fetched
   * from a nested archive page (e.g. ``blog/page/2.html``) is imported into
   * *this* document (see ``adoptPagination``), ``document.importNode`` gives
   * the anchor a new owner document, so ``.href`` would silently resolve a
   * relative link like ``3.html`` against the wrong page and 404.
   *
   * @param {Element} nav
   * @param {string} [baseUrl] The page *nav* itself was rendered on.
   * @returns {string | null}
   */
  function paginationNextUrl(nav, baseUrl = window.location.href) {
    const link = nav.querySelector(".maatlog-pagination-next");
    const href = link instanceof HTMLAnchorElement ? link.getAttribute("href") : null;
    if (href === null) {
      return null;
    }
    let url;
    try {
      url = new URL(href, baseUrl);
    } catch {
      return null;
    }
    return url.origin === window.location.origin ? url.href : null;
  }

  /**
   * Append the next archive page as the reader approaches the end of the list.
   *
   * Progressive enhancement: the static pagination is never removed. Without
   * IntersectionObserver, without fetch, or without a next link, the archive
   * stays exactly the page Sphinx generated.
   *
   * @param {Element} archive
   * @returns {void}
   */
  function enhanceInfiniteScroll(archive) {
    if (typeof IntersectionObserver !== "function" || typeof window.fetch !== "function") {
      return;
    }
    const postList = archive.querySelector(".maatlog-post-list");
    const nav = archive.querySelector('[data-maatlog-component="pagination"]');
    if (!(postList instanceof HTMLElement) || !(nav instanceof HTMLElement)) {
      return;
    }
    let nextUrl = paginationNextUrl(nav);
    if (nextUrl === null) {
      return;
    }

    // JS が作るので、JavaScript 無効時には痕跡が残らない。
    const status = document.createElement("p");
    status.className = "maatlog-infinite-status maatlog-visually-hidden";
    status.setAttribute("role", "status");
    status.setAttribute("aria-live", "polite");
    postList.after(status);

    const sentinel = document.createElement("div");
    sentinel.className = "maatlog-infinite-sentinel";
    sentinel.setAttribute("aria-hidden", "true");
    status.after(sentinel);

    /** Absolute URLs already requested; the same page is never fetched twice. */
    const loadedUrls = new Set();
    let loading = false;

    // Keep this in sync with the observer's rootMargin below: it is also used
    // to re-check the sentinel after a load completes (see loadNextPage).
    const ROOT_MARGIN_PX = 400;

    /**
     * Whether the sentinel still sits inside the rootMargin-expanded viewport.
     *
     * @returns {boolean}
     */
    const sentinelWithinRootMargin = () => {
      const rect = sentinel.getBoundingClientRect();
      const viewportHeight = window.innerHeight || document.documentElement.clientHeight;
      return rect.top < viewportHeight + ROOT_MARGIN_PX && rect.bottom > -ROOT_MARGIN_PX;
    };

    const observer = new IntersectionObserver(
      (entries) => {
        if (loading || !entries.some((entry) => entry.isIntersecting)) {
          return;
        }
        void loadNextPage();
      },
      { rootMargin: `${ROOT_MARGIN_PX}px 0px` },
    );
    observer.observe(sentinel);

    /**
     * Stop auto-loading. The pagination is deliberately left untouched so the
     * reader can always keep going by hand.
     *
     * @returns {void}
     */
    const stop = () => {
      observer.disconnect();
      sentinel.remove();
    };

    /**
     * The single grid every page's cards share, created when page one had none.
     *
     * @returns {Element}
     */
    const postGrid = () => {
      const existing = postList.querySelector(".maatlog-post-grid");
      if (existing !== null) {
        return existing;
      }
      const created = document.createElement("div");
      created.className = "maatlog-post-grid";
      postList.append(created);
      return created;
    };

    /**
     * Move the cards of *doc* into the current grid, skipping duplicates.
     *
     * @param {Document} doc
     * @param {string} pageUrl The fetched archive page URL.
     * @returns {Element[]} the nodes now living in this document.
     */
    const appendCards = (doc, pageUrl) => {
      /** @type {Element[]} */
      const appended = [];
      for (const card of doc.querySelectorAll(".maatlog-post-list .maatlog-post-card")) {
        // featured は archive root の 1 ページ目にしか出ないが、混ざれば列が乱れる。
        if (card.closest(".maatlog-post-featured") !== null) {
          continue;
        }
        // 同じ id が二つあると HTML として壊れ、アンカーも曖昧になる。
        if (card.id !== "" && document.getElementById(card.id) !== null) {
          continue;
        }
        const node = document.importNode(card, true);
        rewriteImportedUrls(node, pageUrl);
        appended.push(postGrid().appendChild(node));
      }
      return appended;
    };

    /**
     * Adopt the fetched page's pagination so current/prev/next stay coherent.
     *
     * The markup is this theme's own nav (anchors and spans); DOMParser does
     * not run scripts and none appear in that component.
     *
     * @param {Document} doc
     * @param {string} pageUrl The fetched archive page URL.
     * @returns {void}
     */
    const adoptPagination = (doc, pageUrl) => {
      const source = doc.querySelector('[data-maatlog-component="pagination"]');
      if (source === null) {
        for (const link of nav.querySelectorAll(".maatlog-pagination-next, .maatlog-pagination-more")) {
          link.remove();
        }
        return;
      }
      nav.textContent = "";
      for (const child of Array.from(source.childNodes)) {
        const node = document.importNode(child, true);
        rewriteImportedUrls(node, pageUrl);
        nav.append(node);
      }
    };

    /** @returns {Promise<void>} */
    const loadNextPage = async () => {
      const url = nextUrl;
      if (url === null || loadedUrls.has(url)) {
        stop();
        return;
      }
      loading = true;
      loadedUrls.add(url);
      try {
        const response = await fetch(url, { credentials: "same-origin" });
        if (!response.ok) {
          throw new Error(`unexpected status ${response.status}`);
        }
        const doc = new DOMParser().parseFromString(await response.text(), "text/html");
        const appended = appendCards(doc, url);
        if (appended.length === 0) {
          stop();
          return;
        }
        for (const card of appended) {
          enhance(card);
        }
        adoptPagination(doc, url);
        // *url* (not window.location.href): the adopted nav's anchors are relative
        // to the page we just fetched, not to this document.
        nextUrl = paginationNextUrl(nav, url);
        archive.dispatchEvent(
          new CustomEvent("maatlog:content-added", {
            bubbles: true,
            detail: { cards: appended, url },
          }),
        );
        const noun = appended.length === 1 ? "post" : "posts";
        status.textContent = `${appended.length} ${noun} loaded`;
        if (nextUrl === null) {
          stop();
        }
      } catch {
        // 自動読み込みだけを諦める。pagination は無傷なので読者は Next で進める。
        stop();
      } finally {
        loading = false;
      }

      // Short pages (or a generous rootMargin) can leave the sentinel
      // continuously intersecting after this append: IntersectionObserver only
      // fires on a change of intersection state, so nothing would otherwise
      // trigger the next load. One rAF later — after layout has settled — check
      // manually and keep going while the sentinel is still within rootMargin.
      requestAnimationFrame(() => {
        if (!loading && nextUrl !== null && sentinel.isConnected && sentinelWithinRootMargin()) {
          void loadNextPage();
        }
      });
    };
  }

  /** Absolute URLs already handed to ``<link rel="prefetch">``. */
  const prefetchedUrls = new Set();

  /**
   * Whether the reader asked us not to spend bandwidth on speculation.
   *
   * Network Information API is Chromium-only; missing ``connection`` must not
   * throw — Prefetch simply stays enabled.
   *
   * @returns {boolean}
   */
  function shouldSuppressPrefetch() {
    try {
      // Network Information API is Chromium-only. Read via Reflect so Safari
      // browserslist checks do not treat ``navigator.connection`` as required.
      const connection = /** @type {{ saveData?: boolean, effectiveType?: string } | undefined} */ (
        Reflect.get(navigator, "connection")
      );
      if (connection === undefined) {
        return false;
      }
      if (connection.saveData === true) {
        return true;
      }
      const type = connection.effectiveType;
      return type === "slow-2g" || type === "2g";
    } catch {
      return false;
    }
  }

  /**
   * Decide whether *href* is a same-origin document worth prefetching.
   *
   * Planner only: keeps URL policy separate from how we actually fetch so a
   * future Speculation Rules backend can reuse the same decisions.
   *
   * @param {string} href
   * @param {string} [baseUrl]
   * @returns {string | null} absolute URL, or null when excluded
   */
  function planPrefetchUrl(href, baseUrl = window.location.href) {
    if (typeof href !== "string") {
      return null;
    }
    const trimmed = href.trim();
    if (trimmed === "") {
      return null;
    }
    const lower = trimmed.toLowerCase();
    if (
      lower.startsWith("mailto:") ||
      lower.startsWith("tel:") ||
      lower.startsWith("javascript:") ||
      lower.startsWith("data:")
    ) {
      return null;
    }
    /** @type {URL} */
    let url;
    try {
      url = new URL(trimmed, baseUrl);
    } catch {
      return null;
    }
    if (url.protocol !== "http:" && url.protocol !== "https:") {
      return null;
    }
    if (url.origin !== window.location.origin) {
      return null;
    }
    // Current document and hash-only in-page links stay out.
    const current = new URL(window.location.href);
    if (url.pathname === current.pathname && url.search === current.search) {
      return null;
    }
    return url.href;
  }

  /**
   * Inject one ``<link rel="prefetch">`` for *url* when allowed.
   *
   * Fetcher only: never throws into the page. Duplicate URLs are ignored.
   *
   * @param {string | null} url
   * @returns {void}
   */
  function fetchPrefetch(url) {
    if (url === null || shouldSuppressPrefetch() || prefetchedUrls.has(url)) {
      return;
    }
    prefetchedUrls.add(url);
    try {
      const link = document.createElement("link");
      link.rel = "prefetch";
      link.as = "document";
      link.href = url;
      document.head.append(link);
    } catch {
      // Prefetch must never take ordinary navigation down.
    }
  }

  /**
   * Prefetch high-confidence targets that already appear in the markup.
   *
   * @param {ParentNode} root
   * @returns {void}
   */
  function prefetchAutomaticTargets(root) {
    for (const selector of [".maatlog-nav-newer", ".maatlog-nav-older", ".maatlog-pagination-next"]) {
      for (const node of root.querySelectorAll(selector)) {
        if (!(node instanceof HTMLAnchorElement) || node.hasAttribute("download")) {
          continue;
        }
        fetchPrefetch(planPrefetchUrl(node.href));
      }
    }
  }

  /**
   * Intent-based Prefetch: the reader hovered or focused an internal link.
   *
   * @param {Event} event
   * @returns {void}
   */
  function onPrefetchIntent(event) {
    const target = event.target;
    if (!(target instanceof Element)) {
      return;
    }
    const anchor = target.closest("a[href]");
    if (!(anchor instanceof HTMLAnchorElement) || anchor.hasAttribute("download")) {
      return;
    }
    fetchPrefetch(planPrefetchUrl(anchor.href));
  }

  /**
   * Conservative page Prefetch for the document.
   *
   * Progressive enhancement: Save-Data / missing APIs / failed inserts leave
   * ordinary ``<a href>`` navigation untouched.
   *
   * @param {Element} root
   * @returns {void}
   */
  function enhancePrefetch(root) {
    prefetchAutomaticTargets(root);

    document.addEventListener("mouseenter", onPrefetchIntent, true);
    document.addEventListener("focusin", onPrefetchIntent);

    // Infinite Scroll replaces ``.maatlog-pagination-next``; pick up the new URL.
    document.addEventListener("maatlog:content-added", () => {
      prefetchAutomaticTargets(document);
    });
  }

  registerEnhancer("toc-scrollspy", {
    selector: ".maatlog-toc-headings",
    apply: enhanceTocScrollspy,
  });
  registerEnhancer("theme-toggle", {
    selector: ".maatlog-theme-toggle",
    apply: enhanceThemeToggle,
  });
  registerEnhancer("infinite-scroll", {
    selector: '[data-maatlog-component="archive"]',
    apply: enhanceInfiniteScroll,
  });
  registerEnhancer("prefetch", {
    selector: "html",
    apply: enhancePrefetch,
  });

  // ---------------------------------------------------------------------------
  // NEW badge — Issue #62
  // ---------------------------------------------------------------------------

  /**
   * Determine the session's "previous visit" baseline once, then persist the
   * current visit so the *next* session can use it.
   *
   * The baseline is fixed for the whole session so navigating between pages
   * does not cause NEW badges to disappear mid-session.
   *
   * Storage layout:
   *   localStorage["maatlog:last-visit"]  — ISO 8601 timestamp of last visit
   *   sessionStorage["maatlog:session-baseline"] — ISO 8601 of this session's start
   *
   * Either storage may be unavailable (private windows, browser settings).
   * All access is wrapped in try/catch; failures silently skip NEW display.
   *
   * @returns {Date | null} baseline date for NEW comparison, or null when not applicable
   */
  function resolveNewBadgeBaseline() {
    const LAST_VISIT_KEY = "maatlog:last-visit";
    const SESSION_KEY = "maatlog:session-baseline";

    try {
      // Already resolved in this session?
      const cached = sessionStorage.getItem(SESSION_KEY);
      if (cached !== null) {
        const d = new Date(cached);
        return isNaN(d.getTime()) ? null : d;
      }
    } catch {
      // sessionStorage unavailable; fall through to in-memory path below.
    }

    /** @type {Date | null} */
    let baseline = null;

    try {
      const stored = localStorage.getItem(LAST_VISIT_KEY);
      if (stored !== null) {
        const d = new Date(stored);
        if (!isNaN(d.getTime())) {
          baseline = d;
        }
      }
      // Update last-visit to now for the *next* session.
      localStorage.setItem(LAST_VISIT_KEY, new Date().toISOString());
    } catch {
      // localStorage unavailable — no baseline, no NEW display.
      return null;
    }

    // Cache in sessionStorage so page navigations reuse the same baseline.
    try {
      if (baseline !== null) {
        sessionStorage.setItem(SESSION_KEY, baseline.toISOString());
      }
    } catch {
      // sessionStorage unavailable; still use the in-memory baseline for this enhancer call.
    }

    return baseline;
  }

  // Resolve once at runtime-load time so Infinite Scroll appends share the same baseline.
  const _newBadgeBaseline = resolveNewBadgeBaseline();

  /**
   * Stamp a ``NEW`` badge on a post card when its published_at is after the
   * session's previous-visit baseline.
   *
   * Idempotent: a card that already has a badge is left unchanged.
   *
   * @param {Element} card
   * @returns {void}
   */
  function enhanceNewBadge(card) {
    if (_newBadgeBaseline === null) {
      return;
    }
    const raw = card.getAttribute("data-maatlog-published-at");
    if (raw === null) {
      return;
    }
    const publishedAt = new Date(raw);
    if (isNaN(publishedAt.getTime())) {
      return;
    }
    if (publishedAt > _newBadgeBaseline) {
      // Guard: skip if badge was already inserted (idempotency).
      if (card.querySelector(".maatlog-new-badge") !== null) {
        return;
      }
      const badge = document.createElement("span");
      badge.className = "maatlog-new-badge";
      badge.setAttribute("aria-label", "New post");
      badge.textContent = "NEW";
      // Insert before the title so it's announced first by screen readers.
      const title = card.querySelector(".maatlog-post-card-title");
      if (title !== null) {
        card.insertBefore(badge, title);
      } else {
        card.prepend(badge);
      }
    }
  }

  registerEnhancer("new-posts", {
    selector: ".maatlog-post-card[data-maatlog-published-at]",
    apply: enhanceNewBadge,
  });

  document.documentElement.classList.add("maatlog-js");
  applyTheme(readStoredTheme());

  // Features registered by other scripts would go through the same registry;
  // the theme itself ships exactly one runtime file (see tmp/FRONTEND.md).
  // Public API: window.maatlog.registerEnhancer, window.maatlog.enhance.
  const globalScope = /** @type {typeof window & { maatlog?: Record<string, unknown> }} */ (window);
  globalScope.maatlog = Object.assign(globalScope.maatlog ?? {}, { registerEnhancer, enhance });

  document.addEventListener("DOMContentLoaded", () => {
    enhance(document);
  });
})();
