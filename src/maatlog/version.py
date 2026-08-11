"""Single package-version source for extension and generated metadata."""

from importlib.metadata import version as distribution_version

PACKAGE_VERSION: str = distribution_version("maatlog")
