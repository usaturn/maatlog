"""Immutable social metadata values for templates."""

import json
from dataclasses import dataclass
from typing import cast

from .serialization import serialize_json_ld


@dataclass(frozen=True, slots=True)
class OpenGraphPropertyView:
    property: str
    content: str


@dataclass(frozen=True, slots=True)
class TwitterCardPropertyView:
    name: str
    content: str


#: Characters that must not reach a ``<script>`` element raw: ``<`` / ``>`` could end
#: the element, ``&`` could start an entity, and U+2028 / U+2029 are raw JavaScript line
#: terminators. :func:`maatlog.social_metadata.serialize_json_ld` escapes exactly these.
_SCRIPT_UNSAFE_CHARACTERS = ("<", ">", "&", "\u2028", "\u2029")


@dataclass(frozen=True, slots=True)
class SocialMetadataView:
    open_graph: tuple[OpenGraphPropertyView, ...] = ()
    twitter: tuple[TwitterCardPropertyView, ...] = ()
    #: Only the return value of :func:`maatlog.social_metadata.serialize_json_ld` may be
    #: assigned: the shared partial renders it with ``|safe``, so an unescaped string
    #: would inject markup. ``__post_init__`` enforces that by re-serializing the parsed
    #: value and requiring it to match the input byte for byte, so a string produced by
    #: any other route — plain ``json.dumps()``, hand-written JSON, a non-JSON sentinel —
    #: is rejected.
    json_ld: str | None = None

    def __post_init__(self) -> None:
        if self.json_ld is None:
            return
        unsafe = [character for character in _SCRIPT_UNSAFE_CHARACTERS if character in self.json_ld]
        if unsafe:
            # Reported before the round-trip check so the diagnostic names the characters
            # that would have escaped the <script> element, not just "not serializer output".
            found = " ".join(f"U+{ord(character):04X}" for character in unsafe)
            msg = (
                f"json_ld contains characters that are unsafe inside <script>: {found}. "
                "Assign the return value of maatlog.social_metadata.serialize_json_ld() instead."
            )
            raise ValueError(msg)
        try:
            parsed: object = json.loads(self.json_ld)
        except ValueError:
            raise self._not_serializer_output("it is not valid JSON") from None
        if not isinstance(parsed, dict):
            raise self._not_serializer_output("it is not a JSON object")
        # ``json.loads`` always produces ``str`` keys for a JSON object, which ``isinstance``
        # alone cannot express.
        if serialize_json_ld(cast(dict[str, object], parsed)) != self.json_ld:
            raise self._not_serializer_output("re-serializing it does not reproduce the value")

    @staticmethod
    def _not_serializer_output(reason: str) -> ValueError:
        return ValueError(
            f"json_ld is not the output of maatlog.social_metadata.serialize_json_ld(): {reason}. "
            "Assign the return value of maatlog.social_metadata.serialize_json_ld() instead."
        )
