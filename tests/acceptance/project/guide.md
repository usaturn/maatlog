# Authoring guide

This normal MyST document coexists with posts and autodoc pages.

## Links into the site

- Index: {doc}`index`
- API: {doc}`api`
- Python function: {py:func}`api.greet`
- Post: {maatlog:post}`md-post`
- Tag archive: {maatlog:tag}`sphinx`
- Category archive: {maatlog:category}`engineering`
- Author archive: {maatlog:author}`alice`
- Month archive: {maatlog:month}`2026-08`

## Notes

Posts may be authored in reStructuredText or MyST with equivalent metadata.

## Code

Highlighted code is the one surface whose colours come from Pygments rather
than the theme tokens, so the acceptance site needs a block to render.

```python
def greet(name: str) -> str:
    return f"Hello, {name}"
```

## Reference table

| Option | Type | Default | Description |
| --- | --- | --- | --- |
| `maatlog_timezone` | `str` | `"UTC"` | Build-time timezone for publication boundaries. |
| `maatlog_tags` | `dict[str, str]` | `{}` | Tag identifier to display label. |
| `maatlog_categories` | `dict[str, str]` | `{}` | Category identifier to display label. |
| `maatlog_authors` | `dict[str, str]` | `{}` | Author identifier to display label. |

## Quoted guidance

> A theme that renders documentation well does not automatically render a blog
> well. The reading posture is different.

```{note}
Design tokens are the contract. Components read them; they never hard-code a colour.
```

```{warning}
Changing a token name is a breaking change for every theme that inherits the base.
```
