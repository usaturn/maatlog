extensions = ["maatlog", "myst_parser"]
source_suffix = {".rst": "restructuredtext", ".md": "markdown"}
root_doc = "index"
project = "Integration Blog"
html_theme = "maatlog-default"
html_baseurl = "https://example.test/docs/"
maatlog_timezone = "UTC"
maatlog_home_docname = "index"
maatlog_archive_docname = "blog"
maatlog_page_size = 1
maatlog_generate_feeds = True
maatlog_feed_taxonomies = ("tag", "category", "author", "month")
maatlog_tags = {"sphinx": "Sphinx", "python": "Python"}
maatlog_categories = {"engineering": "Engineering", "notes": "Notes"}
maatlog_authors = {"alice": "Alice Anderson", "bob": "Bob Builder"}
maatlog_author_profiles = {
    "alice": {
        "about_docname": "authors/alice",
        "avatar": "authors/alice.png",
        "bio_short": "Python developer.",
        "links": [{"type": "website", "url": "https://alice.example/about?from=maatlog#profile"}],
    }
}
exclude_patterns = ["**/__pycache__"]
