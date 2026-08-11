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

* `docs/authoring.rst` — post metadata schema and examples
* `docs/configuration.rst` — conf.py settings and defaults
* `docs/theme-api.rst` — Theme API 1.0 contract and official themes
* `docs/builders.rst` — builder matrix and static-site constraints

Development
-----------

Clone the repository, install the locked development environment, and run the
shared verification entrypoint::

    uv sync --locked --all-groups
    ./scripts/ci/verify.sh full

License and status
------------------

MaatLog MVP targets Sphinx-based static blogs. Public metadata keys, config
names, roles, the Theme API major version, generated docname rules, and
diagnostic codes are compatibility-managed surfaces.
