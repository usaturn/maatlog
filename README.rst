MaatLog
=======

MaatLog is a Sphinx extension that turns a documentation project into a static
blog. Posts are ordinary reStructuredText or MyST Markdown documents with a
small metadata schema. MaatLog adds archives, taxonomy navigation, Atom feeds,
and an HTML Theme API on top of Sphinx's public extension surface.

Requirements
------------

* Python 3.14+
* Sphinx 9.1+
* myst-parser 5.1+

Install
-------

From a built distribution (wheel or sdist)::

    pip install maatlog

Or from a checkout with `uv`::

    uv sync
    uv pip install -e .

Quick start
-----------

1. Enable the extension and (optionally) the bundled theme in ``conf.py``::

    extensions = ["maatlog"]

    html_theme = "maatlog-default"
    html_baseurl = "https://example.com/"  # required when Atom feeds are enabled

    maatlog_timezone = "UTC"
    maatlog_tags = {"sphinx": "Sphinx", "python": "Python"}
    maatlog_categories = {"engineering": "Engineering"}
    maatlog_authors = {"alice": "Alice"}

2. Write a reStructuredText post (field list before the title)::

    :maatlog-post: true
    :maatlog-published-at: 2026-08-01T09:00:00+09:00
    :maatlog-slug: hello-maatlog
    :maatlog-tags: sphinx, python
    :maatlog-categories: engineering
    :maatlog-authors: alice
    :maatlog-excerpt: First post with MaatLog.

    Hello MaatLog
    =============

    Body of the post…

3. Or an equivalent MyST Markdown post (YAML front matter)::

    ---
    maatlog-post: true
    maatlog-published-at: 2026-08-01T09:00:00+09:00
    maatlog-slug: hello-maatlog
    maatlog-tags: [sphinx, python]
    maatlog-categories: [engineering]
    maatlog-authors: [alice]
    maatlog-excerpt: First post with MaatLog.
    ---

    # Hello MaatLog

    Body of the post…

4. Build HTML::

    sphinx-build -b html sourcedir builddir

With the defaults above, MaatLog generates:

* Post pages using the selected MaatLog theme
* Archives under ``blog/`` (configurable via ``maatlog_archive_docname``)
* Atom feeds under the archive root (when ``maatlog_generate_feeds`` is true)
* Cross-reference roles such as ``:maatlog:post:``, ``:maatlog:tag:``, and friends

Rebuild notes
-------------

Most ``maatlog_*`` settings rebuild the Sphinx environment (``env``). Feed-related
settings rebuild HTML outputs only (``html``). After changing taxonomy
dictionaries, archive root, page size, timezone, or feed options, run a clean
or full rebuild so archives and feeds stay consistent.

``SOURCE_DATE_EPOCH`` (Unix seconds, UTC) freezes the build clock used for
draft / scheduled / expired publication status. Prefer it for reproducible CI
builds.

What MaatLog does not replace
-----------------------------

MaatLog does not replace Sphinx document titles, toctree, search, autodoc,
Pygments, or intersphinx. Ordinary documentation pages coexist with posts in
the same project. Full HTML features (archives, Theme API validation, feeds,
MaatLog HTML metadata) are guaranteed for the ``html`` and ``dirhtml`` builders
only; other builders keep post body and role resolution where applicable.

Documentation
-------------

* `docs/authoring.rst <docs/authoring.rst>`_ — post metadata schema and examples
* `docs/configuration.rst <docs/configuration.rst>`_ — conf.py settings and defaults
* `docs/theme-api.rst <docs/theme-api.rst>`_ — Theme API 1.0 contract and official themes
* `docs/builders.rst <docs/builders.rst>`_ — builder matrix and static-site constraints

Development
-----------

Node.js 24 is required only for contributor-side JavaScript and CSS quality
tooling. Installing and using the MaatLog Python package does not require
Node.js.

Official HTML and CSS support follows the ``browserslist`` query in
``package.json``. Long-tail browsers that still appear in ``defaults``
(Opera Mini, KaiOS 2.x, UC Browser, and QQ Browser) are out of scope.

Install both locked development environments and run the frontend checks::

    uv sync --locked --all-groups
    npm ci
    npm run check

The individual frontend commands are::

    npm run lint:js
    npm run format:check
    npm run typecheck:js
    npm run lint:css
    npm run format

The full verification profile runs browser-based accessibility tests, so
install the Playwright browser once before running it. On a system that also
needs the browser's OS packages, run the same command with ``--with-deps``
(it uses ``sudo``)::

    uv run playwright install chromium

The authoritative full repository verification remains::

    ./scripts/ci/verify.sh full

Verification profiles
---------------------

``scripts/ci/verify.sh <profile>`` is the single verification entry point. The
profiles differ in what they cover, not only in how long they take:

``static``
    The static checks: ``ruff check``, ``ruff format --check``, ``pyright``, and
    the frontend checks (``npm ci`` and ``npm run check``).

``quick``
    The Python static checks (``ruff check``, ``ruff format --check`` and
    ``pyright``; the frontend ``npm`` pair runs only in ``static`` and
    ``full``), then a single parallel run covering every non-browser test
    (``pytest -n auto --dist loadgroup -m "not browser"``). The distribution
    tests share that run: ``xdist_group`` keeps them on one worker, whose
    session fixture builds the archives once.

``full``
    The release gate: static checks, non-browser/non-distribution tests with
    ``-n auto --dist loadgroup``, browser/non-distribution tests with
    ``-n 2 --dist loadscope``, then one distribution build (``uv build``) and
    one serial distribution test run (including ``twine check``). These stages
    run in sequence. Browser tests include accessibility checks.

``minimum`` / ``latest``
    The Sphinx compatibility matrix that CI runs. These swap Sphinx versions
    with ``uv pip install``, so they rewrite the virtualenv.

``static`` and ``quick`` never run ``uv pip install``, so the virtualenv stays
exactly as ``uv sync`` left it and both profiles can be repeated freely while
developing. They also stop at the first failing static check, before the test
suite starts. ``full`` remains the authoritative check.

``full`` defaults to two browser workers. Set ``VERIFY_BROWSER_WORKERS`` to
an integer from 1 to 4 to override this; browser tests never use ``-n auto``.
The worker limit does not affect the non-browser or distribution stages::

    VERIFY_BROWSER_WORKERS=1 ./scripts/ci/verify.sh full

Test counts change as coverage evolves. Collect the current selection instead
of relying on a fixed count::

    uv run --no-sync pytest tests --collect-only -q
    uv run --no-sync pytest tests --collect-only -q -m 'not browser and not distribution'
    uv run --no-sync pytest tests --collect-only -q -m 'browser and not distribution'
    uv run --no-sync pytest tests --collect-only -q -m distribution

Wall time depends on CPU capacity, dependencies, cache state and the selected
revision. Compare the entire script on identical inputs and environment
conditions. Once log initialization succeeds, the script prints its log path
and records its final ``EXIT=`` status. Use a separate
``VERIFY_LOG_DIR`` for each measurement to preserve the logs.

License and status
------------------

MaatLog MVP targets Sphinx-based static blogs. Development is still active
and the published package has no known users. Until the project stabilizes,
Theme API updates are breaking and do not keep older Theme API versions
working. Public metadata keys, config names, roles, generated docname
rules, and diagnostic codes remain compatibility-managed surfaces.
