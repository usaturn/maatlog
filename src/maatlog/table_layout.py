"""Build-time scroll wrapper for docutils tables (Theme API 1.19).

Full-HTML builders (``html`` / ``dirhtml``) emit
``<div class="maatlog-table-wrapper" tabindex="0">`` around every docutils
``table`` node so themes can separate horizontal scrolling from native table
layout. The wrapper is a post-transform: pickled doctrees stay untouched, so
incremental and parallel builds re-apply it from scratch on every write.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

from docutils import nodes
from sphinx.transforms.post_transforms import SphinxPostTransform

from .builders import FULL_HTML_BUILDERS

if TYPE_CHECKING:
    from sphinx.application import Sphinx
    from sphinx.writers.html5 import HTML5Translator

WRAPPER_CLASS: Final = "maatlog-table-wrapper"


class table_wrapper_node(nodes.General, nodes.Element):
    """Scroll container emitted around docutils tables in full-HTML builds."""


def html_visit_table_wrapper(self: HTML5Translator, node: table_wrapper_node) -> None:
    # starttag は属性をアルファベット順に出力する: class → tabindex。
    # pyright strict: docutils の starttag は **attributes を Unknown と型付けしている。
    self.body.append(
        self.starttag(  # type: ignore[reportUnknownMemberType]
            node, "div", CLASS=WRAPPER_CLASS, tabindex="0"
        )
    )


def html_depart_table_wrapper(self: HTML5Translator, node: table_wrapper_node) -> None:
    self.body.append("</div>\n")


class TableWrapperPostTransform(SphinxPostTransform):
    """Wrap each ``nodes.table`` in a ``table_wrapper_node``, exactly once.

    The declarative ``builders`` gate keeps non-full-HTML builders (singlehtml,
    text, latex, ...) untouched and avoids the deprecated ``SphinxTransform.app``
    property (removed in Sphinx 11).
    """

    builders = FULL_HTML_BUILDERS
    # ReferencesResolver (priority 10) 等の参照解決より後。xref が解決した後に
    # 包むため、:name: / numref のアンカーは <table> 側の id に残ったまま。
    default_priority = 500

    def run(self, **kwargs: Any) -> None:
        # findall のジェネレータを materialize してから置換する（反復中の木変更回避）。
        for table in list(self.document.findall(nodes.table)):
            if isinstance(table.parent, table_wrapper_node):
                continue  # 冪等性ガード: 包み済みの表を二度包まない
            wrapper = table_wrapper_node()
            table.replace_self(wrapper)
            # replace_self は table の基本属性（ids/classes/names/dupnames）を
            # コピーで wrapper へ引き継ぐ（docutils 0.22 の仕様）。wrapper は
            # スクロール容器のため、表側の id・class は担わせず table に残す。
            for attr in ("ids", "classes", "names", "dupnames"):
                wrapper[attr] = []
            wrapper.append(table)


def setup_table_layout(app: Sphinx) -> None:
    """Register the wrapper node and its post-transform.

    Visitors are registered for ``html`` only: the builder gate guarantees the
    node never reaches other formats, so pass-through visitors would be dead
    code. ``html`` covers both ``html`` and ``dirhtml`` (shared HTML5Translator).
    """
    app.add_node(
        table_wrapper_node,
        html=(html_visit_table_wrapper, html_depart_table_wrapper),
    )
    app.add_post_transform(TableWrapperPostTransform)
