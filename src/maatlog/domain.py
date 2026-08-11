from collections.abc import Collection, Iterable, Mapping, Set
from datetime import datetime
from typing import Any, cast

from docutils import nodes
from docutils.nodes import Element
from sphinx.addnodes import pending_xref
from sphinx.builders import Builder
from sphinx.domains import Domain, ObjType
from sphinx.environment import BuildEnvironment
from sphinx.util.nodes import make_refnode

from .archives import check_generated_docnames, project_archives
from .config import MaatlogConfig
from .directives import PostListDirective
from .errors import Diagnostic, MaatlogBuildError
from .model import Post, publication_status
from .references import (
    ROLE_TYPES,
    MaatlogXRefRole,
    ResolvedReference,
    is_html_archive_builder,
    iter_inventory_objects,
    lookup_reference,
)
from .taxonomy import DomainIndex, build_domain_index


class MaatlogDomain(Domain):
    name = "maatlog"
    label = "MaatLog"
    object_types = {
        "post": ObjType("post", "post"),
        "tag": ObjType("tag", "tag"),
        "category": ObjType("category", "category"),
        "author": ObjType("author", "author"),
        "month": ObjType("month", "month"),
    }
    roles = {name: MaatlogXRefRole() for name in ROLE_TYPES}
    directives = {
        "post-list": PostListDirective,
    }
    initial_data = {
        "posts_by_docname": {},
        "index": None,
        "generated_docnames": set(),
        # Independent ownership manifests; page cleanup must never touch feeds.
        "generated_outputs": {"pages": set(), "feeds": set()},
    }

    def note_post(self, post: Post) -> None:
        posts = cast(dict[str, Post], self.data["posts_by_docname"])
        posts[post.docname] = post
        self._invalidate_index()

    def clear_doc(self, docname: str) -> None:
        posts = cast(dict[str, Post], self.data["posts_by_docname"])
        posts.pop(docname, None)
        self._invalidate_index()

    def merge(self, other_data: Mapping[str, Any], docnames: Collection[str]) -> None:
        posts = cast(dict[str, Post], self.data["posts_by_docname"])
        other_posts = cast(dict[str, Post], other_data.get("posts_by_docname", {}))
        diagnostics: list[Diagnostic] = []

        for docname in sorted(docnames):
            if docname not in other_posts:
                continue
            incoming = other_posts[docname]
            existing = posts.get(docname)
            if existing is not None and existing != incoming:
                diagnostics.append(
                    Diagnostic(
                        code="maatlog.domain.merge-conflict",
                        message=f"Conflicting post data for docname {docname!r}",
                        source=incoming.source_path,
                        field="docname",
                        value=repr(docname),
                        expected="identical Post values across workers for the same docname",
                    )
                )
                continue
            posts[docname] = incoming

        if diagnostics:
            raise MaatlogBuildError(diagnostics)
        self._invalidate_index()

    def merge_domaindata(self, docnames: Set[str], otherdata: dict[str, Any]) -> None:
        self.merge(otherdata, docnames)

    def rebuild_index(
        self,
        config: MaatlogConfig,
        *,
        build_time: datetime | None = None,
    ) -> DomainIndex:
        posts = cast(dict[str, Post], self.data["posts_by_docname"])
        if build_time is not None:
            refreshed: dict[str, Post] = {}
            for docname, post in posts.items():
                status = publication_status(post.published_at, post.expires_at, build_time)
                if status is post.status:
                    refreshed[docname] = post
                else:
                    refreshed[docname] = post.model_copy(update={"status": status})
            self.data["posts_by_docname"] = refreshed
            posts = refreshed
        index = build_domain_index(posts, config)
        self.data["index"] = index
        return index

    def finalize(
        self,
        config: MaatlogConfig,
        *,
        build_time: datetime,
        known_docnames: Collection[str],
    ) -> DomainIndex:
        """Recompute publication status, rebuild the index, and lock archive docnames."""
        index = self.rebuild_index(config, build_time=build_time)
        pages = project_archives(
            index,
            root=config.archive_docname,
            page_size=config.page_size,
            timezone=config.timezone,
        )
        generated = tuple(page.docname for page in pages)
        check_generated_docnames(generated, known_docnames=known_docnames)
        self.data["generated_docnames"] = set(generated)
        return index

    def published_posts(self) -> tuple[Post, ...]:
        index = cast(DomainIndex | None, self.data.get("index"))
        if index is None:
            return ()
        return index.published

    def lookup(self, typ: str, target: str) -> ResolvedReference | None:
        posts = cast(dict[str, Post], self.data["posts_by_docname"])
        index = cast(DomainIndex | None, self.data.get("index"))
        archive_root = cast(str, self.env.config.maatlog_archive_docname)
        return lookup_reference(
            typ=typ,
            target=target,
            index=index,
            posts_by_docname=posts,
            archive_root=archive_root,
        )

    def resolve_xref(
        self,
        env: BuildEnvironment,
        fromdocname: str,
        builder: Builder,
        typ: str,
        target: str,
        node: pending_xref,
        contnode: Element,
    ) -> nodes.reference | None:
        del env
        resolved = self.lookup(typ, target)
        if resolved is None:
            return None
        if typ != "post" and not is_html_archive_builder(builder):
            text = contnode.astext() if node.get("refexplicit") else resolved.label
            # Sphinx replaces pending_xref with any Element; stubs list reference only.
            return cast(nodes.reference, nodes.inline("", text))
        return make_refnode(
            builder,
            fromdocname,
            resolved.docname,
            resolved.anchor or None,
            contnode,
            resolved.label,
        )

    def resolve_any_xref(
        self,
        env: BuildEnvironment,
        fromdocname: str,
        builder: Builder,
        target: str,
        node: pending_xref,
        contnode: Element,
    ) -> list[tuple[str, nodes.reference]]:
        results: list[tuple[str, nodes.reference]] = []
        for typ in ROLE_TYPES:
            ref = self.resolve_xref(env, fromdocname, builder, typ, target, node, contnode)
            if isinstance(ref, nodes.reference):
                results.append((f"{self.name}:{typ}", ref))
        return results

    def get_objects(self) -> Iterable[tuple[str, str, str, str, str, int]]:
        index = cast(DomainIndex | None, self.data.get("index"))
        archive_root = cast(str, self.env.config.maatlog_archive_docname)
        return iter_inventory_objects(index=index, archive_root=archive_root)

    def _invalidate_index(self) -> None:
        self.data["index"] = None
