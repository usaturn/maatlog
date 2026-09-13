"""Template-facing social metadata views.

``maatlog.views`` imports this package at runtime to give every page an empty
:class:`SocialMetadataView`. Projectors in this package must therefore keep
``MaatlogTemplateContext`` behind ``TYPE_CHECKING`` and must not import
``maatlog.views`` at runtime: doing so closes the import cycle and breaks the build.
"""

from .dispatcher import project_social_metadata
from .serialization import serialize_json_ld
from .views import OpenGraphPropertyView, SocialMetadataView, TwitterCardPropertyView

__all__ = [
    "OpenGraphPropertyView",
    "SocialMetadataView",
    "TwitterCardPropertyView",
    "serialize_json_ld",
    "project_social_metadata",
]
